"""Milvus data management: index and delete demo documents.

Uses mcp.tools.vector_tool. For one-off index/delete use the CLI
(data cli milvus index/delete) or vector_tool directly.
"""

from __future__ import annotations

import logging
import os

from data.env_loader import load_dotenv as _load_dotenv

logger = logging.getLogger(__name__)


def populate_milvus() -> tuple[bool, str]:
    """Index two demo documents (content from demo_data). Uses MILVUS_URI."""
    _load_dotenv()
    if not os.environ.get("MILVUS_URI"):
        return False, "MILVUS_URI not set; skipping Milvus."
    from mcp.tools import vector_tool

    # Content from demo_data.VECTOR_SEARCH_RESPONSE; use source so we can delete before re-index.
    docs = [
        {
            "content": "NVIDIA (NVDA) is a leading semiconductor company focused on graphics and AI. Suitable for long-term growth investors; volatility can be high.",
            "fund_id": "NVDA",
            "source": "demo",
        },
        {
            "content": "NVDA fundamentals: Technology sector, strong revenue growth. Not a recommendation to buy or sell.",
            "fund_id": "NVDA",
            "source": "demo",
        },
    ]

    # Idempotent: delete existing demo docs by source before indexing.
    out = vector_tool.delete_by_expr('source == "demo"')
    if out.get("error"):
        # Ignore delete error (e.g. empty collection or first run); proceed to index.
        logger.debug("Milvus delete_by_expr (pre-index): %s", out.get("error"))
    out = vector_tool.index_documents(docs)
    if out.get("status") == "error" or out.get("error"):
        err = out.get("error", "unknown")
        if "Fail connecting" in str(err) or "server unavailable" in str(err):
            err = str(err) + " Start Milvus with: ./scripts/start_milvus.sh (the plain 'docker run milvusdb/milvus' does not start the server). Wait ~60s then run populate again."
        return False, f"Milvus failed: {err}"
    return True, f"Milvus: indexed {out.get('indexed', 0)} demo document(s)."
