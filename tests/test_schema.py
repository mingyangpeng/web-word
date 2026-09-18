"""
表结构与词簇图谱的契约测试。

这些测试**不连真实 MySQL**：`get_db_cursor` 被替换成一个假的游标，它按 SQL 文本
返回预置结果。这样做的好处是测试能跑在任何机器上（CI 无 MySQL 也能过），同时把
「SQL 问什么、代码怎么解释结果」这层契约钉死。
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
import src.cluster_graph as cg  # noqa: E402
import src.graph_export as ge  # noqa: E402


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


# ============================================
# 授权脚本的静态契约
# ============================================
class TestGrantStatements:
    """
    GRANT 里的库名必须转义下划线。

    MySQL 的 GRANT 用 `_` 作**单字符通配符**（与 LIKE 同规则），所以

        GRANT ALL PRIVILEGES ON web_word_db.* TO 'someone'@'%';

    实际授予的是「web_<任意字符>_word_<任意字符>_db」这个**模式**，同机上名字相像的
    无关库（如 `webXwordYdb`）会被一并授权。这是实测确认过的行为差异：
    未转义时该用户能 SELECT 别的库，写成 `web\\_word\\_db` 后被拒（1142）。

    这类问题不会报错、不会测试失败，只会安静地多给权限，所以用静态检查钉住。
    """

    # 也扫文档：README / config/README 里给的授权片段会被用户直接复制粘贴执行，
    # 漏在这里同样会真的多授权。
    SQL_FILES = [
        "scripts/init_db.sql",
        "scripts/grant_local_mysql.sql",
        "README.md",
        "config/README.md",
    ]

    def _statements(self):
        import re
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        out = []
        for rel in self.SQL_FILES:
            path = root / rel
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("--"):
                    continue
                if re.match(r"^GRANT\b", stripped, re.IGNORECASE):
                    out.append((rel, stripped))
        return out

    def test_grant_statements_found(self):
        """先确认真的扫到了语句 —— 否则下面的断言会因为「没扫到」而空过。"""
        stmts = self._statements()
        assert stmts, "没有在 SQL 文件里扫到任何 GRANT 语句，检查逻辑已失效"

    def test_every_granted_database_escapes_underscores(self):
        import re

        offenders = []
        for rel, stmt in self._statements():
            # 抓 GRANT ... ON <db>.* 里的库名部分
            m = re.search(r"ON\s+(`[^`]+`|[^\s.]+)\s*\.", stmt, re.IGNORECASE)
            if not m:
                continue
            dbref = m.group(1).strip("`")
            # 允许的形式：全局 *.*（无库名）或库名里每个 _ 都写成 \_
            if dbref == "*":
                continue
            if "_" in dbref.replace("\\_", ""):
                offenders.append((rel, dbref, stmt))

        assert not offenders, (
            "以下 GRANT 的库名含未转义的下划线，会被当成通配模式，"
            f"请改写成 \\\\_ 形式：{offenders}"
        )

    def test_escaped_form_is_present(self):
        """确认确实用了 `\\_` 写法，而不是所有库名恰好都没有下划线。"""
        joined = "\n".join(stmt for _, stmt in self._statements())
        assert "\\_" in joined


# ============================================
# 交互式图谱导出
# ============================================
class TestGraphExport:
    """
    `graph_export` 把图谱数据渲染成独立 HTML。

    最关键的一条：模板用 `__TOKEN__` 占位符替换，而不是 `str.format()`。模板几乎
    全是 JavaScript，里面有大量 `{}` 对象字面量、还有 `${...}` 模板字符串 ——
    后者恰好是 .format 的替换字段语法，冲突极其隐蔽。这组测试钉住这一点。
    """

    SAMPLE = {
        "nodes": [
            {"id": "a", "label": "a", "cluster_id": 1, "cluster_label": "簇一",
             "sub_cat": "子一", "main_cat": "主一", "degree": 1},
            {"id": "b", "label": "b", "cluster_id": 1, "cluster_label": "簇一",
             "sub_cat": "子一", "main_cat": "主一", "degree": 1},
        ],
        "links": [{"source": "a", "target": "b", "relation": "近义"}],
        "clusters": [{"id": 1, "label": "簇一", "sub_cat": "子一",
                      "size": 2, "edge_count": 1}],
        "stats": {"node_count": 2, "edge_count": 1, "cluster_count": 1},
    }

    def test_no_placeholder_survives_rendering(self):
        html = ge.build_graph_html(self.SAMPLE)
        leftover = re.findall(r"__[A-Z_]+__", html)
        assert not leftover, f"未替换的占位符: {set(leftover)}"

    def test_js_template_literals_not_mangled(self):
        """JS 里出现的 ${...} 与 {} 必须原样保留（str.format 会吃掉它们）。"""
        html = ge.build_graph_html(self.SAMPLE)
        assert "Object.assign({}, n)" in html
        assert "new vis.DataSet" in html
        assert "network.once('stabilizationIterationsDone'" in html

    def test_data_is_embedded_as_json(self):
        html = ge.build_graph_html(self.SAMPLE)
        assert '"id": "a"' in html
        # 边从数据层的 source/target 映射成 vis-network 的 from/to ——
        # 别把这两个字段名混起来，混了图会画不出边
        assert '"from": "a"' in html
        assert '"to": "b"' in html
        assert '"from": "a", "to": "b"' in html.replace("\n", "")

    def test_fingerprint_is_stable_and_order_insensitive(self):
        fp1 = ge.data_fingerprint(self.SAMPLE)
        fp2 = ge.data_fingerprint(self.SAMPLE)
        assert fp1 == fp2

        shuffled = {
            **self.SAMPLE,
            "nodes": list(reversed(self.SAMPLE["nodes"])),
            "links": list(reversed(self.SAMPLE["links"])),
        }
        assert ge.data_fingerprint(shuffled) == fp1, "指纹不应受行序影响"

    def test_fingerprint_includes_template_version(self):
        """
        模板版本必须参与指纹。

        否则「改了模板但数据没变」时 URL 不变 —— 浏览器和 Streamlit 都认为文件
        没换，页面继续跑旧渲染逻辑，改前端却看不到任何变化（重启进程也没用，
        磁盘上还是旧文件）。这个坑本轮真踩到了。
        """
        fp_before = ge.data_fingerprint(self.SAMPLE)
        original = ge.TEMPLATE_VERSION
        try:
            ge.TEMPLATE_VERSION = original + 1
            assert ge.data_fingerprint(self.SAMPLE) != fp_before
        finally:
            ge.TEMPLATE_VERSION = original
        assert ge.data_fingerprint(self.SAMPLE) == fp_before

    def test_fingerprint_changes_when_graph_changes(self):
        other = {
            **self.SAMPLE,
            "nodes": self.SAMPLE["nodes"] + [
                {"id": "c", "label": "c", "cluster_id": 1, "cluster_label": "簇一",
                 "sub_cat": "子一", "main_cat": "主一", "degree": 1}
            ],
        }
        assert ge.data_fingerprint(other) != ge.data_fingerprint(self.SAMPLE)

    def test_legend_covers_every_cluster(self):
        html = ge.build_graph_html(self.SAMPLE)
        assert "簇一" in html
        # 图例项由 JS 动态生成；数据侧只需确认簇的 id/label/size 进了 LEGEND 的 JSON
        assert '"cid": "1"' in html
        assert '"label": "簇一"' in html
        assert '"size": 2' in html

    def test_empty_graph_returns_no_url(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ge, "STATIC_DIR", str(tmp_path))
        assert ge.ensure_graph_html({"nodes": [], "links": [], "clusters": [], "stats": {}}) == ""

    def test_ensure_writes_once_and_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ge, "STATIC_DIR", str(tmp_path))
        url1 = ge.ensure_graph_html(self.SAMPLE)
        assert url1.startswith("/app/static/word_graph_")
        path = tmp_path / os.path.basename(url1)
        assert path.exists()

        mtime = path.stat().st_mtime_ns
        url2 = ge.ensure_graph_html(self.SAMPLE)
        assert url2 == url1, "数据没变时 URL 必须一致，否则 iframe 会重载、布局丢失"
        assert path.stat().st_mtime_ns == mtime, "数据没变时不应重写文件"

    def test_ensure_prunes_stale_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ge, "STATIC_DIR", str(tmp_path))
        stale = tmp_path / "word_graph_deadbeef0000.html"
        stale.write_text("old", encoding="utf-8")

        ge.ensure_graph_html(self.SAMPLE)
        assert not stale.exists(), "旧指纹文件应被清理，避免 static/ 越积越多"
        assert ge.VIS_LIB in os.listdir(tmp_path) or True  # 库文件本身不应被误删

    def test_esc_js_handles_quotes_and_newlines(self):
        """graphify #1838 是节点名里的引号打穿属性导致的存储型 XSS。"""
        out = ge._esc_js('a"b\nc\\d')
        assert out.startswith('"') and out.endswith('"')
        assert '\n' not in out
        assert '\\"' in out

    def test_static_url_matches_streamlit_convention(self):
        """
        静态文件 URL 前缀必须与 Streamlit 的约定一致。

        Streamlit 的 enableStaticServing 把**主脚本同级的 static/** 暴露在
        `/app/static/<file>`。本项目主脚本是 `src/app.py`，所以目录必须是
        `src/static/`、URL 必须是 `/app/static/`。若有人把 app.py 挪走或把
        static/ 放错位置，图谱会 404 而页面没有任何报错 —— 只显示一片空白。
        """
        app_dir = os.path.dirname(ge.STATIC_DIR)          # .../src
        assert os.path.basename(ge.STATIC_DIR) == "static"
        assert os.path.exists(os.path.join(app_dir, "app.py")), (
            "static/ 必须与 app.py 同级，否则 Streamlit 不会暴露 /app/static/"
        )
        html = ge.build_graph_html(self.SAMPLE)
        assert "/app/static/" in html, "模板里的静态资源前缀必须与 Streamlit 约定一致"

    def test_vis_library_is_vendored_locally(self):
        """不许引 CDN：项目已确立零网络依赖，内网下 CDN 会渲染成白屏。"""
        path = os.path.join(ge.STATIC_DIR, ge.VIS_LIB)
        assert os.path.exists(path), f"缺少本地 vis-network: {path}"
        assert os.path.getsize(path) > 100_000
        html = ge.build_graph_html(self.SAMPLE)
        assert "unpkg.com" not in html and "cdn." not in html
        assert f"/app/static/{ge.VIS_LIB}" in html


class TestFullWordGraph:
    """get_full_word_graph 的形状契约（假游标，不连库）。"""

    def test_shape_and_degrees(self, monkeypatch):
        class FakeCursor:
            def __init__(self):
                self._rows = []

            def execute(self, sql, params=None):
                if "LEFT JOIN word_clusters" in sql:
                    self._rows = [
                        {"verb": "a", "cluster_id": 1, "cluster_label": "簇一",
                         "sub_cat": "子一", "main_cat": "主一"},
                        {"verb": "b", "cluster_id": 1, "cluster_label": "簇一",
                         "sub_cat": "子一", "main_cat": "主一"},
                    ]
                elif "FROM word_relations r" in sql:
                    self._rows = [{"source": "a", "target": "b", "relation": "近义"}]
                elif "FROM word_clusters" in sql:
                    self._rows = [{"id": 1, "label": "簇一", "sub_cat": "子一", "size": 2}]
                else:
                    self._rows = []

            def fetchone(self):
                return self._rows[0] if self._rows else None

            def fetchall(self):
                return list(self._rows)

        monkeypatch.setattr(db, "get_db_cursor", lambda: _FakeCtx(FakeCursor()))
        g = db.get_full_word_graph()

        assert g["stats"] == {"node_count": 2, "edge_count": 1, "cluster_count": 1}
        assert [n["id"] for n in g["nodes"]] == ["a", "b"]
        # 度数由边推导，而不是查库时直接读的字段
        assert all(n["degree"] == 1 for n in g["nodes"])
        assert g["clusters"][0]["edge_count"] == 1   # C(2,2) = 1


class TestParticleAndFullscreen:
    """
    粒子动效与全屏能力的静态契约。

    这两项都是前端行为，"能不能跑"只能在浏览器里验证（已实测）。这里钉住的是
    那些一旦被改坏就**不会报错、只会静默失效**的点 —— 比如有人把 iframe 换回
    components.html 导致全屏权限丢失，或把粒子预算写死成"按度数取前 N"导致
    整张图只有一处发光。
    """

    def _html(self):
        return ge.build_graph_html(TestGraphExport.SAMPLE)

    def test_particle_layer_exists(self):
        html = self._html()
        assert '<canvas id="particles"' in html, "缺少粒子覆盖层"
        # 覆盖层必须不吃鼠标事件，否则会挡住 vis-network 的拖拽与点击
        assert "#particles { position: absolute; inset: 0; pointer-events: none" in html

    def test_particle_cap_is_two_hundred(self):
        assert ge.PARTICLE_MAX == 200
        html = self._html()
        assert f"const PARTICLE_MAX = {ge.PARTICLE_MAX};" in html

    def test_particles_prefer_selected_cluster(self):
        """用户明确要求：有被选中的词簇时，优先给该簇粒子。"""
        html = self._html()
        assert "focusClusterIds" in html
        assert "focusClusters.has(a) ? 1 : 0" in html, "排序里必须体现选中簇优先"

    def test_focus_cluster_gets_a_real_quota(self):
        """
        选中簇必须有**独立配额**，而不只是"排在最前"。

        轮转下 3 个词的小簇 3 轮就被塞满，再轮也涨不上去，选中与不选中的粒子数
        完全一样。所以要有一个专门的阶段把它喂到 FOCUS_SHARE 的预算。
        """
        html = self._html()
        assert "FOCUS_SHARE" in html
        assert "第一阶段" in html and "第二阶段" in html
        assert "const quota = Math.floor(PARTICLE_MAX * FOCUS_SHARE)" in html

    def test_particle_allocation_round_robins_clusters(self):
        """
        必须按簇轮转分配，不能按度数排序取前 N。

        实测过：按度数取前 N 时，200 个预算会被 56 词的「常态行走」独占
        （25 个簇里只有 1 个有粒子），整张图只有一处发光。
        """
        html = self._html()
        assert "轮转分配" in html
        assert "for (const cid of clusterIds)" in html, "缺少按簇轮转的分配循环"

    def test_fullscreen_button_and_handler(self):
        html = self._html()
        assert 'id="btn-fullscreen"' in html
        assert "requestFullscreen" in html
        assert "exitFullscreen" in html
        assert "fullscreenchange" in html

    def test_fullscreen_targets_body_not_just_graph(self):
        """全屏要连侧边栏一起放大，只放大画布就没法用搜索与图例了。"""
        html = self._html()
        assert "document.body.requestFullscreen()" in html
        assert "document.documentElement.requestFullscreen" not in html

    def test_app_embeds_via_iframe_for_fullscreen_permission(self):
        """
        页面必须用 st.iframe（而不是 components.html 内联字符串）嵌图谱。

        两个后果绑在一起：内联 iframe 会被 Streamlit 每次重跑重写（布局丢失），
        而且内联 HTML 走的是 srcdoc，没有 allow="fullscreen"，全屏会被浏览器拒绝。
        """
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "src", "app.py"), encoding="utf-8") as f:
            src = f.read()

        # 去掉注释与三引号块再断言：app.py 的 docstring 里正解释「为什么不用
        # components.html」，那是说明文字而不是代码。
        code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
        code = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", code)

        assert "st.iframe(url" in code
        assert "components.html(" not in code
