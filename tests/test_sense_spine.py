"""义项脊柱模块单元测试（批次 4 Agent M，施工规范 §7；批次 6 扩 merged 收口）。

不依赖数据库：脊柱七段的取数一律经 src/sense_spine.py 模块级 _fetch_* /
_resolve_* 薄适配层，测试 monkeypatch 这些名字构造三种场景 ——
  * 全缺数 → 七段全灰（body None，缺数原因非空）；
  * 部分有数 → 对应段渲染文本（标题、关键字段在场）；
  * 脏数据/取数抛异常 → 不崩，整段折叠为灰段或降级文本。
纯函数（payload 摘要、α 展示、JSON 容错、范畴代号解析）与媒体库表单
校验纯函数（license 必填判定、单步流转表、字节格式化、文件指纹）直接测。
渲染入口需要 Streamlit 运行时，按批次 2 契约同口径不做渲染级测试
（页面已由词条浏览器 expander 懒加载接线，源码级断言在场）。

批次 6（G3 merged 消费收口，施工规范 §9）：cs_senses.status='merged' 的
义位 —— merged 去向文案核（_merged_target_suffix 纯函数：大小写/空白容错、
去向缺失不猜 id）＋ 七段编排（① 段「已并入 → #N」警示、④⑤ 段
「已并入，不参与聚类/模板」占位且不再触发簇信息查询/模板实例化、现状取
不到或映射失败按普通义位渲染）。merged 状态经 _fetch_cs_sense_state
薄适配层取，测试同口径 monkeypatch。
"""
import inspect
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import data_pages, dict_admin_pages, media_db, sense_spine  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    _format_bytes,
    _media_register_error,
    _next_media_status,
    _sha256_file,
)
from src.sense_spine import (  # noqa: E402
    SpineSection,
    _format_alpha,
    _parse_json_dict,
    _parse_json_list,
    _payload_summary,
    _spine_sections,
    _study_code_for,
    _tier_label,
    _truncate,
    render_sense_spine,
)


# ============================================
# 模块契约：入口签名与七段顺序
# ============================================

class TestModuleContract:
    def test_render_entry_signature(self):
        """契约 §7-M：render_sense_spine(sense_id, category="motion", language="en")。"""
        sig = inspect.signature(render_sense_spine)
        params = list(sig.parameters.values())
        assert params[0].name == "sense_id"
        assert params[1].name == "category" and params[1].default == "motion"
        assert params[2].name == "language" and params[2].default == "en"

    def test_browser_page_wires_spine(self):
        """词条浏览器义项 expander 已接脊柱（源码级断言：懒加载在 data_pages）。"""
        source = inspect.getsource(data_pages)
        assert "render_sense_spine" in source
        assert "义项脊柱" in source
        assert 'on_change="rerun"' in source  # expander 懒加载（点开才渲染）

    def test_browser_guide_mentions_spine(self):
        """GUIDE 行文含「展开即见义项脊柱」（契约：GUIDE notes 同步）。"""
        full_text = "".join(
            "".join(data_pages.GUIDE[key])
            for key in ("purpose", "principle", "data_source", "steps", "notes")
        )
        assert "展开即见义项脊柱" in full_text

    def test_dict_admin_guide_covers_media(self):
        """媒体库 GUIDE 条目在场（「数据资产归词典管理员」口径）。"""
        full_text = "".join(
            "".join(dict_admin_pages.GUIDE[key])
            for key in ("purpose", "principle", "data_source", "steps", "notes")
        )
        assert "媒体库" in full_text
        assert "词典管理员" in full_text
        assert "license" in full_text or "许可" in full_text

    def test_media_tab_is_seventh(self):
        """七 tab：🖼️ 媒体库 在末位（st.tabs 清单源码级断言）。"""
        source = inspect.getsource(dict_admin_pages.render_dict_admin_page)
        tab_list = source[source.index("st.tabs("):]
        assert "🖼️ 媒体库" in tab_list
        assert tab_list.index("🖼️ 媒体库") > tab_list.index("📋 任务分配")


# ============================================
# 七段编排：全缺数 → 全灰
# ============================================

def _patch_all_missing(monkeypatch):
    """全部取数适配层 → 空库口径（义位行不存在、各数据层返回空）。"""
    monkeypatch.setattr(sense_spine, "_fetch_sense_row", lambda sid: None)
    monkeypatch.setattr(sense_spine, "_fetch_submissions", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_latest_reliability", lambda cat: [])
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: [])
    monkeypatch.setattr(sense_spine, "_fetch_media", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_custom_values", lambda sid: [])


def test_all_missing_yields_seven_gray_sections(monkeypatch):
    _patch_all_missing(monkeypatch)
    sections = _spine_sections(101)
    assert len(sections) == 7
    for sec in sections:
        assert isinstance(sec, SpineSection)
        assert sec.body is None, f"{sec.title} 不应有正文"
        assert sec.missing_reason.strip(), f"{sec.title} 缺数原因不能为空"
    titles = [sec.title for sec in sections]
    assert titles[0].startswith("①")
    assert titles[1].startswith("②")
    assert titles[2].startswith("③")
    assert titles[3].startswith("④")
    assert titles[4].startswith("⑤")
    assert titles[5].startswith("⑥")
    assert titles[6].startswith("⑦")


def test_invalid_sense_id_all_gray(monkeypatch):
    _patch_all_missing(monkeypatch)
    for bad in (0, -3, "abc", None, True):
        sections = _spine_sections(bad)
        assert len(sections) == 7
        assert all(sec.body is None for sec in sections)
        assert all("sense_id 非法" in sec.missing_reason for sec in sections)


def test_reliability_header_notes_category_scope():
    """③ 段头固定注明「α 为范畴×任务级，非单义位」（不把范畴 α 冒充单义位）。"""
    _sections = {sec.title for sec in _spine_sections(1, category="motion")}
    assert any("范畴×任务级" in t and "非单义位" in t for t in _sections)


# ============================================
# 七段编排：部分有数 → 对应段渲染文本
# ============================================

def _patch_partial(monkeypatch):
    monkeypatch.setattr(
        sense_spine, "_fetch_sense_row", lambda sid: {
            "id": sid, "sense_index": 3, "definition": "move fast on foot",
            "grammar": "intransitive", "examples": ["She ran home."],
            "sense_group": "move fast", "is_idiom": 0, "verb": "run",
        })
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state", lambda cs_id: None)
    monkeypatch.setattr(
        sense_spine, "_fetch_submissions", lambda sid: [
            {"id": 1, "task_type": "admission", "coder_id": 7,
             "payload": {"admission": "Y", "schema": "PATH", "alignment": "对齐"},
             "ai_assisted": True, "status": "submitted",
             "submitted_at": "2026-11-01 10:00:00",
             "username": "coder_a", "display_name": "标注员甲"},
        ])
    monkeypatch.setattr(
        sense_spine, "_fetch_latest_reliability", lambda cat: [
            {"task_type": "feature_coding", "overall_alpha": 0.75,
             "per_feature": '{"P1":0.82,"P2":0.9}', "n_coders": 2,
             "n_units": 32, "computed_at": "2026-11-02 09:00:00"},
        ])
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: 77)
    monkeypatch.setattr(
        sense_spine, "_fetch_cluster_info", lambda cs_id, lang: {
            "cluster_id": 9, "cluster_no": 2, "cluster_name": "竞速跑簇",
            "cluster_size": 8, "run_id": 4, "version": "预编码"})
    monkeypatch.setattr(
        sense_spine, "_fetch_tier", lambda cat, lang, cs_id: {
            "tier": "prototype", "is_medoid": True, "gower_to_medoid": 0.12})
    monkeypatch.setattr(
        sense_spine, "instantiate_template", lambda cat, lang, sid, **kw: {
            "template_text": "主体快速经路径位移",
            "图式维度": {
                "name": "路径图式", "code": "PATH",
                "cluster_no": 2, "cluster_name": "竞速跑簇"},
            "句法维度": {"transitivity": "不及物"},
            "oald": {"definition": "move fast on foot",
                     "grammar": "intransitive"}})
    monkeypatch.setattr(
        sense_spine, "_fetch_media", lambda sid: [
            {"binding_id": 5, "asset_id": 11, "kind": "image", "purpose":
             "illustration", "caption": "跑步图", "binding_status": "发布",
             "asset_status": "发布", "file_path": "data/img/run.png",
             "license": "CC BY 4.0", "source": "xianhan"}])
    monkeypatch.setattr(
        sense_spine, "_fetch_custom_values", lambda sid: [
            {"code": "register", "name": "语域", "value_text": "通用",
             "value_num": None, "value_type": "text", "field_status": "active"}])


def test_partial_data_sections_render_text(monkeypatch):
    _patch_partial(monkeypatch)
    sections = _spine_sections(101, category="motion", language="en")
    assert len(sections) == 7

    by_code = {sec.title[0]: sec for sec in sections}  # ①…⑦ 单字符段序号
    # ① 义项信息
    s1 = by_code["①"]
    assert s1.body is not None and s1.missing_reason == ""
    assert "S3" in s1.body and "move fast on foot" in s1.body
    assert "intransitive" in s1.body and "She ran home." in s1.body
    # ② 标注留痕
    s2 = by_code["②"]
    assert s2.body is not None
    assert "标注员甲" in s2.body and "义位准入" in s2.body
    assert "准入=Y" in s2.body and "已提交待审" in s2.body
    # ③ 信度
    s3 = by_code["③"]
    assert s3.body is not None
    assert "0.750" in s3.body and "P1=0.820" in s3.body
    assert "非单义位" in s3.title
    # ④ 簇归属
    s4 = by_code["④"]
    assert s4.body is not None
    assert "竞速跑簇" in s4.body and "原型" in s4.body
    assert "medoid" in s4.body
    # ⑤ 模板预览
    s5 = by_code["⑤"]
    assert s5.body is not None
    assert "主体快速经路径位移" in s5.body and "路径图式" in s5.body
    # ⑥ 媒体
    s6 = by_code["⑥"]
    assert s6.body is not None
    assert "run.png" in s6.body and "释义配图" in s6.body
    assert "CC BY 4.0" in s6.body
    # ⑦ 定制属性
    s7 = by_code["⑦"]
    assert s7.body is not None
    assert "语域" in s7.body and "通用" in s7.body


def test_cs_sense_resolution_paths(monkeypatch):
    """④⑤ 共用映射：包名→研究代号→cs_senses.id；三种失败口径如实区分。"""
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: 77)
    row = {"verb": "run", "sense_index": 3}
    cs_id, study_code, reason = sense_spine._resolve_cs_sense(1, "motion", "en", row)
    assert (cs_id, study_code, reason) == (77, "RUN", None)  # motion → RUN
    # 义项行缺失
    _, _, reason = sense_spine._resolve_cs_sense(1, "motion", "en", None)
    assert reason and "义项行不可用" in reason
    # 范畴未灌入
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: [])
    _, _, reason = sense_spine._resolve_cs_sense(1, "motion", "en", row)
    assert reason and "未灌入" in reason
    # 试点库无对应义位
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: None)
    _, _, reason = sense_spine._resolve_cs_sense(1, "motion", "en", row)
    assert reason and "未在建模覆盖内" in reason


def test_not_covered_placeholder_text(monkeypatch):
    """义位不在试点库时 ④⑤ 占位「未在建模覆盖内」（不编簇、不编模板）。"""
    monkeypatch.setattr(
        sense_spine, "_fetch_sense_row",
        lambda sid: {"id": sid, "sense_index": 3, "verb": "run"})
    monkeypatch.setattr(sense_spine, "_fetch_submissions", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_latest_reliability", lambda cat: [])
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: None)
    monkeypatch.setattr(sense_spine, "_fetch_media", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_custom_values", lambda sid: [])
    sections = _spine_sections(101)
    assert "未在建模覆盖内" in sections[3].missing_reason
    assert "未在建模覆盖内" in sections[4].missing_reason


# ============================================
# 批次 6：merged 消费收口（G3 分立复核定稿 → 脊柱警示/占位）
# ============================================

class TestMergedTargetSuffix:
    """_merged_target_suffix：merged 去向文案核（纯函数；去向缺失不猜 id）。"""

    def test_merged_with_target(self):
        assert sense_spine._merged_target_suffix("merged", 77) == "已并入 → #77"

    def test_merged_without_target_no_guess(self):
        text = sense_spine._merged_target_suffix("merged", None)
        assert text is not None
        assert "已并入" in text and "待补录" in text

    def test_non_merged_none(self):
        for status in ("保留", "目标", "split", "", None, 0):
            assert sense_spine._merged_target_suffix(status, 9) is None, status

    def test_whitespace_and_case_tolerant(self):
        # MySQL ci collation 落库值大小写/空白容错
        assert sense_spine._merged_target_suffix(" MERGED ", 5) == "已并入 → #5"

    def test_dirty_target_falls_back(self):
        text = sense_spine._merged_target_suffix("merged", "x")
        assert text is not None and "待补录" in text
        # bool 不是合法 id（_as_int 口径）→ 待补录
        text = sense_spine._merged_target_suffix("merged", True)
        assert text is not None and "待补录" in text


def test_merged_sense_spine_sections(monkeypatch):
    """status='merged'：① 警示 + ④⑤ 占位，且不触发簇信息查询/模板实例化。"""
    _patch_partial(monkeypatch)
    called = {}
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state",
                        lambda cs_id: {"status": "merged", "merged_into": 77})

    def _no_cluster(cs_id, lang):
        called["cluster"] = True
        return {"cluster_id": 9, "cluster_no": 2, "cluster_name": "竞速跑簇",
                "cluster_size": 8, "run_id": 4, "version": "预编码"}

    def _no_template(*a, **k):
        called["template"] = True
        return {"template_text": "merged 义位不应实例化模板"}

    monkeypatch.setattr(sense_spine, "_fetch_cluster_info", _no_cluster)
    monkeypatch.setattr(sense_spine, "instantiate_template", _no_template)
    sections = _spine_sections(101, category="motion", language="en")
    by_code = {sec.title[0]: sec for sec in sections}
    s1, s4, s5 = by_code["①"], by_code["④"], by_code["⑤"]
    # ① 义项信息：警示行在场（含去向与跳转提示）
    assert s1.body is not None
    assert "⚠️ 该义位已并入 → #77（分立复核定稿）" in s1.body
    assert "跳转" in s1.body
    # ④⑤ 占位（「已并入，不参与聚类/模板」口径原文在场）
    assert s4.body is not None
    assert "已并入，不参与聚类" in s4.body and "#77" in s4.body
    assert s5.body is not None
    assert "已并入，不参与模板" in s5.body
    # 消费收口：不触发簇信息查询 / 模板实例化
    assert called == {}


def test_merged_without_target_renders_no_guess(monkeypatch):
    """merged_into 缺失：文案给「去向待补录」，不编目标 id。"""
    _patch_partial(monkeypatch)
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state",
                        lambda cs_id: {"status": "merged", "merged_into": None})
    sections = _spine_sections(101, category="motion", language="en")
    s1 = next(sec for sec in sections if sec.title.startswith("①"))
    assert "已并入" in s1.body and "待补录" in s1.body
    assert "#77" not in s1.body


def test_merged_state_unavailable_renders_normal(monkeypatch):
    """cs_senses 现状取不到（库不可用/无行）→ 按普通义位渲染（不猜 merged）。"""
    _patch_partial(monkeypatch)
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state", lambda cs_id: None)
    sections = _spine_sections(101, category="motion", language="en")
    body_all = "\n".join(sec.body or "" for sec in sections)
    assert "已并入" not in body_all
    # ④⑤ 走正常有数路径（不因 merged 收口丢信息）
    assert "竞速跑簇" in (sections[3].body or "")
    assert "主体快速经路径位移" in (sections[4].body or "")


def test_merged_state_exception_is_contained(monkeypatch):
    """_fetch_cs_sense_state 抛异常 → 折叠为普通渲染，不崩。"""
    _patch_partial(monkeypatch)

    def boom(cs_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state", boom)
    sections = _spine_sections(101, category="motion", language="en")
    assert len(sections) == 7
    assert "竞速跑簇" in (sections[3].body or "")


def test_merged_probe_skipped_when_mapping_fails(monkeypatch):
    """cs 映射失败（未在建模覆盖内）时不查 merged 状态（无 cs_senses.id 可查）。"""
    monkeypatch.setattr(
        sense_spine, "_fetch_sense_row",
        lambda sid: {"id": sid, "sense_index": 3, "verb": "run"})
    monkeypatch.setattr(sense_spine, "_fetch_submissions", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_latest_reliability", lambda cat: [])
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: None)
    probed = []
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state",
                        lambda cs_id: probed.append(cs_id) or None)
    monkeypatch.setattr(sense_spine, "_fetch_media", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_custom_values", lambda sid: [])
    sections = _spine_sections(101)
    assert probed == []
    assert "未在建模覆盖内" in sections[3].missing_reason
    assert "未在建模覆盖内" in sections[4].missing_reason


def test_non_merged_status_untouched(monkeypatch):
    """split/保留 等非 merged 状态：脊柱维持普通渲染（split 占位属后续工序）。"""
    _patch_partial(monkeypatch)
    for status in ("split", "保留", "目标"):
        monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state",
                            lambda cs_id, s=status: {"status": s,
                                                     "merged_into": None})
        sections = _spine_sections(101, category="motion", language="en")
        body_all = "\n".join(sec.body or "" for sec in sections)
        assert "已并入" not in body_all, status


# ============================================
# 七段编排：脏数据 / 取数抛异常 → 不崩
# ============================================

def test_dirty_data_does_not_crash(monkeypatch):
    """畸形字段、坏 JSON、错误类型一律折叠为灰段或降级文本。"""
    monkeypatch.setattr(
        sense_spine, "_fetch_sense_row", lambda sid: {
            "id": sid, "sense_index": None, "definition": None,
            "grammar": None, "examples": "不是JSON", "sense_group": None,
            "is_idiom": "x", "verb": None})
    monkeypatch.setattr(
        sense_spine, "_fetch_submissions", lambda sid: [
            {"id": 1, "task_type": "奇怪任务", "coder_id": None,
             "payload": "不是字典", "status": "奇怪状态", "submitted_at": None,
             "username": None, "display_name": None},
            {"id": 2, "task_type": "feature_coding", "coder_id": 3,
             "payload": {"features": "不是字典"}, "status": "submitted",
             "submitted_at": "x", "username": "bob", "display_name": None}])
    monkeypatch.setattr(
        sense_spine, "_fetch_latest_reliability", lambda cat: [
            {"task_type": "admission", "overall_alpha": "abc",
             "per_feature": "{坏JSON", "n_coders": None, "n_units": None,
             "computed_at": None}])
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: 77)
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state", lambda cs_id: None)
    monkeypatch.setattr(
        sense_spine, "_fetch_cluster_info", lambda cs_id, lang: {
            "cluster_id": None, "cluster_no": None, "cluster_name": None,
            "cluster_size": None, "run_id": None, "version": None})
    monkeypatch.setattr(sense_spine, "_fetch_tier", lambda *a: {"tier": "怪值"})
    monkeypatch.setattr(sense_spine, "instantiate_template", lambda *a, **k: None)
    monkeypatch.setattr(
        sense_spine, "_fetch_media", lambda sid: [
            {"kind": None, "purpose": None, "caption": None,
             "binding_status": None, "asset_status": None, "file_path": None,
             "license": None}])
    monkeypatch.setattr(
        sense_spine, "_fetch_custom_values", lambda sid: [
            {"code": None, "name": None, "value_text": None,
             "value_num": "脏值", "value_type": "number",
             "field_status": "deprecated"}])
    sections = _spine_sections(101)
    assert len(sections) == 7
    for sec in sections:
        if sec.body is not None:  # 有数段必须是可读文本（降级不抛）
            assert isinstance(sec.body, str)


def test_fetcher_exceptions_collapse_to_gray(monkeypatch):
    """取数适配层抛异常 → 单段灰「段渲染异常」，其余段照常。"""
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(sense_spine, "_fetch_sense_row", boom)
    monkeypatch.setattr(sense_spine, "_fetch_submissions", boom)
    monkeypatch.setattr(sense_spine, "_fetch_latest_reliability", boom)
    monkeypatch.setattr(sense_spine, "_fetch_media", boom)
    monkeypatch.setattr(sense_spine, "_fetch_custom_values", boom)
    sections = _spine_sections(101)
    assert len(sections) == 7
    assert all(sec.body is None for sec in sections)
    assert any("异常" in sec.missing_reason for sec in sections)


def test_instantiate_template_exception_is_contained(monkeypatch):
    """⑤ instantiate_template 抛异常被段内捕获 → 灰段不外泄。"""
    monkeypatch.setattr(sense_spine, "_fetch_sense_row", lambda sid: None)
    monkeypatch.setattr(sense_spine, "_fetch_submissions", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_latest_reliability", lambda cat: [])
    monkeypatch.setattr(sense_spine, "_fetch_category_codes", lambda: ["RUN"])
    monkeypatch.setattr(sense_spine, "_find_cs_sense_id", lambda *a: 77)
    monkeypatch.setattr(sense_spine, "_fetch_cs_sense_state", lambda cs_id: None)

    def boom(*a, **k):
        raise RuntimeError("pack broken")
    monkeypatch.setattr(sense_spine, "instantiate_template", boom)
    monkeypatch.setattr(sense_spine, "_fetch_media", lambda sid: [])
    monkeypatch.setattr(sense_spine, "_fetch_custom_values", lambda sid: [])
    sections = _spine_sections(101)
    assert sections[4].body is None
    assert "异常" in sections[4].missing_reason or "不可用" in sections[4].missing_reason


# ============================================
# 展示口径纯函数
# ============================================

class TestPayloadSummary:
    def test_admission(self):
        text = _payload_summary("admission", {"admission": "Y", "schema": "PATH",
                                              "alignment": "对齐",
                                              "needs_review": 0})
        assert text.startswith("义位准入：")
        assert "准入=Y" in text and "图式=PATH" in text and "需复核=0" in text

    def test_feature_coding(self):
        features = {f"P{i}": 1 for i in range(8)}
        text = _payload_summary("feature_coding", {"features": features})
        assert "编码 8 项" in text and "P0=1" in text and "…" in text

    def test_alignment(self):
        text = _payload_summary("alignment", {"alignment": "完全对应"})
        assert "对齐=完全对应" in text

    def test_dirty_payloads(self):
        assert "（空 payload）" in _payload_summary("admission", {})
        assert "不是字典" in _payload_summary("admission", "不是字典")
        assert _payload_summary(None, None).startswith("未知任务")


class TestFormatAlpha:
    def test_none_and_dirty(self):
        assert _format_alpha(None) == "—"
        assert _format_alpha("abc") == "—"
        assert _format_alpha(object()) == "—"

    def test_numeric(self):
        assert _format_alpha(0.75) == "0.750"
        assert _format_alpha("0.8126") == "0.813"  # 库内 DECIMAL 出参为 str 也能转
        assert _format_alpha(1) == "1.000"


class TestJsonTolerance:
    def test_parse_json_dict(self):
        assert _parse_json_dict('{"P1":0.5}') == {"P1": 0.5}
        assert _parse_json_dict({"a": 1}) == {"a": 1}
        assert _parse_json_dict("[1,2]") is None      # list 不算 dict
        assert _parse_json_dict("{坏") is None
        assert _parse_json_dict(None) is None
        assert _parse_json_dict(42) is None

    def test_parse_json_list(self):
        assert _parse_json_list('["a"]') == ["a"]
        assert _parse_json_list(["a"]) == ["a"]
        assert _parse_json_list('{"a":1}') is None
        assert _parse_json_list("不是JSON") is None
        assert _parse_json_list(None) is None


class TestStudyCode:
    def test_direct_code_case_insensitive(self):
        assert _study_code_for("RUN", ["RUN"]) == "RUN"
        assert _study_code_for("run", ["RUN"]) == "RUN"

    def test_pack_name_mapping(self):
        assert _study_code_for("motion", ["RUN"]) == "RUN"
        assert _study_code_for("MOTION", ["RUN"]) == "RUN"

    def test_no_match_and_dirty(self):
        assert _study_code_for("jump", ["RUN"]) is None
        assert _study_code_for("motion", []) is None
        assert _study_code_for("", ["RUN"]) is None
        assert _study_code_for(None, ["RUN"]) is None


def test_tier_label():
    assert _tier_label("prototype") == "原型"
    assert _tier_label("typical") == "次典型"
    assert _tier_label("periphery") == "边缘"
    assert _tier_label("怪值") == "怪值"   # 未知值回退原文
    assert _tier_label(None) == "—"


def test_truncate_and_as_int():
    assert _truncate("abcdef", 4) == "abcd…"
    assert _truncate(None) == ""
    assert _truncate(42) == "42"
    assert _truncate("  前后空格  ") == "前后空格"
    assert sense_spine._as_int("7") == 7
    assert sense_spine._as_int(True) is None
    assert sense_spine._as_int("x") is None
    assert sense_spine._as_int(3.0) == 3


# ============================================
# 媒体库表单校验纯函数（dict_admin_pages，license 必填判定等）
# ============================================

class TestMediaRegisterValidation:
    def test_valid_inputs_pass(self):
        assert _media_register_error("data/img.png", "image", "xianhan",
                                     "CC BY 4.0") is None

    def test_license_required(self):
        """空 license（含纯空白）必须被拦截 —— 许可纪律。"""
        for bad in ("", "   ", None):
            error = _media_register_error("a.png", "image", "src", bad)
            assert error is not None and "许可" in error and "必填" in error

    def test_file_path_required(self):
        error = _media_register_error("  ", "image", "src", "CC")
        assert error is not None and "file_path" in error

    def test_kind_enum(self):
        """kind 必须在 media_db.KINDS 枚举内（下拉即由该常量生成）。"""
        error = _media_register_error("a.png", "doc", "src", "CC")
        assert error is not None and "kind" in error
        for kind in media_db.KINDS:
            assert _media_register_error("a.png", kind, "src", "CC") is None

    def test_source_required(self):
        error = _media_register_error("a.png", "image", " ", "CC")
        assert error is not None and "source" in error


class TestMediaStatusFlow:
    def test_single_step_chain(self):
        """候选→审定→发布逐级单步；发布为终点；未知态不可流转。"""
        assert _next_media_status("候选") == "审定"
        assert _next_media_status("审定") == "发布"
        assert _next_media_status("发布") is None
        assert _next_media_status("") is None
        assert _next_media_status("草稿") is None
        assert _next_media_status(None) is None

    def test_chain_uses_media_db_constants(self):
        """流转表以 media_db.STATUSES 常量为源（枚举漂移即断言失败）。"""
        candidate, reviewed, published = media_db.STATUSES
        assert dict_admin_pages.MEDIA_STATUS_NEXT == {
            candidate: reviewed, reviewed: published}


class TestMediaHelpers:
    def test_format_bytes(self):
        assert _format_bytes(None) == "—"
        assert _format_bytes("abc") == "—"
        assert _format_bytes(-1) == "—"
        assert _format_bytes(512) == "512 B"
        assert _format_bytes(2048) == "2.0 KB"
        assert _format_bytes(3 * 1024 * 1024) == "3.0 MB"

    def test_sha256_file(self, tmp_path):
        target = tmp_path / "asset.png"
        target.write_bytes(b"run-image-bytes")
        digest = _sha256_file(target)
        import hashlib
        assert digest == hashlib.sha256(b"run-image-bytes").hexdigest()
        assert _sha256_file(tmp_path / "missing.png") is None
