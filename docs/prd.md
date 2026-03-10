# Product Requirements Document (PRD)

What the system must do and why. No API or implementation details; see [backend.md](backend.md) and [file-structure.md](file-structure.md) for those.

---

## Problem statement

Users need investment-research answers tailored to their expertise (beginner, long-term holder, or analyst). The system must accept a natural-language query, coordinate multiple research steps, and return a single, profile-appropriate response while enforcing safety and compliance.

---

## Target users

| Segment | Description | Primary need |
|--------|-------------|--------------|
| Beginner Fund Trader | New to investing | Conclusion-first, analogies, minimal jargon, clear risk warnings |
| Long-Term Equity Holder | Focus on horizons and portfolio | Industry trends, drawdown behavior, horizon-based view |
| Financial Data Analyst | Wants full rigor | Full calculation workflow, raw metrics, model assumptions, confidence intervals |

---

## Scope

**In scope**

- Single conversational interface: user sends a query and receives one final response per conversation.
- Three user profiles with distinct response formatting.
- Safety checks on input (validation, guardrails, PII handling).
- Conversation continuity (create or continue by conversation ID).
- Orchestrated research (internal specialists used as needed; one or more rounds).
- Compliance check on output before delivery.
- Time-bounded processing with explicit timeout behavior.

**Out of scope (current phase)**

- Multi-turn user dialogue within one conversation.
- Authentication/authorization beyond optional user identifier.
- Token-level streaming to the user.
- UI; API-only.

---

## Functional requirements

1. **Input:** System accepts a query string, optional user ID, optional conversation ID, and user profile (beginner | long_term | analyst). Invalid or unsupported profile is rejected.
2. **Safety:** All user input passes through validation, guardrails, and PII masking before any processing. Rejected input returns a clear error.
3. **Conversation:** System creates a new conversation when no conversation ID is supplied; otherwise retrieves existing conversation or returns not-found.
4. **Orchestration:** The orchestrator (Planner) decides which internal specialists to call (one or more) and decomposes the user query into agent-specific sub-queries. Specialists determine which tools to use and with what parameters (e.g. via LLM using prompts and tool descriptions). The Planner runs the planner sufficiency check and, when the planner sufficiency check passes, requests a final response.
5. **Response:** Only one component may produce the final user-facing answer. Response is formatted for the user’s profile and must pass compliance checks before delivery.
6. **Termination:** Conversation is marked complete when the final response is delivered. No further processing for that conversation.
7. **Timeout:** If processing exceeds the configured limit, the user receives a timeout status and no response body.

---

## Constraints

- External data (e.g. vector DB, graph, market, analyst API) is accessed only through a defined tool layer (MCP); no direct backend access from orchestration logic.
- Response formatting and compliance are mandatory before the answer is considered delivered.
- E2E processing must respect a configurable timeout (default 30 seconds).

---

## Acceptance criteria

- User can submit a query with a chosen profile and receive a profile-appropriate response or a clear error.
- User can supply a conversation ID to continue or poll; unknown ID yields not-found.
- Invalid or unsafe input is rejected with an explicit error.
- On timeout, user receives timeout status and conversation ID; no response body.
- Final response is the only user-facing output for that conversation; session lifecycle is well-defined (create → in progress → complete).

---

## Success metrics

- Correct behavior per user profile (beginner vs long_term vs analyst wording).
- All user input passes safety; blocked or invalid input is rejected.
- Timeout and error paths behave as specified (no silent failures).
- Documentation (PRD, user flow, backend, file structure, progress, project status) stays aligned with implementation.
