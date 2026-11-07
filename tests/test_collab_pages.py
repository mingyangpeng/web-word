"""AI 协作区页面模块测试（src/collab_pages.py）。

两层结构，与 tests/test_ai_ledger.py 约定一致：

  * 契约纯件（GUIDE 四段式 / 角色门三态 / 裁决校验四态 / 待决排序 /
    展示格式化 / scope_verbs 解析 / 常量口径）不碰数据库 —— 本地与 CI 全跑；
  * 参数化查询辅助（create_assignment / list_my_assignments / _search_verbs /
    _list_proposal_stages / _assignments_table_ready / _candidate_assignees）
    依赖真实 MySQL —— 连不上就 skip（模块级 skipif + fixture 内 skip），
    CI（无数据库）依然全绿。集成测试使用测试库 TEST_DB（monkeypatch
    db.MYSQL_DATABASE 指向它，连接池按键区分 host/port/db/user），每个测试
    重建，跑完 DROP；本地 MySQL 账号按名授权，本模块没有专属库名，与
    test_org_db / test_dict_admin_db 同口径共用 web_word_users_test
    （pytest 串行执行，fixture 前后 DROP 重建，互不污染；运维补授权
    web_word_collab_test 后改 TEST_DB 一行即可）。

覆盖面（阶段1施工规范 §5 对 Agent H 的要求）：
  GUIDE 契约（四段式、steps≥3、label 口径）/ 角色门 _is_admin_like 六角色
  口径（批次 12 R1-2 升级）＋ _can_adjudicate 裁决权（R1-5）/
  空理由拒绝逻辑 _validate_decision 四态 / 收件箱排序（uncertainty DESC、
  缺失最后、id ASC）/ 分派写读回路（INSERT assignments ↔ 我的任务查询，
  status≠closed 过滤）/ 动词搜索（参数化 LIKE）/ 工序枚举与表就绪探测。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.ai_ledger import (  # noqa: E402
    DECISION_ADOPTED,
    DECISION_MODIFIED,
    DECISION_REJECTED,
    KIND_PROBE,
    ensure_ai_ledger_tables,
    record_proposal,
)
from src.annotation_flow import TASK_TYPES  # noqa: E402
from src.collab_pages import (  # noqa: E402
    ASSIGNMENT_TASK_TYPES,
    GUIDE,
    INBOX_KINDS,
    KEY_PREFIX,
    LEGACY_ASSIGNEE_ROLES,
    _assignments_table_ready,
    _can_adjudicate,
    _clean_reason,
    _candidate_assignees,
    _fmt_rate,
    _fmt_uncertainty,
    _is_admin_like,
    _list_proposal_stages,
    _parse_scope_verbs,
    _search_verbs,
    _sort_pending,
    _validate_decision,
    create_assignment,
    list_my_assignments,
    render_collab_page,
)
from src.mysql_db import get_db_cursor  # noqa: E402
from src.users_db import create_user, grant_role, list_users  # noqa: E402

TEST_DB = "web_word_collab_test"  # 与 users 系测试共用（授权覆盖；见模块 docstring）


# ============================================
# 契约纯件（不碰数据库，CI 必跑）
# ============================================

class TestGuideContract:
    """GUIDE 四段式契约（施工规范 §5：集成时原样并入 PAGE_GUIDES）。"""

    def test_guide_keys(self):
        """六个键齐全：label/purpose/principle/data_source/steps/notes。"""
        assert set(GUIDE.keys()) == {
            "label", "purpose", "principle", "data_source", "steps", "notes",
        }

    def test_guide_label(self):
        """区级页面标签口径（与施工规范 §5 表格一致）。"""
        assert GUIDE["label"] == "🤖 AI 协作"

    def test_guide_steps_at_least_three(self):
        """steps≥3 且每步非空字符串（契约硬指标）。"""
        steps = GUIDE["steps"]
        assert isinstance(steps, list) and len(steps) >= 3
        assert all(isinstance(s, str) and s.strip() for s in steps)

    def test_guide_sections_non_empty(self):
        """purpose 为非空串；principle/data_source/notes 为非空字符串清单。"""
        assert isinstance(GUIDE["purpose"], str) and GUIDE["purpose"].strip()
        for key in ("principle", "data_source", "notes"):
            section = GUIDE[key]
            assert isinstance(section, list) and section, f"GUIDE[{key}] 不得为空"
            assert all(isinstance(s, str) and s.strip() for s in section), key

    def test_guide_covers_three_tabs(self):
        """说明覆盖三个 tab（收件箱/度量/任务分配），与页面 st.tabs 对应。"""
        text = GUIDE["purpose"] + "".join(GUIDE["steps"]) + "".join(GUIDE["notes"])
        for tab in ("收件箱", "协同度量", "任务分配"):
            assert tab in text, f"GUIDE 未提及 tab：{tab}"


class TestRoleGate:
    """角色门 _is_admin_like / _can_adjudicate（批次 12 R1-2/R1-5 六角色口径）。

    _is_admin_like 升级为有效六角色集判定（users_db.effective_six_roles 单一
    实现）：legacy role=='admin' 经映射两位一体自然通过（升级前后对存量账号
    逐字节一致）；授予式 dict_admin/sys_admin（legacy 列 viewer/annotator 但
    user_roles 已授予）自此放行 —— R1 家族「授予式用户不再被 legacy 判定
    拦在门外」。reviewer/editor/annotator/viewer 一律 False。
    """

    def test_admin_role_passes(self):
        """legacy role=='admin' 经映射兼判 dict_admin+sys_admin → True。"""
        assert _is_admin_like({"id": 1, "username": "admin", "role": "admin"})

    def test_six_role_admin_snapshot_passes(self):
        """R1-2 升级：六角色 roles 快照（dict_admin / sys_admin）→ True。

        注：legacy users.role 列值域恒为旧四枚举，六角色只经会话 roles 快照
        携带（verify_login_full），故直接 role='dict_admin' 不是真实会话形态
        （effective fail-closed 空）—— 判定面是 roles 快照。
        """
        assert _is_admin_like({"id": 2, "role": "viewer",
                               "roles": ["dict_admin", "viewer"]})
        assert _is_admin_like({"id": 2, "role": "viewer",
                               "roles": ["sys_admin"]})

    def test_granted_admin_roles_pass(self):
        """授予式管理角色（roles 快照）→ True（授予式用户不再被拦）。"""
        assert _is_admin_like({"id": 3, "role": "viewer",
                               "roles": ["dict_admin", "viewer"]})
        assert _is_admin_like({"id": 4, "role": "annotator",
                               "roles": ["sys_admin"]})

    def test_non_admin_roles_fail(self):
        """reviewer/editor/annotator/viewer（含授予式）→ False。"""
        for user in (
            {"id": 2, "role": "reviewer"},
            {"id": 2, "role": "annotator"},
            {"id": 2, "role": "viewer"},
            {"id": 2, "role": "viewer", "roles": ["annotator", "viewer"]},
            {"id": 2, "role": "viewer", "roles": ["reviewer"]},
            {"id": 2, "role": "viewer", "roles": ["editor"]},
        ):
            assert not _is_admin_like(user), user

    def test_not_a_session_user_fails(self):
        """未登录/非 dict/缺角色键 → False（fail-closed）。"""
        for bad in (None, "admin", 123, [], {}, {"id": 3, "username": "x"}):
            assert not _is_admin_like(bad), repr(bad)


class TestCanAdjudicate:
    """收件箱裁决权 _can_adjudicate（R1-5：dict_admin/reviewer 两角色）。"""

    def test_dict_admin_and_reviewer_pass(self):
        """有效集含 dict_admin 或 reviewer → True（legacy admin 映射兼判）。"""
        assert _can_adjudicate({"id": 1, "role": "admin"})
        assert _can_adjudicate({"id": 3, "role": "reviewer"})
        assert _can_adjudicate({"id": 2, "role": "viewer",
                                "roles": ["dict_admin", "viewer"]})
        assert _can_adjudicate({"id": 4, "role": "viewer",
                                "roles": ["reviewer", "viewer"]})
        assert _can_adjudicate({"id": 5, "role": "annotator",
                                "roles": ["dict_admin"]})

    def test_other_roles_fail(self):
        """sys_admin/editor/annotator/viewer 单角色 → False（fail-closed）。"""
        for user in (
            {"id": 6, "role": "sys_admin"},
            {"id": 7, "role": "viewer", "roles": ["editor"]},
            {"id": 8, "role": "viewer", "roles": ["annotator", "viewer"]},
            {"id": 9, "role": "viewer", "roles": ["sys_admin"]},
            {"id": 10, "role": "viewer"},
        ):
            assert not _can_adjudicate(user), user

    def test_not_a_session_user_fails(self):
        """未登录/非 dict/缺角色键 → False（fail-closed）。"""
        for bad in (None, "reviewer", 42, [], {}):
            assert not _can_adjudicate(bad), repr(bad)


class TestValidateDecision:
    """空理由拒绝逻辑 _validate_decision 四态（否决必须给理由的架构纪律）。"""

    def test_state1_invalid_decision(self):
        """态一：decision 非三值 → 错误文案（大小写敏感，不猜意图）。"""
        for bad in ("approve", "", "ADOPTED", None, 1):
            err = _validate_decision(bad, "理由")
            assert isinstance(err, str) and err, repr(bad)

    def test_state2_rejected_needs_reason(self):
        """态二：否决且理由为空（None/空串/纯空白）→ 错误文案。"""
        for empty in (None, "", "   ", "\n\t "):
            err = _validate_decision(DECISION_REJECTED, empty)
            assert isinstance(err, str) and "理由" in err, repr(empty)

    def test_state3_valid_with_reason(self):
        """态三：三值裁决且理由非空 → 全部通过（None）。"""
        for decision in (DECISION_ADOPTED, DECISION_REJECTED, DECISION_MODIFIED):
            assert _validate_decision(decision, "依库内证据 oald_senses:1") is None
            # 带内容的理由即便首尾带空白也算「非空」（_clean_reason 只负责收敛入库值）
            assert _validate_decision(decision, "  依据 X  ") is None

    def test_state4_adopt_modified_without_reason(self):
        """态四：采纳/修改允许无理由（None/空串/纯空白）；否决已被态二拦截。"""
        for empty in (None, "", "   "):
            assert _validate_decision(DECISION_ADOPTED, empty) is None
            assert _validate_decision(DECISION_MODIFIED, empty) is None

    def test_decisions_align_with_ledger(self):
        """校验函数认可的恰好是 ai_ledger 的裁决三值（无第四值、无漂移）。"""
        assert DECISION_REJECTED in (DECISION_ADOPTED, DECISION_REJECTED,
                                     DECISION_MODIFIED)
        # rejected 带理由同样通过 —— 拦的只是空理由，不是 rejected 本身
        assert _validate_decision(DECISION_REJECTED, "与库内证据冲突") is None


class TestSortPending:
    """收件箱排序口径（与 ai_ledger.list_pending 的 ORDER BY 一致）。"""

    def test_uncertainty_desc_null_last_id_asc(self):
        """不确定度降序；缺失（None）排最后；同分按 id 升序稳序。"""
        items = [
            {"id": 3, "uncertainty": None},
            {"id": 2, "uncertainty": 0.9000},
            {"id": 1, "uncertainty": 0.9000},
            {"id": 5, "uncertainty": 0.1000},
            {"id": 4, "uncertainty": 0.0000},
        ]
        ordered = _sort_pending(items)
        # 0.9 同分按 id 升序 → 1, 2；0.1 → 5；0.0 → 4；缺失（None）最后 → 3
        assert [p["id"] for p in ordered] == [1, 2, 5, 4, 3]

    def test_empty_and_single(self):
        """空清单与单元素清单原样返回（不抛异常）。"""
        assert _sort_pending([]) == []
        assert _sort_pending([{"id": 9, "uncertainty": None}]) == [
            {"id": 9, "uncertainty": None}
        ]

    def test_missing_keys_tolerated(self):
        """缺 uncertainty/id 键的脏行不抛异常（缺失按「最后/最小」处理）。"""
        ordered = _sort_pending([{"id": 1}, {"uncertainty": 0.5}])
        assert len(ordered) == 2


class TestFormattingAndParsing:
    """展示格式化与 scope_verbs 解析（None 显示「—」不虚构）。"""

    def test_fmt_rate_none_is_dash(self):
        """采纳率 None →「—」（没数据 ≠ 0%）。"""
        assert _fmt_rate(None) == "—"

    def test_fmt_rate_values(self):
        """数值 → 百分数一位小数（0 也如实显示 0.0%）。"""
        assert _fmt_rate(0.0) == "0.0%"
        assert _fmt_rate(0.7234) == "72.3%"
        assert _fmt_rate(1.0) == "100.0%"

    def test_fmt_uncertainty(self):
        """不确定度 None →「—」；数值 → 4 位小数（与台账存储口径一致）。"""
        assert _fmt_uncertainty(None) == "—"
        assert _fmt_uncertainty(0.5) == "0.5000"
        assert _fmt_uncertainty(0.0) == "0.0000"

    def test_clean_reason(self):
        """理由规整：去空白；纯空白/None/非字符串 → None（NULL 入库口径）。"""
        assert _clean_reason("  依据 X  ") == "依据 X"
        assert _clean_reason("   ") is None
        assert _clean_reason(None) is None
        assert _clean_reason(123) is None

    def test_parse_scope_verbs(self):
        """scope_verbs JSON 列解析：None→None（全部动词）；JSON 串/bytes→清单。"""
        assert _parse_scope_verbs(None) is None
        assert _parse_scope_verbs('["run", "walk"]') == ["run", "walk"]
        assert _parse_scope_verbs(b'["run"]') == ["run"]
        assert _parse_scope_verbs([" run ", ""]) == ["run"]
        assert _parse_scope_verbs('not json') is None
        assert _parse_scope_verbs(42) is None
        assert _parse_scope_verbs('{"x": 1}') is None


class TestConstantsContract:
    """模块常量口径（与数据层/DDL 对齐，防止两处常量漂移）。"""

    def test_inbox_kinds_exclude_probe(self):
        """收件箱只收 draft/audit；probe 探针不进收件箱（数据层取数约定）。"""
        assert INBOX_KINDS == ("draft", "audit")
        assert KIND_PROBE not in INBOX_KINDS

    def test_task_types_align_with_flow_layer(self):
        """task_type 枚举与 annotation_flow.TASK_TYPES 一致（DDL 单一事实源）。"""
        assert ASSIGNMENT_TASK_TYPES == TASK_TYPES
        assert ASSIGNMENT_TASK_TYPES == ("admission", "feature_coding", "alignment")

    def test_key_prefix(self):
        """widget key 统一前缀（施工规范 §5）。"""
        assert KEY_PREFIX == "collab_"

    def test_assignee_roles_exclude_viewer(self):
        """分派对象过滤：标注→annotator+（viewer 只读不可承担标注任务）。"""
        assert "annotator" in LEGACY_ASSIGNEE_ROLES
        assert "viewer" not in LEGACY_ASSIGNEE_ROLES

    def test_render_entry_signature(self):
        """渲染入口存在且可调用（契约：render_collab_page() -> None）。"""
        assert callable(render_collab_page)


# ============================================
# R2-5：动词搜索 LIKE 转义（与 data_pages._escape_like 同口径，CI 必跑）
# ============================================

class _CaptureCursor:
    """假 cursor：捕获 SQL 文本与参数（_search_verbs 转义守约用，不碰库）。"""

    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._store["sql"] = sql
        self._store["params"] = params

    def fetchall(self):
        return []


def test_search_verbs_escapes_wildcards_and_sets_escape_clause(monkeypatch):
    """R2-5：搜索词经 data_pages._escape_like 转义（!/%/_ → 字面），SQL 两侧
    LIKE 带 ``ESCAPE '!'`` —— 通配符按字面处理，与词条搜索口径一致。"""
    import src.collab_pages as collab_mod
    from src.data_pages import _escape_like

    store = {}
    monkeypatch.setattr(collab_mod, "get_db_cursor", lambda: _CaptureCursor(store))
    assert collab_mod._search_verbs("run_100%") == []
    assert store["sql"].count("ESCAPE '!'") == 2  # verb 与 headword 两个 LIKE
    like = store["params"][0]
    # 与 data_pages 单一实现逐字符一致（函数级复用，不复制第二份转义逻辑）
    assert like == f"%{_escape_like('run_100%')}%"
    assert like == "%run!_100!%%"
    # 空白关键词早退（不触库）：捕获器未被二次调用
    assert collab_mod._search_verbs("   ") == []
    assert store["params"][0] == "%run!_100!%%"  # 仍是第一次（唯一一次）调用


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

# 本模块参数化辅助依赖的三张最小表（只含被查/被写列，结构与 DDL 对齐；
# definitions/oald_senses 的完整 DDL 属 mysql_db，测试库无需全量建）。
_DEFINITIONS_MIN_SQL = """CREATE TABLE definitions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  verb VARCHAR(100) NOT NULL UNIQUE,
  sense_count INT NOT NULL DEFAULT 0,
  cluster_id INT DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_OALD_SENSES_MIN_SQL = """CREATE TABLE oald_senses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  definition_id INT NOT NULL,
  headword VARCHAR(64) DEFAULT NULL,
  KEY idx_min_oald_def (definition_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过协作区辅助查询集成测试")
class TestCollabDbHelpers:
    """参数化查询辅助（跑在独立测试库 web_word_collab_pages_test）。"""

    @pytest.fixture
    def collab_db(self, monkeypatch):
        """建空测试库＋最小表结构，让本模块辅助指向它，测试结束 DROP。

        users/user_roles 走 users_db.ensure_user_tables（含内置 admin 幂等迁移）；
        assignments 走 annotation_flow 的 DDL 常量（该表只有 users 外键，
        可独立建）；definitions/oald_senses 用最小形（只含本模块查询列）；
        ai_proposals 走 ai_ledger.ensure（无外键）。各表是否就绪由各测试
        自行调用（_assignments_table_ready 的"未建"态需要在建表前观察）。
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过协作区集成测试: {e}")
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

    def _create_base_tables(self) -> None:
        """users(+user_roles) + definitions/oald_senses 最小形 + ai_proposals。"""
        from src.users_db import ensure_user_tables

        ensure_user_tables()
        with get_db_cursor() as cursor:
            cursor.execute(_DEFINITIONS_MIN_SQL)
            cursor.execute(_OALD_SENSES_MIN_SQL)
        ensure_ai_ledger_tables()

    def _create_assignments_table(self) -> None:
        """assignments 建表（annotation_flow 的 DDL 常量，只有 users 外键）。"""
        from src.annotation_flow import ASSIGNMENTS_TABLE_SQL

        with get_db_cursor() as cursor:
            cursor.execute(ASSIGNMENTS_TABLE_SQL)

    def _fetch_status(self, assignment_id: int):
        """直接读库取分派行状态（绕过页面辅助，验证落库真相）。"""
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT assignee_id, category, task_type, scope_verbs, status, "
                "assigned_by FROM assignments WHERE id = %s",
                (assignment_id,),
            )
            return cursor.fetchone()

    # --- 表就绪探测 ---

    def test_assignments_table_ready_transitions(self, collab_db):
        """表未建 → False（合法状态）；建表后 → True；幂等重复建不炸。"""
        from src.users_db import ensure_user_tables

        ensure_user_tables()
        assert _assignments_table_ready() is False
        self._create_assignments_table()
        assert _assignments_table_ready() is True
        self._create_assignments_table()  # CREATE IF NOT EXISTS 幂等
        assert _assignments_table_ready() is True

    # --- 创建分派 ↔ 我的任务 ---

    def test_create_and_list_roundtrip(self, collab_db):
        """创建分派（assigned_by=分派人）→「我的任务」读回，字段逐项一致。"""
        self._create_base_tables()
        self._create_assignments_table()
        chief = create_user("chief_h", "pass_h_1234", "主编H", "admin")
        annotator = create_user("ann_h", "pass_h_1234", "标注员H", "annotator")
        new_id = create_assignment(
            assignee_id=annotator,
            task_type="admission",
            scope_verbs=None,
            assigned_by=chief,
        )
        assert isinstance(new_id, int) and new_id > 0
        row = self._fetch_status(new_id)
        assert row["assignee_id"] == annotator
        assert row["assigned_by"] == chief
        assert row["task_type"] == "admission"
        assert row["status"] == "open"       # DDL 默认态
        assert row["category"] == "motion"   # DDL 默认范畴（批次 3 按簇推导）
        assert row["scope_verbs"] is None    # 不限动词 = NULL

        mine = list_my_assignments(annotator)
        assert len(mine) == 1
        assert mine[0]["id"] == new_id
        assert mine[0]["status"] == "open"
        assert mine[0]["scope_verbs"] is None
        assert mine[0]["assigned_by"] == chief

    def test_create_with_scope_verbs(self, collab_db):
        """scope_verbs 清单 → JSON 落库 → 读回为去空白后的动词清单。"""
        self._create_base_tables()
        self._create_assignments_table()
        chief = create_user("chief_h2", "pass_h_1234", "主编H2", "admin")
        ann = create_user("ann_h2", "pass_h_1234", "标注员H2", "annotator")
        new_id = create_assignment(
            assignee_id=ann,
            task_type="feature_coding",
            scope_verbs=[" run ", "walk"],
            assigned_by=chief,
        )
        assert new_id > 0
        mine = list_my_assignments(ann)
        assert mine[0]["scope_verbs"] == ["run", "walk"]
        assert mine[0]["task_type"] == "feature_coding"

    def test_create_rejects_bad_params(self, collab_db):
        """非法参数一律 0（falsy）：空 scope 清单/非法 task_type/非法 id。"""
        self._create_base_tables()
        self._create_assignments_table()
        chief = create_user("chief_h3", "pass_h_1234", "主编H3", "admin")
        ann = create_user("ann_h3", "pass_h_1234", "标注员H3", "annotator")
        assert create_assignment(ann, "admission", [], assigned_by=chief) == 0
        assert create_assignment(ann, "free_ride", None, assigned_by=chief) == 0
        assert create_assignment(0, "admission", None, assigned_by=chief) == 0
        assert create_assignment(ann, "admission", None, assigned_by=0) == 0
        assert create_assignment("x", "admission", None, assigned_by=chief) == 0
        assert list_my_assignments(ann) == []

    def test_list_excludes_closed_orders_desc(self, collab_db):
        """「我的任务」只出 status≠closed 的行，最新分派在前（id DESC）。"""
        self._create_base_tables()
        self._create_assignments_table()
        chief = create_user("chief_h4", "pass_h_1234", "主编H4", "admin")
        ann = create_user("ann_h4", "pass_h_1234", "标注员H4", "annotator")
        ids = [
            create_assignment(ann, "admission", None, assigned_by=chief),
            create_assignment(ann, "alignment", None, assigned_by=chief),
            create_assignment(ann, "feature_coding", None, assigned_by=chief),
        ]
        with get_db_cursor() as cursor:  # 直接把最老的一条置 closed
            cursor.execute(
                "UPDATE assignments SET status = 'closed' WHERE id = %s", (ids[0],)
            )
        mine = list_my_assignments(ann)
        assert [r["id"] for r in mine] == [ids[2], ids[1]]

    def test_list_bad_params_return_empty(self, collab_db):
        """非法 assignee_id/limit → []（不抛异常，页面按空态渲染）。"""
        self._create_base_tables()
        self._create_assignments_table()
        assert list_my_assignments(0) == []
        assert list_my_assignments(-1) == []
        assert list_my_assignments("x") == []
        assert list_my_assignments(999999, limit=0) == []

    # --- 动词搜索（oald_senses × definitions 参数化只读查询） ---

    def _seed_verbs(self) -> None:
        """灌两个动词与其 OALD 义项（最小表）。"""
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, sense_count, cluster_id) "
                "VALUES (%s, %s, %s)",
                ("run", 10, 3),
            )
            run_id = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO definitions (verb, sense_count, cluster_id) "
                "VALUES (%s, %s, %s)",
                ("walk", 6, 4),
            )
            walk_id = int(cursor.lastrowid)
            for def_id, headword in ((run_id, "run"), (run_id, "run into"),
                                     (walk_id, "walk")):
                cursor.execute(
                    "INSERT INTO oald_senses (definition_id, headword) VALUES (%s, %s)",
                    (def_id, headword),
                )

    def test_search_verbs_matches_verb_and_headword(self, collab_db):
        """词目或 OALD 词头 LIKE 命中；返回去重动词行（附义项数/簇 id）。"""
        self._create_base_tables()
        self._seed_verbs()
        hits = _list_proposal_stages()  # 先确认辅助查询在空台账上不炸
        assert hits == []
        rows = _search_verbs("run")
        assert [r["verb"] for r in rows] == ["run"]
        assert rows[0]["oald_senses"] == 2
        assert rows[0]["sense_count"] == 10
        assert rows[0]["cluster_id"] == 3
        # 词头命中：搜 "into" 不在任何词目里，但命中 run 的 "run into" 义项词头
        rows_by_headword = _search_verbs("into")
        assert [r["verb"] for r in rows_by_headword] == ["run"]

    def test_search_verbs_empty_and_no_hit(self, collab_db):
        """空关键词/无命中 → []（页面按「不限动词」口径继续）。"""
        self._create_base_tables()
        self._seed_verbs()
        assert _search_verbs("") == []
        assert _search_verbs("   ") == []
        assert _search_verbs("zzz_no_such_verb") == []

    def test_search_verbs_wildcards_are_literal(self, collab_db):
        """R2-5：搜索词中的 %/_ 按字面匹配（ESCAPE '!'），不展开成通配符 ——
        未转义时 walk_100 会连 walkz100 一起命中，转义后只命中原词目。"""
        self._create_base_tables()
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, sense_count) VALUES (%s, %s)",
                ("walk_100", 1),
            )
            d1 = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO definitions (verb, sense_count) VALUES (%s, %s)",
                ("walkz100", 1),
            )
            d2 = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO definitions (verb, sense_count) VALUES (%s, %s)",
                ("run100%", 1),
            )
            d3 = int(cursor.lastrowid)
            for def_id in (d1, d2, d3):
                cursor.execute(
                    "INSERT INTO oald_senses (definition_id, headword) "
                    "VALUES (%s, %s)",
                    (def_id, "h"),
                )
        rows = _search_verbs("walk_100")
        assert [r["verb"] for r in rows] == ["walk_100"]
        rows = _search_verbs("run100%")
        assert [r["verb"] for r in rows] == ["run100%"]

    # --- 分派对象过滤（users_db.list_users 过滤 role + 六角色并集） ---

    def test_candidate_assignees_filters_roles(self, collab_db):
        """viewer/停用账号不进名单；annotator 进；旧列 viewer 但被授
        annotator 六角色的账号经 list_roles 并集进名单（过渡口径）。"""
        from src.users_db import ensure_user_tables

        ensure_user_tables()
        chief = create_user("chief_h5", "pass_h_1234", "主编H5", "admin")
        ann = create_user("ann_h5", "pass_h_1234", "标注员H5", "annotator")
        viewer = create_user("view_h5", "pass_h_1234", "只读H5", "viewer")
        upgraded = create_user("up_h5", "pass_h_1234", "提权H5", "viewer")
        grant_role(upgraded, "annotator", granted_by=chief)
        users = list_users()
        options = _candidate_assignees(users)
        chosen_ids = set(options.values())
        assert ann in chosen_ids
        assert chief in chosen_ids          # admin 在 annotator+ 集合内
        assert viewer not in chosen_ids     # viewer 只读
        assert upgraded in chosen_ids       # 六角色事实源兜底

    # --- 工序枚举（协同度量下钻） ---

    def test_list_proposal_stages_distinct_sorted(self, collab_db):
        """台账登记后按工序去重升序；空台账 → []。"""
        self._create_base_tables()
        assert _list_proposal_stages() == []
        assert record_proposal("draft", "admission", "oald_senses:1", {"a": 1}) > 0
        assert record_proposal("audit", "admission", "oald_senses:2", {"b": 2}) > 0
        assert record_proposal("draft", "definition", "oald_senses:3", {"c": 3}) > 0
        assert _list_proposal_stages() == ["admission", "definition"]
