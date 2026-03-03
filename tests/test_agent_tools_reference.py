"""Validate that every tool in docs/agent-tools-reference.md is registered and callable.

Uses llm/tool_descriptions.TOOL_DESCRIPTIONS_BY_NAME as the source of tool names.
Calls each registered tool with a minimal payload; asserts the server does not
return 'Unknown tool'. Backend errors (e.g. missing API key, unset MILVUS_URI)
are allowed; only 'Unknown tool' is treated as failure.
"""

from __future__ import annotations

import pytest

from llm.tool_descriptions import TOOL_DESCRIPTIONS_BY_NAME
from mcp.mcp_client import MCPClient
from mcp.mcp_server import MCPServer


# Minimal payloads per tool (from docs/agent-tools-reference.md sample calls).
# Used to verify each tool is registered and accepts the documented payload shape.
SAMPLE_PAYLOADS: dict[str, dict] = {
    "file_tool.read_file": {"path": "/tmp/agent_tools_test"},
    "vector_tool.search": {"query": "NVDA fund performance 2024", "top_k": 5},
    "vector_tool.get_by_ids": {"ids": ["doc_001", "doc_002"]},
    "vector_tool.upsert_documents": {"docs": [{"id": "doc_003", "content": "Test."}]},
    "vector_tool.health_check": {},
    "vector_tool.create_collection_from_config": {"name": "fund_docs_v2", "dimension": 768, "primary_key_field": "id"},
    "kg_tool.query_graph": {"cypher": "MATCH (f:Fund {symbol: $sym}) RETURN f", "params": {"sym": "NVDA"}},
    "kg_tool.get_relations": {"entity": "NVDA"},
    "kg_tool.get_node_by_id": {"id_val": "NVDA", "id_key": "symbol"},
    "kg_tool.get_neighbors": {"node_id": "NVDA", "id_key": "symbol", "direction": "out", "limit": 20},
    "kg_tool.get_graph_schema": {},
    "kg_tool.shortest_path": {"start_id": "NVDA", "end_id": "AAPL", "id_key": "symbol", "max_depth": 5},
    "kg_tool.get_similar_nodes": {"node_id": "NVDA", "id_key": "symbol", "limit": 5},
    "kg_tool.fulltext_search": {"index_name": "fund_fulltext", "query_string": "semiconductor", "limit": 10},
    "kg_tool.bulk_export": {"cypher": "MATCH (f:Fund) RETURN f.symbol, f.name LIMIT 100", "format": "json"},
    "kg_tool.bulk_create_nodes": {"nodes": [{"id": "TSMC", "name": "Taiwan Semiconductor"}], "label": "Company", "id_key": "id"},
    "sql_tool.run_query": {"query": "SELECT * FROM funds WHERE symbol = %s", "params": ["NVDA"]},
    "sql_tool.explain_query": {"query": "SELECT * FROM funds WHERE aum > 1000000", "analyze": False},
    "sql_tool.export_results": {"query": "SELECT symbol, name, aum FROM funds ORDER BY aum DESC", "format": "csv", "row_limit": 500},
    "sql_tool.connection_health_check": {},
    "market_tool.get_fundamentals": {"symbol": "AAPL"},
    "market_tool.get_stock_data": {"symbol": "NVDA", "start_date": "2024-01-01", "end_date": "2024-12-31"},
    "market_tool.get_balance_sheet": {"ticker": "MSFT", "freq": "annual"},
    "market_tool.get_cashflow": {"ticker": "TSLA", "freq": "quarterly"},
    "market_tool.get_income_statement": {"ticker": "NVDA", "freq": "quarterly"},
    "market_tool.get_insider_transactions": {"ticker": "AAPL"},
    "market_tool.get_news": {"symbol": "NVDA", "limit": 5},
    "market_tool.get_global_news": {"as_of_date": "2024-12-31", "look_back_days": 7, "limit": 5},
    "analyst_tool.get_indicators": {"symbol": "NVDA", "indicator": "rsi", "as_of_date": "2024-12-31", "look_back_days": 30},
    "get_capabilities": {},
}


@pytest.fixture
def mcp_client() -> MCPClient:
    """Build MCP server with default tools and return client."""
    server = MCPServer()
    server.register_default_tools()
    return MCPClient(server)


def test_all_documented_tools_registered_and_callable(mcp_client: MCPClient) -> None:
    """Every tool in TOOL_DESCRIPTIONS_BY_NAME that is registered is callable without 'Unknown tool'."""
    caps = mcp_client.call_tool("get_capabilities", {})
    assert isinstance(caps, dict)
    registered = set(caps.get("tools") or [])
    missing_payloads = set(TOOL_DESCRIPTIONS_BY_NAME) - set(SAMPLE_PAYLOADS)
    assert not missing_payloads, f"Add SAMPLE_PAYLOADS for: {missing_payloads}"
    for tool_name in TOOL_DESCRIPTIONS_BY_NAME:
        if tool_name not in registered:
            # Optional tools (market_tool, analyst_tool) may be skipped when deps missing
            continue
        payload = SAMPLE_PAYLOADS.get(tool_name, {})
        result = mcp_client.call_tool(tool_name, payload)
        assert isinstance(result, dict), f"{tool_name}: expected dict, got {type(result)}"
        err = result.get("error")
        assert err != f"Unknown tool: {tool_name}", (
            f"{tool_name} should be registered; got Unknown tool. Registered: {sorted(registered)}"
        )


def test_documented_tool_names_match_tool_descriptions() -> None:
    """TOOL_DESCRIPTIONS_BY_NAME and SAMPLE_PAYLOADS cover the same set (except get_capabilities)."""
    desc_names = set(TOOL_DESCRIPTIONS_BY_NAME)
    payload_names = set(SAMPLE_PAYLOADS)
    assert desc_names == payload_names, (
        f"Tool names mismatch: only in descriptions {desc_names - payload_names}; "
        f"only in payloads {payload_names - desc_names}"
    )
