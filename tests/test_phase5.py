"""
Phase 5 实时生成接入 (Live Generation) tests — LLM-01/02/03/04.

覆盖：
- 适配器优先级 DB → 实时 LLM → MOCK → fallback（LLM-01/LLM-02）
- LLM 结果持久化到 MySQL 的契约（LLM-03）
- API 密钥缺失/调用异常时的降级不崩溃（LLM-04）

所有外部依赖（智谱 API、MySQL）均通过 monkeypatch 隔离，测试不触网、不连库。
"""

import json
import os
import sys

import pytest

# Ensure project root on path so `from src.xxx` imports resolve under pytest.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.app as app_module  # noqa: E402
from src.app import get_display_definition  # noqa: E402
from src import llm_api  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402


RUN_TIMEOUT = 30

_LIVE_UNREACHABLE = (
    "外部依赖未被 monkeypatch：测试不得真实调用智谱 API / MySQL"
)


@pytest.fixture(autouse=True)
def _clear_display_def_cache():
    """清掉 get_display_definition 的会话级缓存。

    get_display_definition 现在按 verb 缓存解析结果（避免一次 rerun 里
    三张卡片各触发一次 LLM）。bare 模式下 st.session_state 是进程级全局，
    不清的话同 verb 的适配器分支测试会互相读到上一步的缓存结果。
    """
    import streamlit as st

    st.session_state.pop("_display_def_cache", None)
    yield
    st.session_state.pop("_display_def_cache", None)


@pytest.fixture(autouse=True)
def _no_external_io(monkeypatch):
    """默认把所有外部依赖替换为「不可达」，各用例再按需覆盖。

    这样任何遗漏的 patch 都会立刻显式失败，而不是静默触网或连库。
    """

    def _boom(*args, **kwargs):
        raise AssertionError(_LIVE_UNREACHABLE)

    monkeypatch.setattr(app_module, "get_definition_by_verb", _boom, raising=False)
    monkeypatch.setattr(app_module, "get_definition", _boom, raising=False)
    monkeypatch.setattr(app_module, "insert_definition", _boom, raising=False)
    monkeypatch.setattr(llm_api, "get_definition", _boom, raising=False)
    yield


# ============================================
# Task 1 — 单元测试：适配器契约与优先级
# ============================================
def test_parse_maps_traditional_optimized():
    """_parse_llm_response 映射 traditional/optimized，同时保留 chinese_ndef（D-03）。"""
    payload = json.dumps(
        {
            "traditional": "T传统",
            "optimized": "O优化",
            "chinese_ndef": "C中文",
            "semantic_table": {"manner": "m"},
            "example": "e",
        },
        ensure_ascii=False,
    )

    parsed = llm_api._parse_llm_response(payload, "跑进来")

    assert parsed is not None
    assert parsed["traditional"] == "T传统"
    assert parsed["optimized"] == "O优化"
    assert parsed["chinese_ndef"] == "C中文"


def test_adapter_db_branch(monkeypatch):
    """DB 命中直接返回，不触发 LLM（155 个已入库动词走此路径）。"""
    row = {
        "verb": "跑进来",
        "chinese_ndef": json.dumps(
            {"traditional": "T", "optimized": "O"}, ensure_ascii=False
        ),
        "semantic_table": json.dumps({"manner": "M"}, ensure_ascii=False),
        "example_sentence": "例句",
    }
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: row, raising=False
    )

    calls = []
    monkeypatch.setattr(
        app_module,
        "get_definition",
        lambda *a, **k: calls.append(a) or None,
        raising=False,
    )

    result = get_display_definition("跑进来")

    assert result["traditional"] == "T"
    assert result["optimized"] == "O"
    assert result["semantic_table"] == {"manner": "M"}
    assert result["example"] == "例句"
    assert calls == [], "DB 命中时不应调用 LLM"


def test_adapter_legacy_plain_row(monkeypatch):
    """历史行的 chinese_ndef 为纯文本时按 traditional 处理，不报错。"""
    row = {
        "chinese_ndef": "旧格式纯文本释义",
        "semantic_table": {"manner": "M"},
        "example_sentence": "旧例句",
    }
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: row, raising=False
    )

    result = get_display_definition("跑进来")

    assert result["traditional"] == "旧格式纯文本释义"
    assert result["optimized"] == ""


def test_adapter_llm_persist(monkeypatch):
    """LLM 生成成功后按契约写入 MySQL（LLM-03）。"""
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: None, raising=False
    )
    generated = {
        "verb": "新动词",
        "traditional": "T新",
        "optimized": "O新",
        "chinese_ndef": "T新",
        "semantic_table": {"manner": "方式", "path": "路径"},
        "example": "例句",
    }
    monkeypatch.setattr(
        app_module, "get_definition", lambda verb, *a, **k: generated, raising=False
    )

    captured = {}

    def _fake_insert(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(app_module, "insert_definition", _fake_insert, raising=False)

    result = get_display_definition("新动词")

    assert result["traditional"] == "T新"
    assert result["optimized"] == "O新"
    assert captured, "LLM 成功路径必须调用 insert_definition 持久化"
    assert captured["verb"] == "新动词"

    stored = json.loads(captured["chinese_ndef"])
    assert stored["traditional"] == "T新"
    assert stored["optimized"] == "O新"
    assert isinstance(captured["semantic_table"], dict)
    assert captured["semantic_table"]["manner"] == "方式"


def test_adapter_mock_fallback(monkeypatch):
    """DB 与 LLM 均失败时退回 MOCK_DEFINITIONS（D-02）。"""
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: None, raising=False
    )
    monkeypatch.setattr(app_module, "get_definition", lambda verb, *a, **k: None, raising=False)

    assert "跑进来" in app_module.MOCK_DEFINITIONS

    result = get_display_definition("跑进来")

    assert "传统释义" in result["traditional"]
    assert result["semantic_table"]["manner"]


def test_adapter_final_fallback(monkeypatch):
    """DB/LLM/MOCK 全部失败时返回最终兜底字典（D-02 最后一档）。"""
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: None, raising=False
    )
    monkeypatch.setattr(app_module, "get_definition", lambda verb, *a, **k: None, raising=False)

    verb = "该项目未收录的动词XYZ"
    assert verb not in app_module.MOCK_DEFINITIONS

    result = get_display_definition(verb)

    assert set(result) == {"traditional", "optimized", "semantic_table", "example"}
    assert isinstance(result["semantic_table"], dict)
    # 五元模型必须齐全：缺任意一键都会让对应语义行永远显示「待生成」。
    assert set(result["semantic_table"]) == {
        "manner", "path", "direction", "aspect", "scope",
    }
    # 兜底释义要能表明是该动词的释义（而不是别的词的残留内容）。
    assert verb in result["traditional"]


def test_adapter_no_crash_on_llm_exception(monkeypatch):
    """LLM 抛异常时不崩溃，降级到 MOCK（D-06 / LLM-04）。"""
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: None, raising=False
    )
    monkeypatch.setattr(
        app_module,
        "get_definition",
        lambda verb, *a, **k: (_ for _ in ()).throw(RuntimeError("密钥缺失")),
        raising=False,
    )

    result = get_display_definition("跑进来")

    assert "传统释义" in result["traditional"]
    assert isinstance(result["semantic_table"], dict)


def test_adapter_rejects_illegal_input(monkeypatch):
    """非法输入（SQL/XSS）在适配器入口被拒绝，绝不进入 LLM 提示词（T-05-01）。"""
    monkeypatch.setattr(
        app_module, "get_definition_by_verb", lambda verb: None, raising=False
    )

    called = []
    monkeypatch.setattr(
        app_module,
        "get_definition",
        lambda *a, **k: called.append(a) or None,
        raising=False,
    )

    result = get_display_definition("跑进来'; DROP TABLE definitions; --")

    assert isinstance(result["semantic_table"], dict)
    assert called == [], "非法输入不得进入 LLM 调用"


# ============================================
# Task 2 — 集成测试：AppTest 加载与结果渲染
# ============================================
def test_app_loads():
    """改接后应用可加载，无导入/运行期异常。"""
    at = AppTest.from_file("src/app.py")
    at.run(timeout=RUN_TIMEOUT)

    assert at.exception == []


def test_result_render_no_mock_hardcode():
    """展示态下四卡区域渲染成功，且渲染层不再硬编码 MOCK。"""
    at = AppTest.from_file("src/app.py")
    at.run(timeout=RUN_TIMEOUT)

    at.session_state["verb_result"] = "跑进来"
    at.session_state["show_result"] = True
    at.run(timeout=RUN_TIMEOUT)

    assert at.exception == []
    assert any("结果展示" in m.value for m in at.markdown)
    assert any("核心释义与多维辨异" in m.value for m in at.markdown)
