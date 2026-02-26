"""REST API (Layer 1): chat and conversation endpoints."""

from __future__ import annotations

import threading
from typing import Any, Optional

from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse

from a2a.acl_message import ACLMessage, Performative
from a2a.conversation_manager import ConversationManager, ConversationState
from a2a.message_bus import InMemoryMessageBus, MessageBus
from safety.safety_gateway import SafetyError, SafetyGateway

VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


def create_app(
    *,
    bus: Optional[MessageBus] = None,
    manager: Optional[ConversationManager] = None,
    safety_gateway: Optional[SafetyGateway] = None,
    mcp_client: Optional[Any] = None,
    agents: Optional[tuple] = None,
    timeout_seconds: Optional[int] = None,
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

    Returns:
        FastAPI app instance.
    """
    from config.config import load_config

    cfg = load_config()
    effective_timeout = timeout_seconds if timeout_seconds is not None else cfg.e2e_timeout_seconds

    if bus is None:
        bus = InMemoryMessageBus()
        for name in ("planner", "librarian", "websearcher", "analyst", "responder"):
            bus.register_agent(name)
    if manager is None:
        manager = ConversationManager(bus)
    if safety_gateway is None:
        safety_gateway = SafetyGateway()
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
        from output.output_rail import OutputRail

        planner = PlannerAgent("planner", bus)
        librarian = LibrarianAgent("librarian", bus, mcp_client=mcp_client)
        websearcher = WebSearcherAgent("websearcher", bus, mcp_client=mcp_client)
        analyst = AnalystAgent("analyst", bus, mcp_client=mcp_client)
        responder = ResponderAgent(
            "responder",
            bus,
            conversation_manager=manager,
            output_rail=OutputRail(),
        )
        agents = (planner, librarian, websearcher, analyst, responder)
        for agent in agents:
            t = threading.Thread(target=agent.run, daemon=True)
            t.start()

    app = FastAPI(title="OpenFund-AI REST API")
    app.state.bus = bus
    app.state.manager = manager
    app.state.safety_gateway = safety_gateway
    app.state.e2e_timeout_seconds = effective_timeout

    @app.post("/chat")
    def post_chat_endpoint(body: dict = Body(...)) -> JSONResponse:
        """POST /chat: validate, safety, create/get conversation, send to planner, wait, return."""
        # Validate body
        query = body.get("query")
        if query is None or (isinstance(query, str) and not query.strip()):
            return JSONResponse(
                status_code=400,
                content={"detail": "query is required and must be non-empty"},
            )
        user_profile = (body.get("user_profile") or "beginner").strip().lower()
        if user_profile not in VALID_USER_PROFILES:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": f"user_profile must be one of {list(VALID_USER_PROFILES)}",
                },
            )
        user_id = body.get("user_id")
        if user_id is None:
            user_id = ""
        else:
            user_id = str(user_id).strip()
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            conversation_id = str(conversation_id).strip() or None
        path = body.get("path")  # optional, for E2E/testing

        # Safety
        try:
            safety_gateway.process_user_input(query)
        except SafetyError as e:
            return JSONResponse(status_code=400, content={"detail": e.reason})

        # Create or get conversation
        if conversation_id:
            state = manager.get_conversation(conversation_id)
            if state is None:
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Conversation not found"},
                )
        else:
            conversation_id = manager.create_conversation(user_id, query)
            state = manager.get_conversation(conversation_id)
            if state is None:
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Failed to create conversation"},
                )

        # Send REQUEST to planner
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

        # Block on completion
        timeout = app.state.e2e_timeout_seconds
        signaled = state.completion_event.wait(timeout=timeout)
        if not signaled:
            return JSONResponse(
                status_code=408,
                content={
                    "status": "timeout",
                    "conversation_id": conversation_id,
                    "response": None,
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "conversation_id": conversation_id,
                "status": state.status,
                "response": state.final_response or "",
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

    return app


def _state_to_json(state: ConversationState) -> dict[str, Any]:
    """Serialize ConversationState to JSON (omit completion_event)."""
    return {
        "id": state.id,
        "user_id": state.user_id,
        "initial_query": state.initial_query,
        "messages": state.messages,
        "status": state.status,
        "final_response": state.final_response,
        "created_at": state.created_at.isoformat() if state.created_at else None,
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
    raise NotImplementedError("Use FastAPI TestClient with create_app() or POST /chat endpoint.")


def get_conversation(conversation_id: str) -> Optional[dict]:
    """
    Handle GET /conversations/{id}.

    Args:
        conversation_id: Conversation to fetch.

    Returns:
        Conversation state/messages or None if not found.
    """
    raise NotImplementedError("Use FastAPI TestClient with create_app() or GET /conversations/{id} endpoint.")
