"""
对话界面 - 与 AI 助手对话学习单词
"""

import logging
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import GLM_MAX_TOKENS_CHAT, MAX_QUICK_QUESTIONS_COLS
from config.logging_config import get_logger
from services.llm_service import LLMConfigError, get_llm_service

logger = get_logger(__name__)


# ========== 常量 ==========

SYSTEM_MESSAGE_TEMPLATE = """你是一个专门帮助用户学习英语单词的 AI 助手。

你的特点：
1. 使用简体中文回答问题
2. 鼓励用户多思考和探索
3. 主动询问用户的学习进度
4. 提供相关的单词建议

你可以回答：
- 单词释义和用法
- 语法问题
- 学习方法建议
- 英语学习技巧
- 单词记忆方法
"""

MODE_PROMPTS = {
    "标准模式": "你是一个友好的学习助手，鼓励用户提问和探索。",
    "讲解模式": "你是一个详细的单词讲解者，深入解释单词的含义和用法。",
    "练习模式": "你是一个互动式练习导师，通过问答帮助用户巩固知识。",
    "备考模式": "你是一个英语考试辅导老师，专注于考试技巧和重点词汇。",
}

QUICK_QUESTIONS = [
    "如何有效记忆英语单词？",
    "推荐一些高频英语单词",
    "什么是词根词缀记忆法？",
    "如何提升英语阅读能力？",
    "单词的用法有哪些需要注意的地方？",
]


# ========== 内部辅助函数 ==========

def _ensure_initialized() -> None:
    """初始化会话状态（仅在缺失时写入）"""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [{
            "role": "system",
            "content": SYSTEM_MESSAGE_TEMPLATE,
        }]
    if "current_mode" not in st.session_state:
        st.session_state.current_mode = "标准模式"


def _switch_mode(new_mode: str) -> None:
    """切换对话模式时更新 system message"""
    if new_mode == st.session_state.current_mode:
        return
    st.session_state.current_mode = new_mode
    mode_hint = MODE_PROMPTS.get(new_mode, "")
    st.session_state.chat_messages[0]["content"] = (
        SYSTEM_MESSAGE_TEMPLATE + f"\n当前模式：{mode_hint}"
    )


def _build_request_messages() -> list:
    """构造发送给 LLM 的 messages（system + 历史）"""
    return [
        {"role": "system", "content": st.session_state.chat_messages[0]["content"]},
        *st.session_state.chat_messages[1:],
    ]


def _send_user_message(prompt: str, message_placeholder) -> None:
    """
    发送一条用户消息并渲染 AI 回复（流式占位）。

    出错时在 placeholder 中显示错误信息。
    """
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    st.session_state.chat_history.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        try:
            llm = get_llm_service()
            response = llm.chat(
                _build_request_messages(),
                max_tokens=GLM_MAX_TOKENS_CHAT,
            )
        except LLMConfigError as e:
            message_placeholder.error(f"❌ 配置错误: {e}")
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("对话请求异常")
            message_placeholder.error(f"❌ 发生错误: {e}")
            return

        if "error" in response:
            message_placeholder.error(f"❌ 请求失败: {response.get('error')}")
            return

        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        message_placeholder.markdown(content)
        st.session_state.chat_messages.append({"role": "assistant", "content": content})
        st.session_state.chat_history.append({"role": "assistant", "content": content})


# ========== 主入口 ==========

def app() -> None:
    """对话界面应用入口"""
    st.title("💬 对话学习")

    _ensure_initialized()

    # ---------- 侧边栏 ----------
    with st.sidebar:
        st.header("⚙️ 对话设置")

        if st.button("🗑️ 清空对话"):
            st.session_state.chat_history = []
            st.session_state.chat_messages = [{
                "role": "system",
                "content": SYSTEM_MESSAGE_TEMPLATE,
            }]
            st.session_state.current_mode = "标准模式"
            st.rerun()

        st.divider()
        st.subheader("对话模式")
        selected_mode = st.selectbox(
            "选择模式",
            list(MODE_PROMPTS.keys()),
            index=list(MODE_PROMPTS.keys()).index(st.session_state.current_mode),
            label_visibility="collapsed",
        )
        _switch_mode(selected_mode)

    # ---------- 历史渲染 ----------
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # ---------- 用户输入 ----------
    if prompt := st.chat_input("输入你想问的问题..."):
        _send_user_message(prompt, st.empty())

    # ---------- 快捷问题 ----------
    st.divider()
    st.subheader("💡 快捷问题")

    cols = st.columns(MAX_QUICK_QUESTIONS_COLS)
    for i, question in enumerate(QUICK_QUESTIONS):
        with cols[i % MAX_QUICK_QUESTIONS_COLS]:
            if st.button(question, key=f"quick_{i}", use_container_width=True):
                _send_user_message(question, st.empty())


if __name__ == "__main__":
    app()
