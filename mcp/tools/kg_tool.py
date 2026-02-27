"""Knowledge graph queries via Neo4j (MCP tool)."""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_driver = None


def _get_driver():
    """Create or return Neo4j driver when NEO4J_URI is set. Lazy import."""
    global _driver
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        return None
    if _driver is not None:
        return _driver
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return None
    user = os.environ.get("NEO4J_USER", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    try:
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        return _driver
    except Exception as e:
        logger.exception("kg_tool: failed to create Neo4j driver: %s", e)
        return None


def _node_to_dict(node) -> dict:
    """Convert Neo4j Node to a plain dict. Prefer node property id/name for output 'id' when present."""
    if node is None:
        return {}
    nid = getattr(node, "element_id", None) or getattr(node, "id", None) or str(node)
    labels = list(getattr(node, "labels", []))
    out = {"label": labels}
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
    driver = _get_driver()
    if driver is None:
        return {
            "error": "Neo4j driver not available or connection failed.",
            "nodes": [],
            "edges": [],
            "params": params or {},
        }
    params = params or {}
    try:
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
    driver = _get_driver()
    if driver is None:
        return {
            "error": "Neo4j driver not available.",
            "nodes": [],
            "edges": [],
            "entity": entity,
        }
    # One-hop: match (e)-[r]-(other) where e has id or name = entity
    cypher = """
    MATCH (e)-[r]-(other)
    WHERE e.id = $entity OR e.name = $entity OR toString(id(e)) = $entity
    RETURN e, type(r) AS rel_type, other
    LIMIT 100
    """
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
