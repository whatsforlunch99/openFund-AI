"""Static demo responses for MCP tools: 'Should I invest in Nvidia?' (beginner).

All data is consistent: symbol NVDA, company NVIDIA Corporation, same timestamp.
Used when OPENFUND_DEMO=1 or --demo to avoid external APIs/DBs.
"""

from __future__ import annotations

# Single timestamp for all market/analyst responses (consistency)
DEMO_TIMESTAMP = "2025-02-21T12:00:00Z"

# --- file_tool.read_file ---
# Librarian uses path = content.get("path") or content.get("query"); return success shape.
FILE_READ_RESPONSE: dict = {
    "content": (
        "# NVIDIA Corporation (NVDA) – Overview for beginners\n\n"
        "NVIDIA Corporation designs GPUs and SoCs. It is known for gaming and data center chips. "
        "Past performance does not guarantee future results. This is not investment advice; "
        "consider your risk tolerance and do your own research before investing."
    ),
    "path": "demo/nvidia_overview.txt",
}

# --- vector_tool.search ---
# Server wraps list as {"documents": list}; each doc: content, score, id.
VECTOR_SEARCH_RESPONSE: dict = {
    "documents": [
        {
            "content": "NVIDIA (NVDA) is a leading semiconductor company focused on graphics and AI. Suitable for long-term growth investors; volatility can be high.",
            "score": 0.92,
            "id": "demo_nvda_1",
        },
        {
            "content": "NVDA fundamentals: Technology sector, strong revenue growth. Not a recommendation to buy or sell.",
            "score": 0.88,
            "id": "demo_nvda_2",
        },
    ]
}

# --- kg_tool.get_relations ---
KG_GET_RELATIONS_RESPONSE: dict = {
    "nodes": [
        {"id": "NVDA", "label": "Company"},
        {"id": "Technology", "label": "Sector"},
    ],
    "edges": [{"source": "NVDA", "target": "Technology", "type": "IN_SECTOR"}],
    "entity": "NVDA",
}

# --- market_tool.get_fundamentals_yf ---
MARKET_FUNDAMENTALS_RESPONSE: dict = {
    "content": (
        "# Company Fundamentals for NVDA\n"
        "# Data retrieved on: 2025-02-21 12:00:00\n\n"
        "Name: NVIDIA Corporation\n"
        "Sector: Technology\n"
        "Industry: Semiconductors\n"
        "Market Cap: 3200000000000\n"
        "PE Ratio (TTM): 65.2\n"
        "52 Week High: 140.0\n"
        "52 Week Low: 75.0\n"
    ),
    "timestamp": DEMO_TIMESTAMP,
}

# --- market_tool.get_news_yf ---
MARKET_NEWS_RESPONSE: dict = {
    "content": (
        "## NVDA News:\n\n"
        "### NVIDIA Reports Strong Data Center Demand (source: Reuters)\n"
        "Demand for AI chips continues to drive results. This is not investment advice.\n"
        "Link: https://example.com/nvda-news\n"
    ),
    "timestamp": DEMO_TIMESTAMP,
}

# --- market_tool.get_global_news_yf ---
MARKET_GLOBAL_NEWS_RESPONSE: dict = {
    "content": (
        "## Global Market News:\n\n"
        "### Fed Holds Rates (source: Reuters)\n"
        "Macro conditions may affect tech valuations including NVDA.\n"
    ),
    "timestamp": DEMO_TIMESTAMP,
}

# --- analyst_tool.get_indicators_yf ---
# Analyst agent uses this and returns {"confidence": 0.7, "indicators": api_result, ...} when no error.
ANALYST_INDICATORS_RESPONSE: dict = {
    "content": (
        "## sma_50 values for NVDA (look back from 2025-02-21):\n\n"
        "2025-02-20: 128.5\n"
        "2025-02-19: 127.8\n"
    ),
    "timestamp": DEMO_TIMESTAMP,
}

# --- sql_tool.run_query ---
SQL_RUN_QUERY_RESPONSE: dict = {
    "rows": [{"symbol": "NVDA", "name": "NVIDIA Corporation"}],
    "schema": ["symbol", "name"],
    "params": {},
}

# Map tool_name -> response dict (for tools that return the same payload regardless of args)
DEMO_RESPONSES: dict[str, dict] = {
    "file_tool.read_file": FILE_READ_RESPONSE,
    "vector_tool.search": VECTOR_SEARCH_RESPONSE,
    "kg_tool.get_relations": KG_GET_RELATIONS_RESPONSE,
    "kg_tool.query_graph": {"nodes": [], "edges": [], "params": {}},
    "market_tool.get_fundamentals_yf": MARKET_FUNDAMENTALS_RESPONSE,
    "market_tool.get_fundamentals": MARKET_FUNDAMENTALS_RESPONSE,
    "market_tool.get_news_yf": MARKET_NEWS_RESPONSE,
    "market_tool.get_news": MARKET_NEWS_RESPONSE,
    "market_tool.get_global_news_yf": MARKET_GLOBAL_NEWS_RESPONSE,
    "market_tool.get_global_news": MARKET_GLOBAL_NEWS_RESPONSE,
    "analyst_tool.get_indicators_yf": ANALYST_INDICATORS_RESPONSE,
    "analyst_tool.get_indicators": ANALYST_INDICATORS_RESPONSE,
    "sql_tool.run_query": SQL_RUN_QUERY_RESPONSE,
}

# Additional market_tool names that may be registered (return same fundamentals/news shape)
for _name in (
    "market_tool.get_stock_data_yf",
    "market_tool.get_balance_sheet_yf",
    "market_tool.get_cashflow_yf",
    "market_tool.get_income_statement_yf",
    "market_tool.get_insider_transactions_yf",
):
    if _name not in DEMO_RESPONSES:
        DEMO_RESPONSES[_name] = {
            "content": f"Demo data for {_name}.",
            "timestamp": DEMO_TIMESTAMP,
        }
