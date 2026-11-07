"""writing_pages 纯逻辑层测试（批次 7 Agent U，施工规范 §10）。

页面尚未接线 app.py（集成步骤负责），故按批次 2 以来惯例只测纯逻辑
（仿 tests/test_dict_admin_pages.py）：
  * GUIDE 结构契约：四段式齐（purpose/principle/data_source/steps/notes）、
    label 以 ✍️ 前缀、steps ≥ 3、内容覆盖三 tab 与 G3/回避制锚点 ——
    集成时原样并入 PAGE_GUIDES["writing"]；
  * 角色纯函数 _can_write/_can_review：editor/dict_admin 可写、
    reviewer/dict_admin 可审、过渡 role=='admin' 兼判、fail-closed 三态；
  * sense_ref 拼装/解析、编辑目标判定（_resolve_edit_target 全分支）、
    ai_draft 快照、义位下拉排序与徽标、状态/裁决中文映射同步；
  * 转义 _esc、模块边界（不 import app —— app 分派由集成接线）。

数据相关私有查询（_list_candidate_senses/_resolve_oald_sense_id/_template_preview/
_reviewer_options/_user_display_map）以 monkeypatch 假 cursor/假数据层驱动，
本文件不连任何数据库（import 不触发连接，业务库零接触）。
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.writing_db as writing_db  # noqa: E402
from src import users_db  # noqa: E402
from src.writing_pages import (  # noqa: E402
    GUIDE,
    STATUS_BADGE_COLORS,
    STATUS_LABELS,
    VERDICT_LABELS,
    _build_ai_draft_snapshot,
    _build_sense_ref,
    _can_review,
    _can_write,
    _esc,
    _format_dt,
    _history_realname,
    _list_candidate_senses,
    _parse_sense_ref,
    _pseudonym_factory,
    _resolve_edit_target,
    _resolve_oald_sense_id,
    _reviewer_options,
    _sense_option_label,
    _sort_senses_locked_first,
    _template_preview,
    _user_display_map,
    render_writing_page,
)


# ============================================
# GUIDE 结构契约（集成并入 PAGE_GUIDES 的前提）
# ============================================

def test_guide_contract_fields():
    """四段式五键齐备且 label 以 ✍️ 前缀（施工规范 §10 契约）。"""
    assert isinstance(GUIDE, dict)
    for key in ("label", "purpose", "principle", "data_source", "steps", "notes"):
        assert key in GUIDE, f"GUIDE 缺少 {key}"
    assert GUIDE["label"].startswith("✍️")
    assert isinstance(GUIDE["purpose"], str) and GUIDE["purpose"].strip()


def test_guide_list_sections_nonempty_strings():
    """principle/data_source/steps/notes 都是非空字符串清单。"""
    for key in ("principle", "data_source", "steps", "notes"):
        section = GUIDE[key]
        assert isinstance(section, list) and section, f"GUIDE.{key} 应为非空 list"
        assert all(isinstance(item, str) and item.strip() for item in section), (
            f"GUIDE.{key} 应全为非空字符串"
        )


def test_guide_steps_at_least_three():
    """steps ≥ 3（契约硬指标）。"""
    assert len(GUIDE["steps"]) >= 3


def test_guide_covers_three_tabs_and_key_anchors():
    """步骤/说明覆盖三 tab 与状态机/回避制/G3 锚点（防模板化空文案）。"""
    joined = " ".join(GUIDE["steps"] + GUIDE["notes"] + [GUIDE["purpose"]])
    assert "撰写台" in joined
    assert "审校台" in joined
    assert "版本历史" in joined
    assert "draft" in joined and "published" in joined  # 状态机口径
    assert "回避制" in joined
    assert "locked" in joined.lower()  # G3 闸门位消费
    assert "merged" in joined  # merged 禁选口径


def test_guide_states_match_data_layer_enum():
    """GUIDE 状态机口径与 writing_db.VERSION_STATUSES 同源一致。"""
    joined = " ".join(GUIDE["principle"] + GUIDE["notes"])
    for status in writing_db.VERSION_STATUSES:
        assert status in joined or status in STATUS_LABELS, (
            f"GUIDE 未覆盖状态 {status}"
        )


# ============================================
# 角色纯函数 _can_write / _can_review（三态 + fail-closed 边界）
# ============================================

def test_can_write_no_user():
    """无 user / 非 dict 一律不可写（fail-closed）。"""
    assert _can_write(None) is False
    assert _can_write({}) is False
    assert _can_write("editor") is False
    assert _can_write(42) is False
    assert _can_write(["editor"]) is False


def test_can_write_roles():
    """editor / dict_admin 可写；过渡期 admin 兼判；sys_admin 不可写。"""
    assert _can_write({"id": 1, "role": "admin"}) is True
    assert _can_write({"id": 1, "role": "admin", "roles": []}) is True
    assert _can_write({"id": 2, "role": "viewer",
                       "roles": ["editor"]}) is True
    assert _can_write({"id": 2, "role": "reviewer",
                       "roles": ("reviewer", "dict_admin")}) is True
    assert _can_write({"id": 2, "roles": {"editor"}}) is True


def test_can_write_denied_states():
    """reviewer/annotator/viewer/sys_admin 单角色不可写；缺键不放行。"""
    assert _can_write({"id": 3, "role": "reviewer"}) is False
    assert _can_write({"id": 3, "role": "viewer",
                       "roles": ["annotator", "viewer"]}) is False
    assert _can_write({"id": 3, "roles": ["sys_admin"]}) is False
    assert _can_write({"id": 3}) is False


def test_can_review_no_user_and_fail_closed():
    """无 user / 非 dict / roles 非序列 / 大小写不符一律不可审。"""
    assert _can_review(None) is False
    assert _can_review({}) is False
    assert _can_review("reviewer") is False
    assert _can_review({"id": 4, "roles": "reviewer"}) is False   # 字符串非序列
    assert _can_review({"id": 4, "roles": ["REVIEWER"]}) is False  # 大小写敏感
    assert _can_review({"id": 4, "role": "Reviewer"}) is False
    assert _can_review({"id": 4, "roles": None}) is False


def test_can_review_roles():
    """reviewer / dict_admin 可审；过渡期 admin 兼判。"""
    assert _can_review({"id": 5, "role": "reviewer"}) is True
    assert _can_review({"id": 5, "role": "admin"}) is True
    assert _can_review({"id": 5, "role": "viewer",
                        "roles": ["reviewer"]}) is True
    assert _can_review({"id": 5, "role": "viewer",
                        "roles": ["dict_admin"]}) is True


def test_editor_alone_cannot_review():
    """editor 单角色不可自审（撰写/审校分权，回避制同源口径）。"""
    assert _can_review({"id": 6, "role": "viewer", "roles": ["editor"]}) is False


# ============================================
# R1-10 版本历史脱敏：_history_realname / _pseudonym_factory
# ============================================

def test_history_realname_roles():
    """editor/reviewer/dict_admin（含 legacy admin 映射）实名；R1-10 口径。"""
    assert _history_realname({"id": 1, "role": "admin"}) is True
    assert _history_realname({"id": 2, "role": "reviewer"}) is True
    assert _history_realname({"id": 3, "role": "viewer",
                              "roles": ["editor", "viewer"]}) is True
    assert _history_realname({"id": 4, "role": "viewer",
                              "roles": ["reviewer"]}) is True
    assert _history_realname({"id": 5, "role": "annotator",
                              "roles": ["dict_admin"]}) is True


def test_history_pseudonym_roles():
    """viewer/annotator 视角（编纂圈外）折算；sys_admin 单角色同折算（取窄）。"""
    assert _history_realname({"id": 6, "role": "viewer"}) is False
    assert _history_realname({"id": 7, "role": "viewer",
                              "roles": ["annotator", "viewer"]}) is False
    assert _history_realname({"id": 8, "role": "viewer",
                              "roles": ["viewer"]}) is False
    assert _history_realname({"id": 9, "roles": ["sys_admin"]}) is False


def test_history_realname_fail_closed():
    """未登录/非 dict → 折算（fail-closed）。"""
    for bad in (None, {}, "reviewer", 42):
        assert _history_realname(bad) is False, repr(bad)


def test_pseudonym_factory_stable_by_appearance_order():
    """「编纂员 A/B」按首次出现序稳定编号：同 id 恒同代号，跨调用可复现。"""
    who, aliases = _pseudonym_factory()
    assert who(11) == "编纂员 A"
    assert who(22) == "编纂员 B"
    assert who(11) == "编纂员 A"          # 同 id 稳定
    assert who(None) == "（系统登记）"
    assert who(None) == "（系统登记）"    # NULL 不占编号
    assert aliases == {11: "编纂员 A", 22: "编纂员 B"}
    who2, _ = _pseudonym_factory()        # 新调用从 A 重新起编（按出现序）
    assert who2(33) == "编纂员 A"


def test_pseudonym_factory_beyond_z():
    """超过 26 人不炸不重号：第 27 人起 A2/B2/… 续编。"""
    who, _ = _pseudonym_factory()
    letters = [who(i + 1) for i in range(27)]
    assert letters[0] == "编纂员 A"
    assert letters[25] == "编纂员 Z"
    assert letters[26] == "编纂员 A2"
    assert len(set(letters)) == 27


# ============================================
# HTML 转义与展示映射同步
# ============================================

def test_esc_escapes_markup_quotes_and_ampersand():
    assert _esc("<b>&") == "&lt;b&gt;&amp;"
    assert _esc('a"b') == "a&quot;b"
    assert _esc("a'b") == "a&#x27;b"
    assert _esc("普通中文") == "普通中文"


def test_esc_stringifies_non_str_values():
    assert _esc(123) == "123"
    assert _esc(None) == "None"
    assert _esc("<img src=x>") == "&lt;img src=x&gt;"


def test_status_labels_cover_all_statuses():
    """状态中文映射与数据层枚举一一对应（徽章渲染不漏态）。"""
    assert set(STATUS_LABELS) == set(writing_db.VERSION_STATUSES)
    assert set(STATUS_BADGE_COLORS) == set(writing_db.VERSION_STATUSES)
    assert set(VERDICT_LABELS) == set(writing_db.VERDICTS)


# ============================================
# sense_ref 拼装/解析（三段式口径）
# ============================================

def test_build_and_parse_sense_ref_roundtrip():
    ref = _build_sense_ref("motion", 12, 345)
    assert ref == "motion:12:345"
    assert _parse_sense_ref(ref) == ("motion", 12, 345)


def test_build_sense_ref_zero_placeholders():
    """0 占位口径：cs 锚缺失 / OALD 锚未解析。"""
    assert _build_sense_ref("motion", 0, 345) == "motion:0:345"
    assert _build_sense_ref("RUN", 7, 0) == "RUN:7:0"


def test_build_sense_ref_rejects_bad_inputs():
    """空范畴 / 负数 / 非数字 id / None 一律 None。"""
    assert _build_sense_ref("", 1, 1) is None
    assert _build_sense_ref(None, 1, 1) is None
    assert _build_sense_ref("motion", -1, 1) is None
    assert _build_sense_ref("motion", 1, -1) is None
    assert _build_sense_ref("motion", None, 1) is None
    assert _build_sense_ref("motion", "x", 1) is None


def test_parse_sense_ref_rejects_bad_formats():
    assert _parse_sense_ref("bad") is None
    assert _parse_sense_ref("motion:12") is None
    assert _parse_sense_ref(None) is None
    assert _parse_sense_ref(123) is None


def test_format_dt():
    from datetime import datetime

    assert _format_dt(datetime(2026, 11, 7, 9, 30)) == "2026-11-07 09:30"
    assert _format_dt(None) == "—"
    assert _format_dt("脏值") == "脏值"


# ============================================
# 编辑目标判定 _resolve_edit_target（撰写台状态机视图层，全分支）
# ============================================

def test_edit_target_no_version():
    """无任何版本 → create（全新首版，无 notice）。"""
    target = _resolve_edit_target(None, 9)
    assert target["mode"] == "create"
    assert target["target_id"] is None
    assert target["expect_version"] is None
    assert target["prefill"] == ""
    assert target["based_on_version"] is None
    assert target["notice"] is None


def test_edit_target_own_draft_updates_with_optimistic_lock():
    """自有 draft → update（target_id/expect_version 定位，预填内容）。"""
    latest = {"id": 10, "version": 2, "status": "draft", "author_id": 9,
              "content": "我的草稿"}
    target = _resolve_edit_target(latest, 9)
    assert target["mode"] == "update"
    assert target["target_id"] == 10
    assert target["expect_version"] == 2
    assert target["prefill"] == "我的草稿"
    assert target["notice"] is None


def test_edit_target_others_draft_starts_new():
    """他人 draft → create 空起（不读入他人未定稿），notice 提示在途。"""
    latest = {"id": 11, "version": 3, "status": "draft", "author_id": 8,
              "content": "别人的草稿"}
    target = _resolve_edit_target(latest, 9)
    assert target["mode"] == "create"
    assert target["prefill"] == ""
    assert target["based_on_version"] is None
    assert "在途" in target["notice"]


def test_edit_target_missing_author_fail_closed():
    """author_id 缺失（系统登记行）按非本人处理：不进乐观锁更新路径。"""
    latest = {"id": 12, "version": 1, "status": "draft", "author_id": None,
              "content": "系统登记"}
    target = _resolve_edit_target(latest, 9)
    assert target["mode"] == "create"


def test_edit_target_rejected_prefills_with_based_on():
    """rejected → create 预填被拒内容，based_on_version=被拒版号（重提链）。"""
    latest = {"id": 13, "version": 3, "status": "rejected", "author_id": 9,
              "content": "被拒的稿子"}
    target = _resolve_edit_target(latest, 9)
    assert target["mode"] == "create"
    assert target["prefill"] == "被拒的稿子"
    assert target["based_on_version"] == 3
    assert "打回" in target["notice"]
    assert "v4" in target["notice"]  # version+1 口径预告


def test_edit_target_in_flight_states_start_new():
    """in_review/final/published 等在途/已定态 → create 空起并提示。"""
    for status in ("in_review", "reviewed", "revised", "approved",
                   "final", "published"):
        latest = {"id": 14, "version": 5, "status": status, "author_id": 9,
                  "content": "已流转"}
        target = _resolve_edit_target(latest, 9)
        assert target["mode"] == "create", status
        assert target["prefill"] == "", status
        assert target["based_on_version"] is None, status
        assert target["notice"], status


# ============================================
# AI/模板草稿快照（审校对照数据面）
# ============================================

def test_ai_draft_snapshot_from_template():
    template = {
        "template_text": "【图式：方式伴随图式】…",
        "图式维度": {"name": "方式伴随图式", "code": "MANNER", "cluster_no": 3},
        "oald": {"source": "OALD10", "definition": "to move fast on foot"},
        "句法维度": {"transitivity": "不及物"},
        "语义参数维度": [{"code": "P1"}, {"code": "M1a"}],
    }
    snap = _build_ai_draft_snapshot(template)
    assert snap["kind"] == "template_preview"
    assert snap["generated_by"] == "template_engine"
    assert snap["template_text"].startswith("【图式")
    assert snap["schema_name"] == "方式伴随图式"
    assert snap["oald_source"] == "OALD10"
    assert snap["n_semantic_params"] == 2


def test_ai_draft_snapshot_tolerates_missing_keys():
    """缺键/空模板尽力取值（None 填充），非 dict 返回 None。"""
    snap = _build_ai_draft_snapshot({"template_text": "只有文本"})
    assert snap["template_text"] == "只有文本"
    assert snap["schema_name"] is None
    assert _build_ai_draft_snapshot({})["generated_by"] == "template_engine"
    assert _build_ai_draft_snapshot(None) is None
    assert _build_ai_draft_snapshot("不是模板") is None
    assert _build_ai_draft_snapshot(42) is None


# ============================================
# 义位下拉：locked 簇优先排序与徽标（G3 消费口径）
# ============================================

def _sense(cs_id, lemma="run", sense_no="1", label="足部奔跑义", status="目标",
           cluster_id=None, cluster_no=None, locked=None):
    return {
        "cs_sense_id": cs_id, "lemma": lemma, "sense_no": sense_no,
        "sense_label": label, "status": status,
        "cluster_id": cluster_id, "cluster_no": cluster_no, "locked": locked,
    }


def test_sort_senses_locked_first():
    """locked 簇 → 未锁定簇 → 未入簇；同组内 lemma 稳定排序。"""
    senses = [
        _sense(4, lemma="walk", cluster_id=9, cluster_no=2, locked=0),
        _sense(1, lemma="run", cluster_id=7, cluster_no=1, locked=1),
        _sense(3, lemma="sprint"),
        _sense(2, lemma="jog", cluster_id=8, cluster_no=3, locked=0),
    ]
    order = [s["cs_sense_id"] for s in _sort_senses_locked_first(senses)]
    assert order == [1, 2, 4, 3]  # locked(1) → 未锁定按 lemma(jog, walk) → 未入簇


def test_sense_option_label_badges():
    """徽标如实标注：🔒 已锁定 / ⚠️ 未锁定 / ⚠️ 未入簇。"""
    locked = _sense(1, cluster_id=7, cluster_no=1, locked=1)
    assert "🔒" in _sense_option_label(locked)
    assert "G3 已锁定" in _sense_option_label(locked)
    unlocked = _sense(2, cluster_id=8, cluster_no=3, locked=0)
    assert "⚠️" in _sense_option_label(unlocked)
    assert "未锁定" in _sense_option_label(unlocked)
    lonely = _sense(3)
    assert "未入簇" in _sense_option_label(lonely)
    assert "run 1「足部奔跑义」" in _sense_option_label(locked)


def test_sense_option_label_tolerates_missing_fields():
    bare = _sense(5, lemma=None, sense_no=None, label=None, status=None)
    text = _sense_option_label(bare)
    assert "—" in text  # 缺字段给占位符，不崩


# ============================================
# 私有只读查询（monkeypatch 假 cursor / 假数据层，零真实数据库）
# ============================================

class _FakeCursor:
    """假 DictCursor：execute 记录参数，fetchall/fetchone 吐预置结果。"""

    def __init__(self, rows=None, row=None, error=None):
        self._rows = rows or []
        self._row = row
        self._error = error
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._error is not None:
            raise self._error

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_list_candidate_senses_dedupes_preferring_locked(monkeypatch):
    """跨运行重复归属去重保 locked 行；invalid 入参直接 []。"""
    rows = [
        {"cs_sense_id": 1, "lemma": "run", "sense_no": "1",
         "sense_label": "跑", "status": "目标", "category_code": "RUN",
         "category_name": "跑", "cluster_id": 7, "cluster_no": 1, "locked": 0},
        {"cs_sense_id": 1, "lemma": "run", "sense_no": "1",
         "sense_label": "跑", "status": "目标", "category_code": "RUN",
         "category_name": "跑", "cluster_id": 9, "cluster_no": 1, "locked": 1},
        {"cs_sense_id": 2, "lemma": "jog", "sense_no": "1",
         "sense_label": "慢跑", "status": "保留", "category_code": "RUN",
         "category_name": "跑", "cluster_id": None, "cluster_no": None,
         "locked": None},
    ]
    monkeypatch.setattr(
        "src.writing_pages.get_db_cursor",
        lambda autocommit=True: _FakeCursor(rows=rows),
    )
    senses = _list_candidate_senses("RUN", "en")
    assert [s["cs_sense_id"] for s in senses] == [1, 2]
    assert senses[0]["locked"] == 1  # 去重保留 locked 行
    assert _list_candidate_senses("", "en") == []
    assert _list_candidate_senses("RUN", "fr") == []
    assert _list_candidate_senses(None, "en") == []


def test_list_candidate_senses_db_failure_degrades(monkeypatch):
    """库异常折叠为 []（降级不崩，页面给占位提示）。"""
    monkeypatch.setattr(
        "src.writing_pages.get_db_cursor",
        lambda autocommit=True: _FakeCursor(error=RuntimeError("db down")),
    )
    assert _list_candidate_senses("RUN", "en") == []


def test_resolve_oald_sense_id(monkeypatch):
    """cs→oald 锚解析：命中返 id；未命中/非数字 sense_no/库异常 → 0 占位。"""
    monkeypatch.setattr(
        "src.writing_pages.get_db_cursor",
        lambda autocommit=True: _FakeCursor(row={"id": 345}),
    )
    assert _resolve_oald_sense_id("run", "1") == 345
    # 汉语侧 ①②/— 或空值：非纯数字直接 0（不打库）
    called = []

    def _no_call(autocommit=True):
        called.append(1)
        return _FakeCursor(row={"id": 345})

    monkeypatch.setattr("src.writing_pages.get_db_cursor", _no_call)
    assert _resolve_oald_sense_id("跑", "①") == 0
    assert _resolve_oald_sense_id("跑", "—") == 0
    assert _resolve_oald_sense_id("run", "") == 0
    assert _resolve_oald_sense_id(None, None) == 0
    assert not called  # 未触库

    monkeypatch.setattr(
        "src.writing_pages.get_db_cursor",
        lambda autocommit=True: _FakeCursor(row=None),
    )
    assert _resolve_oald_sense_id("run", "9") == 0  # 未命中
    monkeypatch.setattr(
        "src.writing_pages.get_db_cursor",
        lambda autocommit=True: _FakeCursor(error=RuntimeError("db down")),
    )
    assert _resolve_oald_sense_id("run", "1") == 0  # 库异常 → 0 占位


def test_template_preview_lazy_and_tolerant(monkeypatch):
    """模板预览：引擎结果透传；异常/缺失折叠为 None（占位容错口径）。"""
    import src.template_engine as te

    monkeypatch.setattr(te, "instantiate_template",
                        lambda c, lang, s: {"template_text": "T"})
    assert _template_preview("RUN", "en", 1) == {"template_text": "T"}

    def _boom(c, lang, s):
        raise RuntimeError("pack missing")

    monkeypatch.setattr(te, "instantiate_template", _boom)
    assert _template_preview("RUN", "en", 1) is None
    monkeypatch.setattr(te, "instantiate_template",
                        lambda c, lang, s: None)
    assert _template_preview("RUN", "en", 1) is None


def test_user_display_map(monkeypatch):
    monkeypatch.setattr(
        users_db, "list_users",
        lambda: [
            {"id": 1, "username": "admin", "display_name": "内置管理员"},
            {"id": 2, "username": "rev", "display_name": ""},
            {"id": None, "username": "ghost", "display_name": "无 id"},
        ],
    )
    mapping = _user_display_map()
    assert mapping[1] == "内置管理员"
    assert mapping[2] == "rev"  # 空展示名回退 username
    assert None not in mapping


def test_reviewer_options_filters_self_inactive_and_roles(monkeypatch):
    """审校人清单：去本人、去停用、去无 reviewer/dict_admin 角色者。"""
    monkeypatch.setattr(
        users_db, "list_users",
        lambda: [
            {"id": 9, "username": "me", "display_name": "我", "active": 1},
            {"id": 2, "username": "rev", "display_name": "审校甲", "active": 1},
            {"id": 3, "username": "off", "display_name": "停用人", "active": 0},
            {"id": 4, "username": "ed", "display_name": "编纂乙", "active": 1},
            {"id": 5, "username": "chief", "display_name": "主编", "active": 1},
        ],
    )

    def _fake_roles(uid):
        return {
            9: ["editor", "dict_admin"],   # 本人（虽有权也排除）
            2: ["reviewer"],
            3: ["reviewer"],               # 停用：上面已滤
            4: ["editor"],                 # 无审校角色
            5: ["dict_admin"],
        }[uid]

    monkeypatch.setattr(users_db, "list_roles", _fake_roles)
    options = _reviewer_options({"id": 9})
    ids = [o["id"] for o in options]
    assert ids == [2, 5]  # 9 本人排除、3 停用排除、4 无角色排除


def test_reviewer_options_role_lookup_failure_skips_user(monkeypatch):
    """单人角色查询异常跳过该人，不拖垮清单；全失败降级为空。"""
    monkeypatch.setattr(
        users_db, "list_users",
        lambda: [
            {"id": 2, "username": "rev", "display_name": "审校甲", "active": 1},
            {"id": 5, "username": "chief", "display_name": "主编", "active": 1},
        ],
    )

    def _flaky(uid):
        if uid == 2:
            raise RuntimeError("db hiccup")
        return ["reviewer"]

    monkeypatch.setattr(users_db, "list_roles", _flaky)
    assert [o["id"] for o in _reviewer_options({"id": 1})] == [5]

    def _boom(uid):
        raise RuntimeError("db down")

    monkeypatch.setattr(users_db, "list_roles", _boom)
    assert _reviewer_options({"id": 1}) == []


# ============================================
# 模块边界（集成前契约）
# ============================================

def test_render_writing_page_exists():
    """入口函数存在且可调用（接线由集成步骤负责，本文件不做 AppTest）。"""
    assert callable(render_writing_page)


def test_module_does_not_import_app():
    """契约「勿 import app」：页面模块不得引用 src.app（分派归集成）。"""
    import inspect

    import src.writing_pages as wp

    source = inspect.getsource(wp)
    assert "from src.app" not in source
    assert "from src import app" not in source
    assert "import src.app" not in source
