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

# Run entry point (config load + ready message)
PYTHONPATH=. python main.py
```

**Run tests:**

```bash
pytest tests/test-stages.py -v
# Or a single stage: pytest tests/test-stages.py -k stage_2_1 -v
```

---

## Project structure

```
├── agents/          # Planner, Librarian, WebSearcher, Analyst, Responder (BaseAgent)
├── a2a/             # ACLMessage, MessageBus, ConversationManager
├── api/             # REST and WebSocket (FastAPI)
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
