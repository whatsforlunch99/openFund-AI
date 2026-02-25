# File-Structure Document

Directory layout, module boundaries, file responsibilities, and per-function (name, responsibility, inputs, outputs, side effects, example usage). See [backend.md](backend.md) for API and architecture, [prd.md](prd.md) for product intent, [user-flow.md](user-flow.md) for user flow.

---

## Project Structure

```
OpenFund-AI/
├── agents/          # Planner, Librarian, WebSearcher, Analyst, Responder
├── a2a/             # ACLMessage, MessageBus, ConversationManager
├── api/             # REST and WebSocket (Layer 1)
├── safety/          # SafetyGateway (Layer 2)
├── output/          # OutputRail (Layer 6)
├── mcp/             # MCPClient, MCPServer, tools
├── config/          # Config, load_config
├── main.py
├── CHANGELOG.md     # User-visible and notable changes (see progress.md)
├── memory/          # (runtime) Conversation persistence; see backend.md § Persistence
├── tests/
│   └── test-stages.py   # Stage tests as functions test_stage_X_Y; run: pytest tests/test-stages.py -v or -k stage_1_2
└── docs/
    ├── user-flow.md
    ├── prd.md
    ├── backend.md
    ├── frontend.md
    ├── file-structure.md (this file)
    ├── test_plan.md
    ├── progress.md
    └── project-status.md
```

---

# a2a/acl_message.py

**Purpose:** Define the FIPA-ACL message type used for all agent-to-agent communication. Provides a dataclass with performative, sender, receiver, content, and optional conversation threading and timestamp.

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

**Purpose:** Assign default conversation_id (UUID) and timestamp if not provided.

**Docstring:** `Assign a unique conversation ID if not provided.`

**Example usage:** Called automatically when constructing `ACLMessage`; no direct call needed.

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

# a2a/conversation_manager.py

**Purpose:** Track conversation state (create, get, register replies) and send STOP via the message bus so agents stop processing a conversation.

---

## Class: `ConversationState`

**Purpose:** Snapshot of one conversation. Holds id, user_id, initial_query, messages, status, final_response, created_at, and completion_event for API blocking and persistence.

**Docstring:**
```text
Conversation state for API blocking and persistence.
Attributes:
    id: Conversation UUID (conversation_id).
    user_id: User identifier; empty string if anonymous.
    initial_query: Original user query.
    messages: Append-only log of ACLMessage dicts.
    status: "active" | "complete" | "error".
    final_response: Set by register_reply when Responder delivers answer; None until then.
    created_at: Creation datetime.
    completion_event: threading.Event; set when final_response is written; callers block with event.wait(timeout=...).
```

**Example usage:**
```python
state = ConversationState(conversation_id="abc", user_id="u1", initial_query="...", messages=[], status="active", final_response=None, created_at=..., completion_event=threading.Event())
```

---

## Class: `ConversationManager`

**Purpose:** Create conversations, look up state, register replies, and broadcast STOP.

**Docstring:** `Tracks conversations and sends STOP broadcasts via the message bus. Responsibilities: create conversation, get state, register replies, broadcast STOP.`

**Persistence:** Conversation state is written to `MEMORY_STORE_PATH` (see [backend.md](backend.md)) on create and on register_reply.

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

**Docstring:** `Start the agent event loop. Continuously receives messages for this agent and delegates to handle_message.`

**Example usage:** Typically run in a thread: `threading.Thread(target=agent.run, daemon=True).start()`

---

## Method: `BaseAgent.handle_message(self, message: ACLMessage) -> None` (abstract)

**Purpose:** Process one received ACL message; each agent type implements its own logic.

**Docstring:** `Process an incoming ACL message. Args: message: The received ACL message.`

**Example usage:** Implement in subclass; e.g. Planner parses content and sends requests to Librarian/WebSearcher/Analyst.

---

# agents/planner_agent.py

**Purpose:** Orchestrate research: decompose the user query into steps, decide which agents to call (Librarian, WebSearcher, Analyst or combination), and when information is sufficient send to Responder; otherwise request more from agents with refined queries.

---

## Class: `TaskStep`

**Purpose:** One step in a decomposed task chain (agent target, action, and optional params).

**Docstring:**
```text
Single step in a decomposed task chain.
Attributes:
    agent: Target agent: "librarian" | "websearcher" | "analyst".
    action: Step type (e.g. retrieve_fund_facts, answer_question).
    params: Optional parameters for the step (forwarded as ACLMessage content extras).
```

**Example usage:**
```python
step = TaskStep(agent="librarian", action="retrieve_fund_facts", params={"fund": "X"})
```

---

## Class: `PlannerAgent(BaseAgent)`

**Purpose:** Decompose queries, create research requests, and route to Librarian/WebSearcher/Analyst or Responder based on sufficiency of information.

**Docstring:** `Decomposes user queries into structured tasks and initiates conversations. Creates research requests for Librarian, WebSearcher, and Analyst.`

---

## Method: `PlannerAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Parse incoming message, call decompose_task and create_research_request, send ACLMessages to the chosen agent(s); handle STOP.

**Docstring:** `Handle incoming messages directed to the Planner. Parse content, call decompose_task, create and send research requests via the bus; handle STOP. Args: message: The received ACL message.`

**Example usage:** Invoked by the base run() loop when a message for the planner arrives.

---

## Method: `PlannerAgent.decompose_task(self, query: str) -> List[TaskStep]`

**Purpose:** Turn the user query into an ordered list of task steps (e.g. retrieve_fund_facts then answer_question).

**Docstring:**
```text
Produce a ReAct-style task chain from the user query.
Args:
    query: Raw user investment query.
Returns:
    Ordered list of task steps.
```

**Example usage:**
```python
steps = planner.decompose_task("Should I buy fund X?")
```

---

## Method: `PlannerAgent.create_research_request(self, query: str, step: TaskStep, context: Optional[Dict[str, Any]] = None) -> ACLMessage`

**Purpose:** Build an ACL request message for Librarian, WebSearcher, or Analyst.

**Docstring:**
```text
Build a request ACL message for Librarian, WebSearcher, or Analyst.
Args:
    query: User query.
    step: Current task step.
    context: Optional prior context.
Returns:
    ACL message addressed to the appropriate agent.
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

**Purpose:** Answer data retrieval requests using MCP vector_tool (Milvus) and kg_tool (Neo4j); combine results and send reply back (to Planner or as specified by protocol).

---

## Class: `LibrarianAgent(BaseAgent)`

**Purpose:** Retrieve documents and knowledge-graph data via MCP only; no direct DB access.

**Docstring:** `Retrieves structured data from knowledge graph and vector database. Uses MCP vector_tool (Milvus) and kg_tool (Neo4j); does not access databases directly.`

---

## Method: `LibrarianAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Parse request, call retrieve_documents and retrieve_knowledge_graph via MCP, combine_results, send reply ACLMessage.

**Docstring:** `Process data retrieval requests. Parse request, call MCP vector_tool and kg_tool, combine_results, send reply ACL message. Args: message: The received ACL message.`

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

**Purpose:** Fetch real-time market, sentiment, and regulatory data via MCP market_tool (Tavily + Yahoo). All returned data must include a timestamp.

---

## Class: `WebSearcherAgent(BaseAgent)`

**Docstring:** `Fetches real-time market and regulatory information. Uses MCP market_tool (Tavily + Yahoo APIs). All returned data must include a timestamp.`

---

## Method: `WebSearcherAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Process requests, call fetch_market_data / fetch_sentiment / fetch_regulatory via MCP, send reply with timestamp in content.

**Docstring:** `Process market/sentiment/regulatory requests. Args: message: The received ACL message.`

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

**Purpose:** Run quantitative analysis (e.g. Sharpe, max drawdown, Monte Carlo) using MCP analyst_tool (custom API) or local helpers; decide if more data is needed and send either refinement request to Planner or result to Planner (Planner then sends consolidated data to Responder when sufficient).

---

## Class: `AnalystAgent(BaseAgent)`

**Docstring:** `Performs quantitative reasoning and uncertainty estimation. Uses MCP analyst_tool (custom API) for heavy quant; may use local helpers for sharpe_ratio, max_drawdown, monte_carlo_simulation.`

---

## Method: `AnalystAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Receive structured_data and market_data from content; call analyze; if needs_more_data send refinement to Planner else send result to Planner (INFORM to planner).

**Docstring:** `Process analysis requests: receive structured_data and market_data, call analyze; if needs_more_data send refinement request else send result to Planner (INFORM). Args: message: The received ACL message.`

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

**Purpose:** Decide whether another research cycle is needed.

**Docstring:** `Determine if additional information is required for refinement. Args: analysis_result: Current analysis output. Returns: True if another research cycle is needed.`

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

**Purpose:** Evaluate confidence in the analysis; decide whether to terminate or request refinement; when terminating, format response via OutputRail, check compliance, send final response, and call conversation_manager.broadcast_stop. Only this agent may trigger STOP.

---

## Class: `ResponderAgent(BaseAgent)`

**Docstring:** `Evaluates sufficiency and terminates or continues the research loop. Uses OutputRail for compliance check and user-profile formatting. Only this agent may trigger STOP.`

---

## Method: `ResponderAgent.handle_message(self, message: ACLMessage) -> None`

**Purpose:** Receive analysis; evaluate_confidence; if not should_terminate send request_refinement to Planner; else format_response via OutputRail, check_compliance, send final response, broadcast_stop.

**Docstring:** `Receive analysis; evaluate_confidence; if not should_terminate send request_refinement else run OutputRail and send final response; optionally broadcast_stop. Args: message: The received ACL message (analysis payload).`

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

**Purpose:** Build an ACL message back to the Planner to request another research cycle.

**Docstring:** `Build message back to Planner for another research cycle. Args: reason: Why refinement is needed. Returns: ACL message addressed to Planner.`

**Example usage:**
```python
refinement_msg = agent.request_refinement("low confidence on drawdown")
bus.send(refinement_msg)
```

---

# api/rest.py

**Purpose:** Layer 1 — REST API. Provide FastAPI app with POST /chat and GET /conversations/{id}. Flow: validate body, SafetyGateway, create or get conversation, send to Planner, wait for response, return JSON.

---

## Function: `create_app() -> Any`

**Purpose:** Build and return the FastAPI application with chat and conversation routes wired to shared state (bus, manager, safety, mcp_client).

**Docstring:** `Create FastAPI application with chat and conversation routes. Returns: FastAPI app instance.`

**Example usage:**
```python
app = create_app()
# uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Function: `post_chat(body: dict) -> dict`

**Purpose:** Handle POST /chat: validate body, process_user_input, create or load conversation, send ACLMessage to Planner, wait for response, return response dict.

**Docstring:**
```text
Handle POST /chat (or POST /research).
Flow: validate body -> SafetyGateway.process_user_input ->
create/load conversation -> send ACLMessage to Planner ->
wait for response (or stream) -> return.
Args:
    body: Request body with 'query'; optional 'conversation_id', 'user_profile'.
Returns:
    Response dict with conversation_id, message_id, status, response.
```

**Example usage:**
```python
result = post_chat({"query": "fund X performance", "user_profile": "beginner"})
# result["conversation_id"], result["response"]
```

---

## Function: `get_conversation(conversation_id: str) -> Optional[dict]`

**Purpose:** Handle GET /conversations/{id}: return conversation state or None.

**Docstring:** `Handle GET /conversations/{id}. Args: conversation_id: Conversation to fetch. Returns: Conversation state/messages or None if not found.`

**Example usage:**
```python
state = get_conversation("uuid-here")
```

---

# api/websocket.py

**Purpose:** Layer 1 — WebSocket handler. Same flow as POST /chat but stream partial responses over the socket.

---

## Function: `handle_websocket(websocket: Any) -> None`

**Purpose:** Accept WebSocket connection, receive query (and optional conversation_id, user_profile), run through SafetyGateway, post to bus, stream partial responses back.

**Docstring:** `Handle WebSocket /ws connection. Same semantics as POST /chat: receive query (and optional conversation_id, user_profile), run through SafetyGateway, post to MessageBus, stream partial responses back. Args: websocket: WebSocket connection object (e.g. FastAPI WebSocket).`

**Example usage:** Mounted as WebSocket route; called by FastAPI when client connects to /ws.

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

**Purpose:** Load application configuration from environment variables (MILVUS_*, NEO4J_*, TAVILY_*, YAHOO_*, ANALYST_*, MCP, LLM_*). No .env file required; defaults are empty or None.

---

## Class: `Config` (dataclass)

**Purpose:** Hold all config fields; used by MCP tools and agents.

**Docstring:** Describes attributes (milvus_uri, milvus_collection, neo4j_*, tavily_api_key, yahoo_*, analyst_api_*, mcp_server_endpoint, llm_*).

**Example usage:** `cfg = load_config(); print(cfg.milvus_uri)`

---

## Function: `load_config() -> Config`

**Purpose:** Read env with os.getenv and return a populated Config instance.

**Docstring:** `Load configuration from environment variables. Reads MILVUS_*, NEO4J_*, TAVILY_API_KEY, YAHOO_*, ANALYST_API_*, MCP server endpoint, and optional LLM/feature flags. Returns: Config instance populated from env.`

**Example usage:**
```python
from config.config import load_config
cfg = load_config()
# cfg.analyst_api_url, cfg.neo4j_uri, etc.
```

---

# main.py

**Purpose:** Entry point. Load config and (in full implementation) create MessageBus, ConversationManager, SafetyGateway, MCP client/server, agents, and start API and agent runners. Currently: load_config and print ready message.

---

## Function: `main() -> None`

**Purpose:** Initialize the stack: at minimum load config and print readiness; in full build wire bus, manager, safety, MCP, agents, and start FastAPI and agent threads.

**Docstring:** `Initialize and start the OpenFund-AI stack. Creates MessageBus (e.g. in-memory); calls bus.register_agent(name) for each agent (planner, librarian, websearcher, analyst, responder) at startup before any messages are sent; creates ConversationManager, SafetyGateway, MCP client (with config); instantiates all agents with bus and MCP client; starts FastAPI (REST + WebSocket) and agent runners; optionally starts MCP server.`

**Example usage:**
```bash
PYTHONPATH=. python main.py
# Prints: OpenFund-AI ready (config loaded)
```

---

# mcp/mcp_client.py

**Purpose:** Client interface to the MCP tool server. All external data (Milvus, Neo4j, Tavily, Yahoo, Analyst API) is accessed via call_tool; agents never call DBs or APIs directly.

---

## Class: `MCPClient`

**Docstring:** `Client interface for interacting with the MCP Tool Server. All external data access (Milvus, Neo4j, Tavily, Yahoo, custom Analyst API) goes through this client.`

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

**Docstring:** `Registers tool handlers and dispatches incoming tool calls. Tools (vector_tool, kg_tool, market_tool, analyst_tool, sql_tool, file_tool) are implemented as handlers; dispatch invokes them and returns results.`

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

**Docstring:** `Invoke the named tool with the given payload. Args: tool_name: Name of the tool to invoke. payload: Tool-specific parameters. Returns: Result dict from the tool. Handles errors and timeouts.`

**Example usage:**
```python
result = server.dispatch("read_file", {"path": "CHANGELOG.md"})
```

---

# mcp/tools/file_tool.py

**Purpose:** MCP tool for reading file content and listing files by prefix. Used by agents via MCPClient.

---

## Function: `read_file(path: str) -> dict`

**Purpose:** Read file at path and return content and metadata.

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

**Purpose:** MCP tool for semantic search and indexing over Milvus. Config: MILVUS_URI, MILVUS_COLLECTION.

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

# mcp/tools/kg_tool.py

**Purpose:** MCP tool for Cypher and relation queries against Neo4j. Config: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.

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

# mcp/tools/market_tool.py

**Purpose:** MCP tool for market data and web search via Tavily and Yahoo. All returns must include `timestamp`. Config: TAVILY_API_KEY, YAHOO_BASE_URL.

---

## Function: `fetch(fund_or_symbol: str) -> dict`

**Purpose:** Fetch market data for a fund or symbol; return must include `timestamp`.

**Docstring:** `Fetch market data for a fund or symbol (Yahoo and/or Tavily). Args: fund_or_symbol: Fund or ticker symbol. Returns: Market data dict; must include 'timestamp'. Config: TAVILY_API_KEY, YAHOO_BASE_URL.`

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

**Purpose:** MCP tool to POST analysis requests to the custom Analyst API. Payload and response schema are defined by that API. Config: ANALYST_API_URL, optional ANALYST_API_KEY.

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

# mcp/tools/sql_tool.py

**Purpose:** MCP tool for executing SQL queries with optional parameters. Returns rows and optional schema.

---

## Function: `run_query(query: str, params: Optional[Dict] = None) -> dict`

**Purpose:** Execute a SQL query; return dict with rows and optional schema.

**Docstring:** `Execute a SQL query with optional parameters. Args: query: SQL query string. params: Optional query parameters. Returns: Dict with rows and optional schema.`

**Example usage:**
```python
result = run_query("SELECT * FROM funds WHERE id = :id", {"id": "X"})
```

---

# tests/test-stages.py

**Purpose:** Single test file for staged implementation. Tests are **standalone functions** named `test_stage_X_Y` (e.g. `test_stage_1_1`, `test_stage_1_2`, `test_stage_2_1`). Run full suite: `pytest tests/test-stages.py -v`. Run a subset: `pytest tests/test-stages.py -k stage_1_2 -v`. Per-stage assertions and commands: see [progress.md](progress.md) and [test_plan.md](test_plan.md).

---

## Design Constraints

- All inter-agent communication uses **ACLMessage** only.
- All external data (Milvus, Neo4j, Tavily, Yahoo, Analyst API) is accessed **only via MCP** (no direct DB/API access from agents).
- **Termination** is decided only by **Responder**; it calls `conversation_manager.broadcast_stop(conversation_id)`.
- **Planner** decides who to call (Librarian, WebSearcher, Analyst or combination) and whether information is sufficient; when sufficient, sends to Responder; when not, sends refined requests to the appropriate agent(s).
- **Tests:** One file `tests/test-stages.py`; tests are functions named `test_stage_X_Y` (see [test_plan.md](test_plan.md)).
