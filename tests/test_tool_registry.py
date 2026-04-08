"""Registry consistency checks."""

from openfund_mcp.mcp_server import MCPServer
from openfund_mcp.tools.registry import get_allowed_tools_by_agent, get_tool_spec_map
from openfund_mcp.tools.registry_metadata import TOOL_DESCRIPTIONS_BY_NAME


def test_registry_tools_registered_in_mcp_server() -> None:
    server = MCPServer()
    server.register_default_tools()
    registered = set(server._handlers.keys())  # internal check for consistency test
    spec_names = set(get_tool_spec_map().keys())
    assert spec_names.issubset(registered)


def test_tool_descriptions_match_registry_tools() -> None:
    spec_names = set(get_tool_spec_map().keys())
    described = set(TOOL_DESCRIPTIONS_BY_NAME.keys())
    missing = described - spec_names
    assert missing.issubset({"analyst_tool.get_indicators"})


def test_allowed_tools_exist_in_registry() -> None:
    spec_names = set(get_tool_spec_map().keys())
    optional_missing = {"analyst_tool.get_indicators"}
    for _, allowed in get_allowed_tools_by_agent().items():
        missing = set(allowed) - spec_names
        assert missing.issubset(optional_missing)

