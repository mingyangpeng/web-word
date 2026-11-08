"""❓ 帮助中心页 —— 渲染 docs/help/平台功能使用说明.md（帮助母本）。

母本机制（docs/README.md §五）：`docs/help/平台功能使用说明.md` 是全部功能帮助的
唯一事实源（四段式：功能说明/使用介绍/原理说明/注意事项）；页面建成后对应章节
原样迁入 page_guides，两处永不漂移。本页把母本搬进界面：章节导航＋关键词过滤，
全员可见（含未登录）——帮助不该有门槛。

状态标记约定：【已实现】可直接使用；【阶段1】【阶段2】为规划中功能，说明即验收标准。
文档缺失时优雅降级（warning 指引），不抛错。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.design_system import HEADER_H1, HEADER_H3, WARNING_COLOR

# 母本路径（仓库根 docs/help/；app 以任意 cwd 启动均可解析）
HELP_DOC = Path(__file__).resolve().parent.parent / "docs" / "help" / "平台功能使用说明.md"


def _load_help_doc() -> str | None:
    """读取母本；缺失返回 None（调用方降级）。"""
    try:
        return HELP_DOC.read_text(encoding="utf-8")
    except OSError:
        return None


def _split_sections(doc: str) -> list[tuple[str, str]]:
    """按 `## ` 二级标题切分章节，返回 [(标题, 正文), ...]；文首（首个 ## 之前）并入「导读」。"""
    sections: list[tuple[str, str]] = []
    title, body = "导读", []
    for line in doc.splitlines():
        if line.startswith("## "):
            if body or title != "导读":
                sections.append((title, "\n".join(body).strip()))
            title, body = line[3:].strip(), []
        else:
            body.append(line)
    if body or title != "导读":
        sections.append((title, "\n".join(body).strip()))
    return [(t, b) for t, b in sections if b]


def render_help_center_page() -> None:
    """帮助中心：母本章节导航 + 关键词过滤 + 全文模式。"""
    st.markdown(f"<h1 style='{HEADER_H1}'>❓ 帮助中心</h1>", unsafe_allow_html=True)
    st.caption(
        "每个功能的「功能说明 / 使用介绍 / 原理说明 / 注意事项」四段式帮助。"
        "【阶段1】【阶段2】标记为规划中功能，说明即验收标准。"
    )

    doc = _load_help_doc()
    if doc is None:
        st.markdown(
            f"<p style='color:{WARNING_COLOR}'>帮助母本缺失（docs/help/平台功能使用说明.md）。"
            "请确认仓库完整性，或在仓库根目录重新检出该文件。</p>",
            unsafe_allow_html=True,
        )
        return

    sections = _split_sections(doc)
    query = st.text_input("搜索帮助内容", placeholder="如：信度 / 导入 / 盲标", key="help_query")
    if query.strip():
        hits = [(t, b) for t, b in sections if query.strip().lower() in (t + b).lower()]
        st.info(f"共 {len(hits)} 个章节命中「{query.strip()}」") if hits else st.warning(
            f"没有章节命中「{query.strip()}」，试试其他关键词（如 盲标、导入、闸门）。")
        for t, b in hits:
            st.markdown(f"<h3 style='{HEADER_H3}'>{t}</h3>", unsafe_allow_html=True)
            st.markdown(b)
        return

    options = ["📖 全文阅读"] + [t for t, _ in sections]
    choice = st.selectbox("章节导航", options=options, key="help_section")
    if choice == "📖 全文阅读":
        st.markdown(doc)
        return
    for t, b in sections:
        if t == choice:
            st.markdown(f"<h3 style='{HEADER_H3}'>{t}</h3>", unsafe_allow_html=True)
            st.markdown(b)
            return
