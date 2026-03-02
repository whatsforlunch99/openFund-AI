"""Collection task definitions for DataCollector.

Each task maps a data type to an MCP tool function and defines how to build
payloads and output filenames.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable


def _days_ago(as_of_date: str, days: int) -> str:
    """Return date string N days before as_of_date."""
    # Parse anchor date first, then subtract rolling window days.
    dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    return (dt - timedelta(days=days)).strftime("%Y-%m-%d")


@dataclass
class CollectionTask:
    """Single collection task configuration."""

    task_type: str
    tool_name: str
    payload_builder: Callable[[str, str], dict]
    output_filename: Callable[[str, str], str]
    enabled: bool = True


COLLECTION_TASKS: list[CollectionTask] = [
    # Price history window (1 year) for trend and return calculations.
    CollectionTask(
        task_type="stock_data",
        tool_name="market_tool.get_stock_data",
        payload_builder=lambda s, d: {
            "symbol": s,
            "start_date": _days_ago(d, 365),
            "end_date": d,
        },
        output_filename=lambda s, d: f"{s}_ohlcv_{d}.json",
    ),
    CollectionTask(
        task_type="fundamentals",
        tool_name="market_tool.get_fundamentals",
        payload_builder=lambda s, d: {"symbol": s},
        output_filename=lambda s, d: f"{s}_fundamentals_{d}.json",
    ),
    CollectionTask(
        task_type="balance_sheet",
        tool_name="market_tool.get_balance_sheet",
        payload_builder=lambda s, d: {"symbol": s, "freq": "quarterly"},
        output_filename=lambda s, d: f"{s}_balance_sheet_{d}.json",
    ),
    CollectionTask(
        task_type="cashflow",
        tool_name="market_tool.get_cashflow",
        payload_builder=lambda s, d: {"symbol": s, "freq": "quarterly"},
        output_filename=lambda s, d: f"{s}_cashflow_{d}.json",
    ),
    CollectionTask(
        task_type="income_statement",
        tool_name="market_tool.get_income_statement",
        payload_builder=lambda s, d: {"symbol": s, "freq": "quarterly"},
        output_filename=lambda s, d: f"{s}_income_{d}.json",
    ),
    CollectionTask(
        task_type="insider_transactions",
        tool_name="market_tool.get_insider_transactions",
        payload_builder=lambda s, d: {"symbol": s},
        output_filename=lambda s, d: f"{s}_insider_{d}.json",
    ),
    CollectionTask(
        task_type="news",
        tool_name="market_tool.get_news",
        payload_builder=lambda s, d: {
            "symbol": s,
            "limit": 50,
            "start_date": _days_ago(d, 30),
            "end_date": d,
        },
        output_filename=lambda s, d: f"{s}_news_{d}.json",
    ),
    CollectionTask(
        task_type="indicators",
        tool_name="analyst_tool.get_indicators",
        payload_builder=lambda s, d: {
            "symbol": s,
            "indicator": "close_50_sma",
            "as_of_date": d,
            "look_back_days": 30,
        },
        output_filename=lambda s, d: f"{s}_indicators_{d}.json",
    ),
]

GLOBAL_NEWS_TASK = CollectionTask(
    task_type="global_news",
    tool_name="market_tool.get_global_news",
    payload_builder=lambda _s, d: {
        "as_of_date": d,
        "look_back_days": 7,
        "limit": 50,
    },
    output_filename=lambda _s, d: f"global_news_{d}.json",
)


def get_task_by_type(task_type: str) -> CollectionTask | None:
    """Return the CollectionTask for a given task_type, or None if not found."""
    # Linear scan is fine here because task registry is intentionally small.
    for task in COLLECTION_TASKS:
        if task.task_type == task_type:
            return task
    if task_type == "global_news":
        return GLOBAL_NEWS_TASK
    return None


def get_enabled_tasks() -> list[CollectionTask]:
    """Return all enabled collection tasks."""
    return [t for t in COLLECTION_TASKS if t.enabled]


def get_active_tool_names() -> set[str]:
    """Return MCP tool names currently allowed for DataCollector task execution."""
    names = {task.tool_name for task in COLLECTION_TASKS}
    names.add(GLOBAL_NEWS_TASK.tool_name)
    return names
