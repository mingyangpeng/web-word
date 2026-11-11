"""FX-45 两块修复测试：标注表单暂存（draft_states 第二消费面）＋ 重标闸批量查询等价。

对应修复（writing FX-39 先例的第二消费面 ＋ RV19-1 留档项消缺）：

  * 标注表单暂存/恢复/提交清除（src/app.py render_submission_flow，FX-45
    任务 1）：form_key 约定 'annotate_draft_{sense_id}'（sense_id =
    oald_senses.id）；「💾 暂存标注」为表单第二提交钮（secondary），upsert
    全部可编辑字段（admission/schema/alignment/cn_syntax/strategy/
    needs_review）→ ui_kit.flash + st.rerun（RV12，不回潮 st.success）；
    重开义位暂存值作表单默认值（优先级：暂存 > 本人上次提交 > AI 初筛
    草稿 > 空；空白/非法暂存值回落既有默认链）＋恢复 caption「已恢复暂存
    标注（…）——提交后自动清除」；提交成功路径 delete_draft 自动清除
    （失败不清除）；未登录/库不可用 fail-closed（own-rows-only 天然拦）；
  * 重标闸批量查询（src/annotation_flow.py，FX-45 任务 2，RV19-1 消缺）：
    create_reannotation_tasks 逐义位单发 _CS_STATUS_SQL（N 次往返）改单条
    IN 查询（_CS_STATUS_BATCH_SQL + _fetch_cs_status_map）。**行为等价**
    用双 SQL 假游标在同一 join 结果数据集上锁定：多命中取最小 cs_senses.id
    （= 原 ORDER BY s.id LIMIT 1）、单命中/未命中/NULL 状态/大小写混排
    逐夹具断言新旧两种实现同输出（eligible + skipped 逐项一致）。

st 桩为最小假体（FX-39 _StubSt 同款思路）：form_submit_button 按预设
**label** 精确点击（提交流双提交钮场景），selectbox/radio 按 index 装载
默认值（与真 Streamlit「未交互取默认」行为一致）。
"""

import datetime
import inspect
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ui_kit  # noqa: E402
from src import user_context_db as ucdb  # noqa: E402
from src.annotation_flow import (  # noqa: E402
    _CS_STATUS_BATCH_SQL,
    _CS_STATUS_SQL,
    _fetch_cs_status_map,
    create_reannotation_tasks,
)
import src.annotation_flow as flow  # noqa: E402
import src.app as app  # noqa: E402

# ============================================
# 公共夹具：提交流 sense 行 ＋ 暂存快照
# ============================================

SENSE_ID = 501
FORM_KEY = f"annotate_draft_{SENSE_ID}"
USER = {"id": 7, "username": "fx45", "display_name": "FX45", "role": "annotator"}

SENSE_ROW = {
    "id": SENSE_ID, "sense_index": 1,
    "definition": "to move fast on foot", "grammar": "v", "en_ndef": "move fast",
    "examples": [], "is_idiom": False, "prototype_level": None,
    "needs_review": False, "cn_syntax": None, "translation_strategy": None,
    "llm_tag": "拓展", "llm_schema": "方式伴随图式", "llm_align": "完全对齐",
    "llm_reason": "趋向补语证据充分", "llm_doubt": None,
}

# 本人上次提交 payload（预填链第二优先级）
PREV_PAYLOAD = {
    "admission": "Y", "schema": "终点抵达图式", "alignment": "部分对齐",
    "cn_syntax": "需“把”字句", "strategy": "增补方式要素", "needs_review": True,
}

# 暂存快照（全部可编辑字段；用户显式保存，最高优先级）
STASH_STATE = {
    "admission": "EXT", "schema": "源点脱离图式", "alignment": "零对齐",
    "cn_syntax": "强制趋向补语", "strategy": "舍弃方式语义",
    "needs_review": False,
}
STASH_UPDATED_AT = datetime.datetime(2026, 11, 11, 8, 30)


def _stash_row(state, form_key=FORM_KEY, updated_at=STASH_UPDATED_AT):
    """draft_states 行桩（列结构与 list_drafts SELECT 对齐）。"""
    return {"id": 1, "form_key": form_key,
            "state_json": json.dumps(state, ensure_ascii=False),
            "created_at": updated_at, "updated_at": updated_at}


# ============================================
# 假体：st ＋ flash 记录器
# ============================================

class _StubSt:
    """st 假体（FX-39 _StubSt 同款最小件，按提交流表单需要扩展）：
    form_submit_button 按预设 label 精确点击；selectbox/radio 按 index 装载
    默认值（真 Streamlit 未交互取默认的同构行为）；successes 记录专供 RV12
    反向断言（暂存路径永不回潮）。容器（columns/form/expander）返回自身
    （提交流表单控件经列上下文 f1.radio/f2.selectbox 创建，须可委派）。"""

    def __init__(self, *, click_labels=(), widget_returns=None):
        self.markdowns, self.captions = [], []
        self.errors, self.infos, self.warnings, self.successes = [], [], [], []
        self.selects, self.radios, self.text_widgets, self.checks = [], [], [], []
        self.submit_buttons, self.expanders, self.forms = [], [], []
        self.dataframes = []
        self.rerun_count = 0
        self.session_state = {}
        self._click_labels = set(click_labels)
        # {label 子串: 返回值} —— 模拟用户已改动的控件值（未命中按默认装载）
        self._widget_returns = dict(widget_returns or {})

    def _user_value(self, label):
        for part, val in self._widget_returns.items():
            if part in label:
                return val
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def markdown(self, text, **kw):
        self.markdowns.append(text)

    def caption(self, text):
        self.captions.append(text)

    def error(self, text):
        self.errors.append(text)

    def info(self, text, **kw):
        self.infos.append(text)

    def warning(self, text):
        self.warnings.append(text)

    def success(self, text):
        self.successes.append(text)

    def selectbox(self, label, options, **kw):
        self.selects.append((label, list(options), kw))
        user = self._user_value(label)
        if user is not None:
            return user
        index = kw.get("index") or 0
        return list(options)[index] if options else None

    def radio(self, label, options, **kw):
        self.radios.append((label, list(options), kw))
        user = self._user_value(label)
        if user is not None:
            return user
        index = kw.get("index") or 0
        return list(options)[index] if options else None

    def text_input(self, label, value="", **kw):
        self.text_widgets.append((label, value, kw))
        user = self._user_value(label)
        return value if user is None else user

    def checkbox(self, label, value=False, **kw):
        self.checks.append((label, value, kw))
        user = self._user_value(label)
        return value if user is None else user

    def columns(self, n):
        return [self] * (n if isinstance(n, int) else len(n))

    def expander(self, label=None, **kw):
        self.expanders.append(label)
        return self

    def form(self, key=None, **kw):
        self.forms.append(key)
        return self

    def form_submit_button(self, label, **kw):
        self.submit_buttons.append((label, kw))
        return label in self._click_labels

    def dataframe(self, df, **kw):
        self.dataframes.append(df)

    def rerun(self):
        self.rerun_count += 1


def _install_flash_recorder(monkeypatch) -> list:
    """ui_kit.flash → 记录器（返回 messages 列表供断言）。"""
    flashes: list = []
    monkeypatch.setattr(ui_kit, "flash",
                        lambda msg, level="success": flashes.append(msg))
    return flashes


def _radio_kwargs(stub, label_part):
    for label, _opts, kw in stub.radios:
        if label_part in label:
            return kw
    return None


def _select_kwargs(stub, label_part):
    for label, _opts, kw in stub.selects:
        if label_part in label:
            return kw
    return None


def _text_value(stub, label_part):
    for label, value, _kw in stub.text_widgets:
        if label_part in label:
            return value
    return None


def _check_value(stub, label_part):
    for label, value, _kw in stub.checks:
        if label_part in label:
            return value
    return None


# ============================================
# 任务 1 纯函数：_apply_annotation_stash_defaults
# ============================================

class TestAnnotationStashDefaults:
    """暂存快照 → 表单默认值（纯函数；优先级与有效性闸）。"""

    def _defaults(self, stashed, prev=None, sense=None):
        return app._apply_annotation_stash_defaults(
            stashed, sense if sense is not None else dict(SENSE_ROW),
            prev if prev is not None else dict(PREV_PAYLOAD))

    def test_no_stash_chain_unchanged(self):
        """无暂存：prev > AI > 空链路与改动前逐字节一致；无恢复 caption。"""
        d = self._defaults(None)
        assert d["admission"] == "Y"              # prev 优先于 AI
        assert d["schema"] == "终点抵达图式"
        assert d["alignment"] == "部分对齐"
        assert d["cn_syntax"] == "需“把”字句"
        assert d["strategy"] == "增补方式要素"
        assert d["needs_review"] is True
        assert d["restore_caption"] is None

    def test_no_stash_no_prev_option_fields_empty_text_fall_authoritative(self):
        """无暂存无 prev（原链路口径逐字节保留）：选项字段 prev 侧取值 ''∈
        OPTIONS 即终值（AI 草稿仅对 prev 非空非法值补位）；文本字段回落
        权威层 cn_syntax / translation_strategy。"""
        sense = dict(SENSE_ROW, cn_syntax="强制趋向补语",
                     translation_strategy="保留原图式")
        d = self._defaults(None, prev={}, sense=sense)
        assert d["admission"] == ""
        assert d["schema"] == ""
        assert d["alignment"] == ""
        assert d["cn_syntax"] == "强制趋向补语"
        assert d["strategy"] == "保留原图式"
        assert d["needs_review"] is False
        d2 = self._defaults(None, prev={}, sense={})
        assert d2["admission"] == "" and d2["schema"] == ""
        assert d2["alignment"] == "" and d2["cn_syntax"] == ""
        assert d2["strategy"] == "" and d2["needs_review"] is False

    def test_no_stash_invalid_prev_falls_to_ai_draft(self):
        """无暂存且 prev 给出非空非法选项值 → AI 初筛草稿补位（原链路）。"""
        prev = {"admission": "垃圾值", "schema": "不存在图式", "alignment": "x"}
        d = self._defaults(None, prev=prev)
        assert d["admission"] == "EXT"            # 「拓展」→ EXT 映射
        assert d["schema"] == "方式伴随图式"
        assert d["alignment"] == "完全对齐"

    def test_stash_highest_priority(self):
        """有暂存：六字段全部取暂存值（覆盖 prev / AI），出恢复 caption。"""
        d = self._defaults({"state": dict(STASH_STATE),
                            "updated_at": STASH_UPDATED_AT})
        assert d["admission"] == "EXT"
        assert d["schema"] == "源点脱离图式"
        assert d["alignment"] == "零对齐"
        assert d["cn_syntax"] == "强制趋向补语"
        assert d["strategy"] == "舍弃方式语义"
        assert d["needs_review"] is False         # bool 快照覆盖 prev True
        assert d["restore_caption"] == (
            "📥 已恢复暂存标注（2026-11-11 08:30）——提交后自动清除")

    def test_stash_partial_overrides_only_valid_fields(self):
        """半成品快照：空白/非法字段回落既有默认链，合法字段照常覆盖。"""
        stashed = {"state": {
            "admission": "",                      # 空准入不覆盖（回落 prev Y）
            "schema": "不存在的图式",              # 非法选项回落 prev
            "alignment": "  ",                    # 空白回落 prev
            "cn_syntax": "   ",                   # 空白回落 prev
            "strategy": "保留原图式",              # 合法覆盖
            # needs_review 缺键 → 照旧
        }, "updated_at": STASH_UPDATED_AT}
        d = self._defaults(stashed)
        assert d["admission"] == "Y"
        assert d["schema"] == "终点抵达图式"
        assert d["alignment"] == "部分对齐"
        assert d["cn_syntax"] == "需“把”字句"
        assert d["strategy"] == "保留原图式"
        assert d["needs_review"] is True
        assert d["restore_caption"] is not None   # 快照可用即出 caption

    def test_stash_field_level_override_and_ai_fallback_kept(self):
        """暂存只在字段级生效；prev 非空非法值时 AI 草稿补位照旧。"""
        prev = {"schema": "不存在的图式"}             # 非法 → AI 预填补位
        d = self._defaults(
            {"state": {"admission": "N", "needs_review": True},
             "updated_at": STASH_UPDATED_AT}, prev=prev)
        assert d["admission"] == "N"                  # 暂存最高优先
        assert d["schema"] == "方式伴随图式"           # 暂存没给 → AI 补位
        assert d["needs_review"] is True

    def test_corrupt_stash_treated_as_no_stash(self):
        """快照损坏（state 非 dict）按「无暂存」渲染，绝不猜态。"""
        for bad in (None, {"state": "junk"}, {"state": ["a"]}, {}):
            d = self._defaults(bad)
            assert d["admission"] == "Y"
            assert d["restore_caption"] is None

    def test_dirty_updated_at_rendered_as_is(self):
        """脏 updated_at（无 strftime）原样展示（None → '—'）。"""
        d = self._defaults({"state": dict(STASH_STATE), "updated_at": None})
        assert "已恢复暂存标注（—）" in d["restore_caption"]


class TestAnnotationStashLoader:
    """_load_stashed_annotation_draft：form_key 过滤 + 容错 + fail-closed。"""

    def _load(self, monkeypatch, rows):
        monkeypatch.setattr(ucdb, "list_drafts", lambda limit=500: list(rows))
        return app._load_stashed_annotation_draft(FORM_KEY)

    def test_hit_returns_state_and_updated_at(self, monkeypatch):
        out = self._load(monkeypatch, [_stash_row(STASH_STATE)])
        assert out["state"] == STASH_STATE
        assert out["updated_at"] == STASH_UPDATED_AT

    def test_form_key_filtered(self, monkeypatch):
        rows = [_stash_row({"admission": "N"}, form_key="annotate_draft_999"),
                _stash_row(STASH_STATE)]
        out = self._load(monkeypatch, rows)
        assert out["state"] == STASH_STATE

    def test_bytes_state_json_decoded(self, monkeypatch):
        row = dict(_stash_row(STASH_STATE))
        row["state_json"] = row["state_json"].encode("utf-8")
        out = self._load(monkeypatch, [row])
        assert out["state"] == STASH_STATE

    def test_already_parsed_dict_passthrough(self, monkeypatch):
        row = dict(_stash_row(STASH_STATE))
        row["state_json"] = dict(STASH_STATE)     # pymysql 解析 JSON 列的形态
        out = self._load(monkeypatch, [row])
        assert out["state"] == STASH_STATE

    def test_corrupt_json_and_non_dict_fail_closed(self, monkeypatch):
        broken = dict(_stash_row(STASH_STATE))
        broken["state_json"] = "{not json"
        assert self._load(monkeypatch, [broken]) is None
        listed = dict(_stash_row(STASH_STATE))
        listed["state_json"] = ["a", "b"]         # 解析出 list → 非字典拒绝
        assert self._load(monkeypatch, [listed]) is None

    def test_no_matching_key_none(self, monkeypatch):
        assert self._load(monkeypatch, []) is None

    def test_list_drafts_error_fail_closed(self, monkeypatch):
        def _boom(limit=500):
            raise RuntimeError("fake db down")

        monkeypatch.setattr(ucdb, "list_drafts", _boom)
        assert app._load_stashed_annotation_draft(FORM_KEY) is None


# ============================================
# 任务 1 接线：render_submission_flow（桩级）
# ============================================

class TestAnnotationStashWiring:
    """提交流暂存/恢复/提交清除接线（数据面全 monkeypatch，st 桩渲染）。"""

    def _render(self, monkeypatch, *, stash_rows=(), my_subs=None, click=(),
                submit_result=True, upsert_result=True, widget_returns=None):
        flashes = _install_flash_recorder(monkeypatch)
        ups, dels, subs = [], [], []
        my_rows = list(my_subs if my_subs is not None else
                       [{"sense_id": SENSE_ID, "payload": dict(PREV_PAYLOAD),
                         "status": "submitted",
                         "submitted_at": "2026-11-11 08:00:00"}])
        monkeypatch.setattr(app, "DB_AVAILABLE", True)
        monkeypatch.setattr(app, "_ensure_flow_tables_once", lambda: None)
        monkeypatch.setattr(app, "_current_user", lambda: dict(USER))
        monkeypatch.setattr(app, "render_page_usage_guide", lambda *a, **k: None)
        monkeypatch.setattr(app, "get_annotation_progress",
                            lambda: [{"verb": "walk"}, {"verb": "run"}])
        monkeypatch.setattr(app, "get_oald_senses",
                            lambda verb: [dict(SENSE_ROW)])
        monkeypatch.setattr(app, "get_my_submissions",
                            lambda coder, cat, tt: list(my_rows))
        monkeypatch.setattr(app, "CATEGORIES", lambda: [])
        monkeypatch.setattr(app, "load_pack", lambda cat: {})
        monkeypatch.setattr(app, "get_tool", lambda tool_id: None)

        def _fake_submit(category, sid, task_type, coder, payload,
                         ai_draft=None):
            subs.append({"category": category, "sense_id": sid,
                         "task_type": task_type, "coder_id": coder,
                         "payload": payload, "ai_draft": ai_draft})
            return submit_result

        monkeypatch.setattr(app, "submit_annotation", _fake_submit)
        monkeypatch.setattr(ucdb, "list_drafts",
                            lambda limit=500: list(stash_rows))
        monkeypatch.setattr(
            ucdb, "upsert_draft",
            lambda key, state: ups.append((key, state)) or upsert_result)
        monkeypatch.setattr(ucdb, "delete_draft",
                            lambda key: dels.append(key) or True)
        stub = _StubSt(click_labels=set(click), widget_returns=widget_returns)
        monkeypatch.setattr(app, "st", stub)
        app.render_submission_flow()
        return stub, flashes, ups, dels, subs

    def test_stash_button_present_no_stash_defaults_unchanged(self, monkeypatch):
        """双提交钮在场；无暂存时无恢复 caption、默认值照旧（prev 链）。"""
        stub, _, _, _, _ = self._render(monkeypatch)
        labels = [label for label, _kw in stub.submit_buttons]
        assert app.ANNOTATE_STASH_BUTTON_LABEL in labels
        assert "📤 提交本义位标注" in labels
        assert not any("已恢复暂存标注" in c for c in stub.captions)
        assert _radio_kwargs(stub, "准入标签")["index"] == \
            app.SUBMIT_ADMIT_OPTIONS.index("Y")
        assert _select_kwargs(stub, "意象图式")["index"] == \
            app.SCHEMA_OPTIONS.index("终点抵达图式")
        assert _text_value(stub, "汉语句法特征") == "需“把”字句"
        assert _check_value(stub, "存疑") is True

    def test_stash_restored_as_form_defaults_with_caption(self, monkeypatch):
        """有暂存：默认值取暂存值（最高优先）＋恢复 caption。"""
        stub, _, _, _, _ = self._render(
            monkeypatch, stash_rows=[_stash_row(STASH_STATE)])
        assert any("已恢复暂存标注（2026-11-11 08:30）" in c
                   and "提交后自动清除" in c for c in stub.captions)
        assert _radio_kwargs(stub, "准入标签")["index"] == \
            app.SUBMIT_ADMIT_OPTIONS.index("EXT")
        assert _select_kwargs(stub, "意象图式")["index"] == \
            app.SCHEMA_OPTIONS.index("源点脱离图式")
        assert _select_kwargs(stub, "英汉对齐")["index"] == \
            app.ALIGNMENT_OPTIONS.index("零对齐")
        assert _text_value(stub, "汉语句法特征") == "强制趋向补语"
        assert _text_value(stub, "译义转化策略") == "舍弃方式语义"
        assert _check_value(stub, "存疑") is False

    def test_stash_click_upserts_all_fields_flash_rerun(self, monkeypatch):
        """暂存点击：upsert_draft(form_key, 六字段) → flash+rerun（RV12）。
        快照取表单装载值（prev 链默认），六键齐全（全部可编辑字段）。"""
        stub, flashes, ups, _, _ = self._render(
            monkeypatch, click=[app.ANNOTATE_STASH_BUTTON_LABEL])
        assert len(ups) == 1
        key, state = ups[0]
        assert key == FORM_KEY
        assert state == {"admission": "Y",              # prev 链装载值
                         "schema": "终点抵达图式",
                         "alignment": "部分对齐",
                         "cn_syntax": "需“把”字句",
                         "strategy": "增补方式要素",
                         "needs_review": True}
        assert flashes == [app.ANNOTATE_STASH_FLASH_TEXT]
        assert stub.rerun_count == 1
        assert stub.successes == []                     # RV12：不回潮 st.success
        assert stub.errors == []

    def test_stash_click_persists_edited_values(self, monkeypatch):
        """暂存快照取表单**当前值**：用户改动的控件值原样入快照。"""
        _, _, ups, _, _ = self._render(
            monkeypatch,
            my_subs=[],                                 # 无 prev → 默认装载
            click=[app.ANNOTATE_STASH_BUTTON_LABEL],
            widget_returns={"准入标签": "N", "汉语句法特征": "手改句法",
                            "存疑": True})
        key, state = ups[0]
        assert key == FORM_KEY
        assert state["admission"] == "N"
        assert state["cn_syntax"] == "手改句法"
        assert state["needs_review"] is True
        assert state["schema"] == "" and state["alignment"] == ""

    def test_stash_failure_error_no_flash_no_rerun(self, monkeypatch):
        """暂存失败（库不可用/超长）：st.error 本轮直出，不 flash 不 rerun。"""
        stub, flashes, _, _, _ = self._render(
            monkeypatch, click=[app.ANNOTATE_STASH_BUTTON_LABEL],
            upsert_result=False)
        assert flashes == [] and stub.rerun_count == 0
        assert stub.errors

    def test_submit_success_deletes_stash(self, monkeypatch):
        """提交成功：submit_annotation 后 delete_draft(form_key) 闭环。"""
        stub, _, _, dels, subs = self._render(
            monkeypatch, click=["📤 提交本义位标注"])
        assert len(subs) == 1 and subs[0]["sense_id"] == SENSE_ID
        assert dels == [FORM_KEY]
        assert stub.successes

    def test_submit_failure_keeps_stash(self, monkeypatch):
        """提交失败：不清除暂存（WIP 仍在）。"""
        _, _, _, dels, _ = self._render(
            monkeypatch, click=["📤 提交本义位标注"], submit_result=False)
        assert dels == []

    def test_stash_click_does_not_submit(self, monkeypatch):
        """点暂存不触发提交链（submit_annotation 零调用）。"""
        _, _, _, _, subs = self._render(
            monkeypatch, click=[app.ANNOTATE_STASH_BUTTON_LABEL])
        assert subs == []

    def test_rv12_wiring_source_discipline(self):
        """RV12 源码哨兵：暂存分支 ui_kit.flash + st.rerun；form_key 约定。"""
        src = inspect.getsource(app.render_submission_flow)
        assert "st.form_submit_button(ANNOTATE_STASH_BUTTON_LABEL)" in src
        assert "ui_kit.flash(ANNOTATE_STASH_FLASH_TEXT)" in src
        assert "st.rerun()" in src
        assert "f\"{ANNOTATE_STASH_FORM_KEY_PREFIX}{sid}\"" in src
        assert app.ANNOTATE_STASH_FORM_KEY_PREFIX == "annotate_draft_"


# ============================================
# 任务 2：重标闸批量查询等价性（双 SQL 假游标同数据集对照）
# ============================================

class _Ctx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class _DualSqlCursor:
    """双 SQL 假体：同一 join 结果数据集上执行旧逐条 SQL 与新批量 SQL。

    数据集行 = {sense_id, cs_status, cs_row_id}（cs_row_id 模拟 cs_senses.id，
    供排序）；旧 SQL（WHERE o.id = %s）按单义位取最小 cs_row_id 一行
    （LIMIT 1 同构），新 SQL（WHERE o.id IN …）按整批返回按 cs_row_id 全序
    排列的行（ORDER BY s.id 同构）。
    """

    def __init__(self, dataset):
        self.dataset = list(dataset)
        self.executed = []
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "WHERE o.id = %s" in sql:
            sid = params[1]
            rows = sorted((r for r in self.dataset if r["sense_id"] == sid),
                          key=lambda r: r["cs_row_id"])[:1]
        elif "WHERE o.id IN" in sql:
            wanted = set(params[1:])
            rows = sorted((r for r in self.dataset if r["sense_id"] in wanted),
                          key=lambda r: r["cs_row_id"])
        elif "SELECT code FROM categories" in sql:
            rows = [{"code": "RUN"}] if params and params[0] == "RUN" else []
        else:
            rows = []                              # coder/headword/dup 查询
        self._result = rows

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _ds(sense_id, cs_row_id, status):
    """数据集行构造器：oald_senses.id × cs_senses(id, status) 映射行。"""
    return {"sense_id": sense_id, "cs_status": status, "cs_row_id": cs_row_id}


# 夹具设计（多命中 / 单命中 / 未命中 / NULL / 大小写混排）：
#   501 多命中（id 7 merged < id 11 保留）→ 最小 id 胜出 → eligible
#   502 多命中（id 5 保留 < id 9 split）→ 最小 id 非裁决态 → skipped
#   503 单命中 merged / 504 单命中 split → eligible
#   505 未命中（无映射行）→ skipped
#   506 状态 NULL → skipped（原样进 reason repr）
#   507 「Merged」大小写混排 → lower() 归一 → eligible
EQUIV_SCENARIOS = [
    ("multi_hit_min_id_divided",
     [_ds(501, 11, "保留"), _ds(501, 7, "merged")], [501]),
    ("multi_hit_min_id_not_divided",
     [_ds(502, 5, "保留"), _ds(502, 9, "split")], [502]),
    ("single_hit_merged", [_ds(503, 21, "merged")], [503]),
    ("single_hit_split", [_ds(504, 22, "split")], [504]),
    ("no_hit_unmapped", [], [505]),
    ("null_status_hit", [_ds(506, 30, None)], [506]),
    ("case_insensitive_status", [_ds(507, 40, "Merged")], [507]),
    ("mixed_batch",
     [_ds(501, 11, "保留"), _ds(501, 7, "merged"), _ds(502, 5, "保留"),
      _ds(503, 21, "merged"), _ds(504, 22, "split"), _ds(506, 30, None)],
     [501, 502, 503, 504, 505, 506]),
]


def _legacy_gate(dataset, study_code, ids):
    """原实现基线（改动前逐义位循环）：每 sense_id 单发 _CS_STATUS_SQL
    （ORDER BY s.id LIMIT 1），判定逻辑与改动前逐字一致（reason 换短词
    便于对照）。"""
    cursor = _DualSqlCursor(dataset)
    eligible, skipped = [], []
    for sid in ids:
        cursor.execute(_CS_STATUS_SQL, (study_code, sid))
        row = cursor.fetchone()
        if not row:
            skipped.append({"sense_id": sid, "token": "unmapped"})
            continue
        status = str(row.get("cs_status") or "").strip().lower()
        if status not in flow.DIVIDED_SENSE_STATUSES:
            skipped.append({"sense_id": sid, "token": "status"})
            continue
        eligible.append(sid)
    return eligible, skipped


def _new_gate(monkeypatch, dataset, ids):
    """新实现：整链跑 create_reannotation_tasks（批量查询路径），取闸输出。"""
    cursor = _DualSqlCursor(dataset)
    monkeypatch.setattr(flow, "get_db_cursor",
                        lambda autocommit=True: _Ctx(cursor))
    result = create_reannotation_tasks("motion", list(ids), 1, 1, actor=None)

    def _token(reason):
        if reason.startswith("未映射到语义分析义位"):
            return "unmapped"
        if reason.startswith("cs_senses 状态为"):
            return "status"
        return reason

    skipped = [{"sense_id": s["sense_id"], "token": _token(s["reason"])}
               for s in result["skipped"]]
    return result.get("eligible_sense_ids", []), skipped


class TestCsStatusBatchEquivalence:
    """RV19-1 消缺等价性：批量 IN 查询与原逐义位单发同数据集同输出。"""

    @pytest.mark.parametrize("name,dataset,ids", EQUIV_SCENARIOS,
                             ids=[s[0] for s in EQUIV_SCENARIOS])
    def test_batch_gate_same_output_as_per_sense(self, monkeypatch,
                                                 name, dataset, ids):
        eligible_old, skipped_old = _legacy_gate(dataset, "RUN", ids)
        eligible_new, skipped_new = _new_gate(monkeypatch, dataset, ids)
        assert eligible_new == eligible_old
        assert skipped_new == skipped_old

    def test_multi_hit_takes_min_cs_row_id(self, monkeypatch):
        """多命中取最小 cs_senses.id（= 原 ORDER BY s.id LIMIT 1 语义）：
        最小 id 行裁决态与非裁决态两个方向都锁定。"""
        for dataset, expect_eligible in (
            ([_ds(501, 11, "保留"), _ds(501, 7, "merged")], True),
            ([_ds(501, 5, "保留"), _ds(501, 9, "split")], False),
        ):
            cmap = self._map(monkeypatch, dataset, [501])
            assert (501 in cmap) is True
            assert (str(cmap[501]).strip().lower()
                    in flow.DIVIDED_SENSE_STATUSES) is expect_eligible

    def test_map_unmapped_ids_absent_not_none(self, monkeypatch):
        """未映射 id 不入键（与原 fetchone() is None 分支对齐；.get() 混淆
        NULL 与未映射是禁止用法）。"""
        cmap = self._map(monkeypatch, [_ds(501, 7, "merged")], [501, 999])
        assert 501 in cmap and 999 not in cmap
        assert "sense_id" not in [k for k in cmap if not isinstance(k, int)]

    def test_map_preserves_null_status_value(self, monkeypatch):
        """映射行状态为 NULL：键在场、值为 None（与未映射区分）。"""
        cmap = self._map(monkeypatch, [_ds(506, 30, None)], [506])
        assert 506 in cmap and cmap[506] is None

    def test_map_empty_ids_no_roundtrip(self, monkeypatch):
        """空 id 清单：零 SQL 往返（防御位）。"""
        cursor = _DualSqlCursor([])
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        assert _fetch_cs_status_map("RUN", []) == {}
        assert cursor.executed == []

    def _map(self, monkeypatch, dataset, ids):
        cursor = _DualSqlCursor(dataset)
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        return _fetch_cs_status_map("RUN", list(ids))


class TestBatchSqlContract:
    """批量语句契约：JOIN 键与逐条基准逐字一致 + 接线哨兵。"""

    def test_join_keys_identical_to_per_sense_sql(self):
        """映射口径逐字一致：FROM oald_senses → WHERE 之前的 JOIN 段两语句
        完全相同（同一 JOIN 键 —— 等价性前提，任一侧改动须重跑等价测试）。"""
        def join_seg(sql):
            return sql.split("FROM oald_senses o")[1].split("WHERE")[0]

        assert join_seg(_CS_STATUS_BATCH_SQL) == join_seg(_CS_STATUS_SQL)
        assert _CS_STATUS_BATCH_SQL.strip().endswith("ORDER BY s.id")
        assert _CS_STATUS_SQL.strip().endswith("ORDER BY s.id LIMIT 1")

    def test_select_shape(self):
        """批量语句回 sense_id＋cs_status 两列（Python 侧按 sense_id 聚合）。"""
        assert "SELECT o.id AS sense_id, s.status AS cs_status " in \
            _CS_STATUS_BATCH_SQL

    def test_gate_wired_to_batch_query(self):
        """接线哨兵：create_reannotation_tasks 走 _fetch_cs_status_map 单条
        查询；闸循环体内零 cursor.execute（逐义位单发不回潮）。"""
        src = inspect.getsource(flow.create_reannotation_tasks)
        assert "_fetch_cs_status_map(study_code, ids)" in src
        gate = src[src.index("for sid in ids:"):src.index("if not eligible:")]
        assert "cursor.execute" not in gate

    def test_batch_roundtrip_count(self, monkeypatch):
        """RV19-1 消缺量化：N 个义位的闸核对只发 1 条 cs 状态查询。"""
        dataset = [_ds(501, 7, "merged"), _ds(503, 21, "merged")]
        cursor = _DualSqlCursor(dataset)
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        result = create_reannotation_tasks("motion", [501, 503, 505], 1, 1,
                                           actor=None)
        assert result["ok"] is True
        cs_sqls = [sql for sql, _p in cursor.executed if "FROM oald_senses o" in sql]
        assert len(cs_sqls) == 1                  # 3 个义位 → 1 条 IN 查询
        assert "WHERE o.id IN" in cs_sqls[0]
