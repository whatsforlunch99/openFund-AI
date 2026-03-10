"""Planner agent: task decomposition and research request creation."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util import interaction_log

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from llm.base import LLMClient

# Same allowed values as api/rest.py; normalize so Responder/OutputRail get consistent profile.
VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


class TaskStep:
    """Planner decompose tasks into many step, TaskStep holds target and instructions for the specific step.

    Attributes:
        agent: Target agent: "librarian" | "websearcher" | "analyst".
        params: Parameters for the step (including "query"); forwarded as ACLMessage content. Either a dict with string keys and values of any type, defaulting to None.
    """

    def __init__(
        self,
        agent: str,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        self.agent = agent
        self.params = params or {}


class PlannerAgent(BaseAgent):
    """Decomposes user queries into structured tasks and initiates conversations.

    Creates research requests for Librarian, WebSearcher, and Analyst.
    Slice 5: sends to all three in one round; aggregates INFORMs then forwards to Responder.
    """

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        llm_client: Optional[LLMClient] = None,
        conversation_manager: Any = None,
        max_research_rounds: int = 2,
    ) -> None:

        super().__init__(name, message_bus)
        self._llm_client = llm_client
        self._conversation_manager = conversation_manager

        # store agents we're waiting for for each conversation_id
        self._round_pending: dict[
            str, set[str]
        ] = {}

        # store collected content from each agent for each conversation_id
        self._collected: dict[
            str, dict[str, Any]
        ] = {} 

        # store user profile for each conversation
        self._user_profile_by_conversation: dict[
            str, str
        ] = {}
        self._round_number: dict[str, int] = {}  # conversation_id -> round (capped by max_research_rounds)
        self._original_query_by_conversation: dict[str, str] = {}  # for sufficiency/refined
        self._max_rounds = max(1, max_research_rounds)

    def handle_message(self, message: ACLMessage) -> None:
        """Handle incoming messages directed to the Planner.

        Handles STOP (ignore), INFORM from specialist agents (aggregate then
        forward to Responder), and REQUEST from API (send to all three agents).

        Args:
            message: The received ACL message (REQUEST from api, or INFORM from
                librarian/websearcher/analyst).
        """
        if message.performative == Performative.STOP:
            return
        content = message.content or {}
        conversation_id = (
            content.get("conversation_id") or message.conversation_id or ""
        )
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.planner_agent.PlannerAgent.handle_message",
            params={
                "performative": getattr(message.performative, "value", str(message.performative)),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
                **interaction_log.content_preview_for_log(content),
            },
        )

        # Specialist replied: store content, mark agent done, forward when all three received
        if message.performative == Performative.INFORM and message.sender in (
            "librarian",
            "websearcher",
            "analyst",
        ):
            # Aggregation phase: store specialist payload and track pending agents.
            if conversation_id not in self._collected:
                interaction_log.log_call(
                    "agents.planner_agent.PlannerAgent.handle_message",
                    result={"skipped": True, "reason": "conversation_id not in _collected"},
                )
                return
            
            # collect content from the agent 
            self._collected[conversation_id][message.sender] = content
            # remove the agent from the list of agents we're waiting for
            self._round_pending[conversation_id].discard(message.sender)

            # if the conversation manager is set, append a flow event
            if self._conversation_manager:
                pending_list = list(self._round_pending[conversation_id])
                still_waiting = ", ".join(pending_list) if pending_list else "none"
                snippet = self._conversation_state_snippet(content)
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "agent_returned",
                        "message": f"**{message.sender}** has responded. Still waiting for: {still_waiting}. {snippet}",
                        "detail": {
                            "agent": message.sender,
                            "pending": pending_list,
                            "result_summary": snippet,
                            "result_keys": [k for k in (content or {}).keys() if k != "query"],
                        },
                    },
                )
            
            # if all agents have responded, compute the combined answer candidate
            if not self._round_pending[conversation_id]:
                collected = self._collected[conversation_id]
                final = self._format_final(collected)
                user_profile = self._user_profile_by_conversation.get(
                    conversation_id, "beginner"
                )
                original_query = self._original_query_by_conversation.get(
                    conversation_id, ""
                )
                round_num = self._round_number.get(conversation_id, 1)
                send_to_responder = True
                insufficient = False
                if self._llm_client and original_query:
                    # Sufficiency phase: decide whether to stop or run a refined second round.
                    aggregated = self._format_aggregated_for_sufficiency(collected)
                    sufficient = self._check_sufficiency(original_query, aggregated)
                    if sufficient:
                        pass
                    elif round_num < self._max_rounds:
                        refined_steps = self._get_refined_steps(
                            original_query, aggregated
                        )
                        if refined_steps:
                            self._round_number[conversation_id] = 2
                            self._round_pending[conversation_id] = {
                                s.agent for s in refined_steps
                            }
                            if self._conversation_manager:
                                self._conversation_manager.append_flow(
                                    conversation_id,
                                    {
                                        "step": "planner_round2",
                                        "message": "Information insufficient after first round. Starting second round with refined queries.",
                                        "detail": {
                                            "steps": [
                                                {"agent": s.agent}
                                                for s in refined_steps
                                            ],
                                        },
                                    },
                                )
                            for step in refined_steps:
                                # Dispatch each refined step as a new REQUEST to the target specialist.
                                step.params = dict(step.params)
                                req = self.create_research_request(
                                    original_query, step, context=collected
                                )
                                req.conversation_id = conversation_id
                                req.reply_to = self.name
                                self.bus.send(req)
                                interaction_log.log_call(
                                    "agents.planner_agent.PlannerAgent.handle_message",
                                    result={
                                        "sent_to": step.agent,
                                        **interaction_log.content_preview_for_log(req.content),
                                    },
                                )
                                if self._conversation_manager:
                                    q = step.params.get("query", original_query)
                                    q_display = q if len(q) <= 120 else (q[:100] + "...")
                                    self._conversation_manager.append_flow(
                                        conversation_id,
                                        {
                                            "step": "planner_sent",
                                            "message": f"Request sent to **{step.agent}** (query: \"{q_display}\").",
                                            "detail": {
                                                "agent": step.agent,
                                                "query": q,
                                                "query_preview": q[:100],
                                            },
                                        },
                                    )
                            send_to_responder = False
                            interaction_log.log_call(
                                "agents.planner_agent.PlannerAgent.handle_message",
                                result={
                                    "refined_REQUEST": "sent to specialists",
                                    "agents": [s.agent for s in refined_steps],
                                },
                            )
                        else:
                            insufficient = True
                    else:
                        insufficient = True
                if send_to_responder:
                    if insufficient:
                        final = "Insufficient information."
                    # Finalization phase: send one INFORM to responder and clean planner state.
                    if self._conversation_manager:
                        self._conversation_manager.append_flow(
                            conversation_id,
                            {
                                "step": "planner_complete",
                                "message": "All agents have responded. Sending combined results to Responder to format your answer."
                                if not insufficient
                                else f"Information still insufficient after {self._max_rounds} round(s). Responder will reply with insufficient.",
                                "detail": {"final_length": len(final)},
                            },
                        )
                    self.bus.send(
                        ACLMessage(
                            performative=Performative.INFORM,
                            sender=self.name,
                            receiver="responder",
                            content={
                                "final_response": final,
                                "conversation_id": conversation_id,
                                "user_profile": user_profile,
                                "insufficient": insufficient,
                            },
                            conversation_id=conversation_id,
                        )
                    )
                    interaction_log.log_call(
                        "agents.planner_agent.PlannerAgent.handle_message",
                        result={"INFORM": "sent to responder"},
                    )
                    del self._round_pending[conversation_id]
                    del self._collected[conversation_id]
                    self._user_profile_by_conversation.pop(conversation_id, None)
                    self._round_number.pop(conversation_id, None)
                    self._original_query_by_conversation.pop(conversation_id, None)
            return

        # New user request phase: decompose into specialist steps and dispatch round 1.
        query = content.get("query", "")
        if not query:
            return
        raw_profile = content.get("user_profile") or "beginner"
        if isinstance(raw_profile, str):
            profile = raw_profile.strip().lower()
        else:
            profile = "beginner"
        if profile not in VALID_USER_PROFILES:
            profile = "beginner"
        self._user_profile_by_conversation[conversation_id] = profile
        self._original_query_by_conversation[conversation_id] = query
        self._round_number[conversation_id] = 1
        user_memory = content.get("user_memory")
        if not isinstance(user_memory, str):
            user_memory = ""
        steps = self.decompose_task(query, user_memory=user_memory)
        if not steps:
            interaction_log.log_call(
                "agents.planner_agent.PlannerAgent.handle_message",
                result={"skipped": True, "reason": "no steps"},
            )
            return
        # Flow: one summary message with actual decomposed steps and full sub-queries
        query_short = query[:80] + ("..." if len(query) > 80 else "")
        step_parts = [s.agent for s in steps]
        agents_waiting = ", ".join(s.agent for s in steps)
        waiting_set = {s.agent for s in steps}
        if self._conversation_manager:
            steps_detail = [
                {"agent": s.agent, "query": s.params.get("query", query)}
                for s in steps
            ]
            self._conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "planner_decomposed",
                    "message": f'Planner has decomposed your query "{query_short}" into: {"; ".join(step_parts)}. Waiting for {agents_waiting} to respond.',
                    "detail": {
                        "query_preview": query[:200] + ("..." if len(query) > 200 else ""),
                        "steps": steps_detail,
                        "waiting_for": list(waiting_set),
                    },
                },
            )
        if self._conversation_manager:
            for s in steps:
                q = s.params.get("query", query)
                q_display = q if len(q) <= 120 else (q[:100] + "...")
                self._conversation_manager.append_flow(
                    conversation_id,
                    {
                        "step": "planner_sent",
                        "message": f"Request sent to **{s.agent}** (query: \"{q_display}\").",
                        "detail": {
                            "agent": s.agent,
                            "query": q,
                            "query_preview": q[:100],
                        },
                    },
                )
        self._round_pending[conversation_id] = waiting_set
        self._collected[conversation_id] = {}
        for step in steps:
            step.params = dict(step.params)
            q = step.params.get("query", query)
            req = self.create_research_request(query, step, context=None)
            req.conversation_id = conversation_id
            req.reply_to = self.name
            self.bus.send(req)
            interaction_log.log_call(
                "agents.planner_agent.PlannerAgent.handle_message",
                result={
                    "sent_to": step.agent,
                    **interaction_log.content_preview_for_log(req.content),
                },
            )
        interaction_log.log_call(
            "agents.planner_agent.PlannerAgent.handle_message",
            result={"REQUEST": "sent to specialists", "agents": [s.agent for s in steps]},
        )

    def _snippet(self, text: str | None, max_len: int = 120) -> str:
        """Return text truncated to max_len with '...' if longer. Handles None/non-str."""
        if text is None:
            return ""
        s = str(text).strip()
        if len(s) <= max_len:
            return s
        return s[:max_len] + "..."

    def _format_final(self, collected: dict[str, Any]) -> str:
        """Turn collected agent outputs into a single string for Responder.

        Args:
            collected: Map of agent name to INFORM content (e.g. librarian, websearcher, analyst).

        Returns:
            Concatenated summary string (Librarian/WebSearcher/Analyst: ...).
        """
        parts = []
        if "librarian" in collected:
            c = collected["librarian"]
            if c.get("content"):
                parts.append(str(c["content"]))
            
            # if the librarian has retrieved documents or graph data, add a summary of the data
            elif c.get("documents") or c.get("graph"):
                bits: list[str] = []

                docs = c.get("documents")
                if isinstance(docs, list) and docs:
                    bits.append(f"{len(docs)} doc(s)")

                    # add a summary of the first document
                    first = docs[0]
                    if isinstance(first, dict):
                        content_str = first.get("content") or first.get("text")
                        if isinstance(content_str, str) and content_str.strip():
                            bits.append(f' (e.g. "{self._snippet(content_str, 120)}")')

                g = c.get("graph")
                if isinstance(g, dict) and g.get("nodes"):
                    nodes = g["nodes"]

                    # add a summary of the graph nodes - the first 3 nodes
                    if isinstance(nodes, list) and nodes:
                        bits.append(f"{len(nodes)} graph node(s)")
                        ids = []
                        for n in nodes[:3]:
                            if isinstance(n, dict):
                                nid = n.get("id")
                                if nid is None:
                                    lbl = n.get("label")
                                    nid = lbl[0] if isinstance(lbl, list) and lbl else lbl
                                if nid is not None:
                                    ids.append(str(nid))
                        if ids:
                            bits.append(f" ({', '.join(ids)})")
                if bits:
                    parts.append("Librarian: " + ", ".join(bits).strip() + ".")
                else:
                    parts.append("Librarian: no content.")
            else:
                parts.append("Librarian: data retrieved.")

        if "websearcher" in collected:
            w = collected["websearcher"]
            if w.get("market_data") or w.get("sentiment"):
                bits_ws: list[str] = []
                summary_ws = w.get("summary")

                # if there is a summary, add a snippet of the summary
                if isinstance(summary_ws, str) and summary_ws.strip():
                    bits_ws.append(f'"{self._snippet(summary_ws, 120)}"')
                else:
                    # if there is no summary, add a summary of the market data and sentiment data
                    for key, label in (("market_data", "market data"), ("sentiment", "sentiment")):
                        val = w.get(key)

                        # if there is an error, add a summary of the error
                        if isinstance(val, dict):
                            err = val.get("error")
                            if isinstance(err, str) and err.strip():
                                bits_ws.append(f"{label}: error {self._snippet(err, 80)}")
                            else:
                                # if there is content, add 120-char snippet
                                content_val = val.get("content")
                                if isinstance(content_val, str) and content_val.strip():
                                    bits_ws.append(f'{label}: "{self._snippet(content_val, 120)}"')
                                else:
                                    # else just say that there's a label
                                    bits_ws.append(f"{label} present, no content")
                if bits_ws:
                    parts.append("WebSearcher: " + "; ".join(bits_ws) + ".")
                else:
                    parts.append("WebSearcher: no content.")

        if "analyst" in collected:
            a = collected["analyst"]
            if a.get("analysis") is not None:
                analysis_val = a["analysis"]
                bits_a: list[str] = []

                # if the analysis is a dictionary, add a summary of the confidence and summary
                if isinstance(analysis_val, dict):
                    conf = analysis_val.get("confidence")
                    if conf is not None:
                        bits_a.append(f"confidence {conf}")
                    
                    # if the summary is a string, add a snippet of the summary
                    summary_a = analysis_val.get("summary")
                    if isinstance(summary_a, str) and summary_a.strip():
                        bits_a.append(f'"{self._snippet(summary_a, 120)}"')
                    elif not bits_a:
                        # if there is no confidence or summary, add a snippet of the analysis
                        bits_a.append(self._snippet(str(analysis_val), 150))
                else:
                    # if the analysis is not a dictionary, add a snippet of the analysis
                    bits_a.append(self._snippet(str(analysis_val), 120))
                
                if bits_a:
                    parts.append("Analyst: " + " ".join(bits_a) + ".")
                else:
                    parts.append("Analyst: no content.")

        return " ".join(parts) if parts else "Research round complete."

    def _conversation_state_snippet(self, content: dict[str, Any], max_chars: int = 350) -> str:
        """Human-readable summary of agent result for flow display (errors, summary, or key fields) for use in the conversation manager."""
        if not content:
            return ""

        # Explicit error (e.g. from tool or MCP)
        err = content.get("error")
        if isinstance(err, str) and err.strip():
            return f"Error: {self._snippet(err, 250)}"
        if isinstance(content.get("market_data"), dict) and content["market_data"].get("error"):
            e = content["market_data"]["error"]
            return f"Error: {self._snippet(e, 250)}"

        # Summary from LLM or agent
        summary = content.get("summary")
        if isinstance(summary, str) and summary.strip():
            return f"Summary: {self._snippet(summary, max_chars)}"

        # Structured keys: describe what's present and show a short preview
        parts = []
        for key in ("market_data", "sentiment", "analysis", "documents", "graph", "combined_data"):
            val = content.get(key)
            if val is None:
                continue
            if isinstance(val, dict) and val.get("error"):
                parts.append(f"{key}: Error: {self._snippet(val.get('error'), 120)}")
            elif isinstance(val, dict):
                parts.append(f"{key}: present ({len(val)} keys)")
            elif isinstance(val, list):
                parts.append(f"{key}: {len(val)} items")
            else:
                parts.append(f"{key}: {self._snippet(str(val), 150)}")
        if parts:
            return " | ".join(parts)
        return f"Result: {self._snippet(str(content), max_chars)}"

    def _format_aggregated_for_sufficiency(self, collected: dict[str, Any]) -> str:
        """Build a string from collected agent outputs for LLM sufficiency check."""
        parts = []
        for agent in ("librarian", "websearcher", "analyst"):
            if agent not in collected:
                continue
            c = collected[agent]
            summary = c.get("summary")
            if isinstance(summary, str) and summary.strip():
                parts.append(f"[{agent}]\n{summary.strip()}")
            elif c.get("market_data") or c.get("sentiment"):
                parts.append(f"[{agent}] market/sentiment data present.")
            elif c.get("analysis") is not None:
                parts.append(f"[{agent}]\n{str(c.get('analysis', ''))[:2000]}")
            else:
                parts.append(f"[{agent}] data retrieved.")
        return "\n\n".join(parts) if parts else "No data."

    def _check_sufficiency(self, user_query: str, aggregated: str) -> bool:
        """Call LLM to decide if aggregated info is sufficient. Returns True if SUFFICIENT."""
        assert self._llm_client is not None  # caller checks before invoking
        try:
            from llm.prompts import get_planner_sufficiency_user_content

            system = "You decide if the research is sufficient to answer the user. Answer only SUFFICIENT or INSUFFICIENT."
            user_content = get_planner_sufficiency_user_content(user_query, aggregated)
            out = self._llm_client.complete(system, user_content)
            s = (out or "").strip().upper()
            # Must start with SUFFICIENT but not INSUFFICIENT (substring would match both)
            return s.startswith("SUFFICIENT") and not s.startswith("INSUFFICIENT")
        except Exception as e:
            logger.debug("Sufficiency check failed, treating as sufficient: %s", e)
            return True

    def _get_refined_steps(
        self, user_query: str, aggregated: str
    ) -> list[TaskStep]:
        """Get steps for round 2 from LLM refined-queries JSON. Returns empty list on parse failure."""
        assert self._llm_client is not None  # caller checks before invoking
        try:
            from llm.prompts import get_planner_refined_user_content

            system = "You output a JSON object with keys librarian, websearcher, analyst (only include agents that can fill gaps). Each value is a query string."
            user_content = get_planner_refined_user_content(user_query, aggregated)
            out = self._llm_client.complete(system, user_content)
            text = (out or "").strip()
            if "```" in text:
                match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
                if match:
                    text = match.group(1)
            raw = json.loads(text)
            if not isinstance(raw, dict):
                return []
            steps = []
            for agent in ("librarian", "websearcher", "analyst"):
                q = raw.get(agent)
                if isinstance(q, str) and q.strip():
                    steps.append(
                        TaskStep(
                            agent=agent,
                            params={"query": q.strip()},
                        )
                    )
            return steps
        except Exception as e:
            logger.debug("Refined steps parse failed: %s", e)
            return []

    def decompose_task(self, query: str, user_memory: str = "") -> list[TaskStep]:
        """Produce a ReAct-style task chain from the user query.

        Uses llm_client.decompose_to_steps when available (Stage 10.2); otherwise
        returns a fixed one-round chain (librarian, websearcher, analyst).

        Args:
            query: Raw user investment query.

        Returns:
            Ordered list of TaskSteps (one per specialist).
        """
        if self._llm_client is not None:
            try:
                # Use LLM to get step dicts; filter to allowed agents and build TaskSteps
                step_dicts = self._llm_client.decompose_to_steps(
                    query, memory_context=user_memory
                )

                if step_dicts is not None:
                    if not step_dicts:
                        # LLM returned valid empty list: use single analyst step so pipeline does not stall
                        return [
                            TaskStep(
                                agent="analyst",
                                params={"query": query},
                            )
                        ]
                    return [
                        TaskStep(
                            agent=s.get("agent", "librarian"),
                            params=dict(s.get("params") or {}),
                        )
                        for s in step_dicts
                        if isinstance(s, dict)
                        and (s.get("agent") or "").strip().lower()
                        in ("librarian", "websearcher", "analyst")
                    ]
            except Exception as e:
                logger.debug("LLM task parse failed, using default steps: %s", e)
        # No LLM or parse failed; use fixed three steps (librarian, websearcher, analyst)
        # Pass vector_query and fund so the librarian calls vector_tool and kg_tool
        # (demo can then use populated backends)
        # Fallback fund/symbol: small heuristic map; full decomposition requires LLM.
        _QUERY_TO_SYMBOL = (
            ("nvidia", "NVDA"), ("nvda", "NVDA"),
            ("apple", "AAPL"), ("aapl", "AAPL"),
            ("tesla", "TSLA"), ("tsla", "TSLA"),
            ("microsoft", "MSFT"), ("msft", "MSFT"),
            ("google", "GOOGL"), ("googl", "GOOGL"), ("alphabet", "GOOGL"),
        )
        q_lower = query.lower()
        fund = ""
        for substring, symbol in _QUERY_TO_SYMBOL:
            if substring in q_lower:
                fund = symbol
                break
        return [
            TaskStep(
                agent="librarian",
                params={
                    "query": query,
                    "vector_query": query,
                    "fund": fund,
                },
            ),
            TaskStep(
                agent="websearcher", params={"query": query}
            ),
            TaskStep(agent="analyst", params={"query": query}),
        ]

    def create_research_request(
        self,
        query: str,
        step: TaskStep,
        context: Optional[dict[str, Any]] = None,
    ) -> ACLMessage:
        """Build a request ACL message for Librarian, WebSearcher, or Analyst.

        Args:
            query: User query.
            step: Current task step (TaskStep object that holds target agent and instructions for the specific step).
            context: Optional prior context (not used in this implementation).

        Returns:
            ACL message addressed to the appropriate agent.
        """
        # Content includes query (role-specific from step.params or fallback) and any step params   
        step_query = step.params.get("query", query)
        content = {"query": step_query, **step.params} # ** dictionary unpacking, overwrite query with step.params if it exists
        return ACLMessage(
            performative=Performative.REQUEST,
            sender=self.name,
            receiver=step.agent,
            content=content,
        )

