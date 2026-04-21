"""Librarian retrieval and response orchestration."""

import logging
from typing import TYPE_CHECKING, Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from util import interaction_log
from util.timeseries_metrics import attach_structured_timeseries_metrics

if TYPE_CHECKING:
    from llm.base import LLMClient

logger = logging.getLogger(__name__)


class LibrarianOrchestrationMixin:
    """Split part for readability."""

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
            mcp_client: MCP client for vector_tool, kg_tool, sql_tool.
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
        When llm_client is None: use content-key dispatch (vector_query, fund, sql_query).

        Args:
            message: The received ACL message; content may include vector_query,
                fund, entity, sql_query, top_k, sql_params, and query (decomposed from planner).
        """
        if not self.mcp_client:
            return

        # Normalize request metadata once for logs and downstream flow events.
        content = message.content or {}
        query = content.get("query") or ""
        conversation_id = getattr(message, "conversation_id", "") or ""
        if not isinstance(conversation_id, str):
            conversation_id = str(conversation_id) if conversation_id else ""
        interaction_log.set_conversation_id(conversation_id)
        interaction_log.log_call(
            "agents.librarian_agent.LibrarianAgent.handle_message",
            params={
                "performative": getattr(
                    message.performative, "value", str(message.performative)
                ),
                "sender": message.sender,
                "content_keys": list(content.keys()) if content else [],
                "conversation_id": conversation_id,
                **interaction_log.content_preview_for_log(content),
            },
        )
        if self._llm_client is not None:
            from llm.prompts import LIBRARIAN_TOOL_SELECTION
            from openfund_mcp.tools.registry_metadata import (
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
            sr = content.get("symbol_resolution")
            entity_hint = ""
            dataset_hint = ""
            if isinstance(sr, dict) and sr.get("status") == "resolved":
                cn = (sr.get("canonical_name") or "").strip()
                if cn:
                    entity_hint = f"\nResolved entity for knowledge graph / SQL (use for get_relations, ILIKE, etc.): {cn}"
                first_listing = (sr.get("listings") or [None])[0]
                if isinstance(first_listing, dict):
                    st = (first_listing.get("symbol_type") or "").strip().lower()
                    if st == "equities":
                        dataset_hint = '\nFor kg_tool.get_relations, include prefer_dataset: "equities" in the payload.'
            user_content = f"Sub-query from planner: {query}{entity_hint}{dataset_hint}"

            # Ask LLM to pick tools, then run only allowed/normalized calls.
            tool_calls = self._llm_client.select_tools(
                LIBRARIAN_TOOL_SELECTION, user_content, tool_descriptions
            )
            tool_calls = filter_tool_calls_to_allowed(tool_calls, allowed)
            tool_calls = normalize_tool_calls(tool_calls)
            if tool_calls:
                parts = self._execute_tool_calls(tool_calls)
                if parts:
                    reply_content = self._build_reply_from_parts(parts)
                    if isinstance(reply_content, dict):
                        attach_structured_timeseries_metrics(reply_content)
                        from llm.prompts import (
                            LIBRARIAN_SYSTEM,
                            get_librarian_user_content,
                        )

                        user_content_summary = get_librarian_user_content(
                            str(query)[:500], reply_content
                        )
                        try:
                            summary = self._llm_client.complete(
                                LIBRARIAN_SYSTEM, user_content_summary
                            )
                        except Exception as e:
                            logger.warning("Librarian summary generation failed: %s", e)
                            summary = ""
                        reply_content = dict(reply_content)
                        reply_content["summary"] = summary
                    self._send_inform(message, reply_content, conversation_id)
                    interaction_log.log_call(
                        "agents.librarian_agent.LibrarianAgent.handle_message",
                        result={
                            "INFORM": "sent to planner",
                            "via": "LLM tool selection",
                        },
                    )
                    return

        # Fallback path: direct dispatch based on explicit content keys.
        vector_query = content.get("vector_query")
        fund = content.get("fund") or content.get("entity") or ""
        sql_query = content.get("sql_query") or content.get("sql") or ""
        if self.conversation_manager and conversation_id:
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "librarian_start",
                    "message": f"**Librarian** received request: fund={fund or '(none)'}. Retrieving documents and knowledge graph data.",
                    "detail": {"fund": fund or "(none)"},
                },
            )
        parts: dict[str, Any] = {}
        if vector_query:
            try:
                docs_result = self.mcp_client.call_tool(
                    "vector_tool.search",
                    {"query": vector_query, "top_k": content.get("top_k", 5)},
                )
            except Exception as e:
                logger.warning("Librarian vector search failed: %s", e)
                docs_result = {"error": str(e), "documents": []}
            docs = (
                docs_result.get("documents", docs_result)
                if isinstance(docs_result, dict)
                else docs_result
            )
            parts["documents"] = docs if isinstance(docs, list) else [docs]
        if fund:
            try:
                graph_result = self.mcp_client.call_tool(
                    "kg_tool.get_relations", {"entity": fund}
                )
            except Exception as e:
                logger.warning("Librarian graph query failed: %s", e)
                graph_result = {"error": str(e)}
            parts["graph"] = (
                graph_result
                if isinstance(graph_result, dict) and "error" not in graph_result
                else {}
            )
        if sql_query:
            try:
                sql_result = self.mcp_client.call_tool(
                    "sql_tool.run_query",
                    {"query": sql_query, "params": content.get("sql_params")},
                )
            except Exception as e:
                logger.warning("Librarian SQL query failed: %s", e)
                sql_result = {"error": str(e), "rows": []}
            parts["sql"] = sql_result if isinstance(sql_result, dict) else {"rows": []}

        # Build response payload from collected parts or an explicit error.
        if not parts:
            reply_content: Any = {"error": "Missing vector_query, fund, or sql_query"}
        else:
            docs_list = (
                list(parts["documents"])
                if isinstance(parts.get("documents"), list)
                else []
            )
            graph_data = parts.get("graph", {})
            reply_content = self.combine_results(docs_list, graph_data)
            if parts.get("sql"):
                reply_content["sql"] = parts["sql"]
            attach_structured_timeseries_metrics(reply_content)

        # Keep summary generation at the end so both execution paths share it.
        if self._llm_client is not None and isinstance(reply_content, dict):
            from llm.prompts import LIBRARIAN_SYSTEM, get_librarian_user_content

            query = content.get("query") or ""
            user_content = get_librarian_user_content(str(query)[:500], reply_content)
            try:
                summary = self._llm_client.complete(LIBRARIAN_SYSTEM, user_content)
            except Exception as e:
                logger.warning("Librarian fallback summary generation failed: %s", e)
                summary = ""
            reply_content = dict(reply_content)
            reply_content["summary"] = summary
        self._send_inform(message, reply_content, conversation_id)

    def _execute_tool_calls(self, tool_calls: list) -> dict[str, Any]:
        """Execute a list of {tool, payload} dicts via mcp_client; return parts dict (documents, graph, sql)."""
        parts: dict[str, Any] = {}
        for tc in tool_calls:
            tool = tc.get("tool", "")
            payload = tc.get("payload") or {}
            if not isinstance(tool, str) or not tool.strip():
                continue
            try:
                result = self.mcp_client.call_tool(tool, payload)
            except Exception as e:
                logger.warning("Librarian tool call failed (%s): %s", tool, e)
                result = {"error": str(e)}
            if tool == "vector_tool.search":
                docs = (
                    result.get("documents", result)
                    if isinstance(result, dict)
                    else result
                )
                docs_list = docs if isinstance(docs, list) else [docs]
                parts.setdefault("documents", []).extend(docs_list)
            elif tool in (
                "kg_tool.get_relations",
                "kg_tool.get_node_by_id",
                "kg_tool.query_graph",
                "kg_tool.fulltext_search",
            ):
                if not isinstance(result, dict):
                    continue
                err = result.get("error")
                has_payload = any(
                    bool(result.get(k)) for k in ("nodes", "edges", "rows", "node")
                )
                if err and (not has_payload):
                    continue
                existing = parts.get("graph", {})
                if not isinstance(existing, dict):
                    existing = {}
                for k in ("nodes", "edges", "rows"):
                    if k in result and result[k]:
                        existing.setdefault(k, []).extend(
                            result[k] if isinstance(result[k], list) else [result[k]]
                        )
                node_one = result.get("node")
                if node_one:
                    existing.setdefault("nodes", []).append(node_one)
                parts["graph"] = existing
            elif tool.startswith("sql_tool."):
                parts["sql"] = result if isinstance(result, dict) else {"rows": []}
        return parts

    def _build_reply_from_parts(self, parts: dict[str, Any]) -> Any:
        """Build reply_content from parts (same shape as content-key path)."""
        if not parts:
            return {"error": "No tool results"}
        docs_list = (
            list(parts.get("documents", []))
            if isinstance(parts.get("documents"), list)
            else []
        )
        graph_data = (
            parts.get("graph", {}) if isinstance(parts.get("graph"), dict) else {}
        )
        reply_content = self.combine_results(docs_list, graph_data)
        if parts.get("sql"):
            reply_content["sql"] = parts["sql"]
        return reply_content

    def _send_inform(
        self, message: ACLMessage, reply_content: Any, conversation_id: str
    ) -> None:
        """Send INFORM to reply_to and append flow event."""
        if isinstance(reply_content, dict):
            reply_content = self._augment_librarian_contract(reply_content)
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
        if self.conversation_manager and conversation_id:
            summary = (
                "documents and graph" if isinstance(reply_content, dict) else "data"
            )
            self.conversation_manager.append_flow(
                conversation_id,
                {
                    "step": "librarian_done",
                    "message": f"**Librarian** has returned {summary}.",
                    "detail": {
                        "reply_keys": list(reply_content.keys())
                        if isinstance(reply_content, dict)
                        else []
                    },
                },
            )

    def _augment_librarian_contract(
        self, reply_content: dict[str, Any]
    ) -> dict[str, Any]:
        """Attach schema-first librarian contract fields expected by planner."""
        out = dict(reply_content)
        docs = out.get("documents")
        raw_doc_list = docs if isinstance(docs, list) else []
        documents: list[dict[str, Any]] = []
        key_facts: list[dict[str, Any]] = []
        evidence: dict[str, str] = {}
        citations: list[str] = []

        # Convert top documents into planner-friendly evidence and citation ids.
        for i, d in enumerate(raw_doc_list[:5], start=1):
            if not isinstance(d, dict):
                continue
            doc_id_raw = d.get("doc_id") or d.get("id") or f"DOC{i}"
            doc_id = str(doc_id_raw).strip() or f"DOC{i}"
            title_raw = d.get("title") or d.get("name") or ""
            source_raw = d.get("source") or d.get("provider") or ""
            ts_raw = d.get("timestamp") or d.get("date") or ""
            snippet_raw = d.get("snippet") or d.get("content") or d.get("text") or ""
            snippet = str(snippet_raw).strip()
            documents.append(
                {
                    "doc_id": doc_id,
                    "title": str(title_raw).strip(),
                    "snippet": snippet[:400],
                    "source": str(source_raw).strip(),
                    "timestamp": str(ts_raw).strip(),
                }
            )
            if snippet:
                key_facts.append(
                    {
                        "fact": snippet[:240],
                        "confidence": 0.7,
                        "evidence_doc_ids": [doc_id],
                    }
                )
                evidence[doc_id] = snippet[:400]
                citations.append(doc_id)
        doc_coverage = len(evidence)
        confidence = min(1.0, round(doc_coverage / 3.0, 2)) if doc_coverage else 0.0
        raw_errors = out.get("errors")

        # Normalize heterogeneous error shapes to a clean list[str].
        if raw_errors is None:
            errors: list[str] = []
        elif isinstance(raw_errors, str):
            errors = [raw_errors] if raw_errors.strip() else []
        elif isinstance(raw_errors, (list, tuple)):
            errors = [str(e).strip() for e in raw_errors if str(e).strip()]
        else:
            text = str(raw_errors).strip()
            errors = [text] if text else []
        if doc_coverage == 0 and (not errors):
            errors.append("no_internal_documents")
        out["agent"] = "librarian"
        out["documents"] = documents
        out["key_facts"] = key_facts
        out["evidence"] = evidence
        out["citations"] = citations
        out["confidence"] = confidence
        out["errors"] = errors
        return out

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
        return {"documents": docs, "graph": graph_data}
