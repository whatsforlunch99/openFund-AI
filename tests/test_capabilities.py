"""Tests for get_capabilities (community-common general tool)."""

from __future__ import annotations

import pytest


def test_get_capabilities_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_capabilities returns neo4j, postgres, milvus, tools."""
    from openfund_mcp.tools import capabilities

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = capabilities.get_capabilities(["vector_tool.search"])
    assert "neo4j" in out
    assert "postgres" in out
    assert "milvus" in out
    assert "tools" in out
    assert isinstance(out["tools"], list)
    assert "get_capabilities" in out["tools"]


def test_get_capabilities_backends_reflect_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend flags reflect env vars."""
    from openfund_mcp.tools import capabilities

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
    from openfund_mcp.mcp_client import MCPClient
    from openfund_mcp.mcp_server import MCPServer

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MILVUS_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    result = client.call_tool("get_capabilities", {})
    assert "tools" in result
    assert "get_capabilities" in result["tools"]
    assert "vector_tool.search" in result["tools"]
    assert "sql_tool.explain_query" in result["tools"]
    assert "vector_tool.get_by_ids" in result["tools"]
    assert "kg_tool.get_node_by_id" in result["tools"]


def test_fastmcp_discovery() -> None:
    """FastMCP server (subprocess) exposes expected tools via MCPClient (no in-process server)."""
    import os

    pytest.importorskip("mcp", reason="MCP SDK required for FastMCP subprocess test")
    from openfund_mcp.mcp_client import MCPClient

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client = MCPClient(command="python", args=("-m", "openfund_mcp"), cwd=project_root or None)
    try:
        names = client.get_registered_tool_names()
    finally:
        client.close()
    assert "vector_tool.search" in names
    assert "sql_tool.run_query" in names
    assert "get_capabilities" in names
