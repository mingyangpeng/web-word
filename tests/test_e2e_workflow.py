"""多人标注系统 R5 端到端验收（真实 MySQL · 完整协作工作流，可重复执行）。

七步验收流程（docs/review_R5.md 的可重复执行依据）：

  1 准备    ensure_user_tables + ensure_flow_tables；以 admin 建两个 annotator
            （coderA/coderB）与一个 reviewer；admin assign_task ×2
            （category=motion, task_type=admission, scope_verbs=["run","walk"]）
  2 提交    从 oald_senses 取 run 的 3 个真实义位 id；coderA/coderB 各对 3 义位提交
            admission 标注（payload 含 admission/schema/alignment/cn_syntax/
            strategy/needs_review；设计为 2 义位两人一致、1 义位 admission 分歧）
  3 独立性  coderA 调 get_my_submissions 只见自己 3 条；detect_disagreements
            （reviewer 视角）恰报 1 条分歧，且 fields 含两个 coder 的取值
  4 信度    run_reliability("motion","admission", features_meta 可空) → n_coders=2、
            n_units=3、overall_alpha 为数值且 <1（2 人 3 义位含 1 处分歧）；
            reliability_runs 落库一条
  5 仲裁    reviewer 对分歧义位 save_adjudication（gold admission=Y，note 说明理由）
            → adjudications 出现记录、submission 状态流转正确；复核：被仲裁提交
            退出信度口径（α 回到 1.0、n_units=2）
  6 范畴包  load_pack("motion") 成功且 features 15 项 in_clustering；
            load_pack("speech") 成功
  7 清理    删除本测试产生的 users/assignments/submissions/adjudications
            （按用户名前缀定位）与 reliability_runs（按 id 水位线），保证可重复执行

执行次序说明（任务书第 4/5 步）：任务书把「信度」列在「仲裁」之后，但按设计规范
（docs/p1/多人标注系统设计规范.md §3 + annotation_flow.save_adjudication 契约），
仲裁会把参与提交置为 'adjudicated' 并使其**退出**信度口径（reliability 只统计
status='submitted'）——分歧一旦仲裁，「n_units=3、α<1」的快照不可复现。因此本
脚本先取仲裁前信度快照（内部步骤 4），再做仲裁并复核退出行为（内部步骤 5）。
任务书两步的全部断言均被覆盖，仅执行次序依数据流语义调整。

环境约定（与 test_users_db / test_annotation_flow 集成层同一约定）：

  * 跑在真实库 web_word_db（**不用**独立测试库：步骤 2 要求 oald_senses 里 run 的
    真实义位 id）；数据隔离靠专用前缀 ``e2e_r5_`` 的用户名 + 结尾强清理；
  * MySQL 不可用时整类 skip（类级 skipif），CI 无库依然全绿；
  * 前置条件（fail-fast 并给诊断）：("motion", "admission") 提交切片必须为空，
    否则外部标注会混进分歧清单与 α 计数，验收数字失真；
  * reliability_runs 无用户外键，无法按前缀定位 —— 以测试开始时的 MAX(id) 为水位线，
    结尾删除水位线之上的行（另有 run_reliability 返回的 run_id 兜底）。
"""

import os
import sys

import pytest
import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.annotation_flow as flow  # noqa: E402
import src.mysql_db as db  # noqa: E402
from src.annotation_flow import (  # noqa: E402
    assign_task,
    detect_disagreements,
    ensure_flow_tables,
    get_my_submissions,
    get_submissions_for_sense,
    save_adjudication,
    submit_annotation,
)
from src.category_pack import load_pack  # noqa: E402
from src.reliability import run_reliability  # noqa: E402
from src.users_db import create_user, ensure_user_tables, verify_login  # noqa: E402

# ============================================
# 前缀隔离（本测试全部用户的用户名前缀；LIKE 里下划线需转义）
# ============================================
PREFIX = "e2e_r5_"
PREFIX_LIKE = "e2e\\_r5\\_%"
CODER_A_NAME = PREFIX + "coderA"
CODER_B_NAME = PREFIX + "coderB"
REVIEWER_NAME = PREFIX + "reviewer"
E2E_PASSWORD = "E2e#R5-pass"


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


# ============================================
# 清理（前置自愈 + 结尾强清理共用）
# ============================================
def _cleanup_prefixed_rows(conn) -> int:
    """删除本测试（前缀用户）产生的全部协作数据，返回删除的用户数。

    删除顺序满足外键依赖：adjudications → annotation_submissions → assignments
    → users。reliability_runs 无用户外键，由调用方按 id 水位线 / run_id 清理。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username LIKE %s", (PREFIX_LIKE,))
        ids = [int(r["id"]) for r in cur.fetchall()]
        if ids:
            placeholders = ", ".join(["%s"] * len(ids))
            cur.execute(
                f"DELETE FROM adjudications WHERE adjudicator_id IN ({placeholders})", ids
            )
            cur.execute(
                f"DELETE FROM annotation_submissions WHERE coder_id IN ({placeholders})", ids
            )
            cur.execute(
                f"DELETE FROM assignments WHERE assignee_id IN ({placeholders})", ids
            )
            cur.execute(f"DELETE FROM users WHERE id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)


@pytest.fixture
def e2e_env():
    """真实库直连（不经应用连接池）：前置自愈 → yield → 结尾强清理 + 自校验。"""
    # autocommit=True：与被测数据层（get_db_cursor 默认 autocommit）同口径，
    # 否则本连接的 REPEATABLE READ 快照看不见连接池连接写入的行（实测踩过）。
    conn = pymysql.connect(
        host=db.MYSQL_HOST,
        port=db.MYSQL_PORT,
        user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD,
        database=db.MYSQL_DATABASE,
        charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=3,
    )
    state = {"conn": conn, "waterline": None, "run_ids": []}
    try:
        # 0a) 前置自愈：清掉上次异常中断残留的前缀用户及其协作数据
        _cleanup_prefixed_rows(conn)

        # 0b) reliability_runs 水位线（表可能尚未建 —— 首次运行由步骤 4 创建）
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM reliability_runs")
                state["waterline"] = int(cur.fetchone()["m"])
            except pymysql.err.ProgrammingError:
                conn.rollback()
                state["waterline"] = None

        # 0c) 前置条件：(motion, admission) 切片必须为空（外部数据会污染分歧/α 计数）
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT coder_id FROM annotation_submissions "
                "WHERE category = 'motion' AND task_type = 'admission'"
            )
            foreign = [int(r["coder_id"]) for r in cur.fetchall()]
        assert not foreign, (
            "E2E 前置条件不满足：annotation_submissions 的 (motion, admission) 切片非空"
            f"（外来 coder_id={foreign}）。本验收要求干净切片，否则分歧清单与 α 会把"
            "外部标注算进来。请先清理该切片或在安静窗口重跑。"
        )
        yield state
    finally:
        try:
            # 7) 清理：前缀用户的全部协作数据 + 本测试产生的 reliability_runs 行
            _cleanup_prefixed_rows(conn)
            with conn.cursor() as cur:
                if state["run_ids"]:
                    placeholders = ", ".join(["%s"] * len(state["run_ids"]))
                    cur.execute(
                        f"DELETE FROM reliability_runs WHERE id IN ({placeholders})",
                        state["run_ids"],
                    )
                if state["waterline"] is not None:
                    cur.execute(
                        "DELETE FROM reliability_runs WHERE id > %s",
                        (state["waterline"],),
                    )
            conn.commit()
            # 清理自校验：前缀用户必须归零（残留即报错，保证下一遍可跑）
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE username LIKE %s",
                    (PREFIX_LIKE,),
                )
                leftover = int(cur.fetchone()["n"])
            assert leftover == 0, f"清理不彻底：仍残留 {leftover} 个前缀用户"
        finally:
            conn.close()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 R5 e2e 验收（真实 MySQL 协作工作流）")
class TestE2EWorkflow:
    """七步协作工作流端到端验收（真实库 + 前缀隔离，连续跑两遍都绿）。"""

    def test_full_collaboration_workflow(self, e2e_env):
        conn = e2e_env["conn"]

        def _step(label: str, summary: str) -> None:
            print(f"[{label}] {summary}")

        # ============================================================
        # 步骤 1 · 准备：建表 + admin 身份 + 3 个账号 + 2 条任务分配
        # ============================================================
        ensure_user_tables()   # users 表（幂等；表非空不重复建内置 admin）
        ensure_flow_tables()   # assignments / annotation_submissions / adjudications

        admin = verify_login("admin", "admin123")
        if admin is None:
            # 环境的内置 admin 已按规范改密：退化为取任一 active admin 的 id
            # （分配流只需要 admin 的 user id 作 assigned_by 外键）
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username FROM users "
                    "WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1"
                )
                row = cur.fetchone()
            assert row, "环境中不存在任何可用 admin（role=admin AND active=1）"
            admin = {"id": int(row["id"]), "username": row["username"], "role": "admin"}

        coder_a = create_user(CODER_A_NAME, E2E_PASSWORD, "验收标注员A", "annotator")
        coder_b = create_user(CODER_B_NAME, E2E_PASSWORD, "验收标注员B", "annotator")
        reviewer = create_user(REVIEWER_NAME, E2E_PASSWORD, "验收审核员", "reviewer")
        assert all(isinstance(u, int) for u in (coder_a, coder_b, reviewer)), (
            f"建号失败: coderA={coder_a}, coderB={coder_b}, reviewer={reviewer}"
        )
        # 登录全链路（pbkdf2 哈希校验 + active=1）逐个走通
        for uid, uname, role in (
            (coder_a, CODER_A_NAME, "annotator"),
            (coder_b, CODER_B_NAME, "annotator"),
            (reviewer, REVIEWER_NAME, "reviewer"),
        ):
            session = verify_login(uname, E2E_PASSWORD)
            assert session and session["id"] == uid and session["role"] == role

        assert assign_task(coder_a, "motion", "admission", ["run", "walk"], admin["id"])
        assert assign_task(coder_b, "motion", "admission", ["run", "walk"], admin["id"])
        with conn.cursor() as cur:
            cur.execute(
                "SELECT assignee_id, scope_verbs, assigned_by FROM assignments "
                "WHERE assignee_id IN (%s, %s) AND category = 'motion' "
                "AND task_type = 'admission'",
                (coder_a, coder_b),
            )
            assignment_rows = cur.fetchall()
        assert len(assignment_rows) == 2, f"应落 2 条分配，实际 {len(assignment_rows)}"
        for r in assignment_rows:
            assert flow._parse_json_list(r["scope_verbs"]) == ["run", "walk"]
            assert int(r["assigned_by"]) == admin["id"]
        _step(
            "步骤1·准备",
            f"ensure_user_tables/ensure_flow_tables OK；admin(id={admin['id']}) 建号 "
            f"coderA={coder_a}, coderB={coder_b}, reviewer={reviewer} 且三人登录成功；"
            "assign_task×2 落 assignments 2 行（scope_verbs=[run,walk]）",
        )

        # ============================================================
        # 步骤 2 · 提交：run 的 3 个真实义位 × 2 coder（2 一致 + 1 admission 分歧）
        # ============================================================
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM oald_senses WHERE headword = 'run' "
                "AND id NOT IN (SELECT sense_id FROM annotation_submissions "
                "               WHERE task_type = 'admission') "
                "AND id NOT IN (SELECT sense_id FROM adjudications "
                "               WHERE task_type = 'admission') "
                "ORDER BY id LIMIT 3"
            )
            sense_ids = [int(r["id"]) for r in cur.fetchall()]
        assert len(sense_ids) == 3, (
            f"run 的干净真实义位不足 3 个（未标注/未仲裁），实际: {sense_ids}"
        )

        def _payload(admission, schema, alignment, cn_syntax, strategy, needs_review):
            return {
                "admission": admission,
                "schema": schema,
                "alignment": alignment,
                "cn_syntax": cn_syntax,
                "strategy": strategy,
                "needs_review": needs_review,
            }

        # 三义位设计：前 2 个两人全字段一致；第 3 个仅 admission 分歧（A=Y / B=N）
        design = {
            sense_ids[0]: ("Y", "MANNER_ACCOMP", "VO", "连动式", "直译", False),
            sense_ids[1]: ("EXT", "SOURCE_DETACH", "VO", "动趋式", "直译", True),
            sense_ids[2]: ("Y", "GOAL_ARRIVE", "SV", "把字句", "意译", True),
        }
        for sid, (admission, schema, alignment, cn, strategy, nr) in design.items():
            assert submit_annotation(
                "motion", sid, "admission", coder_a,
                _payload(admission, schema, alignment, cn, strategy, nr),
            ), f"coderA 提交失败 sense={sid}"
            b_admission = "N" if sid == sense_ids[2] else admission
            assert submit_annotation(
                "motion", sid, "admission", coder_b,
                _payload(b_admission, schema, alignment, cn, strategy, nr),
            ), f"coderB 提交失败 sense={sid}"

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM annotation_submissions "
                "WHERE category = 'motion' AND task_type = 'admission'"
            )
            assert int(cur.fetchone()["n"]) == 6, "应有 6 条提交（3 义位 × 2 人）"
        _step(
            "步骤2·提交",
            f"取 run 真实义位 id={sense_ids}；两 coder 各提交 3 条 admission 标注"
            "（payload 六字段齐备，ai_assisted 默认 True），共 6 条入库",
        )

        # ============================================================
        # 步骤 3 · 独立性：annotator 只见自己；reviewer 视角见分歧全貌
        # ============================================================
        mine_a = get_my_submissions(coder_a, "motion", "admission")
        assert len(mine_a) == 3, f"coderA 应只见自己 3 条，实际 {len(mine_a)}"
        assert {m["sense_id"] for m in mine_a} == set(sense_ids)
        assert all(m["coder_id"] == coder_a for m in mine_a), "混入了他人提交"
        assert all(m["ai_assisted"] is True for m in mine_a)  # 用户决策③：默认同稿
        by_sense_a = {m["sense_id"]: m for m in mine_a}
        assert by_sense_a[sense_ids[2]]["payload"]["admission"] == "Y"
        assert by_sense_a[sense_ids[0]]["payload"]["needs_review"] is False

        mine_b = get_my_submissions(coder_b, "motion", "admission")
        assert len(mine_b) == 3
        assert all(m["coder_id"] == coder_b for m in mine_b)

        disagreements = detect_disagreements("motion", "admission")
        assert len(disagreements) == 1, (
            f"应恰报 1 条分歧，实际 {[(d['sense_id'], d['fields']) for d in disagreements]}"
        )
        dis = disagreements[0]
        assert dis["sense_id"] == sense_ids[2]
        assert dis["verb"] == "run"
        assert dis["n_submissions"] == 2
        assert [f["field"] for f in dis["fields"]] == ["admission"]
        values = dis["fields"][0]["values"]
        assert set(values) == {str(coder_a), str(coder_b)}, "fields 应含两个 coder 的取值"
        assert values[str(coder_a)] == "Y"
        assert values[str(coder_b)] == "N"
        _step(
            "步骤3·独立性",
            f"get_my_submissions(coderA) 恰 3 条且全为本人（ai_assisted=True）；"
            f"detect_disagreements 恰 1 条分歧（sense={sense_ids[2]}, verb=run, "
            f"n_submissions=2），fields=[admission] 且 values 含 coderA=Y / coderB=N",
        )

        # ============================================================
        # 步骤 4 · 信度（仲裁前快照；任务书步骤 5，见模块 docstring 次序说明）
        # ============================================================
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM reliability_runs")
            runs_before = int(cur.fetchone()["n"])

        result = run_reliability("motion", "admission")  # features_meta 可空 → 默认读配置
        assert result["n_coders"] == 2, f"n_coders 应为 2，实际 {result['n_coders']}"
        assert result["n_units"] == 3, f"n_units 应为 3，实际 {result['n_units']}"
        assert isinstance(result["overall_alpha"], float), "overall_alpha 应为数值"
        assert result["overall_alpha"] < 1.0, (
            f"含 1 处分歧时 overall_alpha 应 <1，实际 {result['overall_alpha']}"
        )
        assert result["per_feature"]["admission"] < 1.0
        assert result["per_feature"]["schema"] == 1.0
        assert result["per_feature"]["alignment"] == 1.0
        assert len(result["disagreements"]) == 1
        assert result["disagreements"][0]["sense_id"] == sense_ids[2]

        if result.get("run_id") is not None:
            e2e_env["run_ids"].append(int(result["run_id"]))
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM reliability_runs")
            runs_after = int(cur.fetchone()["n"])
        assert runs_after == runs_before + 1, (
            f"run_reliability 应落库一条（{runs_before} → {runs_after}）"
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT category, task_type, n_coders, n_units, overall_alpha "
                "FROM reliability_runs ORDER BY id DESC LIMIT 1"
            )
            run_row = cur.fetchone()
        assert run_row["category"] == "motion" and run_row["task_type"] == "admission"
        assert int(run_row["n_coders"]) == 2 and int(run_row["n_units"]) == 3
        assert abs(float(run_row["overall_alpha"]) - result["overall_alpha"]) <= 0.0011
        _step(
            "步骤4·信度（任务书⑤，仲裁前快照）",
            f"n_coders=2, n_units=3, per_feature={{admission: "
            f"{result['per_feature']['admission']:.3f}, schema: 1.000, alignment: 1.000}}, "
            f"overall_alpha={result['overall_alpha']:.3f}（<1，含 1 处分歧）；"
            f"reliability_runs 落库 1 条（id={result.get('run_id')}，含分歧摘要）",
        )

        # ============================================================
        # 步骤 5 · 仲裁：reviewer 定稿 gold=Y，状态流转 + 退出信度口径复核
        # ============================================================
        subs = get_submissions_for_sense(sense_ids[2], "admission")
        assert len(subs) == 2
        assert {s["coder_id"] for s in subs} == {coder_a, coder_b}
        assert {s["username"] for s in subs} == {CODER_A_NAME, CODER_B_NAME}
        sub_ids = sorted(int(s["id"]) for s in subs)

        gold = _payload("Y", "GOAL_ARRIVE", "SV", "把字句", "意译", False)
        note = "双人分歧（coderA=Y / coderB=N）：coderA 与准入判据一致（自移核心义），定 gold=Y"
        assert save_adjudication(
            sense_ids[2], "admission", reviewer, gold, sub_ids, note
        ), "save_adjudication 应成功"

        with conn.cursor() as cur:
            cur.execute(
                "SELECT submission_ids, adjudicator_id, gold_payload, note "
                "FROM adjudications WHERE sense_id = %s AND task_type = 'admission'",
                (sense_ids[2],),
            )
            adj_rows = cur.fetchall()
        assert len(adj_rows) == 1, f"(sense, task) 应恰 1 条仲裁记录，实际 {len(adj_rows)}"
        adj = adj_rows[0]
        assert int(adj["adjudicator_id"]) == reviewer
        assert sorted(flow._parse_json_list(adj["submission_ids"])) == sub_ids
        gold_stored = flow.parse_payload(adj["gold_payload"])
        assert gold_stored["admission"] == "Y"
        assert "gold=Y" in (adj["note"] or "")

        # 状态流转：参与仲裁的两条 → adjudicated；未参与（另 2 义位 4 条）→ submitted
        after = get_submissions_for_sense(sense_ids[2], "admission")
        assert {s["status"] for s in after} == {"adjudicated"}
        untouched = (
            get_submissions_for_sense(sense_ids[0], "admission")
            + get_submissions_for_sense(sense_ids[1], "admission")
        )
        assert len(untouched) == 4
        assert {s["status"] for s in untouched} == {"submitted"}

        # 复核：adjudicated 提交退出信度口径（reliability 只统计 submitted）
        result2 = run_reliability("motion", "admission")
        if result2.get("run_id") is not None:
            e2e_env["run_ids"].append(int(result2["run_id"]))
        assert result2["n_units"] == 2, "被仲裁义位应退出信度口径"
        assert result2["n_coders"] == 2
        assert result2["overall_alpha"] == 1.0, "剩余 2 义位两人全一致，α 应为 1.0"
        assert result2["disagreements"] == []
        _step(
            "步骤5·仲裁（任务书④）",
            f"reviewer(id={reviewer}) 对 sense={sense_ids[2]} save_adjudication 成功："
            f"adjudications 1 行（adjudicator={reviewer}, gold.admission=Y, note 留痕, "
            f"submission_ids={sub_ids}）；该义位 2 条 submission → 'adjudicated'，"
            "另 4 条保持 'submitted'；复核 run_reliability：n_units=2、α=1.0、"
            "分歧清零（被仲裁提交已退出信度口径）",
        )

        # ============================================================
        # 步骤 6 · 范畴包冒烟：motion 六件套自检通过 + 15 项 in_clustering；speech 可加载
        # ============================================================
        pack = load_pack("motion")
        assert set(pack) == {
            "admission", "features", "schemas", "corpus_map", "prompts", "pack",
        }
        features = pack["features"]["features"]
        in_clustering = [f for f in features if f.get("in_clustering")]
        assert len(in_clustering) == 15, (
            f"motion 应有 15 项 in_clustering 特征，实际 {len(in_clustering)}"
        )
        speech_pack = load_pack("speech")
        assert speech_pack["pack"]["category"] == "speech"
        _step(
            "步骤6·范畴包冒烟",
            "load_pack('motion') 六件套加载+自检通过（features 15 项 in_clustering）；"
            "load_pack('speech') 成功（category=speech）",
        )

        # ============================================================
        # 步骤 7 · 清理：由 e2e_env fixture 收尾执行（前缀用户 + 水位线之上的
        # reliability_runs），并自校验前缀用户归零 —— 保证连续跑两遍都绿。
        # ============================================================
        _step(
            "步骤7·清理",
            "fixture 收尾：按前缀 e2e_r5_ 删除 users/assignments/submissions/"
            "adjudications，reliability_runs 按 id 水位线+run_id 删除，"
            "并断言前缀用户归零（清理不彻底会显式报错）",
        )
