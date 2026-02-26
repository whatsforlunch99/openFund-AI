"""Live LLM client (OpenAI). Used when LLM_API_KEY is set and openai is installed."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

ALLOWED_AGENTS = ("librarian", "websearcher", "analyst")

DECOMPOSE_SYSTEM = """You are a task decomposer for an investment research assistant.
Given a user query, output a JSON array of steps. Each step has:
- "agent": one of librarian, websearcher, analyst
- "action": string (e.g. read_file, fetch_market, analyze)
- "params": object with at least "query" (the user query)

Output only the JSON array, no markdown or explanation. Example:
[{"agent":"librarian","action":"read_file","params":{"query":"..."}},{"agent":"websearcher","action":"fetch_market","params":{"query":"..."}},{"agent":"analyst","action":"analyze","params":{"query":"..."}}]"""


class LiveLLMClient:
    """OpenAI-backed LLM client for task decomposition."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def decompose_to_steps(self, query: str) -> list[dict[str, Any]]:
        """Call the LLM to decompose the query into steps; parse and validate."""
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": DECOMPOSE_SYSTEM},
                    {"role": "user", "content": query},
                ],
                max_tokens=500,
            )
            text = (
                response.choices[0].message.content
                if response.choices and response.choices[0].message
                else ""
            ).strip()
            steps = self._parse_steps(text, query)
            if steps:
                return steps
        except Exception as e:
            logger.warning("LLM decompose_to_steps failed: %s", e)
        # Fall back to default three steps so the flow still runs
        from llm.static_client import DEFAULT_STATIC_STEPS

        return [
            {**s, "params": {**(s.get("params") or {}), "query": query}}
            for s in DEFAULT_STATIC_STEPS
        ]

    def _parse_steps(self, text: str, query: str) -> list[dict[str, Any]]:
        """Extract JSON array from LLM response and validate agent names."""
        # Allow JSON inside markdown code block
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
            if match:
                text = match.group(1)
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            agent = (item.get("agent") or "").strip().lower()
            if agent not in ALLOWED_AGENTS:
                continue
            action = (item.get("action") or "analyze").strip() or "analyze"
            params = dict(item.get("params") or {})
            params.setdefault("query", query)
            result.append({"agent": agent, "action": action, "params": params})
        return result
