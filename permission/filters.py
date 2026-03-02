"""Database-specific filter generators for permission filtering.

Provides parameterized filter structures for PostgreSQL (SQLFilter),
Neo4j (CypherFilter), and Milvus (MilvusFilter).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SQLFilter:
    """Parameterized SQL filter result.

    Attributes:
        clause: SQL WHERE clause with named placeholders (e.g., %(tenant_id)s).
        params: Dictionary of parameter values.
    """

    clause: str
    params: dict[str, Any] = field(default_factory=dict)

    def with_alias(self, alias: str) -> SQLFilter:
        """Return a new SQLFilter with table alias prefix on columns.

        Args:
            alias: Table alias (e.g., "t" for "t.classification").

        Returns:
            New SQLFilter with aliased column names.
        """
        import re
        columns = [
            "classification_level",
            "classification",
            "tenant_id",
            "roles_allowed",
            "users_allowed",
            "expiry_date",
        ]
        new_clause = self.clause
        for col in columns:
            pattern = rf'\b{col}\b'
            new_clause = re.sub(pattern, f"{alias}.{col}", new_clause)
        return SQLFilter(clause=new_clause, params=self.params.copy())


@dataclass
class CypherFilter:
    """Parameterized Cypher filter result.

    Attributes:
        clause: Cypher WHERE clause with parameter placeholders (e.g., $tenant_id).
        params: Dictionary of parameter values.
    """

    clause: str
    params: dict[str, Any] = field(default_factory=dict)

    def with_node_var(self, node_var: str) -> CypherFilter:
        """Return a new CypherFilter with specified node variable.

        Args:
            node_var: Node variable name (default clause uses "n").

        Returns:
            New CypherFilter with updated node variable.
        """
        new_clause = self.clause.replace("n.", f"{node_var}.")
        return CypherFilter(clause=new_clause, params=self.params.copy())


@dataclass
class MilvusFilter:
    """Milvus filter with post-filter function for complex RBAC.

    Milvus has limited expression capabilities (no array intersection),
    so we use a two-stage approach:
    1. Pre-filter (expr): Classification and tenant checks in Milvus
    2. Post-filter (post_filter): RBAC/ABAC checks in Python

    Attributes:
        expr: Milvus boolean expression for pre-filtering.
        post_filter: Optional function to filter results after retrieval.
    """

    expr: str
    post_filter: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None


def escape_milvus_string(s: str) -> str:
    """Escape special characters for Milvus string literals.

    Args:
        s: String to escape.

    Returns:
        Escaped string safe for Milvus expressions.
    """
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def parse_json_array(value: str | list[str]) -> list[str]:
    """Parse JSON array string or return list as-is.

    Milvus stores arrays as JSON strings; this helper parses them
    for post-filter evaluation.

    Args:
        value: JSON string or list.

    Returns:
        List of strings.
    """
    if isinstance(value, list):
        return value
    if not value or value in ("[]", "null", "None"):
        return []
    try:
        import json
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
        return []
    except (json.JSONDecodeError, TypeError):
        return []
