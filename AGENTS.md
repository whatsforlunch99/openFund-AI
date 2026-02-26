# AGENTS.md

## Cursor Cloud specific instructions

### Overview

OpenFund-AI is a pure-Python multi-agent investment research framework. No external services (databases, Docker, etc.) are required — all stubs are mocked in tests.

### Quick reference

| Action | Command |
|--------|---------|
| Install deps | `pip install -e ".[dev]"` |
| Run app | `PYTHONPATH=. python3 main.py` |
| Run E2E conversation | `PYTHONPATH=. python3 main.py --e2e-once` |
| Run tests | `pytest tests/test-stages.py -v` |
| Lint (ruff) | `ruff check .` |
| Format check (black) | `black --check .` |

See `README.md` for full documentation links.

### Non-obvious notes

- Use `python3` not `python` — the VM does not symlink `python` to `python3`.
- `PYTHONPATH=.` is required when running `main.py` because the project uses namespace-style packages (`a2a/`, `agents/`, `mcp/`, etc.) resolved relative to the repo root.
- `pip install -e ".[dev]"` installs to `~/.local` (user site-packages) since system site-packages is not writable. The `~/.local/bin` directory must be on `PATH` for `pytest`, `ruff`, and `black` CLI tools. Run `export PATH="$HOME/.local/bin:$PATH"` if needed.
- Pre-existing lint issues (import sort order in `main.py` and `a2a/message_bus.py`, format specifier style in `main.py`) are in the repo baseline — do not treat as regressions.
- Stages 4–9 tests are skipped because those features are not yet implemented (stubs only). Only stages 1–3 tests are expected to pass.
