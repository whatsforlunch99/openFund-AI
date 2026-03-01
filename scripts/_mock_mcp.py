"""Shared mock MCP client for standalone agent test scripts. Returns stub data, no network."""

from datetime import datetime, timezone


class MockMCPClient:
    """call_tool(tool_name, payload) returns a stub dict so agents can run without real backends."""

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        if not tool_name:
            return {"error": "empty tool name"}
        # Use today's date for market/analyst stubs so summaries say "today" not a fixed past date
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        # Return minimal stubs so agents don't fail
        if "file_tool" in tool_name:
            return {"content": "(mock file content)", "path": payload.get("path", "")}
        if "vector_tool" in tool_name:
            return {"documents": [], "query": payload.get("query", "")}
        if "kg_tool" in tool_name:
            return {"nodes": [], "edges": [], "rows": []}
        if "sql_tool" in tool_name:
            return {"rows": [], "row_count": 0}
        if "market_tool" in tool_name:
            return {"market_data": {"symbol": payload.get("symbol") or payload.get("ticker", ""), "stub": True}, "timestamp": now_iso}
        if "analyst_tool" in tool_name:
            return {"indicators": {}, "symbol": payload.get("symbol", ""), "stub": True, "timestamp": now_iso}
        if tool_name == "get_capabilities":
            return {"tools": [], "neo4j": False, "postgres": False, "milvus": False}
        return {"stub": True, "tool": tool_name}
