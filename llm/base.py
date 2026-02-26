"""Abstract interface for LLM-backed task decomposition."""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for LLM clients used by Planner for task decomposition.

    When no API key is set, use StaticLLMClient (mock). When LLM_API_KEY is set,
    use a live client (e.g. OpenAI) if the optional dependency is installed.
    """

    def decompose_to_steps(self, query: str) -> list[dict[str, Any]]:
        """Turn a user query into a list of task steps.

        Each step is a dict with keys: agent (str), action (str), params (dict).
        Allowed agents: "librarian", "websearcher", "analyst".

        Args:
            query: Raw user investment query.

        Returns:
            List of step dicts, e.g. [{"agent": "librarian", "action": "read_file", "params": {"query": "..."}}].
        """
        ...
