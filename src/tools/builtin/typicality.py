"""典型性排序工具（typicality）—— ToolSpec 薄包装（批次 1 试点一）。

是什么：
    内置十类工具之「典型性」（架构 §4）的注册薄包装：把
    src/cluster_analysis.compute_medoid_ranking（F6 medoid 典型性排序，
    论文 §5.2 的程序化原型/次典型/边缘判定）按 ToolSpec 契约接入中央
    注册表 src/tools/registry.py。本模块不改原页面模块。

数据链（复用既有数据层，不新建表）：
    cs_cluster_runs → cs_clusters → cs_cluster_members → cs_senses/cs_lexemes
    特征矩阵：cs_sense_features（in_clustering=1 的列进 Gower 距离）；
    value_type 来自范畴包 configs/<category>/features.yaml。
    详见 src/cluster_analysis.py 模块 docstring。

接口：
    TypicalityTool（@register 注册）→ run(ctx) 合并默认参数后委托
    compute_medoid_ranking（结果口径：按 cluster_no 排序的簇列表，成员按
    到 medoid 的 Gower 距离升序）；render(ctx) 留批次 2（ui_surface 对应
    app.py 的 _page == "cluster"）。

降级：
    范畴未灌数据 / 无运行 → compute_medoid_ranking 返回 []（原函数口径）；
    数据库不可用时是否吞异常以原函数实现为准，本包装不加逻辑。

阶段口径（R6-2 明示）：**阶段 1 仅契约与自检** —— 本模块只验证
    ToolSpec 契约可注册、params_schema 可合并默认值、run() 可委托
    （自检可跑通）；页面接线（ui_surface 对应页面调 run）归
    **阶段 2**，本模块不 import streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import cluster_analysis
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class TypicalityTool(ToolSpec):
    """medoid 典型性排序：绑定聚类归类工序，run 委托 compute_medoid_ranking。"""

    id: str = "typicality"
    name: str = "medoid 典型性排序"
    version: str = "1.0.0"
    stage: str = "clustering"        # 工序 7 聚类归类（典型性排序消费聚类产物）
    deps: List[str] = field(default_factory=lambda: [
        "cs_cluster_runs", "cs_cluster_members", "cs_sense_features",
        "configs/motion/features.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "language": {"type": "string", "enum": ["en", "zh"], "default": "en"},
        "run_id": {"type": "integer", "nullable": True, "default": None},
        "prototype_share": {"type": "number", "default": 1 / 3},
        "periphery_share": {"type": "number", "default": 1 / 3},
    })
    ai_hooks: List[str] = field(default_factory=list)  # 纯确定性计算，不接 A 通道
    ui_surface: str = "page:cluster"   # app.py 的 _page == "cluster"
    permission: str = "viewer"         # 现状：聚类页需登录、全角色可看

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """P 层执行：合并默认参数后委托 compute_medoid_ranking。"""
        params = merge_params(self.params_schema, ctx)
        return cluster_analysis.compute_medoid_ranking(**params)
