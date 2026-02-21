# OpenFund-AI — Claude.md v2
## A2A Multi-Agent Skeleton (FIPA-ACL + MCP) + Six-Layer + Tech Stack

---

## Overview

Implementation outline for:

- **A2A** communication via FIPA-ACL and a message bus
- **Six-layer architecture**: User Interaction, Safety, Orchestration, Research Execution, Tool/Data (MCP), Output Review
- **Technology stack**: **Milvus** (vector DB), **Neo4j** (graph), **Tavily** + **Yahoo APIs** (web/market search), **custom Analyst API** (quant analysis)
- **MCP** as the only path for external data; Responder-controlled termination

---

## Technology Stack

| Concern | Technology | MCP Tool / Use |
|--------|------------|----------------|
| Vector DB | **Milvus** | `vector_tool` — semantic search over fund documents; config: MILVUS_* |
| Knowledge graph | **Neo4j** | `kg_tool` — Cypher queries, fund–manager–company relations; config: NEO4J_* |
| Web / market search | **Tavily** + **Yahoo APIs** | `market_tool` — real-time data, web search; results include `timestamp`; config: TAVILY_API_KEY, YAHOO_* |
| Analyst backend | **Custom API** | `analyst_tool` — call custom API for Sharpe, drawdown, Monte Carlo, etc.; config: ANALYST_API_URL |

---

## Project Structure

```
OpenFund-AI/
├── agents/
│   ├── base_agent.py
│   ├── planner_agent.py
│   ├── librarian_agent.py
│   ├── websearch_agent.py
│   ├── analyst_agent.py
│   └── responder_agent.py
├── a2a/
│   ├── acl_message.py
│   ├── message_bus.py
│   └── conversation_manager.py
├── api/
│   ├── rest.py
│   └── websocket.py
├── safety/
│   └── safety_gateway.py
├── output/
│   └── output_rail.py
├── mcp/
│   ├── mcp_client.py
│   ├── mcp_server.py
│   └── tools/
│       ├── sql_tool.py
│       ├── vector_tool.py    # Milvus
│       ├── kg_tool.py        # Neo4j
│       ├── market_tool.py    # Tavily + Yahoo
│       ├── analyst_tool.py   # Custom API
│       └── file_tool.py
├── config/
│   └── config.py
├── main.py
└── docs/
    └── claude-v2.md
```

---

## Layer 1 — User Interaction

### api/rest.py

- **POST /chat** (or **POST /research**): body `query`, optional `conversation_id`, `user_profile` → SafetyGateway → create/load conversation → send ACLMessage to Planner → return/stream response.
- **GET /conversations/{id}** (optional): return conversation state.

### api/websocket.py

- **WebSocket /ws**: same flow; stream partial responses.

---

## Layer 2 — Safety Gateway

### safety/safety_gateway.py

- **SafetyGateway**: `validate_input`, `check_guardrails`, `mask_pii`, `process_user_input` (single entry before bus).

---

## A2A Layer

### a2a/acl_message.py

- **ACLMessage**: performative, sender, receiver, content, conversation_id; add `reply_to`, `in_reply_to`, `timestamp`; reserve performative for STOP.

### a2a/message_bus.py

- **MessageBus**: `send`, `receive(agent_name, timeout?)`, `broadcast`.

### a2a/conversation_manager.py

- **ConversationManager**: `create_conversation`, `get_conversation`, `register_reply`, `broadcast_stop`.

---

## Agents (Layer 3 & 4)

### agents/base_agent.py

- **BaseAgent**: `__init__(name, message_bus)`, `run()`, `handle_message(message)` (abstract).

### agents/planner_agent.py

- **PlannerAgent**: `handle_message`, `decompose_task(query) -> List[TaskStep]`, `create_research_request(...)`, (Phase 2) `resolve_conflicts(agent_outputs)`.

### agents/librarian_agent.py

- **LibrarianAgent**: `handle_message`; uses MCP **vector_tool (Milvus)** and **kg_tool (Neo4j)**; `retrieve_knowledge_graph`, `retrieve_documents`, `combine_results`.

### agents/websearch_agent.py

- **WebSearcherAgent**: `handle_message`; uses MCP **market_tool (Tavily + Yahoo)**; `fetch_market_data`, `fetch_sentiment`, `fetch_regulatory`; all returns include `timestamp`.

### agents/analyst_agent.py

- **AnalystAgent**: `handle_message`; uses MCP **analyst_tool (custom API)** for heavy quant; local helpers: `sharpe_ratio`, `max_drawdown`, `monte_carlo_simulation` (or delegate to custom API); `analyze`, `needs_more_data`.

### agents/responder_agent.py

- **ResponderAgent**: `handle_message`, `evaluate_confidence`, `should_terminate`, `format_response(analysis, user_profile)`; use OutputRail for compliance and formatting; optional `request_refinement`.

---

## Layer 6 — Output Review

### output/output_rail.py

- **OutputRail**: `check_compliance(text)`, `format_for_user(text, user_profile)`.

---

## Layer 5 — MCP Tools (with backends)

### mcp/mcp_client.py

- **MCPClient**: `call_tool(tool_name, payload) -> dict`.

### mcp/mcp_server.py

- **MCPServer**: `register_tool(name, handler)`, `dispatch(tool_name, payload)`.

### mcp/tools/vector_tool.py — **Milvus**

- **search(query: str, top_k: int, filter?: dict) -> list** — Milvus collection; returns docs with scores.
- **index_documents(docs: list) -> dict** (optional).
- Config: MILVUS_URI (or host/port), MILVUS_COLLECTION.

### mcp/tools/kg_tool.py — **Neo4j**

- **query_graph(cypher: str, params?: dict) -> dict** — Neo4j driver; nodes/edges.
- **get_relations(entity: str) -> dict** (optional).
- Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.

### mcp/tools/market_tool.py — **Tavily + Yahoo APIs**

- **fetch(fund_or_symbol: str) -> dict** — Yahoo (and/or Tavily) for market data; must include `timestamp`.
- **fetch_bulk(symbols: list) -> dict** (optional).
- **search_web(query: str) -> list** (optional) — Tavily for regulatory/sentiment; include `timestamp` per result.
- Config: TAVILY_API_KEY, YAHOO_BASE_URL (and YAHOO_API_KEY if required).

### mcp/tools/analyst_tool.py — **Custom API**

- **run_analysis(payload: dict) -> dict** — POST to custom Analyst API; payload/response schema defined by that API (e.g. metrics: sharpe, max_drawdown, monte_carlo distribution).
- Config: ANALYST_API_URL, optional ANALYST_API_KEY or auth header.

### mcp/tools/sql_tool.py

- **run_query(query: str, params?: dict) -> dict**.

### mcp/tools/file_tool.py

- **read_file(path: str) -> dict**; optional **list_files(prefix: str) -> list**.

---

## Config

### config/config.py

- **load_config() -> Config**: env vars for API keys, model names; **MILVUS_***, **NEO4J_***, **TAVILY_API_KEY**, **YAHOO_***, **ANALYST_API_URL** (and optional auth); MCP server endpoint; feature flags.

---

## Entry Point

### main.py

- **main()**: create MessageBus, ConversationManager, SafetyGateway, MCP client (with config); instantiate agents (inject bus + MCP client); start FastAPI (REST + WebSocket) and agent runners; optionally start MCP server.

---

## Design Constraints

- All inter-agent communication: ACLMessage only.
- All external data: via MCP only (Milvus, Neo4j, Tavily, Yahoo, custom Analyst API accessed only through MCP tools).
- Termination: only Responder; broadcast STOP via ConversationManager.
- Loop: multiple refinement cycles (Analyst.needs_more_data → Planner → Responder.should_terminate).

---

## Next Implementation Steps

1. Implement MessageBus backend; ConversationManager and STOP.
2. Implement MCP server and tools: **vector_tool (Milvus)**, **kg_tool (Neo4j)**, **market_tool (Tavily + Yahoo)**, **analyst_tool (custom API)**, sql_tool, file_tool.
3. Add SafetyGateway and OutputRail; wire REST/WebSocket.
4. Define Analyst API payload/response schema and confidence/termination rules.
5. Logging, monitoring, error handling; config and deployment.
