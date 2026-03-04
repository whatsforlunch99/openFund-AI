"""Knowledge graph queries via Neo4j (MCP tool)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Safe identifier for Cypher (label, property key): alphanumeric and underscore only.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_driver = None


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
        out["id"] = node.get("id") or node.get("name") or nid
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
        When NEO4J_URI is unset, returns mock. On error returns {"error": "..."}.
    """
    if not os.environ.get("NEO4J_URI"):
        return {
            "nodes": [{"id": "n1", "label": "Fund"}],
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
        When NEO4J_URI is unset, returns mock node.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "node": None,
        }
    if not os.environ.get("NEO4J_URI"):
        return {"node": {"id": id_val, "label": ["Node"]}}
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
        When NEO4J_URI is unset, returns mock.
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
            "nodes": [{"id": "n2", "label": ["Node"]}],
            "relationships": [{"type": "RELATES_TO", "start": node_id, "end": "n2"}],
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
        When NEO4J_URI is unset, returns mock.
    """
    if not os.environ.get("NEO4J_URI"):
        return {"node_labels": ["Node"], "relationship_types": []}
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
        When NEO4J_URI is unset, returns one mock path.
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
        return {
            "paths": [
                {
                    "nodes": [
                        {"id": start_id, "label": ["Node"]},
                        {"id": end_id, "label": ["Node"]},
                    ],
                    "relationships": [{"type": "RELATES_TO", "start": start_id, "end": end_id}],
                }
            ]
        }
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
        {"nodes": [{"id": ..., "score": count}, ...]}. When NEO4J_URI is unset, returns mock.
    """
    if not _IDENTIFIER_RE.match(id_key):
        return {
            "error": "Invalid id_key: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
        }
    limit = max(1, min(int(limit), 100))
    if not os.environ.get("NEO4J_URI"):
        return {"nodes": [{"id": "similar1", "score": 2}, {"id": "similar2", "score": 1}]}
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


def fulltext_search(index_name: str, query_string: str, limit: int = 50) -> dict:
    """
    Query nodes via Neo4j full-text index: db.index.fulltext.queryNodes.

    Args:
        index_name: Name of the fulltext index (valid identifier).
        query_string: Search string (passed as parameter).
        limit: Maximum nodes to return (default 50).

    Returns:
        {"nodes": [...]} using _node_to_dict. On missing index or failure: {"error": "..."}.
        When NEO4J_URI is unset, returns mock nodes.
    """
    if not _IDENTIFIER_RE.match(index_name):
        return {
            "error": "Invalid index_name: must be a valid identifier (alphanumeric, underscore).",
            "nodes": [],
        }
    limit = max(1, min(int(limit), 200))
    if not os.environ.get("NEO4J_URI"):
        return {"nodes": [{"id": "ft1", "label": ["Node"]}]}
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
        logger.exception("kg_tool.fulltext_search failed: %s", e)
        return {"error": str(e), "nodes": []}


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
        {"data": ..., "format": "json"|"csv"}. When NEO4J_URI is unset, returns mock empty data.
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
        return {"data": [] if format == "json" else "", "format": format}
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
        When NEO4J_URI is unset, returns {"created": len(nodes)}.
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
        return {"created": len(nodes) if nodes else 0}
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


def get_relations(entity: str) -> dict:
    """
    Get relations for an entity (e.g. fund, manager).

    Args:
        entity: Entity identifier.

    Returns:
        Dict with nodes, edges, and entity. When NEO4J_URI is unset, returns mock.
        On error returns {"error": "..."}.
    """
    if not os.environ.get("NEO4J_URI"):
        return {
            "nodes": [{"id": entity, "label": "Entity"}],
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
    # One-hop: match (e)-[r]-(other) where e has id or name = entity (elementId for Neo4j 5+)
    cypher = """
    MATCH (e)-[r]-(other)
    WHERE e.id = $entity OR e.name = $entity OR e.symbol = $entity OR toString(elementId(e)) = $entity
    RETURN e, type(r) AS rel_type, other
    LIMIT 100
    """
    # #region debug log
    try:
        import time
        _has_el = "elementId(e)" in cypher
        _has_id = "id(e)" in cypher
        _dbg = open("/Users/jiani/Desktop/openFund AI/.cursor/debug-0f3c81.log", "a")
        _dbg.write('{"sessionId":"0f3c81","location":"kg_tool.py:get_relations","message":"cypher check","data":{"has_elementId":%s,"has_deprecated_id":%s},"timestamp":%d}\n' % (str(_has_el).lower(), str(_has_id).lower(), int(time.time() * 1000)))
        _dbg.close()
    except Exception:
        pass
    # #endregion
    try:
        records, summary, keys = driver.execute_query(
            cypher,
            parameters_={"entity": entity},
            database_=os.environ.get("NEO4J_DATABASE", "neo4j"),
        )
        nodes = []
        edges = []
        seen = set()
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
        return {"nodes": nodes, "edges": edges, "entity": entity}
    except Exception as e:
        logger.exception("kg_tool.get_relations failed: %s", e)
        return {"error": str(e), "nodes": [], "edges": [], "entity": entity}


def populate_demo() -> tuple[bool, str]:
    """
    Create Company/Sector nodes and IN_SECTOR edge for NVDA. Uses NEO4J_URI.
    Caller should load .env before calling. Returns (success, message).
    Keeps CredentialsExpired/Unauthorized hint text in error messages.
    """
    if not os.environ.get("NEO4J_URI"):
        return False, "NEO4J_URI not set; skipping Neo4j."
    cypher = """
    MERGE (e:Company {id: 'NVDA'})
    MERGE (s:Sector {id: 'Technology'})
    MERGE (e)-[:IN_SECTOR]->(s)
    """
    r = query_graph(cypher)
    if r.get("error"):
        err = r["error"]
        if "CredentialsExpired" in err or "credentials" in err.lower():
            err += " Change the default password: open http://localhost:7474, log in as neo4j, set a new password, then set NEO4J_PASSWORD in .env."
        elif "Unauthorized" in err or "authentication failure" in err.lower():
            err += " Ensure NEO4J_PASSWORD in .env matches the password you set in Neo4j Browser (http://localhost:7474)."
        return False, f"Neo4j failed: {err}"
    return True, "Neo4j: merged Company NVDA, Sector Technology, IN_SECTOR edge."
