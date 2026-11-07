"""Krippendorff's α 信度引擎的合成数据验证（验收 V4 + 任务要求 1-5）。

全部用**已知结果的合成数据**：

  ① 两编码人完全一致 → α = 1.0；
  ② 经典可查表数据（Krippendorff 原文第 8 页例，krippendorff 库 doctest 引用）
     + 本仓库手工推导的算例（巧合矩阵公式逐步计算）→ 误差 < 0.01；
  ③ 同一批数据 ordinal 与 nominal 结果不同（分支生效）；
  ④ 缺失值容忍（某 coder 缺一半 unit 不报错，且两条计算路径一致）；
  ⑤ 单人数据返回 None（不可计算）。

两条计算路径都验证：krippendorff 库（主路径）与纯 Python 回退
（monkeypatch 掉 KRIPPENDORFF_AVAILABLE 强制启用）。

run_reliability 的数据库路径用 test_schema.py 同款「按 SQL 文本分派」的假游标，
不连真实 MySQL（CI 无库也全绿）。
"""

import json
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.reliability as rel  # noqa: E402


# ============================================
# 工具
# ============================================
NAN = float("nan")


def _alpha(units, value_type, monkeypatch=None, pure=False):
    """compute_alpha 的便捷封装；pure=True 时强制走纯 Python 回退路径。"""
    if pure:
        assert monkeypatch is not None
        monkeypatch.setattr(rel, "KRIPPENDORFF_AVAILABLE", False)
    return rel.compute_alpha(units, value_type)


def _columns_to_units(columns):
    """(编码人 × 单元) 矩阵（list of rows，缺失 None/NaN）→ units dict。"""
    n_rows = len(columns)
    n_cols = len(columns[0]) if n_rows else 0
    units = {}
    for j in range(n_cols):
        inner = {}
        for i in range(n_rows):
            v = columns[i][j]
            missing = v is None or (isinstance(v, float) and v != v)
            if not missing:
                inner[i + 1] = v  # coder_id 从 1 起
        if inner:
            units[j + 1] = inner  # unit_id 从 1 起
    return units


# ============================================
# ① 完全一致 → 1.0
# ============================================
class TestPerfectAgreement:
    UNITS = {
        101: {1: "Y", 2: "Y"},
        102: {1: "Y", 2: "Y"},
        103: {1: "N", 2: "N"},
        104: {1: "EXT", 2: "EXT"},
    }

    @pytest.mark.parametrize("pure", [False, True])
    def test_nominal_perfect(self, monkeypatch, pure):
        assert _alpha(self.UNITS, "nominal", monkeypatch, pure) == 1.0

    @pytest.mark.parametrize("pure", [False, True])
    def test_ordinal_perfect(self, monkeypatch, pure):
        units = {i: {1: k, 2: k} for i, k in zip(range(1, 5), [1, 2, 2, 3])}
        assert _alpha(units, "ordinal", monkeypatch, pure) == 1.0


# ============================================
# ② 已知结果（手算 / 可查表）→ 误差 < 0.01
# ============================================
class TestKnownAlphaValues:
    # --- 手推算例 A：2 编码人 × 4 单元，(a,a),(a,b),(b,a),(b,b) ---
    # 巧合矩阵 o = [[2,2],[2,2]]，n_v = [4,4]，n = 8
    # α = 1 − (n−1)·Σ_{c≠k} o_ck δ / Σ_{c≠k} n_c n_k δ = 1 − 7·4/32 = 0.125
    UNITS_A = {
        1: {1: "a", 2: "a"},
        2: {1: "a", 2: "b"},
        3: {1: "b", 2: "a"},
        4: {1: "b", 2: "b"},
    }
    ALPHA_A_NOMINAL = 0.125

    # --- 手推算例 B：2 编码人 × 9 单元，分歧全在相邻秩 ---
    # coder1: 1,2,3,2,1,2,3,1,3   coder2: 2,3,2,1,1,2,3,1,3
    # nominal: Σ_{c≠k} o_ck δ = 8，n_v = [6,6,6]，α = 1 − 17·8/216 = 0.3704
    # ordinal: n_v=[6,6,6] → d12=d23=36, d13=144
    #          Σ o·d = 288，Σ n·n·d = 15552，α = 1 − 17·288/15552 = 0.6852
    UNITS_B = {
        1: {1: 1, 2: 2}, 2: {1: 2, 2: 3}, 3: {1: 3, 2: 2},
        4: {1: 2, 2: 1}, 5: {1: 1, 2: 1}, 6: {1: 2, 2: 2},
        7: {1: 3, 2: 3}, 8: {1: 1, 2: 1}, 9: {1: 3, 2: 3},
    }
    ALPHA_B_NOMINAL = 0.3704
    ALPHA_B_ORDINAL = 0.6852

    # --- 经典可查表数据 1（Krippendorff 原文 p.8 例，库 doctest：nominal 0.691358）---
    DOC_NOMINAL = [
        [NAN, NAN, NAN, NAN, NAN, 3, 4, 1, 2, 1, 1, 3, 3, NAN, 3],
        [1, NAN, 2, 1, 3, 3, 4, 3, NAN, NAN, NAN, NAN, NAN, NAN, NAN],
        [NAN, NAN, 2, 1, 3, 4, 4, NAN, 2, 1, 1, 3, 3, NAN, 4],
    ]

    # --- 经典可查表数据 2（同上，ordinal 0.815）---
    DOC_ORDINAL = [
        [1, 2, 3, 3, 2, 1, 4, 1, 2, NAN, NAN, NAN],
        [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, NAN, 3],
        [NAN, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, NAN],
        [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, NAN],
    ]

    @pytest.mark.parametrize("pure", [False, True])
    def test_hand_computed_a_nominal(self, monkeypatch, pure):
        got = _alpha(self.UNITS_A, "nominal", monkeypatch, pure)
        assert got == pytest.approx(self.ALPHA_A_NOMINAL, abs=0.01)

    @pytest.mark.parametrize("pure", [False, True])
    def test_hand_computed_b_nominal(self, monkeypatch, pure):
        got = _alpha(self.UNITS_B, "nominal", monkeypatch, pure)
        assert got == pytest.approx(self.ALPHA_B_NOMINAL, abs=0.01)

    @pytest.mark.parametrize("pure", [False, True])
    def test_hand_computed_b_ordinal(self, monkeypatch, pure):
        got = _alpha(self.UNITS_B, "ordinal", monkeypatch, pure)
        assert got == pytest.approx(self.ALPHA_B_ORDINAL, abs=0.01)

    @pytest.mark.parametrize("pure", [False, True])
    def test_classic_table_nominal(self, monkeypatch, pure):
        units = _columns_to_units(self.DOC_NOMINAL)
        got = _alpha(units, "nominal", monkeypatch, pure)
        assert got == pytest.approx(0.691358, abs=0.01)

    @pytest.mark.parametrize("pure", [False, True])
    def test_classic_table_ordinal(self, monkeypatch, pure):
        units = _columns_to_units(self.DOC_ORDINAL)
        got = _alpha(units, "ordinal", monkeypatch, pure)
        assert got == pytest.approx(0.815, abs=0.01)

    @pytest.mark.parametrize("pure", [False, True])
    def test_two_paths_agree(self, monkeypatch, pure):
        """库路径与纯 Python 回退在同一批缺失数据上必须给出同一结果。"""
        units = _columns_to_units(self.DOC_NOMINAL)
        lib = rel.compute_alpha(units, "nominal")
        pure_val = _alpha(units, "nominal", monkeypatch, pure=True)
        assert lib == pytest.approx(pure_val, abs=1e-9)


# ============================================
# ③ ordinal 与 nominal 分支各异（同数据）
# ============================================
class TestOrdinalNominalBranches:
    def test_same_data_different_alpha(self, monkeypatch):
        units = TestKnownAlphaValues.UNITS_B
        nominal = _alpha(units, "nominal", monkeypatch)
        ordinal = _alpha(units, "ordinal", monkeypatch)
        assert nominal == pytest.approx(0.3704, abs=0.01)
        assert ordinal == pytest.approx(0.6852, abs=0.01)
        assert ordinal != pytest.approx(nominal, abs=0.05)

    def test_adjacent_disagreement_rewards_ordinal(self, monkeypatch):
        """分歧都在相邻秩上时 ordinal 应显著高于 nominal（把 1↔3 视为最远）。"""
        units = {
            1: {1: 1, 2: 2}, 2: {1: 2, 2: 1},
            3: {1: 1, 2: 2}, 4: {1: 2, 2: 1},
            5: {1: 3, 2: 3}, 6: {1: 1, 2: 1},
        }
        nominal = _alpha(units, "nominal", monkeypatch)
        ordinal = _alpha(units, "ordinal", monkeypatch)
        assert ordinal > nominal + 0.05

    def test_binary_value_type_maps_to_nominal(self, monkeypatch):
        """features.yaml 的 value_type='binary' 按 nominal 分支算，结果一致。"""
        units = TestKnownAlphaValues.UNITS_B
        assert _alpha(units, "binary", monkeypatch) == pytest.approx(
            _alpha(units, "nominal", monkeypatch), abs=1e-12
        )


# ============================================
# ④ 缺失值容忍
# ============================================
class TestMissingTolerance:
    def test_coder_missing_half_units_does_not_raise(self, monkeypatch):
        """coder 2 缺一半单元：不报错，且库/回退两条路径结果一致。"""
        units = {
            1: {1: 1, 2: 1}, 2: {1: 2, 2: 2}, 3: {1: 1, 2: 2},
            4: {1: 2}, 5: {1: 1}, 6: {1: 2},  # coder 2 缺 4/5/6
        }
        lib = rel.compute_alpha(units, "nominal")
        pure_val = _alpha(units, "nominal", monkeypatch, pure=True)
        assert isinstance(lib, float) or lib is None
        assert lib == pytest.approx(pure_val, abs=1e-9)
        # 该数据可算：可配对单元 3 个
        assert isinstance(lib, float)

    def test_missing_known_value(self, monkeypatch):
        """含缺失的可查表数据仍回到已知 α（0.691358 那份数据大量缺失）。"""
        units = _columns_to_units(TestKnownAlphaValues.DOC_NOMINAL)
        missing_count = 15 * 3 - sum(len(u) for u in units.values())
        assert missing_count > 0  # 确实有缺失
        got = _alpha(units, "nominal", monkeypatch)
        assert got == pytest.approx(0.691358, abs=0.01)

    def test_none_value_treated_as_missing(self, monkeypatch):
        units = {1: {1: "Y", 2: "Y"}, 2: {1: "N", 2: None}}
        # 等价于 2 个可配对单元且完全一致 → 1.0
        assert _alpha(units, "nominal", monkeypatch) == 1.0

    def test_single_dirty_value_becomes_missing(self, monkeypatch):
        """dict 等结构化脏值按缺失跳过（不变成假的第三类别）。"""
        units = {
            1: {1: "Y", 2: "Y"},
            2: {1: "Y", 2: "N"},
            3: {1: {"bad": "obj"}, 2: "N"},   # coder 1 脏值 → 缺失 → 该单元只剩 1 人，跳过
            4: {1: "N", 2: "N"},
        }
        # 可配对单元 (Y,Y),(Y,N),(N,N)：o_YY=2, o_NN=2, o_YN=1, o_NY=1
        # n_v=[3,3]，α = 1 − 5·2/18 = 0.4444
        got = _alpha(units, "nominal", monkeypatch)
        assert got == pytest.approx(0.4444, abs=0.01)


# ============================================
# ⑤ 不可计算 → None
# ============================================
class TestNotComputable:
    def test_single_coder_returns_none(self, monkeypatch):
        units = {1: {1: "Y"}, 2: {1: "N"}, 3: {1: "Y"}}
        assert _alpha(units, "nominal", monkeypatch) is None

    def test_disjoint_coders_return_none(self, monkeypatch):
        """两人但无任何共同标注单元（无可配对单元）。"""
        units = {1: {1: "Y"}, 2: {2: "Y"}, 3: {1: "N"}, 4: {2: "N"}}
        assert _alpha(units, "nominal", monkeypatch) is None

    def test_empty_units(self, monkeypatch):
        assert rel.compute_alpha({}, "nominal") is None

    def test_non_dict_units_return_none(self):
        """R4 1d：units 非 dict（None/list/串）→ None 而不是 AttributeError。"""
        for bad in (None, [], "Y", [1, 2]):
            assert rel.compute_alpha(bad, "nominal") is None  # type: ignore[arg-type]

    def test_non_dict_inner_values_treated_missing(self):
        """R4 2：内层不是 dict（脏结构）→ 整个单元按缺失，不抛 AttributeError。"""
        assert rel.compute_alpha({1: "Y", 2: "N"}, "nominal") is None
        assert rel.compute_alpha({1: ["Y"], 2: {"a": "Y"}}, "nominal") is None

    def test_all_values_missing(self, monkeypatch):
        units = {1: {1: None, 2: None}, 2: {1: None}}
        assert rel.compute_alpha(units, "nominal") is None

    def test_single_unit_two_coders_still_computable(self, monkeypatch):
        """只有一个重叠单元也可算（恰好完全一致 → 1.0）。"""
        units = {1: {1: "Y", 2: "Y"}}
        assert _alpha(units, "nominal", monkeypatch) == 1.0

    def test_bad_task_value_type_does_not_crash(self, monkeypatch):
        """未知 value_type 默认 nominal，不抛异常。"""
        units = TestKnownAlphaValues.UNITS_A
        got = _alpha(units, "interval-ish", monkeypatch)
        assert got == pytest.approx(0.125, abs=0.01)


# ============================================
# R2 独立复核：精确算术参照的回归锚点（docs/dev/reviews/review_R2.md）
# ============================================
class TestR2IndependentVerification:
    """R2 数据正确性 review 的独立复核结论固化。

    参照实现（review 脚本，Fraction 精确算术、直接从 units 出发、不经
    _units_to_matrix 数值化）按 Krippendorff (2011) 一般公式独立重算：
    o_ck（c≠k）= m_c·m_k/(n_u−1)、o_cc = m_c(m_c−1)/(n_u−1)；
    α = 1 − (n−1)·Σ_{c≠k} o_ck δ_ck / Σ_{c≠k} n_c n_k δ_ck；
    ordinal δ² 按秩次 (Σ_{g=i..k} n_g − (n_i+n_k)/2)²。
    随机差分 200 组（2-5 人 × 3-12 单元、30% 缺失、nominal/ordinal 混合）
    与库路径/回退路径最大偏差 4e-16。本类固化可手算的精确锚点（分数写在
    断言旁），容差 1e-9（此前套件为 0.01）。
    """

    def _both_paths(self, units, value_type, monkeypatch):
        lib = rel.compute_alpha(units, value_type)
        pure = _alpha(units, value_type, monkeypatch, pure=True)
        return lib, pure

    def test_anchor_hand_derived_cases(self, monkeypatch):
        # 手推（巧合矩阵见注释）：
        # A: 2人4单元 (a,a)(a,b)(b,a)(b,b) → o=[[2,2],[2,2]] n_v=[4,4] n=8
        #    α = 1 − 7·4/32 = 1/8
        units_a = {
            1: {1: "a", 2: "a"}, 2: {1: "a", 2: "b"},
            3: {1: "b", 2: "a"}, 4: {1: "b", 2: "b"},
        }
        # B: 2人9单元（分歧全相邻秩）o=[[4,2,0],[2,2,2],[0,2,4]] n_v=[6,6,6] n=18
        #    nominal α = 1 − 17·8/216 = 10/27；ordinal（d12=d23=36, d13=144）
        #    α = 1 − 17·288/15552 = 37/54
        units_b = {
            1: {1: 1, 2: 2}, 2: {1: 2, 2: 3}, 3: {1: 3, 2: 2},
            4: {1: 2, 2: 1}, 5: {1: 1, 2: 1}, 6: {1: 2, 2: 2},
            7: {1: 3, 2: 3}, 8: {1: 1, 2: 1}, 9: {1: 3, 2: 3},
        }
        cases = [
            (units_a, "nominal", 0.125),                 # = 1/8
            (units_b, "nominal", 10 / 27),               # ≈ 0.37037037037037035
            (units_b, "ordinal", 37 / 54),               # ≈ 0.6851851851851852
        ]
        for units, vt, exact in cases:
            lib, pure = self._both_paths(units, vt, monkeypatch)
            assert lib == pytest.approx(exact, abs=1e-9), (vt, exact)
            assert pure == pytest.approx(exact, abs=1e-9), (vt, exact)

    def test_anchor_multi_coder_2_vs_4(self, monkeypatch):
        # 4人3单元：unit1 (1,1,2,2) → o11+=2/3 o22+=2/3 o12+=4/3 o21+=4/3；
        # unit2 (1,2,1,2) 同；unit3 (2,2,2,2) → o22+=4
        # o=[[4/3,8/3],[8/3,16/3]] n_v=[4,8] n=12 → α = 1 − (16/3)·11/64 = 1/12
        units_4 = {
            1: {1: 1, 2: 1, 3: 2, 4: 2},
            2: {1: 1, 2: 2, 3: 1, 4: 2},
            3: {1: 2, 2: 2, 3: 2, 4: 2},
        }
        # 2人3单元（4人数据的两人子集）：o=[[2,1],[1,2]] n_v=[3,3] n=6
        # → α = 1 − 2·5/18 = 4/9
        units_2 = {1: {1: 1, 2: 1}, 2: {1: 1, 2: 2}, 3: {1: 2, 2: 2}}
        lib, pure = self._both_paths(units_4, "nominal", monkeypatch)
        assert lib == pytest.approx(1 / 12, abs=1e-9)
        assert pure == pytest.approx(1 / 12, abs=1e-9)
        lib, pure = self._both_paths(units_2, "nominal", monkeypatch)
        assert lib == pytest.approx(4 / 9, abs=1e-9)
        assert pure == pytest.approx(4 / 9, abs=1e-9)

    def test_anchor_disagreement_lower_bound(self, monkeypatch):
        # 全不一致：2人×4单元全 (a,b) → o=[[0,4],[4,0]] n_v=[4,4] n=8
        # α = 1 − 8·7/32 = −3/4（完全不一致的下限方向）
        units = {u: {1: "a", 2: "b"} for u in range(1, 5)}
        lib, pure = self._both_paths(units, "nominal", monkeypatch)
        assert lib == pytest.approx(-0.75, abs=1e-9)
        assert pure == pytest.approx(-0.75, abs=1e-9)
        # 三类轮转 (1,2)(2,3)(3,1) → o 全非对角=1，n_v=[2,2,2] n=6 → α = −1/4
        rot = {1: {1: 1, 2: 2}, 2: {1: 2, 2: 3}, 3: {1: 3, 2: 1}}
        lib, pure = self._both_paths(rot, "nominal", monkeypatch)
        assert lib == pytest.approx(-0.25, abs=1e-9)
        assert pure == pytest.approx(-0.25, abs=1e-9)
        # 单对不一致（N=1）→ α = 0
        assert rel.compute_alpha({1: {1: "a", 2: "b"}}, "nominal") == 0.0

    def test_anchor_classic_table_exact(self, monkeypatch):
        # Krippendorff 原文 p.8 / 库 doctest 数据 → 精确分数（Fraction 参照核对）
        units_nom = _columns_to_units(TestKnownAlphaValues.DOC_NOMINAL)
        lib, pure = self._both_paths(units_nom, "nominal", monkeypatch)
        assert lib == pytest.approx(56 / 81, abs=1e-9)          # 0.691358024691358
        assert pure == pytest.approx(56 / 81, abs=1e-9)
        units_ord = _columns_to_units(TestKnownAlphaValues.DOC_ORDINAL)
        lib, pure = self._both_paths(units_ord, "ordinal", monkeypatch)
        assert lib == pytest.approx(108577 / 133160, abs=1e-9)  # 0.8153875037548813
        assert pure == pytest.approx(108577 / 133160, abs=1e-9)

    def test_ordinal_rank_based_not_interval(self, monkeypatch):
        """ordinal 用秩次距离而非数值间距：等距 {0,1,2} 与不等距 {0,10,1000} 同 α。"""
        eq = {
            1: {1: 0, 2: 1}, 2: {1: 1, 2: 2}, 3: {1: 2, 2: 0},
            4: {1: 0, 2: 0}, 5: {1: 1, 2: 1}, 6: {1: 2, 2: 2},
        }
        uneq = {
            1: {1: 0, 2: 10}, 2: {1: 10, 2: 1000}, 3: {1: 1000, 2: 0},
            4: {1: 0, 2: 0}, 5: {1: 10, 2: 10}, 6: {1: 1000, 2: 1000},
        }
        lib_eq, pure_eq = self._both_paths(eq, "ordinal", monkeypatch)
        lib_uneq, pure_uneq = self._both_paths(uneq, "ordinal", monkeypatch)
        assert lib_eq == pytest.approx(0.3125, abs=1e-9)
        assert lib_eq == pytest.approx(lib_uneq, abs=1e-12)  # 秩次语义：间距无关
        assert pure_eq == pytest.approx(pure_uneq, abs=1e-12)

    def test_nan_string_treated_as_missing(self, monkeypatch):
        """R2 修复回归：字符串 'nan' 按缺失（库/回退两路径同结果）。

        修复前：库路径把数值化后的 nan 当缺失（→1.0），纯 Python 回退把它当
        类别（→0.625），两路径分叉（docs/dev/reviews/review_R2.md F1）。
        """
        units = {1: {1: 1, 2: "nan"}, 2: {1: 1, 2: 1}, 3: {1: 2, 2: 2}}
        lib, pure = self._both_paths(units, "nominal", monkeypatch)
        assert lib == pure == 1.0
        # 不变成假的第三类别：'nan' 缺失后剩余可配对单元全一致 → 1.0
        units2 = {1: {1: "Y", 2: "nan"}, 2: {1: "Y", 2: "Y"}, 3: {1: "N", 2: "N"}}
        lib, pure = self._both_paths(units2, "nominal", monkeypatch)
        assert lib == pure == 1.0
        # 各种拼写（float() 可解析出 NaN 的串）与 "NaN" 在 ordinal 下同样缺失
        for spelling in ("nan", "NaN", "NAN", " nan "):
            units3 = {1: {1: 1, 2: spelling}, 2: {1: 1, 2: 1}, 3: {1: 2, 2: 2}}
            assert rel.compute_alpha(units3, "ordinal") == 1.0, spelling

    def test_huge_int_label_does_not_crash(self, monkeypatch):
        """R2 修复回归：float() 装不下的超大 int 按标签码处理，不炸引擎。"""
        units = {1: {1: 1, 2: 10 ** 400}, 2: {1: 1, 2: 10 ** 400}, 3: {1: 2, 2: 2}}
        lib, pure = self._both_paths(units, "nominal", monkeypatch)
        # 标签码分支：三类 {1, 10**400, 2}；unit1/2 是 (1, 10**400) 分歧对（各贡献
        # o_01=o_10=1），unit3 是 (2,2)。o=[[0,2,0],[2,0,0],[0,0,2]] n_v=[2,2,2] n=6
        # → α = 1 − 4·5/24 = 1/6
        assert lib == pytest.approx(1 / 6, abs=1e-9)
        assert pure == pytest.approx(1 / 6, abs=1e-9)
        # 与真分歧数据混合也不崩：10**400 与 1 不同类
        units2 = {1: {1: 1, 2: 10 ** 400}, 2: {1: 2, 2: 1}}
        lib, pure = self._both_paths(units2, "nominal", monkeypatch)
        assert isinstance(lib, float) and lib == pytest.approx(pure, abs=1e-9)


# ============================================
# run_reliability：数据库路径（假游标，按 SQL 文本分派）
# ============================================
class _FakeCtx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class FakeRelCursor:
    """按 SQL 文本分派的假游标：DDL 空转、SELECT 返回种子行、INSERT 捕获参数。"""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []          # [(sql, params)]
        self.insert_params = None
        self.lastrowid = 4242

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "FROM annotation_submissions" in sql:
            category, task_type = params
            self._result = [
                r for r in self.rows
                if r["category"] == category and r["task_type"] == task_type
            ]
        elif "INSERT INTO reliability_runs" in sql:
            self.insert_params = params
            self._result = []
        else:
            self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _submission(sense_id, coder_id, payload, category="motion", task_type="admission"):
    return {
        "id": 0,  # 假游标场景 id 不参与逻辑
        "sense_id": sense_id,
        "coder_id": coder_id,
        "payload": payload,
        "status": "submitted",
        "category": category,
        "task_type": task_type,
    }


def _patch_cursor(monkeypatch, rows):
    cursor = FakeRelCursor(rows)
    monkeypatch.setattr(
        rel, "get_db_cursor", lambda autocommit=True: _FakeCtx(cursor)
    )
    return cursor


class TestRunReliabilityAdmission:
    """admission 任务：admission/schema/alignment 三字段各算 nominal α。"""

    ROWS = [
        # coder 1
        _submission(101, 1, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
        _submission(102, 1, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
        _submission(103, 1, {"admission": "N", "schema": "SOURCE_PATH", "alignment": "B"}),
        _submission(104, 1, {"admission": "Y", "schema": "SOURCE_GOAL", "alignment": "A"}),
        # coder 2（仅 104 的 admission 有分歧）
        _submission(101, 2, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
        _submission(102, 2, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
        _submission(103, 2, {"admission": "N", "schema": "SOURCE_PATH", "alignment": "B"}),
        _submission(104, 2, {"admission": "N", "schema": "SOURCE_GOAL", "alignment": "A"}),
    ]

    def test_per_feature_and_overall(self, monkeypatch):
        cursor = _patch_cursor(monkeypatch, self.ROWS)
        result = rel.run_reliability("motion", "admission")

        # admission 字段：(Y,Y),(Y,Y),(N,N),(Y,N) → 3 一致 1 分歧
        # o_YY=4, o_NN=2, o_YN=1, o_NY=1；n_v=[5,3]，α = 1 − 7·2/30 = 0.5333
        assert result["per_feature"]["admission"] == pytest.approx(0.5333, abs=0.01)
        # schema / alignment 完全一致 → 1.0
        assert result["per_feature"]["schema"] == 1.0
        assert result["per_feature"]["alignment"] == 1.0
        # overall = 三字段均值
        expected_overall = (0.53333 + 1.0 + 1.0) / 3
        assert result["overall_alpha"] == pytest.approx(expected_overall, abs=0.01)
        assert result["n_coders"] == 2
        assert result["n_units"] == 4

        # 结果落库（先幂等建表再 INSERT，DDL/参数可查）
        executed_sql = "\n".join(sql for sql, _ in cursor.executed)
        assert "CREATE TABLE IF NOT EXISTS reliability_runs" in executed_sql
        assert "status = 'submitted'" in executed_sql
        assert cursor.insert_params is not None
        assert cursor.insert_params[0] == "motion"
        assert cursor.insert_params[1] == "admission"
        assert cursor.insert_params[2] == 2      # n_coders
        assert cursor.insert_params[3] == 4      # n_units
        assert cursor.insert_params[4] == pytest.approx(0.844, abs=0.002)
        per_feature_stored = json.loads(cursor.insert_params[5])
        assert set(per_feature_stored) == {"admission", "schema", "alignment"}

        # 分歧条目：只有 104 的 admission
        assert len(result["disagreements"]) == 1
        entry = result["disagreements"][0]
        assert entry["sense_id"] == 104
        assert entry["field"] == "admission"
        assert entry["values"] == {"1": "Y", "2": "N"}

    def test_payload_as_json_string(self, monkeypatch):
        """PyMySQL 对 JSON 列可能返回字符串，payload str/dict 都要能解析。"""
        rows = [
            _submission(201, 1, json.dumps({"admission": "Y"})),
            _submission(201, 2, {"admission": "Y"}),
        ]
        _patch_cursor(monkeypatch, rows)
        result = rel.run_reliability("motion", "admission")
        assert result["per_feature"]["admission"] == 1.0
        assert result["disagreements"] == []

    def test_single_coder_still_writes_run(self, monkeypatch):
        """单人提交：α 不可算（None）但计算运行仍落库留痕。"""
        rows = [_submission(301, 1, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"})]
        cursor = _patch_cursor(monkeypatch, rows)
        result = rel.run_reliability("motion", "admission")
        assert result["n_coders"] == 1
        assert result["n_units"] == 1
        assert result["overall_alpha"] is None
        assert all(v is None for v in result["per_feature"].values())
        assert cursor.insert_params is not None
        assert cursor.insert_params[4] is None  # DECIMAL(5,3) NULL


class TestRunReliabilityFeatureCoding:
    """feature_coding 任务：逐特征按 features_meta 的 value_type 算。"""

    ROWS = [
        _submission(201, 1, {"features": {"P1": 1, "P5": 1}}, task_type="feature_coding"),
        _submission(202, 1, {"features": {"P1": 0, "P5": 2}}, task_type="feature_coding"),
        _submission(203, 1, {"features": {"P1": 1, "P5": 3}}, task_type="feature_coding"),
        _submission(201, 2, {"features": {"P1": 1, "P5": 2}}, task_type="feature_coding"),
        _submission(202, 2, {"features": {"P1": 0, "P5": 2}}, task_type="feature_coding"),
        _submission(203, 2, {"features": {"P1": 0, "P5": 3}}, task_type="feature_coding"),
    ]

    # 手算：P1 (binary→nominal)：(1,1),(0,0),(1,0) → α = 1 − 5·2/18 = 0.4444
    # P5 (ordinal)：(1,2),(2,2),(3,3)，n_v=[1,3,2] → α = 1 − 5·8/180 = 0.7778
    # P5 若误按 nominal：α = 1 − 5·2/22 = 0.5455（分支各异的反例值）
    FEATURES_META = [
        {"code": "P1", "name": "源点凸显", "value_type": "binary"},
        {"code": "P5", "name": "速度", "value_type": "ordinal"},
    ]

    def test_value_type_respected(self, monkeypatch):
        _patch_cursor(monkeypatch, self.ROWS)
        result = rel.run_reliability("motion", "feature_coding", self.FEATURES_META)
        assert result["per_feature"]["P1"] == pytest.approx(0.4444, abs=0.01)
        assert result["per_feature"]["P5"] == pytest.approx(0.7778, abs=0.01)
        # ordinal 分支确实生效（≠ nominal 会得到的 0.5455）
        assert result["per_feature"]["P5"] != pytest.approx(0.5455, abs=0.01)
        expected_overall = (0.44444 + 0.77778) / 2
        assert result["overall_alpha"] == pytest.approx(expected_overall, abs=0.01)

    def test_missing_meta_defaults_nominal(self, monkeypatch):
        """features_meta 为空（configs/motion/features.yaml 不存在的情形）→ 默认 nominal。"""
        _patch_cursor(monkeypatch, self.ROWS)
        result = rel.run_reliability("motion", "feature_coding", [])
        assert result["per_feature"]["P5"] == pytest.approx(0.5455, abs=0.01)
        assert result["per_feature"]["P1"] == pytest.approx(0.4444, abs=0.01)

    def test_features_meta_auto_loaded_when_none(self, monkeypatch, tmp_path):
        """features_meta=None 时自动读 configs/{category}/features.yaml。"""
        cfg_dir = tmp_path / "configs" / "cats_x"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "features.yaml").write_text(
            "features:\n"
            "  - {code: P1, name: 源点凸显, value_type: binary}\n"
            "  - {code: P5, name: 速度, value_type: ordinal}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(rel, "_REPO_ROOT", str(tmp_path))
        meta = rel._load_features_meta("cats_x")
        assert rel._resolve_value_type(meta, "P1") == "nominal"   # binary → nominal
        assert rel._resolve_value_type(meta, "P5") == "ordinal"
        assert rel._resolve_value_type(meta, "ZZ") == "nominal"   # 未登记 → 默认

        rows = [dict(r, category="cats_x") for r in self.ROWS]
        _patch_cursor(monkeypatch, rows)
        result = rel.run_reliability("cats_x", "feature_coding", None)
        assert result["per_feature"]["P5"] == pytest.approx(0.7778, abs=0.01)

    def test_coder_without_feature_is_missing(self, monkeypatch):
        """某 coder 的 payload 缺某特征 → 该 (unit, coder) 缺失，不报错。"""
        rows = [
            _submission(201, 1, {"features": {"P1": 1}}, task_type="feature_coding"),
            _submission(201, 2, {"features": {"P1": 1}}, task_type="feature_coding"),
            _submission(202, 2, {"features": {"P1": 0}}, task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, rows)
        result = rel.run_reliability("motion", "feature_coding", self.FEATURES_META)
        assert result["per_feature"]["P1"] == 1.0  # 唯一可配对单元完全一致
        assert result["per_feature"].get("P5") is None  # P5 无数据 → 不可算
        assert result["overall_alpha"] == 1.0  # 均值跳过 None

    def test_large_feature_set_1000(self, monkeypatch):
        """R4 2：大 payload（1000 特征）逐指标算 α 不炸；999 个一致 + 1 个分歧。"""
        features = {f"P{i}": i % 2 for i in range(1000)}
        rows = [
            _submission(201, 1, {"features": features}, task_type="feature_coding"),
            _submission(201, 2, {"features": dict(features, P0=1)},
                        task_type="feature_coding"),
        ]
        _patch_cursor(monkeypatch, rows)
        result = rel.run_reliability("motion", "feature_coding", self.FEATURES_META)
        assert len(result["per_feature"]) == 1000
        # 唯一分歧特征 P0：单对 (0,1) → α = 0；其余 999 个完全一致 → 1.0
        assert result["per_feature"]["P0"] == pytest.approx(0.0, abs=1e-9)
        assert result["per_feature"]["P1"] == pytest.approx(1.0, abs=1e-9)
        assert result["overall_alpha"] == pytest.approx(999 / 1000, abs=1e-9)
        # 分歧条目只含 P0
        assert [d["field"] for d in result["disagreements"]] == ["P0"]


class TestRunReliabilityEdges:
    def test_no_submissions(self, monkeypatch):
        """无提交：零值结果、overall None、不写库（admission 的固定指标键仍列出，值为 None）。"""
        cursor = _patch_cursor(monkeypatch, [])
        result = rel.run_reliability("motion", "admission")
        assert result["n_coders"] == 0
        assert result["n_units"] == 0
        assert result["overall_alpha"] is None
        assert set(result["per_feature"]) == {"admission", "schema", "alignment"}
        assert all(v is None for v in result["per_feature"].values())
        assert result["disagreements"] == []
        assert cursor.insert_params is None  # 空跑不留垃圾行

    def test_db_unavailable_no_crash(self, monkeypatch):
        """数据库不可用：返回带 db_error 的结果而不是抛异常。"""
        import pymysql

        def boom(autocommit=True):
            raise pymysql.Error("connection refused")

        monkeypatch.setattr(rel, "get_db_cursor", boom)
        result = rel.run_reliability("motion", "admission")
        assert result["overall_alpha"] is None
        assert "db_error" in result

    def test_unknown_task_type_raises(self):
        with pytest.raises(ValueError):
            rel.run_reliability("motion", "not_a_task")

    def test_alignment_task_single_field(self, monkeypatch):
        """alignment 作为独立 task_type：比对 payload 的 alignment 字段。"""
        rows = [
            _submission(401, 1, {"alignment": "A"}, task_type="alignment"),
            _submission(401, 2, {"alignment": "B"}, task_type="alignment"),
            _submission(402, 1, {"alignment": "A"}, task_type="alignment"),
            _submission(402, 2, {"alignment": "A"}, task_type="alignment"),
        ]
        _patch_cursor(monkeypatch, rows)
        result = rel.run_reliability("motion", "alignment")
        assert set(result["per_feature"]) == {"alignment"}
        # (A,B),(A,A)：o_AA=2, o_AB=1, o_BA=1；n_v=[3,1]，α = 1 − 3·2/(2·3·1) = 0.0
        assert result["per_feature"]["alignment"] == pytest.approx(0.0, abs=0.01)


class TestReliabilityRunsDDL:
    """落库表结构必须与规范 §2 的 DDL 原样一致（关键行抽查）。"""

    def test_key_lines(self):
        ddl = rel.RELIABILITY_RUNS_DDL
        assert "CREATE TABLE IF NOT EXISTS reliability_runs" in ddl
        assert "overall_alpha DECIMAL(5,3) NULL" in ddl
        assert "per_feature JSON NULL" in ddl
        assert "disagreements JSON NULL" in ddl
        assert "computed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl
        assert "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" in ddl


# ============================================
# 页面辅助（不依赖 Streamlit 运行时的纯函数部分）
# ============================================
class TestPageHelpers:
    def test_iaa_caption_constant(self):
        assert "AI-assisted IAA" in rel.IAA_CAPTION
        assert "AI 草稿" in rel.IAA_CAPTION

    def test_export_csv_sections(self):
        result = {
            "category": "motion",
            "task_type": "admission",
            "n_coders": 2,
            "n_units": 4,
            "overall_alpha": 0.844444,
            "per_feature": {"admission": 0.533333, "schema": 1.0, "alignment": 1.0},
            "disagreements": [
                {"sense_id": 104, "field": "admission", "values": {"1": "Y", "2": "N"}}
            ],
        }
        text = rel._export_csv(result).decode("utf-8-sig")
        assert "AI-assisted IAA" in text
        assert "overall_alpha" in text
        assert "admission,0.533" in text
        assert "104,admission,2,N" in text

    def test_list_categories_fallback(self, tmp_path, monkeypatch):
        """category_pack 不可用时回退扫 configs/ 子目录。

        Agent D 交付 src/category_pack.py 后，主路径恒可用；为保留本测试原意
        （验证 ImportError 回退分支），向 sys.modules 注入 None 强制
        `from src.category_pack import CATEGORIES` 抛 ImportError。
        """
        monkeypatch.setattr(rel, "_REPO_ROOT", str(tmp_path))
        monkeypatch.setitem(sys.modules, "src.category_pack", None)  # 触发 ImportError
        (tmp_path / "configs" / "motion").mkdir(parents=True)
        (tmp_path / "configs" / "_schema").mkdir(parents=True)  # _ 开头应被排除
        assert rel._list_categories() == ("motion",)

    def test_parse_payload_variants(self):
        """payload JSON 列解析（R4 消重后唯一实现在 annotation_flow.parse_payload）。"""
        assert rel.parse_payload({"a": 1}) == {"a": 1}
        assert rel.parse_payload('{"a": 1}') == {"a": 1}
        assert rel.parse_payload(b'{"a": 1}') == {"a": 1}   # bytes 变体
        assert rel.parse_payload("not json") == {}
        assert rel.parse_payload(None) == {}
        assert rel.parse_payload("[1, 2]") == {}            # 非 dict → {}
