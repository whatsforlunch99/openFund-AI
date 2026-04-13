"""Canonical MCP tool registry.

Single source of truth for:
- tool metadata (name, payload mapping, description)
- registration for in-process MCPServer and FastMCP stdio
- per-agent allowed tool sets and prompt-order descriptions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolArgSpec:
    """Map payload fields to handler kwargs."""

    param_name: str
    payload_keys: tuple[str, ...]
    default: Any = None
    coerce: Callable[[Any], Any] | type | None = None


@dataclass(frozen=True)
class ToolSpec:
    """Canonical MCP tool definition."""

    name: str
    description: str
    handler: Callable[..., Any]
    required_keys: tuple[str, ...] = ()
    arg_specs: tuple[ToolArgSpec, ...] = ()
    result_key: str | None = None
    agents_allowed: tuple[str, ...] = ()
    available: Callable[[], bool] | None = None


def _always_available() -> bool:
    return True


def _safe_available(pred: Callable[[], bool] | None) -> bool:
    if pred is None:
        return True
    try:
        return bool(pred())
    except Exception:
        return False


def _coerce_value(coerce: Callable[[Any], Any] | type | None, val: Any, default: Any) -> Any:
    if coerce is None:
        return val
    if val is None:
        return default
    if coerce is int:
        return int(val)
    if callable(coerce):
        return coerce(val)
    return val


def build_payload_handler(spec: ToolSpec) -> Callable[[dict], dict]:
    """Build MCPServer payload dict -> result dict handler."""

    def handler(payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        for key in spec.required_keys:
            if key not in payload:
                return {"error": f"Missing required parameter '{key}'"}
        kwargs: dict[str, Any] = {}
        for a in spec.arg_specs:
            val = a.default
            for pk in a.payload_keys:
                if pk in payload:
                    val = payload[pk]
                    break
            kwargs[a.param_name] = _coerce_value(a.coerce, val, a.default)
        result = spec.handler(**kwargs)
        if spec.result_key is not None:
            return {spec.result_key: result}
        return result

    return handler


def _spec_from_tool_spec(module: Any, row: tuple[str, str, list[str], list, str | None], description_by_name: dict[str, str], agents_allowed: tuple[str, ...]) -> ToolSpec:
    name, func_name, required, arg_specs, result_key = row
    args = tuple(
        ToolArgSpec(
            param_name=a[0],
            payload_keys=tuple(a[1]),
            default=a[2],
            coerce=a[3],
        )
        for a in arg_specs
    )
    return ToolSpec(
        name=name,
        description=description_by_name.get(name, name),
        handler=getattr(module, func_name),
        required_keys=tuple(required),
        arg_specs=args,
        result_key=result_key,
        agents_allowed=agents_allowed,
        available=_always_available,
    )


def _load_modules() -> dict[str, Any]:
    from openfund_mcp.tools._shared import capabilities
    from openfund_mcp.tools.file import tool as file_tool
    from openfund_mcp.tools.websearch import fund_catalog as fund_catalog_tool
    from openfund_mcp.tools.graph import tool as kg_tool
    from openfund_mcp.tools.websearch import tool as news_tool
    from openfund_mcp.tools.sql import tool as sql_tool
    from openfund_mcp.tools.vendor import stooq as stooq_tool
    from openfund_mcp.tools.vector import tool as vector_tool
    from openfund_mcp.tools.vendor import yahoo_finance as yahoo_finance_tool
    from openfund_mcp.tools.vendor import etfdb as etfdb_tool

    out = {
        "capabilities": capabilities,
        "etfdb_tool": etfdb_tool,
        "file_tool": file_tool,
        "fund_catalog_tool": fund_catalog_tool,
        "kg_tool": kg_tool,
        "news_tool": news_tool,
        "sql_tool": sql_tool,
        "stooq_tool": stooq_tool,
        "vector_tool": vector_tool,
        "yahoo_finance_tool": yahoo_finance_tool,
    }
    try:
        from openfund_mcp.tools.analyst import tool as analyst_tool

        out["analyst_tool"] = analyst_tool
    except ImportError:
        pass
    try:
        from openfund_mcp.tools.market import routing as market_tool

        out["market_tool"] = market_tool
    except ImportError:
        pass
    return out


def _description_source() -> dict[str, str]:
    from openfund_mcp.tools.registry_metadata import TOOL_DESCRIPTIONS_BY_NAME

    return TOOL_DESCRIPTIONS_BY_NAME


def get_all_tools() -> list[ToolSpec]:
    """Build canonical tool list from modules and legacy TOOL_SPECS."""
    mods = _load_modules()
    desc = _description_source()

    tools: list[ToolSpec] = []
    tools.extend(
        _spec_from_tool_spec(mods["vector_tool"], row, desc, ("librarian",))
        for row in mods["vector_tool"].TOOL_SPECS
    )
    tools.extend(
        _spec_from_tool_spec(mods["kg_tool"], row, desc, ("librarian",))
        for row in mods["kg_tool"].TOOL_SPECS
    )
    tools.extend(
        _spec_from_tool_spec(mods["sql_tool"], row, desc, ("librarian",))
        for row in mods["sql_tool"].TOOL_SPECS
    )
    if "market_tool" in mods:
        tools.extend(
            _spec_from_tool_spec(mods["market_tool"], row, desc, ("websearcher",))
            for row in mods["market_tool"].TOOL_SPECS
        )
    if "analyst_tool" in mods:
        tools.extend(
            _spec_from_tool_spec(mods["analyst_tool"], row, desc, ("analyst",))
            for row in mods["analyst_tool"].TOOL_SPECS
        )

    # file tool
    tools.append(
        ToolSpec(
            name="file_tool.read_file",
            description=desc["file_tool.read_file"],
            handler=mods["file_tool"].read_file,
            required_keys=("path",),
            arg_specs=(ToolArgSpec("path", ("path",), "", None),),
            agents_allowed=("librarian",),
            available=_always_available,
        )
    )

    # news tools
    tools.append(
        ToolSpec(
            name="news_tool.search_rss",
            description=desc["news_tool.search_rss"],
            handler=mods["news_tool"].search_rss,
            arg_specs=(
                ToolArgSpec("payload", ("__payload__",), None, None),
            ),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="news_tool.search_yahoo_rss",
            description=desc["news_tool.search_yahoo_rss"],
            handler=mods["news_tool"].search_yahoo_rss,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="news_tool.search_gdelt",
            description=desc["news_tool.search_gdelt"],
            handler=mods["news_tool"].search_gdelt,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="news_tool.search_playwright",
            description=desc["news_tool.search_playwright"],
            handler=mods["news_tool"].search_playwright,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )

    # websearch vendor tools
    tools.append(
        ToolSpec(
            name="fund_catalog_tool.search",
            description=desc["fund_catalog_tool.search"],
            handler=mods["fund_catalog_tool"].search,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="yahoo_finance_tool.get_fundamental",
            description=desc["yahoo_finance_tool.get_fundamental"],
            handler=mods["yahoo_finance_tool"].get_fundamental,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="yahoo_finance_tool.get_price",
            description=desc["yahoo_finance_tool.get_price"],
            handler=mods["yahoo_finance_tool"].get_price,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="stooq_tool.get_price",
            description=desc["stooq_tool.get_price"],
            handler=mods["stooq_tool"].get_price,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )
    tools.append(
        ToolSpec(
            name="etfdb_tool.get_fund_data",
            description=desc["etfdb_tool.get_fund_data"],
            handler=mods["etfdb_tool"].get_fund_data,
            arg_specs=(ToolArgSpec("payload", ("__payload__",), None, None),),
            agents_allowed=("websearcher",),
            available=_always_available,
        )
    )

    tools.append(
        ToolSpec(
            name="get_capabilities",
            description=desc["get_capabilities"],
            handler=mods["capabilities"].get_capabilities,
            arg_specs=(ToolArgSpec("tool_names", ("__registered_tool_names__",), (), None),),
            agents_allowed=("librarian", "websearcher", "analyst"),
            available=_always_available,
        )
    )

    return tools


def get_tool_spec_map() -> dict[str, ToolSpec]:
    """Map tool name -> ToolSpec for available tools."""
    out: dict[str, ToolSpec] = {}
    for spec in get_all_tools():
        if _safe_available(spec.available):
            out[spec.name] = spec
    return out


def call_by_spec(spec: ToolSpec, payload: dict, registered_tool_names: list[str] | None = None) -> dict:
    """Call a ToolSpec with payload using canonical mapping rules."""
    payload = payload if isinstance(payload, dict) else {}

    # passthrough payload-style tools
    if len(spec.arg_specs) == 1 and spec.arg_specs[0].payload_keys == ("__payload__",):
        result = spec.handler(payload)
        return result if isinstance(result, dict) else {"result": result}

    # capabilities special-case to inject live names
    if spec.name == "get_capabilities":
        names = registered_tool_names or []
        result = spec.handler(names)
        return result if isinstance(result, dict) else {"result": result}

    return build_payload_handler(spec)(payload)


def get_allowed_tools_by_agent() -> dict[str, frozenset[str]]:
    from openfund_mcp.tools.registry_metadata import (
        ANALYST_ALLOWED_TOOL_NAMES,
        LIBRARIAN_ALLOWED_TOOL_NAMES,
        WEBSEARCHER_ALLOWED_TOOL_NAMES,
    )

    return {
        "librarian": LIBRARIAN_ALLOWED_TOOL_NAMES,
        "websearcher": WEBSEARCHER_ALLOWED_TOOL_NAMES,
        "analyst": ANALYST_ALLOWED_TOOL_NAMES,
    }


def get_tool_descriptions_by_name() -> dict[str, str]:
    return _description_source()

