"""MCP server: register and dispatch tools.

Provides MCPServer for in-process dispatch (tests) and FastMCP stdio server
for production/external clients. Run with: python -m openfund_mcp
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from openfund_mcp.tools.registry import call_by_spec, get_tool_spec_map

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

_fastmcp_app: Any = None


class MCPServer:
    """Registers tool handlers and dispatches incoming tool calls."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict], dict]] = {}
        self._spec_map = get_tool_spec_map()

    def register_tool(self, name: str, handler: Callable[[dict], dict]) -> None:
        self._handlers[name] = handler

    def dispatch(self, tool_name: str, payload: dict) -> dict:
        handler = self._handlers.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return handler(payload)
        except Exception as e:
            return {"error": str(e)}

    def register_default_tools(self) -> None:
        """Register all available tools from the canonical registry."""
        for name, spec in self._spec_map.items():

            def _handler(payload: dict, _spec=spec) -> dict:
                return call_by_spec(_spec, payload, list(self._handlers.keys()))

            self.register_tool(name, _handler)


def _create_fastmcp_app() -> Any:
    """Build FastMCP app and register all tools from the registry."""
    global _fastmcp_app
    if _fastmcp_app is not None:
        return _fastmcp_app
    if FastMCP is None:
        raise RuntimeError("MCP SDK not installed. Run: pip install mcp")

    app = FastMCP("openfund-ai")
    spec_map = get_tool_spec_map()

    for name, spec in spec_map.items():
        def _build_tool(s: Any) -> Callable[..., dict]:
            def _tool_func(**kwargs: Any) -> dict:
                return call_by_spec(s, kwargs, list(spec_map.keys()))

            return _tool_func

        tool_func = _build_tool(spec)
        tool_func.__name__ = name.replace(".", "_")
        app.tool(name=name, description=spec.description)(tool_func)

    _fastmcp_app = app
    return _fastmcp_app


def run_stdio() -> None:
    """Run the MCP server over stdio."""
    app = _create_fastmcp_app()
    app.run()

