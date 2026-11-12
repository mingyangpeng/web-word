"""图式范畴化引擎（批次 32，src/schema_family.py）测试。

三层覆盖（全部纯计算/打桩，不依赖 MySQL）：
  1. 引擎纯函数：三级归属向量（core=2 压过 slot=1、空码剔除）、Gower
     nominal（并集可比、已知合成距离 0.5/1.0、空向量 0.0）、方阵对称性、
     UPGMA 家族切割（max_distance=0.5 边界合并已知对、max_distance=1.0
     全员单族）、medoid 选取（平局取首、单成员族直取）；
  2. build_schema_families 端到端：合成三图式（两同族＋一异族）→ 家族
     结构断言（成员/is_prototype 唯一性/avg_distance/代表图式核心要素）
     ＋ **proto 错位回归**（曾用「成员在族内位置」索引「按族迭代序」排
     列的 medoids 列表——族排序后错位会取到别族代表：断言每族恰一个
     is_prototype 且其 cluster_no 与 prototype.cluster_no 一致、多成员族
     代表=族内平均距离最小者，可直接捕获该缺陷）；families_summary 读面；
  3. 工具面与页面接线：SchemaFamilyTool.run 两参委托（schemas 必填、
     max_distance 默认 0.5）、list_tools 含 schema_family（12 号内置工
     具）、cluster_analysis._render_schema_family_tab 打桩渲染（≥2 图式
     计算流／<2 图式降级 info——R4 口径）。

合成图式形态与 derive_cluster_schemas 输出对齐（core_features 带
code/label、variable_slots 带 code/label/value_type），保证真实数据可跑。
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import schema_family as sf  # noqa: E402


# ============================================
# 合成图式（对齐 derive_cluster_schemas 输出形态）
# ============================================

def _schema(cluster_no, name, core, slots):
    return {
        "cluster_id": 100 + cluster_no,
        "cluster_no": cluster_no,
        "cluster_name": name,
        "size": 3,
        "schema_core": {c: 1.0 for c in core},
        "core_features": [
            {"code": c, "label": f"特征{c}", "mean": 1.0, "value_label": "有"}
            for c in core
        ],
        "variable_slots": [
            {"code": c, "label": f"槽位{c}", "value_type": "binary",
             "distribution": []}
            for c in slots
        ],
        "members": [{"sense_id": 900 + cluster_no, "lemma": f" lemma{cluster_no}"}],
    }


# S1/S2 同族（仅 C1/C2 槽位不同 → Gower 0.5，= max_distance 边界可并）；
# S3 异族（核心 P2 vs P1/M1 → 到两者皆 1.0）
S1 = _schema(1, "自移簇", ["P1", "M1"], ["C1"])
S2 = _schema(2, "他移簇", ["P1", "M1"], ["C2"])
S3 = _schema(3, "使移簇", ["P2"], [])


# ============================================
# 1. 纯函数
# ============================================

class TestLevelVector:
    def test_core_and_slot(self):
        v = sf.schema_level_vector(S1)
        assert v == {"P1": 2, "M1": 2, "C1": 1}

    def test_core_wins_over_slot(self):
        sc = dict(S1)
        sc["variable_slots"] = [{"code": "P1", "label": "槽位P1",
                                 "value_type": "binary", "distribution": []}]
        assert sf.schema_level_vector(sc)["P1"] == sf.LEVEL_CORE

    def test_empty_and_blank_codes(self):
        assert sf.schema_level_vector({}) == {}
        sc = {"core_features": [{"code": "  "}], "variable_slots": [{}]}
        assert sf.schema_level_vector(sc) == {}

    def test_absent_default(self):
        v = sf.schema_level_vector(S1)
        assert v.get("P9", sf.LEVEL_ABSENT) == 0


class TestGower:
    def test_identical_zero(self):
        v = sf.schema_level_vector(S1)
        assert sf.schema_gower(v, v) == 0.0

    def test_known_half(self):
        # S1/S2 并集 {P1,M1,C1,C2}，C1(1vs0)+C2(0vs1) 两码不同 → 0.5
        assert sf.schema_gower(sf.schema_level_vector(S1),
                               sf.schema_level_vector(S2)) == 0.5

    def test_known_full(self):
        # S1/S3 并集 {P1,M1,C1,P2} 全不同（C1: 槽位 vs 核心 也是类型差异）
        assert sf.schema_gower(sf.schema_level_vector(S1),
                               sf.schema_level_vector(S3)) == 1.0

    def test_empty_vectors(self):
        assert sf.schema_gower({}, {}) == 0.0

    def test_matrix_symmetric(self):
        vecs = [sf.schema_level_vector(s) for s in (S1, S2, S3)]
        m = sf.schema_gower_matrix(vecs)
        assert len(m) == 3
        for i in range(3):
            assert m[i][i] == 0.0
            for j in range(3):
                assert m[i][j] == m[j][i]


class TestClusters:
    def test_single_and_empty(self):
        assert sf.schema_family_clusters([]) == ([], [])
        assert sf.schema_family_clusters([[0.0]]) == ([1], [0])

    def test_boundary_merge_at_max_distance(self):
        # S1-S2 = 0.5 ≤ 0.5 → 同族；S3 孤族
        labels, medoids = sf.schema_family_clusters(
            sf.schema_gower_matrix(
                [sf.schema_level_vector(s) for s in (S1, S2, S3)]))
        assert labels[0] == labels[1]
        assert labels[2] != labels[0]
        assert len(medoids) == len(set(labels))  # 每族恰一 medoid
        assert 0 in medoids and 2 in medoids
        # 平局（S1/S2 互距同）→ medoid 取首
        assert medoids[labels.index(labels[0])] == 0

    def test_all_one_family_at_high_threshold(self):
        m = sf.schema_gower_matrix(
            [sf.schema_level_vector(s) for s in (S1, S2, S3)])
        labels, medoids = sf.schema_family_clusters(m, max_distance=1.0)
        assert len(set(labels)) == 1
        # 全族 medoid = 平均距离最小者（S1: 0.75, S2: 0.75, S3: 1.0 → 平局取首）
        assert medoids == [0]


# ============================================
# 2. build_schema_families 端到端（含 proto 错位回归）
# ============================================

class TestBuildFamilies:
    def test_too_few_schemas(self):
        assert sf.build_schema_families([]) == {"families": [], "n_schemas": 0}
        r = sf.build_schema_families([S1])
        assert r["families"] == [] and r["n_schemas"] == 1

    def test_two_families_structure(self):
        r = sf.build_schema_families([S1, S2, S3])
        assert r["n_schemas"] == 3
        assert len(r["families"]) == 2
        assert len(r["labels"]) == 3 and len(r["medoids"]) == 2
        fam12 = next(f for f in r["families"] if len(f["members"]) == 2)
        assert fam12["avg_distance"] == 0.5
        # 成员按簇号升序、is_prototype 恰一且与 prototype 一致
        nos = [m["cluster_no"] for m in fam12["members"]]
        assert nos == sorted(nos)
        protos = [m for m in fam12["members"] if m["is_prototype"]]
        assert len(protos) == 1
        assert protos[0]["cluster_no"] == fam12["prototype"]["cluster_no"]

    def test_proto_not_misaligned_regression(self):
        """proto 错位回归：曾用族内位置索引按族序排列的 medoids——错位时
        prototype 会指向不在本族成员里的图式，此处必炸。"""
        r = sf.build_schema_families([S1, S2, S3])
        for f in r["families"]:
            member_nos = {m["cluster_no"] for m in f["members"]}
            assert f["prototype"]["cluster_no"] in member_nos
            flags = [m["is_prototype"] for m in f["members"]]
            assert flags.count(True) == 1
            # 多成员族：代表 = 族内平均 Gower 距离最小者（同判据同序）
            if len(f["members"]) > 1:
                vecs = [sf.schema_level_vector(s) for s in (S1, S2, S3)]
                dist = sf.schema_gower_matrix(vecs)
                idx = {m["cluster_no"]: m["cluster_no"] - 1 for m in f["members"]}
                best = min(
                    idx.values(),
                    key=lambda i: sum(dist[i][o] for o in idx.values() if o != i)
                    / (len(idx) - 1))
                assert f["prototype"]["cluster_no"] == best + 1

    def test_prototype_core_features_carried(self):
        r = sf.build_schema_families([S1, S2, S3])
        fam12 = next(f for f in r["families"] if len(f["members"]) == 2)
        codes = [cf["code"] for cf in fam12["prototype"]["core_features"]]
        assert codes == ["P1", "M1"]  # 平局取首 → S1 的核心要素

    def test_single_member_family_avg_zero(self):
        r = sf.build_schema_families([S1, S2, S3])
        lone = next(f for f in r["families"] if len(f["members"]) == 1)
        assert lone["avg_distance"] == 0.0
        assert lone["members"][0]["is_prototype"] is True
        assert lone["members"][0]["level_vector"] == {"P2": 2}

    def test_summary_rows(self):
        rows = sf.families_summary(sf.build_schema_families([S1, S2, S3]))
        assert len(rows) == 2
        row12 = next(x for x in rows if "·自移簇" in x["members"])
        assert row12["prototype"] == "自移簇"
        assert row12["avg_distance"] == 0.5

    def test_input_not_mutated(self):
        schemas = [S1, S2, S3]
        snapshot = [{k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                     for k, v in s.items()} for s in schemas]
        sf.build_schema_families(schemas)
        assert schemas == snapshot


# ============================================
# 3. 工具面与页面接线
# ============================================

class TestToolAndPage:
    def _tool(self):
        from src.tools.builtin import schema_family_tool as mod
        return mod.SchemaFamilyTool()

    def test_tool_spec_fields(self):
        t = self._tool()
        assert t.id == "schema_family" and t.stage == "schema_family"
        assert t.ui_surface == "page:cluster"
        assert t.params_schema["schemas"]["required"] is True
        assert t.params_schema["max_distance"]["default"] == 0.5

    def test_tool_run_delegates(self):
        r = self._tool().run({"schemas": [S1, S2, S3]})
        assert r["n_schemas"] == 3 and len(r["families"]) == 2
        r2 = self._tool().run({"schemas": [S1, S2, S3], "max_distance": 1.0})
        assert len(r2["families"]) == 1
        # 必填缺省按 registry 口径拒绝；空列表走空态（R4）
        from src.tools.registry import RegistryError
        with pytest.raises(RegistryError):
            self._tool().run({})
        assert self._tool().run({"schemas": []})["n_schemas"] == 0

    def test_tool_registered_in_registry(self):
        from src.tools.registry import list_tools
        ids = [t.id for t in list_tools()]
        assert "schema_family" in ids
        assert len(ids) == 12  # 第 12 个内置工具

    def _fake_st(self):
        calls = {"markdown": [], "caption": [], "info": [],
                 "dataframe": [], "button": []}

        class FakeSt(types.SimpleNamespace):
            pass

        def _rec(name):
            def f(*a, **k):
                calls[name].append((a, k))
                if name == "button":
                    return True
                return None
            return f

        fake = FakeSt(
            markdown=_rec("markdown"), caption=_rec("caption"),
            info=_rec("info"), dataframe=_rec("dataframe"),
            button=_rec("button"), session_state={},
        )
        return fake, calls

    def test_tab_renders_families(self, monkeypatch):
        import src.cluster_analysis as ca
        import src.template_engine as te
        monkeypatch.setattr(te, "derive_cluster_schemas",
                            lambda c, l: [S1, S2, S3])
        fake, calls = self._fake_st()
        monkeypatch.setattr(ca, "st", fake)
        ca._render_schema_family_tab("MOTION", "en")
        assert len(calls["dataframe"]) == 1  # 家族表
        # session_state 按范畴+语言落键
        assert "schema_family_result_MOTION_en" in fake.session_state
        # 家族卡片 markdown 含成员与代表图式
        cards = [a[0][0] for a in calls["markdown"] if "家族" in (a[0][0] if a[0] else "")]
        assert any("自移簇" in c for c in cards)
        assert any("使移簇" in c for c in cards)

    def test_tab_degrades_below_two(self, monkeypatch):
        import src.cluster_analysis as ca
        import src.template_engine as te
        monkeypatch.setattr(te, "derive_cluster_schemas", lambda c, l: [S1])
        fake, calls = self._fake_st()
        monkeypatch.setattr(ca, "st", fake)
        ca._render_schema_family_tab("MOTION", "zh")
        assert len(calls["info"]) == 1  # 降级 info（R4 口径）
        assert calls["dataframe"] == []
