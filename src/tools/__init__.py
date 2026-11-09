"""LexiSchema 工具插件注册表包（T 层，架构 §4）。

本包是 ToolSpec 插件契约的家：
  * src/tools/registry.py —— 中央注册表（register/get_tool/list_tools/
    tools_for_stage 等公共符号在此导出）；
  * src/tools/builtin/ —— 内置工具（FX-18 十类补全：admission/
    feature_coding/alignment/reliability/clustering/typicality/schema/
    template/semantic_search/corpus_evidence ＋ multimedia，run 均
    薄包装委托既有实现），导入 src.tools.builtin 即完成注册。

纯进程内注册表：不建表、不查库、零新依赖。

阶段口径（R6-2 明示）：**阶段 1 仅契约与自检** —— 本包只提供 ToolSpec
契约、注册表与依赖自检（selfcheck / register_dep_probe）；各工具的
``run()`` 页面接线（按 stage / ui_surface 在页面层调 run）归**阶段 2**，
本包不做任何页面调用接线。
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
