"""REST API (Layer 1): chat and conversation endpoints."""

from __future__ import annotations

import logging
import threading
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
    """POST /register body: optional display name for new user."""

    display_name: str = ""

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip() or "Guest"


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

    @app.get("/demo")
    def get_demo_mode() -> JSONResponse:
        """Return demo flag (always false; endpoint kept for chat client compatibility)."""
        return JSONResponse(status_code=200, content={"demo": False})

    @app.post("/register")
    def post_register_endpoint(body: RegisterRequest) -> JSONResponse:
        """POST /register: create a new user id and return a welcome message."""
        import uuid

        name = body.display_name or "Guest"
        user_id = "user_" + uuid.uuid4().hex[:8]
        return JSONResponse(
            status_code=200,
            content={
                "user_id": user_id,
                "message": f"New user created. Welcome, {name}! Use this user_id when sending queries.",
            },
        )

    @app.post("/chat")
    def post_chat_endpoint(body: ChatRequest) -> JSONResponse:
        """POST /chat: validate, safety, create/get conversation, send to planner, wait, return."""
        query = body.query
        user_profile = body.user_profile
        user_id = body.user_id
        conversation_id = body.conversation_id
        path = body.path

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
            return JSONResponse(status_code=400, content={"detail": e.reason})

        trace(
            2,
            "safety_passed",
            in_={"query": "processed"},
            out="ok",
            next_="create or get conversation",
        )

        # 2. Create new conversation or load existing by conversation_id
        if conversation_id:
            state = manager.get_conversation(conversation_id)
            if state is None:
                trace(
                    4,
                    "get_conversation",
                    in_={"conversation_id": conversation_id},
                    out="not_found",
                    next_="return 404",
                )
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Conversation not found"},
                )
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
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Failed to create conversation"},
                )
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

        # 3. Send REQUEST to planner; planner will send to librarian, websearcher, analyst
        content = {
            "query": query,
            "conversation_id": conversation_id,
            "user_profile": user_profile,
        }
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

        # 4. Block until responder sets final_response and completion_event, or timeout
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
        # Flow events for UI: planner/agent step messages (see docs/use-case-trace-beginner.md).
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
