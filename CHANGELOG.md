# Changelog

Summary of notable changes. Newest first. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Work breakdown and implementation notes remain in [docs/progress.md](docs/progress.md).

## [Unreleased]

### Added

- **Stage 2.1:** MCP server and client with `file_tool.read_file`: `MCPServer.dispatch`, `MCPClient(server).call_tool("file_tool.read_file", {"path": "..."})`, and `file_tool.read_file(path)` implemented; test_stage_2_1 passes.

### Changed

- (none yet)

### Fixed

- (none yet)

### Removed

- (none yet)

## [0.2.0] - 2025-02-21

### Added

- **docs:** `staged_implementation_plan.md` and `test_plan.md` (tests per stage, runnable commands).
- **docs:** `clarification.md` (architecture decisions and settled items).
- **docs:** User-flow documentation aligned with PRD and file-structure contracts; enhanced for target audiences.
- **config:** `.gitignore` entry to stop tracking `.DS_Store` (macOS directory settings).

### Changed

- **docs:** Reorganized `/docs` into user-flow, prd, backend, frontend (placeholder), file-structure, progress, project-status; integrated changelog into `CHANGELOG.md`; removed `.cursor/rules/changelog.mdc`.
- **docs:** Aligned `/docs` with docs-structure rule — user-flow (behavioral only), prd (what/why only), backend (API, data models, errors; no slices), file-structure (no Overview/Technology Stack), project-status (Not Started | In Progress | Live | Deprecated); renamed `product-requirements.md` to `prd.md`.
- **docs:** Updated `claude-v2.md` (conversation persistence structure, API details); enhanced staged implementation and test plans (detailed test functions, runnable commands per stage).
- **docs:** Aligned clarification, plan, test plan, and use-case flows; documentation consistency across `/docs`.
- **a2a:** Enhanced ACLMessage and MessageBus functionality.
- **main:** README revised for API and agent updates; initial documentation and configuration files added.

### Fixed

- **a2a:** Removed duplicate `self.id = id` in `ConversationState` (use only `self.id = conversation_id`).

### Removed

- **docs:** `docs/python-review-unstaged.md` (temporary review artifact).
- **config:** Stopped tracking `.DS_Store` in git (added to `.gitignore`).

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
