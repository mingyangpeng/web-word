"""批次 19 用户上下文域 UI 落地测试（FX-37）。

三块 UI 的行为契约，全部不依赖真库（数据层 monkeypatch ＋ st 桩）：

  * user_context_db 补读面：get_note / get_profile / get_bookmark 单条
    直读（入参校验先于 DB、fail-closed 返回 None、SQL 恒带 user_id 的
    own-rows-only）＋ list_* 的 LIMIT 加固（RV16-4：默认 500 参数化传参，
    调用方可传，非法回退默认）—— FakeCursor 捕 SQL/params 断言；
  * 义项脊柱「📝 我的笔记」段与「📌 书签」toggle（src/sense_spine.py）：
    未登录段/钮不渲染（上下文域是登录态功能，fail-closed 的 UI 表达）；
    笔记 CRUD 两态（保存/清空/删除/失败），'' 提交=显式清空（RV2-3 第 3
    类口径）；书签 toggle 两态（收藏/取消）；成功一律 ui_kit.flash +
    rerun（RV12 纪律，st.success 回潮反向断言）；
  * 账号管理页「⚙️ 我的偏好」段（src/users_admin_page.py）：未登录不渲染、
    预置两键读写、自定义键增删、空白=未设值（RV2-3 第 2 类）、flash+rerun。

st 桩为最小假体（FX-30 _StubSt 同款思路扩展）：记录调用供断言，
form_submit_button / button / 文本输入由预设驱动。
"""

import inspect
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ui_kit, user_context_db  # noqa: E402
from src import sense_spine as spine  # noqa: E402
from src import users_admin_page as ua  # noqa: E402
from src.sense_spine import SpineSection, render_sense_spine  # noqa: E402
from src.user_context_db import (  # noqa: E402
    DEFAULT_LIST_LIMIT,
    MAX_NOTE_LEN,
    get_bookmark,
    get_note,
    get_profile,
    list_bookmarks,
    list_drafts,
    list_notes,
    list_profiles,
    list_states,
)

UID = 101
SENSE_ID = 7

_ME = {"id": UID, "username": "fx37", "display_name": "FX37 用户"}


# ============================================
# 假体：DB 游标 ＋ st
# ============================================

class _FakeCursor:
    """get_db_cursor 上下文假体：记录 SQL/params，fetch 按预设行返回。"""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.sqls = []
        self.params_list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.sqls.append(sql)
        self.params_list.append(params)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _BoomCursor:
    """一触即炸的游标（降级路径用；记录调用次数供零访问断言）。"""

    def __init__(self):
        self.calls = 0

    def __enter__(self):
        self.calls += 1
        raise pymysql.Error("db down")

    def __exit__(self, *exc):
        return False


class _StubSt:
    """st 假体（FX-30 _StubSt 同款最小件）：记录调用，submit/button/文本
    输入由预设驱动；successes 记录专供 RV12 反向断言（新代码永不回潮）。"""

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def __init__(self, *, submit_label=None, button_label=None,
                 text_values=None, select_value=None):
        self.markdowns, self.captions = [], []
        self.errors, self.infos, self.warnings, self.successes = [], [], [], []
        self.buttons, self.text_widgets, self.selects, self.forms = [], [], [], []
        self.rerun_count = 0
        self.session_state = {}
        self._submit_label = submit_label
        self._button_label = button_label
        self._text_values = dict(text_values or {})
        self._select_value = select_value

    def markdown(self, text, **kw):
        self.markdowns.append(text)

    def caption(self, text):
        self.captions.append(text)

    def error(self, text):
        self.errors.append(text)

    def info(self, text):
        self.infos.append(text)

    def warning(self, text):
        self.warnings.append(text)

    def success(self, text):
        self.successes.append(text)

    def button(self, label, **kw):
        self.buttons.append(label)
        return self._button_label is not None and label == self._button_label

    def text_area(self, label, value="", **kw):
        self.text_widgets.append(("text_area", label, value, kw))
        return self._text_values.get(kw.get("key"), value)

    def text_input(self, label, value="", **kw):
        self.text_widgets.append(("text_input", label, value, kw))
        return self._text_values.get(kw.get("key"), value)

    def selectbox(self, label, options, **kw):
        self.selects.append((label, list(options)))
        if self._select_value in options:
            return self._select_value
        return options[0] if options else None

    def columns(self, n):
        return [self._Ctx() for _ in range(n)]

    def form(self, key=None, **kw):
        self.forms.append(key)
        return self._Ctx()

    def form_submit_button(self, label, **kw):
        return self._submit_label is not None and label == self._submit_label

    def rerun(self):
        self.rerun_count += 1


# ============================================
# 公共件：登录/打桩/flash 记录
# ============================================

def _install_flash_recorder(monkeypatch) -> list:
    """ui_kit.flash → 记录器（返回 messages 列表供断言）。"""
    flashes: list = []
    monkeypatch.setattr(ui_kit, "flash",
                        lambda msg, level="success": flashes.append(msg))
    return flashes


def _login_spine(monkeypatch, uid=UID):
    """脊柱会话门 → 已登录（直接钉 _context_uid，即数据层 _resolve_user_id
    在 spine 命名空间的引用）。"""
    monkeypatch.setattr(spine, "_context_uid", lambda: uid)


def _no_login_spine(monkeypatch):
    monkeypatch.setattr(spine, "_context_uid", lambda: None)


def _login_ucdb(monkeypatch, uid=UID):
    """数据层会话 → 指定用户（fx31 同款：ucdb.current_user 模块级引用）。"""
    monkeypatch.setattr(user_context_db, "current_user",
                        lambda: {"id": uid, "username": "fx37"})


def _sentinel_on(monkeypatch):
    """建表哨兵置位（ensure 直通，单测不触 DDL 路径）。"""
    monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)


def _stub_sections(monkeypatch):
    """_spine_sections → 7 段桩（集成测试只看外围控件接线与次序）。"""
    monkeypatch.setattr(
        spine, "_spine_sections",
        lambda *a, **k: [SpineSection(f"第{i}段", f"正文{i}", "")
                         for i in range(1, 8)],
    )


# ============================================
# 1. user_context_db 补读面（单条直读 + LIMIT 加固）
# ============================================

class TestSingleGetters:
    """get_note / get_profile / get_bookmark：校验先拒、fail-closed、
    own-rows-only（SQL 恒带 user_id）。"""

    # ---- 未登录 fail-closed：零 DB 访问 ----

    def _no_login_boom(self, monkeypatch):
        boom = _BoomCursor()
        monkeypatch.setattr(user_context_db, "current_user", lambda: None)
        monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        return boom

    def test_get_note_no_login_zero_db(self, monkeypatch):
        boom = self._no_login_boom(monkeypatch)
        assert get_note(SENSE_ID) is None
        assert boom.calls == 0

    def test_get_profile_no_login_zero_db(self, monkeypatch):
        boom = self._no_login_boom(monkeypatch)
        assert get_profile("ui.default_category") is None
        assert boom.calls == 0

    def test_get_bookmark_no_login_zero_db(self, monkeypatch):
        boom = self._no_login_boom(monkeypatch)
        assert get_bookmark("sense", str(SENSE_ID)) is None
        assert boom.calls == 0

    # ---- 入参校验先拒（零 DB 访问）----

    @pytest.mark.parametrize("bad_sid", [None, "abc", 0, -1, True])
    def test_get_note_bad_sense_id_no_db(self, monkeypatch, bad_sid):
        boom = _BoomCursor()
        _login_ucdb(monkeypatch)
        monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        assert get_note(bad_sid) is None
        assert boom.calls == 0

    @pytest.mark.parametrize("bad_key", [None, 123, "", "   ", "k" * 121])
    def test_get_profile_bad_key_no_db(self, monkeypatch, bad_key):
        boom = _BoomCursor()
        _login_ucdb(monkeypatch)
        monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        assert get_profile(bad_key) is None
        assert boom.calls == 0

    @pytest.mark.parametrize("anchor_type, anchor_id", [
        ("menu", "7"),          # 白名单外
        ("sense", 7),           # 非 str
        ("sense", ""),          # 空串
        ("sense", "   "),       # 空白串
        ("sense", "a" * 121),   # 超列宽
    ])
    def test_get_bookmark_bad_anchor_no_db(self, monkeypatch, anchor_type,
                                           anchor_id):
        boom = _BoomCursor()
        _login_ucdb(monkeypatch)
        monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        assert get_bookmark(anchor_type, anchor_id) is None
        assert boom.calls == 0

    # ---- 成功路径：单条 SQL、own-rows-only、返回 dict ----

    def _logged_fake_cursor(self, monkeypatch, rows):
        fake = _FakeCursor(rows)
        _login_ucdb(monkeypatch)
        _sentinel_on(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: fake)
        return fake

    def test_get_note_success_single_row_sql(self, monkeypatch):
        row = {"id": 1, "sense_id": SENSE_ID, "note": "动词意象图式：路径类",
               "created_at": "2026-11-10 08:00:00",
               "updated_at": "2026-11-10 09:00:00"}
        fake = self._logged_fake_cursor(monkeypatch, [row])
        assert get_note(SENSE_ID) == row
        sql = fake.sqls[0]
        assert "FROM user_notes" in sql
        assert "WHERE user_id = %s AND sense_id = %s LIMIT 1" in sql
        assert fake.params_list[0] == (UID, SENSE_ID)

    def test_get_note_missing_row_returns_none(self, monkeypatch):
        self._logged_fake_cursor(monkeypatch, [])
        assert get_note(SENSE_ID) is None
        # 显式清空行（note=''）也返回该行 —— 「无行」与「空行」由 note 值区分
        self._logged_fake_cursor(
            monkeypatch, [{"id": 2, "sense_id": SENSE_ID, "note": "",
                           "created_at": None, "updated_at": None}])
        got = get_note(SENSE_ID)
        assert got is not None and got["note"] == ""

    def test_get_profile_success_sql(self, monkeypatch):
        row = {"id": 3, "pref_key": "ui.default_category",
               "pref_value": "motion", "created_at": None, "updated_at": None}
        fake = self._logged_fake_cursor(monkeypatch, [row])
        assert get_profile("ui.default_category") == row
        sql = fake.sqls[0]
        assert "FROM user_profiles" in sql
        assert "WHERE user_id = %s AND pref_key = %s LIMIT 1" in sql
        assert fake.params_list[0] == (UID, "ui.default_category")

    def test_get_profile_null_value_row_kept(self, monkeypatch):
        """键在值空（RV2-3 第 2 类）返回含 None 值的行，与「无键」区分。"""
        row = {"id": 4, "pref_key": "ui.rows_per_page", "pref_value": None,
               "created_at": None, "updated_at": None}
        self._logged_fake_cursor(monkeypatch, [row])
        got = get_profile("ui.rows_per_page")
        assert got is not None and got["pref_value"] is None

    def test_get_bookmark_success_sql(self, monkeypatch):
        row = {"id": 5, "anchor_type": "sense", "anchor_id": str(SENSE_ID),
               "title": "run · S1（#7）", "note": None,
               "created_at": None, "updated_at": None}
        fake = self._logged_fake_cursor(monkeypatch, [row])
        assert get_bookmark("sense", str(SENSE_ID)) == row
        sql = " ".join(fake.sqls[0].split())
        assert ("FROM user_bookmarks WHERE user_id = %s "
                "AND anchor_type = %s AND anchor_id = %s LIMIT 1") in sql
        assert fake.params_list[0] == (UID, "sense", str(SENSE_ID))

    # ---- 库不可用降级：None（不抛）----

    def _logged_boom(self, monkeypatch):
        boom = _BoomCursor()
        _login_ucdb(monkeypatch)
        monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        return boom

    def test_getters_degrade_to_none_on_db_down(self, monkeypatch):
        self._logged_boom(monkeypatch)
        assert get_note(SENSE_ID) is None
        assert get_profile("ui.default_category") is None
        assert get_bookmark("sense", str(SENSE_ID)) is None

    def test_spine_gate_is_data_layer_single_implementation(self):
        """UI 会话门 = user_context_db._resolve_user_id（单一实现点，无第二套判定）。"""
        assert spine._context_uid is user_context_db._resolve_user_id


class TestListLimitHardening:
    """list_* 的 LIMIT 加固（RV16-4 留档项消缺）：默认 500、参数化传参、
    调用方可传、非法回退默认。"""

    def _capturing_cursor(self, monkeypatch):
        fake = _FakeCursor([])
        _login_ucdb(monkeypatch)
        _sentinel_on(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: fake)
        return fake

    @pytest.mark.parametrize("list_fn", [list_profiles, list_states,
                                         list_bookmarks, list_notes,
                                         list_drafts])
    def test_all_lists_default_limit_500(self, monkeypatch, list_fn):
        fake = self._capturing_cursor(monkeypatch)
        list_fn()
        assert "LIMIT %s" in fake.sqls[0]
        assert fake.params_list[0][-1] == DEFAULT_LIST_LIMIT == 500

    @pytest.mark.parametrize("list_fn", [list_profiles, list_states,
                                         list_bookmarks, list_notes,
                                         list_drafts])
    def test_caller_can_pass_limit(self, monkeypatch, list_fn):
        fake = self._capturing_cursor(monkeypatch)
        list_fn(limit=20)
        assert fake.params_list[0][-1] == 20

    @pytest.mark.parametrize("bad_limit", [0, -1, True, False, "x", None,
                                           10001])
    def test_invalid_limit_falls_back_to_default(self, monkeypatch, bad_limit):
        fake = self._capturing_cursor(monkeypatch)
        list_profiles(limit=bad_limit)
        assert fake.params_list[0][-1] == DEFAULT_LIST_LIMIT

    def test_limit_is_parameterized_not_inlined(self, monkeypatch):
        """LIMIT 走占位符，limit 值绝不拼进 SQL 文本（注入面收口）。"""
        fake = self._capturing_cursor(monkeypatch)
        list_notes(limit=20)
        assert "LIMIT 20" not in fake.sqls[0]
        assert "LIMIT %s" in fake.sqls[0]


# ============================================
# 2. 义项脊柱：📝 我的笔记段 ＋ 📌 书签 toggle
# ============================================

class TestNotesSection:
    """📝 我的笔记（登录态专属；'' 提交=显式清空；RV12 flash+rerun）。"""

    def test_no_login_section_not_rendered(self, monkeypatch):
        """未登录整段不渲染（登录态功能 fail-closed 的 UI 表达），零数据层调用。"""
        _no_login_spine(monkeypatch)
        exploded = []

        def _explode(*a, **k):
            exploded.append(1)
            raise AssertionError("未登录不应触碰数据层")

        monkeypatch.setattr(user_context_db, "get_note", _explode)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        assert not exploded
        assert stub.forms == [] and stub.text_widgets == []
        assert not any("我的笔记" in m for m in stub.markdowns)

    def test_logged_in_no_note_renders_empty_editor(self, monkeypatch):
        _login_spine(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_note", lambda sid: None)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        assert any("📝 我的笔记" in m for m in stub.markdowns)
        assert stub.forms == [f"sense_spine_note_form_{SENSE_ID}"]
        kind, label, value, kw = stub.text_widgets[0]
        assert kind == "text_area"
        assert value == ""                      # 无笔记 → 空编辑框
        assert kw["max_chars"] == MAX_NOTE_LEN  # 应用层长度闸前置
        assert kw["key"] == f"sense_spine_note_input_{SENSE_ID}"
        assert not any("最近更新" in c for c in stub.captions)

    def test_logged_in_existing_note_shown_with_timestamp(self, monkeypatch):
        row = {"id": 1, "sense_id": SENSE_ID, "note": "注意与 arrive 的差异",
               "created_at": None, "updated_at": "2026-11-10 09:00:00"}
        _login_spine(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_note", lambda sid: row)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        assert stub.text_widgets[0][2] == "注意与 arrive 的差异"  # 编辑框预填
        assert any("注意与 arrive 的差异" in m for m in stub.markdowns)
        assert any("2026-11-10 09:00:00" in c for c in stub.captions)

    def test_empty_note_row_explicit_clear_caption(self, monkeypatch):
        """note=''（显式清空但保留行，RV2-3 第 3 类）→ 编辑框空＋口径说明。"""
        row = {"id": 1, "sense_id": SENSE_ID, "note": "",
               "created_at": None, "updated_at": "2026-11-10 09:00:00"}
        _login_spine(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_note", lambda sid: row)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        assert stub.text_widgets[0][2] == ""
        assert any("显式清空" in c for c in stub.captions)

    def _save_scenario(self, monkeypatch, note_text, upsert=None, note_row=None):
        flashes = _install_flash_recorder(monkeypatch)
        ups, dels = [], []
        monkeypatch.setattr(
            user_context_db, "upsert_note",
            upsert or (lambda sid, text: ups.append((sid, text)) or True))
        monkeypatch.setattr(user_context_db, "delete_note",
                            lambda sid: dels.append(sid) or True)
        monkeypatch.setattr(user_context_db, "get_note",
                            lambda sid: note_row)
        _login_spine(monkeypatch)
        stub = _StubSt(submit_label="💾 保存笔记", text_values={
            f"sense_spine_note_input_{SENSE_ID}": note_text})
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        return stub, ups, dels, flashes

    def test_save_calls_upsert_flash_rerun(self, monkeypatch):
        stub, ups, dels, flashes = self._save_scenario(
            monkeypatch, "动词意象图式：路径类", note_row=None)
        assert ups == [(SENSE_ID, "动词意象图式：路径类")]
        assert dels == []
        assert flashes == ["笔记已保存（私人，跨设备续接）。"]
        assert stub.rerun_count == 1
        assert stub.errors == []

    def test_save_empty_string_is_explicit_clear(self, monkeypatch):
        """清空提交：upsert_note(sense_id, '') 原样落库（RV2-3 第 3 类口径），
        不是删除也不是拒绝。"""
        row = {"id": 1, "sense_id": SENSE_ID, "note": "旧笔记",
               "created_at": None, "updated_at": None}
        stub, ups, dels, _ = self._save_scenario(
            monkeypatch, "", note_row=row)
        assert ups == [(SENSE_ID, "")]
        assert dels == []          # 清空 ≠ 删除行
        assert stub.rerun_count == 1

    def test_save_failure_error_no_rerun(self, monkeypatch):
        stub, ups, dels, flashes = self._save_scenario(
            monkeypatch, "x", upsert=lambda sid, text: False)
        assert ups == []
        assert flashes == []
        assert stub.rerun_count == 0
        assert stub.errors

    def test_delete_calls_delete_flash_rerun(self, monkeypatch):
        flashes = _install_flash_recorder(monkeypatch)
        dels = []
        monkeypatch.setattr(user_context_db, "delete_note",
                            lambda sid: dels.append(sid) or True)
        row = {"id": 1, "sense_id": SENSE_ID, "note": "旧笔记",
               "created_at": None, "updated_at": None}
        monkeypatch.setattr(user_context_db, "get_note", lambda sid: row)
        _login_spine(monkeypatch)
        stub = _StubSt(submit_label="🗑 删除笔记")
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        assert dels == [SENSE_ID]
        assert flashes == ["已删除该义位的私人笔记。"]
        assert stub.rerun_count == 1
        # 编辑框会话态同步清掉（删除后不残留旧文，防误存回）
        assert f"sense_spine_note_input_{SENSE_ID}" not in stub.session_state

    def test_delete_with_no_row_no_db_call(self, monkeypatch):
        _install_flash_recorder(monkeypatch)
        exploded = []

        def _boom(sid):
            exploded.append(sid)
            return True

        monkeypatch.setattr(user_context_db, "delete_note", _boom)
        monkeypatch.setattr(user_context_db, "get_note", lambda sid: None)
        _login_spine(monkeypatch)
        stub = _StubSt(submit_label="🗑 删除笔记")
        monkeypatch.setattr(spine, "st", stub)
        spine._render_my_notes_section(SENSE_ID)
        assert not exploded       # 无行提示，不触库
        assert stub.infos
        assert stub.rerun_count == 0

    def test_rv12_no_st_success_in_new_code(self):
        """RV12 纪律：新 UI 代码零 st.success 调用（成功提示一律 ui_kit.flash；
        断言调用位 st.success( ，docstring 的纪律注记不误伤）。"""
        source = inspect.getsource(spine)
        assert "st.success(" not in source
        assert "ui_kit.flash" in source


class TestBookmarkToggle:
    """📌 书签 toggle 两态（get_bookmark 单条直读判态；收藏/取消）。"""

    _ON = "📌 收藏本义位"
    _OFF = "📍 已收藏·取消"

    def test_no_login_no_button(self, monkeypatch):
        _no_login_spine(monkeypatch)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert stub.buttons == []

    def test_not_bookmarked_renders_collect_button(self, monkeypatch):
        _login_spine(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_bookmark",
                            lambda t, i: None)
        monkeypatch.setattr(spine, "_fetch_sense_row",
                            lambda sid: {"verb": "run", "sense_index": "1"})
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert stub.buttons == [self._ON]

    def test_bookmarked_renders_cancel_button(self, monkeypatch):
        _login_spine(monkeypatch)
        monkeypatch.setattr(
            user_context_db, "get_bookmark",
            lambda t, i: {"id": 5, "anchor_type": t, "anchor_id": i,
                          "title": "run · S1（#7）", "note": None,
                          "created_at": None, "updated_at": None})
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert stub.buttons == [self._OFF]

    def test_collect_click_upserts_with_title_flash_rerun(self, monkeypatch):
        flashes = _install_flash_recorder(monkeypatch)
        ups, dels = [], []
        monkeypatch.setattr(
            user_context_db, "upsert_bookmark",
            lambda t, i, title=None, note=None:
                ups.append((t, i, title, note)) or True)
        monkeypatch.setattr(user_context_db, "delete_bookmark",
                            lambda t, i: dels.append((t, i)) or True)
        monkeypatch.setattr(user_context_db, "get_bookmark",
                            lambda t, i: None)
        monkeypatch.setattr(spine, "_fetch_sense_row",
                            lambda sid: {"verb": "run", "sense_index": "1"})
        _login_spine(monkeypatch)
        stub = _StubSt(button_label=self._ON)
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert ups == [("sense", str(SENSE_ID), "run · S1（#7）", None)]
        assert dels == []
        assert flashes
        assert stub.rerun_count == 1

    def test_cancel_click_deletes_flash_rerun(self, monkeypatch):
        flashes = _install_flash_recorder(monkeypatch)
        ups, dels = [], []
        monkeypatch.setattr(user_context_db, "upsert_bookmark",
                            lambda t, i, title=None, note=None:
                                ups.append((t, i)) or True)
        monkeypatch.setattr(user_context_db, "delete_bookmark",
                            lambda t, i: dels.append((t, i)) or True)
        monkeypatch.setattr(user_context_db, "get_bookmark",
                            lambda t, i: {"id": 5, "title": "x"})
        _login_spine(monkeypatch)
        stub = _StubSt(button_label=self._OFF)
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert dels == [("sense", str(SENSE_ID))]
        assert ups == []
        assert flashes
        assert stub.rerun_count == 1

    def test_no_click_no_data_layer_write(self, monkeypatch):
        """渲染态只读：不点击不动数据层写面。"""
        _install_flash_recorder(monkeypatch)
        ups, dels = [], []
        monkeypatch.setattr(user_context_db, "upsert_bookmark",
                            lambda t, i, title=None, note=None:
                                ups.append(1) or True)
        monkeypatch.setattr(user_context_db, "delete_bookmark",
                            lambda t, i: dels.append(1) or True)
        monkeypatch.setattr(user_context_db, "get_bookmark",
                            lambda t, i: None)
        monkeypatch.setattr(spine, "_fetch_sense_row", lambda sid: None)
        _login_spine(monkeypatch)
        stub = _StubSt()          # button_label=None → 不点击
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert ups == [] and dels == []
        assert stub.rerun_count == 0

    def test_state_check_failure_hides_control(self, monkeypatch):
        """收藏态判定异常 → 控件不渲染（fail-closed，不猜态）。"""
        def _boom(t, i):
            raise RuntimeError("boom")

        monkeypatch.setattr(spine, "_fetch_my_bookmark", _boom)
        _login_spine(monkeypatch)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        spine._render_bookmark_toggle(SENSE_ID)
        assert stub.buttons == []

    def test_sense_label_fallback_without_sense_row(self, monkeypatch):
        """义项行取不到 → 标签回退 '义位 #id'（书签 title 恒非空可读）。"""
        monkeypatch.setattr(spine, "_fetch_sense_row", lambda sid: None)
        assert spine._sense_label(SENSE_ID) == f"义位 #{SENSE_ID}"
        monkeypatch.setattr(spine, "_fetch_sense_row",
                            lambda sid: {"verb": "run", "sense_index": "1"})
        assert spine._sense_label(SENSE_ID) == "run · S1（#7）"


class TestSpineIntegration:
    """render_sense_spine 外围接线：书签 toggle 在段前、我的笔记在 ⑦ 后、
    未登录全隐、脏 id 跳过控件。"""

    def test_logged_in_wires_toggle_and_notes_after_section_7(
            self, monkeypatch):
        _login_spine(monkeypatch)
        _stub_sections(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_note", lambda sid: None)
        monkeypatch.setattr(user_context_db, "get_bookmark",
                            lambda t, i: None)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        render_sense_spine(SENSE_ID)
        assert stub.buttons == ["📌 收藏本义位"]           # toggle 在场（段前）
        assert f"sense_spine_note_form_{SENSE_ID}" in stub.forms
        notes_idx = next(i for i, m in enumerate(stub.markdowns)
                         if "📝 我的笔记" in m)
        sec7_idx = next(i for i, m in enumerate(stub.markdowns)
                        if "第7段" in m)
        assert sec7_idx < notes_idx                        # 笔记段在 ⑦ 之后

    def test_no_login_hides_both_controls(self, monkeypatch):
        _no_login_spine(monkeypatch)
        _stub_sections(monkeypatch)

        def _explode(*a, **k):
            raise AssertionError("未登录不应触碰上下文域数据层")

        monkeypatch.setattr(user_context_db, "get_note", _explode)
        monkeypatch.setattr(user_context_db, "get_bookmark", _explode)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        render_sense_spine(SENSE_ID)
        assert stub.buttons == []
        assert stub.forms == []
        assert not any("我的笔记" in m for m in stub.markdowns)
        # 七段照常渲染（脊柱本体不受登录态影响）
        assert sum("第" in m and "段" in m for m in stub.markdowns) >= 7

    def test_dirty_sense_id_skips_controls(self, monkeypatch):
        """脏 sense_id：控件跳过、不崩（七段 bad-id 灰段由 _spine_sections
        负责，此处只验证渲染层防御）。"""
        _login_spine(monkeypatch)
        _stub_sections(monkeypatch)
        exploded = []

        def _explode(*a, **k):
            exploded.append(1)
            raise AssertionError("脏 id 不应触碰上下文域数据层")

        monkeypatch.setattr(user_context_db, "get_note", _explode)
        monkeypatch.setattr(user_context_db, "get_bookmark", _explode)
        stub = _StubSt()
        monkeypatch.setattr(spine, "st", stub)
        render_sense_spine("abc")
        assert not exploded
        assert stub.buttons == [] and stub.forms == []


# ============================================
# 3. 账号管理页：⚙️ 我的偏好段
# ============================================

_STORED_PROFILES = [
    {"id": 1, "pref_key": "ui.default_category", "pref_value": "motion",
     "created_at": None, "updated_at": None},
    {"id": 2, "pref_key": "ui.theme", "pref_value": "dark",
     "created_at": None, "updated_at": None},
]


class TestMyPreferences:
    """⚙️ 我的偏好（页面末尾段；读写 UI 不改行为；RV2-3 空值=未设值）。"""

    def _render(self, monkeypatch, *, submit_label=None, text_values=None,
                select_value=None, stored=None):
        flashes = _install_flash_recorder(monkeypatch)
        ups, dels = [], []
        monkeypatch.setattr(
            user_context_db, "list_profiles",
            lambda limit=500: list(stored if stored is not None
                                   else _STORED_PROFILES))
        monkeypatch.setattr(
            user_context_db, "upsert_profile",
            lambda k, v: ups.append((k, v)) or True)
        monkeypatch.setattr(
            user_context_db, "delete_profile",
            lambda k: dels.append(k) or True)
        monkeypatch.setattr(ua, "_current_user", lambda: _ME)
        stub = _StubSt(submit_label=submit_label,
                       text_values=text_values, select_value=select_value)
        monkeypatch.setattr(ua, "st", stub)
        ua._render_my_preferences()
        return stub, ups, dels, flashes

    def test_no_login_section_not_rendered(self, monkeypatch):
        _install_flash_recorder(monkeypatch)
        exploded = []

        def _explode(*a, **k):
            exploded.append(1)
            raise AssertionError("未登录不应触碰数据层")

        monkeypatch.setattr(user_context_db, "list_profiles", _explode)
        monkeypatch.setattr(ua, "_current_user", lambda: None)
        stub = _StubSt()
        monkeypatch.setattr(ua, "st", stub)
        ua._render_my_preferences()
        assert not exploded
        assert not any("我的偏好" in m for m in stub.markdowns)
        assert stub.forms == [] and stub.text_widgets == []

    def test_logged_in_renders_preset_inputs_with_stored_values(
            self, monkeypatch):
        stub, ups, dels, _ = self._render(monkeypatch)
        assert any("⚙️ 我的偏好" in m for m in stub.markdowns)
        preset_inputs = {kw["key"]: value
                         for kind, label, value, kw in stub.text_widgets
                         if label.startswith("ui.")}
        assert preset_inputs == {
            "my_prefs_input_ui.default_category": "motion",  # 预填已存值
            "my_prefs_input_ui.rows_per_page": "",           # 未存键 → 空值态
        }
        # 自定义键列表在场（ui.theme 为已存自定义键）
        assert any("ui.theme" in m for m in stub.markdowns)

    def test_save_preset_keys_upserts_flash_rerun(self, monkeypatch):
        stub, ups, dels, flashes = self._render(
            monkeypatch, submit_label="💾 保存预设键",
            text_values={"my_prefs_input_ui.default_category": "verb"})
        assert ("ui.default_category", "verb") in ups
        assert ("ui.rows_per_page", None) in ups   # 未存键 → 空白 → 未设值
        assert dels == []
        assert flashes == ["我的偏好已保存（跨设备续接）。"]
        assert stub.rerun_count == 1
        assert stub.errors == []

    def test_save_blank_value_becomes_null(self, monkeypatch):
        """空白提交 = 未设值（RV2-3 第 2 类：键已建值 NULL），与笔记 ''=清空
        （第 3 类）不同源。"""
        stored = [{"pref_key": "ui.rows_per_page", "pref_value": "20",
                   "created_at": None, "updated_at": None}]
        stub, ups, _, _ = self._render(
            monkeypatch, submit_label="💾 保存预设键", stored=stored,
            text_values={"my_prefs_input_ui.rows_per_page": ""})
        assert ("ui.rows_per_page", None) in ups

    def test_save_failure_error_no_rerun(self, monkeypatch):
        flashes = _install_flash_recorder(monkeypatch)
        monkeypatch.setattr(user_context_db, "list_profiles",
                            lambda limit=500: [])
        monkeypatch.setattr(user_context_db, "upsert_profile",
                            lambda k, v: False)
        monkeypatch.setattr(user_context_db, "delete_profile",
                            lambda k: False)
        monkeypatch.setattr(ua, "_current_user", lambda: _ME)
        stub = _StubSt(submit_label="💾 保存预设键")
        monkeypatch.setattr(ua, "st", stub)
        ua._render_my_preferences()
        assert flashes == []
        assert stub.rerun_count == 0
        assert stub.errors

    def test_add_custom_key_upserts_flash_rerun(self, monkeypatch):
        stub, ups, dels, flashes = self._render(
            monkeypatch, submit_label="➕ 新增/覆盖自定义键",
            text_values={"my_prefs_custom_key": " ui.theme ",
                         "my_prefs_custom_value": " dark "})
        assert ups == [("ui.theme", "dark")]   # 键与值 strip 后入库
        assert flashes == ["偏好键「ui.theme」已保存。"]
        assert stub.rerun_count == 1

    def test_add_custom_key_empty_rejected(self, monkeypatch):
        stub, ups, _, flashes = self._render(
            monkeypatch, submit_label="➕ 新增/覆盖自定义键",
            text_values={"my_prefs_custom_key": "   "})
        assert ups == []
        assert flashes == []
        assert stub.errors

    def test_delete_key_calls_delete_flash_rerun(self, monkeypatch):
        stub, ups, dels, flashes = self._render(
            monkeypatch, submit_label="🗑 删除所选键",
            select_value="ui.theme")
        assert dels == ["ui.theme"]
        assert ups == []
        assert flashes == ["偏好键「ui.theme」已删除。"]
        assert stub.rerun_count == 1
        # 删除下拉含预置键与自定义键（预置键删除后重存即可恢复）
        options = stub.selects[0][1]
        assert "ui.theme" in options and "ui.default_category" in options

    def test_rv12_no_st_success_in_section(self):
        """RV12 纪律：偏好段零 st.success 调用（断言调用位 st.success( ）。"""
        source = inspect.getsource(ua._render_my_preferences)
        assert "st.success(" not in source
        assert "ui_kit.flash" in source

    def test_section_wired_at_page_end(self):
        """接线契约：我的偏好段在页面末尾（新建用户表单之后）。"""
        page_source = inspect.getsource(ua.render_users_admin_page)
        create_idx = page_source.find("_render_create_user_form(me)")
        prefs_idx = page_source.find("_render_my_preferences()")
        assert create_idx != -1 and prefs_idx != -1
        assert create_idx < prefs_idx
