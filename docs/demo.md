# Demo / Running the full stack

The project runs the **full stack** with real data, real API calls, and a real LLM when configured. There is no separate "demo mode" toggle or stub pipeline.

---

## How to run

**Preferred (single command):**

```bash
./scripts/run.sh
```

On first run this creates `.env` from `.env.example`. Edit `.env` and set `LLM_API_KEY` (and any backend keys you need), then re-run.

**Direct API (no backends, no seed):**

```bash
python main.py --serve --port 8000
```

Use `python3` if `python` is not Python 3.

---

## Optional: load data into backends

Before or after starting the API you can populate and distribute data:

```bash
# Seed PostgreSQL, Neo4j, Milvus with demo data (idempotent)
python -m data_manager populate

# Distribute fund dataset to databases
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode existing
```

The `sql` command requires PostgreSQL configured in `.env` and loaded data:

```bash
python -m data_manager sql "SELECT * FROM fund_info LIMIT 5"
```

---

## Prerequisites

- **Python 3.** Run all commands from the project root.
- **LLM_API_KEY** in `.env` for live planner/specialist decomposition. Install optional LLM deps: `pip install -e ".[llm]"`.
- Optional backends: set `DATABASE_URL`, `NEO4J_URI`, `MILVUS_URI` in `.env` for PostgreSQL, Neo4j, Milvus. See [backend.md](backend.md) for configuration.

---

## Troubleshooting

- **"Unknown tool" or MCP errors:** Ensure the API was started after installing dependencies; market_tool and analyst_tool are skipped if optional deps (e.g. pandas) are missing.
- **Timeout on POST /chat:** Increase timeout or check that LLM_API_KEY is set and the LLM provider is reachable (e.g. LLM_BASE_URL for DeepSeek).
- **Empty or stub responses:** Confirm backends are running and data has been loaded (`python -m data_manager populate`, `distribute-funds` as needed).

For API contracts and configuration details, see [backend.md](backend.md). For quick start and command reference, see [README.md](../README.md).
