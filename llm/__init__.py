"""LLM integration for task decomposition (Stage 10.2).

Provides a static mock by default (no API key). When LLM_API_KEY is set,
a live client can be used for decompose_to_steps. Install optional deps:
  pip install openfund-ai[llm]
"""

from llm.base import LLMClient
from llm.factory import get_llm_client
from llm.static_client import StaticLLMClient

# Public LLM surface for runtime wiring and tests.
__all__ = ["LLMClient", "StaticLLMClient", "get_llm_client"]
