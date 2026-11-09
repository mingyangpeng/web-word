"""内置工具包（FX-18 十类补全后共 11 个：十类 ＋ multimedia）。

导入本包即把内置工具注册进中央注册表（一行装饰器，架构 §4「新工具
接入五步」的第 2 步）。内置十类（§4：准入、特征标注、信度、聚类、
典型性、图式、对齐、模板、语义检索、语料证据）＋ §4 括注的
（＋multimedia）：

  * admission         义位准入标注          （→ annotation_flow.submit_annotation, admission）
  * feature_coding    特征标注编码          （→ annotation_flow.submit_annotation, feature_coding）
  * alignment         英汉对齐标注          （→ annotation_flow.submit_annotation, alignment）
  * reliability       信度检验 α            （→ reliability.run_reliability）
  * clustering        谱系聚类              （→ cluster_analysis.build_dendrogram_data）
  * typicality        medoid 典型性排序     （→ cluster_analysis.compute_medoid_ranking）
  * schema            母图式自动提炼        （→ template_engine.derive_cluster_schemas）
  * template          释义模板批量生成      （→ template_engine.collect_cluster_templates）
  * semantic_search   以句搜义 · 最近邻     （→ semantic_search.search_similar_senses）
  * corpus_evidence   语料搭配证据查询      （→ mysql_db.get_corpus_collocations）
  * multimedia        多媒体资产查询（＋1） （→ media_db.list_assets_for_anchor）

全部为**薄包装**：run() 委托既有公开函数（平台已有实现），不改原页面
模块；render() 继承基类的 NotImplementedError，留阶段 2 按 ui_surface
接线。新工具照此模式：新建 src/tools/builtin/<tool>.py，定义 ToolSpec
子类（dataclass 默认字段 + run 委托），在本包 __init__ 追加一行 import。

阶段口径（R6-2 同款）：**阶段 1 仅契约与自检** —— run() 只做「可调用、
可自检」的可执行封装（数据面函数平台已有）；页面接线（谁在哪个页面调
run）归**阶段 2**，本包不 import streamlit、不注册任何页面入口。
"""

from src.tools.builtin import (  # noqa: F401  导入即注册
    admission_tool,
    alignment_tool,
    clustering_tool,
    corpus_evidence_tool,
    feature_coding_tool,
    multimedia_tool,
    reliability_tool,
    schema_tool,
    semantic_search_tool,
    template_tool,
    typicality,
)

__all__ = [
    "admission_tool",
    "alignment_tool",
    "clustering_tool",
    "corpus_evidence_tool",
    "feature_coding_tool",
    "multimedia_tool",
    "reliability_tool",
    "schema_tool",
    "semantic_search_tool",
    "template_tool",
    "typicality",
]
