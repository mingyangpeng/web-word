"""范畴与工具页面 —— 系统管理区的两步激活视图（Streamlit，FX-18）。

是什么（架构规范 §9 系统管理区「范畴与工具(available区)」＋ §4 两步激活
「平台管理员 available → 词典管理员 enabled」的页面落点）：

  * available 区（平台管理员）：按范畴 × 工具渲染 available 开关，
    写 src/tool_settings_db.available_set（权限闸门 sys_admin，操作落
    settings_audit 审计）；
  * enabled 区（词典管理员）：按范畴 × 工具渲染 enabled 开关，**仅
    available=1 的工具可开**（两步激活第二步的界面表达；available=0 的
    工具开关禁用并提示第一步未完成），写 tool_settings_db.enabled_set
    （权限闸门 dict_admin，操作落审计）；
  * 工具引用自检：对所选范畴跑 src/tools/pack_check.pack_selfcheck
    （pack 引用 ⊆ 注册表 ＋ 启用态校验，§4 selfcheck 双校验之二）——
    接在本页（doctor 在 app.py 系统体检，扩散面最小处选本页，FX-18 口径）；
  * 审计留痕视图：最近操作（settings_audit 倒序限 20 条）只读展示。

接线口径（如实声明）：本模块是独立页面文件，app.py 侧边栏路由归 app.py
所有者接线（本批次 app.py 禁改，未挂路由前的入口经本函数直接调用可测）。
页面体角色门：未登录拦截；sys_admin 或 dict_admin 可进（两个区按角色
分别渲染，无角色的区显示占位说明）。

安全规则：
  * 权限检查在函数入口判定（role gate）：非登录直接拦截，两步激活两区
    的写路径再经 tool_settings_db 内 guards.require_role 二次闸（纵深
    防御，与 users_admin_page 同型）；
  * 开关即写即审计（available_set/enabled_set 内部落 settings_audit），
    页面不绕过数据层直写 SQL。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import streamlit as st

from src import ui_kit
from src.category_pack import CATEGORIES
from src.db_utils import current_user as _current_user
from src.design_system import HEADER_H1, HEADER_H2
from src.tool_settings_db import (
    available_set,
    available_unset,
    bind_registry_loader,
    enabled_set,
    enabled_unset,
    ensure_tool_settings_tables,
    list_audit,
    list_settings,
)
from src.tools import registry as tool_registry
from src.tools.pack_check import pack_selfcheck
from src.users_db import effective_six_roles

logger = logging.getLogger(__name__)


def render_categories_tools_page() -> None:
    """范畴与工具页入口（系统管理区；两步激活 available/enabled 两区）。"""
    me = _current_user()
    if not me:
        st.warning("请先登录。")
        return
    roles = effective_six_roles(me)
    is_sys = "sys_admin" in roles
    is_dict = "dict_admin" in roles
    if not (is_sys or is_dict):
        st.error("⛔ 范畴与工具页仅管理员可用。")
        return

    # DB loader 缝绑定（函数指针赋值，零启动成本）：注册表 enabled 查询
    # 从此 DB 持久化位优先、读不到回落进程内 _ENABLED。
    bind_registry_loader(True)
    ensure_tool_settings_tables()   # 幂等（生产已由 init_database 建表）
    ui_kit.pop_and_render_flash()   # 独立调用也有一次性提示（app.main 同款）

    st.markdown(f"<h1 style='{HEADER_H1}'>🧩 范畴与工具</h1>",
                unsafe_allow_html=True)
    st.markdown(
        "<p style='color:#4a5568;margin:0 0 12px 0;'>两步激活"
        "（架构 §4）：平台管理员维护 <strong>available</strong>（安装/依赖/"
        "selfcheck 就绪）→ 词典管理员 <strong>enabled</strong>（工作方法"
        "决策，界面点亮）。操作全部落 settings_audit 审计。</p>",
        unsafe_allow_html=True,
    )

    categories = list(CATEGORIES())
    if not categories:
        st.info("configs/ 下暂无范畴包（含 pack.yaml 的目录）。")
        return
    category = st.selectbox("范畴", categories, key="ct_category")
    rows = {r["tool_id"]: r for r in list_settings(category)}
    tools = tool_registry.list_tools()

    # ---------- available 区（平台管理员） ----------
    st.markdown(f"<h2 style='{HEADER_H2}'>📦 available 区（平台管理员）</h2>",
                unsafe_allow_html=True)
    if not is_sys:
        st.info("available 位仅平台管理员可操作（当前账号无 sys_admin 角色）。")
    else:
        for t in tools:
            row = rows.get(t.id)
            avail = bool(row and row.get("available"))
            col_label, col_toggle, col_state = st.columns([4, 2, 6])
            with col_label:
                st.markdown(f"**{t.name}**（`{t.id}` v{t.version} · "
                            f"工序 {t.stage}）")
            with col_toggle:
                new_avail = st.checkbox(
                    "available", value=avail,
                    key=f"avail_{category}_{t.id}",
                    disabled=bool(row and row.get("enabled") and avail),
                    help="安装/依赖/selfcheck 就绪位；仍启用的工具须先由词典"
                         "管理员解除 enabled 才能撤 available",
                )
            with col_state:
                if row is None:
                    st.caption("未配置")
                else:
                    st.caption(
                        f"available={'✅' if row.get('available') else '❌'} · "
                        f"enabled={'✅' if row.get('enabled') else '❌'}"
                        + (f" · v{row.get('tool_version')}" if row.get("tool_version") else ""))
            if new_avail != avail:
                ok = (available_set(category, t.id, actor=me, available=True)
                      if new_avail else
                      available_unset(category, t.id, actor=me))
                if ok:
                    ui_kit.flash(f"工具 {t.id} 在范畴 {category} 的 available 位"
                                 f"已{'置位' if new_avail else '撤除'}（已审计）。")
                    st.rerun()
                else:
                    st.error(f"available 写库未生效（工具 {t.id}；见服务端日志）。")

    st.markdown("")

    # ---------- enabled 区（词典管理员） ----------
    st.markdown(f"<h2 style='{HEADER_H2}'>💡 enabled 区（词典管理员）</h2>",
                unsafe_allow_html=True)
    if not is_dict:
        st.info("enabled 位仅词典管理员可操作（当前账号无 dict_admin 角色）。")
    else:
        for t in tools:
            row = rows.get(t.id)
            avail = bool(row and row.get("available"))
            enab = bool(row and row.get("enabled"))
            col_label, col_toggle, col_state = st.columns([4, 2, 6])
            with col_label:
                st.markdown(f"**{t.name}**（`{t.id}` · 最低角色 {t.permission}）")
            with col_toggle:
                new_enab = st.checkbox(
                    "enabled", value=enab,
                    key=f"enab_{category}_{t.id}",
                    disabled=not avail,   # 两步激活：仅 available 的工具可开
                    help="" if avail else "两步激活第一步未完成：该工具在此范畴"
                         "尚未 available（平台管理员区置位后才能点亮）",
                )
            with col_state:
                st.caption("可点亮" if avail else "未 available · 不可点亮")
            if avail and new_enab != enab:
                ok = (enabled_set(category, t.id, actor=me, enabled=True)
                      if new_enab else enabled_unset(category, t.id, actor=me))
                if ok:
                    ui_kit.flash(f"工具 {t.id} 在范畴 {category} 的 enabled 位"
                                 f"已{'点亮' if new_enab else '熄灭'}（已审计）。")
                    st.rerun()
                else:
                    st.error(f"enabled 写库未生效（工具 {t.id}；见服务端日志）。")

    st.markdown("")

    # ---------- 工具引用自检（pack ⊆ 注册表 ＋ 启用态） ----------
    st.markdown(f"<h2 style='{HEADER_H2}'>🧪 工具引用自检</h2>",
                unsafe_allow_html=True)
    st.caption("范畴包 pack.yaml 声明的工具引用 ⊆ 注册表 ＋ 启用态校验"
               "（架构 §4 selfcheck 双校验之二；无引用的范畴直接通过）。")
    if st.button("运行范畴包工具引用自检", key="ct_pack_check"):
        report = pack_selfcheck(category)
        if report["ok"]:
            st.success(f"「{category}」{report['note']}")
        else:
            for p in report["problems"]:
                st.error(p)
        for w in report.get("warnings", []):
            st.warning(w)

    st.markdown("")

    # ---------- 审计留痕 ----------
    st.markdown(f"<h2 style='{HEADER_H2}'>🗂️ 最近操作审计</h2>",
                unsafe_allow_html=True)
    audit_rows = list_audit(limit=20, category=category)
    if not audit_rows:
        st.caption("本范畴暂无运行层操作审计。")
    else:
        st.dataframe(
            [{
                "时间": r.get("created_at"),
                "动作": r.get("action"),
                "工具": r.get("tool_id"),
                "变更": f"{r.get('old_value')} → {r.get('new_value')}",
                "操作人": r.get("actor_username") or r.get("actor_id") or "系统",
            } for r in audit_rows],
            use_container_width=True, hide_index=True,
        )
