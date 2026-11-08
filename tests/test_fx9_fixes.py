"""FX9 批次修复测试：R5-8 义位下拉静默截断 ＋ R4-1 尾部缺表/真不足二分。

对应修复清单（docs/dev/reports/findings_backlog.md，FX9 批次；R4-1/R4-5/
R4-6/R4-7 的核心已由 FX3 落地——tests/test_fx3_perf.py 覆盖页面三口径、
plotly 降级与 MOCK 来源徽章，本文件不重复，只补 FX9 的增量）：

  * R5-8  lexical_pages._list_sense_options 去 LIMIT 全量拉取 —— 曾硬编码
    ``LIMIT 1000`` 且不校验条数，义位规模逼近上限（当前 996 行）后 split
    增量溢出的义项会无声消失（下拉静默缺项）。行为断言：执行 SQL 不含
    LIMIT 子句与占位参数；>1000 行（旧上限）全量返回；库不可用仍按空清单
    优雅降级（原异常契约不动）。
  * R4-1 尾部  cluster_analysis 深探针二分 —— FX3 的主探针只验
    cs_cluster_runs；主探针可达但 ranking 为空时，底层 category_study 把
    深层缺表（cs_clusters / cs_cluster_members / cs_senses / cs_lexemes /
    cs_sense_features）静默折叠成 []，页面曾误报「未灌入」、三 tab 曾误报
    「数据不足（簇成员少于 2 个）」。新增 _cluster_family_reachable_error
    （覆盖 _load_cluster_matrix 全部读面的 LEFT JOIN 探针，仅空态分支调用，
    正常路径零开销）：缺表/连接中断归 load_error → 页面与谱系/分立/图谱
    三 tab 均走「数据不可用（勿重跑灌库）」；探针可达维持「未灌入」原语义。

外部依赖隔离：数据层断言一律假游标（不连库）；AppTest 用例打桩
_load_page_data（fx3 TestSemanticPageThreeWay 同模式，不连库）。
st.cache_data 进程级缓存在 autouse fixture 统一 clear，防串场。
"""

import os
import sys

import pymysql
import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.cluster_analysis as ca  # noqa: E402
import src.lexical_pages as lp  # noqa: E402

_CA_PAGE_SCRIPT = (
    "from src import cluster_analysis as ca\n"
    "ca.render_semantic_analysis_page()\n"
)


# ============================================
# 假游标（fx3 CountingFakeCursor 同思路）
# ============================================
class _FakeCtx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class _CaptureCursor:
    """记录 SQL ＋回放行的假游标（lexical _list_sense_options 断言用）。"""

    def __init__(self, rows=None, error_on=None):
        self.rows = rows or []
        self.error_on = error_on or ()
        self.executed = []
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if any(pat in sql for pat in self.error_on):
            raise pymysql.Error("fake connection failure")
        self._result = list(self.rows)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _RouteCursor:
    """按 SQL 关键字分派的假游标（路由顺序匹配，首条命中生效）。

    深探针 SQL 也含「FROM cs_cluster_runs」子串，故深探针路由（更具体的
    「LEFT JOIN cs_sense_features」）必须排在主探针路由之前。
    routes: [(sql_contains, kind, payload)]；kind="raise" 抛 payload，
    kind="rows" 回放 payload；未命中任何路由即 AssertionError（防打桩面漂移）。
    """

    def __init__(self, routes):
        self.routes = routes
        self.executed = []
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        for pat, kind, payload in self.routes:
            if pat in sql:
                if kind == "raise":
                    raise payload
                self._rows = list(payload)
                return
        raise AssertionError(f"未打桩的 SQL: {sql[:100]}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


@pytest.fixture(autouse=True)
def _clear_page_caches():
    """清 st.cache_data 进程级缓存（_load_page_data 键含 scope，仍统一清防串场）。"""
    ca._load_page_data.clear()
    yield
    ca._load_page_data.clear()


# ============================================
# R5-8：义位下拉选项全量拉取（去 LIMIT 静默截断）
# ============================================
def _sense_row(i: int) -> dict:
    return {"id": i, "sense_no": str(i), "sense_label": f"义位{i}",
            "status": "保留", "merged_into": None,
            "lemma": f"verb{i}", "language": "en"}


class TestR58SenseOptionsFullPull:
    def test_sql_has_no_limit_clause(self, monkeypatch):
        """执行 SQL 不含 LIMIT 子句与占位参数（静默截断源头移除）。"""
        cursor = _CaptureCursor(rows=[_sense_row(1), _sense_row(2)])
        monkeypatch.setattr(lp, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        rows = lp._list_sense_options()
        assert len(rows) == 2
        assert len(cursor.executed) == 1
        sql = " ".join(cursor.executed).upper()
        assert "LIMIT" not in sql
        assert "%S" not in sql  # 无占位参数 —— LIMIT 形参已随之移除

    def test_full_pull_beyond_old_cap(self, monkeypatch):
        """>1000 行（旧硬编码上限）全量返回，不再无声截断。"""
        cursor = _CaptureCursor(rows=[_sense_row(i) for i in range(1, 1501)])
        monkeypatch.setattr(lp, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        rows = lp._list_sense_options()
        assert len(rows) == 1500
        assert rows[-1]["id"] == 1500

    def test_db_failure_still_degrades_to_empty(self, monkeypatch):
        """库不可用仍按空清单降级（R5-8 不动原异常契约，页面优雅降级）。"""
        cursor = _CaptureCursor(error_on=("cs_senses",))
        monkeypatch.setattr(lp, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert lp._list_sense_options() == []


# ============================================
# R4-1 尾部：簇谱系表族深探针（缺表 vs 真数据不足二分）
# ============================================
_MAIN_PROBE_PAT = "FROM cs_cluster_runs"
_DEEP_PROBE_PAT = "LEFT JOIN cs_sense_features"


class TestR41DeepFamilyProbe:
    def _patch_ranking_empty(self, monkeypatch):
        """主探针可达但 ranking 空的触发面：底层取数被折叠成 []。"""
        monkeypatch.setattr(ca, "compute_medoid_ranking", lambda *a, **k: [])

    def test_deep_probe_success_keeps_unseeded_semantics(self, monkeypatch):
        """全表族可达＋无运行 → load_error=None、dendro={}（「未灌入」原语义）。"""
        cursor = _RouteCursor([
            (_DEEP_PROBE_PAT, "rows", [{"n": 0}]),
            (_MAIN_PROBE_PAT, "rows", [{"n": 0}]),
        ])
        monkeypatch.setattr(ca, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        self._patch_ranking_empty(monkeypatch)
        data = ca._load_page_data("scope", "motion", "en")
        assert data["load_error"] is None
        assert data["dendro"] == {}
        assert data["ranking"] == []
        assert data["scipy_missing"] is False
        assert len(cursor.executed) == 2  # 主探针＋深探针（仅空态分支触发）

    def test_deep_family_missing_table_attributed_as_load_error(self, monkeypatch):
        """主探针可达但表族缺表（如 cs_clusters）→ load_error 带「勿重跑灌库」
        语义的原因，dendro 同步带 load_error（三 tab 走「数据不可用」）。"""
        cursor = _RouteCursor([
            (_DEEP_PROBE_PAT, "raise",
             pymysql.Error("Table 'web_word_db.cs_clusters' doesn't exist")),
            (_MAIN_PROBE_PAT, "rows", [{"n": 2}]),
        ])
        monkeypatch.setattr(ca, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        self._patch_ranking_empty(monkeypatch)
        data = ca._load_page_data("scope", "motion", "en")
        assert data["load_error"], "缺表应归因 load_error，而非误报未灌入"
        assert "范畴深挖数据读取失败" in data["load_error"]
        assert data["dendro"] == {"load_error": data["load_error"]}
        assert data["ranking"] == []

    def test_main_probe_failure_skips_deep_probe(self, monkeypatch):
        """主探针失败即短路：深探针不再执行（断库下仍只发一条 SQL）。"""
        cursor = _RouteCursor([
            (_DEEP_PROBE_PAT, "rows", [{"n": 0}]),
            (_MAIN_PROBE_PAT, "raise", pymysql.Error("connection refused")),
        ])
        monkeypatch.setattr(ca, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        self._patch_ranking_empty(monkeypatch)
        data = ca._load_page_data("scope", "motion", "en")
        assert data["load_error"] and "范畴深挖数据读取失败" in data["load_error"]
        assert len(cursor.executed) == 1

    def test_deep_probe_covers_matrix_read_surface(self, monkeypatch):
        """深探针 SQL 覆盖 _load_cluster_matrix 全部读面：缺任一表都能归因。"""
        cursor = _RouteCursor([
            (_DEEP_PROBE_PAT, "rows", [{"n": 0}]),
            (_MAIN_PROBE_PAT, "rows", [{"n": 0}]),
        ])
        monkeypatch.setattr(ca, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        self._patch_ranking_empty(monkeypatch)
        ca._load_page_data("scope", "motion", "en")
        deep_sql = next(s for s in cursor.executed if _DEEP_PROBE_PAT in s)
        for table in ("cs_clusters", "cs_cluster_members", "cs_senses",
                      "cs_lexemes", "cs_sense_features"):
            assert table in deep_sql, f"深探针应覆盖 {table}"

    def test_family_probe_direct(self, monkeypatch):
        """_cluster_family_reachable_error 直测：可达 None / 失败带原因。"""
        ok = _RouteCursor([(_DEEP_PROBE_PAT, "rows", [{"n": 3}])])
        monkeypatch.setattr(ca, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(ok))
        assert ca._cluster_family_reachable_error() is None
        bad = _RouteCursor([(_DEEP_PROBE_PAT, "raise", pymysql.Error("boom"))])
        monkeypatch.setattr(ca, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(bad))
        err = ca._cluster_family_reachable_error()
        assert err and "范畴深挖数据读取失败" in err


# ============================================
# R4-1 尾部端到端：三 tab「数据不可用」而非「数据不足」
# ============================================
def _patch_semantic_page(monkeypatch, page_data, ready=True, categories=None,
                         reachable=True):
    """打桩语义分析页全部 DB 触点（fx3 _patch_semantic_page 同模式）。"""
    monkeypatch.setattr(ca, "_load_page_data", lambda _s, c, lang: page_data)
    monkeypatch.setattr(ca, "category_study_ready", lambda: ready)
    monkeypatch.setattr(ca, "get_categories", lambda: categories or [])
    monkeypatch.setattr(ca, "_categories_table_reachable", lambda: reachable)
    monkeypatch.setattr(ca, "ensure_sense_split_columns", lambda: None)
    monkeypatch.setattr(ca, "ensure_cluster_locked_column", lambda: None)


class TestR41TabsUnavailableNotInsufficient:
    """深缺表二分端到端：dendro.load_error → 分立复核/义位图谱走「数据不可用」，
    不再误报「数据不足（簇成员少于 2 个）」（R4-5 二分在 tab 层的落地验证）。"""

    _DATA = {"ranking": [], "dendro": {"load_error": "簇谱系表族缺表"},
             "scipy_missing": False, "load_error": "簇谱系表族缺表"}

    def test_division_tab_unavailable_on_load_error(self, monkeypatch):
        _patch_semantic_page(monkeypatch, self._DATA, ready=False, reachable=True)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("数据不可用：簇谱系表族缺表" in w and "勿重跑灌库" in w
                   for w in warnings)
        assert any("分立复核暂不可用" in w for w in warnings)
        assert not any("数据不足" in w for w in warnings), \
            f"缺表不得误报「数据不足」: {warnings}"
        assert not any("暂无聚类运行数据" in t for t in
                       [str(i.value) for i in at.info])

    def test_graph_tab_unavailable_on_load_error(self, monkeypatch):
        monkeypatch.setattr(ca, "HAS_PLOTLY", True)  # 缺 plotly 的降级另有 FX3 用例
        _patch_semantic_page(monkeypatch, self._DATA, ready=False, reachable=True)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("义位图谱暂不可用" in w for w in warnings)
        assert not any("数据不足" in w for w in warnings), \
            f"缺表不得误报「数据不足」: {warnings}"
