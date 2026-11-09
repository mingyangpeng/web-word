"""FX32 批次修复测试：第 18 轮十镜头 review 第一波 findings（8 项）。

对应修复（reviewer 原文口径编号 → 本文件测试类）：

  * RV13-1 —— guards 口径表＋交互面专用闸（additive）：模块 docstring 新增
    「actor 语义口径表」（系统作业面 None 放行三族清单 vs 交互面），新增
    require_role_interactive（actor=None 直接拒绝、不读会话兜底；其余判定
    复用 require_role 单一实现）。既有三面契约不改造（test_guards 回归）。
  * RV13-2 —— 改派在册闸 TOCTOU：reassign_assignment 的 UPDATE 原子复验
    （WHERE 带 EXISTS(project_members×users 在册在用)），rowcount=0 重读归因
    （状态已推进 / 并发改派（含同值重放）/ 目标已失格 / 行删除）。
  * RV13-3 —— 重标派单不复核账号在用：create_reannotation_tasks 的 coder
    查询 JOIN users(u.active=1) 排除停用账号；docstring 如实声明「复核=
    账号在用；项目在册不可建立（assignments 无项目列）」的降级口径。
  * RV13-4 —— reassign_assignment docstring 第 4 道闸措辞降格（同项目在册闸
    → 调用方所选项目在册闸）。
  * RV13-5 —— 留痕执行人与 actor 一致性：reassigned_by/assigned_by 与
    actor["id"] 不一致拒绝（as_int 清洗后比对；actor=None 系统作业面不受限）。
  * RV14-1 —— 重标任务同轮幂等闸：落库前按 (category, task_type, assignee_id,
    round) 探测已存在行（round IS NOT NULL AND round=%s），存在即跳过，
    dedup 计入返回体；页面重复发起不再翻倍。
  * RV14-4 —— 迁移 1060 白名单：_migrate_assignments_round_columns /
    _ensure_divided_cols 的 ALTER 逐条捕 MySQL 1060（Duplicate column，并发
    首启第二进程）视为幂等成功；ensure_flow_tables 外层 1060 不再进
    「检查 users/oald_senses 是否已建」误导文案（单列分流）。
  * RV14-6 —— 改派并发 last-writer-wins：UPDATE WHERE 补 assignee_id 前值
    复验；同值重放归因文案「分派已被并发更新（含同值重放）」。
  * RV14-8 —— _parse_json_list 坏数据可区分：坏数据路径 logger.warning
    （scope 范围语义静默放大为全动词必须留痕），返回契约不变（None=全部动词）。

外部依赖隔离：
  * 假游标用例不连库（test_fx20_fixes 同款手法：SQL 子串路由 + rowcount
    控制 + 归因重读的次数态路由）；迁移 1060 用桩游标注入 pymysql 异常；
  * 真库用例（TestFx32RealDb）复用已授权测试库机制（web_word_fx32_test），
    MySQL 不可用/无建库权限整类 skip。
"""

import inspect
import json
import logging
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.annotation_flow as flow  # noqa: E402
import src.mysql_db as db  # noqa: E402
from src import guards  # noqa: E402
from src.annotation_flow import (  # noqa: E402
    _parse_json_list,
    create_reannotation_tasks,
    ensure_flow_tables,
    reassign_assignment,
)

TEST_DB = "web_word_fx32_test"

ADMIN_ACTOR = {"id": 1, "username": "admin", "roles": ["dict_admin"]}
LOW_ACTOR = {"id": 2, "username": "henchman", "roles": ["annotator"]}
NO_ID_ACTOR = {"username": "admin", "roles": ["dict_admin"]}  # RV13-5：缺 id 伪造组合


# ============================================
# 假游标基建（不连库：SQL 子串路由 + rowcount 控制）
# ============================================
class _Ctx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class FakeFx32Cursor:
    """按 SQL 子串分派的假游标（test_fx20_fixes.FakeFx20Cursor 同款变体）。

    select_routes / rowcount_routes 均按插入序首个命中生效；路由值可为
    (sql, params)->rows 的 callable（归因重读的「次数态」种子用）。
    """

    def __init__(self):
        self.executed = []
        self.select_routes = []
        self.rowcount_routes = []
        self.rowcount = 1
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.rowcount = 1
        self._result = []
        for substring, rc in self.rowcount_routes:
            if substring in sql:
                self.rowcount = rc
                return
        for substring, rows in self.select_routes:
            if substring in sql:
                self._result = rows(sql, params) if callable(rows) else list(rows)
                return

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _patch_plain(monkeypatch):
    cursor = FakeFx32Cursor()
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


def _flow_records(caplog):
    return [r for r in caplog.records if r.name == "src.annotation_flow"]


def _seed_assignment(cursor, status="open", assignee=7):
    cursor.select_routes.append(
        ("FROM assignments WHERE id",
         [{"id": 42, "assignee_id": assignee, "status": status,
           "category": "motion", "task_type": "feature_coding"}])
    )


def _seed_reannotation_happy(cursor, coder_rows=None):
    """重标闸 happy 种子：categories 直配、逐义位 merged、历史标注人、动词。"""
    cursor.select_routes.append(
        ("SELECT code FROM categories",
         lambda sql, params: [{"code": "RUN"}] if params[0] == "RUN" else [])
    )
    cursor.select_routes.append(
        ("JOIN cs_senses s", lambda sql, params: [{"cs_status": "merged"}])
    )
    cursor.select_routes.append(
        ("SELECT DISTINCT coder_id",
         coder_rows if coder_rows is not None else [{"coder_id": 5}, {"coder_id": 6}])
    )
    cursor.select_routes.append(
        ("SELECT DISTINCT headword", [{"headword": "run"}])
    )


# ============================================
# RV13-2 + RV14-6：改派原子复验与 0 行归因
# ============================================
class TestReassignAtomicRecheck:
    def test_update_sql_carries_atomic_recheck(self, monkeypatch):
        """UPDATE 文本形态：SET 双列；WHERE status + assignee_id 前值 + EXISTS 在册在用。"""
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is True
        update_sqls = [s for s, _ in cursor.executed if "UPDATE assignments" in s]
        assert len(update_sqls) == 1
        sql = update_sqls[0]
        assert "SET assignee_id = %s, assigned_by = %s" in sql      # RV14-6 审计前值
        assert "AND status = %s" in sql                              # 既有状态闸复验
        assert "AND assignee_id = %s" in sql                         # RV14-6 前值复验
        assert "AND EXISTS (SELECT 1 FROM project_members pm" in sql  # RV13-2 原子在册复验
        assert "u.active = 1" in sql
        # 参数序：(new_uid, by_id, aid, status, prev_assignee, pid, new_uid)
        _, params = next((s, p) for s, p in cursor.executed if "UPDATE assignments" in s)
        assert params == (9, 1, 42, "open", 7, 1, 9)

    def test_zero_rows_status_advanced(self, monkeypatch, caplog):
        """0 行归因①：读后状态被并发推进 → 如实点名新状态。"""
        cursor = _patch_plain(monkeypatch)
        reads = {"n": 0}

        def _assignment_rows(sql, params):
            reads["n"] += 1
            if reads["n"] == 1:  # 闸读：open 可改派
                return [{"id": 42, "assignee_id": 7, "status": "open",
                         "category": "motion", "task_type": "feature_coding"}]
            return [{"status": "in_progress", "assignee_id": 7}]  # 归因重读

        cursor.select_routes.append(("FROM assignments WHERE id", _assignment_rows))
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert any("状态已并发推进" in r.getMessage() and "in_progress" in r.getMessage()
                   for r in _flow_records(caplog))

    def test_zero_rows_concurrent_reassign_other_user(self, monkeypatch, caplog):
        """0 行归因②：承包人已被并发改派给第三者 → 未覆盖他人变更。"""
        cursor = _patch_plain(monkeypatch)
        reads = {"n": 0}

        def _assignment_rows(sql, params):
            reads["n"] += 1
            if reads["n"] == 1:
                return [{"id": 42, "assignee_id": 7, "status": "open",
                         "category": "motion", "task_type": "feature_coding"}]
            return [{"status": "open", "assignee_id": 8}]  # 7 → 8 被他人改派

        cursor.select_routes.append(("FROM assignments WHERE id", _assignment_rows))
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert any("承包人已被并发改派为 user 8" in r.getMessage()
                   for r in _flow_records(caplog))

    def test_zero_rows_same_value_replay(self, monkeypatch, caplog):
        """0 行归因③：同值重放（他人已完成本次改派）→ 文案如实（RV14-6）。"""
        cursor = _patch_plain(monkeypatch)
        reads = {"n": 0}

        def _assignment_rows(sql, params):
            reads["n"] += 1
            if reads["n"] == 1:
                return [{"id": 42, "assignee_id": 7, "status": "open",
                         "category": "motion", "task_type": "feature_coding"}]
            return [{"status": "open", "assignee_id": 9}]  # 已等于目标值

        cursor.select_routes.append(("FROM assignments WHERE id", _assignment_rows))
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert any("同值重放" in r.getMessage() for r in _flow_records(caplog))

    def test_zero_rows_target_lost_eligibility(self, monkeypatch, caplog):
        """0 行归因④：读后在册校验通过、写时目标已失格 → 与状态推进区分。"""
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        member_reads = {"n": 0}

        def _member_rows(sql, params):
            member_reads["n"] += 1
            return [{"n": 1}] if member_reads["n"] == 1 else [{"n": 0}]  # 写时失格

        cursor.select_routes.append(("FROM project_members pm", _member_rows))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert any("目标已失格" in r.getMessage() for r in _flow_records(caplog))
        assert not any("状态已并发推进" in r.getMessage() for r in _flow_records(caplog))

    def test_zero_rows_assignment_deleted(self, monkeypatch, caplog):
        """0 行归因⑤：重读无行（分派被并发删除）。"""
        cursor = _patch_plain(monkeypatch)
        reads = {"n": 0}

        def _assignment_rows(sql, params):
            reads["n"] += 1
            if reads["n"] == 1:
                return [{"id": 42, "assignee_id": 7, "status": "open",
                         "category": "motion", "task_type": "feature_coding"}]
            return []  # 归因重读：行已不在

        cursor.select_routes.append(("FROM assignments WHERE id", _assignment_rows))
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert any("分派不存在" in r.getMessage() for r in _flow_records(caplog))

    def test_zero_rows_fallback_when_reread_fails(self, monkeypatch, caplog):
        """0 行归因兜底：重读本身失败 → 文案退回「并发更新（含同值重放）」，不掩盖失败。"""
        cursor = _patch_plain(monkeypatch)
        reads = {"n": 0}

        def _assignment_rows(sql, params):
            reads["n"] += 1
            if reads["n"] == 1:
                return [{"id": 42, "assignee_id": 7, "status": "open",
                         "category": "motion", "task_type": "feature_coding"}]
            raise RuntimeError("fx32 fake re-read down")

        cursor.select_routes.append(("FROM assignments WHERE id", _assignment_rows))
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert any("分派已被并发更新（含同值重放）" in r.getMessage()
                   for r in _flow_records(caplog))


# ============================================
# RV13-5：留痕执行人与 actor 一致性
# ============================================
class TestProvenanceConsistency:
    def test_reassign_rejects_actor_without_id(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert reassign_assignment(42, 1, 9, 1, actor=NO_ID_ACTOR) is False
        assert cursor.executed == []  # 入口先拒，不触库

    def test_reassign_rejects_foreign_reassigned_by(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert reassign_assignment(42, 1, 9, 9, actor=ADMIN_ACTOR) is False  # actor id=1
        assert cursor.executed == []

    def test_reassign_accepts_string_id_after_as_int(self, monkeypatch):
        """as_int 清洗后比对：actor id 为整数串 "1" 与 reassigned_by=1 一致放行。"""
        cursor = _patch_plain(monkeypatch)
        actor = {"id": "1", "username": "admin", "roles": ["dict_admin"]}
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        assert reassign_assignment(42, 1, 9, 1, actor=actor) is True

    def test_reassign_actor_none_is_system_job(self, monkeypatch):
        """actor=None 系统作业面不受留痕一致性限（此时入参即留痕来源）。"""
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        assert reassign_assignment(42, 1, 9, 77, actor=None) is True

    def test_reannotation_rejects_mismatch(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        result = create_reannotation_tasks("motion", [101], 1, 9, actor=ADMIN_ACTOR)
        assert result["ok"] is False
        assert "留痕只能是自己" in result["error"]
        assert cursor.executed == []

    def test_reannotation_rejects_actor_without_id(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=NO_ID_ACTOR)
        assert result["ok"] is False
        assert cursor.executed == []

    def test_reannotation_actor_none_unrestricted(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        result = create_reannotation_tasks("motion", [101], 1, 77, actor=None)
        assert result["ok"] is True
        assert result["created"] == 2  # 种子标注人 5/6 各一条，assigned_by=77 如实留痕
        assert all(p[4] == 77 for s, p in cursor.executed
                   if "INSERT INTO assignments" in s)


# ============================================
# RV13-4：docstring 措辞降格 + RV13-3 口径声明
# ============================================
class TestDocstringHonesty:
    @staticmethod
    def _flat(fn):
        """docstring 去空白断言面（中文短语换行折叠，措辞本身逐字保留）。"""
        import re

        return re.sub(r"\s+", "", inspect.getdoc(fn) or "")

    def test_reassign_gate4_downgraded_wording(self):
        doc = self._flat(flow.reassign_assignment)
        assert "调用方所选项目在册闸" in doc
        assert "「任务所属项目」语义待阶段2补列后建立" in doc
        assert "dict_admin全局可信角色下风险有界" in doc
        # 旧措辞不得回潮
        assert "同项目在册闸：new_assignee须在project_members(project_id)在册" not in doc

    def test_reassign_docstring_documents_new_gates(self):
        doc = self._flat(flow.reassign_assignment)
        assert "原子并发守卫" in doc            # RV13-2/RV14-6
        assert "留痕一致性" in doc              # RV13-5
        assert "同值重放" in doc

    def test_reannotation_docstring_declares_degraded_scope(self):
        doc = self._flat(flow.create_reannotation_tasks)
        assert "项目在册不可建立" in doc          # assignments 无项目列的如实声明
        assert "账号在用" in doc                  # RV13-3 复核口径
        assert "同轮幂等闸" in doc                # RV14-1
        assert "留痕一致性" in doc                # RV13-5


# ============================================
# RV13-3：重标派单复核账号在用
# ============================================
class TestReannotationCoderActiveJoin:
    def test_coder_query_joins_active_users(self, monkeypatch):
        """coder 查询带 JOIN users(u.active=1)：停用账号在 SQL 层排除。"""
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True
        coder_sqls = [s for s, _ in cursor.executed if "SELECT DISTINCT coder_id" in s]
        assert len(coder_sqls) == 1
        assert "JOIN users u ON u.id = coder_id AND u.active = 1" in coder_sqls[0]

    def test_active_rows_still_flow_through(self, monkeypatch):
        """在用账号行照常建任务（JOIN 只过滤，不改变返回形态）。"""
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["coder_ids"] == [5, 6]
        assert result["created"] == 2


# ============================================
# RV14-1：重标任务同轮幂等闸
# ============================================
class TestReannotationRoundDedup:
    def test_probe_sql_shape(self, monkeypatch):
        """探测 SQL 形态：round IS NOT NULL AND round=%s（NULL 正式轮行不受影响）。"""
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        probes = [s for s, _ in cursor.executed
                  if "SELECT DISTINCT assignee_id FROM assignments" in s]
        assert len(probes) == 1
        assert "`round` IS NOT NULL AND `round` = %s" in probes[0]
        assert "assignee_id IN" in probes[0]

    def test_duplicate_coder_skipped_and_counted(self, monkeypatch):
        """coder 5 本轮任务已存在 → 跳过计 dedup，coder 6 照常建。"""
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        cursor.select_routes.append(
            ("`round` IS NOT NULL",
             lambda sql, params: [{"assignee_id": 5}] if params[2] == 5 else [])
        )
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True
        assert result["created"] == 1
        assert result["dedup"] == 1
        assert result["failed_coder_ids"] == []
        assert result["coder_ids"] == [5, 6]
        assert "幂等跳过" in (result["note"] or "")
        inserts = [p for s, p in cursor.executed if "INSERT INTO assignments" in s]
        assert len(inserts) == 1
        assert inserts[0][0] == 6  # 只给 coder 6 建任务

    def test_all_duplicates_create_nothing(self, monkeypatch):
        """全员已有同轮行 → created=0、dedup=2、零 INSERT（重复发起不翻倍）。"""
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        cursor.select_routes.append(
            ("`round` IS NOT NULL",
             lambda sql, params: [{"assignee_id": c["coder_id"]}
                                  for c in ({"coder_id": 5}, {"coder_id": 6})])
        )
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True
        assert result["created"] == 0
        assert result["dedup"] == 2
        assert not [s for s, _ in cursor.executed if "INSERT INTO assignments" in s]

    def test_no_dedup_when_probe_empty(self, monkeypatch):
        """探测无命中 → dedup=0，行为与修复前一致（created=2）。"""
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["created"] == 2 and result["dedup"] == 0
        assert result["note"] is None

    def test_no_coder_return_carries_dedup_key(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor, coder_rows=[])
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True and result["created"] == 0
        assert result["dedup"] == 0


# ============================================
# RV14-4：迁移 1060 白名单（幂等自愈 + 文案分流）
# ============================================
class _DupColAlterCursor:
    """桩游标：information_schema 探测按 existing 供行；ALTER 注入指定异常。"""

    def __init__(self, existing=(), alter_exc=None):
        self.executed = []
        self.existing = set(existing)
        self.alter_exc = alter_exc
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.lstrip().startswith("ALTER TABLE"):
            if self.alter_exc is not None:
                raise self.alter_exc
            return
        if "information_schema.COLUMNS" in sql:
            table, column = params
            self._result = [{"n": 1 if (table, column) in self.existing else 0}]
            return
        self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _dup_col_error():
    return pymysql.err.InternalError(1060, "Duplicate column name 'round'")


class TestMigration1060Whitelist:
    def test_round_columns_1060_self_heals_and_continues(self, caplog):
        """ALTER 撞 1060（并发首启第二进程）→ 幂等成功继续探测下一列，不抛。"""
        cursor = _DupColAlterCursor(existing=(), alter_exc=_dup_col_error())
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            flow._migrate_assignments_round_columns(cursor)  # 不应 raise
        alters = [s for s, _ in cursor.executed if s.startswith("ALTER TABLE")]
        assert len(alters) == 2  # 第一列 1060 自愈后第二列照常尝试
        probes = [s for s, _ in cursor.executed if "information_schema.COLUMNS" in s]
        assert len(probes) == 2
        assert any("1060" in r.getMessage() and "幂等自愈" in r.getMessage()
                   for r in _flow_records(caplog))

    def test_round_columns_non_1060_propagates(self):
        """非 1060 的迁移错误照旧向上抛（外层容错面不扩大白名单）。"""
        cursor = _DupColAlterCursor(
            existing=(),
            alter_exc=pymysql.err.OperationalError(1054, "Unknown column 'round'"),
        )
        with pytest.raises(pymysql.err.OperationalError):
            flow._migrate_assignments_round_columns(cursor)

    def test_ensure_flow_tables_1060_not_misattributed(self, monkeypatch, caplog):
        """外层 1060 单列分流：不进「检查 users/oald_senses 是否已建」误导文案。"""

        def _boom(cursor):
            raise _dup_col_error()

        monkeypatch.setattr(flow, "_migrate_assignments_round_columns", _boom)
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(_DupColAlterCursor()))
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            ensure_flow_tables()  # 不应 raise
        records = _flow_records(caplog)
        assert not any("users/oald_senses" in r.getMessage() for r in records)
        assert any("1060" in r.getMessage() for r in records)

    def test_ensure_flow_tables_non_1060_keeps_existing_message(self, monkeypatch, caplog):
        """非 1060 错误保留既有归因文案（被引用表缺失的修复提示不丢）。"""

        def _boom(cursor):
            raise pymysql.err.OperationalError(1045, "Access denied")

        monkeypatch.setattr(flow, "_migrate_assignments_round_columns", _boom)
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(_DupColAlterCursor()))
        with caplog.at_level(logging.ERROR, logger="src.annotation_flow"):
            ensure_flow_tables()
        records = _flow_records(caplog)
        assert any("检查 users/oald_senses 是否已建" in r.getMessage() for r in records)

    def test_divided_cols_1060_self_heal_sets_sentinel(self, monkeypatch, caplog):
        """_ensure_divided_cols ALTER 撞 1060 → 幂等成功置哨兵（同款处理）。"""
        monkeypatch.setattr(flow, "_DIVIDED_COLS_ENSURED", False)
        cursor = _DupColAlterCursor(
            existing=(),
            alter_exc=pymysql.err.InternalError(
                1060, "Duplicate column name 'merged_into'"),
        )
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            flow._ensure_divided_cols()  # 不应 raise
        assert flow._DIVIDED_COLS_ENSURED is True
        assert any("1060" in r.getMessage() for r in _flow_records(caplog))
        # 哨兵直通：二次调用不再触库
        cursor2 = _DupColAlterCursor(existing=(), alter_exc=_dup_col_error())
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor2))
        flow._ensure_divided_cols()
        assert cursor2.executed == []

    def test_divided_cols_non_1060_keeps_degradation(self, monkeypatch, caplog):
        """非 1060 错误照旧降级（哨兵不置位，查询路径容错不变）。"""
        monkeypatch.setattr(flow, "_DIVIDED_COLS_ENSURED", False)
        cursor = _DupColAlterCursor(
            existing=(),
            alter_exc=pymysql.err.OperationalError(1054, "Unknown column"),
        )
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
        with caplog.at_level(logging.WARNING, logger="src.annotation_flow"):
            flow._ensure_divided_cols()
        assert flow._DIVIDED_COLS_ENSURED is False
        assert any("迁移探测失败" in r.getMessage() for r in _flow_records(caplog))


# ============================================
# RV14-8：_parse_json_list 坏数据可区分（warning 留痕，契约不变）
# ============================================
class TestParseJsonListBadDataWarning:
    def test_contract_unchanged(self):
        """None=全部动词契约保持：各坏数据路径仍返回 None、合法路径不变。"""
        assert _parse_json_list(None) is None
        assert _parse_json_list(["run"]) == ["run"]
        assert _parse_json_list(("run", "walk")) == ["run", "walk"]
        assert _parse_json_list('["run"]') == ["run"]
        assert _parse_json_list('{"a":1}') is None       # JSON 非 list
        assert _parse_json_list("不是JSON") is None       # 非法 JSON
        assert _parse_json_list(b"\xff\xfe") is None     # UTF-8 解码失败
        assert _parse_json_list(42) is None              # 非字符串类型

    def test_bad_paths_each_warn_once(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.annotation_flow"):
            _parse_json_list("不是JSON")
            _parse_json_list('{"a":1}')
            _parse_json_list(b"\xff\xfe")
            _parse_json_list(42)
        messages = [r.getMessage() for r in _flow_records(caplog)]
        assert len(messages) == 4  # 每条坏路径恰好一次，静默放大不再无声
        assert all("静默放大为全部动词" in m for m in messages)

    def test_good_paths_stay_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.annotation_flow"):
            _parse_json_list(None)
            _parse_json_list(["run"])
            _parse_json_list('["run"]')
        assert _flow_records(caplog) == []


# ============================================
# RV13-1：guards 交互面专用闸（additive）
# ============================================
GUARD_DICT_ADMIN = {"id": 1, "username": "da", "role": "viewer", "roles": ["dict_admin"]}
GUARD_VIEWER = {"id": 5, "username": "vw", "role": "viewer", "roles": ["viewer"]}


class TestRequireRoleInteractive:
    def test_none_rejected_even_when_session_has_user(self, monkeypatch):
        """actor=None 直接拒绝、不读会话兜底（与 require_role 的分界）。"""
        monkeypatch.setattr(guards.st, "session_state", {"user": dict(GUARD_DICT_ADMIN)})
        with pytest.raises(PermissionError) as ei:
            guards.require_role_interactive(None, allowed={"dict_admin"}, action="改派分派")
        assert "会话用户" in str(ei.value)

    def test_none_direct_vs_require_role_session_fallback(self, monkeypatch):
        """对照：同一注入会话下 require_role(None) 走会话放行（既有契约不动），
        interactive 拒 —— 两族语义并存且可区分。"""
        monkeypatch.setattr(guards.st, "session_state", {"user": dict(GUARD_DICT_ADMIN)})
        assert guards.require_role(None, allowed={"dict_admin"}, action="x") is not None
        with pytest.raises(PermissionError):
            guards.require_role_interactive(None, allowed={"dict_admin"}, action="x")

    def test_low_privilege_rejected(self):
        with pytest.raises(PermissionError) as ei:
            guards.require_role_interactive(
                GUARD_VIEWER, allowed={"dict_admin"}, action="改派分派")
        assert "仅词典管理员" in str(ei.value)

    def test_allowed_actor_passes_and_returns_actor(self):
        user = dict(GUARD_DICT_ADMIN)
        assert guards.require_role_interactive(
            user, allowed={"dict_admin", "sys_admin"}, action="改派分派") is user

    def test_empty_allowed_fail_closed(self):
        for bad_allowed in (set(), None, []):
            with pytest.raises(PermissionError):
                guards.require_role_interactive(
                    GUARD_DICT_ADMIN, allowed=bad_allowed, action="x 操作")

    def test_non_dict_rejected(self):
        for bad in ("admin", 42, ["dict_admin"]):
            with pytest.raises(PermissionError):
                guards.require_role_interactive(bad, allowed={"dict_admin"}, action="x")

    def test_actor_semantics_table_in_module_docstring(self):
        """口径表落位：两族清单 + 纪律声明（新交互面一律用 interactive）。"""
        doc = guards.__doc__ or ""
        assert "actor 语义口径表" in doc
        for family_member in ("style_check", "annotation_flow", "broadcast_db"):
            assert family_member in doc
        assert "require_role_interactive" in doc
        assert "一律用" in doc

    def test_existing_gates_untouched(self):
        """additive：require_role / require_dict_admin 签名与既有契约不回溯改造。"""
        sig = inspect.signature(guards.require_role)
        assert list(sig.parameters) == ["actor", "allowed", "action"]
        with pytest.raises(PermissionError):
            guards.require_role(GUARD_VIEWER, allowed={"dict_admin"}, action="x")
        assert guards.require_dict_admin(GUARD_DICT_ADMIN) is GUARD_DICT_ADMIN


# ============================================
# 集成测试：真实 MySQL（无环境则整类 skip）
# ============================================
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


# RV13-2/RV14-6 的 UPDATE 原子复验语句（与被测实现逐字同形，真库直验 rowcount 语义）
_REASSIGN_UPDATE_SQL = (
    "UPDATE assignments SET assignee_id = %s, assigned_by = %s "
    "WHERE id = %s AND status = %s AND assignee_id = %s "
    "AND EXISTS ("
    "SELECT 1 FROM project_members pm "
    "JOIN users u ON u.id = pm.user_id "
    "WHERE pm.project_id = %s AND pm.user_id = %s AND u.active = 1)"
)


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX32 集成测试")
class TestFx32RealDb:
    """重标幂等 / 停用账号排除 / 改派原子复验跑在真实 MySQL 8.0。"""

    @pytest.fixture
    def fx32_db(self, monkeypatch):
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
            cur.execute(f"USE {TEST_DB}")
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX32 集成测试: {e}")
        conn.commit()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        db._register_category_study_tables()
        db._register_zh_dict_tables()
        for table_sql in db.CREATE_TABLES_SQL:
            cur.execute(table_sql)
        conn.commit()
        conn.close()

        from src.org_db import add_member, create_project, ensure_org_tables
        from src.users_db import create_user, ensure_user_tables

        ensure_user_tables()
        ensure_org_tables()
        ensure_flow_tables()

        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
                "VALUES (%s, %s, %s)",
                ("run", "跑", json.dumps({"manner": "x"})),
            )
            definition_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO oald_senses (definition_id, sense_index, definition, "
                "headword) VALUES (%s, %s, %s, %s)",
                (definition_id, 1, "to move fast on foot", "run"),
            )
            sense_a = cursor.lastrowid
            cursor.execute(
                "INSERT INTO categories (code, name_cn, name_en) VALUES (%s, %s, %s)",
                ("RUN", "跑", "Run"),
            )
            category_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO cs_lexemes (category_id, language, lemma, source_dict) "
                "VALUES (%s, %s, %s, %s)",
                (category_id, "en", "run", "OALD10"),
            )
            lexeme_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO cs_senses (lexeme_id, sense_no, sense_label, status) "
                "VALUES (%s, %s, %s, %s)",
                (lexeme_id, "1", "足部奔跑义", "merged"),
            )

        coder_a = create_user("alice", "pw123456", "爱丽丝", "annotator")
        coder_b = create_user("bob", "pw123456", "鲍勃", "annotator")
        coder_c = create_user("carol", "pw123456", "卡罗尔", "annotator")
        project_id = create_project("FX32 项目", 1, ["motion"])
        assert project_id
        for coder in (coder_a, coder_b, coder_c):
            assert add_member(project_id, coder, "annotator", 1)
        assert flow.submit_annotation("motion", sense_a, "feature_coding",
                                      coder_a, {"features": {"P1": 1}})
        assert flow.submit_annotation("motion", sense_a, "feature_coding",
                                      coder_c, {"features": {"P1": 0}})

        yield {
            "admin_id": 1,
            "project_id": project_id,
            "coder_a": coder_a,
            "coder_b": coder_b,
            "coder_c": coder_c,
            "sense_a": sense_a,
        }

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

    def test_reannotation_double_launch_dedup(self, fx32_db):
        """RV14-1：同批两次发起 → 第二次 created=0、dedup 正确、库不翻倍。"""
        ctx = fx32_db
        first = create_reannotation_tasks(
            "motion", [ctx["sense_a"]], 1, ctx["admin_id"], actor=ADMIN_ACTOR)
        assert first["ok"] is True
        # 夹具：sense_a 有两名在册历史标注人（coder_a/coder_c）→ 首次建 2 条
        assert first["created"] == 2 and first["dedup"] == 0
        second = create_reannotation_tasks(
            "motion", [ctx["sense_a"]], 1, ctx["admin_id"], actor=ADMIN_ACTOR)
        assert second["ok"] is True
        assert second["created"] == 0 and second["dedup"] == 2
        assert "幂等跳过" in (second["note"] or "")
        rows = _q(
            "SELECT assignee_id, `round` FROM assignments "
            "WHERE category = 'motion' AND task_type = 'feature_coding' AND `round` = 2"
        )
        assert len(rows) == 2  # 库内恰两名标注人各一条 round=2 任务（不翻倍）

    def test_reannotation_excludes_deactivated_coder(self, fx32_db):
        """RV13-3：停用账号不接重标单（coder_c 有历史提交但已停用）。"""
        from src.users_db import set_active

        ctx = fx32_db
        assert set_active(ctx["coder_c"], False) is True
        result = create_reannotation_tasks(
            "motion", [ctx["sense_a"]], 1, ctx["admin_id"], actor=ADMIN_ACTOR)
        assert result["ok"] is True
        assert result["coder_ids"] == [ctx["coder_a"]]  # 停用的 coder_c 被排除
        assert result["created"] == 1

    def test_reassign_atomic_recheck_rowcount_semantics(self, fx32_db):
        """RV13-2/RV14-6 真库直验：前值不符 / 目标停用 → 0 行；匹配 → 1 行。"""
        from src.users_db import set_active

        ctx = fx32_db
        assert flow.assign_task(ctx["coder_b"], "motion", "admission", None,
                                ctx["admin_id"]) is True
        aid = _q("SELECT id, assignee_id FROM assignments ORDER BY id DESC LIMIT 1")[0]["id"]

        # 前值复验：prev 与库内不符 → 0 行（并发写不被静默覆盖）
        with db.get_db_cursor() as cursor:
            cursor.execute(_REASSIGN_UPDATE_SQL,
                           (ctx["coder_a"], ctx["admin_id"], aid, "open",
                            999999, ctx["project_id"], ctx["coder_a"]))
            assert cursor.rowcount == 0
        assert _q("SELECT assignee_id FROM assignments WHERE id = %s",
                  (aid,))[0]["assignee_id"] == ctx["coder_b"]

        # EXISTS 在册在用复验：新承包人被停用 → 0 行（在册闸与写库原子）
        assert set_active(ctx["coder_a"], False) is True
        with db.get_db_cursor() as cursor:
            cursor.execute(_REASSIGN_UPDATE_SQL,
                           (ctx["coder_a"], ctx["admin_id"], aid, "open",
                            ctx["coder_b"], ctx["project_id"], ctx["coder_a"]))
            assert cursor.rowcount == 0
        assert _q("SELECT assignee_id FROM assignments WHERE id = %s",
                  (aid,))[0]["assignee_id"] == ctx["coder_b"]

        # 三重复验全命中 → 1 行（复验启用户后）
        assert set_active(ctx["coder_a"], True) is True
        with db.get_db_cursor() as cursor:
            cursor.execute(_REASSIGN_UPDATE_SQL,
                           (ctx["coder_a"], ctx["admin_id"], aid, "open",
                            ctx["coder_b"], ctx["project_id"], ctx["coder_a"]))
            assert cursor.rowcount == 1
        row = _q("SELECT assignee_id, assigned_by FROM assignments WHERE id = %s",
                 (aid,))[0]
        assert row["assignee_id"] == ctx["coder_a"]
        assert row["assigned_by"] == ctx["admin_id"]  # SET assigned_by 同步执行人
