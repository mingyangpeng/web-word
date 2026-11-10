"""用户管理页面 —— 多人标注系统的账号管理视图（Streamlit，六角色口径）。

数据层在 src/users_db.py；本文件只做展示与表单，业务规则（角色枚举校验、
重复用户名、停用即禁登）都落在数据层，页面只转译成功/失败。

v5.1 批次 3-K 新增「角色授予」面板（平台架构设计规范 §8）：六角色
（dict_admin/sys_admin/reviewer/editor/annotator/viewer）的授予与撤销
（grant_role/revoke_role，granted_by=当前操作人）。批次 4-N 升级为
**提权硬闸门**（施工规范 §7-N）：授予/撤销动作在调用数据层**之前**判定
——管理角色（dict_admin/sys_admin）仅词典管理员可授予/撤销，平台管理员
不提权口径下只可授/撤 viewer；本页所有能产生管理角色的写路径（角色授予
面板、legacy 修改角色表单、新建用户表单）同闸覆盖，不留面板外的提权旁路。
批次 6-T 收口：页面不再自带 effective 判定实现，四写路径（授予/撤销/
改基线/建号）统一经 _gate_error 调中央闸门 guards.require_role（判定
单一事实源在 guards，本模块只保留「目标角色 → 允许角色集」口径映射）。

页面体角色门（批次 4-N 收口，六角色口径）：effective_six_roles（与 app.py
同源的单一实现，users_db.effective_six_roles）含 sys_admin **或** dict_admin
即可进入 —— 账号生命周期是平台管理员（sys_admin）职能；词典管理员
（dict_admin）作为管理侧过渡期兼判同样放行（legacy role=='admin' 账号经
LEGACY_ROLE_TO_NEW_ROLES 映射必然两位一体，升级前后行为逐字节一致）。
侧边栏入口可见性仍由 app._PAGE_ACCESS_SIX（users_admin → sys_admin）控制，
此处是纵深防御第二层。

安全规则（设计规范 §6）：
  * 权限检查在**函数入口**判定（role gate，§6-4）：非登录或角色不符
    直接拦截，不信任前端隐藏；
  * 所有用户输入/库内文本进 unsafe_allow_html 前一律过 _html_escape（§6-3）；
  * 表单密码框不回显；提交读取后立即从 st.session_state 删除，
    密码不常驻会话、不落日志（§6-2）；
  * 自保护：admin 不能停用自己、不能撤销自己的 admin 角色 —— 否则最后一个
    管理员把自己锁在门外后，系统再无入口。

由 app.py 集成步骤挂载（规范 §5：侧边栏「👥 用户管理」，六角色口径见上）。

批次 19（用户上下文域 UI 落地）新增「⚙️ 我的偏好」段（页面末尾，新建用户
表单之后）：user_profiles 键值对的个人读写面（user_context_db，own-rows-only
—— user_id 会话派生，天然只读写自己的键）。预置 ui.default_category /
ui.rows_per_page 两个示例键＋自定义键增删；**只做读写 UI，不改页面行为**
—— 键的消费接线归下批（docstring 内注明），保存/删除成功一律 ui_kit.flash
+ rerun（RV12 口径）。
"""

import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional

import streamlit as st

from src.design_system import (
    HEADER_H1, HEADER_H2, HEADER_H3,
    get_badge_html, get_card_style, get_table_header_style,
    get_table_row_style,
)
from src import guards
from src import ui_kit  # RV12-2：成功提示统一走 ui_kit.flash（rerun 不再丢）
from src import user_context_db  # 批次 19：我的偏好读写（own-rows-only）
from src.db_utils import current_user as _current_user  # R6-4：单一实现点
from src.users_db import (
    NEW_ROLES,
    ROLES,
    create_user,
    effective_six_roles,
    grant_role,
    list_roles,
    list_users,
    revoke_role,
    set_active,
    set_role,
)

logger = logging.getLogger(__name__)

# 角色中文名（展示用；存库一律用英文枚举值）。
# 前 4 个是 legacy users.role 列枚举（旧改角色表单/会话徽章继续用）；
# 后 3 个是 v5.1 六角色新增（平台架构设计规范 §8，user_roles 多角色表）。
ROLE_LABELS = {
    "admin": "管理员",
    "reviewer": "审核员",
    "annotator": "标注员",
    "viewer": "只读",
    "dict_admin": "词典管理员",
    "sys_admin": "平台管理员",
    "editor": "撰写员",
}

# 角色徽章配色（与 category_study_page._badge 的圆角徽章同一视觉语言）。
# RV1-2：白字对比全 ≥4.5:1 —— 旧 annotator #4299e1 3.05:1 / viewer
# #718096 4.02:1 / editor #dd6b20 3.39:1 不达 AA，分别换深档
# #2b6cb0（5.42:1）/ #4a5568（7.53:1）/ #9c4221（6.53:1）。
ROLE_BADGE_COLORS = {
    "admin": "#2b6cb0",
    "reviewer": "#2f855a",
    "annotator": "#2b6cb0",
    "viewer": "#4a5568",
    "dict_admin": "#553c9a",
    "sys_admin": "#2c5282",
    "editor": "#9c4221",
}

_ACTIVE_GREEN = "#2f855a"
# RV1-2：停用红取深档（白字 5.47:1；旧 #e53e3e 4.13:1 不达 AA）。
_INACTIVE_RED = "#c53030"

# 批次 19「⚙️ 我的偏好」预置示例键（user_context_db 键名约定 'ui.*' = 界面
# 设置）：**只做读写 UI，不改页面行为** —— 消费接线归下批（届时由消费方
# 读 get_profile/list_profiles 调整默认范畴下拉值/列表行数，本页不做）。
_PREF_PRESET_KEYS = (
    ("ui.default_category", "默认范畴下拉值（如 motion）"),
    ("ui.rows_per_page", "每页行数（如 20）"),
)

# ============================================
# 提权硬闸门（批次 4-N 立，批次 6-T 收口到中央闸门 guards.require_role）
# ============================================
# 本页不再自带 effective 判定实现（批次 6-T 前 _grant_gate_error/
# _escalation_gate_error 各自折算 effective_six_roles，属页面级重复）——
# 「操作人是否具备某角色」的判定单一事实源是 src/guards.require_role
# （内部复用 users_db.effective_six_roles 同一实现）；本模块只保留
# 「动作/目标角色 → 允许角色集」的口径映射（这是本页的策略，不是判定）。
#
# 管理角色：授予/撤销即「提权到管理侧」，仅词典管理员（effective 集含
# dict_admin）可执行 —— 平台管理员不得自行提权（含不得互相授予）；
# legacy admin 经映射两位一体（dict_admin+sys_admin）自然通过。

# 拒绝文案里的动作名（与集成测试断言的硬闸门口径文案逐字对齐）。
_ACTION_ADMIN_ROLES = "授予/撤销管理角色"
_ACTION_VIEWER_ROLE = "viewer 角色的授予/撤销"
_ACTION_FUNCTIONAL_ROLE = "职能角色的授予/撤销"

# 批次 5 决策开关：职能角色（reviewer/editor/annotator）的授予/撤销是否放宽给
# 纯平台管理员（sys_admin，effective 不含 dict_admin）过渡期兼判。当前 False ——
# 施工规范 §7-N「sys_admin 只可授 viewer」＋ 平台架构设计规范 §8「平台管理员
# 不得自行提权」（职能角色入册属三级链第二级，归词典管理员）。收口后开关的
# 唯一作用是选择传给 guards.require_role 的 allowed 集合（翻转即放宽，判定
# 实现不变）。
_SYS_ADMIN_TRANSITION_FUNCTIONAL_GRANT = False


def _gate_error(me: Dict[str, Any], target_role: str,
                target_uid: Optional[int] = None,
                *, manage_action: Optional[str] = None) -> Optional[str]:
    """提权硬闸门（授予/撤销/改基线/建号四写路径共用；批次 6-T 收口）。

    写动作提交后、调用数据层**之前**判定：把目标角色映射为「允许角色集 +
    动作名」后调用中央闸门 ``guards.require_role(me, allowed, action)`` ——
    判定（操作人有效角色集是否满足）单一实现复用
    users_db.effective_six_roles；不满足时 PermissionError 文案（含动作名）
    经 ``⛔`` 前缀返回给调用方 st.error 直出并跳过数据层调用，None 表示放行。

    口径（施工规范 §7-N「授予/撤销 dict_admin/sys_admin 仅词典管理员（effective
    判定），sys_admin 只可授 viewer」/ 平台架构设计规范 §8 三级最小权限链，
    N 的开关语义原样保留）：
      * 目标 ∈ {dict_admin, sys_admin}（管理角色；legacy 基线 'admin' 等价于
        dict_admin+sys_admin 双授予，同闸）：allowed={dict_admin} —— 平台
        管理员不得自行提权；
      * 目标 = viewer：词典管理员或平台管理员皆可（三级链第一级建号基线，
        平台管理员主管辖）；
      * 目标 ∈ {reviewer, editor, annotator}（职能角色）：仅词典管理员 ——
        sys_admin 不提权口径只可授/撤 viewer；决策开关
        _SYS_ADMIN_TRANSITION_FUNCTIONAL_GRANT=True 时放宽为两类管理员皆可；
      * 其余/未知角色名：allowed 为空，guards fail-closed 一律拒绝。

    撤方向旁路封堵（原 _escalation_gate_error 语义，target_uid 传入时生效）：
    「修改角色」写的是 users.role 基线列，数据层会把映射集重置进 user_roles
    —— 对**当前兼有管理角色**的用户改基线（rowcount>0 时 DELETE 全部
    user_roles 行再按新基线重建）等价于一次撤销管理角色，故先实时读库
    （list_roles，含旧列兜底）探测目标是否兼有管理角色，是则无论新基线是
    什么都按管理角色闸门判定。

    R1-7 扩展（manage_action keyword，批次 12）：停用/启用等**账号生命周期
    动作**的目标不是角色而是用户 —— 传 manage_action（动作名）时按目标用户
    实时角色判定：目标兼有管理角色（dict_admin/sys_admin）→ 操作人须
    dict_admin（管理角色账号的停用/启停是词典管理员权柄，防止纯平台管理员
    停用词典管理员）；普通账号 → 两类管理员皆可（账号生命周期归平台管理员，
    架构规范 §8）。判定实现与角色路径同一 guards.require_role 调用。

    Args:
        me: 当前操作人会话用户 dict（显式传给 guards，测试可注入）。
        target_role: 目标角色名（六角色或 legacy 基线角色；manage_action
            给定时忽略）。
        target_uid: 目标用户 id（改基线路径传，用于撤方向探测；其余路径 None）。
        manage_action: R1-7 账号生命周期动作名（如「停用/启用管理角色账号」）；
            给定时走目标用户管理角色探测分支，target_role 不参与判定。
    """
    if manage_action is not None:
        if target_uid is not None and (
            {"dict_admin", "sys_admin"} & set(list_roles(int(target_uid)))
        ):
            allowed, action = ("dict_admin",), manage_action
        else:
            allowed, action = ("dict_admin", "sys_admin"), manage_action
    else:
        if target_uid is not None and (
            {"dict_admin", "sys_admin"} & set(list_roles(int(target_uid)))
        ):
            target_role = "admin"  # 撤方向封堵：等价一次管理角色撤销 → 同闸
        if target_role in ("dict_admin", "sys_admin", "admin"):
            allowed, action = ("dict_admin",), _ACTION_ADMIN_ROLES
        elif target_role == "viewer":
            allowed, action = ("dict_admin", "sys_admin"), _ACTION_VIEWER_ROLE
        elif target_role in ("reviewer", "editor", "annotator"):
            allowed = (
                ("dict_admin", "sys_admin")
                if _SYS_ADMIN_TRANSITION_FUNCTIONAL_GRANT
                else ("dict_admin",)
            )
            action = _ACTION_FUNCTIONAL_ROLE
        else:
            allowed, action = (), "未知角色的设置"
    try:
        guards.require_role(me, allowed=allowed, action=action)
    except PermissionError as e:
        return f"⛔ {e}"
    return None


def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span）。text 由调用方保证已转义。

    RV1-2（_badge 收敛）：实现单份进 design_system.get_badge_html ——
    文字颜色按底色自动选深/浅（旧版写死白字，浅底不达 WCAG AA）；
    转义契约不变。
    """
    return get_badge_html(text, color)


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
                # RV1-7：卡内灰字深档 #4a5568（白/浅底 7.53:1；旧 #718096 4.02:1）
                f"<div style='font-size:0.85em;color:#4a5568;'>{_html_escape(label)}</div>"
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
            ROLE_BADGE_COLORS.get(role, "#4a5568"),
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
    # 提权硬闸门（批次 4-N 旁路封堵，批次 6-T 收口到 guards.require_role）：
    # 基线改为 admin ≙ 授予 dict_admin+sys_admin；对兼有管理角色的用户改基线
    # ≙ 撤销管理角色（user_roles 被重置）——双向同闸（见 _gate_error）
    gate_error = _gate_error(me, role, target_uid=uid)
    if gate_error:
        st.error(gate_error)
        logger.error(
            f"用户 {me.get('username')} 尝试将 id={uid} 基线角色改为 {role}，"
            "被提权硬闸门拒绝（guards.require_role）"
        )
        return
    # R1-1 直调面：数据层传 actor=当前会话用户（页面闸门之上再兜一道；
    # PermissionError 转译 st.error，不静默）
    try:
        ok = set_role(uid, role, actor=me)
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    if ok:
        ui_kit.flash(f"已将用户 id={uid} 的角色改为「{ROLE_LABELS.get(role, role)}」。")
        logger.info(f"admin {me.get('username')} 将用户 id={uid} 角色改为 {role}")
        st.rerun()
    else:
        st.error("修改失败：用户不存在、角色未变化或数据库错误。")


def _render_toggle_active_form(users: List[Dict[str, Any]], me: Dict[str, Any]) -> None:
    """停用/启用表单。当前登录管理员不在名单里（不能停用自己）。

    R1-7 管理闸门（批次 12）：目标用户实时兼有管理角色（dict_admin/sys_admin，
    list_roles 读库判定）时，操作人须 dict_admin（_gate_error manage_action
    口径）—— 防止纯平台管理员停用/启用词典管理员账号；普通账号两类管理员
    皆可。数据层 set_active 另传 actor=当前会话用户（R1-1 直调面，纵深防御
    第二层；PermissionError 转译 st.error）。
    """
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
    # R1-7 管理闸门：目标兼有管理角色 → 操作人须 dict_admin（先判后调数据层）
    gate_error = _gate_error(me, "", target_uid=uid,
                             manage_action="停用/启用管理角色账号")
    if gate_error:
        st.error(gate_error)
        logger.error(
            f"用户 {me.get('username')} 尝试{'启用' if target_active else '停用'} "
            f"id={uid}，被管理闸门拒绝（guards.require_role，R1-7）"
        )
        return
    try:
        ok = set_active(uid, target_active, actor=me)
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    if ok:
        ui_kit.flash(f"已{'启用' if target_active else '停用'}用户 id={uid}。")
        logger.info(f"admin {me.get('username')} 将用户 id={uid} active 设为 {target_active}")
        st.rerun()
    else:
        st.error("操作失败：用户不存在、状态未变化或数据库错误。")


def _render_create_user_form(me: Dict[str, Any]) -> None:
    """新建用户表单。密码框不回显，提交读取后立即从会话清除。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>➕ 新建用户</h3>", unsafe_allow_html=True)
    st.caption(
        "新号默认 viewer（只读）——三级最小权限链第一级；初始密码须首次登录修改"
        "（登录后出现强制改密提示），六角色叠加授权见上方「角色授予」面板。"
    )
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
    # 提权硬闸门（批次 4-N 旁路封堵，批次 6-T 收口到 guards.require_role）：
    # 建号即授 admin 基线 ≙ 授予管理角色
    gate_error = _gate_error(me, role)
    if gate_error:
        st.error(gate_error)
        logger.error(
            f"用户 {me.get('username')} 尝试建号（'{username.strip()}'）即授 "
            f"{role} 基线，被提权硬闸门拒绝（guards.require_role）"
        )
        return
    # 建号留痕（R3-5）：created_by = 当前会话用户 id（me 为登录会话 dict，
    # 残缺注入按 None 处理 —— 数据层对非法 created_by 有一致拒绝口径）；
    # R1-1 直调面：actor=当前会话用户（低权会话快照滞后时数据层兜底拒绝）
    try:
        new_id = create_user(
            username.strip(), password, display_name.strip(), role,
            created_by=(me.get("id") if isinstance(me, dict) and isinstance(
                me.get("id"), int) else None),
            actor=me,
        )
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    # 密码用完即焚：不留在 st.session_state（表单 clear_on_submit 之外兜底；
    # 键名与上方 text_input 的 key 一致）
    st.session_state.pop("users_admin_create_password", None)
    if new_id is not None:
        ui_kit.flash(f"已创建用户「{username.strip()}」（id={new_id}，角色：{ROLE_LABELS.get(role, role)}）。")
        logger.info(f"admin 创建用户 '{username.strip()}'（id={new_id}，role={role}）")
        st.rerun()
    else:
        st.error("创建失败：角色非法、用户名已存在或数据库错误。")


def _render_role_grant_panel(users: List[Dict[str, Any]], me: Dict[str, Any]) -> None:
    """六角色授予面板（批次 3-K，平台架构设计规范 §8；批次 4-N 硬闸门）。

    选用户 → 显示其当前 roles（users_db.list_roles 实时读 user_roles 表，
    无行账号按旧 role 列映射兜底）→ 授予/撤销（grant_role / revoke_role，
    granted_by 记当前操作人）。

    提权硬闸门（批次 4-N）：授予/撤销提交后、调用数据层**之前**经 _gate_error
    判定（批次 6-T 收口：判定走中央闸门 guards.require_role，口径见其
    docstring）——管理角色（dict_admin/sys_admin）仅词典管理员可执行；纯
    平台管理员（sys_admin）不提权口径下仅可授/撤 viewer；职能角色
    （reviewer/editor/annotator）仅词典管理员（批次 5 决策开关
    _SYS_ADMIN_TRANSITION_FUNCTIONAL_GRANT 可放宽）。被拒时 st.error 且
    **不触数据层**（纵深防御第二层：本页闸门之外，敏感词典写路径另有
    guards.require_dict_admin API 级闸门）。
    当前登录管理员不在可操作名单里（与改角色/停用表单同一自保护口径：
    legacy admin 的权柄来自旧 role 列，撤销自己的 user_roles 行也会被
    list_roles 的旧列兜底映射复活，徒增困惑）。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>🎭 角色授予（六角色）</h3>", unsafe_allow_html=True)
    st.caption(
        "六角色可叠加（词典管理员 dict_admin · 平台管理员 sys_admin · 审校 reviewer · "
        "撰写 editor · 标注 annotator · 只读 viewer）。新号默认 viewer；账号级角色在"
        "本面板授予，项目内职能与任务分派走三级权限链（项目成员/任务分配页）。"
    )
    st.info(
        "⚠️ **平台管理员不得自行提权（硬闸门已启用）**：授予/撤销 dict_admin"
        "（词典管理员）或 sys_admin（平台管理员）仅词典管理员可执行，"
        "越权提交将被拒绝且不写库；平台管理员只可授/撤 viewer。"
    )

    options = _user_options(users, exclude_id=int(me.get("id") or 0))
    if not options:
        st.info("没有可授予角色的其他用户。")
        return

    selected_label = st.selectbox(
        "选择用户", list(options.keys()), key="users_admin_role_grant_user",
    )
    target_uid = options[selected_label]
    current_roles = list_roles(target_uid)

    if current_roles:
        badges = "".join(
            _badge(
                _html_escape(f"{ROLE_LABELS.get(r, r)}（{r}）"),
                ROLE_BADGE_COLORS.get(r, "#4a5568"),
            )
            for r in current_roles
        )
        st.markdown(f"当前角色：{badges}", unsafe_allow_html=True)
    else:
        st.markdown("当前角色：（无六角色记录，按旧角色列兜底显示）")

    grant_submitted = False
    grant_role_sel: Optional[str] = None
    with st.form("users_admin_grant_role_form", clear_on_submit=True):
        grant_role_sel = st.selectbox(
            "授予角色",
            list(NEW_ROLES),
            format_func=lambda r: f"{ROLE_LABELS.get(r, r)}（{r}）",
        )
        grant_submitted = st.form_submit_button("授予角色", use_container_width=True)

    revoke_submitted = False
    revoke_role_sel: Optional[str] = None
    if current_roles:
        with st.form("users_admin_revoke_role_form", clear_on_submit=True):
            revoke_role_sel = st.selectbox(
                "撤销角色",
                current_roles,
                format_func=lambda r: f"{ROLE_LABELS.get(r, r)}（{r}）",
            )
            revoke_submitted = st.form_submit_button("撤销角色", use_container_width=True)
    else:
        st.caption("该用户暂无可撤销的六角色（授予后可撤销）。")

    granter_id = int(me.get("id") or 0)
    granter_name = str(me.get("username") or "")
    if grant_submitted and grant_role_sel:
        # 提权硬闸门：先判定，被拒则不调数据层（批次 4-N 立，6-T 收口到 guards）
        gate_error = _gate_error(me, grant_role_sel)
        if gate_error:
            st.error(gate_error)
            logger.error(
                f"用户 {granter_name} 授予用户 id={target_uid} 六角色 {grant_role_sel} "
                "被提权硬闸门拒绝"
            )
        else:
            # R1-1 直调面：数据层传 actor=当前会话用户（会话快照滞后的兜底拒绝）
            try:
                granted = grant_role(target_uid, grant_role_sel,
                                     granted_by=granter_id, actor=me)
            except PermissionError as e:
                st.error(f"⛔ {e}")
                return
            if granted:
                ui_kit.flash(
                    f"已授予用户 id={target_uid} 角色「{ROLE_LABELS.get(grant_role_sel, grant_role_sel)}」"
                    f"（granted_by={granter_id}）。"
                )
                logger.info(
                    f"admin {granter_name} 授予用户 id={target_uid} 六角色 {grant_role_sel}"
                )
                st.rerun()
            else:
                st.error("授予未生效：该用户已持有该角色、用户不存在或数据库错误。")
    if revoke_submitted and revoke_role_sel:
        # 提权硬闸门：先判定，被拒则不调数据层（批次 4-N 立，6-T 收口到 guards）
        gate_error = _gate_error(me, revoke_role_sel)
        if gate_error:
            st.error(gate_error)
            logger.error(
                f"用户 {granter_name} 撤销用户 id={target_uid} 六角色 {revoke_role_sel} "
                "被提权硬闸门拒绝"
            )
        else:
            try:
                revoked = revoke_role(target_uid, revoke_role_sel, actor=me)
            except PermissionError as e:
                st.error(f"⛔ {e}")
                return
            if revoked:
                revoked_label = ROLE_LABELS.get(revoke_role_sel, revoke_role_sel)
                ui_kit.flash(f"已撤销用户 id={target_uid} 角色「{revoked_label}」。")
                logger.info(
                    f"admin {granter_name} 撤销用户 id={target_uid} 六角色 {revoke_role_sel}"
                )
                st.rerun()
            else:
                st.error("撤销未生效：该用户未持有该角色、用户不存在或数据库错误。")


def _render_my_preferences() -> None:
    """⚙️ 我的偏好（批次 19，用户上下文域 UI 落地；页面末尾段）。

    user_profiles 键值对的个人读写面：预置 _PREF_PRESET_KEYS 两键的编辑
    （预填已存值）＋自定义键新增/覆盖＋任意已存键删除。**只做读写 UI，
    不改页面行为**（消费接线归下批）；own-rows-only（user_context_db 会话
    派生 user_id，连越权入口都没有），六角色皆可用（私人数据）。

    未登录整段不渲染（上下文域是登录态功能 —— fail-closed 口径的 UI 表达；
    本页入口本有登录门，这里再兜一层纵深防御）。空值口径：提交空白=未设值
    （upsert_profile(key, None)，RV2-3 第 2 类「键已建未设值」；页面文案
    注明）。值两端空白由 UI 层去除（偏好值是设置项非用户原文，与键同类
    清洗；数据层仍原样存，不替用户做清洗）。成功一律 ui_kit.flash + rerun
    （RV12），失败 st.error 本轮直出。

    读取降级：list_profiles 库不可用返回 []（数据层口径），段照常渲染
    （编辑框为空值态），保存时才报错 —— 不因读降级就把整段藏掉。
    """
    me = _current_user()
    if not isinstance(me, dict):
        return
    st.markdown(f"<h3 style='{HEADER_H3}'>⚙️ 我的偏好</h3>", unsafe_allow_html=True)
    st.caption(
        "个人偏好键值对（user_profiles 表，跨设备续接；仅自己可读写）。"
        "本段只做读写 UI：预设键暂不改变页面行为（消费接线归下批）。"
        "值两端空白会去除；空白提交=未设值。"
    )
    try:
        rows = user_context_db.list_profiles()
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"我的偏好读取失败（降级为空值态）: {e}")
        rows = []
    stored = {
        str(r.get("pref_key")): r.get("pref_value")
        for r in rows if r.get("pref_key")
    }

    # -- 预置两键编辑（预填已存值；保存=逐键 upsert，空值=None 未设值）--
    with st.form("my_prefs_preset_form", clear_on_submit=False):
        new_values: Dict[str, Optional[str]] = {}
        for key, label in _PREF_PRESET_KEYS:
            new_values[key] = st.text_input(
                f"{key} —— {label}", value=str(stored.get(key) or ""),
                key=f"my_prefs_input_{key}",
            )
        save_submitted = st.form_submit_button("💾 保存预设键",
                                               use_container_width=True)
    if save_submitted:
        failed = [k for k, v in new_values.items()
                  if not user_context_db.upsert_profile(
                      k, v.strip() or None)]
        if failed:
            st.error(f"保存失败（键 {', '.join(failed)}）：键非法、值超长"
                     "或数据库不可用。")
        else:
            ui_kit.flash("我的偏好已保存（跨设备续接）。")
            st.rerun()

    # -- 自定义键新增/覆盖 --
    preset_names = {k for k, _ in _PREF_PRESET_KEYS}
    custom_keys = sorted(k for k in stored if k not in preset_names)
    with st.form("my_prefs_custom_form", clear_on_submit=True):
        custom_key = st.text_input("自定义键（≤120 字符，如 ui.theme）",
                                   max_chars=120, key="my_prefs_custom_key")
        custom_value = st.text_input("自定义值（空白=未设值）",
                                     key="my_prefs_custom_value")
        add_submitted = st.form_submit_button("➕ 新增/覆盖自定义键",
                                              use_container_width=True)
    if add_submitted:
        clean_key = custom_key.strip()
        if not clean_key:
            st.error("自定义键不能为空。")
        elif user_context_db.upsert_profile(clean_key,
                                            custom_value.strip() or None):
            ui_kit.flash(f"偏好键「{clean_key}」已保存。")
            st.rerun()
        else:
            st.error("保存失败：键非法、值超长或数据库不可用。")

    # -- 已存键删除（自定义键可删；预置键删除后重存即可恢复）--
    all_keys = sorted(stored)
    if custom_keys:
        st.markdown(
            "**当前自定义键：** " + "、".join(f"`{k}`" for k in custom_keys)
        )
    if all_keys:
        with st.form("my_prefs_delete_form", clear_on_submit=False):
            delete_key = st.selectbox("选择要删除的偏好键", all_keys,
                                      key="my_prefs_delete_key")
            delete_submitted = st.form_submit_button("🗑 删除所选键",
                                                     use_container_width=True)
        if delete_submitted:
            if user_context_db.delete_profile(delete_key):
                ui_kit.flash(f"偏好键「{delete_key}」已删除。")
                st.rerun()
            else:
                st.error("删除失败（数据库不可用），请稍后重试。")
    else:
        st.caption("暂无已存偏好键（保存上方预设键或新增自定义键后可删）。")


def render_users_admin_page() -> None:
    """
    用户管理页入口（规范 §5：侧边栏「👥 用户管理」）。

    **role gate 在函数入口**（§6-4）：未登录一律拦截；六角色口径（批次 4-N
    收口）：有效六角色集（users_db.effective_six_roles，与 app.py 页面可见性
    同源的单一实现）含 sys_admin 或 dict_admin 才放行 —— 账号生命周期是平台
    管理员（sys_admin）职能；词典管理员（dict_admin）作为管理侧过渡期兼判
    同样放行（legacy role=='admin' 账号经 LEGACY_ROLE_TO_NEW_ROLES 映射必然
    两位一体，升级前后行为逐字节一致）。页面内容不渲染 —— 权限不信任前端隐藏。

    批次 19：页面末尾（新建用户表单之后）追加「⚙️ 我的偏好」段
    （_render_my_preferences，user_profiles 个人键值读写，见其 docstring）。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录。")
        return
    if not ({"sys_admin", "dict_admin"} & effective_six_roles(me)):
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

    st.markdown("")
    _render_role_grant_panel(users, me)

    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<strong>安全提示</strong>"
        f"<p style='margin:6px 0 0 0;color:#4a5568;'>内置默认管理员 "
        f"admin 的初始密码为公开的 bootstrap 凭据，<strong>首次登录后必须立即修改</strong>；"
        f"停用用户只是禁止登录，其历史提交记录保留。</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("")
    _render_create_user_form(me)

    # 批次 19：页面末尾追加「⚙️ 我的偏好」（新建用户表单之后；账号页作为
    # app.render_users_admin_entry 的中段，其后还有范畴与工具段 —— 本段
    # 收在账号页自身末尾，不动 app.py 接线）。
    st.markdown("")
    _render_my_preferences()
