# Test Plan Document

Stage-by-stage validation matrix for the implementation described in [progress.md](progress.md). This document tracks how to verify behavior and includes a lightweight docs-consistency checklist so `/docs` stays aligned.

---

## Runtime test matrix

Primary automated suite: `pytest tests/test-stages.py -v`.

| Stage | Scope | Command | Expected result |
|------|-------|---------|-----------------|
| 1.2 | MessageBus basics | `pytest tests/test-stages.py -k stage_1_2 -v` | Queueing and receive semantics pass |
| 1.3 | ConversationManager basics | `pytest tests/test-stages.py -k stage_1_3 -v` | Create/get/register behavior passes |
| 2.1 | MCP file_tool path | `pytest tests/test-stages.py -k stage_2_1 -v` | `file_tool.read_file` flow passes |
| 3.x–9.x | Agent/API slices | `pytest tests/test-stages.py -v` | Slice coverage in `tests/test-stages.py` passes |
| 10.1 | One-shot E2E smoke | `python main.py --e2e-once` | One conversation completes or clean timeout |

---

## Docs consistency checklist (`/docs`)

Use this checklist whenever docs are updated:

1. **Cross-file links resolve** (no references to missing docs).
2. **Status vocabulary remains consistent** with `project-status.md` (`Not Started`, `In Progress`, `Live`, `Deprecated`).
3. **Scope boundaries are respected**:
   - `prd.md`: what/why requirements only.
   - `backend.md`: API/data model/error/integration contracts.
   - `file-structure.md`: module and function responsibilities.
   - `progress.md`: implementation slices + changelog.
4. **Document inventory stays accurate** (files listed in `file-structure.md` match real files under `docs/`).

### Suggested commands

- `find docs -maxdepth 1 -type f | sort`
- `rg -n "\[[^\]]+\]\(([^)]+)\)" docs/*.md`
- `pytest tests/test-stages.py -v`

