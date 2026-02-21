"""MCP server: register and dispatch tools."""

from typing import Any, Callable, Dict


class MCPServer:
    """
    Registers tool handlers and dispatches incoming tool calls.

    Tools (vector_tool, kg_tool, market_tool, analyst_tool, sql_tool,
    file_tool) are implemented as handlers; dispatch invokes them and
    returns results.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        """
        Register a tool by name.

        Args:
            name: Tool name (e.g. 'vector_tool.search').
            handler: Callable that accepts payload and returns result dict.
        """
        raise NotImplementedError

    def dispatch(self, tool_name: str, payload: dict) -> dict:
        """
        Invoke the named tool with the given payload.

        Args:
            tool_name: Name of the tool to invoke.
            payload: Tool-specific parameters.

        Returns:
            Result dict from the tool. Handles errors and timeouts.
        """
        raise NotImplementedError
