"""Abstract interface for LLM-backed task decomposition and completion."""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for LLM clients used by Planner (decompose) and optionally Responder (complete).

    When no API key is set, use StaticLLMClient (mock). When LLM_API_KEY is set,
    use a live client (e.g. OpenAI) if the optional dependency is installed.
    """

    def decompose_to_steps(
        self, query: str, memory_context: str = ""
    ) -> list[dict[str, Any]]:
        """Turn a user query into a list of task steps.

        Each step is a dict with keys: agent (str), params (dict).
        Allowed agents: "librarian", "websearcher", "analyst".

        Args:
            query: Raw user investment query.
            memory_context: Optional user memory context from prior conversations.

        Returns:
            List of step dicts, e.g. [{"agent": "librarian", "params": {"query": "..."}}].
        """
        # Contract method: implementations must return planner-compatible step dicts.
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
        # Contract method: implementations decide whether to call live model or mock behavior.
        ...

    def select_tools(
        self,
        system_prompt: str,
        user_content: str,
        tool_descriptions: str,
    ) -> list[dict[str, Any]]:
        """Return a list of tool calls: [{"tool": "tool_name", "payload": {...}}, ...].

        Used by Librarian, WebSearcher, Analyst to decide which MCP tools to call.
        When not implemented or parsing fails, caller should fall back to content-key dispatch.

        Args:
            system_prompt: System message (tool-selection instructions).
            user_content: User message (e.g. decomposed query).
            tool_descriptions: Text listing allowed tools and payload params.

        Returns:
            List of dicts with "tool" (str) and "payload" (dict). Empty list on failure or when no tools.
        """
        # Contract method: specialists rely on this shape before tool-name filtering.
        ...
