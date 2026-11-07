"""阶段 2 编纂成文域端到端验收（真实 MySQL · 复用授权库 web_word_stage1_e2e_test）。

把批次 7/8 建成的编纂链路串成一条端到端场景（批次 9 · Agent AT），作为阶段 2
「能跑通」的证据。六步按定义序执行（类级 fixture 共享状态，方法名 01–06
即执行序；pytest 按类内定义序收集）：

  01 账号与授权链  内置 admin（平台管理员，授权人）→ chief 授 dict_admin →
                   chief 授 editor（撰写人）/ reviewer（审校人）——三级最小权限链
  02 撰写链第一轮  create_draft（三段式锚 speech:101:201）→ submit_for_review
                   回避制拒自审（reviewer=author 拒、状态保持 draft）→
                   正常提交（review_tasks round=1 pending）→ add_comment
                   （意见线；作者留言被回避制拒）→ request_revision 打回
                   （in_review→rejected，verdict=revision_requested）
  03 作者重提发布  create_draft(based_on_version=1) 断言 version+1/based_on_version
                   → 提交 → approve（in_review→final，MVP 单级终审）→
                   publish 非 dict_admin 拒 → publish（dict_admin）→ published；
                   final 终态后终裁不可再收口（adjudicate_final 拒）
  04 终裁直达发布  create_draft(based_on_version=2) → 提交 → adjudicate_final
                   非 dict_admin actor 拒（fail-closed）→ 终裁人=作者拒
                   （回避制含词典管理员）→ adjudicate_final(approved, dict_admin)
                   in_review→final 直达（例外通道）→ publish → published；
                   终裁留痕 = 新任务行（round+1、reviewer=终裁人），
                   受派审校人 pending 任务保持原样
  05 编纂侧例证与对译  lexical_db：例证三来源（corpus/adapted/composed）增改删
                   ＋审定态单步流转（候选→审定→发布；跳级/越终点拒）＋
                   set_translation 三态各一（full/partial/none）＋upsert 重定稿
                   （finalized_by/at 刷新，一义位一行）
  06 内容快照收口  build_content_snapshot：非 dict_admin 拒（§15 闸门）→
                   dict_admin 快照落 export_batches＋zip 存在；sense_examples/
                   sense_translations 在 CONTENT_TABLES（先 grep 确认）应入
                   tables_included 且 CSV 在 zip；编纂三表（definition_versions/
                   review_tasks/review_comments）不在 CONTENT_TABLES——如实断言
                   既不在 included 也不在 skipped（skipped 只收 CONTENT_TABLES
                   中未建的表，编纂三表整个不在快照范围，§15 内容域清单口径）；
                   最后对全程审计线做收口核验

环境约定（对齐 tests/test_stage1_e2e.py 的 Z1 口径）：

  * 复用预授权测试库 ``web_word_stage1_e2e_test``（scripts/grant_local_mysql.sql
    已 GRANT ALL）：类 fixture 先 DROP+CREATE（幂等、可重复执行），monkeypatch
    db.MYSQL_DATABASE 指向它，跑完 DROP —— 不碰生产库 web_word_db；与 Z1
    不可并行同跑（共用一库），pytest 顺序执行下先 DROP 后建互不污染；
  * 基础表用 mysql_db.init_database() 建真实 schema，编纂成文域各模块再用各自
    ensure_*_tables() 幂等补建（users/writing/lexical/export）——与生产同构；
  * MySQL 不可用 / 账号无建库权限时整类 skip（CI 无库依然全绿）；
  * 收口弃池：_pool_key() 是 (host, port, db, user) 四元组（mysql_db:888），
    teardown 按四元组键弹出测试库池条目，防死连接滞留。

如实记录（复用断点 R-5）：writing_db 的 sense_ref 是三段式锚
``范畴:cs_senses.id:oald_senses.id``，lexical_db 的 sense_ref 口径是
「cs_senses.id 字符串引用」（lexical_pages 传 str(sense_id)）——本测试统一用
三段式锚穿过两层（valid_sense_ref 兼容、_clean_ref 也接受），规避两锚分裂；
收口建议见 scripts/verify_category_reuse.py 的断点清单 R-5。
"""

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.export_center import CONTENT_TABLES, EXPORT_ROOT, build_content_snapshot  # noqa: E402
from src.lexical_db import (  # noqa: E402
    EXAMPLE_STATUSES,
    STATE_FULL,
    STATE_NONE,
    STATE_PARTIAL,
    SOURCE_ADAPTED,
    SOURCE_COMPOSED,
    SOURCE_CORPUS,
    STATUS_CANDIDATE as EXAMPLE_STATUS_CANDIDATE,
    STATUS_PUBLISHED as EXAMPLE_STATUS_PUBLISHED,
    STATUS_REVIEWED as EXAMPLE_STATUS_REVIEWED,
    add_example,
    advance_example_status,
    get_translation,
    list_examples,
    remove_example,
    set_translation,
    update_example,
)
from src.users_db import (  # noqa: E402
    create_user,
    grant_role,
    list_roles,
    verify_login_full,
)
from src.writing_db import (  # noqa: E402
    STATUS_DRAFT,
    STATUS_FINAL,
    STATUS_IN_REVIEW,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
    VERDICT_APPROVED,
    VERDICT_PENDING,
    VERDICT_REVISION_REQUESTED,
    add_comment,
    adjudicate_final,
    approve,
    create_draft,
    ensure_writing_tables,
    get_version,
    list_comments,
    list_pending_reviews,
    publish,
    request_revision,
    submit_for_review,
)

TEST_DB = "web_word_stage1_e2e_test"  # 预授权专库（scripts/grant_local_mysql.sql:129-130，与 Z1 复用）
PREFIX = "stage2_at_"  # 用户名前缀（专库按整库重建隔离，前缀仅便于人工辨识）
PASSWORD = "Stage2#E2e-pass"
CHIEF_NAME = PREFIX + "chief"
AUTHOR_NAME = PREFIX + "author"     # 撰写人（editor 六角色）
REVIEWER_NAME = PREFIX + "reviewer"  # 审校人（reviewer 六角色）

# 三段式义位锚（speech 范畴；cs_senses.id/oald_senses.id 槽位为软引用演示值）
SENSE_REF = "speech:101:201"
REF_FULL = "speech:101:201"     # 对译 full 态（与撰写链同义位，叙事连贯）
REF_PARTIAL = "speech:102:202"  # 对译 partial 态
REF_NONE = "speech:103:203"     # 对译 none 态


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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过阶段 2 端到端验收（真库）")
class TestStageTwoE2E:
    """六步批次 7/8 编纂链路端到端验收（专用真库，连续跑两遍都绿）。"""

    @pytest.fixture(scope="class", autouse=True)
    def stage2(self):
        """整库重建（DROP+CREATE）→ 真实 schema + 编纂域各模块建表 → yield 共享状态 → DROP。"""
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
                pytest.skip(f"当前 MySQL 账号无建库权限，跳过阶段 2 端到端验收: {e}")
        finally:
            conn.close()

        old_database = db.MYSQL_DATABASE
        state: dict = {}
        try:
            db.MYSQL_DATABASE = TEST_DB

            # 基础 schema 与生产同构（CREATE TABLE IF NOT EXISTS 幂等）
            assert db.init_database(), (
                "init_database 失败：MySQL 不可用或账号对测试库无 DDL 权限"
            )
            # 编纂成文域各模块自含 DDL（幂等）：users(+user_roles) → writing → lexical → export
            from src.export_center import ensure_export_tables
            from src.lexical_db import ensure_lexical_tables
            from src.users_db import ensure_user_tables

            ensure_user_tables()
            ensure_writing_tables()
            ensure_lexical_tables()
            ensure_export_tables()

            # 底子数据：内置 admin（平台管理员，授权链第一级授权人）
            rows = _q(
                "SELECT id FROM users WHERE username = 'admin' AND active = 1 ORDER BY id LIMIT 1"
            )
            assert rows, "内置 admin 不存在：ensure_user_tables 应幂等建出内置管理员"
            state["admin_id"] = int(rows[0]["id"])
            yield state
        finally:
            # 收尾清理（best-effort）：放 finally —— 测试失败也要清产物不留工作区
            snapshot_dir = state.get("snapshot_dir")
            # 弃池：_pool_key() 为 (host, port, db, user) 四元组（mysql_db._pool_key），
            # 须在还原 MYSQL_DATABASE 之前按测试库键弹出，防指向已删库的死连接滞留
            pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
            getattr(db, "_connection_pools", {}).pop(pool_key, None)
            db.MYSQL_DATABASE = old_database
            conn = pymysql.connect(**conn_params)
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
            finally:
                conn.close()
            if snapshot_dir and str(snapshot_dir).startswith(str(EXPORT_ROOT)):
                shutil.rmtree(snapshot_dir, ignore_errors=True)

    # ------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------
    def _need(self, stage2, *keys):
        """前置步骤守卫：共享状态缺键即显式失败（提示按 01→06 整类执行）。"""
        missing = [k for k in keys if stage2.get(k) is None]
        if missing:
            pytest.fail(
                f"前置步骤未完成（缺状态键 {missing}）——本验收须按 01→06 定义序整类执行"
            )

    # ------------------------------------------------------------
    # 01 账号与授权链：admin → chief(dict_admin) → author(editor)/reviewer(reviewer)
    # ------------------------------------------------------------
    def test_01_account_grant_chain(self, stage2):
        admin_id = stage2["admin_id"]

        chief_id = create_user(CHIEF_NAME, PASSWORD, "验收词典管理员")  # 建号默认 viewer
        assert isinstance(chief_id, int) and chief_id > 0, "create_user 应返回新用户 id"
        assert list_roles(chief_id) == ["viewer"], "新号默认应持有且仅持有 viewer"
        assert grant_role(chief_id, "dict_admin", granted_by=admin_id) is True, (
            "平台管理员授权链第一级：内置 admin 授 chief 词典管理员"
        )
        stage2["chief_id"] = chief_id

        author_id = create_user(AUTHOR_NAME, PASSWORD, "验收撰写编纂员")
        reviewer_id = create_user(REVIEWER_NAME, PASSWORD, "验收审校人")
        assert isinstance(author_id, int) and author_id > 0
        assert isinstance(reviewer_id, int) and reviewer_id > 0
        # 三级最小权限链第二级：词典管理员授予项目职能（数据层 grant_role 留痕 granted_by）
        assert grant_role(author_id, "editor", granted_by=chief_id) is True
        assert grant_role(reviewer_id, "reviewer", granted_by=chief_id) is True
        stage2["author_id"] = author_id
        stage2["reviewer_id"] = reviewer_id

        # 授权留痕：user_roles 行 granted_by 指向授权人（审计线）
        grant_rows = _q(
            "SELECT user_id, role, granted_by FROM user_roles "
            "WHERE user_id IN (%s, %s, %s) ORDER BY user_id, role",
            (chief_id, author_id, reviewer_id),
        )
        by_user: dict = {}
        for row in grant_rows:
            by_user.setdefault(int(row["user_id"]), {})[row["role"]] = int(
                row["granted_by"] or 0
            )
        assert by_user[chief_id]["dict_admin"] == admin_id
        assert by_user[author_id]["editor"] == chief_id
        assert by_user[reviewer_id]["reviewer"] == chief_id

        # 会话可用（后续步骤直接取 actor dict，publish/终裁以此判 dict_admin）
        chief_actor = verify_login_full(CHIEF_NAME, PASSWORD)
        assert chief_actor and "dict_admin" in chief_actor["roles"]
        stage2["chief_actor"] = chief_actor
        author_actor = verify_login_full(AUTHOR_NAME, PASSWORD)
        assert author_actor and "editor" in author_actor["roles"]
        stage2["author_actor"] = author_actor

    # ------------------------------------------------------------
    # 02 撰写链第一轮：建稿 → 回避制拒自审 → 提交 → 意见线 → 打回
    # ------------------------------------------------------------
    def test_02_draft_submit_comment_revise(self, stage2):
        self._need(stage2, "author_id", "reviewer_id")
        author_id, reviewer_id = stage2["author_id"], stage2["reviewer_id"]

        v1 = create_draft(
            SENSE_REF, author_id,
            "to tell（断言图式）：传递命题信息为重心的言说动词释义（第一稿）。",
            style_version="style.yaml@v1",
            ai_draft={"template_hint": "ASSERT", "drafted_by": "batch9-e2e"},
        )
        assert isinstance(v1, int) and v1 > 0, "create_draft 应返回新版本行 id"
        stage2["v1"] = v1
        row = get_version(v1)
        assert row["status"] == STATUS_DRAFT and int(row["version"]) == 1
        assert int(row["author_id"]) == author_id
        assert row["based_on_version"] is None
        assert row["ai_draft"] == {"template_hint": "ASSERT", "drafted_by": "batch9-e2e"}, (
            "ai_draft JSON 快照应解析回容器（审校对照用）"
        )

        # 回避制拒自审（§8 无豁免）：作者把稿子提交给自己审 → 拒，状态保持 draft
        assert submit_for_review(v1, author_id) is False, (
            "submit_for_review 回避制：reviewer=author 应被拒"
        )
        assert get_version(v1)["status"] == STATUS_DRAFT, "拒自审后状态应保持 draft"
        assert _q("SELECT id FROM review_tasks WHERE version_id = %s", (v1,)) == [], (
            "被拒提交不应留下半流转任务行"
        )

        # 正常提交：draft → in_review，创建待审任务（round=1 pending）
        assert submit_for_review(v1, reviewer_id, note="初稿提请审校") is True
        row = get_version(v1)
        assert row["status"] == STATUS_IN_REVIEW
        tasks = _q("SELECT * FROM review_tasks WHERE version_id = %s", (v1,))
        assert len(tasks) == 1
        assert int(tasks[0]["reviewer_id"]) == reviewer_id
        assert int(tasks[0]["round"]) == 1
        assert tasks[0]["verdict"] == VERDICT_PENDING
        assert tasks[0]["note"] == "初稿提请审校"

        # 意见线：受派审校人可挂；作者留言被回避制拒（意见线也是审校侧动作）
        comment_id = add_comment(v1, reviewer_id, "例证建议补直接引语论元（A1 核验区）")
        assert comment_id > 0, "审校人挂意见应成功"
        assert add_comment(v1, author_id, "作者自评（应被回避制拒）") == 0, (
            "add_comment 回避制：留言人=作者应被拒"
        )
        comments = list_comments(v1)
        assert len(comments) == 1 and comments[0]["resolved"] == 0
        assert list_comments(v1, only_open=True)
        # 收口只是标记不删行（D 域不删行纪律）
        assert list_comments(v1)[0]["id"] == comment_id
        from src.writing_db import resolve_comment

        assert resolve_comment(comment_id, True) is True
        assert list_comments(v1, only_open=True) == []
        assert len(list_comments(v1)) == 1, "收口后意见行仍在（标记不删行）"
        stage2["comment_id"] = comment_id

        # 打回：in_review → rejected，任务 verdict → revision_requested（仅受派审校人）
        assert request_revision(v1, reviewer_id, note="例证与对译未配置，先打回补齐") is True
        row = get_version(v1)
        assert row["status"] == STATUS_REJECTED
        tasks = _q(
            "SELECT verdict, note FROM review_tasks WHERE version_id = %s ORDER BY id",
            (v1,),
        )
        assert tasks[0]["verdict"] == VERDICT_REVISION_REQUESTED
        assert tasks[0]["note"] == "例证与对译未配置，先打回补齐", "打回理由应覆盖任务 note"

    # ------------------------------------------------------------
    # 03 作者重提 → 审校通过（MVP 终审）→ 发布（dict_admin）
    # ------------------------------------------------------------
    def test_03_resubmit_approve_publish(self, stage2):
        self._need(stage2, "v1", "author_id", "reviewer_id", "chief_actor")
        author_id = stage2["author_id"]
        reviewer_id, chief_actor = stage2["reviewer_id"], stage2["chief_actor"]

        # 作者重提：version 在 sense_ref 内自动 +1，based_on_version 挂被拒版号
        v2 = create_draft(
            SENSE_REF, author_id,
            "to tell（断言图式）：补齐例证与对译后的第二稿。",
            based_on_version=1,
        )
        assert isinstance(v2, int) and v2 > 0
        stage2["v2"] = v2
        row = get_version(v2)
        assert int(row["version"]) == 2, "重提应 version+1（sense_ref 内自动递增）"
        assert int(row["based_on_version"]) == 1, "based_on_version 应指向被拒版号"
        assert row["status"] == STATUS_DRAFT
        # based_on_version 指向不存在的版号 → 建版被拒（版本链完整性）
        assert create_draft(SENSE_REF, author_id, "断链稿", based_on_version=99) == 0, (
            "based_on_version 不存在应拒绝建版"
        )

        assert submit_for_review(v2, reviewer_id) is True
        # 审校通过（MVP 单级终审）：in_review → final，verdict → approved
        assert approve(v2, reviewer_id, note="例证对译齐备，通过") is True
        row = get_version(v2)
        assert row["status"] == STATUS_FINAL
        tasks = _q(
            "SELECT verdict FROM review_tasks WHERE version_id = %s ORDER BY id", (v2,)
        )
        assert tasks[0]["verdict"] == VERDICT_APPROVED

        # 发布闸门：非 dict_admin 拒（§8 出版批准归词典管理员）
        assert publish(v2, stage2["author_actor"]) is False, (
            "publish 回绝：editor 有效角色集不含 dict_admin"
        )
        assert get_version(v2)["status"] == STATUS_FINAL, "被拒发布后状态保持 final"
        # final 终态后终裁不可再收口（approve 已收口；in_review/approved 才可终裁）
        assert adjudicate_final(v2, stage2["chief_id"], "approved",
                                actor=chief_actor) is False, (
            "final 已是终态，终裁不可重复收口"
        )
        # 正式发布（dict_admin）：final → published
        assert publish(v2, chief_actor) is True
        assert get_version(v2)["status"] == STATUS_PUBLISHED
        # published 也是终态：重复发布/再终裁均拒
        assert publish(v2, chief_actor) is False

    # ------------------------------------------------------------
    # 04 词典管理员终裁直达（例外通道）：in_review → final → published
    # ------------------------------------------------------------
    def test_04_adjudicate_final_direct(self, stage2):
        self._need(stage2, "v2", "author_id", "reviewer_id", "chief_id", "chief_actor")
        author_id, reviewer_id = stage2["author_id"], stage2["reviewer_id"]
        chief_id, chief_actor = stage2["chief_id"], stage2["chief_actor"]

        v3 = create_draft(
            SENSE_REF, author_id,
            "to tell（断言图式）：争议词条第三稿，走词典管理员终裁通道。",
            based_on_version=2,
        )
        assert v3 > 0
        stage2["v3"] = v3
        row = get_version(v3)
        assert int(row["version"]) == 3 and int(row["based_on_version"]) == 2, (
            "版本链：v3 = v2 之后的重提（version+1，based_on_version=2）"
        )
        assert submit_for_review(v3, reviewer_id) is True

        # fail-closed：actor 未显式传入 / 非 dict_admin 一律拒
        assert adjudicate_final(v3, chief_id, "approved") is False, (
            "actor 缺失（未登录写路径）应 fail-closed"
        )
        assert adjudicate_final(v3, chief_id, "approved",
                                actor=stage2["author_actor"]) is False, (
            "终裁仅词典管理员：editor actor 应被拒"
        )
        assert get_version(v3)["status"] == STATUS_IN_REVIEW, "被拒终裁后状态保持 in_review"
        # 回避制无豁免，含词典管理员：终裁人=作者应拒
        assert adjudicate_final(v3, author_id, "approved", actor=chief_actor) is False
        # 非法 decision 拒（「要求修订」是受派审校人动作，不进终裁口径）
        assert adjudicate_final(v3, chief_id, "revision_requested",
                                actor=chief_actor) is False

        # 终裁通过：in_review → final 直达（两级终审例外通道，跳过中段占位枚举）
        assert adjudicate_final(v3, chief_id, "approved",
                                note="争议词条终裁通过（例外通道）",
                                actor=chief_actor) is True
        assert get_version(v3)["status"] == STATUS_FINAL

        # 留痕：终裁插入新任务行（round=MAX+1、reviewer=终裁人），不覆盖审校记录；
        # 受派审校人未决的 pending 任务保持原样
        tasks = _q(
            "SELECT reviewer_id, round, verdict, note FROM review_tasks "
            "WHERE version_id = %s ORDER BY id",
            (v3,),
        )
        assert len(tasks) == 2
        assert int(tasks[0]["reviewer_id"]) == reviewer_id
        assert tasks[0]["verdict"] == VERDICT_PENDING, "受派审校人 pending 任务保持原样"
        assert int(tasks[1]["reviewer_id"]) == chief_id
        assert int(tasks[1]["round"]) == 2, "终裁轮 round = MAX+1"
        assert tasks[1]["verdict"] == VERDICT_APPROVED
        assert tasks[1]["note"] == "争议词条终裁通过（例外通道）"
        # 待审清单（联结读侧）可见版本状态：v3 的 pending 任务仍在审校台视角中
        pending = list_pending_reviews(reviewer_id=reviewer_id)
        assert any(int(p["version_id"]) == v3 and p["status"] == STATUS_FINAL
                   for p in pending), "list_pending_reviews 应联结出版本行最新状态"

        assert publish(v3, chief_actor) is True
        assert get_version(v3)["status"] == STATUS_PUBLISHED

    # ------------------------------------------------------------
    # 05 编纂侧：例证三来源增改删＋审定单步流转＋对译三态定稿
    # ------------------------------------------------------------
    def test_05_examples_and_translations(self, stage2):
        self._need(stage2, "author_id", "chief_id")
        author_id, chief_id = stage2["author_id"], stage2["chief_id"]

        # 例证三来源（工序 11：语料草选 corpus → 人工改写 adapted → 自拟 composed）
        ex_corpus = add_example(REF_FULL, "「'I will come,' he said.」",
                                source=SOURCE_CORPUS, caption="enTenTen21 语料例",
                                created_by=author_id)
        ex_adapted = add_example(REF_FULL, "“我这就来。”他说。",
                                 source=SOURCE_ADAPTED, caption="语料例汉译改写",
                                 sort_order=1, created_by=author_id)
        ex_composed = add_example(REF_FULL, "他小声说了一句：好。",
                                  source=SOURCE_COMPOSED, created_by=author_id)
        assert all(e > 0 for e in (ex_corpus, ex_adapted, ex_composed)), (
            "三种来源例证均应落库（候选态起步）"
        )
        rows = list_examples(REF_FULL)
        assert len(rows) == 3
        assert {r["source"] for r in rows} == {SOURCE_CORPUS, SOURCE_ADAPTED, SOURCE_COMPOSED}
        assert {r["status"] for r in rows} == {EXAMPLE_STATUS_CANDIDATE}, (
            "新例证一律候选态起步"
        )
        assert [(r["sort_order"], r["id"]) for r in rows] == sorted(
            (r["sort_order"], r["id"]) for r in rows
        ), "list_examples 以 (sort_order, id) 稳定排序（装配确定性）"

        # 更新（Patch 语义）：仅非 None 字段入库；来源是改写标记，可随改
        assert update_example(ex_adapted, caption="改写例（含引语论元）", sort_order=2) is True
        matched = [r for r in list_examples(REF_FULL) if r["id"] == ex_adapted][0]
        assert matched["caption"] == "改写例（含引语论元）" and matched["sort_order"] == 2
        assert update_example(ex_adapted, source=SOURCE_CORPUS) is True, "来源可改（改写标记）"
        assert update_example(ex_adapted, source=SOURCE_ADAPTED) is True, "来源可改回"

        # 审定单步流转（候选→审定→发布；乐观并发守卫；跳级/越终点拒）
        assert advance_example_status(
            ex_corpus, EXAMPLE_STATUS_CANDIDATE, EXAMPLE_STATUS_REVIEWED) is True
        assert advance_example_status(
            ex_corpus, EXAMPLE_STATUS_REVIEWED, EXAMPLE_STATUS_PUBLISHED) is True
        assert advance_example_status(
            ex_adapted, EXAMPLE_STATUS_CANDIDATE, EXAMPLE_STATUS_PUBLISHED) is False, (
            "候选→发布跳级应被拒（逐级单步）"
        )
        assert advance_example_status(
            ex_corpus, EXAMPLE_STATUS_PUBLISHED, EXAMPLE_STATUS_REVIEWED) is False, (
            "发布为终态，不可回退"
        )
        published = [r for r in list_examples(REF_FULL, status=EXAMPLE_STATUS_PUBLISHED)]
        assert [r["id"] for r in published] == [ex_corpus]
        assert set(EXAMPLE_STATUSES) == {
            EXAMPLE_STATUS_CANDIDATE, EXAMPLE_STATUS_REVIEWED, EXAMPLE_STATUS_PUBLISHED,
        }

        # 删除（本模块唯一物理删接口；例证可重建、不是词典正文）
        assert remove_example(ex_composed) is True
        assert remove_example(ex_composed) is False, "重复删除（行已不在）应 False"
        assert len(list_examples(REF_FULL)) == 2

        # 对译三态定稿（工序 12）：full / partial / none 各一
        assert set_translation(REF_FULL, STATE_FULL, equivalent="say",
                               note="通用言说动词", finalized_by=author_id) is True
        assert set_translation(REF_PARTIAL, STATE_PARTIAL, equivalent="order",
                               note="祈使语气，常接 to 不定式", finalized_by=chief_id) is True
        assert set_translation(REF_NONE, STATE_NONE,
                               paraphrase="（无对应词）传递命题信息的言说行为",
                               finalized_by=chief_id) is True
        t_full = get_translation(REF_FULL)
        t_partial = get_translation(REF_PARTIAL)
        t_none = get_translation(REF_NONE)
        assert t_full["state"] == STATE_FULL and t_full["equivalent"] == "say"
        assert t_full["paraphrase"] is None
        assert int(t_full["finalized_by"]) == author_id and t_full["finalized_at"]
        assert t_partial["state"] == STATE_PARTIAL and t_partial["note"].startswith("祈使语气")
        assert t_none["state"] == STATE_NONE and t_none["equivalent"] == ""
        assert t_none["paraphrase"] and "言说行为" in t_none["paraphrase"]

        # upsert 重定稿：一义位一行（UNIQUE），三态口径可改、定稿人/时间刷新
        assert set_translation(REF_FULL, STATE_NONE,
                               paraphrase="改口径后的释义翻译",
                               finalized_by=chief_id) is True
        t_full_after = get_translation(REF_FULL)
        assert t_full_after["state"] == STATE_NONE and t_full_after["equivalent"] == ""
        assert int(t_full_after["finalized_by"]) == chief_id, "重定稿应刷新定稿人"
        assert t_full_after["finalized_at"] >= t_full["finalized_at"], "重定稿应刷新定稿时间"
        trans_rows = _q("SELECT id FROM sense_translations")
        assert len(trans_rows) == 3, "三态各一义位一行（upsert 不增行）"

    # ------------------------------------------------------------
    # 06 内容快照收口：§15 闸门 ＋ CONTENT_TABLES 收录口径 ＋ export_batches 留痕
    # ------------------------------------------------------------
    def test_06_content_snapshot_closing(self, stage2):
        self._need(stage2, "chief_actor", "author_actor", "v1", "v2", "v3")
        chief_actor, chief_id = stage2["chief_actor"], stage2["chief_id"]

        # §15 闸门：非词典管理员拒绝（不触库、不产文件）
        banned = build_content_snapshot(actor=stage2["author_actor"])
        assert banned["ok"] is False and "词典管理员" in banned.get("error", "")

        snapshot = build_content_snapshot(actor=chief_actor, license_checked=False)
        assert snapshot["ok"] is True, snapshot.get("error")
        batch_id = int(snapshot["batch_id"])
        zip_path = Path(snapshot["zip_path"])
        assert zip_path.is_file(), f"快照 zip 应存在：{zip_path}"
        stage2["snapshot_dir"] = zip_path.parent  # teardown 清理产物目录

        # 收录口径（先 grep 确认 CONTENT_TABLES，再如实断言）：
        # lexical 两表在 CONTENT_TABLES 且已建 → tables_included
        assert "sense_examples" in CONTENT_TABLES and "sense_translations" in CONTENT_TABLES, (
            "grep 前提：sense_examples/sense_translations 应在 CONTENT_TABLES 清单"
        )
        assert "sense_examples" in snapshot["tables_included"], (
            "例证表应入快照（有 2 行，CSV 落 zip）"
        )
        assert "sense_translations" in snapshot["tables_included"], (
            "对译表应入快照（有 3 行，CSV 落 zip）"
        )
        # 编纂三表不在 CONTENT_TABLES（§15 内容域清单口径）→ 整个不在快照范围：
        # 不在 included（未导出）、也不在 skipped（skipped 只收 CONTENT_TABLES 中未建的表）
        for writing_table in ("definition_versions", "review_tasks", "review_comments"):
            assert writing_table not in CONTENT_TABLES, (
                f"grep 前提变化：{writing_table} 已进入 CONTENT_TABLES，"
                "本用例的「编纂三表不在快照范围」断言需按新口径重写"
            )
            assert writing_table not in snapshot["tables_included"]
            assert writing_table not in snapshot["tables_skipped"]
        # 未建的内容表（media/custom 两族不在本测试 fixture 范围）→ 如实进 skipped
        assert "media_assets" in snapshot["tables_skipped"], (
            "表未建应如实记 skipped（不编空文件）"
        )

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "MANIFEST.txt" in names
            assert "sense_examples.csv" in names
            assert "sense_translations.csv" in names
            manifest = zf.read("MANIFEST.txt").decode("utf-8")
            assert "未过" in manifest, "license_checked=False 应在 MANIFEST 如实标注"
        assert snapshot["rows_total"] >= 5, "快照应含例证 2 行＋对译 3 行（≥5）"

        # 审计线：export_batches 落行（操作人/scope/状态/许可位）
        erows = _q("SELECT * FROM export_batches WHERE id = %s", (batch_id,))
        assert len(erows) == 1
        erow = erows[0]
        assert int(erow["operator_id"]) == chief_id
        assert erow["scope"] == "content_snapshot" and erow["status"] == "ready"
        assert erow["license_checked"] == 0, "未过 G6 许可终检应如实记 0"
        assert set(json.loads(erow["tables_included"])) >= {"sense_examples",
                                                            "sense_translations"}

        # ---- 收口：全程审计线（撰写链三版本 / 任务行 / 意见行 / 编纂侧两表）----
        versions = _q(
            "SELECT id, version, status, based_on_version FROM definition_versions "
            "WHERE sense_ref = %s ORDER BY version",
            (SENSE_REF,),
        )
        assert [(int(v["version"]), v["status"]) for v in versions] == [
            (1, STATUS_REJECTED), (2, STATUS_PUBLISHED), (3, STATUS_PUBLISHED),
        ], "三版本脊柱收口：v1 被打回 / v2、v3 均发布（两条收口路径各一）"
        assert versions[1]["based_on_version"] == 1 and versions[2]["based_on_version"] == 2
        task_rows = _q("SELECT id FROM review_tasks")
        assert len(task_rows) >= 4, "审计线：1(v1) + 1(v2) + 2(v3) 条任务行"
        assert _q("SELECT id FROM review_comments WHERE id = %s", (stage2["comment_id"],)), (
            "审计线缺失：意见线行（收口标记不删行）"
        )
        assert len(_q("SELECT id FROM sense_examples")) == 2
        assert len(_q("SELECT id FROM sense_translations")) == 3
