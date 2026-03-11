# File-Structure Document

Directory layout, module boundaries, file responsibilities, and per-function (name, responsibility, inputs, outputs, side effects, example usage). See [backend.md](backend.md) for API and architecture, [prd.md](prd.md) for product intent, [user-flow.md](user-flow.md) for user flow. This document covers the main application code only; the `data_prep/` folder is not included.

---

## Project Structure

```
OpenFund-AI/
├── agents/
│   ├── __init__.py
│   ├── base_agent.py
│   ├── planner_agent.py
│   ├── librarian_agent.py
│   ├── websearch_agent.py
│   ├── analyst_agent.py
│   └── responder_agent.py
├── a2a/
│   ├── __init__.py
│   ├── acl_message.py
│   ├── message_bus.py
│   └── conversation_manager.py
├── api/
│   ├── __init__.py
│   ├── rest.py
│   └── websocket.py
├── data_manager/              # CLI-based data collection/distribution workflows (see data-manager-agent.md)
│   ├── __init__.py
│   ├── __main__.py            # Entry point for python -m data_manager
│   ├── backend_cli.py         # Backend maintenance subcommands: populate, sql, neo4j, milvus
│   ├── collector.py           # DataCollector: fetch from market_tool/analyst_tool, save to files
│   ├── distributor.py         # DataDistributor: read files, write to sql/kg/vector_tool
│   ├── classifier.py          # DataClassifier: route data to appropriate database
│   ├── transformer.py         # DataTransformer: convert to PG rows / Neo4j nodes / Milvus docs
│   ├── tasks.py               # CollectionTask definitions and COLLECTION_TASKS registry
│   └── schemas.py             # Database schema definitions (SQL DDL, Cypher patterns)
├── datasets/                     # Fund dataset files
│   └── combined_funds.json       # Canonical combined fund dataset used by distribute-funds
├── scripts/
│   ├── run.sh                # Single entrypoint: backends, seed, API, and interactive chat (use --no-chat for API only)
│   └── chat_cli.py            # Interactive terminal client: POST /chat in a loop; --port, --profile
├── safety/
│   ├── __init__.py
│   └── safety_gateway.py
├── output/
│   ├── __init__.py
│   └── output_rail.py
├── llm/
│   ├── __init__.py
│   ├── base.py
│   ├── static_client.py
│   ├── live_client.py
│   └── factory.py
├── mcp/
│   ├── __init__.py
│   ├── mcp_client.py
│   ├── mcp_server.py
│   └── tools/
│       ├── __init__.py
│       ├── file_tool.py
│       ├── vector_tool.py
│       ├── kg_tool.py
│       ├── fund_catalog_tool.py   # P1: FinanceDatabase search
│       ├── stooq_tool.py          # P2: stooq price
│       ├── yahoo_finance_tool.py  # P2 fallback: query1.finance.yahoo.com price
│       ├── etfdb_tool.py          # P3: ETFdb fundamentals
│       ├── market_tool.py
│       ├── analyst_tool.py
│       ├── sql_tool.py
│       └── capabilities.py   # get_capabilities (backends + tool list)
├── config/
│   ├── __init__.py
│   └── config.py
├── memory/
│   ├── __init__.py
│   └── situation_memory.py
├── util/
│   ├── __init__.py
│   ├── trace_log.py
│   └── interaction_log.py
├── main.py
├── CHANGELOG.md
├── README.md
├── pyproject.toml
├── .gitignore
├── tests/
│   └── test-stages.py
└── docs/
    ├── user-flow.md
    ├── prd.md
    ├── backend.md
    ├── frontend.md
    ├── file-structure.md
    ├── agent-tools-reference.md   # MCP tool payloads and per-agent tool lists
    ├── data-manager-agent.md     # Data Manager Agent design: data collection + distribution to DBs
    ├── demo.md                   # How to run full stack; no separate demo mode
    ├── fund-data-schema.md       # Fund data schema: JSON field definitions and DB mapping
    ├── websearcher-design.md     # WebSearcher agent design: parallel sources, schema, Planner contract
    ├── test_plan.md
    ├── progress.md
    ├── project-status.md
    └── use-case-trace-beginner.md   # Step-by-step function trace for one beginner request
```

---

# a2a/acl_message.py

**Purpose:** Define the FIPA-ACL message type used for all agent-to-agent communication. Provides Performative enum (`(str, Enum)` for Python 3.9) and ACLMessage dataclass with performative, sender, receiver, content, and optional conversation threading and timestamp.

---

## Class: `Performative` (str, Enum)

**Purpose:** FIPA-ACL performatives (B1). Uses `(str, Enum)` for Python 3.9 compatibility (StrEnum is 3.11+). Values: REQUEST, INFORM, STOP, FAILURE, ACK, REFUSE, CANCEL.

---

## Class: `ACLMessage` (dataclass)

**Purpose:** Immutable FIPA-ACL message exchanged between agents.

**Docstring:**
```text
FIPA-ACL message exchanged between agents.

Attributes:
    performative: Communication intent (e.g. request, inform, stop).
    sender: Name of the sending agent.
    receiver: Name of the receiving agent.
    content: Structured payload of the message.
    conversation_id: Unique conversation identifier.
    reply_to: Optional agent name to reply to.
    in_reply_to: Optional message id this message replies to.
    timestamp: Optional send time.
```

**Example usage:**
```python
from a2a.acl_message import ACLMessage

msg = ACLMessage(
    performative="request",
    sender="planner",
    receiver="librarian",
    content={"query": "fund X performance", "step": "retrieve_fund_facts"},
)
# conversation_id and timestamp auto-set in __post_init__
print(msg.conversation_id)  # UUID string
```

---

## Method: `ACLMessage.__post_init__(self) -> None`

**Purpose:** Normalize performative (string → Performative enum), assign default conversation_id (UUID) and timestamp if not provided.

**Example usage:** Called automatically when constructing `ACLMessage`; no direct call needed.

---

## Method: `ACLMessage.to_dict(self) -> dict[str, Any]`

**Purpose:** Return a JSON-serializable dict for persistence. Converts performative to string and timestamp to ISO format for serialization to memory/<user_id>/conversations.json.

**Returns:** Dict suitable for json.dumps (e.g. in state.messages).

---

# util/trace_log.py

**Purpose:** Human-readable trace logging for request flow (stage, input, output, next transition). Used by API and SafetyGateway for debugging and onboarding.

---

## Function: `trace(step: int, stage: str, *, in_=None, out=None, next_="") -> None`

**Purpose:** Log one trace step in a readable block. No return value; logs via logger.info.

---

# util/interaction_log.py

**Purpose:** Systematic interaction call logging: every significant function visited during a user interaction (POST /chat or WebSocket /ws), with function name, sanitized params, and result in one JSON object per line. Used for debugging and auditing; filterable by conversation_id. See [use-case-trace-beginner.md](use-case-trace-beginner.md) for the logical flow that is logged.

**Context:** `set_conversation_id(cid)` sets the current conversation id in a contextvar so API, agents, and MCP client can attach logs without passing the id. `get_conversation_id()` returns the current value.

**Functions:**
- `set_conversation_id(conversation_id: str) -> None` — Set conversation id for this context (thread/task).
- `get_conversation_id() -> str` — Return current conversation id or empty string.
- `set_enabled(enabled: bool) -> None` — Override enabled state (e.g. from Config); called at app startup.
- `log_call(function_name: str, params=None, result=None, duration_ms=None) -> None` — Emit one JSON line: ts, conversation_id, function, params, result, duration_ms, sequence. No-op if disabled (INTERACTION_LOG env or config). Params and result are sanitized (truncated strings, JSON-serializable).

**Format:** Each log line is a single JSON object with keys: ts, conversation_id, function, params, result, duration_ms, sequence. Logger name: openfund.interaction. Enable via INTERACTION_LOG=1 or config.interaction_log_enabled.

---

# a2a/message_bus.py

**Purpose:** Abstract message transport for A2A. Implementations (e.g. in-memory, Redis) provide register_agent, send, receive, and broadcast. All agents use the same bus. `main()` calls `register_agent(name)` for each agent at startup before any messages are sent; `broadcast` delivers to all registered names.

---

## Class: `MessageBus` (ABC)

**Purpose:** Abstract base for message transport; concrete implementations deliver messages to agent queues.

**Docstring:** `Abstract message transport layer for A2A communication. Backends may use Redis, Kafka, NATS, or in-memory queues.`

---

## Method: `MessageBus.register_agent(self, name: str) -> None`

**Purpose:** Register an agent name so it can receive messages and be included in broadcasts. Must be called in `main()` for each agent before any messages are sent.

**Docstring:**
```text
Register an agent by name. Required for receive and for broadcast delivery.
Args:
    name: Unique agent name (e.g. "planner", "librarian", "responder").
```

**Example usage:** `bus.register_agent("planner"); bus.register_agent("librarian")`

---

## Method: `MessageBus.send(self, message: ACLMessage) -> None`

**Purpose:** Deliver an ACL message to the message’s designated receiver.

**Docstring:**
```text
Send an ACL message to the designated receiver.
Args:
    message: The message to dispatch.
```

**Example usage:**
```python
bus.send(ACLMessage(performative="request", sender="planner", receiver="librarian", content={"query": "..."}))
```

---

## Method: `MessageBus.receive(self, agent_name: str, timeout: Optional[float] = None) -> Optional[ACLMessage]`

**Purpose:** Block until a message for the given agent is available, or until timeout; return the message or None.

**Docstring:**
```text
Wait for a message addressed to the given agent.
Args:
    agent_name: Name of the agent waiting for messages.
    timeout: Optional max seconds to wait; None means block indefinitely.
Returns:
    The received message, or None if timeout elapsed.
```

**Example usage:**
```python
msg = bus.receive("librarian", timeout=5.0)
if msg:
    handle(msg)
```

---

## Method: `MessageBus.broadcast(self, message: ACLMessage) -> None`

**Purpose:** Send a message to all agents (e.g. STOP from Responder).

**Docstring:**
```text
Send a message to all agents (e.g. STOP).
Args:
    message: The message to broadcast.
```

**Example usage:**
```python
bus.broadcast(ACLMessage(performative="stop", sender="responder", receiver="*", content={"conversation_id": cid}))
```

---

## Class: `InMemoryMessageBus(MessageBus)`

**Purpose:** In-memory implementation: one queue per registered agent. send() delivers only to the named receiver; broadcast() puts a copy in every agent's queue. Used by main and tests.

**Methods:** register_agent(name), send(message), receive(agent_name, timeout), broadcast(message). See MessageBus for contracts.

---

# a2a/conversation_manager.py

**Purpose:** Track conversation state (create, get, register replies) and send STOP via the message bus so agents stop processing a conversation.

---

## Class: `ConversationState`

**Purpose:** Snapshot of one conversation. Holds id, user_id, initial_query, messages, status, final_response, created_at, completion_event, and flow_events for API blocking, persistence, and UI flow steps.

**Docstring:**
```text
Snapshot of one conversation for API blocking and persistence.
Attributes:
    id: Conversation UUID (conversation_id).
    user_id: User identifier; empty string if anonymous.
    initial_query: Original user query.
    messages: Append-only log of ACLMessage dicts.
    status: "active" | "complete" | "error".
    final_response: Set by register_reply when Responder delivers answer; None until then.
    created_at: Creation datetime.
    completion_event: threading.Event set when final_response is written; callers block with event.wait(timeout=...).
    flow_events: Append-only list of flow step dicts for UI (e.g. {"step": "...", "message": "...", "detail": {...}}).
```

**Example usage:**
```python
state = ConversationState(conversation_id="abc", user_id="u1", initial_query="...", messages=[], status="active", final_response=None, created_at=..., completion_event=threading.Event())
```

---

## Method: `ConversationState.append_flow(self, event: dict[str, Any]) -> None`

**Purpose:** Append a flow step (thread-safe). event must have at least 'step' and 'message'; optional 'detail'.

---

## Class: `ConversationManager`

**Purpose:** Create conversations, look up state, register replies, and broadcast STOP.

**Docstring:** `Tracks conversations and sends STOP broadcasts via the message bus. Responsibilities: create conversation, get state, register replies, broadcast STOP.`

**Persistence:** Conversation state is written to `MEMORY_STORE_PATH/<user_id>/conversations.json` (see [backend.md](backend.md)) on create and on register_reply. Anonymous user_id maps to `anonymous/`. ConversationManager maintains _memory_root and uses _user_dir, _save_user internally. Only a subset of state is persisted: id, user_id, initial_query, messages, status, final_response, created_at. **flow_events are in-memory only**; they are returned in the API response (`flow`) for the current request but are not written to conversations.json.

---

## Method: `ConversationManager.append_flow(self, conversation_id: str, event: dict[str, Any]) -> None`

**Purpose:** Append a flow step for a conversation (for UI). No-op if conversation not found or state has no append_flow. The planner calls this with steps that include per-agent query in `detail`; the accumulated flow is returned to the client in the API response as `flow`. Nothing is printed to the console by the conversation manager.

---

## Method: `ConversationManager.get_flow_events(self, conversation_id: str) -> list[dict[str, Any]]`

**Purpose:** Return a copy of the conversation's flow_events (thread-safe when state has _flow_lock). Returns [] if not found.

---

## Method: `ConversationManager.__init__(self, message_bus: MessageBus) -> None`

**Purpose:** Store the MessageBus used for broadcast.

**Docstring:** `Initialize the conversation manager. Args: message_bus: MessageBus implementation for send/broadcast.`

**Example usage:** `mgr = ConversationManager(bus)`

---

## Method: `ConversationManager.create_conversation(self, user_id: str, initial_query: str) -> str`

**Purpose:** Create a new conversation, store its state, return conversation_id.

**Docstring:**
```text
Create a new conversation and return its id.
Args:
    user_id: User identifier.
    initial_query: Initial user query.
Returns:
    New conversation_id.
```

**Example usage:**
```python
cid = mgr.create_conversation("user1", "What is fund X's performance?")
```

---

## Method: `ConversationManager.get_conversation(self, conversation_id: str) -> Optional[ConversationState]`

**Purpose:** Return the current ConversationState for a conversation, or None.

**Docstring:**
```text
Return current state for a conversation.
Args:
    conversation_id: Conversation to look up.
Returns:
    ConversationState if found, else None.
```

**Example usage:**
```python
state = mgr.get_conversation(cid)
```

---

## Method: `ConversationManager.register_reply(self, conversation_id: str, message: ACLMessage) -> None`

**Purpose:** Append a reply message to the conversation’s state.

**Docstring:**
```text
Record a reply message for a conversation.
Args:
    conversation_id: Conversation to update.
    message: The reply ACL message.
```

**Example usage:**
```python
mgr.register_reply(cid, reply_msg)
```

---

## Method: `ConversationManager.broadcast_stop(self, conversation_id: str) -> None`

**Purpose:** Build a STOP ACLMessage and call message_bus.broadcast so all agents stop for this conversation.

**Docstring:**
```text
Send STOP via MessageBus so agents stop processing this conversation.
Args:
    conversation_id: Conversation to terminate.
```

**Example usage:**
```python
mgr.broadcast_stop(cid)
```

---

# agents/base_agent.py

**Purpose:** Abstract base for all agents. Subclasses implement handle_message; the base provides the event loop that receives from the bus and delegates.

---

## Class: `BaseAgent` (ABC)

**Purpose:** Common agent interface: name, message_bus, run() loop, and abstract handle_message.

**Docstring:** `Abstract base class for all agents. Agents listen on the message bus and process incoming ACL messages.`

---

## Method: `BaseAgent.__init__(self, name: str, message_bus: MessageBus) -> None`

**Purpose:** Set the agent’s unique name and the shared bus.

**Docstring:** `Initialize the agent. Args: name: Unique agent name (used as receiver address). message_bus: Shared A2A transport layer.`

**Example usage:** `agent = PlannerAgent("planner", bus)`

---

## Method: `BaseAgent.run(self) -> None`

**Purpose:** Run the agent loop: repeatedly receive messages for this agent and call handle_message.

**Docstring:** `Start the agent event loop. Continuously receives messages for this agent and delegates to handle_message. Exits cleanly when a STOP message is received (e.g. after Responder calls broadcast_stop).`

**Example usage:** Typically run in a thread: `threading.Thread(target=agent.run, daemon=True).start()`

---

## Method: `BaseAgent.handle_message(self, message: ACLMessage) -> None` (abstract)

**Purpose:** Process one received ACL message; each agent type implements its own logic.

**Docstring:** `Process an incoming ACL message. Args: message: The received ACL message.`

**Example usage:** Implement in subclass; e.g. Planner parses content and sends requests to Librarian/WebSearcher/Analyst.

---

# agents/planner_agent.py

**Purpose:** Orchestrate research: decide which agents to call (one or more of Librarian, WebSearcher, Analyst), decompose the user query into agent-specific sub-queries for each chosen agent, run a planner sufficiency check after specialist replies, and either send consolidated data to Responder or start refined planner round(s).

---

## Class: `TaskStep`

**Purpose:** One step in a decomposed task chain (agent target and params, including the decomposed query).

**Docstring:**
```text
Single step in a decomposed task chain.
Attributes:
    agent: Target agent: "librarian" | "websearcher" | "analyst".
    params: Parameters for the step (including "query"); forwarded as ACLMessage content.
```

**Example usage:**
```python
step = TaskStep(agent="librarian", params={"query": "fund X facts", "fund": "X"})
```

---

## Class: `PlannerAgent(BaseAgent)`

**Purpose:** Decompose queries into agent-specific sub-queries, create research requests, and route to one or more of Librarian/WebSearcher/Analyst; aggregate INFORMs and apply the planner sufficiency check to decide responder handoff vs refined planner round(s). Uses optional llm_client for decompose_to_steps (Stage 10.2).

**Docstring:** `Decides which agents to call (one or more of librarian, websearcher, analyst) and decomposes the user query into agent-specific sub-queries. Creates research requests whose content includes the decomposed query per agent; aggregates INFORMs, runs planner sufficiency check, and forwards to Responder when the planner sufficiency check passes.`

---

## Method: `PlannerAgent.__init__(self, name: str, message_bus: MessageBus, llm_client: Optional[LLMClient] = None) -> None`

**Purpose:** Initialize planner with name, bus, and optional LLM client for task decomposition. When llm_client is None, decompose_task returns fixed three steps.

---

## Method: `PlannerAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** On STOP, return. On INFORM from librarian/websearcher/analyst, aggregate in _collected; when all expected specialist replies are in, run planner sufficiency check and either start refined planner round(s) or send INFORM to responder with final_response and user_profile. On REQUEST from api, validate user_profile, call decompose_task (uses llm_client when set), and dispatch the initial planner round; merge path from content for E2E.

**Docstring:** `Handle incoming messages directed to the Planner. Handles STOP (ignore), INFORM from specialist agents (aggregate then forward to Responder), and REQUEST from API (send to all three agents). Args: message: The received ACL message (REQUEST from api, or INFORM from librarian/websearcher/analyst).`

**Example usage:** Invoked by the base run() loop when a message for the planner arrives.

---

## Method: `PlannerAgent.decompose_task(self, query: str) -> List[TaskStep]`

**Purpose:** Produce a task chain from the user query. Decomposition is **LLM-driven**: the LLM selects which agents to call and what query to pass to each; the planner parses the response into a list of steps (TaskSteps) and dispatches REQUESTs only for those steps. Returns an ordered list of TaskSteps; each step targets one agent and includes a **decomposed query** (and optional params) for that agent. May call one, two, or three agents depending on the LLM output. Uses llm_client.decompose_to_steps when available (Stage 10.2); when the LLM returns an empty list, returns a single analyst step; when the LLM is absent or parse fails, returns a fixed three-step chain (librarian, websearcher, analyst).

**Docstring:**
```text
Produce a task chain from the user query. Each step includes the decomposed query for that agent.
Uses llm_client.decompose_to_steps when available; otherwise returns fixed steps.
Args:
    query: Raw user investment query.
Returns:
    Ordered list of task steps (one or more of librarian, websearcher, analyst), each with decomposed query in params.
```

**Example usage:**
```python
steps = planner.decompose_task("Should I buy fund X?")
```

---

## Method: `PlannerAgent.create_research_request(self, query: str, step: TaskStep, context: Optional[Dict[str, Any]] = None) -> ACLMessage`

**Purpose:** Build an ACL REQUEST for Librarian, WebSearcher, or Analyst. Content includes the **decomposed query for that agent** (e.g. from step.params["query"] or equivalent) and any other params, so the specialist can fulfill the sub-task.

**Docstring:**
```text
Build a request ACL message for Librarian, WebSearcher, or Analyst.
Args:
    query: User query (fallback if step has no query).
    step: Current task step (params include decomposed query for this agent).
    context: Optional prior context.
Returns:
    ACL message addressed to the appropriate agent; content includes that agent's decomposed query.
```

**Example usage:**
```python
msg = planner.create_research_request("fund X risk?", step, context={"prior_docs": [...]})
bus.send(msg)
```

---

## Method: `PlannerAgent.resolve_conflicts(self, agent_outputs: Dict[str, Any]) -> Any`

**Purpose:** Reconcile conflicting results from multiple agents (Phase 2).

**Docstring:** `Self-reflection when agent results conflict (Phase 2). Args: agent_outputs: Map of agent name to output. Returns: Reconciled result.`

**Example usage:**
```python
result = planner.resolve_conflicts({"librarian": d1, "analyst": d2})
```

---

# agents/librarian_agent.py

**Purpose:** Retrieve structured data from knowledge graph, vector DB, SQL, and files via MCP. Tool selection may use LLM (see [backend.md](backend.md)); otherwise content-key dispatch. Tool list: [agent-tools-reference.md](agent-tools-reference.md).

---

## Class: `LibrarianAgent(BaseAgent)`

**Purpose:** Retrieve documents and knowledge-graph data via MCP only; no direct DB access. Tool selection may use LLM (see [backend.md](backend.md)); tool list in [agent-tools-reference.md](agent-tools-reference.md).

**Docstring:** `Retrieves structured data from knowledge graph and vector database. Uses MCP vector_tool (Milvus) and kg_tool (Neo4j); does not access databases directly.`

---

## Method: `LibrarianAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Process data retrieval requests; dispatch via MCP (tool selection may use LLM per [backend.md](backend.md)); combine results and send INFORM to reply_to.

---

## Method: `LibrarianAgent.retrieve_knowledge_graph(self, fund: str) -> dict`

**Purpose:** Query the knowledge graph for a fund via MCP kg_tool (Neo4j).

**Docstring:** `Query knowledge graph for fund relationships via MCP kg_tool (Neo4j). Args: fund: Fund identifier. Returns: Structured graph data (nodes/edges).`

**Example usage:**
```python
graph = agent.retrieve_knowledge_graph("FUND_X")
```

---

## Method: `LibrarianAgent.retrieve_documents(self, query: str) -> list`

**Purpose:** Semantic search over the vector store via MCP vector_tool (Milvus).

**Docstring:** `Perform semantic search over vector DB via MCP vector_tool (Milvus). Args: query: Search query. Returns: List of retrieved documents with scores.`

**Example usage:**
```python
docs = agent.retrieve_documents("fund X performance report")
```

---

## Method: `LibrarianAgent.combine_results(self, docs: list, graph_data: dict) -> dict`

**Purpose:** Merge vector and graph results into one structure for the Analyst.

**Docstring:** `Merge vector and graph results for downstream Analyst. Args: docs: Documents from vector search. graph_data: Result from knowledge graph query. Returns: Single structured result dict.`

**Example usage:**
```python
combined = agent.combine_results(docs, graph_data)
```

---

# agents/websearch_agent.py

**Purpose:** Fetch real-time market and fund data via MCP. Entry point `handle_message` → `_run_parallel_flow`: financial bundle per symbol via `_fetch_all_sources_for_symbol` (stooq, Yahoo, ETFdb, market_tool with dated news payloads), merged by `_merge_financial_results` into `normalized_fund`; news bundle via `_fetch_news_sources` in parallel. Symbol resolution uses `_resolve_symbols` / `_normalize_symbol` and `_TICKER_BLOCKLIST` so planner tokens like WHAT are not queried as tickers. Returns `normalized_fund`, backward-compat `market_data`/`sentiment`/`regulatory`, and `news`/`citations`. See [websearcher-design.md](websearcher-design.md).

---

## Class: `WebSearcherAgent(BaseAgent)`

**Purpose:** Fetches real-time market and regulatory information via MCP. Tool selection may use LLM (see [backend.md](backend.md)); tool list in [agent-tools-reference.md](agent-tools-reference.md).

**Docstring:** `Fetches real-time market and fund information. Queries all sources in parallel; merges into normalized_fund, market_data, sentiment, regulatory, news/citations. All returned data includes a timestamp.`

---

## Method: `WebSearcherAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Process market/sentiment/regulatory requests; dispatch via MCP (tool selection may use LLM per [backend.md](backend.md)); send INFORM with timestamp in content.

**Docstring:** `Process REQUEST from Planner: run Financial Data Search and News Search in parallel, merge, send INFORM. Uses _run_parallel_flow; optional LLM summary, conflict resolution, all-tools-fail and news fallbacks when llm_client is set.`

---

## Method: `WebSearcherAgent.fetch_market_data(self, fund: str) -> dict`

**Purpose:** Get live market metrics for a fund/symbol via MCP; return must include `timestamp`.

**Docstring:** `Retrieve live market metrics via MCP market_tool. Args: fund: Fund or symbol identifier. Returns: Market data payload; must include 'timestamp'.`

**Example usage:**
```python
data = agent.fetch_market_data("FUND_X")
assert "timestamp" in data
```

---

## Method: `WebSearcherAgent.fetch_sentiment(self, symbol_or_fund: str) -> dict`

**Purpose:** Get sentiment data via MCP; return must include `timestamp`.

**Docstring:** `Retrieve social/regulatory sentiment via MCP (e.g. Tavily). Args: symbol_or_fund: Symbol or fund identifier. Returns: Sentiment payload; must include 'timestamp'.`

---

## Method: `WebSearcherAgent.fetch_regulatory(self, fund: str) -> dict`

**Purpose:** Get regulatory disclosures for a fund via MCP; return must include `timestamp`.

**Docstring:** `Retrieve regulatory disclosures for a fund. Args: fund: Fund identifier. Returns: Regulatory data; must include 'timestamp'.`

---

# agents/analyst_agent.py

**Purpose:** Run quantitative analysis (e.g. Sharpe, max drawdown, Monte Carlo) using MCP analyst_tool or local helpers. Tool selection may use LLM (see [backend.md](backend.md)); otherwise uses structured_data and market_data from message. Sends INFORM to Planner. Tool list: [agent-tools-reference.md](agent-tools-reference.md).

---

## Class: `AnalystAgent(BaseAgent)`

**Purpose:** Performs quantitative reasoning and uncertainty estimation via MCP and local helpers. Tool selection may use LLM (see [backend.md](backend.md)); tool list in [agent-tools-reference.md](agent-tools-reference.md).

**Docstring:** `Performs quantitative reasoning and uncertainty estimation. Uses MCP analyst_tool (custom API) for heavy quant; may use local helpers for sharpe_ratio, max_drawdown, monte_carlo_simulation.`

---

## Method: `AnalystAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Process analysis requests; dispatch via MCP (tool selection may use LLM per [backend.md](backend.md)) or use structured_data/market_data from content; call analyze(); send INFORM to Planner.

**Docstring:** `Process analysis requests. When LLM is available: use prompt/tool descriptions to select tools and parameters, execute via call_tool, then analyze() and send INFORM. When LLM is unavailable: use structured_data/market_data from message content, run analyze(), and send INFORM.`

---

## Method: `AnalystAgent.analyze(self, structured_data: dict, market_data: dict) -> dict`

**Purpose:** Produce analysis with confidence and, where applicable, probability distributions (not only point estimates).

**Docstring:** `Generate probabilistic investment analysis. Output should include probability distributions where applicable. Args: structured_data: KG and document data from Librarian. market_data: Real-time market signals from WebSearcher. Returns: Analysis result with confidence and optional distributions.`

**Example usage:**
```python
result = agent.analyze(knowledge_data, market_data)
```

---

## Method: `AnalystAgent.needs_more_data(self, analysis_result: dict) -> bool`

**Purpose:** Decide whether another refined planner round is needed.

**Docstring:** `Determine if additional information is required for refinement. Args: analysis_result: Current analysis output. Returns: True if another refined planner round is needed.`

---

## Method: `AnalystAgent.sharpe_ratio(self, returns: list, risk_free_rate: float) -> float`

**Purpose:** Compute Sharpe ratio for a return series.

**Docstring:** `Compute Sharpe ratio for a return series. Args: returns: List of period returns. risk_free_rate: Risk-free rate (e.g. annual). Returns: Sharpe ratio.`

**Example usage:**
```python
sr = agent.sharpe_ratio([0.01, -0.02, 0.015], 0.02)
```

---

## Method: `AnalystAgent.max_drawdown(self, returns: list) -> float`

**Purpose:** Compute maximum drawdown for a return series.

**Docstring:** `Compute maximum drawdown for a return series. Args: returns: List of period returns. Returns: Max drawdown (e.g. as positive decimal).`

---

## Method: `AnalystAgent.monte_carlo_simulation(self, returns: list, horizon: int, n_sims: int) -> dict`

**Purpose:** Run Monte Carlo and return a distribution (e.g. percentiles), not a single point.

**Docstring:** `Run Monte Carlo simulation; return distribution, not single point. Args: returns: Historical returns. horizon: Projection horizon (e.g. periods). n_sims: Number of simulations. Returns: Dict with distribution (e.g. percentiles, mean, std).`

---

# agents/responder_agent.py

**Purpose:** Finalize responder output after planner handoff: format response via OutputRail (or responder LLM path), check compliance, persist final response, and call conversation_manager.broadcast_stop. Only this agent may trigger STOP.

---

## Class: `ResponderAgent(BaseAgent)`

**Purpose:** Formats the final response via OutputRail (or responder LLM path), enforces compliance, and terminates the conversation by broadcasting STOP; only this agent may trigger STOP. See [backend.md](backend.md).

**Constructor:** Accepts optional `llm_client` (LLMClient). When set, handle_message uses llm_client.complete(RESPONDER_SYSTEM, user_content) to format the final answer before compliance check; otherwise uses OutputRail.format_for_user.

**Docstring:** `Final responder stage after planner sufficiency check: format for user profile, check compliance, register reply, and broadcast STOP.`

**Constructor:** Accepts optional `llm_client` (LLMClient). When set, handle_message uses llm_client.complete(RESPONDER_SYSTEM, user_content) to format the final answer before compliance check; otherwise uses OutputRail.format_for_user.

---

## Method: `ResponderAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** On INFORM with final_response: format via LLM or OutputRail, check_compliance, register_reply, broadcast STOP. See [backend.md](backend.md).

**Docstring:** `On INFORM with final_response and conversation_id: get user_profile from content, format via OutputRail.format_for_user, check_compliance, register_reply, broadcast_stop. Args: message: The received ACL message (expected INFORM with final_response).`

---

## Method: `ResponderAgent.evaluate_confidence(self, analysis: dict) -> float`

**Purpose:** Compute a 0–1 confidence score for the analysis.

**Docstring:** `Compute confidence score for the analysis output. Args: analysis: Analyst output dict. Returns: Confidence score between 0 and 1.`

**Example usage:**
```python
score = agent.evaluate_confidence(analysis_dict)
```

---

## Method: `ResponderAgent.should_terminate(self, confidence: float) -> bool`

**Purpose:** Decide whether the research loop should stop.

**Docstring:** `Determine if the research loop should stop. Args: confidence: Current confidence score. Returns: True if termination condition is met.`

---

## Method: `ResponderAgent.format_response(self, analysis: dict, user_profile: str) -> str`

**Purpose:** Turn analysis into user-facing text using OutputRail (tone/disclaimers by profile).

**Docstring:** `Turn analysis dict into user-facing text via OutputRail. Args: analysis: Analyst output. user_profile: User type (e.g. beginner, long_term, analyst). Returns: Formatted string for the user.`

---

## Method: `ResponderAgent.request_refinement(self, reason: str) -> ACLMessage`

**Purpose:** Build an ACL message back to the Planner for a future refined planner round (stub; not active in current runtime flow).

**Docstring:** `Build message back to Planner for a refined planner round. Args: reason: Why refinement is needed. Returns: ACL message addressed to Planner.`

**Example usage:**
```python
refinement_msg = agent.request_refinement("low confidence on drawdown")
bus.send(refinement_msg)
```

---

# api/rest.py

**Purpose:** REST API (Layer 1): chat and conversation endpoints. Builds FastAPI app with POST /chat, GET /conversations/{id}, and WebSocket /ws; shared state (bus, manager, safety_gateway, timeout) on app.state. Optional dependency injection for testing.

---

## Class: `ChatRequest` (BaseModel)

**Purpose:** POST /chat request body: query (required), user_profile (default "beginner"), user_id (default ""), conversation_id (optional), path (optional). Validators: query not empty, user_profile normalized to beginner|long_term|analyst, user_id/conversation_id normalized.

---

## Function: `create_app(*, bus=None, manager=None, safety_gateway=None, mcp_client=None, agents=None, timeout_seconds=None, llm_client=None) -> FastAPI`

**Purpose:** Build and return the FastAPI application with `POST /register`, `POST /login`, `POST /chat`, `GET /conversations/{id}`, and WebSocket `/ws`. Shared state on `app.state`: `bus`, `manager`, `safety_gateway`, `e2e_timeout_seconds`. `mcp_client` and agents are created at startup but not stored on `app.state`. If not provided, state is created at startup (same wiring as `main._run_e2e_once`). Optional args allow dependency injection for tests.

**Docstring:** `Build and return a FastAPI app with POST /chat and GET /conversations/{id}. Shared state is stored on app.state. If not provided, created at startup. Optional dependency injection for testing. Args: bus, manager, safety_gateway, mcp_client, agents, timeout_seconds, llm_client. Returns: FastAPI app instance.`

**Example usage:**
```python
app = create_app()
# uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Function: `post_chat(body: dict) -> dict`

**Purpose:** Programmatic handler for POST /chat flow. Raises NotImplementedError; use FastAPI TestClient with create_app() or the POST /chat endpoint for real requests.

**Docstring:** `Handle POST /chat. Flow: validate body -> SafetyGateway.process_user_input -> create/load conversation -> send ACLMessage to Planner -> wait for response -> return. Args: body with query; optional conversation_id, user_profile. Returns: Response dict. Raises NotImplementedError — use TestClient or POST /chat endpoint.`

**Example usage:**
```python
result = post_chat({"query": "fund X performance", "user_profile": "beginner"})
# result["conversation_id"], result["response"]
```

---

## Function: `get_conversation(conversation_id: str) -> Optional[dict]`

**Purpose:** Programmatic handler for GET /conversations/{id}. Raises NotImplementedError; use FastAPI TestClient with create_app() or the GET /conversations/{id} endpoint.

**Docstring:** `Handle GET /conversations/{id}. Args: conversation_id. Returns: Conversation state or None. Raises NotImplementedError — use TestClient or GET endpoint.`

**Example usage:**
```python
state = get_conversation("uuid-here")
```

---

# api/websocket.py

**Purpose:** Layer 1 — WebSocket handler. Same flow as POST /chat; streams `flow` events while processing, then sends one terminal event (`response` or `timeout`) and closes.

---

## Function: `handle_websocket(websocket, bus, manager, safety_gateway, timeout_seconds) -> None` (async)

**Purpose:** Handle WebSocket /ws: receive one JSON message (query required; optional conversation_id, user_profile, user_id, path), validate, run SafetyGateway.process_user_input, create or get conversation, send REQUEST to planner, stream `flow` events while waiting, then send terminal `response` or `timeout` and close (or `error` for early failures).

**Docstring:** `Handle WebSocket /ws connection. Same flow as POST /chat: receive one JSON message (query required; optional conversation_id, user_profile, user_id, path), validate, run SafetyGateway.process_user_input, create or get conversation, send REQUEST to planner, wait on completion_event, then send response/timeout and close. Args: websocket: WebSocket connection (accept() called by route); bus, manager, safety_gateway, timeout_seconds: from app.state.`

**Example usage:** Called by FastAPI @app.websocket("/ws") after accept().

---

# scripts/

**Purpose:** Operational entrypoints. `scripts/run.sh` is the recommended command: it starts local backends (when configured), seeds data, loads funds, starts the API, and by default launches the interactive chat client (`scripts/chat_cli.py`). Use `--no-chat` to start the API only.

---

## scripts/run.sh

**Purpose:** Single entrypoint for live runtime. Handles `.env` bootstrap, optional dependency install, optional local backend start (PostgreSQL/Neo4j/Milvus when configured), optional `python -m data_manager populate`, optional fund distribution load mode (`existing`, `fresh-symbols`, `fresh-all`, `skip`). By default starts the API in the background, waits for it to be ready, runs `scripts/chat_cli.py` in the foreground, and on chat exit kills the server. With `--no-chat`, execs `python main.py --serve` (API only).

**Example usage:**
```bash
./scripts/run.sh
./scripts/run.sh --help
./scripts/run.sh --port 8010 --funds fresh-symbols
./scripts/run.sh --no-chat
```

---

## scripts/chat_cli.py

**Purpose:** Interactive terminal chat client. Prompts "You: ", POSTs the line to `http://127.0.0.1:{port}/chat` with `query` and `user_profile`, prints "Assistant: <response>". Handles 200 (success), 408 (timeout), 400/422/404/500 (errors) and connection failures. Exits on empty input, "quit"/"exit"/"q", or EOF. Intended to be run after the API is started (e.g. by run.sh). Args: `--port` (default 8000), `--profile` (beginner | long_term | analyst, default beginner).

---

## scripts/test_librarian.py

**Purpose:** Single script to test all Librarian agent functions and MCP tools it uses. Runs: `combine_results`, `retrieve_documents` (vector_tool.search), `retrieve_knowledge_graph` (kg_tool.get_relations), and `handle_message` with path (file_tool), vector_query (vector_tool), fund (kg_tool), sql_query (sql_tool with schema-aligned query). Uses real backends when DATABASE_URL, NEO4J_URI, MILVUS_URI are set; otherwise tools return mock/empty. Run from project root: `python3 scripts/test_librarian.py`. Optional: `--skip-file`, `--skip-vector`, `--skip-kg`, `--skip-sql`.

---

# data_manager/

**Purpose:** Data collection, distribution, and backend CLI entrypoint. Includes both direct backend commands (`populate`, `sql`, `neo4j`, `milvus`) and collection/distribution commands (`collect`, `distribute`, `distribute-funds`, `status`, `list`, `global-news`). See [data-manager-agent.md](data-manager-agent.md) for full design.

---

## data_manager/backend_cli.py

**Purpose:** Backend maintenance subcommands for `python -m data_manager`. Registers populate, sql, neo4j, milvus via `add_backend_subcommands(subparsers)`; __main__.py calls it so these commands appear under the data_manager CLI.

**Functions:**
- `add_backend_subcommands(subparsers)` — Add subparsers for populate, sql, neo4j, milvus and set their `func` to the corresponding cmd_*.
- `run_populate()` — Seed PostgreSQL, Neo4j, and Milvus demo data (idempotent); calls load_config(), then sql_tool.populate_demo(), kg_tool.populate_demo(), vector_tool.populate_demo().
- `cmd_populate(_args)` — Handler for `data_manager populate`.
- `cmd_sql(args)` — Run a SQL query via sql_tool.run_query; requires DATABASE_URL; prints JSON (rows, schema) or error.
- `cmd_neo4j(args)` — Run a Cypher query via kg_tool.query_graph; requires NEO4J_URI.
- `cmd_milvus_index(args)` — Index documents into Milvus (as registered).
- `cmd_milvus_delete(args)` — Delete by source or filter (as registered).

---

## data_manager/collector.py

**Purpose:** Fetch data from MCP market_tool and analyst_tool, save as structured JSON files locally.

**Class:** `DataCollector`

**Methods:**
- `collect_symbol(symbol: str, as_of_date: str) -> CollectionResult` — Collect all data for a single symbol
- `collect_batch(symbols: list[str], as_of_date: str) -> BatchResult` — Batch collect for multiple symbols

---

## data_manager/distributor.py

**Purpose:** Read local JSON files and distribute to PostgreSQL, Neo4j, and Milvus via MCP tools.

**Class:** `DataDistributor`

**Methods:**
- `distribute_file(filepath: str) -> DistributionResult` — Distribute a single file
- `distribute_symbol(symbol: str, as_of_date: str) -> BatchResult` — Distribute all files for a symbol
- `distribute_pending() -> BatchResult` — Distribute all pending files
- `distribute_fund_file(filepath: str, load_mode: str, fresh_scope: str) -> BatchResult` — Distribute combined fund JSON with `existing` or `fresh` load behavior
- `_purge_fund_data(symbols: list[str], scope: str)` — Purge old fund rows before fresh loads (`symbols` or `all`)
- `_write_to_postgres(table: str, rows: list[dict]) -> int` — Write via sql_tool
- `_write_to_neo4j(nodes: list, edges: list) -> int` — Write via kg_tool
- `_write_to_milvus(docs: list[dict]) -> int` — Write via vector_tool

---

## data_manager/classifier.py

**Purpose:** Route data to appropriate database based on task_type and content characteristics.

**Class:** `DataClassifier`

**Constants:**
- `STATIC_ROUTING` — task_type → database mapping (e.g. "stock_data" → "postgres")
- `MULTI_TARGET` — task_types that write to multiple databases (e.g. "fundamentals" → ["postgres", "neo4j"])

**Methods:**
- `classify(task_type: str, content: dict) -> ClassificationResult` — Return targets and sub_types

---

## data_manager/transformer.py

**Purpose:** Transform raw data to formats required by each database.

**Class:** `DataTransformer`

**Methods:**
- `to_postgres_rows(task_type: str, symbol: str, content: dict) -> list[dict]` — Transform to PostgreSQL rows
- `to_neo4j_nodes_edges(task_type: str, symbol: str, content: dict) -> tuple[list, list]` — Transform to Neo4j nodes/edges
- `to_milvus_docs(task_type: str, symbol: str, content: dict) -> list[dict]` — Transform to Milvus documents

---

## data_manager/tasks.py

**Purpose:** CollectionTask definitions and COLLECTION_TASKS registry.

**Dataclass:** `CollectionTask` — task_type, tool_name, payload_builder, output_filename

**Constant:** `COLLECTION_TASKS` — List of predefined collection tasks (stock_data, balance_sheet, cashflow, income_statement, insider_transactions, indicators, news, etc.)

---

## data_manager/schemas.py

**Purpose:** Database schema definitions (PostgreSQL DDL, Neo4j node/edge patterns, Milvus collection schema).

---

## data_manager/__main__.py

**Purpose:** Entry point for `python -m data_manager`; parses CLI args, calls `add_backend_subcommands(subparsers)` for backend commands (populate, sql, neo4j, milvus), and implements collect/distribute/status/list/global-news/distribute-funds.

**Usage:**
```bash
python -m data_manager collect --symbols NVDA,AAPL --date 2024-01-15
python -m data_manager distribute --symbol NVDA
python -m data_manager distribute --all
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode existing
python -m data_manager distribute-funds --file datasets/combined_funds.json --load-mode fresh --fresh-scope symbols
python -m data_manager status --symbol NVDA
```

---

# safety/safety_gateway.py

**Purpose:** Layer 2 — Single entry for user input: validate length/charset, check guardrails (block list), mask PII. All user input should go through process_user_input.

---

## Dataclasses: `ValidationResult`, `GuardrailResult`, `ProcessedInput`

**Purpose:** Typed results for validate_input (valid, reason), check_guardrails (allowed, reason), and process_user_input (text, raw_length, masked).

---

## Class: `SafetyGateway`

**Docstring:** `Single entry point before user input reaches the message bus. Runs validation, guardrails (block list for illegal advice), and PII masking.`

---

## Method: `SafetyGateway.validate_input(self, text: str) -> ValidationResult`

**Purpose:** Basic checks (e.g. length, charset).

**Docstring:** `Basic sanity checks: length, charset. Args: text: Raw user input. Returns: ValidationResult with valid flag and optional reason.`

**Example usage:**
```python
r = gateway.validate_input("What is fund X?")
assert r.valid
```

---

## Method: `SafetyGateway.check_guardrails(self, text: str) -> GuardrailResult`

**Purpose:** Block list for illegal investment-advice phrases.

**Docstring:** `Block list for illegal investment-advice phrases. Args: text: User or content to check. Returns: GuardrailResult with allowed flag and optional reason.`

**Example usage:**
```python
r = gateway.check_guardrails("buy now")
assert not r.allowed
```

---

## Method: `SafetyGateway.mask_pii(self, text: str) -> str`

**Purpose:** Mask PII (e.g. phone, IDs) in text; return desensitized string.

**Docstring:** `Mask PII (IDs, phone numbers, etc.) in text. Args: text: Text that may contain PII. Returns: Desensitized string.`

**Example usage:**
```python
clean = gateway.mask_pii("Call 555-1234")
```

---

## Method: `SafetyGateway.process_user_input(self, raw_input: str) -> ProcessedInput`

**Purpose:** Run validate -> check_guardrails -> mask_pii; return ProcessedInput or raise/return error on failure.

**Docstring:** `Run validate -> check_guardrails -> mask_pii. Args: raw_input: Raw user query. Returns: ProcessedInput with cleaned text and metadata. Raises or returns error state if validation/guardrails fail.`

**Example usage:**
```python
processed = gateway.process_user_input("What is fund X performance?")
# processed.text, processed.masked
```

---

# output/output_rail.py

**Purpose:** Layer 6 — Final compliance check and user-profile formatting before returning the response to the user.

---

## Dataclass: `ComplianceResult`

**Purpose:** Result of check_compliance (passed, reason).

---

## Class: `OutputRail`

**Docstring:** `Final compliance and formatting before response is returned. Used by Responder: check_compliance then format_for_user.`

---

## Method: `OutputRail.check_compliance(self, text: str) -> ComplianceResult`

**Purpose:** Ensure output does not contain explicit buy/sell advice, etc.

**Docstring:** `Ensure output does not contain explicit buy/sell advice, etc. Args: text: Proposed response text. Returns: ComplianceResult with passed flag and optional reason.`

**Example usage:**
```python
r = rail.check_compliance(draft_response)
if not r.passed:
    rewrite(draft_response)
```

---

## Method: `OutputRail.format_for_user(self, text: str, user_profile: str) -> str`

**Purpose:** Adapt tone, length, and disclaimers to user type (e.g. beginner, long_term, analyst).

**Docstring:** `Adapt tone, length, and disclaimers to user type. Args: text: Draft response text. user_profile: User type (e.g. beginner, long_term, analyst). Returns: Formatted string for the user.`

**Example usage:**
```python
final = rail.format_for_user(draft, "beginner")
```

---

# config/config.py

**Purpose:** Load application configuration from environment variables (MILVUS_*, NEO4J_*, TAVILY_*, ANALYST_*, MCP, LLM_*, DATABASE_URL, EMBEDDING_*, thresholds, flags). Automatically loads project-root `.env` when `python-dotenv` is installed; defaults are empty/None or typed defaults when unset.

---

## Class: `Config` (dataclass)

**Purpose:** Hold all config fields; used by MCP tools and agents.

**Docstring:** Describes attributes including milvus_*, neo4j_*, tavily_api_key, yahoo_*, analyst_api_*, mcp_server_endpoint, llm_*, memory_store_path, e2e_timeout_seconds, database_url, embedding_*, planner/analyst/responder thresholds, max_research_rounds, and interaction_log_enabled.

**Example usage:** `cfg = load_config(); print(cfg.milvus_uri)`

---

## Function: `load_config() -> Config`

**Purpose:** Read env with os.getenv and return a populated Config instance.

**Docstring:** `Load configuration from environment variables. Reads MILVUS_*, NEO4J_*, TAVILY_API_KEY, ANALYST_API_*, MCP server endpoint, DATABASE_URL, EMBEDDING_*, thresholds, and optional LLM/feature flags; optional YAHOO_* (unused by market_tool). Returns: Config instance populated from env.`

**Example usage:**
```python
from config.config import load_config
cfg = load_config()
# cfg.analyst_api_url, cfg.neo4j_uri, etc.
```

---

# llm/base.py

**Purpose:** Abstract interface for LLM-backed task decomposition and completion. Defines the LLMClient protocol used by PlannerAgent (decompose_to_steps) and optionally ResponderAgent (complete) when LLM_API_KEY is set (Stage 10.2).

---

## Class: `LLMClient` (Protocol)

**Purpose:** Protocol for LLM clients used by Planner/specialists and Responder. Runtime app wiring uses a live client via `llm.factory.get_llm_client()` and requires `LLM_API_KEY`.

**Method: `decompose_to_steps(self, query: str) -> list[dict[str, Any]]`**

**Purpose:** Turn a user query into a list of task steps. Each step is a dict with keys: agent (str), params (dict). Allowed agents: "librarian", "websearcher", "analyst".

**Args:** query — Raw user investment query.

**Returns:** List of step dicts, e.g. [{"agent": "librarian", "params": {"query": "..."}}].

**Method: `complete(self, system_prompt: str, user_content: str) -> str`**

**Purpose:** Produce a completion given system and user content. Used optionally by Responder (and other agents). Static client returns user_content unchanged; live client calls the LLM.

---

# llm/prompts.py

**Purpose:** Central prompts for all agents; single source of truth aligned with PRD and user-flow.

**Constants:** PLANNER_DECOMPOSE (task decomposition for Planner), LIBRARIAN_SYSTEM (retrieve/combine for Librarian; optional LLM), WEBSEARCHER_SYSTEM (market/sentiment/regulatory for WebSearcher; optional LLM), WEBSEARCHER_TOOL_SELECTION (WebSearcher MCP tool planner), WEBSEARCHER_NEWS_FALLBACK_SYSTEM (LLM-only headline lines when all news APIs fail; used by `WebSearcherAgent._llm_news_fallback`), WEBSEARCHER_LLM_FALLBACK_SYSTEM (LLM paragraph when all market tools fail; used by `_llm_data_search_fallback`), WEBSEARCHER_CONFLICT_RESOLUTION_SYSTEM (stooq vs Yahoo price conflict; used by `_resolve_conflict_with_llm`), ANALYST_SYSTEM (quantitative analysis summary for Analyst; optional LLM), RESPONDER_SYSTEM (final user-facing answer by profile for Responder; used when llm_client set).

**Function: `get_responder_user_content(user_profile: str, aggregated_research: str) -> str`**

**Purpose:** Build user message for Responder LLM complete() call (user_profile + aggregated_research).

**Function: `get_librarian_user_content(query: str, combined_data: Any) -> str`**

**Purpose:** Build user message for Librarian LLM complete() call (query + serialized combined_data).

**Function: `get_websearcher_user_content(query: str, fetched_data: Any) -> str`**

**Purpose:** Build user message for WebSearcher LLM complete() call (query + serialized fetched_data).

**Function: `get_analyst_user_content(structured_data: Any, market_data: Any) -> str`**

**Purpose:** Build user message for Analyst LLM complete() call (structured_data + market_data).

**Function: `_data_summary(data: Any, max_chars: int = 4000) -> str`**

**Purpose:** Serialize dict/list to string for LLM user content; truncate if longer than max_chars.

---

# llm/static_client.py

**Purpose:** Static mock LLM client: returns a fixed task decomposition. Useful for tests or local mocking; not used by default API startup path in current code.

---

## Constant: `DEFAULT_STATIC_STEPS`

**Purpose:** Default one-round steps (librarian read_file, websearcher fetch_market, analyst analyze); same as PlannerAgent fallback before LLM.

---

## Class: `StaticLLMClient`

**Purpose:** Mock LLM client that returns a fixed list of steps.

**Method: `__init__(self, steps: list[dict[str, Any]] | None = None) -> None`**

**Purpose:** Initialize with optional custom steps; defaults to DEFAULT_STATIC_STEPS.

**Method: `decompose_to_steps(self, query: str) -> list[dict[str, Any]]`**

**Purpose:** Return static steps with query filled into params for each step.

**Method: `complete(self, system_prompt: str, user_content: str) -> str`**

**Purpose:** Return user_content unchanged (no LLM call).

---

# llm/live_client.py

**Purpose:** Live LLM client (OpenAI). Used when LLM_API_KEY is set and openai is installed.

---

## Class: `LiveLLMClient`

**Purpose:** OpenAI-backed LLM client for task decomposition and completion. Uses PLANNER_DECOMPOSE from llm.prompts for decompose_to_steps.

**Method: `__init__(self, api_key: str, model: str = "gpt-4o-mini") -> None`**

**Purpose:** Store API key and model; lazy-initialize OpenAI client on first use.

**Method: `decompose_to_steps(self, query: str) -> list[dict[str, Any]]`**

**Purpose:** Call the LLM to decompose the query into steps; parse and validate. Uses PLANNER_DECOMPOSE as system message. Returns the parsed list (which may be empty). On exception or parse failure (_parse_steps returns None), falls back to DEFAULT_STATIC_STEPS with query injected. When the client returns an empty list, the planner uses a single analyst step.

**Method: `complete(self, system_prompt: str, user_content: str) -> str`**

**Purpose:** Call the LLM for a single completion (e.g. Responder format_response). On failure returns user_content.

**Method: `_parse_steps(self, text: str, query: str) -> list[dict[str, Any]]`**

**Purpose:** Extract JSON array from LLM response (strip markdown code fence if present), validate agent names (librarian, websearcher, analyst), and return list of step dicts. Per-step query is taken from params.query or top-level "query"; the user query is used only when the step has neither. Returns None on parse failure; returns [] when the LLM returned a valid empty array.

---

# llm/factory.py

**Purpose:** Factory for runtime LLM client creation. Returns `LiveLLMClient` when configuration is valid; raises a clear error when `LLM_API_KEY` is missing or `llm` extra is not installed.

---

## Function: `get_llm_client(config: Config) -> LLMClient`

**Purpose:** Return a live LLM client for task decomposition/completion. Requires `LLM_API_KEY` and optional dependency `openfund-ai[llm]`; otherwise raises (`ValueError` for missing key, `ImportError` for missing extra). StaticLLMClient is used only by explicit callers (tests or `main.py --e2e-once` fallback path).

**Returns:** `LLMClient` implementation (live client).

---

# memory/situation_memory.py

**Purpose:** BM25-based storage of (situation, recommendation) pairs with persistence. Used for "similar past situations" retrieval; persisted at `{MEMORY_STORE_PATH}/situation_memory.json`. No dependency on TradingAgents package.

---

## Constant: `SITUATION_MEMORY_FILENAME`

**Purpose:** Default filename under MEMORY_STORE_PATH: `situation_memory.json`.

---

## Function: `get_situation_memory(memory_store_path: str = "memory") -> FinancialSituationMemory`

**Purpose:** Return the shared situation-memory singleton; loads from disk if the file exists.

**Example usage:** `mem = get_situation_memory(cfg.memory_store_path); mem.get_memories("current situation", n_matches=2)`

---

## Class: `FinancialSituationMemory`

**Purpose:** In-memory BM25 index over (situation, recommendation) pairs; supports save/load to JSON. Constructor accepts optional `_config` (reserved for API compatibility; unused).

---

## Method: `FinancialSituationMemory.add_situations(self, situations_and_advice: List[Tuple[str, str]]) -> None`

**Purpose:** Append pairs and rebuild the BM25 index.

---

## Method: `FinancialSituationMemory.get_memories(self, current_situation: str, n_matches: int = 1) -> List[dict]`

**Purpose:** Return top-n matches. Each dict has `matched_situation`, `recommendation`, `similarity_score`.

---

## Method: `FinancialSituationMemory.clear(self) -> None`

**Purpose:** Clear all documents and recommendations; reset index.

---

## Method: `FinancialSituationMemory.save(self, path: str | os.PathLike[str]) -> None`

**Purpose:** Write (situation, recommendation) pairs to JSON; creates parent dirs if needed.

---

## Method: `FinancialSituationMemory.load(self, path: str | os.PathLike[str]) -> None`

**Purpose:** Load pairs from JSON and rebuild BM25 index; no-op if file does not exist.

---

## Method: `FinancialSituationMemory.load_from_dir(self, memory_store_path: str) -> None`

**Purpose:** Load from `memory_store_path/situation_memory.json` if present; no-op if missing.

---

# main.py

**Purpose:** Entry point. If `--e2e-once` in sys.argv: run one E2E conversation via _run_e2e_once() (api → planner → librarian + websearcher + analyst → responder) and exit 0. Otherwise load config, optionally initialize situation memory via get_situation_memory(memory_store_path), then start FastAPI/uvicorn by default. `--no-serve` disables server start.

---

## Function: `_run_e2e_once() -> None`

**Purpose:** Run one E2E conversation (Slice 5): wire InMemoryMessageBus, ConversationManager, MCPServer (register_default_tools), MCPClient, and all five agents (PlannerAgent, LibrarianAgent, WebSearcherAgent, AnalystAgent, ResponderAgent) with shared llm_client. It first tries `get_llm_client(cfg)` and falls back to `StaticLLMClient` if key/dependency is missing. Starts agent threads, creates a temp file, sends REQUEST to planner with path, blocks on completion_event, and exits 0.

---

## Function: `main() -> None`

**Purpose:** If --e2e-once: call _run_e2e_once() and return. Otherwise load config, optionally load situation memory, then run uvicorn (`--serve` explicit or default behavior). Supports `--port` override and `--no-serve` for config-only startup.

**Docstring:** `Initialize and start the OpenFund-AI stack. If --e2e-once in sys.argv, runs one E2E conversation and exits. Otherwise loads config, optionally get_situation_memory(memory_store_path), and runs uvicorn unless --no-serve is provided.`

**Example usage:**
```bash
PYTHONPATH=. python main.py
# Starts live API server on port 8000 by default

PYTHONPATH=. python main.py --serve --port 8010
# Starts live API server on custom port

PYTHONPATH=. python main.py --e2e-once
# Runs one conversation across planner/librarian/websearcher/analyst/responder and exits 0
```

---

# mcp/mcp_client.py

**Purpose:** Client interface to the MCP tool server. All external data (Milvus, Neo4j, market via Alpha Vantage/Finnhub, Analyst API, Tavily when implemented) is accessed via call_tool; agents never call DBs or APIs directly.

---

## Class: `MCPClient`

**Docstring:** `Client interface for interacting with the MCP Tool Server. All external data access (Milvus, Neo4j, market tools, custom Analyst API) goes through this client.`

---

## Method: `MCPClient.call_tool(self, tool_name: str, payload: dict) -> dict`

**Purpose:** Invoke a tool on the MCP server by name with a payload; return the tool’s result dict.

**Docstring:** `Invoke a tool on the MCP server. Args: tool_name: Name of the tool (e.g. vector_tool.search, analyst_tool.run_analysis). payload: Tool-specific parameters. Returns: Tool response dict. Structure depends on the tool.`

**Example usage:**
```python
result = mcp_client.call_tool("file_tool.read_file", {"path": "CHANGELOG.md"})
# result["content"], result["path"]
```

---

# mcp/mcp_server.py

**Purpose:** Register tool handlers and dispatch incoming tool calls; catch exceptions and return error dicts.

---

## Class: `MCPServer`

**Docstring:** `Registers tool handlers and dispatches incoming tool calls. Tools (file_tool, vector_tool, kg_tool, sql_tool, market_tool, analyst_tool) are implemented as handlers; dispatch invokes them and returns results. Use register_default_tools() to register all default tools (file_tool first, then vector/kg/sql, then market_tool and analyst_tool if imports succeed).`

---

## Method: `MCPServer.__init__(self) -> None`

**Purpose:** Initialize empty handler registry (_handlers dict).

---

## Method: `MCPServer.register_tool(self, name: str, handler: Callable[..., Any]) -> None`

**Purpose:** Register a callable as the handler for a tool name.

**Docstring:** `Register a tool by name. Args: name: Tool name (e.g. 'vector_tool.search'). handler: Callable that accepts payload and returns result dict.`

**Example usage:**
```python
server.register_tool("read_file", lambda payload: read_file(payload["path"]))
```

---

## Method: `MCPServer.dispatch(self, tool_name: str, payload: dict) -> dict`

**Purpose:** Invoke the named tool’s handler with payload; return result dict or error dict on failure.

**Docstring:** `Invoke the named tool with the given payload. Args: tool_name: Name of the tool to invoke. payload: Tool-specific parameters. Returns: Result dict from the tool. Returns {"error": "..."} if tool unknown or handler raises.`

**Example usage:**
```python
result = server.dispatch("read_file", {"path": "CHANGELOG.md"})
```

---

## Method: `MCPServer.register_default_tools(self) -> None`

**Purpose:** Register file_tool first (read_file); then vector_tool.search, kg_tool.query_graph, kg_tool.get_relations, sql_tool.run_query; then community-common tools (kg_tool.get_node_by_id, get_neighbors, get_graph_schema; sql_tool.explain_query, export_results, connection_health_check; vector_tool.get_by_ids, upsert_documents, health_check); get_capabilities last. Then market_tool and analyst_tool only if imports succeed (optional deps e.g. pandas). Each handler receives the MCP payload dict and passes required params to the underlying function. Vendor-agnostic tools (market_tool.get_stock_data, get_fundamentals, …, analyst_tool.get_indicators) route via MCP_MARKET_VENDOR and MCP_INDICATOR_VENDOR. Call after creating the server.

---

# mcp/tools/file_tool.py

**Purpose:** MCP tool for reading file content and listing files by prefix. When MCP_FILE_BASE_DIR is set, read_file only allows paths under that directory (path traversal protection). Used by agents via MCPClient.

---

## Function: `read_file(path: str) -> dict`

**Purpose:** Read file at path and return content and metadata. If MCP_FILE_BASE_DIR is set, path must resolve under that directory.

**Docstring:** `Read file content and metadata. Args: path: File path. Returns: Dict with content and metadata.`

**Example usage:**
```python
from mcp.tools.file_tool import read_file
out = read_file("CHANGELOG.md")
# out["content"], out["path"]
```

---

## Function: `list_files(prefix: str) -> List[str]`

**Purpose:** List file paths under a prefix.

**Docstring:** `List files under a prefix path. Args: prefix: Path prefix. Returns: List of file paths.`

**Example usage:**
```python
paths = list_files("docs/")
```

---

# mcp/tools/vector_tool.py

**Purpose:** MCP tool for semantic search and indexing over Milvus. Config: MILVUS_URI, MILVUS_COLLECTION. Seed helper: `populate_demo()` deletes by source=="demo", indexes two NVDA docs (caller loads .env).

---

## Function: `search(query: str, top_k: int, filter: Optional[Dict] = None) -> List[dict]`

**Purpose:** Run semantic search over the Milvus collection; return list of docs with scores.

**Docstring:** `Semantic search over Milvus collection. Args: query: Search query (will be embedded if needed). top_k: Maximum number of documents to return. filter: Optional filter on metadata. Returns: List of documents with scores. Config: MILVUS_URI, MILVUS_COLLECTION.`

**Example usage:**
```python
docs = search("fund X annual report", top_k=5)
```

---

## Function: `index_documents(docs: List[dict]) -> dict`

**Purpose:** Index or upsert documents into the Milvus collection.

**Docstring:** `Index or upsert documents into the Milvus collection. Args: docs: List of documents (each with content and optional metadata). Returns: Result dict (e.g. count indexed, status).`

**Example usage:**
```python
result = index_documents([{"content": "Fund X ...", "fund_id": "X"}])
```

---

## Function: `get_by_ids(ids: List[str], collection_name: Optional[str] = None) -> dict`

**Purpose:** Retrieve entities by primary key (id in ids). Returns `{"entities": [...]}`; mock when MILVUS_URI unset.

---

## Function: `upsert_documents(docs: List[dict]) -> dict`

**Purpose:** Insert or overwrite by primary key (each doc must have "id"). Returns `{"upserted": n, "status": "ok"}` or error when MILVUS_URI unset.

---

## Function: `health_check() -> dict`

**Purpose:** Ping Milvus; return `{"ok": true}` or `{"ok": false, "error": "..."}`. When MILVUS_URI unset return `{"ok": false, "error": "MILVUS_URI not set"}`.

---

## Function: `populate_demo() -> tuple[bool, str]`

**Purpose:** Seed baseline vector documents (source=="demo"). Uses MILVUS_URI. Returns (success, message). Caller should load .env first.

---

# mcp/tools/kg_tool.py

**Purpose:** MCP tool for Cypher and relation queries against Neo4j. Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD. Seed helper: `populate_demo()` MERGEs Company NVDA, Sector Technology, IN_SECTOR (caller loads .env).

---

## Function: `query_graph(cypher: str, params: Optional[Dict] = None) -> dict`

**Purpose:** Execute a Cypher query with optional parameters; return nodes/edges or result rows.

**Docstring:** `Execute a Cypher query against Neo4j. Args: cypher: Cypher query string. params: Optional query parameters. Returns: Dict with nodes/edges or result rows. Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.`

**Example usage:**
```python
result = query_graph("MATCH (f:Fund {id: $id})-[:MANAGED_BY]->(m) RETURN m", {"id": "X"})
```

---

## Function: `get_relations(entity: str) -> dict`

**Purpose:** Get relations for an entity (e.g. fund, manager).

**Docstring:** `Get relations for an entity (e.g. fund, manager). Args: entity: Entity identifier. Returns: Dict with related nodes/edges.`

**Example usage:**
```python
rels = get_relations("FUND_X")
```

---

## Function: `get_node_by_id(id_val: str, id_key: str = "id") -> dict`

**Purpose:** Look up a single node by id_key property; mock when NEO4J_URI unset. Returns `{"node": {...}}` or `{"error": "...", "node": None}`.

---

## Function: `get_neighbors(node_id: str, id_key: str = "id", direction: str = "both", relationship_type: Optional[str] = None, limit: int = 100) -> dict`

**Purpose:** Return 1-hop neighbors; direction in/out/both; optional relationship_type filter. Returns `{"nodes": [...], "relationships": [...]}`; mock when NEO4J_URI unset.

---

## Function: `get_graph_schema() -> dict`

**Purpose:** List node labels and relationship types. Returns `{"node_labels": [...], "relationship_types": [...]}`; mock when NEO4J_URI unset.

---

## Function: `populate_demo() -> tuple[bool, str]`

**Purpose:** MERGE Company NVDA, Sector Technology, IN_SECTOR edge. Uses NEO4J_URI. Returns (success, message). Keeps CredentialsExpired/Unauthorized hints in errors. Caller should load .env first.

---

# mcp/tools/market_tool.py

**Purpose:** MCP tool for market/company data and news. **Vendor config:** get_market_vendor(), get_indicator_vendor(), get_data_cache_dir() (env: MCP_MARKET_VENDOR, MCP_INDICATOR_VENDOR, MCP_DATA_CACHE_DIR). **Alpha Vantage common** (in this file): get_api_key(), format_datetime_for_api(), AlphaVantageRateLimitError, _make_api_request(), _filter_csv_by_date_range(), _now_iso(). analyst_tool imports AlphaVantageRateLimitError, _make_api_request, _now_iso from this module. `fetch`, `fetch_bulk`, and `search_web` remain stubs. Implemented: Alpha Vantage functions (`*_av`) and Finnhub functions (`*_finnhub`) where applicable, plus vendor-routing `_route_*` helpers (alpha_vantage/finnhub; no yfinance). Config: TAVILY_API_KEY (for future search_web), ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY.

---

## Function: `fetch(fund_or_symbol: str) -> dict`

**Purpose:** Fetch market data for a fund or symbol; return must include `timestamp`.

**Docstring:** `Fetch market data for a fund or symbol via MCP market_tool (Alpha Vantage or Finnhub). Args: fund_or_symbol: Fund or ticker symbol. Returns: Market data dict; must include 'timestamp'. Config: MCP_MARKET_VENDOR, ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY.`

**Example usage:**
```python
data = fetch("FUND_X")
assert "timestamp" in data
```

---

## Function: `fetch_bulk(symbols: List[str]) -> dict`

**Purpose:** Fetch market data for multiple symbols; each value must include `timestamp`.

**Docstring:** `Fetch market data for multiple symbols. Args: symbols: List of symbols. Returns: Dict keyed by symbol; each value must include 'timestamp'.`

---

## Function: `search_web(query: str) -> List[dict]`

**Purpose:** Web search via Tavily (e.g. regulatory, sentiment); each result must include `timestamp`.

**Docstring:** `Web search via Tavily (e.g. regulatory, sentiment). Args: query: Search query. Returns: List of results; each must include 'timestamp'.`

---

# mcp/tools/analyst_tool.py

**Purpose:** MCP tool for quantitative/statistical analysis. run_analysis(payload): POST to custom Analyst API (payload dict). get_indicators_av(...): Alpha Vantage technical indicators (same file). **_route_indicators** calls get_indicators_av; on failure returns error (no yfinance). Timestamps use _now_iso() imported from market_tool. MCP handler decomposes payload into symbol, indicator, as_of_date, look_back_days. Returns include `timestamp`. Config: ANALYST_API_URL, optional ANALYST_API_KEY; MCP_INDICATOR_VENDOR via market_tool.

---

## Function: `run_analysis(payload: dict) -> dict`

**Purpose:** POST payload to the custom Analyst API; return response dict (e.g. metrics, distribution).

**Docstring:** `POST to custom Analyst API (e.g. Sharpe, max_drawdown, Monte Carlo). Payload and response schema are defined by the custom API. Args: payload: Request body (e.g. returns, horizon, n_sims). Returns: Response dict (e.g. metrics, distribution). Config: ANALYST_API_URL, optional ANALYST_API_KEY.`

**Example usage:**
```python
result = run_analysis({"returns": [0.01, -0.02], "horizon": 12, "n_sims": 1000})
# result["sharpe"], result["max_drawdown"], result["distribution"]
```

---

## Function: `get_indicators(symbol: str, indicator: str, as_of_date: str, look_back_days: int) -> dict` _(via _route_indicators)_

**Purpose:** Compute technical indicators (e.g. SMA, RSI, MACD) from OHLCV via Alpha Vantage; return content and timestamp.

**Docstring:** Payload is decomposed into symbol, indicator (close_50_sma, close_200_sma, rsi, macd, etc.), **as_of_date** (yyyy-mm-dd), look_back_days (int). _route_indicators calls get_indicators_av. Returns `{"content": str, "timestamp": str}` or `{"error": str}`.

**Example usage:**
```python
result = get_indicators("AAPL", "close_50_sma", "2024-01-15", 10)
```

---

# mcp/tools/sql_tool.py

**Purpose:** MCP tool for executing SQL queries with optional parameters. Returns rows and optional schema. Seed helper: `populate_demo()` creates funds table and inserts NVDA (uses DATABASE_URL; caller loads .env).

---

## Function: `run_query(query: str, params: Optional[Dict] = None) -> dict`

**Purpose:** Execute a SQL query; return dict with rows and optional schema.

**Docstring:** `Execute a SQL query with optional parameters. Args: query: SQL query string. params: Optional query parameters. Returns: Dict with rows and optional schema.`

**Example usage:**
```python
result = run_query("SELECT * FROM funds WHERE id = :id", {"id": "X"})
```

---

## Function: `explain_query(query: str, params: Optional[Dict] = None, analyze: bool = False) -> dict`

**Purpose:** Run EXPLAIN or EXPLAIN ANALYZE for a read-only query; return plan rows. Only SELECT/EXPLAIN allowed. Mock when DATABASE_URL unset.

---

## Function: `export_results(query: str, params: Optional[Dict] = None, format: str = "json", row_limit: int = 1000) -> dict`

**Purpose:** Execute read-only SELECT, apply row_limit; return data as JSON (list of dicts) or CSV string. Mock when DATABASE_URL unset.

---

## Function: `connection_health_check() -> dict`

**Purpose:** Execute SELECT 1; return `{"ok": true}` or `{"ok": false, "error": "..."}`. When DATABASE_URL unset return `{"ok": false, "error": "DATABASE_URL not set"}`.

---

## Function: `populate_demo() -> tuple[bool, str]`

**Purpose:** Create funds table (if not exists) and insert NVDA row. Uses DATABASE_URL. Returns (success, message). Caller should load .env first.

---

# mcp/tools/capabilities.py

**Purpose:** Introspection of which backends and tools are available. Used by MCP tool `get_capabilities`.

---

## Function: `get_capabilities(tool_names: List[str]) -> dict`

**Purpose:** Return which backends are configured (neo4j, postgres, milvus from env) and which tools are registered. Args: tool_names from server._handlers.keys(). Returns `{"neo4j": bool, "postgres": bool, "milvus": bool, "tools": sorted list including get_capabilities}`.

---

# tests/test-stages.py

**Purpose:** Single test file for staged implementation. Tests are **standalone functions** named `test_stage_X_Y` (e.g. `test_stage_1_1`, `test_stage_1_2`, `test_stage_2_1`). Run full suite: `pytest tests/test-stages.py -v`. Run a subset: `pytest tests/test-stages.py -k stage_1_2 -v`. Per-stage assertions and commands: see [progress.md](progress.md) and [test_plan.md](test_plan.md). Additional unit tests for community-common tools: tests/test_kg_tool.py, tests/test_sql_tool.py, tests/test_vector_tool.py, tests/test_capabilities.py.

---

## Design Constraints

- All inter-agent communication uses **ACLMessage** only.
- All external data (Milvus, Neo4j, market tools, Analyst API) is accessed **only via MCP** (no direct DB/API access from agents).
- **Termination** is decided only by **Responder**; it calls `conversation_manager.broadcast_stop(conversation_id)`.
- **Planner** decides who to call (Librarian, WebSearcher, Analyst or combination), runs the planner sufficiency check, and either sends consolidated data to Responder or starts refined planner round(s).
- **Tests:** One file `tests/test-stages.py`; tests are functions named `test_stage_X_Y` (see [test_plan.md](test_plan.md)).
