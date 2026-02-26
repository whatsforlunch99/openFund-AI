# Project Status Document

Tracks **major capability readiness**. Update when a capability becomes operational, changes state, is deprecated, or at release milestones. Status values: **Not Started** | **In Progress** | **Live** | **Deprecated**.

---

| Capability | PRD | Status | Notes |
|------------|-----|--------|--------|
| Config + main entry | — | Live | load_config(), main() prints ready |
| In-memory MessageBus | — | Live | register_agent, send, receive, broadcast |
| ConversationManager | FR3, AC2 | Live | create/get, register_reply, broadcast_stop, persistence |
| ACLMessage + Performative | — | Live | (str, Enum) for Python 3.9; to_dict for persistence |
| MCP server + client + file_tool | C1 | Live | file_tool.read_file; register_default_tools skips market_tool/analyst_tool if imports fail |
| BaseAgent run loop | — | Live | receive, STOP break, handle_message; exits cleanly on STOP |
| PlannerAgent (stub) | FR4 | Live | Slice 3: one TaskStep → librarian; forwards INFORM to responder; sufficiency stub 1.0 |
| LibrarianAgent | FR4 | Live | Slice 3: file_tool.read_file only; vector/kg/sql stubs |
| ResponderAgent | FR5, FR6 | Live | Slice 3 stub: register_reply, broadcast_stop on INFORM with final_response; format/compliance not yet |
| E2E one conversation | — | Live | `python main.py --e2e-once` (planner → librarian → responder, temp file for file_tool) |
| WebSearcherAgent | FR4 | Not Started | Slice 5 |
| AnalystAgent | FR4 | Not Started | Slice 5 |
| Planner full stub (3 agents) | FR4 | Not Started | Slice 5: three TaskSteps, parallel REQUESTs |
| SafetyGateway | FR1, FR2, AC3 | Live | Slice 6: validate_input, check_guardrails, mask_pii, process_user_input; test_stage_6_1 |
| REST API (POST /chat, GET /conversations) | FR1, AC1, AC2 | Not Started | Slice 7 |
| OutputRail (real format + compliance) | FR5, C2 | Not Started | Slice 8 |
| WebSocket /ws | — | Not Started | Slice 9 |
| Multi-round Planner | FR4 (optional) | Not Started | Optional |
| LLM (decompose_task, sufficiency) | — | Not Started | Stage 10.2 / Phase 2 |
