"""MCP server: register and dispatch tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from util.log_format import struct_log

logger = logging.getLogger(__name__)


class MCPServer:
    """Registers tool handlers and dispatches incoming tool calls.

    Tools (vector_tool, kg_tool, market_tool, analyst_tool, sql_tool,
    file_tool) are implemented as handlers; dispatch invokes them and
    returns results.
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

    def register_default_tools(self) -> None:
        """Register file_tool first, then vector/kg/sql; market_tool and analyst_tool only if imports succeed (e.g. pandas)."""
        from mcp.tools import file_tool

        self.register_tool(
            "file_tool.read_file",
            lambda p: (
                file_tool.read_file(p["path"])
                if "path" in p
                else {"error": "Missing required parameter 'path'"}
            ),
        )
        from mcp.tools import vector_tool

        self.register_tool(
            "vector_tool.search",
            lambda p: (
                {
                    "documents": vector_tool.search(
                        p.get("query") or "",
                        p.get("top_k", 5),
                        p.get("filter"),
                    )
                }
                if "query" in p
                else {"error": "Missing required parameter 'query'"}
            ),
        )
        self.register_tool(
            "vector_tool.get_by_ids",
            lambda p: vector_tool.get_by_ids(
                p.get("ids") or [],
                p.get("collection_name"),
            ),
        )
        self.register_tool(
            "vector_tool.upsert_documents",
            lambda p: vector_tool.upsert_documents(p.get("docs") or []),
        )
        self.register_tool(
            "vector_tool.health_check",
            lambda p: vector_tool.health_check(),
        )
        self.register_tool(
            "vector_tool.create_collection_from_config",
            lambda p: vector_tool.create_collection_from_config(
                p.get("name") or "",
                int(p["dimension"]) if "dimension" in p and p["dimension"] is not None else 384,
                p.get("primary_key_field") or "id",
                p.get("scalar_fields"),
                p.get("index_params"),
            ),
        )
        from mcp.tools import kg_tool

        self.register_tool(
            "kg_tool.query_graph",
            lambda p: kg_tool.query_graph(
                p.get("cypher") or "",
                p.get("params"),
            ),
        )
        self.register_tool(
            "kg_tool.get_relations",
            lambda p: (
                kg_tool.get_relations(p.get("entity") or "")
                if "entity" in p
                else {"error": "Missing required parameter 'entity'"}
            ),
        )
        self.register_tool(
            "kg_tool.get_node_by_id",
            lambda p: kg_tool.get_node_by_id(
                p.get("id_val") or p.get("id") or "",
                p.get("id_key") or "id",
            ),
        )
        self.register_tool(
            "kg_tool.get_neighbors",
            lambda p: kg_tool.get_neighbors(
                p.get("node_id") or p.get("id") or "",
                p.get("id_key") or "id",
                p.get("direction") or "both",
                p.get("relationship_type"),
                int(p["limit"]) if "limit" in p and p["limit"] is not None else 100,
            ),
        )
        self.register_tool(
            "kg_tool.get_graph_schema",
            lambda p: kg_tool.get_graph_schema(),
        )
        self.register_tool(
            "kg_tool.shortest_path",
            lambda p: kg_tool.shortest_path(
                p.get("start_id") or "",
                p.get("end_id") or "",
                p.get("id_key") or "id",
                p.get("relationship_type"),
                int(p["max_depth"]) if "max_depth" in p and p["max_depth"] is not None else 15,
            ),
        )
        self.register_tool(
            "kg_tool.get_similar_nodes",
            lambda p: kg_tool.get_similar_nodes(
                p.get("node_id") or p.get("id") or "",
                p.get("id_key") or "id",
                int(p["limit"]) if "limit" in p and p["limit"] is not None else 10,
            ),
        )
        self.register_tool(
            "kg_tool.fulltext_search",
            lambda p: kg_tool.fulltext_search(
                p.get("index_name") or "",
                p.get("query_string") or "",
                int(p["limit"]) if "limit" in p and p["limit"] is not None else 50,
            ),
        )
        self.register_tool(
            "kg_tool.bulk_export",
            lambda p: kg_tool.bulk_export(
                p.get("cypher") or "",
                p.get("params"),
                p.get("format") or "json",
                int(p["row_limit"]) if "row_limit" in p and p["row_limit"] is not None else 1000,
            ),
        )
        self.register_tool(
            "kg_tool.bulk_create_nodes",
            lambda p: kg_tool.bulk_create_nodes(
                p.get("nodes") or [],
                p.get("label"),
                p.get("id_key") or "id",
            ),
        )
        from mcp.tools import sql_tool

        self.register_tool(
            "sql_tool.run_query",
            lambda p: (
                sql_tool.run_query(
                    p.get("query") or "",
                    p.get("params"),
                )
                if "query" in p
                else {"error": "Missing required parameter 'query'"}
            ),
        )
        self.register_tool(
            "sql_tool.explain_query",
            lambda p: sql_tool.explain_query(
                p.get("query") or "",
                p.get("params"),
                p.get("analyze") is True,
            ),
        )
        self.register_tool(
            "sql_tool.export_results",
            lambda p: sql_tool.export_results(
                p.get("query") or "",
                p.get("params"),
                p.get("format") or "json",
                int(p["row_limit"]) if "row_limit" in p and p["row_limit"] is not None else 1000,
            ),
        )
        self.register_tool(
            "sql_tool.connection_health_check",
            lambda p: sql_tool.connection_health_check(),
        )
        market_tool: Any | None = None
        try:
            from mcp.tools import market_tool as _market_tool
            market_tool = _market_tool
        except ImportError as e:
            struct_log(logger, logging.INFO, "mcp.tools_skipped", tool="market_tool", reason=str(e))
        # Skip optional tools if deps (e.g. pandas) missing so stage 2.1/2.2 tests pass
        if market_tool is not None:
            # Vendor-routed tools (alpha_vantage or finnhub via config)
            self.register_tool(
                "market_tool.get_fundamentals",
                lambda p: market_tool._route_fundamentals(
                    p.get("symbol") or p.get("ticker") or ""
                ),
            )
            self.register_tool(
                "market_tool.get_stock_data",
                lambda p: market_tool._route_stock_data(
                    p.get("symbol") or p.get("ticker") or "",
                    p.get("start_date") or "",
                    p.get("end_date") or "",
                ),
            )
            self.register_tool(
                "market_tool.get_balance_sheet",
                lambda p: market_tool._route_balance_sheet(
                    p.get("ticker") or p.get("symbol") or "",
                    p.get("freq") or "quarterly",
                ),
            )
            self.register_tool(
                "market_tool.get_cashflow",
                lambda p: market_tool._route_cashflow(
                    p.get("ticker") or p.get("symbol") or "",
                    p.get("freq") or "quarterly",
                ),
            )
            self.register_tool(
                "market_tool.get_income_statement",
                lambda p: market_tool._route_income_statement(
                    p.get("ticker") or p.get("symbol") or "",
                    p.get("freq") or "quarterly",
                ),
            )
            self.register_tool(
                "market_tool.get_news",
                lambda p: market_tool._route_news(
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
                lambda p: market_tool._route_global_news(
                    p.get("as_of_date") or p.get("curr_date") or "",
                    p.get("look_back_days") if "look_back_days" in p else 7,
                    p.get("limit") if "limit" in p else 10,
                ),
            )
            self.register_tool(
                "market_tool.get_insider_transactions",
                lambda p: market_tool._route_insider_transactions(
                    p.get("ticker") or p.get("symbol") or ""
                ),
            )
        analyst_tool: Any | None = None
        try:
            from mcp.tools import analyst_tool as _analyst_tool
            analyst_tool = _analyst_tool
        except ImportError as e:
            struct_log(logger, logging.INFO, "mcp.tools_skipped", tool="analyst_tool", reason=str(e))
        # analyst_tool also optional (may pull in pandas etc.)
        if analyst_tool is not None:
            self.register_tool(
                "analyst_tool.get_indicators",
                lambda p: analyst_tool._route_indicators(
                    p.get("symbol") or p.get("ticker") or "",
                    p.get("indicator") or "",
                    p.get("as_of_date") or p.get("curr_date") or "",
                    p.get("look_back_days") if "look_back_days" in p else 30,
                ),
            )
        from mcp.tools import capabilities

        self.register_tool(
            "get_capabilities",
            lambda p: capabilities.get_capabilities(list(self._handlers.keys())),
        )
