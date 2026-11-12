"""FX-51 落地测试：侧边栏「📌 我的书签」快捷段（书签闭环的导航面）。

契约（src/app.py _render_sidebar_bookmarks；render_sidebar 内、导航区
（ls_nav 容器）之后、AI 待办徽章/实验统计之前的唯一调用点）：

  * 未登录整段不渲染（own-rows-only 口径的 UI 表达，段头都不出）；
  * 无书签整段不渲染（不占版面）；
  * 库降级（DB_AVAILABLE=False / 读取意外异常）段头照出＋灰注如实说明，
    离线时不触数据层；
  * 数量纪律：只渲染最近 3 行——list_bookmarks 的 limit 行数闸（RV16-4，
    默认 500）现成参数传 3，签名零变更（updated_at DESC「最近在前」排序
    内置，无需新参）；完整列表仍在账号管理页（该页默认全量）；
  * 行形态：emoji 按类型（📌 sense/📄 entry/🔗 page）＋标题截断 18 字
    ＋整行按钮（use_container_width，on_click 跳转）；
  * page 锚跳转：PAGE_KEYS 白名单双保险（RV15-3）——渲染期只给合法锚出
    按钮（第一道），回调期再闸（第二道）；键集外脏锚不出按钮、回调不写
    会话（灰字行如实展示）；
  * sense 锚跳转：照 FX-42 书签段回调先例（_extract_verb_from_title /
    _annotate_target_visible 单一实现点复用）——verb 提取到写两键
    page=annotate ＋ annotate_verb=<verb>；提取不到只切页＋ui_kit.flash
    引导手选；目标页不可达回退仅切页＋warning；
  * entry 锚：本批不跳——不出按钮，caption 行挂账（依赖词条浏览器上下文）；
  * 收尾行「全部书签 →」：on_click 写 page="users_admin"（跳账号管理页
    书签段；RV12-1 合规——写会话只在回调）。

st 桩为最小假体（test_fx42_fixes._StubSt 同款思路，加 sidebar 挂载面）；
另含 AppTest 真渲染冒烟（登录态＋数据层打桩：真侧边栏无键冲突/无异常，
未登录真侧边栏无本段）。
"""

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")  # test_pages 同口径：env 优先于 config.yaml

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import ui_kit  # noqa: E402
from src import user_context_db as ucdb  # noqa: E402
from src.page_guides import PAGE_KEYS  # noqa: E402
import src.app as app_mod  # noqa: E402

_ME = {"id": 951, "username": "fx51", "display_name": "FX51 用户", "role": "admin"}
_VIEWER_ONLY = {"id": 952, "username": "fx51v", "display_name": "FX51 只读",
                "role": "viewer"}

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
TIMEOUT = 120


# ============================================
# 假体：st ＋ 打桩记录（fx42 同款最小件 ＋ sidebar 挂载面）
# ============================================

class _StubSt:
    """st 假体：记录调用；本段只用 st.sidebar.{markdown,caption,button}，
    sidebar 面板共享同一组记录列表；button 按预设 **key** 判「点击」，
    on_click 回调捕获供 RV12-1 断言。"""

    def __init__(self, *, click_keys=()):
        self.markdowns, self.captions = [], []
        self.buttons = []
        self.session_state = {}
        self._click_keys = set(click_keys)
        self.sidebar = self

    # —— 本段仅走 st.sidebar.*（sidebar 即自身，记录进同一列表）——

    def markdown(self, text, **kw):
        self.markdowns.append(text)

    def caption(self, text):
        self.captions.append(text)

    def button(self, label, **kw):
        self.buttons.append((label, kw))
        return kw.get("key") in self._click_keys


def _button_by_key(stub, key):
    """stub 记录里按 widget key 找按钮（返回 (label, kwargs) 或 None）。"""
    for label, kw in stub.buttons:
        if kw.get("key") == key:
            return label, kw
    return None


def _bm(bid, anchor_type, anchor_id, title=None):
    """user_bookmarks 行桩（列结构与 list_bookmarks SELECT 对齐）。"""
    return {
        "id": bid, "anchor_type": anchor_type, "anchor_id": anchor_id,
        "title": title, "note": None,
        "created_at": "2026-11-11 08:00:00",
        "updated_at": "2026-11-11 08:00:00",
    }


# ============================================
# 1. 渲染口径：登录门 / 空态 / 降级 / 数量纪律
# ============================================

class TestSectionRenderDiscipline:
    """侧边栏书签快捷段渲染口径（stub 级，不依赖真库）。"""

    def _render(self, monkeypatch, *, me=_ME, db_available=True, rows=None,
                raise_on_list=False):
        """渲染 _render_sidebar_bookmarks：打桩 _current_user / DB_AVAILABLE /
        list_bookmarks（spy 记录 limit 入参），返回 (stub, limits, raised)。"""
        limits = []
        monkeypatch.setattr(app_mod, "_current_user", lambda: me)
        monkeypatch.setattr(app_mod, "DB_AVAILABLE", db_available)

        def _spy(limit=ucdb.DEFAULT_LIST_LIMIT):
            limits.append(limit)
            if raise_on_list:
                raise RuntimeError("db boom")
            # 仿数据层 limit 行数闸语义（updated_at DESC LIMIT n）：桩按 limit
            # 截行——侧边栏传 3 则最多回 3 行（真实 LIMIT 行为由本桩建模）。
            return list(rows if rows is not None else [])[:limit]

        monkeypatch.setattr(ucdb, "list_bookmarks", _spy)
        stub = _StubSt()
        monkeypatch.setattr(app_mod, "st", stub)
        app_mod._render_sidebar_bookmarks()
        return stub, limits

    def test_not_logged_in_renders_nothing(self, monkeypatch):
        """未登录整段不渲染（own-rows-only 口径的 UI 表达）：段头/行/灰注
        全无，且不触数据层（登录门前置）。"""
        stub, limits = self._render(monkeypatch, me=None, rows=[_bm(1, "page", "cluster")])
        assert stub.markdowns == [] and stub.captions == [] and stub.buttons == []
        assert limits == []

    def test_no_bookmarks_renders_nothing(self, monkeypatch):
        """无书签整段不渲染（不占版面）：连段头都不出（段头在空态判定之后）。"""
        stub, limits = self._render(monkeypatch, rows=[])
        assert stub.markdowns == [] and stub.captions == [] and stub.buttons == []
        assert limits == [app_mod._SIDEBAR_BOOKMARK_ROWS]   # 空态前已查询

    def test_db_offline_renders_header_and_gray_caption_no_query(
            self, monkeypatch):
        """库降级·离线：段头照出＋灰注如实说明；离线短路不触数据层。"""
        stub, limits = self._render(monkeypatch, db_available=False)
        assert any("我的书签" in m for m in stub.markdowns)
        assert any("数据库离线" in c for c in stub.captions)
        assert stub.buttons == []
        assert limits == []                       # 离线不查询

    def test_read_exception_renders_gray_caption(self, monkeypatch):
        """库降级·读取意外异常：段头照出＋灰注，段不崩（数据层已自兜底，
        防御一层——意外异常不得掀翻整个侧边栏）。"""
        stub, _ = self._render(monkeypatch, rows=None, raise_on_list=True)
        assert any("我的书签" in m for m in stub.markdowns)
        assert any("暂不可用" in c for c in stub.captions)
        assert stub.buttons == []

    def test_renders_at_most_three_rows_passing_limit_3(self, monkeypatch):
        """数量纪律：5 条书签只渲染 3 行（＋收尾行）；查询传 limit=3（RV16-4
        行数闸现成参数，签名零变更）。"""
        rows = [_bm(i, "page", key, f"页面{i}")
                for i, key in enumerate(("cluster", "graph", "corpus",
                                         "domain", "semantic"))]
        stub, limits = self._render(monkeypatch, rows=rows)
        assert limits == [3] == [app_mod._SIDEBAR_BOOKMARK_ROWS]
        row_buttons = [b for b in stub.buttons if b[1].get("key", "").startswith(
            "sidebar_bm_")]
        assert len(row_buttons) == 3              # 只取最近 3 条
        assert _button_by_key(stub, "sidebar_bookmarks_all") is not None

    def test_row_emoji_by_type(self, monkeypatch):
        """行首 emoji 按类型：📌 sense / 📄 entry / 🔗 page。"""
        rows = [_bm(1, "sense", "42", "walk · S1（#42）"),
                _bm(2, "entry", "chase", "chase 词条"),
                _bm(3, "page", "cluster", "语义分析页")]
        stub, _ = self._render(monkeypatch, rows=rows)
        labels = {kw.get("key"): label for label, kw in stub.buttons}
        assert labels["sidebar_bm_1"].startswith("📌 ")
        assert labels["sidebar_bm_3"].startswith("🔗 ")
        # entry 行不出按钮：caption 行灰字展示（📄 前缀）
        assert any(c.startswith("📄 chase 词条") for c in stub.captions)

    def test_title_truncated_at_18_chars(self, monkeypatch):
        """标题截断 18 字：超出以「…」收尾（诚实省略号）；18 字内原样。"""
        long_title = "一二三四五六七八九十一二三四五六七八九超长义位"
        rows = [_bm(1, "page", "cluster", long_title),
                _bm(2, "page", "graph", "短标题")]
        stub, _ = self._render(monkeypatch, rows=rows)
        labels = {kw.get("key"): label for label, kw in stub.buttons}
        short = labels["sidebar_bm_1"]
        body = short.split(" ", 1)[1]             # 去掉行首 emoji
        assert body == long_title[:18] + "…"
        assert len(body) == 19
        assert labels["sidebar_bm_2"].endswith("短标题") and "…" not in labels["sidebar_bm_2"]

    def test_emoji_table_covers_anchor_whitelist(self):
        """emoji 表覆盖数据层锚白名单三锚（user_context_db
        .BOOKMARK_ANCHOR_TYPES 单一事实源对齐——新增锚漏配即测红）。"""
        assert set(app_mod._BOOKMARK_ROW_EMOJI) == set(ucdb.BOOKMARK_ANCHOR_TYPES)


# ============================================
# 2. 跳转回调：page 锚双保险 / sense 锚三分支 / entry 挂账 / 收尾行
# ============================================

class TestSectionJumpCallbacks:
    """行跳转回调（RV12-1：写会话只在 on_click 回调内）。"""

    def _render(self, monkeypatch, *, me=_ME, rows=None):
        flashes = []
        monkeypatch.setattr(ui_kit, "flash",
                            lambda msg, level="success": flashes.append((level, msg)))
        monkeypatch.setattr(app_mod, "_current_user", lambda: me)
        monkeypatch.setattr(app_mod, "DB_AVAILABLE", True)
        monkeypatch.setattr(ucdb, "list_bookmarks",
                            lambda limit=500: list(rows if rows is not None else []))
        stub = _StubSt()
        monkeypatch.setattr(app_mod, "st", stub)
        app_mod._render_sidebar_bookmarks()
        return stub, flashes

    # ---- page 锚：RV15-3 双保险 ----

    def test_page_anchor_callback_writes_page(self, monkeypatch):
        """page 锚整行按钮：回调写 session_state["page"]=锚值（合法路由键）。"""
        stub, _ = self._render(monkeypatch,
                               rows=[_bm(1, "page", "cluster", "语义分析页")])
        _, kw = _button_by_key(stub, "sidebar_bm_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "cluster"

    def test_page_anchor_render_gate_blocks_dirty_anchor(self, monkeypatch):
        """page 锚键集外脏锚（第一道闸）：不出整行按钮，灰字行如实展示。"""
        stub, _ = self._render(monkeypatch,
                               rows=[_bm(1, "page", "not_a_page", "脏锚行")])
        assert _button_by_key(stub, "sidebar_bm_1") is None
        assert any("脏锚行" in c for c in stub.captions)

    def test_page_anchor_callback_recheck_blocks_dirty_anchor(self, monkeypatch):
        """page 锚脏锚回调期再闸（第二道，RV15-3 双保险）：即使绕过渲染闸
        直调回调工厂，也不写会话。"""
        stub, _ = self._render(monkeypatch)
        cb = app_mod._sidebar_bookmark_jump_callback("page", "not_a_page", "脏锚行")
        cb()
        assert "page" not in stub.session_state

    def test_page_anchor_callback_uses_update_not_subscript(self):
        """RV12-1 源码级锁：回调体一律 st.session_state.update（不走下标直写，
        不回潮 st.success——flash 走 ui_kit 队列 RV12-2）。"""
        source = inspect.getsource(app_mod._sidebar_bookmark_jump_callback)
        assert "st.session_state.update(" in source
        assert 'st.session_state["page"]' not in source
        assert "st.success(" not in source
        assert "ui_kit.flash(" in source

    # ---- sense 锚：FX-42 三分支 ----

    def test_sense_anchor_callback_presets_verb_task_format(self, monkeypatch):
        """sense 锚·verb 提取到（'-S' 直连口径）：写两键 page=annotate ＋
        annotate_verb=<verb>，无附加提示（预置成功不吵）。"""
        stub, flashes = self._render(
            monkeypatch, rows=[_bm(1, "sense", "42", "walk-S1 足部奔跑义")])
        _, kw = _button_by_key(stub, "sidebar_bm_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert stub.session_state.get("annotate_verb") == "walk"
        assert flashes == []

    def test_sense_anchor_callback_presets_verb_live_format(self, monkeypatch):
        """sense 锚·sense_spine 落库格式「walk · S1（#42）」同样预置成功。"""
        stub, flashes = self._render(
            monkeypatch, rows=[_bm(1, "sense", "42", "drift · S2（#43）")])
        _, kw = _button_by_key(stub, "sidebar_bm_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert stub.session_state.get("annotate_verb") == "drift"
        assert flashes == []

    def test_sense_anchor_no_marker_only_page_plus_flash(self, monkeypatch):
        """sense 锚·提取不到（title 无义项段标记）：只写 page ＋ info flash
        引导手选（FX-42 同文案），不预置动词键。"""
        stub, flashes = self._render(
            monkeypatch, rows=[_bm(1, "sense", "44", "好义位")])
        _, kw = _button_by_key(stub, "sidebar_bm_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert "annotate_verb" not in stub.session_state
        assert flashes == [("info", "请在标注平台选择动词 好义位")]

    def test_sense_anchor_target_invisible_falls_back(self, monkeypatch):
        """sense 锚·目标页不可达（防御分支）：回退仅切页＋warning 说明，
        不预置动词（_annotate_target_visible 单一实现点复用）。"""
        stub, flashes = self._render(monkeypatch, me=_VIEWER_ONLY,
                                     rows=[_bm(1, "sense", "42", "walk-S1 足部奔跑义")])
        _, kw = _button_by_key(stub, "sidebar_bm_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert "annotate_verb" not in stub.session_state
        assert len(flashes) == 1 and flashes[0][0] == "warning"
        assert "标注平台对当前账号不可见" in flashes[0][1]

    # ---- entry 锚：本批不跳（caption 挂账）----

    def test_entry_anchor_no_button_and_pending_caption(self, monkeypatch):
        """entry 锚不出整行按钮（不做假按钮）：灰字行＋段尾挂账 caption
        （依赖词条浏览器上下文）。"""
        rows = [_bm(1, "entry", "chase", "chase 词条"),
                _bm(2, "page", "cluster", "语义分析页")]
        stub, _ = self._render(monkeypatch, rows=rows)
        assert _button_by_key(stub, "sidebar_bm_1") is None
        assert any("chase 词条" in c for c in stub.captions)
        assert any("词条锚暂不支持跳转" in c and "挂账" in c for c in stub.captions)
        assert _button_by_key(stub, "sidebar_bm_2") is not None   # page 锚照常跳

    # ---- 收尾行「全部书签 →」----

    def test_all_bookmarks_tail_button_writes_users_admin(self, monkeypatch):
        """收尾行「全部书签 →」：回调写 page="users_admin"（跳账号管理页
        书签段）。"""
        stub, _ = self._render(monkeypatch,
                               rows=[_bm(1, "page", "cluster", "语义分析页")])
        btn = _button_by_key(stub, "sidebar_bookmarks_all")
        assert btn is not None and btn[0] == "全部书签 →"
        btn[1]["on_click"]()
        assert stub.session_state.get("page") == "users_admin"

    def test_users_admin_is_valid_route_key(self):
        """收尾行目标键在 PAGE_KEYS（路由键单一事实源——残留页回退逻辑
        对越权角色折回搜索页，同样不崩）。"""
        assert "users_admin" in PAGE_KEYS


# ============================================
# 3. 接线契约：render_sidebar 位置（导航区之后、AI 待办徽章之前）
# ============================================

class TestWiringInRenderSidebar:
    """render_sidebar 接线位置契约（源码级）：唯一调用点、导航区之后、
    AI 待办徽章之前（FX-51 任务位置口径）。"""

    def _source(self):
        return inspect.getsource(app_mod.render_sidebar)

    def test_called_exactly_once(self):
        """唯一调用点：_render_sidebar_bookmarks() 在 render_sidebar 内恰一次。"""
        assert self._source().count("_render_sidebar_bookmarks()") == 1

    def test_position_between_nav_and_ai_badge(self):
        """位置契约：ls_nav 容器 < 书签段调用 < AI 待办徽章注释（实验统计
        更在其后）。"""
        src = self._source()
        i_nav = src.find('key="ls_nav"')
        i_bm = src.find("_render_sidebar_bookmarks()")
        i_ai = src.find("AI 协作待办徽章")
        assert -1 not in (i_nav, i_bm, i_ai)
        assert i_nav < i_bm < i_ai

    def test_segment_helpers_in_app_module(self):
        """段的三件套在 app 模块（行数纪律常量 3 ＋ 截断宽 18 ＋ emoji 表）。"""
        assert app_mod._SIDEBAR_BOOKMARK_ROWS == 3
        assert app_mod._SIDEBAR_BOOKMARK_TITLE_MAX == 18
        assert app_mod._BOOKMARK_ROW_EMOJI == {"sense": "📌", "entry": "📄",
                                               "page": "🔗"}

    def test_list_bookmarks_signature_unchanged(self):
        """list_bookmarks 签名零变更（FX-51 数量纪律走现成 limit 行数闸，
        默认 DEFAULT_LIST_LIMIT 兼容全量消费面——账号管理页不动）。"""
        sig = inspect.signature(ucdb.list_bookmarks)
        assert list(sig.parameters) == ["limit"]
        assert sig.parameters["limit"].default == ucdb.DEFAULT_LIST_LIMIT
        assert ucdb.DEFAULT_LIST_LIMIT == 500


# ============================================
# 4. AppTest 真渲染冒烟（真侧边栏：无键冲突 / 无异常 / 未登录无本段）
# ============================================

_SMOKE_ROWS = [
    _bm(1, "page", "cluster", "语义分析页"),
    _bm(2, "sense", "42", "walk-S1 足部奔跑义"),
    _bm(3, "entry", "chase", "chase 词条"),
    _bm(4, "page", "graph", "图谱页"),   # 第 4 条不得出现在侧边栏
]


def _new_at():
    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _exceptions(at):
    return [str(e.value) for e in at.exception]


class TestAppTestSmoke:
    """AppTest 真渲染冒烟：数据层打桩（list_bookmarks——AppTest 脚本与测试
    共享同一 user_context_db 模块对象），验证真侧边栏渲染链路。"""

    def test_logged_in_section_renders_in_real_sidebar(self, monkeypatch):
        """登录态＋4 条桩：真侧边栏出段头＋≤3 行＋收尾行，无异常无键冲突；
        DB 离线环境则退化为灰注（两支都不得崩页）。"""
        monkeypatch.setattr(ucdb, "list_bookmarks",
                            lambda limit=500: [dict(r) for r in _SMOKE_ROWS])
        at = _new_at()
        at.session_state["user"] = dict(_ME)
        at.run()
        assert not at.exception, _exceptions(at)
        headers = [str(m.value) for m in at.sidebar.markdown]
        captions = [str(c.value) for c in at.sidebar.caption]
        if any("数据库离线，书签暂不可读" in c for c in captions):
            return                                  # 离线环境：灰注分支即达
        assert any("📌 我的书签" in h for h in headers), headers
        labels = [str(b.label) for b in at.sidebar.button]
        assert any(lab.startswith("🔗 ") for lab in labels), labels
        assert any(lab.startswith("📌 ") for lab in labels), labels
        assert "全部书签 →" in labels, labels
        bm_labels = [lab for lab in labels if lab[:1] in "📌📄🔗"]
        assert len(bm_labels) == 3, labels           # 第 4 条被数量闸拦下

    def test_logged_out_no_section_in_real_sidebar(self, monkeypatch):
        """未登录：真侧边栏无「📌 我的书签」段头、无书签行（own-rows-only
        UI 表达在真渲染下成立）。"""
        monkeypatch.setattr(ucdb, "list_bookmarks",
                            lambda limit=500: [dict(r) for r in _SMOKE_ROWS])
        at = _new_at()
        at.run()
        assert not at.exception, _exceptions(at)
        headers = [str(m.value) for m in at.sidebar.markdown]
        labels = [str(b.label) for b in at.sidebar.button]
        assert not any("我的书签" in h for h in headers), headers
        assert "全部书签 →" not in labels, labels
