"""编纂成文域页面 —— 「📖 例证与对译」（工序 11 例证配置 ＋ 工序 12 对译定稿）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§3 工序 11/12、§6 D④ 编纂
成文域、§9 编纂产出区；契约：docs/spec/阶段1施工规范.md §10 批次 7-V；
页面行为以 docs/help/平台功能使用说明.md「4.3 例证配置 / 4.4 对译定稿」为准。

是什么（区级页面，页内两 tab；批次 7 集成步骤挂载：render_lexical_page()
注册进 app.py 分派 ＋ GUIDE 原样并入 PAGE_GUIDES；本模块不修改 app.py /
page_guides.py）：

  🗂️ 例证配置    选义位（cs_senses 锚，merged 禁选）→ 例证列表（审定态
                徽章）→ 新增（来源 corpus/adapted/composed 即改写标记）→
                单步审定流转（候选→审定→发布，乐观守卫）→ 编辑/删除
                （物理 DELETE，例证可重建非词典正文）→ 媒体例证绑定
                入口（委托 lexical_db.bind_example_media → media_db）；
  🌐 对译定稿    选义位 → 三态单选（full 完全对应 / partial 部分对应
                ＋括注 / none 无对应→释义翻译）→ 分支表单 → 定稿
                （finalized_by/finalized_at 落库）→ 已有定稿展示 ＋
                辨析栏草稿 note（近义簇英汉辨析栏的起草字段）。

角色门（纵深防御，规范 §6-4）：纯函数 _can_edit(user) 复用
users_db.effective_six_roles 单一实现——有效六角色含 editor/reviewer/
dict_admin 放行（编纂职能：例证/对译按任务×角色矩阵 editor+，审校侧
reviewer 需要读改口径），过渡期 role=='admin' 由 effective 映射
（admin→dict_admin+sys_admin）兼判；非 dict 会话 fail-closed。
本模块不 import app.py，不做实时查库兜底（编纂成文域非敏感写路径，
角色门一层＋数据层参数化即可；闸门先例见 src/guards.py）。

数据链：全部取数/写库走 src/lexical_db.py（批次 7 数据层，只读调用
不复制业务规则）；义位选项是页面层私有参数化查询辅助（cs_senses ×
cs_lexemes 联查，docstring 注明），merged 拒选口径见 _sense_selectable
（与 cluster_analysis.MERGED_STATUS / sense_spine「已并入」文案同口径）。

输出安全：所有进 unsafe_allow_html 的用户生成内容/库内文本一律先过
_esc（html.escape 含引号）；selectbox/radio 等纯文本控件由 Streamlit
自带转义。widget key 统一前缀 lex_。
"""

import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src import media_db
from src import ui_kit  # RV12-2：成功提示统一走 ui_kit.flash（rerun 不再丢）
from src.db_utils import as_int as _as_int  # R6-4：公共小件单一实现点
from src.db_utils import current_user as _current_user
from src.design_system import (
    HEADER_H1,
    HEADER_H2,
    HEADER_H3,
    REVIEW_STATUS_COLORS,
    get_badge_html,
    get_card_style,
    get_table_header_style,
    get_table_row_style,
)
from src.lexical_db import (
    EXAMPLE_SOURCES,
    MAX_CONTENT_LEN,
    SOURCE_ADAPTED,
    SOURCE_COMPOSED,
    SOURCE_CORPUS,
    STATE_FULL,
    STATE_NONE,
    STATE_PARTIAL,
    TRANSLATION_STATES,
    add_example,
    advance_example_status,
    bind_example_media,
    ensure_lexical_tables,
    get_translation,
    list_examples,
    _next_example_status,  # R6-5：审定单步链单一实现（lexical_db 内部链）
    remove_example,
    set_translation,
    update_example,
)
from src.mysql_db import get_db_cursor
from src.users_db import effective_six_roles

logger = logging.getLogger(__name__)

# ============================================
# 页面使用说明（四段式；集成时原样并入 PAGE_GUIDES["lexical"]）
# ============================================

GUIDE: Dict[str, Any] = {
    "label": "📖 例证与对译",
    "purpose": (
        "编纂成文域的例证与对译半区（工序 11/12）：例证配置为义位配文字例证"
        "（语料草选/人工改写/自拟三来源）与媒体例证（图/视频带图注与来源，"
        "绑定入口委托媒体库）；对译定稿按三态收口——完全对应（对应词）/部分"
        "对应（对应词＋括注）/无对应（释义翻译），并起草辨析栏（note）。"
        "产出供阶段 2 词条装配渲染例证区与对译区。"
    ),
    "principle": [
        "义位锚与 merged 禁选：编纂成文域一律以 cs_senses.id 为义位锚"
        "（sense_ref 软引用）；分立复核定稿已并入他义位的义位（status='merged'，"
        "去向记 merged_into）在下拉中禁选并标注「已并入 → #目标」——并入后的"
        "义位不再独立配置例证/对译，内容随目标义位走（G3 语义）。",
        "例证三来源即改写标记：corpus 语料草选（装配侧标「语料例」）、adapted "
        "人工改写（装配侧标「改写例」）、composed 自拟（装配侧标「自拟例」）"
        "——来源随行入库，出版侧（G6 许可检查）据此区分"
        "「自产/改写」与版权原文；例证审定三态与媒体资产同链（候选→审定→发布），"
        "单步流转、不可跳级、不可回退，乐观并发守卫两人同流只有一人生效。",
        "例证可重建非词典正文：例证是可反复增删的配置项，remove_example 为"
        "物理 DELETE（义项权威数据仍守 D 域「版本化、不删行」纪律）；删除时"
        "自动摘除该例证的全部媒体绑定（media_db.unbind_for_anchor），孤儿"
        "绑定无需再手工清理。",
        "对译三态定稿（工序 12）：full 完全对应只填对应词；partial 部分对应"
        "填对应词＋括注（括注兼辨析栏草稿起点）；none 无对应填释义翻译"
        "（paraphrase）。定稿即覆盖写（一义位一行），finalized_by/finalized_at "
        "每次定稿刷新，改口径即重新定稿；历史留痕归审校台账（批次 8）。",
        "媒体例证只做绑定入口：资产登记（license 必填）与审定在「📖 词典管理 · "
        "🖼️ 媒体库」，本页把已登记资产绑到例证锚（anchor_type='example'、"
        "purpose='example_media'，委托 media_db.bind_asset，UNIQUE 幂等）；"
        "词条装配只取发布态绑定。",
        "角色门纵深防御：登录门＋_can_edit 纯函数（有效六角色含 editor/"
        "reviewer/dict_admin；过渡期 admin 兼判）一层把关，数据层参数化 "
        "SQL 兜底；merged 拒选在数据选择与写入前双重判定（fail-closed）。",
    ],
    "data_source": [
        "src/lexical_db.py：sense_examples / sense_translations 两表（add_example "
        "/ list_examples / update_example / remove_example / advance_example_status "
        "/ bind_example_media / set_translation / get_translation）——参数非法与"
        "库不可用以 0/False/[]/None 返回，页面转 st.error/st.info 展示。",
        "src/lexical_db.py（委托 media_db.bind_asset）：媒体例证绑定入口——"
        "资产登记/审定留在词典管理区媒体库，本页只绑 example 锚并回写 "
        "media_asset_id 供例证列表直读。",
        "src/media_db.py（只读）：list_assets_for_anchor('example', id) 展示"
        "例证上已绑定的资产（含绑定态），本页不做资产登记。",
        "cs_senses × cs_lexemes（页面层只读参数化查询 _list_sense_options）："
        "义位下拉选项——lemma/义项号/义位标签 ＋ status/merged_into 现状；"
        "cs_senses 表属范畴研究域（category_study 建表），此处只读不写。",
        "src/users_db.py：effective_six_roles（_can_edit 的单一实现来源，"
        "会话快照折算，不查库）。",
    ],
    "steps": [
        "进入「📖 例证与对译」先在「🗂️ 例证配置」选义位：下拉只列可选义位"
        "（已并入义位在下方「已并入（禁选）」清单标注「已并入 → #目标」并禁选）；"
        "列表按展示顺序给出该义位全部例证（#id、内容、来源、说明/出处、审定态"
        "徽章、媒体列）。",
        "「➕ 新增例证」填例证文本（必填）、选来源（语料例/改写例/自拟例——"
        "改写与自拟即改写标记）、给说明/出处与展示顺序后提交；新例证以「候选」"
        "态起步。",
        "「✏️ 编辑 / 审定流转 / 删除」选中一条例证：改文本/来源/顺序保存；"
        "「审定流转」按单步链推进（候选→审定→发布，发布为终态）——被他人先行"
        "流转或库不可用时页面转述失败原因；「物理删除」为不可恢复操作（例证"
        "可重建非词典正文），删除时自动摘除其全部媒体绑定。",
        "「🖼️ 媒体例证绑定」选例证＋填资产 id（media_assets.id，资产先在"
        "词典管理区媒体库登记）＋图注/来源说明后绑定；绑定经 media_db 落 "
        "media_bindings（example 锚，UNIQUE 幂等），例证列表媒体列随之显示"
        "资产号。",
        "切「🌐 对译定稿」选义位（merged 同样禁选）：先看「已有定稿」展示"
        "（三态徽章、对应词、括注/辨析栏草稿、释义翻译、定稿人/时间）；再按"
        "三态单选分支填表——完全对应填对应词；部分对应填对应词＋括注（必填）；"
        "无对应填释义翻译（必填）；辨析栏草稿（note）三态皆可起草。",
        "点「定稿」完成三态落库（缺对应词/括注/释义翻译在表单侧拦截）："
        "一义位一稿、覆盖写，定稿人与定稿时间刷新；改口径即重新定稿，"
        "装配侧按三态渲染对应词/括注/释义翻译。",
    ],
    "notes": [
        "权限口径：登录后按编纂职能放行（editor/reviewer/dict_admin；过渡期 "
        "admin 兼判）；viewer/annotator 只能访问查阅展示区与语义分析区，"
        "本页入口即拦截。",
        "merged 禁选文案与义项脊柱同口径：有去向显示「已并入 → #N」，去向"
        "缺失显示「已并入（merged_into 去向待补录）」——不猜去向 id。",
        "例证审定态是编纂质量线（候选→审定→发布）：装配侧按发布态渲染，"
        "候选/审定仅留痕可见；媒体绑定态仍按媒体库口径独立流转，本页不做"
        "媒体审定。",
        "对译 note 是「括注位兼辨析栏草稿」：partial 态为括注必填位，full/none "
        "态为辨析栏草稿可选位——近义簇英汉辨析栏（装配侧）以 note 为起草源。",
        "所有义位标签/例证文本/图注/对应词等用户生成内容渲染进 HTML 前一律"
        "转义；下拉与单选的选项文本由 Streamlit 自带转义。",
        "义位下拉来自 cs_senses 现状（含 merged/split 落地值）；范畴研究域表"
        "未建或库不可用时页面优雅降级（提示暂无可选义位，不编数据）。",
    ],
}

# ============================================
# 展示常量（徽章配色与枚举中文名；存库一律英文枚举值）
# ============================================

# 例证来源中文名（lexical_db.EXAMPLE_SOURCES 的展示映射）。
SOURCE_LABELS = {
    SOURCE_CORPUS: "语料例",
    SOURCE_ADAPTED: "改写例",
    SOURCE_COMPOSED: "自拟例",
}

# 对译三态中文名（lexical_db.TRANSLATION_STATES 的展示映射）。
STATE_LABELS = {
    STATE_FULL: "完全对应",
    STATE_PARTIAL: "部分对应",
    STATE_NONE: "无对应（释义翻译）",
}

# 审定态徽章配色（与媒体库同链同语义：候选灰/审定蓝/发布绿）。
# R6-5：配色单份事实源进 design_system.REVIEW_STATUS_COLORS（媒体库绑定
# 徽章同源），本名字保留为别名供既有调用点/测试使用。
STATUS_BADGE_COLORS = REVIEW_STATUS_COLORS

# 对译三态徽章配色（完全对应绿/部分对应橙/无对应灰）。
# RV1-2：白字对比全 ≥4.5:1 —— 旧 STATE_NONE #718096 白字 4.02:1 不达，
# 深档换 #4a5568（7.53:1）。
STATE_BADGE_COLORS = {
    STATE_FULL: "#2f855a",
    STATE_PARTIAL: "#c05621",
    STATE_NONE: "#4a5568",
}

# 已并入徽章配色（拒绝/错误红，与 design_system.ERROR_COLOR 同值；
# RV1-2：#e53e3e 白字 4.13:1 不达 AA，取深档 #c53030 5.47:1）。
MERGED_BADGE_COLOR = "#c53030"

# merged 拒选口径：cs_senses.status 分立落地取值（与
# cluster_analysis.MERGED_STATUS 同值；本地常量避免拖入 numpy/scipy 依赖）。
MERGED_STATUS = "merged"

# 编纂职能允许角色（任务×角色矩阵：撰写/例证/对译→editor+；审校侧 reviewer
# 需要读改口径，词典管理员兜底；判定实现复用 effective_six_roles）。
CAN_EDIT_ROLES = frozenset({"editor", "reviewer", "dict_admin"})


# ============================================
# 纯函数（转义 / 角色门 / merged 拒选 / 表单校验）
# ============================================

def _esc(value: Any) -> str:
    """任意值 → HTML 安全文本（str() 后 html.escape 含引号）。

    所有进 unsafe_allow_html 的用户生成内容/库内文本必须先过这里；
    selectbox/radio 等纯文本控件由 Streamlit 自带转义，调用方不要再转。
    """
    return _html_escape(str(value), quote=True)


def _can_edit(user: Any) -> bool:
    """会话用户 dict 是否放行编纂成文域（纯函数，fail-closed）。

    判定单一实现复用 users_db.effective_six_roles（不 import app）：
    有效六角色集（legacy role 映射 ∪ session roles 快照，非法角色名忽略）
    与编纂职能角色集（editor/reviewer/dict_admin）有交集即放行：
      * role == 'admin' 过渡期兼判——effective 映射 admin→{dict_admin,
        sys_admin}（内置 admin 的 users_db 幂等迁移口径），自然命中；
      * 非 dict 会话 / 角色集为空 → 不放行（fail-closed）。
    实时查库兜底不在本函数（编纂成文域非敏感写路径，数据层参数化兜底）。
    """
    if not isinstance(user, dict):
        return False
    return bool(effective_six_roles(user) & CAN_EDIT_ROLES)


def _merged_annotation(status: Any, merged_into: Any) -> Optional[str]:
    """cs_senses 现状 → merged 去向文案核（纯函数，可测）。

    status='merged'（大小写/空白容错）→「已并入 → #N」；merged_into 缺失
    「已并入（merged_into 去向待补录）」——不猜去向 id（与 sense_spine
    「已并入」文案同口径）。非 merged → None。
    """
    if str(status or "").strip().lower() != MERGED_STATUS:
        return None
    target = _as_int(merged_into)
    if target is not None and target > 0:
        return f"已并入 → #{target}"
    return "已并入（merged_into 去向待补录）"


def _sense_selectable(status: Any) -> Tuple[bool, str]:
    """义位可否选入编纂成文（merged 拒选口径，纯函数）。

    Returns:
        (True, "") 可选；(False, 理由) 禁选——merged 义位（分立复核定稿
        已并入他义位）不再独立配置例证/对译，内容随目标义位走（G3 语义）。
        其余 status（保留/边缘/剔除/目标/split）不拦（准入语义归工序 4）。
    """
    if str(status or "").strip().lower() == MERGED_STATUS:
        return (False, "该义位已并入目标义位（分立复核定稿），禁选——请改选"
                       "目标义位配置例证与对译。")
    return (True, "")


def _sense_label(row: Dict[str, Any]) -> str:
    """义位行 → 下拉展示标签（含 #id 防重；merged 行附「已并入」去向）。"""
    sid = _as_int(row.get("id")) or 0
    lemma = str(row.get("lemma") or "")
    no = str(row.get("sense_no") or "").strip()
    label = str(row.get("sense_label") or "")
    lang = str(row.get("language") or "")
    head = lemma + (f"·{no}" if no else "")
    base = f"{head}｜{label}（{lang}）#{sid}"
    ann = _merged_annotation(row.get("status"), row.get("merged_into"))
    return f"{base}｜{ann}" if ann else base


def _sense_options(
    senses: List[Dict[str, Any]],
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """义位清单 → (可选映射 {label: id}, 被拒选清单)。

    merged 义位不进下拉映射（禁选），以 excluded 返回供页面「已并入（禁选）」
    清单标注；标签含 #id 恒唯一，可安全作 selectbox options。
    """
    options: Dict[str, int] = {}
    excluded: List[Dict[str, Any]] = []
    for row in senses:
        ok, _ = _sense_selectable(row.get("status"))
        if ok:
            sid = _as_int(row.get("id"))
            if sid is not None and sid > 0:
                options[_sense_label(row)] = sid
        else:
            excluded.append(row)
    return options, excluded


def _translation_missing(
    state: Any, equivalent: Any, note: Any, paraphrase: Any,
) -> Optional[str]:
    """对译定稿分支校验（纯函数）：缺必填项返回错误文案，齐备返回 None。

    口径（工序 12 三态）：full/partial 必须给出对应词；partial 还必须给
    括注（note）；none 必须给出释义翻译（paraphrase）。state 非法直接拒绝
    （三态单选不会被绕过）。
    """
    if state not in TRANSLATION_STATES:
        return f"未选择合法的对译三态（{state!r}），请先单选 full/partial/none。"
    eq = str(equivalent or "").strip()
    nt = str(note or "").strip()
    pp = str(paraphrase or "").strip() if paraphrase is not None else ""
    if state in (STATE_FULL, STATE_PARTIAL) and not eq:
        return "完全/部分对应必须给出对应词。"
    if state == STATE_PARTIAL and not nt:
        return "部分对应必须给出括注（对应词的含义边界说明）。"
    if state == STATE_NONE and not pp:
        return "无对应必须给出释义翻译。"
    return None


# ============================================
# 渲染小件（徽章 / 表格 / 选项映射，仿 dict_admin_pages 同一视觉语言）
# ============================================

def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span）。text 由调用方保证已过 _esc。

    RV1-2（_badge 收敛）：实现单份进 design_system.get_badge_html ——
    文字颜色按底色自动选深/浅（旧版写死白字，浅底不达 WCAG AA）；
    转义契约不变。
    """
    return get_badge_html(text, color)


def _render_table(headers: List[str], rows: List[List[str]]) -> None:
    """只读 HTML 表格。单元格为调用方拼好的安全 HTML（文本已过 _esc）。"""
    header_cells = "".join(
        f"<th style='{get_table_header_style()}'>{h}</th>" for h in headers
    )
    cell_style = f"{get_table_row_style()}padding:8px;"
    row_htmls = [
        "<tr>" + "".join(f"<td style='{cell_style}'>{cell}</td>" for cell in row)
        + "</tr>"
        for row in rows
    ]
    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<tr>{header_cells}</tr>{''.join(row_htmls)}</table>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _example_options(examples: List[Dict[str, Any]]) -> Dict[str, int]:
    """例证行 → {label: id}（label 含 #id 恒唯一；内容截断换行压平）。"""
    options: Dict[str, int] = {}
    for ex in examples:
        eid = _as_int(ex.get("id")) or 0
        if eid <= 0:
            continue
        content = str(ex.get("content") or "").replace("\n", " ").strip()
        short = content[:30] + ("…" if len(content) > 30 else "")
        status = str(ex.get("status") or "")
        options[f"#{eid} {short}（{status}）"] = eid
    return options


def _render_examples_table(examples: List[Dict[str, Any]]) -> None:
    """例证列表（只读表）：审定态徽章＋媒体列；文本一律 _esc。"""
    headers = ["#", "例证", "来源", "说明/出处", "状态", "媒体"]
    rows: List[List[str]] = []
    for ex in examples:
        eid = _as_int(ex.get("id")) or 0
        status = str(ex.get("status") or "")
        media = (
            f"#{_as_int(ex.get('media_asset_id'))}"
            if ex.get("media_asset_id") is not None
            else "—"
        )
        caption = str(ex.get("caption") or "")
        rows.append([
            str(eid),
            _esc(str(ex.get("content") or "")),
            _esc(SOURCE_LABELS.get(str(ex.get("source") or ""),
                                   str(ex.get("source") or ""))),
            _esc(caption) if caption else "—",
            _badge(_esc(status), STATUS_BADGE_COLORS.get(status, "#4a5568")),
            _esc(media),
        ])
    _render_table(headers, rows)


def _render_merged_excluded(excluded: List[Dict[str, Any]]) -> None:
    """已并入义位清单（禁选标注；文案与义项脊柱同口径）。"""
    if not excluded:
        return
    with st.expander(f"已并入义位（禁选，{len(excluded)}）", expanded=False):
        st.caption("分立复核定稿已并入目标义位的义位不再独立配置例证/对译；"
                   "内容随目标义位走（G3 语义）。")
        for row in excluded:
            ann = _merged_annotation(row.get("status"), row.get("merged_into"))
            note = ann or "已并入"
            st.markdown(
                f"{_badge(_esc(note), MERGED_BADGE_COLOR)} {_esc(_sense_label(row))}",
                unsafe_allow_html=True,
            )


# ============================================
# 页面层只读取数辅助（参数化；cs_senses 现状不复制到本域）
# ============================================

def _list_sense_options() -> List[Dict[str, Any]]:
    """义位下拉选项取数（**只读**）：cs_senses × cs_lexemes 联查。

    编纂成文域以 cs_senses.id 为义位锚（sense_ref），本查询只读、不写范畴
    研究域；返回行含 status/merged_into 现状（分立复核落地值 merged/split）
    ——merged 义位由 _sense_selectable 拒选、_sense_options 排除出下拉。

    R5-8：**不带 LIMIT，全量拉取**。曾硬编码 ``LIMIT 1000`` 且不校验条数
    ——义位规模逼近上限（当前 996 行）后，split 增量溢出的义项会无声消失
    （下拉静默缺项，用户无从察觉）。当前规模（~10³ 行 × 7 列）全量拉取
    开销可忽略，静默截断风险归零；若未来规模增长到需要分页，必须改为
    显式截断提示（st.warning 报告总数与可见数），不得恢复无声 LIMIT。
    表未建 / 数据库不可用返回 []（页面优雅降级，不编数据）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.id, s.sense_no, s.sense_label, s.status, s.merged_into,
                          l.lemma, l.language
                   FROM cs_senses s
                   JOIN cs_lexemes l ON l.id = s.lexeme_id
                   ORDER BY l.lemma, l.language, s.id""",
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按空清单降级
        logger.warning(f"读取义位选项失败（按空清单处理）: {e}")
        return []


# ============================================
# Tab 1：🗂️ 例证配置
# ============================================

def _render_examples_tab(me: Dict[str, Any]) -> None:
    """例证配置 tab：选义位（merged 禁选）→ 列表 → 新增 → 流转/编辑/删除
    → 媒体绑定入口（全链走 lexical_db，失败 st.error 转述不抛异常）。"""
    senses = _list_sense_options()
    options, excluded = _sense_options(senses)
    _render_merged_excluded(excluded)
    if not options:
        st.info("暂无可选义位（cs_senses 未建表/无数据/数据库不可用）——"
                "例证配置需先在语义分析区完成义位甄别与分立复核。")
        return
    pick = st.selectbox("选择义位", list(options.keys()), key="lex_ex_sense_pick")
    sense_id = options.get(pick)
    sense_row = next((s for s in senses if _as_int(s.get("id")) == sense_id), None)
    ok, reason = _sense_selectable((sense_row or {}).get("status"))
    if not ok:
        # 禁选义位不进下拉；此处兜底防会话/清单漂移（fail-closed）
        st.error(reason)
        return
    sense_ref = str(sense_id)
    examples = list_examples(sense_ref)
    st.markdown(f"<h4 style='{HEADER_H3}'>📋 例证列表"
                f"（{len(examples)} 条）</h4>", unsafe_allow_html=True)
    if examples:
        _render_examples_table(examples)
    else:
        st.caption("该义位暂无例证，先在下方新增（新例证以「候选」态起步）。")

    with st.expander("➕ 新增例证", expanded=False):
        with st.form("lex_ex_add_form", clear_on_submit=True):
            content = st.text_area(
                f"例证文本（必填，≤{MAX_CONTENT_LEN} 字符）", key="lex_ex_add_content",
                height=100,
                help="语料草选/人工改写/自拟均可；来源即改写标记，出版侧按来源"
                     "区分「自产/改写」与版权原文（G6 许可检查口径）。正文上限 "
                     f"{MAX_CONTENT_LEN} 字符（应用层显式设防，超长拒收不落库）。",
            )
            source = st.selectbox(
                "来源 source", list(EXAMPLE_SOURCES),
                format_func=lambda s: SOURCE_LABELS.get(s, s),
                key="lex_ex_add_source",
            )
            caption = st.text_input(
                "说明/出处图注（可选，如语料库名/例句出处）",
                key="lex_ex_add_caption",
            )
            order = st.number_input(
                "展示顺序 sort_order（小在前）", value=0, step=1,
                key="lex_ex_add_order",
            )
            submitted = st.form_submit_button("新增例证", use_container_width=True)
        if submitted:
            eid = add_example(
                sense_ref, content, source=source, caption=caption,
                sort_order=int(order), created_by=_as_int(me.get("id")),
            )
            if eid:
                ui_kit.flash(f"已新增例证 #{eid}（状态=候选）。")
                st.rerun()
            else:
                st.error(f"新增失败：例证文本为空/超长（≤{MAX_CONTENT_LEN} 字符）/"
                         "参数非法/数据库不可用（lexical_db 已记日志）。")

    with st.expander("✏️ 编辑 / 审定流转 / 删除", expanded=False):
        ex_options = _example_options(examples)
        if not ex_options:
            st.caption("该义位暂无例证，先在上方新增。")
        else:
            edit_pick = st.selectbox(
                "选择例证", list(ex_options.keys()), key="lex_ex_edit_pick",
            )
            eid = ex_options.get(edit_pick)
            row = next(
                (e for e in examples if _as_int(e.get("id")) == eid), None,
            )
            if row is None or eid is None:
                st.warning("所选例证已被删除或列表已刷新，请重选。")
            else:
                with st.form("lex_ex_edit_form", clear_on_submit=False):
                    new_content = st.text_area(
                        f"例证文本（≤{MAX_CONTENT_LEN} 字符）",
                        value=str(row.get("content") or ""),
                        key="lex_ex_edit_content", height=100,
                    )
                    cur_source = str(row.get("source") or SOURCE_CORPUS)
                    new_source = st.selectbox(
                        "来源 source", list(EXAMPLE_SOURCES),
                        index=list(EXAMPLE_SOURCES).index(cur_source)
                        if cur_source in EXAMPLE_SOURCES else 0,
                        format_func=lambda s: SOURCE_LABELS.get(s, s),
                        key="lex_ex_edit_source",
                    )
                    new_caption = st.text_input(
                        "说明/出处图注", value=str(row.get("caption") or ""),
                        key="lex_ex_edit_caption",
                    )
                    new_order = st.number_input(
                        "展示顺序 sort_order",
                        value=int(_as_int(row.get("sort_order")) or 0), step=1,
                        key="lex_ex_edit_order",
                    )
                    if st.form_submit_button("保存修改", use_container_width=True):
                        if update_example(
                            eid, content=new_content, source=new_source,
                            caption=new_caption, sort_order=int(new_order),
                        ):
                            ui_kit.flash(f"例证 #{eid} 已更新。")
                            st.rerun()
                        else:
                            st.error(f"更新失败：文本为空/超长（≤{MAX_CONTENT_LEN} "
                                     "字符）/参数非法/数据库不可用。")
                cur_status = str(row.get("status") or "")
                nxt_status = _next_example_status(cur_status)
                if nxt_status:
                    if st.button(
                        f"审定流转：{cur_status} → {nxt_status}",
                        key=f"lex_ex_adv_{eid}",
                        help="单步流转不可跳级/回退；两人同流只有一人生效"
                             "（乐观并发守卫）。",
                    ):
                        if advance_example_status(eid, cur_status, nxt_status):
                            ui_kit.flash(f"例证 #{eid} 已流转为「{nxt_status}」。")
                            st.rerun()
                        else:
                            st.error("流转失败：状态已被他人先行流转/行不存在/"
                                     "数据库不可用（乐观守卫拒绝）。")
                else:
                    st.caption("该例证已「发布」（终态，不可再流转）。")
                if st.button(
                    "物理删除该例证（不可恢复）",
                    key=f"lex_ex_del_{eid}",
                    help="例证可重建非词典正文，物理 DELETE；删除时自动摘除"
                         "该例证的全部媒体绑定（unbind_for_anchor），不留孤儿绑定。",
                ):
                    if remove_example(eid):
                        ui_kit.flash(f"例证 #{eid} 已删除。")
                        st.rerun()
                    else:
                        st.error("删除失败：行不存在/数据库不可用。")

    with st.expander("🖼️ 媒体例证绑定（入口）", expanded=False):
        st.caption("资产先在「📖 词典管理 · 🖼️ 媒体库」登记（license 必填）——"
                   "本页只把已登记资产绑到例证（media_bindings example 锚，"
                   "用途 example_media，UNIQUE 幂等，重复绑定保留首次值）。")
        media_options = _example_options(examples)
        if not media_options:
            st.caption("该义位暂无例证，先新增文字例证再绑媒体。")
        else:
            media_pick = st.selectbox(
                "选择例证", list(media_options.keys()), key="lex_media_pick",
            )
            eid = media_options.get(media_pick)
            row = next((e for e in examples if _as_int(e.get("id")) == eid), None)
            if row is None or eid is None:
                st.warning("所选例证已被删除或列表已刷新，请重选。")
            else:
                current = _as_int(row.get("media_asset_id"))
                st.caption(f"当前 media_asset_id：#{current}" if current
                           else "当前 media_asset_id：—（未绑）")
                try:
                    # 批次 19 工具页面接线：registry 未加载回落直调等价
                    from src.tools.registry import get_tool as _get_tool
                    _mm = _get_tool("multimedia")
                    bindings = (_mm.run({"anchor_type": media_db.ANCHOR_EXAMPLE,
                                         "anchor_id": eid})
                                if _mm is not None else
                                media_db.list_assets_for_anchor(
                                    media_db.ANCHOR_EXAMPLE, eid))
                except Exception as e:  # noqa: BLE001 —— 展示失败不拦绑定
                    logger.warning(f"读取例证媒体绑定失败（example={eid}）: {e}")
                    bindings = []
                if bindings:
                    st.caption("该例证已有绑定："
                               + "、".join(
                                   f"#{b.get('asset_id')}"
                                   f"（{b.get('binding_status')}）"
                                   for b in bindings
                               ) + "。")
                else:
                    st.caption("该例证尚无媒体绑定。")
                asset_id = st.number_input(
                    "资产 id（media_assets.id）", min_value=1, step=1,
                    key="lex_media_asset_id",
                )
                media_caption = st.text_input(
                    "图注/来源说明（媒体例证通常记来源）",
                    key="lex_media_caption",
                )
                if st.button("绑定为媒体例证", key="lex_media_bind"):
                    if bind_example_media(
                        eid, int(asset_id), media_caption,
                    ):
                        ui_kit.flash(f"资产 #{int(asset_id)} 已绑为例证 #{eid} 的"
                                     "媒体例证（绑定状态=候选）。")
                        st.rerun()
                    else:
                        st.error("绑定失败：例证不存在/资产不存在（须先在媒体库"
                                 "登记）/参数非法/数据库不可用（media_db 已记日志）。")


# ============================================
# Tab 2：🌐 对译定稿
# ============================================

def _render_translation_state(tr: Optional[Dict[str, Any]]) -> None:
    """已有定稿展示（含辨析栏草稿 note；未定稿灰提示）。"""
    if not tr:
        st.info("该义位尚未定稿对译——三态单选后填表定稿。")
        return
    state = str(tr.get("state") or "")
    finalizer = f"#{tr.get('finalized_by')}" if tr.get("finalized_by") else "—"
    state_color = STATE_BADGE_COLORS.get(state, "#4a5568")
    rows: List[List[str]] = [
        ["三态", _badge(_esc(STATE_LABELS.get(state, state)), state_color)],
        ["对应词 equivalent", _esc(tr.get("equivalent") or "") or "—"],
        ["括注/辨析栏草稿 note", _esc(tr.get("note") or "") or "—"],
        ["释义翻译 paraphrase", _esc(tr.get("paraphrase") or "") or "—"],
        ["定稿人 finalized_by", _esc(finalizer)],
        ["定稿时间 finalized_at", _esc(tr.get("finalized_at") or "—")],
        ["更新时间 updated_at", _esc(tr.get("updated_at") or "—")],
    ]
    _render_table(["字段", "当前定稿"], rows)
    st.caption("对译一义位一稿、覆盖写：重新定稿即覆盖当前口径（定稿人/时间"
               "刷新）；改口径不必先删稿。")


def _render_translations_tab(me: Dict[str, Any]) -> None:
    """对译定稿 tab：选义位（merged 禁选）→ 已有定稿 → 三态分支表单 →
    定稿（set_translation upsert，finalized_by/at 落库）。"""
    senses = _list_sense_options()
    options, excluded = _sense_options(senses)
    _render_merged_excluded(excluded)
    if not options:
        st.info("暂无可选义位（cs_senses 未建表/无数据/数据库不可用）。")
        return
    pick = st.selectbox("选择义位", list(options.keys()), key="lex_tr_sense_pick")
    sense_id = options.get(pick)
    sense_row = next((s for s in senses if _as_int(s.get("id")) == sense_id), None)
    ok, reason = _sense_selectable((sense_row or {}).get("status"))
    if not ok:
        st.error(reason)
        return
    sense_ref = str(sense_id)

    st.markdown(f"<h4 style='{HEADER_H3}'>📜 已有定稿</h4>", unsafe_allow_html=True)
    existing = get_translation(sense_ref)
    _render_translation_state(existing)

    st.markdown(f"<h4 style='{HEADER_H3}'>✒️ 三态定稿</h4>", unsafe_allow_html=True)
    default_state = str((existing or {}).get("state") or STATE_FULL)
    state = st.radio(
        "对译三态",
        list(TRANSLATION_STATES),
        index=list(TRANSLATION_STATES).index(default_state)
        if default_state in TRANSLATION_STATES else 0,
        format_func=lambda s: f"{STATE_LABELS.get(s, s)}（{s}）",
        key="lex_tr_state",
        help="工序 12 三态：full 完全对应 / partial 部分对应（对应词＋括注）/"
             "none 无对应（释义翻译）。",
    )
    with st.form("lex_tr_form", clear_on_submit=False):
        equivalent = st.text_input(
            "对应词 equivalent（full/partial 必填）",
            value=str((existing or {}).get("equivalent") or ""),
            key="lex_tr_equivalent",
        )
        note_label = ("括注 note（partial 必填：对应词的含义边界说明）"
                      if state == STATE_PARTIAL
                      else "辨析栏草稿 note（可选：近义簇英汉辨析栏起草）")
        note = st.text_area(
            note_label,
            value=str((existing or {}).get("note") or ""),
            key="lex_tr_note", height=100,
        )
        paraphrase = st.text_area(
            "释义翻译 paraphrase（none 必填）",
            value=str((existing or {}).get("paraphrase") or ""),
            key="lex_tr_paraphrase", height=120,
            help="无对应时用中文释义直译该义位（装配侧 none 态渲染此列）。",
        )
        submitted = st.form_submit_button("定稿", use_container_width=True)
    if not submitted:
        return
    error = _translation_missing(state, equivalent, note, paraphrase)
    if error:
        st.error(error)  # 缺对应词/括注/释义翻译在表单侧给出可读拒绝
        return
    if set_translation(
        sense_ref, state, equivalent=equivalent, note=note,
        paraphrase=paraphrase, finalized_by=_as_int(me.get("id")),
    ):
        ui_kit.flash(f"义位 #{sense_id} 对译已定稿（{STATE_LABELS.get(state, state)}）。")
        st.rerun()
    else:
        st.error("定稿失败：参数非法/数据库不可用（lexical_db 已记日志）。")


# ============================================
# 区级页面入口（集成时注册进 app.py 分派）
# ============================================

def render_lexical_page() -> None:
    """📖 例证与对译（区级页面；页内两 tab，集成步骤挂进 app.py）。

    登录门＋角色门在函数入口（纵深防御 §6-4）：未登录提示登录；
    _can_edit 不过渲染 st.warning「仅编纂职能」并 return——页面内容
    （含各 tab 的取数）一概不执行。通过后幂等自举 lexical 两表。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录后再访问编纂成文区（例证与对译）。")
        return
    if not _can_edit(me):
        st.warning("⛔ 仅编纂职能（editor/reviewer/dict_admin；过渡期 admin "
                   "视为兼有）可访问例证与对译页。如需权限请联系管理员授予。")
        return

    ensure_lexical_tables()

    st.markdown(f"<h1 style='{HEADER_H1}'>📖 例证与对译</h1>", unsafe_allow_html=True)
    st.markdown(
        f"<h2 style='{HEADER_H2}'>编纂成文 · 工序 11 例证配置 ＋ 工序 12 对译定稿</h2>",
        unsafe_allow_html=True,
    )
    st.caption(
        "例证配置（语料例/改写例/自拟例 ＋ 媒体例证绑定入口，审定三态单步流转）· "
        "对译定稿（三态：完全对应/部分对应＋括注/无对应→释义翻译 ＋ 辨析栏草稿）。"
        "已并入（merged）义位禁选，内容随目标义位走。"
    )

    tab_examples, tab_translations = st.tabs(["🗂️ 例证配置", "🌐 对译定稿"])
    with tab_examples:
        _render_examples_tab(me)
    with tab_translations:
        _render_translations_tab(me)
