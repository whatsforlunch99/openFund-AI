"""MCP server: register and dispatch tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _payload_handler(
    func: Callable[..., Any],
    required_keys: list[str] | None = None,
    arg_specs: list[tuple[str, list[str], Any, Any]] | None = None,
    result_key: str | None = None,
) -> Callable[[dict], dict]:
    """Build a payload -> dict handler from a spec.

    Args:
        func: Tool function to call (e.g. vector_tool.search).
        required_keys: Payload keys that must be present; else return error dict.
        arg_specs: List of (param_name, payload_keys, default, coerce). payload_keys
            is tried in order; first present key supplies the value. coerce is int or
            a callable(val) for custom coercion (e.g. bool for explain_query).
        result_key: If set, wrap return value in {result_key: result}.

    Returns:
        A handler(payload) -> dict suitable for register_tool.
    """
    required_keys = required_keys or []
    arg_specs = arg_specs or []

    def handler(payload: dict) -> dict:
        for k in required_keys:
            if k not in payload:
                return {"error": f"Missing required parameter '{k}'"}
        kwargs: dict[str, Any] = {}
        for param_name, payload_keys, default, coerce in arg_specs:
            val = default
            for pk in payload_keys:
                if pk in payload:
                    val = payload[pk]
                    break
            if coerce is not None:
                if coerce is int and val is not None:
                    val = int(val)
                elif callable(coerce):
                    val = coerce(val) if val is not None else default
            kwargs[param_name] = val
        result = func(**kwargs)
        if result_key is not None:
            return {result_key: result}
        return result

    return handler


class MCPServer:
    """Registers tool handlers and dispatches incoming tool calls.

    Tools (vector_tool, kg_tool, market_tool, analyst_tool, sql_tool)
    are implemented as handlers; dispatch invokes them and returns results.
    """

    def __init__(self) -> None:
        """Initialize empty handler registry."""
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        """Register a tool by name.

        Args:
            name: Tool name (e.g. 'vector_tool.search').
            handler: Callable that accepts payload and returns result dict.
        """
        self._handlers[name] = handler

    def dispatch(self, tool_name: str, payload: dict) -> dict:
        """Invoke the named tool with the given payload.

        Returns {"error": "..."} if tool is unknown or the handler raises.
        """
        handler = self._handlers.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        # Invoke handler; return error dict if it raises
        try:
            return handler(payload)
        except Exception as e:
            return {"error": str(e)}  # backend: MCP tool errors return {"error": "..."}

    def _register_specs(
        self,
        module: Any,
        specs: list[tuple[str, str, list[str], list, str | None]],
    ) -> None:
        """Register tools from a list of (name, func_name, required_keys, arg_specs, result_key)."""
        for name, func_name, required, arg_specs, result_key in specs:
            func = getattr(module, func_name)
            self.register_tool(
                name,
                _payload_handler(func, required, arg_specs, result_key),
            )

    def register_default_tools(self) -> None:
        """Register vector/kg/sql first; market_tool and analyst_tool only if imports succeed (e.g. pandas)."""
        from mcp.tools import vector_tool

        self._register_specs(vector_tool, vector_tool.TOOL_SPECS)

        from mcp.tools import kg_tool

        self._register_specs(kg_tool, kg_tool.TOOL_SPECS)

        from mcp.tools import sql_tool

        self._register_specs(sql_tool, sql_tool.TOOL_SPECS)

        market_tool: Any | None = None
        try:
            from mcp.tools import market_tool as _market_tool

            market_tool = _market_tool
        except ImportError:
            pass
        if market_tool is not None:
            self._register_specs(market_tool, market_tool.TOOL_SPECS)

        analyst_tool: Any | None = None
        try:
            from mcp.tools import analyst_tool as _analyst_tool

            analyst_tool = _analyst_tool
        except ImportError:
            pass
        if analyst_tool is not None:
            self._register_specs(analyst_tool, analyst_tool.TOOL_SPECS)

        from mcp.tools import capabilities

        self.register_tool(
            "get_capabilities",
            lambda p: capabilities.get_capabilities(list(self._handlers.keys())),
        )
