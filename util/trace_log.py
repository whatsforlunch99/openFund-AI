"""Pipeline step tracing for agents (e.g. WebSearcher).

Called with fixed sequence + step name + in_/out/next_. When interaction log is
enabled, emits via interaction_log; otherwise debug-only to avoid noise.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def trace(
    sequence: int,
    step: str,
    *,
    in_: Optional[dict[str, Any]] = None,
    out: Any = None,
    next_: Optional[str] = None,
) -> None:
    """Record a pipeline step (no-op beyond logging)."""
    try:
        from util import interaction_log

        if interaction_log._is_enabled():
            interaction_log.log_call(
                f"trace.{step}",
                params={"in": in_, "out": out, "next": next_},
                result={"trace_step": step, "sequence": sequence},
            )
            return
    except Exception:
        pass
    logger.debug(
        "trace seq=%s step=%s in=%s out=%s next=%s",
        sequence,
        step,
        in_,
        out,
        next_,
    )
