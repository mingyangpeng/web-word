"""RV-22 端到端回归固化（第 10 镜头，沿用 R9 回归固化先例）：批次 14~17 新功能的
六条跨模块链钉成防退化测试面。

既有 fx 系测试是各批次的单元/集成面（单模块签名、闸门、原子复验），本文件只补
「跨模块状态流转」的端到端固化 —— 每链一条测试函数，从真实入口一路断言到落库/
读回/页面呈现，模块间接线断裂或语义漂移即刻红：

  一、工具两步激活链（FX-18/RV14：tool_settings_db × tools/registry）
    sys_admin available_set → dict_admin enabled_set（先 enabled 拒＝两步次序闸）
    → DB 行 available/enabled 双 1 ＋ tool_version 快照 → bind_registry_loader
    绑定后 registry list_tools(enabled_only=True) 含该工具 → 审计行序
    （available_set/enabled_set，倒序读回）→ enabled_unset → available_unset
    → 行双 0、loader 读 False（持久化位优先于进程位）。

  二、质检→指标链（FX-25/FX-19：style_check × collab_metrics）
    run_style_check(category, dict_admin actor) 真跑 configs/motion（回退词典层
    style.yaml）→ run_id 落 style_check_runs → list_recent_runs 读回（run_by
    留痕、detail_json 逐项解析）→ collab_metrics.style_check_status 返回真值
    （pass_rate == passed/(passed+failed)）；「无记录范畴」与「库不可用/表未建」
    两类灰注态与真值态三分（available=False 不编数字）。
    现状锚（configs/style.yaml @ style_version 1.0，沙箱无媒体绑定 → 媒体抽查
    warn）：3 pass / 1 fail / 1 warn、total==5、pass_rate==0.75 —— configs 变更
    导致漂移时按结构性断言（total==三态和、rate==passed/(passed+failed)）改锚。

  三、广播→收件箱链（FX-30：org_db × broadcast_db）
    org 建项目＋成员入册 → dict_admin publish 两条 → list_broadcasts 按 id 倒序
    （标题/正文/发布人 username/display_name 字段往返）→ 成员 latest_for_user
    恰收每项目最新一条（含 project_name）→ 非成员空清单。

  四、改派→重标链（FX-20/RV13/RV14：org_db × annotation_flow × cluster 裁决态）
    建用户/项目/成员 → assignments open 态 round=1 → reassign_assignment 原子
    复验（assignee 换人成功＋assigned_by 同步执行人＋「改派审计」日志）→
    cs_senses merged 直插（分立裁决态种子）＋历史标注人提交 →
    create_reannotation_tasks → 历史标注人各得 round=2 任务 → 同批再发起
    幂等 dedup（库不翻倍）。

  五、登录落地三分支 e2e（FX-29/RV15：app.py × user_context_db，AppTest 真登录）
    (a) 无待办无续接点 → 落搜索释义（分支 3，不 flash）；
    (b) 全流程：登录 → radio 切页（上次工作位置）→ 登出（user_state 落
        resume_page＋会话全清）→ 再登录 → flash「已回到上次工作位置」且
        page==续接页（分支 2）。

  六、用户上下文跨设备续接（FX-31：user_context_db × app 落地 loader 缝）
    会话 A 写 user_state.resume_page → current_user 切另一会话同 uid（模拟跨
    设备登录）→ list_states 读回 → app._resume_page_loader 真适配器读到页键
    （上下文跟账号不跟会话）。

环境约定（对齐 tests/test_review_regression.py 的专库模式）：

  * 专用测试库 ``web_word_review_r18_test``（独立隔离，每用例 DROP+CREATE 重建，
    六链互不共享沙箱态）。授权 SQL 已按既有格式追加进 scripts/grant_local_mysql.sql：
        GRANT ALL PRIVILEGES ON `web\\_word\\_review\\_r18\\_test`.*
            TO 'web_word_user'@'127.0.0.1' / 'localhost' / '%';
    未授权（无建库权限）时库类用例自动 skip（MySQL 不可用同 skip）；
  * users 先建（ensure_user_tables 含内置 admin）—— org/flow/上下文域各表
    CASCADE FK 需真实 users 行；
  * 不 mock 被测模块本身：六链全部走真实数据层 API（registry 打桩零参与，
    loader 用真适配器；会话用户仅在 user_context_db 的 current_user 缝上注入
    —— 裸 pytest 无 Streamlit 会话，fx29/fx31 既有口径），只 patch 连接配置
    （db.MYSQL_DATABASE 指向专库）；
  * 注册表进程态（_ENABLED/依赖探针/DB loader 缝）与 app 续接点 loader 缝在
    autouse fixture 快照/还原，链间与跨模块互不泄漏。
"""

import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import src.mysql_db as db  # noqa: E402
import src.user_context_db as ucdb  # noqa: E402
from src.page_guides import page_label  # noqa: E402
from src.tools import builtin  # noqa: E402,F401  导入即注册内置 11 工具（真实注册路径）

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
TEST_DB = "web_word_review_r18_test"
TIMEOUT = 180
PREFIX = "r18_"
PASSWORD = "R18#regression-pass"


def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不动库）。"""
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

requires_db = pytest.mark.skipif(
    not HAS_MYSQL, reason=f"MySQL 不可用，跳过 RV-22 回归库用例（{TEST_DB}）")


def _q(sql, params=()):
    """测试内直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


@pytest.fixture(autouse=True)
def _isolate_registry():
    """注册表运行态快照/还原（进程 enabled 位/依赖探针/DB loader 缝；fx18 同款
    口径，不动 _REGISTRY —— 内置工具靠 import 时注册）。链 1 的绑定/解绑不跨
    用例泄漏，先前模块遗留的进程位也不污染本文件的断言面。"""
    from src.tools import registry as reg

    snap_enabled = set(reg._ENABLED)
    snap_probes = dict(reg._DEP_PROBES)
    snap_loader = reg._DB_ENABLED_LOADER
    yield
    reg._ENABLED.clear()
    reg._ENABLED.update(snap_enabled)
    reg._DEP_PROBES.clear()
    reg._DEP_PROBES.update(snap_probes)
    reg.set_db_enabled_loader(snap_loader)


@pytest.fixture(autouse=True)
def _reset_app_seams():
    """app 侧模块级缝复位（fx29 同款）：续接点 loader 缝与裸模式 flash 队列
    不跨用例泄漏（AppTest 以脚本形态执行 app.py，script 命名空间的缝自足）。"""
    yield
    import src.app as app_module
    from src import ui_kit

    app_module.set_resume_page_loader(None)
    try:
        ui_kit.st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)
    except Exception:  # noqa: BLE001 —— 裸模式无会话时忽略
        pass


@pytest.fixture()
def r18_env():
    """独立沙箱库（DROP+CREATE 整库重建）→ 真实 schema ＋ 各域建表 ＋ 全链
    用户，yield 共享状态 → 还原全局并 DROP。每条链独享沙箱态（函数级），链间
    零共享。users 先建 —— org/flow/上下文域 CASCADE FK 需真实 users 行。"""
    conn_params = dict(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        connect_timeout=3, autocommit=True,
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
            pytest.skip(
                f"账号对 {TEST_DB} 无建库权限，跳过 RV-22 回归库用例"
                f"（补授权 SQL 见 scripts/grant_local_mysql.sql）: {e}"
            )
    finally:
        conn.close()

    old_database = db.MYSQL_DATABASE
    state: dict = {}
    try:
        db.MYSQL_DATABASE = TEST_DB
        assert db.init_database(), "测试库初始化失败（无 DDL 权限或连接失败）"

        from src.ai_ledger import ensure_ai_ledger_tables
        from src.annotation_flow import ensure_flow_tables
        from src.broadcast_db import ensure_broadcast_table
        from src.media_db import ensure_media_tables
        from src.org_db import ensure_org_tables
        from src.tool_settings_db import ensure_tool_settings_tables
        from src.users_db import (
            create_user,
            ensure_user_tables,
            grant_role,
            list_roles,
        )

        ensure_user_tables()            # users 先建（CASCADE FK 的宿主）
        ensure_org_tables()
        ensure_flow_tables()
        ensure_media_tables()
        ensure_ai_ledger_tables()       # 收件箱 pending 计数走真表（空表 → 0）
        ensure_tool_settings_tables()
        ensure_broadcast_table()
        ucdb._TABLES_ENSURED = False    # 进程级哨兵复位（可能已被先前模块置位）
        ucdb.ensure_user_context_tables()

        def _mk(name, role, roles=()):
            """建真实账号并返回 (uid, 会话形态 actor dict)（与 verify_login_full
            输出同构：id/username/display_name/role/roles，roles 实时读库）。"""
            uid = create_user(PREFIX + name, PASSWORD, name + "（RV-22 回归）", role)
            assert isinstance(uid, int) and uid > 0, f"建号失败: {name}"
            for r in roles:
                assert grant_role(uid, r) is True
            return int(uid), {
                "id": int(uid), "username": PREFIX + name,
                "display_name": name + "（RV-22 回归）", "role": role,
                "roles": list_roles(uid),
            }

        state["uid_sys"], state["sys_admin_actor"] = _mk("sys", "viewer", ("sys_admin",))
        state["uid_chief"], state["chief_actor"] = _mk("chief", "viewer", ("dict_admin",))
        state["uid_ann_a"], _ = _mk("ann_a", "annotator")
        state["uid_ann_b"], _ = _mk("ann_b", "annotator")
        state["uid_newcomer"], _ = _mk("newcomer", "annotator")
        state["uid_member"], state["member_actor"] = _mk("member", "annotator")
        state["uid_outsider"], _ = _mk("outsider", "viewer")
        yield state
    finally:
        db.MYSQL_DATABASE = old_database
        # 丢弃指向已删库的连接池条目（键含库名）
        pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
        getattr(db, "_connection_pools", {}).pop(pool_key, None)
        try:
            db.get_full_word_graph.clear()
        except Exception:  # noqa: BLE001 —— 老版本无此缓存函数时忽略
            pass
        ucdb._TABLES_ENSURED = False    # 哨兵还原为待建态（不指向已删库）
        conn = pymysql.connect(**conn_params)
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        finally:
            conn.close()


# ============================================
# AppTest 辅助（fx29 真登录打桩同手法）
# ============================================

def _pget(at, key, default=None):
    """AppTest 会话读取（SafeSessionState 不支持 .get()）。"""
    try:
        return at.session_state[key]
    except Exception:  # noqa: BLE001
        return default


def _any_warning_containing(at, needle: str) -> bool:
    return any(needle in str(w.value) for w in at.warning)


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _form_login(at, username: str, password: str):
    """侧边栏登录表单真实提交（test_integration_apptest / fx29 同一手法）。"""
    inputs = {t.key: t for t in at.sidebar.text_input}
    inputs["login_username"].set_value(username)
    inputs["login_password"].set_value(password)
    submit = [b for b in at.sidebar.button
              if b.form_id and "登录" in str(b.label)]
    assert submit, "登录提交按钮未找到"
    submit[0].click()
    at.run()
    return at


def _goto(at, key: str):
    """点侧边栏导航按钮切页（批次 22 按钮式侧边栏）。"""
    for b in at.sidebar.button:
        if str(b.label) == page_label(key):
            b.click()
            at.run()
            return
    raise AssertionError(f"导航按钮不存在: {key}")


# ============================================
# 链 1：工具两步激活链（tool_settings_db × tools/registry）
# ============================================

@requires_db
class TestChain1ToolTwoStepActivation:
    """sys_admin available → dict_admin enabled → registry loader 绑定 →
    审计行序 → 反向撤位 → loader 读 False（两步激活的完整跨模块状态流转）。"""

    CATEGORY = "motion"
    TOOL = "corpus_evidence"       # 内置注册工具（导入 src.tools.builtin 即注册）

    def test_two_step_activation_full_chain(self, r18_env):
        from src import tool_settings_db as tsd
        from src.tools import registry as reg

        sys_actor = r18_env["sys_admin_actor"]
        chief_actor = r18_env["chief_actor"]
        cat, tool = self.CATEGORY, self.TOOL

        # 起点清场：缝解绑＋进程位熄灭（fixture 收尾快照还原）—— 断言只看本链
        tsd.bind_registry_loader(False)
        reg.set_enabled(tool, False)
        assert reg.get_tool(tool) is not None, "内置工具未注册（导入即注册路径断裂）"
        assert not any(t.id == tool for t in reg.list_tools(enabled_only=True))

        # 次序闸：available 未先行 → enabled_set 拒（两步激活语义，无审计行）
        assert tsd.enabled_set(cat, tool, chief_actor) is False
        assert tsd.get_setting(cat, tool) is None

        # 第一步：sys_admin available_set（available 独立于 enabled 存在）
        assert tsd.available_set(cat, tool, sys_actor) is True
        assert tsd.is_enabled(cat, tool) is False
        row = tsd.get_setting(cat, tool)
        assert row["available"] == 1 and row["enabled"] == 0

        # 第二步：dict_admin enabled_set → DB 行双 1 ＋ 注册表版本快照
        assert tsd.enabled_set(cat, tool, chief_actor) is True
        assert tsd.is_enabled(cat, tool) is True
        row = tsd.get_setting(cat, tool)
        assert row["available"] == 1 and row["enabled"] == 1
        assert row["tool_version"] == reg.get_tool(tool).version

        # registry loader 绑定后：list_tools(enabled_only=True) 含该工具
        # （DB 持久化位优先 —— enabled 位来自 category_tool_settings，非进程位）
        tsd.bind_registry_loader(True)
        assert tsd.registry_enabled_override(tool) is True
        assert any(t.id == tool for t in reg.list_tools(enabled_only=True))

        # 审计行序（created_at/id 倒序读回 = 动作逆序），who 逐行对号
        audit = tsd.list_audit(category=cat)
        assert [a["action"] for a in audit] == ["enabled_set", "available_set"]
        assert audit[0]["actor_id"] == chief_actor["id"]
        assert audit[0]["actor_username"] == chief_actor["username"]
        assert audit[1]["actor_id"] == sys_actor["id"]
        assert audit[1]["old_value"] is None            # 首置无旧值
        assert '"available": true' in audit[1]["new_value"]
        assert '"enabled": false' in audit[1]["new_value"]

        # 反向撤位：enabled_unset（词典管理员位）→ available_unset（平台管理员位）
        assert tsd.enabled_unset(cat, tool, chief_actor) is True
        assert tsd.available_unset(cat, tool, sys_actor) is True
        row = tsd.get_setting(cat, tool)
        assert row["available"] == 0 and row["enabled"] == 0

        # loader 读 False：行仍在（双 0），持久化位为准、registry 不再点亮
        assert tsd.registry_enabled_override(tool) is False
        assert not any(t.id == tool for t in reg.list_tools(enabled_only=True))

        # 审计全序：四个动作各一行、倒序恰为动作逆序
        actions = [a["action"] for a in tsd.list_audit(category=cat)]
        assert actions == [
            "available_unset", "enabled_unset", "enabled_set", "available_set",
        ]


# ============================================
# 链 2：质检→指标链（style_check × collab_metrics）
# ============================================

@requires_db
class TestChain2StyleCheckToMetrics:
    """run_style_check 真跑 configs → run 落库 → 读回 → 指标真值＋灰注三态。"""

    def test_style_check_runs_then_metrics_true_value(self, r18_env):
        from src import collab_metrics as cm
        from src.style_check import list_recent_runs, run_style_check

        chief = r18_env["chief_actor"]
        result = run_style_check("motion", actor=chief)
        assert result["ok"] is True
        run_id = result["run_id"]
        assert isinstance(run_id, int) and run_id > 0

        # run 落库读回：run_by 留痕＋计数一致＋detail_json 逐项解析
        rows = list_recent_runs("motion", limit=5)
        assert rows and rows[0]["id"] == run_id
        row = rows[0]
        assert row["category"] == "motion" and row["run_by"] == chief["id"]
        assert row["passed"] == result["passed"]
        assert row["failed"] == result["failed"]
        assert row["warned"] == result["warned"] and row["total"] == result["total"]
        assert isinstance(row["items"], list) and len(row["items"]) == result["total"]
        assert {it["code"] for it in row["items"]} == {
            "CFG_COMPLETE", "DEFINING_VOCAB", "SENSE_ORDERING",
            "MICROSTRUCTURE_SPINE", "MULTIMEDIA_BINDINGS",
        }

        # 指标真值：最近 1 次 run 投影，pass_rate == passed/(passed+failed)
        status = cm.style_check_status("motion")
        assert status["available"] is True
        assert status["run_id"] == run_id and status["run_category"] == "motion"
        passed, failed = status["passed"], status["failed"]
        assert status["total"] == passed + failed + status["warned"]
        assert status["pass_rate"] == pytest.approx(passed / (passed + failed))
        # 现状锚（configs/style.yaml @ style_version 1.0：3 pass/1 fail/1 warn，
        # 沙箱无媒体绑定 → 媒体抽查 warn；configs 变更漂移时改按上两行结构锚）
        assert (passed, failed, status["warned"], status["total"]) == (3, 1, 1, 5)
        assert status["pass_rate"] == 0.75

        # 灰注三态之二：无记录范畴（speech 无 run 记录 → 占位不编数字）
        empty_status = cm.style_check_status("speech")
        assert empty_status["available"] is False
        assert empty_status["pass_rate"] is None
        assert "尚未接入体例质检执行数据" in empty_status["note"]

        # 灰注三态之三：库不可用/表未建（DROP 后 list_recent_runs → None 归因）
        with db.get_db_cursor() as cursor:
            cursor.execute("DROP TABLE style_check_runs")
        dbdown = cm.style_check_status("motion")
        assert dbdown["available"] is False
        assert dbdown["pass_rate"] is None
        assert dbdown["note"] == (
            "数据库不可用或表未初始化，本指标暂无法统计（灰注降级，非 0）。")


# ============================================
# 链 3：广播→收件箱链（org_db × broadcast_db）
# ============================================

@requires_db
class TestChain3BroadcastToInbox:
    """org 建项目＋成员 → dict_admin 发布 → 倒序/收件箱聚合/非成员隔离。"""

    def test_publish_then_inbox_roundtrip(self, r18_env):
        from src.broadcast_db import latest_for_user, list_broadcasts
        from src.broadcast_db import publish_broadcast
        from src.org_db import add_member, create_project

        chief = r18_env["chief_actor"]
        member_id = r18_env["uid_member"]
        outsider_id = r18_env["uid_outsider"]

        pid = create_project("RV18 广播项目", chief["id"], ["motion"],
                             "端到端回归项目")
        assert isinstance(pid, int) and pid > 0
        assert add_member(pid, member_id, "annotator", chief["id"]) is True

        # dict_admin 发布两条（发布权闸 + 项目在册闸全走真库）
        first = publish_broadcast(pid, "首条广播", "版本 1.0 试点启动", chief)
        assert first["reason"] is None and isinstance(first["id"], int)
        second = publish_broadcast(pid, "最新广播", "义项排序规则已核定", chief)
        assert second["reason"] is None and isinstance(second["id"], int)

        # 发布页历史小表：按 id 倒序（最新在前）＋标题/发布人字段往返
        rows = list_broadcasts(pid)
        assert [r["id"] for r in rows] == [second["id"], first["id"]]
        newest = rows[0]
        assert newest["title"] == "最新广播"
        assert newest["body"] == "义项排序规则已核定"
        assert newest["project_id"] == pid
        assert newest["published_by"] == chief["id"]
        assert newest["publisher_username"] == chief["username"]
        assert newest["publisher_display_name"] == chief["display_name"]

        # 收件箱聚合：成员恰收每项目最新一条（含项目名）
        inbox = latest_for_user(member_id)
        assert inbox is not None and len(inbox) == 1
        assert inbox[0]["id"] == second["id"]
        assert inbox[0]["project_id"] == pid
        assert inbox[0]["project_name"] == "RV18 广播项目"
        assert inbox[0]["title"] == "最新广播"
        assert inbox[0]["published_by"] == chief["id"]
        assert inbox[0]["publisher_username"] == chief["username"]

        # 非成员不含：不在册用户收件箱为真空清单
        assert latest_for_user(outsider_id) == []


# ============================================
# 链 4：改派→重标链（org_db × annotation_flow × 分立裁决态）
# ============================================

@requires_db
class TestChain4ReassignToReannotation:
    """open 态分派改派换人（原子复验＋审计日志）→ 裁决态种子 → 重标 round=2
    派给历史标注人 → 同批再发起幂等 dedup。"""

    def test_reassign_then_reannotation_round2_with_dedup(self, r18_env, caplog):
        import logging

        from src.annotation_flow import (
            assign_task,
            create_reannotation_tasks,
            list_assignments_admin,
            reassign_assignment,
            submit_annotation,
        )
        from src.org_db import add_member, create_project

        chief = r18_env["chief_actor"]
        coder_a = r18_env["uid_ann_a"]
        coder_b = r18_env["uid_ann_b"]
        newcomer = r18_env["uid_newcomer"]

        pid = create_project("RV18 改派项目", chief["id"], ["motion"])
        assert isinstance(pid, int) and pid > 0
        assert add_member(pid, coder_a, "annotator", chief["id"]) is True
        assert add_member(pid, newcomer, "annotator", chief["id"]) is True

        # open 态 round=1 分派给 coder_a（台账读回核对）
        assert assign_task(coder_a, "motion", "feature_coding", ["run"],
                           chief["id"], round=1) is True
        ledger = list_assignments_admin(statuses=["open"])
        target = next(r for r in ledger if r["assignee_id"] == coder_a)
        assert target["status"] == "open" and target["round"] == 1
        aid = int(target["id"])

        # 改派（原子复验）：assignee 换人成功、assigned_by 同步执行人、审计日志
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            assert reassign_assignment(aid, pid, newcomer, chief["id"],
                                       actor=chief) is True
        row = _q("SELECT assignee_id, assigned_by, status, `round` "
                 "FROM assignments WHERE id=%s", (aid,))[0]
        assert int(row["assignee_id"]) == newcomer
        assert int(row["assigned_by"]) == chief["id"]
        assert row["status"] == "open" and int(row["round"]) == 1
        assert "改派审计" in caplog.text

        # 分立裁决态种子：cs_senses merged 直插（裁决落地态）＋历史标注人提交
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
                "VALUES (%s, %s, %s)", ("run", "跑", "{}"))
            did = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO oald_senses (definition_id, sense_index, definition, "
                "headword) VALUES (%s, %s, %s, %s)",
                (did, 1, "to move fast on foot", "run"))
            sense_id = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO categories (code, name_cn, name_en) "
                "VALUES (%s, %s, %s)", ("RUN", "跑", "Run"))
            cid = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO cs_lexemes (category_id, language, lemma, source_dict) "
                "VALUES (%s, %s, %s, %s)", (cid, "en", "run", "OALD10"))
            lid = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO cs_senses (lexeme_id, sense_no, sense_label, status) "
                "VALUES (%s, %s, %s, %s)", (lid, "1", "足部奔跑义", "merged"))
        assert submit_annotation("motion", sense_id, "feature_coding", coder_a,
                                 {"features": {"P1": 1}}) is True
        assert submit_annotation("motion", sense_id, "feature_coding", coder_b,
                                 {"features": {"P1": 0}}) is True

        # 发起重标：历史标注人各得 round=2 任务（round+1 闭环）
        first = create_reannotation_tasks("motion", [sense_id], 1, chief["id"],
                                          actor=chief)
        assert first["ok"] is True
        assert first["reannotation_round"] == 2
        assert first["created"] == 2 and first["dedup"] == 0
        assert set(first["coder_ids"]) == {coder_a, coder_b}
        round2 = _q("SELECT assignee_id FROM assignments WHERE category='motion' "
                    "AND task_type='feature_coding' AND `round`=2")
        assert {int(r["assignee_id"]) for r in round2} == {coder_a, coder_b}

        # 同批再发起：同轮幂等闸 → 零新建、dedup 计数、库不翻倍
        second = create_reannotation_tasks("motion", [sense_id], 1, chief["id"],
                                           actor=chief)
        assert second["ok"] is True
        assert second["created"] == 0 and second["dedup"] == 2
        assert "幂等跳过" in (second["note"] or "")
        assert len(_q("SELECT id FROM assignments WHERE category='motion' "
                      "AND task_type='feature_coding' AND `round`=2")) == 2


# ============================================
# 链 5：登录落地三分支 e2e（AppTest 真登录表单）
# ============================================

@requires_db
class TestChain5LandingBranches:
    """真登录表单全流程：分支 3（首次→search）与分支 2（登出落续接点→再登录
    回上次工作位置＋flash）。待办计数走真表（沙箱 ai_proposals 空 → 0）。"""

    def test_first_login_without_todo_and_resume_lands_search(self, r18_env):
        at = _new_at()
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        assert _pget(at, "user") is None
        assert _pget(at, "page") == "search"      # 未登录残留页回退（既有口径）

        at = _form_login(at, PREFIX + "ann_a", PASSWORD)
        assert not at.exception, [str(e.value) for e in at.exception]
        user = _pget(at, "user")
        assert isinstance(user, dict) and user["username"] == PREFIX + "ann_a"
        # 分支 3「首次」：无待办且无续接点 → 搜索释义
        assert _pget(at, "page") == "search"
        # 分支 3 不 flash（flash 是分支 2「回到上次位置」的可见面）
        assert not any("已回到上次工作位置" in str(e.value) for e in at.success)

    def test_logout_persists_resume_then_relogin_lands_last_page(self, r18_env):
        at = _new_at()
        at.run()
        at = _form_login(at, PREFIX + "ann_a", PASSWORD)
        assert _pget(at, "page") == "search", "前置：首次登录落搜索释义"

        # 上次工作位置：radio 手动切页
        _goto(at, "cluster")
        at.run()
        assert not at.exception
        assert _pget(at, "page") == "cluster"

        # 登出：user_state 落 resume_page（跨会话持久）＋会话全清＋登出提示
        logout = [b for b in at.sidebar.button if "退出登录" in str(b.label)]
        assert logout, "退出按钮未找到"
        logout[0].click()
        at.run()
        assert not at.exception
        assert _pget(at, "user") is None
        assert _any_warning_containing(at, "已退出登录")
        rows = _q("SELECT state_value FROM user_state WHERE state_key='resume_page'")
        assert rows and rows[0]["state_value"] == "cluster"

        # 再登录（同账号）：分支 2「有续接点」→ 落上次工作位置＋flash
        at = _form_login(at, PREFIX + "ann_a", PASSWORD)
        assert not at.exception, [str(e.value) for e in at.exception]
        assert _pget(at, "page") == "cluster", "再登录应回到登出时的工作页"
        assert any("已回到上次工作位置" in str(e.value) for e in at.success)


# ============================================
# 链 6：用户上下文跨设备续接（user_context_db × app 落地 loader 缝）
# ============================================

@requires_db
class TestChain6UserStateCrossDevice:
    """上下文跟账号不跟会话：会话 A 写 resume_page → 另一会话同 uid 读回 →
    落地 loader（真适配器）读到页键。"""

    def test_resume_page_survives_session_switch_same_uid(self, r18_env,
                                                          monkeypatch):
        import src.app as app_module

        uid = r18_env["uid_member"]
        device_a = dict(r18_env["member_actor"])   # 会话 A（本机登录态）
        device_b = dict(r18_env["member_actor"])   # 会话 B（另设备，同账号同 uid）

        app_module.set_resume_page_loader(app_module._resume_page_loader)
        monkeypatch.setattr(ucdb, "current_user", lambda: device_a)
        assert app_module._resume_page_loader(uid) is None   # 未写 → 无续接点

        assert ucdb.upsert_state("resume_page", "writing") is True

        # 切另一会话（同 uid）：跨设备登录后同一份 user_state 可读
        monkeypatch.setattr(ucdb, "current_user", lambda: device_b)
        rows = ucdb.list_states()
        match = [r for r in rows if r["state_key"] == "resume_page"]
        assert len(match) == 1 and match[0]["state_value"] == "writing"

        # 落地 loader 读到（app 缝绑定的真适配器，走会话派生 CRUD）
        assert app_module._resume_page_loader(uid) == "writing"
