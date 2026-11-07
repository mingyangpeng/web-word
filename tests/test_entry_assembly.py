"""词条装配视图模块单元测试（批次 9 Agent AS，工序 14 消费侧）。

不依赖数据库：装配七段的取数一律经 src/entry_assembly.py 模块级
_fetch_* / _derive_* 薄适配层，测试 monkeypatch 这些名字构造四种场景 ——
  * 全缺数 → ①–⑥ 全灰（body None，缺数原因非空），⑦ 参见整段省略；
  * 部分有数 → 对应段渲染文本（标题、关键字段、coverage 标注在场）；
  * 分支场景 → merged 义项 / 空例证 / 无对译 / 发布过滤 / 图片内嵌上限；
  * 脏数据/取数抛异常 → 不崩，整段折叠为灰段；动态值全部转义。
纯函数（来源分级、coverage 标注、三态对译行、例证行、媒体行、定制属性
值、范畴代号解析）直接测；渲染入口需要 Streamlit 运行时，按义项脊柱
测试同口径不做渲染级测试（app.py 接线为源码级断言）。
"""
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import entry_assembly, lexical_db, media_db, mysql_db  # noqa: E402
from src.entry_assembly import (  # noqa: E402
    Section,
    _assembly_sections,
    _clean_verb,
    _coverage_tag,
    _custom_value_text,
    _example_line,
    _format_source_grade,
    _media_line,
    _study_code_for,
    _translation_line,
    _truncate,
    render_entry_assembly,
)

APP_PATH = os.path.join(PROJECT_ROOT, "src", "app.py")


def _app_source() -> str:
    with open(APP_PATH, encoding="utf-8") as f:
        return f.read()


# ============================================
# 模块契约：入口签名、Section 形态、app.py 接线、GUIDE 母本
# ============================================

class TestModuleContract:
    def test_render_entry_signature(self):
        """契约：render_entry_assembly(verb, category="motion", language="en")。"""
        sig = inspect.signature(render_entry_assembly)
        params = list(sig.parameters.values())
        assert params[0].name == "verb"
        assert params[1].name == "category" and params[1].default == "motion"
        assert params[2].name == "language" and params[2].default == "en"
        assert sig.return_annotation in (None, "None", inspect.Signature.empty) or \
            "None" in str(sig.return_annotation)

    def test_assembly_sections_signature(self):
        """纯编排 _assembly_sections 与渲染入口同参（可 monkeypatch 单测）。"""
        sig = inspect.signature(_assembly_sections)
        params = list(sig.parameters.values())
        assert params[0].name == "verb"
        assert params[1].default == "motion"
        assert params[2].default == "en"

    def test_section_fields(self):
        """Section 四位：title / body / missing_reason / images。"""
        assert Section._fields == ("title", "body", "missing_reason", "images")

    def test_app_wires_assembly_expander(self):
        """搜索结果区接线（源码级断言）：词与词关系之后、「📄 词条装配预览」
        expander 默认收起、展开才调 render_entry_assembly。"""
        source = _app_source()
        assert "render_entry_assembly" in source
        assert "词条装配预览" in source
        assert "entry_assembly_expander" in source
        # 懒加载接线：expander.open 门 + on_change="rerun"（与义项脊柱同模式）
        assert "assembly_expander.open" in source
        # 插入点：装配预览 expander（带 📄 的标题只在接线处出现）在词间关系
        # 区块之后
        assert source.index("render_word_relation_section(verb)") < \
            source.index("📄 词条装配预览")
        # 默认收起（接线处无 expanded=True）
        wiring = source[source.index("📄 词条装配预览") - 300:
                        source.index("📄 词条装配预览") + 400]
        assert "expanded=True" not in wiring

    def test_module_docstring_is_guide_source(self):
        """GUIDE 母本写进模块 docstring（帮助中心同步用）：关键口径在场。"""
        doc = inspect.getmodule(render_entry_assembly).__doc__ or ""
        for key in ("成品词条内容模型", "装配确定性", "绝不编数", "沿用 OALD",
                    "发布", "purpose", "principle", "data_source", "steps", "notes"):
            assert key in doc, f"docstring 缺少 GUIDE 关键词：{key}"


# ============================================
# monkeypatch 基建
# ============================================

def _patch_all_missing(monkeypatch):
    """全部取数适配层 → 空库口径（词目行不存在、义项/映射/例证/媒体全空）。

    含 _fetch_template / _fetch_published_examples / _fetch_translation ——
    有映射义项的段构造会连带调用它们，一并打桩保证单测零真实 DB 访问。
    """
    monkeypatch.setattr(entry_assembly, "_fetch_definition_row", lambda v: None)
    monkeypatch.setattr(entry_assembly, "_fetch_oald_senses", lambda v: [])
    monkeypatch.setattr(entry_assembly, "_fetch_category_codes", lambda: [])
    monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                        lambda code, lang, lemma: {})
    monkeypatch.setattr(entry_assembly, "_derive_engine_schema", lambda cat, lang: [])
    monkeypatch.setattr(entry_assembly, "_fetch_template",
                        lambda code, lang, cid, schema: None)
    monkeypatch.setattr(entry_assembly, "_fetch_published_examples", lambda ref: [])
    monkeypatch.setattr(entry_assembly, "_fetch_translation", lambda ref: None)
    monkeypatch.setattr(entry_assembly, "_fetch_synonyms", lambda v: [])


# ============================================
# 全缺数 → 段灰；⑦ 参见缺则省略段
# ============================================

class TestAllMissing:
    def test_all_missing_yields_six_gray_sections(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        sections = _assembly_sections("run")
        assert len(sections) == 6  # ⑦ 参见缺数 → 整段省略
        for sec in sections:
            assert isinstance(sec, Section)
            assert sec.body is None, f"{sec.title} 不应有正文"
            assert sec.missing_reason.strip(), f"{sec.title} 缺数原因不能为空"
            assert sec.images == ()
        titles = [sec.title for sec in sections]
        for i, mark in enumerate(("①", "②", "③", "④", "⑤", "⑥")):
            assert titles[i].startswith(mark)

    def test_no_see_also_section_when_no_synonyms(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        titles = [s.title for s in _assembly_sections("run")]
        assert not any(t.startswith("⑦") for t in titles)

    def test_missing_reason_says_what_and_why(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        sections = _assembly_sections("run")
        assert "definitions" in sections[0].missing_reason
        assert "oald_senses" in sections[1].missing_reason

    def test_invalid_verb_yields_six_gray_sections(self, monkeypatch):
        _patch_all_missing(monkeypatch)  # 非法词目不应触发任何取数
        for bad in ("", "   ", None):
            sections = _assembly_sections(bad)
            assert len(sections) == 6
            assert all(s.body is None for s in sections)
            assert all("非法" in s.missing_reason for s in sections)


# ============================================
# ⑦ 参见：同簇近义，缺则省略
# ============================================

class TestSeeAlso:
    def test_see_also_present_with_synonyms(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_synonyms",
                            lambda v: ["dash", "jog", "sprint"])
        sections = _assembly_sections("run")
        assert len(sections) == 7
        last = sections[-1]
        assert last.title.startswith("⑦")
        assert "dash" in last.body and "sprint" in last.body
        assert "3" in last.body  # 共 3 词
        assert last.missing_reason == ""

    def test_see_also_truncates_long_lists(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_synonyms",
                            lambda v: [f"v{i:02d}" for i in range(60)])
        last = _assembly_sections("run")[-1]
        assert "v49" in last.body and "v50" not in last.body
        assert "共 60 词" in last.body

    def test_see_also_escapes_member_names(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_synonyms",
                            lambda v: ["<b>dash</b>"])
        last = _assembly_sections("run")[-1]
        assert "&lt;b&gt;dash&lt;/b&gt;" in last.body
        assert "<b>dash</b>" not in last.body


# ============================================
# ① 头块
# ============================================

class TestHeaderSection:
    def _row(self, **over):
        row = {
            "id": 12, "verb": "run", "phonetic": "/rʌn/",
            "chinese_ndef": "跑；奔跑", "en_ndef": "to move fast on foot",
            "definition_source": "dictionary.db", "source_rank": 1,
            "cluster_id": 3,
        }
        row.update(over)
        return row

    def test_header_renders_phonetic_and_grade(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_definition_row", lambda v: self._row())
        head = _assembly_sections("run")[0]
        assert head.body is not None
        assert "run" in head.body
        assert "/rʌn/" in head.body
        assert "词性 v." in head.body
        assert "第 1 级 · dictionary.db" in head.body
        assert "source_rank=1" in head.body
        assert "跑；奔跑" in head.body

    def test_header_missing_phonetic_and_unknown_source(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(
            entry_assembly, "_fetch_definition_row",
            lambda v: self._row(phonetic=None, definition_source="mystery",
                                source_rank=None))
        head = _assembly_sections("run")[0]
        assert "音标暂缺" in head.body
        assert "未登记来源「mystery」" in head.body
        assert "source_rank" not in head.body

    def test_header_missing_row_is_gray(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        head = _assembly_sections("run")[0]
        assert head.body is None
        assert "definitions" in head.missing_reason

    def test_header_escapes_definition_html(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(
            entry_assembly, "_fetch_definition_row",
            lambda v: self._row(chinese_ndef="<script>alert(1)</script>跑",
                                en_ndef="<b>move</b> & fast"))
        head = _assembly_sections("run")[0]
        assert "&lt;script&gt;" in head.body
        assert "<script>" not in head.body
        assert "&lt;b&gt;move&lt;/b&gt; &amp; fast" in head.body


# ============================================
# ② 义项区：coverage 建模 / 沿用 OALD / merged
# ============================================

def _sense(index, definition="to move using your legs", grammar="intransitive"):
    return {"id": 100 + index, "sense_index": index, "definition": definition,
            "grammar": grammar, "examples": [], "is_idiom": 0}


class TestSensesSection:
    def test_no_senses_is_gray(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        sec = _assembly_sections("run")[1]
        assert sec.body is None
        assert "oald_senses" in sec.missing_reason

    def test_unmapped_sense_tagged_yan_yong(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        sec = _assembly_sections("run")[1]
        assert "〔沿用 OALD〕" in sec.body
        assert "to move using your legs" in sec.body
        assert "语法码 intransitive" in sec.body

    def test_mapped_sense_tagged_jian_mo_with_template(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": "足部奔跑义",
                                   "status": "保留", "merged_into": None}})
        monkeypatch.setattr(entry_assembly, "_derive_engine_schema", lambda cat, lang: [])
        monkeypatch.setattr(entry_assembly, "_fetch_template",
                            lambda code, lang, cid, schema:
                            {"template_text": "主体以双足交替…沿路径位移"})
        sec = _assembly_sections("run")[1]
        assert "〔建模〕" in sec.body
        assert "cs_senses #33" in sec.body
        assert "足部奔跑义" in sec.body
        assert "模板释义：主体以双足交替…沿路径位移" in sec.body
        assert "OALD 释义：to move using your legs" in sec.body

    def test_mapped_sense_without_template_notes_honestly(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(entry_assembly, "_derive_engine_schema", lambda cat, lang: [])
        monkeypatch.setattr(entry_assembly, "_fetch_template",
                            lambda code, lang, cid, schema: None)
        sec = _assembly_sections("run")[1]
        assert "〔建模〕" in sec.body
        assert "模板释义未产出" in sec.body

    def test_category_not_loaded_all_senses_yan_yong(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1), _sense(2)])
        sec = _assembly_sections("run")[1]
        assert "未灌入范畴深挖库" in sec.body
        assert sec.body.count("沿用 OALD") >= 2

    def test_mapped_sense_still_yan_yong_when_category_missing(self, monkeypatch):
        """映射依赖范畴代号：范畴未灌时无从映射，如实按沿用渲染。"""
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        sec = _assembly_sections("run")[1]
        assert "〔沿用 OALD〕" in sec.body
        assert "cs_senses #" not in sec.body

    def test_merged_sense_shows_target(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": "merged", "merged_into": 47}})
        sec = _assembly_sections("run")[1]
        assert "建模 · 已并入 → #47" in sec.body

    def test_merged_sense_without_target_does_not_guess(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": "merged", "merged_into": None}})
        sec = _assembly_sections("run")[1]
        assert "已并入（去向待补录）" in sec.body

    def test_sense_definition_is_escaped(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1, definition="<em>run</em> & go")])
        sec = _assembly_sections("run")[1]
        assert "&lt;em&gt;run&lt;/em&gt; &amp; go" in sec.body
        assert "<em>" not in sec.body


# ============================================
# ③ 例证区：仅发布态；空 → 暂无发布例证
# ============================================

def _example(content="He ran across the field.", source="corpus", caption=""):
    return {"id": 1, "sense_ref": "33", "content": content, "source": source,
            "caption": caption, "status": "发布"}


class TestExamplesSection:
    def _setup(self, monkeypatch, examples):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(entry_assembly, "_fetch_published_examples",
                            lambda ref: list(examples))

    def test_published_examples_rendered(self, monkeypatch):
        self._setup(monkeypatch, [_example(),
                                  _example("The dog ran off.", "adapted", "改写自语料")])
        sec = _assembly_sections("run")[2]
        assert sec.body is not None
        assert "He ran across the field." in sec.body
        assert "〔语料例〕" in sec.body
        assert "The dog ran off." in sec.body
        assert "〔改写例〕" in sec.body
        assert "说明：改写自语料" in sec.body
        assert "cs_senses #33" in sec.body

    def test_composed_source_label(self, monkeypatch):
        self._setup(monkeypatch, [_example("She composed a run.", "composed")])
        sec = _assembly_sections("run")[2]
        assert "〔自拟例〕" in sec.body

    def test_no_published_examples_at_all_is_gray(self, monkeypatch):
        """整体无发布例证 → 灰段（缺数原因含「暂无发布例证」口径）。"""
        self._setup(monkeypatch, [])
        sec = _assembly_sections("run")[2]
        assert sec.body is None
        assert "暂无发布例证" in sec.missing_reason

    def test_mixed_senses_show_per_sense_note(self, monkeypatch):
        """部分义项有发布例证、部分没有 → 正文逐义项如实标注。"""
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1), _sense(2)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None},
                             "2": {"id": 34, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(
            entry_assembly, "_fetch_published_examples",
            lambda ref: [_example()] if ref == "33" else [])
        sec = _assembly_sections("run")[2]
        assert sec.body is not None
        assert "He ran across the field." in sec.body
        assert "cs_senses #34）：暂无发布例证" in sec.body

    def test_all_examples_unpublished_is_gray(self, monkeypatch):
        """数据层只回发布态（装配口径）；空清单 → 整段灰、缺数原因含口径。"""
        self._setup(monkeypatch, [])
        monkeypatch.setattr(
            entry_assembly, "_fetch_published_examples", lambda ref: [])
        sec = _assembly_sections("run")[2]
        assert sec.body is None
        assert "暂无发布例证" in sec.missing_reason
        assert "候选" in sec.missing_reason

    def test_no_mapped_senses_is_gray(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        sec = _assembly_sections("run")[2]
        assert sec.body is None
        assert "沿用 OALD" in sec.missing_reason or "未灌" in sec.missing_reason

    def test_example_content_escaped(self, monkeypatch):
        self._setup(monkeypatch, [_example("<img src=x>he ran", "corpus",
                                           "cap<script>")])
        sec = _assembly_sections("run")[2]
        assert "&lt;img src=x&gt;he ran" in sec.body
        assert "cap&lt;script&gt;" in sec.body
        assert "<img" not in sec.body and "<script>" not in sec.body


# ============================================
# ④ 对译区：三态渲染
# ============================================

class TestTranslationsSection:
    def _setup(self, monkeypatch, translation):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(entry_assembly, "_fetch_translation",
                            lambda ref: translation)

    def test_full_state(self, monkeypatch):
        self._setup(monkeypatch, {"state": "full", "equivalent": "跑",
                                  "note": "", "paraphrase": None,
                                  "finalized_by": 7})
        sec = _assembly_sections("run")[3]
        assert "【完全对应】等价词：跑" in sec.body
        assert "定稿人 #7" in sec.body

    def test_partial_state_with_note(self, monkeypatch):
        self._setup(monkeypatch, {"state": "partial", "equivalent": "奔跑",
                                  "note": "多指人或动物快速跑", "paraphrase": None,
                                  "finalized_by": None})
        sec = _assembly_sections("run")[3]
        assert "【部分对应】等价词：奔跑（括注：多指人或动物快速跑）" in sec.body
        assert "系统登记" in sec.body

    def test_partial_state_without_note_flags_honestly(self, monkeypatch):
        self._setup(monkeypatch, {"state": "partial", "equivalent": "奔跑",
                                  "note": "", "paraphrase": None,
                                  "finalized_by": None})
        sec = _assembly_sections("run")[3]
        assert "括注未填" in sec.body

    def test_none_state_renders_paraphrase(self, monkeypatch):
        self._setup(monkeypatch, {"state": "none", "equivalent": "",
                                  "note": "", "paraphrase": "指快速双腿交替移动",
                                  "finalized_by": 3})
        sec = _assembly_sections("run")[3]
        assert "【无对应】释义翻译：指快速双腿交替移动" in sec.body
        assert "等价词" not in sec.body

    def test_none_state_without_paraphrase_flags_honestly(self, monkeypatch):
        self._setup(monkeypatch, {"state": "none", "equivalent": "",
                                  "note": "", "paraphrase": None,
                                  "finalized_by": None})
        sec = _assembly_sections("run")[3]
        assert "释义翻译未填" in sec.body

    def test_no_finalized_translation_at_all_is_gray(self, monkeypatch):
        self._setup(monkeypatch, None)
        sec = _assembly_sections("run")[3]
        assert sec.body is None
        assert "对译定稿" in sec.missing_reason

    def test_mixed_senses_show_unfinalized_note(self, monkeypatch):
        """部分义项已定稿、部分未定稿 → 正文逐义项如实标注。"""
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1), _sense(2)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None},
                             "2": {"id": 34, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(
            entry_assembly, "_fetch_translation",
            lambda ref: ({"state": "full", "equivalent": "跑", "note": "",
                          "paraphrase": None, "finalized_by": 1}
                         if ref == "33" else None))
        sec = _assembly_sections("run")[3]
        assert sec.body is not None
        assert "【完全对应】等价词：跑" in sec.body
        assert "cs_senses #34）· 对译未定稿" in sec.body

    def test_no_mapped_senses_is_gray(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        sec = _assembly_sections("run")[3]
        assert sec.body is None

    def test_all_unfinalized_is_gray(self, monkeypatch):
        self._setup(monkeypatch, None)
        monkeypatch.setattr(entry_assembly, "_fetch_translation", lambda ref: None)
        sec = _assembly_sections("run")[3]
        assert sec.body is None
        assert "对译定稿" in sec.missing_reason

    def test_translation_equivalent_escaped(self, monkeypatch):
        self._setup(monkeypatch, {"state": "full", "equivalent": "<b>跑</b>",
                                  "note": "", "paraphrase": None,
                                  "finalized_by": None})
        sec = _assembly_sections("run")[3]
        assert "&lt;b&gt;跑&lt;/b&gt;" in sec.body


# ============================================
# ⑤ 多模态区：发布态绑定、图片内嵌、音视频文本
# ============================================

def _binding(kind="image", purpose="illustration", binding_status="发布",
             asset_status="发布", path="data/media/image/a.png", **over):
    row = {"binding_id": 1, "asset_id": 2, "anchor_type": "sense",
           "anchor_id": 101, "purpose": purpose, "caption": "奔跑示意图",
           "sort_order": 0, "binding_status": binding_status, "kind": kind,
           "file_path": path, "mime": "image/png", "sha256": "x",
           "source": "tests", "license": "CC BY 4.0", "size_bytes": 10,
           "asset_status": asset_status, "created_at": None}
    row.update(over)
    return row


class TestMediaSection:
    def _setup(self, monkeypatch, by_anchor):
        """by_anchor: {(anchor_type, anchor_id): [bindings]}"""
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_definition_row",
                            lambda v: {"id": 12, "verb": "run"})
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(
            entry_assembly, "_fetch_media_for_anchor",
            lambda anchor_type, anchor_id: by_anchor.get((anchor_type, anchor_id), []))

    def test_published_image_goes_to_images_tuple(self, monkeypatch):
        self._setup(monkeypatch, {("sense", 101): [_binding()]})
        sec = _assembly_sections("run")[4]
        assert sec.body is not None
        assert "释义配图" in sec.body
        assert "data/media/image/a.png" in sec.body
        assert "图注：奔跑示意图" in sec.body
        assert "许可：CC BY 4.0" in sec.body
        assert len(sec.images) == 1
        assert sec.images[0]["file_path"] == "data/media/image/a.png"

    def test_word_anchor_group_label(self, monkeypatch):
        self._setup(monkeypatch, {("word", 12): [_binding(purpose="pronunciation",
                                                          kind="audio",
                                                          path="data/media/audio/a.mp3")]})
        sec = _assembly_sections("run")[4]
        assert "词目锚（definitions #12）" in sec.body
        assert "音频 · 发音" in sec.body
        assert sec.images == ()  # 音频不内嵌

    def test_candidate_binding_filtered_out(self, monkeypatch):
        self._setup(monkeypatch, {("sense", 101): [_binding(binding_status="候选"),
                                                   _binding(binding_status="审定")]})
        sec = _assembly_sections("run")[4]
        assert sec.body is None  # 只消费发布态绑定
        assert "发布" in sec.missing_reason

    def test_published_binding_with_unpublished_asset_noted(self, monkeypatch):
        self._setup(monkeypatch, {("sense", 101): [_binding(asset_status="审定")]})
        sec = _assembly_sections("run")[4]
        assert "资产审定态 审定（绑定已发布，资产未发布）" in sec.body

    def test_no_bindings_is_gray(self, monkeypatch):
        self._setup(monkeypatch, {})
        sec = _assembly_sections("run")[4]
        assert sec.body is None
        assert "媒体库" in sec.missing_reason

    def test_no_definition_row_still_uses_sense_anchor(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(
            entry_assembly, "_fetch_media_for_anchor",
            lambda anchor_type, anchor_id: (
                [_binding()] if anchor_type == "sense" and anchor_id == 101 else []))
        sec = _assembly_sections("run")[4]
        assert "义项 S1 锚（oald_senses #101）" in sec.body

    def test_image_preview_capped_at_limit(self, monkeypatch):
        bindings = [_binding(path=f"data/media/image/{i}.png", caption=f"图{i}")
                    for i in range(9)]
        self._setup(monkeypatch, {("sense", 101): bindings})
        sec = _assembly_sections("run")[4]
        assert len(sec.images) == entry_assembly._IMAGES_SHOW_LIMIT
        assert "图片共 9 张" in sec.body
        assert "预览内嵌前" in sec.body

    def test_media_path_escaped(self, monkeypatch):
        self._setup(monkeypatch, {("sense", 101): [_binding(
            path='data/media/image/<x>&".png')]})
        sec = _assembly_sections("run")[4]
        assert "&lt;x&gt;&amp;&quot;.png" in sec.body


# ============================================
# ⑥ 定制属性
# ============================================

class TestCustomValuesSection:
    def _setup(self, monkeypatch, values, row=None):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_definition_row",
                            lambda v: row if row is not None else {"id": 12})
        monkeypatch.setattr(entry_assembly, "_fetch_custom_values",
                            lambda anchor_type, anchor_id: list(values))

    def test_values_rendered_with_field_meta(self, monkeypatch):
        self._setup(monkeypatch, [
            {"code": "register", "name": "语域", "value_text": "口语",
             "value_num": None, "field_status": "active"},
            {"code": "freq", "name": "频级", "value_text": None,
             "value_num": 3, "field_status": "active"},
        ])
        sec = _assembly_sections("run")[5]
        assert "语域（register）＝ 口语" in sec.body
        assert "频级（freq）＝ 3" in sec.body
        assert "已弃用" not in sec.body

    def test_deprecated_field_noted(self, monkeypatch):
        self._setup(monkeypatch, [
            {"code": "grade", "name": "教材分级", "value_text": "B1",
             "value_num": None, "field_status": "deprecated"},
        ])
        sec = _assembly_sections("run")[5]
        assert "（字段已弃用，存量值只读）" in sec.body

    def test_empty_value_honest(self, monkeypatch):
        self._setup(monkeypatch, [
            {"code": "register", "name": "语域", "value_text": "",
             "value_num": None, "field_status": "active"},
        ])
        sec = _assembly_sections("run")[5]
        assert "＝ （空值）" in sec.body

    def test_no_values_is_gray(self, monkeypatch):
        self._setup(monkeypatch, [])
        sec = _assembly_sections("run")[5]
        assert sec.body is None
        assert "定制属性" in sec.missing_reason

    def test_no_definition_row_is_gray(self, monkeypatch):
        self._setup(monkeypatch, [], row=None)
        monkeypatch.setattr(entry_assembly, "_fetch_definition_row", lambda v: None)
        sec = _assembly_sections("run")[5]
        assert sec.body is None
        assert "无词目锚" in sec.missing_reason

    def test_value_escaped(self, monkeypatch):
        self._setup(monkeypatch, [
            {"code": "reg", "name": "<b>语域</b>", "value_text": "口语<script>",
             "value_num": None, "field_status": "active"},
        ])
        sec = _assembly_sections("run")[5]
        assert "&lt;b&gt;语域&lt;/b&gt;" in sec.body
        assert "口语&lt;script&gt;" in sec.body


# ============================================
# 脏数据 / 取数抛异常 → 段灰不崩
# ============================================

class TestDegradation:
    def test_adapter_exceptions_collapse_to_gray(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("db down")
        monkeypatch.setattr(entry_assembly, "_fetch_definition_row", _boom)
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses", _boom)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes", _boom)
        monkeypatch.setattr(entry_assembly, "_fetch_synonyms", _boom)
        sections = _assembly_sections("run")
        assert len(sections) == 6
        assert sections[0].body is None and sections[1].body is None

    def test_section_constructor_exception_collapses_to_gray(self, monkeypatch):
        """段构造内取数抛异常 → 该段灰段，其余段照常。"""
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None}})

        def _boom(ref):
            raise RuntimeError("boom")
        monkeypatch.setattr(entry_assembly, "_fetch_published_examples", _boom)
        sections = _assembly_sections("run")
        assert sections[2].body is None  # 例证段灰
        assert "异常" in sections[2].missing_reason
        assert sections[0].title.startswith("①")  # 其余段照常构造

    def test_data_layer_wrappers_swallow_exceptions(self, monkeypatch):
        """适配层对数据层函数抛异常自兜底（数据层自身已降级外的防御一层）。"""
        def _boom(*a, **k):
            raise RuntimeError("x")
        monkeypatch.setattr(mysql_db, "get_oald_senses", _boom)
        monkeypatch.setattr(mysql_db, "get_synonyms", _boom)
        monkeypatch.setattr(lexical_db, "list_examples", _boom)
        monkeypatch.setattr(lexical_db, "get_translation", _boom)
        monkeypatch.setattr(media_db, "list_assets_for_anchor", _boom)
        monkeypatch.setattr(entry_assembly, "get_values_for_anchor", _boom)
        monkeypatch.setattr(entry_assembly, "derive_cluster_schemas", _boom)
        monkeypatch.setattr(entry_assembly, "instantiate_template", _boom)
        assert entry_assembly._fetch_oald_senses("run") == []
        assert entry_assembly._fetch_synonyms("run") == []
        assert entry_assembly._fetch_published_examples("33") == []
        assert entry_assembly._fetch_translation("33") is None
        assert entry_assembly._fetch_media_for_anchor("sense", 101) == []
        assert entry_assembly._fetch_custom_values("word", 12) == []
        assert entry_assembly._derive_engine_schema("RUN", "en") == []
        assert entry_assembly._fetch_template("RUN", "en", 33, None) is None

    def test_cs_map_query_falls_back_without_status_columns(self, monkeypatch):
        """迁移未跑（无 status/merged_into 列）→ 降级为不带状态列重查。"""
        class _Cursor:
            def __init__(self, sql_first):
                self.sql_first = sql_first

            def execute(self, sql, params=None):
                assert "%s" in sql and params == ("RUN", "en", "run")  # 参数化
                self.has_status = "status" in sql

            def fetchall(self):
                if getattr(self, "has_status", False):
                    raise RuntimeError("Unknown column 'status'")
                return [{"id": 33, "sense_no": "1", "sense_label": "足部奔跑义"}]

        entered = []

        class _Ctx:
            def __enter__(self):
                entered.append(1)
                return _Cursor(entered)

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(entry_assembly, "get_db_cursor", lambda: _Ctx())
        mapping = entry_assembly._fetch_cs_sense_map("RUN", "en", "run")
        assert mapping["1"]["id"] == 33
        assert "status" not in mapping["1"]  # 降级行不带状态（coverage 不猜 merged）

    def test_cs_map_all_queries_fail_returns_empty(self, monkeypatch):
        def _boom():
            raise RuntimeError("db down")
        monkeypatch.setattr(entry_assembly, "get_db_cursor", _boom)
        assert entry_assembly._fetch_cs_sense_map("RUN", "en", "run") == {}


# ============================================
# 纯函数
# ============================================

class TestPureFunctions:
    def test_clean_verb(self):
        assert _clean_verb(None) == ""
        assert _clean_verb("  run ") == "run"
        assert _clean_verb(42) == "42"
        assert len(_clean_verb("v" * 300)) == 100

    def test_truncate(self):
        assert _truncate(None) == ""
        assert _truncate("abc") == "abc"
        assert _truncate("x" * 200, 10) == "x" * 10 + "…"
        assert _truncate(123) == "123"

    def test_format_source_grade_known_sources(self):
        for source, expect in (
            ("dictionary.db", "第 1 级"),
            ("legacy-library", "第 2 级"),
            ("levin-brief", "第 3 级"),
            ("oxford-en", "第 4 级"),
            ("pending", "第 5 级"),
        ):
            text = _format_source_grade({"definition_source": source,
                                         "source_rank": None})
            assert expect in text

    def test_format_source_grade_unknown_and_rank(self):
        text = _format_source_grade({"definition_source": "who-knows",
                                     "source_rank": 9})
        assert "未登记来源「who-knows」" in text
        assert "source_rank=9" in text
        empty = _format_source_grade({"definition_source": None,
                                      "source_rank": None})
        assert "来源未登记" in empty

    def test_coverage_tag(self):
        assert _coverage_tag(None) == "沿用 OALD"
        assert _coverage_tag({}) == "沿用 OALD"
        assert _coverage_tag({"id": None}) == "沿用 OALD"
        assert _coverage_tag({"id": 5}) == "建模"
        assert _coverage_tag({"id": 5, "status": "保留"}) == "建模"
        assert _coverage_tag({"id": 5, "status": "MERGED",
                              "merged_into": 9}) == "建模 · 已并入 → #9"
        assert _coverage_tag({"id": 5, "status": " merged ",
                              "merged_into": None}) == "建模 · 已并入（去向待补录）"
        assert _coverage_tag({"id": 5, "status": "merged",
                              "merged_into": "bad"}) == "建模 · 已并入（去向待补录）"

    def test_translation_line_states(self):
        assert "对译未定稿" in _translation_line(None)
        full = _translation_line({"state": "full", "equivalent": "跑",
                                  "note": "x", "paraphrase": None})
        assert "【完全对应】等价词：跑" in full and "括注" not in full
        partial = _translation_line({"state": "partial", "equivalent": "奔跑",
                                     "note": "多指人", "paraphrase": None})
        assert "【部分对应】等价词：奔跑（括注：多指人）" in partial
        none_state = _translation_line({"state": "none", "equivalent": "跑",
                                        "note": "", "paraphrase": "释义…"})
        assert "【无对应】释义翻译：释义…" in none_state
        unknown = _translation_line({"state": "weird", "equivalent": "x",
                                     "note": "", "paraphrase": None})
        assert "【weird】" in unknown
        empty_eq = _translation_line({"state": "full", "equivalent": "",
                                      "note": "", "paraphrase": None})
        assert "等价词未填" in empty_eq

    def test_example_line(self):
        line = _example_line({"content": "He ran.", "source": "corpus",
                              "caption": "enTenTen21"})
        assert "He ran.〔语料例〕" in line and "说明：enTenTen21" in line
        bare = _example_line({"content": "X", "source": "alien", "caption": ""})
        assert "〔alien〕" in bare and "说明" not in bare
        blank = _example_line({"content": "", "source": "corpus", "caption": ""})
        assert "例证文本为空" in blank

    def test_media_line(self):
        row = _binding()
        line = _media_line(row)
        assert "图片 · 释义配图 · data/media/image/a.png" in line
        assert "图注：奔跑示意图" in line and "许可：CC BY 4.0" in line
        unpublished = _media_line(_binding(asset_status="候选"))
        assert "资产审定态 候选" in unpublished
        published_asset = _media_line(_binding(asset_status="发布"))
        assert "资产审定态" not in published_asset

    def test_custom_value_text(self):
        assert _custom_value_text({"value_num": 3.0, "value_text": None}) == "3"
        assert _custom_value_text({"value_num": None, "value_text": "口语"}) == "口语"
        assert _custom_value_text({"value_num": None, "value_text": ""}) == "（空值）"

    def test_study_code_for(self):
        assert _study_code_for("RUN", ["RUN", "HIT"]) == "RUN"
        assert _study_code_for("run", ["RUN"]) == "RUN"  # 大小写不敏感直配
        assert _study_code_for("motion", ["RUN"]) == "RUN"  # 包名映射
        assert _study_code_for("motion", []) is None
        assert _study_code_for("unknown", ["RUN"]) is None
        assert _study_code_for("", ["RUN"]) is None
        assert _study_code_for(None, ["RUN"]) is None


# ============================================
# 编排层：段序与取数联动
# ============================================

class TestOrchestration:
    def test_full_data_yields_seven_sections_in_order(self, monkeypatch):
        _patch_all_missing(monkeypatch)
        monkeypatch.setattr(entry_assembly, "_fetch_definition_row",
                            lambda v: {"id": 12, "verb": "run",
                                       "phonetic": "/rʌn/",
                                       "chinese_ndef": "跑",
                                       "en_ndef": "to move fast",
                                       "definition_source": "dictionary.db",
                                       "source_rank": 1, "cluster_id": 3})
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(entry_assembly, "_derive_engine_schema", lambda cat, lang: [])
        monkeypatch.setattr(entry_assembly, "_fetch_template",
                            lambda code, lang, cid, schema: {"template_text": "模板"})
        monkeypatch.setattr(entry_assembly, "_fetch_published_examples",
                            lambda ref: [_example()])
        monkeypatch.setattr(entry_assembly, "_fetch_translation",
                            lambda ref: {"state": "full", "equivalent": "跑",
                                         "note": "", "paraphrase": None,
                                         "finalized_by": 1})
        monkeypatch.setattr(entry_assembly, "_fetch_media_for_anchor",
                            lambda t, i: [_binding()] if (t, i) == ("sense", 101) else [])
        monkeypatch.setattr(entry_assembly, "_fetch_custom_values",
                            lambda t, i: [{"code": "reg", "name": "语域",
                                           "value_text": "口语", "value_num": None,
                                           "field_status": "active"}])
        monkeypatch.setattr(entry_assembly, "_fetch_synonyms",
                            lambda v: ["dash", "sprint"])
        sections = _assembly_sections("run")
        marks = ("①", "②", "③", "④", "⑤", "⑥", "⑦")
        assert [s.title[:1] for s in sections] == list(marks)
        assert all(s.body is not None for s in sections), \
            "全数据场景不应有灰段"
        assert sections[4].images  # 多模态区图片位有发布态图片

    def test_cs_map_and_examples_receive_cs_id_string(self, monkeypatch):
        """sense_ref 以 cs_senses.id 字符串传给例证/对译取数（编纂域软引用口径）。"""
        _patch_all_missing(monkeypatch)
        seen = {}
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 77, "sense_label": None,
                                   "status": None, "merged_into": None}})

        def _examples(ref):
            seen["examples"] = ref
            return []
        monkeypatch.setattr(entry_assembly, "_fetch_published_examples", _examples)

        def _trans(ref):
            seen["translation"] = ref
            return None
        monkeypatch.setattr(entry_assembly, "_fetch_translation", _trans)
        monkeypatch.setattr(entry_assembly, "_fetch_synonyms", lambda v: ["x"])
        _assembly_sections("run")
        assert seen["examples"] == "77"
        assert seen["translation"] == "77"

    def test_template_receives_study_code_as_category(self, monkeypatch):
        """模板实例化以研究代号为范畴参数（义项脊柱同口径）。"""
        _patch_all_missing(monkeypatch)
        seen = {}
        monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                            lambda: ["RUN"])
        monkeypatch.setattr(entry_assembly, "_fetch_oald_senses",
                            lambda v: [_sense(1)])
        monkeypatch.setattr(entry_assembly, "_fetch_cs_sense_map",
                            lambda code, lang, lemma:
                            {"1": {"id": 33, "sense_label": None,
                                   "status": None, "merged_into": None}})
        monkeypatch.setattr(entry_assembly, "_derive_engine_schema",
                            lambda cat, lang: seen.setdefault("schema_args", (cat, lang)) or [])
        monkeypatch.setattr(
            entry_assembly, "_fetch_template",
            lambda code, lang, cid, schema:
            seen.setdefault("template_args", (code, lang, cid)) or None)
        _assembly_sections("run", category="motion", language="en")
        assert seen["schema_args"] == ("RUN", "en")
        assert seen["template_args"] == ("RUN", "en", 33)


# ============================================
# 渲染入口：非 Streamlit 运行时不做渲染级测试（义项脊柱测试同口径），
# 仅锁定入口在模块中定义且纯编排可独立调用（上面已覆盖）。
# ============================================

def test_render_entry_is_importable_and_docstring_points_to_contract():
    assert callable(render_entry_assembly)
    assert "工序 14" in (inspect.getmodule(render_entry_assembly).__doc__ or "")
