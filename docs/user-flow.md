# User Flow Document

Application behavioral flow from the user perspective. See [prd.md](prd.md) for requirements and [backend.md](backend.md) for API contracts.

---

## Current implementation (Slices 1–9)

The codebase implements **one round** with REST and WebSocket: `python main.py --e2e-once` runs a single conversation (api → planner → librarian + websearcher + analyst → responder). The planner sends REQUEST to all three specialists; each replies with INFORM; the planner aggregates and forwards to the responder with `final_response`; the responder formats via OutputRail, checks compliance, calls register_reply and broadcast_stop. **POST /chat** and **GET /conversations/{id}** are implemented (Slice 7). **SafetyGateway** runs on all input (Slice 6). **WebSocket /ws** (Slice 9) follows the same flow as POST /chat. The flow below applies to both REST and WebSocket.

---

## Entry points

- **Chat (new conversation):** User submits a query with optional user ID and profile. No conversation ID.
- **Chat (existing conversation):** User submits with an existing conversation ID to poll/get status for that conversation.
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

# OpenFund-AI — Use Case Flows by Target Audience

This section describes the pipeline at a **high level** (shared flow summary and audience-specific differences). For a **step-by-step function trace** of one beginner request from API entry to final response, see [use-case-trace-beginner.md](use-case-trace-beginner.md). That document aligns with [prd.md](prd.md), [backend.md](backend.md), and the function-level contracts in [file-structure.md](file-structure.md).

---

## Shared flow summary

All three audiences use the same pipeline; only the **request body** (notably `user_profile`) and the **final formatting** step differ:

1. **Layer 1 (API):** Request body → safety → conversation create/get → send to Planner → block on completion.
2. **Layer 2 (Safety):** Validate, guardrails, PII mask.
3. **A2A (Planner rounds):** Planner chooses **one or more** of LibrarianAgent, WebSearcherAgent, and AnalystAgent in **each round**. It sends REQUEST(s) to the chosen agent(s); each replies with INFORM to Planner. If the collected information is **not sufficient**, Planner starts a **new round** using **new queries generated from all current information** at hand, and may again choose one or more agents. When sufficient, Planner sends REQUEST to Responder with consolidated data.
4. **Research execution:** Librarian (vector + graph + sql), WebSearcher (market + sentiment + regulatory), Analyst (run_analysis / local metrics)—each only when chosen that round.
5. **Layer 6 (Output):** Responder evaluates confidence, formats via OutputRail using **user_profile**, checks compliance, registers final response, broadcasts STOP.
6. **API** unblocks and returns JSON.

For a step-by-step function trace of one beginner request, see [use-case-trace-beginner.md](use-case-trace-beginner.md).

---

# 1. Beginner Fund Trader

**Delivery:** Conclusion-first, analogies, minimal jargon, risk warnings.

## Sample input

```json
{
  "query": "Is fund X safe for someone like me who’s new to investing?",
  "user_profile": "beginner",
  "user_id": "user_123"
}
```

Optional: `conversation_id` omitted for a new conversation.

For the full function call sequence (steps 1–11 from API to response), see [use-case-trace-beginner.md](use-case-trace-beginner.md).

---

# 2. Long-Term Equity Holder — differences only

**Delivery:** Industry trends, portfolio/drawdown focus.

The **function call sequence is the same** as in §1 (steps 1–11). Only the following differ:

- **Sample input:** `query` = e.g. `"How does fund X behave in drawdowns and over a 10-year horizon?"`, `user_profile` = `"long_term"`, `user_id` = e.g. `"user_456"`.
- **Step 4:** `content["user_profile"]` = `"long_term"`.
- **Step 10:** `ResponderAgent.format_response(analysis, "long_term")` → `OutputRail.format_for_user(text, "long_term")` adapts tone and content for long-term holders (industry trend, drawdown, horizon).
- **Step 11:** Response JSON contains the long-term–oriented formatted answer.

---

# 3. Financial Data Analyst — differences only

**Delivery:** Full calculation workflow, raw metrics, model assumptions, confidence intervals.

The **function call sequence is the same** as in §1 (steps 1–11). Only the following differ:

- **Sample input:** `query` = e.g. `"Give me Sharpe, max drawdown, and a Monte Carlo distribution for fund X."`, `user_profile` = `"analyst"`, `user_id` = e.g. `"analyst_99"`.
- **Step 4:** `content["user_profile"]` = `"analyst"`.
- **Step 10:** `ResponderAgent.format_response(analysis, "analyst")` → `OutputRail.format_for_user(text, "analyst")` preserves or highlights full workflow, raw API-style metrics, and confidence intervals.
- **Step 11:** Response JSON contains the analyst-oriented answer (full metrics, assumptions, intervals).

(When Analyst agent is chosen in a round, it may return richer structure from `analyze` / `analyst_tool.run_analysis`; the flow and step count are unchanged.)

---

## Summary table: same flow, different inputs and formatting

| Step | Component | Function(s) called | Beginner | Long-term | Analyst |
|------|-----------|--------------------|----------|-----------|---------|
| 1 | api/rest | POST /chat handler, body validation | ✓ | ✓ | ✓ |
| 2 | safety | SafetyGateway.process_user_input | query text | query text | query text |
| 3 | a2a | create_conversation or get_conversation | ✓ | ✓ | ✓ |
| 4 | a2a | MessageBus.send(REQUEST → planner) | user_profile=beginner | user_profile=long_term | user_profile=analyst |
| 5 | api/rest | completion_event.wait(timeout) | ✓ | ✓ | ✓ |
| 6–9 | agents | **Planner rounds:** choose one or more of Librarian, WebSearcher, Analyst; send REQUEST(s); collect INFORM(s); if insufficient, new round with new queries from all current info; when sufficient → Responder | ✓ | ✓ | ✓ |
| 10 | agents + output | Responder.evaluate_confidence, should_terminate; format_response → **OutputRail.format_for_user(_, user_profile)**; check_compliance; register_reply; broadcast_stop | beginner wording | long_term wording | analyst wording |
| 11 | api/rest | Return { conversation_id, status, response, flow } | ✓ | ✓ | ✓ |

