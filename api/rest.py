"""REST API (Layer 1): chat and conversation endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import binascii
import re
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from a2a.acl_message import ACLMessage, Performative
from a2a.conversation_manager import ConversationManager, ConversationState
from a2a.message_bus import InMemoryMessageBus, MessageBus
from api.websocket import handle_websocket as ws_handle_websocket
from safety.safety_gateway import SafetyError, SafetyGateway
from util.trace_log import trace
from util import interaction_log

logger = logging.getLogger(__name__)
VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


class ChatRequest(BaseModel):
    """POST /chat request body: query required; optional user_profile, user_id, conversation_id, path."""

    query: str
    user_profile: str = "beginner"
    user_id: str = ""
    conversation_id: Optional[str] = None
    path: Optional[str] = None

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("query is required and must be non-empty")
        return v.strip()

    @field_validator("user_profile")
    @classmethod
    def normalize_user_profile(cls, v: str) -> str:
        p = (v or "").strip().lower()
        if not p or p not in VALID_USER_PROFILES:
            raise ValueError(
                "user_profile must be one of: beginner, long_term, analyst"
            )
        return p

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("conversation_id")
    @classmethod
    def normalize_conversation_id(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class RegisterRequest(BaseModel):
    """POST /register body: create a user with password."""

    username: str = ""
    display_name: str = ""
    password: str = ""

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip() or "Guest"

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: Any) -> str:
        s = str(v or "").strip()
        if len(s) < 8:
            raise ValueError("password must be at least 8 characters")
        return s


class LoginRequest(BaseModel):
    """POST /login body: login existing user and preload memory."""

    username: str = ""
    user_id: str = ""
    password: str

    @field_validator("username")
    @classmethod
    def normalize_login_username(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("user_id")
    @classmethod
    def normalize_login_user_id(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("password")
    @classmethod
    def normalize_login_password(cls, v: Any) -> str:
        s = str(v or "")
        if not s:
            raise ValueError("password is required")
        return s


_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,31}$")


def _canonical_username(raw: Any) -> str:
    """Normalize username for storage and lookups."""
    return str(raw or "").strip().lower()


def _validate_new_username(raw: Any) -> str | None:
    """Validate username format for registration."""
    name = str(raw or "").strip()
    if not name:
        return None
    if not _USERNAME_RE.fullmatch(name):
        return None
    return name.lower()


def _resolve_user_key(users: dict[str, dict[str, Any]], raw_login: Any) -> str | None:
    """Resolve a login input to stored user key (supports legacy random ids and display_name)."""
    login_raw = str(raw_login or "").strip()
    if not login_raw:
        return None
    canon = _canonical_username(login_raw)
    if canon in users:
        return canon
    for key, record in users.items():
        if _canonical_username(key) == canon:
            return key
        if _canonical_username(record.get("display_name")) == canon:
            return key
    return None


def _users_store_path() -> str:
    root = os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "users.json")


def _load_users() -> dict[str, dict[str, Any]]:
    path = _users_store_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _save_users(users: dict[str, dict[str, Any]]) -> None:
    path = _users_store_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def _hash_password(password: str, salt: bytes | None = None, rounds: int = 200_000) -> str:
    if salt is None:
        salt = os.urandom(16)
    pwd = password.encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", pwd, salt, rounds)
    b64_salt = base64.b64encode(salt).decode("ascii")
    b64_digest = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${rounds}${b64_salt}${b64_digest}"


def _verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algo, rounds_raw, b64_salt, b64_digest = encoded_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_raw)
        salt = base64.b64decode(b64_salt.encode("ascii"))
        expected = base64.b64decode(b64_digest.encode("ascii"))
    except (ValueError, TypeError, binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def create_app(
    *,
    bus: Optional[MessageBus] = None,
    manager: Optional[ConversationManager] = None,
    safety_gateway: Optional[SafetyGateway] = None,
    mcp_client: Optional[Any] = None,
    agents: Optional[tuple] = None,
    timeout_seconds: Optional[int] = None,
    llm_client: Optional[Any] = None,
) -> FastAPI:
    """
    Build and return a FastAPI app with POST /chat and GET /conversations/{id}.

    Shared state (bus, manager, safety_gateway, mcp_client, agents) is stored on
    app.state. If not provided, they are created at startup (same wiring as
    main._run_e2e_once). Optional dependency injection for testing.

    Args:
        bus: Optional MessageBus (default: InMemoryMessageBus).
        manager: Optional ConversationManager (default: created from bus).
        safety_gateway: Optional SafetyGateway (default: new instance).
        mcp_client: Optional MCPClient (default: MCPServer().register_default_tools + MCPClient).
        agents: Optional (planner, librarian, websearcher, analyst, responder) tuple.
        timeout_seconds: Optional E2E timeout override (default: from config).
        llm_client: Optional LLM client for agents (default: from get_llm_client(config); required if not provided).

    Returns:
        FastAPI app instance.
    """
    from config.config import load_config

    cfg = load_config()
    from util import interaction_log as il

    il.set_enabled(cfg.interaction_log_enabled)
    effective_timeout = (
        timeout_seconds if timeout_seconds is not None else cfg.e2e_timeout_seconds
    )

    if bus is None:
        bus = InMemoryMessageBus()
        for name in ("planner", "librarian", "websearcher", "analyst", "responder"):
            bus.register_agent(name)
    if manager is None:
        manager = ConversationManager(bus)
    if safety_gateway is None:
        safety_gateway = SafetyGateway()
    # Wire MCP server with all tools so agents can call file_tool, vector_tool, market_tool, etc.
    if mcp_client is None:
        from mcp.mcp_client import MCPClient
        from mcp.mcp_server import MCPServer

        server = MCPServer()
        server.register_default_tools()
        mcp_client = MCPClient(server)
    if agents is None:
        from agents.analyst_agent import AnalystAgent
        from agents.librarian_agent import LibrarianAgent
        from agents.planner_agent import PlannerAgent
        from agents.responder_agent import ResponderAgent
        from agents.websearch_agent import WebSearcherAgent
        from llm.factory import get_llm_client
        from output.output_rail import OutputRail

        # Resolve LLM client so planner and specialists can decompose queries and select tools
        if llm_client is None:
            try:
                llm_client = get_llm_client(cfg)
            except (ValueError, ImportError) as e:
                raise RuntimeError(
                    "LLM is required. Set LLM_API_KEY in .env and install: pip install openfund-ai[llm]. See README."
                ) from e
        planner = PlannerAgent(
            "planner", bus, llm_client=llm_client, conversation_manager=manager,
            max_research_rounds=cfg.max_research_rounds,
        )
        librarian = LibrarianAgent(
            "librarian",
            bus,
            mcp_client=mcp_client,
            conversation_manager=manager,
            llm_client=llm_client,
        )
        websearcher = WebSearcherAgent(
            "websearcher",
            bus,
            mcp_client=mcp_client,
            conversation_manager=manager,
            llm_client=llm_client,
        )
        analyst = AnalystAgent(
            "analyst",
            bus,
            mcp_client=mcp_client,
            conversation_manager=manager,
            llm_client=llm_client,
            analyst_confidence_threshold=cfg.analyst_confidence_threshold,
        )
        responder = ResponderAgent(
            "responder",
            bus,
            conversation_manager=manager,
            output_rail=OutputRail(),
            llm_client=llm_client,
        )
        agents = (planner, librarian, websearcher, analyst, responder)
        # Start each agent in its own thread so they can receive and handle messages
        for agent in agents:
            t = threading.Thread(target=agent.run, daemon=True)
            t.start()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        logger.info("OpenFund-AI API: live MCP and LLM when configured")
        yield

    app = FastAPI(title="OpenFund-AI REST API", lifespan=_lifespan)
    app.state.bus = bus
    app.state.manager = manager
    app.state.safety_gateway = safety_gateway
    app.state.e2e_timeout_seconds = effective_timeout

    @app.post("/register")
    def post_register_endpoint(body: RegisterRequest) -> JSONResponse:
        """POST /register: create a username account with password and return welcome message."""
        requested = body.username or body.display_name
        user_id = _validate_new_username(requested)
        if not user_id:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "username must match ^[A-Za-z][A-Za-z0-9_.-]{2,31}$ "
                        "(3-32 chars, start with a letter)"
                    )
                },
            )

        users = _load_users()
        # Enforce uniqueness across usernames and legacy display_name values.
        if _resolve_user_key(users, user_id) is not None:
            return JSONResponse(
                status_code=409,
                content={"detail": f"username '{user_id}' is already registered"},
            )
        users[user_id] = {
            "display_name": user_id,
            "username": user_id,
            "password_hash": _hash_password(body.password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_users(users)
        return JSONResponse(
            status_code=200,
            content={
                "user_id": user_id,
                "username": user_id,
                "message": f"New user created. Welcome, {user_id}!",
            },
        )

    @app.post("/login")
    def post_login_endpoint(body: LoginRequest) -> JSONResponse:
        """POST /login: verify password by username/user_id and preload memory."""
        # Read credential store first, then validate password hash.
        users = _load_users()
        login_name = body.username or body.user_id
        user_key = _resolve_user_key(users, login_name)
        record = users.get(user_key or "")
        if not record or not _verify_password(body.password, str(record.get("password_hash") or "")):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid username/user_id or password"},
            )
        loaded = manager.load_user_conversations(user_key or "")
        # Compute compact memory context for planner priming on the next query.
        memory_context = manager.get_user_memory_context(
            user_key or "", max_conversations=3, max_chars=1000
        )
        return JSONResponse(
            status_code=200,
            content={
                "user_id": user_key,
                "username": user_key,
                "message": f"Welcome back, {record.get('display_name') or user_key}.",
                "loaded_conversations": loaded,
                "has_memory_context": bool(memory_context),
            },
        )

    @app.post("/chat")
    def post_chat_endpoint(body: ChatRequest) -> JSONResponse:
        """POST /chat: validate, safety, create/get conversation, send to planner, wait, return."""
        # Normalize request fields into local variables for flow orchestration.
        query = body.query
        user_profile = body.user_profile
        user_id = body.user_id
        conversation_id = body.conversation_id
        path = body.path
        user_memory = ""
        if user_id:
            # Load persisted history and derive planner memory context before dispatch.
            manager.load_user_conversations(user_id)
            user_memory = manager.get_user_memory_context(user_id)

        interaction_log.log_call(
            "api.rest.post_chat_endpoint",
            params={
                "query_len": len(query),
                "user_profile": user_profile,
                "conversation_id": conversation_id or "(new)",
            },
        )

        trace(
            1,
            "request_validated",
            in_={
                "query_len": len(query),
                "user_profile": user_profile,
                "user_id": user_id or "(none)",
                "conversation_id": conversation_id or "(new)",
            },
            out="validated body",
            next_="safety check",
        )

        # 1. Validate and run safety (guardrails, PII masking)
        try:
            safety_gateway.process_user_input(query)
        except SafetyError as e:
            trace(2, "safety_failed", out=f"reason={e.reason}", next_="return 400")
            interaction_log.log_call(
                "api.rest.post_chat_endpoint",
                result={"status_code": 400, "error": e.reason},
            )
            return JSONResponse(status_code=400, content={"detail": e.reason})

        trace(
            2,
            "safety_passed",
            in_={"query": "processed"},
            out="ok",
            next_="create or get conversation",
        )

        # 2. Create a new conversation or restore an existing one by conversation_id.
        if conversation_id:
            state = manager.get_conversation(conversation_id)
            if state is None and user_id:
                # Retry after persistence reload in case conversation was not in memory yet.
                manager.load_user_conversations(user_id)
                state = manager.get_conversation(conversation_id)
            if state is None:
                trace(
                    4,
                    "get_conversation",
                    in_={"conversation_id": conversation_id},
                    out="not_found",
                    next_="return 404",
                )
                interaction_log.set_conversation_id(conversation_id)
                interaction_log.log_call(
                    "api.rest.post_chat_endpoint",
                    result={"status_code": 404, "error": "Conversation not found"},
                )
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Conversation not found"},
                )
            interaction_log.set_conversation_id(conversation_id)
            trace(
                4,
                "get_conversation",
                in_={"conversation_id": conversation_id},
                out=f"found status={state.status}",
                next_="send to planner",
            )
        else:
            conversation_id = manager.create_conversation(user_id, query)
            state = manager.get_conversation(conversation_id)
            if state is None:
                interaction_log.set_conversation_id(conversation_id)
                interaction_log.log_call(
                    "api.rest.post_chat_endpoint",
                    result={"status_code": 500, "error": "Failed to create conversation"},
                )
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Failed to create conversation"},
                )
            interaction_log.set_conversation_id(conversation_id)
            trace(
                3,
                "conversation_created",
                in_={"user_id": user_id, "initial_query": query[:50]},
                out=f"conversation_id={conversation_id}",
                next_="append flow, then send to planner",
            )
            display = f" (welcome, user {user_id})" if user_id else ""
            manager.append_flow(
                conversation_id,
                {
                    "step": "user_created",
                    "message": f"New conversation started.{display} You can ask your question below.",
                    "detail": {
                        "user_id": user_id or "anonymous",
                        "conversation_id": conversation_id,
                    },
                },
            )

        # 3. Build planner payload and dispatch REQUEST into the A2A message bus.
        content = {
            "query": query,
            "conversation_id": conversation_id,
            "user_profile": user_profile,
        }
        if user_memory:
            content["user_memory"] = user_memory
        if path is not None:
            content["path"] = path
        bus.send(
            ACLMessage(
                performative=Performative.REQUEST,
                sender="api",
                receiver="planner",
                content=content,
                conversation_id=conversation_id,
            )
        )
        trace(
            5,
            "request_sent_to_planner",
            in_={
                "conversation_id": conversation_id,
                "user_profile": user_profile,
                "query_preview": query[:50],
            },
            out="sent",
            next_="wait completion_event",
        )
        manager.append_flow(
            conversation_id,
            {
                "step": "request_sent",
                "message": "Query received. Sent to Planner; you will see decomposition and agent steps as they run.",
                "detail": {"query_preview": query[:100]},
            },
        )

        # 4. Wait for responder completion signal (or timeout) before returning to client.
        timeout = app.state.e2e_timeout_seconds
        signaled = state.completion_event.wait(timeout=timeout)
        if not signaled:
            trace(
                14,
                "timeout",
                in_={"conversation_id": conversation_id, "timeout_seconds": timeout},
                out="no final_response",
                next_="return 408",
            )
            interaction_log.log_call(
                "api.rest.post_chat_endpoint",
                result={"status_code": 408, "status": "timeout", "response_len": None},
            )
            return JSONResponse(
                status_code=408,
                content={
                    "status": "timeout",
                    "conversation_id": conversation_id,
                    "response": None,
                    "flow": manager.get_flow_events(conversation_id),
                },
            )
        trace(
            15,
            "response_ready",
            in_={"conversation_id": conversation_id},
            out=f"status={state.status} response_len={len(state.final_response or '')}",
            next_="return 200",
        )
        flow = manager.get_flow_events(conversation_id)
        interaction_log.log_call(
            "api.rest.post_chat_endpoint",
            result={
                "status_code": 200,
                "status": state.status,
                "response_len": len(state.final_response or ""),
            },
        )
        return JSONResponse(
            status_code=200,
            content={
                "conversation_id": conversation_id,
                "status": state.status,
                "response": state.final_response or "",
                "flow": flow,
            },
        )

    @app.get("/conversations/{conversation_id}")
    def get_conversation_endpoint(conversation_id: str) -> JSONResponse:
        """GET /conversations/{id}: return conversation state as JSON."""
        state = manager.get_conversation(conversation_id)
        if state is None:
            return JSONResponse(
                status_code=404,
                content={"detail": "Conversation not found"},
            )
        payload = _state_to_json(state)
        return JSONResponse(status_code=200, content=payload)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket /ws: same flow as POST /chat; one event (response/timeout/error) then close."""
        await websocket.accept()
        await ws_handle_websocket(
            websocket,
            app.state.bus,
            app.state.manager,
            app.state.safety_gateway,
            app.state.e2e_timeout_seconds,
        )

    return app


def _state_to_json(state: ConversationState) -> dict[str, Any]:
    """Serialize ConversationState to JSON (omit completion_event and lock)."""
    return {
        "id": state.id,
        "user_id": state.user_id,
        "initial_query": state.initial_query,
        "messages": state.messages,
        "status": state.status,
        "final_response": state.final_response,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "flow": getattr(state, "flow_events", []),
    }


def post_chat(body: dict) -> dict:
    """
    Handle POST /chat (or POST /research).

    Flow: validate body -> SafetyGateway.process_user_input ->
    create/load conversation -> send ACLMessage to Planner ->
    wait for response (or stream) -> return.

    Args:
        body: Request body with 'query'; optional 'conversation_id', 'user_profile'.

    Returns:
        Response dict with conversation_id, message_id, status, response.
    """
    raise NotImplementedError(
        "Use FastAPI TestClient with create_app() or POST /chat endpoint."
    )


def get_conversation(conversation_id: str) -> Optional[dict]:
    """
    Handle GET /conversations/{id}.

    Args:
        conversation_id: Conversation to fetch.

    Returns:
        Conversation state/messages or None if not found.
    """
    raise NotImplementedError(
        "Use FastAPI TestClient with create_app() or GET /conversations/{id} endpoint."
    )
