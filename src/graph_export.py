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


def data_fingerprint(graph: Dict[str, Any]) -> str:
    """图谱数据指纹，用于给产物文件名加版本后缀。"""
    payload = json.dumps(
        {
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
  #graph { flex: 1; background: #0f0f1a; }
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
</style>
</head>
<body>
<div id="graph"></div>
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

function applyFilter() {
  nodesDS.update(RAW_NODES.map(n => ({ id: n.id, hidden: !enabled.has(n._clusterId) })));
  edgesDS.update(RAW_EDGES.map(e => ({
    id: e.id,
    hidden: !(enabled.has(nodesDS.get(e.from)._clusterId)
              && enabled.has(nodesDS.get(e.to)._clusterId)),
  })));
  updateStats();
  renderLegend();
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
}

focusCb.addEventListener('change', () => {
  if (focusCb.checked) {
    const sel = network.getSelectedNodes();
    if (sel.length) focusNode(sel[0], false);
  } else {
    clearDim();
  }
});

// 初始：全图铺开
renderLegend();
updateStats();
</script>
</body>
</html>
"""
