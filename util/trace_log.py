"""Human-readable trace logging: stage, input, output, next transition."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _fmt(items: dict[str, Any]) -> str:
    """Format key=value pairs for In/Out."""
    # Keep formatter deterministic so trace lines are easy to compare in logs/tests.
    if not items:
        return ""
    return ", ".join(f"{k}={v}" for k, v in items.items())


def trace(
    step: int,
    stage: str,
    *,
    in_: dict[str, Any] | None = None,
    out: str | dict[str, Any] | None = None,
    next_: str = "",
) -> None:
    """Log one trace step in a readable block: stage, input, output, next.

    Example output:
      [Step 1] request_validated
          In:   query_len=25, user_profile=beginner, conversation_id=(new)
          Out:  validated
          Next: safety check
    """
    in_str = _fmt(in_) if isinstance(in_, dict) else (in_ or "")
    out_str = _fmt(out) if isinstance(out, dict) else (str(out) if out else "")
    lines = [f"  [Step {step}] {stage}"]
    if in_str:
        lines.append(f"      In:   {in_str}")
    if out_str:
        lines.append(f"      Out:  {out_str}")
    if next_:
        lines.append(f"      Next: {next_}")
    # Emit one log block so traces are easy to follow
    logger.info("\n" + "\n".join(lines))
