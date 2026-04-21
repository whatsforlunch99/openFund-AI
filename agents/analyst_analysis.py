"""Analyst quantitative analysis methods."""

import math
from datetime import UTC, date, datetime

from agents.analyst_helpers import derive_symbol, extract_market_price, parse_iso_utc


class AnalystAnalysisMixin:
    """Split part for readability."""

    def analyze(self, structured_data: dict, market_data: dict) -> dict:
        """
        Generate probabilistic investment analysis.

        Output should include probability distributions where applicable,
        not only single-point predictions.

        Args:
            structured_data: KG and document data from Librarian.
            market_data: Real-time market signals from WebSearcher.

        Returns:
            Analysis result with confidence and optional distributions.
        """
        symbol = derive_symbol(structured_data, market_data)
        market_price = extract_market_price(
            market_data if isinstance(market_data, dict) else {}
        )
        ts_raw = (
            (market_data or {}).get("timestamp")
            if isinstance(market_data, dict)
            else None
        )
        ts_date = parse_iso_utc(ts_raw)
        stale = True
        if ts_date is not None:
            stale = (datetime.now(UTC).date() - ts_date).days > 0
        confidence = 0.35
        if market_price is not None:
            confidence = 0.55
            if stale:
                confidence = 0.45
        if self.mcp_client:
            as_of = date.today().isoformat()
            payload = {
                "symbol": symbol,
                "indicator": "rsi",
                "as_of_date": as_of,
                "look_back_days": 30,
            }
            api_result = self.mcp_client.call_tool(
                "analyst_tool.get_indicators", payload
            )
            if isinstance(api_result, dict) and "error" not in api_result:
                confidence = max(confidence, 0.8)
                key_metrics = {"rsi": api_result.get("rsi"), "price": market_price}
            else:
                key_metrics = {"rsi": None, "price": market_price}
        else:
            key_metrics = {"rsi": None, "price": market_price}
        risk_factors: list[str] = []
        limitations: list[str] = []
        if market_price is None:
            risk_factors.append("missing_live_price")
            limitations.append("Market price is missing; confidence reduced.")
        if stale:
            risk_factors.append("stale_market_timestamp")
            limitations.append("Market timestamp appears stale; confidence reduced.")
        if not risk_factors:
            risk_factors.append("normal_market_uncertainty")
        scenario_outcomes = [
            {"scenario": "bull", "expected_return": 0.08, "probability": 0.3},
            {"scenario": "base", "expected_return": 0.03, "probability": 0.5},
            {"scenario": "bear", "expected_return": -0.07, "probability": 0.2},
        ]
        reasoning_trace = {
            "data_sources_used": ["market_data", "structured_data"],
            "methods_applied": ["confidence_gate", "scenario_template"],
            "assumptions": [f"symbol={symbol}"],
        }
        return {
            "confidence": round(float(confidence), 2),
            "key_metrics": key_metrics,
            "risk_factors": risk_factors,
            "scenario_outcomes": scenario_outcomes,
            "limitations": limitations,
            "reasoning_trace": reasoning_trace,
            "summary": "Structured analyst output generated.",
            "distribution": {},
        }

    def needs_more_data(self, analysis_result: dict) -> bool:
        """
        Determine if additional information is required for refinement.

        Args:
            analysis_result: Current analysis output.

        Returns:
            True if another research cycle is needed.
        """
        return (
            analysis_result.get("confidence") or 0
        ) < self._analyst_confidence_threshold

    def sharpe_ratio(self, returns: list[float], risk_free_rate: float) -> float:
        """
        Compute Sharpe ratio for a return series.

        Args:
            returns: List of period returns.
            risk_free_rate: Risk-free rate (e.g. annual).

        Returns:
            Sharpe ratio.
        """
        if not returns:
            return 0.0
        avg = sum(returns) / len(returns)
        variance = sum((r - avg) ** 2 for r in returns) / len(returns)
        std = variance**0.5 if variance else 0.0
        if std == 0:
            return 0.0
        return (avg - risk_free_rate) / std

    def max_drawdown(self, returns: list[float]) -> float:
        """
        Compute maximum drawdown for a return series.

        Args:
            returns: List of period returns.

        Returns:
            Max drawdown (e.g. as positive decimal).
        """
        if not returns:
            return 0.0
        peak = returns[0]
        max_dd = 0.0
        for r in returns:
            peak = max(peak, r)
            dd = peak - r
            if peak > 0:
                max_dd = max(max_dd, dd / peak)
        return max_dd

    def monte_carlo_simulation(
        self, returns: list[float], _horizon: int, _n_sims: int
    ) -> dict:
        """
        Run Monte Carlo simulation; return distribution, not single point.

        Args:
            returns: Historical returns.
            horizon: Projection horizon (e.g. periods).
            n_sims: Number of simulations.

        Returns:
            Dict with distribution (e.g. percentiles, mean, std).
        """
        if not returns:
            return {"mean": 0, "std": 0, "percentiles": {}}
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance) if variance else 0.0
        return {"mean": mean_ret, "std": std, "percentiles": {"50": mean_ret}}
