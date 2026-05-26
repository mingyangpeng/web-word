import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import datetime

# ============================================
# 设计系统导入
# ============================================
from src.design_system import (
    HEADER_H1, HEADER_H2, HEADER_H3, HEADER_H4,
    BODY_BASE,
    PRIMARY_COLOR, SECONDARY_COLOR, SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR,
    BACKGROUND_COLOR, CARD_COLOR, TEXT_COLOR, TEXT_SECONDARY,
    BORDER_COLOR, SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    get_button_primary_style, get_button_outline_style, get_card_style,
    get_section_spacing, get_badge_style
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

# ============================================
# Sticky 搜索栏：Google 风格样式
# ============================================
st.markdown(f"""
<style>
/* Google 风格搜索栏 */
.google-search-bar {{
    position: sticky;
    top: 1.5rem;
    z-index: 1000;
    background: rgba({BACKGROUND_COLOR}, 0.98);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    padding: {SPACE_SM}px;
    margin: 0 0 {SPACE_LG}px 0;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1), 0 1px 3px rgba(0, 0, 0, 0.08);
    border: 1px solid rgba(226, 232, 240, 0.5);
}}
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
def search_verb(value: str) -> None:
    """
    处理动词搜索，带防抖延迟。

    当用户在搜索框输入时，延迟 300ms 后才更新结果，
    避免快速连续输入时触发过多搜索。

    Args:
        value: 用户输入的动词
    """
    if value and 1 <= len(value) <= 50:
        st.session_state.verb_result = value
        st.session_state.show_result = True
        st.session_state.current_debounce_start = datetime.datetime.now().timestamp()

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
def render_card_header(title, icon, expandable=True, collapsed=False):
    """
    渲染可折叠卡片头部。

    Args:
        title: 卡片标题
        icon: 图标
        expandable: 是否可折叠
        collapsed: 是否处于折叠状态

    Returns:
        HTML 格式的卡片头部
    """
    expanded = not collapsed

    if expandable:
        arrow = "▼" if expanded else "▶"
    else:
        arrow = "▪"

    style = f"""
    <div style="display: flex; justify-content: space-between; align-items: center;
                padding: 16px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; border-radius: 8px 8px 0 0; cursor: pointer;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-size: 1.5em;">{icon}</span>
            <span style="font-weight: 600; font-size: 1.1em;">{title}</span>
        </div>
        <span style="font-size: 0.9em; opacity: 0.9;">{arrow}</span>
    </div>
    """

    return style

def render_card_prototype(verb):
    """
    渲染原型与位移事件分析卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    semantic_table = MOCK_DEFINITIONS.get(verb, {}).get("semantic_table", [])

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

def render_card_anchor(verb):
    """
    渲染范畴锚定卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    semantic_table = MOCK_DEFINITIONS.get(verb, {}).get("semantic_table", [])

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
    definitions = MOCK_DEFINITIONS.get(verb, {})
    traditional = definitions.get("traditional", "")
    optimized = definitions.get("optimized", "")

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
    渲染图式示例卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #9f7aea; font-weight: 600; margin: 0 0 16px 0;">🖼️ 图式示例</h4>
    '''

    html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>示例场景:</strong></p>'
    html += '<ul style="color: #4a5568; line-height: 1.8;">'
    html += '<li>用户看到"{' + verb + '}"时，会联想到...</li>'
    html += '<li>在具体语境中，该动词通常出现在...</li>'
    html += '<li>与类似动词"跑进来"的区别在于...</li>'
    html += '</ul>'

    html += '</div>'
    return html

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
                on_click=search_verb,
                args=(verb,)
            )

    with tab2:
        for verb in EXAMPLE_VERBS.get(CATEGORY_PATH, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=search_verb,
                args=(verb,)
            )

    with tab3:
        for verb in EXAMPLE_VERBS.get(CATEGORY_MANNER, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=search_verb,
                args=(verb,)
            )

# ============================================
# 模拟数据
# ============================================
# 模拟统计数据
MOCK_STATS = {
    "total_queries": 847,
    "avg_rating": 4.2,
    "total_feedbacks": 312
}

# 模拟热门动词
MOCK_HOT_VERBS = [
    {"verb": "跑进来", "count": 234, "avg_rating": 4.5},
    {"verb": "冲进来", "count": 187, "avg_rating": 4.3},
    {"verb": "滑进来", "count": 156, "avg_rating": 4.1},
    {"verb": "滚进来", "count": 143, "avg_rating": 3.9},
    {"verb": "跌进来", "count": 128, "avg_rating": 4.0},
]

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

# 模拟历史反馈数据
MOCK_FEEDBACK_DATA = pd.DataFrame([
    {"verb": "跑进来", "rating": 5, "feedback": "语义分解很清晰，对学习很有帮助！"},
    {"verb": "冲进来", "rating": 4, "feedback": "体相部分描述得很准确。"},
    {"verb": "滑进来", "rating": 3, "feedback": "希望可以增加更多示例。"},
])

# ============================================
# 侧边栏组件
# ============================================
def render_sidebar():
    """渲染侧边栏组件"""
    st.sidebar.markdown(f"<h2 style='{HEADER_H2}'>📊 实验统计</h2>", unsafe_allow_html=True)
    st.sidebar.metric("总查询次数", MOCK_STATS["total_queries"], delta="+12 今天")
    st.sidebar.metric("平均评分", f"{MOCK_STATS['avg_rating']:.1f}/5.0")
    st.sidebar.metric("总反馈数", MOCK_STATS["total_feedbacks"])

    st.sidebar.markdown(get_section_spacing())

    st.sidebar.markdown(f"<h2 style='{HEADER_H3}'>🔥 热门查询动词</h2>", unsafe_allow_html=True)
    st.sidebar.markdown(
        """
        | 动词 | 次数 | 平均评分 |
        |------|------|----------|
        | 跑进来 | 234 | ⭐ 4.5 |
        | 冲进来 | 187 | ⭐ 4.3 |
        | 滑进来 | 156 | ⭐ 4.1 |
        | 滚进来 | 143 | ⭐ 3.9 |
        | 跌进来 | 128 | ⭐ 4.0 |
        """
    )

    st.sidebar.markdown(get_section_spacing())

    st.sidebar.markdown(f"<h2 style='{HEADER_H3}'>📥 数据导出</h2>", unsafe_allow_html=True)
    csv = MOCK_FEEDBACK_DATA.to_csv(index=False).encode('utf-8-sig')

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

    # ===== Google 风格搜索栏 =====
    st.markdown('<div class="google-search-bar">', unsafe_allow_html=True)

    with st.container():
        # 搜索输入框
        verb_input = st.text_input(
            label="搜索动词",
            value="跑进来",
            placeholder="搜索动词 (例如：跑进来、冲进来、滑进来...)",
            label_visibility="collapsed",
            on_change=search_verb
        )

    st.markdown('</div>', unsafe_allow_html=True)

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
    else:
        # 当有搜索结果时，显示结果区域
        verb = st.session_state.verb_result

        # 获取释义数据，如果没有则使用默认示例
        if verb in MOCK_DEFINITIONS:
            traditional = MOCK_DEFINITIONS[verb]["traditional"]
            optimized = MOCK_DEFINITIONS[verb]["optimized"]
        else:
            # 通用示例
            traditional = f"""
**传统释义 (词典)**

> 「{verb}」指人快速移动进入某空间，以奔跑的方式进入，强调速度和路径。

**语义要素分析：**
- 方式：奔跑
- 路径：进入空间
- 方向：朝向空间内部
- 体相：身体前倾，双臂摆动
"""
            optimized = f"""
**优化释义 (语义分解)**

| 语义要素 | 含义 | 体现 |
|---------|------|------|
| 【方式】 | 奔跑姿态 | 动态运动方式 |
| 【路径】 | 进入空间的路径 | 从外部到内部的移动 |
| 【方向】 | 朝向空间内部 | 目标明确 |
| 【体相】 | 身体前倾 | 动态姿态 |

**改进点：**
1. 显式分解语义要素
2. 提供更详细的描述
3. 便于对比不同动词
"""

    # 显示结果区域
    if hasattr(st.session_state, 'show_result') and st.session_state.show_result:
        verb = st.session_state.verb_result

        # 显示四张卡片布局
        st.markdown(f"<h2 style='{HEADER_H2}'>结果展示</h2>", unsafe_allow_html=True)

        # 卡片 1: 原型与位移事件分析
        st.markdown(get_card_style(), unsafe_allow_html=True)
        st.markdown(render_card_header("原型与位移事件分析", "🧬", expandable=True, collapsed=not st.session_state.card_expanded['prototype']), unsafe_allow_html=True)
        if st.session_state.card_expanded['prototype']:
            st.markdown(render_card_prototype(verb), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # 卡片 2: 范畴锚定
        st.markdown(get_card_style(), unsafe_allow_html=True)
        st.markdown(render_card_header("范畴锚定", "🎯", expandable=True, collapsed=not st.session_state.card_expanded['anchor']), unsafe_allow_html=True)
        if st.session_state.card_expanded['anchor']:
            st.markdown(render_card_anchor(verb), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # 卡片 3: 核心释义与多维辨异
        st.markdown(get_card_style(), unsafe_allow_html=True)
        st.markdown(render_card_header("核心释义与多维辨异", "📚", expandable=True, collapsed=not st.session_state.card_expanded['core']), unsafe_allow_html=True)
        if st.session_state.card_expanded['core']:
            st.markdown(render_card_core(verb), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # 卡片 4: 图式示例
        st.markdown(get_card_style(), unsafe_allow_html=True)
        st.markdown(render_card_header("图式示例", "🖼️", expandable=True, collapsed=not st.session_state.card_expanded['example']), unsafe_allow_html=True)
        if st.session_state.card_expanded['example']:
            st.markdown(render_card_example(verb), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

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
        submit_button = st.button("📤 提交反馈", type="primary", **get_button_primary_style())

        if submit_button:
            if rating > 0 and feedback_text.strip():
                # 模拟提交成功
                st.success("✅ 反馈已成功提交！感谢您的参与！")

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
                        <p style='{BODY_BASE}'><strong>动词:</strong> {fb['verb']}</p>
                        <p style='{BODY_BASE}'><strong>评分:</strong> {'⭐' * fb['rating']} ({fb['rating']}/5)</p>
                        <p style='{BODY_BASE}'><strong>反馈:</strong> {fb['feedback']}</p>
                        <p style='{BODY_BASE}'><strong>时间:</strong> {fb['timestamp']}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    # ===== JS 注入：实现搜索栏固定 =====
    components.html("""
<script>
(function() {
    const doc = window.parent.document;
    let searchBar = null;
    let isFixed = false;
    let spacer = null;

    function init() {
        // 找到标记
        const marker = doc.querySelector('.search-bar-start');
        if (!marker) {
            setTimeout(init, 300);
            return;
        }

        // 找到标记后面的行容器
        searchBar = marker.nextElementSibling;
        if (!searchBar || !searchBar.style) {
            setTimeout(init, 300);
            return;
        }

        // 保存原始样式
        searchBar.dataset.originalTop = searchBar.getBoundingClientRect().top + doc.documentElement.scrollTop;

        // 创建占位符，防止内容跳动
        spacer = doc.createElement('div');
        spacer.style.height = searchBar.offsetHeight + 'px';
        spacer.style.display = 'none';
        searchBar.parentNode.insertBefore(spacer, searchBar);

        // 监听滚动
        window.addEventListener('scroll', handleScroll);
        handleScroll();
    }

    function handleScroll() {
        if (!searchBar) return;

        const scrollY = doc.documentElement.scrollTop || doc.body.scrollTop;
        const originalTop = parseInt(searchBar.dataset.originalTop) || 0;

        if (scrollY > originalTop - 20 && !isFixed) {
            // 转为固定定位
            const width = searchBar.offsetWidth;
            searchBar.style.position = 'fixed';
            searchBar.style.top = '20px';
            searchBar.style.zIndex = '9999';
            searchBar.style.width = width + 'px';
            searchBar.style.background = 'rgba(255, 255, 255, 0.98)';
            searchBar.style.backdropFilter = 'blur(12px)';
            searchBar.style.padding = '16px';
            searchBar.style.borderRadius = '12px';
            searchBar.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.15)';
            searchBar.style.margin = '0 0 0 -16px';

            spacer.style.display = 'block';
            isFixed = true;
        } else if (scrollY <= originalTop - 20 && isFixed) {
            // 恢复原始
            searchBar.style.position = '';
            searchBar.style.top = '';
            searchBar.style.zIndex = '';
            searchBar.style.width = '';
            searchBar.style.background = '';
            searchBar.style.backdropFilter = '';
            searchBar.style.padding = '';
            searchBar.style.borderRadius = '';
            searchBar.style.boxShadow = '';
            searchBar.style.margin = '';

            spacer.style.display = 'none';
            isFixed = false;
        }
    }

    // 多次尝试初始化
    setTimeout(init, 500);
    setTimeout(init, 1000);
    setTimeout(init, 2000);
})();
</script>
""", height=0, width=0)

# ============================================
# 主函数
# ============================================
def main():
    """主函数"""
    render_sidebar()
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
【需要替换的模拟数据】
1. MOCK_STATS → 从数据库读取 (SQL 查询)
2. MOCK_HOT_VERBS → 从数据库统计热门动词 (GROUP BY 查询)
3. MOCK_DEFINITIONS → 替换为大模型 API 调用返回的真实释义
4. MOCK_FEEDBACK_DATA → 替换为真实用户反馈记录 (SQLite/MySQL)
5. MOCK_FEEDBACK_DATA.to_csv() → 接入真实数据库导出

【需要新增的 API 调用】
1. 大模型 API 调用 (DeepSeek/智谱/OpenAI)
   - 输入：动词
   - 输出：传统释义 + 优化释义（带语义分解）
   - 位置：在生成按钮点击时触发

2. 用户反馈提交 API
   - 接收：评分 + 文字反馈
   - 存储：数据库插入操作
   - 位置：在提交反馈按钮点击时触发

3. 统计数据查询 API
   - 查询：总查询次数、平均评分、热门动词
   - 位置：页面加载时从侧边栏调用

【需要优化的数据存储】
1. SQLite 数据库设计
   - queries 表：记录查询日志
   - feedbacks 表：记录用户反馈
   - hot_verbs 表：存储热门动词统计

2. Pandas 数据处理
   - CSV 导出功能需要接入真实数据
   - 统计指标需要实时更新
"""

# ============================================
# 技术栈说明
# ============================================
"""
当前技术栈：
- Streamlit：前端框架
- Pandas：数据处理
- Markdown：内容展示

未来需要添加：
- OpenAI SDK：大模型 API 调用
- SQLAlchemy：数据库 ORM
- 日志库：记录查询和反馈
"""
