"""范畴深挖页面组 —— 跑范畴英汉对比研究的四个视图（Streamlit）。

数据来自 data/d1/ 两个 xlsx（scripts/load_category_study.py 灌入
categories / cs_* 8 表，见 src/category_study.py）。页面结构：

  视图1 双语聚类对比面板  英 5 簇 vs 汉 5 簇卡片对照，成员可展开
  视图2 编码矩阵热图      32×18 / 19×18 特征矩阵着色网格（plotly）
  视图3 跨语言对齐        英簇↔汉簇二部图（连线按 Gower 距离着色）+ 雷达叠加
  视图4 范畴总览与甄别清单 统计卡 + 英汉双清单对照表

由 app.py 的 render_category_study_page() 分派（session_state["cs_view"]）。
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.category_study import (
    FEATURE_COLUMNS, CLUSTERING_FEATURES, VERDICT_ORDER, SCHEMA_ORDER,
    derive_image_schema, compute_schema_alignment,
    category_study_ready, get_categories, get_senses_with_features,
    get_cluster_runs, get_clusters_with_members, get_alignments,
    get_cluster_profiles, get_screening_stats,
)
from src.design_system import HEADER_H1, HEADER_H3

logger = logging.getLogger(__name__)

# 视图清单（页面顶部 tab 顺序 = 用户选定的实现顺序）
VIEWS = ["cluster", "matrix", "align", "overview"]
VIEW_LABELS = {
    "cluster": "🫱🫲 双语聚类对比",
    "matrix": "🔥 编码矩阵热图",
    "align": "🔀 跨语言对齐",
    "overview": "📋 范畴总览与甄别清单",
}

# 编码值三色（0/1/2）：与编码矩阵表的视觉直觉一致 —— 值越高越"实"
FEATURE_COLORS = {0: "#f0f4f8", 1: "#90cdf4", 2: "#2b6cb0"}
VERDICT_COLORS = {
    "完全对齐": "#2f855a", "部分对齐": "#4299e1",
    "错位对齐": "#ed8936", "零对齐": "#e53e3e",
}
STATUS_COLORS = {
    "保留": "#2f855a", "目标": "#2f855a", "边缘": "#ed8936", "剔除": "#e53e3e",
}


@st.cache_data(ttl=600, show_spinner=False)
def _load_category(code: str) -> Optional[Dict[str, Any]]:
    """加载一个范畴的全部展示数据（页面级缓存，10 分钟）。

    返回 {category, senses, en_run, zh_run, en_clusters, zh_clusters,
    alignments, profiles_en, profiles_zh, stats}；数据未灌入返回 None。
    """
    if not category_study_ready(code):
        return None
    categories = [c for c in get_categories() if c["code"] == code]
    if not categories:
        return None
    category = categories[0]
    category_id = int(category["id"])

    senses = get_senses_with_features(category_id)
    runs = get_cluster_runs(category_id)
    en_run = next((r for r in runs if r["language"] == "en"), None)
    zh_run = next((r for r in runs if r["language"] == "zh"), None)
    en_clusters = get_clusters_with_members(en_run["run_id"]) if en_run else []
    zh_clusters = get_clusters_with_members(zh_run["run_id"]) if zh_run else []
    alignments = get_alignments(category_id)
    return {
        "category": category,
        "senses": senses,
        "en_run": en_run, "zh_run": zh_run,
        "en_clusters": en_clusters, "zh_clusters": zh_clusters,
        "alignments": alignments,
        "profiles_en": get_cluster_profiles(en_run["run_id"]) if en_run else {},
        "profiles_zh": get_cluster_profiles(zh_run["run_id"]) if zh_run else {},
        "stats": get_screening_stats(category_id),
    }


def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span），用于判定/语体/标注。"""
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'padding:1px 8px;border-radius:10px;font-size:0.78em;'
        f'margin-right:4px;">{text}</span>'
    )


def _cluster_title(cl: Dict[str, Any]) -> str:
    """簇卡片标题：簇号 + 短名（括号前的主名）。"""
    short = cl["name"].split("（")[0]
    return f"簇{cl['cluster_no']} · {short}"


def _render_profile_bars(profile: Dict[str, float]) -> None:
    """簇特征画像：均值≥0.3 的特征画水平条（st.progress 风格用 HTML 条）。"""
    if not profile:
        return
    items = sorted(profile.items(), key=lambda kv: -kv[1])
    rows = []
    for code, mean in items[:8]:  # 最多画 8 条，避免卡片过长
        pct = min(mean / 2.0, 1.0) * 100  # 值域 0-2 → 0-100%
        label = next((f["label"] for f in FEATURE_COLUMNS
                      if f["code"] == code), code)
        rows.append(
            f'<div style="display:flex;align-items:center;margin:2px 0;">'
            f'<div style="width:110px;font-size:0.8em;color:#4a5568;">{label}</div>'
            f'<div style="flex:1;background:#edf2f7;border-radius:4px;height:12px;">'
            f'<div style="width:{pct:.0f}%;background:#4299e1;height:12px;'
            f'border-radius:4px;"></div></div>'
            f'<div style="width:34px;text-align:right;font-size:0.8em;">{mean:.2f}</div>'
            f'</div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def _render_member_expander(cl: Dict[str, Any], key_prefix: str) -> None:
    """簇成员列表（expander 内）：词目·义位标签 + 释义 + 编码徽章。"""
    with st.expander(f"成员义位（{len(cl['members'])} 条）"):
        for m in cl["members"]:
            name = m["lemma"] + (f"·{m['sense_no']}" if m["sense_no"] else "")
            status_badge = _badge(
                m["status"], STATUS_COLORS.get(m["status"], "#4a5568"))
            header = f"**{name} · {m['sense_label']}** {status_badge}"
            if m.get("tag") and m["tag"] != "无":
                header += _badge(m["tag"], "#805ad5")
            st.markdown(header, unsafe_allow_html=True)
            if m.get("definition"):
                st.caption(str(m["definition"])[:160])
            feats = m.get("features") or {}
            active = [c for c in CLUSTERING_FEATURES if feats.get(c)]
            if active:
                st.caption("编码：" + " ".join(
                    f"{c}={feats[c]}" for c in active))


# ============================================
# 视图1：双语聚类对比面板
# ============================================

def render_cluster_compare_view(data: Dict[str, Any]) -> None:
    """英 5 簇 vs 汉 5 簇卡片对照：左英右汉，按对齐关系配对排序。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>双语独立聚类对比"
                f"（Gower + average）</h3>", unsafe_allow_html=True)

    en_run, zh_run = data["en_run"], data["zh_run"]
    meta = st.columns(4)
    meta[0].metric("英语簇数", len(data["en_clusters"]))
    meta[1].metric("汉语簇数", len(data["zh_clusters"]))
    meta[2].metric("英语 cophenetic",
                   f"{en_run['cophenetic']:.3f}" if en_run["cophenetic"] else "—")
    meta[3].metric("汉语 cophenetic",
                   f"{zh_run['cophenetic']:.3f}" if zh_run["cophenetic"] else "—")
    st.caption(
        "口径：程序预编码（单标注演示），正式流程需双标注 IAA 后重跑；"
        "k=5 为探索性切分。cophenetic 为共表相关系数，越高聚类越保真。"
    )

    # 核心发现置顶：完全对齐的簇对
    full = [a for a in data["alignments"] if a["verdict"] == "完全对齐"]
    for a in full:
        st.success(
            f"🎯 核心发现：英簇{a['en_cluster_no']} ↔ 汉簇{a['zh_cluster_no']} "
            f"**{a['verdict']}**（簇中心 Gower 距离 {a['gower_distance']:.3f}，"
            f"全表最小）—— {a['explanation']}"
        )

    # 对齐关系索引：en_cluster_no → (verdict, zh_cluster_no)
    align_of = {a["en_cluster_no"]: a for a in data["alignments"]}

    # 排序：英簇按簇号；每张英簇卡右侧放它对齐的汉簇卡（无对齐则留空）
    zh_by_no = {cl["cluster_no"]: cl for cl in data["zh_clusters"]}
    for en_cl in data["en_clusters"]:
        a = align_of.get(en_cl["cluster_no"])
        zh_cl = zh_by_no.get(a["zh_cluster_no"]) if a else None
        left, right = st.columns(2)
        with left:
            _render_cluster_card(en_cl, "en", a)
        with right:
            if zh_cl:
                _render_cluster_card(zh_cl, "zh", a)
            else:
                st.info("（该英簇无对齐汉簇）")


def _render_cluster_card(cl: Dict[str, Any], language: str,
                         alignment: Optional[Dict[str, Any]]) -> None:
    """单张簇卡片：标题 + 规模 + 对齐判定徽章 + 特征画像 + 成员 expander。"""
    lang_label = "英" if language == "en" else "汉"
    verdict_html = ""
    if alignment:
        color = VERDICT_COLORS.get(alignment["verdict"], "#4a5568")
        verdict_html = _badge(
            f"{alignment['verdict']} · d={alignment['gower_distance']:.3f}"
            if alignment["gower_distance"] is not None
            else alignment["verdict"], color)
    st.markdown(
        f'<div style="border:1px solid #e2e8f0;border-radius:8px;'
        f'padding:12px;margin-bottom:8px;background:#f7fafc;">'
        f'<div style="font-weight:600;">{lang_label} · {_cluster_title(cl)}'
        f'<span style="color:#718096;font-weight:400;">（{cl["size"]} 条）</span>'
        f'{verdict_html}</div></div>',
        unsafe_allow_html=True,
    )
    st.caption(cl["name"])
    _render_profile_bars(cl.get("profile") or {})
    if cl.get("note"):
        st.caption(f"💡 {cl['note']}")
    _render_member_expander(cl, f"{language}_{cl['cluster_no']}")


# ============================================
# 视图2：编码矩阵热图
# ============================================

def render_matrix_view(data: Dict[str, Any]) -> None:
    """编码矩阵热图：行=义位，列=P/M/C/A 特征，值 0/1/2 三色。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>义位 × 特征编码矩阵</h3>",
                unsafe_allow_html=True)

    lang = st.radio("语言侧", options=["en", "zh"],
                    format_func=lambda v: "英语（32 义位）" if v == "en"
                    else "汉语（19 条目）", horizontal=True, key="cs_matrix_lang")

    status_filter = st.multiselect(
        "判定筛选（汉语侧）", options=["保留", "边缘", "剔除"],
        default=["保留", "边缘"], key="cs_matrix_status",
        help="英语侧无三态判定，此筛选只影响汉语。")

    senses = [s for s in data["senses"] if s["language"] == lang]
    if lang == "zh" and status_filter:
        senses = [s for s in senses if s["status"] in status_filter]
    if not senses:
        st.info("当前筛选下无义位。")
        return

    # 矩阵：行标签 = 词目·义项号·义位标签；列 = 特征码
    rows, labels = [], []
    for s in senses:
        labels.append(
            f"{s['lemma']}"
            + (f"·{s['sense_no']}" if s["sense_no"] and s["sense_no"] != "—" else "")
            + f" {s['sense_label']}")
        feats = s.get("features") or {}
        rows.append([feats.get(f["code"]) for f in FEATURE_COLUMNS])

    df = pd.DataFrame(rows, index=labels,
                      columns=[f["code"] for f in FEATURE_COLUMNS])

    try:
        import plotly.graph_objects as go
        fig = go.Figure(data=go.Heatmap(
            z=df.values,
            x=list(df.columns),
            y=list(df.index),
            colorscale=[[0.0, FEATURE_COLORS[0]], [0.5, FEATURE_COLORS[1]],
                        [1.0, FEATURE_COLORS[2]]],
            zmin=0, zmax=2,
            xgap=1, ygap=1,
            hovertemplate="%{y}<br>%{x} = %{z}<extra></extra>",
        ))
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=max(420, 22 * len(df) + 120),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(side="top", tickangle=-45),
            plot_bgcolor="#ffffff",
        )
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.dataframe(df.style.background_gradient(
            cmap="Blues", vmin=0, vmax=2), use_container_width=True)

    st.caption(
        "列序与编码矩阵表一致：P（路径）/ M1（主体）/ M2（情态）/ M3（介质）/ "
        "C1（动因）进聚类矩阵；A1-A3 仅核验不进矩阵。值域 0/1/2。"
    )

    # 行按簇着色的辅助表：义位 → 簇号
    with st.expander("查看义位 → 簇归属对照"):
        rows2 = [{
            "义位": label,
            "簇": s["cluster"]["cluster_no"] if s.get("cluster") else "—",
            "判定": s["status"],
            "主体": s.get("subject_type") or "",
            "语体": s.get("register") or "",
            "备注": s.get("remark") or "",
        } for label, s in zip(labels, senses)]
        st.dataframe(pd.DataFrame(rows2), use_container_width=True,
                     hide_index=True)


# ============================================
# 视图3：跨语言对齐二部图
# ============================================

def render_alignment_view(data: Dict[str, Any]) -> None:
    """跨语言对齐：簇对齐（二部图+雷达）与图式对齐（四类图式矩阵）两个子视图。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>跨语言簇对齐（四类判定）</h3>",
                unsafe_allow_html=True)

    alignments = data["alignments"]
    if not alignments:
        st.info("无对齐数据。")
        return

    verdict_counts = {}
    for a in alignments:
        verdict_counts[a["verdict"]] = verdict_counts.get(a["verdict"], 0) + 1
    cols = st.columns(len(VERDICT_ORDER))
    for i, v in enumerate(VERDICT_ORDER):
        cols[i].metric(v, verdict_counts.get(v, 0))

    # ---- 二部图（plotly scatter + lines）----
    try:
        import plotly.graph_objects as go
        en_clusters = data["en_clusters"]
        zh_clusters = data["zh_clusters"]
        n_en, n_zh = len(en_clusters), len(zh_clusters)
        fig = go.Figure()

        # 连线：距离越近越绿
        for a in alignments:
            y_en = n_en - a["en_cluster_no"]  # 簇1 在顶部
            y_zh = n_zh - a["zh_cluster_no"]
            d = a["gower_distance"]
            color = ("#2f855a" if d is not None and d < 0.1 else
                     "#4299e1" if d is not None and d < 0.2 else "#e53e3e")
            fig.add_trace(go.Scatter(
                x=[0, 1], y=[y_en, y_zh], mode="lines",
                line=dict(color=color, width=2 + (1.0 - (d or 0)) * 4),
                hovertemplate=(f"英簇{a['en_cluster_no']} ↔ 汉簇{a['zh_cluster_no']}"
                               f"<br>距离 {d}<br>{a['verdict']}<extra></extra>"
                               if d is not None else
                               f"英簇{a['en_cluster_no']} ↔ 汉簇{a['zh_cluster_no']}"
                               f"<br>{a['verdict']}<extra></extra>"),
                showlegend=False,
            ))

        # 节点：左英右汉
        for lang, clusters, x in (("en", en_clusters, 0), ("zh", zh_clusters, 1)):
            for cl in clusters:
                y = (n_en if lang == "en" else n_zh) - cl["cluster_no"]
                short = cl["name"].split("（")[0]
                fig.add_trace(go.Scatter(
                    x=[x], y=[y], mode="markers+text",
                    marker=dict(size=18 + cl["size"], color="#4a5568"),
                    text=[f"簇{cl['cluster_no']} {short}<br>({cl['size']}条)"],
                    textposition=("middle left" if lang == "en" else "middle right"),
                    textfont=dict(size=11),
                    hovertemplate=f"{cl['name']}<extra></extra>",
                    showlegend=False,
                ))
        fig.update_xaxes(range=[-0.75, 1.75], showgrid=False, zeroline=False,
                         visible=False)
        fig.update_yaxes(showgrid=False, zeroline=False, visible=False)
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            height=max(360, 90 * max(n_en, n_zh)),
            plot_bgcolor="#ffffff",
            annotations=[
                dict(x=0, y=n_en + 0.6, xref="x", yref="y",
                     text="英语簇", showarrow=False, font=dict(size=13)),
                dict(x=1, y=n_zh + 0.6, xref="x", yref="y",
                     text="汉语簇", showarrow=False, font=dict(size=13)),
            ],
        )
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        pass

    st.caption("连线颜色：绿（d<0.10）/ 蓝（0.10≤d<0.20）/ 红（d≥0.20）；"
               "线越粗距离越近。节点大小 = 簇规模。")

    # ---- 对齐明细表 ----
    rows = [{
        "英语簇": f"英簇{a['en_cluster_no']}",
        "英语簇名": a["en_cluster_name"].split("（")[0],
        "规模": a["en_size"],
        "汉语簇": f"汉簇{a['zh_cluster_no']}",
        "汉语簇名": a["zh_cluster_name"].split("（")[0],
        "规模 ": a["zh_size"],
        "Gower 距离": a["gower_distance"],
        "判定": a["verdict"],
    } for a in alignments]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for a in alignments:
        color = VERDICT_COLORS.get(a["verdict"], "#4a5568")
        st.markdown(
            f"**英簇{a['en_cluster_no']} ↔ 汉簇{a['zh_cluster_no']}** "
            + _badge(a["verdict"], color)
            + (f"（d={a['gower_distance']:.3f}）"
               if a["gower_distance"] is not None else ""),
            unsafe_allow_html=True)
        if a.get("explanation"):
            st.caption(a["explanation"])

    # ---- 簇画像雷达叠加（完全对齐簇对）----
    _render_radar_overlay(data)

    # ---- 图式层对齐（中英四类图式对照）----
    st.divider()
    _render_schema_alignment(data)


def _render_schema_alignment(data: Dict[str, Any]) -> None:
    """图式层中英对齐：四类图式矩阵 + 逐图式成员清单。

    图式由 P/M/C 编码推导（derive_image_schema）：追逐标注 → 互动位移；
    P1=1 → 源点脱离；P2/P3=1 → 终点抵达；其余 → 方式伴随。
    对齐距离 = 两侧图式中心的 15 列聚类特征均值差的平均（/2 归一）。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>图式层中英对齐"
                f"（四类意象图式）</h3>", unsafe_allow_html=True)

    rows = compute_schema_alignment(data["senses"])
    if not rows:
        st.info("无编码数据，无法推导图式。")
        return

    # ---- 对齐矩阵 ----
    # 判定列在 dataframe 里会被压窄（只剩首字），改用 HTML 徽章行渲染
    try:
        import plotly.graph_objects as go
        labels = [f"{r['schema']}\nEN {r['en_size']} / ZH {r['zh_size']}"
                  for r in rows]
        verdict_color = {"完全对齐": 2, "部分对齐": 1, "零对齐": 0}
        z = [[verdict_color.get(r["verdict"], 0)] for r in rows]
        fig = go.Figure(data=go.Heatmap(
            z=z, x=["汉语侧"], y=[r["schema"] for r in rows],
            colorscale=[[0.0, "#fde8e8"], [0.5, "#e2ecf8"], [1.0, "#e6f4ea"]],
            zmin=0, zmax=2, xgap=2, ygap=2,
            text=[[f"EN {r['en_size']} 条 / ZH {r['zh_size']} 条<br>"
                   f"{r['verdict']}"
                   + (f"（d={r['distance']:.3f}）" if r["distance"] is not None
                      else "")] for r in rows],
            hovertemplate="%{y}<br>%{text}<extra></extra>",
            showscale=False,
        ))
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10), height=280,
            yaxis=dict(autorange="reversed"),
            xaxis=dict(side="top"),
            plot_bgcolor="#ffffff",
        )
        left, right = st.columns([2, 3])
        with left:
            st.plotly_chart(fig, use_container_width=True)
        with right:
            st.markdown(
                "<div style='font-size:0.85em;color:#4a5568;'>"
                "图式 ｜ 英语 ｜ 汉语 ｜ 距离 ｜ 判定</div>",
                unsafe_allow_html=True)
            for r in rows:
                color = VERDICT_COLORS.get(r["verdict"], "#4a5568")
                dist = (f"{r['distance']:.3f}" if r["distance"] is not None
                        else "—")
                st.markdown(
                    f"<div style='display:flex;align-items:center;"
                    f"gap:12px;padding:3px 0;font-size:0.9em;'>"
                    f"<span style='width:72px;'>{r['schema']}</span>"
                    f"<span style='width:88px;'>英 {r['en_size']} 条</span>"
                    f"<span style='width:88px;'>汉 {r['zh_size']} 条</span>"
                    f"<span style='width:56px;'>{dist}</span>"
                    + _badge(r["verdict"], color) + "</div>",
                    unsafe_allow_html=True)
    except ImportError:
        st.dataframe(pd.DataFrame([{
            "图式": r["schema"], "英语": r["en_size"], "汉语": r["zh_size"],
            "距离": r["distance"], "判定": r["verdict"],
        } for r in rows]), use_container_width=True, hide_index=True)

    st.caption(
        "图式由 P/M/C 编码推导：追逐标注 → 互动位移；P1=1 → 源点脱离；"
        "P2/P3=1 → 终点抵达；其余 → 方式伴随。距离 = 两侧图式中心（15 列聚类"
        "特征均值，/2 归一）的平均绝对差；一侧为空 = 该图式未在对方语言词汇化。"
    )

    # ---- 逐图式成员清单 ----
    for r in rows:
        if not (r["en_members"] or r["zh_members"]):
            continue
        color = VERDICT_COLORS.get(r["verdict"], "#4a5568")
        dist_txt = (f"（d={r['distance']:.3f}）" if r["distance"] is not None
                    else "")
        st.markdown(
            f"**{r['schema']}图式** "
            + _badge(f"英 {r['en_size']} 条", "#2b6cb0")
            + _badge(f"汉 {r['zh_size']} 条", "#c05621")
            + _badge(r["verdict"], color) + dist_txt,
            unsafe_allow_html=True)
        en_txt = "、".join(
            f"{m['lemma']}·{m['sense_label']}" for m in r["en_members"]) or "—"
        zh_txt = "、".join(
            f"{m['lemma']}"
            + (f"·{m['sense_no']}" if m["sense_no"] and m["sense_no"] != "—"
               else "")
            + f"·{m['sense_label']}" for m in r["zh_members"]) or "—"
        c1, c2 = st.columns(2)
        c1.caption(f"🇬🇧 {en_txt}")
        c2.caption(f"🇨🇳 {zh_txt}")


def _render_radar_overlay(data: Dict[str, Any]) -> None:
    """完全对齐簇对的特征画像雷达叠加（英簇 vs 汉簇）。"""
    pairs = [a for a in data["alignments"] if a["verdict"] == "完全对齐"]
    if not pairs:
        return
    try:
        import plotly.graph_objects as go
        from src.category_study import FEATURE_COLUMNS as FC
        for a in pairs:
            en_cl = next((c for c in data["en_clusters"]
                          if c["cluster_no"] == a["en_cluster_no"]), None)
            zh_cl = next((c for c in data["zh_clusters"]
                          if c["cluster_no"] == a["zh_cluster_no"]), None)
            if not (en_cl and zh_cl):
                continue
            fig = go.Figure()
            for cl, name, color in ((en_cl, "英语簇", "#2b6cb0"),
                                    (zh_cl, "汉语簇", "#ed8936")):
                profile = cl.get("profile") or {}
                codes = [f["code"] for f in FC
                         if f["code"] in profile] or list(profile.keys())
                values = [profile.get(c, 0) for c in codes]
                fig.add_trace(go.Scatterpolar(
                    r=values + values[:1],
                    theta=codes + codes[:1],
                    fill="toself", opacity=0.35,
                    line=dict(color=color),
                    name=f"{name}{cl['cluster_no']}",
                ))
            fig.update_layout(
                polar=dict(radialaxis=dict(range=[0, 2])),
                title=f"簇画像叠加：英簇{a['en_cluster_no']} vs 汉簇{a['zh_cluster_no']}",
                height=420,
            )
            st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        pass


# ============================================
# 视图4：范畴总览与甄别清单
# ============================================

def render_overview_view(data: Dict[str, Any]) -> None:
    """范畴总览：统计卡 + 甄别口径 + 英汉双清单对照。"""
    stats = data["stats"]
    en, zh = stats["en"], stats["zh"]

    c = st.columns(4)
    c[0].metric("英语词目", en["n_lexemes"])
    c[1].metric("英语目标义位", en["n_senses"])
    c[2].metric("汉语词条", zh["n_lexemes"])
    c[3].metric("汉语义位条目", zh["n_senses"])

    # 汉语判定漏斗
    zh_status = zh.get("status", {})
    verdicts = stats.get("verdicts") or {}
    verdict_summary = "，".join(
        f"{v}{n}" for v, n in sorted(verdicts.items(),
                                     key=lambda kv: VERDICT_ORDER.index(kv[0])
                                     if kv[0] in VERDICT_ORDER else 99))
    c2 = st.columns(4)
    c2[0].metric("保留", zh_status.get("保留", 0))
    c2[1].metric("边缘", zh_status.get("边缘", 0))
    c2[2].metric("剔除", zh_status.get("剔除", 0))
    c2[3].metric("对齐判定", verdict_summary or "—")

    if data["category"].get("notes"):
        st.info(data["category"]["notes"])

    # ---- 英汉双清单对照 ----
    tab_en, tab_zh = st.tabs(["英语目标义位清单", "汉语义位清单"])
    with tab_en:
        rows = [{
            "词目": s["lemma"], "义项号": s["sense_no"],
            "义位标签": s["sense_label"],
            "释义": (s.get("definition") or "")[:120],
            "例句": (s.get("example") or "")[:100],
            "主体": s.get("subject_type") or "",
            "语体": s.get("register") or "",
            "标注": s.get("tag") or "",
            "簇": s["cluster"]["cluster_no"] if s.get("cluster") else "—",
        } for s in data["senses"] if s["language"] == "en"]
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
        st.caption("证据链：OALD10 释义+例句；Word Sketch 语料佐证待补"
                   "（enTenTen21 已有检索结果）。")
    with tab_zh:
        rows = [{
            "词条": s["lemma"], "义项号": s["sense_no"],
            "义位标签": s["sense_label"],
            "释义": (s.get("definition") or "")[:100],
            "判定": s["status"],
            "主体": s.get("subject_type") or "",
            "语体": s.get("register") or "",
            "标注": s.get("tag") or "",
            "簇": s["cluster"]["cluster_no"] if s.get("cluster") else "—",
            "备注": (s.get("remark") or "")[:80],
        } for s in data["senses"] if s["language"] == "zh"]
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
        st.caption("证据链：《现汉7》释义+例句；《现代汉语规范词典》对查与 "
                   "BCC 语料核查待补。◇号隐喻例不计入判定。")


# ============================================
# 页面入口
# ============================================

def render_category_study_page() -> None:
    """🏃‍♀️ 范畴深挖页面：范畴选择 + 四视图 tab。"""
    st.markdown(f"<h1 style='{HEADER_H1}'>🏃‍♀️ 范畴深挖</h1>",
                unsafe_allow_html=True)

    if not category_study_ready():
        st.info(
            "范畴深挖数据尚未灌入。运行 "
            "`MYSQL_HOST=127.0.0.1 python3 scripts/load_category_study.py` "
            "从 data/d1/ 跑范畴两个 xlsx 加载。"
        )
        return

    categories = get_categories()
    if not categories:
        st.warning("categories 为空。")
        return
    if len(categories) == 1:
        code = categories[0]["code"]
        cat = categories[0]
    else:
        code = st.selectbox(
            "范畴", options=[c["code"] for c in categories],
            format_func=lambda c: f"{next(x['name_cn'] for x in categories if x['code'] == c)}"
            f"（{c}）", key="cs_category")
        cat = next(c for c in categories if c["code"] == code)

    data = _load_category(code)
    if data is None:
        st.warning(f"范畴 {code} 数据加载失败。")
        return

    st.caption(
        f"范畴：{cat['name_cn']}（{cat['name_en']}）· 状态：{cat['status']} · "
        f"英语 {cat['en_lexemes']} 词 {cat['en_senses']} 义位 / "
        f"汉语 {cat['zh_lexemes']} 词条 {cat['zh_senses']} 义位条目"
    )

    view = st.radio(
        "视图", options=VIEWS, format_func=lambda v: VIEW_LABELS[v],
        key="cs_view", horizontal=True,
    )
    st.divider()

    if view == "cluster":
        render_cluster_compare_view(data)
    elif view == "matrix":
        render_matrix_view(data)
    elif view == "align":
        render_alignment_view(data)
    else:
        render_overview_view(data)
