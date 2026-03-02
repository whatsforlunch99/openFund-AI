# OpenFund-AI

Open-source investment research framework: multi-agent orchestration over FIPA-ACL and MCP for natural-language investment queries, with safety, compliance, and profile-based responses.

---

## Prerequisites

- **Python 3.9+**
- **Optional (for full features):** Docker (for Milvus), PostgreSQL, Neo4j — see [Quick start (full)](#quick-start-full-with-backends) below.

You can run the app with **only an LLM API key** (no databases) and get chat plus market/analyst tools; add backends when you want vector search, knowledge graph, and SQL.

---

## Quick start (minimal: LLM only)

Fastest way to try the project without setting up databases:

```bash
# 1. Clone and install
git clone https://github.com/whatsforlunch99/openFund-AI.git
cd openFund-AI
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,llm]"

# 2. Configure LLM (required for real task decomposition)
cp .env.example .env
# Edit .env: set LLM_API_KEY=sk-your-key
# For DeepSeek: also set LLM_BASE_URL=https://api.deepseek.com and LLM_MODEL=deepseek-chat

# 3. Run API + chat
python main.py
# Or interactive chat only (if API is already running): python -m demo
```

In the chat, try: *"Should I invest in Nvidia?"* or *"What do you know about NVDA?"*

Without backends, vector/kg/SQL tools return stub or empty data; market and analyst tools work via Alpha Vantage and Finnhub (set `ALPHA_VANTAGE_API_KEY` and/or `FINNHUB_API_KEY` in `.env`).

---

## Quick start (full: with backends)

For vector search, knowledge graph, and SQL over your own data:

```bash
# 1. Clone and install (include backends)
git clone https://github.com/whatsforlunch99/openFund-AI.git
cd openFund-AI
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,backends,llm]"

# 2. One-shot setup and run
./demo/run.sh
```

On **first run**, if `.env` is missing, the script creates it and runs backend install. **Edit `.env`** (e.g. set `NEO4J_PASSWORD`, `DATABASE_URL` to your Postgres user) then run `./demo/run.sh` again. After that, `./demo/run.sh` is the only command you need: it starts Postgres/Neo4j/Milvus, seeds data, and starts the demo.

See [docs/demo.md](docs/demo.md) for backend troubleshooting (Postgres role, Neo4j auth, Milvus script).

---

## First-time setup checklist

| Step | What to do |
|------|------------|
| 1 | Install deps: `pip install -e ".[dev,llm]"` (add `backends` if using Postgres/Neo4j/Milvus). |
| 2 | Copy env: `cp .env.example .env`. |
| 3 | Set `LLM_API_KEY` in `.env` (required for live task decomposition and tool selection). |
| 4 | (Optional) Set `LLM_BASE_URL` and `LLM_MODEL` for DeepSeek or another OpenAI-compatible provider. |
| 5 | (Optional) Set `DATABASE_URL`, `NEO4J_URI`/`NEO4J_PASSWORD`, `MILVUS_URI` for full backends; run `./scripts/start_services.sh` then `python -m data_manager populate`. |

Do not commit `.env`; it is in `.gitignore`.

---

## LLM setup

The API uses a live LLM for task decomposition and agent tool selection.

1. **Install the LLM extra:**
   ```bash
   pip install -e ".[llm]"
   ```

2. **Configure in `.env`:**
   - **Required:** `LLM_API_KEY=sk-your-key`
   - **OpenAI:** leave `LLM_BASE_URL` unset; set `LLM_MODEL=gpt-4o-mini` (or another model).
   - **DeepSeek:** set `LLM_BASE_URL=https://api.deepseek.com` and `LLM_MODEL=deepseek-chat`.

3. **Run:** `python main.py` or `python -m demo` (see [Simple demo commands](#simple-demo-commands)).

---

## Simple demo commands

| What you want | Command |
|---------------|---------|
| **Run full setup** (backends + seed + chat) | `./demo/run.sh` |
| **Chat only** (API already running) | `python -m demo` |
| **Start API only** | `python main.py` |
| **Seed data** (Postgres, Neo4j, Milvus) | `python -m data_manager populate` |
| **Run tests** | `pytest tests/test-stages.py -v` |
| **Run all tests** | `pytest tests/ -v` |
| **E2E smoke** (one conversation, exit 0) | `PYTHONPATH=. python main.py --e2e-once` |
| **Test planner** (decompose query → A2A content) | `PYTHONPATH=. python scripts/test_llm_planner.py "should I invest in AAPL?"` |
| **Test librarian / websearcher / analyst** (one agent, real MCP by default) | `PYTHONPATH=. python scripts/test_websearcher.py "query"` (or `test_librarian.py`, `test_analyst.py`). Add `--mock` for stub data. |

---

## Run backends and chat separately

```bash
# Start Postgres, Neo4j, Milvus (requires .env with DATABASE_URL, NEO4J_*, MILVUS_URI)
./scripts/start_services.sh

# Seed data (optional; skip if already done)
python -m data_manager populate

# Start API + chat
python -m demo
```

---

## Architecture (short)

| Layer | Role |
|-------|------|
| **API** | REST `POST /chat`, `GET /conversations/{id}`, WebSocket `/ws` |
| **Safety** | Validate → guardrails → PII mask before processing |
| **Agents** | Planner, Librarian (vector + graph + SQL), WebSearcher, Analyst, Responder |
| **MCP** | Tools: file_tool, vector_tool (Milvus), kg_tool (Neo4j), sql_tool (Postgres), market_tool, analyst_tool, get_capabilities |

Configuration via `.env` (copy from `.env.example`). See [docs/backend.md](docs/backend.md) and [docs/demo.md](docs/demo.md).

---

## Data CLI

```bash
python -m data_manager --help
python -m data_manager populate
python -m data_manager sql "SELECT * FROM funds LIMIT 5"
python -m data_manager neo4j "MATCH (n) RETURN count(n)"
python -m data_manager milvus index docs.json
python -m data_manager milvus delete 'source == "demo"'
```

Requires `DATABASE_URL`, `NEO4J_URI`, or `MILVUS_URI` in `.env` and `pip install -e ".[backends]"`.

---

## Troubleshooting

- **No .env:** Copy from `.env.example`: `cp .env.example .env`. Run commands from the **project root** (directory containing `data_manager/` and `demo/`).
- **Postgres "role does not exist":** Use your OS username in `DATABASE_URL`, e.g. `postgresql://YOUR_MAC_USERNAME@localhost:5432/openfund`. Create DB: `createdb openfund` or `./scripts/create_db.sh`.
- **Neo4j auth:** Set `NEO4J_USER=neo4j` and `NEO4J_PASSWORD` to the password you set in Neo4j.
- **Milvus connection:** Use `./scripts/start_milvus.sh` (plain `docker run` does not start the server). Wait ~30s then `python -m data_manager populate`.

More: [docs/demo.md](docs/demo.md).

---

## Docs

| Doc | Description |
|-----|-------------|
| [docs/prd.md](docs/prd.md) | Product requirements |
| [docs/backend.md](docs/backend.md) | API contracts, timeouts |
| [docs/demo.md](docs/demo.md) | Demo flow, troubleshooting |
| [docs/agent-tools-reference.md](docs/agent-tools-reference.md) | MCP tools per agent |
| [docs/progress.md](docs/progress.md) | Slices, stages, test commands |
| [docs/file-structure.md](docs/file-structure.md) | Module layout and contracts |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes |

---

## License

See [LICENSE](LICENSE) in this repository.
