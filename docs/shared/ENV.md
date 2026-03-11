# Environment Variables

Generated from `.env.example` and `config/config.py`. Copy `.env.example` to `.env` and set values as needed. The app loads `.env` automatically via `load_config()` (python-dotenv).

<!-- AUTO-GENERATED: from .env.example and config/config.py -->

## Reference

| Variable | Required | Description | Example / values |
|----------|----------|-------------|------------------|
| **LLM** | | | |
| `LLM_API_KEY` | Yes (for live API) | Provider API key | `your_api_key` |
| `LLM_MODEL` | No | Model name (default: gpt-4o-mini) | `gpt-4o-mini`, `deepseek-chat` |
| `LLM_BASE_URL` | No | Base URL for OpenAI-compatible API (e.g. DeepSeek) | `https://api.deepseek.com` |
| **Persistence** | | | |
| `MEMORY_STORE_PATH` | No | Root dir for conversation persistence (default: memory) | `memory` |
| `E2E_TIMEOUT_SECONDS` | No | E2E timeout in seconds (default: 120) | `30`, `120` |
| `INTERACTION_LOG` | No | Log every significant function during user interaction (1/true/yes/on) | `1`, `true` |
| **PostgreSQL (sql_tool)** | | | |
| `DATABASE_URL` | No | PostgreSQL connection URL | `postgresql://user@localhost:5432/openfund` |
| **Neo4j (kg_tool)** | | | |
| `NEO4J_URI` | No | Neo4j connection URI | `bolt://localhost:7687` |
| `NEO4J_USER` | No | Neo4j user (default: neo4j) | `neo4j` |
| `NEO4J_PASSWORD` | No | Neo4j password | `your_password` |
| `NEO4J_DATABASE` | No | Neo4j database name | `neo4j` |
| **Milvus (vector_tool)** | | | |
| `MILVUS_URI` | No | Milvus connection | `http://localhost:19530` |
| `MILVUS_COLLECTION` | No | Collection name for fund documents | `openfund_docs` |
| `EMBEDDING_MODEL` | No | Model name for embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_DIM` | No | Embedding dimension (int) | `384` |
| **Market / web (market_tool)** | | | |
| `TAVILY_API_KEY` | No | Tavily API key | |
| `YAHOO_BASE_URL` | No | Yahoo API base URL | |
| `ALPHA_VANTAGE_API_KEY` | No | Required when using Alpha Vantage | `your_av_key` |
| `FINNHUB_API_KEY` | No | Required when MCP_MARKET_VENDOR=finnhub | `your_finnhub_key` |
| `MCP_MARKET_VENDOR` | No | alpha_vantage (default) or finnhub | `alpha_vantage`, `finnhub` |
| `MCP_INDICATOR_VENDOR` | No | Default alpha_vantage | `alpha_vantage` |
| `MCP_DATA_CACHE_DIR` | No | Cache dir for OHLCV | |
| **Analyst API** | | | |
| `ANALYST_API_URL` | No | Custom Analyst API base URL | `http://localhost:5001` |
| `ANALYST_API_KEY` | No | Optional auth for Analyst API | |
| **MCP server** | | | |
| `MCP_SERVER_ENDPOINT` | No | MCP server endpoint (if using remote MCP) | |
| `MCP_SERVER_COMMAND` | No | Command to run MCP server (default: python) | `python` |
| `MCP_SERVER_ARGS` | No | Comma-separated args (default: -m,openfund_mcp) | `-m,openfund_mcp` |
| `MCP_SERVER_CWD` | No | Working directory for MCP subprocess | |
| **File tool** | | | |
| `MCP_FILE_BASE_DIR` | No | When set, read_file only allows paths under this dir | `/path/to/allowed/files` |
| **Thresholds** | | | |
| `PLANNER_SUFFICIENCY_THRESHOLD` | No | Default 0.6 (reserved) | `0.6` |
| `ANALYST_CONFIDENCE_THRESHOLD` | No | Default 0.6 | `0.6` |
| `RESPONDER_CONFIDENCE_THRESHOLD` | No | Default 0.75 (reserved) | `0.75` |
| `MAX_RESEARCH_ROUNDS` | No | Max refinement rounds (default: 2) | `2` |

<!-- END AUTO-GENERATED -->
