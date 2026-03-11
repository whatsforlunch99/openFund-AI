# Claude Code config (from ECC — OpenFund-AI)

This folder contains **rules**, **skills**, **hooks**, and **commands** based on [everything-claude-code](https://github.com/affaan-m/everything-claude-code), filtered for OpenFund-AI (Python, FastAPI, pytest).

## Contents

- **rules/** — `common/` (language-agnostic) + `python/` (Python/pytest). Used by Claude Code when working in this project.
- **skills/** — 12 task-specific skills (api-design, backend-patterns, python-testing, security-review, tdd-workflow, etc.).
- **commands/** — 11 slash-style commands: build-fix, checkpoint, code-review, plan, python-review, refactor-clean, tdd, test-coverage, update-codemaps, update-docs, verify.
- **hooks.json** — PreToolUse (tmux reminder, git push reminder, doc warning, strategic compact), PostToolUse (PR logger, build analysis), SessionStart, PreCompact, SessionEnd, pattern extraction.
- **scripts/** — Hook scripts and `lib/` they depend on. Hook commands in `hooks.json` use paths like `node .cursor/scripts/hooks/session-start.js`; these run correctly when Claude Code’s working directory is the **project root**.

## Using hooks

- If Claude Code loads project-level hooks from `.cursor/hooks.json`, no extra step is needed; ensure you run Claude Code from this project root so `.cursor/scripts/hooks/` resolves.
- If your setup only reads hooks from the user config, merge the `hooks` object from `.cursor/hooks.json` into `~/.claude/settings.json` (under the `hooks` key). Keep the project as the current working directory when running so the `node .cursor/scripts/hooks/...` paths work.
- To disable a specific hook, remove or comment out its entry in `hooks.json` or override in `~/.claude/settings.json`.
