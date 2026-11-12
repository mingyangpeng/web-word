"""FX-56 修复回归（RV23-2/3 + RV25-3/4/5/7/8 审出问题收口）。

覆盖面（与 src 修复一一对应）：
  * RV23-P2  _PAGE_TO_MODULE 补 model_settings→A + 双源一致性哨兵
             （app 手抄投影 vs module_plugins 派生映射逐键相等）+
             「PAGE_KEYS − 映射 == {users_admin, help}」豁免哨兵；
  * RV23-P3  users_admin 入口补 dict_admin（与页面体闸同口径，恢复闭环）
             ＋ module_plugins 闸收口（require_role 死导入删除、薄封装
             require_role_interactive）＋ enabled_by as_int 清洗；
  * RV25-3   categories_tools_page 三段勾选（available/enabled/功能模块）
             写回改 on_change 回调形态——真用户动作才写库，陈旧驻留会话
             divergence 不代写（dict_admin 与 sys_admin 变体都钉死）；
  * RV25-4   gate 返回按钮 on_click 回调形态（点击即生效）；
  * RV25-5   落地分支 2 续接点接模块过滤（命中停用页顺延分支 3）；
  * RV25-7   lock 模块（C/U）读侧防线——直库写 enabled=0 也不拦死导航；
  * RV25-8   侧边栏 disabled_modules() 一次取全（不再逐键点查）。
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql  # noqa: E402
import src.app as app_module  # noqa: E402
import src.mysql_db as db  # noqa: E402
import src.module_plugins as mp  # noqa: E402
from src.categories_tools_page import (  # noqa: E402
    _available_toggle_callback,
    _enabled_toggle_callback,
    _module_toggle_callback,
)
from src.module_plugins import (  # noqa: E402
    MODULE_A, MODULE_P, MODULE_SPECS, disabled_modules, is_module_enabled,
    set_module_enabled,
)
from src.page_guides import PAGE_KEYS  # noqa: E402

# 沙箱库名：本环境 MySQL 账号按库逐名授权（scripts/grant_local_mysql.sql），
# 新库名无法 CREATE——复用已授权且现无任何测试消费的历史探针库名
# web_word_r1_probe（r1_probe 已改名 fx27_test，该授权位空置）。
TEST_DB = "web_word_r1_probe"

DICT_ADMIN = {"id": 21, "username": "fx56_dict", "role": "viewer",
              "roles": ["dict_admin"]}
SYS_ADMIN = {"id": 22, "username": "fx56_sys", "role": "viewer",
             "roles": ["sys_admin"]}
VIEWER = {"id": 23, "username": "fx56_view", "role": "viewer",
          "roles": ["viewer"]}
ADMIN_SESSION = {"id": 24, "username": "fx56_admin", "display_name": "管理员",
                 "role": "admin", "roles": ["dict_admin", "sys_admin"]}

try:
    _conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        connect_timeout=3)
    _conn.close()
    HAS_MYSQL = True
except Exception:  # noqa: BLE001
    HAS_MYSQL = False


@pytest.fixture(autouse=True)
def _reset_module_seams():
    """loader 缝/落地旗标/flash 队列复位（不跨用例泄漏）。"""
    yield
    app_module.set_resume_page_loader(None)
    for key in (app_module._RESUME_HINT_KEY,):
        app_module.st.session_state.pop(key, None)
    from src import ui_kit

    ui_kit.st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


@pytest.fixture()
def fx56_env(monkeypatch):
    """沙箱库＋模块表哨兵复位。MySQL 不可用 → skip（照 fx54 先例）。"""
    conn = None
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True)
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci")
    except pymysql.err.OperationalError as e:
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 FX-56 沙箱用例: {e}")
    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    mp._TABLES_ENSURED = False
    snap_pool = dict(db._connection_pools)
    yield
    db.MYSQL_DATABASE = old_db
    db._connection_pools.clear()
    db._connection_pools.update(snap_pool)
    mp._TABLES_ENSURED = False
    if conn:
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "src", "app.py"),
        default_timeout=180,
    )


_PAGE_SCRIPT = (
    "import sys\n"
    f"sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r})\n"
    "from src.categories_tools_page import render_categories_tools_page\n"
    "render_categories_tools_page()\n"
)


def _run_ct_page(user: dict):
    """范畴与工具页无头渲染（fx18 同款 PAGE_SCRIPT 形态）。"""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(_PAGE_SCRIPT, default_timeout=120)
    if user is not None:
        at.session_state["user"] = user
    at.run()
    return at


# ============================================
# 1. RV23-P2：五构件映射哨兵（纯数据层，不触库）
# ============================================

class TestMappingSentinels:
    def test_dual_source_page_to_module_identical(self):
        """双源一致性哨兵（RV25-8）：app 手抄投影与 module_plugins 派生映射
        逐键相等——改任一侧（MODULE_SPECS/手抄表）忘了同步即红。"""
        assert app_module._PAGE_TO_MODULE == mp._PAGE_TO_MODULE, (
            "app._PAGE_TO_MODULE 与 module_plugins._PAGE_TO_MODULE 漂移："
            "两源必须逐键相等（改 MODULE_SPECS 后同步 app 手抄投影）")

    def test_unmapped_pages_exactly_users_admin_and_help(self):
        """RV23-P2 哨兵：PAGE_KEYS − 映射 == {"users_admin", "help"}。

        豁免理由（app.py 注释与 module_plugins docstring 同口径）：
          * users_admin —— 插件管理段宿主页：停用模块后的唯一恢复入口，
            映射进任何模块都会被自己锁死；
          * help —— 兜底路由页：全员可达的兜底出口，不随模块停用。
        """
        unmapped = set(PAGE_KEYS) - set(app_module._PAGE_TO_MODULE)
        assert unmapped == {"users_admin", "help"}, (
            f"映射覆盖缺口漂移: {sorted(unmapped)}（新页要么归模块、要么"
            "在 app.py 注释与本测试补豁免理由）")

    def test_model_settings_mapped_to_module_a(self):
        """RV23-P2：model_settings（🤖 模型供应商）归 A 构件——停用 A 后
        不再直访可达（AI 设置属协作智能层语义自洽）。"""
        assert app_module._PAGE_TO_MODULE.get("model_settings") == MODULE_A
        assert mp._PAGE_TO_MODULE.get("model_settings") == MODULE_A
        assert "model_settings" in MODULE_SPECS[MODULE_A]["pages"]
        assert MODULE_SPECS[MODULE_A]["lock"] is False  # A 可停用（非锁定项）

    def test_users_admin_exemption_is_plugin_host_page(self):
        """豁免语义哨兵：users_admin 宿主页确承载「📦 功能模块」段
        （render_users_admin_entry 调 render_categories_tools_page）。"""
        src = inspect.getsource(app_module.render_users_admin_entry)
        assert "render_categories_tools_page" in src

    def test_users_admin_access_matches_page_body_gate(self):
        """RV23-P3：users_admin 入口允许集与页面体闸同口径
        （sys_admin 或 dict_admin）；legacy 投影不变（admin 域）。"""
        assert app_module._PAGE_ACCESS_SIX["users_admin"] == \
            ("sys_admin", "dict_admin")
        assert app_module._PAGE_ACCESS["users_admin"] == ("admin",)

    def test_pure_dict_admin_sees_users_admin_entry(self):
        """纯 dict_admin 会话可见账号管理宿主入口（恢复路径闭环）。"""
        pure_dict = {"id": 25, "username": "pd", "role": "viewer",
                     "roles": ["dict_admin"]}
        keys = app_module._visible_page_keys(pure_dict)
        assert "users_admin" in keys
        pure_sys = {"id": 26, "username": "ps", "role": "viewer",
                    "roles": ["sys_admin"]}
        assert "users_admin" in app_module._visible_page_keys(pure_sys)
        assert "users_admin" not in app_module._visible_page_keys(VIEWER)


# ============================================
# 2. RV25-7：lock 模块读侧防线（打桩，不触库）
# ============================================

class _FakeCursor:
    """最小 DictCursor 打桩：fetchone/fetchall 回放预置行。"""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeCtx:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return _FakeCursor(self._rows)

    def __exit__(self, *a):
        return False


class TestLockReadSideDefense:
    """RV25-7：C/U（lock=True）读侧恒启用——直库写 enabled=0 的不可达态
    也不会拦死导航（gate 永不锁死平台底线；写侧已拒，读侧兜同一底线）。"""

    def _with_rows(self, monkeypatch, rows):
        monkeypatch.setattr(mp, "_TABLES_ENSURED", True)
        monkeypatch.setattr(mp, "get_db_cursor", lambda autocommit=True: _FakeCtx(rows))

    def test_locked_module_enabled_zero_row_still_enabled(self, monkeypatch):
        # 直库写不可达态：c/u 两行 enabled=0
        self._with_rows(monkeypatch, [{"module_key": "c", "enabled": 0},
                                      {"module_key": "u", "enabled": 0}])
        assert is_module_enabled("c") is True
        assert is_module_enabled("u") is True

    def test_disabled_modules_excludes_locked(self, monkeypatch):
        # 侧边栏/落地共用的停用集合同样不收锁定键（u 恒可用）
        self._with_rows(monkeypatch, [{"module_key": "u", "enabled": 0},
                                      {"module_key": "p", "enabled": 0}])
        assert disabled_modules() == {MODULE_P}

    def test_non_locked_respects_enabled_zero_row(self, monkeypatch):
        # 非 lock 模块读侧照常尊重 enabled=0 行（防线只对锁定项）
        self._with_rows(monkeypatch, [{"module_key": "p", "enabled": 0}])
        assert is_module_enabled(MODULE_P) is False

    def test_locked_disable_rejected_at_write_side(self):
        # 写侧闸不变：锁定项停用仍拒绝（且不触库——不建表即可判）
        assert set_module_enabled("c", False, DICT_ADMIN) is False
        assert set_module_enabled("u", False, DICT_ADMIN) is False


# ============================================
# 3. RV25-5：落地分支 2 续接点接模块过滤（打桩，不触库）
# ============================================

class TestLandingModuleFilter:
    def test_resume_on_disabled_module_falls_to_branch3(self, monkeypatch):
        """续接点命中停用模块页 → 视同未命中，顺延分支 3（搜索释义），
        不写续接灰注旗标——登录不再闪现模块 gate 拦截页。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        # 模拟 P 停用：filter 对 cluster 返回空（命中停用页被滤除）
        monkeypatch.setattr(
            app_module, "filter_pages_by_modules",
            lambda pages: [] if list(pages) == ["cluster"] else list(pages))
        app_module.set_resume_page_loader(lambda uid: "cluster")
        assert app_module._landing_page_for(ADMIN_SESSION) == "search"
        assert app_module.st.session_state.get(
            app_module._RESUME_HINT_KEY) is None

    def test_resume_on_enabled_module_still_lands(self, monkeypatch):
        """模块启用（或读侧 fail-open）时续接点照常落地 + 旗标在写。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        monkeypatch.setattr(app_module, "filter_pages_by_modules",
                            lambda pages: list(pages))
        app_module.set_resume_page_loader(lambda uid: "cluster")
        assert app_module._landing_page_for(ADMIN_SESSION) == "cluster"
        assert app_module.st.session_state.get(
            app_module._RESUME_HINT_KEY) == "cluster"

    def test_resume_exempt_pages_not_filtered_mp(self, monkeypatch):
        """豁免键（users_admin）不映射模块——续接点落宿主页不被模块过滤
        拦截（真函数直跑：库不可用→fail-open；可用且默认全启用→同样放行）。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        app_module.set_resume_page_loader(lambda uid: "users_admin")
        assert app_module._landing_page_for(ADMIN_SESSION) == "users_admin"

    def test_filter_pages_by_modules_keeps_unmapped_keys(self, monkeypatch):
        """豁免键不经映射 → 任何停用集合下都放行（宿主页/兜底页恒可达）。"""
        monkeypatch.setattr(mp, "_TABLES_ENSURED", True)
        monkeypatch.setattr(mp, "get_db_cursor", lambda autocommit=True: _FakeCtx(
            [{"module_key": "p", "enabled": 0}]))
        out = mp.filter_pages_by_modules(["users_admin", "help", "cluster"])
        assert out == ["users_admin", "help"]


# ============================================
# 4. RV23-P3：module_plugins 闸收口（薄封装 require_role_interactive）
# ============================================

class TestModuleActorGate:
    def test_none_actor_rejected(self):
        """交互面语义：actor=None 直接拒绝（不读会话兜底）。"""
        with pytest.raises(PermissionError):
            mp._require_module_actor(None, "功能模块勾选")

    def test_junk_type_actor_rejected(self):
        """杂类型（str/int/list）拒绝——不 isinstance dict 一律拒。"""
        for junk in ("admin", 1, ["dict_admin"], {"dict_admin"}):
            with pytest.raises(PermissionError):
                mp._require_module_actor(junk, "功能模块勾选")

    def test_dict_admin_and_sys_admin_pass(self):
        """dict_admin/sys_admin（含 legacy admin 两位一体）放行且返回原 actor。"""
        assert mp._require_module_actor(DICT_ADMIN, "功能模块勾选") is DICT_ADMIN
        assert mp._require_module_actor(SYS_ADMIN, "功能模块勾选") is SYS_ADMIN

    def test_viewer_rejected(self):
        with pytest.raises(PermissionError):
            mp._require_module_actor(VIEWER, "功能模块勾选")

    def test_require_role_dead_import_removed(self):
        """RV23-P3 哨兵：require_role 死导入删除，判定改薄封装
        require_role_interactive（单一实现复用 guards）。"""
        src = inspect.getsource(mp)
        assert "from src.guards import require_role\n" not in src
        assert "require_role_interactive" in src
        assert not hasattr(mp, "require_role")


# ============================================
# 5. RV23-P3：enabled_by 清洗（db_utils.as_int 单一口径；沙箱库）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 enabled_by 清洗用例")
class TestEnabledByCleaning:
    def _read_enabled_by(self, module_key):
        mp.ensure_module_plugins_table()
        with mp.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT enabled_by FROM module_plugins WHERE module_key = %s",
                (module_key,))
            row = cursor.fetchone()
        return (row or {}).get("enabled_by")

    def test_bool_id_lands_null(self, fx56_env):
        """bool 是 int 子类：True 不再放行成 1（RV3-5 口径）→ enabled_by NULL。"""
        assert set_module_enabled(MODULE_P, False, {"id": True, "roles": ["dict_admin"]}) is True
        assert self._read_enabled_by(MODULE_P) is None

    def test_string_int_id_accepted(self, fx56_env):
        """整数值串宽松可转（与全仓 id 类入参清洗一致）。"""
        assert set_module_enabled(MODULE_P, True, {"id": "7", "roles": ["dict_admin"]}) is True
        assert self._read_enabled_by(MODULE_P) == 7

    def test_non_positive_id_lands_null(self, fx56_env):
        """0/负数不是合法 users.id → NULL（旧口径 0→None 保持，负值收紧）。"""
        assert set_module_enabled(MODULE_P, False, {"id": 0, "roles": ["dict_admin"]}) is True
        assert self._read_enabled_by(MODULE_P) is None
        assert set_module_enabled(MODULE_P, True, {"id": -3, "roles": ["dict_admin"]}) is True
        assert self._read_enabled_by(MODULE_P) is None

    def test_normal_id_recorded(self, fx56_env):
        assert set_module_enabled(MODULE_P, False, DICT_ADMIN) is True
        assert self._read_enabled_by(MODULE_P) == 21


# ============================================
# 6. RV25-3：勾选段 on_change 写形态（行为 + 源形态哨兵；沙箱库）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过勾选形态用例")
class TestToggleOnChangeBehavior:
    def test_user_module_toggle_persists(self, fx56_env):
        """真用户动作（on_change 回调触发）→ 写库生效。"""
        at = _run_ct_page(DICT_ADMIN)
        assert not at.exception, [str(e.value) for e in at.exception]
        target = next(c for c in at.checkbox if c.key == "module_toggle_p")
        assert target.value is True
        target.uncheck().run()
        assert not at.exception, [str(e.value) for e in at.exception]
        assert is_module_enabled(MODULE_P) is False

    def test_stale_session_no_op_write_dict_admin(self, fx56_env):
        """RV25-3 核心回归：陈旧驻留会话（UI 残值≠库值）复渲染**不代写**。

        场景还原：会话驻留期间他人把库改停（set_module_enabled 直写模拟），
        本会话无操作 rerun——旧值差写回形态会把 divergence 当「用户勾选」
        自动翻转模块启停；on_change 形态下无用户动作即无写。
        """
        set_module_enabled(MODULE_P, True, DICT_ADMIN)   # 库：启用
        at = _run_ct_page(DICT_ADMIN)
        assert not at.exception
        set_module_enabled(MODULE_P, False, DICT_ADMIN)  # 他人改停（库：停用）
        at.run()                                          # 驻留会话无操作复渲染
        assert not at.exception
        assert is_module_enabled(MODULE_P) is False, (
            "陈旧驻留会话复渲染不得自动翻转模块启停（RV25-3）")

    def test_stale_session_no_op_write_sys_admin_variant(self, fx56_env):
        """sys_admin 变体：勾选框 disabled（非词典管理员）＋陈旧残值，
        复渲染同样不代写（旧值差形态对 disabled 框照样写）。"""
        set_module_enabled(MODULE_P, True, DICT_ADMIN)
        at = _run_ct_page(SYS_ADMIN)
        assert not at.exception
        set_module_enabled(MODULE_P, False, DICT_ADMIN)  # 他人改停
        at.run()                                          # 无操作复渲染
        assert not at.exception
        assert is_module_enabled(MODULE_P) is False

    def test_no_value_diff_writeback_pattern_in_source(self):
        """源形态哨兵：值差写回模式已不存在，三段勾选统一 on_change 接线。"""
        import src.categories_tools_page as ctp

        src = inspect.getsource(ctp)
        assert "!= enabled:" not in src
        assert "!= avail:" not in src
        assert "!= enab:" not in src
        assert "on_change=_module_toggle_callback" in src
        assert "on_change=_available_toggle_callback" in src
        assert "on_change=_enabled_toggle_callback" in src
        # 回调工厂在场（符号级接线，防裸 lambda 漂移）
        assert callable(_module_toggle_callback)
        assert callable(_available_toggle_callback)
        assert callable(_enabled_toggle_callback)

    def test_tool_available_toggle_via_callback(self, fx56_env):
        """FX-18 工具勾选同型修复：available 开勾 → on_change 回调写库。"""
        from src.tool_settings_db import ensure_tool_settings_tables, list_audit, list_settings

        ensure_tool_settings_tables()
        at = _run_ct_page(SYS_ADMIN)
        assert not at.exception, [str(e.value) for e in at.exception]
        from src.tools import registry as tool_registry

        first_tool_id = sorted(t.id for t in tool_registry.list_tools())[0]
        target = next(c for c in at.checkbox
                      if c.label == "available" and not c.value)
        target.check().run()   # on_change 回调写库（RV25-3 形态）
        assert not at.exception
        rows = list_settings()
        assert len(rows) == 1 and rows[0]["tool_id"] == first_tool_id
        assert rows[0]["available"] == 1 and rows[0]["enabled"] == 0
        assert any(r["action"] == "available_set"
                   and r["actor_username"] == "fx56_sys" for r in list_audit())

    def test_tool_stale_session_no_op(self, fx56_env):
        """工具勾选陈旧残值同样不代写（available 位）：会话驻留期间他人置位，
        驻留会话无操作 rerun 不得自动撤回。"""
        from src.tool_settings_db import (
            available_set, ensure_tool_settings_tables, list_settings)

        ensure_tool_settings_tables()
        from src.tools import registry as tool_registry

        first_tool_id = sorted(t.id for t in tool_registry.list_tools())[0]
        at = _run_ct_page(SYS_ADMIN)
        assert not at.exception
        assert list_settings() == []
        category = at.selectbox[0].value   # 本会话选中范畴（勾选键同源）
        # 他人置位（库：available=1）→ 驻留会话无操作复渲染
        available_set(category, first_tool_id, actor=SYS_ADMIN, available=True)
        at.run()
        assert not at.exception
        rows = list_settings()
        assert len(rows) == 1 and rows[0]["available"] == 1, (
            "陈旧驻留会话复渲染不得自动翻转 available 位（RV25-3）")


# ============================================
# 7. RV25-4：gate 返回按钮 on_click 形态（AppTest）
# ============================================

class TestGateBackButton:
    def test_back_button_click_returns_to_search(self, fx56_env):
        """停用 P 后直访其页面 → 拦截提示＋返回按钮；点击返回按钮 →
        落搜索释义、拦截提示消失（AppTest 全链路；AppTest.from_file 每次
        run 重执行脚本、不吃本进程 monkeypatch，故走真沙箱库停用态——
        同 fx54 TestSidebarIntegration 先例）。"""
        set_module_enabled(MODULE_P, False, DICT_ADMIN)   # 沙箱库真停用
        at = _new_at()
        at.session_state["user"] = ADMIN_SESSION
        at.session_state["page"] = "template"
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        assert any("已被词典管理员停用" in str(w.value) for w in at.warning), (
            "停用模块页直访应出拦截提示")
        back = [b for b in at.button if b.key == "module_gate_back"]
        assert back, "gate 返回按钮未渲染"
        back[0].click()
        at.run()
        assert not at.exception
        assert at.session_state["page"] == "search", (
            "点击返回按钮应即切搜索释义（RV25-4 on_click 形态）")
        assert not any("已被词典管理员停用" in str(w.value)
                       for w in at.warning)

    def test_gate_button_source_is_on_click_form(self):
        """源形态哨兵：返回按钮走 on_click 回调，正文期值差形态已移除。"""
        src = inspect.getsource(app_module.render_module_gate)
        assert "on_click" in src
        assert 'if st.button("← 返回搜索释义"' not in src

    def test_sidebar_filter_is_one_shot_disabled_modules(self):
        """RV25-8 源形态哨兵：侧边栏改 disabled_modules() 一次取全，
        逐键 is_module_enabled 点查已移除。"""
        src = inspect.getsource(app_module.render_sidebar)
        assert "disabled_modules()" in src
        assert "is_module_enabled(" not in src


# ============================================
# 8. RV25-5 生产接线哨兵：_landing_page_for 走 filter_pages_by_modules
# ============================================

class TestLandingWiring:
    def test_landing_uses_shared_filter(self):
        """落地分支 2 接 filter_pages_by_modules（module_plugins docstring
        「侧边栏/落地共用」兑现的生产接线哨兵）。"""
        src = inspect.getsource(app_module._landing_page_for)
        assert "filter_pages_by_modules" in src
