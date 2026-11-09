"""特征标注工具（feature_coding）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「特征标注」（架构 §4）的注册薄包装：把
    src/annotation_flow.submit_annotation（task_type="feature_coding" 的
    特征编码提交/覆盖数据面，工序 5 特征标注）按 ToolSpec 契约接入中央
    注册表 src/tools/registry.py。本模块不改原页面/流程模块。

数据链（复用既有数据层，不新建表）：
    annotation_submissions（payload["features"] 为特征码→值的 dict，
    UNIQUE(sense_id, task_type, coder_id)）；特征元数据（label/value_type/
    in_clustering）来自范畴包 configs/<category>/features.yaml（校验经
    annotation_flow.validate_payload / 范畴包 selfcheck）。

接口：
    FeatureCodingTool（@register 注册）→ run(ctx) 合并默认参数后以
    task_type="feature_coding" 固定委托 submit_annotation（返回 bool）；
    render(ctx) 留阶段 2（ui_surface 对应 app.py 的 _page == "annotate"）。

降级：
    数据库不可用 → submit_annotation 返回 False（原函数口径）；features
    空 dict / 值非标量在 validate_payload 应用层先拒。

阶段口径（R6-2 同款）：run() 是可执行薄包装（特征编码数据面，平台已有
实现）；页面接线（谁在哪个页面调 run）归**阶段 2**，本模块不 import
streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import annotation_flow
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class FeatureCodingTool(ToolSpec):
    """特征标注：run 以 task_type="feature_coding" 固定委托 submit_annotation。"""

    id: str = "feature_coding"
    name: str = "特征标注编码"
    version: str = "1.0.0"
    stage: str = "feature_coding"    # 工序 5 特征标注
    deps: List[str] = field(default_factory=lambda: [
        "annotation_submissions", "configs/motion/features.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "sense_id": {"type": "integer", "required": True},
        "coder_id": {"type": "integer", "required": True},
        "payload": {"type": "object", "required": True},   # {"features": {特征码: 值}}
        "ai_assisted": {"type": "boolean", "default": True},
    })
    ai_hooks: List[str] = field(default_factory=lambda: [
        "draft",  # 架构 §5 草稿通道明列「特征草稿」
    ])
    ui_surface: str = "page:annotate"  # app.py 的 _page == "annotate"
    permission: str = "annotator"      # §8 任务×角色矩阵：标注→annotator+

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> bool:
        """P 层执行：合并默认参数后以 task_type="feature_coding" 委托提交。"""
        params = merge_params(self.params_schema, ctx)
        return annotation_flow.submit_annotation(
            task_type="feature_coding", **params)
