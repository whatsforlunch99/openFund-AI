# Backend Document

Server-side system behavior and architecture. See [prd.md](prd.md) for product intent and [file-structure.md](file-structure.md) for code organization (main application code; data_prep folder not covered there). For a step-by-step function trace of one beginner request through the system, see [use-case-trace-beginner.md](use-case-trace-beginner.md).

---

## System architecture overview

- **A2A:** FIPA-ACL messages over a message bus (in-memory or pluggable). Agents communicate via performatives (REQUEST, INFORM, STOP, etc.).
- **Layers:** User Interaction (API), Safety, Orchestration (Planner), Research Execution (Librarian, WebSearcher, Analyst), Tool/Data (MCP), Output Review (OutputRail).
- **Orchestration:** The Planner (orchestrator) decides **which** agents to call (one or more of Librarian, WebSearcher, Analyst) and **decomposes** the user query into **agent-specific sub-queries**. Decomposition is **LLM-driven**: the LLM selects which agents to use and what query to pass to each; the planner parses the LLM response as a list of steps (TaskSteps: agent + params) and dispatches REQUESTs only for those steps. Each REQUEST to a specialist carries that agent's decomposed query (and any shared context). When the LLM is unavailable or returns an empty list, the planner uses a fallback (fixed three steps or a single analyst step). After the planner sufficiency check passes, Planner sends consolidated data to Responder.
- **Termination:** Only the Responder may signal conversation complete (broadcast STOP); all agent threads exit on STOP.
- **Hub-and-spoke:** Planner is the sole orchestrator; specialists reply only to Planner. Planner sends consolidated data to Responder when the planner sufficiency check passes.
- **Background data management:** Data-manager workflows handle data collection (from market_tool/analyst_tool) and distribution (to PostgreSQL/Neo4j/Milvus). This is not part of real-time query flow; primarily triggered via CLI/scheduler. See [data-manager-agent.md](data-manager-agent.md).

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
  - **Request body:** `query` (required), `user_profile` (beginner | long_term | analyst), `user_id` (optional, default `""`), `conversation_id` (optional), `path` (optional, for file_tool).  
  - **Flow:** Validate body → safety (process_user_input) → create or get conversation → send to Planner → block on completion.  
  - **Success (200):** `{ "conversation_id", "status", "response", "flow" }` (flow: optional list of step dicts for UI).  
  - **Timeout (408):** `{ "status": "timeout", "conversation_id", "response": null, "flow" }`.  
  - **Validation/safety (400/422):** Error response (e.g. empty query, invalid user_profile → 422; SafetyError → 400).  
  - **Not found (404):** Unknown conversation_id.

- **GET /conversations/{id}**  
  - Returns conversation state JSON: id, user_id, initial_query, messages, status, final_response, created_at, flow. **404** if not found.

### WebSocket

- **/ws** — Same logical flow as POST /chat.  
- **Input JSON:** `query` (required), optional `user_profile`, `user_id`, `conversation_id`, `path`.  
- **Events:** multiple `flow` events while running, then exactly one terminal event:
  - `{"event": "response", "conversation_id", "status", "response", "flow"}` on success
  - `{"event": "timeout", "conversation_id", "response": null, "flow"}` on timeout
  - `{"event": "error", "detail": "..."}` on validation/safety/not-found failures.

---

## Data models

- **Conversation state:** id (UUID), user_id, initial_query, messages (append-only log), status ("active" | "complete" | "error"), final_response (set when response is delivered), created_at, completion_event (for blocking wait).
- **Message (ACL):** performative, sender, receiver, content, conversation_id, reply_to, in_reply_to, timestamp. Performatives: REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL. Performative type is `(str, Enum)` for Python 3.9 compatibility (StrEnum is 3.11+).
- **Task step (orchestration):** agent ("librarian" | "websearcher" | "analyst"), params. Params include the **decomposed query** for that agent (and any tool-relevant hints). When sufficient information is gathered, Planner sends consolidated data to Responder.
- **Planner memory context:** when `user_id` is provided, recent completed Q/A pairs from that user's persisted history are loaded and passed to Planner as `user_memory` context for decomposition.

---

## Business rules

- **Create vs get:** No conversation_id → create new conversation; conversation_id present → get existing (404 if missing).
- **Sufficiency:** The **Planner** (orchestrator) owns the **planner sufficiency check**. Sufficiency is determined by an **LLM call** (no numeric threshold in code). When the LLM answers SUFFICIENT, the Planner sends consolidated data to the Responder.
- **Confidence:** The **Analyst** computes confidence and exposes `needs_more_data(...)` against `ANALYST_CONFIDENCE_THRESHOLD`, but the current loop refinement decision is driven by the Planner's LLM-based sufficiency check (and `MAX_RESEARCH_ROUNDS`). The **Responder** does not evaluate confidence; it formats the final answer. `RESPONDER_CONFIDENCE_THRESHOLD` is reserved for future use.
- **Persistence:** One JSON file per user at `memory/<user_id>/conversations.json`; anonymous at `memory/anonymous/conversations.json`. Written on create and on register_reply. Root dir: `MEMORY_STORE_PATH` (default `memory/`). User credentials are stored as password hashes in `memory/users.json`. **Situation memory:** A single BM25-backed store of (situation, recommendation) pairs is persisted at `{MEMORY_STORE_PATH}/situation_memory.json`; optional—loaded on startup via `get_situation_memory(memory_store_path)` when the `memory` module (and `rank_bm25`) is available; otherwise startup continues without it.

---

## Validation logic

- **Input:** Query required; user_profile must be one of beginner, long_term, analyst (invalid profile → 422). user_id optional.
- **Safety:** validate_input → check_guardrails → mask_pii. Failure → SafetyError (reason, code) → 400.
- **Conversation ID:** Must be valid for get; invalid or missing conversation → 404 for GET or for POST when continuing.

---

## Error handling standards

- **SafetyError:** Mapped to HTTP 400.
- **Unknown conversation:** 404.
- **Timeout:** 408; body includes status "timeout", conversation_id, response null.
- **E2E timeout (e.g. --e2e-once):** Configurable (default 30s via `E2E_TIMEOUT_SECONDS`). Stub runs treat timeout as non-fatal (exit 0).
- **MCP tool errors:** Handlers return `{"error": "..."}`; market_tool and analyst_tool log exceptions (e.g. `logger.exception`) before returning so failures are visible in logs. Missing required payload keys (e.g. `path` for read_file) return a clear error message.

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
| Files          | —           | file_tool (read_file) |

Tool names are namespaced (e.g. `file_tool.read_file`, `vector_tool.search`). All MCP tools accept a **payload** dict; required parameters (e.g. **symbol**, path, **as_of_date**, start_date, end_date, **limit**) must be passed in by the caller—no UI or client-side defaults. Payload keys: use **symbol** for the security identifier (ticker accepted for backward compatibility); **limit** for max items (e.g. get_news, get_global_news); **as_of_date** for reference date (curr_date accepted for backward compatibility). Analyst API stub: request `{ "returns", "horizon" }`; response `{ "sharpe", "max_drawdown", "distribution" }`. analyst_tool.get_indicators: symbol, indicator, as_of_date, look_back_days (routes to Alpha Vantage via MCP_INDICATOR_VENDOR). **Vendor-agnostic tools** (route by config): market_tool.get_stock_data, market_tool.get_fundamentals, market_tool.get_balance_sheet, market_tool.get_cashflow, market_tool.get_income_statement, market_tool.get_news, market_tool.get_global_news, market_tool.get_insider_transactions; analyst_tool.get_indicators. Embedding: sentence-transformers/all-MiniLM-L6-v2, 384 dims; config: EMBEDDING_MODEL, EMBEDDING_DIM.

**Research execution — specialist tool selection:** Specialist agents (Librarian, WebSearcher, Analyst) determine **which MCP tools to call and with what parameters** via an **LLM call**: they receive the planner's request (including the decomposed query), are given a **prompt** and **tool descriptions** (see [agent-tools-reference.md](agent-tools-reference.md)), and the LLM returns tool calls (tool name + payload); the agent then executes those tool calls and returns results (e.g. INFORM to Planner). If no LLM is available, behavior may fall back to content-key-based dispatch.

---

## Configuration (env)

- **Persistence:** MEMORY_STORE_PATH (default `memory/`). Situation memory file: `{MEMORY_STORE_PATH}/situation_memory.json`.
- **Timeouts:** E2E_TIMEOUT_SECONDS (default 30). LLM_TIMEOUT_SECONDS (default 30) is the per-call timeout for planner/specialist LLM requests (decompose_to_steps, complete, select_tools); increase if your provider is slow.
- **Thresholds:** PLANNER_SUFFICIENCY_THRESHOLD (default 0.6, reserved—sufficiency is LLM-decided), ANALYST_CONFIDENCE_THRESHOLD (default 0.6), RESPONDER_CONFIDENCE_THRESHOLD (default 0.75, reserved for future use). **Planner rounds:** MAX_RESEARCH_ROUNDS (default 2) caps refined planner round(s). **Refined planner round steps:** The Planner builds steps with agent and params (query) only; no separate "action" field. **Fallback decomposition:** When the LLM is unavailable or parse fails, the Planner uses a fixed three-step chain (librarian, websearcher, analyst) with a small heuristic to infer fund/symbol from the query (e.g. nvidia→NVDA, apple→AAPL). When the LLM returns a valid empty list, the planner uses a single analyst step so the pipeline does not stall.
- **LLM:** Required for app startup. `get_llm_client()` requires `LLM_API_KEY`; otherwise startup fails with a clear error. Install optional dependency: `pip install openfund-ai[llm]`. `LLM_MODEL` (default `gpt-4o-mini`) and optional `LLM_BASE_URL` control provider/model routing. Per-call timeout: `LLM_TIMEOUT_SECONDS` (default 30); the implementation that calls the LLM for the planner is `LiveLLMClient.decompose_to_steps()` in `llm/live_client.py`.
- **Runtime entrypoint:** Use `./scripts/run.sh` as the single operational command to start the live system.
- **MCP/backends:** MILVUS_URI, MILVUS_COLLECTION; NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD; TAVILY_API_KEY; ANALYST_API_URL, ANALYST_API_KEY; DATABASE_URL; EMBEDDING_MODEL, EMBEDDING_DIM. **Vendor selection (market/analyst):** MCP_MARKET_VENDOR (default alpha_vantage; or finnhub); MCP_INDICATOR_VENDOR (default alpha_vantage). No yfinance; market data uses Alpha Vantage or Finnhub only. Optional: MCP_DATA_CACHE_DIR (cache dir for OHLCV); ALPHA_VANTAGE_API_KEY (required when using alpha_vantage vendor); FINNHUB_API_KEY (required when MCP_MARKET_VENDOR=finnhub). **Path safety (file_tool):** Optional MCP_FILE_BASE_DIR; when set, read_file only allows paths under this directory (avoids path traversal). When unset, path is used as-is (trusted caller only).

**MCP market/indicator vendor switching:** Set `MCP_MARKET_VENDOR=alpha_vantage` to use Alpha Vantage for market tools (stock data, fundamentals, news, insider transactions). Set `MCP_INDICATOR_VENDOR=alpha_vantage` for technical indicators. Default for both is `alpha_vantage`. Invalid or unset values fall back to `alpha_vantage`. Finnhub is supported for market data when `MCP_MARKET_VENDOR=finnhub` and FINNHUB_API_KEY is set.

**Interaction log:** INTERACTION_LOG (env, default true) or config.interaction_log_enabled enables systematic function-call logging during user interactions (POST /chat, /ws). Each log line is one JSON object: ts, conversation_id, function, params, result, duration_ms, sequence. Logger name: openfund.interaction. Logical flow logged matches [use-case-trace-beginner.md](use-case-trace-beginner.md); see [file-structure.md](file-structure.md) (util/interaction_log.py) for API.

Work breakdown and runnable checkpoints: [progress.md](progress.md).
