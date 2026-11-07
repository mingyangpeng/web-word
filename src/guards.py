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
