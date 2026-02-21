"""Entry point: wire MessageBus, agents, API, and optional MCP server."""


def main() -> None:
    """
    Initialize and start the OpenFund-AI stack.

    Creates MessageBus (e.g. in-memory), ConversationManager,
    SafetyGateway, MCP client (with config); instantiates all
    agents with bus and MCP client; starts FastAPI (REST + WebSocket)
    and agent runners; optionally starts MCP server.
    """
    raise NotImplementedError


if __name__ == "__main__":
    main()
