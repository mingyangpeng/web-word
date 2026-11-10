import sys
import os
# 确保项目根目录在 sys.path 中，使 from src.xxx 导入正常工作
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import json
import datetime
import logging

logger = logging.getLogger(__name__)

# Backend integration imports
from src.mysql_db import (
    init_database, get_stats, get_hot_verbs, get_feedback_data,
    insert_feedback, get_definition_by_verb, insert_definition,
    log_usage, get_synonyms, get_cluster_graph, get_cluster_graph_by_id,
    get_full_word_graph, get_senses, get_oald_senses,
    get_corpus_overview, get_corpus_word_stats, get_corpus_schema_scores,
    get_corpus_schema_evidence, corpus_dataset_ready,
    get_annotation_progress, update_sense_annotation, get_annotation_export_rows,
    update_collocation_annotations, count_feedbacks, cache_scope_key,
    domain_family_ready, get_domain_family_overview, get_domain_family_senses,
    get_domain_family_examples, get_db_cursor,
)
from src.graph_export import ensure_graph_html, ensure_cluster_html
from src.page_guides import PAGE_KEYS, page_label, render_page_usage_guide
from src.help_center import render_help_center_page
from src.dict_admin_pages import render_dict_admin_page
from src.writing_pages import render_writing_page
from src.lexical_pages import render_lexical_page
from src.model_settings_pages import render_model_settings_page
from src.collab_pages import _can_adjudicate_inbox, pending_inbox_count, render_collab_page
from src import ui_kit  # RV12-2：一次性提示统一收口（main() 每轮渲染弹出）
from html import escape as _html_escape
from typing import Callable, Optional, Dict, List, Any, Tuple
from src.llm_api import get_definition, get_fallback_definition
from src.security import InputValidator, sanitize_csv_dataframe

# ============================================
# 多人标注系统集成导入（设计规范 §3 模块契约 / §5 UI 集成契约）
# ============================================
from src.users_db import (
    MIN_PASSWORD_LENGTH,
    NEW_ROLES,
    change_password,
    effective_six_roles,
    ensure_user_tables,
    get_user_role,
    is_using_default_password,
    list_roles,
    list_users,
    needs_password_change,
    verify_login,
    verify_login_full,
)
# 词形还原数据层（与上述导入同区，沿用本文件 sys.path 前置的既定导入模式）
from src.wordforms_db import ensure_wordforms_tables, resolve_form  # noqa: E402
# R6-4：_current_user 单一实现点在 src/db_utils.py（别名导入，调用点零变化；
# 行为与旧本地副本逐字节一致 —— fail-closed，user 非 dict 即 None）。
# as_int（FX-27）：查询归因 user_id 的入参清洗（bool/非整值 → None，不冒充 id）。
from src.db_utils import as_int, current_user as _current_user  # noqa: E402
from src.annotation_flow import (
    ensure_flow_tables, submit_annotation, get_my_submissions,
    get_submissions_for_sense, detect_disagreements, save_adjudication,
    get_assignment_stats, STATUS_ADJUDICATED,
)
from src.reliability import render_reliability_page
from src.cluster_analysis import render_semantic_analysis_page
from src.template_engine import render_template_page
from src.semantic_search import render_semantic_search_page
from src.users_admin_page import render_users_admin_page, ROLE_LABELS, ROLE_BADGE_COLORS
from src.category_pack import CATEGORIES, load_pack
# FX-29 工具页面接线（架构 §4/§9「页面经中央注册表调工具」）：导入内置工具包
# 即把 ToolSpec 注册进中央注册表；页面按 tool_id 经 get_tool 取工具调 run()
# （薄包装 —— merge_params 合并 params_schema 默认值后委托原数据层函数，行为
# 与直调逐字节一致；run 不查 enabled 位，启用位是界面开关语义，FX-18）。
from src.tools.registry import get_tool
from src.tools.builtin import corpus_evidence_tool  # noqa: F401  导入即注册

# ============================================
# 设计系统导入
# ============================================
from src.design_system import (
    HEADER_H1, HEADER_H2, HEADER_H3,
    BODY_BASE,
    SUCCESS_COLOR,
    BACKGROUND_COLOR,
    SPACE_SM, SPACE_LG,
    get_card_style,
    get_section_spacing, get_badge_style, hex_to_rgba
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
# Session State 初始化
# ============================================
# 卡片展开/折叠状态管理
if 'card_expanded' not in st.session_state:
    st.session_state.card_expanded = {
        'prototype': True,
        'anchor': True,
        'core': True,
        'example': True
    }

# 侧边栏折叠状态标志（D-02，与 initial_sidebar_state="expanded" 一致，默认展开）
if 'sidebar_collapsed' not in st.session_state:
    st.session_state.sidebar_collapsed = False

# ============================================
# 数据库初始化（连接失败时降级为无数据库模式）
# ============================================
# R5-1（P1）单例守卫：init_database() 是全量 DDL（建表 + 迁移 + 视图 + 保留期
# 清理），此前无守卫、每次 rerun 都重跑一遍 —— 每个会话的每轮交互都白付几十条
# DDL 往返。现仿下方 `_user_tables_ready` 的 session 旗标模式：每个会话只跑一次，
# 判定结果（DB_AVAILABLE）一并入会话；DB_AVAILABLE 的取值语义不变（成功 True /
# 失败或异常 False），只是不再每轮重算。跨会话不共享 —— 故意不做成进程级单例：
# db_down 类测试各自独立会话，进程级缓存会把上一次的判定串进下一个会话。
DB_AVAILABLE = False
if st.session_state.get("_init_db_done"):
    DB_AVAILABLE = bool(st.session_state.get("_db_available", False))
else:
    try:
        # Initialize MySQL database
        if init_database():
            DB_AVAILABLE = True   # 连接成功保持静默：健康是默认态，状态看侧边栏底部圆点
        else:
            st.warning("⚠️ MySQL 数据库不可用，使用离线模式")
    except Exception as e:
        # RV4-6：异常细节（可能含 MySQL 主机/账号/库名等 DB 信息）只进服务端
        # 日志，页面向用户展示不含插值细节的通用文案。
        logger.error(f"数据库初始化失败，转入离线模式: {e}")
        st.warning("⚠️ 数据库初始化失败，已转入离线模式（详情见服务端日志）")
    st.session_state["_init_db_done"] = True
    st.session_state["_db_available"] = DB_AVAILABLE

# 多人标注系统：登录数据层（users 表 + 内置 admin，幂等建表，规范 §5/§6-5）。
# 每会话只跑一次（session_state 旗标）；失败只记日志不崩，登录框照常渲染。
if DB_AVAILABLE and not st.session_state.get("_user_tables_ready"):
    try:
        ensure_user_tables()
        st.session_state["_user_tables_ready"] = True
    except Exception as e:
        logger.error(f"ensure_user_tables 失败（登录功能可能不可用）: {e}")

# 词形还原索引（批次 3 ③）：wordforms 表幂等建表，供搜索页 resolve_form 前置
# 查询使用。建表失败不拦启动 —— resolve_form 自身 fail-closed 返回 []，
# 搜索页词形提示静默跳过（搜词主链路不受影响）。
if DB_AVAILABLE and not st.session_state.get("_wordforms_table_ready"):
    try:
        ensure_wordforms_tables()
        st.session_state["_wordforms_table_ready"] = True
    except Exception as e:
        logger.error(f"ensure_wordforms_tables 失败（词形还原可能不可用）: {e}")


# ============================================
# 登录态与页面权限（多人标注系统集成；规范 §1 角色语义 / §6-4 入口判定）
# ============================================
# _current_user 已收敛至 src/db_utils.current_user（R6-4 单一实现点，
# 文件头部别名导入）—— 本模块不再留本地副本。


def require_login() -> Optional[Dict[str, Any]]:
    """登录门（main() 分派处调用，规范 §6-4）。

    Returns:
        dict | None: 已登录返回用户 dict；未登录渲染 st.warning「请先登录」
        并返回 None —— 调用方据此 return，页面内容不渲染。
    """
    user = _current_user()
    if user is None:
        st.warning("请先登录")
    return user


# 会话键：标记「该会话经登录表单真实鉴权建立」。只有带标记的会话才做
# 每次操作的角色/停用实时回查（R1-P2b）与默认口令横幅（R1-P2c）——
# 测试或工具直接注入 session_state["user"] 的会话无标记，行为与旧版一致。
_USER_DB_BACKED_KEY = "_user_db_backed"

# 登出白名单（R1-6）：退出登录时**保留**的会话键 —— 只留四类基建键：
#   * 幂等建表就绪旗标（_user_tables_ready / _wordforms_table_ready：
#     每会话只跑一次的启动优化，与登录态无关，清了只是下轮重跑一次）；
#   * 侧边栏折叠偏好（sidebar_collapsed：UI 偏好，非用户数据）；
#   * 数据库初始化单例旗标（_init_db_done / _db_available：R5-1 会话级
#     守卫，init_database() 是全量 DDL —— RV12-4 补入，此前漏了这两个键，
#     每次登出都会把旗标清掉、下一轮重付一遍几十条 DDL 往返）。
# 其余键全部 pop（遍历 keys() 快照）—— 业务键（verb_result / show_result /
# card_expanded / _display_def_cache / page / hot_filter 等）与登录态键
# （user / _user_db_backed）登出即清：上一用户的查询结果、卡片展开态、
# 残留页不得泄漏给共享终端的下一使用者（R1-6 全清口径）。
_LOGOUT_KEEP_KEYS = frozenset({
    "_user_tables_ready",
    "_wordforms_table_ready",
    "sidebar_collapsed",
    "_init_db_done",
    "_db_available",
})

# 一次性登出提示旗标（R1-6 全清配套；_logout 落、main() pop 即消费）
_LOGOUT_FLASH_KEY = "_logout_flash"


def _logout() -> None:
    """退出登录：会话**全清**＋启动白名单（R1-6；规范 §6-5 不做 cookie 持久化）。

    旧实现只 pop user/_user_db_backed 两个键，业务键（查询结果 verb_result /
    show_result、卡片展开态 card_expanded、释义缓存 _display_def_cache、
    残留页 page、热门筛选 hot_filter）跨登出存活 —— 共享终端下下一使用者
    可见上一用户的工作痕迹。现改为遍历 st.session_state.keys() 快照全清，
    仅保留 _LOGOUT_KEEP_KEYS 三类基建键。

    全清后本就不存在「残留受保护页」可供下一轮登录门拦截，退出动作改为
    显式落一个一次性提示旗标（_LOGOUT_FLASH_KEY，main() 下一轮 pop 即
    消费转 st.warning「…请先登录…」）—— 与旧版「残留页登出门提示请先
    登录」同一用户可见语义（集成断言锁定），只是提示不再依赖残留页。
    """
    # 续接点落盘（FX-29/FX-31 对接：上次位置=上次登出时所在页；写库失败
    # fail-open 不阻断登出——续接点是便利不是承诺）
    try:
        from src.user_context_db import upsert_state

        _page = st.session_state.get("page")
        if isinstance(_page, str) and _page in PAGE_KEYS:
            upsert_state("resume_page", _page)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"登出续接点落盘失败（忽略）: {e}")
    for key in list(st.session_state.keys()):
        if key not in _LOGOUT_KEEP_KEYS:
            st.session_state.pop(key)
    st.session_state[_LOGOUT_FLASH_KEY] = True


def _users_table_reachable() -> bool:
    """users 表可达性探针（R4-4）：区分「账号已停用/删除」与「服务暂不可用」。

    get_user_role 把「查无此人/已停用」与「库读不出来」都折叠成 None（fail-closed
    契约不变），但两者的用户提示应当不同 —— 断库时登出提示若仍说「账号已被停用
    或删除」会误导用户去猜账号问题。本探针只发一条最小查询（不取数、不校验角色），
    异常即视为服务暂不可用。仅 DB_AVAILABLE 且会话回查失败时调用，不在正常路径上。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1 FROM users LIMIT 1")
            cursor.fetchone()
        return True
    except Exception as e:
        logger.warning(f"users 表可达性探针失败（按服务暂不可用处理）: {e}")
        return False


def _refresh_session_user() -> Optional[Dict[str, Any]]:
    """会话角色防陈旧（R1-P2b）：每次 rerun 对真实登录会话回查 users 表。

    登录快照（st.session_state["user"]）只用于侧边栏显示；权限判定以本函数
    刷新后的角色为准。在 render_sidebar 顶部调用 —— 它先于 main() 的页面
    分派执行，因此三个受保护页（标注/用户管理/信度）入口拿到的都是当次
    实时角色；任意页面（含基础页）的下次操作都会触发本检查，停用用户即被
    登出并提示。

    规则：
      * 用户已被停用 / 删除（get_user_role 返回 None）→ 清会话 + st.warning
        提示（fail-closed：数据库暂时读不出来时同样登出，不留旧权限会话）；
      * 旧角色列或六角色列表已变更 → 就地更新快照，管理员改角色/授予撤销
        （users_admin 角色授予面板）立即生效 —— 六角色会话（批次 3）下
        _visible_page_keys 读的 roles 快照与 legacy role 一同回查；
      * 数据库离线（DB_AVAILABLE=False）→ 跳过回查保留旧快照（此时全部
        写路径不可用，页面各自降级，见各页 DB_AVAILABLE 分支）。

    Returns:
        dict | None: 刷新后的会话用户；未登录或会话已被登出返回 None。
    """
    user = _current_user()
    if user is None or not st.session_state.get(_USER_DB_BACKED_KEY):
        return user
    if not DB_AVAILABLE:
        return user
    uid = int(user.get("id") or 0)
    fresh_role = get_user_role(uid)
    if fresh_role is None:
        # 停用 / 删除 / 库暂时不可读：登出并提示，下次操作即生效。
        # R4-4：提示语分流 —— users 表探针可达才说「停用或删除」；
        # 探针失败说明是服务端暂时不可用，如实告知账号状态无法核实，
        # 避免误导用户排查账号问题（登出动作 fail-closed 不变）。
        _logout()
        if _users_table_reachable():
            st.warning("⛔ 账号已被停用或删除，会话已失效，请重新登录。")
        else:
            st.warning("⚠️ 账号状态暂无法核实（服务暂不可用），已登出；"
                       "服务恢复后请重新登录。")
        return None
    # 六角色快照回查（list_roles fail-closed：读不出来返回 []，与停用登出
    # 的口径由 get_user_role 先行兜底，不会把正常在线用户误登出）
    fresh_roles = list_roles(uid)
    if fresh_role != user.get("role") or \
            list(fresh_roles) != list(user.get("roles") or []):
        # 角色变更：快照仅用于显示，权限判定随本次入口检查即用新值
        refreshed = dict(user)
        refreshed["role"] = fresh_role
        refreshed["roles"] = list(fresh_roles)
        st.session_state["user"] = refreshed
        return refreshed
    return user


# ============================================
# 页面权限（批次 3 六角色口径；平台架构设计规范 §8 / 施工规范 §6-K）
# ============================================
# 页面允许集的**权威表** `_PAGE_ACCESS_SIX`：值用六角色名（dict_admin=词典管理员、
# sys_admin=平台管理员、reviewer=审校、editor=撰写、annotator=标注、viewer=只读；
# user_roles 一人多角色，新号默认 viewer，语义见 src/users_db.py）。
# 口径变化相对旧四角色表：admin 拆为 dict_admin/sys_admin 两闸 —— 用户管理
# （账号生命周期）归平台管理员 sys_admin；词典管理区归词典管理员 dict_admin；
# submission/标注类按「annotator 及以上」并入 editor（平台架构设计规范 §8
# 任务×角色矩阵：撰写→editor+）。其余既有键可见性与升级前逐角色一致。
#
# 为什么另立 `_PAGE_ACCESS_SIX` 而不是直接改写 `_PAGE_ACCESS` 的值：
# legacy 四角色表保留为六角色表的**投影别名**（dict_admin/sys_admin→admin、
# editor→annotator 折叠回旧域，见 _SIX_TO_LEGACY_DOMAIN），键集、逐角色可见性
# 与升级前逐字节一致，旧调用方继续读 `_PAGE_ACCESS` 不破。批次 4-N 收编后
# tests/test_page_guides.py 的 test_page_access_table_consistent_with_registration
# 对两表做双检：_PAGE_ACCESS_SIX 值域 ⊆ 六角色名（拼写漂移哨兵——未知角色折叠
# 后仍会原样出现在投影里，照样被它拦下）＋ legacy 表恰为六角色表的投影。
_PAGE_ACCESS_SIX: Dict[str, tuple] = {
    "submission": ("dict_admin", "sys_admin", "reviewer", "editor", "annotator"),
    "users_admin": ("sys_admin",),
    "reliability": ("dict_admin", "sys_admin", "reviewer"),
    "cluster": NEW_ROLES,
    "template": NEW_ROLES,
    "semantic": NEW_ROLES,
    "dict_admin": ("dict_admin",),
    "ai_hub": NEW_ROLES,
    "writing": NEW_ROLES,
    "lexical": ("dict_admin", "reviewer", "editor"),
    "model_settings": ("dict_admin",),
}

# 六角色 → legacy 页面权限域的折叠（投影用）：两位一体的旧 admin、
# editor 不低于 annotator 的可见域。
_SIX_TO_LEGACY_DOMAIN: Dict[str, str] = {
    "dict_admin": "admin",
    "sys_admin": "admin",
    "editor": "annotator",
}

# legacy 四角色口径别名表（由 _PAGE_ACCESS_SIX 投影派生，勿手工编辑；
# tests/test_page_guides.py 钉死其键集与值域）。不在表中的键为基础页，
# 所有角色（含未登录）可见，未授权访问由各页渲染入口的 role gate 拦下。
_PAGE_ACCESS: Dict[str, tuple] = {
    key: tuple(sorted(
        {_SIX_TO_LEGACY_DOMAIN.get(role, role) for role in roles}
    ))
    for key, roles in _PAGE_ACCESS_SIX.items()
}


# 批次 4-N 六角色收口：批次 3 ② 的本地折算实现（legacy role 映射 ∪ session
# roles，含 fail-closed 忽略非法角色名）整体迁入 users_db.effective_six_roles
# —— 页面可见性（本文件）、users_admin 页面体角色门与提权硬闸门自此同源调用
# 同一实现，不再各自折算。此处保留模块级别名（非复制 def），_visible_page_keys
# 与既有导入方的调用点行为逐字节不变。
_effective_six_roles = effective_six_roles


def _visible_page_keys(user: Optional[Dict[str, Any]]) -> List[str]:
    """PAGE_KEYS 的角色可见性过滤（选项仍以 PAGE_KEYS 为单一事实来源）。

    批次 3 六角色口径：页面允许集读 _PAGE_ACCESS_SIX（值=六角色名），用户
    有效角色集见 _effective_six_roles（legacy role ∪ session roles），页面
    允许集命中任一角色即可见。基础五页与帮助中心不在表中 → 所有人可见
    （未授权访问由各页渲染入口的 role gate 拦下）；未登录或角色不符的键
    不出现在侧边栏 radio 里。
    签名说明：旧版按 role 字符串过滤，本轮改为接收会话 user dict（roles
    感知），唯一调用点 render_sidebar 同步更新。
    """
    keys: List[str] = []
    effective = _effective_six_roles(user)
    for key in PAGE_KEYS:
        allowed = _PAGE_ACCESS_SIX.get(key)
        if allowed is None or (effective and set(allowed) & effective):
            keys.append(key)
    return keys


# ============================================
# 侧边栏七区菜单分组（规范②组「七区菜单分组」；docs/使用说明书.md §四 界面导览口径）
# ============================================
# 分组只改**呈现**，不改权限：可见集仍由 _visible_page_keys 按六角色权限表
# 过滤（上文，单一事实来源），这里只定义 ——
#   * 区序（组间按本表顺序，组内稳定保持 PAGE_KEYS 相对序，见 _group_keys_by_zone）；
#   * 区名前缀（radio 选项标签 = 【区名】+ page_label，页名仍与使用说明同源）。
# 归区照实（不迁就分区改权限门）：
#   * semantic（以句搜义）按文档口径归「查阅展示」区，但权限在 _PAGE_ACCESS_SIX
#     （NEW_ROLES，登录可见）—— 未登录侧边栏不出现，页面层登录门不变；
#   * model_settings 权限门仅 dict_admin，照实归「词典管理」区；
#   * help 帮助中心不计权限表（全员可见的兜底路由页），照实归「系统管理」区尾 ——
#     未登录也会随可见集出现在该区（帮助中心入口保持可达）；
#   * annotate 标注平台是基础页（权限表外，页面层 require_login 拦未登录），
#     照实归「语义建模」区 —— 未登录仍出现在侧边栏（现状口径，点击见「请先登录」）。
_SIDEBAR_ZONES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("🔍 查阅展示", ("search", "graph", "corpus", "domain", "semantic")),
    ("🏷️ 语义建模", ("annotate", "submission", "reliability")),
    ("📊 语义分析", ("cluster",)),
    ("✍️ 编纂产出", ("template", "writing", "lexical")),
    ("🤖 AI 协作", ("ai_hub",)),
    ("📖 词典管理", ("dict_admin", "model_settings")),
    ("🔧 系统管理", ("users_admin", "help")),
)

# 区名前缀（radio 选项标签用）：选项按七区连续排列后，区名前缀成块出现即分组
# 标题（「单 radio 选项加分区前缀」方案 —— 无多 radio 的 key 冲突/多选残留，
# 无 rerun 环路，key="page" 路由契约不变）。漏配区的键无前缀（防御未知页）。
_PAGE_ZONE_PREFIX: Dict[str, str] = {
    key: f"【{zone}】"
    for zone, zone_keys in _SIDEBAR_ZONES
    for key in zone_keys
}

# 区序号（重排用）：未知键取 len(_SIDEBAR_ZONES)，稳定沉到列表尾。
_ZONE_ORDER: Dict[str, int] = {
    key: i
    for i, (_zone, zone_keys) in enumerate(_SIDEBAR_ZONES)
    for key in zone_keys
}


def _group_keys_by_zone(keys: List[str]) -> List[str]:
    """把可见页键按七区重排（组间按 _SIDEBAR_ZONES 序，组内稳定保持原序）。

    只重排不改键集：sorted 稳定，组内相对序与漏配区键（沉尾）的相对序都
    保持入参顺序；session_state["page"] 的键集契约（PAGE_KEYS 17 键）不受影响。
    """
    return sorted(keys, key=lambda k: (_ZONE_ORDER.get(k, len(_ZONE_ORDER)),))


def sidebar_option_label(page_key: str) -> str:
    """侧边栏 radio 选项标签：七区名前缀 ＋ page_label（页名与使用说明同源）。

    分组呈现走「单 radio 选项加分区前缀」：format_func 组合区名前缀与
    page_label，不复制页名文案；未登记区的键原样返回 page_label（防御）。
    """
    return f"{_PAGE_ZONE_PREFIX.get(page_key, '')}{page_label(page_key)}"


def _ensure_flow_tables_once() -> None:
    """首次进入提交流/仲裁面板时幂等创建 flow 三表（规范：无需手跑迁移）。

    annotation_submissions 等表带 users/oald_senses 外键，因此必须在
    ensure_user_tables（启动时已调）与 init_database（oald_senses）之后执行。
    """
    if not DB_AVAILABLE or st.session_state.get("_flow_tables_ready"):
        return
    try:
        ensure_flow_tables()
        st.session_state["_flow_tables_ready"] = True
    except Exception as e:
        logger.error(f"ensure_flow_tables 失败（提交流可能不可用）: {e}")

# ============================================
# Sticky 搜索栏：Google 风格样式
# ============================================
# 实现说明（2026-09-15 修复）：
#   1. Streamlit 会把每个 st.markdown 渲染成独立的兄弟节点，所以
#      "<div class=...>" 无法包住后面的 st.text_input —— 以前的写法里输入框
#      始终在容器之外，CSS 从未生效。
#   2. 现在改用 st.container(key="search_bar")：Streamlit 会为容器生成稳定的
#      .st-key-search_bar class，输入框真正位于该容器内部。
#   3. sticky 必须落在 wrapper（[data-testid="stLayoutWrapper"]）上而不是容器
#      本身：容器的高度等于自身内容，没有滚动行程；wrapper 的父级
#      stVerticalBlock 才是整页高度，sticky 才能一路吸顶。
#   4. 外观（背景/内边距/圆角/边框）只放在容器上，wrapper 只负责定位，
#      否则两层各加一次内边距，搜索栏会明显变高。
#   5. 背景色通过 hex_to_rgba 转换：CSS 不接受 rgba() 里写十六进制，
#      rgba(#ffffff, 0.98) 是非法值，浏览器会整条丢弃。
#   6. 吸顶偏移必须让开 Streamlit 顶栏：stHeader 是常驻的 absolute 元素
#      （高度 60px、z-index 999990，内含 Deploy 与菜单按钮）。用 top:1rem(16px)
#      会让搜索栏有 44px 压在顶栏下面、输入框完全不可点。这里用 4.5rem
#      （72px = 60px 顶栏 + 12px 间隙）让搜索栏停在顶栏下方。
#      不要改成把 z-index 提到顶栏之上——那会反过来盖住 Deploy 按钮。
STICKY_SEARCH_BAR_TOP = "4.5rem"
st.markdown(f"""
<style>
/* 外观：容器本身（不支持 :has() 的浏览器也能看到样式，只是不吸顶） */
.st-key-search_bar {{
    background: {hex_to_rgba(BACKGROUND_COLOR, 0.98)};
    /* RV1-3/RV1-11：搜索栏是常亮浅色面（近白 0.98），暗色主题下容器内的
       输入文字会继承主题白字（浅底白字 ≈1:1 不可读）。容器整体钉死深字，
       输入框/占位符单独立规则，两种主题都可读。 */
    color: #1a202c;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    padding: {SPACE_SM}px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1), 0 1px 3px rgba(0, 0, 0, 0.08);
    border: 1px solid rgba(226, 232, 240, 0.5);
}}
.st-key-search_bar input, .st-key-search_bar textarea {{
    color: #1a202c;
    -webkit-text-fill-color: #1a202c;
}}
.st-key-search_bar input::placeholder {{
    color: #4a5568;
    opacity: 1;
}}

/* 定位：容器的 wrapper 一直贴在 Streamlit 顶栏下方，方便随时切换搜索的单词 */
[data-testid="stLayoutWrapper"]:has(> .st-key-search_bar) {{
    position: sticky;
    top: {STICKY_SEARCH_BAR_TOP};
    z-index: 1000;
    margin-bottom: {SPACE_LG}px;
}}
</style>
""", unsafe_allow_html=True)

# ============================================
# 卡片头样式：把折叠按钮做成渐变标题条
# ============================================
# render_card_header 用真实的 st.button 实现折叠（可点、有状态），
# 这里把它还原成旧版视觉：全宽、渐变背景、白字。
# 按钮 label 形如 "🧬|原型与位移事件分析|▼"，本样式只做外观，不改行为。
st.markdown("""
<style>
/* RV1-12（P3）：折叠按钮渐变旧值 #667eea（白字实测 3.66:1）不达 AA——
   两个渐变端点换深档紫：常态 #553c9a（白字 8.40:1）→ #6b46c1（白字 6.42:1），
   悬停再加深一档（9.31:1 / 8.23:1），全部 ≥4.5:1。 */
[class*="st-key-card_toggle_"] button {
    width: 100%;
    justify-content: flex-start;
    padding: 16px;
    background: linear-gradient(135deg, #553c9a 0%, #6b46c1 100%);
    color: #ffffff;
    border: none;
    border-radius: 8px 8px 0 0;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}
[class*="st-key-card_toggle_"] button:hover {
    background: linear-gradient(135deg, #4c3a86 0%, #5b3d96 100%);
    color: #ffffff;
    border: none;
}
[class*="st-key-card_toggle_"] button p {
    font-weight: 600;
    font-size: 1.05em;
    color: #ffffff;
}

/* 卡片正文容器。
   这里用带 key 的容器 + CSS，而不是 st.markdown(get_card_style())：
   后者只是把 CSS **文本**当成 markdown 渲染出来，页面上会出现 5 段
   「background-color: #f7fafc; padding: 24px; ...」的原始文字（实测可见），
   而且那对 <div>/</div> 也没有真的包住任何东西 —— Streamlit 把每次
   st.markdown 渲染成独立兄弟节点，HTML 无法跨调用闭合。
   与搜索栏（.st-key-search_bar）是同一个模式，见文件顶部说明。
   RV1-3：卡底是常亮浅色面（#f7fafc），暗色主题下未显式声明颜色的正文
   会继承主题白字（浅底白字 ≈1:1 不可读）—— 容器统一钉死深字。 */
[class*="st-key-card_body_"] {
    background-color: #f7fafc;
    color: #1a202c;
    padding: 0;
    border: 1px solid #e2e8f0;
    border-top: none;
    border-radius: 0 0 8px 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}
</style>
""", unsafe_allow_html=True)

# ============================================
# 核心理论说明
# ============================================
THEORY_DESCRIPTION = """
### 📚 理论背景

**运动事件类型学（Talmy, 1985）**
运动事件可分为两类：
1. **波浪型（Wave-like）**：强调方式
2. **矢量型（Vector-like）**：强调路径+方向

**词典释义优化**
传统释义往往以「路径+方向」为核心，而实际使用中更强调**运动方式**和**身体姿态**。
通过显式分解【方式】【路径】【方向】【体相】【范围】五个语义要素，可以：
- 更准确地捕捉运动语义
- 提供更丰富的表达层次
- 支持更精细的语义搜索

---

**【方式】**：运动采用的姿势/手段
**【路径】**：运动经过的空间轨迹
**【方向】**：运动朝向的终点/目标
**【体相】**：运动时身体的姿态/状态
**【范围】**：运动的范围/程度
"""

# ============================================
# 搜索函数：带 300ms 防抖延迟
# ============================================
def _record_query(verb: str) -> None:
    """
    记录一次真实查询到 usage_logs 表。

    这是「查询次数」与「热门动词」两个统计口径的唯一数据来源 ——
    修正前 log_usage() 虽然早已实现，但应用从未调用过，导致侧边栏的
    「总查询次数」实为已收录词目数、「热门查询动词」实为 definitions 表
    的物理顺序。现在每次用户提交搜索都记一笔。

    只应在「用户主动提交查询」处调用（搜索框回车 / 点击热门词 / 点击示例词），
    不要放进 get_display_definition() —— 那个函数每次渲染会被四张卡片各调一次，
    放在那里会把一次查询记成多次。

    FX-27 查询归因：登录态取当前用户 users.id 随查询写入（usage_logs.user_id，
    规范②组归因留痕）；未登录传 None —— 列值即 NULL（RV2-3 留痕列第 1 类口径：
    未登录 = NULL，不用 0 冒充）。id 经 as_int 清洗（bool/脏值 → None，不把
    伪 id 写进库）。

    失败只记日志，绝不影响界面。
    """
    if not DB_AVAILABLE or not verb:
        return
    user = _current_user()
    user_id = as_int(user.get("id")) if user else None
    try:
        log_usage(str(verb)[:100], user_id=user_id)
    except Exception as e:
        logger.error(f"查询日志写入失败 for '{verb}': {e}")


def search_verb() -> None:
    """on_change 回调：当搜索框值变化时触发搜索。"""
    value = st.session_state.get("搜索动词", "")
    if value and 1 <= len(value) <= 50:
        st.session_state.verb_result = value
        st.session_state.show_result = True
        st.session_state["page"] = "search"  # 从图谱页发起搜索时切回搜索页
        _record_query(value)
        _resolve_wordform_hint(value)  # 词形还原前置查询（批次 3 ③）


def select_example_verb(verb: str) -> None:
    """点击示例库 / 热门动词时触发搜索。"""
    st.session_state.verb_result = verb
    st.session_state.show_result = True
    st.session_state["搜索动词"] = verb
    st.session_state["page"] = "search"  # 从图谱页点热门词时切回搜索页
    _record_query(verb)
    _resolve_wordform_hint(verb)  # 词形还原前置查询（批次 3 ③）


# ============================================
# 词形还原提示（批次 3 ③：wordforms_db.resolve_form 前置查询）
# ============================================
# 查询词命中 wordforms（拼音/屈折/异体词形）且还原出的词目与查询词不同时，
# 在搜索页给出一行「词形「X」→ 词目「Y」」提示与一键切换查询按钮；
# DB 不可用 / 表缺失 / 无命中时静默跳过，搜词主链路（所见即所得的六卡片
# 结果结构）不变。提示只在会话里暂存，不进库。
_WORDFORM_HINT_KEY = "_wordform_hint"


def _resolve_wordform_hint(query: str) -> None:
    """查询词词形还原（search_verb 链路入口处调用）：记录或清除提示信息。

    Args:
        query: 本次提交的查询词（调用方已保证非空、1–50 字符）。

    行为：
      * 先清掉旧提示（每次新查询重新判定，不残留）；
      * DB 不可用直接跳过；resolve_form 自身 fail-closed（表缺失/查询失败
        返回 []），这里再兜一层异常防线；
      * 命中行里取第一条 lemma_word ≠ 查询词 的记录写入会话
        （同形多词目时取库序第一条，交由词形表灌库顺序决定）；
      * 全部命中的词目都与查询词相同（查的就是词目本身）→ 不提示。
    """
    st.session_state.pop(_WORDFORM_HINT_KEY, None)
    if not DB_AVAILABLE or not query:
        return
    try:
        hits = resolve_form(str(query))
    except Exception as e:  # 防御：词形提示永不打断搜词主链路
        logger.error(f"词形还原查询失败 for '{query}': {e}")
        return
    for hit in hits:
        lemma = str(hit.get("lemma_word") or "")
        if lemma and lemma != query:
            st.session_state[_WORDFORM_HINT_KEY] = {"form": str(query), "lemma": lemma}
            return


def _switch_to_wordform_lemma(lemma: str) -> None:
    """词形提示的「切换到词目」回调：以还原出的词目重新发起一次等价查询。"""
    st.session_state.verb_result = lemma
    st.session_state.show_result = True
    st.session_state["搜索动词"] = lemma
    st.session_state["page"] = "search"
    _record_query(lemma)
    _resolve_wordform_hint(lemma)  # 词目本身若仍是词形（链式还原）则继续提示


def filter_hot_verbs(hot_verbs: List[dict], query: str) -> List[dict]:
    """对热门动词列表做前端子串过滤（D-05，确定性、无后端调用）。

    Args:
        hot_verbs: 已加载的热门动词列表（dict 含 'verb' 键）。
        query: 筛选关键字；为空或全空白时返回原列表。

    Returns:
        过滤后的新列表，仅保留 verb 含 query 子串（忽略大小写）的项。
    """
    if not query or not query.strip():
        return hot_verbs
    q = query.lower()
    return [v for v in hot_verbs if v.get("verb", "").lower().__contains__(q)]

# ============================================
# 语义表渲染函数
# ============================================
def render_semantic_table(semantic_data):
    """
    渲染语义分解表，带 emoji 和颜色编码。

    Args:
        semantic_data: 二维列表 [[类型, emoji, 描述], ...]

    Returns:
        HTML 格式的语义表
    """
    if not semantic_data:
        # RV1-6：占位文本旧用 #a0aec0（白底实测 2.26:1 不达 AA），换深档灰。
        return "<p style='color: #4a5568;'>暂无语义分解数据</p>"

    # RV1-9：td 统一补 overflow-wrap:anywhere，长释义/长串窄屏不再撑爆表格。
    html = '<table style="border-collapse: collapse; width: 100%; margin: 16px 0;">'

    # 表头
    html += '<thead style="background-color: #4a5568; color: white; font-weight: 600;">'
    html += '<tr>'
    html += '<th style="padding: 12px; text-align: left; border-bottom: 2px solid #e2e8f0; width: 25%;">类型</th>'
    html += '<th style="padding: 12px; text-align: left; border-bottom: 2px solid #e2e8f0; width: 20%;">标识</th>'
    html += '<th style="padding: 12px; text-align: left; border-bottom: 2px solid #e2e8f0; width: 55%;">描述</th>'
    html += '</tr></thead><tbody>'

    # 表格行
    for i, row in enumerate(semantic_data):
        semantic_type, emoji, description = row
        color = SEMANTIC_COLORS.get(semantic_type, {}).get("color", "#4a5568")

        # 奇偶行背景色
        bg_color = "#f7fafc" if i % 2 == 0 else "#ffffff"

        # 行内容来自 DB/LLM，渲染进 unsafe_allow_html=True 前必须转义
        stype, sdesc = _html_escape(str(semantic_type)), _html_escape(str(description))
        html += f'''
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 12px; color: {color}; font-weight: 500; overflow-wrap: anywhere;">{stype}</td>
            <td style="padding: 12px; font-size: 1.2em;">{emoji}</td>
            <td style="padding: 12px; color: #2d3748; overflow-wrap: anywhere;">{sdesc}</td>
        </tr>'''

    html += '</tbody></table>'
    return html

# ============================================
# 卡片渲染函数
# ============================================
def _toggle_card(card_key: str) -> None:
    """切换某张卡片的展开/折叠状态（供卡片头按钮的 on_click 调用）。"""
    st.session_state.card_expanded[card_key] = not st.session_state.card_expanded.get(card_key, True)


def render_card_header(card_key: str, title: str, icon: str) -> None:
    """
    渲染卡片头部（可点击的展开/折叠按钮）。

    修正历史缺陷：旧实现用 st.markdown 输出一段带 `cursor: pointer` 和 ▼/▶ 箭头的
    HTML，看起来能点，但既没有事件处理器、`card_expanded` 也从未被写入过 ——
    点击毫无反应。现在改用真正的 st.button，通过 on_click 回调写入
    session_state.card_expanded[card_key]，折叠/展开才真的生效。

    外观（渐变背景、圆角、箭头左右对齐）由文件顶部的 CSS 通过
    `[class*="st-key-card_toggle_"]` 前缀选择器还原，视觉与旧版一致。

    Args:
        card_key: card_expanded 中的键（prototype / anchor / core / example）
        title: 卡片标题
        icon: 图标
    """
    expanded = st.session_state.card_expanded.get(card_key, True)
    arrow = "▼" if expanded else "▶"
    st.button(
        f"{icon} {title} {arrow}",
        key=f"card_toggle_{card_key}",
        use_container_width=True,
        on_click=_toggle_card,
        args=(card_key,),
    )

def _mock_source_badge_html(verb: str) -> str:
    """R4-6（P3）：MOCK 兜底来源徽章（复用释义来源分级徽章样式）。

    当前释义解析自 MOCK_DEFINITIONS（离线兜底）时返回「内置示例（非词典数据）」
    徽章 HTML；DB/LLM 路径返回空串（不渲染）。颜色取来源分级的中间档琥珀深档
    （#9c4221，与「二手转写」同级警示；RV1-2 白字对比 6.53:1 达 AA，旧
    #dd6b20 仅 3.39:1），样式与 render_card_annotation 的释义来源徽章一致。
    """
    try:
        display = get_display_definition(verb)
    except Exception:
        return ""
    if display.get("source") != "内置示例":
        return ""
    badge = ('background-color: #9c4221; color: white; padding: 2px 10px; '
             'border-radius: 10px; font-size: 0.85em;')
    return ('<p style="color: #2d3748; margin: 0 0 12px 0;"><strong>释义来源：</strong>'
            f'<span style="{badge}">内置示例（非词典数据）</span></p>')


def render_card_prototype(verb):
    """
    渲染原型与位移事件分析卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    semantic_table = get_semantic_table_for_verb(verb)

    # RV1-7：卡片正文彩字全部换 AA 深档（旧 #667eea/#9f7aea/#48bb78/#ed8936
    # 在 #f7fafc 卡底实测 3.49/3.11/2.31/2.43:1 不达 4.5:1）。
    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #553c9a; font-weight: 600; margin: 0 0 16px 0;">🧬 原型与位移事件分析</h4>
    '''
    html += _mock_source_badge_html(verb)

    if semantic_table:
        html += ('<p style="color: #2d3748; margin-bottom: 12px;"><strong>动词:</strong> '
                 + _html_escape(str(verb)) + '</p>')
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>事件类型:</strong> 基于运动事件类型学的位移事件分析</p>'
        html += '<p style="color: #2d3748;"><strong>语义要素分解:</strong></p>'
        html += render_semantic_table(semantic_table)
    else:
        html += '<p style="color: #4a5568;">暂无详细的位移事件分析数据</p>'

    html += '</div>'
    return html

def render_card_annotation(verb):
    """
    渲染「义位标注」卡片。

    字段与取值全部来自 `docs/research/protocols/义项判定标准.docx`：

      * 原型层级 —— Y（核心）/EXT（拓展）/N（剔除）
      * 意象图式 —— 源点脱离 / 终点抵达 / 方式伴随 / 互动位移（四类，不可自增）
      * 英汉对齐 —— 完全对齐 / 部分对齐 / 零对齐
      * 汉语句法特征、译义转化策略 —— 配套字段

    卡片刻意把「来源」与「待复核」放在最显眼处：文档要求所有判定可回溯到 OALD 原文，
    而 dictionary.db 只覆盖了少数词，所以必须让使用者一眼看出这条是词典原文还是
    二手拼装、是已定稿还是候选值。
    """
    definition = get_definition_by_verb(verb) if DB_AVAILABLE else None
    # get_senses 查询失败返 None（R4-1）：义位明细表降级为不渲染，None 归一成 []
    senses = (get_senses(verb) or []) if DB_AVAILABLE else []

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #553c9a; font-weight: 600; margin: 0 0 16px 0;">🏷️ 义位标注</h4>
    '''

    if not definition:
        return html + '<p style="color: #4a5568;">暂无标注数据（数据库不可用或该词未收录）</p></div>'

    def field(label, value, color="#2d3748"):
        """义位卡单字段渲染：空值返回空串，非空转义后拼 HTML 行。"""
        if not value:
            return ""
        value = _html_escape(str(value))  # DB/LLM 文本进 unsafe_allow_html 前转义
        return (f'<p style="color: #2d3748; margin-bottom: 8px;">'
                f'<strong>{label}：</strong><span style="color: {color};">{value}</span></p>')

    html += field("词目主导义", definition.get("sense_brief"))
    html += field("Levin 来源子类", definition.get("levin_source"))
    html += field("原型层级", definition.get("prototype_level"), "#805ad5")
    html += field("意象图式", definition.get("image_schema"), "#2b6cb0")
    html += field("英汉对齐等级", definition.get("alignment"), "#9c4221")
    html += field("汉语句法特征", definition.get("cn_syntax"))
    html += field("译义转化策略", definition.get("translation_strategy"))
    html += field("判定依据", definition.get("judge_reason"))

    # 来源与复核状态 —— 文档要求可回溯，这两项必须显式呈现
    source = definition.get("definition_source") or "未知"
    rank = definition.get("source_rank")
    source_label = {
        "dictionary.db": "词典原文（OALD，可回溯）",
        "legacy-library": "既有词库（二手转写，非词典原文）",
        "levin-brief": "研究者标注的原型义（短语，非完整释义）",
        "oxford-en": "仅英文释义，中文待补",
        "pending": "暂无释义",
    }.get(source, source)
    # RV1-2：来源分级徽章底色换 AA 深档（旧 #38a169/#dd6b20/#e53e3e 白字
    # 实测 3.25/3.39/4.13:1 均不达 4.5:1）。
    badge_color = ("#276749" if rank == 1
                   else ("#9c4221" if rank and rank <= 2 else "#c53030"))
    html += (f'<p style="color: #2d3748; margin-bottom: 8px;"><strong>释义来源：</strong>'
             f'<span style="background-color: {badge_color}; color: white; padding: 2px 10px; '
             f'border-radius: 10px; font-size: 0.85em;">{source_label}</span></p>')

    if definition.get("needs_review"):
        html += ('<p style="color: #975a16; background-color: #fefcbf; padding: 8px 12px; '
                 'border-radius: 6px; font-size: 0.9em; margin-top: 12px;">'
                 '⚠️ 标注为规则推导的<b>候选值</b>，依《义项判定标准》需人工复核确认。</p>')

    # 义位明细表
    if senses:
        html += ('<p style="color: #2d3748; margin: 16px 0 8px 0;"><strong>义位明细（'
                 + str(len(senses)) + ' 条，分析单元为义位而非词目）:</strong></p>')
        html += '<table style="border-collapse: collapse; width: 100%; font-size: 0.9em;">'
        html += ('<thead style="background-color: #4a5568; color: white;">'
                 '<tr><th style="padding: 8px; text-align: left; width: 40px;">#</th>'
                 '<th style="padding: 8px; text-align: left; width: 70px;">层级</th>'
                 '<th style="padding: 8px; text-align: left;">释义</th>'
                 '<th style="padding: 8px; text-align: left; width: 90px;">对齐</th></tr></thead><tbody>')
        for i, sense in enumerate(senses):
            bg = "#f7fafc" if i % 2 == 0 else "#ffffff"
            level = sense.get("prototype_level") or "-"
            level_color = "#805ad5" if level == "Y" else "#4a5568"
            ch = sense.get("ch_ndef") or sense.get("en_ndef") or "（空）"
            html += (f'<tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0;">'
                     f'<td style="padding: 8px; color: #1a202c; overflow-wrap: anywhere;">{sense.get("sense_index", i + 1)}</td>'
                     f'<td style="padding: 8px; color: {level_color}; font-weight: 600; overflow-wrap: anywhere;">{level}</td>'
                     f'<td style="padding: 8px; color: #1a202c; overflow-wrap: anywhere;">{ch[:160]}</td>'
                     f'<td style="padding: 8px; color: #4a5568; overflow-wrap: anywhere;">{sense.get("alignment") or "-"}</td></tr>')
        html += '</tbody></table>'

    html += '</div>'
    return html


def render_card_anchor(verb):
    """
    渲染范畴锚定卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    # 数据来源：统一适配器（Phase 5, D-01）；返回 5 行 [[类型, emoji, 描述], ...]
    semantic_table = get_semantic_table_for_verb(verb)

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #276749; font-weight: 600; margin: 0 0 16px 0;">🎯 范畴锚定</h4>
    '''
    html += _mock_source_badge_html(verb)

    html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>所属范畴:</strong> 运动方式复合事件</p>'

    if semantic_table:
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>语义特征:</strong></p>'
        html += '<div style="display: flex; flex-wrap: wrap; gap: 8px;">'
        for row in semantic_table:
            semantic_type, emoji, description = row
            color = SEMANTIC_COLORS.get(semantic_type, {}).get("color", "#4a5568")
            html += f'<span style="background-color: {color}; color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.9em;">{emoji} {semantic_type}</span>'
        html += '</div>'
    else:
        html += '<p style="color: #4a5568;">暂无范畴锚定数据</p>'

    html += '</div>'
    return html

def render_card_core(verb):
    """
    渲染核心释义与多维辨异卡片。

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    # 数据来源：统一适配器（Phase 5, D-01）
    display = get_display_definition(verb)
    traditional = display.get("traditional", "")
    optimized = display.get("optimized", "")

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #9c4221; font-weight: 600; margin: 0 0 16px 0;">📚 核心释义与多维辨异</h4>
    '''
    html += _mock_source_badge_html(verb)

    if traditional:
        html += ('<div style="background-color: #edf2f7; color: #1a202c; '
                 'padding: 12px; border-radius: 8px; margin-bottom: 16px;">')
        html += '<h5 style="color: #2d3748; margin: 0 0 8px 0;">📋 传统释义</h5>'
        html += '<p style="color: #4a5568; margin: 0;">' + _html_escape(str(traditional)) + '</p>'
        html += '</div>'

    if optimized:
        html += ('<div style="background-color: #c6f6d5; color: #1a202c; '
                 'padding: 12px; border-radius: 8px;">')
        html += '<h5 style="color: #22543d; margin: 0 0 8px 0;">✅ 优化释义 (语义分解)</h5>'
        # RV1-7：正文彩字 #2f855a 在 #c6f6d5 浅绿底实测 3.79:1 不达，换 #22543d（7.30:1）。
        html += '<p style="color: #22543d; margin: 0;">' + _html_escape(str(optimized)) + '</p>'
        html += '</div>'

    html += '</div>'
    return html

def render_card_example(verb):
    """
    渲染图式示例卡片：真实例句 + 近义动词对比。

    修正历史缺陷：旧实现三条要点全是硬编码占位文案，其中一句还写死了
    "与类似动词"跑进来"的区别在于..." —— 无论查询哪个词都显示"跑进来"，
    对 155 词词库里的其它动词是明确错误的。现在改为：
      * 例句取自语料（LLM 生成的 example / 词库的 example_sentence）
      * 近义动词来自词簇（word_relations / definitions.cluster_id）的真实词间关系
      * 数据缺失时如实说明，不再编造占位句

    Args:
        verb: 动词

    Returns:
        卡片内容 HTML
    """
    display = get_display_definition(verb)
    example = (display.get("example") or "").strip()

    relatives: List[str] = []
    if DB_AVAILABLE:
        try:
            relatives = get_synonyms(verb)[:6]
        except Exception as e:
            logger.error(f"近义词查询失败 for '{verb}': {e}")
            relatives = []

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #9f7aea; font-weight: 600; margin: 0 0 16px 0;">🖼️ 图式示例</h4>
    '''

    if example:
        html += '<p style="color: #2d3748; margin-bottom: 12px;"><strong>例句:</strong></p>'
        html += (f'<div style="background-color: #faf5ff; padding: 12px; border-radius: 8px; '
                 f'margin-bottom: 16px; color: #4a5568; line-height: 1.8;">{_html_escape(str(example))}</div>')
    else:
        html += ('<p style="color: #718096; margin-bottom: 16px;">'
                 '该动词暂无例句数据（可用管理员录入或等待大模型生成）</p>')

    if relatives:
        html += '<p style="color: #2d3748; margin-bottom: 8px;"><strong>近义动词（同语义范畴）:</strong></p>'
        html += '<div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px;">'
        for rel in relatives:
            html += (f'<span style="background-color: #9f7aea; color: white; padding: 4px 12px; '
                     f'border-radius: 12px; font-size: 0.9em;">{_html_escape(str(rel))}</span>')
        html += '</div>'
        html += ('<p style="color: #718096; font-size: 0.9em;">'
                 '这些动词同属一个次语义范畴，可点击示例库或在搜索框输入词名逐一对比差异。</p>')
    else:
        html += ('<p style="color: #718096;">尚无近义动词数据。'
                 '运行 <code>python scripts/load_word_library.py</code> 可载入 155 词词库及其词间关系。</p>')

    html += '</div>'
    return html

# ============================================
# 示例库渲染函数
# ============================================
def render_example_library():
    """
    渲染示例库组件，带分类标签页。

    使用 Streamlit tabs 和 buttons 创建交互式示例库。
    点击动词按钮会调用 search_verb 函数触发搜索。
    """
    st.markdown("<h3 style='color: #2d3748; font-weight: 600; margin: 0 0 16px 0;'>📚 示例库</h3>", unsafe_allow_html=True)

    # 创建标签页
    tab1, tab2, tab3 = st.tabs([
        "🏃 " + CATEGORY_MODE,
        "🛤️ " + CATEGORY_PATH,
        "💪 " + CATEGORY_MANNER
    ])

    with tab1:
        for verb in EXAMPLE_VERBS.get(CATEGORY_MODE, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=select_example_verb,
                args=(verb,)
            )

    with tab2:
        for verb in EXAMPLE_VERBS.get(CATEGORY_PATH, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=select_example_verb,
                args=(verb,)
            )

    with tab3:
        for verb in EXAMPLE_VERBS.get(CATEGORY_MANNER, []):
            st.button(
                verb,
                use_container_width=True,
                key=f"example_{verb}",
                type="secondary",
                on_click=select_example_verb,
                args=(verb,)
            )

# ============================================
# LLM API Integration
# ============================================
def get_verb_definition(verb: str) -> Optional[Dict[str, Any]]:
    """
    Get verb definition from LLM API with caching.

    Args:
        verb: The verb to define

    Returns:
        Dictionary containing definition data or None if failed
    """
    if not verb or not verb.strip():
        return None

    # Check cache first
    result = get_definition(verb, force_refresh=False)
    if result:
        return result

    # If cache not available or failed, try without cache
    result = get_definition(verb, force_refresh=True)
    return result


# ============================================
# Unified Display Adapter (Phase 5 tracer: D-01/D-02/D-05/D-06/D-07)
# ============================================
# Module-level key names for the combined chinese_ndef JSON stored in MySQL.
TRAD_OPT_KEYS = ("traditional", "optimized")


def _normalize_mock_semantic_table(mock_list) -> Dict[str, str]:
    """
    Convert MOCK_DEFINITIONS' list-of-lists semantic_table into the
    five-key dict (manner/path/direction/aspect/scope) expected downstream.

    Args:
        mock_list: List of [type, emoji, desc] rows from MOCK_DEFINITIONS.

    Returns:
        Dict mapping the five semantic keys to their descriptions.
    """
    key_map = {
        "方式": "manner",
        "路径": "path",
        "方向": "direction",
        "体相": "aspect",
        "范围": "scope",
    }
    result = {k: "待生成" for k in key_map.values()}
    if not mock_list:
        return result
    for row in mock_list:
        if not row:
            continue
        label = row[0]
        desc = row[2] if len(row) > 2 else (row[1] if len(row) > 1 else "")
        if label in key_map:
            result[key_map[label]] = desc
    return result


def _restore_trad_opt(chinese_ndef: str):
    """
    Restore (traditional, optimized) from the stored chinese_ndef string.

    The definitions table has no separate columns; Phase 5 (D-03) persists a
    JSON object {"traditional": t, "optimized": o} inside chinese_ndef.
    Legacy rows store a plain string and are treated as traditional only.

    Returns:
        (traditional, optimized) tuple of strings.
    """
    if not chinese_ndef:
        return "", ""
    try:
        parsed = json.loads(chinese_ndef)
        if isinstance(parsed, dict) and "traditional" in parsed and "optimized" in parsed:
            return parsed.get("traditional", "") or "", parsed.get("optimized", "") or ""
    except (json.JSONDecodeError, TypeError):
        pass
    # Legacy plain-text storage
    return chinese_ndef, ""


def get_display_definition(verb: str) -> Dict[str, Any]:
    """
    Single source of truth for verb definitions（带会话级缓存的对外入口）。

    结果页三张卡片各调用一次本函数；DB 未命中时解析要走 LLM，
    不缓存的话一次 rerun 最多触发 3 次模型调用。会话内按 verb 缓存，
    灌库更新数据后新会话自然刷新。
    """
    _cache = st.session_state.setdefault("_display_def_cache", {})
    if verb in _cache:
        return _cache[verb]
    resolved = _resolve_display_definition(verb)
    _cache[verb] = resolved
    return resolved


def _resolve_display_definition(verb: str) -> Dict[str, Any]:
    """
    Single source of truth for verb definitions (Phase 5 tracer).

    Resolution priority (D-02): DB hit → live LLM → MOCK_DEFINITIONS → fallback.

    Args:
        verb: The verb to define.

    Returns:
        Normalized dict {traditional, optimized, semantic_table, example}.
        Never raises; on total failure returns the absolute fallback shape.
    """

    # (0) Entry validation (T-05-01 mitigation): reject malformed verb, never
    #     feed it into the LLM prompt, and bypass straight to the fallback.
    ok, err = InputValidator.validate_string(verb, max_length=50)
    if not ok:
        logger.warning(f"非法 verb 输入被拒绝: {str(verb)[:50]}")
        fb = get_fallback_definition(verb)
        return {
            "traditional": fb.get("chinese_ndef", ""),
            "optimized": fb.get("chinese_ndef", ""),
            "semantic_table": fb.get("semantic_table", {}),
            "example": fb.get("example", ""),
        }

    # (1) DB first (D-02, LLM-02). Persisted rows take precedence over MOCK.
    try:
        row = get_definition_by_verb(verb)
    except Exception as e:
        logger.error(f"DB lookup failed for '{verb}': {e}")
        row = None

    if row:
        trad, opt = _restore_trad_opt(row.get("chinese_ndef", ""))
        semantic_table = row.get("semantic_table") or {}
        if isinstance(semantic_table, str):
            try:
                semantic_table = json.loads(semantic_table)
            except (json.JSONDecodeError, TypeError):
                semantic_table = {}
        return {
            "traditional": trad,
            "optimized": opt,
            "semantic_table": semantic_table,
            "example": row.get("example_sentence") or "",
        }

    # (2) Live LLM generation, wrapped in a spinner (D-07: spinner only here).
    result = None
    try:
        with st.spinner("正在调用大模型生成释义..."):
            result = get_definition(verb)
    except Exception as e:
        # (4) LLM failure / exception (D-06): log, warn once, fall through.
        logger.error(f"实时 LLM 生成失败 for '{verb}': {e}")
        st.warning("实时生成暂不可用，已显示离线释义")

    if result and result.get("semantic_table"):
        normalized = {
            "traditional": result.get("traditional") or result.get("chinese_ndef", ""),
            "optimized": result.get("optimized", ""),
            "semantic_table": result.get("semantic_table", {}),
            "example": result.get("example", ""),
        }
        # (3) Persist LLM result to DB so subsequent queries hit DB (LLM-03).
        try:
            mysql_db_persist(verb, normalized)
        except Exception as e:
            logger.error(f"持久化失败 for '{verb}': {e}")
        return normalized

    # (5) MOCK fallback (D-02): only after LLM fails.
    if verb in MOCK_DEFINITIONS:
        mock = MOCK_DEFINITIONS[verb]
        return {
            "traditional": mock.get("traditional", ""),
            "optimized": mock.get("optimized", ""),
            "semantic_table": _normalize_mock_semantic_table(mock.get("semantic_table", [])),
            "example": "",
            # R4-6（P3）：MOCK 兜底来源标记 —— 卡片渲染「内置示例（非词典数据）」
            # 徽章，让离线兜底数据在 UI 上可辨识（与 DB/LLM 路径区分）。
            "source": "内置示例",
        }

    # (6) Absolute last resort.
    fb = get_fallback_definition(verb)
    result_dict = {
        "traditional": fb.get("chinese_ndef", ""),
        "optimized": fb.get("chinese_ndef", ""),
        "semantic_table": fb.get("semantic_table", {}),
        "example": fb.get("example", ""),
    }
    return result_dict


def mysql_db_persist(verb: str, normalized: Dict[str, Any]) -> bool:
    """
    Persist a normalized definition to MySQL (LLM-03).

    Stores traditional+optimized as a combined JSON inside chinese_ndef so the
    columns need no migration (D-03); semantic_table is stored as JSON, and
    example_sentence carries the example.

    Args:
        verb: The verb.
        normalized: {traditional, optimized, semantic_table, example}.

    Returns:
        bool: True if successful.
    """
    trad = normalized.get("traditional", "") or ""
    opt = normalized.get("optimized", "") or ""
    combined = json.dumps(
        {"traditional": trad, "optimized": opt}, ensure_ascii=False
    )
    return insert_definition(
        verb=verb,
        chinese_ndef=combined,
        semantic_table=normalized.get("semantic_table", {}),
        example_sentence=normalized.get("example", ""),
        model_version="zhipu-glm-4",
    )


def get_semantic_table_for_verb(verb: str) -> List:
    """
    Get semantic table for a verb in the format expected by render_semantic_table.

    Now sourced from the unified adapter get_display_definition (Phase 5 tracer).
    The external signature and return shape are unchanged.

    Args:
        verb: The verb

    Returns:
        List of [type, emoji, description] tuples
    """
    display = get_display_definition(verb)
    semantic_table = display.get("semantic_table") or {}

    if not semantic_table:
        # Return default structure
        return [
            ["方式", "🏃", "待生成"],
            ["路径", "🛤️", "待生成"],
            ["方向", "🎯", "待生成"],
            ["体相", "💪", "待生成"]
        ]

    # Convert semantic table dict to the format expected by render_semantic_table
    return [
        ["方式", "🏃", semantic_table.get("manner", "待生成")],
        ["路径", "🛤️", semantic_table.get("path", "待生成")],
        ["方向", "🎯", semantic_table.get("direction", "待生成")],
        ["体相", "💪", semantic_table.get("aspect", "待生成")],
        ["范围", "🌍", semantic_table.get("scope", "待生成")]
    ]


# ============================================
# Mock Data (Fallback for offline mode)
# ============================================
# 模拟释义数据
MOCK_DEFINITIONS = {
    "跑进来": {
        "semantic_table": [
            ["方式", "🏃", "双脚快速交替蹬地前进"],
            ["路径", "🛤️", "直线穿越边界进入空间"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体前倾，双臂自然摆动"]
        ],
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
        "semantic_table": [
            ["方式", "🏃", "急速奔跑，带有强烈冲击力"],
            ["路径", "🛤️", "带有横向移动的直线进入"],
            ["方向", "🎯", "目的明确的快速进入"],
            ["体相", "💪", "身体前倾更明显，肌肉紧绷"]
        ],
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
    },
    "走进去": {
        "semantic_table": [
            ["方式", "🚶", "平稳移动，步伐稳定"],
            ["路径", "🛤️", "沿着某轨迹进入空间"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "姿态自然，无明显前倾"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滑进来": {
        "semantic_table": [
            ["方式", "🏃", "身体贴近地面快速滑行"],
            ["路径", "🛤️", "弧形轨迹穿越边界"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体压低，保持平衡"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滚进来": {
        "semantic_table": [
            ["方式", "🏃", "以身体为轴滚动前进"],
            ["路径", "🛤️", "波浪式轨迹移动"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体蜷缩，保持稳定"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "跌进来": {
        "semantic_table": [
            ["方式", "🏃", "失去平衡跌入空间"],
            ["路径", "🛤️", "向下弧形轨迹进入"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体前倾，慌乱姿态"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "窜进来": {
        "semantic_table": [
            ["方式", "🏃", "突然快速窜动进入"],
            ["路径", "🛤️", "曲折但快速进入"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "身体扭曲，快速动作"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "走进来": {
        "semantic_table": [
            ["方式", "🚶", "平稳行走进入空间"],
            ["路径", "🛤️", "从外部到内部移动"],
            ["方向", "🎯", "朝向空间内部"],
            ["体相", "💪", "姿态端正，步伐稳健"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "冲出去": {
        "semantic_table": [
            ["方式", "🏃", "急速奔跑向外冲出"],
            ["路径", "🛤️", "直线向外穿越边界"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体后仰，用力冲刺"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滚出去": {
        "semantic_table": [
            ["方式", "🏃", "以身体为轴向外滚动"],
            ["路径", "🛤️", "波浪式轨迹向外移动"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体蜷缩，保持稳定"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "跌出去": {
        "semantic_table": [
            ["方式", "🏃", "失去平衡跌出空间"],
            ["路径", "🛤️", "向下弧形轨迹离开"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体前倾，慌乱姿态"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "滑出去": {
        "semantic_table": [
            ["方式", "🏃", "身体贴地向外滑行"],
            ["路径", "🛤️", "弧形轨迹穿越边界"],
            ["方向", "🎯", "朝向空间外部"],
            ["体相", "💪", "身体压低，保持平衡"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "站着": {
        "semantic_table": [
            ["方式", "🚶", "保持身体直立姿态"],
            ["路径", "🛤️", "原地固定，无明显位移"],
            ["方向", "🎯", "朝向水平方向延伸"],
            ["体相", "💪", "双臂自然下垂或摆动"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "躺着": {
        "semantic_table": [
            ["方式", "🚶", "身体平躺于地面"],
            ["路径", "🛤️", "水平移动，贴近地面"],
            ["方向", "🎯", "朝向任意水平方向"],
            ["体相", "💪", "全身放松，四肢伸展"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "坐着": {
        "semantic_table": [
            ["方式", "🚶", "臀部接触平面坐姿"],
            ["路径", "🛤️", "相对于地面垂直方向"],
            ["方向", "🎯", "朝向前方或侧方"],
            ["体相", "💪", "上身挺直，双腿下垂"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "蹲着": {
        "semantic_table": [
            ["方式", "🚶", "屈膝半蹲姿态"],
            ["路径", "🛤️", "身体上下起伏移动"],
            ["方向", "🎯", "朝向原地或前方"],
            ["体相", "💪", "身体前倾，重心降低"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "趴着": {
        "semantic_table": [
            ["方式", "🚶", "腹部贴地匍匐移动"],
            ["路径", "🛤️", "贴近地面曲折前进"],
            ["方向", "🎯", "朝向任意水平方向"],
            ["体相", "💪", "身体平贴地面，手脚交替"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    },
    "靠着": {
        "semantic_table": [
            ["方式", "🚶", "身体倚靠固定物移动"],
            ["路径", "🛤️", "沿支撑物表面移动"],
            ["方向", "🎯", "朝向支撑物方向"],
            ["体相", "💪", "背部接触支撑面"]
        ],
        "traditional": "传统释义...",
        "optimized": "优化释义..."
    }
}

# ============================================
# 语义颜色常量
# ============================================
SEMANTIC_COLORS = {
    # RV1-6/RV1-7：色值既作表格文字色也作白字徽章底色，全部取 AA 深档
    # （#48bb78 白字 2.43:1、#ed8936 2.55:1 旧值不达）。
    "方式": {"color": "#4a5568", "emoji": "🏃", "label": "方式"},
    "路径": {"color": "#2f855a", "emoji": "🛤️", "label": "路径"},
    "方向": {"color": "#c05621", "emoji": "🎯", "label": "方向"},
    "体相": {"color": "#805ad5", "emoji": "💪", "label": "体相"}
}

# ============================================
# 示例库分类
# ============================================
CATEGORY_MODE = "方式聚焦类"
CATEGORY_PATH = "路径聚焦类"
CATEGORY_MANNER = "体相聚焦类"

EXAMPLE_VERBS = {
    CATEGORY_MODE: ["跑进来", "冲进来", "滑进来", "滚进来", "跌进来", "窜进来"],
    CATEGORY_PATH: ["走进去", "走进来", "冲出去", "滚出去", "跌出去", "滑出去"],
    CATEGORY_MANNER: ["站着", "躺着", "坐着", "蹲着", "趴着", "靠着"]
}

# ============================================
# 侧边栏组件
# ============================================
def _empty_stats() -> Dict[str, Any]:
    """数据库不可用时的空统计（键与 mysql_db.get_stats 保持一致）。"""
    return {
        "total_queries": 0,
        "queries_today": 0,
        "total_definitions": 0,
        "avg_rating": 0.0,
        "total_feedbacks": 0,
        "total_clusters": 0,
        "total_relations": 0,
    }


def _render_must_change_password_banner(user: Dict[str, Any]) -> None:
    """强制改密横幅（批次 3 ①，平台架构设计规范 §8 / users_db 契约）：
    needs_password_change=1 的账号登录后提示改密。

    判据实时取库（users_db.needs_password_change：users.must_change_password
    生命周期标志 —— create_user 建号与内置 admin bootstrap 时置 1，改密成功
    后清零）。与 _render_default_password_guard 的分工：后者针对「口令仍是
    内置默认值」的弱口令判据并在侧边栏内联提供改密表单；本横幅面向管理员
    签发的**非默认**初始口令，仅做引导提示。批次 4-N 起改密动作走侧边栏
    「🔑 修改密码」自助 expander（_render_self_change_password_form：
    change_password 落库成功即清标志，横幅随之消失）。默认口令情形已被
    guard 表单覆盖，这里不再叠加同一条横幅。
    """
    try:
        uid = int(user.get("id"))
    except (TypeError, ValueError):
        return
    if is_using_default_password(uid):
        # 内置默认口令：_render_default_password_guard 已带常驻横幅+改密表单
        return
    if not needs_password_change(uid):
        return
    st.sidebar.warning(
        "🔐 **初始口令必须修改**：当前账号仍在使用管理员签发的初始口令，"
        "请通过下方「🔑 修改密码」入口修改后再继续使用。"
    )


def _render_default_password_guard(user: Dict[str, Any]) -> None:
    """内置默认口令强制改密横幅（R1-P2c）：侧边栏常驻直到口令已改。

    判据实时取库（users_db.is_using_default_password：当前哈希仍匹配内置
    默认口令）——每次 rerun 都判，改密成功后横幅立即消失。仅在数据库
    可用且会话经登录表单建立（_user_db_backed 标记）时调用。
    """
    try:
        uid = int(user.get("id"))
    except (TypeError, ValueError):
        return
    if not is_using_default_password(uid):
        return
    st.sidebar.warning(
        "⚠️ **内置默认密码，请立即修改**：当前密码是公开的 bootstrap 凭据。"
        "请使用下方唯一的「🔑 修改密码」入口修改；修改成功前本提示持续显示。"
    )  # R8-1（批次 12）：内嵌表单删除——改密 UI 三处合一，唯一入口=自助面板


def _render_self_change_password_form(user: Dict[str, Any]) -> None:
    """个人自助改密表单（批次 4-N）：侧边栏「🔑 修改密码」expander 内。

    三输入：当前密码 + 新密码 + 确认新密码。校验链（任一失败 st.error，
    不触数据层写路径）：
      1. 输入完整且两次新密码一致；
      2. 新密码长度 ≥ MIN_PASSWORD_LENGTH（与 users_db.change_password 同一口径，
         应用层先拒，弱口令不进数据层）；
      3. 当前密码校验走 verify_login（与登录**同一鉴权路径**：users_db 契约
         不变，password_hash 不出数据层；无此用户/密码错/已停用统一 False，
         fail-closed —— 停用会话改不了密码）；
    全部通过后 change_password 落库（pbkdf2 新随机盐，旧口令立即失效），
    成功即清 must_change_password（强制改密横幅下次 rerun 消失）→ st.success；
    失败 st.error。与默认口令守卫表单（_render_default_password_guard）键名
    不同、互不影响，可并存。
    """
    with st.sidebar.form("self_change_password_form", clear_on_submit=True):
        st.markdown("**🔑 修改密码**")
        old_password = st.text_input("当前密码", type="password",
                                     key="self_pw_old", max_chars=128)
        new_password = st.text_input("新密码（≥8 位）", type="password",
                                     key="self_pw_new", max_chars=128)
        confirm_password = st.text_input("确认新密码", type="password",
                                         key="self_pw_again", max_chars=128)
        submitted = st.form_submit_button("修改密码", use_container_width=True)
    if not submitted:
        return
    username = str(user.get("username") or "")
    try:
        uid = int(user.get("id"))
    except (TypeError, ValueError):
        st.sidebar.error("会话用户信息不完整，请重新登录后再试。")
        return
    if not old_password or not new_password or new_password != confirm_password:
        st.sidebar.error("请填写当前密码与新密码，且两次新密码一致。")
        return
    if len(new_password) < MIN_PASSWORD_LENGTH:
        st.sidebar.error(f"新密码长度至少 {MIN_PASSWORD_LENGTH} 位。")
        return
    if not verify_login(username, old_password):
        st.sidebar.error("当前密码不正确。")
        return
    if change_password(uid, new_password, actor=user):
        st.sidebar.success("✅ 密码已修改，下次登录请使用新密码。")
    else:
        st.sidebar.error("修改失败（数据库未写入），请重试。")


# ============================================
# 登录落地三分支（规范②组；规范 §9「登录落地三分支」原文口径）
# ============================================
# 规范《平台架构设计规范.md》§9 原文（L242-243）：
#   「登录落地三分支：有待办→协作收件箱；有续接点→上次位置（侧边栏「继续：…」）；
#     首次→搜索释义。用户上下文（profiles/state/bookmarks/notes/draft_states）
#     跨设备续接……」
# 实现口径（FX-29，逐条对照规范文字）：
#   * 只改**登录成功那一刻**的初始 page 设置（写 session_state["page"]）——
#     不动七区分组与路由契约（PAGE_KEYS 键集不变）；用户随后手动切页不被劫持
#     （落地解析只在登录成功路径调用一次，不进每轮渲染）；
#   * 「有待办」＝ ai_proposals 台账 pending 的 draft/audit 提议数 > 0
#     （pending_inbox_count —— 与侧边栏「🤖 AI 待办 N 条 · 去处理」徽章同一
#     信号源；库不可用/表未建按 0 计，自然落到后续分支）→ 协作收件箱 ai_hub
#     （六角色全可见，_PAGE_ACCESS_SIX["ai_hub"]=NEW_ROLES）。
#     RV15-1 落地判定加角色条件：仅当用户可裁决（_can_adjudicate_inbox ——
#     collab_pages 收件箱裁决按钮区同源口径，有效六角色含 dict_admin/reviewer）
#     且其可裁决域（draft/audit pending，即 pending_inbox_count 计数面）>0
#     时才落 ai_hub；无裁决权角色（viewer/annotator/editor/sys_admin 在
#     收件箱本就是只读展示）直接顺序到分支 2/3 —— pending_inbox_count 全局
#     计数不动（侧边栏徽章语义保留：徽章是全角色提示性质），只收落地分支；
#   * 「有续接点」＝ 用户上下文域 user_state（工作位置/续接点，规范 §8-⑨）
#     读到上次工作页 —— 页级续接点读取尚未接线（src/user_context_db 的
#     user_state 为键值面，「键 → 落地页」的换算归其接线方），本模块留
#     set_resume_page_loader 缝（FX-18 set_db_enabled_loader 同款两步绑定），
#     未绑定/读不到 ＝ 无续接点，顺序取下一分支；
#     RV15-3「侧边栏『继续：…』」可见面落位：分支 2 命中即 ui_kit.flash
#     「已回到上次工作位置：{页名}」（flash 队列 main() 每轮渲染消费既有
#     纪律；登录成功路径紧随 st.rerun，提示下一轮渲染弹出）；分支 3（首次）
#     不 flash；
#   * 「首次」（无待办且无续接点）→ 搜索释义 search；
#   * 各分支目标先过 _visible_page_keys 角色可见性过滤：落地页不得是该角色
#     radio 之外的隐藏页（不可见视同该分支未命中，顺序取下一分支）。
_RESUME_PAGE_LOADER: Optional[Callable[[int], Optional[str]]] = None

# RV15-3（FX-35）：侧边栏「继续：…」灰注的一次性旗标键 —— 登录落地分支 2
# （续接点命中）此刻落 session_state（落地解析只在登录成功路径调用一次，
# 旗标自然只写一次、随后只读不写）；render_sidebar 在页面 radio 上方读旗标
# 渲染灰注。非 widget 键（RV12-1 只读纪律无涉），且不在 _LOGOUT_KEEP_KEYS
# —— 登出全清自然回收（共享终端换人不留上一人的续接痕迹）。
_RESUME_HINT_KEY = "_resume_hint_page"


def set_resume_page_loader(
        loader: Optional[Callable[[int], Optional[str]]]) -> None:
    """绑定/解绑续接点 loader（FX-29 缝）：loader(user_id) → 上次工作页键或 None。

    生产绑定入口：用户上下文域（src/user_context_db，FX-31）把 user_state 的
    页级续接点换算成页键后仿 src/tool_settings_db.bind_registry_loader 的
    两步激活绑入；本模块自身零 DB 依赖，loader 未绑定时落地分支 2 恒不命中
    （行为与纯会话内实现一致，兼容测试打桩）。传 None 解绑。
    """
    global _RESUME_PAGE_LOADER
    _RESUME_PAGE_LOADER = loader


def _resume_work_page(user: Dict[str, Any]) -> Optional[str]:
    """读续接点（上次工作页键）：loader 未绑定/读不到/异常 → None。

    异常吞掉补留痕（R6-10 同款口径）—— 落地不该因续接点读数失败而断，
    fail-open 顺序取下一分支。
    """
    loader = _RESUME_PAGE_LOADER
    if loader is None:
        return None
    try:
        return loader(as_int(user.get("id")))
    except Exception as e:  # noqa: BLE001 —— 续接点读数失败按无续接点降级
        logger.warning(f"登录落地：续接点读取失败（按无续接点降级）: {e}")
        return None


def _resume_page_loader(user_id: int) -> Optional[str]:
    """user_state 续接点适配器（FX-31 对接）：登录瞬间会话用户==user_id，
    故走会话派生 CRUD（user_context_db 权限面不收 user_id 入参）读
    resume_page；loader 缝签名由 set_resume_page_loader 约定。"""
    try:
        from src.user_context_db import list_states

        for row in list_states():
            if row.get("state_key") == "resume_page":
                page_key = row.get("state_value")
                # 白名单双保险：脏值/越权页键在此拦下（落地层还有可见集过滤）
                return (page_key if isinstance(page_key, str)
                        and page_key in PAGE_KEYS else None)
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"续接点适配器读取失败（按无续接点降级）: {e}")
        return None


set_resume_page_loader(_resume_page_loader)


def _landing_page_for(user: Dict[str, Any]) -> str:
    """登录落地三分支解析（规范 §9 L242 原文口径，逐条对照见本区注释）。

    分支顺序即规范语序：有待办→协作收件箱；有续接点→上次位置；首次→搜索释义。
    RV15-1：分支 1 加可裁决角色条件（_can_adjudicate_inbox 同源口径）——
    无裁决权角色不因全局 pending>0 被落去 ai_hub；RV15-3：分支 2 命中即
    flash「已回到上次工作位置」。
    仅在登录成功路径调用一次（_render_login_section）；返回键必属该角色可见集
    （_visible_page_keys ⊆ PAGE_KEYS），七区路由契约不受影响。
    """
    visible = _visible_page_keys(user)
    # 分支 1：有待办 → 协作收件箱（ai_hub 六角色全可见）。
    # RV15-1：落地判定加可裁决角色条件（口径见本区注释块）——可裁决且其
    # 可裁决域 pending>0 才落 ai_hub，无裁决权角色顺序到分支 2/3。
    if ("ai_hub" in visible and _can_adjudicate_inbox(user)
            and pending_inbox_count() > 0):
        return "ai_hub"
    # 分支 2：有续接点 → 上次位置（user_state 续接点；侧边栏「继续：…」同源）。
    # RV15-3：命中即 flash（规范「继续：…」可见面；main() 下一轮渲染消费）。
    # FX-35：命中同时把 resume 页键落一次性旗标（_RESUME_HINT_KEY），
    # render_sidebar 在 radio 上方渲染「↩︎ 续接上次：…」灰注（侧边栏可见面
    # 最小件）；旗标写一次后只读，登出全清自然回收。
    resume = _resume_work_page(user)
    if resume is not None and resume in visible:
        ui_kit.flash(f"已回到上次工作位置：{page_label(resume)}")
        st.session_state[_RESUME_HINT_KEY] = resume
        return resume
    # 分支 3：首次（无待办且无续接点）→ 搜索释义（不 flash）
    return "search"


def _render_login_section() -> None:
    """侧边栏登录区（规范 §5）：未登录显示登录表单，已登录显示用户名+角色徽章+退出。

    数据库离线时显示「登录不可用（数据库离线）」info，不崩溃；登录失败
    st.error 提示（verify_login_full 对无此用户/密码错/已停用统一返回 None，
    防枚举）。表单 clear_on_submit=True：密码不常驻会话（规范 §6-2）。
    批次 3 六角色会话：改调 verify_login_full —— session user 在旧四键
    （id/username/display_name/role，role 仍为旧列值向后兼容）基础上增加
    roles 列表（六角色按优先级降序），供 _visible_page_keys 与页面层读取。
    登录成功后（R1-P2c）：若该用户当前哈希仍匹配内置默认口令，侧边栏顶部
    常驻强制改密横幅+表单（_render_default_password_guard）；管理员签发的
    非默认初始口令（must_change_password=1）由 _render_must_change_password_
    banner 提示改密。批次 4-N：已登录区新增「🔑 修改密码」自助 expander
    （旧密码校验 + change_password 落库），仅对真实登录会话渲染 —— 与两条
    强制改密路径并存、互不影响。
    """
    if not DB_AVAILABLE:
        st.sidebar.info("登录不可用（数据库离线）")
        return
    user = _current_user()
    if user:
        role = str(user.get("role") or "")
        name = _html_escape(str(user.get("display_name") or user.get("username") or ""))
        st.sidebar.markdown(
            f"<p style='margin:0 0 6px 0;font-weight:600;'>👤 {name} "
            f"<span style='background:{ROLE_BADGE_COLORS.get(role, '#718096')};"
            f"color:#fff;padding:1px 10px;border-radius:10px;font-size:0.78em;'>"
            f"{_html_escape(ROLE_LABELS.get(role, role))}</span></p>",
            unsafe_allow_html=True,
        )
        st.sidebar.button("🚪 退出登录", key="logout_button",
                          use_container_width=True, on_click=_logout)
        # 强制改密（R1-P2c 默认口令表单 / 批次 3 初始口令横幅 / 批次 4-N 自助
        # 改密 expander）：仅对真实登录会话（_user_db_backed）渲染
        if st.session_state.get(_USER_DB_BACKED_KEY):
            _render_default_password_guard(user)
            _render_must_change_password_banner(user)
            # R8-1：默认口令用户表单默认展开（改密完成后 is_using_default_password
            # 实时判 False，expander 收起——唯一入口始终可见、无需滚动寻找）
            _auto_open = is_using_default_password(int(user.get("id")))
            with st.sidebar.expander("🔑 修改密码", expanded=_auto_open):
                _render_self_change_password_form(user)
        return

    with st.sidebar.form("login_form", clear_on_submit=True):
        st.markdown("**🔐 登录**")
        username = st.text_input("用户名", key="login_username", max_chars=50)
        password = st.text_input("密码", type="password", key="login_password", max_chars=128)
        submitted = st.form_submit_button("登录", use_container_width=True)
    if submitted:
        info = verify_login_full(username or "", password or "")
        if info:
            st.session_state["user"] = info
            st.session_state[_USER_DB_BACKED_KEY] = True
            # 登录落地三分支（FX-29，规范 §9 L242）：有待办→协作收件箱；
            # 有续接点→上次位置；首次→搜索释义。只在登录成功这一刻写初始
            # page（radio key="page" 尚未实例化，st.rerun() 后以其值实例化，
            # 七区路由契约不变）；用户随后手动切页不被劫持 —— 解析不进每轮
            # 渲染，残留页回退逻辑（render_sidebar）原样保留。
            st.session_state["page"] = _landing_page_for(info)
            st.rerun()
        else:
            st.sidebar.error("用户名或密码错误，或账号已停用。")


def render_sidebar():
    """渲染侧边栏组件（折叠/展开双分支，D-01）"""
    # 会话角色防陈旧（R1-P2b）：每次 rerun、先于 main() 页面分派实时回查
    # users 表 —— 停用/删除用户被登出并提示；管理员改角色立即生效。
    # 登录快照自此仅用于显示；三个受保护页入口的权限判定读到的是当次实时角色。
    _refresh_session_user()
    collapsed = st.session_state.get("sidebar_collapsed", False)

    if collapsed:
        # 折叠分支：窄图标栏（D-01），点击任意图标即展开回完整宽度
        st.sidebar.button("☰", key="expand_sidebar", help="展开侧边栏",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        st.sidebar.button("📊", key="rail_stats", help="统计",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        st.sidebar.button("🔥", key="rail_hot", help="热门查询动词",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        st.sidebar.button("📥", key="rail_export", help="数据导出",
                          on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", False))
        return

    # 展开分支：完整内容（D-01）
    st.sidebar.button("◀", key="collapse_sidebar", help="折叠侧边栏",
                      on_click=lambda: st.session_state.__setitem__("sidebar_collapsed", True))

    # ---- 登录区（侧边栏顶部、页面切换之前；规范 §5 UI 集成契约）----
    _render_login_section()

    # 页面切换：基础五页 + 帮助中心 + 受保护页/区级页（按六角色可见性过滤，批次 3 ②）。
    # 选项仍来自 page_guides.PAGE_KEYS（页面 ↔ 使用说明一一对应的单一事实来源），
    # 只是按 _PAGE_ACCESS_SIX 过滤子集 —— 不硬编码页面清单。
    # 残留页（登出/换角色后当前页不在可见集合）回搜索页，避免 radio 的
    # session_state 值不在 options 里抛 StreamlitAPIException。
    # 不要再传 index=：key="page" 一旦存在于 session_state，再传 index 会在
    # 旧版 Streamlit 上抛 StreamlitAPIException、新版上打重复赋值警告。
    visible_keys = _visible_page_keys(_current_user())
    if st.session_state.get("page") not in visible_keys:
        st.session_state["page"] = "search"
    # RV15-3（FX-35）：登录落地分支 2（续接点命中）落的灰注旗标 —— radio 上方
    # 一行 caption「↩︎ 续接上次：{页名}」。仅当续接点命中时显示：旗标由
    # _landing_page_for 在登录那一刻写一次（落地解析不进每轮渲染），本处只读
    # 不写（RV12-1：不直写 widget 键）；旗标页键仍需在当前角色可见集内
    # （会话中途角色收窄则随 radio 回退一起隐藏），登出全清自然回收。
    _resume_hint = st.session_state.get(_RESUME_HINT_KEY)
    if _resume_hint in visible_keys:
        st.sidebar.caption(f"↩︎ 续接上次：{page_label(_resume_hint)}")
    # 七区菜单分组（规范②组，FX-23）：仅展示重排 —— 组间按 _SIDEBAR_ZONES 序、
    # 组内保持 PAGE_KEYS 相对序，键集与权限过滤不变；标签加区名前缀
    # （sidebar_option_label），区名前缀成块出现即分组标题。
    # 不再 horizontal=True：选项标签变为「【区名】页名」两段式，竖排成组可读。
    visible_keys = _group_keys_by_zone(visible_keys)
    st.sidebar.radio(
        "页面",
        options=visible_keys,
        format_func=sidebar_option_label,
        key="page",
    )
    st.sidebar.divider()

    # 🤖 AI 协作待办徽章（批次 7：收件箱 pending 计数，30s 缓存；登录后可见）。
    # 跳转用 on_click 回调（重跑前执行）：radio 的 key="page" 在本函数更下方
    # 实例化，若在其实例化后改 session_state["page"] 会被 Streamlit 拒绝。
    if st.session_state.get("user"):
        _inbox_n = pending_inbox_count()
        if _inbox_n:
            st.sidebar.button(
                f"🤖 AI 待办 {_inbox_n} 条 · 去处理",
                key="sidebar_inbox_badge",
                on_click=lambda: st.session_state.__setitem__("page", "ai_hub"),
            )
            st.sidebar.divider()

    st.sidebar.markdown(f"<h2 style='{HEADER_H2}'>📊 实验统计</h2>", unsafe_allow_html=True)

    if DB_AVAILABLE:
        try:
            stats = get_stats()
            hot_verbs = get_hot_verbs(cache_scope_key(), limit=5)
        except Exception as e:
            logger.error(f"侧边栏统计读取失败: {e}")
            stats = _empty_stats()
            hot_verbs = []
    else:
        stats = _empty_stats()
        hot_verbs = []

    # R4-2（P3）：离线统计显示 "—" 而非 0（口径对齐 ai_hub —— 0 是「统计到了
    # 零条」，"—" 才是「无法统计」，离线时后者才是事实）。
    _off = not DB_AVAILABLE
    _dash = "—"

    # 口径说明：total_queries 来自 usage_logs（真实查询次数），
    # total_definitions 是已收录词目数 —— 两者含义不同，分开展示。
    st.sidebar.metric(
        "总查询次数",
        _dash if _off else stats["total_queries"],
        delta=f"+{stats['queries_today']} 今天"
              if (not _off and stats.get("queries_today")) else None,
    )
    st.sidebar.metric("已收录词目", _dash if _off else stats.get("total_definitions", 0))
    # 结构指标：词簇数与词间关系边数 —— 直接反映「词与词关系」图谱的规模
    st.sidebar.metric("词簇", _dash if _off else stats.get("total_clusters", 0))
    st.sidebar.metric("词间关系", _dash if _off else stats.get("total_relations", 0))
    st.sidebar.metric("平均评分", _dash if _off else f"{stats['avg_rating']:.1f}/5.0")
    st.sidebar.metric("总反馈数", _dash if _off else stats["total_feedbacks"])

    st.sidebar.divider()

    st.sidebar.markdown(f"<h2 style='{HEADER_H3}'>🔥 热门查询动词</h2>", unsafe_allow_html=True)

    if hot_verbs:
        # 本地前端子串筛选输入框（D-05，无后端往返）
        st.sidebar.text_input("筛选热门动词", key="hot_filter", placeholder="输入关键字筛选…")
        filtered = filter_hot_verbs(hot_verbs, st.session_state.get("hot_filter", ""))
        for v in filtered:
            # 可点击行：复用 select_example_verb 填充搜索框并触发搜索（D-04）
            st.sidebar.button(
                f"{v['verb']} · {v['count']}次 ⭐{v['avg_rating']}",
                key=f"hot_{v['verb']}",
                on_click=select_example_verb,
                args=(v['verb'],),
            )
    else:
        st.sidebar.info("暂无热门查询数据")

    st.sidebar.divider()

    # 数据库状态（极简一行：健康绿点/离线红点——代替旧版顶部 success 大横幅）
    st.sidebar.markdown(
        f"<p style='color:{'#48bb78' if DB_AVAILABLE else '#e53e3e'};font-size:0.8rem;"
        f"margin:4px 0;'>{'🟢 MySQL 已连接' if DB_AVAILABLE else '🔴 MySQL 离线 · 功能降级'}</p>",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(f"<h2 style='{HEADER_H3}'>📥 数据导出</h2>", unsafe_allow_html=True)

    # R5-3（P1）按需导出：此前每轮 rerun 都全表 SELECT * FROM feedbacks 只为
    # 填 download_button 的 data。现在默认只渲染「生成导出」按钮 + 行数 caption
    # （轻量 COUNT），点击后才真正取数并生成 CSV（导出功能保留，成本移到点击时）。
    # R7-14 权限闸门：反馈数据（评分＋文字建议）属内部研究数据，未登录灰置
    # 导出按钮并注明原因（与其他导出口径一致：权限不足灰置＋原因；数据闸门
    # 保留离线/取数失败/空数据三支分流）。
    if not DB_AVAILABLE:
        st.sidebar.caption("数据库离线，反馈导出暂不可用。")
    else:
        _fb_count = count_feedbacks()
        if _fb_count is None:
            st.sidebar.caption("反馈行数读取失败（数据库异常），导出暂不可用。")
        else:
            st.sidebar.caption(f"当前反馈 {_fb_count} 条。")
            _export_allowed = isinstance(st.session_state.get("user"), dict)
            if st.sidebar.button("生成并导出反馈 (CSV)",
                                 key="sidebar_feedback_export",
                                 disabled=not _export_allowed,
                                 use_container_width=True):
                try:
                    feedback_df = pd.DataFrame(get_feedback_data())
                except Exception as e:
                    logger.error(f"反馈导出取数失败: {e}")
                    feedback_df = pd.DataFrame(
                        columns=["verb", "rating", "feedback_text", "created_at"])
                if feedback_df.empty:
                    st.sidebar.info("暂无反馈数据可导出。")
                else:
                    # CSV 公式注入防护（R1-P2）：文本以 = + - @ \t 开头时前置单引号
                    csv = sanitize_csv_dataframe(feedback_df).to_csv(
                        index=False).encode('utf-8-sig')
                    st.sidebar.download_button(
                        label="下载反馈数据 (CSV)",
                        data=csv,
                        file_name=f"feedback_data_"
                                  f"{datetime.datetime.now().strftime('%Y%m%d')}.csv",
                        mime='text/csv',
                        type="primary",
                        key="sidebar_feedback_download",
                        use_container_width=True
                    )
            if not _export_allowed:
                st.sidebar.caption(
                    "🔒 反馈数据导出需登录（内部研究数据）—— 请先在上方登录后使用。"
                )

# ============================================
# 主区域组件
# ============================================
def render_main_area():
    """渲染主区域组件"""
    # 词条装配预览（批次 9 Agent AS，工序 14 消费侧）函数级导入：本文件顶部
    # import 块因 sys.path 前置本就整块 E402，此处仿 pandas 的函数级导入先例，
    # 不给 flake8 新增告警。
    from src.entry_assembly import render_entry_assembly
    render_page_usage_guide("search")
    st.markdown(f"<h1 style='{HEADER_H1}'>🏃 动词释义优化器</h1>", unsafe_allow_html=True)
    st.markdown(THEORY_DESCRIPTION, unsafe_allow_html=True)

    # ===== 浮动固定搜索栏 =====
    # 用 st.container(key="search_bar") 让输入框真正位于 .st-key-search_bar 容器内，
    # 固定的 CSS 挂在容器的 wrapper 上（见文件顶部样式块）。不要再改回
    # st.markdown('<div class=...>') 的写法——那只会生成一个空的兄弟 div，
    # 输入框不在其中，sticky 与背景都不会生效。
    with st.container(key="search_bar"):
        # 搜索输入框 — 使用 key 让 Streamlit 自动管理 session_state
        # 不设置 value（由 key 管理），on_change 在值变化时触发搜索
        st.text_input(
            label="搜索动词",
            placeholder="搜索动词 (例如：跑进来、冲进来、滑进来...)",
            label_visibility="collapsed",
            key="搜索动词",
            on_change=search_verb
        )

    # 词形还原提示（批次 3 ③）：查询词命中 wordforms 词形表且还原出的词目
    # 与查询词不同时，渲染一行「词形「X」→ 词目「Y」」提示 + 一键切换查询。
    # 提示由 search_verb / select_example_verb / 切换回调在入口处写入会话；
    # DB 不可用或无命中时会话里没有该键，这里什么都不渲染 —— 既有所见即
    # 所得的结果结构（六卡片 + 词间关系 + 示例库）不变。
    _hint = st.session_state.get(_WORDFORM_HINT_KEY)
    if _hint:
        _col_hint, _col_switch = st.columns([3, 1])
        with _col_hint:
            st.info(f"🔁 词形「{_hint.get('form')}」→ 词目「{_hint.get('lemma')}」")
        with _col_switch:
            st.button(
                f"查询「{_hint.get('lemma')}」",
                key="wordform_switch_button",
                use_container_width=True,
                on_click=_switch_to_wordform_lemma,
                args=(_hint.get("lemma"),),
            )

    # 欢迎消息（当没有结果时显示）
    if not hasattr(st.session_state, 'show_result') or not st.session_state.show_result:
        st.markdown(get_section_spacing(), unsafe_allow_html=True)
        st.markdown(f"""
        <div style='{get_card_style()}'>
            <h2 style='{HEADER_H3}'>🏃 动词释义优化器</h2>
            <p style='{BODY_BASE}'><strong>基于运动事件类型学的中文动词释义优化</strong></p>
            <div style='{get_section_spacing()}'></div>
            <p style='{BODY_BASE}'><strong>核心功能：</strong></p>
            <ul style='{BODY_BASE}; margin-top: 8px; padding-left: 24px; line-height: 1.8;'>
                <li><strong>方式要素分解</strong>：分析运动采用的姿势/手段</li>
                <li><strong>路径要素分解</strong>：解析运动经过的空间轨迹</li>
                <li><strong>方向要素分解</strong>：识别运动朝向的终点/目标</li>
                <li><strong>体相要素分解</strong>：描述运动时身体的姿态/状态</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(get_section_spacing(), unsafe_allow_html=True)

    # 显示结果区域
    if hasattr(st.session_state, 'show_result') and st.session_state.show_result:
        verb = st.session_state.verb_result

        # 显示四张卡片布局
        st.markdown(f"<h2 style='{HEADER_H2}'>结果展示</h2>", unsafe_allow_html=True)

        # 四卡布局：头部是真正可点击的折叠按钮（render_card_header 内部用
        # st.button + on_click 写入 session_state.card_expanded）
        for card_key, title, icon, body_renderer in (
            ("prototype", "原型与位移事件分析", "🧬", render_card_prototype),
            ("anchor", "范畴锚定", "🎯", render_card_anchor),
            ("annotation", "义位标注", "🏷️", render_card_annotation),
            ("core", "核心释义与多维辨异", "📚", render_card_core),
            ("example", "图式示例", "🖼️", render_card_example),
            ("corpus", "语料库证据 (enTenTen21)", "🌐", render_card_corpus),
        ):
            render_card_header(card_key, title, icon)
            if st.session_state.card_expanded.get(card_key, True):
                # 正文放进带 key 的容器，外观由 [class*="st-key-card_body_"] 提供
                with st.container(key=f"card_body_{card_key}"):
                    st.markdown(body_renderer(verb), unsafe_allow_html=True)

        # 词间关系：内嵌当前词所在词簇的交互图（vis-network 力导向布局，
        # 中心词高亮、悬停显名、默认只画中心连线，簇内两两连线页内展开 ——
        # 避免旧版 SVG 完全图的连线视觉纠缠）。全库地图仍由「知识图谱」页承担。
        st.markdown(get_section_spacing(), unsafe_allow_html=True)
        render_word_relation_section(verb)

        # 词条装配预览（批次 9 Agent AS，工序 14 消费侧）：四卡片与词间关系
        # 之后、示例库之前，按《平台架构设计规范》§6 成品词条内容模型装配
        # 只读预览。懒加载 —— expander 用 on_change="rerun" 接线（与词条浏览器
        # 义项脊柱同模式），收起时零取数；展开才调 render_entry_assembly，
        # 各段独立降级，绝不打断既有结果结构。
        st.markdown(get_section_spacing(), unsafe_allow_html=True)
        with st.expander(
            "📄 词条装配预览（头块 / 义项 coverage / 发布例证 / 对译三态 / "
            "媒体 / 定制属性 / 参见）",
            key="entry_assembly_expander",
            on_change="rerun",
        ) as assembly_expander:
            if assembly_expander.open:
                render_entry_assembly(verb)

        # 示例库
        st.markdown(get_section_spacing(), unsafe_allow_html=True)
        render_example_library()

        # 用户反馈区域
        st.markdown(get_section_spacing(), unsafe_allow_html=True)

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
        # 注：get_button_primary_style() 返回的是 CSS 字符串（不是关键字参数字典），
        # 展开传入 st.button 会在渲染结果区时抛 TypeError。
        submit_button = st.button("📤 提交反馈", type="primary")

        if submit_button:
            if rating > 0 and feedback_text.strip():
                if DB_AVAILABLE:
                    try:
                        ok = insert_feedback(verb, rating, feedback_text.strip())
                    except Exception as e:
                        logger.error(f"反馈插入异常: {e}")
                        ok = False
                    if ok:
                        st.success("✅ 反馈已成功提交！感谢您的参与！")
                    else:
                        st.error("反馈提交失败（数据库写入未成功），请稍后重试")
                else:
                    st.success("✅ 反馈已记录（离线模式，未持久化）！")
                    ok = True

                # 只有真正写入成功才标记"已提交"，避免假成功卡片
                if ok:
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
            st.markdown(get_section_spacing(), unsafe_allow_html=True)

            st.markdown(f"<h3 style='{HEADER_H3}'>📝 反馈历史</h3>", unsafe_allow_html=True)
            if hasattr(st.session_state, 'last_feedback'):
                fb = st.session_state.last_feedback
                badge_style = get_badge_style(SUCCESS_COLOR)
                st.markdown(
                    f"""
                    <div style='{get_card_style()}'>
                        <span style='{badge_style}'>已提交</span>
                        <p style='{BODY_BASE}'><strong>动词:</strong> {_html_escape(str(fb['verb']))}</p>
                        <p style='{BODY_BASE}'><strong>评分:</strong> {'⭐' * fb['rating']} ({fb['rating']}/5)</p>
                        <p style='{BODY_BASE}'><strong>反馈:</strong> {_html_escape(str(fb['feedback']))}</p>
                        <p style='{BODY_BASE}'><strong>时间:</strong> {_html_escape(str(fb['timestamp']))}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )


# ============================================
# 交互式知识图谱页面
# ============================================
def render_interactive_graph_page() -> None:
    """
    全屏交互式词间关系图谱页（graphify 风格的力导向图）。

    词间关系的唯一入口：全库 136 词 / 1780 边的语义地图，
    可搜索、可点选、可按簇过滤。搜索页只保留一个跳转按钮到本页。

    实现要点：图谱渲染成**静态 HTML 文件**放进 src/static/，用 iframe 引用。
    不用 components.html(html_string) 的原因是 Streamlit 每次交互重跑脚本时，
    内联的 iframe 会被整体重写 —— 力导向布局从头收敛，用户拖好的位置、
    选中的节点、缩放视野全丢。静态文件 + 内容指纹 URL 则只在数据变化时重载。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>🕸️ 词间关系知识图谱</h1>", unsafe_allow_html=True)
    render_page_usage_guide("graph")

    if not DB_AVAILABLE:
        st.info("数据库不可用，无法展示知识图谱（离线模式下仅提供释义）。")
        return

    try:
        graph = get_full_word_graph(cache_scope_key())
    except Exception as e:
        logger.error(f"读取全库图谱失败: {e}")
        graph = None

    # R4-1 三口径：None=查询失败（数据不可用，勿重跑灌库）；
    # []=表在但词库未灌（给灌库指引）；有数=正常渲染。
    if graph is None:
        st.warning(
            "数据不可用：全库图谱读取失败（数据库查询出错或连接中断）。"
            "属服务端异常，**勿重跑灌库脚本**；恢复后刷新本页即可。"
        )
        return
    if not graph.get("nodes"):
        st.info(
            "暂无词间关系数据。运行 `python scripts/load_word_library.py` "
            "可载入 155 词词库及其 2143 条词间关系。"
        )
        return

    stats = graph["stats"]
    c1, c2, c3 = st.columns(3)
    c1.metric("动词节点", stats["node_count"])
    c2.metric("近义关系", stats["edge_count"])
    c3.metric("词簇", stats["cluster_count"])

    url = ensure_graph_html(graph)
    if not url:
        st.warning("图谱文件生成失败，请检查 `src/static/` 是否可写。")
        return

    st.caption(
        "左侧力导向图可直接缩放拖拽；右侧栏可搜索动词、查看节点邻居、"
        "按词簇勾选过滤。每个节点的连线数等于它所在词簇的大小减一"
        "（同一簇内两两互为近义，即完全图）。"
    )

    # 直接嵌本地静态文件（不是内联 HTML 字符串）—— 这样 Streamlit 重跑脚本时
    # iframe 的 src 不变，浏览器不会重载，图谱的布局与交互状态得以保留。
    st.iframe(url, height=820)

    st.markdown(f"<h3 style='{HEADER_H3}'>按词簇浏览</h3>", unsafe_allow_html=True)
    st.caption("点击任一词即切换搜索词，并在结果页展示该词所在簇的完全图。")
    clusters = graph.get("clusters", [])
    per_row = 4
    for i in range(0, len(clusters), per_row):
        row = clusters[i:i + per_row]
        cols = st.columns(per_row)
        for col, cluster in zip(cols, row):
            with col:
                st.button(
                    f"{cluster['sub_cat']}（{cluster['size']} 词 / {cluster['edge_count']} 边）",
                    key=f"graph_cluster_{cluster['id']}",
                    use_container_width=True,
                    on_click=_pick_cluster_verb,
                    args=(cluster["id"],),
                )


def _pick_cluster_verb(cluster_id: int) -> None:
    """点击「按词簇浏览」按钮：跳到该簇的第一个词（图谱随之打开该簇）。"""
    try:
        g = get_cluster_graph_by_id(cluster_id)
    except Exception as e:
        logger.error(f"读取词簇 {cluster_id} 失败: {e}")
        return
    if not g:  # R4-1：查询失败（None）与空簇一律静默不导航（on_click 回调内不渲染 UI）
        logger.error(f"词簇 {cluster_id} 不可用（读取失败或空簇），未跳转")
        return
    nodes = g.get("nodes") or []
    if not nodes:
        return
    verb = g.get("center") or nodes[0]["id"]
    st.session_state.verb_result = verb
    st.session_state.show_result = True
    st.session_state["搜索动词"] = verb
    st.session_state["page"] = "search"
    _record_query(verb)


# ============================================
# 语料数据集页（Sketch Engine enTenTen21 → 页面展示）
# ============================================
def render_corpus_dataset_page() -> None:
    """📊 语料数据集：136 动词的词频、四图式重心得分与搭配明细浏览。

    数据来自 output/ 语料包灌入的 corpus_* 表（scripts/load_corpus_dataset.py）。
    语义类别/保留标记两列留在库里供人工标注回写，页面原样展示当前值。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>📊 语料数据集</h1>", unsafe_allow_html=True)
    render_page_usage_guide("corpus")

    if not DB_AVAILABLE:
        st.info("数据库不可用，无法展示语料数据集（离线模式下仅提供释义）。")
        return
    if not corpus_dataset_ready():
        st.info(
            "语料数据集尚未灌入。运行 "
            "`MYSQL_HOST=127.0.0.1 python3 scripts/load_corpus_dataset.py` "
            "从 output/ 语料包加载。"
        )
        return

    overview = get_corpus_overview()
    if not overview:
        st.warning(
            "语料概览表（corpus_word_stats）为空：请重跑 "
            "`MYSQL_HOST=127.0.0.1 python3 scripts/load_corpus_dataset.py` "
            "灌入语料包后刷新本页；刚灌完仍为空属页面缓存，稍候再刷一次。"
        )
        return

    import pandas as pd

    total_coll = sum(r["collocate_count"] for r in overview)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("动词", len(overview))
    c2.metric("搭配词型总数", f"{total_coll:,}")
    c3.metric("重心得分行", len(overview) * 4)
    c4.metric("语料库", "enTenTen21")

    df = pd.DataFrame(overview)
    df = df.rename(columns={
        "verb": "动词", "lpos": "词性", "freq": "总频次", "relfreq": "每百万频次",
        "slot_count": "槽位数", "collocate_count": "搭配词型",
        "candidate_schema": "候选凸显图式(AI初筛)", "max_score": "最高重心得分",
    })

    st.markdown(f"<h3 style='{HEADER_H3}'>总表（按频次降序）</h3>", unsafe_allow_html=True)
    kw = st.text_input("筛选动词", key="corpus_filter", placeholder="输入关键字筛选…")
    view = df[df["动词"].str.contains(kw, case=False, na=False)] if kw else df
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "总频次": st.column_config.NumberColumn(format="%,d"),
            "每百万频次": st.column_config.NumberColumn(format="%.1f"),
            "最高重心得分": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption("候选凸显图式为 AI 初筛（未语义归类），最终图式标签以义位标注为准。")

    # ---- 逐词下钻 ----
    st.markdown(f"<h3 style='{HEADER_H3}'>逐词详情</h3>", unsafe_allow_html=True)
    verbs = [r["verb"] for r in overview]
    picked = st.selectbox("选择动词", options=verbs, index=verbs.index("walk") if "walk" in verbs else 0)

    stats = get_corpus_word_stats(picked) or {}
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总频次", f"{stats.get('freq', 0):,}")
    m2.metric("每百万频次", f"{(stats.get('relfreq') or 0):.1f}")
    m3.metric("槽位数", stats.get("slot_count", 0))
    m4.metric("搭配词型", f"{stats.get('collocate_count', 0):,}")

    st.markdown(f"<h3 style='{HEADER_H3}'>四类意象图式重心（AI初筛）</h3>", unsafe_allow_html=True)
    scores = get_corpus_schema_scores(picked)
    if scores:
        sc_df = pd.DataFrame(scores).rename(columns={
            "schema_name": "意象图式", "slots_present": "覆盖槽位",
            "slots_defined": "定义槽位", "coverage": "覆盖率",
            "n_types": "搭配词数N", "mean_logdice": "Mean_logDice",
            "prominence_score": "重心得分S", "cand_rank": "候选排名",
        })
        st.bar_chart(sc_df.set_index("意象图式")["重心得分S"], height=220)
        st.dataframe(sc_df, use_container_width=True, hide_index=True)
    else:
        st.info(f"「{picked}」暂无重心得分数据。")

    st.markdown(f"<h3 style='{HEADER_H3}'>图式证据搭配（每图式 Top5）</h3>", unsafe_allow_html=True)
    evidence = get_corpus_schema_evidence(picked, top_n=5)
    if evidence:
        ev_df = pd.DataFrame(evidence).rename(columns={
            "schema_name": "意象图式", "rank_no": "排名", "word": "证据搭配词",
            "logdice": "logDice", "slot": "所在槽位",
        })
        st.dataframe(ev_df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无图式证据数据。")

    st.markdown(f"<h3 style='{HEADER_H3}'>搭配明细（按槽位，可编辑）</h3>", unsafe_allow_html=True)
    st.caption("在「语义类别」填归类（如 空间终点/抽象结果/方式副词），「处理」选 保留/剔除 ——"
               "保存后即进入 PS 计算口径（Mean_logDice × log2(N+1) 只统计「保留」行）。")
    # FX-29 接线（架构 §4/§9 页面经中央注册表调工具）：搭配明细查询改经
    # corpus_evidence 工具 run —— 薄包装 merge_params 按 params_schema 合并
    # 默认值（verb/slot/limit 全在 schema 内）后委托 mysql_db.get_corpus_
    # collocations；本页两处原直调参数原样进 ctx，返回行列表契约不变，行为
    # 与直调逐字节一致（run 不查 enabled 位）。原调用点无 st.cache_data，
    # tool.run 不缓存 —— 缓存纪律无涉；人工标注回写（保存按钮）不经工具，
    # 仍走 update_collocation_annotations 写路径。
    _corpus_tool = get_tool("corpus_evidence")
    slots = sorted({r["slot"] for r in _corpus_tool.run({"verb": picked, "limit": 2000})})
    if slots:
        default_slot = "objects of \"%w\"" if "objects of \"%w\"" in slots else slots[0]
        slot = st.selectbox("选择槽位", options=slots, index=slots.index(default_slot))
        colls = _corpus_tool.run({"verb": picked, "slot": slot, "limit": 100})
        coll_df = pd.DataFrame(colls).rename(columns={
            "id": "_id", "slot": "槽位", "rank_in_slot": "排名", "collocate": "搭配词",
            "logdice": "logDice", "cooccur_count": "搭配频次",
            "typical_combo": "典型组合", "combo_freq": "组合频次",
            "semantic_category": "语义类别(人工)", "keep_flag": "处理(人工)",
        })
        edited = st.data_editor(
            coll_df,
            use_container_width=True,
            hide_index=True,
            key=f"coll_editor_{picked}_{slot}",
            disabled=["槽位", "排名", "搭配词", "logDice", "搭配频次", "典型组合", "组合频次"],
            column_config={
                "语义类别(人工)": st.column_config.TextColumn(width="medium"),
                "处理(人工)": st.column_config.SelectboxColumn(
                    options=["", "保留", "剔除"], width="small"),
            },
        )
        if st.button("💾 保存本槽位语义归类", key=f"coll_save_{picked}_{slot}"):
            changed = []
            for _, row in edited.iterrows():
                # 用 id 对齐原始行，仅保存真正修改过的行
                orig_row = next((c for c in colls if c["id"] == row["_id"]), None)
                if orig_row is None:
                    continue
                if ((orig_row.get("semantic_category") or "") != (row["语义类别(人工)"] or "")
                        or (orig_row.get("keep_flag") or "") != (row["处理(人工)"] or "")):
                    changed.append({
                        "id": int(row["_id"]),
                        "semantic_category": row["语义类别(人工)"],
                        "keep_flag": row["处理(人工)"],
                    })
            if changed:
                n = update_collocation_annotations(changed)
                st.success(f"✅ 已保存 {n} 条归类（进入 PS 计算口径）")
            else:
                st.info("没有修改需要保存")

        n_keep = int((edited["处理(人工)"] == "保留").sum())
        st.caption(f"当前槽位：{len(edited)} 行，标记「保留」{n_keep} 行 —— "
                   f"PS 口径 N={n_keep}，Mean_logDice 按「保留」行的 logDice 均值计。")
    else:
        st.info("暂无搭配明细数据。")


def render_card_corpus(verb: str) -> str:
    """结果页「语料库证据」卡片：词频概览 + 四图式重心得分 + 每图式 Top3 证据。"""
    if not DB_AVAILABLE:
        return ('<div style="padding: 20px;"><p style="color: #718096;">'
                '数据库不可用，无法展示语料证据。</p></div>')

    stats = get_corpus_word_stats(verb)
    scores = get_corpus_schema_scores(verb)
    evidence = get_corpus_schema_evidence(verb, top_n=3)

    html = '''
    <div style="padding: 20px;">
        <h4 style="color: #3182ce; font-weight: 600; margin: 0 0 16px 0;">🌐 语料库证据（enTenTen21）</h4>
    '''

    if not stats:
        html += ('<p style="color: #718096;">该词暂无语料数据。'
                 '运行 scripts/load_corpus_dataset.py 从 output/ 语料包加载。</p>')
        html += "</div>"
        return html

    html += ('<p style="color: #2d3748; margin-bottom: 8px;">'
             '<strong>总频次:</strong> {:,} &nbsp;|&nbsp; '
             '<strong>每百万词频次:</strong> {:.1f} &nbsp;|&nbsp; '
             '<strong>槽位数:</strong> {} &nbsp;|&nbsp; '
             '<strong>搭配词型:</strong> {:,}</p>').format(
        stats.get("freq") or 0, stats.get("relfreq") or 0.0,
        stats.get("slot_count") or 0, stats.get("collocate_count") or 0)

    if scores:
        cand = next((s for s in scores if s["cand_rank"] == 1), None)
        if cand:
            html += ('<p style="color: #2d3748; margin-bottom: 8px;">'
                     '<strong>候选凸显图式（AI初筛）:</strong> '
                     '<span style="color: #3182ce; font-weight: 600;">{}</span></p>').format(
                _html_escape(str(cand["schema_name"])))
        html += ('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px;">'
                 '<tr style="background-color: #ebf8ff;">'
                 '<th style="padding: 6px; text-align: left;">意象图式</th>'
                 '<th style="padding: 6px;">覆盖率</th><th style="padding: 6px;">N</th>'
                 '<th style="padding: 6px;">Mean_logDice</th><th style="padding: 6px;">重心得分S</th>'
                 '</tr>')
        for s in scores:
            html += ('<tr style="border-bottom: 1px solid #e2e8f0;">'
                     '<td style="padding: 6px;">{}</td>'
                     '<td style="padding: 6px; text-align: center;">{:.0%}</td>'
                     '<td style="padding: 6px; text-align: center;">{}</td>'
                     '<td style="padding: 6px; text-align: center;">{:.2f}</td>'
                     '<td style="padding: 6px; text-align: center; font-weight: 600;">{:.2f}</td>'
                     '</tr>').format(
                _html_escape(str(s["schema_name"])), s.get("coverage") or 0,
                s.get("n_types") or 0, s.get("mean_logdice") or 0.0,
                s.get("prominence_score") or 0.0)
        html += '</table>'

    if evidence:
        by_schema = {}
        for e in evidence:
            by_schema.setdefault(e["schema_name"], []).append(e)
        html += '<p style="color: #2d3748; margin-bottom: 4px;"><strong>图式证据搭配（Top3）:</strong></p>'
        for schema, items in by_schema.items():
            words = "、".join(
                f'{_html_escape(str(x["word"]))}（{x.get("logdice") or 0:.1f}）'
                for x in items)
            html += (f'<p style="color: #4a5568; margin: 0 0 6px 0; font-size: 0.95em;">'
                     f'<strong>{_html_escape(str(schema))}：</strong>{words}</p>')

    html += ('<p style="color: #a0aec0; font-size: 0.85em; margin: 8px 0 0 0;">'
             '候选图式为 AI 初筛（未语义归类），详见「语料数据集」页；'
             '最终图式标签以义位人工标注为准。</p>')
    html += "</div>"
    return html


# ============================================
# 词与词关系区块（当前词的词簇交互图）
# ============================================
def render_word_relation_section(verb: str) -> None:
    """
    渲染「当前查询词 + 其所属词簇」的交互式图谱（vis-network iframe）。

    设计要点（相对旧版内嵌 SVG 的改进）：
      * 静态文件 + st.iframe：Streamlit 重跑脚本不会重置图谱的拖拽/缩放状态
        （与知识图谱页同一模式）；
      * 中心词高亮、全部节点标名（力导向布局摊得开，不再互相压盖）；
      * 默认只画「中心词↔成员」连线，簇内两两连线由 iframe 内按钮展开，
        纯前端切换，不触发 Streamlit 重跑。

    Args:
        verb: 当前查询的动词
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>🕸️ 词与词关系</h3>", unsafe_allow_html=True)

    if not DB_AVAILABLE:
        st.info("数据库不可用，无法展示词簇图谱（离线模式下仅提供释义）。")
        return

    try:
        graph = get_cluster_graph(verb)
    except Exception as e:
        logger.error(f"读取词簇图失败 for '{verb}': {e}")
        graph = None

    # R4-1 三口径：None=查询失败；空图=该词未入簇/词库未灌；有数=正常渲染。
    if graph is None:
        st.warning(
            "数据不可用：词簇图谱读取失败（数据库查询出错或连接中断）。"
            "属服务端异常，**勿重跑灌库脚本**；恢复后重新查询即可。"
        )
        return
    if not graph.get("nodes"):
        st.info(
            f"「{verb}」暂无词簇数据。词簇来自词库的次语义范畴划分；"
            "运行 `python scripts/load_word_library.py` 可载入词库及其词间关系。"
        )
        return

    cluster = graph.get("cluster") or {}
    size = cluster.get("size", len(graph["nodes"]))
    intro = (
        f"「<strong>{_html_escape(str(verb))}</strong>」属于词簇 "
        f"<strong>{_html_escape(str(cluster.get('label', '未分组')))}</strong>"
        f" —— 簇内 {size} 个动词语义相近，两两互为近义。"
    )
    st.markdown(f"<p style='{BODY_BASE}'>{intro}</p>", unsafe_allow_html=True)

    url = ensure_cluster_html(graph)
    if url:
        st.iframe(url, height=520)
    else:
        st.warning("词簇图生成失败，请检查 `src/static/` 是否可写。")

    # 簇内成员快跳（点击即切换查询词，图谱随之前进到该词为中心的视图）
    members = [n["id"] for n in graph["nodes"]]
    with st.expander(f"查看簇内全部 {size} 个动词（点击可直接查询）", expanded=False):
        per_row = 6
        for i in range(0, len(members), per_row):
            row = members[i:i + per_row]
            cols = st.columns(per_row)
            for col, member in zip(cols, row):
                with col:
                    label = f"📍 {member}" if member == verb else member
                    st.button(
                        label,
                        key=f"cluster_member_{member}",
                        use_container_width=True,
                        on_click=select_example_verb,
                        args=(member,),
                    )

    # 切页必须在 on_click 回调里改 session_state —— 按钮渲染时机晚于
    # 侧栏 radio(key="page")，在正文里直接赋值会触发 StreamlitAPIException。
    st.button(
        "🗺️ 打开全库知识图谱",
        key="goto_graph_page",
        help="全库 136 词 / 1780 条词间关系的语义地图（可搜索、可按簇过滤）",
        on_click=lambda: st.session_state.update(page="graph"),
    )


# ============================================
# 域—系初判页（domain_family_senses · 词目层初判预览 v0.2）
# ============================================
def render_domain_family_page() -> None:
    """🧭 域系初判：352 保留义位按词目层初判归入三域十二系的浏览与对照。

    数据来自 docs/research/tables/域系初判表v0.2.xlsx（scripts/load_domain_family.py 灌入）。
    口径：词目层初判预览——义位图式暂取词目初判，最终域—系以义位层
    人工标注后重聚类为准；R2/R3 行携带筛选规则理由。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>🧭 域系初判</h1>", unsafe_allow_html=True)
    render_page_usage_guide("domain")

    if not DB_AVAILABLE:
        st.info("数据库不可用，无法展示域系初判（离线模式下仅提供释义）。")
        return
    if not domain_family_ready():
        st.info(
            "域系初判数据尚未灌入。运行 "
            "`MYSQL_HOST=127.0.0.1 python3 scripts/load_domain_family.py` "
            "从 docs/research/tables/域系初判表v0.2.xlsx 加载。"
        )
        return

    import pandas as pd

    overview = get_domain_family_overview()
    if not overview:
        st.warning(
            "域系初判表（domain_family_senses）为空：请重跑 "
            "`MYSQL_HOST=127.0.0.1 python3 scripts/load_domain_family.py` "
            "灌入初判表后刷新本页；刚灌完仍为空属页面缓存，稍候再刷一次。"
        )
        return

    total = sum(r["n_senses"] for r in overview)
    _ = len({r["family"] for r in overview})  # R7-22: 词簇数已由 metrics 卡展示
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("保留义位", total)
    c2.metric("认知域", len({r["domain"] for r in overview}))
    c3.metric("语义系", len({r["family"] for r in overview}))
    c4.metric("口径", "词目层初判 v0.2")

    st.caption(
        "⚠️ 词目层初判预览：义位图式暂取词目初判，非义位层标注结果；"
        "最终域—系体系以义位层人工标注后重聚类为准（见标注平台）。"
    )

    # ---- 总览表（域 → 系 → 数量）----
    st.markdown(f"<h3 style='{HEADER_H3}'>三域十二系总览</h3>", unsafe_allow_html=True)
    df = pd.DataFrame(overview).rename(columns={
        "domain": "认知域（初判）", "family": "语义系（初判）",
        "n_senses": "义位数", "n_verbs": "词数",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.bar_chart(df.set_index("语义系（初判）")["义位数"], height=260)

    # ---- 逐义位明细（域/系/词三级过滤）----
    st.markdown(f"<h3 style='{HEADER_H3}'>逐义位明细</h3>", unsafe_allow_html=True)
    domains = ["全部"] + sorted({r["domain"] for r in overview})
    fcol1, fcol2, fcol3 = st.columns(3)
    sel_domain = fcol1.selectbox("认知域", options=domains, key="df_domain")
    families = ["全部"]
    if sel_domain != "全部":
        families += sorted({r["family"] for r in overview if r["domain"] == sel_domain})
    else:
        families += sorted({r["family"] for r in overview})
    sel_family = fcol2.selectbox("语义系", options=families, key="df_family")
    kw = fcol3.text_input("词目筛选", key="df_verb", placeholder="输入动词…")

    senses = get_domain_family_senses(
        domain=None if sel_domain == "全部" else sel_domain,
        family=None if sel_family == "全部" else sel_family,
    )
    sdf = pd.DataFrame(senses).rename(columns={
        "word": "词目", "sense_num": "义项序号", "sense_id": "SenseID",
        "definition": "英文释义", "definition_cn": "中文释义",
        "example": "例句（首条）",
        "lemma_schema": "词目层初判图式", "domain": "域", "family": "系",
        "sense_annotation": "义位层标注（待人工）",
        "rule_tag": "规则", "rule_note": "规则理由",
        "source": "数据来源", "updated_at": "最后修改",
        "freq": "语料频次", "schema_scores": "四图式重心得分",
    })
    # 展示列序：词目 + 义项序号（组合键）在前，SenseID 生成列随后
    col_order = ["词目", "义项序号", "SenseID", "英文释义", "中文释义",
                 "词目层初判图式", "域", "系", "义位层标注（待人工）",
                 "语料频次", "四图式重心得分", "规则", "规则理由", "数据来源", "最后修改"]
    sdf = sdf[[c for c in col_order if c in sdf.columns]]
    if "语料频次" in sdf.columns:
        sdf["语料频次"] = pd.to_numeric(sdf["语料频次"], errors="coerce")
    if kw:
        sdf = sdf[sdf["词目"].str.contains(kw, case=False, na=False)]
    st.caption(f"当前筛选 {len(sdf)} 条义位。")
    st.dataframe(
        sdf, use_container_width=True, hide_index=True,
        column_config={
            "英文释义": st.column_config.TextColumn(width="medium"),
            "例句（首条）": st.column_config.TextColumn(width="medium"),
            "规则理由": st.column_config.TextColumn(width="medium"),
        },
    )

    # ---- 单义位下钻 ----
    if not sdf.empty:
        st.markdown(f"<h3 style='{HEADER_H3}'>义位详情</h3>", unsafe_allow_html=True)
        sid = st.selectbox(
            "选择义位（word + 义项序号）",
            options=[f"{w} · S{n}" for w, n in zip(sdf["词目"], sdf["义项序号"])],
            key="df_sense",
        )
        _w, _n = sid.rsplit(" · S", 1)
        row = sdf[(sdf["词目"] == _w) & (sdf["义项序号"] == int(_n))].iloc[0]
        b1, b2, b3 = st.columns(3)
        b1.metric("认知域（初判）", row["域"])
        b2.metric("语义系（初判）", row["系"])
        b3.metric("筛选规则", row["规则"])
        st.markdown(f"**SenseID**：{row['SenseID']}（word=`{_w}`，序号={_n}）")
        st.markdown(f"**数据来源**：{row.get('数据来源') or '—'}　·　**最后修改**：{row.get('最后修改') or '—'}")
        # 语料证据（wordsketch，enTenTen21）
        freq_v = row.get("语料频次")
        if freq_v is not None and not pd.isna(freq_v):
            st.markdown(
                f"**语料频次（enTenTen21）**：{int(freq_v):,}")
            scores = row.get("四图式重心得分")
            if isinstance(scores, str):
                try:
                    scores = json.loads(scores)
                except json.JSONDecodeError:
                    scores = None
            if isinstance(scores, dict) and scores:
                best = max(scores, key=scores.get)
                parts = "　".join(f"{k} {v}" for k, v in
                                 sorted(scores.items(), key=lambda x: -x[1]))
                st.markdown(f"**四图式重心得分（词目层初筛）**：{parts}")
                st.caption(f"候选凸显图式：{best}（未语义归类的 AI 初筛，仅作参考）")
        else:
            st.caption("该词目暂无语料证据（初判表未覆盖该词，或语料包缺该词的检索 JSON）。")
        st.markdown(f"**英文释义**：{row['英文释义'] or '—'}")
        if row.get("中文释义"):
            st.markdown(f"**中文释义**：{row['中文释义']}")
        # 全部例句（英文 + 中文翻译逐条对齐，来自例句子表）
        exs = get_domain_family_examples(_w, int(_n))
        if exs:
            st.markdown(f"**例句（{len(exs)} 条）**")
            for ex in exs:
                st.markdown(f"- {ex['example_en'] or '—'}")
                if ex.get("example_cn"):
                    st.markdown(f"  - ↳ {ex['example_cn']}")
            src_note = "、".join(sorted({str(e.get("source") or "—") for e in exs}))
            st.caption(f"例句来源：{src_note}（dictionary.db 例句带已审校中文翻译；OALD10 例句翻译待补）")
        if row["规则理由"]:
            st.info(f"筛选规则理由：{row['规则理由']}")
        st.caption(
            "该义位的最终图式标签请在「🏷️ 标注平台」中人工复核确定；"
            "此处初判归属仅作对照参考。"
        )


# ============================================
# MOVECAT 标注平台（义位准入 + 图式五维标注 + 进度/导出）
# ============================================
# 准入三分 UI 统一口径（RV5-1）：Y（核心）/EXT（拓展）/N（剔除），
# 首现全称 Y=核心物理位移义、EXT=隐喻拓展义、N=非位移剔除。
# 注意分层：权威层 prototype_level / llm_tag 的存储值仍含中文「拓展」
# （word_source.PROTOTYPE_METAPHOR="拓展"，存量数据不动），
# 显示层经 LEVEL_LABELS / _status 等映射统一按 EXT 展示；提交层
# （annotation_submissions payload）本就用 Y/EXT/N。
LEVEL_OPTIONS = ["", "Y", "拓展", "N"]
LEVEL_LABELS = {"": "（未标注）", "Y": "Y · 核心物理位移义",
                "拓展": "EXT · 隐喻拓展义", "N": "N · 非位移剔除"}
SCHEMA_OPTIONS = ["", "源点脱离图式", "终点抵达图式", "方式伴随图式", "互动位移图式"]
ALIGNMENT_OPTIONS = ["", "完全对齐", "部分对齐", "零对齐"]

# ---- 多人提交流常量（规范 §2 注释：payload["admission"] ∈ "Y|EXT|N"）----
SUBMIT_ADMIT_OPTIONS = ["", "Y", "EXT", "N"]
SUBMIT_ADMIT_LABELS = {"": "（未选择）", "Y": "Y · 核心物理位移义",
                       "EXT": "EXT · 隐喻拓展义", "N": "N · 非位移剔除"}
# LLM 草稿列（llm_tag 权威层存储值，键含「拓展」）→ 提交口径（Y/EXT/N）
_LLM_TAG_TO_ADMIT = {"Y": "Y", "拓展": "EXT", "N": "N"}


def render_annotation_page() -> None:
    """🏷️ 标注平台（按角色分派；规范 §5，权限判定在渲染入口 §6-4）。

    R1-2 收口（施工规范 §14 批次 12）：入口判定从 legacy role 列改为
    **有效六角色集**（users_db.effective_six_roles，与侧边栏可见性同源）
    —— 授予式用户（legacy 列与 user_roles 授予不一致，如旧列 viewer 但已
    grant_role('annotator')）不再被拦在页外；判定口径：

    * viewer 单角色（有效集除 viewer 外为空） → 无权限提示；
    * dict_admin（legacy admin 经映射两位一体自然命中）→ 既有单人流全部
      保留（原表单直写权威层的快速通道），页面顶部加快速通道提示 ——
      直写权威层是词典数据写操作，与 guards.require_dict_admin 同口径；
    * reviewer / dict_admin / sys_admin → 多人提交流 + 分歧清单与仲裁面板；
    * editor / annotator → 多人提交流（annotator 互不可见，规范 §0 独立性）。
    """
    user = _current_user()
    effective = effective_six_roles(user)

    if not (effective - {"viewer"}):
        st.warning("⛔ 无权限：标注平台需要 annotator / editor / reviewer / "
                   "dict_admin / sys_admin 任一角色（viewer 只读）。")
        return

    if "dict_admin" in effective:
        st.info(
            "🛠️ 管理员快速通道：本页表单**直写权威层**（word_senses / oald_senses）；"
            "多人提交流见「📥 标注提交」页。",
            icon="🛠️",
        )
        _render_annotation_admin_view()
        return

    # annotator / reviewer（及 editor / sys_admin 过渡兼容）：多人提交流（AI 草稿可见，验收 V7）
    st.markdown(f"<h1 style='{HEADER_H1}'>🏷️ 标注平台</h1>", unsafe_allow_html=True)
    render_page_usage_guide("submission")
    render_submission_flow()
    if effective & {"dict_admin", "sys_admin", "reviewer"}:
        render_reviewer_panel()


def _render_annotation_admin_view() -> None:
    """
    🏷️ 标注平台 · 管理员快速通道视图（原单人流，逻辑不变）。

    对应标注手册（docs/research/protocols/义项判定标准修改稿.docx）的义位级操作：
      标准1 准入标签（Y/EXT/N）→ 标准2 意象图式（四选一）→
      标准4 英汉对齐（三选一）→ 汉语句法特征 / 译义转化策略；
      边界争议打存疑标记进仲裁清单。判定依据 = OALD 释义 + 例句，
      页面同屏提供语料证据（候选图式 + 重心得分）辅助判断。
    """
    import pandas as pd

    st.markdown(f"<h1 style='{HEADER_H1}'>🏷️ 标注平台</h1>", unsafe_allow_html=True)
    render_page_usage_guide("annotate")
    st.caption("义位准入 → 意象图式 → 英汉对齐 → 句法特征/译义策略；"
               "依据 OALD 释义与例句判定，存疑案例打标进仲裁清单。"
               "完整标准见 docs/research/protocols/义项判定标准修改稿.docx。")

    if not DB_AVAILABLE:
        st.info("数据库不可用，标注平台不可用。")
        return

    progress = get_annotation_progress()
    # R4-1 三口径：None=查询失败（勿重跑灌库）；[]=词库未灌（给灌库指引）。
    if progress is None:
        st.warning(
            "数据不可用：标注进度读取失败（数据库查询出错或连接中断）。"
            "属服务端异常，**勿重跑灌库脚本**；恢复后刷新本页即可。"
        )
        return
    if not progress:
        st.info("词库为空：先运行 `python scripts/load_word_library.py` 灌入义位。")
        return

    total = sum(int(r["total"]) for r in progress)
    reviewed = sum(int(r["reviewed"] or 0) for r in progress)   # 人工复核（经标注平台保存）
    # 词库初标数（prototype_level 预填）当前未单独展示：初标≠人工复核，避免口径混淆
    flagged = sum(int(r["flagged"]) for r in progress)          # 待复核/存疑清单
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("义位总数", total)
    c2.metric("人工已复核", reviewed, f"{reviewed / total:.0%}" if total else None)
    c3.metric("待复核清单", flagged)
    c4.metric("习语义项", sum(int(r["idioms"] or 0) for r in progress))
    st.progress(reviewed / total if total else 0.0)

    # ---- 动词选择（带各自进度）----
    label_map = {
        r["verb"]: f"{r['verb']}（{r['total']} 义位 · {int(r['reviewed'] or 0)} 已复核"
                   f"{' · ' + str(int(r['flagged'])) + ' 待复核' if int(r['flagged']) else ''}）"
        for r in progress
    }
    verbs = [r["verb"] for r in progress]

    # 试点子集（docs/1003 大纲 §4.1：10–12 词，标准与理由见 data/corpus/pilot_verbs.json）
    _pilot_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "corpus", "pilot_verbs.json")
    try:
        with open(_pilot_path, encoding="utf-8") as _f:
            PILOT_VERBS = [v["verb"] for v in json.load(_f)["verbs"]]
    except (OSError, json.JSONDecodeError, KeyError):
        PILOT_VERBS = []
    pilot_only = st.checkbox("仅显示试点动词（12 词，见 pilot_verbs.json）",
                             value=bool(PILOT_VERBS), key="pilot_only")
    if pilot_only and PILOT_VERBS:
        verbs = [v for v in verbs if v in PILOT_VERBS] or verbs

    picked_verb = st.selectbox("选择动词", options=verbs,
                               format_func=lambda v: label_map.get(v, v),
                               index=verbs.index("walk") if "walk" in verbs else 0)

    senses = get_oald_senses(picked_verb)
    if senses is None:
        st.warning(
            f"数据不可用：「{picked_verb}」的 OALD 义项读取失败"
            "（数据库查询出错或连接中断），勿重跑灌库脚本，稍后重试。"
        )
        return
    if not senses:
        st.warning(f"「{picked_verb}」无 OALD 义项数据。"
                   f"（研究词表 996 义位 = 992 OALD + 4 人工补充"
                   f" scutter/kayak/oar/dodder，均已在库。）")
        return

    # ---- 语料证据辅助（判定依据之一）----
    cstats = get_corpus_word_stats(picked_verb)
    cscores = get_corpus_schema_scores(picked_verb)
    if cstats and cscores:
        cand = next((s for s in cscores if s["cand_rank"] == 1), None)
        st.info(
            "🌐 语料证据（enTenTen21，辅助判断）："
            f"总频次 {(cstats.get('freq') or 0):,} · 每百万 {(cstats.get('relfreq') or 0):.1f} · "
            f"候选凸显图式（AI初筛）：**{cand['schema_name'] if cand else '—'}**"
            f"（S={cand['prominence_score']:.2f}）" if cand else "🌐 语料证据：暂无",
            icon="🔎",
        )

    # ---- 义位选择 ----
    only_open = st.checkbox("只看待标注/存疑义位", value=False)
    def _status(s):
        """义位条目的审定状态徽标文案：存疑优先，其余按层级标签折算（RV5-1）。"""
        if s.get("needs_review"):
            return "❓存疑"
        # 权威层存储值「拓展」统一显示为 EXT（RV5-1，口径见 LEVEL_LABELS 注释）
        return {"Y": "✅Y", "拓展": "✅EXT", "N": "✅N"}.get(
            (s.get("prototype_level") or "").strip(), "⬜未标")

    sense_opts = [
        f"{picked_verb}-S{s['sense_index']} · {_status(s)} · {(s.get('en_ndef') or '')[:40]}"
        for s in senses
    ]
    if only_open:
        keep = [i for i, s in enumerate(senses)
                if not (s.get("prototype_level") or "").strip() or s.get("needs_review")]
        pairs = [(sense_opts[i], senses[i]) for i in keep]
    else:
        pairs = list(zip(sense_opts, senses))
    if not pairs:
        st.success("该筛选条件下没有待处理义位 🎉")
        return
    chosen = st.selectbox("选择义位（SenseID）", options=[p[0] for p in pairs])
    sense = dict(pairs[[p[0] for p in pairs].index(chosen)][1])

    sid = sense["id"]
    sense_id_label = f"{picked_verb}-S{sense['sense_index']}"

    st.markdown(f"<h3 style='{HEADER_H3}'>义位 {sense_id_label}</h3>", unsafe_allow_html=True)
    idiom = bool(sense.get("is_idiom"))
    if idiom:
        st.warning("习语义项（IDIOMS 组）—— 按标注手册一般归入 N 或 EXT")
    # 义项来源徽章：研究词表 996 = 992 OALD10 + 4 人工补充 —— 来源在 UI 可见，
    # 人工撰写条（无词典原文背书）复核时应加倍留意
    _src = str(sense.get("source") or "OALD10")
    if _src != "OALD10":
        st.info(f"📝 义项来源：**{_src}**（OALD10 未收录，据 Levin brief 与语料人工撰写）",
                icon="📝")
    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<p style='{BODY_BASE}'><strong>英文释义：</strong>{_html_escape(str(sense.get('definition') or '—'))}</p>"
        f"<p style='{BODY_BASE}'><strong>语法码：</strong>{_html_escape(str(sense.get('grammar') or '—'))}</p>"
        f"<p style='{BODY_BASE}'><strong>语义分组：</strong>{_html_escape(str(sense.get('sense_group') or '—'))}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
    exs = sense.get("examples") or []
    if exs:
        with st.expander(f"真实例句（{len(exs)} 条）——判定证据"):
            for e in exs:
                st.markdown(f"- {_html_escape(str(e))}")

    # ---- LLM 初筛草稿（候选参考，非最终判定）----
    if sense.get("llm_tag"):
        _draft = (
            f"🤖 **LLM 初筛草稿（候选参考，须人工确认）**：准入 **{sense['llm_tag']}**"
            f" · 图式 **{sense.get('llm_schema') or '—'}**"
            f" · 对齐 **{sense.get('llm_align') or '—'}**"
        )
        st.info(_draft, icon="🤖")
        if sense.get("llm_reason"):
            st.markdown(f"<div style='{get_card_style()}'>"
                        f"<p style='{BODY_BASE}'><strong>初筛理由：</strong>"
                        f"{_html_escape(str(sense['llm_reason']))}</p>"
                        + (f"<p style='{BODY_BASE}'><strong>存疑点：</strong>"
                           f"{_html_escape(str(sense['llm_doubt']))}</p>"
                           if sense.get("llm_doubt") else "")
                        + "</div>", unsafe_allow_html=True)

    # ---- 五维标注表单 ----
    st.markdown(f"<h3 style='{HEADER_H3}'>图式五维标注</h3>", unsafe_allow_html=True)
    with st.form(f"ann_form_{sid}"):
        f1, f2 = st.columns(2)
        # 默认值优先级：人工已保存的标注 > LLM 初筛草稿 > 空
        _cur_level = (sense.get("prototype_level") or "").strip()
        _draft_level = (sense.get("llm_tag") or "").strip()
        _init_level = _cur_level if _cur_level in LEVEL_OPTIONS else (
            _draft_level if _draft_level in LEVEL_OPTIONS else "")
        level = f1.radio("准入标签（标准1）", options=LEVEL_OPTIONS,
                         index=LEVEL_OPTIONS.index(_init_level),
                         format_func=lambda v: LEVEL_LABELS[v], horizontal=True)
        _cur_schema = (sense.get("image_schema") or "").strip()
        _draft_schema = (sense.get("llm_schema") or "").strip()
        _init_schema = _cur_schema if _cur_schema in SCHEMA_OPTIONS else (
            _draft_schema if _draft_schema in SCHEMA_OPTIONS else "")
        schema = f2.selectbox("意象图式（标准2，四选一）", options=SCHEMA_OPTIONS,
                              index=SCHEMA_OPTIONS.index(_init_schema))
        _cur_align = (sense.get("alignment") or "").strip()
        _draft_align = (sense.get("llm_align") or "").strip()
        _init_align = _cur_align if _cur_align in ALIGNMENT_OPTIONS else (
            _draft_align if _draft_align in ALIGNMENT_OPTIONS else "")
        align = st.selectbox("英汉对齐等级（标准4）", options=ALIGNMENT_OPTIONS,
                             index=ALIGNMENT_OPTIONS.index(_init_align))
        cn_syn = st.text_input("汉语句法特征", value=sense.get("cn_syntax") or "",
                               placeholder="如：强制趋向补语 / 需“把”字句 / 动词可独立作谓语")
        strategy = st.text_input("译义转化策略", value=sense.get("translation_strategy") or "",
                                 placeholder="如：保留原图式 / 增补方式要素 / 舍弃方式语义")
        review = st.checkbox("❓ 复核后仍存疑（边界案例，进仲裁清单）",
                             value=bool(sense.get("needs_review")))
        saved = st.form_submit_button("💾 保存本义位标注", type="primary")
        if saved:
            ok = update_sense_annotation(
                sid,
                level.strip(), schema.strip(), align.strip(),
                cn_syn.strip(), strategy.strip(), review,
            )
            if ok:
                st.success(f"✅ {sense_id_label} 标注已保存")
                st.session_state.pop("_display_def_cache", None)
            else:
                st.error("保存失败（数据库写入未成功），请重试")

    # ---- 导出 ----
    st.markdown(f"<h3 style='{HEADER_H3}'>📤 导出标注资源</h3>", unsafe_allow_html=True)
    rows = get_annotation_export_rows()
    if rows:
        export_df = pd.DataFrame(rows)
        export_df.insert(2, "SenseID", export_df["verb"] + "-S" + export_df["sense_index"].astype(str))
        # CSV 公式注入防护（R1-P2）：文本以 = + - @ \t 开头时前置单引号
        csv = sanitize_csv_dataframe(export_df).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "导出全部义位标注 (CSV)", data=csv,
            file_name=f"movecat_annotations_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
        st.caption(f"共 {len(rows)} 条义位（含未标注行，便于核对覆盖面）。")


# ============================================
# 多人标注提交流（规范 §5 用户决策③④；验收 V2/V7）—— app.py 新增视图
# ============================================
def _submission_sense_status(s: dict) -> str:
    """义位当前状态徽标文字（与标注平台状态口径一致的简化版）。"""
    if s.get("needs_review"):
        return "❓存疑"
    # 权威层存储值「拓展」统一显示为 EXT（RV5-1，口径见 LEVEL_LABELS 注释）
    return {"Y": "✅Y", "拓展": "✅EXT", "N": "✅N"}.get(
        (s.get("prototype_level") or "").strip(), "⬜未标")


def render_submission_page() -> None:
    """📥 标注提交页：多人提交流的独立入口（annotator/reviewer/admin）。

    权限判定在渲染入口（规范 §6-4），R1-2 收口为有效六角色集判定（授予式
    用户不再被 legacy 列拦在页外）：有效集除 viewer 外为空 → 无权限；
    reviewer/dict_admin/sys_admin 额外渲染分歧清单与仲裁面板。admin 的
    单人流快速通道在「🏷️ 标注平台」页。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>📥 标注提交</h1>", unsafe_allow_html=True)
    render_page_usage_guide("submission")

    effective = effective_six_roles(_current_user())
    if not (effective - {"viewer"}):
        st.warning("⛔ 无权限：标注提交需要 annotator / editor / reviewer / "
                   "dict_admin / sys_admin 任一角色（viewer 只读）。")
        return

    render_submission_flow()
    if effective & {"dict_admin", "sys_admin", "reviewer"}:
        render_reviewer_panel()


def render_submission_flow() -> None:
    """多人提交流视图：选动词 → 选义位 → LLM 初筛草稿 → 表单 → submit_annotation。

    独立性（规范 §0 / 用户决策④）：本视图只经 get_my_submissions 展示
    **本人**提交 —— annotator 角色下页面不存在任何他人数据入口；
    全部提交/分歧清单只在 render_reviewer_panel（reviewer/admin 门）。
    """
    user = _current_user()
    if user is None:
        st.warning("请先登录")
        return
    if not DB_AVAILABLE:
        st.info("数据库不可用，提交流不可用（离线模式）。")
        return
    _ensure_flow_tables_once()

    coder_id = int(user.get("id") or 0)
    st.caption("提交流：准入（Y/EXT/N）→ 意象图式 → 英汉对齐 → 句法/策略；"
               "写入 annotation_submissions（同一义位重复提交=覆盖更新）。")

    progress = get_annotation_progress()
    # R4-1 三口径（与标注平台同口径）
    if progress is None:
        st.warning(
            "数据不可用：标注进度读取失败（数据库查询出错或连接中断）。"
            "属服务端异常，**勿重跑灌库脚本**；恢复后刷新本页即可。"
        )
        return
    if not progress:
        st.info("词库为空：先运行 `python scripts/load_word_library.py` 灌入义位。")
        return
    verbs = [r["verb"] for r in progress]
    picked_verb = st.selectbox(
        "选择动词", options=verbs,
        index=verbs.index("walk") if "walk" in verbs else 0,
        key="submission_verb",
    )

    senses = get_oald_senses(picked_verb)
    if senses is None:
        st.warning(
            f"数据不可用：「{picked_verb}」的 OALD 义项读取失败"
            "（数据库查询出错或连接中断），勿重跑灌库脚本，稍后重试。"
        )
        return
    if not senses:
        st.warning(f"「{picked_verb}」无 OALD 义项数据。")
        return

    sense_opts = [
        f"{picked_verb}-S{s['sense_index']} · {_submission_sense_status(s)} · "
        f"{(s.get('en_ndef') or '')[:40]}"
        for s in senses
    ]
    chosen = st.selectbox("选择义位（SenseID）", options=sense_opts, key="submission_sense")
    sense = dict(senses[sense_opts.index(chosen)])
    sid = sense["id"]
    sense_id_label = f"{picked_verb}-S{sense['sense_index']}"

    idiom = bool(sense.get("is_idiom"))
    if idiom:
        st.warning("习语义项（IDIOMS 组）—— 按范畴包准入标准一般归入 N 或 EXT")
    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<p style='{BODY_BASE}'><strong>英文释义：</strong>"
        f"{_html_escape(str(sense.get('definition') or '—'))}</p>"
        f"<p style='{BODY_BASE}'><strong>语法码：</strong>"
        f"{_html_escape(str(sense.get('grammar') or '—'))}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
    exs = sense.get("examples") or []
    if exs:
        with st.expander(f"真实例句（{len(exs)} 条）——判定证据"):
            for e in exs:
                st.markdown(f"- {_html_escape(str(e))}")

    # ---- LLM 初筛草稿（验收 V7：全员看同样草稿，必须可见）----
    if sense.get("llm_tag"):
        st.info(
            f"🤖 **LLM 初筛草稿（候选参考，须人工确认）**：准入 **{sense['llm_tag']}**"
            f" · 图式 **{sense.get('llm_schema') or '—'}**"
            f" · 对齐 **{sense.get('llm_align') or '—'}**",
            icon="🤖",
        )
        if sense.get("llm_reason"):
            st.markdown(
                f"<div style='{get_card_style()}'>"
                f"<p style='{BODY_BASE}'><strong>初筛理由：</strong>"
                f"{_html_escape(str(sense['llm_reason']))}</p>"
                + (f"<p style='{BODY_BASE}'><strong>存疑点：</strong>"
                   f"{_html_escape(str(sense['llm_doubt']))}</p>"
                   if sense.get("llm_doubt") else "")
                + "</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("该义位暂无 LLM 初筛草稿（可直接人工判定）。")

    # ---- 范畴包判定标准（R-2 收口：按当前标注义位所属范畴取包，只读展示）----
    # 范畴来源 = 标注页当前选中范畴（session/参数）：本提交流未提供范畴选择
    # 件（提交流本体的范畴切换属 R-3 范围），取不到时按 CATEGORIES() 首个
    # 范畴包取数并在 expander 标题注明；提交流接入范畴切换后本取数自动跟随。
    _ann_cat = CATEGORIES()[0] if CATEGORIES() else ""
    with st.expander(f"📋 准入判定标准（configs/{_ann_cat or '—'} 范畴包，只读）",
                     expanded=False):
        try:
            _adm = load_pack(_ann_cat).get("admission") or {}
            _od = str(_adm.get("operational_definition") or "").strip()
            if _od:
                st.markdown(f"**操作性定义**：{_html_escape(_od)}")
            for _cls in (_adm.get("admission_classes") or []):
                st.markdown(
                    f"- **{_html_escape(str(_cls.get('code') or ''))}** "
                    f"{_html_escape(str(_cls.get('name') or ''))}："
                    f"{_html_escape(str(_cls.get('rule') or ''))}"
                )
            for _br in (_adm.get("boundary_rules") or []):
                _between = "/".join(str(x) for x in (_br.get("between") or []))
                st.markdown(
                    f"- 边界条款 {_html_escape(str(_br.get('id') or ''))}"
                    f"（{_html_escape(_between)}）："
                    f"{_html_escape(str(_br.get('rule') or ''))}"
                )
        except Exception as e:
            st.caption(f"范畴包不可用：{_html_escape(str(e))}")

    # ---- 标注表单（预填优先级：本人上次提交 > LLM 初筛草稿 > 空）----
    st.markdown(f"<h3 style='{HEADER_H3}'>标注表单（motion · admission 任务）</h3>",
                unsafe_allow_html=True)
    my_prev = {
        s["sense_id"]: (s.get("payload") or {})
        for s in get_my_submissions(coder_id, "motion", "admission")
    }
    prev = my_prev.get(sid) or {}

    _adm_prev = str(prev.get("admission") or "").strip()
    _adm_draft = _LLM_TAG_TO_ADMIT.get(str(sense.get("llm_tag") or "").strip(), "")
    _init_adm = _adm_prev if _adm_prev in SUBMIT_ADMIT_OPTIONS else (
        _adm_draft if _adm_draft in SUBMIT_ADMIT_OPTIONS else "")
    _schema_prev = str(prev.get("schema") or "").strip()
    _schema_draft = str(sense.get("llm_schema") or "").strip()
    _init_schema = _schema_prev if _schema_prev in SCHEMA_OPTIONS else (
        _schema_draft if _schema_draft in SCHEMA_OPTIONS else "")
    _align_prev = str(prev.get("alignment") or "").strip()
    _align_draft = str(sense.get("llm_align") or "").strip()
    _init_align = _align_prev if _align_prev in ALIGNMENT_OPTIONS else (
        _align_draft if _align_draft in ALIGNMENT_OPTIONS else "")

    with st.form(f"submission_form_{sid}"):
        f1, f2 = st.columns(2)
        admission = f1.radio(
            "准入标签（标准1：Y/EXT/N）", options=SUBMIT_ADMIT_OPTIONS,
            index=SUBMIT_ADMIT_OPTIONS.index(_init_adm),
            format_func=lambda v: SUBMIT_ADMIT_LABELS.get(v, v), horizontal=True,
        )
        schema = f2.selectbox("意象图式（标准2，四选一）", options=SCHEMA_OPTIONS,
                              index=SCHEMA_OPTIONS.index(_init_schema))
        align = st.selectbox("英汉对齐等级（标准4）", options=ALIGNMENT_OPTIONS,
                             index=ALIGNMENT_OPTIONS.index(_init_align))
        cn_syn = st.text_input(
            "汉语句法特征", value=str(prev.get("cn_syntax") or sense.get("cn_syntax") or ""),
            placeholder="如：强制趋向补语 / 需“把”字句 / 动词可独立作谓语")
        strategy = st.text_input(
            "译义转化策略", value=str(prev.get("strategy") or sense.get("translation_strategy") or ""),
            placeholder="如：保留原图式 / 增补方式要素 / 舍弃方式语义")
        review = st.checkbox(
            "❓ 存疑（边界案例，建议进仲裁清单）",
            value=bool(prev.get("needs_review", sense.get("needs_review"))))
        saved = st.form_submit_button("📤 提交本义位标注", type="primary")
        if saved:
            if not admission:
                st.error("请先选择准入标签（Y / EXT / N）。")
            else:
                # 留空的可选字段不入 payload（缺失 ≠ 空串，避免污染分歧比对）
                payload: Dict[str, Any] = {"admission": admission, "needs_review": bool(review)}
                if schema:
                    payload["schema"] = schema
                if align:
                    payload["alignment"] = align
                if cn_syn.strip():
                    payload["cn_syntax"] = cn_syn.strip()
                if strategy.strip():
                    payload["strategy"] = strategy.strip()
                # FX-35 工具页面接线（规范 §4「页面经中央注册表调工具」，照
                # semantic_search.py 接线先例）：准入提交改经 get_tool("admission")
                # .run(...) —— merge_params 按 params_schema 合并默认值后以
                # task_type="admission" 固定委托 submit_annotation；registry 查
                # 不到回落原直调，两路逐字节等价（category/sense_id/coder_id/
                # payload 全在 schema 内；task_type 是工具身份不入 ctx，页面原
                # 直调传的也是字面 "admission"；ai_assisted schema 默认 True 与
                # 直调形参默认同值）。原调用点无 st.cache_data，缓存纪律无涉。
                _admission_tool = get_tool("admission")
                _submitted = (
                    _admission_tool.run({"category": "motion", "sense_id": sid,
                                         "coder_id": coder_id, "payload": payload})
                    if _admission_tool is not None else
                    submit_annotation("motion", sid, "admission", coder_id, payload)
                )
                if _submitted:
                    st.success(f"✅ {sense_id_label} 提交成功"
                               f"（同一义位重复提交=覆盖更新，覆盖后需重新审核）")
                else:
                    st.error("提交失败（数据库写入未成功或校验未通过），请重试")

    # ---- 我的提交记录（独立性：仅本人；form 处理后查询，本轮提交已入库）----
    st.markdown(f"<h3 style='{HEADER_H3}'>📄 我的提交记录</h3>", unsafe_allow_html=True)
    my_subs = get_my_submissions(coder_id, "motion", "admission")
    if my_subs:
        rows = []
        for s in my_subs:
            p = s.get("payload") or {}
            rows.append({
                "sense_id": s.get("sense_id"),
                "准入": str(p.get("admission") or "—"),
                "图式": str(p.get("schema") or "—"),
                "对齐": str(p.get("alignment") or "—"),
                "汉语句法": str(p.get("cn_syntax") or "—"),
                "译义策略": str(p.get("strategy") or "—"),
                "存疑": "是" if p.get("needs_review") else "否",
                "状态": "已定稿" if s.get("status") == STATUS_ADJUDICATED else "已提交",
                "提交时间": str(s.get("submitted_at") or "—"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"共 {len(my_subs)} 条 · 独立性：仅本人提交可见"
                   f"（annotator 之间互相不可见，规范 §0）。")
    else:
        st.info("暂无提交记录。")


def render_reviewer_panel() -> None:
    """⚖️ 仲裁面板（reviewer/admin）：分歧清单（各编码人取值对照）→ 金标定稿。

    权限判定在函数入口（规范 §6-4），R1-2 收口为有效六角色集（与信度页
    同一允许集 dict_admin/sys_admin/reviewer）：annotator/viewer 一律拦截 ——
    detect_disagreements / get_submissions_for_sense 属「看全部」入口，
    不得暴露给 annotator（用户决策④）。授予式 reviewer（legacy 列 viewer
    但 user_roles 已授予 reviewer）自此放行。
    """
    user = _current_user()
    if user is None:
        st.warning("请先登录")
        return
    if not (effective_six_roles(user) & {"dict_admin", "sys_admin", "reviewer"}):
        st.error("⛔ 仲裁面板仅 reviewer / admin 可用（annotator 之间互相不可见，规范 §0）。")
        return
    if not DB_AVAILABLE:
        st.info("数据库不可用，仲裁面板不可用（离线模式）。")
        return
    _ensure_flow_tables_once()

    adjudicator_id = int(user.get("id") or 0)
    st.markdown(f"<h2 style='{HEADER_H2}'>⚖️ 分歧清单与仲裁</h2>", unsafe_allow_html=True)
    st.caption("同一义位被多人提交且取值不一的字段在此对照；定稿金标后"
               "参与的提交置为 adjudicated 并退出信度/分歧口径。")

    # 定稿成功提示跨 rerun 展示（定稿后该义位退出分歧清单，列表会整体刷新）
    _done = st.session_state.pop("_adjudication_done", None)
    if _done:
        st.success(str(_done))

    disagreements = detect_disagreements("motion", "admission")
    if not disagreements:
        st.success("当前没有分歧条目（各编码人取值一致、不足两人，或已全部定稿）。")
    else:
        # coder_id → 展示名（reviewer/admin 可见全部用户，规范 §1）
        id2name: Dict[str, str] = {}
        try:
            for u in list_users():
                id2name[str(int(u.get("id") or 0))] = str(
                    u.get("display_name") or u.get("username") or f"#{u.get('id')}")
        except Exception as e:
            logger.error(f"仲裁面板读取用户映射失败: {e}")

        for d in disagreements:
            verb = str(d.get("verb") or f"sense {d.get('sense_id')}")
            sidx = d.get("sense_index")
            label = f"{verb}-S{sidx}" if sidx is not None else f"sense {d.get('sense_id')}"
            n_fields = len(d.get("fields") or [])
            with st.expander(
                f"⚠️ {label}（{d.get('n_submissions', 0)} 人提交 · {n_fields} 项分歧）"
            ):
                for fitem in (d.get("fields") or []):
                    field = str(fitem.get("field") or "")
                    values = fitem.get("values") or {}
                    pairs = "；".join(
                        f"{_html_escape(id2name.get(str(k), f'编码人{k}'))}："
                        f"{_html_escape(str(v))}"
                        for k, v in values.items()
                    )
                    st.markdown(
                        f"<p style='{BODY_BASE}'>• <strong>"
                        f"{_html_escape(field)}</strong>：{pairs}</p>",
                        unsafe_allow_html=True,
                    )

                submissions = get_submissions_for_sense(d["sense_id"], "admission")
                sub_ids = [int(s["id"]) for s in submissions]
                with st.form(f"adjudicate_form_{d['sense_id']}"):
                    g1, g2 = st.columns(2)
                    g_adm = g1.radio(
                        "金标准入", options=SUBMIT_ADMIT_OPTIONS,
                        index=0,
                        format_func=lambda v: SUBMIT_ADMIT_LABELS.get(v, v),
                        horizontal=True,
                    )
                    g_schema = g2.selectbox("金标意象图式", options=SCHEMA_OPTIONS, index=0)
                    g_align = st.selectbox("金标英汉对齐", options=ALIGNMENT_OPTIONS, index=0)
                    g_doubt = st.checkbox("定稿后仍存疑（保留在复核清单）", value=False)
                    g_note = st.text_input("仲裁说明（note）", placeholder="定稿理由 / 依据条款")
                    ok_btn = st.form_submit_button("💾 保存仲裁定稿（金标）", type="primary")
                if ok_btn:
                    if not g_adm:
                        st.error("请先选择金标准入标签（Y / EXT / N）。")
                    else:
                        gold: Dict[str, Any] = {"admission": g_adm, "needs_review": bool(g_doubt)}
                        if g_schema:
                            gold["schema"] = g_schema
                        if g_align:
                            gold["alignment"] = g_align
                        if save_adjudication(d["sense_id"], "admission", adjudicator_id,
                                             gold, sub_ids, (g_note.strip() or None),
                                             actor=user):
                            # 提示写入会话旗标再 rerun：直接 st.success 会被
                            # st.rerun() 丢弃（本 run 输出整体作废）
                            st.session_state["_adjudication_done"] = (
                                f"✅ {label} 仲裁定稿已保存"
                                f"（{len(sub_ids)} 条参与提交置为 adjudicated）。")
                            st.rerun()
                        else:
                            st.error("仲裁保存失败（数据库写入未成功），请重试。")

    # ---- 任务分配进度概览（reviewer/admin 概览用）----
    with st.expander("📊 任务分配进度（get_assignment_stats）", expanded=False):
        stats = get_assignment_stats()
        if stats:
            st.dataframe(
                pd.DataFrame([{
                    "标注员": str(r.get("display_name") or r.get("username") or f"#{r.get('assignee_id')}"),
                    "范畴": r.get("category"),
                    "任务": r.get("task_type"),
                    "分配状态": r.get("assignment_status") or "（自发）",
                    "已提交": r.get("n_submitted"),
                    "已定稿": r.get("n_adjudicated"),
                } for r in stats]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("暂无任务分配/提交数据。")


# ============================================
# 主函数
# ============================================
def main():
    """主函数：按 session_state["page"] 分派到各页（十七页（16 显式分支 +
    search 兜底）：十二功能页 +
    词典管理/AI 协作/撰写审校/例证对译四工作区页 + 帮助中心；规范 §5 UI 集成契约；
    批次 8「🏃‍♀️ 范畴深挖」并入「📊 语义分析」后 15→14，批次 9 增 writing/lexical）。

    登录门在分派处判定（require_login，规范 §6-4）：标注页与新增三页
    （submission / users_admin / reliability）未登录渲染「请先登录」并 return；
    角色门在各页渲染入口再判一次（纵深防御）。
    _page 在 render_sidebar 之前取值：侧边栏可能因角色可见性把残留页重置回
    search（只影响下一次运行），本次运行仍按用户请求的页分派并给出权限提示。
    旧键重定向（批次 8）：_page == "category" 就地置 "cluster" —— 页面合并后
    旧书签/残留会话重定向一次不断链；置于 render_sidebar 之前，radio(key="page")
    本次运行即选中 cluster，cluster 不可见的会话（未登录）由侧边栏残留页回退兜回
    search，本次运行照常走 cluster 分支给出「请先登录」提示。
    """
    _page = st.session_state.get("page")
    if _page == "category":
        _page = "cluster"
        st.session_state["page"] = "cluster"
    render_sidebar()
    # R1-6 全清配套的一次性登出提示（_logout 落旗标，这里 pop 即消费）：
    # 全清后不再有「残留受保护页」供登录门拦截提示，退出即显式提示会话
    # 已清空须重新登录（与旧版「请先登录」提示同一用户可见语义）。
    if st.session_state.pop(_LOGOUT_FLASH_KEY, None):
        st.warning("已退出登录：会话数据已清空，请先登录后再访问受保护页面。")
    # RV12-2：每轮渲染弹出一次性提示队列（各页写操作 success 后 st.rerun
    # 丢弃提示的问题 —— 上一轮 ui_kit.flash 落的提示在这里消费转渲染，
    # 置于页面分派之前，位于正文顶部；队列消费即清空不跨轮重复）。
    ui_kit.pop_and_render_flash()
    if _page == "graph":
        render_interactive_graph_page()
    elif _page == "corpus":
        render_corpus_dataset_page()
    elif _page == "domain":
        render_domain_family_page()
    elif _page == "annotate":
        if require_login() is not None:
            render_annotation_page()
    elif _page == "submission":
        if require_login() is not None:
            render_submission_page()
    elif _page == "users_admin":
        if require_login() is not None:
            render_users_admin_entry()
    elif _page == "reliability":
        if require_login() is not None:
            render_reliability_entry()
    elif _page == "cluster":
        if require_login() is not None:
            render_cluster_entry()
    elif _page == "template":
        if require_login() is not None:
            render_template_entry()
    elif _page == "semantic":
        if require_login() is not None:
            render_semantic_entry()
    elif _page == "dict_admin":
        render_dict_admin_entry()
    elif _page == "ai_hub":
        render_ai_hub_entry()
    elif _page == "writing":
        render_writing_entry()
    elif _page == "lexical":
        render_lexical_entry()
    elif _page == "model_settings":
        render_model_settings_entry()
    elif _page == "help":
        render_help_entry()
    else:
        render_main_area()


def render_users_admin_entry() -> None:
    """👥 系统管理入口：使用说明 + 账号管理页 + 范畴与工具段（RV20-1 接线）。

    两段各自带函数内角色门（账号管理 sys_admin/dict_admin；范畴与工具
    sys_admin/dict_admin，两区开关再细分 sys_admin/dict_admin 职责）；
    账号管理段空库早退不影响范畴与工具段独立渲染。
    """
    render_page_usage_guide("users_admin")
    render_users_admin_page()
    st.markdown("")
    from src.categories_tools_page import render_categories_tools_page

    render_categories_tools_page()


def render_reliability_entry() -> None:
    """📐 信度报告入口：使用说明 + Agent C 页面（函数内部另有 reviewer/admin 门）。"""
    render_page_usage_guide("reliability")
    render_reliability_page()


def render_cluster_entry() -> None:
    """📊 语义分析入口：使用说明 + 语义分析合并页（需登录，全角色可看）。

    批次 8：「🏃‍♀️ 范畴深挖」并入本页（key=cluster，guide 键仍为 "cluster"，
    旧键 category 在 main() 顶部重定向）；页面本体为
    cluster_analysis.render_semantic_analysis_page（谱系四 tab + 英汉对比五 tab）。
    """
    render_page_usage_guide("cluster")
    render_semantic_analysis_page()


def render_template_entry() -> None:
    """🧩 释义模板入口：使用说明 + 模板引擎页（需登录，全角色可看）。"""
    render_page_usage_guide("template")
    render_template_page()


def render_semantic_entry() -> None:
    """🧠 以句搜义入口：使用说明 + 以句搜义页（需登录，全角色可看）。"""
    render_page_usage_guide("semantic")
    render_semantic_search_page()


def render_dict_admin_entry() -> None:
    """📖 词典管理区入口：使用说明 + 区级页面（驾驶舱/成员/定制属性/导入/浏览器/任务分配）。"""
    render_page_usage_guide("dict_admin")
    render_dict_admin_page()


def render_ai_hub_entry() -> None:
    """🤖 AI 协作区入口：使用说明 + 区级页面（协作收件箱/协同度量）。"""
    render_page_usage_guide("ai_hub")
    render_collab_page()


def render_writing_entry() -> None:
    """✍️ 释义撰写与审校入口：使用说明 + 撰写/审校/版本历史三 tab（编纂成文域）。"""
    render_page_usage_guide("writing")
    render_writing_page()


def render_lexical_entry() -> None:
    """📖 例证与对译入口：使用说明 + 例证配置/对译定稿两 tab（编纂成文域）。"""
    render_page_usage_guide("lexical")
    render_lexical_page()


def render_model_settings_entry() -> None:
    """🤖 模型供应商入口：使用说明 + 供应商管理页面（仅词典管理员）。"""
    render_page_usage_guide("model_settings")
    render_model_settings_page()


def render_help_entry() -> None:
    """❓ 帮助中心入口：使用说明 + 母本文档渲染页（全员可见，含未登录——帮助不该有门槛）。"""
    render_page_usage_guide("help")
    render_help_center_page()

# ============================================
# 启动应用
# ============================================
if __name__ == "__main__":
    main()

# ============================================
# 历史集成说明（开发者参考——勿以裸字符串书写：Streamlit magic 会渲染顶层字面量）
# ============================================
# 【已实现的数据库集成】MOCK_STATS→get_stats、MOCK_HOT_VERBS→get_hot_verbs、
#   MOCK_FEEDBACK_DATA→get_feedback_data（均已接 MySQL）；MOCK_DEFINITIONS 为释义兜底级
# 【需要新增的 API 调用】大模型调用已在 src/llm_api.py 实现（多提供商四级降级）；
#   查询日志 insert_query 已实现（usage_logs 表）
# 【已实现的数据库存储】queries→usage_logs、feedbacks、热门动词统计——均已接入
#
# 技术栈：Streamlit / Pandas / PyMySQL · 详见 docs/dev/ARCHITECTURE.md 与 README
