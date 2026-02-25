"""MCP server: register and dispatch tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class MCPServer:
    """
    Registers tool handlers and dispatches incoming tool calls.

    Tools (vector_tool, kg_tool, market_tool, analyst_tool, sql_tool,
    file_tool) are implemented as handlers; dispatch invokes them and
    returns results.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        """
        Register a tool by name.

        Args:
            name: Tool name (e.g. 'vector_tool.search').
            handler: Callable that accepts payload and returns result dict.
        """
        self._handlers[name] = handler

    def dispatch(self, tool_name: str, payload: dict) -> dict:
        """
        Invoke the named tool with the given payload.

        Args:
            tool_name: Name of the tool to invoke.
            payload: Tool-specific parameters.

        Returns:
            Result dict from the tool. Handles errors and timeouts.
        """
        handler = self._handlers.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return handler(payload)
        except Exception as e:
            return {"error": str(e)}

    def register_default_tools(self) -> None:
        """
        Register all default MCP tools (file_tool.read_file and market_tool.*).
        Handlers decompose payload dict into explicit parameters for each tool.
        """
        from mcp.tools import analyst_tool, file_tool, market_tool

        self.register_tool(
            "file_tool.read_file",
            lambda p: (
                file_tool.read_file(p["path"])
                if "path" in p
                else {"error": "Missing required parameter 'path'"}
            ),
        )
        self.register_tool(
            "market_tool.get_stock_data",
            lambda p: market_tool.get_stock_data(
                p.get("symbol") or p.get("ticker") or "",
                p.get("start_date") or "",
                p.get("end_date") or "",
            ),
        )
        self.register_tool(
            "market_tool.get_fundamentals",
            lambda p: market_tool.get_fundamentals(
                p.get("ticker") or p.get("symbol") or ""
            ),
        )
        self.register_tool(
            "market_tool.get_balance_sheet",
            lambda p: market_tool.get_balance_sheet(
                p.get("ticker") or p.get("symbol") or "",
                p.get("freq") or "quarterly",
            ),
        )
        self.register_tool(
            "market_tool.get_cashflow",
            lambda p: market_tool.get_cashflow(
                p.get("ticker") or p.get("symbol") or "",
                p.get("freq") or "quarterly",
            ),
        )
        self.register_tool(
            "market_tool.get_income_statement",
            lambda p: market_tool.get_income_statement(
                p.get("ticker") or p.get("symbol") or "",
                p.get("freq") or "quarterly",
            ),
        )
        self.register_tool(
            "market_tool.get_insider_transactions",
            lambda p: market_tool.get_insider_transactions(
                p.get("ticker") or p.get("symbol") or ""
            ),
        )
        self.register_tool(
            "market_tool.get_news",
            lambda p: market_tool.get_news(
                p.get("symbol") or p.get("ticker") or "",
                (
                    p.get("limit")
                    if "limit" in p
                    else p.get("count") if "count" in p else None
                ),
                p.get("start_date"),
                p.get("end_date"),
            ),
        )
        self.register_tool(
            "market_tool.get_global_news",
            lambda p: market_tool.get_global_news(
                p.get("as_of_date") or p.get("curr_date") or "",
                p.get("look_back_days") if "look_back_days" in p else None,
                p.get("limit") if "limit" in p else None,
            ),
        )
        self.register_tool(
            "analyst_tool.get_indicators",
            lambda p: analyst_tool.get_indicators(
                p.get("symbol") or p.get("ticker") or "",
                p.get("indicator") or "",
                p.get("as_of_date") or p.get("curr_date") or "",
                p.get("look_back_days") if "look_back_days" in p else None,
            ),
        )
