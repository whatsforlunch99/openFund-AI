"""DataClassifier: route data to appropriate databases based on type and content.

Determines which databases (PostgreSQL, Neo4j, Milvus) should receive each type of data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ClassificationResult:
    """Result of classifying a data file."""

    task_type: str
    targets: list[str]
    sub_types: dict[str, list[str]]


class DataClassifier:
    """Classify data to target databases based on type and content characteristics."""

    # One-to-one routing: these task types always map to a single database target.
    STATIC_ROUTING: dict[str, str] = {
        "stock_data": "postgres",
        "balance_sheet": "postgres",
        "cashflow": "postgres",
        "income_statement": "postgres",
        "insider_transactions": "postgres",
        "indicators": "postgres",
        "fund_performance": "postgres",
        "fund_risk": "postgres",
        "fund_flows": "postgres",
    }

    # Multi-target routing: one task can materialize into multiple storage backends.
    MULTI_TARGET: dict[str, list[str]] = {
        "fundamentals": ["postgres", "neo4j"],
        "info": ["postgres", "neo4j", "milvus"],
        "news": ["milvus"],
        "global_news": ["milvus"],
        "fund_info": ["postgres", "neo4j"],
        "fund_holdings": ["postgres", "neo4j"],
        "fund_sectors": ["postgres", "neo4j"],
    }

    # Optional finer-grained routing hints used by downstream transformers.
    SUB_TYPE_ROUTING: dict[str, dict[str, list[str]]] = {
        "fundamentals": {
            "metrics": ["postgres"],
            "sector_industry": ["neo4j"],
        },
        "info": {
            "metrics": ["postgres"],
            "company": ["neo4j"],
            "sector_industry": ["neo4j"],
            "officers": ["neo4j"],
            "description": ["milvus"],
        },
    }

    def classify(self, task_type: str, content: Any = None) -> ClassificationResult:
        """
        Determine target databases for a given task type.

        Args:
            task_type: Data task type (e.g. "stock_data", "fundamentals").
            content: Optional content for dynamic classification (not used currently).

        Returns:
            ClassificationResult with targets and sub_types.
        """
        # Compute target set from static or multi-target routing tables.
        if task_type in self.MULTI_TARGET:
            targets = self.MULTI_TARGET[task_type]
            sub_types = self.SUB_TYPE_ROUTING.get(task_type, {})
        elif task_type in self.STATIC_ROUTING:
            targets = [self.STATIC_ROUTING[task_type]]
            sub_types = {}
        else:
            targets = []
            sub_types = {}

        return ClassificationResult(
            task_type=task_type,
            targets=targets,
            sub_types=sub_types,
        )

    def get_postgres_tasks(self) -> list[str]:
        """Return all task types that write to PostgreSQL."""
        # Start with static postgres-only tasks, then append multi-target entries.
        tasks = [k for k, v in self.STATIC_ROUTING.items() if v == "postgres"]
        for k, targets in self.MULTI_TARGET.items():
            if "postgres" in targets and k not in tasks:
                tasks.append(k)
        return tasks

    def get_neo4j_tasks(self) -> list[str]:
        """Return all task types that write to Neo4j."""
        # Neo4j currently appears only in multi-target routes.
        tasks = []
        for k, targets in self.MULTI_TARGET.items():
            if "neo4j" in targets:
                tasks.append(k)
        return tasks

    def get_milvus_tasks(self) -> list[str]:
        """Return all task types that write to Milvus."""
        # Milvus currently appears only in multi-target routes.
        tasks = []
        for k, targets in self.MULTI_TARGET.items():
            if "milvus" in targets:
                tasks.append(k)
        return tasks

    def should_write_to(self, task_type: str, db: str) -> bool:
        """Check if a task type should write to a specific database."""
        result = self.classify(task_type)
        return db in result.targets
