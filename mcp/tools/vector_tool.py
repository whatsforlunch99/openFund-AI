"""Vector search via Milvus (MCP tool)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_embedding_model = None
_milvus_connected = False

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIM = 384


def _parse_milvus_uri(uri: str) -> tuple[str, int]:
    """Parse MILVUS_URI to (host, port). E.g. http://localhost:19530 -> (localhost, 19530)."""
    u = (uri or "").strip().replace("http://", "").replace("https://", "")
    if ":" in u:
        host, port_str = u.rsplit(":", 1)
        try:
            port = int(port_str.strip())
        except ValueError:
            port = 19530
        return host.strip(), port
    return (u or "localhost", 19530)


def _ensure_milvus_connection() -> tuple[bool, str | None]:
    """Connect to Milvus if MILVUS_URI is set. Returns (ok, error_message). Retries a few times for slow container startup."""
    global _milvus_connected
    if _milvus_connected:
        return True, None
    uri = os.environ.get("MILVUS_URI")
    if not uri:
        return False, None
    try:
        from pymilvus import connections  # type: ignore[import-untyped]
    except ImportError:
        return False, "Milvus driver not installed. Run: pip install -e '.[backends]'"
    host, port = _parse_milvus_uri(uri)
    last_error = None
    for attempt in range(5):
        try:
            connections.connect(alias="default", host=host, port=port)
            _milvus_connected = True
            return True, None
        except Exception as e:
            last_error = e
            logger.debug("Milvus connection attempt %s failed: %s", attempt + 1, e)
            if attempt < 4:
                import time

                time.sleep(2)
    logger.exception("vector_tool: failed to connect to Milvus: %s", last_error)
    return False, f"Milvus connection failed: {last_error}"


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


def list_collections() -> dict:
    """
    List Milvus collection names. Uses utility.list_collections().

    Returns:
        {"collections": [...]} on success, {"error": "..."} when MILVUS_URI unset or on failure.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set"}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus"}
    try:
        from pymilvus import utility

        names = utility.list_collections()
        return {"collections": list(names) if names is not None else []}
    except Exception as e:
        logger.exception("vector_tool.list_collections failed: %s", e)
        return {"error": str(e)}


def get_collection_info(name: Optional[str] = None) -> dict:
    """
    Return schema fields and row count for a collection. If name is None, use default from env.

    Args:
        name: Collection name, or None for MILVUS_COLLECTION default.

    Returns:
        {"name", "schema_fields", "count"} on success, {"error": "..."} on failure.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set"}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus"}
    coll_name = (
        name
        if name is not None
        else os.environ.get("MILVUS_COLLECTION", "openfund_docs")
    )
    try:
        from pymilvus import Collection, utility

        if not utility.has_collection(coll_name):
            return {"error": f"Collection '{coll_name}' does not exist"}
        coll = Collection(coll_name)
        coll.load()
        schema_fields = []
        if coll.schema and getattr(coll.schema, "fields", None):
            for f in coll.schema.fields:
                schema_fields.append(
                    {
                        "name": getattr(f, "name", str(f)),
                        "dtype": str(getattr(f, "dtype", "")),
                    }
                )
        num = coll.num_entities
        return {"name": coll_name, "schema_fields": schema_fields, "count": num}
    except Exception as e:
        logger.exception("vector_tool.get_collection_info failed: %s", e)
        return {"error": str(e)}


def count(expr: Optional[str] = None) -> dict:
    """
    Count entities in the default collection, optionally with a filter expression.

    Args:
        expr: Optional filter (e.g. 'source == "demo"'). If None, count all.

    Returns:
        {"count": n} on success, {"error": "..."} on failure.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set"}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus"}
    try:
        coll = _get_collection()
        coll.load()
        if expr:
            # Milvus has no built-in filtered count; run query with expr and count rows.
            results = coll.query(expr=expr, output_fields=["id"], limit=16384)
            n = len(results) if results else 0
        else:
            n = coll.num_entities
        return {"count": n}
    except Exception as e:
        logger.exception("vector_tool.count failed: %s", e)
        return {"error": str(e)}


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
    ok, err = _ensure_milvus_connection()
    if not ok:
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
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {
            "error": err or "Could not connect to Milvus",
            "indexed": 0,
            "status": "error",
        }
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


def get_by_ids(ids: list[str], collection_name: Optional[str] = None) -> dict:
    """
    Retrieve entities by primary key (id in ids). No vector search.

    Args:
        ids: List of entity ids (primary key).
        collection_name: Optional collection name; default from MILVUS_COLLECTION.

    Returns:
        {"entities": [{"id", "content", "fund_id", "source", ...}, ...]}.
        When MILVUS_URI is unset, returns mock list.
    """
    if not ids:
        return {"entities": []}
    if not os.environ.get("MILVUS_URI"):
        return {
            "entities": [
                {"id": i, "content": f"mock content {i}", "fund_id": "", "source": "mock"}
                for i in ids[:10]
            ]
        }
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus", "entities": []}
    coll_name = collection_name or os.environ.get("MILVUS_COLLECTION", "openfund_docs")
    try:
        from pymilvus import Collection, utility

        if not utility.has_collection(coll_name):
            return {"error": f"Collection '{coll_name}' does not exist", "entities": []}
        coll = Collection(coll_name)
        coll.load()
        ids_str = [str(i) for i in ids]
        expr = "id in " + json.dumps(ids_str)
        results = coll.query(expr=expr, output_fields=["*"], limit=16384)
        entities = []
        if results:
            for r in results:
                if isinstance(r, dict):
                    entities.append(r)
                else:
                    entities.append(dict(r))
        return {"entities": entities}
    except Exception as e:
        logger.exception("vector_tool.get_by_ids failed: %s", e)
        return {"error": str(e), "entities": []}


def upsert_documents(docs: list[dict]) -> dict:
    """
    Insert or overwrite documents by primary key (each doc must have "id").
    If id exists, overwrite (delete then insert); else insert.

    Args:
        docs: List of dicts with "id" required; "content", "fund_id", "source" optional.

    Returns:
        {"upserted": n, "status": "ok"} or {"error": "...", "upserted": 0, "status": "error"}.
        When MILVUS_URI is unset returns error.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set", "upserted": 0, "status": "error"}
    if not docs:
        return {"upserted": 0, "status": "ok"}
    for d in docs:
        if not d.get("id"):
            return {"error": "Each document must have an 'id' field", "upserted": 0, "status": "error"}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus", "upserted": 0, "status": "error"}
    model, _ = _get_embedding_model()
    if model is None:
        return {"error": "Embedding model not available", "upserted": 0, "status": "error"}
    try:
        coll = _get_collection()
        coll.load()
        ids_to_upsert = [str(d["id"]) for d in docs]
        # Delete existing by id so we can insert (overwrite)
        if ids_to_upsert:
            delete_expr = "id in " + json.dumps(ids_to_upsert)
            coll.delete(delete_expr)
            coll.flush()
        contents = [d.get("content", "") or "" for d in docs]
        embeddings = model.encode(contents, normalize_embeddings=True)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
        ids = [str(d["id"]) for d in docs]
        fund_ids = [str(d.get("fund_id", ""))[:256] for d in docs]
        sources = [str(d.get("source", ""))[:256] for d in docs]
        coll.insert([ids, contents, embeddings, fund_ids, sources])
        coll.flush()
        return {"upserted": len(docs), "status": "ok"}
    except Exception as e:
        logger.exception("vector_tool.upsert_documents failed: %s", e)
        return {"error": str(e), "upserted": 0, "status": "error"}


def health_check() -> dict:
    """
    Ping Milvus (e.g. list_collections or no-op) to verify connectivity.

    Returns:
        {"ok": true} on success; {"ok": false, "error": "..."} on failure.
        When MILVUS_URI is unset returns {"ok": false, "error": "MILVUS_URI not set"}.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"ok": False, "error": "MILVUS_URI not set"}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"ok": False, "error": err or "Could not connect to Milvus"}
    try:
        from pymilvus import utility

        utility.list_collections()
        return {"ok": True}
    except Exception as e:
        logger.debug("vector_tool.health_check failed: %s", e)
        return {"ok": False, "error": str(e)}


def delete_by_expr(expr: str, collection_name: Optional[str] = None) -> dict:
    """
    Delete entities in the collection matching the filter expression.

    Args:
        expr: Filter expression (e.g. 'source == "demo"').
        collection_name: Optional collection name; default from MILVUS_COLLECTION.

    Returns:
        {"deleted": n} on success; {"error": "..."} when MILVUS_URI unset or on failure.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set", "deleted": 0}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus", "deleted": 0}
    coll_name = collection_name or os.environ.get("MILVUS_COLLECTION", "openfund_docs")
    try:
        from pymilvus import Collection, utility

        if not utility.has_collection(coll_name):
            return {"error": f"Collection '{coll_name}' does not exist", "deleted": 0}
        coll = Collection(coll_name)
        coll.load()
        # Query to count then delete (Milvus delete returns void)
        before = coll.num_entities
        coll.delete(expr)
        coll.flush()
        after = coll.num_entities
        return {"deleted": max(0, before - after)}
    except Exception as e:
        logger.exception("vector_tool.delete_by_expr failed: %s", e)
        return {"error": str(e), "deleted": 0}


def create_collection_from_config(
    name: str,
    dimension: int,
    primary_key_field: str = "id",
    scalar_fields: Optional[list[dict]] = None,
    index_params: Optional[dict] = None,
) -> dict:
    """
    Create a Milvus collection with the given schema.

    Args:
        name: Collection name.
        dimension: Vector dimension for the embedding field.
        primary_key_field: Primary key field name (default "id"). Stored as VARCHAR max_length=64.
        scalar_fields: Optional list of {"name": str, "dtype": "VARCHAR"|"INT64"|..., "max_length": int for VARCHAR}.
        index_params: Optional dict for the vector index (e.g. metric_type, index_type, params).

    Returns:
        {"ok": true, "name": name} on success; {"error": "..."} on failure.
        When MILVUS_URI is unset returns {"error": "MILVUS_URI not set"}.
    """
    if not os.environ.get("MILVUS_URI"):
        return {"error": "MILVUS_URI not set"}
    if not (name or "").strip():
        return {"error": "name is required"}
    try:
        dimension = int(dimension)
    except (TypeError, ValueError):
        return {"error": "dimension must be an integer"}
    ok, err = _ensure_milvus_connection()
    if not ok:
        return {"error": err or "Could not connect to Milvus"}
    try:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            utility,
        )

        if utility.has_collection(name):
            return {"ok": True, "name": name}
        fields = [
            FieldSchema(
                name=primary_key_field,
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=64,
            ),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
        ]
        dtype_map = {
            "VARCHAR": DataType.VARCHAR,
            "INT64": DataType.INT64,
            "INT32": DataType.INT32,
            "FLOAT": DataType.FLOAT,
            "DOUBLE": DataType.DOUBLE,
            "BOOL": DataType.BOOL,
        }
        for sf in scalar_fields or []:
            fname = sf.get("name")
            dtype_str = (sf.get("dtype") or "VARCHAR").upper()
            if not fname:
                continue
            dtype = dtype_map.get(dtype_str, DataType.VARCHAR)
            max_len = int(sf.get("max_length", 256))
            if dtype == DataType.VARCHAR:
                fields.append(FieldSchema(name=fname, dtype=dtype, max_length=max_len))
            else:
                fields.append(FieldSchema(name=fname, dtype=dtype))
        schema = CollectionSchema(fields=fields, description=f"Collection {name}")
        coll = Collection(name=name, schema=schema)
        idx_params = index_params or {
            "metric_type": "IP",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        }
        coll.create_index(field_name="embedding", index_params=idx_params)
        return {"ok": True, "name": name}
    except Exception as e:
        logger.exception("vector_tool.create_collection_from_config failed: %s", e)
        return {"error": str(e)}


# Demo docs for populate_demo (content from demo_data.VECTOR_SEARCH_RESPONSE)
_DEMO_DOCS = [
    {
        "content": "NVIDIA (NVDA) is a leading semiconductor company focused on graphics and AI. Suitable for long-term growth investors; volatility can be high.",
        "fund_id": "NVDA",
        "source": "demo",
    },
    {
        "content": "NVDA fundamentals: Technology sector, strong revenue growth. Not a recommendation to buy or sell.",
        "fund_id": "NVDA",
        "source": "demo",
    },
]


def populate_demo() -> tuple[bool, str]:
    """
    Index two demo documents (idempotent: delete by source=='demo' then index).
    Uses MILVUS_URI. Caller should load .env before calling. Returns (success, message).
    Keeps connection-error hint (start_milvus.sh) in error message.
    """
    if not os.environ.get("MILVUS_URI"):
        return False, "MILVUS_URI not set; skipping Milvus."
    out = delete_by_expr('source == "demo"')
    if out.get("error"):
        logger.debug("Milvus delete_by_expr (pre-index): %s", out.get("error"))
    out = index_documents(_DEMO_DOCS)
    if out.get("status") == "error" or out.get("error"):
        err = out.get("error", "unknown")
        err = str(err)
        if "Fail connecting" in err or "server unavailable" in err:
            err += " Start Milvus with: ./scripts/start_milvus.sh (the plain 'docker run milvusdb/milvus' does not start the server). Wait ~60s then run populate again."
        return False, f"Milvus failed: {err}"
    return True, f"Milvus: indexed {out.get('indexed', 0)} demo document(s)."
