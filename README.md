# OpenFund-AI

Open-source investment research framework: multi-agent orchestration over FIPA-ACL and MCP for natural-language investment queries, with safety, compliance, and profile-based responses.

---

## Quick start

**Requirements:** Python ≥3.9.

```bash
# 1. Clone and install
git clone https://github.com/whatsforlunch99/openFund-AI.git
cd openFund-AI
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,backends]"

# 2. Run the demo (one script: setup + backends + chat)
./demo/run.sh
```

On first run, if `.env` is missing, the script creates it and runs backend install. **Edit `.env`** (e.g. set `NEO4J_PASSWORD`, `DATABASE_URL`) then run `./demo/run.sh` again. After that, `./demo/run.sh` is the only command you need.

In the chat, try: *"Should I invest in Nvidia?"* or *"What do you know about NVDA?"*

---

## Simple demo commands

| What you want | Command |
|---------------|---------|
| **Run full demo** (setup + backends + seed + chat) | `./demo/run.sh` |
| **Chat only** (backends already running) | `python -m demo` |
| **Seed demo data** (Postgres, Neo4j, Milvus) | `python -m data populate` |
| **Run tests** | `pytest tests/test-stages.py -v` |
| **Run all tests** (stages + kg/sql/vector/capabilities) | `pytest tests/ -v` |
| **E2E smoke** (one conversation, exit 0) | `PYTHONPATH=. python main.py --e2e-once` |

---

## Run backends and chat separately

```bash
# Start Postgres, Neo4j, Milvus (requires .env)
./scripts/start_services.sh

# Seed data (optional; skip if already done)
python -m data populate

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
python -m data --help
python -m data populate
python -m data sql "SELECT * FROM funds LIMIT 5"
python -m data neo4j "MATCH (n) RETURN count(n)"
python -m data milvus index docs.json
python -m data milvus delete 'source == "demo"'
```

Requires `DATABASE_URL`, `NEO4J_URI`, or `MILVUS_URI` in `.env` and `pip install -e ".[backends]"`.

---

## Docs

| Doc | Description |
|-----|-------------|
| [docs/prd.md](docs/prd.md) | Product requirements |
| [docs/backend.md](docs/backend.md) | API contracts, timeouts |
| [docs/demo.md](docs/demo.md) | Demo flow, troubleshooting |
| [docs/progress.md](docs/progress.md) | Slices, stages, test commands |
| [docs/file-structure.md](docs/file-structure.md) | Module layout and contracts |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes |

---

## License

See [LICENSE](LICENSE) in this repository.
