# Backend Document

Server-side system behavior and architecture. See [prd.md](prd.md) for product intent and [file-structure.md](file-structure.md) for code organization (main application code; data_prep folder not covered there). For a step-by-step function trace of one beginner request through the system, see [use-case-trace-beginner.md](use-case-trace-beginner.md).

---

## System architecture overview

- **A2A:** FIPA-ACL messages over a message bus (in-memory or pluggable). Agents communicate via performatives (REQUEST, INFORM, STOP, etc.).
- **Layers:** User Interaction (API), Safety, Orchestration (Planner), Research Execution (Librarian, WebSearcher, Analyst), Tool/Data (MCP), Output Review (OutputRail).
- **Orchestration:** The Planner (orchestrator) decides **which** agents to call (one or more of Librarian, WebSearcher, Analyst) and **decomposes** the user query into **agent-specific sub-queries**. Each REQUEST to a specialist carries that agent's decomposed query (and any shared context). When information is sufficient, Planner sends consolidated data to Responder.
- **Termination:** Only the Responder may signal conversation complete (broadcast STOP); all agent threads exit on STOP.
- **Hub-and-spoke:** Planner is the sole orchestrator; specialists reply only to Planner. Planner sends consolidated data to Responder when information is sufficient.

---

## API contracts

### REST

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
- **Events:** `{"event": "status", "agent": "<name>", "message": "working"}` (per agent); `{"event": "response", "conversation_id": "...", "response": "..."}` (once when complete).

---

## Data models

- **Conversation state:** id (UUID), user_id, initial_query, messages (append-only log), status ("active" | "complete" | "error"), final_response (set when response is delivered), created_at, completion_event (for blocking wait).
- **Message (ACL):** performative, sender, receiver, content, conversation_id, reply_to, in_reply_to, timestamp. Performatives: REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL. Performative type is `(str, Enum)` for Python 3.9 compatibility (StrEnum is 3.11+).
- **Task step (orchestration):** agent ("librarian" | "websearcher" | "analyst"), action, params. Params include the **decomposed query** for that agent (and any tool-relevant hints). When sufficient information is gathered, Planner sends consolidated data to Responder.

---

## Business rules

- **Create vs get:** No conversation_id → create new conversation; conversation_id present → get existing (404 if missing).
- **Sufficiency:** Orchestrator decides when gathered information is sufficient (threshold configurable; stub always 1.0).
- **Confidence:** Responder uses confidence to decide terminate vs request refinement; Analyst may request more data below its threshold.
- **Persistence:** One JSON file per user at `memory/<user_id>/conversations.json`; anonymous at `memory/anonymous/conversations.json`. Written on create and on register_reply. Root dir: `MEMORY_STORE_PATH` (default `memory/`). **Situation memory:** A single BM25-backed store of (situation, recommendation) pairs is persisted at `{MEMORY_STORE_PATH}/situation_memory.json`; optional—loaded on startup via `get_situation_memory(memory_store_path)` when the `memory` module (and `rank_bm25`) is available; otherwise startup continues without it.

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
| Web / market   | Tavily, Yahoo, Alpha Vantage | market_tool — TAVILY_API_KEY, YAHOO_BASE_URL; optional ALPHA_VANTAGE_API_KEY, MCP_MARKET_VENDOR |
| Analyst        | Custom API, yfinance, Alpha Vantage | analyst_tool — ANALYST_API_URL, ANALYST_API_KEY; optional MCP_INDICATOR_VENDOR |
| SQL            | PostgreSQL  | sql_tool — DATABASE_URL |
| Files          | —           | file_tool (read_file) |

Tool names are namespaced (e.g. `file_tool.read_file`, `vector_tool.search`). All MCP tools accept a **payload** dict; required parameters (e.g. **symbol**, path, **as_of_date**, start_date, end_date, **limit**) must be passed in by the caller—no UI or client-side defaults. Payload keys: use **symbol** for the security identifier (ticker accepted for backward compatibility); **limit** for max items (e.g. get_news_yf, get_global_news_yf); **as_of_date** for reference date (curr_date accepted for backward compatibility). Analyst API stub: request `{ "returns", "horizon" }`; response `{ "sharpe", "max_drawdown", "distribution" }`. analyst_tool.get_indicators_yf and analyst_tool.get_indicators: symbol, indicator, as_of_date, look_back_days (get_indicators routes to yfinance/stockstats or Alpha Vantage via MCP_INDICATOR_VENDOR). **Vendor-agnostic tools** (route by config): market_tool.get_stock_data, market_tool.get_fundamentals, market_tool.get_balance_sheet, market_tool.get_cashflow, market_tool.get_income_statement, market_tool.get_news, market_tool.get_global_news, market_tool.get_insider_transactions; analyst_tool.get_indicators. Existing *_yf tools remain available. Embedding: sentence-transformers/all-MiniLM-L6-v2, 384 dims; config: EMBEDDING_MODEL, EMBEDDING_DIM.

**Research execution — specialist tool selection:** Specialist agents (Librarian, WebSearcher, Analyst) determine **which MCP tools to call and with what parameters** via an **LLM call**: they receive the planner's request (including the decomposed query), are given a **prompt** and **tool descriptions** (see [agent-tools-reference.md](agent-tools-reference.md)), and the LLM returns tool calls (tool name + payload); the agent then executes those tool calls and returns results (e.g. INFORM to Planner). If no LLM is available, behavior may fall back to content-key-based dispatch.

---

## Configuration (env)

- **Persistence:** MEMORY_STORE_PATH (default `memory/`). Situation memory file: `{MEMORY_STORE_PATH}/situation_memory.json`.
- **Timeouts:** E2E_TIMEOUT_SECONDS (default 30).
- **Thresholds:** PLANNER_SUFFICIENCY_THRESHOLD (default 0.6), ANALYST_CONFIDENCE_THRESHOLD (default 0.6), RESPONDER_CONFIDENCE_THRESHOLD (default 0.75).
- **LLM (Stage 10.2):** Optional. When LLM_API_KEY is not set, a static mock client is used (same three steps: librarian, websearcher, analyst). When LLM_API_KEY is set, a live OpenAI client is used for task decomposition if the optional dependency is installed: `pip install openfund-ai[llm]`. LLM_MODEL (default gpt-4o-mini) selects the model.
- **Demo mode:** Set `OPENFUND_DEMO=1` or run `python main.py --demo`. The API uses `demo.demo_client.DemoMCPClient` (static responses from `demo.demo_data`) and no LLM for the planner, so no external APIs or DBs are called. Use the CLI with `python -m demo.demo_chat`. All demo code lives under the `demo/` package; see [file-structure.md](file-structure.md#demo). **Real backends + static LLM:** With backends configured (DATABASE_URL, NEO4J_URI, MILVUS_URI) and OPENFUND_DEMO unset, the app uses real MCP tools. If LLM_API_KEY is not set, the planner uses StaticLLMClient (fixed three steps). Seed demo data once with `python -m data populate` so SQL/KG/vector responses match the static demo content; see README and [demo.md](demo.md).
- **MCP/backends:** MILVUS_URI, MILVUS_COLLECTION; NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD; TAVILY_API_KEY, YAHOO_BASE_URL; ANALYST_API_URL, ANALYST_API_KEY; DATABASE_URL; EMBEDDING_MODEL, EMBEDDING_DIM. **Vendor selection (market/analyst):** MCP_MARKET_VENDOR (default yfinance; or alpha_vantage); MCP_INDICATOR_VENDOR (default yfinance; or alpha_vantage). Optional: MCP_DATA_CACHE_DIR (cache dir for stockstats OHLCV); ALPHA_VANTAGE_API_KEY (required when using alpha_vantage vendor). **Path safety (file_tool):** Optional MCP_FILE_BASE_DIR; when set, read_file only allows paths under this directory (avoids path traversal). When unset, path is used as-is (trusted caller only).

**MCP market/indicator vendor switching:** Set `MCP_MARKET_VENDOR=alpha_vantage` to use Alpha Vantage for market tools (stock data, fundamentals, news, insider transactions). Set `MCP_INDICATOR_VENDOR=alpha_vantage` to use Alpha Vantage for technical indicators. Default for both is `yfinance`. Invalid or unset values fall back to `yfinance`. On Alpha Vantage rate limit, the tools automatically fall back to yfinance.

Work breakdown and runnable checkpoints: [progress.md](progress.md).
