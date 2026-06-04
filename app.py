"""
Streamlit 单词知识图谱 Web 应用主入口

项目：单词知识图谱 Web 应用
技术栈：Streamlit + Sigma.js + GLM-4.7-Flash + MySQL 8.0
"""

import streamlit as st
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置页面布局
st.set_page_config(
    page_title="单词知识图谱",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://docs.streamlit.io',
        'Report a bug': 'https://github.com/streamlit/streamlit/issues',
        'About': '单词知识图谱系统 - 基于 Streamlit + Sigma.js + GLM-4.7-Flash'
    }
)

# 自定义 CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        color: #1f77b4;
        margin-bottom: 2rem;
    }
    .welcome-box {
        background-color: #f0f8ff;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
</style>
""", unsafe_allow_html=True)

# 页面标题
st.markdown('<div class="main-header">📚 单词知识图谱</div>', unsafe_allow_html=True)

# 页面介绍
st.markdown("""
<div class="welcome-box">
    <p><strong>欢迎使用单词知识图谱系统！</strong></p>
    <p>这是一个基于大模型的单词学习平台，通过知识图谱的方式帮助你理解和记忆英语单词。</p>
</div>
""", unsafe_allow_html=True)

# 导航菜单
page = st.sidebar.radio(
    "🚀 导航",
    ["🏠 首页", "🗺️ 学习", "💬 对话", "🔗 单词详情", "📊 单词库", "⚙️ 设置"],
    index=0,
    label_visibility="collapsed"
)

# 页面路由
if page == "🏠 首页":
    from pages import home
    home.app()

elif page == "🗺️ 学习":
    from pages import learn
    learn.app()

elif page == "💬 对话":
    from pages import chat
    chat.app()

elif page == "🔗 单词详情":
    from pages import word_detail
    word_detail.app()

elif page == "📊 单词库":
    from pages import words
    words.app()

elif page == "⚙️ 设置":
    from pages import settings
    settings.app()
