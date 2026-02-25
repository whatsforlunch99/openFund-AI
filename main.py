"""Entry point: wire MessageBus, agents, API, and optional MCP server."""

from config.config import load_config


def main() -> None:
    """
    Initialize and start the OpenFund-AI stack.

    Creates MessageBus (e.g. in-memory), ConversationManager,
    SafetyGateway, MCP client (with config); instantiates all
    agents with bus and MCP client; starts FastAPI (REST + WebSocket)
    and agent runners; optionally starts MCP server.
    """
    cfg = load_config()
    try:
        from memory import get_situation_memory

        get_situation_memory(cfg.memory_store_path)
    except ImportError as e:
        import logging

        logging.getLogger(__name__).info("Situation memory unavailable: %s", e)
    print("OpenFund-AI ready (config loaded)")


if __name__ == "__main__":
    main()
