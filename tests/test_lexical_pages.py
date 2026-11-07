"""lexical_pages 纯逻辑层测试（src/lexical_pages.py，批次 7 Agent V）。

页面尚未接线 app.py（集成步骤负责），故按批次 2/7 契约只测纯逻辑：
  * GUIDE 结构契约：四段式齐（label/purpose/principle/data_source/steps/
    notes）、label 以 📖 前缀且为「例证与对译」、steps ≥ 3 —— 集成时
    原样并入 PAGE_GUIDES["lexical"]；
  * 角色门纯函数 _can_edit：有效六角色含 editor/reviewer/dict_admin 放行、
    过渡 role=='admin' 兼判、无 user / 非编纂角色 / 非法 roles fail-closed；
  * merged 拒选口径：_sense_selectable（merged 禁选）/ _merged_annotation
    （「已并入 → #N」文案与义项脊柱同口径，去向缺失不猜 id）/
    _sense_options（merged 不进下拉映射）；
  * 对译三态分支校验 _translation_missing（full/partial 缺对应词、partial
    缺括注、none 缺释义翻译、非法三态拒绝）；
  * 输出转义 _esc、例证下拉映射 _example_options（截断/换行压平/唯一）、
    widget key 前缀 lex_（源代码扫描守约）。

不要求 AppTest（未接线）；本文件不连数据库（import 各数据层模块不触发连接）。
"""
import inspect
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.lexical_pages import (  # noqa: E402
    GUIDE,
    _can_edit,
    _esc,
    _example_options,
    _merged_annotation,
    _sense_label,
    _sense_options,
    _sense_selectable,
    _translation_missing,
    render_lexical_page,
)


# ============================================
# GUIDE 结构契约（集成并入 PAGE_GUIDES 的前提）
# ============================================

def test_guide_contract_fields():
    """四段式五键齐备且 label 为「📖 例证与对译」（施工规范 §10-V）。"""
    assert isinstance(GUIDE, dict)
    for key in ("label", "purpose", "principle", "data_source", "steps", "notes"):
        assert key in GUIDE, f"GUIDE 缺少 {key}"
    assert GUIDE["label"].startswith("📖")
    assert "例证与对译" in GUIDE["label"]
    assert isinstance(GUIDE["purpose"], str) and GUIDE["purpose"].strip()


def test_guide_list_sections_nonempty_strings():
    """principle/data_source/steps/notes 都是非空字符串清单。"""
    for key in ("principle", "data_source", "steps", "notes"):
        section = GUIDE[key]
        assert isinstance(section, list) and section, f"GUIDE.{key} 应为非空 list"
        assert all(isinstance(item, str) and item.strip() for item in section), (
            f"GUIDE.{key} 应全为非空字符串"
        )


def test_guide_steps_at_least_three():
    """steps ≥ 3（契约硬指标）。"""
    assert len(GUIDE["steps"]) >= 3


def test_guide_covers_both_tabs():
    """步骤/说明要覆盖两 tab（例证配置/对译定稿）与三态口径。"""
    joined = " ".join(GUIDE["steps"] + GUIDE["notes"])
    assert "例证配置" in joined
    assert "对译定稿" in joined
    for state_word in ("完全对应", "部分对应", "释义翻译"):
        assert state_word in joined
    assert "已并入" in joined            # merged 禁选口径入 GUIDE
    assert "物理删除" in joined          # 例证软删口径（可重建非词典正文）入 GUIDE
    assert "媒体" in joined              # 媒体例证绑定入口入 GUIDE


def test_guide_mentions_merged_and_sources():
    """principle 提及 merged 禁选与例证三来源/改写标记。"""
    joined = " ".join(GUIDE["principle"])
    assert "merged" in joined
    for src_word in ("语料", "改写", "自拟"):
        assert src_word in joined


# ============================================
# 角色门纯函数 _can_edit（三态 + fail-closed 边界）
# ============================================

def test_can_edit_no_user():
    """无 user / 非 dict 一律不放行（fail-closed）。"""
    assert _can_edit(None) is False
    assert _can_edit({}) is False
    assert _can_edit("admin") is False
    assert _can_edit(42) is False
    assert _can_edit(["editor"]) is False


def test_can_edit_transitional_admin_role():
    """过渡期：会话 role == 'admin' 视为兼有 dict_admin。"""
    assert _can_edit({"id": 1, "role": "admin"}) is True
    assert _can_edit({"id": 1, "role": "admin", "roles": []}) is True


def test_can_edit_editorial_roles():
    """有效六角色含 editor / reviewer / dict_admin 任一即放行。"""
    assert _can_edit({"id": 2, "role": "viewer", "roles": ["editor"]}) is True
    assert _can_edit({"id": 2, "role": "viewer", "roles": ("reviewer",)}) is True
    assert _can_edit({"id": 2, "role": "viewer",
                      "roles": {"annotator", "dict_admin"}}) is True
    # legacy role 列映射：reviewer 同名放行
    assert _can_edit({"id": 3, "role": "reviewer"}) is True


def test_can_edit_denied_states():
    """viewer/annotator（含 legacy 列）与空角色集不放行。"""
    assert _can_edit({"id": 4, "role": "viewer"}) is False
    assert _can_edit({"id": 4, "role": "annotator"}) is False
    assert _can_edit({"id": 4, "role": "viewer",
                      "roles": ["viewer", "annotator"]}) is False
    assert _can_edit({"id": 4, "role": "viewer", "roles": []}) is False


def test_can_edit_fail_closed_types_and_case():
    """roles 非序列/大小写漂移/垃圾角色一律不放行（白名单校验）。"""
    assert _can_edit({"id": 5, "role": "viewer", "roles": "editor"}) is False
    assert _can_edit({"id": 5, "role": "viewer", "roles": 123}) is False
    assert _can_edit({"id": 5, "role": "viewer", "roles": None}) is False
    assert _can_edit({"id": 5, "role": "viewer", "roles": ["Editor"]}) is False
    assert _can_edit({"id": 5, "role": "viewer", "roles": ["editor_x"]}) is False
    assert _can_edit({"id": 5, "role": "Editor"}) is False


# ============================================
# merged 拒选口径（与 cluster_analysis / sense_spine 同口径）
# ============================================

def test_merged_annotation_target_and_missing():
    """merged 有去向 →「已并入 → #N」；去向缺失不猜 id。"""
    assert _merged_annotation("merged", 7) == "已并入 → #7"
    assert _merged_annotation("MERGED", "7") == "已并入 → #7"   # 大小写/str 容错
    assert _merged_annotation(" merged ", 42) == "已并入 → #42"
    assert _merged_annotation("merged", None) == "已并入（merged_into 去向待补录）"
    assert _merged_annotation("merged", "") == "已并入（merged_into 去向待补录）"
    assert _merged_annotation("merged", 0) == "已并入（merged_into 去向待补录）"
    assert _merged_annotation("merged", "x") == "已并入（merged_into 去向待补录）"


def test_merged_annotation_non_merged_returns_none():
    """非 merged（保留/边缘/剔除/目标/split）→ None。"""
    for status in ("保留", "边缘", "剔除", "目标", "split", None, ""):
        assert _merged_annotation(status, 7) is None


def test_sense_selectable_merged_rejected():
    """merged 禁选（拒选口径），其余 status 可选。"""
    ok, reason = _sense_selectable("merged")
    assert ok is False
    assert "已并入" in reason
    ok, reason = _sense_selectable("MERGED")
    assert ok is False and reason
    for status in ("保留", "边缘", "剔除", "目标", "split", None, ""):
        ok, reason = _sense_selectable(status)
        assert ok is True and reason == ""


def test_sense_label_contains_id_and_merged_note():
    """标签含 #id（恒唯一）与 lemma/义项号；merged 行附「已并入」去向。"""
    row = {"id": 12, "lemma": "run", "sense_no": "1", "sense_label": "足部奔跑义",
           "language": "en", "status": "保留", "merged_into": None}
    label = _sense_label(row)
    assert "#12" in label and "run" in label and "足部奔跑义" in label
    assert "已并入" not in label
    merged = dict(row, id=13, status="merged", merged_into=7)
    label_m = _sense_label(merged)
    assert "#13" in label_m and "已并入 → #7" in label_m


def test_sense_options_excludes_merged():
    """merged 义位不进下拉映射（禁选），以 excluded 返回供页面标注。"""
    senses = [
        {"id": 1, "lemma": "run", "sense_no": "1", "sense_label": "奔跑义",
         "language": "en", "status": "保留", "merged_into": None},
        {"id": 2, "lemma": "run", "sense_no": "2", "sense_label": "管理义",
         "language": "en", "status": "merged", "merged_into": 1},
    ]
    options, excluded = _sense_options(senses)
    assert len(options) == 1 and list(options.values()) == [1]
    assert len(excluded) == 1 and excluded[0]["id"] == 2
    # 标签含 #id → selectbox options 恒唯一
    assert len(set(options.keys())) == len(options)


# ============================================
# 对译三态分支校验 _translation_missing
# ============================================

def test_translation_missing_full_state():
    """full：对应词必填。"""
    assert _translation_missing("full", "", "", None) is not None
    assert _translation_missing("full", "   ", "", None) is not None
    assert _translation_missing("full", "跑", "", None) is None


def test_translation_missing_partial_state():
    """partial：对应词＋括注（note）双必填。"""
    assert _translation_missing("partial", "奔跑", "", None) is not None
    assert _translation_missing("partial", "", "括注", None) is not None
    assert _translation_missing("partial", "奔跑", "括注：强调奔", None) is None


def test_translation_missing_none_state():
    """none：释义翻译（paraphrase）必填；对应词不要求。"""
    assert _translation_missing("none", "", "", "") is not None
    assert _translation_missing("none", "", "", "   ") is not None
    assert _translation_missing("none", "", "", "用释义直译") is None
    assert _translation_missing("none", "跑", "注", "用释义直译") is None


def test_translation_missing_invalid_state_rejected():
    """三态单选不可绕过：非法 state 直接拒绝。"""
    assert _translation_missing("exact", "跑", "注", "译") is not None
    assert _translation_missing("", "跑", "注", "译") is not None
    assert _translation_missing(None, "跑", "注", "译") is not None


# ============================================
# 输出转义 / 例证下拉映射 / widget key 前缀
# ============================================

def test_esc_escapes_markup_quotes_and_ampersand():
    """用户生成内容出口统一转义（含引号与 &）。"""
    assert _esc("<b>run</b>") == "&lt;b&gt;run&lt;/b&gt;"
    assert _esc('a"b') == "a&quot;b"
    assert _esc("a'b") == "a&#x27;b"
    assert _esc("a&b") == "a&amp;b"
    assert _esc(12) == "12"
    assert _esc(None) == "None"


def test_example_options_unique_truncated_and_flattened():
    """例证下拉映射：label 含 #id 恒唯一；内容截断＋换行压平。"""
    examples = [
        {"id": 1, "content": "短句", "status": "候选"},
        {"id": 2, "content": "长句" * 30 + "\n第二行", "status": "审定"},
    ]
    options = _example_options(examples)
    assert len(options) == 2
    assert set(options.values()) == {1, 2}
    long_label = next(k for k, v in options.items() if v == 2)
    assert "\n" not in long_label
    assert "…" in long_label and len(long_label) < 60
    assert _example_options([]) == {}


def test_widget_keys_use_lex_prefix():
    """widget key 统一前缀 lex_（源代码扫描守约；f-string 键亦守）。"""
    src = inspect.getsource(sys.modules["src.lexical_pages"])
    keys = re.findall(r'key=f?"([^"]+)"', src)
    assert keys, "页面源码中应存在带 key 的 widget"
    offenders = [k for k in keys if not k.startswith("lex_")]
    assert offenders == [], f"widget key 未带 lex_ 前缀: {offenders}"


def test_example_content_limit_disclosed_in_page():
    """R2-6：例证正文上限在页面披露 —— MAX_CONTENT_LEN 从 lexical_db 同源
    导入，新增/编辑两处表单文案与失败转述都引用该常量（不写死第二份数字）。"""
    import src.lexical_db as lexical_db_mod

    src = inspect.getsource(sys.modules["src.lexical_pages"])
    assert "MAX_CONTENT_LEN" in src, "页面未引用例证正文上限常量"
    assert "from src.lexical_db import" in src
    # 页面引用的常量与数据层同一对象（单一事实源，不复制数字）
    assert lexical_db_mod.MAX_CONTENT_LEN == 20000
    # 新增与编辑两处表单标签/help、失败文案都带上限口径
    assert src.count("MAX_CONTENT_LEN") >= 4, (
        "新增/编辑表单与失败转述应引用 MAX_CONTENT_LEN 注明上限"
    )


def test_render_entry_is_callable():
    """渲染入口签名稳定（集成按 render_lexical_page() 接线）。"""
    assert callable(render_lexical_page)
