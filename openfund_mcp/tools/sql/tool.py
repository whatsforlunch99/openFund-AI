"""Stable MCP-facing SQL tool surface."""

from openfund_mcp.tools.sql.postgres import *  # noqa: F403
from openfund_mcp.tools.sql import postgres as _postgres

_normalize_sql_bind_params = _postgres._normalize_sql_bind_params
