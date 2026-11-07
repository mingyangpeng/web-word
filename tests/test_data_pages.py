"""数据工具页面模块（Agent G：导入向导 + 词条浏览器）单元测试。

不依赖数据库：只测纯函数（GUIDE 结构、LIKE 通配符转义、分页计算、sha256、
角色门判定、预览防护复用）与源码级契约（CSV 防护复用、widget key 前缀）。
两个渲染入口需要 Streamlit 运行时与 MySQL，且页面未接线进 app.py（集成步骤
归属集成批次），渲染级验证由集成后的 app 级测试承担（tests/test_pages.py
同口径），本文件不重复。
"""

import hashlib
import inspect
import io

import pandas as pd
import pytest

from src import data_pages, security


# ============================================
# GUIDE 结构（契约 §5 四段式）
# ============================================

class TestGuideStructure:
    """GUIDE 必须是契约要求的四段式 dict（集成时原样并入 PAGE_GUIDES）。"""

    def test_required_keys(self):
        assert set(data_pages.GUIDE.keys()) == {
            "label", "purpose", "principle", "data_source", "steps", "notes",
        }

    def test_label_fixed(self):
        """label 固定为「🧰 数据工具」（集成侧边栏与 emoji 白名单按此对齐）。"""
        assert data_pages.GUIDE["label"] == "🧰 数据工具"

    def test_purpose_is_nonempty_str(self):
        purpose = data_pages.GUIDE["purpose"]
        assert isinstance(purpose, str) and purpose.strip()

    @pytest.mark.parametrize("key", ["principle", "data_source", "steps", "notes"])
    def test_list_sections(self, key):
        section = data_pages.GUIDE[key]
        assert isinstance(section, list) and section
        assert all(isinstance(item, str) and item.strip() for item in section)

    def test_steps_at_least_three(self):
        assert len(data_pages.GUIDE["steps"]) >= 3

    def test_honest_annotations_present(self):
        """如实口径必须写进 GUIDE：本期只登记批次、业务写入在批次 3、coverage 待补。"""
        full_text = "".join(
            "".join(data_pages.GUIDE[key]) for key in
            ("purpose", "principle", "data_source", "steps", "notes")
        )
        assert "批次 3" in full_text
        assert "待补" in full_text
        assert "revert_log" in full_text


# ============================================
# 搜索词清洗：_escape_like / _like_pattern（防 LIKE 通配符注入）
# ============================================

class TestEscapeLike:
    """% _ ! 转义（配合 SQL 侧 ESCAPE '!'），防通配符注入。"""

    def test_plain_text_untouched(self):
        assert data_pages._escape_like("run") == "run"
        assert data_pages._escape_like("跑进来") == "跑进来"
        assert data_pages._escape_like("a-b c") == "a-b c"

    def test_percent_escaped(self):
        assert data_pages._escape_like("%") == "!%"
        assert data_pages._escape_like("100%") == "100!%"

    def test_underscore_escaped(self):
        assert data_pages._escape_like("_") == "!_"
        assert data_pages._escape_like("a_b") == "a!_b"

    def test_escape_char_itself_escaped_first(self):
        """转义字符 '!' 自身必须先转义，否则后续转义可被构造绕过。"""
        assert data_pages._escape_like("!") == "!!"
        # "!%" 若先转义 % 会得到 "!!%"（= 字面 '!' + 字面 % 的错位），
        # 正确结果是 "!!!%"（'!'→'!!'、'%'→'!%'）。
        assert data_pages._escape_like("!%") == "!!!%"
        assert data_pages._escape_like("%_!") == "!%!_!!"

    def test_mixed_term(self):
        assert data_pages._escape_like("a%b_c!d") == "a!%b!_c!!d"

    def test_backslash_not_escaped(self):
        """显式 ESCAPE '!' 下反斜杠无特殊含义，保持字面。"""
        assert data_pages._escape_like("a\\b") == "a\\b"

    def test_empty_and_non_string(self):
        assert data_pages._escape_like("") == ""
        assert data_pages._escape_like(None) == ""
        assert data_pages._escape_like(5) == ""
        assert data_pages._escape_like(["%"]) == ""


class TestLikePattern:
    """搜索词 → LIKE 模式串：strip + 截断 + 转义 + 通配符后缀。"""

    def test_prefix_mode(self):
        assert data_pages._like_pattern("run", prefix_only=True) == "run%"

    def test_substring_mode(self):
        assert data_pages._like_pattern("run", prefix_only=False) == "%run%"

    def test_wildcards_neutralized(self):
        """恶意通配符必须被字面化，不能扩大匹配范围。"""
        assert data_pages._like_pattern("%run%", True) == "!%run!%%"  # 末尾 % 是前缀通配符
        assert data_pages._like_pattern("%run%", False) == "%!%run!%%"
        assert data_pages._like_pattern("a_b", True) == "a!_b%"

    def test_whitespace_stripped(self):
        assert data_pages._like_pattern("  run  ", True) == "run%"

    def test_truncated_before_escape(self):
        long_term = "a" * 60 + "%"
        pattern = data_pages._like_pattern(long_term, True)
        # 截断发生在转义之前：只保留前 50 个原始字符（末尾 % 被截掉），
        # 不会出现「截断把转义对拦腰斩断」的悬空 '!'
        assert pattern == "a" * 50 + "%"

    def test_empty_term_no_wildcard_only_pattern(self):
        """空词绝不生成匹配全表的 % / %% 模式。"""
        for term in ("", "   ", None, 42):
            assert data_pages._like_pattern(term, True) == ""
            assert data_pages._like_pattern(term, False) == ""

    def test_default_is_prefix(self):
        assert data_pages._like_pattern("run") == "run%"


# ============================================
# 分页计算
# ============================================

class TestPagination:
    def test_total_pages(self):
        assert data_pages._total_pages(0, 20) == 1
        assert data_pages._total_pages(1, 20) == 1
        assert data_pages._total_pages(20, 20) == 1
        assert data_pages._total_pages(21, 20) == 2
        assert data_pages._total_pages(41, 20) == 3

    def test_total_pages_bad_input(self):
        assert data_pages._total_pages(None, 20) == 1
        assert data_pages._total_pages(-5, 20) == 1
        assert data_pages._total_pages(100, 0) == 1  # 非法 page_size 不除零

    def test_clamp_page(self):
        assert data_pages._clamp_page(1, 5) == 1
        assert data_pages._clamp_page(3, 5) == 3
        assert data_pages._clamp_page(9, 5) == 5
        assert data_pages._clamp_page(0, 5) == 1
        assert data_pages._clamp_page(-2, 5) == 1

    def test_clamp_page_bad_input(self):
        assert data_pages._clamp_page(None, 3) == 1
        assert data_pages._clamp_page("2", 3) == 2
        assert data_pages._clamp_page(2, None) == 1
        assert data_pages._clamp_page(2.0, 4) == 2

    def test_page_size_constant_is_twenty(self):
        """契约口径：每页 20（改动需同步帮助文档与测试）。"""
        assert data_pages.PAGE_SIZE == 20


# ============================================
# sha256 指纹
# ============================================

class TestSha256:
    def test_known_vector(self):
        assert data_pages._sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()
        assert data_pages._sha256_bytes(b"abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_empty_input(self):
        assert data_pages._sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()
        assert data_pages._sha256_bytes(None) == hashlib.sha256(b"").hexdigest()

    def test_hex_format(self):
        digest = data_pages._sha256_bytes("字符串".encode("utf-8"))
        assert len(digest) == 64
        int(digest, 16)  # 64 位十六进制（dict_admin_db._clean_sha256 的入库口径）


# ============================================
# 角色门判定（导入页仅词典管理员；过渡判定 role == "admin"）
# ============================================

class TestRoleGate:
    def test_transitional_admin_role(self):
        assert data_pages._is_dict_admin({"id": 1, "role": "admin"}) is True

    def test_direct_dict_admin_role(self):
        assert data_pages._is_dict_admin({"role": "dict_admin"}) is True

    def test_roles_list_contains_dict_admin(self):
        assert data_pages._is_dict_admin(
            {"role": "viewer", "roles": ["viewer", "dict_admin"]}
        ) is True

    def test_non_admin_roles_rejected(self):
        assert data_pages._is_dict_admin({"role": "annotator"}) is False
        assert data_pages._is_dict_admin({"role": "reviewer"}) is False
        assert data_pages._is_dict_admin({"role": "viewer"}) is False
        assert data_pages._is_dict_admin({"role": "sys_admin"}) is False

    def test_sys_admin_only_not_dict_admin(self):
        """平台管理员不碰业务数据（§15 导入同权）：仅 sys_admin 不放行。"""
        assert data_pages._is_dict_admin(
            {"role": "viewer", "roles": ["sys_admin"]}
        ) is False

    def test_bad_input_rejected(self):
        assert data_pages._is_dict_admin(None) is False
        assert data_pages._is_dict_admin({}) is False
        assert data_pages._is_dict_admin("admin") is False


# ============================================
# CSV 公式注入防护复用（预览必须与导出同源）
# ============================================

class TestCsvProtectionReuse:
    """预览防护必须复用 src/security.py 的唯一实现（源码级 + 对象级双断言）。"""

    def test_object_identity_with_security_module(self):
        """模块导入的就是 security 的同一函数对象（无第二份实现）。"""
        assert data_pages.sanitize_csv_dataframe is security.sanitize_csv_dataframe
        assert data_pages._sanitize_preview is not None

    def test_source_level_import(self):
        """源码级检查：from src.security import sanitize_csv_dataframe 在场。"""
        source = inspect.getsource(data_pages)
        assert "from src.security import sanitize_csv_dataframe" in source
        assert "_sanitize_preview" in source  # 预览确实走该封装

    def test_preview_sanitize_behavior(self):
        """= + - @ 等开头单元格按既有实现处理（前置单引号）。"""
        df = pd.DataFrame({
            "verb": ["run", "=HYPERLINK(\"http://evil\")"],
            "note": ["正常中文", "+cmd|' /C calc"],
            "rating": [5, -1],
        })
        out = data_pages._sanitize_preview(df)
        assert out.loc[0, "verb"] == "run"
        assert out.loc[0, "note"] == "正常中文"
        assert out.loc[1, "verb"].startswith("'=")
        assert out.loc[1, "note"].startswith("'+")
        assert out.loc[1, "rating"] == -1  # 数字列不受影响

    def test_preview_sanitize_does_not_mutate_input(self):
        df = pd.DataFrame({"feedback_text": ["=cmd"]})
        out = data_pages._sanitize_preview(df)
        assert df.loc[0, "feedback_text"] == "=cmd"
        assert out.loc[0, "feedback_text"] == "'=cmd"

    def test_changed_cell_count(self):
        df = pd.DataFrame({
            "a": ["run", "=cmd", "@x"],
            "b": [1, 2, 3],
        })
        assert data_pages._changed_cell_count(df, data_pages._sanitize_preview(df)) == 2
        assert data_pages._changed_cell_count(df, df.copy()) == 0


# ============================================
# 上传解析（csv / xlsx；openpyxl 直读兜底）
# ============================================

class TestReadTabular:
    """_read_tabular：xlsx 走 pandas→openpyxl 兜底，csv 走 pandas。"""

    def _xlsx_bytes(self, rows):
        openpyxl = pytest.importorskip("openpyxl")
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        for row in rows:
            worksheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def test_csv_parse(self):
        data = "verb,note\nrun,正常\n,=cmd\n".encode("utf-8")
        df = data_pages._read_tabular(data, "words.csv")
        assert df is not None and list(df.columns) == ["verb", "note"]
        assert len(df) == 2
        assert df.loc[0, "verb"] == "run" and df.loc[0, "note"] == "正常"

    def test_csv_empty_fields_are_strings(self):
        """keep_default_na=False：空单元格是空串而不是 NaN（预览干净）。"""
        df = data_pages._read_tabular(b"verb,note\nrun,\n", "words.csv")
        assert df.loc[0, "note"] == ""

    def test_xlsx_parse_with_fallback(self):
        """pandas 对 openpyxl 有最低版本硬检查；无论走 pandas 还是直读兜底，
        解析结果必须一致（公式原文保留）。"""
        data = self._xlsx_bytes([["verb", "note"], ["jump", "=SUM(A1)"], ["swim", "正常"]])
        df = data_pages._read_tabular(data, "words.xlsx")
        assert df is not None and list(df.columns) == ["verb", "note"]
        assert len(df) == 2
        assert df.loc[0, "note"] == "=SUM(A1)"
        assert df.loc[1, "note"] == "正常"

    def test_unsupported_extension_returns_none(self):
        assert data_pages._read_tabular(b"whatever", "doc.docx") is None
        assert data_pages._read_tabular(b"whatever", "") is None

    def test_broken_xlsx_returns_none(self):
        """坏 xlsx：pandas 与 openpyxl 直读兜底都失败 → None（页面提示解析失败）。"""
        assert data_pages._read_tabular(b"\x00\x01 garbage", "broken.xlsx") is None

    def test_garbage_csv_yields_zero_rows(self):
        """pandas 对文本非常宽容：垃圾字节按 header-only CSV 解析成 0 行 ——
        页面按「没有数据行」拒绝（_render_preview 的 rows_total<=0 分支）。"""
        df = data_pages._read_tabular(b"\x00\x01 garbage", "broken.csv")
        assert df is not None and len(df) == 0

    def test_header_only_csv_yields_zero_rows(self):
        df = data_pages._read_tabular(b"verb,note\n", "words.csv")
        assert df is not None and len(df) == 0


# ============================================
# 模块级契约（widget key 前缀 / 渲染入口签名）
# ============================================

class TestModuleContract:
    def test_widget_key_prefixes(self):
        assert data_pages.KEY_IMPORT_PREFIX == "data_import_"
        assert data_pages.KEY_BROWSER_PREFIX == "data_browser_"

    def test_source_uses_prefixed_widget_keys(self):
        """源码中所有字面 key= 键名都必须挂统一前缀（f-string 键由前缀常量保证）。"""
        source = inspect.getsource(data_pages)
        assert 'KEY_IMPORT_PREFIX}' in source
        assert 'KEY_BROWSER_PREFIX}' in source

    def test_render_entry_points_exist(self):
        assert callable(data_pages.render_import_page)
        assert callable(data_pages.render_browser_page)

    def test_read_only_helpers_are_private(self):
        """查询封装为本模块私有函数（契约：参数化 SQL、docstring 注明只读）。"""
        for name in ("_search_definitions", "_senses_for_verbs",
                     "_list_recent_batches", "_definitions_source_column"):
            fn = getattr(data_pages, name)
            assert callable(fn)
            assert name.startswith("_")
            assert "只读" in inspect.getdoc(fn)

    def test_queries_parameterized_no_fstring_values(self):
        """SQL 纪律源码级抽查：查询辅助内的动态片段只允许白名单列名拼接。"""
        source = inspect.getsource(data_pages)
        assert "SOURCE_COLUMN_CANDIDATES" in source  # 动态列名有白名单约束
        assert "LIKE %s ESCAPE '!'" in source        # LIKE 走参数 + 显式转义字符

    def test_batch_3_wiring_flags_in_module_docstring(self):
        """模块 docstring 注明本期只登记批次、业务表写入在批次 3。"""
        doc = inspect.getdoc(data_pages) or ""
        assert "批次 3" in doc
        assert "rows_ok=0" in doc
