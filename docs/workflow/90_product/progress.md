# Progress Document

Work breakdown (slices/stages), runnable verification commands, solved repeated errors, and pointers to changelog. **Update this document when new changes are introduced** (work breakdown, errors). **Update [CHANGELOG.md](../../../CHANGELOG.md) at repo root** when making user-visible or notable changes (features, fixes, refactors, config, dependencies).

---

## Work breakdown — slices and stages

Development proceeds in **slices**; each slice is a runnable checkpoint. Tests live in `tests/test-stages.py`. Run full suite: `pytest tests/test-stages.py -v`. Planner now supports capped planner rounds (`MAX_RESEARCH_ROUNDS`, default 2) via an LLM-based planner sufficiency check; unresolved responder-side confidence hooks remain future work.

**Layered symbol resolution (v4):** `util/planner_symbol_resolution.py` orchestrates deterministic aliases (`database/symbol_resolution_aliases.json`), optional LLM + Yahoo meta + OpenFIGI (`OPENFIGI_API_KEY`), `unresolved` financial skips; `pytest tests/test_symbol_resolution.py -v`.

**Implementation notes (AAPL-trace fixes):** SQL bind `params` accept list/tuple/dict; analyst blocks raw OHLCV indicators and locks symbols to planner resolution; default `E2E_TIMEOUT_SECONDS=180` and 408 body mention polling `GET /conversations/{id}`; WebSearcher uses resolved symbols before fund catalog, skips ETFdb for `equities`, Stooq falls back bare ticker, news/AV soft caps + cooldown; `kg_tool.get_relations` exact-first Cypher + optional `prefer_dataset`; librarian summary user content includes retrieval counts; interaction `TRACE` ids are globally monotonic. Golden checklist: [test_plan.md](../../shared/test_plan.md).

**Implementation notes (Codex / NVDA trace follow-ups):** `util/answer_coverage.py` + planner override when price + SQL/metrics; `util/timeseries_metrics.py` on Librarian SQL; WebSearcher Yahoo `get_price` + optional `get_fundamental`, Stooq after Yahoo for US-style tickers, `news_synthetic` / `news_confidence`; analyst batch-skip on AV cooldown; `market_tool.alpha_vantage_cooldown_active()`. Tests: `pytest tests/test_timeseries_metrics.py -v`.

**Git hooks:** `./scripts/install-git-hooks.sh` sets `core.hooksPath=scripts/git-hooks`; `pre-commit` runs `scripts/review_staged_for_commit.py` (secret path blocks, cohesion-by-directory hints, `ruff check` on staged `.py` when `ruff` is on PATH). Cohesion/coupling *edits* use Cursor rule `git-commit-cohesion-review` and `docs/workflow/git-commit-cohesion-review.md`.

**MCP backend gating (no placeholder data):** Without `MILVUS_URI` / `NEO4J_URI` / `DATABASE_URL`, vector/kg/sql tools return explicit errors or empty search results—not synthetic rows or graph nodes. `llm/static_client.py` supplies `StaticLLMClient` for tests; `tests/test-stages.py` imports MCP tools from `openfund_mcp`.

**Layering / cohesion refactor:** [dependency-contract.md](../02_planning/dependency-contract.md) documents import direction. `extract_symbol_from_query` moved to `util/symbol_query_extract.py` (no `util` → `agents`). Planner split: `planner_types`, `planner_formatting`, `planner_decompose`, `planner_sufficiency`, slim `planner_agent.py`. WebSearcher helpers in `agents/websearch_helpers.py`. Symbol resolution JSON cache in `util/symbol_resolution/cache_io.py`. `data_manager/` tree removed from file-structure (package not in repo); ingestion = `scripts/data_loader.py`.

### Slice summary

| Slice | What you add | Runnable checkpoint |
|-------|----------------|---------------------|
| 1 | Config, MessageBus, ConversationManager (1.1–1.3) | `main.py` runs; stage_1_2 and stage_1_3 tests pass |
| 2 | MCP server/client, file_tool (2.1), trading tools (2.2), situation memory (2.3) | stage_2_1, stage_2_2, stage_2_3 tests pass |
| 3 | ACLMessage, BaseAgent, Planner (1 step), Librarian (file_tool), Responder (stub) | `python main.py --e2e-once` completes one conversation |
| 4 | vector_tool, kg_tool, sql_tool (env-gated errors / empty results without backends); full Librarian | E2E with Librarian using three tools |
| 5 | WebSearcher, Analyst; Planner sends to all three | E2E with five agents, initial planner round |
| 6 | SafetyGateway | E2E with process_user_input; bad input rejected |
| 7 | REST: create_app, POST /chat, GET /conversations | curl POST /chat returns 200 JSON |
| 8 | OutputRail in Responder | Response text varies by user_profile |
| 9 | WebSocket /ws | GET and WebSocket work |

### Stage → test function and runnable command

| Stage | Slice | Test function | Runnable command |
|-------|-------|---------------|------------------|
| 1.1 | 1 | — | `PYTHONPATH=. python main.py` |
| 1.2 | 1 | `test_stage_1_2` | `pytest tests/test-stages.py -k stage_1_2 -v` |
| 1.3 | 1 | `test_stage_1_3`, `test_stage_1_3_data_sources_persist`, `test_stage_1_3_merge_data_sources_partial_round2` | `pytest tests/test-stages.py -k stage_1_3 -v` |
| 2.1 | 2 | `test_stage_2_1` | `pytest tests/test-stages.py -k stage_2_1 -v` |
| 2.2 | 2 | `test_stage_2_2_trading_tools` | `pytest tests/test-stages.py -k stage_2_2 -v` |
| 2.3 | 2 | `test_stage_2_3_situation_memory`, `test_stage_2_3_situation_memory_load_from_dir_missing` | `pytest tests/test-stages.py -k stage_2_3 -v` |
| 3.1 | 3 | `test_stage_3_1` | `pytest tests/test-stages.py -k stage_3_1 -v` |
| 3.2 | 3 | `test_stage_3_2` | `pytest tests/test-stages.py -k stage_3_2 -v` |
| 3.3 | 3 | `test_stage_3_3` | `pytest tests/test-stages.py -k stage_3_3 -v` |
| 4.1 | 4 | `test_stage_4_1` | `pytest tests/test-stages.py -k stage_4_1 -v` |
| 4.2 | 4 | `test_stage_4_2` | `pytest tests/test-stages.py -k stage_4_2 -v` |
| 4.3 | 4 | `test_stage_4_3` | `pytest tests/test-stages.py -k stage_4_3 -v` |
| 5.1 | 5 | `test_stage_5_1` | `pytest tests/test-stages.py -k stage_5_1 -v` |
| 5.2 | 5 | `test_stage_5_2` | `pytest tests/test-stages.py -k stage_5_2 -v` |
| 5.3 | 5 | `test_stage_5_3` | `pytest tests/test-stages.py -k stage_5_3 -v` |
| 5.4 | 5 | `test_stage_5_4` | `pytest tests/test-stages.py -k stage_5_4 -v` |
| 6.1 | 6 | `test_stage_6_1` | `pytest tests/test-stages.py -k stage_6_1 -v` |
| 7.1 | 7 | `test_stage_7_1` (optional) | curl POST /chat; GET /conversations/{id} |
| 8.1 | 8 | `test_stage_8_1` | `pytest tests/test-stages.py -k stage_8_1 -v` |
| 9.1 | 9 | `test_stage_9_1` (optional) | WebSocket client; GET |
| 10.1 | E2E | `test_stage_10_1` | `PYTHONPATH=. python main.py --e2e-once` (subprocess, exit 0) |
| 10.2 | Optional | `test_stage_10_2_llm_static_mock`, `test_stage_10_2_planner_uses_prompts_module`, `test_stage_10_2_static_client_complete_passthrough`, `test_stage_10_2_responder_llm_prompt`, `test_stage_10_2_librarian_llm_prompt`, `test_stage_10_2_websearcher_llm_prompt`, `test_stage_10_2_analyst_llm_prompt`, `test_stage_10_2_static_client_select_tools_returns_empty`, `test_stage_10_2_planner_sends_only_to_chosen_agents_with_decomposed_query`, `test_stage_10_2_librarian_tool_selection_when_llm_returns_tool_calls`, `test_stage_10_2_websearcher_tool_selection_when_llm_returns_tool_calls`, `test_stage_10_2_analyst_tool_selection_when_llm_returns_tool_calls` | Runtime API/startup requires live LLM (`LLM_API_KEY` + `pip install [llm]`); StaticLLMClient is test/e2e fallback only. All five agents accept optional `llm_client`; DeepSeek via `LLM_BASE_URL`; specialists use LLM tool selection when `llm_client` set, else content-key dispatch. |

Per-slice and per-stage behavior details: [prd.md](prd.md), [backend.md](../02_planning/backend.md), and [test_plan.md](../../shared/test_plan.md). Test assertions per stage: see `tests/test-stages.py`.

---

## Solved repeated errors

*(Record recurring issues and their fixes here so the same mistakes are not repeated.)*

- **WebSearcher 408 after `_llm_data_search_fallback`:** Same pattern as news fallback — missing `WEBSEARCHER_LLM_FALLBACK_SYSTEM` in `llm/prompts.py` caused ImportError when all market tools failed. Added prompt; `_extract_price_from_text` may still pick up a dollar amount from LLM text.
- **Neo4j large-bundle fresh-all import exceeded runtime target:** Implemented hybrid loader in `scripts/data_loader.py` with `NEO4J_FRESH_IMPORT_MODE` (`auto`/`offline`/`online`). `fresh-all` now prefers offline `neo4j-admin database import full` and falls back to online batched Bolt import only in `auto`. Online loader path in `openfund_mcp/tools/kg_tool.py` now uses batched `UNWIND` writes grouped by label set (`:LABEL`) and relationship type (`:TYPE`) with configurable `NEO4J_LOAD_BATCH_SIZE` (default 10000). Added benchmark runner `scripts/benchmark_neo4j_load.py` for runtime + row-rate + pass/fail reporting against the 180s target.
- **WebSearcher fund=WHAT / no data:** Planner sometimes passes `fund` or normalizes to WHAT (from "What is the price..."). `_resolve_symbols` treated any 1–5 letter uppercase string as ticker → stooq/Yahoo queried WHAT.US and failed. Fix: `_TICKER_BLOCKLIST` + skip blocklisted fund so `fund_catalog_tool.search(query)` runs; `_normalize_symbol` scans for known tickers (SPY, QQQ, …) in text before taking first token.

- **sql_tool.run_query → openfund_stooq_tool:** In an earlier server layout, importing `sql_tool as st` then rebinding `st` to the stooq module broke sql_tool closures. **Fix (current tree):** register stooq/Yahoo/ETFdb from `openfund_mcp.tools` using a distinct name (e.g. `stooq_mod`) so `sql_tool` is never aliased away. **WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM** avoids ImportError in `_resolve_conflict_with_llm`. **fund_catalog_tool.search** is registered with the other WebSearcher tools in `openfund_mcp/mcp_server.py`.

- **Yahoo returns all null in logs:** If `yahoo_finance_tool` / `stooq_tool` / `etfdb_tool` are not registered, WebSearcher sees empty results. **Fix:** ensure those modules load from **`openfund_mcp.tools`** in `register_default_tools()` (package `openfund_mcp`, not a shadowed `mcp`); verify `get_registered_tool_names()` includes them when dependencies are present.

- **WebSearcher 408 after MCP errors:** If every MCP `call_tool` returned `error='CallToolResult' object has no attribute 'is_error'`, the WebSearcher then entered `_llm_news_fallback`, which imported `WEBSEARCHER_NEWS_FALLBACK_SYSTEM` from `llm/prompts` — missing constant caused `ImportError` in the agent thread and POST /chat timed out (408). **Fix:** (1) `openfund_mcp/mcp_client.py` uses `_tool_result_is_error` / `_tool_result_error_text` to support MCP SDKs that expose `isError` or only content blocks, not `is_error`. (2) `llm/prompts.py` defines `WEBSEARCHER_NEWS_FALLBACK_SYSTEM` aligned with `_llm_news_fallback` line format (`Headline | summary` or title-only per line).

- **Python 3.9 and StrEnum:** `enum.StrEnum` exists from 3.11. Use `class Performative(str, Enum)` in `a2a/acl_message.py` for 3.9 compatibility.
- **Slice 3 implemented:** InMemoryMessageBus, ConversationManager (create/get/register_reply/broadcast_stop + persistence), PlannerAgent (one step → librarian, forwards INFORM → responder), LibrarianAgent (file_tool), ResponderAgent (stub), `main.py --e2e-once`.

- **Conversation `data_sources`:** Persisted on `memory/<user_id>/conversations.json` with fixed keys `librarian`, `websearcher`, `analyst` (each `{}` until merged). `util/specialist_snapshot.snapshot_specialist_payload` / `build_data_sources_from_collected` produce bounded JSON-safe snapshots; `ConversationManager.merge_data_sources` merges by agent and saves; `PlannerAgent` invokes this when handing off to the Responder (before `del _collected`), so round-2 partial updates do not wipe round-1 agents. GET `/conversations/{id}` returns `data_sources`. Tests: `test_stage_1_3_data_sources_persist`, `test_stage_1_3_merge_data_sources_partial_round2` (run with `pytest tests/test-stages.py -k stage_1_3 -v`).

- **Planner symbol resolution (some_plan.md):** `PlannerAgent` resolves listings + `by_tool` before `decompose_task` (implementation in `util/planner_symbol_resolution.py`: routing/issuers, per-tool market registry, JSON cache helpers), caches at `{MEMORY_STORE_PATH}/symbol_resolution_cache.json`, passes `symbol_resolution` on all specialist REQUESTs; when `status` is `resolved`, also passes `resolution_listings`, `resolution_symbol_type`, `resolution_canonical_name`. `WebSearcherAgent` skips doomed MCP calls (e.g. Alpha Vantage paths for CN listings). Catalog: `database/symbol_resolution_known_issuers.json` (`symbol_type` per entity). Routing: `database/symbol_resolution_routing.json` (aliases/symbols → cache_key; `ticker_symbol_types`). **Schema v3:** graph-aligned `symbol_type` (`cryptos` | `currencies` | `equities` | `etfs` | `funds` | `indices` | `moneymarkets` | `unknown`); legacy `etf`/`stock` normalize to `etfs`/`equities`; ETFdb only for `etfs`. **Partial answers:** after max rounds, if sufficiency is still insufficient but `_collected_has_answer_signal`, planner wraps `_format_final` with caveats and sets `partial_insufficient`; `ResponderAgent` then keeps that body instead of forcing the single phrase “Insufficient information.” Sufficiency aggregation includes `normalized_fund` price lines. Tests: `pytest tests/test_symbol_resolution.py tests/test_responder_partial.py -v`.
- **Slice 4 implemented:** vector_tool, kg_tool, sql_tool (mocks when backends unset); full Librarian (retrieve_documents, retrieve_knowledge_graph, combine_results; planner REQUEST content keys: `vector_query`, `fund`/`entity`, `sql_query`; optional LLM tool selection). Tests: test_stage_4_1, test_stage_4_2, test_stage_4_3.
- **Slice 5 implemented:** WebSearcherAgent (handle_message, fetch_market_data, fetch_sentiment, fetch_regulatory via market_tool); AnalystAgent (handle_message, analyze stub, needs_more_data, sharpe_ratio, max_drawdown, monte_carlo_simulation); Planner sends to all three specialists and aggregates INFORMs before forwarding to Responder. Planner now supports the planner sufficiency check (LLM-based) + refined planner round(s) capped by `MAX_RESEARCH_ROUNDS`. E2E: `main.py --e2e-once` runs five agents (planner, librarian, websearcher, analyst, responder). Tests: test_stage_5_1, test_stage_5_2, test_stage_5_3, test_stage_5_4.

- **Slice 6 (Stage 6.1) implemented:** SafetyGateway in `safety/safety_gateway.py`: validate_input (reject empty/whitespace-only, max length 10_000, UTF-8 printable/whitespace), check_guardrails (block list: e.g. "guaranteed return", "buy this stock now", "insider tip"), mask_pii (phone, email, SSN-like placeholders), process_user_input (validate → guardrails → mask_pii; raises SafetyError on failure). test_stage_6_1 passes.

- **Slice 7 (Stage 7.1) implemented:** REST API in `api/rest.py`: create_app() builds FastAPI app with POST /register, POST /login, POST /chat, GET /conversations/{id}, and WebSocket /ws. Shared state on `app.state`: bus, manager, safety_gateway, e2e_timeout_seconds. POST /chat validates body (`ChatRequest`: query required; user_profile beginner|long_term|analyst — invalid returns 422; user_id, conversation_id optional — no `path` field). Runs SafetyGateway.process_user_input, creates or gets conversation, sends REQUEST to planner, blocks on completion_event; returns 200/408/400/422/404 as documented in backend.md. GET /conversations/{id} returns conversation state JSON including `data_sources` when merged. test_stage_7_1 passes (TestClient, invalid user_profile → 422, real flow with timeout).

- **Slice 8 (Stage 8.1) implemented:** OutputRail in `output/output_rail.py`: check_compliance(text) returns ComplianceResult(passed=True) unless text contains explicit buy/sell-advice phrases (block list aligned with safety_gateway: e.g. "buy this stock now", "sell immediately", "guaranteed return", "insider tip"); format_for_user(text, user_profile) adapts tone/disclaimers by profile (beginner: disclaimer "This is not investment advice."; long_term: line about long-term horizon; analyst: "Analysis:" prefix, technical content preserved). ResponderAgent uses OutputRail when set: on INFORM with final_response and conversation_id, gets user_profile from content (default "beginner"), formats via format_for_user, runs check_compliance, appends disclaimer if not passed, registers reply with formatted final_response and broadcast_stop. Planner stores user_profile per conversation when handling REQUEST and passes it in INFORM to responder. API includes user_profile in REQUEST content to planner; create_app() and main._run_e2e_once() wire ResponderAgent with output_rail=OutputRail(). test_stage_8_1 passes (format_for_user differs by profile; check_compliance passed/failed).

- **Slice 9 (Stage 9.1) implemented:** WebSocket /ws in `api/websocket.py` and `api/rest.py`: same flow as POST /chat. handle_websocket receives one JSON message (query required; optional conversation_id, user_profile, user_id — same fields as REST, no `path`), validates, runs SafetyGateway, create or get conversation, sends REQUEST to planner, waits on completion_event, then sends one terminal event and closes. test_stage_9_1 passes (TestClient websocket_connect, send_json, receive_json).

- **Stage 10.1 (E2E smoke) implemented:** test_stage_10_1 runs `main.py --e2e-once` in a subprocess (timeout 60s, PYTHONPATH set) and asserts exit code 0. Runnable: `pytest tests/test-stages.py -k stage_10_1 -v`.

- **Stage 10.2 (LLM integration) implemented:** `llm` module provides LLMClient protocol, StaticLLMClient (mock), and get_llm_client(config). Runtime `get_llm_client` requires `LLM_API_KEY` and `openfund-ai[llm]`; missing key raises `ValueError`, missing dependency raises `ImportError`. API startup uses this runtime path (live LLM required). `main.py --e2e-once` has an explicit fallback to StaticLLMClient if live LLM init fails. PlannerAgent accepts optional llm_client and uses it in decompose_task; fallback to fixed three steps on parse failure/unavailable client. test_stage_10_2_llm_static_mock asserts the missing-key error path and that Planner with StaticLLMClient still yields runnable steps. Runnable: `pytest tests/test-stages.py -k stage_10_2 -v`.

- **LLM prompts module (Stage 10.2):** Central prompts in `llm/prompts.py`: PLANNER_DECOMPOSE, LIBRARIAN_SYSTEM, WEBSEARCHER_SYSTEM, ANALYST_SYSTEM, RESPONDER_SYSTEM (aligned with PRD and user-flow). Planner uses PLANNER_DECOMPOSE via LiveLLMClient. Responder optionally uses RESPONDER_SYSTEM when llm_client is set (`complete()`). Librarian/WebSearcher/Analyst prompts are actively used for summary generation and tool-selection workflows when llm_client is set. Tests: test_stage_10_2_planner_uses_prompts_module, test_stage_10_2_static_client_complete_passthrough, test_stage_10_2_responder_llm_prompt.

- **Full LLM integration (all five agents):** LibrarianAgent, WebSearcherAgent, and AnalystAgent now accept optional `llm_client` (same pattern as PlannerAgent and ResponderAgent). When set, Librarian calls `complete(LIBRARIAN_SYSTEM, get_librarian_user_content(query, combined_data))` after building combined docs/graph/sql and adds a `summary` key to INFORM content. WebSearcher calls `complete(WEBSEARCHER_SYSTEM, get_websearcher_user_content(query, fetched_data))` after fetching market/sentiment/regulatory and adds `summary` to INFORM. Analyst calls `complete(ANALYST_SYSTEM, get_analyst_user_content(structured_data, market_data))` after `analyze()` and adds `summary` to the analysis result. Wiring: `api/rest.py` and `main.py` pass the same `llm_client` from `get_llm_client(config)` to all five agents. DeepSeek is supported via `LLM_BASE_URL` (e.g. `https://api.deepseek.com`) and `LLM_MODEL=deepseek-chat`; API key from env (`LLM_API_KEY`) only, never committed. Prompt helpers in `llm/prompts.py`: `get_librarian_user_content`, `get_websearcher_user_content`, `get_analyst_user_content`, and `_data_summary` for building user messages. Tests: test_stage_10_2_librarian_llm_prompt, test_stage_10_2_websearcher_llm_prompt, test_stage_10_2_analyst_llm_prompt.

- **Design / target behavior (implemented):** Planner selects which agents to call and decomposes the user query into agent-specific sub-queries; specialists use LLM + tool descriptions to choose tools and parameters when `llm_client` is set, else content-key dispatch. See [backend.md](../02_planning/backend.md) and [agent-tools-reference.md](../03_tools_and_mcp/agent-tools-reference.md). Tests: `test_stage_10_2_librarian_tool_selection_when_llm_returns_tool_calls`, `test_stage_10_2_websearcher_tool_selection_when_llm_returns_tool_calls`, `test_stage_10_2_analyst_tool_selection_when_llm_returns_tool_calls`; content-key dispatch when llm_client is None or select_tools returns [] (stage 5.3, 5.4, 10.2).

- **Data populate seed removed:** the default runtime (`./scripts/run.sh`) no longer runs `python -m data_manager populate` / demo baseline seeding.
- **Unified loader-backed ingestion implemented:** `scripts/data_loader.py` now populates SQL/Neo4j/Milvus from `database/stats_data`, `database/graph_data/neo4j_export`, and `database/text_data`; `scripts/run.sh` / `run.ps1` call the loader and map `--funds` modes to loader `--load-mode`.

- **MCP `register_default_tools` failing when pandas missing:** `register_default_tools()` imported all tools in one block; if `analyst_tool` (or `market_tool`) failed to import (e.g. missing pandas), stage 2.1/2.2 tests failed. Fix: import `file_tool` first and register it; register `market_tool` and `analyst_tool` only inside try/except ImportError so optional tools are skipped when deps are missing.

- **Community-common tools implemented:** Per [agent-tools-reference.md](../03_tools_and_mcp/agent-tools-reference.md) and [backend.md](../02_planning/backend.md): kg_tool (`get_node_by_id`, `get_neighbors`, `get_graph_schema`), sql_tool (`explain_query`, `export_results`, `connection_health_check`), vector_tool (`get_by_ids`, `upsert_documents`, `health_check`), and `get_capabilities` (openfund_mcp/tools/capabilities.py) are implemented and registered in `register_default_tools`. Mock behavior when env unset; tests in tests/test_kg_tool.py, test_sql_tool.py, test_vector_tool.py, test_capabilities.py. Backend maintenance commands (populate, sql, neo4j, milvus) are provided via `data_manager/backend_cli.py` and `add_backend_subcommands` under `python -m data_manager`.

- **Deferred community-common tools implemented:** kg_tool: `shortest_path`, `get_similar_nodes`, `fulltext_search`, `bulk_export`, `bulk_create_nodes`; vector_tool: `create_collection_from_config`. All registered in `register_default_tools`; mock when NEO4J_URI/MILVUS_URI unset. Tests in tests/test_kg_tool.py and tests/test_vector_tool.py. Fulltext search requires an existing Neo4j fulltext index; bulk_export allows only read-only Cypher (MATCH/CALL).

- **DataManagerAgent Phase 1 (Collector) implemented:** `data_manager/collector.py`: DataCollector class fetches data from market_tool and analyst_tool for OHLCV, balance_sheet, cashflow, income_statement, insider_transactions, indicators, and news. Saves raw JSON files to `datasets/raw/{symbol}/` with metadata. `data_manager/tasks.py`: CollectionTask dataclass and COLLECTION_TASKS registry. CLI: `python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15`, `python -m data_manager global-news`, `python -m data_manager status`, `python -m data_manager list`. Loader-first schema docs: [stats-data-schema.md](../../data_prep/stats-data-schema.md), [graph-data-schema.md](../../data_prep/graph-data-schema.md), [text-data-schema.md](../../data_prep/text-data-schema.md).

- **Interactive chat and run.sh:** `scripts/chat_cli.py` is a terminal chat client that POSTs to the running API `/chat` endpoint. It prompts "You: ", sends the line (with optional `--port`, `--profile`), prints "Assistant: <response>", and handles 200/408/400/422/404/500 and connection errors. `./scripts/run.sh` by default starts the API in the background, waits for it (curl /openapi.json), runs `chat_cli.py` in the foreground, and on chat exit kills the server (trap EXIT/INT/TERM). Use `--no-chat` to start the API only (previous behavior: `exec main.py --serve`).

- **Tools and LLM diagnostics:** On startup, api/rest logs "MCP tools registered: [...]" and "LLM: model=..., base_url=...". mcp_server logs "market_tool skipped" / "analyst_tool skipped" with ImportError when optional tools are not registered. GET /health returns `{tools: [...], llm_configured: bool}`. MCPClient.get_registered_tool_names() returns sorted list of registered tool names. Librarian, WebSearcher, and Analyst filter tool descriptions and allowed sets to only registered tools (get_*_tool_descriptions(registered_tool_names), filter_tool_calls_to_allowed with allowed ∩ registered) so the LLM does not suggest tools that are missing. docs/demo.md has Setup checklist and expanded troubleshooting; README links to it.

- **FastMCP single path (openfund_mcp):** MCP package renamed from `mcp` to `openfund_mcp` so the official `mcp` SDK can be used. All tool access goes through the MCP server: API/agents use **MCPClient** to spawn the server as a subprocess (`python -m openfund_mcp`) and connect over stdio; external clients (e.g. Claude Desktop) run the same server. Config: `MCP_SERVER_COMMAND`, `MCP_SERVER_ARGS`, `MCP_SERVER_CWD` in config/config.py. Tests use in-process **MCPServer** + **MCPClient(server)**; production uses no MCPServer instance. See [mcp-server.md](../03_tools_and_mcp/mcp-server.md) and [backend.md](../02_planning/backend.md).

- **Single MCP server file (no fastmcp_server):** FastMCP stdio logic was merged into `openfund_mcp/mcp_server.py`. That file now provides both **MCPServer** (register_default_tools, dispatch) for in-process tests and **FastMCP** app + **run_stdio()** for production and external clients. `openfund_mcp/__main__.py` calls `run_stdio()` from mcp_server. The separate `fastmcp_server.py` was removed. Tool implementations remain in `openfund_mcp/tools/`.

- **Documentation (ENV):** [ENV.md](../../shared/ENV.md) is the env var reference. Operational runbooks or CONTRIBUTING files, if added under `docs/shared/` or repo root, should be listed in [README.md](../../../README.md); they are not required for the core workflow docs.

- **DataManagerAgent Phase 2-4 (Distributor, Classifier, Transformer) implemented:**
  - `data_manager/schemas.py`: PostgreSQL DDL (stock_ohlcv, company_fundamentals, financial_statements, insider_transactions, technical_indicators); UPSERT templates; Neo4j Cypher templates (Company, Sector, Industry, Officer nodes and edges); Milvus collection config.
  - `data_manager/classifier.py`: DataClassifier routes task_types to target databases (postgres, neo4j, milvus) with STATIC_ROUTING (single target) and MULTI_TARGET (e.g. info → all three).
  - `data_manager/transformer.py`: DataTransformer converts raw data: to_postgres_rows (CSV/JSON → table rows), to_neo4j_nodes_edges (extract Company, Sector, Industry, Officer nodes + relationships), to_milvus_docs (news/description → vector documents with content for embedding).
  - `data_manager/distributor.py`: DataDistributor reads local JSON files, classifies, transforms, and writes to PostgreSQL (sql_tool.run_query), Neo4j (kg_tool.query_graph), and Milvus (vector_tool.upsert_documents). Moves files to processed/failed after.
  - CLI: `python -m data_manager distribute --symbol NVDA`, `python -m data_manager distribute --all`, `python -m data_manager distribute --file path/to/file.json`. Options: `--no-move` (keep files in raw/), `--verbose` (show per-file details).
  - Unified ingestion: `python scripts/data_loader.py` from `database/stats_data`, `database/graph_data/neo4j_export`, `database/text_data` (see [revision_plan.md](../../data_prep/revision_plan.md)). Optional `data_manager distribute-funds` remains for legacy combined-fund JSON if you provide your own file. Schema docs: [stats-data-schema.md](../../data_prep/stats-data-schema.md), [graph-data-schema.md](../../data_prep/graph-data-schema.md), [text-data-schema.md](../../data_prep/text-data-schema.md).

---

## Current implementation status (verified from code)

### Backend tool integrations (implemented; env-gated)

- **openfund_mcp/tools/kg_tool.py:** `query_graph(cypher, params)` — uses neo4j driver with NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD when set; runs Cypher with params; returns rows (and nodes/edges for get_relations). When NEO4J_URI is unset, returns mock. On error returns {"error": "..."}.
- **openfund_mcp/tools/sql_tool.py:** `run_query(query, params)` — uses psycopg2 with DATABASE_URL when set; parameterized execution; returns dict with rows, schema, params. When DATABASE_URL is unset, returns mock data. On error returns {"error": "..."}.
- **openfund_mcp/tools/vector_tool.py:** `search(query, top_k, filter)` — when MILVUS_URI set: connects to Milvus, lazy-loads sentence-transformers embedding model, embeds query, searches collection; returns list of docs with scores. When MILVUS_URI is unset, returns mock data. `index_documents(docs)` embeds and upserts; returns indexed count; when MILVUS_URI unset returns error.

**Install backends (optional):** `pip install -e ".[backends]"` or `pip install neo4j psycopg2-binary pymilvus sentence-transformers`.

**Live tool validation:** `pytest tests/test_agent_tools_reference.py` verifies every tool in [agent-tools-reference.md](../03_tools_and_mcp/agent-tools-reference.md) is registered and callable with minimal payloads. A separate third-party API sweep script may be added later; any generated **`api-test-results.md`** is operational output (do not edit by hand). See [test_plan.md](../../shared/test_plan.md).

---

## Future implementation tracker

*(Functions that currently raise NotImplementedError, plus planned items not yet added. Abstract methods and intentional "use TestClient" wrappers in api/rest.py are excluded.)*

### Stubs (NotImplementedError today)

- **openfund_mcp/tools/file_tool.py:** `list_files(prefix)` — list paths under MCP_FILE_BASE_DIR + prefix (e.g. os.listdir/glob); return list of relative paths.
- **openfund_mcp/tools/market_tool.py:** `fetch(fund_or_symbol)` — wrap get_stock_data or get_fundamentals; add timestamp; return dict.
- **openfund_mcp/tools/market_tool.py:** `fetch_bulk(symbols)` — loop symbols, call existing vendor-routed helpers; return dict keyed by symbol with timestamp.
- **openfund_mcp/tools/market_tool.py:** `search_web(query)` — call Tavily API if TAVILY_API_KEY set; normalize to list of dicts with timestamp; else fallback (e.g. get_news with date range).
- **openfund_mcp/tools/analyst_tool.py:** `run_analysis(payload)` — if ANALYST_API_URL set: POST payload with optional ANALYST_API_KEY; return response JSON; else return stub dict.
- **agents/responder_agent.py:** `evaluate_confidence(analysis)` — return float from analysis.get("confidence") or computed from distribution/indicators. **Current behavior:** Not implemented (NotImplementedError); only the Planner runs the planner sufficiency check (via LLM). Responder formats the final answer and does not use confidence to decide termination.
- **agents/responder_agent.py:** `should_terminate(confidence)` — compare to RESPONDER_CONFIDENCE_THRESHOLD; return True to stop, False to request a refined planner round. **Current behavior:** Not implemented (NotImplementedError). See backend.md: Responder does not use confidence.
- **agents/responder_agent.py:** `format_response(analysis, user_profile)` — build string from analysis (e.g. summary); call OutputRail.format_for_user; return formatted string.
- **agents/responder_agent.py:** `request_refinement(reason)` — return ACLMessage(REQUEST, sender=responder, receiver=planner, content={"reason": reason, "conversation_id": ...}) for a refined planner round.

### Planned additions (not yet in code)

- **agents/planner_agent.py:** `resolve_conflicts(agent_outputs)` — reconcile when librarian/websearcher/analyst disagree (e.g. LLM merge or rule-based preference).

### Suggested implementation order

1. **Low effort:** file_tool.list_files (directory listing under base_dir).
2. **Unify market:** market_tool.fetch, fetch_bulk, search_web (wrap existing vendor-routed/Tavily).
3. **Custom analyst:** analyst_tool.run_analysis (HTTP POST to ANALYST_API_URL).
4. **Backends:** kg_tool, sql_tool, vector_tool are already implemented; validate with live Neo4j/Postgres/Milvus when instances are available.
5. **Phase 2:** ResponderAgent confidence/termination/format/refinement and PlannerAgent resolve_conflicts (planner sufficiency check + refined planner rounds already exist; conflict reconciliation is still pending).

### Not to implement (by design)

- **a2a/message_bus.py:** MessageBus abstract methods — InMemoryMessageBus implements them.
- **agents/base_agent.py:** BaseAgent.handle_message — abstract; each agent implements.
- **api/rest.py:** post_chat, get_conversation — use FastAPI TestClient or real endpoints; left as NotImplementedError by design.

---

## PRD coverage and risks

**PRD coverage:** The plan meets the PRD for MVP. All functional requirements (FR1–FR7), constraints (C1–C3), and acceptance criteria (AC1–AC5) are covered by slices 1–10 and the contracts in [backend.md](../02_planning/backend.md) and [user-flow.md](../00_overview/user-flow.md). The PRD column in [project-status.md](project-status.md) maps each capability to the relevant FR/AC.

**Risks and dependencies:**
- **Slice order:** Ensure stage 2.1 (file_tool) is green before slice 3; SafetyGateway (6) before REST (7). Slices 3–5 depend on MCP and agents; 7–9 on the API layer.
- **MCP/backends unavailable:** Use mocks for vector_tool, kg_tool, sql_tool, and market_tool (slices 4–5). Timeout behavior (408) and E2E timeout config are in backend.md.
- **Phase 2:** LLM integration (decompose_task, planner sufficiency check, capped refined planner rounds) is in Stage 10.2. Remaining Phase-2 work is primarily responder confidence hooks and planner conflict reconciliation; see project-status.md.
- **Slice 3 implementation:** Planner handles INFORM from librarian and forwards to Responder with `final_response`; `main.py --e2e-once` uses a temp file as the query path so file_tool.read_file succeeds and one conversation completes (exit 0). E2E timeout is non-fatal per backend.md.
