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
# Sticky 搜索栏：直接定位 Streamlit 主内容的第一个容器
# ============================================
st.markdown(f"""
<style>
/* 找到主内容区域的第一个水平块容器，就是搜索栏所在的列 */
div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"]:first-of-type {{
    position: sticky;
    top: 1.5rem;
    z-index: 999;
    background: rgba({BACKGROUND_COLOR}, 0.98);
    backdrop-filter: blur(12px);
    padding: {SPACE_SM}px;
    margin: -{SPACE_SM/2}px -{SPACE_SM/2}px {SPACE_LG}px -{SPACE_SM/2}px;
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
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
    }
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

    download_style = get_button_outline_style()
    st.sidebar.download_button(
        label="导出反馈数据 (CSV)",
        data=csv,
        file_name=f"feedback_data_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
        **download_style
    )

# ============================================
# 主区域组件
# ============================================
def render_main_area():
    """渲染主区域组件"""
    st.markdown(f"<h1 style='{HEADER_H1}'>🏃 动词释义优化器</h1>", unsafe_allow_html=True)
    st.markdown(THEORY_DESCRIPTION, unsafe_allow_html=True)

    # ===== 搜索栏 =====
    col_input, col_stats = st.columns([2, 1])

    with col_input:
        verb_input = st.text_input(
            label="请输入动词",
            value="跑进来",
            placeholder="例如：跑进来、冲进来、滑进来...",
            label_visibility="collapsed"
        )

        if st.button("✨ 生成优化释义", type="primary", use_container_width=True):
            st.session_state.verb_result = verb_input
            st.session_state.show_result = True

    with col_stats:
        st.info("""
        ✅ **输入动词后点击生成按钮**
        ✅ **查看传统释义与优化释义的对比**
        ✅ **对优化释义进行评分和反馈**
        ✅ **帮助我们收集数据，改进释义质量**
        """)

    # 显示结果区域
    if hasattr(st.session_state, 'show_result') and st.session_state.show_result:
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

        # 使用两列展示释义
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📋 传统释义")
            st.markdown(traditional, unsafe_allow_html=True)

        with col2:
            st.subheader("✅ 优化释义 (语义分解)")
            st.markdown(optimized, unsafe_allow_html=True)

        # 用户反馈区域
        st.markdown(get_section_spacing())

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
            st.markdown(get_section_spacing())

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
