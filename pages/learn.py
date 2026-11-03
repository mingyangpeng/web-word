"""
学习界面 - 单词知识图谱可视化

使用 vis-network（UMD CDN）渲染力导向图，支持节点拖拽、缩放、点击高亮。
"""

import json
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import (
    DEFAULT_EDGE_COLOR,
    RELATION_COLOR_MAP,
    SIGMA_EDGE_WIDTH_MAX,
    SIGMA_EDGE_WIDTH_MIN,
    SIGMA_GRAPH_HEIGHT,
    SIGMA_DEFAULT_EDGE_WIDTH,
)
from config.logging_config import get_logger
from data.word_database import get_db_manager

logger = get_logger(__name__)


# vis-network UMD CDN（极稳定，多年 API 不变）
_VIS_NETWORK_CDN = "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"


def app() -> None:
    """学习界面应用入口"""
    st.title("🗺️ 学习 - 知识图谱")

    if "graph_data" not in st.session_state:
        st.session_state.graph_data = None
    if "graph_filter" not in st.session_state:
        st.session_state.graph_filter = ""

    # ---------- 侧边栏 ----------
    with st.sidebar:
        st.header("⚙️ 控制面板")
        search_query = st.text_input("🔍 搜索节点", value=st.session_state.graph_filter)

        st.radio(
            "视图模式",
            ["全部节点", "当前选中"],
            horizontal=True,
            key="graph_view_mode",
        )

        st.divider()
        st.subheader("操作")
        col1, col2 = st.columns(2)
        with col1:
            refresh_btn = st.button("🔄 刷新图谱", use_container_width=True)
        with col2:
            st.toggle("自动布局", value=True, help="启用力导向布局")

        st.divider()
        st.subheader("图谱设置")
        show_labels = st.toggle("显示标签", value=True)
        show_edges = st.toggle("显示连线", value=True)
        edge_thickness = st.slider(
            "连线粗细",
            SIGMA_EDGE_WIDTH_MIN,
            SIGMA_EDGE_WIDTH_MAX,
            SIGMA_DEFAULT_EDGE_WIDTH,
            1,
        )

    if refresh_btn:
        st.info("🔄 正在刷新知识图谱...")
        st.session_state.graph_data = None
        st.rerun()

    if search_query != st.session_state.graph_filter:
        st.session_state.graph_filter = search_query
        st.session_state.graph_data = None
        st.rerun()

    # ---------- 加载数据 ----------
    if st.session_state.graph_data is None:
        with st.spinner("正在加载知识图谱..."):
            try:
                db = get_db_manager()
                st.session_state.graph_data = db.get_full_graph()
            except Exception as e:  # noqa: BLE001
                logger.exception("加载图谱失败")
                st.error(f"❌ 加载图谱失败: {e}")
                return

    graph_data = st.session_state.graph_data

    st.subheader("🕸️ 单词知识图谱")

    if not graph_data or not graph_data.get("nodes"):
        st.warning("暂无数据，请先添加单词到数据库。")
        return

    # ---------- 应用搜索过滤 ----------
    view_mode = st.session_state.get("graph_view_mode", "全部节点")
    filter_query = st.session_state.graph_filter.strip()
    filtered_graph = _filter_subgraph(graph_data, filter_query, view_mode)

    col1, col2 = st.columns([3, 1])
    with col1:
        node_count = len(filtered_graph["nodes"])
        edge_count = len(filtered_graph["edges"])
        st.metric("节点数量", node_count)
        st.metric("连线数量", edge_count)

        # 状态提示
        if filter_query:
            if node_count == 0:
                st.warning(f"⚠️ 未找到单词 '{filter_query}'（请输入完整单词，区分大小写）")
            elif node_count == 1:
                st.info(f"🔖 已定位到 '{filter_query}'（无关系连接）")
            else:
                st.success(f"🔖 已聚焦 '{filter_query}' 及其 {node_count - 1} 个关联节点")
        st.caption(f"📦 准备渲染 {node_count} 节点 / {edge_count} 边 → 调用 st.iframe (vis-network)")

        if node_count > 0:
            display_graph(filtered_graph, show_labels, show_edges, edge_thickness)

    with col2:
        st.subheader("📋 图例")
        st.info("""
        🟢 **近义词**: 含义相近的单词
        🔴 **反义词**: 含义相反的单词
        🔵 **相关词**: 主题相关的单词
        🟡 **同音词**: 发音相同的单词
        🟣 **词族词**: 词形变化的单词
        """)
        st.divider()
        st.subheader("💡 提示")
        st.markdown("""
        - 拖拽节点可调整位置
        - 滚轮缩放视图
        - 点击节点查看信息
        - 双击节点居中
        """)


def _filter_subgraph(graph_data: dict, query: str, view_mode: str) -> dict:
    """
    根据 search_query 和 view_mode 过滤图谱。

    - 无 query 或 view_mode="全部节点"（且无 query） → 返回完整图谱
    - 有 query → 仅保留 query 命中节点及其 1 跳邻居（含相关边）

    Args:
        graph_data: 原始 {'nodes': [...], 'edges': [...]} 数据
        query: 搜索关键字（按 word 字段精确匹配，不区分大小写）
        view_mode: 视图模式（"全部节点" / "当前选中"）

    Returns:
        过滤后的 {'nodes': [...], 'edges': [...]}
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # 无 query 时：根据 view_mode 决定
    if not query:
        # "当前选中" 模式但没选中 → 返回空（提示用户搜索）
        if view_mode == "当前选中":
            return {"nodes": [], "edges": []}
        return graph_data

    # 找到命中的节点（按 word 字段，不区分大小写，支持部分前缀匹配）
    query_lower = query.lower()
    matched_ids = {
        n["id"] for n in nodes
        if str(n.get("word", "")).lower() == query_lower
        or str(n.get("word", "")).lower().startswith(query_lower)
    }

    if not matched_ids:
        return {"nodes": [], "edges": []}

    # 收集 1 跳邻居
    neighbor_ids = set(matched_ids)
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in matched_ids and tgt not in neighbor_ids:
            neighbor_ids.add(tgt)
        if tgt in matched_ids and src not in neighbor_ids:
            neighbor_ids.add(src)

    # 过滤节点和边
    filtered_nodes = [n for n in nodes if n["id"] in neighbor_ids]
    filtered_edges = [
        e for e in edges
        if e.get("source") in neighbor_ids and e.get("target") in neighbor_ids
    ]

    return {"nodes": filtered_nodes, "edges": filtered_edges}


def _build_vis_nodes(graph_data: dict, show_labels: bool) -> list:
    """构造 vis-network 节点列表"""
    nodes = []
    for n in graph_data.get("nodes", []):
        # 颜色字段存储的是关系类型（参考 db.get_full_graph 实现）
        rel_or_color = n.get("color", "")
        color = RELATION_COLOR_MAP.get(rel_or_color, rel_or_color) if rel_or_color else DEFAULT_EDGE_COLOR

        node = {
            "id": n["id"],
            "label": n.get("word", "") if show_labels else "",
            "size": n.get("size", 10),
            "color": {"background": color, "border": color, "highlight": {"background": color, "border": "#ff6b6b"}},
            "font": {"color": "#222", "size": 14},
            "title": f"{n.get('word', '')} [{rel_or_color or 'default'}]",  # hover tooltip
        }
        nodes.append(node)
    return nodes


def _build_vis_edges(graph_data: dict, show_edges: bool, edge_thickness: int) -> list:
    """构造 vis-network 边列表"""
    edges = []
    for i, e in enumerate(graph_data.get("edges", [])):
        rel_type = e.get("relation", "")
        color = RELATION_COLOR_MAP.get(rel_type, DEFAULT_EDGE_COLOR)
        edge = {
            "id": e.get("id", f"e_{i}"),
            "from": e.get("source"),
            "to": e.get("target"),
            "label": rel_type,
            "color": {"color": color, "highlight": "#ff6b6b"},
            "width": edge_thickness,
            "font": {"color": "#888", "size": 10, "strokeWidth": 0, "align": "middle"},
            "hidden": not show_edges,
            "title": rel_type,
        }
        edges.append(edge)
    return edges


def display_graph(
    graph_data: dict,
    show_labels: bool = True,
    show_edges: bool = True,
    edge_thickness: int = SIGMA_DEFAULT_EDGE_WIDTH,
) -> None:
    """显示 vis-network 图谱可视化"""
    nodes = graph_data.get("nodes", [])
    if not nodes:
        st.info("暂无节点数据")
        return

    vis_data = {
        "nodes": _build_vis_nodes(graph_data, show_labels),
        "edges": _build_vis_edges(graph_data, show_edges, edge_thickness),
    }

    html_content = _VIS_TEMPLATE.replace(
        "__GRAPH_JSON__", json.dumps(vis_data, ensure_ascii=False)
    ).replace("__HEIGHT__", str(SIGMA_GRAPH_HEIGHT))

    # Streamlit 1.58+ 推荐使用 st.iframe（st.components.v1.html 已废弃）
    st.iframe(html_content, height=SIGMA_GRAPH_HEIGHT + 50)


_VIS_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    html, body { margin: 0; padding: 0; height: 100%; background: #fafafa; }
    #network { width: 100%; height: __HEIGHT__px; border: 1px solid #ddd; border-radius: 6px; }
    .info-card {
      position: absolute; top: 10px; left: 10px;
      background: rgba(255,255,255,0.95); padding: 8px 12px;
      border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);
      font-size: 12px; color: #444; max-width: 280px;
      display: none;
    }
  </style>
</head>
<body>
  <div id="network"></div>
  <div id="info" class="info-card"></div>
  <script>
    const data = __GRAPH_JSON__;

    // vis-network 期望 DataSet 或普通数组
    const nodes = new vis.DataSet(data.nodes);
    const edges = new vis.DataSet(data.edges);

    const container = document.getElementById('network');
    const options = {
      nodes: { shape: 'dot', borderWidth: 2, scaling: { min: 8, max: 24 } },
      edges: {
        arrows: { to: { enabled: false } },
        smooth: { type: 'continuous' },
        selectionWidth: 2,
      },
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        stabilization: { iterations: 200 },
        forceAtlas2Based: {
          gravitationalConstant: -50,
          centralGravity: 0.01,
          springLength: 100,
          springConstant: 0.08,
          damping: 0.4,
        },
      },
      interaction: { hover: true, tooltipDelay: 200, zoomView: true },
    };

    const network = new vis.Network(container, { nodes, edges }, options);

    const infoCard = document.getElementById('info');

    // 物理稳定后自动 fit 视野，确保所有节点都在可视区域
    network.once('stabilizationIterationsDone', () => {
      network.fit({ animation: { duration: 600, easingFunction: 'easeInOutQuad' } });
    });
    // 兜底： stabilization 失败时（如节点为空），3s 后强制 fit
    setTimeout(() => {
      try { network.fit({ animation: { duration: 400 } }); } catch (e) {}
    }, 3000);

    network.on('click', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        const node = nodes.get(nodeId);
        const connected = network.getConnectedEdges(nodeId);
        infoCard.innerHTML = `
          <strong style="font-size:14px;color:#1f77b4;">${node.label}</strong><br/>
          <span style="color:#666;">关系类型: ${node.title.match(/\[(.+?)\]/)?.[1] || 'default'}</span><br/>
          <span style="color:#666;">关联连线: ${connected.length} 条</span>
        `;
        infoCard.style.display = 'block';
      } else {
        infoCard.style.display = 'none';
      }
    });
  </script>
</body>
</html>
"""
