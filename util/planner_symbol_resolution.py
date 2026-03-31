"""Planner-side symbol resolution: listings, per-tool call/skip plan, cache key.

Committed multi-listing entities live in ``database/symbol_resolution_known_issuers.json``
(keyed by cache key). Phrase/symbol → cache_key routing and ticker→type hints live in
``database/symbol_resolution_routing.json`` (separate from issuer listings). Runtime
resolutions are cached in ``{MEMORY_STORE_PATH}/symbol_resolution_cache.json``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from agents.websearch_agent import extract_symbol_from_query

# ---------------------------------------------------------------------------
# MCP by_tool registry (planner-side gating only; keep aligned with openfund_mcp/tools)
# ---------------------------------------------------------------------------

MARKET_US = "US"
MARKET_CN = "CN"
MARKET_HK = "HK"
MARKET_EU = "EU"

FINANCIAL_TOOL_IDS = (
    "stooq_tool.get_price",
    "yahoo_finance_tool.get_fundamental",
    "yahoo_finance_tool.get_price",
    "etfdb_tool.get_fund_data",
    "market_tool.get_fundamentals",
    "market_tool.get_news",
    "market_tool.get_global_news",
)

NEWS_TOOL_IDS = (
    "news_tool.search_rss",
    "news_tool.search_yahoo_rss",
    "news_tool.search_gdelt",
)

_TOOL_MARKETS: dict[str, frozenset[str]] = {
    "stooq_tool.get_price": frozenset({MARKET_US, MARKET_EU}),
    "yahoo_finance_tool.get_fundamental": frozenset({MARKET_US, MARKET_HK, MARKET_CN}),
    "yahoo_finance_tool.get_price": frozenset({MARKET_US, MARKET_HK, MARKET_CN}),
    "etfdb_tool.get_fund_data": frozenset({MARKET_US}),
    "market_tool.get_fundamentals": frozenset({MARKET_US}),
    "market_tool.get_news": frozenset({MARKET_US}),
    "market_tool.get_global_news": frozenset(),
    "news_tool.search_rss": frozenset(),
    "news_tool.search_yahoo_rss": frozenset(),
    "news_tool.search_gdelt": frozenset(),
}


def tool_supports_market(tool_id: str, market: str) -> bool:
    supported = _TOOL_MARKETS.get(tool_id)
    if supported is None:
        return True
    if not supported:
        return True
    return market in supported


def should_include_financial_tool(tool_id: str, primary_market: str) -> bool:
    return tool_supports_market(tool_id, primary_market)


def skip_entry(reason_code: str, message: str = "") -> dict[str, Any]:
    return {"action": "skip", "reason_code": reason_code, "message": message}


def call_entry(symbol: Optional[str] = None, listing_index: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {"action": "call", "listing_index": listing_index}
    if symbol is not None:
        out["symbol"] = symbol
    return out


SYMBOL_RESOLUTION_SCHEMA_VERSION = 3

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_KNOWN_ISSUERS_PATH = os.path.join(
    _REPO_ROOT, "database", "symbol_resolution_known_issuers.json"
)
_ROUTING_PATH = os.path.join(_REPO_ROOT, "database", "symbol_resolution_routing.json")
_known_issuers_loaded: Optional[dict[str, dict[str, Any]]] = None
_routing_loaded: Optional[dict[str, Any]] = None

# Aligned with graph dataset buckets (see some_plan.md). Legacy JSON may still use etf/stock.
_GRAPH_SYMBOL_TYPES = frozenset(
    {
        "cryptos",
        "currencies",
        "equities",
        "etfs",
        "funds",
        "indices",
        "moneymarkets",
        "unknown",
    }
)
_LEGACY_TYPE_MAP = {"etf": "etfs", "stock": "equities"}


def _normalize_symbol_type(raw: Any) -> str:
    s = (raw if isinstance(raw, str) else "unknown").strip().lower()
    if not s:
        return "unknown"
    s = _LEGACY_TYPE_MAP.get(s, s)
    return s if s in _GRAPH_SYMBOL_TYPES else "unknown"


def _load_routing() -> dict[str, Any]:
    """Load routing: routes (phrase/symbol → cache_key), ticker_symbol_types (graph-aligned type)."""
    global _routing_loaded
    if _routing_loaded is not None:
        return _routing_loaded
    empty: dict[str, Any] = {"routes": [], "ticker_symbol_types": {}}
    if not os.path.isfile(_ROUTING_PATH):
        _routing_loaded = empty
        return _routing_loaded
    try:
        with open(_ROUTING_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        _routing_loaded = empty
        return _routing_loaded
    if not isinstance(raw, dict):
        _routing_loaded = empty
        return _routing_loaded
    routes = raw.get("routes") or []
    if not isinstance(routes, list):
        routes = []
    ticker_types: dict[str, str] = {}
    raw_tt = raw.get("ticker_symbol_types") or {}
    if isinstance(raw_tt, dict):
        for k, v in raw_tt.items():
            if isinstance(k, str) and isinstance(v, str):
                ticker_types[k.strip().upper()] = _normalize_symbol_type(v)
    _routing_loaded = {"routes": routes, "ticker_symbol_types": ticker_types}
    return _routing_loaded


def _routing_cache_key_for_query(query: str) -> Optional[str]:
    """If query matches a routing phrase or symbol, return that route's cache_key."""
    q_raw = query or ""
    q_lower = q_raw.strip().lower()
    if not q_lower:
        return None
    sym_extracted = extract_symbol_from_query(q_raw)
    sym_norm = sym_extracted.strip().upper() if sym_extracted else ""

    for route in _load_routing()["routes"]:
        if not isinstance(route, dict):
            continue
        ck = route.get("cache_key")
        if not isinstance(ck, str) or not ck.strip():
            continue
        phrases = route.get("phrases") or []
        if isinstance(phrases, list):
            for p in sorted(
                (x for x in phrases if isinstance(x, str) and x.strip()),
                key=len,
                reverse=True,
            ):
                if p.lower() in q_lower:
                    return ck.strip().lower()
        syms = route.get("symbols") or []
        if sym_norm and isinstance(syms, list):
            for s in syms:
                if isinstance(s, str) and s.strip().upper() == sym_norm:
                    return ck.strip().lower()
    return None


def _load_known_issuers() -> dict[str, dict[str, Any]]:
    """Load cache_key -> {canonical_name, listings} from committed JSON; empty if missing."""
    global _known_issuers_loaded
    if _known_issuers_loaded is not None:
        return _known_issuers_loaded
    out: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(_KNOWN_ISSUERS_PATH):
        _known_issuers_loaded = out
        return out
    try:
        with open(_KNOWN_ISSUERS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        _known_issuers_loaded = out
        return out
    if not isinstance(raw, dict):
        _known_issuers_loaded = out
        return out
    for key, issuer in raw.items():
        if not isinstance(key, str) or not isinstance(issuer, dict):
            continue
        name = issuer.get("canonical_name")
        listings = issuer.get("listings")
        if not isinstance(name, str) or not isinstance(listings, list):
            continue
        st = _normalize_symbol_type(issuer.get("symbol_type", "unknown"))
        out[key.strip().lower()] = {
            "canonical_name": name,
            "symbol_type": st,
            "listings": [dict(x) for x in listings if isinstance(x, dict)],
        }
    _known_issuers_loaded = out
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_cache_key(query: str) -> str:
    """Stable lowercase key for JSON cache (routing file first, then ticker / query slice)."""
    q = (query or "").strip().lower()
    if not q:
        return ""
    routed = _routing_cache_key_for_query(query)
    if routed:
        return routed
    # Prefer sym-based key for non-default tickers
    if len(q) < 200:
        sym = extract_symbol_from_query(query)
        if sym and sym != "AAPL":
            return f"sym:{sym.lower()}"
    return q[:120].strip().lower() if q else ""


def _ticker_symbol_type_from_routing(sym: str) -> str:
    """Map extracted ticker to etf/stock/unknown using routing file."""
    u = (sym or "").strip().upper()
    if not u:
        return "unknown"
    m = _load_routing()["ticker_symbol_types"]
    if u in m:
        return m[u]
    if "." in u:
        base = u.split(".", 1)[0].strip().upper()
        if base in m:
            return m[base]
    return "unknown"


def _listings_from_ticker(sym: str) -> list[dict[str, Any]]:
    s = (sym or "").strip().upper()
    if not s:
        return []
    if s.endswith(".SZ"):
        base = s.replace(".SZ", "")
        return [
            {
                "exchange": "SZSE",
                "market": MARKET_CN,
                "symbol_yahoo": s,
                "symbol_compact": base,
                "primary": True,
            }
        ]
    if s.endswith(".HK"):
        base = s.replace(".HK", "")
        return [
            {
                "exchange": "HKEX",
                "market": MARKET_HK,
                "symbol_yahoo": s,
                "symbol_compact": base,
                "primary": True,
            }
        ]
    if s.endswith(".SS"):
        base = s.replace(".SS", "")
        return [
            {
                "exchange": "SSE",
                "market": MARKET_CN,
                "symbol_yahoo": s,
                "symbol_compact": base,
                "primary": True,
            }
        ]
    return [
        {
            "exchange": "US",
            "market": MARKET_US,
            "symbol_yahoo": s,
            "symbol_compact": s,
            "primary": True,
        }
    ]


def _build_by_tool(
    listings: list[dict[str, Any]], symbol_type: str = "unknown"
) -> dict[str, Any]:
    """Per MCP tool: call (with symbol when needed) or skip with reason_code."""
    by_tool: dict[str, Any] = {}
    if not listings:
        return by_tool

    st = _normalize_symbol_type(symbol_type)
    primary = listings[0]
    mkt = str(primary.get("market") or MARKET_US)
    yahoo_sym = str(primary.get("symbol_yahoo") or primary.get("symbol_compact") or "")
    compact = str(primary.get("symbol_compact") or yahoo_sym)

    for tid in FINANCIAL_TOOL_IDS:
        if tid == "market_tool.get_global_news":
            by_tool[tid] = call_entry()
            continue
        if tid == "etfdb_tool.get_fund_data":
            if st != "etfs":
                by_tool[tid] = skip_entry(
                    "not_etf",
                    "ETFdb applies to ETFs only",
                )
                continue
            if mkt != MARKET_US:
                by_tool[tid] = skip_entry("not_etf", "ETFdb US ETFs only")
            else:
                by_tool[tid] = call_entry(symbol=yahoo_sym)
            continue
        if not should_include_financial_tool(tid, mkt):
            by_tool[tid] = skip_entry(
                "market_not_supported",
                f"Tool not used for market {mkt}",
            )
            continue
        if tid == "stooq_tool.get_price":
            by_tool[tid] = call_entry(symbol=compact)
            continue
        if tid.startswith("yahoo_finance_tool"):
            by_tool[tid] = call_entry(symbol=yahoo_sym)
            continue
        if tid.startswith("market_tool"):
            if mkt != MARKET_US:
                by_tool[tid] = skip_entry(
                    "unsupported_ticker_format_or_vendor",
                    "market_tool/Alpha Vantage path skipped for non-US listing",
                )
            else:
                by_tool[tid] = call_entry(symbol=yahoo_sym)
            continue

    for tid in NEWS_TOOL_IDS:
        by_tool[tid] = call_entry()

    return by_tool


def resolution_summary_for_prompt(resolution: dict[str, Any]) -> str:
    """Short text for LLM decomposition context."""
    if not isinstance(resolution, dict):
        return ""
    if resolution.get("status") != "resolved":
        return ""
    name = resolution.get("canonical_name") or ""
    listings = resolution.get("listings") or []
    if not listings:
        return ""
    syms = [str(L.get("symbol_yahoo") or L.get("symbol_compact") or "") for L in listings if isinstance(L, dict)]
    syms = [s for s in syms if s]
    parts = [f"Resolved entity: {name or syms[0]}", f"Primary symbols: {', '.join(syms[:4])}"]
    return "\n".join(parts)


def resolve_symbol_resolution_for_query(query: str) -> dict[str, Any]:
    """Full symbol_resolution payload for ACL content and cache (schema_version 3: graph-aligned symbol_type)."""
    q = (query or "").strip()
    cache_key = derive_cache_key(q)
    if not q:
        return {
            "schema_version": SYMBOL_RESOLUTION_SCHEMA_VERSION,
            "status": "not_applicable",
            "reason_code": "empty_query",
            "cache_key": "",
            "canonical_name": "",
            "symbol_type": "",
            "listings": [],
            "by_tool": {},
            "source": "planner",
            "updated_at": _now_iso(),
        }

    listings: list[dict[str, Any]] = []
    canonical_name = ""
    symbol_type = "unknown"
    source = "heuristic_planner"

    issuers = _load_known_issuers()
    if cache_key and cache_key in issuers:
        issuer = issuers[cache_key]
        listings = [dict(x) for x in issuer["listings"]]
        canonical_name = issuer["canonical_name"]
        symbol_type = _normalize_symbol_type(issuer.get("symbol_type"))

    if not listings:
        sym = extract_symbol_from_query(q)
        if sym and sym != "AAPL":
            listings = _listings_from_ticker(sym)
            canonical_name = sym
            symbol_type = _ticker_symbol_type_from_routing(sym)

    if not listings:
        return {
            "schema_version": SYMBOL_RESOLUTION_SCHEMA_VERSION,
            "status": "not_applicable",
            "reason_code": "no_listable_security",
            "cache_key": cache_key or q[:80].lower(),
            "canonical_name": "",
            "symbol_type": "unknown",
            "listings": [],
            "by_tool": {},
            "source": source,
            "updated_at": _now_iso(),
        }

    primary = listings[0]
    by_tool = _build_by_tool(listings, symbol_type=symbol_type)

    return {
        "schema_version": SYMBOL_RESOLUTION_SCHEMA_VERSION,
        "status": "resolved",
        "cache_key": cache_key or (primary.get("symbol_yahoo") or "").lower(),
        "canonical_name": canonical_name or primary.get("symbol_yahoo", ""),
        "symbol_type": symbol_type,
        "listings": listings,
        "by_tool": by_tool,
        "source": source,
        "updated_at": _now_iso(),
    }


def maybe_use_cached_resolution(
    query: str, cached: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Return cached entry if schema matches; else compute fresh."""
    if isinstance(cached, dict) and int(cached.get("schema_version", 0)) == SYMBOL_RESOLUTION_SCHEMA_VERSION:
        return dict(cached)
    return resolve_symbol_resolution_for_query(query)


# ---------------------------------------------------------------------------
# Runtime JSON cache under MEMORY_STORE_PATH (was symbol_resolution_cache)
# ---------------------------------------------------------------------------

_SYMBOL_RESOLUTION_CACHE_FILENAME = "symbol_resolution_cache.json"


def _symbol_resolution_cache_path() -> str:
    root = os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")
    return os.path.join(root, _SYMBOL_RESOLUTION_CACHE_FILENAME)


def load_cache() -> dict[str, Any]:
    path = _symbol_resolution_cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_cached_entry(cache_key: str) -> Optional[dict[str, Any]]:
    if not cache_key:
        return None
    data = load_cache()
    entry = data.get(cache_key)
    return entry if isinstance(entry, dict) else None


def put_cached_entry(cache_key: str, entry: dict[str, Any]) -> None:
    if not cache_key or not isinstance(entry, dict):
        return
    path = _symbol_resolution_cache_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = load_cache()
    data[cache_key] = entry
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
