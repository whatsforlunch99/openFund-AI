# Plan A: Response Reranking (Idea)

## Objective

Use **offline reranking (best-of-K)** with a **reward model** to select the highest-quality final response while keeping the existing pipeline intact.

## Rationale

The system already generates responses via an LLM. Reranking avoids invasive policy changes, reduces risk, and scales with more data. We do not change how the planner or tools work—only how we choose among multiple candidate final responses.

## Policy

- **Recommended policy:** Offline reranking with a reward model.
- At inference: generate **K** candidate responses (e.g. 2–4), score each with the reward model, exclude or penalize any that fail compliance, then select the highest-scoring candidate and format/return it as today.
- Training: batch (e.g. nightly) on collected feedback; no online policy updates.

## Constraints

- Safety/compliance checks (OutputRail) remain **mandatory**; reranking runs before final formatting, and non-compliant candidates are excluded or heavily penalized.
- If no reward model is available (missing, outdated, or below quality threshold), **fall back** to the single-response path.
- No online policy updates; training is offline and batch-based.

## Main components

- **Feedback capture & storage** — What we store when users rate responses; production data shape. → [data_collection.md](data_collection.md)
- **Pipeline DAG & schemas** — Jobs (seed_symbols → generate_queries → run_conversations → judge_rewards), inputs/outputs, and exact record schemas. → [dag_and_schemas.md](dag_and_schemas.md)
- **Execution** — How to run the pipeline (CLI steps), where Responder reranking runs in the app, prerequisites. → [execution.md](execution.md)

## Out of scope

Policy fine-tuning (PPO, DPO) and online learning are **out of scope**. Plan A uses **offline reward-model reranking only** (best-of-K with a trained regression/MLP reward model).

## Assumptions

- Adjustment target is **response reranking** (not planner or tool policy).
- Feedback signal is **1–5 rating** (or judge-based scores for synthetic data until real ratings exist).
- Training runs as a **nightly batch** (or similar offline schedule).
- The system continues to rely on external LLMs for generation; RL is implemented as reward-model reranking, not policy fine-tuning.

## Test plan (summary)

- **Feedback:** Valid rating accepted for completed conversation; invalid rating or missing/incomplete conversation rejected; overwrite semantics for same (user_id, conversation_id).
- **Reranking:** With RL disabled, behavior matches current single-candidate path; with RL enabled and model loaded, highest-scored compliant candidate is chosen.
- **Training:** Script runs with synthetic feedback and writes model + manifest; model loads at runtime and produces deterministic scores.

For full test cases and API contract details, see backend/API docs when implemented.
