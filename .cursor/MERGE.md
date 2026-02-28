# Merge: .agents and .claude → .cursor

All configuration previously under `.agents` and `.claude` now lives under `.cursor`.

## Layout

- **rules/** — Cursor rules (`.mdc`) plus merged rules from Claude:
  - **common/** — coding-style, git-workflow, testing, security, patterns, hooks, etc. (from .claude)
  - **python/** — coding-style, testing, patterns, hooks, security (from .claude)
- **skills/** — All skills from .cursor, .claude, and .agents. Duplicates kept the .cursor version.
- **commands/** — Claude commands (plan, tdd, code-review, verify, etc.).
- **scripts/** — Claude hooks and lib (session-start, session-end, evaluate-session, etc.).
- **agents/** — Cursor agent definitions (e.g. write-test-review-workflow).
- **hooks.json** — Claude hooks config (from .claude).
- **README-claude.md** — Original Claude README (from .claude).

There was no `.agent` directory; only `.agents` and `.claude` were merged. `.agents` and `.claude` have been removed after the merge.
