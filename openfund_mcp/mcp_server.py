"""MCP server: register and dispatch tools.

Provides MCPServer for in-process dispatch (tests) and FastMCP stdio server
for production/external clients. Run with: python -m openfund_mcp
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

_fastmcp_app: Any = None


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
        from openfund_mcp.tools import vector_tool

        self._register_specs(vector_tool, vector_tool.TOOL_SPECS)

        from openfund_mcp.tools import kg_tool

        self._register_specs(kg_tool, kg_tool.TOOL_SPECS)

        from openfund_mcp.tools import sql_tool

        self._register_specs(sql_tool, sql_tool.TOOL_SPECS)

        market_tool: Any | None = None
        try:
            from openfund_mcp.tools import market_tool as _market_tool

            market_tool = _market_tool
        except ImportError:
            pass
        if market_tool is not None:
            self._register_specs(market_tool, market_tool.TOOL_SPECS)

        analyst_tool: Any | None = None
        try:
            from openfund_mcp.tools import analyst_tool as _analyst_tool

            analyst_tool = _analyst_tool
        except ImportError:
            pass
        if analyst_tool is not None:
            self._register_specs(analyst_tool, analyst_tool.TOOL_SPECS)

        from openfund_mcp.tools import capabilities

        self.register_tool(
            "get_capabilities",
            lambda p: capabilities.get_capabilities(list(self._handlers.keys())),
        )


def _create_fastmcp_app() -> Any:
    """Build FastMCP app and register all tools. Used for stdio server (python -m openfund_mcp)."""
    global _fastmcp_app
    if _fastmcp_app is not None:
        return _fastmcp_app
    if FastMCP is None:
        raise RuntimeError("MCP SDK not installed. Run: pip install mcp")
    app = FastMCP("openfund-ai")

    # ---------------------------------------------------------------------------
    # vector_tool
    # ---------------------------------------------------------------------------
    from openfund_mcp.tools import vector_tool as vt

    @app.tool(
        name="vector_tool.search",
        description="Semantic search over documents. Query (required), top_k (optional int, default 5), filter (optional dict).",
    )
    def vector_tool_search(
        query: str,
        top_k: int = 5,
        filter: Optional[dict] = None,
    ) -> dict:
        docs = vt.search(query=query, top_k=top_k, filter=filter)
        return {"documents": docs}

    @app.tool(
        name="vector_tool.get_by_ids",
        description="Retrieve entities by IDs. Payload: ids (list), collection_name (optional).",
    )
    def vector_tool_get_by_ids(
        ids: Optional[list[str]] = None,
        collection_name: Optional[str] = None,
    ) -> dict:
        return vt.get_by_ids(ids=ids or [], collection_name=collection_name)

    @app.tool(
        name="vector_tool.upsert_documents",
        description="Insert or update documents. Payload: docs (list of dicts with id, content; optional fund_id, source).",
    )
    def vector_tool_upsert_documents(docs: Optional[list[dict]] = None) -> dict:
        return vt.upsert_documents(docs=docs or [])

    @app.tool(
        name="vector_tool.health_check",
        description="Check Milvus connectivity.",
    )
    def vector_tool_health_check() -> dict:
        return vt.health_check()

    @app.tool(
        name="vector_tool.create_collection_from_config",
        description="Create a Milvus collection. name (str), dimension (optional int, default 384), primary_key_field, scalar_fields, index_params (optional).",
    )
    def vector_tool_create_collection(
        name: str = "",
        dimension: int = 384,
        primary_key_field: str = "id",
        scalar_fields: Optional[list] = None,
        index_params: Optional[dict] = None,
    ) -> dict:
        return vt.create_collection_from_config(
            name=name,
            dimension=dimension,
            primary_key_field=primary_key_field,
            scalar_fields=scalar_fields,
            index_params=index_params,
        )

    # ---------------------------------------------------------------------------
    # kg_tool
    # ---------------------------------------------------------------------------
    from openfund_mcp.tools import kg_tool as kt

    @app.tool(
        name="kg_tool.query_graph",
        description="Run Cypher query. Payload: cypher (string), params (optional dict).",
    )
    def kg_tool_query_graph(
        cypher: str = "",
        params: Optional[dict] = None,
    ) -> dict:
        return kt.query_graph(cypher=cypher, params=params)

    @app.tool(
        name="kg_tool.get_relations",
        description="Get relationships for an entity (fund/company). Payload: entity (string).",
    )
    def kg_tool_get_relations(entity: str) -> dict:
        return kt.get_relations(entity=entity)

    @app.tool(
        name="kg_tool.get_node_by_id",
        description="Look up a node by property. id_val or id (string), id_key (optional, default 'id').",
    )
    def kg_tool_get_node_by_id(
        id_val: Optional[str] = None,
        id_key: str = "id",
    ) -> dict:
        return kt.get_node_by_id(id_val=id_val or "", id_key=id_key)

    @app.tool(
        name="kg_tool.get_neighbors",
        description="Get neighbors of a node. node_id or id (string), id_key, direction ('in'|'out'|'both'), relationship_type (optional), limit (optional int, default 100).",
    )
    def kg_tool_get_neighbors(
        node_id: Optional[str] = None,
        id_key: str = "id",
        direction: str = "both",
        relationship_type: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        return kt.get_neighbors(
            node_id=node_id or "",
            id_key=id_key,
            direction=direction,
            relationship_type=relationship_type,
            limit=limit,
        )

    @app.tool(
        name="kg_tool.get_graph_schema",
        description="List node labels and relationship types.",
    )
    def kg_tool_get_graph_schema() -> dict:
        return kt.get_graph_schema()

    @app.tool(
        name="kg_tool.shortest_path",
        description="Find shortest path between two nodes. start_id, end_id (string), id_key (optional), relationship_type (optional), max_depth (optional int, default 15).",
    )
    def kg_tool_shortest_path(
        start_id: str = "",
        end_id: str = "",
        id_key: str = "id",
        relationship_type: Optional[str] = None,
        max_depth: int = 15,
    ) -> dict:
        return kt.shortest_path(
            start_id=start_id,
            end_id=end_id,
            id_key=id_key,
            relationship_type=relationship_type,
            max_depth=max_depth,
        )

    @app.tool(
        name="kg_tool.get_similar_nodes",
        description="Find structurally similar nodes by shared neighbors. node_id or id (string), id_key (optional), limit (optional int, default 10).",
    )
    def kg_tool_get_similar_nodes(
        node_id: Optional[str] = None,
        id_key: str = "id",
        limit: int = 10,
    ) -> dict:
        return kt.get_similar_nodes(node_id=node_id or "", id_key=id_key, limit=limit)

    @app.tool(
        name="kg_tool.fulltext_search",
        description="Full-text search via Neo4j index. index_name (string), query_string (string), limit (optional int, default 50).",
    )
    def kg_tool_fulltext_search(
        index_name: str = "",
        query_string: str = "",
        limit: int = 50,
    ) -> dict:
        return kt.fulltext_search(
            index_name=index_name,
            query_string=query_string,
            limit=limit,
        )

    @app.tool(
        name="kg_tool.bulk_export",
        description="Read-only Cypher export as JSON or CSV. cypher (string), params (optional), format ('json'|'csv'), row_limit (optional int, default 1000).",
    )
    def kg_tool_bulk_export(
        cypher: str = "",
        params: Optional[dict] = None,
        format: str = "json",
        row_limit: int = 1000,
    ) -> dict:
        return kt.bulk_export(
            cypher=cypher,
            params=params,
            format=format,
            row_limit=row_limit,
        )

    @app.tool(
        name="kg_tool.bulk_create_nodes",
        description="Create/merge nodes. nodes (list of dicts), label (optional string), id_key (optional string, default 'id').",
    )
    def kg_tool_bulk_create_nodes(
        nodes: Optional[list[dict]] = None,
        label: Optional[str] = None,
        id_key: str = "id",
    ) -> dict:
        return kt.bulk_create_nodes(nodes=nodes or [], label=label, id_key=id_key)

    # ---------------------------------------------------------------------------
    # sql_tool
    # ---------------------------------------------------------------------------
    from openfund_mcp.tools import sql_tool as st

    @app.tool(
        name="sql_tool.run_query",
        description="Execute SQL on PostgreSQL. query (string, required), params (optional).",
    )
    def sql_tool_run_query(
        query: str,
        params: Optional[dict] = None,
    ) -> dict:
        return st.run_query(query=query, params=params)

    @app.tool(
        name="sql_tool.explain_query",
        description="Return SQL query plan. query (string), params (optional), analyze (optional bool).",
    )
    def sql_tool_explain_query(
        query: str = "",
        params: Optional[dict] = None,
        analyze: bool = False,
    ) -> dict:
        return st.explain_query(query=query, params=params, analyze=analyze)

    @app.tool(
        name="sql_tool.export_results",
        description="Run read-only SQL and return JSON or CSV. query (string), params (optional), format ('json'|'csv'), row_limit (optional int, default 1000).",
    )
    def sql_tool_export_results(
        query: str = "",
        params: Optional[dict] = None,
        format: str = "json",
        row_limit: int = 1000,
    ) -> dict:
        return st.export_results(
            query=query,
            params=params,
            format=format,
            row_limit=row_limit,
        )

    @app.tool(
        name="sql_tool.connection_health_check",
        description="Test PostgreSQL connectivity.",
    )
    def sql_tool_connection_health_check() -> dict:
        return st.connection_health_check()

    # ---------------------------------------------------------------------------
    # market_tool (optional)
    # ---------------------------------------------------------------------------
    _has_market = False
    try:
        from openfund_mcp.tools import market_tool as mt

        @app.tool(
            name="market_tool.get_fundamentals",
            description="Company fundamentals/overview. symbol or ticker (string).",
        )
        def market_tool_get_fundamentals(symbol: str = "") -> dict:
            return mt._route_fundamentals(symbol=symbol)

        @app.tool(
            name="market_tool.get_stock_data",
            description="OHLCV historical data. symbol (string), start_date (yyyy-mm-dd), end_date (yyyy-mm-dd).",
        )
        def market_tool_get_stock_data(
            symbol: str = "",
            start_date: str = "",
            end_date: str = "",
        ) -> dict:
            return mt._route_stock_data(
                symbol=symbol, start_date=start_date, end_date=end_date
            )

        @app.tool(
            name="market_tool.get_balance_sheet",
            description="Balance sheet. symbol or ticker (string), freq (optional 'quarterly'|'annual').",
        )
        def market_tool_get_balance_sheet(
            symbol: str = "",
            freq: str = "quarterly",
        ) -> dict:
            return mt._route_balance_sheet(symbol=symbol, freq=freq)

        @app.tool(
            name="market_tool.get_cashflow",
            description="Cash flow statement. symbol or ticker (string), freq (optional).",
        )
        def market_tool_get_cashflow(
            symbol: str = "",
            freq: str = "quarterly",
        ) -> dict:
            return mt._route_cashflow(symbol=symbol, freq=freq)

        @app.tool(
            name="market_tool.get_income_statement",
            description="Income statement. symbol or ticker (string), freq (optional).",
        )
        def market_tool_get_income_statement(
            symbol: str = "",
            freq: str = "quarterly",
        ) -> dict:
            return mt._route_income_statement(symbol=symbol, freq=freq)

        @app.tool(
            name="market_tool.get_insider_transactions",
            description="Insider transactions. symbol or ticker (string).",
        )
        def market_tool_get_insider_transactions(symbol: str = "") -> dict:
            return mt._route_insider_transactions(symbol=symbol)

        @app.tool(
            name="market_tool.get_news",
            description="Recent ticker news. symbol or ticker (string), limit (optional), start_date, end_date.",
        )
        def market_tool_get_news(
            symbol: str = "",
            limit: Optional[int] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
        ) -> dict:
            return mt._route_news(
                symbol=symbol,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )

        @app.tool(
            name="market_tool.get_global_news",
            description="Global/macro financial news. as_of_date (optional yyyy-mm-dd), look_back_days (optional int, default 7), limit (optional int, default 10).",
        )
        def market_tool_get_global_news(
            as_of_date: str = "",
            look_back_days: int = 7,
            limit: int = 10,
        ) -> dict:
            return mt._route_global_news(
                as_of_date=as_of_date,
                look_back_days=look_back_days,
                limit=limit,
            )
        _has_market = True
    except ImportError:
        pass

    # ---------------------------------------------------------------------------
    # analyst_tool (optional)
    # ---------------------------------------------------------------------------
    _has_analyst = False
    try:
        from openfund_mcp.tools import analyst_tool as at

        @app.tool(
            name="analyst_tool.get_indicators",
            description="Technical indicators (SMA, RSI, MACD, etc.). symbol (string), indicator (e.g. close_50_sma, rsi, macd), as_of_date (yyyy-mm-dd), look_back_days (optional int, default 30).",
        )
        def analyst_tool_get_indicators(
            symbol: str = "",
            indicator: str = "",
            as_of_date: str = "",
            look_back_days: int = 30,
        ) -> dict:
            return at._route_indicators(
                symbol=symbol,
                indicator=indicator,
                as_of_date=as_of_date,
                look_back_days=look_back_days,
            )
        _has_analyst = True
    except ImportError:
        pass

    # ---------------------------------------------------------------------------
    # get_capabilities
    # ---------------------------------------------------------------------------
    from openfund_mcp.tools import capabilities as cap

    _tool_names: list[str] = [
        "vector_tool.search",
        "vector_tool.get_by_ids",
        "vector_tool.upsert_documents",
        "vector_tool.health_check",
        "vector_tool.create_collection_from_config",
        "kg_tool.query_graph",
        "kg_tool.get_relations",
        "kg_tool.get_node_by_id",
        "kg_tool.get_neighbors",
        "kg_tool.get_graph_schema",
        "kg_tool.shortest_path",
        "kg_tool.get_similar_nodes",
        "kg_tool.fulltext_search",
        "kg_tool.bulk_export",
        "kg_tool.bulk_create_nodes",
        "sql_tool.run_query",
        "sql_tool.explain_query",
        "sql_tool.export_results",
        "sql_tool.connection_health_check",
    ]
    if _has_market:
        _tool_names.extend([
            "market_tool.get_fundamentals",
            "market_tool.get_stock_data",
            "market_tool.get_balance_sheet",
            "market_tool.get_cashflow",
            "market_tool.get_income_statement",
            "market_tool.get_insider_transactions",
            "market_tool.get_news",
            "market_tool.get_global_news",
        ])
    if _has_analyst:
        _tool_names.append("analyst_tool.get_indicators")

    @app.tool(
        name="get_capabilities",
        description="List registered MCP tools and backend status (neo4j, postgres, milvus).",
    )
    def get_capabilities() -> dict:
        return cap.get_capabilities(_tool_names)

    _fastmcp_app = app
    return _fastmcp_app


def run_stdio() -> None:
    """Run the MCP server over stdio (for python -m openfund_mcp and external MCP clients)."""
    app = _create_fastmcp_app()
    app.run()
