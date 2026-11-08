"""批次 12 R1 权限走查十项修复回归测试（FX2）。

覆盖（findings 复现语义重跑；修复前后对照见交付报告）：
  R1-1  数据层直调面第一批：users_db 六函数（change_password/set_role/
        grant_role/revoke_role/create_user＋页面调用点配套的 set_active）与
        annotation_flow.save_adjudication 的 actor=None kwarg —— 低权 actor
        dict 抛 PermissionError（本文件只断「签名在场」，行为用例在
        test_users_db.TestR1ActorGate / test_annotation_flow）；
  R1-2  四处 legacy role 门（app.py 标注平台/标注提交/仲裁面板、
        reliability.py 信度页）改 effective_six_roles 判定 —— AppTest
        权限矩阵八会话：授予式用户（legacy 列与 roles 快照不一致）放行、
        viewer/未登录照旧拦截；
  R1-5  collab_pages 收件箱裁决按钮区过 _can_adjudicate_inbox（dict_admin/
        reviewer）—— 其余角色只读灰注；
  R1-6  app._logout 会话全清＋启动白名单：业务键（verb_result 等）登出即
        清、user 清除、页面回搜索、退出提示在场；
  R1-7  users_admin_page._gate_error manage_action 扩展（停用/启用管理角色
        账号须 dict_admin）；
  R1-8  dict_admin_pages 五写调用点（add_member/remove_member/define_field/
        deprecate_field/set_value）补 guards.require_dict_admin()（源级
        断言在场，语义由 test_guards 覆盖）；
  R1-10 writing_pages 版本历史脱敏纯件（_history_realname /
        _pseudonym_factory 的页面级用例在 test_writing_pages）。

两层结构（与 test_r3_fixes / test_integration_apptest 同约定）：
  * 纯层（签名/源级/docstring）不碰数据库 —— 本地与 CI 全跑；
  * AppTest 权限矩阵依赖真实 MySQL（独立测试库 web_word_users_test，模块
    级 fixture，pytest 串行与其他模块互不污染）；MySQL 不可用整类 skip。
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import src.mysql_db as db  # noqa: E402
from src import collab_pages  # noqa: E402
from src.annotation_flow import save_adjudication  # noqa: E402
from src.users_db import (  # noqa: E402
    change_password,
    create_user,
    ensure_user_tables,
    grant_role,
    revoke_role,
    set_active,
    set_role,
)

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
TEST_DB = "web_word_users_test"  # 授权覆盖库名（pytest 串行，见模块 docstring）
TIMEOUT = 180


# ============================================
# 纯层：签名 / 源级断言（无数据库）
# ============================================

class TestR1SignaturesAndSources:
    """修复面签名与调用点源级断言（keyword 缺省保证既有调用兼容）。"""

    def test_users_db_six_write_functions_have_actor_keyword(self):
        """R1-1：users_db 六函数 actor=None keyword-only（缺省不破坏既有调用）。"""
        for fn in (change_password, set_role, grant_role, revoke_role,
                   create_user, set_active):
            sig = inspect.signature(fn)
            assert "actor" in sig.parameters, fn.__name__
            assert sig.parameters["actor"].default is None, fn.__name__
            assert sig.parameters["actor"].kind == inspect.Parameter.KEYWORD_ONLY, \
                fn.__name__

    def test_save_adjudication_has_actor_keyword(self):
        """R1-1：save_adjudication actor=None keyword-only。"""
        sig = inspect.signature(save_adjudication)
        assert sig.parameters["actor"].default is None
        assert sig.parameters["actor"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_users_db_actor_gate_docstring_declares_direct_call_policy(self):
        """直调面口径 docstring 在场：None=系统作业；页面调用点必须传 actor。"""
        for fn in (change_password, set_role, grant_role, revoke_role,
                   create_user, set_active):
            doc = fn.__doc__ or ""
            assert "直调面" in doc, fn.__name__
            assert "None" in doc and "系统作业" in doc, fn.__name__
        assert "直调面" in (save_adjudication.__doc__ or "")

    def test_dict_admin_pages_five_write_sites_guarded(self):
        """R1-8：五个写调用点函数源内含 guards.require_dict_admin() 闸门。"""
        import src.dict_admin_pages as dp

        for fn_name in ("_render_add_member_form", "_render_remove_member_form",
                        "_render_define_field_form", "_render_deprecate_field_form",
                        "_render_write_value_form"):
            src = inspect.getsource(getattr(dp, fn_name))
            assert "guards.require_dict_admin()" in src, fn_name

    def test_users_admin_page_call_sites_pass_actor(self):
        """R1-1 调用点：users_admin_page 五个写调用（set_role/create_user/
        grant_role/revoke_role/set_active）源内传 actor=当前会话用户。"""
        import src.users_admin_page as uap

        for fn_name, marker in (
            ("_render_change_role_form", "set_role(uid, role, actor=me)"),
            ("_render_create_user_form", "actor=me"),
            ("_render_role_grant_panel", "actor=me"),
            ("_render_toggle_active_form", "set_active(uid, target_active, actor=me)"),
        ):
            src = inspect.getsource(getattr(uap, fn_name))
            assert marker in src, fn_name

    def test_users_admin_toggle_has_management_gate(self):
        """R1-7：停用/启用表单走 _gate_error manage_action 管理闸门。"""
        import src.users_admin_page as uap

        src = inspect.getsource(uap._render_toggle_active_form)
        assert "manage_action" in src
        assert "停用/启用管理角色账号" in src

    def test_collab_inbox_adjudicate_gate_in_source(self):
        """R1-5：收件箱按钮区按 _can_adjudicate_inbox 收口（其余角色灰注）。"""
        src = inspect.getsource(collab_pages._render_pending_inbox)
        assert "_can_adjudicate_inbox(me)" in src  # R6-4 改名
        assert "裁决权归词典管理员/审校" in src

    def test_logout_whitelist_constants(self):
        """R1-6：登出白名单恰三类基建键；flash 旗标常量在场。"""
        import src.app as app

        assert app._LOGOUT_KEEP_KEYS == frozenset({
            "_user_tables_ready", "_wordforms_table_ready", "sidebar_collapsed",
        })
        assert app._LOGOUT_FLASH_KEY == "_logout_flash"

    def test_reliability_gate_uses_effective_roles(self):
        """R1-2：信度页角色门源内走 effective_six_roles 允许集判定。"""
        import src.reliability as rel

        src = inspect.getsource(rel.render_reliability_page)
        assert "effective_six_roles" in src
        assert "dict_admin" in src and "sys_admin" in src and "reviewer" in src


# ============================================
# AppTest 权限矩阵：八会话 × 四门（R1-2/R1-5/R1-6）
# ============================================

def _pget(at, key, default=None):
    """AppTest 会话读取（SafeSessionState 不支持 .get()）。"""
    try:
        return at.session_state[key]
    except Exception:  # noqa: BLE001
        return default


def _page_text(at) -> str:
    """主区域全部文本（markdown/caption/标题/各消息通道）。"""
    parts = []
    for accessor in ("markdown", "caption", "header", "subheader", "title",
                     "info", "warning", "error", "success"):
        elements = getattr(at, accessor, None) or []
        parts.extend(str(e.value) for e in elements)
    return "\n".join(parts)


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _run_page_as(page: str, user):
    """直接注入会话用户并打开页面（test_pages/test_integration_apptest 同手法：
    模拟「会话残留/越权直入」路径 —— 入口 role gate 必须拦下）。"""
    at = _new_at()
    if user is not None:
        at.session_state["user"] = user
    at.session_state["page"] = page
    at.run()
    return at


def _any_warning_containing(at, needle: str) -> bool:
    return any(needle in str(w.value) for w in at.warning)


def _has_button(at, needle: str) -> bool:
    return any(needle in str(b.label) for b in at.button)


# 八会话（用户名 → 会话 user dict；id/roles 由 r1_env 按库内真实账号填充 ——
# 授予式用户 = legacy role 列与 user_roles 授予不一致，R1-2 修复的对象形态）。
# 会话形态与 verify_login_full 输出一致（id/username/display_name/role/roles）。
_R1_SESSIONS = {
    "legacy_admin": {"id": 0, "username": "r1_admin", "display_name": "内置管理员",
                     "role": "admin"},
    "legacy_reviewer": {"id": 0, "username": "r1_rev", "display_name": "存量审校",
                        "role": "reviewer"},
    "granted_annotator": {"id": 0, "username": "r1_grant_ann", "display_name": "授予标注",
                          "role": "viewer", "roles": ["annotator", "viewer"]},
    "granted_reviewer": {"id": 0, "username": "r1_grant_rev", "display_name": "授予审校",
                         "role": "viewer", "roles": ["reviewer", "viewer"]},
    "granted_dict_admin": {"id": 0, "username": "r1_grant_chief",
                           "display_name": "授予词典管理",
                           "role": "annotator", "roles": ["dict_admin", "annotator"]},
    "granted_editor": {"id": 0, "username": "r1_grant_editor", "display_name": "授予撰写",
                       "role": "viewer", "roles": ["editor", "viewer"]},
    "pure_viewer": {"id": 0, "username": "r1_view", "display_name": "只读",
                    "role": "viewer", "roles": ["viewer"]},
}


def _sessions() -> dict:
    """八会话快照（r1_env 已把各账号真实 users.id 回填进 _R1_SESSIONS）。"""
    assert _R1_SESSIONS["legacy_admin"]["id"] > 0, "r1_env fixture 未就位"
    return _R1_SESSIONS


@pytest.fixture(scope="module")
def r1_env():
    """建空测试库＋八会话账号（授予式用户走 grant_role 真实落 user_roles），
    结束 DROP。库结构与 test_integration_apptest.r3_env 同源（init_database
    建 oald_senses 等核心表；ai_ledger 表另 ensure，供 R1-5 收件箱用例）。"""
    import pymysql
    from src.ai_ledger import ensure_ai_ledger_tables, record_proposal

    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.close()
    except pymysql.err.OperationalError as e:
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 R1 修复矩阵: {e}")

    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    try:
        assert db.init_database(), "测试库初始化失败"
        ensure_user_tables()
        # 会话 id 与库内账号一一对应（直调面用例用到真实 id）
        uid_admin = create_user("r1_admin", "r1-admin-pw", "内置管理员", "admin")
        uid_rev = create_user("r1_rev", "r1-rev-pw", "存量审校", "reviewer")
        uid_ann = create_user("r1_grant_ann", "r1-ann-pw", "授予标注", "viewer")
        assert grant_role(uid_ann, "annotator") is True
        uid_grev = create_user("r1_grant_rev", "r1-grev-pw", "授予审校", "viewer")
        assert grant_role(uid_grev, "reviewer") is True
        uid_chief = create_user("r1_grant_chief", "r1-chief-pw", "授予词典管理",
                                "annotator")
        assert grant_role(uid_chief, "dict_admin") is True
        uid_editor = create_user("r1_grant_editor", "r1-ed-pw", "授予撰写", "viewer")
        assert grant_role(uid_editor, "editor") is True
        uid_view = create_user("r1_view", "r1-view-pw", "只读", "viewer")
        # 真实 users.id 回填（授权式用户 = legacy 列与 user_roles 授予不一致）
        _R1_SESSIONS["legacy_admin"]["id"] = int(uid_admin)
        _R1_SESSIONS["legacy_reviewer"]["id"] = int(uid_rev)
        _R1_SESSIONS["granted_annotator"]["id"] = int(uid_ann)
        _R1_SESSIONS["granted_reviewer"]["id"] = int(uid_grev)
        _R1_SESSIONS["granted_dict_admin"]["id"] = int(uid_chief)
        _R1_SESSIONS["granted_editor"]["id"] = int(uid_editor)
        _R1_SESSIONS["pure_viewer"]["id"] = int(uid_view)
        # R1-5：一条 draft 通道 pending 提案（收件箱非空，按钮区可判定）
        ensure_ai_ledger_tables()
        assert record_proposal("draft", "admission", "oald_senses:1",
                               {"admission": "Y"}) > 0
        yield
    finally:
        db.MYSQL_DATABASE = old_db  # 先还原全局再删库（与既有 fixture 同约定）
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()


class TestR1PermissionMatrix:
    """R1-2 四门 × 八会话（AppTest；空库降级路径即判定哨兵）。"""

    # --- 标注平台页（app.render_annotation_page） ---

    def test_annotate_legacy_admin_gets_fast_track(self, r1_env):
        """legacy admin（映射两位一体）→ 直写权威层快速通道（现状不变）。"""
        at = _run_page_as("annotate", _sessions()["legacy_admin"])
        assert not at.exception
        assert "管理员快速通道" in _page_text(at)
        assert not _any_warning_containing(at, "无权限")

    def test_annotate_granted_annotator_no_longer_blocked(self, r1_env):
        """R1-2 复现⑥修复：授予式 annotator（legacy 列 viewer）进标注平台。"""
        at = _run_page_as("annotate", _sessions()["granted_annotator"])
        assert not at.exception
        texts = _page_text(at)
        assert not _any_warning_containing(at, "无权限")
        assert "提交流" in texts          # 多人提交流渲染（flow caption）
        assert "管理员快速通道" not in texts
        assert "分歧清单与仲裁" not in texts  # annotator 不见仲裁面板（独立性）

    def test_annotate_granted_reviewer_sees_panel(self, r1_env):
        """授予式 reviewer → 提交流 + 仲裁面板。"""
        at = _run_page_as("annotate", _sessions()["granted_reviewer"])
        assert not at.exception
        assert not _any_warning_containing(at, "无权限")
        texts = _page_text(at)
        assert "提交流" in texts
        assert "分歧清单与仲裁" in texts

    def test_annotate_granted_dict_admin_gets_fast_track_and_panel(self, r1_env):
        """授予式 dict_admin → 快速通道（直写权威层=词典管理员口径）。"""
        at = _run_page_as("annotate", _sessions()["granted_dict_admin"])
        assert not at.exception
        texts = _page_text(at)
        assert not _any_warning_containing(at, "无权限")
        assert "管理员快速通道" in texts

    def test_annotate_granted_editor_passes_flow(self, r1_env):
        """授予式 editor（任务矩阵撰写→editor+）→ 提交流，无面板。"""
        at = _run_page_as("annotate", _sessions()["granted_editor"])
        assert not at.exception
        texts = _page_text(at)
        assert not _any_warning_containing(at, "无权限")
        assert "提交流" in texts
        assert "分歧清单与仲裁" not in texts

    def test_annotate_viewer_blocked(self, r1_env):
        """viewer（纯只读，含授予式单 viewer）照旧拦截。"""
        at = _run_page_as("annotate", _sessions()["pure_viewer"])
        assert not at.exception
        assert _any_warning_containing(at, "无权限")

    def test_annotate_anonymous_blocked(self, r1_env):
        """未登录 → 「请先登录」（登录门不受 R1-2 影响）。"""
        at = _run_page_as("annotate", None)
        assert not at.exception
        assert _any_warning_containing(at, "请先登录")

    # --- 标注提交页（app.render_submission_page） ---

    def test_submission_granted_annotator_no_longer_blocked(self, r1_env):
        """R1-2 复现⑥修复：授予式 annotator 进标注提交页，且无仲裁面板。"""
        at = _run_page_as("submission", _sessions()["granted_annotator"])
        assert not at.exception
        texts = _page_text(at)
        assert not _any_warning_containing(at, "无权限")
        assert "提交流" in texts
        assert "分歧清单与仲裁" not in texts

    def test_submission_granted_reviewer_sees_panel(self, r1_env):
        """授予式 reviewer → 提交流 + 仲裁面板（复现⑥ :2787 门）。"""
        at = _run_page_as("submission", _sessions()["granted_reviewer"])
        assert not at.exception
        texts = _page_text(at)
        assert not _any_warning_containing(at, "无权限")
        assert "分歧清单与仲裁" in texts

    def test_submission_viewer_blocked(self, r1_env):
        """viewer 照旧拦截。"""
        at = _run_page_as("submission", _sessions()["pure_viewer"])
        assert not at.exception
        assert _any_warning_containing(at, "无权限")

    # --- 仲裁面板入口（app.render_reviewer_panel；复现⑥ :3004 门） ---

    def test_reviewer_panel_granted_reviewer_passes(self, r1_env):
        """授予式 reviewer 直接注入 submission 页已覆盖；此处验 annotator
        与 editor 不见面板入口（看全部入口不暴露给盲标角色，用户决策④）。"""
        for key in ("granted_annotator", "granted_editor"):
            at = _run_page_as("submission", _sessions()[key])
            assert not at.exception, key
            assert "分歧清单与仲裁" not in _page_text(at), key

    # --- 信度报告页（reliability.render_reliability_page；复现⑥ :795 门） ---

    def test_reliability_granted_reviewer_no_longer_blocked(self, r1_env):
        """R1-2 复现⑥修复：授予式 reviewer 进信度页（空库走 info 降级哨兵）。"""
        at = _run_page_as("reliability", _sessions()["granted_reviewer"])
        assert not at.exception
        texts = _page_text(at)
        assert not _any_warning_containing(at, "仅对 reviewer / admin 开放")
        assert "还没有已提交的标注" in texts   # 页面本体渲染（空库降级）

    def test_reliability_legacy_admin_and_reviewer_pass(self, r1_env):
        """legacy admin / legacy reviewer 现状不变。"""
        for key in ("legacy_admin", "legacy_reviewer"):
            at = _run_page_as("reliability", _sessions()[key])
            assert not at.exception, key
            assert not _any_warning_containing(
                at, "仅对 reviewer / admin 开放"), key

    def test_reliability_granted_annotator_and_viewer_blocked(self, r1_env):
        """annotator/viewer 单角色照旧拦截（允许集未放大）。"""
        for key in ("granted_annotator", "pure_viewer"):
            at = _run_page_as("reliability", _sessions()[key])
            assert not at.exception, key
            assert _any_warning_containing(
                at, "仅对 reviewer / admin 开放"), key


class TestR1LogoutFullClear:
    """R1-6：登出全清＋白名单（AppTest，业务键不跨登出存活）。"""

    def test_logout_clears_business_keys_and_user(self, r1_env):
        """点退出：user/业务键全清、页面回搜索、「请先登录」提示在场。

        注：AppTest 的 radio widget 状态取自上一棵元素树 —— 注入 user 后先
        空跑一轮让页面 radio 的 options 按新角色集重渲染，再切 submission，
        否则旧树 options（匿名集）不含「📥 标注提交」会 ValueError。
        """
        at = _new_at()
        at.run()
        at.session_state["user"] = _sessions()["granted_annotator"]
        at.run()                                # radio options 按新角色重渲染
        # 预置业务键（旧版登出后跨会话存活的泄漏面）＋切到受保护页
        at.session_state["verb_result"] = {"verb": "walk"}
        at.session_state["show_result"] = True
        at.session_state["card_expanded"] = {"prototype": False}
        at.session_state["_display_def_cache"] = {"walk": "x"}
        at.session_state["hot_filter"] = "跑"
        at.session_state["page"] = "submission"
        at.run()
        assert _pget(at, "user") is not None
        assert "提交流" in _page_text(at), "受保护页未按注入用户渲染"

        logout = [b for b in at.sidebar.button if "退出登录" in str(b.label)]
        assert logout, "退出按钮未找到"
        logout[0].click()
        at.run()
        assert not at.exception
        assert _pget(at, "user") is None, "退出后 session user 未清除"
        for key in ("verb_result", "show_result",
                    "_display_def_cache", "hot_filter", "_user_db_backed"):
            assert _pget(at, key) is None, f"业务键 {key} 登出后残留（R1-6）"
        # card_expanded 被 _logout 清除后，本轮脚本顶层的会话初始化会重建
        # 缺省值 —— 断言其已被重置为缺省（而非保留注入的 prototype=False）
        card = _pget(at, "card_expanded")
        assert card is None or card.get("prototype") is True, \
            "card_expanded 未被登出重置（R1-6）"
        # 白名单基建键保留
        assert _pget(at, "sidebar_collapsed") is not None
        assert _pget(at, "_user_tables_ready") is not None
        assert _pget(at, "page") == "search", "残留页未回搜索页"
        assert _any_warning_containing(at, "请先登录"), "登出提示未出现"


class TestR1CollabInboxGating:
    """R1-5：收件箱裁决按钮区按 _can_adjudicate_inbox 收口（AppTest）。"""

    def test_granted_annotator_sees_readonly_gray_note(self, r1_env):
        """授予式 annotator：条目可见（知情），按钮替换为灰注，无裁决按钮。"""
        at = _run_page_as("ai_hub", _sessions()["granted_annotator"])
        assert not at.exception
        assert any("待裁决 AI 建议" in str(e.value) for e in at.info) or \
            "待裁决 AI 建议" in _page_text(at)
        assert not _has_button(at, "采纳"), "annotator 不应见裁决按钮（R1-5）"
        assert not _has_button(at, "否决")
        captions = [str(c.value) for c in at.caption]
        assert any("裁决权归词典管理员/审校" in c for c in captions), captions

    def test_granted_dict_admin_sees_decide_buttons(self, r1_env):
        """授予式 dict_admin：裁决按钮区照常渲染（✅ 采纳 / ⛔ 否决）。"""
        at = _run_page_as("ai_hub", _sessions()["granted_dict_admin"])
        assert not at.exception
        assert _has_button(at, "采纳")
        assert _has_button(at, "否决")
        assert _has_button(at, "修改后采纳")

    def test_granted_reviewer_sees_decide_buttons(self, r1_env):
        """授予式 reviewer：裁决权在手（R1-5 允许集 dict_admin/reviewer）。"""
        at = _run_page_as("ai_hub", _sessions()["granted_reviewer"])
        assert not at.exception
        assert _has_button(at, "采纳")

    def test_granted_editor_readonly(self, r1_env):
        """授予式 editor：不在允许集 → 只读灰注。"""
        at = _run_page_as("ai_hub", _sessions()["granted_editor"])
        assert not at.exception
        assert not _has_button(at, "采纳")
        captions = [str(c.value) for c in at.caption]
        assert any("裁决权归词典管理员/审校" in c for c in captions)


class TestR1ToggleManagementGate:
    """R1-7：停用/启用管理闸门（_gate_error manage_action 分支，直调纯件）。"""

    def test_toggling_manager_requires_dict_admin(self, r1_env):
        """目标兼有管理角色 → 操作人须 dict_admin：sys_admin/低权被拒。"""
        from src.users_admin_page import _gate_error

        target = create_user("r1_mgr_target", "pw123456", "管理角色目标", "viewer")
        assert grant_role(target, "sys_admin") is True
        sys_op = {"id": 999, "username": "r1_sysop", "role": "viewer",
                  "roles": ["sys_admin"]}
        chief_op = {"id": 998, "username": "r1_chief_op", "role": "viewer",
                    "roles": ["dict_admin"]}
        err = _gate_error(sys_op, "", target_uid=target,
                          manage_action="停用/启用管理角色账号")
        assert err is not None and "词典管理员" in err
        assert _gate_error(chief_op, "", target_uid=target,
                           manage_action="停用/启用管理角色账号") is None

    def test_toggling_plain_account_allows_both_admins(self, r1_env):
        """普通账号：两类管理员皆可停用/启用（账号生命周期归平台管理员）。"""
        from src.users_admin_page import _gate_error

        target = create_user("r1_plain_target", "pw123456", "普通目标", "viewer")
        sys_op = {"id": 997, "username": "r1_sysop2", "role": "viewer",
                  "roles": ["sys_admin"]}
        assert _gate_error(sys_op, "", target_uid=target,
                           manage_action="停用/启用管理角色账号") is None
        low_op = {"id": 996, "username": "r1_lowop", "role": "viewer",
                  "roles": ["annotator"]}
        err = _gate_error(low_op, "", target_uid=target,
                          manage_action="停用/启用管理角色账号")
        assert err is not None
