# Project Status

Status legend: `Live`, `Partial`, `Planned`.

| Capability | Status | Notes |
|---|---|---|
| API server (`main.py --serve`) | Live | FastAPI app factory in `api/rest.py` |
| Auth (`/register`, `/login`) | Live | Username uniqueness + password hash verification |
| Chat orchestration (`/chat`) | Live | Planner-driven multi-agent flow |
| Conversation retrieval (`/conversations/{id}`) | Live | Serialized conversation state |
| WebSocket chat (`/ws`) | Live | Shared orchestration path with REST |
| Safety pipeline | Live | `SafetyGateway.process_user_input()` |
| Output compliance/formatting | Live | `OutputRail` in responder flow |
| Data manager CLI | Live | `python -m data_manager` subcommands |
| Auto-run script (`scripts/run.sh`) | Live | Backend/data/API/chat orchestration |
| Dedicated frontend app | Planned | Not present in repo |
