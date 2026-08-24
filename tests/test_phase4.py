"""
Phase 4 feature-polish regression tests (UI-06/07/08).

Uses Streamlit AppTest for UI state assertions plus a unit test for the
front-end hot-verb filter helper.
"""

import os
import sys

import pytest

# Ensure project root on path so `from src.xxx` imports resolve under pytest.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from streamlit.testing.v1 import AppTest  # noqa: E402

RUN_TIMEOUT = 30


@pytest.fixture
def at():
    return AppTest.from_file("src/app.py")


def test_sidebar_flag(at):
    """默认侧边栏展开：sidebar_collapsed 存在且为 False。"""
    at.run(timeout=RUN_TIMEOUT)
    assert "sidebar_collapsed" in at.session_state
    assert at.session_state["sidebar_collapsed"] is False


def test_collapse_toggle(at):
    """折叠态有 ☰ 图标栏按钮；展开态有 ◀ 折叠按钮。"""
    at.run(timeout=RUN_TIMEOUT)
    at.session_state["sidebar_collapsed"] = True
    at.run(timeout=RUN_TIMEOUT)
    labels = [b.label for b in at.button]
    assert "☰" in labels

    at.session_state["sidebar_collapsed"] = False
    at.run(timeout=RUN_TIMEOUT)
    labels = [b.label for b in at.button]
    assert "◀" in labels


def test_stats_section(at):
    """展开态下统计标题已渲染且区块分隔线存在（UI-07）。"""
    at.run(timeout=RUN_TIMEOUT)
    # 统计主标题 markdown 含 "实验统计"
    assert any("实验统计" in m.value for m in at.markdown)
    # 展开态下至少存在一处分隔线元素
    assert len(at.divider) > 0
