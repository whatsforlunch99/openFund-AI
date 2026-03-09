"""LLM integration for task decomposition (Stage 10.2).

When LLM_API_KEY is set and openfund-ai[llm] is installed, get_llm_client
returns a live client. Install optional deps: pip install openfund-ai[llm]
"""

from llm.base import LLMClient
from llm.factory import get_llm_client

# Public LLM surface for runtime wiring.
__all__ = ["LLMClient", "get_llm_client"]
