"""FX-24（规范×实现对账 ②组末项）测试：主编驾驶舱「⚠️ 风险清单」＋「📥 待我裁决汇总」。

口径（与 src/dict_admin_pages.py FX-24 段注释一致）：
  * 两段在场且驾驶舱整体渲染不抛异常（stub st 假体驱动全 tab）；
  * 风险项计数正确性（夹具/桩驱动：存疑义位 flagged 合计、pending 按 kind
    GROUP BY 分列、待我审校 len、信度未达标明细包装）；
  * 零风险「✅ 无」路径（全部计数为真 0 且探测通过 → 无灰注）；
  * R4 降级路径（取数失败 → 「数据不可用：<原因>」灰注 ＋ 指标画「—」＋
    内联降级披露 warning；空结果探测不过区分「真 0」与「取数失败」）；
  * 权限：两段仅词典管理员可见（_current_user 兜底门，非 admin 不渲染）；
  * 纪律：两段零写路径（无 st.rerun / ui_kit.flash / st.success / 跳转控件）。

本文件不连数据库（全部 monkeypatch 假体驱动；DB 可达性属集成测试范畴）。
"""
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402

import src.dict_admin_pages as dp  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    FX24_STALE_DAYS,
    _fx24_alpha_threshold,
    _fx24_collect_doubt_senses,
    _fx24_collect_divided_backlog,
    _fx24_collect_low_alpha_detail,
    _fx24_collect_my_reviews,
    _fx24_collect_pending_by_kind,
    _fx24_collect_stale_reviews,
    _fx24_collect_stale_snapshots,
    _fx24_collect_risk_items,
    _render_cockpit_tab,
    _render_my_decisions_section,
    _render_risk_list_section,
)


# ============================================
# 假体：st 假体（含 metric/上下文管理器）与路由式假 cursor
# ============================================

@pytest.fixture(autouse=True)
def _clear_fx24_progress_cache():
    """每用例清驾驶舱进度缓存（批次 20 手写 TTL——跨用例污染防线）。"""
    dp._FX24_PROGRESS_CACHE.clear()
    yield
    dp._FX24_PROGRESS_CACHE.clear()


class _StubCol:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubContainer:
    """st.container(border=True) 桩（FX-40 风险行容器）。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def columns(self, spec, **kwargs):
        return [_StubCol() for _ in range(spec if isinstance(spec, int) else len(spec))]

    def markdown(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def container(self, *args, **kwargs):
        return _StubContainer()

    def button(self, *args, **kwargs):
        return False


class _StubSt:
    """st 假体：驾驶舱全 tab 渲染所需控件的最小实现，记录调用供断言。"""

    def __init__(self):
        self.messages = []       # (kind, text)
        self.metrics = []        # (label, value)

    # —— 上下文管理器族（columns/expander/form/container）——
    def container(self, *args, **kwargs):
        return _StubContainer()

    def button(self, *args, **kwargs):
        # 渲染面不点击（_StubSt 语义：只验渲染形态）
        return False

    def columns(self, spec, **kwargs):
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_StubCol() for _ in range(n)]

    def expander(self, *args, **kwargs):
        return _StubCol()

    def form(self, *args, **kwargs):
        return _StubCol()

    # —— 控件族 ——
    def selectbox(self, *args, **kwargs):
        opts = kwargs.get("options") or (args[1] if len(args) > 1 else [])
        return opts[0] if opts else None

    def text_input(self, *args, **kwargs):
        return ""

    def form_submit_button(self, *args, **kwargs):
        return False

    def button(self, *args, **kwargs):
        # RV21-1：质检段改普通按钮后桩同面（渲染面不点击）
        return False

    def metric(self, label, value=None, **kwargs):
        self.metrics.append((label, value))

    # —— 输出族 ——
    def markdown(self, *args, **kwargs):
        self.messages.append(("markdown", args[0] if args else ""))

    def caption(self, *args, **kwargs):
        self.messages.append(("caption", args[0] if args else ""))

    def info(self, *args, **kwargs):
        self.messages.append(("info", args[0] if args else ""))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args[0] if args else ""))

    def success(self, *args, **kwargs):
        self.messages.append(("success", args[0] if args else ""))

    def error(self, *args, **kwargs):
        self.messages.append(("error", args[0] if args else ""))

    def rerun(self):
        self.messages.append(("rerun", ""))

    # —— 断言辅助 ——
    def texts(self, kind=None):
        return [t for k, t in self.messages if kind is None or k == kind]

    def joined(self):
        return "\n".join(t for _, t in self.messages)


class _FakeCursor:
    """路由式只读假 cursor：按 SQL 子串回放预置行，probe/失败可配。

    routes: [(子串, rows)]；fail_on: [子串]（execute 即抛 RuntimeError）；
    probes_ok=False 时 SELECT 1 FROM ...（连通探测）一律失败。
    行形态与生产 DictCursor 对齐（dict）。
    """

    def __init__(self, routes=None, fail_on=None, probes_ok=True):
        self.routes = list(routes or [])
        self.fail_on = list(fail_on or [])
        self.probes_ok = probes_ok
        self.executed = []
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        for sub in self.fail_on:
            if sub in sql:
                raise RuntimeError(f"假库故障（{sub}）")
        if sql.startswith("SELECT 1 FROM"):
            if not self.probes_ok:
                raise RuntimeError("探测目标不可达")
            self._rows = []
            return
        for sub, rows in self.routes:
            if sub in sql:
                self._rows = list(rows)
                return
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


_ME_ADMIN = {"id": 7, "username": "fx24chief", "display_name": "主编",
             "role": "viewer", "roles": ["dict_admin"], "active": True}
_ME_NOBODY = {"id": 8, "username": "viewer1", "display_name": "路",
              "role": "viewer", "roles": ["viewer"], "active": True}


def _patch_ok_world(monkeypatch, *, flagged=0, divided_n=0, stale_n=0,
                    snap_n=0, pending_rows=None, my_reviews=0, probes_ok=True):
    """一键铺一套「全只读取数就绪」的假世界（各用例再按需覆写单点）。"""
    fake = _FakeCursor(
        routes=[
            ("COUNT(*) AS n FROM cs_senses", [{"n": divided_n}]),
            ("COUNT(DISTINCT t.version_id", [{"n": stale_n}]),
            ("FROM export_batches", [{"n": snap_n}]),
            ("FROM reliability_runs", []),
            ("FROM ai_proposals WHERE status", list(pending_rows or [])),
        ],
        probes_ok=probes_ok,
    )
    monkeypatch.setattr(dp, "get_db_cursor", lambda: fake)
    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress",
                        lambda: [{"verb": "run", "flagged": flagged}])
    monkeypatch.setattr(dp.writing_db, "count_pending_reviews",
                        lambda reviewer_id=None: my_reviews)
    return fake


# ============================================
# 契约常量
# ============================================

def test_stale_days_constant_is_seven():
    """「超过 N 天」口径常量 N=7（任务书口径，风险行文案引用）。"""
    assert FX24_STALE_DAYS == 7


def test_alpha_threshold_mirrors_reliability_source():
    """G2 达标线单一事实源 reliability.LOW_ALPHA_THRESHOLD（导入成功取 0.7）。"""
    from src.reliability import LOW_ALPHA_THRESHOLD
    assert _fx24_alpha_threshold() == float(LOW_ALPHA_THRESHOLD) == 0.7


# ============================================
# 计数正确性（夹具/桩驱动）
# ============================================

def test_doubt_senses_sums_flagged(monkeypatch):
    """存疑义位 = get_annotation_progress 各行 flagged 合计（None 行按 0）。"""
    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress",
                        lambda: [{"verb": "a", "flagged": 3},
                                 {"verb": "b", "flagged": 4},
                                 {"verb": "c", "flagged": None}])
    ok, value = _fx24_collect_doubt_senses()
    assert ok and value == 7


def test_doubt_senses_degrades_on_none(monkeypatch):
    """get_annotation_progress R4-1 fail-closed（None）→ 数据不可用。"""
    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress", lambda: None)
    ok, value = _fx24_collect_doubt_senses()
    assert not ok and "标注进度查询失败" in str(value)


def test_pending_by_kind_exact_group_by(monkeypatch):
    """pending 按 kind 分列 = 轻量 GROUP BY 精确计数（缺失通道补 0）。"""
    monkeypatch.setattr(dp, "get_db_cursor", lambda: _FakeCursor(routes=[
        ("FROM ai_proposals WHERE status",
         [{"kind": "draft", "n": 2}, {"kind": "probe", "n": 1}]),
    ]))
    counts, reason = _fx24_collect_pending_by_kind()
    assert reason is None
    assert counts == {"draft": 2, "audit": 0, "probe": 1}


def test_my_reviews_counts_current_user_assignment(monkeypatch):
    """待我审校 = 当前用户为受派审校人的 pending 任务数（reviewer_id 透传）。"""
    seen = {}

    def _fake_count(reviewer_id=None):
        seen["reviewer_id"] = reviewer_id
        return 2

    monkeypatch.setattr(dp, "get_db_cursor", lambda: _FakeCursor())
    monkeypatch.setattr(dp.writing_db, "count_pending_reviews", _fake_count)
    ok_n, reason = _fx24_collect_my_reviews(7)
    assert reason is None and ok_n == 2
    assert seen["reviewer_id"] == 7


def test_low_alpha_detail_wraps_count_and_examples(monkeypatch):
    """信度未达标 = 「n（明细至多两条…等k项）」包装；空明细如实 0。"""
    monkeypatch.setattr(dp, "get_db_cursor", lambda: _FakeCursor(routes=[
        ("FROM reliability_runs",
         [{"category": "motion", "task_type": "feature_coding",
           "overall_alpha": 0.412},
          {"category": "speech", "task_type": "admission",
           "overall_alpha": 0.55},
          {"category": "speech", "task_type": "alignment",
           "overall_alpha": 0.61}]),
    ]))
    ok, value = _fx24_collect_low_alpha_detail()
    assert ok
    assert str(value).startswith("3（")
    assert "motion·feature_coding α=0.412" in str(value)
    assert "等1项" in str(value)
    monkeypatch.setattr(dp, "get_db_cursor", lambda: _FakeCursor(routes=[
        ("FROM reliability_runs", [])]))
    ok0, value0 = _fx24_collect_low_alpha_detail()
    assert ok0 and value0 == 0


def test_stale_reviews_params_use_constant_and_pending_verdict(monkeypatch):
    """撰写侧积压 SQL 参数 = (verdict='pending', N=7)；口径常量进 SQL。"""
    fake = _FakeCursor(routes=[("COUNT(DISTINCT t.version_id", [{"n": 3}])])
    monkeypatch.setattr(dp, "get_db_cursor", lambda: fake)
    ok, value = _fx24_collect_stale_reviews()
    assert ok and value == 3
    sql, params = fake.executed[0]
    assert "review_tasks" in sql and "created_at < NOW() - INTERVAL" in sql
    assert params == (dp.writing_db.VERDICT_PENDING, FX24_STALE_DAYS)


def test_stale_snapshots_params_use_ready_status(monkeypatch):
    """验收期风险 SQL 参数 = (status='ready', N=7)。"""
    fake = _FakeCursor(routes=[("FROM export_batches", [{"n": 5}])])
    monkeypatch.setattr(dp, "get_db_cursor", lambda: fake)
    ok, value = _fx24_collect_stale_snapshots()
    assert ok and value == 5
    _, params = fake.executed[0]
    assert params == (dp.export_center.EXPORT_STATUS_READY, FX24_STALE_DAYS)


def test_risk_items_five_rows_with_pointers(monkeypatch):
    """风险清单恒五项；每项带处理入口指路；tone 按数据分流。"""
    _patch_ok_world(monkeypatch, flagged=992, divided_n=2, stale_n=0,
                    snap_n=1, pending_rows=[{"kind": "draft", "n": 4}],
                    my_reviews=3)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    items = _fx24_collect_risk_items()
    assert len(items) == 5
    labels = " ".join(it["item"] for it in items)
    assert "存疑义位" in labels and "信度未达标" in labels
    assert "分立复核积压" in labels and "撰写侧积压" in labels
    assert "验收期风险" in labels
    assert all(it["pointer"].strip() for it in items)
    tones = {it["item"].split("（")[0]: it["tone"] for it in items}
    assert tones["存疑义位"] == "risk"
    assert tones["撰写侧积压"] == "zero"


# ============================================
# 空结果探测：区分「真 0」与「取数失败」（R4-3）
# ============================================

def test_divided_zero_with_probe_pass_is_true_zero(monkeypatch):
    """cs_senses 计数 0 且连通探测通过 → 真 0。"""
    monkeypatch.setattr(dp, "get_db_cursor",
                        lambda: _FakeCursor(routes=[
                            ("COUNT(*) AS n FROM cs_senses", [{"n": 0}])],
                            probes_ok=True))
    ok, value = _fx24_collect_divided_backlog()
    assert ok and value == 0


def test_divided_zero_with_probe_fail_degrades(monkeypatch):
    """cs_senses 计数 0 但探测不过 → 取数失败（不冒充真 0）。"""
    monkeypatch.setattr(dp, "get_db_cursor",
                        lambda: _FakeCursor(routes=[
                            ("COUNT(*) AS n FROM cs_senses", [{"n": 0}])],
                            probes_ok=False))
    ok, value = _fx24_collect_divided_backlog()
    assert not ok and "cs_senses" in str(value)


def test_my_reviews_zero_with_probe_fail_degrades(monkeypatch):
    """count_pending_reviews 返 None（库不可用计数契约）→ 探测兜底归因。"""
    monkeypatch.setattr(dp, "get_db_cursor",
                        lambda: _FakeCursor(probes_ok=False))
    monkeypatch.setattr(dp.writing_db, "count_pending_reviews",
                        lambda reviewer_id=None: None)
    ok_n, reason = _fx24_collect_my_reviews(7)
    assert ok_n is None and "review_tasks" in str(reason)


# ============================================
# 渲染：驾驶舱整体 not at exception ＋ 两段在场
# ============================================

def _patch_cockpit_shell(monkeypatch, stub):
    """驾驶舱既有三段（指标卡/漏斗/自检＋建壳表单）的取数假体。"""
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    monkeypatch.setattr(dp.org_db, "list_projects",
                        lambda: [{"id": 1, "name": "P1", "member_count": 2}])
    monkeypatch.setattr(dp.ai_ledger, "get_stats",
                        lambda: {"total": 3, "pending": 1,
                                 "adoption_rate": 0.5, "avg_uncertainty": 0.2})
    monkeypatch.setattr(dp.pipeline_status, "get_cluster_pipeline_status",
                        lambda cat: {"study_code": None})
    monkeypatch.setattr(dp.pipeline_status, "format_funnel_segments",
                        lambda status: [("工序4 义位准入", "cs_senses 保留 12")])
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [])
    monkeypatch.setattr(dp.org_db, "project_selfcheck", lambda pid: (True, []))


def test_cockpit_tab_renders_without_exception(monkeypatch):
    """驾驶舱全 tab（既有三段＋FX-24 两段）渲染 not at exception，两段在场。"""
    stub = _StubSt()
    _patch_cockpit_shell(monkeypatch, stub)
    _patch_ok_world(monkeypatch, flagged=3, divided_n=0, stale_n=0, snap_n=0,
                    pending_rows=[{"kind": "draft", "n": 2},
                                  {"kind": "probe", "n": 1}],
                    my_reviews=2)
    _render_cockpit_tab()
    joined = stub.joined()
    assert "⚠️ 风险清单" in joined
    assert "📥 待我裁决汇总" in joined
    # 存疑义位计数 3+4?（单行动口）/ 此处夹具 flagged=3 → 数量格出现 3
    assert "存疑义位" in joined
    # 处理入口指路（caption）：AI 协作页 / 释义撰写与审校页
    assert "AI 协作" in joined
    assert "释义撰写与审校" in joined
    metric_labels = [label for label, _ in stub.metrics]
    assert any("draft" in m for m in metric_labels)
    assert any("audit" in m for m in metric_labels)
    assert any("probe" in m for m in metric_labels)
    assert any("待我审校" in m for m in metric_labels)


def test_cockpit_metric_values_correct(monkeypatch):
    """待我裁决四卡的计数正确（draft=2/audit=0/probe=1/待我审校=2）。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    _patch_ok_world(monkeypatch, flagged=0, divided_n=0, stale_n=0, snap_n=0,
                    pending_rows=[{"kind": "draft", "n": 2},
                                  {"kind": "probe", "n": 1}],
                    my_reviews=2)
    _render_my_decisions_section()
    metrics = dict(stub.metrics)
    assert metrics["AI 提案·草稿（draft）待裁决"] == 2
    assert metrics["AI 提案·质检（audit）待裁决"] == 0
    assert metrics["AI 提案·探针（probe）待裁决"] == 1
    assert metrics["待我审校（受派审校人）"] == 2


def _risk_card_text(stub):
    """取风险清单行 markdown（批次 20 起为行容器 span：font-weight:600 标记）。"""
    return "\n".join(t for k, t in stub.messages
                     if k == "markdown" and "font-weight:600" in t)


def test_risk_card_renders_counts_and_jump_hints(monkeypatch):
    """风险清单行渲染：数量格如实（存疑=992）、零风险「✅ 无」、指路在场。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    _patch_ok_world(monkeypatch, flagged=992, divided_n=0, stale_n=0, snap_n=0)
    _render_risk_list_section()
    card = _risk_card_text(stub)
    assert ">992</span>" in card
    assert card.count("✅ 无") == 4
    assert "数据不可用" not in card
    # 单目标行（存疑/信度/分立）改「前往 →」按钮（RV21-3）——指路文字不进
    # 行卡，按钮由桩 button 记录面覆盖（源级钉板见 test_sections_have_no_write_path）
    # 文字指路仅剩两行：撰写侧积压（审校台）＋快照滞留（出版导出）
    blob = card + " ".join(
        t for k, t in stub.messages if k in ("caption", "button"))
    assert "出版导出" in blob and "释义撰写与审校" in blob
    assert "发起重标" not in blob and "标注平台" not in blob


# ============================================
# 渲染：零风险「✅ 无」路径 ＋ R4 降级路径
# ============================================

def test_zero_risk_renders_no_gray_notes(monkeypatch):
    """全部真 0 → 五行「✅ 无」、无灰注、四卡 0 且无降级 warning。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    _patch_ok_world(monkeypatch, flagged=0, divided_n=0, stale_n=0, snap_n=0,
                    pending_rows=[], my_reviews=0, probes_ok=True)
    _render_risk_list_section()
    _render_my_decisions_section()
    card = _risk_card_text(stub)
    assert card.count("✅ 无") == 5
    assert "数据不可用" not in card
    assert not stub.texts("warning")
    assert set(dict(stub.metrics).values()) == {0}


def test_degraded_world_renders_unavailable_notes_and_dash(monkeypatch):
    """全取数失败 → 「数据不可用：<原因>」灰注 ×5、指标「—」×4、降级披露。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp, "_current_user", lambda: _ME_ADMIN)
    # db 一律故障（任何 SQL 即抛，probe 也不过）；标注进度 R4-1 返回 None；
    # 待我审校被数据层折叠 [] 后探测不过 → 灰注。
    monkeypatch.setattr(
        dp, "get_db_cursor",
        lambda: _FakeCursor(fail_on=["SELECT"], probes_ok=False))
    monkeypatch.setattr(dp.mysql_db, "get_annotation_progress", lambda: None)
    monkeypatch.setattr(dp.writing_db, "count_pending_reviews",
                        lambda reviewer_id=None: None)
    _render_risk_list_section()
    _render_my_decisions_section()
    joined = stub.joined()
    assert joined.count("数据不可用：") == 5
    assert list(dict(stub.metrics).values()) == ["—"] * 4
    assert stub.texts("warning"), "降级披露 warning 必须在场"


# ============================================
# 权限：两段仅词典管理员可见（兜底门）
# ============================================

def test_sections_hidden_without_dict_admin(monkeypatch):
    """未登录 / 非词典管理员 → 两段一概不渲染（fail-closed）。"""
    for user in (None, _ME_NOBODY):
        stub = _StubSt()
        monkeypatch.setattr(dp, "st", stub)
        monkeypatch.setattr(dp, "_current_user", lambda user=user: user)
        _render_risk_list_section()
        _render_my_decisions_section()
        joined = stub.joined()
        assert "⚠️ 风险清单" not in joined
        assert "📥 待我裁决汇总" not in joined
        assert not stub.metrics


# ============================================
# 纪律：零写路径、无跳转控件
# ============================================

def test_sections_have_no_write_path_and_no_links():
    """两段渲染器零写路径（无 rerun/flash/success）；导航按钮=纯 page 路由
    （批次 20 RV21-3：on_click 仅写 session_state["page"]，无业务写路径），
    st.link_button（外链）仍禁止。"""
    for fn in (_render_risk_list_section, _render_my_decisions_section):
        src = inspect.getsource(fn)
        assert "st.rerun" not in src, fn.__name__
        assert "ui_kit.flash" not in src, fn.__name__
        assert "st.success" not in src, fn.__name__
        assert "st.link_button" not in src, fn.__name__
        if "st.button" in src:  # 导航按钮只准写 page 键（RV12-1 回调纪律）
            import re as _re
            goto_writes = _re.findall(
                r"st\.session_state\.update\(page=([^)]+)\)", src)
            assert goto_writes, f"{fn.__name__} 有按钮但无 page 路由"
            for w in goto_writes:
                assert w.strip() == "pk", (
                    f"{fn.__name__} 按钮路由出现非 page 写: {w}")  # 回调闭包变量 pk


def test_risk_collectors_are_read_only_sql():
    """风险面采集只用 SELECT（只读纪律：出现写动词即失守）。"""
    import re
    for name in ("_fx24_scalar_count", "_fx24_collect_doubt_senses",
                 "_fx24_collect_low_alpha", "_fx24_collect_divided_backlog",
                 "_fx24_collect_stale_reviews", "_fx24_collect_stale_snapshots",
                 "_fx24_collect_pending_by_kind"):
        src = inspect.getsource(getattr(dp, name))
        writes = re.findall(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b", src)
        assert not writes, f"{name} 出现写动词: {writes}"
