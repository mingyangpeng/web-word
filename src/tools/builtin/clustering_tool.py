"""谱系聚类工具（clustering）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「聚类」（架构 §4）的注册薄包装：把
    src/cluster_analysis.build_dendrogram_data（Gower 相异度 → average
    联接 → linkage 矩阵的可绘数据，工序 7 聚类归类；交互式切割
    recut_clusters 归页面层调用）按 ToolSpec 契约接入中央注册表
    src/tools/registry.py。本模块不改原页面/计算模块。

数据链（复用既有数据层，不新建表）：
    cs_cluster_runs → cs_clusters → cs_cluster_members → cs_senses；
    特征矩阵：cs_sense_features（in_clustering=1 的列进 Gower 距离），
    value_type 来自范畴包 configs/<category>/features.yaml（经
    load_feature_types）。

接口：
    ClusteringTool（@register 注册）→ run(ctx) 合并默认参数后委托
    build_dendrogram_data（返回 {"labels", "linkage", "distance_matrix",
    "cut_height", ...}；范畴/运行不存在 → {}，scipy 缺失抛 ImportError，
    均原函数口径）；render(ctx) 留阶段 2（ui_surface 对应 app.py 的
    _page == "cluster"）。
    注意：value_types / ranges 属页面级缓存与元数据注入参数，不进
    params_schema（与 semantic_search_tool 同一口径）。

降级：
    范畴未灌数据 / 无运行 → 返回 {}（原函数口径）。

阶段口径（R6-2 同款）：run() 是可执行薄包装（谱系计算数据面，平台已有
实现）；页面接线（谁在哪个页面调 run）归**阶段 2**，本模块不 import
streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import cluster_analysis
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class ClusteringTool(ToolSpec):
    """谱系聚类：run 委托 build_dendrogram_data（Gower + average 联接）。"""

    id: str = "clustering"
    name: str = "谱系聚类（Gower 相异度）"
    version: str = "1.0.0"
    stage: str = "clustering"        # 工序 7 聚类归类（典型性排序同工序）
    deps: List[str] = field(default_factory=lambda: [
        "cs_cluster_runs", "cs_cluster_members", "cs_sense_features",
        "configs/motion/features.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "language": {"type": "string", "enum": ["en", "zh"], "default": "en"},
        "run_id": {"type": "integer", "nullable": True, "default": None},
    })
    ai_hooks: List[str] = field(default_factory=list)  # 纯确定性计算，不接 A 通道
    ui_surface: str = "page:cluster"   # app.py 的 _page == "cluster"
    permission: str = "viewer"         # 现状：语义分析页全角色可看

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """P 层执行：合并默认参数后委托 build_dendrogram_data。"""
        params = merge_params(self.params_schema, ctx)
        return cluster_analysis.build_dendrogram_data(**params)
