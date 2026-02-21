# Test Plan — Tests per Stage

This document lists the tests (and runnable checks) for each stage of the [staged implementation plan](staged_implementation_plan.md).

---

## Stage 1 — Config and minimal main

| Type | Description | Command / Assertion |
|------|-------------|---------------------|
| Runnable | main loads config and prints ready message | `PYTHONPATH=. python main.py` prints "OpenFund-AI ready (config loaded)" and exits 0 |

*No pytest file; checkpoint is the CLI command.*

---

## Stage 2 — In-memory MessageBus

| Test file | Tests |
|-----------|--------|
| `tests/test_message_bus.py` | Send message to agent; receive by that agent; assert content matches. Broadcast: send to all agents; each agent receives the message. Optional: receive with timeout returns None when empty. |

**Runnable:** `pytest tests/test_message_bus.py -v`

---

## Stage 3 — ConversationManager

| Test file | Tests |
|-----------|--------|
| `tests/test_conversation_manager.py` | Create conversation returns valid UUID and state. Get conversation returns same state. Register reply appends message to state. Broadcast_stop sends ACLMessage with performative "stop" (or reserved STOP value) via message bus. |

**Runnable:** `pytest tests/test_conversation_manager.py -v`

---

## Stage 4 — SafetyGateway

| Test file | Tests |
|-----------|--------|
| `tests/test_safety_gateway.py` | Valid input: validate_input passes. Blocked phrase: check_guardrails returns allowed=False for e.g. "buy now", "sell immediately". PII: mask_pii replaces phone/ID patterns with placeholder. process_user_input: valid input returns ProcessedInput; blocked input raises or returns error; PII in input is masked in result. |

**Runnable:** `pytest tests/test_safety_gateway.py -v`

---

## Stage 5 — OutputRail

| Test file | Tests |
|-----------|--------|
| `tests/test_output_rail.py` | check_compliance: text without buy/sell passes; text with explicit advice fails with reason. format_for_user: returns str for beginner, long_term, analyst; content or disclaimer differs by profile. |

**Runnable:** `pytest tests/test_output_rail.py -v`

---

## Stage 6 — MCP server and client

| Test file | Tests |
|-----------|--------|
| `tests/test_mcp_client_server.py` | Register_tool stores handler; dispatch calls handler and returns result dict. MCPClient.call_tool("read_file", {"path": "CHANGELOG.md"}) returns dict with "content" and "path". Dispatch with unknown tool or exception returns error dict. |

**Runnable:** `pytest tests/test_mcp_client_server.py -v`

---

## Stage 7 — vector_tool (Milvus)

| Test file | Tests |
|-----------|--------|
| `tests/test_vector_tool.py` | Use mock/in-memory backend: search returns list of docs with scores; index_documents accepts list and returns status. Optional: integration test with real Milvus when configured. |

**Runnable:** `pytest tests/test_vector_tool.py -v`

---

## Stage 8 — kg_tool (Neo4j)

| Test file | Tests |
|-----------|--------|
| `tests/test_kg_tool.py` | Mock Neo4j: query_graph(cypher, params) returns nodes/edges dict; get_relations(entity) returns relation dict. |

**Runnable:** `pytest tests/test_kg_tool.py -v`

---

## Stage 9 — market_tool (Tavily + Yahoo)

| Test file | Tests |
|-----------|--------|
| `tests/test_market_tool.py` | Mock HTTP: fetch(symbol) returns dict with "timestamp". fetch_bulk(symbols) returns dict with timestamp per symbol. search_web(query) returns list of results each with timestamp. |

**Runnable:** `pytest tests/test_market_tool.py -v`

---

## Stage 10 — analyst_tool (custom API)

| Test file | Tests |
|-----------|--------|
| `tests/test_analyst_tool.py` | Mock HTTP server: run_analysis(payload) POSTs to configured URL; response shape matches expected (e.g. metrics, distribution). Optional: assert auth header when config has analyst_api_key. |

**Runnable:** `pytest tests/test_analyst_tool.py -v`

---

## Stage 11 — PlannerAgent

| Test file | Tests |
|-----------|--------|
| `tests/test_planner_agent.py` | Send ACLMessage with content {query: "..."} to Planner; assert one message sent to Librarian (via bus or spy). create_research_request returns ACLMessage with performative "request" and content containing query and step. |

**Runnable:** `pytest tests/test_planner_agent.py -v`

---

## Stage 12 — LibrarianAgent

| Test file | Tests |
|-----------|--------|
| `tests/test_librarian_agent.py` | Mock MCP client returning fixed docs and graph. Send request to Librarian; assert reply ACLMessage to Planner (or next agent) with combined result in content. retrieve_documents / retrieve_knowledge_graph call correct tool names. |

**Runnable:** `pytest tests/test_librarian_agent.py -v`

---

## Stage 13 — WebSearcherAgent

| Test file | Tests |
|-----------|--------|
| `tests/test_websearch_agent.py` | Mock MCP client returning market data with timestamp. Send request to WebSearcher; assert reply content contains timestamp. |

**Runnable:** `pytest tests/test_websearch_agent.py -v`

---

## Stage 14 — AnalystAgent

| Test file | Tests |
|-----------|--------|
| `tests/test_analyst_agent.py` | Mock MCP. Send message with structured_data and market_data; assert outbound message to Responder when needs_more_data is false, or to Planner when true. analyze returns dict; needs_more_data returns bool. |

**Runnable:** `pytest tests/test_analyst_agent.py -v`

---

## Stage 15 — ResponderAgent

| Test file | Tests |
|-----------|--------|
| `tests/test_responder_agent.py` | Mock bus and OutputRail. Send analysis to Responder; assert evaluate_confidence and should_terminate used; when terminating, assert format_response and check_compliance called, final message sent, and conversation_manager.broadcast_stop called. Assert STOP message performative. |

**Runnable:** `pytest tests/test_responder_agent.py -v`

---

## Stage 16 — End-to-end agent loop

| Type | Description | Command / Assertion |
|------|-------------|---------------------|
| Runnable | One full conversation | `PYTHONPATH=. python main.py --e2e-once` completes and exits 0; conversation state contains final response. |
| Optional | `tests/test_e2e.py` | Same flow as script: create bus, agents, send request to Planner, wait for reply or timeout; assert response in state. |

**Runnable:** `PYTHONPATH=. python main.py --e2e-once`

---

## Stage 17 — REST API (POST /chat)

| Type | Description | Command / Assertion |
|------|-------------|---------------------|
| Runnable | POST /chat returns 200 and JSON | Start server; `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"fund X performance"}'` returns 200, body has conversation_id, status, response. |

*Optional:* pytest with TestClient for create_app(); assert status and schema.

---

## Stage 18 — GET /conversations and WebSocket

| Type | Description | Command / Assertion |
|------|-------------|---------------------|
| Runnable | GET /conversations/{id} | Returns conversation state (messages or summary). |
| Runnable | WebSocket /ws | Connect, send query (and optional conversation_id, user_profile); receive streamed chunks of response. |

---

## Stage 19 — LangGraph / LLM (optional)

| Type | Description | Command / Assertion |
|------|-------------|---------------------|
| Manual / integration | LLM task decomposition | POST /chat with natural language query; response reflects LLM-decomposed steps (e.g. multiple task steps or richer answer). |

---

## Summary: test files by stage

| Stage | Test file(s) | Runnable command |
|-------|--------------|-------------------|
| 1 | — | `PYTHONPATH=. python main.py` |
| 2 | `tests/test_message_bus.py` | `pytest tests/test_message_bus.py -v` |
| 3 | `tests/test_conversation_manager.py` | `pytest tests/test_conversation_manager.py -v` |
| 4 | `tests/test_safety_gateway.py` | `pytest tests/test_safety_gateway.py -v` |
| 5 | `tests/test_output_rail.py` | `pytest tests/test_output_rail.py -v` |
| 6 | `tests/test_mcp_client_server.py` | `pytest tests/test_mcp_client_server.py -v` |
| 7 | `tests/test_vector_tool.py` | `pytest tests/test_vector_tool.py -v` |
| 8 | `tests/test_kg_tool.py` | `pytest tests/test_kg_tool.py -v` |
| 9 | `tests/test_market_tool.py` | `pytest tests/test_market_tool.py -v` |
| 10 | `tests/test_analyst_tool.py` | `pytest tests/test_analyst_tool.py -v` |
| 11 | `tests/test_planner_agent.py` | `pytest tests/test_planner_agent.py -v` |
| 12 | `tests/test_librarian_agent.py` | `pytest tests/test_librarian_agent.py -v` |
| 13 | `tests/test_websearch_agent.py` | `pytest tests/test_websearch_agent.py -v` |
| 14 | `tests/test_analyst_agent.py` | `pytest tests/test_analyst_agent.py -v` |
| 15 | `tests/test_responder_agent.py` | `pytest tests/test_responder_agent.py -v` |
| 16 | optional `tests/test_e2e.py` | `PYTHONPATH=. python main.py --e2e-once` |
| 17 | optional TestClient | `curl` POST /chat |
| 18 | optional | GET /conversations/{id}; WebSocket client |
| 19 | optional | POST /chat with NL query |
