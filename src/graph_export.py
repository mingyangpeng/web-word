"""
交互式词间关系图谱 —— graphify 风格的力导向图。

## 与 cluster_graph.py 的分工

| 模块 | 形态 | 用途 |
|------|------|------|
| `cluster_graph.py` | 内联 SVG，静态 | 单个词的簇：节点少、要一眼看清「谁和谁相连」 |
| 本模块 | vis-network 力导向图，可交互 | 全局语义地图：155 词 / 2143 边，要能搜、能点、能过滤 |

## 为什么要生成静态 HTML 文件，而不是每次 components.html(html)

Streamlit 每次交互都会重跑整个脚本。如果用 `components.html(html_string)`，
每次重跑都会把 iframe 内容重新写一遍 —— 图谱的力导向布局会**从零重新收敛**，
用户刚拖好的节点位置、选中的节点、缩放的视野全部丢失。

graphify 自己的做法就是产出一个静态 `graph.html` 让浏览器打开。这里沿用同一思路：
把图谱数据渲染成一个**静态 HTML 文件**放进 `src/static/`，由 Streamlit 的
静态文件服务托管，页面用 `components.iframe(url)` 嵌进来。

文件名带上**数据指纹**（`word_graph_<hash>.html`）：
  * 数据没变 → URL 不变 → 浏览器不重新加载 → 布局与交互状态保留；
  * 数据变了（重新灌库）→ URL 变 → 自动加载新图。

## 为什么不用 CDN

vis-network 从本地 `src/static/` 加载（`/app/static/vis-network.min.js`）。
本项目已确立「零网络依赖」原则：灌库脚本离线可用、无 API key 时降级、无数据库时降级。
CDN 在内网或断网环境下会渲染成一片空白，而一个永远打得开的图谱比一个时髦的图谱重要。
"""

import hashlib
import html
import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# vis-network 静态资源与产物的目录（主脚本 src/app.py 的同级 static/）
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
VIS_LIB = "vis-network.min.js"

# Tab20 调色板（与 graphify 图例同源），按簇循环取色
PALETTE = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    "#8CD17D", "#B6992D", "#499894", "#FABFD2", "#D4A6C8",
    "#86BCB6", "#79706E", "#D37295", "#B07AA1", "#A0CBE8",
]


def _esc(text: Any) -> str:
    """HTML 转义。节点名来自数据库，仍按不可信内容处理。"""
    return html.escape(str(text), quote=True)


def _esc_js(text: Any) -> str:
    """
    转义为可安全嵌进 JS 字符串字面量的内容。

    用 json.dumps 而不是手写替换：它同时处理引号、反斜杠、换行与 Unicode，
    而手工 replace 很容易漏掉某一个（graphify #1838 就是节点 id 里的引号
    打穿了 onclick 属性导致的存储型 XSS）。
    """
    return json.dumps(str(text), ensure_ascii=False)


# 模板版本号。**改动 _TEMPLATE 时务必手动 +1。**
#
# 为什么要它：产物文件名原本只由数据决定（节点/边集合的哈希）。于是「改了模板
# 但数据没变」时 URL 不变 —— 浏览器和 Streamlit 都认为文件没换，页面继续跑旧渲染
# 逻辑，改了前端却看不到任何变化，而且重启进程也不一定有用（磁盘上还是旧文件）。
# 把版本号并进指纹后，改模板即产生新 URL，旧文件被自动清理。
TEMPLATE_VERSION = 22


def data_fingerprint(graph: Dict[str, Any]) -> str:
    """
    图谱产物指纹 = 数据（节点/边集合） + 模板版本。

    两者都要参与：
      * 数据变了 → 需要重绘（重新灌库后词表/边集不同）；
      * 模板变了 → 也需要重绘（否则页面跑的是旧渲染代码，改了看不见）。
    """
    payload = json.dumps(
        {
            "v": TEMPLATE_VERSION,
            "nodes": sorted(n["id"] for n in graph.get("nodes", [])),
            "edges": sorted(
                f"{l['source']}-{l['target']}" for l in graph.get("links", [])
            ),
            # 节点全量载荷（释义/义项/音标/标注）也要进指纹：
            # 否则"只更新释义不增删词"的灌库不会刷新图谱页。
            # 节点按 id 排序后再哈希 —— 指纹必须行序无关（见测试契约）。
            "data": hashlib.sha256(
                json.dumps(
                    sorted(graph.get("nodes", []), key=lambda n: str(n.get("id"))),
                    ensure_ascii=False, sort_keys=True, default=str,
                ).encode("utf-8")
            ).hexdigest(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _assign_colors(clusters: List[Dict[str, Any]]) -> Dict[str, str]:
    """按簇 id 稳定分配颜色（同一次渲染内一致，跨渲染也稳定）。"""
    colors: Dict[str, str] = {}
    for i, cluster in enumerate(clusters):
        colors[str(cluster["id"])] = PALETTE[i % len(PALETTE)]
    return colors


def build_graph_html(graph: Dict[str, Any], title: str = "词间关系知识图谱") -> str:
    """
    把 `get_full_word_graph()` 的输出渲染成一个**独立可打开的 HTML 文件**。

    结构对齐 graphify 的 graph.html：左侧力导向图，右侧栏依次是
    搜索框 / 节点信息面板 / 簇图例（可勾选过滤）/ 底部统计。

    Args:
        graph: `src.mysql_db.get_full_word_graph()` 的返回值
        title: 页面标题

    Returns:
        完整的 HTML 字符串
    """
    nodes = graph.get("nodes", [])
    links = graph.get("links", [])
    clusters = graph.get("clusters", [])
    stats = graph.get("stats", {})
    colors = _assign_colors(clusters)

    # 节点：大小按度数（簇内完全图下度数 = 簇大小-1，所以大小实际表示「簇有多大」）
    max_degree = max((n.get("degree", 0) for n in nodes), default=1) or 1
    vis_nodes = []
    for n in nodes:
        cid = str(n.get("cluster_id") or "none")
        color = colors.get(cid, "#BAB0AC")
        # 半径 8~34 之间映射，避免最大簇把其它节点压成点
        size = 8 + 26 * (n.get("degree", 0) / max_degree) ** 0.6
        vis_nodes.append({
            "id": n["id"],
            "label": n["label"],
            "color": {"background": color, "border": "#ffffff"},
            "size": round(size, 1),
            "title": f"{_esc(n['label'])} · {_esc(n.get('cluster_label', ''))}"
                     f" · {n.get('degree', 0)} 条近义边",
            "_clusterId": cid,
            "_clusterLabel": n.get("cluster_label") or "未分组",
            "_subCat": n.get("sub_cat") or "未分组",
            "_mainCat": n.get("main_cat") or "",
            "_degree": n.get("degree", 0),
            # 明细：只给右侧信息面板与浮层卡片用，vis 不读这些键。
            # 缺的字段一律给空值而不是省略 —— 前端靠「有没有这个键」区分
            # 「确实没有数据」和「payload 忘了带」，省略会让两者看起来一样。
            "_d": {
                "pos": n.get("pos") or "v",
                "phonetic": n.get("phonetic") or "",
                "chinese_ndef": n.get("chinese_ndef") or "",
                "en_ndef": n.get("en_ndef") or "",
                "semantic_table": n.get("semantic_table") or {},
                "example_sentence": n.get("example_sentence") or "",
                "image_schema": n.get("image_schema") or "",
                "prototype_level": n.get("prototype_level") or "",
                "alignment": n.get("alignment") or "",
                "cn_syntax": n.get("cn_syntax") or "",
                "translation_strategy": n.get("translation_strategy") or "",
                "definition_source": n.get("definition_source") or "",
                "source_rank": n.get("source_rank"),
                "sense_count": n.get("sense_count") or 0,
                "sense_brief": n.get("sense_brief") or "",
                "judge_reason": n.get("judge_reason") or "",
                "levin_source": n.get("levin_source") or "",
                "cross_subclass": n.get("cross_subclass") or "",
                "needs_review": int(n.get("needs_review") or 0),
                "cluster_image_schema": n.get("cluster_image_schema") or "",
                "cluster_cn_syntax": n.get("cluster_cn_syntax") or "",
                "cluster_translation_strategy": n.get("cluster_translation_strategy") or "",
                "senses": n.get("senses") or [],
                "oald_senses": n.get("oald_senses") or [],
            },
        })

    # 边：完全图边多且密，统一细线 + 低透明度，选中时才凸显
    vis_edges = [
        {
            "id": i,
            "from": l["source"],
            "to": l["target"],
            "color": {"color": "rgba(140,140,200,0.18)", "highlight": "#EDC948"},
            "width": 0.6,
        }
        for i, l in enumerate(links)
    ]

    legend = []
    for c in clusters:
        cid = str(c["id"])
        legend.append({
            "cid": cid,
            "color": colors.get(cid, "#BAB0AC"),
            "label": c["label"],
            "size": c["size"],
        })

    return _render_template({
        "TITLE": _esc(title),
        "VIS_LIB": _esc(VIS_LIB),
        # "</" 必须转义成 "<\/"：json.dumps 不转义斜杠，节点字段里若含
        # "</script>" 字面量会提前终结 <script> 元素（页面损坏/注入）。
        "NODES_JSON": json.dumps(vis_nodes, ensure_ascii=False).replace("</", "<\\/"),
        "EDGES_JSON": json.dumps(vis_edges, ensure_ascii=False).replace("</", "<\\/"),
        "LEGEND_JSON": json.dumps(legend, ensure_ascii=False).replace("</", "<\\/"),
        "NODE_COUNT": str(stats.get("node_count", len(nodes))),
        "EDGE_COUNT": str(stats.get("edge_count", len(links))),
        "CLUSTER_COUNT": str(stats.get("cluster_count", len(clusters))),
    })


def _render_template(values: Dict[str, str]) -> str:
    """
    用 __TOKEN__ 占位符做替换，而不是 str.format()。

    模板几乎全是 JavaScript，里面有大量 `{` `}`（对象字面量、模板字符串 ${}）。
    用 .format() 就必须把每一处都写成 `{{` `}}`，漏一个就抛 KeyError 或静默
    产出坏 JS；而 JS 模板字符串里的 `${...}` 恰好是 .format 的替换字段语法，
    冲突尤其隐蔽。占位符替换没有这个问题。
    """
    out = _TEMPLATE
    for key, val in values.items():
        out = out.replace(f"__{key}__", val)
    return out


def ensure_graph_html(graph: Dict[str, Any], force: bool = False) -> str:
    """
    确保静态图谱文件存在，返回可供 iframe 使用的 URL 路径。

    文件名含数据指纹，所以数据没变时重复调用不会重写文件、也不会让 iframe 重载。

    Args:
        graph: `get_full_word_graph()` 的返回值
        force: 忽略缓存强制重写

    Returns:
        形如 `/app/static/word_graph_<hash>.html` 的 URL；写入失败时返回空串
    """
    if not graph.get("nodes"):
        return ""

    fp = data_fingerprint(graph)
    filename = f"word_graph_{fp}.html"
    path = os.path.join(STATIC_DIR, filename)

    try:
        os.makedirs(STATIC_DIR, exist_ok=True)
        if force or not os.path.exists(path):
            # 先写临时文件再原子替换 —— 直接写目标文件时，中途崩溃会留下
            # 残缺 HTML，而存在性检查会让它被永久复用
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(build_graph_html(graph))
            os.replace(tmp_path, path)
            logger.info(f"交互式图谱已生成: {filename}")
            _prune_old_graphs(keep=filename)
        return f"/app/static/{filename}"
    except OSError as e:
        logger.error(f"写入交互式图谱失败: {e}")
        return ""


def _prune_old_graphs(keep: str) -> None:
    """删掉旧指纹的图谱文件，避免 static/ 越积越多。"""
    try:
        for name in os.listdir(STATIC_DIR):
            if name.startswith("word_graph_") and name.endswith(".html") and name != keep:
                os.remove(os.path.join(STATIC_DIR, name))
    except OSError as e:
        logger.warning(f"清理旧图谱文件失败: {e}")


# ============================================
# HTML 模板
# ============================================
# 结构与 graphify 的 graph.html 一致：主体是 vis-network 画布，右侧栏依次是
# 搜索 / 信息面板 / 图例 / 统计。视觉沿用它的暗色配色。
_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>__TITLE__</title>
<script src="/app/static/__VIS_LIB__"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e0e0e0; display: flex; height: 100vh;
         overflow: hidden; font-family: system-ui, -apple-system, "Segoe UI",
         "PingFang SC", "Microsoft YaHei", sans-serif; }
  /* #graph 现在包在 #graph-wrap 里（wrap 负责相对定位与 flex 占位），
     所以它只要撑满 wrap 即可 */
  #graph { position: absolute; inset: 0; background: #0f0f1a; }
  #sidebar { width: 300px; background: #1a1a2e; border-left: 1px solid #2a2a4e;
             display: flex; flex-direction: column; overflow: hidden; }
  #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
  #search { width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e;
            color: #e0e0e0; padding: 7px 10px; border-radius: 6px;
            font-size: 13px; outline: none; }
  #search:focus { border-color: #4E79A7; }
  #search-results { max-height: 150px; overflow-y: auto; padding: 0 12px;
                    display: none; border-bottom: 1px solid #2a2a4e; }
  .search-item { padding: 5px 6px; cursor: pointer; border-radius: 4px; font-size: 12px;
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .search-item:hover { background: #2a2a4e; }
  #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 150px;
                max-height: 48vh; overflow-y: auto; }
  #info-panel h3 { font-size: 12px; color: #aaa; margin-bottom: 8px;
                   text-transform: uppercase; letter-spacing: 0.06em; }
  #info-content { font-size: 13px; color: #ccc; line-height: 1.65; }
  #info-content .field { margin-bottom: 5px; }
  #info-content .field b { color: #fff; }
  #info-content .empty { color: #555; font-style: italic; }
  #neighbors-list { max-height: 170px; overflow-y: auto; margin-top: 4px; }
  .neighbor-link { display: block; padding: 3px 6px; margin: 2px 0; border-radius: 3px;
                   cursor: pointer; font-size: 12px; white-space: nowrap;
                   overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
  .neighbor-link:hover { background: #2a2a4e; }
  #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
  #legend-wrap h3 { font-size: 12px; color: #aaa; margin-bottom: 10px;
                    text-transform: uppercase; letter-spacing: 0.06em; }
  #legend-controls { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  #legend-controls label { display: flex; align-items: center; gap: 6px; cursor: pointer;
                           font-size: 12px; color: #aaa; user-select: none; }
  #legend-controls label:hover { color: #e0e0e0; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 0;
                 cursor: pointer; border-radius: 4px; font-size: 12px; }
  .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
  .legend-item.dimmed { opacity: 0.35; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
  .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend-count { color: #666; font-size: 11px; }
  .legend-cb, #select-all-cb { appearance: none; -webkit-appearance: none; width: 14px;
      height: 14px; border: 1.5px solid #3a3a5e; border-radius: 3px; background: #0f0f1a;
      cursor: pointer; position: relative; flex-shrink: 0; }
  .legend-cb:checked, #select-all-cb:checked { background: #4E79A7; border-color: #4E79A7; }
  .legend-cb:checked::after, #select-all-cb:checked::after {
      content: ''; position: absolute; left: 3.5px; top: 1px; width: 4px; height: 7px;
      border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg); }
  #stats { padding: 10px 14px; border-top: 1px solid #2a2a4e; font-size: 11px; color: #666;
           line-height: 1.7; }
  #hint { padding: 8px 14px; font-size: 11px; color: #555;
          border-top: 1px solid #2a2a4e; line-height: 1.7; }
  #graph-wrap { position: relative; flex: 1; overflow: hidden; }
  #particles { position: absolute; inset: 0; pointer-events: none; z-index: 2; }
  #toolbar { position: absolute; top: 12px; left: 12px; z-index: 5;
             display: flex; gap: 8px; align-items: center; }
  .tool-btn { background: rgba(26,26,46,0.92); border: 1px solid #3a3a5e; color: #d0d0e0;
              padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer;
              display: flex; align-items: center; gap: 6px; user-select: none;
              transition: background 0.15s, border-color 0.15s; }
  .tool-btn:hover { background: #2a2a4e; border-color: #4E79A7; color: #fff; }
  .tool-btn.on { background: #4E79A7; border-color: #6F9BC7; color: #fff; }
  .tool-btn .dot { width: 7px; height: 7px; border-radius: 50%; background: #59A14F; }
  .tool-btn.on .dot { background: #EDC948; }
  #particle-info { background: rgba(26,26,46,0.92); border: 1px solid #3a3a5e;
                   color: #aaa; padding: 6px 12px; border-radius: 6px; font-size: 11px; }
  /* ---------- 浮层卡片（词条 / 关系）----------
     与右侧面板同源：两者都调用同一个渲染函数，所以内容天然一致。
     卡片是 position:absolute 挂在 #graph-wrap 里，全屏时也跟着图谱一起放大。 */
  .float-card { position: absolute; z-index: 20; width: 384px; max-height: 78vh;
                background: rgba(18,18,34,0.985); border: 1px solid #3a3a5e;
                border-radius: 10px; box-shadow: 0 14px 40px rgba(0,0,0,0.6);
                display: flex; flex-direction: column; overflow: hidden; }
  .float-card.hidden { display: none; }
  .fc-head { display: flex; align-items: center; gap: 7px; padding: 9px 11px;
             background: #1f1f38; border-bottom: 1px solid #2a2a4e;
             cursor: move; user-select: none; touch-action: none; }
  .fc-title { flex: 1; font-size: 13px; color: #fff; font-weight: 600;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fc-btn { background: transparent; border: 1px solid #3a3a5e; color: #aaa;
            min-width: 22px; height: 22px; border-radius: 5px; cursor: pointer;
            font-size: 12px; line-height: 1; padding: 0 4px; }
  .fc-btn:hover { background: #2a2a4e; color: #fff; }
  .fc-btn.on { background: #EDC948; border-color: #EDC948; color: #1a1a2e; }
  .fc-body { padding: 12px; overflow-y: auto; font-size: 12.5px; color: #ccc; line-height: 1.7; }
  .fc-row { margin-bottom: 7px; }
  .fc-row > .k { color: #7f7fa8; font-size: 11px; display: block; }
  .fc-row > .v { color: #dcdce8; word-break: break-word; }
  .fc-sec { border-top: 1px solid #2a2a4e; margin: 11px 0 8px; padding-top: 8px;
            color: #7f7fa8; font-size: 11px; letter-spacing: 0.06em; }
  .fc-sec:first-child { border-top: none; margin-top: 0; padding-top: 0; }
  .fc-sense { border-left: 3px solid #3a3a5e; padding: 3px 0 3px 8px; margin-bottom: 9px; }
  /* 习语义项压暗 + 边框变暖：它们不是该词的位移义，扫一眼就能跳过 */
  .fc-sense.fc-idiom { border-left-color: #7a6a3a; opacity: 0.78; }
  .fc-sense .idx { color: #7f7fa8; font-size: 11px; }
  .fc-ex { color: #9a9ac0; font-style: italic; margin-top: 3px; }
  .fc-miss { color: #6a6a8a; font-style: italic; }
  .fc-note { width: 100%; box-sizing: border-box; background: #0f0f1a; color: #dcdce8;
             border: 1px solid #3a3a5e; border-radius: 6px; padding: 6px 8px;
             font-size: 12px; resize: vertical; min-height: 54px; font-family: inherit; }
  .fc-link { color: #8FB8E0; cursor: pointer; border-bottom: 1px dotted #4a6a8a; }
  .fc-link:hover { color: #fff; }
  /* 全屏时容器由浏览器撑满屏幕，这里只要保证布局跟着变 */
  body:fullscreen #sidebar { width: 320px; }
  /* 360 粒子在 155 节点上，节点本身不需要再发光抢焦点 */
  #graph canvas { outline: none; }
</style>
</head>
<body>
<div id="graph-wrap">
  <div id="graph"></div>
  <canvas id="particles"></canvas>
  <div class="float-card hidden" id="word-card" style="left:24px; top:64px;">
    <div class="fc-head" id="word-card-head">
      <span class="fc-title" id="word-card-title">词条详情</span>
      <button class="fc-btn" id="word-card-star" title="收藏该词条">★</button>
      <button class="fc-btn" id="word-card-close" title="关闭">✕</button>
    </div>
    <div class="fc-body" id="word-card-body"></div>
  </div>

  <div class="float-card hidden" id="edge-card" style="left:432px; top:96px;">
    <div class="fc-head" id="edge-card-head">
      <span class="fc-title" id="edge-card-title">关系详情</span>
      <button class="fc-btn" id="edge-card-star" title="收藏该关系">★</button>
      <button class="fc-btn" id="edge-card-close" title="关闭">✕</button>
    </div>
    <div class="fc-body" id="edge-card-body"></div>
  </div>

  <div id="toolbar">
    <button class="tool-btn on" id="btn-particles"><span class="dot"></span>节点粒子</button>
    <span id="particle-info">—</span>
    <button class="tool-btn" id="btn-fullscreen">⛶ 全屏</button>
  </div>
</div>
<div id="sidebar">
  <div id="search-wrap">
    <input id="search" type="text" placeholder="搜索动词…" autocomplete="off"/>
  </div>
  <div id="search-results"></div>

  <div id="info-panel">
    <h3>节点信息</h3>
    <div id="info-content"><span class="empty">点击任意节点查看详情</span></div>
  </div>

  <div id="legend-wrap">
    <h3>语义簇（可勾选过滤）</h3>
    <div id="legend-controls">
      <label><input type="checkbox" id="select-all-cb" checked/> 全选</label>
      <label><input type="checkbox" id="focus-cb" checked/> 高亮邻居</label>
    </div>
    <div id="legend"></div>
  </div>

  <div id="stats"></div>
  <div id="hint">滚轮缩放 · 拖拽平移 · 悬停看节点 · 点击看邻居<br/>节点即粒子：相互引力斥力 · 带阻尼</div>
</div>

<script>
const RAW_NODES = __NODES_JSON__;
const RAW_EDGES = __EDGES_JSON__;
const LEGEND = __LEGEND_JSON__;
const TOTAL_NODES = __NODE_COUNT__, TOTAL_EDGES = __EDGE_COUNT__,
      TOTAL_CLUSTERS = __CLUSTER_COUNT__;

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const nodesDS = new vis.DataSet(RAW_NODES.map(n => Object.assign({}, n)));
const edgesDS = new vis.DataSet(RAW_EDGES.map(e => Object.assign({}, e)));

const container = document.getElementById('graph');
const network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, {
  physics: {
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {
      gravitationalConstant: -60,
      centralGravity: 0.005,
      springLength: 120,
      springConstant: 0.08,
      damping: 0.4,
      avoidOverlap: 0.8,
    },
    stabilization: { iterations: 200, fit: true },
  },
  interaction: {
    hover: true,
    tooltipDelay: 100,
    hideEdgesOnDrag: true,
    navigationButtons: false,
    keyboard: false,
  },
  nodes: { shape: 'dot', borderWidth: 1.5, font: { color: '#d0d0e0', size: 12 } },
  edges: { smooth: { type: 'continuous', roundness: 0.2 }, selectionWidth: 3 },
});

// 布局收敛后关掉物理引擎：节点不再乱动，用户拖动的位置才留得住
network.once('stabilizationIterationsDone', () => {
  network.setOptions({ physics: { enabled: false } });
});

// ---------- 图例过滤 ----------
const enabled = new Set(LEGEND.map(c => String(c.cid)));

function renderLegend() {
  document.getElementById('legend').innerHTML = LEGEND.map(c => {
    const on = enabled.has(String(c.cid));
    return '<div class="legend-item' + (on ? '' : ' dimmed') + '" data-cid="' + esc(c.cid) + '">'
      + '<input type="checkbox" class="legend-cb" data-cid="' + esc(c.cid) + '"'
      + (on ? ' checked' : '') + '/>'
      + '<span class="legend-dot" style="background:' + esc(c.color) + '"></span>'
      + '<span class="legend-label" title="' + esc(c.label) + '">' + esc(c.label) + '</span>'
      + '<span class="legend-count">' + c.size + '</span></div>';
  }).join('');
  const all = document.getElementById('select-all-cb');
  all.checked = enabled.size === LEGEND.length;
  all.indeterminate = enabled.size > 0 && enabled.size < LEGEND.length;
}

// 图谱状态变化的通知钩子。粒子层注册进来，避免用「重新赋值函数」这种脆弱写法
// （依赖调用时机，且容易漏掉某条调用路径）。
const graphChangeHooks = [];
function notifyGraphChanged() {
  graphChangeHooks.forEach(fn => { try { fn(); } catch (e) { /* 钩子失败不影响主流程 */ } });
}

function applyFilter() {
  nodesDS.update(RAW_NODES.map(n => ({ id: n.id, hidden: !enabled.has(n._clusterId) })));
  edgesDS.update(RAW_EDGES.map(e => ({
    id: e.id,
    hidden: !(enabled.has(nodesDS.get(e.from)._clusterId)
              && enabled.has(nodesDS.get(e.to)._clusterId)),
  })));
  updateStats();
  renderLegend();
  notifyGraphChanged();
}

function updateStats() {
  let sn = 0, se = 0;
  const shownIds = new Set();
  RAW_NODES.forEach(n => { if (enabled.has(n._clusterId)) { sn++; shownIds.add(n.id); } });
  RAW_EDGES.forEach(e => { if (shownIds.has(e.from) && shownIds.has(e.to)) se++; });
  document.getElementById('stats').innerHTML =
    '节点 ' + sn + ' / ' + TOTAL_NODES + ' · 关系 ' + se + ' / ' + TOTAL_EDGES
    + '<br/>语义簇 ' + enabled.size + ' / ' + TOTAL_CLUSTERS;
}

document.addEventListener('click', e => {
  const cb = e.target.closest('.legend-cb');
  if (cb) {
    const cid = cb.dataset.cid;
    if (cb.checked) enabled.add(cid); else enabled.delete(cid);
    applyFilter();
    return;
  }
  const item = e.target.closest('.legend-item');
  if (item) {
    const cid = item.dataset.cid;
    if (enabled.has(cid)) enabled.delete(cid); else enabled.add(cid);
    applyFilter();
    return;
  }
  const nb = e.target.closest('.neighbor-link');
  if (nb && nb.dataset.nid !== undefined) focusNode(nb.dataset.nid);
});

document.getElementById('select-all-cb').addEventListener('change', e => {
  enabled.clear();
  if (e.target.checked) LEGEND.forEach(c => enabled.add(String(c.cid)));
  applyFilter();
});

// ---------- 搜索 ----------
const searchEl = document.getElementById('search');
const resultsEl = document.getElementById('search-results');

searchEl.addEventListener('input', () => {
  const q = searchEl.value.trim().toLowerCase();
  if (!q) { resultsEl.style.display = 'none'; return; }
  const hits = RAW_NODES.filter(n => n.label.toLowerCase().indexOf(q) >= 0).slice(0, 30);
  resultsEl.innerHTML = hits.length
    ? hits.map(n => '<div class="search-item" data-nid="' + esc(n.id) + '">'
        + esc(n.label) + '</div>').join('')
    : '<div class="search-item" style="color:#666">无匹配</div>';
  resultsEl.style.display = 'block';
});

resultsEl.addEventListener('click', e => {
  const item = e.target.closest('.search-item');
  if (!item || item.dataset.nid === undefined) return;
  resultsEl.style.display = 'none';
  const n = nodesDS.get(item.dataset.nid);
  searchEl.value = n ? n.label : '';
  focusNode(item.dataset.nid);
});

// ---------- 收藏 / 备注 ----------
// 图谱页是 iframe 里的静态 HTML，没有回写服务端的通道，所以收藏与备注存在浏览器
// 本地（localStorage）。右侧面板与浮层卡片读的是同一份 store，因此天然同步。
// localStorage 在无痕模式或被沙箱限制时会抛异常 —— 那时退回内存 store，
// 功能在当前会话内照常可用，只是关掉页面就没了（这是有意的降级，不是静默失败）。
const STORE_KEY = 'wordgraph.annotations.v1';
let memStore = {};
let store = null;
function loadStore() {
  if (store) return store;
  try {
    store = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {};
  } catch (e) {
    store = memStore;
  }
  return store;
}
function annGet(kind, key) {
  const bucket = loadStore()[kind] || {};
  return bucket[key] || { star: false, note: '' };
}
function annSet(kind, key, patch) {
  const st = loadStore();
  st[kind] = st[kind] || {};
  st[kind][key] = Object.assign({}, st[kind][key] || { star: false, note: '' }, patch);
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(st));
  } catch (e) {
    memStore = st;
    store = st;
  }
  return st[kind][key];
}

// ---------- 渲染小工具 ----------
let currentNodeId = null;
let currentEdgeId = null;
let renderedWordId = null;    // 卡片当前渲染的是哪个词，用来避免重复重建
let renderedEdgeId = null;

function sec(t) { return '<div class="fc-sec">' + esc(t) + '</div>'; }
/** k 是字段名（转义），v 是**纯文本**（转义后输出）。 */
function plainRow(k, v) {
  if (v === undefined || v === null || v === '') return '';
  return '<div class="fc-row"><span class="k">' + esc(k) + '</span>'
       + '<span class="v">' + esc(v) + '</span></div>';
}
function missRow(text) {
  return '<div class="fc-row"><span class="v fc-miss">' + esc(text) + '</span></div>';
}
function neighborChips(ids) {
  return ids.map(id => {
    const x = nodesDS.get(id);
    if (!x) return '';
    return '<span class="neighbor-link" style="border-left-color:' + esc(x.color.background)
      + '" data-nid="' + esc(id) + '">' + esc(x.label) + '</span>';
  }).join('');
}

// 五元语义分解的键与中文名。aspect / scope 在库中 136 词全为空，所以下面会把
// 「空的那几项」显式列出来并说明原因 —— 静默省略会让人以为这个词没有体相/范围。
const SEMA_KEYS = [['manner', '方式'], ['path', '路径'], ['direction', '方向'],
                   ['aspect', '体相'], ['scope', '范围']];

const ADJ = new Map();
RAW_EDGES.forEach(e => {
  if (!ADJ.has(e.from)) ADJ.set(e.from, new Set());
  if (!ADJ.has(e.to)) ADJ.set(e.to, new Set());
  ADJ.get(e.from).add(e.to);
  ADJ.get(e.to).add(e.from);
});

function senseHTML(s) {
  let h = '<div class="fc-sense"><span class="idx">义位 ' + s.sense_index + '</span><br/>'
        + esc(s.ch_ndef || '（无中文释义）');
  if (s.en_ndef) h += '<div class="fc-ex">' + esc(s.en_ndef) + '</div>';
  if (s.construction) h += '<div class="fc-ex">句式：' + esc(s.construction) + '</div>';
  const exs = s.examples || [], chs = s.ch_examples || [];
  for (let i = 0; i < exs.length; i++) {
    h += '<div class="fc-ex">· ' + esc(exs[i])
       + (chs[i] ? '<br/>&nbsp;&nbsp;' + esc(chs[i]) : '') + '</div>';
  }
  if (s.synonyms && s.synonyms.length) h += '<div class="fc-ex">近义：' + esc(s.synonyms.join('、')) + '</div>';
  if (s.antonyms && s.antonyms.length) h += '<div class="fc-ex">反义：' + esc(s.antonyms.join('、')) + '</div>';
  return h + '</div>';
}

/**
 * 渲染一条 OALD 义项。
 *
 * 语法码（`grammar`）单独一行**不省**：`[transitive]` 决定这个义项能不能带宾语，
 * 是研究者判断英汉对齐时必须看的证据 —— 它是从释义正文里剥下来的，剥掉不等于丢掉。
 * 习语义项打标并压暗：OALD 把 IDIOMS 排在最后，它们的「释义」常是整句习语的解释
 * 而非该词的位移义，混在普通义项里看不出区别。
 */
function oaldSenseHTML(s) {
  let h = '<div class="fc-sense' + (s.is_idiom ? ' fc-idiom' : '') + '">'
        + '<span class="idx">义项 ' + s.sense_index
        + (s.sense_group ? ' · ' + esc(s.sense_group) : '')
        + (s.is_idiom ? ' · 习语' : '') + '</span><br/>'
        + esc(s.definition || '（无释义）');
  if (s.grammar) h += '<div class="fc-ex">语法：' + esc(s.grammar) + '</div>';
  const exs = s.examples || [], pats = s.example_patterns || [];
  for (let i = 0; i < exs.length; i++) {
    h += '<div class="fc-ex">· ' + (pats[i] ? '<' + esc(pats[i]) + '> ' : '') + esc(exs[i]) + '</div>';
  }
  return h + '</div>';
}

/**
 * 词条明细。**右侧面板与浮层卡片共用这一个函数**（compact=true 是面板），
 * 这样「两处数据一致」不是靠两段代码小心翼翼地对齐，而是结构上只有一份数据。
 */
function nodeDetailHTML(n, compact) {
  const d = n._d || {};
  const nb = network.getConnectedNodes(n.id).filter(id => !nodesDS.get(id).hidden);
  let h = '<div class="fc-row"><span class="v" style="font-size:16px;color:#fff;font-weight:600">'
        + esc(n.label) + '</span></div>';
  if (d.phonetic) {
    h += plainRow('音标', '/' + d.phonetic + '/');
  } else {
    h += '<div class="fc-row"><span class="k">音标</span>'
       + '<span class="v fc-miss">未收录</span></div>';
  }
  h += plainRow('词性', d.pos === 'v' ? 'v. 动词' : (d.pos || ''));
  h += plainRow('语义簇', n._clusterLabel + '（次范畴：' + n._subCat + '）');
  h += plainRow('主范畴', n._mainCat);

  h += sec('释义');
  h += '<div class="fc-row"><span class="v">' + esc(d.chinese_ndef || '—') + '</span></div>';
  if (d.en_ndef) h += '<div class="fc-ex">' + esc(d.en_ndef) + '</div>';
  if (d.sense_brief) h += plainRow('原型义要点', d.sense_brief);

  h += sec('意象与标注');
  h += plainRow('意象图式', d.image_schema);
  h += plainRow('原型层级', d.prototype_level === 'Y' ? 'Y（原型义）' : d.prototype_level);
  h += plainRow('英汉对齐', d.alignment);
  h += plainRow('汉语句法', d.cn_syntax);
  h += plainRow('译义策略', d.translation_strategy);

  if (!compact) {
    const st = d.semantic_table || {};
    const filled = SEMA_KEYS.filter(kv => String(st[kv[0]] || '').trim());
    if (filled.length) {
      h += sec('五元语义分解');
      filled.forEach(kv => { h += plainRow(kv[1], st[kv[0]]); });
      const empty = SEMA_KEYS.filter(kv => !String(st[kv[0]] || '').trim()).map(kv => kv[1]);
      if (empty.length) {
        h += missRow(empty.join('、') + '：库中 136 词全部为空，暂无数据');
      }
    }
    // 两个来源的义项**分节展示**，不合并成一个列表：它们的切分体系不同，
    // 合并后会让人以为「第 1 条」和「第 1 条」是同一个义项。
    const senses = d.senses || [];
    const oald = d.oald_senses || [];
    h += sec('中英对照义位（' + senses.length + '）');
    if (senses.length) {
      senses.forEach(x => { h += senseHTML(x); });
    } else {
      h += missRow('该词没有中英对照义位（dictionary.db 只有 333 个动词词条，'
        + '与这 136 词重合 9 个）');
      if (d.example_sentence) h += '<div class="fc-ex">· ' + esc(d.example_sentence) + '</div>';
    }
    h += sec('OALD10 义项（' + oald.length + '）');
    if (oald.length) {
      oald.forEach(x => { h += oaldSenseHTML(x); });
    } else {
      h += missRow('OALD 导出表里查不到该词的动词义项（136 词中有 4 个这样：'
        + 'dodder / scutter / kayak / oar）');
    }
    h += sec('关联节点（' + nb.length + '）');
    h += '<div>' + neighborChips(nb) + '</div>';
    h += sec('来源与复核');
    h += plainRow('释义来源', d.definition_source
      + (d.source_rank ? '（来源优先级 ' + d.source_rank + '）' : ''));
    h += plainRow('Levin 出处', d.levin_source);
    h += plainRow('跨类情况', d.cross_subclass);
    if (d.needs_review) {
      h += missRow('标注待人工复核 —— 图式/对齐/原型层级都是规则推导的候选标签'
        + '（《义项判定标准》第 45 段）');
    }
    if (d.judge_reason) h += plainRow('判定理由', d.judge_reason);
  } else {
    h += sec('关联节点（' + nb.length + '）');
    h += '<div id="neighbors-list">' + neighborChips(nb) + '</div>';
  }
  return h;
}


// ---------- 右侧信息面板 ----------
function renderPanel(nodeId) {
  const n = nodesDS.get(nodeId);
  if (!n) return;
  // 与浮层卡片**共用同一个渲染器**（compact 分支）。不另写一套：两套 HTML 靠人工
  // 对齐，迟早漂移，而漂移的症状是「面板和卡片说的不一样」，最难被发现的那种 bug。
  let html = nodeDetailHTML(n, true)
    + '<div class="fc-row"><span class="k">近义边数</span>'
    + '<span class="v">' + n._degree + '</span></div>'
    + '<button class="tool-btn" id="btn-word-detail" '
    + 'style="margin:7px 0 2px;width:100%;justify-content:center">查看详情</button>';
  document.getElementById('info-content').innerHTML = html;
}

function showInfo(nodeId) {
  currentNodeId = nodeId;
  renderPanel(nodeId);
  syncWordCard();
}

function syncWordCard() {
  const card = document.getElementById('word-card');
  if (card.classList.contains('hidden')) return;
  if (currentNodeId === null) { card.classList.add('hidden'); return; }
  renderWordCard();
}

// ---------- 词条卡片 ----------
function renderWordCard() {
  if (renderedWordId === currentNodeId) return;   // 同一个词不重建，免得打断正在输入的备注
  const n = nodesDS.get(currentNodeId);
  if (!n) return;
  renderedWordId = currentNodeId;
  const ann = annGet('word', currentNodeId);
  document.getElementById('word-card-title').textContent = n.label;
  document.getElementById('word-card-star').classList.toggle('on', !!ann.star);
  document.getElementById('word-card-body').innerHTML = nodeDetailHTML(n, false)
    + sec('备注 / 收藏')
    + '<textarea class="fc-note" id="word-note" placeholder="写下你的备注…">'
    + esc(ann.note || '') + '</textarea>'
    + '<div style="margin-top:5px" class="fc-miss">收藏与备注保存在本机浏览器</div>';
  const ta = document.getElementById('word-note');
  ta.addEventListener('input', () => { annSet('word', currentNodeId, { note: ta.value }); });
}

function openWordCard(nodeId) {
  currentNodeId = nodeId;
  renderedWordId = null;
  renderPanel(nodeId);
  renderWordCard();
  document.getElementById('word-card').classList.remove('hidden');
}

// ---------- 关系卡片 ----------
function openEdgeCard(edgeId) {
  currentEdgeId = edgeId;
  renderedEdgeId = null;
  renderEdgeCard();
  document.getElementById('edge-card').classList.remove('hidden');
  network.selectEdges([edgeId]);
}

function renderEdgeCard() {
  const e = edgesDS.get(currentEdgeId);
  if (!e) return;
  const a = nodesDS.get(e.from), b = nodesDS.get(e.to);
  if (!a || !b) return;
  renderedEdgeId = currentEdgeId;
  const ann = annGet('edge', String(currentEdgeId));
  document.getElementById('edge-card-title').textContent = a.label + ' ↔ ' + b.label;
  document.getElementById('edge-card-star').classList.toggle('on', !!ann.star);

  const na = ADJ.get(a.id) || new Set(), nb2 = ADJ.get(b.id) || new Set();
  let common = 0;
  na.forEach(x => { if (nb2.has(x)) common++; });

  let h = sec('关系');
  h += plainRow('关系名称', e.relation || '近义');
  h += '<div class="fc-row"><span class="k">源词条</span><span class="v">'
     + '<span class="fc-link" data-open-word="' + esc(a.id) + '">' + esc(a.label)
     + '</span></span></div>';
  h += '<div class="fc-row"><span class="k">目标词条</span><span class="v">'
     + '<span class="fc-link" data-open-word="' + esc(b.id) + '">' + esc(b.label)
     + '</span></span></div>';
  h += plainRow('关系类型', '同一次类内的近义关系（簇内完全图边）');
  h += plainRow('关系方向', '无向 —— 近义是对称关系，库里按 verb_a_id < verb_b_id 只存一份');
  h += '<div class="fc-row"><span class="k">关系说明</span><span class="v">'
     + esc(a.label + ' 与 ' + b.label + ' 同属「' + a._subCat + '」次类（'
           + a._clusterLabel + '），在该次类内两两互为近义。') + '</span></div>';

  h += sec('权重 / 强度');
  h += plainRow('共同邻居', common + ' 个');
  h += plainRow('两端近义边数', a._degree + ' / ' + b._degree);
  h += missRow('本图没有边权重字段：次类内是完全图，每条边结构等价，共同邻居数恒等于'
    + '（次类词数 − 2）。这里只给可验证的结构指标，不编一个相似度分数出来。');

  h += sec('例句');
  const exA = (a._d && a._d.example_sentence) || '';
  const exB = (b._d && b._d.example_sentence) || '';
  if (exA || exB) {
    if (exA) h += '<div class="fc-ex">' + esc(a.label) + '：' + esc(exA) + '</div>';
    if (exB) h += '<div class="fc-ex">' + esc(b.label) + '：' + esc(exB) + '</div>';
  } else {
    h += missRow('两端词条都没有例句（词目级例句只覆盖 136 词里的 22 个）');
  }

  h += sec('来源');
  h += plainRow('关系来源', 'docs/Levin移动动词候选词筛选表.xlsx 的次类归并，脚本据此生成完全图');
  h += plainRow('所属次类', a._subCat);
  h += plainRow('所属主范畴', a._mainCat);

  h += sec('备注 / 收藏');
  h += '<textarea class="fc-note" id="edge-note" placeholder="写下你对这条关系的备注…">'
     + esc(ann.note || '') + '</textarea>'
     + '<div style="margin-top:5px" class="fc-miss">收藏与备注保存在本机浏览器</div>';

  document.getElementById('edge-card-body').innerHTML = h;
  const ta = document.getElementById('edge-note');
  ta.addEventListener('input', () => { annSet('edge', String(currentEdgeId), { note: ta.value }); });
}

// ---------- 卡片拖动 ----------
function makeDraggable(cardId, handleId) {
  const card = document.getElementById(cardId);
  const handle = document.getElementById(handleId);
  let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
  handle.addEventListener('pointerdown', ev => {
    if (ev.target.closest('.fc-btn')) return;   // 点按钮不该被当成拖动
    const parent = card.offsetParent || document.body;
    const cr = card.getBoundingClientRect(), pr = parent.getBoundingClientRect();
    ox = cr.left - pr.left;
    oy = cr.top - pr.top;
    card.style.left = ox + 'px';
    card.style.top = oy + 'px';
    sx = ev.clientX; sy = ev.clientY;
    dragging = true;
    try { handle.setPointerCapture(ev.pointerId); } catch (e) {}
    ev.preventDefault();
  });
  handle.addEventListener('pointermove', ev => {
    if (!dragging) return;
    card.style.left = (ox + ev.clientX - sx) + 'px';
    card.style.top = (oy + ev.clientY - sy) + 'px';
  });
  const stop = ev => {
    if (!dragging) return;
    dragging = false;
    try { handle.releasePointerCapture(ev.pointerId); } catch (e) {}
  };
  handle.addEventListener('pointerup', stop);
  handle.addEventListener('pointercancel', stop);
}
makeDraggable('word-card', 'word-card-head');
makeDraggable('edge-card', 'edge-card-head');

// 仅供截图 / 自动化改写状态用：一次性收起两张卡片
function hideAllCards() {
  document.getElementById('word-card').classList.add('hidden');
  document.getElementById('edge-card').classList.add('hidden');
  renderedWordId = null; renderedEdgeId = null;
}
document.getElementById('word-card-close').addEventListener('click', () => {
  document.getElementById('word-card').classList.add('hidden');
  renderedWordId = null;
});
document.getElementById('word-card-star').addEventListener('click', () => {
  if (currentNodeId === null) return;
  const next = annSet('word', currentNodeId, { star: !annGet('word', currentNodeId).star });
  document.getElementById('word-card-star').classList.toggle('on', !!next.star);
});
document.getElementById('edge-card-close').addEventListener('click', () => {
  document.getElementById('edge-card').classList.add('hidden');
  renderedEdgeId = null;
});
document.getElementById('edge-card-star').addEventListener('click', () => {
  if (currentEdgeId === null) return;
  const key = String(currentEdgeId);
  const next = annSet('edge', key, { star: !annGet('edge', key).star });
  document.getElementById('edge-card-star').classList.toggle('on', !!next.star);
});

// 「查看详情」按钮、面板里的词条名、卡片里的跳转链接，统一在这里代理
document.addEventListener('click', ev => {
  if (ev.target.closest('#btn-word-detail')) { openWordCard(currentNodeId); return; }
  const w = ev.target.closest('[data-open-word]');
  if (w) openWordCard(w.dataset.openWord);
});

// hover 比 click 的事件参数更可靠，两者都接上
let hoveredNodeId = null;
let lastClickHadEdge = false;   // 用来阻止「点了边又被当成点了节点」
network.on('hoverNode', p => { hoveredNodeId = p.node; lastClickHadEdge = false; container.style.cursor = 'pointer'; });
network.on('blurNode', () => { hoveredNodeId = null; container.style.cursor = 'default'; });
container.addEventListener('click', () => {
  if (lastClickHadEdge) return;
  if (hoveredNodeId !== null) focusNode(hoveredNodeId, false);
});
network.on('click', p => {
  // **节点优先于边**，这一点必须小心：vis 在点到节点时会把「该节点关联的
  // 所有边」一并塞进 p.edges（实测点一个 44 度的节点会带回 44 条边），
  // 所以如果先判边，点节点就会随机打开某条关联边的关系卡片。
  // 用户的要求本身也写明了「点边，而不是点节点」时才看关系。
  if (p.nodes.length > 0) {
    lastClickHadEdge = false;
    showInfo(p.nodes[0]);
    return;
  }
  if (p.edges && p.edges.length > 0) {
    lastClickHadEdge = true;
    openEdgeCard(p.edges[0]);
    return;
  }
  lastClickHadEdge = false;
  if (hoveredNodeId === null) {
    currentNodeId = null;
    document.getElementById('info-content').innerHTML =
      '<span class="empty">点击任意节点查看详情</span>';
    const card = document.getElementById('word-card');
    if (!card.classList.contains('hidden')) { card.classList.add('hidden'); renderedWordId = null; }
  }
});

// ---------- 聚焦 ----------
const focusCb = document.getElementById('focus-cb');

function clearDim() {
  nodesDS.update(RAW_NODES.map(n => ({ id: n.id, opacity: 1 })));
}

/**
 * 确保某个节点所属的词簇处于勾选状态，返回是否发生了变化。
 *
 * 用户要求：**搜到的词，即使它所在的词簇当前没勾选，也要自动勾选上**。
 * 否则会出现「搜到了这个词，图上却看不到它」—— 搜索给出了一条导航路径，
 * 却因为一个隐藏状态通向空处，那比不给导航更糟。
 *
 * 只在未勾选时才动：每次都调 applyFilter 会重建粒子集合，白白打断正在进行的运动。
 */
function ensureClusterEnabled(nodeId) {
  const n = nodesDS.get(nodeId);
  if (!n) return false;
  const cid = String(n._clusterId);
  if (enabled.has(cid)) return false;
  enabled.add(cid);
  applyFilter();      // 重绘图例与统计，并让节点真正可见
  return true;
}

function focusNode(nodeId, doFocus) {
  // 先让它的簇可见，再聚焦 —— 反过来的话 network.focus 会聚焦到一个当时还
  // hidden 的坐标上，视野可能落空
  ensureClusterEnabled(nodeId);
  if (doFocus !== false) network.focus(nodeId, { scale: 1.2, animation: true });
  network.selectNodes([nodeId]);
  showInfo(nodeId);
  if (!focusCb.checked) { clearDim(); return; }
  // 只高亮「自己 + 邻居」，其余压暗：完全图下每个词有几十个邻居，
  // 不压暗根本看不出谁连着谁。
  const keep = new Set([nodeId].concat(network.getConnectedNodes(nodeId)));
  nodesDS.update(RAW_NODES.map(n => ({ id: n.id, opacity: keep.has(n.id) ? 1 : 0.12 })));
  notifyGraphChanged();
}

focusCb.addEventListener('change', () => {
  if (focusCb.checked) {
    const sel = network.getSelectedNodes();
    if (sel.length) focusNode(sel[0], false);
  } else {
    clearDim();
  }
});

// ============================================
// 粒子物理层：每个单词节点就是一个粒子
// ============================================
// 设计（用户要求，2026-09）：
//   1. **节点本身就是粒子** —— 不再是「节点 + 环绕的小卫星」，节点自己就是那颗粒子；
//   2. **粒子之间有引力与斥力** —— 斥力让它们互不重叠，引力沿近义边把同簇词拉拢；
//   3. **有阻尼感** —— 速度每帧按阻尼衰减，不会越跑越快；
//   4. **速度降到原来的 0.1** —— SPEED_SCALE 是总闸门。
//
// ## 为什么自己写物理，而不是直接用 vis-network 的物理引擎
//
// vis 的 forceAtlas2Based 是**布局求解器**：目标是「尽快收敛，然后停下来」。
// 这里要的是「收敛之后仍然缓慢游动」，两者目标相反 —— 所以布局收敛后关掉 vis 物理
// （见上面的 stabilizationIterationsDone），由本层接管位置更新，再写回给 vis 渲染。
//
// ## 为什么保留一个很弱的「回锚」
//
// 完全自由的粒子系统会把 force-directed 排出来的语义布局搅乱：各词簇会挤成一团，
// 图就失去可读性了。锚定力刻意取很小（ANCHOR_K），只抑制整体漂移，
// 不干预粒子之间的引力斥力 —— 用户要的「动感」来自引力斥力，不是来自漂移。
//
// ## 位置空间
//
// 全部计算在 **canvas 空间**（vis 的 getPositions / moveNode 用的同一套坐标）。
// 该空间不受缩放平移影响，所以缩放后不需要重新锚定；只有绘制时才换算成屏幕坐标。
const pcanvas = document.getElementById('particles');
const pctx = pcanvas.getContext('2d');

// **不再有粒子数量上限**：每个可见节点就是一个粒子，所以粒子数恒等于可见节点数。
//
// 之前那套「200 上限 + 选中簇优先吃配额」的预算分配随之作废 —— 不设上限时
// 每个可见节点都拿得到粒子，也就无所谓谁先谁后、谁优先。相关常量与两阶段分配代码
// 一并删除，不保留「以后可能用得上」的开关：没有调用方的死代码只会误导后来的人。
// ---- 物理参数（单位：canvas 单位 / 帧）----
//
// 收在一个可变对象里，而不是散落的 const：这些值必须靠实测标定（见 __particleDebug.tune），
// 散落的 const 无法在页面上直接调参，每试一组就要改文件 + 重启 + 重新加载。
//
// 标定的目标不是「力有多大」，而是**稳态速度落在哪里**：
// 一阶阻尼系统里 v_eq ≈ a · DAMPING/(1-DAMPING) = 9a（DAMPING=0.9）。
// 所以加速度量级必须控制在 0.01 上下，否则 v_eq 会顶到 MAX_SPEED —— 那时运动由
// 限速决定而不是由引力斥力与阻尼决定，观感是「匀速平移」而不是「有黏滞感的游动」。
// 第一版把 REPULSE_K 设成 4200 就踩了这个坑：实测 171 个粒子全部贴着 MAX_SPEED。
// 这些值是**在浏览器里实测标定**出来的，不是拍脑袋定的。标定过程记录在此，
// 因为下一轮想调手感的人需要知道为什么是这几个数：
//
//   参数组            位移/秒   v中位   被限速节点
//   DAMPING=0.90      1.465    0.250   167/171   ← 初版：几乎全部顶在速度上限
//   ACCEL_MAX=0.05
//
//   DAMPING=0.94      1.280    0.219     0/171   ← 采用
//   ACCEL_MAX=0.014
//
// 关键指标是**被限速的节点数**：一旦大多数节点的速度都等于 MAX_SPEED，运动就由
// 限速决定而不是由引力/斥力/阻尼决定，观感变成「整张图匀速平移」，
// 完全失去用户要的「粒子相互引力斥力 + 阻尼」的质感。
// 所以 MAX_SPEED 只作安全兜底（防止某个粒子被弹飞），正常运行时不该被碰到。
//
// 一阶阻尼系统的稳态速度 v_eq ≈ a·DAMPING/(1-DAMPING)。DAMPING=0.94 时系数约 15.7，
// 配 ACCEL_MAX=0.014 得 v_eq≈0.22，换算成每帧位移 0.022 canvas 单位 —— 缓而不滞。
const PHYS = {
  SPEED_SCALE: 0.1,      // 速度总缩放 —— 用户要求：降到原来的 0.1
  DAMPING: 0.94,         // 阻尼：每帧保留 94% 速度，有明显的黏滞拖尾感
  ANCHOR_K: 0.0003,      // 拉回布局原位的弱弹簧（只防整体漂移）
  REPULSE_K: 3,          // 粒子间斥力强度（与距离平方成反比）
  REPULSE_RANGE: 110,    // 斥力作用半径，超出即忽略（省算力且避免远处干扰）
  MIN_DIST: 6,           // 距离下限，避免除零与无限大的力
  SPRING_K: 0.0006,      // 近义边上的引力系数
  SPRING_REST: 22,       // 边引力的静止长度
  MAX_SPEED: 1.0,        // 速度上限：只做安全兜底，实测 0/171 节点被触发
  ACCEL_MAX: 0.014,      // 净加速度上限：邻居多的节点受力会线性累加，需要护栏
};

let particleOn = true;
// 是否已接管位置更新。布局收敛前交给 vis 的求解器，收敛后本层接手。
let physicsArmed = false;
let pW = 0, pH = 0, dpr = 1;

// 粒子的分配结果（哪些节点参与运动）与物理状态
let particles = [];   // [{node, cluster, color, size}] —— 分配结果
let live = [];        // [{id, x, y, vx, vy, ax, ay, homeX, homeY, color, size}]
let liveIndex = new Map();  // node id -> live 数组下标
let liveEdges = [];   // [[i, j], ...] 指向 live 的下标，两端都已激活动
const homePos = new Map();  // node id -> 布局原位（锚定用，跨 rebuild 保留）

function resizeParticles() {
  const r = document.getElementById('graph-wrap').getBoundingClientRect();
  dpr = window.devicePixelRatio || 1;
  pW = Math.max(1, Math.round(r.width));
  pH = Math.max(1, Math.round(r.height));
  pcanvas.width = Math.round(pW * dpr);
  pcanvas.height = Math.round(pH * dpr);
  pcanvas.style.width = pW + 'px';
  pcanvas.style.height = pH + 'px';
  pctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
resizeParticles();

function rebuildParticles() {
  const visible = RAW_NODES.filter(n => !nodesDS.get(n.id).hidden);
  particles = visible.map(n => ({
    node: n.id,
    cluster: n._clusterId,
    color: n.color.background,
    size: n.size,
  }));
  applyParticleSet(false);
  updateParticleInfo(particles.length);
}

/**
 * 把分配结果同步到物理状态：新粒子从当前节点位置起步，退出集合的丢掉状态。
 *
 * 已经在动的粒子保留 x/y/vx/vy —— 否则用户每次筛选、点选都会看到一次「回弹」，
 * 手感和「缓慢游动」正好相反。
 *
 * Args:
 *   reset: 丢弃已有状态、完全按当前节点位置重建。仅在 armPhysics（布局收敛）时用，
 *          因为那一刻节点位置才第一次是「最终布局」。
 */
function applyParticleSet(reset) {
  const prevById = new Map();
  if (!reset) for (const a of live) prevById.set(a.id, a);

  const pos = network.getPositions(particles.map(p => p.node));

  const nextLive = [];
  const nextIndex = new Map();
  for (const p of particles) {
    const cur = pos[p.node];
    if (!cur) continue;              // 节点还没布局出来，跳过（下次 rebuild 会补上）
    const prev = prevById.get(p.node);
    if (!homePos.has(p.node)) homePos.set(p.node, { x: cur.x, y: cur.y });
    const home = homePos.get(p.node);
    nextIndex.set(p.node, nextLive.length);
    nextLive.push({
      id: p.node,
      x: prev ? prev.x : cur.x,
      y: prev ? prev.y : cur.y,
      vx: prev ? prev.vx : 0,
      vy: prev ? prev.vy : 0,
      ax: 0, ay: 0,
      homeX: home.x, homeY: home.y,
      color: p.color,
      size: p.size,
    });
  }
  live = nextLive;
  liveIndex = nextIndex;

  // 边只在两端都参与运动时才有引力 —— 一端静止的边如果也施力，
  // 会把静止节点拉走又拉不回来，图会散架。
  liveEdges = [];
  for (const e of RAW_EDGES) {
    const i = liveIndex.get(e.from), j = liveIndex.get(e.to);
    if (i !== undefined && j !== undefined) liveEdges.push([i, j]);
  }
}

/**
 * 一帧的物理积分。
 *
 * 力的构成（都在 canvas 空间）：
 *   * 锚定  —— 拉回布局原位，很弱，只防整体漂移
 *   * 斥力  —— 所有粒子两两（距离平方反比，超出 REPULSE_RANGE 忽略）
 *   * 引力  —— 沿近义边（弹簧，目标长度 SPRING_REST）
 * 然后阻尼衰减、限速、按 SPEED_SCALE 积分位置。
 */
function stepPhysics() {
  // 布局没收敛前不接管：那时 vis 的求解器比本层快得多，抢着改位置只会互相打架
  if (!physicsArmed || !particleOn || live.length < 2) return;

  // 1) 锚定 + 清零累加器
  for (const a of live) {
    a.ax = (a.homeX - a.x) * PHYS.ANCHOR_K;
    a.ay = (a.homeY - a.y) * PHYS.ANCHOR_K;
  }

  // 2) 斥力：粒子两两互斥
  const range2 = PHYS.REPULSE_RANGE * PHYS.REPULSE_RANGE;
  for (let i = 0; i < live.length; i++) {
    const a = live[i];
    for (let j = i + 1; j < live.length; j++) {
      const b = live[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d2 = dx * dx + dy * dy;
      if (d2 > range2) continue;
      const d = Math.max(Math.sqrt(d2), PHYS.MIN_DIST);
      const f = PHYS.REPULSE_K / (d * d);
      const ux = dx / d, uy = dy / d;
      a.ax -= ux * f; a.ay -= uy * f;
      b.ax += ux * f; b.ay += uy * f;
    }
  }

  // 3) 引力：近义边上的弹簧
  for (const [i, j] of liveEdges) {
    const a = live[i], b = live[j];
    const dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.max(Math.sqrt(dx * dx + dy * dy), PHYS.MIN_DIST);
    const f = PHYS.SPRING_K * (d - PHYS.SPRING_REST);
    const ux = dx / d, uy = dy / d;
    a.ax += ux * f; a.ay += uy * f;
    b.ax -= ux * f; b.ay -= uy * f;
  }

  // 4) 加速度护栏 + 阻尼 + 限速 + 积分
  for (const a of live) {
    // 邻居多的节点受力会线性累加（45 词的大簇里每个节点有 44 条边），
    // 不设护栏的话大簇会明显比小簇抖。这里限的是**净加速度**，
    // 方向上保持力的合成结果，只压缩幅度。
    const am = Math.hypot(a.ax, a.ay);
    if (am > PHYS.ACCEL_MAX) {
      const k = PHYS.ACCEL_MAX / am;
      a.ax *= k; a.ay *= k;
    }
    a.vx = (a.vx + a.ax) * PHYS.DAMPING;
    a.vy = (a.vy + a.ay) * PHYS.DAMPING;
    const sp = Math.hypot(a.vx, a.vy);
    if (sp > PHYS.MAX_SPEED) {
      a.vx = a.vx / sp * PHYS.MAX_SPEED;
      a.vy = a.vy / sp * PHYS.MAX_SPEED;
    }
    a.x += a.vx * PHYS.SPEED_SCALE;
    a.y += a.vy * PHYS.SPEED_SCALE;
  }

  // 5) 写回给 vis
  writeBackPositions();
}

/**
 * 把物理算出的位置写回 vis。
 *
 * **不要逐帧调 network.moveNode()**：moveNode 内部每次都会安排一个延迟的
 * `startSimulation` 事件，逐帧调 171 次会堆积成千上万个待处理定时器，把主线程压死
 * （实测过一次，页面直接卡死）。moveNode 真正做的事就是给 body.nodes[id] 赋 x/y，
 * 这里直接赋值，最后统一 redraw 一次 —— 效果一样，开销可以忽略。
 */
function writeBackPositions() {
  const bn = network.body.nodes;
  for (const a of live) {
    const node = bn[a.id];
    if (node) { node.x = a.x; node.y = a.y; }
  }
  network.redraw();
}

function updateParticleInfo(shown) {
  document.getElementById('particle-info').textContent = shown + ' 个节点粒子';
}

/**
 * 把一颗粒子画出来：光晕 + 核心 + 沿速度方向的短拖尾。
 *
 * 节点位置就是粒子位置，所以这层画出来的粒子正好盖在 vis 的节点圆点上 ——
 * 「单词节点就是粒子」在视觉上成立，而不是节点旁边另挂一圈小点。
 */
function drawParticles() {
  requestAnimationFrame(drawParticles);
  if (!particleOn) {
    pctx.clearRect(0, 0, pW, pH);
    return;
  }
  pctx.clearRect(0, 0, pW, pH);

  // **半径必须跟着 vis 的缩放走。** vis 把节点画成 size*scale 个屏幕像素，
  // 粒子层如果直接按 canvas 单位画，在缩小的视野里就会比节点大出好几倍。
  // 实测过：视野缩放 0.268 时节点只有 4~9px，而当时的粒子半径是 14~31px（3.4 倍），
  // 171 个半透明光晕在 'lighter' 叠加下互相加亮，17% 的已绘制像素变成近纯白 ——
  // 整张图糊成一团白光，正是用户说的「一团光晕，啥也看不清」。
  const scale = network.getScale();
  pctx.globalCompositeOperation = 'lighter';
  const t = performance.now() / 1000;

  for (const a of live) {
    const dom = network.canvasToDOM({ x: a.x, y: a.y });
    if (dom.x < -60 || dom.y < -60 || dom.x > pW + 60 || dom.y > pH + 60) continue;

    // 呼吸：让静止的粒子也有细微的明暗变化，否则慢速下看不出「活的」
    const breathe = 0.78 + 0.22 * Math.sin(t * 1.6 + a.homeX * 0.01 + a.homeY * 0.013);
    // 下限 2.5px：缩得很小时至少还是个看得见的点，不会整片消失。
    // 上限 26px：放得很大时光晕也不会糊满屏幕。
    const r = Math.min(Math.max(a.size * scale, 2.5), 26);

    // 缩放太小时（整图铺满画布）只点一颗实心点，不画光晕也不画拖尾。
    // 理由：光晕和拖尾都是「放大后才看得见」的细节，而在小缩放下它们是纯粹的成本 ——
    // 171 个半透明圆叠加起来会把画布糊白，恰恰毁掉唯一重要的东西：词的标签。
    // 阈值取 r<4：那时节点本身也就 4px，光晕再小也会盖住旁边的词。
    const small = r < 4;

    // 光晕：只比节点大一点。之前是节点半径的 3.2 倍，那是「节点旁边一团雾」而不是
    // 「节点在发光」，而且叠加后能把邻居的词一起盖掉。
    const glowR = r * 1.9;
    if (!small) {
    const grad = pctx.createRadialGradient(dom.x, dom.y, 0, dom.x, dom.y, glowR);
    grad.addColorStop(0, a.color);
    grad.addColorStop(0.35, hexA(a.color, 0.30 * breathe));
    grad.addColorStop(1, hexA(a.color, 0));
      pctx.globalAlpha = 0.55;
      pctx.fillStyle = grad;
      pctx.beginPath();
      pctx.arc(dom.x, dom.y, glowR, 0, Math.PI * 2);
      pctx.fill();
    }

    // 拖尾：沿速度反方向留几颗残影。速度很慢，所以拖尾很短 —— 这是对的，
    // 长拖尾会让人以为是「快速飞行」而不是「缓慢游动」。
    const sp = Math.hypot(a.vx, a.vy);
    if (!small && sp > 0.05) {
      const ux = a.vx / sp, uy = a.vy / sp;
      const len = Math.min(sp * 26, r * 2.6);
      for (let k = 1; k <= 3; k++) {
        const f = 1 - k / 4;
        pctx.globalAlpha = 0.22 * f * breathe;
        pctx.fillStyle = a.color;
        pctx.beginPath();
        pctx.arc(dom.x - ux * len * (k / 3), dom.y - uy * len * (k / 3),
                 r * 0.55 * f, 0, Math.PI * 2);
        pctx.fill();
      }
    }

    // 核心：白色高光点。它是「粒子感」的来源，但半径必须小于节点圆，
    // 否则会盖掉 vis 画的节点本体颜色（那才是词簇的语义信息）。
    // 小缩放下不提亮反而看不见，所以那里不乘 breathe。
    pctx.globalAlpha = small ? 1 : 0.8 * breathe;
    pctx.fillStyle = '#ffffff';
    pctx.beginPath();
    pctx.arc(dom.x, dom.y, Math.max(r * 0.32, 1.1), 0, Math.PI * 2);
    pctx.fill();
  }

  pctx.globalAlpha = 1;
  pctx.globalCompositeOperation = 'source-over';
}

/** 把 #rrggbb 转成 rgba(...)。需要它是因为 canvas 渐变的色标不支持 alpha 简写。 */
function hexA(hex, alpha) {
  const h = String(hex).replace('#', '');
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const n = parseInt(full, 16);
  if (isNaN(n)) return 'rgba(160,160,200,' + alpha + ')';
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
}

// 物理与绘制是两个独立的循环：物理按固定节奏走（stepPhysics 由 rAF 驱动，
// 但内部按倍数限速），绘制每帧都做。合在一起会让低帧率下物理变慢、手感不一致。
let physAccum = 0;
let lastPhysT = performance.now();
// 帧耗时滑动平均，用于自适应降载
let frameMs = 16;
// 连续太慢就跳过物理步（只保留绘制）。宁可动效变慢，也不能让页面卡住 ——
// 这个页面还要负责搜索、点选、筛选，动效永远不该是瓶颈。
let physSkip = 0;

function physicsLoop(now) {
  requestAnimationFrame(physicsLoop);
  if (!particleOn) { lastPhysT = now; frameMs = 16; return; }

  const dt = Math.min(now - lastPhysT, 100);
  lastPhysT = now;
  frameMs = frameMs * 0.9 + dt * 0.1;

  // 自适应：>33ms（低于 30fps）隔一步跑一次；>60ms 直接暂停物理，等机器缓过来
  if (frameMs > 60) { physSkip = 3; }
  else if (frameMs > 33) { physSkip = 1; }
  if (physSkip > 0) { physSkip--; return; }

  // 固定步长 60Hz，全程最多补 2 步，避免切回标签页时「瞬移」
  physAccum += dt;
  let steps = 0;
  while (physAccum >= 16.67 && steps < 2) {
    stepPhysics();
    physAccum -= 16.67;
    steps++;
  }
  if (physAccum > 16.67 * 4) physAccum = 0;
}

// ---------- 工具栏 ----------
document.getElementById('btn-particles').addEventListener('click', e => {
  particleOn = !particleOn;
  e.currentTarget.classList.toggle('on', particleOn);
  if (!particleOn) {
    // 关掉时把粒子送回原位并清零速度，否则它们会停在半路，
    // 再打开时从偏移位置继续，看起来像「漂移过的图」
    for (const a of live) {
      a.x = a.homeX; a.y = a.homeY; a.vx = 0; a.vy = 0;
    }
    writeBackPositions();
    pctx.clearRect(0, 0, pW, pH);
  }
});

document.getElementById('btn-fullscreen').addEventListener('click', async e => {
  const btn = e.currentTarget;
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      // 对整个 body 请求全屏，这样侧边栏一起进全屏（只放大图就没法用侧栏了）。
      // 组件 iframe 的 allow 属性里已含 fullscreen，所以能成功。
      await document.body.requestFullscreen();
    }
  } catch (err) {
    btn.textContent = '⛶ 全屏不可用';
  }
});

document.addEventListener('fullscreenchange', () => {
  const btn = document.getElementById('btn-fullscreen');
  btn.classList.toggle('on', !!document.fullscreenElement);
  btn.textContent = document.fullscreenElement ? '⛶ 退出全屏' : '⛶ 全屏';
  // canvas 尺寸变了：重算覆盖层，并把图谱视野适配回新尺寸
  resizeParticles();
  network.setSize('100%', '100%');
  network.fit({ animation: false });
  rebuildParticles();
});

window.addEventListener('resize', () => { resizeParticles(); network.setSize('100%', '100%'); });

// 图谱状态变化 → 粒子集合跟着重建（节点隐藏/选中都会影响谁该有粒子）
graphChangeHooks.push(rebuildParticles);

// 拖拽结束后重新锚定并清零速度：用户把节点拖到新位置，就是给了它一个新的"原位"，
// 否则锚定力会立刻把它拽回旧位置，看起来像拖不动。
network.on('dragEnd', params => {
  const ids = params.nodes && params.nodes.length ? params.nodes : network.getSelectedNodes();
  const pos = network.getPositions(ids);
  for (const id of ids) {
    if (!homePos.has(id)) continue;
    const cur = pos[id];
    if (cur) homePos.set(id, { x: cur.x, y: cur.y });
    const a = live.find(x => x.id === id);
    if (a) { a.vx = 0; a.vy = 0; a.x = cur.x; a.y = cur.y; a.homeX = cur.x; a.homeY = cur.y; }
  }
});

/**
 * 接管位置更新。
 *
 * 在**布局收敛之后**才调用：收敛前 vis 的求解器在把节点铺开，本层这时改位置只会
 * 互相打架、收敛更慢。接管时按最终位置重建锚点 —— 粒子应该以「布局排好的样子」为家。
 */
function armPhysics() {
  if (physicsArmed) return;
  const pos = network.getPositions(RAW_NODES.map(n => n.id));
  homePos.clear();
  for (const [id, p] of Object.entries(pos)) homePos.set(id, { x: p.x, y: p.y });
  physicsArmed = true;
  applyParticleSet(true);   // 丢弃旧状态，用收敛后的位置重建
}

network.once('stabilizationIterationsDone', armPhysics);

// 兜底：若收敛在监听注册之前就完成了（例如页面恢复时物理已被关掉），
// 上面那个 once 永远不会触发，物理就永远不开始。这里主动检查一次。
// 判断依据是 vis 的 physics 选项已被上面那个 handler 关掉。
setTimeout(() => {
  const phy = network.physics;
  if (!physicsArmed && phy && phy.options && phy.options.enabled === false) armPhysics();
}, 2000);

// 初始：全图铺开
renderLegend();
updateStats();
rebuildParticles();
requestAnimationFrame(physicsLoop);
drawParticles();

// 调试接口：测试与人工排查用（页面上的粒子数、速度、阻尼等都能查到）
window.__particleDebug = {
  get live() { return live; },
  get particles() { return particles; },
  get liveEdges() { return liveEdges; },
  get homePos() { return homePos; },
  PHYS,
  ensureClusterEnabled,
  // 现场调参：Object.assign(PHYS, {...})，用于标定手感而不必改文件重启
  tune(obj) { Object.assign(PHYS, obj); },
  stepPhysics,
  rebuild: rebuildParticles,
};
</script>
</body>
</html>
"""


# ============================================
# 词簇交互图（搜索结果页内嵌：当前词 + 其所在簇）
# ============================================
# 与全库图谱（build_graph_html）的分工：
#   * 全库页 —— 136 词的语义地图，带搜索/侧栏/图例；
#   * 本模板 —— 单簇轻量视图：中心词高亮，默认只画"中心词↔成员"连线
#     （避免完全图在静态 SVG 时代挤成毛球的问题），簇内两两连线由
#     页内按钮按需展开 —— 纯前端切换，不触发 Streamlit 重跑。
CLUSTER_TEMPLATE_VERSION = 3

_CLUSTER_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>__TITLE__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #ffffff;
               font-family: -apple-system, "Segoe UI", "PingFang SC", sans-serif; }
  #bar { display: flex; align-items: center; gap: 12px; padding: 8px 14px;
         border-bottom: 1px solid #e2e8f0; box-sizing: border-box; }
  #bar .t { font-weight: 600; color: #2d3748; font-size: 14px; }
  #bar .s { color: #718096; font-size: 12px; }
  #bar button { margin-left: auto; border: 1px solid #cbd5e0; background: #fff;
                color: #4a5568; border-radius: 6px; padding: 4px 10px;
                font-size: 12px; cursor: pointer; }
  #bar button.on { background: #6b46c1; border-color: #6b46c1; color: #fff; }
  #net { width: 100%; height: calc(100% - 41px); }
  /* ---------- 浮层卡片（对齐知识图谱页的词条/关系卡片） ---------- */
  #card { position: absolute; z-index: 30; max-width: 320px; min-width: 240px;
          background: #fff; border: 1px solid #cbd5e0; border-radius: 10px;
          box-shadow: 0 8px 24px rgba(45,55,72,.18); display: none; }
  #card.on { display: block; }
  #card-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
               background: #6b46c1; color: #fff; border-radius: 9px 9px 0 0;
               cursor: move; user-select: none; }
  #card-head .t { font-weight: 600; font-size: 14px; flex: 1;
                  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #card-close { border: none; background: none; color: #fff; font-size: 16px;
                line-height: 1; cursor: pointer; padding: 0 2px; }
  #card-body { padding: 10px 12px; max-height: 300px; overflow-y: auto;
               font-size: 12.5px; color: #2d3748; }
  #card-body .row { display: flex; padding: 3px 0; }
  #card-body .k { color: #718096; min-width: 72px; }
  #card-body .v { flex: 1; word-break: break-word; }
  #card-body .sec { margin: 8px 0 4px; font-weight: 600; color: #553c9a;
                    border-bottom: 1px solid #e2e8f0; padding-bottom: 2px; }
  #card-body .ex { background: #f7fafc; border-left: 3px solid #b794f4;
                   padding: 6px 8px; margin: 4px 0; border-radius: 0 6px 6px 0; }
</style>
</head>
<body>
<div id="bar">
  <span class="t">__CLUSTER_LABEL__</span>
  <span class="s">__SIZE__ 词 · 中心连线 __CENTER_EDGES__ 条 · 簇内两两 __PAIR_EDGES__ 条</span>
  <button id="toggle" type="button">显示簇内两两连线</button>
</div>
<div id="net"></div>
<div id="card">
  <div id="card-head"><span class="t" id="card-title"></span>
    <button id="card-close" type="button" title="关闭">×</button></div>
  <div id="card-body"></div>
</div>
<script src="__VIS_LIB__"></script>
<script>
  var NODES_JSON = __NODES_JSON__;
  var EDGES_JSON = __EDGES_JSON__;
  var nodes = new vis.DataSet(NODES_JSON);
  var edges = new vis.DataSet(EDGES_JSON);
  var showPair = false;
  var container = document.getElementById('net');
  var data = { nodes: nodes, edges: edges };
  var options = {
    autoResize: true,
    physics: { solver: 'barnesHut',
               barnesHut: { gravitationalConstant: -6000, springLength: 110 },
               stabilization: { iterations: 400, fit: true } },
    interaction: { hover: true, tooltipDelay: 120, navigationButtons: false },
    nodes: { shape: 'dot', font: { size: 13, color: '#2d3748' },
             borderWidth: 2, borderWidthSelected: 3 },
    edges: { selectionWidth: 1.5, hoverWidth: 0.6 }
  };
  var network = new vis.Network(container, data, options);
  // 布局稳定后立即冻结物理引擎：节点停住不动、拖到哪停在哪儿，
  // 不再持续漂移抖动（与全库图谱页同一处理）。
  network.once('stabilizationIterationsDone', function () {
    network.setOptions({ physics: { enabled: false } });
  });
  // ---------- 浮层卡片（点节点/点边弹出，对齐知识图谱页效果） ----------
  var card = document.getElementById('card');
  var cardTitle = document.getElementById('card-title');
  var cardBody = document.getElementById('card-body');
  document.getElementById('card-close').addEventListener('click', function () {
    card.classList.remove('on');
  });
  function esc(x) {
    return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function row(k, v) {
    return '<div class="row"><span class="k">' + esc(k) + '</span><span class="v">'
           + esc(v) + '</span></div>';
  }
  function showCard(x, y) {
    card.classList.add('on');
    // 定位在点击点附近，越界回拉
    var cw = card.offsetWidth || 280, ch = card.offsetHeight || 200;
    var px = Math.min(Math.max(8, x + 14), window.innerWidth - cw - 8);
    var py = Math.min(Math.max(8, y + 14), window.innerHeight - ch - 8);
    card.style.left = px + 'px';
    card.style.top = py + 'px';
  }
  function openNodeCard(nodeId, x, y) {
    var n = nodes.get(nodeId);
    if (!n) return;
    var d = n._d || {};
    cardTitle.textContent = n.label + (n.isCenter ? '（中心词）' : '');
    var h = '';
    if (d.chinese_ndef || d.en_ndef) {
      h += '<div class="sec">释义</div>';
      if (d.chinese_ndef) h += row('中文', d.chinese_ndef);
      if (d.en_ndef) h += row('英文', d.en_ndef);
    }
    if (d.sense_brief) h += row('主导义', d.sense_brief);
    if (d.image_schema) h += row('意象图式', d.image_schema);
    if (d.subCat) h += row('次类', d.subCat);
    if (d.example_sentence) {
      h += '<div class="sec">例句</div><div class="ex">' + esc(d.example_sentence) + '</div>';
    }
    h += '<div class="sec">提示</div>' + row('操作', '点击簇内其他节点或连线继续查看');
    cardBody.innerHTML = h;
    showCard(x, y);
  }
  function openEdgeCard(edgeId, x, y) {
    var e = edges.get(edgeId);
    if (!e) return;
    var a = nodes.get(e.from), b = nodes.get(e.to);
    if (!a || !b) return;
    cardTitle.textContent = a.label + ' ↔ ' + b.label;
    var h = '<div class="sec">关系</div>';
    h += row('关系名称', '近义');
    h += row('关系类型', '同一次类内的近义关系（簇内完全图边）');
    h += row('关系方向', '无向（对称关系）');
    h += row('所属次类', (a._d && a._d.subCat) || '');
    h += row('关系说明', a.label + ' 与 ' + b.label + ' 同簇，在该次类内两两互为近义');
    h += '<div class="sec">提示</div>' + row('操作', '点击节点可查看词条详情');
    cardBody.innerHTML = h;
    showCard(x, y);
  }
  network.on('click', function (params) {
    // 节点优先于边（vis 点节点会把关联边一并塞进 params.edges）
    if (params.nodes.length > 0) {
      network.selectNodes(params.nodes);
      openNodeCard(params.nodes[0], params.pointer.DOM.x, params.pointer.DOM.y);
      return;
    }
    if (params.edges && params.edges.length > 0) {
      network.selectEdges(params.edges);
      openEdgeCard(params.edges[0], params.pointer.DOM.x, params.pointer.DOM.y);
      return;
    }
    card.classList.remove('on');
  });
  // 卡片拖动（按住标题栏移动）
  (function () {
    var dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    var head = document.getElementById('card-head');
    head.addEventListener('pointerdown', function (ev) {
      if (ev.target.id === 'card-close') return;
      var cr = card.getBoundingClientRect();
      ox = cr.left; oy = cr.top; sx = ev.clientX; sy = ev.clientY;
      card.style.left = ox + 'px'; card.style.top = oy + 'px';
      dragging = true;
      try { head.setPointerCapture(ev.pointerId); } catch (e) {}
      ev.preventDefault();
    });
    head.addEventListener('pointermove', function (ev) {
      if (!dragging) return;
      card.style.left = (ox + ev.clientX - sx) + 'px';
      card.style.top = (oy + ev.clientY - sy) + 'px';
    });
    var stop = function () { dragging = false; };
    head.addEventListener('pointerup', stop);
    head.addEventListener('pointercancel', stop);
  })();
  var btn = document.getElementById('toggle');
  btn.addEventListener('click', function () {
    showPair = !showPair;
    btn.classList.toggle('on', showPair);
    btn.textContent = showPair ? '隐藏簇内两两连线' : '显示簇内两两连线';
    EDGES_JSON.forEach(function (e) {
      if (e.pair) edges.update({ id: e.id, hidden: !showPair });
    });
  });
</script>
</body>
</html>"""


def _esc_js_json(obj: Any) -> str:
    """json.dumps 后转义 "</"，防止节点字段里的字面量提前终结 <script>。"""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build_cluster_html(graph: Dict[str, Any]) -> str:
    """渲染词簇交互图 HTML（中心词高亮；簇内两两连线默认隐藏、页内可展开）。"""
    center = graph.get("center") or ""
    cluster = graph.get("cluster") or {}
    nodes = graph.get("nodes", [])
    links = graph.get("links", [])

    vis_nodes = []
    for n in nodes:
        is_center = n.get("is_center") or n.get("id") == center
        vis_nodes.append({
            "id": n["id"],
            "label": n["id"],
            "title": (f"★ 中心词：{n['id']}" if is_center
                      else f"{n['id']}（与「{center}」同簇近义）"),
            "isCenter": is_center,
            # 浮层卡片明细：与知识图谱页 nodeDetailHTML 同源字段
            "_d": {
                "chinese_ndef": n.get("chinese_ndef") or "",
                "en_ndef": n.get("en_ndef") or "",
                "sense_brief": n.get("sense_brief") or "",
                "image_schema": n.get("image_schema") or "",
                "subCat": n.get("sub_cat") or "",
                "example_sentence": n.get("example_sentence") or "",
            },
            "size": 24 if is_center else 12,
            "color": ({"background": "#6b46c1", "border": "#44337a",
                       "highlight": {"background": "#6b46c1", "border": "#2d3748"}}
                      if is_center
                      else {"background": "#b794f4", "border": "#805ad5",
                            "highlight": {"background": "#805ad5", "border": "#2d3748"}}),
            "font": {"size": 15 if is_center else 12,
                     "bold": is_center},
        })

    vis_edges = []
    center_edges = pair_edges = 0
    for l in links:
        s, tg = l.get("source"), l.get("target")
        is_center_edge = (s == center or tg == center)
        if is_center_edge:
            center_edges += 1
        else:
            pair_edges += 1
        vis_edges.append({
            "id": f"{s}|{tg}",
            "from": s, "to": tg,
            "pair": not is_center_edge,
            "hidden": not is_center_edge,
            "color": ({"color": "rgba(107,70,193,0.55)", "highlight": "#44337a"}
                      if is_center_edge
                      else {"color": "rgba(160,174,208,0.22)", "highlight": "#805ad5"}),
            "width": 1.4 if is_center_edge else 0.8,
        })

    values = {
        "TITLE": _esc(f"词簇图谱：{center}"),
        "CLUSTER_LABEL": _esc(f"词簇 {cluster.get('label', '未分组')}（中心词 {center}）"),
        "SIZE": _esc(str(len(nodes))),
        "CENTER_EDGES": _esc(str(center_edges)),
        "PAIR_EDGES": _esc(str(pair_edges)),
        "VIS_LIB": _esc(VIS_LIB),
        "NODES_JSON": _esc_js_json(vis_nodes),
        "EDGES_JSON": _esc_js_json(vis_edges),
    }
    html = _CLUSTER_TEMPLATE
    for k, v in values.items():
        html = html.replace(f"__{k}__", v)
    return html


def cluster_fingerprint(graph: Dict[str, Any]) -> str:
    """词簇图指纹：中心词 + 簇成员集合变化即重绘（行序无关）。"""
    payload = json.dumps(
        {
            "v": CLUSTER_TEMPLATE_VERSION,
            "center": graph.get("center") or "",
            "nodes": sorted(n["id"] for n in graph.get("nodes", [])),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def ensure_cluster_html(graph: Dict[str, Any]) -> str:
    """生成（或复用）当前词的词簇图静态文件，返回 /app/static/ 相对 URL。"""
    if not graph or not graph.get("nodes"):
        return ""

    fp = cluster_fingerprint(graph)
    filename = f"cluster_graph_{fp}.html"
    path = os.path.join(STATIC_DIR, filename)

    try:
        os.makedirs(STATIC_DIR, exist_ok=True)
        if not os.path.exists(path):
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(build_cluster_html(graph))
            os.replace(tmp_path, path)
            logger.info(f"词簇图已生成: {filename}")
            _prune_cluster_graphs(keep=filename)
        return f"/app/static/{filename}"
    except OSError as e:
        logger.error(f"写入词簇图失败: {e}")
        return ""


def _prune_cluster_graphs(keep: str) -> None:
    """清理旧指纹的词簇图文件，避免 static/ 越积越多。"""
    try:
        for name in os.listdir(STATIC_DIR):
            if (name.startswith("cluster_graph_") and name.endswith(".html")
                    and name != keep):
                os.remove(os.path.join(STATIC_DIR, name))
    except OSError as e:
        logger.warning(f"清理旧词簇图文件失败: {e}")
