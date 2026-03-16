"""Per-user working memory (500-word cap with compression) and preference labels.

Stores under memory_store_path/<user_id>/user_memory.json. When working memory
exceeds 500 words, a pluggable compressor shortens it (default: truncation).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

USER_MEMORY_FILENAME = "user_memory.json"
MAX_WORDS = 500

_compressor: Callable[[str, int], str] = lambda text, max_words: _truncate_to_words(
    text, max_words
)


def _word_count(text: str) -> int:
    """Count words (whitespace-split)."""
    return len((text or "").split())


def _truncate_to_words(text: str, max_words: int) -> str:
    """Return first max_words words of text."""
    if not text or max_words <= 0:
        return ""
    parts = text.split()
    return " ".join(parts[:max_words]) if len(parts) > max_words else text


def compress_to_gist(
    text: str, max_words: int = MAX_WORDS, llm_client: Any = None
) -> str:
    """Shorten text to at most max_words. Uses llm_client.complete() if provided; else truncate."""
    if not text or _word_count(text) <= max_words:
        return text
    if llm_client is not None and hasattr(llm_client, "complete"):
        try:
            system = (
                f"Summarize the following user memory in at most {max_words} words. "
                "Keep preferences, main questions asked, and topics of interest. "
                "Output only the summary, no preamble."
            )
            out = llm_client.complete(system, text)
            if out and _word_count(out) <= max_words:
                return out.strip()
        except Exception:
            pass
    return _truncate_to_words(text, max_words)


def set_compressor(f: Callable[[str, int], str]) -> None:
    """Set the compressor used when working memory exceeds the word cap. Default: truncation."""
    global _compressor
    _compressor = f


def _user_dir(user_id: str, memory_store_path: str) -> Path:
    key = user_id if user_id else "anonymous"
    return Path(memory_store_path).expanduser().resolve() / key


def _path(user_id: str, memory_store_path: str) -> Path:
    return _user_dir(user_id, memory_store_path) / USER_MEMORY_FILENAME


def _load_raw(
    user_id: str, memory_store_path: str
) -> tuple[str, list[str], str]:
    """Load (text, preference_labels, updated_at). Returns empty defaults if file missing."""
    p = _path(user_id, memory_store_path)
    if not p.exists():
        return ("", [], "")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ("", [], "")
    if not isinstance(data, dict):
        return ("", [], "")
    text = data.get("text")
    labels = data.get("preference_labels")
    if not isinstance(text, str):
        text = ""
    if not isinstance(labels, list):
        labels = []
    labels = [str(x) for x in labels if x]
    updated = data.get("updated_at") if isinstance(data.get("updated_at"), str) else ""
    return (text, labels, updated)


def _save(user_id: str, text: str, preference_labels: list[str], memory_store_path: str) -> None:
    p = _path(user_id, memory_store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "text": text,
        "preference_labels": preference_labels,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_user_memory(
    user_id: str,
    memory_store_path: str | None = None,
) -> str:
    """Return planner-ready string: preference labels + working memory. Empty if no file or no content."""
    if user_id is None:
        return ""
    path = memory_store_path or os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    text, labels, _ = _load_raw(user_id, path)
    parts = []
    if labels:
        parts.append("Preferences: " + ", ".join(labels))
    if text:
        parts.append(text)
    return "\n\n".join(parts) if parts else ""


def get_user_memory_raw(
    user_id: str,
    memory_store_path: str | None = None,
) -> tuple[str, list[str]]:
    """Return (working_memory_text, preference_labels) for this user. Returns ("", []) if user_id is None."""
    if user_id is None:
        return ("", [])
    path = memory_store_path or os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    text, labels, _ = _load_raw(user_id, path)
    return (text, labels)


def append_user_memory(
    user_id: str,
    addition: str,
    memory_store_path: str | None = None,
) -> None:
    """Append to working memory; if over MAX_WORDS, compress then save. No-op if user_id is None."""
    if user_id is None:
        return
    path = memory_store_path or os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    text, labels, _ = _load_raw(user_id, path)
    new_text = (text + " " + (addition or "").strip()).strip()
    if _word_count(new_text) > MAX_WORDS:
        new_text = _compressor(new_text, MAX_WORDS)
    _save(user_id, new_text, labels, path)


def update_preference_labels(
    user_id: str,
    labels: list[str],
    memory_store_path: str | None = None,
) -> None:
    """Replace stored preference_labels with the given list and save. No-op if user_id is None."""
    if user_id is None:
        return
    path = memory_store_path or os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    text, _, _ = _load_raw(user_id, path)
    normalized = [str(x).strip() for x in labels if x]
    _save(user_id, text, normalized, path)


def append_preference_labels(
    user_id: str,
    labels: list[str],
    memory_store_path: str | None = None,
    dedupe: bool = True,
) -> None:
    """Add labels to existing list, then save. If dedupe=True, skip labels already present. No-op if user_id is None."""
    if user_id is None:
        return
    path = memory_store_path or os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    text, existing, _ = _load_raw(user_id, path)
    new_list = list(existing)
    for x in labels:
        s = str(x).strip()
        if not s:
            continue
        if dedupe and s in new_list:
            continue
        new_list.append(s)
    _save(user_id, text, new_list, path)
