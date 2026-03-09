# Backend

Current server behavior for `main.py`, `api/rest.py`, and `api/websocket.py`.

## Runtime

- Primary API start: `python main.py --serve --port 8000`
- One-shot E2E: `python main.py --e2e-once`
- Non-serve init only: `python main.py --no-serve`
- Recommended operator entrypoint: `./scripts/run.sh`

## API Endpoints

### `GET /health`
Returns:
- `tools`: registered MCP tool names
- `llm_configured`: whether LLM client is available

### `POST /register`
Body:
- `username` (or fallback `display_name`)
- `password` (min length 8)

Rules:
- Username regex: `^[A-Za-z][A-Za-z0-9_.-]{2,31}$`
- Username must be unique

Success `200`:
- `user_id`, `username`, `message`

Failures:
- `422` invalid username format
- `409` username already exists

### `POST /login`
Body:
- `username` (preferred) or `user_id` (legacy)
- `password`

Success `200`:
- `user_id`, `username`, `message`, `loaded_conversations`, `has_memory_context`

Failure:
- `401` invalid credentials

### `POST /chat`
Body:
- `query` (required)
- `user_profile` in `beginner | long_term | analyst`
- optional `user_id`
- optional `conversation_id`

Flow:
1. Validate body
2. Run safety gateway
3. Create or resume conversation
4. Dispatch planner request on message bus
5. Wait for responder completion event

Success `200`:
- `conversation_id`, `status`, `response`, `flow`

Timeout `408`:
- `status=timeout`, `conversation_id`, `response=null`, `flow`

Other failures:
- `400` safety failure
- `404` unknown conversation (resume path)
- `422` body validation

### `GET /conversations/{conversation_id}`
- `200` serialized conversation state
- `404` if not found

### `WebSocket /ws`
- Same orchestration semantics as `/chat`
- Accepts one JSON request payload and returns terminal response event

## Persistence

- Conversation memory root: `MEMORY_STORE_PATH` (default `memory/`)
- User credentials: `memory/users.json`
- User conversation history: `memory/<user_id>/conversations.json`
- Anonymous history: `memory/anonymous/conversations.json`

## Core Orchestration

- Message bus: `InMemoryMessageBus`
- Agents: planner, librarian, websearcher, analyst, responder
- Planner dispatches specialist tasks and forwards consolidated result to responder
- Responder writes final reply via `ConversationManager.register_reply()` and triggers STOP broadcast
