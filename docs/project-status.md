# Project Status Document

Tracks **major capability readiness**. Update when a capability becomes operational, changes state, is deprecated, or at release milestones. Status values: **Not Started** | **In Progress** | **Live** | **Deprecated**.

---

| Capability | Status | Notes |
|------------|--------|--------|
| Config + main entry | Live | load_config(), main() prints ready |
| In-memory MessageBus | Live | register_agent, send, receive, broadcast |
| ConversationManager | Live | create/get, register_reply, broadcast_stop, persistence |
| ACLMessage + Performative | Live | StrEnum; to_dict for persistence |
| MCP server + client + file_tool | Live | file_tool.read_file |
| BaseAgent run loop | Live | receive, STOP break, handle_message |
| PlannerAgent (stub) | Live | Slice 3: one TaskStep → Librarian; sufficiency stub 1.0 |
| LibrarianAgent | Live | file_tool; vector/kg/sql (mocks) as implemented |
| ResponderAgent | Live | register_reply, broadcast_stop; stub format/compliance |
| WebSearcherAgent | Not Started | Slice 5 |
| AnalystAgent | Not Started | Slice 5 |
| Planner full stub (3 agents) | Not Started | Slice 5: three TaskSteps, parallel REQUESTs |
| SafetyGateway | Not Started | Slice 6 |
| REST API (POST /chat, GET /conversations) | Not Started | Slice 7 |
| OutputRail (real format + compliance) | Not Started | Slice 8 |
| WebSocket /ws | Not Started | Slice 9 |
| Multi-round Planner | Not Started | Optional |
| LLM (decompose_task, sufficiency) | Not Started | Stage 10.2 / Phase 2 |
