# Demo Mode

The demo runs the full flow with **backend services** (PostgreSQL, Neo4j, Milvus) and **static LLM** (no API key). All demo-related code lives under the **demo/** package.

## Single entry: run the demo

**Recommended:** From the project root run `./demo/run.sh`. First run: it creates `.env` and runs install; edit `.env` (NEO4J_PASSWORD etc.) and run again. Every run: starts backends, seeds data, then `python -m demo`. Alternative: run backends and `python -m data populate` yourself, then `python -m demo`.


## What runs in demo mode

- **API:** When the demo entry point runs, it starts the app with `OPENFUND_DEMO=1`, so the app uses `demo.demo_client.DemoMCPClient`. The planner uses a fixed three-step decomposition (no LLM).
- **Backends:** SQL, KG, and vector tools use **real** PostgreSQL, Neo4j, and Milvus when `DATABASE_URL`, `NEO4J_URI`, or `MILVUS_URI` are set (e.g. after `python -m data populate`). When those env vars are not set, those tools return static data from `DEMO_RESPONSES`.
- **Static data:** File, market, and analyst tools **always** return static data (no Tavily, Yahoo, or Analyst API calls).
- **GET /demo:** Returns `{"demo": true}` when the server is in demo mode; the CLI uses this to show a "Demo mode" message.

## Package layout

| File | Purpose |
|------|---------|
| **demo/run.sh** | Single entry: first-time setup (install backends, .env), start services, seed data, run `python -m demo`. Run from project root. |
| `demo/__main__.py` | `python -m demo` — starts API in demo mode in the background, waits for readiness, runs the chat client; stops the server on quit. |
| `demo/demo_data.py` | Static response dicts per tool name (file_tool.read_file, vector_tool.search, market_tool.*, etc.). |
| `demo/demo_client.py` | `DemoMCPClient.call_tool(tool_name, payload)`: uses real sql/kg/vector when DATABASE_URL/NEO4J_URI/MILVUS_URI are set; file, market, analyst always static. |
| `demo/demo_chat.py` | CLI: prompt name → POST /register → chat loop (POST /chat), prints flow and response. |

See [file-structure.md](file-structure.md#demo) for module contracts.

## Troubleshooting

- **`.env` location:** `python -m data populate` and the API load `.env` from the **project root** (the folder that contains `data/` and `demo/`). Run commands from the project root or ensure `.env` is there.
- **Variable names:** In `.env` use `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `MILVUS_URI`. No spaces around `=`.
- **Populate first:** Run `python -m data populate` once before running the demo; if a backend is skipped, its env var is missing or not loaded.
- **Driver not installed:** Install backend drivers: `pip install -e ".[backends]"`.
- **Connection failed:** PostgreSQL, Neo4j, and Milvus must be **running** on the host/port in `.env`. Start them (e.g. `./scripts/start_services.sh` or Docker), then run populate again.
- **Start backends:** Run `python scripts/start_backends.py` or `./scripts/start_services.sh` to check or start services.

### First-time backend setup

- **PostgreSQL: "role \"user\" does not exist"**  
  Homebrew Postgres on macOS uses your **OS username** as the default superuser, not `user`. In `.env` set:
  ```bash
  DATABASE_URL=postgresql://YOUR_MAC_USERNAME@localhost:5432/openfund
  ```
  (Replace `YOUR_MAC_USERNAME` with the output of `whoami`.) Create the database if needed:
  ```bash
  # If createdb is not found, add Postgres to PATH then run createdb:
  export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"   # or postgresql@15, postgresql
  createdb openfund
  # Or run the project script (tries common paths for you):
  ./scripts/create_db.sh
  ```

- **Neo4j: "Unsupported authentication token, missing key 'credentials'"**  
  Set `NEO4J_USER=neo4j` and `NEO4J_PASSWORD` to the password you configured in Neo4j. If you never set one, set it (e.g. in Neo4j Browser at http://localhost:7474 on first run, or via Neo4j docs for your install).

- **Milvus: "Fail connecting to server on localhost:19530"**  
  The default `docker run milvusdb/milvus:latest` does **not** start the Milvus server (the image runs `tini` with no command). Use the project script instead:
  ```bash
  ./scripts/start_milvus.sh
  ```
  That runs Milvus with embedded etcd and the correct `milvus run standalone` command. Wait ~30–60 seconds, then run `python -m data populate`.  
  To reuse an existing container: `docker start milvus-standalone`.
