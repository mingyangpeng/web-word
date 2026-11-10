"""
Design System Module for Web-Word Verb Definition Optimizer

This module provides a centralized design system for the Streamlit application,
including color definitions, spacing system, font system, and reusable component
style functions.

Purpose:
- Maintain visual consistency across the application
- Provide standardized styling functions for UI components
- Enable easy design system updates without code changes
- Support accessibility standards (WCAG AA)

Author: Claude Code
Date: 2026/05/26
"""

# ============================================================================
# Color System
# ============================================================================
# Color palette based on blue-gray theme with semantic colors.
#
# RV1-1/RV1-2（WCAG AA 系统性修复）：文本/徽章全部取「深档」色值 —— 每个色值
# 与白色文字的对比度均 ≥4.5:1（比值由下方 check_contrast 的标准 sRGB 线性化
# 公式实算，见 tests/test_rv1_fixes.py 全表断言）。旧浅档（#48bb78/#ed8936/
# #4299e1/#ecc94b/#a0aec0/#dd6b20/#718096/#e53e3e/#38a169/#667eea）白字
# 对比 1.61~4.13:1 全不达 AA，已整体退役。

# Primary colors (all pass WCAG AA with white text, >= 4.5:1)
PRIMARY_COLOR = "#4a5568"      # Gray 700 - Main action buttons, active states (白字 7.53:1)
SECONDARY_COLOR = "#2c5282"    # Blue 900 - Secondary actions, highlights (白字 7.97:1；旧 #63b3ed 白字仅 2.13:1)
SUCCESS_COLOR = "#2f855a"      # Green 700 - Success messages, positive feedback (白字 4.54:1；旧 #48bb78 2.43:1)
ERROR_COLOR = "#c53030"        # Red 700 - Error messages, negative feedback (白字 5.47:1；旧 #e53e3e 4.13:1)
WARNING_COLOR = "#c05621"      # Orange 700 - Warning messages, attention (白字 4.57:1；旧 #ed8936 2.55:1)

# Semantic colors
BACKGROUND_COLOR = "#ffffff"   # White - Main page background
CARD_COLOR = "#f7fafc"         # Gray 100 - Card backgrounds, containers
TEXT_COLOR = "#1a202c"         # Gray 900 - Main text, headings
TEXT_SECONDARY = "#4a5568"     # Gray 700 - Secondary text, descriptions
# Disabled text/placeholder（WCAG 1.4.3 对禁用态文本豁免，不参与 AA 断言）。
# 徽章/状态底色一律不得再用本值 —— 用 TEXT_SECONDARY（#4a5568，白字 7.53:1）。
TEXT_DISABLED = "#a0aec0"      # Gray 400 - Disabled text, placeholders
BORDER_COLOR = "#e2e8f0"       # Gray 200 - Borders, dividers

# Special purpose colors
DANGER_COLOR = "#c53030"       # Red 700 - Critical errors
INFO_COLOR = "#2b6cb0"         # Blue 700 - Informational messages (白字 5.42:1；旧 #4299e1 3.05:1)
HIGHLIGHT_COLOR = "#975a16"    # Yellow 700 (深档) - Highlights, badges (白字 5.54:1；旧 #ecc94b 1.61:1)

# 审定三态徽章配色（R6-5 单份事实源）：候选灰 / 审定蓝 / 发布绿。
# 媒体绑定（词典管理区媒体库）与例证（编纂成文区）共用同一条审定链
# （候选→审定→发布），徽章配色此前在 dict_admin_pages / lexical_pages
# 各留一份且「审定」蓝值漂移（#4299e1 白字对比不足 WCAG AA）—— 统一取
# lexical_pages 的深蓝 #2b6cb0（白字对比 ≥4.5:1）。
# RV1-2：「候选」灰 #718096 白字实测 4.02:1 不达 AA，深档换 #4a5568
# （白字 7.53:1）；发布绿同步取 AA 档 #2f855a（白字 4.54:1）。
REVIEW_STATUS_COLORS = {
    "候选": "#4a5568",   # Gray 700 - candidate（白字 7.53:1）
    "审定": "#2b6cb0",   # Blue 700 - reviewed（白字 5.42:1）
    "发布": "#2f855a",   # Green 700 - published（白字 4.54:1）
}

# ============================================================================
# Spacing System (8px base unit)
# ============================================================================
# All spacing values are multiples of 8px for consistency

SPACE_XS = 8    # Extra small: 8px (tight spacing, icon-only buttons)
SPACE_SM = 16   # Small: 16px (inline elements, small gaps)
SPACE_MD = 24   # Medium: 24px (default spacing, button groups)
SPACE_LG = 32   # Large: 32px (section spacing, card padding)
SPACE_XL = 48   # Extra large: 48px (section spacing, page sections)

# ============================================================================
# Font System
# ============================================================================
# Typography scale based on system fonts with consistent line heights

# Font families
FONT_FAMILY_BASE = ("system-ui, -apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif")
FONT_FAMILY_MONO = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
                    "'Liberation Mono', monospace")

# Header sizes (h1-h4).
# RV1-4（P2）：旧值是 CSS font 简写（"bold 2.5rem/1.2 system-ui"），调用点一律
# 以 `style='{HEADER_H1}'` 插值 —— 简写值放进 style 属性不是合法声明序列，
# 浏览器整条丢弃，字号层级 120 处调用全部失效。现改为独立属性声明插值，
# 值本身即合法 CSS，所有调用点无需改动即恢复生效。
HEADER_H1 = "font-size: 2.5rem; font-weight: 700; line-height: 1.2;"
HEADER_H2 = "font-size: 2rem; font-weight: 700; line-height: 1.3;"
HEADER_H3 = "font-size: 1.5rem; font-weight: 700; line-height: 1.4;"
HEADER_H4 = "font-size: 1.25rem; font-weight: 700; line-height: 1.5;"

# Body text sizes（同为独立属性声明，见上 RV1-4 说明）
BODY_SM = "font-size: 0.875rem; font-weight: 400; line-height: 1.5;"   # Small text: 14px
BODY_BASE = "font-size: 1rem; font-weight: 400; line-height: 1.5;"     # Base text: 16px
BODY_LG = "font-size: 1.125rem; font-weight: 400; line-height: 1.6;"   # Large text: 18px

# Line height constants
LINE_HEIGHT_TIGHT = 1.2
LINE_HEIGHT_NORMAL = 1.5
LINE_HEIGHT_RELAXED = 1.6

# ============================================================================
# Component Style Functions
# ============================================================================


def get_button_primary_style() -> str:
    """
    Returns primary button style string for Streamlit.

    Primary buttons are used for main actions (Generate, Submit).
    They use the PRIMARY_COLOR and have high contrast white text.

    Returns:
        CSS style string with color, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_primary_style()
        >>> st.button("Generate", type="primary", **style)
    """
    return f"""
    background-color: {PRIMARY_COLOR};
    color: #ffffff;
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: none;
    font-family: {FONT_FAMILY_BASE};
    font-size: 1rem;
    font-weight: 600;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    """


def get_button_secondary_style() -> str:
    """
    Returns secondary button style string for Streamlit.

    Secondary buttons are used for less prominent actions (Cancel, Download).
    They use the SECONDARY_COLOR and have high contrast white text.

    Returns:
        CSS style string with color, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_secondary_style()
        >>> st.button("Cancel", **style)
    """
    return f"""
    background-color: {SECONDARY_COLOR};
    color: #ffffff;
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: none;
    font-family: {FONT_FAMILY_BASE};
    font-size: 1rem;
    font-weight: 500;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    """


def get_button_outline_style() -> str:
    """
    Returns outline button style string for Streamlit.

    Outline buttons are used for secondary actions or destructive actions.
    They have a colored border with white background.

    Returns:
        CSS style string with border, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_outline_style()
        >>> st.button("Secondary", **style)
    """
    return f"""
    background-color: #ffffff;
    color: {PRIMARY_COLOR};
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: 2px solid {PRIMARY_COLOR};
    font-family: {FONT_FAMILY_BASE};
    font-size: 1rem;
    font-weight: 500;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    """


def get_button_warning_style() -> str:
    """
    Returns warning button style string for Streamlit.

    Warning buttons are used for cautionary actions.
    They use the WARNING_COLOR with dark text for contrast.

    Returns:
        CSS style string with color, padding, border-radius, and hover effects

    Example:
        >>> style = get_button_warning_style()
        >>> st.button("Confirm", type="primary", **style)
    """
    return f"""
    background-color: {WARNING_COLOR};
    color: #ffffff;
    padding: {SPACE_SM}px {SPACE_MD}px;
    border-radius: 8px;
    border: none;
    font-family: {FONT_FAMILY_BASE};
    font-size: 1rem;
    font-weight: 500;
    line-height: {LINE_HEIGHT_NORMAL};
    transition: all 0.2s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    """


def get_card_style() -> str:
    """
    Returns card container style string for Streamlit.

    Cards are used for sections, containers, and content grouping.
    They have a subtle background and rounded corners.

    RV1-3（暗色主题）：卡底是常亮的浅色面（#f7fafc），暗色主题下容器内未显式
    声明颜色的文本会继承主题白字（实测 1.10:1 不可读）。这里统一补
    ``color: #1a202c``，浅底容器内文本两种主题都可读；内部元素仍可用自己的
    颜色声明覆盖。

    Returns:
        CSS style string with background, text color, padding, border-radius,
        and shadow

    Example:
        >>> style = get_card_style()
        >>> with st.container(): st.markdown("Content", unsafe_allow_html=True)
    """
    return f"""
    background-color: {CARD_COLOR};
    color: {TEXT_COLOR};
    padding: {SPACE_MD}px;
    border-radius: 12px;
    border: 1px solid {BORDER_COLOR};
    box-shadow: 0 1px 2px rgba(26, 32, 44, 0.04),
                0 4px 16px rgba(26, 32, 44, 0.06);
    transition: box-shadow 0.2s ease, transform 0.2s ease;
    """


def get_container_style(max_width: int = 1200) -> str:
    """
    Returns main content container style string for Streamlit.

    Main containers have a max-width and centered alignment.
    They use the BACKGROUND_COLOR for the page background.

    Args:
        max_width: Maximum width in pixels (default: 1200)

    Returns:
        CSS style string with max-width, padding, and alignment

    Example:
        >>> style = get_container_style(max_width=1000)
        >>> with st.container(): st.markdown("Content")
    """
    return f"""
    max-width: {max_width}px;
    padding: 0 {SPACE_MD}px;
    margin: 0 auto;
    """


def get_input_field_style() -> str:
    """
    Returns input field style string for Streamlit.

    Input fields have a subtle border, padding, and focus state.
    They use the BORDER_COLOR and TEXT_DISABLED for placeholders.

    Returns:
        CSS style string with border, padding, and focus effects

    Example:
        >>> style = get_input_field_style()
        >>> st.text_input("Label", **style)
    """
    return f"""
    border: 2px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: {SPACE_SM}px;
    font-family: {FONT_FAMILY_BASE};
    font-size: 1rem;
    background-color: #ffffff;
    transition: border-color 0.2s ease;
    """


def get_input_field_focused_style() -> str:
    """
    Returns input field focused style string for Streamlit.

    Focused input fields have a border highlight in PRIMARY_COLOR.
    They include a ring effect for accessibility.

    Returns:
        CSS style string with focus state effects

    Example:
        >>> style = get_input_field_focused_style()
        >>> st.text_input("Label", **style)
    """
    return f"""
    border: 2px solid {PRIMARY_COLOR};
    box-shadow: 0 0 0 3px rgba(74, 85, 104, 0.2);
    outline: none;
    """


def get_table_style() -> str:
    """
    Returns table container style string for Streamlit.

    Tables have a subtle border, padding, and clean appearance.
    They use the BORDER_COLOR for row separators.

    Returns:
        CSS style string with border and padding

    Example:
        >>> style = get_table_style()
        >>> st.dataframe(df, **style)
    """
    return f"""
    border-collapse: collapse;
    width: 100%;
    margin: {SPACE_SM}px 0;
    """


def get_table_header_style() -> str:
    """
    Returns table header style string for Streamlit.

    Table headers use PRIMARY_COLOR with white text for contrast.
    They have a subtle background color.

    Returns:
        CSS style string for table headers

    Example:
        >>> style = get_table_header_style()
        >>> st.table(headers, **style)
    """
    return f"""
    background-color: {PRIMARY_COLOR};
    color: #ffffff;
    font-weight: 600;
    text-align: left;
    padding: {SPACE_SM}px;
    border-bottom: 2px solid {BORDER_COLOR};
    """


def get_table_row_style() -> str:
    """
    Returns table row style string for Streamlit.

    Table rows alternate between white and slightly darker backgrounds.
    They use the BORDER_COLOR for row separators.

    RV1-9（移动端）：全库内联 CSS 原先无 overflow-wrap —— 长英文释义/URL/
    无空格长串在窄屏把表格撑出横向滚动。本样式实际被各页拼进 ``<td>``
    使用，故在此补 ``overflow-wrap: anywhere``，全部表格单元格一并生效。

    Returns:
        CSS style string for table rows

    Example:
        >>> style = get_table_row_style()
        >>> st.table(rows, **style)
    """
    return f"""
    border-bottom: 1px solid {BORDER_COLOR};
    overflow-wrap: anywhere;
    transition: background-color 0.2s ease;
    """


def get_table_cell_style() -> str:
    """
    Returns table cell style string for Streamlit.

    Table cells have padding and maintain consistent alignment.
    They use TEXT_COLOR for text and TEXT_SECONDARY for secondary text.

    Returns:
        CSS style string for table cells

    Example:
        >>> style = get_table_cell_style()
        >>> st.table(cells, **style)
    """
    return f"""
    padding: {SPACE_SM}px;
    color: {TEXT_COLOR};
    font-size: 1rem;
    overflow-wrap: anywhere;
    """


def get_section_spacing() -> str:
    """
    Returns spacing style string for section separators.

    Sections have consistent spacing between major content areas.
    They use the SPACE_LG constant.

    Returns:
        A spacer ``<div>``（可直接传给 st.markdown(..., unsafe_allow_html=True)）。
        之前返回裸 CSS 文本，st.markdown 会把它当正文渲染成可见的一行
        "margin-top: 32px; ..."。

        需要把间距写进**已有元素**的 style 属性时，不要把本函数的返回值
        （完整 ``<div>``）塞进 style —— 那是 RV1-10 的原始缺陷（间距从未
        生效）；应改用 :data:`SECTION_SPACING_STYLE` 裸声明串。

    Example:
        >>> st.markdown(get_section_spacing(), unsafe_allow_html=True)
    """
    return f'<div style="margin-top: {SPACE_LG}px; margin-bottom: {SPACE_LG}px;"></div>'


# RV1-10：与 get_section_spacing() 同一数值的**裸 CSS 声明串**（无标签包装），
# 供 `style='{SECTION_SPACING_STYLE}'` 形式的内联插值使用。
SECTION_SPACING_STYLE = (
    f"margin-top: {SPACE_LG}px; margin-bottom: {SPACE_LG}px;"
)


def pick_readable_text_color(background: str) -> str:
    """
    Pick white or dark text, whichever contrasts better on ``background``.

    RV1-1/RV1-2：徽章底色由调用方传入，白字并非永远可读（旧 #ecc94b 黄底
    白字实测 1.61:1）。按 WCAG sRGB 亮度实算两种候选的前景对比度，取更高者：
    深色底（如 #4a5568）选白字，浅色底（如 #ecc94b）选深字 #1a202c。

    Args:
        background: Hex background color string (e.g. "#ecc94b").

    Returns:
        "#ffffff" 或 "#1a202c"。

    Example:
        >>> pick_readable_text_color("#4a5568")
        '#ffffff'
        >>> pick_readable_text_color("#ecc94b")
        '#1a202c'
    """
    white = check_contrast("#ffffff", background)[1]
    dark = check_contrast("#1a202c", background)[1]
    return "#ffffff" if white >= dark else "#1a202c"


def get_badge_style(color: str = PRIMARY_COLOR) -> str:
    """
    Returns badge style string for Streamlit.

    Badges are used for labels, tags, or status indicators.
    They use the specified color with rounded corners and small padding.

    RV1-1/RV1-2：文字颜色按底色自动选深/浅（不再写死白字）—— 黄底等浅色
    面自动配深字 #1a202c，深色底配白字，任意底色都取两者中对比度更高者。

    Args:
        color: Background color for the badge (default: PRIMARY_COLOR)

    Returns:
        CSS style string for badges

    Example:
        >>> style = get_badge_style(SUCCESS_COLOR)
        >>> st.markdown(f"<span style='{style}'>✅ Verified</span>",
        ...             unsafe_allow_html=True)
    """
    return f"""
    display: inline-block;
    background-color: {color};
    color: {pick_readable_text_color(color)};
    padding: 4px {SPACE_SM}px;
    border-radius: 12px;
    font-size: 0.875rem;
    font-weight: 500;
    line-height: 1.4;
    """


# RV1-2（_badge 收敛）：此前 lexical_pages / users_admin_page / cluster_analysis /
# category_study_page（以及 dict_admin_pages、model_settings_pages）各存一份
# 逐字雷同的 ``_badge``，白字写死、对比度修一处漏四处。现收敛为本模块单一
# 实现：同款小圆角视觉语言 + 按底色自动选深/浅字；调用方传入的 text 必须已
# 经 HTML 转义（原 _badge 契约不变）。
BADGE_HTML_TEMPLATE = (
    '<span style="display:inline-block;background:{color};color:{text_color};'
    'padding:1px 10px;border-radius:10px;font-size:0.78em;'
    'margin-right:4px;">{text}</span>'
)


def get_badge_html(text: str, color: str = PRIMARY_COLOR) -> str:
    """
    Render the small rounded status badge (the former per-page ``_badge``).

    单一实现供各页 ``_badge`` 收敛引用（RV1-2）；视觉语言与旧实现一致
    （inline-block 小圆角徽章），文字颜色按底色自动选深/浅。

    Args:
        text: 已经过 HTML 转义的徽章文本（调用方契约，与旧 ``_badge`` 相同；
            本函数不再转义，避免双重转义）。
        color: 徽章底色（hex）；深色底自动配白字、浅色底自动配深字。

    Returns:
        HTML ``<span>`` 字符串，配合 ``unsafe_allow_html=True`` 使用。

    Example:
        >>> get_badge_html("发布", SUCCESS_COLOR)
        '<span style="display:inline-block;background:#2f855a;color:#ffffff;...'
    """
    return BADGE_HTML_TEMPLATE.format(
        color=color,
        text_color=pick_readable_text_color(color),
        text=text,
    )


# ============================================================================
# Color Utilities
# ============================================================================

def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """
    Convert a hex color constant into a CSS ``rgba(...)`` string.

    CSS does not accept a hex value inside ``rgba()`` — ``rgba(#ffffff, 0.98)``
    is invalid and the browser drops the whole declaration. Interpolating a
    design-system hex constant into a translucent color therefore requires a
    real conversion, which this helper provides.

    Args:
        hex_color: Hex color string, with or without a leading '#'
                   (e.g. "#ffffff", "4a5568").
        alpha: Opacity between 0.0 and 1.0 (default: 1.0).

    Returns:
        CSS color string, e.g. "rgba(255, 255, 255, 0.98)".

    Example:
        >>> background: rgba({hex_to_rgba(BACKGROUND_COLOR, 0.98)});
        background: rgba(255, 255, 255, 0.98);
    """
    value = hex_color.lstrip("#")

    # Support the 3-digit shorthand ("#fff") and the 6-digit form.
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)

    if len(value) != 6:
        raise ValueError(f"Unsupported hex color: {hex_color!r}")

    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


# ============================================================================
# Accessibility Utilities
# ============================================================================

def relative_luminance(hex_color: str) -> float:
    """
    Compute WCAG relative luminance of a hex color (standard sRGB linearization).

    WCAG 2.x 规范公式：先把 0-255 的 sRGB 通道值归一化到 0-1，再做伽马
    线性化（<= 0.04045 除以 12.92，否则 ``((v+0.055)/1.055)^2.4``），最后按
    ``0.2126 R + 0.7152 G + 0.0722 B`` 加权求和。

    RV1-5：旧实现把 0-255 原始通道值直接按系数加权（未线性化），得到的
    "luminance" 不是规范量，全部比值错误、校验表整体误报 FAIL。

    Args:
        hex_color: Hex color string, with or without a leading '#'.

    Returns:
        Relative luminance in [0.0, 1.0].

    Example:
        >>> round(relative_luminance("#ffffff"), 4)
        1.0
        >>> round(relative_luminance("#000000"), 4)
        0.0
    """
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"Unsupported hex color: {hex_color!r}")

    def linearize(channel: int) -> float:
        """sRGB 0-255 通道值 → 线性化 0-1（WCAG 2.x 公式）。"""
        v = channel / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * linearize(r)
            + 0.7152 * linearize(g)
            + 0.0722 * linearize(b))


def check_contrast(
    foreground: str, background: str, ui_component: bool = False,
) -> tuple[bool, float]:
    """
    Check if color contrast meets WCAG AA standards.

    WCAG AA requires:
    - Normal text (< 18pt or < 14pt bold): contrast >= 4.5:1
    - Large text (>= 18pt or >= 14pt bold): contrast >= 3:1
    - UI components / graphical objects: contrast >= 3:1

    亮度按 WCAG 2.x 标准 sRGB 线性化公式计算（:func:`relative_luminance`，
    RV1-5 修正旧实现未线性化导致的全表误报）。

    Args:
        foreground: Hex color string (e.g., "#ffffff", "#1a202c")
        background: Hex color string (e.g., "#ffffff", "#4a5568")
        ui_component: Whether the color is used on a UI component (default: False for text)

    Returns:
        Tuple of (is_compliant, contrast_ratio)
        - is_compliant: True if meets WCAG AA standards
        - contrast_ratio: Contrast ratio (e.g., 7.53 for #4a5568 on white)

    Example:
        >>> ok, ratio = check_contrast("#4a5568", "#ffffff")
        >>> print(f"Contrast ratio: {ratio:.2f}:1")
        >>> print(f"Meets WCAG AA: {ok}")
        >>> # For UI components, use the ui_component parameter:
        >>> ok, ratio = check_contrast("#2b6cb0", "#edf2f7", ui_component=True)
    """
    fg_lum = relative_luminance(foreground)
    bg_lum = relative_luminance(background)

    # Ensure the lighter color is in the numerator (ratio is symmetric).
    lighter, darker = max(fg_lum, bg_lum), min(fg_lum, bg_lum)
    contrast_ratio = (lighter + 0.05) / (darker + 0.05)

    # Determine WCAG AA compliance based on type
    # WCAG AA: 4.5:1 for normal text, 3:1 for UI components
    if ui_component:
        is_compliant = contrast_ratio >= 3.0
    else:
        is_compliant = contrast_ratio >= 4.5

    return is_compliant, contrast_ratio


def verify_all_contrasts() -> dict[str, tuple[bool, float]]:
    """
    Verify contrast ratios for all color combinations against white background.

    文本色（深档调色板）与徽章底色（白字对底色）全部参与断言；
    TEXT_DISABLED 按 WCAG 1.4.3 禁用态豁免，单独标注不计入 PASS/FAIL
    （键仍保留，便于观察）。

    Returns:
        Dictionary mapping color name to (is_compliant, contrast_ratio)
    """
    results = {}

    # Foreground (text) colors against the white page background
    text_colors = {
        "PRIMARY_COLOR": PRIMARY_COLOR,
        "SECONDARY_COLOR": SECONDARY_COLOR,
        "SUCCESS_COLOR": SUCCESS_COLOR,
        "ERROR_COLOR": ERROR_COLOR,
        "WARNING_COLOR": WARNING_COLOR,
        "TEXT_COLOR": TEXT_COLOR,
        "TEXT_SECONDARY": TEXT_SECONDARY,
    }

    # Badge / status backgrounds: white text on the color itself
    badge_backgrounds = {
        "PRIMARY_COLOR_bg": PRIMARY_COLOR,
        "SECONDARY_COLOR_bg": SECONDARY_COLOR,
        "SUCCESS_COLOR_bg": SUCCESS_COLOR,
        "ERROR_COLOR_bg": ERROR_COLOR,
        "WARNING_COLOR_bg": WARNING_COLOR,
        "DANGER_COLOR_bg": DANGER_COLOR,
        "INFO_COLOR_bg": INFO_COLOR,
        "HIGHLIGHT_COLOR_bg": HIGHLIGHT_COLOR,
        "REVIEW_STATUS_候选_bg": REVIEW_STATUS_COLORS["候选"],
        "REVIEW_STATUS_审定_bg": REVIEW_STATUS_COLORS["审定"],
        "REVIEW_STATUS_发布_bg": REVIEW_STATUS_COLORS["发布"],
    }

    for name, color in text_colors.items():
        results[name] = check_contrast(color, BACKGROUND_COLOR)
    for name, color in badge_backgrounds.items():
        results[name] = check_contrast("#ffffff", color)

    # WCAG 1.4.3 exempts disabled text — record for observability only.
    results["TEXT_DISABLED(exempt)"] = check_contrast(
        TEXT_DISABLED, BACKGROUND_COLOR)

    return results


# ============================================================================
# Version and Metadata
# ============================================================================

DESIGN_SYSTEM_VERSION = "1.1.0"
DESIGN_SYSTEM_DATE = "2026/11/08"
DESIGN_SYSTEM_AUTHOR = "Claude Code"

# ============================================================================
# Initialization
# ============================================================================


def initialize_design_system() -> None:
    """
    Initialize the design system module.

    This function can be called to run initial checks and verify the design
    system is properly configured. It's optional but useful for debugging.

    Example:
        >>> initialize_design_system()
        >>> # Runs initial checks and prints verification results
    """
    print(f"Design System v{DESIGN_SYSTEM_VERSION} initialized")
    colors = ("PRIMARY_COLOR", "SECONDARY_COLOR", "SUCCESS_COLOR", "ERROR_COLOR",
              "WARNING_COLOR", "BACKGROUND_COLOR", "CARD_COLOR", "TEXT_COLOR",
              "TEXT_SECONDARY", "TEXT_DISABLED", "BORDER_COLOR", "DANGER_COLOR",
              "INFO_COLOR", "HIGHLIGHT_COLOR")
    spacing = ("SPACE_XS", "SPACE_SM", "SPACE_MD", "SPACE_LG", "SPACE_XL")
    fonts = ("HEADER_H1", "HEADER_H2", "HEADER_H3", "HEADER_H4", "BODY_SM",
             "BODY_BASE", "BODY_LG", "LINE_HEIGHT_TIGHT", "LINE_HEIGHT_NORMAL",
             "LINE_HEIGHT_RELAXED")
    components = ("get_button_primary_style", "get_button_secondary_style",
                  "get_button_outline_style", "get_button_warning_style",
                  "get_card_style", "get_container_style",
                  "get_input_field_style", "get_input_field_focused_style",
                  "get_table_style", "get_table_header_style",
                  "get_table_row_style", "get_table_cell_style",
                  "get_section_spacing", "SECTION_SPACING_STYLE",
                  "get_badge_style", "get_badge_html",
                  "pick_readable_text_color", "relative_luminance",
                  "check_contrast",
                  "verify_all_contrasts", "initialize_design_system")
    print(f"Colors: {len(colors)}")
    print(f"Spacing: {len(spacing)}")
    print(f"Fonts: {len(fonts)}")
    print(f"Components: {len(components)}")
    print("\nWCAG AA Contrast Verification:")
    print("=" * 60)
    results = verify_all_contrasts()
    for color, (ok, ratio) in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"{color:20s}: {ratio:5.2f}:1 {status}")


# ============================================================================
# Module Usage
# ============================================================================

if __name__ == "__main__":
    # Run initialization when module is executed directly
    initialize_design_system()

# ============================================
# 全局主题 CSS（批次 21 界面美化）
# ============================================
def get_global_theme_css() -> str:
    """全局主题层：注入一次，作用于 Streamlit 真实 DOM（装饰性升级）。

    纪律（批次 21 界面美化）：
      * **零文本/背景色对变更**——语义色板被 test_rv1_fixes 逐值锁定
        （WCAG 深档），本层只做阴影/圆角/过渡/边框/字距等装饰升级，
        对比度矩阵不受影响；
      * 全部选择器走 Streamlit data-testid/稳定 class，不含用户数据插值；
      * 暗色主题兼容：叠加面用 rgba 半透明，不钉死浅底深字（唯一例外沿用
        RV1-3 既有常亮面纪律）。
    """
    return f"""
<style>
/* ── 按钮：圆角、过渡、悬停抬升 ─────────────────────────────
   primary 型用主色渐变（两端 #4a5568→#2c5282 白字均 ≥7:1，WCAG 不降） */
.stButton > button {{
    border-radius: 10px;
    font-weight: 600;
    transition: transform 0.15s ease, box-shadow 0.2s ease,
                filter 0.2s ease;
}}
.stButton > button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(26, 32, 44, 0.15);
}}
.stButton > button[kind="primary"] {{
    background-image: linear-gradient(135deg, {PRIMARY_COLOR}, {SECONDARY_COLOR});
    border: none;
}}
.stButton > button[kind="primary"]:hover {{
    filter: brightness(1.08);
}}

/* ── 指标卡：卡片化（驾驶舱四卡/风险汇总） ────────────────── */
[data-testid="stMetric"] {{
    background-color: {CARD_COLOR};
    border: 1px solid {BORDER_COLOR};
    border-radius: 12px;
    padding: 14px 18px;
    box-shadow: 0 1px 2px rgba(26, 32, 44, 0.04);
}}
[data-testid="stMetricLabel"] p {{
    font-weight: 600;
    letter-spacing: 0.01em;
}}

/* ── Tabs：活动下划线主题色＋悬停反馈（词典管理八 tab/语义分析九 tab） ── */
[data-testid="stTabs"] [role="tab"] {{
    font-weight: 600;
    transition: color 0.15s ease;
}}
[data-testid="stTabs"] [role="tab"]:hover {{
    color: {SECONDARY_COLOR};
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] p {{
    color: {SECONDARY_COLOR};
}}

/* ── Expander：圆角＋边框柔化 ─────────────────────────────── */
[data-testid="stExpander"] details {{
    border-radius: 10px;
    border-color: {BORDER_COLOR};
}}
[data-testid="stExpander"] summary {{
    border-radius: 10px;
}}

/* ── DataFrame：圆角＋边框 ────────────────────────────────── */
[data-testid="stDataFrame"] {{
    border-radius: 10px;
    border: 1px solid {BORDER_COLOR};
    overflow: hidden;
}}

/* ── 告警条（info/warning/error/success）：左侧主题色强调线 ── */
[data-testid="stAlert"] {{
    border-radius: 10px;
    border-left: 4px solid {INFO_COLOR};
}}
[data-testid="stAlert"][kind="stError"] {{ border-left-color: {ERROR_COLOR}; }}
[data-testid="stAlert"][kind="stWarning"] {{ border-left-color: {WARNING_COLOR}; }}
[data-testid="stAlert"][kind="stSuccess"] {{ border-left-color: {SUCCESS_COLOR}; }}

/* ── 标题字距与主标下划线（页面 h1） ──────────────────────── */
.main h1, [data-testid="stMain"] h1 {{
    letter-spacing: -0.01em;
    padding-bottom: 6px;
    border-bottom: 2px solid rgba(44, 82, 130, 0.15);
}}
.main h2, [data-testid="stMain"] h2 {{
    letter-spacing: -0.005em;
}}

/* ── 侧边栏：右缘细分割＋标题间距 ────────────────────────── */
[data-testid="stSidebar"] {{
    border-right: 1px solid {BORDER_COLOR};
}}
[data-testid="stSidebar"] h2 {{
    letter-spacing: 0.02em;
}}

/* ── 滚动条：细圆角（WebKit 系） ─────────────────────────── */
::-webkit-scrollbar {{
    width: 8px;
    height: 8px;
}}
::-webkit-scrollbar-thumb {{
    background: rgba(74, 85, 104, 0.35);
    border-radius: 8px;
}}
::-webkit-scrollbar-thumb:hover {{
    background: rgba(74, 85, 104, 0.55);
}}

/* ── 分隔线柔化 ──────────────────────────────────────────── */
hr {{
    border: none;
    border-top: 1px solid {BORDER_COLOR};
}}
</style>
"""
