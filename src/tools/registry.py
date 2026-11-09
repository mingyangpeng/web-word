"""工具插件中央注册表（T 层）—— ToolSpec 契约的进程内实现。

是什么：
    《平台架构设计规范.md》§4「工具插件体系」的落地：每个编纂工具实现统一
    契约（ToolSpec），用一行装饰器注册进本注册表；页面层（阶段 1 批次 2）
    按 stage / ui_surface 取工具渲染，按 permission / export_permission 做
    动作级权限位（§15 数据出入口纪律：内容性导出默认归词典管理员）。

数据链：
    纯进程内 dict（tool_id → ToolSpec），**不建表、不查库、不触网**；依赖
    探针（register_dep_probe）由批次 2 按需登记，探针自身查什么与注册表无关。
    FX-18 增设 enabled 位的外接缝 set_db_enabled_loader：持久化位读数函数
    由 src/tool_settings_db.bind_registry_loader() 绑入（两步激活落库
    category_tool_settings），注册表自身仍零 DB 依赖——loader 未绑定时
    行为与纯进程内实现逐字节一致（兼容测试打桩）。

接口（阶段 1 施工规范 §3-B）::

    ToolSpec          dataclass：id/name/version/stage/deps/params_schema/
                      ai_hooks/ui_surface/permission/export_permission（§4 契约）
    register(target)  装饰器（ToolSpec 实例或其子类）；重复 id 抛 RegistryError
    get_tool(tool_id)      → ToolSpec | None
    list_tools(enabled_only=False) → list[ToolSpec]   # 两步激活的 enabled 位
    tools_for_stage(stage) → list[ToolSpec]

    另附接线辅助（§4 语义的最小实现，批次 2 直接调用）：set_enabled（词典
    管理员「点亮」）、register_dep_probe / selfcheck（依赖自检）、
    merge_params（params_schema 默认值合并，工具 run 共用）、unregister。

降级：
    注册表自身零外部依赖——import 永不触库；依赖探针未登记时 check_deps
    视为通过（批次 2 登记探针后强校验才生效）；探针抛异常按「依赖缺失」
    处理，不向外传播。

阶段口径（R6-2 明示）：**阶段 1 仅契约与自检** —— ToolSpec 契约、注册/
查询、merge_params 默认值合并与依赖自检（register_dep_probe / selfcheck）
均已可用；工具 ``run()`` 的页面接线（页面层按 stage / ui_surface 调 run）
归**阶段 2**，本模块不接线、不触库。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = [
    "AI_HOOK_CHANNELS",
    "RegistryError",
    "ToolSpec",
    "register",
    "get_tool",
    "list_tools",
    "tools_for_stage",
    "set_enabled",
    "set_db_enabled_loader",
    "reset_registry_state",
    "register_dep_probe",
    "selfcheck",
    "merge_params",
    "unregister",
]

# A 协作智能层三通道（架构 §5）：草稿 draft / 探针 probe / 质检 audit
AI_HOOK_CHANNELS = frozenset({"draft", "probe", "audit"})


class RegistryError(Exception):
    """注册表契约违例（重复 id / 非法字段 / 必填参数缺失）。"""


@dataclass
class ToolSpec:
    """工具插件契约（架构 §4）。

    字段即契约：id/name/version/stage/deps/params_schema/ai_hooks/
    ui_surface/permission/export_permission；行为方法 run/render 由具体
    工具覆写（render 阶段 1 批次 1 留空，批次 2 接线），check_deps 默认
    走依赖探针。
    """

    id: str                      # 稳定 id（settings/运行记录引用）
    name: str                    # 界面名（中文）
    version: str                 # 语义化版本（运行快照记 tool_version）
    stage: str                   # 绑定的编纂工序（架构 §3 十五道工序）
    deps: List[str] = field(default_factory=list)   # selfcheck 依赖声明（表名/配置文件）
    params_schema: Dict[str, Any] = field(default_factory=dict)  # 可界面调的运行参数
    ai_hooks: List[str] = field(default_factory=list)  # 接哪些 A 通道 ⊆ {draft, probe, audit}
    ui_surface: str = ""         # 渲染位置（如 page:cluster；空 = 无界面纯引擎工具）
    permission: str = "viewer"   # 最低使用角色
    export_permission: str = "dict_admin"  # §15 导出纪律：导出权默认归词典管理员

    def check_deps(self) -> List[str]:
        """selfcheck 依赖自检：返回缺失依赖名列表（空 = 绿）。

        默认实现逐项查 register_dep_probe 登记的探针；未登记探针的依赖
        进程内无法校验，视为满足（批次 2 登记探针后强校验生效）；探针
        抛异常按该依赖缺失处理。
        """
        missing: List[str] = []
        for dep in self.deps:
            probe = _DEP_PROBES.get(dep)
            if probe is None:
                continue
            try:
                ok = bool(probe())
            except Exception:  # noqa: BLE001 探针自身故障按缺失处理
                ok = False
            if not ok:
                missing.append(dep)
        return missing

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> Any:
        """P 层执行：具体工具覆写（薄包装委托既有公开函数）。"""
        raise NotImplementedError(f"工具 {self.id} 未实现 run()")

    def render(self, ctx: Optional[Dict[str, Any]] = None) -> None:
        """U 层渲染：批次 1 留空，批次 2 按 ui_surface 接线。"""
        raise NotImplementedError(
            f"工具 {self.id} 的渲染留批次 2 接线（ui_surface={self.ui_surface!r}）")


# ============================================
# 进程内注册表（无 DDL、无连接）
# ============================================

_REGISTRY: Dict[str, ToolSpec] = {}
_ENABLED: set = set()                       # 两步激活的 enabled 位（tool_id 集合，进程内）
_DEP_PROBES: Dict[str, Callable[[], bool]] = {}
# DB 持久化位 loader 缝（FX-18）：None = 未绑定（行为与纯进程内实现一致）。
# 绑定后 _is_enabled 先问 loader——返回 True/False 以 DB 为准，返回 None
# （无持久化行/库不可用）回落 _ENABLED。绑定入口在 src/tool_settings_db.py
# 的 bind_registry_loader（函数指针赋值，import 永不触库，零启动成本）。
_DB_ENABLED_LOADER: Optional[Callable[[str], Optional[bool]]] = None
_LOCK = threading.RLock()


def _validate(spec: ToolSpec) -> None:
    """注册前契约校验；违例抛 RegistryError。"""
    for attr in ("id", "name", "version", "stage", "permission", "export_permission"):
        value = getattr(spec, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise RegistryError(f"ToolSpec.{attr} 必须是非空字符串，得到 {value!r}")
    if not isinstance(spec.ui_surface, str):
        raise RegistryError(f"ToolSpec.ui_surface 必须是字符串，得到 {spec.ui_surface!r}")
    if not isinstance(spec.deps, list) or any(
            not isinstance(d, str) or not d for d in spec.deps):
        raise RegistryError(f"工具 {spec.id} 的 deps 必须是非空字符串列表")
    if not isinstance(spec.params_schema, dict):
        raise RegistryError(f"工具 {spec.id} 的 params_schema 必须是 dict")
    if not isinstance(spec.ai_hooks, list) or any(
            h not in AI_HOOK_CHANNELS for h in spec.ai_hooks):
        raise RegistryError(
            f"工具 {spec.id} 的 ai_hooks 只能取 {sorted(AI_HOOK_CHANNELS)}，"
            f"得到 {spec.ai_hooks!r}")


def register(target: Any) -> Any:
    """注册工具（装饰器用法 ``@register``）；重复 id 抛 RegistryError。

    接受两种形态：ToolSpec 实例原样注册；ToolSpec 子类先无参实例化再注册
    （内置三工具用 dataclass 子类声明默认字段）。返回原参数，装饰后的
    类/实例照常可用。
    """
    if isinstance(target, type) and issubclass(target, ToolSpec):
        spec = target()
    elif isinstance(target, ToolSpec):
        spec = target
    else:
        raise RegistryError(f"register 需要 ToolSpec 实例或其子类，得到 {target!r}")
    _validate(spec)
    with _LOCK:
        existing = _REGISTRY.get(spec.id)
        if existing is not None:
            raise RegistryError(
                f"工具 id 重复注册: {spec.id}"
                f"（已注册 {existing.name} v{existing.version}）")
        _REGISTRY[spec.id] = spec
    return target


def get_tool(tool_id: str) -> Optional[ToolSpec]:
    """按 id 查工具；不存在返回 None。"""
    return _REGISTRY.get(tool_id)


def _is_enabled(tool_id: str) -> bool:
    """enabled 位判定（FX-18 接线口径）：DB 持久化位优先，读不到回落进程内。

    - loader 已绑定且对 tool_id 给出 True/False → 以 DB 持久化位为准
      （两步激活落 category_tool_settings，重启不丢）；
    - loader 未绑定 / 对该 tool_id 无持久化行 / loader 抛异常 → 回落进程内
      _ENABLED（兼容既有测试打桩与热置位）。
    """
    loader = _DB_ENABLED_LOADER
    if loader is not None:
        try:
            persisted = loader(tool_id)
        except Exception:  # noqa: BLE001 loader 故障按「读不到」回落
            persisted = None
        if persisted is not None:
            return bool(persisted)
    return tool_id in _ENABLED


def list_tools(enabled_only: bool = False) -> List[ToolSpec]:
    """列出工具（按 id 排序保证顺序稳定）；enabled_only 只返回已点亮工具
    （判定走 _is_enabled：DB 持久化位优先，读不到回落进程内 _ENABLED）。"""
    with _LOCK:
        specs = [t for t in _REGISTRY.values()
                 if not enabled_only or _is_enabled(t.id)]
    return sorted(specs, key=lambda t: t.id)


def tools_for_stage(stage: str) -> List[ToolSpec]:
    """按绑定工序取工具（按 id 排序；无匹配返回空列表）。"""
    with _LOCK:
        specs = [t for t in _REGISTRY.values() if t.stage == stage]
    return sorted(specs, key=lambda t: t.id)


def set_enabled(tool_id: str, enabled: bool = True) -> bool:
    """两步激活的 enabled 位·进程内面（词典管理员「点亮」，架构 §4）。

    id 不存在返回 False。FX-18 之后这只是**进程内**位：持久化写路径归
    src/tool_settings_db.enabled_set（权限闸门＋两步激活约束＋审计落库），
    写库成功后由其回调本函数刷新进程内位；loader 已绑定时 DB 位优先，
    本位只作「无持久化行」的回落（兼容测试打桩）。
    """
    with _LOCK:
        if tool_id not in _REGISTRY:
            return False
        if enabled:
            _ENABLED.add(tool_id)
        else:
            _ENABLED.discard(tool_id)
    return True


def set_db_enabled_loader(loader: Optional[Callable[[str], Optional[bool]]]) -> None:
    """绑定/解绑 DB 持久化位 loader（FX-18 缝）。

    loader 签名：loader(tool_id) → True/False（DB 位）或 None（读不到，
    回落进程内 _ENABLED）。传 None 解绑。只做函数指针赋值，不触库。
    生产绑定入口：src/tool_settings_db.bind_registry_loader()。
    """
    global _DB_ENABLED_LOADER
    with _LOCK:
        _DB_ENABLED_LOADER = loader


def reset_registry_state() -> None:
    """进程内运行态复位（测试钩子）：清 enabled 位、解绑 DB loader、
    清依赖探针。**不动 _REGISTRY**（内置工具靠 import 时注册，注册表
    重复注册抛 RegistryError，清了就回不来）。测试隔离用，生产勿调。
    """
    global _DB_ENABLED_LOADER
    with _LOCK:
        _ENABLED.clear()
        _DEP_PROBES.clear()
        _DB_ENABLED_LOADER = None


def unregister(tool_id: str) -> bool:
    """注销工具（热卸载/测试隔离用）；id 不存在返回 False。"""
    with _LOCK:
        if _REGISTRY.pop(tool_id, None) is None:
            return False
        _ENABLED.discard(tool_id)
    return True


def register_dep_probe(dep: str, probe: Callable[[], bool]) -> None:
    """登记依赖探针（selfcheck 用）：probe() 为真表示该依赖可用。"""
    if not dep or not isinstance(dep, str):
        raise RegistryError("依赖名必须是非空字符串")
    if not callable(probe):
        raise RegistryError("探针必须可调用")
    with _LOCK:
        _DEP_PROBES[dep] = probe


def selfcheck() -> Dict[str, List[str]]:
    """全量依赖自检：{tool_id: 缺失依赖列表}（架构 §4「selfcheck 绿」的数据源）。"""
    return {t.id: t.check_deps() for t in list_tools()}


def merge_params(params_schema: Dict[str, Any],
                 ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """按 params_schema 合并运行参数：schema 默认值打底，ctx 覆盖同名键。

    - ctx 中不在 schema 里的键忽略（页面上下文可整包透传，不污染 run）；
    - schema 里无 default（必填）而 ctx 未给的键 → RegistryError。
    """
    merged: Dict[str, Any] = {}
    ctx = dict(ctx or {})
    for key, rule in (params_schema or {}).items():
        if key in ctx:
            merged[key] = ctx[key]
        elif isinstance(rule, dict) and "default" in rule:
            merged[key] = rule["default"]
        else:
            raise RegistryError(f"工具参数 {key} 为必填，ctx 未提供")
    return merged
