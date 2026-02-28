#!/usr/bin/env python3
"""Test script: user input -> planner decomposition -> A2A REQUEST content per agent.

Shows the user query, the decomposed steps (agent, action, sub-query), and the exact
content the planner would send to each agent via the message bus (REQUEST performative).

Usage:
  python scripts/test_llm_planner.py "should I invest in AAPL?"
  echo "what is the stock price of NVDA?" | python scripts/test_llm_planner.py

Requires: .env with LLM_API_KEY set for live decomposition; otherwise uses static
three-step decomposition (librarian, websearcher, analyst) with the same query.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test LLM planner: show user input, decomposed steps, and A2A REQUEST content."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="User query (or read from stdin if omitted)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print full content dicts as JSON",
    )
    args = parser.parse_args()

    query = args.query
    if query is None:
        query = sys.stdin.read().strip()
    if not query:
        print("No query provided. Pass as argument or stdin.", file=sys.stderr)
        return 1

    # Load config (reads .env)
    from config.config import load_config

    config = load_config()

    # LLM client: live if API key set, else static (fixed three steps)
    llm_client = None
    if config.llm_api_key and config.llm_api_key.strip():
        try:
            from llm.factory import get_llm_client

            llm_client = get_llm_client(config)
            print("Using live LLM for decomposition (set LLM_API_KEY in .env).\n")
        except (ValueError, ImportError) as e:
            print(f"LLM client failed ({e}). Using static decomposition.\n", file=sys.stderr)
            from llm.static_client import StaticLLMClient

            llm_client = StaticLLMClient()
    else:
        from llm.static_client import StaticLLMClient

        llm_client = StaticLLMClient()
        print("No LLM_API_KEY set. Using static decomposition (librarian, websearcher, analyst).\n")

    # Planner: only decompose_task + create_research_request (no bus send)
    from a2a.message_bus import InMemoryMessageBus
    from agents.planner_agent import PlannerAgent

    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    planner = PlannerAgent(
        name="planner",
        message_bus=bus,
        llm_client=llm_client,
        conversation_manager=None,
    )

    steps = planner.decompose_task(query)
    if not steps:
        print("Planner returned no steps.", file=sys.stderr)
        return 1

    # --- Output ---
    print("=" * 60)
    print("USER INPUT")
    print("=" * 60)
    print(query)
    print()

    print("=" * 60)
    print("DECOMPOSED STEPS (what the planner produced)")
    print("=" * 60)
    for i, s in enumerate(steps, 1):
        q = s.params.get("query", query)
        print(f"  {i}. agent={s.agent!r}  action={s.action!r}")
        print(f"     query: {q}")
        if args.verbose and s.params:
            extra = {k: v for k, v in s.params.items() if k != "query"}
            if extra:
                print(f"     params: {json.dumps(extra, indent=6)}")
    print()

    print("=" * 60)
    print("A2A REQUEST CONTENT (what each agent receives via message bus)")
    print("=" * 60)
    for step in steps:
        req = planner.create_research_request(query, step)
        print(f"  -> {step.agent}")
        if args.verbose:
            print(json.dumps(req.content, indent=4))
        else:
            q = req.content.get("query", "")
            action = req.content.get("action", "")
            print(f"     query: {q}")
            print(f"     action: {action}")
            others = {k: v for k, v in req.content.items() if k not in ("query", "action")}
            if others:
                print(f"     other: {others}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
