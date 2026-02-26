# Demo Mode

Demo mode runs the full flow with **static data** (no external APIs or databases). All demo-related code lives under the **demo/** package.

## Quick start

**One command** (starts the API in the background, then opens the chat; server stops when you quit):

```bash
python -m demo
```

**Or use two terminals:**

```bash
# Terminal 1: start the API in demo mode
python main.py --demo

# Terminal 2: run the interactive chat
python -m demo.demo_chat
```

Optional: `python -m demo.demo_chat --base-url http://localhost:8000`

## What runs in demo mode

- **API:** When `OPENFUND_DEMO=1` or `--demo`, the app uses `demo.demo_client.DemoMCPClient`. The planner gets no LLM client, so it uses a fixed three-step decomposition (librarian, websearcher, analyst).
- **Backends:** SQL, KG, and vector tools use **real** PostgreSQL, Neo4j, and Milvus when `DATABASE_URL`, `NEO4J_URI`, or `MILVUS_URI` are set (e.g. after `python -m data populate`). When those env vars are not set, those tools return static data from `DEMO_RESPONSES`.
- **Static data for external APIs:** File, market, and analyst tools **always** return static data (no Tavily, Yahoo, or Analyst API calls). LLM is not used.
- **GET /demo:** Returns `{"demo": true}` when the server is in demo mode; the CLI uses this to show a "Demo mode" message.

## Run with real backends and static LLM

To use **real** PostgreSQL, Neo4j, and Milvus while keeping **static LLM** (no `LLM_API_KEY`):

1. Set `DATABASE_URL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `MILVUS_URI` (and optionally `MILVUS_COLLECTION`, `EMBEDDING_*`) in `.env`. Do **not** set `OPENFUND_DEMO`.
2. Do **not** set `LLM_API_KEY` so the planner uses fixed three steps.
3. Run **once** to seed demo data: `python -m data populate`. This seeds PostgreSQL (e.g. `funds` table with NVDA row), Neo4j (Company NVDA, Sector Technology, IN_SECTOR), and Milvus (two demo documents) so tool responses match the static demo content.
4. Start the app: `python main.py`, then use the demo chat or API.

Re-running `python -m data populate` is idempotent (Postgres: ON CONFLICT; Neo4j: MERGE; Milvus: delete by `source == "demo"` then index).

## Package layout

| File           | Purpose |
|----------------|---------|
| `demo/__main__.py` | Single-command entry: `python -m demo` — starts API in demo mode in the background, waits for readiness, runs the chat client; stops the server on quit. |
| `demo/demo_data.py`  | Static response dicts per tool name (file_tool.read_file, vector_tool.search, market_tool.*, etc.). |
| `demo/demo_client.py` | `DemoMCPClient.call_tool(tool_name, payload)`: uses real sql/kg/vector when DATABASE_URL/NEO4J_URI/MILVUS_URI are set; file, market, analyst always static. |
| `demo/demo_chat.py`   | CLI: prompt name → POST /register → chat loop (POST /chat), prints flow and response. |

See [file-structure.md](file-structure.md#demo) for module contracts.
