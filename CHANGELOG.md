# Changelog

Summary of notable changes. Newest first. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Work breakdown and implementation notes remain in [docs/progress.md](docs/progress.md).

## [Unreleased]

- docs: align /docs with docs-structure rule — user-flow (behavioral flow only, no implementation); prd (what/why only); backend (API, data models, errors, integrations; no slices); file-structure (no Overview/Technology Stack); project-status (Not Started | In Progress | Live | Deprecated); rename product-requirements.md to prd.md.
- docs: reorganize /docs into user-flow, prd, backend, frontend (placeholder), file-structure, progress, project-status; integrate changelog into progress.md; remove .cursor/rules/changelog.mdc.
- docs: add staged_implementation_plan.md and test_plan.md (tests per stage, runnable commands).
- docs: add clarification.md (architecture decisions and settled items).
- docs: update claude-v2.md (conversation persistence structure, API details).
- docs: enhance staged_implementation_plan and test_plan (detailed test functions, runnable commands per stage).
- config: track .DS_Store (macOS directory settings).

## [0.1.0] - 2025-02-21

- Initial project skeleton from docs.
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
