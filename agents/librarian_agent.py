"""Librarian agent: vector and graph retrieval via MCP (Milvus, Neo4j)."""

from typing import Any

from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus
from agents.base_agent import BaseAgent


class LibrarianAgent(BaseAgent):
    """
    Retrieves structured data from knowledge graph and vector database.

    Uses MCP vector_tool (Milvus) and kg_tool (Neo4j); does not access
    databases directly.
    """

    def __init__(
        self, name: str, message_bus: MessageBus, mcp_client: Any = None
    ) -> None:
        super().__init__(name, message_bus)
        self.mcp_client = mcp_client

    def handle_message(self, message: ACLMessage) -> None:
        """
        Process data retrieval requests.

        Parse request, call MCP vector_tool and kg_tool, combine_results,
        send reply ACL message.

        Args:
            message: The received ACL message.
        """
        raise NotImplementedError

    def retrieve_knowledge_graph(self, fund: str) -> dict:
        """
        Query knowledge graph for fund relationships via MCP kg_tool (Neo4j).

        Args:
            fund: Fund identifier.

        Returns:
            Structured graph data (nodes/edges).
        """
        raise NotImplementedError

    def retrieve_documents(self, query: str) -> list:
        """
        Perform semantic search over vector DB via MCP vector_tool (Milvus).

        Args:
            query: Search query.

        Returns:
            List of retrieved documents with scores.
        """
        raise NotImplementedError

    def combine_results(self, docs: list, graph_data: dict) -> dict:
        """
        Merge vector and graph results for downstream Analyst.

        Args:
            docs: Documents from vector search.
            graph_data: Result from knowledge graph query.

        Returns:
            Single structured result dict.
        """
        raise NotImplementedError
