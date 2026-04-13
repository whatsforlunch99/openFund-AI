"""Persist WebSearcher news into database/text_data/web_searched_data.json."""

from __future__ import annotations

import json
import math
import os
import re
from hashlib import sha1
from typing import Any

_EMBED_MODEL = None
_DEFAULT_THRESHOLD = 0.9


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_output_path() -> str:
    return os.path.join(_project_root(), "database", "text_data", "web_searched_data.json")


def _record_text(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    content = str(item.get("summary") or item.get("content") or "").strip()
    if content:
        return f"{title}. {content}"
    return title


def _load_embedding_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    model_name = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    try:
        _EMBED_MODEL = SentenceTransformer(model_name, local_files_only=True)
    except Exception:
        _EMBED_MODEL = SentenceTransformer(model_name)
    return _EMBED_MODEL


def _embed_text(text: str) -> list[float] | None:
    model = _load_embedding_model()
    if model is None:
        return None
    if not text.strip():
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vec]
    except Exception:
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _read_existing(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _next_id(existing: list[dict[str, Any]]) -> int:
    mx = 0
    for row in existing:
        try:
            mx = max(mx, int(row.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return mx + 1


def _record_embedding(row: dict[str, Any]) -> list[float] | None:
    emb = row.get("embedding")
    if isinstance(emb, list) and emb and all(isinstance(x, (int, float)) for x in emb):
        return [float(x) for x in emb]
    text = f"{row.get('title') or ''}. {row.get('content') or ''}".strip()
    vec = _embed_text(text)
    if vec:
        row["embedding"] = vec
    return vec


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return out[:48] or "item"


def _build_milvus_id(row: dict[str, Any]) -> str:
    ts = str(row.get("search_timestamp") or "").replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    title = _slug(str(row.get("title") or "news"))
    rid = str(row.get("id") or "")
    raw = f"{ts}|{title}|{rid}"
    digest = sha1(raw.encode("utf-8")).hexdigest()[:16]
    # Milvus id max length is 64; keep deterministic and bounded.
    return f"ws_{ts[:14]}_{title[:24]}_{digest}"[:64]


def _upsert_new_records_to_milvus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"upserted": 0, "status": "ok", "skipped": True}
    try:
        from openfund_mcp.tools.vector import milvus as vector_tool
    except Exception as e:
        return {"upserted": 0, "status": "error", "error": f"milvus import failed: {e}"}

    docs: list[dict[str, str]] = []
    for r in rows:
        content = str(r.get("content") or "").strip() or str(r.get("title") or "").strip()
        if not content:
            continue
        syms = r.get("symbols_mentioned") or []
        fund_id = ",".join(str(s).strip() for s in syms if str(s).strip())
        docs.append(
            {
                "id": _build_milvus_id(r),
                "content": content,
                "fund_id": fund_id[:256],
                "source": "websearch",
            }
        )
    if not docs:
        return {"upserted": 0, "status": "ok", "skipped": True}
    return vector_tool.upsert_documents(docs)


def persist_websearch_news(
    news_items: list[dict[str, Any]],
    symbols_mentioned: list[str],
    search_timestamp: str,
    output_path: str | None = None,
    similarity_threshold: float = _DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Persist deduped news records to web_searched_data.json."""
    if not news_items:
        return {"stored": 0, "skipped": 0}
    path = output_path or _default_output_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = _read_existing(path)
    next_id = _next_id(existing)

    existing_embeddings: list[list[float]] = []
    for row in existing:
        emb = _record_embedding(row)
        if emb:
            existing_embeddings.append(emb)

    stored = 0
    skipped = 0
    new_rows: list[dict[str, Any]] = []
    for item in news_items:
        text = _record_text(item)
        emb = _embed_text(text)
        if emb is None:
            skipped += 1
            continue
        is_dup = any(
            _cosine_similarity(emb, prev) > similarity_threshold for prev in existing_embeddings
        )
        if is_dup:
            skipped += 1
            continue
        record = {
            "id": next_id,
            "title": str(item.get("title") or "(No title)"),
            "content": str(item.get("summary") or item.get("content") or ""),
            "category": "Web Search",
            "embedding": emb,
            "symbols_mentioned": list(dict.fromkeys([s for s in symbols_mentioned if s])),
            "search_timestamp": search_timestamp,
            "url": str(item.get("url") or ""),
            "domain": str(item.get("domain") or ""),
            "source": str(item.get("source") or ""),
        }
        existing.append(record)
        existing_embeddings.append(emb)
        new_rows.append(record)
        next_id += 1
        stored += 1

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    milvus_res = _upsert_new_records_to_milvus(new_rows)
    return {"stored": stored, "skipped": skipped, "milvus": milvus_res}

