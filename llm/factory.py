"""Factory: return StaticLLMClient or LiveLLMClient based on config."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config.config import Config
from llm.static_client import StaticLLMClient

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


def get_llm_client(config: Config) -> LLMClient:
    """Return an LLM client for task decomposition.

    - If config.llm_api_key is set and non-empty, attempts to use a live client
      (e.g. OpenAI). Requires optional dependency: pip install openfund-ai[llm].
    - Otherwise returns StaticLLMClient (mock) so the app runs without an API key.

    Returns:
        LLMClient implementation (static mock or live when key + deps available).
    """
    if config.llm_api_key and config.llm_api_key.strip():
        # Use live OpenAI client when key is set and openai package is installed
        try:
            from llm.live_client import LiveLLMClient

            model = (config.llm_model or "gpt-4o-mini").strip() or "gpt-4o-mini"
            return LiveLLMClient(api_key=config.llm_api_key.strip(), model=model)
        except ImportError as e:
            logger.warning(
                "LLM_API_KEY set but live client unavailable (install [llm] extra): %s. Using static mock.",
                e,
            )
    return StaticLLMClient()
