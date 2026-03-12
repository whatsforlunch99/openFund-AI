"""Yahoo Finance: real-time price and fundamentals via query1.finance.yahoo.com.

- get_price: chart API (v8/finance/chart).
- get_fundamental: quoteSummary (v10/finance/quoteSummary). Yahoo requires a valid
  session cookie + crumb; we obtain both by loading the quote page first and
  extracting the crumb from the page. If quoteSummary still returns 401 (e.g. region
  block), we fall back to chart for price only.
"""

from __future__ import annotations

import logging
import re
import time
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

def _env_base_urls() -> list[str]:
    v = (os.environ.get("YAHOO_BASE_URL") or "").strip()
    if not v:
        return []
    bases = [s.strip().rstrip("/") for s in v.split(",") if s.strip()]
    return bases


def _chart_hosts() -> tuple[str, ...]:
    bases = _env_base_urls()
    if bases:
        return tuple(f"{b}/v8/finance/chart" for b in bases)
    return (
        "https://query1.finance.yahoo.com/v8/finance/chart",
        "https://query2.finance.yahoo.com/v8/finance/chart",
    )


def _quote_summary_hosts() -> tuple[str, ...]:
    bases = _env_base_urls()
    if bases:
        return tuple(f"{b}/v10/finance/quoteSummary" for b in bases)
    return (
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary",
        "https://query2.finance.yahoo.com/v10/finance/quoteSummary",
    )


def _crumb_hosts() -> tuple[str, ...]:
    bases = _env_base_urls()
    if bases:
        return tuple(f"{b}/v1/test/getcrumb" for b in bases)
    return (
        "https://query2.finance.yahoo.com/v1/test/getcrumb",
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
    )


_HTTP_TIMEOUT = float(__import__("os").environ.get("MCP_HTTP_TIMEOUT_SECONDS", "8"))
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_RETRY_DELAYS = (2, 4)  # seconds between retries on 429

# Regex to extract crumb from Yahoo quote page (CrumbStore in JS).
_CRUMB_PATTERNS = [
    re.compile(r'"CrumbStore":\s*\{\s*"crumb"\s*:\s*"([^"]+)"'),
    re.compile(r'"crumb"\s*:\s*"([^"\\]+)"'),
    re.compile(r'crumb["\']?\s*:\s*["\']([^"\']+)["\']'),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unpack(v: Any) -> Any:
    """Yahoo often returns numbers as {"raw": ..., "fmt": ...}. Prefer raw."""
    if isinstance(v, dict) and "raw" in v:
        return v.get("raw")
    return v


def _base_headers(symbol: str) -> dict[str, str]:
    # Shared headers for API calls (chart, quoteSummary).
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://finance.yahoo.com/quote/{symbol}",
        "Origin": "https://finance.yahoo.com",
    }


def _quote_page_headers() -> dict[str, str]:
    # Mimic a browser loading the quote page so Yahoo may set session cookies.
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }


def _extract_crumb_from_page(text: str) -> str | None:
    """Extract crumb from Yahoo quote page HTML/JS (CrumbStore)."""
    if not text:
        return None
    for pat in _CRUMB_PATTERNS:
        m = pat.search(text)
        if m:
            crumb = m.group(1).strip()
            if crumb and len(crumb) < 200:
                return crumb
    return None


def _get_crumb_session(symbol: str) -> tuple[requests.Session, str | None]:
    """Obtain session cookies and crumb for quoteSummary. Prefer crumb from quote page (matches session)."""
    s = requests.Session()
    # First request: browser-like headers so Yahoo may set cookies (same as your browser).
    s.headers.update(_quote_page_headers())
    page_text = ""
    try:
        r = s.get(
            f"https://finance.yahoo.com/quote/{symbol}",
            timeout=max(1.0, _HTTP_TIMEOUT),
        )
        page_text = r.text or ""
    except requests.RequestException:
        pass
    # Use API-style headers for getcrumb/quoteSummary (same session keeps cookies).
    s.headers.update(_base_headers(symbol))

    crumb = _extract_crumb_from_page(page_text)
    if crumb:
        return s, crumb

    for url in _crumb_hosts():
        try:
            r = s.get(url, timeout=max(1.0, _HTTP_TIMEOUT))
            if r.status_code == 429:
                time.sleep(_RETRY_DELAYS[0])
                r = s.get(url, timeout=max(1.0, _HTTP_TIMEOUT))
            r.raise_for_status()
            txt = (r.text or "").strip()
            if txt and len(txt) < 200 and "\n" not in txt and "<" not in txt:
                return s, txt
        except requests.RequestException:
            continue
    return s, None


def get_fundamental(payload: dict) -> dict[str, Any]:
    """Fetch richer ETF/fund fundamentals from Yahoo Finance quoteSummary API.

    Payload:
        symbol (str): Ticker (e.g. SPY, VOO, AAPL).

    Returns:
        {
            "symbol": str,
            "name": str?,
            "currency": str?,
            "price": float?,
            "close": float?,
            "expense_ratio": float?,
            "aum": float?,
            "sector_exposure": dict[str, float]?,
            "holdings_top10": list[dict]?,
            "raw": dict,  # selected quoteSummary modules
            "timestamp": str,
            "source": "yahoo"
        }
        Or {"error": str, "timestamp": str} on failure.
    """
    symbol = (payload.get("symbol") or payload.get("ticker") or "").strip()
    if not symbol:
        return {"error": "Missing required 'symbol'", "timestamp": _now_iso()}

    urls = [f"{base}/{symbol}" for base in _quote_summary_hosts()]
    # Modules chosen to cover ETF/fund profiles + key stats. Some tickers may not have all.
    params = {
        "modules": ",".join(
            [
                "price",
                "summaryDetail",
                "defaultKeyStatistics",
                "fundProfile",
                "fundPerformance",
                "topHoldings",
            ]
        )
    }
    session, crumb = _get_crumb_session(symbol)
    if crumb:
        params["crumb"] = crumb
    params["formatted"] = "false"

    data = None
    last_err: BaseException | None = None
    for url in urls:
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                resp = session.get(url, params=params, timeout=max(1.0, _HTTP_TIMEOUT))
                if resp.status_code == 429 and attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    logger.info("yahoo_finance 429 for %s, retry in %ss", symbol, delay)
                    time.sleep(delay)
                    continue
                # 401/403: try next host rather than failing fast
                if resp.status_code in (401, 403):
                    last_err = requests.HTTPError(
                        f"{resp.status_code} Unauthorized/Forbidden for {url}",
                        response=resp,
                    )
                    logger.info(
                        "yahoo_finance quoteSummary %s for %s (host fallback): %s",
                        resp.status_code,
                        symbol,
                        url,
                    )
                    break
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.HTTPError as e:
                last_err = e
                # treat 401/403 similarly: try next host
                if e.response is not None and e.response.status_code in (401, 403):
                    logger.info(
                        "yahoo_finance quoteSummary %s for %s (host fallback): %s",
                        e.response.status_code,
                        symbol,
                        url,
                    )
                    break
                logger.warning("yahoo_finance get_fundamental failed for %s: %s", symbol, e)
                return {"error": str(e), "timestamp": _now_iso()}
            except requests.RequestException as e:
                # Connection/timeout/etc. Try next host (or give up after hosts exhausted).
                last_err = e
                logger.info("yahoo_finance quoteSummary request failed for %s: %s", symbol, e)
                break
        if data is not None:
            break

    if data is None:
        # quoteSummary blocked (401) or failed: fall back to chart for price only.
        price_fallback = get_price({"symbol": symbol})
        if isinstance(price_fallback, dict) and "error" not in price_fallback:
            price_fallback["source"] = "yahoo"
            price_fallback["quoteSummary_blocked"] = True
            return price_fallback
        err_msg = str(last_err) if last_err else "Unknown error"
        return {"error": err_msg, "timestamp": _now_iso()}

    try:
        qs = data.get("quoteSummary") or {}
        result = (qs.get("result") or [])
        if not result:
            return {"error": f"No data for {symbol}", "timestamp": _now_iso()}
        res = result[0] or {}

        price_mod = (res.get("price") or {}) if isinstance(res, dict) else {}
        sd_mod = (res.get("summaryDetail") or {}) if isinstance(res, dict) else {}
        th_mod = (res.get("topHoldings") or {}) if isinstance(res, dict) else {}

        name = _unpack(price_mod.get("longName")) or _unpack(price_mod.get("shortName")) or symbol
        currency = _unpack(price_mod.get("currency"))

        price = _unpack(price_mod.get("regularMarketPrice"))
        close = _unpack(price_mod.get("regularMarketPreviousClose")) or _unpack(sd_mod.get("previousClose"))
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        try:
            close_f = float(close) if close is not None else None
        except (TypeError, ValueError):
            close_f = None

        expense_ratio = _unpack(sd_mod.get("annualReportExpenseRatio")) or _unpack(sd_mod.get("expenseRatio"))
        try:
            expense_ratio_f = float(expense_ratio) if expense_ratio is not None else None
        except (TypeError, ValueError):
            expense_ratio_f = None

        aum = _unpack(sd_mod.get("totalAssets")) or _unpack(sd_mod.get("totalAssetsValue"))
        try:
            aum_f = float(aum) if aum is not None else None
        except (TypeError, ValueError):
            aum_f = None

        holdings_top10: list[dict[str, Any]] = []
        holdings = th_mod.get("holdings") if isinstance(th_mod, dict) else None
        if isinstance(holdings, list):
            for h in holdings[:10]:
                if not isinstance(h, dict):
                    continue
                hp = _unpack(h.get("holdingPercent"))
                try:
                    hp_f = float(hp) if hp is not None else None
                except (TypeError, ValueError):
                    hp_f = None
                holdings_top10.append(
                    {
                        "symbol": _unpack(h.get("symbol")) or _unpack(h.get("holdingSymbol")),
                        "name": _unpack(h.get("holdingName")) or _unpack(h.get("name")),
                        "weight": hp_f,
                    }
                )

        sector_exposure: dict[str, float] = {}
        sector_weightings = th_mod.get("sectorWeightings") if isinstance(th_mod, dict) else None
        if isinstance(sector_weightings, list):
            for item in sector_weightings:
                if isinstance(item, dict) and item:
                    k = next(iter(item.keys()))
                    v = _unpack(item.get(k))
                    try:
                        sector_exposure[str(k)] = float(v) if v is not None else 0.0
                    except (TypeError, ValueError):
                        continue

        raw_modules: dict[str, Any] = {}
        for k in ("price", "summaryDetail", "defaultKeyStatistics", "fundProfile", "fundPerformance", "topHoldings"):
            if k in res:
                raw_modules[k] = res.get(k)

        out: dict[str, Any] = {
            "symbol": symbol,
            "name": name,
            "currency": currency,
            "price": price_f,
            "close": close_f if close_f is not None else price_f,
            "expense_ratio": expense_ratio_f,
            "aum": aum_f,
            "sector_exposure": sector_exposure,
            "holdings_top10": holdings_top10,
            "raw": raw_modules,
            "timestamp": _now_iso(),
            "source": "yahoo",
        }
        return out
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("yahoo_finance parse fundamental failed for %s: %s", symbol, e)
        return {"error": f"Parse error: {e}", "timestamp": _now_iso()}


def get_price(payload: dict) -> dict[str, Any]:
    """Fetch latest price from Yahoo Finance chart API.

    Payload:
        symbol (str): Ticker (e.g. SPY, AAPL). No .US suffix needed.

    Returns:
        Same schema as stooq_tool.get_price:
        {
            "symbol": str,
            "price": float,
            "close": float,
            "open": float?,
            "high": float?,
            "low": float?,
            "volume": int?,
            "date": str,
            "timestamp": str,
            "source": "yahoo"
        }
        Or {"error": str, "timestamp": str} on failure.
    """
    symbol = (payload.get("symbol") or payload.get("ticker") or "").strip()
    if not symbol:
        return {"error": "Missing required 'symbol'", "timestamp": _now_iso()}

    urls = [f"{base}/{symbol}" for base in _chart_hosts()]
    params = {"range": "1d", "interval": "1d"}
    headers = _base_headers(symbol)

    data = None
    last_err: BaseException | None = None
    for url in urls:
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                resp = requests.get(
                    url, params=params, headers=headers, timeout=max(1.0, _HTTP_TIMEOUT)
                )
                if resp.status_code == 429:
                    if attempt < len(_RETRY_DELAYS):
                        delay = _RETRY_DELAYS[attempt]
                        logger.info("yahoo_finance 429 for %s, retry in %ss", symbol, delay)
                        time.sleep(delay)
                        continue
                    last_err = requests.HTTPError(
                        f"429 Too Many Requests for {url}", response=resp
                    )
                elif resp.status_code in (401, 403):
                    last_err = requests.HTTPError(
                        f"{resp.status_code} Unauthorized/Forbidden for {url}", response=resp
                    )
                    break
                else:
                    resp.raise_for_status()
                data = resp.json()
                break
            except requests.HTTPError as e:
                last_err = e
                if e.response is not None and e.response.status_code == 429:
                    if attempt < len(_RETRY_DELAYS):
                        delay = _RETRY_DELAYS[attempt]
                        logger.info("yahoo_finance 429 for %s, retry in %ss", symbol, delay)
                        time.sleep(delay)
                        continue
                # 401/403: try next host
                if e.response is not None and e.response.status_code in (401, 403):
                    break
                logger.warning("yahoo_finance get_price failed for %s: %s", symbol, e)
                return {"error": str(e), "timestamp": _now_iso()}
            except requests.RequestException as e:
                last_err = e
                logger.info("yahoo_finance chart request failed for %s: %s", symbol, e)
                break
        if data is not None:
            break

    if data is None:
        err_msg = str(last_err) if last_err else "Unknown error"
        return {"error": err_msg, "timestamp": _now_iso()}

    try:
        chart = data.get("chart") or {}
        result = (chart.get("result") or [])
        if not result:
            return {"error": f"No data for {symbol}", "timestamp": _now_iso()}
        res = result[0]
        meta = res.get("meta") or {}
        indicators = res.get("indicators") or {}
        quote = ((indicators.get("quote") or [{}])[0] or {})
        timestamps = res.get("timestamp") or []
        date_str = ""
        if timestamps:
            try:
                dt = datetime.fromtimestamp(timestamps[0], tz=timezone.utc)
                date_str = dt.strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                date_str = str(timestamps[0])

        price = meta.get("regularMarketPrice")
        if price is None and quote.get("close"):
            closes = quote["close"]
            price = closes[-1] if closes else None
        if price is None:
            price = meta.get("chartPreviousClose")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        if price is None:
            return {"error": f"No price for {symbol}", "timestamp": _now_iso()}

        out: dict[str, Any] = {
            "symbol": symbol,
            "price": price,
            "close": price,
            "date": date_str,
            "timestamp": _now_iso(),
            "source": "yahoo",
        }
        for key, field in [("open", "open"), ("high", "high"), ("low", "low"), ("volume", "volume")]:
            vals = quote.get(field)
            if vals is not None and len(vals) > 0 and vals[-1] is not None:
                try:
                    out[key] = int(float(vals[-1])) if key == "volume" else float(vals[-1])
                except (TypeError, ValueError):
                    pass
        return out
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("yahoo_finance parse failed for %s: %s", symbol, e)
        return {"error": f"Parse error: {e}", "timestamp": _now_iso()}
