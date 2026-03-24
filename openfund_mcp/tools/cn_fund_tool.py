"""CN fund ingestion tools (AKShare-backed).

These tools are intended for **offline ingestion** via data_manager. They may
return {"error": "..."} when AKShare is not installed/configured.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    from data_manager.empty_markers import (
        API_MISSING,
        NOT_DISCLOSED,
        NOT_EXIST,
        PARSE_FAILED,
        is_not_disclosed_raw,
    )
except ImportError:
    NOT_EXIST = "not_exist"
    NOT_DISCLOSED = "not_disclosed"
    PARSE_FAILED = "parse_failed"
    API_MISSING = "api_missing"

    def is_not_disclosed_raw(val: object) -> bool:
        if val is None:
            return False
        s = str(val).strip()
        return s in {"未披露", "暂无", "无", "-", "---", "—", "--"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Lazy in-process cache for large AKShare tables (best-effort).
_FUND_MANAGER_LOOKUP_CACHE: dict[str, dict[str, Any]] | None = None


def _parse_date_safe(val: Any) -> date | None:
    """Parse date string (YYYY-MM-DD or YYYYMMDD) to date; return None if invalid."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _json_safe(obj: Any) -> Any:
    """Recursively convert common non-JSON types to JSON-safe primitives."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (datetime, date)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    # pandas / numpy scalar types often expose .item()
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return str(obj)


def _df_to_records(df: Any) -> list[dict]:
    try:
        recs = df.to_dict(orient="records")  # type: ignore[no-any-return]
        if isinstance(recs, list):
            return [_json_safe(r) for r in recs if isinstance(r, dict)]
        return []
    except Exception:
        return []


def _filter_items_by_fund_id(items: list[dict], fund_id: str) -> tuple[list[dict], str | None]:
    """Filter bulk result rows to a single fund_id.

    Returns (filtered_items, error_message). When the payload is large and no
    reliable fund id column exists, returns an error to avoid writing tens of
    thousands of unrelated funds into a single-fund snapshot.
    """
    if not items:
        return [], None
    fid = str(fund_id).strip()
    # Common column names observed in AKShare outputs.
    keys = ("基金代码", "代码", "fund_id", "symbol", "基金编码", "基金代码/基金简称", "基金")

    def _row_fund_id(row: dict) -> str | None:
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            s = str(v).strip()
            # Some combined fields look like "510010/xxx"; split.
            if "/" in s:
                s = s.split("/", 1)[0].strip()
            return s
        return None

    has_any_key = any(any(k in r for k in keys) for r in items[:100] if isinstance(r, dict))
    filtered = []
    if has_any_key:
        for r in items:
            if not isinstance(r, dict):
                continue
            rid = _row_fund_id(r)
            if rid == fid:
                filtered.append(r)

    # Heuristic: consider payload "bulk" if it's huge.
    is_bulk = len(items) >= 5000
    if is_bulk and not filtered:
        # Do not return unfiltered bulk data; it's not a single-fund result.
        why = "no filterable fund_id column" if not has_any_key else "fund_id not found in bulk payload"
        return [], f"Bulk response refused: {why} (items={len(items)})"
    return filtered, None


def get_basic(payload: dict) -> dict:
    """Fetch CN fund basic info by fund_id.

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for metadata only
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"error": f"AKShare not available: {e}", "timestamp": _now_iso()}

    # Preferred priority:
    # 1) EM catalog (fund_name_em) for stable name/type
    # 2) fund_manager_em enrichment (manager/company)
    # 3) Individual detail (if available; version-dependent)
    # 4) XQ as last resort (often unstable/incomplete)
    fn_xq = getattr(ak, "fund_individual_basic_info_xq", None) if hasattr(ak, "fund_individual_basic_info_xq") else None
    fn_em_individual = getattr(ak, "fund_individual_basic_info_em", None) if hasattr(ak, "fund_individual_basic_info_em") else None

    def _cell_from_raw(v: Any) -> Any:
        """Normalize raw value: not_disclosed when upstream says so, else json-safe value or None."""
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return None
        if is_not_disclosed_raw(v):
            return NOT_DISCLOSED
        return _json_safe(v)

    def _out_from_record(rec: dict, api: str) -> dict:
        def _get(*keys: str) -> Any:
            for k in keys:
                v = rec.get(k)
                if v is not None and (not isinstance(v, str) or str(v).strip()):
                    return v
            return None

        return {
            "fund_id": fund_id,
            "fund_name": _cell_from_raw(_get("基金简称", "基金名称", "name", "基金", "基金名称(简称)")),
            "fund_type": _cell_from_raw(_get("基金类型", "type", "类型")),
            "risk_level": _cell_from_raw(_get("风险等级", "risk", "风险")),
            "inception_date": _cell_from_raw(_get("成立日期", "inception_date", "成立时间")),
            "fund_manager": _cell_from_raw(_get("基金经理", "manager", "经理")),
            "management_company": _cell_from_raw(_get("基金公司", "company", "管理人")),
            "tracking_index": _cell_from_raw(_get("跟踪标的", "tracking_index", "跟踪指数")),
            "investment_scope": _cell_from_raw(_get("投资范围", "investment_scope")),
            "latest_scale": _cell_from_raw(_get("最新规模", "scale", "规模")),
            "description": _cell_from_raw(_get("基金介绍", "description", "简介")),
            "source": "akshare",
            "timestamp": _now_iso(),
            "api": api,
        }

    def _maybe_enrich_manager_fields(out: dict) -> dict:
        """Best-effort enrichment for fund_manager / management_company via fund_manager_em.

        fund_manager_em is large and can be slow; we load once per process and cache.
        """
        nonlocal ak
        if out.get("fund_manager") or out.get("management_company"):
            return out
        if not hasattr(ak, "fund_manager_em"):
            return out
        global _FUND_MANAGER_LOOKUP_CACHE
        try:
            if _FUND_MANAGER_LOOKUP_CACHE is None:
                dfm = ak.fund_manager_em()
                rows = []
                try:
                    rows = dfm.to_dict(orient="records")  # type: ignore[attr-defined]
                except Exception:
                    rows = _df_to_records(dfm)
                cache: dict[str, dict[str, Any]] = {}
                cols = list(getattr(dfm, "columns", []))
                # Observed columns (garbled on some consoles): [rank, manager, company, fund_code, fund_name, ...]
                code_col = cols[3] if len(cols) >= 4 else None
                manager_col = cols[1] if len(cols) >= 2 else None
                company_col = cols[2] if len(cols) >= 3 else None
                if code_col and isinstance(rows, list):
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        code = str(r.get(code_col) or "").strip()
                        if not code:
                            continue
                        cache.setdefault(
                            code,
                            {
                                "fund_manager": _json_safe(r.get(manager_col)) if manager_col else None,
                                "management_company": _json_safe(r.get(company_col)) if company_col else None,
                            },
                        )
                _FUND_MANAGER_LOOKUP_CACHE = cache
            info = (_FUND_MANAGER_LOOKUP_CACHE or {}).get(fund_id)
            if info:
                out = dict(out)
                out["fund_manager"] = info.get("fund_manager") or out.get("fund_manager")
                out["management_company"] = info.get("management_company") or out.get("management_company")
                # Mark that we enriched from an additional source.
                api = str(out.get("api") or "")
                if api and "fund_manager_em" not in api:
                    out["api"] = api + "+fund_manager_em"
                elif not api:
                    out["api"] = "fund_manager_em"
                return out
        except Exception:
            # Silent best-effort: do not fail basic ingestion due to enrichment.
            return out
        return out

    def _enrich_from_xq(out: dict) -> dict:
        """Fill null basic fields from fund_individual_basic_info_xq when available."""
        if not callable(fn_xq):
            return out
        empty_fields = {
            "risk_level", "inception_date", "tracking_index", "investment_scope",
            "latest_scale", "description",
        }
        if all(out.get(f) for f in empty_fields):
            return out
        try:
            df = fn_xq(symbol=fund_id)
            recs = _df_to_records(df)
            rec = recs[0] if recs else {}
            if not isinstance(rec, dict) or not rec:
                return out
            out = dict(out)
            xq_map = {
                "risk_level": rec.get("风险等级") or rec.get("risk"),
                "inception_date": rec.get("成立日期") or rec.get("成立时间"),
                "tracking_index": rec.get("跟踪标的") or rec.get("跟踪指数"),
                "investment_scope": rec.get("投资范围"),
                "latest_scale": rec.get("最新规模") or rec.get("规模"),
                "description": rec.get("基金介绍") or rec.get("简介"),
            }
            for k, v in xq_map.items():
                if v is not None and (out.get(k) is None or out.get(k) == ""):
                    cell = _cell_from_raw(v)
                    if cell is not None:
                        out[k] = cell
            api = str(out.get("api") or "")
            if api and "+fund_individual_basic_info_xq" not in api:
                out["api"] = api + "+fund_individual_basic_info_xq"
        except Exception:
            pass
        return out

    def _is_empty(val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, str):
            return val.strip() == ""
        return False

    def _apply_empty_markers(o: dict) -> dict:
        """Set NOT_EXIST for optional basic fields that are still empty."""
        try:
            from data_manager.empty_markers import NOT_EXIST, VALID_MARKERS
        except ImportError:
            VALID_MARKERS = frozenset()
            NOT_EXIST = "not_exist"
        optional = {
            "risk_level", "inception_date", "fund_manager", "management_company",
            "tracking_index", "investment_scope", "latest_scale", "description",
        }
        out = dict(o)
        for f in optional:
            v = out.get(f)
            if _is_empty(v) and (v not in VALID_MARKERS if isinstance(v, str) else True):
                out[f] = NOT_EXIST
        return out

    def _infer_risk_level(fund_type: str | None) -> str | None:
        if not fund_type:
            return None
        t = str(fund_type)
        if "货币型" in t:
            return "低"
        if "债券型" in t:
            return "低-中"
        if "混合型" in t:
            return "中"
        if "指数型-股票" in t or "股票型" in t:
            return "高"
        if "QDII" in t:
            return "高"
        return None

    def _infer_investment_scope(fund_type: str | None) -> str | None:
        if not fund_type:
            return None
        t = str(fund_type)
        # Priority: bond > mix > stock (to handle "债券型-混合..." style types).
        if "债券" in t:
            return "债券为主"
        if "混合" in t:
            return "股债混合"
        if "股票" in t:
            return "股票为主"
        return None

    def _infer_tracking_index(fund_name: str | None, fund_type: str | None) -> str | None:
        # Prefer fund_name keyword extraction; fall back to type only when ETF-like.
        if fund_name:
            n = str(fund_name)
            if "中证" in n:
                # Common pattern: "...中证xxx...指数..." or "...中证xxx...ETF..."
                # Best-effort: extract up to the next "主题"/"指数"/"ETF" if present.
                # Example: "天弘中证工业有色金属主题ETF发起联接C" -> "工业有色金属指数".
                for key in ("创业板人工智能", "沪深300", "中证500"):
                    if key in n:
                        if key == "创业板人工智能":
                            return "创业板人工智能指数"
                        return key
                if "工业有色金属" in n:
                    return "工业有色金属指数"
                if "有色金属" in n:
                    return "有色金属指数"
                if "半导体材料设备" in n:
                    return "半导体材料设备指数"
                if "人工智能" in n:
                    return "人工智能指数"
                if "化工" in n:
                    return "化工指数"
            if "创业板" in n:
                if "人工智能" in n:
                    return "创业板人工智能指数"
                return "创业板"
            if "沪深300" in n:
                return "沪深300"
            if "中证500" in n:
                return "中证500"
            if "工业有色金属" in n:
                return "工业有色金属指数"
            if "有色金属" in n:
                return "有色金属指数"
            if "半导体材料设备" in n:
                return "半导体材料设备指数"
            if "人工智能" in n:
                return "人工智能指数"
            if "化工" in n:
                return "化工指数"
            if "ETF" in n:
                return "未知指数ETF"

        # Optional fallback: if it's clearly an index stock fund but name parsing fails.
        if fund_type and ("指数型" in str(fund_type)) and fund_name and "ETF" in fund_name:
            return "未知指数ETF"
        return None

    def _apply_rule_enrichment(out: dict) -> dict:
        """Fill still-empty basic fields with deterministic rules (best-effort)."""
        if not out:
            return out
        out = dict(out)

        ft = out.get("fund_type")
        fn = out.get("fund_name")

        if _is_empty(out.get("risk_level")):
            inferred = _infer_risk_level(ft)
            if inferred is not None:
                out["risk_level"] = inferred

        if _is_empty(out.get("investment_scope")):
            inferred = _infer_investment_scope(ft)
            if inferred is not None:
                out["investment_scope"] = inferred

        if _is_empty(out.get("tracking_index")):
            inferred = _infer_tracking_index(fn, ft)
            if inferred is not None:
                out["tracking_index"] = inferred

        return out

    def _maybe_enrich_latest_scale_from_scale_change_em(out: dict) -> dict:
        """Optional: fill latest_scale using fund_scale_change_em when available."""
        if not out:
            return out
        if not _is_empty(out.get("latest_scale")):
            return out
        if not hasattr(ak, "fund_scale_change_em"):
            return out
        try:
            df = ak.fund_scale_change_em(symbol=fund_id)  # type: ignore[call-arg]
            recs = _df_to_records(df)
            if not recs:
                return out
            latest = recs[-1] if isinstance(recs, list) else {}
            if not isinstance(latest, dict):
                return out
            for k in (
                "最新规模",
                "规模",
                "基金规模",
                "最新规模(亿元)",
                "最新规模（亿元）",
                "最新规模(万份)",
                "最新规模（万份）",
            ):
                v = latest.get(k)
                if v is not None and v != "":
                    out = dict(out)
                    out["latest_scale"] = _json_safe(v)
                    return out
        except Exception:
            pass
        return out

    def _enrich_from_em_individual(out: dict) -> dict:
        """Fill null basic fields from fund_individual_basic_info_em when available."""
        if not callable(fn_em_individual):
            return out
        empty_fields = {
            "risk_level", "inception_date", "tracking_index", "investment_scope",
            "latest_scale", "description",
        }
        if all(out.get(f) for f in empty_fields):
            return out
        try:
            df = fn_em_individual(symbol=fund_id)
            recs = _df_to_records(df)
            rec = recs[0] if recs else {}
            if not isinstance(rec, dict) or not rec:
                return out
            candidate = _out_from_record(
                rec,
                getattr(fn_em_individual, "__name__", "fund_individual_basic_info_em"),
            )
            out = dict(out)
            for f in empty_fields:
                if _is_empty(out.get(f)) and not _is_empty(candidate.get(f)):
                    out[f] = candidate.get(f)
            api = str(out.get("api") or "")
            if api and "+fund_individual_basic_info_em" not in api:
                out["api"] = api + "+fund_individual_basic_info_em"
        except Exception:
            pass
        return out

    # Primary: fund catalog list (EM). This is broad but stable; filter by code.
    try:
        if hasattr(ak, "fund_name_em"):
            df = ak.fund_name_em()
            # Avoid relying on Chinese column names (console encoding varies); use positional columns:
            # 0: code, 2: name, 3: type (observed). Do not use pandas string ops so this
            # remains robust in environments without full pandas behaviors.
            cols = list(getattr(df, "columns", []))
            code_col = cols[0] if len(cols) >= 1 else None
            name_col = cols[2] if len(cols) >= 3 else None
            type_col = cols[3] if len(cols) >= 4 else None
            if code_col:
                rows = []
                try:
                    rows = df.to_dict(orient="records")  # type: ignore[attr-defined]
                except Exception:
                    rows = _df_to_records(df)
                if isinstance(rows, list):
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        if str(r.get(code_col) or "").strip() != fund_id:
                            continue
                        rec = {
                            "fund_name": (r.get(name_col) if name_col else None),
                            "fund_type": (r.get(type_col) if type_col else None),
                        }
                        base = {
                            "fund_id": fund_id,
                            "fund_name": _json_safe(rec.get("fund_name")),
                            "fund_type": _json_safe(rec.get("fund_type")),
                            "risk_level": None,
                            "inception_date": None,
                            "fund_manager": None,
                            "management_company": None,
                            "tracking_index": None,
                            "investment_scope": None,
                            "latest_scale": None,
                            "description": None,
                            "source": "akshare",
                            "timestamp": _now_iso(),
                            "api": "fund_name_em",
                        }
                        base = _maybe_enrich_manager_fields(base)
                        base = _enrich_from_em_individual(base)
                        base = _enrich_from_xq(base)
                        base = _apply_rule_enrichment(base)
                        base = _maybe_enrich_latest_scale_from_scale_change_em(base)
                        return _apply_empty_markers(base)
    except Exception as e:
        return {"error": str(e), "timestamp": _now_iso()}

    # Secondary: EM individual basic info if available (more fields, version-dependent).
    if callable(fn_em_individual):
        try:
            df = fn_em_individual(symbol=fund_id)
            recs = _df_to_records(df)
            rec = recs[0] if recs else {}
            if isinstance(rec, dict) and rec:
                out = _maybe_enrich_manager_fields(_out_from_record(rec, getattr(fn_em_individual, "__name__", "fund_individual_basic_info_em")))
                out = _apply_rule_enrichment(out)
                out = _maybe_enrich_latest_scale_from_scale_change_em(out)
                if out.get("fund_name") or out.get("fund_type"):
                    return _apply_empty_markers(out)
        except Exception:
            pass

    # Fallback: XQ basic info (often unstable/incomplete).
    if callable(fn_xq):
        try:
            df = fn_xq(symbol=fund_id)
            recs = _df_to_records(df)
            rec = recs[0] if recs else {}
            if isinstance(rec, dict) and rec:
                out = _maybe_enrich_manager_fields(_out_from_record(rec, getattr(fn_xq, "__name__", "fund_individual_basic_info_xq")))
                out = _apply_rule_enrichment(out)
                out = _maybe_enrich_latest_scale_from_scale_change_em(out)
                if out.get("fund_name") or out.get("fund_type"):
                    return _apply_empty_markers(out)
        except Exception:
            pass

    # No data found but not a hard failure.
    out = _maybe_enrich_manager_fields({
        "fund_id": fund_id,
        "fund_name": None,
        "fund_type": None,
        "risk_level": None,
        "inception_date": None,
        "fund_manager": None,
        "management_company": None,
        "tracking_index": None,
        "investment_scope": None,
        "latest_scale": None,
        "description": None,
        "source": "akshare",
        "timestamp": _now_iso(),
        "api": "fallback_empty",
    })
    out = _apply_rule_enrichment(out)
    out = _maybe_enrich_latest_scale_from_scale_change_em(out)
    return _apply_empty_markers(out)


def _is_etf_like(fund_id: str) -> bool:
    """Heuristic: fund_id looks like ETF (Shanghai 51x, Shenzhen 15x/56x/58x)."""
    s = str(fund_id).strip()
    if len(s) < 6:
        return False
    prefix = s[:2]
    return prefix in ("51", "56", "58", "15")


def get_nav(payload: dict) -> dict:
    """Fetch CN fund NAV time series by fund_id.

    For ETF (51x/15x/56x/58x), uses fund_etf_fund_info_em which returns both 单位净值 and 累计净值.
    For open-end funds, uses fund_open_fund_info_em (default indicator may omit 累计净值).

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for metadata only
      - look_back_days (int, optional) ignored in MVP (AKShare returns full series)
      - max_items (int, optional) keep only most recent N items (default: keep all)
      - items_format (str, optional) "rows" (default), "columns", or "triples" ([date, nav, nav_accumulated])

    Returns:
      {"fund_id": "...", "summary": {...}, "items_full_count": int, "items": ..., "items_format": "...", "timestamp": "..."}
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"error": f"AKShare not available: {e}", "timestamp": _now_iso()}

    df = None
    api_used = "fund_open_fund_info_em"
    if _is_etf_like(fund_id) and hasattr(ak, "fund_etf_fund_info_em"):
        try:
            df = ak.fund_etf_fund_info_em(
                fund=fund_id, start_date="20000101", end_date="20991231"
            )
            api_used = "fund_etf_fund_info_em"
        except Exception:
            pass
    if df is None or (hasattr(df, "empty") and df.empty):
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_id)
        except Exception as e:
            return {"error": str(e), "timestamp": _now_iso()}

    recs = _df_to_records(df)
    # If open-end fund has nav but no nav_accumulated, try 累计净值走势 and merge.
    if recs and not any(r.get("累计净值") or r.get("nav_accumulated") for r in recs if isinstance(r, dict)):
        if hasattr(ak, "fund_open_fund_info_em"):
            try:
                df_acc = ak.fund_open_fund_info_em(symbol=fund_id, indicator="累计净值走势")
                acc_recs = _df_to_records(df_acc)
                acc_by_date: dict[str, Any] = {}
                for r in acc_recs:
                    if isinstance(r, dict):
                        d = r.get("净值日期") or r.get("日期") or r.get("date")
                        v = r.get("累计净值")
                        if d and v is not None:
                            acc_by_date[str(d)] = v
                for r in recs:
                    if isinstance(r, dict):
                        d = r.get("净值日期") or r.get("日期") or r.get("date")
                        if d and d in acc_by_date:
                            r["累计净值"] = acc_by_date[d]
                api_used = "fund_open_fund_info_em+累计净值走势"
            except Exception:
                pass

    try:
        items: list[dict] = []
        for r in recs:
            # Common AKShare columns: 净值日期, 单位净值, 累计净值
            items.append(
                {
                    "nav_date": r.get("净值日期") or r.get("日期") or r.get("date"),
                    "nav": r.get("单位净值") or r.get("nav"),
                    "nav_accumulated": r.get("累计净值") or r.get("nav_accumulated"),
                    "source": "akshare",
                }
            )
        # Sort ascending by date when possible (string YYYY-MM-DD works lexicographically).
        items = [it for it in items if isinstance(it, dict) and it.get("nav_date")]
        items.sort(key=lambda x: str(x.get("nav_date")))

        # Limit to last 365 days when look_back_days is set.
        look_back_days = (payload or {}).get("look_back_days")
        if look_back_days is not None:
            try:
                lb = int(look_back_days)
                if lb > 0:
                    anchor = (payload or {}).get("as_of_date") or date.today().isoformat()
                    try:
                        if isinstance(anchor, str):
                            end_dt = datetime.strptime(anchor[:10], "%Y-%m-%d").date()
                        else:
                            end_dt = anchor
                    except Exception:
                        end_dt = date.today()
                    cutoff = end_dt - timedelta(days=lb)
                    items = [
                        it
                        for it in items
                        if (d := _parse_date_safe(it.get("nav_date"))) is not None and d >= cutoff
                    ]
            except (TypeError, ValueError):
                pass

        full_count = len(items)

        def _to_float(v: Any) -> float | None:
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        first = items[0] if items else {}
        last = items[-1] if items else {}
        nav_first = _to_float(first.get("nav"))
        nav_last = _to_float(last.get("nav"))
        summary = {
            "start_date": first.get("nav_date"),
            "end_date": last.get("nav_date"),
            "points": full_count,
            "nav_first": nav_first,
            "nav_last": nav_last,
            "return_total": ((nav_last / nav_first - 1.0) if (nav_first and nav_last) else None),
        }

        max_items = (payload or {}).get("max_items")
        if max_items is not None:
            try:
                n = int(max_items)
                if n > 0 and len(items) > n:
                    items = items[-n:]
            except Exception:
                pass

        items_format = str((payload or {}).get("items_format") or "rows").strip().lower()
        if items_format not in ("rows", "columns", "triples"):
            items_format = "rows"

        if items_format == "columns":
            # Columnar/packed representation to reduce JSON overhead.
            dates: list[str] = []
            navs: list[float | None] = []
            nav_accs: list[float | None] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                dates.append(str(it.get("nav_date")))
                navs.append(_to_float(it.get("nav")))
                nav_accs.append(_to_float(it.get("nav_accumulated")))
            packed = {"nav_date": dates, "nav": navs, "nav_accumulated": nav_accs}
            items_out: Any = _json_safe(packed)
        elif items_format == "triples":
            triples: list[list[Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                triples.append(
                    [
                        str(it.get("nav_date")),
                        _to_float(it.get("nav")),
                        _to_float(it.get("nav_accumulated")),
                    ]
                )
            items_out = _json_safe(triples)
        else:
            items_out = _json_safe(items)

        return {
            "fund_id": fund_id,
            "summary": _json_safe(summary),
            "items_full_count": full_count,
            "items_format": items_format,
            "items": items_out,
            "timestamp": _now_iso(),
            "source": "akshare",
            "api": api_used,
        }
    except Exception as e:
        return {"error": str(e), "timestamp": _now_iso()}


def get_fee(payload: dict) -> dict:
    """Fetch CN fund fee schedule by fund_id.

    Tries multiple indicators (申购费率, 赎回费率, 运作费用) as fund_fee_em requires
    an indicator; aggregates all non-empty results.

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for metadata only
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"error": f"AKShare not available: {e}", "timestamp": _now_iso()}
    if not hasattr(ak, "fund_fee_em"):
        return {"error": "AKShare fund_fee_em not available", "timestamp": _now_iso()}
    indicators = [
        "申购费率（前端）",
        "赎回费率",
        "运作费用",
        "申购费率",
        "认购费率（前端）",
    ]
    all_recs: list[dict] = []
    seen_keys: set[tuple] = set()
    for ind in indicators:
        try:
            df = ak.fund_fee_em(symbol=fund_id, indicator=ind)  # type: ignore[call-arg]
            recs = _df_to_records(df)
            for r in recs:
                if not isinstance(r, dict) or not r:
                    continue
                row_key = tuple(sorted((k, str(v)) for k, v in r.items()))
                if row_key not in seen_keys:
                    seen_keys.add(row_key)
                    r = dict(r)
                    r["_fee_indicator"] = ind
                    all_recs.append(r)
        except Exception:
            continue
    return {"fund_id": fund_id, "items": all_recs, "timestamp": _now_iso(), "source": "akshare"}


def get_holdings(payload: dict) -> dict:
    """Fetch CN fund holdings/portfolio by fund_id.

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for metadata only
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"error": f"AKShare not available: {e}", "timestamp": _now_iso()}
    try:
        # Some AKShare portfolio endpoints return all funds; keep best-effort here.
        df = ak.fund_portfolio_hold_em(symbol=fund_id)  # type: ignore[call-arg]
        recs = _df_to_records(df)
        filtered, err = _filter_items_by_fund_id(recs, fund_id)
        if err:
            return {"error": err, "timestamp": _now_iso()}
        # If not bulk, keep what we got; if bulk we already filtered.
        return {
            "fund_id": fund_id,
            "items": (filtered if len(recs) >= 5000 else recs),
            "timestamp": _now_iso(),
            "source": "akshare",
        }
    except TypeError:
        # Fallback when the endpoint doesn't accept symbol: return error rather than guessing.
        return {"error": "AKShare fund_portfolio_hold_em does not support symbol parameter in this environment", "timestamp": _now_iso()}
    except Exception as e:
        return {"error": str(e), "timestamp": _now_iso()}


def get_announcements(payload: dict) -> dict:
    """Fetch CN fund announcements (dividend, report, personnel, disclosure_cninfo) by fund_id.

    Uses fund_announcement_dividend_em, fund_announcement_report_em,
    fund_announcement_personnel_em (EM), and stock_zh_a_disclosure_report_cninfo
    with market="基金" (巨潮资讯) for broader disclosure coverage.

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for date range; defaults to ~1 year lookback
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"error": f"AKShare not available: {e}", "timestamp": _now_iso()}

    out: dict[str, Any] = {
        "fund_id": fund_id,
        "dividend": {"fund_id": fund_id, "items": [], "timestamp": _now_iso(), "source": "akshare"},
        "report": {"fund_id": fund_id, "items": [], "timestamp": _now_iso(), "source": "akshare"},
        "personnel": {"fund_id": fund_id, "items": [], "timestamp": _now_iso(), "source": "akshare"},
        "disclosure_cninfo": {"fund_id": fund_id, "items": [], "timestamp": _now_iso(), "source": "akshare"},
    }

    # 仅保留近三年公告 (公告日期 或 公告时间)
    cutoff_3y = date.today() - timedelta(days=3 * 365)

    def _within_3y(rec: dict) -> bool:
        d = _parse_date_safe(rec.get("公告日期") or rec.get("公告时间"))
        return d is not None and d >= cutoff_3y

    apis = [
        ("dividend", getattr(ak, "fund_announcement_dividend_em", None)),
        ("report", getattr(ak, "fund_announcement_report_em", None)),
        ("personnel", getattr(ak, "fund_announcement_personnel_em", None)),
    ]
    for key, fn in apis:
        if not callable(fn):
            continue
        try:
            df = fn(symbol=fund_id)  # type: ignore[misc]
            recs = _df_to_records(df)
            if recs:
                out[key]["items"] = [r for r in recs if _within_3y(r)]
        except Exception as e:
            out[key]["error"] = str(e)

    # 巨潮资讯基金披露 (stock_zh_a_disclosure_report_cninfo, market="基金")
    # 部分基金(如164701)可成功; 000001/510010 等可能 KeyError, 捕获后跳过
    # 仅统计近三年公告
    fn_cninfo = getattr(ak, "stock_zh_a_disclosure_report_cninfo", None)
    if callable(fn_cninfo):
        try:
            end_d = date.today()
            start_d = end_d - timedelta(days=3 * 365)
            start_str = start_d.strftime("%Y%m%d")
            end_str = end_d.strftime("%Y%m%d")
            df = fn_cninfo(symbol=fund_id, market="基金", start_date=start_str, end_date=end_str)
            recs = _df_to_records(df)
            if recs:
                out["disclosure_cninfo"]["items"] = recs
        except (KeyError, Exception) as e:
            out["disclosure_cninfo"]["error"] = str(e)

    out["timestamp"] = _now_iso()
    out["source"] = "akshare"
    return out


def get_rank(payload: dict) -> dict:
    """Fetch CN fund rank/labels for a fund_id (best-effort).

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for metadata only
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"error": f"AKShare not available: {e}", "timestamp": _now_iso()}
    # Prefer open fund rank API if available; it returns open-fund ranks.
    if not hasattr(ak, "fund_open_fund_rank_em"):
        return {"error": "AKShare fund_open_fund_rank_em not available", "timestamp": _now_iso()}
    try:
        df = ak.fund_open_fund_rank_em()
        recs = _df_to_records(df)
        filtered, err = _filter_items_by_fund_id(recs, fund_id)
        if err:
            return {"error": err, "timestamp": _now_iso()}
        return {"fund_id": fund_id, "items": filtered, "timestamp": _now_iso(), "source": "akshare"}
    except Exception as e:
        return {"error": str(e), "timestamp": _now_iso()}


def get_all(payload: dict) -> dict:
    """Aggregate CN fund data for offline ingestion in one call.

    This is intended for **offline ingestion** only. It calls multiple upstream
    endpoints and returns a single structured payload that data_manager can
    persist to raw snapshots and then distribute into curated tables.

    Payload:
      - fund_id (str, required)
      - as_of_date (str, optional) for metadata only
      - look_back_days (int, optional) for nav
    """
    fund_id = str((payload or {}).get("fund_id") or "").strip()
    if not fund_id:
        return {"error": "Missing fund_id", "timestamp": _now_iso()}
    as_of_date = str((payload or {}).get("as_of_date") or "").strip()
    look_back_days = (payload or {}).get("look_back_days")
    # Reuse the single-purpose tool functions so behavior stays consistent.
    nav_payload = {"fund_id": fund_id}
    if as_of_date:
        nav_payload["as_of_date"] = as_of_date
    if look_back_days is not None:
        nav_payload["look_back_days"] = look_back_days
    # Default to a compact NAV payload in the aggregate snapshot to keep density high.
    nav_payload["max_items"] = int((payload or {}).get("nav_max_items") or 400)
    # Use a packed format in aggregate snapshots to reduce JSON size.
    nav_payload["items_format"] = str((payload or {}).get("nav_items_format") or "triples")
    base_payload = {"fund_id": fund_id}
    if as_of_date:
        base_payload["as_of_date"] = as_of_date

    basic = get_basic(base_payload)
    nav = get_nav(nav_payload)
    fee = get_fee(base_payload)
    holdings = get_holdings(base_payload)
    rank = get_rank(base_payload)
    announcements = get_announcements(base_payload)

    # If absolutely everything failed, surface a top-level error.
    if all(isinstance(x, dict) and x.get("error") for x in (basic, nav, fee, holdings, rank)):
        return {
            "error": "All AKShare subcalls failed for cn_fund_tool.get_all",
            "timestamp": _now_iso(),
            "fund_id": fund_id,
            "details": {
                "basic": basic.get("error"),
                "nav": nav.get("error"),
                "fee": fee.get("error"),
                "holdings": holdings.get("error"),
                "rank": rank.get("error"),
            },
        }

    return {
        "fund_id": fund_id,
        "as_of_date": as_of_date or None,
        "basic": basic if isinstance(basic, dict) else {},
        "nav": nav if isinstance(nav, dict) else {},
        "fee": fee if isinstance(fee, dict) else {},
        "holdings": holdings if isinstance(holdings, dict) else {},
        "rank": rank if isinstance(rank, dict) else {},
        "announcements": announcements if isinstance(announcements, dict) else {},
        "timestamp": _now_iso(),
        "source": "akshare",
    }

