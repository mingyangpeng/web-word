"""
词簇图谱渲染 —— 把「查找词 + 其所属词簇」的**完全图**画到页面上。

## 为什么是内联 SVG 而不是第三方图形库

graphify 生成的 `graphify-out/graph.html` 用的是 vis-network（CDN 引入的 UMD 包）。
Streamlit 里要复刻那种交互图，只有两条路：

  1. `st.components.v1.html(...)` 嵌 iframe，往里面塞 vis-network 的 CDN script；
  2. 自己输出 SVG，用 `st.markdown(..., unsafe_allow_html=True)` 直接内联。

这里选 2，理由是**可用性优先于炫技**：
  * 不依赖任何 CDN。项目已有「零网络依赖」的约束（灌库脚本、离线降级都是这个原则），
    在断网或内网环境下，方案 1 会渲染出一片空白 iframe，方案 2 永远能画出来。
  * 无需新增前端依赖，也不受 Streamlit 组件沙箱的限制 —— iframe 里的内容无法参与
    页面的主题切换与响应式布局。
  * 完全图本身是**静态结构**，不需要力学布局，圆弧布局（circle layout）就能把
    「谁和谁相连」表达清楚，交互带来的信息增量很小。

代价是节点不能拖拽缩放。对「看清这个簇里有哪些词、彼此都相连」这个目标来说，
这个代价可以接受。

## 完全图的规模问题

簇内完全图的边数是 C(n, 2)：3 词的「处所脱离」只有 3 条边，而 56 词的「常态行走」
是 1540 条 —— 画出来就是一团毛球，任何一条边都看不清。

处理方式不是偷偷截断（那会让用户以为簇里只有几个词），而是**如实画全 + 明确告知规模**：
  * 节点数 ≤ SMALL_CLUSTER：画出全部边并给每个节点标名字。
  * 节点数 > SMALL_CLUSTER：仍然画出全部边（用户要求的完全图），但只给中心词和
    首尾若干节点标名字，其余靠 hover 的 <title> 查看，并在图注里写明实际节点/边数。
  * 提供 `highlight_only_center` 选项：只保留中心词相关的边（n-1 条），用于大簇下
    看清「这个词和谁相连」。
"""

import math
from typing import Dict, Any, List

# 超过这个规模就只给中心词标名字（其余靠 hover），避免标签互相压盖
SMALL_CLUSTER = 18

# 画布与布局常量
CANVAS_W = 920
CANVAS_H = 620
RING_PADDING = 96          # 圆环外侧留白（够放标签）
NODE_R_DEFAULT = 15
NODE_R_CENTER = 21
LABEL_FONT_SIZE = 12


def _esc(text: str) -> str:
    """转义为可安全放进 SVG 文本节点的内容。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _layout(members: List[str], center: str) -> Dict[str, tuple]:
    """
    圆弧布局：中心词放圆心，其余成员均匀排在一个圆环上。

    把中心词固定在圆心是有意为之 —— 用户是「查到某个词」才看这张图的，
    它在视觉上必须一眼可辨，而不是混在环上。
    """
    ring = [m for m in members if m != center]
    n = len(ring)
    cx, cy = CANVAS_W / 2, CANVAS_H / 2
    radius = min(CANVAS_W, CANVAS_H) / 2 - RING_PADDING

    pos = {center: (cx, cy)}
    if n == 1:
        pos[ring[0]] = (cx + radius, cy)
    elif n == 2:
        # 两个成员时用左右布局而不是上下：上下会让「两个环上节点之间的边」
        # 与中心词标签叠在同一竖直线上，读起来像是中心词连着两段线。
        pos[ring[0]] = (cx + radius, cy)
        pos[ring[1]] = (cx - radius, cy)
    else:
        for i, verb in enumerate(ring):
            # 从正上方开始顺时针排布，读起来更符合直觉
            angle = -math.pi / 2 + 2 * math.pi * i / n
            pos[verb] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    return pos


def _label_anchor(x: float) -> str:
    """根据节点横向位置选择标签的 text-anchor，避免标签出画布。"""
    cx = CANVAS_W / 2
    if x < cx - 20:
        return "end"
    if x > cx + 20:
        return "start"
    return "middle"


def render_cluster_graph_svg(
    graph: Dict[str, Any],
    highlight_only_center: bool = False,
    max_draw_nodes: int = 80,
) -> str:
    """
    把 `get_cluster_graph()` 的返回值渲染成内联 SVG。

    Args:
        graph: `src.mysql_db.get_cluster_graph()` 的返回结构（nodes / links / cluster）。
        highlight_only_center: True 时只画与中心词相连的边（大簇下更易读）。
        max_draw_nodes: 绘制上限，超过则提示用户并只画中心词及其若干邻居。

    Returns:
        SVG 字符串；无数据时返回一段说明性 HTML。
    """
    nodes = graph.get("nodes") or []
    links = graph.get("links") or []
    cluster = graph.get("cluster") or {}
    center = graph.get("center") or ""

    if not nodes:
        return (
            "<div style='padding:16px;color:#718096;'>"
            "该词没有可展示的词簇图谱（可能是未收录词，或数据库不可用）。"
            "</div>"
        )

    truncated_for_draw = len(nodes) > max_draw_nodes
    if truncated_for_draw:
        keep = {center}
        for other in sorted(n["id"] for n in nodes if n["id"] != center):
            if len(keep) >= max_draw_nodes:
                break
            keep.add(other)
        nodes = [n for n in nodes if n["id"] in keep]

    if highlight_only_center and center:
        links = [l for l in links if center in (l["source"], l["target"])]

    members = [n["id"] for n in nodes]
    pos = _layout(members, center)

    small = len(members) <= SMALL_CLUSTER
    node_r = NODE_R_DEFAULT if small else 10
    stroke_w = 1.4 if len(members) <= SMALL_CLUSTER else 0.7
    edge_color = "rgba(118, 75, 162, 0.30)" if small else "rgba(118, 75, 162, 0.12)"

    parts: List[str] = []
    parts.append(
        f'<svg viewBox="0 0 {CANVAS_W} {CANVAS_H}" width="100%" '
        f'style="max-width:{CANVAS_W}px;background:#fdfcff;border:1px solid #e2e8f0;'
        f'border-radius:12px;" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{_esc(center)} 的词簇完全图">'
    )

    # --- 边（先画，压在节点下面）---
    parts.append(f'<g stroke="{edge_color}" stroke-width="{stroke_w}">')
    for link in links:
        a, b = link["source"], link["target"]
        if a not in pos or b not in pos:
            continue
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
        )
    parts.append("</g>")

    # --- 节点 ---
    for node in nodes:
        verb = node["id"]
        x, y = pos[verb]
        is_center = bool(node.get("is_center"))
        r = NODE_R_CENTER if is_center else node_r
        fill = "#764ba2" if is_center else "#9f7aea"
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" '
            f'stroke="#ffffff" stroke-width="2">'
            f"<title>{_esc(verb)}{'（当前查询词）' if is_center else ''}</title>"
            f"</circle>"
        )

        # 标签：小簇全标；大簇只标中心词（其余靠 hover）
        if small or is_center:
            anchor = _label_anchor(x)
            dy = -r - 6 if is_center else -node_r - 5
            weight = "700" if is_center else "500"
            color = "#553c9a" if is_center else "#4a5568"
            parts.append(
                f'<text x="{x:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}" '
                f'font-size="{LABEL_FONT_SIZE}" font-weight="{weight}" '
                f'fill="{color}">{_esc(verb)}</text>'
            )

    parts.append("</svg>")

    # --- 图注：如实交代规模 ---
    notes = []
    if cluster:
        notes.append(
            f"词簇 <strong>{_esc(cluster.get('label', ''))}</strong>"
            f"（{_esc(cluster.get('sub_cat', ''))}）"
        )
        notes.append(f"簇内共 <strong>{cluster.get('size', len(nodes))}</strong> 个动词")
    notes.append(f"当前绘制 <strong>{len(nodes)}</strong> 个节点 / <strong>{len(links)}</strong> 条边")
    if graph.get("complete_edge_count"):
        notes.append(f"完全图边数 C(n,2) = <strong>{graph['complete_edge_count']}</strong>")
    if graph.get("truncated"):
        notes.append("⚠️ 已按上限截断绘制")
    if highlight_only_center:
        notes.append("当前只显示与中心词相连的边")
    if truncated_for_draw:
        notes.append(f"⚠️ 节点数超过绘制上限 {max_draw_nodes}，只画了中心词及部分邻居")

    caption = (
        "<div style='font-size:0.85em;color:#718096;line-height:1.9;'>"
        + " · ".join(notes)
        + "<br/>节点=动词；边=近义关系（同一次语义范畴内两两相连，即完全图）；"
        + "紫色实心大圆=当前查询词；鼠标悬停节点可看词名。"
        + "</div>"
    )

    return "".join(parts) + caption
