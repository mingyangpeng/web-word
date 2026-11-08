"""RV-1 CSS/布局/可访问性 13 findings 修复锁定（findings_backlog.md「RV-1」节）。

断言分四类（与既有批次测试约定一致，本地/CI 均不碰数据库）：

  * WCAG 数值断言 —— 用 design_system 自身的标准 sRGB 线性化 luminance
    （RV1-5 修正后的公式）实算每个文本/底色组合，全部 ≥4.5:1（文本）
    或 ≥3:1（UI 构件）；
  * 调色板断言 —— 深档色表逐值锁定，旧浅档 hex 不得再以「字面量常量」
    形式回到页面模块（注释/文档允许提及，AST 常量层面拦截）；
  * 结构断言 —— _badge 五份实现收敛、HEADER_*/BODY_* 属性声明化、
    flex-wrap / overflow-wrap / 进度条填充等逐点在场；
  * 已知锚点值断言 —— findings 证据里的实测对比（1.61 / 2.71 / 4.02…）
    反算校验公式本身没有再次写错。

覆盖 findings：RV1-1 ~ RV1-10、RV1-13（RV1-11/RV1-12 的实现点在
src/app.py 搜索栏/折叠按钮，属本批次外模块，不在本文件断言之列）。
"""

import ast
import inspect
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.category_study_page as category_study_page  # noqa: E402
import src.cluster_analysis as cluster_analysis  # noqa: E402
import src.design_system as design_system  # noqa: E402
import src.graph_export as graph_export  # noqa: E402
import src.help_center as help_center  # noqa: E402
import src.lexical_pages as lexical_pages  # noqa: E402
import src.reliability as reliability  # noqa: E402
import src.semantic_search as semantic_search  # noqa: E402
import src.users_admin_page as users_admin_page  # noqa: E402

WCAG_AA_TEXT = 4.5
WCAG_UI = 3.0

# RV1-2 的 10 组「浅档 → 深档」替换（findings 原文清单）。
OLD_TO_DEEP = {
    "#48bb78": "#2f855a",
    "#ed8936": "#c05621",
    "#4299e1": "#2b6cb0",
    "#ecc94b": "#975a16",
    "#a0aec0": "#4a5568",
    "#dd6b20": "#9c4221",
    "#718096": "#4a5568",
    "#e53e3e": "#c53030",
    "#38a169": "#276749",
    "#667eea": "#553c9a",
}

# 页面模块（不含 design_system：其 TEXT_DISABLED=#a0aec0 为 WCAG 1.4.3
# 禁用态豁免值，注释/文档字符串也按口径保留旧值做溯源说明）。
PAGE_MODULES = (
    reliability, cluster_analysis, category_study_page, lexical_pages,
    semantic_search, users_admin_page, graph_export, help_center,
)


def _ratio(fg: str, bg: str) -> float:
    return design_system.check_contrast(fg, bg)[1]


def _string_constants(module) -> list:
    """模块 AST 里全部字符串字面量常量（含 f-string 的字面片段）。"""
    tree = ast.parse(inspect.getsource(module))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            for item in node.values:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    values.append(item.value)
    return values


def _assert_badge_aa(html: str, where: str) -> None:
    """解析徽章/chip HTML 的 background/color 并断言 AA。"""
    m = re.search(r"background(?:-color)?:([^;]+);color:([^;]+);", html)
    assert m, f"{where}: 徽章 HTML 缺 background/color 声明：{html!r}"
    bg, fg = m.group(1).strip(), m.group(2).strip()
    ratio = _ratio(fg, bg)
    assert ratio >= WCAG_AA_TEXT, (
        f"{where}: 白字对底色 {fg} on {bg} = {ratio:.2f}:1 < {WCAG_AA_TEXT}:1"
    )


# ============================================
# RV1-5：对比度校验器公式（标准 sRGB 线性化 luminance）
# ============================================

class TestRv15ContrastMath:
    def test_luminance_endpoints(self):
        assert design_system.relative_luminance("#ffffff") == 1.0
        assert design_system.relative_luminance("#000000") == 0.0

    def test_luminance_primary_channels(self):
        # 线性化后按 0.2126/0.7152/0.0722 加权：纯通道各得自己系数。
        assert abs(design_system.relative_luminance("#ff0000") - 0.2126) < 1e-9
        assert abs(design_system.relative_luminance("#00ff00") - 0.7152) < 1e-9
        assert abs(design_system.relative_luminance("#0000ff") - 0.0722) < 1e-9

    def test_known_evidence_ratios(self):
        """findings 证据里的实测值必须被公式复现（防公式再写错）。"""
        assert abs(_ratio("#ffffff", "#ecc94b") - 1.61) < 0.01   # RV1-1 黄底白字
        assert abs(_ratio("#718096", "#ffffff") - 4.02) < 0.01   # RV1-2 候选灰
        assert abs(_ratio("#48bb78", "#ffffff") - 2.43) < 0.01   # RV1-6 绿字
        assert abs(_ratio("#e53e3e", "#ffffff") - 4.13) < 0.01   # RV1-6 红字
        assert abs(_ratio("#4299e1", "#edf2f7") - 2.71) < 0.01   # RV1-13 进度条

    def test_known_deep_ratios(self):
        """修复后的深档组合逐值达标（含 findings 建议值 10.12 / 7.53）。"""
        assert abs(_ratio("#1a202c", "#ecc94b") - 10.12) < 0.02  # RV1-1 建议深字
        assert abs(_ratio("#4a5568", "#ffffff") - 7.53) < 0.01
        assert abs(_ratio("#2b6cb0", "#edf2f7") - 4.81) < 0.05   # RV1-13 新填充

    def test_check_contrast_symmetric_and_thresholds(self):
        assert _ratio("#ffffff", "#4a5568") == _ratio("#4a5568", "#ffffff")
        ok, ratio = design_system.check_contrast("#767676", "#ffffff")
        assert ok and ratio >= WCAG_AA_TEXT          # WCAG 官方 4.5 锚点灰
        ok_ui, ratio_ui = design_system.check_contrast(
            "#2b6cb0", "#edf2f7", ui_component=True)
        assert ok_ui and ratio_ui >= WCAG_UI

    def test_verify_all_contrasts_all_pass(self):
        results = design_system.verify_all_contrasts()
        failing = {k: v for k, v in results.items()
                   if not k.startswith("TEXT_DISABLED") and not v[0]}
        assert failing == {}


# ============================================
# RV1-1/RV1-2：调色板深档 + 徽章自动选深/浅字
# ============================================

class TestRv12Palette:
    def test_semantic_colors_are_deep(self):
        """语义色表逐值锁定深档（白字 ≥4.5:1）。"""
        expected = {
            "PRIMARY_COLOR": "#4a5568",
            "SECONDARY_COLOR": "#2c5282",
            "SUCCESS_COLOR": "#2f855a",
            "ERROR_COLOR": "#c53030",
            "WARNING_COLOR": "#c05621",
            "DANGER_COLOR": "#c53030",
            "INFO_COLOR": "#2b6cb0",
            "HIGHLIGHT_COLOR": "#975a16",
        }
        for name, deep in expected.items():
            value = getattr(design_system, name).lower()
            assert value == deep, f"{name} 应为深档 {deep}，实际 {value}"
            assert _ratio("#ffffff", value) >= WCAG_AA_TEXT, name

    def test_review_status_colors_aa(self):
        for state, color in design_system.REVIEW_STATUS_COLORS.items():
            assert _ratio("#ffffff", color) >= WCAG_AA_TEXT, state
        assert design_system.REVIEW_STATUS_COLORS["候选"] == "#4a5568"
        assert design_system.REVIEW_STATUS_COLORS["审定"] == "#2b6cb0"
        assert design_system.REVIEW_STATUS_COLORS["发布"] == "#2f855a"

    def test_no_old_light_hex_as_literal_in_pages(self):
        """旧浅档 hex 不得再以字面量常量回到页面模块（AST 层面，注释豁免）。"""
        old = {k.lower() for k in OLD_TO_DEEP}
        for module in PAGE_MODULES:
            offenders = [s for s in _string_constants(module)
                         if s.lower() in old]
            assert offenders == [], (
                f"{module.__name__} 仍有旧浅档字面量：{offenders}"
            )

    def test_no_hardcoded_white_text_in_badge_helpers(self):
        """徽章/chip 实现不再写死白字（RV1-2 收敛点逐个查）。"""
        for fn in (lexical_pages._badge, users_admin_page._badge,
                   cluster_analysis._badge, category_study_page._badge,
                   semantic_search._chip):
            src = inspect.getsource(fn)
            assert "color:#fff" not in src.replace(" ", ""), (
                f"{fn.__module__}.{fn.__name__} 仍写死白字"
            )


class TestRv11BadgeAutoText:
    def test_pick_readable_text_color(self):
        assert design_system.pick_readable_text_color("#ecc94b") == "#1a202c"
        assert design_system.pick_readable_text_color("#4a5568") == "#ffffff"
        assert design_system.pick_readable_text_color("#975a16") == "#ffffff"

    def test_get_badge_style_auto_text_aa(self):
        """get_badge_style 对任意底色输出都 ≥4.5:1（浅底深字/深底白字）。"""
        for bg in ("#ecc94b", "#975a16", "#48bb78", "#4a5568", "#ffffff",
                   "#f7fafc", "#2b6cb0", "#c05621"):
            _assert_badge_aa(
                re.sub(r"\s+", "", design_system.get_badge_style(bg)),
                f"get_badge_style({bg})")

    def test_iaa_badge_css_main_and_fallback_aa(self):
        """reliability 口径徽章：主路径（design_system）与降级分支都 ≥4.5:1。"""
        main = re.sub(r"\s+", "", reliability._badge_css())
        _assert_badge_aa(main, "reliability._badge_css 主路径")
        fallback_src = inspect.getsource(reliability._badge_css)
        m = re.search(
            r"background-color:(#[0-9a-fA-F]{6});color:(#[0-9a-fA-F]{6})",
            fallback_src)
        assert m, "降级分支缺 background-color/color 声明"
        ratio = _ratio(m.group(2), m.group(1))
        assert ratio >= WCAG_AA_TEXT, (
            f"降级分支 {m.group(2)} on {m.group(1)} = {ratio:.2f}:1")

    def test_badge_html_all_caller_colors_aa(self):
        """各页全部徽章底色经统一实现渲染后都 AA（RV1-2/RV1-7 徽章群）。"""
        color_maps = {
            "REVIEW_STATUS": design_system.REVIEW_STATUS_COLORS.values(),
            "ROLE_BADGE": users_admin_page.ROLE_BADGE_COLORS.values(),
            "STATE_BADGE": lexical_pages.STATE_BADGE_COLORS.values(),
            "VERDICT": category_study_page.VERDICT_COLORS.values(),
            "STATUS": category_study_page.STATUS_COLORS.values(),
            "TIER": cluster_analysis.TIER_COLORS.values(),
        }
        singles = (
            lexical_pages.MERGED_BADGE_COLOR,
            cluster_analysis.MEDOID_COLOR,
            cluster_analysis.LOCKED_COLOR,
            users_admin_page._ACTIVE_GREEN,
            users_admin_page._INACTIVE_RED,
            "#805ad5",   # 语体/标注紫（白字 4.84:1 本就达标，锁定防回退）
            "#6b46c1",   # 编码紫
            "#2b6cb0", "#c05621",
        )
        colors = [c for seq in color_maps.values() for c in seq] + list(singles)
        for color in colors:
            _assert_badge_aa(design_system.get_badge_html("x", color),
                             f"get_badge_html(x, {color})")

    def test_page_badges_delegate_to_design_system(self):
        """四份页内 _badge 收敛为 design_system.get_badge_html 单一实现。"""
        for fn in (lexical_pages._badge, users_admin_page._badge,
                   cluster_analysis._badge, category_study_page._badge):
            text, color = "发布", "#2f855a"
            assert fn(text, color) == design_system.get_badge_html(text, color), (
                f"{fn.__module__}.{fn.__name__} 未收敛到 get_badge_html"
            )


# ============================================
# RV1-3：暗色主题浅底容器补深字
# ============================================

class TestRv13DarkThemeLightSurfaces:
    def test_design_system_card_has_dark_text(self):
        style = design_system.get_card_style()
        assert f"color: {design_system.TEXT_COLOR}" in style
        assert design_system.TEXT_COLOR == "#1a202c"

    def test_reliability_fallback_card_has_dark_text(self):
        src = inspect.getsource(reliability)
        # 模块级 ImportError 降级分支的 get_card_style 也要带 color:#1a202c。
        assert "color: #1a202c" in src

    def test_cluster_card_container_has_dark_text(self):
        src = inspect.getsource(
            category_study_page._render_cluster_card)
        assert "color:#1a202c" in src.replace(" ", "")


# ============================================
# RV1-4：字号层级常量属性声明化
# ============================================

class TestRv14FontConstants:
    PROP_RE = re.compile(
        r"^(font-size: [\d.]+rem; font-weight: \d{3}; line-height: [\d.]+;)$")

    def test_constants_are_property_declarations(self):
        for name in ("HEADER_H1", "HEADER_H2", "HEADER_H3", "HEADER_H4",
                     "BODY_SM", "BODY_BASE", "BODY_LG"):
            value = getattr(design_system, name)
            assert self.PROP_RE.match(value), f"{name} 非属性声明：{value!r}"
            assert "system-ui" not in value  # font 简写的字体族已移除
            assert f"style='{value}'" .count("'") == 2  # 可直接内插 style 属性

    def test_reliability_fallback_headers_synced(self):
        assert "font-size: 2.5rem; font-weight: 700; line-height: 1.2;" \
            in inspect.getsource(reliability)
        # 旧 font 简写不得再以字面量常量存在（注释里的溯源说明豁免）。
        assert not any("system-ui" in s and "bold" in s
                       for s in _string_constants(reliability))

    def test_header_call_sites_interpolate_directly(self):
        """各页既有调用点（style='{HEADER_*}'）无需改动即恢复生效。"""
        assert f"<h1 style='{design_system.HEADER_H1}'>" .startswith("<h1 style='font-size:")


# ============================================
# RV1-6/RV1-7：状态/警示彩字与卡片正文彩字深档
# ============================================

class TestRv16StatusTextColors:
    def test_reliability_verdict_colors_aa(self):
        src = inspect.getsource(reliability.render_reliability_page)
        colors = re.findall(r"<span style='color:(#[0-9a-fA-F]{6})'>", src)
        assert len(colors) >= 3, f"状态彩字少于 3 处：{colors}"
        for color in colors:
            assert _ratio(color, "#ffffff") >= WCAG_AA_TEXT, color

    def test_reliability_chart_colors_deep(self):
        src = inspect.getsource(reliability._per_feature_chart)
        assert "#c53030" in src and "#2f855a" in src and "#c05621" in src
        # 字面量常量层面拦截（注释里的旧值溯源说明豁免）。
        constants = " ".join(_string_constants(reliability))
        for old in ("#e53e3e", "#48bb78", "#ed8936"):
            assert old not in constants, old

    def test_gray_caption_text_deep_in_pages(self):
        """卡片正文灰字 #718096 → #4a5568（users_admin / category_study）。"""
        for fn in (users_admin_page._metrics_row,
                   category_study_page._render_cluster_card,
                   category_study_page._render_zh_dict_evidence,
                   category_study_page._render_en_dict_evidence):
            src = inspect.getsource(fn)
            assert "color:#718096" not in src.replace(" ", ""), fn.__name__
        src = inspect.getsource(users_admin_page._metrics_row)
        assert "color:#4a5568" in src.replace(" ", "")

    def test_graph_export_card_gray_text_deep(self):
        """graph_export 单文件 HTML（白底卡）的 .k/.s 灰字深档。"""
        src = inspect.getsource(graph_export)
        assert "#bar .s { color: #4a5568" in src
        assert "#card-body .k { color: #4a5568" in src
        # 无任何 CSS 颜色声明再取旧灰（注释里的溯源说明豁免）。
        assert not re.search(r"color:\s*#718096", src)

    def test_role_badge_colors_all_aa(self):
        for role, color in users_admin_page.ROLE_BADGE_COLORS.items():
            assert _ratio("#ffffff", color) >= WCAG_AA_TEXT, role
        assert users_admin_page.ROLE_BADGE_COLORS["editor"] == "#9c4221"
        assert users_admin_page._INACTIVE_RED == "#c53030"

    def test_state_badge_colors_deep(self):
        assert lexical_pages.STATE_BADGE_COLORS[lexical_pages.STATE_NONE] \
            == "#4a5568"
        assert lexical_pages.MERGED_BADGE_COLOR == "#c53030"
        assert lexical_pages.STATUS_BADGE_COLORS is \
            design_system.REVIEW_STATUS_COLORS


# ============================================
# RV1-8：320px 移动端 flex-wrap
# ============================================

class TestRv18MobileFlex:
    def test_schema_alignment_rows_wrap(self):
        src = inspect.getsource(
            category_study_page._render_schema_alignment)
        assert "flex-wrap:wrap" in src.replace(" ", "")


# ============================================
# RV1-9：表格单元格 overflow-wrap
# ============================================

class TestRv19OverflowWrap:
    def test_design_system_table_styles_wrap(self):
        for style in (design_system.get_table_row_style(),
                      design_system.get_table_cell_style()):
            assert "overflow-wrap: anywhere" in style

    def test_page_tables_inherit_wrap(self):
        """页内 <td> 拼的是 get_table_row_style()，随单一实现一并生效。"""
        assert "get_table_row_style()" in inspect.getsource(lexical_pages)
        assert "get_table_row_style()" in inspect.getsource(users_admin_page)


# ============================================
# RV1-10：get_section_spacing 独立渲染 + 裸声明串
# ============================================

class TestRv10SectionSpacing:
    def test_returns_renderable_div(self):
        html = design_system.get_section_spacing()
        assert html.startswith("<div style=\"margin-top: 32px;")
        assert html.endswith("margin-bottom: 32px;\"></div>")

    def test_bare_style_constant_same_values(self):
        assert design_system.SECTION_SPACING_STYLE == (
            "margin-top: 32px; margin-bottom: 32px;")

    def test_docstring_warns_against_style_attr_misuse(self):
        assert "RV1-10" in design_system.get_section_spacing.__doc__


# ============================================
# RV1-13：画像进度条填充
# ============================================

class TestRv13ProgressFill:
    def test_fill_is_deep_blue(self):
        src = inspect.getsource(category_study_page._render_profile_bars)
        assert "background:#2b6cb0" in src.replace(" ", "")
        assert "background:#4299e1" not in src.replace(" ", "")

    def test_fill_meets_ui_contrast_on_track(self):
        assert _ratio("#2b6cb0", "#edf2f7") >= WCAG_UI


# ============================================
# 语义色常量引用链（WARNING/INFO/SUCCESS 间接修复的页面）
# ============================================

class TestRv16IndirectPages:
    def test_help_center_warning_text_uses_deep_constant(self):
        """help_center 彩字经 WARNING_COLOR 常量，换深档后自动达标。"""
        src = inspect.getsource(help_center)
        assert "WARNING_COLOR" in src
        assert _ratio(design_system.WARNING_COLOR, "#ffffff") >= WCAG_AA_TEXT

    def test_semantic_search_chip_colors_all_aa(self):
        for color in semantic_search._GROUP_COLORS.values():
            _assert_badge_aa(semantic_search._chip("P", color), f"chip {color}")
