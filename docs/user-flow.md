# User Flow Document

Application behavioral flow from the user perspective. See [prd.md](prd.md) for requirements and [backend.md](backend.md) for API contracts.

---

## Entry points

- **Chat (new conversation):** User submits a query with optional user ID and profile. No conversation ID.
- **Chat (continue conversation):** User submits with an existing conversation ID to continue or get status.
- **Get conversation:** User requests current state of a conversation by ID.

---

## Target audiences (user_profile)

| user_profile | Audience | Delivery focus |
|--------------|----------|----------------|
| `beginner` | Beginner Fund Trader | Conclusion-first, analogies, minimal jargon, risk warnings |
| `long_term` | Long-Term Equity Holder | Industry trends, portfolio/drawdown focus |
| `analyst` | Financial Data Analyst | Full workflow, raw metrics, model assumptions, confidence intervals |

Invalid or unknown `user_profile` is rejected before processing.

---

## Navigation paths and state transitions

1. **User submits query** → System validates input (safety and format).
2. **If validation fails** → User receives error; no conversation created. (Error state.)
3. **If valid, no conversation ID** → New conversation created; request enters processing.
4. **If valid, with conversation ID** → Existing conversation looked up; if not found, user receives not-found error.
5. **Request in processing** → Orchestrator gathers information from internal specialists (one or more rounds as needed).
6. **When information is sufficient** → Response is formatted for the user’s profile, checked for compliance, and finalized.
7. **User receives** → Success: conversation ID, status, and response. Session for that request is complete.
8. **Timeout** → User receives timeout status and conversation ID; no response body.

---

## Decision branches

- **Validation:** Accept vs reject input (e.g. blocked phrases, invalid profile).
- **Conversation:** Create new vs continue existing (by presence of conversation ID).
- **Orchestration:** One round vs multiple rounds of specialist calls depending on sufficiency of information.
- **Termination:** Responder either finalizes the answer (conversation complete) or requests more work from the orchestrator.

---

## Authentication boundaries

- `user_id` is optional; when absent, treated as anonymous. Auth-header extraction is a later phase. No authentication required for current entry points.

---

## Error states

- **Validation / safety failure:** Request rejected; user gets error (e.g. HTTP 400).
- **Unknown conversation ID:** User gets not-found (e.g. HTTP 404).
- **Timeout:** Processing exceeds limit; user gets timeout status (e.g. HTTP 408), no response body.

---

## Session lifecycle

- **Start:** First request without conversation ID creates a conversation and starts processing.
- **In progress:** Same conversation ID can be used to poll or wait for completion.
- **Complete:** When the final response is ready, the conversation is marked complete and the user receives the response. No further processing for that conversation.
- **Termination:** Only the responder can signal conversation complete; all internal processing for that conversation then stops.

---

## Summary: same flow, different profiles

All three audiences follow the same path; only the **request** (notably `user_profile`) and the **final response formatting** differ (beginner vs long_term vs analyst wording).
