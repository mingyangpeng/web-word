"""中文学术文案质量锁定（RV-5 批次验收，tests/test_copy_quality.py）。

纯结构断言（源码文本 / 模块常量 / 母本文档），本地与 CI 全跑，不碰数据库。
锁定五组关键文案口径，防止后续批次回退：

  1. 准入三分（RV5-1）：Y=核心 / EXT=拓展 / N=剔除 统一，旧写法全仓清零；
  2. 理论五要素（RV5-2）：THEORY_DESCRIPTION「五个语义要素」＋【范围】；
  3. 审定/审核/审校/仲裁/裁决 五概念（RV5-14）：母本附录速查表一行锁定；
  4. 词簇（RV5-5）：词义簇 / 语义簇 旧写法在修复范围内清零；
  5. 重心得分（RV5-13）：图式得分四写法定名，UPGMA/MDS/medoid/cophenetic
     首现处带中文全称。

修复范围（FX-C 面内文件）：src/page_guides.py、src/entry_assembly.py、
src/sense_spine.py、src/annotation_flow.py、src/semantic_search.py、
src/data_pages.py、src/writing_pages.py、src/lexical_pages.py、
src/users_admin_page.py、src/collab_pages.py、src/dict_admin_pages.py、
src/cluster_analysis.py、src/category_study_page.py、src/app.py、
src/security.py、src/mysql_db.py，以及母本 docs/help/平台功能使用说明.md。
graph_export.py 的「语义簇」图例不在本批修复面（留批次 13）。
"""

import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.app as app_mod  # noqa: E402
import src.page_guides as page_guides_mod  # noqa: E402

_SRC = os.path.join(PROJECT_ROOT, "src")
MOTHER_DOC = os.path.join(
    PROJECT_ROOT, "docs", "help", "平台功能使用说明.md")

# FX-C 修复面内的文件（graph_export.py 不在面内，不纳入清零断言）
SCOPE_FILES = (
    "page_guides.py", "entry_assembly.py", "sense_spine.py",
    "annotation_flow.py", "semantic_search.py", "data_pages.py",
    "writing_pages.py", "lexical_pages.py", "users_admin_page.py",
    "collab_pages.py", "dict_admin_pages.py", "cluster_analysis.py",
    "category_study_page.py", "app.py", "security.py", "mysql_db.py",
)


def _read(filename: str) -> str:
    with open(os.path.join(_SRC, filename), encoding="utf-8") as fh:
        return fh.read()


def _read_mother() -> str:
    with open(MOTHER_DOC, encoding="utf-8") as fh:
        return fh.read()


def _squash(text: str) -> str:
    """去空白与 Markdown 引用符，便于跨行断言（源码换行拼接 / 折行）。"""
    return re.sub(r"[\s>＞]+", "", text)


def _guide_blob() -> str:
    parts: list = []
    for guide in page_guides_mod.PAGE_GUIDES.values():
        for key in ("purpose", "principle", "data_source", "steps", "notes"):
            v = guide.get(key)
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, list):
                parts.extend(x for x in v if isinstance(x, str))
    return " ".join(parts)


# ============================================
# 1. RV5-1：准入三分标签统一（Y / EXT / N）
# ============================================
class TestAdmitTernaryLabels:
    OLD_ADMIT_WORDINGS = (
        "原型物理位移义", "隐喻引申义", "Y 核心 / 拓展", "Y 核心/拓展",
        "Y/拓展/N", "归入 N 或拓展", "Y=核心、EXT=拓展",
    )

    def test_labels_unified(self):
        """管理员快速通道与多人提交流的三个准入选项同一组中文。"""
        level = {k: v for k, v in app_mod.LEVEL_LABELS.items() if k}
        submit = {k: v for k, v in app_mod.SUBMIT_ADMIT_LABELS.items() if k}
        assert [level["Y"], level["拓展"], level["N"]] == \
            [submit["Y"], submit["EXT"], submit["N"]]
        assert level["Y"] == "Y · 核心物理位移义"
        assert level["拓展"] == "EXT · 隐喻拓展义"
        assert level["N"] == "N · 非位移剔除"

    def test_old_wordings_cleared_in_scope(self):
        """修复面内 16 个文件旧准入写法清零；统一全称在场。"""
        for filename in SCOPE_FILES:
            text = _read(filename)
            for old in self.OLD_ADMIT_WORDINGS:
                assert old not in text, f"{filename} 仍含旧准入文案: {old}"
        assert "Y=核心物理位移义、EXT=隐喻拓展义、N=非位移剔除" in _read("app.py")

    def test_annotate_guide_first_occurrence_full_names(self):
        blob = _squash(" ".join(
            page_guides_mod.PAGE_GUIDES["annotate"]["principle"]))
        assert "Y=核心物理位移义、EXT=隐喻拓展义、N=非位移剔除" in blob


# ============================================
# 2. RV5-2：理论五要素（含【范围】）＋全角标点
# ============================================
class TestTheoryFiveElements:
    def test_five_elements_in_theory_description(self):
        td = app_mod.THEORY_DESCRIPTION
        assert "五个语义要素" in td
        assert "四个语义要素" not in td
        for element in ("【方式】", "【路径】", "【方向】", "【体相】", "【范围】"):
            assert element in td, f"五要素缺 {element}"
        assert "**【范围】**：运动的范围/程度" in td

    def test_search_guide_mentions_five_elements(self):
        assert "五要素" in _guide_blob()
        assert "四要素" not in _guide_blob()


# ============================================
# 3. RV5-14：审定/审核/审校/仲裁/裁决 五概念速查行
# ============================================
class TestFiveReviewConceptsRow:
    def test_mother_doc_appendix_row(self):
        text = _read_mother()
        row = re.search(r"^\| 审定 / 审核 / 审校 / 仲裁 / 裁决 \|(.+)\|$",
                        text, re.M)
        assert row, "母本附录速查表缺「审定/审核/审校/仲裁/裁决」一行"
        blob = _squash(row.group(1))
        for concept, gloss in (
            ("审定", "资产启用"), ("审核", "标注提交"), ("审校", "释义成文"),
            ("仲裁", "盲标分歧"), ("裁决", "AI提议"),
        ):
            assert concept in blob, f"速查行缺概念 {concept}"
            assert gloss in blob, f"速查行缺 {concept} 的分工说明"

    def test_review_and_proofread_wording_in_mother(self):
        """母本「审稿」死术语清零；审校口径在场。"""
        text = _read_mother()
        assert "审稿" not in text
        assert "审校" in text
        # 「顾问」不再是角色列表项（保留「无顾问角色」澄清句不在此断言范围）
        assert "授项目内角色（编纂/审稿/标注/顾问）" not in text


# ============================================
# 4. RV5-5：词簇定名（词义簇 / 语义簇 清零）
# ============================================
class TestClusterNaming:
    def test_old_cluster_names_cleared_in_scope(self):
        for filename in SCOPE_FILES:
            text = _read(filename)
            assert "词义簇" not in text, f"{filename} 仍含「词义簇」"
            assert "语义簇" not in text, f"{filename} 仍含「语义簇」"

    def test_cipin_cluster_metric_in_sidebar(self):
        app_text = _read("app.py")
        assert 'st.sidebar.metric("词簇"' in app_text


# ============================================
# 5. RV5-13：重心得分定名 ＋ 方法名首现中文全称
# ============================================
class TestProminenceScoreNaming:
    def test_no_schema_score_old_writings_in_user_copy(self):
        """page_guides 文案与 app.py 用户可见串不再出现「图式得分/突出度」；
        mysql_db 注释同步定名。"""
        assert "图式得分" not in _guide_blob()
        assert "突出度" not in _guide_blob()
        for filename in ("app.py", "mysql_db.py", "page_guides.py"):
            assert "图式得分" not in _read(filename), \
                f"{filename} 仍含「图式得分」"

    def test_method_full_names_first_occurrence_in_cluster_guide(self):
        blob = _squash(_guide_blob())
        assert "共表型相关系数（cophenetic）" in blob
        assert "（UPGMA，非加权组平均法）" in blob
        assert "多维标度分析（MDS）" in blob
        assert "中心点（medoid）" in blob

    def test_method_full_names_in_mother_doc(self):
        blob = _squash(_read_mother())
        assert "共表型相关系数（cophenetic）" in blob
        assert "UPGMA（非加权组平均法）" in blob
        assert "多维标度分析（MDS）" in blob

    def test_category_page_cophenetic_caption(self):
        text = _squash(_read("category_study_page.py"))
        assert "共表型相关系数（cophenetic" in text


# ============================================
# 6. 其余文案口径锁定（RV5-6/7/9/10/11/12）
# ============================================
class TestOtherCopyLocks:
    def test_collected_headword_metric(self):
        """侧边栏指标与指南统一「已收录词目」。"""
        for filename in ("app.py", "page_guides.py"):
            text = _read(filename)
            assert "已收录词条" not in text, f"{filename} 仍含「已收录词条」"
        assert 'st.sidebar.metric("已收录词目"' in _read("app.py")

    def test_oald_senses_wording(self):
        """OALD 数据层口径用「义项」不用「义位」。"""
        for filename in ("app.py", "page_guides.py"):
            text = _read(filename)
            assert "无 OALD 义位数据" not in text
            assert "OALD 义位读取失败" not in text
        assert "无 OALD 义项数据" in _read("app.py")

    def test_role_gate_six_roles_wording(self):
        """两处角色门对齐六角色口径（不含 legacy admin）。"""
        app_text = _squash(_read("app.py"))
        for page in ("标注平台", "标注提交"):
            marker = f"无权限：{page}需要"
            assert marker in app_text, f"缺 {page} 角色门文案"
            seg = app_text[app_text.index(marker):app_text.index(marker) + 100]
            for role in ("annotator", "editor", "reviewer",
                         "dict_admin", "sys_admin"):
                assert role in seg, f"{page} 角色门缺 {role}"
            assert "/admin角色" not in seg.replace(" ", "")

    def test_no_fake_health_light_wording(self):
        for filename in SCOPE_FILES:
            text = _read(filename)
            assert "假绿灯" not in text, f"{filename} 仍含「假绿灯」"
        assert "绝不渲染虚假健康状态" in _read("dict_admin_pages.py")
        assert "绝不渲染虚假健康状态" in _read_mother()

    def test_plain_language_wording(self):
        """毛球 / 先写点什么 / 双叹号 等口语与行话清零。"""
        for filename in SCOPE_FILES:
            text = _read(filename)
            assert "毛球" not in text, f"{filename} 仍含「毛球」"
            assert "先写点什么" not in text, f"{filename} 仍含「先写点什么」"
            assert "！！" not in text, f"{filename} 仍含双叹号"
        assert "连线视觉纠缠" in _read("page_guides.py")
        assert "请先撰写内容再保存" in _read("writing_pages.py")

    def test_engineering_jargon_chinese(self):
        """GUIDE 文案（用户可见）中 payload/gold/tab/vs/caption/滑杆 清零。"""
        blob = _guide_blob()
        for jargon in ("payload", "gold", "滑杆", "caption"):
            assert jargon not in blob, f"GUIDE 仍含行话 {jargon}"
        # 裸 tab 行话：允许代码标识符（semantic_table 等），禁止中文散文夹 tab
        assert re.search(r"[\u4e00-\u9fff]tab|tab[\u4e00-\u9fff]|」tab|个tab",
                         blob) is None, "GUIDE 仍含裸 tab 行话"
        # vs 行话（允许出现在英文标识符内）
        assert re.search(r"[\u4e00-\u9fff]vs[\u4e00-\u9fff]|[\u4e00-\u9fff] vs ",
                         blob) is None, "GUIDE 仍含 vs 行话"

    def test_tie_caption_implemented(self):
        """最近邻平局 caption 与母本 1.2 口径一致（RV5-11）。"""
        text = _squash(_read("semantic_search.py"))
        assert "以下结果距离相同，供参照" in text

    def test_bare_table_empty_states_have_guidance(self):
        """裸表名空态附下一步指引（RV5-11）。"""
        app_text = _squash(_read("app.py"))
        assert "（corpus_word_stats）为空：请重跑" in app_text
        assert "load_corpus_dataset.py" in app_text
        assert "（domain_family_senses）为空：请重跑" in app_text
        assert "load_domain_family.py" in app_text
        assert "categories为空：多见于灌数后页面缓存未刷新" in \
            _squash(_read("cluster_analysis.py"))

    def test_mother_doc_wording_fixes(self):
        """母本：编撰/词头/caption/滑杆/假绿灯/dump/production/training/gold
        清零；词类歧义改「范畴项目」；编号体例无 1.6/6.6b/6.6c。"""
        text = _read_mother()
        for old in ("编撰", "词头", "滑杆", "假绿灯", "dump", "production",
                    "training", "gold", "caption", "payload"):
            assert old not in text, f"母本仍含 {old}"
        squash = _squash(text)
        assert "范畴项目" in squash
        assert "词类" not in squash
        for heading in ("### 6.6b", "### 6.6c"):
            assert heading not in text, f"母本仍含旧编号 {heading}"
        # 编号体例：1.6 归区一；区二直接从 2.1 开始；区六 6.7 起顺延
        parts = text.split("## 🏷️ 二、语义建模区（登录按角色）")
        assert len(parts) == 2 and "### 1.6" in parts[0] \
            and "### 2.1" in parts[1], "1.6 未归入区一或区二起始编号异常"
        assert "### 6.7 🖼️ 媒体库" in text
        assert "### 6.8 🧬 义项脊柱" in text
        assert "第二个范畴项目/词典项目" in squash

    def test_mother_doc_definition_rule_row(self):
        """母本附录含「词条/词目/义项/义位」定则一行（RV5-6）。"""
        text = _read_mother()
        row = re.search(r"^\| 词条 / 词目 / 义项 / 义位 \|(.+)\|$",
                        text, re.M)
        assert row, "母本附录速查表缺定则一行"
        blob = _squash(row.group(1))
        assert "词目＝头词" in blob
        assert "义项＝词典一条释义" in blob
        assert "义位＝研究层判定单元" in blob

    def test_semantic_analysis_page_name_replaced(self):
        """用户可见空态提示不再使用旧页名「范畴深挖」（历史对照注释除外）。"""
        for filename in ("semantic_search.py", "writing_pages.py",
                         "cluster_analysis.py", "sense_spine.py",
                         "entry_assembly.py", "data_pages.py"):
            text = _read(filename)
            assert "灌入范畴深挖数据" not in text, f"{filename} 仍指旧页名"
            assert "范畴深挖库" not in text, f"{filename} 仍含「范畴深挖库」"

    def test_cluster_study_quantity_names(self):
        """簇研究量名统一：英语用词目/义位、汉语用词条/义位条目。"""
        blob = _squash(_guide_blob())
        assert "英语23词目32义位" in blob
        assert "汉语19词条25义位条目" in blob
        assert "汉19条目" not in blob
