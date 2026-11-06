"""聚类可视化与典型性排序（cluster_analysis）测试。

三层覆盖：
  1. 纯函数（不碰数据库）：Gower 分支（binary/nominal 记不一致、ordinal
     归一差值）→ 合成特征向量构造**已知 medoid** 的小簇验证选取正确；
     tier 三分位边界（n=9 精确三等分、n=7/2/1 的小簇行为、自定义份额、
     平局稳定性）；谱系树 linkage 行数（n-1 次合并）与 k 切分高度一致性。
  2. 范畴包元数据（纯文件系统）：configs/motion/features.yaml 的
     value_type 装载与 A 区排除。
  3. 数据层与页面（需 MySQL，skipif）：种子范畴 CLUSRUN 端到端
     （medoid 先验已知，可断言精确值）+ AppTest 页面冒烟
     （含无数据降级路径，不需要 DB）。

没有可用的 MySQL 时数据层/页面冒烟测试 skip（与 test_category_study 同口径）。
"""

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
        assert "聚类可视化与典型性排序" in text

    @requires_db
    def test_smoke_with_real_data(self):
        """真实 RUN 数据（motion/en）页面冒烟：不抛异常、双 tab 在场。"""
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=120)
        at.run()
        assert not at.exception
        text = _page_text(at)
        assert "谱系树" in text
        assert "典型性排序" in text
        assert "medoid" in text.lower()
        # 簇展开卡 + tier 徽章在场（真实 RUN 数据 = 英 5 簇）
        assert len(at.expander) == 5
