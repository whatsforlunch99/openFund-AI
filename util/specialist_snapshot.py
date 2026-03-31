"""Bounded JSON-safe snapshots of specialist INFORM payloads for conversation persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

SPECIALIST_AGENTS: tuple[str, ...] = ("librarian", "websearcher", "analyst")

# Per-agent cap on serialized JSON size (characters) to keep conversations.json small.
_MAX_JSON_CHARS_PER_AGENT = 48 * 1024
_SUMMARY_MAX = 8000
_ERR_SNIPPET = 240
_SUBQUERY_MAX = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trunc_str(s: Any, max_len: int) -> str:
    if s is None:
        return ""
    t = str(s).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def _error_or_present(val: Any) -> dict[str, Any]:
    """Summarize a tool-style dict: error string or presence hint."""
    if not isinstance(val, dict):
        return {"status": "absent"}
    err = val.get("error")
    if isinstance(err, str) and err.strip():
        return {"status": "error", "error": _trunc_str(err, _ERR_SNIPPET)}
    if val.get("content") is not None:
        return {"status": "present"}
    return {"status": "present" if val else "empty"}


def _snapshot_librarian(content: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "recorded_at": _now_iso(),
        "sub_query": _trunc_str(content.get("query"), _SUBQUERY_MAX),
        "content_keys": sorted(str(k) for k in content.keys() if k != "query"),
    }
    summ = content.get("summary")
    if isinstance(summ, str) and summ.strip():
        out["summary"] = _trunc_str(summ, _SUMMARY_MAX)

    docs = content.get("documents")
    if isinstance(docs, list):
        out["document_count"] = len(docs)
        preview: list[dict[str, Any]] = []
        for d in docs[:3]:
            if isinstance(d, dict):
                preview.append(
                    {
                        "id": d.get("id"),
                        "score": d.get("score"),
                        "content_preview": _trunc_str(
                            d.get("content") or d.get("text"), 200
                        ),
                    }
                )
        if preview:
            out["documents_preview"] = preview

    g = content.get("graph")
    if isinstance(g, dict):
        nodes = g.get("nodes")
        edges = g.get("edges")
        if isinstance(nodes, list):
            out["graph_nodes_count"] = len(nodes)
            gp: list[dict[str, Any]] = []
            for n in nodes[:5]:
                if isinstance(n, dict):
                    gp.append(
                        {
                            "id": n.get("id"),
                            "name": n.get("name"),
                            "symbol": n.get("symbol"),
                        }
                    )
            if gp:
                out["graph_nodes_preview"] = gp
        if isinstance(edges, list):
            out["graph_edges_count"] = len(edges)

    sql = content.get("sql")
    if isinstance(sql, dict):
        rows = sql.get("rows")
        if isinstance(rows, list):
            out["sql_row_count"] = len(rows)
        elif sql.get("data") is not None:
            data = sql["data"]
            if isinstance(data, list):
                out["sql_row_count"] = len(data)

    if content.get("content") is not None and "summary" not in out:
        out["content_preview"] = _trunc_str(content.get("content"), 1200)

    return out


def _snapshot_websearcher(content: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "recorded_at": _now_iso(),
        "sub_query": _trunc_str(content.get("query"), _SUBQUERY_MAX),
        "content_keys": sorted(str(k) for k in content.keys() if k != "query"),
    }
    summ = content.get("summary")
    if isinstance(summ, str) and summ.strip():
        out["summary"] = _trunc_str(summ, _SUMMARY_MAX)

    nf = content.get("normalized_fund")
    if isinstance(nf, list) and nf:
        brief: list[dict[str, Any]] = []
        for rec in nf[:5]:
            if isinstance(rec, dict):
                brief.append(
                    {
                        "symbol": rec.get("symbol"),
                        "name": _trunc_str(rec.get("name"), 120),
                        "price": rec.get("price"),
                        "price_yahoo": rec.get("price_yahoo"),
                    }
                )
        out["normalized_fund_brief"] = brief

    news = content.get("news")
    if isinstance(news, list):
        out["news_count"] = len(news)
    cit = content.get("citations")
    if isinstance(cit, list):
        out["citations_count"] = len(cit)

    out["market_data"] = _error_or_present(content.get("market_data"))
    out["sentiment"] = _error_or_present(content.get("sentiment"))
    out["regulatory"] = _error_or_present(content.get("regulatory"))

    return out


def _snapshot_analyst(content: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "recorded_at": _now_iso(),
        "sub_query": _trunc_str(content.get("query"), _SUBQUERY_MAX),
        "content_keys": sorted(str(k) for k in content.keys() if k != "query"),
    }
    analysis = content.get("analysis")
    if isinstance(analysis, dict):
        conf = analysis.get("confidence")
        if conf is not None:
            try:
                out["confidence"] = float(conf)
            except (TypeError, ValueError):
                out["confidence"] = conf
        summ = analysis.get("summary")
        if isinstance(summ, str) and summ.strip():
            out["summary"] = _trunc_str(summ, _SUMMARY_MAX)
        dist = analysis.get("distribution")
        if isinstance(dist, dict):
            out["distribution_keys"] = sorted(str(k) for k in dist.keys())[:40]
    return out


def snapshot_specialist_payload(agent: str, content: Any) -> dict[str, Any]:
    """Return a JSON-serializable snapshot for one specialist, or {} if unusable."""
    if agent not in SPECIALIST_AGENTS:
        return {}
    if not isinstance(content, dict) or not content:
        return {}

    if agent == "librarian":
        snap = _snapshot_librarian(content)
    elif agent == "websearcher":
        snap = _snapshot_websearcher(content)
    else:
        snap = _snapshot_analyst(content)

    raw = json.dumps(snap, ensure_ascii=False, default=str)
    if len(raw) <= _MAX_JSON_CHARS_PER_AGENT:
        return snap

    # Shrink: drop previews and trim summary further.
    snap.pop("documents_preview", None)
    snap.pop("graph_nodes_preview", None)
    snap.pop("normalized_fund_brief", None)
    if "summary" in snap:
        snap["summary"] = _trunc_str(snap["summary"], 2000)
    raw2 = json.dumps(snap, ensure_ascii=False, default=str)
    if len(raw2) <= _MAX_JSON_CHARS_PER_AGENT:
        return snap
    if "summary" in snap:
        snap["summary"] = _trunc_str(snap["summary"], 400)
    snap["truncated"] = True
    return snap


def build_data_sources_from_collected(collected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map agent name -> snapshot for each agent present in collected with non-empty content."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(collected, dict):
        return out
    for agent in SPECIALIST_AGENTS:
        payload = collected.get(agent)
        snap = snapshot_specialist_payload(agent, payload)
        if snap:
            out[agent] = snap
    return out
