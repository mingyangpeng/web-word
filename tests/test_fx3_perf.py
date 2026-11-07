"""FX3 批次修复测试：R5 性能族（P1×3 + P3×2）＋ R4 归因/降级族（P2×1 + P3×5）。

对应修复清单（docs/dev/reports/findings_backlog.md R5/R4，FX3 批次）：

  * R5-1  app.py init_database 会话级单例守卫 —— 同一会话两次 rerun 只建一次
    初始化连接（AppTest 计数 pymysql.connect 的「无 database 参数」调用，
    即 init_database 的专用连接；连接池取数连接都带 database 参数，不混计）。
  * R5-2  mysql_db.get_full_word_graph 包 st.cache_data(ttl=300)、首参
    cache_scope_key() —— 假游标计数命中断言；查询失败返 None（R4-1 归因）。
  * R5-3  侧边栏反馈导出按需化 —— 默认渲染「生成导出」按钮＋行数 caption
    （轻量 COUNT），不触发全表 SELECT *；点击后才取数并出现下载按钮
    （导出功能保留，AppTest 点击流断言）。
  * R5-9  get_hot_verbs 包 st.cache_data(ttl=60)（假游标计数命中断言）。
  * R5-10 reliability_runs (category, task_type) 幂等索引迁移 —— 假游标下
    「未建则 CREATE INDEX、已建不重复建、探针拿不到结果不炸」（仿
    _migrate_created_by_column 的既有迁移模式）。
  * R4-1  读函数 None vs [] 三口径：get_oald_senses / get_senses /
    get_annotation_progress / get_cluster_graph / get_full_word_graph 失败返
    None（区别于空集）；app.py 图谱页与 cluster_analysis 语义分析页的空态
    分流（None→数据不可用勿重跑灌库；[]→未灌入指引；有数→正常）。
  * R4-2  侧边栏离线统计显示 "—" 而非 0（口径对齐 ai_hub）。
  * R4-4  登出提示语分流：users 表探针可达才说「停用或删除」，探针失败说
    「账号状态暂无法核实（服务暂不可用）」。
  * R4-6  MOCK 兜底带 source="内置示例" 标记；卡片渲染「内置示例（非词典
    数据）」徽章（复用来源分级徽章样式）。
  * R4-7  cluster_analysis HAS_PLOTLY 模块级降级：_render_dendrogram /
    _render_sense_graph_tab 入口缺 plotly 时 warning＋return，不炸 tab。

外部依赖隔离：数据层断言一律假游标（不连库）；AppTest 用例分两类 ——
真实库（R5-1/R5-3，MySQL 不可用则 skip）与打桩/断库模拟（R4-2 与页面
三口径，不连库）。st.cache_data 进程级缓存在本模块的 fixture 中统一
clear，防止污染同进程其它用例（graph 页 S3 矩阵等）。
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pymysql  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import src.mysql_db as db  # noqa: E402
import src.cluster_analysis as ca  # noqa: E402
import src.reliability as rel  # noqa: E402
import src.app as app_module  # noqa: E402

APP = os.path.join(PROJECT_ROOT, "src", "app.py")

_CA_PAGE_SCRIPT = (
    "from src import cluster_analysis as ca\n"
    "ca.render_semantic_analysis_page()\n"
)
_GRAPH_PAGE_SCRIPT = (
    "import src.app as app_module\n"
    "app_module.render_interactive_graph_page()\n"
)


def _db_available() -> bool:
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_available(), reason="MySQL 不可用，跳过 AppTest 真库用例")


# ============================================
# 假游标（按 SQL 文本分派，仿 test_reliability.FakeRelCursor 模式）
# ============================================
class _FakeCtx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class CountingFakeCursor:
    """计数假游标：记录 execute 的 SQL；命中 error_on 子串即抛 pymysql.Error。"""

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


@pytest.fixture(autouse=True)
def _clear_page_caches():
    """清本批新增/相关 st.cache_data 进程级缓存，防串场（S1 review 同款教训）。"""
    db.get_full_word_graph.clear()
    db.get_hot_verbs.clear()
    ca._load_page_data.clear()
    yield
    db.get_full_word_graph.clear()
    db.get_hot_verbs.clear()
    ca._load_page_data.clear()


# ============================================
# R5-2 get_full_word_graph 缓存 + R4-1 None 归因
# ============================================
class TestFullWordGraphCache:
    def test_cache_hit_no_second_fetch(self, monkeypatch):
        """同 scope 二次调用不重新取数（st.cache_data 命中），换 scope 即重取。"""
        cursor = CountingFakeCursor()
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        g1 = db.get_full_word_graph("scope-a")
        g2 = db.get_full_word_graph("scope-a")
        assert g1 is not None and g2 is not None
        assert g1 == g2
        # 5 张表一次全量 fetchall：命中后 execute 计数不变
        assert len(cursor.executed) == 5
        db.get_full_word_graph("scope-b")  # 换库（scope）→ 新缓存槽位 → 再取
        assert len(cursor.executed) == 10

    def test_failure_returns_none_distinct_from_empty(self, monkeypatch):
        """查询失败返 None（数据不可用），区别于表在无数据的空图。"""
        cursor = CountingFakeCursor(error_on=("FROM definitions d",))
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.get_full_word_graph("scope-fail") is None

    def test_empty_db_returns_empty_graph_not_none(self, monkeypatch):
        """表在但无行 → 空图（nodes=[]），不误报「数据不可用」。"""
        cursor = CountingFakeCursor()  # 所有 SELECT 都返回空
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        g = db.get_full_word_graph("scope-empty")
        assert g is not None
        assert g["nodes"] == [] and g["links"] == []
        assert g["stats"]["node_count"] == 0


# ============================================
# R5-9 get_hot_verbs 缓存
# ============================================
class TestHotVerbsCache:
    def test_cache_hit_no_second_query(self, monkeypatch):
        cursor = CountingFakeCursor()
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        h1 = db.get_hot_verbs("scope-a", limit=5)
        h2 = db.get_hot_verbs("scope-a", limit=5)
        assert h1 == h2
        assert len(cursor.executed) == 1
        db.get_hot_verbs("scope-a", limit=10)  # limit 变 → 键变 → 重取
        assert len(cursor.executed) == 2


# ============================================
# R5-3 + R4-1 数据层：count_feedbacks / None vs []
# ============================================
class TestDataLayerNoneVsEmpty:
    def test_count_feedbacks_ok(self, monkeypatch):
        cursor = CountingFakeCursor(rows=[{"n": 7}])
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.count_feedbacks() == 7

    def test_count_feedbacks_failure_returns_none(self, monkeypatch):
        cursor = CountingFakeCursor(error_on=("FROM feedbacks",))
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.count_feedbacks() is None

    def test_get_oald_senses_failure_returns_none(self, monkeypatch):
        cursor = CountingFakeCursor(error_on=("FROM oald_senses s",))
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.get_oald_senses("run") is None

    def test_get_oald_senses_empty_is_empty_list(self, monkeypatch):
        cursor = CountingFakeCursor()  # 无行 = 词未收录/无义项
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.get_oald_senses("run") == []

    def test_get_senses_failure_returns_none(self, monkeypatch):
        cursor = CountingFakeCursor(error_on=("FROM word_senses s",))
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.get_senses("run") is None

    def test_get_annotation_progress_failure_returns_none(self, monkeypatch):
        cursor = CountingFakeCursor(error_on=("FROM oald_senses s",))
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.get_annotation_progress() is None

    def test_get_cluster_graph_failure_returns_none(self, monkeypatch):
        cursor = CountingFakeCursor(error_on=("FROM definitions",))
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        assert db.get_cluster_graph("run") is None

    def test_get_cluster_graph_unclustered_returns_empty(self, monkeypatch):
        """词不在库/未入簇 → 空 graph（非 None），页面走「未灌入」指引。"""
        cursor = CountingFakeCursor()  # cluster_id 查询无行
        monkeypatch.setattr(db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        g = db.get_cluster_graph("run")
        assert g is not None
        assert g["nodes"] == []


# ============================================
# R5-10 reliability_runs 幂等索引迁移
# ============================================
class TestReliabilityCategoryIndexMigration:
    def _patch(self, monkeypatch, cursor):
        # 注意：reliability 是 from-import 绑定（rel.get_db_cursor），
        # 必须 patch rel 命名空间，patch db 不生效（仿 test_reliability）。
        monkeypatch.setattr(rel, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        return cursor

    def test_creates_index_when_missing(self, monkeypatch):
        """探针无此索引 → CREATE INDEX 执行一次。"""
        created = []

        class Cur:
            def execute(self, sql, params=None):
                if "INFORMATION_SCHEMA.STATISTICS" in sql:
                    self._row = {"n": 0}
                elif "CREATE INDEX" in sql:
                    created.append(sql)
                    self._row = None
                else:
                    self._row = None

            def fetchone(self):
                return self._row

        self._patch(monkeypatch, Cur())
        assert rel._ensure_reliability_table() is True
        assert len(created) == 1
        assert "idx_reliability_runs_category" in created[0]
        assert "reliability_runs (category, task_type)" in created[0]

    def test_skips_index_when_present(self, monkeypatch):
        """探针已有此索引 → 不再 CREATE INDEX（幂等，重复调用不炸不重建）。"""
        created = []

        class Cur:
            def execute(self, sql, params=None):
                if "INFORMATION_SCHEMA.STATISTICS" in sql:
                    self._row = {"n": 2}  # 两列各一行 → 索引已存在
                elif "CREATE INDEX" in sql:
                    created.append(sql)
                    self._row = None
                else:
                    self._row = None

            def fetchone(self):
                return self._row

        self._patch(monkeypatch, Cur())
        assert rel._ensure_reliability_table() is True
        assert created == []

    def test_probe_failure_does_not_raise(self, monkeypatch):
        """假游标拿不到探针结果（row=None）→ 按无需迁移处理，不炸建表流程。"""

        class Cur:
            def execute(self, sql, params=None):
                self._row = None

            def fetchone(self):
                return self._row

        self._patch(monkeypatch, Cur())
        assert rel._ensure_reliability_table() is True


# ============================================
# R4-2 侧边栏离线统计 "—"（AppTest，断库模拟，不连库）
# ============================================
class TestSidebarOfflineStats:
    def test_offline_metrics_show_dash(self, monkeypatch):
        """DB_AVAILABLE=False 时六个统计 metric 显示 "—" 而非 0。"""
        monkeypatch.setattr(db, "init_database", lambda *a, **k: False)
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        assert not at.exception
        metrics = {m.label: m.value for m in at.sidebar.metric}
        for label in ("总查询次数", "已收录词条", "词义簇", "词间关系",
                      "平均评分", "总反馈数"):
            assert label in metrics, f"离线侧边栏缺 metric {label}"
            assert metrics[label] == "—", \
                f"离线时 {label} 应显示 — 而非 {metrics[label]!r}"


# ============================================
# R4-4 登出提示语分流（bare 模式单测，探针假游标 + st 记录代理）
# ============================================
class _RecordingSt:
    """st 代理：记录 warning 文本，其余属性透传真 streamlit（session_state 等）。"""

    def __init__(self, real):
        self._real = real
        self.warnings = []

    @property
    def session_state(self):
        return self._real.session_state

    def warning(self, *args, **kwargs):
        self.warnings.append(str(args[0]) if args else "")

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestLogoutMessageAttribution:
    @pytest.fixture(autouse=True)
    def _session_setup(self, monkeypatch):
        """注入 DB-backed 登录会话（_refresh_session_user 的判定前提）。"""
        import streamlit as _real_st

        self._st = _real_st
        _real_st.session_state["user"] = {"id": 42, "username": "fx3_user",
                                          "display_name": "测试",
                                          "role": "annotator", "roles": []}
        _real_st.session_state[app_module._USER_DB_BACKED_KEY] = True
        monkeypatch.setattr(app_module, "DB_AVAILABLE", True)
        monkeypatch.setattr(app_module, "get_user_role", lambda uid: None)
        self._recorder = _RecordingSt(_real_st)
        monkeypatch.setattr(app_module, "st", self._recorder)
        yield
        for key in ("user", app_module._USER_DB_BACKED_KEY,
                    app_module._LOGOUT_FLASH_KEY):
            _real_st.session_state.pop(key, None)

    def test_db_down_message(self, monkeypatch):
        """探针不可达（断库）→ 提示「暂无法核实（服务暂不可用）」，不说「停用」。"""
        cursor = CountingFakeCursor(error_on=("FROM users",))
        monkeypatch.setattr(app_module, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        result = app_module._refresh_session_user()
        assert result is None  # fail-closed 登出不变
        assert not self._st.session_state.get("user")
        assert any("账号状态暂无法核实" in t for t in self._recorder.warnings), \
            f"断库登出应有「暂无法核实」提示: {self._recorder.warnings}"
        assert not any("账号已被停用或删除" in t for t in self._recorder.warnings)

    def test_deactivated_message(self, monkeypatch):
        """探针可达（users 表读得到，只是查无此人/已停用）→ 保留原「停用或删除」。"""
        cursor = CountingFakeCursor(rows=[{"1": 1}])
        monkeypatch.setattr(app_module, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))
        result = app_module._refresh_session_user()
        assert result is None
        assert any("账号已被停用或删除" in t for t in self._recorder.warnings), \
            f"探针可达时应保留原提示: {self._recorder.warnings}"
        assert not any("暂无法核实" in t for t in self._recorder.warnings)


# ============================================
# R4-6 MOCK 兜底来源徽章
# ============================================
class TestMockSourceBadge:
    @pytest.fixture(autouse=True)
    def _clear_display_cache(self):
        import streamlit as _real_st

        _real_st.session_state.pop("_display_def_cache", None)
        yield
        _real_st.session_state.pop("_display_def_cache", None)

    def _mock_mode(self, monkeypatch):
        monkeypatch.setattr(app_module, "get_definition_by_verb",
                            lambda verb: None, raising=False)
        monkeypatch.setattr(app_module, "get_definition",
                            lambda verb, *a, **k: None, raising=False)

    def test_mock_branch_carries_source_marker(self, monkeypatch):
        self._mock_mode(monkeypatch)
        verb = next(iter(app_module.MOCK_DEFINITIONS))
        display = app_module.get_display_definition(verb)
        assert display.get("source") == "内置示例"

    def test_badge_rendered_on_core_card(self, monkeypatch):
        self._mock_mode(monkeypatch)
        verb = next(iter(app_module.MOCK_DEFINITIONS))
        html = app_module.render_card_core(verb)
        assert "内置示例（非词典数据）" in html

    def test_no_badge_for_db_data(self, monkeypatch):
        monkeypatch.setattr(
            app_module, "get_definition_by_verb",
            lambda verb: {"chinese_ndef": "库内释义", "semantic_table": {}},
            raising=False)
        html = app_module.render_card_core("跑")
        assert "内置示例（非词典数据）" not in html


# ============================================
# R4-7 cluster_analysis plotly 降级
# ============================================
class TestPlotlyDegradation:
    def test_has_plotly_flag_exists(self):
        assert isinstance(ca.HAS_PLOTLY, bool)

    def test_dendrogram_warns_and_returns_without_plotly(self, monkeypatch):
        """缺 plotly：_render_dendrogram 入口 warning＋return，不抛 ImportError。"""
        monkeypatch.setattr(ca, "HAS_PLOTLY", False)
        dendro = {"linkage": [[0, 1, 0.5, 2]], "labels": ["a", "b"],
                  "distance_matrix": [[0, 1], [1, 0]]}
        # bare 模式下 st.warning 可调；不抛异常即通过
        ca._render_dendrogram(dendro)

    def test_sense_graph_tab_warns_without_plotly(self, monkeypatch):
        monkeypatch.setattr(ca, "HAS_PLOTLY", False)
        ca._render_sense_graph_tab({"linkage": [[0, 1, 0.5, 2]]})


# ============================================
# R4-1/R4-5 cluster_analysis 页面三口径（AppTest 打桩，不连库）
# ============================================
_SENSE_ROW = {"sense_id": 1, "verb": "aa", "sense_no": "1",
              "sense_label": "L1", "gower_to_medoid": 0.0,
              "tier": ca.TIER_PROTOTYPE}


def _patch_semantic_page(monkeypatch, page_data, ready=True, categories=None,
                         reachable=True):
    """打桩语义分析页全部 DB 触点（装载器/ready/categories/探针/幂等迁移）。"""
    monkeypatch.setattr(ca, "_load_page_data", lambda _s, c, lang: page_data)
    monkeypatch.setattr(ca, "category_study_ready", lambda: ready)
    monkeypatch.setattr(ca, "get_categories", lambda: categories or [])
    monkeypatch.setattr(ca, "_categories_table_reachable", lambda: reachable)
    monkeypatch.setattr(ca, "ensure_sense_split_columns", lambda: None)
    monkeypatch.setattr(ca, "ensure_cluster_locked_column", lambda: None)


class TestSemanticPageThreeWay:
    def test_load_error_shows_unavailable_not_unseeded(self, monkeypatch):
        """R4-1：探针失败 → warning「数据不可用」+「勿重跑灌库」，不误导「未灌入」。"""
        data = {"ranking": [], "dendro": {"load_error": "连接失败"},
                "scipy_missing": False, "load_error": "连接失败"}
        _patch_semantic_page(monkeypatch, data, ready=False, reachable=False)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("数据不可用" in w and "勿重跑灌库" in w for w in warnings)
        assert not any("暂无聚类运行数据" in w for w in warnings)

    def test_unseeded_shows_load_hint(self, monkeypatch):
        """R4-1/R4-5：数据层可达 + 无运行 → info 灌库指引（含既有哨兵文案）。"""
        data = {"ranking": [], "dendro": {}, "scipy_missing": False,
                "load_error": None}
        _patch_semantic_page(monkeypatch, data, ready=False, reachable=True)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        infos = [str(i.value) for i in at.info]
        assert any("暂无聚类运行数据" in t for t in infos), \
            f"未灌入分支应保留灌库指引: {infos}"
        assert any("范畴深挖数据尚未灌入" in t for t in infos), \
            "categories 真空（探针可达）应保留原 info 哨兵"
        assert not any("数据不可用" in w for w in
                       [str(w.value) for w in at.warning])

    def test_categories_join_failure_attribution(self, monkeypatch):
        """R4-5：ready=True 但 categories=[] + 探针失败 → 「数据不可用」。"""
        data = {"ranking": [], "dendro": {}, "scipy_missing": False,
                "load_error": None}
        _patch_semantic_page(monkeypatch, data, ready=True, reachable=False)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("categories 读取失败" in w and "勿重跑灌库" in w
                   for w in warnings), f"JOIN 失败应归因: {warnings}"

    def test_categories_vacuum_keeps_original_warning(self, monkeypatch):
        """R4-5：ready=True 但 categories=[] + 探针可达 → 保留原「categories 为空」。"""
        data = {"ranking": [], "dendro": {}, "scipy_missing": False,
                "load_error": None}
        _patch_semantic_page(monkeypatch, data, ready=True,
                             categories=[], reachable=True)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("categories 为空" in w for w in warnings), \
            f"真真空应保留原提示: {warnings}"
        assert not any("数据不可用" in w for w in warnings)

    def test_ready_false_probe_failure_attribution(self, monkeypatch):
        """R4-5：ready=False + 探针失败 → warning「categories 表读取失败」，
        不给「尚未灌入」误导。"""
        data = {"ranking": [_cluster_stub()], "dendro": {},
                "scipy_missing": False, "load_error": None}
        _patch_semantic_page(monkeypatch, data, ready=False, reachable=False)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("categories 表读取失败" in w and "勿重跑灌库" in w
                   for w in warnings), f"探针失败应归因: {warnings}"
        assert not any("范畴深挖数据尚未灌入" in w for w in warnings)

    def test_data_ok_no_warnings(self, monkeypatch):
        """有数（ranking + 英汉对比侧就绪）→ 无「数据不可用」/「未灌入」提示。"""
        data = {"ranking": [_cluster_stub()], "dendro": {},
                "scipy_missing": False, "load_error": None}
        cat = {"code": "RUN", "name_cn": "跑范畴", "name_en": "RUN",
               "status": "done", "en_lexemes": 1, "en_senses": 1,
               "zh_lexemes": 1, "zh_senses": 1, "id": 1, "notes": ""}
        _patch_semantic_page(monkeypatch, data, ready=True,
                             categories=[cat], reachable=True)
        monkeypatch.setattr(ca, "_load_category", lambda _s, code: {"senses": []})
        monkeypatch.setattr(ca, "render_cluster_compare_view", lambda d: None)
        monkeypatch.setattr(ca, "render_matrix_view", lambda d: None)
        monkeypatch.setattr(ca, "render_alignment_view", lambda d: None)
        monkeypatch.setattr(ca, "render_schema_view", lambda d: None)
        monkeypatch.setattr(ca, "render_overview_view", lambda d: None)
        at = AppTest.from_string(_CA_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert not any("数据不可用" in w for w in warnings), warnings


def _cluster_stub():
    """最小可用簇（medoid/成员字段与真实现同构，仅够渲染不炸）。"""
    return {"cluster_id": 1, "cluster_no": 1, "cluster_name": "合成簇（2 成员）",
            "size": 1, "medoid": dict(_SENSE_ROW), "members": [dict(_SENSE_ROW)]}


# ============================================
# R4-1 app.py 图谱页三口径（AppTest 打桩）
# ============================================
class TestGraphPageThreeWay:
    def test_unavailable_branch(self, monkeypatch):
        """None（查询失败）→ warning「数据不可用」+ 勿重跑灌库；不给灌库指引。"""
        monkeypatch.setattr(app_module, "DB_AVAILABLE", True, raising=False)
        monkeypatch.setattr(app_module, "get_full_word_graph",
                            lambda scope=None: None, raising=False)
        at = AppTest.from_string(_GRAPH_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        warnings = [str(w.value) for w in at.warning]
        assert any("数据不可用" in w and "勿重跑灌库" in w for w in warnings)
        assert not any("暂无词间关系数据" in w for w in warnings)

    def test_unseeded_branch(self, monkeypatch):
        """空图（未灌入）→ info 灌库指引（哨兵文案不变，S3 矩阵依赖）。"""
        monkeypatch.setattr(app_module, "DB_AVAILABLE", True, raising=False)
        monkeypatch.setattr(
            app_module, "get_full_word_graph",
            lambda scope=None: {"nodes": [], "links": [], "clusters": [],
                                "stats": {"node_count": 0, "edge_count": 0,
                                          "cluster_count": 0}},
            raising=False)
        at = AppTest.from_string(_GRAPH_PAGE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert any("暂无词间关系数据" in str(i.value) for i in at.info)


# ============================================
# R5-1 init_database 会话守卫 + R5-3 侧边栏按需导出（AppTest，真库）
# ============================================
class TestAppSessionGuardAndLazyExport:
    @requires_db
    def test_init_database_runs_once_per_session(self, monkeypatch):
        """同一会话两次 rerun：init_database 的专用连接只建一次（R5-1）。"""
        real_connect = db.pymysql.connect
        counter = {"init": 0}

        def counting_connect(*args, **kwargs):
            if "database" not in kwargs:
                counter["init"] += 1
            return real_connect(*args, **kwargs)

        monkeypatch.setattr(db.pymysql, "connect", counting_connect)
        at = AppTest.from_file(APP, default_timeout=120)
        at.run()
        assert not at.exception
        first = counter["init"]
        assert first >= 1, "首轮应执行过 init_database"
        at.run()
        assert not at.exception
        assert counter["init"] == first, \
            "守卫生效：第二轮 rerun 不得再跑 init_database（每轮 +1 即守卫失效）"

    @requires_db
    def test_feedback_export_lazy_and_functional(self, monkeypatch):
        """默认只给按钮＋行数 caption（不取全表）；点击后才取数并出现下载（R5-3）。"""
        fetch_calls = {"n": 0}

        def counting_fetch():
            fetch_calls["n"] += 1
            return [
                {"verb": "run", "rating": 5,
                 "feedback_text": "很好", "created_at": "2026-11-08 10:00:00"},
                {"verb": "=cmd", "rating": 1,
                 "feedback_text": "+calc", "created_at": "2026-11-08 10:01:00"},
            ]

        monkeypatch.setattr(db, "count_feedbacks", lambda: 2)
        monkeypatch.setattr(db, "get_feedback_data", counting_fetch)
        at = AppTest.from_file(APP, default_timeout=120)
        at.run()
        assert not at.exception
        # 默认态：无 download_button、无全表取数、行数 caption 在场
        assert list(at.get("download_button")) == [], \
            "默认态不得渲染下载按钮（CSV 应按需生成）"
        assert fetch_calls["n"] == 0, "未点击时不得全表 SELECT * FROM feedbacks"
        assert any("当前反馈 2 条" in str(c.value) for c in at.sidebar.caption)
        export_btns = [b for b in at.sidebar.button
                       if "生成并导出反馈" in str(b.label)]
        assert export_btns, "默认应渲染「生成并导出反馈 (CSV)」按钮"

        # 点击 → rerun → 全表取数一次 + 下载按钮在场（导出功能保留）
        export_btns[0].click()
        at.run()
        assert not at.exception
        assert fetch_calls["n"] == 1, "点击生成后应恰好全表取数一次"
        dl = [d for d in at.get("download_button")
              if "下载反馈数据" in str(getattr(d, "label", ""))]
        assert dl, "点击生成后应出现「下载反馈数据 (CSV)」下载按钮"

    @requires_db
    def test_feedback_export_failure_caption(self, monkeypatch):
        """行数探针失败（None）→ caption 提示读取失败，不出导出按钮。"""
        monkeypatch.setattr(db, "count_feedbacks", lambda: None)
        at = AppTest.from_file(APP, default_timeout=120)
        at.run()
        assert not at.exception
        assert any("反馈行数读取失败" in str(c.value) for c in at.sidebar.caption)
        assert not [b for b in at.sidebar.button
                    if "生成并导出反馈" in str(b.label)]
