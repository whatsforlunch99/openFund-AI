# Plan B: Planner + Tools Optimization (Data Collection)

This document describes **what data we collect** for Plan B (planner and tool optimization): extended production feedback (traces) and synthetic pipeline outputs. For pipeline job order and exact record schemas, see [dag_and_schemas.md](dag_and_schemas.md).

---

## 1. Production feedback (extended)

Plan B extends feedback to include **trace data** so rewards can be attributed to planner decisions and tool usage. Data is collected from flow events and interaction logs when users submit ratings (e.g. POST /feedback) or when conversations complete.

### Required fields (Plan A plus trace fields)

- **Identifiers:** `conversation_id`, `response_id`, `user_id` (optional), `user_profile`, `planner_trace_id`
- **Content:** `query`, `final_response`
- **Trace:** `planner_steps` (agent + query per step), `tool_calls` (tool name, payload, result summary, duration_ms), `agent_outputs` (summaries and structured data per agent)
- **Signal:** `rating` (1–5) or composite reward components
- **Metadata:** `latency_ms`, `compliance_passed`, optional `tool_errors`, `created_at`

### Storage and semantics

- **Where:** JSONL or DB; one **trace record** per conversation (or one feedback row linking to a stored trace via `planner_trace_id`).
- **Overwrite:** Same as Plan A for rating per (user_id, conversation_id); trace is stored or updated when the conversation completes.
- **Validation:** Store only when conversation is complete and trace is available; reject incomplete or unknown conversations.

### Expected volumes

| Phase   | Target traced conversations |
|--------|------------------------------|
| MVP    | 1,000–2,000                 |
| Stable | 5,000–20,000                |

Plan B needs more traced conversations than Plan A’s rated responses because credit assignment requires full planner/tool traces.

---

## 2. Synthetic pipeline outputs

When running the **synthetic data pipeline** (see [dag_and_schemas.md](dag_and_schemas.md) and [execution.md](execution.md)), the following datasets are written under `datasets/synth/`. Exact schemas are in [dag_and_schemas.md](dag_and_schemas.md). Plan B does **not** produce rerank.jsonl or rerank_rewards.jsonl (those are Plan A).

| File | Description |
|------|-------------|
| `seeds.jsonl` | Seed symbols/names from `combined_funds.json` (SeedRecord). |
| `queries.jsonl` | Generated queries with category and user_profile (QueryRecord). |
| `traces.jsonl` | One per conversation: planner steps, tool calls, agent outputs, final response, latency, compliance (TraceRecord). |
| `trace_rewards.jsonl` | Judge-assigned rewards for each trace (RewardRecord; source_id = trace_id). |

Production and synthetic both store trace-shaped data for credit assignment. Synthetic rewards (judge LLM rubric) provide training labels until enough real user ratings exist.
