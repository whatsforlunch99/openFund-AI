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
from util import interaction_log

logger = logging.getLogger(__name__)
VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


class ChatRequest(BaseModel):
    """POST /chat request body: query required; optional user_profile, user_id, conversation_id."""

    query: str
    user_profile: str = "beginner"
    user_id: str = ""
    conversation_id: Optional[str] = None

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


# The * means all parameters after it must be passed as keyword arguments, not positional
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
    from util import interaction_log as il

    cfg = load_config()


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

    # Wire MCP client to FastMCP server (subprocess over stdio).
    if mcp_client is None:
        from openfund_mcp.mcp_client import MCPClient

        mcp_client = MCPClient(
            command=cfg.mcp_server_command,
            args=tuple(cfg.mcp_server_args),
            cwd=cfg.mcp_server_cwd or None,
        )

    if agents is None:
        from agents.analyst_agent import AnalystAgent
        from agents.librarian_agent import LibrarianAgent
        from agents.planner_agent import PlannerAgent
        from agents.responder_agent import ResponderAgent
        from agents.websearch_agent import WebSearcherAgent
        from llm.factory import get_llm_client
        from safety.safety_gateway import OutputRail

        # Resolve LLM client so planner and specialists can decompose queries and select tools
        if llm_client is None:
            try:
                llm_client = get_llm_client(cfg)
            except (ValueError, ImportError) as e:
                raise RuntimeError(
                    "LLM is required. Set LLM_API_KEY in .env and install: pip install openfund-ai[llm]. See README."
                ) from e

        _model = (cfg.llm_model or "").strip() or "gpt-4o-mini"
        _base = (cfg.llm_base_url or "").strip()
        _provider = "deepseek" if _base and "deepseek" in _base.lower() else "openai"

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

    # asynccontextmanager can be used with async functions to close resources cleanly
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield

    app = FastAPI(title="OpenFund-AI REST API", lifespan=_lifespan)
    app.state.bus = bus
    app.state.manager = manager
    app.state.safety_gateway = safety_gateway
    app.state.e2e_timeout_seconds = effective_timeout
    app.state.mcp_client = mcp_client
    app.state.llm_configured = llm_client is not None

    @app.get("/health")
    def get_health() -> JSONResponse:
        """Return registered MCP tools and whether LLM is configured (for diagnostics)."""
        client = getattr(app.state, "mcp_client", None)
        tools = client.get_registered_tool_names() if client else []
        llm_configured = getattr(app.state, "llm_configured", False)
        return JSONResponse(
            content={"tools": tools, "llm_configured": llm_configured}
        )

    @app.post("/register")
    def post_register_endpoint(body: RegisterRequest) -> JSONResponse:
        """POST /register: create a username account with password and return welcome message."""
        requested = body.username or body.display_name
        user_id = _validate_new_username(requested)

        # if the username is not valid, return a 422 error
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

        # load the users from the users.json file
        users = _load_users()

        # Enforce uniqueness across usernames and legacy display_name values.
        if _resolve_user_key(users, user_id) is not None:
            return JSONResponse(
                status_code=409,
                content={"detail": f"username '{user_id}' is already registered"},
            )

        # create a new user with the username and password
        users[user_id] = {
            "display_name": user_id,
            "username": user_id,
            "password_hash": _hash_password(body.password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_users(users)

        # return the new user id and username
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
        try:
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
        except Exception as e:
            logger.exception("Login failed")
            return JSONResponse(
                status_code=500,
                content={"detail": str(e)},
            )

    @app.post("/chat")
    def post_chat_endpoint(body: ChatRequest) -> JSONResponse:
        """POST /chat: validate, safety, create/get conversation, send to planner, wait, return."""
        # Normalize request fields into local variables for flow orchestration.
        query = body.query
        user_profile = body.user_profile
        user_id = body.user_id
        conversation_id = body.conversation_id
        user_memory = ""

        #  Load persisted history and derive planner memory context before dispatch.
        if user_id:
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

        # validate and run safety (guardrails, PII masking)
        try:
            safety_gateway.process_user_input(query)
        except SafetyError as e:
            interaction_log.log_call(
                "api.rest.post_chat_endpoint",
                result={"status_code": 400, "error": e.reason},
            )
            return JSONResponse(status_code=400, content={"detail": e.reason})

        # Create or resume conversation: if user_id present, reload and use conversation_id if provided; else new user, create new conversation.
        if conversation_id:
            # Resume existing conversation (reload from persistence when user is logged in).
            state = manager.get_conversation(conversation_id)
            interaction_log.set_conversation_id(conversation_id)
            # If this conversation already completed (e.g. after a prior 408), return the cached response immediately.
            if state and (state.status == "complete" or state.final_response):
                if not (query and str(query).strip()):
                    flow = manager.get_flow_events(conversation_id)
                    return JSONResponse(
                        status_code=200,
                        content={
                            "conversation_id": conversation_id,
                            "status": state.status,
                            "response": state.final_response or "",
                            "flow": flow,
                        },
                    )
                # Multi-turn: non-empty follow-up -> new conversation
                conversation_id = manager.create_conversation(user_id, query)
                state = manager.get_conversation(conversation_id)
                interaction_log.set_conversation_id(conversation_id)
                manager.append_flow(
                    conversation_id,
                    {
                        "step": "new_turn",
                        "message": "Follow-up question. Running new research.",
                        "detail": {"query_preview": query[:100]},
                    },
                )
            manager.append_flow(
                conversation_id,
                {
                    "step": "reload_conversation",
                    "message": "Conversation loaded. You can ask your question below.",
                    "detail": {
                        "user_id": user_id or "anonymous",
                        "conversation_id": conversation_id,
                    },
                },
            )
        else:
            # New user or new conversation: create one.
            conversation_id = manager.create_conversation(user_id, query)
            state = manager.get_conversation(conversation_id)

            interaction_log.set_conversation_id(conversation_id)
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

        bus.send(
            ACLMessage(
                performative=Performative.REQUEST,
                sender="api",
                receiver="planner",
                content=content,
                conversation_id=conversation_id,
            )
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
                    "message": "The request took too long. Your question may still be processing. Send the same message again in a moment to get the answer when ready.",
                    "flow": manager.get_flow_events(conversation_id),
                },
            )

        # get the flow events
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
        # serialize the conversation state to JSON
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

