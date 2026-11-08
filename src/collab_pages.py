"""AI 协作区页面模块 —— 协作收件箱 / 协同度量 / 任务分配（Agent H，批次 2）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§5（A 协作智能层）与 §9（AI 协作区
全角色）；契约：docs/spec/阶段1施工规范.md §5（批次 2 契约）；页面口径：
docs/help/平台功能使用说明.md §5（AI 协作区）与 §6.6（任务分配）。

是什么（一个区级页面，页内三 tab）：
  * 📥 协作收件箱：待裁决 AI 建议（ai_ledger.list_pending，只取 draft/audit 两通道
    —— probe 探针不进收件箱，这是数据层 docstring 的取数约定，本页遵守）＋
    「我的任务」（assignments 中当前用户 status≠closed 的行，只读）；词典管理员
    另见「全部 pending」视图（台账全部待决行，含收件箱未收录的探针通道）；
  * 📊 协同度量：ai_ledger.get_stats 总卡（总数/待裁决/采纳率，None 显示「—」
    不虚构）＋按工序（stage）下钻表；
  * 📋 任务分配（词典管理员门）：选动词/义位（oald_senses × definitions 参数化
    只读搜索）→ 选标注员（users_db.list_users 过滤 role）→ task_type
    （admission/feature_coding/alignment）→ scope_verbs（可空 = 不限动词）→
    「创建分派」INSERT assignments（assigned_by = 当前登录用户）。

数据链：
  ai_ledger（提案台账，全部读写走数据层）＋ annotation_flow 建的 assignments 表
  ＋ users_db（账号/角色）＋ org_db（入册项目上下文）＋ mysql_db 的
  oald_senses/definitions（只读搜索）。本模块只写少量参数化查询辅助
  （list_my_assignments 我的任务查询 / create_assignment 创建分派 /
  _search_verbs 动词搜索 / _list_proposal_stages 工序枚举 /
  _assignments_table_ready 表就绪探测），其余一律走批次 1 数据层函数；
  task_type 枚举 import 自 annotation_flow.TASK_TYPES（assignments DDL ENUM
  的单一事实源，避免两处常量漂移）。

角色门（纵深防御，施工规范 §5 通用约定）：
  * 页面入口未登录拦截（st.warning + return）；任务分配 tab 内再做
    _is_admin_like 门 —— 六角色口径（批次 12 R1-2/R1-5 收口：判定走
    users_db.effective_six_roles 单一实现，legacy admin 经映射兼判，
    授予式管理角色放行）；
  * 收件箱裁决按钮区按 _can_adjudicate_inbox 收口（R1-5：有效六角色含
    dict_admin/reviewer 才渲染按钮，其余角色只读灰注「裁决权归词典管理员/
    审校」）；侧边栏待办徽章保留全角色（提示性质）。

留给批次 3 / 集成的事项（docstring 占位，代码内同注）：
  * 任务分配的回避制 / 负荷上限（默认 10，运行层配置可调）/ 角色匹配 require
    校验本期占位，批次 3 在 create_assignment 调用前接入；
  * assignments.category 本期固定取 DDL 默认 'motion'，批次 3「簇为粒度」分派
    时按所选动词所在簇推导；
  * 分派对象过滤按旧 users.role 枚举（annotator 及以上）＋ list_roles 六角色
    并集的过渡口径，六角色会话接线后统一走 list_roles；
  * 收件箱四类待办中的「待我审校 / 待我裁决（词典管理员置顶）」两类属批次 3；
  * 侧边栏待办计数（30s 缓存）由集成在 app.py 侧实现；
  * 词典管理员的「全部 pending」视图本期只读追溯探针通道（探针问答通常不入
    裁决流），是否开放 probe 裁决由批次 3 决定。

安全规则（同 users_admin_page.py 口径）：
  * 用户生成内容进 unsafe_allow_html 前一律 _html_escape；本页尽量用 Streamlit
    原生组件（自带转义），HTML 仅标题/卡片且插值全部过 _html_escape；
  * SQL 一律参数化：本模块无一处把用户输入拼进 SQL 文本（LIMIT/占位符外无拼接）；
  * widget key 统一前缀 KEY_PREFIX = "collab_"，裁决理由/搜索词等用户输入
    只存 st.session_state 对应键，不落日志。
"""

import json
import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional

import streamlit as st

from src.ai_ledger import (
    DECISION_ADOPTED,
    DECISION_MODIFIED,
    DECISION_REJECTED,
    KIND_AUDIT,
    KIND_DRAFT,
    KIND_PROBE,
    MAX_LIST_LIMIT,
    decide,
    get_stats,
    list_pending,
)
from src.annotation_flow import TASK_TYPES as ASSIGNMENT_TASK_TYPES
from src.annotation_flow import TASK_TYPE_LABELS  # R6-8：单一导出，本模块改引
from src.db_utils import current_user as _current_user  # R6-4：单一实现点
from src.data_pages import _escape_like  # R2-5：LIKE 转义与 data_pages 同源
from src.design_system import HEADER_H1, HEADER_H2, HEADER_H3
from src.mysql_db import get_db_cursor
from src.org_db import get_projects_for_user
from src import guards
from src.users_db import effective_six_roles, list_roles, list_users

logger = logging.getLogger(__name__)

# ============================================
# 常量（契约 §5 + 帮助文档 §5.1/§6.6 口径）
# ============================================

# widget key 统一前缀（施工规范 §5：widget key 统一前缀）
KEY_PREFIX = "collab_"

# 会话内一次性提示（裁决成功 → st.success 并刷新：先存提示再 rerun，
# 重跑后在新一轮渲染顶部弹出，避免 success 一闪而过）
_FLASH_KEY = KEY_PREFIX + "flash"

# 收件箱取数通道：只收草稿/质检两通道 —— probe 探针不进收件箱
# （ai_ledger.list_pending docstring 的取数约定；探针仅管理员全量视图追溯）
INBOX_KINDS = (KIND_DRAFT, KIND_AUDIT)

# assignments.task_type 展示名（存库一律用英文枚举值，同 users_admin_page 角色）
# —— R6-8：展示映射收进 annotation_flow.TASK_TYPE_LABELS 单一导出（与
# sense_spine 同源；原「准入标注」统一为「义位准入」工序名），本模块只 import。

# assignments.status 全四态（DDL ENUM('open','in_progress','submitted','closed')）
ASSIGNMENT_STATUS_LABELS = {
    "open": "待开始",
    "in_progress": "进行中",
    "submitted": "已提交待审",
    "closed": "已关闭",
}

# 分派对象过滤 · 旧 users.role 四枚举中「标注任务可承担」的角色
# （任务×角色矩阵：标注→annotator+；旧枚举优先级 admin > reviewer > annotator >
# viewer，annotator 及以上即三值）。viewer 只读，不可承担标注任务。
LEGACY_ASSIGNEE_ROLES = ("annotator", "reviewer", "admin")

# 分派对象过滤 · 六角色中「标注任务可承担」的角色（annotator+，即除 viewer 外全部；
# user_roles 是 v5.1 事实源，覆盖「旧列还是 viewer 但已 grant_role('annotator')」）
SIX_ROLE_ASSIGNEE_ROLES = ("dict_admin", "sys_admin", "reviewer", "editor", "annotator")

# 负荷上限默认值（平台架构设计规范 §8：负荷上限入运行层配置，默认 10）——
# 同一被派人在途（assignments status ∈ open/in_progress）任务达到上限即拒绝新分派
LOAD_LIMIT_DEFAULT = 10

# 任务×角色矩阵 · 标注类任务（判断类工序 4–8：admission/feature_coding/alignment，
# 即 assignments.task_type 现行枚举）可承担的六角色 —— 标注→annotator+（架构规范
# §8 任务×角色矩阵），editor/reviewer/词典管理员/平台管理员天然兼容（一人可叠加
# 多角色）；viewer 只读，不可承担标注任务
CODING_TASK_ALLOWED_ROLES = ("annotator", "editor", "reviewer", "dict_admin", "sys_admin")

# 任务×角色矩阵 · 分立双评（工序 8）可承担角色：annotator+reviewer（架构规范 §8
# 「分立双评→annotator+reviewer」）。assignments.task_type 的 ENUM 尚无此值
# （DDL 单一事实源见 annotation_flow.ASSIGNMENTS_TABLE_SQL），本常量是批次 4 接入
# 分立复核任务时的预留口径 —— 接入时须同步 DDL ENUM 与 annotation_flow.TASK_TYPES
SPLIT_REVIEW_TASK_TYPES = ("split_review",)
SPLIT_REVIEW_ALLOWED_ROLES = ("annotator", "reviewer", "dict_admin")

# 收件箱/待决列表单次渲染上限（对齐 ai_ledger.MAX_LIST_LIMIT，防一次性拖全表）
INBOX_LIMIT = MAX_LIST_LIMIT

# 裁决三值展示名（数据层 decide 的 decision 入参）
DECISION_LABELS = {
    DECISION_ADOPTED: "采纳",
    DECISION_REJECTED: "否决",
    DECISION_MODIFIED: "修改后采纳",
}


# ============================================
# 页面使用说明（契约 §5 四段式；集成时原样并入 PAGE_GUIDES["ai_hub"]）
# ============================================

GUIDE = {
    "label": "🤖 AI 协作",
    "purpose": (
        "人机协同的总控台：协作收件箱把「AI 提议 → 人裁决」的待办（按不确定度从高到低）"
        "与分派给我的任务收进一页，协同度量把提案台账量化成采纳率等论文可引的指标；"
        "任务分配已并入词典管理区（📋 任务分配标签页）。"
    ),
    "principle": [
        "混合主动交互（帮助文档 §5.1）：AI 可以发起（草稿/质检通道的建议），人批量裁决；"
        "不确定度＝规则层未命中特征数＋历史人-机分歧率＋预演分歧标记的综合信号，"
        "禁用 LLM 自报置信度 —— 收件箱按不确定度降序排列，「最需要人看」的提议优先。",
        "AI 永不直写义位权威库：收件箱每条提议只展示候选内容与证据链"
        "（evidence_ref ＋ 提示词版本 ＋ 资源快照版本，可复现「当时 AI 看到了什么」），"
        "采纳后的实际落地由对应业务页完成，ai_proposals 仅作不可变留痕 —— "
        "重复裁决会被数据层拒绝，首次结论不可覆盖。",
        "裁决留痕纪律：否决必须填写理由（架构纪律 —— 空口否决在提交前被页面拦截），"
        "采纳/修改建议填写理由；三个裁决按钮对应 adopted/rejected/modified 三值。",
        "探针（probe）通道不进收件箱：库内受控问答属轻量留痕，本页收件箱按数据层"
        "取数约定只取 draft/audit 两通道；词典管理员可在页底「全部 pending」视图"
        "追溯台账全部待决行（含探针）。",
        "任务分派三级权限链（平台架构设计规范 §8）的第三级（分派任务）在词典管理区"
        "「📋 任务分配」标签页执行（复用本模块 _render_assign_tab）；过渡期以 "
        "role=='admin' 兼判词典管理员。回避制与负荷上限（默认 10）校验批次 3 接入，"
        "本期分派人自行把关。",
    ],
    "data_source": [
        "src/ai_ledger.py（ai_proposals 台账）：list_pending(kind) 供收件箱"
        "（draft/audit，按 uncertainty DESC, id ASC）、get_stats 供协同度量"
        "（总数/待裁决/采纳率＝adopted/(adopted+rejected+modified)、平均不确定度）、"
        "decide 写裁决留痕（理由＋裁决人＋时间，一次性不可改）。",
        "assignments 表（annotation_flow.ensure_flow_tables 建，DDL 见多人标注系统"
        "设计规范 §2）：「我的任务」查当前用户 status≠closed 的行；「任务分配」INSERT "
        "新行（assigned_by=当前登录词典管理员）—— 两处是本模块的参数化查询辅助，"
        "SQL 全占位符。",
        "src/users_db.py：list_users 全量账号（角色/在用状态）；list_roles 六角色"
        "事实源，与旧 role 列取并集筛「标注任务可承担」（annotator+）的账号。",
        "src/org_db.py：get_projects_for_user 取当前用户入册项目与项目内职能，"
        "在「我的任务」段提示任务所属的项目上下文。",
        "definitions × oald_senses（mysql_db 只读查询）：任务分配的动词/义位搜索"
        "（词目或 OALD 义项词目 LIKE 匹配，关键词走占位符），命中动词作为 scope_verbs "
        "落进 assignments。",
    ],
    "steps": [
        "在侧边栏切到「🤖 AI 协作」：三个标签页分别是 📥 协作收件箱 / 📊 协同度量 / "
        "📋 任务分配。",
        "收件箱：展开任一条「待裁决 AI 建议」，查看提议 JSON、证据引用、不确定度与"
        "提示词/资源快照版本；填写裁决理由后点 ✅ 采纳 / ⛔ 否决 / ✏️ 修改后采纳 —— "
        "否决不填理由会被拦截；裁决成功页面自动刷新，该条从待决列表消失且不可再改。",
        "收件箱「我的任务」段查看分派给自己的在途任务（状态≠已关闭）：任务类型/范畴/"
        "范围动词/状态一览；标注与提交请到「语义建模 → 标注任务」页完成（本页只读）。",
        "协同度量：顶部三卡看全库提案总数/待裁决/采纳率（尚无已裁决提案时采纳率显示"
        "「—」而不是 0%）；下方按工序（stage）下钻表看各工序的计数与平均不确定度。",
        "任务分配（词典管理员）：① 输入关键词搜索动词/义位并多选范围动词"
        "（一个不选＝不限动词，任务覆盖全库）；② 选标注员；③ 选任务类型"
        "（准入/特征编码/英汉对齐）；④ 点「创建分派」—— 任务立即出现在该标注员的"
        "收件箱「我的任务」里。",
    ],
    "notes": [
        "采纳率口径：分母是已裁决提案数（pending 不计）；「—」＝还没有已裁决提案，"
        "不要读成 0%；平均不确定度按全部提案（含已裁决）平均 —— 度量的是信号本身"
        "的质量，不是当前积压。",
        "收件箱只收 draft/audit 两通道；probe 探针问答不入裁决流（数据层约定），"
        "词典管理员可在页底「全部 pending」视图追溯全部待决台账。",
        "裁决是不可变留痕：重复裁决（含两人同时裁决同一条）只有首次生效；裁决失败"
        "通常意味着提案已被他人处理，刷新即可。",
        "「我的任务」为只读列表，提交动作在标注任务页 —— 双入口会造成状态口径分裂，"
        "本页刻意不开。",
        "任务分配的回避制/负荷上限/角色匹配为批次 3 事项，本期创建前请人工核对；"
        "范畴 category 暂取表默认 motion，批次 3 改为按所选动词所在簇推导。",
        "数据库不可用时收件箱显示为空、度量卡为 0 口径 —— 是降级渲染，"
        "不代表没有数据。",
    ],
}


# ============================================
# 会话与角色门（纯函数可测）
# ============================================

def _is_admin_like(user: Optional[Dict[str, Any]]) -> bool:
    """管理面判定（纯函数，tests/test_collab_pages.py 覆盖）。

    六角色接线后的升级实现（原过渡判定 role == "admin" 的唯一改动点，见
    旧 docstring 占位）：有效六角色集（users_db.effective_six_roles 单一
    实现，R1-2 同源口径）含 dict_admin 或 sys_admin 即 True —— legacy
    admin 经映射两位一体自然通过（升级前后对存量账号逐字节一致）；
    授予式 dict_admin（legacy 列 viewer/annotator 但 user_roles 已授予）
    自此放行（R1-2 家族：授予式用户不再被 legacy 判定拦在门外）。
    reviewer/editor/annotator/viewer 单角色一律 False（fail-closed）。

    Returns:
        bool: user 为 dict 且有效六角色集含管理角色才 True；未登录/非 dict/
        其余角色一律 False（fail-closed）。
    """
    if not isinstance(user, dict):
        return False
    return bool(effective_six_roles(user) & {"dict_admin", "sys_admin"})


def _can_adjudicate_inbox(user: Optional[Dict[str, Any]]) -> bool:
    """收件箱裁决权（R1-5，施工规范 §14 批次 12；纯函数 fail-closed）。

    R6-4 改名 _can_adjudicate_inbox：与 writing_pages._can_adjudicate
    （词典管理员终裁，dict_admin 单角色口径）同名不同义，就地改名消歧。

    有效六角色集（users_db.effective_six_roles 单一实现）含 dict_admin 或
    reviewer 才可裁决 AI 建议 —— 收件箱裁决按钮区按本函数收口，其余角色
    （editor/annotator/viewer/sys_admin）只读展示（按钮替换为灰注
    「裁决权归词典管理员/审校」）；legacy admin 经映射两位一体自然命中。
    侧边栏待办徽章（pending_inbox_count）不受本判定影响 —— 徽章是全角色
    提示性质（R1-5 口径：提示保留）。
    """
    if not isinstance(user, dict):
        return False
    return bool(effective_six_roles(user) & {"dict_admin", "reviewer"})


def _validate_decision(decision: str, reason: Optional[str]) -> Optional[str]:
    """裁决入参校验（纯函数）：通过返回 None，否则返回可直接展示的错误文案。

    四态（tests/test_collab_pages.py 测齐）：
      1. decision 不在 ai_ledger.DECISIONS 三值内 → 错误文案；
      2. decision == 'rejected' 且理由为空（None/非字符串/纯空白）→ 错误文案
         （架构纪律：否决必须给理由 —— 数据层 decide 的 reason 允许 NULL，
         页面层收紧）；
      3. decision 合法且理由非空 → None（三值均可带理由，留痕更完整）；
      4. decision 合法且理由为空 → None（采纳/修改允许无理由；rejected 已被
         态 2 拦截，不会落到这里）。
    """
    if decision not in (DECISION_ADOPTED, DECISION_REJECTED, DECISION_MODIFIED):
        return f"非法裁决值 {decision!r}（须为 采纳/否决/修改后采纳 之一）"
    if decision == DECISION_REJECTED and not (isinstance(reason, str) and reason.strip()):
        return "否决必须填写理由（架构纪律：裁决留痕不可空口否决）。"
    return None


def _clean_reason(reason: Optional[str]) -> Optional[str]:
    """裁决理由规整：去首尾空白，纯空白归一为 None（与 ai_ledger 入库口径一致）。"""
    if not isinstance(reason, str):
        return None
    cleaned = reason.strip()
    return cleaned or None


def _legacy_role_map(users: List[Dict[str, Any]]) -> Dict[int, str]:
    """users 清单 → {users.id: legacy role}（纯函数；id 非法/缺 role 的行跳过）。

    任务分配的 assignee_roles 取「六角色 user_roles ∪ legacy role」并集（过渡
    口径），本映射为并集里的 legacy 半边提供数据（_render_assign_tab 已有
    list_users 结果，不必二次查库）。
    """
    mapping: Dict[int, str] = {}
    for u in users or []:
        if not isinstance(u, dict):
            continue
        try:
            uid = int(u.get("id") or 0)
        except (TypeError, ValueError):
            continue
        role = u.get("role")
        if uid > 0 and isinstance(role, str) and role.strip():
            mapping[uid] = role
    return mapping


def _check_role_matrix(task_type: str, assignee_roles: List[str]) -> Optional[str]:
    """任务×角色矩阵校验（纯函数）：通过返回 None，否则返回可展示的拒绝原因。

    矩阵口径（平台架构设计规范 §8 任务×角色矩阵）：
      * admission / feature_coding / alignment（标注类，判断类工序 4–8）→
        被派人须含 annotator / editor / reviewer / dict_admin / sys_admin 任一
        （标注→annotator+；editor 及以上继承兼容；viewer 只读不可承担）；
      * 分立双评（预留任务类型 'split_review'，批次 4 接入）→ annotator /
        reviewer / dict_admin 之一（editor/sys_admin 不在该矩阵）；
      * 未知 task_type → 一律拒绝（fail-closed，不猜意图）；
      * assignee_roles 非 str/空串元素忽略 —— 角色枚举在库里恒为小写字面量，
        不做大小写/类型宽容。

    assignee_roles 由调用方取 users_db.list_roles（六角色事实源）∪ 账号 legacy
    role 的并集（见 _render_assign_tab / _legacy_role_map）。
    """
    roles = {
        r for r in (assignee_roles or [])
        if isinstance(r, str) and r.strip()
    }
    if task_type in ASSIGNMENT_TASK_TYPES:
        allowed = CODING_TASK_ALLOWED_ROLES
    elif task_type in SPLIT_REVIEW_TASK_TYPES:
        allowed = SPLIT_REVIEW_ALLOWED_ROLES
    else:
        return (
            f"任务分配被拒：未知任务类型 {task_type!r}"
            "（assignments.task_type 枚举之外，不予创建）。"
        )
    if roles & set(allowed):
        return None
    if roles:
        current = "、".join(sorted(roles))
        return (
            f"任务分配被拒（任务×角色矩阵）：{task_type} 需要角色 "
            f"{'/'.join(allowed)} 之一，被派人现有角色（{current}）不满足。"
        )
    return (
        f"任务分配被拒（任务×角色矩阵）：{task_type} 需要角色 "
        f"{'/'.join(allowed)} 之一，被派人查无任何角色（viewer 只读，不可承担标注任务）。"
    )


def _check_recusal(task_type: str, assignee_id: int, assigned_by: int) -> Optional[str]:
    """回避制校验（批次 3 占位：本期一律放行返回 None）。

    批次 4 接入口径（平台架构设计规范 §8）：编纂协作（表达类工序 10–13）的
    审校类任务须 审校人 ≠ 该簇/义位的撰写人（回避制无豁免，含词典管理员；
    自写词条走 reviewer 终审，单主项目走 bypass 公示）。届时本函数改查
    同一工作单元的撰写人（assignments / 释义版本归属）比对 assignee_id，
    命中即返回拒绝原因。当前分派的均为标注类任务（判断类工序 4–8，盲标
    独立范式），不涉及回避制，直接放行。
    """
    return None  # 占位：task_type/assignee_id/assigned_by 留给批次 4 接入


def _flash(level: str, text: str) -> None:
    """把一次性提示写进会话（配合 st.rerun，重跑后由 _pop_flash 弹出）。"""
    st.session_state[_FLASH_KEY] = {"level": level, "text": text}


def _pop_flash() -> None:
    """弹出 _flash 存的一次性提示（成功/失败各一种样式）。"""
    msg = st.session_state.pop(_FLASH_KEY, None)
    if not isinstance(msg, dict) or not msg.get("text"):
        return
    if msg.get("level") == "success":
        st.success(str(msg["text"]))
    else:
        st.error(str(msg["text"]))


def _fmt_rate(rate: Optional[float]) -> str:
    """采纳率展示：None →「—」（没数据不虚构 0），数值 → 百分数（1 位小数）。"""
    if rate is None:
        return "—"
    return f"{rate * 100:.1f}%"


def _fmt_uncertainty(value: Optional[float]) -> str:
    """不确定度展示：None →「—」，数值 → 4 位小数（与 ai_ledger 存储口径一致）。"""
    if value is None:
        return "—"
    return f"{value:.4f}"


# ============================================
# 本模块参数化查询辅助（assignments / oald_senses 只读＋一处 INSERT；
# 除注释/常量外无任何字符串拼接进 SQL，值全走占位符）
# ============================================

def _assignments_table_ready() -> bool:
    """assignments 表是否已建（annotation_flow.ensure_flow_tables 的产物）。

    只读探测（information_schema，表名是本模块常量非用户输入）。表缺失是合法
    状态（任务分派未启用），页面据此给修复指引而不是抛错 —— 与 org_db
    「查 assignments 占位，MVP 放行」同口径。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assignments'"
            )
            row = cursor.fetchone()
            return bool(row) and int(row["n"] or 0) > 0
    except Exception as e:  # noqa: BLE001 —— 库不可用按表未就绪渲染
        logger.error(f"探测 assignments 表就绪失败: {e}")
        return False


def _parse_scope_verbs(raw: Any) -> Optional[List[str]]:
    """assignments.scope_verbs JSON 列 → 动词清单（纯函数，脏数据容错）。

    None → None（DDL 语义：NULL = 全部动词）；JSON 串/list → str 清单；
    解析失败/结构不对 → None（按未限范围渲染，不打崩「我的任务」）。
    """
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    return None


def list_my_assignments(assignee_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """当前用户的在途任务（assignments，status ≠ 'closed'；本模块参数化只读辅助）。

    「我的任务」段数据源：**只读展示** —— 任务的标注与提交动作在
    「语义建模 → 标注任务」页完成，本列表刻意不提供提交入口（避免双入口造成
    状态口径分裂，见 GUIDE notes）。

    Args:
        assignee_id: 当前登录用户 users.id
        limit: 返回条数上限（≤0 返回 []；防一次性拖全表）

    Returns:
        list[dict]: {id, category, task_type, scope_verbs(None=全部动词 或
        list[str]), status, assigned_by, created_at}，按 id 降序（最新分派在前）；
        参数非法 / 表未建 / 数据库不可用返回 []。
    """
    try:
        uid = int(assignee_id)
        lim = int(limit)
    except (TypeError, ValueError):
        return []
    if uid <= 0 or lim <= 0:
        return []
    sql = (
        "SELECT id, category, task_type, scope_verbs, status, assigned_by, created_at "
        "FROM assignments WHERE assignee_id = %s AND status <> 'closed' "
        "ORDER BY id DESC LIMIT %s"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (uid, lim))
            rows = cursor.fetchall()
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按空列表降级渲染
        logger.error(f"查询用户 {uid} 的在途任务失败: {e}")
        return []
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["scope_verbs"] = _parse_scope_verbs(item.get("scope_verbs"))
        result.append(item)
    return result


def _count_open_assignments(assignee_id: int) -> Optional[int]:
    """被派人的在途任务数（assignments status ∈ open/in_progress；只读辅助）。

    负荷上限校验（_check_load_limit）的计数口径。表未建 / 参数非法 / 库不可用
    返回 None（按「未知」处理）—— 体检性校验不阻断页面，真正建分派时
    create_assignment 的失败路径会给出明确报错。
    """
    try:
        uid = int(assignee_id)
    except (TypeError, ValueError):
        return None
    if uid <= 0:
        return None
    sql = (
        "SELECT COUNT(*) AS n FROM assignments "
        "WHERE assignee_id = %s AND status IN ('open', 'in_progress')"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (uid,))
            row = cursor.fetchone()
            return int(row["n"] or 0) if row else 0
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按未知处理
        logger.error(f"统计在途任务数失败（assignee={uid}）: {e}")
        return None


def _check_load_limit(assignee_id: int, limit: int = LOAD_LIMIT_DEFAULT) -> Optional[str]:
    """负荷上限校验：同被派人在途任务数 ≥ 上限即拒绝（返回原因，否则 None）。

    上限默认 LOAD_LIMIT_DEFAULT（架构规范 §8：负荷上限入运行层配置，默认 10；
    limit 参数即运行层覆盖入口）。在途数未知（表未建/库不可用）时放行 ——
    分派动作本身会因同样的库问题失败并有明确报错，校验层不做第二重报错。
    """
    open_count = _count_open_assignments(assignee_id)
    if open_count is None:
        return None
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = LOAD_LIMIT_DEFAULT
    if cap > 0 and open_count >= cap:
        return (
            f"任务分配被拒（负荷上限）：该被派人已有 {open_count} 个在途任务"
            f"（open/in_progress），达到上限 {cap} —— 请先等任务闭环或由运行层"
            "调整上限配置。"
        )
    return None


def create_assignment(
    assignee_id: int,
    task_type: str,
    scope_verbs: Optional[List[str]] = None,
    assigned_by: int = 0,
    category: str = "motion",
) -> int:
    """创建任务分派（INSERT assignments；本模块参数化写辅助，docstring 注明）。

    assignments 表由 annotation_flow.ensure_flow_tables() 建（DDL：多人标注
    系统设计规范 §2）。本函数不建表；任务×角色矩阵 / 负荷上限 / 回避制三重
    校验在调用前完成（批次 3 起，_render_assign_tab 用 _check_role_matrix /
    _check_load_limit / _check_recusal 接线）—— 本函数保持薄 INSERT 不重复
    校验，数据层直调（脚本/测试）仍走参数与 FK 兜底。

    Args:
        assignee_id: 标注员 users.id
        task_type: 任务类型 ∈ ASSIGNMENT_TASK_TYPES（import 自 annotation_flow，
        与 assignments DDL ENUM 一致）
        scope_verbs: 范围动词清单（list/tuple，元素去空白后须非空）；
        None = 全部动词（DDL 语义：scope_verbs NULL）
        assigned_by: 分派人 users.id（词典管理员，= 页面当前登录用户）
        category: 范畴（DDL 默认 'motion'；批次 3 簇为粒度分派时按所选动词
        所在簇推导，本页不暴露该参数）

    Returns:
        int: 新任务 id；参数非法（含 scope_verbs 传了空清单 —— 意图不明，
        页面层「一个不选」已归一为 None）/ 表未建 / 数据库错误返回 0。
    """
    try:
        assignee = int(assignee_id)
        granter = int(assigned_by)
    except (TypeError, ValueError):
        logger.error(f"create_assignment 拒绝非法 id: assignee_id={assignee_id!r}, "
                     f"assigned_by={assigned_by!r}")
        return 0
    if assignee <= 0 or granter <= 0:
        logger.error(f"create_assignment 拒绝非正 id: assignee={assignee}, "
                     f"assigned_by={granter}")
        return 0
    if task_type not in ASSIGNMENT_TASK_TYPES:
        logger.error(f"create_assignment 拒绝非法 task_type: {task_type!r}")
        return 0
    if not isinstance(category, str) or not category.strip() or len(category) > 40:
        logger.error(f"create_assignment 拒绝非法 category: {category!r}")
        return 0
    scope_json: Optional[str] = None
    if scope_verbs is not None:
        if not isinstance(scope_verbs, (list, tuple)):
            logger.error(f"create_assignment 拒绝非法 scope_verbs: {scope_verbs!r}")
            return 0
        cleaned = [str(v).strip() for v in scope_verbs if str(v).strip()]
        if not cleaned:
            logger.error("create_assignment 拒绝空 scope_verbs 清单"
                         "（不限动词请传 None，DDL 语义 NULL=全部动词）")
            return 0
        try:
            scope_json = json.dumps(cleaned, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error(f"create_assignment 序列化 scope_verbs 失败: {e}")
            return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO assignments (assignee_id, category, task_type, "
                "scope_verbs, status, assigned_by) "
                "VALUES (%s, %s, %s, %s, 'open', %s)",
                (assignee, category.strip(), task_type, scope_json, granter),
            )
            return int(cursor.lastrowid)
    except Exception as e:  # noqa: BLE001 —— FK 无此人/表缺失/库不可用按失败
        logger.error(f"创建任务分派失败（assignee={assignee}, task_type={task_type}）: {e}")
        return 0


def _search_verbs(keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    """动词/义位搜索（definitions × oald_senses 参数化只读查询，本模块辅助）。

    词目（definitions.verb）或 OALD 义项词目（oald_senses.headword）LIKE 匹配：
    关键词走占位符，包裹用的 ``%`` 由本函数拼在**值**里（``%kw%``）；R2-5 起
    关键词先经 data_pages._escape_like 转义（``!``/``%``/``_``，SQL 侧
    ``ESCAPE '!'`` 与 data_pages.LIKE_ESCAPE 同源同口径）—— 通配符按字面
    处理：搜 ``100%`` 匹配字面「100%」而不是「100」开头的任意串（与
    data_pages 词条搜索口径一致，无 SQL 文本拼接）。

    Args:
        keyword: 搜索关键词（去空白后为空返回 []；通配符按字面处理）
        limit: 返回条数上限（去重到动词，按词目排序）

    Returns:
        list[dict]: {verb, sense_count, cluster_id, oald_senses（OALD 义项数）}；
        两表由 mysql_db.init_database 建，库不可用/无命中返回 []。
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    try:
        lim = max(1, int(limit))
    except (TypeError, ValueError):
        return []
    like = f"%{_escape_like(kw)}%"  # 值，不进 SQL 文本；通配符按字面处理
    sql = (
        "SELECT d.verb AS verb, d.sense_count AS sense_count, "
        "d.cluster_id AS cluster_id, COUNT(os.id) AS oald_senses "
        "FROM definitions d "
        "JOIN oald_senses os ON os.definition_id = d.id "
        "WHERE d.verb LIKE %s ESCAPE '!' OR os.headword LIKE %s ESCAPE '!' "
        "GROUP BY d.id, d.verb, d.sense_count, d.cluster_id "
        "ORDER BY d.verb LIMIT %s"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (like, like, lim))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按无命中降级
        logger.error(f"动词搜索失败（keyword 长度 {len(kw)}）: {e}")
        return []


def _list_proposal_stages() -> List[str]:
    """台账出现过的全部工序（stage）清单（本模块参数化只读辅助）。

    协同度量按工序下钻需要工序枚举；ai_proposals 的 stage 无独立维表，
    直接 SELECT DISTINCT（SQL 文本为常量，无用户输入参与）。
    数据库不可用返回 []（下钻表降级为「暂无记录」提示）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT DISTINCT stage FROM ai_proposals ORDER BY stage")
            rows = cursor.fetchall()
            return [str(r["stage"]) for r in rows if r.get("stage")]
    except Exception as e:  # noqa: BLE001
        logger.error(f"枚举提案工序失败: {e}")
        return []


# ============================================
# tab 1 · 协作收件箱
# ============================================

def _sort_pending(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """待决条目排序（纯函数，tests/test_collab_pages.py 覆盖排序口径）。

    与 ai_ledger.list_pending 的 ORDER BY 同口径：不确定度降序（最需要人看的
    优先）、缺失（None）排最后、同分按登记先后（id ASC）稳序 —— 两通道合并
    后用本函数恢复全局排序。
    """
    return sorted(
        items,
        key=lambda p: (
            p.get("uncertainty") is None,
            -(p.get("uncertainty") or 0.0),
            int(p.get("id") or 0),
        ),
    )


def _proposal_summary(p: Dict[str, Any]) -> str:
    """收件箱条目的 expander 标题（纯文本组件，Streamlit 自带转义）。"""
    uncertainty = p.get("uncertainty")
    unc_text = "未提供" if uncertainty is None else f"{uncertainty:.2f}"
    kind_label = "质检" if p.get("kind") == KIND_AUDIT else (
        "探针" if p.get("kind") == KIND_PROBE else "草稿")
    return (
        f"#{p.get('id')} · [{kind_label}] {p.get('stage') or '（无工序）'} · "
        f"{p.get('unit_ref') or '（无单元）'} · 不确定度 {unc_text}"
    )


def _proposal_detail(p: Dict[str, Any]) -> None:
    """提议详情：候选 JSON ＋ 证据链 ＋ 资源注入协议版本留痕（原生组件自带转义）。"""
    st.json(p.get("proposal") if isinstance(p.get("proposal"), (dict, list)) else {})
    evidence = p.get("evidence_ref")
    cols = st.columns(2)
    cols[0].caption(
        f"证据引用：{evidence if evidence else '（无据 —— AI 明说查不到）'}"
    )
    cols[0].caption(
        f"提示词版本：{p.get('prompt_version') or '—'} · "
        f"资源快照版本：{p.get('resource_version') or '—'}"
    )
    cols[1].caption(f"工序：{p.get('stage') or '—'} · 工作单元：{p.get('unit_ref') or '—'}")
    cols[1].caption(f"登记时间：{p.get('created_at') or '—'} · 不确定度："
                    f"{_fmt_uncertainty(p.get('uncertainty'))}")


def _decide_buttons(p: Dict[str, Any]) -> None:
    """单条提议的裁决区：理由框 ＋ adopted/rejected/modified 三按钮。

    流程：点按钮 → _validate_decision 校验（空理由否决在此拦截）→
    ai_ledger.decide（不可变留痕，重复裁决 False）→ 成功 _flash ＋ st.rerun
    刷新收件箱；失败原位 st.error（通常是已被他人抢先裁决）。
    """
    pid = int(p.get("id") or 0)
    reason = st.text_area(
        "裁决理由（否决必填；采纳/修改建议填写 —— 留痕可复现）",
        key=f"{KEY_PREFIX}reason_{pid}",
        height=68,
        placeholder="否决必须说明依据；采纳/修改建议写明落地位置或修改内容。",
    )
    adopt_col, reject_col, modify_col = st.columns(3)
    clicked: Optional[str] = None
    if adopt_col.button("✅ 采纳", key=f"{KEY_PREFIX}adopt_{pid}", type="primary"):
        clicked = DECISION_ADOPTED
    if reject_col.button("⛔ 否决", key=f"{KEY_PREFIX}reject_{pid}"):
        clicked = DECISION_REJECTED
    if modify_col.button("✏️ 修改后采纳", key=f"{KEY_PREFIX}modify_{pid}"):
        clicked = DECISION_MODIFIED
    if clicked is None:
        return

    error = _validate_decision(clicked, reason)
    if error:
        _flash("error", f"提案 #{pid}：{error}")
        st.rerun()
    me = _current_user()
    if me is None:  # 理论不可达（页面入口已拦），纵深防御
        _flash("error", f"提案 #{pid}：会话已失效，请重新登录后再裁决。")
        st.rerun()
    if decide(pid, clicked, _clean_reason(reason), int(me.get("id") or 0)):
        _flash("success",
               f"提案 #{pid} 已裁决为「{DECISION_LABELS[clicked]}」，收件箱已刷新。")
        st.rerun()
    st.error(
        f"提案 #{pid} 裁决失败：该提议可能已被他人裁决（留痕不可覆盖）"
        "或数据库暂不可用，请刷新后查看。"
    )


def _render_pending_inbox(me: Dict[str, Any]) -> List[Dict[str, Any]]:
    """待裁决 AI 建议（draft/audit 两通道；probe 排除 —— 数据层取数约定）。

    两通道各取一次后合并，用 _sort_pending 恢复 ai_ledger 的全局排序口径
    （uncertainty DESC、缺失最后、id ASC）。返回草稿/质检条目清单
    （供管理员「全部 pending」视图做计数对照）。

    **裁决按钮区角色收口（R1-5，施工规范 §14 批次 12）**：按钮区过
    _can_adjudicate_inbox(me)（有效六角色含 dict_admin/reviewer）—— 其余角色
    只读展示，按钮替换为灰注「裁决权归词典管理员/审校」（提议内容与证据
    链照常可见：知情不等于裁决权）；legacy admin 经映射自然命中。
    """
    pending: List[Dict[str, Any]] = []
    for kind in INBOX_KINDS:
        pending.extend(list_pending(kind=kind, limit=INBOX_LIMIT))
    pending = _sort_pending(pending)
    st.markdown(f"<h3 style='{HEADER_H3}'>📨 待裁决 AI 建议</h3>", unsafe_allow_html=True)
    if not pending:
        st.info(
            "收件箱暂无待裁决建议（draft/audit 通道均为空，或数据库未初始化）—— "
            "AI 提议由各业务工序登记后出现在这里。"
        )
        return pending
    st.caption(
        f"共 {len(pending)} 条待裁决（按不确定度降序）；探针（probe）通道不入收件箱。"
    )
    can_adjudicate = _can_adjudicate_inbox(me)
    for p in pending:
        with st.expander(_proposal_summary(p)):
            _proposal_detail(p)
            if can_adjudicate:
                _decide_buttons(p)
            else:
                st.caption(
                    "🔒 裁决权归词典管理员/审校：本条为只读展示"
                    "（如需权限请联系管理员授予）。"
                )
    return pending


def _render_admin_all_pending(inbox_count: int) -> None:
    """词典管理员的「全部 pending」视图（另见台账全部待决行，含探针通道）。

    草稿/质检条目已在上方收件箱列出，这里给台账总量对照 ＋ 收件箱未收录的
    探针条目（只读追溯：探针问答通常不入裁决流，是否开放裁决批次 3 定）。
    """
    all_pending = list_pending(limit=INBOX_LIMIT)  # 全通道（含 probe）
    probes = [p for p in all_pending if p.get("kind") == KIND_PROBE]
    st.divider()
    st.markdown(
        f"<h3 style='{HEADER_H3}'>📡 全部 pending（词典管理员视图）</h3>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"台账待决共 {len(all_pending)} 条：草稿/质检 {inbox_count} 条已在上方收件箱；"
        f"探针 {len(probes)} 条如下（只读追溯，探针问答不入裁决流）。"
    )
    if not probes:
        st.info("探针通道暂无待决记录。")
        return
    for p in probes:
        with st.expander(_proposal_summary(p)):
            _proposal_detail(p)


def _render_my_tasks(me: Dict[str, Any]) -> None:
    """「我的任务」段：当前用户 assignments（status≠closed）只读列表。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>📋 我的任务</h3>", unsafe_allow_html=True)

    projects = get_projects_for_user(int(me.get("id") or 0))
    if projects:
        joined = "、".join(
            f"{p.get('name')}（{p.get('project_role')}）" for p in projects
        )
        st.caption(f"入册项目：{joined}")

    if not _assignments_table_ready():
        st.info(
            "任务表尚未初始化（assignments 由标注流程模块 ensure_flow_tables 建）："
            "任务分派未启用，暂无可显示任务。"
        )
        return
    rows = list_my_assignments(int(me.get("id") or 0))
    if not rows:
        st.info("暂无进行中的任务：任务由词典管理员在「任务分配」页分派后出现在这里。")
        return

    table_rows = []
    for r in rows:
        scope = r.get("scope_verbs")
        table_rows.append({
            "任务ID": r.get("id"),
            "任务类型": TASK_TYPE_LABELS.get(r.get("task_type"), r.get("task_type")),
            "范畴": r.get("category"),
            "范围动词": "全部动词" if scope is None else "、".join(scope),
            "状态": ASSIGNMENT_STATUS_LABELS.get(r.get("status"), r.get("status")),
            "分派人ID": r.get("assigned_by"),
            "分派时间": str(r.get("created_at") or ""),
        })
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
    st.caption(
        "任务列表为只读：标注与提交请在「语义建模 → 标注任务」页完成"
        "（本页不提供提交入口，避免双入口状态口径分裂）。"
    )


@st.cache_data(ttl=30, show_spinner=False)
def pending_inbox_count() -> int:
    """侧边栏待办徽章：pending 的 draft/audit 提议数（probe 不计；30s 缓存）。

    供 app.py 侧边栏渲染；库不可用/表未建返回 0（徽章自然隐藏），
    异常不外抛——侧边栏计数失败不该影响页面主流程。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM ai_proposals "
                "WHERE status = 'pending' AND kind IN ('draft', 'audit')"
            )
            row = cursor.fetchone()
            return int(row["n"] or 0) if row else 0
    except Exception as e:  # noqa: BLE001 —— 计数失败降级为 0（R6-10 补留痕）
        logger.warning(f"pending_inbox_count 侧边栏待办计数失败（按 0 降级）: {e}")
        return 0


def _pending_stage_counts() -> list:
    """按 stage 分组的 pending 计数（待我裁决类目；参数化只读辅助）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT stage, COUNT(*) AS n FROM ai_proposals "
                "WHERE status = 'pending' GROUP BY stage ORDER BY n DESC"
            )
            return [(str(r["stage"]), int(r["n"] or 0)) for r in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 —— R6-10：吞错补留痕
        logger.warning(f"_pending_stage_counts 按工序分组计数失败（按空降级）: {e}")
        return []


def _render_adjudication_section(me: Dict[str, Any]) -> None:
    """⚖️ 待我裁决（词典管理员视角）：按工序的 pending 分布＋分立复核直达。

    终审/出版/许可等裁决随对应页面（批次 8）接入；本版先收口
    sense_division（语义分析页·分立复核 tab 裁决）与全工序分布。
    """
    counts = _pending_stage_counts()
    if not counts:
        return
    st.markdown(f"<h3 style='{HEADER_H3}'>⚖️ 待我裁决（按工序分布）</h3>",
                unsafe_allow_html=True)
    st.table({"工序 stage": [c[0] for c in counts], "待决数": [c[1] for c in counts]})
    division = [n for stage, n in counts if stage == "sense_division"]
    if division:
        st.info(f"义项分立复核有 {division[0]} 条待裁决——裁决动作在"
                "「📊 语义分析 · 🧬 分立复核」标签页完成（证据与落地在同一处）。")
        if st.button("去分立复核", key="collab_adj_goto_cluster"):
            st.session_state["page"] = "cluster"
            st.rerun()


def _render_inbox_tab(me: Dict[str, Any]) -> None:
    """📥 协作收件箱：待裁决 AI 建议 ＋ 我的任务（＋管理员全部 pending 视图）。

    「全部 pending / 待我裁决」视图随 _is_admin_like 的六角色升级（R1-2
    同源口径）对授予式管理角色开放；裁决按钮区由 _render_pending_inbox
    按 _can_adjudicate_inbox 收口（R1-5）。
    """
    _pop_flash()
    pending = _render_pending_inbox(me)
    if _is_admin_like(me):
        _render_admin_all_pending(len(pending))
        _render_adjudication_section(me)
    st.divider()
    _render_my_tasks(me)


# ============================================
# tab 2 · 协同度量
# ============================================

def _render_metrics_tab() -> None:
    """📊 协同度量：get_stats 总卡（None 显示「—」不虚构）＋按工序下钻表。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>📈 提案台账总览（全库口径）</h3>",
                unsafe_allow_html=True)
    stats = get_stats()  # 数据库不可用时返回全 0 口径 dict（比率 None）
    cards = st.columns(3)
    cards[0].metric("提案总数", str(stats.get("total", 0)))
    cards[1].metric("待裁决", str(stats.get("pending", 0)))
    cards[2].metric("采纳率", _fmt_rate(stats.get("adoption_rate")))
    st.caption(
        "采纳率＝采纳 ÷（采纳＋否决＋修改后采纳），分母是已裁决提案（pending 不计）；"
        "「—」＝尚无已裁决提案，不是 0%。"
    )

    st.markdown(f"<h3 style='{HEADER_H3}'>🔬 按工序下钻</h3>", unsafe_allow_html=True)
    stages = _list_proposal_stages()
    if not stages:
        st.info("台账暂无提案记录（或数据库不可用）—— 提案由各业务工序登记后按工序汇总。")
        return
    drill_rows = []
    for stage in stages:
        s = get_stats(stage)
        drill_rows.append({
            "工序": s.get("stage") or stage,
            "总数": s.get("total", 0),
            "待裁决": s.get("pending", 0),
            "采纳": s.get("adopted", 0),
            "否决": s.get("rejected", 0),
            "修改后采纳": s.get("modified", 0),
            "采纳率": _fmt_rate(s.get("adoption_rate")),
            "平均不确定度": _fmt_uncertainty(s.get("avg_uncertainty")),
        })
    st.dataframe(drill_rows, use_container_width=True, hide_index=True)
    st.caption(
        "平均不确定度按该工序全部提案（含已裁决）平均 —— 度量信号本身的质量；"
        "「—」＝该工序暂无带不确定度的提案。"
    )


# ============================================
# tab 3 · 任务分配（词典管理员门）
# ============================================

def _candidate_assignees(users: List[Dict[str, Any]]) -> Dict[str, int]:
    """标注任务可承担的账号下拉（「显示名 → users.id」映射，过渡期口径）。

    过滤（任务×角色矩阵：标注→annotator+，两源取并集 —— 宁可多列由分派人把关）：
      1. 旧 users.role 列（施工规范 §5 指定的 list_users 入口）∈
         LEGACY_ASSIGNEE_ROLES；
      2. 或 users_db.list_roles 六角色 ∩ SIX_ROLE_ASSIGNEE_ROLES 非空
         （user_roles 是 v5.1 事实源，覆盖「旧列 viewer 但已 grant_role('annotator')」）。
    停用账号一律排除；六角色会话接线后统一走 list_roles（留给批次 3，见模块 docstring）。
    """
    options: Dict[str, int] = {}
    for u in users:
        uid = int(u.get("id") or 0)
        if uid <= 0 or not int(u.get("active") or 0):
            continue
        legacy = u.get("role")
        if legacy not in LEGACY_ASSIGNEE_ROLES:
            six_roles = set(list_roles(uid)) & set(SIX_ROLE_ASSIGNEE_ROLES)
            if not six_roles:
                continue
        display = u.get("display_name") or u.get("username")
        options[f"{u.get('username')}（{display}）· {legacy}"] = uid
    return options


def _render_verb_picker() -> Optional[List[str]]:
    """① 搜索并多选范围动词（oald_senses × definitions 参数化只读搜索）。

    Returns:
        list[str] | None: 选中的动词清单；一个不选返回 None（DDL 语义：
        scope_verbs NULL = 任务不限动词，覆盖全库）。
    """
    results_key = f"{KEY_PREFIX}verb_results"
    st.markdown("**① 范围动词（可空）**")
    keyword = st.text_input(
        "搜索动词 / 义位（匹配词目或 OALD 义项词目，参数化只读查询）",
        key=f"{KEY_PREFIX}assign_search",
        max_chars=50,
        placeholder="如 run、walk；留空直接创建＝不限动词",
    )
    if st.button("🔍 搜索", key=f"{KEY_PREFIX}assign_search_btn"):
        st.session_state[results_key] = _search_verbs(keyword)
        # 新搜索结果替换旧清单：清掉上一次的勾选，避免过期选项残留会话
        st.session_state.pop(f"{KEY_PREFIX}assign_verbs", None)
    results = st.session_state.get(results_key) or []
    if not results:
        st.caption("未搜索或无命中：不选动词则任务不限动词（scope_verbs=NULL，全库）。")
        return None
    verb_options = {
        f"{r['verb']}（OALD 义项 {r.get('oald_senses') or 0} 条）": str(r["verb"])
        for r in results
        if r.get("verb")
    }
    st.caption(f"命中 {len(verb_options)} 个动词（最多列 20 条，可换关键词重搜）。")
    picked = st.multiselect(
        "选择范围动词（可多选；一个不选＝不限动词）",
        list(verb_options.keys()),
        key=f"{KEY_PREFIX}assign_verbs",
    )
    if not picked:
        return None
    return [verb_options[label] for label in picked]


def _render_assign_tab(me: Dict[str, Any]) -> None:
    """📋 任务分配（词典管理员门）：选动词 → 选标注员 → task_type → 三校验 → 创建分派。

    **role gate 在 tab 入口**（纵深防御，不信任前端隐藏）：legacy role=='admin'
    兼判（_is_admin_like）＋ 六角色会话读 user['roles'] 含 dict_admin（批次 3
    会话口径，缺 roles 键回退 legacy 判定）。创建分派前接三重校验（批次 3）：
    ① 任务×角色矩阵（_check_role_matrix）；② 负荷上限（_check_load_limit，
    默认 10）；③ 回避制（_check_recusal，审校类任务批次 4 接入，本期占位放行）
    —— 拒绝原因一律 st.warning 展示，不静默、不落库。
    """
    if not _is_admin_like(me):
        st.warning(
            "⛔ 任务分配仅词典管理员可用（有效六角色集含 dict_admin / sys_admin；"
            "legacy role=='admin' 经映射兼判）。"
        )
        return
    st.markdown(f"<h3 style='{HEADER_H3}'>📤 创建任务分派</h3>", unsafe_allow_html=True)
    st.caption(
        "分派规则（帮助文档 §6.6 ＋ 架构规范 §8）：创建前接三重校验 —— ① 任务×"
        "角色矩阵（标注类须 annotator 及以上）；② 负荷上限（同人在途 open/"
        f"in_progress ≥ {LOAD_LIMIT_DEFAULT} 拒绝）；③ 回避制（审校类任务批次 4 "
        "接入，本期占位放行）。范畴暂取表默认 motion。"
    )

    scope_verbs = _render_verb_picker()

    users = list_users()
    candidates = _candidate_assignees(users)
    if not candidates:
        st.info(
            "没有可分派的标注员：请先在「用户管理」建号并授予 annotator 及以上角色"
            "（或经六角色 grant_role 授予）。"
        )
        return
    st.markdown("**② 标注员**")
    assignee_label = st.selectbox(
        "选择标注员（在用账号、annotator 及以上）",
        list(candidates.keys()),
        key=f"{KEY_PREFIX}assign_assignee",
    )
    st.markdown("**③ 任务类型**")
    task_type = st.selectbox(
        "任务类型（assignments.task_type 枚举）",
        list(ASSIGNMENT_TASK_TYPES),
        format_func=lambda t: f"{TASK_TYPE_LABELS.get(t, t)}（{t}）",
        key=f"{KEY_PREFIX}assign_task_type",
    )

    st.markdown("---")
    if st.button("📤 创建分派", type="primary", key=f"{KEY_PREFIX}assign_submit"):
        assignee_id = candidates[assignee_label]
        # assignee_roles = 六角色事实源（users_db.list_roles）∪ 账号 legacy role
        legacy_role = _legacy_role_map(users).get(assignee_id)
        assignee_roles = sorted({r for r in [*list_roles(assignee_id), legacy_role] if r})
        # 批次 3 三重校验：任一拒绝原因都展示给分派人，且不落库
        reasons = [
            reason
            for reason in (
                _check_role_matrix(task_type, assignee_roles),
                _check_load_limit(assignee_id),
                _check_recusal(task_type, assignee_id, int(me.get("id") or 0)),
            )
            if reason
        ]
        if reasons:
            for reason in reasons:
                st.warning(reason)
            logger.info(
                f"任务分派被拒（assignee={assignee_id}, task_type={task_type}, "
                f"roles={assignee_roles}）：{len(reasons)} 项校验未过"
            )
            return
        try:
            actor = guards.require_dict_admin()
        except PermissionError as e:
            st.error(f"⛔ {e}")
            return
        new_id = create_assignment(
            assignee_id=assignee_id,
            task_type=task_type,
            scope_verbs=scope_verbs,
            assigned_by=int((actor or me).get("id") or 0),
        )
        if new_id:
            scope_text = "全部动词" if scope_verbs is None else "、".join(scope_verbs)
            st.success(
                f"已创建任务 #{new_id}（{TASK_TYPE_LABELS.get(task_type, task_type)}，"
                f"范围：{scope_text}）—— 已出现在该标注员的收件箱「我的任务」里。"
            )
            logger.info(
                f"词典管理员 {me.get('username')} 创建分派 #{new_id}"
                f"（assignee={assignee_id}, task_type={task_type}, "
                f"scope={'ALL' if scope_verbs is None else scope_verbs}）"
            )
        else:
            st.error(
                "创建失败：assignments 表未初始化（需标注流程模块建表）、"
                "标注员不存在或数据库错误，详见服务端日志。"
            )


# ============================================
# 页面入口
# ============================================

def render_collab_page() -> None:
    """AI 协作区页面入口（🤖 AI 协作区级菜单 → 页内三 tab）。

    **登录门在函数入口**（纵深防御）：未登录 st.warning 后 return，页面内容
    不渲染；收件箱/度量对登录全角色开放。任务分配 tab 已迁词典管理区
    （render_dict_admin_page 六 tab 之一，复用本模块 _render_assign_tab）。
    GUIDE（使用说明）由集成方并入 PAGE_GUIDES 后在 app.py 侧调用
    render_page_usage_guide，页面模块不自引（与 users_admin_page 同口径）。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录。")
        return

    st.markdown(
        f"<h1 style='{HEADER_H1}'>{_html_escape(str(GUIDE['label']))} · AI 协作区</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<h2 style='{HEADER_H2}'>人机协同：AI 建议裁决 · 协同度量</h2>",
        unsafe_allow_html=True,
    )

    inbox_tab, metrics_tab = st.tabs(["📥 协作收件箱", "📊 协同度量"])
    with inbox_tab:
        _render_inbox_tab(me)
    with metrics_tab:
        _render_metrics_tab()
