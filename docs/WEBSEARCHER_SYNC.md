# WebSearcher sync from local WIP to origin/main

## Backup branch (nothing lost)

All pre-sync local state is on branch **`backup/local-wip-20260310`** (commit `02c90d3` and descendants).  
To recover any file:

```bash
git show backup/local-wip-20260310:path/to/file
# or
git checkout backup/local-wip-20260310 -- path/to/file
```

## Why `mcp/mcp_server.py` was removed

`origin/main` uses **`openfund_mcp/mcp_server.py`** only; there is no `mcp/mcp_server.py` on main.  
WebSearcher news tools are registered in **`openfund_mcp/mcp_server.py`**; implementation lives in **`openfund_mcp/tools/news_tool.py`**.

## Legacy `mcp/tools/` on disk

Stooq/Yahoo/ETFdb/fund_catalog tools from the old layout may still exist under `mcp/tools/` **untracked**.  
They are **not** registered on main until ported to `openfund_mcp/tools/` (see backup branch for full versions).

## `struct_log` / `log_agent_section`

Added to **`util/log_format.py`** so `agents/websearch_agent.py` can run on the current main tree.
