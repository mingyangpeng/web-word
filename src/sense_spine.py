"""义项脊柱（Agent M，批次 4）—— 点开任一义位即见全链留痕的七段视图。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D「三版本脊柱」（
annotation_submissions → cs_cluster_runs → definition_versions）与 §9 U
「义项脊柱（跨区中枢）：谁标的 → α → 簇 → 模板 → 释义版本 → 媒体 → 定制属性」；
契约：docs/spec/阶段1施工规范.md §7 批次 4 Agent M 行。

是什么（七段，每段独立取数、独立降级，绝不编数）：
  ① 义项信息    oald_senses（sense_index/definition/grammar/examples）——
                本模块私有参数化只读查询（顺带联 definitions 取 verb，
                供 ④⑤ 做语义分析库的义位映射）；
  ② 标注留痕    annotation_flow.get_submissions_for_sense（三类任务逐类取，
                coder 显示名经 users 表 LEFT JOIN 随行返回）＋payload 摘要；
  ③ 信度        reliability_runs 该范畴每类任务的最近一次运行
                （overall_alpha / per_feature）——本模块私有只读查询；
                **α 为范畴×任务级口径，非单义位**（段头固定注明）；
  ④ 簇归属      cs_cluster_members → cs_clusters 最近运行（簇名/成员数）＋
                典型性 tier（cluster_analysis.compute_medoid_ranking 的
                medoid 距离三分位）；簇数据挂在 cs_senses（语义分析研究层），
                与义位锚 oald_senses.id 不同库位 —— 先经 ⑤同款映射解析
                cs_senses.id，解析不到即「未在建模覆盖内」；
  ⑤ 模板预览    template_engine.instantiate_template（确定性引擎，不调 LLM）
                ——义位不在试点库时占位「未在建模覆盖内」；
  ⑥ 媒体        media_db.list_assets_for_anchor('sense', id)（绑定＋资产
                两级状态随行展示）；
  ⑦ 定制属性    dict_admin_db.get_values_for_anchor('sense', id)。

数据链（全部只读调用批次 1/3 数据层；本模块不建表、不写任何业务表）：
  义位唯一锚 = oald_senses.id（架构规范 §6）；语义分析研究层经
  definitions.verb + oald_senses.sense_index ↔ cs_lexemes.lemma +
  cs_senses.sense_no 映射（范畴代号解析复用 cluster_analysis 的
  PACK_TO_STUDY_CODE 对应关系：包名 motion ↔ 研究代号 RUN）。

接口（契约 §7-Agent M）：
  render_sense_spine(sense_id, category="motion", language="en") -> None
  _spine_sections(sense_id, category, language)
      -> list[SpineSection(title, body, missing_reason)] —— 纯编排：
      body 非 None 即有数文本；body 为 None 即缺数灰段（渲染层给
      「暂无数据：missing_reason」）。取数一律经模块级 _fetch_* /
      _resolve_* 薄适配层，测试 monkeypatch 这些名字即可构造全缺数 /
      部分有数 / 脏数据场景，不需要真实数据库。
  批次 19 追加渲染件（有 st. 副作用，不入纯编排）：
      _render_bookmark_toggle(sense_id) / _render_my_notes_section(sense_id)
      —— 登录态专属（会话门 _context_uid = user_context_db
      ._resolve_user_id 单一实现），测试 monkeypatch 数据层与 st 桩。

降级（每段独立 try/except，段头照常渲染）：
  数据层函数自身已把数据库不可用折叠为 []/None（只记日志），本模块把
  每段再包一层 try/except —— 任何脏数据（畸形 JSON、None 字段、类型
  漂移）都折叠为该段的缺数灰段或降级文本，绝不让单段异常打崩整页；
  缺数原因如实写「暂无数据：<原因>」，不猜测、不编数。

安全规则：
  1. 私有 SQL 一律参数化（本模块 7 条只读查询：义项行、信度最近运行、
     categories 代号清单、cs_senses 映射、簇信息、cs_senses 现状
     status/merged_into、R5-5 标注留痕批量（task_type IN 一次取回，替代
     逐任务类型 3 查询），其余全走数据层函数）；
  2. 段头为模块内静态文案（HTML 由 design_system 样式渲染）；段体走
     st.markdown（unsafe_allow_html=False），由 Streamlit 自动转义，
     与 src/data_pages.py 的转义口径一致（不手工二次转义避免实体直显）。

批次 6（G3 merged 消费收口，施工规范 §9）：cs_senses.status='merged'
（分立复核 merge 落地，去向记 merged_into）的义位在脊柱如实收口 ——
  ① 段追加警示「⚠️ 该义位已并入 → #target（分立复核定稿）」（附按目标 id
    检索跳转的提示）；
  ④⑤ 段不再取簇信息/实例化模板，改「已并入，不参与聚类/模板」占位
    （簇归属与典型性、模板释义的消费流向并入目标义位）。
merged 状态经 _fetch_cs_sense_state（cs_senses 现状，只读）随 ④⑤ 共用的
cs_sense 映射取得；映射失败/行缺失/列缺失（迁移未跑）时按普通义位渲染
（不猜 merged，绝不把取数故障谎报成「已并入」）。

批次 19（用户上下文域 UI 落地，施工规范批次 19）：七段静态面之外新增两件
**登录态专属**的私人上下文控件（用户上下文域 = 登录态功能，fail-closed
口径的 UI 表达 —— 未登录整段/整钮不渲染，而不是渲染出灰提示）：
  * 📌 书签 toggle（段前动作位）：user_bookmarks 锚 'sense'+str(sense_id)，
    已收藏态经 get_bookmark 单条直读判定（批次 19 补读面，不走全量）；
    未收藏「📌 收藏本义位」→ upsert_bookmark（title=义位标签），已收藏
    「📍 已收藏·取消」→ delete_bookmark。own-rows-only（user_id 会话派生，
    天然只读写自己的），六角色皆可用（私人数据）。书签列表独立页归第二批
    （list_bookmarks 消费入口建议：侧边栏「继续/收藏」区或账号管理页，
    见 user_context_db.list_bookmarks docstring）。
  * 📝 我的笔记段（⑦ 定制属性段之后，七段面末尾）：user_notes 该用户 ×
    该义位的私人笔记 —— 已存笔记显示（updated_at 时间戳）＋ text_area
    编辑 ＋「💾 保存笔记」（upsert_note；'' 提交=显式清空但保留行，RV2-3
    第 3 类口径）＋「🗑 删除笔记」（delete_note）。
  两者成功提示一律 ui_kit.flash + st.rerun（RV12：rerun 会丢本轮渲染，
  禁止 st.success+st.rerun 回潮）；失败 st.error 留在本轮不 rerun。
  控件键一律带 sense_id 后缀（同一词条页可展开多个义位脊柱，widget 键
  必须互斥）。两件都走 _render_* 渲染层（有 st. 副作用，不入
  _spine_sections 纯编排——SpineSection 是纯文本载荷，塞不进 widget）；
  会话门复用 user_context_db._resolve_user_id 单一实现（UI 门与数据层门
  同一口径，无第二套判定）。
"""

import json
import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import streamlit as st

from src import annotation_flow, media_db, ui_kit, user_context_db
from src.annotation_flow import TASK_TYPE_LABELS  # R6-8：单一导出
from src.db_utils import as_int as _as_int  # R6-4：公共小件单一实现点
from src.cluster_analysis import (
    PACK_TO_STUDY_CODE,
    TIER_LABELS,
    compute_medoid_ranking,
)
from src.dict_admin_db import get_values_for_anchor
from src.design_system import HEADER_H4
from src.mysql_db import get_db_cursor
from src.template_engine import instantiate_template
from src.user_context_db import MAX_NOTE_LEN, _resolve_user_id as _context_uid

logger = logging.getLogger(__name__)

# ============================================
# 常量（段头文案与展示映射）
# ============================================

# ② 标注留痕：任务类型中文 —— R6-8 收进 annotation_flow.TASK_TYPE_LABELS
# 单一导出（与 collab_pages 同源同值），本模块不再自留一份。

# ⑥ 媒体：kind / purpose 的中文展示映射（media_db 常量）
KIND_LABELS = {"image": "图片", "audio": "音频", "video": "视频"}
PURPOSE_LABELS = {
    "pronunciation": "发音",
    "illustration": "释义配图",
    "example_media": "例证媒体",
    "schema_diagram": "图式示意图",
}

# ④ 簇归属：tier → 中文（cluster_analysis.TIER_LABELS 同源；缺项回退原文）
_TIER_LABELS_FALLBACK = dict(TIER_LABELS)

# 批次 6 merged 消费：cs_senses.status 分立落地取值
# （cluster_analysis.SPLIT_STATUS_VALUES[0] 同源；此处独立常量避免环形 import）
_MERGED_STATUS = "merged"

# payload 摘要与例句展示的截断上限（防长文本撑爆脊柱段）
_SUMMARY_MAX_LEN = 120
_EXAMPLES_SHOW = 3

# 批次 19 用户上下文域 UI：段头文案与笔记展示截断（全文在下方编辑框，
# 展示行截断防 50000 字符笔记撑爆脊柱段；截断是有损展示不是丢数据）
_MY_NOTES_TITLE = "📝 我的笔记（user_notes · 私人）"
_NOTE_DISPLAY_MAX_LEN = 500

# 书签 toggle 与笔记控件键前缀（键带 sense_id 后缀：同一词条页可展开
# 多个义位脊柱，widget 键必须互斥）
_BOOKMARK_KEY_ON = "sense_spine_bm_on_{sid}"
_BOOKMARK_KEY_OFF = "sense_spine_bm_off_{sid}"
_NOTE_FORM_KEY = "sense_spine_note_form_{sid}"
_NOTE_INPUT_KEY = "sense_spine_note_input_{sid}"


class SpineSection(NamedTuple):
    """脊柱一段的渲染载荷（契约 sketch 的 list[tuple[str, str|None]] 之类形态）。

    body 非 None：有数，渲染层 st.markdown(body)（Streamlit 自动转义）；
    body 为 None：缺数灰段，渲染层 st.caption(f"暂无数据：{missing_reason}")。
    missing_reason 恒非空字符串（有数段给空串占位，便于测试断言）。
    """

    title: str
    body: Optional[str]
    missing_reason: str


# ============================================
# 展示口径纯函数（无 st./DB 依赖，tests 直接测）
# ============================================

def _truncate(text: Any, limit: int = _SUMMARY_MAX_LEN) -> str:
    """任意值 → 截断字符串（脏值兜底 str()；None → 空串）。"""
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _format_alpha(value: Any) -> str:
    """α 展示口径：None/脏值 → '—'（未产出），数值 → 三位小数。"""
    try:
        if value is None:
            return "—"
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "—"


def _parse_json_dict(raw: Any) -> Optional[Dict[str, Any]]:
    """JSON 列 → dict（per_feature 等；畸形/非 dict 返回 None，不抛）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_json_list(raw: Any) -> Optional[List[Any]]:
    """JSON 列 → list（oald_senses.examples；畸形/非 list 返回 None）。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def _payload_summary(task_type: Any, payload: Any) -> str:
    """payload → 一行人读摘要（纯函数；脏 payload 兜底截断原文）。

    admission → 「准入=Y；图式=…；对齐=…；需复核=…」；feature_coding →
    「编码 N 项：P1=1 …」；alignment → 「对齐=…」。其余/畸形 → 截断原文。
    """
    prefix = TASK_TYPE_LABELS.get(str(task_type), str(task_type or "未知任务"))
    if not isinstance(payload, dict):
        return f"{prefix}：{_truncate(payload) or '（空 payload）'}"
    parts: List[str] = []
    if task_type == "admission":
        labels = (("admission", "准入"), ("schema", "图式"), ("alignment", "对齐"))
        for key, label in labels:
            if key in payload:
                parts.append(f"{label}={_truncate(payload.get(key), 40)}")
        if "needs_review" in payload:
            parts.append(f"需复核={payload.get('needs_review')}")
    elif task_type == "feature_coding":
        features = payload.get("features")
        if isinstance(features, dict):
            shown = " ".join(
                f"{code}={features[code]}" for code in list(features)[:6]
            )
            more = "…" if len(features) > 6 else ""
            parts.append(f"编码 {len(features)} 项：{shown}{more}")
        else:
            parts.append(f"payload={_truncate(payload, 60)}")
    elif task_type == "alignment":
        parts.append(f"对齐={_truncate(payload.get('alignment'), 60)}")
    if not parts:
        fallback = _truncate(payload, 80)
        if fallback in ("", "{}"):
            fallback = "（空 payload）"
        parts.append(fallback)
    return f"{prefix}：" + "；".join(parts)


def _tier_label(tier: Any) -> str:
    """tier 枚举 → 中文（原型/次典型/边缘；未知值回退原文）。"""
    key = str(tier or "")
    return _TIER_LABELS_FALLBACK.get(key, key) or "—"


def _merged_target_suffix(status: Any, merged_into: Any) -> Optional[str]:
    """cs_senses 现状 → merged 去向文案核（纯函数，可测；批次 6 G3 消费收口）。

    status='merged'（大小写/空白容错）→「已并入 → #N」；merged_into 缺失
    「已并入（merged_into 去向待补录）」—— 不猜去向 id。非 merged → None
    （调用方按普通义位渲染）。
    """
    if str(status or "").strip().lower() != _MERGED_STATUS:
        return None
    target = _as_int(merged_into)
    if target is not None:
        return f"已并入 → #{target}"
    return "已并入（merged_into 去向待补录）"


def _study_code_for(category: Any, available_codes: List[str]) -> Optional[str]:
    """范畴参数 → 语义分析 categories.code（纯函数；与 cluster_analysis
    _resolve_study_code 同口径，此处独立实现以便无库单测）。

    先按 categories.code 大小写不敏感直配（兼容 RUN 与 run），再按
    PACK_TO_STUDY_CODE 把包名（motion）映射到研究代号（RUN）。
    """
    cat = str(category or "").strip()
    if not cat:
        return None
    codes = {str(c).upper(): str(c) for c in available_codes if c}
    if cat.upper() in codes:
        return codes[cat.upper()]
    mapped = PACK_TO_STUDY_CODE.get(cat.lower())
    if mapped and mapped.upper() in codes:
        return codes[mapped.upper()]
    return None


# ============================================
# 取数薄适配层（模块级名字，测试 monkeypatch 目标；SQL 一律参数化）
# ============================================

def _fetch_sense_row(sense_id: int) -> Optional[Dict[str, Any]]:
    """① 义项行（**只读**）：oald_senses 主字段 + definitions.verb（④⑤
    映射用）。不存在 / 数据库不可用返回 None（数据链口径：词条浏览器
    的义项明细同源）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT os.id, os.sense_index, os.definition, os.grammar,
                          os.examples, os.sense_group, os.is_idiom,
                          d.verb
                   FROM oald_senses os
                   JOIN definitions d ON d.id = os.definition_id
                   WHERE os.id = %s""",
                (int(sense_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:  # noqa: BLE001 — 降级不崩（页面给缺数灰段）
        logger.error(f"sense_spine: 义项行查询失败（id={sense_id}）: {e}")
        return None


def _fetch_submissions_for_spine(sense_id: int) -> List[Dict[str, Any]]:
    """② 标注留痕（**只读**；R6-4 改名 _fetch_submissions_for_spine，与
    reliability._fetch_submissions 同名不同义消歧）。

    R5-5（N+1 修复）：三类任务原逐类调 annotation_flow.get_submissions_for_sense
    （3 条同构查询）→ 现一次 task_type IN 批量取回（同一 SELECT 列与
    LEFT JOIN users，组间按 TASK_TYPES 顺序拼接、组内 coder_id, id 序，
    行转换复用 annotation_flow 的单一实现 —— 输出与逐类拼接逐字段一致）。
    批量失败回退逐类查询（旧行为兜底；单类失败不拖垮其余类）。

    reviewer+ 口径的页面才嵌脊柱，调用方负责角色门；coder 显示名经 users
    表 LEFT JOIN 随行返回。数据库不可用返回 []。
    """
    try:
        task_types = annotation_flow.TASK_TYPES
        placeholders = ", ".join(["%s"] * len(task_types))
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT s.id, s.category, s.sense_id, s.task_type, s.coder_id, "
                "s.payload, s.ai_assisted, s.status, s.submitted_at, "
                "u.username, u.display_name "
                "FROM annotation_submissions s "
                "LEFT JOIN users u ON u.id = s.coder_id "
                f"WHERE s.sense_id = %s AND s.task_type IN ({placeholders}) "
                "ORDER BY s.coder_id, s.id",
                (int(sense_id), *task_types),
            )
            rows = cursor.fetchall()
    except Exception as e:  # noqa: BLE001 — 批量失败回退逐类查询（旧行为）
        logger.warning(f"sense_spine: 标注留痕批量查询失败，回退逐任务类型查询: {e}")
        rows = []
        for task_type in annotation_flow.TASK_TYPES:
            try:
                rows.extend(
                    annotation_flow.get_submissions_for_sense(int(sense_id), task_type)
                )
            except Exception as e2:  # noqa: BLE001 — 单任务失败不拖垮其余任务
                logger.error(f"sense_spine: 标注留痕查询失败（task={task_type}）: {e2}")
        return rows
    order = {t: i for i, t in enumerate(annotation_flow.TASK_TYPES)}
    rows = sorted(rows, key=lambda r: order.get(r.get("task_type"),
                                                len(order)))  # 稳定排序：组内保持 coder_id, id 序
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = annotation_flow._submission_row_to_dict(row)
        item["username"] = row.get("username")
        item["display_name"] = row.get("display_name")
        out.append(item)
    return out


def _fetch_latest_reliability(category: str) -> List[Dict[str, Any]]:
    """③ 信度（**只读**）：reliability_runs 该范畴每类任务的最近一次运行
    （MAX(id) per task_type；category 存包名，DDL 默认 motion）。
    表未建 / 数据库不可用返回 []。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT r.task_type, r.overall_alpha, r.per_feature,
                          r.n_coders, r.n_units, r.computed_at
                   FROM reliability_runs r
                   WHERE r.category = %s
                     AND r.id IN (SELECT MAX(id) FROM reliability_runs
                                  WHERE category = %s GROUP BY task_type)
                   ORDER BY r.task_type""",
                (str(category), str(category)),
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.error(f"sense_spine: 信度最近运行查询失败（category={category}）: {e}")
        return []


def _fetch_category_codes() -> List[str]:
    """④⑤ 映射辅助（**只读**）：categories.code 清单（语义分析 8 表未灌
    返回 []）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT code FROM categories")
            return [str(r["code"]) for r in cursor.fetchall() if r.get("code")]
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.warning(f"sense_spine: categories 清单查询失败: {e}")
        return []


def _find_cs_sense_id(study_code: str, language: str, lemma: str,
                      sense_no: str) -> Optional[int]:
    """④⑤ 映射辅助（**只读**）：oald_senses（verb/sense_index）→ cs_senses.id。

    映射键 = (categories.code, cs_lexemes.language, cs_lexemes.lemma,
    cs_senses.sense_no)；多命中取最小 id（确定性）。查无 / 数据库不可用
    返回 None（调用方按「未在建模覆盖内 / 不可用」口径降级）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.id FROM cs_senses s
                   JOIN cs_lexemes l ON s.lexeme_id = l.id
                   JOIN categories c ON l.category_id = c.id
                   WHERE c.code = %s AND l.language = %s
                     AND l.lemma = %s AND s.sense_no = %s
                   ORDER BY s.id LIMIT 1""",
                (str(study_code), str(language), str(lemma), str(sense_no)),
            )
            row = cursor.fetchone()
            return int(row["id"]) if row else None
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.error(
            f"sense_spine: cs_senses 映射查询失败（{study_code}/{language}/"
            f"{lemma}/{sense_no}）: {e}"
        )
        return None


def _fetch_cluster_info(cs_sense_id: int, language: str) -> Optional[Dict[str, Any]]:
    """④ 簇信息（**只读**）：cs_cluster_members → cs_clusters 最近运行
    （r.id 最大即最新；簇名/簇号/成员数/运行版本）。无簇 / 数据库不可用
    返回 None。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT c.id AS cluster_id, c.cluster_no,
                          c.name AS cluster_name, c.size AS cluster_size,
                          r.id AS run_id, r.version
                   FROM cs_cluster_members m
                   JOIN cs_clusters c ON m.cluster_id = c.id
                   JOIN cs_cluster_runs r ON c.run_id = r.id
                   WHERE m.sense_id = %s AND r.language = %s
                   ORDER BY r.id DESC LIMIT 1""",
                (int(cs_sense_id), str(language)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.error(f"sense_spine: 簇信息查询失败（cs_sense_id={cs_sense_id}）: {e}")
        return None


def _fetch_tier(category: str, language: str,
                cs_sense_id: int) -> Optional[Dict[str, Any]]:
    """④ 典型性（**只读**）：cluster_analysis.compute_medoid_ranking 的
    三分位 tier（gower_to_medoid / is_medoid 随行）。无覆盖 / 数据不可用
    返回 None（数据层口径：范畴或运行不存在 → []）。"""
    try:
        ranking = compute_medoid_ranking(category=str(category),
                                         language=str(language))
    except Exception as e:  # noqa: BLE001 — scipy/包缺失等降级不崩
        logger.warning(f"sense_spine: 典型性计算失败（category={category}）: {e}")
        return None
    target = int(cs_sense_id)
    for cluster in ranking:
        for member in cluster.get("members") or []:
            if _as_int(member.get("sense_id")) == target:
                return {
                    "tier": member.get("tier"),
                    "is_medoid": bool(member.get("is_medoid")),
                    "gower_to_medoid": member.get("gower_to_medoid"),
                }
    return None


def _fetch_cs_sense_state(cs_sense_id: int) -> Optional[Dict[str, Any]]:
    """批次 6 merged 消费（**只读**）：cs_senses 现状 status/merged_into。

    ④⑤ 共用映射解析出的 cs_senses.id → 分立复核落地状态（merged 义位
    脊柱收口的取数源）。行不存在 / 数据库不可用 / 列缺失（迁移未跑）返回
    None —— 调用方按普通义位渲染（不猜 merged，不把取数故障谎报成状态）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, status, merged_into FROM cs_senses WHERE id = %s",
                (int(cs_sense_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "status": (str(row["status"])
                           if row.get("status") is not None else None),
                "merged_into": (int(row["merged_into"])
                                if row.get("merged_into") is not None else None),
            }
    except Exception as e:  # noqa: BLE001 — 降级不崩（merged 状态未知按普通义位）
        logger.warning(f"sense_spine: cs_senses 现状查询失败（id={cs_sense_id}）: {e}")
        return None


def _fetch_media(sense_id: int) -> List[Dict[str, Any]]:
    """⑥ 媒体（**只读**）：media_db.list_assets_for_anchor('sense', id)。"""
    try:
        return media_db.list_assets_for_anchor(media_db.ANCHOR_SENSE,
                                               int(sense_id))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"sense_spine: 媒体绑定查询失败（sense_id={sense_id}）: {e}")
        return []


def _fetch_custom_values(sense_id: int) -> List[Dict[str, Any]]:
    """⑦ 定制属性（**只读**）：dict_admin_db.get_values_for_anchor('sense', id)。"""
    try:
        return get_values_for_anchor("sense", int(sense_id))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"sense_spine: 定制属性查询失败（sense_id={sense_id}）: {e}")
        return []


def _fetch_my_note(sense_id: int) -> Optional[Dict[str, Any]]:
    """📝 我的笔记取数（**只读**）：user_context_db.get_note（批次 19 补读面，
    会话派生 user_id 单条直读，未登录/无行/库不可用 → None）。"""
    try:
        return user_context_db.get_note(int(sense_id))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"sense_spine: 私人笔记读取失败（sense_id={sense_id}）: {e}")
        return None


def _fetch_my_bookmark(sense_id: int) -> Optional[Dict[str, Any]]:
    """📌 书签态取数（**只读**）：user_context_db.get_bookmark('sense', str(id))
    （批次 19 补读面，单条直读判 toggle 态，不走 list_bookmarks 全量）。"""
    try:
        return user_context_db.get_bookmark("sense", str(int(sense_id)))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"sense_spine: 书签态读取失败（sense_id={sense_id}）: {e}")
        return None


def _sense_label(sense_id: int) -> str:
    """义位显示标签（书签 title 用）：'verb · S{index}（#id）'；义项行取不到
    回退 '义位 #id'（title 可空，展示时数据层回退锚值；这里给全尽量可读）。"""
    fallback = f"义位 #{sense_id}"
    try:
        row = _fetch_sense_row(sense_id)
    except Exception as e:  # noqa: BLE001 — 取数失败按无标签
        logger.warning(f"sense_spine: 书签标题取数失败（id={sense_id}）: {e}")
        return fallback
    if not row:
        return fallback
    verb = str(row.get("verb") or "").strip()
    index = str(row.get("sense_index") or "").strip()
    parts = [p for p in (verb, f"S{index}" if index else "") if p]
    if not parts:
        return fallback
    return f"{' · '.join(parts)}（#{sense_id}）"


def _resolve_cs_sense(sense_id: int, category: str, language: str,
                      sense_row: Optional[Dict[str, Any]],
                      ) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """义位锚 → 语义分析研究层映射（④⑤ 共用）。

    Returns:
        (cs_sense_id, study_code, reason)：映射成功 → (id, code, None)；
        失败 → (None, None, 原因文案)（「未在建模覆盖内」/「不可用」两种口径，
        绝不把库故障谎报成未覆盖）。
    """
    if not sense_row or not sense_row.get("verb"):
        return None, None, "义项行不可用（oald_senses 无该义位，无法映射语义分析库）"
    study_code = _study_code_for(category, _fetch_category_codes())
    if study_code is None:
        return None, None, (
            f"范畴 {category} 未灌入语义分析库（categories 无对应研究代号）"
        )
    sense_no = str(sense_row.get("sense_index") or "").strip()
    verb = str(sense_row.get("verb") or "").strip()
    if not sense_no:
        return None, None, "义项号缺失（oald_senses.sense_index 为空），无法映射"
    cs_id = _find_cs_sense_id(study_code, language, verb, sense_no)
    if cs_id is None:
        return None, None, (
            f"未在建模覆盖内（范畴 {study_code}/{language} 试点库无词目 "
            f"{verb} 义项 {sense_no} 的对应义位）"
        )
    return cs_id, study_code, None


# ============================================
# 七段构造（每段独立 try/except；body=None 即缺数灰段）
# ============================================

def _section_sense_info(sense_id: int,
                        sense_row: Optional[Dict[str, Any]],
                        merged: Optional[str] = None) -> SpineSection:
    """① 义项信息：oald_senses 的 sense_index/definition/grammar/examples。

    批次 6：cs_senses.status='merged'（分立复核定稿并入他义位）时在段内
    追加警示行「⚠️ 该义位已并入 → #target（分立复核定稿）」（merged 参数由
    _spine_sections 经 _fetch_cs_sense_state 解析传入；None 按普通义位）。
    """
    title = "① 义项信息（oald_senses · 义位唯一锚）"
    try:
        if not sense_row:
            return SpineSection(title, None,
                                f"oald_senses 中无 id={sense_id} 的义项行"
                                "（义项不存在或数据库不可用）")
        lines = [
            f"**义项号 S{sense_row.get('sense_index')}**"
            f" · 词目 {sense_row.get('verb') or '—'}"
            f" · 语法码 {str(sense_row.get('grammar') or '').strip() or '—'}"
        ]
        definition = str(sense_row.get("definition") or "").strip()
        lines.append(f"释义：{definition or '（释义为空，如实标注）'}")
        group = str(sense_row.get("sense_group") or "").strip()
        if group:
            lines.append(f"语义分组：{group}")
        examples = _parse_json_list(sense_row.get("examples")) or []
        if examples:
            shown = " ｜ ".join(_truncate(e, 80) for e in examples[:_EXAMPLES_SHOW])
            more = f"（共 {len(examples)} 条）" if len(examples) > _EXAMPLES_SHOW else ""
            lines.append(f"例句：{shown}{more}")
        if int(sense_row.get("is_idiom") or 0):
            lines.append("习语义项（group_tag=IDIOMS，是否排除由研究者决定）")
        if merged:
            lines.append(
                f"⚠️ 该义位{merged}（分立复核定稿）—— 后续消费（簇归属/模板/"
                "释义撰写）流向其并入目标义位，可在词条浏览器按目标 #id 检索跳转。"
            )
        return SpineSection(title, "\n\n".join(f"- {ln}" for ln in lines), "")
    except Exception as e:  # noqa: BLE001 — 脏数据不崩整页
        logger.warning(f"sense_spine: 义项信息段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


def _section_annotations(sense_id: int) -> SpineSection:
    """② 标注留痕：三类任务 × 编码人的提交（payload 摘要；留痕可见）。"""
    title = "② 标注留痕（annotation_submissions · 谁标的）"
    try:
        rows = _fetch_submissions_for_spine(sense_id)
        if not rows:
            return SpineSection(title, None,
                                "该义位暂无任何标注提交（admission / "
                                "feature_coding / alignment 三类任务均无记录，"
                                "或数据库不可用）")
        lines = []
        for row in rows:
            coder = (row.get("display_name") or row.get("username")
                     or f"用户#{row.get('coder_id')}（账号不可见）")
            status = str(row.get("status") or "")
            status_text = {"submitted": "已提交待审", "adjudicated": "已仲裁"}.get(
                status, status or "—")
            lines.append(
                f"- {_payload_summary(row.get('task_type'), row.get('payload'))}"
                f" · 编码人 {coder} · {status_text}"
                f" · 提交时间 {row.get('submitted_at') or '—'}"
            )
        return SpineSection(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sense_spine: 标注留痕段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


def _section_reliability(category: str) -> SpineSection:
    """③ 信度：范畴×任务级最近运行的 overall_alpha / per_feature。

    **段头固定注明 α 为范畴×任务级，非单义位**（reliability_runs 无义位
    粒度；单义位不存在专属 α，绝不把范畴 α 冒充为该义位的 α）。
    """
    title = "③ 信度（α 为范畴×任务级，非单义位）"
    try:
        rows = _fetch_latest_reliability(category)
        if not rows:
            return SpineSection(title, None,
                                f"范畴 {category} 暂无信度运行记录"
                                "（reliability_runs 未灌或数据库不可用；"
                                "α 由双标注人提交后经信度引擎产出）")
        lines = []
        for row in rows:
            task = str(row.get("task_type") or "")
            label = TASK_TYPE_LABELS.get(task, task or "未知任务")
            alpha = _format_alpha(row.get("overall_alpha"))
            per_feature = _parse_json_dict(row.get("per_feature")) or {}
            per_text = " ".join(
                f"{code}={_format_alpha(val)}"
                for code, val in list(per_feature.items())[:6]
            )
            more = "…" if len(per_feature) > 6 else ""
            lines.append(
                f"- {label}（最近运行）：overall α = **{alpha}**"
                f" · 编码人 {row.get('n_coders') or '—'} × 单位 "
                f"{row.get('n_units') or '—'}"
                f" · 计算时间 {row.get('computed_at') or '—'}"
            )
            if per_text:
                lines.append(f"  - 逐特征：{per_text}{more}"
                             "（达标线 α ≥ 0.7，G2 闸门口径）")
        return SpineSection(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sense_spine: 信度段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


def _section_cluster(cs: Tuple[Optional[int], Optional[str], Optional[str]],
                     category: str, language: str,
                     merged: Optional[str] = None) -> SpineSection:
    """④ 簇归属：最近运行的簇名/成员数＋典型性 tier。

    批次 6：merged 义位（分立复核定稿并入他义位）不再取簇信息 —— 改
    「已并入，不参与聚类」占位（簇归属与典型性的消费流向并入目标义位）；
    cs 映射失败时无从判定 merged，维持原灰段口径。
    """
    title = "④ 簇归属（cs_cluster_members → cs_clusters 最近运行）"
    cs_id, _study_code, reason = cs
    try:
        if merged and cs_id is not None:
            return SpineSection(
                title,
                f"- 该义位{merged}（分立复核定稿）——已并入，不参与聚类："
                "簇归属与典型性以并入目标义位为准（G3 分立复核裁决结果）。",
                "")
        if cs_id is None:
            return SpineSection(title, None, reason or "未在建模覆盖内")
        info = _fetch_cluster_info(cs_id, language)
        if not info:
            return SpineSection(
                title, None,
                f"该义位不在任何聚类簇中（cs_cluster_runs 无 {language} 运行，"
                "或数据库不可用）")
        lines = [
            f"- 所在簇：簇{info.get('cluster_no')} "
            f"{info.get('cluster_name') or '（簇名缺失）'}"
            f" · 成员 {info.get('cluster_size') if info.get('cluster_size') is not None else '—'} 条义位"
        ]
        version = str(info.get("version") or "").strip()
        if version:
            lines.append(f"- 运行版本：{version}（最近一次，run_id={info.get('run_id')}）")
        tier = _fetch_tier(category, language, cs_id)
        if tier:
            medoid_mark = " · 本簇 medoid（最具典型性成员）" if tier.get("is_medoid") else ""
            try:
                distance = f"{float(tier.get('gower_to_medoid')):.3f}"
            except (TypeError, ValueError):
                distance = "—"
            lines.append(
                f"- 典型性：**{_tier_label(tier.get('tier'))}**{medoid_mark}"
                f"（到 medoid 的 Gower 距离 {distance}）")
        else:
            lines.append("- 典型性：—（medoid 排序不可用：运行无有效特征矩阵或范畴包缺失）")
        return SpineSection(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sense_spine: 簇归属段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


def _section_template(cs: Tuple[Optional[int], Optional[str], Optional[str]],
                      category: str, language: str,
                      merged: Optional[str] = None) -> SpineSection:
    """⑤ 模板预览：template_engine.instantiate_template（确定性引擎）。

    批次 6：merged 义位不实例化模板（G3 收口 —— 模板对 merged 返回占位
    不生成），改「已并入，不参与模板」占位；释义消费流向并入目标义位。
    """
    title = "⑤ 模板预览（template_engine · 四维模板）"
    cs_id, study_code, reason = cs
    try:
        if merged and cs_id is not None:
            return SpineSection(
                title,
                f"- 该义位{merged}（分立复核定稿）——已并入，不参与模板："
                "模板实例化跳过 merged 义位，释义消费流向并入目标"
                "（阶段 2 释义撰写消费）。",
                "")
        if cs_id is None:
            return SpineSection(title, None, reason or "未在建模覆盖内")
        try:
            template = instantiate_template(str(study_code or category),
                                            str(language), int(cs_id))
        except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
            logger.warning(f"sense_spine: instantiate_template 异常: {e}")
            template = None
        if template is None:
            return SpineSection(title, None,
                                "模板实例化不可用（instantiate_template 返回空："
                                "聚类运行或范畴包缺失，详见服务端日志）")
        lines = [f"**模板文本：{template.get('template_text') or '（空）'}**"]
        schema = template.get("图式维度") or {}
        schema_name = schema.get("name")
        if schema_name:
            lines.append(
                f"- 图式维度：{schema_name}（{schema.get('code') or '—'}）"
                f" · 簇{schema.get('cluster_no')} {schema.get('cluster_name') or ''}")
        syntax = template.get("句法维度") or {}
        if syntax.get("transitivity"):
            lines.append(f"- 句法维度：{syntax.get('transitivity')}")
        oald = template.get("oald") or {}
        oald_def = str(oald.get("definition") or "").strip()
        if oald_def:
            grammar = str(oald.get("grammar") or "").strip()
            lines.append(
                f"- OALD 原文对照：{oald_def}"
                f"{f'（语法码 {grammar}）' if grammar else ''}")
        return SpineSection(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sense_spine: 模板预览段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


def _section_media(sense_id: int) -> SpineSection:
    """⑥ 媒体：media_db.list_assets_for_anchor('sense', id)（两级状态随行）。"""
    title = "⑥ 媒体（media_bindings · sense 锚）"
    try:
        rows = _fetch_media(sense_id)
        if not rows:
            return SpineSection(title, None,
                                "该义位暂无媒体绑定（media_bindings 无 sense 锚"
                                "记录，或数据库不可用；媒体登记与审定在词典管理"
                                "区「🖼️ 媒体库」）")
        lines = []
        for row in rows:
            kind = KIND_LABELS.get(str(row.get("kind")), str(row.get("kind")))
            purpose = PURPOSE_LABELS.get(str(row.get("purpose")),
                                         str(row.get("purpose")))
            caption = str(row.get("caption") or "").strip()
            license_text = str(row.get("license") or "").strip()
            line = (
                f"- {kind or '—'} · {purpose or '—'}"
                f" · 绑定 {row.get('binding_status') or '—'}"
                f"（资产 {row.get('asset_status') or '—'}）"
                f" · {row.get('file_path') or '（路径缺失）'}"
            )
            if caption:
                line += f" · 图注：{caption}"
            if license_text:
                line += f" · 许可：{license_text}"
            lines.append(line)
        lines.append("- 注：词条装配多模态区只取「发布」态绑定；此处全量展示留痕。")
        return SpineSection(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sense_spine: 媒体段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


def _section_custom_values(sense_id: int) -> SpineSection:
    """⑦ 定制属性：dict_admin_db.get_values_for_anchor('sense', id)。"""
    title = "⑦ 定制属性（custom_values · sense 锚）"
    try:
        rows = _fetch_custom_values(sense_id)
        if not rows:
            return SpineSection(title, None,
                                "该义位暂无定制属性值（custom_values 无 sense 锚"
                                "记录，或数据库不可用；字段定义在词典管理区"
                                "「🏷️ 定制属性」）")
        lines = []
        for row in rows:
            name = str(row.get("name") or row.get("code") or "（字段缺失）")
            value = (row.get("value_text")
                     if row.get("value_num") is None else row.get("value_num"))
            text = _truncate(value, 80) or "（空值）"
            suffix = "（字段已弃用，存量值只读）" \
                if str(row.get("field_status") or "") == "deprecated" else ""
            lines.append(f"- {name}（{row.get('code')}）＝ {text}{suffix}")
        return SpineSection(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sense_spine: 定制属性段渲染失败: {e}")
        return SpineSection(title, None, f"段渲染异常：{e}")


# ============================================
# 用户上下文域 UI（批次 19）：📌 书签 toggle ＋ 📝 我的笔记段
# （登录态专属 —— 会话门复用数据层 _resolve_user_id 单一口径，未登录
#   整段/整钮不渲染；写成功走 ui_kit.flash + rerun（RV12），失败 st.error
#   留在本轮；数据层 own-rows-only，六角色皆可用（私人数据））
# ============================================

def _render_bookmark_toggle(sense_id: int) -> None:
    """📌 书签 toggle（登录态专属；置于七段之前的动作位）。

    已收藏态经 _fetch_my_bookmark 单条直读判定（get_bookmark，批次 19 补
    读面）；两态：未收藏「📌 收藏本义位」→ upsert_bookmark（title=义位
    标签），已收藏「📍 已收藏·取消」→ delete_bookmark。取数异常时收藏态
    不可知 → 不渲染控件（fail-closed，不猜态）。书签列表独立页归第二批
    （list_bookmarks 消费入口见 user_context_db docstring 建议）。
    """
    if _context_uid() is None:
        return
    sid = int(sense_id)
    try:
        bookmarked = _fetch_my_bookmark(sid) is not None
    except Exception as e:  # noqa: BLE001 — 态不可知不渲染，不猜
        logger.error(f"sense_spine: 书签态判定失败（id={sid}），控件不渲染: {e}")
        return
    if bookmarked:
        if st.button("📍 已收藏·取消", key=_BOOKMARK_KEY_OFF.format(sid=sid)):
            if user_context_db.delete_bookmark("sense", str(sid)):
                ui_kit.flash("已取消收藏该义位。")
                st.rerun()
            else:
                st.error("取消收藏失败（数据库不可用），请稍后重试。")
    else:
        if st.button("📌 收藏本义位", key=_BOOKMARK_KEY_ON.format(sid=sid)):
            if user_context_db.upsert_bookmark("sense", str(sid),
                                               title=_sense_label(sid)):
                ui_kit.flash("已收藏该义位（个人书签，跨设备续接）。")
                st.rerun()
            else:
                st.error("收藏失败（数据库不可用），请稍后重试。")


def _render_my_notes_section(sense_id: int) -> None:
    """📝 我的笔记段（登录态专属；⑦ 定制属性段之后，七段面末尾）。

    user_notes 该用户 × 该义位私人笔记：已存笔记显示（updated_at 时间戳；
    展示行截断 _NOTE_DISPLAY_MAX_LEN，全文在下方编辑框）＋ text_area 编辑
    ＋「💾 保存笔记」/「🗑 删除笔记」（form 内双 submit：保存=upsert_note，
    '' 提交=显式清空但保留行 RV2-3 第 3 类；删除=delete_note，无行先提示
    不触库）。成功 ui_kit.flash + rerun（RV12），失败 st.error 本轮直出。
    段内异常折叠为灰提示，绝不打崩整页（与七段同款降级口径）。
    """
    if _context_uid() is None:
        return
    sid = int(sense_id)
    try:
        st.markdown(f"<h4 style='{HEADER_H4}'>{_MY_NOTES_TITLE}</h4>",
                    unsafe_allow_html=True)
        note_row = _fetch_my_note(sid)
        existing = str((note_row or {}).get("note") or "")
        if note_row is None:
            st.caption("该义位还没有私人笔记（仅自己可见；保存后跨设备续接）。")
        elif existing.strip():
            shown = (existing if len(existing) <= _NOTE_DISPLAY_MAX_LEN
                     else existing[:_NOTE_DISPLAY_MAX_LEN] + "…")
            st.markdown(shown)
            st.caption(f"最近更新：{note_row.get('updated_at') or '—'}"
                       "（全文见下方编辑框）。")
        else:
            st.caption("当前笔记为空（''=显式清空但保留行）。")
        with st.form(_NOTE_FORM_KEY.format(sid=sid), clear_on_submit=False):
            text = st.text_area(
                "笔记内容（'' 提交=显式清空；≤50000 字符）",
                value=existing,
                max_chars=MAX_NOTE_LEN,
                key=_NOTE_INPUT_KEY.format(sid=sid),
            )
            save_col, delete_col = st.columns(2)
            with save_col:
                save_clicked = st.form_submit_button("💾 保存笔记",
                                                     use_container_width=True)
            with delete_col:
                delete_clicked = st.form_submit_button("🗑 删除笔记",
                                                       use_container_width=True)
        if save_clicked:
            if user_context_db.upsert_note(sid, text):
                ui_kit.flash("笔记已保存（私人，跨设备续接）。")
                st.rerun()
            else:
                st.error("保存失败：会话失效、正文超长或数据库不可用。")
        if delete_clicked:
            if note_row is None:
                st.info("该义位还没有笔记可删。")
            elif user_context_db.delete_note(sid):
                st.session_state.pop(_NOTE_INPUT_KEY.format(sid=sid), None)
                ui_kit.flash("已删除该义位的私人笔记。")
                st.rerun()
            else:
                st.error("删除失败（数据库不可用），请稍后重试。")
    except Exception as e:  # noqa: BLE001 — 段渲染失败不拖垮整页（七段同款）
        logger.warning(f"sense_spine: 我的笔记段渲染失败: {e}")
        st.caption("暂无数据：我的笔记段渲染异常（详见服务端日志）。")


# ============================================
# 纯编排与渲染入口
# ============================================

def _spine_sections(sense_id: int, category: str = "motion",
                    language: str = "en") -> List[SpineSection]:
    """采集七段脊柱（**纯编排**：渲染层不取数，本函数不做 st. 调用）。

    各段独立构造（内部各自 try/except）；段顺序固定 ①→⑦，缺数段的
    body 为 None、missing_reason 说明原因（绝不编数）。
    """
    sid = _as_int(sense_id)
    if sid is None or sid <= 0:
        bad = f"sense_id 非法：{sense_id!r}（义位唯一锚 oald_senses.id 须为正整数）"
        return [
            SpineSection("① 义项信息（oald_senses · 义位唯一锚）", None, bad),
            SpineSection("② 标注留痕（annotation_submissions · 谁标的）", None, bad),
            SpineSection("③ 信度（α 为范畴×任务级，非单义位）", None, bad),
            SpineSection("④ 簇归属（cs_cluster_members → cs_clusters 最近运行）",
                         None, bad),
            SpineSection("⑤ 模板预览（template_engine · 四维模板）", None, bad),
            SpineSection("⑥ 媒体（media_bindings · sense 锚）", None, bad),
            SpineSection("⑦ 定制属性（custom_values · sense 锚）", None, bad),
        ]
    try:
        sense_row = _fetch_sense_row(sid)
    except Exception as e:  # noqa: BLE001 — 取数层已自兜底，防御一层
        logger.error(f"sense_spine: 义项行取数意外失败（id={sid}）: {e}")
        sense_row = None
    try:
        cs = _resolve_cs_sense(sid, category, language, sense_row)
    except Exception as e:  # noqa: BLE001
        logger.error(f"sense_spine: cs_senses 映射意外失败（id={sid}）: {e}")
        cs = (None, None, f"语义分析库映射异常：{e}")
    # 批次 6 merged 消费：cs_senses 映射成功才查分立落地现状（status/
    # merged_into）；映射失败或取数失败按普通义位渲染（不猜 merged）。
    merged: Optional[str] = None
    if cs[0] is not None:
        try:
            state = _fetch_cs_sense_state(int(cs[0]))
        except Exception as e:  # noqa: BLE001 — 取数层已自兜底，防御一层
            logger.error(f"sense_spine: cs_senses 现状取数意外失败（id={cs[0]}）: {e}")
            state = None
        if state:
            merged = _merged_target_suffix(state.get("status"),
                                           state.get("merged_into"))
    return [
        _section_sense_info(sid, sense_row, merged),
        _section_annotations(sid),
        _section_reliability(category),
        _section_cluster(cs, category, language, merged),
        _section_template(cs, category, language, merged),
        _section_media(sid),
        _section_custom_values(sid),
    ]


def render_sense_spine(sense_id: int, category: str = "motion",
                       language: str = "en") -> None:
    """渲染七段义项脊柱（义项 expander 内嵌；懒加载由调用方的 expander 承担）。

    每段：段头（h4）＋ 有数文本（st.markdown，Streamlit 自动转义）或
    缺数灰提示（st.caption「暂无数据：<原因>」）。单段异常已在
    _spine_sections 折叠为灰段，这里再兜一层，保证整页不崩。

    批次 19：七段之外加两件登录态专属私人上下文控件 —— 📌 书签 toggle
    （段前动作位）与 📝 我的笔记段（⑦ 之后，七段面末尾）；未登录两者皆
    不渲染（上下文域是登录态功能，fail-closed 口径的 UI 表达）。sense_id
    先归一（_as_int），脏 id 跳过两件控件（七段的 bad-id 灰段照旧）。
    """
    st.caption(
        f"义项脊柱 · 义位唯一锚 oald_senses.id = {sense_id} · 范畴 "
        f"{category} · 语言 {language}；各段独立取数，缺数如实灰显（不编数）。"
    )
    try:
        sections = _spine_sections(sense_id, category, language)
    except Exception as e:  # noqa: BLE001 — 编排层意外异常的最后防线
        logger.error(f"sense_spine: 脊柱编排意外失败（id={sense_id}）: {e}")
        st.warning("义项脊柱暂时不可用（编排异常，详见服务端日志）。")
        return
    ctx_sid = _as_int(sense_id)
    if ctx_sid is not None and ctx_sid > 0:
        try:
            _render_bookmark_toggle(ctx_sid)
        except Exception as e:  # noqa: BLE001 — 控件失败不拖垮七段
            logger.warning(f"sense_spine: 书签控件渲染失败（id={ctx_sid}）: {e}")
            st.caption("暂无数据：书签控件渲染异常（详见服务端日志）。")
    for section in sections:
        try:
            st.markdown(
                f"<h4 style='{HEADER_H4}'>{section.title}</h4>",
                unsafe_allow_html=True,
            )
            if section.body:
                st.markdown(section.body)
            else:
                st.caption(f"暂无数据：{section.missing_reason}")
        except Exception as e:  # noqa: BLE001 — 单段渲染失败不拖垮其余段
            logger.warning(f"sense_spine: 段渲染失败（{section.title}）: {e}")
            st.caption(f"暂无数据：段渲染异常（{section.title}）")
    if ctx_sid is not None and ctx_sid > 0:
        try:
            _render_my_notes_section(ctx_sid)
        except Exception as e:  # noqa: BLE001 — 控件失败不拖垮整页
            logger.warning(f"sense_spine: 我的笔记控件渲染失败（id={ctx_sid}）: {e}")
            st.caption("暂无数据：我的笔记段渲染异常（详见服务端日志）。")
