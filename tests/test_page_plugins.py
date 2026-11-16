"""批次 62 页面与功能开关测试（用户需求「所有页面/页内功能在账号管理中心开关」）。

三层（对齐 test_fx54 的插件测试结构）：
  * 数据层：page_plugins/feature_plugins 表 CRUD／默认启用／底线页拒绝／
    未知键拒绝／fail-open（表缺 → 恒启用）；
  * 注册表：FEATURE_SPECS 声明完整性与 page 键归属；
  * 语义层：disabled_pages 批量集合与 is_feature_enabled 的降级口径。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.page_plugins import (  # noqa: E402
    FEATURE_SPECS,
    LOCKED_PAGES,
    disabled_pages,
    ensure_page_plugins_tables,
    is_feature_enabled,
    is_page_enabled,
    list_feature_settings,
    list_page_settings,
    set_feature_enabled,
    set_page_enabled,
)

TEST_DB = "web_word_pageplug_test"

ACTOR = {"id": 2, "username": "pageplug_dict", "role": "viewer",
         "roles": ["dict_admin"]}


@pytest.fixture()
def pageplug_env(monkeypatch):
    """沙箱库。MySQL 不可用 → skip。"""
    import pymysql as _pymysql

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
        cur.close()
        conn.close()
    except _pymysql.err.OperationalError as e:
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 page_plugins: {e}")
    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    snap_pool = dict(db._connection_pools)
    db._connection_pools.clear()
    ensure_page_plugins_tables()
    yield
    db.MYSQL_DATABASE = old_db
    db._connection_pools.clear()
    db._connection_pools.update(snap_pool)


class TestPageSwitches:
    def test_default_enabled(self, pageplug_env):
        """未登记页/刚建表：默认启用（升级零自伤）。"""
        assert is_page_enabled("graph") is True
        assert is_page_enabled("cluster") is True

    def test_set_roundtrip(self, pageplug_env):
        """停用→读 False→恢复→读 True（开关往返）。"""
        assert set_page_enabled("graph", False, ACTOR) is True
        assert is_page_enabled("graph") is False
        assert set_page_enabled("graph", True, ACTOR) is True
        assert is_page_enabled("graph") is True

    def test_disabled_pages_batch(self, pageplug_env):
        """停用集合批量读取（侧边栏过滤口径）：含停用页、不含恢复页。"""
        set_page_enabled("graph", False, ACTOR)
        set_page_enabled("corpus", False, ACTOR)
        disabled = disabled_pages()
        assert {"graph", "corpus"} <= disabled
        set_page_enabled("graph", True, ACTOR)
        assert "graph" not in disabled_pages()
        assert "corpus" in disabled_pages()

    def test_locked_pages_reject_and_always_enabled(self, pageplug_env):
        """底线三键：写路径拒绝＋读侧恒启用（直库写 0 也不拦导航）。"""
        for key in LOCKED_PAGES:
            assert set_page_enabled(key, False, ACTOR) is False
            assert is_page_enabled(key) is True

    def test_unknown_page_key_rejected(self, pageplug_env):
        """未知页键拒绝（开关面只对 PAGE_KEYS 开放——垃圾行不进表）。"""
        assert set_page_enabled("nope_page", False, ACTOR) is False

    def test_list_settings_reflects_state(self, pageplug_env):
        """管理界面清单反映写状态。"""
        set_page_enabled("graph", False, ACTOR)
        states = {str(r.get("page_key")): bool(r.get("enabled"))
                  for r in list_page_settings()}
        assert states.get("graph") is False


class TestFeatureSwitches:
    def test_default_enabled_all_specs(self, pageplug_env):
        """seed 后全部功能默认启用。"""
        for spec in FEATURE_SPECS:
            assert is_feature_enabled(spec["key"]) is True

    def test_set_roundtrip(self, pageplug_env):
        """功能停用→恢复往返。"""
        key = FEATURE_SPECS[0]["key"]
        assert set_feature_enabled(key, False, ACTOR) is True
        assert is_feature_enabled(key) is False
        assert set_feature_enabled(key, True, ACTOR) is True
        assert is_feature_enabled(key) is True

    def test_unknown_feature_key_rejected(self, pageplug_env):
        """未知功能键拒绝（开关面只对 FEATURE_SPECS 开放）。"""
        assert set_feature_enabled("nope.feature", False, ACTOR) is False

    def test_list_settings_covers_all_specs(self, pageplug_env):
        """管理清单覆盖全部 spec（未 seed 行也按默认启用列出）。"""
        feats = list_feature_settings()
        assert {f["key"] for f in feats} == {s["key"] for s in FEATURE_SPECS}
        assert all(bool(f.get("enabled")) for f in feats)


class TestFailOpen:
    def test_read_fail_open(self, monkeypatch):
        """读失败按启用降级（fail-open——开关故障不锁死功能）。"""
        import src.page_plugins as pp

        def boom(*a, **k):
            raise RuntimeError("probe down")

        monkeypatch.setattr(pp, "get_db_cursor", boom)
        assert pp.is_page_enabled("graph") is True
        assert pp.is_feature_enabled("search.examples") is True
        assert pp.disabled_pages() == set()
        assert pp.list_page_settings() == []
        # 功能清单以 FEATURE_SPECS 为骨架——读失败按默认启用列出（管理界面仍可用）
        feats = pp.list_feature_settings()
        assert {f["key"] for f in feats} == {s2["key"] for s2 in pp.FEATURE_SPECS}
        assert all(bool(f["enabled"]) for f in feats)


class TestRegistry:
    def test_spec_pages_valid(self):
        """FEATURE_SPECS 的 page 键都在 PAGE_KEYS（接线页合法）。"""
        from src.page_guides import PAGE_KEYS

        for spec in FEATURE_SPECS:
            assert spec["page"] in PAGE_KEYS, spec["key"]

    def test_locked_pages_in_page_keys(self):
        """底线三键是真实页面键（豁免口径防漂移）。"""
        from src.page_guides import PAGE_KEYS

        assert set(LOCKED_PAGES) <= set(PAGE_KEYS)

    def test_spec_bilingual_labels(self):
        """双语 label 齐备（管理界面直接渲染，不落 i18n 字典）。"""
        for spec in FEATURE_SPECS:
            assert spec.get("zh") and spec.get("en")
            assert spec["zh"] != spec["en"]
