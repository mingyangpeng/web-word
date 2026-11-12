"""图式范畴化工具（schema_family_tool）—— ToolSpec 薄包装（批次 32）。

理论：工作流「图式范畴化」环节（对提取得到的事件图式本身进行归纳，
梳理图式之间的亲缘关系与家族相似性，建立更高层级的事件类型谱系）——
引擎 src/schema_family.py：三级归属向量 → Gower nominal → UPGMA →
图式家族＋medoid 代表图式。

插件化：挂 P 构件（编纂工序链下游），ToolSpec 两步激活照全仓口径；
页面入口在语义分析「🌐 图式谱系」tab（cluster_analysis 接线）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import schema_family
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class SchemaFamilyTool(ToolSpec):
    """图式范畴化：run({"schemas": [...], "max_distance": 0.5}) → 亲缘谱系。"""

    id: str = "schema_family"
    name: str = "图式范畴化（图式家族亲缘谱系）"
    version: str = "1.0.0"
    stage: str = "schema_family"   # 工序 8 下游：图式提取后的二级归纳
    deps: List[str] = field(default_factory=lambda: [
        "cs_clusters", "cs_cluster_members", "cs_sense_features",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "schemas": {"type": "array", "required": True},
        "max_distance": {"type": "number", "default": 0.5},
    })
    ai_hooks: List[str] = field(default_factory=list)  # 确定性计算，不接 A 通道
    ui_surface: str = "page:cluster"   # 语义分析「🌐 图式谱系」tab
    permission: str = "viewer"

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """P 层执行：schemas（derive_cluster_schemas 输出）→ 亲缘谱系。"""
        params = merge_params(self.params_schema, ctx)
        return schema_family.build_schema_families(
            params.get("schemas") or [],
            max_distance=params.get("max_distance") or 0.5,
        )
