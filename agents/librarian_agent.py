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

        Slice 3: file_tool.read_file only. Content may have "path" or "query"
        (Planner sends query; E2E can pass path). Call MCP, then send INFORM
        back to reply_to (Planner) with file content or error.

        Args:
            message: The received ACL message.
        """
        if not self.mcp_client:
            return
        content = message.content or {}
        path = content.get("path")
        if not path and content.get("query"):
            path = content.get("query")  # Planner often sends query; treat as path for read_file
        if not path:
            reply_content = {"error": "Missing path or query"}
        else:
            result = self.mcp_client.call_tool("file_tool.read_file", {"path": path})
            reply_content = dict(result) if isinstance(result, dict) else {"content": str(result)}
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
        raise NotImplementedError

    def retrieve_documents(self, query: str) -> list:
        """Perform semantic search over vector DB via MCP vector_tool (Milvus).

        Args:
            query: Search query.

        Returns:
            List of retrieved documents with scores.
        """
        raise NotImplementedError

    def combine_results(self, docs: list, graph_data: dict) -> dict:
        """Merge vector and graph results for downstream Analyst.

        Args:
            docs: Documents from vector search.
            graph_data: Result from knowledge graph query.

        Returns:
            Single structured result dict.
        """
        raise NotImplementedError
