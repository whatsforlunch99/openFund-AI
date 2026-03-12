"""News search via RSS and GDELT. MCP tool for WebSearcher per docs/news-searcher-design.md."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_YAHOO_FINANCE_RSS = "https://finance.yahoo.com/news/rssindex"
_GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_DEFAULT_DAYS = 7
_HTTP_TIMEOUT = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_by_local_name(parent: ET.Element, local: str) -> ET.Element | None:
    """Find first child with given local name (namespace-agnostic)."""
    for c in parent:
        if c.tag.split("}")[-1] == local:
            return c
    return None


def _parse_rfc822_date(s: str) -> str | None:
    """Parse RSS pubDate to yyyy-mm-dd. Best-effort."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    # Common format: "Wed, 05 Mar 2026 12:00:00 GMT"
    m = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", s)
    if m:
        day, mon, year = m.group(1), m.group(2), m.group(3)
        mon_map = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                   "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
        mn = mon_map.get(mon[:3])
        if mn:
            return f"{year}-{mn}-{day.zfill(2)}"
    return None


def search_rss(payload: dict) -> dict[str, Any]:
    """Search news via Google News RSS.

    Payload: query (required, string), days (optional, int, default 7).
    Returns: {"items": [{"title", "link", "published", "source"}], "timestamp": str} or {"error": str}.
    """
    query = (payload.get("query") or payload.get("q") or "").strip()
    if not query:
        return {"error": "Missing required parameter 'query'", "timestamp": _now_iso()}

    days = payload.get("days", _DEFAULT_DAYS)
    try:
        days = int(days)
        days = max(1, min(30, days))
    except (TypeError, ValueError):
        days = _DEFAULT_DAYS

    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    url = f"{_GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; OpenFund-AI/1.0; +https://github.com/openfund-ai)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("news_tool search_rss fetch failed: %s", e)
        return {"error": str(e), "timestamp": _now_iso()}

    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(data)
        # RSS 2.0: channel/item; Atom: feed/entry
        ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
        for item in root.findall(".//item") or root.findall(".//atom:entry", ns) or []:
            title_el = item.find("title") or item.find("atom:title", ns)
            link_el = item.find("link") or item.find("atom:link", ns)
            pub_el = item.find("pubDate") or item.find("published") or item.find("atom:published", ns)
            source_el = item.find("source") or item.find("atom:source", ns)
            source_name = "Unknown"
            if source_el is not None and source_el.text:
                source_name = (source_el.text or "").strip()
            elif source_el is not None:
                src_title = source_el.find("title") or source_el.find("atom:title", ns)
                if src_title is not None and src_title.text:
                    source_name = (src_title.text or "").strip()
            link = ""
            if link_el is not None:
                link = (link_el.text or link_el.get("href") or "").strip()
            title = (title_el.text or "").strip() if title_el is not None else ""
            published = (pub_el.text or "").strip() if pub_el is not None else ""
            date_str = _parse_rfc822_date(published) or published
            if title or link:
                items.append({
                    "title": title or "(No title)",
                    "link": link,
                    "published": published,
                    "date": date_str,
                    "source": source_name,
                })
    except ET.ParseError as e:
        logger.warning("news_tool search_rss parse failed: %s", e)
        return {"error": f"RSS parse error: {e}", "timestamp": _now_iso()}

    return {
        "items": items[:50],
        "timestamp": _now_iso(),
    }


def search_yahoo_rss(payload: dict) -> dict[str, Any]:
    """Fetch general finance news from Yahoo Finance RSS (fixed feed, no query).

    Payload: limit (optional, int, default 20).
    Returns: {"items": [{"title", "link", "published", "source"}], "timestamp": str} or {"error": str}.
    """
    limit = 20
    if "limit" in payload and payload["limit"] is not None:
        try:
            limit = max(1, min(50, int(payload["limit"])))
        except (TypeError, ValueError):
            pass
    url = _YAHOO_FINANCE_RSS
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; OpenFund-AI/1.0)",
            "Accept": "application/rss+xml, application/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("news_tool search_yahoo_rss fetch failed: %s", e)
        return {"error": str(e), "timestamp": _now_iso()}

    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # Yahoo may use namespaced elements; match by local name
        candidates = root.findall(".//item") or root.findall(".//atom:entry", ns)
        if not candidates:
            candidates = root.findall(".//{*}item") or root.findall(".//{*}entry")
        for item in candidates:
            title_el = item.find("title") or item.find("atom:title", ns) or _find_by_local_name(item, "title")
            link_el = item.find("link") or item.find("atom:link", ns) or _find_by_local_name(item, "link")
            pub_el = item.find("pubDate") or item.find("published") or item.find("atom:published", ns) or _find_by_local_name(item, "pubDate") or _find_by_local_name(item, "published")
            source_el = item.find("source") or _find_by_local_name(item, "source")
            link = (link_el.text or link_el.get("href") or "").strip() if link_el is not None else ""
            title = (title_el.text or "").strip() if title_el is not None else ""
            published = (pub_el.text or "").strip() if pub_el is not None else ""
            source_name = (source_el.text or "").strip() if source_el is not None and source_el.text else "Yahoo Finance"
            if title or link:
                items.append({
                    "title": title or "(No title)",
                    "link": link,
                    "published": published,
                    "date": _parse_rfc822_date(published),
                    "source": source_name or "Yahoo Finance",
                })
    except ET.ParseError as e:
        logger.warning("news_tool search_yahoo_rss parse failed: %s", e)
        return {"error": f"RSS parse error: {e}", "timestamp": _now_iso()}

    return {"items": items[:limit], "timestamp": _now_iso()}


def search_gdelt(payload: dict) -> dict[str, Any]:
    """Search news via GDELT API (free, no key). May return 429; use sparingly.

    Payload: query (required, string), limit (optional, int, default 10).
    Returns: {"items": [{"title", "link", "published", "source"}], "timestamp": str} or {"error": str}.
    """
    query = (payload.get("query") or payload.get("q") or "").strip()
    if not query:
        return {"error": "Missing required parameter 'query'", "timestamp": _now_iso()}

    limit = min(15, max(1, int(payload.get("limit", 10))))
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": str(limit),
        "format": "json",
    }
    url = f"{_GDELT_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; OpenFund-AI/1.0)"},
    )
    last_err = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt == 0:
                time.sleep(2)
                continue
            logger.warning("news_tool search_gdelt HTTP %s: %s", e.code, e)
            return {"error": f"GDELT HTTP {e.code}", "timestamp": _now_iso()}
        except Exception as e:
            logger.warning("news_tool search_gdelt failed: %s", e)
            return {"error": str(e), "timestamp": _now_iso()}
    else:
        if last_err:
            return {"error": f"GDELT HTTP {last_err.code}", "timestamp": _now_iso()}

    items: list[dict[str, Any]] = []
    articles = data.get("articles") or data.get("ArticleList") or []
    if not isinstance(articles, list):
        return {"items": [], "timestamp": _now_iso()}
    for a in articles[:limit]:
        if not isinstance(a, dict):
            continue
        title = (a.get("title") or "").strip()
        url_val = (a.get("url") or a.get("link") or "").strip()
        published = a.get("seendate") or a.get("published") or ""
        source = (a.get("source") or a.get("domain") or "Unknown").strip()
        if title or url_val:
            date_str = None
            if isinstance(published, str) and len(published) >= 10:
                date_str = published[:10]
            items.append({
                "title": title or "(No title)",
                "link": url_val,
                "published": published,
                "date": date_str,
                "source": source,
            })
    return {"items": items, "timestamp": _now_iso()}
