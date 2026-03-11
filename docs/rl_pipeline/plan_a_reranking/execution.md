# Plan A: Response Reranking (Execution)

How to **run the pipeline** and where **Responder reranking** runs in the app. For the DAG and record schemas, see [dag_and_schemas.md](dag_and_schemas.md).

---

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| **LLM API** | Configured for query generation (job 2), conversation run (job 3), and judge scoring (job 4). |
| **MCP tools** | Real tools configured (API keys, databases) so `run_conversations` can call them. |
| **OutputRail** | Compliance remains mandatory for the final response; reranking only chooses among compliant candidates. |
| **Optional (online reranking)** | `RL_ENABLED`, `RL_MODEL_PATH`, `RL_CANDIDATE_COUNT` (e.g. 3); when set and model is loaded, Responder uses reranking at inference time. |

---

## Execution steps (pipeline)

Run in order. Commands assume a CLI entrypoint such as `python -m pipeline` or `scripts/run_pipeline.py` with subcommands from [dag_and_schemas.md](dag_and_schemas.md).

| Step | Job | Command (example) | Output(s) |
|------|-----|-------------------|-----------|
| 1 | `seed_symbols` | `pipeline gen-seeds` (or equivalent) | `datasets/synth/seeds.jsonl` |
| 2 | `generate_queries` | `pipeline gen-queries` | `datasets/synth/queries.jsonl` |
| 3 | `run_conversations` | `pipeline run` | `datasets/synth/traces.jsonl`, `datasets/synth/rerank.jsonl` |
| 4 | `judge_rewards` | `pipeline judge` | `datasets/synth/trace_rewards.jsonl`, `datasets/synth/rerank_rewards.jsonl` |

1. **Generate seed symbols** from `datasets/combined_funds.json` → `seeds.jsonl`.
2. **Generate synthetic queries** from seeds + taxonomy + LLM → `queries.jsonl`.
3. **Run conversations** for each query through the existing LLM→tools→LLM flow; optionally generate K candidate responses per query. Writes `traces.jsonl` and `rerank.jsonl`.
4. **Apply judge LLM** to score responses and attach synthetic rewards → `trace_rewards.jsonl` and `rerank_rewards.jsonl`.

---

## Responder reranking (online inference)

Reranking runs **in the Responder** at request time, after the planner and specialists have produced consolidated data and the Responder would normally call the LLM once to generate the final answer.

**When `RL_ENABLED` is true and the reward model is loaded:**

1. Generate **K** candidate responses (e.g. K=3) via the LLM instead of one.
2. Run OutputRail compliance on each candidate; keep only those that pass (or penalize failures).
3. Score each compliant candidate with the reward model.
4. Select the highest-scoring candidate, then run OutputRail `format_for_user(best, user_profile)` and return that as the final response.

**When RL is disabled or the model is missing/outdated:** Use the existing single-response path (one LLM call, then format and return).

### Pseudocode (Responder)

```python
# When RL_ENABLED and model loaded:
candidates = [llm.complete(prompt_i) for i in range(K)]
safe = [c for c in candidates if output_rail.check_compliance(c).passed]
scored = [(c, reward_model.predict(query, c, user_profile)) for c in safe]
best = max(scored, key=lambda x: x[1])[0] if scored else candidates[0]
final = output_rail.format_for_user(best, user_profile)
# ... register reply, broadcast stop, etc.
```

If no candidate passes compliance, fall back to the first candidate or to a safe default (implementation choice); ensure the returned response still passes OutputRail before sending to the user.

---

## Outputs summary

| Step | Output files |
|------|--------------|
| 1. seed_symbols | `datasets/synth/seeds.jsonl` |
| 2. generate_queries | `datasets/synth/queries.jsonl` |
| 3. run_conversations | `datasets/synth/traces.jsonl`, `datasets/synth/rerank.jsonl` |
| 4. judge_rewards | `datasets/synth/trace_rewards.jsonl`, `datasets/synth/rerank_rewards.jsonl` |

Schema and field details for each file are in [dag_and_schemas.md](dag_and_schemas.md).
