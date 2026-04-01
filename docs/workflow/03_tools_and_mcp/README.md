# MCP and agent tools (`03_tools_and_mcp`)

This folder documents **how OpenFund exposes MCP tools** and **how agents use them**. Each file has one job; dependencies flow in one direction (see below).

## Files (single responsibility)

| File | Responsibility | Read this for |
|------|----------------|---------------|
| [agent-tools-reference.md](agent-tools-reference.md) | **Canonical** tool names, payloads, sample JSON, per-agent allowlists, selection hints | LLM/tool contracts, `mcp_client.call_tool`, parity with `llm/tool_descriptions.py` |
| [mcp-server.md](mcp-server.md) | Running the FastMCP stdio server (`python -m openfund_mcp`), MCPClient env, Claude Desktop snippet | Operations and external MCP clients only |
| [websearcher-design.md](websearcher-design.md) | WebSearcher agent: parallel finance + news, `normalized_fund`, symbol resolution, Planner INFORM shape | `agents/websearch_agent.py` behavior—not full tool payloads |
| [news-searcher-design.md](news-searcher-design.md) | News subsystem: citations (`NEWS1`…), merge/dedupe rules, verification | News/citations—tool payloads still live in agent-tools-reference |

## Dependency direction (low coupling)

```text
llm/tool_descriptions.py  ←→  agent-tools-reference.md   (must stay in sync)
         │
         ▼
websearcher-design.md ──► agent-tools-reference.md   (design points to contracts)
news-searcher-design.md ──► websearcher-design.md + agent-tools-reference.md
mcp-server.md ──► agent-tools-reference.md           (tool list by reference only)
```

- **Do not** duplicate full tool payload tables in the design docs; link to **agent-tools-reference** instead.
- **Do not** put server startup instructions in agent-tools-reference; that belongs in **mcp-server**.

## Code locations

- Tool implementations: `openfund_mcp/tools/`
- Server + dispatch: `openfund_mcp/mcp_server.py`
- Per-agent allowlists and descriptions: `llm/tool_descriptions.py`

Historical git/sync notes (backup branch, pre-`openfund_mcp` migration) live outside this folder: [websearcher-git-sync-notes.md](../../shared/websearcher-git-sync-notes.md).
