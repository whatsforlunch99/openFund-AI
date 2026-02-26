"""Librarian agent: vector and graph retrieval via MCP (Milvus, Neo4j)."""

from typing import Any

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent


class LibrarianAgent(BaseAgent):
    """Retrieves structured data from knowledge graph and vector database.

    Uses MCP vector_tool (Milvus) and kg_tool (Neo4j); does not access
    databases directly.
    """

    def __init__(
        self, name: str, message_bus: MessageBus, mcp_client: Any = None
    ) -> None:
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client

    def handle_message(self, message: ACLMessage) -> None:
        """Process data retrieval requests.

        Dispatches to file_tool (path), vector_tool (vector_query), kg_tool (fund/entity),
        sql_tool (sql_query) per content; combines results and sends INFORM to reply_to.
        When only path is provided, reply is file result only (Slice 3 backward compat).

        Args:
            message: The received ACL message; content may include path, vector_query,
                fund, entity, sql_query, top_k, sql_params.
        """
        if not self.mcp_client:
            return
        content = message.content or {}
        path = content.get("path")
        if not path and content.get("query"):
            path = content.get("query")  # Planner often sends query as path for read_file
        vector_query = content.get("vector_query")
        fund = content.get("fund") or content.get("entity") or ""
        sql_query = content.get("sql_query") or content.get("sql") or ""

        # Call each requested tool and collect results
        parts = {}
        if path:
            result = self.mcp_client.call_tool("file_tool.read_file", {"path": path})
            parts["file"] = result if isinstance(result, dict) else {"content": str(result)}
        if vector_query:
            docs_result = self.mcp_client.call_tool(
                "vector_tool.search",
                {"query": vector_query, "top_k": content.get("top_k", 5)},
            )
            docs = docs_result.get("documents", docs_result) if isinstance(docs_result, dict) else docs_result
            parts["documents"] = docs if isinstance(docs, list) else [docs]
        if fund:
            graph_result = self.mcp_client.call_tool("kg_tool.get_relations", {"entity": fund})
            parts["graph"] = graph_result if isinstance(graph_result, dict) and "error" not in graph_result else {}
        if sql_query:
            sql_result = self.mcp_client.call_tool(
                "sql_tool.run_query",
                {"query": sql_query, "params": content.get("sql_params")},
            )
            parts["sql"] = sql_result if isinstance(sql_result, dict) else {"rows": []}

        # Build reply: file-only keeps Slice 3 shape; else combined structure
        if not parts:
            reply_content = {"error": "Missing path, vector_query, fund, or sql_query"}
        elif len(parts) == 1 and "file" in parts:
            reply_content = parts["file"]
        else:
            docs_list = parts.get("documents", [])
            graph_data = parts.get("graph", {})
            reply_content = self.combine_results(docs_list, graph_data)
            if parts.get("file"):
                reply_content["file"] = parts["file"]
            if parts.get("sql"):
                reply_content["sql"] = parts["sql"]

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
        result = self.mcp_client.call_tool("vector_tool.search", {"query": query, "top_k": top_k})
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
