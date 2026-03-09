# Agent Tools Reference

This document reflects `mcp/mcp_server.py` + `mcp/tools/*` as of the current code.

## Registration Model

- Tools are registered in `MCPServer.register_default_tools()`.
- Always registered: `vector_tool.*`, `kg_tool.*`, `sql_tool.*`, `get_capabilities`.
- Conditionally registered (only if imports succeed): `market_tool.*`, `analyst_tool.*`.
- Agents call tools via `mcp_client.call_tool("tool_name", payload)`.

## Registered Tool Names

### vector_tool
- `vector_tool.search`
- `vector_tool.get_by_ids`
- `vector_tool.upsert_documents`
- `vector_tool.health_check`
- `vector_tool.create_collection_from_config`

### kg_tool
- `kg_tool.query_graph`
- `kg_tool.get_relations`
- `kg_tool.get_node_by_id`
- `kg_tool.get_neighbors`
- `kg_tool.get_graph_schema`
- `kg_tool.shortest_path`
- `kg_tool.get_similar_nodes`
- `kg_tool.fulltext_search`
- `kg_tool.bulk_export`
- `kg_tool.bulk_create_nodes`

### sql_tool
- `sql_tool.run_query`
- `sql_tool.explain_query`
- `sql_tool.export_results`
- `sql_tool.connection_health_check`

### market_tool (optional)
- `market_tool.get_fundamentals`
- `market_tool.get_stock_data`
- `market_tool.get_balance_sheet`
- `market_tool.get_cashflow`
- `market_tool.get_income_statement`
- `market_tool.get_news`
- `market_tool.get_global_news`
- `market_tool.get_insider_transactions`

### analyst_tool (optional)
- `analyst_tool.get_indicators`

### capabilities
- `get_capabilities`

## Payload Shape (High Level)

- `vector_tool.search`: `query`, optional `top_k`, `filter`
- `kg_tool.query_graph`: `cypher`, optional `params`
- `sql_tool.run_query`: `query`, optional `params`
- `market_tool.get_stock_data`: optional `symbol`, `start_date`, `end_date`
- `analyst_tool.get_indicators`: optional `symbol`, `indicator`, `as_of_date`, `look_back_days`

For exact function behavior and edge cases, use the source in `mcp/tools/*.py`.
