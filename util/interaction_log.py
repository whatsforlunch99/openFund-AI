"""Systematic interaction call logging: every significant function with params and result.

Logs one JSON object per line (ts, conversation_id, function, params, result,
duration_ms, sequence) so traces can be filtered by conversation. Use
set_conversation_id() at API/agent entry so MCP and other layers can attach
logs without passing conversation_id. Gate with INTERACTION_LOG=1 or config.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

_CONVERSATION_ID: ContextVar[str] = ContextVar("interaction_log_conversation_id", default="")
_SEQUENCE_LOCK = threading.Lock()
_SEQUENCES: dict[str, int] = {}
_ENABLED_OVERRIDE: Optional[bool] = None  # None = use env; True/False = override

logger = logging.getLogger("openfund.interaction")
_MAX_STR_LEN = 200


def set_conversation_id(conversation_id: str) -> None:
    """Set the current conversation id for this context (thread/task)."""
    _CONVERSATION_ID.set(conversation_id or "")


def get_conversation_id() -> str:
    """Return the current conversation id, or empty string if not set."""
    return _CONVERSATION_ID.get("")


def _next_sequence(conversation_id: str) -> int:
    """Thread-safe per-conversation sequence counter."""
    with _SEQUENCE_LOCK:
        n = _SEQUENCES.get(conversation_id, 0) + 1
        _SEQUENCES[conversation_id] = n
        return n


def _sanitize(obj: Any, max_str_len: int = _MAX_STR_LEN) -> Any:
    """Make obj JSON-serializable and truncate long strings. Avoid logging raw PII/passwords."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, str):
        return obj[:max_str_len] + ("..." if len(obj) > max_str_len else "")
    if isinstance(obj, dict):
        return {str(k): _sanitize(v, max_str_len) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(x, max_str_len) for x in obj]
    return str(obj)[:max_str_len]


def set_enabled(enabled: bool) -> None:
    """Override interaction log enabled state (e.g. from Config). None to reset to env."""
    global _ENABLED_OVERRIDE
    _ENABLED_OVERRIDE = enabled


def _is_enabled() -> bool:
    """True if interaction logging is enabled (override or env; default True)."""
    if _ENABLED_OVERRIDE is not None:
        return _ENABLED_OVERRIDE
    v = os.getenv("INTERACTION_LOG", "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def log_call(
    function_name: str,
    params: Optional[dict[str, Any]] = None,
    result: Optional[Any] = None,
    duration_ms: Optional[float] = None,
) -> None:
    """Log one function call: function name, sanitized params, sanitized result, optional duration.

    Emits one JSON object per line to the openfund.interaction logger at INFO.
    No-op if INTERACTION_LOG is disabled. conversation_id and sequence come from
    context (set by API or agent handle_message).
    """
    if not _is_enabled():
        return
    conversation_id = get_conversation_id()
    sequence = _next_sequence(conversation_id)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "function": function_name,
        "params": _sanitize(params) if params is not None else {},
        "result": _sanitize(result) if result is not None else None,
        "duration_ms": duration_ms,
        "sequence": sequence,
    }
    try:
        line = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        payload["params"] = "(serialization error)"
        payload["result"] = "(serialization error)"
        line = json.dumps(payload, default=str)
    logger.info("%s", line)
