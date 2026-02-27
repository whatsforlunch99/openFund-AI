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
| ResponderAgent | FR5, FR6 | Live | register_reply, broadcast_stop; OutputRail format_for_user + check_compliance by user_profile (Slice 8) |
| E2E one conversation | — | Live | `python main.py --e2e-once` (planner → librarian → responder, temp file for file_tool) |
| WebSearcherAgent | FR4 | Live | Slice 5: fetch_market_data, fetch_sentiment, fetch_regulatory via market_tool |
| AnalystAgent | FR4 | Live | Slice 5: analyze, needs_more_data, sharpe_ratio, max_drawdown, monte_carlo_simulation |
| Planner full stub (3 agents) | FR4 | Live | Slice 5: three TaskSteps, parallel REQUESTs to librarian, websearcher, analyst |
| SafetyGateway | FR1, FR2, AC3 | Live | Slice 6: validate_input, check_guardrails, mask_pii, process_user_input; test_stage_6_1 |
| REST API (POST /chat, GET /conversations) | FR1, AC1, AC2 | Live | Slice 7: create_app, POST /chat, GET /conversations/{id}; test_stage_7_1 |
| OutputRail (real format + compliance) | FR5, C2 | Live | Slice 8: check_compliance, format_for_user; Responder uses OutputRail; user_profile API → planner → responder |
| WebSocket /ws | — | Live | Slice 9: /ws same flow as POST /chat; events response/timeout/error; test_stage_9_1 |
| Multi-round Planner | FR4 (optional) | Not Started | Optional |
| LLM (decompose_task, sufficiency) | — | In Progress | Stage 10.2: static mock live; set LLM_API_KEY + pip install [llm] for live OpenAI |
