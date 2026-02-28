"""DataTransformer: convert raw data to formats required by each database.

Transforms collected JSON data into:
- PostgreSQL rows (list of dicts)
- Neo4j nodes and edges
- Milvus documents (with content field for embedding)
"""

from __future__ import annotations

import csv
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from io import StringIO
from typing import Any

logger = logging.getLogger(__name__)


def _parse_csv_content(content: str) -> list[dict]:
    """Parse CSV content (with optional # comment header) to list of dicts."""
    if not content or not content.strip():
        return []

    lines = []
    for line in content.strip().split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)

    if not lines:
        return []

    reader = csv.DictReader(StringIO("\n".join(lines)))
    return list(reader)


def _safe_float(val: Any, default: float | None = None) -> float | None:
    """Safely convert value to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int | None = None) -> int | None:
    """Safely convert value to int."""
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _parse_date(date_str: str) -> str | None:
    """Parse various date formats to YYYY-MM-DD."""
    if not date_str:
        return None

    date_str = str(date_str).strip()

    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"]:
        try:
            return datetime.strptime(date_str[:10], fmt[:8]).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str[:10] if len(date_str) >= 10 else None


class DataTransformer:
    """Transform raw data to formats required by each database."""

    def __init__(self, collected_at: str | None = None):
        """
        Initialize transformer.

        Args:
            collected_at: Default timestamp for collected_at fields.
        """
        self.collected_at = collected_at or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def to_postgres_rows(
        self, task_type: str, symbol: str, content: Any, as_of_date: str
    ) -> tuple[str, list[dict]]:
        """
        Transform raw content to PostgreSQL rows.

        Args:
            task_type: Data type (e.g. "stock_data", "fundamentals").
            symbol: Stock/fund symbol.
            content: Raw content from MCP tool response.
            as_of_date: Reference date.

        Returns:
            Tuple of (table_name, list_of_row_dicts).
        """
        if task_type == "stock_data":
            return self._transform_stock_data(symbol, content)
        elif task_type == "fundamentals":
            return self._transform_fundamentals(symbol, content, as_of_date)
        elif task_type == "info":
            return self._transform_info_to_fundamentals(symbol, content, as_of_date)
        elif task_type in ("balance_sheet", "cashflow", "income_statement"):
            return self._transform_financial_statement(symbol, content, task_type)
        elif task_type == "insider_transactions":
            return self._transform_insider_transactions(symbol, content)
        elif task_type == "indicators":
            return self._transform_indicators(symbol, content)
        elif task_type == "fund_info":
            return self._transform_fund_info(symbol, content)
        elif task_type == "fund_performance":
            return self._transform_fund_performance(symbol, content)
        elif task_type == "fund_risk":
            return self._transform_fund_risk(symbol, content)
        elif task_type == "fund_holdings":
            return self._transform_fund_holdings(symbol, content)
        elif task_type == "fund_sectors":
            return self._transform_fund_sectors(symbol, content)
        elif task_type == "fund_flows":
            return self._transform_fund_flows(symbol, content)
        else:
            logger.warning("Unknown task_type for PostgreSQL: %s", task_type)
            return "", []

    def _transform_stock_data(
        self, symbol: str, content: str
    ) -> tuple[str, list[dict]]:
        """Transform OHLCV CSV to stock_ohlcv rows."""
        rows = _parse_csv_content(content)
        result = []

        for row in rows:
            date_col = row.get("Date") or row.get("date") or row.get("timestamp", "")
            trade_date = _parse_date(date_col)
            if not trade_date:
                continue

            result.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": _safe_float(row.get("Open") or row.get("open")),
                    "high": _safe_float(row.get("High") or row.get("high")),
                    "low": _safe_float(row.get("Low") or row.get("low")),
                    "close": _safe_float(
                        row.get("Close")
                        or row.get("close")
                        or row.get("Adj Close")
                        or row.get("adjusted close")
                    ),
                    "volume": _safe_int(row.get("Volume") or row.get("volume")),
                    "collected_at": self.collected_at,
                }
            )

        return "stock_ohlcv", result

    def _transform_fundamentals(
        self, symbol: str, content: str, as_of_date: str
    ) -> tuple[str, list[dict]]:
        """Transform fundamentals text to company_fundamentals row."""
        data = self._parse_fundamentals_text(content)
        if not data:
            return "company_fundamentals", []

        row = {
            "symbol": symbol,
            "as_of_date": as_of_date,
            "name": data.get("Name"),
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),
            "market_cap": _safe_int(data.get("Market Cap")),
            "pe_ratio": _safe_float(data.get("PE Ratio (TTM)")),
            "forward_pe": _safe_float(data.get("Forward PE")),
            "peg_ratio": _safe_float(data.get("PEG Ratio")),
            "price_to_book": _safe_float(data.get("Price to Book")),
            "eps_ttm": _safe_float(data.get("EPS (TTM)")),
            "dividend_yield": _safe_float(data.get("Dividend Yield")),
            "beta": _safe_float(data.get("Beta")),
            "fifty_two_week_high": _safe_float(data.get("52 Week High")),
            "fifty_two_week_low": _safe_float(data.get("52 Week Low")),
            "collected_at": self.collected_at,
        }

        return "company_fundamentals", [row]

    def _transform_info_to_fundamentals(
        self, symbol: str, content: str, as_of_date: str
    ) -> tuple[str, list[dict]]:
        """Transform ticker info JSON to company_fundamentals row."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "company_fundamentals", []

        if not data or not isinstance(data, dict):
            return "company_fundamentals", []

        row = {
            "symbol": symbol,
            "as_of_date": as_of_date,
            "name": data.get("longName") or data.get("shortName"),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "market_cap": _safe_int(data.get("marketCap")),
            "pe_ratio": _safe_float(data.get("trailingPE")),
            "forward_pe": _safe_float(data.get("forwardPE")),
            "peg_ratio": _safe_float(data.get("pegRatio")),
            "price_to_book": _safe_float(data.get("priceToBook")),
            "eps_ttm": _safe_float(data.get("trailingEps")),
            "dividend_yield": _safe_float(data.get("dividendYield")),
            "beta": _safe_float(data.get("beta")),
            "fifty_two_week_high": _safe_float(data.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _safe_float(data.get("fiftyTwoWeekLow")),
            "collected_at": self.collected_at,
        }

        return "company_fundamentals", [row]

    def _transform_financial_statement(
        self, symbol: str, content: str, statement_type: str
    ) -> tuple[str, list[dict]]:
        """Transform financial statement CSV to financial_statements rows (EAV)."""
        rows = _parse_csv_content(content)
        if not rows:
            return "financial_statements", []

        type_map = {
            "balance_sheet": "balance_sheet",
            "cashflow": "cashflow",
            "income_statement": "income",
        }
        stmt_type = type_map.get(statement_type, statement_type)

        result = []
        for row in rows:
            line_item = row.get("") or row.get("Unnamed: 0") or row.get("item")
            if not line_item:
                continue

            for col, value in row.items():
                if col in ("", "Unnamed: 0", "item"):
                    continue
                if not value or value == "NaN":
                    continue

                report_date = _parse_date(col)
                if not report_date:
                    continue

                result.append(
                    {
                        "symbol": symbol,
                        "statement_type": stmt_type,
                        "report_date": report_date,
                        "fiscal_period": None,
                        "line_item": str(line_item)[:128],
                        "value": _safe_float(value),
                        "collected_at": self.collected_at,
                    }
                )

        return "financial_statements", result

    def _transform_insider_transactions(
        self, symbol: str, content: str
    ) -> tuple[str, list[dict]]:
        """Transform insider transactions CSV to insider_transactions rows."""
        rows = _parse_csv_content(content)
        result = []

        for row in rows:
            result.append(
                {
                    "symbol": symbol,
                    "insider_name": row.get("Name") or row.get("insider"),
                    "relation": row.get("Relation") or row.get("relation"),
                    "transaction_type": row.get("Transaction")
                    or row.get("transaction_type"),
                    "shares": _safe_int(row.get("Shares") or row.get("shares")),
                    "value": _safe_float(row.get("Value") or row.get("value")),
                    "transaction_date": _parse_date(
                        row.get("Start Date") or row.get("date") or ""
                    ),
                    "collected_at": self.collected_at,
                }
            )

        return "insider_transactions", result

    def _transform_indicators(
        self, symbol: str, content: str
    ) -> tuple[str, list[dict]]:
        """Transform indicators text to technical_indicators rows."""
        result = []
        lines = content.strip().split("\n") if content else []

        indicator_name = None
        for line in lines:
            if line.startswith("##"):
                match = re.search(r"##\s*(\w+)", line)
                if match:
                    indicator_name = match.group(1).lower()
                continue

            if ":" in line and indicator_name:
                parts = line.split(":", 1)
                date_str = parts[0].strip()
                value_str = parts[1].strip()

                date = _parse_date(date_str)
                value = _safe_float(value_str)

                if date and value is not None:
                    result.append(
                        {
                            "symbol": symbol,
                            "indicator_name": indicator_name,
                            "indicator_date": date,
                            "value": value,
                            "collected_at": self.collected_at,
                        }
                    )

        return "technical_indicators", result

    def _transform_fund_info(
        self, symbol: str, content: Any
    ) -> tuple[str, list[dict]]:
        """Transform fund info to fund_info row."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "fund_info", []

        if not data or not isinstance(data, dict):
            return "fund_info", []

        as_of_date = data.get("as_of_date", "")
        row = {
            "symbol": symbol,
            "name": data.get("name"),
            "category": data.get("category"),
            "index_tracked": data.get("index") or data.get("index_tracked"),
            "investment_style": data.get("investment_style"),
            "total_assets_billion": _safe_float(data.get("total_assets_billion")),
            "expense_ratio": _safe_float(data.get("expense_ratio")),
            "dividend_yield": _safe_float(data.get("dividend_yield")),
            "holdings_count": _safe_int(data.get("holdings_count")),
            "as_of_date": as_of_date,
            "collected_at": self.collected_at,
        }
        return "fund_info", [row]

    def _transform_fund_performance(
        self, symbol: str, content: Any
    ) -> tuple[str, list[dict]]:
        """Transform fund performance data."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "fund_performance", []

        if not data or not isinstance(data, dict):
            return "fund_performance", []

        perf = data.get("performance", data)
        as_of_date = data.get("as_of_date", "")

        row = {
            "symbol": symbol,
            "as_of_date": as_of_date,
            "ytd_return": _safe_float(perf.get("ytd_2025") or perf.get("ytd_return")),
            "return_1yr": _safe_float(perf.get("return_1yr")),
            "return_3yr": _safe_float(perf.get("return_3yr")),
            "return_5yr": _safe_float(perf.get("return_5yr")),
            "return_10yr": _safe_float(perf.get("return_10yr")),
            "collected_at": self.collected_at,
        }
        return "fund_performance", [row]

    def _transform_fund_risk(
        self, symbol: str, content: Any
    ) -> tuple[str, list[dict]]:
        """Transform fund risk metrics."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "fund_risk_metrics", []

        if not data or not isinstance(data, dict):
            return "fund_risk_metrics", []

        risk = data.get("risk_metrics", data)
        as_of_date = data.get("as_of_date", "")

        row = {
            "symbol": symbol,
            "as_of_date": as_of_date,
            "beta": _safe_float(risk.get("beta")),
            "standard_deviation": _safe_float(risk.get("standard_deviation") or risk.get("volatility_std_dev")),
            "sharpe_ratio": _safe_float(risk.get("sharpe_ratio")),
            "max_drawdown": _safe_float(risk.get("max_drawdown")),
            "collected_at": self.collected_at,
        }
        return "fund_risk_metrics", [row]

    def _transform_fund_holdings(
        self, symbol: str, content: Any
    ) -> tuple[str, list[dict]]:
        """Transform fund holdings data."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "fund_holdings", []

        if not data:
            return "fund_holdings", []

        holdings = data if isinstance(data, list) else data.get("top_10_holdings", [])
        as_of_date = data.get("as_of_date", "") if isinstance(data, dict) else ""

        result = []
        for h in holdings:
            if not isinstance(h, dict):
                continue
            result.append({
                "fund_symbol": symbol,
                "holding_symbol": h.get("symbol", ""),
                "holding_name": h.get("name", ""),
                "weight": _safe_float(h.get("weight")),
                "sector": h.get("sector", ""),
                "as_of_date": as_of_date,
                "collected_at": self.collected_at,
            })
        return "fund_holdings", result

    def _transform_fund_sectors(
        self, symbol: str, content: Any
    ) -> tuple[str, list[dict]]:
        """Transform fund sector allocation data."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "fund_sector_allocation", []

        if not data:
            return "fund_sector_allocation", []

        sectors = data if isinstance(data, dict) else data.get("sector_allocation", {})
        as_of_date = data.get("as_of_date", "") if isinstance(data, dict) and "sector_allocation" in data else ""

        result = []
        for sector, weight in sectors.items():
            if sector in ("as_of_date", "sector_allocation"):
                continue
            result.append({
                "symbol": symbol,
                "sector": sector,
                "weight": _safe_float(weight),
                "as_of_date": as_of_date,
                "collected_at": self.collected_at,
            })
        return "fund_sector_allocation", result

    def _transform_fund_flows(
        self, symbol: str, content: Any
    ) -> tuple[str, list[dict]]:
        """Transform fund flows data."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return "fund_flows", []

        if not data or not isinstance(data, dict):
            return "fund_flows", []

        flows = data.get("fund_flows_2025", data)
        as_of_date = data.get("as_of_date", "")

        row = {
            "symbol": symbol,
            "period": "2025",
            "inflow_billion": _safe_float(flows.get("annual_inflow_billion") or flows.get("inflow_billion")),
            "outflow_billion": _safe_float(flows.get("outflow_billion")),
            "net_flow_billion": _safe_float(flows.get("net_flow_billion")),
            "pct_of_aum": _safe_float(flows.get("pct_of_total_etf_flows") or flows.get("pct_of_aum")),
            "as_of_date": as_of_date,
            "collected_at": self.collected_at,
        }
        return "fund_flows", [row]

    def _parse_fundamentals_text(self, content: str) -> dict[str, str]:
        """Parse fundamentals text (key: value lines) to dict."""
        result = {}
        if not content:
            return result

        for line in content.split("\n"):
            if line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()

        return result

    def to_neo4j_nodes_edges(
        self, task_type: str, symbol: str, content: Any, as_of_date: str
    ) -> tuple[list[dict], list[dict]]:
        """
        Transform raw content to Neo4j nodes and edges.

        Args:
            task_type: Data type.
            symbol: Stock/fund symbol.
            content: Raw content.
            as_of_date: Reference date.

        Returns:
            Tuple of (list_of_nodes, list_of_edges).
        """
        if task_type == "fundamentals":
            return self._fundamentals_to_neo4j(symbol, content)
        elif task_type == "info":
            return self._info_to_neo4j(symbol, content)
        elif task_type == "fund_info":
            return self._fund_info_to_neo4j(symbol, content)
        elif task_type == "fund_holdings":
            return self._fund_holdings_to_neo4j(symbol, content)
        elif task_type == "fund_sectors":
            return self._fund_sectors_to_neo4j(symbol, content)
        else:
            return [], []

    def _fundamentals_to_neo4j(
        self, symbol: str, content: str
    ) -> tuple[list[dict], list[dict]]:
        """Extract sector/industry relationships from fundamentals."""
        data = self._parse_fundamentals_text(content)
        if not data:
            return [], []

        nodes = []
        edges = []

        company_node = {
            "label": "Company",
            "symbol": symbol,
            "name": data.get("Name"),
            "market_cap": _safe_int(data.get("Market Cap")),
            "collected_at": self.collected_at,
        }
        nodes.append(company_node)

        sector = data.get("Sector")
        if sector:
            nodes.append({"label": "Sector", "name": sector})
            edges.append(
                {
                    "type": "IN_SECTOR",
                    "from_label": "Company",
                    "from_key": symbol,
                    "to_label": "Sector",
                    "to_key": sector,
                }
            )

        industry = data.get("Industry")
        if industry:
            nodes.append({"label": "Industry", "name": industry})
            edges.append(
                {
                    "type": "IN_INDUSTRY",
                    "from_label": "Company",
                    "from_key": symbol,
                    "to_label": "Industry",
                    "to_key": industry,
                }
            )

        return nodes, edges

    def _info_to_neo4j(
        self, symbol: str, content: str
    ) -> tuple[list[dict], list[dict]]:
        """Extract company, sector, industry, officers from ticker info."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return [], []

        if not data or not isinstance(data, dict):
            return [], []

        nodes = []
        edges = []

        company_node = {
            "label": "Company",
            "symbol": symbol,
            "name": data.get("longName") or data.get("shortName"),
            "market_cap": _safe_int(data.get("marketCap")),
            "exchange": data.get("exchange"),
            "currency": data.get("currency"),
            "country": data.get("country"),
            "city": data.get("city"),
            "employees": _safe_int(data.get("fullTimeEmployees")),
            "website": data.get("website"),
            "collected_at": self.collected_at,
        }
        nodes.append(company_node)

        sector = data.get("sector")
        if sector:
            nodes.append({"label": "Sector", "name": sector})
            edges.append(
                {
                    "type": "IN_SECTOR",
                    "from_label": "Company",
                    "from_key": symbol,
                    "to_label": "Sector",
                    "to_key": sector,
                }
            )

        industry = data.get("industry")
        if industry:
            nodes.append({"label": "Industry", "name": industry})
            edges.append(
                {
                    "type": "IN_INDUSTRY",
                    "from_label": "Company",
                    "from_key": symbol,
                    "to_label": "Industry",
                    "to_key": industry,
                }
            )

        officers = data.get("companyOfficers", [])
        for officer in officers:
            if not isinstance(officer, dict):
                continue
            name = officer.get("name")
            if not name:
                continue

            nodes.append(
                {
                    "label": "Officer",
                    "name": name,
                    "age": _safe_int(officer.get("age")),
                }
            )
            edges.append(
                {
                    "type": "HAS_OFFICER",
                    "from_label": "Company",
                    "from_key": symbol,
                    "to_label": "Officer",
                    "to_key": name,
                    "properties": {
                        "title": officer.get("title"),
                        "total_pay": _safe_int(officer.get("totalPay")),
                    },
                }
            )

        return nodes, edges

    def _fund_info_to_neo4j(
        self, symbol: str, content: Any
    ) -> tuple[list[dict], list[dict]]:
        """Extract fund node from fund info."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return [], []

        if not data or not isinstance(data, dict):
            return [], []

        nodes = []
        edges = []

        fund_node = {
            "label": "Fund",
            "symbol": symbol,
            "name": data.get("name"),
            "category": data.get("category"),
            "index_tracked": data.get("index") or data.get("index_tracked"),
            "investment_style": data.get("investment_style"),
            "total_assets_billion": _safe_float(data.get("total_assets_billion")),
            "expense_ratio": _safe_float(data.get("expense_ratio")),
            "collected_at": self.collected_at,
        }
        nodes.append(fund_node)

        return nodes, edges

    def _fund_holdings_to_neo4j(
        self, symbol: str, content: Any
    ) -> tuple[list[dict], list[dict]]:
        """Extract fund holdings relationships."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return [], []

        if not data:
            return [], []

        holdings = data if isinstance(data, list) else data.get("top_10_holdings", [])
        as_of_date = data.get("as_of_date", "") if isinstance(data, dict) else ""

        nodes = []
        edges = []

        for h in holdings:
            if not isinstance(h, dict):
                continue
            holding_symbol = h.get("symbol", "")
            if not holding_symbol:
                continue

            nodes.append({
                "label": "Company",
                "symbol": holding_symbol,
                "name": h.get("name"),
            })
            edges.append({
                "type": "HOLDS",
                "from_label": "Fund",
                "from_key": symbol,
                "to_label": "Company",
                "to_key": holding_symbol,
                "properties": {
                    "weight": _safe_float(h.get("weight")),
                    "as_of_date": as_of_date,
                },
            })

        return nodes, edges

    def _fund_sectors_to_neo4j(
        self, symbol: str, content: Any
    ) -> tuple[list[dict], list[dict]]:
        """Extract fund sector allocation relationships."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return [], []

        if not data:
            return [], []

        if isinstance(data, dict) and "sector_allocation" in data:
            sectors = data.get("sector_allocation", {})
        else:
            sectors = data if isinstance(data, dict) else {}

        if not isinstance(sectors, dict):
            return [], []

        nodes = []
        edges = []

        for sector, weight in sectors.items():
            if sector in ("as_of_date", "sector_allocation"):
                continue

            nodes.append({"label": "Sector", "name": sector})
            edges.append({
                "type": "INVESTS_IN_SECTOR",
                "from_label": "Fund",
                "from_key": symbol,
                "to_label": "Sector",
                "to_key": sector,
                "properties": {"weight": _safe_float(weight)},
            })

        return nodes, edges

    def to_milvus_docs(
        self, task_type: str, symbol: str, content: Any, as_of_date: str
    ) -> list[dict]:
        """
        Transform raw content to Milvus documents.

        Args:
            task_type: Data type.
            symbol: Stock/fund symbol.
            content: Raw content.
            as_of_date: Reference date.

        Returns:
            List of document dicts with id, content, symbol, doc_type, etc.
        """
        if task_type == "news":
            return self._news_to_milvus(symbol, content)
        elif task_type == "global_news":
            return self._global_news_to_milvus(content)
        elif task_type == "info":
            return self._info_description_to_milvus(symbol, content)
        else:
            return []

    def _news_to_milvus(self, symbol: str, content: str) -> list[dict]:
        """Extract news articles as Milvus documents."""
        docs = []
        if not content:
            return docs

        sections = re.split(r"###\s+", content)
        for section in sections:
            if not section.strip():
                continue

            lines = section.strip().split("\n")
            if not lines:
                continue

            title_line = lines[0]
            match = re.match(r"(.+?)\s*\(source:\s*(.+?)\)", title_line)
            if match:
                title = match.group(1).strip()
                source = match.group(2).strip()
            else:
                title = title_line.strip()
                source = "unknown"

            summary_lines = []
            for line in lines[1:]:
                if line.startswith("Link:"):
                    continue
                if line.strip():
                    summary_lines.append(line.strip())
            summary = " ".join(summary_lines)

            text_content = f"{title}. {summary}".strip()
            if len(text_content) < 10:
                continue

            docs.append(
                {
                    "id": f"{symbol}-news-{uuid.uuid4().hex[:8]}",
                    "content": text_content[:65000],
                    "symbol": symbol,
                    "doc_type": "news",
                    "source": source[:256],
                    "published_at": "",
                    "collected_at": self.collected_at,
                }
            )

        return docs

    def _global_news_to_milvus(self, content: str) -> list[dict]:
        """Extract global news as Milvus documents."""
        docs = self._news_to_milvus("global", content)
        for doc in docs:
            doc["doc_type"] = "global_news"
        return docs

    def _info_description_to_milvus(self, symbol: str, content: str) -> list[dict]:
        """Extract company description from ticker info as Milvus document."""
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            return []

        if not data or not isinstance(data, dict):
            return []

        description = data.get("longBusinessSummary", "")
        if not description or len(description) < 50:
            return []

        return [
            {
                "id": f"{symbol}-description-{uuid.uuid4().hex[:8]}",
                "content": description[:65000],
                "symbol": symbol,
                "doc_type": "description",
                "source": "company_info",
                "published_at": "",
                "collected_at": self.collected_at,
            }
        ]
