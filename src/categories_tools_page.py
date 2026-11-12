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
from typing import Any, Dict

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


# ============================================
# RV25-3：勾选写回统一改 on_change 回调形态（真用户动作才写库）
# ============================================
# 旧实现是渲染期值差写回形态（渲染时比较勾选值与库值，有差异即代写）：
# 陈旧驻留会话在他人改库后复渲染时，UI 残值与库值的 divergence 会被当成
# 「用户勾选」自动翻转启停（无操作写库，含 sys_admin 变体）。回调形态下
# 只有用户真的动了开关（on_change 触发）才落库；divergence 不代写。回调内
# 不直接 st.error/st.success（回调期渲染命令不可靠），成功/失败一律
# ui_kit.flash 落会话队列、st.rerun 后由页顶 pop_and_render_flash 弹出。
def _available_toggle_callback(category: str, tool_id: str,
                               actor: Dict[str, Any], widget_key: str) -> None:
    """available 勾选 on_change 回调：写 available_set/available_unset（审计）。"""
    new_value = bool(st.session_state.get(widget_key))
    ok = (available_set(category, tool_id, actor=actor, available=True)
          if new_value else
          available_unset(category, tool_id, actor=actor))
    if ok:
        ui_kit.flash(f"工具 {tool_id} 在范畴 {category} 的 available 位"
                     f"已{'置位' if new_value else '撤除'}（已审计）。")
        st.rerun()
    else:
        ui_kit.flash(f"available 写库未生效（工具 {tool_id}；见服务端日志）。",
                     level="error")


def _enabled_toggle_callback(category: str, tool_id: str,
                             actor: Dict[str, Any], widget_key: str,
                             avail: bool) -> None:
    """enabled 勾选 on_change 回调：写 enabled_set/enabled_unset（审计）。

    两步激活前置闸（仅 available 的工具可开）双保险：开关 disabled=not avail
    之外，回调内再验 avail（纵深防御——不依赖前端 disabled 态）。
    """
    if not avail:
        ui_kit.flash(
            f"工具 {tool_id} 在范畴 {category} 尚未 available（两步激活第一步"
            "未完成），enabled 位不可点亮。", level="warning")
        return
    new_value = bool(st.session_state.get(widget_key))
    ok = (enabled_set(category, tool_id, actor=actor, enabled=True)
          if new_value else enabled_unset(category, tool_id, actor=actor))
    if ok:
        ui_kit.flash(f"工具 {tool_id} 在范畴 {category} 的 enabled 位"
                     f"已{'点亮' if new_value else '熄灭'}（已审计）。")
        st.rerun()
    else:
        ui_kit.flash(f"enabled 写库未生效（工具 {tool_id}；见服务端日志）。",
                     level="error")


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
    _render_module_plugins_section(me)
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
                avail_key = f"avail_{category}_{t.id}"
                st.checkbox(
                    "available", value=avail,
                    key=avail_key,
                    disabled=bool(row and row.get("enabled") and avail),
                    help="安装/依赖/selfcheck 就绪位；仍启用的工具须先由词典"
                         "管理员解除 enabled 才能撤 available",
                    on_change=_available_toggle_callback,
                    args=(category, t.id, me, avail_key),
                )
            with col_state:
                if row is None:
                    st.caption("未配置")
                else:
                    st.caption(
                        f"available={'✅' if row.get('available') else '❌'} · "
                        f"enabled={'✅' if row.get('enabled') else '❌'}"
                        + (f" · v{row.get('tool_version')}" if row.get("tool_version") else ""))

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
                enab_key = f"enab_{category}_{t.id}"
                st.checkbox(
                    "enabled", value=enab,
                    key=enab_key,
                    disabled=not avail,   # 两步激活：仅 available 的工具可开
                    help="" if avail else "两步激活第一步未完成：该工具在此范畴"
                         "尚未 available（平台管理员区置位后才能点亮）",
                    on_change=_enabled_toggle_callback,
                    args=(category, t.id, me, enab_key, avail),
                )
            with col_state:
                st.caption("可点亮" if avail else "未 available · 不可点亮")

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

# ============================================
# 批次 30：五构件功能模块勾选（用户需求「五个插件模式」——词典管理员勾选启停）
# ============================================


def _module_toggle_callback(module_key: str, module_name: str,
                            actor: Dict[str, Any], widget_key: str) -> None:
    """功能模块勾选 on_change 回调（RV25-3）：真用户动作才写 module_plugins。

    写路径经 set_module_enabled（数据层词典管理员闸＋锁定项拒绝，逐字节
    不变）；PermissionError（会话角色被实时收窄的兜底）转 flash error。
    """
    new_enabled = bool(st.session_state.get(widget_key))
    from src.module_plugins import set_module_enabled  # 函数级导入（同区先例）

    try:
        ok = set_module_enabled(module_key, new_enabled, actor)
    except PermissionError as e:
        ui_kit.flash(f"⛔ {e}", level="error")
        return
    if ok:
        ui_kit.flash(
            f"功能模块「{module_name}」已{'启用' if new_enabled else '停用'}"
            "（已留痕）。"
        )
        st.rerun()
    else:
        ui_kit.flash("模块勾选写库未生效（见服务端日志）。", level="error")


def _render_module_plugins_section(me: Dict[str, Any]) -> None:
    """📦 功能模块（五构件 D·C·P·A·U 插件化）：词典管理员勾选启停。

    语义（src/module_plugins.py 单一实现）：
      * 勾选持久化 module_plugins 表；停用模块——侧边栏入口隐藏＋直访拦截；
      * 配置定义层（C）与编者界面层（U）为**锁定项**（勾选框置灰）：配置层
        是引擎输入、查阅层是平台底线——停用任一等于停全站；
      * 未登录/非管理员不渲染段；库降级灰注（R4 归因口径）。
    """
    try:
        from src.module_plugins import MODULE_SPECS, list_module_settings
    except ImportError as e:  # noqa: BLE001
        st.warning(f"插件注册表加载失败：{e}")
        return
    if not isinstance(me, dict):
        return
    effective = effective_six_roles(me)
    is_dict = "dict_admin" in effective
    st.markdown(f"<h2 style='{HEADER_H2}'>📦 功能模块（五构件插件）</h2>",
                unsafe_allow_html=True)
    st.caption(
        "勾选启用/取消勾选停用对应构件模块——停用的模块侧边栏入口隐藏、"
        "直访拦截；数据不受影响，重新勾选即恢复。配置定义层与编者界面层"
        "为平台底线（锁定项）。"
    )
    try:
        settings = {row["module_key"]: row for row in list_module_settings()}
    except Exception as e:  # noqa: BLE001
        st.warning(f"模块设置读取失败（R4 归因）：{e}")
        return
    for key, spec in MODULE_SPECS.items():
        row = settings.get(key) or {}
        enabled = bool(row.get("enabled", True))
        lock = spec.get("lock")
        label = f"{spec['symbol']} 构件｜{spec['name']}——{spec['description']}"
        if lock:
            st.checkbox(
                label + "（🔒 平台底线，不可停用）",
                value=True, disabled=True,
                key=f"module_lock_{key}",
            )
            continue
        # RV25-3：模块勾选写回同样改 on_change 回调形态（真用户动作才写）——
        # 值差写回形态下陈旧驻留会话会在复渲染时无操作自动翻转模块启停。
        toggle_key = f"module_toggle_{key}"
        st.checkbox(
            label,
            value=enabled,
            disabled=not is_dict,
            key=toggle_key,
            help="勾选=启用（侧边栏入口可见）；取消=停用（入口隐藏＋直访拦截）",
            on_change=_module_toggle_callback,
            args=(key, spec["name"], me, toggle_key),
        )
