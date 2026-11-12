"""FX-26 批次修复验证：驾驶舱「🧪 体例质检」段 ＋ R6-11 docstring 清欠。

口径（与 src/dict_admin_pages.py FX-26 段注释、src/style_check.py 引擎
docstring 一致）：

  * 体例质检段（FX-25 引擎 src/style_check.py 的 UI 入口）：
    - 常量与徽章：历史条数 5、pass/fail/warn 三色徽章走
      design_system.get_badge_html 既有口径（SUCCESS/ERROR/WARNING_COLOR）；
    - 渲染：权限兜底门（非词典管理员整段不渲染）、runs=None → R4 归因灰注、
      空清单 → 引导文案、逐项表（code/规则/结论/说明）＋ 通过率 caption
      （公式 passed/(passed+failed)、warn 不入分母）＋ 历史 run 小表
      （run_by=NULL →「系统作业」，RV2-3 留痕口径）、detail_json 解析失败
      如实灰注；
    - 运行按钮（form 提交）：guards 中央闸门拒绝 → st.error 不触引擎；
      引擎 ok → ui_kit.flash ＋ st.rerun（RV12-2，禁止 st.success 回潮）；
      ok=False / 异常形态 / 意外异常 → R4 归因灰注、不崩页不编数；
    - AppTest 冒烟：质检段渲染 not at exception ＋ 按钮在场 ＋ 点击后
      flash 成功提示经 ui_kit.pop_and_render_flash 弹出（打桩引擎函数，
      不触真库、不落假 run）；
  * R6-11 docstring 清欠（台账遗留 P3，fx5 契约 FX5_FILES 之外的本批涉改
    文件）：category_pack / llm_api / reliability / word_source 全函数
    （含嵌套函数与降级分支内函数）docstring 覆盖 100% —— 本文件钉住，
    防回潮；dict_admin_pages 本批新增函数同扫。

本文件不连数据库（单测全部 monkeypatch 假体驱动；AppTest 打桩引擎与花名册
取数函数）。
"""
import ast
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import src.dict_admin_pages as dp  # noqa: E402
from src import ui_kit  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    FX26_STYLE_CHECK_HISTORY,
    _render_style_check_section,
    _style_check_history_rows,
    _style_check_run_clicked,
    _style_check_status_badge,
    _style_check_user_names,
)


# ============================================
# 假体：st 假体（form 提交可配）＋ 夹具
# ============================================

class _StubCol:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubSt:
    """st 假体：质检段所需控件的最小实现（form/submit/selectbox＋输出族）。

    submit=True 模拟「▶ 运行体例质检」被提交；selectbox 取 options 首项
    （与真实 UI 的默认选中一致）。记录调用供断言。
    """

    def __init__(self, submit=False):
        self.submit = submit
        self.messages = []       # (kind, text)
        self.selectboxes = []    # (label, options)
        self.buttons = []        # (label, kwargs)
        self.charts = []         # FX-50 趋势图 line_chart 调用 (data, kwargs)

    def form(self, *args, **kwargs):
        return _StubCol()

    def columns(self, spec, **kwargs):
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_StubCol() for _ in range(n)]

    def selectbox(self, *args, **kwargs):
        opts = kwargs.get("options") or (args[1] if len(args) > 1 else [])
        self.selectboxes.append((args[0] if args else "", opts))
        return opts[0] if opts else None

    def form_submit_button(self, *args, **kwargs):
        self.buttons.append((args[0] if args else "", kwargs))
        return self.submit

    def button(self, *args, **kwargs):
        # RV21-1：质检段改普通按钮后桩同面（点击路径与 form 提交等价）
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
        # FX-50 趋势图桩：单独记录不进 messages（DataFrame 非 str，
        # 混入会让 joined() 的 "\n".join 炸类型；本文件用例默认 trend 桩
        # 为 None，不走到图表，仅防新渲染路径炸桩）
        self.charts.append((args[0] if args else None, kwargs))

    def texts(self, kind=None):
        return [t for k, t in self.messages if kind is None or k == kind]

    def joined(self):
        return "\n".join(self.texts())


_ME_ADMIN = {"id": 7, "username": "fx26chief", "display_name": "主编",
             "role": "viewer", "roles": ["dict_admin"], "active": True}
_ME_VIEWER = {"id": 8, "username": "viewer1", "display_name": "路",
              "role": "viewer", "roles": ["viewer"], "active": True}

_FAKE_ITEMS = [
    {"code": "CFG_COMPLETE", "rule": "六件套必备键齐备", "status": "pass",
     "detail": "六件套键齐备"},
    {"code": "DEFINING_VOCAB", "rule": "定义词表非空且无重复词条",
     "status": "fail", "detail": "定义词表为空（词表本体待编者核定）"},
    {"code": "SENSE_ORDERING", "rule": "排序规则键合法", "status": "pass",
     "detail": "primary=原型梯度（命中枚举）"},
    {"code": "MICROSTRUCTURE_SPINE", "rule": "microstructure×spine 一致性",
     "status": "warn", "detail": "自动化比对未覆盖：声明键未纳入比对"},
    {"code": "MULTIMEDIA_BINDINGS", "rule": "multimedia 位规则抽查",
     "status": "pass", "detail": "暂无媒体绑定可检（观察项）"},
]


def _fake_runs(**over):
    """最近 run 假清单（形态与 style_check.list_recent_runs 行对齐）。"""
    run = {
        "id": 2, "category": "motion", "run_by": 7,
        "passed": 3, "failed": 1, "warned": 1, "total": 5,
        "created_at": "2026-11-09 10:00:00",
        "detail_json": "[...]",
        "items": [dict(it) for it in _FAKE_ITEMS],
    }
    run.update(over)
    return [run]


def _clear_flash_queue():
    """清空 ui_kit 会话提示队列（裸模式 session_state 跨用例残留）。"""
    st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


# ============================================
# 常量与徽章
# ============================================

def test_history_limit_constant_is_five():
    """历史 run 小表条数 = 5（任务书口径；引擎 list_recent_runs limit 透传）。"""
    assert FX26_STYLE_CHECK_HISTORY == 5


def test_status_badge_uses_design_system_badge_html():
    """三态徽章走 design_system.get_badge_html ＋ 既有色板（自动深/浅字）。"""
    from src import design_system as ds

    assert dp._STYLE_CHECK_STATUS_COLORS["pass"] == ds.SUCCESS_COLOR
    assert dp._STYLE_CHECK_STATUS_COLORS["fail"] == ds.ERROR_COLOR
    assert dp._STYLE_CHECK_STATUS_COLORS["warn"] == ds.WARNING_COLOR
    badge = _style_check_status_badge("pass")
    assert badge == ds.get_badge_html("通过", ds.SUCCESS_COLOR)
    assert "通过" in badge and ds.SUCCESS_COLOR in badge
    assert "未过" in _style_check_status_badge("fail")
    assert "警告" in _style_check_status_badge("warn")


def test_status_badge_unknown_status_gray_raw_text():
    """枚举外 status → 灰徽章显原文（引擎契约外值不隐藏、不编文案）。"""
    badge = _style_check_status_badge("mystery")
    assert "mystery" in badge and dp._INACTIVE_GRAY in badge
    assert "—" in _style_check_status_badge(None)


# ============================================
# 历史小表：执行人映射与行归一
# ============================================

def test_user_names_mapping_and_degradation(monkeypatch):
    """run_by → 展示名映射；花名册取数失败按空映射降级（不拖垮质检段）。"""
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [
        {"id": 7, "username": "chief", "display_name": "主编甲"},
        {"id": 9, "username": "乙", "display_name": None},
        "脏行", {"id": "x", "username": "脏id"},
    ])
    dp._STYLE_CHECK_NAMES_CACHE.clear()  # RV16-3：清缓存使首Phase真实取数
    names = _style_check_user_names()
    assert names == {7: "主编甲", 9: "乙"}
    # 二阶段（断库降级）：TTL 内缓存命中是 RV16-3 设计行为（陈旧窗折中）——
    # 降级路径在缓存清空后触发：清缓存→取数失败→空映射即时降级不缓存
    dp._STYLE_CHECK_NAMES_CACHE.clear()

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(dp.users_db, "list_users", _boom)
    assert _style_check_user_names() == {}


def test_history_rows_shape_and_system_actor(monkeypatch):
    """历史行：id/时间/执行人/通过/未过/警告；run_by=None →「系统作业」。"""
    monkeypatch.setattr(dp.users_db, "list_users",
                        lambda: [{"id": 7, "username": "c", "display_name": "主编甲"}])
    rows = _style_check_history_rows([
        {"id": 2, "created_at": "2026-11-09 10:00:00", "run_by": 7,
         "passed": 3, "failed": 1, "warned": 1},
        {"id": 1, "created_at": "2026-11-08 09:00:00", "run_by": None,
         "passed": 0, "failed": 0, "warned": 0},
    ])
    assert rows[0] == ["#2", "2026-11-09 10:00:00", "主编甲", "3", "1", "1"]
    assert rows[1][2] == "系统作业"


# ============================================
# 运行按钮提交处理：闸门 / 成功 flash / R4 灰注
# ============================================

def test_run_clicked_gate_denied_engine_untouched(monkeypatch):
    """guards 中央闸门拒绝 → st.error 转述，引擎一次都不被触达。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)

    def _deny():
        raise PermissionError("仅词典管理员可执行词典数据写操作。")

    called = []
    monkeypatch.setattr(dp.guards, "require_dict_admin", _deny)
    monkeypatch.setattr(dp.style_check, "run_style_check",
                        lambda *a, **k: called.append((a, k)))
    _style_check_run_clicked("motion", _ME_ADMIN)
    assert called == []
    assert any(k == "error" and "仅词典管理员" in t for k, t in stub.messages)
    assert not stub.texts("rerun")


def test_run_clicked_ok_flashes_then_reruns(monkeypatch):
    """引擎 ok → ui_kit.flash（队列含完成文案与计数）＋ st.rerun；actor 透传。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    _clear_flash_queue()
    seen = {}

    def _fake_run(category, actor=None):
        seen["args"] = (category, actor)
        return {"ok": True, "run_id": 3, "category": category,
                "passed": 3, "failed": 1, "warned": 1, "total": 5,
                "pass_rate": 0.75, "items": []}

    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME_ADMIN)
    monkeypatch.setattr(dp.style_check, "run_style_check", _fake_run)
    _style_check_run_clicked("motion", _ME_ADMIN)
    assert seen["args"] == ("motion", _ME_ADMIN)   # actor=当前用户透传引擎
    assert any(k == "rerun" for k, _ in stub.messages)
    queue = st.session_state.get(ui_kit._FLASH_QUEUE_KEY) or []
    assert queue and "体例质检完成" in queue[-1]["message"]
    assert "run #3" in queue[-1]["message"] and "3/4" in queue[-1]["message"]
    assert "警告 1 项单列" in queue[-1]["message"]
    assert not stub.texts("success")               # 禁 st.success 回潮
    _clear_flash_queue()


def test_run_clicked_engine_permission_error(monkeypatch):
    """引擎闸门（require_role）拒绝 → st.error 转述、不 rerun。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME_ADMIN)

    def _deny(category, actor=None):
        raise PermissionError("体例质检执行仅词典管理员可执行")

    monkeypatch.setattr(dp.style_check, "run_style_check", _deny)
    _style_check_run_clicked("motion", _ME_ADMIN)
    assert any(k == "error" and "仅词典管理员" in t for k, t in stub.messages)
    assert not stub.texts("rerun")


def test_run_clicked_engine_exception_gray_note(monkeypatch):
    """引擎意外异常（理论不抛）→ R4 归因灰注、不崩页、不 rerun。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME_ADMIN)

    def _boom(category, actor=None):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(dp.style_check, "run_style_check", _boom)
    _style_check_run_clicked("motion", _ME_ADMIN)
    assert any(k == "warning" and "RuntimeError" in t and "未执行" in t
               for k, t in stub.messages)
    assert not stub.texts("rerun")


def test_run_clicked_declined_reason_gray_note(monkeypatch):
    """引擎 ok=False（style.yaml 缺失/库不可用）→ reason 原文灰注、不 rerun。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME_ADMIN)
    monkeypatch.setattr(
        dp.style_check, "run_style_check",
        lambda category, actor=None: {"ok": False, "run_id": None,
                                      "reason": "style.yaml 不在场（候选路径均未检出）"})
    _style_check_run_clicked("motion", _ME_ADMIN)
    assert any(k == "warning" and "style.yaml 不在场" in t
               for k, t in stub.messages)
    assert not stub.texts("rerun") and not stub.texts("success")


def test_run_clicked_bad_shape_result_gray_note(monkeypatch):
    """引擎返回异常形态（非 dict）→ 灰注兜底，不崩页。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME_ADMIN)
    monkeypatch.setattr(dp.style_check, "run_style_check",
                        lambda category, actor=None: None)
    _style_check_run_clicked("motion", _ME_ADMIN)
    assert any(k == "warning" and "未执行" in t for k, t in stub.messages)
    assert not stub.texts("rerun")


# ============================================
# 渲染：权限门 / 数据不可用分级 / 逐项表与历史表
# ============================================

def _patch_section_world(monkeypatch, stub, runs="unset", submit=False,
                         trend=None):
    """铺质检段渲染假体：st/会话用户/花名册；runs 传 None/[]/清单可配。

    FX-50：趋势读面 pass_rate_trend 一并打桩（默认 None=R4 灰注路径，
    本文件用例不展开图表面——图表契约由 test_fx50_fixes 钉住），保证
    质检段单测不触真库。
    """
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    monkeypatch.setattr(dp.users_db, "list_users",
                        lambda: [{"id": 7, "username": "c", "display_name": "主编甲"}])
    if runs != "unset":
        monkeypatch.setattr(dp.style_check, "list_recent_runs",
                            lambda category=None, limit=5, include_detail=True: runs)
    monkeypatch.setattr(dp.style_check, "pass_rate_trend",
                        lambda category=None, limit=20: trend)
    return stub


def test_section_hidden_without_dict_admin(monkeypatch):
    """未登录 / 非词典管理员 → 整段不渲染（fail-closed，同 FX-24 两段）。"""
    for user in (None, _ME_VIEWER):
        stub = _StubSt()
        monkeypatch.setattr(dp, "st", stub)
        monkeypatch.setattr(dp, "_current_user", lambda user=user: user)
        _render_style_check_section()
        assert "体例质检" not in stub.joined()
        assert stub.buttons == []


def test_section_runs_none_renders_gray_note(monkeypatch):
    """list_recent_runs=None（表未建/库断连）→ R4 归因灰注，无表格无引导。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=None)
    _render_style_check_section()
    joined = stub.joined()
    assert "🧪 体例质检" in joined
    assert any("▶ 运行体例质检" in label for label, _ in stub.buttons)
    assert any(k == "warning" and "数据不可用" in t and "style_check_runs" in t
               for k, t in stub.messages)
    assert not any(k == "info" for k, t in stub.messages)


def test_section_empty_runs_guidance(monkeypatch):
    """空清单（真 0）→ 「尚无质检记录」引导文案，不出灰注。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=[])
    _render_style_check_section()
    joined = stub.joined()
    assert "尚无质检记录" in joined
    assert not any(k == "warning" for k, t in stub.messages)


def test_section_full_renders_items_history_and_caption(monkeypatch):
    """全量渲染：逐项表（含三态徽章）＋ 通过率公式 caption ＋ 历史 run 小表。"""
    stub = _StubSt()
    _patch_section_world(monkeypatch, stub, runs=_fake_runs())
    _render_style_check_section()
    joined = stub.joined()
    # 运行入口（form 提交按钮）在场
    assert any("▶ 运行体例质检" in label for label, _ in stub.buttons)
    # 逐项表：code 与说明如实；三态徽章在场（通过/未过/警告）
    assert "CFG_COMPLETE" in joined and "DEFINING_VOCAB" in joined
    assert "词表本体待编者核定" in joined
    for label in ("通过", "未过", "警告"):
        assert f">{label}</span>" in joined
    # 通过率 caption：公式与 warn 口径注明（3/4=75.0%）
    captions = stub.texts("caption")
    assert any("passed/(passed+failed)" in c and "75.0%" in c
               and "warn 单列" in c for c in captions)
    # 历史小表：run #2 行与执行人映射（">#2<" 精确匹配单元格，避开徽章色值）
    history_md = [m for k, m in stub.messages
                  if k == "markdown" and ">#2<" in m]
    assert history_md and "主编甲" in history_md[0]
    assert ">#1<" not in history_md[0]
    # 范畴下拉与质检范畴同源（funnel 选项，motion 在列）
    assert any("质检范畴" in label and "motion" in opts
               for label, opts in stub.selectboxes)


def test_section_history_shows_system_actor(monkeypatch):
    """run_by=None 的历史行渲染「系统作业」（RV2-3 留痕列第 1 类口径）。"""
    stub = _StubSt()
    _patch_section_world(
        monkeypatch, stub, runs=_fake_runs(id=1, run_by=None))
    _render_style_check_section()
    history_md = [m for k, m in stub.messages
                  if k == "markdown" and "系统作业" in m]
    assert history_md


def test_section_items_parse_failure_gray_note(monkeypatch):
    """detail_json 解析失败（items=None）→ 如实灰注，不编逐项行。"""
    stub = _StubSt()
    _patch_section_world(
        monkeypatch, stub, runs=_fake_runs(items=None))
    _render_style_check_section()
    joined = stub.joined()
    assert "明细解析失败" in joined
    assert "CFG_COMPLETE" not in joined     # 不编项


# ============================================
# 纪律：成功反馈走 ui_kit.flash ＋ widget key 前缀
# ============================================

def test_run_feedback_uses_flash_not_st_success():
    """RV12-2 纪律：提交处理成功反馈一律 ui_kit.flash ＋ st.rerun。"""
    src = inspect.getsource(_style_check_run_clicked)
    assert "ui_kit.flash" in src and "st.rerun" in src
    assert "st.success" not in src


def test_section_widget_keys_prefixed():
    """widget key 一律 'dict_admin_' 前缀（页面自订规则；质检段两键——
    RV21-1 后范畴下拉移出表单、运行按钮直置）。"""
    src = inspect.getsource(_render_style_check_section)
    assert 'key="dict_admin_style_check_category"' in src
    assert 'key="dict_admin_style_check_run"' in src


# ============================================
# AppTest 冒烟：渲染 not at exception ＋ 按钮在场 ＋ 点击 flash 弹出
# ============================================

_SMOKE_SCRIPT = (
    "from src import ui_kit\n"
    "from src.dict_admin_pages import _render_style_check_section\n"
    "ui_kit.pop_and_render_flash()\n"     # 与 app.main() 每轮渲染开头同序
    "_render_style_check_section()\n"
)


def test_apptest_smoke_render_and_run_button(monkeypatch):
    """AppTest 冒烟：段渲染不抛异常、提交按钮在场；点击后 flash 经
    pop_and_render_flash 弹出（引擎打桩，不触真库不落假 run）。"""
    monkeypatch.setattr(dp.style_check, "list_recent_runs",
                        lambda category=None, limit=5, include_detail=True: _fake_runs())
    monkeypatch.setattr(dp.style_check, "pass_rate_trend",
                        lambda category=None, limit=20: None)  # FX-50：趋势面本文件不展开
    monkeypatch.setattr(
        dp.style_check, "run_style_check",
        lambda category, actor=None: {"ok": True, "run_id": 9,
                                      "category": category,
                                      "passed": 4, "failed": 0, "warned": 1,
                                      "total": 5, "pass_rate": 1.0,
                                      "items": []})
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [])
    at = AppTest.from_string(_SMOKE_SCRIPT, default_timeout=60)
    at.session_state["user"] = dict(_ME_ADMIN)
    at.run()
    assert not at.exception
    run_buttons = [b for b in at.button if "▶ 运行体例质检" in b.label]
    assert run_buttons, "体例质检运行按钮未渲染"
    # 首轮：逐项表与历史表在场（打桩 run #2）
    markdown_text = "".join(str(md.value) for md in at.markdown)
    assert "CFG_COMPLETE" in markdown_text and "#2" in markdown_text
    # 点击运行按钮 → 引擎执行 → flash ＋ rerun → 成功提示弹出
    run_buttons[0].click().run()
    assert not at.exception
    assert any("体例质检完成" in str(s.value) and "run #9" in str(s.value)
               for s in at.success)
    # 逐项表仍渲染（rerun 后历史首位是新 run，此处打桩恒返回 run #2）
    assert any("▶ 运行体例质检" in b.label for b in at.button)


# ============================================
# R6-11 docstring 清欠（本批涉改文件全函数覆盖，含嵌套/降级分支函数）
# ============================================

class TestR611:
    FX26_FILES = (
        "src/dict_admin_pages.py", "src/category_pack.py",
        "src/llm_api.py", "src/reliability.py", "src/word_source.py",
    )

    def test_all_functions_have_docstrings(self):
        """本批涉改文件内函数（含嵌套函数）docstring 覆盖 100%（钉住防回潮）。"""
        for rel in self.FX26_FILES:
            tree = ast.parse(open(os.path.join(PROJECT_ROOT, rel)).read())
            missing = [
                f"{n.name}:{n.lineno}" for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and ast.get_docstring(n) is None
            ]
            assert not missing, f"{rel} 缺 docstring: {missing}"
