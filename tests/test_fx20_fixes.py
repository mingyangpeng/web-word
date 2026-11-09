"""FX20 批次修复测试：规范×实现对账 ①组（改派 / 试标轮两列 / G2 重标闭环）。

对应修复（FX-20，仓库 RV 对账清单 ①组三项）：

  * assignments 试标轮两列 —— round INT NULL / training TINYINT(1) NULL
    DEFAULT NULL（ALTER-only 幂等迁移：column_exists 探测→ADD COLUMN，照
    media_db R3-4a 先例；NULL 口径遵循 RV2-3「留痕列 NULL 口径」——未设轮次
    =NULL，不用 0 冒充）；assign_task 增可选 keyword round/training（默认
    None 不破坏既有调用），get_assignment_stats / list_assignments_admin 带
    出两列；
  * 改派入口 —— reassign_assignment：状态闸（规范 §8「改派仅限
    draft/rejected」以码为准：assignments 实际枚举 open/in_progress/submitted/
    closed 无 draft/rejected 字面值，映射 draft≈open，in_progress/submitted/
    closed 一律拒绝）＋ 非现承包人闸 ＋ 同项目在册在用成员闸
    （project_members 校验）＋ 乐观并发守卫 ＋ actor 权限直调面
    （dict_admin/sys_admin，同 save_adjudication 家族口径）＋ 审计日志；
  * G2「修订→重标」闭环 —— create_reannotation_tasks：逐义位把标注侧
    sense_id（oald_senses.id）映射 cs_senses 核对分立裁决（仅 merged/split
    可发），任务建于 round+1、派给历史标注人、旧轮提交保留作历史；
    list_divided_senses 提供已裁决证据面；页面入口在 dict_admin_pages
    任务分配 tab 补充段 _render_assign_ops_tab（改派/试标轮分派/发起重标/
    分派台账轮次徽章，成功反馈一律 ui_kit.flash + st.rerun）。

外部依赖隔离：
  * 假游标用例不连库：monkeypatch annotation_flow.get_db_cursor，按 SQL
    子串分派种子行/行数（test_annotation_flow 同款手法的 FX-20 变体，
    rowcount 可按路由控制以测乐观并发守卫）；
  * 真库用例（TestFx20RealDb）复用已授权测试库机制（web_word_fx20_test，
    独立库名不与 stage1/stage2 e2e 与 web_word_flow_test 冲突；pytest 顺序
    执行下各自 DROP+CREATE 互不污染），MySQL 不可用/无建库权限整类 skip。
"""

import inspect
import json
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.annotation_flow as flow  # noqa: E402
import src.dict_admin_pages as dp  # noqa: E402
import src.mysql_db as db  # noqa: E402
from src.annotation_flow import (  # noqa: E402
    ASSIGNMENTS_ROUND_COLUMNS,
    ASSIGNMENT_STATUSES,
    REASSIGNABLE_ASSIGNMENT_STATUSES,
    assign_task,
    create_reannotation_tasks,
    ensure_flow_tables,
    get_assignment_stats,
    list_assignments_admin,
    list_divided_senses,
    reassign_assignment,
)

TEST_DB = "web_word_fx20_test"


# ============================================
# 假游标基建（不连库：按 SQL 子串分派 + rowcount 路由）
# ============================================
class _Ctx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class FakeFx20Cursor:
    """按 SQL 子串分派的假游标（test_annotation_flow.FakeFlowCursor 变体）。

    select_routes: [(子串, 行列表或 callable(sql, params)->行)] —— SELECT 种子；
    rowcount_routes: [(子串, rowcount)] —— UPDATE/INSERT 行数（乐观守卫用）；
    两者都未命中时 rowcount=1、结果空（默认写成功路径）。
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


def _patch(monkeypatch, existing_columns=()):
    """annotation_flow.get_db_cursor → 假游标；information_schema 探测按
    existing_columns（(table, column) 集合）供行 —— 迁移幂等测试用。"""
    cursor = FakeFx20Cursor()
    existing = set(existing_columns)

    def _probe(sql, params):
        table, column = params
        return [{"n": 1 if (table, column) in existing else 0}]

    cursor.select_routes.append(("information_schema.COLUMNS", _probe))
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


def _patch_plain(monkeypatch):
    """同 _patch，但不带 information_schema 路由（非迁移用例）。"""
    cursor = FakeFx20Cursor()
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


ADMIN_ACTOR = {"username": "admin", "roles": ["dict_admin"]}
LOW_ACTOR = {"username": "henchman", "roles": ["annotator"]}


# ============================================
# 1) 试标轮两列：ALTER-only 幂等迁移
# ============================================
class TestMigrateRoundColumns:
    def test_column_pairs_shape(self):
        assert [c for c, _ in ASSIGNMENTS_ROUND_COLUMNS] == ["round", "training"]
        for _, sql in ASSIGNMENTS_ROUND_COLUMNS:
            assert sql.startswith("ALTER TABLE assignments ADD COLUMN")

    def test_missing_columns_emit_alter(self, monkeypatch):
        cursor = _patch(monkeypatch, existing_columns=())
        ensure_flow_tables()
        sqls = [sql for sql, _ in cursor.executed]
        creates = [s for s in sqls if s.startswith("CREATE TABLE")]
        alters = [s for s in sqls if s.startswith("ALTER TABLE assignments ADD COLUMN")]
        assert len(creates) == 3  # 三表 DDL 照旧
        assert len(alters) == 2
        assert alters[0] == ASSIGNMENTS_ROUND_COLUMNS[0][1]
        assert alters[1] == ASSIGNMENTS_ROUND_COLUMNS[1][1]
        # ALTER 只在建表之后（存量库/新库同一条路径）
        assert sqls.index(alters[0]) > sqls.index(creates[-1])

    def test_idempotent_second_run_no_alter(self, monkeypatch):
        # 二次执行不炸不重复加列：探测命中即跳过（幂等核心断言）
        cols = {("assignments", c) for c, _ in ASSIGNMENTS_ROUND_COLUMNS}
        cursor = _patch(monkeypatch, existing_columns=cols)
        ensure_flow_tables()
        ensure_flow_tables()
        alters = [s for s, _ in cursor.executed if s.startswith("ALTER TABLE")]
        assert alters == []

    def test_migration_direct_callable(self, monkeypatch):
        cursor = _patch(monkeypatch, existing_columns=())
        flow._migrate_assignments_round_columns(cursor)
        # 每列 = 1 探测 SELECT + 1 ALTER；缺失态共 2 条 ALTER
        alters = [s for s, _ in cursor.executed if s.startswith("ALTER TABLE")]
        assert len(alters) == 2
        # 幂等：换「列已存在」桩再跑——探测命中，零 ALTER（真实库 information_schema
        # 是活的，同库二次执行即此形态；桩静态快照无法单游标模拟，故换桩）
        cursor2 = _patch(monkeypatch, existing_columns={("assignments", c) for c, _ in ASSIGNMENTS_ROUND_COLUMNS})
        flow._migrate_assignments_round_columns(cursor2)
        assert [s for s, _ in cursor2.executed if s.startswith("ALTER TABLE")] == []


# ============================================
# 2) assign_task 可选 round/training 参数
# ============================================
class TestAssignTaskRoundTraining:
    def _insert_params(self, cursor):
        sql, params = cursor.executed[-1]
        assert "INSERT INTO assignments" in sql
        assert "`round`" in sql and "training" in sql
        return params

    def test_round_training_captured(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert assign_task(7, "motion", "feature_coding", ["run"], 1,
                           round=2, training=True) is True
        params = self._insert_params(cursor)
        assert params[5] == 2      # round
        assert params[6] == 1      # training True → 1
        assert json.loads(params[3]) == ["run"]

    def test_training_false_stored_0(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert assign_task(7, "motion", "admission", None, 1,
                           round=1, training=False) is True
        params = self._insert_params(cursor)
        assert params[5] == 1 and params[6] == 0

    def test_defaults_none_preserve_legacy_calls(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert assign_task(7, "motion", "admission", None, 1) is True
        params = self._insert_params(cursor)
        # RV2-3：未设轮次/试标位 = NULL，不用 0 冒充
        assert params[5] is None and params[6] is None

    @pytest.mark.parametrize("bad_round", [0, -1, "2", 1.5, True])
    def test_invalid_round_rejected(self, monkeypatch, bad_round):
        cursor = _patch_plain(monkeypatch)
        assert assign_task(7, "motion", "admission", None, 1,
                           round=bad_round) is False
        assert cursor.executed == []

    def test_numeric_string_id_is_cleaned_not_rejected(self, monkeypatch):
        """整数串 id 按 as_int 口径合法清洗（"42"→42），走查询路径非参数拒绝。"""
        cursor = _patch_plain(monkeypatch)
        assert reassign_assignment("42", 1, 9, 1, actor=ADMIN_ACTOR) is False  # 桩空行→拒绝
        assert any("FROM assignments" in s for s, _ in cursor.executed)  # 入口先拒，不落库

    @pytest.mark.parametrize("bad_training", ["yes", 1, 0])
    def test_invalid_training_rejected(self, monkeypatch, bad_training):
        cursor = _patch_plain(monkeypatch)
        assert assign_task(7, "motion", "admission", None, 1,
                           training=bad_training) is False
        assert cursor.executed == []


# ============================================
# 3) 改派：状态闸 / 成员校验 / 同人闸 / 乐观守卫 / 权限直调面
# ============================================
def _seed_assignment(cursor, status="open", assignee=7):
    cursor.select_routes.append(
        ("FROM assignments WHERE id",
         [{"id": 42, "assignee_id": assignee, "status": status,
           "category": "motion", "task_type": "feature_coding"}])
    )


class TestReassignAssignment:
    def test_open_assignment_reassigned(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(
            ("FROM project_members pm", [{"n": 1}])
        )
        assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is True
        update = [p for s, p in cursor.executed if "UPDATE assignments" in s]
        assert update == [(9, 42, "open")]  # 乐观守卫 WHERE status 复验

    @pytest.mark.parametrize("status", ["in_progress", "submitted", "closed"])
    def test_status_gate_rejects(self, monkeypatch, status):
        # active/accepted 家族状态拒绝改派（规范 draft/rejected 以码为准映射）
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status=status, assignee=7)
        assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert not [s for s, _ in cursor.executed if "UPDATE assignments" in s]

    def test_reassignable_constant_open_only(self):
        assert REASSIGNABLE_ASSIGNMENT_STATUSES == ("open",)
        assert set(REASSIGNABLE_ASSIGNMENT_STATUSES) <= set(ASSIGNMENT_STATUSES)

    def test_same_assignee_rejected(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=9)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert not [s for s, _ in cursor.executed if "UPDATE assignments" in s]

    def test_target_not_project_member_rejected(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 0}]))
        assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert not [s for s, _ in cursor.executed if "UPDATE assignments" in s]

    def test_missing_assignment_rejected(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)  # 无种子 → fetchone None
        assert reassign_assignment(999, 1, 9, 1, actor=ADMIN_ACTOR) is False

    def test_optimistic_guard_rowcount_zero(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        cursor.rowcount_routes.append(("UPDATE assignments SET assignee_id", 0))
        assert reassign_assignment(42, 1, 9, 1, actor=ADMIN_ACTOR) is False

    @pytest.mark.parametrize("bad", [0, -1, None, True])
    def test_invalid_ids_rejected(self, monkeypatch, bad):
        cursor = _patch_plain(monkeypatch)
        assert reassign_assignment(bad, 1, 9, 1, actor=ADMIN_ACTOR) is False
        assert reassign_assignment(42, bad, 9, 1, actor=ADMIN_ACTOR) is False
        assert reassign_assignment(42, 1, bad, 1, actor=ADMIN_ACTOR) is False
        assert reassign_assignment(42, 1, 9, bad, actor=ADMIN_ACTOR) is False
        assert cursor.executed == []

    def test_actor_low_privilege_raises(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        with pytest.raises(PermissionError):
            reassign_assignment(42, 1, 9, 1, actor=LOW_ACTOR)
        with pytest.raises(PermissionError):
            reassign_assignment(42, 1, 9, 1, actor="junk")
        assert cursor.executed == []  # 抛在入口，未触库

    def test_actor_none_is_system_job(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_assignment(cursor, status="open", assignee=7)
        cursor.select_routes.append(("FROM project_members pm", [{"n": 1}]))
        assert reassign_assignment(42, 1, 9, 1, actor=None) is True


# ============================================
# 4) 重标闭环：round+1 / 裁决闸 / 历史标注人
# ============================================
def _seed_reannotation_happy(cursor, cs_status_by_sense=None):
    """重标闸的种子路由：categories 直配/映射、逐义位裁决、历史标注人、动词。"""
    cs_status_by_sense = cs_status_by_sense or {}
    cursor.select_routes.append(
        ("SELECT code FROM categories",
         lambda sql, params: [{"code": "RUN"}] if params[0] == "RUN" else [])
    )

    def _cs_status(sql, params):
        study_code, sense_id = params
        return [{"cs_status": cs_status_by_sense.get(sense_id, "merged")}]

    cursor.select_routes.append(("JOIN cs_senses s", _cs_status))
    cursor.select_routes.append(
        ("SELECT DISTINCT coder_id", [{"coder_id": 5}, {"coder_id": 6}])
    )
    cursor.select_routes.append(("SELECT DISTINCT headword", [{"headword": "run"}]))


class TestCreateReannotationTasks:
    def test_creates_tasks_at_round_plus_one(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        result = create_reannotation_tasks(
            "motion", [101, 102], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True
        assert result["reannotation_round"] == 2  # round+1
        assert result["created"] == 2  # 两个历史标注人各一条
        assert result["eligible_sense_ids"] == [101, 102]
        inserts = [p for s, p in cursor.executed if "INSERT INTO assignments" in s]
        assert len(inserts) == 2
        for params in inserts:
            assert params[5] == 2      # 重标任务 round=旧轮+1
            assert params[6] is None   # 重标是正式轮，training 不留痕
            assert json.loads(params[3]) == ["run"]  # scope_verbs=受影响义位的动词

    def test_scope_verbs_none_when_no_headword(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        cursor.select_routes[-1] = ("SELECT DISTINCT headword", [])
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True
        params = [p for s, p in cursor.executed if "INSERT INTO assignments" in s][0]
        assert params[3] is None  # 查不到 headword → NULL（页面灰注说明）

    def test_gate_skips_non_divided_sense(self, monkeypatch):
        # cs_senses 状态非 merged/split → 跳过并列明，绝不带病建任务
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor, cs_status_by_sense={101: "保留"})
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is False
        assert result["created"] == 0
        assert "未通过分立裁决闸" in result["error"]
        assert result["skipped"][0]["sense_id"] == 101
        assert not [s for s, _ in cursor.executed if "INSERT INTO assignments" in s]

    def test_gate_skips_unmapped_sense(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        cursor.select_routes[1] = ("JOIN cs_senses s", lambda sql, params: [])
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is False
        assert "未映射到语义分析义位" in result["skipped"][0]["reason"]

    def test_mixed_senses_partial_eligible(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor, cs_status_by_sense={102: "split"})
        cursor.select_routes[1] = (
            "JOIN cs_senses s",
            lambda sql, params: ([{"cs_status": "merged"}] if params[1] == 101
                                 else [{"cs_status": "split"}] if params[1] == 102
                                 else []),
        )
        result = create_reannotation_tasks("motion", [101, 102, 103], 2, 1,
                                           actor=ADMIN_ACTOR)
        assert result["ok"] is True
        assert result["eligible_sense_ids"] == [101, 102]
        assert result["skipped"][0]["sense_id"] == 103
        assert result["reannotation_round"] == 3

    def test_no_prior_coders_creates_nothing_but_ok(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        cursor.select_routes[-2] = ("SELECT DISTINCT coder_id", [])
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is True and result["created"] == 0
        assert result["note"] and "无历史标注提交" in result["note"]
        assert not [s for s, _ in cursor.executed if "INSERT INTO assignments" in s]

    def test_study_code_unresolved_fails_closed(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        cursor.select_routes.append(("SELECT code FROM categories", []))
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=ADMIN_ACTOR)
        assert result["ok"] is False
        assert "研究代号" in result["error"]
        assert not [s for s, _ in cursor.executed if "INSERT INTO assignments" in s]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"category": ""}, {"category": 3},
            {"task_type": "screening"}, {"round": 0}, {"round": -1},
            {"round": "2"}, {"round": True},
            {"assigned_by": 0}, {"sense_ids": []}, {"sense_ids": None},
            {"sense_ids": [0]}, {"sense_ids": [-3]}, {"sense_ids": "101"},
        ],
    )
    def test_invalid_params_fail_closed(self, monkeypatch, kwargs):
        cursor = _patch_plain(monkeypatch)
        call = dict(category="motion", sense_ids=[101], round=1, assigned_by=1)
        call.update(kwargs)
        result = create_reannotation_tasks(**call, actor=ADMIN_ACTOR)
        assert result["ok"] is False and result["error"]
        assert cursor.executed == []

    def test_actor_gate(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        with pytest.raises(PermissionError):
            create_reannotation_tasks("motion", [101], 1, 1, actor=LOW_ACTOR)
        # 非 dict 杂类型 fail-closed（注意不能用 None.__class__()——那构造
        # 出的就是 None 单例本身，is None 命中「系统作业」放行不抛）
        with pytest.raises(PermissionError):
            create_reannotation_tasks("motion", [101], 1, 1, actor="admin")
        assert cursor.executed == []

    def test_actor_none_is_system_job(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        _seed_reannotation_happy(cursor)
        result = create_reannotation_tasks("motion", [101], 1, 1, actor=None)
        assert result["ok"] is True


# ============================================
# 5) 台账读面与已裁决证据面
# ============================================
class TestReadHelpers:
    def test_list_assignments_admin_filters_and_limits(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        rows = [{"id": 3, "assignee_id": 7, "category": "motion",
                 "task_type": "feature_coding", "status": "open",
                 "scope_verbs": '["run"]', "assigned_by": 1, "round": 2,
                 "training": 1, "created_at": "2026-11-09",
                 "username": "alice", "display_name": "爱丽丝"}]
        cursor.select_routes.append(("FROM assignments a", rows))
        out = list_assignments_admin(statuses=["open"], limit=50)
        assert out and out[0]["round"] == 2
        assert out[0]["training"] is True   # TINYINT → bool
        assert out[0]["scope_verbs"] == ["run"]
        sql, params = cursor.executed[-1]
        assert "WHERE a.status IN" in sql and params[0] == "open"

    def test_list_assignments_admin_bad_statuses_empty(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        assert list_assignments_admin(statuses=["bogus"]) == []
        assert list_assignments_admin(limit=0) == []

    def test_list_divided_senses(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        cursor.select_routes.append(
            ("FROM cs_senses", [{"id": 9, "sense_no": "1", "sense_label": "足部奔跑义",
                                 "status": "merged", "merged_into": 7}])
        )
        out = list_divided_senses()
        assert out[0]["status"] == "merged"
        assert out[0]["merged_into"] == 7
        # executed[0] 是 merged_into 列探测（FX-20 哨兵，桩探测返回空行→跳过 ALTER）；
        # 主查询取首条 FROM cs_senses 语句断言
        main = next((sp for sp in cursor.executed if "FROM cs_senses" in sp[0]))
        sql, params = main
        assert "status IN (%s, %s)" in sql and set(params[:2]) == {"merged", "split"}

    def test_list_divided_senses_degrades_on_error(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)

        def _boom(sql, params=None):
            raise RuntimeError("fx20 fake db down")

        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _BoomCtx())
        assert list_divided_senses() == []

    def test_stats_includes_round_training_keys(self, monkeypatch):
        cursor = _patch_plain(monkeypatch)
        cursor.select_routes.append(
            ("FROM assignments a",
             [{"assignment_id": 3, "assignee_id": 7, "category": "motion",
               "task_type": "feature_coding", "assignment_status": "open",
               "scope_verbs": None, "assigned_by": 1, "round": 2,
               "training": 0, "username": "alice", "display_name": None,
               "n_submitted": 1, "n_adjudicated": 0}])
        )
        cursor.select_routes.append(("WHERE NOT EXISTS", []))
        stats = get_assignment_stats()
        assert stats[0]["round"] == 2
        assert stats[0]["training"] is False


class _BoomCtx:
    def __enter__(self):
        raise RuntimeError("fx20 fake db down")

    def __exit__(self, *args):
        return False


# ============================================
# 6) UI 补充段仍在（tab 接线 + flash 纪律 + 表单键）
# ============================================
class TestFx20Ui:
    def test_ops_helpers_callable(self):
        for name in ("_render_assign_ops_tab", "_render_assignment_ledger",
                     "_render_reassign_section", "_render_training_assign_section",
                     "_render_reannotation_section", "_assignment_round_badges"):
            assert callable(getattr(dp, name)), name

    def test_assign_tab_wiring_intact(self):
        # tab_assign 内先主表单（collab_pages 本体）后 FX-20 补充段
        src = inspect.getsource(dp.render_dict_admin_page)
        assert "collab_pages._render_assign_tab(me)" in src
        assert "_render_assign_ops_tab(me)" in src
        assert src.index("collab_pages._render_assign_tab(me)") < \
            src.index("_render_assign_ops_tab(me)")

    def test_ops_section_has_three_entries_and_badges(self):
        src = inspect.getsource(dp)
        assert "🔁 改派分派" in src
        assert "🎯 试标轮分派" in src
        assert "♻️ 发起重标" in src
        assert "🗂️ 分派台账" in src
        assert "试标" in inspect.getsource(dp._assignment_round_badges)

    def test_success_feedback_uses_flash_not_st_success(self):
        # RV12-2 纪律：FX-20 补充段成功反馈一律 ui_kit.flash + st.rerun，
        # 禁止 st.success + st.rerun 组合回潮
        for fn in (dp._render_assign_ops_tab, dp._render_reassign_section,
                   dp._render_training_assign_section,
                   dp._render_reannotation_section,
                   dp._render_assignment_ledger):
            src = inspect.getsource(fn)
            assert "ui_kit.flash" in src or "st.rerun" not in src, fn.__name__
            assert "st.success" not in src, fn.__name__

    def test_ops_widget_keys_prefixed(self):
        src = inspect.getsource(dp._render_training_assign_section)
        assert "dict_admin_fx20_train_round" in src
        assert "dict_admin_fx20_train_training" in src

    def test_g2_export_pointer_in_cockpit(self):
        # 特征矩阵导出已在 reliability 页（只读核实），驾驶舱 G2 灰注有指路说明
        src = inspect.getsource(dp._render_cockpit_tab)
        assert "信度报告" in src
        assert "规范修订→重标" in src


# ============================================
# 集成测试：真实 MySQL（无环境则整类 skip）
# ============================================
def _mysql_reachable() -> bool:
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX20 集成测试")
class TestFx20RealDb:
    """试标轮迁移/改派/重标闭环跑在真实 MySQL 8.0（独立测试库 web_word_fx20_test）。"""

    @pytest.fixture
    def fx20_db(self, monkeypatch):
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX20 集成测试: {e}")
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
        ensure_flow_tables()  # 建三表 + FX-20 试标轮两列迁移

        # 种子：1 词条 2 义项（oald_senses）；RUN 范畴的 cs 侧（lexeme + sense#1）
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
                "INSERT INTO oald_senses (definition_id, sense_index, definition, "
                "headword) VALUES (%s, %s, %s, %s)",
                (definition_id, 2, "to manage a business", "run"),
            )
            sense_b = cursor.lastrowid
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
        assert all(isinstance(u, int) for u in (coder_a, coder_b))
        project_id = create_project("FX20 项目", 1, ["motion"])
        assert project_id
        assert add_member(project_id, coder_a, "annotator", 1)
        assert add_member(project_id, coder_b, "annotator", 1)
        # 历史标注：coder_a 在 sense_a 上有一条 feature_coding 提交
        assert flow.submit_annotation("motion", sense_a, "feature_coding",
                                      coder_a, {"features": {"P1": 1}})

        yield {
            "admin_id": 1,
            "project_id": project_id,
            "coder_a": coder_a,
            "coder_b": coder_b,
            "sense_a": sense_a,
            "sense_b": sense_b,
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

    def test_round_training_migration_idempotent(self, fx20_db):
        cols = _q(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assignments' "
            "AND COLUMN_NAME IN ('round', 'training')"
        )
        assert {r["COLUMN_NAME"] for r in cols} == {"round", "training"}
        ensure_flow_tables()  # 二次执行不炸、不重复加列
        cols = _q(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assignments' "
            "AND COLUMN_NAME IN ('round', 'training')"
        )
        assert len(cols) == 2
        nullables = _q(
            "SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE FROM "
            "information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'assignments' AND COLUMN_NAME IN "
            "('round', 'training') ORDER BY COLUMN_NAME"
        )
        by_name = {r["COLUMN_NAME"]: r for r in nullables}
        assert by_name["round"]["IS_NULLABLE"] == "YES"
        assert by_name["training"]["IS_NULLABLE"] == "YES"

    def test_assign_task_round_training_roundtrip(self, fx20_db):
        ctx = fx20_db
        assert assign_task(ctx["coder_a"], "motion", "feature_coding", ["run"],
                           ctx["admin_id"], round=2, training=True) is True
        row = _q("SELECT `round`, training FROM assignments ORDER BY id DESC "
                 "LIMIT 1")[0]
        assert row["round"] == 2 and row["training"] == 1
        # 默认调用：None 不留痕（RV2-3）
        assert assign_task(ctx["coder_b"], "motion", "admission", None,
                           ctx["admin_id"]) is True
        row = _q("SELECT `round`, training FROM assignments ORDER BY id DESC "
                 "LIMIT 1")[0]
        assert row["round"] is None and row["training"] is None
        stats = get_assignment_stats()
        assert all("round" in s and "training" in s for s in stats)
        mine = [s for s in stats if s.get("assignment_id")
                and s["round"] == 2]
        assert mine and mine[0]["training"] is True

    def test_reassign_end_to_end(self, fx20_db):
        ctx = fx20_db
        from src.org_db import get_members

        assert assign_task(ctx["coder_b"], "motion", "admission", None,
                           ctx["admin_id"]) is True
        aid = _q("SELECT id FROM assignments ORDER BY id DESC LIMIT 1")[0]["id"]
        # actor 权限直调面：低权先抛，未触库
        with pytest.raises(PermissionError):
            reassign_assignment(aid, ctx["project_id"], ctx["coder_a"],
                                ctx["admin_id"], actor=LOW_ACTOR)
        assert _q("SELECT assignee_id FROM assignments WHERE id = %s",
                  (aid,))[0]["assignee_id"] == ctx["coder_b"]
        # 正常改派：open → coder_a（同项目在册在用、非现承包人）
        assert reassign_assignment(aid, ctx["project_id"], ctx["coder_a"],
                                   ctx["admin_id"], actor=ADMIN_ACTOR) is True
        assert _q("SELECT assignee_id FROM assignments WHERE id = %s",
                  (aid,))[0]["assignee_id"] == ctx["coder_a"]
        # 非当前承包人闸：同一个人重复改派拒绝
        assert reassign_assignment(aid, ctx["project_id"], ctx["coder_a"],
                                   ctx["admin_id"], actor=ADMIN_ACTOR) is False
        # 同项目在册闸：未入册用户拒绝
        from src.users_db import create_user

        outsider = create_user("mallory", "pw123456", "局外人", "annotator")
        assert reassign_assignment(aid, ctx["project_id"], outsider,
                                   ctx["admin_id"], actor=ADMIN_ACTOR) is False
        # 状态闸：in_progress / closed 拒绝（active/accepted 家族）
        for status in ("in_progress", "submitted", "closed"):
            _q("UPDATE assignments SET status = %s WHERE id = %s", (status, aid))
            assert reassign_assignment(aid, ctx["project_id"], ctx["coder_b"],
                                       ctx["admin_id"],
                                       actor=ADMIN_ACTOR) is False, status
            assert _q("SELECT assignee_id FROM assignments WHERE id = %s",
                      (aid,))[0]["assignee_id"] == ctx["coder_a"]
        # 成员资格未被改派触碰（在途保护沿用 remove_member 口径）
        member_ids = {m["user_id"] for m in get_members(ctx["project_id"])}
        assert {ctx["coder_a"], ctx["coder_b"]} <= member_ids

    def test_reannotation_end_to_end(self, fx20_db):
        ctx = fx20_db
        submissions_before = len(_q(
            "SELECT id FROM annotation_submissions WHERE category = 'motion' "
            "AND task_type = 'feature_coding'"
        ))
        assert submissions_before >= 1
        # 发起重标：sense_a 已裁决 merged（cs_senses 种子），旧轮=1 → 任务 round=2
        result = create_reannotation_tasks(
            "motion", [ctx["sense_a"]], 1, ctx["admin_id"], actor=ADMIN_ACTOR)
        assert result["ok"] is True
        assert result["reannotation_round"] == 2
        assert result["created"] == 1
        assert result["coder_ids"] == [ctx["coder_a"]]
        rows = _q(
            "SELECT assignee_id, `round`, training, scope_verbs FROM assignments "
            "ORDER BY id DESC LIMIT 1"
        )
        assert rows[0]["assignee_id"] == ctx["coder_a"]
        assert rows[0]["round"] == 2 and rows[0]["training"] is None
        assert json.loads(rows[0]["scope_verbs"]) == ["run"]
        # 旧轮提交保留作历史（annotation_submissions 零写入）
        submissions_after = len(_q(
            "SELECT id FROM annotation_submissions WHERE category = 'motion' "
            "AND task_type = 'feature_coding'"
        ))
        assert submissions_after == submissions_before
        # 裁决闸：sense_b 无 cs_senses 映射 → 跳过；全跳过 ok=False
        result = create_reannotation_tasks(
            "motion", [ctx["sense_b"]], 2, ctx["admin_id"], actor=ADMIN_ACTOR)
        assert result["ok"] is False
        assert "未通过分立裁决闸" in result["error"]
        assert result["skipped"][0]["sense_id"] == ctx["sense_b"]
        # 闸状态改回「保留」（非 merged/split）→ 同样拒绝
        _q("UPDATE cs_senses SET status = '保留' WHERE sense_no = '1'")
        result = create_reannotation_tasks(
            "motion", [ctx["sense_a"]], 2, ctx["admin_id"], actor=ADMIN_ACTOR)
        assert result["ok"] is False
        assert result["skipped"][0]["reason"].startswith("cs_senses 状态为")
        _q("UPDATE cs_senses SET status = 'merged' WHERE sense_no = '1'")

    def test_list_divided_senses_and_admin_ledger(self, fx20_db):
        ctx = fx20_db
        divided = list_divided_senses()
        assert len(divided) == 1
        assert divided[0]["status"] == "merged"
        assert divided[0]["sense_label"] == "足部奔跑义"
        assert list_assignments_admin() == []  # 空台账不炸
        assert assign_task(ctx["coder_a"], "motion", "admission", None,
                           ctx["admin_id"], round=1, training=True)
        ledger = list_assignments_admin(statuses=["open"])
        assert ledger and ledger[0]["round"] == 1
        assert ledger[0]["training"] is True
