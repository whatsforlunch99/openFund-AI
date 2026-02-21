"""Quantitative analysis via custom Analyst API (MCP tool)."""


def run_analysis(payload: dict) -> dict:
    """
    POST to custom Analyst API (e.g. Sharpe, max_drawdown, Monte Carlo).

    Payload and response schema are defined by the custom API.

    Args:
        payload: Request body (e.g. returns, horizon, n_sims).

    Returns:
        Response dict (e.g. metrics, distribution). Config: ANALYST_API_URL, optional ANALYST_API_KEY.
    """
    raise NotImplementedError
