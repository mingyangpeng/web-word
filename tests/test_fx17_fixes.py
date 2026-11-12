"""FX-17 修复批次的回归测试。

覆盖台账（与修复工程师 FX-17 的改动一一对应，来源 RV-2/RV-4/RV-8/R6-4 复审）：

  * RV2-1  clear_all_word_data 标注数据闸门：有标注行且未 force → 显式报错
           （含各表行数）；force 放行前置闸；删除撞 MySQL 1451 → 显式报错
           不再「静默回滚 + 返回假计数」；哑游标（既有单测桩）行为不变；
  * RV2-2  「users FK 删除纪律」规范注释在位（users_db 单一出处 ＋ org_db
           互指），不做破坏性 ALTER；
  * RV2-3  「留痕列 NULL 口径」规范注释在位（mysql_db CREATE_TABLES_SQL 头）；
  * RV2-4  CREATE_TABLES_SQL 头部 ALTER-only 列清单在位，且清单内
           mysql_db 管辖的列确实不在任何 CREATE 文本里（清单与实况互钉）；
  * RV4-3  媒体路径 base 闸：../ 逃逸 / 绝对路径越界 / 符号链接三条负向
           （register_asset 返回 0 ＋ 拒绝文案可读），base 内文件放行；
  * RV4-5  grant_role / revoke_role docstring 明示 TOCTOU 亚 rerun 窗口并
           指向页面的实时复核行（list_roles）；
  * RV4-6  app.py 的 st.warning 不再把异常对象插值进用户可见文案（AST 钉死）；
  * RV4-8  ci-cd.yml 有 pip-audit 温和档 step（continue-on-error ＋ 误伤注释）；
  * RV8-2/RV8-6  .env.example 补 9+3 变量，且键名逐个以 src/ 实读反证存在；
  * R6-4   六处本地副本收敛 db_utils：五处为别名导入（`is` 同一函数对象），
           mysql_db._column_exists 因查询形态被 tests/test_schema 迁移契约
           桩钉死而声明豁免（源码 docstring 注明与 db_utils 的关系）；
           同名不同义件 cluster_analysis._as_int_id 明确不动；
  * 跨路遗留  test_schema 词簇卡片字段 token 随 FX-15 改名（语义簇→词簇，
           TEMPLATE_VERSION 23）。
"""

import ast
import logging
import os
import re
import sys
from pathlib import Path

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.ai_ledger as ai_ledger  # noqa: E402
import src.app as app  # noqa: E402
import src.data_pages as data_pages  # noqa: E402
import src.db_utils as db_utils  # noqa: E402
import src.graph_export as graph_export  # noqa: E402
import src.media_db as media_db  # noqa: E402
import src.mysql_db as mysql_db  # noqa: E402
import src.users_db as users_db  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _src_text(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


# ============================================
# RV2-1：clear_all_word_data 标注数据闸门
# ============================================

class _FakeCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, exc_type, exc, tb):
        return False


class _RealLikeCursor:
    """有 description 的游标桩（pymysql DictCursor 的行为面）。

    counts: 表名 → SELECT COUNT 返回值（缺省 0）；delete_error: DELETE 时抛的
    异常。description 在场 ⇒ clear_all_word_data 的前置探测闸正常工作。
    """

    description = [("n",)]

    def __init__(self, counts=None, delete_error=None):
        self.counts = counts or {}
        self.delete_error = delete_error
        self.executed = []
        self._last = ""

    def execute(self, sql, params=None):
        self.executed.append(sql)
        self._last = sql
        if sql.strip().upper().startswith("DELETE") and self.delete_error:
            raise self.delete_error

    def fetchone(self):
        for table, n in self.counts.items():
            if f"FROM {table}" in self._last:
                return {"n": n}
        return {"n": 0}


class TestRV21ClearAllGate:
    """清词表必须先过标注数据闸（FK 1451 前置探测 ＋ 后置兜底）。"""

    def _patch(self, monkeypatch, cursor):
        monkeypatch.setattr(mysql_db, "get_db_cursor",
                            lambda autocommit=True: _FakeCtx(cursor))

    def test_refuses_when_annotation_rows_exist(self, monkeypatch):
        """有标注行且未 force → RuntimeError 报各表行数，一条 DELETE 都不发。"""
        cur = _RealLikeCursor(counts={"annotation_submissions": 3,
                                      "adjudications": 1})
        self._patch(monkeypatch, cur)
        with pytest.raises(RuntimeError) as ei:
            mysql_db.clear_all_word_data()
        msg = str(ei.value)
        assert "annotation_submissions=3" in msg
        assert "adjudications=1" in msg
        assert "force=True" in msg          # 报错要给出放行方式
        assert not [s for s in cur.executed
                    if s.strip().upper().startswith("DELETE")]

    def test_no_annotation_rows_proceeds_unchanged(self, monkeypatch):
        """无标注数据 → 行为与旧版一致（四表 DELETE 全发，返回各表计数）。"""
        cur = _RealLikeCursor()
        self._patch(monkeypatch, cur)
        removed = mysql_db.clear_all_word_data()
        for table in ("word_relations", "oald_senses", "word_senses",
                      "definitions", "word_clusters"):
            assert f"DELETE FROM {table}" in cur.executed
        assert set(removed) == {"word_relations", "oald_senses",
                                "word_senses", "definitions", "word_clusters"}

    def test_force_bypasses_pregate(self, monkeypatch):
        """force=True 放行前置闸（DELETE 照发；物理约束仍在）。"""
        cur = _RealLikeCursor(counts={"annotation_submissions": 3})
        self._patch(monkeypatch, cur)
        removed = mysql_db.clear_all_word_data(force=True)
        assert "DELETE FROM oald_senses" in cur.executed
        assert removed["word_relations"] == 0

    def test_fk_1451_raises_instead_of_fake_success(self, monkeypatch):
        """删除撞 1451（探测后窗口内新到标注行等）→ RuntimeError，不假成功。"""
        err = pymysql.err.IntegrityError(
            1451, "Cannot delete or update a parent row: a foreign key "
                  "constraint fails (`web_word_db`.`annotation_submissions`")
        cur = _RealLikeCursor(delete_error=err)
        self._patch(monkeypatch, cur)
        with pytest.raises(RuntimeError) as ei:
            mysql_db.clear_all_word_data()
        assert "1451" in str(ei.value)
        assert "annotation_submissions" in str(ei.value)

    def test_dumb_cursor_without_description_keeps_old_behavior(self, monkeypatch):
        """哑游标（既有单测桩形态，无 description）：前置闸跳过，行为不变。"""

        class _DumbCursor:
            def __init__(self):
                self.executed = []

            def execute(self, sql, params=None):
                self.executed.append(sql)

            def fetchone(self):
                return {"n": 5}

        cur = _DumbCursor()
        self._patch(monkeypatch, cur)
        removed = mysql_db.clear_all_word_data()
        assert "DELETE FROM definitions" in cur.executed
        assert removed["definitions"] == 5

    def test_generic_db_error_returns_empty_not_fake_counts(self, monkeypatch):
        """非 1451 的 DB 错误 → 返回 {}（回滚后不返回回滚前的假计数）。"""
        err = pymysql.err.OperationalError(2002, "connection gone")
        cur = _RealLikeCursor(delete_error=err)
        self._patch(monkeypatch, cur)
        assert mysql_db.clear_all_word_data() == {}


# ============================================
# RV4-3：媒体路径 base 闸（三条负向 + 正向对照）
# ============================================

class TestRV43MediaPathGate:
    """register_asset 路径边界：resolve 后限 base ＋ 拒 symlink。"""

    @pytest.fixture
    def base_env(self, tmp_path, monkeypatch):
        """把允许清单钉到 tmp 下的 media/ 目录（避免写仓库 data/）。"""
        base = tmp_path / "media"
        base.mkdir()
        monkeypatch.setattr(media_db, "_media_bases", lambda: (str(base),))
        return base

    def _png(self, dir_path: Path, name="x.png") -> Path:
        p = dir_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(PNG_BYTES)
        return p

    def test_register_rejects_relative_dotdot_escape(self, base_env, tmp_path,
                                                     monkeypatch, caplog):
        """../ 逃逸：字符串上以 base 开头、resolve 后越界的相对路径拒绝。"""
        self._png(tmp_path / "outside")
        monkeypatch.chdir(tmp_path)
        with caplog.at_level(logging.ERROR, logger="src.media_db"):
            rc = media_db.register_asset("media/../outside/x.png", "image",
                                         "s", "CC0")
        assert rc == 0
        assert any("越界路径" in r.message for r in caplog.records)

    def test_register_rejects_absolute_path_outside(self, caplog):
        """绝对路径越界（生产默认清单）：仓库 tests/ 下的真实文件拒绝。"""
        outside = Path(__file__).resolve()   # tests/test_fx17_fixes.py，必存在
        assert outside.is_file()
        assert str(outside).startswith(media_db.PROJECT_ROOT)  # 仓库内、data 外
        with caplog.at_level(logging.ERROR, logger="src.media_db"):
            rc = media_db.register_asset(str(outside), "image", "s", "CC0")
        assert rc == 0
        assert any("越界路径" in r.message for r in caplog.records)

    def test_register_rejects_symlink(self, base_env, tmp_path, caplog):
        """符号链接：base 内的链接指向 base 外的真实文件 → 拒绝。"""
        target = self._png(tmp_path / "outside")
        link = base_env / "link.png"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("当前环境不支持创建符号链接")
        assert os.path.islink(str(link))
        with caplog.at_level(logging.ERROR, logger="src.media_db"):
            rc = media_db.register_asset(str(link), "image", "s", "CC0")
        assert rc == 0
        assert any("符号链接" in r.message for r in caplog.records)

    def test_gate_allows_file_inside_base(self, base_env, tmp_path):
        """正向对照：base 内真实文件过闸（gate 放行，返回 None）。"""
        inside = self._png(base_env)
        assert media_db._media_path_gate(str(inside)) is None

    def test_default_bases_cover_real_media_dirs(self):
        """生产默认允许清单钉死：data/media ＋ data/ModernChineseDict
        （现汉配图加载链 scripts/load_media_xianhan.py 的既有来源）。"""
        bases = media_db.DEFAULT_MEDIA_BASES
        assert str(PROJECT_ROOT / "data" / "media") in bases
        assert str(PROJECT_ROOT / "data" / "ModernChineseDict") in bases


# ============================================
# R6-4：六处本地副本收敛 db_utils
# ============================================

class TestR64ConvergenceFX17:
    def test_aliases_are_single_implementation(self):
        """收敛件与 db_utils 是同一函数对象（同名同义，调用点零变化）。"""
        assert ai_ledger._as_int is db_utils.as_int
        assert app._current_user is db_utils.current_user
        assert data_pages._current_user is db_utils.current_user
        assert mysql_db._table_exists is db_utils.table_exists
        assert users_db._column_exists is db_utils.column_exists

    def test_mysql_db_column_exists_is_documented_exemption(self):
        """mysql_db._column_exists 刻意不收敛：三参 (schema, table, column)
        查询形态被 tests/test_schema 迁移契约桩（V2Cursor 读 params[1]/[2]）
        钉死，db_utils 版（两参 + DATABASE()）无法直接替换 —— 豁免原因必须
        留在源码 docstring（R6-4 说明块）。"""
        assert mysql_db._column_exists is not db_utils.column_exists
        text = _src_text("mysql_db.py")
        assert "不收敛" in text and "豁免" in text
        assert "test_schema" in text      # 指明钉死形态的测试

    def test_no_local_helper_defs_left(self):
        """AST 扫描：本地副本清零（mysql_db._column_exists 为已声明豁免项，
        其余 _as_int/_current_user/_table_exists 与三处 _column_exists 不再
        有本地定义）。"""
        targets = {"_as_int", "_current_user", "_table_exists"}
        for name in ("ai_ledger.py", "app.py", "data_pages.py",
                     "mysql_db.py", "users_db.py"):
            tree = ast.parse(_src_text(name))
            bad = [n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name in targets]
            assert not bad, f"{name} 仍有本地副本定义: {bad}"
        # _column_exists 仅剩 users_db（收敛）与 mysql_db（豁免）两处出现
        col_definers = []
        for name in ("ai_ledger.py", "app.py", "data_pages.py", "users_db.py",
                     "mysql_db.py"):
            tree = ast.parse(_src_text(name))
            if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "_column_exists" for n in ast.walk(tree)):
                col_definers.append(name)
        assert col_definers == ["mysql_db.py"], col_definers

    def test_same_name_different_meaning_untouched(self):
        """同名不同义件明确不动：cluster_analysis._as_int_id（正整数语义，
        ≤0 → None）保留原实现，不得被收敛波及 —— 与 as_int 的宽松 int 语义
        对照钉死。"""
        import src.cluster_analysis as cluster_analysis
        assert cluster_analysis._as_int_id is not db_utils.as_int
        assert cluster_analysis._as_int_id(True) is None   # 两者都拦 bool
        assert cluster_analysis._as_int_id(-3) is None     # 正整数语义
        assert db_utils.as_int(-3) == -3                   # 宽松 int 语义

    def test_db_utils_import_direction_is_acyclic(self):
        """收敛前提：db_utils 不得 import 任何 src 内部模块（无环）。"""
        tree = ast.parse(_src_text("db_utils.py"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("src"), alias.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "src" and not (
                    node.module or "").startswith("src."), node.module


# ============================================
# RV4-6：st.warning 不插值异常对象（app.py 面）
# ============================================

class TestRV46WarningNoExceptionLeak:
    def test_no_st_warning_interpolates_exception(self):
        """AST 钉死：src/app.py 所有 st.warning(...) 的实参不得插值异常
        变量（e/err/ex/exc）—— DB 信息走 logger，页面给通用文案。"""
        tree = ast.parse(_src_text("app.py"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr == "warning"
                    and isinstance(f.value, ast.Name) and f.value.id == "st"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.JoinedStr):
                    for value in arg.values:
                        if isinstance(value, ast.FormattedValue):
                            for sub in ast.walk(value):
                                if (isinstance(sub, ast.Name)
                                        and sub.id in {"e", "err", "ex", "exc"}):
                                    offenders.append(node.lineno)
        assert not offenders, f"st.warning 插值异常对象于行: {offenders}"

    def test_offline_banner_is_generic(self):
        """离线横幅文案不含异常插值细节，并注明细节去向（服务端日志）。"""
        text = _src_text("app.py")
        assert "数据库初始化失败，已转入离线模式（详情见服务端日志）" in text
        assert 'st.warning(f"⚠️ 数据库初始化失败' not in text


# ============================================
# RV4-5：grant/revoke TOCTOU docstring
# ============================================

class TestRV45GrantRevokeTocTouDocs:
    def test_grant_role_declares_toctou_window(self):
        doc = users_db.grant_role.__doc__ or ""
        assert "TOCTOU" in doc
        assert "亚 rerun" in doc
        assert "list_roles" in doc      # 指向页面的实时 DB 复核（users_admin_page）

    def test_revoke_role_declares_toctou_window(self):
        doc = users_db.revoke_role.__doc__ or ""
        assert "TOCTOU" in doc
        assert "亚 rerun" in doc
        assert "list_roles" in doc


# ============================================
# RV2-2 / RV2-3 / RV2-4：规范注释在位
# ============================================

class TestRV2NormComments:
    def test_rv22_fk_discipline_norm_in_users_db(self):
        text = _src_text("users_db.py")
        assert "users FK 删除纪律" in text            # 定名
        assert "NO ACTION" in text                    # 业务引用口径
        assert "入口前置探测" in text
        assert "annotation_flow" in text              # 两处口径互指（NO ACTION 示例）
        assert "org_db.py" in text                    # 互指（CASCADE 落点）

    def test_rv22_org_db_cross_reference(self):
        text = _src_text("org_db.py")
        assert "users FK 删除纪律" in text
        assert "src/users_db.py" in text              # 指回规范单一出处

    def test_rv23_null_semantics_norm_named(self):
        text = _src_text("mysql_db.py")
        assert "留痕列 NULL 口径" in text              # 定名
        for marker in ("INT NULL", "VARCHAR NULL", "NOT NULL DEFAULT ''"):
            assert marker in text

    # RV2-4：ALTER-only 列清单 —— (表, 列)。清单与 CREATE 文本互钉：
    # 头注释列出的 mysql_db 管辖列必须确实不在 CREATE_TABLES_SQL 里。
    # RV24-5 适配：cs_clusters.merged_into 系清单笔误（列实际在 cs_senses，
    # cluster_analysis 分立迁移 ＋ annotation_flow 台账读面两处补列）；
    # 补 annotation_submissions.ai_draft_snapshot（FX-43，annotation_flow）。
    ALTER_ONLY = (
        ("oald_senses", "human_reviewed"),
        ("domain_family_senses", "llm_tag"),
        ("domain_family_senses", "llm_schema"),
        ("domain_family_senses", "llm_align"),
        ("domain_family_senses", "llm_reason"),
        ("domain_family_senses", "llm_doubt"),
        ("domain_family_senses", "freq"),
        ("domain_family_senses", "schema_scores"),
        ("definitions", "import_voided"),
        ("media_bindings", "reviewed_by"),
        ("media_bindings", "reviewed_at"),
        ("export_batches", "published_by"),
        ("export_batches", "published_at"),
        ("reliability_runs", "created_by"),
        ("users", "must_change_password"),
        ("users", "created_by"),
        ("cs_clusters", "locked"),
        ("cs_senses", "merged_into"),
        ("annotation_submissions", "ai_draft_snapshot"),
    )

    def test_rv24_header_lists_alter_only_columns(self):
        text = _src_text("mysql_db.py")
        assert "ALTER-only 列清单" in text
        for _table, col in self.ALTER_ONLY:
            assert col in text, f"ALTER-only 清单缺列: {col}"

    def test_rv24_listed_columns_absent_from_create_tables_sql(self):
        """清单内 mysql_db 管辖的列不得出现在 CREATE_TABLES_SQL 的对应建表
        文本里 —— 清单失真（列被并进 CREATE 却没维护注释）即测试报警。"""
        managed = {("oald_senses", "human_reviewed"),
                   ("domain_family_senses", "llm_tag"),
                   ("domain_family_senses", "llm_schema"),
                   ("domain_family_senses", "llm_align"),
                   ("domain_family_senses", "llm_reason"),
                   ("domain_family_senses", "llm_doubt"),
                   ("domain_family_senses", "freq"),
                   ("domain_family_senses", "schema_scores")}
        for table, col in managed:
            blocks = re.findall(
                r"CREATE TABLE IF NOT EXISTS " + table + r" \(.*?ENGINE=InnoDB",
                "\n".join(mysql_db.CREATE_TABLES_SQL), re.DOTALL,
            )
            assert blocks, f"CREATE_TABLES_SQL 缺 {table} 建表文本"
            assert not re.search(rf"\b{col}\b", blocks[0]), (
                f"{table}.{col} 已进 CREATE 文本，请从 ALTER-only 清单移除")


# ============================================
# RV8-2 / RV8-6：.env.example 键名以代码实读反证
# ============================================

class TestEnvExampleKeys:
    # 键 → 反证其真实存在的模块（grep src/ 逐键核对，RV8-2/RV8-6）
    EXPECTED_KEYS = {
        "LLM_PROVIDER": "llm_api.py",
        "OPENAI_API_KEY": "llm_api.py",
        "OPENAI_BASE_URL": "llm_api.py",
        "DEEPSEEK_API_KEY": "llm_api.py",
        "DEEPSEEK_BASE_URL": "llm_api.py",
        "LLM_CONNECT_TIMEOUT": "llm_providers_db.py",
        "LLM_DB_PROVIDER_TTL_SECONDS": "llm_api.py",
        "MYSQL_TIME_ZONE": "mysql_db.py",
        "RELIABILITY_FORCE_PURE": "reliability.py",
        "MYSQL_CHARSET": "mysql_db.py",
        "MYSQL_COLLATION": "mysql_db.py",
    }

    def test_env_example_documents_all_keys(self):
        text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        for key in self.EXPECTED_KEYS:
            assert re.search(rf"^#?\s*{key}=", text, re.MULTILINE), (
                f".env.example 缺 {key}")

    def test_keys_actually_read_by_src(self):
        """反证：每个键在对应模块的源码里真实出现（台账键名笔误防线）。"""
        for key, module in self.EXPECTED_KEYS.items():
            assert key in _src_text(module), f"{key} 不在 src/{module}，键名有误"

    def test_mysql_defaults_match_code(self):
        """RV8-6：MYSQL_TIME_ZONE/CHARSET/COLLATION 的占位值 = mysql_db 缺省
        （与 src/mysql_db.py 头部常量缺省一致，避免模板误导部署）。"""
        text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "MYSQL_TIME_ZONE=+08:00" in text
        assert "MYSQL_CHARSET=utf8mb4" in text
        assert "MYSQL_COLLATION=utf8mb4_unicode_ci" in text
        src_mysql = _src_text("mysql_db.py")
        assert 'os.getenv("MYSQL_TIME_ZONE", "+08:00")' in src_mysql
        assert '_setting("MYSQL_CHARSET", "charset", "utf8mb4")' in src_mysql
        assert '_setting("MYSQL_COLLATION", "collation", "utf8mb4_unicode_ci")' \
            in src_mysql


# ============================================
# RV4-8：ci-cd.yml pip-audit 温和档
# ============================================

class TestCiCdPipAudit:
    WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci-cd.yml"

    def test_pip_audit_step_present(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        assert "pip-audit" in text
        assert "continue-on-error: true" in text      # 温和档：不挡 CI

    def test_lockfile_gap_risk_documented(self):
        """注释说明锁文件缺失的误伤风险（RV4-8 台账要求）。"""
        text = self.WORKFLOW.read_text(encoding="utf-8")
        assert "锁文件缺失误伤" in text


# ============================================
# 跨路遗留：词簇卡片字段 token（FX-15 改名随动）
# ============================================

class TestClusterCardTokenFX15:
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

    def test_word_card_uses_renamed_cluster_label(self):
        """FX-15 定名（语义簇→词簇，TEMPLATE_VERSION 23）后，词条卡片字段
        实渲染为「词簇」—— test_schema 的字段清单据此钉新名。"""
        html = graph_export.build_graph_html(self.SAMPLE)
        assert "词簇" in html
        assert "语义簇" not in html
        assert graph_export.TEMPLATE_VERSION >= 23
