# OpenFund-AI: Staged Implementation (Runnable Checkpoints)

Each stage ends with a **runnable checkpoint**: either tests passing or a command/API you can execute. Dependencies flow stage-to-stage; external services (Milvus, Neo4j, Tavily, Yahoo, Analyst API) can be mocked in tests so stages are runnable without full infra.

---

## Stage 1 — Config and minimal main

**Scope:** [config/config.py](../config/config.py) `load_config()`, [main.py](../main.py) `main()`.

- Implement `load_config()`: read env with `os.getenv`, default empty strings; no .env file required.
- Implement `main()`: call `load_config()`, print `"OpenFund-AI ready (config loaded)"`, exit 0.

**Runnable:** `PYTHONPATH=. python main.py` prints the message and exits 0.

---

## Stage 2 — In-memory MessageBus

**Scope:** New implementation of [a2a/message_bus.py](../a2a/message_bus.py) (e.g. `InMemoryMessageBus`).

- Implement a concrete `MessageBus`: `register_agent(name: str)` adds agent to known set; per-agent queues (`defaultdict(queue.Queue)`); `send` puts to receiver queue; `receive(agent_name, timeout?)` blocks until message or timeout returns `None`; `broadcast` puts to all registered agent queues.
- Tests in `tests/test-stages.py`: send message → receive by that agent → assert content. Broadcast: register two agents, broadcast → each receives. Receive with timeout returns `None` when empty.

**Runnable:** `pytest tests/test-stages.py -k stage_2 -v` passes.

---

## Stage 3 — ConversationManager

**Scope:** [a2a/conversation_manager.py](../a2a/conversation_manager.py).

- Implement `ConversationState` dataclass: `id` (UUID str), `user_id` (str), `initial_query` (str), `messages` (list[dict]), `status` ("active"|"complete"|"error"), `final_response` (str|None), `created_at` (datetime), `completion_event` (threading.Event).
- Implement `create_conversation(user_id, query) -> ConversationState`: generate UUID, build state, persist to `memory/<user_id>/conversations.json` (root dir from `MEMORY_STORE_PATH` env var, default `memory/`); auto-create dir with `os.makedirs(..., exist_ok=True)`. Anonymous users use `memory/anonymous/`.
- Implement `get_conversation(id) -> ConversationState`.
- Implement `register_reply(conversation_id, message)`: append message dict to `state.messages`; if message is final response set `state.final_response`, `state.status = "complete"`, and `state.completion_event.set()`; persist to JSON. Thread-safety: `# TODO` deferred.
- Implement `broadcast_stop`: build STOP ACLMessage, call `message_bus.broadcast`.
- Tests in `tests/test-stages.py`: create → valid UUID + state; get → same state; register_reply → message appended + event set + file written; broadcast_stop → STOP performative sent.

**Runnable:** `pytest tests/test-stages.py -k stage_3 -v` passes.

---

## Stage 4 — SafetyGateway

**Scope:** [safety/safety_gateway.py](../safety/safety_gateway.py).

- Implement `validate_input`: length and charset checks; return `ValidationResult`.
- Implement `check_guardrails`: block list of phrases (e.g. "buy now", "sell immediately"); return `GuardrailResult`.
- Implement `mask_pii`: regex for phone/ID patterns, replace with placeholder; return masked string.
- Implement `process_user_input(...) -> ProcessedInput`: validate → guardrails → mask_pii. On failure raises `SafetyError(reason: str, code: str)`. FastAPI registers an exception handler mapping `SafetyError` → HTTP 400.
- Tests in `tests/test-stages.py`: valid input passes; blocked phrase raises `SafetyError`; PII masked; integration test for full pipeline.

**Runnable:** `pytest tests/test-stages.py -k stage_4 -v` passes.

---

## Stage 5 — OutputRail

**Scope:** [output/output_rail.py](../output/output_rail.py).

- Implement `UserProfile` StrEnum: `BEGINNER`, `LONG_TERM`, `ANALYST`. Input normalized to lowercase; unknown values return HTTP 400.
- Implement `check_compliance(text) -> ComplianceResult`: keyword check (e.g. no "buy"/"sell" in isolation).
- Implement `format_for_user(text, user_profile: UserProfile) -> str`: switch on profile, return string with appropriate disclaimer.
- Tests in `tests/test-stages.py`: compliance pass/fail; `format_for_user` returns str for all three profiles with distinct content; unknown profile rejected.

**Runnable:** `pytest tests/test-stages.py -k stage_5 -v` passes.

---

## Stage 6 — MCP server and client (in-process)

**Scope:** [mcp/mcp_server.py](../mcp/mcp_server.py), [mcp/mcp_client.py](../mcp/mcp_client.py), one tool.

- Implement `MCPServer.register_tool(name, handler)` (store handler) and `dispatch(tool_name, payload)` (call handler, return dict; catch exceptions → return error dict).
- Implement `MCPClient`: hold reference to server; `call_tool(tool_name, payload)` calls `server.dispatch`.
- Implement [mcp/tools/file_tool.py](../mcp/tools/file_tool.py) `read_file`: read from path, return `{"content": ..., "path": ...}`.
- Register as `"file_tool.read_file"` (namespaced convention). Test: `client.call_tool("file_tool.read_file", {"path": "CHANGELOG.md"})` returns content.
- Tests in `tests/test-stages.py`: register + dispatch; call_tool success; unknown tool returns error dict; handler exception returns error dict.

**Runnable:** `pytest tests/test-stages.py -k stage_6 -v` passes..

---

## Stage 7 — vector_tool (Milvus)

**Scope:** [mcp/tools/vector_tool.py](../mcp/tools/vector_tool.py).

- Implement `search(query, top_k, filter?)`: embed query using `sentence-transformers/all-MiniLM-L6-v2` (model and dim from `EMBEDDING_MODEL` / `EMBEDDING_DIM` env vars, defaults `all-MiniLM-L6-v2` / `384`); search Milvus collection via `MILVUS_URI`; return list of docs with scores.
- Implement `index_documents(docs)`: embed and insert into collection.
- Test stub: zero-vector of length `EMBEDDING_DIM` instead of real model. Mock Milvus connection so tests pass without a running instance.
- Register as `"vector_tool.search"` and `"vector_tool.index_documents"`.
- Tests in `tests/test-stages.py`: search returns list with scores; index_documents returns status; embedding uses configured dim.

**Runnable:** `pytest tests/test-stages.py -k stage_7 -v` passes (mock); optional manual run with real Milvus.

---

## Stage 8 — kg_tool (Neo4j)

**Scope:** [mcp/tools/kg_tool.py](../mcp/tools/kg_tool.py).

- Implement `query_graph(cypher, params?)`: Neo4j driver, run Cypher, return nodes/edges dict.
- Implement `get_relations(entity)`: parameterised Cypher query for entity relations.
- Register as `"kg_tool.query_graph"` and `"kg_tool.get_relations"`.
- Tests in `tests/test-stages.py`: mock Neo4j driver; query_graph returns nodes/edges dict; get_relations returns relation dict.

**Runnable:** `pytest tests/test-stages.py -k stage_8 -v` passes.

---

## Stage 8b — sql_tool (PostgreSQL)

**Scope:** [mcp/tools/sql_tool.py](../mcp/tools/sql_tool.py).

- Implement `run_query(query: str, params?: dict) -> dict`: execute parameterised SQL against PostgreSQL (via `psycopg2` or `asyncpg`); return rows as list of dicts.
- Config: `DATABASE_URL` env var.
- Register as `"sql_tool.run_query"`.
- Tests in `tests/test-stages.py`: mock PostgreSQL connection; run_query returns expected rows dict; parameterised query uses params correctly.

**Runnable:** `pytest tests/test-stages.py -k stage_8b -v` passes.

---

## Stage 9 — market_tool (Tavily + Yahoo)

**Scope:** [mcp/tools/market_tool.py](../mcp/tools/market_tool.py).

- Implement `fetch(fund_or_symbol) -> dict`: call Yahoo and/or Tavily; return dict with `timestamp`.
- Implement `fetch_bulk(symbols) -> dict`: timestamp per symbol.
- Implement `search_web(query) -> list` (Tavily): each result includes `timestamp`.
- Register as `"market_tool.fetch"`, `"market_tool.fetch_bulk"`, `"market_tool.search_web"`.
- Tests in `tests/test-stages.py`: mock HTTP (pytest-httpx); fetch returns dict with timestamp; fetch_bulk has timestamp per symbol; search_web results each have timestamp.

**Runnable:** `pytest tests/test-stages.py -k stage_9 -v` passes.

---

## Stage 10 — analyst_tool (custom API)

**Scope:** [mcp/tools/analyst_tool.py](../mcp/tools/analyst_tool.py).

- Implement `run_analysis(payload: dict) -> dict`: POST to `ANALYST_API_URL`; include `ANALYST_API_KEY` auth header if configured.
- Stub schema: request `{ "returns": [...], "horizon": 252 }`, response `{ "sharpe": 1.4, "max_drawdown": -0.12, "distribution": { "mean": 0.08, "std": 0.15 } }`.
- Register as `"analyst_tool.run_analysis"`.
- Tests in `tests/test-stages.py`: mock HTTP; assert POST to correct URL; response matches stub shape; auth header present when key configured.

**Runnable:** `pytest tests/test-stages.py -k stage_10 -v` passes.

---

## Stage 11 — PlannerAgent (stub decomposition)

**Scope:** [agents/planner_agent.py](../agents/planner_agent.py).

- Implement `decompose_task(query) -> List[TaskStep]` — stub always returns three `TaskStep` objects: `{ agent: "librarian", action: "retrieve_fund_facts", params: {query} }`, `{ agent: "websearcher", action: "fetch_market_data", params: {query} }`, `{ agent: "analyst", action: "run_analysis", params: {query} }`.
- Implement `create_research_request(step, accumulated_data)`: build `ACLMessage(performative=REQUEST, receiver=step.agent, content={query, step, data: accumulated_data})`.
- Implement `handle_message`: on initial REQUEST from REST/main → call `decompose_task` → send all three REQUEST messages in parallel (no waiting between sends) → track expected replies in a dict. On each INFORM reply → store result → call `compute_sufficiency`. If score ≥ `PLANNER_SUFFICIENCY_THRESHOLD` → send REQUEST to Responder.
- Implement `compute_sufficiency(collected: dict) -> float` — stub always returns `1.0`. `PLANNER_SUFFICIENCY_THRESHOLD` env var default `0.6`.
- Tests in `tests/test-stages.py`: send REQUEST to Planner → assert three messages sent (one to each specialist) in the same round. `compute_sufficiency` returns float. After all three INFORMs received → assert REQUEST sent to Responder.

**Runnable:** `pytest tests/test-stages.py -k stage_11 -v` passes.

---

## Stage 12 — LibrarianAgent

**Scope:** [agents/librarian_agent.py](../agents/librarian_agent.py).

- Implement `handle_message`: parse request, call `retrieve_documents`, `retrieve_knowledge_graph`, and `retrieve_sql` via MCPClient, call `combine_results`, send INFORM reply to Planner.
- `retrieve_documents`: `mcp_client.call_tool("vector_tool.search", {query, top_k})`.
- `retrieve_knowledge_graph`: `mcp_client.call_tool("kg_tool.query_graph", {cypher, params})`.
- `retrieve_sql`: `mcp_client.call_tool("sql_tool.run_query", {query, params})`.
- Tests in `tests/test-stages.py`: mock MCPClient; assert all three tool names called; reply ACLMessage sent to Planner with combined result in content.

**Runnable:** `pytest tests/test-stages.py -k stage_12 -v` passes.

---

## Stage 13 — WebSearcherAgent

**Scope:** [agents/websearch_agent.py](../agents/websearch_agent.py).

- Implement `handle_message`: parse request, call `fetch_market_data` (`"market_tool.fetch"`), optionally `fetch_sentiment` / `fetch_regulatory` (`"market_tool.search_web"`); send INFORM reply to Planner with timestamp in content.
- Tests in `tests/test-stages.py`: mock MCPClient; assert reply contains timestamp field; receiver is Planner.

**Runnable:** `pytest tests/test-stages.py -k stage_13 -v` passes.

---

## Stage 14 — AnalystAgent

**Scope:** [agents/analyst_agent.py](../agents/analyst_agent.py).

- Implement `handle_message`: receive structured_data and market_data from content; call `analyze` (calls `"analyst_tool.run_analysis"` via MCPClient); call `needs_more_data`.
- `needs_more_data(confidence: float) -> bool`: returns True when confidence < `ANALYST_CONFIDENCE_THRESHOLD` (env var, default `0.6`) → send REQUEST (refinement) to Planner. Otherwise send INFORM (analysis result) to Planner.
- Tests in `tests/test-stages.py`: mock MCPClient; when needs_more_data is False → assert INFORM sent to Planner; when True → assert REQUEST sent to Planner. `analyze` returns dict; `needs_more_data` returns bool.

**Runnable:** `pytest tests/test-stages.py -k stage_14 -v` passes.

---

## Stage 15 — ResponderAgent

**Scope:** [agents/responder_agent.py](../agents/responder_agent.py).

- Implement `handle_message`: receive analysis from Planner; call `evaluate_confidence(analysis: dict) -> float` (stub returns `0.8`); call `should_terminate`.
- `should_terminate`: returns True when confidence ≥ `RESPONDER_CONFIDENCE_THRESHOLD` (env var, default `0.75`) → call `format_response` via OutputRail → call `check_compliance` → send INFORM (final response) to Planner → call `conversation_manager.broadcast_stop`. When False → send REQUEST (refinement) to Planner.
- Inject OutputRail and ConversationManager into Responder constructor.
- Tests in `tests/test-stages.py`: mock bus and OutputRail; assert evaluate_confidence called with dict only; when terminating: format_response called, check_compliance called, final INFORM sent, broadcast_stop called with STOP performative.

**Runnable:** `pytest tests/test-stages.py -k stage_15 -v` passes.

---

## Stage 16 — End-to-end agent loop (no HTTP)

**Scope:** [main.py](../main.py), wiring.

- In `main()`: create `InMemoryMessageBus`; call `register_agent` for each agent name; create `ConversationManager`, `SafetyGateway`, `MCPClient`/`MCPServer` (all tools registered with namespaced names); instantiate all agents (Planner, Librarian, WebSearcher, Analyst, Responder) injecting bus and mcp_client; start each in a daemon thread (`agent.run()`).
- `--e2e-once` flag: call `SafetyGateway.process_user_input`; create conversation; send ACLMessage to Planner; block on `state.completion_event.wait(timeout=E2E_TIMEOUT_SECONDS)` (default 30s). On completion print final response and exit 0. On timeout exit 0 (non-fatal for stub stages). Use stub/mock tools (no real Milvus/Neo4j/APIs required).

**Runnable:** `PYTHONPATH=. python main.py --e2e-once` completes one conversation and exits 0.

---

## Stage 17 — REST API (POST /chat)

**Scope:** [api/rest.py](../api/rest.py).

- Implement `create_app(bus, manager, safety, mcp_client)`: returns FastAPI app with all state injected; route handlers close over dependencies. `main()` creates all objects and passes them in; tests call `create_app(mock_bus, ...)` directly.
- **POST /chat** body: `{ query: str, conversation_id?: str, user_id?: str (default ""), user_profile?: UserProfile }`.
  - `SafetyGateway.process_user_input` → raises `SafetyError` → HTTP 400.
  - If `conversation_id` supplied → `get_conversation`; else → `create_conversation(user_id, query)`.
  - Send `ACLMessage(REQUEST)` to Planner.
  - Block on `state.completion_event.wait(timeout=E2E_TIMEOUT_SECONDS)`.
  - On success: return `200 { conversation_id, status: "complete", response }`.
  - On timeout: return `408 { status: "timeout", conversation_id, response: null }`.
- Register `SafetyError` exception handler → HTTP 400.
- Mount app in `main()`; run with uvicorn.

**Runnable:** `uvicorn api.rest:app` (or via main); `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"fund X performance"}'` returns 200 JSON with response.

---

## Stage 18 — GET /conversations and WebSocket

**Scope:** [api/rest.py](../api/rest.py) GET endpoint, [api/websocket.py](../api/websocket.py).

- Implement **GET /conversations/{id}**: return conversation state JSON (messages, status, final_response).
- Implement **WebSocket /ws**: accept connection; receive JSON `{ query, conversation_id?, user_id?, user_profile? }`; same flow as POST /chat but send discrete JSON event messages over the socket:
  - `{"event": "status", "agent": "<name>", "message": "working"}` — one per agent as it starts.
  - `{"event": "response", "conversation_id": "...", "response": "..."}` — once when Responder completes.
  - Token-level streaming deferred to Stage 19.

**Runnable:** GET /conversations/{id} returns state JSON; WebSocket client receives status events then final response event.

---

## Stage 19 — LLM integration (Phase 2)

**Scope:** [agents/planner_agent.py](../agents/planner_agent.py), new LLM client module.

- Add LLM client (OpenAI/Claude) behind config (`LLM_API_KEY`, `LLM_MODEL`); call from Planner.
- Replace stub `decompose_task` and `compute_sufficiency` with LLM-based implementations (ReAct-style prompt). Keep `create_research_request` and all message flow unchanged.
- LangGraph graph topology is deferred to Stage 20+.

**Runnable:** POST /chat with natural language query returns a response that reflects LLM-decomposed steps (manual or integration test).

---

## Summary diagram

```mermaid
flowchart LR
  S1[Stage 1 Config]
  S2[Stage 2 MessageBus]
  S3[Stage 3 ConvMgr]
  S4[Stage 4 Safety]
  S5[Stage 5 OutputRail]
  S6[Stage 6 MCP]
  S7[Stage 7 Vector]
  S8[Stage 8 KG]
  S8b[Stage 8b SQL]
  S9[Stage 9 Market]
  S10[Stage 10 Analyst]
  S11[Stage 11 Planner]
  S12[Stage 12 Librarian]
  S13[Stage 13 WebSearcher]
  S14[Stage 14 AnalystAgent]
  S15[Stage 15 Responder]
  S16[Stage 16 E2E Loop]
  S17[Stage 17 REST]
  S18[Stage 18 WS]
  S1 --> S2 --> S3
  S3 --> S4 --> S5 --> S6
  S6 --> S7 --> S8 --> S8b --> S9 --> S10
  S10 --> S11 --> S12 --> S13 --> S14 --> S15
  S15 --> S16 --> S17 --> S18
```

---

## Test layout

All tests live in `tests/test-stages.py`. Run the full suite with `pytest tests/test-stages.py -v`, or a single stage with `pytest tests/test-stages.py -k stage_N -v`.

| Stage | Filter | Runnable command |
|-------|--------|-----------------|
| 1 | — | `PYTHONPATH=. python main.py` |
| 2 | `stage_2` | `pytest tests/test-stages.py -k stage_2 -v` |
| 3 | `stage_3` | `pytest tests/test-stages.py -k stage_3 -v` |
| 4 | `stage_4` | `pytest tests/test-stages.py -k stage_4 -v` |
| 5 | `stage_5` | `pytest tests/test-stages.py -k stage_5 -v` |
| 6 | `stage_6` | `pytest tests/test-stages.py -k stage_6 -v` |
| 7 | `stage_7` | `pytest tests/test-stages.py -k stage_7 -v` |
| 8 | `stage_8` | `pytest tests/test-stages.py -k stage_8 -v` |
| 8b | `stage_8b` | `pytest tests/test-stages.py -k stage_8b -v` |
| 9 | `stage_9` | `pytest tests/test-stages.py -k stage_9 -v` |
| 10 | `stage_10` | `pytest tests/test-stages.py -k stage_10 -v` |
| 11 | `stage_11` | `pytest tests/test-stages.py -k stage_11 -v` |
| 12 | `stage_12` | `pytest tests/test-stages.py -k stage_12 -v` |
| 13 | `stage_13` | `pytest tests/test-stages.py -k stage_13 -v` |
| 14 | `stage_14` | `pytest tests/test-stages.py -k stage_14 -v` |
| 15 | `stage_15` | `pytest tests/test-stages.py -k stage_15 -v` |
| 16 | — | `PYTHONPATH=. python main.py --e2e-once` |
| 17 | — | `curl` POST /chat (see stage description) |
| 18 | — | GET /conversations/{id}; WebSocket client |
| 19 | — | POST /chat with NL query |

Add `pytest`, `pytest-asyncio`, `pytest-httpx` to `pyproject.toml` dev dependencies.
