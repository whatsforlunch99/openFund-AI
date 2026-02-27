"""Neo4j data management: create nodes/edges and seed demo data.

Uses mcp.tools.kg_tool for Cypher. For one-off queries use the CLI
(data cli neo4j) or kg_tool.query_graph directly.
"""

from __future__ import annotations

import os

from data.env_loader import load_dotenv as _load_dotenv


def populate_neo4j() -> tuple[bool, str]:
    """Create Company/Sector nodes and IN_SECTOR edge for NVDA. Uses NEO4J_URI."""
    _load_dotenv()
    if not os.environ.get("NEO4J_URI"):
        return False, "NEO4J_URI not set; skipping Neo4j."
    from mcp.tools import kg_tool

    # MERGE so re-runs are idempotent. Nodes need id (or name) for get_relations(entity) to match.
    cypher = """
    MERGE (e:Company {id: 'NVDA'})
    MERGE (s:Sector {id: 'Technology'})
    MERGE (e)-[:IN_SECTOR]->(s)
    """
    r = kg_tool.query_graph(cypher)
    if r.get("error"):
        err = r["error"]
        if "CredentialsExpired" in err or "credentials" in err.lower():
            err += (
                " Change the default password: open http://localhost:7474, log in as neo4j, set a new password, then set NEO4J_PASSWORD in .env."
            )
        elif "Unauthorized" in err or "authentication failure" in err.lower():
            err += (
                " Ensure NEO4J_PASSWORD in .env matches the password you set in Neo4j Browser (http://localhost:7474)."
            )
        return False, f"Neo4j failed: {err}"
    return True, "Neo4j: merged Company NVDA, Sector Technology, IN_SECTOR edge."
