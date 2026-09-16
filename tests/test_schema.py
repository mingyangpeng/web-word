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
def _fake_cursor_factory(fake):
    """
    构造假游标，按 SQL 特征分派。

    fake 是 {
        "verb_to_cluster": {verb: cluster_id},
        "clusters": {cluster_id: {id,label,sub_cat,main_cat,size}},
        "members": {cluster_id: [{"id":..,"verb":..}, ...]},
    }

    用 SQL 特征而非调用顺序来分派：一旦实现里的查询顺序变了（本轮就变过），
    顺序式 mock 会以「返回错数据」而不是「报错」的方式静默失效。
    """

    class FakeCursor:
        def __init__(self):
            self._rows = []

        def execute(self, sql, params=None):
            if "FROM definitions WHERE verb" in sql:
                cid = fake["verb_to_cluster"].get(params[0])
                self._rows = [{"cluster_id": cid}] if cid is not None else []
            elif "FROM word_clusters WHERE id" in sql:
                if "label, sub_cat, main_cat, size" in sql:
                    row = fake["clusters"].get(params[0])
                    self._rows = [row] if row else []
                else:
                    self._rows = []
            elif "FROM definitions" in sql and "WHERE cluster_id" in sql:
                self._rows = list(fake["members"].get(params[0], []))
            elif "FROM word_clusters" in sql and "ORDER BY size" in sql:
                self._rows = sorted(
                    (dict(c) for c in fake["clusters"].values()),
                    key=lambda c: (-c["size"], c["label"]),
                )[: (params[0] if params else 500)]
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


def _fixture(cluster_size=3):
    """一个三词簇的默认测试数据（abandon / desert / leave）。"""
    members = [
        {"id": 1, "verb": "abandon"},
        {"id": 2, "verb": "desert"},
        {"id": 3, "verb": "leave"},
    ][:cluster_size]
    return {
        "verb_to_cluster": {m["verb"]: 7 for m in members},
        "clusters": {
            7: {"id": 7, "label": "路径聚焦类 / 处所脱离", "sub_cat": "处所脱离",
                "main_cat": "路径聚焦类", "size": cluster_size},
        },
        "members": {7: members},
    }


class TestClusterGraph:
    """get_cluster_graph 必须返回**完全图**。"""

    def _patch(self, monkeypatch, fake):
        cur = _fake_cursor_factory(fake)
        monkeypatch.setattr(db, "get_db_cursor", lambda: _FakeCtx(cur))

    def test_three_member_cluster_is_complete(self, monkeypatch):
        self._patch(monkeypatch, _fixture())
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
        self._patch(monkeypatch, _fixture(cluster_size=2))
        g = db.get_cluster_graph("abandon")
        flagged = [n["id"] for n in g["nodes"] if n["is_center"]]
        assert flagged == ["abandon"]

    def test_large_cluster_edge_count_matches_formula(self, monkeypatch):
        members = [{"id": i, "verb": f"v{i:02d}"} for i in range(56)]
        fake = {
            "verb_to_cluster": {"v00": 4},
            "clusters": {4: {"id": 4, "label": "方式聚焦类 / 常态行走",
                             "sub_cat": "常态行走", "main_cat": "方式聚焦类",
                             "size": 56}},
            "members": {4: members},
        }
        self._patch(monkeypatch, fake)
        g = db.get_cluster_graph("v00")
        assert len(g["nodes"]) == 56
        # 用户明确要求完全图：56 词应产生 C(56,2)=1540 条边
        assert len(g["links"]) == 1540
        assert g["complete_edge_count"] == 1540
        assert g["truncated"] is False

    def test_unknown_verb_returns_empty(self, monkeypatch):
        self._patch(monkeypatch, _fixture())
        g = db.get_cluster_graph("nonexistent")
        assert g["nodes"] == [] and g["links"] == []
        assert g["cluster"] is None

    def test_verb_without_cluster_returns_empty(self, monkeypatch):
        fake = _fixture()
        fake["verb_to_cluster"]["solo"] = None
        self._patch(monkeypatch, fake)
        g = db.get_cluster_graph("solo")
        assert g["nodes"] == []


class TestClusterGraphById:
    """按簇 id 直接取图 —— 这是页面上「切换簇」依赖的能力。"""

    def _patch(self, monkeypatch, fake):
        cur = _fake_cursor_factory(fake)
        monkeypatch.setattr(db, "get_db_cursor", lambda: _FakeCtx(cur))

    def test_open_cluster_without_any_verb(self, monkeypatch):
        """不传 center 也要能打开一个簇，并自动高亮一个节点。"""
        self._patch(monkeypatch, _fixture())
        g = db.get_cluster_graph_by_id(7)

        assert g["cluster"]["id"] == 7
        assert len(g["nodes"]) == 3
        assert len(g["links"]) == 3
        flagged = [n["id"] for n in g["nodes"] if n["is_center"]]
        # 总得有一个高亮节点，否则用户不知道从哪儿看起
        assert len(flagged) == 1
        assert g["center"] == flagged[0]

    def test_center_outside_cluster_falls_back(self, monkeypatch):
        """点了别的簇、但 center 来自原查询词时应退化，而不是一个高亮都没有。"""
        self._patch(monkeypatch, _fixture())
        g = db.get_cluster_graph_by_id(7, center="not_in_this_cluster")
        flagged = [n["id"] for n in g["nodes"] if n["is_center"]]
        assert len(flagged) == 1
        assert g["center"] == flagged[0]

    def test_center_inside_cluster_is_kept(self, monkeypatch):
        self._patch(monkeypatch, _fixture())
        g = db.get_cluster_graph_by_id(7, center="desert")
        assert g["center"] == "desert"
        assert [n["id"] for n in g["nodes"] if n["is_center"]] == ["desert"]

    def test_missing_cluster_returns_empty(self, monkeypatch):
        self._patch(monkeypatch, _fixture())
        g = db.get_cluster_graph_by_id(999)
        assert g["nodes"] == [] and g["cluster"] is None


class TestListClusters:
    def test_lists_all_with_edge_counts(self, monkeypatch):
        fake = _fixture()
        fake["clusters"][8] = {"id": 8, "label": "方式聚焦类 / 奔跑行进",
                               "sub_cat": "奔跑行进", "main_cat": "方式聚焦类",
                               "size": 31}
        cur = _fake_cursor_factory(fake)
        monkeypatch.setattr(db, "get_db_cursor", lambda: _FakeCtx(cur))

        cs = db.list_clusters()
        assert [c["id"] for c in cs] == [8, 7]          # 按 size 降序
        assert cs[0]["edge_count"] == 31 * 30 // 2      # C(31,2) = 465
        assert cs[1]["edge_count"] == 3


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
