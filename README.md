# OpenFund-AI

Live multi-agent investment research backend (Planner, Librarian, WebSearcher, Analyst, Responder) over MCP tools and FastAPI.

## Start

Preferred single command:

```bash
./scripts/run.sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

This can:
- bootstrap `.env` from `.env.example`
- optionally install deps (`--install-deps`)
- optionally start local backends (`--no-backends` to skip)
- optionally seed baseline data (`--no-seed` to skip)
- optionally load funds data (`--funds existing|fresh-symbols|fresh-all|skip`)
- start API and interactive terminal chat (use `--no-chat` for API only)

## Common CLI

```bash
./scripts/run.sh --help
./scripts/run.sh --port 8010
./scripts/run.sh --no-backends
./scripts/run.sh --no-seed
./scripts/run.sh --funds existing
./scripts/run.sh --funds fresh-symbols
./scripts/run.sh --funds fresh-all
./scripts/run.sh --funds skip
./scripts/run.sh --install-deps
./scripts/run.sh --no-chat
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --help
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --port 8010
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --no-backends
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --no-seed
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --funds existing
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --funds fresh-symbols
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --funds fresh-all
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --funds skip
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --install-deps
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --no-chat
```

Direct API run:

```bash
python main.py --serve --port 8000
```

Stop local backends:

```bash
./scripts/stop.sh
```

## Development Setup

### Prerequisites

- **Python 3.11+** (see `requires-python` in [pyproject.toml](pyproject.toml))
- Optional: virtualenv or venv for isolation

### Setup

1. Clone the repo and go to the project root.
2. Create and activate a virtualenv (recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```
3. Install the package with dev and optional extras:
   ```bash
   pip install -e .
   pip install -e ".[dev]"
   pip install -e ".[llm]"        # for live LLM (OpenAI/DeepSeek)
   pip install -e ".[backends]"    # for PostgreSQL, Neo4j, Milvus
   ```
4. Copy environment template and set variables as needed:
   ```bash
   cp .env.example .env
   ```
   See [ENV.md](docs/shared/ENV.md) for variable reference.

### Available Commands

<!-- AUTO-GENERATED: from README, scripts/run.sh, main.py, data_manager, pyproject.toml -->

| Command | Description |
|---------|-------------|
| `./scripts/run.sh` | Single entrypoint: bootstrap .env, optional backends/seed/funds, start API and chat |
| `./scripts/run.sh --port 8010` | Run API on port 8010 |
| `./scripts/run.sh --no-backends` | Skip starting Postgres/Neo4j/Milvus |
| `./scripts/run.sh --no-seed` | Skip `python -m data_manager populate` |
| `./scripts/run.sh --funds existing` | Load funds: existing \| fresh-symbols \| fresh-all \| skip |
| `./scripts/run.sh --install-deps` | Install Python extras [backends, llm] |
| `./scripts/run.sh --no-chat` | Start API only; do not launch interactive chat client |
| `./scripts/stop.sh` | Stop local backends (Postgres, Neo4j, Milvus) |
| `python main.py --serve --port 8000` | Run API directly (no run.sh) |
| `python main.py --e2e-once` | Run one E2E conversation and exit (for CI) |
| `python -m openfund_mcp` | Run MCP server over stdio (for external clients) |
| `python -m data_manager --help` | Data management CLI help |
| `python -m data_manager populate` | Seed PostgreSQL, Neo4j, Milvus with demo data |
| `python -m data_manager sql "SELECT ..."` | Run a SQL query on PostgreSQL |
| `python -m data_manager neo4j "MATCH ..."` | Run Cypher on Neo4j |
| `python -m data_manager milvus ...` | Milvus index/delete documents |
| `python -m data_manager collect ...` | Collect data for symbols |
| `python -m data_manager distribute-funds --file ... --load-mode existing` | Distribute fund data to DBs |
| `pytest tests/ -v` | Run test suite |
| `ruff check .` | Lint (see pyproject.toml [tool.ruff]) |
| `black .` | Format (see pyproject.toml [tool.black]) |

<!-- END AUTO-GENERATED -->

## API

Implemented endpoints:
- `GET /health`
- `POST /register`
- `POST /login`
- `POST /chat`
- `GET /conversations/{conversation_id}`
- `WebSocket /ws`

Auth model:
- register/login by `username` + password
- duplicate usernames rejected

## API Endpoints (Reference)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check; tools and LLM status |
| `/register` | POST | Register user (username, password) |
| `/login` | POST | Login (username, password) |
| `/chat` | POST | Send query; returns response or 408 timeout |
| `/conversations/{conversation_id}` | GET | Get conversation state |
| `/ws` | WebSocket | Same flow as POST /chat; streaming flow events |

## Data CLI

```bash
python -m data_manager --help
python -m data_manager populate
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode existing
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode fresh --fresh-scope symbols
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode fresh --fresh-scope all
python -m data_manager sql "SELECT * FROM fund_info LIMIT 5"
```

## Testing

- **Run all tests:** `pytest tests/ -v`
- **Run a subset:** `pytest tests/test_capabilities.py -v` or `pytest tests/ -k "stage_2" -v`
- **Stage tests:** See [progress.md](docs/workflow/90_product/progress.md) and [test_plan.md](docs/shared/test_plan.md) for stage-specific commands (e.g. `pytest tests/test-stages.py -k stage_2_1 -v`).
- Tests use mocks for external services (Milvus, Neo4j, HTTP) where possible; in-process MCP uses `MCPServer()` + `MCPClient(server)`.
- **E2E:** `python main.py --e2e-once` runs one full conversation (requires no API key; uses fallbacks).

## Code Style

- **Linter:** [Ruff](https://docs.astral.sh/ruff/) — config in `[tool.ruff]` in [pyproject.toml](pyproject.toml). Run: `ruff check .`
- **Formatter:** [Black](https://black.readthedocs.io/) — config in `[tool.black]`. Run: `black .`
- **Type checking:** Optional — `mypy` is in `[dev]`; `ignore_missing_imports = true` for third-party libs.
- **Conventions:** See [.cursor/rules/simple-readable-code.mdc](.cursor/rules/simple-readable-code.mdc) and [python-code-style](https://github.com/cursor/skills/blob/main/skills/python-code-style/SKILL.md) for short functions, stdlib-first, no premature abstraction.

## Submitting Changes

- Prefer small, reviewable diffs; state the plan in a few bullets before editing.
- Add or update tests for behavioral changes.
- For user-visible or notable changes, add an entry to [CHANGELOG.md](CHANGELOG.md) and update [project-status.md](docs/workflow/90_product/project-status.md) if a capability goes live.
- Run `pytest tests/ -v` and `ruff check .` before pushing.

## Operations / Runbook

### Deployment

<!-- AUTO-GENERATED: from README, scripts/run.sh, demo.md -->

1. **Prerequisites:** Python 3.11+, `.env` from `.env.example` with required vars (see [ENV.md](docs/shared/ENV.md)).
2. **Install:** `pip install -e .` and optionally `pip install -e ".[llm]"` and `pip install -e ".[backends]"`.
3. **Start (recommended):** From project root run `./scripts/run.sh`. This can bootstrap `.env`, start local backends (Postgres/Neo4j/Milvus), seed data, and start the API. Use `--no-chat` for API only.
4. **Or start API only:** `python main.py --serve --port 8000` (no backends/seed).
5. **Stop local backends:** `./scripts/stop.sh`.

<!-- END AUTO-GENERATED -->

### Health Checks

<!-- AUTO-GENERATED: from api/rest.py -->

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness and readiness. Returns `tools` (registered MCP tool names) and `llm_configured` for quick verification. |

Use **GET /health** to confirm the API is up and that MCP tools and LLM are configured. For full API contracts see [backend.md](docs/workflow/02_planning/backend.md).

<!-- END AUTO-GENERATED -->

### Common Issues and Fixes

| Issue | Cause | Fix |
|-------|--------|-----|
| "Unknown tool" or market_tool/analyst_tool missing | Optional deps not installed or skipped at startup | Install `pip install -e ".[backends]"` or `.[llm]`; check startup log for "market_tool skipped" / "analyst_tool skipped". Set ALPHA_VANTAGE_API_KEY or FINNHUB_API_KEY as in [backend.md](docs/workflow/02_planning/backend.md). |
| LLM not working / "LLM is required" at startup | Missing LLM_API_KEY or llm extra | Set `LLM_API_KEY` in `.env`; run `pip install -e ".[llm]"`. For DeepSeek set `LLM_BASE_URL` and `LLM_MODEL`. |
| Neo4j connection refused on 7687 | Stale pid file or process not running | Remove stale pid file or run `neo4j console` in a separate terminal; wait for "Bolt enabled on localhost:7687". See [demo.md](docs/demo.md#troubleshooting). |
| POST /chat timeout (408) | LLM slow or unreachable; timeout too low | Increase `E2E_TIMEOUT_SECONDS` in `.env`; verify LLM_API_KEY and LLM_BASE_URL (if used) and provider reachability. |
| Empty or stub responses | Backends not running or no data | Run `python -m data_manager populate` and/or `distribute-funds`; ensure DATABASE_URL, NEO4J_URI, MILVUS_URI are set. |
| MCP server fails to start (subprocess) | MCP SDK not installed | Run `pip install mcp` (or install full deps). API spawns MCP server via `python -m openfund_mcp`. |

More troubleshooting: [demo.md](docs/demo.md).

### Rollback

- **Application:** Stop the API process; redeploy previous version and restart (e.g. `./scripts/run.sh --no-chat` or `python main.py --serve`).
- **Data:** Backends (Postgres, Neo4j, Milvus) are not auto-migrated by the app; restore from backups if you need to revert data changes.
- **Config:** Restore previous `.env` and restart.

### Monitoring and Alerts

- **Liveness:** GET `/health` should return 200; use for load balancer or orchestrator health checks.
- **Logs:** Structured logs include `request.received`, `pipeline.*`, `planner.decompose`, `agent.*`, `response.generated`. Set `INTERACTION_LOG=1` for per-call JSON logging; see [backend.md](docs/workflow/02_planning/backend.md) and [demo.md](docs/demo.md).

## Docs

- **Shared:** [ENV](docs/shared/ENV.md), [test_plan](docs/shared/test_plan.md)
- **Workflow:** [user-flow](docs/workflow/00_overview/user-flow.md), [use-case-trace-beginner](docs/workflow/00_overview/use-case-trace-beginner.md) | [backend](docs/workflow/02_planning/backend.md), [file-structure](docs/workflow/02_planning/file-structure.md) | [agent-tools-reference](docs/workflow/03_tools_and_mcp/agent-tools-reference.md), [mcp-server](docs/workflow/03_tools_and_mcp/mcp-server.md) | [prd](docs/workflow/90_product/prd.md), [project-status](docs/workflow/90_product/project-status.md), [progress](docs/workflow/90_product/progress.md), [frontend](docs/workflow/90_product/frontend.md)
- **Data prep:** [data-manager-agent](docs/data_prep/data-manager-agent.md), [fund-data-schema](docs/data_prep/fund-data-schema.md)
- **RL pipeline:** [rl_pipeline/README](docs/rl_pipeline/README.md)

## Notes

- `LLM_API_KEY` is required for live LLM decomposition/specialist behavior.
- Run commands from project root.
