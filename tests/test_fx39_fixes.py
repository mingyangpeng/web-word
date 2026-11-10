"""FX-39 两块 UI 落地测试：📌 我的书签列表段 ＋ 撰写台草稿暂存/恢复。

三块契约，桩级不依赖真库（数据层 monkeypatch ＋ st 最小假体），真库链路
（MySQL 不可用整类 skip，test_writing_db / test_fx31 同款跳库口径）：

  * 账号管理页「📌 我的书签」段（src/users_admin_page.py，FX-39 任务 1）：
    三锚（sense/entry/page）表格渲染（类型徽章/标题回退锚值/锚/收藏时间）、
    page 锚「🔗 前往」跳转（on_click 回调内写 session_state["page"]，RV12-1
    照 collab_pages「去分立复核」先例；PAGE_KEYS 键集外的脏锚不出按钮）、
    逐行「🗑 取消收藏」（delete_bookmark → flash+rerun，失败 st.error）、
    空态引导、未登录整段不渲染（同偏好段纪律）；
  * 撰写台草稿暂存/恢复（src/writing_pages.py，FX-39 任务 2，draft_states
    域激活）：form_key 约定 'writing_draft_{cs_sense_id}'；「💾 暂存草稿
    （不提交审校）」upsert 全部可编辑字段（content/style_version/
    based_on_version）→ flash+rerun（RV12，不回潮 st.success）；重开撰写台
    暂存值作表单默认值＋恢复 caption；基线前进警示 caption（恢复值仅作
    草稿底稿）；提交审校成功路径 delete_draft 自动清除（失败不清除）；
    **乐观锁不破坏**：暂存在场时 update_draft 的 expect_version 仍来自
    _resolve_edit_target（冲突纪律：暂存只动表单默认值与会话存储）；
  * 真库全链（skipif 无 MySQL）：暂存（真库 draft_states）→ 恢复（loader
    过滤＋纯函数默认值）→ 建版提交审校（真库版本链）→ 清除；form_key
    隔离与损坏快照容错。

st 桩为最小假体（FX-37 _StubSt 同款思路）：button 按预设 **key** 精确点击
（多行按钮列表场景），并捕获 on_click 回调供跳转断言。
"""

import inspect
import json
import os
import queue
import re
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ui_kit  # noqa: E402
from src import user_context_db as ucdb  # noqa: E402
from src import users_admin_page as ua  # noqa: E402
from src import writing_pages as wp  # noqa: E402
import src.mysql_db as db  # noqa: E402
import src.writing_db as writing_db  # noqa: E402

UID = 901
SENSE_CS_ID = 77
FORM_KEY = f"writing_draft_{SENSE_CS_ID}"

_ME = {"id": UID, "username": "fx39", "display_name": "FX39 用户", "role": "admin"}

# RV12-1 正文期切页直写哨兵（users_admin_page 同口径，本页跳转必须走回调）
_BODY_PAGE_WRITE = re.compile(
    r'st\.session_state\[\s*["\']page["\']\s*\]\s*=')


# ============================================
# 假体：st ＋ 打桩记录
# ============================================

class _StubSt:
    """st 假体（FX-37 _StubSt 同款最小件）：记录调用，button 按 **key** 精确
    点击（书签多行 / 撰写台三按钮场景），on_click 回调捕获供 RV12-1 断言；
    successes 记录专供 RV12 反向断言（新增暂存/删除路径永不回潮）。"""

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def __init__(self, *, click_keys=(), text_values=None, select_value=None):
        self.markdowns, self.captions = [], []
        self.errors, self.infos, self.warnings, self.successes = [], [], [], []
        self.buttons, self.text_widgets, self.selects, self.radios = [], [], [], []
        self.expanders, self.forms = [], []
        self.rerun_count = 0
        self.session_state = {}
        self._click_keys = set(click_keys)
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
        self.buttons.append((label, kw))
        return kw.get("key") in self._click_keys

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

    def radio(self, label, options, **kw):
        self.radios.append((label, list(options)))
        return options[0] if options else None

    def columns(self, n):
        # st.columns 同时接受 int 与宽度比例序列（书签表用比例元组）
        count = len(n) if isinstance(n, (list, tuple)) else n
        return [self._Ctx() for _ in range(count)]

    def expander(self, label=None, **kw):
        self.expanders.append(label)
        return self._Ctx()

    def form(self, key=None, **kw):
        self.forms.append(key)
        return self._Ctx()

    def form_submit_button(self, label, **kw):
        return False

    def rerun(self):
        self.rerun_count += 1


def _install_flash_recorder(monkeypatch) -> list:
    """ui_kit.flash → 记录器（返回 messages 列表供断言）。"""
    flashes: list = []
    monkeypatch.setattr(ui_kit, "flash",
                        lambda msg, level="success": flashes.append(msg))
    return flashes


def _widget_value(stub, key):
    """stub 记录里按 widget key 取装载 value（text_area / text_input）。"""
    for kind, _label, value, kw in stub.text_widgets:
        if kw.get("key") == key:
            return value
    return None


def _button_by_key(stub, key):
    """stub 记录里按 widget key 找按钮（返回 (label, kwargs) 或 None）。"""
    for label, kw in stub.buttons:
        if kw.get("key") == key:
            return label, kw
    return None


# ============================================
# 任务 1：📌 我的书签列表段（users_admin_page）
# ============================================

def _bm(bid, anchor_type, anchor_id, title=None):
    """user_bookmarks 行桩（列结构与 list_bookmarks SELECT 对齐）。"""
    return {
        "id": bid, "anchor_type": anchor_type, "anchor_id": anchor_id,
        "title": title, "note": None,
        "created_at": "2026-11-10 08:00:00",
        "updated_at": "2026-11-10 08:00:00",
    }


BM_ROWS = [
    _bm(1, "sense", "42", "好义位"),
    _bm(2, "entry", "chase", None),
    _bm(3, "page", "cluster", "语义分析页"),
]


class TestMyBookmarksSection:
    """📌 我的书签段（FX-39 任务 1；三锚渲染 / page 跳转 / 删除 / 空态）。"""

    def _render(self, monkeypatch, *, rows=None, click_keys=(),
                delete_result=True, me=_ME):
        flashes = _install_flash_recorder(monkeypatch)
        del_calls = []

        def _fake_del(anchor_type, anchor_id):
            del_calls.append((anchor_type, anchor_id))
            return delete_result

        monkeypatch.setattr(
            ucdb, "list_bookmarks",
            lambda limit=500: list(rows if rows is not None else BM_ROWS))
        monkeypatch.setattr(ucdb, "delete_bookmark", _fake_del)
        monkeypatch.setattr(ua, "_current_user", lambda: me)
        stub = _StubSt(click_keys=click_keys)
        monkeypatch.setattr(ua, "st", stub)
        ua._render_my_bookmarks()
        return stub, del_calls, flashes

    def test_no_login_section_not_rendered(self, monkeypatch):
        """未登录整段不渲染（同偏好段纪律），且零数据层访问。"""
        _install_flash_recorder(monkeypatch)
        exploded = []

        def _explode(*a, **k):
            exploded.append(1)
            raise AssertionError("未登录不应触碰数据层")

        monkeypatch.setattr(ucdb, "list_bookmarks", _explode)
        monkeypatch.setattr(ua, "_current_user", lambda: None)
        stub = _StubSt()
        monkeypatch.setattr(ua, "st", stub)
        ua._render_my_bookmarks()
        assert not exploded
        assert not any("我的书签" in m for m in stub.markdowns)
        assert stub.buttons == []

    def test_three_anchor_rows_rendered(self, monkeypatch):
        """三锚表格：类型徽章（义位/词条/页面）、标题回退锚值、锚、收藏时间。"""
        stub, _, _ = self._render(monkeypatch)
        joined = "\n".join(stub.markdowns)
        assert "📌 我的书签" in joined
        for type_label in ("义位", "词条", "页面"):
            assert type_label in joined
        assert "好义位" in joined                 # sense 锚的收藏标题
        assert "chase" in joined                 # entry 锚 title=None → 回退锚值
        assert "语义分析页" in joined            # page 锚的收藏标题
        for anchor in ("42", "chase", "cluster"):
            assert anchor in joined
        assert "2026-11-10 08:00:00" in joined   # 收藏时间列
        for label in ("类型", "标题", "锚", "收藏时间", "操作"):
            assert f"**{label}**" in joined      # 表头行
        # 列间跳转口径如实注明（sense/entry 本批不跳）
        assert any("归第二批" in c for c in stub.captions)

    def test_page_anchor_only_jump_button(self, monkeypatch):
        """仅 page 锚出「🔗 前往」；sense/entry 锚只有「🗑 取消收藏」。"""
        stub, _, _ = self._render(monkeypatch)
        goto_btns = [kw for label, kw in stub.buttons if label == "🔗 前往"]
        assert [kw["key"] for kw in goto_btns] == ["bm_goto_3"]
        del_keys = [kw["key"] for label, kw in stub.buttons
                    if label == "🗑 取消收藏"]
        assert del_keys == ["bm_del_1", "bm_del_2", "bm_del_3"]

    def test_page_jump_callback_writes_session_state(self, monkeypatch):
        """RV12-1：跳转经 on_click 回调写会话（collab_pages 先例同款）。"""
        stub, _, _ = self._render(monkeypatch)
        _, kw = _button_by_key(stub, "bm_goto_3")
        on_click = kw.get("on_click")
        assert callable(on_click)
        on_click()
        assert stub.session_state.get("page") == "cluster"

    def test_page_jump_invalid_key_no_button(self, monkeypatch):
        """PAGE_KEYS 键集外的脏 page 锚不渲染跳转按钮（不写非法路由值）。"""
        rows = [_bm(9, "page", "not_a_page", "脏锚")]
        stub, _, _ = self._render(monkeypatch, rows=rows)
        assert _button_by_key(stub, "bm_goto_9") is None
        assert any("not_a_page" in m for m in stub.markdowns)  # 锚值如实展示

    def test_delete_success_flash_rerun(self, monkeypatch):
        """🗑 取消收藏：delete_bookmark(type, id) → flash + rerun（RV12）。"""
        stub, del_calls, flashes = self._render(
            monkeypatch, click_keys={"bm_del_1"})
        assert del_calls == [("sense", "42")]
        assert flashes == ["已取消收藏「好义位」。"]
        assert stub.rerun_count == 1
        assert stub.successes == []              # RV12：不回潮 st.success
        assert stub.errors == []

    def test_delete_failure_error_no_rerun(self, monkeypatch):
        """删除失败（库不可用/并发已删）：st.error 本轮直出，不 flash 不 rerun。"""
        stub, del_calls, flashes = self._render(
            monkeypatch, click_keys={"bm_del_2"}, delete_result=False)
        assert del_calls == [("entry", "chase")]
        assert flashes == []
        assert stub.rerun_count == 0
        assert stub.errors

    def test_empty_state_guidance(self, monkeypatch):
        """空态引导：引导去义项脊柱收藏；无表头无按钮。"""
        stub, _, _ = self._render(monkeypatch, rows=[])
        assert any("尚无书签——在义项脊柱点『📌 收藏本义位』即可收藏"
                   in c for c in stub.captions)
        assert stub.buttons == []
        assert not any("**类型**" in m for m in stub.markdowns)

    def test_rv12_no_st_success_in_section(self):
        """RV12 纪律：书签段零 st.success（删除成功走 ui_kit.flash）。"""
        for fn in (ua._render_my_bookmarks, ua._delete_bookmark_row):
            source = inspect.getsource(fn)
            assert "st.success(" not in source
        assert "ui_kit.flash" in inspect.getsource(ua._delete_bookmark_row)

    def test_rv12_no_body_time_page_write(self):
        """RV12-1 哨兵：本模块不得出现正文期 st.session_state['page'] 直写
        （跳转一律 st.button(..., on_click=...) 回调改会话）。"""
        source = inspect.getsource(ua)
        assert not _BODY_PAGE_WRITE.search(source)

    def test_section_wired_after_preferences(self):
        """接线契约：书签段在「⚙️ 我的偏好」段之后（页面末尾收尾）。"""
        page_source = inspect.getsource(ua.render_users_admin_page)
        prefs_idx = page_source.find("_render_my_preferences()")
        bm_idx = page_source.find("_render_my_bookmarks()")
        assert prefs_idx != -1 and bm_idx != -1
        assert prefs_idx < bm_idx


# ============================================
# 任务 2：撰写台草稿暂存/恢复（writing_pages，桩级）
# ============================================

SENSE = {
    "cs_sense_id": SENSE_CS_ID, "sense_no": "1",
    "sense_label": "cause to go from one place to another",
    "status": "locked", "lemma": "move", "language": "en",
    "category_code": "motion", "category_name": "移动",
    "cluster_id": 5, "cluster_no": 3, "locked": True,
}

# update 态基线：本人自有在途草稿 v2（乐观锁 expect_version=2）
LATEST_OWN_DRAFT = {
    "id": 11, "version": 2, "status": "draft", "author_id": UID,
    "content": "自有草稿内容", "style_version": "style.yaml@v1",
    "based_on_version": None,
}
CONTENT_KEY = "writing_content_11_2"          # target_id=11 + latest v2

# rejected 态基线：被拒 v3（打回重提 prefill + based_on_version=3）
LATEST_REJECTED = {
    "id": 12, "version": 3, "status": "rejected", "author_id": UID,
    "content": "被拒内容v3", "style_version": "style.yaml@v1",
    "based_on_version": None,
}


class TestWritingStashStubbed:
    """撰写台暂存/恢复（桩级；form_key 约定 + RV12 + 乐观锁不破坏）。"""

    def _render_write(self, monkeypatch, *, stub=None, latest=None,
                      stash_rows=(), content="", click_keys=(),
                      update_result=True, submit_result=True,
                      upsert_result=True):
        """渲染撰写台（_render_write_tab）：数据面全 monkeypatch。"""
        flashes = _install_flash_recorder(monkeypatch)
        ups, dels, upd_calls, subm_calls = [], [], [], []

        monkeypatch.setattr(ucdb, "list_drafts",
                            lambda limit=500: list(stash_rows))
        monkeypatch.setattr(
            ucdb, "upsert_draft",
            lambda key, state: ups.append((key, state)) or upsert_result)
        monkeypatch.setattr(ucdb, "delete_draft",
                            lambda key: dels.append(key) or True)

        def _fake_update(version_id, expect_version, content_arg,
                         style_version=None, ai_draft=None, **kw):
            upd_calls.append((version_id, expect_version, content_arg,
                              style_version))
            return update_result

        def _fake_submit(version_id, reviewer_id, note=None):
            subm_calls.append((version_id, reviewer_id))
            return submit_result

        monkeypatch.setattr(wp.writing_db, "update_draft", _fake_update)
        monkeypatch.setattr(wp.writing_db, "submit_for_review", _fake_submit)
        monkeypatch.setattr(wp.writing_db, "get_cluster_lock_state",
                            lambda *a, **k: None)
        monkeypatch.setattr(
            wp.writing_db, "get_latest_version",
            lambda ref, viewer_id=None: latest)
        monkeypatch.setattr(wp, "_list_categories_dicts",
                            lambda: [{"code": "motion", "name_cn": "移动"}])
        monkeypatch.setattr(wp, "_list_candidate_senses",
                            lambda cat, lang: [dict(SENSE)])
        monkeypatch.setattr(wp, "_resolve_oald_sense_id",
                            lambda lemma, no: 345)
        monkeypatch.setattr(wp, "_template_preview", lambda *a: None)
        monkeypatch.setattr(
            wp, "_reviewer_options",
            lambda me: [{"id": 202, "label": "审校员（uid 202）"}])

        stub = stub or _StubSt(click_keys=click_keys, text_values={
            CONTENT_KEY: content,
        })
        monkeypatch.setattr(wp, "st", stub)
        wp._render_write_tab(_ME)
        return stub, flashes, ups, dels, upd_calls, subm_calls

    # ---- form_key 约定 ----

    def test_stash_button_present_with_form_key_convention(self, monkeypatch):
        """「💾 暂存草稿（不提交审校）」与提交审校并列在场（无暂存照旧渲染）。"""
        stub, _, _, _, _, _ = self._render_write(monkeypatch,
                                                 latest=LATEST_OWN_DRAFT)
        assert _button_by_key(stub, "writing_stash_draft") is not None
        assert _button_by_key(stub, "writing_submit_review") is not None
        # 无暂存：无恢复提示，默认值照旧 = target prefill
        assert not any("已恢复暂存草稿" in c for c in stub.captions)
        assert _widget_value(stub, CONTENT_KEY) == "自有草稿内容"

    # ---- 暂存（upsert_draft 全部可编辑字段）----

    def test_stash_success_upserts_all_fields_flash_rerun(self, monkeypatch):
        """暂存成功：upsert_draft(form_key, {content, style_version,
        based_on_version}) → flash + rerun（RV12，不回潮 st.success）。"""
        stub, flashes, ups, dels, _, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT,
            content="暂存的内容ABC", click_keys={"writing_stash_draft"})
        assert ups == [(
            FORM_KEY,
            {"content": "暂存的内容ABC",
             "style_version": "style.yaml@v1",   # 表单默认值（latest 带出）
             "based_on_version": None},           # update 态无基线挂点
        )]
        assert flashes == ["草稿已暂存（未提交审校）。"]
        assert stub.rerun_count == 1
        assert stub.successes == []               # RV12：不回潮 st.success
        assert stub.errors == []
        assert dels == []                         # 暂存不动提交路径

    def test_stash_rejected_mode_records_based_on(self, monkeypatch):
        """打回重提态暂存：based_on_version 记录暂存当时基线（恢复期判据）。"""
        _, _, ups, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_REJECTED,
            content="改好的重提稿", click_keys={"writing_stash_draft"})
        assert ups[0][0] == FORM_KEY
        assert ups[0][1]["based_on_version"] == 3

    def test_stash_empty_content_warns_no_upsert(self, monkeypatch):
        """空成文暂存：st.warning 直出，不触数据层。"""
        stub, flashes, ups, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, content="   ",
            click_keys={"writing_stash_draft"})
        assert ups == []
        assert flashes == []
        assert stub.rerun_count == 0
        assert stub.warnings

    def test_stash_failure_error_no_rerun(self, monkeypatch):
        """暂存失败（库不可用/超长）：st.error 直出，不 flash 不 rerun。"""
        stub, flashes, ups, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, content="要暂存的内容",
            click_keys={"writing_stash_draft"}, upsert_result=False)
        assert len(ups) == 1 and ups[0][0] == FORM_KEY
        assert flashes == []
        assert stub.rerun_count == 0
        assert stub.errors

    # ---- 恢复（暂存值作表单默认值 + caption）----

    def _stash_row(self, state, form_key=FORM_KEY):
        return {
            "id": 1, "form_key": form_key,
            "state_json": json.dumps(state, ensure_ascii=False),
            "created_at": "2026-11-10 08:00:00",
            "updated_at": "2026-11-10 09:30:00",
        }

    def test_restore_prefills_form_and_caption(self, monkeypatch):
        """有暂存：表单默认值用暂存值（content/style），恢复 caption 带时间戳
        并注明「提交后自动清除」。"""
        rows = [self._stash_row({
            "content": "暂存的内容XYZ", "style_version": "style.yaml@v9",
            "based_on_version": 2,
        })]
        stub, _, _, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, stash_rows=rows)
        assert _widget_value(stub, CONTENT_KEY) == "暂存的内容XYZ"
        assert _widget_value(stub, "writing_style_version") == "style.yaml@v9"
        assert any(
            "已恢复暂存草稿（2026-11-10 09:30:00）——提交后自动清除" in c
            for c in stub.captions)

    def test_restore_base_advanced_caption(self, monkeypatch):
        """基线前进（暂存基于 v2、当前最新 v3 被拒）：恢复值照常作默认值，
        附加「注意：基线版本可能已前进」caption（仅作草稿底稿口径）。"""
        rows = [self._stash_row({
            "content": "暂存的旧底稿", "style_version": "style.yaml@v2",
            "based_on_version": 2,
        })]
        stub, _, _, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_REJECTED, stash_rows=rows)
        assert _widget_value(stub, "writing_content_0_3") == "暂存的旧底稿"
        assert any("注意：基线版本可能已前进" in c for c in stub.captions)
        assert any("恢复值仅作草稿底稿" in c for c in stub.captions)

    def test_restore_skips_other_form_key(self, monkeypatch):
        """其他义位的暂存不串台（form_key 隔离）。"""
        rows = [self._stash_row({"content": "别家草稿"},
                                form_key="writing_draft_88")]
        stub, _, _, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, stash_rows=rows)
        assert not any("已恢复暂存草稿" in c for c in stub.captions)
        assert _widget_value(stub, CONTENT_KEY) == "自有草稿内容"

    def test_restore_tolerates_corrupt_and_blank_snapshots(self, monkeypatch):
        """损坏 JSON / 空白 content 快照按「无暂存」渲染（绝不猜态）。"""
        corrupt = dict(self._stash_row({"content": "x"}))
        corrupt["state_json"] = "not-json{{"
        blank = self._stash_row({"content": "   "})
        stub, _, _, _, _, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, stash_rows=[corrupt, blank])
        assert not any("已恢复暂存草稿" in c for c in stub.captions)
        assert _widget_value(stub, CONTENT_KEY) == "自有草稿内容"

    # ---- 提交审校成功路径：自动清除暂存 ----

    def test_submit_success_deletes_stash(self, monkeypatch):
        """提交成功：delete_draft(form_key)（「提交后自动清除」闭环）。"""
        _, _, ups, dels, _, subm_calls = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, content="自有草稿内容",
            click_keys={"writing_submit_review"})
        assert subm_calls == [(11, 202)]          # 乐观锁目标 + 受派审校人
        assert dels == [FORM_KEY]
        assert ups == []                          # 提交路径不写暂存

    def test_submit_failure_keeps_stash(self, monkeypatch):
        """提交失败（状态已变/回避制拦截）：暂存保留（不误删）。"""
        _, _, _, dels, _, subm_calls = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, content="自有草稿内容",
            click_keys={"writing_submit_review"}, submit_result=False)
        assert subm_calls == [(11, 202)]
        assert dels == []

    # ---- 冲突纪律：乐观锁/闸门不被暂存破坏 ----

    def test_stash_does_not_touch_optimistic_lock(self, monkeypatch):
        """暂存在场时保存草稿：expect_version 仍来自 _resolve_edit_target
        （v2），暂存恢复只换表单默认值（content 恢复值、style 暂存值）——
        乐观锁语义不变。"""
        rows = [self._stash_row({
            "content": "暂存的旧底稿", "style_version": "style.yaml@v9",
            "based_on_version": 2,
        })]
        _, _, _, _, upd_with_stash, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT, stash_rows=rows,
            content="改过的内容", click_keys={"writing_save_draft"})
        _, _, _, _, upd_without, _ = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT,
            content="改过的内容", click_keys={"writing_save_draft"})
        # 乐观锁目标一致：版本行 id 与 expect_version 均来自编辑目标判定
        assert upd_with_stash[0][:2] == upd_without[0][:2] == (11, 2)
        # 默认值口径：暂存在场 → content/style 用暂存值；无暂存 → latest 带出
        assert upd_with_stash[0][2] == upd_without[0][2] == "改过的内容"
        assert upd_with_stash[0][3] == "style.yaml@v9"
        assert upd_without[0][3] == "style.yaml@v1"

    def test_stash_submit_path_unchanged_gates(self, monkeypatch):
        """暂存在场时提交：仍要求「先保存草稿」（未保存修改告警不跳过）——
        提交闸门序列与暂存正交。"""
        rows = [self._stash_row({"content": "暂存的旧底稿"})]
        stub, _, _, dels, _, subm_calls = self._render_write(
            monkeypatch, latest=LATEST_OWN_DRAFT,
            content="暂存的旧底稿",           # ≠ latest content（未保存修改）
            stash_rows=rows, click_keys={"writing_submit_review"})
        assert subm_calls == []                   # 被既有闸门拦下（未保存修改）
        assert dels == []
        assert any("未保存的修改" in w for w in stub.warnings)

    def test_rv12_stash_uses_flash_not_success(self):
        """RV12 纪律：暂存成功走 ui_kit.flash + rerun（源码级锁）。"""
        source = inspect.getsource(wp._render_write_tab)
        assert "ui_kit.flash(STASH_FLASH_TEXT)" in source
        assert 'st.rerun()' in source
        # 暂存分支不引入 st.success：本 tab 既有 st.success 均为
        # 保存/提交/终裁旧路径（无 rerun），此处只锁新增调用不回潮
        assert "STASH_FLASH_TEXT" in source

    def test_guide_documents_stash_feature(self):
        """使用说明（验收标准）覆盖暂存按钮与自动清除口径。"""
        joined = " ".join(wp.GUIDE["steps"] + wp.GUIDE["notes"])
        assert "暂存草稿" in joined
        assert "自动清除" in joined


# ============================================
# 任务 2 纯函数：_apply_stash_defaults / _load_stashed_writing_draft 容错
# ============================================

class TestApplyStashDefaults:
    """恢复口径单一实现点（纯函数；默认值/恢复 caption/基线前进判定）。"""

    TARGET_UPDATE = {
        "mode": "update", "target_id": 11, "expect_version": 2,
        "prefill": "自有草稿内容", "based_on_version": None, "notice": None,
    }
    TARGET_REJECT = {
        "mode": "create", "target_id": None, "expect_version": None,
        "prefill": "被拒内容v3", "based_on_version": 3, "notice": None,
    }
    STASHED = {
        "state": {"content": "暂存的内容", "style_version": "style.yaml@v9",
                  "based_on_version": 2},
        "updated_at": "2026-11-10 09:30:00",
    }

    def test_no_stash_keeps_defaults(self):
        content, style, restore, base = wp._apply_stash_defaults(
            None, self.TARGET_UPDATE, LATEST_OWN_DRAFT)
        assert (content, style) == ("自有草稿内容", "style.yaml@v1")
        assert restore is None and base is None

    def test_stash_overrides_form_defaults(self):
        content, style, restore, base = wp._apply_stash_defaults(
            self.STASHED, self.TARGET_UPDATE, LATEST_OWN_DRAFT)
        assert content == "暂存的内容"
        assert style == "style.yaml@v9"
        assert restore and "已恢复暂存草稿" in restore
        assert "2026-11-10 09:30:00" in restore
        assert "提交后自动清除" in restore
        # 基线未前进（暂存基于 v2 = 当前最新 v2）
        assert base is None

    def test_base_advanced_yields_warning_caption(self):
        _, _, _, base = wp._apply_stash_defaults(
            self.STASHED, self.TARGET_REJECT,
            {"id": 12, "version": 4, "status": "in_review"})
        assert base and "注意：基线版本可能已前进" in base
        assert "恢复值仅作草稿底稿" in base

    def test_tolerates_broken_payloads(self):
        for bad in ({}, {"state": None}, {"state": "x"},
                    {"state": {"content": "   "}}, {"state": {}}):
            content, style, restore, base = wp._apply_stash_defaults(
                bad, self.TARGET_UPDATE, LATEST_OWN_DRAFT)
            assert content == "自有草稿内容" and style == "style.yaml@v1"
            assert restore is None and base is None


class TestLoadStashedDraftDegraded:
    """loader 降级口径（无库环境：list_drafts fail-closed → None）。"""

    def test_no_session_no_db_returns_none(self, monkeypatch):
        monkeypatch.setattr(ucdb, "current_user", lambda: None)
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)

        def _explode(*a, **k):
            raise AssertionError("未登录不应触库")

        monkeypatch.setattr(ucdb, "get_db_cursor", _explode)
        assert wp._load_stashed_writing_draft(FORM_KEY) is None

    def test_bytes_and_native_dict_payloads(self, monkeypatch):
        """state_json 三形态兼容：str（主流）/ bytes / 已解析 dict。"""
        rows = [
            {"form_key": "f_str", "state_json": '{"content": "串"}',
             "updated_at": "t1"},
            {"form_key": "f_bytes",
             "state_json": '{"content": "字节"}'.encode("utf-8"),
             "updated_at": "t2"},
            {"form_key": "f_dict", "state_json": {"content": "原生"},
             "updated_at": "t3"},
            {"form_key": "f_bad", "state_json": "{oops", "updated_at": "t4"},
        ]
        monkeypatch.setattr(ucdb, "list_drafts", lambda limit=500: rows)
        assert wp._load_stashed_writing_draft("f_str")["state"] == {
            "content": "串"}
        assert wp._load_stashed_writing_draft("f_bytes")["state"] == {
            "content": "字节"}
        assert wp._load_stashed_writing_draft("f_dict")["state"] == {
            "content": "原生"}
        assert wp._load_stashed_writing_draft("f_bad") is None
        assert wp._load_stashed_writing_draft("f_missing") is None


# ============================================
# 真库全链：暂存 → 恢复 → 提交清除（无 MySQL 整类 skip）
# ============================================

TEST_DB = "web_word_fx39_test"


def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不建库；test_writing_db 同口径）。"""
    try:
        from pymysql.cursors import DictCursor

        conn = pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=DictCursor,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()


def _q(sql: str, params: tuple = ()):
    """测试内直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-39 真库全链测试")
class TestStashChainRealDb:
    """暂存→恢复→提交清除全链（真库 draft_states + 版本链）。"""

    @pytest.fixture
    def ctx_db(self, monkeypatch):
        """建空测试库（users 表先行 → 上下文域 5 表），身份钉 UID_A；结束 DROP。

        与 test_fx31.ctx_db 同款手法（全局态 teardown 走 finally 还原，
        池化连接显式关闭防悬挂会话）。"""
        conn_params = dict(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
        )
        conn = pymysql.connect(**conn_params)
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
                cur.execute(
                    f"CREATE DATABASE {TEST_DB} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn.close()
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过真库全链测试: {e}")

        sentinel_before = ucdb._TABLES_ENSURED
        old_database = db.MYSQL_DATABASE
        try:
            from src.users_db import ensure_user_tables

            db.MYSQL_DATABASE = TEST_DB
            ensure_user_tables()
            _q("INSERT INTO users (id, username, password_hash, display_name, "
               "role, active) VALUES (%s, %s, %s, %s, %s, 1)",
               (UID, "fx39_a", "x", "A 撰写", "viewer"))
            _q("INSERT INTO users (id, username, password_hash, display_name, "
               "role, active) VALUES (%s, %s, %s, %s, %s, 1)",
               (UID + 1, "fx39_b", "x", "B 审校", "viewer"))
            ucdb._TABLES_ENSURED = False
            ucdb.ensure_user_context_tables()
            # 会话归人：draft_states 是 own-rows-only，数据层从会话取 user_id
            monkeypatch.setattr(
                ucdb, "current_user", lambda: {"id": UID, "username": "fx39_a"})
            yield
        finally:
            db.MYSQL_DATABASE = old_database
            pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
            pool = getattr(db, "_connection_pools", {}).pop(pool_key, None)
            if pool is not None:
                while True:
                    try:
                        pool.get_nowait().close()
                    except queue.Empty:
                        break
                    except Exception:  # noqa: BLE001 单连接关不掉不阻塞 teardown
                        pass
            try:
                conn = pymysql.connect(**conn_params)
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001 teardown 尽力而为
                pass
            ucdb._TABLES_ENSURED = sentinel_before

    def test_stash_restore_submit_clear_full_chain(self, ctx_db):
        """暂存（真库）→ 恢复（loader＋纯函数默认值）→ 建版提交审校（真库
        版本链）→ 清除（页面提交成功路径同款调用）。"""
        state = {"content": "真库暂存内容", "style_version": "style.yaml@v1",
                 "based_on_version": None}
        # 1. 暂存（「💾 暂存草稿」路径的数据面调用）
        assert ucdb.upsert_draft(FORM_KEY, state) is True
        stashed = wp._load_stashed_writing_draft(FORM_KEY)
        assert stashed is not None
        assert stashed["state"] == state
        assert stashed["updated_at"] is not None
        # 2. 恢复（表单默认值口径；基线未前进 → 无警示）
        target = {"mode": "update", "target_id": 11, "expect_version": 1,
                  "prefill": "旧内容", "based_on_version": None,
                  "notice": None}
        content, style, restore_cap, base_cap = wp._apply_stash_defaults(
            stashed, target, {"id": 11, "version": 1})
        assert content == "真库暂存内容"
        assert style == "style.yaml@v1"
        assert restore_cap and "提交后自动清除" in restore_cap
        assert base_cap is None
        # 3. 提交审校（真库版本链：draft → in_review，回避制 901≠902）
        writing_db.ensure_writing_tables()
        vid = writing_db.create_draft("motion:77:345", UID, "真库暂存内容")
        assert vid
        assert writing_db.submit_for_review(int(vid), UID + 1) is True
        # 4. 提交成功路径末尾清除暂存（与 _render_write_tab 同款调用）
        assert ucdb.delete_draft(FORM_KEY) is True
        assert wp._load_stashed_writing_draft(FORM_KEY) is None

    def test_form_key_isolation_and_corrupt_snapshot(self, ctx_db):
        """form_key 隔离（跨义位不串台）＋损坏快照（NULL）按无暂存渲染。"""
        assert ucdb.upsert_draft(FORM_KEY, {"content": "A77"}) is True
        assert ucdb.upsert_draft("writing_draft_78", {"content": "A78"}) is True
        assert wp._load_stashed_writing_draft(
            "writing_draft_78")["state"]["content"] == "A78"
        assert wp._load_stashed_writing_draft(
            FORM_KEY)["state"]["content"] == "A77"
        # 快照损坏（state_json NULL）→ loader None，绝不猜态
        assert ucdb.upsert_draft("writing_draft_79", None) is True
        assert wp._load_stashed_writing_draft("writing_draft_79") is None
        assert wp._load_stashed_writing_draft("writing_draft_missing") is None
