"""MCP client: invoke tools on the MCP server."""

import time
from typing import TYPE_CHECKING

from util import interaction_log

if TYPE_CHECKING:
    from mcp.mcp_server import MCPServer


class MCPClient:
    """Client interface for interacting with the MCP Tool Server.

    All external data access (Milvus, Neo4j, Tavily, Yahoo,
    custom Analyst API) goes through this client.
    """

    def __init__(self, server: "MCPServer") -> None:
        """Initialize the client.

        Args:
            server: MCPServer instance to dispatch tool calls to.
        """
        # Store server reference; dispatch remains centralized server-side.
        self._server = server

    def get_registered_tool_names(self) -> list[str]:
        """Return sorted list of tool names registered on the server."""
        return sorted(self._server._handlers.keys())

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        """Invoke a tool on the MCP server.

        Args:
            tool_name: Name of the tool (e.g. vector_tool.search, analyst_tool.run_analysis).
            payload: Tool-specific parameters.

        Returns:
            Tool response dict. Structure depends on the tool.
        """
        start = time.perf_counter()
        result = self._server.dispatch(tool_name, payload)
        duration_ms = (time.perf_counter() - start) * 1000.0
        # Build result summary for logging (keys, size, error if present)
        result_summary: dict = {}
        if isinstance(result, dict):
            result_summary["result_keys"] = list(result.keys())
            if "error" in result:
                result_summary["error"] = str(result.get("error", ""))[:200]
            for k in ("documents", "rows", "content"):
                if k in result and result[k] is not None:
                    val = result[k]
                    result_summary[f"{k}_size"] = len(val) if isinstance(val, (list, str)) else 1
                    break
        else:
            result_summary["result_type"] = type(result).__name__
        interaction_log.log_call(
            "mcp.mcp_client.MCPClient.call_tool",
            params={"tool_name": tool_name, "payload": payload},
            result=result_summary or result,
            duration_ms=round(duration_ms, 2),
        )
        return result
