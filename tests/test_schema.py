"""
表结构与词簇图谱的契约测试。

这些测试**不连真实 MySQL**：`get_db_cursor` 被替换成一个假的游标，它按 SQL 文本
返回预置结果。这样做的好处是测试能跑在任何机器上（CI 无 MySQL 也能过），同时把
「SQL 问什么、代码怎么解释结果」这层契约钉死。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
import src.cluster_graph as cg  # noqa: E402


# ============================================
# 表结构契约
# ============================================
class TestSchemaDefinition:
    """DDL 本身的结构性断言 —— 防止关键约束被误删。"""

    def _all_ddl(self):
        return "\n".join(db.CREATE_TABLES_SQL)

    def test_schema_version_is_recorded(self):
        assert db.SCHEMA_VERSION >= 2
        assert "schema_migrations" in self._all_ddl()

    def test_cluster_table_exists(self):
        ddl = self._all_ddl()
        assert "CREATE TABLE IF NOT EXISTS word_clusters" in ddl
        # (main_cat, sub_cat) 必须唯一，否则同一簇会被建两次
        assert "uq_word_clusters_cats" in ddl

    def test_relations_table_is_undirected_with_unique_pair(self):
        ddl = self._all_ddl()
        assert "CREATE TABLE IF NOT EXISTS word_relations" in ddl
        assert "uq_word_relations_pair" in ddl
        # 无向边只存一份：a < b 的 CHECK 约束
        assert "chk_word_relations_order" in ddl
        assert "verb_a_id < verb_b_id" in ddl
        # 两个端点都必须是真的动词（外键），不是裸字符串
        assert "fk_word_relations_a" in ddl
        assert "fk_word_relations_b" in ddl

    def test_definitions_has_cluster_fk(self):
        ddl = self._all_ddl()
        assert "cluster_id" in ddl
        assert "fk_definitions_cluster" in ddl
        assert "idx_definitions_cluster" in ddl

    def test_dead_statistics_table_is_gone(self):
        """statistics 是 v1 的死表（无任何代码读写），迁移里应删除且不再重建。"""
        assert "CREATE TABLE IF NOT EXISTS statistics" not in self._all_ddl()

    def test_synonyms_table_is_gone(self):
        assert "CREATE TABLE IF NOT EXISTS synonyms" not in self._all_ddl()

    def test_view_provides_complete_graph(self):
        """视图用「同簇两两配对」推导完全图，与物化表互为校验。"""
        views = "\n".join(db.CREATE_VIEWS_SQL)
        assert "v_cluster_complete_graph" in views
        assert "b.id > a.id" in views


class TestMigrationIdempotency:
    """迁移必须是幂等的、重复执行安全的。"""

    def test_migration_drops_legacy_tables_and_adds_column(self):
        executed = []

        class FakeCursor:
            def __init__(self):
                self._last = None

            def execute(self, sql, params=None):
                executed.append(sql)
                self._last = sql

            def fetchone(self):
                sql = self._last or ""
                if "information_schema.COLUMNS" in sql:
                    # 模拟旧库：没有 cluster_id
                    return {"n": 0}
                if "information_schema.TABLES" in sql:
                    # 模拟旧库：synonyms / statistics 都在，schema_migrations 不在
                    return {"n": 0 if "schema_migrations" in sql else 1}
                if "FROM synonyms" in sql:
                    return {"n": 738}
                if "FROM statistics" in sql:
                    return {"n": 0}
                if "MAX(version)" in sql:
                    return {"v": None}
                return {"n": 1}

        summary = db._migrate_schema(FakeCursor())
        joined = "\n".join(executed)

        assert "ADD COLUMN cluster_id INT" in joined
        assert "DROP TABLE synonyms" in joined
        assert "DROP TABLE statistics" in joined
        assert summary["to"] == db.SCHEMA_VERSION
        assert any("synonyms dropped" in a for a in summary["actions"])
        assert any("statistics dropped" in a for a in summary["actions"])


# ============================================
# 词簇图谱查询
# ============================================
def _fake_cursor_factory(center_row, member_rows):
    """构造一个假游标：按 SQL 内容返回 definitions / 成员列表。"""

    class FakeCursor:
        def __init__(self):
            self._last = None
            self._rows = []

        def execute(self, sql, params=None):
            self._last = sql
            if "FROM definitions d" in sql and "LEFT JOIN word_clusters" in sql:
                self._rows = [center_row] if center_row else []
            elif "WHERE cluster_id = %s ORDER BY verb" in sql:
                self._rows = member_rows
            else:
                self._rows = []

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    return FakeCursor()


class _FakeCtx:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self.cur

    def __exit__(self, *a):
        return False


class TestClusterGraph:
    """get_cluster_graph 必须返回**完全图**。"""

    def _patch(self, monkeypatch, center_row, members):
        cur = _fake_cursor_factory(center_row, members)
        monkeypatch.setattr(db, "get_db_cursor", lambda: _FakeCtx(cur))

    def test_three_member_cluster_is_complete(self, monkeypatch):
        self._patch(
            monkeypatch,
            {"id": 1, "verb": "abandon", "cluster_id": 7,
             "cluster_label": "路径聚焦类 / 处所脱离", "sub_cat": "处所脱离",
             "cluster_size": 3},
            [{"id": 1, "verb": "abandon"},
             {"id": 2, "verb": "desert"},
             {"id": 3, "verb": "leave"}],
        )
        g = db.get_cluster_graph("abandon")

        assert len(g["nodes"]) == 3
        # C(3,2) = 3 条边，且任意两词都有边
        assert len(g["links"]) == 3
        assert g["complete_edge_count"] == 3
        pairs = {tuple(sorted((link["source"], link["target"]))) for link in g["links"]}
        assert pairs == {("abandon", "desert"), ("abandon", "leave"),
                         ("desert", "leave")}
        assert g["cluster"]["sub_cat"] == "处所脱离"

    def test_center_is_flagged(self, monkeypatch):
        self._patch(
            monkeypatch,
            {"id": 1, "verb": "abandon", "cluster_id": 7,
             "cluster_label": "x", "sub_cat": "处所脱离", "cluster_size": 2},
            [{"id": 1, "verb": "abandon"}, {"id": 2, "verb": "leave"}],
        )
        g = db.get_cluster_graph("abandon")
        flagged = [n["id"] for n in g["nodes"] if n["is_center"]]
        assert flagged == ["abandon"]

    def test_large_cluster_edge_count_matches_formula(self, monkeypatch):
        members = [{"id": i, "verb": f"v{i:02d}"} for i in range(56)]
        self._patch(
            monkeypatch,
            {"id": 0, "verb": "v00", "cluster_id": 4,
             "cluster_label": "方式聚焦类 / 常态行走", "sub_cat": "常态行走",
             "cluster_size": 56},
            members,
        )
        g = db.get_cluster_graph("v00")
        assert len(g["nodes"]) == 56
        # 用户明确要求完全图：56 词应产生 C(56,2)=1540 条边
        assert len(g["links"]) == 1540
        assert g["complete_edge_count"] == 1540
        assert g["truncated"] is False

    def test_unknown_verb_returns_empty(self, monkeypatch):
        self._patch(monkeypatch, None, [])
        g = db.get_cluster_graph("nonexistent")
        assert g["nodes"] == [] and g["links"] == []
        assert g["cluster"] is None

    def test_verb_without_cluster_returns_empty(self, monkeypatch):
        self._patch(
            monkeypatch,
            {"id": 9, "verb": "solo", "cluster_id": None,
             "cluster_label": None, "sub_cat": None, "cluster_size": None},
            [],
        )
        g = db.get_cluster_graph("solo")
        assert g["nodes"] == []


# ============================================
# SVG 渲染
# ============================================
class TestClusterGraphSvg:
    def _graph(self, members, center="abandon"):
        links = []
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                links.append({"source": a, "target": b, "relation": "近义"})
        return {
            "center": center,
            "cluster": {"label": "路径聚焦类 / 处所脱离", "sub_cat": "处所脱离",
                        "size": len(members)},
            "nodes": [{"id": m, "label": m, "is_center": m == center}
                      for m in members],
            "links": links,
            "truncated": False,
            "complete_edge_count": len(links),
        }

    def test_renders_one_circle_and_label_per_node(self):
        svg = cg.render_cluster_graph_svg(self._graph(["abandon", "desert", "leave"]))
        assert svg.count("<circle") == 3
        assert svg.count("<line") == 3
        for verb in ("abandon", "desert", "leave"):
            assert verb in svg

    def test_complete_graph_draws_all_edges_including_non_center(self):
        """完全图的关键：非中心词之间也要有边（desert–leave）。"""
        g = self._graph(["abandon", "desert", "leave"])
        svg = cg.render_cluster_graph_svg(g)
        # 3 个节点 3 条边 —— 若只画中心词连线就只会是 2 条
        assert svg.count("<line") == 3

    def test_highlight_only_center_drops_other_edges(self):
        g = self._graph(["abandon", "desert", "leave"])
        svg = cg.render_cluster_graph_svg(g, highlight_only_center=True)
        assert svg.count("<line") == 2

    def test_empty_graph_returns_message_not_crash(self):
        svg = cg.render_cluster_graph_svg(
            {"nodes": [], "links": [], "cluster": None, "center": "x"}
        )
        assert "<svg" not in svg
        assert "没有可展示的词簇图谱" in svg

    def test_large_cluster_only_labels_center(self):
        members = [f"v{i:02d}" for i in range(56)]
        svg = cg.render_cluster_graph_svg(self._graph(members, center="v00"))
        assert svg.count("<circle") == 56
        assert svg.count("<line") == 1540
        # 大簇只标中心词，其余靠 <title> hover
        assert svg.count("<text") == 1
        assert svg.count("<title") == 56

    def test_escapes_html_in_verb_names(self):
        g = self._graph(["<script>", "safe"], center="<script>")
        svg = cg.render_cluster_graph_svg(g)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_truncation_is_reported(self):
        members = [f"v{i:03d}" for i in range(120)]
        g = self._graph(members, center="v000")
        svg = cg.render_cluster_graph_svg(g, max_draw_nodes=20)
        assert "节点数超过绘制上限" in svg


class TestSidebarStatsContract:
    """页面空统计的键必须与 mysql_db.get_stats 一致，否则侧边栏会 KeyError。"""

    def test_get_stats_empty_branch_has_cluster_keys(self, monkeypatch):
        class BoomCtx:
            def __enter__(self):
                raise RuntimeError("no db")

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(db, "get_db_cursor", lambda: BoomCtx())
        s = db.get_stats()
        assert "total_clusters" in s
        assert "total_relations" in s
        assert "total_synonyms" not in s
