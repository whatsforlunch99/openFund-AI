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
from data.postgres import populate_postgres
from data.neo4j import populate_neo4j
from data.milvus import populate_milvus

__all__ = [
    "main",
    "run_populate",
    "populate_postgres",
    "populate_neo4j",
    "populate_milvus",
]
