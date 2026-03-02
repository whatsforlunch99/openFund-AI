"""DataCollector: fetch data from MCP tools and save to local files.

Uses market_tool and analyst_tool to collect fund/stock data, then saves
each response as a JSON file with metadata.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mcp.tools import market_tool, analyst_tool
from data_manager.tasks import (
    CollectionTask,
    COLLECTION_TASKS,
    GLOBAL_NEWS_TASK,
    get_task_by_type,
    get_enabled_tasks,
)

logger = logging.getLogger(__name__)


@dataclass
class CollectionResult:
    """Result of collecting data for a single symbol."""

    symbol: str
    as_of_date: str
    success: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of batch collecting data for multiple symbols."""

    as_of_date: str
    results: dict[str, CollectionResult] = field(default_factory=dict)
    total_success: int = 0
    total_failed: int = 0


class DataCollector:
    """Collect data from MCP tools and save to local files."""

    def __init__(self, data_dir: str = "datasets/raw"):
        """
        Initialize DataCollector.

        Args:
            data_dir: Root directory for raw data files.
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def _get_symbol_dir(self, symbol: str) -> str:
        """Return the directory path for a symbol's data files."""
        symbol_dir = os.path.join(self.data_dir, symbol.upper())
        os.makedirs(symbol_dir, exist_ok=True)
        return symbol_dir

    def _call_tool(self, tool_name: str, payload: dict) -> dict:
        """
        Call an MCP tool function by name.

        Args:
            tool_name: Full tool name (e.g. "market_tool.get_stock_data")
            payload: Arguments to pass to the tool function.

        Returns:
            Tool response dict (contains "content" or "error").
        """
        module_name, func_name = tool_name.split(".", 1)

        if module_name == "market_tool":
            return self._call_market_tool(func_name, payload)
        elif module_name == "analyst_tool":
            return self._call_analyst_tool(func_name, payload)
        else:
            return {"error": f"Unknown tool module: {module_name}"}

    def _call_market_tool(self, func_name: str, payload: dict) -> dict:
        """Call a market_tool function."""
        func_map = {
            "get_stock_data": lambda p: market_tool._route_stock_data(
                p["symbol"], p["start_date"], p["end_date"]
            ),
            "get_fundamentals": lambda p: market_tool._route_fundamentals(p["symbol"]),
            "get_balance_sheet": lambda p: market_tool._route_balance_sheet(
                p["symbol"], p.get("freq", "quarterly")
            ),
            "get_cashflow": lambda p: market_tool._route_cashflow(
                p["symbol"], p.get("freq", "quarterly")
            ),
            "get_income_statement": lambda p: market_tool._route_income_statement(
                p["symbol"], p.get("freq", "quarterly")
            ),
            "get_insider_transactions": lambda p: market_tool._route_insider_transactions(
                p["symbol"]
            ),
            "get_news": lambda p: market_tool._route_news(
                p["symbol"],
                p.get("limit", 20),
                p.get("start_date"),
                p.get("end_date"),
            ),
            "get_global_news": lambda p: market_tool._route_global_news(
                p["as_of_date"],
                p.get("look_back_days", 7),
                p.get("limit", 50),
            ),
            "get_ticker_info": lambda p: market_tool.get_ticker_info(p["symbol"]),
        }

        if func_name not in func_map:
            return {"error": f"Unknown market_tool function: {func_name}"}

        try:
            return func_map[func_name](payload)
        except Exception as e:
            logger.exception("market_tool.%s failed", func_name)
            return {"error": str(e)}

    def _call_analyst_tool(self, func_name: str, payload: dict) -> dict:
        """Call an analyst_tool function."""
        func_map = {
            "get_indicators": lambda p: analyst_tool._route_indicators(
                p["symbol"],
                p["indicator"],
                p["as_of_date"],
                p.get("look_back_days", 30),
            ),
        }

        if func_name not in func_map:
            return {"error": f"Unknown analyst_tool function: {func_name}"}

        try:
            return func_map[func_name](payload)
        except Exception as e:
            logger.exception("analyst_tool.%s failed", func_name)
            return {"error": str(e)}

    def _save_to_file(
        self,
        symbol: str,
        task_type: str,
        source: str,
        as_of_date: str,
        content: Any,
        filename: str,
    ) -> str:
        """
        Save collected data to a JSON file with metadata.

        Args:
            symbol: Stock/fund symbol.
            task_type: Type of data collected.
            source: MCP tool that provided the data.
            as_of_date: Reference date.
            content: Raw content from tool response.
            filename: Output filename.

        Returns:
            Full path to the saved file.
        """
        if task_type == "global_news":
            symbol_dir = os.path.join(self.data_dir, "global")
        else:
            symbol_dir = self._get_symbol_dir(symbol)

        os.makedirs(symbol_dir, exist_ok=True)
        filepath = os.path.join(symbol_dir, filename)

        data = {
            "metadata": {
                "symbol": symbol,
                "task_type": task_type,
                "collected_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": source,
                "as_of_date": as_of_date,
            },
            "content": content,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info("Saved %s to %s", task_type, filepath)
        return filepath

    def collect_task(
        self, symbol: str, task: CollectionTask, as_of_date: str
    ) -> tuple[bool, str | None, str | None]:
        """
        Execute a single collection task for a symbol.

        Args:
            symbol: Stock/fund symbol.
            task: CollectionTask to execute.
            as_of_date: Reference date.

        Returns:
            Tuple of (success, filepath, error_message).
        """
        payload = task.payload_builder(symbol, as_of_date)
        logger.debug(
            "Collecting %s for %s: %s(%s)",
            task.task_type,
            symbol,
            task.tool_name,
            payload,
        )

        response = self._call_tool(task.tool_name, payload)

        if "error" in response:
            logger.warning(
                "Failed to collect %s for %s: %s",
                task.task_type,
                symbol,
                response["error"],
            )
            return False, None, response["error"]

        content = response.get("content", "")
        filename = task.output_filename(symbol, as_of_date)

        filepath = self._save_to_file(
            symbol=symbol,
            task_type=task.task_type,
            source=task.tool_name,
            as_of_date=as_of_date,
            content=content,
            filename=filename,
        )

        return True, filepath, None

    def collect_symbol(
        self,
        symbol: str,
        as_of_date: str,
        task_types: list[str] | None = None,
    ) -> CollectionResult:
        """
        Collect all data for a single symbol.

        Args:
            symbol: Stock/fund symbol (e.g. "NVDA", "AAPL").
            as_of_date: Reference date (yyyy-mm-dd).
            task_types: Optional list of specific task types to collect.
                       If None, collects all enabled tasks.

        Returns:
            CollectionResult with success/failed lists and file paths.
        """
        symbol = symbol.strip().upper()
        result = CollectionResult(symbol=symbol, as_of_date=as_of_date)

        if task_types:
            tasks = [get_task_by_type(t) for t in task_types]
            tasks = [t for t in tasks if t is not None]
        else:
            tasks = get_enabled_tasks()

        for task in tasks:
            success, filepath, error = self.collect_task(symbol, task, as_of_date)

            if success:
                result.success.append(task.task_type)
                if filepath:
                    result.files.append(filepath)
            else:
                result.failed.append(task.task_type)
                if error:
                    result.errors[task.task_type] = error

        logger.info(
            "Collected %s for %s: %d success, %d failed",
            as_of_date,
            symbol,
            len(result.success),
            len(result.failed),
        )

        return result

    def collect_batch(
        self,
        symbols: list[str],
        as_of_date: str,
        task_types: list[str] | None = None,
    ) -> BatchResult:
        """
        Batch collect data for multiple symbols.

        Args:
            symbols: List of stock/fund symbols.
            as_of_date: Reference date (yyyy-mm-dd).
            task_types: Optional list of specific task types to collect.

        Returns:
            BatchResult with per-symbol results and totals.
        """
        batch = BatchResult(as_of_date=as_of_date)

        for symbol in symbols:
            result = self.collect_symbol(symbol, as_of_date, task_types)
            batch.results[symbol] = result
            batch.total_success += len(result.success)
            batch.total_failed += len(result.failed)

        logger.info(
            "Batch collection complete: %d symbols, %d success, %d failed",
            len(symbols),
            batch.total_success,
            batch.total_failed,
        )

        return batch

    def collect_global_news(self, as_of_date: str) -> CollectionResult:
        """
        Collect global market news (not symbol-specific).

        Args:
            as_of_date: Reference date (yyyy-mm-dd).

        Returns:
            CollectionResult for global news.
        """
        result = CollectionResult(symbol="global", as_of_date=as_of_date)
        task = GLOBAL_NEWS_TASK

        success, filepath, error = self.collect_task("global", task, as_of_date)

        if success:
            result.success.append(task.task_type)
            if filepath:
                result.files.append(filepath)
        else:
            result.failed.append(task.task_type)
            if error:
                result.errors[task.task_type] = error

        return result

    def list_collected_files(self, symbol: str | None = None) -> list[dict]:
        """
        List all collected data files.

        Args:
            symbol: Optional symbol to filter by. If None, lists all.

        Returns:
            List of dicts with file info (path, symbol, task_type, collected_at).
        """
        files = []

        if symbol:
            search_dirs = [self._get_symbol_dir(symbol)]
        else:
            search_dirs = []
            for entry in os.listdir(self.data_dir):
                entry_path = os.path.join(self.data_dir, entry)
                if os.path.isdir(entry_path):
                    search_dirs.append(entry_path)

        for dir_path in search_dirs:
            if not os.path.exists(dir_path):
                continue
            for filename in os.listdir(dir_path):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(dir_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    metadata = data.get("metadata", {})
                    files.append(
                        {
                            "path": filepath,
                            "filename": filename,
                            "symbol": metadata.get("symbol"),
                            "task_type": metadata.get("task_type"),
                            "collected_at": metadata.get("collected_at"),
                            "as_of_date": metadata.get("as_of_date"),
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to read %s: %s", filepath, e)

        return sorted(files, key=lambda x: x.get("collected_at", ""), reverse=True)
