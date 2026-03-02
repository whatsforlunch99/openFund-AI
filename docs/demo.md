# Demo Mode

The demo runs the **full stack** with **real data**, **real API calls**, and **real LLM** from `.env`. There are no static stubs or `OPENFUND_DEMO`; the API uses live MCP tools and a live LLM for decomposition and answers.

## What runs in the demo

- **API:** Started by `python -m demo`; uses real `MCPClient` and real `get_llm_client(config)`. Planner and specialist agents use the LLM for task decomposition and tool selection.
- **Backends:** PostgreSQL, Neo4j, and Milvus are used when `DATABASE_URL`, `NEO4J_URI`, and `MILVUS_URI` are set in `.env`. SQL, KG, and vector tools run against these backends.
- **Market / analyst:** Market and analyst tools call real external APIs (Alpha Vantage, Finnhub, etc.) when the corresponding API keys are set in `.env`.
- **LLM:** Required. Set `LLM_API_KEY` in `.env`; optionally `LLM_BASE_URL` and `LLM_MODEL` (e.g. for DeepSeek).

## Prerequisites

- **Required:** `LLM_API_KEY` in `.env` (see `.env.example`). Install LLM extra: `pip install -e ".[llm]"`.
- **For rich answers:** `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `MILVUS_URI` so the app can query PostgreSQL, Neo4j, and Milvus.
- **For market/analyst data:** `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY` (optional but recommended).

## First-time data load

Load data into the backends once before or when running the demo:

1. **NVDA-style seed (optional):**  
   `python -m data_manager populate`  
   Seeds demo-style data for SQL, KG, and vector tools.

2. **Fund data (optional):**  
   `PYTHONPATH=. python -m data_manager distribute-funds --funds-dir datasets`  
   Loads fund JSON files from `datasets` into PostgreSQL and Neo4j.

3. **Or use --ensure-data:**  
   `python -m demo --ensure-data`  
   Runs the fund distribution above automatically before starting the API, then starts the demo.

## Run the demo

From the project root:

```bash
python -m demo
```

Optional: load fund data into backends before starting:

```bash
python -m demo --ensure-data
```

Alternative: start the API yourself, then run the chat client:

```bash
python main.py
# In another terminal:
python -m demo.demo_chat --base-url http://localhost:8000
```

Package layout and module contracts: see [file-structure.md](file-structure.md#demo).

## Troubleshooting

- **`.env` location:** The API and `python -m data_manager populate` / `python -m data_manager` load `.env` from the **project root** (the folder that contains `config/`, `data_manager/`, and `demo/`). Run commands from the project root or ensure `.env` is there.
- **Variable names:** In `.env` use `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `MILVUS_URI`, `LLM_API_KEY`. No spaces around `=`.
- **LLM required:** If the API fails to start with "LLM is required", set `LLM_API_KEY` in `.env` and install `pip install -e ".[llm]"`.
- **Populate / distribute:** Run `python -m data_manager populate` and/or `python -m data_manager distribute-funds --funds-dir datasets` once so backends have data; or use `python -m demo --ensure-data`.
- **Driver not installed:** Install backend drivers: `pip install -e ".[backends]"`.
- **Connection failed:** PostgreSQL, Neo4j, and Milvus must be **running** on the host/port in `.env`. Start them (e.g. `./scripts/start_services.sh` or Docker), then run populate/distribute again.
- **Start backends:** Run `python scripts/start_backends.py` or `./scripts/start_services.sh` to check or start services.

### First-time backend setup

- **PostgreSQL: "role \"user\" does not exist"**  
  Homebrew Postgres on macOS uses your **OS username** as the default superuser. In `.env` set:
  ```bash
  DATABASE_URL=postgresql://YOUR_MAC_USERNAME@localhost:5432/openfund
  ```
  (Replace `YOUR_MAC_USERNAME` with the output of `whoami`.) Create the database if needed:
  ```bash
  export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
  createdb openfund
  # Or: ./scripts/create_db.sh
  ```

- **Neo4j: "Unsupported authentication token, missing key 'credentials'"**  
  Set `NEO4J_USER=neo4j` and `NEO4J_PASSWORD` to the password you configured in Neo4j (e.g. in Neo4j Browser at http://localhost:7474).

- **Milvus: "Fail connecting to server on localhost:19530"**  
  Use the project script: `./scripts/start_milvus.sh`. Wait ~30–60 seconds, then run `python -m data_manager populate` or `python -m demo --ensure-data`. To reuse a container: `docker start milvus-standalone`.
