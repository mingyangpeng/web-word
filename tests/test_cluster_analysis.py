"""聚类可视化与典型性排序（cluster_analysis）测试。

三层覆盖：
  1. 纯函数（不碰数据库）：Gower 分支（binary/nominal 记不一致、ordinal
     归一差值）→ 合成特征向量构造**已知 medoid** 的小簇验证选取正确；
     tier 三分位边界（n=9 精确三等分、n=7/2/1 的小簇行为、自定义份额、
     平局稳定性）；谱系树 linkage 行数（n-1 次合并）与 k 切分高度一致性；
     批次 3 交互切割（论文 §5.1 / 对照清单 F2）：recut_clusters 的
     fcluster(maxclust) 重切（合成树 2/3/5 簇切分已知、medoid 标注、
     输入对象不可变）与 next_interactive_version 版本号生成（「交互-
     时间戳」+ 冲突递增后缀 + 重试上限）。
  2. 范畴包元数据（纯文件系统）：configs/motion/features.yaml 的
     value_type 装载与 A 区排除。
  3. 数据层与页面（需 MySQL，skipif）：种子范畴 CLUSRUN 端到端
     （medoid 先验已知，可断言精确值）+ 交互切割保存（cs_cluster_runs
     版本化：参数化 INSERT 往返、UNIQUE(category_id, language, version)
     冲突不覆盖、自动版本去重）+ AppTest 页面冒烟（含无数据降级路径、
     交互切割控件与保存流，均不需要 DB）。
  4. 批次 5（义项分立复核＋义位级图谱，论文 §7.2 / 闸门 G3）：
     * 纯函数：建议载荷校验（动作白名单/理由必填/merge 目标约束）、
       裁决门（六角色 effective + legacy role=='admin'）、簇证据组装
       （簇内平均两两距离=预计算方阵子阵）、裁决编排（decide 留痕→
       adopted 才落地）、经典 MDS 坐标（共线点精确还原/退化矩阵）、
       图谱组装（recut 分组键/medoid 星标/簇内边表降序截断）；
     * 迁移（真 MySQL）：ensure_sense_split_columns 在**合成表**上验证
       分支与幂等（ENUM 扩值保留原值默认、varchar 窄列加宽、宽列不动、
       merged_into 新增）＋ 主库 cs_senses 验收（merged_into 在场、
       既有行 status 分布不变、重复执行幂等）。独立测试库不可用时
       （web_word_user 无建库权限）合成表落在业务库、finally 清理
       —— 与本模块 CLUSRUN 种子同口径。
     * 落地执行（真 MySQL，CLUSRUN 行，teardown 级联清理）：merge/split/
       keep 往返 + 非法载荷拒绝 + adjudicate 端到端（台账留痕→cs_senses）。
     * 页面（AppTest，打桩不需要 DB）：分立复核 tab 的匿名/登录/裁决三态、
       建议提交流（载荷与台账参数捕获）、义位图谱 tab（MDS 注记/边表开关）。
  5. 批次 6（G3 闸门位 ＋ merged 消费收口，施工规范 §9）：
     * 迁移（真 MySQL）：ensure_cluster_locked_column 在**合成表**验证
       locked TINYINT(1) DEFAULT 0 幂等 ALTER（列型/默认/往返写入/二次零
       改动）＋ 主库 cs_clusters 验收（locked 在场且幂等）。
     * 锁定写库（真 MySQL，CLUSRUN 行）：set_cluster_locked 锁定/解锁
       UPDATE 往返 + 非法 id 拒绝 + 不存在簇报错 + _load_cluster_locks 读
       （cache_data 直调，先 clear 再读防进程内缓存串扰）。
     * merged 消费（纯函数）：merged_sense_display 标注（「已并入 → #N」/
       去向待补录/非 merged None）、_status_display 收口、
       sense_division_landing_counts 落地计数、build_sense_division_evidence
       的 locks→locked 徽章键、build_sense_graph_data 的 merged_ids 跳过
       （节点/边剔除、n_merged_skipped 计数、无 merged 逐位一致、全 merged
       返回空）。
     * 页面（AppTest，打桩）：簇锁定控件（匿名仅提示/裁决者锁定解锁流/
       失败报错/锁定徽章在场）、裁决区落地计数、证据表 merged 标注。

没有可用的 MySQL 时数据层/页面冒烟测试 skip（与 test_category_study 同口径）。
"""

import math
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import category_study as cs  # noqa: E402
from src import cluster_analysis as ca  # noqa: E402

# 合成特征元数据：F1/F2 binary、F3 ordinal（值域 0-2，归一除以 2）
VT = {"F1": "binary", "F2": "binary", "F3": "ordinal"}
RG = {"F3": (0, 2)}


def _db_available() -> bool:
    try:
        with cs.get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_available(), reason="MySQL 不可用，跳过聚类分析数据层测试")


# ============================================
# 1. Gower 相异度（value_type 分支）
# ============================================

class TestGowerDistance:
    def test_identical_vectors_zero(self):
        v = {"F1": 1, "F2": 0, "F3": 2}
        assert ca.gower_distance(v, v, VT, RG) == 0.0

    def test_binary_nominal_mismatch_is_one(self):
        vt = {"B": "binary", "N": "nominal"}
        assert ca.gower_distance({"B": 0}, {"B": 1}, vt) == 1.0
        assert ca.gower_distance({"B": 1}, {"B": 1}, vt) == 0.0
        # nominal 值 2 vs 0 同样只记不一致（C1 动因 0/1/2 的口径）
        assert ca.gower_distance({"N": 2}, {"N": 0}, vt) == 1.0

    def test_ordinal_normalized_difference(self):
        vt = {"O": "ordinal"}
        rg = {"O": (0, 2)}
        assert ca.gower_distance({"O": 0}, {"O": 2}, vt, rg) == 1.0
        assert ca.gower_distance({"O": 1}, {"O": 2}, vt, rg) == 0.5
        assert ca.gower_distance({"O": 1}, {"O": 1}, vt, rg) == 0.0

    def test_mixed_mean(self):
        # F1 不一致(1) + F2 一致(0) + F3 |1-2|/2(0.5) → 均值 0.5
        a = {"F1": 1, "F2": 1, "F3": 1}
        b = {"F1": 0, "F2": 1, "F3": 2}
        assert ca.gower_distance(a, b, VT, RG) == pytest.approx(0.5)

    def test_missing_features_skipped(self):
        # 只有共同特征 F1 计入均值（缺失列不摊薄）
        assert ca.gower_distance({"F1": 1, "F3": 9}, {"F1": 0}, VT, RG) == 1.0

    def test_no_common_features_zero(self):
        assert ca.gower_distance({"X": 1}, {"F1": 1}, VT, RG) == 0.0


class TestGowerMatrix:
    VECTORS = [
        {"F1": 1, "F2": 1, "F3": 1},
        {"F1": 0, "F2": 1, "F3": 2},
        {"F1": 1, "F2": 0, "F3": 0},
    ]

    def test_symmetric_zero_diagonal(self):
        d = ca.gower_matrix(self.VECTORS, VT, RG)
        assert len(d) == len(self.VECTORS)
        for i in range(len(d)):
            assert d[i][i] == 0.0
            for j in range(len(d)):
                assert d[i][j] == pytest.approx(d[j][i])

    def test_matches_pairwise(self):
        d = ca.gower_matrix(self.VECTORS, VT, RG)
        for i in range(len(self.VECTORS)):
            for j in range(len(self.VECTORS)):
                assert d[i][j] == pytest.approx(ca.gower_distance(
                    self.VECTORS[i], self.VECTORS[j], VT, RG))


# ============================================
# 2. medoid 选取（已知答案的合成簇）
# ============================================

class TestMedoidIndex:
    def test_known_medoid(self):
        """aa/bb/cc 三条完全相同的向量是平均距离最小者，平局取下标最小。"""
        vectors = [
            {"F1": 1, "F2": 1, "F3": 1},   # aa —— medoid（平局胜出：id 最小）
            {"F1": 1, "F2": 1, "F3": 1},   # bb
            {"F1": 1, "F2": 1, "F3": 1},   # cc
            {"F1": 1, "F2": 0, "F3": 1},   # dd：到前三者各 1/3
            {"F1": 0, "F2": 0, "F3": 2},   # ee：到前三者各 2.5/3
        ]
        dist = ca.gower_matrix(vectors, VT, RG)
        medoid = ca.medoid_index(dist)
        assert medoid == 0
        # 平均距离：aa/bb/cc = (1/3 + 2.5/3)/4 = 7/24；dd = 0.375；ee = 0.75
        averages = [sum(dist[i]) / (len(vectors) - 1) for i in range(5)]
        assert averages[0] == pytest.approx(7 / 24)
        assert averages[3] == pytest.approx(0.375)
        assert averages[4] == pytest.approx(0.75)

    def test_single_member_is_own_medoid(self):
        assert ca.medoid_index([[0.0]]) == 0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ca.medoid_index([])


# ============================================
# 3. tier 三分位边界
# ============================================

class TestAssignTiers:
    def test_nine_members_exact_thirds(self):
        tiers = ca.assign_tiers([float(i) for i in range(9)])
        assert tiers == [ca.TIER_PROTOTYPE] * 3 + [ca.TIER_TYPICAL] * 3 + [
            ca.TIER_PERIPHERY] * 3

    def test_seven_members_three_one_three(self):
        tiers = ca.assign_tiers([float(i) for i in range(7)])
        assert tiers.count(ca.TIER_PROTOTYPE) == 3
        assert tiers.count(ca.TIER_TYPICAL) == 1
        assert tiers.count(ca.TIER_PERIPHERY) == 3

    def test_two_members_no_typical(self):
        tiers = ca.assign_tiers([0.0, 0.7])
        assert tiers == [ca.TIER_PROTOTYPE, ca.TIER_PERIPHERY]

    def test_single_member_prototype(self):
        assert ca.assign_tiers([0.0]) == [ca.TIER_PROTOTYPE]

    def test_medoid_zero_distance_always_prototype(self):
        assert ca.assign_tiers([0.0, 0.9, 0.95])[0] == ca.TIER_PROTOTYPE

    def test_custom_shares(self):
        # 份额可配置：n=4，prototype 0.5 / periphery 0.25 → 2/1/1
        tiers = ca.assign_tiers([0.1, 0.2, 0.5, 0.9],
                                prototype_share=0.5, periphery_share=0.25)
        assert tiers == [ca.TIER_PROTOTYPE, ca.TIER_PROTOTYPE,
                         ca.TIER_TYPICAL, ca.TIER_PERIPHERY]

    def test_full_shares_propagation(self):
        # n=5，prototype 0.6 / periphery 0.2 → 3 原型 / 1 次典型 / 1 边缘
        tiers = ca.assign_tiers([0.0, 0.0, 0.1, 0.4, 0.9],
                                prototype_share=0.6, periphery_share=0.2)
        assert tiers == [ca.TIER_PROTOTYPE, ca.TIER_PROTOTYPE,
                         ca.TIER_PROTOTYPE, ca.TIER_TYPICAL,
                         ca.TIER_PERIPHERY]

    def test_ties_stable_by_index(self):
        # 全平局按输入下标序切分（ceil(1)=1 原型、1 边缘，中间次典型）
        tiers = ca.assign_tiers([0.5, 0.5, 0.5])
        assert tiers == [ca.TIER_PROTOTYPE, ca.TIER_TYPICAL,
                         ca.TIER_PERIPHERY]

    def test_empty(self):
        assert ca.assign_tiers([]) == []


# ============================================
# 4. 谱系树：linkage 一致性与 k 切分高度
# ============================================

class TestDendrogramHelpers:
    def test_linkage_two_points_single_merge(self):
        z = ca.linkage_from_distance_matrix([[0.0, 0.5], [0.5, 0.0]])
        assert len(z) == 1  # n-1 次合并
        assert z[0][2] == pytest.approx(0.5)

    def test_linkage_rows_and_final_cluster(self):
        d = ca.gower_matrix([
            {"F1": 1, "F2": 1, "F3": 0},
            {"F1": 1, "F2": 1, "F3": 1},
            {"F1": 0, "F2": 0, "F3": 1},
            {"F1": 1, "F2": 0, "F3": 2},
        ], VT, RG)
        z = ca.linkage_from_distance_matrix(d)
        assert len(z) == 3  # 4 观测 → 3 次合并
        assert z[-1][3] == pytest.approx(4.0)  # 最终合并成 1 簇
        heights = [row[2] for row in z]
        assert heights == sorted(heights)  # average 联接单调

    def test_cut_height_yields_k_clusters(self):
        d = ca.gower_matrix([
            {"F1": 1, "F2": 1, "F3": 0},
            {"F1": 1, "F2": 1, "F3": 1},
            {"F1": 0, "F2": 0, "F3": 1},
            {"F1": 1, "F2": 0, "F3": 2},
        ], VT, RG)
        z = ca.linkage_from_distance_matrix(d)
        for k in (2, 3):  # k=4（= n）按契约返回 None，见 test_cut_height_out_of_range
            cut = ca.cut_height_for(z, k)
            assert cut is not None
            n_below = sum(1 for row in z if row[2] < cut)
            assert n_below == 4 - k, f"k={k} 切分高度不一致"

    def test_cut_height_k_one_is_last_merge(self):
        z = ca.linkage_from_distance_matrix(
            [[0.0, 0.5, 0.75], [0.5, 0.0, 0.75], [0.75, 0.75, 0.0]])
        assert ca.cut_height_for(z, 1) == pytest.approx(z[-1][2])

    def test_cut_height_out_of_range(self):
        z = ca.linkage_from_distance_matrix([[0.0, 0.5], [0.5, 0.0]])
        assert ca.cut_height_for(z, 0) is None
        assert ca.cut_height_for(z, 2) is None  # k == n → None

    def test_sense_label_format(self):
        assert ca._sense_label("run", "2") == "run-S2"
        assert ca._sense_label("跑", "①") == "跑-S①"
        assert ca._sense_label("run", None) == "run-S?"
        assert ca._sense_label("run", "") == "run-S?"

    def test_single_observation_rejected(self):
        with pytest.raises(ValueError):
            ca.linkage_from_distance_matrix([[0.0]])


# ============================================
# 4b. 批次 3 交互切割（F2）：fcluster 重切 + 版本号生成（纯函数）
# ============================================

def _recut_fake_matrix() -> dict:
    """5 义位合成矩阵：aa/bb 全同、cc/dd 全同、ee 独立（切分已知，见下）。

    Gower 距离（VT/RG）：aa-bb = cc-dd = 0；{aa,bb}×{cc,dd} = 0.5；
    {aa,bb}×ee = 2.5/3；{cc,dd}×ee = 2/3 → average 联接合并高度
    [0, 0, 0.5, 0.75]，fcluster(maxclust) 的 k=2/3/5 切分先验已知。
    """
    members = [
        {"sense_id": 1, "verb": "aa", "sense_no": "1", "sense_label": "L1",
         "features": {"F1": 1, "F2": 1, "F3": 1}},
        {"sense_id": 2, "verb": "bb", "sense_no": "1", "sense_label": "L2",
         "features": {"F1": 1, "F2": 1, "F3": 1}},
        {"sense_id": 3, "verb": "cc", "sense_no": "1", "sense_label": "L3",
         "features": {"F1": 0, "F2": 1, "F3": 0}},
        {"sense_id": 4, "verb": "dd", "sense_no": "1", "sense_label": "L4",
         "features": {"F1": 0, "F2": 1, "F3": 0}},
        {"sense_id": 5, "verb": "ee", "sense_no": "1", "sense_label": "L5",
         "features": {"F1": 0, "F2": 0, "F3": 2}},
    ]
    return {
        "study_code": "RUN",
        "run": {"run_id": 7, "params": {"k": 2}, "cophenetic": 0.9,
                "version": "预编码"},
        "clusters": [{"cluster_id": 71, "cluster_no": 1, "name": "合成簇",
                      "size": 5, "members": members}],
        "value_types": VT, "ranges": RG,
    }


def _synthetic_dendro(monkeypatch) -> dict:
    """经 _load_cluster_matrix 打桩 + build_dendrogram_data 产出合成谱系树
    （真实走 gower_matrix/linkage 通路，members 按 verb 排序 aa..ee）。"""
    monkeypatch.setattr(ca, "_load_cluster_matrix",
                        lambda *a, **k: _recut_fake_matrix())
    dendro = ca.build_dendrogram_data("motion", "en")
    assert dendro, "合成矩阵应产出谱系树数据"
    return dendro


class TestRecutClusters:
    """recut_clusters：fcluster(maxclust) 对已算好 linkage 重切（批次 3 F2）。"""

    def test_recut_k3_matches_known_partition(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 3)
        assert recut["k"] == 3 and recut["n_clusters"] == 3
        # assignments 与 members（aa,bb,cc,dd,ee）同序；簇号按叶序首现连续编号
        assert recut["assignments"] == [1, 1, 2, 2, 3]
        assert [c["size"] for c in recut["clusters"]] == [2, 2, 1]
        assert [[m["verb"] for m in c["members"]] for c in recut["clusters"]] \
            == [["aa", "bb"], ["cc", "dd"], ["ee"]]

    def test_recut_k2_and_k5(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        r2 = ca.recut_clusters(dendro, 2)
        assert r2["assignments"] == [1, 1, 1, 1, 2]
        assert [c["size"] for c in r2["clusters"]] == [4, 1]
        r5 = ca.recut_clusters(dendro, 5)
        assert r5["assignments"] == [1, 2, 3, 4, 5]  # 全部单例簇
        assert all(c["size"] == 1 for c in r5["clusters"])

    def test_recut_medoid_annotation(self, monkeypatch):
        """medoid 与 compute_medoid_ranking 同口径：预计算 Gower 子阵重算。"""
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 3)
        # 簇1 {aa,bb}：两人全同 → 平均距离平局取叶序靠前者 aa
        c1 = recut["clusters"][0]
        assert c1["medoid"]["verb"] == "aa"
        assert [m["is_medoid"] for m in c1["members"]] == [True, False]
        # 簇3 {ee}：单成员簇自身即 medoid（medoid_index 单成员口径）
        c3 = recut["clusters"][2]
        assert c3["medoid"]["verb"] == "ee" and c3["members"][0]["is_medoid"]
        # 每簇恰有一个 medoid 标注
        for cl in recut["clusters"]:
            assert sum(1 for m in cl["members"] if m["is_medoid"]) == 1
        # k=2 的大簇 {aa,bb,cc,dd}：平均距离全平局(1/3) → 首位 aa 胜出
        r2 = ca.recut_clusters(dendro, 2)
        assert r2["clusters"][0]["medoid"]["verb"] == "aa"

    def test_recut_does_not_mutate_input(self, monkeypatch):
        """dendro 来自 st.cache_data：重切不得原地污染输入对象。"""
        dendro = _synthetic_dendro(monkeypatch)
        before = [dict(m) for m in dendro["members"]]
        ca.recut_clusters(dendro, 3)
        assert all(m == b for m, b in zip(dendro["members"], before))
        assert all("is_medoid" not in m for m in dendro["members"])

    def test_recut_k_out_of_range(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        assert ca.recut_clusters(dendro, 1) == {}   # 下界 2
        assert ca.recut_clusters(dendro, 6) == {}   # > n_senses
        assert ca.recut_clusters(dendro, 11) == {}  # > RECUT_K_MAX
        assert ca.recut_clusters(dendro, 0) == {}
        assert ca.recut_clusters(dendro, "x") == {}

    def test_recut_missing_inputs(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        no_linkage = {**dendro, "linkage": None}
        assert ca.recut_clusters(no_linkage, 2) == {}
        assert ca.recut_clusters({}, 2) == {}
        # 无距离矩阵：不猜 medoid（多成员簇 medoid=None、is_medoid 不贴）
        no_dist = {**dendro, "distance_matrix": None}
        recut = ca.recut_clusters(no_dist, 3)
        assert recut and recut["n_clusters"] == 3
        assert recut["clusters"][0]["medoid"] is None
        assert all(not m["is_medoid"] for m in recut["clusters"][0]["members"])
        assert recut["clusters"][2]["medoid"]["verb"] == "ee"  # 单例仍自标注


class TestNextInteractiveVersion:
    """「交互-时间戳」运行版本号：生成/冲突递增后缀/重试上限。"""

    def test_fresh_timestamp(self):
        v = ca.next_interactive_version([], now_str="20261107-093000")
        assert v == "交互-20261107-093000"

    def test_default_now_format(self):
        import re
        assert re.fullmatch(r"交互-\d{8}-\d{6}",
                            ca.next_interactive_version([]))

    def test_conflict_bumps_suffix(self):
        ts = "20261107-093000"
        used = ["交互-" + ts]
        assert ca.next_interactive_version(used, now_str=ts) \
            == "交互-20261107-093000-2"
        used.append("交互-20261107-093000-2")
        assert ca.next_interactive_version(used, now_str=ts) \
            == "交互-20261107-093000-3"

    def test_custom_prefix(self):
        assert ca.next_interactive_version([], now_str="20261107-100000",
                                           prefix="试用") == "试用-20261107-100000"

    def test_exhausted_raises(self):
        ts = "20261107-093000"
        used = ["交互-" + ts] + [f"交互-{ts}-{i}" for i in range(2, 1000)]
        with pytest.raises(ValueError):
            ca.next_interactive_version(used, now_str=ts)

    def test_conflict_only_within_same_base(self):
        # 不同时间戳/其他版本不受干扰
        ts = "20261107-093000"
        used = ["预编码", "双标注IAA", f"交互-{ts}-2"]
        assert ca.next_interactive_version(used, now_str=ts) == f"交互-{ts}"


class TestFeatureTypesFromPack:
    """范畴包元数据装载（纯文件系统，读 configs/motion/features.yaml）。"""

    def test_motion_value_types(self):
        value_types, ranges = ca.load_feature_types("motion")
        assert value_types["P1"] == "binary"
        assert value_types["P5"] == "ordinal"
        assert value_types["C1"] == "nominal"
        assert ranges["P5"] == (0, 2)
        assert ranges["M2"] == (0, 2)
        # 15 项进聚类（P/M/C），A 区核验列被排除
        assert len(value_types) == 15
        assert not any(code.startswith("A") for code in value_types)

    def test_missing_pack_degrades_to_empty(self):
        value_types, ranges = ca.load_feature_types("nosuchpack")
        assert value_types == {} and ranges == {}


class TestNominalFallbackOnEmptyMeta:
    """包缺失 → 元数据为空时按 nominal 兜底（S2 review 回归）。

    修复前：空 value_types 直接进 gower_distance → 每一对都判「无共同特征」
    记 0，medoid/tier/谱系树静默产出全零距离的退化结果。
    修复后：与 semantic_search.search_similar_senses 同口径 —— 出现过的特征
    码按 nominal 兜底并告警，距离恢复真实相异度。
    """

    _MEMBERS = [
        {"sense_id": 1, "verb": "sprint", "sense_no": "1", "sense_label": "L1",
         "features": {"P1": 1, "P5": 2, "M1a": 1, "C1": 2}},
        {"sense_id": 2, "verb": "dash", "sense_no": "1", "sense_label": "L2",
         "features": {"P1": 1, "P5": 2, "M1a": 1, "C1": 2}},
        {"sense_id": 3, "verb": "amble", "sense_no": "1", "sense_label": "L3",
         "features": {"P1": 0, "P5": 0, "M1b": 1, "C1": 0}},
    ]

    def _fake_matrix(self, value_types, ranges):
        return {
            "study_code": "RUN",
            "run": {"run_id": 1, "params": {}},
            "clusters": [{"cluster_id": 11, "cluster_no": 1, "name": "测试簇",
                          "size": 3, "members": self._MEMBERS}],
            "value_types": value_types, "ranges": ranges,
        }

    def test_empty_meta_nominal_fallback_ranking(self, monkeypatch):
        monkeypatch.setattr(ca, "_load_cluster_matrix",
                            lambda *a, **k: self._fake_matrix({}, {}))
        ranking = ca.compute_medoid_ranking("motion", "en")
        assert ranking, "兜底后应产出排序而非空"
        members = {m["verb"]: m for m in ranking[0]["members"]}
        # sprint 与 dash 全同 → 距离 0；与 amble 全不一致 → 1.0（不再全 0）
        assert members["dash"]["gower_to_medoid"] == 0.0
        assert members["sprint"]["gower_to_medoid"] == 0.0
        assert members["amble"]["gower_to_medoid"] == 1.0
        assert members["amble"]["tier"] == "periphery"

    def test_empty_meta_nominal_fallback_dendrogram(self, monkeypatch):
        monkeypatch.setattr(ca, "_load_cluster_matrix",
                            lambda *a, **k: self._fake_matrix({}, {}))
        dendro = ca.build_dendrogram_data("motion", "en")
        assert dendro, "兜底后应产出谱系树数据而非空"
        dm = dendro["distance_matrix"]
        # 叶序按 verb 排序：amble, dash, sprint —— amble 与另两者 1.0，dash-sprint 0
        assert dm[0][1] == 1.0 and dm[0][2] == 1.0 and dm[1][2] == 0.0, \
            "距离矩阵不应是全 0 退化矩阵"

    def test_nonempty_meta_untouched(self, monkeypatch):
        """元数据齐全时不触发兜底：结果与直接 gower_matrix 逐位一致。"""
        vt = {"P1": "binary", "P5": "ordinal", "M1a": "binary", "C1": "nominal",
              "M1b": "binary"}
        rg = {"P5": (0, 2)}
        monkeypatch.setattr(ca, "_load_cluster_matrix",
                            lambda *a, **k: self._fake_matrix(vt, rg))
        ranking = ca.compute_medoid_ranking("motion", "en")
        vecs = [m["features"] for m in self._MEMBERS]
        expected = ca.gower_matrix(vecs, vt, rg)
        med_idx = next(i for i, m in enumerate(self._MEMBERS)
                       if m["sense_id"] == ranking[0]["medoid"]["sense_id"])
        got = [m["gower_to_medoid"] for m in
               sorted(ranking[0]["members"], key=lambda r: r["sense_id"])]
        assert got == [expected[med_idx][i] for i in range(len(vecs))]


# ============================================
# 5. 数据层端到端（CLUSRUN 种子范畴，medoid 先验已知）
# ============================================

def _clusrun_payload() -> dict:
    """已知 medoid 的种子数据（合成向量设计见 TestMedoidIndex.test_known_medoid）。"""
    en_senses = [
        ("aa", {"F1": 1, "F2": 1, "F3": 1}),
        ("bb", {"F1": 1, "F2": 1, "F3": 1}),
        ("cc", {"F1": 1, "F2": 1, "F3": 1}),
        ("dd", {"F1": 1, "F2": 0, "F3": 1}),
        ("ee", {"F1": 0, "F2": 0, "F3": 2}),
        ("ff", {"F1": 0, "F2": 0, "F3": 0}),
        ("gg", {"F1": 0, "F2": 1, "F3": 2}),
    ]
    return {
        "category": {"code": "CLUSRUN", "name_cn": "聚类分析测试",
                     "name_en": "ClusterAnalysisTest", "status": "试点",
                     "notes": "tests/test_cluster_analysis.py 临时范畴，测完即删"},
        "lexemes": [{"language": "en", "lemma": lemma, "source_dict": "OALD10",
                     "in_levin": 0} for lemma, _ in en_senses]
        + [{"language": "zh", "lemma": "词甲", "source_dict": "现汉7",
            "in_levin": 0}],
        "senses": [{"language": "en", "lemma": lemma, "sense_no": "1",
                    "sense_label": "测试义", "status": "保留",
                    "features": feats} for lemma, feats in en_senses]
        + [{"language": "zh", "lemma": "词甲", "sense_no": "①",
            "sense_label": "测试义", "status": "保留",
            "features": {"F1": 1, "F2": 1, "F3": 1}}],
        "cluster_runs": [
            {"language": "en", "algorithm": "Gower+average",
             "params": {"k": 2}, "cophenetic": 0.9, "version": "预编码",
             "clusters": [
                 {"cluster_no": 1, "name": "测试簇一（画像）", "size": 5,
                  "profile": {}, "note": "",
                  "members": [(lem, "1", "测试义") for lem, _ in en_senses[:5]]},
                 {"cluster_no": 2, "name": "测试簇二", "size": 2,
                  "profile": {}, "note": "",
                  "members": [(lem, "1", "测试义") for lem, _ in en_senses[5:]]},
             ]},
            {"language": "zh", "algorithm": "Gower+average",
             "params": {"k": 1}, "cophenetic": 1.0, "version": "预编码",
             "clusters": [
                 {"cluster_no": 1, "name": "汉语测试簇", "size": 1,
                  "profile": {}, "note": "", "members": [("词甲", "①", "测试义")]},
             ]},
        ],
        "alignments": [],
    }


@pytest.fixture(scope="module")
def clusrun_seeded():
    """把 CLUSRUN 种子范畴灌入业务库（模块级一次，读测试共用，最后删除）。"""
    if not _db_available():
        pytest.skip("MySQL 不可用，跳过聚类分析数据层测试")
    counts = cs.replace_category_study(_clusrun_payload())
    yield counts
    with cs.get_db_cursor() as cursor:
        cursor.execute("DELETE FROM categories WHERE code = 'CLUSRUN'")


@requires_db
class TestMedoidRankingDB:
    def test_medoid_selection_exact(self, clusrun_seeded):
        ranking = ca.compute_medoid_ranking("CLUSRUN", "en",
                                            value_types=VT, ranges=RG)
        assert [c["cluster_no"] for c in ranking] == [1, 2]

        c1 = ranking[0]
        assert c1["size"] == 5
        # medoid：三条相同向量中 sense_id 最小的 aa，到自身距离 0、tier 原型
        assert c1["medoid"]["verb"] == "aa"
        assert c1["medoid"]["gower_to_medoid"] == pytest.approx(0.0)
        assert c1["medoid"]["tier"] == ca.TIER_PROTOTYPE

        by_verb = {m["verb"]: m for m in c1["members"]}
        assert by_verb["aa"]["is_medoid"] is True
        assert by_verb["bb"]["gower_to_medoid"] == pytest.approx(0.0)
        assert by_verb["cc"]["gower_to_medoid"] == pytest.approx(0.0)
        assert by_verb["dd"]["gower_to_medoid"] == pytest.approx(1 / 3)
        assert by_verb["ee"]["gower_to_medoid"] == pytest.approx(2.5 / 3)
        # 三分位（n=5 → 2 原型 / 1 次典型 / 2 边缘），平局按 sense_id 稳定
        assert [m["tier"] for m in c1["members"]] == [
            ca.TIER_PROTOTYPE, ca.TIER_PROTOTYPE, ca.TIER_TYPICAL,
            ca.TIER_PERIPHERY, ca.TIER_PERIPHERY]
        # 成员按到 medoid 距离升序
        dists = [m["gower_to_medoid"] for m in c1["members"]]
        assert dists == sorted(dists)

        c2 = ranking[1]
        assert c2["size"] == 2
        assert c2["medoid"]["verb"] == "ff"  # 平局取 sense_id 较小者
        assert [m["tier"] for m in c2["members"]] == [
            ca.TIER_PROTOTYPE, ca.TIER_PERIPHERY]

    def test_custom_shares_propagate(self, clusrun_seeded):
        ranking = ca.compute_medoid_ranking(
            "CLUSRUN", "en", value_types=VT, ranges=RG,
            prototype_share=0.6, periphery_share=0.2)
        c1 = ranking[0]
        assert [m["tier"] for m in c1["members"]] == [
            ca.TIER_PROTOTYPE, ca.TIER_PROTOTYPE, ca.TIER_PROTOTYPE,
            ca.TIER_TYPICAL, ca.TIER_PERIPHERY]

    def test_language_filter_and_single_member_cluster(self, clusrun_seeded):
        ranking = ca.compute_medoid_ranking("CLUSRUN", "zh",
                                            value_types=VT, ranges=RG)
        assert len(ranking) == 1
        member = ranking[0]["members"][0]
        assert member["verb"] == "词甲"
        assert member["sense_no"] == "①"
        assert member["gower_to_medoid"] == pytest.approx(0.0)
        assert member["tier"] == ca.TIER_PROTOTYPE
        # 单成员簇：自身即 medoid
        assert ranking[0]["medoid"]["verb"] == "词甲"

    def test_explicit_run_id_and_cross_language_fallback(self, clusrun_seeded):
        cats = [c for c in cs.get_categories() if c["code"] == "CLUSRUN"]
        runs = cs.get_cluster_runs(int(cats[0]["id"]))
        en_run = next(r for r in runs if r["language"] == "en")
        zh_run = next(r for r in runs if r["language"] == "zh")

        ranking = ca.compute_medoid_ranking("CLUSRUN", "en", run_id=en_run["run_id"],
                                            value_types=VT, ranges=RG)
        assert [c["cluster_no"] for c in ranking] == [1, 2]

        # run_id 不属于该语言时告警回退到该语言最新运行（docstring 口径）
        zh_fallback = ca.compute_medoid_ranking("CLUSRUN", "zh",
                                                run_id=en_run["run_id"],
                                                value_types=VT, ranges=RG)
        assert len(zh_fallback) == 1 and zh_fallback[0]["cluster_name"] == "汉语测试簇"
        assert zh_run["run_id"] != en_run["run_id"]

    def test_output_contract(self, clusrun_seeded):
        ranking = ca.compute_medoid_ranking("CLUSRUN", "en",
                                            value_types=VT, ranges=RG)
        for cluster in ranking:
            assert {"cluster_id", "cluster_no", "cluster_name", "size",
                    "medoid", "members"} <= set(cluster)
            assert cluster["size"] == len(cluster["members"])
            assert sum(1 for m in cluster["members"] if m["is_medoid"]) == 1
            for m in cluster["members"]:
                assert {"sense_id", "verb", "sense_no", "sense_label",
                        "gower_to_medoid", "tier", "is_medoid"} <= set(m)
                assert m["tier"] in (ca.TIER_PROTOTYPE, ca.TIER_TYPICAL,
                                     ca.TIER_PERIPHERY)


@requires_db
class TestDendrogramDB:
    def test_consistency_with_linkage(self, clusrun_seeded):
        data = ca.build_dendrogram_data("CLUSRUN", "en",
                                        value_types=VT, ranges=RG)
        assert data["n_senses"] == 7
        assert len(data["linkage"]) == 6  # n-1 次合并
        assert data["method"] == "average" and data["metric"] == "gower"
        # labels = verb-Sn，按 verb 排序（叶序确定）
        assert data["labels"] == ["aa-S1", "bb-S1", "cc-S1", "dd-S1",
                                  "ee-S1", "ff-S1", "gg-S1"]
        # 运行参数 k=2 → 切分高度 = 第 n-k 次合并，其下方恰有 n-k 次合并
        assert data["k"] == 2
        cut = data["cut_height"]
        assert cut == pytest.approx(data["linkage"][5][2])
        assert sum(1 for row in data["linkage"] if row[2] < cut) == 5
        # 距离矩阵对称、对角 0，且重算 linkage 与返回值一致
        dist = data["distance_matrix"]
        for i in range(7):
            assert dist[i][i] == 0.0
            for j in range(7):
                assert dist[i][j] == pytest.approx(dist[j][i])
        assert ca.linkage_from_distance_matrix(dist) == data["linkage"]

    def test_too_few_members_empty(self, clusrun_seeded):
        # 汉语侧只有 1 个成员，构不成树
        assert ca.build_dendrogram_data("CLUSRUN", "zh",
                                        value_types=VT, ranges=RG) == {}

    def test_unknown_category_empty(self, clusrun_seeded):
        assert ca.compute_medoid_ranking("nosuchcategory", "en") == []
        assert ca.build_dendrogram_data("nosuchcategory", "en") == {}


# ============================================
# 5b. 交互切割保存（cs_cluster_runs 版本化，批次 3 F2）
# ============================================

@requires_db
class TestSaveInteractiveRunDB:
    """save_interactive_cluster_run：参数化 INSERT 往返 + UNIQUE 冲突不覆盖。

    版本化口径（论文 §5.1 / 对照清单 F2）：交互切割结果为探索性运行，与
    预计算版共存互不覆盖 —— 冲突时返回 conflict 而非改写既有行。
    本类放在 TestDendrogramDB/TestMedoidRankingDB 之后：保存会把
    cs_cluster_runs 的最大 run_id 推到交互版，而 _resolve_run 取最新运行，
    放在前面会让先验断言（k=2、簇数）读到交互版而错位。夹具 teardown 删
    CLUSRUN 范畴 → CASCADE 级联清掉本类写入的全部行。
    """

    def _dendro_recut(self):
        dendro = ca.build_dendrogram_data("CLUSRUN", "en",
                                          value_types=VT, ranges=RG)
        recut = ca.recut_clusters(dendro, 3)
        assert recut["n_clusters"] == 3
        return dendro, recut

    def _runs(self, language="en"):
        cats = [c for c in cs.get_categories() if c["code"] == "CLUSRUN"]
        return cs.get_cluster_runs(int(cats[0]["id"]), language)

    def test_save_roundtrip(self, clusrun_seeded):
        dendro, recut = self._dendro_recut()
        result = ca.save_interactive_cluster_run(dendro, recut,
                                                 version="交互测试v1")
        assert result["ok"] is True
        assert result["version"] == "交互测试v1"
        saved = next(r for r in self._runs()
                     if r["version"] == "交互测试v1")
        assert int(saved["run_id"]) == int(result["run_id"])
        assert saved["algorithm"] == "Gower+average"
        assert saved["params"]["k"] == 3
        assert saved["params"]["criterion"] == "maxclust"
        assert saved["params"]["interactive"] is True
        assert int(saved["params"]["source_run_id"]) == int(dendro["run_id"])
        # 同一棵树 → cophenetic 沿用源运行值（CLUSRUN 种子 = 0.9）
        assert saved["cophenetic"] == pytest.approx(0.9)
        # 簇与成员与 recut 完全一致（参数化 INSERT 往返）
        clusters = cs.get_clusters_with_members(int(result["run_id"]))
        assert sorted(c["size"] for c in clusters) == \
            sorted(cl["size"] for cl in recut["clusters"])
        saved_ids = sorted(m["sense_id"] for cl in clusters
                           for m in cl["members"])
        dendro_ids = sorted(m["sense_id"] for m in dendro["members"])
        assert saved_ids == dendro_ids
        assert {cl["cluster_no"] for cl in clusters} == {1, 2, 3}

    def test_duplicate_version_conflict_no_overwrite(self, clusrun_seeded):
        dendro, recut = self._dendro_recut()
        first = ca.save_interactive_cluster_run(dendro, recut,
                                                version="交互冲突v")
        assert first["ok"] is True
        second = ca.save_interactive_cluster_run(dendro, recut,
                                                 version="交互冲突v")
        assert second["ok"] is False and second["conflict"] is True
        assert second["version"] == "交互冲突v"
        # 共存口径：未覆盖既有行，同名版本仍只有一行
        rows = [r for r in self._runs() if r["version"] == "交互冲突v"]
        assert len(rows) == 1
        clusters = cs.get_clusters_with_members(int(rows[0]["run_id"]))
        assert len(clusters) == first["n_clusters"]

    def test_auto_version_dedupes(self, clusrun_seeded):
        """自动「交互-时间戳」版本：连续两次保存版本号必不相同。"""
        dendro, recut = self._dendro_recut()
        r1 = ca.save_interactive_cluster_run(dendro, recut)
        r2 = ca.save_interactive_cluster_run(dendro, recut)
        assert r1["ok"] and r2["ok"]
        assert r1["version"].startswith("交互-")
        assert r1["version"] != r2["version"]

    def test_empty_recut_rejected(self, clusrun_seeded):
        dendro, _ = self._dendro_recut()
        result = ca.save_interactive_cluster_run(dendro, {"clusters": []})
        assert result["ok"] is False and "conflict" not in result
        assert ca.save_interactive_cluster_run({}, {})["ok"] is False


# ============================================
# 6. 页面（AppTest 冒烟：真实数据 + 无数据降级）
# ============================================
# AppTest.from_string 而非 from_function：页面函数依赖模块级全局
# （st / design_system 等），from_function 只把函数体当独立脚本执行，
# 不带全局环境（官方约定"must contain all necessary imports"）。

PAGE_SCRIPT = (
    "from src import cluster_analysis as ca\n"
    "ca.render_cluster_analysis_page()\n"
)


def _page_text(at: AppTest) -> str:
    parts = []
    for accessor in ("markdown", "caption", "info", "warning", "header",
                     "subheader", "title"):
        elements = getattr(at, accessor, None) or []
        parts.extend(e.value for e in elements)
    return " ".join(parts)


class TestPage:
    def test_no_data_degrades_gracefully(self, monkeypatch):
        """无运行数据时页面渲染降级提示，不抛异常（不需要 DB）。"""
        monkeypatch.setattr(ca, "_load_page_data",
                            lambda _scope, c, lang: {"ranking": [], "dendro": {},
                                                     "scipy_missing": False})
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=30)
        at.run()
        assert not at.exception
        text = _page_text(at)
        assert "暂无聚类运行数据" in text
        assert "📊 语义分析" in text  # 合并页标题（原「聚类可视化与典型性排序」）

    @requires_db
    def test_smoke_with_real_data(self):
        """真实 RUN 数据（motion/en）页面冒烟：不抛异常、四 tab 在场。"""
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=120)
        at.run()
        assert not at.exception
        text = _page_text(at)
        assert "谱系树" in text
        assert "典型性排序" in text
        assert "medoid" in text.lower()
        assert "义项分立复核" in text or "簇证据视图" in text
        assert "义位图谱" in text
        # 展开卡 = 谱系侧（典型性 5 簇 + 分立复核证据 5 簇）＋ 英汉对比侧（合并后
        # 双侧同渲染，五视图成员/对齐 expander 叠加）——合并页只断言下限与关键标记
        assert len(at.expander) >= 10
        assert any("簇1" in str(e.label) for e in at.expander)


# ============================================
# 6b. 交互切割页面控件（批次 3 F2，AppTest 冒烟，不需要 DB）
# ============================================

def _fake_ranking() -> list:
    """典型性排序 tab 的最小假数据（medoid/members 结构与真实现同构）。"""
    return [{
        "cluster_id": 71, "cluster_no": 1, "cluster_name": "合成簇", "size": 2,
        "medoid": {"sense_id": 1, "verb": "aa", "sense_no": "1",
                   "sense_label": "L1", "gower_to_medoid": 0.0,
                   "tier": ca.TIER_PROTOTYPE},
        "members": [
            {"sense_id": 1, "verb": "aa", "sense_no": "1", "sense_label": "L1",
             "gower_to_medoid": 0.0, "tier": ca.TIER_PROTOTYPE,
             "is_medoid": True},
            {"sense_id": 2, "verb": "bb", "sense_no": "1", "sense_label": "L2",
             "gower_to_medoid": 0.5, "tier": ca.TIER_PERIPHERY,
             "is_medoid": False},
        ],
    }]


class TestInteractiveCuttingPage:
    """谱系树 tab 交互切割控件（F2）：滑杆/对比表/保存流（打桩，不需要 DB）。

    批次 5 起页面扩为四 tab（谱系树/典型性排序/分立复核/义位图谱），st.tabs
    全部子块每次 run 都会渲染：控件计数按「谱系树 + 分立复核 + 图谱」合计断言，
    并以 widget key 定位（tab 内顺序不脆）。
    """

    def _page(self, monkeypatch, user=None) -> AppTest:
        return _stub_page(monkeypatch, user=user)

    def test_controls_render_and_default_k(self, monkeypatch):
        at = self._page(monkeypatch)
        assert not at.exception
        text = _page_text(at)
        assert "交互式谱系切割" in text
        # 论文口径注（对照清单 F2 承诺）在场
        assert "共存互不覆盖" in text
        # 滑杆 ×2：谱系树切割 + 义位图谱分组（默认均取当前运行 k=2）
        assert len(at.slider) == 2
        assert [s.key for s in at.slider] == ["ca_recut_k", "ca_graph_k"]
        assert all(s.value == 2 for s in at.slider)
        # 表 ×2：谱系树重切对比表 + 分立复核簇证据表
        assert len(at.dataframe) == 2
        # checkbox ×2：保存确认 + 图谱边表开关；text_input ×1（保存版本号）
        assert len(at.checkbox) == 2
        assert len(at.text_input) == 1
        # button ×1（保存；匿名用户无分立建议提交按钮 —— 登录门槛）
        assert len(at.button) == 1
        df = at.dataframe[0].value
        assert list(df["簇"]) == [1, 2]
        assert list(df["成员数"]) == [4, 1]

    def test_slider_recut_updates_table(self, monkeypatch):
        at = self._page(monkeypatch)
        at.slider[0].set_value(3).run()
        assert not at.exception
        assert at.slider[0].value == 3
        df = at.dataframe[0].value
        assert list(df["簇"]) == [1, 2, 3]
        assert list(df["成员数"]) == [2, 2, 1]
        # medoid 标注列在场（簇1 = aa，见 TestRecutClusters 先验）
        assert "aa" in str(df.iloc[0]["medoid"])

    def test_save_requires_confirm_then_succeeds(self, monkeypatch):
        calls = []

        def fake_save(dendro, recut, version=None):
            calls.append({"run_id": dendro["run_id"], "k": recut["k"],
                          "version": version})
            return {"ok": True, "run_id": 99,
                    "version": version or "交互-自动",
                    "n_clusters": recut["n_clusters"], "n_members": 5}

        monkeypatch.setattr(ca, "save_interactive_cluster_run", fake_save)
        at = self._page(monkeypatch)
        # 未勾选确认 → 点击不触发保存（st.confirm 式门槛）
        at.button[0].click().run()
        assert calls == []
        assert not at.exception
        assert any("勾选" in w.value for w in at.warning)
        # 勾选确认 + 自定义版本号 → 保存成功，success 文案含版本与共存口径
        at.slider[0].set_value(3).run()
        at.checkbox[0].check().run()
        at.text_input[0].set_value("我的交互版").run()
        at.button[0].click().run()
        assert not at.exception
        assert len(calls) == 1
        assert calls[0]["version"] == "我的交互版"
        assert calls[0]["k"] == 3
        assert calls[0]["run_id"] == 7  # 合成 dendro 的源运行
        assert len(at.success) == 1
        assert "我的交互版" in at.success[0].value
        assert "共存互不覆盖" in at.success[0].value

    def test_save_conflict_prompts_version_change(self, monkeypatch):
        """UNIQUE(category, language, version) 冲突 → 页面提示改版本号。"""
        def fake_save(dendro, recut, version=None):
            return {"ok": False, "conflict": True, "version": version,
                    "error": f"版本号「{version}」已存在，请改版本号后重试"}
        monkeypatch.setattr(ca, "save_interactive_cluster_run", fake_save)
        at = self._page(monkeypatch)
        at.checkbox[0].check().run()
        at.text_input[0].set_value("撞名版本").run()
        at.button[0].click().run()
        assert not at.exception
        assert not at.success
        assert len(at.error) == 1
        assert "改版本" in at.error[0].value


# ============================================
# 7. 批次 5 纯函数：分立复核（建议载荷 / 裁决门 / 证据 / 裁决编排）
# ============================================

def _div_member(sid, verb, no="1", label="L"):
    """分立证据/建议的最小成员行（与 build_sense_division_evidence 输出同构）。"""
    return {"sense_id": sid, "verb": verb, "sense_no": no, "sense_label": label,
            "gower_to_medoid": 0.0, "tier": ca.TIER_PROTOTYPE,
            "name": f"{verb}·{no} {label}", "freq": None,
            "status": None, "merged_into": None}


class TestEnumParsingAndGuards:
    """迁移辅助的纯函数：enum 文本解析 / id 规整（不碰数据库）。"""

    def test_parse_standard_enum(self):
        assert ca._parse_enum_values("enum('目标','保留')") == ["目标", "保留"]

    def test_parse_escaped_quote(self):
        assert ca._parse_enum_values("enum('a','b''c','d')") == ["a", "b'c", "d"]

    def test_non_enum_returns_none(self):
        for bad in ("varchar(8)", "int", "enum(", "enum('a'", "", None,
                    "enum(a,b)"):
            assert ca._parse_enum_values(bad) is None, bad

    def test_as_int_id(self):
        assert ca._as_int_id(3) == 3
        assert ca._as_int_id("7") == 7
        assert ca._as_int_id(2.0) == 2
        assert ca._as_int_id(True) is None      # bool 不算 id
        assert ca._as_int_id(None) is None
        assert ca._as_int_id(0) is None         # ≤0 拒
        assert ca._as_int_id(-1) is None
        assert ca._as_int_id("x") is None

    def test_strip_quoted_default(self):
        assert ca._strip_quoted_default("保留") == "保留"
        assert ca._strip_quoted_default("'保留'") == "保留"  # MariaDB 风格


class TestDivisionProposalBuilder:
    """build_sense_division_proposal：载荷校验（非法值不进台账，应用层先拒）。"""

    def _members(self):
        return [_div_member(1, "aa"), _div_member(2, "bb"), _div_member(3, "cc")]

    def test_valid_merge(self):
        proposal, err = ca.build_sense_division_proposal(
            "merge", 1, self._members()[:2], "距离全 0 应合并",
            target_sense_id=1, run_id=7, version="预编码")
        assert err is None
        assert proposal["action"] == "merge"
        assert proposal["cluster_no"] == 1
        assert proposal["sense_ids"] == [1, 2]
        assert proposal["target_sense_id"] == 1
        assert proposal["senses"] == ["aa·1 L", "bb·1 L"]
        assert proposal["reason"] == "距离全 0 应合并"
        assert proposal["run_id"] == 7
        assert proposal["version"] == "预编码"

    def test_valid_split_and_keep(self):
        for action in ("split", "keep"):
            proposal, err = ca.build_sense_division_proposal(
                action, 2, self._members()[:1], "依据 X")
            assert err is None, action
            assert proposal["action"] == action
            assert "target_sense_id" not in proposal  # 非 merge 不带目标键

    def test_reason_required(self):
        proposal, err = ca.build_sense_division_proposal(
            "split", 1, self._members()[:1], "   ")
        assert proposal is None
        assert "理由" in err

    def test_invalid_action_rejected(self):
        proposal, err = ca.build_sense_division_proposal(
            "delete", 1, self._members()[:1], "x")
        assert proposal is None and "非法动作" in err

    def test_invalid_cluster_no_rejected(self):
        proposal, err = ca.build_sense_division_proposal(
            "split", "x", self._members()[:1], "x")
        assert proposal is None and "目标簇" in err

    def test_empty_selection_rejected(self):
        proposal, err = ca.build_sense_division_proposal("split", 1, [], "x")
        assert proposal is None and "sense 清单" in err

    def test_merge_needs_two_senses(self):
        proposal, err = ca.build_sense_division_proposal(
            "merge", 1, self._members()[:1], "x", target_sense_id=1)
        assert proposal is None and "至少选择 2 个" in err

    def test_merge_target_required_and_in_selection(self):
        members = self._members()[:2]
        proposal, err = ca.build_sense_division_proposal(
            "merge", 1, members, "x", target_sense_id=None)
        assert proposal is None and "保留目标" in err
        proposal, err = ca.build_sense_division_proposal(
            "merge", 1, members, "x", target_sense_id=99)
        assert proposal is None and "清单内" in err

    def test_duplicate_ids_deduped(self):
        members = [_div_member(1, "aa"), _div_member(1, "aa"), _div_member(2, "bb")]
        proposal, err = ca.build_sense_division_proposal(
            "merge", 1, members, "x", target_sense_id=1)
        assert err is None
        assert proposal["sense_ids"] == [1, 2]

    def test_dirty_members_skipped(self):
        members = [{"sense_id": "bad"}, None, _div_member(2, "bb")]
        proposal, err = ca.build_sense_division_proposal("split", 1, members, "x")
        assert err is None
        assert proposal["sense_ids"] == [2]


class TestDivisionAdjudicator:
    """_is_division_adjudicator：六角色 effective 门（fail-closed 三态覆盖）。"""

    def test_anonymous_and_dirty(self):
        assert ca._is_division_adjudicator(None) is False
        assert ca._is_division_adjudicator("admin") is False
        assert ca._is_division_adjudicator({}) is False

    def test_legacy_admin_role(self):
        assert ca._is_division_adjudicator({"id": 1, "role": "admin"}) is True

    def test_six_roles(self):
        assert ca._is_division_adjudicator(
            {"id": 2, "role": "viewer", "roles": ["dict_admin"]}) is True
        assert ca._is_division_adjudicator(
            {"id": 2, "role": "viewer", "roles": ["reviewer"]}) is True
        assert ca._is_division_adjudicator(
            {"id": 2, "role": "viewer", "roles": ["editor", "reviewer"]}) is True

    def test_other_roles_fail_closed(self):
        for roles in (["viewer"], ["editor"], ["annotator"], ["sys_admin"], []):
            assert ca._is_division_adjudicator(
                {"id": 2, "role": "viewer", "roles": roles}) is False, roles
        # roles 缺键 / 脏值 → False
        assert ca._is_division_adjudicator({"id": 2, "role": "editor"}) is False
        assert ca._is_division_adjudicator(
            {"id": 2, "role": "editor", "roles": "dict_admin"}) is False


class TestDivisionEvidence:
    """build_sense_division_evidence：簇内平均两两距离 = 预计算方阵子阵（不重算）。"""

    def _dendro_ranking(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        monkeypatch.setattr(ca, "_load_cluster_matrix",
                            lambda *a, **k: _recut_fake_matrix())
        ranking = ca.compute_medoid_ranking("motion", "en")
        assert ranking
        return dendro, ranking

    def test_avg_pairwise_from_precomputed_matrix(self, monkeypatch):
        dendro, ranking = self._dendro_ranking(monkeypatch)
        evidence = ca.build_sense_division_evidence(dendro, ranking)
        assert len(evidence) == 1
        cl = evidence[0]
        assert cl["cluster_no"] == 1 and cl["size"] == 5
        # medoid 显示名（compute_medoid_ranking 先验：5 成员簇里 cc 平均距离最小
        # 0.375 < aa 0.4583 —— 与 recut 小簇 medoid 先验区分开）
        assert cl["medoid_name"].startswith("cc")
        # 簇内平均两两距离 = 方阵 10 个无序对的均值（对照直接重算）
        idx_of = {m["sense_id"]: i for i, m in enumerate(dendro["members"])}
        ids = [m["sense_id"] for m in cl["members"]]
        total = sum(dendro["distance_matrix"][idx_of[a]][idx_of[b]]
                    for x, a in enumerate(ids) for b in ids[x + 1:])
        assert cl["avg_pairwise"] == pytest.approx(total / 10)

    def test_freq_and_status_columns(self, monkeypatch):
        dendro, ranking = self._dendro_ranking(monkeypatch)
        evidence = ca.build_sense_division_evidence(
            dendro, ranking, freqs={"aa": 100},
            sense_rows={1: {"status": "目标", "merged_into": None},
                        2: {"status": "merged", "merged_into": 1}})
        by_sid = {m["sense_id"]: m for m in evidence[0]["members"]}
        assert by_sid[1]["freq"] == 100
        assert by_sid[1]["status"] == "目标"
        assert by_sid[2]["status"] == "merged"
        assert by_sid[2]["merged_into"] == 1
        assert by_sid[3]["freq"] is None and by_sid[3]["status"] is None

    def test_missing_distance_matrix_no_guess(self, monkeypatch):
        dendro, ranking = self._dendro_ranking(monkeypatch)
        evidence = ca.build_sense_division_evidence(
            {**dendro, "distance_matrix": None}, ranking)
        assert evidence[0]["avg_pairwise"] is None

    def test_empty_inputs(self, monkeypatch):
        dendro, ranking = self._dendro_ranking(monkeypatch)
        assert ca.build_sense_division_evidence({}, ranking) == []
        assert ca.build_sense_division_evidence(dendro, []) == []


class TestMergedConsumption:
    """批次 6 merged 消费收口（纯函数）：标注 / 图谱跳过 / 锁定键 / 落地计数。"""

    def test_merged_sense_display_with_target(self):
        assert ca.merged_sense_display("merged", 42) == "已并入 → #42"

    def test_merged_sense_display_without_target_no_guess(self):
        text = ca.merged_sense_display("merged", None)
        assert text is not None and "已并入" in text and "待补录" in text

    def test_merged_sense_display_non_merged(self):
        for status in ("保留", "目标", "split", "", None):
            assert ca.merged_sense_display(status, 3) is None, status

    def test_status_display_annotates_merged(self):
        """证据表「cs_senses 现状」列对 merged 行的收口标注。"""
        assert ca._status_display(
            {"status": "merged", "merged_into": 9}) == "已并入 → #9"
        assert ca._status_display(
            {"status": "merged", "merged_into": None}) == "已并入（去向待补录）"
        assert ca._status_display({"status": "目标", "merged_into": None}) == "目标"
        assert ca._status_display({"status": "保留", "merged_into": 5}) == "保留 → #5"

    def test_landing_counts(self):
        rows = {1: {"status": "merged", "merged_into": 2},
                2: {"status": "目标", "merged_into": None},
                3: {"status": "split", "merged_into": None},
                4: {"status": "merged", "merged_into": 2},
                5: {"status": None, "merged_into": None}}
        assert ca.sense_division_landing_counts(rows) == {
            "merged": 2, "split": 1, "total": 5}
        assert ca.sense_division_landing_counts({}) == {
            "merged": 0, "split": 0, "total": 0}
        assert ca.sense_division_landing_counts(None) == {  # type: ignore[arg-type]
            "merged": 0, "split": 0, "total": 0}

    def test_evidence_carries_locked_flag(self, monkeypatch):
        """locks → 每簇 locked 键；缺省全 False（页面徽章按未锁定渲染）。"""
        dendro = _synthetic_dendro(monkeypatch)
        monkeypatch.setattr(ca, "_load_cluster_matrix",
                            lambda *a, **k: _recut_fake_matrix())
        ranking = ca.compute_medoid_ranking("motion", "en")
        unlocked = ca.build_sense_division_evidence(dendro, ranking)
        assert all(cl["locked"] is False for cl in unlocked)
        locked = ca.build_sense_division_evidence(dendro, ranking,
                                                  locks={71: True})
        assert locked[0]["locked"] is True

    def test_graph_skips_merged_nodes(self, monkeypatch):
        """merged_ids 中的义位不进图谱：节点/边剔除 + 跳过计数如实。"""
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 2)  # {aa,bb,cc,dd} / {ee}
        graph = ca.build_sense_graph_data(dendro, recut, merged_ids={1, 2})
        assert graph["n_merged_skipped"] == 2
        assert graph["n_senses"] == 3
        assert {n["sense_id"] for n in graph["nodes"]} == {3, 4, 5}
        for edge in graph["edges"]:
            assert "aa" not in edge["成员对"] and "bb" not in edge["成员对"]

    def test_graph_no_merged_identical_to_base(self, monkeypatch):
        """无 merged：与既有组装逐位一致（向后兼容，键只加不改）。"""
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 2)
        base = ca.build_sense_graph_data(dendro, recut)
        no_merged = ca.build_sense_graph_data(dendro, recut, merged_ids=[])
        assert no_merged == base
        assert base["n_merged_skipped"] == 0

    def test_graph_all_merged_returns_empty(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 2)
        assert ca.build_sense_graph_data(
            dendro, recut, merged_ids={1, 2, 3, 4, 5}) == {}

    def test_graph_merged_edges_keep_true_distances(self, monkeypatch):
        """边距离仍取预计算方阵真值（子阵条目与原方阵逐位一致）。"""
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 2)
        base = ca.build_sense_graph_data(dendro, recut)
        graph = ca.build_sense_graph_data(dendro, recut, merged_ids={5})
        base_pairs = {e["成员对"]: e["Gower 距离"] for e in base["edges"]
                      if "ee" not in e["成员对"]}
        got_pairs = {e["成员对"]: e["Gower 距离"] for e in graph["edges"]}
        assert got_pairs == base_pairs
        assert graph["n_merged_skipped"] == 1


class TestAdjudicateFlow:
    """adjudicate_sense_division：先 decide 留痕、adopted 才落地（monkeypatch）。"""

    def _proposal(self):
        return {"action": "merge", "cluster_no": 1, "sense_ids": [1, 2],
                "target_sense_id": 1, "reason": "r"}

    def test_adopted_executes_after_decide(self, monkeypatch):
        calls = {"decide": [], "execute": []}
        monkeypatch.setattr(ca, "decide",
                            lambda pid, d, r, u: calls["decide"].append(
                                (pid, d, r, u)) or True)
        monkeypatch.setattr(ca, "execute_sense_division",
                            lambda p: calls["execute"].append(p)
                            or {"ok": True, "updated": 1})
        result = ca.adjudicate_sense_division(9, "adopted", "采纳理由", 1,
                                              self._proposal())
        assert result["ok"] is True and result["executed"] is True
        assert result["updated"] == 1
        assert calls["decide"] == [(9, "adopted", "采纳理由", 1)]
        assert calls["execute"] == [self._proposal()]

    def test_decide_failure_blocks_execution(self, monkeypatch):
        monkeypatch.setattr(ca, "decide", lambda pid, d, r, u: False)
        executed = []
        monkeypatch.setattr(ca, "execute_sense_division",
                            lambda p: executed.append(p) or {"ok": True})
        result = ca.adjudicate_sense_division(9, "adopted", None, 1,
                                              self._proposal())
        assert result["ok"] is False and "裁决未记录" in result["error"]
        assert executed == []  # 留痕失败绝不落地

    def test_rejected_and_modified_record_only(self, monkeypatch):
        monkeypatch.setattr(ca, "decide", lambda pid, d, r, u: True)
        executed = []
        monkeypatch.setattr(ca, "execute_sense_division",
                            lambda p: executed.append(p) or {"ok": True})
        for decision in ("rejected", "modified"):
            result = ca.adjudicate_sense_division(
                9, decision, "理由", 1, self._proposal())
            assert result["ok"] is True and result["executed"] is False
        assert executed == []  # 本页 MVP 无改参编辑：modified 仅留痕不落地

    def test_execution_failure_after_adopt(self, monkeypatch):
        monkeypatch.setattr(ca, "decide", lambda pid, d, r, u: True)
        monkeypatch.setattr(ca, "execute_sense_division",
                            lambda p: {"ok": False, "error": "DB down"})
        result = ca.adjudicate_sense_division(9, "adopted", None, 1,
                                              self._proposal())
        assert result["ok"] is False and result["executed"] is False
        assert "人工补救" in result["error"]

    def test_invalid_inputs(self, monkeypatch):
        monkeypatch.setattr(ca, "decide", lambda pid, d, r, u: True)
        assert ca.adjudicate_sense_division(9, "bogus", None, 1,
                                            self._proposal())["ok"] is False
        assert ca.adjudicate_sense_division("x", "adopted", None, 1,
                                            self._proposal())["ok"] is False

    def test_execute_validates_payload_without_db(self):
        """execute_sense_division 的载荷校验在开连接前拒绝（不需要 DB）。"""
        assert ca.execute_sense_division(None)["ok"] is False
        assert ca.execute_sense_division({"action": "nope"})["ok"] is False
        assert ca.execute_sense_division({"action": "merge", "sense_ids": []})[
            "ok"] is False
        assert ca.execute_sense_division(
            {"action": "merge", "sense_ids": [1], "target_sense_id": 1})[
            "ok"] is False  # 单 sense 不构成合并
        assert ca.execute_sense_division(
            {"action": "merge", "sense_ids": [1, 2], "target_sense_id": 9})[
            "ok"] is False  # 目标不在清单内


# ============================================
# 8. 批次 5 纯函数：义位图谱（经典 MDS 坐标 / 图谱组装）
# ============================================

class TestClassicalMDS:
    """classical_mds_coordinates：Torgerson 双中心化＋特征分解（零新依赖）。"""

    def test_collinear_points_exact_recovery(self):
        """共线三点 0/1/3：一维结构 → 解释率 1.0，两两距离精确还原（非造假坐标）。"""
        d = [[0.0, 1.0, 3.0], [1.0, 0.0, 2.0], [3.0, 2.0, 0.0]]
        coords, explained = ca.classical_mds_coordinates(d)
        assert explained == pytest.approx(1.0)
        assert len(coords) == 3
        assert math.dist(coords[0], coords[1]) == pytest.approx(1.0)
        assert math.dist(coords[0], coords[2]) == pytest.approx(3.0)
        assert math.dist(coords[1], coords[2]) == pytest.approx(2.0)

    def test_projection_explains_less_for_higher_dim(self):
        """正四面体（3 维单纯形）：2D 投影必有损失 → 0 < 解释率 < 1。"""
        s = 2.0
        d = [[0.0, s, s, s], [s, 0.0, s, s], [s, s, 0.0, s], [s, s, s, 0.0]]
        coords, explained = ca.classical_mds_coordinates(d)
        assert 0.0 < explained < 1.0
        assert len(coords) == 4

    def test_degenerate_zero_matrix(self):
        coords, explained = ca.classical_mds_coordinates(
            [[0.0, 0.0], [0.0, 0.0]])
        assert coords == [[0.0, 0.0], [0.0, 0.0]]
        assert explained == 0.0

    def test_single_point_and_empty(self):
        coords, explained = ca.classical_mds_coordinates([[0.0]])
        assert coords == [[0.0, 0.0]] and explained == 0.0
        assert ca.classical_mds_coordinates([]) == ([], 0.0)
        # 非方阵 → 空坐标（不猜）；方阵脏值（非对称）不炸（双中心化后强制对称）
        assert ca.classical_mds_coordinates([[1.0, 2.0, 3.0],
                                             [4.0, 5.0, 6.0]]) == ([], 0.0)
        coords2, _ = ca.classical_mds_coordinates([[1.0, 2.0], [3.0, 4.0]])
        assert len(coords2) == 2


class TestSenseGraphData:
    """build_sense_graph_data：recut 分组键 + 预计算方阵 → 节点/medoid/边表。"""

    def test_known_partition(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 3)
        graph = ca.build_sense_graph_data(dendro, recut)
        assert graph["k"] == 3 and graph["n_senses"] == 5
        assert graph["labels"] == ["aa-S1", "bb-S1", "cc-S1", "dd-S1", "ee-S1"]
        # 节点分组 = assignments；medoid 先验：簇1 aa / 簇2 cc / 簇3 ee
        assert [n["cluster_no"] for n in graph["nodes"]] == [1, 1, 2, 2, 3]
        medoids = [n for n in graph["nodes"] if n["is_medoid"]]
        assert sorted(n["label"] for n in medoids) == ["aa-S1", "cc-S1", "ee-S1"]
        # 坐标（有限浮点）与解释率在场（合成矩阵欧氏可嵌 → 解释率 > 0）
        for node in graph["nodes"]:
            assert isinstance(node["x"], float) and isinstance(node["y"], float)
            assert math.isfinite(node["x"]) and math.isfinite(node["y"])
        assert 0.0 < graph["explained"] <= 1.0
        # 边 = 簇内两两距离：{aa,bb} 与 {cc,dd} 各 1 条（距离 0），单例簇无边
        assert len(graph["edges"]) == 2
        assert all(e["Gower 距离"] == pytest.approx(0.0) for e in graph["edges"])
        assert {e["簇"] for e in graph["edges"]} == {1, 2}

    def test_edge_limit_truncates_desc(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 2)  # k=2 → 大簇 4 成员 = 6 条边
        graph = ca.build_sense_graph_data(dendro, recut, edge_limit=3)
        assert len(graph["edges"]) == 3
        dists = [e["Gower 距离"] for e in graph["edges"]]
        assert dists == sorted(dists, reverse=True)  # 降序截断

    def test_invalid_inputs(self, monkeypatch):
        dendro = _synthetic_dendro(monkeypatch)
        recut = ca.recut_clusters(dendro, 3)
        assert ca.build_sense_graph_data({}, recut) == {}
        assert ca.build_sense_graph_data(dendro, {}) == {}
        assert ca.build_sense_graph_data(
            {**dendro, "distance_matrix": None}, recut) == {}
        assert ca.build_sense_graph_data(
            dendro, {**recut, "assignments": [1, 1, 2]}) == {}  # 长度不齐不猜


# ============================================
# 9. 批次 5 数据层：迁移（合成表幂等）＋ 落地执行（CLUSRUN 行）
# ============================================
# 说明：本机 web_word_user 无建库权限（tests/ 各模块的独立测试库 fixture 同样
# 可能 skip），合成表落在业务库、finally 清理 —— 与本模块 CLUSRUN 种子同口径。

SYNTH_ENUM_TABLE = "cs_senses_p5synth_enum"
SYNTH_VC_TABLE = "cs_senses_p5synth_vc"


def _drop_synth_tables():
    with cs.get_db_cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {SYNTH_ENUM_TABLE}")
        cursor.execute(f"DROP TABLE IF EXISTS {SYNTH_VC_TABLE}")


@requires_db
class TestSenseSplitColumnsMigration:
    """ensure_sense_split_columns：合成表验证分支与幂等 → 主库验收。"""

    def _create_synth(self, table, status_ddl):
        with cs.get_db_cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
            cursor.execute(f"""CREATE TABLE {table} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sense_no VARCHAR(16) NOT NULL,
                sense_label VARCHAR(64) NOT NULL,
                status {status_ddl},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")

    def _column(self, table, column):
        """information_schema 列定义（SHOW COLUMNS 不含 Comment，故走这里）。"""
        with cs.get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                          COLUMN_DEFAULT, COLUMN_COMMENT
                   FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = %s""",
                (table, column),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {"Field": row["COLUMN_NAME"], "Type": row["COLUMN_TYPE"],
                "Null": row["IS_NULLABLE"], "Default": row["COLUMN_DEFAULT"],
                "Comment": row["COLUMN_COMMENT"]}

    def test_enum_extension_roundtrip_and_idempotent(self):
        """ENUM 扩值：原值/默认保留在前、merged/split 追加可写、二次执行零改动。"""
        self._create_synth(
            SYNTH_ENUM_TABLE,
            "ENUM('目标','保留') NOT NULL DEFAULT '目标' COMMENT '准入判定'")
        try:
            result = ca._ensure_sense_split_columns_for(SYNTH_ENUM_TABLE)
            assert result["ok"] is True
            assert result["status_altered"] is True
            assert result["merged_into_added"] is True
            status = self._column(SYNTH_ENUM_TABLE, "status")
            assert status["Type"] == "enum('目标','保留','merged','split')"
            assert status["Default"] == "目标"  # 原默认值保留
            assert "准入判定" in status["Comment"]  # 原注释保留（追加分立说明）
            merged = self._column(SYNTH_ENUM_TABLE, "merged_into")
            assert merged["Type"] == "int" and merged["Null"] == "YES"
            # 往返：新增状态值与 merged_into 可写；默认值路径不丢
            with cs.get_db_cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SYNTH_ENUM_TABLE} "
                    "(sense_no, sense_label, status, merged_into) "
                    "VALUES ('1', '甲', 'merged', 42)")
                cursor.execute(
                    f"INSERT INTO {SYNTH_ENUM_TABLE} (sense_no, sense_label) "
                    "VALUES ('2', '乙')")
                cursor.execute(
                    f"SELECT status, merged_into FROM {SYNTH_ENUM_TABLE} ORDER BY id")
                rows = cursor.fetchall()
            assert rows[0]["status"] == "merged" and rows[0]["merged_into"] == 42
            assert rows[1]["status"] == "目标" and rows[1]["merged_into"] is None
            # 幂等：第二次执行不再改动
            again = ca._ensure_sense_split_columns_for(SYNTH_ENUM_TABLE)
            assert again["ok"] is True
            assert again["status_altered"] is False
            assert again["merged_into_added"] is False
            assert again["actions"] == []
        finally:
            _drop_synth_tables()

    def test_narrow_varchar_widened(self):
        """varchar(4) 装不下 'merged' → 同型加宽到 varchar(8)，默认值保留。"""
        self._create_synth(SYNTH_VC_TABLE, "VARCHAR(4) NOT NULL DEFAULT '保留'")
        try:
            result = ca._ensure_sense_split_columns_for(SYNTH_VC_TABLE)
            assert result["ok"] is True and result["status_altered"] is True
            status = self._column(SYNTH_VC_TABLE, "status")
            assert status["Type"] == "varchar(8)"
            assert status["Default"] == "保留"
            assert result["merged_into_added"] is True
        finally:
            _drop_synth_tables()

    def test_wide_varchar_untouched(self):
        """varchar(8)（主库实测列型）长度充足：status 不动，仅补 merged_into。"""
        self._create_synth(SYNTH_VC_TABLE, "VARCHAR(8) NOT NULL DEFAULT '保留'")
        try:
            result = ca._ensure_sense_split_columns_for(SYNTH_VC_TABLE)
            assert result["ok"] is True
            assert result["status_altered"] is False
            assert result["status_column_type"] == "varchar(8)"
            assert result["merged_into_added"] is True
        finally:
            _drop_synth_tables()

    def test_missing_table_reports_error(self):
        result = ca._ensure_sense_split_columns_for("cs_senses_p5_nosuch")
        assert result["ok"] is False and "不存在" in result["error"]

    def test_main_db_migration_and_idempotency(self):
        """主库 cs_senses：merged_into 在场、status 列型不变、既有行分布不变。

        实测主库 status 为 varchar(8) 非 ENUM —— 枚举扩值分支不触发
        （'merged'(6)/'split'(5) 在 varchar(8) 内，新值直接可写，落地往返见
        TestExecuteSenseDivisionDB）。
        """
        with cs.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT status, COUNT(*) AS n FROM cs_senses GROUP BY status")
            before = {r["status"]: int(r["n"]) for r in cursor.fetchall()}
        ca.ensure_sense_split_columns()          # 公共入口（进程内 flag 直通）
        assert "cs_senses" in ca._ENSURED_SPLIT_TABLES
        forced = ca._ensure_sense_split_columns_for("cs_senses")  # 强制重跑内核
        assert forced["ok"] is True
        assert forced["status_altered"] is False
        assert forced["merged_into_added"] is False
        with cs.get_db_cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM cs_senses")
            cols = {r["Field"]: dict(r) for r in cursor.fetchall()}
        assert "merged_into" in cols
        assert cols["merged_into"]["Type"] == "int"
        assert cols["merged_into"]["Null"] == "YES"
        assert cols["status"]["Type"] == "varchar(8)"
        assert cols["status"]["Default"] == "保留"
        with cs.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT status, COUNT(*) AS n FROM cs_senses GROUP BY status")
            after = {r["status"]: int(r["n"]) for r in cursor.fetchall()}
        assert before == after  # 既有 '目标'/'保留'/'边缘'/'剔除' 行不受影响


SYNTH_CLUSTERS_TABLE = "cs_clusters_p6synth"


@requires_db
class TestClusterLockedColumnMigration:
    """ensure_cluster_locked_column：合成表验证幂等 ALTER → 主库验收（批次 6）。"""

    def _create_synth(self):
        with cs.get_db_cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {SYNTH_CLUSTERS_TABLE}")
            cursor.execute(f"""CREATE TABLE {SYNTH_CLUSTERS_TABLE} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                run_id INT NOT NULL,
                cluster_no INT NOT NULL,
                name VARCHAR(64) NOT NULL,
                size INT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")

    def _drop_synth(self):
        with cs.get_db_cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {SYNTH_CLUSTERS_TABLE}")

    def test_add_locked_roundtrip_and_idempotent(self):
        """locked 列缺失 → ADD TINYINT(1) NOT NULL DEFAULT 0；可写往返；二次零改动。"""
        self._create_synth()
        try:
            result = ca._ensure_cluster_locked_column_for(SYNTH_CLUSTERS_TABLE)
            assert result["ok"] is True and result["locked_added"] is True
            assert result["locked_column_type"] == "tinyint(1)"
            col = ca._column_meta(SYNTH_CLUSTERS_TABLE, "locked")
            assert col is not None
            assert str(col["COLUMN_TYPE"]).lower() == "tinyint(1)"
            assert str(col["COLUMN_DEFAULT"]) == "0"   # DEFAULT 0 = 初始未定稿
            assert str(col["IS_NULLABLE"]).upper() == "NO"
            assert "G3" in str(col["COLUMN_COMMENT"])
            # 往返：显式写 1 与缺省路径（DEFAULT 0）都成立
            with cs.get_db_cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SYNTH_CLUSTERS_TABLE} "
                    "(run_id, cluster_no, name, size, locked) "
                    "VALUES (1, 1, '簇甲', 2, 1)")
                cursor.execute(
                    f"INSERT INTO {SYNTH_CLUSTERS_TABLE} "
                    "(run_id, cluster_no, name, size) VALUES (1, 2, '簇乙', 1)")
                cursor.execute(
                    f"SELECT id, locked FROM {SYNTH_CLUSTERS_TABLE} ORDER BY id")
                rows = cursor.fetchall()
            assert int(rows[0]["locked"]) == 1
            assert int(rows[1]["locked"]) == 0
            # 幂等：第二次执行不再改动
            again = ca._ensure_cluster_locked_column_for(SYNTH_CLUSTERS_TABLE)
            assert again["ok"] is True and again["locked_added"] is False
            assert again["actions"] == []
        finally:
            self._drop_synth()

    def test_missing_table_reports_error(self):
        result = ca._ensure_cluster_locked_column_for("cs_clusters_p6_nosuch")
        assert result["ok"] is False and "不存在" in result["error"]

    def test_main_db_cs_clusters_locked_column(self):
        """主库 cs_clusters：locked 在场（TINYINT(1) DEFAULT 0）、重复执行幂等。"""
        ca.ensure_cluster_locked_column()          # 公共入口（进程内 flag 直通）
        assert "cs_clusters" in ca._ENSURED_LOCKED_TABLES
        forced = ca._ensure_cluster_locked_column_for("cs_clusters")  # 强制重跑内核
        assert forced["ok"] is True and forced["locked_added"] is False
        with cs.get_db_cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM cs_clusters")
            cols = {r["Field"]: dict(r) for r in cursor.fetchall()}
        assert "locked" in cols
        assert cols["locked"]["Type"] == "tinyint(1)"
        assert str(cols["locked"]["Default"]) == "0"


@requires_db
class TestExecuteSenseDivisionDB:
    """execute_sense_division / adjudicate_sense_division：真实 cs_senses 往返。

    放在本模块最后：UPDATE 只改 CLUSRUN 行的 status/merged_into（特征编码不动，
    不影响 medoid/tier 先验断言）；夹具 teardown 删 CLUSRUN 范畴 → CASCADE
    级联清掉全部测试行。
    """

    def _sense_ids(self, verbs):
        with cs.get_db_cursor() as cursor:
            placeholders = ",".join(["%s"] * len(verbs))
            cursor.execute(
                f"""SELECT l.lemma, s.id, s.status, s.merged_into
                    FROM cs_senses s
                    JOIN cs_lexemes l ON l.id = s.lexeme_id
                    JOIN categories c ON c.id = l.category_id
                    WHERE c.code = 'CLUSRUN' AND l.language = 'en'
                      AND l.lemma IN ({placeholders})""",
                list(verbs),
            )
            return {r["lemma"]: {"id": int(r["id"]), "status": r["status"],
                                 "merged_into": (int(r["merged_into"])
                                                 if r["merged_into"] is not None
                                                 else None)}
                    for r in cursor.fetchall()}

    def test_merge_execution(self, clusrun_seeded):
        ids = self._sense_ids(["aa", "bb"])
        aa_id, bb_id = ids["aa"]["id"], ids["bb"]["id"]
        proposal = {"action": "merge", "cluster_no": 1,
                    "sense_ids": [aa_id, bb_id], "target_sense_id": aa_id}
        result = ca.execute_sense_division(proposal)
        assert result["ok"] is True and result["updated"] == 1
        after = self._sense_ids(["aa", "bb"])
        assert after["bb"]["status"] == "merged"          # 被并方
        assert after["bb"]["merged_into"] == aa_id        # 指向保留目标
        assert after["aa"]["status"] == ids["aa"]["status"]  # 目标状态不动

    def test_split_execution(self, clusrun_seeded):
        cc_id = self._sense_ids(["cc"])["cc"]["id"]
        result = ca.execute_sense_division(
            {"action": "split", "cluster_no": 1, "sense_ids": [cc_id]})
        assert result["ok"] is True and result["updated"] == 1
        assert self._sense_ids(["cc"])["cc"]["status"] == "split"

    def test_keep_no_write(self, clusrun_seeded):
        ee = self._sense_ids(["ee"])["ee"]
        result = ca.execute_sense_division(
            {"action": "keep", "cluster_no": 1, "sense_ids": [ee["id"]]})
        assert result["ok"] is True and result["updated"] == 0
        after = self._sense_ids(["ee"])["ee"]
        assert after["status"] == ee["status"] and after["merged_into"] is None

    def test_invalid_payloads_rejected_before_write(self, clusrun_seeded):
        ee = self._sense_ids(["ee"])["ee"]
        before = self._sense_ids(["ee"])["ee"]
        for bad in ({"action": "bogus", "sense_ids": [ee["id"]]},
                    {"action": "merge", "sense_ids": [ee["id"]]},
                    {"action": "split", "sense_ids": []},
                    {"action": "split", "sense_ids": ["x"]}):
            result = ca.execute_sense_division(bad)
            assert result["ok"] is False, bad
        assert self._sense_ids(["ee"])["ee"] == before  # 库未被改动

    def test_adjudicate_adopted_end_to_end(self, clusrun_seeded):
        """record_proposal → adopted → cs_senses 落地 → 台账留痕（测试行清理）。"""
        from src import ai_ledger

        ai_ledger.ensure_ai_ledger_tables()
        ids = self._sense_ids(["dd", "ee"])
        dd_id, ee_id = ids["dd"]["id"], ids["ee"]["id"]
        proposal = {"action": "merge", "cluster_no": 1,
                    "sense_ids": [dd_id, ee_id], "target_sense_id": dd_id,
                    "reason": "测试合并"}
        pid = ai_ledger.record_proposal(
            "draft", ca.SENSE_DIVISION_STAGE, "CLUSRUN:en", proposal)
        assert pid
        try:
            result = ca.adjudicate_sense_division(
                pid, "adopted", "测试采纳（距离全 0）", 1, proposal)
            assert result["ok"] is True and result["executed"] is True
            after = self._sense_ids(["dd", "ee"])
            assert after["ee"]["status"] == "merged"
            assert after["ee"]["merged_into"] == dd_id
            record = ai_ledger.get_proposal(pid)
            assert record["status"] == "adopted"  # 台账不可变留痕
            assert record["decided_at"] is not None
        finally:
            with cs.get_db_cursor() as cursor:
                cursor.execute("DELETE FROM ai_proposals WHERE id = %s", (pid,))

    def test_adjudicate_rejected_record_only(self, clusrun_seeded):
        """否决：仅台账留痕，cs_senses 不动（否决必须给理由由页面层拦截）。"""
        from src import ai_ledger

        ai_ledger.ensure_ai_ledger_tables()
        ee = self._sense_ids(["ee"])["ee"]
        before = self._sense_ids(["ee"])["ee"]
        pid = ai_ledger.record_proposal(
            "draft", ca.SENSE_DIVISION_STAGE, "CLUSRUN:en",
            {"action": "split", "cluster_no": 1, "sense_ids": [ee["id"]],
             "reason": "测试拆分"})
        assert pid
        try:
            result = ca.adjudicate_sense_division(
                pid, "rejected", "证据不足，维持现状", 1,
                {"action": "split", "cluster_no": 1, "sense_ids": [ee["id"]]})
            assert result["ok"] is True and result["executed"] is False
            assert ai_ledger.get_proposal(pid)["status"] == "rejected"
            assert self._sense_ids(["ee"])["ee"] == before
        finally:
            with cs.get_db_cursor() as cursor:
                cursor.execute("DELETE FROM ai_proposals WHERE id = %s", (pid,))


@requires_db
class TestClusterLockDB:
    """set_cluster_locked / _load_cluster_locks：cs_clusters.locked UPDATE 往返。

    改动仅 CLUSRUN 簇行的 locked 列（特征/成员不动，不影响 medoid/tier 先验
    断言）；finally 复位 locked=0 并清 _load_cluster_locks 进程内缓存（
    cache_data 跨用例共享，防串扰）。
    """

    def _first_cluster_id(self):
        cats = [c for c in cs.get_categories() if c["code"] == "CLUSRUN"]
        runs = cs.get_cluster_runs(int(cats[0]["id"]), "en")
        clusters = cs.get_clusters_with_members(int(runs[0]["run_id"]))
        return int(clusters[0]["cluster_id"])

    def _db_locked(self, cid):
        with cs.get_db_cursor() as cursor:
            cursor.execute("SELECT locked FROM cs_clusters WHERE id = %s", (cid,))
            return int(cursor.fetchone()["locked"])

    def test_lock_unlock_roundtrip(self, clusrun_seeded):
        cid = self._first_cluster_id()
        try:
            result = ca.set_cluster_locked(cid, True)
            assert result == {"ok": True, "cluster_id": cid, "locked": True,
                              "updated": 1}
            assert self._db_locked(cid) == 1
            result = ca.set_cluster_locked(cid, False)
            assert result == {"ok": True, "cluster_id": cid, "locked": False,
                              "updated": 1}
            assert self._db_locked(cid) == 0
        finally:
            ca.set_cluster_locked(cid, False)
            ca._load_cluster_locks.clear()

    def test_invalid_cluster_id_rejected_before_write(self, clusrun_seeded):
        for bad in (None, 0, -1, "x", True):
            result = ca.set_cluster_locked(bad, True)
            assert result["ok"] is False, bad
            assert "cluster_id" in result["error"]

    def test_missing_cluster_reports_error(self, clusrun_seeded):
        result = ca.set_cluster_locked(999999999, True)
        assert result["ok"] is False and "不存在" in result["error"]

    def test_locks_loader_reads_state(self, clusrun_seeded):
        """cache_data 装载器读真值；写库后 clear 再读反映新状态。"""
        cid = self._first_cluster_id()
        try:
            ca._load_cluster_locks.clear()
            assert ca._load_cluster_locks("p6-lock-scope-a", (cid,)) == {cid: False}
            assert ca.set_cluster_locked(cid, True)["ok"] is True
            ca._load_cluster_locks.clear()  # set_cluster_locked 已清，防御性再清
            assert ca._load_cluster_locks("p6-lock-scope-b", (cid,)) == {cid: True}
            assert ca._load_cluster_locks("p6-lock-scope-c", ()) == {}
        finally:
            ca.set_cluster_locked(cid, False)
            ca._load_cluster_locks.clear()


# ============================================
# 10. 批次 5 页面：分立复核 / 义位图谱 tab（AppTest，打桩不需要 DB）
# ============================================

_DIV_PENDING = [{
    "id": 55,
    "kind": "draft",
    "stage": ca.SENSE_DIVISION_STAGE,
    "unit_ref": "motion:en",
    "proposal": {"action": "merge", "cluster_no": 1, "sense_ids": [1, 2],
                 "target_sense_id": 1, "reason": "距离全 0 应合并",
                 "senses": ["aa·1 L1", "bb·1 L2"], "run_id": 7,
                 "version": "预编码"},
    "evidence_ref": "预编码",
    "uncertainty": None,
    "status": "pending",
    "created_at": "2026-11-07 09:00:00",
}]


def _stub_page(monkeypatch, user=None, sense_rows=None, locks=None) -> AppTest:
    """四 tab 页面 + 全部 DB 触点打桩（迁移入口/cs_senses 现状/词频/锁定），不需要 DB。"""
    dendro = _synthetic_dendro(monkeypatch)
    monkeypatch.setattr(
        ca, "_load_page_data",
        lambda _scope, _c, _lang: {"ranking": _fake_ranking(),
                                   "dendro": dendro,
                                   "scipy_missing": False})
    monkeypatch.setattr(ca, "ensure_sense_split_columns", lambda: None)
    monkeypatch.setattr(ca, "ensure_cluster_locked_column", lambda: None)
    monkeypatch.setattr(ca, "_load_sense_rows", lambda _s, ids: sense_rows or {})
    monkeypatch.setattr(ca, "_load_word_freqs", lambda _s, verbs: {"aa": 100})
    monkeypatch.setattr(ca, "_load_cluster_locks", lambda _s, ids: locks or {})
    # 批次 8 合并页九 tab 全渲染：把英汉对比侧关掉（ready=False → 仅降级 caption，
    # 无 dataframe/slider/button），谱系侧控件计数断言与四 tab 时代同口径
    monkeypatch.setattr(ca, "category_study_ready", lambda: False)
    at = AppTest.from_string(PAGE_SCRIPT, default_timeout=60)
    if user is not None:
        at.session_state["user"] = user
    at.run()
    return at


class TestSenseDivisionTabPage:
    """分立复核 tab 三态（匿名/登录提议者/裁决者）＋ 建议提交流（打桩）。"""

    def _page(self, monkeypatch, user=None, pending=None):
        # list_pending 一律打桩（pending=None → 空收件箱）：tab 渲染不碰真实台账
        monkeypatch.setattr(ca, "list_pending", lambda **k: pending or [])
        return _stub_page(monkeypatch, user=user)

    def _by_key(self, at, accessor, key):
        return [w for w in getattr(at, accessor) if getattr(w, "key", "") == key]

    def test_anonymous_sees_evidence_only(self, monkeypatch):
        at = self._page(monkeypatch)
        assert not at.exception
        text = _page_text(at)
        assert "簇证据视图" in text
        assert "闸门 G3" in text
        assert "登录后即可发起分立建议" in text
        assert "当前会话无裁决权" in text
        # 匿名：无建议表单（提交按钮/多选不在场）、无裁决 expander
        assert self._by_key(at, "button", "ca_div_submit") == []
        assert self._by_key(at, "multiselect", "ca_div_senses") == []
        # 证据表在场（合成 ranking 1 簇 → 分立复核 1 张证据表）
        assert len(at.dataframe) == 2  # 谱系树重切表 + 分立证据表

    def test_logged_in_proposer_gets_form(self, monkeypatch):
        user = {"id": 2, "username": "editor", "role": "editor"}
        at = self._page(monkeypatch, user=user)
        assert not at.exception
        text = _page_text(at)
        assert "发起分立建议" in text
        assert "当前会话无裁决权" in text  # editor 无裁决权
        # 表单控件：动作/簇 selectbox ×2（页面级范畴语言另 2）、sense 多选、
        # 理由框、提交按钮
        assert len(self._by_key(at, "selectbox", "ca_div_action")) == 1
        assert len(self._by_key(at, "selectbox", "ca_div_cluster")) == 1
        assert len(self._by_key(at, "multiselect", "ca_div_senses")) == 1
        assert len(self._by_key(at, "text_area", "ca_div_reason")) == 1
        assert len(self._by_key(at, "button", "ca_div_submit")) == 1

    def test_submit_requires_reason(self, monkeypatch):
        user = {"id": 2, "username": "editor", "role": "editor"}
        recorded = []
        monkeypatch.setattr(
            ca, "record_proposal", lambda *a, **k: recorded.append((a, k)) or 1)
        at = self._page(monkeypatch, user=user)
        self._by_key(at, "button", "ca_div_submit")[0].click().run()
        assert not at.exception
        assert any("理由必填" in e.value for e in at.error)
        assert recorded == []  # 校验未过不进台账

    def test_submit_merge_records_proposal(self, monkeypatch):
        user = {"id": 2, "username": "editor", "role": "editor"}
        captured = {}

        def fake_record(kind, stage, unit_ref, proposal, **kwargs):
            captured.update(kind=kind, stage=stage, unit_ref=unit_ref,
                            proposal=proposal, **kwargs)
            return 123

        monkeypatch.setattr(ca, "record_proposal", fake_record)
        at = self._page(monkeypatch, user=user)
        # 选动作 merge + 两个 sense（选项 = 显示名 (#sense_id)）
        self._by_key(at, "selectbox", "ca_div_action")[0].set_value("merge").run()
        self._by_key(at, "multiselect", "ca_div_senses")[0].set_value(
            ["aa·1 L1 (#1)", "bb·1 L2 (#2)"]).run()
        # merge 目标 selectbox 在选完 sense 后出现（默认第一项 = aa）
        target = self._by_key(at, "selectbox", "ca_div_target")
        assert len(target) == 1
        self._by_key(at, "text_area", "ca_div_reason")[0].set_value(
            "aa/bb 距离全 0，释义同指应合并").run()
        self._by_key(at, "button", "ca_div_submit")[0].click().run()
        assert not at.exception
        assert captured, "record_proposal 应被调用"
        assert captured["kind"] == "draft"
        assert captured["stage"] == ca.SENSE_DIVISION_STAGE
        assert captured["unit_ref"] == "motion:en"
        assert captured["proposal"]["action"] == "merge"
        assert captured["proposal"]["sense_ids"] == [1, 2]
        assert captured["proposal"]["target_sense_id"] == 1
        assert captured["evidence_ref"] == "预编码"      # evidence_ref=簇运行版本
        assert captured["uncertainty"] is None           # 人工建议不编不确定度
        assert captured["created_by"] == 2
        assert any("提案 #123" in s.value for s in at.success)

    def test_adjudicator_sees_pending_and_adopt_executes(self, monkeypatch):
        user = {"id": 1, "username": "chief", "role": "admin"}
        calls = {}

        def fake_adjudicate(pid, decision, reason, decider, proposal):
            calls.update(pid=pid, decision=decision, reason=reason,
                         decider=decider, proposal=proposal)
            return {"ok": True, "decision": decision, "executed": True,
                    "updated": 1}

        monkeypatch.setattr(ca, "adjudicate_sense_division", fake_adjudicate)
        at = self._page(monkeypatch, user=user, pending=_DIV_PENDING)
        assert not at.exception
        text = _page_text(at)
        assert "裁决区" in text
        assert "共 1 条待裁决" in text
        # 待裁决 expander（标题含提案号/动作/单元）＋ 三裁决按钮在场
        assert any("提案 #55" in e.label for e in at.expander)
        assert len(self._by_key(at, "button", "ca_div_adopt_55")) == 1
        assert len(self._by_key(at, "button", "ca_div_reject_55")) == 1
        assert len(self._by_key(at, "button", "ca_div_modify_55")) == 1
        assert len(self._by_key(at, "text_area", "ca_div_reason_55")) == 1
        self._by_key(at, "text_area", "ca_div_reason_55")[0].set_value(
            "证据充分").run()
        self._by_key(at, "button", "ca_div_adopt_55")[0].click().run()
        assert not at.exception
        assert calls["pid"] == 55 and calls["decision"] == "adopted"
        assert calls["decider"] == 1
        assert calls["proposal"]["action"] == "merge"
        assert any("已采纳并落地" in s.value for s in at.success)

    def test_reject_requires_reason(self, monkeypatch):
        user = {"id": 1, "username": "chief", "role": "admin"}
        calls = []
        monkeypatch.setattr(
            ca, "adjudicate_sense_division",
            lambda *a, **k: calls.append(a) or {"ok": True})
        at = self._page(monkeypatch, user=user, pending=_DIV_PENDING)
        self._by_key(at, "button", "ca_div_reject_55")[0].click().run()
        assert not at.exception
        assert calls == []  # 否决无理由：页面层拦截，未进裁决
        # 拦截提示走 _flash_division("error") → st.error
        assert any("否决必须填写理由" in e.value for e in at.error)

    def test_empty_pending_shows_info(self, monkeypatch):
        user = {"id": 1, "username": "chief", "role": "admin"}
        monkeypatch.setattr(ca, "list_pending", lambda **k: [])
        at = self._page(monkeypatch, user=user, pending=[])
        assert not at.exception
        assert any("暂无待裁决" in i.value for i in at.info)


class TestSenseGraphTabPage:
    """义位图谱 tab（打桩）：MDS 注记 / 边表开关 / 分组滑杆。"""

    def _page(self, monkeypatch):
        return _stub_page(monkeypatch)

    def test_graph_renders_with_metric_annotation(self, monkeypatch):
        at = self._page(monkeypatch)
        assert not at.exception
        text = _page_text(at)
        assert "义位图谱" in text
        # 论文 §7.2 口径注记与本实现如实差异在场
        assert "论文 §7.2" in text
        assert "经典 MDS" in text
        assert "解释率" in text
        assert "零新依赖" in text
        assert "不是精确还原" in text
        # 边表开关在场；未勾选时无边表（全页面 dataframe = 重切表 + 证据表）
        edges_cb = [c for c in at.checkbox if c.key == "ca_graph_edges"]
        assert len(edges_cb) == 1
        assert edges_cb[0].value is False
        assert len(at.dataframe) == 2

    def test_edge_table_toggle(self, monkeypatch):
        at = self._page(monkeypatch)
        before = len(at.dataframe)
        [c for c in at.checkbox if c.key == "ca_graph_edges"][0].check().run()
        assert not at.exception
        assert len(at.dataframe) == before + 1  # 边表出现在场
        edge_df = at.dataframe[-1].value
        assert list(edge_df.columns) == ["簇", "成员对", "Gower 距离"]


# ============================================
# 11. 批次 6 页面：簇锁定控件 / 落地计数 / merged 标注（AppTest，打桩）
# ============================================

class TestClusterLockTabPage:
    """簇锁定（G3 闸门写路径）：匿名仅提示、裁决者锁定/解锁流、失败报错。"""

    def _page(self, monkeypatch, user=None, locks=None) -> AppTest:
        monkeypatch.setattr(ca, "list_pending", lambda **k: [])
        return _stub_page(monkeypatch, user=user, locks=locks)

    def _by_key(self, at, accessor, key):
        return [w for w in getattr(at, accessor) if getattr(w, "key", "") == key]

    def test_anonymous_sees_hint_only(self, monkeypatch):
        at = self._page(monkeypatch)
        assert not at.exception
        assert self._by_key(at, "button", "ca_lock_btn") == []
        assert self._by_key(at, "button", "ca_unlock_btn") == []
        assert self._by_key(at, "selectbox", "ca_lock_cluster") == []
        text = _page_text(at)
        assert "簇锁定" in text
        assert "词典管理员/审校执行" in text

    def test_adjudicator_gets_lock_controls(self, monkeypatch):
        user = {"id": 1, "username": "chief", "role": "admin"}
        at = self._page(monkeypatch, user=user)
        assert not at.exception
        assert len(self._by_key(at, "selectbox", "ca_lock_cluster")) == 1
        assert len(self._by_key(at, "button", "ca_lock_btn")) == 1
        assert len(self._by_key(at, "button", "ca_unlock_btn")) == 1

    def test_lock_button_writes_and_flashes(self, monkeypatch):
        calls = []

        def fake_lock(cid, locked):
            calls.append((cid, locked))
            return {"ok": True, "cluster_id": cid, "locked": locked, "updated": 1}

        monkeypatch.setattr(ca, "set_cluster_locked", fake_lock)
        at = self._page(monkeypatch, user={"id": 1, "role": "admin"})
        self._by_key(at, "button", "ca_lock_btn")[0].click().run()
        assert not at.exception
        assert calls == [(71, True)]  # 合成证据簇 cluster_id=71
        assert any("已锁定" in s.value for s in at.success)

    def test_unlock_button_writes_and_flashes(self, monkeypatch):
        calls = []

        def fake_lock(cid, locked):
            calls.append((cid, locked))
            return {"ok": True, "cluster_id": cid, "locked": locked, "updated": 1}

        monkeypatch.setattr(ca, "set_cluster_locked", fake_lock)
        at = self._page(monkeypatch, user={"id": 1, "role": "admin"},
                        locks={71: True})
        self._by_key(at, "button", "ca_unlock_btn")[0].click().run()
        assert not at.exception
        assert calls == [(71, False)]
        assert any("已解锁" in s.value for s in at.success)

    def test_lock_on_locked_cluster_noops_with_info(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            ca, "set_cluster_locked",
            lambda cid, locked: calls.append((cid, locked))
            or {"ok": True, "cluster_id": cid, "locked": locked, "updated": 1})
        at = self._page(monkeypatch, user={"id": 1, "role": "admin"},
                        locks={71: True})
        self._by_key(at, "button", "ca_lock_btn")[0].click().run()
        assert not at.exception
        assert calls == []  # 已锁定 → 幂等提示，不重复写库
        assert any("已处于锁定状态" in i.value for i in at.info)

    def test_unlock_on_unlocked_cluster_noops_with_info(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            ca, "set_cluster_locked",
            lambda cid, locked: calls.append((cid, locked))
            or {"ok": True, "cluster_id": cid, "locked": locked, "updated": 1})
        at = self._page(monkeypatch, user={"id": 1, "role": "admin"})
        self._by_key(at, "button", "ca_unlock_btn")[0].click().run()
        assert not at.exception
        assert calls == []
        assert any("未锁定" in i.value for i in at.info)

    def test_lock_failure_shows_error(self, monkeypatch):
        monkeypatch.setattr(ca, "set_cluster_locked",
                            lambda cid, locked: {"ok": False, "error": "写库失败"})
        at = self._page(monkeypatch, user={"id": 1, "role": "admin"})
        self._by_key(at, "button", "ca_lock_btn")[0].click().run()
        assert not at.exception
        assert not at.success
        assert any("锁定失败" in e.value for e in at.error)

    def test_locked_cluster_badge_in_evidence(self, monkeypatch):
        """locked 簇在证据视图加「已锁定」徽章（expander 标题纯文本＋段内徽章）。"""
        at = self._page(monkeypatch, locks={71: True})
        assert not at.exception
        text = _page_text(at)
        assert "已锁定" in text
        assert any("已锁定" in e.label for e in at.expander)  # expander 标题标注


class TestMergedConsumptionPage:
    """merged 消费收口（页面级）：落地计数 + 证据表「已并入 → #N」标注。"""

    def test_adjudication_area_shows_landing_counts(self, monkeypatch):
        user = {"id": 1, "username": "chief", "role": "admin"}
        monkeypatch.setattr(ca, "list_pending", lambda **k: [])
        at = _stub_page(monkeypatch, user=user, sense_rows={
            1: {"status": "merged", "merged_into": 2},
            2: {"status": "split", "merged_into": None},
            3: {"status": "目标", "merged_into": None}})
        assert not at.exception
        text = _page_text(at)
        assert "cs_senses 落地结果计数" in text
        assert "merged 1 条" in text and "split 1 条" in text
        assert "已并入不计入" in text

    def test_evidence_table_annotates_merged_members(self, monkeypatch):
        monkeypatch.setattr(ca, "list_pending", lambda **k: [])
        at = _stub_page(monkeypatch, sense_rows={
            1: {"status": "merged", "merged_into": 2},
            2: {"status": "目标", "merged_into": None}})
        assert not at.exception
        # 分立证据表 = 全页第 2 张 dataframe（第 1 张是谱系树重切表）
        df = at.dataframe[1].value
        col = df.set_index("sense_id")["cs_senses 现状"]
        assert col[1] == "已并入 → #2"
        assert col[2] == "目标"

    def test_graph_tab_notes_merged_skipped(self, monkeypatch):
        """图谱 tab 注记「N 条已并入不计入」（打桩 sense_rows 含 merged 行）。"""
        monkeypatch.setattr(ca, "list_pending", lambda **k: [])
        at = _stub_page(monkeypatch, sense_rows={
            1: {"status": "merged", "merged_into": 2},
            2: {"status": "merged", "merged_into": 3}})
        assert not at.exception
        text = _page_text(at)
        assert "2 条已并入不计入" in text
        assert "消费流向其并入目标" in text
