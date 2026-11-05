"""用户管理页面 —— 多人标注系统的账号管理视图（Streamlit，仅 admin 可用）。

数据层在 src/users_db.py；本文件只做展示与表单，业务规则（角色枚举校验、
重复用户名、停用即禁登）都落在数据层，页面只转译成功/失败。

安全规则（设计规范 §6）：
  * 权限检查在**函数入口**判定（role gate，§6-4）：非登录或非 admin
    直接拦截，不信任前端隐藏；
  * 所有用户输入/库内文本进 unsafe_allow_html 前一律过 _html_escape（§6-3）；
  * 表单密码框不回显；提交读取后立即从 st.session_state 删除，
    密码不常驻会话、不落日志（§6-2）；
  * 自保护：admin 不能停用自己、不能撤销自己的 admin 角色 —— 否则最后一个
    管理员把自己锁在门外后，系统再无入口。

由 app.py 集成步骤挂载（规范 §5：侧边栏「👥 用户管理」，仅 admin 可见）。
"""

import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional

import streamlit as st

from src.design_system import (
    HEADER_H1, HEADER_H2, HEADER_H3,
    get_card_style, get_table_header_style, get_table_row_style,
)
from src.users_db import ROLES, create_user, list_users, set_active, set_role

logger = logging.getLogger(__name__)

# 角色中文名（展示用；存库一律用英文枚举值）
ROLE_LABELS = {
    "admin": "管理员",
    "reviewer": "审核员",
    "annotator": "标注员",
    "viewer": "只读",
}

# 角色徽章配色（与 category_study_page._badge 的圆角徽章同一视觉语言）
ROLE_BADGE_COLORS = {
    "admin": "#2b6cb0",
    "reviewer": "#2f855a",
    "annotator": "#4299e1",
    "viewer": "#718096",
}

_ACTIVE_GREEN = "#2f855a"
_INACTIVE_RED = "#e53e3e"


def _current_user() -> Optional[Dict[str, Any]]:
    """当前会话用户（规范 §6-5：会话只存 st.session_state["user"]）。"""
    user = st.session_state.get("user")
    return user if isinstance(user, dict) else None


def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span）。text 由调用方保证已转义。"""
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'padding:1px 10px;border-radius:10px;font-size:0.78em;'
        f'margin-right:4px;">{text}</span>'
    )


def _metrics_row(users: List[Dict[str, Any]]) -> None:
    """顶部统计卡：总用户 / 启用中 / 管理员数（样式沿用 get_card_style）。"""
    n_total = len(users)
    n_active = sum(1 for u in users if int(u.get("active") or 0))
    n_admin = sum(1 for u in users if u.get("role") == "admin")
    cards = (
        ("总用户数", str(n_total)),
        ("启用中", str(n_active)),
        ("管理员", str(n_admin)),
    )
    cols = st.columns(len(cards))
    for col, (label, value) in zip(cols, cards):
        with col:
            st.markdown(
                f"<div style='{get_card_style()}'>"
                f"<div style='font-size:0.85em;color:#718096;'>{_html_escape(label)}</div>"
                f"<div style='font-size:1.8em;font-weight:bold;color:#2d3748;'>"
                f"{_html_escape(value)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _users_table(users: List[Dict[str, Any]]) -> None:
    """只读用户列表（HTML 表格）。所有文本过 _html_escape，哈希不出数据层。"""
    header_cells = "".join(
        f"<th style='{get_table_header_style()}'>{_html_escape(label)}</th>"
        for label in ("ID", "用户名", "显示名", "角色", "状态", "创建时间")
    )
    row_htmls = []
    for u in users:
        role = u.get("role") or "viewer"
        role_badge = _badge(
            _html_escape(ROLE_LABELS.get(role, str(role))),
            ROLE_BADGE_COLORS.get(role, "#718096"),
        )
        if int(u.get("active") or 0):
            status = _badge("启用", _ACTIVE_GREEN)
        else:
            status = _badge("已停用", _INACTIVE_RED)
        cell_style = f"{get_table_row_style()}padding:8px;"
        cells = (
            f"<td style='{cell_style}'>{int(u.get('id') or 0)}</td>"
            f"<td style='{cell_style}'>{_html_escape(str(u.get('username') or ''))}</td>"
            f"<td style='{cell_style}'>{_html_escape(str(u.get('display_name') or ''))}</td>"
            f"<td style='{cell_style}'>{role_badge}</td>"
            f"<td style='{cell_style}'>{status}</td>"
            f"<td style='{cell_style}'>{_html_escape(str(u.get('created_at') or ''))}</td>"
        )
        row_htmls.append(f"<tr>{cells}</tr>")

    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<tr>{header_cells}</tr>{''.join(row_htmls)}</table>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _user_options(users: List[Dict[str, Any]], exclude_id: Optional[int] = None) -> Dict[str, int]:
    """生成「显示名 → id」的下拉选项。exclude_id 用于剔除当前登录管理员。"""
    options: Dict[str, int] = {}
    for u in users:
        uid = int(u.get("id") or 0)
        if exclude_id is not None and uid == exclude_id:
            continue
        # selectbox 选项是纯文本渲染（非 HTML），不需要转义
        label = f"{u.get('username')}（{u.get('display_name') or u.get('username')}）"
        options[label] = uid
    return options


def _render_change_role_form(users: List[Dict[str, Any]], me: Dict[str, Any]) -> None:
    """改角色表单。当前登录管理员不在可改名单里（不能撤销自己的 admin）。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>🔁 修改角色</h3>", unsafe_allow_html=True)
    options = _user_options(users, exclude_id=int(me.get("id") or 0))
    if not options:
        st.info("没有可修改角色的其他用户。")
        return
    with st.form("users_admin_role_form", clear_on_submit=True):
        label = st.selectbox("选择用户", list(options.keys()))
        role = st.selectbox(
            "新角色",
            list(ROLES),
            format_func=lambda r: f"{ROLE_LABELS.get(r, r)}（{r}）",
        )
        submitted = st.form_submit_button("保存角色", use_container_width=True)
    if not submitted:
        return
    uid = options[label]
    if set_role(uid, role):
        st.success(f"已将用户 id={uid} 的角色改为「{ROLE_LABELS.get(role, role)}」。")
        logger.info(f"admin {me.get('username')} 将用户 id={uid} 角色改为 {role}")
        st.rerun()
    else:
        st.error("修改失败：用户不存在、角色未变化或数据库错误。")


def _render_toggle_active_form(users: List[Dict[str, Any]], me: Dict[str, Any]) -> None:
    """停用/启用表单。当前登录管理员不在名单里（不能停用自己）。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>⏸️ 停用 / 启用</h3>", unsafe_allow_html=True)
    options = _user_options(users, exclude_id=int(me.get("id") or 0))
    if not options:
        st.info("没有可操作的其他用户。")
        return
    with st.form("users_admin_active_form", clear_on_submit=True):
        label = st.selectbox("选择用户", list(options.keys()))
        action = st.radio("操作", ("停用（禁止登录）", "启用（恢复登录）"), horizontal=True)
        submitted = st.form_submit_button("执行", use_container_width=True)
    if not submitted:
        return
    uid = options[label]
    target_active = action.startswith("启用")
    if set_active(uid, target_active):
        st.success(f"已{'启用' if target_active else '停用'}用户 id={uid}。")
        logger.info(f"admin {me.get('username')} 将用户 id={uid} active 设为 {target_active}")
        st.rerun()
    else:
        st.error("操作失败：用户不存在、状态未变化或数据库错误。")


def _render_create_user_form() -> None:
    """新建用户表单。密码框不回显，提交读取后立即从会话清除。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>➕ 新建用户</h3>", unsafe_allow_html=True)
    with st.form("users_admin_create_form", clear_on_submit=True):
        username = st.text_input("用户名（唯一，≤50 字符）", max_chars=50, key="users_admin_create_username")
        password = st.text_input("初始密码", type="password", key="users_admin_create_password")
        display_name = st.text_input("显示名（≤80 字符）", max_chars=80, key="users_admin_create_display")
        role = st.selectbox(
            "角色",
            list(ROLES),
            format_func=lambda r: f"{ROLE_LABELS.get(r, r)}（{r}）",
        )
        submitted = st.form_submit_button("创建用户", use_container_width=True)
    if not submitted:
        return
    if not username.strip() or not password:
        st.error("用户名与初始密码不能为空。")
        return
    new_id = create_user(username.strip(), password, display_name.strip(), role)
    # 密码用完即焚：不留在 st.session_state（表单 clear_on_submit 之外兜底；
    # 键名与上方 text_input 的 key 一致）
    st.session_state.pop("users_admin_create_password", None)
    if new_id is not None:
        st.success(f"已创建用户「{username.strip()}」（id={new_id}，角色：{ROLE_LABELS.get(role, role)}）。")
        logger.info(f"admin 创建用户 '{username.strip()}'（id={new_id}，role={role}）")
        st.rerun()
    else:
        st.error("创建失败：角色非法、用户名已存在或数据库错误。")


def render_users_admin_page() -> None:
    """
    用户管理页入口（规范 §5：侧边栏「👥 用户管理」）。

    **role gate 在函数入口**（§6-4）：未登录或非 admin 一律拦截，
    页面内容不渲染 —— 权限不信任前端隐藏。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录。")
        return
    if me.get("role") != "admin":
        st.error("⛔ 用户管理仅管理员可用。")
        return

    st.markdown(f"<h1 style='{HEADER_H1}'>👥 用户管理</h1>", unsafe_allow_html=True)
    st.markdown(
        f"<h2 style='{HEADER_H2}'>账号与角色（管理员专用）</h2>",
        unsafe_allow_html=True,
    )

    users = list_users()
    if not users:
        # 空列表通常是数据库未初始化（ensure_user_tables 会在登录前建表+建 admin）
        st.info("暂无用户。请确认数据库已初始化（users 表由 ensure_user_tables 创建）。")
        return

    _metrics_row(users)
    st.markdown("")

    _users_table(users)
    st.markdown("")

    left, right = st.columns(2)
    with left:
        _render_change_role_form(users, me)
    with right:
        _render_toggle_active_form(users, me)

    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<strong>安全提示</strong>"
        f"<p style='margin:6px 0 0 0;color:#4a5568;'>内置默认管理员 "
        f"admin 的初始口令为公开的 bootstrap 凭据，<strong>首次登录后必须立即修改</strong>；"
        f"停用用户只是禁止登录，其历史提交记录保留。</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("")
    _render_create_user_form()
