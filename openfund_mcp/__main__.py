"""Run the FastMCP server over stdio. Usage: python -m openfund_mcp"""

import os

# Load .env from project root so tools (e.g. market_tool) see ALPHA_VANTAGE_API_KEY
# when this process is spawned as a subprocess (parent may pass env; loading here is a fallback).
try:
    from dotenv import load_dotenv
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_root, ".env"))
except ImportError:
    pass

from openfund_mcp.fastmcp_server import run

if __name__ == "__main__":
    run()
