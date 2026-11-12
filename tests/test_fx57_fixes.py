"""FX-57 批次修复验证：RV24-1 / RV24-3 / RV24-11 / RV25-6 消缺。

口径（与被修面 docstring 同步）：

  * RV24-1 质检逐项明细表死路（P2）：dict_admin_pages 质检段此前以
    include_detail=False 读 list_recent_runs 却渲染「最近一次 run 逐项
    明细」——瘦身行无 items，三色徽章表自批次 20 起永不显示，灰注还误归因
    「detail_json 非法」＋误导「重跑即好」。修复后最近一次 run 单独全量读
    （limit=1、include_detail=True），历史小表保持瘦身（False）。双形态桩
    （False→行无 items 键；True→行带 items）钉三件事：全量读调用形态、
    全量面有明细 → 徽章表真渲染、全量读失败 → R4 灰注瘦身面降级（不冒充
    解析失败；真解析失败的如实灰注由 test_fx26 反钉钉住）。
  * RV24-3 TTL 缓存族语义统一：失败 pop 即降级（R4 归因即时可见优先；
    取舍=TTL 窗口内仍回陈旧成功值，两处 docstring 注明）——
    _fx24_annotation_progress_cached 失败（None）清 scope 条目（与
    _style_check_user_names 同口径）；_style_check_user_names 成功路径
    缓存写移出 for 循环体尾（每次取数恰写一次），失败 pop 口径不变。
  * RV24-11 docstring 漂移钉真：_render_style_check_section 不再写「form
    提交型控件」（RV21-1 已改表外下拉＋裸 button）；趋势 docstring 与实现
    同为 st.altair_chart（批次 29）。
  * RV25-6 st.success＋st.rerun 回潮收口（RV12-2 漏网，批次 9 老码）：导入
    回滚成功提示改 ui_kit.flash（提示进会话队列，rerun 不丢）＋会话暂存键
    pop＋st.rerun；st.success 禁止回潮（源级＋行为级双钉）。

本文件不连数据库（全部 monkeypatch 假体驱动；get_pref 断库 fail-closed）。
"""
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402
import streamlit as st  # noqa: E402

import src.data_pages as dpage  # noqa: E402
import src.dict_admin_pages as dp  # noqa: E402
from src import ui_kit  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    _fx24_annotation_progress_cached,
    _render_style_check_section,
    _style_check_user_names,
)


# ============================================
# 假体与夹具
# ============================================

class _StubCol:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubSt:
    """st 假体：质检段与批次列表渲染所需控件的最小实现，记录调用供断言。"""

    def __init__(self, submit=False):
        self.submit = submit
        self.session_state = {}
        self.messages = []       # (kind, text)
        self.selectboxes = []    # (label, options)
        self.buttons = []        # (label, kwargs)
        self.charts = []         # altair_chart (chart, kwargs)

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

    def dataframe(self, *args, **kwargs):
        pass

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

    def altair_chart(self, *args, **kwargs):
        self.charts.append((args[0] if args else None, kwargs))

    def texts(self, kind=None):
        return [t for k, t in self.messages if kind is None or k == kind]

    def joined(self):
        return "\n".join(self.texts())


_ME_ADMIN = {"id": 7, "username": "fx57da", "display_name": "主编",
             "role": "viewer", "roles": ["dict_admin"], "active": True}

_FAKE_ITEMS = [
    {"code": "CFG_COMPLETE", "rule": "六件套必备键齐备", "status": "pass",
     "detail": "六件套键齐备"},
    {"code": "DEFINING_VOCAB", "rule": "定义词表非空且无重复词条",
     "status": "fail", "detail": "定义词表为空（词表本体待编者核定）"},
    {"code": "MULTIMEDIA_BINDINGS", "rule": "multimedia 位规则抽查",
     "status": "warn", "detail": "暂无媒体绑定可检（观察项）"},
]


def _run_row(run_id=2, **over):
    """最近 run 全量面假行（形态与 list_recent_runs include_detail=True 对齐）。"""
    row = {
        "id": run_id, "category": "motion", "run_by": 7,
        "passed": 3, "failed": 1, "warned": 1, "total": 5,
        "created_at": "2026-11-09 10:00:00",
        "detail_json": "[...]",
        "items": [dict(it) for it in _FAKE_ITEMS],
    }
    row.update(over)
    return row


def _slim_row(row):
    """瘦身面行：剥 items/detail_json 键（include_detail=False 形态）。"""
    return {k: v for k, v in row.items() if k not in ("items", "detail_json")}


def _trend_ok():
    """趋势假行（≥2 次，避开趋势 R4 灰注路径；图表契约归 test_fx50）。"""
    return [
        {"run_id": 1, "created_at": "2026-11-08 10:00:00", "rate": 0.5,
         "passed": 2, "failed": 2},
        {"run_id": 2, "created_at": "2026-11-09 10:00:00", "rate": 0.75,
         "passed": 3, "failed": 1},
    ]


def _patch_section(monkeypatch, stub, *, slim, full, trend=None):
    """铺质检段假体；list_recent_runs 桩按 include_detail 回双形态并记录调用。

    返回 calls（每次调用的 {category, limit, include_detail}）供调用形态断言。
    """

    def _fake_list_recent_runs(category=None, limit=5, include_detail=True):
        calls.append({"category": category, "limit": limit,
                      "include_detail": include_detail})
        if include_detail:
            return None if full is None else list(full)
        return list(slim)

    calls: list = []
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    monkeypatch.setattr(dp.users_db, "list_users",
                        lambda: [{"id": 7, "username": "c", "display_name": "主编甲"}])
    monkeypatch.setattr(dp.style_check, "list_recent_runs",
                        _fake_list_recent_runs)
    monkeypatch.setattr(dp.style_check, "pass_rate_trend",
                        lambda category=None, limit=20: trend)
    return calls


@pytest.fixture(autouse=True)
def _clear_caches_and_flash():
    """每用例清两个 TTL 缓存与 flash 队列（裸模式 session_state 跨用例防线）。"""
    dp._FX24_PROGRESS_CACHE.clear()
    dp._STYLE_CHECK_NAMES_CACHE.clear()
    st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)
    yield
    dp._FX24_PROGRESS_CACHE.clear()
    dp._STYLE_CHECK_NAMES_CACHE.clear()
    st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


# ============================================
# RV24-1：最近一次 run 全量读 ＋ 明细表真渲染 ＋ 瘦身面降级灰注
# ============================================

def test_latest_run_full_detail_fetch_and_badge_table_renders(monkeypatch):
    """双形态桩：历史小表走瘦身面（limit=5、include_detail=False），最近一次
    run 单独全量读（limit=1、include_detail=True）；全量面带 items → 三色
    徽章明细表真渲染（FX-26 核心交付复活），且无任何灰注。"""
    stub = _StubSt()
    row = _run_row()
    calls = _patch_section(monkeypatch, stub, slim=[_slim_row(row)],
                           full=[row], trend=_trend_ok())
    _render_style_check_section()
    slim_calls = [c for c in calls if not c["include_detail"]]
    full_calls = [c for c in calls if c["include_detail"]]
    assert slim_calls and slim_calls[0]["limit"] == 5
    assert full_calls and full_calls[0]["limit"] == 1
    assert full_calls[0]["category"] == slim_calls[0]["category"]
    joined = stub.joined()
    # 明细表真渲染：三项 code 与说明在场（瘦身面桩形态下旧实现必失败）
    for code in ("CFG_COMPLETE", "DEFINING_VOCAB", "MULTIMEDIA_BINDINGS"):
        assert code in joined
    assert "词表本体待编者核定" in joined
    for label in ("通过", "未过", "警告"):
        assert f">{label}</span>" in joined
    # 计数 caption 与历史小表照常（>#2< 精确匹配历史行单元格）
    assert any("75.0%" in c and "passed/(passed+failed)" in c
               for c in stub.texts("caption"))
    assert any(k == "markdown" and ">#2<" in m for k, m in stub.messages)
    assert not stub.texts("warning")     # 全量面有明细 → 无任何灰注


def test_latest_detail_fetch_failure_degrades_with_r4_note(monkeypatch):
    """瘦身面灰注：全量读失败（None）→ R4 归因灰注，历史小表与计数 caption
    不受影响；不冒充「解析失败」（与明细缺失分开归因，RV24-1）。"""
    stub = _StubSt()
    row = _run_row()
    calls = _patch_section(monkeypatch, stub, slim=[_slim_row(row)],
                           full=None, trend=_trend_ok())
    _render_style_check_section()
    assert len([c for c in calls if c["include_detail"]]) == 1
    joined = stub.joined()
    assert any(k == "warning" and "读取失败" in t and "R4" in t
               for k, t in stub.messages)
    assert not any("解析失败" in t for t in stub.texts("warning"))
    assert "CFG_COMPLETE" not in joined          # 无明细表、不编项
    assert any("75.0%" in c for c in stub.texts("caption"))
    assert any(k == "markdown" and ">#2<" in m for k, m in stub.messages)


# ============================================
# RV24-3：TTL 缓存族「失败 pop 即降级」＋ 循环外单次写
# ============================================

def test_fx24_progress_cache_failure_pops_entry_immediately(monkeypatch):
    """失败（R4 None）pop 即降级：过期后取数失败 → 条目即时清除、返回 None，
    不留旧值；恢复后下次调用重新取数（与 _style_check_user_names 同口径）。"""
    dp._FX24_PROGRESS_CACHE.clear()
    scope = "fx57-progress"
    values = iter([
        [{"verb": "run", "flagged": 1}],
        None,
        [{"verb": "run", "flagged": 5}],
    ])
    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress",
                        lambda: next(values))
    v1 = _fx24_annotation_progress_cached(scope)
    assert v1 == [{"verb": "run", "flagged": 1}]
    assert scope in dp._FX24_PROGRESS_CACHE
    # 回拨时间戳模拟 TTL 过期（保真过期路径，非清缓存捷径）
    ts, val = dp._FX24_PROGRESS_CACHE[scope]
    dp._FX24_PROGRESS_CACHE[scope] = (ts - dp._FX24_PROGRESS_TTL - 1, val)
    v2 = _fx24_annotation_progress_cached(scope)
    assert v2 is None                                # 失败如实降级
    assert scope not in dp._FX24_PROGRESS_CACHE      # pop 即降级（不留旧条目）
    v3 = _fx24_annotation_progress_cached(scope)     # 恢复后重新取数自愈
    assert v3 == [{"verb": "run", "flagged": 5}]
    assert scope in dp._FX24_PROGRESS_CACHE


def test_fx24_progress_cache_fresh_hit_serves_stale_within_ttl(monkeypatch):
    """取舍面：TTL 窗口内回陈旧成功值、不触取数（docstring 注明的折中）。"""
    dp._FX24_PROGRESS_CACHE.clear()
    scope = "fx57-progress2"
    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress",
                        lambda: [{"verb": "run", "flagged": 1}])
    assert _fx24_annotation_progress_cached(scope) == \
        [{"verb": "run", "flagged": 1}]

    def _boom():
        raise AssertionError("TTL 窗口内不应重新取数")

    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress", _boom)
    assert _fx24_annotation_progress_cached(scope) == \
        [{"verb": "run", "flagged": 1}]


def test_style_check_names_cache_write_once_and_empty_not_cached(monkeypatch):
    """成功路径缓存写恰一次（RV24-3：写移出 for 循环体尾，原实现逐行重复写）；
    空映射不缓存（断库恢复即时自愈口径不变）。"""

    class _SpyDict(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.writes = []

        def __setitem__(self, key, value):
            self.writes.append(key)
            super().__setitem__(key, value)

    spy = _SpyDict()
    monkeypatch.setattr(dp, "_STYLE_CHECK_NAMES_CACHE", spy)
    monkeypatch.setattr(dp.mysql_db, "cache_scope_key", lambda: "fx57-names")
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [
        {"id": 7, "username": "c", "display_name": "主编甲"},
        {"id": 9, "username": "乙", "display_name": None},
    ])
    names = _style_check_user_names()
    assert names == {7: "主编甲", 9: "乙"}
    assert spy.writes == ["fx57-names"]              # 恰写一次
    assert spy["fx57-names"][1] == names
    # 空花名册（先清缓存走取数路径）→ 空映射不缓存
    spy.clear()
    spy.writes.clear()
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [])
    assert _style_check_user_names() == {}
    assert spy.writes == []


def test_style_check_names_cache_failure_pops_stale_entry(monkeypatch):
    """失败 pop 即降级（既有口径钉住防漂移）：过期后取数失败 → 旧条目被清、
    空映射降级；恢复后下次调用重新取数。"""
    dp._STYLE_CHECK_NAMES_CACHE.clear()
    monkeypatch.setattr(dp.mysql_db, "cache_scope_key", lambda: "fx57-names2")
    monkeypatch.setattr(dp.users_db, "list_users",
                        lambda: [{"id": 7, "username": "c", "display_name": "主编甲"}])
    assert _style_check_user_names() == {7: "主编甲"}
    assert "fx57-names2" in dp._STYLE_CHECK_NAMES_CACHE
    ts, mapping = dp._STYLE_CHECK_NAMES_CACHE["fx57-names2"]
    dp._STYLE_CHECK_NAMES_CACHE["fx57-names2"] = (
        ts - dp._STYLE_CHECK_NAMES_TTL - 1, mapping)

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(dp.users_db, "list_users", _boom)
    assert _style_check_user_names() == {}
    assert "fx57-names2" not in dp._STYLE_CHECK_NAMES_CACHE


# ============================================
# RV24-11：docstring 与实现同步（控件形态 / 图表 API）
# ============================================

def test_section_docstring_matches_rv21_1_widgets():
    """RV24-11：段 docstring 不再写「form 提交型控件」（RV21-1 表外下拉＋
    裸 button），并如实记载 RV24-1 全量读口径。"""
    src = inspect.getsource(dp._render_style_check_section)
    doc = src.split('"""', 2)[1]
    assert "表单提交型" not in doc
    assert "include_detail=True" in doc and "include_detail=False" in doc


def test_trend_docstring_matches_altair_implementation():
    """RV24-11：趋势 docstring 与实现同为 st.altair_chart（批次 29），不再
    漂移到 st.line_chart；实现体确在调 altair_chart。"""
    src = inspect.getsource(dp._render_style_check_trend)
    doc, body = src.split('"""', 2)[1], src.split('"""', 2)[-1]
    assert "st.altair_chart" in doc and "st.line_chart" not in doc
    assert "st.altair_chart(" in body and "st.line_chart" not in body


# ============================================
# RV25-6：导入回滚成功反馈 ui_kit.flash ＋ st.rerun（st.success 回潮禁止）
# ============================================

_FINISHED_BATCH = {
    "id": 5, "file_name": "verbs.csv", "file_sha256": "ab" * 16,
    "target_domain": "definitions", "rows_total": 3, "rows_ok": 3,
    "rows_rejected": 0, "status": "finished", "operator": "fx57",
    "created_at": "2026-11-09 10:00:00",
}


def _patch_batch_list_world(monkeypatch, stub, rollback):
    monkeypatch.setattr(dpage, "st", stub)
    monkeypatch.setattr(dpage, "_list_recent_batches",
                        lambda *a, **k: [dict(_FINISHED_BATCH)])
    monkeypatch.setattr(dpage, "_load_persisted_revert_log",
                        lambda bid: [{"old_values": {}}])
    monkeypatch.setattr(dpage, "rollback_batch", rollback)


def test_import_rollback_success_flashes_then_reruns(monkeypatch):
    """行为级：回滚成功 → ui_kit.flash 队列含批次文案（rerun 不丢提示）、
    无 st.success、st.rerun 在场、持久化事件路径不显式传参。"""
    stub = _StubSt(submit=True)
    seen = {}

    def _fake_rollback(bid, events=None):
        seen["args"] = (bid, events)
        return True

    _patch_batch_list_world(monkeypatch, stub, _fake_rollback)
    dpage._render_batch_list()
    assert seen["args"][0] == 5 and seen["args"][1] is None  # 持久化路径
    queue = st.session_state.get(ui_kit._FLASH_QUEUE_KEY) or []
    assert queue and "已回滚" in queue[-1]["message"]
    assert "批次 5" in queue[-1]["message"] and "old_values" in queue[-1]["message"]
    assert not stub.texts("success")                 # 禁 st.success 回潮
    assert any(k == "rerun" for k, _ in stub.messages)


def test_import_rollback_failure_stays_inline_error(monkeypatch):
    """回滚失败路径不 flash 不 rerun，行内 st.error 如实归因（既有口径）。"""
    stub = _StubSt(submit=True)

    def _fail(bid, events=None):
        return False

    _patch_batch_list_world(monkeypatch, stub, _fail)
    dpage._render_batch_list()
    assert any(k == "error" and "回滚失败" in t for k, t in stub.messages)
    assert not stub.texts("success") and not stub.texts("rerun")
    assert not (st.session_state.get(ui_kit._FLASH_QUEUE_KEY) or [])


def test_render_batch_list_has_no_st_success():
    """源级钉板：_render_batch_list 全函数 st.success 清零（RV25-6 收口），
    成功反馈走 ui_kit.flash ＋ st.rerun。"""
    src = inspect.getsource(dpage._render_batch_list)
    assert "st.success" not in src
    assert "ui_kit.flash" in src and "st.rerun" in src
