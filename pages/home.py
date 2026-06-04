"""
首页 - 单词查询和分析
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import (
    DIFFICULTY_LABELS,
    MAX_RELATIONS_DISPLAY,
    RELATION_LABELS,
    WORD_HISTORY_MAX,
)
from data.word_database import get_db_manager
from services.llm_service import LLMConfigError, get_llm_service


def app() -> None:
    """首页应用入口"""
    st.title("🔍 单词查询")

    # 初始化会话状态
    if "current_word" not in st.session_state:
        st.session_state.current_word = ""
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None
    if "word_history" not in st.session_state:
        st.session_state.word_history = []
    if "relations" not in st.session_state:
        st.session_state.relations = None
    if "relations_word" not in st.session_state:
        st.session_state.relations_word = None

    # 搜索框
    col1, col2, col3 = st.columns([3, 1, 2])

    with col1:
        search_query = st.text_input(
            "输入要查询的单词",
            value=st.session_state.current_word,
            placeholder="例如：happy, intelligent...",
        )

    with col2:
        search_btn = st.button("🔍 查询", type="primary", use_container_width=True)

    with col3:
        clear_btn = st.button("✖️ 清除", use_container_width=True)

    if clear_btn:
        st.session_state.current_word = ""
        st.session_state.analysis_result = None
        st.rerun()

    st.divider()
    if not st.session_state.analysis_result and not search_query:
        st.info("👈 请输入单词开始查询，或查看历史记录")

    # ---------- 查询逻辑 ----------
    if search_btn and search_query.strip():
        word = search_query.strip()
        st.session_state.current_word = word
        # 去重后插入到历史头部
        history = st.session_state.word_history
        if word in history:
            history.remove(word)
        history.insert(0, word)
        # 截断历史长度
        st.session_state.word_history = history[:WORD_HISTORY_MAX]

        with st.spinner(f"正在分析单词 '{word}'..."):
            try:
                db = get_db_manager()
                word_info = db.get_word(word=word)

                if word_info:
                    st.session_state.analysis_result = {
                        "source": "database",
                        "word": word_info,
                    }
                    show_word_info(word_info)
                else:
                    llm = get_llm_service()
                    analysis = llm.analyze_word(word)
                    st.session_state.analysis_result = {
                        "source": "llm",
                        "word": word,
                        "analysis": analysis,
                    }
                    # 缓存清空，避免显示上一个单词的关系
                    st.session_state.relations = None
                    st.session_state.relations_word = None
                    show_llm_analysis(analysis)
            except LLMConfigError as e:
                st.error(f"❌ 配置错误: {e}")
            except Exception as e:  # noqa: BLE001
                st.error(f"❌ 查询出错: {e}")

    # ---------- 历史记录 ----------
    if len(st.session_state.word_history) > 1:
        st.divider()
        st.caption("最近查询:")
        for word in st.session_state.word_history[:WORD_HISTORY_MAX]:
            if word == st.session_state.current_word:
                continue
            if st.button(f"↩️ {word}", key=f"history_{word}"):
                # 重新填入搜索框，清空当前结果，等待用户再次点击查询
                st.session_state.current_word = word
                st.session_state.analysis_result = None
                st.session_state.relations = None
                st.session_state.relations_word = None
                st.rerun()

    # ---------- LLM 结果中的查看详情按钮 ----------
    if (
        st.session_state.analysis_result
        and st.session_state.analysis_result.get("source") == "llm"
    ):
        st.divider()
        if st.button(
            "📊 查看 LLM 生成的单词详情和知识图谱",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state.word_info = {
                "word": st.session_state.analysis_result["word"]
            }
            st.rerun()


def show_word_info(word_info: dict) -> None:
    """显示数据库中的单词信息"""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("单词", word_info["word"])
    with col2:
        st.metric("词性", word_info.get("part_of_speech", "N/A"))
    with col3:
        difficulty = word_info.get("difficulty_level", "medium")
        st.metric("难度", DIFFICULTY_LABELS.get(difficulty, difficulty))

    st.divider()
    st.markdown("#### 🔗 查看知识图谱")
    if st.button("📊 查看单词详情和知识图谱", type="primary", use_container_width=True):
        st.session_state.current_word = word_info["word"]
        st.session_state.word_info = word_info
        st.session_state.analysis_result = {
            "source": "database",
            "word": word_info,
        }
        st.rerun()

    st.divider()
    st.subheader("📖 单词详情")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 中文释义")
        st.write(word_info.get("definition") or "无")
        st.markdown("#### 英文释义")
        st.write(word_info.get("english_definition") or "无")

    with col2:
        st.markdown("#### 例句")
        if word_info.get("example_sentence"):
            st.write(f"**{word_info['example_sentence']}**")
        else:
            st.write("暂无例句")

        if word_info.get("example_translation"):
            st.info(f"_{word_info['example_translation']}_")

        if word_info.get("pronunciation"):
            st.info(f"🔊 {word_info['pronunciation']}")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 统计信息")
        st.metric("出现频率", word_info.get("frequency", 0))
    with col2:
        st.subheader("🏷️ 难度等级")
        difficulty = word_info.get("difficulty_level", "medium")
        st.write(DIFFICULTY_LABELS.get(difficulty, difficulty))


def show_llm_analysis(analysis: dict) -> None:
    """显示 LLM 分析结果"""
    if "error" in analysis:
        st.error(f"❌ 分析失败: {analysis['error']}")
        return

    result = analysis.get("choices", [{}])[0].get("message", {})
    content = result.get("content", "")
    st.markdown(content)

    st.divider()
    st.subheader("🔗 关系网络")
    word = st.session_state.current_word

    # 已为当前单词生成过关系 -> 直接展示，避免重复请求
    cached = (
        st.session_state.relations_word == word
        and st.session_state.relations is not None
    )
    if cached:
        show_relations(st.session_state.relations)
        return

    with st.spinner("正在生成关系网络..."):
        try:
            llm = get_llm_service()
            relations = llm.generate_relations(word)
            st.session_state.relations = relations
            st.session_state.relations_word = word
            show_relations(relations)
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 关系生成失败: {e}")


def show_relations(relations: dict) -> None:
    """显示关系网络"""
    if not isinstance(relations, dict):
        st.info("暂无关系数据")
        return

    total = sum(len(v) for v in relations.values() if isinstance(v, list))
    if total == 0:
        st.info("暂无关系数据")
        return

    relation_types = [k for k, v in relations.items() if isinstance(v, list) and v]
    if not relation_types:
        st.info("暂无关系数据")
        return

    tabs = st.tabs([RELATION_LABELS.get(t, t) for t in relation_types])
    for tab, rel_type in zip(tabs, relation_types):
        with tab:
            words_list = relations[rel_type]
            cols = st.columns(3)
            for i, word in enumerate(words_list[:MAX_RELATIONS_DISPLAY]):
                with cols[i % 3]:
                    st.button(word, key=f"rel_{rel_type}_{i}")

    st.divider()
    st.subheader("📈 关系统计")
    for rel_type, word_list in relations.items():
        if isinstance(word_list, list) and word_list:
            st.write(f"{RELATION_LABELS.get(rel_type, rel_type)}: {len(word_list)} 个")


if __name__ == "__main__":
    app()
