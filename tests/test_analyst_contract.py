"""Analyst contract tests for structured outputs and confidence gating."""

from datetime import date, timedelta

from a2a.message_bus import InMemoryMessageBus
from agents.analyst_agent import AnalystAgent


def test_analyst_contract_has_required_fields() -> None:
    bus = InMemoryMessageBus()
    agent = AnalystAgent("analyst", bus, mcp_client=None)
    ts = f"{date.today().isoformat()}T10:00:00Z"
    out = agent.analyze({"query": "thesis"}, {"price": 100.0, "timestamp": ts})
    assert isinstance(out, dict)
    for key in ("confidence", "risk_factors", "scenario_outcomes", "key_metrics", "limitations", "reasoning_trace"):
        assert key in out
    assert isinstance(out.get("scenario_outcomes"), list)
    assert isinstance(out.get("key_metrics"), dict)


def test_analyst_confidence_degrades_without_market_price() -> None:
    bus = InMemoryMessageBus()
    agent = AnalystAgent("analyst", bus, mcp_client=None)
    ts = f"{date.today().isoformat()}T10:00:00Z"
    no_price = agent.analyze({"query": "thesis"}, {"timestamp": ts})
    with_price = agent.analyze({"query": "thesis"}, {"price": 101.0, "timestamp": ts})
    assert (no_price.get("confidence") or 0) < (with_price.get("confidence") or 0)


def test_analyst_confidence_degrades_when_timestamp_stale() -> None:
    bus = InMemoryMessageBus()
    agent = AnalystAgent("analyst", bus, mcp_client=None)
    fresh_ts = f"{date.today().isoformat()}T10:00:00Z"
    stale_ts = f"{(date.today() - timedelta(days=30)).isoformat()}T00:00:00Z"
    fresh = agent.analyze({"query": "thesis"}, {"price": 101.0, "timestamp": fresh_ts})
    stale = agent.analyze({"query": "thesis"}, {"price": 101.0, "timestamp": stale_ts})
    assert (stale.get("confidence") or 0) < (fresh.get("confidence") or 0)


def test_analyst_can_reach_recommendation_threshold_on_good_data() -> None:
    class _OkMcp:
        def call_tool(self, tool: str, payload: dict):
            return {"rsi": 55.0}

    bus = InMemoryMessageBus()
    agent = AnalystAgent("analyst", bus, mcp_client=_OkMcp())
    ts = f"{date.today().isoformat()}T10:00:00Z"
    out = agent.analyze({"query": "thesis"}, {"price": 101.0, "timestamp": ts})
    assert (out.get("confidence") or 0) >= 0.75
