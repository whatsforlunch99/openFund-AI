# Demo / Running the full stack

The project runs the **full stack** with real data, real API calls, and a real LLM when configured. There is no separate "demo mode" toggle or stub pipeline.

---

## How to run

**Preferred (single command):**

```bash
./scripts/run.sh
```

This starts backends (when configured), seeds data, loads funds, starts the live API, and launches an **interactive chat** in the terminal. The chat may ask for username and password (or Enter to skip for anonymous) before the "You: " prompt. On first run it creates `.env` from `.env.example` — edit `.env` and set `LLM_API_KEY` (and any backend keys you need), then re-run.

To run the API only without the interactive chat client:

```bash
./scripts/run.sh --no-chat
```

**Direct API (no backends, no seed):**

```bash
python main.py --serve --port 8000
```

Use `python3` if `python` is not Python 3.

To stop local backends (PostgreSQL, Neo4j, Milvus): `./scripts/stop.sh`

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

## Setup checklist (tools and LLM)

Use this to get **tools callable** and **LLM functioning**:

- **LLM:** Set `LLM_API_KEY` in `.env`. Run `pip install -e ".[llm]"`. For DeepSeek set `LLM_BASE_URL=https://api.deepseek.com` and `LLM_MODEL=deepseek-chat`. At startup the API logs `LLM: model=..., base_url=...` so you can confirm configuration.
- **Market / analyst tools:** If you see "Unknown tool" for `market_tool.*` or `analyst_tool.*`, check the startup log for `market_tool skipped` or `analyst_tool skipped` (usually due to missing deps). Install full deps: `pip install -e ".[backends]"` or `pip install -e ".[llm]"`. For market data, set `ALPHA_VANTAGE_API_KEY` or `FINNHUB_API_KEY` and vendor env vars; see [backend.md](backend.md).
- **How to verify:** Call **GET /health** to see `tools` (registered MCP tool names) and `llm_configured`. Or run `PYTHONPATH=. python3 scripts/test_third_party_apis.py` to exercise tools and generate `docs/api-test-results.md`.

---

## Troubleshooting

- **"Unknown tool" or MCP errors:** Check the startup log for `market_tool skipped` / `analyst_tool skipped` (install pandas and deps; re-run `pip install -e ".[backends]"` or full install). Ensure the API was started after installing dependencies. For market/analyst tools to return data (not just be callable), set `ALPHA_VANTAGE_API_KEY` or `FINNHUB_API_KEY` as in [backend.md](backend.md).
- **LLM not functioning:** Confirm `LLM_API_KEY` is set and `pip install -e ".[llm]"` is done. For DeepSeek set `LLM_BASE_URL` and `LLM_MODEL`. Check startup log for `LLM: model=..., base_url=...`. If the server fails to start with "LLM is required", set the key and reinstall the llm extra.
- **Neo4j "already running" but connection refused on 7687:** Often caused by a **stale pid file** (Neo4j thinks it is running but the process is gone). Remove it: `rm -f $(find /opt/homebrew -name "neo4j.pid" 2>/dev/null)` (or the path under your Neo4j install), then run `neo4j console` in a separate terminal and wait for "Bolt enabled on localhost:7687". If the process is actually running as root and you cannot stop it, get the PID from `neo4j console` (e.g. "already running (pid:949)") and run `sudo kill -9 <pid>`, then `neo4j console`. If `brew services start neo4j` fails with "Bootstrap failed: 5", use `neo4j console` instead of brew services.
- **Timeout on POST /chat:** Increase timeout or check that LLM_API_KEY is set and the LLM provider is reachable (e.g. LLM_BASE_URL for DeepSeek).
- **Empty or stub responses:** Confirm backends are running and data has been loaded (`python -m data_manager populate`, `distribute-funds` as needed).

**Logging:** By default, the console shows structured logs (request.received, pipeline.*, planner.decompose, agent.*, response.generated, etc.). Interaction and trace logs (`openfund.interaction`, `util.trace_log`) are at DEBUG level and do not appear unless you set `LOG_LEVEL=DEBUG` or re-enable interaction logging (e.g. `INTERACTION_LOG=1` in env) so the default console stays readable.

For API contracts and configuration details, see [backend.md](backend.md). For quick start and command reference, see [README.md](../README.md).
