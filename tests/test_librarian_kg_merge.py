"""Librarian merges all kg_tool graph-shaped results into reply graph (not only get_relations)."""

from unittest.mock import MagicMock

from agents.librarian_agent import LibrarianAgent


class _McpFulltextOnly:
    def call_tool(self, tool: str, payload: dict):
        if tool == "kg_tool.fulltext_search":
            return {
                "nodes": [{"id": "000002_sz", "symbol": "000002.SZ", "name": "China Vanke Co., Ltd."}],
                "fallback": "property_contains",
            }
        return {}

    def get_registered_tool_names(self):
        return []


class _McpNodeById:
    def call_tool(self, tool: str, payload: dict):
        if tool == "kg_tool.get_node_by_id":
            return {"node": {"node_id": "000002_sz", "symbol": "000002.SZ"}}
        return {}

    def get_registered_tool_names(self):
        return []


def test_execute_tool_calls_merges_fulltext_search_nodes() -> None:
    bus = MagicMock()
    lib = LibrarianAgent("librarian", bus, mcp_client=_McpFulltextOnly())
    parts = lib._execute_tool_calls(
        [
            {
                "tool": "kg_tool.fulltext_search",
                "payload": {"index_name": "company", "query_string": "Vanke", "limit": 5},
            }
        ]
    )
    assert parts["graph"]["nodes"][0]["symbol"] == "000002.SZ"


def test_execute_tool_calls_merges_get_node_by_id_single_node() -> None:
    bus = MagicMock()
    lib = LibrarianAgent("librarian", bus, mcp_client=_McpNodeById())
    parts = lib._execute_tool_calls(
        [{"tool": "kg_tool.get_node_by_id", "payload": {"id_val": "000002_sz", "id_key": "node_id"}}]
    )
    assert len(parts["graph"]["nodes"]) == 1
    assert parts["graph"]["nodes"][0]["node_id"] == "000002_sz"
