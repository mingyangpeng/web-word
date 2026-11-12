"""批次 30 五构件插件化测试（用户需求「五个插件模式」）。

三层：
  * 数据层：module_plugins 表 CRUD/默认启用/锁定项拒绝/未知键放行；
  * 语义层：filter_pages_by_modules 过滤＋is_module_enabled fail-open；
  * UI 层：categories_tools_page 勾选段渲染＋侧边栏隐藏联动（AppTest）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.module_plugins import (  # noqa: E402
    MODULE_C, MODULE_P, MODULE_SPECS, MODULE_U, disabled_modules,
    ensure_module_plugins_table, filter_pages_by_modules, is_module_enabled,
    list_module_settings, set_module_enabled,
)
import src.app as app_module  # noqa: E402
import src.mysql_db as db  # noqa: E402
import pymysql  # noqa: E402

TEST_DB = "web_word_fx54_test"

DICT_ADMIN = {"id": 2, "username": "fx54_dict", "role": "viewer",
              "roles": ["dict_admin"]}
VIEWER = {"id": 3, "username": "fx54_view", "role": "viewer",
          "roles": ["viewer"]}


@pytest.fixture()
def fx54_env(monkeypatch):
    """沙箱库＋哨兵/缓存复位。MySQL 不可用 → skip。"""
    import pymysql as _pymysql

    conn = None
    try:
        conn = _pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=_pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True)
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci")
    except _pymysql.err.OperationalError as e:
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 FX-54: {e}")
    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    import src.module_plugins as mp

    mp._TABLES_ENSURED = False
    monkeypatch.setattr(mp, "_TABLES_ENSURED", False)
    snap_pool = dict(db._connection_pools)
    yield
    db.MYSQL_DATABASE = old_db
    db._connection_pools.clear()
    db._connection_pools.update(snap_pool)
    mp._TABLES_ENSURED = False
    if conn:
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()


class TestDataLayer:
    def test_default_all_enabled(self, fx54_env):
        """默认全启用（存量库/新键不自伤——升级不自伤纪律）。"""
        ensure_module_plugins_table()
        for key in MODULE_SPECS:
            assert is_module_enabled(key) is True, key

    def test_toggle_and_persist(self, fx54_env):
        """勾选停用→持久化→重读仍停用；重新勾选恢复。"""
        assert set_module_enabled(MODULE_P, False, DICT_ADMIN) is True
        assert is_module_enabled(MODULE_P) is False
        assert "p" in disabled_modules()
        assert set_module_enabled(MODULE_P, True, DICT_ADMIN) is True
        assert is_module_enabled(MODULE_P) is True
        assert "p" not in disabled_modules()

    def test_locked_modules_reject_disable(self, fx54_env):
        """锁定项（C/U）拒绝停用——平台底线。"""
        ensure_module_plugins_table()
        assert set_module_enabled(MODULE_C, False, DICT_ADMIN) is False
        assert set_module_enabled(MODULE_U, False, DICT_ADMIN) is False
        assert is_module_enabled(MODULE_C) is True
        assert is_module_enabled(MODULE_U) is True

    def test_unknown_key_passes(self, fx54_env):
        """未知模块键 → True（fail-open，未知不拦）。"""
        assert is_module_enabled("nonexistent") is True

    def test_list_settings_shape(self, fx54_env):
        ensure_module_plugins_table()
        rows = list_module_settings()
        assert len(rows) == 5
        locked = {r["module_key"] for r in rows if r["lock"]}
        assert locked == {"c", "u"}


class TestSemantic:
    def test_filter_pages(self, fx54_env):
        """filter_pages_by_modules：停用 P → 其页面全滤除。"""
        ensure_module_plugins_table()
        assert set_module_enabled(MODULE_P, False, DICT_ADMIN) is True
        out = filter_pages_by_modules(
            ["search", "cluster", "template", "annotate", "ai_hub"])
        assert "cluster" not in out and "template" not in out
        assert "search" in out and "annotate" in out and "ai_hub" in out
        assert set_module_enabled(MODULE_P, True, DICT_ADMIN) is True
        out2 = filter_pages_by_modules(["cluster", "search"])
        assert "cluster" in out2

    def test_is_module_enabled_fail_open_on_db_down(self, fx54_env, monkeypatch):
        """库断连 → fail-open 全启用（禁用是显式动作，基础设施抖动不拦导航）。"""
        import pymysql as _pymysql

        def _boom(*a, **k):
            raise _pymysql.err.OperationalError(2003, "db down")

        monkeypatch.setattr(
            "src.module_plugins.get_db_cursor",
            lambda autocommit=True: (_ for _ in ()).throw(_boom()))
        assert is_module_enabled(MODULE_P) is True


class TestPermission:
    def test_non_dict_admin_rejected(self, fx54_env):
        ensure_module_plugins_table()
        with pytest.raises(Exception):
            set_module_enabled(MODULE_P, False, VIEWER)
        with pytest.raises(Exception):
            set_module_enabled(MODULE_P, False, None)


class TestSidebarIntegration:
    def test_disabled_module_hidden_from_sidebar(self, fx54_env):
        """停用 P 构件 → 侧边栏编纂产出区入口隐藏（AppTest 真渲染）。"""
        from streamlit.testing.v1 import AppTest

        assert set_module_enabled(MODULE_P, False, DICT_ADMIN) is True
        at = AppTest.from_file(
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "src", "app.py"),
            default_timeout=180)
        at.session_state["user"] = DICT_ADMIN
        at.run()
        assert not at.exception, [str(e.value)[:80] for e in at.exception]
        from src.page_guides import page_label

        labels = [str(b.label) for b in at.sidebar.button]
        assert page_label("cluster") not in labels, (
            "停用 P 后编纂产出区导航应隐藏")
        assert page_label("search") in labels
        # 恢复
        assert set_module_enabled(MODULE_P, True, DICT_ADMIN) is True
