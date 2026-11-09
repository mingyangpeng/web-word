"""语料证据工具（corpus_evidence）—— ToolSpec 薄包装（FX-18 十类补全）。

是什么：
    内置十类工具之「语料证据」（架构 §4）的注册薄包装：把
    src/mysql_db.get_corpus_collocations（enTenTen21 Word Sketch 搭配
    明细查询，语料证据域②的数据面；词频概览/图式证据的读取函数同族）
    按 ToolSpec 契约接入中央注册表 src/tools/registry.py。本模块不改
    原数据层。

数据链（复用既有数据层，不新建表）：
    corpus_word_stats（词频概览）/ corpus_collocations（搭配明细，
    semantic_category / keep_flag 人工标注列）/ word_schema_scores /
    corpus_schema_evidence（图式证据搭配）；由
    scripts/load_corpus_dataset.py 灌库。

接口：
    CorpusEvidenceTool（@register 注册）→ run(ctx) 合并默认参数后委托
    get_corpus_collocations（返回搭配行列表；词不在库 → []，原函数
    口径）；render(ctx) 留阶段 2（ui_surface 对应 app.py 的
    _page == "corpus"，语料库页）。

降级：
    数据库不可用 → []（原函数口径）；人工标注回写
    （update_collocation_annotations）不经本工具 run —— 写路径归页面
    模块，export 动作另受 export_permission 闸门约束。

阶段口径（R6-2 同款）：run() 是可执行薄包装（搭配证据查询数据面，
平台已有实现）；页面接线（谁在哪个页面调 run）归**阶段 2**，本模块
不 import streamlit、不改页面模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import mysql_db
from src.tools.registry import ToolSpec, merge_params, register


@register
@dataclass
class CorpusEvidenceTool(ToolSpec):
    """语料证据：run 委托 get_corpus_collocations（enTenTen21 搭配明细）。"""

    id: str = "corpus_evidence"
    name: str = "语料搭配证据查询"
    version: str = "1.0.0"
    stage: str = "corpus_evidence"   # 语料证据域②的查询面（工序 2 语料建设的数据源）
    deps: List[str] = field(default_factory=lambda: [
        "corpus_word_stats", "corpus_collocations",
    ])
    params_schema: Dict[str, Any] = field(default_factory=lambda: {
        "verb": {"type": "string", "required": True},
        "slot": {"type": "string", "nullable": True, "default": None},
        "limit": {"type": "integer", "default": 100},
    })
    ai_hooks: List[str] = field(default_factory=list)  # 纯库内查询，不接 A 通道
    ui_surface: str = "page:corpus"    # app.py 的 _page == "corpus"
    permission: str = "viewer"         # 现状：语料库页未登录可看

    def run(self, ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """P 层执行：合并默认参数后委托 get_corpus_collocations。"""
        params = merge_params(self.params_schema, ctx)
        return mysql_db.get_corpus_collocations(**params)
