"""Planner LLM sufficiency check and refined round step generation."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from agents.planner_types import TaskStep

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


def check_planner_sufficiency(
    llm_client: "LLMClient",
    user_query: str,
    aggregated: str,
) -> bool:
    """Call LLM to decide if aggregated info is sufficient. Returns True if SUFFICIENT."""
    try:
        from llm.prompts import get_planner_sufficiency_user_content

        system = "You decide if the research is sufficient to answer the user. Answer only SUFFICIENT or INSUFFICIENT."
        user_content = get_planner_sufficiency_user_content(user_query, aggregated)
        out = llm_client.complete(system, user_content)
        s = (out or "").strip().upper()
        return s.startswith("SUFFICIENT") and not s.startswith("INSUFFICIENT")
    except Exception as e:
        logger.debug("Sufficiency check failed, treating as sufficient: %s", e)
        return True


def get_planner_refined_steps(
    llm_client: "LLMClient",
    user_query: str,
    aggregated: str,
) -> list[TaskStep]:
    """Get steps for round 2 from LLM refined-queries JSON. Returns empty list on parse failure."""
    try:
        from llm.prompts import get_planner_refined_user_content

        system = (
            "You output a JSON object with keys librarian, websearcher, analyst "
            "(only include agents that can fill gaps). Each value is a query string."
        )
        user_content = get_planner_refined_user_content(user_query, aggregated)
        out = llm_client.complete(system, user_content)
        text = (out or "").strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
            if match:
                text = match.group(1)
        raw = json.loads(text)
        if not isinstance(raw, dict):
            return []
        steps: list[TaskStep] = []
        for agent in ("librarian", "websearcher", "analyst"):
            q = raw.get(agent)
            if isinstance(q, str) and q.strip():
                steps.append(
                    TaskStep(
                        agent=agent,
                        params={"query": q.strip()},
                    )
                )
        return steps
    except Exception as e:
        logger.debug("Refined steps parse failed: %s", e)
        return []
