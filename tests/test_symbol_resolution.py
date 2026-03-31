"""Tests for planner symbol resolution cache and by_tool planning."""

import json
import os
import tempfile

from util.planner_symbol_resolution import (
    SYMBOL_RESOLUTION_SCHEMA_VERSION,
    derive_cache_key,
    get_cached_entry,
    load_cache,
    put_cached_entry,
    resolve_symbol_resolution_for_query,
)


def test_known_issuers_json_exists_and_has_vanke() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root, "database", "symbol_resolution_known_issuers.json")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    vanke = data.get("china vanke")
    assert isinstance(vanke, dict)
    assert "China Vanke" in (vanke.get("canonical_name") or "")
    listings = vanke.get("listings") or []
    assert any(
        isinstance(L, dict) and L.get("symbol_yahoo") == "000002.SZ" for L in listings
    )
    assert vanke.get("symbol_type") == "equities"


def test_routing_json_exists_and_matches_vanke() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root, "database", "symbol_resolution_routing.json")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    routes = data.get("routes") or []
    vanke_route = next(
        (
            r
            for r in routes
            if isinstance(r, dict) and r.get("cache_key") == "china vanke"
        ),
        None,
    )
    assert vanke_route is not None
    phrases = vanke_route.get("phrases") or []
    assert "vanke" in [p.lower() for p in phrases if isinstance(p, str)]


def test_derive_cache_key_vanke() -> None:
    assert derive_cache_key("What about China Vanke stock?") == "china vanke"


def test_resolve_vanke_listings_and_skip_market_tool() -> None:
    r = resolve_symbol_resolution_for_query("price of china vanke today")
    assert r["schema_version"] == SYMBOL_RESOLUTION_SCHEMA_VERSION
    assert r["status"] == "resolved"
    assert "China Vanke" in (r.get("canonical_name") or "")
    by = r.get("by_tool") or {}
    assert by.get("market_tool.get_fundamentals", {}).get("action") == "skip"
    assert by.get("yahoo_finance_tool.get_fundamental", {}).get("action") == "call"
    assert "000002.SZ" in (by.get("yahoo_finance_tool.get_fundamental") or {}).get(
        "symbol", ""
    )
    assert r.get("symbol_type") == "equities"
    assert by.get("etfdb_tool.get_fund_data", {}).get("action") == "skip"
    assert (by.get("etfdb_tool.get_fund_data") or {}).get("reason_code") == "not_etf"


def test_resolve_spy_etf_calls_etfdb() -> None:
    r = resolve_symbol_resolution_for_query("SPY price and holdings")
    assert r["status"] == "resolved"
    assert r.get("symbol_type") == "etfs"
    by = r.get("by_tool") or {}
    assert by.get("etfdb_tool.get_fund_data", {}).get("action") == "call"
    assert "SPY" in (by.get("etfdb_tool.get_fund_data") or {}).get("symbol", "")


def test_resolve_empty_query_not_applicable() -> None:
    r = resolve_symbol_resolution_for_query("")
    assert r["status"] == "not_applicable"
    assert r.get("reason_code") == "empty_query"
    assert r.get("symbol_type") == ""


def test_symbol_resolution_cache_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("MEMORY_STORE_PATH")
        os.environ["MEMORY_STORE_PATH"] = tmp
        try:
            key = "china vanke"
            entry = resolve_symbol_resolution_for_query("vanke stock")
            put_cached_entry(key, entry)
            path = os.path.join(tmp, "symbol_resolution_cache.json")
            assert os.path.isfile(path)
            loaded = get_cached_entry(key)
            assert loaded is not None
            assert loaded.get("status") == "resolved"
            data = load_cache()
            assert key in data
        finally:
            if prev is not None:
                os.environ["MEMORY_STORE_PATH"] = prev
            else:
                os.environ.pop("MEMORY_STORE_PATH", None)


def test_planner_request_includes_symbol_resolution() -> None:
    from a2a.message_bus import InMemoryMessageBus
    from agents.planner_agent import PlannerAgent, TaskStep

    bus = InMemoryMessageBus()
    p = PlannerAgent("planner", bus)
    cid = "conv-test-1"
    sr = resolve_symbol_resolution_for_query("china vanke")
    p._symbol_resolution_by_conversation[cid] = sr
    step = TaskStep("websearcher", {"query": "test"})
    msg = p.create_research_request("user q", step, conversation_id=cid)
    assert msg.content.get("symbol_resolution") is sr
    assert msg.content.get("resolution_listings") == sr.get("listings")
    assert msg.content.get("resolution_symbol_type") == "equities"
    assert "Vanke" in (msg.content.get("resolution_canonical_name") or "")


def test_format_aggregated_for_sufficiency_includes_normalized_fund() -> None:
    from unittest.mock import MagicMock

    from agents.planner_agent import PlannerAgent

    p = PlannerAgent("planner", MagicMock())
    collected = {
        "websearcher": {
            "summary": "Market summary here.",
            "normalized_fund": [
                {"symbol": "SPY", "price": 400.0},
                {"symbol": "000002.SZ", "price": 4.06},
            ],
        }
    }
    agg = p._format_aggregated_for_sufficiency(collected)
    assert "normalized_fund_prices" in agg
    assert "SPY" in agg
    assert "normalized_fund_symbols" in agg


def test_collected_has_answer_signal_price_line() -> None:
    from unittest.mock import MagicMock

    from agents.planner_agent import PlannerAgent

    p = PlannerAgent("planner", MagicMock())
    assert p._collected_has_answer_signal(
        {
            "websearcher": {
                "normalized_fund": [{"symbol": "X", "price": 1.0}],
            }
        }
    )
    assert not p._collected_has_answer_signal({"websearcher": {"summary": "short"}})


def test_legacy_symbol_types_normalize_to_graph_buckets() -> None:
    """Routing JSON may still carry etf/stock; normalization maps to etfs/equities."""
    from util import planner_symbol_resolution as ps

    assert ps._normalize_symbol_type("etf") == "etfs"
    assert ps._normalize_symbol_type("stock") == "equities"
    assert ps._normalize_symbol_type("equities") == "equities"
    assert ps._normalize_symbol_type("bogus") == "unknown"
