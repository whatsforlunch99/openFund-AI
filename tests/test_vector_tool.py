"""Tests for vector_tool community-common helpers: get_by_ids, upsert_documents, health_check."""

from __future__ import annotations

import pytest


def test_get_by_ids_mock_when_milvus_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MILVUS_URI is unset, get_by_ids returns mock entities."""
    from openfund_mcp.tools import vector_tool

    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = vector_tool.get_by_ids(["id1", "id2"])
    assert "entities" in out
    assert len(out["entities"]) >= 1
    assert out["entities"][0]["id"] in ("id1", "id2")


def test_get_by_ids_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_by_ids with empty list returns empty entities."""
    from openfund_mcp.tools import vector_tool

    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = vector_tool.get_by_ids([])
    assert out["entities"] == []


def test_upsert_documents_unset_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MILVUS_URI is unset, upsert_documents returns error."""
    from openfund_mcp.tools import vector_tool

    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = vector_tool.upsert_documents([{"id": "x", "content": "hi"}])
    assert "error" in out
    assert out.get("status") == "error"
    assert out.get("upserted") == 0


def test_upsert_documents_missing_id_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """upsert_documents with doc missing 'id' returns error (when MILVUS_URI set we still validate first)."""
    from openfund_mcp.tools import vector_tool

    monkeypatch.setenv("MILVUS_URI", "http://localhost:19530")
    try:
        out = vector_tool.upsert_documents([{"content": "no id"}])
        assert "error" in out
        assert "id" in out["error"].lower()
    finally:
        monkeypatch.delenv("MILVUS_URI", raising=False)


def test_health_check_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MILVUS_URI is unset, health_check returns ok: false."""
    from openfund_mcp.tools import vector_tool

    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = vector_tool.health_check()
    assert out["ok"] is False
    assert "error" in out
    assert "MILVUS_URI" in out["error"]


def test_vector_community_tools_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for get_by_ids, health_check."""
    from openfund_mcp.mcp_client import MCPClient
    from openfund_mcp.mcp_server import MCPServer

    monkeypatch.delenv("MILVUS_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    r1 = client.call_tool("vector_tool.get_by_ids", {"ids": ["a", "b"]})
    assert "entities" in r1
    r2 = client.call_tool("vector_tool.health_check", {})
    assert "ok" in r2
    assert r2["ok"] is False


def test_create_collection_from_config_unset_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MILVUS_URI is unset, create_collection_from_config returns error."""
    from openfund_mcp.tools import vector_tool

    monkeypatch.delenv("MILVUS_URI", raising=False)
    out = vector_tool.create_collection_from_config("test_coll", 384)
    assert "error" in out
    assert "MILVUS_URI" in out["error"]


def test_create_collection_from_config_missing_name_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_collection_from_config with empty name returns error when MILVUS_URI set."""
    monkeypatch.setenv("MILVUS_URI", "http://localhost:19530")
    from openfund_mcp.tools import vector_tool

    try:
        out = vector_tool.create_collection_from_config("", 384)
        assert "error" in out
        assert "name" in out["error"].lower()
    finally:
        monkeypatch.delenv("MILVUS_URI", raising=False)


def test_create_collection_from_config_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for create_collection_from_config returns error when MILVUS_URI unset."""
    from openfund_mcp.mcp_client import MCPClient
    from openfund_mcp.mcp_server import MCPServer

    monkeypatch.delenv("MILVUS_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    result = client.call_tool(
        "vector_tool.create_collection_from_config",
        {"name": "test_coll", "dimension": 384},
    )
    assert "error" in result
    assert "MILVUS_URI" in result["error"]
