# Backend Document

Server-side system behavior and architecture. See [prd.md](../90_product/prd.md) for product intent, [file-structure.md](file-structure.md) for code organization, and [dependency-contract.md](dependency-contract.md) for allowed package import direction (loader/schema contracts: [`docs/data_prep/`](../../data_prep/revision_plan.md)). For a step-by-step function trace of one beginner request through the system, see [use-case-trace-beginner.md](../00_overview/use-case-trace-beginner.md).

---

## System architecture overview

- **A2A:** FIPA-ACL messages over a message bus (in-memory or pluggable). Agents communicate via performatives (REQUEST, INFORM, STOP, etc.).
- **Layers:** User Interaction (API), Safety, Orchestration (Planner), Research Execution (Librarian, WebSearcher, Analyst), Tool/Data (MCP), Output Review (OutputRail).
- **Tool/Data (MCP):** All tool access goes through **FastMCP** (MCP protocol). The OpenFund API uses **MCPClient** (`openfund_mcp/mcp_client.py`) to spawn the FastMCP server as a subprocess and connect over stdio; external clients (e.g. Claude Desktop) can run the same server via `python -m openfund_mcp`. Tool implementations live in `openfund_mcp/tools/`; the single MCP server module is `openfund_mcp/mcp_server.py` (FastMCP stdio + MCPServer for in-process tests). **SDK compatibility:** `session.call_tool` returns a CallToolResult whose shape varies by `mcp` package version; MCPClient normalizes error detection (`is_error` / `isError` / content blocks) so tool calls do not raise `AttributeError`. **WebSearcher Yahoo/stooq/ETFdb/fund_catalog:** Implementations live in `openfund_mcp/tools/`; the FastMCP app and MCPServer register them from there. See [agent-tools-reference.md](../03_tools_and_mcp/agent-tools-reference.md).
- **Orchestration:** The Planner (orchestrator) decides **which** agents to call (one or more of Librarian, WebSearcher, Analyst) and **decomposes** the user query into **agent-specific sub-queries**. Decomposition is **LLM-driven**: the LLM selects which agents to use and what query to pass to each; the planner parses the LLM response as a list of steps (TaskSteps: agent + params) and dispatches REQUESTs only for those steps. Each REQUEST to a specialist carries that agent's decomposed query (and any shared context). When the LLM is unavailable or returns an empty list, the planner uses a fallback (fixed three steps or a single analyst step). After the planner sufficiency check passes, Planner sends consolidated data to Responder.
- **Termination:** Only the Responder may signal conversation complete (broadcast STOP); all agent threads exit on STOP.
- **Hub-and-spoke:** Planner is the sole orchestrator; specialists reply only to Planner. Planner sends consolidated data to Responder when the planner sufficiency check passes.
- **Background data loading:** `scripts/data_loader.py` loads CSV/JSON assets into PostgreSQL, Neo4j, and Milvus from `database/stats_data`, `database/graph_data/neo4j_export`, and `database/text_data`. This is not part of real-time query flow; it is run before or alongside runtime startup (for example via `scripts/run.sh` / `scripts/run.ps1`). See schema docs in `docs/data_prep/`.

---

## API contracts

### REST

- **POST /register**  
  - **Request body:** `username` (preferred) or legacy `display_name`; resolved username must match `^[A-Za-z][A-Za-z0-9_.-]{2,31}$` and be unique. `password` is required (min 8 chars).  
  - **Success (200):** `{ "user_id", "username", "message" }`.  
  - **Failure (409):** username already exists.  
  - **Persistence:** stores password hash in `MEMORY_STORE_PATH/users.json`.

- **POST /login**  
  - **Request body:** `username` (preferred) or legacy `user_id`, `password` (required).  
  - **Success (200):** `{ "user_id", "username", "message", "loaded_conversations", "has_memory_context" }`.  
  - **Failure (401):** invalid credentials.  
  - **Behavior:** loads persisted user conversations from `memory/<user_id>/conversations.json` into ConversationManager.

- **POST /chat**  
  - **Request body:** `query` (required), `user_profile` (beginner | long_term | analyst), `user_id` (optional, default `""`), `conversation_id` (optional).  
  - **Flow:** Validate body → safety (process_user_input) → create or get conversation → send to Planner → block on completion.  
  - **Success (200):** `{ "conversation_id", "status", "response", "flow" }` (flow: optional list of step dicts for UI).  
  - **Timeout (408):** `{ "status": "timeout", "conversation_id", "response": null, "flow" }`.  
  - **Validation/safety (400/422):** Error response (e.g. empty query, invalid user_profile → 422; SafetyError → 400).  
  - **Not found (404):** Unknown conversation_id.

- **GET /conversations/{id}**  
  - Returns conversation state JSON: id, user_id, initial_query, messages, status, final_response, created_at, flow, **data_sources** (bounded snapshots per specialist after planner aggregation; see Data models). **404** if not found.

### WebSocket

- **/ws** — Same logical flow as POST /chat.  
- **Input JSON:** `query` (required), optional `user_profile`, `user_id`, `conversation_id`.  
- **Events:** multiple `flow` events while running, then exactly one terminal event:
  - `{"event": "response", "conversation_id", "status", "response", "flow"}` on success
  - `{"event": "timeout", "conversation_id", "response": null, "flow"}` on timeout
  - `{"event": "error", "detail": "..."}` on validation/safety/not-found failures.

---

## Data models

- **Conversation state:** id (UUID), user_id, initial_query, messages (append-only log), status ("active" | "complete" | "error"), final_response (set when response is delivered), created_at, completion_event (for blocking wait). **data_sources:** object with fixed keys `librarian`, `websearcher`, `analyst`; each value is a JSON object (bounded snapshot of that specialist’s INFORM content) or `{}` if that agent has not been merged yet. The Planner calls `ConversationManager.merge_data_sources` when a research round completes and the flow proceeds to the Responder; a second planner round merges **by agent** only (agents not contacted in round 2 keep their round‑1 snapshot). Snapshots are produced by `util/specialist_snapshot.py` (size-capped, JSON-safe); full raw payloads are not stored in `conversations.json`.
- **Message (ACL):** performative, sender, receiver, content, conversation_id, reply_to, in_reply_to, timestamp. Performatives: REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL. Performative type is `(str, Enum)` for Python 3.9 compatibility (StrEnum is 3.11+).
- **Task step (orchestration):** agent ("librarian" | "websearcher" | "analyst"), params. Params include the **decomposed query** for that agent (and any tool-relevant hints). Planner REQUEST `content` may include **`symbol_resolution`** (`schema_version`, `status`, `symbol_type`, `listings`, `by_tool`, `resolution_tier`, `confidence`, optional `validation`) so specialists align symbols with tool capabilities. Status may be **`resolved`**, **`unresolved`** (no validated ticker; financial tools are skipped in `by_tool`), or **`not_applicable`**. When `status` is `resolved`, content may also include **`resolution_listings`**, **`resolution_symbol_type`**, **`resolution_canonical_name`**. Deterministic matches use `database/symbol_resolution_aliases.json`; LLM fallback requires **`OPENFIGI_API_KEY`** for OpenFIGI mapping after Yahoo meta check. See `util/planner_symbol_resolution.py` and `{MEMORY_STORE_PATH}/symbol_resolution_cache.json` (only **`resolved`** payloads are cached). When sufficient information is gathered, Planner sends consolidated data to Responder.
- **Planner memory context:** When `user_id` is provided, the API loads planner memory as follows: first `get_user_memory(user_id)` (per-user working memory and preference labels from `memory/<user_id>/user_memory.json`); if that returns empty, fall back to recent completed Q/A from ConversationManager (`get_user_memory_context`). The result is passed to the Planner as `user_memory` in the REQUEST content.

---

## Business rules

- **Create vs get:** No conversation_id → create new conversation; conversation_id present → get existing (404 if missing).
- **Sufficiency:** The **Planner** (orchestrator) owns the **planner sufficiency check**. Sufficiency is determined by an **LLM call** (no numeric threshold in code). When the LLM answers SUFFICIENT, the Planner sends consolidated data to the Responder. If the LLM answers INSUFFICIENT but **`strong_equity_evidence_for_sufficiency`** applies (WebSearcher price line plus Librarian SQL rows ≥3 or `structured_timeseries_metrics` from internal SQL), the Planner **overrides** to SUFFICIENT for that round so the responder is not pushed into a false “insufficient” path. After **max rounds**, if the LLM still answers INSUFFICIENT but collected outputs contain answer signal (e.g. WebSearcher prices, librarian SQL rows), the Planner may send a **partial** combined answer with caveats and set **`partial_insufficient`** on the INFORM to the Responder so the Responder does not replace the body with the single phrase “Insufficient information.”
- **Confidence:** The **Analyst** computes confidence and exposes `needs_more_data(...)` against `ANALYST_CONFIDENCE_THRESHOLD`, but the current loop refinement decision is driven by the Planner's LLM-based sufficiency check (and `MAX_RESEARCH_ROUNDS`). The **Responder** does not evaluate confidence; it formats the final answer. `RESPONDER_CONFIDENCE_THRESHOLD` is reserved for future use.
- **Persistence:** One JSON file per user at `memory/<user_id>/conversations.json`; anonymous at `memory/anonymous/conversations.json`. Written on create, on register_reply, and when the Planner merges specialist snapshots (`merge_data_sources`). **Global symbol resolution cache:** `{MEMORY_STORE_PATH}/symbol_resolution_cache.json` (**`resolved`** status only, keyed by cache key). **Committed issuer catalog:** `database/symbol_resolution_known_issuers.json` (listings + `symbol_type` per entity). **Routing:** `database/symbol_resolution_routing.json` maps phrases/symbols to `cache_key` and optional `ticker_symbol_types` (graph-aligned values, e.g. SPY → `etfs`). `symbol_type` uses **`cryptos` | `currencies` | `equities` | `etfs` | `funds` | `indices` | `moneymarkets` | `unknown`** (`schema_version` 4); legacy `etf`/`stock` in JSON normalize to `etfs`/`equities`. `etfdb_tool` is planned only when `symbol_type` is `etfs` and the primary listing is US. Root dir: `MEMORY_STORE_PATH` (default `memory/`). User credentials are stored as password hashes in `memory/users.json`. **Situation memory:** A single BM25-backed store of (situation, recommendation) pairs is persisted at `{MEMORY_STORE_PATH}/situation_memory.json`; optional—loaded on startup via `get_situation_memory(memory_store_path)` when the `memory` module (and `rank_bm25`) is available; otherwise startup continues without it. **User memory:** Per-user working memory and preference labels are stored at `memory/<user_id>/user_memory.json` (schema: `text`, `preference_labels`, `updated_at`). Written when a conversation completes (ConversationManager calls `append_user_memory`). Working memory is capped at 500 words; when exceeded, a pluggable compressor shortens it (default truncation; optional LLM summarization wired at startup).
- **Neo4j graph_data import model:** `database/graph_data/*.csv` is transformed into a normalized multi-file export bundle. **Bare ids** (no `record_` / `currency_` / `dataset_` prefixes): e.g. record `ogka_sg`, currency `usd`, dataset `funds`. **Tag** nodes dedupe all non-currency categorical values **globally** by normalized text (e.g. `china` from `country` and from `category` share one node); `source_field` on record→tag relationships preserves column semantics. **Dimension** nodes `currency` and `dataset` link every currency code and every dataset row respectively (`CURRENCY_IN_DIMENSION`, `DATASET_IN_DIMENSION`). Currency codes share one node per normalized code. Relationship CSVs omit a per-row `:TYPE` where the type is fixed per file (admin import maps one type per file); `record_to_tag_rels.csv` carries `source_field` so loaders map to the correct semantic relationship type.

---

## Validation logic

- **Input:** Query required; user_profile must be one of beginner, long_term, analyst (invalid profile → 422). user_id optional.
- **Safety:** validate_input → check_guardrails → mask_pii. Failure → SafetyError (reason, code) → 400.
- **Conversation ID:** Must be valid for get; invalid or missing conversation → 404 for GET or for POST when continuing.

---

## Error handling standards

- **SafetyError:** Mapped to HTTP 400.
- **Unknown conversation:** 404.
- **Timeout:** HTTP 408; body includes `status: "timeout"`, `conversation_id`, `response: null`, and a message that recommends polling **GET /conversations/{conversation_id}** for `final_response` when the multi-agent run outlasts the wait.
- **E2E timeout (e.g. --e2e-once):** Configurable via `E2E_TIMEOUT_SECONDS` (default **180** seconds to cover planner + Librarian/WebSearcher/Analyst + MCP). Stub runs treat timeout as non-fatal (exit 0).
- **MCP tool errors:** Handlers return `{"error": "..."}`; **vector/kg/sql without backends** use explicit messages (`MILVUS_URI not set`, `NEO4J_URI not set`, `DATABASE_URL not set`) and empty payloads—no placeholder fund/graph/SQL data. `vector_tool.search` returns no hits when Milvus is not configured. market_tool and analyst_tool log exceptions (e.g. `logger.exception`) before returning so failures are visible in logs. Missing required payload keys (e.g. `path` for read_file) return a clear error message.

---

## External integrations

All external data via MCP tools only:

| Concern        | Technology   | Tool / config |
|----------------|-------------|----------------|
| Vector DB      | Milvus      | vector_tool — MILVUS_URI, MILVUS_COLLECTION |
| Knowledge graph| Neo4j       | kg_tool — NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD |
| Web / market   | Tavily, Alpha Vantage, Finnhub | market_tool — TAVILY_API_KEY (for search_web when implemented); ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY; MCP_MARKET_VENDOR (alpha_vantage \| finnhub) |
| Analyst        | Custom API, Alpha Vantage | analyst_tool — ANALYST_API_URL, ANALYST_API_KEY; optional MCP_INDICATOR_VENDOR |
| SQL            | PostgreSQL  | sql_tool — DATABASE_URL |
| Local files    | —           | `file_tool.read_file` (MCP only; optional `MCP_FILE_BASE_DIR`; not part of POST /chat or WebSocket bodies) |

Tool names are namespaced (e.g. `file_tool.read_file`, `vector_tool.search`). All MCP tools accept a **payload** dict; required parameters (e.g. **symbol**, **path** for read_file, **as_of_date**, start_date, end_date, **limit**) must be passed in by the caller—no UI or client-side defaults. Payload keys: use **symbol** for the security identifier (ticker accepted for backward compatibility); **limit** for max items (e.g. get_news, get_global_news); **as_of_date** for reference date (curr_date accepted for backward compatibility). Analyst API stub: request `{ "returns", "horizon" }`; response `{ "sharpe", "max_drawdown", "distribution" }`. analyst_tool.get_indicators: symbol, indicator, as_of_date, look_back_days (routes to Alpha Vantage via MCP_INDICATOR_VENDOR). **Vendor-agnostic tools** (route by config): market_tool.get_stock_data, market_tool.get_fundamentals, market_tool.get_balance_sheet, market_tool.get_cashflow, market_tool.get_income_statement, market_tool.get_news, market_tool.get_global_news, market_tool.get_insider_transactions; analyst_tool.get_indicators. Embedding: sentence-transformers/all-MiniLM-L6-v2, 384 dims; config: EMBEDDING_MODEL, EMBEDDING_DIM.

**Research execution — specialist tool selection:** Specialist agents (Librarian, WebSearcher, Analyst) determine **which MCP tools to call and with what parameters** via an **LLM call**: they receive the planner's request (including the decomposed query), are given a **prompt** and **tool descriptions** (see [agent-tools-reference.md](../03_tools_and_mcp/agent-tools-reference.md)), and the LLM returns tool calls (tool name + payload); the agent then executes those tool calls and returns results (e.g. INFORM to Planner). If no LLM is available, behavior may fall back to content-key-based dispatch.

---

## Configuration (env)

- **Persistence:** MEMORY_STORE_PATH (default `memory/`). Situation memory file: `{MEMORY_STORE_PATH}/situation_memory.json`. User memory files: `{MEMORY_STORE_PATH}/<user_id>/user_memory.json`.
- **Graph import artifacts:** normalized bundle under `database/graph_data/neo4j_export/`:
  - **Export (3 files):** `graph_nodes.csv`, `graph_relationships.csv`, `category_inspection.csv`.
  - Bundle validation (`validate_graph_csv_bundle_for_neo4j`): requires `graph_nodes.csv` + `graph_relationships.csv`; schema id `normalized_bundle_v4`.
  - **Fresh rebuild strategy:** `scripts/data_loader.py --load-mode fresh-all` uses `NEO4J_FRESH_IMPORT_MODE`:
    - `auto` (default): try offline `neo4j-admin database import full`; fallback to online batched Bolt load.
    - `offline`: require offline import success (error if unavailable).
    - `online`: force online wipe + batched Bolt load only.
  - **Batch tuning:** online Neo4j loader batch size can be tuned via `NEO4J_LOAD_BATCH_SIZE` (default 10000).
- **Timeouts:** E2E_TIMEOUT_SECONDS (default **180** for full-stack chat waits). LLM_TIMEOUT_SECONDS (default 30) is the per-call timeout for planner/specialist LLM requests (decompose_to_steps, complete, select_tools); increase if your provider is slow.
- **Thresholds:** PLANNER_SUFFICIENCY_THRESHOLD (default 0.6, reserved—sufficiency is LLM-decided), ANALYST_CONFIDENCE_THRESHOLD (default 0.6), RESPONDER_CONFIDENCE_THRESHOLD (default 0.75, reserved for future use). **Planner rounds:** MAX_RESEARCH_ROUNDS (default 2) caps refined planner round(s). **Refined planner round steps:** The Planner builds steps with agent and params (query) only; no separate "action" field. **Fallback decomposition:** When the LLM is unavailable or parse fails, the Planner uses a fixed three-step chain (librarian, websearcher, analyst) with a small heuristic to infer fund/symbol from the query (e.g. nvidia→NVDA, apple→AAPL). When the LLM returns a valid empty list, the planner uses a single analyst step so the pipeline does not stall.
- **LLM:** Required for app startup. `get_llm_client()` requires `LLM_API_KEY`; otherwise startup fails with a clear error. Install optional dependency: `pip install openfund-ai[llm]`. `LLM_MODEL` (default `gpt-4o-mini`) and optional `LLM_BASE_URL` control provider/model routing. Per-call timeout: `LLM_TIMEOUT_SECONDS` (default 30); the implementation that calls the LLM for the planner is `LiveLLMClient.decompose_to_steps()` in `llm/live_client.py`.
- **Runtime entrypoint:** Use `./scripts/run.sh` as the single operational command to start the live system.
- **MCP/backends:** MILVUS_URI, MILVUS_COLLECTION; NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD; TAVILY_API_KEY; ANALYST_API_URL, ANALYST_API_KEY; DATABASE_URL; EMBEDDING_MODEL, EMBEDDING_DIM. **Vendor selection (market/analyst):** MCP_MARKET_VENDOR (default alpha_vantage; or finnhub); MCP_INDICATOR_VENDOR (default alpha_vantage). No yfinance; market data uses Alpha Vantage or Finnhub only. Optional: MCP_DATA_CACHE_DIR (cache dir for OHLCV); ALPHA_VANTAGE_API_KEY (required when using alpha_vantage vendor); FINNHUB_API_KEY (required when MCP_MARKET_VENDOR=finnhub). **Path safety (file_tool):** Optional MCP_FILE_BASE_DIR; when set, read_file only allows paths under this directory (avoids path traversal). When unset, path is used as-is (trusted caller only).

**MCP market/indicator vendor switching:** Set `MCP_MARKET_VENDOR=alpha_vantage` to use Alpha Vantage for market tools (stock data, fundamentals, news, insider transactions). Set `MCP_INDICATOR_VENDOR=alpha_vantage` for technical indicators. Default for both is `alpha_vantage`. Invalid or unset values fall back to `alpha_vantage`. Finnhub is supported for market data when `MCP_MARKET_VENDOR=finnhub` and FINNHUB_API_KEY is set.

**Interaction log:** INTERACTION_LOG (env, default true) or config.interaction_log_enabled enables systematic function-call logging during user interactions (POST /chat, /ws). Each log line is one JSON object: ts, conversation_id, function, params, result, duration_ms, sequence. Logger name: openfund.interaction. Logical flow logged matches [use-case-trace-beginner.md](../00_overview/use-case-trace-beginner.md); see [file-structure.md](file-structure.md) (util/interaction_log.py) for API.

**MCP server (FastMCP):** All tool access uses the FastMCP server. The API spawns it automatically when needed. For external clients (e.g. Claude Desktop), see [mcp-server.md](../03_tools_and_mcp/mcp-server.md).

Work breakdown and runnable checkpoints: [progress.md](../90_product/progress.md).
