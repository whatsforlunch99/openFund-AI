"""Planner-only types shared by planner_agent and planner helper modules."""

from __future__ import annotations

from typing import Any, Optional

# Same allowed values as api/rest.py; normalize so Responder/OutputRail get consistent profile.
VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


class TaskStep:
    """One step in a decomposed task chain (target agent + params).

    Attributes:
        agent: Target agent: "librarian" | "websearcher" | "analyst".
        params: Parameters for the step (including "query"); forwarded as ACLMessage content.
    """

    def __init__(
        self,
        agent: str,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        self.agent = agent
        self.params = params or {}
