"""FX-50 批次修复测试：体例质检通过率趋势（读面 pass_rate_trend ＋ 质检段趋势图）。

对应任务「让通过率历史一眼可读」（编者核心诉求）——在 FX-26 质检段历史小表
之前加趋势块，三件事：

  * 趋势读面（真库沙箱）—— src/style_check.pass_rate_trend(category,
    limit=20)：3 runs 构造 rate 序列断言 run_id 升序与值；分母 0
    （passed+failed=0）→ rate=None（「还没有可比项」≠ 0%）；limit 截取与
    跨范畴过滤；库不可用 → None（R4 归因）。读面与 list_recent_runs 共用
    私有 _query_runs 查询内核（单一 SQL 事实源，不复制查询文本）——本文件
    同时钉住重构后 list_recent_runs 契约不变（id 降序、slim 模式不带
    detail_json、items 键恒在）。
  * 质检段图表（全桩不触库）—— dict_admin_pages._render_style_check_trend：
    trend=None → R4 归因灰注；<2 次 → caption 占位「≥2 次质检后显示趋势」；
    ≥2 次 → st.altair_chart（批次 29；pandas DataFrame：index=created_at、
    列=通过率，分母 0 的 run 落 NaN 线上留空，y 轴钉 0~1）＋ 标题 caption
    「通过率趋势（最近 N 次）」；Streamlit 原生 Altair 渲染，不引 plotly。
  * AppTest 冒烟（真 Streamlit 渲染链）—— runs≥2 趋势图渲染不炸页；不足
    占位 caption 在场。

外部依赖隔离：UI 用例全部打桩（st 假体＋读面桩，不触库）；读面用例跑独立
沙箱库。沙箱库复用 web_word_fx25_test（scripts/grant_local_mysql.sql 清单
未含 fx50 专名、本机无全局 CREATE 权限；同引擎域共用 —— pytest 串行执行、
fixture 前后 DROP 重建，与 test_fx25_fixes 互不污染，test_fx25 同口径）。
"""

import inspect
import os
import sys

import pymysql
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.mysql_db as db  # noqa: E402
import src.dict_admin_pages as dp  # noqa: E402
from src import style_check as sc  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    FX50_STYLE_CHECK_TREND,
    _render_style_check_section,
    _render_style_check_trend,
)
from streamlit.testing.v1 import AppTest  # noqa: E402

# 沙箱库复用 FX-25 授权库（grant 清单未含 fx50 专名；见模块 docstring）。
TEST_DB = "web_word_fx25_test"

_ME_ADMIN = {"id": 7, "username": "fx50da", "display_name": "主编",
             "role": "viewer", "roles": ["dict_admin"], "active": True}


def _mysql_reachable() -> bool:
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001 —— 本地/CI 无 MySQL 时跳过沙箱段
        return False


HAS_MYSQL = _mysql_reachable()


def _seed_run(category: str = "motion", passed: int = 1, failed: int = 1,
              warned: int = 0, run_by=None) -> int:
    """直连种一行 run（绕过引擎写路径——rate 序列由计数精确控制）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO style_check_runs "
            "(category, run_by, passed, failed, warned, total, detail_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, NULL)",
            (category, run_by, passed, failed, warned,
             passed + failed + warned),
        )
        return int(cursor.lastrowid)


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-50 沙箱测试")
class _Fx50Sandbox:
    """沙箱共用件（建空测试库＋style_check_runs，测试结束 DROP；口径同
    test_fx25_fixes._SandboxCase.fx25_db）。"""

    @pytest.fixture
    def fx50_db(self, monkeypatch):
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
        )
        cur = conn.cursor()
        try:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            cur.execute(
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
                f"COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX-50 沙箱测试: {e}")
        conn.close()
        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        sc.ensure_style_check_table()   # 空表=「无 run 记录」态
        yield
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()


# ============================================
# 趋势读面：真库沙箱
# ============================================
@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-50 沙箱测试")
class TestPassRateTrendSandbox(_Fx50Sandbox):
    """pass_rate_trend 沙箱：顺序/值/口径/降级 ＋ _query_runs 重构回归锚。"""

    def test_three_runs_ascending_rates(self, fx50_db):
        """3 runs：run_id 升序返回（图表 x 轴时间序）、rate 序列与值正确，
        行键恰为契约五键 {run_id, created_at, rate, passed, failed}。"""
        id1 = _seed_run(passed=1, failed=1)      # rate 0.5
        id2 = _seed_run(passed=2, failed=2)      # rate 0.5
        id3 = _seed_run(passed=3, failed=1)      # rate 0.75
        trend = sc.pass_rate_trend("motion")
        assert trend is not None
        assert [row["run_id"] for row in trend] == [id1, id2, id3]
        assert [row["rate"] for row in trend] == [0.5, 0.5, 0.75]
        for row, (p, f) in zip(trend, [(1, 1), (2, 2), (3, 1)]):
            assert set(row) == {"run_id", "created_at", "rate",
                                "passed", "failed"}
            assert row["passed"] == p and row["failed"] == f
            assert row["created_at"] is not None

    def test_denominator_zero_rate_is_none(self, fx50_db):
        """分母 0（passed+failed=0，warn 单列不入分母）→ rate=None；全过 → 1.0。"""
        _seed_run(passed=0, failed=0, warned=5)
        id_ok = _seed_run(passed=4, failed=0)
        trend = sc.pass_rate_trend("motion", limit=10)
        assert [row["rate"] for row in trend] == [None, 1.0]
        assert trend[0]["passed"] == 0 and trend[0]["failed"] == 0
        assert set(trend[0]) == {"run_id", "created_at", "rate",
                                 "passed", "failed"}   # warned 契约外不回传
        assert trend[1]["run_id"] == id_ok and trend[1]["rate"] == 1.0

    def test_limit_window_and_cross_category(self, fx50_db):
        """limit 取最近 N 次且窗口内升序；category 过滤；limit=0 封顶按 1。"""
        id1 = _seed_run(passed=1, failed=1)
        id2 = _seed_run(passed=2, failed=0)
        id3 = _seed_run(passed=0, failed=3)
        id4 = _seed_run(category="speech", passed=5, failed=0)
        trend = sc.pass_rate_trend("motion", limit=2)
        assert [row["run_id"] for row in trend] == [id2, id3]
        assert [row["rate"] for row in trend] == [1.0, 0.0]
        all_rows = sc.pass_rate_trend()      # category=None → 跨范畴
        assert [row["run_id"] for row in all_rows] == [id1, id2, id3, id4]
        one = sc.pass_rate_trend("motion", limit=0)   # 非正数按 1（内核封顶）
        assert [row["run_id"] for row in one] == [id3]

    def test_db_offline_returns_none_and_recent_runs_regression(
            self, fx50_db, monkeypatch):
        """库不可用 → pass_rate_trend / list_recent_runs 同为 None（共用
        _query_runs 内核同一降级路径；R4 归因口径）。"""

        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(sc, "get_db_cursor", _boom)
        assert sc.pass_rate_trend("motion") is None
        assert sc.pass_rate_trend() is None
        assert sc.list_recent_runs("motion", limit=5) is None

    def test_recent_runs_contract_unchanged_after_refactor(self, fx50_db):
        """回归锚：抽 _query_runs 后 list_recent_runs 契约不变——id 降序、
        slim 模式不带 detail_json 原文、items 键恒在（RV16-1 瘦身口径）。"""
        id1 = _seed_run(passed=1, failed=1)
        id2 = _seed_run(passed=2, failed=0)
        slim = sc.list_recent_runs("motion", limit=5, include_detail=False)
        assert [r["id"] for r in slim] == [id2, id1]
        assert "detail_json" not in slim[0]
        assert "items" in slim[0] and slim[0]["items"] is None
        full = sc.list_recent_runs("motion", limit=5, include_detail=True)
        assert "detail_json" in full[0] and full[0]["items"] is None


# ============================================
# 质检段趋势块：全桩渲染（st 假体＋读面桩，不触库）
# ============================================

class _StubCol:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubSt:
    """st 假体（质检段所需最小面＋line_chart 记录器）。

    line_chart 调用单独记入 charts（(data, kwargs)），不混入 messages ——
    DataFrame 不是 str，混入会让 joined() 的 "\\n".join 炸类型。
    """

    def __init__(self, submit=False):
        self.submit = submit
        self.messages = []       # (kind, text)
        self.selectboxes = []    # (label, options)
        self.buttons = []        # (label, kwargs)
        self.charts = []         # line_chart (data, kwargs)

    def form(self, *args, **kwargs):
        return _StubCol()

    def columns(self, spec, **kwargs):
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_StubCol() for _ in range(n)]

    def selectbox(self, *args, **kwargs):
        opts = kwargs.get("options") or (args[1] if len(args) > 1 else [])
        self.selectboxes.append((args[0] if args else "", opts))
        return opts[0] if opts else None

    def button(self, *args, **kwargs):
        self.buttons.append((args[0] if args else "", kwargs))
        return self.submit

    def markdown(self, *args, **kwargs):
        self.messages.append(("markdown", args[0] if args else ""))

    def caption(self, *args, **kwargs):
        self.messages.append(("caption", args[0] if args else ""))

    def info(self, *args, **kwargs):
        self.messages.append(("info", args[0] if args else ""))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args[0] if args else ""))

    def success(self, *args, **kwargs):
        self.messages.append(("success", args[0] if args else ""))

    def error(self, *args, **kwargs):
        self.messages.append(("error", args[0] if args else ""))

    def rerun(self):
        self.messages.append(("rerun", ""))

    def line_chart(self, *args, **kwargs):
        self.charts.append((args[0] if args else None, kwargs))

    def altair_chart(self, *args, **kwargs):
        # 批次 29：趋势图改 altair_chart（y 轴钉 0~1）——记录面同 line_chart
        self.charts.append((args[0] if args else None, kwargs))

    def texts(self, kind=None):
        return [t for k, t in self.messages if kind is None or k == kind]

    def joined(self):
        return "\n".join(self.texts())


_FAKE_ITEMS = [{"code": "CFG_COMPLETE", "rule": "六件套键齐备",
                "status": "pass", "detail": "六件套键齐备"}]


def _one_run_row(run_id=2, passed=3, failed=1, warned=1):
    """最近 run 假行（形态与 list_recent_runs 行对齐；items 可解析）。"""
    return {"id": run_id, "category": "motion", "run_by": None,
            "passed": passed, "failed": failed, "warned": warned,
            "total": passed + failed + warned,
            "created_at": "2026-11-09 10:00:00",
            "items": [dict(it) for it in _FAKE_ITEMS]}


def _trend_rows(rates, start_id=1):
    """趋势假行（run_id 升序、created_at 逐日递增；rate → 计数映射）。"""
    counts = {0.0: (0, 4), 0.5: (1, 1), 0.75: (3, 1), 1.0: (4, 0),
              None: (0, 0)}
    rows = []
    for i, rate in enumerate(rates):
        p, f = counts.get(rate, (1, 1))
        rows.append({
            "run_id": start_id + i,
            "created_at": f"2026-11-{9 + i:02d} 10:00:00",
            "rate": rate, "passed": p, "failed": f,
        })
    return rows


def _patch_section_world(monkeypatch, stub, runs, trend):
    """铺质检段渲染假体：st/当前用户/花名册/两读面（runs 与 trend 独立可配）。

    RV24-1：list_recent_runs 桩按 include_detail 回双形态——False（历史小表
    瘦身面）行剥去 items/detail_json 键，True（最近一次 run 全量面）行带
    items（与真引擎两面形态对齐）。
    """

    def _fake_list_recent_runs(category=None, limit=5, include_detail=True):
        if not include_detail:
            return [{k: v for k, v in row.items()
                     if k not in ("items", "detail_json")} for row in runs]
        return runs

    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [])
    monkeypatch.setattr(dp.style_check, "list_recent_runs",
                        _fake_list_recent_runs)
    monkeypatch.setattr(dp.style_check, "pass_rate_trend",
                        lambda category=None, limit=20: trend)
    return stub


def test_section_trend_chart_and_placement(monkeypatch):
    """runs≥2 → st.altair_chart 在场且位于历史小表之前：DataFrame
    （index=created_at 时间序、列=通过率、分母 0 落 NaN 留空）＋标题
    caption 注明 N 与留空口径。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=[_one_run_row()],
                         trend=_trend_rows([0.5, None, 0.75]))
    _render_style_check_section()
    assert len(stub.charts) == 1
    # 批次 29：趋势图改 altair_chart（y 轴钉 0~1）——从 chart spec 断言
    chart = stub.charts[0][0]
    spec = chart.to_dict()
    enc = spec["encoding"]
    assert enc["x"]["field"] == "created_at" and enc["x"]["type"] == "temporal"
    y = enc["y"]
    assert y["field"] == "通过率" and y["type"] == "quantitative"
    assert y["scale"]["domain"] == [0, 1]           # y 轴钉 0~1（监工裁决落地）
    captions = stub.texts("caption")
    assert any("通过率趋势（最近 3 次）" in c and "线上留空" in c
               for c in captions)
    # 摆位契约：趋势标题 caption 在历史小表（>#2< 行）之前
    msgs = stub.messages
    idx_title = next(i for i, (k, t) in enumerate(msgs)
                     if k == "caption" and "通过率趋势" in t)
    idx_hist = next(i for i, (k, t) in enumerate(msgs)
                    if k == "markdown" and ">#2<" in t)
    assert idx_title < idx_hist


def test_section_trend_placeholder_below_two_runs(monkeypatch):
    """runs<2 → 不渲染图表，caption 占位「≥2 次质检后显示趋势」。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=[_one_run_row()],
                         trend=_trend_rows([0.75]))
    _render_style_check_section()
    assert stub.charts == []
    assert any("≥2 次质检后显示趋势" in c for c in stub.texts("caption"))
    assert not any("通过率趋势（最近" in c for c in stub.texts("caption"))


def test_section_trend_unavailable_gray_note(monkeypatch):
    """trend=None（表未建/库断连）→ R4 归因灰注；图表与占位都不出。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=[_one_run_row()], trend=None)
    _render_style_check_section()
    assert stub.charts == []
    assert any(k == "warning" and "通过率趋势数据不可用" in t and "R4" in t
               for k, t in stub.messages)
    assert not any("≥2 次质检后显示趋势" in c for c in stub.texts("caption"))


def test_section_trend_no_gap_note_when_rates_complete(monkeypatch):
    """全部 run 分母非 0 → 标题 caption 不带留空注记（如实、不添噪）。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=[_one_run_row()],
                         trend=_trend_rows([0.5, 1.0]))
    _render_style_check_trend("motion")
    assert len(stub.charts) == 1
    captions = stub.texts("caption")
    assert any("通过率趋势（最近 2 次）" in c for c in captions)
    assert not any("线上留空" in c for c in captions)


def test_trend_limit_constant_matches_read_face_default():
    """趋势条数常量=20，且与读面 pass_rate_trend 默认 limit 同口径。"""
    assert FX50_STYLE_CHECK_TREND == 20
    assert inspect.signature(sc.pass_rate_trend).parameters["limit"].default \
        == FX50_STYLE_CHECK_TREND


def test_trend_chart_is_streamlit_native_no_plotly():
    """不引 plotly：趋势块用 st.altair_chart（Streamlit 原生 Altair 渲染）。

    RV24-11：实现钉板——断言落在代码体（st.altair_chart 在码、st.line_chart
    不在码），不再用 docstring 子串钉板，docstring 漂移骗不过哨兵。
    """
    src = inspect.getsource(_render_style_check_trend)
    body = src.split('"""', 2)[-1]   # 只查代码体（docstring 文案不参与钉板）
    assert "st.altair_chart" in body   # 批次 29：altair 折线（y 轴钉 0~1）
    assert "st.line_chart" not in body
    assert "plotly" not in body.lower()
    assert "import plotly" not in inspect.getsource(dp)


# ============================================
# AppTest 冒烟：真 Streamlit 渲染链（图表在场 / 不足占位）
# ============================================

_SMOKE_SCRIPT = (
    "from src import ui_kit\n"
    "from src.dict_admin_pages import _render_style_check_section\n"
    "ui_kit.pop_and_render_flash()\n"     # 与 app.main() 每轮渲染开头同序
    "_render_style_check_section()\n"
)


def test_apptest_smoke_trend_chart_renders(monkeypatch):
    """AppTest 冒烟（runs≥2）：真 st.altair_chart 渲染链跑通，not at exception，
    标题 caption 在场（读面与花名册打桩，不触真库；RV24-1 双形态桩）。"""

    def _fake_list_recent_runs(category=None, limit=5, include_detail=True):
        if not include_detail:
            return [{k: v for k, v in _one_run_row().items()
                     if k not in ("items", "detail_json")}]
        return [_one_run_row()]

    monkeypatch.setattr(dp.style_check, "list_recent_runs",
                        _fake_list_recent_runs)
    monkeypatch.setattr(dp.style_check, "pass_rate_trend",
                        lambda category=None, limit=20:
                        _trend_rows([0.5, 0.75, 1.0]))
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [])
    at = AppTest.from_string(_SMOKE_SCRIPT, default_timeout=60)
    at.session_state["user"] = dict(_ME_ADMIN)
    at.run()
    assert not at.exception
    assert any("通过率趋势（最近 3 次）" in str(c.value) for c in at.caption)


def test_apptest_smoke_trend_placeholder(monkeypatch):
    """AppTest 冒烟（runs<2）：占位 caption「≥2 次质检后显示趋势」在场，
    not at exception（RV24-1 双形态桩）。"""

    def _fake_list_recent_runs(category=None, limit=5, include_detail=True):
        if not include_detail:
            return [{k: v for k, v in _one_run_row().items()
                     if k not in ("items", "detail_json")}]
        return [_one_run_row()]

    monkeypatch.setattr(dp.style_check, "list_recent_runs",
                        _fake_list_recent_runs)
    monkeypatch.setattr(dp.style_check, "pass_rate_trend",
                        lambda category=None, limit=20: _trend_rows([0.75]))
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [])
    at = AppTest.from_string(_SMOKE_SCRIPT, default_timeout=60)
    at.session_state["user"] = dict(_ME_ADMIN)
    at.run()
    assert not at.exception
    assert any("≥2 次质检后显示趋势" in str(c.value) for c in at.caption)
