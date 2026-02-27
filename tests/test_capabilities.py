"""Tests for get_capabilities (community-common general tool)."""

from __future__ import annotations

import os

import pytest


def test_get_capabilities_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_capabilities returns neo4j, postgres, milvus, tools."""
    from mcp.tools import capabilities

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = capabilities.get_capabilities(["file_tool.read_file"])
    assert "neo4j" in out
    assert "postgres" in out
    assert "milvus" in out
    assert "tools" in out
    assert isinstance(out["tools"], list)
    assert "get_capabilities" in out["tools"]


def test_get_capabilities_backends_reflect_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend flags reflect env vars."""
    from mcp.tools import capabilities

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = capabilities.get_capabilities([])
    assert out["neo4j"] is False
    assert out["postgres"] is False
    assert out["milvus"] is False

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    out2 = capabilities.get_capabilities([])
    assert out2["neo4j"] is True


def test_get_capabilities_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for get_capabilities returns dict with tools and backends."""
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MILVUS_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    result = client.call_tool("get_capabilities", {})
    assert "tools" in result
    assert "get_capabilities" in result["tools"]
    assert "file_tool.read_file" in result["tools"]
    assert "sql_tool.explain_query" in result["tools"]
    assert "vector_tool.get_by_ids" in result["tools"]
    assert "kg_tool.get_node_by_id" in result["tools"]
