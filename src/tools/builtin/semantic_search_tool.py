"""以句搜义工具（semantic_search）—— ToolSpec 薄包装（批次 1 试点二）。

是什么：
    内置十类工具之「语义检索」（架构 §4）的注册薄包装：把
    src/semantic_search.search_similar_senses（库内 Gower 最近邻检索，
    论文 §7.1 第二模式的检索端）按 ToolSpec 契约接入中央注册表
    src/tools/registry.py。本模块不改原页面模块。

数据链（复用既有数据层，不新建表）：
    cs_senses / cs_lexemes / cs_sense_features（义位编码矩阵长表）；
    特征元数据（value_type / 值域）来自范畴包 configs/<category>/features.yaml
    （经 src/cluster_analysis.load_feature_types）。
    详见 src/semantic_search.py 模块 docstring。

接口：
    SemanticSearchTool（@register 注册）→ run(ctx) 合并默认参数后委托
    search_similar_senses（结果口径：距离升序最近邻列表，附
    matched_features 证据链）；render(ctx) 留批次 2（ui_surface 对应
    app.py 的 _page == "semantic"）。
    注意：index / value_types / ranges 属页面级缓存与元数据注入参数，
    不进 params_schema（批次 2 接线时如需预装载索引再扩展 schema）。

降级：
    查询向量为空 / 范畴未灌数据 / 库不可用 → search_similar_senses
    返回 []（原函数口径）；查询解析的 LLM 增强失败静默回退规则层
    （原模块两层解析策略，与本包装无关）。

阶段口径（R6-2 明示）：**阶段 1 仅契约与自检** —— 本模块只验证
    ToolSpec 契约可注册、params_schema 可合并默认值、run() 可委托
    （自检可跑通）；页面接线（ui_surface 对应页面调 run）归
    **阶段 2**，本模块不 import streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import semantic_search
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class SemanticSearchTool(ToolSpec):
    """以句搜义：run 委托 search_similar_senses（Gower 最近邻检索）。"""

    id: str = "semantic_search"
    name: str = "以句搜义 · 库内最近邻检索"
    version: str = "1.0.0"
    stage: str = "semantic_search"   # 独立检索能力面（与架构 §4 alignment 示例同型：id==stage）
    deps: List[str] = field(default_factory=lambda: [
        "cs_senses", "cs_sense_features", "configs/motion/features.yaml",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "feature_vector": {"type": "object", "required": True},
        "category": {"type": "string", "default": "motion"},
        "language": {"type": "string", "enum": ["en", "zh"], "default": "en"},
        "top_k": {"type": "integer", "default": semantic_search.DEFAULT_TOP_K},
    })
    ai_hooks: List[str] = field(default_factory=lambda: [
        "draft",  # LLM 把自然语言查询解析成特征向量（失败回退规则层）
        "probe",  # 检索结果附 matched_features/definition 证据链，供库内受控问答
    ])
    ui_surface: str = "page:semantic"  # app.py 的 _page == "semantic"
    permission: str = "viewer"         # 现状：语义检索页需登录、全角色可看

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """P 层执行：合并默认参数后委托 search_similar_senses。

        feature_vector 为必填（parse_query_to_features / parse_query_detail
        的输出），缺失抛 RegistryError。
        """
        params = merge_params(self.params_schema, ctx)
        return semantic_search.search_similar_senses(**params)
