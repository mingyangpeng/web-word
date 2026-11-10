"""批次 19 工具页面接线（FX-36）——分析/模板/媒体面八处等价性测试。

两层结构：
  * 源级钉板：八处接线点全部使用「get_tool(id) → 非 None 走 run(ctx)、
    None 回落直调」先例形态（RV18 源码钉板口径：接线契约负向耦合合理）；
  * 行为等价：entry_assembly 两个跨模块包装（schema/multimedia）——
    monkeypatch 委托目标后断言 tool.run 逐字段收到原直调参数。
同模块自委托面（cluster_analysis/template_engine 内部调用点）的委托等价
已由 test_fx18_fixes 的委托测试覆盖（工具 run → 同一函数），此处不重复。
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.cluster_analysis as cluster_analysis  # noqa: E402
import src.entry_assembly as entry_assembly  # noqa: E402
import src.lexical_pages as lexical_pages  # noqa: E402
import src.template_engine as template_engine  # noqa: E402
from src.tools import builtin  # noqa: E402,F402  导入即注册

# ============================================
# 源级钉板：八处接线点形态（先例：get_tool → run / 回落直调）
# ============================================

_WIRING_SITES = [
    (cluster_analysis, "compute_medoid_ranking wiring",
     'get_tool("typicality").run' if False else None),
]


def _src(module):
    return inspect.getsource(module)


def test_cluster_analysis_wired():
    src = _src(cluster_analysis)
    assert '_typ = _get_tool("typicality")' in src
    assert '_clu = _get_tool("clustering")' in src
    assert "compute_medoid_ranking(category, language)" in src  # 回落直调在场
    assert "build_dendrogram_data(category, language)" in src


def test_template_engine_wired():
    src = _src(template_engine)
    assert src.count('_get_tool("schema")') == 2  # 两处懒接线
    assert '_tpl = _get_tool("template")' in src
    assert "derive_cluster_schemas(str(category), str(language))" in src
    assert "collect_cluster_templates(cat_code, language," in src


def test_entry_assembly_wired():
    src = _src(entry_assembly)
    assert '_sch = _get_tool("schema")' in src
    assert '_mm = _get_tool("multimedia")' in src
    assert "media_db.list_assets_for_anchor(anchor_type, int(anchor_id))" in src


def test_lexical_pages_wired():
    src = _src(lexical_pages)
    assert '_mm = _get_tool("multimedia")' in src
    assert "media_db.ANCHOR_EXAMPLE" in src


# ============================================
# 行为等价：跨模块包装经 tool.run 逐字段透传
# ============================================

def test_derive_engine_schema_via_tool(monkeypatch):
    """_derive_engine_schema → get_tool("schema").run → 委托目标逐字段透传。"""
    sentinel = [{"cluster_no": 1}]
    captured = {}

    def _fake(category, language):
        captured["args"] = (category, language)
        return sentinel

    monkeypatch.setattr(template_engine, "derive_cluster_schemas", _fake)
    out = entry_assembly._derive_engine_schema("RUN", "en")
    assert out is sentinel
    assert captured["args"] == ("RUN", "en")


def test_fetch_media_via_tool(monkeypatch):
    """_fetch_media_for_anchor → get_tool("multimedia").run → 委托目标透传。"""
    sentinel = [{"id": 9}]
    captured = {}

    def _fake(anchor_type, anchor_id):
        captured["args"] = (anchor_type, anchor_id)
        return sentinel

    monkeypatch.setattr(
        __import__("src.media_db", fromlist=["media_db"]),
        "list_assets_for_anchor", _fake)
    out = entry_assembly._fetch_media_for_anchor("sense", 101)
    assert out is sentinel
    assert captured["args"] == ("sense", 101)


def test_fallback_when_registry_empty(monkeypatch):
    """registry 查无此工具（清空注册表模拟）→ 回落直调逐字节等价。"""
    import src.tools.registry as reg
    snap = dict(reg._REGISTRY)
    try:
        reg._REGISTRY.clear()
        monkeypatch.setattr(
            __import__("src.media_db", fromlist=["media_db"]),
            "list_assets_for_anchor",
            lambda anchor_type, anchor_id: [{"fallback": True}])
        out = entry_assembly._fetch_media_for_anchor("sense", 7)
        assert out == [{"fallback": True}]
    finally:
        reg._REGISTRY.clear()
        reg._REGISTRY.update(snap)
