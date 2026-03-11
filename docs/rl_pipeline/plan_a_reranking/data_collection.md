# Plan A: Response Reranking (Data Collection)

This document describes **what data we collect** for Plan A (response reranking): production user feedback and synthetic pipeline outputs. For pipeline job order and exact record schemas, see [dag_and_schemas.md](dag_and_schemas.md).

---

## 1. Production feedback

Data collected when users submit ratings via **POST /feedback** after a completed conversation.

### Minimal fields stored per feedback record

- **Identifiers:** `conversation_id`, `response_id`, `user_id` (optional), `user_profile`
- **Content:** `query`, `final_response`
- **Signal:** `rating` (1–5)
- **Metadata:** `latency_ms`, `compliance_passed`, `created_at`

### Storage and semantics

- **Where:** JSONL file or DB table (e.g. `feedback.jsonl` or a `feedback` table).
- **Overwrite:** One rating per `(user_id, conversation_id)`; later submissions overwrite the previous rating for that pair.
- **Validation:** Store only when conversation `status=complete` and `final_response` exists; reject incomplete or unknown conversations.

### Sample feedback record (production)

```json
{
  "feedback_id": "uuid",
  "conversation_id": "string",
  "response_id": "string",
  "user_id": "string",
  "user_profile": "beginner|long_term|analyst",
  "query": "string",
  "final_response": "string",
  "rating": 4,
  "comment": "optional",
  "latency_ms": 1200,
  "compliance_passed": true,
  "created_at": "ISO8601"
}
```

### Expected volumes

| Phase   | Target rated responses |
|--------|-------------------------|
| MVP    | 200–500                 |
| Stable | 2,000–5,000             |

Reranking training needs at least a minimum number of records (e.g. `RL_MIN_FEEDBACK=200`) before producing a new model.

---

## 2. Synthetic pipeline outputs

When running the **synthetic data pipeline** (see [dag_and_schemas.md](dag_and_schemas.md) and [execution.md](execution.md)), the following datasets are written under `datasets/synth/`. Exact schemas are in [dag_and_schemas.md](dag_and_schemas.md).

| File | Description |
|------|--------------|
| `seeds.jsonl` | Seed symbols/names from `combined_funds.json` (SeedRecord). |
| `queries.jsonl` | Generated queries with category and user_profile (QueryRecord). |
| `traces.jsonl` | One per conversation: planner steps, tool calls, agent outputs, final response, latency, compliance (TraceRecord). |
| `rerank.jsonl` | One per conversation when reranking is used: K candidates, selected response, final response (RerankRecord). When RL is disabled, may have a single candidate. |
| `trace_rewards.jsonl` | Judge-assigned rewards for trace records (RewardRecord, `source_id` = trace_id). |
| `rerank_rewards.jsonl` | Judge-assigned rewards for rerank candidates (RewardRecord, `source_id` = rerank_id). |

Synthetic rewards (judge LLM rubric: helpfulness, correctness, completeness, compliance) provide training labels until enough real user ratings exist. Production feedback and synthetic outputs share the same reward-related fields where applicable (e.g. rating/reward, compliance_passed).

---

## Optional: candidates for reranking training

For synthetic runs, storing **K candidates per conversation** in `rerank.jsonl` (see RerankRecord in [dag_and_schemas.md](dag_and_schemas.md)) allows training the reward model on multiple (query, response) pairs per query. Production feedback stores only the single delivered response and its rating.
