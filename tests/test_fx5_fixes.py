"""FX5 批次修复验证（R6 代码质量 ＋ R8 UX，对应 docs 台账 R6-2~R6-12 / R8-2 /
R8-3 / R7-13）。

两层结构（与既有批次测试约定一致）：

  * 纯结构断言（模块常量 / 改名后的符号在场与缺席 / docstring 覆盖 /
    源码文本口径）—— 本地与 CI 全跑，不碰数据库；
  * 行为断言（db_utils 四小件 / media_db 状态机纯守卫 / collab 吞错留痕）
    —— 同样无库依赖（守卫在触库前返回，或 monkeypatch 假 cursor）。

R8-1（侧边栏密码入口三处合一）与 R8-4（render_card_header 分隔符）目标
实现均在 src/app.py（本批次禁碰清单），未实施 —— 见交付报告，不在本文件
断言之列。
"""

import ast
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.annotation_flow as annotation_flow  # noqa: E402
import src.collab_pages as collab_pages  # noqa: E402
import src.design_system as design_system  # noqa: E402
import src.dict_admin_db as dict_admin_db  # noqa: E402
import src.dict_admin_pages as dict_admin_pages  # noqa: E402
import src.lexical_pages as lexical_pages  # noqa: E402
import src.media_db as media_db  # noqa: E402
import src.sense_spine as sense_spine  # noqa: E402
import src.users_admin_page as users_admin_page  # noqa: E402
import src.writing_pages as writing_pages  # noqa: E402
import src.cluster_analysis as cluster_analysis  # noqa: E402
from src import db_utils  # noqa: E402


# ============================================
# R6-4：公共小件单一实现点（src/db_utils.py）
# ============================================

class TestDbUtils:
    """db_utils 四小件：语义与既有各副本逐字节一致（收敛不改行为）。"""

    def test_as_int_cases(self):
        """宽松转 int：整数/整值 float/整数串可转；bool/None/脏值 → None。"""
        assert db_utils.as_int(7) == 7
        assert db_utils.as_int("42") == 42
        assert db_utils.as_int(3.0) == 3
        assert db_utils.as_int(True) is None      # bool 是 int 子类，先拦
        assert db_utils.as_int(False) is None
        assert db_utils.as_int(None) is None
        assert db_utils.as_int("abc") is None
        assert db_utils.as_int(2.5) == 2          # int() 截断（与原副本一致）
        assert db_utils.as_int([1]) is None

    def test_column_and_table_exists_use_placeholder_and_database(self):
        """information_schema 探测：schema 取 DATABASE()，值全走占位符。"""
        class _Cursor:
            def __init__(self):
                self.sqls, self.params = [], []
                self.n = 1

            def execute(self, sql, params=None):
                self.sqls.append(sql)
                self.params.append(params)

            def fetchone(self):
                return {"n": self.n}

        cur = _Cursor()
        assert db_utils.column_exists(cur, "media_bindings", "reviewed_by") is True
        assert "information_schema.COLUMNS" in cur.sqls[0]
        assert "DATABASE()" in cur.sqls[0]
        assert cur.params[0] == ("media_bindings", "reviewed_by")

        cur.n = 0
        assert db_utils.table_exists(cur, "assignments") is False
        assert "information_schema.TABLES" in cur.sqls[1]
        assert cur.params[1] == ("assignments",)

    def test_current_user_dict_only(self, monkeypatch):
        """会话 user 非 dict（缺键/脏值）→ None（fail-closed）。"""
        import streamlit as st

        class _FakeState(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        monkeypatch.setattr(st, "session_state", _FakeState())
        assert db_utils.current_user() is None
        monkeypatch.setattr(st, "session_state",
                            _FakeState(user={"id": 1, "role": "admin"}))
        assert db_utils.current_user() == {"id": 1, "role": "admin"}
        monkeypatch.setattr(st, "session_state", _FakeState(user="admin"))
        assert db_utils.current_user() is None

    def test_page_modules_share_single_implementation(self):
        """各模块的 _as_int/_current_user 与 db_utils 是同一函数对象。"""
        assert lexical_pages._as_int is db_utils.as_int
        assert sense_spine._as_int is db_utils.as_int
        assert annotation_flow._as_int is db_utils.as_int
        assert dict_admin_db._as_int is db_utils.as_int
        assert media_db._as_int is db_utils.as_int
        for mod in (lexical_pages, collab_pages, dict_admin_pages,
                    users_admin_page, writing_pages):
            assert mod._current_user is db_utils.current_user, mod.__name__
        assert media_db._column_exists is db_utils.column_exists
        assert dict_admin_db._table_exists is db_utils.table_exists


# ============================================
# R6-2：孤儿删除 ＋ tools 阶段口径
# ============================================

class TestR62:
    def test_session_roles_removed(self):
        """R6-2：collab_pages._session_roles 孤儿已删（验收 grep 清零）。"""
        assert not hasattr(collab_pages, "_session_roles")

    def test_tools_docstrings_declare_stage_scope(self):
        """src/tools 六个模块 docstring 明示「阶段 1 仅契约与自检」。"""
        import src.tools as tools_pkg
        import src.tools.builtin as builtin_pkg
        import src.tools.builtin.semantic_search_tool as t1
        import src.tools.builtin.template_tool as t2
        import src.tools.builtin.typicality as t3
        import src.tools.registry as registry

        for mod in (tools_pkg, registry, builtin_pkg, t1, t2, t3):
            doc = ast.get_docstring(ast.parse(inspect.getsource(mod))) or ""
            assert "阶段 1 仅契约与自检" in doc, mod.__name__
            assert "阶段 2" in doc, mod.__name__


# ============================================
# R6-4：同名不同义四件改名
# ============================================

class TestR64Renames:
    def test_dump_json_strict(self):
        """dict_admin_db._dump_json → _dump_json_strict（旧名缺席）。"""
        assert callable(dict_admin_db._dump_json_strict)
        assert not hasattr(dict_admin_db, "_dump_json")

    def test_can_adjudicate_inbox(self):
        """collab_pages._can_adjudicate → _can_adjudicate_inbox。"""
        assert callable(collab_pages._can_adjudicate_inbox)
        assert not hasattr(collab_pages, "_can_adjudicate")

    def test_list_categories_dicts(self):
        """writing_pages._list_categories → _list_categories_dicts。"""
        assert callable(writing_pages._list_categories_dicts)
        assert not hasattr(writing_pages, "_list_categories")

    def test_fetch_submissions_for_spine(self):
        """sense_spine._fetch_submissions → _fetch_submissions_for_spine。"""
        assert callable(sense_spine._fetch_submissions_for_spine)
        assert not hasattr(sense_spine, "_fetch_submissions")


# ============================================
# R6-5：审定状态流转单一实现 ＋ 配色单份
# ============================================

class TestR65:
    def test_lexical_pages_use_db_chain(self):
        """lexical_pages 不再自留流转表，改调 lexical_db._next_example_status。"""
        assert not hasattr(lexical_pages, "NEXT_EXAMPLE_STATUS")
        assert lexical_pages._next_example_status is \
            __import__("src.lexical_db", fromlist=["_next_example_status"]
                       )._next_example_status
        assert lexical_pages._next_example_status("候选") == "审定"
        assert lexical_pages._next_example_status("审定") == "发布"
        assert lexical_pages._next_example_status("发布") is None

    def test_review_status_colors_single_source(self):
        """审定三态徽章配色单份进 design_system（页面侧同源引用）。"""
        assert design_system.REVIEW_STATUS_COLORS == {
            "候选": "#718096", "审定": "#2b6cb0", "发布": "#2f855a",
        }
        assert lexical_pages.STATUS_BADGE_COLORS is \
            design_system.REVIEW_STATUS_COLORS
        src = inspect.getsource(dict_admin_pages)
        assert "REVIEW_STATUS_COLORS" in src
        assert '"审定": "#4299e1"' not in src  # 旧漂移蓝不再出现


# ============================================
# R6-6 / R6-7：状态枚举域前缀 ＋ ANCHOR_TYPES 消歧
# ============================================

class TestR66R67:
    def test_media_status_prefix_values_unchanged(self):
        """MEDIA_STATUS_* 值与 DDL ENUM 一致（值不改，避免 DDL）。"""
        assert media_db.MEDIA_STATUS_CANDIDATE == "候选"
        assert media_db.MEDIA_STATUS_REVIEWED == "审定"
        assert media_db.MEDIA_STATUS_PUBLISHED == "发布"
        assert media_db.MEDIA_STATUSES == ("候选", "审定", "发布")
        for old in ("STATUS_CANDIDATE", "STATUS_REVIEWED", "STATUS_PUBLISHED",
                    "STATUSES"):
            assert not hasattr(media_db, old), old

    def test_media_anchor_types_renamed(self):
        """media_db.ANCHOR_TYPES → MEDIA_ANCHOR_TYPES（旧名缺席）。"""
        assert media_db.MEDIA_ANCHOR_TYPES == (
            "word", "sense", "example", "schema")
        assert not hasattr(media_db, "ANCHOR_TYPES")

    def test_dict_admin_db_alias_removed(self):
        """dict_admin_db 删 ANCHOR_TYPES 别名，只留 APPLIES_TO。"""
        assert dict_admin_db.APPLIES_TO == ("word", "sense", "example")
        assert not hasattr(dict_admin_db, "ANCHOR_TYPES")


# ============================================
# R6-8：TASK_TYPE_LABELS 单一导出
# ============================================

class TestR68:
    def test_single_export_and_identity(self):
        """annotation_flow 单一导出；sense_spine / collab_pages 同源引用。"""
        assert annotation_flow.TASK_TYPE_LABELS == {
            "admission": "义位准入",
            "feature_coding": "特征编码",
            "alignment": "英汉对齐",
        }
        assert set(annotation_flow.TASK_TYPE_LABELS) == set(
            annotation_flow.TASK_TYPES)
        assert sense_spine.TASK_TYPE_LABELS is annotation_flow.TASK_TYPE_LABELS
        assert collab_pages.TASK_TYPE_LABELS is annotation_flow.TASK_TYPE_LABELS


# ============================================
# R6-9：widget key 前缀收敛
# ============================================

class TestR69:
    def test_grant_user_key_prefixed(self):
        """role_grant_user → users_admin_role_grant_user（区前缀唯一）。"""
        src = inspect.getsource(users_admin_page)
        assert 'key="users_admin_role_grant_user"' in src
        assert 'key="role_grant_user"' not in src


# ============================================
# R6-10：静默吞错补 logger.warning（collab 两处）
# ============================================

class TestR610:
    def test_pending_stage_counts_logs_on_failure(self, caplog):
        """库不可用按空清单降级时留 warning（不再静默）。"""
        import logging

        def _boom():
            raise RuntimeError("db down")

        monkey_token = caplog.at_level(logging.WARNING, logger=collab_pages.__name__)
        with monkey_token:
            original = collab_pages.get_db_cursor
            collab_pages.get_db_cursor = _boom
            try:
                assert collab_pages._pending_stage_counts() == []
            finally:
                collab_pages.get_db_cursor = original
        assert any("pending_stage_counts" in r.message for r in caplog.records)

    def test_pending_inbox_count_source_has_warning(self):
        """侧边栏徽章计数失败留 warning（源码口径断言；函数带 30s 缓存）。"""
        src = inspect.getsource(collab_pages)
        assert "pending_inbox_count 侧边栏待办计数失败" in src


# ============================================
# R6-11：无 docstring 函数清零（本批次涉改文件）
# ============================================

class TestR611:
    FX5_FILES = (
        "src/dict_admin_pages.py", "src/collab_pages.py",
        "src/cluster_analysis.py", "src/lexical_pages.py",
        "src/users_admin_page.py", "src/entry_assembly.py",
        "src/sense_spine.py", "src/design_system.py", "src/security.py",
        "src/annotation_flow.py", "src/writing_pages.py",
        "src/media_db.py", "src/dict_admin_db.py", "src/db_utils.py",
        "src/category_study_page.py",
    )

    def test_all_functions_have_docstrings(self):
        """涉改文件内函数（含嵌套函数）docstring 覆盖 100%。"""
        for rel in self.FX5_FILES:
            tree = ast.parse(open(os.path.join(PROJECT_ROOT, rel)).read())
            missing = [
                f"{n.name}:{n.lineno}" for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and ast.get_docstring(n) is None
            ]
            assert not missing, f"{rel} 缺 docstring: {missing}"


# ============================================
# R6-12：媒体状态机下沉 media_db
# ============================================

class TestR612:
    def test_data_layer_functions_present(self):
        """advance_binding_status / next_binding_status / list_assets 在场。"""
        sig = inspect.signature(media_db.advance_binding_status)
        assert list(sig.parameters) == [
            "binding_id", "from_status", "to_status", "reviewed_by"]
        assert sig.parameters["reviewed_by"].default is None
        assert callable(media_db.next_binding_status)
        assert callable(media_db.list_assets)

    def test_next_binding_status_chain(self):
        """候选→审定→发布单步链（media_db.MEDIA_STATUS_NEXT 单一事实源）。"""
        assert media_db.next_binding_status("候选") == "审定"
        assert media_db.next_binding_status("审定") == "发布"
        assert media_db.next_binding_status("发布") is None
        assert media_db.next_binding_status("") is None
        assert media_db.next_binding_status(None) is None

    def test_page_delegates_to_data_layer(self):
        """页面私有 _advance_binding_status/_list_media_assets/_next_media_status
        删除，媒体 tab 改调 media_db（源码口径）。"""
        for gone in ("_advance_binding_status", "_list_media_assets",
                     "_next_media_status", "MEDIA_STATUS_NEXT"):
            assert not hasattr(dict_admin_pages, gone), gone
        src = inspect.getsource(dict_admin_pages)
        assert "media_db.advance_binding_status(" in src
        assert "media_db.list_assets(" in src
        assert "media_db.next_binding_status(" in src

    def test_advance_rejects_before_touching_db(self):
        """非单步对 / 非法 id 在触库前拒绝（守卫顺序，无库依赖可测）。"""
        assert media_db.advance_binding_status(1, "候选", "发布") is False
        assert media_db.advance_binding_status(1, "发布", "发布") is False
        assert media_db.advance_binding_status(1, "草稿", "审定") is False
        assert media_db.advance_binding_status(0, "候选", "审定") is False
        assert media_db.advance_binding_status(-1, "候选", "审定") is False
        assert media_db.advance_binding_status(None, "候选", "审定") is False


# ============================================
# R8-2：语义分析九 tab 标签缩短
# ============================================

class TestR82:
    def test_nine_tab_labels_short(self):
        """九 tab 全部短版；无「谱系树与交互切割」/「总览甄别」字面。"""
        expected = ("🌳 谱系树", "🏆 典型性", "🧬 分立复核", "🕸️ 义位图谱",
                    "🫱🫲 双语对比", "🔥 编码热图", "🔀 跨语言对齐",
                    "⚖️ 图式对齐", "📋 总览")
        src = inspect.getsource(cluster_analysis)
        for label in expected:
            assert label in src, label
        tabs_block = src[src.index("st.tabs(["):src.index("])", src.index("st.tabs(["))]
        assert "谱系树与交互切割" not in tabs_block
        assert "总览甄别" not in tabs_block


# ============================================
# R8-3：总览计数口径注 ＋ 硬编码条数转动态
# ============================================

class TestR83:
    def test_overview_carries_scope_caption(self):
        """总览视图带口径注（同源同口径 / 缓存窗口 / 词典层差异）。"""
        import src.category_study_page as csp

        src = inspect.getsource(csp.render_overview_view)
        assert "口径注" in src
        assert "get_screening_stats" in src
        assert "get_categories" in src

    def test_matrix_lang_labels_dynamic(self):
        """编码热图语言侧标签实时计数（硬编码「汉语（19 条目）」不再出现）。"""
        import src.category_study_page as csp

        src = inspect.getsource(csp)
        assert "汉语（19 条目）" not in src
        assert "英语（32 义位）" not in src
        assert "f\"英语（{n_en} 义位）\"" in src


# ============================================
# R7-13：待我裁决文案指向新页名
# ============================================

class TestR713:
    def test_adjudication_hint_uses_new_page_name(self):
        """「📈 谱系与典型性」→「📊 语义分析」（tab 名随 R8-2 短版）。"""
        src = inspect.getsource(collab_pages)
        assert "「📊 语义分析 · 🧬 分立复核」tab 完成" in src
        assert "📈 谱系与典型性" not in src
