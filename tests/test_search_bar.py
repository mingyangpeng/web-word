"""
UI-01 回归测试：浮动固定搜索栏 (sticky search bar)。

背景（2026-09-15 修复的缺陷）：
1. 旧实现用 `st.markdown('<div class="google-search-bar">')` 试图包住后面的
   `st.text_input`。Streamlit 把每个 markdown 渲染成独立的兄弟节点，浏览器会立即
   闭合这个未闭合的 div，输入框实际在容器之外 —— CSS 与 sticky 从未生效。
2. 旧样式 `background: rgba({BACKGROUND_COLOR}, 0.98)` 插值出
   `rgba(#ffffff, 0.98)`，这是非法 CSS，浏览器整条丢弃。
3. 旧 JS 注入等待 `.search-bar-start` 标记，而代码从未输出该 class，于是
   init() 每 300ms 自我重试、永不成功。

本文件锁定修复后的契约：搜索栏外观挂在 `.st-key-search_bar` 容器上，定位由
`:has()` 挂到容器 wrapper 上，且颜色经 `hex_to_rgba` 正确转换。
"""

import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.design_system import (  # noqa: E402
    BACKGROUND_COLOR,
    hex_to_rgba,
)
from streamlit.testing.v1 import AppTest  # noqa: E402

RUN_TIMEOUT = 30
APP_PATH = os.path.join(PROJECT_ROOT, "src", "app.py")


@pytest.fixture(scope="module")
def app_source():
    with open(APP_PATH, encoding="utf-8") as f:
        return f.read()


# ============================================
# 颜色工具（非法 rgba 的根因）
# ============================================
def test_hex_to_rgba_converts_six_digit_hex():
    assert hex_to_rgba("#ffffff", 0.98) == "rgba(255, 255, 255, 0.98)"
    assert hex_to_rgba("4a5568", 0.5) == "rgba(74, 85, 104, 0.5)"


def test_hex_to_rgba_supports_shorthand_and_full_alpha():
    assert hex_to_rgba("#fff") == "rgba(255, 255, 255, 1.0)"
    assert hex_to_rgba("#000000") == "rgba(0, 0, 0, 1.0)"


def test_hex_to_rgba_rejects_malformed_input():
    with pytest.raises(ValueError):
        hex_to_rgba("#ffff")
    with pytest.raises(ValueError):
        hex_to_rgba("not-a-color")


def test_no_hex_interpolated_into_rgba(app_source):
    """回归：任何 CSS `rgba(` 里都不得再插入十六进制色值。

    f-string 里用 {{ }} 转义，因此先还原成单花括号，再看真实的 CSS 声明。
    """
    css_lines = []
    inside_style = False
    for line in app_source.splitlines():
        if "<style>" in line:
            inside_style = True
            continue
        if "</style>" in line:
            inside_style = False
            continue
        if inside_style:
            css_lines.append(line.replace("{{", "{").replace("}}", "}"))

    assert css_lines, "未在 app.py 中定位到 <style> 块"

    # 注意用 (?<![_a-z]) 排除 Python 的 hex_to_rgba( 调用，只匹配真正的 CSS 函数。
    css_rgba = re.compile(r"(?<![_a-z])rgba\(")
    offenders = [
        line.strip() for line in css_lines
        if css_rgba.search(line) and not re.search(r"(?<![_a-z])rgba\(\s*\d", line)
    ]
    assert offenders == [], f"rgba() 中插入了非数值颜色：{offenders}"


def test_search_bar_background_uses_helper(app_source):
    """搜索栏背景必须经 hex_to_rgba 生成合法 rgba。"""
    assert "hex_to_rgba(BACKGROUND_COLOR" in app_source
    # 生成的 CSS 不含十六进制
    css_value = hex_to_rgba(BACKGROUND_COLOR, 0.98)
    assert "#" not in css_value and css_value.startswith("rgba(")


# ============================================
# 结构：输入框必须真的在可定位容器内
# ============================================
def _code_only(app_source: str) -> str:
    """去掉注释与三引号块（<style> 块、docstring），只留可执行代码。

    否则「st.container(key="search_bar")」出现在注释或文档字符串里也会让结构断言
    假通过。单引号/双引号字符串保留，因为 key 的值本身就是字符串字面量。
    """
    without_comments = "\n".join(
        line.split("#", 1)[0] for line in app_source.splitlines()
    )
    return re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", without_comments)


def test_search_input_uses_keyed_container(app_source):
    """输入框必须放在 st.container(key="search_bar") 内（真实代码，非注释）。

    这是修复的核心：只有带 key 的容器才会生成稳定的 .st-key-search_bar class，
    CSS 才有一个真正包含输入框的元素可以定位。
    """
    code = _code_only(app_source)
    assert re.search(r'st\.container\(\s*key\s*=\s*["\']search_bar["\']\s*\)', code), (
        "搜索输入框必须放在带 key 的容器内"
    )
    # 且不得再出现无 key 的裸容器包裹输入框
    assert not re.search(r"with\s+st\.container\(\s*\)\s*:", code), (
        "搜索栏容器必须有 key，否则拿不到 .st-key-search_bar class"
    )


def test_obsolete_div_wrapper_is_gone(app_source):
    """回归：不得再退回「用 markdown div 包住 widget」的写法。"""
    assert 'class="google-search-bar"' not in app_source


def test_sticky_targets_container_wrapper(app_source):
    """sticky 必须挂在 wrapper 上，容器本身没有滚动行程。"""
    # f-string 里 CSS 花括号被转义成 {{ }}，因此按转义形式匹配。
    # 注意用 DOTALL：body 内还可能出现 {STICKY_SEARCH_BAR_TOP} 这类插值。
    sticky_block = re.search(
        r':has\(>\s*\.st-key-search_bar\)\s*\{\{(?P<body>.*?)\}\}',
        app_source,
        re.DOTALL,
    )
    assert sticky_block is not None, "缺少 :has(> .st-key-search_bar) 定位规则"
    body = sticky_block.group("body")
    assert "position: sticky" in body
    assert "top:" in body
    assert "z-index" in body


def test_sticky_top_clears_streamlit_header(app_source):
    """吸顶偏移必须让开 Streamlit 顶栏（Deploy/菜单那个常驻条）。

    stHeader 是高度 60px、z-index 999990 的常驻元素。若 sticky top 小于该高度，
    搜索栏会有一截压在顶栏下面且输入框不可点（实测 top:1rem 时重叠 44px、
    输入框 elementFromPoint 命中的是顶栏而非输入框）。
    """
    match = re.search(
        r'^STICKY_SEARCH_BAR_TOP\s*=\s*["\'](?P<value>[^"\']+)["\']',
        app_source,
        re.MULTILINE,
    )
    assert match is not None, "缺少 STICKY_SEARCH_BAR_TOP 常量，无法校验吸顶偏移"

    raw = match.group("value")
    value = float(raw.replace("rem", "")) * 16 if raw.endswith("rem") else float(
        raw.replace("px", "")
    )

    # 60px 是 stHeader 的固定高度；留出间隙避免视觉贴边。
    assert value >= 60, f"吸顶偏移 {raw}（{value}px）未让开 60px 的 Streamlit 顶栏"

    # 且 CSS 必须真的使用这个常量，而不是又写死一个小值。
    assert "top: {STICKY_SEARCH_BAR_TOP}" in app_source, (
        "sticky top 必须引用 STICKY_SEARCH_BAR_TOP"
    )


def test_sticky_stays_below_header_zindex(app_source):
    """回归：不得把搜索栏 z-index 提到顶栏之上，否则会盖住 Deploy 按钮。"""
    sticky_block = re.search(
        r':has\(>\s*\.st-key-search_bar\)\s*\{\{(?P<body>.*?)\}\}', app_source, re.DOTALL
    )
    assert sticky_block is not None
    z_match = re.search(r"z-index:\s*(\d+)", sticky_block.group("body"))
    assert z_match is not None, "缺少 z-index"
    # stHeader 的 z-index 是 999990；必须远低于它。
    assert int(z_match.group(1)) < 999990, "搜索栏 z-index 不得高于 Streamlit 顶栏"


def test_appearance_is_on_container_not_wrapper(app_source):
    """外观只在容器上，避免内外两层各加一次内边距。"""
    # 样式块写在 f-string 里，CSS 花括号因此被转义成 {{ }}。
    container_block = re.search(
        r'^\.st-key-search_bar\s*\{\{(?P<body>.*?)\}\}', app_source,
        re.MULTILINE | re.DOTALL,
    )
    assert container_block is not None, "缺少 .st-key-search_bar 外观规则"
    body = container_block.group("body")
    for prop in ("background:", "padding:", "border-radius:"):
        assert prop in body, f".st-key-search_bar 缺少 {prop}"


def test_no_dead_marker_js(app_source):
    """回归：等待 .search-bar-start 的 JS 注入已删除，且无残留引用。"""
    assert "search-bar-start" not in app_source
    assert "components.html" not in app_source


# ============================================
# 渲染：样式与输入框确实进入页面
# ============================================
def test_search_bar_style_and_input_render():
    at = AppTest.from_file("src/app.py")
    at.run(timeout=RUN_TIMEOUT)

    assert at.exception == []

    styles = [m.value for m in at.markdown if "st-key-search_bar" in m.value]
    assert styles, "页面未输出搜索栏样式"
    assert any("position: sticky" in s for s in styles)
    assert any("rgba(255, 255, 255, 0.98)" in s for s in styles)

    assert len(at.text_input) == 1
    assert at.text_input[0].key == "搜索动词"
