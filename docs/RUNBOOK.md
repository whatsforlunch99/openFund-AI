# Runbook

Operational reference for running, monitoring, troubleshooting, and recovering OpenFund-AI services.

## Deployment / Startup Procedures

### Standard startup (macOS/Linux)

```bash
./scripts/run.sh --no-chat
```

### Standard startup (Windows PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 --no-chat
```

### Direct API startup (without runner)

```bash
python main.py --serve --port 8000
```

## Health Checks

<!-- AUTO-GENERATED: API endpoints from api/rest.py -->
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | `GET` | Returns MCP registered tools and `llm_configured` status. |
| `/register` | `POST` | Register a new username/password account. |
| `/login` | `POST` | Authenticate user and preload memory context. |
| `/chat` | `POST` | Run planner-driven multi-agent research for one request. |
| `/conversations/{conversation_id}` | `GET` | Poll conversation state and final response. |
| `/ws` | `WEBSOCKET` | WebSocket chat flow endpoint. |
<!-- END AUTO-GENERATED -->

Quick check:

```bash
python scripts/check_health.py --port 8000
curl -s http://127.0.0.1:8000/health
```

## Common Issues and Fixes

- LLM not configured
  - Symptom: health check fails with `llm_configured=false`
  - Fix: set `LLM_API_KEY` in `.env`, install `pip install -e ".[llm]"`
- Backend data missing
  - Symptom: empty retrieval results from librarian/websearch paths
  - Fix: run `python scripts/data_loader.py --load-mode existing`
- Slow or timed out chat
  - Symptom: `POST /chat` returns `408`
  - Fix: increase `E2E_TIMEOUT_SECONDS`, inspect provider latency, poll `GET /conversations/{id}`
- Neo4j/Milvus local startup problems
  - Fix: run API with `--no-backends`, or start dependencies manually then retry

## Rollback Procedures

### Code rollback

1. Identify last known good commit.
2. Deploy/restart API from that commit.
3. Re-run health checks.

```bash
git checkout <known-good-commit>
python main.py --serve --port 8000
python scripts/check_health.py --port 8000
```

### Data rollback / reset

- For full reload of loader-owned data:

```bash
python scripts/data_loader.py --load-mode fresh-all
```

## Alerting and Escalation

- Primary runtime signal: `/health` status and chat timeout rate
- Escalate when:
  - API cannot start
  - `/health` repeatedly fails
  - sustained `POST /chat` timeout spikes
  - backend connectors fail after retries/restarts
- First response checklist:
  - verify env vars
  - verify local/remote backend availability
  - run health checks
  - capture logs and failing request IDs/conversation IDs

