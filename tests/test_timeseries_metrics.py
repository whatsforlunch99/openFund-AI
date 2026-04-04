"""Tests for util.timeseries_metrics and util.answer_coverage."""

from datetime import date, timedelta

from util.answer_coverage import (
    has_structured_timeseries_metrics,
    normalized_fund_price_line,
    strong_equity_evidence_for_sufficiency,
)
from util.timeseries_metrics import (
    attach_structured_timeseries_metrics,
    compute_timeseries_metrics,
    extract_date_close_rows,
    format_timeseries_metrics_for_final_response,
    format_timeseries_metrics_for_sufficiency_chunk,
    structured_metrics_from_sql_payload,
)


def test_extract_and_metrics_simple_up_trend() -> None:
    base = date(2020, 1, 2)
    rows = [
        {"date": (base + timedelta(days=i)).isoformat(), "level_close": 100.0 + float(i)}
        for i in range(10)
    ]
    pairs = extract_date_close_rows(rows)
    assert len(pairs) == 10
    m = compute_timeseries_metrics(pairs)
    assert m["total_return_fraction"] > 0
    assert m["cagr_fraction"] > 0
    assert m["max_drawdown_fraction"] <= 0


def test_structured_metrics_from_sql_payload() -> None:
    sql = {
        "data": [
            {"symbol": "NVDA", "date": "2020-01-02", "level_close": 10.0},
            {"symbol": "NVDA", "date": "2021-01-04", "level_close": 20.0},
        ],
        "row_count": 2,
    }
    m = structured_metrics_from_sql_payload(sql)
    assert m is not None
    assert m.get("symbol") == "NVDA"


def test_attach_structured_timeseries_metrics() -> None:
    reply = {
        "sql": {
            "data": [
                {"date": "2020-01-02", "level_close": 50.0},
                {"date": "2021-01-04", "level_close": 55.0},
            ],
            "row_count": 2,
        }
    }
    attach_structured_timeseries_metrics(reply)
    assert "structured_timeseries_metrics" in reply


def test_strong_equity_evidence() -> None:
    collected = {
        "websearcher": {"normalized_fund": [{"symbol": "NVDA", "price": 100.0}]},
        "librarian": {"sql": {"row_count": 10, "data": [{"a": 1}] * 10}},
    }
    assert strong_equity_evidence_for_sufficiency(collected)


def test_has_structured_timeseries_metrics() -> None:
    assert has_structured_timeseries_metrics(
        {
            "structured_timeseries_metrics": {
                "span_first_date": "2020-01-01",
                "span_last_date": "2021-01-01",
            }
        }
    )
    assert not has_structured_timeseries_metrics(
        {"structured_timeseries_metrics": {"span_first_date": "2020-01-01"}}
    )
    assert not has_structured_timeseries_metrics({})


def test_normalized_fund_price_line() -> None:
    line = normalized_fund_price_line(
        {"normalized_fund": [{"symbol": "X", "price": 1.0, "source": {"price": "yahoo"}}]}
    )
    assert "X" in line and "$1.00" in line


def test_format_timeseries_metrics_helpers() -> None:
    stm = {
        "span_first_date": "2020-01-02",
        "span_last_date": "2021-01-04",
        "span_trading_days": 10,
        "total_return_fraction": 0.1,
        "cagr_fraction": 0.05,
        "max_drawdown_fraction": -0.02,
        "symbol": "NVDA",
    }
    assert "NVDA" in format_timeseries_metrics_for_final_response(stm)
    assert "structured_timeseries_metrics:" in format_timeseries_metrics_for_sufficiency_chunk(stm)


def test_alpha_vantage_cooldown_active_returns_bool() -> None:
    from openfund_mcp.tools.market_tool import alpha_vantage_cooldown_active

    assert isinstance(alpha_vantage_cooldown_active(), bool)
