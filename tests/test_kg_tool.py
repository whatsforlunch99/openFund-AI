"""Tests for kg_tool community-common helpers: get_node_by_id, get_neighbors, get_graph_schema."""

from __future__ import annotations

import csv
import os
import tempfile

import pytest


def test_get_node_by_id_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_node_by_id returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_node_by_id("n1")
    assert out.get("error") == "NEO4J_URI not set"
    assert out.get("node") is None


def test_get_node_by_id_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_node_by_id("n1", id_key="invalid-key")
    assert "error" in out
    assert "node" in out
    assert out["node"] is None


def test_get_neighbors_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_neighbors returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_neighbors("n1")
    assert out.get("error") == "NEO4J_URI not set"
    assert out["nodes"] == []
    assert out["relationships"] == []


def test_get_neighbors_invalid_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid direction returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_neighbors("n1", direction="invalid")
    assert "error" in out
    assert "direction" in out["error"].lower()


def test_get_neighbors_invalid_relationship_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid relationship_type (non-identifier) returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_neighbors("n1", relationship_type="bad-type")
    assert "error" in out


def test_get_graph_schema_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_graph_schema returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_graph_schema()
    assert out.get("error") == "NEO4J_URI not set"
    assert out["node_labels"] == []
    assert out["relationship_types"] == []


def test_get_node_by_id_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for kg_tool.get_node_by_id with id_val."""
    from openfund_mcp.mcp_client import MCPClient
    from openfund_mcp.mcp_server import MCPServer

    monkeypatch.delenv("NEO4J_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    result = client.call_tool("kg_tool.get_node_by_id", {"id_val": "x", "id_key": "id"})
    assert result.get("error") == "NEO4J_URI not set"
    assert result.get("node") is None


def test_get_capabilities_includes_kg_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_capabilities returns tools list including kg_tool community helpers."""
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
    assert "kg_tool.get_node_by_id" in result["tools"]
    assert "kg_tool.get_neighbors" in result["tools"]
    assert "kg_tool.get_graph_schema" in result["tools"]
    assert "kg_tool.shortest_path" in result["tools"]
    assert "kg_tool.get_similar_nodes" in result["tools"]
    assert "kg_tool.fulltext_search" in result["tools"]
    assert "kg_tool.bulk_export" in result["tools"]
    assert "kg_tool.bulk_create_nodes" in result["tools"]
    assert "kg_tool.build_graph_csvs" in result["tools"]
    assert "kg_tool.load_graph_csvs_to_neo4j" in result["tools"]


def test_shortest_path_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, shortest_path returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.shortest_path("a", "b")
    assert out.get("error") == "NEO4J_URI not set"
    assert out["paths"] == []


def test_shortest_path_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.shortest_path("a", "b", id_key="bad-key")
    assert "error" in out
    assert out["paths"] == []


def test_get_relations_isolated_node_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Degree-0 nodes do not match (e)-[r]-(other); fallback MATCH (e) still returns the node."""
    from unittest.mock import MagicMock

    from openfund_mcp.tools import kg_tool

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    kg_tool._driver = None

    class FakeNode:
        labels = frozenset({"Company"})

        def __init__(self) -> None:
            self._p = {"id": "000002.SZ", "name": "China Vanke Co., Ltd."}

        def items(self) -> list[tuple[str, str]]:
            return list(self._p.items())

        def get(self, k: str, default: str | None = None) -> str | None:
            return self._p.get(k, default)

    fake_node = FakeNode()
    cyphers: list[str] = []

    def execute_query(cypher: str, parameters_=None, database_=None):
        cyphers.append(cypher)
        if "MATCH (e)-[r]-" in cypher:
            return [], None, None
        if "MATCH (e)" in cypher and "-[r]-" not in cypher:
            return [{"e": fake_node}], None, None
        return [], None, None

    mock_driver = MagicMock()
    mock_driver.execute_query = execute_query
    monkeypatch.setattr(kg_tool, "_get_driver", lambda: (mock_driver, None))

    out = kg_tool.get_relations("China Vanke Co., Ltd.")
    assert "error" not in out
    assert len(out["nodes"]) == 1
    assert out["nodes"][0].get("id") == "000002.SZ"
    assert out["edges"] == []
    assert len(cyphers) == 2


def test_get_similar_nodes_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, get_similar_nodes returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_similar_nodes("n1", limit=5)
    assert out.get("error") == "NEO4J_URI not set"
    assert out["nodes"] == []


def test_get_similar_nodes_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.get_similar_nodes("n1", id_key="invalid-key")
    assert "error" in out
    assert out["nodes"] == []


def test_fulltext_search_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, fulltext_search returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.fulltext_search("myIndex", "query text", limit=10)
    assert out.get("error") == "NEO4J_URI not set"
    assert out["nodes"] == []


def test_fulltext_search_invalid_index_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid index_name (non-identifier) returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.fulltext_search("invalid-index-name", "q")
    assert "error" in out
    assert out["nodes"] == []


def test_fulltext_error_is_missing_index_heuristic() -> None:
    from openfund_mcp.tools import kg_tool

    assert kg_tool._fulltext_error_is_missing_index(
        "There is no such fulltext schema index: company"
    )
    assert not kg_tool._fulltext_error_is_missing_index("connection refused")


def test_entity_compact_alnum_normalizes_punctuation() -> None:
    from openfund_mcp.tools import kg_tool

    assert kg_tool._entity_compact_alnum("China Vanke Co., Ltd.") == "chinavankecoltd"
    assert kg_tool._entity_compact_alnum("China Vanke Co Ltd") == "chinavankecoltd"


def test_fulltext_search_property_fallback_when_index_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If fulltext index is missing, fall back to name/symbol CONTAINS search."""
    from openfund_mcp.tools import kg_tool

    class _FakeDriver:
        def execute_query(self, cypher: str, parameters_=None, database_=None):
            if "fulltext.queryNodes" in cypher:
                raise RuntimeError(
                    "There is no such fulltext schema index: company"
                )
            if "CONTAINS" in cypher and "RETURN DISTINCT n" in cypher:
                return (
                    [{"n": {"id": "v1", "name": "China Vanke Co., Ltd."}}],
                    None,
                    None,
                )
            return ([], None, None)

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(kg_tool, "_get_driver", lambda: (_FakeDriver(), None))

    out = kg_tool.fulltext_search("company", "Vanke", limit=5)
    assert out.get("fallback") == "property_contains"
    assert len(out["nodes"]) == 1
    assert out["nodes"][0].get("name") == "China Vanke Co., Ltd."


def test_bulk_export_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, bulk_export returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_export("MATCH (n) RETURN n LIMIT 1", format="json")
    assert out.get("error") == "NEO4J_URI not set"
    assert out["format"] == "json"
    assert out["data"] == []


def test_bulk_export_invalid_cypher_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """bulk_export rejects cypher that does not start with MATCH or CALL."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_export("MERGE (n {id: 1}) RETURN n")
    assert "error" in out
    assert "read-only" in out["error"].lower() or "MATCH" in out["error"] or "CALL" in out["error"]


def test_bulk_export_write_keyword_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """bulk_export rejects cypher containing SET/DELETE/etc. as standalone keywords."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_export("MATCH (n) SET n.x = 1 RETURN n")
    assert "error" in out


def test_bulk_export_allows_identifiers_containing_forbidden_substrings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bulk_export allows read-only queries when property/label names contain SET/CREATE/MERGE as substrings."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")

    def fake_query_graph(cypher: str, params: dict | None = None) -> dict:
        return {"rows": [], "params": params or {}}

    monkeypatch.setattr(kg_tool, "query_graph", fake_query_graph)
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


def test_bulk_create_nodes_error_when_neo4j_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NEO4J_URI is unset, bulk_create_nodes returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_create_nodes([{"id": "n1", "name": "Node1"}, {"id": "n2"}])
    assert out.get("error") == "NEO4J_URI not set"
    assert out.get("created") == 0


def test_bulk_create_nodes_invalid_id_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid id_key returns error."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    out = kg_tool.bulk_create_nodes([{"id": "n1"}], id_key="bad-key")
    assert "error" in out
    assert out.get("created") == 0


def test_kg_deferred_tools_via_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP dispatch for shortest_path, get_similar_nodes, fulltext_search, bulk_export, bulk_create_nodes."""
    from openfund_mcp.mcp_client import MCPClient
    from openfund_mcp.mcp_server import MCPServer

    monkeypatch.delenv("NEO4J_URI", raising=False)
    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    r1 = client.call_tool("kg_tool.shortest_path", {"start_id": "a", "end_id": "b"})
    assert r1.get("error") == "NEO4J_URI not set"
    assert r1.get("paths") == []
    r2 = client.call_tool("kg_tool.get_similar_nodes", {"node_id": "x", "limit": 5})
    assert r2.get("error") == "NEO4J_URI not set"
    assert r2.get("nodes") == []
    r3 = client.call_tool("kg_tool.fulltext_search", {"index_name": "idx", "query_string": "q"})
    assert r3.get("error") == "NEO4J_URI not set"
    assert r3.get("nodes") == []
    r4 = client.call_tool("kg_tool.bulk_export", {"cypher": "MATCH (n) RETURN n LIMIT 1"})
    assert r4.get("error") == "NEO4J_URI not set"
    assert "data" in r4 and "format" in r4
    r5 = client.call_tool("kg_tool.bulk_create_nodes", {"nodes": [{"id": "m1"}]})
    assert r5.get("error") == "NEO4J_URI not set"
    assert r5.get("created") == 0
    r6 = client.call_tool(
        "kg_tool.build_graph_csvs",
        {"data_dir": "database/graph_data", "output_dir": "database/graph_data/neo4j_export"},
    )
    assert "graph_nodes_csv" in r6 or "error" in r6


def test_build_graph_csvs_canonical_category_reuse_and_dataset_link() -> None:
    """build_graph_csvs canonicalizes category values and links record to dataset node."""
    from openfund_mcp.tools import kg_tool

    with tempfile.TemporaryDirectory() as d:
        data_dir = os.path.join(d, "graph_data")
        os.makedirs(data_dir, exist_ok=True)
        # Minimal funds.csv with mixed-case currency values to verify dedupe.
        with open(os.path.join(data_dir, "funds.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "symbol",
                    "name",
                    "currency",
                    "summary",
                    "category_group",
                    "category",
                    "family",
                    "exchange",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "symbol": "OGKA.SG",
                    "name": "Fund A",
                    "currency": "USD",
                    "summary": "",
                    "category_group": "Equities",
                    "category": "Equity",
                    "family": "Fam1",
                    "exchange": "STU",
                }
            )
            w.writerow(
                {
                    "symbol": "ABC.SG",
                    "name": "Fund B",
                    "currency": "uSD",
                    "summary": "",
                    "category_group": "Equities",
                    "category": "equity",
                    "family": "Fam1",
                    "exchange": "STU",
                }
            )

        # Create empty CSVs for remaining datasets with required headers.
        empty_defs = {
            "equities.csv": [
                "symbol",
                "name",
                "summary",
                "currency",
                "sector",
                "industry_group",
                "industry",
                "exchange",
                "market",
                "country",
                "state",
                "city",
                "zipcode",
                "website",
                "market_cap",
                "isin",
                "cusip",
                "figi",
                "composite_figi",
                "shareclass_figi",
            ],
            "etfs.csv": [
                "symbol",
                "name",
                "currency",
                "summary",
                "category_group",
                "category",
                "family",
                "exchange",
                "isin",
            ],
            "indices.csv": [
                "symbol",
                "name",
                "currency",
                "summary",
                "category_group",
                "category",
                "exchange",
            ],
            "currencies.csv": [
                "symbol",
                "name",
                "base_currency",
                "quote_currency",
                "summary",
                "exchange",
            ],
            "cryptos.csv": [
                "symbol",
                "name",
                "cryptocurrency",
                "currency",
                "summary",
                "exchange",
            ],
            "moneymarkets.csv": ["symbol", "name", "currency", "summary", "family", "exchange"],
        }
        for fn, headers in empty_defs.items():
            with open(os.path.join(data_dir, fn), "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()

        out_dir = os.path.join(d, "out")
        result = kg_tool.build_graph_csvs(data_dir=data_dir, output_dir=out_dir)
        assert result.get("ok") is True
        assert os.path.exists(result["graph_nodes_csv"])
        assert os.path.exists(result["graph_relationships_csv"])
        assert os.path.exists(result["category_inspection_csv"])

        with open(result["graph_nodes_csv"], encoding="utf-8", newline="") as f:
            rnodes = list(csv.DictReader(f))
        gn_ids = {r["node_id:ID"] for r in rnodes}
        assert "ogka_sg" in gn_ids
        assert "funds" in gn_ids
        assert sum(1 for r in rnodes if r["node_id:ID"] == "usd") == 1

        with open(result["graph_relationships_csv"], encoding="utf-8", newline="") as f:
            drel = list(csv.DictReader(f))
        assert any(
            r[":START_ID"] == "ogka_sg"
            and r[":END_ID"] == "funds"
            and r.get(":TYPE") == "BELONGS_TO_DATASET"
            for r in drel
        )
        assert all(":TYPE" in r for r in drel)


def test_load_graph_csvs_to_neo4j_error_when_neo4j_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_graph_csvs_to_neo4j returns error when NEO4J_URI is unset."""
    from openfund_mcp.tools import kg_tool

    monkeypatch.delenv("NEO4J_URI", raising=False)
    with tempfile.TemporaryDirectory() as d:
        nodes_csv = os.path.join(d, "nodes.csv")
        rels_csv = os.path.join(d, "relationships.csv")
        with open(nodes_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "node_id",
                    "node_type",
                    "labels",
                    "symbol",
                    "name",
                    "dataset",
                    "record_type",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "node_id": "record:OGKA.SG",
                    "node_type": "Record",
                    "labels": "Record;FundRecord",
                    "symbol": "OGKA.SG",
                    "name": "Fund A",
                    "dataset": "funds",
                    "record_type": "funds",
                }
            )
        with open(rels_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["start_node_id", "end_node_id", "rel_type", "source_field"],
            )
            w.writeheader()
            w.writerow(
                {
                    "start_node_id": "record:OGKA.SG",
                    "end_node_id": "dataset:funds",
                    "rel_type": "BELONGS_TO_DATASET",
                    "source_field": "dataset",
                }
            )

        out = kg_tool.load_graph_csvs_to_neo4j(nodes_csv, rels_csv, mode="append")
        assert out.get("ok") is False
        assert out.get("error") == "NEO4J_URI not set"
        assert out.get("nodes_loaded") == 0
        assert out.get("relationships_loaded") == 0


def test_validate_graph_csv_bundle_for_neo4j_minimal() -> None:
    """Bundle validator reports ok for a minimal normalized export."""
    from openfund_mcp.tools import kg_tool

    with tempfile.TemporaryDirectory() as d:
        files = {
            "graph_nodes.csv": (
                ["node_id:ID", "symbol", "name", "dataset", "record_type", ":LABEL"],
                [
                    ["currency", "", "currency", "", "", "Dimension"],
                    ["dataset", "", "dataset", "", "", "Dimension"],
                    ["funds", "", "funds", "", "", "Dataset"],
                    ["ogka_sg", "OGKA.SG", "Fund A", "funds", "funds", "Record;FundRecord"],
                    ["equity", "", "equity", "", "", "Tag"],
                    ["usd", "", "USD", "", "", "Currency"],
                ],
            ),
            "graph_relationships.csv": (
                [":START_ID", ":END_ID", ":TYPE", "source_field"],
                [
                    ["ogka_sg", "funds", "BELONGS_TO_DATASET", ""],
                    ["ogka_sg", "equity", "IN_CATEGORY", "category"],
                    ["ogka_sg", "usd", "DENOMINATED_IN", "currency"],
                    ["usd", "currency", "CURRENCY_IN_DIMENSION", ""],
                    ["funds", "dataset", "DATASET_IN_DIMENSION", ""],
                ],
            ),
        }
        for fn, (headers, rows) in files.items():
            with open(os.path.join(d, fn), "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(headers)
                for row in rows:
                    w.writerow(row)
        out = kg_tool.validate_graph_csv_bundle_for_neo4j(d, sample_limit=5)
        assert out.get("ok") is True
        assert out.get("schema") == "normalized_bundle_v4"
        assert out["node_counts"]["record"] == 1


def test_build_graph_csvs_filters_narrative_category_values() -> None:
    """Narrative-like category text is excluded from category nodes and category rels."""
    from openfund_mcp.tools import kg_tool

    with tempfile.TemporaryDirectory() as d:
        data_dir = os.path.join(d, "graph_data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "funds.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["symbol", "name", "currency", "summary", "category_group", "category", "family", "exchange"],
            )
            w.writeheader()
            w.writerow(
                {
                    "symbol": "AAA.SG",
                    "name": "Fund A",
                    "currency": "USD",
                    "summary": "",
                    "category_group": "Equities",
                    "category": "and (c) lower overall volatility of portfolio returns than would otherwise be experienced by owning securities",
                    "family": "Fam1",
                    "exchange": "STU",
                }
            )
        for fn, headers in {
            "equities.csv": ["symbol", "name", "currency", "sector", "industry_group", "industry", "exchange", "market", "country", "state", "market_cap", "summary"],
            "etfs.csv": ["symbol", "name", "currency", "category_group", "category", "family", "exchange", "summary"],
            "indices.csv": ["symbol", "name", "currency", "category_group", "category", "exchange", "summary"],
            "currencies.csv": ["symbol", "name", "base_currency", "quote_currency", "exchange", "summary"],
            "cryptos.csv": ["symbol", "name", "cryptocurrency", "currency", "exchange", "summary"],
            "moneymarkets.csv": ["symbol", "name", "currency", "family", "exchange", "summary"],
        }.items():
            with open(os.path.join(data_dir, fn), "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()

        out = kg_tool.build_graph_csvs(data_dir=data_dir, output_dir=os.path.join(d, "out"))
        assert out["filtered_narrative_category_values"] >= 1

        with open(out["graph_nodes_csv"], encoding="utf-8", newline="") as f:
            tag_rows = [r for r in csv.DictReader(f) if (r.get(":LABEL") or "") == "Tag"]
        assert all("lower overall volatility" not in (r.get("name") or "") for r in tag_rows)

        with open(out["graph_relationships_csv"], encoding="utf-8", newline="") as f:
            rel_rows = list(csv.DictReader(f))
        assert len(rel_rows) == 0 or all("source_field" in r and ":TYPE" in r for r in rel_rows)


def test_validate_graph_csv_bundle_reports_quality_flags() -> None:
    """Bundle validator reports canonical id and tag quality failures."""
    from openfund_mcp.tools import kg_tool

    with tempfile.TemporaryDirectory() as d:
        files = {
            "graph_nodes.csv": (
                ["node_id:ID", "symbol", "name", "dataset", "record_type", ":LABEL"],
                [
                    ["currency", "", "currency", "", "", "Dimension"],
                    ["dataset", "", "dataset", "", "", "Dimension"],
                    ["funds", "", "funds", "", "", "Dataset"],
                    ["bad.id", "BAD.ID", "Bad", "funds", "funds", "Record;FundRecord"],
                    [
                        "story",
                        "",
                        "this fund aims to provide investment returns according to benchmark policy",
                        "",
                        "",
                        "Tag",
                    ],
                    ["usdx", "", "USDX", "", "", "Currency"],
                ],
            ),
            "graph_relationships.csv": (
                [":START_ID", ":END_ID", ":TYPE", "source_field"],
                [
                    ["bad.id", "funds", "BELONGS_TO_DATASET", ""],
                    ["bad.id", "story", "IN_CATEGORY", "category"],
                    ["bad.id", "usdx", "DENOMINATED_IN", "currency"],
                    ["usdx", "currency", "CURRENCY_IN_DIMENSION", ""],
                    ["funds", "dataset", "DATASET_IN_DIMENSION", ""],
                ],
            ),
        }
        for fn, (headers, rows) in files.items():
            with open(os.path.join(d, fn), "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(headers)
                for row in rows:
                    w.writerow(row)
        out = kg_tool.validate_graph_csv_bundle_for_neo4j(d, sample_limit=5)
        assert out["canonical_id_checks"]["non_canonical_id_count"] >= 1
        assert out["tag_quality_checks"]["narrative_like_value_count"] >= 1
        assert out["warnings"]["suspicious_currency_codes_count"] >= 1


def test_build_graph_csvs_china_shared_across_country_and_category() -> None:
    """Same normalized value in country vs category maps to one Tag node."""
    from openfund_mcp.tools import kg_tool

    with tempfile.TemporaryDirectory() as d:
        data_dir = os.path.join(d, "graph_data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "funds.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "symbol",
                    "name",
                    "currency",
                    "summary",
                    "category_group",
                    "category",
                    "family",
                    "exchange",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "symbol": "F1.SG",
                    "name": "F1",
                    "currency": "USD",
                    "summary": "",
                    "category_group": "Asia",
                    "category": "China",
                    "family": "Fam",
                    "exchange": "X",
                }
            )
        eq_headers = [
            "symbol",
            "name",
            "summary",
            "currency",
            "sector",
            "industry_group",
            "industry",
            "exchange",
            "market",
            "country",
            "state",
            "city",
            "zipcode",
            "website",
            "market_cap",
            "isin",
            "cusip",
            "figi",
            "composite_figi",
            "shareclass_figi",
        ]
        with open(os.path.join(data_dir, "equities.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=eq_headers)
            w.writeheader()
            row = {h: "" for h in eq_headers}
            row.update(
                {
                    "symbol": "E1.US",
                    "name": "E1",
                    "currency": "USD",
                    "country": "china",
                    "exchange": "NYSE",
                }
            )
            w.writerow(row)
        for fn, headers in {
            "etfs.csv": [
                "symbol",
                "name",
                "currency",
                "summary",
                "category_group",
                "category",
                "family",
                "exchange",
                "isin",
            ],
            "indices.csv": [
                "symbol",
                "name",
                "currency",
                "summary",
                "category_group",
                "category",
                "exchange",
            ],
            "currencies.csv": [
                "symbol",
                "name",
                "base_currency",
                "quote_currency",
                "summary",
                "exchange",
            ],
            "cryptos.csv": [
                "symbol",
                "name",
                "cryptocurrency",
                "currency",
                "summary",
                "exchange",
            ],
            "moneymarkets.csv": ["symbol", "name", "currency", "summary", "family", "exchange"],
        }.items():
            with open(os.path.join(data_dir, fn), "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                w.writeheader()

        out = kg_tool.build_graph_csvs(data_dir=data_dir, output_dir=os.path.join(d, "out"))
        assert out.get("ok") is True
        with open(out["graph_nodes_csv"], encoding="utf-8", newline="") as f:
            tags = list(csv.DictReader(f))
        china_tags = [r for r in tags if r.get("node_id:ID") == "china"]
        assert len(china_tags) == 1
        with open(out["graph_relationships_csv"], encoding="utf-8", newline="") as f:
            rels = list(csv.DictReader(f))
        china_rels = [r for r in rels if r.get(":END_ID") == "china"]
        assert {r[":END_ID"] for r in china_rels} == {"china"}
        src = {(r[":START_ID"], r["source_field"]) for r in china_rels}
        assert ("f1_sg", "category") in src
        assert ("e1_us", "country") in src
