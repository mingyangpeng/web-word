"""
单词库页面 - 管理和浏览单词
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import DEFAULT_PAGE_SIZE, DIFFICULTY_LABELS
from config.logging_config import get_logger
from data.word_database import get_db_manager

logger = get_logger(__name__)


# 词性中文标签 -> 英文匹配关键词（用于 part_of_speech 字段的子串匹配）
POS_FILTER_KEYWORDS = {
    "全部": None,
    "名词": "noun",
    "动词": "verb",
    "形容词": "adj",
    "副词": "adv",
    "其他": None,  # 特殊：在 UI 中表示"以上都不是"
}

DIFFICULTY_FILTER_OPTIONS = ["全部", "简单", "中等", "困难", "高级"]


def app() -> None:
    """单词库页面应用入口"""
    st.title("📊 单词库")

    if "words_data" not in st.session_state:
        st.session_state.words_data = None
    if "search_query" not in st.session_state:
        st.session_state.search_query = ""
    if "pos_filter" not in st.session_state:
        st.session_state.pos_filter = "全部"
    if "difficulty_filter" not in st.session_state:
        st.session_state.difficulty_filter = "全部"
    if "current_page" not in st.session_state:
        st.session_state.current_page = 1

    # ========== 侧边栏 ==========
    with st.sidebar:
        st.header("🔍 筛选")
        search_query = st.text_input("搜索单词", value=st.session_state.search_query)

        st.divider()
        st.subheader("词性")
        pos_filter = st.radio(
            "按词性筛选",
            list(POS_FILTER_KEYWORDS.keys()),
            index=list(POS_FILTER_KEYWORDS.keys()).index(st.session_state.pos_filter),
            horizontal=True,
            label_visibility="collapsed",
            key="pos_filter_radio",
        )

        st.divider()
        st.subheader("难度等级")
        difficulty_filter = st.radio(
            "按难度筛选",
            DIFFICULTY_FILTER_OPTIONS,
            index=DIFFICULTY_FILTER_OPTIONS.index(st.session_state.difficulty_filter),
            horizontal=True,
            label_visibility="collapsed",
            key="difficulty_filter_radio",
        )

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            refresh_btn = st.button("🔄 刷新", use_container_width=True)
        with col2:
            export_btn = st.button("📥 导出", use_container_width=True)

    # 检测筛选条件变化
    filter_changed = (
        search_query != st.session_state.search_query
        or pos_filter != st.session_state.pos_filter
        or difficulty_filter != st.session_state.difficulty_filter
    )
    if filter_changed:
        st.session_state.search_query = search_query
        st.session_state.pos_filter = pos_filter
        st.session_state.difficulty_filter = difficulty_filter
        st.session_state.words_data = None
        st.session_state.current_page = 1
        st.rerun()

    if refresh_btn:
        st.session_state.words_data = None
        st.rerun()

    # ========== 数据加载 ==========
    if st.session_state.words_data is None:
        try:
            db = get_db_manager()
            if search_query:
                words_data = db.search_words(search_query, limit=1000)
            else:
                words_data = db.get_all_words(limit=1000)
            # 应用筛选
            words_data = _apply_filters(words_data, pos_filter, difficulty_filter)
            st.session_state.words_data = words_data
        except Exception as e:  # noqa: BLE001
            logger.exception("加载数据失败")
            st.error(f"❌ 加载数据失败: {e}")
            return

    words_data = st.session_state.words_data
    total = len(words_data)

    # ========== 统计信息 ==========
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总单词数", total)
    with col2:
        st.metric("简单", _count_by_difficulty(words_data, {"easy"}))
    with col3:
        st.metric("中等", _count_by_difficulty(words_data, {"medium"}))
    with col4:
        st.metric("困难+高级", _count_by_difficulty(words_data, {"hard", "advanced"}))

    # ========== 列表（分页） ==========
    st.divider()
    st.subheader("📖 单词列表")

    if not words_data:
        st.info("暂无单词数据")
    else:
        _render_paginated_list(words_data, db)

    # ========== 导出 ==========
    if export_btn:
        _export_csv(words_data)


# ========== 辅助函数 ==========

def _apply_filters(words_data: list, pos_filter: str, difficulty_filter: str) -> list:
    """应用词性与难度筛选"""
    pos_keyword = POS_FILTER_KEYWORDS.get(pos_filter)
    result = []
    for w in words_data:
        # 难度筛选
        if difficulty_filter != "全部":
            label = DIFFICULTY_LABELS.get(w.get("difficulty_level", ""), "")
            # DIFFICULTY_LABELS 形如 "😊 简单"，去掉前缀比对
            if not label.endswith(difficulty_filter):
                continue

        # 词性筛选
        if pos_filter == "其他":
            pos = (w.get("part_of_speech") or "").lower()
            if any(k in pos for k in ("noun", "verb", "adj", "adv")):
                continue
        elif pos_keyword:
            pos = (w.get("part_of_speech") or "").lower()
            if pos_keyword not in pos:
                continue

        result.append(w)
    return result


def _count_by_difficulty(words_data: list, levels: set) -> int:
    return sum(1 for w in words_data if w.get("difficulty_level") in levels)


def _render_paginated_list(words_data: list, db) -> None:
    """渲染分页单词卡片网格"""
    total = len(words_data)
    total_pages = max(1, (total + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE)

    # 防越界
    if st.session_state.current_page > total_pages:
        st.session_state.current_page = total_pages
    current_page = st.session_state.current_page

    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("◀️ 上一页", disabled=(current_page <= 1)):
            st.session_state.current_page -= 1
            st.rerun()
    with col2:
        st.write(f"第 {current_page} 页 / 共 {total_pages} 页")
    with col3:
        if st.button("下一页 ▶️", disabled=(current_page >= total_pages)):
            st.session_state.current_page += 1
            st.rerun()

    start = (current_page - 1) * DEFAULT_PAGE_SIZE
    end = start + DEFAULT_PAGE_SIZE
    page_items = words_data[start:end]

    cols = st.columns(4)
    for i, word in enumerate(page_items):
        with cols[i % 4]:
            with st.container():
                word_id = word.get("id", "")
                card_content = f"""
                <div style="background: #f8f9fa; border-radius: 8px; padding: 15px; margin: 5px; border-left: 4px solid #1f77b4;">
                    <div style="font-weight: bold; font-size: 16px;">{word.get('word', '')}</div>
                    <div style="color: #666; font-size: 12px;">{word.get('pronunciation', '')}</div>
                    <div style="color: #1f77b4; font-size: 12px;">{word.get('part_of_speech', '')}</div>
                    <div style="color: #888; font-size: 10px; margin-top: 5px;">{word.get('definition', '无定义')}</div>
                </div>
                """
                st.markdown(card_content, unsafe_allow_html=True)

                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("🔍", key=f"view_{word_id}"):
                        st.session_state.current_view_word = word.get("word", "")
                        st.session_state.view_mode = "word"
                        st.rerun()
                with btn_col2:
                    if st.button("❌", key=f"delete_{word_id}"):
                        try:
                            db.delete_word(word_id)
                            st.session_state.words_data = None
                            st.success(f"已删除单词: {word.get('word', '')}")
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error(f"删除失败: {e}")


def _export_csv(words_data: list) -> None:
    """导出当前列表为 CSV 下载"""
    if not words_data:
        st.warning("暂无数据可导出")
        return

    import pandas as pd

    export_data = [
        {
            "单词": w.get("word", ""),
            "音标": w.get("pronunciation", ""),
            "词性": w.get("part_of_speech", ""),
            "难度": DIFFICULTY_LABELS.get(w.get("difficulty_level", ""), ""),
            "定义": (w.get("definition") or "")[:100],
        }
        for w in words_data
    ]

    df = pd.DataFrame(export_data)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 下载 CSV",
        data=csv,
        file_name=f"单词库_{st.session_state.search_query or 'all'}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    app()
