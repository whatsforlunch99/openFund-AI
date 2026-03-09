# User Flow

Current end-to-end flow for REST and WebSocket chat.

## Entry

- Register: `POST /register`
- Login: `POST /login`
- Chat: `POST /chat` or `WebSocket /ws`

## Chat Lifecycle

1. User submits query + profile (+ optional user_id, conversation_id).
2. API validates request.
3. Safety gateway processes input.
4. Conversation is created or resumed.
5. Planner request is published on bus.
6. Specialists execute tool-backed research.
7. Planner decides sufficiency and forwards final package.
8. Responder formats/compliance-checks final text.
9. Conversation reply is persisted and returned to user.

## Profiles

- `beginner`: simple language and caution framing
- `long_term`: horizon-oriented framing
- `analyst`: denser technical framing

## State Outcomes

- `200`: completed response
- `408`: timeout before completion
- `400/422/404`: validation/safety/not-found failures

## CLI-Driven User Path

`./scripts/run.sh` starts API and (unless `--no-chat`) launches terminal chat client:
- `scripts/chat_cli.py`
