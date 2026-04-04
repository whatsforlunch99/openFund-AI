"""Analyst agent: enforce planner-resolved symbol on get_indicators payloads."""

from __future__ import annotations

from agents.analyst_agent import apply_resolved_symbol_to_analyst_calls


def test_apply_resolved_symbol_overrides_mismatch() -> None:
    sr = {
        "status": "resolved",
        "listings": [{"symbol_yahoo": "AAPL", "symbol_compact": "AAPL"}],
    }
    calls = [
        {
            "tool": "analyst_tool.get_indicators",
            "payload": {"symbol": "NVDA", "indicator": "rsi"},
        }
    ]
    out = apply_resolved_symbol_to_analyst_calls(calls, sr)
    assert out[0]["payload"]["symbol"] == "AAPL"


def test_apply_resolved_symbol_noop_when_unresolved() -> None:
    calls = [
        {"tool": "analyst_tool.get_indicators", "payload": {"symbol": "NVDA"}},
    ]
    out = apply_resolved_symbol_to_analyst_calls(calls, {"status": "ambiguous"})
    assert out[0]["payload"]["symbol"] == "NVDA"


def test_apply_resolved_symbol_injects_symbol_when_missing() -> None:
    sr = {
        "status": "resolved",
        "listings": [{"symbol_compact": "MSFT"}],
    }
    calls = [{"tool": "analyst_tool.get_indicators", "payload": {"indicator": "rsi"}}]
    out = apply_resolved_symbol_to_analyst_calls(calls, sr)
    assert out[0]["payload"]["symbol"] == "MSFT"
