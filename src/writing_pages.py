"""释义撰写与审校工作台 —— 编纂成文域页面（批次 7 Agent U，阶段 2 主打第一批）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§3 工序 10/13（释义撰写 · 审校
定稿，G4/G5 闸门）、§6 D④ 编纂成文域、§8 编纂协作范式（簇承包 → 多轮审校
（回避制）→ 定稿；两级终审）；契约：docs/spec/阶段1施工规范.md §10 Agent U 行。

页面行为依据 docs/help/平台功能使用说明.md「4.2 释义撰写与审校」（说明即验收
标准）：编纂员簇承包撰写：模板 → 释义草稿 → 编者改定 → 版本留痕 → 审校
（初审 → 修订 → 终审）→ 定稿；意见线逐条挂义位；状态机 draft→in_review→
reviewed→revised→approved→final→published。编纂协作与标注协作是**两种范式**
——表达类工作不盲标、不算 α，质量靠「承包制（同簇同人保口吻）＋ style.yaml
硬准绳＋AI 体例质检＋终审」。

三 tab（st.tabs）：
  ✍️ 撰写台   选义位（cs_senses **locked 簇优先** —— G3 闸门：分立复核定稿的
              簇才放行撰写；merged 义位禁选）→ 模板预览（template_engine，
              占位容错：不在建模覆盖内不拦撰写）→ text_area 成文编辑 →
              保存草稿（create_draft / update_draft 乐观锁）→ 提交初审
              （选审校人，回避制数据层硬校验）；
  ⚖️ 审校台   list_pending_reviews 待审列表 → expander 释义内容 ＋ ai_draft
              对照 → 意见线（add_comment / list_comments）→ 裁决
              （request_revision 打回 / approve 通过——终审即 final MVP）；
              批次 8 G6 增「👑 词典管理员终裁」子视图（_can_adjudicate =
              effective 含 dict_admin）：全部 in_review/approved 版本逐条
              expander → 终裁通过（final 直达）/终裁否决（rejected＋理由必填）
              → writing_db.adjudicate_final（两级终审的例外通道收口）；
  📚 版本历史 版本链表（版本/状态/作者/based_on_version/体例版本）＋ 逐版
              成文、意见线与 AI 快照，收口（resolve_comment）只标记不删行；
              R1-10 脱敏：viewer/annotator 视角作者/意见人折算「编纂员 A/B」
              （按出现序稳定编号），draft 态内容显示「🔒 撰写中」——
              reviewer/dict_admin（含 editor）实名全链不变。

权限（角色纯函数，**不 import app**）：_can_write（有效六角色 ∩ {editor,
dict_admin}）/ _can_review（∩ {reviewer, dict_admin}）/ _can_adjudicate
（批次 8 G6：须含 dict_admin —— 终裁是例外通道，不随 reviewer 继承），判定
复用 users_db.effective_six_roles 单一实现（过渡期 role=='admin' 经 legacy
映射兼判 dict_admin，无需另写分支）。页面入口先登录门；撰写台/审校台各自在
tab 内做角色门（版本历史全角色可读 —— 区级菜单「编纂产出区（全角色）」）。

数据层（src/writing_db.py）负责状态机/回避制/乐观锁硬校验；本页面只做
转述（0/False 返回一律 st.warning/st.error 展示，不静默）＋两层防御的
第一层（tab 级角色门）。审校人指派下拉实时过滤：active 用户 − 本人 −
无 reviewer/dict_admin 有效角色者（users_db.list_roles 实时判定）。

由集成步骤挂载（render_writing_page() 注册进 app.py 分派 + GUIDE 并入
PAGE_GUIDES["writing"]）；本模块不修改 app.py / page_guides.py。

输出转义口径（与 dict_admin_pages / sense_spine 同源）：进
unsafe_allow_html 的用户生成内容一律先 _esc；释义成文/意见走
st.markdown（unsafe_allow_html=False）由 Streamlit 自动转义；selectbox/
expander 选项文本由 Streamlit 自带转义，不再手工转。widget key 一律
'writing_' 前缀。
"""

import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

import src.writing_db as writing_db
from src import users_db
from src.db_utils import current_user as _current_user  # R6-4：单一实现点
from src.design_system import HEADER_H1, HEADER_H2, HEADER_H3
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 页面使用说明（四段式；集成时原样并入 PAGE_GUIDES["writing"]）
# ============================================

GUIDE: Dict[str, Any] = {
    "label": "✍️ 释义撰写与审校",
    "purpose": (
        "编纂成文域工作台（工序 10/13）：编纂员按簇承包撰写释义 —— locked 簇优先"
        "选义位 → 模板预览打底 → 成文编辑 → 版本留痕 → 提交审校（回避制）→ "
        "意见线逐条收口 → 终审定稿 → 词典管理员发布；状态机 "
        "draft→in_review→reviewed→revised→approved→final→published 全程留痕。"
    ),
    "principle": [
        "编纂协作与标注协作是两种范式（架构规范 §8）：表达类工作不盲标、不算 α "
        "（散文无 α），质量靠「簇承包制（同簇同人保口吻）＋ style.yaml 硬准绳＋"
        "AI 体例质检＋终审」；审校走回避制且无豁免（含词典管理员）—— 审校动作"
        "（指派/意见/打回/通过）的审校人一律不得是撰写人，数据层硬校验。",
        "G3 闸门位消费：撰写台选义位时 locked 簇优先展示（🔒 = 分立复核定稿，"
        "义项清单锁定后才允许流入释义撰写）；未锁定簇与未入簇义位仍可选但如实"
        "标注 ⚠️；status='merged'（已并入他义位）的义位一律禁选。",
        "模板预览是确定性引擎（template_engine，不调 LLM）：四维模板是编者的"
        "结构化语义底座，不是成品释义 —— 成文以文本框人工改定为准；义位不在"
        "建模覆盖内时预览占位降级，不拦撰写。",
        "版本链完整性：version 在 sense_ref 内自动递增（UNIQUE 兜底并发），打回"
        "重提自动 version+1 并挂 based_on_version（指向被拒版号）—— 任何一版"
        "释义可答「谁写的、基于哪版、哪个体例、AI 提了什么」；每版另记 "
        "style_version 占位（体例工单批次 8 接入）。",
        "两级终审（架构规范 §8）：普通词条 reviewer 审校通过即 final（MVP 单级"
        "口径）；争议词条升级词典管理员终裁是例外通道而非必经站 —— 批次 8 G6 "
        "开通「👑 词典管理员终裁」子视图（仅 dict_admin 可见）：对全部 "
        "in_review/approved 版本终裁通过（→ final 直达收口）或终裁否决（→ "
        "rejected，理由必填），数据层 adjudicate_final 以同源 effective 口径"
        "再校验角色与回避制；published 仅词典管理员可执行，G6 许可/体例/备份"
        "硬闸门由词典管理区「📤 出版导出」标签页接管。",
        "乐观锁防互踩：改稿带 expect_version（表单装载时看到的版本号），草稿被"
        "流转或目标行已易主时保存被拒 —— 双开标签页/先存后提的竞态在数据层挡住。",
    ],
    "data_source": [
        "src/writing_db.py：definition_versions / review_tasks / review_comments "
        "三表（建版/改稿/提交/裁决/终裁 adjudicate_final/发布 CRUD＋list_versions "
        "版本链＋list_pending_reviews 待审清单）—— 状态机与回避制硬校验都在数据层。",
        "cs_senses / cs_lexemes / categories / cs_cluster_members / cs_clusters "
        "（category_study 8 表，本页私有只读查询）：撰写台义位下拉 —— 最新聚类"
        "运行的簇归属 ＋ locked 徽标（G3 闸门位），merged 义位过滤。",
        "src/template_engine.py：instantiate_template 槽位实例化（确定性引擎）"
        "—— 撰写台模板预览与 ai_draft 快照（审校对照用），只读不写。",
        "oald_senses × definitions（本页私有只读查询）：sense_ref 第三段 OALD 锚"
        "解析（definitions.verb + oald_senses.sense_index 对齐；解析不到 0 占位）。",
        "src/users_db.py：list_users / list_roles / effective_six_roles —— 审校人"
        "下拉（active − 本人 − 无 reviewer/dict_admin 角色者）与角色纯函数判定。",
    ],
    "steps": [
        "进「✍️ 撰写台」选范畴/语言后挑义位：下拉按 🔒 locked 簇优先排序（G3 "
        "已放行），簇名与状态徽标如实展示；merged 义位不出现在下拉里。",
        "展开「🧩 模板预览」读四维模板与 OALD 原文对照（不在建模覆盖内时给占位"
        "提示，不拦撰写）；在成文编辑框写定释义（替换性测试口径：释义须可代回"
        "语料原文），可选填体例版本（如 style.yaml@v1）。",
        "点「💾 保存草稿」落库（首版自动建 v1；在途自有草稿走乐观锁更新；打回"
        "重提自动 version+1 并挂 based_on_version）；再选审校人（回避制：列表已"
        "滤掉自己）点「📨 提交初审」—— draft → in_review，任务进入对方审校台。",
        "切「⚖️ 审校台」查看待我审校列表（词典管理员可勾选总览全部）：expander 里"
        "对照释义内容与 AI/模板草稿快照，先「💬 挂意见」逐条留痕，再裁决 —— "
        "「⛔ 要求修订」给理由打回（in_review → rejected），「✅ 通过」即终审定稿"
        "（in_review → final）。",
        "争议词条升级终裁（批次 8 G6）：词典管理员在审校台底部「👑 词典管理员"
        "终裁」子视图看到全部 in_review/approved 版本 —— 逐条展开后「👑 终裁"
        "通过」（→ final 直达，两级终审收口）或「⛔ 终裁否决」（→ rejected，"
        "理由必填、随任务行留痕）；reviewer 单角色看不到该子视图。",
        "「📚 版本历史」按义位查版本链表：版本/状态/作者/基于版本/体例版本一目"
        "了然；逐版展开看成文、AI 快照与意见线，作者或审校人可把未处理意见"
        "「✔️ 标记已处理」（收口只标记不删行）。",
        "定稿（final）后的发布由词典管理员在集成后的出版链路执行（final → "
        "published，仅 dict_admin；G6 许可/体例/备份硬闸门批次 8 接管）。",
    ],
    "notes": [
        "回避制无豁免（架构规范 §8）：审校人＝撰写人的提交/留言/打回/通过在数据"
        "层直接拒绝；系统登记（author_id 为空）的版本无可比对对象，如实放行并"
        "记日志。审校人下拉已前置过滤本人与无审校角色者。",
        "裁决与意见分权：✅/⛔ 只认受派审校人（review_tasks.reviewer_id 一致）；"
        "意见线任何非作者审校人可挂 —— 词典管理员总览他人任务时可挂意见但裁决"
        "会被拒（页面黄色提示预告）。",
        "撰写台编辑目标按最新版状态自动判定：自有 draft 续写（乐观锁更新）；他"
        "人在途 draft 另起新版（不读入他人未定稿内容）；rejected 版打回重提"
        "（预填被拒内容＋挂 based_on_version）；in_review/final/published 另起"
        "新版并提示。",
        "merged 义位禁选是硬口径（分立复核已并入他义位，再写释义即分叉）；未锁"
        "定簇/未入簇义位可选但页面如实标注 ⚠️ —— G3 的放宽消费是显式选择而非"
        "静默放行。",
        "审校通过即 final 是 MVP 口径（普通词条 reviewer 终审即 final）；批次 8 "
        "G6 的词典管理员终裁（adjudicate_final）是例外通道：in_review/approved "
        "→ final 直达或 in_review → rejected，reviewed/revised 两态仍为占位不经由。"
        "终裁不覆盖受派审校人的既有任务行（伪造 verdict 即篡改审校记录），终裁以"
        "新任务行落 review_tasks（round+1 标记终裁轮）；终裁后受派人的 pending "
        "任务保持原样，其裁决动作会被数据层状态守卫拒绝。",
        "所有用户生成内容（成文/意见/词目/簇名/说明）渲染前一律转义；markdown "
        "正文走 Streamlit 自带转义通道 —— 释义里出现 HTML/标记只会被当普通文本。",
    ],
}

# ============================================
# 展示常量（徽章配色与枚举中文名；存库一律英文枚举值）
# ============================================

STATUS_LABELS: Dict[str, str] = {
    "draft": "草稿",
    "in_review": "审校中",
    "reviewed": "已初审",
    "revised": "已修订",
    "approved": "终审通过",
    "final": "定稿",
    "published": "已发布",
    "rejected": "已打回",
}

STATUS_BADGE_COLORS: Dict[str, str] = {
    "draft": "#718096",
    "in_review": "#2b6cb0",
    "reviewed": "#4299e1",
    "revised": "#805ad5",
    "approved": "#2f855a",
    "final": "#276749",
    "published": "#22543d",
    "rejected": "#c53030",
}

VERDICT_LABELS: Dict[str, str] = {
    "pending": "待审",
    "approved": "通过",
    "rejected": "否决",
    "revision_requested": "要求修订",
}

# 角色口径（架构规范 §8 任务×角色矩阵）：撰写/例证/对译→editor+；审校→reviewer+；
# 词典管理员终裁（批次 8 G6，例外通道）→dict_admin 单列（不继承 reviewer/editor）
_WRITE_ROLES = {"editor", "dict_admin"}
_REVIEW_ROLES = {"reviewer", "dict_admin"}
_ADJUDICATE_ROLES = {"dict_admin"}

# 版本历史实名口径（R1-10，施工规范 §14 批次 12）：editor/reviewer/dict_admin
# 实名全链不变（编纂协作与审校的署名权与追责链）；viewer/annotator（编纂圈外
# 只读/盲标角色）视角作者/意见人折算「编纂员 A/B」。sys_admin 单角色（管理侧
# 非编纂圈，且账号生命周期职能不涉成文内容）按折算处理 —— fail-closed 取窄。
_HISTORY_REALNAME_ROLES = {"editor", "reviewer", "dict_admin"}

# draft 态内容对折算视角的展示文案（R1-10：在途草稿不外露）
_DRAFT_HIDDEN_TEXT = "🔒 撰写中（草稿内容仅作者与审校侧可见）"


# ============================================
# 角色纯函数（不 import app；判定复用 users_db 单一实现）
# ============================================

def _can_write(user: Any) -> bool:
    """会话用户是否可撰写（纯函数，fail-closed）。

    有效六角色集（users_db.effective_six_roles：legacy role 列映射 ∪ session
    roles 快照）与 {editor, dict_admin} 有交集即放行；过渡期 role=='admin'
    经 legacy 映射兼判（admin → dict_admin+sys_admin，两位一体）。非 dict
    会话 / sys_admin / reviewer / annotator / viewer 一律不可写。
    """
    if not isinstance(user, dict):
        return False
    return bool(users_db.effective_six_roles(user) & _WRITE_ROLES)


def _can_review(user: Any) -> bool:
    """会话用户是否可审校（纯函数，fail-closed）。

    有效六角色集与 {reviewer, dict_admin} 有交集即放行（词典管理员继承
    reviewer 职能，架构规范 §8）；过渡期 role=='admin' 经 legacy 映射兼判。
    editor 单角色不可自审（回避制同源口径：撰写与审校分权）。
    """
    if not isinstance(user, dict):
        return False
    return bool(users_db.effective_six_roles(user) & _REVIEW_ROLES)


def _can_adjudicate(user: Any) -> bool:
    """会话用户是否可词典管理员终裁（纯函数，fail-closed；批次 8 G6）。

    有效六角色集须含 dict_admin（终裁是例外通道而非必经站，不随 reviewer
    继承 —— reviewer 单角色不见终裁子视图）；过渡期 role=='admin' 经
    effective_six_roles 的 legacy 映射兼判。数据层 adjudicate_final 以同一
    effective 口径再校验（actor 显式传入，纵深防御两层）。
    """
    if not isinstance(user, dict):
        return False
    return bool(users_db.effective_six_roles(user) & _ADJUDICATE_ROLES)


def _history_realname(user: Any) -> bool:
    """版本历史是否实名（纯函数，fail-closed；R1-10 脱敏口径）。

    有效六角色集与 _HISTORY_REALNAME_ROLES（editor/reviewer/dict_admin）
    有交集即实名；viewer/annotator/未登录按折算处理 —— 作者/意见人显示
    「编纂员 A/B」（按出现序稳定编号，见 _render_history_tab）。判定复用
    users_db.effective_six_roles 单一实现（legacy admin 经映射兼判）。
    """
    if not isinstance(user, dict):
        return False
    return bool(users_db.effective_six_roles(user) & _HISTORY_REALNAME_ROLES)


def _pseudonym_factory():
    """「编纂员 A/B/…」稳定编号生成器（纯函数；R1-10 折算口径）。

    按首次出现顺序编号：A、B、…、Z，超过 26 人后 A2、B2、…（同一 user id
    恒得同一代号，不同 version 间可复现 —— 顺序敏感度仅限「谁先出现」，
    与版本链升序一致）。返回 (lookup_fn, alias_map)：lookup_fn(None) 返回
    「系统登记」。
    """
    alias_map: Dict[int, str] = {}

    def _letter(idx: int) -> str:
        """序号 → 稳定代号（A..Z，超过 26 人 A2/B2/…；R6-11 补一行式）。"""
        if idx < 26:
            return chr(ord("A") + idx)
        return f"{chr(ord('A') + idx % 26)}{idx // 26 + 1}"

    def _who(uid_any: Any) -> str:
        """user id → 折算显示名（首次出现按序编号，同 id 恒同代号）。"""
        uid = _safe_int(uid_any)
        if uid is None:
            return "（系统登记）"
        if uid not in alias_map:
            alias_map[uid] = f"编纂员 {_letter(len(alias_map))}"
        return alias_map[uid]

    return _who, alias_map


def _esc(value: Any) -> str:
    """任意值 → HTML 安全文本（str() 后 html.escape 含引号）。

    所有进 unsafe_allow_html 的用户生成内容/库内文本必须先过这里；
    selectbox 等纯文本控件由 Streamlit 自带转义，调用方不要再转。
    """
    return _html_escape(str(value), quote=True)


# ============================================
# 纯函数：sense_ref / 展示口径 / 编辑目标判定 / AI 快照
# ============================================

def _safe_int(value: Any) -> Optional[int]:
    """宽松转 int（失败 None；bool 借道 int —— 页面侧容忍度高于数据层）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_sense_ref(category: str, cs_id: Any, oald_id: Any) -> Optional[str]:
    """三段式锚拼装 ``category:cs_id:oald_id``（0 占位口径）；非法返回 None。

    口径与 writing_db.valid_sense_ref 一致：范畴段非空，两段 id 为非负整数
    （0 = 未落位），总长 ≤ 60。
    """
    cat = str(category or "").strip()
    cs = _safe_int(cs_id)
    oid = _safe_int(oald_id)
    if not cat or cs is None or cs < 0 or oid is None or oid < 0:
        return None
    ref = f"{cat}:{cs}:{oid}"
    return ref if writing_db.valid_sense_ref(ref) else None


def _parse_sense_ref(sense_ref: Any) -> Optional[Tuple[str, int, int]]:
    """``motion:12:345`` → ('motion', 12, 345)；格式非法返回 None。"""
    if not writing_db.valid_sense_ref(sense_ref):
        return None
    cat, cs, oid = str(sense_ref).strip().split(":")
    return cat, int(cs), int(oid)


def _format_dt(value: Any) -> str:
    """datetime 展示口径：None → '—'，datetime → 'YYYY-MM-DD HH:MM'，脏值原样。"""
    if value is None:
        return "—"
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(value)


def _sense_option_label(sense: Dict[str, Any]) -> str:
    """撰写台义位下拉选项文案（Streamlit 自带转义，勿先 _esc）。

    格式：``lemma sense_no「sense_label」 · status · 簇徽标``；
    簇徽标：🔒 簇#N（G3 已锁定） / 簇#N（未锁定） / 未入簇 —— locked 簇优先
    的可视化承载（_sort_senses_locked_first 排序，本函数负责如实标注）。
    """
    lemma = str(sense.get("lemma") or "—")
    sense_no = str(sense.get("sense_no") or "—")
    label = str(sense.get("sense_label") or "—")
    status = str(sense.get("status") or "—")
    if sense.get("locked"):
        cluster = f"🔒 簇#{sense.get('cluster_no')}（G3 已锁定）"
    elif sense.get("cluster_id"):
        cluster = f"⚠️ 簇#{sense.get('cluster_no')}（未锁定）"
    else:
        cluster = "⚠️ 未入簇"
    return f"{lemma} {sense_no}「{label}」 · {status} · {cluster}"


def _sort_senses_locked_first(senses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """义位清单排序（纯函数）：locked 簇优先 → 未锁定簇 → 未入簇。

    G3 闸门消费口径（施工规范 §10）：**优先**不等于禁选未锁定 —— 排序给出
    承包推荐序，未锁定/未入簇以 ⚠️ 标注（_sense_option_label），merged 已在
    查询层过滤。同组内 lemma/sense_no/cs_id 稳定排序，下拉顺序可复现。
    """

    def _key(s: Dict[str, Any]) -> Tuple[int, str, str, int]:
        """单义位排序键（锁定分组 → 词目 → 义项号 → cs_senses.id）。"""
        locked = bool(s.get("locked"))
        has_cluster = s.get("cluster_id") is not None
        group = 0 if locked else (1 if has_cluster else 2)
        return (
            group,
            str(s.get("lemma") or ""),
            str(s.get("sense_no") or ""),
            _safe_int(s.get("cs_sense_id")) or 0,
        )

    return sorted(senses, key=_key)


def _resolve_edit_target(
    latest: Optional[Dict[str, Any]], user_id: Any
) -> Dict[str, Any]:
    """按最新版状态判定撰写台编辑动作（纯函数；MVP 状态机的视图层映射）。

    规则（与 help §4.2「版本留痕→审校→修订」口径一致）：
      * 无任何版本            → create（全新首版，based_on_version=None）；
      * latest=draft 且是本人 → update（续写自有草稿，乐观锁
                                expect_version=latest 版本号）；
      * latest=draft 但是他人 → create（空起，notice 他人在途 —— 不读入
                                他人未定稿内容当底稿）；
      * latest=rejected       → create（预填被拒内容，based_on_version=被拒
                                版号，notice 打回重提口径 —— version 自动 +1）；
      * 其余状态（in_review/reviewed/revised/approved/final/published）
                              → create（空起，notice 已有在途/已定版本）。

    author_id 缺失（系统登记行）按「非本人」处理（fail-closed：无法确认
    归属的草稿不进乐观锁更新路径）。

    Returns:
        dict: {mode: 'update'|'create', target_id, expect_version, prefill,
        based_on_version, notice} —— notice 非 None 时页面以 st.info 转述。
    """
    none_target: Dict[str, Any] = {
        "mode": "create", "target_id": None, "expect_version": None,
        "prefill": "", "based_on_version": None, "notice": None,
    }
    if not isinstance(latest, dict):
        return none_target
    status = str(latest.get("status") or "")
    version_no = _safe_int(latest.get("version"))
    mine = (
        _safe_int(latest.get("author_id")) is not None
        and _safe_int(latest.get("author_id")) == _safe_int(user_id)
    )
    if status == writing_db.STATUS_DRAFT and mine:
        return {
            "mode": "update",
            "target_id": _safe_int(latest.get("id")),
            "expect_version": version_no,
            "prefill": str(latest.get("content") or ""),
            "based_on_version": None,
            "notice": None,
        }
    if status == writing_db.STATUS_DRAFT:
        author = _safe_int(latest.get("author_id"))
        return {
            **none_target,
            "notice": (
                f"该义位已有他人在途草稿 v{version_no}（作者 #{author if author is not None else '系统'}）："
                "你的新草稿将另起新版，互不影响；请以审校定稿口径协调承包归属。"
            ),
        }
    if status == writing_db.STATUS_REJECTED:
        return {
            "mode": "create",
            "target_id": None,
            "expect_version": None,
            "prefill": str(latest.get("content") or ""),
            "based_on_version": version_no,
            "notice": (
                f"上一版 v{version_no} 已被审校打回：本次保存将自动建 v{(version_no or 0) + 1} "
                f"并挂 based_on_version={version_no}（版本链留痕，见「📚 版本历史」）。"
            ),
        }
    label = STATUS_LABELS.get(status, status or "未知")
    return {
        **none_target,
        "notice": f"该义位最新版 v{version_no} 处于「{label}」：新草稿将另起新版。",
    }


def _build_ai_draft_snapshot(template: Any) -> Optional[Dict[str, Any]]:
    """模板预览 dict → ai_draft 快照（审校台「AI/模板草稿对照」的数据面）。

    全容错纯函数：template 非 dict / 缺键一律尽力取值（缺的键给 None），
    不可快照（非 dict）返回 None。快照只随草稿落库一次 —— 之后模板引擎
    再怎么演进，审校对照的仍是提交当时所见（留痕纪律）。
    """
    if not isinstance(template, dict):
        return None
    dim = template.get("图式维度") or {}
    oald = template.get("oald") or {}
    syntax = template.get("句法维度") or {}
    return {
        "kind": "template_preview",
        "generated_by": "template_engine",
        "template_text": str(template.get("template_text") or ""),
        "schema_name": dim.get("name"),
        "schema_code": dim.get("code"),
        "cluster_no": dim.get("cluster_no"),
        "oald_source": oald.get("source"),
        "oald_definition": oald.get("definition"),
        "transitivity": syntax.get("transitivity"),
        "n_semantic_params": len(template.get("语义参数维度") or []),
    }


# ============================================
# 私有只读查询（sense_spine _fetch_* 风格：独立降级，绝不编数）
# ============================================

def _list_categories_dicts() -> List[Dict[str, Any]]:
    """范畴清单（category_study.get_categories 薄包装；失败返回 []）。

    R6-4 改名 _list_categories_dicts：返回 dict 清单（含 code/name_cn 等），
    与 reliability._list_categories（返回 code 元组）同名不同义，就地改名
    消歧 —— 语义与调用点不变。
    """
    try:
        from src.category_study import get_categories

        return [c for c in (get_categories() or []) if c.get("code")]
    except Exception as e:  # noqa: BLE001 — 降级不崩（页面给占位提示）
        logger.warning(f"writing_pages: 范畴清单查询失败: {e}")
        return []


_CANDIDATE_SENSES_SQL = """SELECT s.id AS cs_sense_id, s.sense_no, s.sense_label,
       s.status, l.lemma, l.language, c.code AS category_code,
       c.name_cn AS category_name, cl.id AS cluster_id, cl.cluster_no, cl.locked
FROM cs_senses s
JOIN cs_lexemes l ON s.lexeme_id = l.id
JOIN categories c ON l.category_id = c.id
LEFT JOIN cs_cluster_members m ON m.sense_id = s.id
LEFT JOIN cs_clusters cl ON cl.id = m.cluster_id
LEFT JOIN cs_cluster_runs r ON r.id = cl.run_id
WHERE c.code = %s AND l.language = %s AND s.status <> 'merged'
  AND (cl.id IS NULL OR r.id = (
        SELECT MAX(r2.id) FROM cs_cluster_runs r2
        WHERE r2.category_id = c.id AND r2.language = l.language))
ORDER BY l.lemma ASC, s.id ASC, cl.id ASC"""


def _list_candidate_senses(category: str, language: str) -> List[Dict[str, Any]]:
    """撰写台义位下拉数据（**只读**）：最新运行簇归属 ＋ locked 徽标。

    merged 禁选在 SQL 层落实（status <> 'merged' —— 分立复核已并入的义位
    再写释义即分叉）；一义位多簇归属（跨运行脏数据）时去重并保留 locked
    行（宁可多提示可锁定，不静默丢簇信息）。最新运行约束与
    template_engine._fetch_sense 同口径（MAX(run_id) per 范畴×语言）。

    Returns:
        list[dict]: 已按 _sort_senses_locked_first 排序；库不可用/未灌 → []。
    """
    cat = str(category or "").strip()
    lang = str(language or "").strip()
    if not cat or lang not in ("en", "zh"):
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(_CANDIDATE_SENSES_SQL, (cat, lang))
            rows = [dict(r) for r in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.error(f"writing_pages: 义位清单查询失败（{cat}/{lang}）: {e}")
        return []
    merged: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        sid = _safe_int(row.get("cs_sense_id"))
        if sid is None or sid <= 0:
            continue
        prev = merged.get(sid)
        if prev is None or (row.get("locked") and not prev.get("locked")):
            merged[sid] = row
    return _sort_senses_locked_first(list(merged.values()))


def _resolve_oald_sense_id(lemma: Any, sense_no: Any) -> int:
    """cs_senses → oald_senses 锚解析（**只读**），失败/未命中返回 0 占位。

    映射口径与 sense_spine 的 cs↔oald 对齐同源（反向）：cs_lexemes.lemma ↔
    definitions.verb、cs_senses.sense_no ↔ oald_senses.sense_index（英语侧
    sense_no 即 OALD 义项号）；汉语侧 sense_no 为 ①②/—（非纯数字）→ 0。
    解析不到不编数 —— sense_ref 第三段 0 占位（writing_db docstring 口径）。
    """
    sn = str(sense_no or "").strip()
    # isdecimal 而非 isdigit：isdigit 对「①」（No 类数字）也 True 而 int() 会炸
    if not sn.isdecimal() or len(sn) > 10:
        return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT os.id FROM oald_senses os "
                "JOIN definitions d ON d.id = os.definition_id "
                "WHERE d.verb = %s AND os.sense_index = %s ORDER BY os.id LIMIT 1",
                (str(lemma or "").strip(), int(sn)),
            )
            row = cursor.fetchone()
            return int(row["id"]) if row else 0
    except Exception as e:  # noqa: BLE001 — 降级不崩（0 占位）
        logger.warning(f"writing_pages: OALD 锚解析失败（lemma={lemma!r}）: {e}")
        return 0


def _template_preview(
    category: str, language: str, cs_sense_id: int
) -> Optional[Dict[str, Any]]:
    """模板预览（template_engine.instantiate_template 薄包装＋全容错）。

    懒 import 避免模块加载顺序耦合（dict_admin_pages 同款做法）；引擎任何
    异常/返回 None 原样折叠为 None —— 页面给占位提示，**不拦撰写**（模板是
    底座不是前置条件，帮助文档 §4.1/§4.2 口径）。
    """
    try:
        from src.template_engine import instantiate_template

        return instantiate_template(str(category), str(language), int(cs_sense_id))
    except Exception as e:  # noqa: BLE001 — 占位容错
        logger.warning(
            f"writing_pages: 模板预览失败（{category}/{language}/{cs_sense_id}）: {e}"
        )
        return None


def _user_display_map() -> Dict[int, str]:
    """users_db.list_users() → {id: 显示名}（审校台署名用；失败 {}）。"""
    try:
        rows = users_db.list_users()
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.warning(f"writing_pages: 用户清单查询失败: {e}")
        return {}
    out: Dict[int, str] = {}
    for row in rows:
        uid = _safe_int(row.get("id"))
        if uid is None:
            continue
        out[uid] = str(row.get("display_name") or row.get("username") or f"#{uid}")
    return out


def _reviewer_options(me: Dict[str, Any]) -> List[Dict[str, Any]]:
    """可指派审校人清单：active 用户 − 本人 − 无 reviewer/dict_admin 角色者。

    逐人 users_db.list_roles 实时判定（六角色事实源在 user_roles 表，会话
    快照只对本人可用；平台团队规模小，N 次查询可接受）。回避制前置过滤
    （排除本人）只是体验优化 —— 数据层仍硬校验，绕过 UI 的调用拦得住。
    任何异常降级为 []（页面提示无可指派审校人，不崩）。
    """
    me_id = _safe_int(me.get("id"))
    try:
        users = users_db.list_users()
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.warning(f"writing_pages: 审校人清单查询失败: {e}")
        return []
    options: List[Dict[str, Any]] = []
    for row in users:
        if not row.get("active"):
            continue
        uid = _safe_int(row.get("id"))
        if uid is None or (me_id is not None and uid == me_id):
            continue
        try:
            roles = set(users_db.list_roles(uid))
        except Exception as e:  # noqa: BLE001 — 单人失败不拖垮全清单
            logger.warning(f"writing_pages: 用户 {uid} 角色查询失败: {e}")
            continue
        if roles & _REVIEW_ROLES:
            display = str(row.get("display_name") or row.get("username") or f"#{uid}")
            options.append({"id": uid, "label": f"{display}（uid {uid}）"})
    return options


# ============================================
# tab 渲染
# ============================================

def _render_write_tab(me: Dict[str, Any]) -> None:
    """✍️ 撰写台：选义位（locked 优先）→ 模板预览 → 成文 → 保存 → 提交初审。"""
    if not _can_write(me):
        st.warning(
            "⛔ 撰写台仅编纂员可用（editor / dict_admin；过渡期 admin 兼判）。"
            "如需权限请联系词典管理员授予。"
        )
        return

    categories = _list_categories_dicts()
    if not categories:
        st.info("范畴清单不可用：数据库未灌语义分析数据（cs_* 表）或库不可用。")
        return
    cat_options = [c["code"] for c in categories]
    cat_code = st.selectbox(
        "范畴",
        options=cat_options,
        format_func=lambda code: next(
            (f"{c['code']} {c['name_cn']}" for c in categories if c["code"] == code),
            code,
        ),
        key="writing_category",
    )
    language = st.radio(
        "语言",
        options=["en", "zh"],
        horizontal=True,
        format_func={"en": "英语（OALD10）", "zh": "汉语（现汉7）"}.get,
        key="writing_language",
    )
    senses = _list_candidate_senses(cat_code, language)
    if not senses:
        st.info(
            "该范畴/语言暂无可撰写义位：cs_senses 未灌数据，或现有义位全部已并入"
            "（merged 禁选口径）。"
        )
        return
    sense = st.selectbox(
        "选择义位（🔒 locked 簇优先 —— G3 闸门：分立复核定稿的簇才放行撰写）",
        options=senses,
        format_func=_sense_option_label,
        key="writing_sense",
    )

    cs_id = _safe_int(sense.get("cs_sense_id")) or 0
    oald_id = _resolve_oald_sense_id(sense.get("lemma"), sense.get("sense_no"))
    ref = _build_sense_ref(str(sense.get("category_code") or ""), cs_id, oald_id)
    if ref is None:
        st.error("义位锚拼装失败（数据异常）：请换一个义位，或联系管理员核查 cs_senses 行。")
        return
    if sense.get("locked"):
        cluster_note = "🔒 G3 已锁定（分立复核定稿，正常放行）"
    elif sense.get("cluster_id"):
        cluster_note = "⚠️ 簇未锁定（G3 未放行 —— 如实标注，是否先行撰写由你显式决定）"
    else:
        cluster_note = "⚠️ 未入簇（无聚类归属 —— 如实标注）"
    st.caption(f"版本锚 sense_ref = {ref} · 簇状态：{cluster_note}")

    latest = writing_db.get_latest_version(ref, viewer_id=me.get("id"))
    target = _resolve_edit_target(latest, me.get("id"))
    if target.get("notice"):
        st.info(target["notice"])

    preview = _template_preview(str(sense.get("category_code") or ""), language, cs_id)
    with st.expander("🧩 模板预览（确定性引擎 · 编者的语义底座，不是成品释义）"):
        if not preview:
            st.info(
                "模板预览暂不可用：该义位不在建模覆盖内 / 缺特征编码 / 范畴包解析"
                "失败 —— 占位容错，不拦撰写，可直接成文。"
            )
        else:
            st.markdown("**模板化释义（底稿）**")
            st.markdown(str(preview.get("template_text") or "（空模板）"))
            dim = preview.get("图式维度") or {}
            oald = preview.get("oald") or {}
            syntax = preview.get("句法维度") or {}
            st.caption(
                f"图式：{dim.get('name') or '—'}（{dim.get('code') or '—'}） · "
                f"句法：{syntax.get('transitivity') or '未标注'} · "
                f"{oald.get('source') or '—'} 原文：{oald.get('definition') or '—'}"
            )
    ai_snapshot = _build_ai_draft_snapshot(preview)

    st.markdown("#### ✍️ 成文编辑")
    content_key = (
        f"writing_content_{target['target_id'] or 0}_"
        f"{_safe_int((latest or {}).get('version')) or 0}"
    )
    content = st.text_area(
        "释义成文",
        value=target["prefill"],
        height=220,
        key=content_key,
        help="替换性测试口径：释义须可代回语料原文（学习词典通行标准）；"
        "定义词表合规检查（AI 体例质检）批次 8 接入。",
    )
    default_style = ""
    if target["mode"] == "update" and latest:
        default_style = str(latest.get("style_version") or "")
    style_version = st.text_input(
        "体例版本（可选，如 style.yaml@v1）", value=default_style,
        key="writing_style_version",
    )

    col_save, col_submit = st.columns(2)
    with col_save:
        st.markdown("**💾 保存草稿**")
        if st.button("保存草稿（版本自动递增）", key="writing_save_draft"):
            if not content.strip():
                st.warning("释义成文为空：请先撰写内容再保存。")
            elif target["mode"] == "update":
                ok = writing_db.update_draft(
                    int(target["target_id"]), int(target["expect_version"]),
                    content, style_version or None, ai_snapshot,
                    author_id=me.get("id"),
                )
                if ok:
                    st.success(
                        f"草稿已更新（v{target['expect_version']}，乐观锁校验通过）。"
                    )
                else:
                    st.error(
                        "保存失败：草稿已被流转或版本已变化（乐观锁拦截）——"
                        "请刷新页面后重试。"
                    )
            else:
                vid = writing_db.create_draft(
                    ref, me.get("id"), content,
                    based_on_version=target.get("based_on_version"),
                    style_version=style_version or None,
                    ai_draft=ai_snapshot,
                )
                if vid:
                    st.success(
                        "草稿已保存（版本号自动递增）：可在「📚 版本历史」查看链路。"
                    )
                else:
                    st.error("保存失败：参数或数据库异常，详见服务端日志。")
    with col_submit:
        st.markdown("**📨 提交初审**")
        reviewers = _reviewer_options(me)
        if not reviewers:
            st.warning(
                "当前没有可指派的审校人（reviewer/dict_admin，且非本人）——"
                "请先在「用户管理」授权，再提交审校。"
            )
            reviewer = None
        else:
            reviewer = st.selectbox(
                "选择审校人（回避制：已滤掉本人，数据层再硬校验）",
                options=reviewers,
                format_func=lambda o: o["label"],
                key="writing_reviewer",
            )
        if st.button("提交初审（draft → in_review）", key="writing_submit_review"):
            if not content.strip():
                st.warning("释义成文为空，无法提交。")
            elif target["mode"] != "update":
                st.warning("当前没有可提交的在途草稿：请先「保存草稿」，再提交初审。")
            elif latest is not None and content != str(latest.get("content") or ""):
                st.warning("成文有未保存的修改：请先「保存草稿」，再提交初审。")
            elif reviewer is None:
                st.warning("请先选择审校人（回避制：不能选自己）。")
            else:
                ok = writing_db.submit_for_review(
                    int(target["target_id"]), int(reviewer["id"])
                )
                if ok:
                    st.success(
                        "已提交初审（draft → in_review）：任务已派给所选审校人，"
                        "可在「📚 版本历史」跟踪状态。"
                    )
                else:
                    st.error(
                        "提交失败：草稿状态已变化，或回避制拦截（审校人=撰写人）——"
                        "请刷新后重试。"
                    )


def _render_review_tab(me: Dict[str, Any]) -> None:
    """⚖️ 审校台：待审列表 → 内容＋ai_draft 对照 → 意见线 → 打回/通过；
    词典管理员末尾另见「👑 终裁」子视图（_render_adjudication_view）。"""
    if not _can_review(me):
        st.warning(
            "⛔ 审校台仅审校人可用（reviewer / dict_admin；过渡期 admin 兼判）。"
            "如需权限请联系词典管理员授予。"
        )
        return
    scope_all = False
    if "dict_admin" in users_db.effective_six_roles(me):
        scope_all = st.checkbox(
            "查看全部待审（词典管理员总览口径；裁决仍仅受派审校人可执行）",
            value=False, key="writing_review_all",
        )
    rows = writing_db.list_pending_reviews(None if scope_all else me.get("id"))
    if not rows:
        st.info(
            "暂无待你审校的任务：撰写台提交初审后出现在这里（「待我审校」"
            "收件箱口径）。"
        )
    else:
        _render_pending_review_rows(me, rows)
    # 批次 8 G6：词典管理员终裁子视图（例外通道收口；reviewer 单角色不可见）
    if _can_adjudicate(me):
        _render_adjudication_view(me)


def _render_pending_review_rows(me: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    """待审任务列表渲染（审校台主体；裁决仅受派审校人，意见线非作者可挂）。"""
    st.caption(
        f"共 {len(rows)} 条待审。裁决动作（⛔ 打回 / ✅ 通过）仅受派审校人可执行；"
        "意见线任何非作者审校人可挂；回避制（审校人≠撰写人）在数据层硬校验、"
        "无豁免。"
    )
    names = _user_display_map()
    for row in rows:
        author = names.get(_safe_int(row.get("author_id")),
                           f"#{row.get('author_id')}")
        label = (
            f"#{row['task_id']} · {row['sense_ref']} v{row['version']} · "
            f"第 {row['round']} 轮 · 作者：{author}"
        )
        with st.expander(label):
            assigned = _safe_int(row.get("reviewer_id")) == _safe_int(me.get("id"))
            if not assigned:
                st.warning(
                    "该任务受派给其他审校人：你只能挂意见，裁决按钮会被数据层拒绝。"
                )
            st.markdown(f"**释义内容（v{row['version']}）**")
            st.markdown(str(row.get("content") or ""))
            st.caption(
                f"状态：{STATUS_LABELS.get(str(row.get('status')), '—')} · "
                f"基于：v{row.get('based_on_version') or '—'} · "
                f"体例版本：{row.get('style_version') or '—'} · "
                f"提交说明：{row.get('note') or '—'}"
            )
            with st.expander("🤖 AI/模板草稿对照"):
                payload = row.get("ai_draft")
                if payload:
                    st.json(payload)
                else:
                    st.caption("本版无 AI/模板草稿快照（纯人工撰写）。")
            comments = writing_db.list_comments(int(row["version_id"]))
            st.markdown(f"**💬 意见线（{len(comments)} 条）**")
            if comments:
                for c in comments:
                    who = names.get(_safe_int(c.get("reviewer_id")),
                                    f"#{c.get('reviewer_id')}")
                    flag = "✅ 已处理" if c.get("resolved") else "🔔 未处理"
                    st.markdown(
                        f"- {flag} · {who} · {_format_dt(c.get('created_at'))}："
                        f"{c.get('body')}"
                    )
            else:
                st.caption("暂无意见。")
            new_comment = st.text_area(
                "挂意见（逐条留痕）",
                key=f"writing_comment_{row['task_id']}", height=80,
            )
            if st.button("💬 挂意见", key=f"writing_add_comment_{row['task_id']}"):
                if not new_comment.strip():
                    st.warning("意见内容为空。")
                else:
                    cid = writing_db.add_comment(
                        int(row["version_id"]), me.get("id"), new_comment
                    )
                    if cid:
                        st.success(f"意见已挂上（#{cid}）：请在修订后由作者/审校收口。")
                    else:
                        st.error(
                            "挂意见失败：回避制拦截（不得在自己撰写的版本上留言）"
                            "或参数异常。"
                        )
            note = st.text_area(
                "裁决意见（打回理由 / 通过留言）",
                key=f"writing_note_{row['task_id']}", height=80,
            )
            col_reject, col_approve = st.columns(2)
            with col_reject:
                if st.button("⛔ 要求修订（打回）",
                             key=f"writing_revise_{row['task_id']}"):
                    if not assigned:
                        st.error("你不是该任务的受派审校人，无法裁决。")
                    elif not note.strip():
                        st.warning("打回须给理由：请在裁决意见里写明修订要求。")
                    elif writing_db.request_revision(
                        int(row["version_id"]), me.get("id"), note
                    ):
                        st.success(
                            "已打回（in_review → rejected）：作者可在撰写台重提 "
                            "version+1（自动挂 based_on_version，版本链不断）。"
                        )
                    else:
                        st.error("打回失败：任务已被处理或状态已变化，请刷新。")
            with col_approve:
                if st.button("✅ 通过（终审即 final）",
                             key=f"writing_approve_{row['task_id']}"):
                    if not assigned:
                        st.error("你不是该任务的受派审校人，无法裁决。")
                    elif writing_db.approve(
                        int(row["version_id"]), me.get("id"), note or None
                    ):
                        st.success(
                            "已通过（in_review → final）：普通词条 reviewer 终审即"
                            "定稿；争议词条走下方「👑 词典管理员终裁」子视图。"
                        )
                    else:
                        st.error("通过失败：任务已被处理或状态已变化，请刷新。")


def _render_adjudication_view(me: Dict[str, Any]) -> None:
    """👑 词典管理员终裁子视图（批次 8 G6；两级终审的例外通道收口）。

    口径（架构规范 §8 / 施工规范 §12）：全部 in_review / approved 版本逐条
    expander —— 「👑 终裁通过」走 writing_db.adjudicate_final(decision=
    approved)，in_review/approved → final 直达（终裁通过 = final 直达，两级
    终审收口）；「⛔ 终裁否决」decision=rejected，仅 in_review → rejected，
    否决理由必填（页面侧强制）。adjudicate_final 返回 False（状态已变/权限/
    回避制拦截）转 st.warning 如实转述，不静默。数据层再校验 actor 有效角色
    （effective_six_roles 同源）与回避制（终裁人≠作者，无豁免）—— 本视图只
    是第一层入口。
    """
    in_review = writing_db.list_versions(status=writing_db.STATUS_IN_REVIEW)
    approved = writing_db.list_versions(status=writing_db.STATUS_APPROVED)
    rows = in_review + approved
    st.markdown(f"<h4 style='{HEADER_H3}'>👑 词典管理员终裁（两级终审收口）</h4>",
                unsafe_allow_html=True)
    if not rows:
        st.caption(
            "当前无 in_review / approved 态版本可终裁（普通词条 reviewer 审校"
            "通过即 final，终裁是争议词条的例外通道而非必经站）。"
        )
        return
    st.caption(
        f"共 {len(rows)} 条（审校中 {len(in_review)} / 终审通过 {len(approved)}）。"
        "终裁通过 = final 直达；终裁否决 → rejected（理由必填）。终裁人与撰写人"
        "回避制在数据层硬校验（无豁免，含词典管理员）。"
    )
    names = _user_display_map()
    for row in rows:
        author = names.get(_safe_int(row.get("author_id")),
                           f"#{row.get('author_id')}")
        status = STATUS_LABELS.get(str(row.get("status")), str(row.get("status")))
        with st.expander(
            f"{row.get('sense_ref')} v{row.get('version')} · {status} · "
            f"作者：{author}"
        ):
            st.markdown(str(row.get("content") or ""))
            st.caption(
                f"状态：{status} · 基于：v{row.get('based_on_version') or '—'} · "
                f"体例版本：{row.get('style_version') or '—'} · 行 id：{row.get('id')}"
            )
            note = st.text_area(
                "终裁意见（否决理由必填 / 通过留言可选）",
                key=f"writing_final_note_{row['id']}", height=80,
            )
            col_ok, col_no = st.columns(2)
            with col_ok:
                if st.button("👑 终裁通过（→ final）",
                             key=f"writing_final_ok_{row['id']}"):
                    if writing_db.adjudicate_final(
                        int(row["id"]), me.get("id"), "approved", note or "",
                        actor=me,
                    ):
                        st.success(
                            "终裁通过（→ final）：两级终审收口，该版本已定稿；"
                            "发布由词典管理员走出版链路（G6 闸门）。"
                        )
                    else:
                        st.warning(
                            "终裁未生效：版本状态已变化、你不是词典管理员（会话"
                            "快照滞后）或回避制拦截（终裁人=撰写人）——请刷新后"
                            "重试。"
                        )
            with col_no:
                if st.button("⛔ 终裁否决（→ rejected）",
                             key=f"writing_final_no_{row['id']}"):
                    if not note.strip():
                        st.warning("终裁否决须给理由：请在终裁意见里写明否决依据"
                                   "（理由随任务行留痕）。")
                    elif writing_db.adjudicate_final(
                        int(row["id"]), me.get("id"), "rejected", note, actor=me,
                    ):
                        st.success(
                            "终裁否决（in_review → rejected）：作者可在撰写台"
                            "重提 version+1（自动挂 based_on_version）。"
                        )
                    else:
                        st.warning(
                            "终裁未生效：版本状态已变化、你不是词典管理员或"
                            "回避制拦截 —— 请刷新后重试。"
                        )


def _render_history_tab(me: Dict[str, Any]) -> None:
    """📚 版本历史：版本链表 ＋ 逐版成文 / AI 快照 / 意见线（全角色可读）。

    **R1-10 脱敏口径（施工规范 §14 批次 12）**：viewer/annotator 视角
    （_history_realname=False）作者/意见人折算「编纂员 A/B」（按出现序
    稳定编号，_pseudonym_factory），draft 态内容与字数列显示
    「🔒 撰写中」（在途草稿不外露）；reviewer/dict_admin（含 editor——
    编纂圈署名权）实名全链不变。收口（标记意见已处理）仍按原角色口径。
    """
    st.caption(
        "版本链按 sense_ref 升序：每版记作者 / based_on_version / 体例版本 —— "
        "三版本脊柱第三条（谁标的 → α → 簇 → 模板 → 释义版本）。"
    )
    categories = _list_categories_dicts()
    if not categories:
        st.info("范畴清单不可用：数据库未灌语义分析数据（cs_* 表）或库不可用。")
        return
    cat_options = [c["code"] for c in categories]
    cat_code = st.selectbox(
        "范畴",
        options=cat_options,
        format_func=lambda code: next(
            (f"{c['code']} {c['name_cn']}" for c in categories if c["code"] == code),
            code,
        ),
        key="writing_history_category",
    )
    language = st.radio(
        "语言",
        options=["en", "zh"],
        horizontal=True,
        format_func={"en": "英语（OALD10）", "zh": "汉语（现汉7）"}.get,
        key="writing_history_language",
    )
    senses = _list_candidate_senses(cat_code, language)
    if not senses:
        st.info("该范畴/语言暂无义位（与撰写台同源，merged 禁选）。")
        return
    sense = st.selectbox(
        "选择义位", options=senses, format_func=_sense_option_label,
        key="writing_history_sense",
    )
    cs_id = _safe_int(sense.get("cs_sense_id")) or 0
    oald_id = _resolve_oald_sense_id(sense.get("lemma"), sense.get("sense_no"))
    ref = _build_sense_ref(str(sense.get("category_code") or ""), cs_id, oald_id)
    if ref is None:
        st.error("义位锚拼装失败（数据异常）。")
        return
    st.caption(f"版本锚 sense_ref = {ref}")
    versions = writing_db.list_versions(ref)
    if not versions:
        st.info("该义位还没有任何释义版本：去「✍️ 撰写台」开第一版。")
        return

    realname = _history_realname(me)
    names = _user_display_map()
    who, alias_map = _pseudonym_factory()

    def _who(uid_any: Any) -> str:
        """实名 → 显示名；折算 → 「编纂员 A/B」（按出现序稳定编号）。"""
        if realname:
            return names.get(_safe_int(uid_any), f"#{uid_any}")
        return who(uid_any)

    table_rows = []
    for v in versions:
        is_hidden_draft = (
            not realname and str(v.get("status") or "") == "draft"
        )
        table_rows.append({
            "版本": f"v{v.get('version')}",
            "状态": STATUS_LABELS.get(str(v.get("status")), str(v.get("status"))),
            "作者": _who(v.get("author_id")),
            "基于": f"v{v.get('based_on_version')}" if v.get("based_on_version") else "—",
            "体例版本": str(v.get("style_version") or "—"),
            "字数": _DRAFT_HIDDEN_TEXT if is_hidden_draft else len(str(v.get("content") or "")),
            "创建时间": _format_dt(v.get("created_at")),
            "更新时间": _format_dt(v.get("updated_at")),
        })
    st.dataframe(table_rows, hide_index=True, use_container_width=True)

    st.markdown("#### 版本链详情")
    can_resolve_base = _can_review(me)
    my_id = _safe_int(me.get("id"))
    for v in versions:
        status = STATUS_LABELS.get(str(v.get("status")), str(v.get("status")))
        base = f"v{v.get('based_on_version')}" if v.get("based_on_version") else "—"
        with st.expander(
            f"v{v.get('version')} · {status} · 作者：{_who(v.get('author_id'))} · 基于：{base}"
        ):
            is_hidden_draft = (
                not realname and str(v.get("status") or "") == "draft"
            )
            if is_hidden_draft:
                st.markdown(_DRAFT_HIDDEN_TEXT)
            else:
                st.markdown(str(v.get("content") or ""))
            ai = v.get("ai_draft")
            if ai:
                with st.expander("🤖 AI/模板草稿快照"):
                    st.json(ai)
            comments = writing_db.list_comments(int(v["id"]))
            if comments:
                st.markdown(f"**💬 意见线（{len(comments)} 条）**")
                for c in comments:
                    flag = "✅ 已处理" if c.get("resolved") else "🔔 未处理"
                    st.markdown(
                        f"- {flag} · {_who(c.get('reviewer_id'))} · "
                        f"{_format_dt(c.get('created_at'))}："
                        f"{c.get('body')}"
                    )
                open_comments = [c for c in comments if not c.get("resolved")]
                if open_comments and (can_resolve_base or my_id == _safe_int(v.get("author_id"))):
                    if st.button(
                        f"✔️ 标记全部意见已处理（{len(open_comments)} 条）",
                        key=f"writing_resolve_{v['id']}",
                    ):
                        done = sum(
                            1 for c in open_comments
                            if writing_db.resolve_comment(int(c["id"]), True)
                        )
                        st.success(f"已标记 {done} 条意见为已处理（收口只标记，不删行）。")
            else:
                st.caption("暂无意见。")
    if not realname:
        st.caption("🔒 视角提示：你的角色（viewer/annotator）对作者/意见人做匿名化"
                   "折算（编纂员 A/B），草稿内容不外露 —— 实名链仅编纂与审校侧可见。")


# ============================================
# 区级页面入口
# ============================================

def render_writing_page() -> None:
    """✍️ 释义撰写与审校区入口（区级页面；三 tab，集成步骤挂进 app.py）。

    登录门在函数入口：未登录提示并 return（页面内容含各 tab 取数一概不
    执行）；撰写/审校的角色门在各 tab 内（版本历史全角色可读 —— 编纂产出
    区为全角色可见区，动作按角色收口）。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录后再访问释义撰写与审校工作台。")
        return

    # 页面自举：编纂成文域三表幂等就位（CREATE TABLE IF NOT EXISTS，
    # 开销可忽略；users 表由登录链路 ensure_user_tables 先行）
    writing_db.ensure_writing_tables()

    st.markdown(f"<h1 style='{HEADER_H1}'>✍️ 释义撰写与审校</h1>",
                unsafe_allow_html=True)
    st.markdown(
        f"<h2 style='{HEADER_H2}'>编纂成文域工作台（阶段 2 第一批）</h2>",
        unsafe_allow_html=True,
    )
    st.caption(
        "簇承包撰写（locked 簇优先 · G3 消费）· 模板预览对照（确定性引擎）· "
        "版本留痕（乐观锁 · based_on_version）· 审校（回避制 · 两级终审 MVP）· "
        "意见线 · 定稿发布（dict_admin，G6 硬闸门批次 8 接管）。"
    )

    tab_write, tab_review, tab_history = st.tabs(
        ["✍️ 撰写台", "⚖️ 审校台", "📚 版本历史"],
    )
    with tab_write:
        _render_write_tab(me)
    with tab_review:
        _render_review_tab(me)
    with tab_history:
        _render_history_tab(me)
