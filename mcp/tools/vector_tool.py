"""Vector search via Milvus (MCP tool)."""

from typing import Dict, List, Optional


def search(
    query: str,
    top_k: int,
    filter: Optional[Dict] = None,
) -> List[dict]:
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


def index_documents(docs: List[dict]) -> dict:
    """
    Index or upsert documents into the Milvus collection.

    Args:
        docs: List of documents (each with content and optional metadata).

    Returns:
        Result dict (e.g. count indexed, status).
    """
    raise NotImplementedError
