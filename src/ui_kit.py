"""ui_kit —— 跨页面共用的一次性提示（flash）公共件（RV12-2）。

问题背景：dict_admin_pages / users_admin_page / lexical_pages 共 23 处
「st.success(...) + st.rerun()」成功提示 —— rerun 会把本轮渲染整体丢弃，
提示从未被用户看见（写操作成功后零反馈，易重复提交）。collab_pages 已有
正确模式（_flash 写会话、rerun 后 _pop_flash 弹出），本模块把它提取为
公共件供三页 + collab_pages 本体统一使用：

  * flash(message, level="success")：把提示追加进会话队列（调用点紧随
    st.rerun()，下一轮渲染时由 pop_and_render_flash 消费）；
  * pop_and_render_flash()：每轮渲染开头调用一次（app.main() 入口），
    弹出并渲染队列里的全部提示，消费即清空、不跨轮重复。

level 支持 success / error / warning / info；未知取值按 success 兜底
（与原 collab_pages._pop_flash 的保守口径一致：提示宁可展示也不静默丢弃）。

线程/会话口径：纯会话数据、不挂 widget 键；登出全清（app._LOGOUT_KEEP_KEYS
不含本模块键）自然覆盖 —— 共享终端换使用者不留上一人的操作提示。
"""

import streamlit as st

# 会话队列键：以 "_ui_kit_flash_queue" 常量收口（collab_pages 旧私有键
# "collab_flash" 一并迁移，旧队列键在迁移前的会话里只会被 _pop_flash
# 读不到而静默跳过，无残留风险）。
_FLASH_QUEUE_KEY = "_ui_kit_flash_queue"

_LEVEL_RENDERERS = {
    "success": st.success,
    "error": st.error,
    "warning": st.warning,
    "info": st.info,
}


def flash(message: str, level: str = "success") -> None:
    """追加一条一次性提示进会话队列（配合 st.rerun，下一轮渲染时弹出）。"""
    queue = st.session_state.get(_FLASH_QUEUE_KEY)
    if not isinstance(queue, list):
        queue = []
    queue.append({"level": str(level or "success"),
                  "message": str(message or "")})
    st.session_state[_FLASH_QUEUE_KEY] = queue


def pop_and_render_flash() -> None:
    """弹出并渲染队列中的全部一次性提示（app.main() 每轮渲染调用一次）。

    队列损坏（非 list / 元素非 dict）按空队列处理，不让提示机制带崩页面。
    """
    queue = st.session_state.pop(_FLASH_QUEUE_KEY, None)
    if not isinstance(queue, list):
        return
    for msg in queue:
        if not isinstance(msg, dict) or not str(msg.get("message") or ""):
            continue
        render = _LEVEL_RENDERERS.get(str(msg.get("level") or "success"),
                                      st.success)
        render(str(msg["message"]))
