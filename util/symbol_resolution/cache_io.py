"""Persisted symbol resolution cache under MEMORY_STORE_PATH."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_SYMBOL_RESOLUTION_CACHE_FILENAME = "symbol_resolution_cache.json"


def _symbol_resolution_cache_path() -> str:
    root = os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    return os.path.join(root, _SYMBOL_RESOLUTION_CACHE_FILENAME)


def load_cache() -> dict[str, Any]:
    path = _symbol_resolution_cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_cached_entry(cache_key: str) -> Optional[dict[str, Any]]:
    if not cache_key:
        return None
    data = load_cache()
    entry = data.get(cache_key)
    return entry if isinstance(entry, dict) else None


def put_cached_entry(cache_key: str, entry: dict[str, Any]) -> None:
    if not cache_key or not isinstance(entry, dict):
        return
    path = _symbol_resolution_cache_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = load_cache()
    data[cache_key] = entry
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
