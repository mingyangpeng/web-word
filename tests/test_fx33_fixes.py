"""FX-33 修复批次回归测试（十镜头 review 第一波 findings，第 18 轮起）。

覆盖台账（逐条对照修复任务书）：

  * RV14-3 两步激活 TOCTOU＋并发首置 UNIQUE（src/tool_settings_db.py）：
    撤位闸 / enabled 置位闸改 UPDATE WHERE 原子复验 —— 桩 rowcount=0 的
    两分支归因（仍 enabled=1 拒「工具仍启用」/ available 被并发撤下拒；
    重复撤位与重复置位按幂等成功照写审计）；首置 INSERT 捕 1062
    （Duplicate entry）转幂等 UPDATE 读回现值返回 True；非 1062 冲突照旧
    降级 False；真库沙箱回归两步激活全链不受原子复验影响；
  * RV14-9 available_set(available=False) 无行 → 幂等熄灭 True（同
    enabled_set 无行熄灭先例），不 INSERT available=0 空行、不写审计；
  * RV14-2 user_context 5 表补 FK users(id) ON DELETE CASCADE（用户自有表
    类，RV2-2「只约束新建表」纪律）：DDL 契约逐表含 FK 子句＋真库沙箱
    删 users 行 5 表行级联消失、他人行无损、FK 真实生效（孤儿 user_id
    插入被拒）；存量库不追溯（IF NOT EXISTS 语义）——无存量可测；
  * RV14-7 user_bookmarks 双口径＋冗余索引：_check_opt_text 空白串归一
    None（DDL「NULL=未命名」单口径）；DDL 删 idx_user_bookmarks_user
    （uq_user_bookmarks 最左前缀完全重复）；真库实测无该冗余索引；
  * RV14-5 长度闸＋归因：broadcast_db.publish_broadcast body 10000 字符闸
    （超限归因「正文超长」而非「数据库不可用」，返回体带 reason 字段）；
    页面按 reason 显示真实原因（stub 渲染）；user_context_db KV 值与笔记
    正文 50000 字符闸（入参校验先于 DB 访问，超长不触库）；
  * RV15-1 落地分支 1 按可裁决角色过滤（src/app.py）：viewer/annotator/
    editor/sys_admin 有全局 pending 也不落 ai_hub（顺序到续接点/搜索）；
    dict_admin/reviewer（含 legacy admin）pending>0 → ai_hub；
  * RV15-3 「继续：…」规范面落位：分支 2 命中 → ui_kit.flash
    「已回到上次工作位置：{页名}」；分支 1/3 不 flash；
  * RV15-2 广播表单陈旧载荷跨项目（src/dict_admin_pages.py）：form 三键
    按项目作用域化（切项目键不同 → 会话 widget 状态不残留）＋段头 caption
    回显「发布目标：{项目名}」；
  * RV13-6 _is_dict_admin 收口：effective_six_roles 薄封装（判定语义与
    原实现等价：legacy admin / roles 快照 dict_admin 放行，其余 fail-closed），
    docstring 无「过渡期」。

测试分层与仓库约定一致：纯单元（桩 cursor / stub st / 纯会话计算）本地
CI 全跑；真库集成跑独立测试库 web_word_fx33_test，连不上或无建库权限
skip，CI 依然全绿。
"""

import inspect
import json
import logging
import os
import queue
import sys
import time
from types import SimpleNamespace

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.dict_admin_pages as dp  # noqa: E402
import src.mysql_db as db  # noqa: E402
import src.tool_settings_db as tsd  # noqa: E402
from src import app as app_module  # noqa: E402
from src import broadcast_db as bdb  # noqa: E402
from src import ui_kit  # noqa: E402
from src.page_guides import page_label  # noqa: E402
from src.tool_settings_db import (  # noqa: E402
    available_set,
    available_unset,
    enabled_set,
)
from src.user_context_db import (  # noqa: E402
    MAX_KV_VALUE_LEN,
    MAX_NOTE_LEN,
    DRAFT_STATES_TABLE_SQL,
    USER_BOOKMARKS_TABLE_SQL,
    USER_NOTES_TABLE_SQL,
    USER_PROFILES_TABLE_SQL,
    USER_STATE_TABLE_SQL,
    _check_opt_text,
    ensure_user_context_tables,
    upsert_note,
    upsert_profile,
    upsert_state,
)

TEST_DB = "web_word_fx33_test"

# 会话用户样例（与 users_db/app 登录态同构：role=legacy 列，roles=会话快照）
SYS_ADMIN = {"id": 2, "username": "sys_a", "role": "viewer",
             "roles": ["sys_admin"]}
DICT_ADMIN = {"id": 3, "username": "dict_a", "role": "viewer",
              "roles": ["dict_admin"]}
REVIEWER = {"id": 6, "username": "rev", "role": "reviewer",
            "roles": ["reviewer"]}
LEGACY_ADMIN = {"id": 1, "username": "admin", "role": "admin"}  # 两位一体
EDITOR = {"id": 4, "username": "ed", "role": "viewer", "roles": ["editor"]}
ANNOTATOR = {"id": 7, "username": "ann", "role": "annotator",
             "roles": ["annotator"]}
VIEWER = {"id": 5, "username": "vw", "role": "viewer", "roles": ["viewer"]}


@pytest.fixture(autouse=True)
def _clean_flash_queue():
    """ui_kit flash 队列清空（裸模式 session_state 跨用例残留防护）。"""
    st_state = ui_kit.st.session_state
    st_state.pop(ui_kit._FLASH_QUEUE_KEY, None)
    yield
    st_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


@pytest.fixture(autouse=True)
def _reset_resume_loader():
    """app 落地 loader 缝复位（模块级缝不跨用例泄漏）。"""
    yield
    app_module.set_resume_page_loader(None)


def _pop_flash_queue():
    st_state = ui_kit.st.session_state
    queue_val = st_state.pop(ui_kit._FLASH_QUEUE_KEY, None)
    return queue_val if isinstance(queue_val, list) else []


def pymysql_boom():
    """构造真实 pymysql.Error（降级路径模拟库故障）。"""
    return pymysql.err.OperationalError(2003, "Can't connect to MySQL server")


# ============================================
# 桩件：tool_settings 假 cursor（并发语义单测）
# ============================================

class _TSCursor:
    """tool_settings 假 cursor：读行按队列回放；写语句 rowcount 按脚本给出。

    读（SELECT）恒 rowcount=1（模块不消费读 rowcount）；UPDATE/INSERT 的
    rowcount 从 update_rowcounts 队列按序弹出（默认 1）—— 并发语义单测
    用它脚本化「预检读到旧态、UPDATE 执行时刻行已变」的 rowcount=0 路径。
    """

    def __init__(self, read_rows=(), update_rowcounts=()):
        self._read_rows = list(read_rows)
        self._update_rowcounts = list(update_rowcounts)
        self.executed = []          # (规整 SQL 文本, params)
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _record(self, sql, params):
        self.executed.append((" ".join(sql.split()), params))

    def _set_rowcount(self, sql):
        flat = " ".join(sql.split())
        if flat.upper().startswith(("UPDATE", "INSERT", "DELETE")):
            self.rowcount = (self._update_rowcounts.pop(0)
                             if self._update_rowcounts else 1)
        else:
            self.rowcount = 1

    def execute(self, sql, params=None):
        self._record(sql, params)
        self._set_rowcount(sql)

    def fetchone(self):
        return self._read_rows.pop(0) if self._read_rows else None


class _DupEntryCursor(_TSCursor):
    """首置 INSERT 抛 1062（Duplicate entry）的假 cursor（RV14-3 并发首置）。

    读队列：第一读返回 None（无行）→ INSERT 撞 UNIQUE 抛 1062 → 第二读
    回放竞速对手已建的行（raced_row）。异常前先记录语句（断言执行面）。
    """

    def __init__(self, raced_row):
        super().__init__(read_rows=[None, raced_row])

    def execute(self, sql, params=None):
        self._record(sql, params)
        flat = " ".join(sql.split())
        if flat.startswith("INSERT") and not flat.startswith(
                "INSERT INTO settings_audit"):
            raise pymysql.err.IntegrityError(
                1062,
                "Duplicate entry 'motion-typicality' for key 'uq_category_tool'")
        self._set_rowcount(sql)


class _OtherIntegrityCursor(_TSCursor):
    """INSERT 抛非 1062 完整性错误（如列约束）的假 cursor（照旧降级口径）。"""

    def execute(self, sql, params=None):
        self._record(sql, params)
        flat = " ".join(sql.split())
        if flat.startswith("INSERT INTO category_tool_settings"):
            raise pymysql.err.IntegrityError(
                1048, "Column 'category' cannot be null")
        self._set_rowcount(sql)


def _row(available=1, enabled=0, row_id=5):
    return {"id": row_id, "category": "motion", "tool_id": "typicality",
            "tool_version": None, "available": available, "enabled": enabled,
            "params": None, "updated_by": None, "created_at": None,
            "updated_at": None}


def _kinds(cursor):
    """已执行语句的首词序列（断言执行面：无 INSERT / 有 UPDATE 等）。"""
    return [sql.split()[0].upper() for sql, _ in cursor.executed]


# ============================================
# RV14-3：撤位/置位原子复验（桩 rowcount=0 两分支归因）
# ============================================

class TestAtomicRevalidation:
    """不变式闸并入 UPDATE WHERE 的并发语义（预检放行、执行时刻裁决）。"""

    def test_unset_rowcount_zero_still_enabled_rejected(self, monkeypatch, caplog):
        """撤位 UPDATE ... AND enabled=0 命中 0 行、复读发现 enabled=1 →
        拒绝，归因「工具仍启用，先解除 enabled」（TOCTOU：预检后并发点亮）。"""
        cur = _TSCursor(read_rows=[_row(available=1, enabled=0),
                                   _row(available=1, enabled=1)],
                        update_rowcounts=[0])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        with caplog.at_level(logging.ERROR, logger="src.tool_settings_db"):
            assert available_unset("motion", "typicality", actor=SYS_ADMIN) is False
        assert any("仍 enabled=1" in r.message for r in caplog.records)
        # 执行面：撤位 UPDATE 带 enabled=0 守卫（原子复验），未写审计
        sqls = [sql for sql, _ in cur.executed]
        assert any("SET available = 0" in s and "AND enabled = 0" in s
                   for s in sqls)
        assert not any("INSERT INTO settings_audit" in s for s in sqls)

    def test_unset_rowcount_zero_idempotent_rewrite_succeeds(self, monkeypatch):
        """撤位 UPDATE 命中 0 行但复读 enabled=0/available 已 0 → 重复撤位
        （无状态变更）幂等成功，照写审计（每次动作留痕的既有口径）。"""
        cur = _TSCursor(read_rows=[_row(available=0, enabled=0),
                                   _row(available=0, enabled=0)],
                        update_rowcounts=[0])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_unset("motion", "typicality", actor=SYS_ADMIN) is True
        sqls = [sql for sql, _ in cur.executed]
        assert any("INSERT INTO settings_audit" in s for s in sqls)

    def test_unset_rowcount_zero_row_vanished_idempotent(self, monkeypatch):
        """撤位 UPDATE 命中 0 行且复读无行（行已被并发删除）→ 幂等熄灭
        True，不写审计（无行可审计，撤位目标已达成）。"""
        cur = _TSCursor(read_rows=[_row(available=1, enabled=0), None],
                        update_rowcounts=[0])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_unset("motion", "typicality", actor=SYS_ADMIN) is True
        sqls = [sql for sql, _ in cur.executed]
        assert not any("INSERT INTO settings_audit" in s for s in sqls)

    def test_set_available_plain_update_no_guard(self, monkeypatch):
        """置位（available=1）单调安全，不加不变式守卫；无变化也成功留审计。"""
        cur = _TSCursor(read_rows=[_row(available=1, enabled=1)],
                        update_rowcounts=[0])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_set("motion", "typicality", actor=SYS_ADMIN) is True
        sqls = [sql for sql, _ in cur.executed]
        assert any("SET available = 1" in s and "AND enabled" not in s
                   for s in sqls)
        assert any("INSERT INTO settings_audit" in s for s in sqls)

    def test_enabled_set_rowcount_zero_available_pulled_rejected(
            self, monkeypatch, caplog):
        """enabled 置位 UPDATE ... AND available=1 命中 0 行、复读 available=0
        → 拒绝，归因「available 已被并发撤下」（TOCTOU：预检后并发撤下）。"""
        cur = _TSCursor(read_rows=[_row(available=1, enabled=0),
                                   _row(available=0, enabled=0)],
                        update_rowcounts=[0])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        monkeypatch.setattr(tsd._registry, "get_tool",
                            lambda key: SimpleNamespace(version="1.0.0"))
        with caplog.at_level(logging.ERROR, logger="src.tool_settings_db"):
            assert enabled_set("motion", "typicality", actor=DICT_ADMIN) is False
        assert any("available 已被" in r.message and "并发撤下" in r.message
                   for r in caplog.records)
        sqls = [sql for sql, _ in cur.executed]
        assert any("SET enabled = 1" in s and "AND available = 1" in s
                   for s in sqls)
        assert not any("INSERT INTO settings_audit" in s for s in sqls)

    def test_enabled_set_rowcount_zero_idempotent_reenable(self, monkeypatch):
        """enabled 置位 UPDATE 命中 0 行但复读 available=1 且 enabled 已 1
        → 重复置位（无状态变更）幂等成功，照写审计＋进程位同步刷新。"""
        cur = _TSCursor(read_rows=[_row(available=1, enabled=1),
                                   _row(available=1, enabled=1)],
                        update_rowcounts=[0])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        monkeypatch.setattr(tsd._registry, "get_tool",
                            lambda key: SimpleNamespace(version="1.0.0"))
        synced = []
        monkeypatch.setattr(tsd._registry, "set_enabled",
                            lambda key, flag: synced.append((key, flag)))
        assert enabled_set("motion", "typicality", actor=DICT_ADMIN) is True
        sqls = [sql for sql, _ in cur.executed]
        assert any("INSERT INTO settings_audit" in s for s in sqls)
        assert synced == [("typicality", True)]

    def test_enabled_unset_no_available_guard(self, monkeypatch):
        """enabled 撤位不需 available=1（available=0 行也照常熄灭，既有语义）。"""
        cur = _TSCursor(read_rows=[_row(available=0, enabled=1)])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        synced = []
        monkeypatch.setattr(tsd._registry, "set_enabled",
                            lambda key, flag: synced.append((key, flag)))
        assert enabled_set("motion", "typicality", actor=DICT_ADMIN,
                           enabled=False) is True
        sqls = [sql for sql, _ in cur.executed]
        assert any("SET enabled = 0" in s and "AND available" not in s
                   for s in sqls)
        assert synced == [("typicality", False)]

    def test_real_db_two_step_chain_unaffected(self, fx33_env):
        """真库回归：原子复验不改变单进程两步激活全链语义（RV14-3 不回归）。"""
        tsd.ensure_tool_settings_tables()
        assert available_set("motion", "typicality", actor=SYS_ADMIN)
        assert enabled_set("motion", "typicality", actor=DICT_ADMIN)
        row = tsd.get_setting("motion", "typicality")
        assert row["available"] == 1 and row["enabled"] == 1
        # enabled ⊆ available 不变式照旧：enabled=1 时撤位拒（原子复验路径）
        assert available_unset("motion", "typicality", actor=SYS_ADMIN) is False
        assert tsd.get_setting("motion", "typicality")["enabled"] == 1
        # 先解除 enabled 才能撤下（复验 rowcount 语义与原一致）
        assert enabled_set("motion", "typicality", actor=DICT_ADMIN,
                           enabled=False)
        assert available_unset("motion", "typicality", actor=SYS_ADMIN)
        assert tsd.get_setting("motion", "typicality")["available"] == 0


# ============================================
# RV14-3：并发首置撞 UNIQUE 1062 转幂等 ＋ 非 1062 照旧降级
# ============================================

class TestConcurrentFirstSet:
    def test_dup_entry_1062_converts_to_idempotent_update(self, monkeypatch):
        """首置 INSERT 捕 1062 → 读回竞速行 → 幂等 UPDATE 返回 True，
        审计 old→new 取竞速行现值（如实留痕）。"""
        raced = _row(available=1, enabled=1, row_id=9)
        cur = _DupEntryCursor(raced_row=raced)
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_set("motion", "typicality", actor=SYS_ADMIN) is True
        sqls = [sql for sql, _ in cur.executed]
        assert any(s.startswith("INSERT INTO category_tool_settings") for s in sqls)
        # 转幂等 UPDATE（参数化语句：SET available = %s，params[0]=1 置位）
        updates = [(sql, p) for sql, p in cur.executed
                   if sql.startswith("UPDATE category_tool_settings")]
        assert updates and updates[0][1][0] == 1
        assert "WHERE id = %s" in updates[0][0]
        audit_params = next(p for sql, p in cur.executed
                            if sql.startswith("INSERT INTO settings_audit"))
        # old→new 取竞速行现值（available=True/enabled=True → available=1 保持）
        assert json.loads(audit_params[4]) == {"available": True, "enabled": True}
        assert json.loads(audit_params[5]) == {"available": True, "enabled": True}

    def test_dup_entry_1062_raced_row_vanished_returns_true(self, monkeypatch):
        """1062 后复读无行（冲突行又消失）→ 幂等成功 True，不写审计。"""
        cur = _DupEntryCursor(raced_row=None)
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_set("motion", "typicality", actor=SYS_ADMIN) is True
        sqls = [sql for sql, _ in cur.executed]
        assert not any("INSERT INTO settings_audit" in s for s in sqls)

    def test_other_integrity_error_still_degrades(self, monkeypatch):
        """非 1062 完整性错误照旧走降级（False，外层容错口径不变）。"""
        cur = _OtherIntegrityCursor()
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_set("motion", "typicality", actor=SYS_ADMIN) is False


# ============================================
# RV14-9：available_set(available=False) 无行幂等熄灭
# ============================================

class TestUnsetWithoutRow:
    def test_unset_without_row_idempotent_no_insert_no_audit(self, monkeypatch):
        """无行撤位 → True 幂等熄灭：零写语句（不 INSERT available=0 空行）、
        不写审计（同 enabled_set 无行熄灭先例）。"""
        cur = _TSCursor(read_rows=[None])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_set("motion", "typicality", actor=SYS_ADMIN,
                             available=False) is True
        assert _kinds(cur) == ["SELECT"]  # 仅预检读，无任何写语句

    def test_unset_without_row_real_db_leaves_no_row_no_audit(self, fx33_env):
        """真库：无行撤位后仍无行、无审计行（enabled_set 照旧被前置闸拒绝）。"""
        tsd.ensure_tool_settings_tables()
        assert available_unset("motion", "typicality", actor=SYS_ADMIN) is True
        assert tsd.get_setting("motion", "typicality") is None
        assert tsd.list_audit(category="motion") == []
        # enabled 置位照旧被「未 available 先行」拒绝（无行即无先行）
        assert enabled_set("motion", "typicality", actor=DICT_ADMIN) is False
        assert tsd.list_audit(category="motion") == []

    def test_set_without_row_still_inserts(self, monkeypatch):
        """无行置位照旧 INSERT（两步激活允许「先 available 未 enabled」中间态）。"""
        cur = _TSCursor(read_rows=[None])
        monkeypatch.setattr(tsd, "get_db_cursor", lambda: cur)
        assert available_set("motion", "typicality", actor=SYS_ADMIN) is True
        assert _kinds(cur) == ["SELECT", "INSERT", "INSERT"]


# ============================================
# RV14-2：user_context 5 表 FK CASCADE（DDL 契约＋真库级联）
# ============================================

SPEC_TABLE_NAMES = (
    "user_profiles",
    "user_state",
    "user_bookmarks",
    "user_notes",
    "draft_states",
)

_FK_CLAUSE = "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"


class TestCascadeDdlContract:
    def test_every_ddl_has_cascade_fk(self):
        """五表 DDL 逐表含 FOREIGN KEY ... ON DELETE CASCADE（用户自有表类）。"""
        for ddl in (USER_PROFILES_TABLE_SQL, USER_STATE_TABLE_SQL,
                    USER_BOOKMARKS_TABLE_SQL, USER_NOTES_TABLE_SQL,
                    DRAFT_STATES_TABLE_SQL):
            assert _FK_CLAUSE in ddl, ddl
            assert ddl.upper().count("FOREIGN KEY") == 1

    def test_bookmarks_redundant_user_index_removed(self):
        """RV14-7：uq_user_bookmarks 最左前缀已覆盖 user_id，冗余
        idx_user_bookmarks_user 不再出现在 DDL。"""
        assert "idx_user_bookmarks_user" not in USER_BOOKMARKS_TABLE_SQL
        assert "UNIQUE KEY uq_user_bookmarks (user_id, anchor_type, anchor_id)" \
            in USER_BOOKMARKS_TABLE_SQL

    def test_bookmarks_null_semantics_comment_registered(self):
        """RV14-7：title/note 列注释登记「空白串归一 NULL」单口径。"""
        assert "空白串归一" in USER_BOOKMARKS_TABLE_SQL


def _mysql_reachable() -> bool:
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()


def _q(sql, params=()):
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


@pytest.fixture
def fx33_env(monkeypatch):
    """建空测试库＋users(+user_roles)＋上下文域 5 表，测试结束 DROP。

    FK 引用 users —— 建表顺序 users 先行（与生产 init_database 时序一致，
    也守 RV14-2 的「建表前 users 表必须已存在」口径）；再入两个显式 id 的
    测试身份（101/202）供级联测试归人写入。
    """
    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
        autocommit=True,
    )
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        for _ in range(40):
            cur.execute(
                "SELECT COUNT(*) AS n FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME = %s", (TEST_DB,))
            if int(cur.fetchone()["n"] or 0) == 0:
                break
            time.sleep(0.05)
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
            f"COLLATE utf8mb4_unicode_ci"
        )
    except pymysql.err.OperationalError as e:
        conn.close()
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX-33 集成测试: {e}")
    conn.close()

    old_database = db.MYSQL_DATABASE
    from src import user_context_db as ucdb
    sentinel_before = ucdb._TABLES_ENSURED
    try:
        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        from src.users_db import ensure_user_tables
        ensure_user_tables()                 # users(+user_roles) 先行（FK 目标）
        ucdb._TABLES_ENSURED = False         # 强制重走 DDL 路径（新库逐用例重建）
        ensure_user_context_tables()
        ensure_user_context_tables()         # 幂等：二次执行不炸
        _q("INSERT INTO users (id, username, password_hash, display_name, "
           "role, active) VALUES (%s, %s, %s, %s, %s, 1)",
           (101, "fx33_a", "x", "A 用户", "viewer"))
        _q("INSERT INTO users (id, username, password_hash, display_name, "
           "role, active) VALUES (%s, %s, %s, %s, %s, 1)",
           (202, "fx33_b", "x", "B 用户", "viewer"))
        yield
    finally:
        db.MYSQL_DATABASE = old_database
        ucdb._TABLES_ENSURED = sentinel_before
        pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
        pool = getattr(db, "_connection_pools", {}).pop(pool_key, None)
        if pool is not None:
            while True:
                try:
                    pool.get_nowait().close()
                except queue.Empty:
                    break
                except Exception:  # noqa: BLE001 单连接关不掉不阻塞 teardown
                    pass
        try:
            conn = pymysql.connect(
                host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
                password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
                cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
                autocommit=True,
            )
            try:
                conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 teardown 尽力而为
            pass


def _login(monkeypatch, uid):
    """把 user_context_db 的会话钉到指定用户（模块级引用，patch 即生效）。"""
    from src import user_context_db as ucdb
    monkeypatch.setattr(ucdb, "current_user",
                        lambda: {"id": uid, "username": f"u{uid}"})


def _seed_user_rows(uid):
    """五表各写一行（真库，走被测 CRUD —— FK 生效要求 users 行在场）。"""
    from src import user_context_db as ucdb
    assert ucdb.upsert_profile("ui.theme", "dark") is True
    assert ucdb.upsert_state("resume_page", "cluster") is True
    assert ucdb.upsert_bookmark("sense", "42", title="好义位") is True
    assert ucdb.upsert_note(42, "私人笔记") is True
    assert ucdb.upsert_draft("def:sense:42", {"text": "草稿"}) is True


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-33 集成测试")
class TestCascadeRealDb:
    """RV14-2 真库沙箱：FK 真实生效，删 users 行 5 表行级联消失。"""

    def test_delete_user_cascades_all_five_tables(self, fx33_env, monkeypatch):
        _login(monkeypatch, 101)
        _seed_user_rows(101)
        _login(monkeypatch, 202)
        _seed_user_rows(202)
        for table in SPEC_TABLE_NAMES:
            rows = _q(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = %s",
                      (101,))
            assert int(rows[0]["n"]) == 1, table
            rows = _q(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = %s",
                      (202,))
            assert int(rows[0]["n"]) == 1, table

        _q("DELETE FROM users WHERE id = %s", (101,))

        for table in SPEC_TABLE_NAMES:
            rows = _q(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = %s",
                      (101,))
            assert int(rows[0]["n"]) == 0, f"{table}: 删号未级联"
            rows = _q(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = %s",
                      (202,))
            assert int(rows[0]["n"]) == 1, f"{table}: 他人行被误删"

    def test_fk_rejects_orphan_user_id(self, fx33_env):
        """FK 真实生效：user_id 指向不存在的 users 行直接被库拒绝（1452）。"""
        with pytest.raises(pymysql.err.IntegrityError) as excinfo:
            _q("INSERT INTO user_profiles (user_id, pref_key, pref_value) "
               "VALUES (999999, 'k', 'v')")
        assert excinfo.value.args[0] == 1452  # Cannot add or update a child row

    def test_fk_present_in_information_schema(self, fx33_env):
        """information_schema 实测：5 表各有一条指向 users 的 FK（CASCADE）。"""
        rows = _q(
            "SELECT rc.TABLE_NAME, rc.DELETE_RULE FROM "
            "information_schema.REFERENTIAL_CONSTRAINTS rc "
            "WHERE rc.CONSTRAINT_SCHEMA = %s AND rc.REFERENCED_TABLE_NAME = 'users' "
            "AND rc.TABLE_NAME IN (%s,%s,%s,%s,%s)",
            (TEST_DB, *SPEC_TABLE_NAMES),
        )
        by_table = {r["TABLE_NAME"]: r["DELETE_RULE"] for r in rows}
        assert set(by_table) == set(SPEC_TABLE_NAMES)
        assert all(rule == "CASCADE" for rule in by_table.values())

    def test_no_redundant_bookmark_user_index(self, fx33_env):
        """RV14-7 实测：user_bookmarks 无 idx_user_bookmarks_user（唯一键
        最左前缀已覆盖 user_id 查询面）。"""
        rows = _q(
            "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'user_bookmarks'",
            (TEST_DB,),
        )
        names = {r["INDEX_NAME"] for r in rows}
        assert "idx_user_bookmarks_user" not in names
        assert "uq_user_bookmarks" in names


# ============================================
# RV14-7：_check_opt_text 空白串归一 None（单口径）
# ============================================

class TestOptTextNormalization:
    def test_empty_and_blank_normalize_to_none(self):
        reject = object()
        assert _check_opt_text(None, 200, reject) is None
        assert _check_opt_text("", 200, reject) is None
        assert _check_opt_text("   ", 200, reject) is None
        assert _check_opt_text("\u3000\t\n", 200, reject) is None

    def test_valid_text_stays_verbatim(self):
        reject = object()
        assert _check_opt_text(" x ", 200, reject) == " x "  # 原样存（不替用户清洗）
        assert _check_opt_text("好义位", 200, reject) == "好义位"

    def test_invalid_types_and_overlong_rejected(self):
        reject = object()
        assert _check_opt_text(42, 200, reject) is reject
        assert _check_opt_text(["t"], 200, reject) is reject
        assert _check_opt_text("t" * 201, 200, reject) is reject

    def test_bookmark_upsert_normalizes_blank_title_note(self, monkeypatch):
        """收藏标题/备注空白串入库前归一 NULL（与 DDL「NULL=未命名」单口径）。"""
        from src import user_context_db as ucdb

        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)
        captured = {}

        class _FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                captured["params"] = params

        monkeypatch.setattr(ucdb, "get_db_cursor", lambda *a, **k: _FakeCursor())
        monkeypatch.setattr(ucdb, "current_user",
                            lambda: {"id": 101, "username": "u101"})
        assert ucdb.upsert_bookmark("sense", "42", title="   ", note="") is True
        assert captured["params"][3] is None   # title → NULL
        assert captured["params"][4] is None   # note → NULL


# ============================================
# RV14-5：长度闸＋归因（broadcast 10000 / user_context 50000）
# ============================================

class TestLengthGates:
    def test_broadcast_body_over_limit_rejected_with_reason(self):
        """正文 >10000 字符 → 拒绝体 reason=「正文超长」（先于任何 DB 访问，
        归因不再是「数据库不可用」的一揽子文案）。"""
        actor = {"id": 3, "username": "dict_a", "role": "viewer",
                 "roles": ["dict_admin"]}
        result = bdb.publish_broadcast(1, "标题", "字" * (bdb.MAX_BODY_LEN + 1),
                                       actor=actor)
        assert result["id"] is None
        assert "正文超长" in result["reason"]
        assert str(bdb.MAX_BODY_LEN) in result["reason"]

    def test_broadcast_body_at_limit_passes_validation(self, monkeypatch):
        """边界：恰 10000 字符过应用层闸（走到项目在册校验——打桩 DB 隔离）。"""
        actor = {"id": 3, "username": "dict_a", "role": "viewer",
                 "roles": ["dict_admin"]}
        # RV17-1 后在册闸前有连通探测（DB 访问是设计内行为）：桩给探活行，
        # 在册闸仍打桩空册 → 断言「过长度闸、被在册闸拒」
        class _ProbeOkCursor:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def execute(self, sql, params=None):
                pass
            def fetchone(self):
                return {"1": 1}
        monkeypatch.setattr(bdb, "get_db_cursor", lambda *a, **k: _ProbeOkCursor())
        monkeypatch.setattr("src.org_db.list_projects", lambda: [])
        result = bdb.publish_broadcast(1, "标题", "字" * bdb.MAX_BODY_LEN,
                                       actor=actor)
        assert result["id"] is None
        assert "不在册" in result["reason"]  # 过了长度闸，走到下一道闸

    def test_broadcast_rejection_reasons_are_distinct(self):
        """各拒绝路径 reason 可区分（页面逐因显示的依据）。"""
        actor = {"id": 3, "username": "dict_a", "role": "viewer",
                 "roles": ["dict_admin"]}
        reasons = {
            bdb.publish_broadcast(1, "", "正文", actor=actor)["reason"],
            bdb.publish_broadcast(1, "标题", "  ", actor=actor)["reason"],
            bdb.publish_broadcast(1, "x" * 201, "正文", actor=actor)["reason"],
            bdb.publish_broadcast(1, "标题", "字" * 10001, actor=actor)["reason"],
            bdb.publish_broadcast(0, "标题", "正文", actor=actor)["reason"],
        }
        assert len(reasons) == 5

    def test_broadcast_db_down_reason_mentions_database(self, monkeypatch):
        """库不可用 → reason 归因「数据库」（与业务拒绝原因分得开）。"""
        actor = {"id": 3, "username": "dict_a", "role": "viewer",
                 "roles": ["dict_admin"]}
        monkeypatch.setattr(bdb, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(pymysql_boom()))
        monkeypatch.setattr("src.org_db.list_projects", lambda: [{"id": 1}])
        result = bdb.publish_broadcast(1, "标题", "正文", actor=actor)
        assert result["id"] is None
        assert "数据库" in result["reason"]

    def test_kv_value_over_50000_rejected_before_db(self, monkeypatch):
        """KV 值 >50000 字符 → False，入参校验先于 DB 访问（零触库）。"""
        from src import user_context_db as ucdb

        def _boom(*args, **kwargs):
            raise AssertionError("超长入参应在触库前被拒（RV14-5）")

        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)
        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)
        monkeypatch.setattr(ucdb, "current_user",
                            lambda: {"id": 101, "username": "u101"})
        assert upsert_profile("k", "字" * (MAX_KV_VALUE_LEN + 1)) is False
        assert upsert_state("k", "字" * (MAX_KV_VALUE_LEN + 1)) is False

    def test_note_over_50000_rejected_before_db(self, monkeypatch):
        """笔记正文 >50000 字符 → False，零触库；边界 50000 过闸（桩接收）。"""
        from src import user_context_db as ucdb

        def _boom(*args, **kwargs):
            raise AssertionError("超长入参应在触库前被拒（RV14-5）")

        monkeypatch.setattr(ucdb, "_TABLES_ENSURED", True)
        monkeypatch.setattr(ucdb, "get_db_cursor", _boom)
        monkeypatch.setattr(ucdb, "current_user",
                            lambda: {"id": 101, "username": "u101"})
        assert upsert_note(42, "字" * (MAX_NOTE_LEN + 1)) is False

        captured = {}

        class _FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                captured["params"] = params

        monkeypatch.setattr(ucdb, "get_db_cursor", lambda *a, **k: _FakeCursor())
        assert upsert_note(42, "字" * MAX_NOTE_LEN) is True
        assert captured["params"][2] == "字" * MAX_NOTE_LEN

    def test_page_shows_real_reason_from_result_body(self, monkeypatch):
        """页面消费结果体 reason（RV14-5）：st.warning 文案 = 数据层真实原因。"""
        monkeypatch.setattr(dp, "st", _BroadcastStubSt(submit=True))
        monkeypatch.setattr(dp.broadcast_db, "list_broadcasts", lambda pid, limit=20: [])
        monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: None)
        monkeypatch.setattr(
            dp.broadcast_db, "publish_broadcast",
            lambda *a, **k: {"id": None, "reason": "正文超长（>10000 字符，上限）"})
        dp._render_broadcast_section(3, dict(DICT_ADMIN))
        stub = dp.st
        assert any(k == "warning" and "广播未发布" in t and "正文超长" in t
                   for k, t in stub.messages)

    def test_page_unknown_reason_fallback(self, monkeypatch):
        """结果体缺 reason / 非 dict 旧形态（防御）→ 未知原因灰注，不崩段。"""
        monkeypatch.setattr(dp, "st", _BroadcastStubSt(submit=True))
        monkeypatch.setattr(dp.broadcast_db, "list_broadcasts", lambda pid, limit=20: [])
        monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: None)
        monkeypatch.setattr(dp.broadcast_db, "publish_broadcast", lambda *a, **k: None)
        dp._render_broadcast_section(3, dict(DICT_ADMIN))
        stub = dp.st
        assert any(k == "warning" and "广播未发布" in t and "未知原因" in t
                   for k, t in stub.messages)


# ============================================
# RV15-1：落地分支 1 按可裁决角色过滤
# ============================================

class TestLandingAdjudicatorFilter:
    """RV15-1：分支 1 = 可裁决（_can_adjudicate_inbox 同源口径）且其可裁决域
    pending>0；无裁决权角色顺序到分支 2/3。pending_inbox_count 全局计数不动。"""

    @pytest.mark.parametrize("user", [DICT_ADMIN, REVIEWER, LEGACY_ADMIN],
                             ids=["dict_admin", "reviewer", "legacy_admin"])
    def test_adjudicator_with_pending_lands_ai_hub(self, user, monkeypatch):
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
        assert app_module._landing_page_for(user) == "ai_hub"

    @pytest.mark.parametrize("user", [VIEWER, ANNOTATOR, EDITOR, SYS_ADMIN],
                             ids=["viewer", "annotator", "editor", "sys_admin"])
    def test_non_adjudicator_with_pending_skips_ai_hub(self, user, monkeypatch):
        """无裁决权角色：有全局 pending 也不落 ai_hub（顺序到分支 3 搜索）。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
        assert app_module._landing_page_for(user) == "search"

    def test_non_adjudicator_with_pending_falls_to_resume(self, monkeypatch):
        """RV15-1 验收面：viewer 登录且有全局 pending → 落**续接点**而非 ai_hub。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
        app_module.set_resume_page_loader(lambda uid: "cluster")
        assert app_module._landing_page_for(VIEWER) == "cluster"

    def test_adjudicator_without_pending_skips_ai_hub(self, monkeypatch):
        """可裁决但其可裁决域 pending=0 → 非分支 1（顺序到续接点/搜索）。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        app_module.set_resume_page_loader(lambda uid: "cluster")
        assert app_module._landing_page_for(DICT_ADMIN) == "cluster"


# ============================================
# RV15-3：「继续：…」规范面落位（分支 2 flash）
# ============================================

class TestResumeFlash:
    def test_branch2_flash_with_page_label(self, monkeypatch):
        """分支 2 命中 → flash「已回到上次工作位置：{页名}」（ui_kit 队列在场）。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        app_module.set_resume_page_loader(lambda uid: "cluster")
        assert app_module._landing_page_for(DICT_ADMIN) == "cluster"
        queue_val = _pop_flash_queue()
        assert len(queue_val) == 1
        assert queue_val[0]["message"] == \
            f"已回到上次工作位置：{page_label('cluster')}"

    def test_branch1_no_flash(self, monkeypatch):
        """分支 1（有待办）命中 → 不 flash（「继续」文案只归属续接点分支）。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
        app_module.set_resume_page_loader(lambda uid: "cluster")
        assert app_module._landing_page_for(DICT_ADMIN) == "ai_hub"
        assert _pop_flash_queue() == []

    def test_branch3_first_login_no_flash(self, monkeypatch):
        """分支 3（首次登录，无待办无续接点）→ 不 flash。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        app_module.set_resume_page_loader(lambda uid: None)
        assert app_module._landing_page_for(DICT_ADMIN) == "search"
        assert _pop_flash_queue() == []

    def test_branch3_after_hidden_resume_no_flash(self, monkeypatch):
        """续接点指向不可见页（视同未命中走分支 3）→ 不 flash。"""
        monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
        app_module.set_resume_page_loader(lambda uid: "dict_admin")
        assert app_module._landing_page_for(VIEWER) == "search"
        assert _pop_flash_queue() == []


# ============================================
# RV15-2：广播表单按项目作用域化 ＋ 发布目标 caption
# ============================================

class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _BroadcastStubSt:
    """st 假体（广播段渲染面）：记录控件 key 与输出调用。"""

    def __init__(self, submit=False):
        self.submit = submit
        self.messages = []       # (kind, text)
        self.keys = []           # (控件族, key)

    def form(self, *args, **kwargs):
        # st.form 的首位参数即 key（源码按位置传；text_input 等按 key= 传）
        self.keys.append(("form", kwargs.get("key")
                          or (args[0] if args else None)))
        return _Ctx()

    def text_input(self, *args, **kwargs):
        self.keys.append(("text_input", kwargs.get("key")))
        return "标题X"

    def text_area(self, *args, **kwargs):
        self.keys.append(("text_area", kwargs.get("key")))
        return "正文Y"

    def form_submit_button(self, *args, **kwargs):
        return self.submit

    def markdown(self, *args, **kwargs):
        self.messages.append(("markdown", args[0] if args else ""))

    def caption(self, *args, **kwargs):
        self.messages.append(("caption", args[0] if args else ""))

    def info(self, *args, **kwargs):
        self.messages.append(("info", args[0] if args else ""))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args[0] if args else ""))

    def success(self, *args, **kwargs):
        self.messages.append(("success", args[0] if args else ""))

    def error(self, *args, **kwargs):
        self.messages.append(("error", args[0] if args else ""))

    def divider(self, *args, **kwargs):
        pass

    def rerun(self):
        self.messages.append(("rerun", ""))


def _patch_broadcast_section(monkeypatch, stub, publish="unset"):
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.broadcast_db, "list_broadcasts",
                        lambda project_id, limit=20: [])
    if publish != "unset":
        monkeypatch.setattr(dp.broadcast_db, "publish_broadcast", publish)


class TestScopedBroadcastForm:
    def test_form_keys_scoped_by_project(self, monkeypatch):
        """form 三键按项目作用域化：key 以 project_id 结尾（切项目键不同，
        会话 widget 状态不残留上一项目的陈旧载荷）。"""
        stub = _BroadcastStubSt()
        _patch_broadcast_section(monkeypatch, stub)
        dp._render_broadcast_section(3, dict(DICT_ADMIN))
        assert stub.keys == [
            ("form", "dict_admin_broadcast_form_3"),
            ("text_input", "dict_admin_bc_title_3"),
            ("text_area", "dict_admin_bc_body_3"),
        ]

    def test_different_projects_different_keys(self, monkeypatch):
        stub = _BroadcastStubSt()
        _patch_broadcast_section(monkeypatch, stub)
        dp._render_broadcast_section(3, dict(DICT_ADMIN))
        keys_p3 = dict(stub.keys)
        stub2 = _BroadcastStubSt()
        _patch_broadcast_section(monkeypatch, stub2)
        dp._render_broadcast_section(4, dict(DICT_ADMIN))
        keys_p4 = dict(stub2.keys)
        assert keys_p3["text_input"] != keys_p4["text_input"]
        assert keys_p3["text_area"] != keys_p4["text_area"]
        assert keys_p3["form"] != keys_p4["form"]

    def test_caption_echoes_publish_target_with_project_name(self, monkeypatch):
        """段头 caption 回显「发布目标：{项目名}」（调用方从项目清单带出）。"""
        stub = _BroadcastStubSt()
        _patch_broadcast_section(monkeypatch, stub)
        dp._render_broadcast_section(3, dict(DICT_ADMIN),
                                     project_name="现汉七")
        captions = [t for k, t in stub.messages if k == "caption"]
        assert any("发布目标：现汉七" in c and "id 3" in c for c in captions)

    def test_caption_falls_back_to_project_id(self, monkeypatch):
        stub = _BroadcastStubSt()
        _patch_broadcast_section(monkeypatch, stub)
        dp._render_broadcast_section(3, dict(DICT_ADMIN))
        captions = [t for k, t in stub.messages if k == "caption"]
        assert any("发布目标：项目 #3" in c for c in captions)

    def test_source_registers_scoped_keys(self):
        """源码契约：作用域化键在源（供检修/检索；fx30 旧字面量键断言随之退役）。"""
        src = inspect.getsource(dp._render_broadcast_section)
        assert 'key=f"dict_admin_bc_title_{project_id}"' in src
        assert 'key=f"dict_admin_bc_body_{project_id}"' in src
        assert 'f"dict_admin_broadcast_form_{project_id}"' in src
        assert 'key="dict_admin_bc_title"' not in src


# ============================================
# RV13-6：_is_dict_admin 收口 effective_six_roles
# ============================================

class TestIsDictAdminConsolidation:
    @pytest.mark.parametrize("user,expected", [
        ({"id": 1, "role": "admin"}, True),                    # legacy 两位一体
        ({"id": 1, "role": "admin", "roles": []}, True),
        ({"id": 2, "role": "viewer", "roles": ["dict_admin"]}, True),
        ({"id": 2, "role": "reviewer",
          "roles": ("reviewer", "dict_admin")}, True),
        ({"id": 2, "roles": {"dict_admin"}}, True),
        ({"id": 3, "role": "reviewer"}, False),
        ({"id": 3, "role": "viewer", "roles": ["viewer", "annotator"]}, False),
        ({"id": 3, "roles": ["sys_admin"]}, False),            # 仅平台管理员不放行
        ({"id": 3}, False),
        ({"id": 4, "roles": "dict_admin"}, False),             # 字符串非序列
        ({"id": 4, "roles": ["DICT_ADMIN"]}, False),           # 大小写不宽容
        ({"id": 4, "role": "Admin"}, False),
        ({"id": 4, "roles": None}, False),
        (None, False),
        ({}, False),
        ("admin", False),
        (42, False),
    ])
    def test_semantics_preserved(self, user, expected):
        assert dp._is_dict_admin(user) is expected

    def test_uses_effective_six_roles_single_implementation(self):
        """源码契约：判定走 effective_six_roles 单一实现，docstring 无「过渡期」。"""
        src = inspect.getsource(dp._is_dict_admin)
        assert "effective_six_roles" in src
        assert "过渡期" not in src
