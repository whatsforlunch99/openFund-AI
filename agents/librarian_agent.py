"""LibrarianAgent composed from split modules in agents/."""

from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.librarian_orchestration import LibrarianOrchestrationMixin


class LibrarianAgent(LibrarianOrchestrationMixin, BaseAgent):
    """Composed class from split in-folder parts."""

    pass


__all__ = ["LibrarianAgent"]
