# RL Pipeline Plans (Collated)

This folder contains two plans organized by abstraction layer. Each plan has idea, data collection, execution, and DAG/schema documents.

## Plans

- [Plan A: Response Reranking](plan_a_reranking/idea.md)
- [Plan B: Planner + Tools Optimization](plan_b_planner_tools/idea.md)

## Key Differences (Summary)

- Plan A optimizes the final response by reranking candidate answers.
- Plan B optimizes planner decomposition and tool usage before execution.
- Plan A requires minimal data: query, response, rating, and basic metadata.
- Plan B requires richer traces: planner steps, tool calls, and agent outputs.
- Plan A can start with 200–500 rated samples for MVP.
- Plan B typically needs 1,000–2,000 traced samples for MVP.
- Both plans use offline reranking policies for safety and stability.

## File Layout

- `plan_a_reranking/idea.md`
- `plan_a_reranking/data_collection.md`
- `plan_a_reranking/execution.md`
- `plan_a_reranking/dag_and_schemas.md`
- `plan_b_planner_tools/idea.md`
- `plan_b_planner_tools/data_collection.md`
- `plan_b_planner_tools/execution.md`
- `plan_b_planner_tools/dag_and_schemas.md`
