# OpenFund-AI

Live multi-agent investment research backend (Planner, Librarian, WebSearcher, Analyst, Responder) over MCP tools and FastAPI.

## Start

Preferred single command:

```bash
./scripts/run.sh
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

Direct API run:

```bash
python main.py --serve --port 8000
```

Stop local backends:

```bash
./scripts/stop.sh
```

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

## Data CLI

```bash
python -m data_manager --help
python -m data_manager populate
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode existing
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode fresh --fresh-scope symbols
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode fresh --fresh-scope all
python -m data_manager sql "SELECT * FROM fund_info LIMIT 5"
```

## Docs

- [docs/prd.md](docs/prd.md)
- [docs/backend.md](docs/backend.md)
- [docs/data-manager-agent.md](docs/data-manager-agent.md)
- [docs/fund-data-schema.md](docs/fund-data-schema.md)
- [docs/user-flow.md](docs/user-flow.md)
- [docs/use-case-trace-beginner.md](docs/use-case-trace-beginner.md)
- [docs/agent-tools-reference.md](docs/agent-tools-reference.md)
- [docs/project-status.md](docs/project-status.md)
- [docs/progress.md](docs/progress.md)
- [docs/test_plan.md](docs/test_plan.md)
- [docs/file-structure.md](docs/file-structure.md)

## Notes

- `LLM_API_KEY` is required for live LLM decomposition/specialist behavior.
- Run commands from project root.
