# Progress

Snapshot aligned to current codebase.

## Implemented

- Live API with routes:
  - `GET /health`
  - `POST /register`
  - `POST /login`
  - `POST /chat`
  - `GET /conversations/{conversation_id}`
  - `WebSocket /ws`
- Username-based auth with uniqueness checks and password hashing
- Conversation persistence and memory context loading
- Multi-agent orchestration (planner/librarian/websearcher/analyst/responder)
- SafetyGateway and OutputRail integration
- Data manager CLI for populate/collect/distribute/backend operations
- Single operational runner script with backend + data + API + chat options

## Recently Corrected

- `data_manager sql` now JSON-serializes non-primitive result values using `default=str`
  (prevents Decimal serialization failures on `SELECT *` queries).

## Operational Reality

- `--funds existing` and `--funds fresh-all` are practical runtime modes.
- `--funds fresh-symbols` may take significantly longer depending on dataset/backends.
