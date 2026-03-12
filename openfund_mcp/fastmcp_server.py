"""FastMCP server: MCP protocol over stdio for external clients (e.g. Claude Desktop).

Tools are the same as in mcp/tools; registered with @mcp.tool() for discovery and JSON schema.
Run with: python -m openfund_mcp
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[misc, assignment]

mcp: Optional[Any] = None


def _create_app() -> Any:
    """Build FastMCP app and register all tools. Called on first use."""
    global mcp
    if mcp is not None:
        return mcp
    if FastMCP is None:
        raise RuntimeError(
            "MCP SDK not installed. Run: pip install mcp"
        )
    mcp = FastMCP("openfund-ai")

    # ---------------------------------------------------------------------------
    # vector_tool
    # ---------------------------------------------------------------------------
    from openfund_mcp.tools import vector_tool as vt

    @mcp.tool(
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

    @mcp.tool(
        name="vector_tool.get_by_ids",
        description="Retrieve entities by IDs. Payload: ids (list), collection_name (optional).",
    )
    def vector_tool_get_by_ids(
        ids: Optional[list[str]] = None,
        collection_name: Optional[str] = None,
    ) -> dict:
        return vt.get_by_ids(ids=ids or [], collection_name=collection_name)

    @mcp.tool(
        name="vector_tool.upsert_documents",
        description="Insert or update documents. Payload: docs (list of dicts with id, content; optional fund_id, source).",
    )
    def vector_tool_upsert_documents(docs: Optional[list[dict]] = None) -> dict:
        return vt.upsert_documents(docs=docs or [])

    @mcp.tool(
        name="vector_tool.health_check",
        description="Check Milvus connectivity.",
    )
    def vector_tool_health_check() -> dict:
        return vt.health_check()

    @mcp.tool(
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

    @mcp.tool(
        name="kg_tool.query_graph",
        description="Run Cypher query. Payload: cypher (string), params (optional dict).",
    )
    def kg_tool_query_graph(
        cypher: str = "",
        params: Optional[dict] = None,
    ) -> dict:
        return kt.query_graph(cypher=cypher, params=params)

    @mcp.tool(
        name="kg_tool.get_relations",
        description="Get relationships for an entity (fund/company). Payload: entity (string).",
    )
    def kg_tool_get_relations(entity: str) -> dict:
        return kt.get_relations(entity=entity)

    @mcp.tool(
        name="kg_tool.get_node_by_id",
        description="Look up a node by property. id_val or id (string), id_key (optional, default 'id').",
    )
    def kg_tool_get_node_by_id(
        id_val: Optional[str] = None,
        id_key: str = "id",
    ) -> dict:
        return kt.get_node_by_id(id_val=id_val or "", id_key=id_key)

    @mcp.tool(
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

    @mcp.tool(
        name="kg_tool.get_graph_schema",
        description="List node labels and relationship types.",
    )
    def kg_tool_get_graph_schema() -> dict:
        return kt.get_graph_schema()

    @mcp.tool(
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

    @mcp.tool(
        name="kg_tool.get_similar_nodes",
        description="Find structurally similar nodes by shared neighbors. node_id or id (string), id_key (optional), limit (optional int, default 10).",
    )
    def kg_tool_get_similar_nodes(
        node_id: Optional[str] = None,
        id_key: str = "id",
        limit: int = 10,
    ) -> dict:
        return kt.get_similar_nodes(node_id=node_id or "", id_key=id_key, limit=limit)

    @mcp.tool(
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

    @mcp.tool(
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

    @mcp.tool(
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

    @mcp.tool(
        name="sql_tool.run_query",
        description="Execute SQL on PostgreSQL. query (string, required), params (optional).",
    )
    def sql_tool_run_query(
        query: str,
        params: Optional[dict] = None,
    ) -> dict:
        return st.run_query(query=query, params=params)

    @mcp.tool(
        name="sql_tool.explain_query",
        description="Return SQL query plan. query (string), params (optional), analyze (optional bool).",
    )
    def sql_tool_explain_query(
        query: str = "",
        params: Optional[dict] = None,
        analyze: bool = False,
    ) -> dict:
        return st.explain_query(query=query, params=params, analyze=analyze)

    @mcp.tool(
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

    @mcp.tool(
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

        @mcp.tool(
            name="market_tool.get_fundamentals",
            description="Company fundamentals/overview. symbol or ticker (string).",
        )
        def market_tool_get_fundamentals(symbol: str = "") -> dict:
            return mt._route_fundamentals(symbol=symbol)

        @mcp.tool(
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

        @mcp.tool(
            name="market_tool.get_balance_sheet",
            description="Balance sheet. symbol or ticker (string), freq (optional 'quarterly'|'annual').",
        )
        def market_tool_get_balance_sheet(
            symbol: str = "",
            freq: str = "quarterly",
        ) -> dict:
            return mt._route_balance_sheet(symbol=symbol, freq=freq)

        @mcp.tool(
            name="market_tool.get_cashflow",
            description="Cash flow statement. symbol or ticker (string), freq (optional).",
        )
        def market_tool_get_cashflow(
            symbol: str = "",
            freq: str = "quarterly",
        ) -> dict:
            return mt._route_cashflow(symbol=symbol, freq=freq)

        @mcp.tool(
            name="market_tool.get_income_statement",
            description="Income statement. symbol or ticker (string), freq (optional).",
        )
        def market_tool_get_income_statement(
            symbol: str = "",
            freq: str = "quarterly",
        ) -> dict:
            return mt._route_income_statement(symbol=symbol, freq=freq)

        @mcp.tool(
            name="market_tool.get_insider_transactions",
            description="Insider transactions. symbol or ticker (string).",
        )
        def market_tool_get_insider_transactions(symbol: str = "") -> dict:
            return mt._route_insider_transactions(symbol=symbol)

        @mcp.tool(
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

        @mcp.tool(
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

        @mcp.tool(
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
    # WebSearcher parallel sources (Yahoo, stooq, ETFdb)
    # Local implementations live under mcp/tools/ but the PyPI package "mcp" shadows
    # the project folder name; load by file path so subprocess stdio server exposes them.
    # ---------------------------------------------------------------------------
    _has_websearcher_sources = False
    _websearcher_tool_names: list[str] = []

    def _load_tool_module(unique_name: str, relpath: str) -> Any | None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, relpath)
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location(unique_name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    try:
        # P1 FinanceDatabase search — same path-load pattern (PyPI mcp shadows local mcp package).
        fc = _load_tool_module("openfund_fund_catalog_tool", os.path.join("mcp", "tools", "fund_catalog_tool.py"))
        if fc is not None and hasattr(fc, "search"):
            @mcp.tool(
                name="fund_catalog_tool.search",
                description="Search ETFs/funds by name or query. query or name (string), limit (optional int).",
            )
            def fund_catalog_tool_search(
                query: str = "",
                name: str = "",
                limit: int = 10,
            ) -> dict:
                payload = {"limit": limit}
                if query.strip():
                    payload["query"] = query
                elif name.strip():
                    payload["name"] = name
                else:
                    payload["query"] = query or name
                return fc.search(payload)

            _has_websearcher_sources = True
            _websearcher_tool_names.append("fund_catalog_tool.search")
    except Exception:
        pass

    try:
        yft = _load_tool_module("openfund_yahoo_finance_tool", os.path.join("mcp", "tools", "yahoo_finance_tool.py"))
        if yft is not None and hasattr(yft, "get_fundamental") and hasattr(yft, "get_price"):
            @mcp.tool(
                name="yahoo_finance_tool.get_fundamental",
                description="Yahoo quoteSummary: price, ETF stats, holdings when available. symbol (string).",
            )
            def yahoo_finance_tool_get_fundamental(symbol: str = "") -> dict:
                return yft.get_fundamental({"symbol": symbol})

            @mcp.tool(
                name="yahoo_finance_tool.get_price",
                description="Yahoo chart API: latest price. symbol (string).",
            )
            def yahoo_finance_tool_get_price(symbol: str = "") -> dict:
                return yft.get_price({"symbol": symbol})
            _has_websearcher_sources = True
            _websearcher_tool_names.extend([
                "yahoo_finance_tool.get_fundamental",
                "yahoo_finance_tool.get_price",
            ])
    except Exception:
        pass

    try:
        # Name must not be `st` — sql_tool is imported as st above; reusing st breaks sql_tool.* closures.
        stooq_mod = _load_tool_module("openfund_stooq_tool", os.path.join("mcp", "tools", "stooq_tool.py"))
        if stooq_mod is not None and hasattr(stooq_mod, "get_price"):
            @mcp.tool(
                name="stooq_tool.get_price",
                description="Latest price from stooq. symbol (string); .US appended if missing.",
            )
            def stooq_tool_get_price(symbol: str = "") -> dict:
                return stooq_mod.get_price({"symbol": symbol})
            _has_websearcher_sources = True
            _websearcher_tool_names.append("stooq_tool.get_price")
    except Exception:
        pass

    try:
        et = _load_tool_module("openfund_etfdb_tool", os.path.join("mcp", "tools", "etfdb_tool.py"))
        if et is not None and hasattr(et, "get_fund_data"):
            @mcp.tool(
                name="etfdb_tool.get_fund_data",
                description="ETFdb expense ratio, AUM, holdings. symbol (string).",
            )
            def etfdb_tool_get_fund_data(symbol: str = "") -> dict:
                return et.get_fund_data({"symbol": symbol})
            _has_websearcher_sources = True
            _websearcher_tool_names.append("etfdb_tool.get_fund_data")
    except Exception:
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
    if _websearcher_tool_names:
        _tool_names.extend(_websearcher_tool_names)

    @mcp.tool(
        name="get_capabilities",
        description="List registered MCP tools and backend status (neo4j, postgres, milvus).",
    )
    def get_capabilities() -> dict:
        return cap.get_capabilities(_tool_names)

    return mcp


def run() -> None:
    """Run the FastMCP server over stdio (for external MCP clients)."""
    app = _create_app()
    app.run()


if __name__ == "__main__":
    run()
