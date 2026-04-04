"""Deterministic LLM client for tests and E2E without live API calls."""

from __future__ import annotations

from typing import Any, Optional

_DEFAULT_AGENTS = ("librarian", "websearcher", "analyst")


class StaticLLMClient:
    """Returns fixed decomposition steps, passthrough complete, and empty tool selection."""

    def __init__(self, steps: Optional[list[dict[str, Any]]] = None) -> None:
        self._custom_steps = steps

    def decompose_to_steps(
        self, query: str, memory_context: str = ""
    ) -> list[dict[str, Any]]:
        if self._custom_steps is not None:
            out: list[dict[str, Any]] = []
            for item in self._custom_steps:
                if not isinstance(item, dict):
                    continue
                agent = (item.get("agent") or "").strip().lower()
                params = dict(item.get("params") or {})
                params["query"] = query
                out.append({"agent": agent, "params": params})
            return out

        return [{"agent": a, "params": {"query": query}} for a in _DEFAULT_AGENTS]

    def complete(self, system_prompt: str, user_content: str) -> str:
        return user_content

    def select_tools(
        self,
        system_prompt: str,
        user_content: str,
        tool_descriptions: str,
    ) -> list[dict[str, Any]]:
        return []
