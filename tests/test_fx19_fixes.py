"""FX-19 批次修复测试：协同度量五指标（规范 §5 度量清单补齐）。

对应台账「规范×实现对账」①组缺口：协同度量此前仅有采纳率，本批次在
src/collab_metrics.py 集中补齐五指标并接入 collab_pages 协同度量 tab：

  * AI-人一致率     —— 数据源勘察：annotation_submissions 只存 ai_assisted
    布尔标志（不落 AI 草稿内容快照），逐特征比对不可行；按勘测指令退用
    ai_proposals(kind='draft') 已裁决提案与人工裁决对照（完全一致=adopted /
    部分一致=modified 不入分子 / 不一致=rejected）。纯函数断言分子分母。
  * 标注节省量      —— 估算口径：(采纳+修改后采纳)×3.0 分钟/条（工程估算，
    非实测）；纯函数断言计数与换算，页面渲染「估算」徽章（R4-6 MOCK 徽章
    同款纪律，不得看起来像实测）。
  * 打回率          —— 数据源 writing_db.review_tasks.verdict（只读）：
    (revision_requested+rejected)÷已出结论审校轮（verdict≠pending）。
    夹具库种子数据断言分子分母；kind='draft' 之外的通道不进一致率分母。
  * 替换测试通过率 / 体例质检通过率 —— 全库勘察无执行结果数据源（配置
    已就绪但无结果表/写入）：如实灰注占位，pass_rate 恒 None，绝不编数字；
    降级路径（无数据源→灰注文案）与数据库不可用整卡灰注均有测试。

外部依赖隔离：纯函数与常量用例不碰数据库（CI 全跑）；种子数据用例跑独立
测试库 web_word_fx19_test（连不上/无建库权限则 skip，test_collab_pages 同
口径）；页面 AppTest 用例打桩 collab_metrics 数据函数或让其降级，不依赖
开发库内容。
"""

import os
import sys

import pymysql
import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.mysql_db as db  # noqa: E402
from src import collab_metrics as cm  # noqa: E402
from src.ai_ledger import (  # noqa: E402
    DECISION_ADOPTED,
    DECISION_MODIFIED,
    DECISION_REJECTED,
    KIND_AUDIT,
    KIND_DRAFT,
    KIND_PROBE,
    decide,
    ensure_ai_ledger_tables,
    record_proposal,
)
from src.writing_db import REVIEW_TASKS_TABLE_SQL  # noqa: E402 只读 import（DDL 常量）

# 独立测试库（本地 MySQL 账号按名授权，web_word_fx19_test 已入
# scripts/grant_local_mysql.sql 授权清单 —— FX-21 归位；pytest 串行执行、
# fixture 前后 DROP 重建，互不污染）
TEST_DB = "web_word_fx19_test"


# ============================================
# 纯函数 · 指标 1 AI-人一致率（分子/分母在这里断言）
# ============================================
class TestAgreementRateFromCounts:
    """agreement_rate_from_counts：adopted÷(adopted+rejected+modified)。"""

    def test_numerator_is_adopted_only(self):
        """分子只算完全一致（adopted）；modified 是部分一致，不入分子。"""
        r = cm.agreement_rate_from_counts(adopted=3, rejected=1, modified=1)
        assert r["adopted"] == 3 and r["rejected"] == 1 and r["modified"] == 1
        assert r["decided"] == 5          # 分母 = 三值合计（已裁决）
        assert r["partial_agreement"] == 1
        assert r["agreement_rate"] == 0.6  # 3/5 —— modified 不进分子

    def test_all_agreed(self):
        """全部原样采纳 → 一致率 1.0。"""
        r = cm.agreement_rate_from_counts(4, 0, 0)
        assert r["decided"] == 4 and r["agreement_rate"] == 1.0

    def test_no_decided_yields_none_not_zero(self):
        """分母 0（尚无已裁决提案）→ None（「还没数据」≠ 0%）。"""
        r = cm.agreement_rate_from_counts(0, 0, 0)
        assert r["decided"] == 0
        assert r["agreement_rate"] is None

    def test_dirty_counts_clamped_to_zero(self):
        """脏计数（None/非数值/负数/bool）按 0，不抛异常。"""
        r = cm.agreement_rate_from_counts(None, "x", -5)
        assert r["decided"] == 0 and r["agreement_rate"] is None
        r2 = cm.agreement_rate_from_counts(True, 2, 0)
        assert r2["adopted"] == 0 and r2["decided"] == 2
        assert r2["agreement_rate"] == 0.0


# ============================================
# 纯函数 · 指标 2 标注节省量（估算口径断言）
# ============================================
class TestSavingsEstimateFromCounts:
    """savings_estimate_from_counts：(采纳+修改后采纳)×单条分钟假设。"""

    def test_default_includes_modified_and_converts_hours(self):
        """默认口径 adopted+modified 全计；分钟→小时换算（4+2)×3.0=18.0 分钟。"""
        r = cm.savings_estimate_from_counts(adopted=4, modified=2)
        assert r["base_count"] == 6
        assert r["minutes_saved"] == 18.0
        assert r["hours_saved"] == 0.3
        assert r["minutes_per_item"] == cm.SAVED_MINUTES_PER_ITEM
        assert r["estimated"] is True  # 估算口径标记（页面徽章依据）

    def test_conservative_excludes_modified(self):
        """include_modified=False → 只算原样采纳（更保守口径可用）。"""
        r = cm.savings_estimate_from_counts(adopted=4, modified=2,
                                            include_modified=False)
        assert r["base_count"] == 4 and r["minutes_saved"] == 12.0

    def test_custom_minutes_per_item(self):
        """单条假设可覆盖（运行层将来换实测口径的入口）。"""
        r = cm.savings_estimate_from_counts(2, 0, minutes_per_item=5.0)
        assert r["minutes_saved"] == 10.0 and r["hours_saved"] == pytest.approx(0.17)

    def test_zero_base_is_zero_not_none(self):
        """没有已采纳草稿 → 节省 0（计数 0 是真值，不是无数据）。"""
        r = cm.savings_estimate_from_counts(0, 0)
        assert r["base_count"] == 0
        assert r["minutes_saved"] == 0.0 and r["estimated"] is True

    def test_assumption_constant_is_engineering_estimate(self):
        """假设常数钉住 3.0 分钟/条（工程估算；改动须连文档口径一起改）。"""
        assert cm.SAVED_MINUTES_PER_ITEM == 3.0
        assert isinstance(cm.SAVED_MINUTES_PER_ITEM, float)
        # 口径文案常量齐全（页面 tooltip/caption 引用；双语口径纪律的中文部分）
        for note in (cm.AGREEMENT_NOTE, cm.SAVINGS_NOTE, cm.REJECTION_NOTE,
                     cm.SUBSTITUTION_NOTE, cm.STYLE_CHECK_NOTE):
            assert isinstance(note, str) and note.strip()
        assert "工程估算" in cm.SAVINGS_NOTE and "非实测" in cm.SAVINGS_NOTE


# ============================================
# 纯函数 · 指标 3 打回率（分子/分母在这里断言）
# ============================================
class TestRejectionRateFromCounts:
    """rejection_rate_from_counts：(打回修订+直接否决)÷已出结论审校轮。"""

    def test_numerator_is_revision_requested_plus_rejected(self):
        """分子 = revision_requested + rejected；分母 = 三值合计。"""
        r = cm.rejection_rate_from_counts(approved=5, revision_requested=2,
                                          rejected=1)
        assert r["decided"] == 8           # 已出结论的审校轮
        assert r["rejection_rate"] == 0.375  # (2+1)/8

    def test_no_decided_yields_none(self):
        """尚无已出结论审校轮 → None（不是 0%）。"""
        r = cm.rejection_rate_from_counts(0, 0, 0)
        assert r["decided"] == 0 and r["rejection_rate"] is None

    def test_dirty_counts_clamped(self):
        """脏计数按 0，不抛异常。"""
        r = cm.rejection_rate_from_counts(None, -1, "x")
        assert r["decided"] == 0 and r["rejection_rate"] is None


# ============================================
# 指标 4/5 · 无数据源灰注（宁缺毋假：pass_rate 恒 None，不编数字）
# ============================================
class TestNoDataSourceMetrics:
    """替换测试通过率 / 体例质检通过率：无执行结果数据源 → 灰注占位。"""

    def test_substitution_grey_note_and_no_fabricated_number(self):
        """替换测试：available=False、pass_rate=None、灰注文案注明配置已就绪。"""
        r = cm.substitution_test_status()
        assert r["available"] is False
        assert r["pass_rate"] is None           # 绝不编数字
        assert "尚未接入" in r["reason"] and "不编数字" in r["reason"]

    def test_style_check_grey_note_and_no_fabricated_number(self, monkeypatch):
        """体例质检：无 run 记录/取数不可用 → 灰注、pass_rate=None、不编数字。

        FX-25 契约变更注：本指标已接真数据源（style_check_runs，取数函数
        list_recent_runs）——「无 run → 灰注」仍成立，但与开发库内容无关了
        （真值路径见 tests/test_fx25_fixes.py），这里打桩取数层固定三态。
        """
        monkeypatch.setattr(cm, "list_recent_runs",
                            lambda category=None, limit=5: [])
        r = cm.style_check_status()
        assert r["available"] is False
        assert r["pass_rate"] is None           # 绝不编数字
        assert "尚未接入" in r["reason"]
        monkeypatch.setattr(cm, "list_recent_runs",
                            lambda category=None, limit=5: None)
        r2 = cm.style_check_status()
        assert r2["available"] is False and r2["pass_rate"] is None
        assert "数据库不可用" in r2["reason"]

    def test_substitution_config_detection(self, tmp_path, monkeypatch):
        """配置探测：正常 YAML 命中键 → configured=True，reason 换「配置已就绪」。"""
        cfg = tmp_path / "style.yaml"
        cfg.write_text("vocab:\n  allow_gloss_terms: true\nsubstitution_test:\n"
                       "  method: 双向替换\n", encoding="utf-8")
        monkeypatch.setattr(cm, "_STYLE_YAML_PATH", cfg)
        r = cm.substitution_test_status()
        assert r["configured"] is True
        assert "配置已就绪" in r["reason"] and "不编数字" in r["reason"]

    def test_config_detection_falls_back_to_text_scan(self, tmp_path, monkeypatch):
        """脏 YAML（解析失败）退化文本扫描，仍能检出键。"""
        cfg = tmp_path / "style.yaml"
        cfg.write_text("substitution_test:\n\t method: [坏缩进\n  -: {", encoding="utf-8")
        monkeypatch.setattr(cm, "_STYLE_YAML_PATH", cfg)
        assert cm._style_yaml_config("substitution_test") is True

    def test_config_detection_missing_file(self, tmp_path, monkeypatch):
        """style.yaml 不存在 → configured=False（reason 相应变化），仍不编数字。"""
        monkeypatch.setattr(cm, "_STYLE_YAML_PATH", tmp_path / "missing.yaml")
        r = cm.substitution_test_status()
        assert r["configured"] is False and r["pass_rate"] is None
        assert "未检出" in r["reason"]


# ============================================
# 数据库取数层（独立测试库种子数据；连不上 MySQL 则 skip）
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
    except Exception:  # noqa: BLE001 —— 本地/CI 无 MySQL 时跳过集成段
        return False


HAS_MYSQL = _mysql_reachable()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-19 集成测试")
class TestMetricFetchers:
    """取数层回路：种子数据 → 取数 → 纯函数口径（分子分母对表）。"""

    @pytest.fixture
    def metrics_db(self, monkeypatch):
        """建空测试库＋ai_proposals＋review_tasks，测试结束 DROP。"""
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
                f"COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX-19 集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_ai_ledger_tables()          # ai_proposals（无外键，可独立建）
        with db.get_db_cursor() as cursor:  # review_tasks（软引用，可独立建）
            cursor.execute(REVIEW_TASKS_TABLE_SQL)
        yield
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()

    @staticmethod
    def _seed_draft_proposal(stage: str = "sense_division") -> int:
        """登记一条 draft 提案（proposal 结构随意，字典即可），返回 id。"""
        pid = record_proposal(
            kind=KIND_DRAFT, stage=stage, unit_ref="cluster:1",
            proposal={"action": "merge", "target": "cluster:2"},
            uncertainty=0.4,
        )
        assert pid > 0
        return pid

    def test_agreement_rate_counts_draft_channel_only(self, metrics_db):
        """一致率：draft 已裁决三值计数；audit/probe 通道与 pending 不进分母。"""
        seeds = [self._seed_draft_proposal() for _ in range(5)]
        decide(seeds[0], DECISION_ADOPTED, "按草稿落地", 1)
        decide(seeds[1], DECISION_ADOPTED, "按草稿落地", 1)
        decide(seeds[2], DECISION_REJECTED, "方向不对", 1)
        decide(seeds[3], DECISION_MODIFIED, "改成局部合并", 1)
        # seeds[4] 留 pending（不计入分母）；audit/probe 通道各有已裁决行也不计入
        audit_pid = record_proposal(kind=KIND_AUDIT, stage="style_check",
                                    unit_ref="oald_senses:1",
                                    proposal={"finding": "词表违例"})
        assert audit_pid > 0
        decide(audit_pid, DECISION_ADOPTED, "确认违例", 1)
        probe_pid = record_proposal(kind=KIND_PROBE, stage="probe_qa",
                                    unit_ref="oald_senses:2",
                                    proposal={"question": "测试"})
        assert probe_pid > 0
        decide(probe_pid, DECISION_REJECTED, "探针裁决", 1)

        r = cm.ai_human_agreement_rate()
        assert r["available"] is True
        assert r["adopted"] == 2 and r["rejected"] == 1 and r["modified"] == 1
        assert r["decided"] == 4                      # pending/audit/probe 均不计
        assert r["agreement_rate"] == 0.5             # 2/4（modified 不入分子）
        assert "口径" in r["note"]

    def test_savings_counts_adopted_plus_modified(self, metrics_db):
        """节省量：adopted(1)+modified(1)=2 条 × 3.0 分钟 = 6.0 分钟。"""
        seeds = [self._seed_draft_proposal() for _ in range(3)]
        decide(seeds[0], DECISION_ADOPTED, "", 1)
        decide(seeds[1], DECISION_MODIFIED, "", 1)
        decide(seeds[2], DECISION_REJECTED, "", 1)   # 否决不产生节省
        r = cm.annotation_savings()
        assert r["available"] is True
        assert r["base_count"] == 1 + 1
        assert r["minutes_saved"] == (1 + 1) * cm.SAVED_MINUTES_PER_ITEM
        assert r["estimated"] is True                 # 估算口径，页面须带徽章

    def test_rejection_rate_counts_review_rounds(self, metrics_db):
        """打回率：approved(2)+revision_requested(1)+rejected(1)=4 轮，(1+1)/4=0.5。"""
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO review_tasks (version_id, verdict) VALUES "
                "(1, 'approved'), (2, 'approved'), (3, 'revision_requested'), "
                "(4, 'rejected'), (5, 'pending')"   # pending 不进分母
            )
        r = cm.writing_rejection_rate()
        assert r["available"] is True
        assert r["approved"] == 2
        assert r["revision_requested"] == 1 and r["rejected"] == 1
        assert r["decided"] == 4
        assert r["rejection_rate"] == 0.5

    def test_empty_tables_yield_none_rates(self, metrics_db):
        """空表（建库直连）→ available=True 但比率为 None（不是 0%）。"""
        assert cm.ai_human_agreement_rate()["agreement_rate"] is None
        assert cm.writing_rejection_rate()["rejection_rate"] is None
        s = cm.annotation_savings()
        assert s["available"] is True and s["minutes_saved"] == 0.0

    def test_db_offline_degrades_to_grey_note(self, metrics_db, monkeypatch):
        """数据库不可用 → available=False ＋ 降级文案（灰注），比率 None。"""
        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(cm, "get_db_cursor", _boom)
        for wrapper in (cm.ai_human_agreement_rate, cm.annotation_savings,
                        cm.writing_rejection_rate):
            r = wrapper()
            assert r["available"] is False
            assert "数据库不可用" in r["note"]
            rate_key = ("agreement_rate" if "agreement_rate" in r
                        else "rejection_rate" if "rejection_rate" in r else None)
            if rate_key:
                assert r[rate_key] is None
        assert cm.annotation_savings()["minutes_saved"] == 0.0


# ============================================
# 页面渲染（AppTest；打桩数据函数，不依赖开发库内容）
# ============================================
_METRICS_TAB_SCRIPT = (
    "from src.collab_pages import _render_metrics_tab\n"
    "_render_metrics_tab()\n"
)

# 打桩用五指标返回值（口径与 collab_metrics docstring 一致）
_STUB_AGREEMENT = {
    "available": True, "adopted": 3, "rejected": 1, "modified": 1,
    "decided": 5, "agreement_rate": 0.6, "partial_agreement": 1,
    "note": cm.AGREEMENT_NOTE,
}
_STUB_SAVINGS = {
    "available": True, "base_count": 6, "minutes_saved": 18.0,
    "hours_saved": 0.3, "minutes_per_item": 3.0, "estimated": True,
    "note": cm.SAVINGS_NOTE,
}
_STUB_REJECTION = {
    "available": True, "approved": 5, "revision_requested": 2, "rejected": 1,
    "decided": 8, "rejection_rate": 0.375, "note": cm.REJECTION_NOTE,
}
_STUB_SUBSTITUTION = {
    "available": False, "configured": True, "pass_rate": None,
    "reason": cm.SUBSTITUTION_NOTE, "note": cm.SUBSTITUTION_NOTE,
}
_STUB_STYLE_CHECK = {
    "available": False, "configured": True, "pass_rate": None,
    "reason": cm.STYLE_CHECK_NOTE, "note": cm.STYLE_CHECK_NOTE,
}


def _patch_ledger_stubs(monkeypatch, stats=None, stages=None):
    """打桩 collab_pages 侧台账触点（get_stats/工序枚举），页面只测五指标卡。"""
    import src.collab_pages as cp

    monkeypatch.setattr(cp, "get_stats", lambda stage=None: stats if stats is not None else {
        "stage": None, "total": 9, "pending": 1, "adopted": 3, "rejected": 1,
        "modified": 1, "decided": 5, "adoption_rate": 0.6,
        "avg_uncertainty": 0.4,
    })
    monkeypatch.setattr(cp, "_list_proposal_stages",
                        lambda: stages if stages is not None else ["sense_division"])


def _patch_metric_stubs(monkeypatch):
    """打桩 collab_metrics 五指标（collab_pages 经模块属性调用，补丁即刻生效）。

    FX-43 适配：AI-人一致率卡升级双口径回退链后，页面先取
    feature_level_agreement_rate（快照面）——本夹具把它钉为「快照面无数据」
    零值面，页面回退台账口径桩（_STUB_AGREEMENT），原有断言语义不变（页面
    用例不依赖开发库快照内容）；快照面真值路径的页面用例归 tests/
    test_fx43_fixes.py。
    """
    monkeypatch.setattr(cm, "ai_human_agreement_rate", lambda: dict(_STUB_AGREEMENT))
    monkeypatch.setattr(cm, "feature_level_agreement_rate",
                        lambda *a, **k: {"rate": None, "n_submissions": 0,
                                         "n_features": 0, "matched": 0})
    monkeypatch.setattr(cm, "annotation_savings", lambda: dict(_STUB_SAVINGS))
    monkeypatch.setattr(cm, "writing_rejection_rate", lambda: dict(_STUB_REJECTION))
    monkeypatch.setattr(cm, "substitution_test_status", lambda: dict(_STUB_SUBSTITUTION))
    monkeypatch.setattr(cm, "style_check_status", lambda: dict(_STUB_STYLE_CHECK))


class TestMetricsTabPage:
    """协同度量 tab 渲染：五卡接入、估算徽章、灰注占位、降级不崩。"""

    def test_five_metrics_render_with_stubs(self, monkeypatch):
        """打桩可用数据：三张真值卡出数、估算徽章在场、两张灰注卡不编数字。"""
        _patch_ledger_stubs(monkeypatch)
        _patch_metric_stubs(monkeypatch)
        at = AppTest.from_string(_METRICS_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception

        metrics = {m.label: m.value for m in at.metric}
        assert "AI-人一致率" in metrics and metrics["AI-人一致率"] == "60.0%"
        assert "标注节省量" in metrics and metrics["标注节省量"] == "0.30 小时"
        assert "打回率" in metrics and metrics["打回率"] == "37.5%"
        # 灰注两卡：值恒「—」，绝不出现编造数字
        assert metrics.get("替换测试通过率") == "—"
        assert metrics.get("体例质检通过率") == "—"
        # 估算徽章（markdown 渲染）：有「估算」与「非实测」字样
        markdown_text = "".join(str(md.value) for md in at.markdown)
        assert "估算" in markdown_text and "非实测" in markdown_text
        # 每卡口径/数据源 caption
        caption_text = "".join(str(c.value) for c in at.caption)
        assert "ai_proposals" in caption_text          # 一致率/节省量数据源
        assert "review_tasks" in caption_text          # 打回率数据源
        assert "尚未接入替换测试数据" in caption_text   # 灰注文案
        assert "尚未接入体例质检执行数据" in caption_text
        # 采纳率总览卡保持不动（原有三卡仍在）
        assert metrics.get("提案总数") == "9" and metrics.get("采纳率") == "60.0%"

    def test_db_offline_full_grey_cards_no_crash(self, monkeypatch):
        """数据库不可用：五指标整卡灰注（值「—」＋降级文案），页面不崩。"""
        _patch_ledger_stubs(monkeypatch)

        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(cm, "get_db_cursor", _boom)
        at = AppTest.from_string(_METRICS_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        metrics = {m.label: m.value for m in at.metric}
        # 三张可算卡：值「—」（不是 0% / 0.00 小时 —— 不可用 ≠ 无数据）
        assert metrics.get("AI-人一致率") == "—"
        assert metrics.get("标注节省量") == "—"
        assert metrics.get("打回率") == "—"
        caption_text = "".join(str(c.value) for c in at.caption)
        assert "数据库不可用" in caption_text           # 降级文案（灰注纪律）
        # 灰注两卡照常在场
        assert metrics.get("替换测试通过率") == "—"
        assert metrics.get("体例质检通过率") == "—"

    def test_metrics_tab_smoke_without_stubs(self):
        """无打桩冒烟（连真库或库不可用均降级渲染）：不崩且五卡标签齐全。"""
        at = AppTest.from_string(_METRICS_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        labels = {m.label for m in at.metric}
        for title in ("提案总数", "待裁决", "采纳率", "AI-人一致率", "标注节省量",
                      "打回率", "替换测试通过率", "体例质检通过率"):
            assert title in labels, f"协同度量缺卡：{title}"
