"""Entry point: wire MessageBus, agents, API, and optional MCP server."""

import logging
import os
import sys
import warnings

from config.config import load_config
from util.log_format import OpenFundFormatter, struct_log

logger = logging.getLogger(__name__)

UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "openfund": {"()": "util.log_format.OpenFundFormatter"},
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "openfund",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}


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
    try:
        llm_client = get_llm_client(cfg)
    except (ValueError, ImportError):
        from llm.static_client import StaticLLMClient

        llm_client = StaticLLMClient()
    planner = PlannerAgent("planner", bus, llm_client=llm_client)
    librarian = LibrarianAgent(
        "librarian", bus, mcp_client=client, llm_client=llm_client
    )
    websearcher = WebSearcherAgent(
        "websearcher", bus, mcp_client=client, llm_client=llm_client
    )
    analyst = AnalystAgent(
        "analyst", bus, mcp_client=client, llm_client=llm_client
    )
    responder = ResponderAgent(
        "responder",
        bus,
        conversation_manager=mgr,
        output_rail=OutputRail(),
        llm_client=llm_client,
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
    """Initialize entry modes for OpenFund-AI.

    Modes:
    - --e2e-once: run one end-to-end conversation and exit 0.
    - --serve: run FastAPI via uvicorn (same as default).
    - --no-serve: load config/situation memory only and exit.
    """
    warnings.filterwarnings(
        "ignore",
        message=".*urllib3 v2 only supports OpenSSL",
        category=UserWarning,
        module="urllib3",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    root = logging.getLogger()
    for h in root.handlers:
        h.setFormatter(OpenFundFormatter())
    if os.environ.get("LOG_LEVEL", "").strip().upper() == "DEBUG":
        logging.getLogger("openfund.interaction").setLevel(logging.INFO)
        logging.getLogger("util.trace_log").setLevel(logging.INFO)
    else:
        logging.getLogger("openfund.interaction").setLevel(logging.WARNING)
        logging.getLogger("util.trace_log").setLevel(logging.WARNING)
    try:
        import ssl
        if "LibreSSL" in getattr(ssl, "OPENSSL_VERSION_STRING", ""):
            struct_log(logger, logging.WARNING, "ssl.environment", message="LibreSSL detected (urllib3 v2 prefers OpenSSL)")
    except Exception:
        pass
    if "--e2e-once" in sys.argv:
        _run_e2e_once()
        return

    cfg = load_config()
    # Optional: load BM25 situation memory from MEMORY_STORE_PATH/situation_memory.json
    try:
        from memory import get_situation_memory

        get_situation_memory(cfg.memory_store_path)
    except ImportError as e:
        struct_log(logger, logging.INFO, "memory.load", status="unavailable", reason=str(e))

    serve = ("--serve" in sys.argv) or ("--no-serve" not in sys.argv)
    port = 8000
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
            except ValueError:
                port = 8000
    if serve:
        struct_log(logger, logging.INFO, "system.startup", port=port, status="ready")
    else:
        struct_log(logger, logging.INFO, "system.startup", status="ready")

    if serve:
        import uvicorn

        uvicorn.run(
            "api.rest:create_app",
            factory=True,
            host="0.0.0.0",
            port=port,
            log_config=UVICORN_LOG_CONFIG,
        )


if __name__ == "__main__":
    main()
