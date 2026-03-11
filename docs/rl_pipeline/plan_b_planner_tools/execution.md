# Plan B: Planner + Tools Optimization (Execution)

How to **run the pipeline** and where **Planner reranking** runs in the app. For the DAG and record schemas, see [dag_and_schemas.md](dag_and_schemas.md).

---

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| **LLM API** | Configured for query generation (job 2), planner (K candidate plans in job 3), and judge scoring (job 4). |
| **MCP tools** | Real tools configured (API keys, databases) so plan_rerank_execute can run the full flow. |
| **OutputRail** | Compliance is enforced on the final response from the executed plan. |
| **Optional (online planner reranking)** | `RL_ENABLED`, `RL_MODEL_PATH`, `RL_PLAN_CANDIDATE_COUNT` (K, e.g. 2–4); when set and model is loaded, Planner uses reranking at inference time. |

---

## Execution steps (pipeline)

Run in order. Commands assume a CLI entrypoint such as `python -m pipeline` or `scripts/run_pipeline.py` with subcommands from [dag_and_schemas.md](dag_and_schemas.md).

| Step | Job | Command (example) | Output(s) |
|------|-----|-------------------|-----------|
| 1 | `seed_symbols` | `pipeline gen-seeds` | `datasets/synth/seeds.jsonl` |
| 2 | `generate_queries` | `pipeline gen-queries` | `datasets/synth/queries.jsonl` |
| 3 | `plan_rerank_execute` | `pipeline run` or `pipeline plan-rerank-run` | `datasets/synth/traces.jsonl` |
| 4 | `judge_rewards` | `pipeline judge` | `datasets/synth/trace_rewards.jsonl` |

1. **Generate seed symbols** from `datasets/combined_funds.json` → `seeds.jsonl`.
2. **Generate synthetic queries** from seeds + taxonomy + LLM → `queries.jsonl`.
3. **Plan rerank and execute:** For each query, generate K alternative planner plans, score each with the reward model, execute only the best plan (full LLM→tools→LLM flow), capture one TraceRecord → `traces.jsonl`.
4. **Apply judge LLM** to score traces and attach synthetic rewards → `trace_rewards.jsonl`.

---

## Planner reranking (online inference)

Planner reranking runs **in the Planner** before any agents are dispatched. Instead of calling the LLM once to get a single decomposition, the Planner generates K candidate plans, scores them with the reward model, and dispatches only the best one.

**When `RL_ENABLED` is true and the reward model is loaded:**

1. Generate **K** candidate decompositions (e.g. K=2–4) via the LLM.
2. Score each plan with the reward model (e.g. predict_plan(query, plan, user_profile)).
3. Select the highest-scoring plan.
4. Dispatch the best plan to the agents (librarian, websearcher, analyst) and run the rest of the flow as today.

**When RL is disabled or the model is missing:** Use the existing single-call planner path (one LLM decompose, then dispatch).

### Pseudocode (Planner)

```python
# When RL_ENABLED and model loaded:
plans = [llm.decompose(query) for _ in range(K)]
scored = [(p, reward_model.predict_plan(query, p, profile)) for p in plans]
best_plan = max(scored, key=lambda x: x[1])[0]
dispatch(best_plan)
# ... agents run, tools execute, Responder produces final response
```

---

## Outputs summary

| Step | Output files |
|------|--------------|
| 1. seed_symbols | `datasets/synth/seeds.jsonl` |
| 2. generate_queries | `datasets/synth/queries.jsonl` |
| 3. plan_rerank_execute | `datasets/synth/traces.jsonl` |
| 4. judge_rewards | `datasets/synth/trace_rewards.jsonl` |

Plan B does not produce rerank.jsonl or rerank_rewards.jsonl. Schema and field details are in [dag_and_schemas.md](dag_and_schemas.md).
