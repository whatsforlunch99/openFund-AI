# Progress Document

Work breakdown (slices/stages), runnable verification commands, solved repeated errors, and pointers to changelog. **Update this document when new changes are introduced** (work breakdown, errors). **Update [CHANGELOG.md](../CHANGELOG.md) at repo root** when making user-visible or notable changes (features, fixes, refactors, config, dependencies).

---

## Work breakdown — slices and stages

Development proceeds in **slices**; each slice is a runnable checkpoint. Tests live in `tests/test-stages.py`. Run full suite: `pytest tests/test-stages.py -v`.

### Slice summary

| Slice | What you add | Runnable checkpoint |
|-------|----------------|---------------------|
| 1 | Config, MessageBus, ConversationManager (1.1–1.3) | `main.py` runs; stage_1_2 and stage_1_3 tests pass |
| 2 | MCP server/client, file_tool only (2.1) | stage_2_1 tests pass; `call_tool("file_tool.read_file", ...)` works |
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
| 10.1 | E2E | — | `python main.py --e2e-once` |
| 10.2 | Optional | — | POST /chat with NL (manual) |

Per-slice and per-stage behavior details: [prd.md](prd.md), [backend.md](backend.md). Test assertions per stage: see `tests/test-stages.py` and the test plan coverage (previously in test_plan.md; logic unchanged).

---

## Solved repeated errors

*(Record recurring issues and their fixes here so the same mistakes are not repeated.)*

- *(None recorded yet.)*

---

## Solved repeated errors