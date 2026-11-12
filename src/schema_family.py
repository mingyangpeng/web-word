"""图式范畴化引擎（批次 32）——工作流缺失环节的平台化。

理论（docs/research/papers/lexikos/给师兄讨论-Project的思路(1).docx「共享图式
提取、图式范畴化与多维释义模板构建」段）：
    共享事件图式从同一子范畴内提炼；**图式范畴化，是对提取得到的事件图式
    本身进行归纳，梳理图式之间的亲缘关系与家族相似性，建立更高层级的
    事件类型谱系**。

方法（方法论自洽：把义位聚类的同一套机器用在图式对象上——
    Gower nominal 相异度 + average linkage/UPGMA + medoid 代表）：
    * 图式特征向量：各语义槽的三级归属（核心=2 / 可变槽位=1 / 缺省=0），
      有序分类特征；特征码全集 = 全部图式槽位码并集；
    * Gower nominal：逐码比对三级归属，一致记 0、不同记 1，除以可比码数；
    * UPGMA（average linkage）对图式聚类 → **图式家族**（更高层级事件类型）；
    * 每家族 medoid（到族内其他图式平均距离最小者）= **代表图式**；
    * 谱系输出：家族表（成员图式/代表图式/族内平均距离）＋亲缘矩阵。

插件化（批次 30 架构）：
    * 本引擎挂 P 构件（编纂工序链——图式范畴化是工序 8 图式提取的下游）；
    * ToolSpec 注册 schema_family_tool（第 12 个内置工具，两步激活照全仓
      口径）；页面入口在语义分析「🌐 图式谱系」tab；
    * 结果落库 cs_schema_family_runs/members（可选持久化，同语言最新运行
      取最新家族运行）。

降级：范畴未灌数据/簇<2/库不可用 → 结构化空态（不崩，R4 口径）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

logger = logging.getLogger(__name__)

# 三级归属（有序分类：图式槽位的参与层级）
LEVEL_CORE = 2      # schema_core：簇内均值 ≥ 阈值，全簇共享
LEVEL_SLOT = 1      # variable_slots：簇内分歧，可变参数槽
LEVEL_ABSENT = 0    # 未参与

# Gower nominal 三级比对：一致 0、不同 1（有序差异不取数值差——图式槽位
# 的「核心 vs 槽位」是类型差异不是程度差异，nominal 处理避免循环论证）
_CORE_THRESHOLD = 0.5


def schema_level_vector(schema: Dict[str, Any]) -> Dict[str, int]:
    """单图式 → 槽位码三级归属向量 {code: 2|1|0}。

    schema_core（均值 ≥0.5）→ 2；variable_slots → 1；两者皆无 → 0。
    """
    vec: Dict[str, int] = {}
    for f in schema.get("core_features") or []:
        code = str(f.get("code") or "").strip()
        if code:
            vec[code] = LEVEL_CORE
    for f in schema.get("variable_slots") or []:
        code = str(f.get("code") or "").strip()
        if code and code not in vec:
            vec[code] = LEVEL_SLOT
    return vec


def schema_gower(va: Dict[str, int], vb: Dict[str, int]) -> float:
    """两图式 Gower nominal 相异度（0=同型，1=全异；可比码=并集）。"""
    codes = set(va) | set(vb)
    if not codes:
        return 0.0
    diff = sum(1 for c in codes if va.get(c, LEVEL_ABSENT) != vb.get(c, LEVEL_ABSENT))
    return round(diff / len(codes), 4)


def schema_gower_matrix(vectors: List[Dict[str, int]]) -> List[List[float]]:
    """n 图式对称相异度矩阵（对角线 0）。"""
    n = len(vectors)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = schema_gower(vectors[i], vectors[j])
            mat[i][j] = mat[j][i] = d
    return mat


def schema_family_clusters(
    dist: List[List[float]], max_distance: float = 0.5,
) -> Tuple[List[int], List[int]]:
    """UPGMA 聚类 → 家族标签（1 起）＋每族 medoid 图式下标。

    切割标准：average linkage 谱系在 max_distance 处切割（默认 0.5——
    半数以上槽位归属一致的图式归同族）；medoid = 族内到其他成员平均
    Gower 距离最小的图式（与义位典型性 F6 同判据）。
    """
    n = len(dist)
    if n <= 1:
        return [1] * n, list(range(n))
    try:
        condensed = squareform(np.array(dist, dtype=float), checks=False)
        link = linkage(condensed, method="average")
        labels = fcluster(link, t=max_distance, criterion="distance").tolist()
    except Exception as e:  # noqa: BLE001 —— scipy 异常退化为全员单族
        logger.warning(f"schema_family 聚类失败（退化为单族）: {e}")
        return [1] * n, [0]
    families: Dict[int, List[int]] = {}
    for idx, lab in enumerate(labels):
        families.setdefault(lab, []).append(idx)
    medoids: List[int] = []
    for members in families.values():
        if len(members) == 1:
            medoids.append(members[0])
            continue
        best = min(
            members,
            key=lambda m: sum(
                dist[m][o] for o in members if o != m
            ) / (len(members) - 1),
        )
        medoids.append(best)
    return labels, medoids


def build_schema_families(schemas: List[Dict[str, Any]],
                          max_distance: float = 0.5) -> Dict[str, Any]:
    """图式范畴化主入口：图式列表 → 亲缘谱系结构化结果。

    Args:
        schemas: derive_cluster_schemas 输出（每簇一图式）。
        max_distance: 家族切割距离（默认 0.5）。

    Returns:
        {"families": [{family_no, members: [{cluster_id, cluster_no,
        cluster_name, schema_core, core_features, variable_slots}],
        prototype: <同 member 形态>, prototype_level_vector, avg_distance}],
        "labels", "medoids", "distance_matrix", "n_schemas"}；
        图式 <2 → {"families": [], "n_schemas": len(schemas)}。
    """
    vectors = [schema_level_vector(sc) for sc in schemas]
    n = len(schemas)
    if n < 2:
        return {"families": [], "n_schemas": n}
    dist = schema_gower_matrix(vectors)
    labels, medoids = schema_family_clusters(dist, max_distance)
    fam_groups: Dict[int, List[int]] = {}
    for idx, lab in enumerate(labels):
        fam_groups.setdefault(lab, []).append(idx)
    families: List[Dict[str, Any]] = []
    for fam_no in sorted(fam_groups):
        members_idx = sorted(fam_groups[fam_no])
        members = [schemas[i] for i in members_idx]
        # 代表图式：族内平均 Gower 距离最小者（与 schema_family_clusters 的
        # medoid 同判据同序——min 稳定取首个最小，medoids 仅作透明输出）
        proto_idx = (
            min(members_idx,
                key=lambda i: sum(dist[i][o] for o in members_idx if o != i)
                / (len(members_idx) - 1))
            if len(members_idx) > 1 else members_idx[0])
        distances = [dist[i][o] for i in members_idx for o in members_idx if i != o]
        avg = round(sum(distances) / len(distances), 4) if distances else 0.0
        families.append({
            "family_no": len(families) + 1,
            "members": [
                {"cluster_id": schemas[i].get("cluster_id"),
                 "cluster_no": schemas[i].get("cluster_no"),
                 "cluster_name": schemas[i].get("cluster_name"),
                 "is_prototype": i == proto_idx,
                 "level_vector": vectors[i]}
                for i in members_idx
            ],
            "prototype": {
                "cluster_no": schemas[proto_idx].get("cluster_no"),
                "cluster_name": schemas[proto_idx].get("cluster_name"),
                "schema_core": schemas[proto_idx].get("schema_core") or {},
                "core_features": schemas[proto_idx].get("core_features") or [],
            },
            "avg_distance": avg,
        })
    return {"families": families, "labels": labels, "medoids": medoids,
            "distance_matrix": dist, "n_schemas": n}


def families_summary(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """家族表读面（UI 渲染用）：家族号/成员数/代表图式/族内平均距离。"""
    return [
        {"family_no": f["family_no"],
         "members": "、".join(
             f"{m.get('cluster_no')}·{m.get('cluster_name')}" for m in f["members"]),
         "prototype": f["prototype"].get("cluster_name") or "",
         "avg_distance": f["avg_distance"]}
        for f in result.get("families", [])
    ]
