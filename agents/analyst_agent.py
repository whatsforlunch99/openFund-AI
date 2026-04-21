"""AnalystAgent composed from split modules in agents/."""

from __future__ import annotations

from agents.analyst_analysis import AnalystAnalysisMixin
from agents.analyst_orchestration import (
    AnalystOrchestrationMixin,
    apply_resolved_symbol_to_analyst_calls,
)
from agents.base_agent import BaseAgent


class AnalystAgent(AnalystOrchestrationMixin, AnalystAnalysisMixin, BaseAgent):
    """Composed class from split in-folder parts."""

    pass


__all__ = ["AnalystAgent", "apply_resolved_symbol_to_analyst_calls"]
