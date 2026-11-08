"""阶段 1 端到端验收（真实 MySQL · 专用测试库 web_word_stage1_e2e_test，可重复执行）。

把阶段 1 建成的新链路串成一条端到端场景（批次 8 · Agent Z1），作为阶段 1
「能跑通」的证据。七步按定义序执行（类级 fixture 共享状态，方法名 01–07
即执行序；pytest 按类内定义序收集）：

  01 建号与授权链  create_user 默认 viewer（六角色 user_roles 落行 +
                   must_change_password=1）→ grant_role 提 dict_admin
                   （内置 admin 作授权人；重复授予返回 False）
  02 项目壳与成员  create_project（chief=该词典管理员，同事务入册）→
                   add_member 入册编纂员（editor 六角色由 chief 授予）→
                   project_selfcheck 全绿（True, []）
  03 数据入口      import_engine.run_import(dry_run=True) 零写库断言
                   （definitions 行数不变、revert_log 恒空、preview 全 insert）
                   ＋ start_batch 台账登记（import_batches 落行审计）
  04 分派          _check_role_matrix 通过/拒绝两态（editor 放行 /
                   viewer 与未知任务类型拒绝）＋ create_assignment 落库
                   ＋ _check_load_limit（负荷上限：cap=1 拒、默认 10 放行）
  05 AI 提议→裁决  record_proposal(kind='draft', stage='sense_division') →
                   list_pending 出现 → decide(adopted) → pending 消失 →
                   重复裁决被拒（一次性留痕）
  06 媒体链        register_asset（license 必填硬闸＋sha256 去重）→
                   bind_asset（词目锚）→ 审定状态单步流转（候选→审定→发布，
                   跳级与越终点拒绝，advance_binding_status 乐观守卫）
  07 快照与漏斗    build_content_snapshot（dict_admin actor；非词典管理员
                   被 §15 闸门拒绝）→ export_batches 落行＋zip 存在；
                   get_cluster_pipeline_status('motion') 六段 data/reason
                   互斥；最后对全程审计线（assignments/ai_proposals/
                   export_batches 留痕行）做收口核验

环境约定（对齐 tests/test_e2e_workflow.py 的集成层模式）：

  * 专用预授权测试库 ``web_word_stage1_e2e_test``（scripts/grant_local_mysql.sql
    已 GRANT ALL）：类 fixture 先 DROP+CREATE（幂等、可重复执行），monkeypatch
    db.MYSQL_DATABASE 指向它，跑完 DROP —— 不碰生产库 web_word_db；
  * 基础表用 ``mysql_db.init_database()`` 建真实 schema（definitions/
    oald_senses/categories/cs_* 等），阶段 1 各模块再用各自 ensure_*_tables()
    幂等补建自有表（org/dict_admin/ai_ledger/media/export/flow）—— 与生产
    同构，不编最小假表；
  * MySQL 不可用 / 账号无建库权限时整类 skip（CI 无库依然全绿）；
  * 数据层签名以各模块实际实现为准（先 grep 核对过）。

依赖说明：07 用到 media_db.advance_binding_status（媒体绑定审定，R6-12 下沉
流转的唯一写路径，本模块导入但不触发任何 st. 渲染调用）。
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.ai_ledger import decide, get_proposal, list_pending, record_proposal  # noqa: E402
from src.annotation_flow import ensure_flow_tables  # noqa: E402
from src.collab_pages import (  # noqa: E402
    LOAD_LIMIT_DEFAULT,
    _check_load_limit,
    _check_role_matrix,
    create_assignment,
)
from src.dict_admin_db import start_batch  # noqa: E402
from src.media_db import advance_binding_status  # noqa: E402  R6-12 下沉
from src.export_center import EXPORT_ROOT, build_content_snapshot  # noqa: E402
from src.import_engine import plan_import, run_import  # noqa: E402
from src.media_db import (  # noqa: E402
    MEDIA_STATUS_CANDIDATE,
    MEDIA_STATUS_PUBLISHED,
    MEDIA_STATUS_REVIEWED,
    bind_asset,
    list_assets_for_anchor,
    register_asset,
)
from src.org_db import add_member, create_project, get_members, project_selfcheck  # noqa: E402
from src.pipeline_status import get_cluster_pipeline_status  # noqa: E402
from src.users_db import (  # noqa: E402
    create_user,
    grant_role,
    list_roles,
    needs_password_change,
    verify_login_full,
)

TEST_DB = "web_word_stage1_e2e_test"  # 预授权专库（scripts/grant_local_mysql.sql:129-130）
PREFIX = "stage1_z1_"  # 用户名前缀（专库按整库重建隔离，前缀仅便于人工辨识）
PASSWORD = "Stage1#E2e-pass"
CHIEF_NAME = PREFIX + "chief"
EDITOR_NAME = PREFIX + "editor"
TRAINEE_NAME = PREFIX + "trainee"

# 干跑导入映射与行（词目 'walk'/'jump' 不在库内 → preview 全为 insert，
# 与 fixture 预置的 'run' 行区分，零写库断言干净）
IMPORT_MAPPING = {"词目": "verb", "中文释义": "chinese_ndef", "音标": "phonetic"}
IMPORT_ROWS = [
    {"词目": "walk", "中文释义": "走；步行", "音标": "/wɔːk/"},
    {"词目": "jump", "中文释义": "跳", "音标": "/dʒʌmp/"},
]


def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不动库）。"""
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


def _q(sql: str, params: tuple = ()):
    """测试内直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过阶段 1 端到端验收（真库）")
class TestStageOneE2E:
    """七步阶段 1 链路端到端验收（专用真库，连续跑两遍都绿）。"""

    @pytest.fixture(scope="class", autouse=True)
    def stage1(self):
        """整库重建（DROP+CREATE）→ 真实 schema + 阶段 1 各模块建表 → yield 共享状态 → DROP。"""
        conn_params = dict(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            connect_timeout=3,
        )
        conn = pymysql.connect(**conn_params)
        try:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
                    cur.execute(
                        f"CREATE DATABASE `{TEST_DB}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
            except pymysql.err.OperationalError as e:
                pytest.skip(f"当前 MySQL 账号无建库权限，跳过阶段 1 端到端验收: {e}")
        finally:
            conn.close()

        old_database = db.MYSQL_DATABASE
        state: dict = {}
        try:
            db.MYSQL_DATABASE = TEST_DB

            # 基础 schema 与生产同构（CREATE TABLE IF NOT EXISTS 幂等 + 幂等迁移 + 视图）
            assert db.init_database(), (
                "init_database 失败：MySQL 不可用或账号对测试库无 DDL 权限"
            )
            # 阶段 1 各模块自含 DDL（幂等）：org/users 扩展 → dict_admin → ai → media → export → flow
            from src.dict_admin_db import ensure_dict_admin_tables
            from src.ai_ledger import ensure_ai_ledger_tables
            from src.media_db import ensure_media_tables
            from src.export_center import ensure_export_tables
            from src.org_db import ensure_org_tables

            ensure_org_tables()  # dictionary_projects/project_members（内含 ensure_user_tables）
            ensure_dict_admin_tables()  # custom_fields/custom_values/import_batches(+revert_log)
            ensure_ai_ledger_tables()  # ai_proposals
            ensure_media_tables()  # media_assets/media_bindings
            ensure_export_tables()  # export_batches
            ensure_flow_tables()  # assignments/annotation_submissions/adjudications

            # 底子数据：内置 admin（平台管理员，授权人）+ 词目 'run' 投影行
            # （供媒体词目锚与步骤 03 零写库对照；语义表/音标给最小真实值）
            rows = _q(
                "SELECT id FROM users WHERE username = 'admin' AND active = 1 ORDER BY id LIMIT 1"
            )
            assert rows, "内置 admin 不存在：ensure_user_tables 应幂等建出内置管理员"
            with db.get_db_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO definitions "
                    "(verb, chinese_ndef, semantic_table, phonetic, sense_count) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    ("run", "跑", "{}", "/rʌn/", 3),
                )
                run_definition_id = int(cursor.lastrowid)

            state["admin_id"] = int(rows[0]["id"])
            state["run_definition_id"] = run_definition_id
            yield state
        finally:
            # 收尾清理（best-effort）：放 finally —— 测试失败也要清产物不留工作区
            snapshot_dir = state.get("snapshot_dir")
            media_tmp_path = state.get("media_tmp_path")
            db.MYSQL_DATABASE = old_database
            # 丢弃指向已删库的连接池条目（键含库名，防死连接滞留）
            # 弹池键与 mysql_db._pool_key() 同口径（(host, port, db, user) 四元组）
            pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
            getattr(db, "_connection_pools", {}).pop(pool_key, None)
            conn = pymysql.connect(**conn_params)
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
            finally:
                conn.close()
            if snapshot_dir and str(snapshot_dir).startswith(str(EXPORT_ROOT)):
                shutil.rmtree(snapshot_dir, ignore_errors=True)
            if media_tmp_path:
                try:
                    os.unlink(media_tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------
    def _need(self, stage1, *keys):
        """前置步骤守卫：共享状态缺键即显式失败（提示按 01→07 整类执行）。"""
        missing = [k for k in keys if stage1.get(k) is None]
        if missing:
            pytest.fail(
                f"前置步骤未完成（缺状态键 {missing}）——本验收须按 01→07 定义序整类执行"
            )

    # ------------------------------------------------------------
    # 01 建号与授权链：create_user 默认 viewer → grant_role 提 dict_admin
    # ------------------------------------------------------------
    def test_01_account_grant_chain(self, stage1):
        admin_id = stage1["admin_id"]

        chief_id = create_user(CHIEF_NAME, PASSWORD, "验收词典管理员")  # 不传 role → 默认 viewer
        assert isinstance(chief_id, int) and chief_id > 0, "create_user 应返回新用户 id"
        stage1["chief_id"] = chief_id

        # 建号即 viewer：六角色表落行 + 登录全链路（含 roles 列表）+ 首登强制改密
        assert list_roles(chief_id) == ["viewer"], "新号默认应持有且仅持有 viewer"
        session = verify_login_full(CHIEF_NAME, PASSWORD)
        assert session and session["id"] == chief_id
        assert session["role"] == "viewer", "legacy role 键应为 viewer（向后兼容）"
        assert session["roles"] == ["viewer"]
        assert needs_password_change(chief_id) is True, "新号 must_change_password=1"
        audit = _q(
            "SELECT role, granted_by FROM user_roles WHERE user_id = %s AND role = 'viewer'",
            (chief_id,),
        )
        assert len(audit) == 1 and audit[0]["granted_by"] is None, (
            "user_roles 应有系统登记的 viewer 行（granted_by 为空）"
        )

        # 授权链：词典管理员授予（提权闸门口径：dict_admin 由既有管理员授）
        assert grant_role(chief_id, "dict_admin", granted_by=admin_id) is True
        assert grant_role(chief_id, "dict_admin", granted_by=admin_id) is False, (
            "重复授予（已持有）应返回 False（无实际变更口径）"
        )
        assert list_roles(chief_id) == ["dict_admin", "viewer"], (
            "六角色按优先级降序：dict_admin 在前、viewer 保留"
        )
        session2 = verify_login_full(CHIEF_NAME, PASSWORD)
        assert session2["roles"] == ["dict_admin", "viewer"], "登录会话 roles 应实时反映授权"
        assert session2["role"] == "viewer", "legacy role 键不变（叠加授权不动基线列）"
        audit2 = _q(
            "SELECT granted_by FROM user_roles WHERE user_id = %s AND role = 'dict_admin'",
            (chief_id,),
        )
        assert len(audit2) == 1 and int(audit2[0]["granted_by"]) == admin_id, (
            "授权留痕：user_roles.dict_admin 行 granted_by=授权人"
        )

    # ------------------------------------------------------------
    # 02 项目壳与成员：create_project（chief=管理员）→ add_member（编纂员）
    # ------------------------------------------------------------
    def test_02_project_shell_members(self, stage1):
        self._need(stage1, "chief_id")
        chief_id = stage1["chief_id"]

        # 编纂员账号：建号默认 viewer → chief 授 editor 六角色（三级最小权限链）
        editor_id = create_user(EDITOR_NAME, PASSWORD, "验收编纂员")
        assert isinstance(editor_id, int) and editor_id > 0
        assert list_roles(editor_id) == ["viewer"]
        assert grant_role(editor_id, "editor", granted_by=chief_id) is True
        stage1["editor_id"] = editor_id

        project_id = create_project("阶段1端到端验收项目", chief_id, ["motion"],
                                    description="批次8 Z1 端到端验收专用项目")
        assert isinstance(project_id, int) and project_id > 0, "create_project 应返回项目 id"
        stage1["project_id"] = project_id

        # chief 同事务入册：project_members 出现 chief 行（≥1 名 chief 约束的来源）
        members = get_members(project_id)
        chief_rows = [m for m in members if int(m["user_id"]) == chief_id]
        assert chief_rows and chief_rows[0]["project_role"] == "chief", (
            "create_project 应同事务册封 chief"
        )
        assert add_member(project_id, editor_id, "editor", granted_by=chief_id) is True

        # 自检全绿：项目存在 + ≥1 名 chief + chief 账号在用
        ok, problems = project_selfcheck(project_id)
        assert ok is True and problems == [], f"project_selfcheck 应全绿，实际 {problems}"
        # 审计线：dictionary_projects + project_members 留痕
        proj = _q("SELECT created_by, status FROM dictionary_projects WHERE id = %s", (project_id,))
        assert len(proj) == 1 and proj[0]["status"] == "active"
        assert int(proj[0]["created_by"]) == chief_id
        mrows = _q(
            "SELECT project_role FROM project_members WHERE project_id = %s ORDER BY user_id",
            (project_id,),
        )
        assert {r["project_role"] for r in mrows} == {"chief", "editor"}

    # ------------------------------------------------------------
    # 03 数据入口：run_import(dry_run=True) 零写库 + start_batch 台账登记
    # ------------------------------------------------------------
    def test_03_import_dry_run_and_batch_ledger(self, stage1):
        self._need(stage1, "project_id", "chief_id")
        project_id, chief_id = stage1["project_id"], stage1["chief_id"]

        # 纯函数计划层：映射合法、两行全过
        plan = plan_import(IMPORT_ROWS, IMPORT_MAPPING)
        assert plan["mapping_errors"] == []
        assert plan["rows_total"] == 2 and plan["rows_ok"] == 2 and plan["rows_rejected"] == 0

        before = int(_q("SELECT COUNT(*) AS n FROM definitions")[0]["n"])

        result = run_import(IMPORT_ROWS, IMPORT_MAPPING, operator=chief_id, dry_run=True)
        assert result["ok"] is True and result["dry_run"] is True
        assert result["rows_total"] == 2 and result["rows_ok"] == 2 and result["rows_rejected"] == 0
        assert result["mapping_errors"] == []
        # 干跑：revert_log 恒空；预览全为 insert（两动词不在库内），不给 row_id
        assert result["revert_log"] == []
        assert [p["action"] for p in result["preview"]] == ["insert", "insert"]
        assert all(p["row_id"] is None for p in result["preview"])

        # 零写库硬断言：definitions 行数不变，且 walk/jump 未出现
        after = int(_q("SELECT COUNT(*) AS n FROM definitions")[0]["n"])
        assert before == after == 1, f"干跑零写库：行数应保持 {before}，实际 {before}→{after}"
        assert not _q(
            "SELECT id FROM definitions WHERE verb IN (%s, %s)", ("walk", "jump")
        ), "干跑不应写库：walk/jump 不应存在"

        # 台账登记（§15 导入同权：operator=词典管理员，审计留痕）
        file_sha = hashlib.sha256(b"stage1-e2e-walk.xlsx").hexdigest()
        batch_id = start_batch(project_id, "stage1_e2e_walk.xlsx", file_sha,
                               "definitions", IMPORT_MAPPING, chief_id)
        assert isinstance(batch_id, int) and batch_id > 0, "start_batch 应返回批次 id"
        stage1["batch_id"] = batch_id
        brows = _q("SELECT * FROM import_batches WHERE id = %s", (batch_id,))
        assert len(brows) == 1
        brow = brows[0]
        assert brow["status"] == "running"
        assert int(brow["operator"]) == chief_id, "批次台账应留痕操作人（词典管理员）"
        assert int(brow["project_id"]) == project_id
        assert brow["file_sha256"] == file_sha.lower()
        assert json.loads(brow["mapping_json"]) == IMPORT_MAPPING, "映射应 JSON 留痕"
        # 干跑零写库 → 批次保持 running、行数三列 0（实跑/回滚链路由
        # test_import_engine/test_dict_admin_db 的集成用例覆盖，不在本场景编数）

    # ------------------------------------------------------------
    # 04 分派：角色矩阵两态 + create_assignment 落库 + 负荷上限
    # ------------------------------------------------------------
    def test_04_assignment_dispatch(self, stage1):
        self._need(stage1, "project_id", "chief_id", "editor_id")
        chief_id, editor_id = stage1["chief_id"], stage1["editor_id"]

        # 通过态：编纂员（editor 六角色）可承担标注类任务
        assert _check_role_matrix("feature_coding", list_roles(editor_id)) is None
        # 拒绝态：只读 viewer 不在矩阵内；未知任务类型 fail-closed
        trainee_id = create_user(TRAINEE_NAME, PASSWORD, "验收见习(只读)")  # 默认 viewer
        assert isinstance(trainee_id, int) and trainee_id > 0
        stage1["trainee_id"] = trainee_id
        reject_reason = _check_role_matrix("feature_coding", list_roles(trainee_id))
        assert reject_reason is not None and "任务×角色矩阵" in reject_reason, (
            f"viewer 承担标注任务应被矩阵拒绝，实际 {reject_reason!r}"
        )
        unknown_reason = _check_role_matrix("no_such_task", list_roles(editor_id))
        assert unknown_reason is not None and "未知任务类型" in unknown_reason

        # 分派落库（assignments 留痕行）
        task_id = create_assignment(editor_id, "feature_coding",
                                    scope_verbs=["run", "walk"], assigned_by=chief_id,
                                    category="motion")
        assert isinstance(task_id, int) and task_id > 0, "create_assignment 应返回任务 id"
        stage1["task_id"] = task_id
        arows = _q("SELECT * FROM assignments WHERE id = %s", (task_id,))
        assert len(arows) == 1
        arow = arows[0]
        assert int(arow["assignee_id"]) == editor_id
        assert int(arow["assigned_by"]) == chief_id
        assert arow["task_type"] == "feature_coding" and arow["category"] == "motion"
        assert arow["status"] == "open"
        assert json.loads(arow["scope_verbs"]) == ["run", "walk"]

        # 负荷上限（运行层默认 10）：cap=1 且已有 1 条在途 → 拒；默认上限 → 放行
        over_limit = _check_load_limit(editor_id, limit=1)
        assert over_limit is not None and "负荷上限" in over_limit, (
            f"在途任务数达到上限应拒绝，实际 {over_limit!r}"
        )
        assert _check_load_limit(editor_id, limit=LOAD_LIMIT_DEFAULT) is None, (
            "默认上限 10、仅在途 1 条应放行"
        )

    # ------------------------------------------------------------
    # 05 AI 提议→裁决：record_proposal → list_pending → decide(adopted)
    # ------------------------------------------------------------
    def test_05_ai_proposal_decision(self, stage1):
        self._need(stage1, "chief_id")
        chief_id = stage1["chief_id"]

        proposal_id = record_proposal(
            "draft", "sense_division", "cs_senses:cluster-1",
            proposal={"action": "merge", "targets": [11, 12], "note": "验收提议"},
            evidence_ref="configs/motion/pack.yaml#schemas",
            prompt_version="stage1-e2e-p1",
            resource_version="stage1-e2e-r1",
            uncertainty=0.4,
            created_by=chief_id,
        )
        assert isinstance(proposal_id, int) and proposal_id > 0, "record_proposal 应返回提案 id"
        stage1["proposal_id"] = proposal_id

        pending = list_pending(kind="draft", stage="sense_division")
        assert any(int(p["id"]) == proposal_id for p in pending), "提案应出现在待决列表"
        row = _q("SELECT status FROM ai_proposals WHERE id = %s", (proposal_id,))
        assert row and row[0]["status"] == "pending"

        # 裁决（词典管理员终裁）：采纳后退出待决列表，留痕不可覆盖
        assert decide(proposal_id, "adopted", "验收：采纳该义项分立提议", chief_id) is True
        pending_after = list_pending(kind="draft", stage="sense_division")
        assert not any(int(p["id"]) == proposal_id for p in pending_after), (
            "采纳后提案应退出待决列表"
        )
        assert decide(proposal_id, "rejected", "重复裁决尝试", chief_id) is False, (
            "重复裁决应被拒（一次性留痕，不改写首次结论）"
        )
        item = get_proposal(proposal_id)
        assert item["status"] == "adopted"
        assert int(item["decider_id"]) == chief_id
        assert item["decision_reason"] == "验收：采纳该义项分立提议"

    # ------------------------------------------------------------
    # 06 媒体链：register_asset（license 必填）→ bind_asset → 单步流转
    # ------------------------------------------------------------
    def test_06_media_chain(self, stage1):
        self._need(stage1, "run_definition_id")
        word_anchor_id = stage1["run_definition_id"]

        # 临时素材文件（png 字节，注册后收尾删除）
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="stage1_e2e_")
        with os.fdopen(fd, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nstage1-e2e-media-bytes")
        stage1["media_tmp_path"] = tmp_path

        # 许可硬闸：空 license 拒入库；合法登记返回 id
        assert register_asset(tmp_path, "image", "验收素材", "   ") == 0, (
            "空 license 应被拒（无许可不入库）"
        )
        asset_id = register_asset(tmp_path, "image", "阶段1验收素材",
                                  "CC BY-SA 4.0（e2e 测试）", mime="image/png")
        assert isinstance(asset_id, int) and asset_id > 0
        # sha256 去重：同内容重复登记返回已有 id，不新插行
        assert register_asset(tmp_path, "image", "阶段1验收素材",
                              "CC BY-SA 4.0（e2e 测试）", mime="image/png") == asset_id
        assert len(_q("SELECT id FROM media_assets WHERE id = %s", (asset_id,))) == 1

        # 绑定到词目锚（word 锚 = definitions.id；UNIQUE 幂等）
        assert bind_asset(asset_id, "word", word_anchor_id, purpose="illustration",
                          caption="验收图注：run", sort_order=1) is True
        bindings = _q(
            "SELECT id, status FROM media_bindings WHERE asset_id = %s "
            "AND anchor_type = 'word' AND anchor_id = %s AND purpose = 'illustration'",
            (asset_id, word_anchor_id),
        )
        assert len(bindings) == 1
        binding_id = int(bindings[0]["id"])
        assert bindings[0]["status"] == MEDIA_STATUS_CANDIDATE, "新绑定默认候选态"

        # 单步流转：候选→审定→发布；跳级/越终点拒绝（乐观并发守卫）
        assert advance_binding_status(
            binding_id, MEDIA_STATUS_CANDIDATE, MEDIA_STATUS_PUBLISHED) is False, (
            "候选→发布跳级应被拒（逐级不可跳）"
        )
        listed = list_assets_for_anchor("word", word_anchor_id)
        match = [r for r in listed if int(r["binding_id"]) == binding_id]
        assert match and match[0]["binding_status"] == MEDIA_STATUS_CANDIDATE, \
            "跳级被拒后仍是候选"
        assert match[0]["license"] == "CC BY-SA 4.0（e2e 测试）", "资产联查应带许可信息"

        assert advance_binding_status(
            binding_id, MEDIA_STATUS_CANDIDATE, MEDIA_STATUS_REVIEWED) is True
        assert advance_binding_status(
            binding_id, MEDIA_STATUS_REVIEWED, MEDIA_STATUS_PUBLISHED) is True
        assert advance_binding_status(
            binding_id, MEDIA_STATUS_PUBLISHED, MEDIA_STATUS_PUBLISHED) is False, (
            "发布为终点，不能再流转"
        )
        final = [r for r in list_assets_for_anchor("word", word_anchor_id)
                 if int(r["binding_id"]) == binding_id]
        assert final and final[0]["binding_status"] == MEDIA_STATUS_PUBLISHED

    # ------------------------------------------------------------
    # 07 快照与漏斗：build_content_snapshot（dict_admin）+ export_batches 落行
    #    + zip 存在；get_cluster_pipeline_status('motion') 各段 data/reason 互斥；
    #    收口核验全程审计线
    # ------------------------------------------------------------
    def test_07_snapshot_and_funnel(self, stage1):
        self._need(stage1, "chief_id", "task_id", "proposal_id")
        chief_id = stage1["chief_id"]

        # 重新登录取 actor（会话 dict 带 id/username/display_name/role/roles）
        actor = verify_login_full(CHIEF_NAME, PASSWORD)
        assert actor and "dict_admin" in actor["roles"], "chief 应以词典管理员身份登录"

        # §15 闸门：非词典管理员拒绝（不触库、不产文件）
        banned = build_content_snapshot(
            actor={"id": stage1["trainee_id"], "username": TRAINEE_NAME,
                   "role": "viewer", "roles": ["viewer"]},
        )
        assert banned["ok"] is False and "词典管理员" in banned.get("error", "")

        snapshot = build_content_snapshot(actor=actor, license_checked=False)
        assert snapshot["ok"] is True, snapshot.get("error")
        batch_id = int(snapshot["batch_id"])
        assert batch_id > 0
        zip_path = Path(snapshot["zip_path"])
        assert zip_path.is_file(), f"快照 zip 应存在：{zip_path}"
        stage1["snapshot_dir"] = zip_path.parent  # teardown 清理产物目录

        # 审计线：export_batches 落行（操作人/scope/状态/file_path）
        erows = _q("SELECT * FROM export_batches WHERE id = %s", (batch_id,))
        assert len(erows) == 1
        erow = erows[0]
        assert int(erow["operator_id"]) == chief_id
        assert erow["scope"] == "content_snapshot" and erow["status"] == "ready"
        assert erow["license_checked"] == 0, "未过 G6 许可终检应如实记 0（不得对外交付）"
        assert "definitions" in json.loads(erow["tables_included"]), (
            "预置词目行所在表应入快照清单"
        )

        import zipfile

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "MANIFEST.txt" in names and "definitions.csv" in names
            manifest = zf.read("MANIFEST.txt").decode("utf-8")
            assert "未过" in manifest, "license_checked=False 应在 MANIFEST 如实标注"
        assert snapshot["rows_total"] >= 1, "快照应至少含预置 definitions 1 行"

        # 十五工序漏斗聚合：六段 data/reason 互斥（空测试库各段如实给 reason）
        funnel = get_cluster_pipeline_status("motion")
        assert funnel["category"] == "motion"
        assert funnel["pack_name"] == "motion"
        segments = funnel["segments"]
        assert set(segments) == {
            "admission", "coding", "reliability", "clustering", "split_review", "authoring",
        }
        for name, seg in segments.items():
            data, reason = seg.get("data"), seg.get("reason")
            assert (data is None) != (reason is None), (
                f"漏斗段 {name} 的 data/reason 必须互斥，实际 data={data!r}, reason={reason!r}"
            )
            if data is None:
                assert isinstance(reason, str) and reason.strip(), (
                    f"缺数段 {name} 的 reason 应为非空说明"
                )

        # ---- 收口：全程审计线（assignments / ai_proposals / export_batches 留痕行）----
        assert _q("SELECT id FROM assignments WHERE id = %s", (stage1["task_id"],)), (
            "审计线缺失：步骤 04 的 assignments 行"
        )
        prow = _q("SELECT status FROM ai_proposals WHERE id = %s", (stage1["proposal_id"],))
        assert prow and prow[0]["status"] == "adopted", "审计线缺失：步骤 05 的 ai_proposals 行"
        assert _q("SELECT id FROM export_batches WHERE id = %s", (batch_id,)), (
            "审计线缺失：步骤 07 的 export_batches 行"
        )
