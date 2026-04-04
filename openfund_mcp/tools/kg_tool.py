"""Knowledge graph queries via Neo4j (MCP tool)."""

from __future__ import annotations

import logging
import os
import re
import csv
import json
from typing import Any, Optional

from openfund_mcp.tools.kg_graph_schema_constants import (
    CATEGORY_FIELDS as _CATEGORY_FIELDS,
    DATASET_FILES as _DATASET_FILES,
    DIMENSION_REL as _DIMENSION_REL,
)

logger = logging.getLogger(__name__)

# Safe identifier for Cypher (label, property key): alphanumeric and underscore only.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_NEO4J_UNSET = "NEO4J_URI not set"

_driver = None


def _norm_value(v: Any) -> str:
    return str(v or "").strip().lower()


def _record_labels_for_dataset(dataset: str) -> str:
    mapping = {
        "funds": "FundRecord",
        "equities": "EquityRecord",
        "etfs": "EtfRecord",
        "indices": "IndexRecord",
        "currencies": "CurrencyRecord",
        "cryptos": "CryptoRecord",
        "moneymarkets": "MoneyMarketRecord",
    }
    return "Record;" + mapping.get(dataset, "AssetRecord")


def _get_driver():
    """Create or return Neo4j driver when NEO4J_URI is set. Lazy import. Returns (driver, error_msg)."""
    global _driver
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return None, None
    if _driver is not None:
        return _driver, None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return None, "Neo4j driver not installed. Run: pip install -e '.[backends]'"
    user = os.environ.get("NEO4J_USER", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    try:
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        return _driver, None
    except Exception as e:
        logger.exception("kg_tool: failed to create Neo4j driver: %s", e)
        return None, f"Neo4j connection failed: {e}"


def _node_to_dict(node: Any) -> dict[str, Any]:
    """Convert Neo4j Node to a plain dict. Prefer node property id/name for output 'id' when present."""
    if node is None:
        return {}
    nid = getattr(node, "element_id", None) or getattr(node, "id", None) or str(node)
    labels = list(getattr(node, "labels", []))
    out: dict[str, Any] = {"label": labels}
    # Use node's id or name property when present so get_relations returns same shape as demo.
    if hasattr(node, "items"):
        out["id"] = node.get("node_id") or node.get("id") or node.get("name") or nid
        for k, v in node.items():
            if k != "label":
                out[k] = v
    else:
        out["id"] = nid
    return out


def query_graph(cypher: str, params: Optional[dict] = None) -> dict:
    """
    Execute a Cypher query against Neo4j.

    Args:
        cypher: Cypher query string. Use $paramName for parameters.
        params: Optional query parameters (dict). Keys match $paramName in Cypher.

    Returns:
        Dict with nodes, edges, and/or rows. Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", ...}.
    """
    if not os.environ.get("NEO4J_URI"):
        return {
            "error": _NEO4J_UNSET,
            "nodes": [],
            "edges": [],
            "params": params or {},
        }
    driver, err = _get_driver()
    if driver is None:
        return {
            "error": err or "Neo4j driver not available or connection failed.",
            "nodes": [],
            "edges": [],
            "params": params or {},
        }
    params = params or {}
    try:
        # Execute Cypher with params; convert Node/Relationship in each record to plain dicts
        records, summary, keys = driver.execute_query(
            cypher,
            parameters_=params,
            database_=os.environ.get("NEO4J_DATABASE", "neo4j"),
        )
        rows = []
        for record in records:
            row = {}
            for i, key in enumerate(keys):
                val = record[key]
                if hasattr(val, "element_id"):  # Node
                    row[key] = _node_to_dict(val)
                elif hasattr(val, "type"):  # Relationship
                    row[key] = {
                        "type": val.type,
                        "start": _node_to_dict(getattr(val, "start_node", None)),
                        "end": _node_to_dict(getattr(val, "end_node", None)),
                    }
                else:
                    row[key] = val
            rows.append(row)
        return {"rows": rows, "params": params}
    except Exception as e:
        logger.exception("kg_tool.query_graph failed: %s", e)
        return {"error": str(e), "nodes": [], "edges": [], "params": params}


def get_all_nodes(label: Optional[str] = None) -> dict:
    """
    Return all nodes, optionally filtered by label. Reuses query_graph.

    Args:
        label: Optional node label (e.g. "Fund"). Must be a valid identifier.

    Returns:
        Same shape as query_graph: nodes/edges/rows/params on success, error key on failure.
    """
    if label is not None and not _IDENTIFIER_RE.match(label):
        return {
            "error": "Invalid label: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
            "edges": [],
            "rows": [],
            "params": {},
        }
    if label:
        cypher = "MATCH (n:" + label + ") RETURN n"
    else:
        cypher = "MATCH (n) RETURN n"
    return query_graph(cypher, None)


def get_all_relationships(limit: Optional[int] = None) -> dict:
    """
    Return relationship types and start/end nodes. Reuses query_graph.

    Args:
        limit: Optional maximum number of relationships to return.

    Returns:
        Same shape as query_graph: rows (rel_type, start, end), params; or error.
    """
    cypher = "MATCH ()-[r]->() RETURN type(r) AS rel_type, startNode(r) AS start, endNode(r) AS end"
    params: Optional[dict] = None
    if limit is not None:
        cypher += " LIMIT $limit"
        params = {"limit": int(limit)}
    return query_graph(cypher, params)


def update_node(id_val: str, props: dict, id_key: str = "id") -> dict:
    """
    MERGE node by id_key=id_val and SET props. Reuses query_graph.

    Args:
        id_val: Value of the id property.
        props: Properties to set (merged with existing).
        id_key: Property name used as id (default "id"). Must be a valid identifier.

    Returns:
        Same result shape as query_graph (rows with updated node, or error).
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
            "edges": [],
            "rows": [],
            "params": {},
        }
    cypher = "MERGE (n {" + id_key + ": $id_val}) SET n += $props RETURN n"
    return query_graph(cypher, {"id_val": id_val, "props": props or {}})


def delete_node(id_val: str, id_key: str = "id") -> dict:
    """
    MATCH node by id_key=id_val and DETACH DELETE. Reuses query_graph.

    Args:
        id_val: Value of the id property.
        id_key: Property name used as id (default "id"). Must be a valid identifier.

    Returns:
        {"ok": true} on success, {"error": "..."} on failure.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore)."
        }
    cypher = "MATCH (n {" + id_key + ": $id_val}) DETACH DELETE n"
    result = query_graph(cypher, {"id_val": id_val})
    if result.get("error"):
        return {"error": result["error"]}
    return {"ok": True}


def get_node_by_id(id_val: str, id_key: str = "id") -> dict:
    """
    Look up a single node by id_key property. Thin wrapper over query_graph.

    Args:
        id_val: Value of the id property.
        id_key: Property name used as id (default "id"). Must be a valid identifier.

    Returns:
        {"node": {...}} on success (node as dict); {"error": "..."} when not found or failure.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", "node": None}.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "node": None,
        }
    if not os.environ.get("NEO4J_URI"):
        return {"error": _NEO4J_UNSET, "node": None}
    cypher = "MATCH (n {" + id_key + ": $id_val}) RETURN n"
    result = query_graph(cypher, {"id_val": id_val})
    if result.get("error"):
        return {"error": result["error"], "node": None}
    rows = result.get("rows", [])
    if not rows or "n" not in rows[0]:
        return {"error": "Node not found", "node": None}
    return {"node": rows[0]["n"]}


def get_neighbors(
    node_id: str,
    id_key: str = "id",
    direction: str = "both",
    relationship_type: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """
    Return 1-hop neighbors of a node. Optional relationship type filter; direction in/out/both.

    Args:
        node_id: Value of the node's id property.
        id_key: Property name used as id (default "id"). Must be a valid identifier.
        direction: "in", "out", or "both".
        relationship_type: Optional filter on relationship type (valid identifier).
        limit: Max number of neighbor nodes to return (default 100).

    Returns:
        {"nodes": [...], "relationships": [{"type": ..., "start": id, "end": id}, ...]}.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", ...}.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
            "relationships": [],
        }
    if relationship_type is not None and not _IDENTIFIER_RE.match(relationship_type):
        return {
            "error": "Invalid relationship_type: must be a valid identifier.",
            "nodes": [],
            "relationships": [],
        }
    if direction not in ("in", "out", "both"):
        return {
            "error": "direction must be one of: in, out, both",
            "nodes": [],
            "relationships": [],
        }
    if not os.environ.get("NEO4J_URI"):
        return {
            "error": _NEO4J_UNSET,
            "nodes": [],
            "relationships": [],
        }
    # Build parameterized Cypher
    if direction == "out":
        pattern = "(start {" + id_key + ": $id_val})-[r]->(n)"
    elif direction == "in":
        pattern = "(start {" + id_key + ": $id_val})<-[r]-(n)"
    else:
        pattern = "(start {" + id_key + ": $id_val})-[r]-(n)"
    cypher = "MATCH " + pattern
    if relationship_type is not None:
        cypher += " WHERE type(r) = $rel_type"
    cypher += " RETURN n, type(r) AS rel_type LIMIT $limit"
    params: dict = {"id_val": node_id, "limit": int(limit)}
    if relationship_type is not None:
        params["rel_type"] = relationship_type
    result = query_graph(cypher, params)
    if result.get("error"):
        return {"error": result["error"], "nodes": [], "relationships": []}
    nodes = []
    relationships = []
    seen_nodes: set[str] = set()
    for row in result.get("rows", []):
        n = row.get("n")
        rel_type = row.get("rel_type", "")
        if not n:
            continue
        node_id_out = n.get("id") or n.get("name") or ""
        if node_id_out and node_id_out not in seen_nodes:
            nodes.append(n)
            seen_nodes.add(node_id_out)
        relationships.append({"type": rel_type, "start": node_id, "end": node_id_out})
    return {"nodes": nodes, "relationships": relationships}


def get_graph_schema() -> dict:
    """
    List node labels and relationship types in the graph.

    Returns:
        {"node_labels": [...], "relationship_types": [...]}.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", ...}.
    """
    if not os.environ.get("NEO4J_URI"):
        return {
            "error": _NEO4J_UNSET,
            "node_labels": [],
            "relationship_types": [],
        }
    driver, err = _get_driver()
    if driver is None:
        return {
            "error": err or "Neo4j driver not available.",
            "node_labels": [],
            "relationship_types": [],
        }
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    try:
        # MATCH (n) RETURN DISTINCT labels(n) then flatten; MATCH ()-[r]->() RETURN DISTINCT type(r)
        labels_result, _, _ = driver.execute_query(
            "MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label",
            database_=db,
        )
        node_labels = [r["label"] for r in labels_result] if labels_result else []
        rel_result, _, _ = driver.execute_query(
            "MATCH ()-[r]->() RETURN DISTINCT type(r) AS t",
            database_=db,
        )
        relationship_types = [r["t"] for r in rel_result] if rel_result else []
        return {"node_labels": sorted(node_labels), "relationship_types": sorted(relationship_types)}
    except Exception as e:
        logger.exception("kg_tool.get_graph_schema failed: %s", e)
        return {
            "error": str(e),
            "node_labels": [],
            "relationship_types": [],
        }


def shortest_path(
    start_id: str,
    end_id: str,
    id_key: str = "id",
    relationship_type: Optional[str] = None,
    max_depth: int = 15,
) -> dict:
    """
    Find one or more shortest paths between two nodes (unweighted). Uses Neo4j shortestPath().

    Args:
        start_id: Start node id value.
        end_id: End node id value.
        id_key: Property name used as id (default "id"). Must be a valid identifier.
        relationship_type: Optional filter on relationship type (valid identifier).
        max_depth: Maximum path length (default 15).

    Returns:
        {"paths": [{"nodes": [...], "relationships": [...]}, ...]}. If no path: {"paths": []}.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", "paths": []}.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "paths": [],
        }
    if relationship_type is not None and not _IDENTIFIER_RE.match(relationship_type):
        return {
            "error": "Invalid relationship_type: must be a valid identifier.",
            "paths": [],
        }
    max_depth = max(1, min(int(max_depth), 30))
    if not os.environ.get("NEO4J_URI"):
        return {"error": _NEO4J_UNSET, "paths": []}
    driver, err = _get_driver()
    if driver is None:
        return {"error": err or "Neo4j driver not available.", "paths": []}
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    # Build Cypher with validated identifiers (id_key and relationship_type)
    where_clause = f"a.{id_key} = $start_id AND b.{id_key} = $end_id"
    if relationship_type:
        rel_pattern = f"(a)-[:{relationship_type}*..{max_depth}]-(b)"
    else:
        rel_pattern = f"(a)-[*..{max_depth}]-(b)"
    cypher = (
        f"MATCH (a), (b) WHERE {where_clause} WITH a, b "
        f"MATCH path = shortestPath({rel_pattern}) RETURN path"
    )
    try:
        records, _, _ = driver.execute_query(
            cypher,
            parameters_={"start_id": start_id, "end_id": end_id},
            database_=db,
        )
        paths = []
        for record in records:
            path = record.get("path")
            if path is None:
                continue
            nodes = []
            relationships = []
            path_nodes = getattr(path, "nodes", []) or []
            path_rels = getattr(path, "relationships", []) or []
            for node in path_nodes:
                nodes.append(_node_to_dict(node))
            for rel in path_rels:
                start_node = getattr(rel, "start_node", None)
                end_node = getattr(rel, "end_node", None)
                rel_type = getattr(rel, "type", "")
                s_id = _node_to_dict(start_node).get("id") or ""
                e_id = _node_to_dict(end_node).get("id") or ""
                relationships.append({"type": rel_type, "start": s_id, "end": e_id})
            paths.append({"nodes": nodes, "relationships": relationships})
        return {"paths": paths}
    except Exception as e:
        logger.exception("kg_tool.shortest_path failed: %s", e)
        return {"error": str(e), "paths": []}


def get_similar_nodes(node_id: str, id_key: str = "id", limit: int = 10) -> dict:
    """
    "Nodes similar to X" by shared neighbors: 1-hop neighbors of node_id, then their 1-hop
    neighbors; count occurrences (excluding node_id); return top `limit` nodes.

    Args:
        node_id: Source node id value.
        id_key: Property name used as id (default "id"). Must be a valid identifier.
        limit: Maximum number of similar nodes to return (default 10).

    Returns:
        {"nodes": [{"id": ..., "score": count}, ...]}. When NEO4J_URI is unset, returns error.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
        }
    limit = max(1, min(int(limit), 100))
    if not os.environ.get("NEO4J_URI"):
        return {"error": _NEO4J_UNSET, "nodes": []}
    out = get_neighbors(node_id, id_key=id_key, limit=500)
    if out.get("error"):
        return {"error": out["error"], "nodes": []}
    neighbors = out.get("nodes", [])
    if not neighbors:
        return {"nodes": []}
    # Count 2-hop nodes (neighbors of neighbors), excluding node_id
    counts: dict[str, int] = {}
    for n in neighbors:
        nid = n.get("id") or n.get("name")
        if not nid or nid == node_id:
            continue
        neighbor_out = get_neighbors(str(nid), id_key=id_key, limit=200)
        if neighbor_out.get("error"):
            continue
        for m in neighbor_out.get("nodes", []):
            mid = m.get("id") or m.get("name")
            if not mid or mid == node_id:
                continue
            counts[mid] = counts.get(mid, 0) + 1
    # Sort by score desc, take top limit
    sorted_nodes = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    return {"nodes": [{"id": nid, "score": score} for nid, score in sorted_nodes]}


def _fulltext_fallback_name_symbol_search(
    driver: Any, db: str, query_string: str, limit: int
) -> list[dict[str, Any]]:
    """MATCH nodes where name or symbol CONTAINS query (no fulltext index required)."""
    q = (query_string or "").strip()
    if not q:
        return []
    q = q[:500]
    cypher = """
    MATCH (n)
    WHERE (n.name IS NOT NULL AND toLower(toString(n.name)) CONTAINS toLower($q))
       OR (n.symbol IS NOT NULL AND toLower(toString(n.symbol)) CONTAINS toLower($q))
    RETURN DISTINCT n LIMIT $limit
    """
    records, _, _ = driver.execute_query(
        cypher,
        parameters_={"q": q, "limit": limit},
        database_=db,
    )
    out: list[dict[str, Any]] = []
    for record in records:
        node = record.get("n")
        if node is not None:
            out.append(_node_to_dict(node))
    return out


def _fulltext_error_is_missing_index(msg: str) -> bool:
    lower = (msg or "").lower()
    return (
        "no such fulltext" in lower
        or "fulltext schema index" in lower
        or "illegalargumentexception" in lower
    )


def fulltext_search(index_name: str, query_string: str, limit: int = 50) -> dict:
    """
    Query nodes via Neo4j full-text index: db.index.fulltext.queryNodes.

    Args:
        index_name: Name of the fulltext index (valid identifier).
        query_string: Search string (passed as parameter).
        limit: Maximum nodes to return (default 50).

    Returns:
        {"nodes": [...]} using _node_to_dict. On missing index or failure: {"error": "..."}.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", "nodes": []}.
    """
    if not _IDENTIFIER_RE.match(index_name):
        return {
            "error": "Invalid index_name: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
        }
    limit = max(1, min(int(limit), 200))
    if not os.environ.get("NEO4J_URI"):
        return {"error": _NEO4J_UNSET, "nodes": []}
    driver, err = _get_driver()
    if driver is None:
        return {"error": err or "Neo4j driver not available.", "nodes": []}
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    cypher = "CALL db.index.fulltext.queryNodes($indexName, $queryString) YIELD node RETURN node LIMIT $limit"
    try:
        records, _, _ = driver.execute_query(
            cypher,
            parameters_={"indexName": index_name, "queryString": query_string, "limit": limit},
            database_=db,
        )
        nodes = []
        for record in records:
            node = record.get("node")
            if node is not None:
                nodes.append(_node_to_dict(node))
        return {"nodes": nodes}
    except Exception as e:
        err_text = str(e)
        if _fulltext_error_is_missing_index(err_text):
            logger.warning(
                "kg_tool.fulltext_search: index %r missing or invalid; using name/symbol CONTAINS fallback",
                index_name,
            )
            try:
                nodes = _fulltext_fallback_name_symbol_search(
                    driver, db, query_string, limit
                )
                return {
                    "nodes": nodes,
                    "fallback": "property_contains",
                    "index_name": index_name,
                }
            except Exception as e2:
                logger.warning("kg_tool.fulltext_search fallback failed: %s", e2)
                return {
                    "error": f"Fulltext index unavailable ({err_text}); fallback failed: {e2}",
                    "nodes": [],
                }
        logger.warning("kg_tool.fulltext_search failed: %s", e)
        return {"error": err_text, "nodes": []}


def bulk_export(
    cypher: str,
    params: Optional[dict] = None,
    format: str = "json",
    row_limit: int = 1000,
) -> dict:
    """
    Run a read-only Cypher query (MATCH/CALL only) and return result rows as JSON or CSV.

    Args:
        cypher: Cypher query; must start with MATCH or CALL (validated).
        params: Optional query parameters.
        format: "json" (list of dicts) or "csv".
        row_limit: Maximum rows to return (default 1000).

    Returns:
        {"data": ..., "format": "json"|"csv"}. When NEO4J_URI is unset, returns error.
    """
    stripped = (cypher or "").strip().upper()
    if not stripped.startswith(("MATCH", "CALL")):
        return {
            "error": "Only read-only queries allowed: cypher must start with MATCH or CALL.",
            "data": [] if format == "json" else "",
            "format": format,
        }
    for forbidden in ("MERGE", "SET", "DELETE", "DETACH", "CREATE", "REMOVE", "DROP"):
        if re.search(r"\b" + re.escape(forbidden) + r"\b", stripped):
            return {
                "error": f"Write operations not allowed (e.g. {forbidden}).",
                "data": [] if format == "json" else "",
                "format": format,
            }
    row_limit = max(1, min(int(row_limit), 10000))
    if not os.environ.get("NEO4J_URI"):
        return {
            "error": _NEO4J_UNSET,
            "data": [] if format == "json" else "",
            "format": format,
        }
    params = dict(params or {})
    params["_row_limit"] = row_limit
    # Append LIMIT if not present
    cypher_normalized = cypher.strip()
    if "LIMIT" not in cypher_normalized.upper():
        cypher_normalized += " LIMIT $_row_limit"
    result = query_graph(cypher_normalized, params)
    if result.get("error"):
        return {"error": result["error"], "data": [] if format == "json" else "", "format": format}
    rows = result.get("rows", [])[:row_limit]
    # Serialize row values (nodes/rels to dicts)
    serializable = []
    for row in rows:
        out_row = {}
        for k, v in row.items():
            if hasattr(v, "items") and not isinstance(v, dict):
                out_row[k] = _node_to_dict(v) if hasattr(v, "element_id") else dict(v)
            elif hasattr(v, "type"):
                out_row[k] = {
                    "type": v.type,
                    "start": _node_to_dict(getattr(v, "start_node", None)),
                    "end": _node_to_dict(getattr(v, "end_node", None)),
                }
            else:
                out_row[k] = v
        serializable.append(out_row)
    if format == "csv":
        import csv
        import io
        if not serializable:
            data = ""
        else:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(serializable[0].keys()))
            writer.writeheader()
            for r in serializable:
                writer.writerow({k: str(v) for k, v in r.items()})
            data = buf.getvalue()
        return {"data": data, "format": "csv"}
    return {"data": serializable, "format": "json"}


def bulk_create_nodes(
    nodes: list[dict],
    label: Optional[str] = None,
    id_key: str = "id",
) -> dict:
    """
    For each node dict, MERGE (n:Label {id_key: val}) SET n += props. Idempotent.

    Args:
        nodes: List of node dicts; each must contain id_key (or "id").
        label: Optional node label (valid identifier if provided).
        id_key: Property name used as id (default "id"). Must be a valid identifier.

    Returns:
        {"created": n} on success; {"created": 0, "error": "..."} on failure.
        When NEO4J_URI is unset, returns {"error": "NEO4J_URI not set", "created": 0}.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "created": 0,
        }
    if label is not None and not _IDENTIFIER_RE.match(label):
        return {
            "error": "Invalid label: must be a valid identifier (alphanumeric, underscore).",
            "created": 0,
        }
    if not os.environ.get("NEO4J_URI"):
        return {"error": _NEO4J_UNSET, "created": 0}
    driver, err = _get_driver()
    if driver is None:
        return {"error": err or "Neo4j driver not available.", "created": 0}
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    label_part = (":" + label) if label else ""
    created = 0
    for node in nodes or []:
        id_val = node.get(id_key) or node.get("id")
        if id_val is None:
            return {"created": created, "error": f"Node missing '{id_key}' or 'id'."}
        props = {k: v for k, v in node.items() if k != id_key and k != "id"}
        cypher = f"MERGE (n{label_part} {{{id_key}: $id_val}}) SET n += $props RETURN n"
        try:
            driver.execute_query(
                cypher,
                parameters_={"id_val": id_val, "props": props or {}},
                database_=db,
            )
            created += 1
        except Exception as e:
            logger.exception("kg_tool.bulk_create_nodes failed for node %s: %s", id_val, e)
            return {"created": created, "error": str(e)}
    return {"created": created}


def _entity_compact_alnum(s: str) -> str:
    """Lowercase alphanumerics only — matches planner text to stored names despite punctuation."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# Exact match first (symbol, node_id, name, element id) — avoids Neo4j warnings on missing `id` property.
_GET_RELATIONS_PREDICATE_EXACT = """trim(toString($entity)) <> '' AND (
        (e.node_id IS NOT NULL AND toLower(toString(e.node_id)) = toLower(trim(toString($entity))))
        OR (e.symbol IS NOT NULL AND toLower(trim(toString(e.symbol))) = toLower(trim(toString($entity))))
        OR (e.name IS NOT NULL AND toLower(trim(toString(e.name))) = toLower(trim(toString($entity))))
        OR toString(elementId(e)) = trim(toString($entity))
    )"""

# Fuzzy / substring fallback when exact phase returns nothing (no `e.id`; graph uses node_id).
_GET_RELATIONS_PREDICATE_FUZZY = """trim(toString($entity)) <> '' AND (
        (
            size($entity_compact) >= 4
            AND e.name IS NOT NULL
            AND (
                replace(replace(replace(lower(trim(toString(e.name))), '.', ''), ',', ''), ' ', '') CONTAINS $entity_compact
                OR $entity_compact CONTAINS replace(replace(replace(lower(trim(toString(e.name))), '.', ''), ',', ''), ' ', '')
            )
        )
        OR (
            e.symbol IS NOT NULL
            AND size(trim(toString(e.symbol))) >= 3
            AND toLower(trim(toString($entity))) CONTAINS toLower(trim(toString(e.symbol)))
        )
    )"""

_GET_RELATIONS_DATASET_FILTER = """ AND ($prefer_dataset = '' OR coalesce(toString(e.dataset), '') = $prefer_dataset)"""


def get_relations(entity: str, prefer_dataset: str = "") -> dict:
    """
    Get relations for an entity (e.g. fund, manager).

    Args:
        entity: Entity identifier.
        prefer_dataset: Optional graph dataset bucket (e.g. ``equities``, ``etfs``) to bias fuzzy matches.

    Returns:
        Dict with nodes, edges, and entity. When NEO4J_URI is unset, returns error.
        On error returns {"error": "..."}.
        Nodes with **no** incident relationships are still returned via a fallback
        ``MATCH (e) WHERE ...`` when the one-hop pattern matches nothing.
    """
    if not os.environ.get("NEO4J_URI"):
        return {
            "error": _NEO4J_UNSET,
            "nodes": [],
            "edges": [],
            "entity": entity,
        }
    driver, err = _get_driver()
    if driver is None:
        return {
            "error": err or "Neo4j driver not available.",
            "nodes": [],
            "edges": [],
            "entity": entity,
        }
    entity_s = (entity or "").strip()
    ec = _entity_compact_alnum(entity_s)
    if len(ec) < 4:
        ec = ""
    pref_ds = (prefer_dataset or "").strip().lower()
    params = {
        "entity": entity_s,
        "entity_compact": ec,
        "prefer_dataset": pref_ds,
    }
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    ds_clause = _GET_RELATIONS_DATASET_FILTER if pref_ds else ""

    def _run_phase(predicate_body: str) -> tuple[list[dict], list[dict]]:
        where_full = f"({predicate_body}){ds_clause}"
        cypher_rels = f"""
        MATCH (e)-[r]-(other)
        WHERE {where_full}
        RETURN e, type(r) AS rel_type, other
        LIMIT 100
        """
        cypher_isolated = f"""
        MATCH (e)
        WHERE {where_full}
        RETURN e
        LIMIT 25
        """
        nodes: list[dict] = []
        edges: list[dict] = []
        seen: set[str] = set()
        records, _, _ = driver.execute_query(cypher_rels, parameters_=params, database_=db)
        for record in records:
            e, rel_type, other = record["e"], record["rel_type"], record["other"]
            nd_e = _node_to_dict(e)
            nd_o = _node_to_dict(other)
            eid = nd_e.get("id") or ""
            oid = nd_o.get("id") or ""
            if eid and eid not in seen:
                nodes.append(nd_e)
                seen.add(eid)
            if oid and oid not in seen:
                nodes.append(nd_o)
                seen.add(oid)
            edges.append({"source": eid, "target": oid, "type": rel_type})
        if not records:
            rec2, _, _ = driver.execute_query(
                cypher_isolated, parameters_=params, database_=db
            )
            for record in rec2:
                e = record.get("e")
                nd_e = _node_to_dict(e)
                eid = nd_e.get("id") or ""
                if eid and eid not in seen:
                    nodes.append(nd_e)
                    seen.add(eid)
        return nodes, edges

    try:
        nodes, edges = _run_phase(_GET_RELATIONS_PREDICATE_EXACT)
        if not nodes:
            nodes, edges = _run_phase(_GET_RELATIONS_PREDICATE_FUZZY)
        return {"nodes": nodes, "edges": edges, "entity": entity}
    except Exception as e:
        logger.exception("kg_tool.get_relations failed: %s", e)
        return {"error": str(e), "nodes": [], "edges": [], "entity": entity}


def _canonical_slug(v: Any) -> str:
    s = str(v or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


# Dimension parent keys (also used as Dimension node ids).
_DIM_CURRENCY = "currency"
_DIM_DATASET = "dataset"


def _bare_record_id(symbol: str) -> str:
    """Bare Record id from symbol (no record_ prefix)."""
    return _canonical_slug(symbol)


def _bare_dataset_id(dataset: str) -> str:
    """Bare Dataset id (no dataset_ prefix)."""
    return _canonical_slug(dataset)


def _bare_currency_id(code_norm: str) -> str:
    """Bare Currency id (no currency_ prefix)."""
    return _canonical_slug(code_norm)


def _bare_tag_id(value_norm: str) -> str:
    """Bare Tag id: one node per normalized value across categorical fields."""
    return _canonical_slug(value_norm)


def _build_global_id_map(entries: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """
    Map (node_kind, bare_id) -> import id for a single nodes file / global id space.
    When the same bare slug appears for more than one kind, only the first kind (sorted
    alphabetically) keeps the bare id; others get ``{bare}_{kind.lower()}``.
    """
    by_bare: dict[str, set[str]] = {}
    for kind, bare in entries:
        by_bare.setdefault(bare, set()).add(kind)
    out: dict[tuple[str, str], str] = {}
    for bare, kinds_set in sorted(by_bare.items()):
        kinds = sorted(kinds_set)
        if len(kinds) == 1:
            out[(kinds[0], bare)] = bare
            continue
        for i, k in enumerate(kinds):
            if i == 0:
                out[(k, bare)] = bare
            else:
                out[(k, bare)] = f"{bare}_{k.lower()}"
    return out


def _is_narrative_like_category_value(v: str) -> bool:
    """
    Heuristic guard for noisy category text.
    Keep simple, deterministic checks only.
    """
    s = (v or "").strip()
    if not s:
        return False
    if len(s) > 120:
        return True
    lower = s.lower()
    sentence_markers = (
        " aims to ",
        " seeks to ",
        " according to ",
        " investment returns ",
        " lower overall volatility ",
    )
    if any(m in lower for m in sentence_markers):
        return True
    punct = sum(1 for ch in s if ch in ".,;:()")
    if punct >= 4:
        return True
    return False


# Bare import ids: lowercase slug, underscores, digits only.
_BARE_IMPORT_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_SUSPICIOUS_CURRENCY_CODE_RE = re.compile(r"^[a-z]{3}$")


def build_graph_csvs(
    data_dir: str = "database/graph_data",
    output_dir: str = "database/graph_data/neo4j_export",
) -> dict:
    """
    Build normalized Neo4j import CSV bundle (bare ids, global Tag values, Dimension parents).

    Emits:
    - graph_nodes.csv (all node labels in one file; columns: node_id:ID, symbol, name, dataset, record_type, :LABEL)
    - graph_relationships.csv (all edges; columns: :START_ID, :END_ID, :TYPE, source_field)
    - category_inspection.csv
    """
    os.makedirs(output_dir, exist_ok=True)

    graph_nodes_csv = os.path.join(output_dir, "graph_nodes.csv")
    graph_relationships_csv = os.path.join(output_dir, "graph_relationships.csv")
    inspection_csv = os.path.join(output_dir, "category_inspection.csv")

    records: dict[str, dict[str, Any]] = {}
    datasets: dict[str, dict[str, Any]] = {}
    tags: dict[str, dict[str, Any]] = {}
    currencies: dict[str, dict[str, Any]] = {}
    dimensions: dict[str, dict[str, Any]] = {
        _DIM_CURRENCY: {"name": _DIM_CURRENCY},
        _DIM_DATASET: {"name": _DIM_DATASET},
    }

    rel_dataset: set[tuple[str, str]] = set()
    rel_tag: set[tuple[str, str, str, str]] = set()  # rid, tag_id, rel_type, source_field
    rel_cur_denom: set[tuple[str, str]] = set()
    rel_cur_base: set[tuple[str, str]] = set()
    rel_cur_quote: set[tuple[str, str]] = set()
    rel_cur_crypto: set[tuple[str, str]] = set()
    rel_currency_dim: set[tuple[str, str]] = set()
    rel_dataset_dim: set[tuple[str, str]] = set()

    inspection_rows: list[dict[str, Any]] = []
    filtered_narrative_categories = 0

    category_values: dict[tuple[str, str], set[str]] = {}
    category_display: dict[tuple[str, str, str], str] = {}
    tag_display: dict[str, str] = {}

    def _merge_display(existing: str, new: str) -> str:
        a, b = (existing or "").strip(), (new or "").strip()
        if not a:
            return b or new
        if not b:
            return a
        return b if len(b) > len(a) else a

    # 1) scan unique values for inspection; build currency + global tag nodes.
    for dataset, filename in _DATASET_FILES.items():
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path):
            continue
        fields = list(_CATEGORY_FIELDS.get(dataset, []))
        for field in fields:
            category_values.setdefault((dataset, field), set())
        with open(path, encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for field in fields:
                    raw = (row.get(field) or "").strip()
                    if not raw:
                        continue
                    if field not in {
                        "currency",
                        "base_currency",
                        "quote_currency",
                        "cryptocurrency",
                    }:
                        if _is_narrative_like_category_value(raw):
                            filtered_narrative_categories += 1
                            continue
                    norm = _norm_value(raw)
                    if not norm:
                        continue
                    category_values[(dataset, field)].add(norm)
                    key = (dataset, field, norm)
                    if key not in category_display:
                        category_display[key] = raw
                    if field in {
                        "currency",
                        "base_currency",
                        "quote_currency",
                        "cryptocurrency",
                    }:
                        cid = _bare_currency_id(norm)
                        disp = category_display[key]
                        cur = currencies.get(cid)
                        if cur is None:
                            currencies[cid] = {"name": disp}
                        else:
                            cur["name"] = _merge_display(cur.get("name", ""), disp)
                        rel_currency_dim.add((cid, _DIM_CURRENCY))
                    else:
                        tid = _bare_tag_id(norm)
                        tag_display[tid] = _merge_display(tag_display.get(tid, ""), category_display[key])
                        tags.setdefault(tid, {})

    # inspection artifact (per dataset, field)
    for (dataset, field), vals in sorted(category_values.items()):
        sample_values = sorted(list(vals))[:10]
        inspection_rows.append(
            {
                "dataset": dataset,
                "field": field,
                "unique_count": len(vals),
                "sample_values": "|".join(sample_values),
            }
        )
    with open(inspection_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["dataset", "field", "unique_count", "sample_values"]
        )
        writer.writeheader()
        for row in inspection_rows:
            writer.writerow(row)

    for tid in tags:
        tags[tid]["name"] = tag_display.get(tid, "")

    # Dataset nodes + dimension link
    for dataset in _DATASET_FILES:
        did = _bare_dataset_id(dataset)
        datasets[did] = {"name": dataset}
        rel_dataset_dim.add((did, _DIM_DATASET))

    # 4) records and relationships
    for dataset, filename in _DATASET_FILES.items():
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path):
            continue
        fields = list(_CATEGORY_FIELDS.get(dataset, []))
        with open(path, encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = (row.get("symbol") or "").strip()
                if not symbol:
                    continue
                name = (row.get("name") or "").strip()
                rid = _bare_record_id(symbol)
                rec = records.get(
                    rid,
                    {
                        "symbol": symbol,
                        "name": name,
                        "dataset": dataset,
                        "record_type": dataset,
                    },
                )
                if not rec.get("name") and name:
                    rec["name"] = name
                records[rid] = rec

                did = _bare_dataset_id(dataset)
                rel_dataset.add((rid, did))

                for field in fields:
                    raw = (row.get(field) or "").strip()
                    if not raw:
                        continue
                    if field not in {
                        "currency",
                        "base_currency",
                        "quote_currency",
                        "cryptocurrency",
                    }:
                        if _is_narrative_like_category_value(raw):
                            continue
                    norm = _norm_value(raw)
                    if not norm:
                        continue
                    if field == "currency":
                        cid = _bare_currency_id(norm)
                        rel_cur_denom.add((rid, cid))
                    elif field == "base_currency":
                        cid = _bare_currency_id(norm)
                        rel_cur_base.add((rid, cid))
                    elif field == "quote_currency":
                        cid = _bare_currency_id(norm)
                        rel_cur_quote.add((rid, cid))
                    elif field == "cryptocurrency":
                        cid = _bare_currency_id(norm)
                        rel_cur_crypto.add((rid, cid))
                    else:
                        tag_id = _bare_tag_id(norm)
                        _, rel_type = _DIMENSION_REL.get(
                            field, ("CategoryValue", "HAS_CATEGORY_VALUE")
                        )
                        rel_tag.add((rid, tag_id, rel_type, field))

    entries: list[tuple[str, str]] = []
    for rid in records:
        entries.append(("Record", rid))
    for did in datasets:
        entries.append(("Dataset", did))
    for tid in tags:
        entries.append(("Tag", tid))
    for cid in currencies:
        entries.append(("Currency", cid))
    for dk in dimensions:
        entries.append(("Dimension", dk))
    gid_map = _build_global_id_map(entries)

    def gid(kind: str, bare: str) -> str:
        return gid_map[(kind, bare)]

    # 5) single node file + 6) relationship files (global id space)
    node_fieldnames = ["node_id:ID", "symbol", "name", "dataset", "record_type", ":LABEL"]
    graph_rows: list[dict[str, str]] = []
    for dk in sorted(dimensions):
        graph_rows.append(
            {
                "node_id:ID": gid("Dimension", dk),
                "symbol": "",
                "name": dimensions[dk]["name"],
                "dataset": "",
                "record_type": "",
                ":LABEL": "Dimension",
            }
        )
    for did in sorted(datasets):
        d = datasets[did]
        graph_rows.append(
            {
                "node_id:ID": gid("Dataset", did),
                "symbol": "",
                "name": d["name"],
                "dataset": "",
                "record_type": "",
                ":LABEL": "Dataset",
            }
        )
    for rid in sorted(records):
        r = records[rid]
        graph_rows.append(
            {
                "node_id:ID": gid("Record", rid),
                "symbol": r.get("symbol", ""),
                "name": r.get("name", ""),
                "dataset": r.get("dataset", ""),
                "record_type": r.get("record_type", ""),
                ":LABEL": _record_labels_for_dataset(r.get("record_type", "")),
            }
        )
    for cid in sorted(currencies):
        c = currencies[cid]
        graph_rows.append(
            {
                "node_id:ID": gid("Currency", cid),
                "symbol": "",
                "name": c.get("name", ""),
                "dataset": "",
                "record_type": "",
                ":LABEL": "Currency",
            }
        )
    for tid in sorted(tags):
        t = tags[tid]
        graph_rows.append(
            {
                "node_id:ID": gid("Tag", tid),
                "symbol": "",
                "name": t.get("name", ""),
                "dataset": "",
                "record_type": "",
                ":LABEL": "Tag",
            }
        )
    graph_rows.sort(key=lambda row: row["node_id:ID"])
    with open(graph_nodes_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=node_fieldnames)
        w.writeheader()
        for row in graph_rows:
            w.writerow(row)

    unified_rel_rows: list[dict[str, str]] = []
    for s, e in sorted(rel_dataset):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Record", s),
                ":END_ID": gid("Dataset", e),
                ":TYPE": "BELONGS_TO_DATASET",
                "source_field": "",
            }
        )
    for s, e, rtype, sf in sorted(rel_tag):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Record", s),
                ":END_ID": gid("Tag", e),
                ":TYPE": rtype,
                "source_field": sf,
            }
        )
    for s, e in sorted(rel_cur_denom):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Record", s),
                ":END_ID": gid("Currency", e),
                ":TYPE": "DENOMINATED_IN",
                "source_field": "currency",
            }
        )
    for s, e in sorted(rel_cur_base):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Record", s),
                ":END_ID": gid("Currency", e),
                ":TYPE": "HAS_BASE_CURRENCY",
                "source_field": "base_currency",
            }
        )
    for s, e in sorted(rel_cur_quote):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Record", s),
                ":END_ID": gid("Currency", e),
                ":TYPE": "HAS_QUOTE_CURRENCY",
                "source_field": "quote_currency",
            }
        )
    for s, e in sorted(rel_cur_crypto):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Record", s),
                ":END_ID": gid("Currency", e),
                ":TYPE": "TRACKS_CRYPTO",
                "source_field": "cryptocurrency",
            }
        )
    for s, e in sorted(rel_currency_dim):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Currency", s),
                ":END_ID": gid("Dimension", e),
                ":TYPE": "CURRENCY_IN_DIMENSION",
                "source_field": "",
            }
        )
    for s, e in sorted(rel_dataset_dim):
        unified_rel_rows.append(
            {
                ":START_ID": gid("Dataset", s),
                ":END_ID": gid("Dimension", e),
                ":TYPE": "DATASET_IN_DIMENSION",
                "source_field": "",
            }
        )
    unified_rel_rows.sort(
        key=lambda r: (
            r[":START_ID"],
            r[":END_ID"],
            r[":TYPE"],
            r["source_field"],
        )
    )
    with open(graph_relationships_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=[":START_ID", ":END_ID", ":TYPE", "source_field"]
        )
        w.writeheader()
        for row in unified_rel_rows:
            w.writerow(row)

    rel_count = (
        len(rel_dataset)
        + len(rel_tag)
        + len(rel_cur_denom)
        + len(rel_cur_base)
        + len(rel_cur_quote)
        + len(rel_cur_crypto)
        + len(rel_currency_dim)
        + len(rel_dataset_dim)
    )

    import_files = {
        "graph_nodes": graph_nodes_csv,
        "graph_relationships": graph_relationships_csv,
        "category_inspection": inspection_csv,
    }
    import_command = (
        "neo4j-admin database import full "
        f"--nodes={graph_nodes_csv} "
        f"--relationships={graph_relationships_csv}"
        "  # graph_relationships.csv uses :TYPE per row; source_field set where applicable."
    )

    return {
        "ok": True,
        "mode": "normalized_bundle_primary",
        "output_dir": output_dir,
        "graph_nodes_csv": graph_nodes_csv,
        "graph_relationships_csv": graph_relationships_csv,
        "category_inspection_csv": inspection_csv,
        "record_count": len(records),
        "dataset_count": len(datasets),
        "tag_count": len(tags),
        "currency_count": len(currencies),
        "dimension_count": len(dimensions),
        "relationship_count": rel_count,
        "filtered_narrative_category_values": filtered_narrative_categories,
        "import_files": import_files,
        "neo4j_import_command_hint": import_command,
        "category_nodes_csv": graph_nodes_csv,
        "record_to_category_rels_csv": graph_relationships_csv,
        "record_to_currency_rels_csv": graph_relationships_csv,
    }


def load_graph_csvs_to_neo4j(
    nodes_csv: str,
    relationships_csv: str,
    mode: str = "append",
    output_dir: str | None = None,
) -> dict:
    """
    Load graph CSVs into Neo4j using MERGE.

    With output_dir set, loads graph_nodes.csv and graph_relationships.csv from that directory.
    Otherwise loads the given nodes_csv and relationships_csv (ad-hoc two-file format:
    node_id / labels / … and start_node_id / end_node_id / rel_type / source_field).
    """
    if mode != "append":
        return {"error": "Only append mode is supported."}
    # Bundle mode: output_dir; else ad-hoc two-file load.
    if output_dir:
        graph_nodes_csv = os.path.join(output_dir, "graph_nodes.csv")
        graph_relationships_csv = os.path.join(output_dir, "graph_relationships.csv")
        required = [graph_nodes_csv, graph_relationships_csv]
        missing = [p for p in required if not os.path.exists(p)]
        if missing:
            return {"error": f"Missing bundle files: {missing}"}
    else:
        if not os.path.exists(nodes_csv):
            return {"error": f"nodes_csv not found: {nodes_csv}"}
        if not os.path.exists(relationships_csv):
            return {"error": f"relationships_csv not found: {relationships_csv}"}
    if not os.environ.get("NEO4J_URI"):
        return {
            "error": _NEO4J_UNSET,
            "ok": False,
            "nodes_loaded": 0,
            "relationships_loaded": 0,
        }

    driver, err = _get_driver()
    if driver is None:
        return {"error": err or "Neo4j driver not available."}
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    nodes_loaded = 0
    rels_loaded = 0
    # Batch size tuned for lower Bolt round-trip overhead on large bundles.
    # Can be overridden for tuning in different environments.
    try:
        batch_size = max(1000, int(os.environ.get("NEO4J_LOAD_BATCH_SIZE", "10000")))
    except ValueError:
        batch_size = 10000

    def _load_nodes_file(path: str, id_col: str, labels: str, map_props: list[str]) -> tuple[int, str | None]:
        loaded = 0
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                node_id = (row.get(id_col) or "").strip()
                if not node_id:
                    continue
                label_part = ":" + ":".join([x for x in labels.split(";") if _IDENTIFIER_RE.match(x)])
                props = {"node_id": node_id}
                for k in map_props:
                    props[k] = (row.get(k) or "").strip()
                sym = (props.get("symbol") or "").strip()
                props["id"] = sym if sym else node_id
                cypher = f"MERGE (n{label_part} {{node_id: $node_id}}) SET n += $props"
                try:
                    driver.execute_query(
                        cypher,
                        parameters_={"node_id": node_id, "props": props},
                        database_=db,
                    )
                    loaded += 1
                except Exception as e:
                    return loaded, str(e)
        return loaded, None

    def _load_rels_file(path: str, start_col: str, end_col: str, type_col: str, source_col: str | None = None) -> tuple[int, str | None]:
        loaded = 0
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                s = (row.get(start_col) or "").strip()
                e = (row.get(end_col) or "").strip()
                t = (row.get(type_col) or "").strip()
                if not s or not e or not _IDENTIFIER_RE.match(t):
                    continue
                cypher = (
                    "MATCH (a {node_id: $start_id}), (b {node_id: $end_id}) "
                    f"MERGE (a)-[r:{t}]->(b)"
                )
                params = {"start_id": s, "end_id": e}
                if source_col:
                    cypher += " SET r.source_field = $source_field"
                    params["source_field"] = (row.get(source_col) or "").strip()
                try:
                    driver.execute_query(cypher, parameters_=params, database_=db)
                    loaded += 1
                except Exception as e2:
                    return loaded, str(e2)
        return loaded, None

    def _load_rels_fixed_type(
        path: str, start_col: str, end_col: str, rel_type: str
    ) -> tuple[int, str | None]:
        if not _IDENTIFIER_RE.match(rel_type):
            return 0, f"Invalid rel_type: {rel_type}"
        loaded = 0
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                s = (row.get(start_col) or "").strip()
                e = (row.get(end_col) or "").strip()
                if not s or not e:
                    continue
                cypher = (
                    "MATCH (a {node_id: $start_id}), (b {node_id: $end_id}) "
                    f"MERGE (a)-[r:{rel_type}]->(b)"
                )
                try:
                    driver.execute_query(
                        cypher,
                        parameters_={"start_id": s, "end_id": e},
                        database_=db,
                    )
                    loaded += 1
                except Exception as e2:
                    return loaded, str(e2)
        return loaded, None

    def _flush_nodes_batch(label_part: str, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        cypher = (
            f"UNWIND $rows AS row "
            f"MERGE (n{label_part} {{node_id: row.node_id}}) "
            f"SET n += row.props"
        )
        try:
            driver.execute_query(cypher, parameters_={"rows": rows}, database_=db)
            return None
        except Exception as e:
            return str(e)

    def _load_unified_graph_nodes(path: str) -> tuple[int, str | None]:
        loaded = 0
        buckets: dict[str, list[dict[str, Any]]] = {}
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                node_id = (row.get("node_id:ID") or "").strip()
                labels_raw = (row.get(":LABEL") or "").strip()
                if not node_id:
                    continue
                label_tokens = [
                    x.strip()
                    for x in labels_raw.split(";")
                    if x.strip() and _IDENTIFIER_RE.match(x.strip())
                ]
                if not label_tokens:
                    continue
                label_part = ":" + ":".join(label_tokens)
                props = {"node_id": node_id}
                for k in ("symbol", "name", "dataset", "record_type"):
                    props[k] = (row.get(k) or "").strip()
                sym = (props.get("symbol") or "").strip()
                props["id"] = sym if sym else node_id
                payload = {"node_id": node_id, "props": props}
                bucket = buckets.setdefault(label_part, [])
                bucket.append(payload)
                if len(bucket) >= batch_size:
                    err = _flush_nodes_batch(label_part, bucket)
                    if err:
                        return loaded, err
                    loaded += len(bucket)
                    bucket.clear()
        for label_part, bucket in buckets.items():
            err = _flush_nodes_batch(label_part, bucket)
            if err:
                return loaded, err
            loaded += len(bucket)
        return loaded, None

    def _flush_rels_batch(rel_type: str, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        cypher = (
            f"UNWIND $rows AS row "
            f"MATCH (a {{node_id: row.start_id}}), (b {{node_id: row.end_id}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET r.source_field = CASE WHEN row.source_field = '' THEN r.source_field ELSE row.source_field END"
        )
        try:
            driver.execute_query(cypher, parameters_={"rows": rows}, database_=db)
            return None
        except Exception as e:
            return str(e)

    def _load_unified_graph_rels(path: str) -> tuple[int, str | None]:
        loaded = 0
        buckets: dict[str, list[dict[str, Any]]] = {}
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                s = (row.get(":START_ID") or "").strip()
                e = (row.get(":END_ID") or "").strip()
                t = (row.get(":TYPE") or "").strip()
                sf = (row.get("source_field") or "").strip()
                if not s or not e or not t:
                    continue
                if not _IDENTIFIER_RE.match(t):
                    continue
                payload = {"start_id": s, "end_id": e, "source_field": sf}
                bucket = buckets.setdefault(t, [])
                bucket.append(payload)
                if len(bucket) >= batch_size:
                    err = _flush_rels_batch(t, bucket)
                    if err:
                        return loaded, err
                    loaded += len(bucket)
                    bucket.clear()
        for t, bucket in buckets.items():
            err = _flush_rels_batch(t, bucket)
            if err:
                return loaded, err
            loaded += len(bucket)
        return loaded, None

    if output_dir:
        n, err2 = _load_unified_graph_nodes(graph_nodes_csv)
        nodes_loaded += n
        if err2:
            return {"error": err2, "nodes_loaded": nodes_loaded, "relationships_loaded": rels_loaded}

        n, err2 = _load_unified_graph_rels(graph_relationships_csv)
        rels_loaded += n
        if err2:
            return {"error": err2, "nodes_loaded": nodes_loaded, "relationships_loaded": rels_loaded}
    else:
        # legacy single-file mode
        n, err2 = _load_nodes_file(
            nodes_csv,
            "node_id",
            "Node",
            ["node_type", "symbol", "name", "dataset", "record_type"],
        )
        nodes_loaded += n
        if err2:
            return {"error": err2, "nodes_loaded": nodes_loaded, "relationships_loaded": rels_loaded}
        n, err2 = _load_rels_file(
            relationships_csv,
            "start_node_id",
            "end_node_id",
            "rel_type",
            "source_field",
        )
        rels_loaded += n
        if err2:
            return {"error": err2, "nodes_loaded": nodes_loaded, "relationships_loaded": rels_loaded}

    return {
        "ok": True,
        "nodes_loaded": nodes_loaded,
        "relationships_loaded": rels_loaded,
    }


def validate_graph_csvs_for_neo4j(
    nodes_csv: str,
    relationships_csv: str,
    sample_limit: int = 20,
    output_dir: str | None = None,
) -> dict:
    """
    Validate Neo4j import CSVs and return import-risk errors.
    """
    if output_dir:
        return validate_graph_csv_bundle_for_neo4j(output_dir, sample_limit=sample_limit)
    if not os.path.exists(nodes_csv):
        return {"error": f"nodes_csv not found: {nodes_csv}"}
    if not os.path.exists(relationships_csv):
        return {"error": f"relationships_csv not found: {relationships_csv}"}

    node_ids: set[str] = set()
    dup_node_ids: list[str] = []
    empty_node_id_rows = 0
    bad_labels_rows = 0
    node_rows = 0
    with open(nodes_csv, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_rows += 1
            nid = (row.get("node_id") or "").strip()
            labels = (row.get("labels") or "").strip()
            if not nid:
                empty_node_id_rows += 1
                continue
            if nid in node_ids and len(dup_node_ids) < sample_limit:
                dup_node_ids.append(nid)
            node_ids.add(nid)
            if labels:
                for lb in labels.split(";"):
                    s = lb.strip()
                    if s and not _IDENTIFIER_RE.match(s):
                        bad_labels_rows += 1
                        break

    # H1: dangling relationship refs.
    missing_start_refs: list[str] = []
    missing_end_refs: list[str] = []
    # H2: invalid relationship types.
    invalid_rel_types: list[str] = []
    # H3: duplicate relationships.
    rel_seen: set[tuple[str, str, str]] = set()
    duplicate_rels = 0
    rel_rows = 0
    with open(relationships_csv, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel_rows += 1
            s = (row.get("start_node_id") or "").strip()
            e = (row.get("end_node_id") or "").strip()
            t = (row.get("rel_type") or "").strip()
            if s and s not in node_ids and len(missing_start_refs) < sample_limit:
                missing_start_refs.append(s)
            if e and e not in node_ids and len(missing_end_refs) < sample_limit:
                missing_end_refs.append(e)
            if not t or not _IDENTIFIER_RE.match(t):
                if len(invalid_rel_types) < sample_limit:
                    invalid_rel_types.append(t)
            key = (s, e, t)
            if key in rel_seen:
                duplicate_rels += 1
            rel_seen.add(key)

    # H4: suspicious node type rows
    unknown_node_type_rows = 0
    with open(nodes_csv, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ntype = (row.get("node_type") or "").strip()
            if ntype and ntype not in {"Record", "Dataset", "Category", "Tag", "Currency", "Dimension"}:
                unknown_node_type_rows += 1

    summary = {
        "ok": True,
        "node_rows": node_rows,
        "relationship_rows": rel_rows,
        "errors": {
            "empty_node_id_rows": empty_node_id_rows,
            "duplicate_node_ids_count": len(dup_node_ids),
            "duplicate_node_ids_sample": dup_node_ids,
            "bad_labels_rows": bad_labels_rows,
            "missing_start_refs_count": len(missing_start_refs),
            "missing_start_refs_sample": missing_start_refs,
            "missing_end_refs_count": len(missing_end_refs),
            "missing_end_refs_sample": missing_end_refs,
            "invalid_rel_types_count": len(invalid_rel_types),
            "invalid_rel_types_sample": invalid_rel_types,
            "duplicate_relationship_rows": duplicate_rels,
            "unknown_node_type_rows": unknown_node_type_rows,
        },
    }
    return summary




def validate_graph_csv_bundle_for_neo4j(
    output_dir: str,
    sample_limit: int = 20,
) -> dict:
    """
    Validate normalized neo4j_export bundle (graph_nodes + graph_relationships + optional inspection).
    """
    req_files = ["graph_nodes.csv", "graph_relationships.csv"]
    paths = {fn: os.path.join(output_dir, fn) for fn in req_files}
    missing_files = [fn for fn, p in paths.items() if not os.path.exists(p)]
    if missing_files:
        return {"error": f"Missing files: {missing_files}"}

    rec_ids: set[str] = set()
    ds_ids: set[str] = set()
    tag_ids: set[str] = set()
    cur_ids: set[str] = set()
    dim_ids: set[str] = set()
    rec_dups = ds_dups = tag_dups = cur_dups = dim_dups = 0
    seen_nid: set[str] = set()
    graph_dups = 0

    with open(paths["graph_nodes.csv"], encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nid = (row.get("node_id:ID") or "").strip()
            lb = (row.get(":LABEL") or "").strip()
            if not nid:
                continue
            if nid in seen_nid:
                graph_dups += 1
            seen_nid.add(nid)
            if lb == "Dimension":
                if nid in dim_ids:
                    dim_dups += 1
                dim_ids.add(nid)
            elif lb == "Dataset":
                if nid in ds_ids:
                    ds_dups += 1
                ds_ids.add(nid)
            elif lb == "Currency":
                if nid in cur_ids:
                    cur_dups += 1
                cur_ids.add(nid)
            elif lb == "Tag":
                if nid in tag_ids:
                    tag_dups += 1
                tag_ids.add(nid)
            elif lb.startswith("Record"):
                if nid in rec_ids:
                    rec_dups += 1
                rec_ids.add(nid)

    all_node_ids = rec_ids | ds_ids | tag_ids | cur_ids | dim_ids

    non_canonical_ids: dict[str, list[str]] = {
        "record": [],
        "dataset": [],
        "tag": [],
        "currency": [],
        "dimension": [],
    }
    for rid in rec_ids:
        if not _BARE_IMPORT_ID_RE.match(rid) and len(non_canonical_ids["record"]) < sample_limit:
            non_canonical_ids["record"].append(rid)
    for did in ds_ids:
        if not _BARE_IMPORT_ID_RE.match(did) and len(non_canonical_ids["dataset"]) < sample_limit:
            non_canonical_ids["dataset"].append(did)
    for tid in tag_ids:
        if not _BARE_IMPORT_ID_RE.match(tid) and len(non_canonical_ids["tag"]) < sample_limit:
            non_canonical_ids["tag"].append(tid)
    for cid in cur_ids:
        if not _BARE_IMPORT_ID_RE.match(cid) and len(non_canonical_ids["currency"]) < sample_limit:
            non_canonical_ids["currency"].append(cid)
    for dk in dim_ids:
        if not _BARE_IMPORT_ID_RE.match(dk) and len(non_canonical_ids["dimension"]) < sample_limit:
            non_canonical_ids["dimension"].append(dk)

    narrative_tag_values_sample: list[str] = []
    overlong_tag_values_sample: list[str] = []
    with open(paths["graph_nodes.csv"], encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get(":LABEL") or "").strip() != "Tag":
                continue
            name_val = (row.get("name") or "").strip()
            if name_val and len(name_val) > 120 and len(overlong_tag_values_sample) < sample_limit:
                overlong_tag_values_sample.append(name_val)
            if name_val and _is_narrative_like_category_value(name_val):
                if len(narrative_tag_values_sample) < sample_limit:
                    narrative_tag_values_sample.append(name_val)

    suspicious_currency_codes_sample: list[str] = []
    with open(paths["graph_nodes.csv"], encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get(":LABEL") or "").strip() != "Currency":
                continue
            cid = (row.get("node_id:ID") or "").strip()
            if cid and not _SUSPICIOUS_CURRENCY_CODE_RE.match(cid):
                if len(suspicious_currency_codes_sample) < sample_limit:
                    suspicious_currency_codes_sample.append(cid)

    miss_s: list[str] = []
    miss_e: list[str] = []
    bad_types: list[str] = []
    bad_sf: list[str] = []
    dup_rels = 0
    rel_rows = 0
    seen_rel: set[tuple[str, str, str, str]] = set()
    by_type: dict[str, int] = {}

    with open(paths["graph_relationships.csv"], encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel_rows += 1
            s = (row.get(":START_ID") or "").strip()
            e = (row.get(":END_ID") or "").strip()
            rt = (row.get(":TYPE") or "").strip()
            sf = (row.get("source_field") or "").strip()
            if s and s not in all_node_ids and len(miss_s) < sample_limit:
                miss_s.append(s)
            if e and e not in all_node_ids and len(miss_e) < sample_limit:
                miss_e.append(e)
            if rt and not _IDENTIFIER_RE.match(rt) and len(bad_types) < sample_limit:
                bad_types.append(rt)
            if rt:
                by_type[rt] = by_type.get(rt, 0) + 1
            if sf and sf not in _DIMENSION_REL and len(bad_sf) < sample_limit:
                bad_sf.append(sf)
            key = (s, e, rt, sf)
            if key in seen_rel:
                dup_rels += 1
            seen_rel.add(key)

    unified_rel = {
        "rows": rel_rows,
        "missing_start_sample": miss_s,
        "missing_end_sample": miss_e,
        "invalid_rel_type_sample": bad_types,
        "unknown_source_field_sample": bad_sf,
        "duplicate_rows": dup_rels,
        "relationship_type_counts": dict(sorted(by_type.items())),
    }

    return {
        "ok": True,
        "schema": "normalized_bundle_v4",
        "node_counts": {
            "record": len(rec_ids),
            "dataset": len(ds_ids),
            "tag": len(tag_ids),
            "currency": len(cur_ids),
            "dimension": len(dim_ids),
        },
        "duplicate_node_ids": {
            "graph_nodes": graph_dups,
            "record": rec_dups,
            "dataset": ds_dups,
            "tag": tag_dups,
            "currency": cur_dups,
            "dimension": dim_dups,
        },
        "canonical_id_checks": {
            "non_canonical_id_count": sum(len(v) for v in non_canonical_ids.values()),
            "non_canonical_id_sample": non_canonical_ids,
        },
        "tag_quality_checks": {
            "overlong_value_count": len(overlong_tag_values_sample),
            "overlong_value_sample": overlong_tag_values_sample,
            "narrative_like_value_count": len(narrative_tag_values_sample),
            "narrative_like_value_sample": narrative_tag_values_sample,
        },
        "warnings": {
            "suspicious_currency_codes_count": len(suspicious_currency_codes_sample),
            "suspicious_currency_codes_sample": suspicious_currency_codes_sample,
        },
        "relationship_checks": {
            "graph_relationships": unified_rel,
        },
    }






# MCP registration: (name, func_name, required_keys, arg_specs, result_key).
# arg_specs: list of (param_name, payload_keys, default, coerce). coerce = int or None.
TOOL_SPECS: list[tuple[str, str, list[str], list, str | None]] = [
    ("kg_tool.query_graph", "query_graph", [], [("cypher", ["cypher"], "", None), ("params", ["params"], None, None)], None),
    ("kg_tool.get_relations", "get_relations", ["entity"], [
        ("entity", ["entity"], "", None),
        ("prefer_dataset", ["prefer_dataset", "dataset"], "", None),
    ], None),
    ("kg_tool.get_node_by_id", "get_node_by_id", [], [("id_val", ["id_val", "id"], "", None), ("id_key", ["id_key"], "id", None)], None),
    ("kg_tool.get_neighbors", "get_neighbors", [], [
        ("node_id", ["node_id", "id"], "", None),
        ("id_key", ["id_key"], "id", None),
        ("direction", ["direction"], "both", None),
        ("relationship_type", ["relationship_type"], None, None),
        ("limit", ["limit"], 100, int),
    ], None),
    ("kg_tool.get_graph_schema", "get_graph_schema", [], [], None),
    ("kg_tool.shortest_path", "shortest_path", [], [
        ("start_id", ["start_id"], "", None),
        ("end_id", ["end_id"], "", None),
        ("id_key", ["id_key"], "id", None),
        ("relationship_type", ["relationship_type"], None, None),
        ("max_depth", ["max_depth"], 15, int),
    ], None),
    ("kg_tool.get_similar_nodes", "get_similar_nodes", [], [
        ("node_id", ["node_id", "id"], "", None),
        ("id_key", ["id_key"], "id", None),
        ("limit", ["limit"], 10, int),
    ], None),
    ("kg_tool.fulltext_search", "fulltext_search", [], [
        ("index_name", ["index_name"], "", None),
        ("query_string", ["query_string"], "", None),
        ("limit", ["limit"], 50, int),
    ], None),
    ("kg_tool.bulk_export", "bulk_export", [], [
        ("cypher", ["cypher"], "", None),
        ("params", ["params"], None, None),
        ("format", ["format"], "json", None),
        ("row_limit", ["row_limit"], 1000, int),
    ], None),
    ("kg_tool.bulk_create_nodes", "bulk_create_nodes", [], [
        ("nodes", ["nodes"], [], None),
        ("label", ["label"], None, None),
        ("id_key", ["id_key"], "id", None),
    ], None),
    ("kg_tool.build_graph_csvs", "build_graph_csvs", [], [
        ("data_dir", ["data_dir"], "database/graph_data", None),
        ("output_dir", ["output_dir"], "database/graph_data/neo4j_export", None),
    ], None),
    ("kg_tool.load_graph_csvs_to_neo4j", "load_graph_csvs_to_neo4j", [], [
        ("nodes_csv", ["nodes_csv"], "", None),
        ("relationships_csv", ["relationships_csv"], "", None),
        ("mode", ["mode"], "append", None),
        ("output_dir", ["output_dir"], None, None),
    ], None),
    ("kg_tool.validate_graph_csvs_for_neo4j", "validate_graph_csvs_for_neo4j", [], [
        ("nodes_csv", ["nodes_csv"], "", None),
        ("relationships_csv", ["relationships_csv"], "", None),
        ("sample_limit", ["sample_limit"], 20, int),
        ("output_dir", ["output_dir"], None, None),
    ], None),
    ("kg_tool.validate_graph_csv_bundle_for_neo4j", "validate_graph_csv_bundle_for_neo4j", ["output_dir"], [
        ("output_dir", ["output_dir"], "", None),
        ("sample_limit", ["sample_limit"], 20, int),
    ], None),
]
