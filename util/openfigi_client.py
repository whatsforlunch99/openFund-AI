"""OpenFIGI v3 mapping client (trusted symbol universe check)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_OPENFIGI_MAPPING = "https://api.openfigi.com/v3/mapping"
_HTTP_TIMEOUT = float(os.environ.get("MCP_HTTP_TIMEOUT_SECONDS", "8"))


def map_us_equity_ticker(ticker: str) -> dict[str, Any]:
    """
    Map a US equity ticker via OpenFIGI. Requires OPENFIGI_API_KEY.

    Returns:
        {"ok": True, "figi": str, "name": str, "security_type": str, "ticker": str, "raw": list}
        or {"ok": False, "error": str, "reason_code": str}
    """
    key = (os.environ.get("OPENFIGI_API_KEY") or "").strip()
    if not key:
        return {
            "ok": False,
            "error": "OPENFIGI_API_KEY not set",
            "reason_code": "openfigi_unconfigured",
        }
    sym = (ticker or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "empty ticker", "reason_code": "invalid_ticker"}
    body = [{"idType": "TICKER", "idValue": sym, "exchCode": "US"}]
    headers = {
        "Content-Type": "application/json",
        "X-OPENFIGI-APIKEY": key,
    }
    try:
        resp = requests.post(
            _OPENFIGI_MAPPING,
            json=body,
            headers=headers,
            timeout=max(3.0, _HTTP_TIMEOUT),
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("openfigi mapping failed for %s: %s", sym, e)
        return {"ok": False, "error": str(e), "reason_code": "openfigi_http_error"}

    if not isinstance(data, list) or not data:
        return {"ok": False, "error": "empty OpenFIGI response", "reason_code": "openfigi_empty"}

    first = data[0]
    if not isinstance(first, dict):
        return {"ok": False, "error": "invalid OpenFIGI response", "reason_code": "openfigi_parse"}

    warn = first.get("warning")
    if warn:
        return {
            "ok": False,
            "error": str(warn),
            "reason_code": "openfigi_warning",
        }

    results = first.get("data")
    if not isinstance(results, list) or not results:
        return {"ok": False, "error": "no mapping data", "reason_code": "openfigi_no_match"}

    if len(results) > 5:
        return {
            "ok": False,
            "error": "too many OpenFIGI matches",
            "reason_code": "openfigi_ambiguous",
        }

    row = results[0]
    if not isinstance(row, dict):
        return {"ok": False, "error": "bad row", "reason_code": "openfigi_parse"}

    figi = row.get("figi") or row.get("compositeFIGI") or ""
    name = row.get("name") or row.get("securityDescription") or ""
    sec_type = row.get("securityType") or row.get("securityType2") or ""
    tick = row.get("ticker") or sym

    if not figi:
        return {"ok": False, "error": "missing FIGI", "reason_code": "openfigi_no_figi"}

    return {
        "ok": True,
        "figi": str(figi),
        "name": str(name) if name else "",
        "security_type": str(sec_type) if sec_type else "",
        "ticker": str(tick).upper() if tick else sym,
        "raw": results[:3],
    }
