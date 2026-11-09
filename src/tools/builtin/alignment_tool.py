"""英汉对齐工具（alignment）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「对齐」（架构 §4；§4 契约示例即 id="alignment"）的
    注册薄包装：把 src/annotation_flow.submit_annotation
    （task_type="alignment" 的英汉对齐三态提交/覆盖数据面，工序 12 标签
    与对译的对齐面）按 ToolSpec 契约接入中央注册表
    src/tools/registry.py。本模块不改原页面/流程模块。

数据链（复用既有数据层，不新建表）：
    annotation_submissions（task_type="alignment"，payload 结构从宽：值
    均标量 + 非空，校验在 annotation_flow.validate_payload）。

接口：
    AlignmentTool（@register 注册）→ run(ctx) 合并默认参数后以
    task_type="alignment" 固定委托 submit_annotation（返回 bool）；
    render(ctx) 留阶段 2（ui_surface 对应 app.py 的 _page == "annotate"）。

降级：
    数据库不可用 → submit_annotation 返回 False（原函数口径）；payload
    非法在 validate_payload 应用层先拒。

阶段口径（R6-2 同款）：run() 是可执行薄包装（对齐提交数据面，平台已有
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
class AlignmentTool(ToolSpec):
    """英汉对齐：run 以 task_type="alignment" 固定委托 submit_annotation。"""

    id: str = "alignment"
    name: str = "英汉对齐标注"
    version: str = "1.0.0"
    stage: str = "alignment"         # 工序 12 标签与对译的对齐面（与架构 §4 示例同 id）
    deps: List[str] = field(default_factory=lambda: [
        "annotation_submissions",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "sense_id": {"type": "integer", "required": True},
        "coder_id": {"type": "integer", "required": True},
        "payload": {"type": "object", "required": True},   # 对齐三态等标量值
        "ai_assisted": {"type": "boolean", "default": True},
    })
    ai_hooks: List[str] = field(default_factory=lambda: [
        "draft",  # 架构 §5 草稿通道：枚举属性预填（对齐三态候选）
    ])
    ui_surface: str = "page:annotate"  # app.py 的 _page == "annotate"
    permission: str = "annotator"      # §8 任务×角色矩阵：标注→annotator+

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> bool:
        """P 层执行：合并默认参数后以 task_type="alignment" 委托提交。"""
        params = merge_params(self.params_schema, ctx)
        return annotation_flow.submit_annotation(
            task_type="alignment", **params)
