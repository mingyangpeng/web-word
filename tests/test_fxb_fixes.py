"""FX-B 批次修复验证（RV-3 签名一致性 ＋ RV-4 安全深化 ＋ R6-4 收敛残留）。

对应台账（docs/dev/reports/findings_backlog.md）：
  * RV3-4  media_db.register_asset ``mime: str = None`` → ``Optional[str]``；
           _sha256_of_file 返回注解 ``Any`` → ``Optional[str]``；
  * RV4-2  media_db._sha256_of_file except 扩为 (OSError, ValueError)
           —— NUL byte 路径不再穿透为 traceback（dict_admin_pages 侧
           _sha256_file 同款修复属禁碰面，随集成批次落地）；
  * RV3-8  media_db.advance_binding_status 参数校验顺序对齐
           lexical_db.advance_example_status（先 id 后状态对）；
  * RV3-5  org_db.create_project chief_id 走 db_utils.as_int（bool 不再
           放行成 1）＋ categories 参数补类型注解；
  * RV3-6  update_draft（无变化=True）与 update_example（无变化=False）
           docstring 互注「相反是有意设计」；
  * RV3-7  pipeline_status.format_funnel_segments ``status: Any`` →
           ``dict``（_pending_stage_counts 在 collab_pages 禁碰面）；
  * RV3-3  操作人参数统一：start_batch ``operator`` → ``started_by``、
           run_import ``operator`` → ``imported_by``，口径表锚定在
           src/lexical_db.py 模块 docstring，全仓调用点同步清零；
  * RV4-5  users_db._require_actor_roles 实时回库复核（测试见
           tests/test_users_db.py::TestRV45LiveRoleRecheck）；
  * RV4-8  requirements.txt requests>=2.32.4 在场确认；
  * R6-4   lexical_db/_as_int、writing_db/_as_int、
           import_engine/_column_exists 本地副本收敛 db_utils
           （export_center/pipeline_status/media_db/dict_admin_db 上一批
           已收敛，见 tests/test_fx10_fixes.py）。

两层结构（与既有批次测试约定一致）：
  * 结构断言（签名注解 / docstring 口径 / 源码 grep）——本地与 CI 全跑；
  * 行为断言（NUL byte 降级 / 假 cursor 走 as_int 口径）——无库依赖；
  * 涉库断言（org_db.create_project bool 拒绝＋str-int 宽松放行）用假
    cursor，不依赖真实 MySQL。
"""

import ast
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Optional

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import db_utils  # noqa: E402
from src import (  # noqa: E402
    dict_admin_db,
    import_engine,
    lexical_db,
    media_db,
    org_db,
    pipeline_status,
    writing_db,
)

REPO_SRC = Path(PROJECT_ROOT) / "src"
REPO_TESTS = Path(PROJECT_ROOT) / "tests"


# ============================================
# RV3-4：media_db 注解诚实化
# ============================================

class TestRV34MediaAnnotations:
    def test_register_asset_mime_is_optional_str(self):
        """mime 注解 Optional[str]（None 缺省不再与 str 谎注矛盾）。"""
        annotation = inspect.signature(
            media_db.register_asset).parameters["mime"].annotation
        assert annotation == Optional[str]

    def test_sha256_of_file_returns_optional_str(self):
        """_sha256_of_file 返回注解 Optional[str]（读不开返 None 是契约）。"""
        ret = inspect.signature(media_db._sha256_of_file).return_annotation
        assert ret == Optional[str]

    def test_sha256_missing_file_returns_none(self):
        """ OSError 路径（既有行为钉住）：读不开返回 None 不抛。"""
        assert media_db._sha256_of_file(
            "/nonexistent/fxb/no-such-file.png") is None


# ============================================
# RV4-2：sha256 except 扩 (OSError, ValueError)
# ============================================

class TestRV42Sha256ValueError:
    def test_nul_byte_path_returns_none(self):
        """NUL byte 路径：open 抛 ValueError → 捕获降级返回 None（RV4-2）。"""
        # 修复前：ValueError("embedded null byte") 穿透为 traceback；
        # 修复后：与 OSError 同款 fail-closed 降级。
        assert media_db._sha256_of_file("bad\x00path.png") is None
        assert media_db._sha256_of_file(str(Path("dir\x00file"))) is None

    def test_real_file_still_hashes(self, tmp_path):
        """正常文件路径行为不变（sha256 十六进制摘要 64 位）。"""
        target = tmp_path / "ok.png"
        target.write_bytes(b"fxb-fixture-bytes")
        digest = media_db._sha256_of_file(str(target))
        assert isinstance(digest, str) and len(digest) == 64
        int(digest, 16)  # 十六进制可解析


# ============================================
# RV3-8：advance_binding_status 校验顺序
# ============================================

class TestRV38ValidationOrder:
    def test_id_checked_before_status_pair(self, caplog):
        """id 与状态对同时非法时，拒绝文案先报 id（对齐 lexical_db 口径）。"""
        import logging

        with caplog.at_level(logging.ERROR, logger="src.media_db"):
            ok = media_db.advance_binding_status(
                0, "不是状态", "也不是状态")
        assert ok is False
        assert "binding_id" in caplog.text, (
            f"应先校验 id 再校验状态对（RV3-8），实际日志: {caplog.text!r}")

    def test_valid_id_bad_pair_still_rejected(self, caplog):
        """id 合法、状态对非法 → 状态对拒绝文案（顺序换位不丢校验）。"""
        import logging

        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="src.media_db"):
            ok = media_db.advance_binding_status(3, "垃圾态", "另一个态")
        assert ok is False
        assert "非单步对" in caplog.text


# ============================================
# RV3-5：org_db chief_id 走 as_int（bool 不放行）
# ============================================

class _RecordingCursor:
    """假 cursor：记录 SQL；lastrowid 固定（org_db 两段 INSERT 用）。"""

    def __init__(self):
        self.calls = []
        self.lastrowid = 777

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


class _FakeCursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, *args):
        return False


class TestRV35OrgChiefId:
    @pytest.fixture(autouse=True)
    def _fake_db(self, monkeypatch):
        self.cursor = _RecordingCursor()
        self.db_calls = 0

        def _fake_get_db_cursor(autocommit=False):
            self.db_calls += 1
            return _FakeCursorCtx(self.cursor)

        monkeypatch.setattr(org_db, "get_db_cursor", _fake_get_db_cursor)

    def test_bool_chief_rejected_before_db(self):
        """RV3-5 核心：chief_id=True 不再被 isinstance(int) 放行成 1。"""
        # 修复前：isinstance(True, int) 为真 → True<=0 为假 → bool 穿透，
        # chief 被册封到 users.id=1 头上（越权册封面）。
        assert org_db.create_project("bool 项目", True, None) is None
        assert org_db.create_project("bool 项目", False, None) is None
        assert self.db_calls == 0, "校验拒绝不得触库"

    def test_other_dirty_chief_rejected(self):
        """None / 0 / 负数 / 非整值 str / 容器 仍拒绝（口径不变部分钉住）。

        注：非整数值 float（3.5 等）按 as_int 既有口径 int() 截断放行
        （db_utils.as_int 全库同款，非本批新引入），不在拒绝清单。
        """
        for bad in (None, 0, -1, "abc", [], {}):
            assert org_db.create_project("脏值项目", bad, None) is None
        assert self.db_calls == 0

    def test_int_and_loose_int_accepted(self):
        """int 照常；as_int 口径的 int-str/整数值 float 宽松放行（一致口径）。"""
        assert org_db.create_project("宽松项目", 7, ["motion"]) == 777
        assert org_db.create_project("宽松项目2", "8", "motion") == 777
        assert org_db.create_project("宽松项目3", 9.0, None) == 777
        # 两段 INSERT：项目壳 + chief 入册，且传的是清洗后的 int
        assert self.db_calls == 3
        first_params = self.cursor.calls[0][1]
        second_params = self.cursor.calls[1][1]
        assert first_params[-1] == 7
        assert second_params[1] == 7 and second_params[3] == 7

    def test_categories_annotation_present(self):
        """categories 参数有类型注解（RV3-5；Any —— _normalize_categories 接 list/tuple/str/None）。"""
        annotation = inspect.signature(
            org_db.create_project).parameters["categories"].annotation
        assert annotation not in (inspect.Parameter.empty, ""), (
            "categories 参数应有类型注解")


# ============================================
# RV3-6：无变化语义 docstring 互注
# ============================================

class TestRV36NoChangeDocstrings:
    def test_update_draft_mentions_update_example(self):
        """update_draft docstring 互注：无变化=True 与 update_example 相反。"""
        doc = writing_db.update_draft.__doc__ or ""
        assert "update_example" in doc
        assert "无变化" in doc

    def test_update_example_mentions_update_draft(self):
        """update_example docstring 互注：rowcount=1 口径与 update_draft 相反。"""
        doc = lexical_db.update_example.__doc__ or ""
        assert "update_draft" in doc
        assert "无变化" in doc

    def test_semantics_actually_opposite(self, monkeypatch):
        """行为层钉住（假 cursor）：同值更新 update_draft=True / update_example=False。

        update_example：UPDATE rowcount=0 → False（lexical_db 直读 rowcount）；
        update_draft：前置 SELECT 行在位即 True（不依赖 rowcount）。
        """

        class _RowCursor:
            """前置 SELECT 给行（draft 态 / 现值），UPDATE 报 rowcount=0。"""

            def __init__(self, row):
                self._row = row
                self.rowcount = 0

            def execute(self, sql, params=None):
                if sql.strip().upper().startswith("SELECT"):
                    self._current = self._row
                else:
                    self.rowcount = 0  # 同值更新：MySQL 计 0 受影响行

            def fetchone(self):
                return self._current

        class _Ctx:
            def __init__(self, cursor):
                self._cursor = cursor

            def __enter__(self):
                return self._cursor

            def __exit__(self, *args):
                return False

        # update_example：内容与库内同值 → rowcount=0 → False
        ex_cursor = _RowCursor({"content": "同值例证", "source": "corpus",
                                "caption": "", "sort_order": 0})
        monkeypatch.setattr(lexical_db, "get_db_cursor",
                            lambda *a, **k: _Ctx(ex_cursor))
        assert lexical_db.update_example(1, content="同值例证") is False

        # update_draft：行在位（draft 态、作者一致）、同值 → True
        dr_cursor = _RowCursor({"status": "draft", "author_id": 5})
        monkeypatch.setattr(writing_db, "get_db_cursor",
                            lambda *a, **k: _Ctx(dr_cursor))
        assert writing_db.update_draft(
            1, 1, "同值成文", author_id=5) is True


# ============================================
# RV3-7：pipeline_status 注解精度
# ============================================

class TestRV37PipelineAnnotations:
    def test_format_funnel_segments_status_is_dict(self):
        """format_funnel_segments 入参注解 Any → dict（RV3-7）。"""
        annotation = inspect.signature(
            pipeline_status.format_funnel_segments).parameters["status"].annotation
        # pipeline_status 顶部有 from __future__ import annotations，
        # 运行时注解是字符串形态 —— 两种形态都认。
        assert annotation in (dict, "dict")

    def test_none_input_still_tolerated(self):
        """注解收紧后运行时容忍保留（None/非 dict → []，不抛）。"""
        assert pipeline_status.format_funnel_segments(None) == []
        assert pipeline_status.format_funnel_segments("漏斗") == []
        assert pipeline_status.format_funnel_segments([1, 2]) == []

    def test_six_formatters_have_docstrings(self):
        """六个 _format_* 全部有一行 docstring（RV3-7/R6-11 结构断言）。"""
        source = (REPO_SRC / "pipeline_status.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        formatters = {
            node.name: ast.get_docstring(node) is not None
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_format_")
        }
        assert set(formatters) == {
            "_format_admission", "_format_coding", "_format_reliability",
            "_format_clustering", "_format_split_review", "_format_authoring",
        }, f"六格式化器集合漂移: {sorted(formatters)}"
        assert all(formatters.values()), f"缺 docstring: {formatters}"


# ============================================
# RV3-3：操作人参数统一（operator 越轨名清零）
# ============================================

class TestRV33OperatorParamUnification:
    def test_start_batch_param_renamed(self):
        """dict_admin_db.start_batch 末位操作人参数 → started_by。"""
        params = list(inspect.signature(dict_admin_db.start_batch).parameters)
        assert params[-1] == "started_by"
        assert "operator" not in params

    def test_run_import_param_renamed(self):
        """import_engine.run_import 操作人参数 → imported_by。"""
        params = list(inspect.signature(import_engine.run_import).parameters)
        assert params[2] == "imported_by"
        assert "operator" not in params

    def test_no_operator_keyword_calls_left_in_repo(self):
        """全仓 grep：越轨关键字调用清零（列名/文案不算；本文件自除外）。"""
        # 模式动态拼接，避免本测试源码自身命中待查文本
        pattern = re.compile(r"\boperator" + r"=")
        self_path = Path(__file__).resolve()
        leftovers = []
        for base in (REPO_SRC, REPO_TESTS):
            for py in base.rglob("*.py"):
                if py.resolve() == self_path:
                    continue
                for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                    if pattern.search(line):
                        leftovers.append(f"{py.name}:{i}: {line.strip()}")
        assert leftovers == [], "仍有越轨关键字调用残留:\n" + "\n".join(leftovers)

    def test_run_import_guard_message_uses_new_name(self):
        """入口守卫拒绝文案用新名（调用方据 error 文案定位参数）。"""
        result = import_engine.run_import([], {"词目": "verb"}, 0, dry_run=True)
        assert result["ok"] is False
        assert "imported_by" in result["error"]

    def test_convention_table_anchored_in_lexical_db(self):
        """全库口径表锚定 src/lexical_db.py 模块 docstring（RV3-3 声明点）。"""
        doc = lexical_db.__doc__ or ""
        assert "操作人参数口径" in doc
        for name in ("started_by", "imported_by", "reviewed_by", "registered_by",
                     "actor"):
            assert name in doc, f"口径表缺 {name}"


# ============================================
# RV4-8：requests 下限在场
# ============================================

class TestRV48Requirements:
    def test_requests_floor(self):
        """requirements.txt 含 requests>=2.32.4（CVE-2024-35195/47081 修复线）。"""
        text = (Path(PROJECT_ROOT) / "requirements.txt").read_text(encoding="utf-8")
        assert re.search(r"^requests>=2\.32\.4\b", text, re.MULTILINE), (
            "requests>=2.32.4 应在场（RV4-8）")


# ============================================
# R6-4：面内小件副本收敛 db_utils（本批残留三件）
# ============================================

class TestR64ConvergenceFXB:
    def test_lexical_db_as_int_is_db_utils(self):
        assert lexical_db._as_int is db_utils.as_int
        assert lexical_db._as_int(True) is None   # bool 先拦（口径不变）
        assert lexical_db._as_int("7") == 7
        assert lexical_db._as_int(3.0) == 3
        assert lexical_db._as_int("x") is None

    def test_writing_db_as_int_is_db_utils(self):
        assert writing_db._as_int is db_utils.as_int
        assert writing_db._as_int(True) is None
        assert writing_db._as_int("12") == 12

    def test_import_engine_column_exists_is_db_utils(self):
        assert import_engine._column_exists is db_utils.column_exists

        class _Cursor:
            sqls, params, n = [], [], 1

            def execute(self, sql, params=None):
                self.sqls.append(sql)
                self.params.append(params)

            def fetchone(self):
                return {"n": self.n}

        cur = _Cursor()
        assert import_engine._column_exists(cur, "definitions", "import_voided") is True
        assert "information_schema.COLUMNS" in cur.sqls[0]
        assert cur.params[0] == ("definitions", "import_voided")

    def test_no_local_helper_defs_left_in_my_scope(self):
        """AST 扫描：面内模块不再有本地 _as_int/_column_exists 定义。"""
        module_names = ("lexical_db.py", "writing_db.py", "import_engine.py",
                        "media_db.py", "org_db.py", "dict_admin_db.py",
                        "pipeline_status.py", "export_center.py",
                        "registry_db.py", "template_engine.py",
                        "wordforms_db.py", "annotation_flow.py")
        offenders = {}
        for name in module_names:
            tree = ast.parse((REPO_SRC / name).read_text(encoding="utf-8"))
            bad = [
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in ("_as_int", "_column_exists")
            ]
            if bad:
                offenders[name] = bad
        assert offenders == {}, f"仍有本地副本: {offenders}"
