# OpenFund-AI

Live multi-agent investment research system (Planner, Librarian, WebSearcher, Analyst, Responder) over MCP tools and FastAPI.

## One Command Run

Use only:

```bash
./scripts/run.sh
```

This single script can:
- create `.env` from `.env.example` (first run)
- optionally install deps
- start local backends (PostgreSQL, Neo4j, Milvus) when configured
- seed baseline data
- load `datasets/combined_funds.json`
- start the live API (`main.py --serve`)

## Common Options

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
```

## Direct API Run (Optional)

If you want to run manually without helper script:

```bash
python main.py --serve --port 8000
```

## Authentication

- Register with unique username via `POST /register`
- Login with username via `POST /login`
- Username duplicates are rejected

## Data CLI

```bash
python -m data_manager --help
python -m data_manager populate
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode existing
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode fresh --fresh-scope symbols
python -m data_manager sql "SELECT * FROM fund_info LIMIT 5"
```

## Notes

- `LLM_API_KEY` is required for live planner/specialist decomposition.
- Run from project root.
- `demo/` has been removed; system is now live-only.
