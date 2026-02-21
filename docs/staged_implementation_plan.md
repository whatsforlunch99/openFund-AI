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

- Implement a concrete `MessageBus`: per-agent queues (e.g. `defaultdict(list)`), `send` appends to receiver queue, `receive` pops from agent queue (block with optional timeout), `broadcast` appends to all known agent queues.
- Add a small test module (e.g. `tests/test_message_bus.py`): send message, receive by agent, assert content; test broadcast.

**Runnable:** `pytest tests/test_message_bus.py -v` passes.

---

## Stage 3 — ConversationManager

**Scope:** [a2a/conversation_manager.py](../a2a/conversation_manager.py).

- Implement `create_conversation`: generate UUID, store `ConversationState`, return id.
- Implement `get_conversation`, `register_reply` (append message to state), `broadcast_stop` (build STOP ACLMessage, call `message_bus.broadcast`).
- Tests: create conversation, get state, register reply, broadcast_stop; assert STOP message performative.

**Runnable:** `pytest tests/test_conversation_manager.py -v` passes.

---

## Stage 4 — SafetyGateway

**Scope:** [safety/safety_gateway.py](../safety/safety_gateway.py).

- Implement `validate_input`: length and charset checks; return `ValidationResult`.
- Implement `check_guardrails`: block list of phrases (e.g. "buy now", "sell immediately"); return `GuardrailResult`.
- Implement `mask_pii`: regex for phone/ID patterns, replace with placeholder; return masked string.
- Implement `process_user_input`: validate -> guardrails -> mask_pii; return `ProcessedInput` or raise/return error.
- Tests: valid input passes, blocked phrase fails, PII masked, process_user_input integration.

**Runnable:** `pytest tests/test_safety_gateway.py -v` passes.

---

## Stage 5 — OutputRail

**Scope:** [output/output_rail.py](../output/output_rail.py).

- Implement `check_compliance`: keyword check (e.g. no "buy"/"sell" in isolation); return `ComplianceResult`.
- Implement `format_for_user`: switch on `user_profile` (beginner / long_term / analyst), return string (stub text or add disclaimer).
- Tests: compliance pass/fail, format_for_user returns str per profile.

**Runnable:** `pytest tests/test_output_rail.py -v` passes.

---

## Stage 6 — MCP server and client (in-process)

**Scope:** [mcp/mcp_server.py](../mcp/mcp_server.py), [mcp/mcp_client.py](../mcp/mcp_client.py), one tool.

- Implement `MCPServer.register_tool` (store handler) and `dispatch` (call handler with payload, return dict; catch exceptions, return error dict).
- Implement `MCPClient`: hold reference to server; `call_tool` calls `server.dispatch(tool_name, payload)`.
- Implement [mcp/tools/file_tool.py](../mcp/tools/file_tool.py) `read_file`: read from path, return `{"content": ..., "path": ...}`.
- Register file_tool with server; test client.call_tool("read_file", {"path": "CHANGELOG.md"}) returns content.

**Runnable:** `pytest tests/test_mcp_client_server.py -v` passes (and/or `python -c "from mcp.mcp_client import MCPClient; ..."`).

---

## Stage 7 — vector_tool (Milvus)

**Scope:** [mcp/tools/vector_tool.py](../mcp/tools/vector_tool.py), [config/config.py](../config/config.py) already has MILVUS_*.

- Implement `search`: connect to Milvus (from config), embed query (use a simple embedding or Milvus built-in if available), search collection, return list of docs with scores.
- Implement `index_documents`: embed docs, insert into collection.
- Use pymilvus client; config from env. For **runnable without Milvus**: add a mock backend in tests (e.g. in-memory list of docs) so pytest passes without a running Milvus.

**Runnable:** `pytest tests/test_vector_tool.py -v` passes (mock); optional manual run with real Milvus.

---

## Stage 8 — kg_tool (Neo4j)

**Scope:** [mcp/tools/kg_tool.py](../mcp/tools/kg_tool.py).

- Implement `query_graph`: Neo4j driver, run Cypher with params, return nodes/edges dict.
- Implement `get_relations`: run a parameterized Cypher query for entity relations.
- Tests: mock Neo4j (e.g. in-memory or neo4j-mock) so pytest passes without a running Neo4j.

**Runnable:** `pytest tests/test_kg_tool.py -v` passes.

---

## Stage 9 — market_tool (Tavily + Yahoo)

**Scope:** [mcp/tools/market_tool.py](../mcp/tools/market_tool.py).

- Implement `fetch`: call Yahoo (and/or Tavily) API for symbol; ensure return dict includes `timestamp`.
- Implement `fetch_bulk`, `search_web` (Tavily); all returns include timestamp.
- Tests: mock HTTP (responses or pytest-httpx) so tests pass without API keys.

**Runnable:** `pytest tests/test_market_tool.py -v` passes.

---

## Stage 10 — analyst_tool (custom API)

**Scope:** [mcp/tools/analyst_tool.py](../mcp/tools/analyst_tool.py).

- Implement `run_analysis`: POST payload to `ANALYST_API_URL` (from config), optional auth header; return response dict.
- Tests: mock HTTP server returning fixed analysis; assert request/response shape.

**Runnable:** `pytest tests/test_analyst_tool.py -v` passes.

---

## Stage 11 — PlannerAgent (stub decomposition)

**Scope:** [agents/planner_agent.py](../agents/planner_agent.py).

- Implement `handle_message`: parse content (query), call `decompose_task` (stub: return single TaskStep e.g. "retrieve_fund_facts"), call `create_research_request`, send ACLMessage to Librarian via bus.
- Implement `create_research_request`: build ACLMessage with performative "request", content = {query, step}.
- No LLM: fixed task chain. Tests: send message to Planner, assert one message sent to Librarian.

**Runnable:** `pytest tests/test_planner_agent.py -v` passes.

---

## Stage 12 — LibrarianAgent

**Scope:** [agents/librarian_agent.py](../agents/librarian_agent.py).

- Implement `handle_message`: parse request, call `retrieve_documents` and `retrieve_knowledge_graph` via MCP client, call `combine_results`, send reply ACLMessage to Planner (or next agent per your protocol).
- Implement retrieve_* to call mcp_client.call_tool("vector_tool.search", ...) and ("kg_tool.query_graph", ...).
- Tests: mock MCP client returning fixed docs/graph; assert reply content and receiver.

**Runnable:** `pytest tests/test_librarian_agent.py -v` passes.

---

## Stage 13 — WebSearcherAgent

**Scope:** [agents/websearch_agent.py](../agents/websearch_agent.py).

- Implement `handle_message`: parse request, call `fetch_market_data` (and optionally fetch_sentiment/fetch_regulatory) via MCP; send reply with timestamp in content.
- Tests: mock MCP client; assert reply contains timestamp.

**Runnable:** `pytest tests/test_websearch_agent.py -v` passes.

---

## Stage 14 — AnalystAgent

**Scope:** [agents/analyst_agent.py](../agents/analyst_agent.py).

- Implement `handle_message`: receive structured_data and market_data from content; call `analyze` (stub or call analyst_tool); if `needs_more_data` send refinement request to Planner else send result to Responder.
- Implement `analyze`, `needs_more_data` (e.g. confidence threshold); optional local `sharpe_ratio`/`max_drawdown` or delegate to analyst_tool.
- Tests: mock MCP; assert outbound message to Responder or Planner.

**Runnable:** `pytest tests/test_analyst_agent.py -v` passes.

---

## Stage 15 — ResponderAgent

**Scope:** [agents/responder_agent.py](../agents/responder_agent.py).

- Implement `handle_message`: receive analysis; `evaluate_confidence` (stub: return 0.8); if not `should_terminate` send `request_refinement` to Planner else `format_response` via OutputRail, run `check_compliance`, then send final response; call `conversation_manager.broadcast_stop`.
- Inject OutputRail and ConversationManager into Responder. Tests: mock bus and output rail; assert STOP broadcast and final message.

**Runnable:** `pytest tests/test_responder_agent.py -v` passes.

---

## Stage 16 — End-to-end agent loop (no HTTP)

**Scope:** [main.py](../main.py), wiring.

- In `main()`: create InMemoryMessageBus, ConversationManager, SafetyGateway, MCPClient + MCPServer (with tools registered), all agents (Planner, Librarian, WebSearcher, Analyst, Responder) with bus and mcp_client; start each agent in a thread (agent.run()); create one conversation, send one ACLMessage (request) to Planner; wait for final reply or timeout (e.g. 30s); assert response in conversation state.
- Add a flag or script: `python main.py --e2e-once` that runs one conversation and exits. Use stub/mock tools so no real Milvus/Neo4j/APIs required.

**Runnable:** `PYTHONPATH=. python main.py --e2e-once` completes one conversation and exits 0.

---

## Stage 17 — REST API (POST /chat)

**Scope:** [api/rest.py](../api/rest.py).

- Implement `create_app()`: FastAPI app; POST /chat (body: query, optional conversation_id, user_profile) -> SafetyGateway.process_user_input -> ConversationManager.create_or_get -> send ACLMessage to Planner -> wait for Responder reply (poll conversation state or bus), then return JSON (conversation_id, status, response).
- Mount app in main(); run with uvicorn. Use in-process bus and agents (same process).

**Runnable:** Start server (`uvicorn api.rest:app` or via main), `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"fund X performance"}'` returns 200 and JSON with response (or placeholder).

---

## Stage 18 — GET /conversations and WebSocket

**Scope:** [api/rest.py](../api/rest.py) GET endpoint, [api/websocket.py](../api/websocket.py).

- Implement GET /conversations/{id}: return conversation state (messages or summary).
- Implement WebSocket /ws: accept connection, receive message (query + optional ids), same flow as POST /chat but stream partial responses (e.g. when Responder produces chunks) over the socket.

**Runnable:** GET returns state; WebSocket client receives streamed chunks for a query.

---

## Stage 19 — LangGraph / LLM (optional, Phase 2)

**Scope:** [agents/planner_agent.py](../agents/planner_agent.py), new LLM client module.

- Add LLM client (OpenAI/Claude) behind config (llm_api_key, llm_model); call from Planner.
- Replace stub `decompose_task` with LLM-based task decomposition (ReAct-style prompt); keep create_research_request and message flow.

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
  S6 --> S7 --> S8 --> S9 --> S10
  S10 --> S11 --> S12 --> S13 --> S14 --> S15
  S15 --> S16 --> S17 --> S18
```

---

## Suggested test layout

- `tests/test_message_bus.py`, `test_conversation_manager.py`, `test_safety_gateway.py`, `test_output_rail.py`
- `tests/test_mcp_client_server.py`, `test_vector_tool.py`, `test_kg_tool.py`, `test_market_tool.py`, `test_analyst_tool.py`
- `tests/test_planner_agent.py`, `test_librarian_agent.py`, `test_websearch_agent.py`, `test_analyst_agent.py`, `test_responder_agent.py`
- Optional: `tests/test_e2e.py` for Stage 16

Add `pytest` (and optionally `pytest-asyncio`, `pytest-httpx`) to pyproject.toml dependencies when you add tests.
