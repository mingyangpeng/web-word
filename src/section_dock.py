"""section_dock —— 页内功能快捷导航条（macOS Dock 形态）。

问题背景：平台每个功能页内部还有若干段（域系初判页＝三域十二系总览／逐义位
明细／义位详情；语义分析页＝十个 tab…），长页面要切到某一段只能一路滚动。
本模块在**页面顶部**注入一条悬浮胶囊导航，把当前页的段与 tab 收成一排可点
chip，点一下即刻跳到目标，鼠标靠近时 chip 像 macOS Dock 一样轻微放大。

三条设计纪律：

  * **零 Python 侧页面改动**：段清单由前端扫描实际 DOM 得出（`stMain` 内可见
    的 `h3` 与 `[role="tab"]`），因此每个现有页面自动获得导航，新增页面无需
    登记；页内改标题/加 tab 也不需要同步维护任何 Python 表（无漂移面）。
  * **只读 DOM、不碰 Streamlit 状态**：跳段是纯滚动；跳 tab 是程序化点击
    已有的 tab 元素（Streamlit 的 tab 是纯前端切换，不触发脚本重跑）。导航条
    不写 session_state、不参与路由，七区菜单契约与权限门一概不受影响。
  * **自愈**：每次重跑都会重新注入桥脚本；桥内定时器再兜一层——DOM 被重跑
    替换（Streamlit 重建元素）后自动重建导航条，签名（可见段标题序列）变化
    时重建 chip 列表。

为什么位置在顶部条带而不是内容区：搜索页有一条 sticky 搜索栏（top: 4.5rem），
内容区顶部已被占；Streamlit 顶栏（stHeader，60px）中段是空的（Deploy 与
菜单在右侧），导航条落在这一条带里既不遮挡任何页面内容，也不会与搜索栏
抢位置。

平台限制备忘（实测）：本仓的浏览器环境里 `scrollTo({behavior:'smooth'})`
与 `requestAnimationFrame` 都可能不推进（rAF 帧数为 0）。因此平滑滚动一律
用 `setInterval` 逐帧改 `scrollTop` 实现，不依赖浏览器原生平滑与 rAF。

阈值：可见目标少于 MIN_ITEMS 个时整条隐藏（只有一个段的页面不需要导航）。
"""

import streamlit as st
# 注入点：`st.components.v1.html` 已被 Streamlit 标为废弃（2026-06-01 后移除，
# 1.57 实测每次渲染都打 DeprecationWarning），改用同能力的 `st.iframe`。
# 两者都是同源 srcdoc iframe，桥脚本照样能操作父文档 DOM（实测可用）。
# 测试以 `section_dock._inject` 为打桩点，不关心底层是哪一个 API。

# 导航条 DOM id / 样式 id（前端识别与自愈重建用；测试钉面）。
DOCK_ID = "ls-section-dock"
DOCK_STYLE_ID = "ls-dock-style"

# 少于该数量的可见目标就整条隐藏（单个目标无需导航）。
DOCK_MIN_ITEMS = 2

# chip 文案上限（字）：先在解释性括注前截断（谱系树（Gower + average 层次
# 聚类）→ 谱系树），再兜底硬截。12 = 图标(≤2)＋空格＋9 字正文——覆盖动态
# 段名「🎯 义位 walk-S1」不折断；用户反馈「快捷项字数不要太多」。
DOCK_LABEL_MAX = 12

# 桥脚本：在 components.html 的 iframe 内运行，操作同源父文档 DOM。
# 占位符用 {{NAME}} 形式（str.replace 单点替换，不引入 % 格式化的转义陷阱
# ——脚本里 CSS 的 50%/100% 会被 %-格式化当成占位符）。
_BRIDGE_JS_TEMPLATE = """
<script>
(function () {
  var P = window.parent, D = P.document;
  var ID = "{{DOCK_ID}}", STYLE_ID = "{{STYLE_ID}}";
  var MIN_ITEMS = {{MIN_ITEMS}}, LABEL_MAX = {{LABEL_MAX}};
  var state = { sig: null, dock: null };
  /* 属主标记：dock 挂在 body 上跨重跑存活，而它的点击监听属于**创建它的
     那个 iframe 脚本实例**。桥脚本更新（srcdoc 变化）后新实例若直接复用
     旧 dock，点击走的是已销毁 realm 的旧监听——实测静默失效。每个实例
     用随机属主接管：属主不符就拆掉重建（监听随元素一起换血）。 */
  var OWNER = "r" + Math.random().toString(36).slice(2);

  function mainEl() { return D.querySelector('[data-testid="stMain"]'); }

  function vis(el) {
    if (!el || !el.isConnected) return false;
    var cs = P.getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    if (cs.opacity !== "" && parseFloat(cs.opacity) === 0) return false;
    var r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  }

  function fullText(el) {
    return (el.innerText || "").replace(/\\s+/g, " ").trim();
  }

  /* chip 面上显示的短文案：先在解释性括注前截断（「谱系树（Gower +
     average 层次聚类）」→「谱系树」，「四类意象图式重心（AI初筛）」→
     「四类意象图式重心」），再兜底硬截 LABEL_MAX 字。括注细节不丢——
     完整标题进 chip 的 title 悬停提示。cut>0 保证截完非空（emoji 开头
     的标题不受影响）。 */
  function text(el) {
    var t = fullText(el);
    var cut = t.search(/[（(·—–：:]/);
    if (cut > 0) t = t.slice(0, cut).trim();
    return t.length > LABEL_MAX ? t.slice(0, LABEL_MAX - 1) + "\\u2026" : t;
  }

  function collect() {
    var m = mainEl();
    if (!m) return { tabs: [], heads: [] };
    var tabs = [].slice.call(m.querySelectorAll('[role="tab"]')).filter(vis);
    /* 段标题 = h2 ＋ h3 按 DOM 序混收。h2 需跳过「页面副标题」形态：
       五个工作区页在 h1 下有一个全文级的 h2 副标题（编纂成文域工作台 /
       账号与角色…），紧贴页顶、不是可导航的节——判定口径：出现在**首个
       h3 之前**的 h2 一律丢弃（副标题恒在 h3 之前；正文章节 h2 如提交页
       ⚖️ 分歧清单与仲裁、账号管理页 📦 功能模块段 都在 h3 之后，照收）。 */
    var raw = [].slice.call(m.querySelectorAll("h2, h3")).filter(function (h) {
      if (!vis(h)) return false;
      if (!(h.innerText || "").trim()) return false;
      return !(h.closest && h.closest("#" + ID));
    });
    var firstH3 = -1;
    for (var i = 0; i < raw.length; i++) {
      if (raw[i].tagName === "H3") { firstH3 = i; break; }
    }
    var heads = firstH3 === -1 ? [] : raw.slice(firstH3);
    return { tabs: tabs, heads: heads };
  }

  function sigOf(d) {
    var a = d.tabs.map(function (x) { return "t:" + text(x); }).join("|");
    var b = d.heads.map(function (x) { return "h:" + text(x); }).join("|");
    return a + "||" + b;
  }

  function ensureStyle() {
    if (D.getElementById(STYLE_ID)) return;
    var s = D.createElement("style");
    s.id = STYLE_ID;
    s.textContent = [
      "#" + ID + "{position:fixed;top:8px;left:50%;transform:translateX(-50%);",
      "z-index:1000000;display:flex;align-items:center;gap:5px;",
      "max-width:min(62vw,780px);padding:9px 10px;border-radius:18px;",
      "background:rgba(255,255,255,.74);",
      "-webkit-backdrop-filter:blur(26px) saturate(1.9);",
      "backdrop-filter:blur(26px) saturate(1.9);",
      "border:1px solid rgba(0,0,0,.07);",
      "box-shadow:0 8px 30px rgba(0,0,0,.14),0 1px 2px rgba(0,0,0,.06);",
      "overflow-x:auto;overflow-y:hidden;scrollbar-width:none;",
      "font-family:system-ui,-apple-system,'PingFang SC',sans-serif;}",
      "#" + ID + "::-webkit-scrollbar{display:none;}",
      /* chip 统一浅蓝药丸（用户定稿：语义分析页 tab 排的形态——浅蓝底、
         蓝字、全圆角），段与 tab 不再分两套色；当前项实心 accent。 */
      "#" + ID + " .ls-dock-chip{flex:0 0 auto;border:0;cursor:pointer;",
      "padding:7px 14px;border-radius:999px;background:rgba(0,113,227,.09);",
      "color:#0058b0;font-size:13px;font-weight:500;line-height:1.35;",
      "white-space:nowrap;",
      "transition:transform .16s cubic-bezier(.2,.9,.3,1.25),background .16s,color .16s;}",
      "#" + ID + " .ls-dock-chip:hover{background:rgba(0,113,227,.18);}",
      "#" + ID + " .ls-dock-chip.ls-dock-active{background:#0071E3;color:#fff;}",
      "#" + ID + " .ls-dock-sep{flex:0 0 auto;width:1px;height:18px;",
      "background:rgba(0,113,227,.25);margin:0 3px;}"
    ].join("");
    (D.head || D.documentElement).appendChild(s);
  }

  function ensureDock() {
    var dock = D.getElementById(ID);
    if (dock && dock.dataset.owner === OWNER && dock.isConnected) return dock;
    if (dock) dock.remove();           /* 旧属主（可能已销毁的 realm）→ 换血 */
    dock = D.createElement("div");
    dock.id = ID;
    dock.dataset.owner = OWNER;
    (D.body || D.documentElement).appendChild(dock);
    dock.addEventListener("click", onChipClick);
    dock.addEventListener("mousemove", onHover);
    dock.addEventListener("mouseleave", resetHover);
    return dock;
  }

  function makeChip(label, full, kind, idx) {
    var b = D.createElement("button");
    b.type = "button";
    b.className = "ls-dock-chip" + (kind === "tab" ? " ls-dock-tab" : "");
    b.setAttribute("data-kind", kind);
    b.setAttribute("data-idx", String(idx));
    b.title = full;                      /* 悬停看完整段名（括注细节不丢） */
    b.textContent = label;
    return b;
  }

  function build(dock, data) {
    dock.innerHTML = "";
    data.tabs.forEach(function (t, i) {
      dock.appendChild(makeChip(text(t), fullText(t), "tab", i));
    });
    if (data.tabs.length && data.heads.length) {
      var sep = D.createElement("span");
      sep.className = "ls-dock-sep";
      dock.appendChild(sep);
    }
    data.heads.forEach(function (h, i) {
      dock.appendChild(makeChip(text(h), fullText(h), "head", i));
    });
    dock.style.display =
      (data.tabs.length + data.heads.length) >= MIN_ITEMS ? "flex" : "none";
    cacheChips(dock);
    syncActive(data);
  }

  function cacheChips(dock) {
    [].forEach.call(dock.querySelectorAll(".ls-dock-chip"), function (c) {
      c.dataset.lsCx = String(c.offsetLeft + c.offsetWidth / 2);
    });
  }

  function headerH() {
    var h = D.querySelector('[data-testid="stHeader"]');
    return h ? h.getBoundingClientRect().height : 60;
  }

  function scrollOffset() {
    var off = headerH() + 26;
    var sb = D.querySelector(".st-key-search_bar");
    if (sb) {
      var r = sb.getBoundingClientRect();
      /* 搜索栏吸顶（顶部贴到顶栏下沿）时才需要额外让位 */
      if (r.height > 0 && r.top <= headerH() + 12) off += r.height + 8;
    }
    return off;
  }

  function easeScroll(m, to) {
    if (!m) return;
    var from = m.scrollTop, t0 = Date.now(), dur = 380, n = 0;
    var timer = setInterval(function () {
      var p = Math.min(1, (Date.now() - t0) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      m.scrollTop = Math.round(from + (to - from) * e);
      if (p >= 1 || ++n > 120) clearInterval(timer);
    }, 16);
  }

  /* 元素锚定滚动：动画每帧都按目标元素**当下**的位置重算落点。
     固定目标值在两类页面上会漂（批次 37 实测）：① tab 类 chip——点击后面
     板重排，点击瞬间的几何已失效（词典管理 y=-47 / 语义分析 y=148）；②
     目标上方有懒渲染内容（账号管理账号总表 y=-434，表格布局在滚动后收
     缩）。逐帧重锚天然自愈，收敛到元素的实时位置。 */
  function scrollToEl(el, m, delayMs) {
    if (!el || !m) return;
    var start = Date.now() + (delayMs || 0), dur = 420, n = 0;
    var timer = setInterval(function () {
      if (Date.now() < start || !el.isConnected) return;
      var p = Math.min(1, (Date.now() - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      var to = Math.max(0, el.getBoundingClientRect().top
        - m.getBoundingClientRect().top + m.scrollTop - scrollOffset());
      var from = m.scrollTop;
      m.scrollTop = Math.round(from + (to - from) * e);
      if (p >= 1 || ++n > 150) clearInterval(timer);
    }, 16);
  }

  function onChipClick(ev) {
    var chip = ev.target && ev.target.closest
      ? ev.target.closest(".ls-dock-chip") : null;
    if (!chip) return;
    ev.preventDefault();
    var idx = parseInt(chip.getAttribute("data-idx"), 10);
    var kind = chip.getAttribute("data-kind");
    var m = mainEl();
    if (!m) return;
    /* 点击时现取元素：Streamlit 重跑会整体替换 DOM，构建期缓存的引用会
       失效（实测重跑后 tab 点击静默无效）——chip 上的 data-idx 配合当下
       collect() 的确定性顺序（可见 tab 先、可见 h3 后）即稳定寻址。 */
    var cur = collect();
    if (kind === "tab") {
      var t = cur.tabs[idx];
      if (!t || !t.isConnected) return;
      t.click();                       /* Streamlit tab 纯前端切换，不触发重跑 */
      var bar = t.closest('[data-testid="stTabs"]');
      if (bar) {
        /* 等面板切换重排完再滚（120ms），滚动本身仍逐帧重锚 */
        scrollToEl(bar, m, 120);
      }
    } else {
      scrollToEl(cur.heads[idx], m, 0);
    }
  }

  function onHover(ev) {
    var dock = state.dock;
    if (!dock) return;
    var dr = dock.getBoundingClientRect();
    var cx = ev.clientX - dr.left + dock.scrollLeft;
    [].forEach.call(dock.querySelectorAll(".ls-dock-chip"), function (c) {
      var base = parseFloat(c.dataset.lsCx || "0");
      var d = Math.abs(cx - base);
      var f = Math.max(0, 1 - d / 92);
      var s = 1 + 0.18 * f * f;
      c.style.transform = "scale(" + s.toFixed(3) + ")";
    });
  }

  function resetHover() {
    var dock = state.dock;
    if (!dock) return;
    [].forEach.call(dock.querySelectorAll(".ls-dock-chip"), function (c) {
      c.style.transform = "";
    });
  }

  /* 当前段判定（单一规则，避免「贴底」与「越阈」两规则叠加出双高亮）：
     贴底 → 末段；否则取「最后一个已越过阈值」的段（实测语料数据集页
     末段距阈值差 28px，不贴底永远点不亮，故贴底特判收口在同一个函数）。 */
  function activeHeadIdx(data, m) {
    if (!m || !data.heads.length) return -1;
    if (m.scrollTop + m.clientHeight >= m.scrollHeight - 8) {
      return data.heads.length - 1;
    }
    var best = -1;
    for (var i = 0; i < data.heads.length; i++) {
      var y = data.heads[i].getBoundingClientRect().top - m.getBoundingClientRect().top;
      if (y <= scrollOffset() + 40) best = i;
      else break;
    }
    return best;
  }

  function syncActive(data) {
    var dock = state.dock;
    if (!dock) return;
    var m = mainEl();
    var headActive = activeHeadIdx(data, m);
    [].forEach.call(dock.querySelectorAll(".ls-dock-chip"), function (c) {
      var idx = parseInt(c.getAttribute("data-idx"), 10);
      var kind = c.getAttribute("data-kind");
      var on = false;
      if (kind === "tab") {
        var t = data.tabs[idx];
        on = !!t && t.getAttribute("aria-selected") === "true";
      } else {
        on = idx === headActive;
      }
      if (on) c.classList.add("ls-dock-active");
      else c.classList.remove("ls-dock-active");
    });
  }

  function tick() {
    ensureStyle();
    var dock = ensureDock();
    state.dock = dock;
    var data = collect();
    var sig = sigOf(data);
    if (sig !== state.sig) {
      state.sig = sig;
      build(dock, data);
    }
    /* 每拍都用**当下**采集的元素同步高亮：重跑换 DOM 后缓存引用失效，
       高亮会停在旧段上（与点击寻址同一纪律——任何用 Element 的地方都
       现取，state 只留 sig 与 dock 引用）。 */
    syncActive(data);
  }

  ensureStyle();
  tick();
  setInterval(tick, 450);
  var m0 = mainEl();
  if (m0) {
    m0.addEventListener("scroll", function () { syncActive(collect()); },
                        { passive: true });
  }
})();
</script>
"""


def _bridge_js() -> str:
    """桥脚本（常量单点：id/阈值/截断宽度只在 Python 侧定义）。"""
    js = _BRIDGE_JS_TEMPLATE
    js = js.replace("{{DOCK_ID}}", DOCK_ID)
    js = js.replace("{{STYLE_ID}}", DOCK_STYLE_ID)
    js = js.replace("{{MIN_ITEMS}}", str(DOCK_MIN_ITEMS))
    js = js.replace("{{LABEL_MAX}}", str(DOCK_LABEL_MAX))
    return js


def _inject(html: str, height: int = 1) -> None:
    """把桥脚本注成同源 iframe（打桩点；st.iframe 取代废弃的 components.html）。

    height=1 而非 0：st.iframe 校验拒绝 0（StreamlitInvalidHeightError），
    1px 在版面上不可见。
    """
    st.iframe(html, height=height)


def render_section_dock() -> None:
    """注入页内快捷导航条（每次页面渲染调用一次，height=1 不占版面（st.iframe 拒绝 0））。

    调用位置契约：app.main() 页面分派之前、模块停用闸之后——停用模块的页
    会被 gate 拦下不渲染，导航条自然也不出；页面本体渲染顺序不影响结果
    （桥脚本自己轮询 DOM，直到可见段/tab 稳定）。
    """
    _inject(_bridge_js())
