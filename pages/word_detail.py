"""
单词详情 - 动态知识图谱可视化

根据动词范畴动态加载和展示知识图谱（使用 vis-network）。
"""

import json
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import (
    ALL_CATEGORIES,
    CATEGORY_COLOR_MAP,
    DEFAULT_EDGE_COLOR,
    DEFAULT_NODE_COLOR,
    MAX_DISPLAY_WORDS,
    RELATION_COLOR_MAP,
    SIGMA_GRAPH_HEIGHT_DETAIL,
)
from config.logging_config import get_logger
from data.word_database import get_db_manager

logger = get_logger(__name__)

RELATION_DATA_FILE = "data/word_graph_relations.json"


def load_relation_data(word_category: str, word_subclass: str) -> list:
    """
    根据范畴和次类加载关系数据。

    Args:
        word_category: 单词范畴（path / manner / purpose / participant）
        word_subclass: 单词次类

    Returns:
        匹配的单词信息列表；若无匹配则返回 all_words 兜底。
    """
    try:
        with open(RELATION_DATA_FILE, "r", encoding="utf-8") as f:
            relations_data = json.load(f)
    except FileNotFoundError:
        logger.warning("关系数据文件不存在: %s", RELATION_DATA_FILE)
        st.warning("关系数据文件不存在")
        return []
    except json.JSONDecodeError:
        logger.exception("关系数据 JSON 解析失败: %s", RELATION_DATA_FILE)
        st.warning("关系数据文件格式错误")
        return []

    filtered_words = []
    for word_info in relations_data.get("filtered_words", []):
        word_cat = word_info.get("category", "")
        word_sub = word_info.get("subclass", "")
        if (
            word_cat == word_category
            or word_sub == word_subclass
            or word_category in ALL_CATEGORIES
        ):
            filtered_words.append(word_info)

    if not filtered_words:
        filtered_words = list(relations_data.get("all_words", []))

    return filtered_words


def display_word_detail(word_info: dict) -> None:
    """显示单词详细信息"""
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.markdown(f"### 📖 {word_info.get('word', '')}")
        st.markdown(f"**{word_info.get('chinese', '')}**")
        st.markdown(
            f"**{word_info.get('category', '')}** - {word_info.get('subclass', '')}"
        )
        st.divider()
        st.info(f"""
        **发音**: {word_info.get('pronunciation', 'N/A')}
        **语法形式**: {word_info.get('formula', 'N/A')}
        **语义特征**: {word_info.get('meaning', 'N/A')}
        **备注**: {word_info.get('note', 'N/A')}
        """)

    with col2:
        st.metric("单词", word_info.get("word", ""))
        st.metric("中文释义", word_info.get("chinese", ""))

    with col3:
        st.metric("范畴", word_info.get("category", ""))
        st.metric("次类", word_info.get("subclass", ""))


def _build_vis_nodes(filtered_words: list, highlight_word: str) -> list:
    """构造 vis-network 节点列表，selected word 高亮"""
    nodes = []
    for w in filtered_words:
        word = w.get("word", "")
        if not word:
            continue
        category = w.get("category", "path")
        color = CATEGORY_COLOR_MAP.get(category, DEFAULT_NODE_COLOR)
        is_selected = word == highlight_word
        nodes.append({
            "id": word,
            "label": word,
            "color": {
                "background": color,
                "border": "#ff6b6b" if is_selected else color,
                "highlight": {"background": color, "border": "#ff6b6b"},
            },
            "size": is_selected and 25 or 15,
            "borderWidth": is_selected and 3 or 1,
            "font": {"color": "#222", "size": 14, "bold": is_selected},
            "title": f"{word}\n[{category}] {w.get('chinese', '')}",
        })
    return nodes


def _build_vis_edges(selected_word_name: str, filtered_words: list) -> list:
    """构造 vis-network 边列表（基于 word_graph_relations.json）"""
    word_set = {w.get("word") for w in filtered_words if w.get("word")}
    edges = []

    try:
        with open(RELATION_DATA_FILE, "r", encoding="utf-8") as f:
            relations = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.exception("读取关系文件失败: %s", RELATION_DATA_FILE)
        return edges

    relations_map = relations.get("relations", {})
    for rel_type in ("synonym", "antonym"):
        color = RELATION_COLOR_MAP.get(rel_type, DEFAULT_EDGE_COLOR)
        label = "近义词" if rel_type == "synonym" else "反义词"
        for related in relations_map.get(rel_type, {}).get(selected_word_name, []):
            if related in word_set:
                edges.append({
                    "from": selected_word_name,
                    "to": related,
                    "label": label,
                    "color": {"color": color, "highlight": "#ff6b6b"},
                    "width": 2,
                    "font": {"color": "#888", "size": 10, "align": "middle"},
                    "title": label,
                })
    return edges


def display_graph_visualization(filtered_words: list, selected_word: dict) -> None:
    """显示 vis-network 知识图谱可视化"""
    if not filtered_words:
        st.info("暂无相关单词数据")
        return

    selected_word_name = (
        selected_word.get("word", "") if isinstance(selected_word, dict) else ""
    )

    vis_data = {
        "nodes": _build_vis_nodes(filtered_words, selected_word_name),
        "edges": _build_vis_edges(selected_word_name, filtered_words),
    }

    html_content = _VIS_TEMPLATE_DETAIL.replace(
        "__GRAPH_JSON__", json.dumps(vis_data, ensure_ascii=False)
    ).replace("__HEIGHT__", str(SIGMA_GRAPH_HEIGHT_DETAIL))

    # Streamlit 1.58+ 推荐使用 st.iframe（st.components.v1.html 已废弃）
    st.iframe(html_content, height=SIGMA_GRAPH_HEIGHT_DETAIL + 50)


_VIS_TEMPLATE_DETAIL = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    html, body { margin: 0; padding: 0; background: #fafafa; }
    #network { width: 100%; height: __HEIGHT__px; border: 1px solid #ddd; border-radius: 6px; }
  </style>
</head>
<body>
  <div id="network"></div>
  <script>
    const data = __GRAPH_JSON__;
    const nodes = new vis.DataSet(data.nodes);
    const edges = new vis.DataSet(data.edges);
    const container = document.getElementById('network');

    const options = {
      nodes: { shape: 'dot', borderWidth: 2, scaling: { min: 10, max: 30 } },
      edges: { smooth: { type: 'continuous' }, selectionWidth: 2 },
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        stabilization: { iterations: 150 },
        forceAtlas2Based: {
          gravitationalConstant: -45,
          centralGravity: 0.015,
          springLength: 110,
          springConstant: 0.06,
          damping: 0.4,
        },
      },
      interaction: { hover: true, zoomView: true },
    };

    const network = new vis.Network(container, { nodes, edges }, options);

    // 物理稳定后：若存在选中节点则聚焦，否则 fit 全图到视野内
    network.once('stabilizationIterationsDone', () => {
      const selected = data.nodes.find(n => n.borderWidth === 3);
      if (selected) {
        network.focus(selected.id, { scale: 1.2, animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
      } else {
        network.fit({ animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
      }
    });
    // 兜底：stabilization 失败时，3s 后强制 fit
    setTimeout(() => {
      try {
        const selected = data.nodes.find(n => n.borderWidth === 3);
        if (selected) {
          network.focus(selected.id, { scale: 1.0, animation: { duration: 300 } });
        } else {
          network.fit({ animation: { duration: 300 } });
        }
      } catch (e) {}
    }, 3000);
  </script>
</body>
</html>
"""


def app() -> None:
    """单词详情应用入口"""
    st.title("🔗 单词详情 - 知识图谱")

    if "word_info" not in st.session_state:
        st.session_state.word_info = None
    if "selected_word" not in st.session_state:
        st.session_state.selected_word = None
    if "filtered_words" not in st.session_state:
        st.session_state.filtered_words = []

    search_query = st.text_input(
        "🔍 搜索单词", placeholder="输入单词查询，如：arrive, run, chase..."
    )

    if st.button("🔍 查询", type="primary"):
        if search_query.strip():
            st.session_state.selected_word = {"word": search_query.strip()}

    if not st.session_state.selected_word:
        st.info("👈 请输入单词查询，或从首页选择单词")
        return

    word_name = st.session_state.selected_word.get("word", "")
    db = get_db_manager()
    word_info = db.get_word(word=word_name)

    if not word_info:
        st.error(f"❌ 单词 '{word_name}' 不存在于数据库中")
        return

    st.session_state.word_info = word_info
    st.session_state.current_word_name = word_name

    display_word_detail(word_info)

    # 注：import_from_json 把 category 写入了 definition 字段（混合格式）
    # 这里用 part_of_speech 作为 fallback
    category = word_info.get("part_of_speech", "path") or "path"
    subclass = word_info.get("difficulty_level", "path") or "path"

    with st.spinner(f"正在加载 {category}/{subclass} 范畴的单词..."):
        filtered = load_relation_data(category, subclass)
        st.session_state.filtered_words = filtered

        st.divider()
        st.subheader(f"📚 {category} - {subclass} 范畴相关单词 ({len(filtered)} 个)")

        if filtered:
            cols = st.columns(3)
            for i, info in enumerate(filtered[:MAX_DISPLAY_WORDS]):
                with cols[i % 3]:
                    with st.container():
                        st.markdown(f"""
                        <div style="
                            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                            border-radius: 10px;
                            padding: 15px;
                            margin: 5px;
                            border-left: 4px solid #667eea;
                            text-align: center;
                        ">
                            <div style="font-weight: bold; font-size: 18px;">{info.get('word', '')}</div>
                            <div style="color: #666; font-size: 12px;">{info.get('chinese', '')}</div>
                        </div>
                        """, unsafe_allow_html=True)

        st.divider()
        st.subheader("🕸️ 单词关系图谱")
        if st.session_state.filtered_words:
            display_graph_visualization(
                st.session_state.filtered_words,
                st.session_state.selected_word,
            )


if __name__ == "__main__":
    app()
