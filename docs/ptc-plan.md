# Programmatic Tool Calling (PTC) — Tool‑Calling Loop + Central Executor

## Summary
Implement an OpenAI‑compatible tool‑calling loop for Librarian. The LLM decides tool calls, a centralized executor inside `MCPClient` validates and executes them, and the agent orchestrates the loop until no tool calls remain. This aligns with production patterns: LLM reasoning → tool execution → orchestration.

## Implementation Changes
1. Tool schema generation (OpenAI‑compatible)
   - Add a helper (inside `openfund_mcp/mcp_client.py`) to build OpenAI tool schemas from existing MCP `TOOL_SPECS`.
   - Schema fields:
     - `name`: MCP tool name (e.g., `vector_tool.search`)
     - `description`: short generic description (or derived from tool docstring if accessible)
     - `parameters`: JSON schema inferred from `arg_specs` and `required_keys`
   - Inference rules:
     - `coerce is int` → `integer`
     - `default is bool` → `boolean`
     - `default is list` → `array`
     - fallback → `string`
   - Allow passing an `allowed_tools` set (Librarian + registered tools).

2. Centralized tool executor inside MCPClient
   - Add a `ToolExecutor` (or methods on `MCPClient`) that:
     - Validates tool name is in a whitelist.
     - Validates payload is a dict and includes required keys (based on `TOOL_SPECS`).
     - Executes `call_tool(tool_name, payload)`.
     - Returns structured result `{ "success": bool, "data": result, "error": "...?" }` for LLM tool messages, while preserving raw tool data for agent aggregation.

3. Librarian tool‑calling loop (LLM reasoning + orchestration)
   - In `agents/librarian_agent.py`, when `llm_client` is set:
     - Build `messages` with system prompt and user content.
     - Supply `tools` from MCPClient’s schema helper.
     - Call the LLM with `tools` + `tool_choice="auto"` and capture `tool_calls`.
     - For each tool call:
       - Execute via MCPClient ToolExecutor.
       - Append a tool message with structured result (`role="tool"`, `tool_name`, JSON content).
     - Repeat until no tool calls or `MAX_TOOL_ROUNDS` reached.
   - If no tool calls were produced, or the loop errors, fall back to:
     - current LLM tool‑selection JSON path, then
     - current content‑key dispatch.
   - Aggregate tool results as before (combine_results, optional summary).

4. LLM client support
   - Extend `LiveLLMClient` with a `tool_call_step(messages, tools)` helper that:
     - Calls OpenAI‑compatible chat with `tools` + `tool_choice="auto"`.
     - Returns message and tool_calls.
   - Keep `LLMClient` protocol unchanged by using `hasattr` in Librarian (fallback if not supported).

5. Config + guardrails
   - Add runtime limits:
     - `LLM_TOOL_MAX_ROUNDS` (e.g., default 3)
     - `LLM_TOOL_MAX_CALLS_PER_ROUND` (default 5)
   - Ensure whitelist = (agent allowed tool set) ∩ (registered tools).
   - Ensure tool results with errors are returned as `{success: False, error: ...}` to the LLM so it can adapt.

## Test Plan
1. Unit tests for MCPClient ToolExecutor:
   - Valid tool call executes and returns structured result.
   - Unknown tool or missing args returns structured error.
2. Librarian loop test (mock LLM client):
   - LLM returns tool calls → executor runs → tool results appended → loop exits.
   - Loop respects `MAX_TOOL_ROUNDS`.
3. Regression: existing JSON tool‑selection path still works when tool‑calling loop returns no tool calls.

## Assumptions
- Librarian is the only agent using the tool‑calling loop for now.
- OpenAI‑compatible tool schema is sufficient for DeepSeek/OpenAI providers.
- Central executor will live inside `MCPClient` as requested.
