# Data Manager Agent Design Document

Data management agent responsible for fund/stock data collection, storage, and distribution. Uses MCP tool chain to manage the data lifecycle.

---

## Overview

### Responsibilities

1. **Data Collection**: Call MCP market_tool and analyst_tool to fetch fund/stock data, save as structured files locally
2. **Data Distribution**: Read local data files and distribute content to three databases based on data characteristics:
   - **PostgreSQL** — Structured/tabular data (fundamentals, financial statements, trading history)
   - **Neo4j** — Relationship/graph data (company-sector, company-officers, holdings)
   - **Milvus** — Text/vector data (news, report summaries, company descriptions)

### Design Principles

- **Idempotency**: Repeated execution of the same task does not produce duplicate data (uses UPSERT/MERGE)
- **Traceability**: Each data record carries `source` and `collected_at` metadata
- **Fault Tolerance**: Single data source failure does not affect other sources
- **Extensibility**: New data types can be added via configuration without modifying core logic

---

## Integration with Existing System

### Position in Overall Architecture

DataManagerAgent is a **background data infrastructure component**, not part of the real-time user query flow. It prepares and maintains data that other agents (Librarian, WebSearcher, Analyst) consume.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    User Query Flow (Real-time)                       │
│  POST /chat → SafetyGateway → Planner → Librarian/WebSearcher       │
│                                         /Analyst → Responder         │
│                                              │                       │
│                                              │ read from             │
│                                              ▼                       │
│                                    ┌─────────────────┐               │
│                                    │ PostgreSQL      │               │
│                                    │ Neo4j           │               │
│                                    │ Milvus          │               │
│                                    └─────────────────┘               │
│                                              ▲                       │
│                                              │ write to              │
└──────────────────────────────────────────────┼───────────────────────┘
                                               │
┌──────────────────────────────────────────────┼───────────────────────┐
│               DataManagerAgent (Background/Scheduled)                │
│  CLI/Scheduler/Planner REQUEST → Collect → Distribute                │
└──────────────────────────────────────────────────────────────────────┘
```

### Relationship with Existing `data/` Module

The existing `data/` module provides basic CLI commands for data operations. DataManagerAgent extends this with agent-based orchestration:

| Existing Module | DataManagerAgent | Relationship |
|-----------------|------------------|--------------|
| `data/populate.py` | `DataDistributor` | DataDistributor replaces populate.py logic with configurable, multi-source distribution |
| `data/cli.py` | Agent message protocol | CLI remains as direct access; agent adds A2A integration |
| `mcp/tools/*_tool.py` | DataCollector/Distributor | Agent calls existing MCP tools; no duplication |

**Migration path:**
1. DataManagerAgent reuses `mcp/tools/sql_tool.py`, `kg_tool.py`, `vector_tool.py` for writes
2. `data/populate.py` can be refactored to call DataDistributor internally
3. CLI (`python -m data`) preserved for direct operations; agent for orchestrated/scheduled tasks

### Trigger Mechanisms

DataManagerAgent supports three trigger modes:

| Mode | Trigger | Use Case |
|------|---------|----------|
| **CLI** | `python -m data_manager collect --symbols NVDA` | Manual one-off collection |
| **Scheduled** | Cron/scheduler sends REQUEST to agent | Daily/weekly batch updates |
| **On-demand** | Planner sends REQUEST when data is stale | Real-time data refresh during query |

#### CLI Entry Point

```bash
# Collect data for symbols
python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15

# Distribute collected data to databases
python -m data_manager distribute --symbol NVDA --date 2024-01-15

# Distribute all pending files
python -m data_manager distribute --all

# Query data status
python -m data_manager status --symbol NVDA
```

#### Planner Integration (On-demand)

When Planner detects stale data during query processing, it can send a REQUEST to DataManagerAgent:

```python
# Planner sends data refresh request
msg = ACLMessage(
    performative="request",
    sender="planner",
    receiver="data_manager",
    content={
        "action": "collect",
        "symbols": ["NVDA"],
        "as_of_date": "2024-01-15",
        "tasks": ["stock_data", "news"],  # specific tasks only
    }
)
message_bus.send(msg)

# Planner waits for INFORM or continues with cached data on timeout
```

#### Scheduled Execution

For production, use external scheduler (cron, Airflow, etc.) to trigger collection:

```bash
# Example cron job (daily at 6:00 AM)
0 6 * * * cd /path/to/openfund-ai && python -m data_manager collect --symbols-file watchlist.txt --date $(date +%Y-%m-%d)
```

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DataManagerAgent                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐         ┌──────────────────┐              │
│  │  DataCollector   │         │  DataDistributor │              │
│  │                  │         │                  │              │
│  │  - fetch_stock   │ ──────▶ │  - classify      │              │
│  │  - fetch_fund    │  JSON   │  - route_to_db   │              │
│  │  - fetch_news    │  files  │  - transform     │              │
│  │  - fetch_indicators│       │                  │              │
│  └────────┬─────────┘         └────────┬─────────┘              │
│           │                            │                         │
│           ▼                            ▼                         │
│  ┌──────────────────┐         ┌──────────────────┐              │
│  │   MCP Tools      │         │   MCP Tools      │              │
│  │  (market_tool)   │         │  (sql/kg/vector) │              │
│  │  (analyst_tool)  │         │                  │              │
│  └──────────────────┘         └──────────────────┘              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
            │ PostgreSQL  │     │   Neo4j     │     │   Milvus    │
            │ (sql_tool)  │     │  (kg_tool)  │     │(vector_tool)│
            └─────────────┘     └─────────────┘     └─────────────┘
```

---

## Feature 1: Data Collection (DataCollector)

### Data Sources and MCP Tool Mapping

| Data Type | MCP Tool | Function | Output File Format |
|-----------|----------|----------|-------------------|
| Stock Quotes | market_tool | `get_stock_data_yf` / `_route_stock_data` | `{symbol}_ohlcv_{date}.json` |
| Company Fundamentals | market_tool | `get_fundamentals_yf` / `_route_fundamentals` | `{symbol}_fundamentals_{date}.json` |
| Balance Sheet | market_tool | `get_balance_sheet_yf` / `_route_balance_sheet` | `{symbol}_balance_sheet_{date}.json` |
| Cash Flow Statement | market_tool | `get_cashflow_yf` / `_route_cashflow` | `{symbol}_cashflow_{date}.json` |
| Income Statement | market_tool | `get_income_statement_yf` / `_route_income_statement` | `{symbol}_income_{date}.json` |
| Insider Transactions | market_tool | `get_insider_transactions_yf` / `_route_insider_transactions` | `{symbol}_insider_{date}.json` |
| Company News | market_tool | `get_news_yf` / `_route_news` | `{symbol}_news_{date}.json` |
| Global News | market_tool | `get_global_news_yf` / `_route_global_news` | `global_news_{date}.json` |
| Company Info | market_tool | `get_ticker_info` | `{symbol}_info_{date}.json` |
| Technical Indicators | analyst_tool | `get_indicators_yf` / `_route_indicators` | `{symbol}_indicators_{date}.json` |

### Data Collection Flow

```python
class DataCollector:
    """Collect data from MCP tools and save to local files."""

    def __init__(self, mcp_client: MCPClient, data_dir: str = "datasets/raw"):
        self.mcp_client = mcp_client
        self.data_dir = data_dir

    def collect_symbol(self, symbol: str, as_of_date: str) -> CollectionResult:
        """
        Collect all data for a single symbol.

        Args:
            symbol: Stock/fund ticker (e.g. "NVDA", "AAPL")
            as_of_date: Reference date (yyyy-mm-dd)

        Returns:
            CollectionResult: Collection result (success/failed file lists)
        """
        pass

    def collect_batch(self, symbols: list[str], as_of_date: str) -> BatchResult:
        """Batch collect data for multiple symbols."""
        pass
```

### Collection Task Configuration

```python
@dataclass
class CollectionTask:
    """Single collection task configuration."""
    task_type: str           # "stock_data" | "fundamentals" | "news" | "indicators" | ...
    tool_name: str           # MCP tool name (e.g. "market_tool.get_stock_data_yf")
    payload_builder: Callable[[str, str], dict]  # (symbol, as_of_date) -> payload
    output_filename: Callable[[str, str], str]   # (symbol, as_of_date) -> filename

# Predefined tasks
COLLECTION_TASKS = [
    CollectionTask(
        task_type="stock_data",
        tool_name="market_tool.get_stock_data",
        payload_builder=lambda s, d: {"symbol": s, "start_date": _days_ago(d, 365), "end_date": d},
        output_filename=lambda s, d: f"{s}_ohlcv_{d}.json",
    ),
    CollectionTask(
        task_type="fundamentals",
        tool_name="market_tool.get_fundamentals",
        payload_builder=lambda s, d: {"symbol": s},
        output_filename=lambda s, d: f"{s}_fundamentals_{d}.json",
    ),
    CollectionTask(
        task_type="news",
        tool_name="market_tool.get_news",
        payload_builder=lambda s, d: {"symbol": s, "limit": 50, "start_date": _days_ago(d, 30), "end_date": d},
        output_filename=lambda s, d: f"{s}_news_{d}.json",
    ),
    # ... more tasks
]
```

### Output File Format

Each collected file is JSON containing metadata and raw content:

```json
{
  "metadata": {
    "symbol": "NVDA",
    "task_type": "fundamentals",
    "collected_at": "2024-01-15T10:30:00Z",
    "source": "market_tool.get_fundamentals_yf",
    "as_of_date": "2024-01-15"
  },
  "content": {
    "Name": "NVIDIA Corporation",
    "Sector": "Technology",
    "Industry": "Semiconductors",
    "Market Cap": 1200000000000,
    "PE Ratio (TTM)": 65.3,
    ...
  }
}
```

### File Storage Structure

```
datasets/
├── raw/                          # Raw collected data
│   ├── NVDA/
│   │   ├── NVDA_ohlcv_2024-01-15.json
│   │   ├── NVDA_fundamentals_2024-01-15.json
│   │   ├── NVDA_balance_sheet_2024-01-15.json
│   │   ├── NVDA_cashflow_2024-01-15.json
│   │   ├── NVDA_income_2024-01-15.json
│   │   ├── NVDA_insider_2024-01-15.json
│   │   ├── NVDA_news_2024-01-15.json
│   │   ├── NVDA_info_2024-01-15.json
│   │   └── NVDA_indicators_2024-01-15.json
│   ├── AAPL/
│   │   └── ...
│   └── global/
│       └── global_news_2024-01-15.json
├── processed/                    # Marked after distribution
│   └── ...
└── failed/                       # Failure records
    └── ...
```

---

## Feature 2: Data Distribution (DataDistributor)

### Data Classification Rules

Route collected file content to different databases based on data characteristics:

| Data Characteristic | Target Database | Storage Form | Typical Data |
|--------------------|-----------------|--------------|--------------|
| **Structured Tables** | PostgreSQL | Rows/Columns | OHLCV, financial statements, fundamental metrics |
| **Entity Relationships** | Neo4j | Nodes/Edges | Company-sector, company-officers, holdings |
| **Text Content** | Milvus | Vectors | News headlines/summaries, company descriptions, reports |

### Classifier Design

```python
class DataClassifier:
    """Classify data to target databases based on type and content characteristics."""

    # Static classification mapping (by task_type)
    STATIC_ROUTING = {
        # PostgreSQL: Structured data
        "stock_data": "postgres",
        "balance_sheet": "postgres",
        "cashflow": "postgres",
        "income_statement": "postgres",
        "insider_transactions": "postgres",
        "indicators": "postgres",

        # Neo4j: Relationship data (extracted from fundamentals/info)
        "company_sector": "neo4j",
        "company_industry": "neo4j",
        "company_officers": "neo4j",

        # Milvus: Text data
        "news": "milvus",
        "company_description": "milvus",
    }

    # Mixed data types (write to multiple databases)
    MULTI_TARGET = {
        "fundamentals": ["postgres", "neo4j"],  # Metrics → PG, Relationships → Neo4j
        "info": ["postgres", "neo4j", "milvus"],  # Metrics → PG, Relationships → Neo4j, Description → Milvus
    }

    def classify(self, task_type: str, content: dict) -> list[str]:
        """
        Return list of target databases.

        Args:
            task_type: Data task type
            content: Data content

        Returns:
            List of target databases (e.g. ["postgres", "neo4j"])
        """
        pass
```

### Data Transformers

Each database requires different data formats:

```python
class DataTransformer:
    """Transform raw data to formats required by each database."""

    def to_postgres_rows(self, task_type: str, symbol: str, content: dict) -> list[dict]:
        """Transform to PostgreSQL row format."""
        pass

    def to_neo4j_nodes_edges(self, task_type: str, symbol: str, content: dict) -> tuple[list, list]:
        """Transform to Neo4j nodes and edges format."""
        pass

    def to_milvus_docs(self, task_type: str, symbol: str, content: dict) -> list[dict]:
        """Transform to Milvus document format (with content field for embedding)."""
        pass
```

### Database Schema Design

#### PostgreSQL Tables

```sql
-- Stock quotes table
CREATE TABLE IF NOT EXISTS stock_ohlcv (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(18, 4),
    high DECIMAL(18, 4),
    low DECIMAL(18, 4),
    close DECIMAL(18, 4),
    volume BIGINT,
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, trade_date)
);

-- Company fundamentals table
CREATE TABLE IF NOT EXISTS company_fundamentals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    as_of_date DATE NOT NULL,
    name VARCHAR(256),
    sector VARCHAR(128),
    industry VARCHAR(128),
    market_cap BIGINT,
    pe_ratio DECIMAL(10, 4),
    forward_pe DECIMAL(10, 4),
    peg_ratio DECIMAL(10, 4),
    price_to_book DECIMAL(10, 4),
    eps_ttm DECIMAL(10, 4),
    dividend_yield DECIMAL(10, 6),
    beta DECIMAL(10, 4),
    fifty_two_week_high DECIMAL(18, 4),
    fifty_two_week_low DECIMAL(18, 4),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, as_of_date)
);

-- Financial statements table (shared structure for balance sheet, cash flow, income)
CREATE TABLE IF NOT EXISTS financial_statements (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    statement_type VARCHAR(32) NOT NULL,  -- 'balance_sheet' | 'cashflow' | 'income'
    report_date DATE NOT NULL,
    fiscal_period VARCHAR(16),  -- 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'FY'
    line_item VARCHAR(128) NOT NULL,
    value DECIMAL(24, 4),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, statement_type, report_date, line_item)
);

-- Insider transactions table
CREATE TABLE IF NOT EXISTS insider_transactions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    insider_name VARCHAR(256),
    relation VARCHAR(128),
    transaction_type VARCHAR(64),
    shares BIGINT,
    value DECIMAL(18, 4),
    transaction_date DATE,
    collected_at TIMESTAMP DEFAULT NOW()
);

-- Technical indicators table
CREATE TABLE IF NOT EXISTS technical_indicators (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    indicator_name VARCHAR(64) NOT NULL,
    indicator_date DATE NOT NULL,
    value DECIMAL(18, 6),
    collected_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (symbol, indicator_name, indicator_date)
);
```

#### Neo4j Nodes and Edges

```cypher
-- Node types
(:Company {symbol, name, market_cap, exchange, currency, country, city, employees, website, collected_at})
(:Sector {name})
(:Industry {name})
(:Officer {name})

-- Edge types
(:Company)-[:IN_SECTOR]->(:Sector)
(:Company)-[:IN_INDUSTRY]->(:Industry)
(:Company)-[:HAS_OFFICER {title, total_pay}]->(:Officer)
(:Company)-[:COMPETES_WITH]->(:Company)
```

#### Milvus Collection Schema

```python
# Collection: fund_documents
fields = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384),
    FieldSchema(name="symbol", dtype=DataType.VARCHAR, max_length=32),
    FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=32),  # 'news' | 'description' | 'report'
    FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=256),
    FieldSchema(name="published_at", dtype=DataType.VARCHAR, max_length=32),
    FieldSchema(name="collected_at", dtype=DataType.VARCHAR, max_length=32),
]
```

### Distribution Flow

```python
class DataDistributor:
    """Distribute local data files to various databases."""

    def __init__(self, mcp_client: MCPClient, data_dir: str = "datasets/raw"):
        self.mcp_client = mcp_client
        self.data_dir = data_dir
        self.classifier = DataClassifier()
        self.transformer = DataTransformer()

    def distribute_file(self, filepath: str) -> DistributionResult:
        """
        Distribute a single data file to target databases.

        Args:
            filepath: Data file path

        Returns:
            DistributionResult: Distribution result
        """
        pass

    def distribute_symbol(self, symbol: str, as_of_date: str) -> BatchResult:
        """Distribute all data files for a symbol."""
        pass

    def distribute_pending(self) -> BatchResult:
        """Distribute all pending data files."""
        pass

    def _write_to_postgres(self, table: str, rows: list[dict]) -> int:
        """Write to PostgreSQL using sql_tool.run_query."""
        pass

    def _write_to_neo4j(self, nodes: list[dict], edges: list[dict]) -> int:
        """Write to Neo4j using kg_tool.query_graph / bulk_create_nodes."""
        pass

    def _write_to_milvus(self, docs: list[dict]) -> int:
        """Write to Milvus using vector_tool.index_documents / upsert_documents."""
        pass
```

---

## Agent Implementation

### Class Structure

```python
class DataManagerAgent(BaseAgent):
    """
    Data Manager Agent.

    Responsibilities:
    1. Handle data collection requests (collect from MCP tools and store locally)
    2. Handle data distribution requests (distribute from local files to three databases)
    3. Handle data status queries (collected/distributed/pending)

    Message types:
    - REQUEST: action="collect" | "distribute" | "status"
    - INFORM: Return operation results
    """

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        mcp_client: MCPClient,
        data_dir: str = "datasets",
    ):
        super().__init__(name, message_bus)
        self.collector = DataCollector(mcp_client, os.path.join(data_dir, "raw"))
        self.distributor = DataDistributor(mcp_client, os.path.join(data_dir, "raw"))
        self.datasets_dir = data_dir

    def handle_message(self, message: ACLMessage) -> None:
        """
        Handle messages.

        REQUEST content format:
        - {"action": "collect", "symbols": ["NVDA", "AAPL"], "as_of_date": "2024-01-15"}
        - {"action": "distribute", "symbols": ["NVDA"], "as_of_date": "2024-01-15"}
        - {"action": "distribute_pending"}
        - {"action": "status", "symbol": "NVDA"}
        """
        pass
```

### Message Protocol

#### Collection Request

```python
# REQUEST: Collect data
{
    "action": "collect",
    "symbols": ["NVDA", "AAPL"],    # List of symbols to collect
    "as_of_date": "2024-01-15",     # Reference date
    "tasks": ["stock_data", "fundamentals", "news"],  # Optional: specify task types
}

# INFORM: Collection result
{
    "action": "collect",
    "status": "completed",
    "results": {
        "NVDA": {
            "success": ["stock_data", "fundamentals", "news"],
            "failed": [],
            "files": [
                "datasets/raw/NVDA/NVDA_ohlcv_2024-01-15.json",
                "datasets/raw/NVDA/NVDA_fundamentals_2024-01-15.json",
                "datasets/raw/NVDA/NVDA_news_2024-01-15.json",
            ]
        },
        "AAPL": { ... }
    }
}
```

#### Distribution Request

```python
# REQUEST: Distribute data
{
    "action": "distribute",
    "symbols": ["NVDA"],            # List of symbols to distribute
    "as_of_date": "2024-01-15",     # Reference date
}

# INFORM: Distribution result
{
    "action": "distribute",
    "status": "completed",
    "results": {
        "NVDA": {
            "postgres": {"rows_written": 365, "tables": ["stock_ohlcv", "company_fundamentals"]},
            "neo4j": {"nodes_created": 3, "edges_created": 2},
            "milvus": {"docs_indexed": 15},
        }
    }
}
```

#### Status Query

```python
# REQUEST: Query status
{
    "action": "status",
    "symbol": "NVDA",               # Optional: specify symbol
}

# INFORM: Status result
{
    "action": "status",
    "symbol": "NVDA",
    "files": {
        "collected": [
            {"file": "NVDA_ohlcv_2024-01-15.json", "collected_at": "2024-01-15T10:30:00Z"},
            ...
        ],
        "distributed": [
            {"file": "NVDA_ohlcv_2024-01-15.json", "distributed_at": "2024-01-15T10:35:00Z"},
            ...
        ],
        "pending": [
            {"file": "NVDA_news_2024-01-15.json", "collected_at": "2024-01-15T10:30:00Z"},
        ]
    }
}
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATA_MANAGER_DIR` | Data storage root directory | `datasets/` |
| `DATA_MANAGER_BATCH_SIZE` | Batch write size | `100` |
| `DATA_MANAGER_RETRY_COUNT` | Failure retry count | `3` |

### Collection Configuration File

`config/collection_tasks.yaml`:

```yaml
tasks:
  - name: stock_data
    tool: market_tool.get_stock_data
    enabled: true
    schedule: daily
    params:
      look_back_days: 365

  - name: fundamentals
    tool: market_tool.get_fundamentals
    enabled: true
    schedule: weekly

  - name: news
    tool: market_tool.get_news
    enabled: true
    schedule: daily
    params:
      limit: 50
      look_back_days: 30

  - name: indicators
    tool: analyst_tool.get_indicators
    enabled: true
    schedule: daily
    params:
      indicators: [close_50_sma, close_200_sma, rsi, macd]
      look_back_days: 30
```

---

## Error Handling

### Collection Errors

| Error Type | Handling |
|------------|----------|
| MCP tool call failure | Retry N times, then log to `datasets/failed/`, continue to next task |
| Data format exception | Log raw response, mark as `invalid`, skip |
| Network timeout | Exponential backoff retry |

### Distribution Errors

| Error Type | Handling |
|------------|----------|
| Database connection failure | Retry, then mark as `pending`, wait for next distribution |
| Data transformation failure | Log error, skip file |
| Primary key conflict | Use UPSERT/MERGE to overwrite |

---

## Implementation Plan

### Phase Breakdown

| Phase | Content | Deliverable |
|-------|---------|-------------|
| **Phase 1** | DataCollector core + stock_data/fundamentals/news collection | Can collect 3 data types |
| **Phase 2** | DataDistributor core + PostgreSQL write | Structured data in database |
| **Phase 3** | Neo4j relationship extraction and write | Relationship data in database |
| **Phase 4** | Milvus text vectorization and write | Text data in database |
| **Phase 5** | Agent message protocol + full integration | Callable via A2A |

### File Structure

```
agents/
└── data_manager_agent.py       # Agent main class

data_manager/
├── __init__.py
├── collector.py                # DataCollector
├── distributor.py              # DataDistributor
├── classifier.py               # DataClassifier
├── transformer.py              # DataTransformer
├── tasks.py                    # CollectionTask definitions
└── schemas.py                  # Database schema definitions

config/
└── collection_tasks.yaml       # Collection task configuration
```

---

## Test Plan

### Unit Tests

| Test | Coverage |
|------|----------|
| `test_collector_fetch_stock_data` | DataCollector fetching stock data |
| `test_collector_batch` | DataCollector batch collection |
| `test_classifier_routing` | DataClassifier routing logic |
| `test_transformer_to_postgres` | DataTransformer PostgreSQL transformation |
| `test_transformer_to_neo4j` | DataTransformer Neo4j transformation |
| `test_transformer_to_milvus` | DataTransformer Milvus transformation |
| `test_distributor_postgres` | DataDistributor PostgreSQL write |
| `test_distributor_neo4j` | DataDistributor Neo4j write |
| `test_distributor_milvus` | DataDistributor Milvus write |

### Integration Tests

| Test | Coverage |
|------|----------|
| `test_collect_and_distribute_flow` | Complete collect-distribute flow |
| `test_agent_collect_request` | Agent handling collect request |
| `test_agent_distribute_request` | Agent handling distribute request |
| `test_idempotency` | Repeated execution idempotency |

### Run Commands

```bash
# Unit tests
pytest tests/test_data_manager.py -v

# Integration tests (requires backend services)
pytest tests/test_data_manager_integration.py -v --runslow

# List available collection tasks
python -m data_manager list
```

---

## Usage Examples

### Command Line

```bash
# Collect single symbol
python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15

# Distribute collected data
python -m data_manager distribute --symbol NVDA --date 2024-01-15

# Distribute all pending
python -m data_manager distribute --all

# Query status
python -m data_manager status --symbol NVDA

# List available tasks
python -m data_manager list
```

### API Call

```python
from agents.data_manager_agent import DataManagerAgent
from a2a.acl_message import ACLMessage

# Send collection request
msg = ACLMessage(
    performative="request",
    sender="planner",
    receiver="data_manager",
    content={
        "action": "collect",
        "symbols": ["NVDA", "AAPL"],
        "as_of_date": "2024-01-15",
    }
)
message_bus.send(msg)
```

---

## Fund Data Distribution Guide

This section describes how to import fund data from `datasets/funds/` into the three databases (PostgreSQL, Neo4j, Milvus).

### Prerequisites

#### 1. Start Database Services (Docker)

```bash
# Start PostgreSQL
docker run -d --name openfund-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=openfund \
  -p 5432:5432 \
  postgres:15-alpine

# Start Neo4j
docker run -d --name openfund-neo4j \
  -e NEO4J_AUTH=neo4j/password123 \
  -p 7474:7474 \
  -p 7687:7687 \
  neo4j:5-community

# Start Milvus (optional, for vector storage)
docker run -d --name openfund-milvus \
  -p 19530:19530 \
  -p 9091:9091 \
  milvusdb/milvus:v2.3.4 milvus run standalone
```

#### 2. Verify Containers Are Running

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected output:
```
NAMES               STATUS         PORTS
openfund-milvus     Up X minutes   0.0.0.0:19530->19530/tcp, 0.0.0.0:9091->9091/tcp
openfund-neo4j      Up X minutes   0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
openfund-postgres   Up X minutes   0.0.0.0:5432->5432/tcp
```

#### 3. Install Python Dependencies

```bash
pip install -e ".[backends]"
# Or install individually:
pip install psycopg2-binary neo4j pymilvus
```

### Distribution Commands

#### Set Environment Variables

**Linux/macOS (bash):**
```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/openfund"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password123"
export MILVUS_URI="http://localhost:19530"  # Optional
```

**Windows (PowerShell):**
```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/openfund"
$env:NEO4J_URI="bolt://localhost:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="password123"
$env:MILVUS_URI="http://localhost:19530"  # Optional
```

#### Distribute All Fund Files

```bash
python -m data_manager distribute-funds --funds-dir datasets/funds
```

This command processes all JSON files in `datasets/funds/` and distributes data to:
- **PostgreSQL**: Fund info, performance, risk metrics, holdings, sector allocation, fund flows
- **Neo4j**: Fund nodes, Company nodes, Sector nodes, HOLDS and INVESTS_IN_SECTOR relationships

#### Distribute a Single Fund File

```bash
python -m data_manager distribute-funds --file datasets/funds/top_etfs_2025.json
```

### Expected Output

```
Distributing all fund files from datasets/funds...

Results:
  Total files: 7
  Success: 7

Database writes:
  PostgreSQL rows: 463
  Neo4j nodes: 375
  Neo4j edges: 283
  Milvus docs: 0
```

### Data Written to Each Database

#### PostgreSQL Tables

| Table | Description |
|-------|-------------|
| `fund_info` | Fund name, symbol, expense ratio, total assets, investment style |
| `fund_performance` | 1/3/5/10-year annualized returns, YTD return |
| `fund_risk_metrics` | Beta, Sharpe ratio, standard deviation, max drawdown |
| `fund_holdings` | Top 10 holdings per fund with weights |
| `fund_sector_allocation` | Sector weights (Technology, Healthcare, etc.) |
| `fund_flows` | Quarterly/annual inflows and outflows |

**Sample Query:**
```sql
SELECT symbol, name, total_assets_billion, expense_ratio
FROM fund_info
ORDER BY total_assets_billion DESC
LIMIT 10;
```

#### Neo4j Graph

| Node Label | Description |
|------------|-------------|
| `Fund` | ETF or mutual fund (symbol, name, category, expense_ratio) |
| `Company` | Held companies (symbol, name) |
| `Sector` | Industry sectors (Technology, Healthcare, etc.) |

| Relationship | Description |
|--------------|-------------|
| `(Fund)-[:HOLDS]->(Company)` | Fund holds company stock with weight |
| `(Fund)-[:INVESTS_IN_SECTOR]->(Sector)` | Fund allocates to sector with weight |

**Sample Query:**
```cypher
// Find all companies held by VOO
MATCH (f:Fund {symbol: 'VOO'})-[r:HOLDS]->(c:Company)
RETURN c.symbol, c.name, r.weight
ORDER BY r.weight DESC
LIMIT 10;

// Find sector allocation for a fund
MATCH (f:Fund {symbol: 'QQQ'})-[r:INVESTS_IN_SECTOR]->(s:Sector)
RETURN s.name, r.weight
ORDER BY r.weight DESC;
```

#### Milvus (Optional)

Fund data is primarily structured; Milvus storage is not used for current fund files. Milvus is intended for text-based data like fund descriptions, news, or report summaries when available.

### Verification Commands

**Check PostgreSQL:**
```bash
python -c "
from mcp.tools import sql_tool
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:postgres@localhost:5432/openfund'
print(sql_tool.list_tables())
"
```

**Check Neo4j:**
```bash
python -c "
from mcp.tools import kg_tool
import os
os.environ['NEO4J_URI'] = 'bolt://localhost:7687'
os.environ['NEO4J_USER'] = 'neo4j'
os.environ['NEO4J_PASSWORD'] = 'password123'
print(kg_tool.get_graph_schema())
"
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| `psycopg2` not found | Run `pip install psycopg2-binary` |
| `neo4j` not found | Run `pip install neo4j` |
| PostgreSQL connection refused | Ensure container is running: `docker ps` |
| Neo4j authentication failed | Verify `NEO4J_PASSWORD` matches the value set in `NEO4J_AUTH` |
| No data written | Check environment variables are set correctly |

### Fund Data File Structure

Fund files in `datasets/funds/` have this structure:

```json
{
  "metadata": {
    "description": "Top ETFs 2025",
    "as_of_date": "2025-02-27",
    "last_updated": "2025-02-27T12:00:00Z"
  },
  "sp500_etfs": [
    {
      "symbol": "VOO",
      "name": "Vanguard S&P 500 ETF",
      "total_assets_billion": 502.2,
      "expense_ratio": 0.0003,
      "performance": {
        "return_1yr": 0.2845,
        "return_3yr": 0.1123,
        "return_5yr": 0.1567
      },
      "risk_metrics": {
        "beta": 1.0,
        "sharpe_ratio": 1.45,
        "max_drawdown": -0.2376
      },
      "top_10_holdings": [
        {"symbol": "AAPL", "name": "Apple Inc.", "weight": 0.072},
        ...
      ],
      "sector_allocation": {
        "Technology": 0.31,
        "Healthcare": 0.12,
        ...
      }
    }
  ]
}
```

---

## References

- [backend.md](backend.md) — System architecture and MCP tool interfaces
- [file-structure.md](file-structure.md) — Code structure
- [backend-tools-design.md](backend-tools-design.md) — MCP tool design
