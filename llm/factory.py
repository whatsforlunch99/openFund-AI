"""Factory: return LiveLLMClient when LLM_API_KEY is set; required for app startup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config.config import Config

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


def get_llm_client(config: Config) -> LLMClient:
    """Return a live LLM client for task decomposition and agent completion.

    Requires config.llm_api_key to be set and non-empty. Install optional
    dependency: pip install openfund-ai[llm].

    Returns:
        LiveLLMClient instance.

    Raises:
        ValueError: If LLM_API_KEY is not set or empty.
    """
    if not (config.llm_api_key and config.llm_api_key.strip()):
        raise ValueError(
            "LLM_API_KEY is required. Set it in .env (see .env.example and README)."
        )
    try:
        from llm.live_client import LiveLLMClient
    except ImportError as e:
        raise ImportError(
            "LLM extra is required. Install with: pip install openfund-ai[llm]"
        ) from e
    # Use configured model and base URL (e.g. DeepSeek) or defaults
    model = (config.llm_model or "gpt-4o-mini").strip() or "gpt-4o-mini"
    base_url = (config.llm_base_url or "").strip() or None
    return LiveLLMClient(
        api_key=config.llm_api_key.strip(),
        model=model,
        base_url=base_url,
    )
