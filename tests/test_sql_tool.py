"""Tests for sql_tool community-common helpers: explain_query, export_results, connection_health_check."""

from __future__ import annotations

import pytest


def test_explain_query_error_when_db_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DATABASE_URL is unset, explain_query returns error."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.explain_query("SELECT 1")
    assert out.get("error") == "DATABASE_URL not set"
    assert out["plan"] == []


def test_explain_query_rejects_non_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """explain_query rejects non-SELECT query."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.explain_query("DELETE FROM t")
    assert "error" in out
    assert "plan" in out


def test_export_results_error_when_db_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DATABASE_URL is unset, export_results returns error."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("SELECT 1", format="json")
    assert out.get("error") == "DATABASE_URL not set"
    assert out["data"] == []
    assert out["row_count"] == 0


def test_export_results_csv_error_when_db_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """export_results format=csv returns empty string data when DATABASE_URL unset."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("SELECT 1", format="csv")
    assert out.get("error") == "DATABASE_URL not set"
    assert out["data"] == ""


def test_export_results_rejects_non_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """export_results rejects non-SELECT query."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("INSERT INTO t VALUES (1)")
    assert "error" in out


def test_export_results_invalid_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """export_results with invalid format returns error."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("SELECT 1", format="xml")
    assert "error" in out


def test_export_results_list_params_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM-shaped list params are normalized before DATABASE_URL check."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results(
        "SELECT * FROM t WHERE sym = %s",
        params=["AAPL"],
        format="json",
    )
    assert out.get("error") == "DATABASE_URL not set"
    assert out["data"] == []


def test_normalize_sql_bind_params() -> None:
    from openfund_mcp.tools.sql import tool as sql_tool

    assert sql_tool._normalize_sql_bind_params(None) is None
    assert sql_tool._normalize_sql_bind_params({"a": 1}) == {"a": 1}
    assert sql_tool._normalize_sql_bind_params((1, 2)) == (1, 2)
    assert sql_tool._normalize_sql_bind_params(["AAPL"]) == ("AAPL",)


def test_connection_health_check_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DATABASE_URL is unset, connection_health_check returns ok: false."""
    from openfund_mcp.tools.sql import tool as sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.connection_health_check()
    assert out["ok"] is False
    assert "error" in out
    assert "DATABASE_URL" in out["error"]


def test_sql_community_tools_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for explain_query, export_results, connection_health_check."""
    from openfund_mcp.mcp_client import MCPClient
    from openfund_mcp.mcp_server import MCPServer

    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    r1 = client.call_tool("sql_tool.explain_query", {"query": "SELECT 1"})
    assert r1.get("error") == "DATABASE_URL not set"
    assert r1.get("plan") == []
    r2 = client.call_tool("sql_tool.export_results", {"query": "SELECT 1", "format": "json"})
    assert r2.get("error") == "DATABASE_URL not set"
    assert r2.get("data") == []
    r2b = client.call_tool(
        "sql_tool.export_results",
        {"query": "SELECT 1", "format": "json", "params": ["x"]},
    )
    assert r2b.get("error") == "DATABASE_URL not set"
    assert r2b.get("data") == []
    r3 = client.call_tool("sql_tool.connection_health_check", {})
    assert "ok" in r3
