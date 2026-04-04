# Git hooks (OpenFund-AI)

## Install (once per clone)

From the repo root:

```bash
./scripts/install-git-hooks.sh
```

This sets `core.hooksPath` to `scripts/git-hooks` so hooks are versioned with the repo.

## `pre-commit`

Runs `scripts/review_staged_for_commit.py`, which:

- Blocks common secret filenames (e.g. `.env`, private keys, risky `.pem` names).
- Prints a **cohesion** summary (staged files grouped by top-level directory) and hints if many areas are touched.
- Runs **`ruff check`** on staged `.py` files when `ruff` is on your `PATH` (install dev deps: `pip install '.[dev]'`).

It does **not** auto-refactor code. For **high cohesion / low coupling** review and edits, use Cursor with the rule **git-commit-cohesion-review** (see `.cursor/rules/git-commit-cohesion-review.mdc`) on your diff before `git add`.

## Optional: commit and push

After staging and fixing issues:

```bash
./scripts/commit-and-push.sh -m "Your message"
```

`git commit` triggers `pre-commit` automatically; the script then `git push`s the current branch.
