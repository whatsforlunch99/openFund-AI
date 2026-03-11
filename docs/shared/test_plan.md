# Test Plan Document

Stage-by-stage validation matrix for the implementation described in [progress.md](../workflow/90_product/progress.md). This document tracks how to verify behavior and includes a lightweight docs-consistency checklist so `/docs` stays aligned.

---

## Runtime test matrix

Primary automated suite: `pytest tests/test-stages.py -v`.

| Stage | Scope | Command | Expected result |
|------|-------|---------|-----------------|
| 1.1 | Config + main | `PYTHONPATH=. python main.py` | Prints ready message, exit 0 |
| 1.2 | MessageBus basics | `pytest tests/test-stages.py -k stage_1_2 -v` | Queueing and receive semantics pass |
| 1.3 | ConversationManager basics | `pytest tests/test-stages.py -k stage_1_3 -v` | Create/get/register_reply/persistence/broadcast_stop pass |
| 2.1 | MCP file_tool path | `pytest tests/test-stages.py -k stage_2_1 -v` | `file_tool.read_file` flow passes |
| 2.2 | Trading tools (market_tool) | `pytest tests/test-stages.py -k stage_2_2 -v` | market_tool endpoints (e.g. get_stock_data) pass |
| 2.3 | Situation memory | `pytest tests/test-stages.py -k stage_2_3 -v` | FinancialSituationMemory add/get/save/load pass |
| 3.1–3.3 | Slice 3 agents | `pytest tests/test-stages.py -k "stage_3_1 or stage_3_2 or stage_3_3" -v` | Planner, Librarian (file_tool), Responder stub pass |
| 3.x–9.x | Agent/API slices | `pytest tests/test-stages.py -v` | Slice coverage in `tests/test-stages.py` passes |
| 10.1 | One-shot E2E smoke | `PYTHONPATH=. python main.py --e2e-once` | One conversation completes (planner → librarian → responder), exit 0 |

Stages **7.1** and **9.1** are optional (manual curl or WebSocket client); full automated suite covers 1.1–6.1, 8.1, 10.1.

For per-stage deliverables and slice context, see [progress.md](progress.md).

---

## Docs consistency checklist (`/docs`)

Use this checklist whenever docs are updated:

1. **Cross-file links resolve** (no references to missing docs; remove references to deleted docs e.g. backend-tools-design.md).
2. **Status vocabulary remains consistent** with `project-status.md` (`Not Started`, `In Progress`, `Live`, `Deprecated`).
3. **Scope boundaries are respected**:
   - `prd.md`: what/why requirements only.
   - `backend.md`: API/data model/error/integration contracts.
   - `file-structure.md`: module and function responsibilities.
   - `progress.md`: implementation slices + changelog.
4. **Document inventory stays accurate** (files listed in `file-structure.md` match real files under `docs/`).

**Generated doc:** `api-test-results.md` is produced by `scripts/test_third_party_apis.py`; do not edit by hand.

### Suggested commands

- `find docs -maxdepth 1 -type f | sort`
- `rg -n "\[[^\]]+\]\(([^)]+)\)" docs/*.md`
- `pytest tests/test-stages.py -v`

