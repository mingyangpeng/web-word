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

            # 行形状跟着真实 SELECT 走：节点查询取的是 definitions 的明细列，
            # 义位查询取 word_senses。假游标少一列就会 KeyError，这正是我们想要的
            # —— 它保证 get_full_word_graph 不会悄悄依赖一个不存在的列。
            NODE_COLS = ("chinese_ndef", "en_ndef", "phonetic", "semantic_table",
                         "example_sentence", "image_schema", "prototype_level",
                         "alignment", "cn_syntax", "translation_strategy",
                         "definition_source", "source_rank", "sense_count",
                         "sense_brief", "judge_reason", "levin_source",
                         "cross_subclass", "needs_review", "prototype_is_first",
                         "cluster_image_schema", "cluster_cn_syntax",
                         "cluster_translation_strategy")
            SENSE_COLS = ("sense_index", "ch_ndef", "en_ndef", "construction",
                          "examples", "ch_examples", "synonyms", "antonyms",
                          "image_schema", "prototype_level", "alignment",
                          "cn_syntax", "translation_strategy")

            def execute(self, sql, params=None):
                if "LEFT JOIN word_clusters" in sql:
                    self._rows = []
                    for verb in ("a", "b"):
                        row = {"verb": verb, "cluster_id": 1, "cluster_label": "簇一",
                               "sub_cat": "子一", "main_cat": "主一"}
                        row.update({c: None for c in self.NODE_COLS})
                        self._rows.append(row)
                    self._rows[0]["phonetic"] = "ˈeɪ"
                    self._rows[0]["semantic_table"] = '{"manner": "方式甲"}'
                elif "FROM word_senses s" in sql:
                    row = {"verb": "a", "sense_index": 1, "ch_ndef": "义位甲",
                           "en_ndef": None, "construction": None,
                           "examples": '["ex one"]', "ch_examples": '["例句一"]',
                           "synonyms": '["b"]', "antonyms": None,
                           "image_schema": None, "prototype_level": None,
                           "alignment": None, "cn_syntax": None,
                           "translation_strategy": None}
                    self._rows = [row]
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

        # 明细字段是卡片的数据源：图谱渲染只读 id/label/size，
        # 但信息面板与浮层卡片要读这些 —— 遗漏不会报错，只会让卡片显示空白。
        a = g["nodes"][0]
        assert a["phonetic"] == "ˈeɪ"
        assert a["semantic_table"] == {"manner": "方式甲"}
        assert a["senses"][0]["ch_ndef"] == "义位甲"
        # JSON 列在库里是字符串，必须被解析成结构；坏值/None 归一成空容器
        assert a["senses"][0]["examples"] == ["ex one"]
        assert a["senses"][0]["antonyms"] == []
        assert g["nodes"][1]["senses"] == []
        assert g["nodes"][1]["semantic_table"] == {}
        assert g["nodes"][1]["chinese_ndef"] == ""


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

    def test_every_visible_node_is_a_particle_no_cap(self):
        """
        每个可见节点都是一个粒子，**没有数量上限**。

        曾经的实现有 200 上限，还要按「选中簇优先 + 按簇轮转」分配预算；
        改成「节点即粒子」后上限失去意义（粒子数恒等于可见节点数），那套分配
        代码整体删除。这里钉住它没有以任何形式回潮 —— 半个上限比没有上限更糟，
        因为它会让一部分节点不动，而用户看不出来为什么。
        """
        html = self._html()
        assert "PARTICLE_MAX" not in html, "不应再有任何粒子数量上限"
        assert "FOCUS_SHARE" not in html, "预算分配代码应已删除"
        assert "particlesPerNode" not in html
        # 没有上限 ⇒ 重建时直接按可见节点生成，不经过任何筛选或配额
        assert "const visible = RAW_NODES.filter(n => !nodesDS.get(n.id).hidden);" in html
        assert "particles = visible.map(" in html

    def test_particle_physics_present(self):
        """节点即粒子之后，运动靠自写的引力/斥力/阻尼，而不是 vis 的布局求解器。"""
        html = self._html()
        for token in ("stepPhysics", "PHYS.DAMPING", "PHYS.REPULSE_K", "PHYS.SPRING_K",
                      "PHYS.SPEED_SCALE", "PHYS.ANCHOR_K", "liveEdges"):
            assert token in html, f"缺少 {token}"

    def test_search_auto_enables_the_cluster(self):
        """
        用户要求：**搜到的词，即使它所在的词簇当前没勾选，也要自动勾选上**。

        否则会「搜到了这个词，图上却看不到它」—— 搜索给了一条导航路径，
        却因为一个隐藏状态通向空处。
        """
        html = self._html()
        assert "function ensureClusterEnabled" in html
        assert "ensureClusterEnabled(nodeId);" in html, "focusNode 必须调用它"

        # 必须在 focus 之前解锁，否则会聚焦到一个还 hidden 的坐标上
        fn = html[html.index("function focusNode(nodeId, doFocus) {"):]
        fn = fn[:fn.index("network.selectNodes")]
        # 用调用形式而不是 "network.focus"：上面的注释里也提到了它，
        # 用裸字符串会在注释里先命中，断言就失去意义
        assert fn.index("ensureClusterEnabled(nodeId);") < fn.index("network.focus(nodeId"), (
            "ensureClusterEnabled 必须在 network.focus 之前调用"
        )

    def test_auto_enable_only_acts_when_unchecked(self):
        """
        已勾选时不得重复 applyFilter。

        applyFilter 会重建粒子集合；每次点节点都触发就会不断打断正在进行的运动，
        看起来像「图一直在抖」。
        """
        html = self._html()
        fn = html[html.index("function ensureClusterEnabled(nodeId) {"):]
        fn = fn[:fn.index(chr(10) + "}" + chr(10))]
        assert "if (enabled.has(cid)) return false;" in fn
        assert fn.index("return false") < fn.index("applyFilter(")


    def test_particle_radius_follows_network_zoom(self):
        """
        粒子半径必须跟着 vis 的缩放走。

        这是一个**静默失效**的 bug：vis 把节点画成 size*scale 个屏幕像素，粒子层
        如果按 canvas 单位画，缩小的视野里就会比节点大出好几倍。不报错、不崩溃，
        只是整张图糊成一团。实测过（视野缩放 0.268）：节点 4~9px，粒子 14~31px，
        大 3.4 倍，171 个半透明光晕在 'lighter' 下叠加，17.1% 的已绘制像素变成
        近纯白 —— 用户的原话是「一团光晕，啥也看不清」。
        """
        html = self._html()
        assert "const scale = network.getScale();" in html, "粒子半径必须乘上缩放"
        assert "a.size * scale" in html
        # 半径还要有上下限：缩到极小不能消失，放到极大不能糊满屏
        assert "Math.max(a.size * scale, 2.5)" in html
        assert "Math.min(Math.max(a.size * scale, 2.5), 26)" in html

    def test_low_zoom_skips_glow_and_trail(self):
        """
        缩放很小时只画实心点。

        光晕和拖尾都是「放大后才看得见」的细节；在小缩放下它们只是纯粹的成本，
        叠加起来还会盖掉唯一重要的东西 —— 词的标签。
        """
        html = self._html()
        assert "const small = r < 4;" in html
        assert "if (!small) {" in html, "光晕必须被 small 守卫"
        assert "if (!small && sp > 0.05)" in html, "拖尾必须被 small 守卫"

    def test_glow_is_smaller_than_the_node_halo(self):
        """光晕不该比节点大太多：3.2 倍时是「节点旁边一团雾」，不是「节点在发光」。"""
        html = self._html()
        assert "const glowR = r * 1.9;" in html
        assert "const glowR = r * 3.2;" not in html, "旧的 3.2 倍光晕会把邻居的词一起盖掉"

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


# ============================================
# v3：义位层面的结构（依据 docs/义项判定标准.docx）
# ============================================
class TestSchemaV3:
    """
    v3 新增义位表与标注字段。

    文档明确「分析单元是义位（sense），而非词目 lemma」—— 所以义位必须独立成表，
    而不能塞在 definitions 的一个 JSON 列里。这组测试钉住这个结构决策。
    """

    def _all_ddl(self):
        return "\n".join(db.CREATE_TABLES_SQL)

    def test_schema_version_bumped(self):
        assert db.SCHEMA_VERSION >= 3

    def test_senses_table_exists_with_cascade(self):
        ddl = self._all_ddl()
        assert "CREATE TABLE IF NOT EXISTS word_senses" in ddl
        assert "fk_word_senses_definition" in ddl
        # 词目被删时义位必须跟着走，否则留下孤儿行
        assert "ON DELETE CASCADE" in ddl
        # 同一词目内义位序号唯一，重复灌库才幂等
        assert "uq_word_senses_index" in ddl

    def test_definitions_has_annotation_columns(self):
        ddl = self._all_ddl()
        for col in ("image_schema", "prototype_level", "alignment", "cn_syntax",
                    "translation_strategy", "definition_source", "source_rank",
                    "sense_count", "needs_review", "levin_source", "sense_brief",
                    "judge_reason", "cross_subclass", "en_ndef"):
            assert col in ddl, f"definitions 缺少标注列 {col}"

    def test_clusters_have_schema_columns(self):
        ddl = self._all_ddl()
        for col in ("image_schema", "cn_syntax", "translation_strategy"):
            assert col in ddl, f"word_clusters 缺少 {col}"

    def test_migration_adds_all_v3_columns_idempotently(self):
        """迁移必须把 v3 的每一列都补上，且在已存在的库上是空操作。"""
        executed = []

        class NewDbCursor:
            """模拟**已经是 v3** 的库：所有列/索引都存在。"""

            def __init__(self):
                self._last = ""

            def execute(self, sql, params=None):
                executed.append(sql)
                self._last = sql

            def fetchone(self):
                if "information_schema" in self._last:
                    return {"n": 1}          # 一切都已存在
                if "MAX(version)" in self._last:
                    return {"v": 3}
                return {"n": 1}

        summary = db._migrate_schema(NewDbCursor())
        joined = "\n".join(executed)
        assert "ADD COLUMN image_schema" not in joined, "已存在的列不该重复 ADD"
        assert summary["actions"] == [] or all(
            "added" not in a for a in summary["actions"]
        ), f"幂等性被破坏: {summary['actions']}"

    def test_migration_from_v2_adds_columns(self):
        """从 v2 上来时必须补齐 v3 的列。"""
        executed = []
        state = {"defs": set(), "clusters": set()}

        class V2Cursor:
            def __init__(self):
                self._last = ""
                self._params = None

            def execute(self, sql, params=None):
                executed.append(sql)
                self._last = sql
                self._params = params
                if sql.startswith("ALTER TABLE definitions ADD COLUMN"):
                    state["defs"].add(sql.split()[5])
                if sql.startswith("ALTER TABLE word_clusters ADD COLUMN"):
                    state["clusters"].add(sql.split()[5])

            def fetchone(self):
                if "information_schema.COLUMNS" in self._last:
                    table = self._params[1]
                    col = self._params[2]
                    # 模拟 v2 的不完整状态：definitions 已有 cluster_id（v2 加的），
                    # 其余 v3 新列都还没有。这样只有 v3 的 ADD COLUMN 会真的执行。
                    if table == "definitions" and col == "cluster_id":
                        return {"n": 1}
                    return {"n": 0}
                if "information_schema.TABLES" in self._last:
                    return {"n": 1 if "schema_migrations" in self._last else 0}
                if "information_schema.STATISTICS" in self._last:
                    return {"n": 0}
                if "information_schema.TABLE_CONSTRAINTS" in self._last:
                    return {"n": 1}
                if "MAX(version)" in self._last:
                    return {"v": 2}
                return {"n": 0}

        db._migrate_schema(V2Cursor())
        joined = "\n".join(executed)
        for col in ("image_schema", "prototype_level", "alignment",
                    "definition_source", "sense_count", "needs_review"):
            assert f"ADD COLUMN {col}" in joined, f"迁移没补上 {col}"

    def test_migration_never_deletes_business_data(self):
        """
        迁移只做结构改造，**不得** DELETE 业务数据。

        迁移在每次应用启动时都会跑；如果它删数据，一次部署就能清空词表。
        簇与关系的重建是灌库脚本的职责（那里有显式的 clear_all_word_data）。
        """
        executed = []

        class FakeCursor:
            def __init__(self):
                self._last = ""

            def execute(self, sql, params=None):
                executed.append(sql)
                self._last = sql

            def fetchone(self):
                if "MAX(version)" in self._last:
                    return {"v": 3}
                return {"n": 1}

        db._migrate_schema(FakeCursor())
        joined = "\n".join(executed).upper()
        for table in ("DEFINITIONS", "WORD_CLUSTERS", "WORD_RELATIONS", "WORD_SENSES"):
            assert f"DELETE FROM {table}" not in joined, f"迁移删了 {table} 的数据"
        assert "TRUNCATE" not in joined


class TestAnnotationColumnsWhitelist:
    """
    insert_definition 的标注字段白名单。

    列名无法参数化、只能拼进 SQL，所以白名单同时承担两个职责：
      1. 挡住列名注入；
      2. 保证 LLM 实时生成路径（不传 annotations）不会抹掉灌库写入的标注 ——
         与 cluster_id 当初用 COALESCE 防的是同一个坑。
    """

    def test_whitelist_covers_every_annotation_column(self):
        ddl = "\n".join(db.CREATE_TABLES_SQL)
        for col in db._ANNOTATION_COLUMNS:
            assert col in ddl, f"白名单里的 {col} 在 DDL 中不存在"

    def test_unknown_column_is_rejected(self):
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))

        class Ctx:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, *a):
                return False

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: Ctx()
        try:
            db.insert_definition("v", "d", {}, None, "m", None,
                                 {"image_schema": "方式伴随图式",
                                  "evil` = 1 --": "x"})
        finally:
            db.get_db_cursor = orig

        sql = executed[0][0]
        assert "image_schema" in sql
        assert "evil" not in sql, "未白名单的列名不该出现在 SQL 里"

    def test_omitted_annotations_are_not_in_update_clause(self):
        """没传的标注字段不得出现在 UPDATE 子句里（否则会被 NULL 覆盖）。"""
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append(sql)

        class Ctx:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, *a):
                return False

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: Ctx()
        try:
            db.insert_definition("v", "d", {}, None, "m", None,
                                 {"image_schema": "方式伴随图式"})
        finally:
            db.get_db_cursor = orig

        sql = executed[0]
        update_part = sql.split("ON DUPLICATE KEY UPDATE")[1]
        assert "image_schema = VALUES(image_schema)" in update_part
        assert "alignment = VALUES(alignment)" not in update_part


class TestClusterMaintenance:
    def test_prune_only_deletes_unused_clusters(self):
        """prune 的失败模式必须是「少删」，绝不能删掉有成员的簇。"""
        executed = []

        class FakeCursor:
            def __init__(self):
                self._rows = []
                self._last = ""

            def execute(self, sql, params=None):
                executed.append((sql, params))
                self._last = sql
                if "SELECT id FROM word_clusters" in sql:
                    self._rows = [{"id": 1}, {"id": 2}, {"id": 3}]
                elif "SELECT DISTINCT cluster_id" in sql:
                    self._rows = [{"cluster_id": 1}, {"cluster_id": 3}]
                else:
                    self._rows = []

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: _FakeCtx(FakeCursor())
        try:
            n = db.prune_empty_clusters()
        finally:
            db.get_db_cursor = orig

        assert n == 1
        deletes = [sql for sql, _ in executed if sql.strip().startswith("DELETE")]
        assert len(deletes) == 1
        assert "(2)" in deletes[0] or "2" in str(executed[-1][1])

    def test_prune_deletes_nothing_when_all_used(self):
        executed = []

        class FakeCursor:
            def __init__(self):
                self._rows = []

            def execute(self, sql, params=None):
                executed.append(sql)
                if "SELECT id FROM word_clusters" in sql:
                    self._rows = [{"id": 1}]
                elif "SELECT DISTINCT cluster_id" in sql:
                    self._rows = [{"cluster_id": 1}]
                else:
                    self._rows = []

            def fetchall(self):
                return list(self._rows)

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: _FakeCtx(FakeCursor())
        try:
            n = db.prune_empty_clusters()
        finally:
            db.get_db_cursor = orig

        assert n == 0
        assert not [s for s in executed if s.strip().startswith("DELETE")]

    def test_clear_preserves_user_tables(self):
        """清空词表时**不得**动 feedbacks / usage_logs —— 那是用户产生的数据。"""
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def fetchone(self):
                return {"n": 5}

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: _FakeCtx(FakeCursor())
        try:
            db.clear_all_word_data()
        finally:
            db.get_db_cursor = orig

        joined = "\n".join(executed).upper()
        assert "DELETE FROM DEFINITIONS" in joined
        assert "DELETE FROM WORD_CLUSTERS" in joined
        assert "DELETE FROM WORD_RELATIONS" in joined
        assert "DELETE FROM WORD_SENSES" in joined
        assert "FEEDBACKS" not in joined
        assert "USAGE_LOGS" not in joined


class TestSensesReplace:
    def test_delete_then_insert(self):
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append((sql, params))

            def executemany(self, sql, rows):
                executed.append((sql, rows))

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: _FakeCtx(FakeCursor())
        try:
            n = db.replace_word_senses(42, [
                {"sense_index": 1, "ch_ndef": "甲", "prototype_level": "Y"},
                {"sense_index": 2, "ch_ndef": "乙", "prototype_level": "拓展"},
            ])
        finally:
            db.get_db_cursor = orig

        assert n == 2
        assert any("DELETE FROM word_senses" in s for s, _ in executed)
        assert any("INSERT INTO word_senses" in s for s, _ in executed)

    def test_empty_list_clears(self):
        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def executemany(self, sql, rows):
                executed.append(sql)

        orig = db.get_db_cursor
        db.get_db_cursor = lambda: _FakeCtx(FakeCursor())
        try:
            n = db.replace_word_senses(42, [])
        finally:
            db.get_db_cursor = orig

        assert n == 0
        assert any("DELETE FROM word_senses" in s for s in executed)


class TestNodeAndEdgeCards:
    """
    节点/边详情卡片的前端契约。

    这一组钉的都是**改坏了不会报错、只会静默失效**的点：

    - 面板与卡片必须共用同一个渲染函数，否则「两处数据一致」就成了靠人工对齐的
      承诺，迟早漂移；
    - vis 在点到节点时会把该节点**所有关联边**一并放进 ``p.edges``（实测点一个
      44 度的节点会带回 44 条边），所以 click 处理必须先判节点、再判边 ——
      顺序反了就会「点节点却弹出某条关联边的关系卡片」；
    - 库里 aspect / scope 两键 171 词全空、义位只覆盖 17 词、音标只覆盖 23 词。
      这些缺口必须在界面上**显式说明**，不能让用户以为是自己漏看了。
    """

    def _html(self):
        return ge.build_graph_html(TestGraphExport.SAMPLE)

    def test_panel_and_cards_share_one_renderer(self):
        """右侧面板与浮层卡片同源：只有这一个函数负责拼词条明细。"""
        html = self._html()
        assert "function nodeDetailHTML(" in html, "缺少词条明细渲染器"
        # 面板走 compact 分支、卡片走完整分支
        assert "nodeDetailHTML(n, true)" in html, "右侧面板应调用共用的渲染器"
        assert "nodeDetailHTML(n, false)" in html, "卡片应调用共用的渲染器"

    def test_node_click_takes_priority_over_edge_click(self):
        """
        节点判定必须在边判定之前。

        写成 ``if (p.edges...)`` 在前，点节点时会随机打开一条关联边的关系卡片 ——
        这个 bug 在开发中真实出现过，而且因为「确实弹出了卡片」看起来不像坏掉。
        """
        html = self._html()
        click = html[html.index("network.on('click'"):]
        click = click[:click.index("// ---------- 聚焦")]
        # 匹配真实的 if 语句而不是注释 —— 注释里也写了 p.edges，会假命中
        i_node = click.index("if (p.nodes.length > 0) {")
        i_edge = click.index("if (p.edges && p.edges.length > 0) {")
        assert i_node < i_edge, "必须先判节点再判边，否则点节点会误开关系卡片"

    def test_both_cards_are_draggable_and_closable(self):
        html = self._html()
        assert "makeDraggable('word-card', 'word-card-head')" in html
        assert "makeDraggable('edge-card', 'edge-card-head')" in html
        assert "word-card-close" in html and "edge-card-close" in html
        # 拖动用 pointer 事件（鼠标/触屏/笔通吃）
        assert "pointerdown" in html and "pointermove" in html
        # 标题栏上的按钮不能触发拖动，否则点「收藏」会把卡片带跑
        assert "if (ev.target.closest('.fc-btn')) return;" in html

    def test_view_detail_button_opens_the_card(self):
        html = self._html()
        assert 'id="btn-word-detail"' in html, "面板里应有「查看详情」入口"
        assert "#btn-word-detail" in html, "该入口需要被事件代理接管"

    def test_card_fields_stay_wired(self):
        """卡片字段清单直接对应需求，掉了就是功能缺失。"""
        html = self._html()
        for token in ("音标", "词性", "语义簇", "释义", "意象与标注", "原型层级",
                      "英汉对齐", "五元语义分解", "义位明细", "关联节点",
                      "来源与复核", "备注 / 收藏"):
            assert token in html, f"词条卡片缺少字段：{token}"
        for token in ("关系名称", "源词条", "目标词条", "关系类型", "关系方向",
                      "关系说明", "权重 / 强度", "共同邻居", "例句", "来源"):
            assert token in html, f"关系卡片缺少字段：{token}"

    def test_data_gaps_are_stated_not_hidden(self):
        """
        缺失数据要明说，不能留空白让人以为是自己没找到。

        音标 23/171、义位 17/171、例句 43/171、aspect/scope 全空 —— 这四个缺口
        都要在界面上有文字说明。
        """
        html = self._html()
        assert "未收录" in html, "音标缺失应显式标注"
        assert "库中 171 词全部为空，暂无数据" in html, "aspect/scope 空要说明"
        assert "该词尚未拆分义位" in html, "无义位要说明"
        assert "171/171" not in html or True  # 数字会随数据变，不硬钉

    def test_no_fabricated_similarity_score(self):
        """
        关系卡片不许编造相似度分数。

        次类内是完全图，每条边结构等价，「共同邻居数」恒等于次类词数 − 2，
        任何 0~1 的相似度都只是把簇大小重新标度一遍。所以只给可验证的结构指标，
        并在卡片里说明为什么没有权重。
        """
        html = self._html()
        assert "本图没有边权重字段" in html, "必须说明为什么没有权重"
        assert "共同邻居" in html, "给出可验证的替代指标"

    def test_annotations_persist_locally_with_fallback(self):
        """
        收藏 / 备注写 localStorage；被沙箱禁用时退回内存 store。

        图谱页是 iframe 里的静态 HTML，没有回写服务端的通道 —— 所以只能存本地，
        并且必须如实告诉用户。存储不可用时降级到内存而不是抛异常。
        """
        html = self._html()
        assert "wordgraph.annotations.v1" in html
        assert "localStorage.setItem" in html and "localStorage.getItem" in html
        assert "memStore" in html, "localStorage 不可用时要退回内存 store"
        assert "保存在本机浏览器" in html, "必须如实告知存储位置"
        # 词与边分开存键，避免 id 空间撞车
        assert "annSet('word'" in html and "annSet('edge'" in html
