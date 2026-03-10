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
| PlannerAgent orchestration | FR4 | Live | Decomposition + specialist dispatch; planner sufficiency check (LLM-based); refined planner round(s) up to MAX_RESEARCH_ROUNDS |
| LibrarianAgent | FR4 | Live | MCP retrieval (file/vector/kg/sql), LLM tool selection when llm_client is set, fallback content-key dispatch |
| ResponderAgent | FR5, FR6 | Live | register_reply, broadcast_stop; OutputRail format_for_user + check_compliance by user_profile (Slice 8) |
| E2E one conversation | — | Live | `python main.py --e2e-once` (planner + librarian + websearcher + analyst + responder; static LLM fallback in e2e path) |
| WebSearcherAgent | FR4 | Live | Slice 5: fetch_market_data, fetch_sentiment, fetch_regulatory via market_tool |
| AnalystAgent | FR4 | Live | Slice 5: analyze, needs_more_data, sharpe_ratio, max_drawdown, monte_carlo_simulation |
| Planner specialist fan-out | FR4 | Live | Sends REQUESTs to librarian/websearcher/analyst, aggregates INFORMs, forwards consolidated result to responder |
| SafetyGateway | FR1, FR2, AC3 | Live | Slice 6: validate_input, check_guardrails, mask_pii, process_user_input; test_stage_6_1 |
| REST API (register/login/chat/conversations) | FR1, AC1, AC2 | Live | create_app with POST /register, POST /login, POST /chat, GET /conversations/{id} |
| OutputRail (real format + compliance) | FR5, C2 | Live | Slice 8: check_compliance, format_for_user; Responder uses OutputRail; user_profile API → planner → responder |
| WebSocket /ws | — | Live | Slice 9: /ws same flow as POST /chat; events response/timeout/error; test_stage_9_1 |
| Multi-round Planner | FR4 (optional) | Live | Implemented with LLM sufficiency and capped refinement rounds (MAX_RESEARCH_ROUNDS) |
| LLM (decompose_task, sufficiency, tool selection) | — | Live | Runtime API path requires LLM_API_KEY + llm extra; StaticLLMClient is explicit test/e2e fallback |
