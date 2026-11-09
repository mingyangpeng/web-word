"""母图式提炼工具（schema）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「图式」（架构 §4）的注册薄包装：把
    src/template_engine.derive_cluster_schemas（母图式自动提炼·DB 编排：
    范畴 × 语言的每个簇 → 母图式草案列表，§11「引擎计算：母图式 ✅ 已通」，
    工序 9 图式模板的图式面）按 ToolSpec 契约接入中央注册表
    src/tools/registry.py。本模块不改原页面/计算模块。

数据链（复用既有数据层，不新建表）：
    cs_cluster_runs（取该语言最新运行）→ cs_clusters → cs_cluster_members
    → cs_sense_features（成员特征编码与甄别标注）；图式定义与槽位来自
    范畴包 configs/<category>/schemas.yaml（经 resolve_pack）。

接口：
    SchemaTool（@register 注册）→ run(ctx) 合并默认参数后委托
    derive_cluster_schemas（返回按簇组织的母图式草案列表；无数据 / 库
    不可用 / 配置缺失 → []，原函数口径）；render(ctx) 留阶段 2
    （ui_surface 对应 app.py 的 _page == "template"，图式与模板页）。

降级：
    范畴未灌入 / 无运行 → []（原函数口径，记日志页面降级展示）。

阶段口径（R6-2 同款）：run() 是可执行薄包装（母图式提炼数据面，平台
已有实现）；页面接线（谁在哪个页面调 run）归**阶段 2**，本模块不
import streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import template_engine
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class SchemaTool(ToolSpec):
    """母图式提炼：run 委托 derive_cluster_schemas（每簇 → 母图式草案）。"""

    id: str = "schema"
    name: str = "母图式自动提炼"
    version: str = "1.0.0"
    stage: str = "schema"            # 工序 9 图式模板的图式面（模板面归 template 工具）
    deps: List[str] = field(default_factory=lambda: [
        "cs_cluster_runs", "cs_cluster_members", "cs_sense_features",
        "configs/motion/schemas.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "language": {"type": "string", "enum": ["en", "zh"], "default": "en"},
    })
    ai_hooks: List[str] = field(default_factory=lambda: [
        "draft",  # 架构 §5 草稿通道明列「图式草稿」
    ])
    ui_surface: str = "page:template"  # app.py 的 _page == "template"（图式与模板页）
    permission: str = "viewer"         # 现状：模板页需登录、全角色可看

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """P 层执行：合并默认参数后委托 derive_cluster_schemas。"""
        params = merge_params(self.params_schema, ctx)
        return template_engine.derive_cluster_schemas(**params)
