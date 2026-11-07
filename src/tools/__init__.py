"""LexiSchema 工具插件注册表包（T 层，架构 §4）。

本包是 ToolSpec 插件契约的家：
  * src/tools/registry.py —— 中央注册表（register/get_tool/list_tools/
    tools_for_stage 等公共符号在此导出）；
  * src/tools/builtin/ —— 内置试点三工具（典型性 / 语义检索 / 模板），
    导入 src.tools.builtin 即完成注册。

纯进程内注册表：不建表、不查库、零新依赖。
"""

from src.tools.registry import (
    AI_HOOK_CHANNELS,
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

__all__ = [
    "AI_HOOK_CHANNELS",
    "RegistryError",
    "ToolSpec",
    "register",
    "get_tool",
    "list_tools",
    "merge_params",
    "register_dep_probe",
    "selfcheck",
    "set_enabled",
    "tools_for_stage",
    "unregister",
]
