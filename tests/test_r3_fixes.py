"""批次 R3 修复回归测试（9 项 findings 修复面 —— Agent FX，批次 12 前）。

覆盖（findings 复现口径见各测试 docstring；修复前后对照见交付报告）：
  R3-1  rollback_batch 混用仲裁 —— 伴生表已有持久化事件时：显式空清单拒、
        显式非空但与持久化集不同拒（防架空）、仅逐事件一致放行；
        无持久化记录现状不变（含「损坏日志视同无记录」口径）。
  R3-2  persist_revert_log 批次状态守卫 —— rolled_back 批次拒补写
        （「已回滚批次不可补写日志」）；running/finished 可。
  R3-3  media_db.unbind_for_anchor（锚级解绑，返回删除数）＋
        lexical_db.remove_example 删除例证前自动摘绑（孤儿绑定不再依赖
        页面手工摘除）。
  R3-4  审计留痕列：media_bindings.reviewed_by/reviewed_at（R3-4a，流转
        写入操作人 username + NOW()）；export_batches.published_by/
        published_at（R3-4b，published 流转写入；revoked 不写）。
  R3-5  users.created_by 建号留痕 —— create_user keyword 缺省 None 兼容
        既有调用；非 None 时落 users.created_by 且 user_roles.granted_by
        同取该值；非法 created_by 拒绝。
  R3-6  export_batches.operator_id 不落 0 —— actor 无有效 id 落 NULL
        （审计「未知操作人」），有效 id 落正整数。
  R3-7/R3-8  纯文档口径：org_db / writing_db 模块 docstring 末尾
        「已知口径（R3-7/R3-8）」段在场（不修码，照转述）。
  R3-9  导入回滚 updated_at 还原（update 事件 old_values 收录导入前旧值，
        rollback 显式 SET 优先于 ON UPDATE CURRENT_TIMESTAMP）＋
        definitions.import_voided 作废标记（幂等 ALTER；INSERT 落 0；
        回滚 insert 事件置 1；entry_assembly 头块查询与 export_center
        definitions 导出排除作废行）。

两层结构（与 test_users_db / test_dict_admin_db 既有约定一致）：
  * 纯函数/签名/常量/docstring 断言不碰数据库 —— 本地与 CI 全跑；
  * 集成层依赖真实 MySQL —— 连不上或账号无建库权限就 skip（类级 skipif +
    fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_users_test（monkeypatch db.MYSQL_DATABASE，
连接池按键区分 host/port/db/user），每个测试重建，跑完 DROP。库内最小
definitions 表**不带 import_voided**（由 ensure_import_voided_column 的
幂等 ALTER 迁移补齐 —— 迁移路径本身被本文件实测）。
"""

import inspect
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.dict_admin_db import (  # noqa: E402
    _same_revert_events,
    define_field,
    ensure_dict_admin_tables,
    finish_batch,
    persist_revert_log,
    rollback_batch,
    start_batch,
)
from src.export_center import (  # noqa: E402
    EXPORT_BATCHES_AUDIT_COLUMNS,
    _dump_table_csv,
    build_content_snapshot,
    ensure_export_tables,
)
from src.import_engine import (  # noqa: E402
    IMPORT_VOIDED_COLUMN_SQL,
    _ts_text,
    ensure_import_voided_column,
    has_import_voided_column,
    run_import,
)
from src.lexical_db import ensure_lexical_tables, remove_example  # noqa: E402
from src.media_db import (  # noqa: E402
    MEDIA_BINDINGS_AUDIT_COLUMNS,
    bind_asset,
    ensure_media_tables,
    list_assets_for_anchor,
    register_asset,
    unbind_for_anchor,
)
from src.users_db import create_user, ensure_user_tables  # noqa: E402

TEST_DB = "web_word_users_test"  # 与 users / dict_admin 系测试共用（授权覆盖）

MAPPING = {"词目": "verb", "中文释义": "chinese_ndef"}

# 最小 definitions 表：与真实库被测列同构（含 entry_assembly 头块读取的
# en_ndef/definition_source/source_rank）；**刻意不带 import_voided** ——
# ensure_import_voided_column 的幂等 ALTER 迁移路径由 fixture 实测。
_DEFINITIONS_DDL = """CREATE TABLE IF NOT EXISTS definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL UNIQUE,
    chinese_ndef TEXT NOT NULL,
    semantic_table JSON NOT NULL,
    phonetic VARCHAR(64) DEFAULT NULL,
    en_ndef TEXT,
    definition_source VARCHAR(32) DEFAULT NULL,
    source_rank TINYINT DEFAULT NULL,
    cluster_id INT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 纯层：签名 / 常量 / docstring / 纯函数（无数据库）
# ============================================

class TestR3SignaturesAndConstants:
    """修复面签名与常量（keyword 缺省保证既有调用兼容）。"""

    def test_create_user_has_created_by_keyword_default_none(self):
        """R3-5：create_user 增 keyword created_by=None（缺省不破坏既有调用）。"""
        sig = inspect.signature(create_user)
        assert "created_by" in sig.parameters
        assert sig.parameters["created_by"].default is None
        assert sig.parameters["created_by"].kind == inspect.Parameter.KEYWORD_ONLY \
            or sig.parameters["created_by"].default is not inspect.Parameter.empty

    def test_advance_status_helpers_have_audit_keyword(self):
        """R3-4a/4b：流转辅助带 reviewed_by / published_by keyword（缺省 None）。"""
        import src.dict_admin_pages as dp

        assert inspect.signature(dp._advance_binding_status).parameters[
            "reviewed_by"].default is None
        assert inspect.signature(dp._advance_export_status).parameters[
            "published_by"].default is None

    def test_unbind_for_anchor_signature(self):
        """R3-3：media_db.unbind_for_anchor(anchor_type, anchor_id) 在场。"""
        sig = inspect.signature(unbind_for_anchor)
        assert list(sig.parameters) == ["anchor_type", "anchor_id"]

    def test_audit_column_constants(self):
        """R3-4a/4b/9c：迁移常量列名与 DDL 形态（幂等 ALTER 的信息源）。"""
        assert [c for c, _ in MEDIA_BINDINGS_AUDIT_COLUMNS] == [
            "reviewed_by", "reviewed_at"]
        assert [c for c, _ in EXPORT_BATCHES_AUDIT_COLUMNS] == [
            "published_by", "published_at"]
        assert "ADD COLUMN import_voided TINYINT(1) NOT NULL DEFAULT 0" \
            in IMPORT_VOIDED_COLUMN_SQL
        assert "ALTER TABLE definitions" in IMPORT_VOIDED_COLUMN_SQL

    def test_unbind_for_anchor_validates_before_db(self):
        """R3-3：非法锚类型/锚 id 在触库前拒绝返回 0（无库环境也可跑）。"""
        assert unbind_for_anchor("lemma", 1) == 0      # 锚类型白名单外
        assert unbind_for_anchor("", 1) == 0
        assert unbind_for_anchor("example", 0) == 0    # 锚 id 须正整数
        assert unbind_for_anchor("example", -3) == 0
        assert unbind_for_anchor("example", "x") == 0

    def test_ts_text(self):
        """R3-9a：TIMESTAMP 值 → 'YYYY-MM-DD HH:MM:SS' 串（JSON 可序列化）。"""
        assert _ts_text(datetime(2020, 1, 2, 3, 4, 5)) == "2020-01-02 03:04:05"
        assert _ts_text("2020-01-02 03:04:05") == "2020-01-02 03:04:05"
        assert _ts_text(None) is None
        assert _ts_text(42) is None
        assert _ts_text("") is None

    def test_same_revert_events(self):
        """R3-1：逐事件一致判定 —— dict 键序不敏感；条数/值不同即不一致。"""
        persisted = [{"action": "insert", "table": "definitions", "row_id": 3}]
        assert _same_revert_events(persisted, [
            {"row_id": 3, "table": "definitions", "action": "insert"}]) is True
        assert _same_revert_events(persisted, persisted) is True
        assert _same_revert_events(persisted, []) is False                # 条数不同
        assert _same_revert_events(persisted, persisted + [{}]) is False
        assert _same_revert_events(persisted, [
            {"action": "insert", "table": "definitions", "row_id": 4}]) is False
        assert _same_revert_events(persisted, "不是清单") is False

    def test_docstrings_carry_new_contract(self):
        """R3-1/R3-2：函数 docstring 标注混用仲裁与已回滚守卫口径。"""
        import src.dict_admin_db as m

        assert "混用仲裁" in (m.rollback_batch.__doc__ or "")
        assert "已回滚批次不可补写日志" in (m.persist_revert_log.__doc__ or "")
        assert "updated_at" in (m.rollback_batch.__doc__ or "")  # R3-9a 口径在册


class TestR3KnownIssuesDocumented:
    """R3-7/R3-8：不修码，模块 docstring 末尾「已知口径」段照转述在场。"""

    def test_org_db_documents_r3_7(self):
        doc = __import__("src.org_db", fromlist=["__doc__"]).__doc__ or ""
        assert "已知口径（R3-7" in doc
        assert "assignments" in doc and "project_id" in doc
        assert "over-block" in doc                      # 全局 COUNT 连带挡移除
        assert "批次 12" in doc

    def test_writing_db_documents_r3_8(self):
        doc = __import__("src.writing_db", fromlist=["__doc__"]).__doc__ or ""
        assert "已知口径（R3-8" in doc
        assert "based_on" in doc                        # 跨作者续基无守卫无标记
        assert "批次 12" in doc


# ============================================
# 集成层：真实 MySQL（无环境则整类 skip）
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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 R3 修复集成测试")
class TestR3FixesIntegration:
    """9 项修复的真 MySQL 回归（独立测试库，每测试重建）。"""

    @pytest.fixture
    def r3db(self, monkeypatch):
        """建空测试库（R3 涉及的全部表）并指向它，结束 DROP。

        definitions 刻意不带 import_voided —— ensure_import_voided_column
        的幂等 ALTER 迁移在 fixture 内实测（返回 True 且列随后在位）。
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
                "COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 R3 修复集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)

        ensure_user_tables()
        ensure_dict_admin_tables()
        ensure_media_tables()
        ensure_lexical_tables()
        ensure_export_tables()
        with db.get_db_cursor() as cursor:
            cursor.execute(_DEFINITIONS_DDL)
        # R3-9c：幂等补列（fixture 库的 definitions 无此列 → 走 ALTER 分支）
        assert ensure_import_voided_column() is True
        assert has_import_voided_column() is True
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

    # --- 辅助（测试自控直写 SQL；表名白名单防拼错） ---

    _TABLES = ("users", "user_roles", "custom_fields", "custom_values",
               "import_batches", "import_revert_log", "definitions",
               "media_assets", "media_bindings", "sense_examples",
               "export_batches")

    def _q(self, sql, params=()):
        assert any(t in sql for t in self._TABLES) or "information_schema" in sql, sql
        with db.get_db_cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def _one(self, sql, params=()):
        rows = self._q(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql, params=()):
        assert any(t in sql for t in self._TABLES), sql
        with db.get_db_cursor() as cursor:
            cursor.execute(sql, params)

    def _column_present(self, table, column):
        row = self._one(
            """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND COLUMN_NAME = %s""",
            (table, column),
        )
        return int(row["n"] or 0) > 0

    def _finished_batch(self, domain="custom_values"):
        bid = start_batch(1, "f.xlsx", "ab" * 32, domain, {}, operator=1)
        assert bid > 0
        assert finish_batch(bid, 2, 2, 0) is True
        return bid

    def _text_field(self, code):
        fid = define_field(1, code, "语域", "word", "text", created_by=1)
        assert isinstance(fid, int) and fid > 0
        return fid

    def _seed_verb(self, verb, chinese_ndef):
        self._exec(
            "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
            "VALUES (%s, %s, '{}')",
            (verb, chinese_ndef),
        )

    # ============================================
    # R3-1：rollback_batch 混用仲裁
    # ============================================

    def test_r3_1_persisted_log_blocks_empty_explicit_list(self, r3db):
        """伴生表已有持久化事件 ＋ 显式空清单 → 拒（矛盾），状态不动、行不废。"""
        fid = self._text_field("reg1")
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        assert rollback_batch(bid, []) is False
        assert str(self._one(
            "SELECT status FROM import_batches WHERE id = %s", (bid,))["status"]
        ) == "finished"
        assert str(self._one(
            "SELECT status FROM custom_fields WHERE id = %s", (fid,))["status"]
        ) == "active"

    def test_r3_1_persisted_log_blocks_differing_explicit_list(self, r3db):
        """显式非空但与持久化集不同 → 拒（防架空持久化日志）。"""
        fid = self._text_field("reg2")
        fid2 = self._text_field("reg3")
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        assert rollback_batch(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid2},
        ]) is False
        assert str(self._one(
            "SELECT status FROM import_batches WHERE id = %s", (bid,))["status"]
        ) == "finished"
        # 两字段都未被回滚动作触碰
        for f in (fid, fid2):
            assert str(self._one(
                "SELECT status FROM custom_fields WHERE id = %s", (f,))["status"]
            ) == "active"

    def test_r3_1_identical_explicit_list_passes(self, r3db):
        """显式传参与持久化事件逐事件一致 → 放行（幂等重放同一份清单）。"""
        fid = self._text_field("reg4")
        bid = self._finished_batch()
        events = [{"action": "insert", "table": "custom_fields", "row_id": fid}]
        assert persist_revert_log(bid, events) is True
        assert rollback_batch(bid, events) is True
        assert str(self._one(
            "SELECT status FROM custom_fields WHERE id = %s", (fid,))["status"]
        ) == "deprecated"
        assert str(self._one(
            "SELECT status FROM import_batches WHERE id = %s", (bid,))["status"]
        ) == "rolled_back"

    def test_r3_1_no_persisted_record_explicit_still_works(self, r3db):
        """无持久化记录 → 显式传参现状不变（含空清单与非空清单）。"""
        fid = self._text_field("reg5")
        bid = self._finished_batch()
        assert rollback_batch(bid, []) is True          # 零变更批次只翻状态
        bid2 = self._finished_batch()
        assert rollback_batch(bid2, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        assert str(self._one(
            "SELECT status FROM custom_fields WHERE id = %s", (fid,))["status"]
        ) == "deprecated"

    def test_r3_1_corrupt_persisted_log_treated_as_absent(self, r3db):
        """持久化事件损坏读不回（非 dict JSON）→ 视同无记录：显式传参维持旧口径。"""
        bid = self._finished_batch()
        self._exec(
            "INSERT INTO import_revert_log (batch_id, seq, event) VALUES (%s, 1, %s)",
            (bid, "[1, 2]"),
        )
        assert rollback_batch(bid, []) is True          # 损坏 ≠ 持久化事件集在手
        assert str(self._one(
            "SELECT status FROM import_batches WHERE id = %s", (bid,))["status"]
        ) == "rolled_back"

    # ============================================
    # R3-2：persist_revert_log 批次状态守卫
    # ============================================

    def test_r3_2_rolled_back_batch_rejects_persist(self, r3db):
        """rolled_back 批次补写 → False（已回滚批次不可补写日志），零落库。"""
        fid = self._text_field("guard1")
        bid = self._finished_batch()
        assert rollback_batch(bid, []) is True          # 先合法回滚（无持久化）
        events = [{"action": "insert", "table": "custom_fields", "row_id": fid}]
        assert persist_revert_log(bid, events) is False
        rows = self._q("SELECT id FROM import_revert_log WHERE batch_id = %s", (bid,))
        assert not rows

    def test_r3_2_running_and_finished_batches_accept_persist(self, r3db):
        """running / finished 批次可补写（守卫只拦 rolled_back）；不存在批次拒。"""
        fid = self._text_field("guard2")
        running = start_batch(1, "r.xlsx", "cd" * 32, "custom_values", {}, operator=1)
        assert persist_revert_log(running, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        finished = self._finished_batch()
        assert persist_revert_log(finished, []) is True
        assert persist_revert_log(999999, []) is False  # 批次不存在（可读拒绝）

    # ============================================
    # R3-3：unbind_for_anchor ＋ remove_example 自动摘绑
    # ============================================

    def _make_asset(self, tmp_path, name="a.png"):
        path = tmp_path / name
        path.write_bytes(f"\x89PNG-r3-fixture-{name}".encode())  # 内容互异（sha256 去重）
        aid = register_asset(path, "image", "r3-test", "CC-BY-4.0（R3 测试）")
        assert aid > 0
        return aid

    def _open_batch(self, domain="custom_values"):
        """登记一个 running 批次（行数留给调用方按实际结果 finish）。"""
        bid = start_batch(1, "f.xlsx", "ab" * 32, domain, {}, operator=1)
        assert bid > 0
        return bid

    def test_r3_3_unbind_for_anchor_deletes_all_and_counts(self, r3db, tmp_path):
        """摘除锚上全部绑定返回删除数；他锚绑定不受影响；重复摘除返回 0。"""
        aid = self._make_asset(tmp_path)
        assert bind_asset(aid, "example", 11, "example_media") is True
        assert bind_asset(aid, "example", 11, "illustration") is True
        assert bind_asset(aid, "word", 5, "illustration") is True

        assert unbind_for_anchor("example", 11) == 2
        assert not self._q("SELECT id FROM media_bindings "
                           "WHERE anchor_type='example' AND anchor_id=11")
        assert len(self._q("SELECT id FROM media_bindings "
                           "WHERE anchor_type='word' AND anchor_id=5")) == 1
        assert unbind_for_anchor("example", 11) == 0    # 幂等：再摘返回 0

    def test_r3_3_remove_example_unbinds_media_first(self, r3db, tmp_path):
        """remove_example 删除例证前自动摘其全部绑定（孤儿绑定不再依赖页面）。"""
        aid = self._make_asset(tmp_path, "b.png")
        self._exec(
            "INSERT INTO sense_examples (sense_ref, content, source, status) "
            "VALUES ('motion:1:1', '例证文本', 'adapted', '候选')"
        )
        eid = int(self._one("SELECT id FROM sense_examples "
                            "WHERE content='例证文本'")["id"])
        assert bind_asset(aid, "example", eid, "example_media") is True
        assert len(self._q("SELECT id FROM media_bindings "
                           "WHERE anchor_type='example' AND anchor_id=%s",
                           (eid,))) == 1

        assert remove_example(eid) is True
        assert not self._q("SELECT id FROM sense_examples WHERE id=%s", (eid,))
        # 绑定随之消失（R3-3 自动摘除）
        assert not self._q("SELECT id FROM media_bindings "
                           "WHERE anchor_type='example' AND anchor_id=%s",
                           (eid,))

    # ============================================
    # R3-4a：media_bindings 审定留痕列
    # ============================================

    def test_r3_4a_ensure_migrates_audit_columns_idempotent(self, r3db):
        """ensure_media_tables 幂等补 reviewed_by/reviewed_at（重复调用不炸）。"""
        ensure_media_tables()
        ensure_media_tables()
        assert self._column_present("media_bindings", "reviewed_by") is True
        assert self._column_present("media_bindings", "reviewed_at") is True

    def test_r3_4a_advance_writes_reviewer_and_time(self, r3db, tmp_path):
        """流转写入 reviewed_by（操作人 username）/ reviewed_at（NOW()）；
        每步刷新；非法跳级拒；出参带两新列。"""
        import src.dict_admin_pages as dp

        aid = self._make_asset(tmp_path, "c.png")
        assert bind_asset(aid, "sense", 21, "illustration") is True
        bid = int(self._one(
            "SELECT id FROM media_bindings WHERE asset_id=%s", (aid,))["id"])

        assert dp._advance_binding_status(bid, "候选", "审定",
                                          reviewed_by="管理员甲") is True
        row = self._one("SELECT status, reviewed_by, reviewed_at "
                        "FROM media_bindings WHERE id=%s", (bid,))
        assert row["status"] == "审定"
        assert row["reviewed_by"] == "管理员甲"
        assert row["reviewed_at"] is not None

        # 下一步流转刷新留痕（列语义 = 把绑定推到当前态的人与时间）
        assert dp._advance_binding_status(bid, "审定", "发布",
                                          reviewed_by="管理员乙") is True
        row = self._one("SELECT status, reviewed_by FROM media_bindings "
                        "WHERE id=%s", (bid,))
        assert row["status"] == "发布"
        assert row["reviewed_by"] == "管理员乙"

        # 非单步对拒绝；不带 reviewed_by 的调用维持旧形态（不碰留痕列）
        assert dp._advance_binding_status(bid, "候选", "发布") is False
        aid2 = self._make_asset(tmp_path, "d.png")
        assert bind_asset(aid2, "sense", 22, "illustration") is True
        bid2 = int(self._one(
            "SELECT id FROM media_bindings WHERE asset_id=%s", (aid2,))["id"])
        assert dp._advance_binding_status(bid2, "候选", "审定") is True
        row2 = self._one("SELECT reviewed_by FROM media_bindings WHERE id=%s",
                         (bid2,))
        assert row2["reviewed_by"] is None

        # list_assets_for_anchor 出参带 reviewed_by / reviewed_at（R3-4a）
        assets = list_assets_for_anchor("sense", 21)
        assert len(assets) == 1
        assert assets[0]["reviewed_by"] == "管理员乙"
        assert assets[0]["reviewed_at"] is not None

    # ============================================
    # R3-4b：export_batches 出版留痕列
    # ============================================

    def _ready_export(self, file_path):
        self._exec(
            "INSERT INTO export_batches (operator_id, scope, file_path, "
            "rows_total, status) VALUES (1, 'content_snapshot', %s, 3, 'ready')",
            (file_path,),
        )
        return int(self._one(
            "SELECT id FROM export_batches WHERE file_path=%s", (file_path,))["id"])

    def test_r3_4b_ensure_migrates_published_columns_idempotent(self, r3db):
        """ensure_export_tables 幂等补 published_by/published_at（重复调用不炸）。"""
        ensure_export_tables()
        ensure_export_tables()
        assert self._column_present("export_batches", "published_by") is True
        assert self._column_present("export_batches", "published_at") is True

    def test_r3_4b_publish_flow_writes_publisher_revoked_leaves_null(self, r3db):
        """published 流转写入出版人/时间；revoked 流转不写（列语义即出版人）。"""
        import src.dict_admin_pages as dp

        pub_id = self._ready_export("data/exports/r3/pub.zip")
        rev_id = self._ready_export("data/exports/r3/rev.zip")

        assert dp._advance_export_status(pub_id, "ready", "published",
                                         published_by="出版甲") is True
        row = self._one("SELECT status, published_by, published_at "
                        "FROM export_batches WHERE id=%s", (pub_id,))
        assert row["status"] == "published"
        assert row["published_by"] == "出版甲"
        assert row["published_at"] is not None

        assert dp._advance_export_status(rev_id, "ready", "revoked") is True
        row = self._one("SELECT status, published_by, published_at "
                        "FROM export_batches WHERE id=%s", (rev_id,))
        assert row["status"] == "revoked"
        assert row["published_by"] is None
        assert row["published_at"] is None

        # 非法流转（终态再流转）拒绝；流转表外拒绝
        assert dp._advance_export_status(pub_id, "published", "revoked") is False
        assert dp._advance_export_status(rev_id, "ready", "published") is False

    # ============================================
    # R3-5：users.created_by 建号留痕
    # ============================================

    def test_r3_5_create_user_records_creator_and_granter(self, r3db):
        """created_by 落 users 列；默认 viewer 的 user_roles 行 granted_by 同取该值。"""
        creator = create_user("r3_creator", "pw123456", "建号管理员", "admin")
        assert isinstance(creator, int) and creator > 0
        u = create_user("r3_newbie", "pw123456", "被建号新人", "viewer",
                        created_by=creator)
        assert isinstance(u, int) and u > 0
        row = self._one("SELECT created_by FROM users WHERE id=%s", (u,))
        assert int(row["created_by"]) == creator
        granted = self._q("SELECT granted_by FROM user_roles "
                          "WHERE user_id=%s AND role='viewer'", (u,))
        assert [int(r["granted_by"]) for r in granted] == [creator]

    def test_r3_5_create_user_without_created_by_stays_null(self, r3db):
        """keyword 缺省：不传 created_by → users.created_by 与 granted_by 均 NULL
        （既有调用点零破坏）。"""
        u = create_user("r3_legacy", "pw123456", "旧口径新人", "viewer")
        assert isinstance(u, int) and u > 0
        assert self._one("SELECT created_by FROM users WHERE id=%s",
                         (u,))["created_by"] is None
        granted = self._q("SELECT granted_by FROM user_roles WHERE user_id=%s",
                          (u,))
        assert all(r["granted_by"] is None for r in granted)

    def test_r3_5_create_user_rejects_bad_created_by(self, r3db):
        """非法 created_by（0/负数/非整数/bool/不存在用户）一律 None，不建号。"""
        before = int(self._one("SELECT COUNT(*) AS n FROM users")["n"])
        for bad in (0, -1, "1", 1.5, True, 999999):
            assert create_user(f"r3_bad_{bad!r}", "pw123456", "不该存在",
                               "viewer", created_by=bad) is None, bad
        assert int(self._one("SELECT COUNT(*) AS n FROM users")["n"]) == before

    # ============================================
    # R3-6：export_batches.operator_id 不落 0
    # ============================================

    def test_r3_6_operator_id_records_actor_or_null_never_zero(self, r3db):
        """actor 带有效 id → 落正整数；actor 无 id → 落 NULL；绝不落 0。

        快照落盘走 data/exports（gitignored，与 test_export_center 同约定）——
        EXPORT_ROOT 须在仓库内（file_path 登记取相对路径），不 monkeypatch。"""
        actor = {"id": 7, "username": "chief", "role": "admin",
                 "roles": ["dict_admin", "sys_admin"]}
        r1 = build_content_snapshot(actor=actor, license_checked=False)
        assert r1["ok"] is True, r1.get("error")
        assert int(self._one("SELECT operator_id FROM export_batches "
                             "WHERE id=%s", (r1["batch_id"],))["operator_id"]) == 7

        no_id = {"username": "匿名", "role": "admin",
                 "roles": ["dict_admin", "sys_admin"]}
        r2 = build_content_snapshot(actor=no_id, license_checked=False)
        assert r2["ok"] is True, r2.get("error")
        assert self._one("SELECT operator_id FROM export_batches "
                         "WHERE id=%s", (r2["batch_id"],))["operator_id"] is None

        zero_rows = self._q("SELECT id FROM export_batches WHERE operator_id = 0")
        assert not zero_rows                            # R3-6：0 是不存在的假人

    # ============================================
    # R3-9：updated_at 还原 ＋ import_voided 作废标记
    # ============================================

    def test_r3_9_update_event_captures_and_rollback_restores_updated_at(self, r3db):
        """update 事件 old_values 收录导入前 updated_at；回滚后时间戳回到导入前。"""
        old_ts = "2020-01-02 03:04:05"
        self._seed_verb("walk", "旧释义")
        wid = int(self._one("SELECT id FROM definitions WHERE verb='walk'")["id"])
        self._exec("UPDATE definitions SET updated_at=%s WHERE id=%s",
                   (old_ts, wid))

        bid = self._open_batch("definitions")
        result = run_import([{"词目": "walk", "中文释义": "新释义"}], MAPPING, 1,
                            dry_run=False)
        assert result["ok"] is True and result["rows_ok"] == 1
        event = result["revert_log"][0]
        assert event["action"] == "update"
        assert event["old_values"]["chinese_ndef"] == "旧释义"
        assert event["old_values"]["updated_at"] == old_ts      # R3-9a 收录

        assert finish_batch(bid, result["rows_total"], result["rows_ok"],
                            result["rows_rejected"]) is True
        assert rollback_batch(bid, result["revert_log"]) is True
        row = self._one("SELECT chinese_ndef, updated_at FROM definitions "
                        "WHERE id=%s", (wid,))
        assert row["chinese_ndef"] == "旧释义"
        assert row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") == old_ts

    def test_r3_9_insert_voided_on_rollback_and_hidden_from_reads(self, r3db):
        """insert 回滚置 import_voided=1；装配头块与 definitions 导出排除作废行。"""
        self._seed_verb("stay", "既有行")                     # 正常行对照
        bid = self._open_batch("definitions")
        result = run_import([{"词目": "dash", "中文释义": "新词目"}], MAPPING, 1,
                            dry_run=False)
        assert result["ok"] is True and result["rows_ok"] == 1
        new_id = result["revert_log"][0]["row_id"]
        assert int(self._one("SELECT import_voided FROM definitions WHERE id=%s",
                             (new_id,))["import_voided"]) == 0  # 落行显式 0
        assert finish_batch(bid, result["rows_total"], result["rows_ok"],
                            result["rows_rejected"]) is True
        assert rollback_batch(bid, result["revert_log"]) is True
        assert int(self._one("SELECT import_voided FROM definitions WHERE id=%s",
                             (new_id,))["import_voided"]) == 1  # 回滚作废
        # 行仍留库（不物理 DELETE）
        assert self._one("SELECT verb FROM definitions WHERE id=%s",
                         (new_id,)) is not None

        # 读侧排除（R3-9c）：装配头块查不到作废行，正常行照常
        from src.entry_assembly import _fetch_definition_row

        assert _fetch_definition_row("dash") is None
        assert _fetch_definition_row("stay") is not None

        # 读侧排除（R3-9c）：definitions 导出不含作废行
        text, n = _dump_table_csv("definitions")
        assert "dash" not in text
        assert "stay" in text
        assert n == 1

    def test_r3_9_import_voided_migration_idempotent(self, r3db):
        """ensure_import_voided_column 幂等：重复调用返回 True 且不炸。"""
        assert ensure_import_voided_column() is True
        assert ensure_import_voided_column() is True
        assert self._column_present("definitions", "import_voided") is True
