"""MCP capabilities: which backends and tools are available (introspection)."""

from __future__ import annotations

import os


def get_capabilities(tool_names: list[str]) -> dict:
    """
    Return which backends are configured and which tools are registered.

    Args:
        tool_names: List of registered MCP tool names (e.g. from server._handlers.keys()).

    Returns:
        Dict with "neo4j", "postgres", "milvus" (bool per env), and "tools" (sorted list
        including "get_capabilities").
    """
    neo4j = bool(os.environ.get("NEO4J_URI"))
    postgres = bool(os.environ.get("DATABASE_URL"))
    milvus = bool(os.environ.get("MILVUS_URI"))
    tools = sorted(set(tool_names) | {"get_capabilities"})
    return {
        "neo4j": neo4j,
        "postgres": postgres,
        "milvus": milvus,
        "tools": tools,
    }
