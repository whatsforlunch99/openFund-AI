"""WebSearcher contract tests for freshness and source-conflict metadata."""

from a2a.message_bus import InMemoryMessageBus
from agents.websearch_agent import WebSearcherAgent


def test_websearch_contract_adds_freshness_flags() -> None:
    bus = InMemoryMessageBus()
    agent = WebSearcherAgent("websearcher", bus, mcp_client=None)
    reply = {
        "normalized_fund": [{"symbol": "NVDA", "price": 900.0}],
        "timestamp": "2026-04-20T10:00:00Z",
        "citations": {"NEWS1": "https://example.com/a"},
    }
    out = agent._augment_websearch_contract(reply)
    freshness = out.get("freshness")
    assert isinstance(freshness, dict)
    assert "price_is_fresh" in freshness
    assert "fundamentals_is_fresh" in freshness


def test_websearch_contract_marks_stale_price_when_timestamp_old() -> None:
    bus = InMemoryMessageBus()
    agent = WebSearcherAgent("websearcher", bus, mcp_client=None)
    reply = {
        "normalized_fund": [
            {
                "symbol": "NVDA",
                "price": 900.0,
                "timestamp": "2020-01-01T00:00:00Z",
            }
        ],
        "citations": {},
    }
    out = agent._augment_websearch_contract(reply)
    freshness = out.get("freshness") or {}
    assert freshness.get("price_is_fresh") is False


def test_websearch_contract_marks_not_fresh_when_timestamp_missing() -> None:
    bus = InMemoryMessageBus()
    agent = WebSearcherAgent("websearcher", bus, mcp_client=None)
    out = agent._augment_websearch_contract({"normalized_fund": [{"symbol": "NVDA", "price": 900.0}]})
    freshness = out.get("freshness") or {}
    assert freshness.get("price_is_fresh") is False


def test_websearch_contract_collects_source_conflicts() -> None:
    bus = InMemoryMessageBus()
    agent = WebSearcherAgent("websearcher", bus, mcp_client=None)
    reply = {
        "normalized_fund": [
            {
                "symbol": "NVDA",
                "price": 900.0,
                "conflict_resolution": {
                    "chosen_source": "yahoo",
                    "reason": "more recent",
                },
                "source": {"price": "yahoo"},
            }
        ],
        "citations": {},
    }
    out = agent._augment_websearch_contract(reply)
    conflicts = out.get("source_conflicts")
    assert isinstance(conflicts, list)
    assert conflicts
    assert conflicts[0].get("chosen_source") == "yahoo"
