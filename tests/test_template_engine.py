"""释义模板引擎测试（论文 §6：母图式提炼 + 槽位实例化 + 批量导出）。

分层覆盖（与 test_category_study 同口径）：
  1. 纯函数层（主体）：合成簇特征矩阵，不碰数据库 ——
     a) 均值阈值划核心/槽位正确（含 0.5 边界、全 0 剔除、A 组不进图式）；
     b) 实例化模板四维字段齐全、中文标签来自 features.yaml 配置；
     c) 导出 CSV 单元格防公式注入（= 开头被前置单引号）。
  2. 配置桥接：cs 范畴代号（RUN）→ configs 范畴包（motion）的解析。
  3. MySQL 路径：真实 RUN 数据抽验（run-S1 对照论文样例），无库则 skip。
  4. 批次 10 R-1 收口（拼装表外置进范畴包 template_assembly 节）：
     speech 拼装节渲染言说动词口径词面 / 缺节 fail-closed（不回退
     motion）/ motion 整句逐字护栏（收口前后渲染逐字相同）。
"""

import csv
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import template_engine as te  # noqa: E402
from src.category_pack import load_pack  # noqa: E402


# ============================================
# 合成数据（特征编码 = motion 包 18 列）
# ============================================

@pytest.fixture(scope="module")
def feature_meta():
    """真实 motion 范畴包的特征元数据（label/values 断言的参照系）。"""
    return te._feature_meta(load_pack("motion"))


def mkvector(**overrides):
    """全 0 基线向量 + 覆盖项（键 = 特征编码）。"""
    base = {code: 0 for code in
            ["P1", "P2", "P3", "P4", "P5",
             "M1a", "M1b", "M1c", "M1d", "M2",
             "M3a", "M3b", "M3c", "M3d", "C1", "A1", "A2", "A3"]}
    base.update(overrides)
    return base


def members_of(*vectors):
    return [{"features": v} for v in vectors]


def meta_of(vectors, cluster_no=1, name="合成簇"):
    return {"cluster_id": 100 + cluster_no, "cluster_no": cluster_no,
            "cluster_name": name, "size": len(vectors),
            "members": [{"sense_id": i, "lemma": f"w{i}", "sense_no": str(i),
                         "sense_label": f"义{i}"} for i, _ in enumerate(vectors)]}


# ============================================
# a) 母图式提炼：均值阈值划核心 / 槽位
# ============================================

class TestDeriveCoreSlotSplit:
    def test_binary_mean_ge_threshold_is_core(self, feature_meta):
        """4 成员全部 M1a=1 → 均值 1.0 ≥ 0.5 → 共享要素。"""
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(mkvector(M1a=1), mkvector(M1a=1),
                               mkvector(M1a=1), mkvector(M1a=1))),
            [mkvector(M1a=1)] * 4, feature_meta)
        assert schema["schema_core"]["M1a"] == 1.0
        assert [f["code"] for f in schema["core_features"]] == ["M1a"]
        assert schema["core_features"][0]["label"] == "主体-人"

    def test_binary_mean_half_threshold_is_core(self, feature_meta):
        """均值恰为 0.5（2/4）→ 边界归共享要素（任务口径 ≥ 0.5）。"""
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(mkvector(M1a=1), mkvector(M1a=1),
                               mkvector(), mkvector())),
            [mkvector(M1a=1), mkvector(M1a=1), mkvector(), mkvector()],
            feature_meta)
        assert schema["schema_core"]["M1a"] == 0.5

    def test_binary_mean_below_threshold_is_slot(self, feature_meta):
        """均值 0.25 ∈ (0, 0.5) → 可变槽位，附取值分布（计数+占比）。"""
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(mkvector(M1b=1), mkvector(), mkvector(),
                               mkvector())),
            [mkvector(M1b=1), mkvector(), mkvector(), mkvector()], feature_meta)
        assert "M1b" not in schema["schema_core"]
        slots = {s["code"]: s for s in schema["variable_slots"]}
        assert "M1b" in slots
        dist = {d["value"]: d for d in slots["M1b"]["distribution"]}
        # 分布按计数降序：非动物主体 3/4、动物主体 1/4；标签来自 features.yaml
        assert dist[0]["label"] == "非动物主体" and dist[0]["count"] == 3
        assert dist[0]["ratio"] == pytest.approx(0.75)
        assert dist[1]["label"] == "动物主体" and dist[1]["ratio"] == pytest.approx(0.25)
        assert slots["M1b"]["label"] == "主体-动物"

    def test_ordinal_shared_value_is_core_split_is_slot(self, feature_meta):
        """序数特征：簇内同值（P5 全 2）→ 共享要素记该值；分歧（C1 混合）→ 槽位。"""
        vecs = [mkvector(P5=2, C1=2), mkvector(P5=2, C1=2),
                mkvector(P5=2, C1=1), mkvector(P5=2, C1=0)]
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs)), vecs, feature_meta)
        assert schema["schema_core"]["P5"] == 2.0
        p5 = next(f for f in schema["core_features"] if f["code"] == "P5")
        assert p5["value_label"] == "高"
        assert "C1" not in schema["schema_core"]
        assert {s["code"] for s in schema["variable_slots"]} == {"C1"}

    def test_all_zero_features_absent_from_template(self, feature_meta):
        """全簇全 0 的特征与本簇无关：既不进核心也不进槽位。"""
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(mkvector(M1a=1), mkvector(M1a=1))),
            [mkvector(M1a=1), mkvector(M1a=1)], feature_meta)
        codes = set(schema["schema_core"]) | {
            s["code"] for s in schema["variable_slots"]}
        assert "P1" not in codes and "M3b" not in codes
        assert schema["schema_core"] == {"M1a": 1.0}

    def test_verification_features_stay_out_of_schema(self, feature_meta):
        """A 组核验特征属句法维度：即使全簇 A1=1 也不进图式核心/槽位。"""
        vecs = [mkvector(A1=1, M3a=1), mkvector(A1=1, M3a=1),
                mkvector(A1=1, M3a=1), mkvector(A1=1, M3a=1)]
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs)), vecs, feature_meta)
        assert "A1" not in schema["schema_core"]
        assert {s["code"] for s in schema["variable_slots"]} == set()
        assert schema["schema_core"] == {"M3a": 1.0}

    def test_empty_cluster_yields_blank_draft(self, feature_meta):
        schema = te.derive_cluster_schema_from_members(
            meta_of([]), [], feature_meta)
        assert schema["schema_core"] == {}
        assert schema["variable_slots"] == []
        assert schema["members"] == []


class TestDeriveSchemaMapping:
    def test_p1_cluster_maps_to_source_detach(self, feature_meta):
        """P1 均值 ≥ 0.5 → 源点脱离图式（schemas.yaml 名称与定义）。"""
        vecs = [mkvector(P1=1, C1=1)] * 3 + [mkvector(P1=0, C1=1)]
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs), name="逃离脱离类"), vecs, feature_meta,
            schema_defs=load_pack("motion")["schemas"]["schemas"])
        assert schema["schema"]["code"] == "SOURCE_DETACH"
        assert schema["schema"]["name"] == "源点脱离图式"
        assert schema["schema"]["definition"]
        assert schema["schema_source"] == "feature_map"

    def test_p2_cluster_maps_to_goal_arrive(self, feature_meta):
        vecs = [mkvector(P2=1, P3=1)] * 4
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs)), vecs, feature_meta,
            schema_defs=load_pack("motion")["schemas"]["schemas"])
        assert schema["schema"]["code"] == "GOAL_ARRIVE"

    def test_chase_tag_majority_maps_to_interact(self, feature_meta):
        """追逐标注过半 → 互动位移图式（优先级高于路径特征）。"""
        vecs = [mkvector(P2=1), mkvector(P2=1), mkvector(P2=1), mkvector(P2=1)]
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs)), vecs, feature_meta,
            tags=["追逐", "追逐", "追逐", None],
            schema_defs=load_pack("motion")["schemas"]["schemas"])
        assert schema["schema"]["code"] == "INTERACT_MOVE"

    def test_no_path_prominence_maps_to_manner(self, feature_meta):
        vecs = [mkvector(M1a=1, M3a=1)] * 4
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs)), vecs, feature_meta,
            schema_defs=load_pack("motion")["schemas"]["schemas"])
        assert schema["schema"]["code"] == "MANNER_ACCOMP"

    def test_no_schema_defs_falls_back_to_none(self, feature_meta):
        vecs = [mkvector()] * 2
        schema = te.derive_cluster_schema_from_members(
            meta_of(members_of(*vecs)), vecs, feature_meta, schema_defs=[])
        assert schema["schema"] is None
        assert schema["schema_source"] == "none"


# ============================================
# b) 槽位实例化：四维字段齐全，中文标签来自配置
# ============================================

RUN_S1_DEFINITION = "[intransitive]to move using your legs, " \
    "going faster than when you walk"


def _synthetic_run_s1_vector():
    """run·足部奔跑义 的真实编码锚点（tests/test_category_study.py 抽查值）。"""
    return mkvector(M1a=1, M1b=1, M2=1, M3a=1, C1=2, A1=1)


def _synthetic_cluster_schema(feature_meta, vectors):
    return te.derive_cluster_schema_from_members(
        meta_of([{"features": v} for v in vectors]),
        vectors, feature_meta,
        schema_defs=load_pack("motion")["schemas"]["schemas"])


class TestBuildTemplate:
    def _build(self, feature_meta, **sense_overrides):
        vecs = [_synthetic_run_s1_vector(), mkvector(M1a=1, M3a=1),
                mkvector(M1a=1, M3a=1), mkvector(M1a=1, M3a=1)]
        cluster_schema = _synthetic_cluster_schema(feature_meta, vecs)
        sense_row = {
            "sense_id": 1, "lemma": "run", "sense_no": "1",
            "sense_label": "足部奔跑义", "language": "en", "status": "目标",
            "tag": None, "register": None, "subject_type": None,
            "source_dict": "OALD10", "definition": RUN_S1_DEFINITION,
        }
        sense_row.update(sense_overrides)
        return te.build_template(sense_row, _synthetic_run_s1_vector(),
                                 cluster_schema, feature_meta)

    def test_four_dimensions_present(self, feature_meta):
        tpl = self._build(feature_meta)
        for key in ("图式维度", "语义参数维度", "句法维度", "对齐预留维度"):
            assert key in tpl, f"缺四维结构之一: {key}"
        assert tpl["图式维度"]["name"] == "方式伴随图式"
        assert tpl["图式维度"]["definition"] == "位移过程伴随的运动方式是语义重心"
        assert tpl["对齐预留维度"]["filled"] is False

    def test_oald_definition_split_for_comparison(self, feature_meta):
        """OALD 原文一并返回：语法码剥到 grammar，释义正文干净。"""
        tpl = self._build(feature_meta)
        assert tpl["oald"]["source"] == "OALD10"
        assert tpl["oald"]["grammar"] == "intransitive"
        assert tpl["oald"]["definition"] == \
            "to move using your legs, going faster than when you walk"

    def test_semantic_params_labels_from_config(self, feature_meta):
        """15 项语义槽位逐条列出，label 与取值标签都来自 features.yaml。"""
        tpl = self._build(feature_meta)
        params = tpl["语义参数维度"]
        assert len(params) == 15  # motion 包 in_clustering 特征数
        by_code = {p["code"]: p for p in params}
        assert by_code["P1"]["label"] == "源点凸显"
        assert by_code["P1"]["value_label"] == "不凸显"
        assert by_code["M1a"]["value_label"] == "人主体"
        assert by_code["C1"]["value_label"] == "自主"
        assert by_code["M3a"]["value_label"] == "陆地介质"
        # 槽位角色来自母图式：簇共享 M1a/M3a 为核心，M2（分歧）为可变槽位
        assert by_code["M1a"]["role"] == "core"
        assert by_code["M3a"]["role"] == "core"
        assert by_code["M2"]["role"] == "variable"
        assert by_code["P2"]["role"] == "off"  # 全簇全 0，与本簇无关

    def test_syntactic_dimension_from_a_features(self, feature_meta):
        """句法维度 = A 组核验特征 + 及物性摘要（A1=1 → 不及物）。"""
        tpl = self._build(feature_meta)
        syn = tpl["句法维度"]
        assert syn["transitivity"] == "不及物"
        assert {f["code"] for f in syn["features"]} == {"A1", "A2", "A3"}
        a1 = next(f for f in syn["features"] if f["code"] == "A1")
        assert a1["label"] == "构式论元-不及物"
        assert a1["value_label"] == "有"

    def test_template_text_deterministic_slot_assembly(self, feature_meta):
        """模板文字确定性拼装：两次调用逐字符相同，且槽位清单来自母图式。"""
        tpl1 = self._build(feature_meta)
        tpl2 = self._build(feature_meta)
        assert tpl1["template_text"] == tpl2["template_text"]
        text = tpl1["template_text"]
        assert text.startswith("【图式：方式伴随图式】")
        assert "人/动物主体" in text          # M1a+M1b → 主体标签
        assert "陆地介质中移动" in text       # M3a → 介质短语
        assert "动因自主" in text             # C1 → 动因短语
        assert "[可变槽位: " in text
        assert "情态急促度=一般" in text      # 可变槽位 × 本义位取值

    def test_template_text_varies_with_vector(self, feature_meta):
        """换义位（flee 式 P1=1 受迫）文字随特征向量变化。"""
        vecs = [mkvector(P1=1, C1=1, M2=2, M3a=1)] * 4
        cluster_schema = _synthetic_cluster_schema(feature_meta, vecs)
        tpl = te.build_template(
            {"sense_id": 9, "lemma": "flee", "sense_no": "1",
             "sense_label": "逃离义", "language": "en", "status": "目标",
             "tag": None, "register": None, "subject_type": None,
             "source_dict": "OALD10", "definition": "[intransitive]to leave"},
            mkvector(P1=1, C1=1, M2=2, M3a=1), cluster_schema, feature_meta)
        text = tpl["template_text"]
        assert "【图式：源点脱离图式】" in text
        assert "自源点出发" in text
        assert "急促" in text
        assert "动因受迫" in text

    def test_subject_fallback_when_no_m1_feature(self, feature_meta):
        vecs = [mkvector(P5=2)] * 2
        cluster_schema = _synthetic_cluster_schema(feature_meta, vecs)
        tpl = te.build_template(
            {"sense_id": 2, "lemma": "x", "sense_no": "1", "sense_label": "义",
             "language": "en", "status": "目标", "tag": None, "register": None,
             "subject_type": None, "source_dict": "OALD10",
             "definition": "to move"},
            mkvector(P5=2), cluster_schema, feature_meta)
        assert "主体不限" in tpl["template_text"]
        assert "高速" in tpl["template_text"]

    def test_no_cluster_schema_still_renders(self, feature_meta):
        """无簇归属（剔除义位）也能出模板：图式名回退、槽位为空清单。"""
        tpl = te.build_template(
            {"sense_id": 3, "lemma": "跑", "sense_no": "③", "sense_label": "离位义",
             "language": "zh", "status": "剔除", "tag": None, "register": None,
             "subject_type": None, "source_dict": "现汉7",
             "definition": "离开原来的位置"},
            mkvector(), None, feature_meta)
        assert tpl["图式维度"]["name"] is None
        assert "[可变槽位: 无（全要素簇内共享）]" in tpl["template_text"]


# ============================================
# c) 批量导出：CSV 防公式注入 + 结构化 JSON
# ============================================

def _export_templates(feature_meta):
    """两条合成模板（其中一条释义原文以 = 开头，构造注入样本）。"""
    vecs = [_synthetic_run_s1_vector(), mkvector(M1a=1, M3a=1),
            mkvector(M1a=1, M3a=1), mkvector(M1a=1, M3a=1)]
    cluster_schema = _synthetic_cluster_schema(feature_meta, vecs)
    base = {"language": "en", "status": "目标", "tag": None, "register": None,
            "subject_type": None, "source_dict": "OALD10"}
    t1 = te.build_template(
        {**base, "sense_id": 1, "lemma": "run", "sense_no": "1",
         "sense_label": "足部奔跑义", "definition": RUN_S1_DEFINITION},
        _synthetic_run_s1_vector(), cluster_schema, feature_meta)
    t2 = te.build_template(
        {**base, "sense_id": 2, "lemma": "evil", "sense_no": "1",
         "sense_label": "恶意注入样本", "definition": "=cmd|' /C calc!A0"},
        mkvector(), cluster_schema, feature_meta)
    return [t1, t2]


class TestExport:
    def test_csv_first_cell_formula_injection_guarded(self, feature_meta):
        """以 = 开头的单元格被前置单引号（src/security.sanitize_csv_value）。"""
        csv_text = te.build_export_csv(_export_templates(feature_meta))
        rows = list(csv.reader(io.StringIO(csv_text)))
        assert rows[0] == te.TEMPLATE_CSV_COLUMNS
        target = rows[2][1]  # 注入样本位于第 2 数据行的 OALD 原文列
        assert target.startswith("'=")
        assert "cmd|' /C calc!A0" in target
        # 全表无任何未防护的公式触发首字符
        for row in rows[1:]:
            for cell in row:
                assert not str(cell).startswith("=")

    def test_csv_column_structure_follows_paper_table(self, feature_meta):
        """列结构 = 论文 §6.4 对照表：词条义位/OALD10原文/模板化释义/优化要点。"""
        csv_text = te.build_export_csv(_export_templates(feature_meta))
        rows = list(csv.reader(io.StringIO(csv_text)))
        assert rows[0][:3] == ["词条义位", "OALD10原文释义",
                               "LexiSchema模板化释义"]
        assert rows[0][-1] == "优化要点（编者填写）"
        assert len(rows) == 3  # 表头 + 2 条模板
        assert rows[1][0] == "run1（足部奔跑义）"
        assert rows[1][2].startswith("【图式：")

    def test_json_roundtrip_keeps_four_dimensions(self, feature_meta):
        payload = {"category": "RUN", "language": "en", "cluster": {"cluster_no": 4},
                   "templates": _export_templates(feature_meta)}
        data = json.loads(te.build_export_json(payload))
        assert data["category"] == "RUN"
        assert len(data["templates"]) == 2
        tpl = data["templates"][0]
        for key in ("图式维度", "语义参数维度", "句法维度", "对齐预留维度",
                    "template_text", "oald"):
            assert key in tpl
        assert "to move using your legs" in tpl["oald"]["definition"]


# ============================================
# 配置桥接：cs 范畴代号 → configs 范畴包
# ============================================

class TestResolvePack:
    def test_direct_pack_name(self):
        pack = te.resolve_pack("motion")
        assert pack["pack"]["category"] == "motion"

    def test_cs_category_code_resolves_by_observed_codes(self):
        """categories.code（RUN）≠ 包名（motion）：按义位实际编码列解析。"""
        pack = te.resolve_pack(
            "RUN", ["P1", "P2", "M1a", "M1b", "M2", "M3a", "C1", "A1"])
        assert pack["pack"]["category"] == "motion"
        codes = set(te._feature_meta(pack))
        assert {"P1", "M1a", "C1", "A1"} <= codes

    def test_no_candidate_pack_raises(self, monkeypatch):
        """扫描不到任何范畴包（configs/ 为空）时抛 CategoryPackError。"""
        from src import category_pack
        monkeypatch.setattr(category_pack, "CATEGORIES", lambda: ())
        with pytest.raises(category_pack.CategoryPackError):
            te.resolve_pack("__nonexistent__", ["X9"])


# ============================================
# d) 批次 10 R-1 收口：拼装表外置（template_assembly 节）
# ============================================

@pytest.fixture(scope="module")
def speech_meta():
    """speech 范畴包特征元数据（言说动词验证帧；R-1 收口后渲染词面参照系）。"""
    return te._feature_meta(load_pack("speech"))


def speech_vector(**overrides):
    """speech 全默认基线向量（S1 声道 = nominal 字符串值域原值）＋覆盖项。"""
    base = {"I1": 0, "I2": 0, "I3": 0, "S1": "oral", "R1": 0, "R2": 0, "A1": 0}
    base.update(overrides)
    return base


class TestMotionRenderVerbatim:
    """护栏：motion 渲染逐字不变（R-1 收口 = 拼装表逐字迁移入包，非重设计）。"""

    def test_run_s1_full_text_verbatim(self, feature_meta):
        """run-S1 合成场景整句模板与收口前引擎输出逐字相同。"""
        vecs = [_synthetic_run_s1_vector(), mkvector(M1a=1, M3a=1),
                mkvector(M1a=1, M3a=1), mkvector(M1a=1, M3a=1)]
        cluster_schema = _synthetic_cluster_schema(feature_meta, vecs)
        tpl = te.build_template(
            {"sense_id": 1, "lemma": "run", "sense_no": "1",
             "sense_label": "足部奔跑义", "language": "en", "status": "目标",
             "tag": None, "register": None, "subject_type": None,
             "source_dict": "OALD10", "definition": RUN_S1_DEFINITION},
            _synthetic_run_s1_vector(), cluster_schema, feature_meta)
        assert tpl["template_text"] == (
            "【图式：方式伴随图式】人/动物主体，以低速、一般方式在陆地介质中移动，"
            "动因自主；[可变槽位: 主体-动物=动物主体；情态急促度=一般；动因=自主]")

    def test_flee_full_text_verbatim(self, feature_meta):
        """flee 式场景（P1=1 受迫）整句模板逐字不变（含路径片段与回退主体）。"""
        vec = mkvector(P1=1, C1=1, M2=2, M3a=1)
        cluster_schema = _synthetic_cluster_schema(feature_meta, [vec] * 4)
        tpl = te.build_template(
            {"sense_id": 9, "lemma": "flee", "sense_no": "1",
             "sense_label": "逃离义", "language": "en", "status": "目标",
             "tag": None, "register": None, "subject_type": None,
             "source_dict": "OALD10", "definition": "[intransitive]to leave"},
            vec, cluster_schema, feature_meta)
        assert tpl["template_text"] == (
            "【图式：源点脱离图式】主体不限，自源点出发，以低速、急促方式在陆地介质"
            "中移动，动因受迫；[可变槽位: 无（全要素簇内共享）]")


class TestSpeechTemplateAssembly:
    """speech 包 template_assembly 节：render_template_text 产出言说动词口径释义。"""

    def test_renders_speech_wordings_without_motion_residue(self, speech_meta):
        """断言义向量 → 受话/引语/声道/话题/取向/正式度全按拼装节出词面。"""
        text = te.render_template_text(
            speech_meta, speech_vector(I1=1, I2=1, I3=1, R2=1),
            {"name": "断言图式", "code": "ASSERT"}, [])
        assert text.startswith("【图式：断言图式】")
        assert "有受话" in text                       # I1 值标签直出
        assert "有引语" in text                       # I2 值标签直出
        assert "以口头声道就话题作出陈述" in text      # S1+I3+R1 谓词段拼接
        assert "正式度中性" in text                   # R2 前缀＋值标签
        assert "[可变槽位: 无（全要素簇内共享）]" in text
        # 零 motion 词面残留（R-1 判据：非 motion 词面产物）
        for residue in ("移动", "介质", "自源点出发", "主体不限", "动因"):
            assert residue not in text

    def test_wording_varies_with_vector(self, speech_meta):
        """换取向/正式度/话题凸显/声道 → 词面随特征向量确定性变化。"""
        directive = te.render_template_text(
            speech_meta, speech_vector(I3=0, R1=1, R2=2, S1="written"),
            {"name": "指令图式", "code": "DIRECTIVE"}, [])
        assert "促使行动" in directive          # R1=1 → 指令取向词面
        assert "就话题" not in directive        # I3=0 不凸显 → 话题词面不出
        assert "以书面声道" in directive        # S1=written（nominal 原值）
        assert "正式度正式" in directive        # R2=2
        expressive = te.render_template_text(
            speech_meta, speech_vector(I1=1, R1=2),
            {"name": "表达图式", "code": "EXPRESSIVE"}, [])
        assert "抒发情感" in expressive         # R1=2 → 表情取向词面
        assert "有受话" in expressive

    def test_variable_slots_render_with_speech_labels(self, speech_meta):
        """槽位清单 = 本簇可变槽位 × 本义位取值标签（speech 同一机制）。"""
        slots = [{"code": "R2"}, {"code": "S1"}]
        text = te.render_template_text(
            speech_meta, speech_vector(R2=1, S1="sign"),
            {"name": "断言图式"}, slots)
        assert "正式度=中性" in text
        assert "声道使用=手势" in text
        assert text.index("正式度=中性") < text.index("声道使用=手势")

    def test_motion_pack_still_renders_via_own_assembly(self, feature_meta):
        """对照锚：motion 渲染走 motion 拼装节（词面是移动动词口径）。"""
        text = te.render_template_text(feature_meta, mkvector(M1a=1, P1=1),
                                       {"name": "源点脱离图式"}, [])
        assert "自源点出发" in text and "移动" in text


class TestTemplateAssemblyFailClosed:
    """范畴包缺 template_assembly → fail-closed（报错，不回退 motion 拼装表）。"""

    @pytest.fixture()
    def pack_without_assembly(self, monkeypatch):
        """把 resolve_pack 指向剥掉 template_assembly 节的 speech 包。"""
        pack = load_pack("speech")
        pack["schemas"] = {k: v for k, v in pack["schemas"].items()
                           if k != "template_assembly"}
        monkeypatch.setattr(te, "resolve_pack", lambda *a, **k: pack)
        return pack

    def test_render_raises_category_pack_error(self, pack_without_assembly):
        """缺节时 render_template_text 报「范畴包缺 template_assembly」。"""
        with pytest.raises(te.CategoryPackError, match="template_assembly"):
            te.render_template_text(
                te._feature_meta(pack_without_assembly),
                speech_vector(R1=0), {"name": "断言图式"})

    def test_build_template_raises(self, pack_without_assembly):
        """缺节时 build_template 同样 fail-closed（instantiate 链路降级为 None）。"""
        with pytest.raises(te.CategoryPackError, match="template_assembly"):
            te.build_template(
                {"sense_id": 1, "lemma": "say", "sense_no": "1",
                 "sense_label": "陈述义", "language": "en", "status": "目标",
                 "tag": None, "register": None, "subject_type": None,
                 "source_dict": "OALD10", "definition": "to speak"},
                speech_vector(S1=0), None,   # 全整数向量（DB 存储口径）
                te._feature_meta(pack_without_assembly))

    def test_empty_assembly_raises(self, speech_meta):
        """显式传入空拼装节（节为空）同样 fail-closed。"""
        with pytest.raises(te.CategoryPackError, match="template_assembly"):
            te.render_template_text(speech_meta, speech_vector(), None, [],
                                    assembly={})


# ============================================
# MySQL 路径（不可用则 skip，与 test_category_study 同口径）
# ============================================

def _db_available():
    try:
        from src.mysql_db import get_db_cursor
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark_db = pytest.mark.skipif(not _db_available(),
                                   reason="MySQL 不可用，跳过模板引擎数据层测试")


@pytest.mark.skipif(not _db_available(),
                    reason="MySQL 不可用，跳过模板引擎数据层测试")
class TestRealRunData:
    """真实 RUN 范畴数据抽验：run-S1 对照论文 §6.4 手工样例。"""

    def test_derive_run_en_clusters(self):
        schemas = te.derive_cluster_schemas("RUN", "en")
        assert len(schemas) == 5  # 预编码版英 5 簇
        names = {(s["schema"] or {}).get("code") for s in schemas}
        assert names <= {"MANNER_ACCOMP", "SOURCE_DETACH", "GOAL_ARRIVE",
                         "INTERACT_MOVE"}
        # 每个簇的核心/槽位互斥且只含 in_clustering 特征（P/M/C 15 列）
        pack = load_pack("motion")
        clustering = {c for c, f in te._feature_meta(pack).items()
                      if f["in_clustering"]}
        for s in schemas:
            assert set(s["schema_core"]) <= clustering
            assert {v["code"] for v in s["variable_slots"]} <= clustering

    def test_instantiate_run_s1_against_paper_sample(self):
        """run-S1：OALD 原文 = 论文样例原文；簇4 → 方式伴随图式。"""
        sense_id = te.lookup_sense_id("RUN", "en", "run", sense_no="1")
        assert sense_id is not None
        schemas = te.derive_cluster_schemas("RUN", "en")
        tpl = te.instantiate_template("RUN", "en", sense_id,
                                      engine_schema=schemas)
        assert tpl is not None
        assert tpl["lemma"] == "run" and tpl["sense_no"] == "1"
        assert tpl["oald"]["grammar"] == "intransitive"
        assert tpl["oald"]["definition"] == \
            "to move using your legs, going faster than when you walk"
        assert tpl["图式维度"]["name"] == "方式伴随图式"
        assert tpl["图式维度"]["cluster_no"] == 4  # 方式奔跑大类
        # 真实编码锚点：C1=2 自主、M1a=1 人主体
        by_code = {p["code"]: p for p in tpl["语义参数维度"]}
        assert by_code["C1"]["value_label"] == "自主"
        assert by_code["M1a"]["value_label"] == "人主体"
        assert tpl["template_text"].startswith("【图式：方式伴随图式】")

    def test_export_run_cluster_csv(self):
        sense_id = te.lookup_sense_id("RUN", "en", "run", sense_no="1")
        schemas = te.derive_cluster_schemas("RUN", "en")
        cluster = next(s for s in schemas
                       if any(m["sense_id"] == sense_id for m in s["members"]))
        payload = te.collect_cluster_templates(
            "RUN", "en", cluster_no=cluster["cluster_no"])
        assert len(payload["templates"]) == cluster["size"]
        csv_text = te.build_export_csv(payload["templates"])
        rows = list(csv.reader(io.StringIO(csv_text)))
        assert len(rows) == cluster["size"] + 1
        for row in rows[1:]:
            for cell in row:
                assert not str(cell).startswith("=")
        json.loads(te.build_export_json(payload))
