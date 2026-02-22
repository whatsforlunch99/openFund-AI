# Changelog

Summary of notable changes. Newest first.

## [Unreleased]

- docs: add staged_implementation_plan.md and test_plan.md (tests per stage, runnable commands).
- docs: add clarification.md (architecture decisions and settled items).
- docs: update claude-v2.md (conversation persistence structure, API details).
- docs: enhance staged_implementation_plan.md and test_plan.md (detailed test functions, runnable commands per stage).
- config: track .DS_Store (macOS directory settings).

## [0.1.0] - 2025-02-21

- Initial project skeleton from docs/claude-v2.md.
- **a2a:** ACLMessage, MessageBus, ConversationManager, ConversationState.
- **agents:** BaseAgent; PlannerAgent, LibrarianAgent, WebSearcherAgent, AnalystAgent, ResponderAgent (stubs only).
- **api:** rest.py (create_app, post_chat, get_conversation), websocket.py (handle_websocket).
- **safety:** SafetyGateway (validate_input, check_guardrails, mask_pii, process_user_input).
- **output:** OutputRail (check_compliance, format_for_user).
- **config:** Config dataclass, load_config().
- **mcp:** MCPClient, MCPServer; tools: vector_tool (Milvus), kg_tool (Neo4j), market_tool (Tavily/Yahoo), analyst_tool (custom API), sql_tool, file_tool.
- **main:** main() entry point stub.
- pyproject.toml (Python >=3.11); package __init__.py for all modules.
- Cursor rules: operating-principles, changelog convention.
