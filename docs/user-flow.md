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

This document describes, for each target audience, a **sample input** and the **sequence of function calls** from API entry to final response. It aligns with [prd.md](prd.md), [backend.md](backend.md), and the function-level contracts in [file-structure.md](file-structure.md).

---

## Shared flow summary

All three audiences use the same pipeline; only the **request body** (notably `user_profile`) and the **final formatting** step differ:

1. **Layer 1 (API):** Request body → safety → conversation create/get → send to Planner → block on completion.
2. **Layer 2 (Safety):** Validate, guardrails, PII mask.
3. **A2A (Planner rounds):** Planner chooses **one or more** of LibrarianAgent, WebSearcherAgent, and AnalystAgent in **each round**. It sends REQUEST(s) to the chosen agent(s); each replies with INFORM to Planner. If the collected information is **not sufficient**, Planner starts a **new round** using **new queries generated from all current information** at hand, and may again choose one or more agents. When sufficient, Planner sends REQUEST to Responder with consolidated data.
4. **Research execution:** Librarian (vector + graph + sql), WebSearcher (market + sentiment + regulatory), Analyst (run_analysis / local metrics)—each only when chosen that round.
5. **Layer 6 (Output):** Responder evaluates confidence, formats via OutputRail using **user_profile**, checks compliance, registers final response, broadcasts STOP.
6. **API** unblocks and returns JSON.

Below: **one full example** (Beginner) with the exact function call sequence; then **differences only** for the other two audiences.

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

## Function call sequence (in order)

1. **API (REST)**  
   - Request hits `POST /chat` handler in the FastAPI app created by `api/rest.create_app()`.  
   - Handler validates body (query required; user_profile one of beginner | long_term | analyst; user_id optional, default `""`).

2. **SafetyGateway.process_user_input(raw_input)**  
   - `raw_input` = `body["query"]` (e.g. `"Is fund X safe for someone like me who's new to investing?"`).  
   - Internally: `SafetyGateway.validate_input(text)` → `SafetyGateway.check_guardrails(text)` → `SafetyGateway.mask_pii(text)`.  
   - Returns `ProcessedInput` or raises `SafetyError` → HTTP 400.

3. **Conversation create or get**  
   - If `body["conversation_id"]` absent: `ConversationManager.create_conversation(user_id, initial_query)` with `user_id = body.get("user_id", "")`, `initial_query = processed.text`; returns `conversation_id`.  
   - If present: `ConversationManager.get_conversation(conversation_id)`; if None → 404.

4. **Send to Planner**  
   - Build `ACLMessage(performative="request", sender="api", receiver="planner", content={ "query": processed.text, "conversation_id": conversation_id, "user_profile": "beginner" })`.  
   - `MessageBus.send(message)`.

5. **Block for completion**  
   - Get `ConversationState` for `conversation_id`; call `state.completion_event.wait(timeout=<configured_timeout_seconds>)` (default 30s).  
   - On timeout: return HTTP 408 `{ "status": "timeout", "conversation_id": "...", "response": null, "flow": [...] }`.  
   - When unblocked: read `state.final_response`; return 200 `{ "conversation_id", "status", "response": state.final_response, "flow": [...] }`.

— **Agent threads (parallel to the above):** —

6. **PlannerAgent.handle_message(message)**  
   - Receives REQUEST from API (or from a prior round).  
   - Reads `message.content["query"]`, `message.content["conversation_id"]`, `message.content["user_profile"]`, and any accumulated context.

7. **Planner decides round:** For this round, Planner chooses **one or more** of Librarian, WebSearcher, Analyst (e.g. via `decompose_task` or sufficiency logic). It may send to all three, to two, or to one, depending on the query and current information.  
   - **PlannerAgent.decompose_task(query)** (or equivalent) returns a list of `TaskStep`s; each step targets one agent (`librarian` | `websearcher` | `analyst`).  
   - For each chosen step: `PlannerAgent.create_research_request(query, step, context)` where `context` holds all information gathered so far (empty on first round).  
   - **MessageBus.send("request")** for each chosen agent (one or more of librarian, websearcher, analyst), each with the same conversation_id and round-specific query/step in content.

8. **Chosen agents run (this round); each replies INFORM to Planner.**  
   - **LibrarianAgent.handle_message(message)** (if chosen): `retrieve_documents` → `MCPClient.call_tool("vector_tool.search", ...)`; `retrieve_knowledge_graph` → `MCPClient.call_tool("kg_tool.query_graph", ...)`; `MCPClient.call_tool("sql_tool.run_query", ...)`; `combine_results(docs, graph_data)`; **MessageBus.send("inform")** to planner.  
   - **WebSearcherAgent.handle_message(message)** (if chosen): `fetch_market_data`, `fetch_sentiment`, `fetch_regulatory` via market_tool; all returns include `timestamp`; **MessageBus.send("inform")** to planner.  
   - **AnalystAgent.handle_message(message)** (if chosen): receives structured_data/market_data (from context or prior round); `analyze(...)`; optionally `MCPClient.call_tool("analyst_tool.run_analysis", ...)`; **MessageBus.send("inform")** to planner.

9. **PlannerAgent** (after collecting INFORM replies for this round)  
   - Aggregates results from whichever agents replied this round with all prior-round data.  
   - Decides **sufficiency** according to planner policy/heuristics.  
   - **If sufficient:** **MessageBus.send("request")** to `responder` with consolidated payload (including `user_profile`, `conversation_id`).  
   - **If not sufficient:** starts a **new round**: generates **new queries** from **all current information** at hand, then goes back to step 7 (choose one or more agents again, send REQUEST(s), wait for INFORM(s), re-evaluate sufficiency). Repeat until sufficient, then send to Responder.

10. **ResponderAgent.handle_message(message)**  
    - Receives REQUEST with consolidated analysis and `message.content["user_profile"]` = `"beginner"`, `message.content["conversation_id"]`.  
    - `ResponderAgent.evaluate_confidence(analysis)` computes confidence from the analysis payload.  
    - `ResponderAgent.should_terminate(confidence)` decides whether to finalize or request refinement.  
    - **When terminating:** Responder sends the final reply to the user (not to Planner): formats, checks compliance, registers the reply so the API can return it, then broadcasts STOP so all agents (including Planner) know the conversation is complete.  
      - `ResponderAgent.format_response(analysis, user_profile)` → internally `OutputRail.format_for_user(draft_text, "beginner")` (conclusion-first, analogies, risk wording).  
      - `OutputRail.check_compliance(final_text)` → `ComplianceResult`.  
      - `ConversationManager.register_reply(conversation_id, ACLMessage(... performative="inform" ... final_response ...))`; implementation sets `state.final_response` and `state.completion_event.set()` (API returns this to the user).  
      - `ConversationManager.broadcast_stop(conversation_id)` → `MessageBus.broadcast(ACLMessage(performative="stop", ...))` so all agent threads exit; this is the conversation-complete signal.  
    - **When not terminating:** build refinement request to Planner and `MessageBus.send("request")` to planner.

11. **API** (blocking caller)  
    - Unblocks on `completion_event.set()`.  
    - Reads `state.final_response` and flow events; returns JSON `{ "conversation_id", "status", "response": "<formatted answer for beginner>", "flow": [...] }`.

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

