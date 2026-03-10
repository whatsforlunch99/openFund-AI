# Use-Case Trace (Beginner)

Trace of one beginner request through current code.

## Input

`POST /chat`

```json
{
  "query": "I am new to investing. How risky is this fund?",
  "user_profile": "beginner",
  "user_id": "alice"
}
```

## Execution Path

1. `api/rest.py:post_chat_endpoint` validates body (`ChatRequest`).
2. `SafetyGateway.process_user_input()` runs validation + guardrails + masking.
3. `ConversationManager.load_user_conversations("alice")` and memory-context fetch.
4. New or existing conversation is resolved.
5. API sends ACL `REQUEST` to `planner` over message bus.
6. Planner decomposes and dispatches specialist requests.
7. Librarian/WebSearcher/Analyst return `INFORM` payloads.
8. Planner consolidates and sends to responder.
9. Responder formats via `OutputRail` (from safety), registers reply, broadcasts STOP.
10. API unblocks on `completion_event` and returns response payload.

## Success Response Shape

```json
{
  "conversation_id": "<uuid>",
  "status": "complete",
  "response": "...",
  "flow": []
}
```

## Error Paths

- Validation error: `422`
- Safety rejection: `400`
- Conversation resume not found: `404`
- Timeout waiting for completion: `408`
