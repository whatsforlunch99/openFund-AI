"""Live LLM client (OpenAI-compatible). Used when LLM_API_KEY is set and openai is installed."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from llm.prompts import PLANNER_DECOMPOSE
from util.log_format import struct_log

logger = logging.getLogger(__name__)

ALLOWED_AGENTS = ("librarian", "websearcher", "analyst")


class LiveLLMClient:
    """OpenAI-compatible LLM client for task decomposition and completion (e.g. DeepSeek, OpenAI)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
    ) -> None:
        # Fail fast on missing SDK so API startup surfaces a clear setup error.
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise ImportError(
                "openai package is required for LiveLLMClient. "
                "Install with: pip install -e '.[llm]'"
            ) from e
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or "").strip() or None
        self._timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
        self._client: Any = None
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        kwargs["timeout"] = max(1.0, self._timeout_seconds)
        kwargs["max_retries"] = 0
        self._client = OpenAI(**kwargs)

    def _get_client(self) -> Any:
        # Client is initialized eagerly in __init__ for fail-fast dependency checks.
        return self._client

    def decompose_to_steps(
        self, query: str, memory_context: str = ""
    ) -> list[dict[str, Any]]:
        """Call the LLM to decompose the query into steps; parse and validate."""
        try:
            # Build request payload: combine current query with optional user memory context.
            client = self._get_client()
            user_input = query
            if isinstance(memory_context, str) and memory_context.strip():
                user_input = (
                    f"User query:\n{query}\n\n"
                    f"Prior memory context (use when relevant):\n{memory_context.strip()}"
                )
            # Declare chat message list in OpenAI format, then request a compact JSON response.
            planner_messages: list[dict[str, str]] = [
                {"role": "system", "content": PLANNER_DECOMPOSE},  # type: ignore[dict-item]
                {"role": "user", "content": user_input},
            ]
            response = client.chat.completions.create(
                model=self._model,
                messages=planner_messages,
                max_tokens=500,
                timeout=max(1.0, self._timeout_seconds),
            )
            raw = response.choices[0].message.content if response.choices and response.choices[0].message else None
            text = (raw or "").strip()
            # Parse + validate into canonical planner steps.
            steps = self._parse_steps(text, query)
            if steps is not None:
                return steps  # May be empty list (LLM returned []) or list of steps
        except Exception as e:
            err_msg = str(e).lower()
            if "timed out" in err_msg or "timeout" in err_msg:
                struct_log(logger, logging.WARNING, "llm.timeout", message=str(e), recovered=True)
            else:
                logger.warning("LLM decompose_to_steps failed: %s", e)
        # Fallback path: keep the pipeline running with static three-agent steps.
        from llm.static_client import DEFAULT_STATIC_STEPS

        return [
            {**s, "params": {**(s.get("params") or {}), "query": query}}  # type: ignore[dict-item]
            for s in DEFAULT_STATIC_STEPS
        ]

    def _parse_steps(self, text: str, query: str) -> list[dict[str, Any]] | None:
        """Extract JSON array from LLM response; validate agent names. Each element is agent + params (query). Per-step query from params.query or top-level 'query'; only use user query when step has neither. Returns None on parse failure, [] when LLM returned valid empty array."""
        # Normalize markdown-wrapped answers into raw JSON text before decoding.
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
            if match:
                text = match.group(1)
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, list):
            return None
        # Validate each element and coerce to canonical planner-step shape.
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            agent = (item.get("agent") or "").strip().lower()
            if agent not in ALLOWED_AGENTS:
                continue
            params = dict(item.get("params") or {})
            # Per-step query: from params.query or top-level "query"; only setdefault when neither present.
            step_query = params.get("query") or item.get("query")
            if isinstance(step_query, str) and step_query.strip():
                params["query"] = step_query.strip()
            else:
                params.setdefault("query", query)
            result.append({"agent": agent, "params": params})
        return result

    def complete(self, system_prompt: str, user_content: str) -> str:
        """Call the LLM for a single completion (e.g. Responder format_response)."""
        try:
            client = self._get_client()
            completion_messages: list[dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
            response = client.chat.completions.create(
                model=self._model,
                messages=completion_messages,
                max_tokens=1500,
                timeout=max(1.0, self._timeout_seconds),
            )  # type: ignore[dict-item]
            text = (
                (response.choices[0].message.content or "")
                if response.choices and response.choices[0].message
                else ""
            ).strip()
            return text or user_content
        except Exception as e:
            err_msg = str(e).lower()
            if "timed out" in err_msg or "timeout" in err_msg:
                struct_log(logger, logging.WARNING, "llm.timeout", message=str(e), recovered=True)
            else:
                logger.warning("LLM complete failed: %s", e)
            return user_content

    def select_tools(
        self,
        system_prompt: str,
        user_content: str,
        tool_descriptions: str,
    ) -> list[dict[str, Any]]:
        """Call the LLM to get tool calls; parse JSON array of {tool, payload}. Returns [] on failure."""
        try:
            # Inject runtime tool-description text into the system prompt template.
            if "{tool_descriptions}" in system_prompt:
                system_prompt = system_prompt.format(tool_descriptions=tool_descriptions)
            text = self.complete(system_prompt, user_content)
            from llm.tool_descriptions import normalize_tool_calls

            # Parse raw model output and normalize to [{"tool", "payload"}].
            parsed = self._parse_tool_calls(text)
            return normalize_tool_calls(parsed)
        except Exception as e:
            err_msg = str(e).lower()
            if "timed out" in err_msg or "timeout" in err_msg:
                struct_log(logger, logging.WARNING, "llm.timeout", message=str(e), recovered=True)
            else:
                logger.warning("LLM select_tools failed: %s", e)
            return []

    def _parse_tool_calls(self, text: str) -> list[dict[str, Any]]:
        """Extract JSON array of {tool, payload} from LLM response. Accepts 'tool' or 'tool_name'."""
        if not (text or "").strip():
            return []
        text = text.strip()
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
            tool = item.get("tool") or item.get("tool_name")
            payload = item.get("payload")
            if isinstance(tool, str) and tool.strip():
                result.append({
                    "tool": tool.strip(),
                    "payload": payload if isinstance(payload, dict) else {},
                })
        return result
