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

# 粒子数的硬上限（用户要求：最多 200 个动态粒子）。
# Python 侧定义一次，模板通过 __PARTICLE_MAX__ 注入，测试也读这个常量，
# 避免「代码里 200、文案里 200、测试里 200」三处各写一遍将来对不上。
PARTICLE_MAX = 200

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
TEMPLATE_VERSION = 8


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
        "NODES_JSON": json.dumps(vis_nodes, ensure_ascii=False),
        "EDGES_JSON": json.dumps(vis_edges, ensure_ascii=False),
        "LEGEND_JSON": json.dumps(legend, ensure_ascii=False),
        "NODE_COUNT": str(stats.get("node_count", len(nodes))),
        "EDGE_COUNT": str(stats.get("edge_count", len(links))),
        "CLUSTER_COUNT": str(stats.get("cluster_count", len(clusters))),
        "PARTICLE_MAX": str(PARTICLE_MAX),
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
            with open(path, "w", encoding="utf-8") as f:
                f.write(build_graph_html(graph))
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
  #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 150px; }
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
  <div id="toolbar">
    <button class="tool-btn on" id="btn-particles"><span class="dot"></span>粒子动效</button>
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
  <div id="hint">滚轮缩放 · 拖拽平移 · 悬停看节点 · 点击看邻居</div>
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

// ---------- 信息面板 ----------
function showInfo(nodeId) {
  const n = nodesDS.get(nodeId);
  if (!n) return;
  const neighborIds = network.getConnectedNodes(nodeId).filter(id => !nodesDS.get(id).hidden);
  const items = neighborIds.map(nid => {
    const nb = nodesDS.get(nid);
    return '<span class="neighbor-link" style="border-left-color:'
      + esc(nb.color.background) + '" data-nid="' + esc(nid) + '">' + esc(nb.label) + '</span>';
  }).join('');
  let html = '<div class="field"><b>' + esc(n.label) + '</b></div>'
    + '<div class="field">语义簇: ' + esc(n._clusterLabel) + '</div>'
    + '<div class="field">次范畴: ' + esc(n._subCat) + '</div>'
    + '<div class="field">主范畴: ' + esc(n._mainCat || '-') + '</div>'
    + '<div class="field">近义边数: ' + n._degree + '</div>';
  if (neighborIds.length) {
    html += '<div class="field" style="margin-top:8px;color:#aaa;font-size:11px">'
      + '近义动词（' + neighborIds.length + '）</div>'
      + '<div id="neighbors-list">' + items + '</div>';
  }
  document.getElementById('info-content').innerHTML = html;
}

// hover 比 click 的事件参数更可靠，两者都接上
let hoveredNodeId = null;
network.on('hoverNode', p => { hoveredNodeId = p.node; container.style.cursor = 'pointer'; });
network.on('blurNode', () => { hoveredNodeId = null; container.style.cursor = 'default'; });
container.addEventListener('click', () => {
  if (hoveredNodeId !== null) focusNode(hoveredNodeId, false);
});
network.on('click', p => {
  if (p.nodes.length > 0) showInfo(p.nodes[0]);
  else if (hoveredNodeId === null) {
    document.getElementById('info-content').innerHTML =
      '<span class="empty">点击任意节点查看详情</span>';
  }
});

// ---------- 聚焦 ----------
const focusCb = document.getElementById('focus-cb');

function clearDim() {
  nodesDS.update(RAW_NODES.map(n => ({ id: n.id, opacity: 1 })));
}

function focusNode(nodeId, doFocus) {
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
// 粒子动效层
// ============================================
// 为什么用**独立 canvas 覆盖层**而不是把节点本身做成粒子：
//   * vis-network 负责布局与交互，粒子层只读它的坐标 —— 两者互不干扰，
//     粒子再花哨也不会影响拖拽、缩放、命中检测；
//   * 请求动画帧只重绘粒子层，不必让 vis-network 重绘 2143 条边（那是它最贵的部分）；
//   * 粒子数量与节点数量解耦，可以按上限裁剪，而节点仍然全部可见可点。
const pcanvas = document.getElementById('particles');
const pctx = pcanvas.getContext('2d');

const PARTICLE_MAX = __PARTICLE_MAX__;      // 硬上限：超过就不再加粒子
const PARTICLE_BASE = 3;       // 每个节点的基础粒子数
const PARTICLE_EXTRA_MAX = 5;  // 度数最高的节点额外再加几个
// 有选中节点时，**先把它所在簇喂饱**：该簇最多可占这么大比例的预算。
// 只做「排在最前」是不够的 —— 轮转下 3 个词的小簇 3 轮就被塞满，
// 再轮下去也涨不上去，选中与不选中的粒子数完全一样（实测过）。
const FOCUS_SHARE = 0.5;

let particleOn = true;
let particles = [];
let pW = 0, pH = 0, dpr = 1;

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

// 决定哪些节点有粒子：**优先当前有选中节点的簇**。
// 用户明确要求「如果有被选中的词簇，则优先该簇有动态粒子」—— 簇大时粒子预算
// 不够分，所以先把预算给用户正在看的那个簇，剩下的按度数（簇大小）补。
function focusClusterIds() {
  const ids = new Set();
  network.getSelectedNodes().forEach(id => {
    const n = nodesDS.get(id);
    if (n && !n.hidden) ids.add(n._clusterId);
  });
  return ids;
}

function particlesPerNode(n, maxDeg) {
  const extra = Math.round(PARTICLE_EXTRA_MAX * (n._degree / maxDeg));
  return PARTICLE_BASE + extra;
}

function rebuildParticles() {
  particles = [];
  const focusClusters = focusClusterIds();
  // 顺序有意义：被选中的簇排前面，先吃预算
  const visible = RAW_NODES.filter(n => !nodesDS.get(n.id).hidden);
  if (!visible.length) { updateParticleInfo(0); return; }

  const maxDeg = visible.reduce((m, n) => Math.max(m, n._degree), 1) || 1;

  // 按簇分组，簇内按度数降序（大簇里先给枢纽节点）
  const byCluster = new Map();
  for (const n of visible) {
    if (!byCluster.has(n._clusterId)) byCluster.set(n._clusterId, []);
    byCluster.get(n._clusterId).push(n);
  }
  for (const list of byCluster.values()) list.sort((a, b) => b._degree - a._degree);

  const clusterIds = [...byCluster.keys()].sort((a, b) => {
    const fa = focusClusters.has(a) ? 1 : 0;
    const fb = focusClusters.has(b) ? 1 : 0;
    if (fa !== fb) return fb - fa;                       // 选中的簇优先
    return byCluster.get(b).length - byCluster.get(a).length;  // 其次按簇大小
  });

  function takeFrom(n) {
    const want = Math.min(particlesPerNode(n, maxDeg), PARTICLE_MAX - particles.length);
    for (let i = 0; i < want; i++) {
      particles.push({
        node: n.id,
        cluster: n._clusterId,
        color: n.color.background,
        angle: Math.random() * Math.PI * 2,
        // 轨道半径略大于节点半径，粒子绕在节点外圈而不是被节点盖住
        radius: n.size * 0.55 + Math.random() * 4,
        speed: 0.008 + Math.random() * 0.025,
        size: 1.4 + Math.random() * 2.2,
        alpha: 0.45 + Math.random() * 0.5,
      });
    }
    return want;
  }

  // 轮转分配：每轮给每个簇依次取一个节点，直到预算用光。
  // 不能简单按度数排序取前 N —— 那样 200 个预算会被一个 56 词的大簇全部吃掉，
  // 整张图上只有一处发光（实测过：200 个粒子全落在「常态行走」）。
  // 轮转保证每个簇都有粒子，被选中的簇因为排在最前，每轮先拿、拿得更多。
  const cursor = new Map(clusterIds.map(c => [c, 0]));

  // 第一阶段：把选中簇喂到 FOCUS_SHARE 的预算。每一轮给它的每个节点再来一份，
  // 直到达到配额 —— 这样大簇会明显变密。
  if (focusClusters.size) {
    const quota = Math.floor(PARTICLE_MAX * FOCUS_SHARE);
    const focusList = clusterIds.filter(c => focusClusters.has(c));
    let fProgress = true;
    while (particles.length < quota && fProgress) {
      fProgress = false;
      for (const cid of focusList) {
        if (particles.length >= quota) break;
        for (const n of byCluster.get(cid)) {
          if (particles.length >= quota) break;
          takeFrom(n);
        }
        fProgress = true;
      }
    }
  }

  // 第二阶段：按簇轮转，把剩余预算分摊到所有簇（含选中簇）。
  // 轮转而不是「按度数取前 N」：实测后者会让 56 词的大簇独占全部 200 个粒子，
  // 25 个簇里只有 1 个发光。
  let progress = true;
  while (particles.length < PARTICLE_MAX && progress) {
    progress = false;
    for (const cid of clusterIds) {
      if (particles.length >= PARTICLE_MAX) break;
      const list = byCluster.get(cid);
      const i = cursor.get(cid);
      if (i >= list.length) continue;
      cursor.set(cid, i + 1);
      takeFrom(list[i]);
      progress = true;
    }
  }
  updateParticleInfo(particles.length);
}

function updateParticleInfo(shown) {
  const f = focusClusterIds().size;
  document.getElementById('particle-info').textContent =
    shown + ' / ' + PARTICLE_MAX + ' 粒子' + (f ? '（聚焦选中簇）' : '');
}

function drawParticles() {
  requestAnimationFrame(drawParticles);
  if (!particleOn) {
    pctx.clearRect(0, 0, pW, pH);
    return;
  }
  pctx.clearRect(0, 0, pW, pH);

  // 一次性取所有位置，避免每个粒子各调一次 getPositions
  const ids = [];
  const seen = new Set();
  for (const p of particles) { if (!seen.has(p.node)) { seen.add(p.node); ids.push(p.node); } }
  const pos = network.getPositions(ids);

  pctx.globalCompositeOperation = 'lighter';
  for (const p of particles) {
    const n = nodesDS.get(p.node);
    if (!n || n.hidden) continue;
    const cur = pos[p.node];
    if (!cur) continue;
    const dom = network.canvasToDOM(cur);
    if (dom.x < -20 || dom.y < -20 || dom.x > pW + 20 || dom.y > pH + 20) continue;

    // 绕着自己的节点做轨道运动。轨道半径随节点大小走，且带一点向外的漂移感，
    // 看起来像节点在往外冒能量，而不是一群独立光点到处乱飘。
    p.angle += p.speed;
    const pulse = 0.75 + 0.25 * Math.sin(p.angle * 2.2);

    // 拖尾：沿运动方向往回画 3 个逐渐变小的残影。
    // 只画一个圆点的话，在 25 簇 155 节点的图上几乎看不见（实测非透明像素仅 ~1300）；
    // 拖尾既提高可见度，也带来「在动」的观感。
    const TRAIL = 3;
    for (let t = TRAIL; t >= 0; t--) {
      const a = p.angle - p.speed * t * 4.5;
      const ox = Math.cos(a) * p.radius;
      const oy = Math.sin(a * 1.3) * p.radius;
      const fade = t === 0 ? 1 : 0.30 * (1 - t / (TRAIL + 1));
      const scale = t === 0 ? 1 : 0.55;
      pctx.globalAlpha = p.alpha * pulse * fade;
      pctx.fillStyle = p.color;
      pctx.beginPath();
      pctx.arc(dom.x + ox, dom.y + oy, p.size * pulse * scale, 0, Math.PI * 2);
      pctx.fill();
    }
  }
  pctx.globalAlpha = 1;
  pctx.globalCompositeOperation = 'source-over';
}

// ---------- 工具栏 ----------
document.getElementById('btn-particles').addEventListener('click', e => {
  particleOn = !particleOn;
  e.currentTarget.classList.toggle('on', particleOn);
  if (!particleOn) pctx.clearRect(0, 0, pW, pH);
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

// 初始：全图铺开
renderLegend();
updateStats();
rebuildParticles();
drawParticles();
</script>
</body>
</html>
"""
