from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_cn_collector_saves_to_ingestion_layout(tmp_path: Path) -> None:
    from data_manager.collector import DataCollector
    from data_manager.tasks import get_task_by_type

    class StubMCP:
        def call_tool(self, tool_name: str, payload: dict) -> dict:
            if tool_name == "cn_fund_tool.get_basic":
                return {
                    "content": {
                        "fund_name": "测试基金",
                        "fund_type": "混合型",
                        "risk_level": "中风险",
                        "source": "akshare",
                    }
                }
            raise AssertionError(f"unexpected tool: {tool_name}")

    c = DataCollector(data_dir=str(tmp_path / "datasets" / "raw"), mcp_client=StubMCP())
    task = get_task_by_type("cn_fund_basic")
    assert task is not None

    ok, filepath, err = c.collect_task("000001", task, "2026-03-18")
    assert ok and err is None
    assert filepath is not None
    assert Path(filepath).as_posix().endswith("/datasets/raw/ingestion/cn_fund_basic/2026-03-18/000001.json")

    data = json.loads(Path(filepath).read_text(encoding="utf-8"))
    assert data["metadata"]["symbol"] == "000001"
    assert data["metadata"]["task_type"] == "cn_fund_basic"

def test_cn_collector_persists_dict_when_no_content_wrapper(tmp_path: Path) -> None:
    from data_manager.collector import DataCollector
    from data_manager.tasks import get_task_by_type

    class StubMCP:
        def call_tool(self, tool_name: str, payload: dict) -> dict:
            if tool_name == "cn_fund_tool.get_all":
                return {"fund_id": payload.get("fund_id"), "basic": {"fund_name": "X"}, "timestamp": "t"}
            raise AssertionError(f"unexpected tool: {tool_name}")

    c = DataCollector(data_dir=str(tmp_path / "datasets" / "raw"), mcp_client=StubMCP())
    task = get_task_by_type("cn_fund_all")
    assert task is not None

    ok, filepath, err = c.collect_task("000001", task, "2026-03-18")
    assert ok and err is None
    saved = json.loads(Path(filepath).read_text(encoding="utf-8"))
    assert isinstance(saved["content"], dict)
    assert saved["content"]["basic"]["fund_name"] == "X"


def test_cn_collector_csv_output_when_format_csv(tmp_path: Path) -> None:
    from data_manager.collector import DataCollector
    from data_manager.tasks import get_task_by_type

    content = {
        "fund_id": "510010",
        "basic": {
            "fund_id": "510010",
            "fund_name": "测试ETF",
            "fund_type": "指数型-股票",
            "source": "akshare",
        },
        "nav": {
            "fund_id": "510010",
            "items_format": "triples",
            "items": [["2026-03-17", 1.5, None], ["2026-03-18", 1.52, None]],
        },
        "holdings": {
            "fund_id": "510010",
            "items": [
                {"股票代码": "600000", "股票名称": "浦发银行", "占净值比例": 0.05},
            ],
        },
    }

    class StubMCP:
        def call_tool(self, tool_name: str, payload: dict) -> dict:
            if tool_name == "cn_fund_tool.get_all":
                return content
            raise AssertionError(f"unexpected tool: {tool_name}")

    c = DataCollector(data_dir=str(tmp_path / "datasets" / "raw"), mcp_client=StubMCP())
    task = get_task_by_type("cn_fund_all")
    assert task is not None

    ok, filepath, err = c.collect_task("510010", task, "2026-03-18", output_format="csv")
    assert ok and err is None

    dir_path = Path(filepath).parent
    # cn_fund_all 的 CSV 统一落盘为 data.csv（同目录下的 data.json 旁）
    csv_path = dir_path / "data.csv"
    assert csv_path.exists()

    raw = csv_path.read_text(encoding="utf-8-sig")
    assert "基金代码: 510010" in raw
    assert "基础信息 (BASIC)" in raw
    assert "净值 (NAV)" in raw
    assert "持仓 (HOLDINGS)" in raw
    assert "测试ETF" in raw
    assert "2026-03-17" in raw
    assert "1.5" in raw
    assert "浦发银行" in raw


def test_cn_transformer_basic_and_nav_rows() -> None:
    from data_manager.transformer import DataTransformer

    t = DataTransformer(collected_at="2026-03-18T00:00:00Z")

    table, rows = t.to_postgres_rows(
        "cn_fund_basic",
        "000001",
        {"fund_name": "测试基金", "latest_scale": "123.4", "source": "akshare"},
        "2026-03-18",
    )
    assert table == "cn_fund_basic"
    assert len(rows) == 1
    assert rows[0]["fund_id"] == "000001"
    assert rows[0]["as_of_date"] == "2026-03-18"
    assert rows[0]["latest_scale"] == pytest.approx(123.4)

    nav_content = [
        {"nav_date": "2026-03-17", "nav": 1.23, "nav_accumulated": 2.34, "source": "akshare"},
        {"nav_date": "2026-03-18", "nav": "1.25", "nav_accumulated": None, "source": "akshare"},
    ]
    table, rows = t.to_postgres_rows("cn_fund_nav", "000001", nav_content, "2026-03-18")
    assert table == "cn_fund_nav"
    assert len(rows) == 2
    assert rows[0]["fund_id"] == "000001"
    assert rows[0]["nav_date"] == "2026-03-17"


def test_cn_fund_tool_filter_refuses_bulk_without_fund_id_key() -> None:
    from openfund_mcp.tools.cn_fund_tool import _filter_items_by_fund_id

    items = [{"x": i} for i in range(6000)]
    filtered, err = _filter_items_by_fund_id(items, "510010")
    assert filtered == []
    assert err is not None


def test_cn_fund_tool_filter_keeps_only_one_fund() -> None:
    from openfund_mcp.tools.cn_fund_tool import _filter_items_by_fund_id

    items = [
        {"基金代码": "510010", "rank": 1},
        {"基金代码": "000001", "rank": 2},
        {"基金代码": "510010", "rank": 3},
    ]
    filtered, err = _filter_items_by_fund_id(items, "510010")
    assert err is None
    assert [x["rank"] for x in filtered] == [1, 3]


def test_cn_fund_basic_falls_back_when_xq_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate: XQ returns a record but without name/type; should fall back to fund_name_em.
    import types

    from openfund_mcp.tools import cn_fund_tool

    class DF:
        def __init__(self, recs: list[dict]):
            self._recs = recs
            self.columns = ["code", "abbr", "name", "type", "pinyin"]

        def to_dict(self, orient: str = "records"):
            return list(self._recs)

    fake_ak = types.SimpleNamespace()
    fake_ak.fund_individual_basic_info_xq = lambda symbol: DF([{"x": 1}])  # no name/type fields
    fake_ak.fund_name_em = lambda: DF([{"code": "004433", "abbr": "", "name": "基金A", "type": "混合型", "pinyin": ""}])

    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    out = cn_fund_tool.get_basic({"fund_id": "004433"})
    assert out.get("fund_name") is not None or out.get("fund_type") is not None


def test_cn_fund_basic_enriches_manager_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    import types
    from openfund_mcp.tools import cn_fund_tool

    class DF:
        def __init__(self, recs: list[dict], columns: list[str]):
            self._recs = recs
            self.columns = columns

        def to_dict(self, orient: str = "records"):
            return list(self._recs)

    # fund_name_em returns name/type, fund_manager_em returns manager/company mapping.
    fake_ak = types.SimpleNamespace()
    fake_ak.fund_individual_basic_info_xq = lambda symbol: DF([{"x": 1}], ["x"])  # incomplete -> fallback
    fake_ak.fund_name_em = lambda: DF([{"code": "004433", "abbr": "", "name": "基金A", "type": "混合型", "pinyin": ""}], ["code", "abbr", "name", "type", "pinyin"])
    fake_ak.fund_manager_em = lambda: DF(
        [
            {"rank": 1, "manager": "张三", "company": "华夏基金", "code": "004433", "fund_name": "基金A"},
        ],
        ["rank", "manager", "company", "code", "fund_name"],
    )

    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)
    # Reset module cache for this test
    cn_fund_tool._FUND_MANAGER_LOOKUP_CACHE = None

    out = cn_fund_tool.get_basic({"fund_id": "004433"})
    assert out.get("fund_manager") == "张三"
    assert out.get("management_company") == "华夏基金"


def test_cn_fund_basic_rule_infers_risk_and_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """When EM/XQ basic fields are missing, deterministic rules should fill them."""
    import types

    from openfund_mcp.tools import cn_fund_tool

    class DF:
        def __init__(self, recs: list[dict], columns: list[str]):
            self._recs = recs
            self.columns = columns

        def to_dict(self, orient: str = "records"):
            return list(self._recs)

    fake_ak = types.SimpleNamespace()
    fake_ak.fund_name_em = lambda: DF(
        [
            {"code": "001235", "abbr": "", "name": "中银国有企业债A", "type": "债券型-混合一级", "pinyin": ""},
        ],
        ["code", "abbr", "name", "type", "pinyin"],
    )

    # Ensure we don't accidentally reuse cache.
    cn_fund_tool._FUND_MANAGER_LOOKUP_CACHE = None
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    out = cn_fund_tool.get_basic({"fund_id": "001235"})
    assert out.get("risk_level") == "低-中"
    assert out.get("investment_scope") == "债券为主"


def test_cn_fund_basic_rule_infers_tracking_index(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from openfund_mcp.tools import cn_fund_tool

    class DF:
        def __init__(self, recs: list[dict], columns: list[str]):
            self._recs = recs
            self.columns = columns

        def to_dict(self, orient: str = "records"):
            return list(self._recs)

    fake_ak = types.SimpleNamespace()
    fake_ak.fund_name_em = lambda: DF(
        [
            {"code": "004433", "abbr": "", "name": "南方有色金属ETF联接C", "type": "指数型-股票", "pinyin": ""},
        ],
        ["code", "abbr", "name", "type", "pinyin"],
    )

    cn_fund_tool._FUND_MANAGER_LOOKUP_CACHE = None
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)

    out = cn_fund_tool.get_basic({"fund_id": "004433"})
    assert out.get("tracking_index") == "有色金属指数"
    assert out.get("risk_level") == "高"


def test_cn_distributor_writes_postgres(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from data_manager.distributor import DataDistributor

    # Pretend we have Postgres configured.
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/db")

    calls: list[tuple[str, dict | None]] = []

    def fake_run_query(query: str, params: dict | None = None) -> dict:
        calls.append((query, params))
        return {"rows": [], "schema": [], "params": params or {}}

    # Patch the sql_tool used by DataDistributor.
    import data_manager.distributor as dist_mod

    monkeypatch.setattr(dist_mod.sql_tool, "run_query", fake_run_query)

    # Create a fake collected CN basic file.
    raw_dir = tmp_path / "datasets" / "raw" / "ingestion" / "cn_fund_basic" / "2026-03-18"
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "000001.json"
    f.write_text(
        json.dumps(
            {
                "metadata": {
                    "symbol": "000001",
                    "task_type": "cn_fund_basic",
                    "as_of_date": "2026-03-18",
                    "collected_at": "2026-03-18T00:00:00Z",
                    "source": "cn_fund_tool.get_basic",
                },
                "content": {"fund_name": "测试基金", "source": "akshare"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    d = DataDistributor(
        data_dir=str(tmp_path / "datasets" / "raw"),
        processed_dir=str(tmp_path / "datasets" / "processed"),
        failed_dir=str(tmp_path / "datasets" / "failed"),
    )
    r = d.distribute_file(str(f), move_after=False)
    assert r is not None
    assert r.success is True

    # First call should be schema init (DDL), then upsert.
    assert any("CREATE TABLE IF NOT EXISTS cn_fund_basic" in q for q, _ in calls)
    assert any("INSERT INTO cn_fund_basic" in q for q, _ in calls)


def test_cn_distributor_splits_cn_fund_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from data_manager.distributor import DataDistributor

    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/db")

    calls: list[tuple[str, dict | None]] = []

    def fake_run_query(query: str, params: dict | None = None) -> dict:
        calls.append((query, params))
        return {"rows": [], "schema": [], "params": params or {}}

    import data_manager.distributor as dist_mod

    monkeypatch.setattr(dist_mod.sql_tool, "run_query", fake_run_query)

    raw_dir = tmp_path / "datasets" / "raw" / "ingestion" / "cn_fund_all" / "2026-03-18"
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "000001.json"
    f.write_text(
        json.dumps(
            {
                "metadata": {
                    "symbol": "000001",
                    "task_type": "cn_fund_all",
                    "as_of_date": "2026-03-18",
                    "collected_at": "2026-03-18T00:00:00Z",
                    "source": "cn_fund_tool.get_all",
                },
                "content": {
                    "fund_id": "000001",
                    "basic": {"fund_name": "测试基金", "source": "akshare"},
                    "nav": {
                        "summary": {"points": 1},
                        "items_full_count": 1,
                        "items_format": "triples",
                        "items": [["2026-03-18", 1.0, None]],
                    },
                    "fee": {"items": []},
                    "holdings": {"items": []},
                    "rank": {"items": []},
                    "timestamp": "2026-03-18T00:00:00Z",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    d = DataDistributor(
        data_dir=str(tmp_path / "datasets" / "raw"),
        processed_dir=str(tmp_path / "datasets" / "processed"),
        failed_dir=str(tmp_path / "datasets" / "failed"),
    )
    r = d.distribute_file(str(f), move_after=False)
    assert r.success is True
    assert any("INSERT INTO cn_fund_basic" in q for q, _ in calls)
    assert any("INSERT INTO cn_fund_nav" in q for q, _ in calls)

