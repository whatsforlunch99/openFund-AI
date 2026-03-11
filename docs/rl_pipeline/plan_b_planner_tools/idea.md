# Plan B: Planner + Tools Optimization (Idea)

## Objective

Optimize **planner decomposition and tool usage** using offline reranking policies that score alternative plans **before** execution. Generate K candidate plans, score each with a reward model, execute only the best plan.

## Rationale

Planner decisions dominate downstream quality and cost. Improving which agents and tools are invoked yields better evidence and safer responses. We do not change how agents or tools work internally—only how we choose among multiple candidate decompositions.

## Policy

- **Recommended policy:** Offline reranking of multiple planner plans using a reward model.
- At inference: Planner generates **K** alternative decompositions (e.g. 2–4), reward model scores each plan, we **execute only the top plan** (full LLM→tools→LLM flow).
- Training: batch (e.g. nightly) on traced conversations and ratings; reward model trained on (query, steps, tools, response) to predict user rating or composite reward.

## Constraints

- **No online policy updates;** training remains offline.
- Safety/compliance (OutputRail) and timeouts must be preserved; the executed plan still runs through the same compliance checks.
- When RL is disabled or the model is missing, fall back to existing deterministic planner behavior.

## Main components

- **Feedback & trace capture** — What we store per conversation (planner_steps, tool_calls, agent_outputs, ratings); production vs synthetic. → [data_collection.md](data_collection.md)
- **Pipeline DAG & schemas** — Jobs (seed_symbols → generate_queries → plan_rerank_execute → judge_rewards), inputs/outputs, and exact record schemas. → [dag_and_schemas.md](dag_and_schemas.md)
- **Execution** — How to run the pipeline (CLI steps), where Planner reranking runs in the app, prerequisites. → [execution.md](execution.md)

## Out of scope

Online policy updates and policy gradient methods (e.g. PPO) are **out of scope**. Plan B uses **offline plan reranking only** (best-of-K plans with a trained reward model); no fine-tuning of the planner or agent policies.

## Assumptions

- RL scope targets **Planner + tools** (which plans to execute), not final-response reranking (that is Plan A).
- Reward can combine **rating + safety + latency** (composite reward); training data includes **queries + traces + ratings** for credit assignment.
- Initial RL is offline and uses reranking for safety; no online policy updates.

## Test plan (summary)

- **Reward calculation:** Rating normalization, compliance penalty, latency penalty, timeout penalty (and any composite formula).
- **Logging:** Planner steps, tool calls, and agent outputs are stored with each conversation and linked via planner_trace_id.
- **Planner reranking:** With RL enabled, higher-reward plan is chosen; otherwise fallback to single deterministic plan.
- **Data integrity:** Feedback record links to correct conversation and planner trace.

For full test cases and API details, see backend/API docs when implemented.
