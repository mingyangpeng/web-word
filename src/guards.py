"""中央权限闸门 —— 数据出入口纪律（架构规范 §15）的 API 级落点。

页面层角色门（纵深防御第一层）之外，敏感写路径在**调用点**再过本闸门：
`require_dict_admin()` 从会话读当前用户并按六角色口径判定，不满足即抛
`PermissionError`（页面捕获转 st.error；脚本/测试显式传 actor 或 allow_system）。

批次 6-T 新增通用角色闸门 `require_role(actor, allowed, action)`：任意
「动作 → 允许角色集」的判定收口到此（users_admin_page 四写路径的首个
消费方），判定实现同样只此一份。

设计口径：
- 判定单一实现复用 `users_db.effective_six_roles`（legacy admin → dict_admin+sys_admin）；
- 传 `actor` dict 时按显式入参判定（测试可注入）；`allow_system=True` 供数据迁移
  等系统作业显式越过（调用点必须 docstring 注明理由）；
- 本模块**不读库**（会话/入参即判定），实时查库兜底由页面层 has_role 负责——
  两层叠加，闸门自身保持纯函数可测。

actor 语义口径表（RV13-1：全仓 ``actor`` 入参的两族语义，新增闸门前先对号入座）：

  * **系统作业面**（``actor=None`` 放行 = 系统作业；数据层直调面，页面调用点
    必须传会话用户，但迁移/定时脚本可传 None 自证系统身份）——既有三面：
    ``style_check.run_style_check``（None → run_by 落 NULL）、
    ``annotation_flow`` 家族（save_adjudication / reassign_assignment /
    create_reannotation_tasks 的 _require_assignment_actor）、
    ``broadcast_db`` 家族（require_role 读会话兜底面之外的系统脚本调用）；
  * **交互面**（页面调用点专用）：``require_dict_admin`` / ``require_role``
    （actor=None 时读 st.session_state，未登录拒绝）与新增
    ``require_role_interactive``（actor=None **直接拒绝**，不读会话——
    页面调用点必须显式传会话用户，防止「忘传 actor」被会话静默兜住）。

  纪律声明：**新增交互面闸门一律用 ``require_role_interactive``**；既有三面
  的 None=系统作业契约被各自测试钉死，不回溯改造。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

import streamlit as st

from src.users_db import effective_six_roles

# 角色中文名（require_role 拒绝文案用；与 users_admin_page.ROLE_LABELS 同口径，
# 本表只含六角色 —— guards 不依赖页面模块，单独维护这份只读小映射）。
_ROLE_LABELS = {
    "dict_admin": "词典管理员",
    "sys_admin": "平台管理员",
    "reviewer": "审核员",
    "editor": "撰写员",
    "annotator": "标注员",
    "viewer": "只读",
}


def require_dict_admin(actor: Any = None, *, allow_system: bool = False) -> dict:
    """要求当前（或显式给定）用户具备词典管理员角色，否则抛 PermissionError。

    Args:
        actor: 显式用户 dict（含 role/roles）；None 时读 st.session_state["user"]。
        allow_system: 系统作业显式越过（迁移脚本等；调用点 docstring 必须注明理由）。

    Returns:
        通过判定的用户 dict（便于调用方继续取 user id 落审计）。
    """
    if allow_system:
        return {"username": "__system__", "roles": ["dict_admin"]}
    user = actor if actor is not None else st.session_state.get("user")
    if not isinstance(user, dict):
        raise PermissionError("未登录：词典数据写操作仅词典管理员可执行。")
    roles = effective_six_roles(user)
    if "dict_admin" not in roles:
        raise PermissionError(
            "仅词典管理员（dict_admin）可执行词典数据写操作；如需权限请联系词典管理员授予。"
        )
    return user


def require_role(
    actor: Any = None,
    allowed: Optional[Iterable[str]] = None,
    action: str = "该操作",
) -> dict:
    """通用角色闸门：要求当前（或显式给定）用户的**有效六角色集**与 ``allowed``
    有交集，否则抛 PermissionError（批次 6-T：users_admin_page 四写路径的
    页面级判定收口到此，单一事实源 —— 页面只负责「动作 → 允许角色集」的
    口径映射，不再自带 effective 判定实现）。

    判定复用 ``users_db.effective_six_roles``（与 require_dict_admin 同一
    单一实现：legacy admin → dict_admin+sys_admin 两位一体，session roles
    快照逐名白名单校验）；``actor=None`` 时读 ``st.session_state["user"]``，
    传 actor dict 时按显式入参判定（测试可注入）。本模块不读库（会话/入参
    即判定），实时查库兜底由页面层 list_roles 负责 —— 两层叠加。

    Args:
        actor: 显式用户 dict（含 role/roles）；None 时读 st.session_state["user"]。
        allowed: 允许执行该动作的角色集合（六角色名）。**空/None 一律拒绝**
            （fail-closed：未配置允许角色的动作任何人都不可执行）。
        action: 动作名（拼进拒绝文案，页面 st.error 直出）。

    Returns:
        通过判定的用户 dict（便于调用方继续取 user id 落审计）。

    Raises:
        PermissionError: 未登录 / 有效角色集与 allowed 无交集（含 allowed 为空）。
    """
    allowed_set = {r for r in (allowed or ()) if isinstance(r, str) and r}
    user = actor if actor is not None else st.session_state.get("user")
    if not isinstance(user, dict):
        raise PermissionError(f"未登录：{action}需相应角色授权，请先登录。")
    if not allowed_set:
        raise PermissionError(f"{action}未配置允许角色，已拒绝（fail-closed）。")
    roles = effective_six_roles(user)
    if not (roles & allowed_set):
        names = "/".join(_ROLE_LABELS.get(r, r) for r in sorted(allowed_set))
        have = "/".join(sorted(roles)) if roles else "无有效角色"
        raise PermissionError(
            f"{action}仅{names}可执行；当前用户有效角色集（{have}）不满足，"
            "如需权限请联系管理员授予。"
        )
    return user


def require_role_interactive(
    actor: Any = None,
    allowed: Optional[Iterable[str]] = None,
    action: str = "该操作",
) -> dict:
    """交互面专用角色闸门：``actor=None`` **直接拒绝**（不读会话兜底）。

    与 ``require_role`` 的差别只有一点（RV13-1，additive 不改既有契约）：
    ``require_role`` 在 actor=None 时读 ``st.session_state["user"]`` 兜底，
    裸脚本/忘传 actor 的调用点会被「会话里恰好有用户」静默兜住；交互面闸门
    语义相反——页面调用点**必须显式传会话用户**（页面先经
    ``require_dict_admin()`` 等取到用户再传入），None 一律抛 PermissionError，
    把「忘传 actor」暴露成显式错误而非静默放行或静默兜底。

    其余判定（空 allowed fail-closed、有效六角色交集、拒绝文案、返回原
    actor 供落审计）与 ``require_role`` 逐字同一实现——本函数只做 None 前置
    拦截，判定不重复实现。

    适用：新增的页面交互面闸门一律用本函数（模块 docstring「actor 语义
    口径表」的纪律声明）；系统作业面（None=系统作业放行）的三面既有契约
    （style_check / annotation_flow / broadcast_db）不回溯改造。

    Args:
        actor: 会话用户 dict（页面调用点显式传入，含 role/roles）；None 直接
            拒绝（交互面语义：系统作业不走本闸门）。
        allowed: 允许执行该动作的角色集合（六角色名）。空/None 一律拒绝
            （fail-closed，同 require_role）。
        action: 动作名（拼进拒绝文案，页面 st.error 直出）。

    Returns:
        通过判定的用户 dict（即传入的 actor，便于调用方取 user id 落审计）。

    Raises:
        PermissionError: actor 为 None（交互面未传会话用户）/ 非 dict /
            有效角色集与 allowed 无交集（含 allowed 为空）。
    """
    if actor is None:
        raise PermissionError(
            f"{action}为页面交互操作，须以登录会话用户执行（actor 未传 —— "
            "交互面调用点必须显式传会话用户；None=系统作业，不走本闸门）。"
        )
    return require_role(actor, allowed=allowed, action=action)
