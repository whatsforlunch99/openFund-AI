from __future__ import annotations

from unittest.mock import patch

from openfund_mcp.tools.websearch import fund_catalog


def test_fund_catalog_search_requires_query() -> None:
    out = fund_catalog.search({})
    assert "error" in out
    assert "query" in out["error"]


@patch("openfund_mcp.tools.websearch.fund_catalog.os.environ.get", return_value=None)
def test_fund_catalog_search_no_database_url(_env: object) -> None:
    out = fund_catalog.search({"query": "Vanguard", "limit": 5})
    assert out["error"] == "DATABASE_URL not set"


def test_fund_catalog_search_returns_empty_matches() -> None:
    def fake_run_query(query: str, params: dict | None = None) -> dict:
        if "GROUP BY table_name" in query:
            return {"rows": [{"table_name": "index_symbol_map"}], "schema": ["table_name"]}
        if "lower(column_name) AS column_name" in query:
            return {"rows": [{"column_name": "symbol"}], "schema": ["column_name"]}
        return {"rows": [], "schema": ["symbol", "name", "asset_class", "exchange"]}

    with patch("openfund_mcp.tools.websearch.fund_catalog.os.environ.get", return_value="postgres://x"), patch(
        "openfund_mcp.tools.websearch.fund_catalog.sql_postgres.run_query", side_effect=fake_run_query
    ):
        out = fund_catalog.search({"query": "ZZZZ", "limit": 3})
    assert out.get("matches") == []
    assert out.get("source") == "PostgreSQL"


def test_fund_catalog_search_success_dedupes_symbols() -> None:
    def fake_run_query(query: str, params: dict | None = None) -> dict:
        if "GROUP BY table_name" in query:
            return {
                "rows": [{"table_name": "index_symbol_map"}, {"table_name": "fund_info"}],
                "schema": ["table_name"],
            }
        if "table_name = %(table)s" in query:
            table = (params or {}).get("table")
            if table == "index_symbol_map":
                return {"rows": [{"column_name": "symbol"}, {"column_name": "name"}], "schema": ["column_name"]}
            return {
                "rows": [{"column_name": "symbol"}, {"column_name": "name"}, {"column_name": "exchange"}],
                "schema": ["column_name"],
            }
        if "FROM index_symbol_map" in query:
            return {
                "rows": [{"symbol": "VTI", "name": "Vanguard Total Stock", "asset_class": None, "exchange": None}],
                "schema": ["symbol", "name", "asset_class", "exchange"],
            }
        return {
            "rows": [
                {"symbol": "VTI", "name": "Vanguard Total Stock", "asset_class": "ETF", "exchange": "NYSE"},
                {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "asset_class": "ETF", "exchange": "NYSE"},
            ],
            "schema": ["symbol", "name", "asset_class", "exchange"],
        }

    with patch("openfund_mcp.tools.websearch.fund_catalog.os.environ.get", return_value="postgres://x"), patch(
        "openfund_mcp.tools.websearch.fund_catalog.sql_postgres.run_query", side_effect=fake_run_query
    ):
        out = fund_catalog.search({"query": "Vanguard", "limit": 5})

    assert out.get("source") == "PostgreSQL"
    assert [m["symbol"] for m in out.get("matches", [])] == ["VTI", "VOO"]

