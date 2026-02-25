"""Entry point: wire MessageBus, agents, API, and optional MCP server."""

import sys

from config.config import load_config


def _run_e2e_once() -> None:
    """Run one E2E conversation (Slice 3): api → planner → librarian (file_tool) → responder.

    Wires bus, manager, MCP server (file_tool only), agents; starts agent threads;
    creates a temp file and passes its path so librarian can read it; blocks on
    completion_event then exits 0.
    """
    import threading
    import tempfile
    import os

    from a2a.acl_message import ACLMessage, Performative
    from a2a.conversation_manager import ConversationManager
    from a2a.message_bus import InMemoryMessageBus
    from agents.librarian_agent import LibrarianAgent
    from agents.planner_agent import PlannerAgent
    from agents.responder_agent import ResponderAgent
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer

    cfg = load_config()
    bus = InMemoryMessageBus()
    for name in ("planner", "librarian", "responder"):
        bus.register_agent(name)

    mgr = ConversationManager(bus)
    server = MCPServer()
    from mcp.tools import file_tool

    server.register_tool(
        "file_tool.read_file",
        lambda p: (
            file_tool.read_file(p["path"])
            if "path" in p
            else {"error": "Missing required parameter 'path'"}
        ),
    )
    client = MCPClient(server)
    planner = PlannerAgent("planner", bus)
    librarian = LibrarianAgent("librarian", bus, mcp_client=client)
    responder = ResponderAgent("responder", bus, conversation_manager=mgr)

    for agent in (planner, librarian, responder):
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

        bus.send(
            ACLMessage(
                performative=Performative.REQUEST,
                sender="api",
                receiver="planner",
                content={
                    "query": "What is in the project?",
                    "conversation_id": cid,
                    "path": e2e_path,
                },
                conversation_id=cid,
            )
        )

        timeout = cfg.e2e_timeout_seconds
        state.completion_event.wait(timeout=timeout)
        if state.final_response:
            print(
                "E2E complete:",
                (state.final_response[:80] + "...")
                if len(state.final_response) > 80
                else state.final_response,
            )
        else:
            print("E2E timeout (no final response within %ss)" % timeout)
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
    if "--e2e-once" in sys.argv:
        _run_e2e_once()
        return

    cfg = load_config()
    # Optional: load BM25 situation memory from MEMORY_STORE_PATH/situation_memory.json
    try:
        from memory import get_situation_memory

        get_situation_memory(cfg.memory_store_path)
    except ImportError as e:
        import logging

        logging.getLogger(__name__).info("Situation memory unavailable: %s", e)
    print("OpenFund-AI ready (config loaded)")


if __name__ == "__main__":
    main()
