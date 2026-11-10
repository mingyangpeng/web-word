"""以句搜义 —— 自然语言查询 → 特征向量 → 库内 Gower 最近邻（MVP）。

原名「AI 语义检索」；因与首页「搜索释义」（输入词形 → 出释义）名字相近易混，
更名「以句搜义」以体现相反方向：输入一句话描述，反查库内最相近的义位。
模块名 semantic_search 与内部函数名不变（代码标识，非界面文案）。

补齐《白话版对照清单》第三档 F1（论文 §7.1 第二模式）：输入一句话
（「一个士兵整齐地走」）→ 解析成语义特征向量 → 在范畴库 cs_sense_features
的义位编码矩阵上做 Gower 最近邻检索 → 返回最相近的义位（march 类）。

两层解析策略（MVP 不依赖 LLM 也能跑，LLM 仅增强）：

  第一层 规则匹配（默认，确定性、离线）
      configs/motion/features.yaml 每个特征新增可选字段 keywords:
      [{kw: 快, value: 2}, ...] —— 关键词在查询句中出现（子串匹配）即把
      该特征赋为 value；同一特征多个关键词命中时取更长关键词
      （更具体的词面优先，如「快走」胜过其子串「走」），平局取查询中
      位置最靠后者（最后提到的限定语优先）。
      未命中任何关键词的特征不进向量（查询向量是稀疏向量）。

  第二层 LLM 增强（可选开关，默认关）
      调 src/llm_api 的多提供商客户端，把查询句解析成特征 JSON
      （提示词内嵌特征清单与值域）；解析结果经值域校验后合并进第一层
      向量（补充规则层覆盖不到的表达）。任何失败（无 key / 网络异常 /
      JSON 不合法 / 取值越界）静默回退第一层结果，绝不抛错。

最近邻检索（复用 src/cluster_analysis 的 Gower 口径）：

  search_similar_senses(vector, category, language, top_k=10)
      取该范畴 × 语言全部义位的 in_clustering 特征向量（cs_sense_features
      长表），只比对查询向量中出现且义位也编码的特征（缺失跳过、按实际
      比对数归一 —— 与 cluster_analysis.gower_distance 同口径）；无任何
      共同特征的义位跳过（Gower 对无共同特征记 0，直接采纳会把未编码
      义位错误地排到最前）。返回 [{sense_id, verb, sense_label, distance,
      matched_features, ...}]，距离升序（平局按 sense_id 稳定）。

范畴名解析：``category`` 参数接受范畴包目录名（configs/<category>/，如
motion）或语义分析 categories.code（如 RUN）——包名 → 研究代号复用
cluster_analysis.PACK_TO_STUDY_CODE（d1 试点：motion 包的研究登记名是
RUN 跑范畴）。

页面接入：render_semantic_search_page() 由集成步骤挂进 app.py 的页面分派，
本模块不修改 app.py；无结果 / 无库 / 范畴包失败均优雅降级。
"""

from __future__ import annotations

import json
import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.category_pack import CATEGORIES, CategoryPackError, load_pack
from src.cluster_analysis import (
    LANGUAGE_LABELS,
    PACK_TO_STUDY_CODE,
    gower_distance,
    load_feature_types,
)
from src.design_system import (
    HEADER_H1, HEADER_H3, INFO_COLOR, SUCCESS_COLOR, WARNING_COLOR,
    pick_readable_text_color,
)
from src.mysql_db import cache_scope_key, get_db_cursor
from src.security import InputValidator

logger = logging.getLogger(__name__)

# 默认返回条数（页面与检索默认口径）
DEFAULT_TOP_K = 10

# 页面语言选择器（复用 cluster_analysis 的中英文标签）
LANGUAGES = ("en", "zh")

# LLM 增强层提示词（特征清单与值域由 _build_llm_prompt 按范畴包动态生成）
_LLM_SYSTEM_PROMPT = (
    "你是词典学助手。把用户的中文描述句解析为语义特征编码，只输出 JSON。"
)


# ============================================
# 特征元数据（features.yaml 经 category_pack 读取）
# ============================================

def _feature_meta(pack: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """范畴包 → {特征码: {label, group, value_type, in_clustering, values}}。

    values 的键统一转 int（yaml.safe_load 对 ``{0: 不凸显}`` 已产 int 键，
    这里再防御一次字符串键写法；speech 包 S1 的字符串值域原样保留）。
    """
    meta: Dict[str, Dict[str, Any]] = {}
    for feat in pack["features"].get("features") or []:
        code = str(feat.get("code") or "").strip()
        if not code:
            continue
        values: Dict[Any, str] = {}
        for k, v in (feat.get("values") or {}).items():
            try:
                values[int(k)] = str(v)
            except (TypeError, ValueError):
                values[str(k)] = str(v)
        meta[code] = {
            "code": code,
            "label": str(feat.get("name") or code),
            "group": str(feat.get("group") or ""),
            "value_type": str(feat.get("value_type") or "binary"),
            "in_clustering": bool(feat.get("in_clustering")),
            "values": values,
            "keywords": feat.get("keywords") or [],
        }
    return meta


def value_label(feature: Dict[str, Any], value: Any) -> str:
    """特征取值的中文标签（features.yaml values 值域；未知值回退数字字面量）。"""
    try:
        key = int(value)
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    values: Dict[Any, str] = feature["values"]
    return values.get(key, str(key))


# ============================================
# 第一层：规则匹配（关键词表，离线确定性）
# ============================================

def _keyword_entries(feat: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """features.yaml 的 keywords 字段 → [(关键词, 赋值), ...]。

    keywords 是可选字段，缺省视为无关键词。支持两种条目写法：
      * 字符串条目：省略赋值，按 binary 特征的「取 1」处理；
      * {kw: 关键词, value: 编码值} 映射条目：显式赋值（ordinal/nominal 用）。
    """
    entries: List[Tuple[str, Any]] = []
    for item in feat.get("keywords") or []:
        if isinstance(item, str):
            kw = item.strip()
            if kw:
                entries.append((kw, 1))
        elif isinstance(item, dict):
            kw = str(item.get("kw") or "").strip()
            if kw:
                entries.append((kw, item.get("value", 1)))
    return entries


def _rule_match(query: str,
                meta: Dict[str, Dict[str, Any]],
                ) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """第一层规则匹配：关键词表命中 → 特征赋值。

    同一特征有多个关键词命中时：取更长关键词（更具体的词面优先，子串
    关键词天然出现在更后位置，不能只看位置）；平局取出现位置最靠后者
    （最后提到的限定语优先）。

    Returns:
        (vector, keywords)：vector = {特征码: 编码值}（未命中的特征不进
        向量）；keywords = {特征码: 命中的关键词}（页面 chips 的触发词标注）。
    """
    hits: Dict[str, List[Tuple[int, int, str, Any]]] = {}
    for code, feat in meta.items():
        if not feat["in_clustering"]:
            continue  # A 组核验特征不进检索向量（与聚类矩阵同口径）
        for kw, value in _keyword_entries(feat):
            pos = query.find(kw)
            if pos < 0:
                continue
            # 取值对齐值域（与 LLM 层 _coerce_value 同口径）：配置被篡改/写错时
            # （value 为 None/嵌套容器/越域值/序数特征配了非数值）丢弃该条目，
            # 不让脏值进向量 —— 否则 Gower ordinal 分支 abs(a-b) 会对非数值抛
            # TypeError 打崩检索页（S1 review 6f）。
            aligned = _coerce_value(value, feat["values"]) if feat["values"] else value
            if aligned is None or (
                feat["value_type"] == "ordinal"
                and not isinstance(aligned, (int, float))
            ):
                continue
            hits.setdefault(code, []).append((pos, len(kw), kw, aligned))
    vector: Dict[str, Any] = {}
    keywords: Dict[str, str] = {}
    for code, found in hits.items():
        _, _, kw, value = max(found, key=lambda t: (t[1], t[0]))
        vector[code] = value
        keywords[code] = kw
    return vector, keywords


# ============================================
# 第二层：LLM 增强（可选开关，失败静默回退）
# ============================================

def _build_llm_prompt(query: str, meta: Dict[str, Dict[str, Any]]) -> str:
    """构造解析提示词：内嵌全部进聚类特征的清单与值域（中文标签）。"""
    lines = ["请把下面的查询句解析为语义特征编码。可用特征及其值域（只能用这些特征和取值）："]
    for code, feat in meta.items():
        if not feat["in_clustering"]:
            continue
        domain = "、".join(f"{k}={label}" for k, label in feat["values"].items())
        lines.append(f"- {code} {feat['label']}（{feat['value_type']}）: {domain}")
    lines.append("")
    lines.append(f"查询句：{query}")
    lines.append('只输出一个 JSON 对象，形如 {"P5": 2, "M1a": 1}，')
    lines.append("只包含查询句明确表达的特征；没有就输出 {}。不要输出任何解释文字。")
    return "\n".join(lines)


def _extract_json(content: str) -> Optional[dict]:
    """从 LLM 回复提取 JSON 对象（兼容 ```json 围栏）；不合法返回 None。"""
    text = str(content or "").strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _coerce_value(value: Any, values: Dict[Any, str]) -> Optional[Any]:
    """把 LLM 输出的取值对齐到 features.yaml 的值域键（int 优先，字符串值域次之）。"""
    try:
        iv = int(value)
        if iv in values:
            return iv
    except (TypeError, ValueError):
        pass
    sv = str(value)
    return sv if sv in values else None


def _llm_parse_features(query: str,
                        meta: Dict[str, Dict[str, Any]],
                        ) -> Optional[Dict[str, Any]]:
    """第二层 LLM 增强：查询句 → 特征 JSON（经值域校验）。

    无可用客户端 / 网络异常 / 回复不可解析 / 校验后为空 → None
    （调用方静默回退第一层规则结果）。
    """
    try:
        # 延迟导入：不开 AI 增强时不触发 SDK 导入与日志初始化（src/llm_api 只读复用）
        from src import llm_api

        client, _provider = llm_api.get_llm_client()
        if not client:
            logger.info("semantic_search: LLM 客户端不可用，AI 增强跳过")
            return None
        response = client.chat.completions.create(
            model=llm_api.LLM_MODEL,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": _build_llm_prompt(query, meta)},
            ],
            temperature=0.0,  # 结构化解析要确定性，不沿用释义生成的默认温度
            max_tokens=llm_api.LLM_MAX_TOKENS,
            timeout=llm_api.LLM_TIMEOUT,
        )
        data = _extract_json(response.choices[0].message.content)
        if not data:
            return None
        vector: Dict[str, Any] = {}
        for code, value in data.items():
            feat = meta.get(str(code))
            if not feat or not feat["in_clustering"]:
                continue  # 未知特征 / 核验区特征一律丢弃
            coerced = _coerce_value(value, feat["values"])
            if coerced is not None:
                vector[str(code)] = coerced
        return vector
    except Exception as e:  # noqa: BLE001 —— LLM 任何失败静默回退规则层
        logger.warning("semantic_search: LLM 解析失败，回退规则层: %s", e)
        return None


# ============================================
# 查询解析（两层策略编排）
# ============================================

def parse_query_to_features(query: str, pack: Dict[str, Any],
                            use_llm: bool = False) -> Dict[str, Any]:
    """查询句 → 特征向量 {特征码: 编码值}（两层策略，见模块 docstring）。

    Args:
        query: 自然语言查询句（中文；子串匹配对分词无要求）。
        pack: 范畴包（src/category_pack.load_pack 的输出，含 features.yaml）。
        use_llm: 是否开启第二层 LLM 增强（默认 False；失败静默回退规则层）。

    Returns:
        特征向量（只含命中的特征；空查询 / 无命中 → {}）。
    """
    detail = parse_query_detail(query, pack, use_llm=use_llm)
    vector: Dict[str, Any] = detail["vector"]
    return vector


def parse_query_detail(query: str, pack: Dict[str, Any],
                       use_llm: bool = False) -> Dict[str, Any]:
    """解析全过程（页面展示用）：向量 + 规则/LLM 分层明细。

    Returns:
        {"vector": 合并后向量, "rule_vector": 第一层规则结果,
         "llm_vector": 第二层 LLM 结果（未开 / 失败 → None）,
         "keywords": {特征码: 命中关键词}, "source": "rules" | "rules+llm"}
    """
    text = str(query or "").strip()
    meta = _feature_meta(pack)
    rule_vector, kw_map = _rule_match(text, meta)
    vector = dict(rule_vector)
    llm_vector: Optional[Dict[str, Any]] = None
    if use_llm and text:
        llm_vector = _llm_parse_features(text, meta)
        if llm_vector:
            vector.update(llm_vector)  # 增强：LLM 特征补充 / 覆盖规则层
    return {
        "vector": vector,
        "rule_vector": rule_vector,
        "llm_vector": llm_vector,
        "keywords": kw_map,
        "source": "rules+llm" if llm_vector else "rules",
    }


# ============================================
# 检索：库内 Gower 最近邻（cs_sense_features 编码矩阵）
# ============================================

def _get_category_id(category: str) -> Optional[int]:
    """范畴参数（包名 motion / 研究代号 RUN）→ categories.id；未灌数据 → None。

    包名 → 研究代号的映射复用 cluster_analysis.PACK_TO_STUDY_CODE
    （d1 试点：motion 包的研究登记名是 RUN 跑范畴）。
    """
    cat = str(category or "").strip()
    if not cat:
        return None
    candidates: List[str] = []
    for code in (cat, cat.upper(), PACK_TO_STUDY_CODE.get(cat.lower()) or ""):
        if code and code not in candidates:
            candidates.append(code)
    try:
        with get_db_cursor() as cursor:
            for code in candidates:
                cursor.execute(
                    "SELECT id FROM categories WHERE code = %s LIMIT 1", (code,))
                row = cursor.fetchone()
                if row:
                    return int(row["id"])
    except Exception as e:  # noqa: BLE001 —— 库不可用降级（返回 None）
        logger.error(f"semantic_search: 范畴查询失败 category={category}: {e}")
    return None


def _load_sense_index(category: str, language: str) -> Optional[Dict[str, Any]]:
    """范畴 × 语言的检索索引：全部义位行 + in_clustering 特征向量。

    Returns:
        {"category_id", "rows": [{sense_id, verb, sense_no, sense_label,
        definition, source_dict, status, language, features}]}；
        范畴未灌数据 / 库不可用 → None（调用方降级）。
    """
    cat_id = _get_category_id(category)
    if cat_id is None:
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.id AS sense_id, s.sense_no, s.sense_label,
                          s.definition, s.status, l.lemma, l.language,
                          l.source_dict
                   FROM cs_senses s
                   JOIN cs_lexemes l ON s.lexeme_id = l.id
                   WHERE l.category_id = %s AND l.language = %s
                   ORDER BY s.id""",
                (cat_id, str(language)))
            senses = list(cursor.fetchall())
            rows: List[Dict[str, Any]] = []
            if not senses:
                return {"category_id": cat_id, "rows": rows}
            ids = [int(r["sense_id"]) for r in senses]
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(
                f"""SELECT sense_id, feature_code, value
                    FROM cs_sense_features
                    WHERE sense_id IN ({placeholders}) AND in_clustering = 1""",
                ids,
            )
            features: Dict[int, Dict[str, Any]] = {}
            for row in cursor.fetchall():
                features.setdefault(int(row["sense_id"]), {})[
                    str(row["feature_code"])] = int(row["value"])
    except Exception as e:  # noqa: BLE001 —— 库不可用降级
        logger.error(f"semantic_search: 检索索引装载失败 category={category}: {e}")
        return None
    for s in senses:
        rows.append({
            "sense_id": int(s["sense_id"]),
            "verb": str(s["lemma"]),
            "sense_no": s["sense_no"],
            "sense_label": str(s["sense_label"]),
            "definition": s.get("definition") or "",
            "source_dict": str(s.get("source_dict") or ""),
            "status": str(s.get("status") or ""),
            "language": str(s["language"]),
            "features": features.get(int(s["sense_id"]), {}),
        })
    return {"category_id": cat_id, "rows": rows}


def search_similar_senses(feature_vector: Dict[str, Any],
                          category: str,
                          language: str,
                          top_k: int = DEFAULT_TOP_K,
                          index: Optional[Dict[str, Any]] = None,
                          value_types: Optional[Dict[str, str]] = None,
                          ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                          ) -> List[Dict[str, Any]]:
    """库内 Gower 最近邻检索（论文 §7.1 第二模式的检索端）。

    Args:
        feature_vector: 查询特征向量（parse_query_to_features 的输出）。
        category: 范畴包名（motion）或研究代号（RUN），见模块 docstring。
        language: "en" / "zh"。
        top_k: 返回条数上限；None / <=0 返回全部。
        index: 预装载的检索索引（_load_sense_index 输出）；None 现场装载
            （页面应传入缓存索引，避免每次检索重复查库）。
        value_types/ranges: 显式特征元数据（合成数据测试用）；缺省从范畴包
            features.yaml 读取（cluster_analysis.load_feature_types）。

    Returns:
        距离升序（平局按 sense_id 稳定）的最近邻列表，每项::

            {sense_id, verb, sense_no, sense_label, distance,
             matched_features, definition, source_dict, status, language}

        matched_features = 该义位实际参与比对的特征码（升序）：只比对查询
        向量中出现且义位也编码的特征，缺失跳过、按实际比对数归一；无任何
        共同特征的义位跳过。范畴未灌数据 / 库不可用 → []。
    """
    query = {str(c): v for c, v in (feature_vector or {}).items()}
    if not query:
        return []
    if value_types is None:
        value_types, ranges = load_feature_types(category)
    if not value_types:
        # 包缺失 / 元数据不全：未知特征按 nominal 处理（cluster_analysis 同口径）
        value_types = {code: "nominal" for code in query}
        ranges = {}
    if index is None:
        index = _load_sense_index(category, language)
    if not index or not index.get("rows"):
        return []

    results: List[Dict[str, Any]] = []
    for row in index["rows"]:
        sense_vec = row.get("features") or {}
        common = sorted(c for c in value_types if c in query and c in sense_vec)
        if not common:
            continue  # 无任何可比对特征：跳过（Gower 对空比对记 0，会把未编码义位排到最前）
        distance = gower_distance(query, sense_vec, value_types, ranges)
        results.append({
            "sense_id": row["sense_id"],
            "verb": row["verb"],
            "sense_no": row["sense_no"],
            "sense_label": row["sense_label"],
            "distance": distance,
            "matched_features": common,
            "definition": row.get("definition") or "",
            "source_dict": row.get("source_dict") or "",
            "status": row.get("status") or "",
            "language": row.get("language") or str(language),
        })
    results.sort(key=lambda r: (r["distance"], r["sense_id"]))
    if top_k is not None and top_k > 0:
        results = results[:int(top_k)]
    return results


# ============================================
# Streamlit 页面（集成步骤挂进 app.py，本模块不改 app.py）
# ============================================

# 特征分组配色（沿用 src/design_system 语义色板）
_GROUP_COLORS = {"P": INFO_COLOR, "M": SUCCESS_COLOR, "C": WARNING_COLOR}


def _chip(text: str, color: str) -> str:
    """特征 chip（HTML span；文本先经 _html_escape，样式沿用 design_system 色板）。

    RV1-2：文字颜色按底色自动选深/浅（旧版写死白字；换任何浅色底都
    不会退回 WCAG AA 之下）。
    """
    return (
        f'<span style="display:inline-block;background:{color};'
        f'color:{pick_readable_text_color(color)};'
        f'padding:2px 10px;border-radius:12px;font-size:0.82em;'
        f'margin:2px 6px 2px 0;">{text}</span>'
    )


@st.cache_data(ttl=600, show_spinner=False)
def _load_page_index(cache_scope: str, category: str,
                     language: str) -> Optional[Dict[str, Any]]:
    """页面级缓存（10 分钟）：范畴 × 语言的检索索引一次装载。

    首参 cache_scope（**不得**加下划线前缀）由调用方传
    mysql_db.cache_scope_key()：st.cache_data 的键只含入参，且**下划线开头的
    参数不参与哈希**（Streamlit 明确行为）—— 曾把作用域传进 `_cache_scope`
    下划线参数，等于没进键，测试切换 MYSQL_DATABASE 指向测试库时键不变，
    会把业务库的检索索引串进「空测试库」用例（S1 review 修复本身失效，
    S3 合跑复现：换库必须换缓存槽位，跨库隔离）。"""
    return _load_sense_index(category, language)


def _render_vector_chips(vector: Dict[str, Any],
                         meta: Dict[str, Dict[str, Any]],
                         keywords: Dict[str, str]) -> str:
    """命中的特征向量 → chips HTML（按 features.yaml 定义序；触发词标注）。"""
    chips: List[str] = []
    for code, feat in meta.items():
        if code not in vector:
            continue
        label = value_label(feat, vector[code])
        trigger = ""
        if code in keywords:
            trigger = f" ←「{_html_escape(keywords[code])}」"
        color = _GROUP_COLORS.get(feat["group"], INFO_COLOR)
        chips.append(_chip(
            f"{_html_escape(code)} {_html_escape(feat['label'])}="
            f"{_html_escape(str(label))}{trigger}", color))
    return "".join(chips)


def render_semantic_search_page() -> None:
    """🧠 以句搜义页：一句话 → 特征向量 chips → Gower 最近邻表（可展开释义）。

    范畴选择器列出范畴包目录（configs/<category>/，CATEGORIES()）；
    「AI 增强」开关默认关（MVP 不依赖 LLM 也能跑，LLM 仅增强）。
    无查询 / 无命中 / 无库 / 范畴包失败均优雅降级，不抛错。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>🧠 以句搜义（一句话找意思）</h1>",
                unsafe_allow_html=True)
    st.caption(
        "论文 §7.1 第二模式：自然语言描述 → 语义特征向量 → 库内 Gower 最近邻。"
        "规则层离线可用；「AI 增强」开启后由 LLM 补充解析（失败自动回退规则层）。"
    )

    packs = list(CATEGORIES()) or ["motion"]
    default_idx = packs.index("motion") if "motion" in packs else 0
    # FX-41（批次 20 挂账项）：ui.default_category 偏好接线 —— 偏好命中
    # 选项集才改首建 index；未登录/断库/无键/值空由 get_pref fail-closed
    # 返 None，偏好不在选项集保持原 motion 默认（ImportError 兜底并行读面
    # 未落），不崩页面。widget key 不变，index 只作用于首次实例化，
    # 不劫持用户手选。
    try:
        from src.user_context_db import get_pref

        pref = get_pref("ui.default_category")
        if pref in packs:
            default_idx = packs.index(pref)
    except ImportError:  # 并行读面未落 → 按无偏好降级
        pass
    category = st.selectbox("范畴包", options=packs, index=default_idx,
                            key="ss_category")
    language = st.selectbox("语言", options=list(LANGUAGES),
                            format_func=lambda lang: LANGUAGE_LABELS.get(lang, lang),
                            key="ss_language")
    query = st.text_input(
        "用一句话描述你想找的意思",
        placeholder="例如：一个士兵整齐地走",
        max_chars=200,
        key="ss_query")
    use_llm = st.toggle("AI 增强（LLM 解析，默认关闭；失败自动回退规则层）",
                        value=False, key="ss_use_llm")

    if not str(query or "").strip():
        st.info(
            "输入一句话（如「一个士兵整齐地走」）：系统解析出主体、速度、介质、"
            "动因等特征，再在库内按 Gower 距离找最相近的义位。"
            "描述越具体（谁在动、多快、什么介质、自愿还是被迫），结果越准。")
        return
    # 自由文本输入点过 src/security 安全校验（与首页动词搜索同一验证器）：
    # SQL/XSS 特征串直接拒绝、超长截停 —— 查询句虽只做子串匹配与 LLM 提示词，
    # 不进 SQL、不原样渲染 HTML，仍按全库惯例纵深防御（S1 review）。
    ok, err = InputValidator.validate_string(str(query), max_length=200)
    if not ok:
        st.error(f"查询句未通过安全校验（{err}），请调整措辞后重试。")
        return
    try:
        pack = load_pack(category)
    except CategoryPackError as e:
        st.error(f"范畴包 {category} 加载失败：{e}")
        return

    # ---- 解析出的特征向量（命中特征 chips）----
    detail = parse_query_detail(query, pack, use_llm=use_llm)
    vector = detail["vector"]
    meta = _feature_meta(pack)

    st.markdown(f"<h3 style='{HEADER_H3}'>解析出的特征向量</h3>",
                unsafe_allow_html=True)
    if not vector:
        st.warning(
            "没有从这句话中识别出任何特征。试试带上主体（士兵/马/车）、"
            "速度（快/慢）、介质（草地/水里/空中）或动因（自主/被迫）的描述，"
            "或开启「AI 增强」。")
        return
    st.markdown(_render_vector_chips(vector, meta, detail["keywords"]),
                unsafe_allow_html=True)
    st.caption({
        "rules": "解析方式：规则关键词匹配（离线，未命中特征不进向量）",
        "rules+llm": "解析方式：规则关键词匹配 + AI 增强（LLM 结果已合并，失败自动回退）",
    }[detail["source"]])

    # ---- 库内最近邻 ----
    st.markdown(f"<h3 style='{HEADER_H3}'>库内最近邻（Gower 距离升序）</h3>",
                unsafe_allow_html=True)
    index = _load_page_index(cache_scope_key(), category, language)
    if index is None or not index.get("rows"):
        st.info(
            f"范畴 {category}（{LANGUAGE_LABELS.get(language, language)}侧）"
            "暂无义位数据。请先运行 scripts/load_category_study.py 灌入语义分析数据。")
        return
    from src.tools.registry import get_tool
    _tool = get_tool("semantic_search")
    results = (_tool.run({"feature_vector": vector, "category": category,
                          "language": language, "top_k": DEFAULT_TOP_K,
                          "index": index})
               if _tool is not None else
               search_similar_senses(vector, category, language,
                                     top_k=DEFAULT_TOP_K, index=index))
    if not results:
        st.warning("没有可与该向量比对的义位（该范畴 / 语言侧没有特征编码数据）。")
        return

    st.dataframe(pd.DataFrame([
        {
            "距离": round(r["distance"], 4),
            "词": r["verb"],
            "义项": r["sense_no"] or "",
            "义位标签": r["sense_label"],
            "比对特征": "、".join(r["matched_features"]),
        }
        for r in results
    ]), hide_index=True)
    st.caption(
        f"共 {len(results)} 条（top_k={DEFAULT_TOP_K}）；距离 = 查询向量与义位"
        "编码向量的 Gower 相异度（只比对双方都编码的特征，按实际比对数归一；"
        "平局按义位 id 稳定排序）。点击下方行展开词典释义。")
    # 平局提示（RV5-11，与帮助文档 1.2 口径一致）：有并列距离时结果区注明供参照
    if any(results[i]["distance"] == results[i + 1]["distance"]
           for i in range(len(results) - 1)):
        st.caption("⚠️ 以下结果距离相同，供参照（并列距离按义位 id 稳定排序）。")

    for i, r in enumerate(results, start=1):
        title = (f"{i}. {_html_escape(r['verb'])}"
                 f"{_html_escape(str(r['sense_no'] or ''))} "
                 f"{_html_escape(r['sense_label'])}"
                 f"（距离 {r['distance']:.3f}）")
        with st.expander(title):
            st.markdown(f"**{_html_escape(r['source_dict'] or '词典')} 原文释义**")
            st.markdown(r["definition"] or "（无释义原文）")
            st.caption(
                f"状态：{_html_escape(r['status'] or '—')}｜"
                f"比对特征：{_html_escape('、'.join(r['matched_features']))}｜"
                f"义位 id：{r['sense_id']}")
