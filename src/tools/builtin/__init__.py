"""内置工具包（阶段 1 批次 1 试点三个）。

导入本包即把试点三工具注册进中央注册表（一行装饰器，架构 §4「新工具
接入五步」的第 2 步）：

  * typicality          medoid 典型性排序（→ src/cluster_analysis）
  * semantic_search     以句搜义 · 库内最近邻（→ src/semantic_search）
  * template            释义模板批量生成（→ src/template_engine）

三工具均为**薄包装**：run() 委托既有公开函数，不改原页面模块；render()
继承基类的 NotImplementedError，留批次 2 按 ui_surface 接线。批次 2 其余
七类工具照此模式补注册：新建 src/tools/builtin/<tool>.py，定义 ToolSpec
子类（dataclass 默认字段 + run 委托），在本包 __init__ 追加一行 import。

阶段口径（R6-2 明示）：**阶段 1 仅契约与自检** —— 三工具的 run() 只做
「可调用、可自检」的可执行封装；页面接线（谁在哪个页面调 run）归
**阶段 2**，本包不 import streamlit、不注册任何页面入口。
"""

from src.tools.builtin import (  # noqa: F401  导入即注册
    semantic_search_tool,
    template_tool,
    typicality,
)

__all__ = ["semantic_search_tool", "template_tool", "typicality"]
