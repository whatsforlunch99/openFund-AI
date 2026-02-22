# OpenFund-AI — Architecture Decisions

> Settled decisions are recorded as facts. Items still requiring clarification are at the bottom.

---

## Settled Decisions

---

### A1 · Python version and packaging

`pyproject.toml` and `CHANGELOG.md` already exist locally. No action needed in this document. Python version and build backend are defined in the local `pyproject.toml`.

---

### A2 · Test file layout

All tests live in a single file: `tests/test-stages.py`. Each stage's tests are implemented as a single test function (not a class). Run with `pytest tests/test-stages.py -v`. The `staged_implementation_plan.md` and `test_plan.md` runnable commands should be updated to match.

---

### B1 · ACLMessage performative type and set

Performatives are typed as a `StrEnum` (Python 3.11+). The complete set for current stages is:


| Performative | Used by                             |
| ------------ | ----------------------------------- |
| `REQUEST`    | Planner → specialist agents         |
| `INFORM`     | Agent replies carrying results      |
| `STOP`       | Responder → broadcast               |
| `FAILURE`    | Any agent on error                  |
| `ACK`        | Acknowledgement                     |
| `REFUSE`     | Agent declines a request            |
| `CANCEL`     | Caller cancels an in-flight request |


New performatives are added only when a stage explicitly requires them.

---

### B2 · ConversationState fields

```python
@dataclass
class ConversationState:
    id: str                            # UUID
    user_id: str                       # empty string if anonymous
    initial_query: str
    messages: list[dict]               # append-only log of ACLMessage dicts
    status: str                        # "active" | "complete" | "error"
    final_response: str | None         # set by register_reply when Responder delivers answer
    created_at: datetime
    completion_event: threading.Event  # unblocks pollers when final_response is set
```

---

### B3 · TaskStep structure

```python
@dataclass
class TaskStep:
    agent: str    # "librarian" | "websearcher" | "analyst"
    action: str   # e.g. "retrieve_fund_facts"
    params: dict  # forwarded as ACLMessage content extras
```

---

### C1 · MessageBus — agent registration for broadcast

`MessageBus` exposes `register_agent(name: str)`. `main()` calls it explicitly for each agent at startup, before any messages are sent. `broadcast` delivers to all registered names.

---

### C2 · Agent chain — message sequence

Hub-and-spoke: Planner is the sole orchestrator. All specialists reply only to Planner. Planner decides who to call next based on accumulated state.

```
REST/main  → Planner
Planner    → Librarian / WebSearcher / Analyst  (REQUEST, one or more rounds)
<agent>    → Planner                             (INFORM: result)
Planner    → Responder                           (REQUEST: consolidated data)
Responder  → Planner                             (INFORM: final_response)
Responder  → broadcast STOP
```

Planner accumulates replies and decides each next call dynamically — see C3 for stub behavior.

---

### C4 · BaseAgent.run() — loop and STOP handling

```python
def run(self):
    while True:
        msg = self.message_bus.receive(self.name, timeout=1.0)
        if msg is None:
            continue
        if msg.performative == Performative.STOP:
            break   # thread exits cleanly
        self.handle_message(msg)
```

`handle_message` never receives a STOP message.

---

### C5 · Final-response completion signal

`ConversationState` holds a `threading.Event`. `register_reply` sets it when `final_response` is written. Callers block with `event.wait(timeout=30)` — no busy-polling.

---

### D1 · ConversationManager — create_or_get

No new method is added. The REST handler calls `create_conversation` when no `conversation_id` is supplied, and `get_conversation` when one is. This logic lives inline in `api/rest.py`.

---

### D3 · Responder — source of conversation_id

Responder reads `message.conversation_id` from the incoming ACLMessage. No constructor injection is needed.

---

### D4 · Timeout values and failure behavior

- Timeout: **30 seconds**, configurable via `E2E_TIMEOUT_SECONDS` env var.
- `--e2e-once` on timeout: **exit 0** (timeout is treated as a non-fatal run for the stub stages).
- `POST /chat` on timeout: **HTTP 408** with body `{"status": "timeout", "conversation_id": "...", "response": null}`.

---

### E1 · SafetyGateway — error contract

`process_user_input(...) -> ProcessedInput` raises a custom `SafetyError(reason: str, code: str)` on validation or guardrail failure. FastAPI registers an exception handler that maps `SafetyError` to HTTP 400.

---

### E2 · user_profile values

Allowed values: `beginner`, `long_term`, `analyst` (exhaustive for now). Input is normalized to lowercase before comparison. Implemented as:

```python
class UserProfile(StrEnum):
    BEGINNER  = "beginner"
    LONG_TERM = "long_term"
    ANALYST   = "analyst"
```

Unknown values return HTTP 400.

---

### F1 · MCP tool name convention

All tool names are namespaced: `"file_tool.read_file"`, `"vector_tool.search"`, `"kg_tool.query_graph"`, `"market_tool.fetch"`, `"analyst_tool.run_analysis"`, `"sql_tool.run_query"`. Registration and `call_tool` calls must use the same namespaced key.

---

### F2 · Milvus config

Only `MILVUS_URI` is supported (e.g. `grpc://host:19530` or a Zilliz cloud URI). `MILVUS_HOST` / `MILVUS_PORT` are not supported.

---

### F3 · Embedding model for vector_tool

- Model: `sentence-transformers/all-MiniLM-L6-v2` (384 dims, no API key required).
- Config-driven: `EMBEDDING_MODEL` and `EMBEDDING_DIM` env vars; defaults are the model above and 384.
- Test stub: a zero-vector of length `EMBEDDING_DIM`.

---

### F4 · Analyst custom API schema (stub)

Until the real API spec is available, implement to this stub:

```jsonc
// POST request body
{ "returns": [0.02, -0.01, 0.03], "horizon": 252 }

// response
{ "sharpe": 1.4, "max_drawdown": -0.12, "distribution": { "mean": 0.08, "std": 0.15 } }
```

---

### F5 · sql_tool — stage and backing database

- **Stage:** 8b (between kg_tool and market_tool in the staged plan).
- **Database engine:** PostgreSQL.
- **Connection config:** `DATABASE_URL` env var.
- LibrarianAgent (Stage 12) calls `"sql_tool.run_query"` alongside the vector and graph tools.
- Tests mock the PostgreSQL connection so no real DB is needed to run the test suite.

---

### G1 · REST shared-state injection

`create_app(bus, manager, safety, ...)` receives all dependencies as constructor arguments. `main()` creates all objects and passes them in. Route handlers close over them. Tests call `create_app(mock_bus, ...)` directly.

---

### G2 · user_id in REST requests

`user_id` is an optional field in the `POST /chat` request body. It defaults to `""` (anonymous) if absent. Auth-header extraction is a later phase.

---

### H1 · Confidence thresholds

- `AnalystAgent.needs_more_data`: fires when confidence < **0.6** (default). Env var: `ANALYST_CONFIDENCE_THRESHOLD`.
- `ResponderAgent.should_terminate`: fires when confidence ≥ **0.75** (default). Env var: `RESPONDER_CONFIDENCE_THRESHOLD`.
- `evaluate_confidence(analysis: dict) -> float` — takes the analysis dict only; returns hardcoded **0.8** stub until LLM is added.

---

### H2 · LangGraph

Stage 19 is LLM-only: replace stub `decompose_task` with a real LLM call + ReAct prompt. LangGraph graph topology is deferred to Stage 20+.

---

### C3 · Planner stub behavior before LLM exists

The stub (pre-LLM) Planner always dispatches to all three specialists in parallel, collects all three INFORMs, then proceeds to Responder. Detailed behavior:

- `decompose_task(query)` always returns three `TaskStep` objects: one each for `librarian`, `websearcher`, and `analyst`.
- Planner sends all three `REQUEST` messages simultaneously (parallel dispatch, no waiting between sends).
- Planner tracks expected replies. Once all three `INFORM` replies are received, it computes a sufficiency score.
- **Stub sufficiency score:** always returns `1.0` once all dispatched agents have replied. The threshold check still exists in code so the LLM can replace the scoring function in Stage 19 without touching control flow.
- **Env var:** `PLANNER_SUFFICIENCY_THRESHOLD` (default `0.6`). Stub always scores `1.0` so it always passes.

---

### D2 · Conversation state persistence

Conversations are persisted as JSON, one file per user, written on every `create_conversation` and `register_reply` call.

- **Root dir:** configurable via `MEMORY_STORE_PATH` env var, defaulting to `memory/`.
- **File path per user:** `memory/<user_id>/conversations.json` — one JSON array per user holding all their conversations.
- **Anonymous users** (`user_id == ""`): stored at `memory/anonymous/conversations.json`.
- **Directory creation:** `ConversationManager` calls `os.makedirs(path, exist_ok=True)` before the first write.
- **Thread-safety:** `# TODO` comment deferred to a later stage; no lock for now.

---

### I1 · WebSocket streaming — event stream

The WebSocket sends discrete JSON event messages, not a single final message. Two event types:

```jsonc
{"event": "status",   "agent": "librarian", "message": "working"}
{"event": "response", "conversation_id": "...", "response": "..."}
```

One status event is emitted per agent as it begins processing. One response event is emitted when Responder completes. Token-level chunking is deferred to Stage 19 (LLM).

---

## Decision summary table

| ID  | Topic                                                | Status                                                          |
| --- | ---------------------------------------------------- | --------------------------------------------------------------- |
| A1  | Python version + packaging                           | ✅ files exist locally                                           |
| A2  | Test file layout                                     | ✅ single `test-stages.py`, one function per stage               |
| B1  | ACLMessage performative type + full set              | ✅ StrEnum; REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL  |
| B2  | ConversationState fields                             | ✅ confirmed                                                     |
| B3  | TaskStep structure                                   | ✅ dataclass with agent / action / params                        |
| C1  | Broadcast agent registration                         | ✅ explicit `register_agent()`                                   |
| C2  | Agent chain pattern                                  | ✅ hub-and-spoke, Planner orchestrates                           |
| C3  | Planner stub dispatch + sufficiency score            | ✅ all 3 parallel; stub scores 1.0; PLANNER_SUFFICIENCY_THRESHOLD |
| C4  | BaseAgent.run()                                      | ✅ confirmed loop + STOP intercept                               |
| C5  | Completion signal                                    | ✅ `threading.Event` per conversation                            |
| D1  | create_or_get                                        | ✅ inline create + get in REST                                   |
| D2  | Conversation persistence                             | ✅ JSON per user at memory/<user_id>/conversations.json          |
| D3  | Responder conversation_id source                     | ✅ from `message.conversation_id`                                |
| D4  | Timeouts + failure behavior                          | ✅ 30s, exit 0, HTTP 408                                         |
| E1  | SafetyGateway error contract                         | ✅ raise `SafetyError`                                           |
| E2  | user_profile values                                  | ✅ beginner / long_term / analyst, case-insensitive              |
| F1  | MCP tool name convention                             | ✅ namespaced `tool.method`                                      |
| F2  | Milvus config                                        | ✅ `MILVUS_URI` only                                             |
| F3  | Embedding model                                      | ✅ sentence-transformers, config-driven, zero-vector stub        |
| F4  | Analyst API schema                                   | ✅ stub schema defined                                           |
| F5  | sql_tool stage + database                            | ✅ Stage 8b, PostgreSQL, `DATABASE_URL`                          |
| G1  | REST shared-state injection                          | ✅ constructor injection                                         |
| G2  | user_id in REST                                      | ✅ optional body field, default `""`                             |
| H1  | Confidence thresholds                                | ✅ 0.6 / 0.75, config-driven, dict-only input                    |
| H2  | LangGraph                                            | ✅ deferred to Stage 20+                                         |
| I1  | WebSocket streaming                                  | ✅ event stream: status events + final response event            |


