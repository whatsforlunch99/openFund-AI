"""Root log formatter: UTC timestamp, logger name as category, message."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

CATEGORY_WIDTH = 28
MESSAGE_INDENT = 45


class OpenFundFormatter(logging.Formatter):
    """Format log records as [ISO8601Z] LEVEL  category   message (multiline indented)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        level = "WARN" if record.levelno == logging.WARNING else record.levelname
        category = getattr(record, "openfund_category", None) or record.name
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
