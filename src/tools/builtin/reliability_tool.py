"""信度检验工具（reliability）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「信度」（架构 §4）的注册薄包装：把
    src/reliability.run_reliability（Krippendorff's α 计算＋落库
    reliability_runs，工序 6 信度检验，G2 闸门「α≥0.7」的数据源）按
    ToolSpec 契约接入中央注册表 src/tools/registry.py。本模块不改原
    页面/计算模块。

数据链（复用既有数据层，不新建表）：
    annotation_submissions（status='submitted' 全量提交）→ coincidence
    矩阵 → reliability_runs（版本化留痕，created_by 归属列）；特征元数据
    （value_type）来自范畴包 configs/<category>/features.yaml。

接口：
    ReliabilityTool（@register 注册）→ run(ctx) 合并默认参数后委托
    run_reliability（返回 dict：overall_alpha / per_feature / n_coders /
    disagreements 等；数据库不可用时结果带 db_error 且不落库，原函数
    口径）；render(ctx) 留阶段 2（ui_surface 对应 app.py 的
    _page == "reliability"）。

降级：
    范畴无提交 / 全不可算 → overall_alpha 为 None（原函数口径）；
    krippendorff 库缺失走纯 Python 巧合矩阵兜底（原模块双路径）。

阶段口径（R6-2 同款）：run() 是可执行薄包装（信度计算数据面，平台已有
实现）；页面接线（谁在哪个页面调 run）归**阶段 2**，本模块不 import
streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import reliability
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class ReliabilityTool(ToolSpec):
    """信度检验：run 委托 run_reliability（α 计算＋reliability_runs 落库）。"""

    id: str = "reliability"
    name: str = "信度检验（Krippendorff's α）"
    version: str = "1.0.0"
    stage: str = "reliability"       # 工序 6 信度检验（G2 闸门数据源）
    deps: List[str] = field(default_factory=lambda: [
        "annotation_submissions", "reliability_runs",
        "configs/motion/features.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "task_type": {"type": "string",
                      "enum": ["admission", "feature_coding", "alignment"],
                      "default": "feature_coding"},
        "created_by": {"type": "integer", "nullable": True, "default": None},
    })
    ai_hooks: List[str] = field(default_factory=list)  # 纯确定性计算，不接 A 通道
    ui_surface: str = "page:reliability"  # app.py 的 _page == "reliability"
    permission: str = "reviewer"          # 与 _PAGE_ACCESS_SIX["reliability"] 同口径

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """P 层执行：合并默认参数后委托 run_reliability。"""
        params = merge_params(self.params_schema, ctx)
        return reliability.run_reliability(**params)
