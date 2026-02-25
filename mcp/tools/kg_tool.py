"""Knowledge graph queries via Neo4j (MCP tool)."""

from __future__ import annotations

from typing import Optional


def query_graph(cypher: str, params: Optional[dict] = None) -> dict:
    """
    Execute a Cypher query against Neo4j.

    Args:
        cypher: Cypher query string.
        params: Optional query parameters.

    Returns:
        Dict with nodes/edges or result rows. Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
    """
    raise NotImplementedError


def get_relations(entity: str) -> dict:
    """
    Get relations for an entity (e.g. fund, manager).

    Args:
        entity: Entity identifier.

    Returns:
        Dict with related nodes/edges.
    """
    raise NotImplementedError
