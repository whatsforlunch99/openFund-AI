"""MCP client: invoke tools on the MCP server."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.mcp_server import MCPServer


class MCPClient:
    """
    Client interface for interacting with the MCP Tool Server.

    All external data access (Milvus, Neo4j, Tavily, Yahoo,
    custom Analyst API) goes through this client.
    """

    def __init__(self, server: "MCPServer") -> None:
        self._server = server

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        """
        Invoke a tool on the MCP server.

        Args:
            tool_name: Name of the tool (e.g. vector_tool.search, analyst_tool.run_analysis).
            payload: Tool-specific parameters.

        Returns:
            Tool response dict. Structure depends on the tool.
        """
        return self._server.dispatch(tool_name, payload)
