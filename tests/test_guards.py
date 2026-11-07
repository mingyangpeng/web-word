"""中央权限闸门纯函数测试（src/guards.py，批次 6-T 新建）。

guards 判定**不读库**（会话/显式入参即判定，见模块 docstring），本文件
零数据库依赖、本地与 CI 全跑：显式传 actor dict 注入用户，逐角色断言
放行/拒绝与拒绝文案口径（文案被集成测试与页面 st.error 直出，逐字契约）。

覆盖面（批次 6-T 对 T 的要求）：
  require_role 通用角色闸门（批次 6 新增）—— 允许集交集放行 / 管理角色仅
  词典管理员（文案与 users_admin_page 硬闸门口径逐字对齐）/ viewer 双管理员 /
  职能角色 / 空 allowed fail-closed / 未登录 / 非 dict 入参 / 返回原 actor；
  require_dict_admin 既有口径回归 —— 未登录拒绝、非词典管理员拒绝、
  allow_system 显式越过、legacy admin 两位一体放行（签名未改）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import guards  # noqa: E402

# 各角色的会话用户构造（role=legacy 列、roles=会话快照，与 app 登录态同构）
DICT_ADMIN = {"id": 1, "username": "da", "role": "viewer", "roles": ["dict_admin"]}
PURE_SYS_ADMIN = {"id": 2, "username": "sa", "role": "viewer", "roles": ["sys_admin"]}
LEGACY_ADMIN = {"id": 3, "username": "admin", "role": "admin"}  # 两位一体（映射）
EDITOR = {"id": 4, "username": "ed", "role": "viewer", "roles": ["editor"]}
VIEWER = {"id": 5, "username": "vw", "role": "viewer", "roles": ["viewer"]}


# ============================================
# require_role（批次 6-T 新增通用角色闸门）
# ============================================

class TestRequireRole:
    """「动作 → 允许角色集」的判定收口（users_admin_page 四写路径消费方）。"""

    def test_pass_returns_actor_for_audit(self):
        """放行返回原 actor dict（调用方继续取 user id 落审计，同 require_dict_admin）。"""
        assert guards.require_role(DICT_ADMIN, allowed={"dict_admin"},
                                   action="授予/撤销管理角色") is DICT_ADMIN

    def test_admin_roles_require_dict_admin(self):
        """管理角色闸门：仅词典管理员；纯平台管理员拒绝（不得自行提权）。"""
        assert guards.require_role(LEGACY_ADMIN, allowed={"dict_admin"},
                                   action="授予/撤销管理角色") is LEGACY_ADMIN
        with pytest.raises(PermissionError) as ei:
            guards.require_role(PURE_SYS_ADMIN, allowed={"dict_admin"},
                                action="授予/撤销管理角色")
        # 拒绝文案与集成测试断言的硬闸门口径逐字对齐（页面 st.error 直出）
        assert "授予/撤销管理角色仅词典管理员可执行" in str(ei.value)

    def test_viewer_gate_allows_both_admins(self):
        """viewer 建号基线（三级链第一级）：词典管理员或平台管理员皆可。"""
        allowed = {"dict_admin", "sys_admin"}
        assert guards.require_role(DICT_ADMIN, allowed=allowed,
                                   action="viewer 角色的授予/撤销") is DICT_ADMIN
        assert guards.require_role(PURE_SYS_ADMIN, allowed=allowed,
                                   action="viewer 角色的授予/撤销") is PURE_SYS_ADMIN
        with pytest.raises(PermissionError):
            guards.require_role(EDITOR, allowed=allowed,
                                action="viewer 角色的授予/撤销")

    def test_functional_roles_dict_admin_only_by_default(self):
        """职能角色默认仅词典管理员（N 的开关语义在调用方选择 allowed 集）。"""
        with pytest.raises(PermissionError) as ei:
            guards.require_role(PURE_SYS_ADMIN, allowed={"dict_admin"},
                                action="职能角色的授予/撤销")
        assert "职能角色的授予/撤销仅词典管理员可执行" in str(ei.value)
        # 开关放宽口径 = allowed 换成双管理员集（guards 侧同一判定）
        assert guards.require_role(PURE_SYS_ADMIN,
                                   allowed={"dict_admin", "sys_admin"},
                                   action="职能角色的授予/撤销") is PURE_SYS_ADMIN

    def test_empty_allowed_fails_closed(self):
        """空/None allowed 一律拒绝（fail-closed：未配置允许角色的动作不可执行）。"""
        for bad_allowed in (set(), None, [], ("",), (None,)):
            with pytest.raises(PermissionError) as ei:
                guards.require_role(LEGACY_ADMIN, allowed=bad_allowed, action="x 操作")
            assert "fail-closed" in str(ei.value)

    def test_not_logged_in_rejected(self):
        """actor=None 且会话无用户（裸脚本态）→ 未登录拒绝；非 dict 入参同拒。"""
        with pytest.raises(PermissionError) as ei:
            guards.require_role(None, allowed={"dict_admin"}, action="写操作")
        assert "未登录" in str(ei.value)
        for bad in ("admin", 42, ["dict_admin"]):
            with pytest.raises(PermissionError):
                guards.require_role(bad, allowed={"dict_admin"}, action="写操作")

    def test_message_names_allowed_roles_and_action(self):
        """拒绝文案点名动作与允许角色中文名（页面直出，可读性契约）。"""
        with pytest.raises(PermissionError) as ei:
            guards.require_role(VIEWER, allowed={"dict_admin", "sys_admin"},
                                action="viewer 角色的授予/撤销")
        msg = str(ei.value)
        assert "viewer 角色的授予/撤销" in msg
        assert "词典管理员" in msg and "平台管理员" in msg
        assert "viewer" in msg  # 当前有效角色集如实点名

    def test_invalid_role_names_in_allowed_ignored(self):
        """allowed 里的非字符串/空串成员被剔除（垃圾入参不放大也不误伤合法角色）。"""
        # 剔除 3/"" 后仍含 dict_admin → legacy admin 放行
        assert guards.require_role(LEGACY_ADMIN, allowed={"dict_admin", 3, ""},
                                   action="写操作") is LEGACY_ADMIN
        # 集合只含垃圾成员 → 剔除后为空 → fail-closed 拒绝
        with pytest.raises(PermissionError):
            guards.require_role(LEGACY_ADMIN, allowed={3, "", None},
                                action="写操作")


# ============================================
# require_dict_admin 既有口径回归（批次 6-T 未改签名，防收口回归）
# ============================================

class TestRequireDictAdminRegression:
    """批次 6-T 只新增 require_role，require_dict_admin 签名与口径不变。"""

    def test_signature_unchanged(self):
        import inspect

        sig = inspect.signature(guards.require_dict_admin)
        assert list(sig.parameters) == ["actor", "allow_system"]
        assert sig.parameters["allow_system"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["allow_system"].default is False

    def test_legacy_admin_two_in_one_passes(self):
        """legacy role=='admin' 经映射两位一体（dict_admin+sys_admin）自然放行。"""
        assert guards.require_dict_admin(LEGACY_ADMIN) is LEGACY_ADMIN
        assert guards.require_dict_admin(DICT_ADMIN) is DICT_ADMIN

    def test_sys_admin_and_editor_rejected(self):
        """仅 sys_admin / 职能角色都不是词典管理员（§15 导入同权）。"""
        for user in (PURE_SYS_ADMIN, EDITOR, VIEWER):
            with pytest.raises(PermissionError) as ei:
                guards.require_dict_admin(user)
            assert "词典管理员" in str(ei.value)

    def test_not_logged_in_and_bad_input(self):
        with pytest.raises(PermissionError) as ei:
            guards.require_dict_admin(None)
        assert "未登录" in str(ei.value)
        with pytest.raises(PermissionError):
            guards.require_dict_admin("admin")

    def test_allow_system_explicit_bypass(self):
        """allow_system=True 供系统作业显式越过（返回哑 system 主体）。"""
        system = guards.require_dict_admin(allow_system=True)
        assert system["username"] == "__system__"
        assert "dict_admin" in system["roles"]


# ============================================
# 页面闸门口径映射（users_admin_page._gate_error → guards.require_role 收口）
# ============================================

class TestUsersAdminGateMapping:
    """users_admin_page 四写路径的「目标角色 → allowed 集」映射（无 DB 判定）。

    判定实现已收口到 guards.require_role（单一事实源）；这里只锁页面侧
    映射口径与 N 的开关语义（含撤方向旁路封堵的 DB-free 部分）。
    """

    @pytest.fixture
    def gate(self):
        from src import users_admin_page

        return users_admin_page._gate_error

    def test_grant_paths_via_guards_mapping(self, gate):
        """授予/撤销面板口径：管理角色仅词典管理员；viewer 双管理员；职能仅词典管理员。"""
        assert gate(PURE_SYS_ADMIN, "dict_admin") is not None     # 不得自行提权
        assert gate(DICT_ADMIN, "sys_admin") is None
        assert gate(PURE_SYS_ADMIN, "viewer") is None             # 建号基线
        assert gate(EDITOR, "viewer") is not None
        assert gate(PURE_SYS_ADMIN, "reviewer") is not None       # 职能仅词典管理员
        assert gate(DICT_ADMIN, "annotator") is None
        assert gate(LEGACY_ADMIN, "editor") is None
        assert gate(DICT_ADMIN, "root") is not None               # 未知角色 fail-closed

    def test_legacy_baseline_mapping(self, gate):
        """改基线/建号口径：legacy 'admin' ≙ 管理角色授予，同闸。"""
        assert gate(PURE_SYS_ADMIN, "admin") is not None
        assert gate(LEGACY_ADMIN, "admin") is None
        assert gate(PURE_SYS_ADMIN, "viewer") is None
        assert gate(EDITOR, "annotator") is not None

    def test_functional_grant_switch_widens_allowed_set(self, gate, monkeypatch):
        """N 开关语义：翻转后职能角色对纯平台管理员放行（判定实现仍在 guards）。"""
        from src import users_admin_page

        assert gate(PURE_SYS_ADMIN, "reviewer") is not None       # 默认 False：拒
        monkeypatch.setattr(
            users_admin_page, "_SYS_ADMIN_TRANSITION_FUNCTIONAL_GRANT", True,
        )
        assert gate(PURE_SYS_ADMIN, "reviewer") is None           # 放宽：过
        assert gate(EDITOR, "reviewer") is not None               # 普通角色仍拒
        # 管理角色闸门不随开关放宽（开关只管职能角色）
        assert gate(PURE_SYS_ADMIN, "dict_admin") is not None

    def test_denial_message_carries_canonical_wording(self, gate):
        """拒绝文案与集成测试断言的硬闸门口径逐字对齐（⛔ 前缀 + 核心句）。"""
        msg = gate(PURE_SYS_ADMIN, "dict_admin")
        assert msg is not None and msg.startswith("⛔")
        assert "授予/撤销管理角色仅词典管理员可执行" in msg

