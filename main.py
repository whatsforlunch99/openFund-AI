"""Entry point: wire MessageBus, agents, API, and optional MCP server."""

import logging
import sys

from config.config import load_config

logger = logging.getLogger(__name__)


def _run_e2e_once() -> None:
    """Run one E2E conversation (Slice 5): api → planner → librarian + websearcher + analyst → responder.

    Wires bus, manager, MCP server (default tools), all five agents; starts agent threads;
    creates a temp file and passes its path so librarian can read it; blocks on
    completion_event then exits 0.
    """
    import os
    import tempfile
    import threading

    from a2a.acl_message import ACLMessage, Performative
    from a2a.conversation_manager import ConversationManager
    from a2a.message_bus import InMemoryMessageBus
    from agents.analyst_agent import AnalystAgent
    from agents.librarian_agent import LibrarianAgent
    from agents.planner_agent import PlannerAgent
    from agents.responder_agent import ResponderAgent
    from agents.websearch_agent import WebSearcherAgent
    from llm.factory import get_llm_client
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer
    from output.output_rail import OutputRail

    cfg = load_config()
    bus = InMemoryMessageBus()
    for name in ("planner", "librarian", "websearcher", "analyst", "responder"):
        bus.register_agent(name)

    # Wire manager, MCP server with default tools, LLM client, and all five agents
    mgr = ConversationManager(bus)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    llm_client = get_llm_client(cfg)
    planner = PlannerAgent("planner", bus, llm_client=llm_client)
    librarian = LibrarianAgent("librarian", bus, mcp_client=client)
    websearcher = WebSearcherAgent("websearcher", bus, mcp_client=client)
    analyst = AnalystAgent("analyst", bus, mcp_client=client)
    responder = ResponderAgent(
        "responder",
        bus,
        conversation_manager=mgr,
        output_rail=OutputRail(),
    )

    for agent in (planner, librarian, websearcher, analyst, responder):
        t = threading.Thread(target=agent.run, daemon=True)
        t.start()

    # Temp file so librarian has something to read; we pass path in the REQUEST content
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("E2E test content.")
        e2e_path = f.name
    try:
        cid = mgr.create_conversation("e2e_user", "What is in the project?")
        state = mgr.get_conversation(cid)
        assert state is not None

        # Send REQUEST to planner; planner sends to librarian, websearcher, analyst (Slice 5)
        bus.send(
            ACLMessage(
                performative=Performative.REQUEST,
                sender="api",
                receiver="planner",
                content={
                    "query": "What is in the project?",
                    "conversation_id": cid,
                    "user_profile": "beginner",
                    "path": e2e_path,
                },
                conversation_id=cid,
            )
        )

        timeout = cfg.e2e_timeout_seconds
        # Block until responder sets final_response and sets completion_event
        state.completion_event.wait(timeout=timeout)
        if state.final_response:
            logger.info(
                "E2E complete: %s",
                (
                    (state.final_response[:80] + "...")
                    if len(state.final_response) > 80
                    else state.final_response
                ),
            )
        else:
            logger.warning("E2E timeout (no final response within %ss)", timeout)
    finally:
        os.unlink(e2e_path)
    sys.exit(0)


def main() -> None:
    """Initialize and start the OpenFund-AI stack.

    Creates MessageBus (e.g. in-memory), ConversationManager, SafetyGateway,
    MCP client (with config); instantiates all agents with bus and MCP client;
    starts FastAPI (REST + WebSocket) and agent runners; optionally starts MCP server.
    If --e2e-once is in sys.argv, runs one E2E conversation and exits.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    if "--e2e-once" in sys.argv:
        _run_e2e_once()
        return

    cfg = load_config()
    # Optional: load BM25 situation memory from MEMORY_STORE_PATH/situation_memory.json
    try:
        from memory import get_situation_memory

        get_situation_memory(cfg.memory_store_path)
    except ImportError as e:
        logger.info("Situation memory unavailable: %s", e)
    logger.info("OpenFund-AI ready (config loaded)")


if __name__ == "__main__":
    main()
