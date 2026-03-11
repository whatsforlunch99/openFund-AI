# Progress Document

Work breakdown (slices/stages), runnable verification commands, solved repeated errors, and pointers to changelog. **Update this document when new changes are introduced** (work breakdown, errors). **Update [CHANGELOG.md](../CHANGELOG.md) at repo root** when making user-visible or notable changes (features, fixes, refactors, config, dependencies).

---

## Work breakdown — slices and stages

Development proceeds in **slices**; each slice is a runnable checkpoint. Tests live in `tests/test-stages.py`. Run full suite: `pytest tests/test-stages.py -v`. Planner now supports capped planner rounds (`MAX_RESEARCH_ROUNDS`, default 2) via an LLM-based planner sufficiency check; unresolved responder-side confidence hooks remain future work.

### Slice summary

| Slice | What you add | Runnable checkpoint |
|-------|----------------|---------------------|
| 1 | Config, MessageBus, ConversationManager (1.1–1.3) | `main.py` runs; stage_1_2 and stage_1_3 tests pass |
| 2 | MCP server/client, file_tool (2.1), trading tools (2.2), situation memory (2.3) | stage_2_1, stage_2_2, stage_2_3 tests pass |
| 3 | ACLMessage, BaseAgent, Planner (1 step), Librarian (file_tool), Responder (stub) | `python main.py --e2e-once` completes one conversation |
| 4 | vector_tool, kg_tool, sql_tool (mocks); full Librarian | E2E with Librarian using three tools |
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
| 1.3 | 1 | `test_stage_1_3` | `pytest tests/test-stages.py -k stage_1_3 -v` |
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

Per-slice and per-stage behavior details: [prd.md](prd.md), [backend.md](backend.md), and [test_plan.md](test_plan.md). Test assertions per stage: see `tests/test-stages.py`.

---

## Solved repeated errors

*(Record recurring issues and their fixes here so the same mistakes are not repeated.)*

- **WebSearcher 408 after `_llm_data_search_fallback`:** Same pattern as news fallback — missing `WEBSEARCHER_LLM_FALLBACK_SYSTEM` in `llm/prompts.py` caused ImportError when all market tools failed. Added prompt; `_extract_price_from_text` may still pick up a dollar amount from LLM text.
- **WebSearcher fund=WHAT / no data:** Planner sometimes passes `fund` or normalizes to WHAT (from "What is the price..."). `_resolve_symbols` treated any 1–5 letter uppercase string as ticker → stooq/Yahoo queried WHAT.US and failed. Fix: `_TICKER_BLOCKLIST` + skip blocklisted fund so `fund_catalog_tool.search(query)` runs; `_normalize_symbol` scans for known tickers (SPY, QQQ, …) in text before taking first token.

- **sql_tool.run_query → openfund_stooq_tool:** In `fastmcp_server._create_app`, `from openfund_mcp.tools import sql_tool as st` then later `st = _load_tool_module(...stooq...)` rebinding `st` broke all sql_tool @mcp.tool closures. Fix: use `stooq_mod` for stooq. **WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM** added to avoid ImportError in `_resolve_conflict_with_llm`. **fund_catalog_tool.search** registered by path alongside yahoo/stooq/etfdb.

- **Yahoo returns all null in logs:** Subprocess MCP server (`python -m openfund_mcp`) did not register `yahoo_finance_tool` / `stooq_tool` / `etfdb_tool` because the local package name `mcp` is shadowed by the installed MCP SDK. WebSearcher only adds tasks for tools in `get_registered_tool_names()`; unregistered tools left `yahoo_res` as `{}`, which `_summarize_yahoo_fundamental` prints as symbol None, etc. Fix: register those tools via `importlib.util.spec_from_file_location` from `mcp/tools/*.py` in `fastmcp_server._create_app` and `MCPServer.register_default_tools`.

- **WebSearcher 408 after MCP errors:** If every MCP `call_tool` returned `error='CallToolResult' object has no attribute 'is_error'`, the WebSearcher then entered `_llm_news_fallback`, which imported `WEBSEARCHER_NEWS_FALLBACK_SYSTEM` from `llm/prompts` — missing constant caused `ImportError` in the agent thread and POST /chat timed out (408). **Fix:** (1) `openfund_mcp/mcp_client.py` uses `_tool_result_is_error` / `_tool_result_error_text` to support MCP SDKs that expose `isError` or only content blocks, not `is_error`. (2) `llm/prompts.py` defines `WEBSEARCHER_NEWS_FALLBACK_SYSTEM` aligned with `_llm_news_fallback` line format (`Headline | summary` or title-only per line).

- **Python 3.9 and StrEnum:** `enum.StrEnum` exists from 3.11. Use `class Performative(str, Enum)` in `a2a/acl_message.py` for 3.9 compatibility.
- **Slice 3 implemented:** InMemoryMessageBus, ConversationManager (create/get/register_reply/broadcast_stop + persistence), PlannerAgent (one step → librarian, forwards INFORM → responder), LibrarianAgent (file_tool), ResponderAgent (stub), `main.py --e2e-once`.
- **Slice 4 implemented:** vector_tool, kg_tool, sql_tool (mocks when backends unset); full Librarian (retrieve_documents, retrieve_knowledge_graph, combine_results; content keys: path, vector_query, fund, sql_query). Tests: test_stage_4_1, test_stage_4_2, test_stage_4_3.
- **Slice 5 implemented:** WebSearcherAgent (handle_message, fetch_market_data, fetch_sentiment, fetch_regulatory via market_tool); AnalystAgent (handle_message, analyze stub, needs_more_data, sharpe_ratio, max_drawdown, monte_carlo_simulation); Planner sends to all three specialists and aggregates INFORMs before forwarding to Responder. Planner now supports the planner sufficiency check (LLM-based) + refined planner round(s) capped by `MAX_RESEARCH_ROUNDS`. E2E: `main.py --e2e-once` runs five agents (planner, librarian, websearcher, analyst, responder). Tests: test_stage_5_1, test_stage_5_2, test_stage_5_3, test_stage_5_4.

- **Slice 6 (Stage 6.1) implemented:** SafetyGateway in `safety/safety_gateway.py`: validate_input (reject empty/whitespace-only, max length 10_000, UTF-8 printable/whitespace), check_guardrails (block list: e.g. "guaranteed return", "buy this stock now", "insider tip"), mask_pii (phone, email, SSN-like placeholders), process_user_input (validate → guardrails → mask_pii; raises SafetyError on failure). test_stage_6_1 passes.

- **Slice 7 (Stage 7.1) implemented:** REST API in `api/rest.py`: create_app() builds FastAPI app with POST /register, POST /login, POST /chat, GET /conversations/{id}, and WebSocket /ws. Shared state on `app.state`: bus, manager, safety_gateway, e2e_timeout_seconds. POST /chat validates body (query required; user_profile must be one of beginner|long_term|analyst — invalid returns 422; user_id, conversation_id optional), runs SafetyGateway.process_user_input, creates or gets conversation, sends REQUEST to planner, blocks on completion_event; returns 200 (conversation_id, status, response, flow), 408 (timeout; conversation_id, flow), 400 (safety), 422 (validation), 404 (unknown conversation_id). GET /conversations/{id} returns conversation state JSON (id, user_id, initial_query, messages, status, final_response, created_at, flow). test_stage_7_1 passes (TestClient, invalid user_profile → 422, real flow with 5s timeout and optional path for file_tool).

- **Slice 8 (Stage 8.1) implemented:** OutputRail in `output/output_rail.py`: check_compliance(text) returns ComplianceResult(passed=True) unless text contains explicit buy/sell-advice phrases (block list aligned with safety_gateway: e.g. "buy this stock now", "sell immediately", "guaranteed return", "insider tip"); format_for_user(text, user_profile) adapts tone/disclaimers by profile (beginner: disclaimer "This is not investment advice."; long_term: line about long-term horizon; analyst: "Analysis:" prefix, technical content preserved). ResponderAgent uses OutputRail when set: on INFORM with final_response and conversation_id, gets user_profile from content (default "beginner"), formats via format_for_user, runs check_compliance, appends disclaimer if not passed, registers reply with formatted final_response and broadcast_stop. Planner stores user_profile per conversation when handling REQUEST and passes it in INFORM to responder. API includes user_profile in REQUEST content to planner; create_app() and main._run_e2e_once() wire ResponderAgent with output_rail=OutputRail(). test_stage_8_1 passes (format_for_user differs by profile; check_compliance passed/failed).

- **Slice 9 (Stage 9.1) implemented:** WebSocket /ws in `api/websocket.py` and `api/rest.py`: same flow as POST /chat. handle_websocket(websocket, bus, manager, safety_gateway, timeout_seconds) receives one JSON message (query required; optional conversation_id, user_profile, user_id, path), validates, runs SafetyGateway.process_user_input, create or get conversation, sends REQUEST to planner, waits on completion_event via run_in_executor, then sends one event (response, timeout, or error) and closes. create_app() adds @app.websocket("/ws") that accepts and calls handle_websocket with app.state. test_stage_9_1 passes (TestClient websocket_connect, send_json, receive_json; accepts response, timeout, or error).

- **Stage 10.1 (E2E smoke) implemented:** test_stage_10_1 runs `main.py --e2e-once` in a subprocess (timeout 60s, PYTHONPATH set) and asserts exit code 0. Runnable: `pytest tests/test-stages.py -k stage_10_1 -v`.

- **Stage 10.2 (LLM integration) implemented:** `llm` module provides LLMClient protocol, StaticLLMClient (mock), and get_llm_client(config). Runtime `get_llm_client` requires `LLM_API_KEY` and `openfund-ai[llm]`; missing key raises `ValueError`, missing dependency raises `ImportError`. API startup uses this runtime path (live LLM required). `main.py --e2e-once` has an explicit fallback to StaticLLMClient if live LLM init fails. PlannerAgent accepts optional llm_client and uses it in decompose_task; fallback to fixed three steps on parse failure/unavailable client. test_stage_10_2_llm_static_mock asserts the missing-key error path and that Planner with StaticLLMClient still yields runnable steps. Runnable: `pytest tests/test-stages.py -k stage_10_2 -v`.

- **LLM prompts module (Stage 10.2):** Central prompts in `llm/prompts.py`: PLANNER_DECOMPOSE, LIBRARIAN_SYSTEM, WEBSEARCHER_SYSTEM, ANALYST_SYSTEM, RESPONDER_SYSTEM (aligned with PRD and user-flow). Planner uses PLANNER_DECOMPOSE via LiveLLMClient. Responder optionally uses RESPONDER_SYSTEM when llm_client is set (`complete()`). Librarian/WebSearcher/Analyst prompts are actively used for summary generation and tool-selection workflows when llm_client is set. Tests: test_stage_10_2_planner_uses_prompts_module, test_stage_10_2_static_client_complete_passthrough, test_stage_10_2_responder_llm_prompt.

- **Full LLM integration (all five agents):** LibrarianAgent, WebSearcherAgent, and AnalystAgent now accept optional `llm_client` (same pattern as PlannerAgent and ResponderAgent). When set, Librarian calls `complete(LIBRARIAN_SYSTEM, get_librarian_user_content(query, combined_data))` after building combined docs/graph/sql and adds a `summary` key to INFORM content. WebSearcher calls `complete(WEBSEARCHER_SYSTEM, get_websearcher_user_content(query, fetched_data))` after fetching market/sentiment/regulatory and adds `summary` to INFORM. Analyst calls `complete(ANALYST_SYSTEM, get_analyst_user_content(structured_data, market_data))` after `analyze()` and adds `summary` to the analysis result. Wiring: `api/rest.py` and `main.py` pass the same `llm_client` from `get_llm_client(config)` to all five agents. DeepSeek is supported via `LLM_BASE_URL` (e.g. `https://api.deepseek.com`) and `LLM_MODEL=deepseek-chat`; API key from env (`LLM_API_KEY`) only, never committed. Prompt helpers in `llm/prompts.py`: `get_librarian_user_content`, `get_websearcher_user_content`, `get_analyst_user_content`, and `_data_summary` for building user messages. Tests: test_stage_10_2_librarian_llm_prompt, test_stage_10_2_websearcher_llm_prompt, test_stage_10_2_analyst_llm_prompt.

- **Design / target behavior (implemented):** Planner selects which agents to call and decomposes the user query into agent-specific sub-queries; specialists use LLM + tool descriptions to choose tools and parameters when `llm_client` is set, else content-key dispatch. See [backend.md](backend.md) and [agent-tools-reference.md](agent-tools-reference.md). Tests: `test_stage_10_2_librarian_tool_selection_when_llm_returns_tool_calls`, `test_stage_10_2_websearcher_tool_selection_when_llm_returns_tool_calls`, `test_stage_10_2_analyst_tool_selection_when_llm_returns_tool_calls`; content-key dispatch when llm_client is None or select_tools returns [] (stage 5.3, 5.4, 10.2).

- **Data populate seed implemented:** `python -m data_manager populate` seeds PostgreSQL (funds table, NVDA row), Neo4j (Company NVDA, Sector Technology, IN_SECTOR), and Milvus (two baseline documents with source "demo"). Idempotent: ON CONFLICT / MERGE / delete-by-source then index. Skips any backend whose env var is unset. kg_tool._node_to_dict prefers node property id/name for output "id" so get_relations shape is stable. test_data_populate_skips_when_no_backends asserts exit 0 and skip messages when no backend env set.

- **MCP `register_default_tools` failing when pandas missing:** `register_default_tools()` imported all tools in one block; if `analyst_tool` (or `market_tool`) failed to import (e.g. missing pandas), stage 2.1/2.2 tests failed. Fix: import `file_tool` first and register it; register `market_tool` and `analyst_tool` only inside try/except ImportError so optional tools are skipped when deps are missing.

- **Community-common tools implemented:** Per [agent-tools-reference.md](agent-tools-reference.md) and [backend.md](backend.md): kg_tool (`get_node_by_id`, `get_neighbors`, `get_graph_schema`), sql_tool (`explain_query`, `export_results`, `connection_health_check`), vector_tool (`get_by_ids`, `upsert_documents`, `health_check`), and `get_capabilities` (mcp/tools/capabilities.py) are implemented and registered in `register_default_tools`. Mock behavior when env unset; tests in tests/test_kg_tool.py, test_sql_tool.py, test_vector_tool.py, test_capabilities.py. Backend maintenance commands (populate, sql, neo4j, milvus) are provided via `data_manager/backend_cli.py` and `add_backend_subcommands` under `python -m data_manager`.

- **Deferred community-common tools implemented:** kg_tool: `shortest_path`, `get_similar_nodes`, `fulltext_search`, `bulk_export`, `bulk_create_nodes`; vector_tool: `create_collection_from_config`. All registered in `register_default_tools`; mock when NEO4J_URI/MILVUS_URI unset. Tests in tests/test_kg_tool.py and tests/test_vector_tool.py. Fulltext search requires an existing Neo4j fulltext index; bulk_export allows only read-only Cypher (MATCH/CALL).

- **DataManagerAgent Phase 1 (Collector) implemented:** `data_manager/collector.py`: DataCollector class fetches data from market_tool and analyst_tool for OHLCV, balance_sheet, cashflow, income_statement, insider_transactions, indicators, and news. Saves raw JSON files to `datasets/raw/{symbol}/` with metadata. `data_manager/tasks.py`: CollectionTask dataclass and COLLECTION_TASKS registry. CLI: `python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15`, `python -m data_manager global-news`, `python -m data_manager status`, `python -m data_manager list`. Design doc: [docs/data-manager-agent.md](data-manager-agent.md).

- **Interactive chat and run.sh:** `scripts/chat_cli.py` is a terminal chat client that POSTs to the running API `/chat` endpoint. It prompts "You: ", sends the line (with optional `--port`, `--profile`), prints "Assistant: <response>", and handles 200/408/400/422/404/500 and connection errors. `./scripts/run.sh` by default starts the API in the background, waits for it (curl /openapi.json), runs `chat_cli.py` in the foreground, and on chat exit kills the server (trap EXIT/INT/TERM). Use `--no-chat` to start the API only (previous behavior: `exec main.py --serve`).

- **Tools and LLM diagnostics:** On startup, api/rest logs "MCP tools registered: [...]" and "LLM: model=..., base_url=...". mcp_server logs "market_tool skipped" / "analyst_tool skipped" with ImportError when optional tools are not registered. GET /health returns `{tools: [...], llm_configured: bool}`. MCPClient.get_registered_tool_names() returns sorted list of registered tool names. Librarian, WebSearcher, and Analyst filter tool descriptions and allowed sets to only registered tools (get_*_tool_descriptions(registered_tool_names), filter_tool_calls_to_allowed with allowed ∩ registered) so the LLM does not suggest tools that are missing. docs/demo.md has Setup checklist and expanded troubleshooting; README links to it.

- **DataManagerAgent Phase 2-4 (Distributor, Classifier, Transformer) implemented:**
  - `data_manager/schemas.py`: PostgreSQL DDL (stock_ohlcv, company_fundamentals, financial_statements, insider_transactions, technical_indicators); UPSERT templates; Neo4j Cypher templates (Company, Sector, Industry, Officer nodes and edges); Milvus collection config.
  - `data_manager/classifier.py`: DataClassifier routes task_types to target databases (postgres, neo4j, milvus) with STATIC_ROUTING (single target) and MULTI_TARGET (e.g. info → all three).
  - `data_manager/transformer.py`: DataTransformer converts raw data: to_postgres_rows (CSV/JSON → table rows), to_neo4j_nodes_edges (extract Company, Sector, Industry, Officer nodes + relationships), to_milvus_docs (news/description → vector documents with content for embedding).
  - `data_manager/distributor.py`: DataDistributor reads local JSON files, classifies, transforms, and writes to PostgreSQL (sql_tool.run_query), Neo4j (kg_tool.query_graph), and Milvus (vector_tool.upsert_documents). Moves files to processed/failed after.
  - CLI: `python -m data_manager distribute --symbol NVDA`, `python -m data_manager distribute --all`, `python -m data_manager distribute --file path/to/file.json`. Options: `--no-move` (keep files in raw/), `--verbose` (show per-file details).
  - Fund data distribution: `python -m data_manager distribute-funds --funds-dir datasets`. Schema reference: [docs/fund-data-schema.md](fund-data-schema.md).

---

## Future implementation tracker

*(Functions that currently raise NotImplementedError or are stubs; track here for future work. Abstract methods and intentional "use TestClient" wrappers in api/rest.py are excluded.)*

### Backend integrations (when Neo4j / Postgres / Milvus are available)

- **mcp/tools/kg_tool.py:** `query_graph(cypher, params)` — uses neo4j driver with NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD when set; runs Cypher with params; returns rows (and nodes/edges for get_relations). Mock when unset.
- **mcp/tools/sql_tool.py:** `run_query(query, params)` — uses psycopg2 with DATABASE_URL when set; parameterized execution; returns dict with rows, schema, params. Mock when unset.
- **mcp/tools/vector_tool.py:** `search(query, top_k, filter)` — when MILVUS_URI set: connects to Milvus, lazy-loads sentence-transformers embedding model, embeds query, searches collection; returns list of docs with scores. `index_documents(docs)` embeds and upserts; returns indexed count. Mock when MILVUS_URI unset.

**Install backends (optional):** `pip install -e ".[backends]"` or `pip install neo4j psycopg2-binary pymilvus sentence-transformers`. See [data_prep/neo4j_postgres_milvus_integration.md](data_prep/neo4j_postgres_milvus_integration.md).

**Live tool validation:** Run `PYTHONPATH=. python3 scripts/test_third_party_apis.py` to call every MCP tool via the MCP layer and generate `docs/api-test-results.md` (PASS/INFRA_SKIP/API_FAIL). Tools that persistently return API_FAIL (subscription, rate limit, invalid) are candidates for removal; see plan "Live Tool Validation & Cleanup".

### MCP tool stubs (to complete tool surface)

- **mcp/tools/file_tool.py:** `list_files(prefix)` — list paths under MCP_FILE_BASE_DIR + prefix (e.g. os.listdir/glob); return list of relative paths.
- **mcp/tools/market_tool.py:** `fetch(fund_or_symbol)` — wrap get_stock_data or get_fundamentals; add timestamp; return dict.
- **mcp/tools/market_tool.py:** `fetch_bulk(symbols)` — loop symbols, call existing vendor-routed helpers; return dict keyed by symbol with timestamp.
- **mcp/tools/market_tool.py:** `search_web(query)` — call Tavily API if TAVILY_API_KEY set; normalize to list of dicts with timestamp; else fallback (e.g. get_news with date range).
- **mcp/tools/analyst_tool.py:** `run_analysis(payload)` — if ANALYST_API_URL set: POST payload with optional ANALYST_API_KEY; return response JSON; else return stub dict.

### Phase 2 (planner rounds / confidence-driven flow)

- **agents/planner_agent.py:** `resolve_conflicts(agent_outputs)` — reconcile when librarian/websearcher/analyst disagree (e.g. LLM merge or rule-based preference).
- **agents/responder_agent.py:** `evaluate_confidence(analysis)` — return float from analysis.get("confidence") or computed from distribution/indicators. **Current behavior:** Not implemented (NotImplementedError); only the Planner runs the planner sufficiency check (via LLM). Responder formats the final answer and does not use confidence to decide termination.
- **agents/responder_agent.py:** `should_terminate(confidence)` — compare to RESPONDER_CONFIDENCE_THRESHOLD; return True to stop, False to request a refined planner round. **Current behavior:** Not implemented (NotImplementedError). See backend.md: Responder does not use confidence.
- **agents/responder_agent.py:** `format_response(analysis, user_profile)` — build string from analysis (e.g. summary); call OutputRail.format_for_user; return formatted string.
- **agents/responder_agent.py:** `request_refinement(reason)` — return ACLMessage(REQUEST, sender=responder, receiver=planner, content={"reason": reason, "conversation_id": ...}) for a refined planner round.

### Suggested implementation order

1. **Low effort:** file_tool.list_files (directory listing under base_dir).
2. **Unify market:** market_tool.fetch, fetch_bulk, search_web (wrap existing vendor-routed/Tavily).
3. **Custom analyst:** analyst_tool.run_analysis (HTTP POST to ANALYST_API_URL).
4. **Backends:** kg_tool, sql_tool, vector_tool when Neo4j/Postgres/Milvus instances are available.
5. **Phase 2:** ResponderAgent confidence/termination/format/refinement and PlannerAgent resolve_conflicts (planner sufficiency check + refined planner rounds already exist; conflict reconciliation is still pending).

### Not to implement (by design)

- **a2a/message_bus.py:** MessageBus abstract methods — InMemoryMessageBus implements them.
- **agents/base_agent.py:** BaseAgent.handle_message — abstract; each agent implements.
- **api/rest.py:** post_chat, get_conversation — use FastAPI TestClient or real endpoints; left as NotImplementedError by design.

---

## PRD coverage and risks

**PRD coverage:** The plan meets the PRD for MVP. All functional requirements (FR1–FR7), constraints (C1–C3), and acceptance criteria (AC1–AC5) are covered by slices 1–10 and the contracts in [backend.md](backend.md) and [user-flow.md](user-flow.md). The PRD column in [project-status.md](project-status.md) maps each capability to the relevant FR/AC.

**Risks and dependencies:**
- **Slice order:** Ensure stage 2.1 (file_tool) is green before slice 3; SafetyGateway (6) before REST (7). Slices 3–5 depend on MCP and agents; 7–9 on the API layer.
- **MCP/backends unavailable:** Use mocks for vector_tool, kg_tool, sql_tool, and market_tool (slices 4–5). Timeout behavior (408) and E2E timeout config are in backend.md.
- **Phase 2:** LLM integration (decompose_task, planner sufficiency check, capped refined planner rounds) is in Stage 10.2. Remaining Phase-2 work is primarily responder confidence hooks and planner conflict reconciliation; see project-status.md.
- **Slice 3 implementation:** Planner handles INFORM from librarian and forwards to Responder with `final_response`; `main.py --e2e-once` uses a temp file as the query path so file_tool.read_file succeeds and one conversation completes (exit 0). E2E timeout is non-fatal per backend.md.
