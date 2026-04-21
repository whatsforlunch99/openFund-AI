"""WebSearcherAgent composed from split modules in agents/."""

from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.websearch_news_processing import WebSearchNewsProcessingMixin
from agents.websearch_news_sources import WebSearchNewsSourceMixin
from agents.websearch_orchestration import WebSearchOrchestrationMixin
from agents.websearch_pipeline import WebSearchPipelineMixin
from agents.websearch_symbol_resolution import WebSearchSymbolResolutionMixin


class WebSearcherAgent(
    WebSearchSymbolResolutionMixin,
    WebSearchNewsSourceMixin,
    WebSearchNewsProcessingMixin,
    WebSearchPipelineMixin,
    WebSearchOrchestrationMixin,
    BaseAgent,
):
    """Composed class from split in-folder parts."""

    pass


__all__ = ["WebSearcherAgent"]
