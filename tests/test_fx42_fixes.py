"""FX-42 三块落地测试：书签 sense 锚跳转 ＋ 标注平台动词键 ＋ 预置行为实测。

四块契约：

  * verb 提取（src/users_admin_page.py _extract_verb_from_title，纯函数）：
    任务口径「walk-S1 足部奔跑义」→ split("-S")[0]='walk'；sense_spine
    ._sense_label 实际落库格式「walk · S1（#42）」→ 同样提取 'walk'（实测
    书签 title 全落此格式，'-S' 直连口径与其共存）；无义项段标记（标题回退
    锚值/未命名）→ None —— 跳转降级为只切页＋flash 引导手选；
  * sense 锚「前往 →」跳转（users_admin_page._render_my_bookmarks ＋
    _goto_sense_callback，桩级不依赖真库）：sense 行出「前往 →」（独立键
    bm_goto_s_*，与 page 锚「🔗 前往」bm_goto_* 区分），entry 行不出（挂账
    如实）；RV12-1 回调内写会话 —— verb 提取到写两键（page=annotate ＋
    annotate_verb=<verb>），提取不到只写 page＋flash「请在标注平台选择动词
    {title}」，目标页不可达（防御分支）回退 page 锚行为（只写 page＋flash
    说明）；flash 走 ui_kit（RV12-2，不回潮 st.success）；
  * 标注平台动词 selectbox key="annotate_verb" 在码（src/app.py
    _render_annotation_admin_view；index 回退 walk 逻辑保持）＋ 回调工厂接线；
  * Pilot 集外 verb 的预置行为实测（AppTest 记录 Streamlit 1.57 真实语义）：
    预置值在 options 内 → 生效且优先于 index（官方「程序化设值」）；预置值
    不在 options（pilot 过滤收缩/词库缺词）→ 静默回落 index 默认值，不抛
    异常，且 session_state 被回落值覆盖（残留预置不跨轮复活）；真库集成
    （AppTest 跑真实标注平台页）：预置 pilot 动词 drift → selectbox 选中
    drift，无预置 → index 回退 walk（skipif 无 MySQL，test_pages 同口径）。

st 桩为最小假体（test_fx39_fixes._StubSt 同款思路）：button 按 **key** 精确
点击，on_click 回调捕获供 RV12-1 断言。
"""

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")  # test_pages 同口径：env 优先于 config.yaml

import pytest  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from src import ui_kit  # noqa: E402
from src import user_context_db as ucdb  # noqa: E402
from src import users_admin_page as ua  # noqa: E402
from src.page_guides import PAGE_KEYS  # noqa: E402
import src.app as app_mod  # noqa: E402

_ME = {"id": 901, "username": "fx42", "display_name": "FX42 用户", "role": "admin"}
_VIEWER_ONLY = {"id": 902, "username": "fx42v", "display_name": "FX42 只读",
                "role": "viewer"}


# ============================================
# 假体：st ＋ 打桩记录（fx39 同款最小件）
# ============================================

class _StubSt:
    """st 假体：记录调用，button 按 **key** 精确点击，on_click 捕获供断言。"""

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def __init__(self, *, click_keys=()):
        self.markdowns, self.captions = [], []
        self.errors, self.infos, self.warnings, self.successes = [], [], [], []
        self.buttons = []
        self.rerun_count = 0
        self.session_state = {}
        self._click_keys = set(click_keys)

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

    def columns(self, n):
        count = len(n) if isinstance(n, (list, tuple)) else n
        return [self._Ctx() for _ in range(count)]

    def rerun(self):
        self.rerun_count += 1


def _button_by_key(stub, key):
    """stub 记录里按 widget key 找按钮（返回 (label, kwargs) 或 None）。"""
    for label, kw in stub.buttons:
        if kw.get("key") == key:
            return label, kw
    return None


# ============================================
# 1. verb 提取（纯函数）
# ============================================

class TestExtractVerbFromTitle:
    """_extract_verb_from_title：任务口径 '-S' 直连 ＋ sense_spine 落库
    ' · S' 格式共存；无标记 → None。"""

    def test_task_format_dash_s(self):
        """FX-42 任务口径：「walk-S1 足部奔跑义」→ split("-S")[0]='walk'。"""
        assert ua._extract_verb_from_title("walk-S1 足部奔跑义") == "walk"

    def test_task_format_multi_digit(self):
        """两位义项号照提：「fly-S12 习语用法」→ 'fly'。"""
        assert ua._extract_verb_from_title("fly-S12 习语用法") == "fly"

    def test_live_format_from_sense_spine(self):
        """sense_spine._sense_label 实际落库格式「walk · S1（#42）」→ 'walk'。"""
        assert ua._extract_verb_from_title("walk · S1（#42）") == "walk"

    def test_live_format_multi_digit(self):
        """落库格式两位义项号：「drop · S33（#7）」→ 'drop'。"""
        assert ua._extract_verb_from_title("drop · S33（#7）") == "drop"

    def test_no_marker_returns_none(self):
        """无义项段标记：标题回退锚值/纯词目/未命名 → None（降级手选）。"""
        for title in ("好义位", "义位 #77", "chase", "42", "（未命名）"):
            assert ua._extract_verb_from_title(title) is None, title

    def test_dirty_inputs_none(self):
        """脏入参：None/空白/只有标记无动词段 → None，绝不预置空值。"""
        for title in (None, "", "   ", "-S1", "· S3"):
            assert ua._extract_verb_from_title(title) is None, title


# ============================================
# 2. 书签段 sense 锚「前往 →」（桩级渲染＋回调）
# ============================================

def _bm(bid, anchor_type, anchor_id, title=None):
    """user_bookmarks 行桩（列结构与 list_bookmarks SELECT 对齐）。"""
    return {
        "id": bid, "anchor_type": anchor_type, "anchor_id": anchor_id,
        "title": title, "note": None,
        "created_at": "2026-11-11 08:00:00",
        "updated_at": "2026-11-11 08:00:00",
    }


BM_ROWS = [
    _bm(1, "sense", "42", "walk-S1 足部奔跑义"),          # 任务口径 title
    _bm(2, "sense", "43", "drift · S2（#43）"),           # sense_spine 落库格式
    _bm(3, "sense", "44", "好义位"),                       # 无义项段标记
    _bm(4, "entry", "chase", None),                        # entry 锚：挂账不跳
    _bm(5, "page", "cluster", "语义分析页"),               # page 锚：FX-39 先例
]


class TestBookmarkSenseJumpSection:
    """📌 我的书签段 FX-42 增量：sense 行「前往 →」＋三分支回调。"""

    def _render(self, monkeypatch, *, rows=None, me=_ME):
        flashes = []
        monkeypatch.setattr(ui_kit, "flash",
                            lambda msg, level="success": flashes.append((level, msg)))
        monkeypatch.setattr(ucdb, "list_bookmarks",
                            lambda limit=500: list(rows if rows is not None else BM_ROWS))
        monkeypatch.setattr(ua, "_current_user", lambda: me)
        stub = _StubSt()
        monkeypatch.setattr(ua, "st", stub)
        ua._render_my_bookmarks()
        return stub, flashes

    # ---- 按钮在场性 ----

    def test_sense_rows_have_goto_with_distinct_key(self, monkeypatch):
        """sense 行出「前往 →」（独立键 bm_goto_s_*，与 page 锚 bm_goto_*
        区分）；entry 行不出跳转按钮（挂账如实）。"""
        stub, _ = self._render(monkeypatch)
        for rid in (1, 2, 3):
            btn = _button_by_key(stub, f"bm_goto_s_{rid}")
            assert btn is not None, f"sense 行 {rid} 缺「前往 →」"
            assert btn[0] == "前往 →"
            assert callable(btn[1].get("on_click"))
        assert _button_by_key(stub, "bm_goto_s_4") is None   # entry 锚不跳
        page_btn = _button_by_key(stub, "bm_goto_5")
        assert page_btn is not None and page_btn[0] == "🔗 前往"   # page 锚先例不动

    def test_caption_documents_entry_anchor_pending(self, monkeypatch):
        """caption 如实口径：义位锚可跳＋预选动词；词条锚挂账暂不支持。"""
        stub, _ = self._render(monkeypatch)
        joined = "\n".join(stub.captions)
        assert "义位锚可一键跳转" in joined
        assert "词条锚" in joined and "挂账" in joined

    # ---- RV12-1：回调写会话（三分支）----

    def test_callback_writes_page_and_verb_task_format(self, monkeypatch):
        """verb 提取到（任务口径 title）：回调写两键 page=annotate ＋
        annotate_verb=<verb>（键在标注平台 selectbox 实例化前写入）。"""
        stub, flashes = self._render(monkeypatch)
        _, kw = _button_by_key(stub, "bm_goto_s_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert stub.session_state.get("annotate_verb") == "walk"
        assert flashes == []                      # 预置成功无附加提示

    def test_callback_writes_verb_from_live_format(self, monkeypatch):
        """sense_spine 落库格式 title 同样预置成功（两键）。"""
        stub, flashes = self._render(monkeypatch)
        _, kw = _button_by_key(stub, "bm_goto_s_2")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert stub.session_state.get("annotate_verb") == "drift"
        assert flashes == []

    def test_callback_preset_even_out_of_pilot_set(self, monkeypatch):
        """verb 在词库但不在 pilot 12 词集（如 give）：回调照写 annotate_verb
        —— Streamlit 侧的回落行为由 TestStreamlitPresetBehavior 实测记录
        （1.57 静默回落 index 默认值），回调职责止于如实写键。"""
        rows = [_bm(9, "sense", "50", "give-S3 赠予义")]
        stub, _ = self._render(monkeypatch, rows=rows)
        _, kw = _button_by_key(stub, "bm_goto_s_9")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert stub.session_state.get("annotate_verb") == "give"

    def test_callback_no_marker_only_page_plus_flash(self, monkeypatch):
        """提取不到（title 无义项段标记）：只写 page ＋ flash 引导手选
        （文案「请在标注平台选择动词 {title}」，info 级），不预置动词键。"""
        stub, flashes = self._render(monkeypatch)
        _, kw = _button_by_key(stub, "bm_goto_s_3")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert "annotate_verb" not in stub.session_state
        assert flashes == [("info", "请在标注平台选择动词 好义位")]
        assert stub.successes == []               # RV12：不回潮 st.success

    def test_callback_target_invisible_falls_back_to_page_anchor(self, monkeypatch):
        """目标页不可达（防御分支，annotate 页面层角色门折算）：回退 page 锚
        行为——只写 page（app 侧栏残留页回退兜底）＋flash 说明，不预置动词。"""
        stub, flashes = self._render(monkeypatch, me=_VIEWER_ONLY)
        _, kw = _button_by_key(stub, "bm_goto_s_1")
        kw["on_click"]()
        assert stub.session_state.get("page") == "annotate"
        assert "annotate_verb" not in stub.session_state
        assert len(flashes) == 1 and flashes[0][0] == "warning"
        assert "标注平台对当前账号不可见" in flashes[0][1]

    def test_annotate_target_visible_by_role(self):
        """可达性闸口径：admin（legacy 两位一体 dict_admin+sys_admin）→ True；
        viewer 单角色 → False；None/残缺 → False（fail-closed）。"""
        assert ua._annotate_target_visible(_ME) is True
        assert ua._annotate_target_visible(_VIEWER_ONLY) is False
        assert ua._annotate_target_visible(None) is False
        assert ua._annotate_target_visible({"id": 1}) is False
        assert "annotate" in PAGE_KEYS        # 路由键闸的前半件

    # ---- RV12 纪律（源码级锁）----

    def test_rv12_callback_uses_update_and_ui_kit_flash(self):
        """RV12-1/2：新回调写会话一律 st.session_state.update（不触发 fx39
        模块级正文期直写哨兵）；flash 走 ui_kit；零 st.success。"""
        source = inspect.getsource(ua._goto_sense_callback)
        assert "st.session_state.update(" in source
        assert "ui_kit.flash(" in source
        assert "st.success(" not in source
        assert 'st.session_state["page"]' not in source


# ============================================
# 3. 标注平台动词键在码（app.py）
# ============================================

class TestAnnotateVerbKeyInCode:
    """app.py _render_annotation_admin_view 的动词 selectbox 加
    key="annotate_verb"（FX-42；index 回退 walk 逻辑保持）。"""

    def test_selectbox_key_present(self):
        source = inspect.getsource(app_mod._render_annotation_admin_view)
        assert 'key="annotate_verb"' in source

    def test_index_walk_fallback_unchanged(self):
        """index 逻辑保持 walk 回退（FX-42 只加键，不动其余参数）。"""
        source = inspect.getsource(app_mod._render_annotation_admin_view)
        assert 'index=verbs.index("walk") if "walk" in verbs else 0' in source

    def test_callback_factory_wired_in_bookmarks(self):
        """书签段接线契约：sense 行按钮挂 _goto_sense_callback（me＋title）。"""
        source = inspect.getsource(ua._render_my_bookmarks)
        assert "_goto_sense_callback(me, display_title)" in source
        assert 'key=f"bm_goto_s_{row_id}"' in source


# ============================================
# 4. Pilot 集外 verb 预置行为实测（AppTest 记录 Streamlit 1.57 语义）
# ============================================

# 最小复现应用：probe_mode='shrink' 模拟「仅试点过滤收缩」（fly 被丢出
# options），其余为「全部动词 3 词」——同一会话可跨轮切态（实测不复活）。
_PROBE_APP = (
    "import streamlit as st\n"
    "verbs_all = ['run', 'walk', 'fly']\n"
    "verbs = ['run', 'walk'] if st.session_state.get('probe_mode') == 'shrink' "
    "else verbs_all\n"
    "st.selectbox('选择动词', options=verbs,\n"
    "             index=verbs.index('walk') if 'walk' in verbs else 0,\n"
    "             key='annotate_verb')\n"
)


class TestStreamlitPresetBehavior:
    """预置 session_state[key] 的 Streamlit 1.57 实测记录（行为契约固化）。"""

    def test_no_preset_index_walk_fallback(self):
        """无预置：index 回退 walk（改动前后行为一致，探针基线）。"""
        at = AppTest.from_string(_PROBE_APP)
        at.run()
        assert not at.exception
        assert at.selectbox[0].value == "walk"

    def test_preset_in_options_wins_over_index(self):
        """预置值在 options 内：生效且优先于 index（官方「程序化设值」）。"""
        at = AppTest.from_string(_PROBE_APP)
        at.session_state["annotate_verb"] = "fly"
        at.run()
        assert not at.exception
        assert at.selectbox[0].value == "fly"

    def test_preset_out_of_options_silently_falls_back(self):
        """预置值不在 options（pilot 收缩）：1.57 实测静默回落 index 默认值
        （walk），不抛异常 —— 会话预置不崩页。"""
        at = AppTest.from_string(_PROBE_APP)
        at.session_state["probe_mode"] = "shrink"
        at.session_state["annotate_verb"] = "fly"
        at.run()
        assert not at.exception
        assert at.selectbox[0].value == "walk"

    def test_fallback_overwrites_session_no_resurrection(self):
        """回落值覆盖 session_state（实测同会话跨轮）：残留预置不复活 ——
        下一轮 options 恢复含 fly，selectbox 仍是 walk（不会突然跳回预置）。"""
        at = AppTest.from_string(_PROBE_APP)
        at.session_state["probe_mode"] = "shrink"
        at.session_state["annotate_verb"] = "fly"
        at.run()
        assert at.session_state["annotate_verb"] == "walk"   # 已被回落值覆盖
        at.session_state["probe_mode"] = None                # options 恢复 3 词
        at.run()
        assert not at.exception
        assert at.selectbox[0].value == "walk"               # 未跳回预置 fly


# ============================================
# 5. 真库集成：标注平台页预置动词生效（skipif 无 MySQL，test_pages 同口径）
# ============================================

_ADMIN_USER = {"id": 1, "username": "admin", "display_name": "管理员",
               "role": "admin"}
APP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "app.py")


def _mysql_reachable() -> bool:
    try:
        import pymysql

        import src.mysql_db as _db
        conn = pymysql.connect(
            host=_db.MYSQL_HOST, port=_db.MYSQL_PORT, user=_db.MYSQL_USER,
            password=_db.MYSQL_PASSWORD, charset=_db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()

pytestmark_mysql = pytest.mark.skipif(
    not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-42 真库集成用例")


@pytestmark_mysql
class TestAnnotatePagePresetIntegration:
    """AppTest 跑真实标注平台页：书签跳转回调写的 annotate_verb 键在
    selectbox 实例化前已入会话 → 页面渲染即选中预置动词（全链闭环）。"""

    @staticmethod
    def _verb_selectbox(at):
        """标注平台页「选择动词」selectbox（admin 快速通道唯一实例）。"""
        boxes = [s for s in at.selectbox if s.label == "选择动词"]
        assert len(boxes) == 1, f"期望唯一「选择动词」，实得 {len(boxes)}"
        return boxes[0]

    def test_preset_pilot_verb_preselected(self):
        """预置 pilot 动词 drift（在词库、在 pilot 12 词集）：页面渲染即选中
        drift（回调两键写入的全链等效验证），无 exception。"""
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.session_state["user"] = _ADMIN_USER
        at.session_state["page"] = "annotate"
        at.session_state["annotate_verb"] = "drift"
        at.run()
        assert not at.exception
        assert self._verb_selectbox(at).value == "drift"

    def test_no_preset_index_fallback_walk(self):
        """无预置：index 回退 walk（改动前后首渲染行为一致）。"""
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.session_state["user"] = _ADMIN_USER
        at.session_state["page"] = "annotate"
        at.run()
        assert not at.exception
        assert self._verb_selectbox(at).value == "walk"
