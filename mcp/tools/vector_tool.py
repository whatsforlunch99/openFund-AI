"""Vector search via Milvus (MCP tool)."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_embedding_model = None
_milvus_connected = False

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIM = 384


def _parse_milvus_uri(uri: str) -> tuple:
    """Parse MILVUS_URI to (host, port). E.g. http://localhost:19530 -> (localhost, 19530)."""
    u = (uri or "").strip().replace("http://", "").replace("https://", "")
    if ":" in u:
        host, port = u.rsplit(":", 1)
        return host.strip(), str(port.strip())
    return u or "localhost", "19530"


def _ensure_milvus_connection() -> bool:
    """Connect to Milvus if MILVUS_URI is set. Lazy import pymilvus."""
    global _milvus_connected
    if _milvus_connected:
        return True
    uri = os.environ.get("MILVUS_URI")
    if not uri:
        return False
    try:
        from pymilvus import connections
    except ImportError:
        return False
    try:
        host, port = _parse_milvus_uri(uri)
        connections.connect(alias="default", host=host, port=port)
        _milvus_connected = True
        return True
    except Exception as e:
        logger.exception("vector_tool: failed to connect to Milvus: %s", e)
        return False


def _get_embedding_model():
    """Lazy-load sentence-transformers model. Returns (model, dim)."""
    global _embedding_model
    if _embedding_model is not None:
        dim = int(os.environ.get("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM))
        return _embedding_model, dim
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None, DEFAULT_EMBEDDING_DIM
    model_name = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    dim = int(os.environ.get("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM))
    try:
        _embedding_model = SentenceTransformer(model_name)
        # Actual dim may differ; use config for collection schema
        return _embedding_model, dim
    except Exception as e:
        logger.exception(
            "vector_tool: failed to load embedding model %s: %s", model_name, e
        )
        return None, dim


def _get_collection():
    """Return Milvus Collection for the configured name; create if not exists."""
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

    name = os.environ.get("MILVUS_COLLECTION", "openfund_docs")
    dim = int(os.environ.get("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM))
    if utility.has_collection(name):
        return Collection(name)
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="fund_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=256),
    ]
    schema = CollectionSchema(
        fields=fields, description="Fund documents for semantic search"
    )
    coll = Collection(name=name, schema=schema)
    coll.create_index(
        field_name="embedding",
        index_params={
            "metric_type": "IP",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        },
    )
    return coll


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
        filter: Optional filter on metadata (e.g. fund_id, source).

    Returns:
        List of documents with content, score, id. Config: MILVUS_URI, MILVUS_COLLECTION.
        When MILVUS_URI is unset, returns mock data. On error returns [] and logs.
    """
    if not os.environ.get("MILVUS_URI"):
        return [
            {"content": f"mock doc for: {query}", "score": 0.9, "id": "mock1"},
            {"content": "second mock doc", "score": 0.8, "id": "mock2"},
        ][: max(1, min(top_k, 10))]
    if not _ensure_milvus_connection():
        return []
    model, dim = _get_embedding_model()
    if model is None:
        return []
    try:
        qvec = model.encode([query], normalize_embeddings=True)
        if qvec is None or len(qvec) == 0:
            return []
        qvec = qvec.tolist()
        coll = _get_collection()
        coll.load()
        expr = None
        if filter:
            parts = []
            if filter.get("fund_id"):
                parts.append(f'fund_id == "{filter["fund_id"]}"')
            if filter.get("source"):
                parts.append(f'source == "{filter["source"]}"')
            if parts:
                expr = " and ".join(parts)
        search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
        results = coll.search(
            data=[qvec[0]],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
        )
        out = []
        for hits in results:
            for h in hits:
                entity = getattr(h, "entity", None)
                content = getattr(entity, "content", "") if entity else ""
                doc_id = getattr(entity, "id", str(h.id)) if entity else str(h.id)
                out.append(
                    {"id": doc_id, "content": content or "", "score": float(h.score)}
                )
        return out
    except Exception as e:
        logger.exception("vector_tool.search failed: %s", e)
        return []


def index_documents(docs: list[dict]) -> dict:
    """
    Index or upsert documents into the Milvus collection.

    Args:
        docs: List of dicts with "content" required; optional "fund_id", "source".

    Returns:
        Dict with "indexed" (count) and "status" ("ok" or "error"). On error returns {"error": "...", "indexed": 0}.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set", "indexed": 0, "status": "error"}
    if not _ensure_milvus_connection():
        return {"error": "Could not connect to Milvus", "indexed": 0, "status": "error"}
    model, dim = _get_embedding_model()
    if model is None:
        return {
            "error": "Embedding model not available",
            "indexed": 0,
            "status": "error",
        }
    if not docs:
        return {"indexed": 0, "status": "ok"}
    try:
        contents = [d.get("content", "") or "" for d in docs]
        embeddings = model.encode(contents, normalize_embeddings=True)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
        ids = [str(uuid.uuid4()) for _ in docs]
        fund_ids = [str(d.get("fund_id", ""))[:256] for d in docs]
        sources = [str(d.get("source", ""))[:256] for d in docs]
        coll = _get_collection()
        coll.load()
        coll.insert([ids, contents, embeddings, fund_ids, sources])
        coll.flush()
        return {"indexed": len(docs), "status": "ok"}
    except Exception as e:
        logger.exception("vector_tool.index_documents failed: %s", e)
        return {"error": str(e), "indexed": 0, "status": "error"}


def delete_by_expr(expr: str) -> dict:
    """
    Delete entities from the Milvus collection by filter expression.

    Args:
        expr: Milvus filter expression (e.g. 'id in ["id1","id2"]' or 'fund_id == "X"').

    Returns:
        Dict with "deleted" (count) or "error".
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set", "deleted": 0}
    if not _ensure_milvus_connection():
        return {"error": "Could not connect to Milvus", "deleted": 0}
    try:
        coll = _get_collection()
        coll.load()
        result = coll.delete(expr)
        coll.flush()
        deleted = getattr(result, "delete_count", 0)
        return {"deleted": deleted}
    except Exception as e:
        logger.exception("vector_tool.delete_by_expr failed: %s", e)
        return {"error": str(e), "deleted": 0}
