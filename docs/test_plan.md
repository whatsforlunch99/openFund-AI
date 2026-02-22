# Test Plan — Tests per Stage

This document lists the tests and runnable checks for each stage of the [staged implementation plan](staged_implementation_plan.md).

All tests live in `tests/test-stages.py`. Each stage's tests are in a single test function named `test_stage_N`. Run with:

```
pytest tests/test-stages.py -v           # full suite
pytest tests/test-stages.py -k stage_2 -v  # single stage
```

---

## Stage 1 — Config and minimal main

| Type | Description | Command |
|------|-------------|---------|
| Runnable | main loads config and prints ready message | `PYTHONPATH=. python main.py` prints "OpenFund-AI ready (config loaded)" and exits 0 |

*No pytest function for Stage 1; checkpoint is the CLI command.*

---

## Stage 2 — In-memory MessageBus

**Function:** `test_stage_2` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| Send and receive | `send(msg, receiver="a")` → `receive("a")` returns same message |
| Broadcast | register two agents, `broadcast(msg)` → both agents receive it |
| Timeout | `receive("empty_agent", timeout=0.1)` returns `None` when no message |
| register_agent | unregistered agent name not included in broadcast |

**Runnable:** `pytest tests/test-stages.py -k stage_2 -v`

---

## Stage 3 — ConversationManager

**Function:** `test_stage_3` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| create_conversation | returns valid UUID; state has correct fields (id, user_id, initial_query, status="active", final_response=None) |
| get_conversation | returns same state by id |
| register_reply | message appended to state.messages; if final response: status="complete", final_response set, completion_event.is_set() == True |
| JSON persistence | file written to `memory/<user_id>/conversations.json` on create and register_reply; file content is valid JSON |
| anonymous user | file written to `memory/anonymous/conversations.json` when user_id="" |
| auto-create dir | directory created with os.makedirs if it doesn't exist |
| broadcast_stop | ACLMessage with `performative == Performative.STOP` sent via bus broadcast |

**Runnable:** `pytest tests/test-stages.py -k stage_3 -v`

---

## Stage 4 — SafetyGateway

**Function:** `test_stage_4` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| validate_input passes | valid query returns ValidationResult with passed=True |
| check_guardrails blocks | "buy now", "sell immediately" return GuardrailResult with allowed=False |
| mask_pii | phone/ID patterns replaced with placeholder |
| process_user_input success | returns ProcessedInput with masked content |
| process_user_input blocked | raises `SafetyError` with reason and code fields |
| SafetyError fields | `SafetyError(reason, code)` has both attributes |

**Runnable:** `pytest tests/test-stages.py -k stage_4 -v`

---

## Stage 5 — OutputRail

**Function:** `test_stage_5` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| check_compliance passes | text without buy/sell returns ComplianceResult with passed=True |
| check_compliance fails | text with explicit advice returns ComplianceResult with passed=False and reason |
| format_for_user beginner | returns str; content appropriate for beginner |
| format_for_user long_term | returns str; distinct from beginner output |
| format_for_user analyst | returns str; distinct from other profiles |
| UserProfile StrEnum | `UserProfile.BEGINNER == "beginner"`, `UserProfile.LONG_TERM == "long_term"`, etc. |
| case normalization | "BEGINNER" and "Beginner" both map to UserProfile.BEGINNER |

**Runnable:** `pytest tests/test-stages.py -k stage_5 -v`

---

## Stage 6 — MCP server and client

**Function:** `test_stage_6` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| register_tool | handler stored; dispatch calls it with payload, returns result dict |
| call_tool file_tool | `client.call_tool("file_tool.read_file", {"path": "CHANGELOG.md"})` returns dict with "content" and "path" keys |
| unknown tool | `dispatch("nonexistent.tool", {})` returns error dict (not exception) |
| handler exception | handler that raises → dispatch returns error dict |
| namespaced convention | tool registered as `"file_tool.read_file"` not `"read_file"` |

**Runnable:** `pytest tests/test-stages.py -k stage_6 -v`

---

## Stage 7 — vector_tool (Milvus)

**Function:** `test_stage_7` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| search returns scores | mock backend: `search(query, top_k=3)` returns list of dicts with score field |
| index_documents | accepts list of docs, returns status dict |
| embedding dim | zero-vector stub has length equal to EMBEDDING_DIM (default 384) |
| config-driven model | EMBEDDING_MODEL and EMBEDDING_DIM env vars read by tool |
| no real Milvus needed | all tests use mock; no network calls |

**Runnable:** `pytest tests/test-stages.py -k stage_7 -v`

---

## Stage 8 — kg_tool (Neo4j)

**Function:** `test_stage_8` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| query_graph | mock Neo4j: `query_graph(cypher, params)` returns dict with nodes and edges keys |
| get_relations | `get_relations(entity)` returns relation dict |
| no real Neo4j needed | mock driver; no network calls |

**Runnable:** `pytest tests/test-stages.py -k stage_8 -v`

---

## Stage 8b — sql_tool (PostgreSQL)

**Function:** `test_stage_8b` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| run_query returns rows | mock connection: `run_query(sql, params)` returns list of row dicts |
| params forwarded | mock asserts params passed to execute() |
| DATABASE_URL read | tool reads config from DATABASE_URL env var |
| no real PostgreSQL needed | mock connection; no network calls |

**Runnable:** `pytest tests/test-stages.py -k stage_8b -v`

---

## Stage 9 — market_tool (Tavily + Yahoo)

**Function:** `test_stage_9` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| fetch has timestamp | mock HTTP: `fetch(symbol)` returns dict with "timestamp" key |
| fetch_bulk timestamps | `fetch_bulk(symbols)` returns dict with timestamp per symbol |
| search_web timestamps | `search_web(query)` returns list; each result has "timestamp" |
| no API keys needed | mock HTTP (pytest-httpx); no real network calls |

**Runnable:** `pytest tests/test-stages.py -k stage_9 -v`

---

## Stage 10 — analyst_tool (custom API)

**Function:** `test_stage_10` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| run_analysis POSTs | mock HTTP: request made to ANALYST_API_URL |
| response shape | response dict has sharpe, max_drawdown, distribution keys (stub schema) |
| auth header | when ANALYST_API_KEY set, request includes auth header |
| no real API needed | mock HTTP; no network calls |

**Runnable:** `pytest tests/test-stages.py -k stage_10 -v`

---

## Stage 11 — PlannerAgent

**Function:** `test_stage_11` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| parallel dispatch | send REQUEST to Planner → three messages sent (one each to librarian, websearcher, analyst) |
| REQUEST performative | all three outbound messages have performative REQUEST |
| compute_sufficiency stub | returns 1.0 (float) |
| threshold check | when all three INFORMs received, if score ≥ PLANNER_SUFFICIENCY_THRESHOLD → REQUEST sent to Responder |
| create_research_request | returns ACLMessage with performative REQUEST, correct receiver, query and step in content |

**Runnable:** `pytest tests/test-stages.py -k stage_11 -v`

---

## Stage 12 — LibrarianAgent

**Function:** `test_stage_12` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| calls all three tools | mock MCPClient: `"vector_tool.search"`, `"kg_tool.query_graph"`, `"sql_tool.run_query"` all called |
| reply to Planner | INFORM sent with receiver="planner" |
| combined result | reply content contains combined data from all three tools |

**Runnable:** `pytest tests/test-stages.py -k stage_12 -v`

---

## Stage 13 — WebSearcherAgent

**Function:** `test_stage_13` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| calls market_tool | mock MCPClient: `"market_tool.fetch"` called |
| reply has timestamp | INFORM reply content contains timestamp field |
| reply to Planner | receiver is planner |

**Runnable:** `pytest tests/test-stages.py -k stage_13 -v`

---

## Stage 14 — AnalystAgent

**Function:** `test_stage_14` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| analyze calls analyst_tool | mock MCPClient: `"analyst_tool.run_analysis"` called |
| analyze returns dict | result has sharpe, max_drawdown, distribution keys |
| needs_more_data False | confidence=0.8 (above 0.6 threshold) → INFORM sent to Planner |
| needs_more_data True | confidence=0.4 (below 0.6 threshold) → REQUEST (refinement) sent to Planner |
| threshold configurable | ANALYST_CONFIDENCE_THRESHOLD env var respected |

**Runnable:** `pytest tests/test-stages.py -k stage_14 -v`

---

## Stage 15 — ResponderAgent

**Function:** `test_stage_15` in `tests/test-stages.py`

| Test | Assertion |
|------|-----------|
| evaluate_confidence stub | returns 0.8; takes analysis dict only |
| should_terminate True | confidence 0.8 ≥ 0.75 threshold → format_response and check_compliance called |
| final INFORM sent | INFORM with final response content sent |
| broadcast_stop called | ConversationManager.broadcast_stop called with STOP performative |
| should_terminate False | confidence below threshold → REQUEST (refinement) sent to Planner; no broadcast |
| threshold configurable | RESPONDER_CONFIDENCE_THRESHOLD env var respected |

**Runnable:** `pytest tests/test-stages.py -k stage_15 -v`

---

## Stage 16 — End-to-end agent loop

| Type | Description | Command |
|------|-------------|---------|
| Runnable | One full conversation with all agents | `PYTHONPATH=. python main.py --e2e-once` completes and exits 0; prints final response |

*No pytest function required; checkpoint is the CLI command. Stub/mock tools used — no real external services needed.*

---

## Stage 17 — REST API (POST /chat)

| Type | Description | Command |
|------|-------------|---------|
| Runnable | POST /chat returns 200 and JSON | `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"fund X performance"}'` returns 200, body has conversation_id, status, response |
| Timeout | POST /chat with slow agents | returns 408 with `{"status": "timeout", "conversation_id": "...", "response": null}` |
| Optional pytest | TestClient smoke test | `create_app(mock_bus, ...)` → POST /chat → assert 200 schema |

---

## Stage 18 — GET /conversations and WebSocket

| Type | Description | Command |
|------|-------------|---------|
| Runnable | GET /conversations/{id} | returns conversation state JSON (id, status, messages, final_response) |
| Runnable | WebSocket /ws | connect, send query, receive `{"event":"status",...}` events then `{"event":"response",...}` |

---

## Stage 19 — LLM integration

| Type | Description | Command |
|------|-------------|---------|
| Manual / integration | LLM task decomposition and sufficiency scoring | POST /chat with natural language query; response reflects LLM-driven steps |

---

## Summary: stages and commands

| Stage | Function in test-stages.py | Runnable command |
|-------|---------------------------|-----------------|
| 1 | — | `PYTHONPATH=. python main.py` |
| 2 | `test_stage_2` | `pytest tests/test-stages.py -k stage_2 -v` |
| 3 | `test_stage_3` | `pytest tests/test-stages.py -k stage_3 -v` |
| 4 | `test_stage_4` | `pytest tests/test-stages.py -k stage_4 -v` |
| 5 | `test_stage_5` | `pytest tests/test-stages.py -k stage_5 -v` |
| 6 | `test_stage_6` | `pytest tests/test-stages.py -k stage_6 -v` |
| 7 | `test_stage_7` | `pytest tests/test-stages.py -k stage_7 -v` |
| 8 | `test_stage_8` | `pytest tests/test-stages.py -k stage_8 -v` |
| 8b | `test_stage_8b` | `pytest tests/test-stages.py -k stage_8b -v` |
| 9 | `test_stage_9` | `pytest tests/test-stages.py -k stage_9 -v` |
| 10 | `test_stage_10` | `pytest tests/test-stages.py -k stage_10 -v` |
| 11 | `test_stage_11` | `pytest tests/test-stages.py -k stage_11 -v` |
| 12 | `test_stage_12` | `pytest tests/test-stages.py -k stage_12 -v` |
| 13 | `test_stage_13` | `pytest tests/test-stages.py -k stage_13 -v` |
| 14 | `test_stage_14` | `pytest tests/test-stages.py -k stage_14 -v` |
| 15 | `test_stage_15` | `pytest tests/test-stages.py -k stage_15 -v` |
| 16 | — | `PYTHONPATH=. python main.py --e2e-once` |
| 17 | — | `curl` POST /chat |
| 18 | — | GET /conversations/{id}; WebSocket client |
| 19 | — | POST /chat with NL query |
