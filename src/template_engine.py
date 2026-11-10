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

    collect_cluster_templates()  当前簇全部义位逐条实例化（R5-7 起走
                                 instantiate_templates 批量取数：3 条查询
                                 取回全簇义位行/簇归属/特征向量，逐义位
                                 纯函数实例化，语义与逐条口径一致）
    build_export_csv()           §6.4 列结构 CSV，单元格过 src/security
                                 .sanitize_csv_value 防公式注入（= + - @ \\t
                                 前置单引号；该函数已存在，不新增）
    build_export_json()          结构化 JSON（ensure_ascii=False）

页面接入由集成步骤统一做：本模块只暴露 render_template_page()。
G3 消费（FX-28）：locked 词簇的模板实例化结果加「🔒 定稿基线」标识
（writing_db.get_cluster_lock_state 锁态读面，只读 fail-open；不禁止
查看/导出）。

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
            # 批次 19 工具页面接线（规范 §4）：registry 未加载回落直调等价
            from src.tools.registry import get_tool as _get_tool
            _sch = _get_tool("schema")
            schemas = (_sch.run({"category": str(category),
                                 "language": str(language)})
                       if _sch is not None else
                       derive_cluster_schemas(str(category), str(language)))
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
    """单义位行 + 特征向量 + 所在簇（一次连接三查；批量入口见 _fetch_senses）。"""
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


def _fetch_senses(category: str, language: str,
                  sense_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """多义位批量取数（R5-7 脊柱/导出 N+1 修复，**只读** cs_* 表）。

    与逐义位 _fetch_sense 等价的批量版：一次 3 条查询取回全部义位的
    主行 / 簇归属 / 特征向量，行形状逐字段一致（主行同 SELECT 列 +
    ``_cluster``（cs_cluster_members → cs_clusters 最近运行一行，r.id
    最大即最新，与逐义位 ORDER BY r.id DESC LIMIT 1 同解；无簇为 None）
    ＋ ``_vector``（cs_sense_features → {feature_code: int(value)}））。

    Returns:
        {sense_id: 行 dict}；义位不在库的 id 无键；入参全非法 / 整批
        查询失败返回 {}（调用方回退逐义位 _fetch_sense，旧行为兜底）。
    """
    ids: List[int] = []
    for sid in sense_ids:
        try:
            got = int(sid)
        except (TypeError, ValueError):
            continue
        if got not in ids:
            ids.append(got)
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""SELECT s.id AS sense_id, s.sense_no, s.sense_label,
                           s.definition, s.example, s.subject_type, s.register,
                           s.tag, s.status, s.remark,
                           l.lemma, l.language, l.source_dict,
                           c.code AS category_code, c.name_cn AS category_name
                    FROM cs_senses s
                    JOIN cs_lexemes l ON s.lexeme_id = l.id
                    JOIN categories c ON l.category_id = c.id
                    WHERE c.code = %s AND l.language = %s
                      AND s.id IN ({placeholders})
                    ORDER BY s.id""",
                (category, language, *ids))
            senses: Dict[int, Dict[str, Any]] = {}
            for row in cursor.fetchall():
                senses[int(row["sense_id"])] = dict(row)
            if not senses:
                return {}
            cursor.execute(
                f"""SELECT m.sense_id, m.cluster_id, cl.cluster_no,
                           cl.name AS cluster_name
                    FROM cs_cluster_members m
                    JOIN cs_clusters cl ON m.cluster_id = cl.id
                    JOIN cs_cluster_runs r ON cl.run_id = r.id
                    WHERE m.sense_id IN ({placeholders}) AND r.language = %s
                    ORDER BY m.sense_id ASC, r.id DESC""",
                (*ids, language))
            clusters: Dict[int, Dict[str, Any]] = {}
            for row in cursor.fetchall():
                sid = int(row["sense_id"])
                if sid not in clusters:  # 首见即 r.id 最大（与 LIMIT 1 同解）
                    clusters[sid] = {k: row[k] for k in
                                     ("cluster_id", "cluster_no", "cluster_name")}
            cursor.execute(
                f"""SELECT sense_id, feature_code, value
                    FROM cs_sense_features
                    WHERE sense_id IN ({placeholders})
                    ORDER BY sense_id ASC""",
                tuple(ids))
            vectors: Dict[int, Dict[str, int]] = {}
            for row in cursor.fetchall():
                sid = int(row["sense_id"])
                vectors.setdefault(sid, {})[row["feature_code"]] = int(row["value"])
            for sid, sense in senses.items():
                sense["_cluster"] = clusters.get(sid)
                sense["_vector"] = vectors.get(sid, {})
            return senses
    except Exception as e:  # noqa: BLE001 — 整批失败回退逐义位（降级不崩）
        logger.error("template_engine: fetch_senses failed: %s", e)
        return {}


def instantiate_templates(
    category: str,
    language: str,
    sense_ids: Sequence[int],
    engine_schema: Any = None,
) -> Dict[int, Optional[Dict[str, Any]]]:
    """【槽位实例化·批量编排】多义位一次取数 → 逐义位四维模板（R5-7）。

    语义与逐个 instantiate_template(category, language, sense_id,
    engine_schema) **逐字段一致**（None 占位口径也一致）：
      * 母图式按 engine_schema 挑选（_pick_cluster_schema 同参同解）；
        挑不中时母图式提炼**一次共享**（derive_cluster_schemas 同参确定性，
        与逐义位重复提炼同解，避免批量导出 N 次重提炼）；
      * 范畴包按本义位特征码重合度解析（resolve_pack 同参同解，同解共享）；
      * 批量取数失败（_fetch_senses 返回 {}）回退逐义位 instantiate_template
        （旧行为兜底）。

    Returns:
        {sense_id: build_template 结构 | None}；每个合法入参 id 都有键。
    """
    ids: List[int] = []
    for sid in sense_ids:
        try:
            got = int(sid)
        except (TypeError, ValueError):
            continue
        if got not in ids:
            ids.append(got)
    if not ids:
        return {}
    try:
        senses = _fetch_senses(str(category), str(language), ids)
    except Exception as e:  # noqa: BLE001 — 防御一层（_fetch_senses 已自兜底）
        logger.error("template_engine: instantiate_templates fetch failed: %s", e)
        senses = {}
    if not senses:
        return {
            i: instantiate_template(str(category), str(language), i,
                                    engine_schema=engine_schema)
            for i in ids
        }
    out: Dict[int, Optional[Dict[str, Any]]] = {}
    packs: Dict[frozenset, Optional[tuple]] = {}  # 特征码集 → (pack, meta, assembly)
    derived: Optional[List[Dict[str, Any]]] = None  # 母图式提炼一次共享（懒）
    for i in ids:
        try:
            sense = senses.get(i)
            if not sense:
                out[i] = None  # 义位不存在：与逐义位 instantiate_template 同口径
                continue
            vector = sense["_vector"]
            observed = frozenset(vector.keys())
            if observed not in packs:
                try:
                    pack = resolve_pack(str(category), vector.keys())
                    packs[observed] = (pack, _feature_meta(pack),
                                       _pack_assembly(pack))
                except Exception:  # noqa: BLE001 — CategoryPackError 等同旧捕获口径
                    packs[observed] = None
            entry = packs[observed]
            if entry is None:
                out[i] = None
                continue
            pack, feature_meta, assembly = entry
            cluster_info = sense["_cluster"]
            cluster_schema = _pick_cluster_schema(engine_schema, cluster_info)
            if cluster_schema is None:
                if derived is None:
                    from src.tools.registry import get_tool as _get_tool
                    _sch = _get_tool("schema")
                    derived = (_sch.run({"category": str(category),
                                         "language": str(language)})
                               if _sch is not None else
                               derive_cluster_schemas(str(category),
                                                      str(language)))
                cluster_schema = _pick_cluster_schema(derived, cluster_info)
            out[i] = build_template(sense, vector, cluster_schema,
                                    feature_meta, assembly=assembly)
        except Exception as e:  # noqa: BLE001 — 单义位异常折叠为 None（不崩批量）
            logger.error("template_engine: instantiate_templates sense=%s failed: %s",
                         i, e)
            out[i] = None
    return out


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

    R5-7（N+1 修复）：成员义位改走 instantiate_templates 一次取数
    （义位行 / 簇归属 / 特征向量各 1 条查询，共 3 条；母图式与范畴包同解
    共享），替代原「逐成员 instantiate_template 3 条查询 × N」的循环取数；
    实例化语义与逐成员口径逐字段一致（失败成员 None 不入表）。

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
        members = cluster.get("members") or []
        by_id = instantiate_templates(str(category), str(language),
                                      [int(m["sense_id"]) for m in members],
                                      engine_schema=[cluster])
        for m in members:
            tpl = by_id.get(int(m["sense_id"]))
            if tpl:
                templates.append(tpl)
    return {
        "category": str(category),
        "language": str(language),
        "cluster": cluster,
        "templates": templates,
    }


def _csv_row(tpl: Dict[str, Any], note: Optional[str] = None) -> List[Any]:
    """一条模板 → §6.4 列结构的一行。

    note：该义位最新人工修订的优化要点（FX-38 回填"优化要点"列；
    None → 留空，与旧口径逐字兼容——列仍由编者在导出表上续填）。
    """
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
        note or "",  # 优化要点：有在线修订取其 note，否则留空由编者续填
    ]


def build_export_csv(templates: List[Dict[str, Any]],
                     notes: Optional[Dict[int, str]] = None) -> str:
    """模板列表 → CSV 文本（§6.4 列结构；列序固定 10 列不变）。

    notes（FX-38 可选）：{sense_id: 优化要点}——有在线人工修订的义位把
    其 note 回填进"优化要点"列，无则留空（编者续填口径不变）。缺省 None
    时行为与历史版本逐字节一致（tests/test_template_engine.py TestExport
    的旧断言兼容）。

    每个单元格过 src/security.sanitize_csv_value：以 = + - @ \\t 开头的
    文本前置单引号，防 Excel/WPS 公式注入（CSV Injection）。
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_CSV_COLUMNS)
    _notes = notes if isinstance(notes, dict) else {}
    for tpl in templates:
        note = _notes.get(tpl.get("sense_id"))
        writer.writerow(
            [sanitize_csv_value(cell) for cell in _csv_row(tpl, note)])
    return buf.getvalue()


def overview_rows(templates: List[Dict[str, Any]],
                  revisions: Optional[Dict[int, Dict[str, Any]]] = None,
                  ) -> List[Dict[str, Any]]:
    """同簇并排总览行构造（FX-38 纯函数，tests 直接测，不碰 st./DB）。

    Args:
        templates: build_template 产物列表（含 sense_id / lemma / sense_no /
            sense_label / oald / template_text）；
        revisions: {sense_id: 最新修订行}（template_revision_db 读面产物）；
            None / 缺条目 / 库不可用空字典 → 修订列占位"—"（fail-open）。

    Returns:
        行 dict 列表：义位 / 词典原文释义 / 模板化释义（引擎） /
        人工修订版（最新） / 修订标记。
    """
    revs = revisions if isinstance(revisions, dict) else {}
    rows: List[Dict[str, Any]] = []
    for tpl in templates or []:
        if not isinstance(tpl, dict):
            continue
        sid_raw = tpl.get("sense_id")
        try:
            sid = int(sid_raw) if sid_raw is not None else None
        except (TypeError, ValueError):
            sid = None
        rev = revs.get(sid) if sid is not None else None
        rev_text = ""
        rev_ver = None
        if isinstance(rev, dict):
            rev_text = str(rev.get("revision_text") or "").strip()
            rev_ver = rev.get("version")
        lemma_no = f"{tpl.get('lemma') or ''}{tpl.get('sense_no') or ''}"
        rows.append({
            "义位": f"{lemma_no}（{tpl.get('sense_label') or ''}）",
            "词典原文释义": (tpl.get("oald") or {}).get("definition") or "",
            "模板化释义（引擎）": tpl.get("template_text") or "",
            "人工修订版（最新）": rev_text or "—",
            "修订标记": (
                f"已修订（v{rev_ver}）"
                if rev_text and rev_ver is not None else "引擎基线"),
        })
    return rows


def build_export_json(payload: Dict[str, Any]) -> str:
    """collect_cluster_templates 的结构化 JSON（ensure_ascii=False，编者可读）。"""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


# ============================================
# G3 簇锁定消费（FX-28 撰写侧；只读 writing_db 锁态读面，不改锁定写入）
# ============================================

TEMPLATE_LOCK_BADGE = "🔒 定稿基线"


def template_lock_note(lock_state: Any) -> Optional[str]:
    """locked 词簇的模板实例化标识文案（纯函数；G3 撰写侧消费）。

    lock_state 为 writing_db.get_cluster_lock_state 的返回。locked=True →
    「🔒 定稿基线」标识＋说明（该词簇义项清单已分立复核定稿 —— 本模板为
    定稿基线，查看与导出不受限；修订以新版本走审校）；未锁定 / 无簇归属 /
    入参非法 / 库不可用（读面 fail-open 降级）→ None（不加标识 —— 锁定是
    提示不是闸刀，不阻断模板页任何只读与导出动作）。
    """
    if not isinstance(lock_state, dict) or not lock_state.get("locked"):
        return None
    cluster = lock_state.get("cluster_no")
    where = f"（簇{cluster}）" if cluster is not None else ""
    return (
        f"**{TEMPLATE_LOCK_BADGE}{where}** —— 该词簇义项清单已分立复核定稿"
        "（G3 分立→释义闸门）：本模板为定稿基线，查看与导出不受限；"
        "修订以新版本提交走审校（锁定不是禁写）。"
    )


# ============================================
# Streamlit 页（页面接入由集成步骤统一做：app.py 只需调本函数）
# ============================================

def _ensure_revision_tables_once() -> None:
    """FX-38：首次进入模板页幂等建 template_revisions（flow-tables 先例）。

    建表失败按「修订不可用」降级不崩页：读面在 template_revision_db 内
    fail-open 返回空，写面返回 {"ok": False, "reason": ...}。
    """
    import streamlit as st

    if st.session_state.get("_template_rev_ready"):
        return
    try:
        from src.template_revision_db import ensure_template_revision_tables

        ensure_template_revision_tables()
        st.session_state["_template_rev_ready"] = True
    except Exception as e:  # noqa: BLE001 — 建表失败降级，不阻断页面其余功能
        logger.warning(f"render_template_page: 修订表建表降级: {e}")


def _load_latest_revisions(category: Any, language: Any,
                           sense_ids: List[Any]) -> Dict[int, Dict[str, Any]]:
    """FX-38：批義位最新修订（fail-open：任何异常 → 空字典，页面照常渲染）。"""
    try:
        from src.template_revision_db import get_latest_revisions

        return get_latest_revisions(str(category), str(language), sense_ids)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"render_template_page: 修订批量读取降级: {e}")
        return {}


def _render_revision_panel(category: Any, language: Any, sense_id: int,
                           tpl: Dict[str, Any], cluster_locked: bool) -> None:
    """FX-38：单义位人工修订面板（编辑 + 历史；页面交互闸 + 数据层二次闸）。

    权限：编纂职能 editor/reviewer/dict_admin（CAN_REVISE_ROLES 单一事实源
    在 template_revision_db）；无权限只读展示引擎基线与既有修订。
    G3 口径沿用 FX-28：「锁定＝放行撰写，不是禁写」——锁定簇不拦修订，
    仅加注记说明修订不改变撰写域已采用的基线。
    """
    import streamlit as st

    from src.guards import require_role_interactive
    from src.template_revision_db import (CAN_REVISE_ROLES, get_latest_revision,
                                          list_revisions, save_revision)
    from src.ui_kit import flash
    from src.users_db import effective_six_roles

    st.markdown("##### 人工修订（编者定稿层）")
    st.caption("在引擎基线上增删槽位、调整措辞、补充句法说明；按版本留痕，"
               "引擎输出并存，可逐版对照。")
    try:
        latest = get_latest_revision(str(category), str(language), sense_id)
    except Exception as e:  # noqa: BLE001 — 读面意外按无修订降级
        logger.warning(f"render_template_page: 修订读取降级: {e}")
        latest = None
    if cluster_locked:
        st.caption("🔒 本簇已锁定（G3 分立复核定稿）：锁定＝放行撰写、不是禁写；"
                   "此处的修订不改变撰写域已采用的基线。")
    if isinstance(latest, dict) and latest:
        who = latest.get("edited_by_name") or "—"
        note = latest.get("note")
        st.info(f"现行人工修订：v{latest.get('version')}（{who}）"
                + (f" · 优化要点：{note}" if note else ""))

    user = st.session_state.get("user")
    roles = effective_six_roles(user) if user else set()
    can_revise = bool(roles & CAN_REVISE_ROLES)
    if not can_revise:
        st.caption("✍️ 修订权限：编纂职能（editor / reviewer / dict_admin）。"
                   "当前账号无修订权限，可查看引擎基线与既有修订。")
        if isinstance(latest, dict) and latest:
            st.markdown("**人工修订版（现行）**")
            st.markdown(latest.get("revision_text") or "")
        return

    default_text = ((latest or {}).get("revision_text")
                    if isinstance(latest, dict) and latest else None) \
        or tpl.get("template_text") or ""
    default_note = ((latest or {}).get("note")
                    if isinstance(latest, dict) and latest else "") or ""
    with st.form("template_revision_form", clear_on_submit=False):
        st.markdown("**修订文本**（预填现行文本：引擎基线或最新修订）")
        # key 按义位隔离（FX-38 review 修复）：Streamlit widget 会话值优先于
        # value= 预填——若跨义位共用 key，切换义位后面板残留上一义位文本，
        # 编者会把 A 义位的修订串写进 B 义位。
        rev_text = st.text_area("修订文本", value=default_text, height=200,
                                key=f"template_rev_text_{sense_id}",
                                label_visibility="collapsed")
        note_val = st.text_input(
            "优化要点（≤500 字；随修订留痕，随 CSV「优化要点」列导出）",
            value=default_note, key=f"template_rev_note_{sense_id}")
        submitted = st.form_submit_button("保存修订（生成新版本）")
    if not submitted:
        if isinstance(latest, dict) and latest:
            with st.expander("修订历史"):
                hist = list_revisions(str(category), str(language), sense_id)
                if hist:
                    st.dataframe([{
                        "版本": f"v{h.get('version')}",
                        "修订人": h.get("edited_by_name") or "—",
                        "时间": str(h.get("created_at") or ""),
                        "优化要点": h.get("note") or "",
                    } for h in hist], hide_index=True)
                else:
                    st.caption("（暂无历史）")
        return
    try:
        require_role_interactive(
            user, CAN_REVISE_ROLES, action="模板人工修订")
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    sense_ref = f"{tpl.get('lemma') or ''}{tpl.get('sense_no') or ''}" or None
    result = save_revision(str(category), str(language), sense_id,
                           rev_text, user, note=note_val or None,
                           sense_ref=sense_ref)
    if not isinstance(result, dict) or not result.get("ok"):
        reason = (result or {}).get("reason") or "未知原因"
        st.error(f"❌ 修订未保存：{reason}")
        return
    flash(f"✅ 已保存人工修订 v{result.get('version')}"
          f"（引擎基线并存，可逐版对照）")
    st.rerun()


def render_template_page() -> None:
    """「释义模板引擎」页：母图式卡片 → 同簇并排总览 → 实例化模板卡片
    → OALD 对照 → 人工修订 → 批量导出。

    G3 消费（FX-28）：locked 词簇的模板实例化结果上方加「🔒 定稿基线」
    标识（取数经 writing_db.get_cluster_lock_state 锁态读面，fail-open
    降级不加标识）；不禁止查看/导出。
    FX-38 增能：簇级「同簇并排总览」（整簇 OALD 分散释义 vs 统一母图式
    模板一屏对照）＋ 单义位「在线人工修订」（编纂职能 editor+，按版本
    留痕，引擎输出并存为基线；修订不可用时整块降级，页面其余功能不受影响）。
    """
    import streamlit as st

    from src.category_study import category_study_ready, get_categories

    _ensure_revision_tables_once()
    st.subheader("释义模板引擎 · 母图式提炼与槽位实例化")
    st.caption(
        "聚类子簇 → 共享事件母图式（核心要素）+ 可变参数槽位 → 单义位四维模板 "
        "（图式 / 语义参数 / 句法 / 对齐预留）→ 与 OALD10 原文并排对照 → 同簇并排"
        "总览 → 批量导出。全程确定性规则拼装，不调用 LLM；模板定稿权在编者"
        "（在线人工修订，按版本留痕——论文 §6.2 人机协同）。")

    if not category_study_ready():
        st.info("范畴深挖数据尚未灌入：先运行 scripts/load_category_study.py，"
                "再回到本页。")
        return
    categories = get_categories()
    if not categories:
        st.warning("数据库中没有范畴记录。")
        return

    cat_options = [c["code"] for c in categories]
    # FX-41（批次 20 挂账项）：ui.default_category 偏好接线 —— 偏好命中
    # 选项集才改首建 index；未登录/断库/无键/值空由 get_pref fail-closed
    # 返 None，偏好不在选项集回退 0（本下拉原无 index 参数，默认即首项，
    # 行为不变；ImportError 兜底并行读面未落），不崩页面。format_func
    # 口径保持；index 只作用于首次实例化，不劫持用户手选。
    default_idx = 0
    try:
        from src.user_context_db import get_pref

        pref = get_pref("ui.default_category")
        if pref in cat_options:
            default_idx = cat_options.index(pref)
    except ImportError:  # 并行读面未落 → 按无偏好降级
        pass
    cat_code = st.selectbox(
        "范畴", options=cat_options, index=default_idx,
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

    # ---- 同簇并排总览（FX-38：范畴化释义对照——整簇一屏看「分散释义 → 统一模式」）----
    overview_members = cl.get("members") or []
    if overview_members:
        overview_ids = [int(m["sense_id"]) for m in overview_members]
        overview_tpls = instantiate_templates(
            cat_code, language, overview_ids, engine_schema=schemas)
        overview_revs = _load_latest_revisions(cat_code, language, overview_ids)
        rows = overview_rows(
            [overview_tpls[i] for i in overview_ids
             if isinstance(overview_tpls, dict) and overview_tpls.get(i)],
            overview_revs)
        st.markdown("##### 同簇并排总览（范畴化释义对照）")
        st.caption(
            "整簇一屏对照：左列词典原文各自成条、模式不一；右列同一母图式下按参数"
            "分档——同族共享什么、成员差异在哪一目了然（论文 §6.4 弧线的平台落点；"
            f"词典原文来源：{'OALD10' if language == 'en' else '现汉7'}）。")
        st.dataframe(
            rows, hide_index=True,
            column_config={
                "词典原文释义": st.column_config.TextColumn(width="large"),
                "模板化释义（引擎）": st.column_config.TextColumn(width="large"),
                "人工修订版（最新）": st.column_config.TextColumn(width="large"),
            },
        )

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

    # G3 锁定状态读面消费（FX-28）：locked 词簇的模板实例化结果加
    # 「🔒 定稿基线」标识（不禁止查看/导出；读面 fail-open 降级时不加）。
    try:
        from src.writing_db import get_cluster_lock_state

        lock_state = get_cluster_lock_state(str(cat_code), sense_id)
    except Exception as e:  # noqa: BLE001 — 读面意外按锁态未知降级，不崩页
        logger.warning(f"render_template_page: 锁态读面降级: {e}")
        lock_state = {"locked": False, "reason": "db_unavailable"}
    cluster_locked = bool(
        isinstance(lock_state, dict) and lock_state.get("locked"))
    lock_note = template_lock_note(lock_state)

    st.markdown("##### 实例化模板（四维结构）")
    if lock_note:
        st.markdown(lock_note)
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

    # ---- 人工修订面板（FX-38：编者在线修订，版本留痕；引擎输出并存为基线）----
    _render_revision_panel(cat_code, language, sense_id, tpl, cluster_locked)

    st.divider()

    # ---- 批量导出（当前簇全部义位）----
    st.markdown("##### 批量导出（当前簇全部义位）")
    if st.button("生成当前簇全部模板", key="template_collect"):
        try:
            guards.require_dict_admin()  # §15：内容性导出仅词典管理员
        except PermissionError as e:
            st.error(f"⛔ {e}")
            st.stop()
        from src.tools.registry import get_tool as _get_tool
        _tpl = _get_tool("template")
        st.session_state["template_export"] = (
            _tpl.run({"category": cat_code, "language": language,
                      "cluster_no": cl.get("cluster_no")})
            if _tpl is not None else
            collect_cluster_templates(cat_code, language,
                                      cl.get("cluster_no")))
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
        baseline = " · 🔒 定稿基线（G3 分立复核定稿）" if cluster_locked else ""
        st.caption(
            f"已生成 {n} 条模板（簇{payload['cluster'].get('cluster_no')}）"
            f"{baseline}。")
        try:
            # FX-38：有在线修订的义位把其优化要点回填进 CSV「优化要点」列
            # （fail-open：库不可用 → 空字典，列留空由编者续填，口径不变）
            from src.template_revision_db import get_latest_notes

            _notes = get_latest_notes(
                str(cat_code), str(language),
                [t.get("sense_id") for t in payload["templates"]])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"render_template_page: CSV 优化要点回填降级: {e}")
            _notes = {}
        csv_bytes = build_export_csv(
            payload["templates"], _notes).encode("utf-8-sig")
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
