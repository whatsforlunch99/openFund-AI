"""Data services entry point: create, update, delete data in PostgreSQL, Neo4j, and Milvus.

Run: python -m data --help
     python -m data populate
     python -m data sql "SELECT 1"
     python -m data neo4j "MATCH (n) RETURN count(n)"
     python -m data milvus index docs.json
     python -m data milvus delete 'id in ["id1","id2"]'
"""

from data.cli import main
from data.populate import run_populate

__all__ = [
    "main",
    "run_populate",
]
