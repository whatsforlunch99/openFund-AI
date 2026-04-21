"""Format collected specialist payloads for planner sufficiency and responder handoff."""

from __future__ import annotations

from typing import Any

from util.answer_coverage import (
    has_structured_timeseries_metrics,
    normalized_fund_price_line,
)
from util.symbol_query_extract import extract_symbol_from_query
from util.timeseries_metrics import (
    format_timeseries_metrics_for_final_response,
    format_timeseries_metrics_for_sufficiency_chunk,
)


def planner_snippet(text: str | None, max_len: int = 120) -> str:
    """Return text truncated to max_len with '...' if longer. Handles None/non-str."""
    if text is None:
        return ""
    s = str(text).strip()
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def planner_websearcher_price_line(w: dict[str, Any]) -> str:
    """One-line price summary from websearcher normalized_fund."""
    return normalized_fund_price_line(w)


def planner_librarian_sql_signal_line(c: dict[str, Any]) -> str:
    """Short line for sufficiency: whether SQL returned rows."""
    sql = c.get("sql")
    if not isinstance(sql, dict):
        return ""
    rc = sql.get("row_count")
    try:
        if isinstance(rc, int) and rc > 0:
            return f"sql_row_count={rc}"
    except (TypeError, ValueError):
        pass
    data = sql.get("data")
    if isinstance(data, list) and len(data) > 0:
        return f"sql_data_rows={len(data)}"
    rows = sql.get("rows")
    if isinstance(rows, list) and len(rows) > 0:
        return f"sql_rows={len(rows)}"
    return ""


def format_planner_final(collected: dict[str, Any]) -> str:
    """Turn collected agent outputs into a single string for Responder."""
    parts: list[str] = []
    if "librarian" in collected:
        c = collected["librarian"]
        if c.get("content"):
            parts.append(str(c["content"]))
        elif c.get("documents") or c.get("graph"):
            bits: list[str] = []
            docs = c.get("documents")
            if isinstance(docs, list) and docs:
                bits.append(f"{len(docs)} doc(s)")
                first = docs[0]
                if isinstance(first, dict):
                    content_str = first.get("content") or first.get("text")
                    if isinstance(content_str, str) and content_str.strip():
                        bits.append(f' (e.g. "{planner_snippet(content_str, 120)}")')
            g = c.get("graph")
            if isinstance(g, dict) and g.get("nodes"):
                nodes = g["nodes"]
                if isinstance(nodes, list) and nodes:
                    bits.append(f"{len(nodes)} graph node(s)")
                    ids = []
                    for n in nodes[:3]:
                        if isinstance(n, dict):
                            nid = n.get("id")
                            if nid is None:
                                lbl = n.get("label")
                                nid = lbl[0] if isinstance(lbl, list) and lbl else lbl
                            if nid is not None:
                                ids.append(str(nid))
                    if ids:
                        bits.append(f" ({', '.join(ids)})")
            if bits:
                parts.append("Librarian: " + ", ".join(bits).strip() + ".")
            else:
                parts.append("Librarian: no content.")
        else:
            parts.append("Librarian: data retrieved.")
        stm = c.get("structured_timeseries_metrics")
        if isinstance(stm, dict):
            line_stm = format_timeseries_metrics_for_final_response(stm)
            if line_stm:
                parts.append(line_stm)

    if "websearcher" in collected:
        w = collected["websearcher"]
        has_ws_payload = bool(
            w.get("market_data")
            or w.get("sentiment")
            or w.get("normalized_fund")
            or w.get("summary")
        )
        if has_ws_payload:
            bits_ws: list[str] = []
            ws_query = w.get("query") or ""
            expected_symbol = (
                extract_symbol_from_query(ws_query) if isinstance(ws_query, str) else ""
            )
            nf = w.get("normalized_fund") or []
            actual_symbols = [
                rec.get("symbol")
                for rec in nf
                if isinstance(rec, dict) and rec.get("symbol")
            ]
            symbol_mismatch = bool(
                expected_symbol
                and actual_symbols
                and expected_symbol.upper() not in {s.upper() for s in actual_symbols}
            )
            if symbol_mismatch:
                bits_ws.append(
                    f"No market data could be retrieved for the requested symbol ({expected_symbol})."
                )
                price_line = ""
            else:
                price_line = planner_websearcher_price_line(w)
                if price_line:
                    bits_ws.append(f"price: {price_line}")
            summary_ws = w.get("summary")
            if isinstance(summary_ws, str) and summary_ws.strip():
                cap = 280 if price_line else 120
                bits_ws.append(f'"{planner_snippet(summary_ws, cap)}"')
            elif not price_line:
                for key, label in (
                    ("market_data", "market data"),
                    ("sentiment", "sentiment"),
                ):
                    val = w.get(key)
                    if isinstance(val, dict):
                        err = val.get("error")
                        if isinstance(err, str) and err.strip():
                            bits_ws.append(f"{label}: error {planner_snippet(err, 80)}")
                        else:
                            content_val = val.get("content")
                            if isinstance(content_val, str) and content_val.strip():
                                bits_ws.append(
                                    f'{label}: "{planner_snippet(content_val, 120)}"'
                                )
                            else:
                                bits_ws.append(f"{label} present, no content")
            if bits_ws:
                parts.append("WebSearcher: " + "; ".join(bits_ws) + ".")
            else:
                parts.append("WebSearcher: no content.")
            if w.get("news_synthetic") or (
                w.get("news_confidence") == "low" and not (w.get("citations") or {})
            ):
                parts.append(
                    "WebSearcher news: synthetic/low-confidence fallback (no verified feed URLs); "
                    "do not treat headlines as confirmed facts."
                )

    if "analyst" in collected:
        a = collected["analyst"]
        if a.get("analysis") is not None:
            analysis_val = a["analysis"]
            bits_a: list[str] = []
            if isinstance(analysis_val, dict):
                conf = analysis_val.get("confidence")
                if conf is not None:
                    bits_a.append(f"confidence {conf}")
                summary_a = analysis_val.get("summary")
                if isinstance(summary_a, str) and summary_a.strip():
                    bits_a.append(f'"{planner_snippet(summary_a, 120)}"')
                elif not bits_a:
                    bits_a.append(planner_snippet(str(analysis_val), 150))
            else:
                bits_a.append(planner_snippet(str(analysis_val), 120))
            if bits_a:
                parts.append("Analyst: " + " ".join(bits_a) + ".")
            else:
                parts.append("Analyst: no content.")

    return " ".join(parts) if parts else "Research round complete."


def conversation_state_snippet(content: dict[str, Any], max_chars: int = 350) -> str:
    """Human-readable summary of agent result for flow display."""
    if not content:
        return ""
    err = content.get("error")
    if isinstance(err, str) and err.strip():
        return f"Error: {planner_snippet(err, 250)}"
    if isinstance(content.get("market_data"), dict) and content["market_data"].get(
        "error"
    ):
        e = content["market_data"]["error"]
        return f"Error: {planner_snippet(e, 250)}"
    summary = content.get("summary")
    if isinstance(summary, str) and summary.strip():
        return f"Summary: {planner_snippet(summary, max_chars)}"
    parts = []
    for key in (
        "market_data",
        "sentiment",
        "analysis",
        "documents",
        "graph",
        "combined_data",
    ):
        val = content.get(key)
        if val is None:
            continue
        if isinstance(val, dict) and val.get("error"):
            parts.append(f"{key}: Error: {planner_snippet(val.get('error'), 120)}")
        elif isinstance(val, dict):
            parts.append(f"{key}: present ({len(val)} keys)")
        elif isinstance(val, list):
            parts.append(f"{key}: {len(val)} items")
        else:
            parts.append(f"{key}: {planner_snippet(str(val), 150)}")
    if parts:
        return " | ".join(parts)
    return f"Result: {planner_snippet(str(content), max_chars)}"


def collected_has_answer_signal(collected: dict[str, Any]) -> bool:
    """True if at least one specialist returned usable facts (partial answer eligible)."""
    w = collected.get("websearcher")
    if isinstance(w, dict):
        if planner_websearcher_price_line(w).strip():
            return True
        summ = w.get("summary")
        if isinstance(summ, str) and len(summ.strip()) >= 120:
            return True
    lib = collected.get("librarian")
    if isinstance(lib, dict):
        if has_structured_timeseries_metrics(lib):
            return True
        if planner_librarian_sql_signal_line(lib):
            return True
        summ = lib.get("summary")
        if isinstance(summ, str) and len(summ.strip()) >= 120:
            return True
        docs = lib.get("documents")
        if isinstance(docs, list) and len(docs) > 0:
            return True
        g = lib.get("graph")
        if (
            isinstance(g, dict)
            and isinstance(g.get("nodes"), list)
            and len(g["nodes"]) > 0
        ):
            return True
    an = collected.get("analyst")
    if isinstance(an, dict):
        av = an.get("analysis")
        if isinstance(av, dict):
            s = av.get("summary")
            if isinstance(s, str) and len(s.strip()) >= 80:
                return True
        elif av is not None and len(str(av).strip()) >= 80:
            return True
    return False


def format_aggregated_for_sufficiency(collected: dict[str, Any]) -> str:
    """Build a string from collected agent outputs for LLM sufficiency check."""
    parts: list[str] = []
    for agent in ("librarian", "websearcher", "analyst"):
        if agent not in collected:
            continue
        c = collected[agent]
        if not isinstance(c, dict):
            parts.append(f"[{agent}] (non-dict payload)")
            continue
        chunk_lines: list[str] = []
        summary = c.get("summary")
        if isinstance(summary, str) and summary.strip():
            chunk_lines.append(summary.strip())
        if agent == "websearcher":
            pl = planner_websearcher_price_line(c)
            if pl:
                chunk_lines.append(f"normalized_fund_prices: {pl}")
            nf = c.get("normalized_fund")
            if isinstance(nf, list) and nf:
                syms = [
                    str(rec.get("symbol", ""))
                    for rec in nf
                    if isinstance(rec, dict) and rec.get("symbol")
                ]
                if syms:
                    chunk_lines.append(
                        f"normalized_fund_symbols: {', '.join(syms[:8])}"
                    )
        if agent == "librarian":
            sql_line = planner_librarian_sql_signal_line(c)
            if sql_line:
                chunk_lines.append(sql_line)
            stm = c.get("structured_timeseries_metrics")
            if isinstance(stm, dict):
                chunk = format_timeseries_metrics_for_sufficiency_chunk(stm)
                if chunk:
                    chunk_lines.append(chunk)
        if chunk_lines:
            parts.append(f"[{agent}]\n" + "\n".join(chunk_lines))
        elif c.get("market_data") or c.get("sentiment"):
            parts.append(f"[{agent}] market/sentiment data present.")
        elif c.get("analysis") is not None:
            parts.append(f"[{agent}]\n{str(c.get('analysis', ''))[:2000]}")
        else:
            parts.append(f"[{agent}] data retrieved.")
    return "\n\n".join(parts) if parts else "No data."
