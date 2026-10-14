"""
词表数据源的契约测试。

覆盖 `src/word_source.py` 的两类风险：

  1. **文档解析** —— xlsx/docx 是外部输入，列名、工作表名、值域都可能被改。
     改了必须让测试红，而不是静默少读几行词。
  2. **释义优先级** —— dictionary.db 是「释义正确性」的首选来源，但它只覆盖
     136 词里的 9 个。降级链的每一级都不能静默跳过，否则页面会显示空释义。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.word_source as ws  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVIN = os.path.join(ROOT, "docs/Levin移动动词候选词筛选表.xlsx")


# ============================================
# 常量：值域必须与文档一致
# ============================================
def test_image_schemas_match_doc():
    """标准 2 明确「标注时不能自行新增图式类型」—— 值域锁死成四类。"""
    assert ws.IMAGE_SCHEMAS == (
        "源点脱离图式",
        "终点抵达图式",
        "方式伴随图式",
        "互动位移图式",
    )


def test_alignment_levels_match_doc():
    """标准 4 的三个对齐等级。"""
    assert ws.ALIGNMENT_FULL == "完全对齐"
    assert ws.ALIGNMENT_PARTIAL == "部分对齐"
    assert ws.ALIGNMENT_ZERO == "零对齐"


def test_every_sub_cat_has_a_schema():
    """xlsx 里出现过的每个次类都必须映射到图式，不能漏。"""
    rows = ws.load_levin_table()
    sub_cats = {r["sub_cat"] for r in rows}
    unmapped = sub_cats - set(ws.SCHEMA_BY_SUB_CAT)
    assert not unmapped, f"这些次类没有映射意象图式: {unmapped}"


def test_schema_values_are_within_allowed_set():
    for sub_cat, schema in ws.SCHEMA_BY_SUB_CAT.items():
        assert schema in ws.IMAGE_SCHEMAS, f"{sub_cat} 映射到了非法图式 {schema}"


# ============================================
# Levin xlsx 解析
# ============================================
def test_levin_table_is_readable():
    """默认取全部三类 171 词（2026-10-07 决策：捞回路径/互动聚焦词）。"""
    rows = ws.load_levin_table()
    assert rows, "没读到任何词 —— 检查工作表名是否被改"
    assert len(rows) == 171, f"词表默认范围应有 171 词，实得 {len(rows)}"
    assert {r["main_cat"] for r in rows} == {"方式聚焦型", "路径聚焦型", "互动聚焦型"}


def test_levin_manner_scope_is_the_136_subset():
    """
    ``scope='manner'`` 取回历史的方式聚焦子集（136 词）。

    两个数都要钉住：136 是 9-28 至 10-07 间的历史词表范围（对照与语料连续性
    检查用），171 是筛选表的全部结果。只钉一个的话，「默认范围被改回 136」
    或「xlsx 悄悄少了词」都发现不了。
    """
    allrows = ws.load_levin_table(scope="all")
    assert len(allrows) == 171, f"筛选后应有 171 词，实得 {len(allrows)}"
    assert {r["main_cat"] for r in allrows} == {"方式聚焦型", "路径聚焦型", "互动聚焦型"}
    manner = ws.load_levin_table(scope="manner")
    assert len(manner) == 136, f"方式聚焦型应有 136 词，实得 {len(manner)}"
    assert {r["main_cat"] for r in manner} == {ws.MAIN_CAT_MANNER}
    assert {r["verb"] for r in manner} <= {r["verb"] for r in allrows}


def test_levin_rejects_unknown_scope():
    """非法 scope 必须报错，不能静默返回全部 —— 那会让词表悄悄多出 35 个词。"""
    import pytest

    with pytest.raises(ValueError):
        ws.load_levin_table(scope="bogus")


def test_levin_rows_have_required_fields():
    for row in ws.load_levin_table():
        assert row["verb"], "词目不能为空"
        assert row["main_cat"], f"{row['verb']} 缺主范畴"
        assert row["sub_cat"], f"{row['verb']} 缺次类"
        assert row["image_schema"], f"{row['verb']} 缺意象图式"


def test_levin_three_main_categories():
    """文档的「三域」：方式 / 路径 / 互动。"""
    cats = {r["main_cat"] for r in ws.load_levin_table(scope="all")}
    assert cats == {"方式聚焦型", "路径聚焦型", "互动聚焦型"}, cats


def test_manner_scope_has_eight_sub_categories():
    """方式聚焦子集的次类数（8 个）。「十二次类」是整张筛选表的说法。"""
    subs = {r["sub_cat"] for r in ws.load_levin_table(scope="manner")}
    assert len(subs) == 8, f"方式聚焦型应有 8 个次类，实得 {len(subs)}: {sorted(subs)}"


def test_levin_twelve_sub_categories():
    """文档的「十二次类」—— 数量与内容都钉住。"""
    subs = {r["sub_cat"] for r in ws.load_levin_table(scope="all")}
    assert len(subs) == 12, f"次类应为 12 个，实得 {len(subs)}: {sorted(subs)}"


def test_levin_lemmas_are_unique():
    rows = ws.load_levin_table()
    verbs = [r["verb"].lower() for r in rows]
    dupes = {v for v in verbs if verbs.count(v) > 1}
    assert not dupes, f"Levin 表有重复词目: {dupes}"


def test_rejected_sheet_partitions_candidates():
    """
    「候选词筛选表」= 保留 ∪ 剔除，两页必须对得上。

    否则说明有人只改了一页 —— 那样后面的统计与文档都是错的。
    """
    import openpyxl

    wb = openpyxl.load_workbook(LEVIN, data_only=True)
    ws_cand = wb["候选词筛选表"]
    rows = list(ws_cand.iter_rows(values_only=True))
    header = [(str(h).strip() if h else "") for h in rows[0]]
    i_verb = header.index("词目(lemma)")
    i_reason = header.index("剔除原因")
    candidates = {str(r[i_verb]).strip() for r in rows[1:] if r[i_verb]}
    rejected = {
        str(r[i_verb]).strip() for r in rows[1:]
        if r[i_verb] and str(r[i_reason] or "").strip()
    }
    # 这里比的是**筛选表**的保留集（171），不是词表的取词范围（136）。
    # 两页是否对得上，跟「词表只收方式聚焦型」是两件事，不能混为一谈。
    kept = {r["verb"] for r in ws.load_levin_table(scope="all")}

    assert kept <= candidates, f"保留词不在候选表里: {kept - candidates}"
    assert rejected <= candidates
    assert kept | rejected == candidates, (
        f"候选表未被完整划分，漏掉: {candidates - kept - rejected}"
    )
    assert not (kept & rejected), f"既保留又剔除: {kept & rejected}"


def test_missing_sheet_raises():
    """工作表被改名时必须报错，不能返回空列表让下游以为「没有词」。"""
    import pytest

    with pytest.raises(ValueError):
        ws.load_levin_table(_make_bad_xlsx())


def _make_bad_xlsx():
    import openpyxl
    import tempfile

    wb = openpyxl.Workbook()
    wb.active.title = "别的名字"
    path = os.path.join(tempfile.mkdtemp(), "bad.xlsx")
    wb.save(path)
    return path


# ============================================
# dictionary.db 解析
# ============================================
class TestDictionaryDB:
    def test_unavailable_path_is_safe(self):
        db = ws.DictionaryDB("/tmp/no-such-dictionary.db")
        assert db.available is False
        assert db.senses("go") == []
        assert db.has_verb("go") is False

    def test_parses_senses_with_chinese(self):
        db = ws.DictionaryDB()
        if not db.available:
            return
        senses = db.senses("go")
        assert senses, "go 应该有义位"
        assert any(s["ch_ndef"] for s in senses), "至少要有一个带中文释义的义位"
        first = senses[0]
        assert set(first) >= {"ch_ndef", "en_ndef", "examples", "synonyms",
                              "antonyms", "sense_index"}

    def test_sense_index_is_sequential(self):
        db = ws.DictionaryDB()
        if not db.available:
            return
        senses = db.senses("go")
        assert [s["sense_index"] for s in senses] == list(range(1, len(senses) + 1))

    def test_ignores_non_verb_pos(self):
        """
        必须只取 pos='v'。

        库里的 pos 有脏值（'v '、' v'、'v　'），所以实现用了 trim()；
        这里用一个同时有名词与动词义位的词验证没有取错。
        """
        db = ws.DictionaryDB()
        if not db.available:
            return
        assert db.has_verb("abandon") is True
        senses = db.senses("abandon")
        assert senses

    def test_empty_placeholder_senses_are_dropped(self):
        """库里存在只有空标签的 <sense> 占位节点，不该被当成真实义位。"""
        db = ws.DictionaryDB()
        if not db.available:
            return
        for sense in db.senses("depart"):
            assert sense["ch_ndef"] or sense["en_ndef"] or sense["examples"], (
                "返回了完全空的义位"
            )

    def test_missing_word_returns_empty(self):
        db = ws.DictionaryDB()
        if not db.available:
            return
        assert db.senses("notarealverbxyz") == []


# ============================================
# 释义优先级（核心契约）
# ============================================
def _fake_levin(verb, brief="某某动作", sub="陆地行进类"):
    return [{
        "verb": verb, "levin_source": "51", "cross_subclass": "否",
        "main_cat": "方式聚焦型", "sub_cat": sub,
        "sense_brief": brief, "judge_reason": "理由",
        "image_schema": "方式伴随图式", "alignment_hint": "部分对齐",
        "cn_syntax_hint": "需状语", "translation_hint": "增补方式",
    }]


def test_dictionary_db_wins_over_everything():
    """dictionary.db 有 Ch-Def 时必须优先，不能被二手来源覆盖。"""

    class FakeDB:
        available = True

        def has_verb(self, v):
            return True

        def phonetic(self, v):
            return "wɔːk"

        def senses(self, v):
            return [{"sense_index": 1, "ch_ndef": "词典原文释义", "en_ndef": "en",
                     "construction": "", "examples": ["ex"], "ch_examples": ["例"],
                     "synonyms": [], "antonyms": []}]

    entries = ws.build_entries(
        _fake_levin("walk"), {"walk": {"en_def": "oxford"}},
        FakeDB(), {"walk": {"chinese_ndef": "旧词库释义"}},
    )
    assert entries[0]["chinese_ndef"] == "词典原文释义"
    assert entries[0]["definition_source"] == "dictionary.db"
    assert entries[0]["definition_rank"] == 1


def test_legacy_used_when_db_has_no_chinese():
    class EmptyDB:
        available = True

        def has_verb(self, v):
            return False

        def senses(self, v):
            return []

        def phonetic(self, v):
            return ""

    entries = ws.build_entries(
        _fake_levin("walk"), {}, EmptyDB(),
        {"walk": {"chinese_ndef": "旧词库释义", "example_sentence": "例句"}},
    )
    assert entries[0]["definition_source"] == "legacy-library"
    assert entries[0]["chinese_ndef"] == "旧词库释义"
    assert entries[0]["example_sentence"] == "例句"


def test_phonetic_comes_from_dictionary_db():
    """音标随词目一起进 entry —— 卡片要读它。缺了不会报错，只会让卡片显示「未收录」。"""

    class DB:
        available = True

        def has_verb(self, v):
            return True

        def phonetic(self, v):
            return "əˈbændən"

        def senses(self, v):
            return []

    entries = ws.build_entries(_fake_levin("abandon"), {}, DB(), {})
    assert entries[0]["phonetic"] == "əˈbændən"


def test_phonetic_is_empty_when_db_absent():
    """没有 dictionary.db 时给空串而不是 None —— 前端据此显示「未收录」。"""

    class DB:
        available = False

        def has_verb(self, v):
            return False

        def phonetic(self, v):
            raise AssertionError("库不可用就不该去问它要音标")

        def senses(self, v):
            return []

    entries = ws.build_entries(_fake_levin("walk"), {}, DB(), {})
    assert entries[0]["phonetic"] == ""


def test_levin_brief_used_when_no_other_chinese():
    """xlsx 的「原型主导义简述」兜底 —— 保证不会出现空壳释义。"""

    class EmptyDB:
        available = True

        def has_verb(self, v):
            return False

        def senses(self, v):
            return []

        def phonetic(self, v):
            return ""

    entries = ws.build_entries(_fake_levin("slither", brief="蜿蜒滑行爬行"),
                               {}, EmptyDB(), {})
    assert entries[0]["definition_source"] == "levin-brief"
    assert "蜿蜒滑行爬行" in entries[0]["chinese_ndef"]


def test_oxford_is_last_resort_before_pending():
    class EmptyDB:
        available = True

        def has_verb(self, v):
            return False

        def senses(self, v):
            return []

        def phonetic(self, v):
            return ""

    entries = ws.build_entries(
        _fake_levin("x", brief=""), {"x": {"en_def": "to move"}}, EmptyDB(), {},
    )
    assert entries[0]["definition_source"] == "oxford-en"


def test_pending_when_nothing_available():
    class EmptyDB:
        available = True

        def has_verb(self, v):
            return False

        def senses(self, v):
            return []

        def phonetic(self, v):
            return ""

    entries = ws.build_entries(_fake_levin("x", brief=""), {}, EmptyDB(), {})
    assert entries[0]["definition_source"] == "pending"
    assert entries[0]["definition_rank"] == 5


def test_source_rank_is_monotonic_with_reliability():
    """可信度排名：词典原文 < 旧词库 < 研究者短语 < 英文 < 空。"""
    assert ws.SOURCE_RANK["dictionary.db"] < ws.SOURCE_RANK["legacy-library"]
    assert ws.SOURCE_RANK["legacy-library"] < ws.SOURCE_RANK["levin-brief"]
    assert ws.SOURCE_RANK["levin-brief"] < ws.SOURCE_RANK["oxford-en"]
    assert ws.SOURCE_RANK["oxford-en"] < ws.SOURCE_RANK["pending"]


def test_no_entry_has_empty_definition_in_real_data():
    """
    真实数据下不能有任何空释义。

    这是「释义正确性」的兜底：四级降级链必须真的兜住，否则页面会显示空。
    """
    entries = ws.build_entries(
        ws.load_levin_table(), ws.load_oxford_cache(),
        ws.DictionaryDB(), ws.load_legacy_library(),
    )
    empty = [e["verb"] for e in entries if not (e["chinese_ndef"] or "").strip()]
    assert not empty, f"这些词没有释义: {empty}"


# ============================================
# 覆盖率审计
# ============================================
def test_audit_reports_honest_coverage():
    """
    审计必须如实报告 dictionary.db 的低覆盖率。

    这是刻意暴露的事实：词表 171 词（默认范围，三类）里只有少数在词典库里有
    动词词条。若审计把数字报高了，文档里就会写出与事实不符的「全部来自 OALD 原文」。
    """
    entries = ws.build_entries(
        ws.load_levin_table(), ws.load_oxford_cache(),
        ws.DictionaryDB(), ws.load_legacy_library(),
    )
    audit = ws.audit_coverage(entries)
    assert audit["total"] == 171
    assert audit["in_dictionary_db"] == sum(
        1 for e in entries if e["has_dictionary_verb"]
    )
    assert audit["dictionary_原文率"] < 50, "覆盖率不该被夸大"
    # 覆盖率审计里的「原文率」必须与 by_source 里 dictionary.db 的条数一致，
    # 两个口径不一致会让人得出相反的结论
    assert (audit["in_dictionary_db"] / audit["total"] * 100
            - audit["dictionary_原文率"]) < 0.05


# ============================================
# Oxford 缓存
# ============================================
def test_oxford_nulls_are_normalised():
    """缓存里有 null 值（抓取失败的占位），必须归一成 {}。"""
    import tempfile

    path = os.path.join(tempfile.mkdtemp(), "ox.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"a": None, "b": {"en_def": "x"}, "c": "字符串不是字典"}, f)
    out = ws.load_oxford_cache(path)
    assert out["a"] == {}
    assert out["b"]["en_def"] == "x"
    assert out["c"] == {}


def test_oxford_missing_file_is_safe():
    assert ws.load_oxford_cache("/tmp/no-such-oxford.json") == {}


def test_sense_count_matches_senses_written_to_db():
    """
    sense_count 必须等于**实际写入 word_senses 表的行数**。

    它曾经被写成「有中文释义的义位数」(238)，而库里实际写入 246 行，
    于是文档说「合计 238 条义位」、库里却是 246 —— 同一件事两个数字。
    这个字段的语义就是行数，不该有第二种解释。
    """
    entries = ws.build_entries(
        ws.load_levin_table(), ws.load_oxford_cache(),
        ws.DictionaryDB(), ws.load_legacy_library(),
    )
    for e in entries:
        assert e["sense_count"] == len(e["senses"]), (
            f"{e['verb']}: sense_count={e['sense_count']} 与义位数 {len(e['senses'])} 不一致"
        )


def test_build_entries_shape_contract():
    """合成结果的字段契约（页面与灌库脚本都依赖这些键）。"""
    entries = ws.build_entries(
        ws.load_levin_table(), ws.load_oxford_cache(),
        ws.DictionaryDB(), ws.load_legacy_library(),
    )
    required = {
        "verb", "main_cat", "sub_cat", "image_schema", "alignment_hint",
        "cn_syntax_hint", "translation_hint", "sense_brief", "judge_reason",
        "chinese_ndef", "definition_source", "definition_rank", "sense_count",
        "senses", "has_dictionary_verb",
    }
    for e in entries:
        missing = required - set(e)
        assert not missing, f"{e.get('verb')} 缺少字段 {missing}"


def test_source_rank_matches_table():
    """definition_rank 必须与 SOURCE_RANK 表一致，不能各自维护一份。"""
    entries = ws.build_entries(
        ws.load_levin_table(), ws.load_oxford_cache(),
        ws.DictionaryDB(), ws.load_legacy_library(),
    )
    for e in entries:
        assert e["definition_rank"] == ws.SOURCE_RANK[e["definition_source"]], e["verb"]


# ============================================
# 原型义位选择
# ============================================
#
# dictionary.db 的义位按词典原书顺序排列，首位**往往**就是原型义，但不总是。
# 这组测试钉住两件事：
#   1. 默认保留首条（词典的排序本身携带「哪个义最核心」的信息）；
#   2. 只有在首条完全不含位移语义时，才允许被覆盖。
#
# 因为一个会挑冷僻义位的启发式，比一个基本正确的默认值更糟。


class TestPrototypeSenseSelection:
    def test_empty_senses_returns_zero(self):
        assert ws.select_prototype_index([], "任意简述") == 0

    def test_senses_without_chinese_fall_back_to_zero(self):
        senses = [{"ch_ndef": "", "en_ndef": "x"}] * 3
        assert ws.select_prototype_index(senses, "简述") == 0

    def test_keeps_first_when_it_has_motion_content(self):
        """首条含位移语义时不得被覆盖 —— 哪怕别的义位与简述字面更接近。"""
        senses = [
            {"sense_index": 1, "ch_ndef": "跑；奔跑", "en_ndef": "to run"},
            {"sense_index": 2, "ch_ndef": "操作〔机器〕使其运转", "en_ndef": "to operate"},
        ]
        # 「操作」这条不含位移语素，不该被选中
        assert ws.select_prototype_index(senses, "跑动") == 0

    def test_overrides_when_first_has_no_motion(self):
        """真实的错例：charge 首条是「要价，收费」，原型主导义是「猛冲向前」。"""
        senses = [
            {"sense_index": 1, "ch_ndef": "〔某人向他人〕要价，收费",
             "en_ndef": "to ask for money"},
            {"sense_index": 2, "ch_ndef": "〔某人向他人或某物〕冲锋，进攻；冲进〔某处〕",
             "en_ndef": "they rush forward very fast"},
        ]
        idx = ws.select_prototype_index(senses, "猛冲向前")
        assert idx == 1, "首条不含位移语义时应该被覆盖"

    def test_does_not_pick_an_obscure_sense_over_a_good_first(self):
        """
        回归：`come` 的简述是「朝说话人位置趋近」，字面在「来到；到达」里一个都不出现，
        而冷僻义位「〔某物〕垂到〔某位置〕」因为带「位置」二字反而更接近。

        若有人把策略改回「永远取最高分」，这条会红。
        """
        senses = [
            {"sense_index": 1, "ch_ndef": "来到；到达",
             "en_ndef": "to move or travel to where the speaker is located"},
            {"sense_index": 2, "ch_ndef": "〔某物〕垂到〔某位置〕",
             "en_ndef": "sth comes down to a position it goes down to it"},
        ]
        assert ws.select_prototype_index(senses, "朝说话人位置趋近") == 0

    def test_has_motion_content_detects_both_languages(self):
        assert ws.has_motion_content({"ch_ndef": "奔跑", "en_ndef": ""}) is True
        assert ws.has_motion_content({"ch_ndef": "", "en_ndef": "to travel"}) is True
        assert ws.has_motion_content({"ch_ndef": "要价，收费", "en_ndef": "to charge money"}) is False

    def test_brief_overlap_range(self):
        s = {"ch_ndef": "追逐；追赶", "en_ndef": ""}
        assert 0.0 <= ws.brief_overlap(s, "追逐另一对象移动") <= 1.0
        assert ws.brief_overlap(s, "") == 0.0

    def test_real_data_only_charge_is_overridden(self):
        """
        真实数据上的结果：能取到中文释义的 4 个词里，只有 charge 需要修正。

        这个数字本身是一个断言 —— 如果它突然变大，说明选择器被改得过于激进，
        开始覆盖本来正确的首条了。

        为什么是 4 而不是更多：词表范围收窄到「方式聚焦型」136 词后，与
        `data/dictionary.db`（只有 333 个动词词条）的交集正好是
        charge / run / move / fly 四个。这是**覆盖率的真实下降**，不是 bug ——
        收窄取词范围就必然减少与词典库的重合。库里有多少就是多少，不为了
        让这个数字好看而放宽词表范围。
        """
        db = ws.DictionaryDB()
        if not db.available:
            return
        lev = {r["verb"]: r for r in ws.load_levin_table()}
        overridden = []
        checked = 0
        for verb, row in lev.items():
            senses = db.senses(verb)
            with_ch = [i for i, s in enumerate(senses) if s["ch_ndef"]]
            if not with_ch:
                continue
            checked += 1
            if ws.select_prototype_index(senses, row["sense_brief"]) != with_ch[0]:
                overridden.append(verb)

        # 下限钉在 4：低于这个数说明 dictionary.db 读不到了（路径变了 / 库没了），
        # 而不是「词表变窄了」。上限不钉 —— 将来补词典数据不该让测试变红。
        assert checked >= 4, f"能取到释义的词太少（{checked}），检查 dictionary.db"
        assert overridden == ["charge"], f"被覆盖的词变了: {overridden}"
