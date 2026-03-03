"""Librarian agent: vector and graph retrieval via MCP (Milvus, Neo4j)."""

import logging
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent
from util.trace_log import trace
from util import interaction_log
from util.log_format import log_agent_section, struct_log

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


class LibrarianAgent(BaseAgent):
    """Retrieves structured data from knowledge graph and vector database.

    Uses MCP vector_tool (Milvus) and kg_tool (Neo4j); does not access
    databases directly.
    """

    def __init__(
        self,
        name: str,
        message_bus: MessageBus,
        mcp_client: Any = None,
        conversation_manager: Any = None,
        llm_client: "LLMClient | None" = None,
    ) -> None:
        """Initialize the librarian agent.

        Args:
            name: Unique agent name (receiver address).
            message_bus: Shared A2A transport.
            mcp_client: MCP client for file_tool, vector_tool, kg_tool, sql_tool.
            conversation_manager: Optional ConversationManager for flow events.
            llm_client: Optional LLM client for summarizing combined results (LIBRARIAN_SYSTEM).
        """
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client
        self.conversation_manager = conversation_manager
        self._llm_client = llm_client

    def handle_message(self, message: ACLMessage) -> None:
        """Process data retrieval requests.

        When llm_client is set: use LLM (prompt + tool descriptions) to select tools and
        parameters, execute via call_tool, combine results, send INFORM. If select_tools
        returns empty or fails, fall back to content-key dispatch.
        When llm_client is None: use content-key dispatch (path, vector_query, fund, sql_query).

        Args:
            message: The received ACL message; content may include path, vector_query,
                fund, entity, sql_query, top_k, sql_params, and query (decomposed from planner).
        """
        if not self.mcp_client:
            return
        content = message.content or {}
        conversation_id = getattr(message, "conversation_id", "") or ""
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id) if conversation_id else ""
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.librarian_agent.LibrarianAgent.handle_message",
            params={
                "performative": getattr(message.performative, "value", str(message.performative)),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
            },
        )
        if message.performative == Performative.REQUEST:
            log_agent_section(logger, "librarian")
            struct_log(logger, logging.INFO, "agent.librarian.start")
        query = content.get("query") or content.get("path") or ""

        # When LLM is available, try tool selection first; fall back to content-key if empty/fail
        if self._llm_client is not None:
            from llm.prompts import LIBRARIAN_TOOL_SELECTION
            from llm.tool_descriptions import (
                LIBRARIAN_ALLOWED_TOOL_NAMES,
                filter_tool_calls_to_allowed,
                get_librarian_tool_descriptions,
                normalize_tool_calls,
            )

            registered = (
                set(self.mcp_client.get_registered_tool_names())
                if self.mcp_client
                else None
            )
            allowed = (
                frozenset(LIBRARIAN_ALLOWED_TOOL_NAMES & registered)
                if registered is not None
                else LIBRARIAN_ALLOWED_TOOL_NAMES
            )
            tool_descriptions = get_librarian_tool_descriptions(registered)
            user_content = f"Sub-query from planner: {query}"
            tool_calls = self._llm_client.select_tools(
                LIBRARIAN_TOOL_SELECTION, user_content, tool_descriptions
            )
            # Discard any tool the LLM returned that is not in allowed (and registered)
            tool_calls = filter_tool_calls_to_allowed(tool_calls, allowed)
            tool_calls = normalize_tool_calls(tool_calls)
            if tool_calls:
                parts = self._execute_tool_calls(tool_calls)
                if parts:
                    reply_content = self._build_reply_from_parts(parts)
                    if isinstance(reply_content, dict):
                        from llm.prompts import LIBRARIAN_SYSTEM, get_librarian_user_content
                        user_content_summary = get_librarian_user_content(str(query)[:500], reply_content)
                        summary = self._llm_client.complete(LIBRARIAN_SYSTEM, user_content_summary)
                        reply_content = dict(reply_content)
                        reply_content["summary"] = summary
                    struct_log(logger, logging.INFO, "agent.librarian.done", status="success")
                    self._send_inform(message, reply_content, conversation_id)
                    interaction_log.log_call(
                        "agents.librarian_agent.LibrarianAgent.handle_message",
                        result={"INFORM": "sent to planner", "via": "LLM tool selection"},
                    )
                    return
        # Fallback: content-key dispatch
        path = content.get("path")
        if not path and content.get("query"):
            path = content.get("query")
        vector_query = content.get("vector_query")
        fund = content.get("fund") or content.get("entity") or ""
        sql_query = content.get("sql_query") or content.get("sql") or ""
        trace(
            8,
            "librarian_request_received",
            in_={
                "conversation_id": conversation_id,
                "path": path or "(none)",
                "fund": fund or "(none)",
            },
            out="ok",
            next_="call tools (file, vector, kg, sql)",
        )
        if self.conversation_manager and conversation_id:
            path_preview = (path or "(query)")[:60] + (
                "..." if len(path or "") > 60 else ""
            )
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "librarian_start",
                    "message": f'**Librarian** received request: path="{path_preview}", fund={fund or "(none)"}. Retrieving documents and knowledge graph data.',
                    "detail": {"path": path or "(query)", "fund": fund or "(none)"},
                },
            )

        # Call each requested tool and collect results
        parts: dict[str, Any] = {}
        if path:
            result = self.mcp_client.call_tool("file_tool.read_file", {"path": path})
            parts["file"] = (
                result if isinstance(result, dict) else {"content": str(result)}
            )
            has_error = isinstance(parts["file"], dict) and "error" in parts["file"]
            trace(
                9,
                "librarian_read_file_done",
                in_={"path": path},
                out=f"error={has_error}",
                next_="build reply",
            )
        if vector_query:
            docs_result = self.mcp_client.call_tool(
                "vector_tool.search",
                {"query": vector_query, "top_k": content.get("top_k", 5)},
            )
            docs = (
                docs_result.get("documents", docs_result)
                if isinstance(docs_result, dict)
                else docs_result
            )
            parts["documents"] = docs if isinstance(docs, list) else [docs]
        if fund:
            graph_result = self.mcp_client.call_tool(
                "kg_tool.get_relations", {"entity": fund}
            )
            parts["graph"] = (
                graph_result
                if isinstance(graph_result, dict) and "error" not in graph_result
                else {}
            )
        if sql_query:
            sql_result = self.mcp_client.call_tool(
                "sql_tool.run_query",
                {"query": sql_query, "params": content.get("sql_params")},
            )
            parts["sql"] = sql_result if isinstance(sql_result, dict) else {"rows": []}

        # Build reply: file-only keeps Slice 3 shape; else combined structure
        if not parts:
            reply_content: Any = {"error": "Missing path, vector_query, fund, or sql_query"}
        elif len(parts) == 1 and "file" in parts:
            reply_content = parts["file"]
        else:
            docs_list = (
                list(parts["documents"])
                if isinstance(parts.get("documents"), list)
                else []
            )
            graph_data = parts.get("graph", {})
            reply_content = self.combine_results(docs_list, graph_data)
            if parts.get("file"):
                reply_content["file"] = parts["file"]
            if parts.get("sql"):
                reply_content["sql"] = parts["sql"]

        # Optional LLM summary of combined data for the planner
        if self._llm_client is not None and isinstance(reply_content, dict):
            from llm.prompts import LIBRARIAN_SYSTEM, get_librarian_user_content

            query = content.get("query") or content.get("path") or ""
            user_content = get_librarian_user_content(str(query)[:500], reply_content)
            summary = self._llm_client.complete(LIBRARIAN_SYSTEM, user_content)
            reply_content = dict(reply_content)
            reply_content["summary"] = summary

        status = "limited_data" if (isinstance(reply_content, dict) and reply_content.get("error")) else "success"
        struct_log(logger, logging.INFO, "agent.librarian.done", status=status)
        reply_to = getattr(message, "reply_to", None) or message.sender
        reply = ACLMessage(
            performative=Performative.INFORM,
            sender=self.name,
            receiver=reply_to,
            content=reply_content,
            conversation_id=message.conversation_id,
            reply_to=message.sender,
        )
        self.bus.send(reply)
        interaction_log.log_call(
            "agents.librarian_agent.LibrarianAgent.handle_message",
            result={"INFORM": "sent to planner", "reply_keys": list(reply_content.keys()) if isinstance(reply_content, dict) else []},
        )
        trace(
            9,
            "librarian_inform_sent",
            in_={"conversation_id": conversation_id},
            out=f"reply_keys={list(reply_content.keys()) if isinstance(reply_content, dict) else []}",
            next_="planner receives",
        )
        if self.conversation_manager and conversation_id:
            summary = "file content" if parts.get("file") else "documents and graph"
            nchars = 0
            if isinstance(reply_content, dict) and reply_content.get("content"):
                nchars = len(str(reply_content["content"]))
            elif (
                isinstance(reply_content, dict)
                and reply_content.get("file")
                and isinstance(reply_content["file"], dict)
            ):
                nchars = len(str(reply_content["file"].get("content", "")))
            size_str = f" ({nchars} chars)" if nchars else ""
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "librarian_done",
                    "message": f"**Librarian** has returned {summary}{size_str}.",
                    "detail": {
                        "reply_keys": list(reply_content.keys())
                        if isinstance(reply_content, dict)
                        else []
                    },
                },
            )

    def _execute_tool_calls(self, tool_calls: list) -> dict[str, Any]:
        """Execute a list of {tool, payload} dicts via mcp_client; return parts dict (file, documents, graph, sql)."""
        parts: dict[str, Any] = {}
        for tc in tool_calls:
            tool = tc.get("tool", "")
            payload = tc.get("payload") or {}
            if not isinstance(tool, str) or not tool.strip():
                continue
            result = self.mcp_client.call_tool(tool, payload)
            if tool == "file_tool.read_file":
                parts["file"] = result if isinstance(result, dict) else {"content": str(result)}
            elif tool == "vector_tool.search":
                docs = result.get("documents", result) if isinstance(result, dict) else result
                docs_list = docs if isinstance(docs, list) else [docs]
                parts.setdefault("documents", []).extend(docs_list)
            elif tool in ("kg_tool.get_relations", "kg_tool.get_node_by_id", "kg_tool.query_graph"):
                if isinstance(result, dict) and "error" not in result:
                    existing = parts.get("graph", {})
                    if isinstance(existing, dict) and isinstance(result, dict):
                        # Merge nodes/edges if present
                        for k in ("nodes", "edges", "rows"):
                            if k in result and result[k]:
                                existing.setdefault(k, []).extend(result[k] if isinstance(result[k], list) else [result[k]])
                        parts["graph"] = existing
                    else:
                        parts["graph"] = result
            elif tool.startswith("sql_tool."):
                parts["sql"] = result if isinstance(result, dict) else {"rows": []}
        return parts

    def _build_reply_from_parts(self, parts: dict[str, Any]) -> Any:
        """Build reply_content from parts (same shape as content-key path)."""
        if not parts:
            return {"error": "No tool results"}
        if len(parts) == 1 and "file" in parts:
            return parts["file"]
        docs_list = list(parts.get("documents", [])) if isinstance(parts.get("documents"), list) else []
        graph_data = parts.get("graph", {}) if isinstance(parts.get("graph"), dict) else {}
        reply_content = self.combine_results(docs_list, graph_data)
        if parts.get("file"):
            reply_content["file"] = parts["file"]
        if parts.get("sql"):
            reply_content["sql"] = parts["sql"]
        return reply_content

    def _send_inform(self, message: ACLMessage, reply_content: Any, conversation_id: str) -> None:
        """Send INFORM to reply_to and append flow event."""
        reply_to = getattr(message, "reply_to", None) or message.sender
        reply = ACLMessage(
            performative=Performative.INFORM,
            sender=self.name,
            receiver=reply_to,
            content=reply_content,
            conversation_id=message.conversation_id,
            reply_to=message.sender,
        )
        self.bus.send(reply)
        interaction_log.log_call(
            "agents.librarian_agent.LibrarianAgent.handle_message",
            result={"INFORM": "sent to planner"},
        )
        trace(9, "librarian_inform_sent", in_={"conversation_id": conversation_id}, out="sent", next_="planner receives")
        if self.conversation_manager and conversation_id:
            summary = "documents and graph" if isinstance(reply_content, dict) else "data"
            self.conversation_manager.append_flow(
                conversation_id,
                {"step": "librarian_done", "message": f"**Librarian** has returned {summary}.", "detail": {"reply_keys": list(reply_content.keys()) if isinstance(reply_content, dict) else []}},
            )

    def retrieve_knowledge_graph(self, fund: str) -> dict:
        """Query knowledge graph for fund relationships via MCP kg_tool (Neo4j).

        Args:
            fund: Fund identifier.

        Returns:
            Structured graph data (nodes/edges).
        """
        if not self.mcp_client:
            return {"nodes": [], "edges": []}
        result = self.mcp_client.call_tool("kg_tool.get_relations", {"entity": fund})
        if isinstance(result, dict) and "error" in result:
            return {"nodes": [], "edges": []}
        return result if isinstance(result, dict) else {"nodes": [], "edges": []}

    def retrieve_documents(self, query: str, top_k: int = 5) -> list:
        """Perform semantic search over vector DB via MCP vector_tool (Milvus).

        Args:
            query: Search query.
            top_k: Max documents to return.

        Returns:
            List of retrieved documents with scores.
        """
        if not self.mcp_client:
            return []
        result = self.mcp_client.call_tool(
            "vector_tool.search", {"query": query, "top_k": top_k}
        )
        if isinstance(result, dict) and "error" in result:
            return []
        docs = result.get("documents", result) if isinstance(result, dict) else result
        return docs if isinstance(docs, list) else [docs]

    def combine_results(self, docs: list, graph_data: dict) -> dict:
        """Merge vector and graph results for downstream Analyst.

        Args:
            docs: Documents from vector search.
            graph_data: Result from knowledge graph query.

        Returns:
            Single structured result dict.
        """
        return {
            "documents": docs,
            "graph": graph_data,
        }
