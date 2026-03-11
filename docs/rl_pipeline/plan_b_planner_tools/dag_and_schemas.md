# Plan B: Planner + Tools Optimization (DAG + Schemas)

Single source of truth for the **pipeline DAG** and **all record schemas** for Plan B. For what data we collect and where, see [data_collection.md](data_collection.md). For how to run the pipeline, see [execution.md](execution.md). Plan B does not produce rerank.jsonl or rerank_rewards.jsonl (those are Plan A).

---

## Data flow

```mermaid
flowchart LR
  subgraph inputs [Inputs]
    funds[combined_funds.json]
  end
  subgraph job1 [Job 1]
    J1[seed_symbols]
  end
  subgraph job2 [Job 2]
    J2[generate_queries]
  end
  subgraph job3 [Job 3]
    J3[plan_rerank_execute]
  end
  subgraph job4 [Job 4]
    J4[judge_rewards]
  end
  funds --> J1
  J1 --> seeds[seeds.jsonl]
  seeds --> J2
  J2 --> queries[queries.jsonl]
  queries --> J3
  J3 --> traces[traces.jsonl]
  traces --> J4
  J4 --> trace_rewards[trace_rewards.jsonl]
```

---

## DAG (jobs, inputs, outputs)

All paths under `datasets/synth/` unless noted. IDs (e.g. `query_id`, `trace_id`) are UUIDs or conversation_id + run identifier where one record per conversation is required.

### Job 1: `seed_symbols`

| | |
|--|--|
| **Input** | `datasets/combined_funds.json` |
| **Output** | `datasets/synth/seeds.jsonl` |
| **Record type** | SeedRecord |

Extracts symbol/name/kind from the combined funds file into one JSONL record per symbol. Same as Plan A.

### Job 2: `generate_queries`

| | |
|--|--|
| **Inputs** | `datasets/synth/seeds.jsonl`, taxonomy config, LLM client |
| **Output** | `datasets/synth/queries.jsonl` |
| **Record type** | QueryRecord |

LLM-driven query generation using seeds and a fixed taxonomy (e.g. fund_compare, risk_profile, drawdown, valuation, macro_impact). One QueryRecord per generated query. Same as Plan A.

### Job 3: `plan_rerank_execute`

| | |
|--|--|
| **Inputs** | `datasets/synth/queries.jsonl`, LLM client, MCP client (real tools), reward model, system config |
| **Output** | `datasets/synth/traces.jsonl` |
| **Record type** | TraceRecord |

For each query: (1) Generate **K** alternative planner plans (decompositions) using the LLM. (2) Score each plan with the reward model. (3) **Execute only the best plan** (full LLM→tools→LLM flow: dispatch to agents, run tools, get final response). (4) Capture one TraceRecord per conversation (planner_steps, tool_calls, agent_outputs, final_response, compliance_passed, latency_ms). No rerank.jsonl in Plan B.

### Job 4: `judge_rewards`

| | |
|--|--|
| **Inputs** | `datasets/synth/traces.jsonl`, judge LLM |
| **Output** | `datasets/synth/trace_rewards.jsonl` |
| **Record type** | RewardRecord |

Reads traces and scores each trace (e.g. final response or full trace) using the judge LLM rubric. One RewardRecord per trace; `source_id` = trace_id, `response_id` optional (e.g. null for trace-level reward). Reward is numeric 0–1; rubric sub-scores: helpfulness, correctness, completeness, compliance.

---

## Schemas

Each record type is defined once. Use these for JSONL read/write and validation.

### SeedRecord

One per symbol from the seed source. Same as Plan A.

```json
{
  "symbol": "string",
  "name": "string",
  "kind": "fund|equity",
  "source": "combined_funds.json"
}
```

| Field | Description |
|-------|-------------|
| `symbol` | Ticker or fund identifier. |
| `name` | Display name. |
| `kind` | `fund` or `equity`. |
| `source` | Origin file (e.g. `combined_funds.json`). |

---

### QueryRecord

One per generated query. `query_id` links to downstream traces. Same as Plan A.

```json
{
  "query_id": "string",
  "query": "string",
  "user_profile": "beginner|long_term|analyst",
  "category": "fund_compare|risk_profile|drawdown|valuation|macro_impact",
  "seed_symbols": ["string"],
  "created_at": "ISO8601"
}
```

| Field | Description |
|-------|-------------|
| `query_id` | Unique ID; links to TraceRecord. |
| `query` | Natural-language query text. |
| `user_profile` | beginner, long_term, or analyst. |
| `category` | Taxonomy category. |
| `seed_symbols` | Symbols used to generate this query. |
| `created_at` | ISO8601 timestamp. |

---

### TraceRecord

One per conversation. Full planner/tool trace for training the reward model and for judge scoring. `trace_id` = UUID or conversation_id + run id.

```json
{
  "trace_id": "string",
  "query_id": "string",
  "conversation_id": "string",
  "user_profile": "beginner|long_term|analyst",
  "query": "string",
  "planner_steps": [
    { "agent": "librarian|websearcher|analyst", "query": "string" }
  ],
  "tool_calls": [
    {
      "tool": "string",
      "payload": {},
      "result_summary": { "keys": ["string"], "error": "string|null" },
      "duration_ms": "number"
    }
  ],
  "agent_outputs": {
    "librarian": { "summary": "string", "data": {} },
    "websearcher": { "summary": "string", "data": {} },
    "analyst": { "summary": "string", "data": {} }
  },
  "final_response": "string",
  "compliance_passed": "boolean",
  "latency_ms": "number",
  "created_at": "ISO8601"
}
```

| Field | Description |
|-------|-------------|
| `trace_id` | Unique ID; referenced by RewardRecord (source_id). |
| `query_id` | Links to queries.jsonl. |
| `conversation_id` | Conversation UUID from the run. |
| `planner_steps` | Decomposed steps (agent + query per step). |
| `tool_calls` | Tool name, payload, result summary, duration. |
| `agent_outputs` | Per-agent summary and data. |
| `final_response` | Final response text. |
| `compliance_passed` | OutputRail compliance result. |
| `latency_ms` | End-to-end latency. |

---

### RewardRecord

One per scored trace. Used for training the reward model. `reward_id` = UUID; `source_id` = trace_id; `response_id` = null for trace-level reward.

```json
{
  "reward_id": "string",
  "source_id": "string",
  "query_id": "string",
  "response_id": "string|null",
  "scores": {
    "helpfulness": "number",
    "correctness": "number",
    "completeness": "number",
    "compliance": "number"
  },
  "reward": "number",
  "judge_model": "string",
  "created_at": "ISO8601"
}
```

| Field | Description |
|-------|-------------|
| `source_id` | trace_id (for trace_rewards.jsonl). |
| `response_id` | Optional; null for trace-level reward. |
| `scores` | Rubric sub-scores (0–1 or equivalent). |
| `reward` | Aggregate reward (0–1). |
| `judge_model` | Judge LLM identifier. |

---

## Code layout (minimal)

Same pattern as Plan A. The runner (or a dedicated planner_runner) implements "generate K plans, score with reward model, execute best plan, write TraceRecord."

| Path | Purpose |
|------|---------|
| `pipeline/__init__.py` | Package init. |
| `pipeline/schemas.py` | Dataclasses + JSONL read/write for SeedRecord, QueryRecord, TraceRecord, RewardRecord. |
| `pipeline/seeds.py` | Read `combined_funds.json`, emit SeedRecord JSONL. |
| `pipeline/query_gen.py` | LLM-driven query generation + taxonomy. |
| `pipeline/runner.py` | For Plan B: generate K planner plans, score, execute best, capture TraceRecord; or a separate `pipeline/planner_runner.py`. |
| `pipeline/tracing_mcp.py` | MCPClient wrapper to record tool calls and results. |
| `pipeline/judge.py` | Judge LLM prompt + scoring logic → RewardRecord. |
| `pipeline/cli.py` | Subcommands: `gen-seeds`, `gen-queries`, `run` (or `plan-rerank-run`), `judge`. |
| `scripts/run_pipeline.py` | Thin entrypoint that calls `pipeline.cli`. |

---

## Test plan

1. **gen-seeds:** Builds valid SeedRecord JSONL from `combined_funds.json`.
2. **gen-queries:** Produces valid QueryRecord JSONL with taxonomy coverage.
3. **plan_rerank_execute (run):** Produces TraceRecord with required fields, planner_steps, tool_calls, and agent_outputs logged.
4. **judge:** Emits RewardRecord with 0–1 reward and rubric sub-scores; source_id = trace_id.
5. Schema validation for each JSONL file.

---

## Assumptions

- Real MCP tools are configured (API keys, DBs) for plan_rerank_execute.
- LLM API is available for query generation, planner (K plans), and judge scoring.
- Data is stored as JSONL under `datasets/synth/` for simplicity.
