"""聚类可视化与典型性排序 —— 范畴深挖的谱系树（F3）与 medoid 典型性排序（F6）。

补齐《白话版对照清单》第二档缺口（docs/p1/白话版对照清单.md §三）：

  * F3 谱系树（dendrogram）  论文 §5.1：聚类产出「谱系树」可交互切割；
    本模块用 scipy average 联接画树，并标注 k=5 探索性切分参考线。
  * F6 medoid 典型性排序     论文 §5.2：每簇按「到簇代表点的距离」分
    原型(prototype)/次典型(typical)/边缘(periphery)三级，程序化判定。

数据链（复用 src/category_study.py 的 cs_* 8 表）：

  cs_cluster_runs → cs_clusters → cs_cluster_members → cs_senses/cs_lexemes
  特征矩阵：cs_sense_features（in_clustering=1 的列进 Gower 距离）

特征 value_type 来自范畴包（configs/motion/features.yaml，经
src/category_pack.load_pack），决定 Gower 分支（框架文档 §4「引擎层不变项」）：

  binary / nominal → 不一致记 1；ordinal → |x−y| / 值域跨度（values 键 min-max）。
  Gower 距离 = 各特征相异度的均值（无共同特征的义位对记 0，实际编码矩阵
  15 列齐全，不会触发）。

范畴名解析：本模块的 ``category`` 参数接受范畴包目录名（configs/<category>/，
如 motion —— 与页面选择器一致）或范畴深挖 categories.code（如 RUN）。
包名 → 研究范畴代号的对应关系由 PACK_TO_STUDY_CODE 声明（d1 试点：
motion 包的研究登记名是 RUN 跑范畴）。

页面接入：render_cluster_analysis_page() 由集成步骤挂进 app.py 的页面分派，
本模块不修改 app.py。
"""

from __future__ import annotations

import logging
import math
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.category_pack import CategoryPackError, CATEGORIES, VALUE_TYPES, load_pack
from src.category_study import (
    get_categories,
    get_cluster_runs,
    get_clusters_with_members,
)
from src.design_system import HEADER_H1, HEADER_H3
from src.mysql_db import cache_scope_key, get_db_cursor

logger = logging.getLogger(__name__)

# scipy 为 dendrogram 的可选依赖（requirements.txt 已列）。缺失时本模块的
# medoid 排序照常工作，仅谱系树功能降级报错（与 krippendorff 同降级口径）。
try:
    import numpy as _np
    from scipy.cluster.hierarchy import linkage as _scipy_linkage
    from scipy.spatial.distance import squareform as _scipy_squareform

    HAS_SCIPY = True
except ImportError:  # pragma: no cover - 环境无 scipy 时才触发
    HAS_SCIPY = False

# ============================================
# 配置常量
# ============================================

# 范畴包目录名 → 范畴深挖 categories.code。包是引擎视角的研究对象配置，
# categories.code 是研究登记名 —— d1 试点：motion 包 → RUN 跑范畴。
PACK_TO_STUDY_CODE = {"motion": "RUN"}

# 默认语言清单（页面语言选择器）
LANGUAGES = ("en", "zh")
LANGUAGE_LABELS = {"en": "英语", "zh": "汉语"}

# 典型性三级（tier）标签：内部键英文、展示中文（论文 §5.2 原型/次典型/边缘）
TIER_PROTOTYPE = "prototype"
TIER_TYPICAL = "typical"
TIER_PERIPHERY = "periphery"
TIER_LABELS = {
    TIER_PROTOTYPE: "原型",
    TIER_TYPICAL: "次典型",
    TIER_PERIPHERY: "边缘",
}
# tier 颜色（沿用 src/design_system 的语义色；徽章底色 / plotly 分色共用）
TIER_COLORS = {
    TIER_PROTOTYPE: "#48bb78",   # SUCCESS_COLOR
    TIER_TYPICAL: "#4299e1",     # INFO_COLOR
    TIER_PERIPHERY: "#a0aec0",   # TEXT_DISABLED
}
MEDOID_COLOR = "#ed8936"         # WARNING_COLOR：medoid 徽章金色系


# ============================================
# 范畴解析与特征元数据
# ============================================

def _pack_name_for(category: str) -> str:
    """范畴参数 → 范畴包目录名（供 load_pack 取 value_type）。

    motion（包名）→ motion；RUN（研究代号）→ 反查 PACK_TO_STUDY_CODE；
    其他值原样返回（调用方对 load_pack 失败已有降级）。
    """
    cat = str(category or "").strip()
    if cat.lower() in PACK_TO_STUDY_CODE:
        return cat.lower()
    for pack, code in PACK_TO_STUDY_CODE.items():
        if code.upper() == cat.upper():
            return pack
    return cat


def _resolve_study_code(category: str) -> Optional[str]:
    """范畴参数 → 范畴深挖 categories.code（无已灌数据的范畴返回 None）。

    先按 categories.code 直接匹配（大小写不敏感，兼容 RUN 与 run），
    再按 PACK_TO_STUDY_CODE 把包名（motion）映射到研究代号（RUN）。
    """
    cat = str(category or "").strip()
    if not cat:
        return None
    codes = {str(r["code"]).upper(): str(r["code"]) for r in get_categories()}
    if cat.upper() in codes:
        return codes[cat.upper()]
    mapped = PACK_TO_STUDY_CODE.get(cat.lower())
    if mapped and mapped.upper() in codes:
        return codes[mapped.upper()]
    return None


def load_feature_types(category: str) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
    """从范畴包 features.yaml 读聚类特征的 value_type 与 ordinal 值域。

    Returns:
        (value_types, ranges)：
        value_types  {特征码: "binary"|"nominal"|"ordinal"}（仅 in_clustering=true）；
        ranges       {ordinal 特征码: (min, max)}，来自 values 键（如 P5 → (0, 2)）。
        包缺失/自检未过 → 空 dict（调用方把未知特征当 nominal 处理并告警）。
    """
    pack_name = _pack_name_for(category)
    try:
        pack = load_pack(pack_name)
    except CategoryPackError as exc:
        logger.warning(f"load_feature_types: 范畴包 {pack_name} 加载失败，"
                       f"未知特征将按 nominal 处理: {exc}")
        return {}, {}
    value_types: Dict[str, str] = {}
    ranges: Dict[str, Tuple[float, float]] = {}
    for feat in pack["features"].get("features") or []:
        if not feat.get("in_clustering"):
            continue  # A1-A3 核验区不进聚类矩阵（与 cs_sense_features.in_clustering 同口径）
        code = str(feat.get("code") or "").strip()
        if not code:
            continue
        vt = feat.get("value_type")
        value_types[code] = vt if vt in VALUE_TYPES else "nominal"
        if value_types[code] == "ordinal":
            keys: List[float] = []
            for k in (feat.get("values") or {}).keys():
                try:
                    keys.append(float(k))
                except (TypeError, ValueError):
                    continue
            if len(keys) >= 2:
                ranges[code] = (min(keys), max(keys))
    return value_types, ranges


# ============================================
# Gower 相异度（value_type 分支：binary/nominal 记不一致，ordinal 归一差值）
# ============================================

def gower_distance(vec_a: Dict[str, int], vec_b: Dict[str, int],
                   value_types: Dict[str, str],
                   ranges: Optional[Dict[str, Tuple[float, float]]] = None) -> float:
    """两条特征向量的 Gower 相异度（各特征分支均值，∈ [0, 1]）。

    Args:
        vec_a/vec_b: 特征向量 {特征码: 编码值}；缺失特征跳过不计入均值。
        value_types: {特征码: value_type}；binary/nominal 不一致记 1，
            ordinal 记 |a−b|/(max−min)（ranges 提供值域，缺省按 (0, 2)）。
        ranges: ordinal 特征的值域表（load_feature_types 返回的 ranges）。

    Returns:
        相异度均值；无共同特征时记 0.0（实际编码矩阵 15 列齐全，不触发）。
    """
    common = [code for code in value_types if code in vec_a and code in vec_b]
    if not common:
        return 0.0
    total = 0.0
    for code in common:
        a, b = vec_a[code], vec_b[code]
        if value_types.get(code) == "ordinal":
            lo, hi = (ranges or {}).get(code, (0.0, 2.0))
            span = hi - lo
            total += abs(a - b) / span if span else 0.0
        else:  # binary / nominal → 不一致记 1（features.yaml 头注口径）
            total += 0.0 if a == b else 1.0
    return total / len(common)


def gower_matrix(vectors: Sequence[Dict[str, int]],
                 value_types: Dict[str, str],
                 ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                 ) -> List[List[float]]:
    """Gower 相异度矩阵（对称、对角 0）。第 i 行对应 vectors[i]。"""
    n = len(vectors)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = gower_distance(vectors[i], vectors[j], value_types, ranges)
            matrix[i][j] = matrix[j][i] = d
    return matrix


def medoid_index(dist_matrix: Sequence[Sequence[float]]) -> int:
    """簇 medoid 的下标：到其他成员平均距离最小者（平局取下标最小者）。

    平均距离分母为 n-1（其余成员数）；单成员簇平均距离记 0（自身即 medoid）。
    """
    n = len(dist_matrix)
    if n == 0:
        raise ValueError("dist_matrix 为空，无法选 medoid")
    averages = [
        sum(dist_matrix[i]) / (n - 1) if n > 1 else 0.0
        for i in range(n)
    ]
    return min(range(n), key=lambda i: (averages[i], i))


def assign_tiers(distances: Sequence[float],
                 prototype_share: float = 1 / 3,
                 periphery_share: float = 1 / 3) -> List[str]:
    """按到 medoid 距离的排名划三级典型性（返回与 distances 同序的 tier 列表）。

    默认三分位：最近 1/3 = prototype（原型）、中 1/3 = typical（次典型）、
    最远 1/3 = periphery（边缘）。份额可配置（prototype_share /
    periphery_share，typical 自动取中间余量）；向上取整保证小簇也有原型，
    份额之和超 1 时边缘层被压缩（prototype 优先）。

    平局按输入下标序稳定切分（medoid 距离 0 恒居首 → 恒为 prototype）。
    """
    n = len(distances)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: (distances[i], i))
    n_proto = max(0, min(math.ceil(n * prototype_share), n))
    n_periph = max(0, min(math.ceil(n * periphery_share), n - n_proto))
    tiers: List[Optional[str]] = [None] * n
    for rank, idx in enumerate(order):
        if rank < n_proto:
            tiers[idx] = TIER_PROTOTYPE
        elif rank >= n - n_periph:
            tiers[idx] = TIER_PERIPHERY
        else:
            tiers[idx] = TIER_TYPICAL
    return [t or TIER_TYPICAL for t in tiers]


# ============================================
# 数据装载（cs_* 表 → 特征矩阵 + 簇结构）
# ============================================

def _resolve_run(category_id: int, language: str,
                 run_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """选定聚类运行：显式 run_id（须属于该范畴+语言），否则取最新（id 最大）。"""
    runs = [r for r in get_cluster_runs(category_id, language)]
    if run_id is not None:
        for run in runs:
            if int(run["run_id"]) == int(run_id):
                return run
        logger.warning(f"run_id={run_id} 不属于 category_id={category_id} "
                       f"language={language}，回退到最新运行")
    return max(runs, key=lambda r: int(r["run_id"])) if runs else None


def _load_cluster_matrix(category: str, language: str,
                         run_id: Optional[int] = None,
                         ) -> Optional[Dict[str, Any]]:
    """装载一个聚类运行的全部分析输入（compute_medoid_ranking /
    build_dendrogram_data 共用，保证谱系树与典型性排序出自同一特征矩阵）。

    Returns:
        {"study_code", "run", "clusters", "value_types", "ranges"}；
        clusters 每项 {"cluster_id", "cluster_no", "name", "size", "members"}，
        members 每项 {"sense_id", "verb", "sense_no", "sense_label",
        "features"}（features 仅含 cs_sense_features.in_clustering=1 的列）。
        范畴未灌数据 / 语言无运行 / 运行无簇 → None。
    """
    study_code = _resolve_study_code(category)
    if study_code is None:
        return None
    categories = [c for c in get_categories() if str(c["code"]) == study_code]
    if not categories:
        return None
    run = _resolve_run(int(categories[0]["id"]), language, run_id)
    if run is None:
        return None
    clusters = get_clusters_with_members(int(run["run_id"]))
    if not clusters:
        return None

    # in_clustering=1 的特征列（cs_sense_features 口径；A1-A3 核验区被排除）
    sense_ids = [int(m["sense_id"]) for cl in clusters for m in cl["members"]]
    features: Dict[int, Dict[str, int]] = {}
    if sense_ids:
        placeholders = ",".join(["%s"] * len(sense_ids))
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    f"""SELECT sense_id, feature_code, value
                        FROM cs_sense_features
                        WHERE sense_id IN ({placeholders})
                          AND in_clustering = 1""",
                    sense_ids,
                )
                for row in cursor.fetchall():
                    features.setdefault(int(row["sense_id"]), {})[
                        str(row["feature_code"])] = int(row["value"])
        except Exception as e:
            logger.error(f"_load_cluster_matrix 特征查询失败: {e}")
            return None

    value_types, ranges = load_feature_types(category)
    out_clusters: List[Dict[str, Any]] = []
    for cl in clusters:
        members = []
        for m in cl["members"]:
            members.append({
                "sense_id": int(m["sense_id"]),
                "verb": str(m["lemma"]),
                "sense_no": m["sense_no"],
                "sense_label": str(m["sense_label"]),
                "features": features.get(int(m["sense_id"]), {}),
            })
        out_clusters.append({
            "cluster_id": int(cl["cluster_id"]),
            "cluster_no": int(cl["cluster_no"]),
            "name": str(cl["name"]),
            "size": len(members),
            "members": members,
        })
    return {
        "study_code": study_code,
        "run": run,
        "clusters": out_clusters,
        "value_types": value_types,
        "ranges": ranges,
    }


def _effective_types(matrix: Dict[str, Any],
                     value_types: Optional[Dict[str, str]],
                     ranges: Optional[Dict[str, Tuple[float, float]]],
                     ) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
    """合并显式指定的 value_types/ranges（测试/换包场景）与包元数据。"""
    vt = dict(matrix["value_types"] or {})
    rg = dict(matrix["ranges"] or {})
    if value_types:
        vt.update(value_types)
    if ranges:
        rg.update(ranges)
    return vt, rg


def _nominal_fallback(vectors: Sequence[Dict[str, int]],
                      value_types: Dict[str, str],
                      ranges: Dict[str, Tuple[float, float]],
                      ) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
    """特征元数据为空时的 nominal 兜底（S2 review 修复，与 semantic_search 同口径）。

    load_feature_types 对包缺失/自检未过返回空 dict，契约是「调用方把未知
    特征按 nominal 处理并告警」。若把空 value_types 直接传进 gower_distance，
    所有特征都不在 value_types 里 → 每一对都被判「无共同特征」记 0，medoid
    排序与谱系树会静默产出全零距离的退化结果（tier 按行序乱贴）。故在
    元数据为空而向量确有编码时，把出现过的特征码按 nominal 兜底并告警，
    与 semantic_search.search_similar_senses 对同一条件的降级语义保持一致。
    """
    if value_types or not vectors:
        return value_types, ranges
    codes = sorted({code for vec in vectors for code in vec})
    if not codes:
        return value_types, ranges
    logger.warning("特征元数据为空（范畴包缺失/自检未过），%d 个特征码按 nominal 兜底: %s",
                   len(codes), ", ".join(codes))
    return {code: "nominal" for code in codes}, {}


def _sense_label(verb: str, sense_no: Any) -> str:
    """谱系树/条形图成员标签：verb-Sn（en: run-S2；zh: 跑-S②）。"""
    sn = "?" if sense_no is None or str(sense_no) == "" else str(sense_no)
    return f"{verb}-S{sn}"


# ============================================
# F6 medoid 典型性排序
# ============================================

def compute_medoid_ranking(category: str = "motion",
                           language: str = "en",
                           run_id: Optional[int] = None,
                           value_types: Optional[Dict[str, str]] = None,
                           ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                           prototype_share: float = 1 / 3,
                           periphery_share: float = 1 / 3,
                           ) -> List[Dict[str, Any]]:
    """每簇的 medoid 典型性排序（论文 §5.2 的程序化原型/次典型/边缘判定）。

    对选定运行的每个簇：取成员 in_clustering 特征向量 → Gower 相异度矩阵 →
    medoid = 簇内到其他成员平均距离最小的成员 → 各成员按到 medoid 的距离
    排名划 tier（默认最近 1/3 原型 / 中 1/3 次典型 / 最远 1/3 边缘）。

    Args:
        category: 范畴包名（motion）或研究代号（RUN），见模块 docstring。
        language: "en" / "zh"。
        run_id: 指定聚类运行；None 取该语言最新运行。
        value_types/ranges: 显式特征元数据（缺省从范畴包 features.yaml 读）。
        prototype_share/periphery_share: 三分位份额（默认 1/3、1/3）。

    Returns:
        按 cluster_no 排序的簇列表，每项::

            {"cluster_id", "cluster_no", "cluster_name", "size",
             "medoid": {sense_id, verb, sense_no, sense_label, gower_to_medoid, tier},
             "members": [{sense_id, verb, sense_no, sense_label,
                          gower_to_medoid, tier, is_medoid}, ...]}

        members 按 gower_to_medoid 升序（平局按 sense_id）；空簇跳过；
        范畴/运行不存在 → []。
    """
    matrix = _load_cluster_matrix(category, language, run_id)
    if matrix is None:
        return []
    vt, rg = _effective_types(matrix, value_types, ranges)
    # 包缺失 → 元数据为空时按 nominal 兜底（否则 gower 全 0，tier 退化，S2 review）
    vt, rg = _nominal_fallback(
        [m["features"] for cl in matrix["clusters"] for m in cl["members"]], vt, rg)

    ranking: List[Dict[str, Any]] = []
    for cl in matrix["clusters"]:
        members = cl["members"]
        if not members:
            continue  # 空簇（理论上有外键就不该出现，防御性跳过）
        vectors = [m["features"] for m in members]
        dist = gower_matrix(vectors, vt, rg)
        med_idx = medoid_index(dist)
        tiers = assign_tiers([dist[med_idx][i] for i in range(len(members))],
                             prototype_share, periphery_share)
        rows = []
        for i, m in enumerate(members):
            rows.append({
                "sense_id": m["sense_id"],
                "verb": m["verb"],
                "sense_no": m["sense_no"],
                "sense_label": m["sense_label"],
                "gower_to_medoid": dist[med_idx][i],
                "tier": tiers[i],
                "is_medoid": i == med_idx,
            })
        rows.sort(key=lambda r: (r["gower_to_medoid"], r["sense_id"]))
        medoid = next(r for r in rows if r["is_medoid"])
        ranking.append({
            "cluster_id": cl["cluster_id"],
            "cluster_no": cl["cluster_no"],
            "cluster_name": cl["name"],
            "size": len(rows),
            "medoid": {k: medoid[k] for k in
                       ("sense_id", "verb", "sense_no", "sense_label",
                        "gower_to_medoid", "tier")},
            "members": rows,
        })
    ranking.sort(key=lambda c: c["cluster_no"])
    return ranking


# ============================================
# F3 谱系树（dendrogram）
# ============================================

def linkage_from_distance_matrix(dist_matrix: Sequence[Sequence[float]],
                                 method: str = "average") -> List[List[float]]:
    """由预计算相异度矩阵做层次聚类（scipy linkage，需先 squareform 压缩）。

    scipy 不原生支持 Gower 度量，故先算好方阵再 squareform 传入；
    method 默认 average（UPGMA，与 d1 聚类运行的 algorithm 口径一致）。
    返回 linkage 矩阵（n-1 行 × 4 列：idx1, idx2, dist, count）。
    """
    if not HAS_SCIPY:
        raise ImportError("scipy 未安装，无法计算谱系树（pip install scipy）")
    if len(dist_matrix) < 2:
        raise ValueError("谱系树至少需要 2 个观测")
    condensed = _scipy_squareform(_np.asarray(dist_matrix, dtype=float))
    z = _scipy_linkage(condensed, method=method)
    return [[float(v) for v in row] for row in z]


def cut_height_for(linkage_matrix: Sequence[Sequence[float]], k: int) -> Optional[float]:
    """切成 k 簇的参考高度：首个会跌破 k 簇的合并（第 n-k+1 次）的高度。

    参考线画在「再合并一次就会跌破 k 簇」的那次合并上：平均联接单调，
    高度 < 该值的合并恰有 n-k 次 → k 簇（与 plotly color_threshold 及
    test_cut_height_yields_k_clusters 的严格小于口径一致；S1 review 订正
    原稿「第 (n-k) 次合并的高度」的措辞 —— 代码取行 n-k 即第 n-k+1 次
    合并，行为不变）；k=1 取最后一次合并的高度（其上方即单簇）；
    k 出界返回 None。
    """
    n = len(linkage_matrix) + 1
    if not (1 <= k < n):
        return None
    row = n - k if k >= 2 else n - 2
    return float(linkage_matrix[row][2])


def build_dendrogram_data(category: str = "motion",
                          language: str = "en",
                          run_id: Optional[int] = None,
                          value_types: Optional[Dict[str, str]] = None,
                          ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                          ) -> Dict[str, Any]:
    """谱系树可绘数据（F3）：Gower 相异度 → average 联接 → linkage 矩阵。

    成员集与 compute_medoid_ranking 同源（同一运行的全体簇成员，
    按 verb/sense_no/sense_label 排序保证叶序确定），labels = verb-Sn。

    Returns:
        {"labels", "linkage"（n-1×4 列表）, "distance_matrix"（Gower 方阵）,
         "n_senses", "method", "metric",
         "run_id", "language", "study_code", "k"（运行参数的探索性切分）,
         "cut_height"（切成 k 簇的参考高度）, "members"}；
        scipy 缺失抛 ImportError；范畴/运行不存在 → {}。
    """
    matrix = _load_cluster_matrix(category, language, run_id)
    if matrix is None:
        return {}
    vt, rg = _effective_types(matrix, value_types, ranges)

    members: List[Dict[str, Any]] = []
    for cl in matrix["clusters"]:
        for m in cl["members"]:
            members.append({**m, "cluster_id": cl["cluster_id"],
                            "cluster_no": cl["cluster_no"]})
    members.sort(key=lambda m: (m["verb"], str(m["sense_no"]), m["sense_label"]))
    if len(members) < 2:
        return {}

    # 包缺失 → 元数据为空时按 nominal 兜底（否则 gower 全 0，树退化，S2 review）
    vt, rg = _nominal_fallback([m["features"] for m in members], vt, rg)
    dist = gower_matrix([m["features"] for m in members], vt, rg)
    z = linkage_from_distance_matrix(dist, method="average")
    run = matrix["run"]
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    k = params.get("k") if isinstance(params, dict) else None
    try:
        k = int(k) if k is not None else None
    except (TypeError, ValueError):
        k = None
    return {
        "labels": [_sense_label(m["verb"], m["sense_no"]) for m in members],
        "linkage": z,
        "distance_matrix": dist,
        "n_senses": len(members),
        "method": "average",
        "metric": "gower",
        "run_id": int(run["run_id"]),
        "language": language,
        "study_code": matrix["study_code"],
        "k": k,
        "cut_height": cut_height_for(z, k) if k else None,
        "members": members,
    }


# ============================================
# Streamlit 页面（F3 谱系树 + F6 典型性排序 双 tab）
# ============================================

def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span，文本须先经 _html_escape）。"""
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'padding:1px 8px;border-radius:10px;font-size:0.78em;'
        f'margin-right:4px;">{text}</span>'
    )


def _member_name(m: Dict[str, Any]) -> str:
    """成员显示名：verb·sense_no（义位标签），全部经 _html_escape。"""
    no = f"·{_html_escape(str(m['sense_no']))}" if m.get("sense_no") else ""
    return f"{_html_escape(str(m['verb']))}{no} {_html_escape(str(m['sense_label']))}"


@st.cache_data(ttl=600, show_spinner=False)
def _load_page_data(cache_scope: str, category: str, language: str) -> Dict[str, Any]:
    """页面级缓存（10 分钟）：典型性排序 + 谱系树数据一次装载。

    首参 cache_scope（**不得**加下划线前缀）由调用方传
    mysql_db.cache_scope_key()：st.cache_data 的键只含入参，且**下划线开头的
    参数不参与哈希**（Streamlit 明确行为）—— 曾把作用域传进 `_cache_scope`
    下划线参数，等于没进键，测试切换 MYSQL_DATABASE 指向测试库时键不变，
    会把业务库的聚类矩阵串进「空测试库」用例（S1 review 修复本身失效，
    S3 合跑复现：换库必须换缓存槽位，跨库隔离）。"""
    ranking = compute_medoid_ranking(category, language)
    dendro: Dict[str, Any] = {}
    scipy_missing = False
    if ranking:
        try:
            dendro = build_dendrogram_data(category, language)
        except ImportError:
            scipy_missing = True
    return {"ranking": ranking, "dendro": dendro, "scipy_missing": scipy_missing}


def _render_dendrogram(dendro: Dict[str, Any]) -> None:
    """谱系树 tab：plotly create_dendrogram（预计算 Gower 矩阵直传）+ k 切分参考线。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>谱系树（Gower + average 层次聚类）</h3>",
                unsafe_allow_html=True)
    if not dendro or not dendro.get("linkage"):
        st.warning("谱系树数据不足（簇成员少于 2 个）。")
        return
    from plotly.figure_factory import create_dendrogram

    k = dendro.get("k")
    cut = dendro.get("cut_height")
    # scipy 不原生支持 gower 度量：预计算好的 Gower 方阵经 distfun 压缩成
    # 紧凑距离向量，linkagefun 固定 average（UPGMA），与 d1 运行口径一致。
    # plotly 要求 X 为二维 ndarray（列表无 .shape 属性）。
    fig = create_dendrogram(
        _np.asarray(dendro["distance_matrix"], dtype=float),
        distfun=_scipy_squareform,
        linkagefun=lambda d: _scipy_linkage(d, method="average"),
        labels=dendro["labels"],
        color_threshold=cut,
    )
    if cut is not None:
        fig.add_hline(
            y=cut, line_dash="dash", line_color="#e53e3e",
            annotation_text=f"k={k} 探索性切分参考线",
            annotation_position="top right",
        )
    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(tickfont=dict(size=10)),
        plot_bgcolor="#ffffff",
    )
    st.plotly_chart(fig, use_container_width=True)
    if cut is not None:
        cut_note = (f"红色虚线为 k={k} 的探索性切分参考线"
                    f"（该高度再合并一次即跌破 {k} 簇）—— ")
    else:
        cut_note = "运行参数未提供有效 k，未画切分参考线 —— "
    st.caption(
        f"方法：Gower 相异度（binary/nominal 不一致记 1，ordinal 归一差值）"
        f"+ average 联接（UPGMA），共 {dendro['n_senses']} 个义位、"
        f"{len(dendro['linkage'])} 次合并。{cut_note}"
        f"层次树本身支持任意高度切割，"
        f"k=5 只是 d1 试点采用的探索性解，不是唯一正确答案。"
    )


def _render_tier_bars(cluster: Dict[str, Any]) -> None:
    """单簇成员距离条形图（plotly 横条，tier 分色，最近成员在顶部）。"""
    import plotly.express as px

    members = cluster["members"]
    df = pd.DataFrame({
        "成员": [_member_name(m) for m in members],
        "到 medoid 的 Gower 距离": [m["gower_to_medoid"] for m in members],
        "典型性层级": [TIER_LABELS[m["tier"]] for m in members],
    })
    fig = px.bar(
        df, x="到 medoid 的 Gower 距离", y="成员", orientation="h",
        color="典型性层级", color_discrete_map={
            TIER_LABELS[TIER_PROTOTYPE]: TIER_COLORS[TIER_PROTOTYPE],
            TIER_LABELS[TIER_TYPICAL]: TIER_COLORS[TIER_TYPICAL],
            TIER_LABELS[TIER_PERIPHERY]: TIER_COLORS[TIER_PERIPHERY],
        },
        category_orders={"成员": df["成员"].tolist()},
        text="到 medoid 的 Gower 距离",
    )
    fig.update_yaxes(autorange="reversed")  # 升序成员列表 → 距离最小者画在顶部
    fig.update_traces(texttemplate="%{x:.3f}", textposition="outside")
    fig.update_layout(
        height=max(240, 46 * len(members) + 90),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(range=[0, max(0.05, max(
            m["gower_to_medoid"] for m in members) * 1.15)]),
        plot_bgcolor="#ffffff",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_cluster_analysis_page() -> None:
    """🧬 聚类可视化与典型性排序页面：选范畴/语言 → 谱系树 + 典型性排序双 tab。

    范畴选择器列出范畴包目录（configs/<category>/，CATEGORIES()）；
    语言 en/zh；数据取该语言最新聚类运行（cs_cluster_runs）。
    页面接入由集成步骤统一挂进 app.py。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>🧬 聚类可视化与典型性排序</h1>",
                unsafe_allow_html=True)
    st.caption(
        "F3 谱系树（Gower + average 层次聚类，k=5 探索性切分参考线）｜ "
        "F6 典型性排序（medoid 到簇内成员平均距离最小 → 原型/次典型/边缘三级）"
    )

    packs = list(CATEGORIES()) or ["motion"]
    default_idx = packs.index("motion") if "motion" in packs else 0
    category = st.selectbox("范畴", options=packs, index=default_idx,
                            key="ca_category")
    language = st.selectbox("语言", options=list(LANGUAGES),
                            format_func=lambda lang: LANGUAGE_LABELS.get(lang, lang),
                            key="ca_language")

    data = _load_page_data(cache_scope_key(), category, language)
    if not data["ranking"]:
        st.info(
            f"范畴 {category}（{LANGUAGE_LABELS.get(language, language)}侧）"
            "暂无聚类运行数据。请先运行 scripts/load_category_study.py "
            "灌入范畴深挖数据。"
        )
        return
    if data.get("scipy_missing"):
        st.warning("scipy 未安装，谱系树 tab 不可用（pip install scipy）；"
                   "典型性排序不受影响。")

    tab_tree, tab_typical = st.tabs(["🌳 谱系树", "🏆 典型性排序"])

    with tab_tree:
        _render_dendrogram(data["dendro"])

    with tab_typical:
        st.markdown(f"<h3 style='{HEADER_H3}'>各簇典型性排序"
                    f"（medoid = 簇内到其他成员平均距离最小者）</h3>",
                    unsafe_allow_html=True)
        st.caption(
            "层级三分位：距 medoid 最近 1/3 = 原型（prototype），中 1/3 = 次典型"
            "（typical），最远 1/3 = 边缘（periphery）；medoid 距离恒为 0，"
            "必属原型。"
        )
        for cluster in data["ranking"]:
            medoid = cluster["medoid"]
            # expander 标签不渲染 HTML（streamlit 前端 allowHTML=False，S1 review）：
            # 徽章 span 会原样显示成字面文本，medoid 改用纯文本标注；
            # 标签由 Streamlit 自带转义，DB 文本无需（也不能）先过 _html_escape。
            title = str(cluster["cluster_name"]).split("（")[0]
            medoid_no = f"·{medoid['sense_no']}" if medoid.get("sense_no") else ""
            header = (
                f"簇{cluster['cluster_no']} · {title}"
                f"（{cluster['size']} 成员） 🏆 medoid: "
                f"{medoid['verb']}{medoid_no} {medoid['sense_label']}"
            )
            with st.expander(header, expanded=len(data["ranking"]) <= 6):
                _render_tier_bars(cluster)
                legend = " ".join(
                    _badge(f"{TIER_LABELS[t]} "
                           f"({sum(1 for m in cluster['members'] if m['tier'] == t)})",
                           TIER_COLORS[t])
                    for t in (TIER_PROTOTYPE, TIER_TYPICAL, TIER_PERIPHERY)
                )
                st.markdown(legend, unsafe_allow_html=True)
