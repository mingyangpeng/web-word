"""FX8 批次修复验证（RV3-1 幂等重绑 ＋ RV5-1~5 中文学术文案统一）。

两层结构（与既有批次测试约定一致）：

  * 纯结构断言（模块常量映射一致 / 源码文本旧文案清零 / 指南段落口径）
    —— 本地与 CI 全跑，不碰数据库；
  * 行为断言（RV3-1 bind_example_media 幂等重绑）在
    tests/test_lexical_db.py（TestLexicalIntegration::
    test_bind_media_idempotent_rebind_returns_true /
    test_bind_media_real_path_idempotent_rebind），本文件不重复。

RV5-1 分层口径（重要）：统一的是 **显示/文案层** —— 权威层
word_senses / oald_senses.prototype_level 与 domain_family_senses.llm_tag
的存储值仍含中文「拓展」（word_source.PROTOTYPE_METAPHOR，存量数据不动），
提交层 annotation_submissions payload 本就用 Y/EXT/N；因此结构断言同时
锁住「存储值不变」与「显示文案统一」两侧。
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.app as app_mod  # noqa: E402
import src.page_guides as page_guides_mod  # noqa: E402
import src.users_admin_page as users_admin_page_mod  # noqa: E402

_SRC = os.path.join(PROJECT_ROOT, "src")


def _read(filename: str) -> str:
    with open(os.path.join(_SRC, filename), encoding="utf-8") as fh:
        return fh.read()


# ============================================
# RV5-1：准入三分统一（Y 核心 / EXT 拓展 / N 剔除）
# ============================================
class TestRV51AdmitTernaryUnified:
    """两页 radio 同一组中文；旧 5 种写法清零；存储值分层不动。"""

    def test_two_radios_share_same_chinese_labels(self):
        """管理员快速通道（LEVEL_LABELS）与多人提交流（SUBMIT_ADMIT_LABELS）
        的三个准入选项显示同一组中文（空选项除外）。"""
        level = {k: v for k, v in app_mod.LEVEL_LABELS.items() if k}
        submit = {k: v for k, v in app_mod.SUBMIT_ADMIT_LABELS.items() if k}
        # 显示键归一：LEVEL 用权威层存储值（Y/拓展/N），SUBMIT 用提交口径
        # （Y/EXT/N），两者一一对应后中文文案必须完全一致。
        paired = [level["Y"], level["拓展"], level["N"]]
        assert paired == [submit["Y"], submit["EXT"], submit["N"]]
        # 统一后的全称文案（首现口径）
        assert level["Y"] == "Y · 核心物理位移义"
        assert level["拓展"] == "EXT · 隐喻拓展义"
        assert level["N"] == "N · 非位移剔除"

    def test_storage_values_untouched(self):
        """分层不动数据：LEVEL_OPTIONS 仍含权威层存储值「拓展」，
        LLM 草稿映射 llm_tag「拓展」→ 提交口径 EXT。"""
        assert app_mod.LEVEL_OPTIONS == ["", "Y", "拓展", "N"]
        assert app_mod._LLM_TAG_TO_ADMIT == {"Y": "Y", "拓展": "EXT", "N": "N"}
        assert app_mod.SUBMIT_ADMIT_OPTIONS == ["", "Y", "EXT", "N"]

    def test_status_badges_display_ext_for_stored_value(self):
        """两处状态徽标把权威层存储值「拓展」显示为 ✅EXT（与 radio 同口径）。"""
        stored = "拓展"
        for fn in (app_mod._submission_sense_status,):
            assert "✅EXT" in fn({"prototype_level": stored})
            assert "✅Y" in fn({"prototype_level": "Y"})
            assert "✅N" in fn({"prototype_level": "N"})
            assert "❓存疑" in fn({"needs_review": True})
            assert "⬜未标" in fn({})

    def test_old_admit_wording_cleared_in_sources(self):
        """app.py / page_guides.py 旧准入写法清零（原型物理位移义 /
        隐喻引申义 / Y 核心 / 拓展 短式 / Y/拓展/N / 归入 N 或拓展）。"""
        for filename in ("app.py", "page_guides.py"):
            text = _read(filename)
            for old in ("原型物理位移义", "隐喻引申义", "Y 核心 / 拓展",
                        "Y 核心/拓展", "Y/拓展/N", "归入 N 或拓展",
                        "Y=核心、EXT=拓展"):
                assert old not in text, f"{filename} 仍含旧准入文案: {old}"
        # 显示层统一后的口径在场（app.py 常量注释首现全称）
        app_text = _read("app.py")
        assert "Y=核心物理位移义、EXT=隐喻拓展义、N=非位移剔除" in app_text
        # page_guides annotate 指南首现全称
        annotate_text = " ".join(page_guides_mod.PAGE_GUIDES["annotate"]["principle"])
        assert "Y=核心物理位移义、EXT=隐喻拓展义、N=非位移剔除" in annotate_text


# ============================================
# RV5-2：搜索页理论块「四要素」→「五要素」＋标点全角化
# ============================================
class TestRV52TheoryDescription:
    """THEORY_DESCRIPTION：五要素（含【范围】）、全角标点、波浪型标点对齐。"""

    def test_five_elements_with_scope(self):
        td = app_mod.THEORY_DESCRIPTION
        assert "五个语义要素" in td
        assert "四个语义要素" not in td
        for element in ("【方式】", "【路径】", "【方向】", "【体相】", "【范围】"):
            # 开头枚举与逐条释义各出现一次
            assert td.count(element) == 2, f"{element} 应出现 2 次"
        assert "**【范围】**：运动的范围/程度" in td

    def test_full_width_punctuation(self):
        td = app_mod.THEORY_DESCRIPTION
        assert "**波浪型（Wave-like）**：强调方式" in td
        assert "**矢量型（Vector-like）**：强调路径+方向" in td
        assert "波浪型 (Wave-like)" not in td          # 旧半角写法清零
        assert "**运动事件类型学（Talmy, 1985）**" in td
        assert "以「路径+方向」为核心" in td            # ASCII 引号 → 「」
        assert '"路径+方向"' not in td
        assert "**【方式】**：运动采用的姿势/手段" in td  # 释义行破折号 → 全角冒号


# ============================================
# RV5-3：annotate 指南英汉对齐三值（「错位」属簇层）
# ============================================
class TestRV53AlignmentThreeValues:
    def test_annotate_guide_three_values_with_cluster_note(self):
        annotate = page_guides_mod.PAGE_GUIDES["annotate"]
        blob = " ".join(annotate["principle"] + annotate["steps"])
        assert "完全 / 部分 / 零 三选一" in blob
        assert "「错位」" in blob and "簇层" in blob
        # 义位层旧四值写法清零（「错位」只允许出现在簇层说明里）
        assert "零 / 错位" not in blob
        assert "零对齐 / 错位" not in blob

    def test_cluster_guide_keeps_four_values(self):
        """「错位」属簇层：语义分析（cluster）指南的四类簇对齐口径不动。"""
        cluster = page_guides_mod.PAGE_GUIDES["cluster"]
        blob = " ".join(cluster["principle"])
        assert "完全 / 部分 / " in blob and "零 / 错位" in blob


# ============================================
# RV5-4：users_admin_page / page_guides 口令 → 密码
# ============================================
class TestRV54PasswordWording:
    def test_no_kouling_in_scope_files(self):
        """两个修复范围内文件「口令」清零（app.py 不在本项范围）。"""
        for filename, mod in (("users_admin_page.py", users_admin_page_mod),
                              ("page_guides.py", page_guides_mod)):
            assert "口令" not in _read(filename), f"{filename} 仍含「口令」"
            assert "密码" in _read(filename)

    def test_fixed_sentences_in_place(self):
        users_text = _read("users_admin_page.py")
        assert "初始密码须首次登录修改" in users_text
        assert "admin 的初始密码为公开的 bootstrap 凭据" in users_text
        assert "初始密码是公开 bootstrap 凭据" in _read("page_guides.py")


# ============================================
# RV5-5：词义簇 / 语义簇 → 词簇（Levin 次类簇定名）
# ============================================
class TestRV55ClusterNaming:
    def test_no_old_cluster_names_in_scope_files(self):
        """app.py / page_guides.py 旧写法（词义簇 / 语义簇）清零。"""
        for filename in ("app.py", "page_guides.py"):
            text = _read(filename)
            assert "词义簇" not in text, f"{filename} 仍含「词义簇」"
            assert "语义簇" not in text, f"{filename} 仍含「语义簇」"

    def test_new_cluster_name_in_place(self):
        app_text = _read("app.py")
        assert 'st.sidebar.metric("词簇"' in app_text
        assert 'c3.metric("词簇"' in app_text
        assert "按词簇勾选过滤" in app_text
        guide_blob = _read("page_guides.py")
        assert "12 个词簇的交互式力导向图" in guide_blob
        assert "词簇（当前为 171 / 1935 / 12）" in guide_blob
