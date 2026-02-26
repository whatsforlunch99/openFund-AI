"""Static mock LLM client: returns a fixed task decomposition (no API key)."""

from __future__ import annotations

from typing import Any

# Default one-round steps: same as PlannerAgent.decompose_task() before LLM.
DEFAULT_STATIC_STEPS = [
    {"agent": "librarian", "action": "read_file", "params": {"query": ""}},
    {"agent": "websearcher", "action": "fetch_market", "params": {"query": ""}},
    {"agent": "analyst", "action": "analyze", "params": {"query": ""}},
]


class StaticLLMClient:
    """Mock LLM client that returns a fixed list of steps.

    Use when LLM_API_KEY is not set. Keeps E2E and API runnable without an API key.
    """

    def __init__(
        self,
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize with optional custom steps.

        Args:
            steps: Optional list of step dicts (agent, action, params).
                Defaults to DEFAULT_STATIC_STEPS.
        """
        self._steps = steps if steps is not None else list(DEFAULT_STATIC_STEPS)

    def decompose_to_steps(self, query: str) -> list[dict[str, Any]]:
        """Return static steps with query filled into params."""
        result = []
        for s in self._steps:
            step = dict(s)
            params = dict(step.get("params") or {})
            # Always pass the user query into each step so agents receive it
            params["query"] = query
            step["params"] = params
            result.append(step)
        return result
