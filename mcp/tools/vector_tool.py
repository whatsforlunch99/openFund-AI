"""Vector search via Milvus (MCP tool)."""

from __future__ import annotations

import os
from typing import Optional


def search(
    query: str,
    top_k: int,
    filter: Optional[dict] = None,
) -> list[dict]:
    """
    Semantic search over Milvus collection.

    Args:
        query: Search query (will be embedded if needed).
        top_k: Maximum number of documents to return.
        filter: Optional filter on metadata.

    Returns:
        List of documents with scores. Config: MILVUS_URI, MILVUS_COLLECTION.
        When MILVUS_URI is not set, returns mock data for slice 4.
    """
    if not os.environ.get("MILVUS_URI"):
        return [
            {"content": f"mock doc for: {query}", "score": 0.9, "id": "mock1"},
            {"content": "second mock doc", "score": 0.8, "id": "mock2"},
        ][: max(1, min(top_k, 10))]
    raise NotImplementedError("Real Milvus backend not implemented")


def index_documents(docs: list[dict]) -> dict:
    """
    Index or upsert documents into the Milvus collection.

    Args:
        docs: List of documents (each with content and optional metadata).

    Returns:
        Result dict (e.g. count indexed, status).
    """
    raise NotImplementedError
