# Test Plan — Per-Stage Functionality and Per-Slice Verification

This document aligns with the [staged implementation plan](staged_implementation_plan.md), [clarification.md](clarification.md), [claude-v2.md](claude-v2.md), and [use-case-flows.md](use-case-flows.md). It defines:

1. **Per-stage tests:** Each small stage (e.g. 1.1, 1.2, 2.1) has a test function that asserts **all functionalities** for that stage.
2. **Per-slice verification:** Each slice as a whole is verified for **implementation** (components wired and specified behavior), **runnable** (checkpoint command succeeds), and **ultimate goal** (slice goal met).

All stage tests live in `tests/test-stages.py`. Test functions are named `test_stage_N_M` (e.g. `test_stage_1_2`, `test_stage_2_1`). Run with:

```bash
pytest tests/test-stages.py -v                    # full suite
pytest tests/test-stages.py -k stage_1_2 -v       # single stage
pytest tests/test-stages.py -k "stage_1_" -v      # all Slice 1 stages
```

---

## Slice 1 — Bootstrap (no agents)

**Goal:** Config, bus, and conversation state work; no agent flow yet.

**Runnable checkpoint:** `PYTHONPATH=. python main.py` prints ready; `pytest -k stage_1_2 -v` and `pytest -k stage_1_3 -v` pass.

### Stage 1.1 — Config and minimal main

**Function:** `test_stage_1_1`

| Functionality | Assertion |
|---------------|-----------|
| load_config | `load_config()` returns object; reads env via os.getenv; defaults to empty strings where documented |
| main | `main()` calls load_config(); prints "OpenFund-AI ready (config loaded)" (or equivalent); exits 0 |

**Runnable:** `PYTHONPATH=. python main.py` — no pytest; CLI checkpoint only.

---

### Stage 1.2 — In-memory MessageBus

**Function:** `test_stage_1_2`

| Functionality | Assertion |
|---------------|-----------|
| register_agent | Registering name adds agent to known set; required before send/receive/broadcast |
| send | `send(msg)` delivers message to msg.receiver's queue |
| receive | `receive(agent_name)` returns message for that agent; blocks until available |
| receive timeout | `receive(agent_name, timeout=0.1)` returns None when no message |
| broadcast | After registering two agents, `broadcast(msg)` → both receive the message |
| broadcast scope | Unregistered agent name does not receive broadcast |

**Runnable:** `pytest tests/test-stages.py -k stage_1_2 -v`

---

### Stage 1.3 — ConversationManager

**Function:** `test_stage_1_3`

| Functionality | Assertion |
|---------------|-----------|
| ConversationState | Has id (UUID str), user_id, initial_query, messages, status, final_response, created_at, completion_event (B2) |
| create_conversation | Returns str (conversation_id); state has correct initial values; status="active", final_response=None |
| get_conversation | Returns same state by conversation_id; returns None for unknown id |
| register_reply | Appends message to state.messages; when final response: sets final_response, status="complete", completion_event.set() |
| persistence | File written to memory/<user_id>/conversations.json on create and register_reply; valid JSON; dir auto-created (D2) |
| MEMORY_STORE_PATH | Root dir configurable via MEMORY_STORE_PATH env var, default memory/ (D2) |
| anonymous | user_id="" → memory/anonymous/conversations.json |
| broadcast_stop | Builds STOP ACLMessage (performative StrEnum per B1); calls message_bus.broadcast with that message |

**Runnable:** `pytest tests/test-stages.py -k stage_1_3 -v`

---

### Slice 1 — Verification (implementation, runnable, goal)

| Check | How to verify |
|-------|----------------|
| **Implementation** | All stage 1.1, 1.2, 1.3 tests pass; config, bus, ConversationManager have all specified behaviors |
| **Runnable** | `python main.py` exits 0 with ready message; `pytest -k stage_1_2 -v` and `pytest -k stage_1_3 -v` pass |
| **Goal** | No agent flow; config loads, bus can send/receive/broadcast, conversations can be created and completed (register_reply sets final_response and completion_event) |

---

## Slice 2 — MCP plumbing + one tool

**Goal:** Any agent can call one MCP tool; no Milvus/Neo4j/APIs needed.

**Runnable checkpoint:** `pytest -k stage_2_1 -v` passes; `client.call_tool("file_tool.read_file", {"path": "CHANGELOG.md"})` returns content.

### Stage 2.1 — MCP server and client

**Function:** `test_stage_2_1`

| Functionality | Assertion |
|---------------|-----------|
| register_tool | Server stores handler by name; dispatch invokes it with payload |
| dispatch | Returns result dict from handler; does not raise |
| call_tool | MCPClient.call_tool(tool_name, payload) calls server.dispatch; returns dict |
| file_tool.read_file | call_tool("file_tool.read_file", {"path": "CHANGELOG.md"}) returns dict with "content" and "path" |
| unknown tool | dispatch("nonexistent.tool", {}) returns error dict (no exception) |
| handler exception | Handler that raises → dispatch returns error dict |
| namespaced name | Tool registered as "file_tool.read_file" (F1) |

**Runnable:** `pytest tests/test-stages.py -k stage_2_1 -v`

---

### Slice 2 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | test_stage_2_1 passes; register_tool, dispatch, call_tool, read_file, namespaced convention |
| **Runnable** | `pytest -k stage_2_1 -v` passes; manual call_tool("file_tool.read_file", {"path": "CHANGELOG.md"}) returns content |
| **Goal** | One MCP tool callable without external services |

---

## Slice 3 — Minimal chain (Planner, Librarian, Responder)

**Goal:** Smallest runnable agent pipeline with real MCP.

**Runnable checkpoint:** `PYTHONPATH=. python main.py --e2e-once` runs one full conversation; exits 0; prints response.

### Stage 3.1 — PlannerAgent (Slice 3 subset)

**Function:** `test_stage_3_1`

| Functionality | Assertion |
|---------------|-----------|
| ACLMessage | performative, sender, receiver, content, conversation_id, timestamp; performatives StrEnum (B1): REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL; conversation_id/timestamp default in __post_init__ |
| TaskStep | Dataclass with agent, action, params (B3); agent in {"librarian","websearcher","analyst"} |
| decompose_task (stub) | Returns list of TaskStep; Slice 3 subset: one step with agent="librarian" |
| create_research_request | Returns ACLMessage performative=REQUEST; receiver=step.agent; content has query, step, conversation_id, user_profile |
| handle_message REQUEST | On REQUEST from caller: decompose_task → send one REQUEST to librarian (Slice 3) |
| on one INFORM | After one INFORM from librarian: compute_sufficiency (stub 1.0) → send REQUEST to Responder with conversation_id, user_profile, analysis |
| STOP | On STOP performative, Planner does not block; run() loop exits |
| PLANNER_SUFFICIENCY_THRESHOLD | Env var (default 0.6) used in threshold check |

**Runnable:** `pytest tests/test-stages.py -k stage_3_1 -v`

---

### Stage 3.2 — LibrarianAgent (Slice 3 subset)

**Function:** `test_stage_3_2`

| Functionality | Assertion |
|---------------|-----------|
| handle_message | Parses request; extracts query/conversation_id |
| file_tool only (Slice 3) | Calls mcp_client.call_tool("file_tool.read_file", {"path": ...}) |
| combine_results | Merges single-doc result into one structure |
| INFORM to planner | Sends INFORM with receiver=planner; content has combined result |
| STOP | On STOP, run() loop exits |

**Runnable:** `pytest tests/test-stages.py -k stage_3_2 -v`

---

### Stage 3.3 — ResponderAgent (Slice 3 subset)

**Function:** `test_stage_3_3`

| Functionality | Assertion |
|---------------|-----------|
| handle_message | Reads conversation_id, user_profile, analysis from message content (D3: conversation_id from ACLMessage) |
| evaluate_confidence | Takes analysis dict only; stub returns 0.8 |
| should_terminate | Returns True when confidence ≥ RESPONDER_CONFIDENCE_THRESHOLD (default 0.75); stub 0.8 → True |
| Slice 3 stub format | format_response produces string (e.g. str(analysis)); stub compliance always pass |
| register_reply | Calls conversation_manager.register_reply(conversation_id, INFORM with final_response); state.final_response set; completion_event.set() |
| broadcast_stop | Calls conversation_manager.broadcast_stop(conversation_id) after register_reply |
| No INFORM to Planner | Does not send final response INFORM to Planner; only register_reply + broadcast STOP (C2) |
| STOP | On STOP, run() loop exits |

**Runnable:** `pytest tests/test-stages.py -k stage_3_3 -v`

---

### Slice 3 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | test_stage_3_1, test_stage_3_2, test_stage_3_3 pass; ACLMessage/BaseAgent used; Planner 1 step → Librarian → Responder; register_reply + broadcast_stop |
| **Runnable** | `python main.py --e2e-once` completes; exits 0; prints state.final_response; no SafetyGateway yet; on timeout, --e2e-once exits 0 (non-fatal per D4) |
| **Goal** | One full conversation: Planner → Librarian (file_tool) → Responder → register_reply + broadcast_stop; smallest runnable pipeline with MCP |

---

## Slice 4 — Tools (vector, kg, sql) + full Librarian

**Goal:** Librarian uses all three tool types; no real Milvus/Neo4j/DB.

**Runnable checkpoint:** E2E still works; Librarian returns combined vector + graph + sql (mocked). `pytest -k stage_4_1 -k stage_4_2 -k stage_4_3 -v` pass.

### Stage 4.1 — vector_tool (Milvus)

**Function:** `test_stage_4_1`

| Functionality | Assertion |
|---------------|-----------|
| config | MILVUS_URI, MILVUS_COLLECTION; EMBEDDING_MODEL, EMBEDDING_DIM (default 384) |
| search | search(query, top_k, filter?) returns list of docs with scores; mock/stub: zero-vector, no real Milvus |
| register | "vector_tool.search" registered (F1) |

**Runnable:** `pytest tests/test-stages.py -k stage_4_1 -v`

---

### Stage 4.2 — kg_tool (Neo4j)

**Function:** `test_stage_4_2`

| Functionality | Assertion |
|---------------|-----------|
| query_graph | query_graph(cypher, params?) returns dict (nodes/edges); mock Neo4j; no network |
| get_relations | get_relations(entity) returns relation dict if implemented |
| register | "kg_tool.query_graph", "kg_tool.get_relations" (F1) |

**Runnable:** `pytest tests/test-stages.py -k stage_4_2 -v`

---

### Stage 4.3 — sql_tool (PostgreSQL)

**Function:** `test_stage_4_3`

| Functionality | Assertion |
|---------------|-----------|
| run_query | run_query(query, params?) returns dict with rows (list of dicts); mock connection |
| DATABASE_URL | Config reads DATABASE_URL |
| register | "sql_tool.run_query" (F1) |

**Runnable:** `pytest tests/test-stages.py -k stage_4_3 -v`

---

### Slice 4 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | test_stage_4_1, 4_2, 4_3 pass; Librarian handle_message calls vector_tool.search, kg_tool.query_graph, sql_tool.run_query; combine_results → INFORM to planner |
| **Runnable** | `python main.py --e2e-once` still completes; Librarian returns combined result from three tools (mocked); pytest for 4.1–4.3 pass |
| **Goal** | Librarian uses all three MCP tools; no real backends required |

---

## Slice 5 — WebSearcher, Analyst; full Planner

**Goal:** Full hub-and-spoke with all three specialists; one round.

**Runnable checkpoint:** `python main.py --e2e-once` runs one round: Planner → Librarian, WebSearcher, Analyst → Planner → Responder → register_reply + broadcast_stop.

### Stage 5.1 — market_tool

**Function:** `test_stage_5_1`

| Functionality | Assertion |
|---------------|-----------|
| fetch | fetch(fund_or_symbol) returns dict with "timestamp"; mock HTTP |
| fetch_bulk / search_web | If implemented, returns include timestamp per result |
| register | market_tool.* namespaced (F1) |

**Runnable:** `pytest tests/test-stages.py -k stage_5_1 -v`

---

### Stage 5.2 — analyst_tool

**Function:** `test_stage_5_2`

| Functionality | Assertion |
|---------------|-----------|
| run_analysis | POST to ANALYST_API_URL; payload dict; stub response: sharpe, max_drawdown, distribution |
| ANALYST_API_KEY | When set, auth header present; mock HTTP |
| register | "analyst_tool.run_analysis" (F1) |

**Runnable:** `pytest tests/test-stages.py -k stage_5_2 -v`

---

### Stage 5.3 — WebSearcherAgent

**Function:** `test_stage_5_3`

| Functionality | Assertion |
|---------------|-----------|
| handle_message | Calls fetch_market_data (market_tool.fetch); optionally fetch_sentiment, fetch_regulatory |
| INFORM to planner | receiver=planner; content includes timestamp |
| STOP | On STOP, run() exits |

**Runnable:** `pytest tests/test-stages.py -k stage_5_3 -v`

---

### Stage 5.4 — AnalystAgent

**Function:** `test_stage_5_4`

| Functionality | Assertion |
|---------------|-----------|
| handle_message | Receives structured_data, market_data; calls analyze(); calls needs_more_data(result) |
| analyze | Returns dict (e.g. confidence, distributions); may call analyst_tool.run_analysis |
| needs_more_data True | Sends REQUEST (refinement) to Planner |
| needs_more_data False | Sends INFORM (result) to Planner only (not to Responder) |
| ANALYST_CONFIDENCE_THRESHOLD | Env (default 0.6) used for needs_more_data |
| STOP | On STOP, run() exits |

**Runnable:** `pytest tests/test-stages.py -k stage_5_4 -v`

---

### Slice 5 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | test_stage_5_1 through 5_4 pass; Planner full stub: decompose_task returns three TaskSteps; sends three REQUESTs in parallel; collects three INFORMs; compute_sufficiency 1.0 → REQUEST to Responder; main registers and starts five agents |
| **Runnable** | `python main.py --e2e-once` completes one round with all five agents; register_reply + broadcast_stop |
| **Goal** | Full hub-and-spoke; one round; stub sufficiency 1.0 |

---

## Slice 6 — Safety

**Goal:** All user input passes through Safety before the bus; ready for REST.

**Runnable checkpoint:** E2E with valid query works; blocked phrase raises SafetyError or exits with error.

### Stage 6.1 — SafetyGateway

**Function:** `test_stage_6_1`

| Functionality | Assertion |
|---------------|-----------|
| validate_input | Valid query → ValidationResult passed=True; length/charset checks |
| check_guardrails | Block list (e.g. "buy now", "sell immediately") → GuardrailResult allowed=False |
| mask_pii | Phone/ID patterns replaced with placeholder |
| process_user_input | validate → guardrails → mask_pii; success → ProcessedInput; failure → raises SafetyError(reason, code) |
| SafetyError | Has reason and code attributes; FastAPI maps to HTTP 400 |

**Runnable:** `pytest tests/test-stages.py -k stage_6_1 -v`

---

### Slice 6 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | test_stage_6_1 pass; main (--e2e-once) calls process_user_input before create_conversation; SafetyError handled |
| **Runnable** | E2E valid query succeeds; E2E with blocked phrase raises SafetyError or exits non-zero |
| **Goal** | All input passes through Safety before bus; ready to plug into REST |

---

## Slice 7 — REST API

**Goal:** Full request-to-response over HTTP with safety.

**Runnable checkpoint:** `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"..."}'` returns 200 with conversation_id and response; blocked input → 400; unknown conversation_id → 404.

### Stage 7.1 — REST API

**Function:** `test_stage_7_1` (optional TestClient smoke)

| Functionality | Assertion |
|---------------|-----------|
| create_app | create_app(bus, manager, safety, mcp_client) returns FastAPI app; handlers close over deps |
| POST /chat body | Accepts query (required), conversation_id?, user_id? (optional, default "" per G2), user_profile?; user_profile one of beginner|long_term|analyst (E2); unknown user_profile → 400 |
| POST /chat flow | process_user_input → create or get conversation → send REQUEST to planner → block on completion_event.wait(timeout) |
| POST /chat 200 | On completion: 200 JSON with conversation_id, status, response (final_response) |
| POST /chat 408 | On timeout: 408 with status "timeout", conversation_id, response null |
| POST /chat 400 | SafetyError → 400 |
| GET /conversations/{id} | Returns conversation state JSON; 404 when not found |
| E2E_TIMEOUT_SECONDS | Env (default 30) used for wait |

**Runnable:** curl POST /chat; GET /conversations/{id}; optional `pytest -k stage_7_1 -v` with TestClient

---

### Slice 7 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | create_app, POST /chat, GET /conversations; SafetyError → 400; timeout → 408; 404 for unknown id |
| **Runnable** | Server running; curl POST /chat returns 200 JSON; blocked input 400; GET 404 for bad id |
| **Goal** | Full HTTP request-to-response with safety |

---

## Slice 8 — OutputRail

**Goal:** Responses are profile-aware and compliance-checked.

**Runnable checkpoint:** POST /chat with user_profile "beginner" vs "analyst" returns differently formatted text.

### Stage 8.1 — OutputRail

**Function:** `test_stage_8_1`

| Functionality | Assertion |
|---------------|-----------|
| UserProfile | StrEnum: BEGINNER, LONG_TERM, ANALYST; normalized lowercase; unknown → HTTP 400 in API |
| check_compliance | check_compliance(text) returns ComplianceResult; keyword check (e.g. no isolated buy/sell); pass/fail and reason |
| format_for_user | format_for_user(text, user_profile) returns str; output differs by profile: beginner (conclusion-first, analogies, risk), long_term (drawdown, horizon), analyst (full metrics, confidence intervals) per use-case-flows |
| Responder integration | Responder uses format_for_user and check_compliance before register_reply (no stub) |

**Runnable:** `pytest tests/test-stages.py -k stage_8_1 -v`; POST /chat with different user_profile

---

### Slice 8 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | test_stage_8_1 pass; Responder injects OutputRail; format_for_user and check_compliance used |
| **Runnable** | POST /chat with user_profile beginner vs analyst returns distinct response text |
| **Goal** | Profile-aware and compliance-checked responses |

---

## Slice 9 — WebSocket

**Goal:** Full API surface (GET + WebSocket).

**Runnable checkpoint:** GET /conversations/{id} returns state; WebSocket client receives status events then response event.

### Stage 9.1 — WebSocket

**Function:** `test_stage_9_1` (optional TestClient/async)

| Functionality | Assertion |
|---------------|-----------|
| /ws | Accepts connection; receives JSON { query, conversation_id?, user_id?, user_profile? } |
| flow | Same as POST /chat: process_user_input, create/get, send to Planner, wait |
| status events | Sends {"event": "status", "agent": "<name>", "message": "working"} per agent as it starts (I1) |
| response event | Sends {"event": "response", "conversation_id": "...", "response": "..."} once when Responder completes |

**Runnable:** WebSocket client; GET /conversations/{id}

---

### Slice 9 — Verification

| Check | How to verify |
|-------|----------------|
| **Implementation** | /ws implements same flow as POST /chat; status events and response event per I1 |
| **Runnable** | GET returns state; WebSocket client gets status events then response event |
| **Goal** | Full API surface |

---

## E2E and optional

### Stage 10.1 — E2E loop (full main)

**Runnable only:** No dedicated test function. Main grows each slice; `python main.py --e2e-once` is the checkpoint (first valid after Slice 3).

| Check | How to verify |
|-------|----------------|
| **Runnable** | `PYTHONPATH=. python main.py --e2e-once` completes; exits 0; prints final response; after Slice 6 includes process_user_input; after Slice 7 can use HTTP instead |

---

### Stage 10.2 — LLM (Phase 2, optional)

**Manual / integration:** Replace stub decompose_task and compute_sufficiency with LLM; POST /chat with natural language query; response reflects LLM-driven steps (H2).

---

## Coverage vs /docs

The following maps items from [clarification.md](clarification.md), [use-case-flows.md](use-case-flows.md), and [staged_implementation_plan.md](staged_implementation_plan.md) to where they are verified in this test plan.

| Doc / ID | Topic | Where verified |
|----------|--------|----------------|
| A2 | Test file layout: single test-stages.py, one function per stage | Intro; summary table |
| B1 | ACLMessage performative StrEnum; REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL | Stage 1.3 (broadcast_stop STOP); Stage 3.1 (ACLMessage, REQUEST/INFORM); Stage 3.2, 3.3 (INFORM, STOP) |
| B2 | ConversationState fields (id, user_id, initial_query, messages, status, final_response, created_at, completion_event) | Stage 1.3 |
| B3 | TaskStep agent / action / params | Stage 3.1 |
| C1 | register_agent in main; broadcast to registered only | Stage 1.2; Slice 3 Verification (main register_agent) |
| C2 | Hub-and-spoke; Responder → user via register_reply; broadcast STOP only; no INFORM to Planner | Stage 3.3 (No INFORM to Planner, register_reply, broadcast_stop) |
| C3 | Planner one-or-more per round; stub all three; sufficiency 1.0; PLANNER_SUFFICIENCY_THRESHOLD | Stage 3.1 (Slice 3 subset); Stage 5 Verification (full stub) |
| C4 | BaseAgent.run() loop; receive timeout=1.0; STOP breaks; handle_message never sees STOP | Stage 3.1, 3.2, 3.3 (STOP exits) |
| C5 | completion_event; register_reply sets it; wait(timeout) no busy-poll | Stage 1.3; Stage 7.1 |
| D1 | create_or_get inline in REST (no separate method) | Stage 7.1 (create or get conversation) |
| D2 | Persistence JSON; memory/<user_id>/conversations.json; MEMORY_STORE_PATH; anonymous; makedirs | Stage 1.3 |
| D3 | Responder conversation_id from message | Stage 3.3 |
| D4 | E2E 30s; --e2e-once timeout exit 0; POST /chat timeout HTTP 408 | Stage 7.1 (408, E2E_TIMEOUT_SECONDS); Slice 3 Verification (exit 0 on timeout) |
| E1 | SafetyError(reason, code); HTTP 400 | Stage 6.1; Stage 7.1 |
| E2 | user_profile beginner | long_term | analyst; lowercase; unknown → 400 | Stage 8.1; Stage 7.1 |
| F1 | MCP namespaced tool names | Stage 2.1, 4.1, 4.2, 4.3, 5.1, 5.2 |
| F2 | MILVUS_URI, MILVUS_COLLECTION | Stage 4.1 |
| F3 | Embedding model, EMBEDDING_DIM, zero-vector stub | Stage 4.1 |
| F4 | Analyst API stub schema | Stage 5.2 |
| F5 | sql_tool, DATABASE_URL, Librarian calls it | Stage 4.3; Slice 4 Verification |
| G1 | create_app(bus, manager, ...) constructor injection | Stage 7.1 |
| G2 | user_id optional, default "" | Stage 7.1 |
| H1 | ANALYST_CONFIDENCE_THRESHOLD 0.6; RESPONDER 0.75; evaluate_confidence dict only 0.8 | Stage 3.3; Stage 5.4 |
| I1 | WebSocket event stream: status per agent, response when complete | Stage 9.1 |
| use-case-flows | Steps 1–11; body validation; create/get; send to Planner; block; format_for_user by profile; register_reply; broadcast_stop | Stage 7.1 (REST flow); Stage 8.1 (format_by_profile); Stage 3.3 (register_reply, broadcast_stop) |
| use-case-flows | New round: insufficient → new queries from all info → REQUEST again | Optional; Planner design (Stage 3.1/5); no dedicated test in stub |

**Optional / not automated:** Multi-round Planner (new queries from current info); Stage 10.2 LLM; LangGraph (H2 deferred).

---

## Summary: stage test functions and runnable commands

| Stage | Test function | Runnable command |
|-------|---------------|------------------|
| 1.1 | — | `PYTHONPATH=. python main.py` |
| 1.2 | `test_stage_1_2` | `pytest tests/test-stages.py -k stage_1_2 -v` |
| 1.3 | `test_stage_1_3` | `pytest tests/test-stages.py -k stage_1_3 -v` |
| 2.1 | `test_stage_2_1` | `pytest tests/test-stages.py -k stage_2_1 -v` |
| 3.1 | `test_stage_3_1` | `pytest tests/test-stages.py -k stage_3_1 -v` |
| 3.2 | `test_stage_3_2` | `pytest tests/test-stages.py -k stage_3_2 -v` |
| 3.3 | `test_stage_3_3` | `pytest tests/test-stages.py -k stage_3_3 -v` |
| 4.1 | `test_stage_4_1` | `pytest tests/test-stages.py -k stage_4_1 -v` |
| 4.2 | `test_stage_4_2` | `pytest tests/test-stages.py -k stage_4_2 -v` |
| 4.3 | `test_stage_4_3` | `pytest tests/test-stages.py -k stage_4_3 -v` |
| 5.1 | `test_stage_5_1` | `pytest tests/test-stages.py -k stage_5_1 -v` |
| 5.2 | `test_stage_5_2` | `pytest tests/test-stages.py -k stage_5_2 -v` |
| 5.3 | `test_stage_5_3` | `pytest tests/test-stages.py -k stage_5_3 -v` |
| 5.4 | `test_stage_5_4` | `pytest tests/test-stages.py -k stage_5_4 -v` |
| 6.1 | `test_stage_6_1` | `pytest tests/test-stages.py -k stage_6_1 -v` |
| 7.1 | `test_stage_7_1` (optional) | curl POST /chat; GET /conversations/{id} |
| 8.1 | `test_stage_8_1` | `pytest tests/test-stages.py -k stage_8_1 -v` |
| 9.1 | `test_stage_9_1` (optional) | WebSocket client; GET |
| 10.1 | — | `python main.py --e2e-once` |
| 10.2 | — | POST /chat with NL query (manual) |
