import sys
import os
# 确保项目根目录在 sys.path 中，使 from src.xxx 导入正常工作
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import json
import datetime
import logging

logger = logging.getLogger(__name__)

# Backend integration imports
from src.mysql_db import (
    init_database, get_stats, get_hot_verbs, get_feedback_data,
    insert_feedback, get_definition_by_verb, insert_definition,
    log_usage, get_synonyms, get_cluster_graph, get_cluster_graph_by_id, list_clusters,
    get_full_word_graph, get_senses,
)
from src.cluster_graph import render_cluster_graph_svg
from src.graph_export import ensure_graph_html
from typing import Optional, Dict, List, Any
from src.llm_api import get_definition, get_fallback_definition
from src.security import InputValidator

# ============================================
# 设计系统导入
# ============================================
from src.design_system import (
    HEADER_H1, HEADER_H2, HEADER_H3,
    BODY_BASE,
    SUCCESS_COLOR,
    BACKGROUND_COLOR,
    SPACE_SM, SPACE_LG,
    get_card_style,
    get_section_spacing, get_badge_style, hex_to_rgba
)

# ============================================
# 页面配置
# ============================================
st.set_page_config(
    page_title="Verb Definition Optimizer - 运动事件类型学与词典释义优化",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# Session State 初始化
# ============================================
# 卡片展开/折叠状态管理
if 'card_expanded' not in st.session_state:
    st.session_state.card_expanded = {
        'prototype': True,
        'anchor': True,
        'core': True,
        'example': True
    }

# 侧边栏折叠状态标志（D-02，与 initial_sidebar_state="expanded" 一致，默认展开）
if 'sidebar_collapsed' not in st.session_state:
    st.session_state.sidebar_collapsed = False

# ============================================
# 数据库初始化（连接失败时降级为无数据库模式）
# ============================================
DB_AVAILABLE = False
try:
    # Initialize MySQL database
    if init_database():
        DB_AVAILABLE = True
        st.success("✅ 数据库连接成功")
    else:
        st.warning("⚠️ MySQL 数据库不可用，使用离线模式")
except Exception as e:
    st.warning(f"⚠️ 数据库初始化失败，使用离线模式：{e}")

# ============================================
# Sticky 搜索栏：Google 风格样式
# ============================================
# 实现说明（2026-09-15 修复）：
#   1. Streamlit 会把每个 st.markdown 渲染成独立的兄弟节点，所以
#      "<div class=...>" 无法包住后面的 st.text_input —— 以前的写法里输入框
#      始终在容器之外，CSS 从未生效。
#   2. 现在改用 st.container(key="search_bar")：Streamlit 会为容器生成稳定的
#      .st-key-search_bar class，输入框真正位于该容器内部。
#   3. sticky 必须落在 wrapper（[data-testid="stLayoutWrapper"]）上而不是容器
#      本身：容器的高度等于自身内容，没有滚动行程；wrapper 的父级
#      stVerticalBlock 才是整页高度，sticky 才能一路吸顶。
#   4. 外观（背景/内边距/圆角/边框）只放在容器上，wrapper 只负责定位，
#      否则两层各加一次内边距，搜索栏会明显变高。
#   5. 背景色通过 hex_to_rgba 转换：CSS 不接受 rgba() 里写十六进制，
#      rgba(#ffffff, 0.98) 是非法值，浏览器会整条丢弃。
#   6. 吸顶偏移必须让开 Streamlit 顶栏：stHeader 是常驻的 absolute 元素
#      （高度 60px、z-index 999990，内含 Deploy 与菜单按钮）。用 top:1rem(16px)
#      会让搜索栏有 44px 压在顶栏下面、输入框完全不可点。这里用 4.5rem
#      （72px = 60px 顶栏 + 12px 间隙）让搜索栏停在顶栏下方。
#      不要改成把 z-index 提到顶栏之上——那会反过来盖住 Deploy 按钮。
STICKY_SEARCH_BAR_TOP = "4.5rem"
st.markdown(f"""
<style>
/* 外观：容器本身（不支持 :has() 的浏览器也能看到样式，只是不吸顶） */
.st-key-search_bar {{
    background: {hex_to_rgba(BACKGROUND_COLOR, 0.98)};
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    padding: {SPACE_SM}px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1), 0 1px 3px rgba(0, 0, 0, 0.08);
    border: 1px solid rgba(226, 232, 240, 0.5);
}}

/* 定位：容器的 wrapper 一直贴在 Streamlit 顶栏下方，方便随时切换搜索的单词 */
[data-testid="stLayoutWrapper"]:has(> .st-key-search_bar) {{
    position: sticky;
    top: {STICKY_SEARCH_BAR_TOP};
    z-index: 1000;
    margin-bottom: {SPACE_LG}px;
}}
</style>
""", unsafe_allow_html=True)

# ============================================
# 卡片头样式：把折叠按钮做成渐变标题条
# ============================================
# render_card_header 用真实的 st.button 实现折叠（可点、有状态），
# 这里把它还原成旧版视觉：全宽、渐变背景、白字。
# 按钮 label 形如 "🧬|原型与位移事件分析|▼"，本样式只做外观，不改行为。
st.markdown("""
<style>
[class*="st-key-card_toggle_"] button {
    width: 100%;
    justify-content: flex-start;
    padding: 16px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #ffffff;
    border: none;
    border-radius: 8px 8px 0 0;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}
[class*="st-key-card_toggle_"] button:hover {
    background: linear-gradient(135deg, #5a6fd8 0%, #6a4194 100%);
    color: #ffffff;
    border: none;
}
[class*="st-key-card_toggle_"] button p {
    font-weight: 600;
    font-size: 1.05em;
    color: #ffffff;
}

/* 卡片正文容器。
   这里用带 key 的容器 + CSS，而不是 st.markdown(get_card_style())：
   后者只是把 CSS **文本**当成 markdown 渲染出来，页面上会出现 5 段
   「background-color: #f7fafc; padding: 24px; ...」的原始文字（实测可见），
   而且那对 <div>/</div> 也没有真的包住任何东西 —— Streamlit 把每次
   st.markdown 渲染成独立兄弟节点，HTML 无法跨调用闭合。
   与搜索栏（.st-key-search_bar）是同一个模式，见文件顶部说明。 */
[class*="st-key-card_body_"] {
    background-color: #f7fafc;
    padding: 0;
    border: 1px solid #e2e8f0;
    border-top: none;
    border-radius: 0 0 8px 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}
</style>
""", unsafe_allow_html=True)

# ============================================
# 核心理论说明
# ============================================
THEORY_DESCRIPTION = """
### 📚 理论背景

**运动事件类型学 (Talmy, 1985)**
运动事件可分为两类：
1. **波浪型 (Wave-like)**: 强调方式
2. **矢量型 (Vector-like)**: 强调路径+方向

**词典释义优化**
传统释义往往以"路径+方向"为核心，而实际使用中更强调**运动方式**和**身体姿态**。
通过显式分解【方式】【路径】【方向】【体相】四个语义要素，可以：
- 更准确地捕捉运动语义
- 提供更丰富的表达层次
- 支持更精细的语义搜索

---

**【方式】** - 运动采用的姿势/手段
**【路径】** - 运动经过的空间轨迹
**【方向】** - 运动朝向的终点/目标
**【体相】** - 运动时身体的姿态/状态
"""

# ============================================
# 搜索函数：带 300ms 防抖延迟
# ============================================
def _record_query(verb: str) -> None:
    """
    记录一次真实查询到 usage_logs 表。

    这是「查询次数」与「热门动词」两个统计口径的唯一数据来源 ——
    修正前 log_usage() 虽然早已实现，但应用从未调用过，导致侧边栏的
    「总查询次数」实为已收录词条数、「热门查询动词」实为 definitions 表
    的物理顺序。现在每次用户提交搜索都记一笔。

    只应在「用户主动提交查询」处调用（搜索框回车 / 点击热门词 / 点击示例词），
    不要放进 get_display_definition() —— 那个函数每次渲染会被四张卡片各调一次，
    放在那里会把一次查询记成多次。

    失败只记日志，绝不影响界面。
    """
    if not DB_AVAILABLE or not verb:
        return
    try:
        log_usage(str(verb)[:100])
    except Exception as e:
        logger.error(f"查询日志写入失败 for '{verb}': {e}")


def search_verb() -> None:
    """on_change 回调：当搜索框值变化时触发搜索。"""
    value = st.session_state.get("搜索动词", "")
    if value and 1 <= len(value) <= 50:
        st.session_state.verb_result = value
        st.session_state.show_result = True
        # 让词簇图谱跟随新查的词，否则会停在用户上次手动选的簇上
        st.session_state.pop("cluster_selector", None)
        _record_query(value)


def select_example_verb(verb: str) -> None:
    """点击示例库 / 热门动词时触发搜索。"""
    st.session_state.verb_result = verb
    st.session_state.show_result = True
    st.session_state["搜索动词"] = verb
    # 同上：换词就让图谱回到该词所在的簇
    st.session_state.pop("cluster_selector", None)
    _record_query(verb)


def filter_hot_verbs(hot_verbs: List[dict], query: str) -> List[dict]:
    """对热门动词列表做前端子串过滤（D-05，确定性、无后端调用）。

    Args:
        hot_verbs: 已加载的热门动词列表（dict 含 'verb' 键）。
        query: 筛选关键字；为空或全空白时返回原列表。

    Returns:
        过滤后的新列表，仅保留 verb 含 query 子串（忽略大小写）的项。
    """
    if not query or not query.strip():
        return hot_verbs
    q = query.lower()
    return [v for v in hot_verbs if v.get("verb", "").lower().__contains__(q)]

# ============================================
# 语义表渲染函数
# ============================================
def render_semantic_table(semantic_data):
    """
    渲染语义分解表，带 emoji 和颜色编码。

    Args:
        semantic_data: 二维列表 [[类型, emoji, 描述], ...]

    Returns:
        HTML 格式的语义表
    """
    if not semantic_data:
        return "<p style='color: #a0aec0;'>暂无语义分解数据</p>"

    html = '<table style="border-collapse: collapse; width: 100%; margin: 16px 0;">'

    # 表头
    html += '<thead style="background-color: #4a5568; color: white; font-weight: 600;">'
    html += '<tr>'
    html += '<th style="padding: 12px; text-align: left; border-bottom: 2px solid #e2e8f0; width: 25%;">类型</th>'
    html += '<th style="padding: 12px; text-align: left; border-bottom: 2px solid #e2e8f0; width: 20%;">标识</th>'
    html += '<th style="padding: 12px; text-align: left; border-bottom: 2px solid #e2e8f0; width: 55%;">描述</th>'
    html += '</tr></thead><tbody>'

    # 表格行
    for i, row in enumerate(semantic_data):
        semantic_type, emoji, description = row
        color = SEMANTIC_COLORS.get(semantic_type, {}).get("color", "#4a5568")

        # 奇偶行背景色
        bg_color = "#f7fafc" if i % 2 == 0 else "#ffffff"

        html += f'''
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 12px; color: {color}; font-weight: 500;">{semantic_type}</td>
            <td style="padding: 12px; font-size: 1.2em;">{emoji}</td>
            <td style="padding: 12px; color: #2d3748;">{description}</td>
        </tr>'''

    html += '</tbody></table>'
    return html

# ============================================
# 卡片渲染函数
# ============================================
def _toggle_card(card_key: str) -> None:
    """切换某张卡片的展开/折叠状态（供卡片头按钮的 on_click 调用）。"""
    st.session_state.card_expanded[card_key] = not st.session_state.card_expanded.get(card_key, True)


def render_card_header(card_key: str, title: str, icon: str) -> None:
    """
    渲染卡片头部（可点击的展开/折叠按钮）。

    修正历史缺陷：旧实现用 st.markdown 输出一段带 `cursor: pointer` 和 ▼/▶ 箭头的
    HTML，看起来能点，但既没有事件处理器、`card_expanded` 也从未被写入过 ——
    点击毫无反应。现在改用真正的 st.button，通过 on_click 回调写入
    session_state.card_expanded[card_key]，折叠/展开才真的生效。

    外观（渐变背景、圆角、箭头左右对齐）由文件顶部的 CSS 通过
    `[class*="st-key-card_toggle_"]` 前缀选择器还原，视觉与旧版一致。

    Args:
        card_key: card_expanded 中的键（prototype / anchor / core / example）
        title: 卡片标题
        icon: 图标
    """
    expanded = st.session_state.card_expanded.get(card_key, True)
    arrow = "▼" if expanded else "▶"
    st.button(
        f"{icon}|{title}|{arrow}",
        key=f"card_toggle_{card_key}",
        use_container_width=True,
        on_click=_toggle_card,
        args=(card_key,),
    )

def render_card_prototype(verb):
    """
    渲染原型与位移事件分析卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    semantic_table = get_semantic_table_for_verb(verb)

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #667eea; font-weight: 600; margin: 0 0 16px 0;">🧬 原型与位移事件分析</h4>
    '''

    if semantic_table:
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>动词:</strong> ' + verb + '</p>'
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>事件类型:</strong> 基于运动事件类型学的位移事件分析</p>'
        html += '<p style="color: #2d3748;"><strong>语义要素分解:</strong></p>'
        html += render_semantic_table(semantic_table)
    else:
        html += '<p style="color: #718096;">暂无详细的位移事件分析数据</p>'

    html += '</div>'
    return html

def render_card_annotation(verb):
    """
    渲染「义位标注」卡片。

    字段与取值全部来自 `docs/义项判定标准.docx`：

      * 原型层级 —— Y 原型物理位移义 / 拓展 隐喻引申义 / N 剔除
      * 意象图式 —— 源点脱离 / 终点抵达 / 方式伴随 / 互动位移（四类，不可自增）
      * 英汉对齐 —— 完全对齐 / 部分对齐 / 零对齐
      * 汉语句法特征、译义转化策略 —— 配套字段

    卡片刻意把「来源」与「待复核」放在最显眼处：文档要求所有判定可回溯到 OALD 原文，
    而 dictionary.db 只覆盖了少数词，所以必须让使用者一眼看出这条是词典原文还是
    二手拼装、是已定稿还是候选值。
    """
    definition = get_definition_by_verb(verb) if DB_AVAILABLE else None
    senses = get_senses(verb) if DB_AVAILABLE else []

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #9f7aea; font-weight: 600; margin: 0 0 16px 0;">🏷️ 义位标注</h4>
    '''

    if not definition:
        return html + '<p style="color: #718096;">暂无标注数据（数据库不可用或该词未收录）</p></div>'

    def field(label, value, color="#2d3748"):
        if not value:
            return ""
        return (f'<p style="color: #2d3748; margin-bottom: 8px;">'
                f'<strong>{label}：</strong><span style="color: {color};">{value}</span></p>')

    html += field("词目主导义", definition.get("sense_brief"))
    html += field("Levin 来源子类", definition.get("levin_source"))
    html += field("原型层级", definition.get("prototype_level"), "#805ad5")
    html += field("意象图式", definition.get("image_schema"), "#3182ce")
    html += field("英汉对齐等级", definition.get("alignment"), "#dd6b20")
    html += field("汉语句法特征", definition.get("cn_syntax"))
    html += field("译义转化策略", definition.get("translation_strategy"))
    html += field("判定依据", definition.get("judge_reason"))

    # 来源与复核状态 —— 文档要求可回溯，这两项必须显式呈现
    source = definition.get("definition_source") or "未知"
    rank = definition.get("source_rank")
    source_label = {
        "dictionary.db": "词典原文（OALD，可回溯）",
        "legacy-library": "既有词库（二手转写，非词典原文）",
        "levin-brief": "研究者标注的原型义（短语，非完整释义）",
        "oxford-en": "仅英文释义，中文待补",
        "pending": "暂无释义",
    }.get(source, source)
    badge_color = "#38a169" if rank == 1 else ("#dd6b20" if rank and rank <= 2 else "#e53e3e")
    html += (f'<p style="color: #2d3748; margin-bottom: 8px;"><strong>释义来源：</strong>'
             f'<span style="background-color: {badge_color}; color: white; padding: 2px 10px; '
             f'border-radius: 10px; font-size: 0.85em;">{source_label}</span></p>')

    if definition.get("needs_review"):
        html += ('<p style="color: #975a16; background-color: #fefcbf; padding: 8px 12px; '
                 'border-radius: 6px; font-size: 0.9em; margin-top: 12px;">'
                 '⚠️ 标注为规则推导的<b>候选值</b>，依《义项判定标准》需人工复核确认。</p>')

    # 义位明细表
    if senses:
        html += ('<p style="color: #2d3748; margin: 16px 0 8px 0;"><strong>义位明细（'
                 + str(len(senses)) + ' 条，分析单元为义位而非词目）:</strong></p>')
        html += '<table style="border-collapse: collapse; width: 100%; font-size: 0.9em;">'
        html += ('<thead style="background-color: #4a5568; color: white;">'
                 '<tr><th style="padding: 8px; text-align: left; width: 40px;">#</th>'
                 '<th style="padding: 8px; text-align: left; width: 70px;">层级</th>'
                 '<th style="padding: 8px; text-align: left;">释义</th>'
                 '<th style="padding: 8px; text-align: left; width: 90px;">对齐</th></tr></thead><tbody>')
        for i, sense in enumerate(senses):
            bg = "#f7fafc" if i % 2 == 0 else "#ffffff"
            level = sense.get("prototype_level") or "-"
            level_color = "#805ad5" if level == "Y" else "#a0aec0"
            ch = sense.get("ch_ndef") or sense.get("en_ndef") or "（空）"
            html += (f'<tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0;">'
                     f'<td style="padding: 8px;">{sense.get("sense_index", i + 1)}</td>'
                     f'<td style="padding: 8px; color: {level_color}; font-weight: 600;">{level}</td>'
                     f'<td style="padding: 8px;">{ch[:160]}</td>'
                     f'<td style="padding: 8px; color: #718096;">{sense.get("alignment") or "-"}</td></tr>')
        html += '</tbody></table>'

    html += '</div>'
    return html


def render_card_anchor(verb):
    """
    渲染范畴锚定卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    # 数据来源：统一适配器（Phase 5, D-01）；返回 5 行 [[类型, emoji, 描述], ...]
    semantic_table = get_semantic_table_for_verb(verb)

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #48bb78; font-weight: 600; margin: 0 0 16px 0;">🎯 范畴锚定</h4>
    '''

    html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>所属范畴:</strong> 运动方式复合事件</p>'

    if semantic_table:
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>语义特征:</strong></p>'
        html += '<div style="display: flex; flex-wrap: wrap; gap: 8px;">'
        for row in semantic_table:
            semantic_type, emoji, description = row
            color = SEMANTIC_COLORS.get(semantic_type, {}).get("color", "#4a5568")
            html += f'<span style="background-color: {color}; color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.9em;">{emoji} {semantic_type}</span>'
        html += '</div>'
    else:
        html += '<p style="color: #718096;">暂无范畴锚定数据</p>'

    html += '</div>'
    return html

def render_card_core(verb):
    """
    渲染核心释义与多维辨异卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    # 数据来源：统一适配器（Phase 5, D-01）
    display = get_display_definition(verb)
    traditional = display.get("traditional", "")
    optimized = display.get("optimized", "")

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #ed8936; font-weight: 600; margin: 0 0 16px 0;">📚 核心释义与多维辨异</h4>
    '''

    if traditional:
        html += '<div style="background-color: #edf2f7; padding: 12px; border-radius: 8px; margin-bottom: 16px;">'
        html += '<h5 style="color: #2d3748; margin: 0 0 8px 0;">📋 传统释义</h5>'
        html += '<p style="color: #4a5568; margin: 0;">' + traditional + '</p>'
        html += '</div>'

    if optimized:
        html += '<div style="background-color: #c6f6d5; padding: 12px; border-radius: 8px;">'
        html += '<h5 style="color: #22543d; margin: 0 0 8px 0;">✅ 优化释义 (语义分解)</h5>'
        html += '<p style="color: #2f855a; margin: 0;">' + optimized + '</p>'
        html += '</div>'

    html += '</div>'
    return html

def render_card_example(verb):
    """
    渲染图式示例卡片：真实例句 + 近义动词对比。

    修正历史缺陷：旧实现三条要点全是硬编码占位文案，其中一句还写死了
    "与类似动词"跑进来"的区别在于..." —— 无论查询哪个词都显示"跑进来"，
    对 155 词词库里的其它动词是明确错误的。现在改为：
      * 例句取自语料（LLM 生成的 example / 词库的 example_sentence）
      * 近义动词来自词簇（word_relations / definitions.cluster_id）的真实词间关系
      * 数据缺失时如实说明，不再编造占位句

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    display = get_display_definition(verb)
    example = (display.get("example") or "").strip()

    relatives: List[str] = []
    if DB_AVAILABLE:
        try:
            relatives = get_synonyms(verb)[:6]
        except Exception as e:
            logger.error(f"近义词查询失败 for '{verb}': {e}")
            relatives = []

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #9f7aea; font-weight: 600; margin: 0 0 16px 0;">🖼️ 图式示例</h4>
    '''

    if example:
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>例句:</strong></p>'
        html += (f'<div style="background-color: #faf5ff; padding: 12px; border-radius: 8px; '
                 f'margin-bottom: 16px; color: #4a5568; line-height: 1.8;">{example}</div>')
    else:
        html += ('<p style="color: #718096; margin-bottom: 16px;">'
                 '该动词暂无例句数据（可用管理员录入或等待大模型生成）</p>')

    if relatives:
        html += '<p style="color: #2d3748; margin-bottom: 8px;"><strong>近义动词（同语义范畴）:</strong></p>'
        html += '<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px;">'
        for rel in relatives:
            html += (f'<span style="background-color: #9f7aea; color: white; padding: 4px 12px; '
                     f'border-radius: 12px; font-size: 0.9em;">{rel}</span>')
        html += '</div>'
        html += ('<p style="color: #718096; font-size: 0.9em;">'
                 '这些动词同属一个次语义范畴，可点击示例库或在搜索框输入词名逐一对比差异。</p>')
    else:
        html += ('<p style="color: #718096;">尚无近义动词数据。'
                 '运行 <code>python scripts/load_word_library.py</code> 可载入 155 词词库及其词间关系。</p>')

    html += '</div>'
    return html

# ============================================
# 词簇关系图谱（graphify 风格的词与词关系可视化）
# ============================================
def render_cluster_graph_section(verb: str) -> None:
    """
    渲染「当前查询词 + 其所属词簇」的完全图，并支持切换到任意其它簇。

    这是词与词关系在**页面上的接口**。之前它只存在于命令行（graphify query /
    explain）和文件产物（data/word_graph.json），页面上看不到任何一张图。

    三条进入路径：
      1. 默认 —— 跟随当前查询词，画它所在的簇；
      2. 「切换词簇」下拉框 —— 直接打开任意一个簇（25 个），不必先搜一个别的词；
      3. 展开簇内成员列表 —— 点任一词即切换查询，图谱随之前进到它的簇。

    Args:
        verb: 当前查询的动词
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>🕸️ 词与词关系图谱</h3>", unsafe_allow_html=True)

    if not DB_AVAILABLE:
        st.info("数据库不可用，无法展示词簇图谱（离线模式下仅提供释义）。")
        return

    # --- 簇选择器 ---
    # key="cluster_selector" 由 Streamlit 管理；search_verb / select_example_verb
    # 会在换词时 pop 掉它，从而回到「跟随当前词」的默认行为。
    try:
        clusters = list_clusters()
    except Exception as e:
        logger.error(f"读取词簇列表失败: {e}")
        clusters = []

    follow_label = f"跟随当前词「{verb}」"
    if clusters:
        options = [follow_label] + [
            f"{c['label']}（{c['size']} 词 / {c['edge_count']} 边）" for c in clusters
        ]
        label_to_id = {
            f"{c['label']}（{c['size']} 词 / {c['edge_count']} 边）": c["id"]
            for c in clusters
        }

        picked = st.selectbox(
            "切换词簇",
            options=options,
            index=0,
            key="cluster_selector",
            help="默认跟随当前查询词所在的簇；也可以直接选任意一个簇来浏览其完全图。",
        )

        if picked != follow_label:
            cluster_id = label_to_id.get(picked)
            try:
                graph = get_cluster_graph_by_id(cluster_id)
            except Exception as e:
                logger.error(f"按簇 id 取图失败 ({cluster_id}): {e}")
                graph = None
        else:
            graph = get_cluster_graph(verb)
    else:
        graph = get_cluster_graph(verb)

    if not graph or not graph.get("nodes"):
        st.info(
            f"「{verb}」暂无词簇数据。词簇来自词库的次语义范畴划分；"
            "运行 `python scripts/load_word_library.py` 可载入 155 词词库及其词间关系。"
        )
        return

    cluster = graph.get("cluster") or {}
    size = cluster.get("size", len(graph["nodes"]))
    edges = graph.get("complete_edge_count", 0)
    center = graph.get("center") or verb

    # 用户是「查到某个词」进来的，还是自己选了别的簇 —— 文案要区分开，
    # 否则在别的簇里看到「」属于该词簇」会让人以为查错了词。
    if center == verb:
        intro = (
            f"「<strong>{verb}</strong>」属于词簇 "
            f"<strong>{cluster.get('label', '未分组')}</strong>"
        )
    else:
        intro = (
            f"正在浏览词簇 <strong>{cluster.get('label', '未分组')}</strong>"
            f"（当前高亮 <strong>{center}</strong>，非本次查询词「{verb}」）"
        )

    st.markdown(
        f"<p style='{BODY_BASE}'>{intro} —— 簇内 {size} 个动词语义相近，"
        f"两两互为近义（完全图，共 {edges} 条边）。</p>",
        unsafe_allow_html=True,
    )

    # --- 视图控制 ---
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        mode = st.radio(
            "图谱视图",
            options=["完整簇完全图", "只显示中心词连线"],
            index=0,
            horizontal=True,
            key="cluster_graph_mode",
            help="完整簇显示簇内所有词两两相连；只显示中心词连线则突出当前词与谁相关。",
        )
    with c2:
        st.metric("簇大小", size)
    with c3:
        st.metric("完全图边数", edges)

    highlight_only = mode == "只显示中心词连线"

    if size > 18:
        st.caption(
            f"该簇有 {size} 个词、{edges} 条边（= C({size},2)），全部标名会互相压盖；"
            "当前只标注中心词，其余节点可用鼠标悬停查看词名。"
            f"{'（已切换为只显示中心词连线）' if highlight_only else ''}"
        )

    svg = render_cluster_graph_svg(graph, highlight_only_center=highlight_only)
    st.markdown(f"<div style='margin:8px 0;'>{svg}</div>", unsafe_allow_html=True)

    with st.expander(f"查看簇内全部 {size} 个动词（点击可直接查询）", expanded=size <= 12):
        members = [n["id"] for n in graph["nodes"]]
        # 按每行 6 个铺按钮，点击即切换查询词
        per_row = 6
        for i in range(0, len(members), per_row):
            row = members[i:i + per_row]
            cols = st.columns(per_row)
            for col, member in zip(cols, row):
                with col:
                    label = f"📍 {member}" if member == center else member
                    st.button(
                        label,
                        key=f"cluster_member_{member}",
                        use_container_width=True,
                        on_click=select_example_verb,
                        args=(member,),
                    )


# ============================================
# 示例库渲染函数
# ============================================
def render_example_library():
    """
    渲染示例库组件，带分类标签页。

    使用 Streamlit tabs 和 buttons 创建交互式示例库。
    点击动词按钮会调用 search_verb 函数触发搜索。
    """
    st.markdown("<h3 style='color: #2d3748; font-weight: 600; margin: 0 0 16px 0;'>📚 示例库</h3>", unsafe_allow_html=True)

    # 创建标签页
    tab1, tab2, tab3 = st.tabs([
        "🏃 " + CATEGORY_MODE,
        "🛤️ " + CATEGORY_PATH,
        "💪 " + CATEGORY_MANNER
    ])

    with tab1:
        for verb in EXAMPLE_VERBS.get(CATEGORY_MODE, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=select_example_verb,
                args=(verb,)
            )

    with tab2:
        for verb in EXAMPLE_VERBS.get(CATEGORY_PATH, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=select_example_verb,
                args=(verb,)
            )

    with tab3:
        for verb in EXAMPLE_VERBS.get(CATEGORY_MANNER, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=select_example_verb,
                args=(verb,)
            )

# ============================================
# LLM API Integration
# ============================================
def get_verb_definition(verb: str) -> Optional[Dict[str, Any]]:
    """
    Get verb definition from LLM API with caching.

    Args:
        verb: The verb to define

    Returns:
        Dictionary containing definition data or None if failed
    """
    if not verb or not verb.strip():
        return None

    # Check cache first
    result = get_definition(verb, force_refresh=False)
    if result:
        return result

    # If cache not available or failed, try without cache
    result = get_definition(verb, force_refresh=True)
    return result


# ============================================
# Unified Display Adapter (Phase 5 tracer: D-01/D-02/D-05/D-06/D-07)
# ============================================
# Module-level key names for the combined chinese_ndef JSON stored in MySQL.
TRAD_OPT_KEYS = ("traditional", "optimized")


def _normalize_mock_semantic_table(mock_list) -> Dict[str, str]:
    """
    Convert MOCK_DEFINITIONS' list-of-lists semantic_table into the
    five-key dict (manner/path/direction/aspect/scope) expected downstream.

    Args:
        mock_list: List of [type, emoji, desc] rows from MOCK_DEFINITIONS.

    Returns:
        Dict mapping the five semantic keys to their descriptions.
    """
    key_map = {
        "方式": "manner",
        "路径": "path",
        "方向": "direction",
        "体相": "aspect",
        "范围": "scope",
    }
    result = {k: "待生成" for k in key_map.values()}
    if not mock_list:
        return result
    for row in mock_list:
        if not row:
            continue
        label = row[0]
        desc = row[2] if len(row) > 2 else (row[1] if len(row) > 1 else "")
        if label in key_map:
            result[key_map[label]] = desc
    return result


def _restore_trad_opt(chinese_ndef: str):
    """
    Restore (traditional, optimized) from the stored chinese_ndef string.

    The definitions table has no separate columns; Phase 5 (D-03) persists a
    JSON object {"traditional": t, "optimized": o} inside chinese_ndef.
    Legacy rows store a plain string and are treated as traditional only.

    Returns:
        (traditional, optimized) tuple of strings.
    """
    if not chinese_ndef:
        return "", ""
    try:
        parsed = json.loads(chinese_ndef)
        if isinstance(parsed, dict) and "traditional" in parsed and "optimized" in parsed:
            return parsed.get("traditional", "") or "", parsed.get("optimized", "") or ""
    except (json.JSONDecodeError, TypeError):
        pass
    # Legacy plain-text storage
    return chinese_ndef, ""


def get_display_definition(verb: str) -> Dict[str, Any]:
    """
    Single source of truth for verb definitions (Phase 5 tracer).

    Resolution priority (D-02): DB hit → live LLM → MOCK_DEFINITIONS → fallback.

    Args:
        verb: The verb to define.

    Returns:
        Normalized dict {traditional, optimized, semantic_table, example}.
        Never raises; on total failure returns the absolute fallback shape.
    """
    # (0) Entry validation (T-05-01 mitigation): reject malformed verb, never
    #     feed it into the LLM prompt, and bypass straight to the fallback.
    ok, err = InputValidator.validate_string(verb, max_length=50)
    if not ok:
        logger.warning(f"非法 verb 输入被拒绝: {str(verb)[:50]}")
        fb = get_fallback_definition(verb)
        return {
            "traditional": fb.get("chinese_ndef", ""),
            "optimized": fb.get("chinese_ndef", ""),
            "semantic_table": fb.get("semantic_table", {}),
            "example": fb.get("example", ""),
        }

    # (1) DB first (D-02, LLM-02). Persisted rows take precedence over MOCK.
    try:
        row = get_definition_by_verb(verb)
    except Exception as e:
        logger.error(f"DB lookup failed for '{verb}': {e}")
        row = None

    if row:
        trad, opt = _restore_trad_opt(row.get("chinese_ndef", ""))
        semantic_table = row.get("semantic_table") or {}
        if isinstance(semantic_table, str):
            try:
                semantic_table = json.loads(semantic_table)
            except (json.JSONDecodeError, TypeError):
                semantic_table = {}
        return {
            "traditional": trad,
            "optimized": opt,
            "semantic_table": semantic_table,
            "example": row.get("example_sentence") or "",
        }

    # (2) Live LLM generation, wrapped in a spinner (D-07: spinner only here).
    result = None
    try:
        with st.spinner("正在调用大模型生成释义..."):
            result = get_definition(verb)
    except Exception as e:
        # (4) LLM failure / exception (D-06): log, warn once, fall through.
        logger.error(f"实时 LLM 生成失败 for '{verb}': {e}")
        st.warning("实时生成暂不可用，已显示离线释义")

    if result and result.get("semantic_table"):
        normalized = {
            "traditional": result.get("traditional") or result.get("chinese_ndef", ""),
            "optimized": result.get("optimized", ""),
            "semantic_table": result.get("semantic_table", {}),
            "example": result.get("example", ""),
        }
        # (3) Persist LLM result to DB so subsequent queries hit DB (LLM-03).
        try:
            mysql_db_persist(verb, normalized)
        except Exception as e:
            logger.error(f"持久化失败 for '{verb}': {e}")
        return normalized

    # (5) MOCK fallback (D-02): only after LLM fails.
    if verb in MOCK_DEFINITIONS:
        mock = MOCK_DEFINITIONS[verb]
        return {
            "traditional": mock.get("traditional", ""),
            "optimized": mock.get("optimized", ""),
            "semantic_table": _normalize_mock_semantic_table(mock.get("semantic_table", [])),
            "example": "",
        }

    # (6) Absolute last resort.
    fb = get_fallback_definition(verb)
    return {
        "traditional": fb.get("chinese_ndef", ""),
        "optimized": fb.get("chinese_ndef", ""),
        "semantic_table": fb.get("semantic_table", {}),
        "example": fb.get("example", ""),
    }


def mysql_db_persist(verb: str, normalized: Dict[str, Any]) -> bool:
    """
    Persist a normalized definition to MySQL (LLM-03).

    Stores traditional+optimized as a combined JSON inside chinese_ndef so the
    columns need no migration (D-03); semantic_table is stored as JSON, and
    example_sentence carries the example.

    Args:
        verb: The verb.
        normalized: {traditional, optimized, semantic_table, example}.

    Returns:
        bool: True if successful.
    """
    trad = normalized.get("traditional", "") or ""
    opt = normalized.get("optimized", "") or ""
    combined = json.dumps(
        {"traditional": trad, "optimized": opt}, ensure_ascii=False
    )
    return insert_definition(
        verb=verb,
        chinese_ndef=combined,
        semantic_table=normalized.get("semantic_table", {}),
        example_sentence=normalized.get("example", ""),
        model_version="zhipu-glm-4",
    )


def get_semantic_table_for_verb(verb: str) -> List:
    """
    Get semantic table for a verb in the format expected by render_semantic_table.

    Now sourced from the unified adapter get_display_definition (Phase 5 tracer).
    The external signature and return shape are unchanged.

    Args:
        verb: The verb

    Returns:
        List of [type, emoji, description] tuples
    """
    display = get_display_definition(verb)
    semantic_table = display.get("semantic_table") or {}

    if not semantic_table:
        # Return default structure
        return [
            ["方式", "🏃", "待生成"],
            ["路径", "🛤️", "待生成"],
            ["方向", "🎯", "待生成"],
            ["体相", "💪", "待生成"]
        ]

    # Convert semantic table dict to the format expected by render_semantic_table
    return [
        ["方式", "🏃", semantic_table.get("manner", "待生成")],
        ["路径", "🛤️", semantic_table.get("path", "待生成")],
        ["方向", "🎯", semantic_table.get("direction", "待生成")],
        ["体相", "💪", semantic_table.get("aspect", "待生成")],
        ["范围", "🌍", semantic_table.get("scope", "待生成")]
    ]


# ============================================
# Mock Data (Fallback for offline mode)
# ============================================
# 模拟释义数据
MOCK_DEFINITIONS = {
    "跑进来": {
        "semantic_table": [
            ["方式", "🏃", "双脚快速交替蹬地前进"],
            ["路径", "🛤️", "直线穿越边界进入空间"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体前倾，双臂自然摆动"]
        ],
        "traditional": """
**传统释义 (词典)**

> 「跑进来」指人快速移动进入某空间，以跑步的方式进入，强调速度和路径。

**语义要素分析：**
- 方式：跑步（需要双脚交替蹬地）
- 路径：直线进入空间
- 方向：朝向某空间内部
- 体相：身体前倾，双臂自然摆动
""",
        "optimized": """
**优化释义 (语义分解)**

| 语义要素 | 含义 | 体现 |
|---------|------|------|
| 【方式】 | 双脚快速交替蹬地前进 | 跑步姿势，体现速度 |
| 【路径】 | 直线穿越边界进入空间 | 从外部到内部的空间移动 |
| 【方向】 | 朝向空间内部 | 目标明确，进入动作 |
| 【体相】 | 身体前倾，双臂摆动 | 动态姿态，增加生动感 |

**改进点：**
1. **显式分解**：将隐含的语义要素明确化
2. **详细说明**：每个要素都有具体描述
3. **可对比性**：便于理解不同动词的差异
4. **学术支撑**：基于运动事件类型学理论
"""
    },
    "冲进来": {
        "semantic_table": [
            ["方式", "🏃", "急速奔跑，带有强烈冲击力"],
            ["路径", "🛤️", "带有横向移动的直线进入"],
            ["方向", "🎯", "目的明确的快速进入"],
            ["体相", "💪", "身体前倾更明显，肌肉紧绷"]
        ],
        "traditional": """
**传统释义 (词典)**

> 「冲进来」指人快速且有力地进入某空间，通常带有突然性或紧迫感。

**语义要素分析：**
- 方式：快速跑动
- 路径：冲入空间
- 方向：朝向空间内部
- 体相：身体前倾，姿态用力
""",
        "optimized": """
**优化释义 (语义分解)**

| 语义要素 | 含义 | 体现 |
|---------|------|------|
| 【方式】 | 急速奔跑，带有冲击力 | 快速且用力的跑动 |
| 【路径】 | 带有横向移动的直线进入 | 超越跑进来，更显动态 |
| 【方向】 | 带有目的性的快速进入 | 目标明确， urgency 强 |
| 【体相】 | 身体前倾更明显，肌肉紧绷 | 感觉更加紧张/紧迫 |

**改进点：**
1. **增加紧迫感描述**：比"跑进来"更紧迫
2. **体相更详细**：肌肉紧绷体现紧张感
3. **路径有横向移动**：不只是直线
"""
    },
    "走进去": {
        "semantic_table": [
            ["方式", "🚶", "平稳移动，步伐稳定"],
            ["路径", "🛤️", "沿着某轨迹进入空间"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "姿态自然，无明显前倾"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滑进来": {
        "semantic_table": [
            ["方式", "🏃", "身体贴近地面快速滑行"],
            ["路径", "🛤️", "弧形轨迹穿越边界"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体压低，保持平衡"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滚进来": {
        "semantic_table": [
            ["方式", "🏃", "以身体为轴滚动前进"],
            ["路径", "🛤️", "波浪式轨迹移动"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体蜷缩，保持稳定"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "跌进来": {
        "semantic_table": [
            ["方式", "🏃", "失去平衡跌入空间"],
            ["路径", "🛤️", "向下弧形轨迹进入"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体前倾，慌乱姿态"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "窜进来": {
        "semantic_table": [
            ["方式", "🏃", "突然快速窜动进入"],
            ["路径", "🛤️", "曲折但快速进入"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体扭曲，快速动作"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "走进来": {
        "semantic_table": [
            ["方式", "🚶", "平稳行走进入空间"],
            ["路径", "🛤️", "从外部到内部移动"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "姿态端正，步伐稳健"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "冲出去": {
        "semantic_table": [
            ["方式", "🏃", "急速奔跑向外冲出"],
            ["路径", "🛤️", "直线向外穿越边界"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体后仰，用力冲刺"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滚出去": {
        "semantic_table": [
            ["方式", "🏃", "以身体为轴向外滚动"],
            ["路径", "🛤️", "波浪式轨迹向外移动"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体蜷缩，保持稳定"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "跌出去": {
        "semantic_table": [
            ["方式", "🏃", "失去平衡跌出空间"],
            ["路径", "🛤️", "向下弧形轨迹离开"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体前倾，慌乱姿态"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滑出去": {
        "semantic_table": [
            ["方式", "🏃", "身体贴地向外滑行"],
            ["路径", "🛤️", "弧形轨迹穿越边界"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体压低，保持平衡"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "站着": {
        "semantic_table": [
            ["方式", "🚶", "保持身体直立姿态"],
            ["路径", "🛤️", "原地固定，无明显位移"],
            ["方向", "🎯", "朝向水平方向延伸"],
            ["体相", "💪", "双臂自然下垂或摆动"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "躺着": {
        "semantic_table": [
            ["方式", "🚶", "身体平躺于地面"],
            ["路径", "🛤️", "水平移动，贴近地面"],
            ["方向", "🎯", "朝向任意水平方向"],
            ["体相", "💪", "全身放松，四肢伸展"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "坐着": {
        "semantic_table": [
            ["方式", "🚶", "臀部接触平面坐姿"],
            ["路径", "🛤️", "相对于地面垂直方向"],
            ["方向", "🎯", "朝向前方或侧方"],
            ["体相", "💪", "上身挺直，双腿下垂"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "蹲着": {
        "semantic_table": [
            ["方式", "🚶", "屈膝半蹲姿态"],
            ["路径", "🛤️", "身体上下起伏移动"],
            ["方向", "🎯", "朝向原地或前方"],
            ["体相", "💪", "身体前倾，重心降低"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "趴着": {
        "semantic_table": [
            ["方式", "🚶", "腹部贴地匍匐移动"],
            ["路径", "🛤️", "贴近地面曲折前进"],
            ["方向", "🎯", "朝向任意水平方向"],
            ["体相", "💪", "身体平贴地面，手脚交替"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "靠着": {
        "semantic_table": [
            ["方式", "🚶", "身体倚靠固定物移动"],
            ["路径", "🛤️", "沿支撑物表面移动"],
            ["方向", "🎯", "朝向支撑物方向"],
            ["体相", "💪", "背部接触支撑面"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    }
}

# ============================================
# 语义颜色常量
# ============================================
SEMANTIC_COLORS = {
    "方式": {"color": "#4a5568", "emoji": "🏃", "label": "方式"},
    "路径": {"color": "#48bb78", "emoji": "🛤️", "label": "路径"},
    "方向": {"color": "#ed8936", "emoji": "🎯", "label": "方向"},
    "体相": {"color": "#805ad5", "emoji": "💪", "label": "体相"}
}

# ============================================
# 示例库分类
# ============================================
CATEGORY_MODE = "方式聚焦类"
CATEGORY_PATH = "路径聚焦类"
CATEGORY_MANNER = "体相聚焦类"

EXAMPLE_VERBS = {
    CATEGORY_MODE: ["跑进来", "冲进来", "滑进来", "滚进来", "跌进来", "窜进来"],
    CATEGORY_PATH: ["走进去", "走进来", "冲出去", "滚出去", "跌出去", "滑出去"],
    CATEGORY_MANNER: ["站着", "躺着", "坐着", "蹲着", "趴着", "靠着"]
}

# ============================================
# 侧边栏组件
# ============================================
def _empty_stats() -> Dict[str, Any]:
    """数据库不可用时的空统计（键与 mysql_db.get_stats 保持一致）。"""
    return {
        "total_queries": 0,
        "queries_today": 0,
        "total_definitions": 0,
        "avg_rating": 0.0,
        "total_feedbacks": 0,
        "total_clusters": 0,
        "total_relations": 0,
    }


def render_sidebar():
    """渲染侧边栏组件（折叠/展开双分支，D-01）"""
    collapsed = st.session_state.get("sidebar_collapsed", False)

    if collapsed:
        # 折叠分支：窄图标栏（D-01），点击任意图标即展开回完整宽度
        st.sidebar.button("☰", key="expand_sidebar", help="展开侧边栏",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        st.sidebar.button("📊", key="rail_stats", help="统计",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        st.sidebar.button("🔥", key="rail_hot", help="热门查询动词",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        st.sidebar.button("📥", key="rail_export", help="数据导出",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        return

    # 展开分支：完整内容（D-01）
    st.sidebar.button("◀", key="collapse_sidebar", help="折叠侧边栏",
                      on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", True))

    # 页面切换：搜索页 ↔ 交互式知识图谱页
    _page = st.session_state.get("page", "search")
    st.sidebar.radio(
        "页面",
        options=["search", "graph"],
        index=0 if _page != "graph" else 1,
        format_func=lambda v: "🔍 搜索释义" if v == "search" else "🕸️ 知识图谱",
        key="page",
        horizontal=True,
    )
    st.sidebar.divider()

    st.sidebar.markdown(f"<h2 style='{HEADER_H2}'>📊 实验统计</h2>", unsafe_allow_html=True)

    if DB_AVAILABLE:
        try:
            stats = get_stats()
            hot_verbs = get_hot_verbs(limit=5)
        except Exception as e:
            logger.error(f"侧边栏统计读取失败: {e}")
            stats = _empty_stats()
            hot_verbs = []
    else:
        stats = _empty_stats()
        hot_verbs = []

    # 口径说明：total_queries 来自 usage_logs（真实查询次数），
    # total_definitions 是已收录词条数 —— 两者含义不同，分开展示。
    st.sidebar.metric(
        "总查询次数",
        stats["total_queries"],
        delta=f"+{stats['queries_today']} 今天" if stats.get("queries_today") else None,
    )
    st.sidebar.metric("已收录词条", stats.get("total_definitions", 0))
    # 结构指标：词簇数与词间关系边数 —— 直接反映「词与词关系」图谱的规模
    st.sidebar.metric("词义簇", stats.get("total_clusters", 0))
    st.sidebar.metric("词间关系", stats.get("total_relations", 0))
    st.sidebar.metric("平均评分", f"{stats['avg_rating']:.1f}/5.0")
    st.sidebar.metric("总反馈数", stats["total_feedbacks"])

    st.sidebar.divider()

    st.sidebar.markdown(f"<h2 style='{HEADER_H3}'>🔥 热门查询动词</h2>", unsafe_allow_html=True)

    if hot_verbs:
        # 本地前端子串筛选输入框（D-05，无后端往返）
        st.sidebar.text_input("筛选热门动词", key="hot_filter", placeholder="输入关键字筛选…")
        filtered = filter_hot_verbs(hot_verbs, st.session_state.get("hot_filter", ""))
        for v in filtered:
            # 可点击行：复用 select_example_verb 填充搜索框并触发搜索（D-04）
            st.sidebar.button(
                f"{v['verb']} · {v['count']}次 ⭐{v['avg_rating']}",
                key=f"hot_{v['verb']}",
                on_click=select_example_verb,
                args=(v['verb'],),
            )
    else:
        st.sidebar.info("暂无热门查询数据")

    st.sidebar.divider()

    st.sidebar.markdown(f"<h2 style='{HEADER_H3}'>📥 数据导出</h2>", unsafe_allow_html=True)

    if DB_AVAILABLE:
        try:
            feedback_rows = get_feedback_data()
            feedback_df = pd.DataFrame(feedback_rows)
        except Exception:
            feedback_df = pd.DataFrame(columns=["verb", "rating", "feedback_text", "created_at"])
    else:
        feedback_df = pd.DataFrame(columns=["verb", "rating", "feedback_text", "created_at"])

    csv = feedback_df.to_csv(index=False).encode('utf-8-sig')

    st.sidebar.download_button(
        label="导出反馈数据 (CSV)",
        data=csv,
        file_name=f"feedback_data_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
        type="primary",
        use_container_width=True
    )

# ============================================
# 主区域组件
# ============================================
def render_main_area():
    """渲染主区域组件"""
    st.markdown(f"<h1 style='{HEADER_H1}'>🏃 动词释义优化器</h1>", unsafe_allow_html=True)
    st.markdown(THEORY_DESCRIPTION, unsafe_allow_html=True)

    # ===== 浮动固定搜索栏 =====
    # 用 st.container(key="search_bar") 让输入框真正位于 .st-key-search_bar 容器内，
    # 固定的 CSS 挂在容器的 wrapper 上（见文件顶部样式块）。不要再改回
    # st.markdown('<div class=...>') 的写法——那只会生成一个空的兄弟 div，
    # 输入框不在其中，sticky 与背景都不会生效。
    with st.container(key="search_bar"):
        # 搜索输入框 — 使用 key 让 Streamlit 自动管理 session_state
        # 不设置 value（由 key 管理），on_change 在值变化时触发搜索
        st.text_input(
            label="搜索动词",
            placeholder="搜索动词 (例如：跑进来、冲进来、滑进来...)",
            label_visibility="collapsed",
            key="搜索动词",
            on_change=search_verb
        )

    # 欢迎消息（当没有结果时显示）
    if not hasattr(st.session_state, 'show_result') or not st.session_state.show_result:
        st.markdown(get_section_spacing())
        st.markdown(f"""
        <div style='{get_card_style()}'>
            <h2 style='{HEADER_H3}'>🏃 动词释义优化器</h2>
            <p style='{BODY_BASE}'><strong>基于运动事件类型学的中文动词释义优化</strong></p>
            <div style='{get_section_spacing()}'></div>
            <p style='{BODY_BASE}'><strong>核心功能：</strong></p>
            <ul style='{BODY_BASE}; margin-top: 8px; padding-left: 24px; line-height: 1.8;'>
                <li><strong>方式要素分解</strong>：分析运动采用的姿势/手段</li>
                <li><strong>路径要素分解</strong>：解析运动经过的空间轨迹</li>
                <li><strong>方向要素分解</strong>：识别运动朝向的终点/目标</li>
                <li><strong>体相要素分解</strong>：描述运动时身体的姿态/状态</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(get_section_spacing(), unsafe_allow_html=True)

    # 显示结果区域
    if hasattr(st.session_state, 'show_result') and st.session_state.show_result:
        verb = st.session_state.verb_result

        # 显示四张卡片布局
        st.markdown(f"<h2 style='{HEADER_H2}'>结果展示</h2>", unsafe_allow_html=True)

        # 四卡布局：头部是真正可点击的折叠按钮（render_card_header 内部用
        # st.button + on_click 写入 session_state.card_expanded）
        for card_key, title, icon, body_renderer in (
            ("prototype", "原型与位移事件分析", "🧬", render_card_prototype),
            ("anchor", "范畴锚定", "🎯", render_card_anchor),
            ("annotation", "义位标注", "🏷️", render_card_annotation),
            ("core", "核心释义与多维辨异", "📚", render_card_core),
            ("example", "图式示例", "🖼️", render_card_example),
        ):
            render_card_header(card_key, title, icon)
            if st.session_state.card_expanded.get(card_key, True):
                # 正文放进带 key 的容器，外观由 [class*="st-key-card_body_"] 提供
                with st.container(key=f"card_body_{card_key}"):
                    st.markdown(body_renderer(verb), unsafe_allow_html=True)

        # 词簇关系图谱（graphify 风格的词与词关系可视化）
        st.markdown(get_section_spacing(), unsafe_allow_html=True)
        render_cluster_graph_section(verb)

        # 示例库
        st.markdown(get_section_spacing(), unsafe_allow_html=True)
        render_example_library()

        # 用户反馈区域
        st.markdown(get_section_spacing(), unsafe_allow_html=True)

        st.markdown(f"<h3 style='{HEADER_H3}'>💬 反馈与评分</h3>", unsafe_allow_html=True)

        # 评分组件
        st.write("请对优化释义进行评分：")
        rating = st.select_slider(
            label="评分 (1-5分)",
            options=[1, 2, 3, 4, 5],
            value=3,
            format_func=lambda x: f"{'⭐' * x}" if x else "⭐" * x
        )

        # 文字反馈输入
        st.write("您对优化释义有什么建议？")
        feedback_text = st.text_area(
            label="文字反馈",
            placeholder="请输入您的建议或意见...",
            height=100
        )

        # 提交按钮
        # 注：get_button_primary_style() 返回的是 CSS 字符串（不是关键字参数字典），
        # 展开传入 st.button 会在渲染结果区时抛 TypeError。
        submit_button = st.button("📤 提交反馈", type="primary")

        if submit_button:
            if rating > 0 and feedback_text.strip():
                if DB_AVAILABLE:
                    try:
                        insert_feedback(verb, rating, feedback_text.strip())
                        st.success("✅ 反馈已成功提交！感谢您的参与！")
                    except Exception as e:
                        st.error(f"反馈提交失败：{e}")
                else:
                    st.success("✅ 反馈已记录（离线模式，未持久化）！")

                # 更新 session_state 状态
                st.session_state.feedback_submitted = True
                st.session_state.last_feedback = {
                    "verb": verb,
                    "rating": rating,
                    "feedback": feedback_text,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            else:
                st.warning("⚠️ 请先评分并填写反馈内容")

        # 显示提交历史
        if hasattr(st.session_state, 'feedback_submitted') and st.session_state.feedback_submitted:
            st.markdown(get_section_spacing(), unsafe_allow_html=True)

            st.markdown(f"<h3 style='{HEADER_H3}'>📝 反馈历史</h3>", unsafe_allow_html=True)
            if hasattr(st.session_state, 'last_feedback'):
                fb = st.session_state.last_feedback
                badge_style = get_badge_style(SUCCESS_COLOR)
                st.markdown(
                    f"""
                    <div style='{get_card_style()}'>
                        <span style='{badge_style}'>已提交</span>
                        <p style='{BODY_BASE}'><strong>动词:</strong> {fb['verb']}</p>
                        <p style='{BODY_BASE}'><strong>评分:</strong> {'⭐' * fb['rating']} ({fb['rating']}/5)</p>
                        <p style='{BODY_BASE}'><strong>反馈:</strong> {fb['feedback']}</p>
                        <p style='{BODY_BASE}'><strong>时间:</strong> {fb['timestamp']}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )


# ============================================
# 交互式知识图谱页面
# ============================================
def render_interactive_graph_page() -> None:
    """
    全屏交互式词间关系图谱页（graphify 风格的力导向图）。

    与 render_cluster_graph_section 的分工：
      * 区块内的 SVG —— 跟着当前查询词走，几十个节点，一眼看清谁连谁；
      * 本页 —— 全库 155 词 / 2143 边的语义地图，可搜索、可点选、可按簇过滤。

    实现要点：图谱渲染成**静态 HTML 文件**放进 src/static/，用 iframe 引用。
    不用 components.html(html_string) 的原因是 Streamlit 每次交互重跑脚本时，
    内联的 iframe 会被整体重写 —— 力导向布局从头收敛，用户拖好的位置、
    选中的节点、缩放视野全丢。静态文件 + 内容指纹 URL 则只在数据变化时重载。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>🕸️ 词间关系知识图谱</h1>", unsafe_allow_html=True)

    if not DB_AVAILABLE:
        st.info("数据库不可用，无法展示知识图谱（离线模式下仅提供释义）。")
        return

    try:
        graph = get_full_word_graph()
    except Exception as e:
        logger.error(f"读取全库图谱失败: {e}")
        graph = None

    if not graph or not graph.get("nodes"):
        st.info(
            "暂无词间关系数据。运行 `python scripts/load_word_library.py` "
            "可载入 155 词词库及其 2143 条词间关系。"
        )
        return

    stats = graph["stats"]
    c1, c2, c3 = st.columns(3)
    c1.metric("动词节点", stats["node_count"])
    c2.metric("近义关系", stats["edge_count"])
    c3.metric("语义簇", stats["cluster_count"])

    url = ensure_graph_html(graph)
    if not url:
        st.warning("图谱文件生成失败，请检查 `src/static/` 是否可写。")
        return

    st.caption(
        "左侧力导向图可直接缩放拖拽；右侧栏可搜索动词、查看节点邻居、"
        "按语义簇勾选过滤。每个节点的连线数等于它所在词簇的大小减一"
        "（同一簇内两两互为近义，即完全图）。"
    )

    # 直接嵌本地静态文件（不是内联 HTML 字符串）—— 这样 Streamlit 重跑脚本时
    # iframe 的 src 不变，浏览器不会重载，图谱的布局与交互状态得以保留。
    st.iframe(url, height=820)

    st.markdown(f"<h3 style='{HEADER_H3}'>按词簇浏览</h3>", unsafe_allow_html=True)
    st.caption("点击任一词即切换搜索词，并在结果页展示该词所在簇的完全图。")
    clusters = graph.get("clusters", [])
    per_row = 4
    for i in range(0, len(clusters), per_row):
        row = clusters[i:i + per_row]
        cols = st.columns(per_row)
        for col, cluster in zip(cols, row):
            with col:
                st.button(
                    f"{cluster['sub_cat']}（{cluster['size']} 词 / {cluster['edge_count']} 边）",
                    key=f"graph_cluster_{cluster['id']}",
                    use_container_width=True,
                    on_click=_pick_cluster_verb,
                    args=(cluster["id"],),
                )


def _pick_cluster_verb(cluster_id: int) -> None:
    """点击「按词簇浏览」按钮：跳到该簇的第一个词（图谱随之打开该簇）。"""
    try:
        g = get_cluster_graph_by_id(cluster_id)
    except Exception as e:
        logger.error(f"读取词簇 {cluster_id} 失败: {e}")
        return
    nodes = g.get("nodes") or []
    if not nodes:
        return
    verb = g.get("center") or nodes[0]["id"]
    st.session_state.verb_result = verb
    st.session_state.show_result = True
    st.session_state["搜索动词"] = verb
    st.session_state.pop("cluster_selector", None)
    st.session_state["page"] = "search"
    _record_query(verb)


# ============================================
# 主函数
# ============================================
def main():
    """主函数：按 session_state["page"] 分派到搜索页或图谱页。"""
    render_sidebar()
    if st.session_state.get("page") == "graph":
        render_interactive_graph_page()
    else:
        render_main_area()

# ============================================
# 启动应用
# ============================================
if __name__ == "__main__":
    main()

# ============================================
# ⚠️ 未来集成说明
# ============================================
"""
【已实现的数据库集成】
1. MOCK_STATS → 从 MySQL 读取 (get_stats)
2. MOCK_HOT_VERBS → 从 MySQL 统计热门动词 (get_hot_verbs)
3. MOCK_DEFINITIONS → 待替换为大模型 API 调用返回的真实释义
4. MOCK_FEEDBACK_DATA → 已替换为真实用户反馈记录 (get_feedback_data → MySQL)
5. MOCK_FEEDBACK_DATA.to_csv() → 已接入真实数据库导出

【需要新增的 API 调用】
1. 大模型 API 调用 (DeepSeek/智谱/OpenAI)
   - 输入：动词
   - 输出：传统释义 + 优化释义（带语义分解）
   - 位置：在生成按钮点击时触发

2. 查询日志记录 (insert_query)
   - 输入：动词、释义结果
   - 存储：MySQL queries 表插入
   - 位置：在搜索动词时触发

【已实现的数据库存储 (MySQL 8.0)】
1. queries 表：记录查询日志
2. feedbacks 表：记录用户反馈
3. 热门动词统计：从 queries + feedbacks 联合查询
"""

# ============================================
# 技术栈说明
# ============================================
"""
当前技术栈：
- Streamlit：前端框架
- Pandas：数据处理
- Markdown：内容展示
- PyMySQL：MySQL 8.0 数据库连接

已集成：
- MySQL 8.0：数据库存储 (queries + feedbacks)
- 环境变量：数据库连接配置

待添加：
- OpenAI SDK：大模型 API 调用
- 日志库：记录查询和反馈
"""
