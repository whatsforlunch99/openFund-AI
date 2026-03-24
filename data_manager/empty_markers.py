"""Empty-value markers for data ingestion and consolidation.

When a CSV cell would be blank, we fill it with one of these markers to indicate why:

| Marker       | Meaning   |
|--------------|-----------|
| not_exist    | 数据不存在  Data does not exist in source |
| not_disclosed| 未披露     Not disclosed by issuer      |
| parse_failed | 解析失败   Parse/validation failed      |
| api_missing  | 接口缺失   API unavailable or failed    |
"""

NOT_EXIST = "not_exist"
NOT_DISCLOSED = "not_disclosed"
PARSE_FAILED = "parse_failed"
API_MISSING = "api_missing"

VALID_MARKERS = frozenset({NOT_EXIST, NOT_DISCLOSED, PARSE_FAILED, API_MISSING})

# Raw values from upstream that indicate "not disclosed"
NOT_DISCLOSED_RAW = frozenset({"未披露", "暂无", "无", "-", "---", "—", "--", "—"})


def _is_empty(val: object) -> bool:
    if val is None:
        return True
    s = str(val).strip()
    return s == ""


def is_not_disclosed_raw(val: object) -> bool:
    """Return True if raw value indicates 'not disclosed'."""
    if val is None:
        return False
    s = str(val).strip()
    return s in NOT_DISCLOSED_RAW or s.lower() in {"na", "n/a", "null"}


def to_cell(val: object, default_marker: str = NOT_EXIST) -> str:
    """Convert value for CSV cell. Use marker when empty; preserve valid markers."""
    if val is None:
        return default_marker
    s = str(val).strip().replace("\n", " ").replace("\r", " ")
    if not s:
        return default_marker
    if s in VALID_MARKERS:
        return s
    return s
