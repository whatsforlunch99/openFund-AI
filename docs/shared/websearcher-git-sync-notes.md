# WebSearcher / MCP migration notes (historical)

Operational notes from merging WebSearcher work into `main`. **Not** an MCP API reference—see [agent-tools-reference.md](../workflow/03_tools_and_mcp/agent-tools-reference.md) for tool contracts.

## Backup branch

Pre-sync local state was preserved on branch **`backup/local-wip-20260310`** (see repo history). To recover a file:

```bash
git show backup/local-wip-20260310:path/to/file
# or
git checkout backup/local-wip-20260310 -- path/to/file
```

## Current layout

The MCP server and tools live under **`openfund_mcp/`** only (`openfund_mcp/mcp_server.py`, `openfund_mcp/tools/`, including `news_tool.py`). There is no supported `mcp/mcp_server.py` path on current `main`.
