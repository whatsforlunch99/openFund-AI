"""Data Manager: collect data from MCP tools and distribute to databases.

Run: python -m data_manager --help
     python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15
     python -m data_manager distribute --symbol NVDA
     python -m data_manager status --symbol NVDA
"""

from data_manager.collector import DataCollector, CollectionResult, BatchResult
from data_manager.tasks import CollectionTask, COLLECTION_TASKS
from data_manager.classifier import DataClassifier, ClassificationResult
from data_manager.transformer import DataTransformer
from data_manager.distributor import DataDistributor, DistributionResult, BatchDistributionResult

# Curated exports make the package convenient for scripts/tests without deep imports.
__all__ = [
    "DataCollector",
    "CollectionResult",
    "BatchResult",
    "CollectionTask",
    "COLLECTION_TASKS",
    "DataClassifier",
    "ClassificationResult",
    "DataTransformer",
    "DataDistributor",
    "DistributionResult",
    "BatchDistributionResult",
]
