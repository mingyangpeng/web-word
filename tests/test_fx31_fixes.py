"""用户上下文域 5 表测试（src/user_context_db.py，FX-31）。

三层结构，与 tests/ 既有约定一致（仿 test_llm_providers_db.py）：

  * DDL 契约纯单元（规范 §6 D⑨ 表名清单 → 本模块 DDL 常量逐项对齐）——
    零数据库依赖，本地与 CI 全跑；
  * 数据层 CRUD（ensure 幂等 / 未登录 fail-closed / own-rows-only /
    upsert 覆盖幂等 / updated_at 手动刷新）—— 真实 MySQL 专用测试库
    web_word_fx31_test，连不上或账号无建库权限就 skip，CI 依然全绿；
  * 降级路径（get_db_cursor 抛错 → 安全值：读 [] / 写 False / ensure
    只记日志不抛、哨兵不置位）—— 全 mock，不依赖真库。

核心契约（任务验收口径）：
  * ensure 二次执行不炸（CREATE TABLE IF NOT EXISTS + 进程哨兵直通，
    失败不置位下次自动重试）；
  * session 无登录 → fail-closed 返回空且**零 DB 访问**（上下文域是
    登录态功能）；
  * 只读写自己的行：A 写 B 读不到，B 删 A 的行 = False 且 A 行无损 ——
    数据层没有越过 user_id 的入口（user_id 一律会话派生）；
  * upsert 同键二写覆盖（单行），且值未变化的重复写也是成功；
  * 更新语句手动刷 updated_at（dict_admin_db 回滚恢复先例）—— 把
    updated_at 强制拨回 2000 年再 upsert，验证 NOW() 刷新、created_at 不动。
"""

import json
import os
import queue
import sys
import time
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src import user_context_db as ucdb  # noqa: E402
from src.user_context_db import (  # noqa: E402
    BOOKMARK_ANCHOR_TYPES,
    DRAFT_STATES_TABLE_SQL,
    USER_BOOKMARKS_TABLE_SQL,
    USER_NOTES_TABLE_SQL,
    USER_PROFILES_TABLE_SQL,
    USER_STATE_TABLE_SQL,
    delete_bookmark,
    delete_draft,
    delete_note,
    delete_profile,
    delete_state,
    ensure_user_context_tables,
    list_bookmarks,
    list_drafts,
    list_notes,
    list_profiles,
    list_states,
    upsert_bookmark,
    upsert_draft,
    upsert_note,
    upsert_profile,
    upsert_state,
)

TEST_DB = "web_word_fx31_test"

# 规范 §6 D⑨ 五表名（顺序与本模块 _USER_CONTEXT_TABLE_DDLS 元组一致）
SPEC_TABLE_NAMES = (
    "user_profiles",
    "user_state",
    "user_bookmarks",
    "user_notes",
    "draft_states",
)

_NO_DB_TOUCH = "被测路径不应触碰数据库（fail-closed/校验须在任何 DB 访问之前）"

_OLD_TS = datetime(2000, 1, 1, 0, 0, 0)

# A/B 两个测试身份（RV14-2 后 FK 生效：user_id 必须指向真实 users 行，
# fixture 在测试库里以显式 id 建这两行）
UID_A = 101
UID_B = 202


def _q(sql: str, params: tuple = ()):
    """测试内直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _count(table: str) -> int:
    """表内总行数（own-rows-only 断言：任何时刻 5 表行数都可预测）。"""
    rows = _q(f"SELECT COUNT(*) AS n FROM {table}")
    return int(rows[0]["n"])


def _as_json(raw):
    """JSON 列读出的容错折算（pymysql 可能给 str 也可能给原生结构）。"""
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _login(monkeypatch, uid: int, username: str = "fx31") -> None:
    """把会话钉到指定用户（ucdb.current_user 是模块级引用，patch 即生效）。"""
    monkeypatch.setattr(
        ucdb, "current_user", lambda: {"id": uid, "username": username}
    )


def _force_old_timestamps(table: str, where_pairs: tuple) -> None:
    """把某行 created_at/updated_at 强制拨回 2000 年（验证手动刷新用）。

    where_pairs 首对必须是 (user_id, uid)；列名全部来自代码常量。
    """
    set_clause = "created_at = %s, updated_at = %s"
    where_clause = " AND ".join(f"{col} = %s" for col, _ in where_pairs)
    params = (_OLD_TS, _OLD_TS, *(val for _, val in where_pairs))
    _q(f"UPDATE {table} SET {set_clause} WHERE {where_clause}", params)


# A 用户在 5 表各写一行（own-rows-only / 行数预测的统一种子）
_A_WRITES = (
    ("user_profiles", lambda: upsert_profile("ui.theme", "dark")),
    ("user_state", lambda: upsert_state("last_sense", "42")),
    ("user_bookmarks", lambda: upsert_bookmark("sense", "42", title="好义位")),
    ("user_notes", lambda: upsert_note(42, "A 的私人笔记")),
    ("draft_states", lambda: upsert_draft("def:sense:42", {"text": "A 草稿"})),
)


# ============================================
# DDL 契约（纯单元，零数据库依赖）
# ============================================

class TestDdlContract:
    """规范 §6 D⑨ 五表名 → 本模块 DDL 常量逐项对齐（不触库）。"""

    def test_five_ddls_match_spec_names(self):
        d = ucdb._USER_CONTEXT_TABLE_DDLS
        assert d == (
            USER_PROFILES_TABLE_SQL,
            USER_STATE_TABLE_SQL,
            USER_BOOKMARKS_TABLE_SQL,
            USER_NOTES_TABLE_SQL,
            DRAFT_STATES_TABLE_SQL,
        )
        for name, ddl in zip(SPEC_TABLE_NAMES, d):
            assert f"CREATE TABLE IF NOT EXISTS {name} " in ddl

    def test_domain_discipline_columns_in_every_ddl(self):
        """域纪律落 DDL：每表 user_id NOT NULL + 双时间戳默认值 +
        user_id 外键 ON DELETE CASCADE（RV14-2：用户自有表类，删号自愈）。"""
        for ddl in ucdb._USER_CONTEXT_TABLE_DDLS:
            assert "user_id INT NOT NULL" in ddl
            assert (
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl
            )
            assert (
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl
            )
            # RV14-2：外键统一引用 users(id)，删除口径 CASCADE（只约束新建表）
            assert ("FOREIGN KEY (user_id) REFERENCES users(id) "
                    "ON DELETE CASCADE" in ddl)

    def test_bookmark_anchor_types_match_ddl_enum(self):
        """应用层白名单与 DDL ENUM 同值（先拒非法值，MySQL 报错只是最后防线）。"""
        enum_part = USER_BOOKMARKS_TABLE_SQL[
            USER_BOOKMARKS_TABLE_SQL.index("anchor_type ENUM"):]
        for value in BOOKMARK_ANCHOR_TYPES:
            assert f"'{value}'" in enum_part.split(")")[0]
        assert BOOKMARK_ANCHOR_TYPES == ("sense", "entry", "page")


# ============================================
# 未登录 fail-closed（零 DB 访问；全 mock）
# ============================================

class TestFailClosedNoLogin:
    """session 无有效登录 → 15 个入口全返回安全值且不触库。

    哨兵钉在 True（运行中进程的常态）确保 ensure 直通；get_db_cursor 被
    patch 成炸点 —— 任何一次触库都会让用例以 AssertionError 失败。
    """

    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError(_NO_DB_TOUCH)

        monkeypatch.setattr(ucdb, "current_user", lambda: None)
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)
        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)

    @pytest.mark.parametrize("fn", [
        list_profiles, list_states, list_bookmarks, list_notes, list_drafts,
    ])
    def test_list_returns_empty_without_db(self, fn):
        assert fn() == []

    @pytest.mark.parametrize("fn,args", [
        (upsert_profile, ("ui.theme", "dark")),
        (upsert_state, ("last_sense", "42")),
        (upsert_bookmark, ("sense", "42")),
        (upsert_note, (42, "笔记")),
        (upsert_draft, ("f:k", {"a": 1})),
    ])
    def test_upsert_fails_closed_without_db(self, fn, args):
        assert fn(*args) is False

    @pytest.mark.parametrize("fn,args", [
        (delete_profile, ("ui.theme",)),
        (delete_state, ("last_sense",)),
        (delete_bookmark, ("sense", "42")),
        (delete_note, (42,)),
        (delete_draft, ("f:k",)),
    ])
    def test_delete_fails_closed_without_db(self, fn, args):
        assert fn(*args) is False

    @pytest.mark.parametrize("dirty_user", [
        None,                       # session 无 user 键
        "admin",                    # user 非 dict（脏值）
        {},                         # dict 缺 id
        {"username": "x"},          # 同上，别种脏形状
        {"id": None},               # id 为 None
        {"id": 0},                  # id=0 不是合法主键
        {"id": -5},                 # 负 id
        {"id": True},               # bool 先拦（as_int 契约，True!=1）
        {"id": "abc"},              # 非整数串
        {"id": []},                 # 结构垃圾
    ])
    def test_dirty_session_fail_closed(self, dirty_user, monkeypatch):
        monkeypatch.setattr(ucdb, "current_user", lambda: dirty_user)
        assert list_profiles() == []
        assert list_notes() == []
        assert upsert_profile("k", "v") is False
        assert upsert_note(42, "n") is False
        assert delete_draft("f") is False
        assert delete_state("k") is False


# ============================================
# 建表与 DDL 实测契约（真库）
# ============================================

@pytest.fixture
def ctx_db():
    """建空测试库并让本模块指向它；ensure 跑两遍验幂等；结束 DROP。

    teardown 走 finally（用例失败也必须还原 db.MYSQL_DATABASE 与进程级
    哨兵 —— 全局态泄漏会污染后续用例）。跳库（无建库权限）发生在改全局
    之前，哨兵不受影响。
    """
    import pymysql

    sentinel_before = ucdb._TABLES_ENSURED

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
            # 确认库真的没了再建（防御偶发的 DROP 元数据时延——曾见一次
            # CREATE 1007 "database exists"；直连本机正常时零等待直通）
            for _ in range(40):
                cur.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.SCHEMATA "
                    "WHERE SCHEMA_NAME = %s",
                    (TEST_DB,),
                )
                if int(cur.fetchone()["n"] or 0) == 0:
                    break
                time.sleep(0.05)
            cur.execute(
                f"CREATE DATABASE {TEST_DB} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    except pymysql.err.OperationalError as e:
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过集成测试: {e}")
    finally:
        conn.close()

    old_database = db.MYSQL_DATABASE
    try:
        # RV14-2：五表 user_id 外键引用 users(id) —— 建表前 users 必须先行
        # （与生产 init_database 时序一致），且写入身份须是真实 users 行
        # （FK 生效后孤儿 user_id 会被 1452 拒绝）。
        from src.users_db import ensure_user_tables

        db.MYSQL_DATABASE = TEST_DB
        ensure_user_tables()
        _q("INSERT INTO users (id, username, password_hash, display_name, "
           "role, active) VALUES (%s, %s, %s, %s, %s, 1)",
           (UID_A, "fx31_a", "x", "A 用户", "viewer"))
        _q("INSERT INTO users (id, username, password_hash, display_name, "
           "role, active) VALUES (%s, %s, %s, %s, %s, 1)",
           (UID_B, "fx31_b", "x", "B 用户", "viewer"))
        ucdb._TABLES_ENSURED = False  # 强制重走 DDL 路径
        ensure_user_context_tables()
        ensure_user_context_tables()  # 幂等：二次执行不炸不重建
        yield
    finally:
        db.MYSQL_DATABASE = old_database
        pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
        pool = getattr(db, "_connection_pools", {}).pop(pool_key, None)
        if pool is not None:
            # 显式关掉指向测试库的池化连接（不靠 GC 的不定时机，防悬挂
            # 会话让后续 DROP/CREATE 撞上元数据时延）
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
        except Exception:  # noqa: BLE001 teardown 尽力而为，不遮掩用例异常
            pass
        ucdb._TABLES_ENSURED = sentinel_before


@pytest.mark.usefixtures("ctx_db")
class TestSchemaContract:
    """information_schema 实测：5 表齐、列结构、users FK（CASCADE）、唯一键。"""

    def test_all_five_tables_exist(self):
        rows = _q(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN (%s,%s,%s,%s,%s)",
            (TEST_DB, *SPEC_TABLE_NAMES),
        )
        assert {r["TABLE_NAME"] for r in rows} == set(SPEC_TABLE_NAMES)

    def test_column_shapes(self):
        expected = {
            "user_profiles": {
                "id", "user_id", "pref_key", "pref_value",
                "created_at", "updated_at",
            },
            "user_state": {
                "id", "user_id", "state_key", "state_value",
                "created_at", "updated_at",
            },
            "user_bookmarks": {
                "id", "user_id", "anchor_type", "anchor_id", "title", "note",
                "created_at", "updated_at",
            },
            "user_notes": {
                "id", "user_id", "sense_id", "note",
                "created_at", "updated_at",
            },
            "draft_states": {
                "id", "user_id", "form_key", "state_json",
                "created_at", "updated_at",
            },
        }
        rows = _q(
            "SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE, DATA_TYPE, "
            "COLUMN_DEFAULT FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN (%s,%s,%s,%s,%s)",
            (TEST_DB, *SPEC_TABLE_NAMES),
        )
        cols = {}
        for r in rows:
            cols.setdefault(r["TABLE_NAME"], {})[r["COLUMN_NAME"]] = r
        assert set(cols) == set(expected)
        for table, names in expected.items():
            assert set(cols[table]) == names, table
            # 上下文域 = 必须归人：user_id 一律 NOT NULL
            assert cols[table]["user_id"]["IS_NULLABLE"] == "NO", table
            for ts in ("created_at", "updated_at"):
                col = cols[table][ts]
                assert col["DATA_TYPE"] == "datetime", table
                assert col["COLUMN_DEFAULT"] == "CURRENT_TIMESTAMP", table
        # JSON 列与 NOT NULL 正文列（RV2-3 第 3 类：''=显式清空保留行）
        assert cols["draft_states"]["state_json"]["DATA_TYPE"] == "json"
        assert cols["user_notes"]["note"]["IS_NULLABLE"] == "NO"

    def test_cascade_foreign_keys_to_users(self):
        """RV14-2 实测：5 表各有指向 users 的 FK，DELETE_RULE=CASCADE
        （删 users 行 5 表行级联消失，端到端见 TestUserDeleteCascade）。"""
        rows = _q(
            "SELECT TABLE_NAME, DELETE_RULE FROM "
            "information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = %s AND REFERENCED_TABLE_NAME = 'users' "
            "AND TABLE_NAME IN (%s,%s,%s,%s,%s)",
            (TEST_DB, *SPEC_TABLE_NAMES),
        )
        by_table = {r["TABLE_NAME"]: r["DELETE_RULE"] for r in rows}
        assert set(by_table) == set(SPEC_TABLE_NAMES)
        assert all(rule == "CASCADE" for rule in by_table.values())

    def test_unique_keys_per_table(self):
        """每表的幂等唯一键就位（upsert 覆盖语义的物理兜底）。"""
        expected_keys = {
            "user_profiles": "uq_user_profiles",
            "user_state": "uq_user_state",
            "user_bookmarks": "uq_user_bookmarks",
            "user_notes": "uq_user_notes",
            "draft_states": "uq_draft_states",
        }
        rows = _q(
            "SELECT DISTINCT TABLE_NAME, INDEX_NAME FROM "
            "information_schema.STATISTICS WHERE TABLE_SCHEMA = %s "
            "AND NON_UNIQUE = 0",
            (TEST_DB,),
        )
        uniq = {}
        for r in rows:
            uniq.setdefault(r["TABLE_NAME"], set()).add(r["INDEX_NAME"])
        for table, key in expected_keys.items():
            assert key in uniq.get(table, set()), table


@pytest.mark.usefixtures("ctx_db")
class TestEnsureSentinel:
    """进程级哨兵语义：成功置位直通、失败不置位下次自动重试。"""

    def test_sentinel_set_after_success_and_passthrough(self, monkeypatch):
        assert ucdb._TABLES_ENSURED is True  # fixture 两次 ensure 后置位

        def _boom(*args, **kwargs):
            raise AssertionError("哨兵置位后 ensure 应直通，不应触库")

        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)
        ensure_user_context_tables()  # 直通：不触库不抛

    def test_failure_keeps_sentinel_clear_and_retries(self, monkeypatch):
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", False)

        def _boom(*args, **kwargs):
            raise pymysql_boom()

        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)
        ensure_user_context_tables()  # 只记日志不抛
        assert ucdb._TABLES_ENSURED is False  # 失败不置位 → 下次自动重试

    def test_generic_exception_swallowed(self, monkeypatch):
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", False)

        def _boom(*args, **kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)
        ensure_user_context_tables()
        assert ucdb._TABLES_ENSURED is False


def pymysql_boom():
    """构造一个真实 pymysql.Error（降级测试的模拟库故障）。"""
    import pymysql

    return pymysql.err.OperationalError(2003, "Can't connect to MySQL server")


# ============================================
# own-rows-only（真库）：A 写 B 读不到，B 删 A 无效
# ============================================

@pytest.mark.usefixtures("ctx_db")
class TestOwnRowsOnly:
    """权限面 = 只读写自己的行（user_id 一律会话派生，无越权入口）。"""

    def test_b_cannot_read_a(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for _, write in _A_WRITES:
            assert write() is True

        _login(monkeypatch, UID_B)
        assert list_profiles() == []
        assert list_states() == []
        assert list_bookmarks() == []
        assert list_notes() == []
        assert list_drafts() == []

    def test_b_write_same_keys_leaves_a_intact(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for _, write in _A_WRITES:
            assert write() is True

        _login(monkeypatch, UID_B)
        assert upsert_profile("ui.theme", "light") is True
        assert upsert_state("last_sense", "99") is True
        assert upsert_bookmark("sense", "42", title="B 的收藏") is True
        assert upsert_note(42, "B 的私人笔记") is True
        assert upsert_draft("def:sense:42", {"text": "B 草稿"}) is True

        # 每表恰 2 行（A 一行 + B 一行，互不覆盖）
        for table, _ in _A_WRITES:
            assert _count(table) == 2, table

        _login(monkeypatch, UID_A)
        assert [r["pref_value"] for r in list_profiles()] == ["dark"]
        assert [r["state_value"] for r in list_states()] == ["42"]
        assert [r["title"] for r in list_bookmarks()] == ["好义位"]
        assert [r["note"] for r in list_notes()] == ["A 的私人笔记"]
        assert [_as_json(r["state_json"]) for r in list_drafts()] == [
            {"text": "A 草稿"}
        ]

    def test_b_cannot_delete_a_and_can_delete_own(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for _, write in _A_WRITES:
            assert write() is True

        # B 删 A 的行：命中 0 行 → False（不是异常），A 行无损
        _login(monkeypatch, UID_B)
        assert delete_profile("ui.theme") is False
        assert delete_state("last_sense") is False
        assert delete_bookmark("sense", "42") is False
        assert delete_note(42) is False
        assert delete_draft("def:sense:42") is False
        for table, _ in _A_WRITES:
            assert _count(table) == 1, table  # 每表只有 A 的一行，无损

        # B 删自己的行：True（先写一行再删）
        assert upsert_profile("ui.theme", "light") is True
        assert delete_profile("ui.theme") is True
        assert _count("user_profiles") == 1  # 只剩 A 的行


# ============================================
# upsert 幂等（真库）：同键二写覆盖，单行
# ============================================

@pytest.mark.usefixtures("ctx_db")
class TestUpsertIdempotent:
    """INSERT ... ON DUPLICATE KEY UPDATE：同键二写覆盖；同值重写也 True。"""

    # (表名, 写旧值, 写新值, list 函数, 值列, 值折算, 二写后的期望值)
    _CASES = (
        ("user_profiles", lambda: upsert_profile("k", "v1"),
         lambda: upsert_profile("k", "v2"), list_profiles, "pref_value",
         lambda r: r, "v2"),
        ("user_state", lambda: upsert_state("k", "v1"),
         lambda: upsert_state("k", "v2"), list_states, "state_value",
         lambda r: r, "v2"),
        ("user_bookmarks", lambda: upsert_bookmark("sense", "42", title="t1"),
         lambda: upsert_bookmark("sense", "42", title="t2", note="n2"),
         list_bookmarks, "title", lambda r: r, "t2"),
        ("user_notes", lambda: upsert_note(42, "n1"),
         lambda: upsert_note(42, "n2"), list_notes, "note", lambda r: r,
         "n2"),
        ("draft_states", lambda: upsert_draft("f", {"v": 1}),
         lambda: upsert_draft("f", {"v": 2}), list_drafts, "state_json",
         _as_json, {"v": 2}),
    )

    def test_second_write_overwrites_single_row(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for table, first, second, lister, value_col, unwrap, expected \
                in self._CASES:
            assert first() is True
            assert second() is True
            rows = lister()
            assert len(rows) == 1, table
            assert unwrap(rows[0][value_col]) == expected, table
            if table == "user_bookmarks":
                assert rows[0]["note"] == "n2"  # 二写顺带覆盖备注

    def test_identical_rewrite_is_success(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for table, first, _, lister, _, _, _ in self._CASES:
            assert first() is True
            assert first() is True  # 值未变化的重复写：幂等成功（非 rowcount 口径）
            assert len(lister()) == 1, table

    def test_null_value_upsert(self, monkeypatch):
        """value=None → NULL（键已建未设值，RV2-3 第 2 类），None 再写覆盖。"""
        _login(monkeypatch, UID_A)
        assert upsert_profile("k", None) is True
        rows = list_profiles()
        assert len(rows) == 1 and rows[0]["pref_value"] is None
        assert upsert_profile("k", "v") is True
        assert list_profiles()[0]["pref_value"] == "v"

    def test_draft_none_clears_snapshot(self, monkeypatch):
        _login(monkeypatch, UID_A)
        assert upsert_draft("f", {"a": 1}) is True
        assert upsert_draft("f", None) is True  # 提交后清快照
        rows = list_drafts()
        assert len(rows) == 1 and rows[0]["state_json"] is None


# ============================================
# updated_at 手动刷新（真库；dict_admin_db 回滚恢复先例）
# ============================================

@pytest.mark.usefixtures("ctx_db")
class TestUpdatedAtRefresh:
    """把时间戳拨回 2000 年再 upsert：updated_at 被 NOW() 刷新、created_at 不动。"""

    # (表名, 拨回用 WHERE 列值对, 再次 upsert)
    _CASES = (
        ("user_profiles", (("user_id", None), ("pref_key", "k")),
         lambda: upsert_profile("k", "v2")),
        ("user_state", (("user_id", None), ("state_key", "k")),
         lambda: upsert_state("k", "v2")),
        ("user_bookmarks",
         (("user_id", None), ("anchor_type", "sense"), ("anchor_id", "42")),
         lambda: upsert_bookmark("sense", "42")),
        ("user_notes", (("user_id", None), ("sense_id", 42)),
         lambda: upsert_note(42, "n2")),
        ("draft_states", (("user_id", None), ("form_key", "f")),
         lambda: upsert_draft("f", {"v": 2})),
    )

    def test_upsert_refreshes_updated_at_only(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for table, where_pairs, rewrite in self._CASES:
            assert rewrite() is True  # 首写建行
            pairs = (("user_id", UID_A),
                     *(p for p in where_pairs if p[0] != "user_id"))
            _force_old_timestamps(table, pairs)
            row = _q(
                f"SELECT created_at, updated_at FROM {table} "
                "WHERE " + " AND ".join(f"{c} = %s" for c, _ in pairs),
                tuple(v for _, v in pairs),
            )[0]
            assert row["updated_at"] == _OLD_TS, table  # 拨回成功（前置成立）

            assert rewrite() is True  # 二写触发手动刷新
            row = _q(
                f"SELECT created_at, updated_at FROM {table} "
                "WHERE " + " AND ".join(f"{c} = %s" for c, _ in pairs),
                tuple(v for _, v in pairs),
            )[0]
            assert row["updated_at"] > _OLD_TS, table   # NOW() 刷新生效
            assert row["created_at"] == _OLD_TS, table  # created_at 不被改动


# ============================================
# 校验面（零 DB 依赖）：非法值在触库前被拒
# ============================================

class TestValidationNoDb:
    """入口校验先于任何 DB 访问（llm_providers_db 同款纪律）。"""

    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError(_NO_DB_TOUCH)

        _login(monkeypatch, UID_A)
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)
        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)

    @pytest.mark.parametrize("bad_key", ["", "   ", None, 42, "k" * 121])
    def test_bad_profile_key_rejected(self, bad_key):
        assert upsert_profile(bad_key, "v") is False
        assert delete_profile(bad_key) is False

    @pytest.mark.parametrize("bad_value", [42, 1.5, True, ["a"], {"a": 1}])
    def test_bad_profile_value_rejected(self, bad_value):
        # dict/list 必须调用方序列化（upsert_state）或走 upsert_draft
        assert upsert_profile("k", bad_value) is False

    @pytest.mark.parametrize("bad_key", ["", "   ", None, ["k"], "k" * 121])
    def test_bad_state_key_rejected(self, bad_key):
        assert upsert_state(bad_key, "v") is False
        assert delete_state(bad_key) is False

    @pytest.mark.parametrize("bad_anchor", ["word", "entry ", "", None, 42])
    def test_bad_anchor_type_rejected(self, bad_anchor):
        assert upsert_bookmark(bad_anchor, "42") is False
        assert delete_bookmark(bad_anchor, "42") is False

    @pytest.mark.parametrize("bad_anchor_id",
                             ["", "   ", None, 42, "a" * 121])
    def test_bad_anchor_id_rejected(self, bad_anchor_id):
        assert upsert_bookmark("sense", bad_anchor_id) is False
        assert delete_bookmark("sense", bad_anchor_id) is False

    @pytest.mark.parametrize("bad_title", [42, True, ["t"], "t" * 201])
    def test_bad_title_rejected(self, bad_title):
        assert upsert_bookmark("sense", "42", title=bad_title) is False

    @pytest.mark.parametrize("bad_note", [42, True, ["n"], "n" * 501])
    def test_bad_bookmark_note_rejected(self, bad_note):
        assert upsert_bookmark("sense", "42", note=bad_note) is False

    @pytest.mark.parametrize("bad_sense_id",
                             [0, -1, None, "abc", True, [1]])
    def test_bad_sense_id_rejected(self, bad_sense_id):
        # 注意：非整数 float（如 1.5）随仓库 as_int 的宽松口径被截断为 int，
        # 不在本拒绝集（as_int 是 db_utils 单一实现点，本模块不改其语义）。
        assert upsert_note(bad_sense_id, "n") is False
        assert delete_note(bad_sense_id) is False

    @pytest.mark.parametrize("bad_note", [None, 42, True, ["n"]])
    def test_bad_note_body_rejected(self, bad_note):
        assert upsert_note(42, bad_note) is False

    @pytest.mark.parametrize("bad_form_key",
                             ["", "   ", None, 42, "f" * 151])
    def test_bad_form_key_rejected(self, bad_form_key):
        assert upsert_draft(bad_form_key, {"a": 1}) is False
        assert delete_draft(bad_form_key) is False

    @pytest.mark.parametrize("bad_state", ["pre-serialized", 42, True])
    def test_bad_draft_state_rejected(self, bad_state):
        # str 拒收（是否已序列化有二义性）；标量拒收 —— 要存串走 upsert_state
        assert upsert_draft("f", bad_state) is False

    def test_draft_accepts_dict_list_none(self, monkeypatch):
        # 合法三形态在无库环境只到校验为止：把 get_db_cursor 换成可控假 cursor
        captured = {}

        class _FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                captured["params"] = params

        monkeypatch.setattr(ucdb, "get_db_cursor", lambda *a, **k: _FakeCursor())
        assert upsert_draft("f", {"a": 1, "b": ["中文"]}) is True
        payload = json.loads(captured["params"][2])
        assert payload == {"a": 1, "b": ["中文"]}
        assert upsert_draft("f", None) is True
        assert captured["params"][2] is None


# ============================================
# 库不可用降级（全 mock）：读 [] / 写 False / ensure 静默
# ============================================

class TestDbDownDegradation:
    """get_db_cursor 抛错 → 全部安全值（页面绝不崩）。"""

    def _install_boom(self, monkeypatch, exc_factory):
        def _boom(*args, **kwargs):
            raise exc_factory()

        # 已登录（否则 fail-closed 会先挡住，测不到降级路径）
        _login(monkeypatch, UID_A)
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", False)
        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)

    def test_pymysql_error_degrades_to_safe_values(self, monkeypatch):
        self._install_boom(monkeypatch, pymysql_boom)

        ensure_user_context_tables()  # 只记日志，不抛
        assert ucdb._TABLES_ENSURED is False

        assert list_profiles() == []
        assert list_states() == []
        assert list_bookmarks() == []
        assert list_notes() == []
        assert list_drafts() == []

        assert upsert_profile("k", "v") is False
        assert upsert_state("k", "v") is False
        assert upsert_bookmark("sense", "42") is False
        assert upsert_note(42, "n") is False
        assert upsert_draft("f", {"a": 1}) is False

        assert delete_profile("k") is False
        assert delete_state("k") is False
        assert delete_bookmark("sense", "42") is False
        assert delete_note(42) is False
        assert delete_draft("f") is False

    def test_generic_exception_degrades_to_safe_values(self, monkeypatch):
        self._install_boom(monkeypatch, RuntimeError)

        ensure_user_context_tables()
        assert list_profiles() == []
        assert upsert_note(42, "n") is False
        assert delete_draft("f") is False

    def test_degradation_after_prior_success(self, monkeypatch):
        """哨兵置位后库挂掉：ensure 直通照旧，CRUD 走降级。"""
        self._install_boom(monkeypatch, pymysql_boom)
        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)
        ensure_user_context_tables()  # 直通（不触库）
        assert list_profiles() == []
        assert upsert_profile("k", "v") is False


# ============================================
# RV14-2：删 users 行 → 5 表行级联消失（真库端到端）
# ============================================

@pytest.mark.usefixtures("ctx_db")
class TestUserDeleteCascade:
    """用户自有表类的删除口径：账号物理删除时上下文行 CASCADE 跟随消失
    （RV2-2「users FK 删除纪律」分类口径，单一出处 users_db.py）；他人行无损。"""

    def test_delete_user_cascades_five_tables(self, monkeypatch):
        _login(monkeypatch, UID_A)
        for _, write in _A_WRITES:
            assert write() is True
        _login(monkeypatch, UID_B)
        for _, write in _A_WRITES:
            assert write() is True

        _q("DELETE FROM users WHERE id = %s", (UID_A,))

        for table, _ in _A_WRITES:
            assert _count(table) == 1, f"{table}: 删号未级联（应只剩 B 一行）"
        # B 的行完好（逐表核对归属：删的是 A，B 行不受牵连）
        for table, _ in _A_WRITES:
            rows = _q(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = %s",
                      (UID_B,))
            assert int(rows[0]["n"]) == 1, table

    def test_fk_rejects_orphan_user_id(self):
        """FK 真实生效：user_id 指向不存在的 users 行被库拒绝（1452）——
        本域「必须归人」从应用层口径落到物理约束。"""
        import pymysql

        with pytest.raises(pymysql.err.IntegrityError) as excinfo:
            _q("INSERT INTO user_profiles (user_id, pref_key, pref_value) "
               "VALUES (999999, 'k', 'v')")
        assert excinfo.value.args[0] == 1452
