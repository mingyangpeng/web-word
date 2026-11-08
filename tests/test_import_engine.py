"""导入业务写入映射引擎测试（src/import_engine.py，批次 5 Agent Q）。

两层结构，与 tests/test_users_db.py / test_dict_admin_db.py 既有约定一致：

  * 纯函数（_cell_str / validate_mapping / plan_import）与 run_import 的
    入口守卫（imported_by / 映射非法 / 零合法行早退）不碰数据库 —— 本地与 CI 全跑；
  * run_import 干跑零写库断言与真 MySQL 集成（UPSERT → revert_log →
    rollback_batch 恢复往返）依赖真实 MySQL —— 连不上或账号无建库权限就
    skip（类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_users_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，跑完
DROP。库名沿用 test_users_db / test_dict_admin_db 既成约定（授权覆盖）。
测试库另建**最小 definitions 表**（与真实 definitions 的被测列同构：
verb UNIQUE / chinese_ndef TEXT NOT NULL / semantic_table JSON NOT NULL /
phonetic / cluster_id / example_sentence），真实库的 word_clusters 外键等
结构差异不影响被测行为 —— 引擎对 definitions 的写域仅限白名单字段。

覆盖面（阶段1施工规范 §8 对 Agent Q 的要求 + 批次 R3 修复回归）：
  映射白名单拒绝（oald_senses 等）/ 缺键列/主载荷列 / 一字段多列歧义 /
  非法行原因（空键/超长/重复 verb）/ 干跑零写库 / UPSERT 更新 → revert_log
  含 old_values（**附 updated_at 导入前旧值，R3-9a**）→ rollback_batch 恢复
  → 行值还原（cluster_id 保留 + updated_at 回导入前时点）/
  insert → revert_log → 回滚置 **import_voided=1**（R3-9c 作废标记；行仍留库
  可审计，不物理 DELETE）/ 无变更不发事件 / 空音标跳过写入。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.dict_admin_db import (  # noqa: E402
    finish_batch,
    rollback_batch,
    start_batch,
)
from src.import_engine import (  # noqa: E402
    KEY_FIELD,
    MAX_CHINESE_NDEF_LEN,
    MAX_PHONETIC_LEN,
    MAX_VERB_LEN,
    TARGET_FIELDS,
    _cell_str,
    plan_import,
    run_import,
    validate_mapping,
)

TEST_DB = "web_word_users_test"  # 与 users / dict_admin 系测试共用（授权覆盖）

MAPPING = {"词目": "verb", "中文释义": "chinese_ndef", "音标": "phonetic"}

# 最小 definitions 表（被测列同构；无 word_clusters 外键 —— 引擎写域不含它）
DEFINITIONS_DDL = """CREATE TABLE IF NOT EXISTS definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL UNIQUE,
    chinese_ndef TEXT NOT NULL,
    semantic_table JSON NOT NULL,
    example_sentence TEXT,
    phonetic VARCHAR(64) DEFAULT NULL,
    cluster_id INT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 纯函数：单元格规整
# ============================================

class TestCellStr:
    """_cell_str：Excel/CSV 脏类型不直接进 SQL。"""

    def test_none_and_nan(self):
        assert _cell_str(None) == ""
        assert _cell_str(float("nan")) == ""

    def test_str_stripped(self):
        assert _cell_str("  run  ") == "run"
        assert _cell_str("") == ""

    def test_non_str_coerced(self):
        assert _cell_str(3) == "3"
        assert _cell_str(2.5) == "2.5"
        assert _cell_str(True) == "True"


# ============================================
# 纯函数：映射校验（白名单是第一道闸）
# ============================================

class TestValidateMapping:
    """validate_mapping：白名单 / 键列 / 主载荷列 / 一字段一列。"""

    def test_valid_mapping(self):
        norm, errors = validate_mapping(MAPPING)
        assert errors == []
        assert norm == MAPPING

    def test_target_fields_whitelist_contract(self):
        """白名单常量 = 词目键 + 中文释义 + 音标（页面映射下拉据此同源渲染）。"""
        assert TARGET_FIELDS == ("verb", "chinese_ndef", "phonetic")

    def test_empty_and_non_dict(self):
        for bad in (None, {}, "verb", [("a", "verb")]):
            norm, errors = validate_mapping(bad)
            assert norm is None
            assert errors

    def test_unknown_target_rejected(self):
        """白名单外目标字段（含 oald_senses 域）一律拒 —— 追加写入不支持。"""
        norm, errors = validate_mapping({"词目": "verb", "义项": "sense_id"})
        assert norm is None
        assert any("白名单" in e for e in errors)

    def test_oald_senses_target_rejected(self):
        norm, errors = validate_mapping({"词目": "verb", "释义": "oald_senses"})
        assert norm is None
        assert any("白名单" in e for e in errors)

    def test_missing_key_field(self):
        norm, errors = validate_mapping({"中文释义": "chinese_ndef"})
        assert norm is None
        assert any(KEY_FIELD in e for e in errors)

    def test_missing_payload_field(self):
        """phonetic-only 映射不支持：新词目行 chinese_ndef NOT NULL 无法成型。"""
        norm, errors = validate_mapping({"词目": "verb", "音标": "phonetic"})
        assert norm is None
        assert any("chinese_ndef" in e for e in errors)

    def test_duplicate_target_ambiguous(self):
        norm, errors = validate_mapping({"A": "verb", "B": "chinese_ndef", "C": "chinese_ndef"})
        assert norm is None
        assert any("一字段至多一列" in e for e in errors)

    def test_non_str_column(self):
        norm, errors = validate_mapping({3: "verb", "中文释义": "chinese_ndef"})
        assert norm is None
        assert errors

    def test_mapping_values_stripped(self):
        norm, errors = validate_mapping({" 词目 ": " verb ", "中文释义": "chinese_ndef"})
        assert errors == []
        assert norm == {"词目": "verb", "中文释义": "chinese_ndef"}


# ============================================
# 纯函数：plan_import（合法/非法行 + 原因）
# ============================================

class TestPlanImport:
    """plan_import：映射/白名单拒绝/非法行原因（纯函数口径）。"""

    ROWS = [
        {"词目": " run ", "中文释义": "奔跑", "音标": "/rʌn/", "多余列": "x"},
        {"词目": "jog", "中文释义": "慢跑"},
    ]

    def test_valid_plan(self):
        plan = plan_import(self.ROWS, MAPPING)
        assert plan["rows_total"] == 2
        assert plan["rows_ok"] == 2
        assert plan["rows_rejected"] == 0
        assert plan["mapping_errors"] == []
        assert plan["valid_rows"][0]["verb"] == "run"
        assert plan["valid_rows"][0]["values"] == {
            "verb": "run", "chinese_ndef": "奔跑", "phonetic": "/rʌn/",
        }
        assert plan["valid_rows"][1]["values"] == {
            "verb": "jog", "chinese_ndef": "慢跑", "phonetic": "",
        }  # 缺音标单元格 → 规整空串（写入端跳过空值，保留现值）

    def test_invalid_mapping_rejects_all_rows(self):
        plan = plan_import(self.ROWS, {"词目": "verb"})
        assert plan["rows_ok"] == 0
        assert plan["rows_rejected"] == 2
        assert plan["mapping_errors"]
        assert all("映射" in r["reason"] or "缺少" in r["reason"] for r in plan["rejected"])

    def test_empty_verb_rejected(self):
        plan = plan_import([{"词目": "  ", "中文释义": "x"}], MAPPING)
        assert plan["rows_rejected"] == 1
        assert "verb" in plan["rejected"][0]["reason"]

    def test_verb_too_long_rejected(self):
        plan = plan_import([{"词目": "v" * (MAX_VERB_LEN + 1), "中文释义": "x"}], MAPPING)
        assert plan["rows_rejected"] == 1
        assert "超长" in plan["rejected"][0]["reason"]

    def test_empty_chinese_ndef_rejected(self):
        plan = plan_import([{"词目": "run", "中文释义": ""}], MAPPING)
        assert plan["rows_rejected"] == 1
        assert "chinese_ndef" in plan["rejected"][0]["reason"]

    def test_chinese_ndef_too_long_rejected(self):
        plan = plan_import([{"词目": "run", "中文释义": "长" * (MAX_CHINESE_NDEF_LEN + 1)}], MAPPING)
        assert plan["rows_rejected"] == 1
        assert "chinese_ndef 超长" in plan["rejected"][0]["reason"]

    def test_phonetic_empty_allowed_but_too_long_rejected(self):
        """空音标合法（执行时跳过写入）；超长按列宽 VARCHAR(64) 拒。"""
        ok = plan_import([{"词目": "run", "中文释义": "奔跑", "音标": ""}], MAPPING)
        assert ok["rows_ok"] == 1
        assert ok["valid_rows"][0]["values"]["phonetic"] == ""
        bad = plan_import(
            [{"词目": "run", "中文释义": "奔跑", "音标": "p" * (MAX_PHONETIC_LEN + 1)}],
            MAPPING,
        )
        assert bad["rows_rejected"] == 1
        assert "phonetic" in bad["rejected"][0]["reason"]

    def test_duplicate_verb_rows(self):
        rows = [
            {"词目": "run", "中文释义": "一"},
            {"词目": "run", "中文释义": "二"},
        ]
        plan = plan_import(rows, MAPPING)
        assert plan["rows_ok"] == 1
        assert plan["rows_rejected"] == 1
        assert "重复" in plan["rejected"][0]["reason"]

    def test_rejected_row_verb_does_not_block_later_valid_row(self):
        """R2-4（docstring 对齐实测行为）：被拒行的 verb 不占去重坑 ——
        去重坑只在**通过全部校验的合法行**上登记，同名后续合法行可被接受
        （最终以 DB UNIQUE(verb) 兜底，run_import 执行期命中既有行走 UPDATE）。"""
        rows = [
            {"词目": "run", "中文释义": ""},      # 拒：释义为空（不占坑）
            {"词目": "run", "中文释义": "奔跑"},  # 同名合法行：接受
        ]
        plan = plan_import(rows, MAPPING)
        assert plan["rows_ok"] == 1
        assert plan["rows_rejected"] == 1
        assert plan["rejected"][0]["row_index"] == 0
        assert plan["valid_rows"][0]["row_index"] == 1
        assert plan["valid_rows"][0]["verb"] == "run"

    def test_duplicate_verb_docstring_aligned(self):
        """R2-4：plan_import docstring 明示去重口径（锁定，防回漂）。"""
        doc = plan_import.__doc__ or ""
        assert "不占去重坑" in doc
        assert "UNIQUE(verb)" in doc

    def test_non_dict_row_rejected(self):
        plan = plan_import(["not-a-dict"], MAPPING)
        assert plan["rows_rejected"] == 1
        assert "行格式非法" in plan["rejected"][0]["reason"]

    def test_rows_not_list(self):
        plan = plan_import("rows", MAPPING)
        assert plan["rows_ok"] == 0
        assert any("list[dict]" in e for e in plan["mapping_errors"])

    def test_nan_cell_treated_empty(self):
        plan = plan_import([{"词目": "run", "中文释义": float("nan")}], MAPPING)
        assert plan["rows_rejected"] == 1
        assert "chinese_ndef" in plan["rejected"][0]["reason"]


# ============================================
# run_import 入口守卫（不碰数据库）
# ============================================

class TestRunImportGuards:
    """imported_by / 映射非法 / 零合法行早退 —— 均发生在触库之前。"""

    def test_operator_required(self):
        for bad in (None, 0, -1, "1", 1.0, True):
            result = run_import([], MAPPING, bad, dry_run=True)
            assert result["ok"] is False
            assert "imported_by" in result["error"]
            assert result["rows_ok"] == 0
            assert result["revert_log"] == []

    def test_invalid_mapping_fatal_before_db(self):
        result = run_import([{"A": "x"}], {"A": "sense_id"}, 1, dry_run=False)
        assert result["ok"] is False
        assert result["rows_rejected"] == 1
        assert result["mapping_errors"]
        assert result["revert_log"] == []

    def test_all_rows_invalid_early_return(self):
        """零合法行：不触库直接返回计划口径（空 revert_log / 空 preview）。"""
        rows = [{"词目": "", "中文释义": "x"}]
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["ok"] is True
        assert result["rows_ok"] == 0
        assert result["rows_rejected"] == 1
        assert result["revert_log"] == []
        assert result["preview"] == []

    def test_dry_run_is_default(self):
        """不传 dry_run 时默认干跑（结果标记 dry_run=True；验收④零写库口径）。"""
        result = run_import([], MAPPING, 1)
        assert result["dry_run"] is True


# ============================================
# 真 MySQL 集成（干跑零写库 + UPSERT/revert_log/rollback 往返）
# ============================================

def _mysql_reachable() -> bool:
    import pymysql
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过导入引擎集成测试")
class TestImportEngineIntegration:
    """干跑零写库 / UPSERT → revert_log → rollback_batch 恢复往返（测试库）。"""

    @pytest.fixture
    def engine_db(self, monkeypatch):
        """建空测试库（dict_admin 三表 + 最小 definitions）并指向它，结束 DROP。"""
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
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过导入引擎集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)

        from src.dict_admin_db import ensure_dict_admin_tables

        ensure_dict_admin_tables()
        with db.get_db_cursor() as cursor:
            cursor.execute(DEFINITIONS_DDL)
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

    def _seed(self, verb, chinese_ndef, phonetic=None, cluster_id=None, example=None):
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions "
                "(verb, chinese_ndef, semantic_table, phonetic, cluster_id, example_sentence) "
                "VALUES (%s, %s, '{}', %s, %s, %s)",
                (verb, chinese_ndef, phonetic, cluster_id, example),
            )
            return int(cursor.lastrowid)

    def _row_of(self, verb):
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, verb, chinese_ndef, phonetic, cluster_id, "
                "example_sentence, updated_at "
                "FROM definitions WHERE verb = %s",
                (verb,),
            )
            return cursor.fetchone()

    def _count(self):
        with db.get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM definitions")
            return int(cursor.fetchone()["n"])

    # --- 干跑：零写库 ---

    def test_dry_run_zero_writes(self, engine_db):
        """干跑只读库：行数不变、现值不变、revert_log 恒空、预览给出 diff。"""
        self._seed("run", "旧释义", phonetic="/old/", cluster_id=7)
        rows = [
            {"词目": "run", "中文释义": "新释义", "音标": "/rʌn/"},
            {"词目": "dash", "中文释义": "猛冲", "音标": ""},
        ]
        before = self._row_of("run")
        result = run_import(rows, MAPPING, 1, dry_run=True)

        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["rows_ok"] == 2
        assert result["rows_rejected"] == 0
        assert result["revert_log"] == []          # 干跑零写库 → 无回滚事件
        assert len(result["preview"]) == 2

        update_entry = next(p for p in result["preview"] if p["verb"] == "run")
        assert update_entry["action"] == "update"
        assert update_entry["row_id"] == before["id"]
        assert update_entry["changes"]["chinese_ndef"] == {"old": "旧释义", "new": "新释义"}
        assert update_entry["changes"]["phonetic"] == {"old": "/old/", "new": "/rʌn/"}
        insert_entry = next(p for p in result["preview"] if p["verb"] == "dash")
        assert insert_entry["action"] == "insert"
        assert insert_entry["row_id"] is None
        assert insert_entry["changes"]["chinese_ndef"] == {"old": None, "new": "猛冲"}

        # 零写库断言：行数与现值完全不变
        assert self._count() == 1
        after = self._row_of("run")
        assert after["chinese_ndef"] == before["chinese_ndef"]
        assert after["phonetic"] == before["phonetic"]

    def test_dry_run_none_action_for_identical_values(self, engine_db):
        """干跑：值完全相同的行 → action=none，零变更预览。"""
        self._seed("run", "奔跑")
        result = run_import(
            [{"词目": "run", "中文释义": "奔跑"}], MAPPING, 1, dry_run=True,
        )
        assert result["ok"] is True
        assert result["preview"][0]["action"] == "none"
        assert result["preview"][0]["changes"] == {}

    # --- 实写：update → revert_log → rollback 恢复 ---

    def test_update_revert_log_and_rollback_restores_values(self, engine_db):
        """UPSERT 更新：revert_log 含 old_values（含 updated_at 旧值，R3-9a）→
        rollback_batch 恢复 → 行值与时间戳还原到导入前。"""
        row_id = self._seed("run", "旧释义", phonetic="/old/", cluster_id=7,
                            example="an old example")
        # 固定导入前时间戳（秒级分辨率的 CURRENT_TIMESTAMP 不足以证明还原）：
        # 显式把 updated_at 拨回过去，导入覆盖必然顶掉它，回滚应还原此值
        OLD_TS = "2020-01-02 03:04:05"
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE definitions SET updated_at = %s WHERE id = %s",
                (OLD_TS, row_id),
            )
        rows = [{"词目": "run", "中文释义": "新释义", "音标": "/rʌn/"}]

        batch_id = start_batch(1, "verbs.xlsx", "a" * 64, "definitions",
                               {"column_field_mapping": MAPPING}, 1)
        assert batch_id > 0
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["ok"] is True
        assert result["rows_ok"] == 1
        assert result["rows_rejected"] == 0

        # revert_log 事件格式逐字对齐 dict_admin_db 口径
        assert len(result["revert_log"]) == 1
        event = result["revert_log"][0]
        assert event["action"] == "update"
        assert event["table"] == "definitions"
        assert event["row_id"] == row_id
        assert event["old_values"]["chinese_ndef"] == "旧释义"
        assert event["old_values"]["phonetic"] == "/old/"
        # R3-9a：updated_at 导入前旧值随事件收录（MySQL 可消化的串，JSON 可序列化）
        assert event["old_values"]["updated_at"] == OLD_TS

        # 写入生效且 cluster_id / 白名单外列保留（COALESCE 保留语义）
        row = self._row_of("run")
        assert row["chinese_ndef"] == "新释义"
        assert row["phonetic"] == "/rʌn/"
        assert row["cluster_id"] == 7
        assert row["example_sentence"] == "an old example"
        assert row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") != OLD_TS  # 导入顶掉了旧时点

        # 记账 → 回滚 → 行值还原（含 phonetic 的 None 旧值写回 + updated_at 还原）
        assert finish_batch(batch_id, result["rows_total"], result["rows_ok"],
                            result["rows_rejected"]) is True
        assert rollback_batch(batch_id, result["revert_log"]) is True
        restored = self._row_of("run")
        assert restored["chinese_ndef"] == "旧释义"
        assert restored["phonetic"] == "/old/"
        assert restored["cluster_id"] == 7
        # R3-9a：回滚后时间戳回到导入前时点（不被回滚动作本身顶掉）
        assert restored["updated_at"].strftime("%Y-%m-%d %H:%M:%S") == OLD_TS
        with db.get_db_cursor() as cursor:
            cursor.execute("SELECT status FROM import_batches WHERE id = %s", (batch_id,))
            assert cursor.fetchone()["status"] == "rolled_back"

    # --- 实写：insert → revert_log → 回滚的如实限制 ---

    def test_insert_revert_log_and_rollback_voided(self, engine_db):
        """insert 事件回滚（R3-9c）：definitions 补 import_voided 列 → 回滚置
        import_voided=1 作废；行仍留库可审计（不物理 DELETE）。"""
        rows = [{"词目": "dash", "中文释义": "猛冲", "音标": "/dæʃ/"}]
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["ok"] is True
        assert result["rows_ok"] == 1
        assert len(result["revert_log"]) == 1

        event = result["revert_log"][0]
        assert event["action"] == "insert"
        assert event["table"] == "definitions"
        assert isinstance(event["row_id"], int) and event["row_id"] > 0
        assert "old_values" not in event  # insert 事件无 old_values（口径逐字对齐）

        # R3-9c：引擎落的新行显式 import_voided=0（未被作废）
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT import_voided FROM definitions WHERE id = %s",
                (event["row_id"],),
            )
            assert int(cursor.fetchone()["import_voided"]) == 0

        row = self._row_of("dash")
        assert row["id"] == event["row_id"]
        assert row["chinese_ndef"] == "猛冲"
        assert row["phonetic"] == "/dæʃ/"
        assert row["cluster_id"] is None  # 新词目行 cluster_id 显式 NULL

        batch_id = start_batch(1, "new.xlsx", "b" * 64, "definitions", MAPPING, 1)
        assert finish_batch(batch_id, result["rows_total"], result["rows_ok"],
                            result["rows_rejected"]) is True
        assert rollback_batch(batch_id, result["revert_log"]) is True
        # 行仍留库可审计（不物理 DELETE），但 import_voided 置 1 作废（R3-9c）
        assert self._count() == 1
        assert self._row_of("dash") is not None
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT import_voided FROM definitions WHERE id = %s",
                (event["row_id"],),
            )
            assert int(cursor.fetchone()["import_voided"]) == 1

    # --- 实写：混合批次 / 无变更 / 空音标 ---

    def test_mixed_update_and_insert_events(self, engine_db):
        """混合批次：既有行 + 新词目行 → revert_log 两种事件并存。"""
        self._seed("run", "旧释义")
        rows = [
            {"词目": "run", "中文释义": "新释义"},
            {"词目": "jog", "中文释义": "慢跑"},
        ]
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["rows_ok"] == 2
        assert result["rows_total"] == 2
        actions = sorted(e["action"] for e in result["revert_log"])
        assert actions == ["insert", "update"]
        update_event = next(e for e in result["revert_log"] if e["action"] == "update")
        assert update_event["old_values"]["chinese_ndef"] == "旧释义"
        assert "updated_at" in update_event["old_values"]  # R3-9a：旧时间戳随事件收录

    def test_no_change_no_revert_event(self, engine_db):
        """值完全相同的行：不写库、不发 revert 事件；空 revert_log 可回滚。"""
        self._seed("run", "奔跑")
        rows = [{"词目": "run", "中文释义": "奔跑"}]
        batch_id = start_batch(1, "same.xlsx", "c" * 64, "definitions", MAPPING, 1)
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["rows_ok"] == 1          # 幂等重放计 ok
        assert result["revert_log"] == []
        assert self._count() == 1
        assert finish_batch(batch_id, result["rows_total"], 1, 0) is True
        assert rollback_batch(batch_id, []) is True  # 空清单合法（只翻状态）

    def test_empty_phonetic_skipped(self, engine_db):
        """空音标跳过写入：库内现值保留、revert_log 不收 phonetic。"""
        self._seed("run", "旧释义", phonetic="/old/")
        rows = [{"词目": "run", "中文释义": "新释义", "音标": ""}]
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["rows_ok"] == 1
        assert len(result["revert_log"]) == 1
        assert result["revert_log"][0]["old_values"]["chinese_ndef"] == "旧释义"
        assert "updated_at" in result["revert_log"][0]["old_values"]  # R3-9a
        row = self._row_of("run")
        assert row["phonetic"] == "/old/"       # 空单元格不清现值
        assert row["chinese_ndef"] == "新释义"

    def test_whitespace_only_change_noop(self, engine_db):
        """规整后与现值一致的行（原值带首尾空白）→ 无变更、零写。"""
        self._seed("run", "奔跑")
        rows = [{"词目": " run ", "中文释义": " 奔跑 "}]
        result = run_import(rows, MAPPING, 1, dry_run=False)
        assert result["rows_ok"] == 1
        assert result["revert_log"] == []

    def test_revert_log_matches_dict_admin_actions(self, engine_db):
        """revert_log 的 action 值域与 dict_admin_db.REVERT_ACTIONS 逐字对齐。"""
        from src.dict_admin_db import REVERT_ACTIONS

        self._seed("run", "旧释义")
        rows = [{"词目": "run", "中文释义": "新释义"}, {"词目": "jog", "中文释义": "慢跑"}]
        result = run_import(rows, MAPPING, 1, dry_run=False)
        for event in result["revert_log"]:
            assert event["action"] in REVERT_ACTIONS
            assert event["table"] == "definitions"
            assert isinstance(event["row_id"], int) and event["row_id"] > 0
