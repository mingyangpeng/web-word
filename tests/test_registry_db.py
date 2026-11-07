r"""资源登记数据层测试（src/registry_db.py，批次 11 AV2）。

两层结构，与 tests/test_media_db.py 既有约定一致：

  * 入参守卫（四项必填 / 超长 / 非法 id）在应用层先拒、不碰数据库 ——
    本地与 CI 全跑；
  * 数据层 CRUD（ensure_resource_registry_tables / register_resource /
    list_resources / get_resource）依赖真实 MySQL —— 连不上或账号无建库
    权限就 skip（类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_registry_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，
跑完 DROP。库名按模块预授权（scripts/grant_local_mysql.sql 模式：三 host
`web\_word\_registry\_test` 转义授权；无该库名授权的环境自动 skip）。

覆盖面（批次 11 契约）：CRUD 往返 / UNIQUE(name, version) 去重 /
license 必填（应用层先拒）/ registered_by 留痕 / list 降级。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.registry_db import (  # noqa: E402
    MAX_COVERAGE_LEN,
    MAX_LICENSE_LEN,
    MAX_NAME_LEN,
    MAX_REGISTERED_BY_LEN,
    MAX_VERSION_LEN,
    ensure_resource_registry_tables,
    get_resource,
    list_resources,
    register_resource,
)

TEST_DB = "web_word_registry_test"


# ============================================
# 入参守卫（应用层先拒，不碰数据库 —— CI 必跑）
# ============================================

class TestGuards:
    """register_resource / get_resource / list_resources 的应用层守卫。"""

    def test_license_required_rejected(self):
        """许可必填（D⑥ 许可纪律）：空/纯空白 license 拒绝（不碰库，返回 0）。"""
        assert register_resource("enTenTen21", "2021", "搭配", "") == 0
        assert register_resource("enTenTen21", "2021", "搭配", "  \n\t ") == 0
        assert register_resource("enTenTen21", "2021", "搭配", None) == 0

    def test_all_fields_required_rejected(self):
        """name/version/coverage 三项同样必填（空/纯空白/None 拒绝）。"""
        assert register_resource("", "2021", "搭配", "CC BY 4.0") == 0
        assert register_resource("  ", "2021", "搭配", "CC BY 4.0") == 0
        assert register_resource(None, "2021", "搭配", "CC BY 4.0") == 0
        assert register_resource("enTenTen21", "", "搭配", "CC BY 4.0") == 0
        assert register_resource("enTenTen21", "2021", "", "CC BY 4.0") == 0

    def test_non_string_rejected(self):
        """非 str 入参拒绝（int/dict 等，不依赖 DDL 报错）。"""
        assert register_resource(123, "2021", "c", "l") == 0
        assert register_resource("n", ["2021"], "c", "l") == 0
        assert register_resource("n", "2021", {"k": 1}, "l") == 0
        assert register_resource("n", "2021", "c", 4.0) == 0

    def test_overlong_rejected(self):
        """超长拒绝（列宽一致：120/64/255/120/64，应用层先拒）。"""
        assert register_resource("n" * 121, "v", "c", "l") == 0
        assert register_resource("n", "v" * 65, "c", "l") == 0
        assert register_resource("n", "v", "c" * 256, "l") == 0
        assert register_resource("n", "v", "c", "l" * 121) == 0
        assert register_resource(
            "n", "v", "c", "l", registered_by="u" * 65) == 0

    def test_limits_constants_match_ddl(self):
        """长度常量与 DDL 列宽一致（应用层守卫与存储层同口径）。"""
        assert MAX_NAME_LEN == 120
        assert MAX_VERSION_LEN == 64
        assert MAX_COVERAGE_LEN == 255
        assert MAX_LICENSE_LEN == 120
        assert MAX_REGISTERED_BY_LEN == 64

    def test_registered_by_blank_allowed(self):
        """registered_by 空串允许（数据层不强加角色判定；默认 ''）。"""
        # 不碰库的断言只有守卫路径可测：空白 → strip 后空串允许入库方向，
        # 但无库时 register 返回 0（DB 失败同样返回 0）——这里只验证
        # registered_by=None 这种**类型**错误在应用层被拒。
        assert register_resource("n", "v", "c", "l", registered_by=None) == 0
        assert register_resource("n", "v", "c", "l", registered_by=42) == 0

    def test_get_resource_invalid_ids(self):
        """get_resource 非法 id（0/负数/非整数/bool）返回 None，不碰库。"""
        assert get_resource(0) is None
        assert get_resource(-1) is None
        assert get_resource("abc") is None
        assert get_resource(None) is None
        assert get_resource(True) is None  # bool 显式拒绝

    def test_list_resources_invalid_limit(self):
        """list_resources 非法 limit → []（守卫路径）。"""
        assert list_resources("abc") == []
        assert list_resources(None) == []


# ============================================
# 集成测试：真实 MySQL（无环境则整类 skip）
# ============================================

def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不建库）。"""
    try:
        import pymysql
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


@pytest.fixture
def registry_env(monkeypatch):
    """建空测试库并让 registry 模块指向它，测试结束 DROP。

    与 test_media_db.py 同一手法：get_db_cursor 在调用时读 mysql_db
    模块全局，monkeypatch MYSQL_DATABASE 即可；账号无该库名授权则 skip。
    """
    import pymysql

    conn = pymysql.connect(
        host=db.MYSQL_HOST,
        port=db.MYSQL_PORT,
        user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD,
        charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
    )
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
            f"COLLATE utf8mb4_unicode_ci"
        )
    except pymysql.err.OperationalError as e:
        conn.close()
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过 registry 集成测试: {e}")
    conn.close()

    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
    yield
    conn = pymysql.connect(
        host=db.MYSQL_HOST,
        port=db.MYSQL_PORT,
        user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD,
        charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
        autocommit=True,
    )
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.close()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 registry 数据层集成测试")
class TestRegistryIntegration:
    """resource_registry CRUD（跑在独立测试库 web_word_registry_test）。"""

    # --- 建表 ---

    def test_ensure_idempotent(self, registry_env):
        """ensure 重复调用幂等（CREATE TABLE IF NOT EXISTS）。"""
        ensure_resource_registry_tables()
        ensure_resource_registry_tables()
        ensure_resource_registry_tables()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'resource_registry'"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 1

    # --- register_resource ---

    def test_register_returns_id_and_fields(self, registry_env):
        """登记返回 id；四必填 + registered_by + created_at 入库正确。"""
        ensure_resource_registry_tables()
        rid = register_resource(
            "enTenTen21", "2021", "69,943 搭配", "CC BY 4.0",
            registered_by="chief",
        )
        assert isinstance(rid, int) and rid > 0
        row = get_resource(rid)
        assert row is not None
        assert row["name"] == "enTenTen21"
        assert row["version"] == "2021"
        assert row["coverage"] == "69,943 搭配"
        assert row["license"] == "CC BY 4.0"
        assert row["registered_by"] == "chief"
        assert row["created_at"] is not None

    def test_register_strips_whitespace(self, registry_env):
        """四必填去首尾空白后入库（' OALD ' → 'OALD'）。"""
        ensure_resource_registry_tables()
        rid = register_resource(
            "  OALD  ", "\t第7版\n", " 996 全义项 ", " 授权协议 ")
        row = get_resource(rid)
        assert row["name"] == "OALD"
        assert row["version"] == "第7版"
        assert row["coverage"] == "996 全义项"
        assert row["license"] == "授权协议"

    def test_unique_name_version_dedup(self, registry_env):
        """UNIQUE(name, version)：同 (名称, 版本) 重复登记返回已有 id，不新插行。"""
        ensure_resource_registry_tables()
        first = register_resource("现汉7", "v1", "三表", "授权")
        second = register_resource("现汉7", "v1", "三表（重复登记）", "授权")
        assert second == first
        # 不同版本各自一行（版本演进如实分立）
        third = register_resource("现汉7", "v2", "三表", "授权")
        assert third != first

    def test_license_not_null_at_ddl_level(self, registry_env):
        """DDL 硬约束兜底：license NOT NULL（应用层守卫被绕过时 DB 仍拒）。"""
        ensure_resource_registry_tables()
        import pymysql
        from src.mysql_db import get_db_cursor

        with pytest.raises(pymysql.err.IntegrityError):
            with get_db_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO resource_registry "
                    "(name, version, coverage, license) "
                    "VALUES ('x', 'v', 'c', NULL)"
                )

    # --- list_resources ---

    def test_list_resources_newest_first_and_limit(self, registry_env):
        """清单 id 倒序（最新在前）；limit 截断生效。"""
        ensure_resource_registry_tables()
        for i in range(3):
            register_resource(f"res{i}", "v1", "c", "l")
        rows = list_resources()
        assert [r["name"] for r in rows] == ["res2", "res1", "res0"]
        assert set(rows[0]) == {
            "id", "name", "version", "coverage", "license",
            "registered_by", "created_at",
        }
        assert [r["name"] for r in list_resources(limit=2)] == ["res2", "res1"]
        # limit 越界取边界（0 → 1，超大 → 上限内）
        assert len(list_resources(limit=0)) == 1

    def test_list_resources_empty(self, registry_env):
        """空表 → []（0 行如实，G6 许可终检「空过」的取数口径）。"""
        ensure_resource_registry_tables()
        assert list_resources() == []

    # --- get_resource ---

    def test_get_resource_missing(self, registry_env):
        """不存在的 id → None（如实，不抛）。"""
        ensure_resource_registry_tables()
        register_resource("OALD", "v1", "c", "l")
        assert get_resource(999) is None
