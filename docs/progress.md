# Progress Document

Work breakdown (slices/stages), runnable verification commands, solved repeated errors, and pointers to changelog. **Update this document when new changes are introduced** (work breakdown, errors). **Update [CHANGELOG.md](../CHANGELOG.md) at repo root** when making user-visible or notable changes (features, fixes, refactors, config, dependencies).

---

## Work breakdown — slices and stages

Development proceeds in **slices**; each slice is a runnable checkpoint. Tests live in `tests/test-stages.py`. Run full suite: `pytest tests/test-stages.py -v`. PRD allows one or more rounds; current slices deliver **one round** for MVP; multi-round Planner is an optional follow-up.

### Slice summary

| Slice | What you add | Runnable checkpoint |
|-------|----------------|---------------------|
| 1 | Config, MessageBus, ConversationManager (1.1–1.3) | `main.py` runs; stage_1_2 and stage_1_3 tests pass |
| 2 | MCP server/client, file_tool (2.1), trading tools (2.2), situation memory (2.3) | stage_2_1, stage_2_2, stage_2_3 tests pass |
| 3 | ACLMessage, BaseAgent, Planner (1 step), Librarian (file_tool), Responder (stub) | `python main.py --e2e-once` completes one conversation |
| 4 | vector_tool, kg_tool, sql_tool (mocks); full Librarian | E2E with Librarian using three tools |
| 5 | WebSearcher, Analyst; Planner sends to all three | E2E with five agents, one round |
| 6 | SafetyGateway | E2E with process_user_input; bad input rejected |
| 7 | REST: create_app, POST /chat, GET /conversations | curl POST /chat returns 200 JSON |
| 8 | OutputRail in Responder | Response text varies by user_profile |
| 9 | WebSocket /ws | GET and WebSocket work |

### Stage → test function and runnable command

| Stage | Slice | Test function | Runnable command |
|-------|-------|---------------|------------------|
| 1.1 | 1 | — | `PYTHONPATH=. python main.py` |
| 1.2 | 1 | `test_stage_1_2` | `pytest tests/test-stages.py -k stage_1_2 -v` |
| 1.3 | 1 | `test_stage_1_3` | `pytest tests/test-stages.py -k stage_1_3 -v` |
| 2.1 | 2 | `test_stage_2_1` | `pytest tests/test-stages.py -k stage_2_1 -v` |
| 2.2 | 2 | `test_stage_2_2_trading_tools` | `pytest tests/test-stages.py -k stage_2_2 -v` |
| 2.3 | 2 | `test_stage_2_3_situation_memory`, `test_stage_2_3_situation_memory_load_from_dir_missing` | `pytest tests/test-stages.py -k stage_2_3 -v` |
| 3.1 | 3 | `test_stage_3_1` | `pytest tests/test-stages.py -k stage_3_1 -v` |
| 3.2 | 3 | `test_stage_3_2` | `pytest tests/test-stages.py -k stage_3_2 -v` |
| 3.3 | 3 | `test_stage_3_3` | `pytest tests/test-stages.py -k stage_3_3 -v` |
| 4.1 | 4 | `test_stage_4_1` | `pytest tests/test-stages.py -k stage_4_1 -v` |
| 4.2 | 4 | `test_stage_4_2` | `pytest tests/test-stages.py -k stage_4_2 -v` |
| 4.3 | 4 | `test_stage_4_3` | `pytest tests/test-stages.py -k stage_4_3 -v` |
| 5.1 | 5 | `test_stage_5_1` | `pytest tests/test-stages.py -k stage_5_1 -v` |
| 5.2 | 5 | `test_stage_5_2` | `pytest tests/test-stages.py -k stage_5_2 -v` |
| 5.3 | 5 | `test_stage_5_3` | `pytest tests/test-stages.py -k stage_5_3 -v` |
| 5.4 | 5 | `test_stage_5_4` | `pytest tests/test-stages.py -k stage_5_4 -v` |
| 6.1 | 6 | `test_stage_6_1` | `pytest tests/test-stages.py -k stage_6_1 -v` |
| 7.1 | 7 | `test_stage_7_1` (optional) | curl POST /chat; GET /conversations/{id} |
| 8.1 | 8 | `test_stage_8_1` | `pytest tests/test-stages.py -k stage_8_1 -v` |
| 9.1 | 9 | `test_stage_9_1` (optional) | WebSocket client; GET |
| 10.1 | E2E | — | `PYTHONPATH=. python main.py --e2e-once` |
| 10.2 | Optional | — | POST /chat with NL (manual) |

Per-slice and per-stage behavior details: [prd.md](prd.md), [backend.md](backend.md), and [test_plan.md](test_plan.md). Test assertions per stage: see `tests/test-stages.py`.

---

## Solved repeated errors

*(Record recurring issues and their fixes here so the same mistakes are not repeated.)*

- **Python 3.9 and StrEnum:** `enum.StrEnum` exists from 3.11. Use `class Performative(str, Enum)` in `a2a/acl_message.py` for 3.9 compatibility.
- **Slice 3 implemented:** InMemoryMessageBus, ConversationManager (create/get/register_reply/broadcast_stop + persistence), PlannerAgent (one step → librarian, forwards INFORM → responder), LibrarianAgent (file_tool), ResponderAgent (stub), `main.py --e2e-once`.
- **Slice 4 implemented:** vector_tool, kg_tool, sql_tool (mocks when backends unset); full Librarian (retrieve_documents, retrieve_knowledge_graph, combine_results; content keys: path, vector_query, fund, sql_query). Tests: test_stage_4_1, test_stage_4_2, test_stage_4_3.
- **Slice 5 implemented:** WebSearcherAgent (handle_message, fetch_market_data, fetch_sentiment, fetch_regulatory via market_tool); AnalystAgent (handle_message, analyze stub, needs_more_data, sharpe_ratio, max_drawdown, monte_carlo_simulation); Planner sends to all three (librarian, websearcher, analyst) in one round and aggregates INFORMs before forwarding to Responder. E2E: `main.py --e2e-once` runs five agents (planner, librarian, websearcher, analyst, responder). Tests: test_stage_5_1, test_stage_5_2, test_stage_5_3, test_stage_5_4.

- **Slice 6 (Stage 6.1) implemented:** SafetyGateway in `safety/safety_gateway.py`: validate_input (reject empty/whitespace-only, max length 10_000, UTF-8 printable/whitespace), check_guardrails (block list: e.g. "guaranteed return", "buy this stock now", "insider tip"), mask_pii (phone, email, SSN-like placeholders), process_user_input (validate → guardrails → mask_pii; raises SafetyError on failure). test_stage_6_1 passes.

- **MCP `register_default_tools` failing when pandas missing:** `register_default_tools()` imported all tools in one block; if `analyst_tool` (or `market_tool`) failed to import (e.g. missing pandas), stage 2.1/2.2 tests failed. Fix: import `file_tool` first and register it; register `market_tool` and `analyst_tool` only inside try/except ImportError so optional tools are skipped when deps are missing.

---

## PRD coverage and risks

**PRD coverage:** The plan meets the PRD for MVP. All functional requirements (FR1–FR7), constraints (C1–C3), and acceptance criteria (AC1–AC5) are covered by slices 1–10 and the contracts in [backend.md](backend.md) and [user-flow.md](user-flow.md). The PRD column in [project-status.md](project-status.md) maps each capability to the relevant FR/AC.

**Risks and dependencies:**
- **Slice order:** Ensure stage 2.1 (file_tool) is green before slice 3; SafetyGateway (6) before REST (7). Slices 3–5 depend on MCP and agents; 7–9 on the API layer.
- **MCP/backends unavailable:** Use mocks for vector_tool, kg_tool, sql_tool, and market_tool (slices 4–5). Timeout behavior (408) and E2E timeout config are in backend.md.
- **Phase 2:** LLM integration (decompose_task, sufficiency) is Stage 10.2 / Phase 2; see project-status.md.
- **Slice 3 implementation:** Planner handles INFORM from librarian and forwards to Responder with `final_response`; `main.py --e2e-once` uses a temp file as the query path so file_tool.read_file succeeds and one conversation completes (exit 0). E2E timeout is non-fatal per backend.md.
