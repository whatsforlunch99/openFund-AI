"""DataCollector: fetch data from MCP tools and save to local files.

Uses market_tool and analyst_tool to collect fund/stock data, then saves
each response as a JSON file with metadata.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import urlopen, Request

from openfund_mcp.mcp_client import MCPClient
from data_manager.empty_markers import NOT_EXIST, to_cell
from data_manager.tasks import (
    CollectionTask,
    GLOBAL_NEWS_TASK,
    get_task_by_type,
    get_enabled_tasks,
    get_active_tool_names,
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

    def __init__(self, data_dir: str = "datasets/raw", mcp_client: MCPClient | None = None):
        """
        Initialize DataCollector.

        Args:
            data_dir: Root directory for raw data files.
            mcp_client: Optional MCP client; when omitted, uses default local MCP server registry.
        """
        self.data_dir = data_dir
        # Snapshot allowed tool names from task registry to enforce API consistency.
        self._active_tool_names = get_active_tool_names()
        if mcp_client is None:
            from config.config import load_config

            cfg = load_config()
            mcp_client = MCPClient(
                command=cfg.mcp_server_command,
                args=tuple(cfg.mcp_server_args),
                cwd=cfg.mcp_server_cwd or None,
            )
        self.mcp_client = mcp_client
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
        # Guardrail: only allow tools explicitly referenced by collection tasks.
        if tool_name not in self._active_tool_names:
            return {
                "error": (
                    f"Tool '{tool_name}' is not an active DataCollector API. "
                    "Use one of the task-defined MCP tools."
                )
            }
        try:
            return self.mcp_client.call_tool(tool_name, payload)
        except Exception as e:
            # Bubble up tool/runtime errors as structured collector failure.
            logger.exception("MCP call failed for %s", tool_name)
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
        if task_type.startswith("cn_"):
            # CN ingestion: datasets/raw/ingestion/{dataset}/{as_of_date}/{fund_id}/
            # For cn_fund_all: data.json, data.csv, reports/*.pdf in fund_id/
            symbol_dir = os.path.join(self.data_dir, "ingestion", task_type, as_of_date)
            if task_type == "cn_fund_all":
                symbol_dir = os.path.join(symbol_dir, symbol)
            os.makedirs(symbol_dir, exist_ok=True)
            base_name = "data.json" if task_type == "cn_fund_all" else f"{symbol}.json"
            filepath = os.path.join(symbol_dir, base_name)
        elif task_type == "global_news":
            symbol_dir = os.path.join(self.data_dir, "global")
        else:
            symbol_dir = self._get_symbol_dir(symbol)

        if not task_type.startswith("cn_"):
            os.makedirs(symbol_dir, exist_ok=True)
            filepath = os.path.join(symbol_dir, filename)

        # Persist metadata + raw content so downstream distribution can route correctly.
        data = {
            "metadata": {
                "symbol": symbol,
                "task_type": task_type,
                "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": source,
                "as_of_date": as_of_date,
            },
            "content": content,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info("Saved %s to %s", task_type, filepath)
        return filepath

    def _save_cn_fund_all_csv(
        self,
        content: dict,
        symbol: str,
        as_of_date: str,
        collected_at: str,
        dir_path: str,
    ) -> None:
        """
        Write cn_fund_all content to a single CSV file named {fund_id}.csv.

        All sections (basic, nav, fee, holdings, rank) are concatenated with
        clear section headers for readability.
        """
        if not isinstance(content, dict):
            return

        fund_id = str(symbol).strip()
        filepath = os.path.join(dir_path, "data.csv")

        def _row_to_str(val: Any) -> str:
            return to_cell(val, default_marker=NOT_EXIST)

        def _normalize_fee_to_long_format(items: list[dict]) -> list[dict]:
            """Convert raw fee items to long table: fund_id, fee_type, condition, fee_value, fee_unit.
            Reduces empty cells per fund-table-adjustment design."""
            out: list[dict] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                ind = str(it.get("_fee_indicator") or "").strip()
                base = {"fund_id": fund_id, "as_of_date": as_of_date, "collected_at": collected_at}

                if "申购" in ind or "认购" in ind:
                    # 原费率 + 适用金额
                    fee_val = it.get("原费率") or it.get("费率") or ""
                    cond = it.get("适用金额") or it.get("适用期限") or "---"
                    if fee_val:
                        unit = "元" if "元" in str(fee_val) else "%"
                        raw_text = json.dumps(it, ensure_ascii=False)[:500] if it else ""
                        out.append({**base, "fee_type": "buy", "condition": _row_to_str(cond), "fee_value": _row_to_str(fee_val), "fee_unit": unit, "raw_text": _row_to_str(raw_text)})

                elif "赎回" in ind:
                    fee_val = it.get("赎回费率") or it.get("费率") or ""
                    cond = it.get("适用期限") or "---"
                    if fee_val:
                        unit = "元" if "元" in str(fee_val) else "%"
                        raw_text = json.dumps(it, ensure_ascii=False)[:500] if it else ""
                        out.append({**base, "fee_type": "redeem", "condition": _row_to_str(cond), "fee_value": _row_to_str(fee_val), "fee_unit": unit, "raw_text": _row_to_str(raw_text)})

                elif "运作" in ind or ind == "运作费用":
                    # columns 0,1,2,3,4,5 = key,value,key,value,key,value (AKShare pivot style)
                    kv_pairs: list[tuple[str, str]] = []
                    for i in range(0, 6, 2):
                        k = it.get(str(i)) or it.get(i)
                        v = it.get(str(i + 1)) or it.get(i + 1)
                        if k is not None and v is not None and str(k).strip() and str(v).strip():
                            kv_pairs.append((str(k).strip(), str(v).strip()))
                    type_map = {"管理费率": "manage", "托管费率": "custody", "销售服务费率": "sales_service"}
                    for k, v in kv_pairs:
                        ft = type_map.get(k, k)
                        if ft and v:
                            unit = "元" if "元" in v else "%"
                            raw_text = json.dumps(it, ensure_ascii=False)[:500] if it else ""
                            out.append({**base, "fee_type": ft, "condition": "", "fee_value": _row_to_str(v), "fee_unit": unit, "raw_text": _row_to_str(raw_text)})
            return out

        def _normalize_holdings_to_dense(items: list[dict]) -> list[dict]:
            """Normalize holdings to consistent columns per fund-table-adjustment."""
            out: list[dict] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                code = it.get("股票代码") or it.get("代码") or ""
                name = it.get("股票名称") or it.get("名称") or ""
                weight = it.get("占净值比例")
                period = it.get("季度") or ""
                mkt_val = it.get("持仓市值")
                share_cnt = it.get("持股数")
                rank = it.get("序号")
                industry = it.get("行业") or it.get("行业类别") or it.get("所属行业")
                row = {
                    "fund_id": fund_id, "as_of_date": as_of_date, "collected_at": collected_at,
                    "report_period": _row_to_str(period), "holding_code": _row_to_str(code),
                    "holding_name": _row_to_str(name), "weight": _row_to_str(weight) if weight is not None else "",
                    "industry": _row_to_str(industry) if industry is not None else "",
                    "market_value": _row_to_str(mkt_val) if mkt_val is not None else "",
                    "share_count": _row_to_str(share_cnt) if share_cnt is not None else "",
                    "rank": _row_to_str(rank) if rank is not None else "",
                }
                if code or name or (weight is not None):
                    out.append(row)
            return out

        def _write_section(
            f: Any,
            title: str,
            title_cn: str,
            fieldnames: list[str],
            rows: list[dict],
        ) -> None:
            if not rows:
                return
            f.write(f"\n# {'=' * 60}\n")
            f.write(f"# {title_cn} ({title})\n")
            f.write(f"# {'=' * 60}\n")
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow({k: _row_to_str(v) for k, v in r.items()})

        sections_written = 0
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            f.write(f"# 基金代码: {fund_id} | 参考日期: {as_of_date} | 采集时间: {collected_at}\n")

            # basic (aligned with fund_basic per fund-table-adjustment)
            basic = content.get("basic")
            if isinstance(basic, dict) and not basic.get("error"):
                ft = str(basic.get("fund_type") or "")
                is_etf_val = (len(fund_id) >= 2 and fund_id[:2] in ("51", "56", "58", "15")) or "ETF" in ft
                is_qdii_val = "QDII" in ft
                cols = [
                    "fund_id", "fund_name", "fund_type", "risk_level", "inception_date",
                    "fund_manager", "management_company", "tracking_index", "investment_scope",
                    "latest_scale", "currency", "is_etf", "is_qdii",
                    "description", "source", "api", "as_of_date", "collected_at",
                ]
                row = {c: basic.get(c, "") for c in cols}
                row["fund_id"] = fund_id
                row["as_of_date"] = as_of_date
                row["collected_at"] = collected_at
                row["currency"] = row.get("currency") or "CNY"
                row["is_etf"] = "true" if is_etf_val else "false"
                row["is_qdii"] = "true" if is_qdii_val else "false"
                _write_section(f, "BASIC", "基础信息", cols, [row])
                sections_written += 1

            # nav
            nav = content.get("nav")
            if isinstance(nav, dict) and not nav.get("error"):
                items = nav.get("items") or []
                fmt = str(nav.get("items_format") or "rows").strip().lower()
                rows = []
                cols = ["fund_id", "nav_date", "nav", "nav_accumulated", "as_of_date", "collected_at"]
                if fmt == "triples" and isinstance(items, list):
                    for r in items:
                        if isinstance(r, list) and len(r) >= 2:
                            rows.append({
                                "fund_id": fund_id,
                                "nav_date": r[0],
                                "nav": r[1] if len(r) > 1 else None,
                                "nav_accumulated": r[2] if len(r) > 2 else None,
                                "as_of_date": as_of_date,
                                "collected_at": collected_at,
                            })
                elif fmt == "columns" and isinstance(items, dict):
                    dates = items.get("nav_date") or []
                    navs = items.get("nav") or []
                    accs = items.get("nav_accumulated") or []
                    n = min(len(dates), len(navs), len(accs) if isinstance(accs, list) else len(dates))
                    for i in range(n):
                        rows.append({
                            "fund_id": fund_id,
                            "nav_date": dates[i] if i < len(dates) else "",
                            "nav": navs[i] if i < len(navs) else None,
                            "nav_accumulated": accs[i] if i < len(accs) else None,
                            "as_of_date": as_of_date,
                            "collected_at": collected_at,
                        })
                else:
                    for r in items if isinstance(items, list) else []:
                        if isinstance(r, dict):
                            rows.append({
                                "fund_id": fund_id,
                                "nav_date": r.get("nav_date", r.get("净值日期", "")),
                                "nav": r.get("nav", r.get("单位净值", r.get("净值", ""))),
                                "nav_accumulated": r.get("nav_accumulated", r.get("累计净值", "")),
                                "as_of_date": as_of_date,
                                "collected_at": collected_at,
                            })
                if rows:
                    _write_section(f, "NAV", "净值", cols, rows)
                    sections_written += 1

            # fee (long format: fee_type, condition, fee_value, fee_unit to reduce empty cells)
            fee = content.get("fee")
            if isinstance(fee, dict) and not fee.get("error"):
                items = fee.get("items") or []
                if items and isinstance(items, list):
                    rows = _normalize_fee_to_long_format(items)
                    if rows:
                        cols = ["fund_id", "as_of_date", "collected_at", "fee_type", "condition", "fee_value", "fee_unit", "raw_text"]
                        _write_section(f, "FEE", "费率", cols, rows)
                        sections_written += 1

            # holdings (normalized columns to reduce empty cells)
            holdings = content.get("holdings")
            if isinstance(holdings, dict) and not holdings.get("error"):
                items = holdings.get("items") or []
                if items and isinstance(items, list):
                    rows = _normalize_holdings_to_dense(items)
                    if rows:
                        cols = ["fund_id", "as_of_date", "collected_at", "report_period", "holding_code", "holding_name", "weight", "industry", "market_value", "share_count", "rank"]
                        _write_section(f, "HOLDINGS", "持仓", cols, rows)
                        sections_written += 1

            # rank
            rank = content.get("rank")
            if isinstance(rank, dict) and not rank.get("error"):
                items = rank.get("items") or []
                if items and isinstance(items, list):
                    preferred = ["序号", "基金代码", "基金简称", "日期", "单位净值", "累计净值", "日增长率", "近1周", "近1月", "近3月", "近6月", "近1年", "近2年", "近3年", "今年来", "成立来", "手续费"]
                    all_keys = set()
                    for it in items:
                        if isinstance(it, dict):
                            all_keys.update(it.keys())
                    ordered = [k for k in preferred if k in all_keys]
                    ordered += sorted(all_keys - set(preferred) - {"fund_id", "as_of_date", "collected_at"})
                    cols = ["fund_id", "as_of_date", "collected_at"] + ordered
                    rows = []
                    for it in items:
                        if isinstance(it, dict):
                            rows.append({"fund_id": fund_id, "as_of_date": as_of_date, "collected_at": collected_at, **it})
                    if rows:
                        _write_section(f, "RANK", "排名/业绩", cols, rows)
                        sections_written += 1

            # announcements (dividend, report, personnel)
            announcements = content.get("announcements")
            if isinstance(announcements, dict) and not announcements.get("error"):
                ann_preferred = ["基金代码", "公告标题", "基金名称", "公告日期", "报告ID", "代码", "简称", "公告时间", "公告链接"]
                for key, title_cn in [
                    ("dividend", "公告-分红"),
                    ("report", "公告-定期报告"),
                    ("personnel", "公告-人事"),
                    ("disclosure_cninfo", "公告-巨潮资讯"),
                ]:
                    sub = announcements.get(key)
                    if not isinstance(sub, dict) or sub.get("error"):
                        continue
                    items = sub.get("items") or []
                    if not items or not isinstance(items, list):
                        continue
                    all_keys = set()
                    for it in items:
                        if isinstance(it, dict):
                            all_keys.update(it.keys())
                    ordered = [k for k in ann_preferred if k in all_keys]
                    ordered += sorted(all_keys - set(ann_preferred) - {"fund_id", "as_of_date", "collected_at"})
                    cols = ["fund_id", "as_of_date", "collected_at"] + ordered
                    rows = []
                    for it in items:
                        if isinstance(it, dict):
                            rows.append({"fund_id": fund_id, "as_of_date": as_of_date, "collected_at": collected_at, **it})
                    if rows:
                        _write_section(f, f"ANNOUNCEMENTS_{key.upper()}", title_cn, cols, rows)
                        sections_written += 1

        if sections_written > 0:
            logger.debug("Wrote %s with %d section(s)", filepath, sections_written)

    def _download_fund_reports(
        self,
        content: dict,
        fund_id: str,
        dir_path: str,
    ) -> int:
        """Download quarterly/annual reports to dir_path/reports/. Returns count downloaded.

        Uses EM PDF URL: https://pdf.dfcfw.com/pdf/H2_{report_id}_1.pdf
        Only processes items with 季度报告 or 年度报告 in 公告标题.
        Only downloads reports from the last 3 years.
        """
        reports_dir = os.path.join(dir_path, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        downloaded = 0
        cutoff = datetime.now().date() - timedelta(days=3 * 365)

        def _parse_date(val: Any) -> datetime | None:
            if val is None:
                return None
            s = str(val).strip()[:10]
            for fmt in ("%Y-%m-%d", "%Y%m%d"):
                try:
                    dt = datetime.strptime(s, fmt)
                    return dt
                except ValueError:
                    continue
            return None

        def _is_quarterly_or_annual(item: dict) -> bool:
            title = str(item.get("公告标题", "") or "")
            return "季度报告" in title or "年度报告" in title

        def _within_3y(item: dict) -> bool:
            d = _parse_date(item.get("公告日期") or item.get("公告时间"))
            return d is not None and d.date() >= cutoff

        # Collect report items from announcement sections
        announcements = content.get("announcements") or {}
        if not isinstance(announcements, dict):
            return 0

        seen_ids: set[str] = set()
        for key in ("report", "dividend", "disclosure_cninfo"):
            sub = announcements.get(key)
            if not isinstance(sub, dict) or sub.get("error"):
                continue
            items = sub.get("items") or []
            for it in items:
                if not isinstance(it, dict):
                    continue
                if not _is_quarterly_or_annual(it):
                    continue
                if not _within_3y(it):
                    continue
                report_id = str(it.get("报告ID", it.get("报告id", "")) or "").strip()
                # EM format: ANxxxxxxxx
                if report_id and report_id.startswith("AN") and report_id not in seen_ids:
                    seen_ids.add(report_id)
                    url = f"https://pdf.dfcfw.com/pdf/H2_{report_id}_1.pdf"
                    fname = f"{report_id}.pdf"
                    filepath = os.path.join(reports_dir, fname)
                    if os.path.exists(filepath):
                        continue
                    try:
                        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DataCollector/1.0)"})
                        with urlopen(req, timeout=30) as resp:
                            data = resp.read()
                        if len(data) > 100:  # skip tiny error pages
                            with open(filepath, "wb") as f:
                                f.write(data)
                            downloaded += 1
                            logger.debug("Downloaded report %s to %s", report_id, filepath)
                    except Exception as e:
                        logger.debug("Failed to download %s: %s", url, e)

        return downloaded

    def collect_task(
        self,
        symbol: str,
        task: CollectionTask,
        as_of_date: str,
        output_format: str = "json",
        download_reports: bool = True,
    ) -> tuple[bool, str | None, str | None]:
        """
        Execute a single collection task for a symbol.

        Args:
            symbol: Stock/fund symbol.
            task: CollectionTask to execute.
            as_of_date: Reference date.
            output_format: "json", "csv", or "both". CSV only applies to cn_fund_all.

        Returns:
            Tuple of (success, filepath, error_message).
        """
        payload = task.payload_builder(symbol, as_of_date)
        # Step 1: compute payload from task config; Step 2: call tool; Step 3: persist output.
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

        # Some tools return a top-level dict payload (no "content" wrapper), while others
        # follow the {"content": "..."} convention. Persist the full response when the
        # wrapper is absent so offline ingestion snapshots aren't empty.
        content = response.get("content", response)
        filename = task.output_filename(symbol, as_of_date)

        filepath = self._save_to_file(
            symbol=symbol,
            task_type=task.task_type,
            source=task.tool_name,
            as_of_date=as_of_date,
            content=content,
            filename=filename,
        )

        if task.task_type == "cn_fund_all" and isinstance(content, dict):
            dir_path = os.path.dirname(filepath)
            if output_format in ("csv", "both"):
                metadata = {
                    "symbol": symbol,
                    "task_type": task.task_type,
                    "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                collected_at = metadata["collected_at"]
                self._save_cn_fund_all_csv(
                    content=content,
                    symbol=symbol,
                    as_of_date=as_of_date,
                    collected_at=collected_at,
                    dir_path=dir_path,
                )
            # Download quarterly/annual reports to dir_path/reports/ (unless --no-reports)
            if download_reports:
                n = self._download_fund_reports(content, symbol, dir_path)
                if n > 0:
                    logger.info("Downloaded %d report(s) for %s to %s/reports/", n, symbol, dir_path)

        return True, filepath, None

    def collect_symbol(
        self,
        symbol: str,
        as_of_date: str,
        task_types: list[str] | None = None,
        output_format: str = "json",
        download_reports: bool = True,
    ) -> CollectionResult:
        """
        Collect all data for a single symbol.

        Args:
            symbol: Stock/fund symbol (e.g. "NVDA", "AAPL").
            as_of_date: Reference date (yyyy-mm-dd).
            task_types: Optional list of specific task types to collect.
                       If None, collects all enabled tasks.
            output_format: "json", "csv", or "both". CSV only for cn_fund_all.

        Returns:
            CollectionResult with success/failed lists and file paths.
        """
        symbol = symbol.strip().upper()
        result = CollectionResult(symbol=symbol, as_of_date=as_of_date)

        if task_types:
            # User requested explicit subset; validate each requested task_type.
            tasks = []
            for task_type in task_types:
                task = get_task_by_type(task_type)
                if task is None:
                    result.failed.append(task_type)
                    result.errors[task_type] = f"Unknown or unsupported task type: {task_type}"
                    continue
                tasks.append(task)
        else:
            # Default mode: run all enabled tasks from the registry.
            tasks = get_enabled_tasks()

        for task in tasks:
            success, filepath, error = self.collect_task(
                symbol,
                task,
                as_of_date,
                output_format=output_format,
                download_reports=download_reports,
            )

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
        output_format: str = "json",
        download_reports: bool = True,
    ) -> BatchResult:
        """
        Batch collect data for multiple symbols.

        Args:
            symbols: List of stock/fund symbols.
            as_of_date: Reference date (yyyy-mm-dd).
            task_types: Optional list of specific task types to collect.
            output_format: "json", "csv", or "both". CSV only for cn_fund_all.

        Returns:
            BatchResult with per-symbol results and totals.
        """
        batch = BatchResult(as_of_date=as_of_date)

        for symbol in symbols:
            # Execute symbol collections independently so one symbol failure does not block others.
            result = self.collect_symbol(
                symbol,
                as_of_date,
                task_types,
                output_format=output_format,
                download_reports=download_reports,
            )
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

        def _add_json_file(filepath: str, filename: str) -> None:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                metadata = data.get("metadata", {})
                sym = metadata.get("symbol")
                if symbol and sym and str(sym).strip().upper() != str(symbol).strip().upper():
                    return
                files.append(
                    {
                        "path": filepath,
                        "filename": filename,
                        "symbol": sym,
                        "task_type": metadata.get("task_type"),
                        "collected_at": metadata.get("collected_at"),
                        "as_of_date": metadata.get("as_of_date"),
                    }
                )
            except Exception as e:
                logger.warning("Failed to read %s: %s", filepath, e)

        # Scan ingestion/cn_fund_all/{date}/{fund_id}/data.json
        ingestion_cn = os.path.join(self.data_dir, "ingestion", "cn_fund_all")
        if os.path.isdir(ingestion_cn):
            for date_dir in os.listdir(ingestion_cn):
                date_path = os.path.join(ingestion_cn, date_dir)
                if not os.path.isdir(date_path):
                    continue
                for fund_id in os.listdir(date_path):
                    if symbol and str(fund_id).strip().upper() != str(symbol).strip().upper():
                        continue
                    data_json = os.path.join(date_path, fund_id, "data.json")
                    if os.path.isfile(data_json):
                        _add_json_file(data_json, "data.json")

        if symbol:
            search_dirs = [self._get_symbol_dir(symbol)]
        else:
            search_dirs = []
            for entry in os.listdir(self.data_dir):
                entry_path = os.path.join(self.data_dir, entry)
                if os.path.isdir(entry_path) and entry != "ingestion":
                    search_dirs.append(entry_path)

        for dir_path in search_dirs:
            if not os.path.exists(dir_path):
                continue
            for filename in os.listdir(dir_path):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(dir_path, filename)
                _add_json_file(filepath, filename)

        return sorted(files, key=lambda x: x.get("collected_at", ""), reverse=True)
