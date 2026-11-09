"""义位准入工具（admission）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「准入」（架构 §4：准入、特征标注、信度、聚类、典型性、
    图式、对齐、模板、语义检索、语料证据）的注册薄包装：把
    src/annotation_flow.submit_annotation（task_type="admission" 的标注
    提交/覆盖数据面，工序 4 义位准入）按 ToolSpec 契约接入中央注册表
    src/tools/registry.py。本模块不改原页面/流程模块。

数据链（复用既有数据层，不新建表）：
    annotation_submissions（UNIQUE(sense_id, task_type, coder_id)，覆盖即
    重新进审核流）→ oald_senses（义位锚）/ users（coder_id）；
    准入三值口径来自范畴包 configs/<category>/admission.yaml（Y/EXT/N，
    payload 校验在 annotation_flow.validate_payload 应用层先拒）。

接口：
    AdmissionTool（@register 注册）→ run(ctx) 合并默认参数后以
    task_type="admission" 固定委托 submit_annotation（返回 bool：
    提交成功 True；payload/参数非法或数据库错误 False）；render(ctx)
    留阶段 2（ui_surface 对应 app.py 的 _page == "annotate"）。

降级：
    数据库不可用 → submit_annotation 返回 False（原函数口径）；payload
    非法在 validate_payload 应用层先拒，不进库。

阶段口径（R6-2 同款）：run() 是可执行薄包装（标注提交数据面，平台已有
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
class AdmissionTool(ToolSpec):
    """义位准入：run 以 task_type="admission" 固定委托 submit_annotation。"""

    id: str = "admission"
    name: str = "义位准入标注"
    version: str = "1.0.0"
    stage: str = "admission"         # 工序 4 义位准入
    deps: List[str] = field(default_factory=lambda: [
        "annotation_submissions", "oald_senses", "configs/motion/admission.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "category": {"type": "string", "default": "motion"},
        "sense_id": {"type": "integer", "required": True},
        "coder_id": {"type": "integer", "required": True},
        "payload": {"type": "object", "required": True},   # admission 三值 + schema/alignment 旁注
        "ai_assisted": {"type": "boolean", "default": True},
    })
    ai_hooks: List[str] = field(default_factory=lambda: [
        "draft",  # 架构 §5 草稿通道明列「准入草稿」（LLM 初筛草稿对照）
    ])
    ui_surface: str = "page:annotate"  # app.py 的 _page == "annotate"
    permission: str = "annotator"      # §8 任务×角色矩阵：标注→annotator+

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> bool:
        """P 层执行：合并默认参数后以 task_type="admission" 委托提交。"""
        params = merge_params(self.params_schema, ctx)
        return annotation_flow.submit_annotation(
            task_type="admission", **params)
