"""范畴包机制的加载与自检验证（Agent D · 验收 V5）。

依据唯一事实源 docs/p1/多人标注系统设计规范.md §3-§4 / §7-V5，
与 docs/p1/跨词类通用框架.md §1-§3：

  ① motion 包 load_pack + run_selfcheck 通过（含已验证真值抽查：216/171/996=992+4/
     358、352、四图式、18 槽位、15+3 特征、9 占位符）；
  ② speech 验证帧（言说动词）通过——同一结构装得下不同词类：features ≥6 项、
     ordinal 与 nominal 各至少一项、A 组一项 in_clustering=false、三图式
     ASSERT/DIRECTIVE/EXPRESSIVE、八槽位；
  ③ 坏包必须报 CategoryPackError 且信息含坏槽位名（tmp_path 复制 motion 后把某个
     evidence_slot 改成不存在的值）；
  ④ CATEGORIES() 含 motion 与 speech；_template 被排除；
  ⑤ 六件套缺一 / 占位符缺失 / 准入 code 重复 / value_type 非法 / 组未定义等
     各自检条款的负面用例（不引 jsonschema，纯 Python 校验）。

不连数据库、不碰 src/app.py 等集成约束文件。
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.category_pack as cp  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS_DIR = os.path.join(REPO_ROOT, "configs")


# ============================================
# ① motion 包（验收 V5 正向）
# ============================================

class TestMotionPack:
    def test_selfcheck_passes(self):
        ok, problems = cp.run_selfcheck("motion")
        assert ok, problems

    def test_load_pack_returns_six_keys(self):
        pack = cp.load_pack("motion")
        assert set(pack) == {"admission", "features", "schemas", "corpus_map", "prompts", "pack"}

    def test_verified_truth_values(self):
        """规范 §4：数值以已验证真值为准（框架文档 §2 为蓝本）。"""
        pack = cp.load_pack("motion")
        # 词元池 216 候选 → 171 准入
        assert pack["pack"]["lemma_pool"] == {
            "source": "Levin (1993) Ch.51", "candidates": 216, "admitted_lemmas": 171,
        }
        # 996 = 992（OALD）+ 4（补充）
        assert pack["pack"]["sense_counts"] == {"total": 996, "oald": 992, "supplemented": 4}
        # 试点：英 32 义位 / 汉 25 条目
        assert pack["pack"]["pilot"]["en"]["senses"] == 32
        assert pack["pack"]["pilot"]["zh"]["items"] == 25
        # 候选链：机械筛 10 正 17 负 992→358；显式规则 344-6+5(+3 复核)→352
        pipe = pack["admission"]["candidate_pipeline"]
        assert pipe["mechanical_screening"] == {
            "positive_signals": 10, "negative_signals": 17, "kept": 358, "of": 992,
        }
        assert pipe["explicit_rules"] == {
            "R0": 344, "R1_removed": 6, "R2_kept": 5, "R3_review": 3, "net": 352,
        }
        # 边界条款 BR1-3
        assert [b["id"] for b in pack["admission"]["boundary_rules"]] == ["BR1", "BR2", "BR3"]

    def test_admission_three_classes(self):
        admission = cp.load_pack("motion")["admission"]["admission_classes"]
        classes = {c["code"]: c["name"] for c in admission}
        assert set(classes) == {"Y", "EXT", "N"}
        assert classes["Y"] == "核心物理位移义"

    def test_features_15_in_clustering_plus_3_verification(self):
        doc = cp.load_pack("motion")["features"]
        feats = {f["code"]: f for f in doc["features"]}
        assert len(feats) == 18
        clustering = [c for c, f in feats.items() if f["in_clustering"]]
        assert len(clustering) == 15
        assert set(clustering) == {
            "P1", "P2", "P3", "P4", "P5",
            "M1a", "M1b", "M1c", "M1d", "M2", "M3a", "M3b", "M3c", "M3d", "C1",
        }
        assert {c for c, f in feats.items() if not f["in_clustering"]} == {"A1", "A2", "A3"}
        # value_type 分布：P5/M2 ordinal，C1 nominal，其余 binary
        assert feats["P5"]["value_type"] == "ordinal"
        assert feats["P5"]["values"] == {0: "低", 1: "中", 2: "高"}
        assert feats["M2"]["value_type"] == "ordinal"
        assert feats["C1"]["value_type"] == "nominal"
        assert all(
            f["value_type"] == "binary"
            for c, f in feats.items()
            if c not in {"P5", "M2", "C1"}
        )
        # 分组 P/M/C/A 与 groups 定义一致
        assert {g["id"] for g in doc["groups"]} == {"P", "M", "C", "A"}
        assert all(f["group"] in {"P", "M", "C", "A"} for f in doc["features"])

    def test_four_schemas_and_domain_merging(self):
        doc = cp.load_pack("motion")["schemas"]
        codes = [s["code"] for s in doc["schemas"]]
        assert codes == ["MANNER_ACCOMP", "SOURCE_DETACH", "GOAL_ARRIVE", "INTERACT_MOVE"]
        assert doc["annotation"]["mode"] == "forced_choice"
        domains = {d["name"]: d["families"] for d in doc["annotation"]["domain_merging"]["domains"]}
        assert domains == {
            "方式位移域": ["MANNER_ACCOMP"],
            "路径位移域": ["SOURCE_DETACH", "GOAL_ARRIVE"],
            "互动位移域": ["INTERACT_MOVE"],
        }

    def test_corpus_map_18_slots_and_scoring(self):
        doc = cp.load_pack("motion")["corpus_map"]
        assert len(doc["slots"]) == 18
        assert all(s["sketch_gramrel"] for s in doc["slots"])
        assert doc["scoring"]["function"] == "mean_logdice_log2n"
        assert doc["scoring"]["top_k"] == 50
        assert doc["scoring"]["noise_filter"]["remove"] == ["抽象概念名词", "隐喻投射名词", "量化时间状态名词"]
        # 图式引用的槽位是 18 槽位的子集
        slot_codes = {s["code"] for s in doc["slots"]}
        for schema in cp.load_pack("motion")["schemas"]["schemas"]:
            assert set(schema["evidence_slots"]) <= slot_codes

    def test_screening_prompt_placeholders_and_heuristic(self):
        text = cp.load_pack("motion")["prompts"]["screening"]
        for name in cp.REQUIRED_PLACEHOLDERS:
            assert "{" + name + "}" in text, name
        assert "有没有真实物体，在物理空间里从一个地方移动到另一个地方" in text
        assert "有→Y；抽象隐喻→拓展；不动／只是改变自身属性→N" in text


# ============================================
# ② speech 包（框架文档 §3：同一框架装下言说动词）
# ============================================

class TestSpeechPack:
    def test_selfcheck_and_load(self):
        ok, problems = cp.run_selfcheck("speech")
        assert ok, problems
        assert set(cp.load_pack("speech")) == {
            "admission", "features", "schemas", "corpus_map", "prompts", "pack",
        }

    def test_features_same_structure_as_motion(self):
        """对照结论（§3）：正式度（ordinal）/声道（nominal）/引语论元（binary）
        与移动动词落在完全相同的字段结构里。"""
        doc = cp.load_pack("speech")["features"]
        feats = doc["features"]
        assert len(feats) >= 6
        clustering = [f for f in feats if f["in_clustering"]]
        assert len(clustering) >= 5
        value_types = {f["value_type"] for f in clustering}
        assert "ordinal" in value_types and "nominal" in value_types and "binary" in value_types
        # A 组核验区一项 in_clustering=false
        a_group = [f for f in feats if f["group"] == "A"]
        assert len(a_group) == 1 and a_group[0]["in_clustering"] is False
        assert all("values" in f for f in feats)

    def test_three_schemas_eight_slots(self):
        pack = cp.load_pack("speech")
        codes = [s["code"] for s in pack["schemas"]["schemas"]]
        assert codes == ["ASSERT", "DIRECTIVE", "EXPRESSIVE"]
        assert len(pack["corpus_map"]["slots"]) == 8
        assert pack["schemas"]["annotation"]["mode"] == "forced_choice"
        # 四图式换三图式、六槽位换八槽位——引擎读到的都是同一套键名
        motion_pack, speech_pack = cp.load_pack("motion"), cp.load_pack("speech")
        assert set(speech_pack["schemas"]) == set(motion_pack["schemas"])
        assert set(speech_pack["corpus_map"]["scoring"]) == set(
            motion_pack["corpus_map"]["scoring"])

    def test_screening_prompt_same_placeholders(self):
        text = cp.load_pack("speech")["prompts"]["screening"]
        for name in cp.REQUIRED_PLACEHOLDERS:
            assert "{" + name + "}" in text, name


# ============================================
# ③ 坏包必须报 CategoryPackError（验收 V5 反向）
# ============================================

def _copy_motion_to(tmp_path):
    """把真实 motion 包复制到 tmp_path/configs/motion，返回其目录。"""
    dest = tmp_path / "configs" / "motion"
    shutil.copytree(os.path.join(CONFIGS_DIR, "motion"), dest)
    return dest


def test_bad_evidence_slot_raises_with_slot_name(tmp_path, monkeypatch):
    """把 MANNER_ACCOMP 的某个 evidence_slot 改成不存在的值 → 必须报错且含该槽位名。"""
    dest = _copy_motion_to(tmp_path)
    bogus = "objects_bogus"
    schemas_path = dest / "schemas.yaml"
    import yaml

    data = yaml.safe_load(schemas_path.read_text(encoding="utf-8"))
    data["schemas"][0]["evidence_slots"][0] = bogus
    schemas_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))

    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    assert any(bogus in p for p in problems)

    with pytest.raises(cp.CategoryPackError) as excinfo:
        cp.load_pack("motion")
    assert bogus in str(excinfo.value)


def test_missing_file_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    (dest / "corpus_map.yaml").unlink()
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    with pytest.raises(cp.CategoryPackError) as excinfo:
        cp.load_pack("motion")
    assert "corpus_map.yaml" in str(excinfo.value)


def test_unparseable_yaml_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    (dest / "features.yaml").write_text("features: [ {unclosed", encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    with pytest.raises(cp.CategoryPackError) as excinfo:
        cp.load_pack("motion")
    assert "features.yaml" in str(excinfo.value)


def test_duplicate_admission_code_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    adm_path = dest / "admission.yaml"
    import yaml

    data = yaml.safe_load(adm_path.read_text(encoding="utf-8"))
    data["admission_classes"][1]["code"] = "Y"  # EXT → Y，code 互斥被破坏
    adm_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    assert any("互斥" in p and "Y" in p for p in problems)


def test_too_few_clustering_features_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    feat_path = dest / "features.yaml"
    import yaml

    data = yaml.safe_load(feat_path.read_text(encoding="utf-8"))
    n_off = 0
    for feat in data["features"]:
        if feat["in_clustering"] and n_off < 11:  # 15 → 4 项进聚类
            feat["in_clustering"] = False
            n_off += 1
    feat_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    assert any("in_clustering=true 的特征仅 4 项" in p for p in problems)


def test_bad_value_type_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    feat_path = dest / "features.yaml"
    import yaml

    data = yaml.safe_load(feat_path.read_text(encoding="utf-8"))
    data["features"][0]["value_type"] = "interval"  # 不在 {binary, nominal, ordinal}
    feat_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    assert any("interval" in p and "P1" in p for p in problems)


def test_undefined_feature_group_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    feat_path = dest / "features.yaml"
    import yaml

    data = yaml.safe_load(feat_path.read_text(encoding="utf-8"))
    data["features"][0]["group"] = "X"  # groups 只定义了 P/M/C/A
    feat_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    assert any("'X'" in p and "P1" in p for p in problems)


def test_missing_prompt_placeholder_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    screen_path = dest / "prompts" / "screening.txt"
    text = screen_path.read_text(encoding="utf-8").replace("{verbal_heuristic}", "判定口诀")
    screen_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    assert any("{verbal_heuristic}" in p for p in problems)


def test_missing_placeholder_granularity_exact(tmp_path, monkeypatch):
    """R4 1e：占位符自检颗粒度 —— 缺 N 个报 N 条、每条只点名缺失的那一个。

    颗粒度差的自检只给「占位符不全」一句话，维护者得逐个 diff 九个占位符；
    这里钉死逐占位符报告（每条含「缺少占位符 {name}」），且不误报在场的
    占位符、不夹带其他自检条款的噪音。
    """
    dest = _copy_motion_to(tmp_path)
    screen_path = dest / "prompts" / "screening.txt"
    text = screen_path.read_text(encoding="utf-8")
    # 同时挖掉两个占位符（verbal_heuristic / schema_names，其余七个在场）
    for token in ("{verbal_heuristic}", "{schema_names}"):
        text = text.replace(token, "占位")
    screen_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))

    ok, problems = cp.run_selfcheck("motion")
    assert not ok
    expected = sorted([
        "prompts/screening.txt: 缺少占位符 {verbal_heuristic}",
        "prompts/screening.txt: 缺少占位符 {schema_names}",
    ])
    assert sorted(problems) == expected  # 恰好两条、逐一点名、无其他噪音


def test_missing_screening_prompt_raises(tmp_path, monkeypatch):
    dest = _copy_motion_to(tmp_path)
    (dest / "prompts" / "screening.txt").unlink()
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    with pytest.raises(cp.CategoryPackError) as excinfo:
        cp.load_pack("motion")
    assert "screening.txt" in str(excinfo.value)


def test_unknown_category_not_in_categories_and_selfcheck_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "_REPO_ROOT", str(tmp_path))
    assert cp.CATEGORIES() == ()
    ok, problems = cp.run_selfcheck("nonexistent")
    assert not ok and problems


# ============================================
# ④ CATEGORIES() 与 _template
# ============================================

class TestCategories:
    def test_contains_motion_and_speech(self):
        cats = cp.CATEGORIES()
        assert isinstance(cats, tuple)
        assert "motion" in cats and "speech" in cats

    def test_template_excluded(self):
        assert "_template" not in cp.CATEGORIES()

    def test_template_six_files_complete_and_parseable(self):
        """模板字段齐全、可解析（值留占位，不要求过 selfcheck）。"""
        import yaml

        tdir = os.path.join(CONFIGS_DIR, "_template")
        for fname in cp.PACK_FILES:
            path = os.path.join(tdir, fname)
            assert os.path.isfile(path), fname
            with open(path, encoding="utf-8") as fh:
                assert isinstance(yaml.safe_load(fh), dict), fname
        screen = os.path.join(tdir, "prompts", "screening.txt")
        assert os.path.isfile(screen)
        with open(screen, encoding="utf-8") as fh:
            text = fh.read()
        for name in cp.REQUIRED_PLACEHOLDERS:
            assert "{" + name + "}" in text, name

    def test_selfcheck_contract_signature(self):
        """规范 §3 契约：run_selfcheck → (bool, list[str])。"""
        result = cp.run_selfcheck("motion")
        assert isinstance(result, tuple) and len(result) == 2
        ok, problems = result
        assert ok is True and problems == []


# ============================================
# ⑤ 占位符契约与引擎-配置边界
# ============================================

class TestContract:
    def test_required_placeholders_match_spec(self):
        """规范 §4 / 框架文档 §2⑤ 列出的九个占位符。"""
        assert set(cp.REQUIRED_PLACEHOLDERS) == {
            "category_name", "operational_definition", "admission_classes",
            "verbal_heuristic", "boundary_rules", "schema_names",
            "sense_id", "definition", "examples",
        }

    def test_engine_has_no_wordclass_names(self):
        """框架文档 §4 纪律：引擎代码不得出现具体词类名词（如「方式伴随」「P5 速度」）。"""
        with open(os.path.join(REPO_ROOT, "src", "category_pack.py"), encoding="utf-8") as fh:
            source = fh.read()
        for banned in ("MANNER_ACCOMP", "SOURCE_DETACH", "GOAL_ARRIVE", "INTERACT_MOVE",
                       "ASSERT", "DIRECTIVE", "EXPRESSIVE", "方式伴随", "移动动词", "言说"):
            assert banned not in source, banned

    def test_yaml_safe_load_only(self):
        """安全规则：yaml 只用 safe_load。"""
        with open(os.path.join(REPO_ROOT, "src", "category_pack.py"), encoding="utf-8") as fh:
            source = fh.read()
        assert "safe_load" in source
        assert "yaml.load(" not in source
        assert "unsafe_load" not in source
        assert "import jsonschema" not in source
