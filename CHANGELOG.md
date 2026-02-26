# Changelog

Summary of notable changes. Newest first. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Work breakdown and implementation notes remain in [docs/progress.md](docs/progress.md).

## [Unreleased]

### Added

- **Stage 10.2 (LLM integration, mock-first):** New `llm` module for task decomposition. `LLMClient` protocol and `StaticLLMClient` return a fixed three-step plan (librarian, websearcher, analyst) when `LLM_API_KEY` is not set, so E2E and API run without an API key. When `LLM_API_KEY` is set and optional dependency is installed (`pip install openfund-ai[llm]`), `LiveLLMClient` (OpenAI) is used. `get_llm_client(config)` chooses client; `PlannerAgent` accepts optional `llm_client` and uses it in `decompose_task` with fallback to fixed steps. Optional env: `LLM_MODEL` (default gpt-4o-mini). test_stage_10_2_llm_static_mock added. docs/progress.md, project-status.md, backend.md updated.
- **Slice 9 (Stage 9.1):** WebSocket /ws endpoint: same flow as POST /chat. Client sends one JSON message (query required; optional conversation_id, user_profile, user_id, path); server validates, runs SafetyGateway, create/get conversation, sends REQUEST to planner, waits on completion, then sends one event (response, timeout, or error) and closes. Implemented in api/websocket.py (async handle_websocket) and api/rest.py (WebSocket route). test_stage_9_1 passes.
- **Slice 8 (Stage 8.1):** OutputRail implementation: check_compliance(text) blocks explicit buy/sell-advice phrases (e.g. "buy this stock now", "sell immediately"); format_for_user(text, user_profile) adapts disclaimers and tone for beginner, long_term, analyst. ResponderAgent uses OutputRail when set: formats final response by user_profile, checks compliance, appends disclaimer if needed, registers formatted reply. user_profile flows from POST /chat → planner (stored per conversation) → INFORM to responder. create_app() and main._run_e2e_once() pass output_rail=OutputRail() to ResponderAgent. test_stage_8_1 passes.
- **Slice 7 (Stage 7.1):** REST API: create_app() in api/rest.py builds FastAPI app with POST /chat and GET /conversations/{id}. POST /chat validates body (query, user_profile, optional user_id/conversation_id), runs SafetyGateway.process_user_input, create/get conversation, sends REQUEST to planner, blocks on completion; returns 200 (conversation_id, status, response), 408 (timeout), 400 (validation/safety), 404 (conversation not found). GET /conversations/{id} returns conversation state JSON. Optional dependency injection (bus, manager, safety_gateway, mcp_client, agents, timeout_seconds) for testing. test_stage_7_1 passes. Dependencies: fastapi, uvicorn[standard] in pyproject.toml; httpx in dev for TestClient.
- **Slice 6 (Stage 6.1):** SafetyGateway implementation: validate_input (empty/whitespace reject, max length 10_000, UTF-8 printable/whitespace), check_guardrails (block list for illegal investment-advice phrases, case-insensitive), mask_pii (phone, email, SSN-like patterns → [PHONE], [EMAIL], [REDACTED]), process_user_input (validate → guardrails → mask_pii; raises SafetyError on failure). test_stage_6_1 passes.
- **Slice 5 (Stages 5.1–5.4):** WebSearcherAgent (handle_message, fetch_market_data, fetch_sentiment, fetch_regulatory via market_tool); AnalystAgent (handle_message, analyze stub, needs_more_data, sharpe_ratio, max_drawdown, monte_carlo_simulation); Planner sends REQUEST to librarian, websearcher, and analyst in one round, aggregates their INFORMs, then sends INFORM to Responder. E2E `main.py --e2e-once` wires all five agents and uses register_default_tools(). Tests: test_stage_5_1 (market_tool), test_stage_5_2 (analyst_tool), test_stage_5_3 (WebSearcherAgent), test_stage_5_4 (AnalystAgent).
- **Slice 4 (Stages 4.1–4.3):** vector_tool.search, kg_tool.query_graph, kg_tool.get_relations, sql_tool.run_query with mock implementations when MILVUS_URI / NEO4J_URI / DATABASE_URL are unset. MCPServer.register_default_tools() registers all four tools. LibrarianAgent uses vector_tool (vector_query), kg_tool (fund/entity), sql_tool (sql_query), and combine_results(); backward-compatible: when only path is provided, reply is file_tool result only. Tests: test_stage_4_1, test_stage_4_2, test_stage_4_3.
- **Slice 3 (Stages 3.1–3.3):** ACLMessage, BaseAgent, PlannerAgent (one step to librarian), LibrarianAgent (file_tool.read_file), ResponderAgent (stub: register_reply + broadcast_stop). Planner handles INFORM from librarian and sends INFORM to Responder with `final_response` and `conversation_id`. Tests: `test_stage_3_1`, `test_stage_3_2`, `test_stage_3_3`. E2E: `python main.py --e2e-once` runs one conversation (planner → librarian → responder) and exits 0; uses temp file for file_tool so response is successful.
- **Situation memory (Stage 2.3):** BM25-based `FinancialSituationMemory` for (situation, recommendation) pairs; persistence at `{MEMORY_STORE_PATH}/situation_memory.json`. API: `add_situations`, `get_memories`, `clear`, `save(path)`, `load(path)`, `load_from_dir(memory_store_path)`. Shared instance via `get_situation_memory(memory_store_path)`; initialized in `main()`. Dependency: `rank_bm25`. Tests: `test_stage_2_3_situation_memory`, `test_stage_2_3_situation_memory_load_from_dir_missing`.
- **Stage 2.1:** MCP server and client with `file_tool.read_file`: `MCPServer.dispatch`, `MCPClient(server).call_tool("file_tool.read_file", {"path": "..."})`, and `file_tool.read_file(path)` implemented; test_stage_2_1 passes.
- **TradingAgents tools integration:** New MCP tools (yfinance-backed) integrated into **original** tool modules: `market_tool` now includes get_stock_data, get_indicators (SMA), get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement, get_insider_transactions, get_news, get_global_news. Registration via `MCPServer.register_default_tools()`. No separate fundamental_tool/news_tool/register_tools files. Dependencies: yfinance, pandas, python-dateutil. Test `test_stage_2_2_trading_tools` verifies market_tool endpoints.

### Changed

- **Refactor (mcp/tools):** Removed duplicate `_now_iso()`: analyst_tool now imports `_now_iso` from market_tool. docs/file-structure.md updated to document shared helper and analyst_tool imports.
- **Python:** Minimum version relaxed to **3.9** (was 3.11) so `pip install -e ".[dev]"` works on systems with Python 3.9. Type hints use `from __future__ import annotations` and `Optional[str]` where needed for 3.9 compatibility.
- **MCP tools:** Required params must be passed in payload—no UI or client-side defaults. Parameter names reflect usage: **symbol** (security id), **limit** (max articles/items), **as_of_date** (reference date for lookback). get_indicators in analyst_tool; get_news(symbol, limit); get_global_news(as_of_date, look_back_days, limit). Payload may still accept legacy keys (ticker, count, curr_date) for backward compatibility. Docs and backend aligned with implementation.
- **MCP tool signatures:** Tool functions take **explicit parameters** (e.g. get_stock_data(symbol, start_date, end_date), get_news(symbol, limit, ...), get_global_news(as_of_date, look_back_days, limit), get_indicators(symbol, indicator, as_of_date, look_back_days)); MCP layer decomposes payload in register_default_tools.
- **Code quality (python-review):** Ruff and black added to dev deps; `[tool.ruff]` and `[tool.black]` in pyproject.toml (target Python 3.9+). market_tool and analyst_tool log exceptions before returning `{"error": str(e)}`; get_global_news logs query failures at debug. file_tool.read_file validates `path` in payload (clear error if missing). Situation memory constructor uses `_config` (reserved, unused); save/load use `encoding="utf-8"`. Type hints: `dict`/`list`/`Callable` from collections.abc where applicable; tests use UTF-8 when loading JSON.

### Fixed

- **MCP server:** `register_default_tools()` now imports `file_tool` first and registers optional tools (`market_tool`, `analyst_tool`) only when their imports succeed, so stage 2.1/2.2 tests pass in environments where pandas (or other optional deps) are not installed.

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
