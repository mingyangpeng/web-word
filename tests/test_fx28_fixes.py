"""FX-28 测试：G3 簇锁定「撰写侧消费」最小诚实落地（规范×实现对账②组）。

规范口径（docs/spec/平台架构设计规范.md §3 闸门表）：
  G3 分立→释义：条件＝该簇分立复核定稿（义项清单锁定）；拦下＝未定清单上写释义。
  即 locked=1 是「义项清单定稿、放行流入释义撰写」的正向口径（批次 6 落库位
  cluster_analysis：locked 簇才允许流入释义撰写）—— 拦的是未定清单，不是
  禁写已锁定簇；撰写侧据此做**提示型消费**（锁定不是闸刀）。

覆盖（全部不连真实数据库 —— 数据层假游标、页面 AppTest 打桩）：
  1. writing_db.get_cluster_lock_state 锁态读面三态（锁定/未锁/无簇归属）
     ＋ fail-open 路径（库不可用/意外异常/入参非法 → locked=False＋reason，
     不抛异常不阻断编纂；诚实口径：cs_clusters 无 locked_at/locked_by 列，
     读面不编造这两个字段）；
  2. 撰写台顶部「🔒 词簇已定稿锁定」徽章两态 AppTest（_render_write_tab）：
     locked → 徽章＋定稿基线说明；未锁定/读面降级 → 不渲染；且 locked 态下
     保存草稿照常落库（「锁定不是禁写」的实证）；
  3. 模板页「🔒 定稿基线」标识两态 AppTest（render_template_page 打桩）＋
     template_lock_note 纯函数（查看/导出不受限口径）；
  4. G3 展示口径对齐：文案与簇分析侧「分立复核定稿（G3）」一致、词簇定名
     统一（新文案无「词义簇/语义簇」残留）、GUIDE 如实记载读面与徽章。
"""
import json
import os
import sys

import pymysql
import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.writing_db as writing_db  # noqa: E402
import src.writing_pages as wp  # noqa: E402
from src.template_engine import (  # noqa: E402
    TEMPLATE_LOCK_BADGE,
    template_lock_note,
)
from src.writing_pages import (  # noqa: E402
    GUIDE,
    LOCK_BANNER_NOTE,
    LOCK_BANNER_TEXT,
    cluster_lock_banner,
)


# ============================================
# 1. 锁态读面 get_cluster_lock_state（三态 + fail-open）
# ============================================

class _FakeCursor:
    """假 DictCursor：execute 记参数，fetchone/fetchall 吐预置结果（可注错）。"""

    def __init__(self, rows=None, row=None, error=None):
        self._rows = rows or []
        self._row = row
        self._error = error
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._error is not None:
            raise self._error

    def fetchone(self):
        return self._row

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_LOCKED_ROW = {"cluster_id": 7, "cluster_no": 1,
               "cluster_name": "方式伴随簇", "locked": 1, "run_id": 3}


def test_lock_state_locked_cluster(monkeypatch):
    """三态①：locked 簇归属命中 → locked=True ＋ 簇身份字段，无 reason 键。"""
    cur = _FakeCursor(row=dict(_LOCKED_ROW))
    monkeypatch.setattr(writing_db, "get_db_cursor", lambda autocommit=True: cur)
    state = writing_db.get_cluster_lock_state("RUN", 1)
    assert state["locked"] is True
    assert state["cluster_id"] == 7
    assert state["cluster_no"] == 1
    assert state["cluster_name"] == "方式伴随簇"
    assert state["run_id"] == 3
    assert "reason" not in state
    # 参数化查询：范畴/义位走绑定参数；取的是 cs_clusters.locked 列
    sql, params = cur.executed[0]
    assert params == ("RUN", 1)
    assert "locked" in sql and "cs_cluster_members" in sql


def test_lock_state_unlocked_cluster(monkeypatch):
    """三态②：有簇归属但 locked=0 → locked=False（有簇身份、无 reason）。"""
    row = dict(_LOCKED_ROW, locked=0)
    monkeypatch.setattr(
        writing_db, "get_db_cursor", lambda autocommit=True: _FakeCursor(row=row))
    state = writing_db.get_cluster_lock_state("RUN", 1)
    assert state["locked"] is False
    assert state["cluster_id"] == 7
    assert "reason" not in state


def test_lock_state_no_cluster_membership(monkeypatch):
    """三态③：无簇归属（未入簇）→ locked=False ＋ reason=no_cluster。"""
    monkeypatch.setattr(
        writing_db, "get_db_cursor", lambda autocommit=True: _FakeCursor(row=None))
    state = writing_db.get_cluster_lock_state("RUN", 99)
    assert state == {"locked": False, "reason": writing_db.LOCK_REASON_NO_CLUSTER}


@pytest.mark.parametrize("error", [
    pymysql.Error("connection refused"),            # 库不可用（含缺 locked 列）
    pymysql.OperationalError(1054, "Unknown column 'locked'"),
    RuntimeError("unexpected driver blowup"),       # 非预期异常同样折叠
])
def test_lock_state_db_unavailable_fail_open(monkeypatch, error):
    """fail-open：库不可用/locked 列未迁移/意外异常 → locked=False 不抛不阻断。"""
    monkeypatch.setattr(
        writing_db, "get_db_cursor",
        lambda autocommit=True: _FakeCursor(error=error))
    state = writing_db.get_cluster_lock_state("RUN", 1)
    assert state["locked"] is False
    assert state["reason"] == writing_db.LOCK_REASON_DB_UNAVAILABLE


def test_lock_state_invalid_params_never_touch_db(monkeypatch):
    """入参非法 → reason=invalid_params 且不触库（读面纯应用层先拒）。"""
    touched = []

    def _no_touch(autocommit=True):
        touched.append(1)
        return _FakeCursor(row=dict(_LOCKED_ROW))

    monkeypatch.setattr(writing_db, "get_db_cursor", _no_touch)
    for cat, sid in [("", 1), (None, 1), ("   ", 1), ("RUN", 0),
                     ("RUN", -1), ("RUN", None), ("RUN", "x"), (42, 1)]:
        state = writing_db.get_cluster_lock_state(cat, sid)
        assert state == {"locked": False,
                         "reason": writing_db.LOCK_REASON_INVALID_PARAMS}, (cat, sid)
    assert not touched  # 全部未触库


def test_lock_state_readonly_no_lock_write_path():
    """纪律：读面只读 —— 函数体内不得出现 UPDATE/INSERT cs_clusters（锁定
    写路径唯一在 cluster_analysis.set_cluster_locked，本模块不碰）。"""
    import inspect

    source = inspect.getsource(writing_db.get_cluster_lock_state)
    assert "UPDATE" not in source.upper()
    assert "INSERT" not in source.upper()
    assert "ALTER" not in source.upper()


# ============================================
# 2. 撰写台徽章（纯函数文案 + 两态 AppTest + 锁定不是禁写实证）
# ============================================

def test_cluster_lock_banner_locked_copy():
    """locked → 徽章＋说明：词簇已定稿锁定/定稿基线/分立复核定稿/不是禁写。"""
    banner = cluster_lock_banner(
        {"locked": True, "cluster_id": 7, "cluster_no": 1,
         "cluster_name": "方式伴随簇", "run_id": 3})
    assert banner is not None
    assert LOCK_BANNER_TEXT in banner and "🔒" in LOCK_BANNER_TEXT
    assert "定稿基线" in LOCK_BANNER_NOTE
    assert "分立复核定稿" in LOCK_BANNER_NOTE   # 与簇分析侧 G3 口径一致
    assert "不是禁写" in LOCK_BANNER_NOTE and "审校" in LOCK_BANNER_NOTE


@pytest.mark.parametrize("state", [
    None, {}, "locked", 42,
    {"locked": False},
    {"locked": False, "reason": writing_db.LOCK_REASON_NO_CLUSTER},
    {"locked": False, "reason": writing_db.LOCK_REASON_DB_UNAVAILABLE},
])
def test_cluster_lock_banner_fail_open_states(state):
    """未锁定/无簇归属/库不可用/非 dict → 不渲染徽章（提示不是闸刀）。"""
    assert cluster_lock_banner(state) is None


_WRITE_TAB_SCRIPT = (
    "from src.writing_pages import _render_write_tab\n"
    "_render_write_tab({'id': 7, 'username': 'ed', 'role': 'viewer', "
    "'roles': ['editor']})\n"
)

_SENSE_ROW = {
    "cs_sense_id": 1, "lemma": "run", "sense_no": "1",
    "sense_label": "足部奔跑义", "status": "目标", "category_code": "RUN",
    "cluster_id": 7, "cluster_no": 1, "locked": 1,
}


def _patch_write_tab(monkeypatch, lock_state, sense_locked=1):
    """打桩撰写台取数触点（义位清单/OALD 锚/模板/审校人/版本链/锁态读面）。"""
    sense = dict(_SENSE_ROW, locked=sense_locked)
    monkeypatch.setattr(
        wp, "_list_categories_dicts", lambda: [{"code": "RUN", "name_cn": "跑"}])
    monkeypatch.setattr(wp, "_list_candidate_senses",
                        lambda cat, lang: [sense])
    monkeypatch.setattr(wp, "_resolve_oald_sense_id", lambda lemma, no: 345)
    monkeypatch.setattr(wp, "_template_preview", lambda cat, lang, sid: None)
    monkeypatch.setattr(wp, "_reviewer_options", lambda me: [])
    monkeypatch.setattr(writing_db, "get_latest_version",
                        lambda *a, **k: None)
    monkeypatch.setattr(writing_db, "get_cluster_lock_state",
                        lambda cat, sid: dict(lock_state))


def test_write_tab_lock_badge_rendered_when_locked(monkeypatch):
    """AppTest 两态①：locked → 页面顶部「🔒 词簇已定稿锁定」徽章＋说明渲染。"""
    _patch_write_tab(monkeypatch, {"locked": True, "cluster_id": 7,
                                   "cluster_no": 1,
                                   "cluster_name": "方式伴随簇", "run_id": 3})
    at = AppTest.from_string(_WRITE_TAB_SCRIPT, default_timeout=60)
    at.run()
    assert not at.exception
    markdown_text = "".join(str(md.value) for md in at.markdown)
    assert "🔒 词簇已定稿锁定" in markdown_text
    assert "定稿基线" in markdown_text
    assert "不是禁写" in markdown_text
    caption_text = "".join(str(c.value) for c in at.caption)
    assert "G3 已锁定" in caption_text  # 既有簇状态标注仍在（两处口径一致）


def test_write_tab_no_badge_when_unlocked_or_degraded(monkeypatch):
    """AppTest 两态②：未锁定/读面降级 → 无徽章、页面照常渲染（fail-open）。"""
    for lock_state in ({"locked": False,
                        "reason": writing_db.LOCK_REASON_NO_CLUSTER},
                       {"locked": False,
                        "reason": writing_db.LOCK_REASON_DB_UNAVAILABLE}):
        _patch_write_tab(monkeypatch, lock_state, sense_locked=0)
        at = AppTest.from_string(_WRITE_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        markdown_text = "".join(str(md.value) for md in at.markdown)
        assert "词簇已定稿锁定" not in markdown_text
        caption_text = "".join(str(c.value) for c in at.caption)
        assert "⚠️ 簇未锁定" in caption_text  # 既有 ⚠️ 如实标注不缺席


def test_write_tab_save_draft_still_works_when_locked(monkeypatch):
    """锁定不是禁写实证：locked 态下保存草稿照常落库（create_draft 正常调用）。"""
    _patch_write_tab(monkeypatch, {"locked": True, "cluster_id": 7,
                                   "cluster_no": 1,
                                   "cluster_name": "方式伴随簇", "run_id": 3})
    calls = []
    monkeypatch.setattr(
        writing_db, "create_draft",
        lambda ref, author, content, **k: calls.append((ref, author)) or 55)
    at = AppTest.from_string(_WRITE_TAB_SCRIPT, default_timeout=60)
    at.run()
    areas = [t for t in at.text_area if t.label == "释义成文"]
    assert areas, "成文编辑框未渲染"
    areas[0].set_value("定稿基线上的修订稿（修订仍可提交走审校）")
    save = [b for b in at.button if "保存草稿" in str(b.label)]
    assert save, "保存草稿按钮未渲染"
    save[0].click()
    at.run()
    assert not at.exception
    assert calls and calls[0][0] == "RUN:1:345"  # 草稿照常建版（未被锁定拦截）
    assert any("草稿已保存" in str(s.value) for s in at.success)


# ============================================
# 3. 模板页「🔒 定稿基线」标识（纯函数 + 两态 AppTest）
# ============================================

def test_template_lock_note_locked_and_fail_open():
    """纯函数：locked → 「🔒 定稿基线」标识（查看/导出不受限）；其余 None。"""
    note = template_lock_note({"locked": True, "cluster_id": 7, "cluster_no": 1,
                               "cluster_name": "方式伴随簇", "run_id": 3})
    assert note is not None
    assert "🔒 定稿基线" in note
    assert "簇1" in note
    assert "分立复核定稿" in note
    assert "查看与导出不受限" in note
    assert "不是禁写" in note
    for state in (None, {}, {"locked": False},
                  {"locked": False, "reason": "db_unavailable"}):
        assert template_lock_note(state) is None, repr(state)


def test_template_lock_badge_constant_named():
    """标识文案沿用平台定名：🔒 前缀＋「定稿基线」。"""
    assert TEMPLATE_LOCK_BADGE == "🔒 定稿基线"


_SCHEMA = {
    "cluster_id": 7, "cluster_no": 1, "cluster_name": "方式伴随簇", "size": 2,
    "note": None,
    "schema": {"code": "MANNER", "name": "方式伴随图式", "definition": "主体以特定方式位移"},
    "schema_source": "feature_map",
    "schema_core": {"M1a": 1.0},
    "core_features": [{"code": "M1a", "label": "主体-人", "mean": 1.0,
                       "value_label": "凸显"}],
    "variable_slots": [{"code": "C1", "label": "动因", "value_type": "nominal",
                        "distribution": [{"value": 1, "label": "自移",
                                          "count": 1, "ratio": 0.5}]}],
    "members": [
        {"sense_id": 1, "lemma": "run", "sense_no": "1", "sense_label": "跑"},
        {"sense_id": 2, "lemma": "jog", "sense_no": "1", "sense_label": "慢跑"},
    ],
}

_TEMPLATE = {
    "template_text": "【图式：方式伴随图式】主体伴随方式位移；[可变槽位: 动因=自移]",
    "图式维度": {"code": "MANNER", "name": "方式伴随图式",
                 "definition": "主体以特定方式位移", "schema_source": "feature_map",
                 "cluster_id": 7, "cluster_no": 1, "cluster_name": "方式伴随簇",
                 "schema_core": {"M1a": 1.0}},
    "语义参数维度": [{"code": "M1a", "label": "主体-人", "value": 1,
                     "value_label": "凸显", "role": "core"}],
    "句法维度": {"transitivity": "不及物", "features": []},
    "对齐预留维度": {"filled": False, "aligned": None, "note": "空槽待填"},
    "oald": {"source": "OALD10", "grammar": "v.",
             "definition": "to move fast on foot"},
}

_TEMPLATE_PAGE_SCRIPT = (
    "from src.template_engine import render_template_page\n"
    "render_template_page()\n"
)


def _patch_template_page(monkeypatch, lock_state):
    """打桩模板页取数触点（范畴就绪/簇清单/母图式/实例化/锁态读面）。"""
    import src.category_study as cs
    import src.template_engine as te

    monkeypatch.setattr(cs, "category_study_ready", lambda: True)
    monkeypatch.setattr(cs, "get_categories",
                        lambda: [{"code": "RUN", "name_cn": "跑"}])
    monkeypatch.setattr(te, "derive_cluster_schemas",
                        lambda cat, lang: [json.loads(json.dumps(_SCHEMA))])
    monkeypatch.setattr(
        te, "instantiate_template",
        lambda cat, lang, sid, engine_schema=None: json.loads(json.dumps(_TEMPLATE)))
    monkeypatch.setattr(writing_db, "get_cluster_lock_state",
                        lambda cat, sid: dict(lock_state))


def test_template_page_baseline_marker_when_locked(monkeypatch):
    """AppTest：locked 词簇的模板实例化结果带「🔒 定稿基线」标识（可查看）。"""
    _patch_template_page(monkeypatch,
                         {"locked": True, "cluster_id": 7, "cluster_no": 1,
                          "cluster_name": "方式伴随簇", "run_id": 3})
    at = AppTest.from_string(_TEMPLATE_PAGE_SCRIPT, default_timeout=60)
    at.run()
    assert not at.exception
    markdown_text = "".join(str(md.value) for md in at.markdown)
    assert "🔒 定稿基线" in markdown_text
    assert "查看与导出不受限" in markdown_text
    # 实例化模板本体照常渲染（标识不替代模板、不拦查看）
    assert "【图式：方式伴随图式】" in markdown_text


def test_template_page_no_marker_when_unlocked(monkeypatch):
    """AppTest：未锁定/读面降级 → 无定稿基线标识，页面照常渲染（fail-open）。"""
    for lock_state in ({"locked": False,
                        "reason": writing_db.LOCK_REASON_NO_CLUSTER},
                       {"locked": False,
                        "reason": writing_db.LOCK_REASON_DB_UNAVAILABLE}):
        _patch_template_page(monkeypatch, lock_state)
        at = AppTest.from_string(_TEMPLATE_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        markdown_text = "".join(str(md.value) for md in at.markdown)
        assert "定稿基线" not in markdown_text
        assert "【图式：方式伴随图式】" in markdown_text  # 模板照常渲染


# ============================================
# 4. G3 展示口径对齐（词簇定名 + GUIDE 如实记载）
# ============================================

def test_g3_copy_uses_unified_cluster_term():
    """词簇定名统一（RV5-5）：新文案用「词簇」，无「词义簇/语义簇」残留。"""
    joined = f"{LOCK_BANNER_TEXT}{LOCK_BANNER_NOTE}"
    assert "词簇" in joined
    assert "词义簇" not in joined and "语义簇" not in joined


def test_guide_documents_lock_read_face_and_badge():
    """GUIDE 如实记载：锁态读面函数与顶部徽章口径（防文档漂移）。"""
    text = json.dumps(GUIDE, ensure_ascii=False)
    assert "词簇已定稿锁定" in text
    assert "get_cluster_lock_state" in text
    assert "不是禁写" in text
