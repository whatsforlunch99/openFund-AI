"""Tests for sql_tool community-common helpers: explain_query, export_results, connection_health_check."""

from __future__ import annotations

import pytest


def test_explain_query_mock_when_db_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DATABASE_URL is unset, explain_query returns mock plan."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.explain_query("SELECT 1")
    assert "plan" in out
    assert len(out["plan"]) >= 1
    assert "error" not in out


def test_explain_query_rejects_non_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """explain_query rejects non-SELECT query."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.explain_query("DELETE FROM t")
    assert "error" in out
    assert "plan" in out


def test_export_results_mock_when_db_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DATABASE_URL is unset, export_results returns mock data."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("SELECT 1", format="json")
    assert "data" in out
    assert "row_count" in out
    assert out["row_count"] >= 1
    assert "error" not in out


def test_export_results_csv_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """export_results format=csv returns string data when mocked."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("SELECT 1", format="csv")
    assert "data" in out
    assert isinstance(out["data"], str)
    assert "id" in out["data"] or "value" in out["data"]


def test_export_results_rejects_non_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """export_results rejects non-SELECT query."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("INSERT INTO t VALUES (1)")
    assert "error" in out


def test_export_results_invalid_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """export_results with invalid format returns error."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.export_results("SELECT 1", format="xml")
    assert "error" in out


def test_connection_health_check_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DATABASE_URL is unset, connection_health_check returns ok: false."""
    from mcp.tools import sql_tool

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = sql_tool.connection_health_check()
    assert out["ok"] is False
    assert "error" in out
    assert "DATABASE_URL" in out["error"]


def test_sql_community_tools_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for explain_query, export_results, connection_health_check."""
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer

    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    r1 = client.call_tool("sql_tool.explain_query", {"query": "SELECT 1"})
    assert "plan" in r1
    r2 = client.call_tool("sql_tool.export_results", {"query": "SELECT 1", "format": "json"})
    assert "data" in r2
    r3 = client.call_tool("sql_tool.connection_health_check", {})
    assert "ok" in r3
