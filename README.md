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

## Quick start

**Requirements:** Python ≥3.9

```bash
# Clone and enter project
git clone https://github.com/whatsforlunch99/openFund-AI.git
cd openFund-AI

# Optional: create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows

# Install (dev deps for tests)
pip install -e ".[dev]"

# Optional: install backend drivers (Neo4j, PostgreSQL, Milvus + embeddings)
# Required for real backends and for the data CLI (create/update/delete).
pip install -e ".[backends]"
# Or: pip install neo4j psycopg2-binary pymilvus sentence-transformers
```

**Run tests:**

```bash
pytest tests/test-stages.py -v
# Or a single stage: pytest tests/test-stages.py -k stage_2_1 -v
```

---

## Commands to run

Copy-paste reference for common tasks.

| Task | Commands |
|------|----------|
| **Install (dev + backends)** | `pip install -e ".[dev]"` then `pip install -e ".[backends]"` |
| **Run tests** | `pytest tests/test-stages.py -v` |
| **Run demo** (one command) | `python -m demo` |
| **Run demo** (two terminals) | Terminal 1: `python main.py --demo` — Terminal 2: `python -m demo.demo_chat` |
| **Run real API** | `python main.py` |
| **Run demo chat vs API** | `python -m demo.demo_chat --base-url http://localhost:8000` |
| **Seed demo data into backends** | `python -m data populate` |
| **Data CLI help** | `python -m data --help` |
| **SQL query** | `python -m data sql "SELECT * FROM funds LIMIT 5"` |
| **Neo4j query** | `python -m data neo4j "MATCH (n) RETURN count(n)"` |
| **Milvus index** | `python -m data milvus index docs.json` |
| **Milvus delete** | `python -m data milvus delete 'fund_id == "F1"'` |

See sections below for full context (env vars, two-terminal demo, real backends + static LLM).

---

## Run demo (static data, no backends)

Use demo mode to try the full flow. **SQL, KG, and vector** use real backends (PostgreSQL, Neo4j, Milvus) when configured and seeded with `python -m data populate`; **file, market, analyst, and LLM** stay static (no external APIs or keys).

**One command** (starts the API in the background, then opens the chat):

```bash
python -m demo
```

When you type `quit` or `exit`, the server stops. Run from the project root. With no backend env vars set, all tool responses are static.

**Alternatively**, use two terminals:

```bash
# Terminal 1: start the API in demo mode
python main.py --demo

# Terminal 2: run the interactive chat
python -m demo.demo_chat
```

You’ll be prompted for your name, then can ask questions (e.g. “should I invest in Nvidia?”). Each reply shows the system flow and the final answer. See [docs/demo.md](docs/demo.md).

---

## Run real project (with backends)

When you have **PostgreSQL**, **Neo4j**, and/or **Milvus** running, set the corresponding env vars in `.env` (see [.env.example](.env.example)), then start the API and use the chat.

```bash
# 1. Copy and edit env (set DATABASE_URL, NEO4J_URI, MILVUS_URI, etc.)
cp .env.example .env
# Edit .env with your connection strings.

# 2. Install backend drivers (if not already)
pip install -e ".[backends]"

# 3. Start the API (loads .env automatically)
python main.py

# 4. In another terminal: chat via API or run the demo chat against the real API
python -m demo.demo_chat --base-url http://localhost:8000
# Or: curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"query":"..."}'
```

---

## Backend data services (create, modify, delete)

The **data** CLI lets you **input, update, and delete** data in PostgreSQL, Neo4j, and Milvus from the command line. Use it to seed or maintain backends. Requires `.env` with the right `DATABASE_URL`, `NEO4J_URI`, or `MILVUS_URI`, and `pip install -e ".[backends]"`.

```bash
# From the project root (or set PYTHONPATH=. if not installed in editable mode)
python -m data --help
```

### PostgreSQL (sql)

Run any SQL (SELECT, INSERT, UPDATE, DELETE). Set `DATABASE_URL` in `.env`.

```bash
# Select
python -m data sql "SELECT * FROM funds LIMIT 5"

# Insert (use params to avoid injection)
python -m data sql "INSERT INTO funds (id, name) VALUES (%(id)s, %(name)s)" --params id=F1 name="Fund One"

# Update
python -m data sql "UPDATE funds SET name = %(name)s WHERE id = %(id)s" --params id=F1 name="Fund One Updated"

# Delete
python -m data sql "DELETE FROM funds WHERE id = %(id)s" --params id=F1
```

### Neo4j (neo4j)

Run any Cypher (CREATE, MERGE, SET, DELETE, MATCH). Set `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` in `.env`.

```bash
# Create nodes
python -m data neo4j "CREATE (f:Fund {id: $id, name: $name})" --params id=F1 name="Fund One"

# Query
python -m data neo4j "MATCH (f:Fund) RETURN f.id, f.name LIMIT 5"

# Update (SET)
python -m data neo4j "MATCH (f:Fund {id: $id}) SET f.name = $name" --params id=F1 name="Updated"

# Delete
python -m data neo4j "MATCH (f:Fund {id: $id}) DETACH DELETE f" --params id=F1
```

### Milvus (vector store)

**Index** documents from a JSON file (each doc: `content`, optional `fund_id`, `source`). **Delete** by filter expression. Set `MILVUS_URI`, and optionally `MILVUS_COLLECTION`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` in `.env`.

```bash
# Create / add documents (file: array of {"content": "text...", "fund_id": "X", "source": "fact_sheet"})
echo '[{"content": "Fund X overview...", "fund_id": "F1", "source": "fact_sheet"}]' > docs.json
python -m data milvus index docs.json

# Delete by expression (e.g. by id or fund_id)
python -m data milvus delete 'id in ["uuid-1", "uuid-2"]'
python -m data milvus delete 'fund_id == "F1"'
```

See [data_prep/neo4j_postgres_milvus_integration.md](data_prep/neo4j_postgres_milvus_integration.md) for schema and data-model guidance.

---

## Run with real backends and static LLM

You can run the app against **real PostgreSQL, Neo4j, and Milvus** while keeping **LLM responses static** (no API key). Tool responses then come from the real backends, and the planner uses a fixed three-step decomposition.

1. **Set backend env vars** in `.env` (do **not** set `OPENFUND_DEMO` so `demo=False` and real MCP is used):
   - `DATABASE_URL` — PostgreSQL connection string
   - `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` — Neo4j
   - `MILVUS_URI`, and optionally `MILVUS_COLLECTION`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`

2. **Do not set `LLM_API_KEY`** if you want static planner responses (fixed three steps; no OpenAI calls). When `LLM_API_KEY` is unset, `get_llm_client` returns `StaticLLMClient`.

3. **Seed demo data once:**
   ```bash
   python -m data populate
   ```
   This creates/updates the `funds` table and inserts NVDA, creates Neo4j nodes/edges (Company NVDA, Sector Technology, IN_SECTOR), and indexes the two demo documents in Milvus so tool responses match the static demo content.

4. **Start the app and use the demo chat or API:**
   ```bash
   python main.py
   python -m demo.demo_chat --base-url http://localhost:8000
   ```


## Project structure

```
├── agents/          # Planner, Librarian, WebSearcher, Analyst, Responder (BaseAgent)
├── a2a/             # ACLMessage, MessageBus, ConversationManager
├── api/             # REST and WebSocket (FastAPI)
├── data/            # Data services CLI: create/update/delete in PostgreSQL, Neo4j, Milvus
├── demo/            # Demo mode: static data, CLI chat (demo_data, demo_client, demo_chat)
├── safety/          # SafetyGateway
├── output/          # OutputRail
├── mcp/             # MCPClient, MCPServer, tools (file, vector, kg, market, analyst, sql)
├── config/          # Config, load_config()
├── main.py          # Entry point
├── tests/           # test-stages.py (per-stage tests)
└── docs/            # PRD, backend, progress, project-status, test plan
```

Full file layout and per-module contracts: [docs/file-structure.md](docs/file-structure.md).

---

## Documentation

| Doc | Description |
|-----|--------------|
| [docs/prd.md](docs/prd.md) | Product requirements, user segments, scope |
| [docs/backend.md](docs/backend.md) | API contracts, data models, persistence, timeouts |
| [docs/demo.md](docs/demo.md) | Demo mode: static data, CLI chat, demo/ package |
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
