"""AI 协作台账模块测试（src/ai_ledger.py）。

两层结构，与 tests/test_users_db.py 约定一致：

  * 纯函数（proposal 序列化守卫 / 不确定度规整）与模块常量不碰数据库 ——
    本地与 CI 全跑；
  * 数据层 CRUD（ensure / record_proposal / decide / list_pending / get_stats /
    get_proposal）依赖真实 MySQL —— 连不上或账号无建库权限就 skip
    （模块级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_ai_ledger_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，跑完 DROP。

覆盖面（阶段1施工规范对 Agent D 的要求）：
  登记三类（draft/audit/probe）/ 裁决流转（adopted/rejected/modified）/
  重复裁决拒绝 / list_pending 排序与过滤 / 统计口径（采纳率分母、平均不确定度）。
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.ai_ledger import (  # noqa: E402
    DECISIONS,
    KINDS,
    PROPOSAL_STATUSES,
    _as_uncertainty,
    _dump_proposal,
    decide,
    ensure_ai_ledger_tables,
    get_proposal,
    get_stats,
    list_pending,
    record_proposal,
)

TEST_DB = "web_word_ai_ledger_test"


# ============================================
# 纯函数与常量（规范 §5 三通道 / 契约 §3-D 口径，无数据库）
# ============================================

class TestConstantsAndGuards:
    """模块常量与入参守卫（不碰数据库，CI 必跑）。"""

    def test_kinds_three_channels(self):
        """三通道 kind 齐全（平台架构设计规范 §5：草稿/质检/探针）。"""
        assert KINDS == ("draft", "audit", "probe")

    def test_decisions_and_statuses(self):
        """裁决三值 + status 全集（pending + 裁决三值）。"""
        assert DECISIONS == ("adopted", "rejected", "modified")
        assert PROPOSAL_STATUSES == ("pending", "adopted", "rejected", "modified")

    def test_dump_proposal_accepts_containers(self):
        """dict/list 提议可序列化，中文原样（ensure_ascii=False）。"""
        dumped = _dump_proposal({"admission": "Y", "理由": "依库内证据 sense:1"})
        assert dumped is not None
        assert "理由" in dumped
        assert _dump_proposal([]) == "[]"
        assert _dump_proposal({"deep": {"nested": [1, 2, 3]}}) is not None

    def test_dump_proposal_rejects_scalars_and_nan(self):
        """标量/不可序列化/NaN/Inf 一律拒绝（MySQL JSON 列会炸的先在入口拒）。"""
        bad = [
            42,
            "纯字符串不是提议",
            None,
            3.14,
            True,
            {"x": float("nan")},
            [1.0, float("inf")],
            {1, 2},            # set 不可 JSON 序列化
            {"x": object()},
        ]
        for item in bad:
            assert _dump_proposal(item) is None, f"应拒绝: {item!r}"

    def test_uncertainty_normalization(self):
        """不确定度规整到 [0,1] 与 4 位小数。"""
        assert _as_uncertainty(0.5) == 0.5
        assert _as_uncertainty(1) == 1.0
        assert _as_uncertainty(0) == 0.0
        assert _as_uncertainty(0.123456) == 0.1235
        assert _as_uncertainty(0.99999) == 1.0

    def test_uncertainty_rejects_out_of_domain(self):
        """越界/NaN/Inf/布尔/字符串一律 None（record_proposal 会拒）。"""
        bad = [-0.1, 1.5, 100, float("nan"), float("inf"), True, "0.8", None]
        for item in bad:
            assert _as_uncertainty(item) is None, f"应拒绝: {item!r}"


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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 AI 台账集成测试")
class TestAiLedgerIntegration:
    """数据层 CRUD + 统计口径（跑在独立测试库 web_word_ai_ledger_test）。"""

    @pytest.fixture
    def ledger(self, monkeypatch):
        """建空测试库并让 ai_ledger 指向它，测试结束 DROP。

        与 test_users_db.users_db 相同的手法：get_db_cursor / _new_connection
        在调用时读 mysql_db 模块全局，monkeypatch MYSQL_DATABASE 即可；
        连接池按键含 db 名，互不污染。ai_proposals 无外键，ensure 可独立建表。
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
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 AI 台账集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_ai_ledger_tables()
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

    # --- 辅助 ---

    def _fetch(self, proposal_id):
        """直接读库取单行（绕过数据层，验证落库真相）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM ai_proposals WHERE id = %s", (proposal_id,))
            return cursor.fetchone()

    def _count(self, where="1=1", params=()):
        """直接数行数（验证统计真相）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS n FROM ai_proposals WHERE {where}", params)
            return int(cursor.fetchone()["n"])

    # --- 建表 ---

    def test_ensure_idempotent(self, ledger):
        """ensure 重复调用幂等（CREATE TABLE IF NOT EXISTS）。"""
        ensure_ai_ledger_tables()
        ensure_ai_ledger_tables()
        assert get_stats()["total"] == 0

    # --- 登记三类 ---

    def test_record_three_kinds(self, ledger):
        """draft/audit/probe 三类均可登记，id 递增且 kind 落库正确。"""
        ids = [
            record_proposal("draft", "admission", "oald_senses:1", {"admission": "Y"}),
            record_proposal("audit", "definition", "oald_senses:2", {"issue": "句式检查"}),
            record_proposal("probe", "qa", "cluster:45", {"question": "run 的图式邻居?"}),
        ]
        assert all(isinstance(i, int) and i > 0 for i in ids)
        assert len(set(ids)) == 3
        kinds = [self._fetch(i)["kind"] for i in ids]
        assert kinds == ["draft", "audit", "probe"]

    def test_record_full_fields_roundtrip(self, ledger):
        """可选字段（证据/双版本/不确定度/登记人）全量登记并读回。"""
        pid = record_proposal(
            "draft",
            "admission",
            "oald_senses:123",
            {"admission": "EXT", "依据": "配置规则 X + 库内证据 Y"},
            evidence_ref="enTenTen21:match/9876",
            prompt_version="prompts/admission@v3",
            resource_version="snap-20260101",
            uncertainty=0.35,
            created_by=1,
        )
        assert pid > 0
        got = list_pending()[0]
        assert got["id"] == pid
        assert got["kind"] == "draft"
        assert got["stage"] == "admission"
        assert got["unit_ref"] == "oald_senses:123"
        assert got["proposal"] == {"admission": "EXT", "依据": "配置规则 X + 库内证据 Y"}
        assert got["evidence_ref"] == "enTenTen21:match/9876"
        assert got["prompt_version"] == "prompts/admission@v3"
        assert got["resource_version"] == "snap-20260101"
        assert got["uncertainty"] == 0.35
        assert got["status"] == "pending"
        assert got["created_by"] == 1
        assert got["decision_reason"] is None
        assert got["decider_id"] is None
        assert got["decided_at"] is None
        assert got["created_at"] is not None

    def test_record_defaults_pending(self, ledger):
        """新登记一律 status='pending'（probe 也不例外）。"""
        pid = record_proposal("probe", "qa", "word:run", {"q": "有据吗?", "a": "无据"})
        row = self._fetch(pid)
        assert row["status"] == "pending"
        assert row["decided_at"] is None

    def test_probe_also_decidable(self, ledger):
        """probe 走 pending→可裁决（探针问答通常不入裁决流，但机制上可裁决）。"""
        pid = record_proposal("probe", "qa", "word:run", {"q": "cite?"})
        assert decide(pid, "rejected", "探针答复已确认，无需入流", 1) is True
        assert self._fetch(pid)["status"] == "rejected"
        assert list_pending(kind="probe") == []

    def test_record_rejects_invalid_kind(self, ledger):
        """kind 白名单外（应用层先拒，不进数据库）。"""
        assert record_proposal("summary", "qa", "x", {}) == 0
        assert record_proposal("", "qa", "x", {}) == 0
        assert record_proposal(None, "qa", "x", {}) == 0
        assert record_proposal("DRAFT", "qa", "x", {}) == 0  # 大小写敏感
        assert self._count() == 0

    def test_record_rejects_non_json_proposal(self, ledger):
        """proposal 必须是可 JSON 序列化的 dict/list。"""
        bad = [42, "文本", None, 3.14, True, {1, 2}, {"x": float("nan")}, [float("inf")]]
        for p in bad:
            assert record_proposal("draft", "s", "u", p) == 0, f"应拒绝: {p!r}"
        assert self._count() == 0

    def test_record_rejects_bad_stage_and_unit_ref(self, ledger):
        """stage/unit_ref 非空且限长（VARCHAR 口径，应用层先拒）。"""
        assert record_proposal("draft", "", "u", {}) == 0
        assert record_proposal("draft", "   ", "u", {}) == 0
        assert record_proposal("draft", "x" * 41, "u", {}) == 0
        assert record_proposal("draft", None, "u", {}) == 0
        assert record_proposal("draft", "s", "", {}) == 0
        assert record_proposal("draft", "s", "x" * 121, {}) == 0
        assert record_proposal("draft", "s", None, {}) == 0
        assert self._count() == 0

    def test_record_rejects_bad_optional_strings(self, ledger):
        """可选字符串超长/类型不对拒绝（40/40/255 上限）。"""
        assert record_proposal("draft", "s", "u", {}, evidence_ref="e" * 256) == 0
        assert record_proposal("draft", "s", "u", {}, prompt_version="p" * 41) == 0
        assert record_proposal("draft", "s", "u", {}, resource_version="r" * 41) == 0
        assert record_proposal("draft", "s", "u", {}, evidence_ref=123) == 0
        assert self._count() == 0

    def test_record_rejects_bad_uncertainty(self, ledger):
        """不确定度越界/非数值拒绝（综合信号必归一 [0,1]，禁 LLM 自报也禁乱传）。"""
        assert record_proposal("draft", "s", "u", {}, uncertainty=-0.01) == 0
        assert record_proposal("draft", "s", "u", {}, uncertainty=1.01) == 0
        assert record_proposal("draft", "s", "u", {}, uncertainty="high") == 0
        assert record_proposal("draft", "s", "u", {}, uncertainty=float("nan")) == 0
        assert self._count() == 0

    def test_record_rejects_bad_created_by(self, ledger):
        """created_by 须为正整数或 None。"""
        assert record_proposal("draft", "s", "u", {}, created_by=0) == 0
        assert record_proposal("draft", "s", "u", {}, created_by=-1) == 0
        assert record_proposal("draft", "s", "u", {}, created_by="me") == 0
        assert record_proposal("draft", "s", "u", {}, created_by=1) > 0  # 合法

    def test_record_strips_whitespace(self, ledger):
        """stage/unit_ref/evidence_ref 首尾空白去净；纯空白可选项存 NULL。"""
        pid = record_proposal(
            "draft", "  admission  ", "  oald_senses:9  ", {"a": 1}, evidence_ref="  "
        )
        got = list_pending()[0]
        assert got["stage"] == "admission"
        assert got["unit_ref"] == "oald_senses:9"
        assert got["evidence_ref"] is None  # 纯空白 → NULL（=无据）

    def test_uncertainty_roundtrip_precision(self, ledger):
        """不确定度 DECIMAL(5,4) 往返：边界 0/1 与 4 位小数均保真。"""
        for u in (0.0, 0.5, 0.9876, 1.0):
            record_proposal("draft", "s", f"u{u}", {}, uncertainty=u)
        got = {row["unit_ref"]: row["uncertainty"] for row in list_pending(limit=10)}
        assert got["u0.0"] == 0.0
        assert got["u0.5"] == 0.5
        assert got["u0.9876"] == 0.9876
        assert got["u1.0"] == 1.0

    # --- 裁决流转 ---

    def test_decide_adopted_flow(self, ledger):
        """采纳：status/decision_reason/decider_id/decided_at 全部落库。"""
        pid = record_proposal("draft", "admission", "oald_senses:1", {"admission": "Y"})
        assert decide(pid, "adopted", "与库内证据一致，采纳", 7) is True
        row = self._fetch(pid)
        assert row["status"] == "adopted"
        assert row["decision_reason"] == "与库内证据一致，采纳"
        assert row["decider_id"] == 7
        assert row["decided_at"] is not None
        assert list_pending() == []  # 已裁决的退出待决列表

    def test_decide_rejected_and_modified(self, ledger):
        """否决与修改后采纳两条流转。"""
        p1 = record_proposal("draft", "s", "u1", {})
        p2 = record_proposal("audit", "s", "u2", {})
        assert decide(p1, "rejected", "证据不足", 1) is True
        assert decide(p2, "modified", "人工改了特征后采纳", 1) is True
        assert self._fetch(p1)["status"] == "rejected"
        assert self._fetch(p2)["status"] == "modified"

    def test_decide_twice_rejected(self, ledger):
        """重复裁决拒绝：第二次返回 False，首次结论不被覆盖。"""
        pid = record_proposal("draft", "s", "u", {})
        assert decide(pid, "adopted", "首次采纳", 1) is True
        assert decide(pid, "rejected", "试图翻案", 2) is False
        row = self._fetch(pid)
        assert row["status"] == "adopted"
        assert row["decision_reason"] == "首次采纳"
        assert row["decider_id"] == 1

    def test_decide_rejected_once_only(self, ledger):
        """否决后再裁决同样拒绝（任意状态都不可二次裁决）。"""
        pid = record_proposal("audit", "s", "u", {})
        assert decide(pid, "rejected", "否", 1) is True
        assert decide(pid, "adopted", "再试", 1) is False
        assert self._fetch(pid)["status"] == "rejected"

    def test_decide_invalid_decision(self, ledger):
        """decision 白名单外拒绝，提案保持 pending。"""
        pid = record_proposal("draft", "s", "u", {})
        assert decide(pid, "approved", "typo", 1) is False
        assert decide(pid, "pending", "没这回事", 1) is False
        assert decide(pid, None, None, 1) is False
        assert self._fetch(pid)["status"] == "pending"

    def test_decide_nonexistent_or_bad_args(self, ledger):
        """提案不存在 / id 与 decider 非法 → False。"""
        assert decide(999999, "adopted", "x", 1) is False
        assert decide("abc", "adopted", "x", 1) is False
        assert decide(None, "adopted", "x", 1) is False
        pid = record_proposal("draft", "s", "u", {})
        assert decide(pid, "adopted", "x", None) is False
        assert decide(pid, "adopted", "x", 0) is False
        assert decide(pid, "adopted", "x", "admin") is False
        assert self._fetch(pid)["status"] == "pending"

    def test_decide_reason_optional(self, ledger):
        """reason=None 允许（存 NULL）；页面应尽量要求填写。"""
        pid = record_proposal("draft", "s", "u", {})
        assert decide(pid, "adopted", None, 1) is True
        assert self._fetch(pid)["decision_reason"] is None

    # --- list_pending 排序与过滤 ---

    def test_list_pending_order(self, ledger):
        """排序：uncertainty DESC, id ASC；无不确定度（NULL）排最后。"""
        a = record_proposal("draft", "s", "A", {}, uncertainty=0.5)
        b = record_proposal("draft", "s", "B", {}, uncertainty=0.9)
        c = record_proposal("draft", "s", "C", {})  # 无不确定度
        d = record_proposal("draft", "s", "D", {}, uncertainty=0.9)
        e = record_proposal("draft", "s", "E", {}, uncertainty=0.25)
        got = [row["id"] for row in list_pending()]
        # 0.9 的两条按 id ASC（b, d）→ 0.5（a）→ 0.25（e）→ NULL（c）最后
        assert got == [b, d, a, e, c]

    def test_list_pending_kind_filter(self, ledger):
        """kind 过滤：三通道各自可查（收件箱按通道取数）。"""
        record_proposal("draft", "s", "d1", {})
        record_proposal("audit", "s", "a1", {})
        record_proposal("audit", "s", "a2", {})
        record_proposal("probe", "s", "p1", {})
        assert [r["unit_ref"] for r in list_pending(kind="audit")] == ["a1", "a2"]
        assert [r["unit_ref"] for r in list_pending(kind="draft")] == ["d1"]
        assert [r["unit_ref"] for r in list_pending(kind="probe")] == ["p1"]
        assert len(list_pending()) == 4  # None = 全通道

    def test_list_pending_invalid_kind(self, ledger):
        """kind 非法（白名单外）返回空列表，不报错。"""
        record_proposal("draft", "s", "d1", {})
        assert list_pending(kind="summary") == []
        assert list_pending(kind="") == []
        assert list_pending(kind=123) == []

    def test_list_pending_stage_filter(self, ledger):
        """stage 过滤：同通道不同工序分开取。"""
        record_proposal("draft", "admission", "d-a", {})
        record_proposal("draft", "feature_coding", "d-f", {})
        record_proposal("audit", "admission", "a-a", {})
        assert [r["unit_ref"] for r in list_pending(kind="draft", stage="admission")] == ["d-a"]
        assert [r["unit_ref"] for r in list_pending(stage="admission")] == ["d-a", "a-a"]
        assert list_pending(stage="不存在的工序") == []

    def test_list_pending_limit(self, ledger):
        """limit 生效（按排序取前 N）；≤0 返回空；超大值不炸（截断上限）。"""
        for i, u in enumerate([0.1, 0.9, 0.5, 0.7]):
            record_proposal("draft", "s", f"u{i}", {}, uncertainty=u)
        top2 = list_pending(limit=2)
        assert [r["uncertainty"] for r in top2] == [0.9, 0.7]  # 排序后前两条
        assert list_pending(limit=0) == []
        assert list_pending(limit=-5) == []
        assert len(list_pending(limit=10 ** 6)) == 4  # 超上限截到 MAX_LIST_LIMIT 也不炸

    def test_list_pending_excludes_decided(self, ledger):
        """已裁决行离开待决列表，但记录仍在库里（留痕不删）。"""
        p1 = record_proposal("draft", "s", "u1", {})
        p2 = record_proposal("draft", "s", "u2", {})
        p3 = record_proposal("draft", "s", "u3", {})
        assert len(list_pending()) == 3
        decide(p2, "adopted", "ok", 1)
        got = [r["id"] for r in list_pending()]
        assert got == [p1, p3]
        assert self._count() == 3

    def test_list_pending_proposal_parsed(self, ledger):
        """list_pending 的 proposal 是解析后的 dict（PyMySQL JSON 列给 str 也要解）。"""
        record_proposal("draft", "s", "u", {"admission": "Y", "features": {"P1": 1}})
        row = list_pending()[0]
        assert row["proposal"] == {"admission": "Y", "features": {"P1": 1}}

    # --- get_stats 统计口径 ---

    def test_get_stats_empty(self, ledger):
        """空库口径：全 0 + 两个比率为 None（「没数据」≠「0%」）。"""
        stats = get_stats()
        assert stats["stage"] is None
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["decided"] == 0
        assert stats["adoption_rate"] is None
        assert stats["avg_uncertainty"] is None

    def test_get_stats_keys(self, ledger):
        """统计字典键齐全（批次 2 协同度量页按此接线）。"""
        assert set(get_stats().keys()) == set(
            [
                "stage", "total", "pending", "adopted", "rejected",
                "modified", "decided", "adoption_rate", "avg_uncertainty",
            ]
        )

    def test_get_stats_mixed(self, ledger):
        """混合口径：total/pending/decided/采纳率/平均不确定度。"""
        # 采纳 1 + 否决 1 + 修改 1 + 待决 2（其中一条无不确定度）
        record_proposal("draft", "s", "p1", {}, uncertainty=0.9)
        record_proposal("draft", "s", "p2", {}, uncertainty=0.4)
        record_proposal("audit", "s", "p3", {}, uncertainty=0.6)
        record_proposal("audit", "s", "p4", {}, uncertainty=0.2)
        record_proposal("draft", "s", "p5", {})  # 无不确定度
        ids = [r["id"] for r in list_pending(limit=10)]
        decide(ids[0], "adopted", "好", 1)    # p1 (0.9)
        decide(ids[1], "rejected", "差", 1)   # p2 (0.4)
        decide(ids[2], "modified", "改", 1)   # p3 (0.6)
        stats = get_stats()
        assert stats["total"] == 5
        assert stats["pending"] == 2
        assert stats["adopted"] == 1
        assert stats["rejected"] == 1
        assert stats["modified"] == 1
        assert stats["decided"] == 3
        # 采纳率 = adopted / (adopted + rejected + modified) = 1/3
        assert stats["adoption_rate"] == round(1 / 3, 4)
        # 平均不确定度含已裁决行：pending 不参与分母，全部 4 条非空取平均
        assert math.isclose(stats["avg_uncertainty"], (0.9 + 0.4 + 0.6 + 0.2) / 4)

    def test_get_stats_adoption_rate_edges(self, ledger):
        """采纳率边界：全采纳 1.0 / 全否决 0.0。"""
        p1 = record_proposal("draft", "s", "p1", {})
        p2 = record_proposal("draft", "s", "p2", {})
        decide(p1, "adopted", "ok", 1)
        decide(p2, "adopted", "ok", 1)
        assert get_stats()["adoption_rate"] == 1.0
        p3 = record_proposal("draft", "s", "p3", {})
        decide(p3, "rejected", "no", 1)
        stats = get_stats()
        assert stats["adoption_rate"] == round(2 / 3, 4)

    def test_get_stats_stage_scope(self, ledger):
        """stage 过滤口径：只统计该工序；stage 键回显过滤条件。"""
        record_proposal("draft", "admission", "a1", {}, uncertainty=0.8)
        record_proposal("draft", "admission", "a2", {})
        record_proposal("audit", "feature_coding", "f1", {})
        aid = [r["id"] for r in list_pending(kind="draft", stage="admission")][0]
        decide(aid, "adopted", "ok", 1)
        stats = get_stats(stage="admission")
        assert stats["stage"] == "admission"
        assert stats["total"] == 2
        assert stats["adopted"] == 1
        assert stats["pending"] == 1
        assert stats["adoption_rate"] == 1.0
        assert stats["avg_uncertainty"] == 0.8
        other = get_stats(stage="feature_coding")
        assert other["total"] == 1
        assert other["pending"] == 1
        assert other["adoption_rate"] is None
        assert get_stats()["total"] == 3  # 全库口径不受影响

    def test_get_stats_invalid_stage(self, ledger):
        """stage 非法（非字符串）返回全 0 口径，不抛异常。"""
        stats = get_stats(stage=123)
        assert stats["total"] == 0
        assert stats["adoption_rate"] is None

    # --- get_proposal 辅助入口 ---

    def test_get_proposal_roundtrip(self, ledger):
        """单条读取（含已裁决行），字段与 list_pending 一致口径。"""
        pid = record_proposal("draft", "s", "u", {"a": 1}, uncertainty=0.7)
        got = get_proposal(pid)
        assert got["id"] == pid
        assert got["proposal"] == {"a": 1}
        assert got["uncertainty"] == 0.7
        assert got["status"] == "pending"
        decide(pid, "modified", "改后采纳", 5)
        got = get_proposal(pid)
        assert got["status"] == "modified"
        assert got["decider_id"] == 5
        assert got["decided_at"] is not None

    def test_get_proposal_missing(self, ledger):
        """不存在的 id / 非法 id 返回 None。"""
        assert get_proposal(999999) is None
        assert get_proposal("abc") is None
        assert get_proposal(None) is None
