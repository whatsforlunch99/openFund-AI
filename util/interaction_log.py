"""Systematic interaction call logging: every significant function with params and result.

Logs TRACE-style multi-line blocks (sequence, category, component, action, key=value)
so traces are human-readable. Use set_conversation_id() at API/agent entry so MCP
and other layers can attach logs without passing conversation_id. Gate with
INTERACTION_LOG=1 or config.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

_CONVERSATION_ID: ContextVar[str] = ContextVar("interaction_log_conversation_id", default="")
_SEQUENCE_LOCK = threading.Lock()
_SEQUENCES: dict[str, int] = {}
_ENABLED_OVERRIDE: Optional[bool] = None  # None = use env; True/False = override

logger = logging.getLogger("openfund.interaction")
_MAX_STR_LEN = 200

CATEGORY_WIDTH = 10
COMPONENT_WIDTH = 24
CONTINUATION_INDENT = "                     | "


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
    """Make obj safe for display and truncate long strings. Avoid logging raw PII/passwords."""
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


def _function_to_category_component(function_name: str) -> tuple[str, str]:
    """Map function_name to (category, component) for TRACE line 1."""
    fn = function_name or ""
    if fn.startswith("api.rest."):
        part = fn.replace("api.rest.", "", 1)
        return ("API", part.split(".")[0] if "." in part else part)
    if fn.startswith("api.websocket."):
        return ("API", "handle_websocket")
    if "message_bus" in fn and "send" in fn:
        return ("BUS", "message_bus")
    if "message_bus" in fn and "broadcast" in fn:
        return ("BUS", "message_bus")
    if fn.startswith("agents."):
        m = re.match(r"agents\.(\w+_agent)", fn)
        return ("AGENT", m.group(1) if m else fn.split(".")[1] if "." in fn else "agent")
    if fn.startswith("a2a.conversation_manager."):
        part = fn.replace("a2a.conversation_manager.ConversationManager.", "", 1)
        return ("MANAGER", part.split(".")[0] if "." in part else part)
    if fn.startswith("safety.safety_gateway."):
        return ("SAFETY", "process_user_input")
    if fn.startswith("mcp.mcp_client."):
        return ("MCP", "call_tool")
    parts = fn.split(".")
    if len(parts) >= 2:
        return ("LOG", parts[-2] + "." + parts[-1])
    return ("LOG", fn or "?")


def _action_from_result(result: Any, function_name: str) -> str:
    """Derive short action string from result and function_name."""
    fn = function_name or ""
    if isinstance(result, dict):
        if result.get("status_code") == 408:
            return "timeout"
        if result.get("status_code") == 200 and "post_chat_endpoint" in fn:
            return "response"
        if result.get("status_code") == 400:
            return "rejected"
        if "INFORM" in result and "sent to planner" in str(result.get("INFORM", "")):
            return "handle_message"
        if "INFORM" in result and "sent to responder" in str(result.get("INFORM", "")):
            return "handle_message"
        if result.get("REQUEST"):
            return "handle_message"
        if result.get("sent_to") is not None:
            return "send_to_specialist"
        if "send" in fn or "InMemoryMessageBus.send" in fn:
            return "send"
        if "broadcast" in fn:
            return "broadcast"
        if "register_reply" in fn:
            if result.get("status") == "complete":
                return "complete"
            return "register_reply"
        if "create_conversation" in fn:
            return "create"
        if "get_conversation" in fn:
            return "get"
        if "call_tool" in fn:
            return "call_tool"
        if "process_user_input" in fn:
            if "error" in result:
                return "rejected"
            return "processed"
    if "send" in fn and "message_bus" in fn:
        return "send"
    if "broadcast" in fn:
        return "broadcast"
    if ".handle_message" in fn:
        return "handle_message"
    if ".send" in fn:
        return "send"
    parts = fn.split(".")
    return parts[-1] if parts else "call"


def content_preview_for_log(
    content: Optional[dict[str, Any]],
    max_query: int = 100,
    max_text: int = 150,
) -> dict[str, Any]:
    """Build a small dict of content fields for TRACE logs (query, user_profile, final_response preview)."""
    if not content or not isinstance(content, dict):
        return {}
    out: dict[str, Any] = {}
    if content.get("query") is not None:
        q = str(content["query"])
        out["content_query"] = (q[:max_query] + "...") if len(q) > max_query else q
    if content.get("user_profile") is not None:
        out["content_user_profile"] = content["user_profile"]
    if content.get("conversation_id") is not None:
        out["content_conversation_id"] = content["conversation_id"]
    if content.get("final_response") is not None:
        r = str(content["final_response"])
        out["content_final_response"] = (r[:max_text] + "...") if len(r) > max_text else r
    if content.get("summary") is not None:
        s = str(content["summary"])
        out["content_summary"] = (s[:max_text] + "...") if len(s) > max_text else s
    for key in ("market_data", "sentiment", "regulatory", "documents", "graph", "analysis"):
        if content.get(key) is not None:
            v = content[key]
            if isinstance(v, str):
                out[f"content_{key}"] = (v[:max_text] + "...") if len(v) > max_text else v
            elif isinstance(v, (list, dict)):
                out[f"content_{key}"] = _sanitize(v, max_str_len=80)
            else:
                out[f"content_{key}"] = _sanitize(v)
    return out


def _format_continuation(
    params: Optional[dict[str, Any]],
    result: Any,
    conversation_id: str,
    function_name: str,
) -> list[str]:
    """Build indented key=value continuation lines. Special-case BUS send."""
    lines: list[str] = []
    prefix = CONTINUATION_INDENT
    fn = function_name or ""

    if "InMemoryMessageBus.send" in fn and isinstance(params, dict):
        sender = params.get("sender", "")
        receiver = params.get("receiver", "")
        if sender and receiver:
            lines.append(f"{prefix}from={sender} → {receiver}")

    if isinstance(params, dict):
        for k, v in params.items():
            if "InMemoryMessageBus.send" in fn and k in ("sender", "receiver"):
                continue
            v = _sanitize(v)
            if v is None:
                v = "null"
            lines.append(f"{prefix}{k}={v}")

    if result is not None:
        if isinstance(result, dict):
            for k, v in result.items():
                max_len = 300 if k in ("result_preview", "conclusion_preview") else _MAX_STR_LEN
                v = _sanitize(v, max_str_len=max_len)
                if v is None:
                    v = "null"
                lines.append(f"{prefix}{k}={v}")
        else:
            lines.append(f"{prefix}result={_sanitize(result)}")

    has_conversation_id = any("conversation_id=" in line for line in lines)
    if conversation_id:
        if not has_conversation_id:
            lines.append(f"{prefix}conversation_id={conversation_id}")
    else:
        if not has_conversation_id:
            lines.append(f"{prefix}conversation_id=(anonymous)")

    return lines


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
    """Log one function call in TRACE format: category, component, action, key=value lines.

    No-op if INTERACTION_LOG is disabled. conversation_id and sequence come from
    context (set by API or agent handle_message).
    """
    if not _is_enabled():
        return
    conversation_id = get_conversation_id()
    sequence = _next_sequence(conversation_id)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    category, component = _function_to_category_component(function_name)
    action = _action_from_result(result, function_name)
    category_pad = category + " " * (CATEGORY_WIDTH - len(category)) if len(category) <= CATEGORY_WIDTH else category[:CATEGORY_WIDTH]
    component_pad = component + " " * (COMPONENT_WIDTH - len(component)) if len(component) <= COMPONENT_WIDTH else component[:COMPONENT_WIDTH]
    line1 = f"{ts} | {category_pad} | {component_pad} | {action}"
    try:
        continuation = _format_continuation(
            params,
            result,
            conversation_id,
            function_name,
        )
    except (TypeError, ValueError):
        continuation = [CONTINUATION_INDENT + "(serialization error)"]
    if duration_ms is not None:
        continuation.append(f"{CONTINUATION_INDENT}duration_ms={duration_ms}")
    if continuation:
        message = f"TRACE {sequence}\n{line1}\n" + "\n".join(continuation) + "\n"
    else:
        message = f"TRACE {sequence}\n{line1}\n"
    logger.info("%s", message)
