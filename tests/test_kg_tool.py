"""Tests for kg_tool community-common helpers: get_node_by_id, get_neighbors, get_graph_schema."""

from __future__ import annotations

import pytest


def test_get_node_by_id_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_node_by_id returns mock node."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_node_by_id("n1")
    assert "node" in out
    assert out["node"] == {"id": "n1", "label": ["Node"]}
    assert "error" not in out


def test_get_node_by_id_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_node_by_id("n1", id_key="invalid-key")
    assert "error" in out
    assert "node" in out
    assert out["node"] is None


def test_get_neighbors_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_neighbors returns mock nodes/relationships."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_neighbors("n1")
    assert "nodes" in out
    assert "relationships" in out
    assert len(out["nodes"]) >= 1
    assert out["relationships"][0]["start"] == "n1"


def test_get_neighbors_invalid_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid direction returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_neighbors("n1", direction="invalid")
    assert "error" in out
    assert "direction" in out["error"].lower()


def test_get_neighbors_invalid_relationship_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid relationship_type (non-identifier) returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_neighbors("n1", relationship_type="bad-type")
    assert "error" in out


def test_get_graph_schema_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_graph_schema returns mock labels/types."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_graph_schema()
    assert "node_labels" in out
    assert "relationship_types" in out
    assert out["node_labels"] == ["Node"]
    assert out["relationship_types"] == []


def test_get_node_by_id_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for kg_tool.get_node_by_id with id_val."""
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer

    monkeypatch.delenv("NEO4J_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    result = client.call_tool("kg_tool.get_node_by_id", {"id_val": "x", "id_key": "id"})
    assert "node" in result
    assert result["node"]["id"] == "x"


def test_get_capabilities_includes_kg_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_capabilities returns tools list including kg_tool community helpers."""
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
    assert "kg_tool.get_node_by_id" in result["tools"]
    assert "kg_tool.get_neighbors" in result["tools"]
    assert "kg_tool.get_graph_schema" in result["tools"]
    assert "kg_tool.shortest_path" in result["tools"]
    assert "kg_tool.get_similar_nodes" in result["tools"]
    assert "kg_tool.fulltext_search" in result["tools"]
    assert "kg_tool.bulk_export" in result["tools"]
    assert "kg_tool.bulk_create_nodes" in result["tools"]


def test_shortest_path_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, shortest_path returns one mock path."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.shortest_path("a", "b")
    assert "paths" in out
    assert len(out["paths"]) == 1
    assert out["paths"][0]["nodes"][0]["id"] == "a"
    assert out["paths"][0]["nodes"][1]["id"] == "b"
    assert out["paths"][0]["relationships"][0]["start"] == "a"
    assert out["paths"][0]["relationships"][0]["end"] == "b"


def test_shortest_path_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.shortest_path("a", "b", id_key="bad-key")
    assert "error" in out
    assert out["paths"] == []


def test_get_similar_nodes_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_similar_nodes returns mock nodes with scores."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_similar_nodes("n1", limit=5)
    assert "nodes" in out
    assert len(out["nodes"]) >= 1
    assert "id" in out["nodes"][0]
    assert "score" in out["nodes"][0]


def test_get_similar_nodes_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_similar_nodes("n1", id_key="invalid-key")
    assert "error" in out
    assert out["nodes"] == []


def test_fulltext_search_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, fulltext_search returns mock nodes."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.fulltext_search("myIndex", "query text", limit=10)
    assert "nodes" in out
    assert len(out["nodes"]) >= 1
    assert out["nodes"][0]["id"] == "ft1"


def test_fulltext_search_invalid_index_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid index_name (non-identifier) returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.fulltext_search("invalid-index-name", "q")
    assert "error" in out
    assert out["nodes"] == []


def test_bulk_export_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, bulk_export returns empty data."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_export("MATCH (n) RETURN n LIMIT 1", format="json")
    assert "data" in out
    assert "format" in out
    assert out["format"] == "json"
    assert out["data"] == []


def test_bulk_export_invalid_cypher_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """bulk_export rejects cypher that does not start with MATCH or CALL."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_export("MERGE (n {id: 1}) RETURN n")
    assert "error" in out
    assert "read-only" in out["error"].lower() or "MATCH" in out["error"] or "CALL" in out["error"]


def test_bulk_export_write_keyword_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """bulk_export rejects cypher containing SET/DELETE/etc. as standalone keywords."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_export("MATCH (n) SET n.x = 1 RETURN n")
    assert "error" in out


def test_bulk_export_allows_identifiers_containing_forbidden_substrings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bulk_export allows read-only queries when property/label names contain SET/CREATE/MERGE as substrings."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    for cypher in (
        "MATCH (n) RETURN n.ASSET",
        "MATCH (n) RETURN n.CREATED_AT",
        "MATCH (n) RETURN n.OFFSET LIMIT 1",
        "MATCH (n) RETURN n.MERGE_KEY",
    ):
        out = kg_tool.bulk_export(cypher, format="json")
        assert "error" not in out or "Write" not in str(out.get("error", "")), (
            f"Expected no write-op error for: {cypher!r}, got: {out}"
        )
        assert "data" in out


def test_bulk_create_nodes_mock_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, bulk_create_nodes returns created count."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_create_nodes([{"id": "n1", "name": "Node1"}, {"id": "n2"}])
    assert "created" in out
    assert out["created"] == 2


def test_bulk_create_nodes_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_create_nodes([{"id": "n1"}], id_key="bad-key")
    assert "error" in out
    assert out.get("created") == 0


def test_kg_deferred_tools_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for shortest_path, get_similar_nodes, fulltext_search, bulk_export, bulk_create_nodes."""
    from mcp.mcp_client import MCPClient
    from mcp.mcp_server import MCPServer

    monkeypatch.delenv("NEO4J_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    r1 = client.call_tool("kg_tool.shortest_path", {"start_id": "a", "end_id": "b"})
    assert "paths" in r1
    r2 = client.call_tool("kg_tool.get_similar_nodes", {"node_id": "x", "limit": 5})
    assert "nodes" in r2
    r3 = client.call_tool("kg_tool.fulltext_search", {"index_name": "idx", "query_string": "q"})
    assert "nodes" in r3
    r4 = client.call_tool("kg_tool.bulk_export", {"cypher": "MATCH (n) RETURN n LIMIT 1"})
    assert "data" in r4 and "format" in r4
    r5 = client.call_tool("kg_tool.bulk_create_nodes", {"nodes": [{"id": "m1"}]})
    assert "created" in r5
