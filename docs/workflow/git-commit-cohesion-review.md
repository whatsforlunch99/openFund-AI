# Git commit: cohesion and coupling review

Operational companion to `.cursor/rules/git-commit-cohesion-review.mdc` and `scripts/review_staged_for_commit.py`.

## Install hooks

```bash
./scripts/install-git-hooks.sh
```

This sets `git config core.hooksPath scripts/git-hooks` so `pre-commit` runs on every `git commit`.

## Automated checks (pre-commit)

- **Secrets guardrails:** rejects staging paths like `.env`, common private key names, and risky `.pem` patterns.
- **Cohesion hint:** lists how many files are staged per top-level directory (`agents/`, `util/`, …) and warns when many unrelated areas change at once.
- **Ruff:** `ruff check` on staged `*.py` files if `ruff` is installed (`pip install '.[dev]'`).

Manual dry run (no ruff failure exit from cohesion hints only):

```bash
python3 scripts/review_staged_for_commit.py --print-only
```

## Semantic review (Cursor)

Before committing, ask the AI to review the staged diff using the **git-commit-cohesion-review** Cursor rule (or paste the checklist from that rule). The hook cannot refactor code; cohesion/coupling fixes are applied in the editor.

## Optional commit + push

```bash
./scripts/commit-and-push.sh -m "feat: describe change"
```

Runs the review script once, then `git commit` (which runs the hook again), then prompts to push.

## Related

- [docs-structure.mdc](../../.cursor/rules/docs-structure.mdc) — which doc to update when behavior changes.
- [operating-principles.mdc](../../.cursor/rules/operating-principles.mdc) — small diffs, no secrets.
