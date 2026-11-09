"""FX10 批次修复验证（R6 质量收敛残留 ＋ R7 文档一致性残留）。

对应台账：R6-4（export_center/_column_exists、export_center/pipeline_status
的 _table_exists 收敛 db_utils）、R6-6（export_center EXPORT_STATUS_* 域前缀）、
R6-10（media_db/export_center 静默吞错清零——AST 全量核查）、R6-11
（pipeline_status 六 _format_*＋template_engine _strip_prefix/_get_category
＋export_center _table_exists 补 docstring）、R7-22/23/25/26（README /
ARCHITECTURE / CHANGELOG / 功能使用说明 过时数字与标注）。

两层结构（与既有批次测试约定一致）：

  * 结构断言（docstring 覆盖 / 文档口径 grep / 源码文本口径）——本地与 CI 全跑；
  * 行为断言（_table_exists 薄包装经 db_utils.table_exists 探测）——monkeypatch
    假 cursor，无库依赖。

R7-26 的「七类→八类」经 scripts/env_doctor.py 核实为**七类**（Python/MySQL/
.env/AI 接入/种子数据/数据库内容/端口磁盘），功能使用说明的「七类检查」口径
正确，**不改**——本文件顺带钉住两处「七类」一致性，防止后续误改。
"""

import ast
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.export_center as export_center  # noqa: E402
import src.pipeline_status as pipeline_status  # noqa: E402
from src import db_utils  # noqa: E402


# ============================================
# R6-4：export_center / pipeline_status 探测小件收敛
# ============================================

class TestR64ExportCenter:
    def test_column_exists_is_db_utils(self):
        """export_center._column_exists 不再留本地副本，与 db_utils 同一函数对象。"""
        assert export_center._column_exists is db_utils.column_exists

        # 行为一致（假 cursor 直测，与 test_fx5_fixes 同款）
        class _Cursor:
            sqls, params, n = [], [], 1

            def execute(self, sql, params=None):
                self.sqls.append(sql)
                self.params.append(params)

            def fetchone(self):
                return {"n": self.n}

        cur = _Cursor()
        assert export_center._column_exists(
            cur, "export_batches", "published_by") is True
        assert "information_schema.COLUMNS" in cur.sqls[0]
        assert cur.params[0] == ("export_batches", "published_by")

    def test_table_exists_delegates_to_db_utils(self, monkeypatch):
        """_table_exists（只传表名、自开游标口径）收敛为 db_utils.table_exists 薄包装。"""
        calls = []

        def _fake_probe(cursor, table):
            calls.append((cursor, table))
            return table == "definitions"

        monkeypatch.setattr(export_center, "_db_table_exists", _fake_probe)

        class _Cursor:
            pass

        cur = _Cursor()

        class _Ctx:
            def __enter__(self):
                return cur

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(export_center, "get_db_cursor", lambda: _Ctx())
        assert export_center._table_exists("definitions") is True
        assert export_center._table_exists("missing_table") is False
        assert calls == [(cur, "definitions"), (cur, "missing_table")]


class TestR64PipelineStatus:
    def test_table_exists_delegates_to_db_utils(self, monkeypatch):
        """pipeline_status._table_exists 同口径收敛（探测逻辑单一实现点）。"""
        calls = []

        def _fake_probe(cursor, table):
            calls.append(table)
            return table == "cs_senses"

        monkeypatch.setattr(pipeline_status, "_db_table_exists", _fake_probe)

        class _Cursor:
            pass

        cur = _Cursor()

        class _Ctx:
            def __enter__(self):
                return cur

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(pipeline_status, "get_db_cursor", lambda: _Ctx())
        assert pipeline_status._table_exists("cs_senses") is True
        assert pipeline_status._table_exists("annotation_submissions") is False
        assert calls == ["cs_senses", "annotation_submissions"]

    def test_probe_sql_lives_only_in_db_utils(self):
        """information_schema 探测 SQL 全仓库只剩 db_utils 一份（本两模块不再复制）。"""
        for mod in (export_center, pipeline_status):
            src = inspect.getsource(mod)
            assert "information_schema.TABLES" not in src, mod.__name__


# ============================================
# R6-6：export_center 快照状态域前缀
# ============================================

class TestR66ExportStatus:
    def test_constants_domain_prefixed_values_unchanged(self):
        """EXPORT_STATUS_* 与 DDL ENUM('ready','published','revoked') 一致（值不改）。"""
        assert export_center.EXPORT_STATUS_READY == "ready"
        assert export_center.EXPORT_STATUS_PUBLISHED == "published"
        assert export_center.EXPORT_STATUS_REVOKED == "revoked"
        assert export_center.EXPORT_STATUSES == (
            "ready", "published", "revoked")

    def test_insert_uses_constant_not_inline_literal(self):
        """登记 INSERT 不再内联裸 'ready' 字面量（状态值走域前缀常量）。"""
        src = inspect.getsource(export_center.build_content_snapshot)
        assert "'ready'" not in src
        assert "EXPORT_STATUS_READY" in src


# ============================================
# R6-10：静默吞错清零（AST 全量核查，防回归）
# ============================================

class TestR610NoSilentExcept:
    def test_every_handler_logs_or_raises(self):
        """media_db / export_center 所有 except 块必须 logger 留痕或显式抛出。"""
        for rel in ("src/media_db.py", "src/export_center.py"):
            tree = ast.parse(open(os.path.join(PROJECT_ROOT, rel)).read())
            silent = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                for handler in node.handlers:
                    body = ast.unparse(handler.body)
                    if "logger." not in body and "raise" not in body:
                        silent.append(f"{rel}:{handler.lineno}")
            assert not silent, f"{rel} 静默吞错: {silent}"


# ============================================
# R6-11：本批次涉改文件函数 docstring 覆盖 100%
# ============================================

class TestR611Docstrings:
    FILES = (
        "src/pipeline_status.py", "src/template_engine.py",
        "src/export_center.py", "src/db_utils.py",
    )

    def test_all_functions_have_docstrings(self):
        """涉改文件内函数（含嵌套函数）docstring 覆盖 100%（同 FX5 口径）。"""
        for rel in self.FILES:
            tree = ast.parse(open(os.path.join(PROJECT_ROOT, rel)).read())
            missing = [
                f"{n.name}:{n.lineno}" for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and ast.get_docstring(n) is None
            ]
            assert not missing, f"{rel} 缺 docstring: {missing}"

    def test_six_segment_formatters_declared(self):
        """pipeline_status 六个 _format_* 一行式 docstring 在场（RV3-7 同源）。"""
        for key, fn in pipeline_status._SEGMENT_FORMATTERS.items():
            assert fn.__doc__, f"段 {key} 格式化器缺 docstring"


# ============================================
# R7-25：CHANGELOG 批次 13 置顶 ＋ 八 tab 口径
# ============================================

class TestR725Changelog:
    def _read(self) -> str:
        path = os.path.join(PROJECT_ROOT, "docs", "dev", "CHANGELOG.md")
        return open(path).read()

    def test_batch13_entry_is_topmost(self):
        """新条目（批次 13：FX10）置顶——首个「## 」标题即本批。"""
        text = self._read()
        headings = [
            ln for ln in text.splitlines() if ln.startswith("## ")]
        assert headings, "CHANGELOG 无条目标题"
        # 置顶条目随批次滚动更新（FX-16 先例：每批入账置顶）——
        # 现最新为 review waves 1-2（f85e5e6），要求置顶为日期前缀新条目
        assert headings[0].startswith("## 2026-"), headings[0]
        assert "批次 13" not in headings[0], "批次 13 条目应已非置顶"

    def test_no_seven_tab_left(self):
        """「七 tab」口径清零（词典管理区实际八 tab，dict_admin_pages 页内八 tab）。"""
        assert "七 tab" not in self._read()
        assert "八 tab" in self._read()

    def test_batch_11_12_and_v2_entries_present(self):
        """批次 11/12 与 v2 词表 171 条目在位（此前批已补，钉住不丢）。"""
        text = self._read()
        assert "批次 12" in text
        assert "批次 11" in text
        assert "171 词" in text


# ============================================
# R7-26：功能使用说明 7.4 扩展项标注 ＋ 七类口径
# ============================================

class TestR726HelpDoc:
    def _read(self) -> str:
        path = os.path.join(
            PROJECT_ROOT, "docs", "help", "平台功能使用说明.md")
        return open(path).read()

    def test_74_extension_marked_stage1_followup(self):
        """7.4 扩展项（媒体 sha256 抽验/配置漂移/备份新鲜度）标【阶段 1 后续】。"""
        text = self._read()
        section = text[text.index("### 7.4"):text.index("### 7.5")]
        assert "【阶段 1 后续】" in section
        assert "扩展项" in section

    def test_seven_classes_matches_env_doctor(self):
        """「七类」口径与 scripts/env_doctor.py 一致（实查七类，不改八类）。"""
        doctor = open(os.path.join(
            PROJECT_ROOT, "scripts", "env_doctor.py")).read()
        assert "检查七类环境要素" in doctor
        assert "七类检查" in self._read()

    def test_no_stale_vocab_numbers(self):
        """136 词 / 1780 / 8 簇 过时口径清零；六卡片口径在场。"""
        text = self._read()
        assert "1780" not in text
        assert "四张结果卡片" not in text
        assert "六张结果卡片" in text
        assert "171 词/1935 边/12 簇" in text


# ============================================
# R7-22：README 过时数字
# ============================================

class TestR722Readme:
    def _read(self) -> str:
        return open(os.path.join(PROJECT_ROOT, "README.md")).read()

    def test_no_stale_numbers(self):
        """1780 / 8 个次类 / 四张卡片 清零。"""
        text = self._read()
        assert "1780" not in text
        assert "8 个次类" not in text
        assert "四张卡片" not in text

    def test_current_numbers_present(self):
        """现行口径 171 词 / 1935 边 / 12 次类簇 / 六张卡片 在场。"""
        text = self._read()
        assert "171 词 / 1935 边" in text
        assert "12 个次类簇" in text
        assert "六张结果卡片" in text

    def test_remaining_136_mentions_are_v1_scoped(self):
        """残留「136 词」仅限 v1 历史口径注与卡片原文引用（不冒充现行口径）。"""
        for ln in self._read().splitlines():
            if "136 词" in ln:
                assert ("v1" in ln or "全部为空" in ln), ln


# ============================================
# R7-23：ARCHITECTURE 五处硬错
# ============================================

class TestR723Architecture:
    def _read(self) -> str:
        return open(os.path.join(PROJECT_ROOT, "docs", "dev",
                                 "ARCHITECTURE.md")).read()

    def test_five_hard_errors_fixed(self):
        """136 词 / 1780 / 8 次类簇 / 四张(结果)卡片 全部清零（五处硬错）。"""
        text = self._read()
        assert "136 词" not in text          # L132 / L151
        assert "1780" not in text            # L132 / L151
        assert "8 次类簇" not in text        # L132
        assert "四张" not in text            # L18 / L46 / L179

    def test_current_facts_present(self):
        """现行口径在场：171 词 / 12 次类簇 / 1935 边 / 六卡片。"""
        text = self._read()
        assert "171 词 / 12 次类簇 → 1935 条边" in text
        assert "171 词 / 1935 边" in text
        assert "六张结果卡片" in text
        assert "结果六卡片" in text
        assert "填入六张卡片" in text
