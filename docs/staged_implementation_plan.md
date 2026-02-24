# OpenFund-AI: Staged Implementation (Runnable Checkpoints)

This plan aligns with [clarification.md](clarification.md), [claude-v2.md](claude-v2.md), and [use-case-flows.md](use-case-flows.md). Development proceeds in **slices**: each slice is a **runnable unit** you can implement and verify before moving on. Start with the smallest runnable pipeline (Planner + Librarian + Responder + MCP), then add tools, other agents, Safety, and REST. External services (Milvus, Neo4j, Tavily, Yahoo, Analyst API) can be mocked so every slice is runnable without full infra.

---

## Development order (slices)

| Slice | What you add | Runnable checkpoint |
|-------|----------------|---------------------|
| 1 | Config, MessageBus, ConversationManager (1.1, 1.2, 1.3) | `main.py` runs; stage_1_2 and stage_1_3 tests pass |
| 2 | MCP server/client, file_tool only (2.1) | stage_2_1 tests pass; `call_tool("file_tool.read_file", ...)` works |
| 3 | ACLMessage, BaseAgent, Planner (1 step), Librarian (file_tool), Responder (stub format) | `python main.py --e2e-once` completes one conversation |
| 4 | vector_tool, kg_tool, sql_tool (mocks); full Librarian | E2E with Librarian using three tools |
| 5 | WebSearcher, Analyst; Planner sends to all three | E2E with five agents, one round |
| 6 | SafetyGateway | E2E with `process_user_input`; bad input rejected |
| 7 | REST: create_app, POST /chat, GET /conversations | `curl` POST /chat returns 200 JSON |
| 8 | OutputRail in Responder | Response text varies by user_profile |
| 9 | WebSocket /ws | GET and WebSocket work |
| Optional | New rounds (Planner); Stage 10.2 LLM | Multi-round or LLM-driven flow |

---

## Prerequisite: ACLMessage and BaseAgent

Before any agents run (Slice 3), implement:

- **a2a/acl_message.py**: `ACLMessage` dataclass — performative, sender, receiver, content, conversation_id, timestamp (B1). Default conversation_id (UUID) and timestamp in `__post_init__`.
- **agents/base_agent.py**: `BaseAgent` — `run()` loop: `receive(self.name, timeout=1.0)`; if message is STOP, break; else `handle_message(msg)` (C4). Subclasses implement `handle_message`.

---

## Slice 1 — Bootstrap (no agents)

**Implement:** Stages 1.1, 1.2, 1.3 (see [Reference: Stage specifications](#reference-stage-specifications) below).

- **Stage 1.1:** [config/config.py](../config/config.py) `load_config()`, [main.py](../main.py) `main()` — load env, print ready, exit 0.
- **Stage 1.2:** [a2a/message_bus.py](../a2a/message_bus.py) — `InMemoryMessageBus` with `register_agent`, `send`, `receive`, `broadcast` (C1).
- **Stage 1.3:** [a2a/conversation_manager.py](../a2a/conversation_manager.py) — `ConversationState` (B2), `create_conversation` → conversation_id, `get_conversation`, `register_reply`, `broadcast_stop`; persistence (D2).

**Runnable:** `PYTHONPATH=. python main.py` prints ready; `pytest tests/test-stages.py -k stage_1_2 -v` and `-k stage_1_3 -v` pass.

**Goal:** Config, bus, and conversation state work; no agent flow yet.

---

## Slice 2 — MCP plumbing + one tool

**Implement:** Stage 2.1 — MCP server, MCP client, [mcp/tools/file_tool.py](../mcp/tools/file_tool.py) `read_file`. Register only `"file_tool.read_file"` (F1).

**Runnable:** `pytest tests/test-stages.py -k stage_2_1 -v` passes; `client.call_tool("file_tool.read_file", {"path": "CHANGELOG.md"})` returns content.

**Goal:** Any agent can call one MCP tool; no Milvus/Neo4j/APIs needed.

---

## Slice 3 — Minimal chain: Planner + Librarian + Responder

**Implement:**

- **ACLMessage** and **BaseAgent** (prerequisite above).
- **PlannerAgent (reduced):** On REQUEST from caller, `decompose_task` stub returns **one** `TaskStep`: `agent="librarian"`. Send one REQUEST to librarian; on **one** INFORM from librarian, `compute_sufficiency` (stub 1.0) → send REQUEST to Responder with `{ conversation_id, user_profile, analysis: <librarian result> }`. No WebSearcher/Analyst.
- **LibrarianAgent:** `handle_message` → parse query/conversation_id → `mcp_client.call_tool("file_tool.read_file", {"path": ...})` (path from query or fixed file) → `combine_results` (single doc) → send INFORM to **planner**.
- **ResponderAgent:** `handle_message` → read conversation_id, user_profile, analysis → `evaluate_confidence` (stub 0.8) → `should_terminate` (True) → **stub** format (e.g. `final_text = str(analysis)`) and **stub** compliance (always pass) → `register_reply(conversation_id, INFORM with final_response)` → `broadcast_stop`. No real OutputRail yet.
- **main():** Create bus; `register_agent("planner")`, `register_agent("librarian")`, `register_agent("responder")`; ConversationManager; MCP server (file_tool only); instantiate Planner, Librarian, Responder (bus + mcp_client); start three daemon threads. **No SafetyGateway.** `--e2e-once`: create conversation, send REQUEST to planner with `{ query, conversation_id, user_profile }`, block on `state.completion_event.wait(timeout=30)`, print `state.final_response`.

**Runnable:** `PYTHONPATH=. python main.py --e2e-once` runs one full conversation end-to-end; exits 0 and prints a response.

**Goal:** Smallest runnable agent pipeline with real MCP.

---

## Slice 4 — Remaining MCP tools (mocks) + full Librarian

**Implement:** Stages 4.1, 4.2, 4.3 — vector_tool, kg_tool, sql_tool (stubs/mocks). Register all on MCP server. **LibrarianAgent** full behavior: `vector_tool.search`, `kg_tool.query_graph`, `sql_tool.run_query` → `combine_results` → INFORM to planner. Planner stub can still send only to Librarian for this slice.

**Runnable:** E2E still works; Librarian returns combined vector + graph + sql (mocked). `pytest -k stage_4_1 -k stage_4_2 -k stage_4_3` pass.

**Goal:** Librarian uses all three tool types; no real Milvus/Neo4j/DB.

---

## Slice 5 — WebSearcher and Analyst; Planner sends to all three

**Implement:** Stages 5.1, 5.2 (market_tool, analyst_tool — mocks); Stages 5.3, 5.4 (WebSearcherAgent, AnalystAgent). **PlannerAgent** full stub: `decompose_task` returns **three** TaskSteps; send three REQUESTs in parallel; collect three INFORMs; `compute_sufficiency` (1.0) → send REQUEST to Responder with consolidated payload. In main: register and start five agents.

**Runnable:** `python main.py --e2e-once` runs one round: Planner → Librarian, WebSearcher, Analyst → Planner → Responder → register_reply + broadcast_stop.

**Goal:** Full hub-and-spoke with all three specialists.

---

## Slice 6 — Safety

**Implement:** Stage 6.1 (SafetyGateway). In `main` for `--e2e-once`, call `SafetyGateway.process_user_input(query)` before `create_conversation`; on `SafetyError` exit non-zero or skip send. No REST yet.

**Runnable:** E2E with valid query works; blocked phrase raises SafetyError or exits with error.

**Goal:** All user input passes through Safety before the bus; ready for REST.

---

## Slice 7 — REST API (POST /chat, GET /conversations)

**Implement:** Stage 7.1 — `create_app(bus, manager, safety, mcp_client)`; POST /chat (validate body → process_user_input → create/get conversation → send to Planner → block on completion_event → return JSON); GET /conversations/{id} (404 if not found); SafetyError → HTTP 400; timeout → 408. Mount app in main; uvicorn.

**Runnable:** `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"..."}'` returns 200 with conversation_id and response; blocked input → 400; unknown conversation_id → 404.

**Goal:** Full request-to-response over HTTP with safety.

---

## Slice 8 — OutputRail (real formatting and compliance)

**Implement:** Stage 8.1 (OutputRail). Inject into Responder; replace stub format/compliance with `format_for_user(..., user_profile)` and `check_compliance(final_text)` before register_reply.

**Runnable:** POST /chat with `user_profile: "beginner"` vs `"analyst"` returns differently formatted text.

**Goal:** Responses are profile-aware and compliance-checked.

---

## Slice 9 — WebSocket

**Implement:** Stage 9.1 — WebSocket /ws: same flow as POST /chat; send status events per agent and final response event (I1).

**Runnable:** GET /conversations/{id} returns state; WebSocket client receives status events then response event.

**Goal:** Full API surface.

---

## Optional: New rounds and LLM

- **Planner new rounds:** When `compute_sufficiency` < threshold, generate new queries from all current info and send REQUESTs again to one or more agents (use-case-flows). Add when you want multi-round behavior.
- **Stage 10.2 (LLM):** Replace stub `decompose_task` and `compute_sufficiency` with LLM; keep message flow unchanged.

---

## Summary diagram (slice order)

```mermaid
flowchart LR
  S1[Slice_1_Bootstrap]
  S2[Slice_2_MCP]
  S3[Slice_3_Minimal_Chain]
  S4[Slice_4_Tools_Librarian]
  S5[Slice_5_All_Agents]
  S6[Slice_6_Safety]
  S7[Slice_7_REST]
  S8[Slice_8_OutputRail]
  S9[Slice_9_WS]
  S1 --> S2 --> S3
  S3 --> S4 --> S5
  S5 --> S6 --> S7
  S7 --> S8 --> S9
```

---

## Reference: Stage specifications

Stages are ordered by the **slice in which they first appear** and numbered as **slice.sub** (e.g. 2.1). Each stage is a subset of the work done in that slice. Implement the subset required by the slice you are on; tests use `-k stage_N_M` (e.g. `stage_1_2`) for the corresponding stage.

### Slice 1 — Bootstrap

#### Stage 1.1 — Config and minimal main

- **Scope:** [config/config.py](../config/config.py), [main.py](../main.py).
- `load_config()`: read env via `os.getenv`, default empty strings.
- `main()`: call `load_config()`, print `"OpenFund-AI ready (config loaded)"`, exit 0.
- **Runnable:** `PYTHONPATH=. python main.py`.

#### Stage 1.2 — In-memory MessageBus

- **Scope:** [a2a/message_bus.py](../a2a/message_bus.py). Per C1.
- `register_agent(name)`, per-agent queues; `send`, `receive(agent_name, timeout?)`, `broadcast`.
- **Runnable:** `pytest tests/test-stages.py -k stage_1_2 -v`.

#### Stage 1.3 — ConversationManager

- **Scope:** [a2a/conversation_manager.py](../a2a/conversation_manager.py). Per B2, D2.
- `ConversationState`: id, user_id, initial_query, messages, status, final_response, created_at, completion_event.
- `create_conversation(user_id, initial_query) -> str`; `get_conversation(conversation_id)`; `register_reply`; `broadcast_stop`; persist to `memory/<user_id>/conversations.json`.
- **Runnable:** `pytest tests/test-stages.py -k stage_1_3 -v`.

---

### Slice 2 — MCP + one tool

#### Stage 2.1 — MCP server and client

- **Scope:** [mcp/mcp_server.py](../mcp/mcp_server.py), [mcp/mcp_client.py](../mcp/mcp_client.py), [mcp/tools/file_tool.py](../mcp/tools/file_tool.py). Per F1.
- `register_tool`, `dispatch`; MCPClient `call_tool`; `read_file` → `{"content", "path"}`; register `"file_tool.read_file"`.
- **Runnable:** `pytest tests/test-stages.py -k stage_2_1 -v`.

---

### Slice 3 — Minimal chain (Planner, Librarian, Responder)

In Slice 3 you implement a **subset** of each agent (one TaskStep, file_tool only, stub format/compliance). Full behavior is in later slices.

#### Stage 3.1 — PlannerAgent

- **Scope:** [agents/planner_agent.py](../agents/planner_agent.py). Per C2, C3, use-case-flows.
- **Slice 3 subset:** stub returns one TaskStep (librarian); one REQUEST, one INFORM, then REQUEST to Responder. **Full (Slice 5):** `decompose_task` → three TaskSteps; parallel REQUESTs; collect INFORMs; `compute_sufficiency`; new rounds when insufficient.
- TaskStep(agent, action, params). `create_research_request(query, step, context?)`. Stub sufficiency 1.0.
- **Runnable:** `pytest tests/test-stages.py -k stage_3_1 -v`.

#### Stage 3.2 — LibrarianAgent

- **Scope:** [agents/librarian_agent.py](../agents/librarian_agent.py).
- **Slice 3 subset:** `handle_message` → `file_tool.read_file` only → `combine_results` (single doc) → INFORM to planner. **Full (Slice 4):** vector_tool.search, kg_tool.query_graph, sql_tool.run_query → combine_results → INFORM to planner.
- **Runnable:** `pytest tests/test-stages.py -k stage_3_2 -v`.

#### Stage 3.3 — ResponderAgent

- **Scope:** [agents/responder_agent.py](../agents/responder_agent.py). Per C2.
- **Slice 3 subset:** stub `format_response` and stub compliance; register_reply; broadcast_stop. **Full (Slice 8):** OutputRail `format_for_user`, `check_compliance` before register_reply.
- evaluate_confidence (stub 0.8); should_terminate; no INFORM to Planner with final response.
- **Runnable:** `pytest tests/test-stages.py -k stage_3_3 -v`.

---

### Slice 4 — Tools (vector, kg, sql) + full Librarian

#### Stage 4.1 — vector_tool (Milvus)

- **Scope:** [mcp/tools/vector_tool.py](../mcp/tools/vector_tool.py). Per F2, F3.
- MILVUS_URI, MILVUS_COLLECTION; `search(query, top_k, filter?)`; stub: zero-vector; register `"vector_tool.search"`.
- **Runnable:** `pytest tests/test-stages.py -k stage_4_1 -v` (mock).

#### Stage 4.2 — kg_tool (Neo4j)

- **Scope:** [mcp/tools/kg_tool.py](../mcp/tools/kg_tool.py). `query_graph`, `get_relations`; register `"kg_tool.query_graph"`, `"kg_tool.get_relations"`.
- **Runnable:** `pytest tests/test-stages.py -k stage_4_2 -v` (mock).

#### Stage 4.3 — sql_tool (PostgreSQL)

- **Scope:** [mcp/tools/sql_tool.py](../mcp/tools/sql_tool.py). Per F5. `run_query`; DATABASE_URL; register `"sql_tool.run_query"`.
- **Runnable:** `pytest tests/test-stages.py -k stage_4_3 -v` (mock).

---

### Slice 5 — WebSearcher, Analyst, full Planner

#### Stage 5.1 — market_tool

- **Scope:** [mcp/tools/market_tool.py](../mcp/tools/market_tool.py). `fetch`, `fetch_bulk`, `search_web`; all returns include `timestamp`. Register market_tool.*.
- **Runnable:** `pytest tests/test-stages.py -k stage_5_1 -v` (mock).

#### Stage 5.2 — analyst_tool

- **Scope:** [mcp/tools/analyst_tool.py](../mcp/tools/analyst_tool.py). Per F4. `run_analysis` POST to ANALYST_API_URL; stub schema.
- **Runnable:** `pytest tests/test-stages.py -k stage_5_2 -v` (mock).

#### Stage 5.3 — WebSearcherAgent

- **Scope:** [agents/websearch_agent.py](../agents/websearch_agent.py). market_tool; INFORM to planner with timestamp.
- **Runnable:** `pytest tests/test-stages.py -k stage_5_3 -v`.

#### Stage 5.4 — AnalystAgent

- **Scope:** [agents/analyst_agent.py](../agents/analyst_agent.py). analyze; needs_more_data → refinement REQUEST to Planner or INFORM (result) to Planner only.
- **Runnable:** `pytest tests/test-stages.py -k stage_5_4 -v`.

---

### Slice 6 — Safety

#### Stage 6.1 — SafetyGateway

- **Scope:** [safety/safety_gateway.py](../safety/safety_gateway.py). Per E1.
- `validate_input`, `check_guardrails`, `mask_pii`, `process_user_input` → ProcessedInput or raises SafetyError.
- **Runnable:** `pytest tests/test-stages.py -k stage_6_1 -v`.

---

### Slice 7 — REST API

#### Stage 7.1 — REST API

- **Scope:** [api/rest.py](../api/rest.py). create_app; POST /chat (body, safety, create/get, send to Planner, wait, 200/408); GET /conversations/{id} (404); SafetyError → 400.
- **Runnable:** curl POST /chat; GET /conversations/{id}.

---

### Slice 8 — OutputRail

#### Stage 8.1 — OutputRail

- **Scope:** [output/output_rail.py](../output/output_rail.py). Per E2.
- UserProfile StrEnum; `check_compliance(text)`; `format_for_user(text, user_profile)`.
- **Runnable:** `pytest tests/test-stages.py -k stage_8_1 -v`.

---

### Slice 9 — WebSocket

#### Stage 9.1 — WebSocket

- **Scope:** [api/websocket.py](../api/websocket.py). /ws; status events + response event (I1).
- **Runnable:** WebSocket client.

---

### E2E and optional

#### Stage 10.1 — E2E loop (full main)

- **Scope:** [main.py](../main.py). Grows each slice: register_agent for active agents; ConversationManager, (from Slice 6) SafetyGateway, MCP server (all registered tools), all agents; `--e2e-once` with process_user_input, create conversation, send to Planner, wait, print response.
- **Runnable:** `PYTHONPATH=. python main.py --e2e-once` (first valid after Slice 3).

#### Stage 10.2 — LLM (Phase 2, optional)

- **Scope:** Planner + LLM client. Replace stub decompose_task and compute_sufficiency; keep flow (H2).
- **Runnable:** POST /chat with NL query.

---

## Test layout

All tests in `tests/test-stages.py`. Per A2: one test function per stage (not a class). Run full suite: `pytest tests/test-stages.py -v`. By slice:

| Slice | Runnable command |
|-------|------------------|
| 1 | `python main.py`; `pytest -k stage_1_2 -v`; `pytest -k stage_1_3 -v` |
| 2 | `pytest -k stage_2_1 -v` |
| 3 | `python main.py --e2e-once` |
| 4 | `pytest -k stage_4_1 -k stage_4_2 -k stage_4_3 -v`; E2E |
| 5 | E2E with five agents |
| 6 | E2E with Safety; `pytest -k stage_6_1 -v` |
| 7 | `curl` POST /chat; GET /conversations/{id} |
| 8 | POST /chat with different user_profile |
| 9 | WebSocket client |

By stage (same order as slices; each stage is slice.sub):

| Stage | Slice | Filter | Command |
|-------|-------|--------|---------|
| 1.1 | 1 | — | `PYTHONPATH=. python main.py` |
| 1.2 | 1 | `stage_1_2` | `pytest tests/test-stages.py -k stage_1_2 -v` |
| 1.3 | 1 | `stage_1_3` | `pytest tests/test-stages.py -k stage_1_3 -v` |
| 2.1 | 2 | `stage_2_1` | `pytest tests/test-stages.py -k stage_2_1 -v` |
| 3.1 | 3 | `stage_3_1` | `pytest tests/test-stages.py -k stage_3_1 -v` |
| 3.2 | 3 | `stage_3_2` | `pytest tests/test-stages.py -k stage_3_2 -v` |
| 3.3 | 3 | `stage_3_3` | `pytest tests/test-stages.py -k stage_3_3 -v` |
| 4.1 | 4 | `stage_4_1` | `pytest tests/test-stages.py -k stage_4_1 -v` |
| 4.2 | 4 | `stage_4_2` | `pytest tests/test-stages.py -k stage_4_2 -v` |
| 4.3 | 4 | `stage_4_3` | `pytest tests/test-stages.py -k stage_4_3 -v` |
| 5.1 | 5 | `stage_5_1` | `pytest tests/test-stages.py -k stage_5_1 -v` |
| 5.2 | 5 | `stage_5_2` | `pytest tests/test-stages.py -k stage_5_2 -v` |
| 5.3 | 5 | `stage_5_3` | `pytest tests/test-stages.py -k stage_5_3 -v` |
| 5.4 | 5 | `stage_5_4` | `pytest tests/test-stages.py -k stage_5_4 -v` |
| 6.1 | 6 | `stage_6_1` | `pytest tests/test-stages.py -k stage_6_1 -v` |
| 7.1 | 7 | — | curl POST /chat; GET /conversations/{id} |
| 8.1 | 8 | `stage_8_1` | `pytest tests/test-stages.py -k stage_8_1 -v` |
| 9.1 | 9 | — | WebSocket client |
| 10.1 | E2E | — | `python main.py --e2e-once` |
| 10.2 | Optional | — | POST /chat with NL |

Add `pytest`, `pytest-asyncio`, `pytest-httpx` to `pyproject.toml` dev dependencies.
