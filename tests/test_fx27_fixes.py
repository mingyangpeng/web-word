"""FX27 批次修复测试：规范②组「usage_logs.user_id」（查询日志归因）。

对应修复（FX-27，台账「规范×实现对账」②组；规范《平台架构设计规范.md》
附录 A ⑥「usage_logs(＋user_id 可空)」与「存量表变更」同口径）：

  * DDL —— usage_logs 补 user_id INT NULL（ALTER-only 幂等迁移：
    _column_exists 探测缺列才加，照 annotation_flow.
    _migrate_assignments_round_columns 先例；CREATE TABLE 文本保持原样，
    列属文件头部「ALTER-only 列清单」口径）。NULL 口径遵循 RV2-3
    「留痕列 NULL 口径」第 1 类：user_id = users.id（软引用无 FK），
    NULL = 未登录访客/系统作业，不用 0 冒充；
  * 写路径 —— log_usage 增可选关键字 user_id（默认 None：既有调用零破坏，
    未登录保持旧 INSERT 形态、列值即 NULL）；app._record_query 登录态取
    current_user()["id"]（as_int 清洗）随查询写入；
  * 读面 —— get_stats / get_hot_verbs 聚合口径不变（user_id 不参与聚合，
    仅归因留痕）。规范无「我的查询历史」类功能承诺，不发明读面。

外部依赖隔离：
  * 假游标用例不连库：monkeypatch mysql_db.get_db_cursor，按 SQL 子串
    分派 information_schema 探测行（test_fx20 同款手法；注意 db.
    _column_exists 探测参数是 (MYSQL_DATABASE, table, column) 三元）；
  * 真库用例（TestFx27RealDb）复用已授权测试库机制：web_word_user 无
    CREATE DATABASE 全局权限，只有点名授权的沙箱库 —— 取**现无任何测试
    引用**的 web_word_fx27_test（grep 全 tests/ 零引用，FX-27 专用，不与
    其他套件/并行批次冲突），MySQL 不可用/无沙箱权限整类 skip。
"""

import inspect
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.app as app_module  # noqa: E402  （模块级导入执行 init_database，仓库既有测试口径）
import src.mysql_db as db  # noqa: E402
from src.mysql_db import (  # noqa: E402
    USAGE_LOGS_USER_ID_COLUMN,
    _migrate_usage_logs_user_id,
)

# 已授权沙箱库（web_word_user 对其有 ALL PRIVILEGES；现无任何测试引用）
TEST_DB = "web_word_fx27_test"


# ============================================
# 假游标基建（不连库：按 SQL 子串分派）
# ============================================
class _Ctx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class FakeFx27Cursor:
    """按 SQL 子串分派的假游标（test_fx20.FakeFx20Cursor 变体）。

    select_routes: [(子串, 行列表或 callable(sql, params)->行)] —— SELECT 种子；
    error_on: 命中子串的 execute 直接抛 pymysql 异常（迁移缺列降级用）；
    都未命中时结果空（默认写成功路径）。
    """

    def __init__(self):
        self.executed = []
        self.select_routes = []
        self.error_on = ()

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        for substring in self.error_on:
            if substring in sql:
                raise pymysql.err.OperationalError(substring)
        for substring, rows in self.select_routes:
            if substring in sql:
                self._result = rows(sql, params) if callable(rows) else list(rows)
                return
        self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _patch(monkeypatch, existing_columns=()):
    """db.get_db_cursor → 假游标；information_schema 探测按 existing_columns
    （(table, column) 集合）供行 —— 迁移幂等测试用。注意 db._column_exists
    传 (MYSQL_DATABASE, table, column) 三元参数（与 annotation_flow 的
    db_utils.column_exists 二元不同），解包按位取后两元。"""
    cursor = FakeFx27Cursor()
    existing = set(existing_columns)

    def _probe(sql, params):
        _, table, column = params
        return [{"n": 1 if (table, column) in existing else 0}]

    cursor.select_routes.append(("information_schema.COLUMNS", _probe))
    monkeypatch.setattr(db, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


def _patch_plain(monkeypatch):
    """同 _patch，但不带 information_schema 路由（非迁移用例）。"""
    cursor = FakeFx27Cursor()
    monkeypatch.setattr(db, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


# ============================================
# 1) ALTER-only 幂等迁移（假游标）
# ============================================
class TestMigrateUsageLogsUserId:
    def test_column_pair_shape(self):
        column, sql = USAGE_LOGS_USER_ID_COLUMN
        assert column == "user_id"
        assert sql.startswith("ALTER TABLE usage_logs ADD COLUMN")
        assert "INT NULL" in sql
        # RV2-3 第 1 类口径：可空、不用 0/默认值冒充「未登录」
        assert "NOT NULL" not in sql
        assert "DEFAULT 0" not in sql

    def test_column_only_via_alter_not_in_create_table(self):
        """user_id 不得混进 usage_logs 的 CREATE TABLE 文本 —— 列必须只走
        ALTER-only 迁移（「ALTER-only 列清单」口径的结构守卫）。"""
        create_sqls = [s for s in db.CREATE_TABLES_SQL
                       if "CREATE TABLE IF NOT EXISTS usage_logs" in s]
        assert len(create_sqls) == 1
        assert "user_id" not in create_sqls[0]

    def test_missing_column_emits_single_alter(self, monkeypatch):
        cursor = _patch(monkeypatch, existing_columns=())
        _migrate_usage_logs_user_id(cursor)
        probes = [s for s, _ in cursor.executed
                  if "information_schema.COLUMNS" in s]
        alters = [s for s, _ in cursor.executed if s.startswith("ALTER TABLE")]
        # 每列 = 1 探测 + 至多 1 条 ALTER；缺失态恰好 1 条，且与常量同文
        assert len(probes) == 1
        assert alters == [USAGE_LOGS_USER_ID_COLUMN[1]]

    def test_idempotent_when_column_exists(self, monkeypatch):
        # 探测命中（列已在）→ 零 ALTER（幂等核心断言）
        cursor = _patch(monkeypatch,
                        existing_columns={("usage_logs", "user_id")})
        _migrate_usage_logs_user_id(cursor)
        _migrate_usage_logs_user_id(cursor)
        assert [s for s, _ in cursor.executed if s.startswith("ALTER")] == []

    def test_init_database_hooks_migration(self):
        """init_database 全链路挂了迁移调用（建表后、视图前），存量库与新库
        同一条路径 —— 启动即补列，不依赖额外 ensure_* 调用纪律。"""
        src = inspect.getsource(db.init_database)
        assert "_migrate_usage_logs_user_id(cursor)" in src


# ============================================
# 2) log_usage 写路径（假游标；向后兼容 + 归因）
# ============================================
class TestLogUsageUserId:
    def test_signature_backward_compatible(self):
        """(verb, device_info=None, user_id=None)：user_id 关键字默认 None，
        既有调用（log_usage(verb) / log_usage(verb, device)）零破坏。"""
        sig = inspect.signature(db.log_usage)
        assert list(sig.parameters) == ["verb", "device_info", "user_id"]
        assert sig.parameters["user_id"].default is None
        assert sig.parameters["user_id"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    def test_legacy_call_keeps_old_sql(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert db.log_usage("run") is True
        sql, params = cursor.executed[-1]
        assert sql == "INSERT INTO usage_logs (verb, device_info) VALUES (%s, %s)"
        assert params == ("run", None)

    def test_user_id_none_keeps_old_sql(self, monkeypatch):
        """未登录（显式 user_id=None，app 层归因路径）同样走旧形态 ——
        列值由列默认 NULL 表达（RV2-3 第 1 类），不用 0 冒充。"""
        cursor = _patch_plain(monkeypatch)
        assert db.log_usage("run", user_id=None) is True
        sql, params = cursor.executed[-1]
        assert "user_id" not in sql
        assert params == ("run", None)

    def test_user_id_written(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert db.log_usage("run", user_id=7) is True
        sql, params = cursor.executed[-1]
        assert "INSERT INTO usage_logs (verb, device_info, user_id)" in sql
        assert params == ("run", None, 7)

    def test_device_info_with_user_id(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert db.log_usage("run", device_info="web", user_id=3) is True
        sql, params = cursor.executed[-1]
        assert "user_id" in sql
        assert params == ("run", "web", 3)

    def test_migration_missing_degrades_not_crashes(self, monkeypatch):
        """归因列未迁移到位（降级态）：带 user_id 的写入失败返回 False 只记
        日志；旧形态写入不受影响仍然成功 —— 归因缺失不拖垮查询主链路。"""
        cursor = FakeFx27Cursor()
        cursor.error_on = ("user_id",)
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        assert db.log_usage("run", user_id=7) is False
        assert db.log_usage("run") is True


# ============================================
# 3) app._record_query 归因（bare 模式 session_state，test_fx3 同款）
# ============================================
class TestRecordQueryAttribution:
    @pytest.fixture(autouse=True)
    def _clean_session(self):
        import streamlit as _real_st

        _real_st.session_state.pop("user", None)
        yield
        _real_st.session_state.pop("user", None)

    def _capture(self, monkeypatch):
        captured = {}

        def fake_log_usage(verb, device_info=None, user_id=None):
            captured["args"] = (verb, device_info, user_id)
            return True

        monkeypatch.setattr(app_module, "log_usage", fake_log_usage)
        monkeypatch.setattr(app_module, "DB_AVAILABLE", True)
        return captured

    def test_logged_in_records_user_id(self, monkeypatch):
        import streamlit as _real_st

        _real_st.session_state["user"] = {"id": 42, "username": "fx27_user"}
        captured = self._capture(monkeypatch)
        app_module._record_query("run")
        assert captured["args"] == ("run", None, 42)

    def test_anonymous_records_none(self, monkeypatch):
        """未登录（session 无 user）→ user_id=None，列值即 NULL 留痕。"""
        captured = self._capture(monkeypatch)
        app_module._record_query("run")
        assert captured["args"] == ("run", None, None)

    @pytest.mark.parametrize("dirty_id", [True, "42", [], {}])
    def test_dirty_session_id_cleaned_by_as_int(self, monkeypatch, dirty_id):
        """脏 id（bool/串/容器）经 as_int 清洗：布尔与容器 → None（不冒充
        id），整值串 → 42（宽松转 int 统一口径）。"""
        import streamlit as _real_st

        _real_st.session_state["user"] = {"id": dirty_id}
        captured = self._capture(monkeypatch)
        app_module._record_query("run")
        expected = 42 if dirty_id == "42" else None
        assert captured["args"][2] is expected

    def test_db_unavailable_no_write(self, monkeypatch):
        called = []
        monkeypatch.setattr(app_module, "DB_AVAILABLE", False)
        monkeypatch.setattr(app_module, "log_usage",
                            lambda *a, **k: called.append(1) or True)
        app_module._record_query("run")
        assert called == []

    def test_empty_verb_no_write(self, monkeypatch):
        called = []
        monkeypatch.setattr(app_module, "DB_AVAILABLE", True)
        monkeypatch.setattr(app_module, "log_usage",
                            lambda *a, **k: called.append(1) or True)
        app_module._record_query("")
        assert called == []


# ============================================
# 4) 真库沙箱（web_word_fx27_test：init 全链路 + 写入 + 聚合口径）
# ============================================
def _q(sql, params=()):
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


_USER_ID_COL = ("SELECT IS_NULLABLE, COLUMN_TYPE, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'usage_logs' AND COLUMN_NAME = 'user_id'")


class TestFx27RealDb:
    """迁移/写入/聚合口径跑在真实 MySQL 8.0（已授权沙箱库 web_word_fx27_test，
    每用例 DROP+CREATE 重建，互不污染）。"""

    @pytest.fixture
    def fx27_db(self, monkeypatch):
        original_database = db.MYSQL_DATABASE
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
        )
        cur = conn.cursor()
        try:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            cur.execute(
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无沙箱库权限，跳过 FX27 集成测试: {e}")
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        # init 全链路（建表 → _migrate_schema → FX-27 归因列迁移 → 视图）
        assert db.init_database(max_retries=1) is True

        yield

        monkeypatch.setattr(db, "MYSQL_DATABASE", original_database)
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.commit()
        conn.close()

    def test_user_id_column_created_nullable(self, fx27_db):
        rows = _q(_USER_ID_COL)
        assert len(rows) == 1
        assert rows[0]["IS_NULLABLE"] == "YES"
        assert rows[0]["COLUMN_TYPE"] == "int"
        # RV2-3 口径随列 COMMENT 落库，防后人改回 NOT NULL/伪默认值
        assert "RV2-3" in (rows[0]["COLUMN_COMMENT"] or "")

    def test_migration_idempotent_rerun(self, fx27_db):
        # 二次 init 全链路不炸、不重复加列
        assert db.init_database(max_retries=1) is True
        assert len(_q(_USER_ID_COL)) == 1
        # 迁移函数直调（探测命中）同样零 ALTER 不抛
        with db.get_db_cursor() as cursor:
            _migrate_usage_logs_user_id(cursor)
        assert len(_q(_USER_ID_COL)) == 1

    def test_legacy_table_upgrade_keeps_rows(self, fx27_db):
        """存量库形态：旧形 usage_logs（无 user_id）带历史行 → 迁移补列后
        历史行保留、user_id 为 NULL（存量 = 系统作业口径），此后登录写入可用。"""
        with db.get_db_cursor() as cursor:
            cursor.execute("DROP TABLE usage_logs")
            cursor.execute(
                "CREATE TABLE usage_logs ("
                " id INT AUTO_INCREMENT PRIMARY KEY,"
                " verb VARCHAR(100) NOT NULL,"
                " query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                " device_info VARCHAR(255),"
                " INDEX idx_usage_logs_verb (verb(50)))"
            )
            cursor.execute("INSERT INTO usage_logs (verb) VALUES ('run')")
        with db.get_db_cursor() as cursor:
            _migrate_usage_logs_user_id(cursor)
        rows = _q("SELECT verb, user_id FROM usage_logs")
        assert len(rows) == 1
        assert rows[0]["verb"] == "run"
        assert rows[0]["user_id"] is None
        assert db.log_usage("walk", user_id=9) is True

    def test_logged_in_and_anonymous_writes(self, fx27_db):
        assert db.log_usage("run", user_id=7) is True
        assert db.log_usage("walk") is True                # 既有调用形态
        assert db.log_usage("jump", user_id=None) is True  # 显式未登录
        by_verb = {r["verb"]: r["user_id"]
                   for r in _q("SELECT verb, user_id FROM usage_logs")}
        assert by_verb["run"] == 7
        assert by_verb["walk"] is None
        assert by_verb["jump"] is None

    def test_stats_and_hot_verbs_aggregation_unchanged(self, fx27_db):
        """口径不变：user_id 不参与聚合 —— 总查询次数逐条计，同词不同人
        合并计热度（归因列只留痕，不分裂统计）。"""
        db.get_hot_verbs.clear()
        assert db.log_usage("run", user_id=1) is True
        assert db.log_usage("run", user_id=2) is True
        assert db.log_usage("walk") is True
        stats = db.get_stats()
        assert stats["total_queries"] == 3
        assert stats["queries_today"] == 3
        hot = {h["verb"]: h["count"] for h in db.get_hot_verbs(TEST_DB, limit=5)}
        assert hot["run"] == 2
        assert hot["walk"] == 1
