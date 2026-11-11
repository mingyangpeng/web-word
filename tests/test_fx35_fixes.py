"""FX-35 回归：工具 run() 页面接线（批次 19，规范 §4「页面经中央注册表调工具」）
＋ RV15-3 侧边栏「继续：…」灰注最小件。

接线范围与等价锁（照 src/semantic_search.py corpus/semantic 接线先例：
get_tool(id)，非 None 走 tool.run(ctx)，None 回落直调逐字节等价）：

  1. admission（app.py 提交表单）：submit_annotation("motion", sid,
     "admission", coder_id, payload) 改经 get_tool("admission").run(...) ——
     AppTest 真表单提交＋数据层打桩：monkeypatch 数据层
     annotation_flow.submit_annotation，断言 tool.run 收到页面原直调参数
     （category/sense_id/coder_id/payload 逐字段一致）、数据层收到
     task_type="admission"（工具身份固定，不入 ctx）＋ ai_assisted=True
     （schema 默认与直调形参默认同值）——落库行为（覆盖更新语义的入参
     契约与返回码→成功/失败提示分流）不变；
  2. reliability（src/reliability.py 信度报告页）：run_reliability(category,
     task_type, created_by=...) 改经 get_tool("reliability").run(...) ——
     同模块自委托；AppTest＋打桩：ReliabilityTool.run 间谍记录 ctx，数据层
     run_reliability 桩记录 kwargs，断言每次取数都经工具且三参逐字段一致
     （features_meta 不入 ctx，与直调一样走形参默认 None 自动读范畴包）；
  3. RV15-3 侧边栏灰注（两态）：登录落地分支 2（续接点命中）落
     _RESUME_HINT_KEY 一次性旗标 → 侧边栏 radio 上方 caption
     「↩︎ 续接上次：{页名}」；未命中 / 旗标页键不在当前角色可见集不显示；
     登出全清自然回收（键不在 _LOGOUT_KEEP_KEYS，RV12-1 只读不直写
     widget 键——旗标是自有键，radio 的 "page" 键零接触）。

口径注记（照实，不遮掩）：
  * task_type 不在 admission params_schema 内 —— 它是工具身份（run 内固定
    task_type="admission" 委托 submit_annotation），不是页面可调参数；页面
    原直调传的也是字面 "admission"，语义一致，**schema 无出入、无需扩面**；
  * feature_coding / alignment 两工具当前无页面调用点（标注平台只做
    admission UI，图式/对齐作为 admission payload 旁注字段采集）——接线
    欠账照实挂账（见交付报告）；
  * 两处接线点均不在 st.cache_data 函数体内（submit_annotation 是 DB 写、
    run_reliability 是计算＋落库，页面均无缓存包装）——缓存语义保留无涉。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import pytest  # noqa: E402

import src.app as app_module  # noqa: E402
import src.annotation_flow as annotation_flow  # noqa: E402
import src.reliability as reliability  # noqa: E402
from src.tools.builtin.admission_tool import AdmissionTool  # noqa: E402
from src.tools.builtin.reliability_tool import ReliabilityTool  # noqa: E402
from src.tools.registry import get_tool  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
TIMEOUT = 120

# 探针会话（结构与 verify_login_full 输出一致；仅注入 session_state 不触库）
_ADMIN = {"id": 901, "username": "fx35_admin", "display_name": "管理员",
          "role": "admin", "roles": ["dict_admin", "sys_admin"]}
_ANNOTATOR = {"id": 12, "username": "fx35_ann", "display_name": "标注员",
              "role": "annotator", "roles": ["annotator"]}
_REVIEWER = {"id": 7, "username": "fx35_rev", "display_name": "审校",
             "role": "reviewer", "roles": ["reviewer"]}
_VIEWER = {"id": 903, "username": "fx35_view", "display_name": "只读",
           "role": "viewer", "roles": ["viewer"]}


@pytest.fixture(autouse=True)
def _clean_session_flags():
    """裸模式会话旗标不跨用例泄漏（_RESUME_HINT_KEY / ui_kit flash 队列）。"""
    yield
    import streamlit as st

    st.session_state.pop(app_module._RESUME_HINT_KEY, None)
    from src import ui_kit

    ui_kit.st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _exceptions(at):
    return [str(e.value) for e in at.exception]


# ============================================
# 1. admission 接线等价锁（AppTest 真表单＋数据层打桩）
# ============================================

# 提交流只读面打桩的 canned 数据（字段结构与 mysql_db 两函数一致）
_PROGRESS = [{"verb": "walk", "total": 3, "done": 1},
             {"verb": "run", "total": 2, "done": 0}]

_SENSE = {
    "id": 501,
    "sense_index": 1,
    "en_ndef": "to move on foot at a moderate pace",
    "definition": "to move on foot at a moderate pace",
    "grammar": "v.",
    "examples": [{"en": "She walks to school.", "zh": "她走路去学校。"}],
    "is_idiom": 0,
    "llm_tag": "",
    "llm_schema": "",
    "llm_align": "",
    "cn_syntax": "",
    "translation_strategy": "",
    "needs_review": 0,
    "prototype_level": "",
}


def test_admission_submit_routes_through_registry_tool(monkeypatch):
    """提交表单改经 get_tool("admission").run —— tool.run 收到页面原直调参数
    （category/sense_id/coder_id/payload 逐字段一致），数据层收到
    task_type="admission"（工具身份固定）＋ai_assisted=True（schema 默认＝
    直调形参默认）。

    打桩口径（fx29 同款）：AppTest 以脚本形态执行 app.py，脚本命名空间每轮
    重导数据层名字 —— 桩必须落在**数据层模块属性**上（mysql_db /
    annotation_flow），脚本重导即取到桩；工具 run 经 annotation_flow 模块
    属性查找委托，桩必经 tool.run（tool-meditation 由 AdmissionTool.run
    间谍正向证明：ctx_seen 与数据层取数次数相等，绕过工具直调即不等）。
    返回码契约不变：True → 成功提示在场、失败提示不在（落库行为不变）。
    """
    import src.collab_pages as collab_pages
    import src.mysql_db as mysql_db

    ctx_seen = []
    layer_calls = []
    orig_tool_run = AdmissionTool.run

    def spy_tool_run(self, ctx=None):
        ctx_seen.append(dict(ctx or {}))
        return orig_tool_run(self, ctx)

    def fake_submit(**kwargs):
        layer_calls.append(dict(kwargs))
        return True

    monkeypatch.setattr(AdmissionTool, "run", spy_tool_run)
    monkeypatch.setattr(annotation_flow, "submit_annotation", fake_submit)
    # 页面只读面打桩（本用例聚焦接线等价性，不依赖词库灌数/建表）
    monkeypatch.setattr(mysql_db, "get_annotation_progress",
                        lambda: [dict(r) for r in _PROGRESS])
    monkeypatch.setattr(mysql_db, "get_oald_senses", lambda verb: [dict(_SENSE)])
    monkeypatch.setattr(annotation_flow, "get_my_submissions", lambda *a, **k: [])
    monkeypatch.setattr(annotation_flow, "ensure_flow_tables", lambda: None)
    monkeypatch.setattr(collab_pages, "pending_inbox_count", lambda: 0)

    at = _new_at()
    at.session_state["user"] = dict(_ANNOTATOR)
    at.session_state["page"] = "submission"
    at.run()
    assert not at.exception, _exceptions(at)

    radios = [r for r in at.radio if "准入标签" in str(r.label)]
    assert radios, "准入标签 radio 未渲染（页面未走到表单）"
    radios[0].set_value("Y")
    submit = [b for b in at.button
              if b.form_id and "提交本义位标注" in str(b.label)]
    assert submit, "提交按钮未找到"
    submit[0].click()
    at.run()
    assert not at.exception, _exceptions(at)

    # 恰好一次提交，且全部经注册表工具（原直调参数原样透传，无 ai_assisted 键
    # —— 页面未传，与直调一致走默认）
    assert len(ctx_seen) == 1, f"tool.run 调用次数漂移: {ctx_seen}"
    assert ctx_seen[0] == {
        "category": "motion", "sense_id": 501, "coder_id": 12,
        "payload": {"admission": "Y", "needs_review": False},
    }
    # 数据层入参：merge_params 补 schema 默认 ai_assisted=True，task_type 由
    # 工具身份固定 —— 与原直调 submit_annotation("motion", 501, "admission",
    # 12, payload)（ai_assisted 形参默认 True）逐参数等价
    assert layer_calls == [{
        "category": "motion", "sense_id": 501, "task_type": "admission",
        "coder_id": 12, "payload": {"admission": "Y", "needs_review": False},
        "ai_assisted": True,
    }]
    # 返回码→提示分流契约不变（覆盖更新语义的提示文案原样）
    assert any("提交成功" in str(s.value) for s in at.success)
    assert not any("提交失败" in str(e.value) for e in at.error)


def test_admission_tool_pins_task_type_and_ai_assisted_default(monkeypatch):
    """契约面（单元）：task_type 不入 params_schema（工具身份，run 内固定）；
    ai_assisted 缺省由 schema 默认补 True（与 submit_annotation 形参默认
    同值），显式 False 原样透传。"""
    assert "task_type" not in get_tool("admission").params_schema
    seen = []
    monkeypatch.setattr(annotation_flow, "submit_annotation",
                        lambda **kw: (seen.append(dict(kw)), True)[1])
    tool = get_tool("admission")
    assert tool is not None

    assert tool.run({"category": "motion", "sense_id": 1, "coder_id": 2,
                     "payload": {"admission": "Y"}}) is True
    assert seen == [{"task_type": "admission", "category": "motion",
                     "sense_id": 1, "coder_id": 2,
                     "payload": {"admission": "Y"}, "ai_assisted": True}]

    seen.clear()
    tool.run({"category": "motion", "sense_id": 1, "coder_id": 2,
              "payload": {"admission": "N"}, "ai_assisted": False})
    assert seen[0]["ai_assisted"] is False
    assert seen[0]["task_type"] == "admission"


def test_params_schema_covers_page_call_arguments():
    """schema 覆盖哨兵：两工具 params_schema 覆盖页面直调的全部参数键
    （无缺键）——admission 五键、reliability 三键，无需扩面。"""
    admission_schema = set(get_tool("admission").params_schema)
    assert {"category", "sense_id", "coder_id", "payload",
            "ai_assisted"} <= admission_schema
    reliability_schema = set(get_tool("reliability").params_schema)
    assert {"category", "task_type", "created_by"} <= reliability_schema


# ============================================
# 2. reliability 接线等价锁（AppTest＋打桩：同模块自委托）
# ============================================

# 信度页 canned 结果（结构与 run_reliability 返回一致；db_error 缺席 = 库可用）
_RELIABILITY_RESULT = {
    "category": "motion",
    "task_type": "admission",
    "overall_alpha": 0.812,
    "per_feature": {"admission": 0.812},
    "n_coders": 3,
    "n_units": 12,
    "disagreements": [],
    "features_meta": [],
}


def test_reliability_page_routes_through_registry_tool(monkeypatch):
    """信度报告页改经 get_tool("reliability").run —— 同模块自委托：间谍钉在
    ReliabilityTool.run 上证明每次取数都经注册表工具（若页面绕过工具直调，
    ctx_seen 为空即失败）；数据层 run_reliability 桩收到的 kwargs 与原直调
    (category, task_type, created_by=user["id"]) 逐字段一致，且不含
    features_meta（与直调一样走形参默认 None）。"""
    ctx_seen = []
    layer_calls = []
    orig_tool_run = ReliabilityTool.run

    def spy_tool_run(self, ctx=None):
        ctx_seen.append(dict(ctx or {}))
        return orig_tool_run(self, ctx)

    def fake_run_reliability(**kwargs):
        layer_calls.append(dict(kwargs))
        return dict(_RELIABILITY_RESULT)

    monkeypatch.setattr(ReliabilityTool, "run", spy_tool_run)
    monkeypatch.setattr(reliability, "run_reliability", fake_run_reliability)
    import src.collab_pages as collab_pages

    monkeypatch.setattr(collab_pages, "pending_inbox_count", lambda: 0)

    at = _new_at()
    at.session_state["user"] = dict(_REVIEWER)
    at.session_state["page"] = "reliability"
    at.run()
    assert not at.exception, _exceptions(at)

    # 显式选范畴/任务类型（与页面原直调同源的取值），再跑一轮取数
    cat_sb = [s for s in at.selectbox if str(s.label) == "范畴"]
    task_sb = [s for s in at.selectbox if str(s.label) == "任务类型"]
    assert cat_sb and task_sb, "信度页选择器未渲染"
    cat_sb[0].set_value("motion")
    task_sb[0].set_value("admission")
    at.run()
    assert not at.exception, _exceptions(at)

    # 两轮取数全部经工具（首轮默认值＋本轮显式值），无一次绕过
    assert len(ctx_seen) == len(layer_calls) == 2, (
        f"取数次数漂移: ctx={ctx_seen}, layer={layer_calls}")
    assert ctx_seen[-1] == {"category": "motion", "task_type": "admission",
                            "created_by": 7}
    assert layer_calls[-1] == {"category": "motion", "task_type": "admission",
                               "created_by": 7}
    # 返回值契约不变：canned 结果照常渲染（overall 大数字 + 达标判定）
    assert any("0.812" in str(m.value) for m in at.markdown)
    assert any("达标" in str(m.value) for m in at.markdown)


# ============================================
# 3. RV15-3 侧边栏「继续：…」灰注（两态＋旗标生命周期）
# ============================================

def test_landing_branch2_sets_resume_hint_flag(monkeypatch):
    """分支 2（续接点命中）：flash 照旧 ＋ resume 页键落一次性旗标
    （_RESUME_HINT_KEY，侧栏灰注数据源；落地解析只在登录路径调用一次）。"""
    import streamlit as st

    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    app_module.set_resume_page_loader(lambda uid: "cluster")
    try:
        assert app_module._landing_page_for(_VIEWER) == "cluster"
        assert st.session_state.get(app_module._RESUME_HINT_KEY) == "cluster"
        from src import ui_kit

        queue = ui_kit.st.session_state.get(ui_kit._FLASH_QUEUE_KEY) or []
        assert any("已回到上次工作位置" in str(m.get("message")) for m in queue)
    finally:
        app_module.set_resume_page_loader(None)


def test_landing_other_branches_do_not_set_flag(monkeypatch):
    """分支 1（有待办）/ 分支 3（首次）不落旗标 —— 灰注仅续接点命中显示。"""
    import streamlit as st

    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    assert app_module._landing_page_for(_VIEWER) == "search"      # 分支 3
    assert app_module._RESUME_HINT_KEY not in st.session_state
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
    assert app_module._landing_page_for(_ADMIN) == "ai_hub"       # 分支 1
    assert app_module._RESUME_HINT_KEY not in st.session_state


def test_sidebar_resume_caption_shown_when_flag_set():
    """灰注两态·显示：旗标在且页键在当前角色可见集 → radio 上方 caption
    「↩︎ 续接上次：{页名}」（cluster 页名含「语义分析」）。"""
    at = _new_at()
    at.session_state["user"] = dict(_VIEWER)
    at.session_state[app_module._RESUME_HINT_KEY] = "cluster"
    at.run()
    assert not at.exception, _exceptions(at)
    captions = [str(c.value) for c in at.sidebar.caption]
    assert any(c.startswith("↩︎ 续接上次：") and "语义分析" in c
               for c in captions), captions


def test_sidebar_resume_caption_hidden_without_flag():
    """灰注两态·隐藏（未命中）：无旗标（首次落地/已消费）→ caption 不渲染。"""
    at = _new_at()
    at.session_state["user"] = dict(_VIEWER)
    at.run()
    assert not at.exception, _exceptions(at)
    captions = [str(c.value) for c in at.sidebar.caption]
    assert not any("续接上次" in c for c in captions), captions


def test_sidebar_resume_caption_hidden_for_invisible_page():
    """灰注两态·隐藏（越权）：旗标页键不在当前角色可见集（viewer ×
    dict_admin）→ 不显示（与 radio 残留页回退同口径）。"""
    at = _new_at()
    at.session_state["user"] = dict(_VIEWER)
    at.session_state[app_module._RESUME_HINT_KEY] = "dict_admin"
    at.run()
    assert not at.exception, _exceptions(at)
    captions = [str(c.value) for c in at.sidebar.caption]
    assert not any("续接上次" in c for c in captions), captions


def test_resume_hint_key_recycled_on_logout():
    """登出全清自然回收：旗标键不在 _LOGOUT_KEEP_KEYS，_logout 全清后消失
    （共享终端换人不留上一人的续接痕迹，R1-6 口径）。"""
    import streamlit as st

    assert app_module._RESUME_HINT_KEY not in app_module._LOGOUT_KEEP_KEYS
    st.session_state.pop("page", None)  # 不带残留页：不触发续接点落库写路径
    st.session_state[app_module._RESUME_HINT_KEY] = "cluster"
    app_module._logout()
    assert app_module._RESUME_HINT_KEY not in st.session_state


def test_resume_hint_never_writes_page_widget_key():
    """RV12-1 哨兵：灰注段只读自有键 _RESUME_HINT_KEY（session_state.get），
    无任何下标写 —— 页面 radio 的 "page" widget 键零接触。"""
    import inspect

    src = inspect.getsource(app_module.render_sidebar)
    start = src.find("_resume_hint")
    end = src.find("七区菜单导航")  # 批次 22 按钮式侧边栏后的区块名
    if end == -1:
        end = src.find("七区菜单分组")
    assert start != -1 and end != -1 and start < end, "灰注段未找到（结构漂移？）"
    segment = src[start:end]
    assert "session_state[" not in segment, segment
    assert "session_state.get(_RESUME_HINT_KEY)" in segment
