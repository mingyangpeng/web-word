"""释义模板引擎 —— 母图式自动提炼 + 槽位实例化 + 批量导出（论文 §6 支柱）。

对应 docs/spec/白话版对照清单.md 第二档 F5（自动生成释义模板的引擎）与
第四节（模板批量导出）；目标形态 = 论文 §6 的四维模板与 §6.4 对照表
（run¹/jog/march 三个手工样例的列结构：词条义位 / OALD10 原文释义 /
LexiSchema 模板化释义 / 优化要点）。

数据链（全部复用既有数据层，不新建表）::

    cs_clusters / cs_cluster_members / cs_sense_features（src/category_study.py）
    configs/<category>/features.yaml（特征 label / value_type / values 值域，
        经 src/category_pack.load_pack 读取）
    configs/<category>/schemas.yaml（图式定义：名称 / 重心定义 / 证据槽位；
        另含模板拼装节 template_assembly，见下）
    cs_senses.definition（OALD10 / 现汉7 释义原文，对照用）

两个主入口（均为确定性计算，**不调 LLM**）::

    derive_cluster_schemas(category, language)
        【母图式自动提炼】逐簇取成员特征均值（cs_sense_features 长表）：
          二元特征均值 >= 0.5            → 簇共享要素（schema_core）
          二元特征均值在 (0, 0.5)        → 可变槽位
          序数/名义特征簇内同值且非零    → 共享要素；有分歧 → 可变槽位
          全簇全 0 的特征                → 不进模板（与该簇无关）
        可变槽位附簇内取值分布（各取值计数 + 占比）。

    instantiate_template(category, language, sense_id, engine_schema=None)
        【槽位实例化】单义位特征向量 → 四维模板：
          图式维度     簇图式名 + 重心定义（schemas.yaml，按簇主体特征映射：
                       追逐标注多数 > 互动位移；P1 均值 ≥ 0.5 > 源点脱离；
                       P2/P3 均值 ≥ 0.5 > 终点抵达；其余 > 方式伴随 —— 与
                       category_study.derive_image_schema 的凸显优先级一致）
          语义参数维度 15 项聚类特征逐槽列出：槽位中文 label + 本义位取值
                       的中文标签（features.yaml values），并标注该槽在本簇
                       是共享要素还是可变槽位
          句法维度     A 组核验特征（A1 构式论元-不及物 / A2 及物使役 /
                       A3 主体受限，来自 cs_sense_features 的 A 列）及物性摘要
          对齐预留维度 空槽待填（跨语言簇对齐 / 双语同位义位回填后再实例化）
        OALD（或现汉7）原文释义一并返回供对照。

模板文字生成（确定性槽位拼装，拼装配置外置于范畴包）::

    【图式：X】…主句各段…；[可变槽位: 特征=取值标签；…]

    拼装配置 = configs/<category>/schemas.yaml 的 ``template_assembly`` 节
    （批次 10 R-1 收口：原引擎硬编码拼装表逐字迁移入各范畴包；引擎只保留
    「特征取值 → 槽位词面」的通用段规则 —— 段类型 text / codes / fragments /
    value_fragments / values / concat，修饰 joiner / prefix / suffix /
    template({value} 占位) / fallback / split_parts / first_only /
    strip_prefix，引擎代码零词类名词，框架文档 §4 纪律）。
    范畴包缺 template_assembly 节 → 抛 CategoryPackError（fail-closed，
    不回退任何词类的拼装表）；槽位清单 = 本簇可变槽位 × 本义位取值标签。

导出（第四节：模板批量导出）::

    collect_cluster_templates()  当前簇全部义位逐条实例化
    build_export_csv()           §6.4 列结构 CSV，单元格过 src/security
                                 .sanitize_csv_value 防公式注入（= + - @ \\t
                                 前置单引号；该函数已存在，不新增）
    build_export_json()          结构化 JSON（ensure_ascii=False）

页面接入由集成步骤统一做：本模块只暴露 render_template_page()。

约束与边界：
  * 槽位拼装配置外置于范畴包（schemas.yaml 的 template_assembly 节，
    批次 10 R-1 收口）；换词类 = 换 configs/<category>/ 并研制该包的拼装节，
    引擎主流程不改；缺节 fail-closed（见 render_template_text）。
  * 数据库不可用时主入口返回空列表 / None 并记日志（降级不崩，全库惯例）。
"""

import csv
import io
import json
import logging
import statistics
from typing import Any, Dict, List, Optional, Sequence

from src import guards
from src.category_pack import CategoryPackError, load_pack
from src.category_study import get_cluster_runs, get_clusters_with_members
from src.mysql_db import get_db_cursor
from src.oald_senses import split_definition
from src.security import sanitize_csv_value

logger = logging.getLogger(__name__)

# 二元特征进 schema_core 的均值阈值（任务口径：均值 ≥ 0.5 = 簇共享要素）
CORE_THRESHOLD = 0.5

# CSV 导出列序 = 论文 §6.4 对照表的列结构（前三列同名，末列留给编者）
TEMPLATE_CSV_COLUMNS = [
    "词条义位", "OALD10原文释义", "LexiSchema模板化释义",
    "图式维度", "语义参数维度", "句法维度", "对齐预留维度",
    "簇号", "簇名", "优化要点（编者填写）",
]


# ============================================
# 特征元数据（features.yaml 经 category_pack 读取）
# ============================================

def _feature_meta(pack: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """features.yaml → {code: {label, group, value_type, values, in_clustering}}。

    values 的键：整数键统一转 int（yaml.safe_load 对 ``{0: 不凸显}`` 已产
    int 键，这里再防御一次字符串数字键的写法）；非整数键（nominal 的字符
    串值域，如声道/方式类特征）原样保留 —— 两类键并存，value_label 双路查找。
    """
    meta: Dict[str, Dict[str, Any]] = {}
    for feat in pack["features"].get("features") or []:
        code = str(feat.get("code") or "").strip()
        if not code:
            continue
        raw_values = feat.get("values") or {}
        values: Dict[Any, str] = {}
        for k, v in raw_values.items():
            try:
                values[int(k)] = str(v)
            except (TypeError, ValueError):
                values[k] = str(v)  # nominal 字符串值域原样保留
        meta[code] = {
            "code": code,
            "label": str(feat.get("name") or code),
            "group": str(feat.get("group") or ""),
            "value_type": str(feat.get("value_type") or "binary"),
            "in_clustering": bool(feat.get("in_clustering")),
            "values": values,
        }
    return meta


def value_label(feature: Dict[str, Any], value: Any) -> str:
    """特征取值的中文标签（features.yaml values 值域；未知值回退字面量）。

    两路查找：值原样命中（nominal 字符串值域）优先，整数键次之。
    """
    if value is None:
        return ""
    values = feature.get("values") or {}
    if value in values:
        return str(values[value])
    try:
        key = int(value)
    except (TypeError, ValueError):
        return str(value)
    return str(values.get(key, key))


def resolve_pack(category: str, observed_codes: Sequence[str] = ()) -> Dict[str, Any]:
    """把 cs_* 表的范畴代号（如 RUN）解析到 configs/ 下的范畴包（如 motion）。

    两套命名空间不同：categories.code 是研究定位的范畴代号，configs/<dir>/
    是范畴包目录名（annotation 体系用 motion）。解析顺序：
      1) 同名直取（category 本身就是包名时零成本）；
      2) 否则扫描全部范畴包，选特征编码与 observed_codes（义位实际编码列）
         重合度最高的包 —— cs_sense_features 的 P1..A3 编码体系由哪个包
         定义，哪个包就是事实源。
    无候选 / 全部加载失败时抛 CategoryPackError（调用方降级处理）。
    """
    from src.category_pack import CATEGORIES

    candidates = CATEGORIES()
    if str(category) in candidates:
        return load_pack(str(category))
    observed = {str(c) for c in observed_codes if c}
    best: tuple = (None, -1)
    problems: List[str] = []
    for name in candidates:
        try:
            pack = load_pack(name)
        except CategoryPackError as e:
            problems.append(f"{name}: {e}")
            continue
        codes = set(_feature_meta(pack))
        overlap = len(observed & codes) if observed else len(codes)
        if overlap > best[1]:
            best = (pack, overlap)
    if best[0] is None:
        raise CategoryPackError(
            f"范畴 {category} 无法解析到任何范畴包（configs/ 扫描失败：\n- "
            + "\n- ".join(problems))
    return best[0]


# ============================================
# 母图式提炼（纯函数核心 + DB 编排）
# ============================================

def derive_cluster_schema_from_members(
    cluster_meta: Dict[str, Any],
    member_vectors: Sequence[Dict[str, Any]],
    feature_meta: Dict[str, Dict[str, Any]],
    tags: Optional[Sequence[Optional[str]]] = None,
    schema_defs: Optional[List[Dict[str, Any]]] = None,
    core_threshold: float = CORE_THRESHOLD,
) -> Dict[str, Any]:
    """【母图式提炼·纯函数】一个簇的成员特征矩阵 → 母图式草案。

    只提炼语义要素：feature_meta 中 in_clustering=true 的特征（motion 包 =
    P/M/C 15 列）；A 组核验特征留给句法维度（build_template）。

    划分规则（确定性，见模块 docstring）：
      binary   均值 >= core_threshold → schema_core；均值 ∈ (0, threshold) → 槽位
      ordinal/nominal 簇内方差为 0 且均值 > 0 → schema_core（记共享取值）；
                       方差 > 0 → 槽位
      全簇全 0 → 该特征与本簇无关，不进模板

    Returns:
        {cluster_id, cluster_no, cluster_name, size, note,
         schema: {code, name, definition} | None, schema_source,
         schema_core: {code: round(mean, 3)},
         core_features: [{code, label, mean, value_label}],
         variable_slots: [{code, label, value_type, distribution: [...]}],
         members: [{sense_id, lemma, sense_no, sense_label}]}
    """
    n = len(member_vectors)
    meta = dict(cluster_meta or {})
    members = [
        {k: m.get(k) for k in ("sense_id", "lemma", "sense_no", "sense_label")}
        for m in (meta.pop("members", None) or [])
    ]
    out: Dict[str, Any] = {
        "cluster_id": meta.get("cluster_id"),
        "cluster_no": meta.get("cluster_no"),
        "cluster_name": meta.get("cluster_name"),
        "size": meta.get("size", n),
        "note": meta.get("note"),
        "schema": None,
        "schema_source": "none",
        "schema_core": {},
        "core_features": [],
        "variable_slots": [],
        "members": members,
    }
    if n == 0:
        return out

    # 母图式只提炼语义要素（features.yaml in_clustering=true 的 P/M/C 15 列）；
    # A 组核验特征（构式论元/主体受限）属于句法维度，不进图式核心，
    # 否则 A1 的「有无及物构式」会冒充语义共享要素（真实 RUN 数据的教训）。
    semantic_meta = {
        code: feat for code, feat in feature_meta.items() if feat["in_clustering"]
    }

    means: Dict[str, float] = {}
    variances: Dict[str, float] = {}
    for code, feat in semantic_meta.items():
        vals = [int(v.get(code, 0) or 0) for v in member_vectors]
        mean = statistics.fmean(vals)
        means[code] = mean
        variances[code] = statistics.pvariance(vals) if len(vals) > 1 else 0.0

    core_codes: List[str] = []
    slot_codes: List[str] = []
    for code, feat in semantic_meta.items():
        mean, var = means[code], variances[code]
        if mean == 0 and var == 0:
            continue  # 全簇不取值：该要素与本簇无关
        if feat["value_type"] == "binary":
            if mean >= core_threshold:
                core_codes.append(code)
            else:
                slot_codes.append(code)
        else:
            # 序数/名义：0 也是有意义的取值（低/跟随依附…），簇内同值即共享
            if var == 0:
                core_codes.append(code)
            else:
                slot_codes.append(code)

    out["schema_core"] = {code: round(means[code], 3) for code in core_codes}
    out["core_features"] = [
        {
            "code": code,
            "label": feature_meta[code]["label"],
            "mean": round(means[code], 3),
            "value_label": value_label(feature_meta[code],
                                       round(means[code])),
        }
        for code in core_codes
    ]
    for code in slot_codes:
        feat = feature_meta[code]
        counts: Dict[int, int] = {}
        for v in member_vectors:
            counts[int(v.get(code, 0) or 0)] = counts.get(int(v.get(code, 0) or 0), 0) + 1
        distribution = [
            {
                "value": val,
                "label": value_label(feat, val),
                "count": cnt,
                "ratio": round(cnt / n, 3),
            }
            for val, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        out["variable_slots"].append({
            "code": code,
            "label": feat["label"],
            "value_type": feat["value_type"],
            "distribution": distribution,
        })

    out["schema"], out["schema_source"] = _map_cluster_schema(
        means, tags, schema_defs or [],
        fallback_name=out.get("cluster_name") or "")
    return out


def _map_cluster_schema(
    means: Dict[str, float],
    tags: Optional[Sequence[Optional[str]]],
    schema_defs: List[Dict[str, Any]],
    fallback_name: str = "",
) -> tuple:
    """簇 → 四图式之一（schemas.yaml）。返回 (schema|None, source)。

    映射优先级 = category_study.derive_image_schema 的凸显顺序：
    互动位移（追逐标注过半）> 源点脱离（P1）> 终点抵达（P2/P3）> 方式伴随。
    特征映射不上时退回簇名包含图式名的字面匹配；再不行返回 None。
    """
    tag_list = [str(t) for t in (tags or []) if t]
    chase = sum(1 for t in tag_list if "追逐" in t)
    if tag_list and chase * 2 > len(tag_list):
        key = "互动位移"
    elif means.get("P1", 0.0) >= CORE_THRESHOLD:
        key = "源点脱离"
    elif means.get("P2", 0.0) >= CORE_THRESHOLD or means.get("P3", 0.0) >= CORE_THRESHOLD:
        key = "终点抵达"
    else:
        key = "方式伴随"
    for s in schema_defs:
        if str(s.get("name") or "").startswith(key):
            return ({k: s.get(k) for k in ("code", "name", "definition")}, "feature_map")
    for s in schema_defs:
        if str(s.get("name") or "") and str(s.get("name")) in fallback_name:
            return ({k: s.get(k) for k in ("code", "name", "definition")}, "cluster_name")
    return None, "none"


def derive_cluster_schemas(category: str, language: str) -> List[Dict[str, Any]]:
    """【母图式自动提炼·DB 编排】范畴 × 语言的每个簇 → 母图式草案列表。

    数据源：cs_cluster_runs（取该语言最新运行）→ cs_clusters →
    cs_cluster_members → cs_sense_features（get_clusters_with_members
    已带成员特征编码与甄别标注）。失败（无数据 / 库不可用 / 配置缺失）
    返回 [] 并记日志，页面降级展示。
    """
    try:
        cat = _get_category(str(category))
        if not cat:
            logger.warning("template_engine: 范畴 %s 未灌入", category)
            return []
        runs = get_cluster_runs(int(cat["id"]), language=str(language))
        if not runs:
            return []
        run = runs[-1]  # 同语言多运行时取最新（id 递增）
        clusters = get_clusters_with_members(int(run["run_id"]))
        observed = set()
        for cl in clusters:
            for m in cl.get("members") or []:
                observed.update((m.get("features") or {}).keys())
        pack = resolve_pack(str(category), observed)
        feature_meta = _feature_meta(pack)
        schema_defs = pack["schemas"].get("schemas") or []
        return [
            derive_cluster_schema_from_members(
                {
                    "cluster_id": cl.get("cluster_id"),
                    "cluster_no": cl.get("cluster_no"),
                    "cluster_name": cl.get("name"),
                    "size": cl.get("size"),
                    "note": cl.get("note"),
                    "members": [
                        {k: m.get(k) for k in
                         ("sense_id", "lemma", "sense_no", "sense_label")}
                        for m in cl.get("members") or []
                    ],
                },
                [m.get("features") or {} for m in cl.get("members") or []],
                feature_meta,
                tags=[m.get("tag") for m in cl.get("members") or []],
                schema_defs=schema_defs,
            )
            for cl in clusters
        ]
    except CategoryPackError as e:
        logger.error("template_engine: 范畴包加载失败 category=%s: %s", category, e)
        return []
    except Exception as e:  # noqa: BLE001 — 降级不崩（无库/表缺失均走这里）
        logger.error("template_engine: derive_cluster_schemas failed: %s", e)
        return []


# ============================================
# 模板文字（确定性槽位拼装，不调 LLM；拼装配置外置于范畴包）
# ============================================

# 拼装节缺省骨架（骨架词面可被范畴包 template_assembly 逐键覆盖）；
# 主句各段与固定词面只来自范畴包，引擎不含任何词类拼装表（批次 10 R-1）。
_ASSEMBLY_SKELETON = {
    "header": "【图式：{schema}】",
    "main_joiner": "，",
    "slots_section": "；[可变槽位: {slots}]",
    "slots_joiner": "；",
    "slots_entry": "{label}={value}",
    "slots_empty": "无（全要素簇内共享）",
}


def _pack_assembly(pack: Dict[str, Any]) -> Dict[str, Any]:
    """范畴包 → template_assembly 节（缺节 fail-closed，R-1 收口）。

    拼装配置只来自范畴包；包缺节时抛 CategoryPackError（报「范畴包缺
    template_assembly」），绝不静默回退任何词类的拼装表。
    """
    node = ((pack.get("schemas") or {}).get("template_assembly"))
    if not isinstance(node, dict) or not node:
        cat = ((pack.get("pack") or {}).get("category")) or "?"
        raise CategoryPackError(
            f"范畴包缺 template_assembly（category={cat}）：模板拼装配置必须"
            "外置于范畴包 schemas.yaml 的 template_assembly 节（批次 10 R-1 "
            "收口），引擎不回退任何词类的拼装表")
    return node


def _load_assembly(feature_meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """按特征码重合度解析范畴包（resolve_pack）→ template_assembly 节。

    供纯函数直调路径（未显式传入拼装节）使用；DB 编排路径在
    instantiate_template 里已持有包，直接取节传入。
    """
    return _pack_assembly(resolve_pack("", list(feature_meta)))


def _is_on(value: Any) -> bool:
    """特征取值是否「启用」（整数口径与旧拼装表逐字一致：取 1 进词面）；
    nominal 字符串值域（引擎不预设取值编码）按非空即启用。"""
    if value is None:
        return False
    if isinstance(value, str):
        return value not in ("", "0")
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return bool(value)


def _strip_prefix(label: str, prefix: Any) -> str:
    """去特征标签前缀（拼装节 strip_prefix 配置；空/None 前缀原样返回）。"""
    prefix = str(prefix or "")
    return label.replace(prefix, "") if prefix else label


def _render_segment(seg: Any, feature_meta: Dict[str, Dict[str, Any]],
                    vector: Dict[str, Any]) -> List[str]:
    """拼装节单段 → 主句词面列表（空列表 = 本段不进主句）。

    通用段规则（特征码与词面全部来自范畴包拼装节，引擎零词类名词）：
      text            固定词面；
      codes           启用（_is_on）的特征 → label（可去前缀 strip_prefix，
                      first_only 只取首命中）；
      fragments       {特征码: 固定词面}，启用者按序出词面；
      value_fragments {取值: 固定词面}＋code，按本义位取值查表；
      values          [{code, prefix?, suffix?}] → 值标签词面；
      concat          子段按序拼接成一段。
    通用修饰：joiner / prefix / suffix / template({value} 占位) /
    fallback（全空时的词面）/ split_parts（各词面独立成主句段）。
    """
    seg = seg or {}
    if isinstance(seg.get("concat"), list):
        merged = "".join(
            "".join(_render_segment(child, feature_meta, vector))
            for child in seg["concat"])
        return [merged] if merged else []

    tokens: List[str] = []
    if seg.get("text") is not None:
        tokens.append(str(seg["text"]))
    for code in seg.get("codes") or []:
        feat = feature_meta.get(code)
        if feat and _is_on(vector.get(code)):
            tokens.append(_strip_prefix(str(feat["label"]), seg.get("strip_prefix")))
            if seg.get("first_only"):
                break
    for code, text in (seg.get("fragments") or {}).items():
        if code in feature_meta and _is_on(vector.get(code)):
            tokens.append(str(text))
    if seg.get("value_fragments"):
        raw = vector.get(seg.get("code"))
        table = {str(k): str(v) for k, v in (seg["value_fragments"] or {}).items()}
        hit = table.get(str(raw)) if raw is not None else None
        if hit:
            tokens.append(hit)
    for item in seg.get("values") or []:
        code = (item or {}).get("code")
        feat = feature_meta.get(code)
        if not feat:
            continue
        label = value_label(feat, vector.get(code, 0))
        if not label:
            continue
        tokens.append(str(item.get("prefix") or "") + str(label)
                      + str(item.get("suffix") or ""))

    tokens = [t for t in tokens if t]
    if not tokens:
        return [str(seg["fallback"])] if seg.get("fallback") else []
    if seg.get("split_parts"):
        return tokens
    joined = str(seg.get("joiner") or "").join(tokens)
    if seg.get("template"):
        return [str(seg["template"]).format(value=joined)]
    return [str(seg.get("prefix") or "") + joined + str(seg.get("suffix") or "")]


def render_template_text(
    feature_meta: Dict[str, Dict[str, Any]],
    vector: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    variable_slots: Optional[List[Dict[str, Any]]] = None,
    assembly: Optional[Dict[str, Any]] = None,
) -> str:
    """确定性模板文字：「【图式：X】…主句各段…；[可变槽位: …]」。

    与论文 §6.4 样例同构：图式名来自 schemas.yaml 的映射结果；主句各段与
    固定词面全部按范畴包 ``template_assembly`` 节渲染（批次 10 R-1 收口，
    引擎不含任何词类拼装表）；槽位清单 = 本簇可变槽位 × 本义位取值标签。
    全程无随机、无 LLM。

    Args:
        assembly: 范畴包的拼装节（instantiate_template 已持有包时显式传入）；
            未传时按 feature_meta 的特征码重合度解析范畴包取节。范畴包缺节
            时抛 CategoryPackError（fail-closed，不回退任何词类拼装表）。
    """
    if assembly is None:
        assembly = _load_assembly(feature_meta)
    if not isinstance(assembly, dict) or not assembly:
        raise CategoryPackError("范畴包缺 template_assembly（拼装节为空）")
    cfg = {**_ASSEMBLY_SKELETON, **assembly}

    parts: List[str] = []
    for seg in cfg.get("segments") or []:
        parts.extend(_render_segment(seg, feature_meta, vector))

    slot_entries = []
    entry_template = str(cfg.get("slots_entry") or "{label}={value}")
    for slot in variable_slots or []:
        feat = feature_meta.get((slot or {}).get("code"))
        if not feat:
            continue
        slot_entries.append(entry_template.format(
            label=str(feat["label"]),
            value=value_label(feat, vector.get(slot["code"], 0))))
    slot_text = (str(cfg.get("slots_joiner") or "；").join(slot_entries)
                 or str(cfg.get("slots_empty") or ""))

    schema_name = ((schema or {}).get("name")
                   or str(cfg.get("schema_fallback") or "未定图式"))
    header = str(cfg["header"]).format(schema=schema_name)
    slots_section = str(cfg["slots_section"]).format(slots=slot_text)
    return header + str(cfg["main_joiner"]).join(parts) + slots_section


# ============================================
# 槽位实例化（纯函数核心 + DB 编排）
# ============================================

def build_template(
    sense_row: Dict[str, Any],
    vector: Dict[str, Any],
    cluster_schema: Optional[Dict[str, Any]],
    feature_meta: Dict[str, Dict[str, Any]],
    assembly: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """【槽位实例化·纯函数】义位行 + 特征向量 + 母图式 → 四维模板。

    四维结构（论文 §6.2）：图式维度 / 语义参数维度 / 句法维度 / 对齐预留维度；
    词典原文（OALD10 / 现汉7）拆语法码后一并返回供 §6.4 式对照。
    模板文字按范畴包 template_assembly 节渲染（assembly 未传时按特征码
    解析范畴包取节；缺节 fail-closed，见 render_template_text）。
    """
    clustering = [c for c, f in feature_meta.items() if f["in_clustering"]]
    verify = [c for c, f in feature_meta.items() if not f["in_clustering"]]
    core_codes = set((cluster_schema or {}).get("schema_core") or {})
    slot_codes = {s["code"] for s in (cluster_schema or {}).get("variable_slots", [])}

    semantic_params = [
        {
            "code": code,
            "label": feature_meta[code]["label"],
            "value": int(vector.get(code, 0) or 0),
            "value_label": value_label(feature_meta[code], vector.get(code, 0)),
            "role": "core" if code in core_codes
                    else ("variable" if code in slot_codes else "off"),
        }
        for code in clustering
    ]
    syntax_features = [
        {
            "code": code,
            "label": feature_meta[code]["label"],
            "value": int(vector.get(code, 0) or 0),
            "value_label": value_label(feature_meta[code], vector.get(code, 0)),
        }
        for code in verify
        if code in feature_meta
    ]
    intrans = next((x for x in syntax_features if x["code"] == "A1"), None)
    trans = next((x for x in syntax_features if x["code"] == "A2"), None)
    transitivity = "未标注"
    if intrans and trans:
        flags = []
        if intrans["value"] == 1:
            flags.append("不及物")
        if trans["value"] == 1:
            flags.append("及物使役")
        transitivity = "+".join(flags) if flags else "未标注"

    grammar, definition = split_definition(sense_row.get("definition") or "")
    schema = (cluster_schema or {}).get("schema")
    template_text = render_template_text(
        feature_meta, vector, schema,
        (cluster_schema or {}).get("variable_slots") or [],
        assembly=assembly)

    return {
        "sense_id": sense_row.get("sense_id"),
        "lemma": sense_row.get("lemma"),
        "sense_no": sense_row.get("sense_no"),
        "sense_label": sense_row.get("sense_label"),
        "language": sense_row.get("language"),
        "status": sense_row.get("status"),
        "tag": sense_row.get("tag"),
        "register": sense_row.get("register"),
        "subject_type": sense_row.get("subject_type"),
        "oald": {
            "source": sense_row.get("source_dict"),
            "grammar": grammar,
            "definition": definition,
        },
        "图式维度": {
            "code": (schema or {}).get("code"),
            "name": (schema or {}).get("name"),
            "definition": (schema or {}).get("definition"),
            "schema_source": (cluster_schema or {}).get("schema_source", "none"),
            "cluster_id": (cluster_schema or {}).get("cluster_id"),
            "cluster_no": (cluster_schema or {}).get("cluster_no"),
            "cluster_name": (cluster_schema or {}).get("cluster_name"),
            "schema_core": (cluster_schema or {}).get("schema_core", {}),
        },
        "语义参数维度": semantic_params,
        "句法维度": {
            "transitivity": transitivity,
            "features": syntax_features,
        },
        "对齐预留维度": {
            "filled": False,
            "aligned": None,
            "note": "对齐预留维度：空槽待填（跨语言簇对齐 / 双语同位义位回填后实例化）",
        },
        "可变槽位": (cluster_schema or {}).get("variable_slots", []),
        "template_text": template_text,
    }


def instantiate_template(
    category: str,
    language: str,
    sense_id: int,
    engine_schema: Any = None,
) -> Optional[Dict[str, Any]]:
    """【槽位实例化·DB 编排】单义位 → 四维模板 + 词典原文对照。

    Args:
        engine_schema: 预提炼的母图式（derive_cluster_schemas 的单项或整表）。
            传入可避免重复提炼；未传则现场提炼一遍。给出的图式与义位所在簇
            不匹配且只有单项时按覆盖处理（供编者换图式试算）。
    Returns:
        build_template 的结构；义位不存在 / 数据不可用返回 None。
    """
    try:
        sense = _fetch_sense(str(category), int(sense_id), str(language))
        if not sense:
            logger.warning("template_engine: 义位不存在 category=%s sense_id=%s",
                           category, sense_id)
            return None
        pack = resolve_pack(str(category), sense["_vector"].keys())
        feature_meta = _feature_meta(pack)
        assembly = _pack_assembly(pack)  # 缺节 fail-closed（不回退任何词类拼装表）

        cluster_info = sense.pop("_cluster")
        cluster_schema = _pick_cluster_schema(engine_schema, cluster_info)
        if cluster_schema is None:
            schemas = derive_cluster_schemas(str(category), str(language))
            cluster_schema = _pick_cluster_schema(schemas, cluster_info)
        return build_template(sense, sense.pop("_vector"), cluster_schema,
                              feature_meta, assembly=assembly)
    except CategoryPackError as e:
        logger.error("template_engine: 范畴包加载失败 category=%s: %s", category, e)
        return None
    except Exception as e:  # noqa: BLE001 — 降级不崩
        logger.error("template_engine: instantiate_template failed: %s", e)
        return None


def _pick_cluster_schema(
    engine_schema: Any,
    cluster_info: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """从 engine_schema（单项 / 列表 / None）里挑出义位所在簇的母图式。"""
    if engine_schema is None:
        return None
    schemas = engine_schema if isinstance(engine_schema, (list, tuple)) else [engine_schema]
    target_id = (cluster_info or {}).get("cluster_id")
    for s in schemas:
        if s and s.get("cluster_id") == target_id:
            return s
    if len(schemas) == 1 and schemas[0]:
        return schemas[0]  # 单项覆盖：编者显式换图式试算
    return None


# ============================================
# 查询（本模块自有，只读 cs_* 表；不改动 category_study.py）
# ============================================

def _get_category(code: str) -> Optional[Dict[str, Any]]:
    """按研究代号查 categories 行（只读；库不可用/无命中返回 None）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, code, name_cn, name_en FROM categories WHERE code = %s",
                (code,))
            return cursor.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.error("template_engine: get_category failed: %s", e)
        return None


def _fetch_sense(category: str, sense_id: int,
                 language: str) -> Optional[Dict[str, Any]]:
    """单义位行 + 特征向量 + 所在簇（一次连接三查）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.id AS sense_id, s.sense_no, s.sense_label,
                          s.definition, s.example, s.subject_type, s.register,
                          s.tag, s.status, s.remark,
                          l.lemma, l.language, l.source_dict,
                          c.code AS category_code, c.name_cn AS category_name
                   FROM cs_senses s
                   JOIN cs_lexemes l ON s.lexeme_id = l.id
                   JOIN categories c ON l.category_id = c.id
                   WHERE c.code = %s AND l.language = %s AND s.id = %s""",
                (category, language, sense_id))
            sense = cursor.fetchone()
            if not sense:
                return None
            cursor.execute(
                """SELECT m.cluster_id, cl.cluster_no, cl.name AS cluster_name
                   FROM cs_cluster_members m
                   JOIN cs_clusters cl ON m.cluster_id = cl.id
                   JOIN cs_cluster_runs r ON cl.run_id = r.id
                   WHERE m.sense_id = %s AND r.language = %s
                   ORDER BY r.id DESC LIMIT 1""",
                (sense_id, language))
            sense["_cluster"] = cursor.fetchone()
            cursor.execute(
                """SELECT feature_code, value FROM cs_sense_features
                   WHERE sense_id = %s""",
                (sense_id,))
            sense["_vector"] = {row["feature_code"]: int(row["value"])
                                for row in cursor.fetchall()}
            return sense
    except Exception as e:  # noqa: BLE001
        logger.error("template_engine: fetch_sense failed: %s", e)
        return None


def lookup_sense_id(category: str, language: str, lemma: str,
                    sense_no: Optional[str] = None,
                    sense_label: Optional[str] = None) -> Optional[int]:
    """按 (词目[, 义项号][, 义位标签]) 找义位 id；测试与报告复现用。"""
    try:
        with get_db_cursor() as cursor:
            sql = """SELECT s.id FROM cs_senses s
                     JOIN cs_lexemes l ON s.lexeme_id = l.id
                     JOIN categories c ON l.category_id = c.id
                     WHERE c.code = %s AND l.language = %s AND l.lemma = %s"""
            params: List[Any] = [category, language, lemma]
            if sense_no is not None:
                sql += " AND s.sense_no = %s"
                params.append(str(sense_no))
            if sense_label is not None:
                sql += " AND s.sense_label = %s"
                params.append(sense_label)
            sql += " ORDER BY s.id LIMIT 1"
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return int(row["id"]) if row else None
    except Exception as e:  # noqa: BLE001
        logger.error("template_engine: lookup_sense_id failed: %s", e)
        return None


# ============================================
# 批量导出（论文 §6.3 流程第 5 步：表格 + 结构化文本两种格式）
# ============================================

def collect_cluster_templates(category: str, language: str,
                              cluster_no: Optional[int] = None) -> Dict[str, Any]:
    """当前簇全部义位逐条实例化（批量导出的数据面）。

    Returns:
        {"category", "language", "cluster": {母图式草案}, "templates": [...]}；
        簇不存在时 templates 为空列表。cluster_no 缺省取第一个簇。
    """
    schemas = derive_cluster_schemas(str(category), str(language))
    cluster = None
    for s in schemas:
        if cluster_no is None or s.get("cluster_no") == int(cluster_no):
            cluster = s
            break
    templates: List[Dict[str, Any]] = []
    if cluster:
        for m in cluster.get("members") or []:
            tpl = instantiate_template(str(category), str(language),
                                       int(m["sense_id"]),
                                       engine_schema=[cluster])
            if tpl:
                templates.append(tpl)
    return {
        "category": str(category),
        "language": str(language),
        "cluster": cluster,
        "templates": templates,
    }


def _csv_row(tpl: Dict[str, Any]) -> List[Any]:
    """一条模板 → §6.4 列结构的一行。"""
    dims = tpl["图式维度"]
    semantic = "；".join(
        f"{p['label']}={p['value_label']}"
        for p in tpl["语义参数维度"] if p["value"] != 0 or p["role"] != "off"
    )
    syntax = tpl["句法维度"]
    syntax_text = "及物性: " + syntax["transitivity"] + "；" + "；".join(
        f"{f['label']}={f['value_label']}" for f in syntax["features"])
    lemma_no = f"{tpl.get('lemma') or ''}{tpl.get('sense_no') or ''}"
    return [
        f"{lemma_no}（{tpl.get('sense_label') or ''}）",
        (tpl.get("oald") or {}).get("definition") or "",
        tpl.get("template_text") or "",
        f"{dims.get('name') or ''}：{dims.get('definition') or ''}",
        semantic,
        syntax_text,
        "（空槽待填）" if not tpl["对齐预留维度"]["filled"] else "已回填",
        dims.get("cluster_no"),
        dims.get("cluster_name"),
        "",  # 优化要点：编者填写列
    ]


def build_export_csv(templates: List[Dict[str, Any]]) -> str:
    """模板列表 → CSV 文本（§6.4 列结构）。

    每个单元格过 src/security.sanitize_csv_value：以 = + - @ \\t 开头的
    文本前置单引号，防 Excel/WPS 公式注入（CSV Injection）。
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_CSV_COLUMNS)
    for tpl in templates:
        writer.writerow([sanitize_csv_value(cell) for cell in _csv_row(tpl)])
    return buf.getvalue()


def build_export_json(payload: Dict[str, Any]) -> str:
    """collect_cluster_templates 的结构化 JSON（ensure_ascii=False，编者可读）。"""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


# ============================================
# Streamlit 页（页面接入由集成步骤统一做：app.py 只需调本函数）
# ============================================

def render_template_page() -> None:
    """「释义模板引擎」页：母图式卡片 → 实例化模板卡片 → OALD 对照 → 批量导出。"""
    import streamlit as st

    from src.category_study import category_study_ready, get_categories

    st.subheader("释义模板引擎 · 母图式提炼与槽位实例化")
    st.caption(
        "聚类子簇 → 共享事件母图式（核心要素）+ 可变参数槽位 → 单义位四维模板 "
        "（图式 / 语义参数 / 句法 / 对齐预留）→ 与 OALD10 原文并排对照 → 批量导出。"
        "全程确定性规则拼装，不调用 LLM；模板定稿权在编者（论文 §6.2 人机协同）。")

    if not category_study_ready():
        st.info("范畴深挖数据尚未灌入：先运行 scripts/load_category_study.py，"
                "再回到本页。")
        return
    categories = get_categories()
    if not categories:
        st.warning("数据库中没有范畴记录。")
        return

    cat_code = st.selectbox(
        "范畴", options=[c["code"] for c in categories],
        format_func=lambda code: next(
            f"{c['code']} {c['name_cn']}" for c in categories if c["code"] == code))
    language = st.radio(
        "语言", options=["en", "zh"], horizontal=True,
        format_func={"en": "英语（OALD10）", "zh": "汉语（现汉7）"}.get)

    schemas = derive_cluster_schemas(cat_code, language)
    if not schemas:
        st.warning("该语言没有可用的聚类运行（cs_cluster_runs 为空）。")
        return

    # ---- 母图式卡片（核心要素 vs 可变槽位 两栏）----
    cluster_labels = [
        f"簇{s.get('cluster_no')} {s.get('cluster_name') or ''}" for s in schemas]
    picked = st.selectbox("选择簇（母图式）", options=range(len(schemas)),
                          format_func=lambda i: cluster_labels[i],
                          key="template_cluster")
    cl = schemas[picked]
    schema = cl.get("schema") or {}
    st.markdown(
        f"**母图式**：{schema.get('name') or '未映射图式'}"
        f"（{schema.get('code') or '—'}，映射来源 {cl.get('schema_source')}） — "
        f"{schema.get('definition') or '（schemas.yaml 未给出定义）'}")
    col_core, col_slot = st.columns(2)
    with col_core:
        st.markdown("##### 核心要素（簇共享，均值 ≥ 0.5）")
        if cl.get("core_features"):
            for f in cl["core_features"]:
                st.markdown(f"- **{f['label']}**（均值 {f['mean']}，"
                            f"典型取值「{f['value_label']}」）")
        else:
            st.caption("本簇没有达到阈值的共享二元要素。")
        with st.expander("schema_core 原始均值"):
            st.json(cl.get("schema_core") or {})
    with col_slot:
        st.markdown("##### 可变槽位（簇内分歧 / 低频要素）")
        if cl.get("variable_slots"):
            for s in cl["variable_slots"]:
                dist = " · ".join(
                    f"{d['label']} {d['count']}/{cl.get('size') or '?'}"
                    for d in s["distribution"])
                st.markdown(f"- **{s['label']}**（{s['value_type']}）：{dist}")
        else:
            st.caption("本簇全部要素共享，无可变槽位。")
    if cl.get("members"):
        with st.expander(f"簇成员（{len(cl['members'])} 条）"):
            st.dataframe(cl["members"], hide_index=True)

    st.divider()

    # ---- 槽位实例化 + OALD 对照 ----
    members = cl.get("members") or []
    if not members:
        st.info("本簇没有成员义位，无法实例化。")
        return
    member_labels = [
        f"{m.get('lemma')}{m.get('sense_no') or ''}（{m.get('sense_label') or ''}）"
        for m in members]
    member_idx = st.selectbox(
        "选择簇内义位（实例化模板）", options=range(len(members)),
        format_func=lambda i: member_labels[i], key="template_sense")
    sense_id = int(members[member_idx]["sense_id"])
    tpl = instantiate_template(cat_code, language, sense_id, engine_schema=schemas)
    if not tpl:
        st.error("模板实例化失败，请查看日志。")
        return

    st.markdown("##### 实例化模板（四维结构）")
    st.markdown(f"**{tpl['template_text']}**")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**① 图式维度**")
        sd = tpl["图式维度"]
        st.markdown(
            f"- 图式：{sd.get('name') or '—'}（{sd.get('code') or '—'}）\n"
            f"- 重心定义：{sd.get('definition') or '—'}\n"
            f"- 所属簇：簇{sd.get('cluster_no')} {sd.get('cluster_name') or ''}")
        st.markdown("**③ 句法维度**")
        sy = tpl["句法维度"]
        st.markdown(
            f"- 及物性：{sy['transitivity']}\n" + "\n".join(
                f"- {f['label']} = {f['value_label']}" for f in sy["features"]))
    with d2:
        st.markdown("**② 语义参数维度**")
        for p in tpl["语义参数维度"]:
            role = {"core": "核心", "variable": "槽位", "off": "未启用"}[p["role"]]
            st.markdown(f"- {p['label']} = **{p['value_label'] or '（未编）'}**"
                        f"　`{p['code']}`·{role}")
        st.markdown("**④ 对齐预留维度**")
        al = tpl["对齐预留维度"]
        st.markdown(f"- {'已回填' if al['filled'] else '空槽待填'}：{al['note']}")

    st.markdown("##### 与词典原文并排对照（§6.4）")
    oald = tpl.get("oald") or {}
    left, right = st.columns(2)
    with left:
        st.markdown(f"**{oald.get('source') or '词典'} 原文释义**")
        if oald.get("grammar"):
            st.caption(f"语法码：[{oald['grammar']}]")
        st.markdown(oald.get("definition") or "（无释义原文）")
    with right:
        st.markdown("**LexiSchema 模板化释义**")
        st.markdown(tpl["template_text"])

    st.divider()

    # ---- 批量导出（当前簇全部义位）----
    st.markdown("##### 批量导出（当前簇全部义位）")
    if st.button("生成当前簇全部模板", key="template_collect"):
        try:
            guards.require_dict_admin()  # §15：内容性导出仅词典管理员
        except PermissionError as e:
            st.error(f"⛔ {e}")
            st.stop()
        st.session_state["template_export"] = collect_cluster_templates(
            cat_code, language, cl.get("cluster_no"))
    payload = st.session_state.get("template_export")
    # RV12-3 陈旧载荷守卫：切簇/语言/范畴后旧导出不得继续显示。载荷在写入
    # 时已自带作用域三元组（collect_cluster_templates 返回的 category /
    # language / cluster.cluster_no），读取处与当前选择比对，不一致即视为
    # 无载荷 —— 不渲染计数/下载按钮，也不误报「当前簇没有可导出的模板」。
    if payload and (
        str(payload.get("category") or "") != str(cat_code)
        or str(payload.get("language") or "") != str(language)
        or (payload.get("cluster") or {}).get("cluster_no")
        != cl.get("cluster_no")
    ):
        payload = None
    if payload and payload.get("templates"):
        n = len(payload["templates"])
        st.caption(f"已生成 {n} 条模板（簇{payload['cluster'].get('cluster_no')}）。")
        csv_bytes = build_export_csv(payload["templates"]).encode("utf-8-sig")
        json_bytes = build_export_json(payload).encode("utf-8")
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                f"导出 CSV（{n} 条，防公式注入）", data=csv_bytes,
                file_name=f"templates_{cat_code}_{language}_"
                          f"cluster{payload['cluster'].get('cluster_no')}.csv",
                mime="text/csv", key="template_dl_csv")
        with dl2:
            st.download_button(
                f"导出结构化 JSON（{n} 条）", data=json_bytes,
                file_name=f"templates_{cat_code}_{language}_"
                          f"cluster{payload['cluster'].get('cluster_no')}.json",
                mime="application/json", key="template_dl_json")
    elif payload is not None:
        st.warning("当前簇没有可导出的模板。")
