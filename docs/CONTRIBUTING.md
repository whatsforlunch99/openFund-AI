# Contributing

This guide covers local development, tests, code quality, and PR expectations for OpenFund-AI.

## Prerequisites

- Python `3.11+`
- Optional local backends for full integration testing: PostgreSQL, Neo4j, Milvus

## Development Setup

1. Create and activate a virtual environment.
2. Install project and development dependencies.
3. Copy environment template.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

The `dev` optional dependency group includes **pytest**, **ruff**, and other tooling (`pyproject.toml`). Use `python -m pip install -e ".[dev]"` so `python -m pytest` works without a globally installed `pytest`.

## Commands

<!-- AUTO-GENERATED: scripts and run commands -->
| Command | Description |
|---------|-------------|
| `./scripts/run.sh` | Start local system bootstrap (API + optional chat). |
| `./scripts/run.sh --no-chat` | Start API only via runner script. |
| `powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1` | Windows runner equivalent. |
| `./scripts/stop.sh` | Stop local Postgres/Neo4j/Milvus helpers. |
| `python main.py --serve --port 8000` | Start FastAPI service directly. |
| `python main.py --e2e-once` | Run one end-to-end chat cycle. |
| `python -m openfund_mcp` | Start MCP server over stdio. |
| `python scripts/data_loader.py --load-mode existing` | Load existing datasets into configured backends. |
| `python scripts/data_loader.py --load-mode fresh-all` | Full reload of loader-owned backend data. |
| `python scripts/check_health.py --port 8000` | Verify `/health` and LLM readiness. |
| `python -m pytest tests/ -v` | Run test suite (requires `pip install -e ".[dev]"`). |
| `ruff check .` | Run lint checks. |
| `black .` | Format codebase. |
| `./scripts/install-git-hooks.sh` | Install repo-managed git hooks. |
| `./scripts/commit-and-push.sh -m "message"` | Run staged review, commit, and optionally push. |
<!-- END AUTO-GENERATED -->

## Environment Variables

Environment variables are documented in `docs/shared/ENV.md` (generated from `.env.example` and config usage).

## Testing

- Run fast checks first: `ruff check .`
- Run targeted tests while iterating: `python -m pytest tests/ -k <keyword>`
- Run full tests before PR: `python -m pytest tests/ -v`
- If `pytest` is not found, ensure the venv is active and run `python -m pip install -e ".[dev]"` first, then use **`python -m pytest`** (invokes the environment’s pytest module).

## Code Style and Quality

- Lint: Ruff (`tool.ruff` in `pyproject.toml`)
- Format: Black (`tool.black` in `pyproject.toml`)
- Type checks (optional in dev extras): MyPy
- Keep changes cohesive by feature and avoid unrelated edits in one PR

## Pull Request Checklist

- [ ] Scope is focused and cohesive
- [ ] Tests added/updated for behavior changes
- [ ] `ruff check .` passes
- [ ] Relevant docs updated (workflow docs, ENV, runbook, etc.)
- [ ] No secrets committed (`.env`, keys, credentials)

