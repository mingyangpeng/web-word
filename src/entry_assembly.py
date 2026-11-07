"""词条装配视图（Agent AS，批次 9 阶段 2 主打）—— 工序 14 的消费侧预览。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6「成品词条内容模型」
（头块 / 义项区 / 多模态区 / 例证区 / 辨析栏 / 参见 / 定制属性——装配视图
按此渲染，段序以本任务契约为准）与「装配确定性：词条装配＝纯函数(义位版本,
体例版本, 装配器版本)，不单独版本化」；数据链为 §3 工序 14 出版装配 ——
本模块是其只读消费侧：编纂产出（definition_versions / sense_examples /
sense_translations）＋媒体发布绑定＋定制属性 → 装配成词条预览。

是什么（七段，每段独立取数、独立降级，绝不编数）：
  ① 头块        definitions 词目行（私有只读查询）：词形 verb / 音标
                phonetic / 词性（本库仅收动词，词性 v. 为平台口径而非 DB
                字段）/ 词目层中英释义 / 释义来源分级标注（definition_source
                ＋source_rank，分级语义来自 word_source.SOURCE_RANK：1
                dictionary.db · 2 legacy-library · 3 levin-brief · 4
                oxford-en · 5 pending）；
  ② 义项区      oald_senses 按 sense_index（mysql_db.get_oald_senses）；
                每义项：释义＋语法码＋coverage 标注——「建模」＝该 义项号
                在 cs_senses 有映射（软映射口径参照 sense_spine：categories
                .code ← PACK_TO_STUDY_CODE 包名映射，键 = (研究代号,
                language, lemma=词目, sense_no=oald_senses.sense_index)）；
                映射不到如实「沿用 OALD」。建模义项附模板释义
                （template_engine.instantiate_template，母图式每次装配只
                提炼一次经 engine_schema 复用）；cs_senses.status='merged'
                （批次 6 分立复核落地）如实追加「已并入 → #N」。
  ③ 例证区      lexical_db.list_examples(sense_ref, status='发布')（建模
                义项逐个取，sense_ref＝cs_senses.id 字符串）；整体为空
                →「暂无发布例证」。
  ④ 对译区      lexical_db.get_translation(sense_ref) 三态渲染：full
                完全对应（等价词）/ partial 部分对应（等价词＋括注 note）/
                none 无对应（释义翻译 paraphrase）；无定稿行 →「对译未定稿」。
  ⑤ 多模态区    media_db.list_assets_for_anchor 发布态绑定（binding_status
                ='发布'，media_db docstring 的装配口径）：词目锚
                （definitions.id）＋各义项锚（oald_senses.id）。图片进
                Section.images 由渲染层 st.image；音/视频 MVP 渲染文本
                ＋文件路径说明，不强行内嵌。
  ⑥ 定制属性    dict_admin_db.get_values_for_anchor('word', definitions.id)
                （词目层；义项级值在义项脊柱 ⑦ 段可见）。
  ⑦ 参见        mysql_db.get_synonyms（同簇近义词，word_clusters 簇成员
                口径）；**缺则整段省略**（返回段清单时不给灰段）。

接口（本批次契约）：
  render_entry_assembly(verb, category="motion", language="en") -> None
  _assembly_sections(verb, category, language) -> list[Section]
      —— 纯编排：body 非 None 即有数文本（动态值全部经 _html_escape 转义）；
      body 为 None 即缺数灰段（渲染层给「暂无：missing_reason」）；
      missing_reason 恒非空字符串。取数一律经模块级 _fetch_* / _derive_*
      薄适配层，测试 monkeypatch 这些名字即可构造全缺数 / 部分有数 /
      脏数据场景，不需要真实数据库。

GUIDE 母本（帮助中心同步用，本模块非独立页键——装配以搜索页 expander 呈现）：
  purpose  「📄 词条装配预览」把工序 3–14 的定稿产出按成品词条内容模型
           装配成一个只读预览：头块 / 义项（含 coverage 建模·沿用标注）/
           发布例证 / 对译三态 / 发布媒体 / 定制属性 / 同簇参见。
  principle 装配确定性（纯函数，不单独版本化）；只消费审定/发布态产出
           （例证取发布、媒体取发布绑定），未定稿产出绝不混入；缺数如实
           灰显，绝不编数；映射不到 cs_senses 的义项如实标「沿用 OALD」。
  data_source definitions / oald_senses / cs_senses / sense_examples /
           sense_translations / media_bindings / custom_values /
           word_clusters（全部只读）。
  steps    搜索命中 → 结果区「🕸️ 词与词关系」之后展开「📄 词条装配预览」
           → 逐段阅读；义项级留痕（谁标的、α、簇、模板版本）点词条浏览器
           的「🧬 义项脊柱」。
  notes    预览不落库、不参与出版导出（出版走 export_center 批次）；辨析栏
           与词源栏为可选微结构，本预览暂未渲染。

降级（每段独立 try/except，段头照常渲染）：
  数据层函数自身已把数据库不可用折叠为 []/None（只记日志），本模块把每段
  再包一层 try/except —— 任何脏数据（畸形字段、None、类型漂移）都折叠为
  该段缺数灰段，绝不让单段异常打崩整页；缺数原因如实写「暂无：<原因>」。

安全规则：
  1. 私有 SQL 一律参数化（本模块仅 3 条只读查询：definitions 词目行、
     categories 代号清单、cs_senses 软映射；其余全走数据层函数）；
  2. 所有动态值（词形/释义/例证/对译/路径/图注/属性值）拼进段体前一律
     经 _html_escape（html.escape）转义；段体由 st.markdown 输出
     （unsafe_allow_html=False），段头 h4 与 app.py 同口径带内联样式；
  3. 本模块只读：不建表、不写任何业务表，无写路径。
"""

import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from html import escape as _html_escape

import streamlit as st

from src import import_engine, lexical_db, media_db, mysql_db
from src.dict_admin_db import get_values_for_anchor
from src.design_system import HEADER_H4
from src.mysql_db import get_db_cursor
from src.cluster_analysis import PACK_TO_STUDY_CODE
from src.template_engine import derive_cluster_schemas, instantiate_template

logger = logging.getLogger(__name__)

# ============================================
# 常量（段头文案与展示映射）
# ============================================

# 释义来源分级（word_source.SOURCE_RANK 的展示文案；未知来源回退原文）
DEFINITION_SOURCE_LABELS = {
    "dictionary.db": "第 1 级 · dictionary.db（OALD 已审校中文释义，可回溯原文）",
    "legacy-library": "第 2 级 · legacy-library（既有词库释义）",
    "levin-brief": "第 3 级 · levin-brief（研究者标注的原型义简述）",
    "oxford-en": "第 4 级 · oxford-en（Oxford 英文释义，中文待补）",
    "pending": "第 5 级 · pending（释义待补）",
}

# 例证来源（lexical_db.EXAMPLE_SOURCES 的中文展示）
EXAMPLE_SOURCE_LABELS = {
    "corpus": "语料例",
    "adapted": "改写例",
    "composed": "自拟例",
}

# 对译三态（lexical_db.TRANSLATION_STATES 的中文展示）
TRANSLATION_STATE_LABELS = {
    "full": "完全对应",
    "partial": "部分对应",
    "none": "无对应",
}

# 媒体 kind / purpose 中文（media_db 常量；与义项脊柱同词）
KIND_LABELS = {"image": "图片", "audio": "音频", "video": "视频"}
PURPOSE_LABELS = {
    "pronunciation": "发音",
    "illustration": "释义配图",
    "example_media": "例证媒体",
    "schema_diagram": "图式示意图",
}

# 批次 6 merged 消费：cs_senses 分立落地状态（与 sense_spine 同口径常量）
_MERGED_STATUS = "merged"

# 发布态（media_bindings / sense_examples 审定链终态；装配只消费发布）
_PUBLISHED_STATUS = "发布"

# 多模态区 st.image 预览上限（文本行全量列出，图片只内嵌前 N 张）
_IMAGES_SHOW_LIMIT = 6

# 例证/定制属性值的单条展示截断（防长文本撑爆预览段）
_VALUE_MAX_LEN = 120


class Section(NamedTuple):
    """装配一段的渲染载荷（与义项脊柱 SpineSection 同构，另加 images 位）。

    body 非 None：有数文本（动态值已转义，渲染层 st.markdown）；
    body 为 None：缺数灰段，渲染层 st.caption(f"暂无：{missing_reason}")；
    missing_reason 恒非空字符串（有数段给空串占位，便于测试断言）；
    images：发布态图片绑定元组（dict 含 file_path/caption），仅多模态区
    使用，渲染层逐张 st.image（MVP 内嵌位；音视频只在 body 文本里）。
    """

    title: str
    body: Optional[str]
    missing_reason: str
    images: Tuple[Dict[str, Any], ...] = ()


# ============================================
# 展示口径纯函数（无 st./DB 依赖，tests 直接测）
# ============================================

def _clean_verb(verb: Any) -> str:
    """词目参数规整：转 str、去空白、限长 100（与 definitions.verb 同宽）。"""
    if verb is None:
        return ""
    text = str(verb).strip()
    return text[:100]


def _truncate(text: Any, limit: int = _VALUE_MAX_LEN) -> str:
    """任意值 → 截断字符串（脏值兜底 str()；None → 空串）。"""
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _esc(value: Any) -> str:
    """动态值 → 转义文本（_html_escape 别名；None → 空串）。

    装配视图的安全口径：所有进入段体的动态值先过这里，渲染层 st.markdown
    （unsafe_allow_html=False）只负责 markdown 结构本身。
    """
    return _html_escape(_truncate(value))


def _format_source_grade(row: Dict[str, Any]) -> str:
    """词目行 → 释义来源分级标注文本（纯函数；未知来源如实回退原文）。"""
    source = str(row.get("definition_source") or "").strip()
    rank = row.get("source_rank")
    label = DEFINITION_SOURCE_LABELS.get(source)
    if label is None:
        label = f"未登记来源「{_truncate(source, 40) or '—'}」" if source else "来源未登记"
    rank_text = f"（source_rank={rank}）" if rank is not None else ""
    return f"{label}{rank_text}"


def _coverage_tag(cs_entry: Optional[Dict[str, Any]]) -> str:
    """cs_senses 映射行 → coverage 标注（纯函数）。

    有映射 →「建模」；其中 status='merged'（分立复核定稿）追加「已并入 →
    #N」，merged_into 缺失则不猜去向（与义项脊柱 _merged_target_suffix 同
    口径）。无映射 →「沿用 OALD」。
    """
    if not cs_entry or cs_entry.get("id") is None:
        return "沿用 OALD"
    if str(cs_entry.get("status") or "").strip().lower() != _MERGED_STATUS:
        return "建模"
    target = cs_entry.get("merged_into")
    if isinstance(target, bool) or target is None:
        return "建模 · 已并入（去向待补录）"
    try:
        return f"建模 · 已并入 → #{int(target)}"
    except (TypeError, ValueError):
        return "建模 · 已并入（去向待补录）"


def _example_line(row: Dict[str, Any]) -> str:
    """例证行 → 展示文本（纯函数）：正文〔来源〕＋说明。"""
    content = _esc(row.get("content")) or "（例证文本为空，如实标注）"
    source = EXAMPLE_SOURCE_LABELS.get(str(row.get("source")),
                                       str(row.get("source") or "—"))
    line = f"{content}〔{source}〕"
    caption = str(row.get("caption") or "").strip()
    if caption:
        line += f" · 说明：{_esc(caption)}"
    return line


def _translation_line(tr: Optional[Dict[str, Any]]) -> str:
    """对译定稿行 → 三态展示文本（纯函数；空字段如实标注「未填」）。"""
    if not tr:
        return "对译未定稿（编纂产出区「例证与对译」页定稿后进入装配）"
    state = str(tr.get("state") or "")
    label = TRANSLATION_STATE_LABELS.get(state, state or "—")
    equivalent = str(tr.get("equivalent") or "").strip()
    note = str(tr.get("note") or "").strip()
    paraphrase = str(tr.get("paraphrase") or "").strip()
    if state == "none":
        body = _esc(paraphrase) if paraphrase else "释义翻译未填（none 态应给释义翻译）"
        return f"【{label}】释义翻译：{body}"
    eq_text = _esc(equivalent) if equivalent else "等价词未填"
    line = f"【{label}】等价词：{eq_text}"
    if state == "partial":
        line += f"（括注：{_esc(note)}）" if note else "（括注未填，partial 态应给括注）"
    return line


def _media_line(row: Dict[str, Any]) -> str:
    """发布态媒体绑定行 → 展示文本（纯函数；MVP 文本＋路径，不内嵌音视频）。"""
    kind = KIND_LABELS.get(str(row.get("kind")), str(row.get("kind") or "—"))
    purpose = PURPOSE_LABELS.get(str(row.get("purpose")),
                                 str(row.get("purpose") or "—"))
    path = _esc(row.get("file_path")) or "（路径缺失）"
    line = f"{kind} · {purpose} · {path}"
    caption = str(row.get("caption") or "").strip()
    if caption:
        line += f" · 图注：{_esc(caption)}"
    license_text = str(row.get("license") or "").strip()
    if license_text:
        line += f" · 许可：{_esc(license_text)}"
    asset_status = str(row.get("asset_status") or "").strip()
    if asset_status and asset_status != _PUBLISHED_STATUS:
        line += f" · 资产审定态 {asset_status}（绑定已发布，资产未发布）"
    return line


def _custom_value_text(row: Dict[str, Any]) -> str:
    """定制属性值行 → 展示值（number 优先，其余 value_text；脏值兜底）。

    value_num 数据层出参统一为 float（dict_admin_db.get_values_for_anchor），
    整数值（教材分级 3.0）按整数展示，属展示格式化而非改值。
    """
    num = row.get("value_num")
    if num is not None:
        try:
            fnum = float(num)
        except (TypeError, ValueError):
            return _truncate(num, 40)  # 脏值兜底如实展示
        if fnum.is_integer():
            return str(int(fnum))
        return _truncate(fnum, 40)
    return _esc(row.get("value_text")) or "（空值）"


# ============================================
# 取数薄适配层（模块级名字，测试 monkeypatch 目标；SQL 一律参数化）
# ============================================

def _fetch_definition_row(verb: str) -> Optional[Dict[str, Any]]:
    """① 头块词目行（**只读**私有查询）：definitions 主字段（含 phonetic——
    mysql_db.get_definition_by_verb 的出参不含音标，装配需要，故自查）。

    排除 import_voided=1（R3-9c）：导入回滚已作废的词目行不进装配（行仍
    留库审计）；列缺失（存量库未跑过导入迁移）时如实不过滤（探测见
    import_engine.has_import_voided_column）。

    无该词目 / 数据库不可用返回 None。"""
    try:
        sql = ("""SELECT id, verb, phonetic, chinese_ndef, en_ndef,
                         definition_source, source_rank, cluster_id
                  FROM definitions WHERE verb = %s""")
        if import_engine.has_import_voided_column():
            sql += " AND import_voided = 0"
        sql += " ORDER BY created_at DESC LIMIT 1"
        with get_db_cursor() as cursor:
            cursor.execute(sql, (str(verb),))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:  # noqa: BLE001 — 降级不崩（头块给缺数灰段）
        logger.error(f"entry_assembly: 词目行查询失败（verb={verb!r}）: {e}")
        return None


def _fetch_oald_senses(verb: str) -> List[Dict[str, Any]]:
    """② 义项区（**只读**）：mysql_db.get_oald_senses（examples 等 JSON 列
    已解析）。数据库不可用 / 无义项返回 []。"""
    try:
        return mysql_db.get_oald_senses(str(verb))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"entry_assembly: OALD 义项查询失败（verb={verb!r}）: {e}")
        return []


def _fetch_category_codes() -> List[str]:
    """② 映射辅助（**只读**）：categories.code 清单（与义项脊柱同口径；
    范畴深挖 8 表未灌返回 []）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT code FROM categories")
            return [str(r["code"]) for r in cursor.fetchall() if r.get("code")]
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.warning(f"entry_assembly: categories 清单查询失败: {e}")
        return []


def _study_code_for(category: Any, available_codes: List[str]) -> Optional[str]:
    """范畴参数 → 范畴深挖 categories.code（纯函数；与 sense_spine 同口径
    独立实现：先按 code 大小写不敏感直配，再按 PACK_TO_STUDY_CODE 包名映射）。"""
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


def _fetch_cs_sense_map(study_code: str, language: str,
                        lemma: str) -> Dict[str, Dict[str, Any]]:
    """② 软映射（**只读**私有查询）：词目全部义项 → cs_senses 映射表。

    键 = (categories.code, cs_lexemes.language, cs_lexemes.lemma,
    cs_senses.sense_no)（sense_spine._find_cs_sense_id 的逐义项口径批量版）；
    同义项号多行（不同 sense_label）取最小 id（确定性）。值附 status /
    merged_into（批次 6 分立落地现状，coverage 标注用）。

    迁移未跑（cs_senses 无 status/merged_into 列）时降级为不带状态列重查；
    查无 / 数据库不可用返回 {}。
    """
    lemma_text = str(lemma)
    base = (
        "SELECT s.id, s.sense_no, s.sense_label{extra} FROM cs_senses s "
        "JOIN cs_lexemes l ON s.lexeme_id = l.id "
        "JOIN categories c ON l.category_id = c.id "
        "WHERE c.code = %s AND l.language = %s AND l.lemma = %s "
        "ORDER BY s.id"
    )
    for extra in (", s.status, s.merged_into", ""):
        try:
            with get_db_cursor() as cursor:
                cursor.execute(base.format(extra=extra),
                               (str(study_code), str(language), lemma_text))
                rows = cursor.fetchall()
        except Exception as e:  # noqa: BLE001 — 状态列缺失（迁移未跑）降级重查
            logger.warning(
                f"entry_assembly: cs_senses 映射查询失败，降级重查"
                f"（{study_code}/{language}/{lemma_text}, extra={extra!r}）: {e}"
            )
            continue
        mapping: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("sense_no") or "").strip()
            if not key or key in mapping:
                continue  # 同义项号取最小 id（ORDER BY s.id 保证首见最小）
            entry: Dict[str, Any] = {"id": row.get("id"),
                                     "sense_label": row.get("sense_label")}
            if extra:
                entry["status"] = row.get("status")
                entry["merged_into"] = row.get("merged_into")
            mapping[key] = entry
        return mapping  # 查询成功即定案（有行带状态 / 无行=该词无映射）
    return {}


def _derive_engine_schema(study_code: str, language: str) -> List[Dict[str, Any]]:
    """② 模板辅助：母图式一次提炼（instantiate_template 的 engine_schema
    位逐义项复用，避免每义项重复 scipy 提炼）。失败 / 无数据返回 []。"""
    try:
        return derive_cluster_schemas(str(study_code), str(language))
    except Exception as e:  # noqa: BLE001 — 降级不崩（模板段按未产出口径）
        logger.warning(f"entry_assembly: 母图式提炼失败（{study_code}）: {e}")
        return []


def _fetch_template(study_code: str, language: str, cs_sense_id: int,
                    engine_schema: Any) -> Optional[Dict[str, Any]]:
    """② 模板释义（**只读**）：template_engine.instantiate_template（确定性
    引擎，不调 LLM）。义位不存在 / 数据不可用返回 None。"""
    try:
        return instantiate_template(str(study_code), str(language),
                                    int(cs_sense_id), engine_schema=engine_schema)
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.warning(f"entry_assembly: 模板实例化失败（cs_sense_id={cs_sense_id}）: {e}")
        return None


def _fetch_published_examples(sense_ref: str) -> List[Dict[str, Any]]:
    """③ 例证区（**只读**）：lexical_db.list_examples(sense_ref, status='发布')
    —— 只消费发布态（候选/审定例证不进装配）。数据库不可用返回 []。"""
    try:
        return lexical_db.list_examples(str(sense_ref), status=lexical_db.STATUS_PUBLISHED)
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"entry_assembly: 发布例证查询失败（sense_ref={sense_ref!r}）: {e}")
        return []


def _fetch_translation(sense_ref: str) -> Optional[Dict[str, Any]]:
    """④ 对译区（**只读**）：lexical_db.get_translation（一义位至多一行）。"""
    try:
        return lexical_db.get_translation(str(sense_ref))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"entry_assembly: 对译定稿查询失败（sense_ref={sense_ref!r}）: {e}")
        return None


def _fetch_media_for_anchor(anchor_type: str, anchor_id: int) -> List[Dict[str, Any]]:
    """⑤ 多模态区（**只读**）：media_db.list_assets_for_anchor（绑定＋资产
    两级状态随行；发布过滤在段构造层做）。"""
    try:
        return media_db.list_assets_for_anchor(anchor_type, int(anchor_id))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"entry_assembly: 媒体绑定查询失败（{anchor_type}:{anchor_id}）: {e}")
        return []


def _fetch_custom_values(anchor_type: str, anchor_id: int) -> List[Dict[str, Any]]:
    """⑥ 定制属性（**只读**）：dict_admin_db.get_values_for_anchor。"""
    try:
        return get_values_for_anchor(anchor_type, int(anchor_id))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"entry_assembly: 定制属性查询失败（{anchor_type}:{anchor_id}）: {e}")
        return []


def _fetch_synonyms(verb: str) -> List[str]:
    """⑦ 参见（**只读**）：mysql_db.get_synonyms（同簇全部其他成员）。"""
    try:
        return mysql_db.get_synonyms(str(verb))
    except Exception as e:  # noqa: BLE001 — 数据层已自兜底，防御一层
        logger.error(f"entry_assembly: 同簇近义查询失败（verb={verb!r}）: {e}")
        return []


# ============================================
# 七段构造（每段独立 try/except；body=None 即缺数灰段）
# ============================================

def _section_header(verb: str, row: Optional[Dict[str, Any]]) -> Section:
    """① 头块：词形 · 音标 · 词性 · 词目层释义 · 释义来源分级标注。"""
    title = "① 头块（definitions · 词目层展示投影）"
    try:
        if not row:
            return Section(title, None,
                           f"definitions 中无词目「{verb}」的行（词未入库或数据库不可用）")
        phonetic = str(row.get("phonetic") or "").strip()
        head = f"**{_esc(verb)}**"
        head += f" · 音标 /{_esc(phonetic)}/" if phonetic else " · 音标暂缺"
        head += " · 词性 v.（动词；本库仅收动词）"
        lines = [head]
        chinese = str(row.get("chinese_ndef") or "").strip()
        lines.append(f"- 中文释义（词目层主导义）：{_esc(chinese) or '（待补，如实标注）'}")
        english = str(row.get("en_ndef") or "").strip()
        lines.append(f"- 英文释义（词目层）：{_esc(english) or '（暂无）'}")
        lines.append(f"- 释义来源分级：{_esc(_format_source_grade(row))}")
        return Section(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001 — 脏数据不崩整页
        logger.warning(f"entry_assembly: 头块段渲染失败: {e}")
        return Section(title, None, f"段渲染异常：{e}")


def _section_senses(verb: str, senses: List[Dict[str, Any]],
                    cs_map: Dict[str, Dict[str, Any]],
                    study_code: Optional[str], category: str, language: str,
                    engine_schema: Any) -> Section:
    """② 义项区：oald_senses 按 sense_index；释义＋语法码＋coverage 标注。

    建模义项（cs_senses 有映射）附模板释义（instantiate_template，母图式
    复用）；merged 义位如实追加去向；映射不到的义项如实「沿用 OALD」。
    """
    title = "② 义项区（oald_senses · coverage：建模 / 沿用 OALD）"
    try:
        if not senses:
            return Section(title, None,
                           f"oald_senses 无词目「{verb}」的义项（词未入库、义项未灌"
                           "或数据库不可用；OALD 提取口径见 docs/research）")
        lines: List[str] = []
        if study_code is None:
            lines.append(
                f"- （范畴 {category} 未灌入范畴深挖库：coverage 全按「沿用 OALD」"
                "口径渲染，不判建模）")
        modeled_any = False
        for s in senses:
            index = _esc(s.get("sense_index"))
            grammar = str(s.get("grammar") or "").strip()
            definition = str(s.get("definition") or "").strip()
            cs_entry = cs_map.get(str(s.get("sense_index") or "").strip())
            tag = _coverage_tag(cs_entry)
            head = f"- **S{index}**〔{_esc(tag)}〕"
            if cs_entry and cs_entry.get("id") is not None:
                head += f"（cs_senses #{cs_entry.get('id')}"
                label = str(cs_entry.get("sense_label") or "").strip()
                if label:
                    head += f" · {_esc(label)}"
                head += "）"
                modeled_any = True
            head += f" · 语法码 {_esc(grammar) or '—'}"
            lines.append(head)
            if cs_entry and cs_entry.get("id") is not None and study_code:
                template = _fetch_template(study_code, language,
                                           int(cs_entry["id"]), engine_schema)
                template_text = str((template or {}).get("template_text") or "").strip()
                if template_text:
                    lines.append(f"  模板释义：{_esc(template_text)}")
                else:
                    lines.append("  模板释义未产出（聚类运行或范畴包缺失，"
                                 "详见服务端日志；正文以 OALD 原文为准）")
            lines.append(f"  OALD 释义：{_esc(definition) or '（释义为空，如实标注）'}")
        if not modeled_any and study_code is not None:
            lines.append(
                f"- （该词全部义项均未在建模覆盖内：范畴 {study_code}/{language} "
                "试点库无对应义位，coverage 如实标「沿用 OALD」）")
        return Section(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"entry_assembly: 义项区段渲染失败: {e}")
        return Section(title, None, f"段渲染异常：{e}")


def _section_examples(senses: List[Dict[str, Any]],
                      cs_map: Dict[str, Dict[str, Any]]) -> Section:
    """③ 例证区：建模义项逐个取发布态例证；整体为空 → 暂无发布例证。"""
    title = "③ 例证区（sense_examples · 仅发布态）"
    try:
        mapped = [(s, cs_map.get(str(s.get("sense_index") or "").strip()))
                  for s in senses]
        mapped = [(s, c) for s, c in mapped if c and c.get("id") is not None]
        if not mapped:
            return Section(title, None,
                           "该词无可取例证的义项：全部义项均为「沿用 OALD」或范畴深挖库"
                           "未灌（例证配置挂在 cs_senses 锚上，编纂产出区「例证与对译」"
                           "页按义项配置）")
        lines: List[str] = []
        any_published = False
        for s, cs_entry in mapped:
            ref = str(cs_entry["id"])
            rows = _fetch_published_examples(ref)
            head = f"- **S{_esc(s.get('sense_index'))}**（cs_senses #{ref}）"
            if rows:
                any_published = True
                lines.append(head)
                lines.extend(f"  - {_example_line(row)}" for row in rows)
            else:
                lines.append(f"{head}：暂无发布例证")
        if not any_published:
            return Section(title, None,
                           "暂无发布例证（建模义项的例证均在候选/审定态，或尚未配置；"
                           "候选→审定→发布单步流转在编纂产出区完成）")
        return Section(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"entry_assembly: 例证区段渲染失败: {e}")
        return Section(title, None, f"段渲染异常：{e}")


def _section_translations(senses: List[Dict[str, Any]],
                          cs_map: Dict[str, Dict[str, Any]]) -> Section:
    """④ 对译区：建模义项逐个取对译定稿，三态渲染。"""
    title = "④ 对译区（sense_translations · 三态定稿）"
    try:
        mapped = [(s, cs_map.get(str(s.get("sense_index") or "").strip()))
                  for s in senses]
        mapped = [(s, c) for s, c in mapped if c and c.get("id") is not None]
        if not mapped:
            return Section(title, None,
                           "该词无可取对译的义项：全部义项均为「沿用 OALD」或范畴深挖库"
                           "未灌（对译定稿挂在 cs_senses 锚上，一义位一行）")
        lines: List[str] = []
        any_finalized = False
        for s, cs_entry in mapped:
            ref = str(cs_entry["id"])
            tr = _fetch_translation(ref)
            line = _translation_line(tr)
            if tr:
                any_finalized = True
                who = tr.get("finalized_by")
                line += f" · 定稿人 #{who}" if who is not None else " · 系统登记"
            lines.append(f"- **S{_esc(s.get('sense_index'))}**（cs_senses #{ref}）· {line}")
        if not any_finalized:
            return Section(title, None,
                           "该词全部建模义项均无对译定稿（sense_translations 无记录，"
                           "或数据库不可用；三态定稿在编纂产出区「例证与对译」页完成）")
        return Section(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"entry_assembly: 对译区段渲染失败: {e}")
        return Section(title, None, f"段渲染异常：{e}")


def _published_bindings(anchor_type: str, anchor_id: Optional[int]) -> List[Dict[str, Any]]:
    """一个锚上的发布态绑定（binding_status='发布'；media_db 装配口径）。"""
    if anchor_id is None or int(anchor_id) <= 0:
        return []
    rows = _fetch_media_for_anchor(anchor_type, int(anchor_id))
    return [r for r in rows
            if str(r.get("binding_status") or "").strip() == _PUBLISHED_STATUS]


def _section_media(row: Optional[Dict[str, Any]],
                   senses: List[Dict[str, Any]]) -> Section:
    """⑤ 多模态区：词目锚＋义项锚的发布态绑定；图片进 images 位，其余文本。"""
    title = "⑤ 多模态区（media_bindings · 发布态绑定）"
    try:
        word_id = int(row["id"]) if row and row.get("id") is not None else None
        groups: List[Tuple[str, List[Dict[str, Any]]]] = []
        word_rows = _published_bindings(media_db.ANCHOR_WORD, word_id)
        if word_rows:
            groups.append((f"词目锚（definitions #{word_id}）", word_rows))
        for s in senses:
            sid = s.get("id")
            if sid is None:
                continue
            sense_rows = _published_bindings(media_db.ANCHOR_SENSE, int(sid))
            if sense_rows:
                groups.append(
                    (f"义项 S{_esc(s.get('sense_index'))} 锚（oald_senses #{sid}）",
                     sense_rows))
        if not groups:
            return Section(title, None,
                           "暂无发布态媒体绑定（媒体登记与审定在词典管理区「🖼️ 媒体库」；"
                           "候选/审定绑定不进装配，词目锚与义项锚均无发布记录，或数据库"
                           "不可用）")
        lines: List[str] = []
        images: List[Dict[str, Any]] = []
        for label, rows in groups:
            lines.append(f"- {label}")
            for r in rows:
                lines.append(f"  - {_media_line(r)}")
                if (str(r.get("kind")) == media_db.KIND_IMAGE
                        and r.get("file_path")
                        and len(images) < _IMAGES_SHOW_LIMIT):
                    images.append({
                        "file_path": str(r.get("file_path")),
                        "caption": str(r.get("caption") or "").strip(),
                    })
        total_images = sum(
            1 for _, rows in groups for r in rows
            if str(r.get("kind")) == media_db.KIND_IMAGE and r.get("file_path"))
        if total_images > len(images):
            lines.append(
                f"- 图片共 {total_images} 张，预览内嵌前 {len(images)} 张"
                "（其余见文件路径行；媒体库可查看全部）")
        return Section(title, "\n".join(lines), "", tuple(images))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"entry_assembly: 多模态区段渲染失败: {e}")
        return Section(title, None, f"段渲染异常：{e}")


def _section_custom_values(row: Optional[Dict[str, Any]]) -> Section:
    """⑥ 定制属性：词目锚（definitions.id）上的 custom_values（附字段元信息）。"""
    title = "⑥ 定制属性（custom_values · word 锚）"
    try:
        if not row or row.get("id") is None:
            return Section(title, None,
                           "无词目锚（definitions 无该词目行），定制属性无从取值")
        rows = _fetch_custom_values("word", int(row["id"]))
        if not rows:
            return Section(title, None,
                           "该词目暂无定制属性值（custom_values 无 word 锚记录，或数据库"
                           "不可用；字段定义在词典管理区「🏷️ 定制属性」，义项级值在义项"
                           "脊柱 ⑦ 段可见）")
        lines: List[str] = []
        for r in rows:
            name = str(r.get("name") or r.get("code") or "（字段缺失）")
            suffix = "（字段已弃用，存量值只读）" \
                if str(r.get("field_status") or "") == "deprecated" else ""
            lines.append(f"- {_esc(name)}（{_esc(r.get('code'))}）＝ "
                         f"{_custom_value_text(r)}{suffix}")
        return Section(title, "\n".join(lines), "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"entry_assembly: 定制属性段渲染失败: {e}")
        return Section(title, None, f"段渲染异常：{e}")


def _section_see_also(verb: str) -> Optional[Section]:
    """⑦ 参见：同簇近义词（word_clusters 簇成员口径）；**缺则整段省略**。"""
    try:
        synonyms = _fetch_synonyms(verb)
    except Exception as e:  # noqa: BLE001 — 取数层已自兜底，防御一层
        logger.warning(f"entry_assembly: 参见段取数失败: {e}")
        return None
    if not synonyms:
        return None  # 契约：缺则省略段（不出灰段）
    title = "⑦ 参见（同簇近义互见）"
    try:
        shown = "、".join(_esc(w) for w in synonyms[:50])
        more = f" 等（共 {len(synonyms)} 词）" if len(synonyms) > 50 else f"（共 {len(synonyms)} 词）"
        body = (f"参见同簇近义：{shown}{more} —— 词簇来自词库的次语义范畴划分"
                "（word_clusters / word_relations），簇内成员两两互为近义；"
                "在搜索栏输入词形即可互见复查。")
        return Section(title, body, "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"entry_assembly: 参见段渲染失败: {e}")
        return None


# ============================================
# 纯编排与渲染入口
# ============================================

def _assembly_sections(verb: Any, category: str = "motion",
                       language: str = "en") -> List[Section]:
    """采集七段装配视图（**纯编排**：渲染层不取数，本函数不做 st. 调用）。

    各段独立构造（内部各自 try/except）；缺数段 body 为 None、
    missing_reason 说明原因（绝不编数）；⑦ 参见缺数时整段省略。
    """
    v = _clean_verb(verb)
    if not v:
        bad = f"词目参数非法：{verb!r}（须为非空词形，≤100 字符）"
        return [
            Section("① 头块（definitions · 词目层展示投影）", None, bad),
            Section("② 义项区（oald_senses · coverage：建模 / 沿用 OALD）", None, bad),
            Section("③ 例证区（sense_examples · 仅发布态）", None, bad),
            Section("④ 对译区（sense_translations · 三态定稿）", None, bad),
            Section("⑤ 多模态区（media_bindings · 发布态绑定）", None, bad),
            Section("⑥ 定制属性（custom_values · word 锚）", None, bad),
        ]
    try:
        row = _fetch_definition_row(v)
    except Exception as e:  # noqa: BLE001 — 取数层已自兜底，防御一层
        logger.error(f"entry_assembly: 词目行取数意外失败（verb={v!r}）: {e}")
        row = None
    try:
        senses = _fetch_oald_senses(v)
    except Exception as e:  # noqa: BLE001
        logger.error(f"entry_assembly: 义项取数意外失败（verb={v!r}）: {e}")
        senses = []
    try:
        study_code = _study_code_for(category, _fetch_category_codes())
    except Exception as e:  # noqa: BLE001
        logger.error(f"entry_assembly: 范畴代号解析意外失败（category={category!r}）: {e}")
        study_code = None
    cs_map: Dict[str, Dict[str, Any]] = {}
    engine_schema: Any = None
    if study_code is not None:
        try:
            cs_map = _fetch_cs_sense_map(study_code, language, v)
        except Exception as e:  # noqa: BLE001
            logger.error(f"entry_assembly: cs_senses 映射意外失败（verb={v!r}）: {e}")
            cs_map = {}
        try:
            engine_schema = _derive_engine_schema(study_code, language)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"entry_assembly: 母图式提炼意外失败: {e}")
            engine_schema = []
    sections = [
        _section_header(v, row),
        _section_senses(v, senses, cs_map, study_code, category, language,
                        engine_schema),
        _section_examples(senses, cs_map),
        _section_translations(senses, cs_map),
        _section_media(row, senses),
        _section_custom_values(row),
    ]
    see_also = _section_see_also(v)
    if see_also is not None:
        sections.append(see_also)
    return sections


def render_entry_assembly(verb: Any, category: str = "motion",
                          language: str = "en") -> None:
    """渲染七段词条装配预览（搜索页 expander 内嵌；懒加载由调用方承担）。

    每段：段头（h4，与 app.py/义项脊柱同口径内联样式）＋ 有数文本
    （st.markdown，动态值已在段构造层经 _html_escape 转义）＋ 多模态区
    的发布态图片逐张 st.image（文件渲染失败降级为路径说明），或缺数灰提示
    （st.caption「暂无：<原因>」）。单段异常已在 _assembly_sections 折叠为
    灰段，这里再兜一层，保证整页不崩。
    """
    st.caption(
        f"词条装配预览 · 词目 {_html_escape(_clean_verb(verb) or str(verb))} · "
        f"范畴 {category} · 语言 {language}；按《平台架构设计规范》§6 成品词条"
        "内容模型装配（工序 14 消费侧），各段独立取数，缺数如实灰显（不编数）。"
    )
    try:
        sections = _assembly_sections(verb, category, language)
    except Exception as e:  # noqa: BLE001 — 编排层意外异常的最后防线
        logger.error(f"entry_assembly: 装配编排意外失败（verb={verb!r}）: {e}")
        st.warning("词条装配预览暂时不可用（编排异常，详见服务端日志）。")
        return
    for section in sections:
        try:
            st.markdown(
                f"<h4 style='{HEADER_H4}'>{section.title}</h4>",
                unsafe_allow_html=True,
            )
            if section.body:
                st.markdown(section.body)
            for image in section.images:
                try:
                    st.image(image.get("file_path"),
                             caption=image.get("caption") or None)
                except Exception as e:  # noqa: BLE001 — 文件缺失不拖垮整段
                    logger.warning(f"entry_assembly: 图片渲染失败"
                                   f"（{image.get('file_path')}）: {e}")
                    st.caption(f"图片文件渲染失败：{image.get('file_path')}"
                               "（文件不存在或不可读，路径以文本为准）")
            if not section.body and not section.images:
                st.caption(f"暂无：{section.missing_reason}")
        except Exception as e:  # noqa: BLE001 — 单段渲染失败不拖垮其余段
            logger.warning(f"entry_assembly: 段渲染失败（{section.title}）: {e}")
            st.caption(f"暂无：段渲染异常（{section.title}）")
