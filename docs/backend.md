# Backend Document

Server-side system behavior and architecture. See [prd.md](prd.md) for product intent and [file-structure.md](file-structure.md) for code organization.

---

## System architecture overview

- **A2A:** FIPA-ACL messages over a message bus (in-memory or pluggable). Agents communicate via performatives (REQUEST, INFORM, STOP, etc.).
- **Layers:** User Interaction (API), Safety, Orchestration (Planner), Research Execution (Librarian, WebSearcher, Analyst), Tool/Data (MCP), Output Review (OutputRail).
- **Termination:** Only the Responder may signal conversation complete (broadcast STOP); all agent threads exit on STOP.
- **Hub-and-spoke:** Planner is the sole orchestrator; specialists reply only to Planner. Planner sends consolidated data to Responder when information is sufficient.

---

## API contracts

### REST

- **POST /chat**  
  - **Request body:** `query` (required), `user_profile` (beginner | long_term | analyst), `user_id` (optional, default `""`), `conversation_id` (optional).  
  - **Flow:** Validate body → safety (process_user_input) → create or get conversation → send to Planner → block on completion.  
  - **Success (200):** `{ "conversation_id", "status", "response" }`.  
  - **Timeout (408):** `{ "status": "timeout", "conversation_id", "response": null }`.  
  - **Validation/safety (400):** Error response (e.g. SafetyError).  
  - **Not found (404):** Unknown conversation_id.

- **GET /conversations/{id}**  
  - Returns conversation state JSON. **404** if not found.

### WebSocket

- **/ws** — Same logical flow as POST /chat.  
- **Events:** `{"event": "status", "agent": "<name>", "message": "working"}` (per agent); `{"event": "response", "conversation_id": "...", "response": "..."}` (once when complete).

---

## Data models

- **Conversation state:** id (UUID), user_id, initial_query, messages (append-only log), status ("active" | "complete" | "error"), final_response (set when response is delivered), created_at, completion_event (for blocking wait).
- **Message (ACL):** performative, sender, receiver, content, conversation_id, reply_to, in_reply_to, timestamp. Performatives: REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL.
- **Task step (orchestration):** agent ("librarian" | "websearcher" | "analyst"), action, params (forwarded in message content).

---

## Business rules

- **Create vs get:** No conversation_id → create new conversation; conversation_id present → get existing (404 if missing).
- **Sufficiency:** Orchestrator decides when gathered information is sufficient (threshold configurable; stub always 1.0).
- **Confidence:** Responder uses confidence to decide terminate vs request refinement; Analyst may request more data below its threshold.
- **Persistence:** One JSON file per user at `memory/<user_id>/conversations.json`; anonymous at `memory/anonymous/conversations.json`. Written on create and on register_reply. Root dir: `MEMORY_STORE_PATH` (default `memory/`).

---

## Validation logic

- **Input:** Query required; user_profile must be one of beginner, long_term, analyst (normalized lowercase); unknown profile → 400.
- **Safety:** validate_input → check_guardrails → mask_pii. Failure → SafetyError (reason, code) → 400.
- **Conversation ID:** Must be valid for get; invalid or missing conversation → 404 for GET or for POST when continuing.

---

## Error handling standards

- **SafetyError:** Mapped to HTTP 400.
- **Unknown conversation:** 404.
- **Timeout:** 408; body includes status "timeout", conversation_id, response null.
- **E2E timeout (e.g. --e2e-once):** Configurable (default 30s via `E2E_TIMEOUT_SECONDS`). Stub runs treat timeout as non-fatal (exit 0).

---

## External integrations

All external data via MCP tools only:

| Concern        | Technology   | Tool / config |
|----------------|-------------|----------------|
| Vector DB      | Milvus      | vector_tool — MILVUS_URI, MILVUS_COLLECTION |
| Knowledge graph| Neo4j       | kg_tool — NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD |
| Web / market   | Tavily, Yahoo | market_tool — TAVILY_API_KEY, YAHOO_BASE_URL |
| Analyst        | Custom API  | analyst_tool — ANALYST_API_URL, ANALYST_API_KEY |
| SQL            | PostgreSQL  | sql_tool — DATABASE_URL |
| Files          | —           | file_tool (read_file) |

Tool names are namespaced (e.g. `file_tool.read_file`, `vector_tool.search`). Analyst API stub: request `{ "returns", "horizon" }`; response `{ "sharpe", "max_drawdown", "distribution" }`. Embedding: sentence-transformers/all-MiniLM-L6-v2, 384 dims; config: EMBEDDING_MODEL, EMBEDDING_DIM.

---

## Configuration (env)

- **Persistence:** MEMORY_STORE_PATH (default `memory/`).
- **Timeouts:** E2E_TIMEOUT_SECONDS (default 30).
- **Thresholds:** PLANNER_SUFFICIENCY_THRESHOLD (default 0.6), ANALYST_CONFIDENCE_THRESHOLD (default 0.6), RESPONDER_CONFIDENCE_THRESHOLD (default 0.75).
- **MCP/backends:** MILVUS_URI, MILVUS_COLLECTION; NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD; TAVILY_API_KEY, YAHOO_BASE_URL; ANALYST_API_URL, ANALYST_API_KEY; DATABASE_URL; EMBEDDING_MODEL, EMBEDDING_DIM.

Work breakdown and runnable checkpoints: [progress.md](progress.md).
