# File Structure

Current high-level structure of the repository.

## Top-Level Modules

- `main.py`: process entrypoint (`--serve`, `--no-serve`, `--e2e-once`)
- `a2a/`: ACL message types, message bus, conversation manager
- `agents/`: planner/librarian/websearcher/analyst/responder
- `api/`: REST + WebSocket API layer
- `mcp/`: MCP server/client + backend tools
- `data_manager/`: collection/distribution/maintenance CLI
- `memory/`: situation memory + persisted conversation data
- `llm/`: LLM client factory + prompt assets
- `output/`: output formatting/compliance rail
- `safety/`: input validation, guardrails, PII masking
- `util/`: logging and interaction tracing helpers

## Scripts

Current scripts under `scripts/`:
- `run.sh`
- `stop.sh`
- `chat_cli.py`
- `check_health.py`
- `test_librarian.py`
- `milvus/` helper scripts

## Data + Docs

- `datasets/`: JSON datasets (including `combined_funds.json`)
- `output/`: generated export artifacts
- `docs/`: project documentation

## API Source of Truth

- REST routes: `api/rest.py`
- WebSocket handler: `api/websocket.py`
- Startup wiring: `main.py` and `api/rest.py:create_app`

## Data Schema Source of Truth

- `data_manager/schemas.py`
- `docs/fund-data-schema.md` (human-facing summary)
