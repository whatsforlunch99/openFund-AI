"""Vector search via Milvus (MCP tool)."""

from __future__ import annotations

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
    """
    raise NotImplementedError


def index_documents(docs: list[dict]) -> dict:
    """
    Index or upsert documents into the Milvus collection.

    Args:
        docs: List of documents (each with content and optional metadata).

    Returns:
        Result dict (e.g. count indexed, status).
    """
    raise NotImplementedError
