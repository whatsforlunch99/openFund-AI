"""Tests for ticker extraction from free-form queries (websearch_agent)."""

from unittest.mock import MagicMock

from agents.websearch_agent import (
    WebSearcherAgent,
    _by_tool_symbol_for_iteration,
    _pin_matches_iteration,
    extract_symbol_from_query,
)


def test_extract_symbol_china_vanke_prefers_listed_ticker() -> None:
    q = "China Vanke Co., Ltd stock price recent performance"
    assert extract_symbol_from_query(q) == "000002.SZ"


def test_normalize_symbol_china_vanke_matches_extract() -> None:
    bus = MagicMock()
    agent = WebSearcherAgent("websearcher", bus, mcp_client=None)
    q = "how is China Vanke doing as an equity"
    assert agent._normalize_symbol(q) == "000002.SZ"


def test_pin_matches_iteration_same_security_suffix() -> None:
    assert _pin_matches_iteration("000002.SZ", "000002") is True
    assert _pin_matches_iteration("000002.SZ", "000002.SZ") is True


def test_pin_matches_iteration_different_securities() -> None:
    assert _pin_matches_iteration("000002.SZ", "SPY") is False


def test_extract_spy_wins_over_sp500_phrase_in_same_query() -> None:
    """Regression: 'SPY (S&P 500 ETF)' must not resolve to SPX via query_substring_to_symbol order."""
    q = (
        "Search for latest news, price action, and market outlook for China Vanke "
        "and SPY (S&P 500 ETF)."
    )
    assert extract_symbol_from_query(q) == "SPY"


def test_merge_catalog_prefers_spy_over_spx_when_query_names_spy() -> None:
    from agents.websearch_agent import _merge_catalog_symbols_for_query

    q = "China Vanke and SPY (S&P 500 ETF)"
    assert _merge_catalog_symbols_for_query(["SPX"], q) == ["SPY"]
    assert _merge_catalog_symbols_for_query(["SPX", "VOO"], q)[:2] == ["SPY", "VOO"]


def test_by_tool_symbol_for_iteration_uses_loop_symbol_when_pin_differs() -> None:
    """Planner by_tool pins primary listing; parallel fetch for another ticker must not reuse it."""
    by_tool = {
        "yahoo_finance_tool.get_fundamental": {
            "action": "call",
            "symbol": "000002.SZ",
        }
    }
    assert (
        _by_tool_symbol_for_iteration(
            by_tool, "yahoo_finance_tool.get_fundamental", "SPY"
        )
        == "SPY"
    )
    assert (
        _by_tool_symbol_for_iteration(
            by_tool, "yahoo_finance_tool.get_fundamental", "000002.SZ"
        )
        == "000002.SZ"
    )
