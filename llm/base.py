"""Abstract interface for LLM-backed task decomposition and completion."""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for LLM clients used by Planner (decompose) and optionally Responder (complete).

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

    def complete(self, system_prompt: str, user_content: str) -> str:
        """Produce a completion given a system prompt and user content.

        Used optionally by Responder (and other agents) for format_response or summarization.
        Static client returns user_content unchanged; live client calls the LLM.

        Args:
            system_prompt: System message content.
            user_content: User message content.

        Returns:
            Model response text, or passthrough of user_content for static mock.
        """
        ...
