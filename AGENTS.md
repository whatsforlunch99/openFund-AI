# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

OpenFund-AI is a Python-based (3.9+) multi-agent investment research framework. See `README.md` for full docs.

### Virtual environment

All commands must run inside the `.venv` virtual environment:

```bash
source /workspace/.venv/bin/activate
```

### Key commands

| Task | Command |
|------|---------|
| Run tests | `pytest tests/ -v` |
| Run stage tests | `pytest tests/test-stages.py -v` |
| Lint (ruff) | `ruff check .` |
| Format check | `black --check .` |
| Type check | `mypy .` |
| E2E smoke (no LLM key) | `PYTHONPATH=. python main.py --e2e-once` |
| Start API server | `python main.py --serve` (requires `LLM_API_KEY` in `.env`) |

### Running without LLM_API_KEY

- `python main.py` (default mode) loads config and exits. Works without any API keys.
- `python main.py --e2e-once` runs the full agent pipeline using `StaticLLMClient` fallback. Works without API keys.
- `python main.py --serve` starts the FastAPI server but **requires** `LLM_API_KEY` in `.env`. Without it, the app raises `RuntimeError` at startup.
- To test the API without an LLM key, use `httpx.AsyncClient` with `ASGITransport` and pass `llm_client=StaticLLMClient()` to `create_app()`.

### Optional external services

PostgreSQL, Neo4j, and Milvus are optional. Without them, the corresponding tools (`sql_tool`, `kg_tool`, `vector_tool`) return stub/empty data. The core pipeline (planner, librarian, websearcher, analyst, responder) works without any backends.

### Pre-existing lint/test issues

- `ruff check .` reports ~28 import-sorting warnings (fixable with `--fix`). These are pre-existing.
- `black --check .` reports ~34 files needing reformatting. These are pre-existing.
- 2 tests in `tests/test_agent_tools_reference.py` fail due to missing `SAMPLE_PAYLOADS` for `market_tool.get_fundamentals`. Pre-existing.
