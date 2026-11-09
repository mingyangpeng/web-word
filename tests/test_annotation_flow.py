"""标注提交与仲裁流模块测试（src/annotation_flow.py）。

两层结构，与 tests/ 既有约定一致：

  * 纯逻辑层（假游标，按 SQL 文本分派，test_reliability.py 同款手法）：
    payload 校验、upsert 语义（验收 V2）、分歧检测等/不等与 bool 比较
    （验收 V3）、仲裁落库参数、任务分配与进度统计 —— 本地与 CI 全跑；
  * 集成层（真实 MySQL 8.0）：与 test_users_db.py 同一约定 —— 连不上或账号
    无建库权限就 skip（类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。
    集成跑在独立测试库 web_word_flow_test（monkeypatch db.MYSQL_DATABASE，
    连接池按 host/port/db/user 键隔离），用 mysql_db.CREATE_TABLES_SQL 建全套
    权威层表（oald_senses 是 annotation_submissions 的外键目标），每个测试重建，
    跑完 DROP。

覆盖的验收标准：V2（覆盖更新）、V3（分歧检测）、V7 相关的数据层侧
（ai_assisted 默认 True 全员同稿；页面展示属集成步骤）。
"""

import json
import math
import os
import sys

import pytest
import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
import src.annotation_flow as flow  # noqa: E402
from src.annotation_flow import (  # noqa: E402
    ADMISSION_FIELDS,
    assign_task,
    detect_disagreements,
    ensure_flow_tables,
    get_assignment_stats,
    get_my_submissions,
    get_submissions_for_sense,
    save_adjudication,
    submit_annotation,
    validate_payload,
)

TEST_DB = "web_word_flow_test"

NAN = float("nan")


# ============================================
# 假游标（按 SQL 文本分派，test_reliability.py 同款）
# ============================================
class _FakeCtx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class _BoomCtx:
    """模拟数据库不可用：进入 with 时抛 pymysql.Error（真实 get_db_cursor 会
    先 logger 再 re-raise，模块的 except 块在 with 语句处接住它）。"""

    def __enter__(self):
        raise pymysql.Error("db down")

    def __exit__(self, *args):
        return False


class FakeFlowCursor:
    """按 SQL 文本分派的假游标：DDL/写语句只捕获参数，SELECT 按 routes 取种子行。"""

    def __init__(self):
        self.executed = []   # [(sql, params)]
        self.routes = []     # [(sql子串, 行列表或 callable(sql, params)->行)]
        self.lastrowid = 4242
        self.rowcount = 1    # MySQL 语义：INSERT/UPDATE 计 1（upsert 计 1 或 2）
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._result = []
        for substring, rows in self.routes:
            if substring in sql:
                self._result = rows(sql, params) if callable(rows) else list(rows)
                return

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _patch_cursor(monkeypatch, routes=None):
    cursor = FakeFlowCursor()
    cursor.routes = routes or []
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _FakeCtx(cursor))
    return cursor


def _patch_boom(monkeypatch):
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _BoomCtx())


def _row(sense_id, coder_id, payload, category="motion", task_type="admission",
         status="submitted", verb="run", sense_index=1, submission_id=0):
    """annotation_submissions 行（detect_disagreements 的 JOIN 种子形状）。"""
    return {
        "id": submission_id,
        "sense_id": sense_id,
        "coder_id": coder_id,
        "payload": payload,
        "category": category,
        "task_type": task_type,
        "status": status,
        "verb": verb,
        "sense_index": sense_index,
    }


# 种子行的 SELECT 分派：镜像真实 WHERE（category/task_type/status='submitted'），
# 这是测试约定（test_reliability.py 同款），不是被测逻辑本身。
def _detect_routes(rows):
    def _select(sql, params):
        category, task_type = params
        return [
            r for r in rows
            if r["category"] == category and r["task_type"] == task_type
            and r["status"] == "submitted"
        ]
    return [("LEFT JOIN oald_senses", _select)]


def _my_routes(rows):
    def _select(sql, params):
        coder_id, category, task_type = params
        return [
            r for r in rows
            if r["coder_id"] == coder_id and r["category"] == category
            and r["task_type"] == task_type
        ]
    return [("WHERE coder_id = %s", _select)]


# ============================================
# ensure_flow_tables：三表 DDL 原样 + 幂等 + 容错
# ============================================
class TestEnsureFlowTables:
    def test_creates_three_flow_tables(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        ensure_flow_tables()
        ddl_texts = [sql for sql, _ in cursor.executed]
        assert any("CREATE TABLE IF NOT EXISTS assignments" in s for s in ddl_texts)
        assert any("CREATE TABLE IF NOT EXISTS annotation_submissions" in s for s in ddl_texts)
        assert any("CREATE TABLE IF NOT EXISTS adjudications" in s for s in ddl_texts)
        # 规范 §2 DDL 原样的关键约束随表落地
        joined = "\n".join(ddl_texts)
        assert "UNIQUE KEY uq_submission (sense_id, task_type, coder_id)" in joined
        assert "UNIQUE KEY uq_adjudication (sense_id, task_type)" in joined
        assert "status ENUM('submitted','adjudicated')" in joined

    def test_ddl_order_assignments_first(self, monkeypatch):
        # assignments 只依赖 users；后两表依赖 users + oald_senses —— 先易后难
        cursor = _patch_cursor(monkeypatch)
        ensure_flow_tables()
        names = []
        for sql, _ in cursor.executed:
            for table in ("assignments", "annotation_submissions", "adjudications"):
                if f"CREATE TABLE IF NOT EXISTS {table}" in sql:
                    names.append(table)
        assert names == ["assignments", "annotation_submissions", "adjudications"]

    def test_db_error_swallowed(self, monkeypatch):
        """数据库不可用只记日志不抛（与 users_db.ensure_user_tables 口径一致）。"""
        _patch_boom(monkeypatch)
        ensure_flow_tables()  # 不应 raise

    def test_status_constants_match_ddl_enum(self):
        """R4 4：status 两态常量与规范 §2 ENUM 一致（页面判断共用常量，防魔法串分叉）。"""
        assert flow.STATUS_SUBMITTED == "submitted"
        assert flow.STATUS_ADJUDICATED == "adjudicated"
        assert flow.SUBMISSION_STATUSES == ("submitted", "adjudicated")


# ============================================
# validate_payload：应用层先拒非法值
# ============================================
class TestValidatePayload:
    def test_admission_valid(self):
        assert validate_payload("admission", {
            "admission": "Y", "schema": "SOURCE_PATH", "alignment": "A",
            "cn_syntax": "主谓宾", "strategy": "直译", "needs_review": True,
        })
        assert validate_payload("admission", {"admission": "EXT"})
        assert validate_payload("admission", {"admission": "N", "needs_review": False})

    def test_admission_illegal_value_rejected(self):
        for bad in ("X", "yes", "", "y", None, 1):
            assert not validate_payload("admission", {"admission": bad}), bad

    def test_admission_missing_key_rejected(self):
        assert not validate_payload("admission", {"schema": "SOURCE_PATH"})

    def test_needs_review_must_be_bool(self):
        assert validate_payload("admission", {"admission": "Y", "needs_review": True})
        for bad in (1, 0, "true", "yes", None):
            assert not validate_payload(
                "admission", {"admission": "Y", "needs_review": bad}
            ), bad

    def test_payload_must_be_nonempty_dict(self):
        assert not validate_payload("admission", {})
        assert not validate_payload("admission", None)
        assert not validate_payload("admission", [])
        assert not validate_payload("admission", "admission")

    def test_non_scalar_values_rejected(self):
        assert not validate_payload("admission", {"admission": "Y", "schema": {"a": 1}})
        assert not validate_payload("admission", {"admission": "Y", "schema": ["A"]})
        assert not validate_payload("admission", {"admission": "Y", "schema": None})
        assert not validate_payload("admission", {"admission": "Y", "schema": NAN})
        assert not validate_payload("admission", {"admission": "Y", "schema": math.inf})

    def test_extra_keys_allowed_if_scalar(self):
        assert validate_payload("admission", {"admission": "N", "备注": "初筛存疑"})

    def test_feature_coding_valid(self):
        assert validate_payload("feature_coding", {"features": {"P1": 1, "P5": 3}})
        assert validate_payload("feature_coding", {"features": {"P1": 0}})
        assert validate_payload("feature_coding", {"features": {"P9": " manner"}})

    def test_feature_coding_rejections(self):
        assert not validate_payload("feature_coding", {"features": {}})          # 空
        assert not validate_payload("feature_coding", {"features": None})        # 缺
        assert not validate_payload("feature_coding", {"features": ["P1"]})      # 非 dict
        assert not validate_payload("feature_coding", {})                        # 无 features
        assert not validate_payload("feature_coding", {"features": {"P1": {"x": 1}}})
        assert not validate_payload("feature_coding", {"features": {"P1": None}})
        assert not validate_payload("feature_coding", {"features": {"": 1}})     # 空特征码

    def test_alignment_payload(self):
        assert validate_payload("alignment", {"alignment": "A1"})
        assert not validate_payload("alignment", {})
        assert not validate_payload("alignment", {"alignment": ["A1"]})

    def test_nan_feature_value_rejected(self):
        assert not validate_payload("feature_coding", {"features": {"P1": NAN}})

    def test_nan_string_values_rejected(self):
        """R4 1a：字符串 'nan'（float() 可解析出 NaN）在入口拒收。

        两个下游消费方（本模块 _normalize_for_compare 与
        reliability._is_usable_label）都把这类串按缺失剔除 —— 静默入库只会
        存垃圾值，与「非法值根本不进数据库」口径矛盾（docs/dev/reviews/review_R4.md 1a）。
        """
        for bad in ("nan", "NaN", " nan "):
            assert not validate_payload("feature_coding", {"features": {"P1": bad}}), bad
            assert not validate_payload("admission", {"admission": "Y", "schema": bad}), bad
            assert not validate_payload("admission", {"admission": "Y", "备注": bad}), bad
        # 非 NaN 的数值串照常放行（"inf" 是合法 nominal 标签，两侧口径同此）
        assert validate_payload("feature_coding", {"features": {"C1": "方式", "P9": "inf"}})


# ============================================
# submit_annotation：upsert 语义（验收 V2）
# ============================================
class TestSubmitAnnotation:
    UPSERT_SQL_SUBSTRINGS = (
        "INSERT INTO annotation_submissions",
        "ON DUPLICATE KEY UPDATE",
        "status = 'submitted'",
        "submitted_at = CURRENT_TIMESTAMP",
    )

    def test_valid_insert_captures_params(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        payload = {"admission": "Y", "schema": "SOURCE_PATH", "needs_review": True}
        assert submit_annotation("motion", 101, "admission", 7, payload) is True
        assert len(cursor.executed) == 1
        sql, params = cursor.executed[0]
        for substring in self.UPSERT_SQL_SUBSTRINGS:
            assert substring in sql, substring
        category, sense_id, task_type, coder_id, payload_json, ai_assisted = params
        assert (category, sense_id, task_type, coder_id) == ("motion", 101, "admission", 7)
        # payload 以 JSON 文本落 JSON 列（ensure_ascii=False 断言在下一测）
        assert json.loads(payload_json) == payload
        assert ai_assisted == 1  # 默认全员看 AI 草稿（用户决策③）

    def test_payload_json_chinese_unescaped(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        submit_annotation("motion", 101, "admission", 7,
                          {"admission": "Y", "cn_syntax": "奔跑义"})
        _, params = cursor.executed[0]
        assert "奔跑义" in params[4]  # ensure_ascii=False

    def test_ai_assisted_false(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert submit_annotation("motion", 101, "admission", 7, {"admission": "N"},
                                 ai_assisted=False) is True
        assert cursor.executed[0][1][5] == 0

    def test_upsert_resubmission_overwrites(self, monkeypatch):
        """重复提交走 ON DUPLICATE KEY UPDATE 且 status 重置 submitted（验收 V2）。"""
        cursor = _patch_cursor(monkeypatch)
        submit_annotation("motion", 101, "admission", 7, {"admission": "Y"})
        submit_annotation("motion", 101, "admission", 7, {"admission": "EXT"})
        assert len(cursor.executed) == 2
        sql2, params2 = cursor.executed[1]
        assert "ON DUPLICATE KEY UPDATE" in sql2
        assert "status = 'submitted'" in sql2  # 覆盖后重新进入审核流
        assert json.loads(params2[4]) == {"admission": "EXT"}

    def test_illegal_payload_rejected(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert submit_annotation("motion", 101, "admission", 7, {"admission": "X"}) is False
        assert submit_annotation("motion", 101, "admission", 7, {}) is False
        assert submit_annotation("motion", 101, "feature_coding", 7, {"features": {}}) is False
        assert submit_annotation("motion", 101, "admission", 7, "Y") is False
        assert cursor.executed == []  # 非法值根本不进数据库

    def test_nan_string_payload_rejected(self, monkeypatch):
        """R4 1a 回归：'nan' 串在服务端校验被拒，SQL 根本不执行。"""
        cursor = _patch_cursor(monkeypatch)
        assert submit_annotation("motion", 101, "feature_coding", 7,
                                 {"features": {"P1": "nan"}}) is False
        assert submit_annotation("motion", 101, "admission", 7,
                                 {"admission": "Y", "schema": "NaN"}) is False
        assert cursor.executed == []

    def test_large_payload_1000_features(self, monkeypatch):
        """R4 2：大 payload（1000 特征）不炸 —— 校验、JSON 序列化、参数捕获正常。"""
        cursor = _patch_cursor(monkeypatch)
        features = {f"P{i}": i % 2 for i in range(1000)}
        assert submit_annotation("motion", 101, "feature_coding", 7,
                                 {"features": features}) is True
        sql, params = cursor.executed[0]
        assert "INSERT INTO annotation_submissions" in sql
        assert json.loads(params[4]) == {"features": features}

    def test_illegal_ids_and_task_rejected(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        good = {"admission": "Y"}
        assert submit_annotation("motion", 101, "screening", 7, good) is False   # task 非法
        assert submit_annotation("motion", "abc", "admission", 7, good) is False
        assert submit_annotation("motion", 0, "admission", 7, good) is False
        assert submit_annotation("motion", None, "admission", 7, good) is False
        assert submit_annotation("motion", 101, "admission", None, good) is False
        assert submit_annotation("", 101, "admission", 7, good) is False
        assert cursor.executed == []

    def test_db_error_returns_false(self, monkeypatch):
        _patch_boom(monkeypatch)
        assert submit_annotation("motion", 101, "admission", 7, {"admission": "Y"}) is False


# ============================================
# get_my_submissions / get_submissions_for_sense
# ============================================
def _sub_row(**kw):
    """SELECT 种子行（模块 _submission_row_to_dict 的输入形状）。"""
    base = {
        "id": kw.get("id", 1),
        "category": kw.get("category", "motion"),
        "sense_id": kw.get("sense_id", 101),
        "task_type": kw.get("task_type", "admission"),
        "coder_id": kw.get("coder_id", 7),
        "payload": kw.get("payload", {"admission": "Y"}),
        "ai_assisted": kw.get("ai_assisted", 1),
        "status": kw.get("status", "submitted"),
        "submitted_at": kw.get("submitted_at", "2026-01-01 00:00:00"),
    }
    base.update({k: v for k, v in kw.items() if k in ("username", "display_name")})
    return base


class TestGetMySubmissions:
    def test_returns_own_rows_parsed(self, monkeypatch):
        rows = [
            _sub_row(sense_id=102, coder_id=7, payload=json.dumps({"admission": "EXT"}),
                     status="adjudicated"),
            _sub_row(sense_id=101, coder_id=7, id=2),
        ]
        cursor = _patch_cursor(monkeypatch, _my_routes(rows))
        got = get_my_submissions(7, "motion", "admission")
        assert [g["sense_id"] for g in got] == [102, 101]  # 假游标保持种子顺序
        assert got[0]["payload"] == {"admission": "EXT"}   # JSON 字符串被解析
        assert got[0]["status"] == "adjudicated"           # 自己的历史结论对自己可见
        assert got[1]["ai_assisted"] is True and isinstance(got[1]["ai_assisted"], bool)
        assert "password_hash" not in got[0]
        assert cursor.executed[0][1] == (7, "motion", "admission")

    def test_payload_dict_passthrough(self, monkeypatch):
        rows = [_sub_row(payload={"admission": "N"})]
        _patch_cursor(monkeypatch, _my_routes(rows))
        got = get_my_submissions(7, "motion", "admission")
        assert got[0]["payload"] == {"admission": "N"}

    def test_invalid_coder_id(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert get_my_submissions(None, "motion", "admission") == []
        assert get_my_submissions("abc", "motion", "admission") == []
        assert cursor.executed == []

    def test_db_error_returns_empty(self, monkeypatch):
        _patch_boom(monkeypatch)
        assert get_my_submissions(7, "motion", "admission") == []


class TestGetSubmissionsForSense:
    ROWS = [
        _sub_row(id=1, sense_id=101, coder_id=7, payload={"admission": "Y"}),
        _sub_row(id=2, sense_id=101, coder_id=8, payload={"admission": "N"},
                 status="adjudicated", username="bob", display_name="鲍勃"),
    ]
    ROUTES = [("LEFT JOIN users u ON u.id = s.coder_id", ROWS)]

    def test_cross_coder_rows_with_username(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch, self.ROUTES)
        got = get_submissions_for_sense(101, "admission")
        assert len(got) == 2
        assert {g["coder_id"] for g in got} == {7, 8}
        assert got[1]["username"] == "bob" and got[1]["display_name"] == "鲍勃"
        assert got[0]["payload"] == {"admission": "Y"}
        # reviewer/admin「看全部」：adjudicated 历史也返回（留痕可见）
        assert {g["status"] for g in got} == {"submitted", "adjudicated"}
        _, params = cursor.executed[0]
        assert params == (101, "admission")

    def test_invalid_sense_id(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert get_submissions_for_sense(None, "admission") == []
        assert cursor.executed == []

    def test_db_error_returns_empty(self, monkeypatch):
        _patch_boom(monkeypatch)
        assert get_submissions_for_sense(101, "admission") == []


# ============================================
# detect_disagreements（验收 V3）
# ============================================
class TestDetectDisagreementsAdmission:
    def test_admission_compare_fields_per_spec(self):
        """比对字段 = admission/schema/alignment/needs_review（任务要求，钉死契约）。"""
        assert ADMISSION_FIELDS == ("admission", "schema", "alignment", "needs_review")

    def test_disagreement_detected_with_verb_join(self, monkeypatch):
        rows = [
            _row(101, 7, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
            _row(101, 8, {"admission": "N", "schema": "SOURCE_PATH", "alignment": "A"},
                 verb="run", sense_index=1),
        ]
        cursor = _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "admission")
        assert len(result) == 1
        entry = result[0]
        assert entry["sense_id"] == 101
        assert entry["verb"] == "run" and entry["sense_index"] == 1  # JOIN oald_senses
        assert entry["n_submissions"] == 2
        assert entry["fields"] == [
            {"field": "admission", "values": {"7": "Y", "8": "N"}}
        ]
        # 只统计 status='submitted'（已仲裁的退出分歧清单）
        assert "status = 'submitted'" in cursor.executed[0][0]

    def test_full_agreement_not_listed(self, monkeypatch):
        rows = [
            _row(101, 7, {"admission": "Y", "schema": "S", "alignment": "A"}),
            _row(101, 8, {"admission": "Y", "schema": "S", "alignment": "A"}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission") == []

    def test_all_admission_fields_compared(self, monkeypatch):
        """schema / alignment 字段的分歧也被捕获；payload 未给的字段不出现在 fields。"""
        rows = [
            _row(101, 7, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
            _row(101, 8, {"admission": "Y", "schema": "SOURCE_GOAL", "alignment": "B"}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "admission")
        assert [f["field"] for f in result[0]["fields"]] == ["schema", "alignment"]
        assert result[0]["fields"][0]["values"] == {"7": "SOURCE_PATH", "8": "SOURCE_GOAL"}

    def test_needs_review_bool_compare(self, monkeypatch):
        """bool 值转 'true'/'false' 比较（任务要求）。"""
        rows = [
            _row(101, 7, {"admission": "Y", "needs_review": True}),
            _row(101, 8, {"admission": "Y", "needs_review": False}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "admission")
        assert result[0]["fields"] == [
            {"field": "needs_review", "values": {"7": "true", "8": "false"}}
        ]

    def test_needs_review_equal_bools_not_listed(self, monkeypatch):
        rows = [
            _row(101, 7, {"admission": "Y", "needs_review": True}),
            _row(101, 8, {"admission": "Y", "needs_review": True}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission") == []

    def test_needs_review_int_tinyint_compat(self, monkeypatch):
        """防御：0/1 整数（TINYINT 混写）也按 'true'/'false' 比较。"""
        rows = [
            _row(101, 7, {"admission": "Y", "needs_review": 1}),
            _row(101, 8, {"admission": "Y", "needs_review": 0}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "admission")
        assert result[0]["fields"] == [
            {"field": "needs_review", "values": {"7": "true", "8": "false"}}
        ]

    def test_payload_as_json_string(self, monkeypatch):
        """PyMySQL 对 JSON 列可能返回字符串（真实集成亦验证）。"""
        rows = [
            _row(101, 7, json.dumps({"admission": "Y"})),
            _row(101, 8, {"admission": "N"}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "admission")
        assert result[0]["fields"][0]["values"] == {"7": "Y", "8": "N"}

    def test_missing_field_tolerated(self, monkeypatch):
        """某 coder 缺字段：缺失容忍，不炸也不当第三取值。"""
        rows = [
            _row(101, 7, {"admission": "Y", "schema": "A"}),
            _row(101, 8, {"admission": "Y"}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission") == []

    def test_nan_value_treated_missing(self, monkeypatch):
        rows = [
            _row(101, 7, {"admission": "Y", "schema": NAN}),
            _row(101, 8, {"admission": "Y", "schema": "A"}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission") == []

    def test_adjudicated_excluded(self, monkeypatch):
        rows = [
            _row(101, 7, {"admission": "Y"}, status="adjudicated"),
            _row(101, 8, {"admission": "N"}, status="adjudicated"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission") == []

    def test_min_coders_threshold(self, monkeypatch):
        rows = [
            # 101：2 人分歧（min_coders=3 时不进清单）
            _row(101, 7, {"admission": "Y"}),
            _row(101, 8, {"admission": "N"}),
            # 102：3 人（其中一对分歧）
            _row(102, 7, {"admission": "Y"}, verb="walk", sense_index=2),
            _row(102, 8, {"admission": "N"}),
            _row(102, 9, {"admission": "Y"}),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission", min_coders=2) == [
            {"sense_id": 101, "verb": "run", "sense_index": 1, "n_submissions": 2,
             "fields": [{"field": "admission", "values": {"7": "Y", "8": "N"}}]},
            {"sense_id": 102, "verb": "walk", "sense_index": 2, "n_submissions": 3,
             "fields": [{"field": "admission", "values": {"7": "Y", "8": "N", "9": "Y"}}]},
        ]
        assert [e["sense_id"] for e in detect_disagreements("motion", "admission",
                                                            min_coders=3)] == [102]

    def test_single_coder_not_listed(self, monkeypatch):
        rows = [_row(101, 7, {"admission": "Y"})]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "admission") == []

    def test_orphan_sense_without_oald_row(self, monkeypatch):
        """义位不在 oald_senses（LEFT JOIN 落空）：verb/sense_index 为 None 仍列出。"""
        rows = [
            _row(999, 7, {"admission": "Y"}, verb=None, sense_index=None),
            _row(999, 8, {"admission": "N"}, verb=None, sense_index=None),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "admission")
        assert result[0]["verb"] is None and result[0]["sense_index"] is None

    def test_invalid_task_type_and_db_error(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert detect_disagreements("motion", "screening") == []
        assert cursor.executed == []
        _patch_boom(monkeypatch)
        assert detect_disagreements("motion", "admission") == []


class TestDetectDisagreementsFeatureCoding:
    def test_per_feature_compare(self, monkeypatch):
        rows = [
            _row(201, 7, {"features": {"P1": 1, "P5": 2}}, task_type="feature_coding"),
            _row(201, 8, {"features": {"P1": 0, "P5": 2}}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "feature_coding")
        assert len(result) == 1
        assert result[0]["fields"] == [{"field": "P1", "values": {"7": 1, "8": 0}}]

    def test_multiple_disagreeing_features_sorted(self, monkeypatch):
        rows = [
            _row(201, 7, {"features": {"P9": "a", "P1": 1, "P5": 2}},
                 task_type="feature_coding"),
            _row(201, 8, {"features": {"P9": "b", "P1": 1, "P5": 3}},
                 task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "feature_coding")
        assert [f["field"] for f in result[0]["fields"]] == ["P5", "P9"]  # 按名排序

    def test_feature_present_in_one_coder_only(self, monkeypatch):
        rows = [
            _row(201, 7, {"features": {"P1": 1, "P7": 5}}, task_type="feature_coding"),
            _row(201, 8, {"features": {"P1": 1}}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "feature_coding") == []

    def test_none_feature_value_treated_missing(self, monkeypatch):
        """R4 1b 补充：显式 None 特征值按缺失（不参与比对、不当第三取值）。"""
        rows = [
            _row(201, 7, {"features": {"P1": None, "P5": 2}}, task_type="feature_coding"),
            _row(201, 8, {"features": {"P1": 1, "P5": 2}}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "feature_coding") == []

    def test_large_feature_set_1000(self, monkeypatch):
        """R4 2：1000 特征的大 payload 分歧检测不炸，且只报真实分歧的特征。"""
        feats_a = {f"P{i}": i % 2 for i in range(1000)}
        feats_b = dict(feats_a, P999=1 - feats_a["P999"])  # 仅 P999 一处分歧
        rows = [
            _row(201, 7, {"features": feats_a}, task_type="feature_coding"),
            _row(201, 8, {"features": feats_b}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "feature_coding")
        assert len(result) == 1
        assert [f["field"] for f in result[0]["fields"]] == ["P999"]
        assert result[0]["n_submissions"] == 2

    def test_bool_feature_value_normalized(self, monkeypatch):
        rows = [
            _row(201, 7, {"features": {"P1": True}}, task_type="feature_coding"),
            _row(201, 8, {"features": {"P1": False}}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "feature_coding")
        assert result[0]["fields"] == [{"field": "P1", "values": {"7": "true", "8": "false"}}]

    def test_nan_string_feature_value_treated_missing(self, monkeypatch):
        """R2 修复回归：字符串 'nan'（float 可解析出 NaN）按缺失，不做假标签。

        修复前：'nan' 与对方真实取值比较会报出假分歧（reliability 侧同一取值
        按缺失跳过，两个分歧口径不一致）；修复后两侧口径一致（docs/dev/reviews/review_R2.md F1）。
        """
        rows = [
            _row(201, 7, {"features": {"P1": 1, "P5": "nan"}}, task_type="feature_coding"),
            _row(201, 8, {"features": {"P1": 1, "P5": 2}}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        assert detect_disagreements("motion", "feature_coding") == []


class TestDetectDisagreementsAlignmentTask:
    def test_alignment_field_only(self, monkeypatch):
        rows = [
            _row(301, 7, {"alignment": "A"}, task_type="alignment"),
            _row(301, 8, {"alignment": "B"}, task_type="alignment"),
        ]
        _patch_cursor(monkeypatch, _detect_routes(rows))
        result = detect_disagreements("motion", "alignment")
        assert result[0]["fields"] == [{"field": "alignment", "values": {"7": "A", "8": "B"}}]


# ============================================
# save_adjudication
# ============================================
class TestSaveAdjudication:
    def test_insert_and_status_flip(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        gold = {"admission": "EXT", "schema": "SOURCE_PATH", "needs_review": False}
        ok = save_adjudication(101, "admission", 2, gold, [11, 12], "证据更充分")
        assert ok is True
        assert len(cursor.executed) == 2
        insert_sql, insert_params = cursor.executed[0]
        assert "INSERT INTO adjudications" in insert_sql
        assert "ON DUPLICATE KEY UPDATE" in insert_sql  # 重复仲裁=覆盖定稿
        sense_id, task_type, ids_json, adjudicator_id, gold_json, note = insert_params
        assert (sense_id, task_type, adjudicator_id, note) == (101, "admission", 2, "证据更充分")
        assert json.loads(ids_json) == [11, 12]
        assert json.loads(gold_json) == gold
        update_sql, update_params = cursor.executed[1]
        assert "UPDATE annotation_submissions SET status = 'adjudicated'" in update_sql
        assert "id IN (%s, %s)" in update_sql
        assert update_params == (101, "admission", 11, 12)

    def test_empty_submission_ids_skips_update(self, monkeypatch):
        """无历史提交直接定稿：只写 gold，不翻状态。"""
        cursor = _patch_cursor(monkeypatch)
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, [], None) is True
        assert len(cursor.executed) == 1
        assert "INSERT INTO adjudications" in cursor.executed[0][0]

    def test_uses_transaction(self, monkeypatch):
        """定稿落库与状态翻转在同一事务（autocommit=False）。"""
        captured = {}

        def _factory(autocommit=True):
            captured["autocommit"] = autocommit
            return _FakeCtx(FakeFlowCursor())
        monkeypatch.setattr(flow, "get_db_cursor", _factory)
        save_adjudication(101, "admission", 2, {"admission": "Y"}, [11], None)
        assert captured["autocommit"] is False

    def test_invalid_gold_payload_rejected(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert save_adjudication(101, "admission", 2, {"admission": "X"}, [11], None) is False
        assert save_adjudication(101, "admission", 2, {}, [11], None) is False
        assert save_adjudication(101, "feature_coding", 2, {"features": {}}, [11], None) is False
        assert cursor.executed == []

    def test_invalid_submission_ids_rejected(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, "11", None) is False
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, ["abc"], None) is False
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, None, None) is False
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, [0], None) is False
        assert cursor.executed == []

    def test_invalid_ids_and_task_rejected(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert save_adjudication(101, "screening", 2, {"admission": "Y"}, [11], None) is False
        assert save_adjudication(None, "admission", 2, {"admission": "Y"}, [11], None) is False
        assert save_adjudication(101, "admission", None, {"admission": "Y"}, [11], None) is False
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, [11], 123) is False
        assert cursor.executed == []

    def test_db_error_returns_false(self, monkeypatch):
        _patch_boom(monkeypatch)
        assert save_adjudication(101, "admission", 2, {"admission": "Y"}, [11], None) is False

    # --- R1-1 直调面：actor 足色闸门（施工规范 §14 批次 12） ---

    def test_actor_none_is_system_job(self, monkeypatch):
        """actor=None（缺省）= 系统作业：现状不变（既有调用零破坏）。"""
        cursor = _patch_cursor(monkeypatch)
        assert save_adjudication(
            101, "admission", 2, {"admission": "Y"}, [11], None) is True
        assert len(cursor.executed) == 2          # INSERT gold + UPDATE 状态翻转

    def test_actor_reviewer_and_above_pass(self, monkeypatch):
        """reviewer/dict_admin/sys_admin（含 legacy admin 映射）→ 放行。"""
        cursor = _patch_cursor(monkeypatch)
        gold = {"admission": "Y"}
        assert save_adjudication(101, "admission", 2, gold, [], None,
                                 actor={"id": 3, "role": "viewer",
                                        "roles": ["reviewer"]}) is True
        assert save_adjudication(101, "admission", 2, gold, [], None,
                                 actor={"id": 1, "role": "admin"}) is True
        assert save_adjudication(101, "admission", 2, gold, [], None,
                                 actor={"id": 5, "role": "viewer",
                                        "roles": ["dict_admin"]}) is True
        assert len(cursor.executed) == 3

    def test_actor_low_privilege_raises_permission_error(self, monkeypatch):
        """低权 actor（editor/annotator/viewer/空集）抛 PermissionError，不触库。"""
        cursor = _patch_cursor(monkeypatch)
        gold = {"admission": "Y"}
        for actor in (
            {"id": 7, "role": "viewer", "roles": ["annotator", "viewer"]},
            {"id": 7, "role": "viewer", "roles": ["editor"]},
            {"id": 7, "role": "viewer", "roles": ["viewer"]},
            {"id": 7, "role": "annotator"},            # legacy 无六角色映射
            {"id": 7, "role": "viewer"},               # 无 roles 键
        ):
            with pytest.raises(PermissionError, match="仲裁"):
                save_adjudication(101, "admission", 2, gold, [11], None,
                                  actor=actor)
        assert cursor.executed == []                # 异常在触库前抛出

    def test_actor_garbage_raises_permission_error(self, monkeypatch):
        """非 dict 垃圾 actor（str/int/list）fail-closed 抛 PermissionError。"""
        _patch_cursor(monkeypatch)
        for actor in ("admin", 42, ["reviewer"], True):
            with pytest.raises(PermissionError):
                save_adjudication(101, "admission", 2, {"admission": "Y"},
                                  [11], None, actor=actor)


# ============================================
# assign_task（补充函数）与 get_assignment_stats
# ============================================
class TestAssignTask:
    def test_insert_captures_params(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert assign_task(7, "motion", "admission", ["run", "walk"], 1) is True
        sql, params = cursor.executed[0]
        assert "INSERT INTO assignments" in sql
        # FX-20：INSERT 追加 round/training 两列（默认 None 不留痕，RV2-3 口径）
        assignee, category, task_type, scope_json, assigned_by, round_val, training_val = params
        assert (assignee, category, task_type, assigned_by) == (7, "motion", "admission", 1)
        assert json.loads(scope_json) == ["run", "walk"]
        assert round_val is None and training_val is None

    def test_scope_none_means_all_verbs(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert assign_task(7, "motion", "feature_coding", None, 1) is True
        assert cursor.executed[0][1][3] is None

    def test_scope_tuple_accepted(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert assign_task(7, "motion", "admission", ("run",), 1) is True
        assert json.loads(cursor.executed[0][1][3]) == ["run"]

    def test_invalid_inputs_rejected(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch)
        assert assign_task(7, "motion", "screening", None, 1) is False
        assert assign_task(7, "motion", "admission", "run", 1) is False      # 非 list
        assert assign_task(7, "motion", "admission", [], 1) is False          # 空（请传 None）
        assert assign_task(7, "motion", "admission", [""], 1) is False
        assert assign_task(None, "motion", "admission", None, 1) is False
        assert assign_task(7, "motion", "admission", None, None) is False
        assert assign_task(7, "", "admission", None, 1) is False
        assert cursor.executed == []

    def test_fk_violation_returns_false(self, monkeypatch):
        """assignee 不存在（FK 拒绝，errno 1452）→ False 而不是抛异常。"""
        _patch_boom(monkeypatch)
        assert assign_task(99999, "motion", "admission", None, 1) is False


class TestGetAssignmentStats:
    ASSIGN_ROWS = [
        {
            "assignment_id": 1, "assignee_id": 7, "category": "motion",
            "task_type": "admission", "assignment_status": "in_progress",
            "scope_verbs": '["run", "walk"]', "assigned_by": 1,
            "username": "alice", "display_name": "爱丽丝",
            "n_submitted": 12, "n_adjudicated": 3,
        },
    ]
    ORPHAN_ROWS = [
        {
            "assignee_id": 8, "category": "motion", "task_type": "feature_coding",
            "n_submitted": 2, "n_adjudicated": 0,
            "username": "bob", "display_name": "鲍勃",
        },
    ]
    ROUTES = [
        ("NOT EXISTS", ORPHAN_ROWS),
        ("FROM assignments a", ASSIGN_ROWS),
    ]

    def test_merges_assignments_and_orphans(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch, self.ROUTES)
        stats = get_assignment_stats()
        assert len(stats) == 2
        assigned = stats[0]
        assert assigned["assignment_id"] == 1
        assert assigned["assignee_id"] == 7
        assert assigned["username"] == "alice"
        assert assigned["scope_verbs"] == ["run", "walk"]     # JSON 列被解析
        assert assigned["assignment_status"] == "in_progress"
        assert (assigned["n_submitted"], assigned["n_adjudicated"]) == (12, 3)
        orphan = stats[1]
        assert orphan["assignment_id"] is None                # 自发表（无分配）
        assert orphan["assignment_status"] is None
        assert orphan["scope_verbs"] is None
        assert orphan["n_submitted"] == 2
        assert len(cursor.executed) == 2  # 两条统计 SQL 都执行

    def test_scope_verbs_null(self, monkeypatch):
        rows = [dict(self.ASSIGN_ROWS[0], scope_verbs=None)]
        _patch_cursor(monkeypatch, [("FROM assignments a", rows), ("NOT EXISTS", [])])
        stats = get_assignment_stats()
        assert stats[0]["scope_verbs"] is None                # NULL = 全部动词

    def test_scope_verbs_bad_json_null(self, monkeypatch):
        """R4 2：scope_verbs 列内容不是合法 JSON（或非数组）→ None，不炸统计页。"""
        for bad in ("not-json", '{"a": 1}', "[1, 2"):
            rows = [dict(self.ASSIGN_ROWS[0], scope_verbs=bad)]
            _patch_cursor(monkeypatch, [("FROM assignments a", rows), ("NOT EXISTS", [])])
            stats = get_assignment_stats()
            assert stats[0]["scope_verbs"] is None, bad

    def test_db_error_returns_empty(self, monkeypatch):
        _patch_boom(monkeypatch)
        assert get_assignment_stats() == []


# ============================================
# 集成测试：真实 MySQL（无环境则整类 skip）
# ============================================

def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不建库）。"""
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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 flow 数据层集成测试")
class TestFlowIntegration:
    """提交流/分歧/仲裁/分配跑在真实 MySQL 8.0（独立测试库 web_word_flow_test）。"""

    @pytest.fixture
    def flow_db(self, monkeypatch):
        """
        建空测试库并指向它；用 mysql_db.CREATE_TABLES_SQL 建权威层全套表
        （oald_senses / users 是 flow 表的外键目标），再 ensure_user_tables +
        ensure_flow_tables；种子 1 词条 2 义项、2 名标注员 + 1 名 reviewer。
        测试结束 DROP。无建库权限则 skip（环境能力问题，不是代码缺陷）。
        """
        original_database = db.MYSQL_DATABASE
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
            cur.execute(f"USE {TEST_DB}")  # 裸连接建权威层表需要先选中库
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 flow 集成测试: {e}")
        conn.commit()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        # 权威层全套表（含 definitions / oald_senses / word_clusters 等外键链）
        db._register_category_study_tables()
        db._register_zh_dict_tables()
        for table_sql in db.CREATE_TABLES_SQL:
            cur.execute(table_sql)
        conn.commit()
        conn.close()

        from src.users_db import create_user, ensure_user_tables

        ensure_user_tables()      # users 表 + 内置 admin（assigned_by 用）
        ensure_flow_tables()      # flow 三表

        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
                "VALUES (%s, %s, %s)",
                ("run", "跑", json.dumps({"manner": "x"})),
            )
            definition_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO oald_senses (definition_id, sense_index, definition, headword) "
                "VALUES (%s, %s, %s, %s)",
                (definition_id, 1, "to move fast on foot", "run"),
            )
            sense_a = cursor.lastrowid
            cursor.execute(
                "INSERT INTO oald_senses (definition_id, sense_index, definition, headword) "
                "VALUES (%s, %s, %s, %s)",
                (definition_id, 2, "to manage a business", "run"),
            )
            sense_b = cursor.lastrowid
        coder_a = create_user("alice", "pw123456", "爱丽丝", "annotator")
        coder_b = create_user("bob", "pw123456", "鲍勃", "annotator")
        reviewer = create_user("rachel", "pw123456", "瑞秋", "reviewer")
        assert all(isinstance(u, int) for u in (coder_a, coder_b, reviewer))

        yield {
            "admin_id": 1,
            "coder_a": coder_a,
            "coder_b": coder_b,
            "reviewer": reviewer,
            "sense_a": sense_a,
            "sense_b": sense_b,
        }

        # 还原全局再删库：避免池中归还路径引用已删的库
        monkeypatch.setattr(db, "MYSQL_DATABASE", original_database)
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

    def _table_names(self):
        with db.get_db_cursor() as cursor:
            cursor.execute("SHOW TABLES")
            return {list(row.values())[0] for row in cursor.fetchall()}

    # --- 建表 ---

    def test_ensure_flow_tables_idempotent(self, flow_db):
        ensure_flow_tables()
        ensure_flow_tables()
        tables = self._table_names()
        assert {"assignments", "annotation_submissions", "adjudications"} <= tables

    # --- 提交流（验收 V2 / V7 数据层侧）---

    def test_submit_and_resubmit_overwrites(self, flow_db):
        """V2：同 (sense, task, coder) 重复提交 = 覆盖更新，status 重置 submitted。"""
        ctx = flow_db
        assert submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                                 {"admission": "Y", "schema": "SOURCE_PATH"}) is True
        first = get_my_submissions(ctx["coder_a"], "motion", "admission")
        assert len(first) == 1 and first[0]["payload"]["admission"] == "Y"
        assert first[0]["ai_assisted"] is True  # 用户决策③：默认 AI 草稿口径

        assert submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                                 {"admission": "EXT", "schema": "SOURCE_GOAL"}) is True
        second = get_my_submissions(ctx["coder_a"], "motion", "admission")
        assert len(second) == 1                       # 仍是一条（UNIQUE upsert）
        assert second[0]["id"] == first[0]["id"]
        assert second[0]["payload"]["admission"] == "EXT"  # 覆盖为新值

    def test_illegal_payload_never_enters_db(self, flow_db):
        assert submit_annotation("motion", flow_db["sense_a"], "admission",
                                 flow_db["coder_a"], {"admission": "X"}) is False
        # R4 1a：'nan' 串同样被服务端校验拒收（真实 MySQL JSON 列路径）
        assert submit_annotation("motion", flow_db["sense_a"], "admission",
                                 flow_db["coder_a"], {"admission": "Y", "schema": "nan"}) is False
        assert submit_annotation("motion", flow_db["sense_a"], "feature_coding",
                                 flow_db["coder_a"], {"features": {"P1": "NaN"}}) is False
        assert get_my_submissions(flow_db["coder_a"], "motion", "admission") == []

    # --- 分歧检测（验收 V3）---

    def test_disagreement_detected_end_to_end(self, flow_db):
        ctx = flow_db
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                          {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A",
                           "needs_review": True})
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_b"],
                          {"admission": "N", "schema": "SOURCE_PATH", "alignment": "A",
                           "needs_review": False})
        # sense_b 两人一致
        submit_annotation("motion", ctx["sense_b"], "admission", ctx["coder_a"],
                          {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"})
        submit_annotation("motion", ctx["sense_b"], "admission", ctx["coder_b"],
                          {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"})

        result = detect_disagreements("motion", "admission")
        assert [e["sense_id"] for e in result] == [ctx["sense_a"]]
        entry = result[0]
        assert entry["verb"] == "run" and entry["sense_index"] == 1  # JOIN oald_senses
        assert entry["n_submissions"] == 2
        fields = {f["field"]: f["values"] for f in entry["fields"]}
        assert fields["admission"] == {str(ctx["coder_a"]): "Y", str(ctx["coder_b"]): "N"}
        assert fields["needs_review"] == {str(ctx["coder_a"]): "true",
                                          str(ctx["coder_b"]): "false"}
        assert "schema" not in fields and "alignment" not in fields

    def test_feature_coding_disagreement_end_to_end(self, flow_db):
        ctx = flow_db
        submit_annotation("motion", ctx["sense_a"], "feature_coding", ctx["coder_a"],
                          {"features": {"P1": 1, "P5": 2}})
        submit_annotation("motion", ctx["sense_a"], "feature_coding", ctx["coder_b"],
                          {"features": {"P1": 0, "P5": 2}})
        result = detect_disagreements("motion", "feature_coding")
        assert len(result) == 1
        assert result[0]["fields"] == [
            {"field": "P1", "values": {str(ctx["coder_a"]): 1, str(ctx["coder_b"]): 0}}
        ]

    # --- 独立性（用户决策④的数据层侧）---

    def test_independence_my_vs_for_sense(self, flow_db):
        ctx = flow_db
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                          {"admission": "Y"})
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_b"],
                          {"admission": "N"})
        mine = get_my_submissions(ctx["coder_a"], "motion", "admission")
        assert len(mine) == 1 and mine[0]["coder_id"] == ctx["coder_a"]
        all_rows = get_submissions_for_sense(ctx["sense_a"], "admission")
        assert {r["coder_id"] for r in all_rows} == {ctx["coder_a"], ctx["coder_b"]}
        usernames = {r["coder_id"]: r["username"] for r in all_rows}
        assert usernames[ctx["coder_b"]] == "bob"

    # --- 仲裁 ---

    def test_adjudication_flips_status_and_overwrites(self, flow_db):
        ctx = flow_db
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                          {"admission": "Y"})
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_b"],
                          {"admission": "N"})
        subs = get_submissions_for_sense(ctx["sense_a"], "admission")
        ids = sorted(s["id"] for s in subs)

        gold = {"admission": "EXT", "schema": "SOURCE_PATH", "needs_review": True}
        assert save_adjudication(ctx["sense_a"], "admission", ctx["reviewer"], gold,
                                 ids, "采纳扩展义判定") is True
        rows = get_submissions_for_sense(ctx["sense_a"], "admission")
        assert all(r["status"] == "adjudicated" for r in rows)

        # 仲裁后的提交退出分歧清单与信度口径（reliability 只统计 submitted）
        assert detect_disagreements("motion", "admission") == []

        # 重复仲裁 = 覆盖定稿（uq_adjudication 唯一），note/gold 更新
        gold2 = {"admission": "N", "schema": "SOURCE_PATH", "needs_review": False}
        assert save_adjudication(ctx["sense_a"], "admission", ctx["reviewer"], gold2,
                                 ids, "复核改判") is True
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT submission_ids, gold_payload, note, adjudicator_id "
                "FROM adjudications WHERE sense_id = %s AND task_type = %s",
                (ctx["sense_a"], "admission"),
            )
            row = cursor.fetchone()
        assert row is not None
        stored_ids = row["submission_ids"]
        if isinstance(stored_ids, str):
            stored_ids = json.loads(stored_ids)
        assert stored_ids == ids
        stored_gold = row["gold_payload"]
        if isinstance(stored_gold, str):
            stored_gold = json.loads(stored_gold)
        assert stored_gold == gold2
        assert row["note"] == "复核改判"

        # 覆盖更新后 status 重置 submitted，重新进入审核流
        assert submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                                 {"admission": "Y"}) is True
        mine = get_my_submissions(ctx["coder_a"], "motion", "admission")
        assert mine[0]["status"] == "submitted"

    def test_adjudication_nonexistent_sense_fk_rejected(self, flow_db):
        """R4 1c：sense_id 不存在（FK 拒绝）→ False，adjudications 无残留行。"""
        assert save_adjudication(99999999, "admission", flow_db["reviewer"],
                                 {"admission": "Y"}, [], None) is False
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM adjudications WHERE sense_id = %s",
                (99999999,),
            )
            assert cursor.fetchone()["n"] == 0

    def test_adjudication_unknown_submission_ids_tolerated(self, flow_db):
        """R4 1c：submission_ids 指向不存在的提交 → gold 照写（留痕）、不炸、
        无提交被翻转。页面传参恒来自 get_submissions_for_sense，此处固化
        数据层对陈旧 id 的宽容口径。"""
        ctx = flow_db
        assert save_adjudication(ctx["sense_a"], "admission", ctx["reviewer"],
                                 {"admission": "Y"}, [424242], None) is True
        assert get_submissions_for_sense(ctx["sense_a"], "admission") == []
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT submission_ids FROM adjudications WHERE sense_id = %s",
                (ctx["sense_a"],),
            )
            row = cursor.fetchone()
        assert row is not None
        stored = row["submission_ids"]
        if isinstance(stored, str):
            stored = json.loads(stored)
        assert stored == [424242]

    # --- 分配与统计 ---

    def test_assign_task_and_stats(self, flow_db):
        ctx = flow_db
        assert assign_task(ctx["coder_a"], "motion", "admission", ["run"], 1) is True
        assert assign_task(ctx["coder_a"], "motion", "feature_coding", None, 1) is True
        assert assign_task(999999, "motion", "admission", None, 1) is False  # FK 拒绝

        # alice 提交 2 条（1 admission + 1 feature_coding），bob 未分配自发 1 条
        submit_annotation("motion", ctx["sense_a"], "admission", ctx["coder_a"],
                          {"admission": "Y"})
        submit_annotation("motion", ctx["sense_a"], "feature_coding", ctx["coder_a"],
                          {"features": {"P1": 1}})
        submit_annotation("motion", ctx["sense_b"], "admission", ctx["coder_b"],
                          {"admission": "N"})

        stats = get_assignment_stats()
        keys = {(s["assignee_id"], s["category"], s["task_type"]): s for s in stats}
        alice_adm = keys[(ctx["coder_a"], "motion", "admission")]
        assert alice_adm["username"] == "alice"
        assert alice_adm["scope_verbs"] == ["run"]
        assert alice_adm["assignment_status"] == "open"
        assert alice_adm["n_submitted"] == 1
        alice_fc = keys[(ctx["coder_a"], "motion", "feature_coding")]
        assert alice_fc["scope_verbs"] is None           # NULL = 全部动词
        # bob 有提交但无分配 → 孤儿行
        bob_adm = keys[(ctx["coder_b"], "motion", "admission")]
        assert bob_adm["assignment_id"] is None
        assert bob_adm["n_submitted"] == 1
