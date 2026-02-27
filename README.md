# OpenFund-AI

**Open-source investment research framework** — multi-agent orchestration over FIPA-ACL and MCP for natural-language investment queries, with safety, compliance, and profile-based responses.

---

## What it does

Users submit a **natural-language query** and receive a **single, profile-appropriate answer** per conversation. The system:

- **Orchestrates** specialist agents (Planner, Librarian, WebSearcher, Analyst, Responder) over a message bus
- **Enforces** input validation, guardrails, and PII handling before any processing
- **Uses MCP** as the only path to external data (vector DB, knowledge graph, market data, analyst API)
- **Formats** responses by user profile (beginner, long-term holder, analyst) and runs compliance checks before delivery

Target users: beginner fund traders, long-term equity holders, and financial data analysts. See [docs/prd.md](docs/prd.md) for requirements and scope.

---

## First-time setup and run (3 steps)

**Requirements:** Python ≥3.9, macOS or Linux (scripts use Homebrew and Docker for backends).

### Step 1: Clone and install

```bash
git clone https://github.com/whatsforlunch99/openFund-AI.git
cd openFund-AI

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev,backends]"
```

### Step 2: Run the demo (one script)

From the project root:

```bash
chmod +x demo/run.sh
./demo/run.sh
```

- **First run:** If `.env` is missing, the script creates it and runs backend installation (Postgres, Neo4j, Milvus via Homebrew/Docker). It then asks you to **edit `.env`** (set `NEO4J_PASSWORD`, and `DATABASE_URL` user to your Mac username if needed) and run `./demo/run.sh` again.
- **Second run (after editing .env):** Starts Postgres/Neo4j/Milvus, creates the DB and seeds demo data, then starts the API and opens the chat. Type `quit` or `exit` to stop.

### Step 3: Use the demo

In the chat, try: *"Should I invest in Nvidia?"* or *"What do you know about NVDA?"* The demo uses real backends (SQL, graph, vector) when configured; file/market/analyst use static data. No API keys required for the static-LLM demo.

**Summary:** Install once (`pip install -e ".[dev,backends]"`), then run `./demo/run.sh`. Edit `.env` when prompted and run again once. After that, `./demo/run.sh` is the only command you need to start the demo.

---

## Run the demo (later runs)

If backends are already installed and `.env` is set:

```bash
./demo/run.sh
```

Or start backends and chat separately:

```bash
./scripts/start_services.sh
python -m data populate   # only if you haven’t seeded yet
python -m demo
```

---

## Architecture

| Layer | Role |
|-------|------|
| **API** | REST (`POST /chat`, `GET /conversations/{id}`) and WebSocket `/ws` |
| **Safety** | Single entry: validate → guardrails → PII mask |
| **A2A** | FIPA-ACL messages, in-memory MessageBus, ConversationManager (create/get, broadcast STOP) |
| **Agents** | Planner (orchestrator), Librarian (vector + graph + SQL), WebSearcher (market/sentiment), Analyst (quant), Responder (final answer + compliance) |
| **MCP** | Server/client; tools: `file_tool`, `vector_tool` (Milvus), `kg_tool` (Neo4j), `market_tool` (Tavily/Yahoo), `analyst_tool` (custom API), `sql_tool` |
| **Output** | OutputRail: compliance check and profile-based formatting |

All agent communication is ACL-only; only the Responder may trigger conversation termination (STOP). Configuration via environment variables; see [docs/backend.md](docs/backend.md).

**Environment:** Copy [.env.example](.env.example) to `.env` and set your values. The app loads `.env` automatically (python-dotenv). `.env` is gitignored.

---

## Commands (reference)

| Task | Command |
|------|---------|
| **Run demo (setup + start + chat)** | `./demo/run.sh` |
| **Run demo (chat only, backends already running)** | `python -m demo` |
| **Install backends + create .env** | `./scripts/install_backends.sh` |
| **Start Postgres, Neo4j, Milvus** | `./scripts/start_services.sh` |
| **Create Postgres DB `openfund`** | `./scripts/create_db.sh` |
| **Seed demo data** | `python -m data populate` |
| **Run tests** | `pytest tests/test-stages.py -v` |
| **Check/start backends (Python)** | `python scripts/start_backends.py` (optional `--check-only`) |
| **Data CLI** | `python -m data --help` (sql, neo4j, milvus index/delete) |

---

## Demo package (`demo/`)

| File | Purpose |
|------|---------|
| **run.sh** | Single entry: first-time setup (install backends, .env), start services, seed data, run `python -m demo`. Run from project root. |
| **__main__.py** | `python -m demo`: starts API in demo mode, then interactive chat; server stops on quit. |
| **demo_client.py** | DemoMCPClient: real SQL/KG/vector when env set; file/market/analyst static. |
| **demo_data.py** | Static response data for tools when backends are not used. |
| **demo_chat.py** | Chat CLI (POST /chat loop). |

See [docs/demo.md](docs/demo.md) for troubleshooting (Postgres role, Neo4j password, Milvus connection).

---

## Backend data services (data CLI)

The **data** CLI creates, updates, and deletes data in PostgreSQL, Neo4j, and Milvus. Requires `.env` with `DATABASE_URL`, `NEO4J_URI`, or `MILVUS_URI`, and `pip install -e ".[backends]"`.

```bash
python -m data --help
```

- **PostgreSQL:** Set `DATABASE_URL`. Example: `python -m data sql "SELECT * FROM funds LIMIT 5"`.
- **Neo4j:** Set `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`. Example: `python -m data neo4j "MATCH (n) RETURN count(n)"`.
- **Milvus:** Set `MILVUS_URI`. Start Milvus with `./scripts/start_milvus.sh`. Index/delete: `python -m data milvus index docs.json`, `python -m data milvus delete 'fund_id == "F1"'`.

See [data_prep/neo4j_postgres_milvus_integration.md](data_prep/neo4j_postgres_milvus_integration.md) for schema guidance.

---

## Project structure

```
├── agents/     # Planner, Librarian, WebSearcher, Analyst, Responder (BaseAgent)
├── a2a/        # ACLMessage, MessageBus, ConversationManager
├── api/        # REST and WebSocket (FastAPI)
├── data/       # Data CLI: populate, sql, neo4j, milvus (Postgres, Neo4j, Milvus)
├── demo/       # Demo: run.sh (setup+run), python -m demo (API + chat)
├── scripts/    # install_backends.sh, start_services.sh, start_milvus.sh, create_db.sh
├── safety/     # SafetyGateway
├── output/     # OutputRail
├── mcp/        # MCPClient, MCPServer, tools (file, vector, kg, market, analyst, sql)
├── config/     # Config, load_config()
├── main.py     # Entry point (--e2e-once, --demo, or config load)
├── tests/      # test-stages.py (per-stage tests)
└── docs/       # PRD, backend, demo, progress, project-status, file-structure
```

Full layout and per-module contracts: [docs/file-structure.md](docs/file-structure.md).

---

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/prd.md](docs/prd.md) | Product requirements, user segments, scope |
| [docs/backend.md](docs/backend.md) | API contracts, data models, persistence, timeouts |
| [docs/demo.md](docs/demo.md) | Demo flow, troubleshooting (Postgres, Neo4j, Milvus) |
| [docs/progress.md](docs/progress.md) | Slices/stages, runnable commands, test matrix |
| [docs/project-status.md](docs/project-status.md) | Capability status (Live / Not Started) |
| [docs/file-structure.md](docs/file-structure.md) | Module and file responsibilities |
| [CHANGELOG.md](CHANGELOG.md) | User-visible and notable changes |

---

## Status and roadmap

- **Live:** Config, MessageBus, ConversationManager, ACLMessage, MCP server/client, `file_tool.read_file`, BaseAgent, Planner (stub), Librarian (file_tool), Responder (stub).
- **In progress:** Staged implementation (slices 2–10); see [docs/progress.md](docs/progress.md) and [docs/project-status.md](docs/project-status.md).
- **Planned:** REST/WebSocket API, SafetyGateway, OutputRail, full E2E with five agents; optional LLM for decompose/sufficiency (Phase 2).

---

## License

See [LICENSE](LICENSE) in this repository (add a file if not present).
