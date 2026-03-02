"""Demo: run the full stack with real data, real MCP calls, and real LLM from .env.

Default entry: python -m demo (starts API, then interactive chat). Optionally use
--ensure-data to load datasets/funds into PostgreSQL/Neo4j before starting.

Package contents:
- __main__: Single-command entry (python -m demo); loads .env, optionally ensures fund data, starts API and chat.
- demo_chat: Interactive CLI (python -m demo.demo_chat --base-url URL).
- demo_client, demo_data: Legacy stubs for testing; not used by python -m demo.
"""
