"""RV-12 轮修复回归（review RV-10 批次）。

两个关注点，均可在**无 MySQL 环境**全绿：

  * 帮助中心页（src/help_center.py）此前零行为级覆盖（P2-2）——补一个
    AppTest 用例：渲染不抛异常、章节导航选项来自母本 `## ` 二级标题、
    默认全文模式正文在场、关键词过滤真实出命中。母本来自 docs/，不触库。
  * collab_pages.py 正文期 `st.session_state["page"] =` 直写哨兵（RV12-1）：
    该写法在 Streamlit 1.57 抛 StreamlitAPIException（渲染时机晚于侧栏
    radio(key="page")），必须经 on_click 回调改会话。grep 式哨兵锁住
    「本模块不得再出现正文期直写」—— 修复由 FX-12 在 src 侧落盘（本文件
    不改 src），落盘后本哨兵即可真跑。
"""

import os
import re
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.help_center as hc  # noqa: E402

HELP_SCRIPT = (
    "from src.help_center import render_help_center_page\n"
    "render_help_center_page()\n"
)


def _all_text(at: AppTest) -> str:
    """主区全部文本元素（与 test_integration_apptest._page_text 同口径）。"""
    parts = []
    for accessor in ("markdown", "caption", "header", "subheader", "title",
                     "info", "warning", "error", "success"):
        elements = getattr(at, accessor, None) or []
        parts.extend(str(e.value) for e in elements)
    return "\n".join(parts)


# ============================================
# P2-2 帮助中心行为用例（AppTest，无库环境可跑）
# ============================================

class TestHelpCenterPage:
    def test_help_center_renders_sections_and_filter(self):
        """帮助中心：章节导航选项来自母本二级标题，全文模式正文在场，
        关键词过滤真实出命中计数 —— 三个行为断言一次跑齐，不触数据库。"""
        at = AppTest.from_string(HELP_SCRIPT, default_timeout=30)
        at.run()
        assert not at.exception
        assert "帮助中心" in _all_text(at)

        # 章节导航 selectbox：首项全文模式 + 其余为母本 `## ` 章节（逐一对齐）
        selectboxes = [s for s in at.selectbox if s.label == "章节导航"]
        assert selectboxes, "章节导航 selectbox 缺失"
        expected_sections = [t for t, _ in hc._split_sections(hc._load_help_doc() or "")]
        assert selectboxes[0].options == ["📖 全文阅读"] + expected_sections, \
            "章节导航选项必须与母本章节一一对应（含顺序）"

        # 默认选中全文模式：母本正文原样渲染（取真实章节标题在场为证；
        # 「导读」是文首合成段名、母本原文没有该字面量，故用首个 `## ` 实章节）
        real_sections = [t for t in expected_sections if t != "导读"]
        assert real_sections, "母本不应只有导读段"
        first_section = real_sections[0]
        assert first_section in _all_text(at), \
            f"全文模式应渲染母本正文（缺章节「{first_section}」）"

        # 关键词过滤：输入「信度」→ 命中计数 info 在场
        at.text_input[0].set_value("信度")
        at.run()
        assert not at.exception
        assert any("个章节命中" in str(i.value) for i in at.info), \
            f"关键词过滤应给出命中计数: {[_all_text(at)]}"


# ============================================
# RV12-1 collab_pages 正文期切页直写哨兵（依赖 FX-12 的 src 修复，已合入）
# ============================================

# 只拦「正文期对 st.session_state["page"] 赋值」这一种形态；on_click 回调里的
# st.session_state.update(page=...) 是 RV12-1 认可的正确修法，不在哨兵范围。
_BODY_PAGE_WRITE = re.compile(
    r'st\.session_state\[\s*["\']page["\']\s*\]\s*=')


def test_collab_pages_no_body_time_page_write():
    """哨兵：src/collab_pages.py 源码不得再含正文期 `st.session_state["page"] =`
    直写（RV12-1：晚于侧栏 radio 渲染的赋值在 Streamlit 1.57 必崩页）。
    新增切页一律走 st.button(..., on_click=...) 回调改会话。"""
    src_path = Path(PROJECT_ROOT) / "src" / "collab_pages.py"
    assert src_path.exists(), f"哨兵目标缺失: {src_path}"
    source = src_path.read_text(encoding="utf-8")
    hits = [
        f"L{i}: {line.strip()}"
        for i, line in enumerate(source.splitlines(), start=1)
        if _BODY_PAGE_WRITE.search(line)
    ]
    assert not hits, (
        "collab_pages.py 出现正文期 st.session_state['page'] 直写（会崩页），"
        f"应改为 on_click 回调: {hits}"
    )
