"""工具插件中央注册表（src/tools）测试。

覆盖（纯进程内注册表，**无需 MySQL**）：
  1. 注册/查询：register（ToolSpec 实例与 dataclass 子类两种形态）、
     get_tool、list_tools（排序 + enabled_only 过滤）、tools_for_stage；
  2. 重复 id 拒绝：RegistryError；非法字段（空 id/名、ai_hooks 越界）拒绝；
  3. 依赖校验：默认探针口径（无探针放行 / 探针 False / 探针抛异常）、
     mock check_deps（覆写多态）经 selfcheck 汇总生效；
  4. export_permission 默认值：架构 §15 导出纪律默认归词典管理员
     （dict_admin），显式覆盖可改；
  5. 内置试点三工具（typicality / semantic_search / template）：契约字段、
     run 薄包装委托（monkeypatch 目标公开函数验证参数合并与透传）、
     render 留批次 2（NotImplementedError）。
"""

import dataclasses
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import cluster_analysis, semantic_search, template_engine  # noqa: E402
from src.tools import builtin  # noqa: E402,F401  导入即注册内置三工具
from src.tools import registry as reg  # noqa: E402
from src.tools.registry import (  # noqa: E402
    RegistryError,
    ToolSpec,
    get_tool,
    list_tools,
    merge_params,
    register,
    register_dep_probe,
    selfcheck,
    set_enabled,
    tools_for_stage,
    unregister,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """每用例前后快照/还原注册表、启用位与探针，测试互不污染。"""
    snap_tools = dict(reg._REGISTRY)
    snap_enabled = set(reg._ENABLED)
    snap_probes = dict(reg._DEP_PROBES)
    yield
    reg._REGISTRY.clear()
    reg._REGISTRY.update(snap_tools)
    reg._ENABLED.clear()
    reg._ENABLED.update(snap_enabled)
    reg._DEP_PROBES.clear()
    reg._DEP_PROBES.update(snap_probes)


def _spec(tool_id: str = "dummy", stage: str = "dummy_stage", **kw) -> ToolSpec:
    kw.setdefault("name", "测试假工具")
    kw.setdefault("version", "0.0.1")
    return ToolSpec(id=tool_id, stage=stage, **kw)


# ============================================
# 1. 注册 / 查询
# ============================================

class TestRegistrationAndLookup:
    def test_register_instance_and_get_tool(self):
        spec = _spec("dummy_a")
        assert register(spec) is spec          # 返回原参数（装饰器可用）
        assert get_tool("dummy_a") is spec     # 注册表存原实例
        assert get_tool("no_such_tool") is None

    def test_register_class_decorator(self):
        @register
        @dataclasses.dataclass
        class DummyClassTool(ToolSpec):
            id: str = "dummy_cls"
            name: str = "类装饰器工具"
            version: str = "1.0.0"
            stage: str = "dummy_stage"
            deps: list = dataclasses.field(default_factory=lambda: ["dep_x"])

        assert isinstance(DummyClassTool, type)  # register 返回类本身
        tool = get_tool("dummy_cls")
        assert isinstance(tool, ToolSpec)
        assert tool.name == "类装饰器工具"       # dataclass 默认字段生效
        assert tool.deps == ["dep_x"]
        assert tool.export_permission == "dict_admin"

    def test_register_rejects_non_toolspec(self):
        with pytest.raises(RegistryError):
            register(object())
        with pytest.raises(RegistryError):
            register(dict)

    def test_register_rejects_invalid_fields(self):
        with pytest.raises(RegistryError):
            register(_spec(""))                 # 空 id
        with pytest.raises(RegistryError):
            register(_spec("dummy_b", name=""))  # 空名
        with pytest.raises(RegistryError):
            register(_spec("dummy_c", ai_hooks=["draft", "bogus"]))  # 通道越界

    def test_list_tools_sorted(self):
        register(_spec("b_tool"))
        register(_spec("a_tool"))
        dummy_ids = [t.id for t in list_tools() if t.id in ("a_tool", "b_tool")]
        assert dummy_ids == ["a_tool", "b_tool"]  # 全表按 id 排序（内置工具同表共存）

    def test_list_tools_enabled_only(self):
        register(_spec("e_on"))
        register(_spec("e_off"))
        assert list_tools(enabled_only=True) == []      # 默认全部未点亮
        assert set_enabled("e_on", True) is True
        assert [t.id for t in list_tools(enabled_only=True)] == ["e_on"]
        assert set_enabled("e_off", True) is True
        assert [t.id for t in list_tools(enabled_only=True)] == ["e_off", "e_on"]
        assert set_enabled("e_off", False) is True      # 熄灭
        assert [t.id for t in list_tools(enabled_only=True)] == ["e_on"]
        assert set_enabled("no_such_tool", True) is False

    def test_tools_for_stage(self):
        # 用不与内置工具撞名的工序名，保证断言与内置注册状态无关
        register(_spec("s1_a", stage="stage_x"))
        register(_spec("s1_b", stage="stage_x"))
        register(_spec("s2_c", stage="stage_y"))
        assert [t.id for t in tools_for_stage("stage_x")] == ["s1_a", "s1_b"]
        assert [t.id for t in tools_for_stage("stage_y")] == ["s2_c"]
        assert tools_for_stage("no_such_stage") == []

    def test_unregister(self):
        register(_spec("gone"))
        set_enabled("gone", True)
        assert unregister("gone") is True
        assert get_tool("gone") is None
        assert list_tools(enabled_only=True) == []      # 启用位一并清理
        assert unregister("gone") is False


# ============================================
# 2. 重复 id 拒绝
# ============================================

class TestDuplicateId:
    def test_duplicate_instance_rejected(self):
        register(_spec("dup"))
        with pytest.raises(RegistryError, match="重复注册"):
            register(_spec("dup"))

    def test_duplicate_class_rejected(self):
        register(_spec("dup2"))

        with pytest.raises(RegistryError, match="重复注册"):
            @register
            @dataclasses.dataclass
            class Dup2(ToolSpec):
                id: str = "dup2"
                name: str = "撞 id"
                version: str = "1.0.0"
                stage: str = "dummy_stage"

        assert get_tool("dup2").name == "测试假工具"  # 原注册未被覆盖


# ============================================
# 3. 依赖校验（探针 + mock check_deps）
# ============================================

class TestCheckDeps:
    def test_unprobed_deps_pass(self):
        # 纯进程内注册表：未登记探针的依赖无法校验，默认放行
        spec = _spec("dep_free", deps=["never_probed_table"])
        assert spec.check_deps() == []

    def test_probe_ok_and_missing(self):
        register_dep_probe("dep_ok", lambda: True)
        register_dep_probe("dep_bad", lambda: False)
        spec = _spec("probed", deps=["dep_ok", "dep_bad"])
        assert spec.check_deps() == ["dep_bad"]

    def test_probe_exception_counts_missing(self):
        def _boom():
            raise RuntimeError("探针炸了")
        register_dep_probe("dep_boom", _boom)
        spec = _spec("probed_boom", deps=["dep_boom"])
        assert spec.check_deps() == ["dep_boom"]    # 异常按缺失处理，不外传

    def test_register_dep_probe_validation(self):
        with pytest.raises(RegistryError):
            register_dep_probe("", lambda: True)
        with pytest.raises(RegistryError):
            register_dep_probe("dep_x", "not-callable")

    def test_mock_check_deps_via_selfcheck(self):
        # mock 口径：覆写 check_deps 后 selfcheck 汇总必须尊重多态结果
        register(_spec("healthy"))
        mock_spec = _spec("mocked", deps=["whatever"])
        mock_spec.check_deps = lambda: ["mock_missing"]
        register(mock_spec)
        report = selfcheck()
        assert {"healthy", "mocked"} <= set(report)  # 内置工具同表共存
        assert report["healthy"] == []
        assert report["mocked"] == ["mock_missing"]


# ============================================
# 4. export_permission 默认值（架构 §15 导出纪律）
# ============================================

class TestExportPermissionDefault:
    def test_defaults_to_dict_admin(self):
        spec = ToolSpec(id="e1", name="n", version="1.0.0", stage="s")
        assert spec.export_permission == "dict_admin"

    def test_explicit_override(self):
        spec = ToolSpec(id="e2", name="n", version="1.0.0", stage="s",
                        export_permission="sys_admin")
        assert spec.export_permission == "sys_admin"

    def test_builtin_tools_keep_default(self):
        for tool_id in ("typicality", "semantic_search", "template"):
            tool = get_tool(tool_id)
            assert tool is not None
            assert tool.export_permission == "dict_admin"


# ============================================
# 5. 参数合并（merge_params，工具 run 共用）
# ============================================

class TestMergeParams:
    SCHEMA = {
        "category": {"type": "string", "default": "motion"},
        "run_id": {"type": "integer", "nullable": True, "default": None},
        "feature_vector": {"type": "object", "required": True},
    }

    def test_defaults_and_overlay(self):
        merged = merge_params(self.SCHEMA,
                              {"feature_vector": {"P5": 2}, "run_id": 7})
        assert merged == {"category": "motion", "run_id": 7,
                          "feature_vector": {"P5": 2}}

    def test_unknown_ctx_keys_ignored(self):
        merged = merge_params(self.SCHEMA,
                              {"feature_vector": {}, "user": "someone"})
        assert "user" not in merged

    def test_required_missing_raises(self):
        with pytest.raises(RegistryError, match="必填"):
            merge_params(self.SCHEMA, {"category": "motion"})

    def test_empty_ctx_uses_defaults_only(self):
        with pytest.raises(RegistryError):
            merge_params(self.SCHEMA, None)     # 必填项仍缺


# ============================================
# 6. 内置试点三工具（薄包装契约与 run 委托）
# ============================================

EXPECTED_BUILTIN_FIELDS = {
    "typicality": {
        "name": "medoid 典型性排序", "stage": "clustering",
        "ui_surface": "page:cluster", "permission": "viewer",
        "ai_hooks": [],
        "deps_head": "cs_cluster_runs",
    },
    "semantic_search": {
        "name": "以句搜义 · 库内最近邻检索", "stage": "semantic_search",
        "ui_surface": "page:semantic", "permission": "viewer",
        "ai_hooks": ["draft", "probe"],
        "deps_head": "cs_senses",
    },
    "template": {
        "name": "释义模板批量生成与导出", "stage": "template",
        "ui_surface": "page:template", "permission": "viewer",
        "ai_hooks": ["draft"],
        "deps_head": "cs_clusters",
    },
}


class TestBuiltinTools:
    @pytest.mark.parametrize("tool_id", sorted(EXPECTED_BUILTIN_FIELDS))
    def test_contract_fields(self, tool_id):
        exp = EXPECTED_BUILTIN_FIELDS[tool_id]
        tool = get_tool(tool_id)
        assert tool is not None                      # 导入 src.tools.builtin 即注册
        assert tool.name == exp["name"]
        assert tool.version == "1.0.0"
        assert tool.stage == exp["stage"]
        assert tool.ui_surface == exp["ui_surface"]
        assert tool.permission == exp["permission"]
        assert tool.ai_hooks == exp["ai_hooks"]
        assert tool.deps and tool.deps[0] == exp["deps_head"]  # 依赖按数据链声明
        assert tool.params_schema                    # 参数 schema 非空

    def test_three_pilots_registered(self):
        assert {t.id for t in list_tools()} == set(EXPECTED_BUILTIN_FIELDS)

    def test_stage_lookup_finds_pilots(self):
        assert "typicality" in {t.id for t in tools_for_stage("clustering")}
        assert "semantic_search" in {t.id for t in tools_for_stage("semantic_search")}
        assert "template" in {t.id for t in tools_for_stage("template")}

    def test_typicality_run_delegates(self, monkeypatch):
        captured = {}
        sentinel = [{"cluster_no": 1, "medoid": {"verb": "march"}}]

        def fake_ranking(**kwargs):
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(cluster_analysis, "compute_medoid_ranking", fake_ranking)
        tool = get_tool("typicality")
        assert tool.run({"language": "zh", "run_id": 7}) is sentinel
        # 未给的参数补 schema 默认值，给出的透传
        assert captured == {"category": "motion", "language": "zh", "run_id": 7,
                            "prototype_share": 1 / 3, "periphery_share": 1 / 3}

    def test_typicality_run_all_defaults(self, monkeypatch):
        captured = {}

        def fake_ranking(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr(cluster_analysis, "compute_medoid_ranking", fake_ranking)
        assert get_tool("typicality").run() == []
        assert captured["category"] == "motion" and captured["language"] == "en"
        assert captured["run_id"] is None

    def test_semantic_search_run_delegates(self, monkeypatch):
        captured = {}
        vector = {"P5": 2, "M2": 1}
        sentinel = [{"sense_id": 11, "distance": 0.25}]

        def fake_search(**kwargs):
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(semantic_search, "search_similar_senses", fake_search)
        tool = get_tool("semantic_search")
        assert tool.run({"feature_vector": vector, "top_k": 3}) is sentinel
        assert captured == {"feature_vector": vector, "category": "motion",
                            "language": "en", "top_k": 3}

    def test_semantic_search_run_requires_vector(self, monkeypatch):
        # 必填参数缺失：merge_params 抛 RegistryError，不触原函数
        def fail_search(**kwargs):  # pragma: no cover - 不应被调用
            raise AssertionError("缺 feature_vector 时不应调用原函数")

        monkeypatch.setattr(semantic_search, "search_similar_senses", fail_search)
        with pytest.raises(RegistryError, match="feature_vector"):
            get_tool("semantic_search").run({"category": "motion"})

    def test_template_run_delegates(self, monkeypatch):
        captured = {}
        sentinel = {"category": "motion", "language": "en",
                    "cluster": {"cluster_no": 2}, "templates": [{"tpl": 1}]}

        def fake_collect(**kwargs):
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(template_engine, "collect_cluster_templates", fake_collect)
        tool = get_tool("template")
        assert tool.run({"cluster_no": 2}) is sentinel
        assert captured == {"category": "motion", "language": "en", "cluster_no": 2}

    def test_render_left_for_batch2(self):
        for tool_id in EXPECTED_BUILTIN_FIELDS:
            with pytest.raises(NotImplementedError, match="批次 2"):
                get_tool(tool_id).render({})

    def test_builtin_default_check_deps_green_without_probes(self):
        # 纯进程内：无探针登记时依赖自检绿（批次 2 登记探针后强校验）
        for tool_id in EXPECTED_BUILTIN_FIELDS:
            assert get_tool(tool_id).check_deps() == []
