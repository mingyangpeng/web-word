"""多媒体资产工具（multimedia）—— ToolSpec 薄包装（FX-18 十类之外的 ＋1）。

是什么：
    架构 §4「内置十类……（＋multimedia）」括注的第十一个工具面的注册
    薄包装：把 src/media_db.list_assets_for_anchor（媒体资产四锚查询：
    词目/义位/例证/图式，媒体资产域⑦两表 media_assets/media_bindings，
    批次「媒体两表」的数据面）按 ToolSpec 契约接入中央注册表
    src/tools/registry.py。本模块不改原数据层。

数据链（复用既有数据层，不新建表）：
    media_assets（kind/source/license/sha256，sha256 完整性校验）×
    media_bindings（四锚绑定 + 状态机 候选→审定→发布）。

接口：
    MultimediaTool（@register 注册）→ run(ctx) 合并默认参数后委托
    list_assets_for_anchor（返回该锚点已绑定的资产列表；无绑定 → []，
    原函数口径）；render(ctx) 留阶段 2（媒体库是 §9 标注「阶段 2 新页」，
    故 ui_surface 留空 = 无界面纯引擎工具）。
    资产登记/绑定（register_asset / bind_asset）不经本工具 run —— 写
    路径归 media_db 调用方（页面/导入管线），本工具只是锚点查询面。

降级：
    数据库不可用 → list_assets_for_anchor 返回 []（原函数口径）。

阶段口径（R6-2 同款）：run() 是可执行薄包装（锚点资产查询数据面，
平台已有实现）；媒体库页面与 AI 配图/视频推荐通道归**阶段 2**
（§5 草稿通道「配图/视频推荐」），本模块不 import streamlit、不改
页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import media_db
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class MultimediaTool(ToolSpec):
    """多媒体资产：run 委托 list_assets_for_anchor（四锚绑定资产查询）。"""

    id: str = "multimedia"
    name: str = "多媒体资产查询"
    version: str = "1.0.0"
    stage: str = "multimedia"        # 媒体资产域⑦（词条多模态区的数据面）
    deps: List[str] = field(default_factory=lambda: [
        "media_assets", "media_bindings",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "anchor_type": {"type": "string",
                        "enum": list(media_db.MEDIA_ANCHOR_TYPES),
                        "default": media_db.ANCHOR_WORD},
        "anchor_id": {"type": "integer", "required": True},
    })
    ai_hooks: List[str] = field(default_factory=list)  # 推荐通道（配图/视频）归阶段 2，run 本身纯查询
    ui_surface: str = ""               # 媒体库是阶段 2 新页（架构 §9），先作无界面引擎工具
    permission: str = "viewer"

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """P 层执行：合并默认参数后委托 list_assets_for_anchor。"""
        params = merge_params(self.params_schema, ctx)
        return media_db.list_assets_for_anchor(**params)
