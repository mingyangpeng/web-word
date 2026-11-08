"""释义模板工具（template）—— ToolSpec 薄包装（批次 1 试点三）。

是什么：
    内置十类工具之「模板」（架构 §4）的注册薄包装：把
    src/template_engine.collect_cluster_templates（当前簇全部义位逐条
    实例化的批量接口，第四节「模板批量导出」的数据面）按 ToolSpec 契约
    接入中央注册表 src/tools/registry.py。本模块不改原页面模块。

数据链（复用既有数据层，不新建表）：
    cs_clusters / cs_cluster_members / cs_sense_features / cs_senses
    （OALD10 / 现汉7 释义原文对照）+ configs/motion/features.yaml（特征
    label / value_type）+ configs/motion/schemas.yaml（四图式定义）。
    详见 src/template_engine.py 模块 docstring。

接口：
    TemplateTool（@register 注册）→ run(ctx) 合并默认参数后委托
    collect_cluster_templates（返回 {"category", "language", "cluster":
    母图式草案, "templates": [...]}）；render(ctx) 留批次 2（ui_surface
    对应 app.py 的 _page == "template"）。
    批量导出的 CSV/JSON 组装（build_export_csv / build_export_json）仍由
    原模块承担，导出动作受 export_permission（默认 dict_admin，架构 §15）
    闸门约束——批次 2 接线。

降级：
    簇不存在 → templates 为空列表（原函数口径）；母图式提炼 / 槽位
    实例化失败 → 原模块记日志返回空 / None，不崩。

阶段口径（R6-2 明示）：**阶段 1 仅契约与自检** —— 本模块只验证
    ToolSpec 契约可注册、params_schema 可合并默认值、run() 可委托
    （自检可跑通）；页面接线（ui_surface 对应页面调 run）归
    **阶段 2**，本模块不 import streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import template_engine
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class TemplateTool(ToolSpec):
    """释义模板批量生成：run 委托 collect_cluster_templates（批量数据面）。"""

    id: str = "template"
    name: str = "释义模板批量生成与导出"
    version: str = "1.0.0"
    stage: str = "template"          # 工序 9 图式模板 / 工序 10 释义撰写的数据面
    deps: List[str] = field(default_factory=lambda: [
        "cs_clusters", "cs_cluster_members", "cs_sense_features", "cs_senses",
        "configs/motion/features.yaml", "configs/motion/schemas.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "language": {"type": "string", "enum": ["en", "zh"], "default": "en"},
        "cluster_no": {"type": "integer", "nullable": True, "default": None},
    })
    ai_hooks: List[str] = field(default_factory=lambda: [
        "draft",  # 架构 §5 草稿通道明列「模板批量生成」
    ])
    ui_surface: str = "page:template"  # app.py 的 _page == "template"
    permission: str = "viewer"         # 模板页需登录、全角色可看；导出另受 export_permission 管

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """P 层执行：合并默认参数后委托 collect_cluster_templates。"""
        params = merge_params(self.params_schema, ctx)
        return template_engine.collect_cluster_templates(**params)
