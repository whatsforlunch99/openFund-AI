# OpenFund-AI — Claude.md v2
## A2A Multi-Agent Skeleton (FIPA-ACL + MCP) + Six-Layer + Tech Stack

---

## Overview

Implementation outline for:

- **A2A** communication via FIPA-ACL and a message bus
- **Six-layer architecture**: User Interaction, Safety, Orchestration, Research Execution, Tool/Data (MCP), Output Review
- **Technology stack**: **Milvus** (vector DB), **Neo4j** (graph), **Tavily** + **Yahoo APIs** (web/market search), **custom Analyst API** (quant analysis)
- **MCP** as the only path for external data; Responder-controlled termination

---

## Technology Stack

| Concern | Technology | MCP Tool / Use |
|--------|------------|----------------|
| Vector DB | **Milvus** | `vector_tool` — semantic search over fund documents; config: MILVUS_* |
| Knowledge graph | **Neo4j** | `kg_tool` — Cypher queries, fund–manager–company relations; config: NEO4J_* |
| Web / market search | **Tavily** + **Yahoo APIs** | `market_tool` — real-time data, web search; results include `timestamp`; config: TAVILY_API_KEY, YAHOO_* |
| Analyst backend | **Custom API** | `analyst_tool` — call custom API for Sharpe, drawdown, Monte Carlo, etc.; config: ANALYST_API_URL |

---

## Project Structure

```
OpenFund-AI/
├── agents/
│   ├── base_agent.py
│   ├── planner_agent.py
│   ├── librarian_agent.py
│   ├── websearch_agent.py
│   ├── analyst_agent.py
│   └── responder_agent.py
├── a2a/
│   ├── acl_message.py
│   ├── message_bus.py
│   └── conversation_manager.py
├── api/
│   ├── rest.py
│   └── websocket.py
├── safety/
│   └── safety_gateway.py
├── output/
│   └── output_rail.py
├── mcp/
│   ├── mcp_client.py
│   ├── mcp_server.py
│   └── tools/
│       ├── sql_tool.py
│       ├── vector_tool.py    # Milvus
│       ├── kg_tool.py        # Neo4j
│       ├── market_tool.py    # Tavily + Yahoo
│       ├── analyst_tool.py   # Custom API
│       └── file_tool.py
├── memory/                   # conversation persistence (git-ignored)
│   └── <user_id>/
│       └── conversations.json
├── config/
│   └── config.py
├── main.py
└── docs/
    └── claude-v2.md
```

---

## Layer 1 — User Interaction

### api/rest.py

- **`create_app(bus, manager, safety, mcp_client)`**: returns a FastAPI app; all shared state is injected as constructor arguments — route handlers close over them. Tests call `create_app(mock_bus, ...)` directly.
- **POST /chat**: body `{ query, conversation_id? (str), user_id? (str, default ""), user_profile? (UserProfile) }` → `SafetyGateway.process_user_input` (raises `SafetyError` → HTTP 400) → if `conversation_id` supplied call `get_conversation`, else call `create_conversation` → send `ACLMessage` to Planner → block on `conversation_state.completion_event.wait(timeout=E2E_TIMEOUT_SECONDS)` → return JSON `{ conversation_id, status, response }`. On timeout return **HTTP 408** `{ "status": "timeout", "conversation_id": "...", "response": null }`.
- **GET /conversations/{id}**: return conversation state JSON.

### api/websocket.py

- **WebSocket /ws**: same flow as POST /chat. Sends discrete JSON event messages — not a single final message:
  - `{"event": "status", "agent": "<name>", "message": "working"}` — emitted once per agent as it begins processing.
  - `{"event": "response", "conversation_id": "...", "response": "..."}` — emitted once when Responder completes.
  - Token-level streaming is deferred to Stage 19 (LLM).

---

## Layer 2 — Safety Gateway

### safety/safety_gateway.py

- **SafetyGateway**: `validate_input`, `check_guardrails`, `mask_pii`, `process_user_input` (single entry before bus).
- `process_user_input(...) -> ProcessedInput` raises `SafetyError(reason: str, code: str)` on validation or guardrail failure. FastAPI registers an exception handler mapping `SafetyError` to HTTP 400.

---

## A2A Layer

### a2a/acl_message.py

- **ACLMessage**: `performative`, `sender`, `receiver`, `content`, `conversation_id`; add `reply_to`, `in_reply_to`, `timestamp`.
- Performatives are typed as a `StrEnum` (Python 3.11+). Complete set: `REQUEST`, `INFORM`, `STOP`, `FAILURE`, `ACK`, `REFUSE`, `CANCEL`. New values added only when a stage requires them.

### a2a/message_bus.py

- **MessageBus**: `register_agent(name: str)`, `send`, `receive(agent_name, timeout?)`, `broadcast`.
- `register_agent` must be called in `main()` for each agent before any messages are sent. `broadcast` delivers to all registered names.

### a2a/conversation_manager.py

- **ConversationManager**: `create_conversation`, `get_conversation`, `register_reply`, `broadcast_stop`.
- **ConversationState** fields: `id` (UUID str), `user_id` (str, `""` if anonymous), `initial_query` (str), `messages` (list[dict], append-only ACLMessage log), `status` ("active" | "complete" | "error"), `final_response` (str | None), `created_at` (datetime), `completion_event` (threading.Event — set by `register_reply` when `final_response` is written; callers block with `event.wait(timeout=30)`).
- **Persistence:** JSON, one file per user at `memory/<user_id>/conversations.json` (anonymous users: `memory/anonymous/conversations.json`). Root dir configurable via `MEMORY_STORE_PATH` env var (default `memory/`). Written on every `create_conversation` and `register_reply` call. Directory auto-created with `os.makedirs(..., exist_ok=True)`. Thread-safety: `# TODO` deferred to a later stage.

---

## Agents (Layer 3 & 4)

### agents/base_agent.py

- **BaseAgent**: `__init__(name, message_bus)`, `run()`, `handle_message(message)` (abstract).
- `run()` loop: `while True` → `message_bus.receive(self.name, timeout=1.0)` → skip `None` → if `performative == STOP` break (thread exits cleanly) → else call `handle_message`. `handle_message` never receives a STOP message.

### agents/planner_agent.py

- **PlannerAgent**: `handle_message`, `decompose_task(query) -> List[TaskStep]`, `create_research_request(...)`, `compute_sufficiency(collected: dict) -> float`, (Phase 2) `resolve_conflicts(agent_outputs)`.
- **TaskStep** dataclass: `agent` (str: "librarian" | "websearcher" | "analyst"), `action` (str), `params` (dict).
- **Stub behavior (pre-LLM):** `decompose_task` always returns three TaskSteps — one each for librarian, websearcher, and analyst. Planner sends all three `REQUEST` messages in parallel (no waiting between sends), tracks expected INFORMs, and when all three have replied calls `compute_sufficiency`. Stub `compute_sufficiency` always returns `1.0`. If score ≥ `PLANNER_SUFFICIENCY_THRESHOLD` (env var, default `0.6`) → send to Responder. The LLM in Stage 19 replaces both `decompose_task` and `compute_sufficiency` without touching the control flow.

### agents/librarian_agent.py

- **LibrarianAgent**: `handle_message`; uses MCP **vector_tool (Milvus)**, **kg_tool (Neo4j)**, and **sql_tool (PostgreSQL)**; `retrieve_knowledge_graph`, `retrieve_documents`, `retrieve_sql`, `combine_results`. Calls `"vector_tool.search"`, `"kg_tool.query_graph"`, and `"sql_tool.run_query"` via MCPClient.

### agents/websearch_agent.py

- **WebSearcherAgent**: `handle_message`; uses MCP **market_tool (Tavily + Yahoo)**; `fetch_market_data`, `fetch_sentiment`, `fetch_regulatory`; all returns include `timestamp`.

### agents/analyst_agent.py

- **AnalystAgent**: `handle_message`; uses MCP **analyst_tool (custom API)** for heavy quant; local helpers: `sharpe_ratio`, `max_drawdown`, `monte_carlo_simulation` (or delegate to custom API); `analyze`, `needs_more_data`.

### agents/responder_agent.py

- **ResponderAgent**: `handle_message`, `evaluate_confidence(analysis: dict) -> float`, `should_terminate() -> bool`, `format_response(analysis, user_profile)`; use OutputRail for compliance and formatting; optional `request_refinement`.
- `evaluate_confidence` takes the analysis dict only; returns hardcoded `0.8` stub until LLM is added.
- `should_terminate` returns True when confidence ≥ `RESPONDER_CONFIDENCE_THRESHOLD` (env var, default `0.75`). When not terminating, sends `REQUEST` (refinement) to Planner.

---

## Layer 6 — Output Review

### output/output_rail.py

- **OutputRail**: `check_compliance(text)`, `format_for_user(text, user_profile)`.
- `user_profile` uses `UserProfile` StrEnum: `BEGINNER`, `LONG_TERM`, `ANALYST`. Input normalized to lowercase; unknown values return HTTP 400.

---

## Layer 5 — MCP Tools (with backends)

### mcp/mcp_client.py

- **MCPClient**: `call_tool(tool_name, payload) -> dict`.

### mcp/mcp_server.py

- **MCPServer**: `register_tool(name, handler)`, `dispatch(tool_name, payload)`.

### mcp/tools/vector_tool.py — **Milvus**

- **search(query: str, top_k: int, filter?: dict) -> list** — embeds query using `sentence-transformers/all-MiniLM-L6-v2` (384 dims), searches Milvus collection, returns docs with scores.
- **index_documents(docs: list) -> dict** (optional).
- Config: `MILVUS_URI` (e.g. `grpc://host:19530`; host/port not supported), `MILVUS_COLLECTION`, `EMBEDDING_MODEL` (default `sentence-transformers/all-MiniLM-L6-v2`), `EMBEDDING_DIM` (default `384`).
- Test stub: zero-vector of length `EMBEDDING_DIM`.

### mcp/tools/kg_tool.py — **Neo4j**

- **query_graph(cypher: str, params?: dict) -> dict** — Neo4j driver; nodes/edges.
- **get_relations(entity: str) -> dict** (optional).
- Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.

### mcp/tools/market_tool.py — **Tavily + Yahoo APIs**

- **fetch(fund_or_symbol: str) -> dict** — Yahoo (and/or Tavily) for market data; must include `timestamp`.
- **fetch_bulk(symbols: list) -> dict** (optional).
- **search_web(query: str) -> list** (optional) — Tavily for regulatory/sentiment; include `timestamp` per result.
- Config: TAVILY_API_KEY, YAHOO_BASE_URL (and YAHOO_API_KEY if required).

### mcp/tools/analyst_tool.py — **Custom API**

- **run_analysis(payload: dict) -> dict** — POST to `ANALYST_API_URL`; optional auth via `ANALYST_API_KEY` header.
- Stub schema (until real API spec is provided):
  ```jsonc
  // request: { "returns": [0.02, -0.01, 0.03], "horizon": 252 }
  // response: { "sharpe": 1.4, "max_drawdown": -0.12, "distribution": { "mean": 0.08, "std": 0.15 } }
  ```
- Config: `ANALYST_API_URL`, optional `ANALYST_API_KEY`.

### mcp/tools/sql_tool.py — **PostgreSQL**

- **run_query(query: str, params?: dict) -> dict** — executes parameterised SQL against PostgreSQL; returns rows as list of dicts.
- Config: `DATABASE_URL` env var.
- Implemented in Stage 8b (after kg_tool, before market_tool). Tests mock the PostgreSQL connection.

### mcp/tools/file_tool.py

- **read_file(path: str) -> dict**; optional **list_files(prefix: str) -> list**.

---

## Config

### config/config.py

- **load_config() -> Config**: reads all env vars via `os.getenv`; defaults to empty strings or documented defaults. Full env var list:
  - **Milvus:** `MILVUS_URI`, `MILVUS_COLLECTION`
  - **Embedding:** `EMBEDDING_MODEL` (default `sentence-transformers/all-MiniLM-L6-v2`), `EMBEDDING_DIM` (default `384`)
  - **Neo4j:** `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
  - **Market:** `TAVILY_API_KEY`, `YAHOO_BASE_URL`, `YAHOO_API_KEY`
  - **Analyst API:** `ANALYST_API_URL`, `ANALYST_API_KEY`
  - **SQL:** `DATABASE_URL`
  - **Persistence:** `MEMORY_STORE_PATH` (default `memory/`)
  - **Timeouts:** `E2E_TIMEOUT_SECONDS` (default `30`)
  - **Thresholds:** `PLANNER_SUFFICIENCY_THRESHOLD` (default `0.6`), `ANALYST_CONFIDENCE_THRESHOLD` (default `0.6`), `RESPONDER_CONFIDENCE_THRESHOLD` (default `0.75`)
  - **LLM (Phase 2):** `LLM_API_KEY`, `LLM_MODEL`
  - **MCP:** MCP server endpoint; feature flags

---

## Entry Point

### main.py

- **main()**: call `load_config()`; create `InMemoryMessageBus`; call `register_agent` for each agent name; create `ConversationManager`, `SafetyGateway`, `MCPClient`/`MCPServer` (tools registered); instantiate all agents (inject bus + mcp_client); call `create_app(bus, manager, safety, mcp_client)` and mount with uvicorn; start each agent in a daemon thread (`agent.run()`).
- `--e2e-once` flag: run one full conversation without HTTP, block on `completion_event.wait(timeout=E2E_TIMEOUT_SECONDS)`, exit 0.

---

## Design Constraints

- All inter-agent communication: ACLMessage only (performatives typed as StrEnum).
- All external data: via MCP only (Milvus, Neo4j, PostgreSQL, Tavily, Yahoo, custom Analyst API — all accessed through namespaced MCP tools).
- Termination: only Responder; broadcast STOP via ConversationManager; all agent threads exit on STOP receipt.
- Planner orchestrates hub-and-spoke: specialists (Librarian, WebSearcher, Analyst) only reply to Planner.
- Planner dispatches to all three specialists in parallel; proceeds to Responder when sufficiency score ≥ `PLANNER_SUFFICIENCY_THRESHOLD`.
- Conversation state persisted as JSON under `memory/<user_id>/conversations.json`; `completion_event` (threading.Event) signals reply readiness to pollers.

---

## Next Implementation Steps

1. Implement `InMemoryMessageBus` with `register_agent`; `ConversationManager` with `ConversationState` and JSON persistence; STOP broadcast.
2. Implement MCP server and tools (namespaced): `vector_tool` (Milvus + sentence-transformers), `kg_tool` (Neo4j), `sql_tool` (PostgreSQL, Stage 8b), `market_tool` (Tavily + Yahoo), `analyst_tool` (custom API stub), `file_tool`.
3. Implement `SafetyGateway` (raises `SafetyError`), `OutputRail` (`UserProfile` StrEnum), wire `create_app(bus, manager, safety, ...)` REST + WebSocket (event stream).
4. Implement agents: `PlannerAgent` (parallel dispatch to all 3, `PLANNER_SUFFICIENCY_THRESHOLD`), `LibrarianAgent` (vector + kg + sql), `WebSearcherAgent`, `AnalystAgent` (`ANALYST_CONFIDENCE_THRESHOLD`), `ResponderAgent` (`RESPONDER_CONFIDENCE_THRESHOLD`, 0.8 stub).
5. E2E loop (`--e2e-once`), REST Stage 17, WebSocket Stage 18; logging, monitoring, config, deployment.
6. Stage 19: replace stub `decompose_task` and `compute_sufficiency` with LLM (ReAct prompt). LangGraph deferred to Stage 20+.
