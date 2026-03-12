# MCP Server (FastMCP)

OpenFund-AI exposes all tools through a single **MCP server** (FastMCP over stdio). The server is implemented in **one module**: `openfund_mcp/mcp_server.py`, which provides both the **FastMCP** stdio app (for production and external clients) and **MCPServer** (for in-process tests). Both the OpenFund API/agents and external MCP clients (e.g. Claude Desktop) use this server. Run it with `python -m openfund_mcp`.

## Running the server

From the project root:

```bash
python -m openfund_mcp
```

The server runs over **stdio**: it reads JSON-RPC messages from stdin and writes responses to stdout. It does not open a network port. External clients and the OpenFund API both run this process and communicate with it via stdio.

## Internal usage (OpenFund API)

When you start the API (`python main.py --serve` or `./scripts/run.sh`), the app creates an **MCPClient** that spawns the MCP server as a subprocess and connects to it over stdio. No extra step is required: the same server is used automatically for all tool calls (vector, SQL, KG, market, analyst, file, capabilities).

Configuration (see `config/config.py`):

- `MCP_SERVER_COMMAND` — command to run (default: `python`)
- `MCP_SERVER_ARGS` — comma-separated args (default: `-m,openfund_mcp`)
- `MCP_SERVER_CWD` — working directory (default: project root when empty)

## External usage (e.g. Claude Desktop)

To use OpenFund tools from Claude Desktop or another MCP client, configure the client to start the server with stdio.

**Example Claude Desktop config** (add to your Claude Desktop MCP config file):

```json
{
  "mcpServers": {
    "openfund": {
      "command": "python",
      "args": ["-m", "openfund_mcp"],
      "cwd": "/path/to/openFund AI"
    }
  }
}
```

Replace `"/path/to/openFund AI"` with the absolute path to the OpenFund-AI project root. Ensure the environment has the project’s dependencies installed (`pip install -e .` or `pip install openfund-ai`) and any required env vars (e.g. `MILVUS_URI`, `NEO4J_URI`, `DATABASE_URL`, API keys) so the tools can reach backends.

## Tool list

Tool names and payloads are documented in [agent-tools-reference.md](agent-tools-reference.md). The server exposes the same tools as used by the API (vector_tool, sql_tool, kg_tool, market_tool, analyst_tool, file_tool, get_capabilities, etc.).
