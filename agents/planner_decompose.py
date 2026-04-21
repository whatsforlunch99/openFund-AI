"""LLM and fallback decomposition of user queries into planner TaskSteps."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from agents.planner_types import TaskStep
from util.agent_heuristics import planner_fallback_substring_symbol_pairs

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


def decompose_planner_task(
    llm_client: Optional[LLMClient],
    query: str,
    user_memory: str = "",
    symbol_resolution: Optional[dict[str, Any]] = None,
) -> list[TaskStep]:
    """Produce task steps from the user query (LLM or fixed three-step fallback)."""
    if llm_client is not None:
        try:
            step_dicts = llm_client.decompose_to_steps(
                query,
                memory_context=user_memory,
            )
            if step_dicts is not None:
                if not step_dicts:
                    return [TaskStep(agent="analyst", params={"query": query})]
                return [
                    TaskStep(
                        agent=s.get("agent", "librarian"),
                        params=dict(s.get("params") or {}),
                    )
                    for s in step_dicts
                    if isinstance(s, dict)
                    and (s.get("agent") or "").strip().lower()
                    in ("librarian", "websearcher", "analyst")
                ]
        except Exception as e:
            logger.debug("LLM task parse failed, using default steps: %s", e)

    q_lower = query.lower()
    fund = ""
    if (
        symbol_resolution
        and symbol_resolution.get("status") == "resolved"
        and isinstance(symbol_resolution.get("listings"), list)
        and symbol_resolution["listings"]
    ):
        listing0 = symbol_resolution["listings"][0]
        if isinstance(listing0, dict):
            fund = str(
                listing0.get("symbol_yahoo") or listing0.get("symbol_compact") or ""
            )
    if not fund:
        for substring, symbol in planner_fallback_substring_symbol_pairs():
            if substring in q_lower:
                fund = symbol
                break
    return [
        TaskStep(
            agent="librarian",
            params={
                "query": query,
                "vector_query": query,
                "fund": fund,
            },
        ),
        TaskStep(
            agent="websearcher",
            params={"query": query, "fund": fund} if fund else {"query": query},
        ),
        TaskStep(agent="analyst", params={"query": query}),
    ]
