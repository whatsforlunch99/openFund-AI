# Dependency contract (layering)

Non-negotiable import and responsibility boundaries for refactors. Derived from [backend.md](backend.md) and [03_tools_and_mcp/README.md](../03_tools_and_mcp/README.md).

## Allowed dependency direction

- **`api/`** may depend on `a2a`, `safety`, `config`, `agents` (registration only), `memory` (persistence adapters as wired today).
- **`safety/`** depends on stdlib and local config types only; no MCP, no agents.
- **`agents/`** may depend on `a2a`, `util`, `llm`, `openfund_mcp` (via MCP client), `output` (responder), `config`. **Must not** be imported by `util/` or `openfund_mcp/`.
- **`util/`** may depend on `llm` only where needed for thin clients/helpers; **must not** import `agents`, `api`, or `openfund_mcp`.
- **`openfund_mcp/`** implements MCP tools and server; **must not** import `agents` or `api`.
- **`llm/`** prompts, clients, tool descriptions; **must not** import `agents` or `api`.
- **`a2a/`** messages, bus, conversation manager; **must not** import MCP or specialist agents.
- **`output/`** formatting/compliance; consumed by responder; no MCP.
- **`scripts/`** operational entrypoints; may import anything but is not part of the request-time graph.

## Documentation coupling

- Tool names and payloads: keep [agent-tools-reference.md](../03_tools_and_mcp/agent-tools-reference.md) and `llm/tool_descriptions.py` in sync.
- Design docs (`websearcher-design.md`, `news-searcher-design.md`) link to the reference; do not duplicate full payload tables.

## Data ingestion

- **Supported in this repository:** `scripts/data_loader.py` and `database/*` inputs (see `docs/data_prep/`).
- A legacy **`data_manager`** CLI is described historically in [progress.md](../90_product/progress.md); that package is **not** present in the current tree—do not document `python -m data_manager` as available without restoring the package.
