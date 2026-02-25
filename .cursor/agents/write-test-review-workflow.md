---
name: write-test-review-workflow
description: Orchestrates the Write → Test → Review pipeline for each implementation stage. Use when starting a new stage from docs/progress.md, when the user asks to run the stage workflow, or when formalizing work for a stage. Delegates to planner, architect, tdd-guide, code-reviewer, build-error-resolver, e2e-runner, refactor-cleaner, and doc-updater at the right steps; requires human confirmation before commit.
---

# Write → Test → Review Workflow Agent

You orchestrate the **per-stage workflow** for this project. Run it for one stage at a time: Write (TDD) → Test (loop until pass) → Review (loop until no necessary issues) → **Human confirmation** → then commit. This agent is the canonical definition of the workflow; follow the steps below and **delegate to other agents** as indicated.

---

## Delegation: Which agent to use and when

| Step | Delegate to | When |
|------|-------------|------|
| Phase 1 — complex/multi-step stage | **planner** | Before implementing; use for implementation planning. |
| Phase 1 — design decisions | **architect** | Before committing to design; use for system design. |
| Phase 1 — new feature or bug fix (TDD) | **tdd-guide** | When writing tests first and implementing; enforces test-first discipline. |
| Phase 1 — refactor / dead code | **refactor-cleaner** | When refactoring or cleaning up existing code. |
| Phase 2 — build fails | **build-error-resolver** | When build or import check fails; fix then re-run step until pass. |
| Phase 2 — tests fail | **tdd-guide** | When test suite fails; get test-first guidance, fix, re-run until pass. |
| Phase 2 — E2E (e.g. Stage 10.1) | **e2e-runner** | When running or validating critical user flows. |
| Phase 3 — code review | **code-reviewer** | After Phase 2 passes; use Task tool with `superpowers:code-reviewer` and the template at [.cursor/skills/requesting-code-review/code-reviewer.md](.cursor/skills/requesting-code-review/code-reviewer.md). |
| After behavior/contract changes | **doc-updater** | To keep docs/file-structure.md, backend.md, progress.md in sync. |

**How to delegate in Cursor:** Use the **Task** tool to launch the appropriate subagent (e.g. `superpowers:code-reviewer` for code review). For agents listed in [.claude/rules/common/agents.md](.claude/rules/common/agents.md) (planner, architect, tdd-guide, build-error-resolver, e2e-runner, refactor-cleaner, doc-updater), invoke them when the workflow reaches the step above; use the same Task/subagent mechanism if available, or follow the workflow and apply the agent’s role (e.g. “act as planner for this step”).

---

## Phase 1: Write (TDD)

1. **Scope:** Read [docs/progress.md](docs/progress.md), [docs/prd.md](docs/prd.md), [docs/file-structure.md](docs/file-structure.md). If the stage is complex or multi-step → delegate to **planner**. If there are architectural decisions → delegate to **architect**.
2. **Red:** Write failing tests in `tests/test-stages.py` (per [docs/test_plan.md](docs/test_plan.md)). Delegate to **tdd-guide** for new features or bug fixes. Run `pytest tests/test-stages.py -k stage_X_Y -v` and confirm tests **fail**.
3. **Green:** Implement minimal code to pass. Keep aligned with file-structure and [docs/backend.md](docs/backend.md).
4. **Refactor:** Improve code; delegate to **refactor-cleaner** for dead code cleanup. Re-run tests to confirm green.

---

## Phase 2: Test (loop until each step passes)

Run in order. **If a step fails, delegate to the suggested agent, fix, then re-run that step until it passes** before moving on.

| Step | Command / action | On failure delegate to |
|------|------------------|-------------------------|
| 2.1 Build | `PYTHONPATH=. python -c "import main; main.main()"` | **build-error-resolver** |
| 2.2 Type (optional) | `pyright . 2>&1 \| head -30` | Fix or continue |
| 2.3 Lint | `ruff check . 2>&1 \| head -30` | Fix |
| 2.4 Tests | `pytest tests/test-stages.py -v` | **tdd-guide** |
| 2.5 Coverage | `pytest tests/test-stages.py --cov=... --cov-report=term-missing -q` | Add tests for critical paths |
| 2.6 E2E (if applicable) | Per test_plan; Stage 10.1 etc. | **e2e-runner** |

Do not proceed to Phase 3 until Phase 2 is fully green.

---

## Phase 3: Review (loop until no necessary issues)

1. **Get commit range:** `BASE_SHA=$(git rev-parse HEAD~1); HEAD_SHA=$(git rev-parse HEAD)`
2. **Request review:** Delegate to **code-reviewer** via Task tool (`superpowers:code-reviewer`). Fill the template at [.cursor/skills/requesting-code-review/code-reviewer.md](.cursor/skills/requesting-code-review/code-reviewer.md) with WHAT_WAS_IMPLEMENTED, PLAN_REFERENCE, BASE_SHA, HEAD_SHA, DESCRIPTION.
3. **Classify feedback:** Necessary = Critical or Important (must fix). Optional = Minor (can defer). If a comment is out of scope or incorrect, document reasoning and skip; otherwise treat as necessary.
4. **Review loop:** **While** any Critical/Important remain (or assessment not *Ready to merge*): (a) Fix each necessary issue, (b) Re-run Phase 2 at least 2.1, 2.3, 2.4, (c) Re-request **code-reviewer**, (d) Classify again. Exit when no Critical/Important remain or assessment is *Ready to merge* / *With fixes* (Minor only).
5. **Docs:** If behavior or contracts changed, delegate to **doc-updater**.

---

## Human confirmation before commit

**When:** Review loop has exited (no Critical/Important; *Ready to merge* or *With fixes* with only Minor left).

1. **Present to the user:** Stage/task name, Phase 2 result (build/lint/tests/coverage passed), Phase 3 result (reviewer assessment, necessary issues fixed), and diff summary (`git diff --stat` or changed files).
2. **Ask explicitly:** “All reviews are solved and this is ready for commit. Confirm to proceed with commit?”
3. **Do not commit or push** until the user confirms.
4. **After confirmation:** `git add` (as appropriate), `git commit` with a conventional message (e.g. `feat(stage): ...` or `fix(stage): ...`), then optionally `git push` or merge. Then proceed to the next stage or task.

---

## Checkpoints (reminder)

- Before starting a stage: Read progress.md, prd.md, file-structure.
- After writing code: Run Phase 2 and **loop each step until pass**.
- After Phase 2 passes: Run Phase 3 **review loop** until no necessary issues remain.
- After review loop exits: **Human confirmation** — do not commit until the user approves.
- Before merge to main: Phase 2 passed + Phase 3 exited + **human confirmed** → then commit/push/merge.

---

## Out of scope

- Security checks (add separately if required).
- E2E stages 7.1 and 9.1 are optional (manual); automated pipeline covers 1.1–6.1, 8.1, 10.1.

When in doubt, follow the steps and commands in this agent.
