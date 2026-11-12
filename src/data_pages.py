"""数据工具页面 —— 数据导入向导 + 词条浏览器（Agent G，批次 2）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D⑧ 词典项目域与 §15
（数据出入口纪律，导入同权：批量灌库仅词典管理员）；契约：
docs/spec/阶段1施工规范.md §5（批次 2 页面层契约，Agent G 行）。
页面行为母本：docs/help/平台功能使用说明.md §六 6.3 数据导入 / 6.4 词条浏览器。

是什么（一个区级页面的两个渲染入口，集成时挂 st.tabs）：
  * render_import_page —— 三步导入向导：① 上传 xlsx/csv＋target_domain 说明；
    ② 预览（pandas 读前 20 行、sha256 指纹、列名清单、CSV 公式注入防护**复用**
    src/security.py 唯一实现）；③「登记批次」→ dict_admin_db.start_batch →
    列→字段映射配置（目标字段白名单 verb/chinese_ndef/phonetic，与
    src/import_engine.py 同源；列自动建议按「列名 ⊇ 目标字段」包含关系预填，
    仍以用户指派为准）→「干跑预览」（plan_import 结果表＋变更 diff
    预览，run_import(dry_run=True) **零写库**）→「执行写入」
    （run_import(dry_run=False) 逐行 UPSERT definitions）→ rows_ok/rows_rejected
    真实计数 → finish_batch 记账 → persist_revert_log 把回滚事件落伴生表
    import_revert_log → 回滚按钮启用。批次 2 首建时本页 rows_ok=0 是如实口径
    （只登记批次台账，业务表写入原计划批次 3 接线）；批次 5 起映射引擎已接线，
    上述计数与回滚都是真实值。oald_senses 追加写入**不支持**（批次 6 评审）。
    已登记批次列表＋「回滚」按钮：回滚**优先读持久化事件**（伴生表
    import_revert_log，跨会话成立）；无持久化记录才回退本会话暂存的
    revert_log（「本会话刚执行写入且已记账」的兼容口径）；两者皆无的批次
    按钮禁用并如实注明。
  * render_browser_page —— 管理视角的词条浏览器：词目搜索框（LIKE 前缀/子串，
    % _ 通配符转义防注入）＋分页（页码 number_input，每页 20）＋结果表
    （词目/义项数/coverage 列「待补」如实标注/来源分级）＋行展开（该词
    oald_senses 义项列表：sense_index/释义/语法码，前 10 条＋总计数）。

数据链（导入页调用批次 1 数据层＋批次 5 导入引擎；浏览器只读）：
  导入向导：start_batch / finish_batch / persist_revert_log / rollback_batch
  （写 import_batches 台账与 import_revert_log 伴生表，登记/记账/持久化/回滚
  是台账本身的数据）；业务写入走 src/import_engine.py 的
  plan_import（纯函数产计划）＋ run_import（dry_run=True 干跑预览零写库 /
  dry_run=False 逐行 UPSERT definitions 并收集 revert_log）；批次列表与持久化
  回滚日志读取为本模块私有参数化只读查询。
  词条浏览器：definitions / oald_senses 两表私有参数化只读查询（走
  src.mysql_db.get_db_cursor）；列名以 SHOW COLUMNS 实测为准 —— 来源分级列
  经 information_schema 探测（definition_source 优先，其次 source），探测不到
  显示「待补」。

权限（纵深防御，§15 导入同权；中央闸门 require_dict_admin 由集成接线）：
  * 导入页仅词典管理员：过渡期判定 role == "admin"（升级前旧列语义），升级后
    认 user_roles 的 roles 列表含 "dict_admin"（两者任一即放行）；
  * 词条浏览器登录即可（viewer 可看）；
  * 权限判定只信 st.session_state["user"]，不信任前端隐藏。

接口（契约 §5-Agent G；批次 5 导入写入接线 §8-Agent Q）：
  GUIDE（四段式 dict，集成时并入 PAGE_GUIDES）/
  render_import_page() -> None / render_browser_page() -> None
  其余下划线函数均为模块私有：纯函数（_escape_like/_like_pattern/_total_pages/
  _clamp_page/_sha256_bytes/_is_dict_admin/_sanitize_preview）与参数化只读
  查询辅助（_search_definitions/_senses_for_verbs/_list_recent_batches/
  _definitions_source_column）。业务写入不落在本模块 —— 全部委托
  src/import_engine.py（plan_import / run_import），本模块只做映射 UI、
  干跑预览渲染与台账接线（start_batch / finish_batch / rollback_batch）。

降级：
  数据库不可用时只读查询返回 []/0/None、写台账返回 0/False（数据层口径），
  页面渲染降级提示（「无匹配词目（或数据库不可用）」等），不整页崩掉；
  上传文件解析失败给出明确错误信息并停在第二步。

安全规则（全体遵守）：
  1. SQL 一律参数化（含 LIMIT/OFFSET 占位符）；唯一的动态片段是
     information_schema 探测结果拼 SELECT 列名 —— 取值限定在
     ('definition_source', 'source') 白名单内，绝不接受外部原文拼 SQL；
     业务写入的 SQL 全部在 src/import_engine.py 内（同样白名单＋参数化），
     本模块不自带任何写库语句；
  2. LIKE 搜索词经 _escape_like 转义 % _ !（配合 ESCAPE '!' 子句），防通配符
     注入把前缀查询变成全表模糊扫描；搜索词截断 50 字符；
  3. 预览表所有字符串单元格过 src/security.sanitize_csv_dataframe（CSV 公式
     注入防护的唯一实现，导出/预览同源，杜绝两份逻辑漂移）；
  4. 用户生成内容进 unsafe_allow_html 的 HTML 前一律 _html_escape
     （st.dataframe/expander/selectbox 与 unsafe_allow_html=False 的 markdown
     由 Streamlit 自动转义，不手工二次转义避免实体直显）；
  5. 导入写入默认干跑：页面只提供「干跑预览」按钮（run_import 默认
     dry_run=True），「执行写入」按钮是唯一显式 dry_run=False 的调用路径 ——
     未点执行前零业务写库（§15 导入同权，写入仅词典管理员）。
"""

import hashlib
import io
import json
import logging
import math
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.dict_admin_db import finish_batch, persist_revert_log, rollback_batch, start_batch
from src.db_utils import current_user as _current_user  # R6-4：单一实现点（调用点零变化）
from src.import_engine import TARGET_FIELDS, plan_import, run_import, validate_mapping
from src.mysql_db import get_db_cursor
from src.security import sanitize_csv_dataframe
from src import guards
from src import ui_kit
from src.design_system import HEADER_H1, get_card_style
from src import sense_spine

logger = logging.getLogger(__name__)

# ============================================
# 页面级常量
# ============================================

# widget key 统一前缀（契约：widget key 统一前缀；集成测试按前缀定位）。
KEY_IMPORT_PREFIX = "data_import_"
KEY_BROWSER_PREFIX = "data_browser_"

# 分页与预览规模（契约：每页 20；预览读前 20 行）。
PAGE_SIZE = 20
PREVIEW_ROWS = 20

# 行展开：每个词目显示前 N 条义项（＋总计数，绝不假装只有 10 条）。
SENSES_SHOW_LIMIT = 10

# 上传白名单与体积上限（docx 阶段 2 接入；20MB 上限是 MVP 防护，非业务口径）。
UPLOAD_TYPES = ("xlsx", "csv")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 搜索词长度上限（与主搜索框 1–50 字符口径一致）。
MAX_TERM_LEN = 50

# LIKE 转义字符（SQL 侧 ESCAPE '!'，避开 MySQL 反斜杠双重转义的坑）。
LIKE_ESCAPE = "!"

# coverage 列的如实标注值（覆盖阶梯 RUN 试点 32 → 352 → 996 尚未接入浏览器）。
COVERAGE_PENDING = "待补"

# 已登记批次列表展示条数。
BATCH_LIST_LIMIT = 20

# 来源分级探测白名单（definitions 的候选列，按优先级；唯一的动态列名来源）。
SOURCE_COLUMN_CANDIDATES = ("definition_source", "source")

# 列→字段映射下拉选项（目标字段白名单与 src/import_engine.TARGET_FIELDS 同源；
# 首项为不导入 —— 映射校验由引擎 validate_mapping 负责，页面不重复造规则）。
MAPPING_SKIP = "不导入"
MAPPING_OPTIONS = (MAPPING_SKIP,) + TARGET_FIELDS

# 会话键（revert_log 会话回退与执行结果提示）。批次 6-T 起 revert_log 在
# 「执行写入」成功后由 persist_revert_log 持久化进伴生表 import_revert_log ——
# 回滚优先读持久化事件（跨会话成立）；会话键仅作「本会话刚执行写入」的
# 回退兼容口径（持久化失败时不丢同会话回滚能力）与顶部提示。
REVERT_LOG_KEY = f"{KEY_IMPORT_PREFIX}revert_log"
REVERT_BATCH_KEY = f"{KEY_IMPORT_PREFIX}revert_batch_id"
EXEC_RESULT_KEY = f"{KEY_IMPORT_PREFIX}exec_result"
PLAN_KEY = f"{KEY_IMPORT_PREFIX}plan"
PREVIEW_KEY = f"{KEY_IMPORT_PREFIX}preview"
MAPPING_KEY = f"{KEY_IMPORT_PREFIX}mapping"

# 登记向导的会话键集合（重置向导时清空；revert_* 与 exec_result 属已记账批次，
# 保留给下方批次列表的回滚入口，不随向导重置）。
_WIZARD_SESSION_KEYS = (
    f"{KEY_IMPORT_PREFIX}batch_id",
    f"{KEY_IMPORT_PREFIX}rows_total",
    MAPPING_KEY,
    PLAN_KEY,
    PREVIEW_KEY,
)


# ============================================
# GUIDE（契约 §5：四段式，集成时原样并入 PAGE_GUIDES）
# ============================================

GUIDE = {
    "label": "🧰 数据工具",
    "purpose": "词典管理区的数据出入口：数据导入向导走「上传 → 指纹 → 预览 → 登记"
               "批次 → 列映射 → 干跑预览 → 执行写入（可回滚）」的批次台账＋业务写入"
               "流程（import_batches 审计线＋import_engine 映射引擎），词条浏览器提供"
               "管理视角的词目检索、分页浏览与义项明细展开。",
    "principle": [
        "两条通道边界明确（帮助文档 6.3 口径）：首建批量走 CLI 灌库脚本（幂等八步）；"
        "向导只管编辑期增量。批次 2 首建时向导只完成「登记批次」半程（rows_ok=0）"
        "且业务表写入原计划批次 3 接线 —— 批次 5 起映射引擎（src/import_engine.py）"
        "已接线：按 verb 键逐行 UPSERT definitions，只写映射白名单字段"
        "（chinese_ndef/phonetic），cluster_id 簇归属保留现值。",
        "批次台账是一次性事实：start_batch 登记（status=running）→ 执行写入 →"
        "finish_batch 记真实行数（running → finished，只有 running 批次可记账，"
        "不许覆盖）→ persist_revert_log 把回滚事件持久化进伴生表 "
        "import_revert_log → 出问题 rollback_batch 回滚（finished → "
        "rolled_back）。revert_log 由导入引擎逐行收集（insert→软作废 / update→"
        "恢复旧值），持久化后回滚不再依赖同会话。",
        "默认干跑：映射配置后先「干跑预览」（plan_import 校验表＋run_import "
        "dry_run=True 变更 diff，零写库），确认后才可「执行写入」（唯一显式 "
        "dry_run=False 的路径）—— 未点执行前业务表零写入。",
        "目标字段白名单同源约束：列→字段映射下拉只提供 verb/chinese_ndef/phonetic"
        "（与引擎 TARGET_FIELDS 常量同源）；列自动建议按「列名与目标字段的包含"
        "关系」预填下拉（如 verb_clean → verb），仅是预填、映射仍以用户指派为准；"
        "oald_senses 追加写入不支持（涉及义位准入语义，批次 6 评审）。",
        "sha256 指纹是批次的幂等/对账凭据：文件指纹入 import_batches.file_sha256，"
        "重复导入同一文件可对账识别；预览只读前 20 行，绝不把未确认的数据当已导入。",
        "CSV 公式注入防护与导出同源：以 = + - @ 制表符/回车 开头的单元格在预览中即"
        "前置单引号（复用 src/security.py 唯一实现）—— 恶意文本从上传到导出全链路"
        "不可能以公式形态离开平台。",
        "词条浏览器是只读视图：数据来自 definitions / oald_senses 两表参数化查询；"
        "coverage 列如实标注「待补」（覆盖阶梯尚未接入浏览器），来源分级列取 "
        "definitions 的来源列（information_schema 实测，缺失同样标「待补」）。",
        "LIKE 通配符防注入：搜索词中 % _ 会被转义为字面字符（ESCAPE '!'），防止"
        "「%%」把前缀查询变成全表模糊扫描；搜索词截断 50 字符。",
    ],
    "data_source": [
        "import_batches ＋ import_revert_log（src/dict_admin_db.py start_batch / "
        "finish_batch / persist_revert_log / rollback_batch 登记）：批次 id、"
        "文件名、sha256、target_domain、列映射留痕（mapping_json 含 "
        "column_field_mapping）、行数三列与状态机（running/finished/rolled_back）；"
        "伴生表按 (batch_id, seq) 存逐条回滚事件（跨会话回滚的数据源）。",
        "definitions（src/import_engine.py plan_import / run_import 写入）：按 "
        "verb 键 UPSERT 中文释义/音标；映射校验、非法行原因、变更 diff 预览与"
        "逐行 revert_log 全部来自引擎返回值；cluster_id 等白名单外字段引擎不触碰。",
        "definitions / oald_senses（src/mysql_db.py 只读查询）：词目、义项数（按 "
        "oald_senses 实数）、释义、语法码；来源分级列以 SHOW COLUMNS 实测为准"
        "（definition_source 优先，其次 source）。",
        "上传文件本身：xlsx 用 openpyxl 引擎、csv 用 pandas 解析；预览读前 20 行，"
        "全量行数以完整解析为准（20MB 上限内的 MVP 解析）；执行写入以完整解析的"
        "全量行为准。",
        "操作留痕：operator 为操作人 users.id（§15 导入同权，仅词典管理员可登记"
        "与执行写入）。",
    ],
    "steps": [
        "「📥 数据导入向导」标签页：上传 xlsx / csv 文件（docx 阶段 2 接入），确认"
        "目标域 target_domain 与词典项目 id。",
        "第二步自动生成预览：核对行数、列名清单、sha256 指纹与前 20 行数据；命中"
        "公式注入防护的单元格已前置单引号并有计数提示。",
        "点「登记批次」写入 import_batches（得到 batch_id，mapping_json 留痕），"
        "在映射配置区把列逐一指派到目标字段（verb 键列与 chinese_ndef 主载荷列"
        "必选，phonetic 可选；其余列留「不导入」）。",
        "点「干跑预览」看两张表：plan_import 的合法/非法行清单（非法行带中文"
        "原因）＋ run_import 干跑的变更 diff（新增/更新/无变更，逐字段旧值→"
        "新值）—— 干跑零写库。",
        "确认无误点「执行写入」：逐行 UPSERT definitions，rows_ok/rows_rejected "
        "为真实计数，finish_batch 自动记账，revert_log 持久化进伴生表 "
        "import_revert_log 后下方「回滚」按钮对本批次启用；也可选「不写入业务"
        "表，直接记账完成」（rows_ok=0 口径）。",
        "在「已登记批次」列表核对最近批次（文件/指纹/行数/状态）；对已记账批次"
        "可点「回滚」—— 回滚读持久化回滚日志，跨会话成立（不必是执行写入的"
        "同一会话）：更新行按 old_values 恢复旧值，新增行因 definitions "
        "无 status 列仅留痕不作废（不物理 DELETE）。",
        "「📖 词条浏览器」标签页：输入词目关键字并选前缀/子串匹配，结果表给出 词目 / "
        "义项数 / coverage（待补） / 来源分级；页码输入框翻页（每页 20 条）。",
        "展开任一词目行：显示该词 oald_senses 义项列表（sense_index / 释义 / 语法码，"
        "前 10 条＋总计数）；展开即见义项脊柱 —— 每条义项下的 🧬 expander 点开后"
        "懒加载七段全链留痕（义项信息 / 标注留痕 / 信度 / 簇归属 / 模板预览 / 媒体 / "
        "定制属性），收起时零取数。",
    ],
    "notes": [
        "业务写入已接线但范围如实：本页只写 definitions 词目层（中文释义/音标，"
        "按 verb 键 UPSERT）；oald_senses 追加写入不支持（批次 6 评审）；词条"
        "内容仍以词条浏览器/搜索页读到的 definitions / oald_senses 为准。",
        "revert_log 已持久化（批次 6-T）：执行写入成功后事件落伴生表 "
        "import_revert_log（UNIQUE(batch_id, seq)），回滚优先读持久化事件 —— "
        "跨会话回滚成立，页面刷新/换会话后仍可回滚；无持久化记录的批次才回退"
        "本会话暂存的 revert_log（持久化失败时的兜底口径）。rows_ok=0 的空批次"
        "无回滚事件可持久化，回滚对其无事可做。",
        "回滚语义如实说明：更新行按 old_values 恢复旧值（含 cluster_id 在内的"
        "白名单外字段导入时就没被触碰）；新增行因 definitions 无 status 列，"
        "rollback_batch 软作废跳过、仅留痕不作废 —— 平台纪律不物理 DELETE。",
        "义项脊柱（批次 4 接入）为只读视图：七段各自独立取数、独立降级，缺数段如实"
        "显示「暂无数据：<原因>」不编数；信度段 α 为范畴×任务级口径（非单义位）；"
        "簇/模板两段在义位未进入语义分析试点库时如实标注「未在建模覆盖内」。",
        "coverage 列「待补」与来源分级缺失时的「待补」都是如实标注 —— 覆盖阶梯"
        "（RUN 试点 32 义位 → 352 建模义位 → 996 全义项）尚未接入浏览器，不得编数。",
        "搜索词里的 % 和 _ 按字面字符匹配（已转义）；想用通配符的诉求不在此页支持。",
        "上传文件只在预览与指纹计算中读取，未点「登记批次」前不写入任何台账、"
        "未点「执行写入」前不写业务表；20MB 是 MVP 解析上限，更大的批量走 CLI "
        "灌库脚本。",
    ],
}


# ============================================
# 会话与权限（纵深防御自检）
# ============================================
# _current_user 已收敛至 src/db_utils.current_user（R6-4 单一实现点，文件头
# 别名导入）—— 本模块不再留本地副本（fail-closed 语义不变：user 非 dict 即 None）。


def _is_dict_admin(user: Optional[Dict[str, Any]]) -> bool:
    """词典管理员判定（纯函数；导入页角色门用，纵深防御层）。

    过渡期判定（契约 §5 通用约定）：role == "admin" 视为兼有 dict_admin ——
    users.role 旧列在升级完成前仍是登录态的主角色来源。升级后以 user_roles
    的 roles 列表为准（含 "dict_admin" 即放行）；role 列直接为 "dict_admin"
    的账号同样放行（六角色口径直读）。
    """
    if not isinstance(user, dict):
        return False
    if user.get("role") in ("admin", "dict_admin"):
        return True
    roles = user.get("roles")
    return isinstance(roles, (list, tuple)) and "dict_admin" in roles


# ============================================
# 纯函数（搜索词清洗 / 分页 / 指纹 / 预览防护）
# ============================================

def _escape_like(value: Any) -> str:
    """转义 LIKE 通配符与本模块的转义字符（纯函数，防通配符注入）。

    与 SQL 侧 ``LIKE %s ESCAPE '!'`` 配套：'!' 是转义字符必须先转义，然后
    % 与 _ 转为字面字符；反斜杠在显式 ESCAPE 下无特殊含义，不处理。
    非 str 入参（None/数字等）返回空串 —— 页面按「空搜索词」处理。
    """
    if not isinstance(value, str):
        return ""
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE + LIKE_ESCAPE)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def _like_pattern(term: Any, prefix_only: bool = True) -> str:
    """把搜索词清洗成 LIKE 模式串（纯函数；前缀/子串两种口径）。

    清洗 = 去首尾空白 → 截断 MAX_TERM_LEN 字符 → _escape_like 转义（先截断后
    转义，避免把转义对从中间截断出悬空的 '!'）；空词返回空串（调用方按
    「无搜索词」处理，绝不生成匹配全表的 %% 模式）。
    """
    if not isinstance(term, str):
        return ""
    cleaned = term.strip()[:MAX_TERM_LEN]
    if not cleaned:
        return ""
    escaped = _escape_like(cleaned)
    return escaped + "%" if prefix_only else f"%{escaped}%"


def _total_pages(total_rows: Any, page_size: int) -> int:
    """总页数（纯函数）：至少 1 页（空库也给第 1 页，显示「共 0 条」）。"""
    if page_size <= 0:
        return 1
    try:
        rows = max(0, int(total_rows or 0))
    except (TypeError, ValueError):
        rows = 0
    return max(1, math.ceil(rows / page_size))


def _clamp_page(page: Any, total_pages: Any) -> int:
    """把页码收敛到 [1, total_pages]（纯函数；页码来自 number_input，防越界）。"""
    try:
        current = int(page)
    except (TypeError, ValueError):
        current = 1
    try:
        top = max(1, int(total_pages or 1))
    except (TypeError, ValueError):
        top = 1
    return min(max(current, 1), top)


def _sha256_bytes(data: Any) -> str:
    """字节串的 sha256 十六进制指纹（批次台账 file_sha256 的来源）。"""
    return hashlib.sha256(data if isinstance(data, (bytes, bytearray)) else b"").hexdigest()


def _as_positive_int(value: Any) -> Optional[int]:
    """宽松转正整数（int 且非 bool 且 >0 才收；其余 None）—— 纯函数防脏入参。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _sanitize_preview(df: pd.DataFrame) -> pd.DataFrame:
    """预览表的 CSV 公式注入防护（复用 src/security.py 唯一实现，不修改原表）。

    以 = + - @ 制表符/回车 开头的字符串单元格前置单引号 —— 与平台所有 CSV
    导出同一实现，杜绝「预览一套、导出另一套」的逻辑漂移。
    """
    return sanitize_csv_dataframe(df)


def _changed_cell_count(before: pd.DataFrame, after: pd.DataFrame) -> int:
    """防护前后发生变化的单元格数（纯统计，页面提示「命中防护 N 格」用）。"""
    try:
        diff = before.astype(str) != after.astype(str)
        return int(diff.to_numpy().sum())
    except Exception as e:  # 形状异常等按 0 处理，不影响预览渲染
        logger.warning(f"防护命中统计失败（按 0 处理）: {e}")
        return 0


def _suggest_mapping(columns: Any) -> Dict[str, str]:
    """xlsx 列自动建议（批次 6-T，契约 §9-T②；纯函数，零副作用）。

    口径：列名与目标字段（TARGET_FIELDS 白名单）**模糊匹配（包含关系，
    大小写不敏感）** —— 列名包含字段名或字段名包含列名即命中（如
    verb_clean → verb、Chinese_ndef → chinese_ndef）；同字段多列只取首个
    命中列，同列多字段按 TARGET_FIELDS 顺序取首个命中字段（确定性口径）。
    精确相等优先于包含关系。中文列名（如「中文释义」）与英文字段无包含
    关系，如实不猜 —— 预填只到「不导入」，映射仍以用户指派为准
    （validate_mapping 是唯一校验闸口）。

    Returns:
        dict: {列名: 建议目标字段}（仅含命中列；空入参/非 list 返回 {}）。
    """
    if not isinstance(columns, (list, tuple)):
        return {}
    norm = {str(c): str(c).strip().lower() for c in columns}
    suggestions: Dict[str, str] = {}
    used_columns: set = set()
    for field in TARGET_FIELDS:  # 白名单顺序即优先级（verb 键列优先）
        field_lower = field.lower()
        assigned = None
        # 先精确相等，再包含关系；一字段至多建议一列（与映射校验的
        # 「一字段至多一列」同口径，杜绝预填即歧义）
        for col, col_lower in norm.items():
            if col not in used_columns and col_lower == field_lower:
                assigned = col
                break
        if assigned is None:
            for col, col_lower in norm.items():
                if col in suggestions or col in used_columns:
                    continue
                if field_lower in col_lower or col_lower in field_lower:
                    assigned = col
                    break
        if assigned is not None:
            suggestions[assigned] = field
            used_columns.add(assigned)
    return suggestions


# ============================================
# 只读查询辅助（本模块私有；SQL 一律参数化，docstring 注明只读）
# ============================================

def _definitions_source_column() -> Optional[str]:
    """探测 definitions 表的「来源分级」列（**只读**；契约要求列名以 SHOW
    COLUMNS 实测为准，不硬编码猜测）。

    探测范围限定 SOURCE_COLUMN_CANDIDATES 白名单（definition_source 优先，
    其次 source）；返回值要么是白名单成员、要么是 None —— 这是本模块唯一
    会拼进 SQL 的动态片段，白名单 + information_schema 双重约束。数据库
    不可用返回 None（页面来源分级列显示「待补」）。
    """
    try:
        with get_db_cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(SOURCE_COLUMN_CANDIDATES))
            cursor.execute(
                f"""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = %s
                      AND COLUMN_NAME IN ({placeholders})
                    ORDER BY FIELD(COLUMN_NAME, {placeholders})""",
                ("definitions", *SOURCE_COLUMN_CANDIDATES, *SOURCE_COLUMN_CANDIDATES),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        name = str(row["COLUMN_NAME"])
        return name if name in SOURCE_COLUMN_CANDIDATES else None
    except Exception as e:
        logger.warning(f"探测 definitions 来源列失败（按无来源列处理）: {e}")
        return None


def _search_definitions(
    term: Any, prefix_only: bool, page: Any, page_size: int = PAGE_SIZE,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """按词目搜索 definitions（**只读**；词目/义项数/来源分级，含分页收敛）。

    Args:
        term: 搜索词（经 _like_pattern 清洗：转义 % _ !、截断 50 字符）
        prefix_only: True=前缀匹配，False=子串匹配
        page: 请求页码（超出范围自动收敛到 [1, total_pages]）
        page_size: 每页条数（默认 PAGE_SIZE=20）

    Returns:
        (rows, total, page)：rows 为当前页词条行（verb/sense_total/source_label），
        total 为匹配词目总数，page 为实际生效页码（收敛后）。搜索词为空、
        无匹配或数据库不可用返回 ([], 0, 1)。
    """
    pattern = _like_pattern(term, prefix_only)
    if not pattern:
        return [], 0, 1
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM definitions WHERE verb LIKE %s ESCAPE '!'",
                (pattern,),
            )
            total = int(cursor.fetchone()["n"] or 0)
            if total <= 0:
                return [], 0, 1
            total_pages = _total_pages(total, page_size)
            current = _clamp_page(page, total_pages)
            offset = (current - 1) * page_size
            # source_col 只能取自 _definitions_source_column 的白名单探测结果
            # （definition_source / source），绝不接受外部原文 —— 本模块唯一的
            # 动态列名拼接点，白名单约束见该函数 docstring。
            source_col = _definitions_source_column()
            source_expr = (
                f"d.{source_col} AS source_label" if source_col else "NULL AS source_label"
            )
            group_extra = f", d.{source_col}" if source_col else ""
            cursor.execute(
                f"""SELECT d.id, d.verb, {source_expr},
                           COUNT(os.id) AS sense_total
                    FROM definitions d
                    LEFT JOIN oald_senses os ON os.definition_id = d.id
                    WHERE d.verb LIKE %s ESCAPE '!'
                    GROUP BY d.id, d.verb{group_extra}
                    ORDER BY d.verb
                    LIMIT %s OFFSET %s""",
                (pattern, page_size, offset),
            )
            rows = [dict(r) for r in cursor.fetchall()]
            return rows, total, current
    except Exception as e:
        logger.error(f"词目搜索失败（term={term!r}）: {e}")
        return [], 0, 1


def _senses_for_verbs(verbs: List[Any]) -> Dict[str, List[Dict[str, Any]]]:
    """取一批词目的 oald_senses 义项明细（**只读**；行展开数据源）。

    一次 IN 查询带回整页词目的全部义项（当前数据每词 ≤39 条、每页 20 词，
    规模有界），按 verb + sense_index 排序后在页面侧分组截前 10 条 ——
    计数用全量列表长度，不另发 COUNT 查询。占位符按动词个数生成（个数来自
    受控的当前页行数，值全走参数），数据库不可用返回 {}。行含 s.id
    （义位唯一锚），供义项脊柱 expander 懒加载定位。
    """
    clean_verbs = [str(v) for v in verbs if str(v)]
    if not clean_verbs:
        return {}
    placeholders = ", ".join(["%s"] * len(clean_verbs))
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""SELECT s.id, d.verb, s.sense_index, s.definition, s.grammar
                    FROM oald_senses s
                    JOIN definitions d ON d.id = s.definition_id
                    WHERE d.verb IN ({placeholders})
                    ORDER BY d.verb, s.sense_index""",
                tuple(clean_verbs),
            )
            rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"批量取义项失败（{len(clean_verbs)} 词）: {e}")
        return {}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("verb")), []).append(dict(row))
    return grouped


def _list_recent_batches(limit: int = BATCH_LIST_LIMIT) -> List[Dict[str, Any]]:
    """最近的导入批次台账（**只读**；导入页批次列表数据源）。

    Returns:
        list[dict]: 按 id 降序的批次行（id/project_id/file_name/file_sha256/
        target_domain/rows_*/status/operator/created_at）；台账表未建
        （ensure_dict_admin_tables 未跑）或数据库不可用返回 []。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT id, project_id, file_name, file_sha256, target_domain,
                          rows_total, rows_ok, rows_rejected, status, operator,
                          created_at
                   FROM import_batches
                   ORDER BY id DESC
                   LIMIT %s""",
                (max(1, int(limit)),),
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.warning(f"读取导入批次列表失败（按空列表处理）: {e}")
        return []


def _load_persisted_revert_log(batch_id: Any) -> List[Dict[str, Any]]:
    """读一个批次的持久化回滚事件（**只读**；伴生表 import_revert_log）。

    回滚按钮「优先读持久化事件」的取数来源：事件由执行写入成功后的
    persist_revert_log 落库，按 seq 升序返回 —— 跨会话/页面刷新后仍可读，
    会话丢失不再阻断回滚。批次无持久化记录、参数非法或数据库不可用返回
    []（调用方回退会话暂存口径）。
    """
    bid = _as_positive_int(batch_id)
    if bid is None:
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT event FROM import_revert_log "
                "WHERE batch_id = %s ORDER BY seq",
                (bid,),
            )
            rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f"读取持久化回滚日志失败（batch_id={bid}，按无记录处理）: {e}")
        return []
    events: List[Dict[str, Any]] = []
    for row in rows:
        raw = row.get("event")
        if isinstance(raw, (dict, list)):
            events.append(raw if isinstance(raw, dict) else {})
            continue
        try:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            parsed = json.loads(text) if isinstance(text, str) else None
        except (UnicodeDecodeError, TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            events.append(parsed)
        else:
            logger.warning(f"持久化回滚日志含不可解析事件（batch_id={bid}），该条按缺失处理")
    return events


# ============================================
# 页面渲染：数据导入向导
# ============================================

def _read_excel_fallback(data: bytes) -> pd.DataFrame:
    """openpyxl 直读兜底（pandas 与 openpyxl 版本倾斜时的降级路径）。

    pandas 对 openpyxl 有最低版本硬检查（如要求 ≥3.1.5 而环境装 3.1.2），
    不满足即在引擎分发时抛 ImportError —— 但 openpyxl 本体完全可用。此处
    绕开 pandas 引擎分发、直接用 openpyxl 读首张工作表（data_only=False
    保留公式原文，与预览「看原文 + 公式防护」的定位一致），保证 xlsx 预览
    不因依赖版本倾斜失效。
    """
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    try:
        rows = [tuple(r) for r in workbook.active.iter_rows(values_only=True)]
    finally:
        workbook.close()
    if not rows:
        return pd.DataFrame()
    header = ["" if c is None else str(c) for c in rows[0]]
    return pd.DataFrame(rows[1:], columns=header)


def _read_tabular(data: bytes, file_name: str) -> Optional[pd.DataFrame]:
    """把上传字节解析成 DataFrame（xlsx → openpyxl / csv → pandas）。

    dtype=object 保留单元格原文（公式文本不被 pandas 当数值吞掉）；xlsx 的
    pandas 路径失败时降级 openpyxl 直读（见 _read_excel_fallback）；仍失败
    （坏文件/空文件/不支持的后缀）返回 None，由页面给出明确提示。
    """
    lower = (file_name or "").lower()
    try:
        if lower.endswith(".csv"):
            return pd.read_csv(io.BytesIO(data), dtype=object, keep_default_na=False)
        if lower.endswith(".xlsx"):
            try:
                return pd.read_excel(io.BytesIO(data), engine="openpyxl", dtype=object)
            except Exception as e:
                logger.warning(f"pd.read_excel 失败，降级 openpyxl 直读: {e}")
                return _read_excel_fallback(data)
        return None
    except Exception as e:
        logger.error(f"解析上传文件失败: {file_name!r}: {e}")
        return None


def _render_metric_cards(cards: List[Tuple[str, Any]]) -> None:
    """顶部统计卡（users_admin_page._metrics_row 同款视觉语言；值已转义）。"""
    cols = st.columns(len(cards))
    for col, (label, value) in zip(cols, cards):
        with col:
            st.markdown(
                f"<div style='{get_card_style()}'>"
                f"<div style='font-size:0.85em;color:#718096;'>"
                f"{_html_escape(str(label))}</div>"
                f"<div style='font-size:1.3em;font-weight:bold;color:#2d3748;'>"
                f"{_html_escape(str(value))}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_preview(data: bytes, file_name: str) -> Optional[Tuple[int, List[str]]]:
    """第二步：sha256 + 前 20 行预览 + 列名清单 + 防护复用。

    Returns:
        (rows_total, columns)：全量行数与列名清单（登记批次的 mapping_json
        留痕用）；解析失败 / 空文件返回 None（页面停在第二步）。
    """
    sha = _sha256_bytes(data)
    df = _read_tabular(data, file_name)
    if df is None:
        st.error("文件解析失败：请确认上传的是 xlsx 或 csv（docx 阶段 2 接入）。")
        return None
    rows_total = int(len(df))
    if rows_total <= 0:
        st.error("文件中没有数据行，无法登记批次。")
        return None
    columns = [str(c) for c in df.columns]

    preview = df.head(PREVIEW_ROWS)
    protected = _sanitize_preview(preview)
    n_protected = _changed_cell_count(preview, protected)

    _render_metric_cards([
        ("数据行数", rows_total),
        ("列数", len(columns)),
        ("预览行数", f"{len(preview)} / {PREVIEW_ROWS}"),
        ("防护命中格数", n_protected),
    ])
    st.code(sha, language=None)
    st.caption("↑ 文件 sha256 指纹（写入 import_batches.file_sha256，幂等/对账凭据）")

    column_names = ", ".join(_html_escape(c) for c in columns)
    st.markdown(f"**列名清单：** {column_names}", unsafe_allow_html=True)
    st.dataframe(protected, use_container_width=True)
    if n_protected > 0:
        st.caption(
            f"预览中 {n_protected} 个单元格命中 CSV 公式注入防护（= + - @ 制表符/"
            "回车 开头已前置单引号）—— 复用 src/security.py 唯一实现，与平台导出同源。"
        )
    st.caption(
        f"仅展示前 {PREVIEW_ROWS} 行；行数统计以完整解析为准。预览不写任何数据 —— "
        "点「登记批次」才写 import_batches 台账，业务表写入在批次 3 接线。"
    )
    return rows_total, columns


def _render_mapping_editor(columns: List[str]) -> Tuple[Optional[Dict[str, str]], List[str]]:
    """列 → 目标字段映射编辑区（白名单校验委托引擎 validate_mapping，不重复造规则）。

    下拉选项与 src/import_engine.TARGET_FIELDS 同源（MAPPING_OPTIONS）；一个列名
    一个 widget（key 按列名持久，重复上传同名文件可保留上次映射）。列自动建议
    （_suggest_mapping，列名与目标字段包含关系）只决定**首次渲染的预填项**，
    用户改选后以其为准；命中列在 caption 中提示，未命中的列如实留「不导入」。

    Returns:
        (mapping, errors)：映射合法时 ({列名: 字段}, [])；未指派任何列 / 校验
        不过时 (None, [中文原因, ...])。
    """
    st.markdown("**列 → 目标字段映射**")
    suggestions = _suggest_mapping(columns)
    st.caption(
        "目标字段白名单与引擎同源：verb＝词目键（必选一列）；chinese_ndef＝中文释义"
        "（必选一列）；phonetic＝音标（可选）。oald_senses 追加写入不支持（批次 6 "
        "评审）。列自动建议按「列名 ⊇ 目标字段」包含关系预填（大小写不敏感），"
        "仅是预填，映射仍以你的指派为准；中文列名与英文字段无包含关系，如实不猜。"
    )
    if suggestions:
        hinted = "、".join(f"「{col}」→ {field}" for col, field in sorted(suggestions.items()))
        st.caption(f"已按列名包含关系预填 {len(suggestions)} 列：{hinted}。")
    mapping: Dict[str, str] = {}
    for col in columns:
        prefill = suggestions.get(col, MAPPING_SKIP)
        choice = st.selectbox(
            f"列「{col}」→ 目标字段",
            MAPPING_OPTIONS,
            index=list(MAPPING_OPTIONS).index(prefill) if prefill in MAPPING_OPTIONS else 0,
            key=f"{KEY_IMPORT_PREFIX}map_{col}",
        )
        if choice != MAPPING_SKIP:
            mapping[str(col)] = choice
    if not mapping:
        return None, ["尚未指派任何列：verb（词目键）与 chinese_ndef（中文释义）必选。"]
    norm, errors = validate_mapping(mapping)
    if norm is None:
        return None, errors
    return norm, []


def _render_dry_run_tables(plan: Dict[str, Any], preview: List[Dict[str, Any]]) -> None:
    """干跑结果两张表（只读渲染）：plan_import 校验表 ＋ 变更 diff 预览。"""
    if plan.get("mapping_errors"):
        for err in plan["mapping_errors"]:
            st.error(f"映射错误：{err}")
    _render_metric_cards([
        ("合法行", plan.get("rows_ok", 0)),
        ("非法行", plan.get("rows_rejected", 0)),
        ("预览条目", len(preview)),
    ])
    rejected = plan.get("rejected") or []
    if rejected:
        st.markdown("**非法行（执行时拒绝，原因如下）**")
        st.dataframe(
            pd.DataFrame([
                {"行号": r["row_index"] + 1, "拒绝原因": r["reason"]} for r in rejected
            ]),
            use_container_width=True,
        )
    if preview:
        preview_rows: List[Dict[str, Any]] = []
        action_labels = {"insert": "新增词目行", "update": "更新既有行", "none": "无变更"}
        for p in preview:
            label = action_labels.get(str(p.get("action")), str(p.get("action")))
            changes = p.get("changes") or {}
            if changes:
                for field, ch in changes.items():
                    old = ch.get("old")
                    preview_rows.append({
                        "行号": p.get("row_index", 0) + 1,
                        "词目": p.get("verb"),
                        "动作": label,
                        "字段": field,
                        "旧值": "（空）" if old is None else str(old),
                        "新值": str(ch.get("new")),
                    })
            else:
                preview_rows.append({
                    "行号": p.get("row_index", 0) + 1,
                    "词目": p.get("verb"),
                    "动作": label,
                    "字段": "—",
                    "旧值": "—",
                    "新值": "—",
                })
        st.markdown("**变更 diff（执行写入将发生的确切变更）**")
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)
    st.caption(
        "干跑（run_import 默认 dry_run=True）只读不写库：以上是「执行写入」将发生的"
        "确切变更；新增词目行的 semantic_table 为空对象结构占位，cluster_id 置 NULL。"
    )


def _render_register_step(user: Dict[str, Any], file_name: str, sha: str,
                          rows_total: int, target_domain: str, project_id: int,
                          columns: List[str], rows: List[Dict[str, Any]]) -> None:
    """第三步：映射配置 → 登记批次 → 干跑预览 → 执行写入（默认干跑，显式才写库）。

    映射在**登记时冻结**（mapping_json 留痕 ＝ 会话暂存 MAPPING_KEY，执行一律用
    登记版映射，杜绝「台账留痕一套、实际执行另一套」）；改映射须重置向导重登记。
    """
    operator = user.get("id")
    can_register = isinstance(operator, int) and operator > 0 and rows_total > 0
    batch_id = st.session_state.get(f"{KEY_IMPORT_PREFIX}batch_id")

    if not batch_id:
        # --- 映射配置（登记前冻结）---
        mapping, mapping_errors = _render_mapping_editor(columns)
        if mapping is None:
            for err in mapping_errors:
                st.error(f"映射错误：{err}")
        if not can_register:
            st.warning("无法确定操作人（会话用户缺少有效 id），不能登记批次。")
        if st.button(
            "📦 登记批次",
            type="primary",
            disabled=not (can_register and mapping is not None),
            key=f"{KEY_IMPORT_PREFIX}register_btn",
            help="写入 import_batches（status=running），记录文件名/sha256/列→字段映射"
                 "（mapping_json 留痕）；映射随登记冻结。",
        ):
            payload = {
                "columns": columns,
                "rows_total": rows_total,
                "target_domain": target_domain,
                "column_field_mapping": mapping,
                "wiring_note": "批次 5 映射引擎已接线（src/import_engine.py）",
            }
            bid = start_batch(project_id, file_name, sha, target_domain,
                              payload, int(operator or 0))
            if bid:
                st.session_state[f"{KEY_IMPORT_PREFIX}batch_id"] = bid
                st.session_state[f"{KEY_IMPORT_PREFIX}rows_total"] = rows_total
                st.session_state[MAPPING_KEY] = mapping
                st.rerun()
            else:
                st.error("登记失败：参数非法或数据库不可用（详见服务端日志）。")
        return

    # --- 已登记：用冻结映射复核 + 干跑预览 + 执行写入 ---
    bid = int(batch_id)
    registered_rows = int(
        st.session_state.get(f"{KEY_IMPORT_PREFIX}rows_total") or rows_total
    )
    st.success(f"已登记批次：batch_id = {bid}（status=running，尚未记账）")
    registered_mapping_raw = st.session_state.get(MAPPING_KEY)
    registered_mapping, mapping_errors = validate_mapping(registered_mapping_raw)
    if registered_mapping is None:
        for err in mapping_errors:
            st.error(f"映射错误：{err}")
    else:
        st.markdown("**冻结映射（mapping_json 留痕 ＝ 执行口径）**")
        st.json({col: registered_mapping[col] for col in sorted(registered_mapping)})
    _render_metric_cards([
        ("批次 id", bid),
        ("rows_total（预览计数）", registered_rows),
        ("状态", "running"),
        ("全量行数", len(rows)),
    ])

    if registered_mapping is not None:
        if st.button(
            "🔍 干跑预览（零写库）",
            key=f"{KEY_IMPORT_PREFIX}dryrun_btn",
            help="plan_import 校验表 ＋ run_import(dry_run=True) 变更 diff；只读，零写库。",
        ):
            plan = plan_import(rows, registered_mapping)
            dry = run_import(rows, registered_mapping, int(operator or 0), dry_run=True)
            st.session_state[PLAN_KEY] = plan
            st.session_state[PREVIEW_KEY] = dry["preview"] if dry["ok"] else []
        plan_stash = st.session_state.get(PLAN_KEY)
        preview_stash = st.session_state.get(PREVIEW_KEY)
        if isinstance(plan_stash, dict):
            _render_dry_run_tables(
                plan_stash, preview_stash if isinstance(preview_stash, list) else [],
            )

        can_execute = bool(rows) and isinstance(operator, int) and operator > 0
        if st.button(
            "🚀 执行写入（dry_run=False，写库）",
            type="primary",
            disabled=not can_execute,
            key=f"{KEY_IMPORT_PREFIX}execute_btn",
            help="run_import(dry_run=False) 逐行 UPSERT definitions → finish_batch 记真实"
                 "行数 → revert_log 持久化（import_revert_log 伴生表），回滚按钮对本批次"
                 "启用（跨会话可回滚）。",
        ):
            try:
                guards.require_dict_admin()
            except PermissionError as e:
                st.error(f"⛔ {e}")
                return
            result = run_import(rows, registered_mapping, int(operator or 0),
                                dry_run=False)
            if not result["ok"]:
                st.error(f"执行中止：{result['error']}")
                for err in result["mapping_errors"]:
                    st.error(f"映射错误：{err}")
            else:
                st.session_state[REVERT_LOG_KEY] = result["revert_log"]
                st.session_state[REVERT_BATCH_KEY] = bid
                st.session_state[EXEC_RESULT_KEY] = {
                    "batch_id": bid,
                    "rows_total": result["rows_total"],
                    "rows_ok": result["rows_ok"],
                    "rows_rejected": result["rows_rejected"],
                    "revert_count": len(result["revert_log"]),
                }
                if result["rejected"]:
                    st.dataframe(
                        pd.DataFrame([
                            {"行号": r["row_index"] + 1, "拒绝原因": r["reason"]}
                            for r in result["rejected"]
                        ]),
                        use_container_width=True,
                    )
                if finish_batch(bid, result["rows_total"], result["rows_ok"],
                                result["rows_rejected"]):
                    persisted = persist_revert_log(bid, result["revert_log"])
                    if persisted:
                        st.success(
                            f"批次 {bid} 执行写入完成：rows_ok={result['rows_ok']}，"
                            f"rows_rejected={result['rows_rejected']}；revert_log "
                            f"{len(result['revert_log'])} 条已持久化（import_revert_log）"
                            " —— 「回滚」按钮对本批次启用，跨会话可回滚。"
                        )
                    else:
                        st.warning(
                            f"批次 {bid} 已记账，但 revert_log 持久化失败（数据库不可用等）"
                            "—— 本会话内仍可按会话暂存的事件回滚，跨会话回滚不可用，"
                            "请核对服务端日志。"
                        )
                    for key in _WIZARD_SESSION_KEYS:
                        st.session_state.pop(key, None)
                else:
                    st.error(
                        "写入已执行但 finish_batch 记账失败（批次不在 running 态或数据库"
                        "不可用）—— 批次未 finished 则无法回滚，请核对 import_batches。"
                    )

    if st.button(
        "🧾 不写入业务表，直接记账完成（rows_ok=0）",
        key=f"{KEY_IMPORT_PREFIX}finish_zero_btn",
        help="finish_batch(rows_total=预览计数, rows_ok=0, rows_rejected=0)——放弃写入"
             "只结账（放弃口径如实留痕）。",
    ):
        if finish_batch(bid, registered_rows, 0, 0):
            st.success(
                f"批次 {bid} 已记账完成（rows_ok=0 —— 未写业务表，revert_log 为空，"
                "回滚对本批次无事可做）。"
            )
            for key in _WIZARD_SESSION_KEYS:
                st.session_state.pop(key, None)
        else:
            st.error("记账失败：批次不存在、已非 running 态或数据库不可用。")
    if st.button("🧹 重置向导", key=f"{KEY_IMPORT_PREFIX}reset_btn",
                 help="清空本页会话中的批次登记状态（不影响已登记的台账行；已写入的"
                      "业务数据与 revert_log 留痕不受影响）。"):
        for key in _WIZARD_SESSION_KEYS:
            st.session_state.pop(key, None)
        st.rerun()


def _render_batch_list() -> None:
    """已登记批次列表＋回滚按钮（**优先读持久化事件**，跨会话回滚成立）。

    事件来源两态（批次 6-T）：伴生表 import_revert_log 有持久化记录 →
    rollback_batch(batch_id) 由数据层读表回滚（跨会话成立）；无持久化记录
    才回退本会话暂存的 revert_log（rollback_batch(batch_id, revert_log)
    显式传参的兼容口径）—— 两者皆无的批次按钮禁用并如实注明。
    """
    st.markdown(
        f"<h3 style='margin-top:32px;'>🗂️ 已登记批次（最近 {BATCH_LIST_LIMIT} 条）"
        f"</h3>",
        unsafe_allow_html=True,
    )
    exec_result = st.session_state.get(EXEC_RESULT_KEY)
    if isinstance(exec_result, dict) and exec_result.get("batch_id"):
        st.info(
            f"上次执行写入：批次 #{exec_result.get('batch_id')} rows_ok="
            f"{exec_result.get('rows_ok')}，rows_rejected={exec_result.get('rows_rejected')}，"
            f"revert_log {exec_result.get('revert_count')} 条（已持久化，回滚见下）。"
        )
    batches = _list_recent_batches()
    if not batches:
        st.info("暂无批次记录（import_batches 为空、未建表或数据库不可用；"
                "表由 ensure_dict_admin_tables 幂等创建）。")
        return

    table_rows = [
        {
            "批次 id": b.get("id"),
            "文件名": b.get("file_name"),
            "sha256（前 12 位）": str(b.get("file_sha256") or "")[:12] + "…",
            "目标域": b.get("target_domain"),
            "行数": b.get("rows_total"),
            "rows_ok": b.get("rows_ok"),
            "拒绝": b.get("rows_rejected"),
            "状态": b.get("status"),
            "操作人": b.get("operator"),
            "登记时间": b.get("created_at"),
        }
        for b in batches
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

    finished = [b for b in batches if str(b.get("status")) == "finished"]
    if not finished:
        st.caption("当前没有 finished 批次（回滚的合法起点）。")
        return
    options = {
        f"批次 #{b.get('id')} · {b.get('file_name')}": int(b.get("id") or 0)
        for b in finished
    }
    selected_label = st.selectbox(
        "选择要回滚的批次", list(options.keys()),
        key=f"{KEY_IMPORT_PREFIX}rollback_select",
    )
    selected_bid = int(options.get(selected_label, 0))
    # 优先读持久化事件（跨会话成立）；无持久化才回退本会话暂存（兼容口径）
    persisted_events = _load_persisted_revert_log(selected_bid)
    session_events = st.session_state.get(REVERT_LOG_KEY) or []
    session_bid = st.session_state.get(REVERT_BATCH_KEY)
    use_persisted = bool(persisted_events)
    use_session = (not use_persisted) and bool(session_events) and session_bid == selected_bid
    can_rollback = use_persisted or use_session
    if st.button(
        "↩️ 回滚选中批次",
        disabled=not can_rollback,
        key=f"{KEY_IMPORT_PREFIX}rollback_btn",
        help="rollback_batch：更新行按 old_values 恢复旧值；新增行因 definitions "
             "无 status 列仅留痕不作废（不物理 DELETE）。有持久化日志的批次跨会话"
             "可回滚。",
    ):
        if use_persisted:
            # 事件以伴生表为准：不显式传参，由数据层在同一事务内读表回滚
            ok = rollback_batch(selected_bid)
        else:
            ok = rollback_batch(selected_bid, list(session_events))
        if ok:
            # RV25-6（RV12-2 漏网收口）：直渲染成功提示会随本轮 rerun 丢弃
            # —— 统一 ui_kit.flash 进会话队列，下一轮渲染由
            # pop_and_render_flash 弹出（全仓收口口径，禁直渲染成功族回潮）。
            ui_kit.flash(
                f"批次 {selected_bid} 已回滚（rolled_back）：更新行按 old_values 恢复"
                "旧值；新增行因 definitions 无 status 列仅留痕不作废（平台纪律："
                "不物理 DELETE）。"
            )
            st.session_state.pop(REVERT_LOG_KEY, None)
            st.session_state.pop(REVERT_BATCH_KEY, None)
            st.session_state.pop(EXEC_RESULT_KEY, None)
            st.rerun()
        else:
            st.error("回滚失败：批次不在 finished 态、revert_log 校验未过或数据库不可用"
                     "（详见服务端日志）。")
    if can_rollback:
        source = (
            f"持久化回滚日志 {len(persisted_events)} 条（import_revert_log，跨会话可回滚）"
            if use_persisted
            else "本会话刚执行写入（revert_log 暂存会话，持久化未命中的兜底口径）"
        )
        st.caption(
            f"回滚已对本批次启用（{source}）：更新行恢复旧值；新增行仅"
            "留痕不作废（definitions 无 status 列，rollback_batch 既有口径）。"
        )
    else:
        st.caption(
            "回滚按钮仅对「已持久化回滚日志」或「本会话刚执行写入且已记账」的批次"
            "启用：执行写入成功后 revert_log 会持久化进伴生表 import_revert_log"
            "（跨会话回滚成立）；两者皆无（如 rows_ok=0 的空批次、持久化失败且"
            "会话已丢失）则无回滚凭据，按钮如实禁用。"
        )


def render_import_page() -> None:
    """数据导入向导（三步）。**role gate 在函数入口**（§15 导入同权）：
    仅词典管理员 —— 过渡期 role == "admin"，升级后 roles 含 dict_admin。"""
    user = _current_user()
    if not user:
        st.warning("请先登录。")
        return
    if not _is_dict_admin(user):
        st.error("⛔ 数据导入仅词典管理员可用（导入同权，规范 §15）。")
        return

    st.markdown(f"<h1 style='{HEADER_H1}'>🧰 数据导入向导</h1>", unsafe_allow_html=True)
    st.caption(
        "三步向导：① 上传 → ② 预览与指纹 → ③ 登记批次＋列映射。批次 5 起业务写入"
        "已接线（src/import_engine.py）：默认干跑预览（零写库），显式「执行写入」才"
        "逐行 UPSERT definitions（中文释义/音标，cluster_id 保留现值，可回滚）；"
        "oald_senses 追加写入不支持（批次 6 评审）。仅词典管理员（§15 导入同权）。"
    )

    st.markdown("<h3>① 上传文件</h3>", unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "词条文档（xlsx / csv；docx 阶段 2 接入）",
        type=list(UPLOAD_TYPES),
        key=f"{KEY_IMPORT_PREFIX}uploader",
    )
    left, right = st.columns(2)
    with left:
        target_domain = st.text_input(
            "目标域 target_domain（≤40 字符）",
            value="definitions",
            max_chars=40,
            key=f"{KEY_IMPORT_PREFIX}target_domain",
            help="灌入的目标域。本页业务写入固定写 definitions 词目层（中文释义/音标，"
                 "按 verb 键 UPSERT）；custom_values 等其他目标域留后续版本，此处值同时"
                 "作为 import_batches 台账留痕。",
        )
    with right:
        project_id = st.number_input(
            "词典项目 id", min_value=1, value=1, step=1,
            key=f"{KEY_IMPORT_PREFIX}project_id",
            help="import_batches.project_id（词典项目软引用；项目清单见主编驾驶舱）。",
        )

    if uploaded is None:
        st.info("请先上传 xlsx / csv 文件开始预览（单文件 ≤ 20MB，MVP 解析上限；"
                "更大的首建批量走 CLI 灌库脚本）。")
        _render_batch_list()
        return

    data = uploaded.getvalue()
    if len(data) > MAX_UPLOAD_BYTES:
        st.error(f"文件 {len(data) / 1024 / 1024:.1f}MB 超过 20MB 上限，"
                 "请拆分后上传或改走 CLI 灌库脚本。")
        _render_batch_list()
        return

    st.markdown("<h3>② 预览与指纹</h3>", unsafe_allow_html=True)
    preview = _render_preview(data, uploaded.name)
    if preview is None:
        _render_batch_list()
        return
    rows_total, columns = preview

    st.markdown("<h3>③ 登记批次＋列映射写入</h3>", unsafe_allow_html=True)
    rows_df = _read_tabular(data, uploaded.name)
    rows = rows_df.to_dict("records") if rows_df is not None else []
    _render_register_step(
        user=user,
        file_name=uploaded.name,
        sha=_sha256_bytes(data),
        rows_total=rows_total,
        target_domain=(target_domain or "").strip() or "definitions",
        project_id=int(project_id),
        columns=columns,
        rows=rows,
    )
    _render_batch_list()


# ============================================
# 页面渲染：词条浏览器
# ============================================

def _render_sense_lines(verb: str, senses: List[Dict[str, Any]]) -> None:
    """单个词目的义项列表（前 10 条 + 总计数；st.markdown 非 HTML 输出由
    Streamlit 自动转义，不手工二次转义避免实体直显）。

    每条义项下方内嵌「义项脊柱」expander（批次 4 Agent M）：懒加载 ——
    expander 用 on_change="rerun" 接线，点开才触发重跑渲染脊柱七段
    （streamlit ≥1.57 的 expander.open 惰性语义），收起时零取数。
    """
    total = len(senses)
    if total <= 0:
        st.caption("该词目暂无 oald_senses 义项记录（如实标注，不编造）。")
        return
    for s in senses[:SENSES_SHOW_LIMIT]:
        index = str(s.get("sense_index") or "")
        definition = str(s.get("definition") or "（释义为空）")
        grammar = str(s.get("grammar") or "").strip() or "—"
        st.markdown(f"- **S{index}** · {definition} · 语法码：{grammar}")
        sense_id = s.get("id")
        if sense_id is None:
            continue  # 行缺义位锚（异常数据）时只少一个脊柱入口，不打崩列表
        with st.expander(
            f"🧬 义项脊柱 · S{index}（展开即见标注留痕 / 信度 / 簇 / 模板 / 媒体）",
            key=f"{KEY_BROWSER_PREFIX}spine_{int(sense_id)}",
            on_change="rerun",
        ) as spine_expander:
            if spine_expander.open:
                sense_spine.render_sense_spine(int(sense_id))
    if total > SENSES_SHOW_LIMIT:
        st.caption(
            f"共 {total} 条义项，显示前 {SENSES_SHOW_LIMIT} 条"
            "（义项明细的标注操作在标注平台页）。"
        )


def render_browser_page() -> None:
    """词条浏览器（登录即可看，viewer 可读）。**role gate 在函数入口**。"""
    user = _current_user()
    if not user:
        st.warning("请先登录。")
        return

    st.markdown(f"<h1 style='{HEADER_H1}'>📖 词条浏览器</h1>", unsafe_allow_html=True)
    st.caption(
        "管理视角的词条列表（只读）：词目 / 义项数 / coverage（待补，如实标注） / "
        "来源分级；行展开即见义项脊柱（每条义项一个 🧬 expander，点开懒加载七段"
        "全链留痕）。完整 coverage 覆盖阶梯在批次 3 与后续版本接入。"
    )

    left, right = st.columns([3, 1])
    with left:
        query = st.text_input(
            "词目搜索（LIKE 前缀/子串；% _ 按字面匹配）",
            max_chars=MAX_TERM_LEN,
            key=f"{KEY_BROWSER_PREFIX}query",
        )
    with right:
        match_mode = st.radio(
            "匹配方式", ("前缀匹配", "子串匹配"), horizontal=True,
            key=f"{KEY_BROWSER_PREFIX}match_mode",
        )
    prefix_only = str(match_mode).startswith("前缀")
    page_input = st.number_input(
        "页码（每页 20 条）", min_value=1, value=1, step=1,
        key=f"{KEY_BROWSER_PREFIX}page",
    )

    if not str(query or "").strip():
        st.info("输入词目关键字开始检索（如 run —— 当前匹配 definitions.verb 词目列）。")
        return

    rows, total, page = _search_definitions(query, prefix_only, int(page_input))
    if not rows:
        st.warning("无匹配词目（或数据库不可用 / 词表未灌入）。")
        return
    total_pages = _total_pages(total, PAGE_SIZE)
    st.caption(
        f"共 {total} 个词目 · 第 {page} / {total_pages} 页 · 每页 {PAGE_SIZE} 条"
        "（coverage 列「待补」是如实标注 —— 覆盖阶梯尚未接入浏览器）"
    )

    senses_map = _senses_for_verbs([str(r.get("verb")) for r in rows])
    for row in rows:
        verb = str(row.get("verb") or "")
        sense_total = int(row.get("sense_total") or 0)
        source = str(row.get("source_label") or "").strip() or COVERAGE_PENDING
        with st.expander(f"📎 {verb} · 义项 {sense_total} 条 · 来源 {source}"):
            _render_sense_lines(verb, senses_map.get(verb, []))
