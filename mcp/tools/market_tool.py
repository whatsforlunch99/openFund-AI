"""Market and web search via Tavily + Yahoo APIs (MCP tool).

Also provides company fundamentals, financials, insider transactions, and news (yfinance).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import yfinance as yf
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _symbol_info(symbol: str) -> dict:
    """Return yfinance info dict for the given stock/fund symbol; empty if missing."""
    try:
        obj = yf.Ticker(symbol.upper())
        info = obj.info
        return info if info else {}
    except Exception as e:
        logger.debug("yfinance info unavailable for %s: %s", symbol, e)
        return {}


def _extract_article(article: dict) -> dict:
    """Extract title, summary, publisher, link, pub_date from yfinance article (nested or flat)."""
    if "content" in article:
        c = article["content"]
        title = c.get("title", "No title")
        summary = c.get("summary", "")
        provider = c.get("provider", {})
        publisher = provider.get("displayName", "Unknown")
        url_obj = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
        link = (
            url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj or "")
        )
        pub_date_str = c.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    return {
        "title": article.get("title", "No title"),
        "summary": article.get("summary", ""),
        "publisher": article.get("publisher", "Unknown"),
        "link": article.get("link", ""),
        "pub_date": None,
    }


# --- Stubs (Tavily / Yahoo) ---


def fetch(fund_or_symbol: str) -> dict:
    """
    Fetch market data for a fund or symbol (Yahoo and/or Tavily).

    Args:
        fund_or_symbol: Fund or ticker symbol.

    Returns:
        Market data dict; must include 'timestamp'. Config: TAVILY_API_KEY, YAHOO_BASE_URL.
    """
    raise NotImplementedError


def fetch_bulk(symbols: list[str]) -> dict:
    """
    Fetch market data for multiple symbols.

    Args:
        symbols: List of symbols.

    Returns:
        Dict keyed by symbol; each value must include 'timestamp'.
    """
    raise NotImplementedError


def search_web(query: str) -> list[dict]:
    """
    Web search via Tavily (e.g. regulatory, sentiment).

    Args:
        query: Search query.

    Returns:
        List of results; each must include 'timestamp'.
    """
    raise NotImplementedError


def get_stock_data(symbol: str, start_date: str, end_date: str) -> dict:
    """
    Historical OHLCV for a symbol (yfinance).

    Args:
        symbol: Stock or fund symbol (e.g. AAPL).
        start_date: Start date yyyy-mm-dd.
        end_date: End date yyyy-mm-dd.

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        if not start_date:
            return {"error": "Missing required 'start_date'"}
        if not end_date:
            return {"error": "Missing required 'end_date'"}

        ticker_obj = yf.Ticker(symbol)
        data = ticker_obj.history(start=start_date, end=end_date)

        if data.empty:
            return {
                "content": f"No data found for {symbol} between {start_date} and {end_date}",
                "timestamp": _now_iso(),
            }

        if data.index.tz is not None:
            data = data.tz_localize(None)
        for col in ["Open", "High", "Low", "Close", "Adj Close"]:
            if col in data.columns:
                data[col] = data[col].round(2)

        csv_string = data.to_csv()
        header = f"# Stock data for {symbol} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(data)}\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return {"content": header + csv_string, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_stock_data failed")
        return {"error": str(e)}


# --- Fundamentals (yfinance) ---


def get_fundamentals(symbol: str) -> dict:
    """
    Company fundamentals overview (sector, PE, margins, etc.).

    Args:
        symbol: Stock or fund symbol (e.g. AAPL).

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        info = _symbol_info(symbol)
        if not info:
            return {
                "content": f"No fundamentals data found for symbol '{symbol}'",
                "timestamp": _now_iso(),
            }

        fields = [
            ("Name", info.get("longName")),
            ("Sector", info.get("sector")),
            ("Industry", info.get("industry")),
            ("Market Cap", info.get("marketCap")),
            ("PE Ratio (TTM)", info.get("trailingPE")),
            ("Forward PE", info.get("forwardPE")),
            ("PEG Ratio", info.get("pegRatio")),
            ("Price to Book", info.get("priceToBook")),
            ("EPS (TTM)", info.get("trailingEps")),
            ("Forward EPS", info.get("forwardEps")),
            ("Dividend Yield", info.get("dividendYield")),
            ("Beta", info.get("beta")),
            ("52 Week High", info.get("fiftyTwoWeekHigh")),
            ("52 Week Low", info.get("fiftyTwoWeekLow")),
            ("50 Day Average", info.get("fiftyDayAverage")),
            ("200 Day Average", info.get("twoHundredDayAverage")),
            ("Revenue (TTM)", info.get("totalRevenue")),
            ("Gross Profit", info.get("grossProfits")),
            ("EBITDA", info.get("ebitda")),
            ("Net Income", info.get("netIncomeToCommon")),
            ("Profit Margin", info.get("profitMargins")),
            ("Operating Margin", info.get("operatingMargins")),
            ("Return on Equity", info.get("returnOnEquity")),
            ("Return on Assets", info.get("returnOnAssets")),
            ("Debt to Equity", info.get("debtToEquity")),
            ("Current Ratio", info.get("currentRatio")),
            ("Book Value", info.get("bookValue")),
            ("Free Cash Flow", info.get("freeCashflow")),
        ]
        lines = [f"{label}: {value}" for label, value in fields if value is not None]
        header = f"# Company Fundamentals for {symbol}\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content = (
            header + "\n".join(lines) if lines else header + "No fields available."
        )
        return {"content": content, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_fundamentals failed")
        return {"error": str(e)}


def get_balance_sheet(symbol: str, freq: str = "quarterly") -> dict:
    """
    Balance sheet (annual or quarterly).

    Args:
        symbol: Stock or fund symbol.
        freq: "annual" or "quarterly".

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        freq = (freq or "quarterly").lower()
        obj = yf.Ticker(symbol)
        data = obj.quarterly_balance_sheet if freq == "quarterly" else obj.balance_sheet
        if data is None or data.empty:
            return {
                "content": f"No balance sheet data found for symbol '{symbol}'",
                "timestamp": _now_iso(),
            }
        csv_string = data.to_csv()
        header = f"# Balance Sheet data for {symbol} ({freq})\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return {"content": header + csv_string, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_balance_sheet failed")
        return {"error": str(e)}


def get_cashflow(symbol: str, freq: str = "quarterly") -> dict:
    """
    Cash flow statement (annual or quarterly).

    Args:
        symbol: Stock or fund symbol.
        freq: "annual" or "quarterly".

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        freq = (freq or "quarterly").lower()
        obj = yf.Ticker(symbol)
        data = obj.quarterly_cashflow if freq == "quarterly" else obj.cashflow
        if data is None or data.empty:
            return {
                "content": f"No cash flow data found for symbol '{symbol}'",
                "timestamp": _now_iso(),
            }
        csv_string = data.to_csv()
        header = f"# Cash Flow data for {symbol} ({freq})\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return {"content": header + csv_string, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_cashflow failed")
        return {"error": str(e)}


def get_income_statement(symbol: str, freq: str = "quarterly") -> dict:
    """
    Income statement (annual or quarterly).

    Args:
        symbol: Stock or fund symbol.
        freq: "annual" or "quarterly".

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        freq = (freq or "quarterly").lower()
        obj = yf.Ticker(symbol)
        data = obj.quarterly_income_stmt if freq == "quarterly" else obj.income_stmt
        if data is None or data.empty:
            return {
                "content": f"No income statement data found for symbol '{symbol}'",
                "timestamp": _now_iso(),
            }
        csv_string = data.to_csv()
        header = f"# Income Statement data for {symbol} ({freq})\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return {"content": header + csv_string, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_income_statement failed")
        return {"error": str(e)}


def get_insider_transactions(symbol: str) -> dict:
    """
    Insider transactions for a stock or fund.

    Args:
        symbol: Stock or fund symbol.

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        obj = yf.Ticker(symbol)
        data = getattr(obj, "insider_transactions", None)
        if data is None or (hasattr(data, "empty") and data.empty):
            return {
                "content": f"No insider transactions data found for symbol '{symbol}'",
                "timestamp": _now_iso(),
            }
        csv_string = data.to_csv()
        header = f"# Insider Transactions data for {symbol}\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return {"content": header + csv_string, "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_insider_transactions failed")
        return {"error": str(e)}


# --- News (yfinance) ---


def get_news(
    symbol: str,
    limit: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    News for a stock or fund, optionally filtered by date range.

    Args:
        symbol: Stock or fund symbol.
        limit: Maximum number of articles to return.
        start_date: Optional filter start (yyyy-mm-dd).
        end_date: Optional filter end (yyyy-mm-dd).

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"error": "Missing required 'symbol'"}
        if limit is None:
            return {"error": "Missing required 'limit'"}
        limit = int(limit)

        stock = yf.Ticker(symbol)
        news = stock.get_news(count=limit)

        if not news:
            return {"content": f"No news found for {symbol}", "timestamp": _now_iso()}

        start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None

        lines = []
        for art in news:
            data = _extract_article(art)
            if start_dt and end_dt and data["pub_date"]:
                pub = data["pub_date"]
                try:
                    pub_date_only = pub.date()
                except AttributeError:
                    continue
                if not (start_dt.date() <= pub_date_only <= end_dt.date()):
                    continue
            lines.append(f"### {data['title']} (source: {data['publisher']})")
            if data["summary"]:
                lines.append(data["summary"])
            if data["link"]:
                lines.append(f"Link: {data['link']}")
            lines.append("")

        if not lines:
            range_str = (
                f" between {start_date} and {end_date}"
                if start_date and end_date
                else ""
            )
            return {
                "content": f"No news found for {symbol}{range_str}",
                "timestamp": _now_iso(),
            }

        range_str = (
            f", from {start_date} to {end_date}" if start_date and end_date else ""
        )
        content = f"## {symbol} News{range_str}:\n\n" + "\n".join(lines)
        return {"content": content.strip(), "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_news failed")
        return {"error": str(e)}


def get_global_news(as_of_date: str, look_back_days: int, limit: int) -> dict:
    """
    Global/macro market news (yfinance Search).

    Args:
        as_of_date: Reference date for the range, yyyy-mm-dd.
        look_back_days: Number of days to look back from as_of_date.
        limit: Maximum number of articles to return.

    Returns:
        {"content": str, "timestamp": str} or {"error": str}.
    """
    try:
        as_of_date = (as_of_date or "").strip()
        if not as_of_date:
            return {"error": "Missing required 'as_of_date'"}
        if look_back_days is None:
            return {"error": "Missing required 'look_back_days'"}
        look_back_days = int(look_back_days)
        if limit is None:
            return {"error": "Missing required 'limit'"}
        limit = int(limit)

        queries = [
            "stock market economy",
            "Federal Reserve interest rates",
            "inflation economic outlook",
            "global markets trading",
        ]
        all_news = []
        seen = set()

        for query in queries:
            try:
                search = yf.Search(
                    query=query, news_count=limit, enable_fuzzy_query=True
                )
                if not getattr(search, "news", None):
                    continue
                for article in search.news:
                    if "content" in article:
                        title = article["content"].get("title", "")
                    else:
                        title = article.get("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        all_news.append(article)
            except Exception as e:
                logger.debug("get_global_news query %r failed: %s", query, e)
                continue
            if len(all_news) >= limit:
                break

        if not all_news:
            return {
                "content": f"No global news found for {as_of_date}",
                "timestamp": _now_iso(),
            }

        as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        start_dt = as_of_dt - relativedelta(days=look_back_days)
        start_str = start_dt.strftime("%Y-%m-%d")

        lines = []
        for article in all_news[:limit]:
            data = _extract_article(article)
            lines.append(f"### {data['title']} (source: {data['publisher']})")
            if data["summary"]:
                lines.append(data["summary"])
            if data["link"]:
                lines.append(f"Link: {data['link']}")
            lines.append("")

        content = (
            f"## Global Market News, from {start_str} to {as_of_date}:\n\n"
            + "\n".join(lines)
        )
        return {"content": content.strip(), "timestamp": _now_iso()}
    except Exception as e:
        logger.exception("get_global_news failed")
        return {"error": str(e)}
