"""Layer 2: LLM infers candidate ticker + entity name (JSON)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


class _SupportsComplete(Protocol):
    def complete(self, system_prompt: str, user_content: str) -> str: ...


_SYSTEM = """You are a financial symbol resolver. Given a user question, output ONLY a single JSON object with keys:
- candidate_symbol: US stock/ETF ticker (uppercase, 1-5 letters), or empty string if unknown
- inferred_entity_name: company or fund name you believe the user means (short), or empty
- rationale: one short phrase for logs (no PII)

No markdown, no code fences."""


def llm_infer_symbol(llm_client: _SupportsComplete, query: str) -> Optional[dict[str, Any]]:
    text = (query or "").strip()
    if not text:
        return None
    try:
        raw = llm_client.complete(_SYSTEM, f"User query:\n{text}\n\nJSON:")
    except Exception as e:
        logger.warning("symbol_resolution_llm complete failed: %s", e)
        return None
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    sym = obj.get("candidate_symbol") or obj.get("symbol")
    if not isinstance(sym, str):
        return None
    sym = sym.strip().upper()
    ent = obj.get("inferred_entity_name")
    if ent is not None and not isinstance(ent, str):
        ent = ""
    ent = (ent or "").strip()
    rat = obj.get("rationale")
    if rat is not None and not isinstance(rat, str):
        rat = ""
    if not sym or not re.match(r"^[A-Z]{1,5}$", sym):
        return None
    return {
        "candidate_symbol": sym,
        "inferred_entity_name": ent,
        "rationale": (rat or "").strip()[:200],
    }
