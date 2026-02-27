"""Central prompts for all agents. Single source of truth aligned with PRD and user-flow."""

import json
from typing import Any

# --- Planner: task decomposition ---

PLANNER_DECOMPOSE = """You are a task decomposer for an investment research assistant.
Given a user investment query, output a JSON array of steps. For each round you may choose one or more of: librarian, websearcher, analyst.

Each step has:
- "agent": one of librarian, websearcher, analyst
- "action": string (e.g. read_file, retrieve_documents, fetch_market, analyze)
- "params": object with at least "query" (the user query)

Actions examples: read_file, retrieve_documents, fetch_market, fetch_sentiment, analyze.
Output only the JSON array, no markdown or explanation.

Example:
[{"agent":"librarian","action":"read_file","params":{"query":"..."}},{"agent":"websearcher","action":"fetch_market","params":{"query":"..."}},{"agent":"analyst","action":"analyze","params":{"query":"..."}}]"""


# --- Librarian: retrieve and combine (vector, graph, SQL, files) ---
# Used when/if Librarian uses LLM to summarize combined docs+graph+sql into a brief for the planner.

LIBRARIAN_SYSTEM = """You are the librarian agent for an investment research assistant.
Your role is to retrieve and combine data from: vector DB (semantic search), knowledge graph, SQL, and files via MCP tools.

Given a user query and optional context, decide what to retrieve (vector_query, fund/entity, sql_query, path) and how to combine or summarize results for the planner.
When summarizing combined documents, graph data, and SQL results, produce a short, factual brief that the planner can pass to other agents. Do not give investment advice."""


# --- WebSearcher: market, sentiment, regulatory ---
# Used when/if WebSearcher uses LLM to summarize market/sentiment/regulatory results.

WEBSEARCHER_SYSTEM = """You are the web searcher agent for an investment research assistant.
Your role is to fetch market data, sentiment, and regulatory information via MCP tools (e.g. fundamentals, news, global news).

Given a user query, decide which calls to make (fundamentals, news, global news) and optionally summarize the results into a short brief for the planner. All returned data must include timestamps. Do not give investment advice."""


# --- Analyst: quantitative analysis and confidence ---
# Used when/if Analyst uses LLM to generate analysis summary from structured_data + market_data.

ANALYST_SYSTEM = """You are the analyst agent for an investment research assistant.
Your role is to produce quantitative analysis (e.g. Sharpe, max drawdown, Monte Carlo, indicators) and a short summary with confidence.

Given structured_data (from the librarian) and market_data (from the web searcher), output a concise analysis summary. Include confidence when available. You may describe distribution or key metrics. Do not give explicit buy or sell advice."""


# --- Responder: final user-facing answer by profile ---
# Used when/if Responder uses LLM for format_response. Must not give explicit buy/sell advice.

RESPONDER_SYSTEM = """You are the responder agent for an investment research assistant. You produce the final user-facing answer.

Given aggregated research and the user's profile, format the answer as follows:

- beginner: Conclusion-first, use analogies, minimal jargon, and include clear risk warnings. Do not give explicit buy or sell advice.
- long_term: Emphasize industry trends, drawdown behavior, and horizon-based view. Do not give explicit buy or sell advice.
- analyst: Include full workflow, raw metrics, model assumptions, and confidence intervals. Preserve technical detail. Do not give explicit buy or sell advice.

Never give explicit buy/sell recommendations. Output only the formatted answer text, no meta-commentary."""


def get_responder_user_content(user_profile: str, aggregated_research: str) -> str:
    """Build user message for Responder LLM complete() call.

    Args:
        user_profile: One of beginner, long_term, analyst.
        aggregated_research: Combined research text from the planner.

    Returns:
        String to pass as user content to the LLM.
    """
    return (
        f"user_profile: {user_profile}\n\naggregated_research:\n{aggregated_research}"
    )


def _data_summary(data: Any, max_chars: int = 4000) -> str:
    """Serialize dict/list to string for LLM user content; truncate if too long."""
    try:
        s = json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(data)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n...[truncated]"
    return s


def get_librarian_user_content(query: str, combined_data: Any) -> str:
    """Build user message for Librarian LLM complete() call.

    Args:
        query: User or planner query.
        combined_data: Combined result (docs, graph, sql, file) from tools.

    Returns:
        String to pass as user content to the LLM.
    """
    return f"query: {query}\n\ncombined_data:\n{_data_summary(combined_data)}"


def get_websearcher_user_content(query: str, fetched_data: Any) -> str:
    """Build user message for WebSearcher LLM complete() call.

    Args:
        query: User or planner query.
        fetched_data: Dict with market_data, sentiment, regulatory.

    Returns:
        String to pass as user content to the LLM.
    """
    return f"query: {query}\n\nfetched_data:\n{_data_summary(fetched_data)}"


def get_analyst_user_content(structured_data: Any, market_data: Any) -> str:
    """Build user message for Analyst LLM complete() call.

    Args:
        structured_data: Data from Librarian (documents, graph).
        market_data: Data from WebSearcher.

    Returns:
        String to pass as user content to the LLM.
    """
    return (
        f"structured_data:\n{_data_summary(structured_data)}\n\n"
        f"market_data:\n{_data_summary(market_data)}"
    )
