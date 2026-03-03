"""Structured logging: UTC timestamp, dotted category, key=value messages."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

CATEGORY_WIDTH = 28
MESSAGE_INDENT = 45


def _format_value(v: Any) -> str:
    """Format a value for key=value; quote strings that contain spaces."""
    s = str(v)
    if " " in s or "\n" in s or '"' in s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


class OpenFundFormatter(logging.Formatter):
    """Format log records as [ISO8601Z] LEVEL  category   message (key=value; multiline indented)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        level = "WARN" if record.levelno == logging.WARNING else record.levelname
        raw_category = getattr(record, "openfund_category", None)
        if raw_category == "section":
            return record.getMessage().rstrip()
        category = (raw_category or record.name)
        if len(category) > CATEGORY_WIDTH:
            category = category[: CATEGORY_WIDTH - 1] + "…"
        else:
            category = category + " " * (CATEGORY_WIDTH - len(category))
        msg = record.getMessage()
        if "\n" in msg:
            lines = msg.split("\n")
            first = lines[0]
            rest = "\n".join(" " * MESSAGE_INDENT + line for line in lines[1:])
            msg = first + ("\n" + rest if rest else "")
        return f"[{ts}] {level:4}  {category}   {msg}"


def struct_log(
    logger: logging.Logger,
    level: int,
    category: str,
    **kwargs: Any,
) -> None:
    """Log a structured message: category + key=value pairs. Values with spaces are quoted."""
    parts = []
    for k, v in kwargs.items():
        parts.append(f"{k}={_format_value(v)}")
    message = " ".join(parts)
    logger.log(level, message, extra={"openfund_category": category})


def log_agent_section(logger: logging.Logger, agent_name: str) -> None:
    """Log an agent section separator (no timestamp)."""
    sep = "─" * 40
    block = f"\n{sep}\nAGENT: {agent_name.upper()}\n{sep}"
    logger.info(block, extra={"openfund_category": "section"})
