"""聚类可视化与典型性排序 —— 语义分析的谱系树（F3/F2）与 medoid 典型性排序（F6）。

补齐《白话版对照清单》第二档缺口（docs/spec/白话版对照清单.md §三）：

  * F3 谱系树（dendrogram）  论文 §5.1：聚类产出「谱系树」可交互切割；
    本模块用 scipy average 联接画树，并标注 k=5 探索性切分参考线。
  * F2 交互式谱系切割        论文 §5.1「拖动阈值实时重切子簇」：谱系树 tab
    提供 k 滑块（2–10），scipy fcluster(maxclust) 对已算好的 linkage 重切，
    可「保存为新运行版本」（cs_cluster_runs 追加 version，与预计算版共存
    互不覆盖 —— 交互切割结果为探索性运行）。
  * F6 medoid 典型性排序     论文 §5.2：每簇按「到簇代表点的距离」分
    原型(prototype)/次典型(typical)/边缘(periphery)三级，程序化判定。

数据链（复用 src/category_study.py 的 cs_* 8 表）：

  cs_cluster_runs → cs_clusters → cs_cluster_members → cs_senses/cs_lexemes
  特征矩阵：cs_sense_features（in_clustering=1 的列进 Gower 距离）

特征 value_type 来自范畴包（configs/motion/features.yaml，经
src/category_pack.load_pack），决定 Gower 分支（框架文档 §4「引擎层不变项」）：

  binary / nominal → 不一致记 1；ordinal → |x−y| / 值域跨度（values 键 min-max）。
  Gower 距离 = 各特征相异度的均值（无共同特征的义位对记 0，实际编码矩阵
  15 列齐全，不会触发）。

范畴名解析：本模块的 ``category`` 参数接受范畴包目录名（configs/<category>/，
如 motion —— 与页面选择器一致）或语义分析 categories.code（如 RUN）。
包名 → 研究范畴代号的对应关系由 PACK_TO_STUDY_CODE 声明（d1 试点：
motion 包的研究登记名是 RUN 跑范畴）。

页面接入：render_cluster_analysis_page() 由集成步骤挂进 app.py 的页面分派，
本模块不修改 app.py。

写入说明（批次 3 交互切割）：category_study.replace_category_study 是「全范畴
先删后插」的全量替换，不适合页面层追加单条运行 —— 交互切割的「保存为新运行
版本」在本模块实现参数化 INSERT（cs_cluster_runs → cs_clusters →
cs_cluster_members，单事务），列约束以 category_study.py 的建表 SQL 为准
（UNIQUE uq_cs_cluster_runs (category_id, language, version)）。

批次 5（义项分立复核＋义位级图谱，工序 8 / 闸门 G3 / 论文 §7.2）：

  * 🧬 分立复核 tab   G3 闸门（分立→释义：「该簇分立复核定稿（义项清单锁定）后
    才进入释义撰写」）的人工工作台。三段：簇证据视图（最近运行簇清单：成员/
    medoid/簇内平均 Gower 距离/词频 corpus_word_stats，缺数据灰注）→ 登录者
    发起 merge/split/keep 建议（ai_ledger.record_proposal kind='draft',
    stage='sense_division'，AI/人提议都只入台账不直写 D）→ 词典管理员/审校
    裁决（list_pending 逐条，adopted 才 execute_sense_division 落地 cs_senses）。
    迁移 ensure_sense_split_columns：幂等 ALTER。实测主库 web_word_db 的
    cs_senses.status 为 **varchar(8)** 非 ENUM（准入语义
    '保留/边缘/剔除/目标'，默认'保留'）—— 枚举扩值分支仅对 ENUM 列触发，
    varchar(8) 对 'merged'(6 字符)/'split'(5 字符) 长度充足，列型不动（转 ENUM
    反而与 category_study.py 建表 SQL 制造「新建库 vs 迁移库」漂移）；
    merged_into INT NULL 新增（自引用软键指向合并目标 cs_senses.id，不加外键
    —— replace_category_study 全量替换先删后插，自引用外键会卡删除顺序；
    D 域不删行纪律下软键足够，展示时 join 校验）。迁移记录：2026-11-07 于
    测试库合成表验证幂等（tests/test_cluster_analysis.py
    TestSenseSplitColumnsMigration）后主库执行；迁移前 status=varchar(8)
    NOT NULL DEFAULT '保留'、merged_into 不存在，迁移后仅新增 merged_into，
    既有行 status 值不变（测试断言 GROUP BY 前后一致）。
  * 🕸️ 义位图谱 tab  论文 §7.2「节点=义位、距离=Gower、原型居中」：
    recut_clusters 分组键 + dendro 预计算 Gower 方阵（勿重算）→ 经典 MDS
    （Torgerson 双中心化 + numpy 特征分解，**零新依赖**，不用 sklearn）
    前两主轴坐标散点，medoid 星标大标记呈现「原型居中」，簇内两两距离边表
    可选。与论文口径的如实差异在页面 caption 注明：坐标是前两轴最优投影
    （解释率如实展示），不是精确距离还原，也不是示意造假坐标；「原型居中」
    在投影下以星标呈现，几何居中不保证。

批次 6（G3 闸门位 ＋ merged 消费收口，施工规范 §9）：

  * 🔒 簇锁定（G3 落库位）  cs_clusters 加 locked TINYINT(1) NOT NULL
    DEFAULT 0（ensure_cluster_locked_column，幂等 ALTER，模式同
    ensure_sense_split_columns）。G3 语义：**locked=1 = 该簇义项清单复核
    定稿，才允许流入释义撰写（阶段 2 消费约定）**；locked 簇在证据视图加
    「已锁定」徽章。分立复核 tab 增锁定/解锁控件（词典管理员/审校，
    effective 判定复用 _is_division_adjudicator；写库 set_cluster_locked
    参数化 UPDATE）。
  * merged 消费收口        cs_senses.status='merged'（批次 5 merge 落地）
    的义位在下游如实收口：证据视图现状列标注「已并入 → #N」
    （merged_sense_display）；义位图谱组装跳过 merged 节点
    （build_sense_graph_data 的 merged_ids 参数，n_merged_skipped 计数
    如实注明「N 条已并入不计入」，坐标对保留成员重投影、边距离仍取
    预计算 Gower 真值）；裁决区显示 cs_senses 落地结果计数
    （sense_division_landing_counts）。义项脊柱侧的 merged 占位在
    src/sense_spine.py（①段警示 ＋ ④⑤段「已并入，不参与聚类/模板」）。

批次 8（语义分析页合并，施工规范 §11 ——「一个动作一个门」的收口页）：

  * render_semantic_analysis_page  「🏃‍♀️ 范畴深挖」（原 category 键，
    src/category_study_page 五视图 radio）并入本模块页面（key=cluster，
    label 📊 语义分析）：st.tabs 前四 tab（谱系树（含交互切割）/ 典型性 /
    分立复核 / 义位图谱）委托本模块既有渲染，后五 tab（双语对比 /
    编码热图 / 跨语言对齐 / 图式对齐 / 总览）委托 category_study_page
    既有视图函数 —— 视图函数与取数逻辑（_load_page_data / _load_category）
    原样复用，仅页面组装收拢，不做任何取数改动。谱系侧运行缺失不早退：
    两侧读同一 cs_* 表族，九 tab 各自优雅降级。
  * 兼容入口      render_cluster_analysis_page（本模块）与
    render_category_study_page（category_study_page，函数内延迟导入防环）
    保留为兼容薄包装，行为 = 渲染合并页；旧 "category" 键在 app.main()
    顶部重定向一次（session page 置 "cluster"，防书签断裂）。使用说明由
    app.render_cluster_entry 以 guide 键 "cluster" 渲染（合并页不重复渲染）。
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pymysql
import streamlit as st

from src.ai_ledger import (
    DECISIONS,
    DECISION_ADOPTED,
    DECISION_MODIFIED,
    DECISION_REJECTED,
    KIND_DRAFT,
    decide,
    list_pending,
    record_proposal,
)
from src.category_pack import CategoryPackError, CATEGORIES, VALUE_TYPES, load_pack
from src.category_study import (
    category_study_ready,
    get_categories,
    get_cluster_runs,
    get_clusters_with_members,
)
# 批次 8 合并页：英汉对比五视图 + 语义分析缓存装载器委托 category_study_page
# （视图函数独立可调、取数逻辑原样复用；无循环导入 —— category_study_page
# 不回 importer 本模块，其旧页面入口经函数内延迟导入指回这里）
from src.category_study_page import (
    _load_category,
    render_alignment_view,
    render_cluster_compare_view,
    render_matrix_view,
    render_overview_view,
    render_schema_view,
)
from src.design_system import HEADER_H1, HEADER_H3, get_badge_html
from src.mysql_db import cache_scope_key, get_db_cursor

logger = logging.getLogger(__name__)

# scipy 为 dendrogram 的可选依赖（requirements.txt 已列）。缺失时本模块的
# medoid 排序照常工作，仅谱系树功能降级报错（与 krippendorff 同降级口径）。
# numpy 为顶层依赖（pandas 传递依赖，义位图谱经典 MDS 特征分解也需要）。
try:
    from scipy.cluster.hierarchy import fcluster as _scipy_fcluster
    from scipy.cluster.hierarchy import linkage as _scipy_linkage
    from scipy.spatial.distance import squareform as _scipy_squareform

    HAS_SCIPY = True
except ImportError:  # pragma: no cover - 环境无 scipy 时才触发
    HAS_SCIPY = False

# plotly 为谱系树/义位图谱/单簇条形图的可选渲染依赖（requirements.txt 已列）。
# 缺失时相关 tab 入口 warning＋return（R4-7，与上方 scipy 同款双层降级），
# 不让 ImportError 炸页面；典型性排序数据与英汉对比侧不依赖 plotly。
try:
    import plotly  # noqa: F401  # 探测可用性；具体模块在函数内延迟导入
    HAS_PLOTLY = True
except ImportError:  # pragma: no cover - 环境无 plotly 时才触发
    HAS_PLOTLY = False

# ============================================
# 配置常量
# ============================================

# 范畴包目录名 → 语义分析 categories.code。包是引擎视角的研究对象配置，
# categories.code 是研究登记名 —— d1 试点：motion 包 → RUN 跑范畴。
PACK_TO_STUDY_CODE = {"motion": "RUN"}

# 默认语言清单（页面语言选择器）
LANGUAGES = ("en", "zh")
LANGUAGE_LABELS = {"en": "英语", "zh": "汉语"}

# 典型性三级（tier）标签：内部键英文、展示中文（论文 §5.2 原型/次典型/边缘）
TIER_PROTOTYPE = "prototype"
TIER_TYPICAL = "typical"
TIER_PERIPHERY = "periphery"
TIER_LABELS = {
    TIER_PROTOTYPE: "原型",
    TIER_TYPICAL: "次典型",
    TIER_PERIPHERY: "边缘",
}
# tier 颜色（沿用 src/design_system 的语义色；徽章底色 / plotly 分色共用）。
# RV1-2：徽章底色全取深档（白字对比 ≥4.5:1）—— 旧 #48bb78 2.43:1 /
# #4299e1 3.05:1 / #a0aec0 2.26:1 全不达 AA（periphery 灰不取 TEXT_DISABLED，
# 用 TEXT_SECONDARY 同值 #4a5568）。
TIER_COLORS = {
    TIER_PROTOTYPE: "#2f855a",   # SUCCESS_COLOR
    TIER_TYPICAL: "#2b6cb0",     # INFO_COLOR
    TIER_PERIPHERY: "#4a5568",   # TEXT_SECONDARY
}
MEDOID_COLOR = "#c05621"         # WARNING_COLOR：medoid 徽章金色系（白字 4.57:1）

# 交互式谱系切割（F2，论文 §5.1）：滑块簇数范围 2–10；当前运行无有效 k 时
# 默认 5（与 d1 试点的探索性解一致）。
RECUT_K_MAX = 10
RECUT_K_DEFAULT = 5
# 交互切割保存的运行版本前缀（cs_cluster_runs.version = 「交互-时间戳」）
INTERACTIVE_VERSION_PREFIX = "交互"

# ============================================
# 批次 5 配置常量（义项分立复核 / 义位图谱）
# ============================================

# 分立建议台账工序名（ai_proposals.stage；施工规范 §8 批次 5 契约）
SENSE_DIVISION_STAGE = "sense_division"
# 分立建议动作白名单（proposal.action / execute 分支）
SENSE_DIVISION_ACTIONS = ("merge", "split", "keep")
SENSE_DIVISION_ACTION_LABELS = {"merge": "合并", "split": "拆分", "keep": "维持"}
# 分立落地新增的 cs_senses.status 取值（见 ensure_sense_split_columns docstring）
SPLIT_STATUS_VALUES = ("merged", "split")
# merged 取值（merge 落地的 status；下游消费收口据此标注/跳过，批次 6）
MERGED_STATUS = SPLIT_STATUS_VALUES[0]
# merged_into 列注释（自引用软键，无外键 —— 见迁移函数 docstring）
MERGED_INTO_COMMENT = (
    "合并去向：并入的目标义位 cs_senses.id（自引用软键，无外键 —— "
    "replace_category_study 全量替换先删后插，自引用外键会卡删除顺序）"
)
# 裁决区单次取数上限（ai_ledger.list_pending 自带 MAX_LIST_LIMIT=500 硬顶）
DIV_PENDING_LIMIT = 50
# 义位图谱边表上限（簇内两两 Gower 距离按降序截断前 N 条）
GRAPH_EDGES_MAX = 100

# ============================================
# 批次 6 配置常量（G3 簇锁定 / merged 消费）
# ============================================

# cs_clusters.locked 列注释（G3 复核定稿；ensure_cluster_locked_column 幂等新增）
CLUSTER_LOCKED_COMMENT = (
    "G3 分立复核闸门：1=该簇义项清单复核定稿（locked 簇才允许流入释义撰写，"
    "阶段 2 消费），0=未定稿（批次 6 幂等新增）"
)
# 「已锁定」徽章底色（DANGER 色系，与谱系树切分参考线同源；区别 medoid 金色；
# RV1-2：#e53e3e 白字 4.13:1 不达 AA，取深档 #c53030 白字 5.47:1）
LOCKED_COLOR = "#c53030"


# ============================================
# 范畴解析与特征元数据
# ============================================

def _pack_name_for(category: str) -> str:
    """范畴参数 → 范畴包目录名（供 load_pack 取 value_type）。

    motion（包名）→ motion；RUN（研究代号）→ 反查 PACK_TO_STUDY_CODE；
    其他值原样返回（调用方对 load_pack 失败已有降级）。
    """
    cat = str(category or "").strip()
    if cat.lower() in PACK_TO_STUDY_CODE:
        return cat.lower()
    for pack, code in PACK_TO_STUDY_CODE.items():
        if code.upper() == cat.upper():
            return pack
    return cat


def _resolve_study_code(category: str) -> Optional[str]:
    """范畴参数 → 语义分析 categories.code（无已灌数据的范畴返回 None）。

    先按 categories.code 直接匹配（大小写不敏感，兼容 RUN 与 run），
    再按 PACK_TO_STUDY_CODE 把包名（motion）映射到研究代号（RUN）。
    """
    cat = str(category or "").strip()
    if not cat:
        return None
    codes = {str(r["code"]).upper(): str(r["code"]) for r in get_categories()}
    if cat.upper() in codes:
        return codes[cat.upper()]
    mapped = PACK_TO_STUDY_CODE.get(cat.lower())
    if mapped and mapped.upper() in codes:
        return codes[mapped.upper()]
    return None


def load_feature_types(category: str) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
    """从范畴包 features.yaml 读聚类特征的 value_type 与 ordinal 值域。

    Returns:
        (value_types, ranges)：
        value_types  {特征码: "binary"|"nominal"|"ordinal"}（仅 in_clustering=true）；
        ranges       {ordinal 特征码: (min, max)}，来自 values 键（如 P5 → (0, 2)）。
        包缺失/自检未过 → 空 dict（调用方把未知特征当 nominal 处理并告警）。
    """
    pack_name = _pack_name_for(category)
    try:
        pack = load_pack(pack_name)
    except CategoryPackError as exc:
        logger.warning(f"load_feature_types: 范畴包 {pack_name} 加载失败，"
                       f"未知特征将按 nominal 处理: {exc}")
        return {}, {}
    value_types: Dict[str, str] = {}
    ranges: Dict[str, Tuple[float, float]] = {}
    for feat in pack["features"].get("features") or []:
        if not feat.get("in_clustering"):
            continue  # A1-A3 核验区不进聚类矩阵（与 cs_sense_features.in_clustering 同口径）
        code = str(feat.get("code") or "").strip()
        if not code:
            continue
        vt = feat.get("value_type")
        value_types[code] = vt if vt in VALUE_TYPES else "nominal"
        if value_types[code] == "ordinal":
            keys: List[float] = []
            for k in (feat.get("values") or {}).keys():
                try:
                    keys.append(float(k))
                except (TypeError, ValueError):
                    continue
            if len(keys) >= 2:
                ranges[code] = (min(keys), max(keys))
    return value_types, ranges


# ============================================
# Gower 相异度（value_type 分支：binary/nominal 记不一致，ordinal 归一差值）
# ============================================

def gower_distance(vec_a: Dict[str, int], vec_b: Dict[str, int],
                   value_types: Dict[str, str],
                   ranges: Optional[Dict[str, Tuple[float, float]]] = None) -> float:
    """两条特征向量的 Gower 相异度（各特征分支均值，∈ [0, 1]）。

    Args:
        vec_a/vec_b: 特征向量 {特征码: 编码值}；缺失特征跳过不计入均值。
        value_types: {特征码: value_type}；binary/nominal 不一致记 1，
            ordinal 记 |a−b|/(max−min)（ranges 提供值域，缺省按 (0, 2)）。
        ranges: ordinal 特征的值域表（load_feature_types 返回的 ranges）。

    Returns:
        相异度均值；无共同特征时记 0.0（实际编码矩阵 15 列齐全，不触发）。
    """
    common = [code for code in value_types if code in vec_a and code in vec_b]
    if not common:
        return 0.0
    total = 0.0
    for code in common:
        a, b = vec_a[code], vec_b[code]
        if value_types.get(code) == "ordinal":
            lo, hi = (ranges or {}).get(code, (0.0, 2.0))
            span = hi - lo
            total += abs(a - b) / span if span else 0.0
        else:  # binary / nominal → 不一致记 1（features.yaml 头注口径）
            total += 0.0 if a == b else 1.0
    return total / len(common)


def gower_matrix(vectors: Sequence[Dict[str, int]],
                 value_types: Dict[str, str],
                 ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                 ) -> List[List[float]]:
    """Gower 相异度矩阵（对称、对角 0）。第 i 行对应 vectors[i]。"""
    n = len(vectors)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = gower_distance(vectors[i], vectors[j], value_types, ranges)
            matrix[i][j] = matrix[j][i] = d
    return matrix


def medoid_index(dist_matrix: Sequence[Sequence[float]]) -> int:
    """簇 medoid 的下标：到其他成员平均距离最小者（平局取下标最小者）。

    平均距离分母为 n-1（其余成员数）；单成员簇平均距离记 0（自身即 medoid）。
    """
    n = len(dist_matrix)
    if n == 0:
        raise ValueError("dist_matrix 为空，无法选 medoid")
    averages = [
        sum(dist_matrix[i]) / (n - 1) if n > 1 else 0.0
        for i in range(n)
    ]
    return min(range(n), key=lambda i: (averages[i], i))


def assign_tiers(distances: Sequence[float],
                 prototype_share: float = 1 / 3,
                 periphery_share: float = 1 / 3) -> List[str]:
    """按到 medoid 距离的排名划三级典型性（返回与 distances 同序的 tier 列表）。

    默认三分位：最近 1/3 = prototype（原型）、中 1/3 = typical（次典型）、
    最远 1/3 = periphery（边缘）。份额可配置（prototype_share /
    periphery_share，typical 自动取中间余量）；向上取整保证小簇也有原型，
    份额之和超 1 时边缘层被压缩（prototype 优先）。

    平局按输入下标序稳定切分（medoid 距离 0 恒居首 → 恒为 prototype）。
    """
    n = len(distances)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: (distances[i], i))
    n_proto = max(0, min(math.ceil(n * prototype_share), n))
    n_periph = max(0, min(math.ceil(n * periphery_share), n - n_proto))
    tiers: List[Optional[str]] = [None] * n
    for rank, idx in enumerate(order):
        if rank < n_proto:
            tiers[idx] = TIER_PROTOTYPE
        elif rank >= n - n_periph:
            tiers[idx] = TIER_PERIPHERY
        else:
            tiers[idx] = TIER_TYPICAL
    return [t or TIER_TYPICAL for t in tiers]


# ============================================
# 数据装载（cs_* 表 → 特征矩阵 + 簇结构）
# ============================================

def _categories_table_reachable() -> bool:
    """categories 表可达性探针（R4-5/R4-1）。

    底层 category_study.get_categories / category_study_ready 对异常静默
    折叠成 []/False（我方不可改其契约），「JOIN 失败」与「真空表」在页面侧
    无法区分 —— 这里直接发一条最小查询：成功即认为数据层可达（未灌入），
    异常即服务端异常（数据不可用，勿重跑灌库）。仅空态分支调用，正常路径
    零开销。
    """
    try:
        with get_db_cursor() as cursor:
            # 探针带 cs_lexemes JOIN：get_categories 的计数子查询依赖同表族，
            # 缺表/连接中断在这里同样会炸，归因更贴近真实失败面。
            cursor.execute(
                "SELECT COUNT(*) AS n FROM categories c "
                "LEFT JOIN cs_lexemes l ON l.category_id = c.id"
            )
            cursor.fetchone()
        return True
    except Exception as e:
        logger.warning(f"categories 表可达性探针失败（按服务暂不可用处理）: {e}")
        return False


def _cluster_family_reachable_error() -> Optional[str]:
    """簇谱系表族可达性深探针（R4-1 尾部：缺表 vs 真数据不足二分）。

    底层 category_study.get_clusters_with_members / get_cluster_runs 对异常
    静默折叠成 []（我方不可改其契约），故 cs_cluster_runs 主探针可达但
    cs_clusters / cs_cluster_members / cs_senses / cs_lexemes /
    cs_sense_features 任一缺表或连接中断时，_load_cluster_matrix 会把失败
    折叠成 None → ranking=[]，被误报成「未灌入」（误导用户重跑灌库脚本）。
    这里用一条覆盖 _load_cluster_matrix 全部读面的 LEFT JOIN 探针归因：
    成功返回 None（真未灌入）；异常返回失败原因（服务端异常，勿重跑灌库）。
    仅在主探针可达而 ranking 为空的分支调用（正常路径零开销）。
    """
    try:
        with get_db_cursor() as cursor:
            # 覆盖 _load_cluster_matrix 读面：runs→clusters→members→senses/
            # lexemes（get_clusters_with_members 的 JOIN 链）＋ sense_features
            # (in_clustering 特征查询)。全部 LEFT JOIN，只验证表可达性。
            cursor.execute(
                "SELECT COUNT(*) AS n FROM cs_cluster_runs r "
                "LEFT JOIN cs_clusters c ON c.run_id = r.id "
                "LEFT JOIN cs_cluster_members m ON m.cluster_id = c.id "
                "LEFT JOIN cs_senses s ON s.id = m.sense_id "
                "LEFT JOIN cs_lexemes l ON l.id = s.lexeme_id "
                "LEFT JOIN cs_sense_features f ON f.sense_id = s.id"
            )
            cursor.fetchone()
        return None
    except Exception as e:
        logger.warning(f"簇谱系表族深探针失败（按数据不可用归因）: {e}")
        return f"语义分析数据读取失败：{e}"


def _resolve_run(category_id: int, language: str,
                 run_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """选定聚类运行：显式 run_id（须属于该范畴+语言），否则取最新（id 最大）。"""
    runs = [r for r in get_cluster_runs(category_id, language)]
    if run_id is not None:
        for run in runs:
            if int(run["run_id"]) == int(run_id):
                return run
        logger.warning(f"run_id={run_id} 不属于 category_id={category_id} "
                       f"language={language}，回退到最新运行")
    return max(runs, key=lambda r: int(r["run_id"])) if runs else None


def _load_cluster_matrix(category: str, language: str,
                         run_id: Optional[int] = None,
                         ) -> Optional[Dict[str, Any]]:
    """装载一个聚类运行的全部分析输入（compute_medoid_ranking /
    build_dendrogram_data 共用，保证谱系树与典型性排序出自同一特征矩阵）。

    Returns:
        {"study_code", "run", "clusters", "value_types", "ranges"}；
        clusters 每项 {"cluster_id", "cluster_no", "name", "size", "members"}，
        members 每项 {"sense_id", "verb", "sense_no", "sense_label",
        "features"}（features 仅含 cs_sense_features.in_clustering=1 的列）。
        范畴未灌数据 / 语言无运行 / 运行无簇 → None。
    """
    study_code = _resolve_study_code(category)
    if study_code is None:
        return None
    categories = [c for c in get_categories() if str(c["code"]) == study_code]
    if not categories:
        return None
    run = _resolve_run(int(categories[0]["id"]), language, run_id)
    if run is None:
        return None
    clusters = get_clusters_with_members(int(run["run_id"]))
    if not clusters:
        return None

    # in_clustering=1 的特征列（cs_sense_features 口径；A1-A3 核验区被排除）
    sense_ids = [int(m["sense_id"]) for cl in clusters for m in cl["members"]]
    features: Dict[int, Dict[str, int]] = {}
    if sense_ids:
        placeholders = ",".join(["%s"] * len(sense_ids))
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    f"""SELECT sense_id, feature_code, value
                        FROM cs_sense_features
                        WHERE sense_id IN ({placeholders})
                          AND in_clustering = 1""",
                    sense_ids,
                )
                for row in cursor.fetchall():
                    features.setdefault(int(row["sense_id"]), {})[
                        str(row["feature_code"])] = int(row["value"])
        except Exception as e:
            logger.error(f"_load_cluster_matrix 特征查询失败: {e}")
            return None

    value_types, ranges = load_feature_types(category)
    out_clusters: List[Dict[str, Any]] = []
    for cl in clusters:
        members = []
        for m in cl["members"]:
            members.append({
                "sense_id": int(m["sense_id"]),
                "verb": str(m["lemma"]),
                "sense_no": m["sense_no"],
                "sense_label": str(m["sense_label"]),
                "features": features.get(int(m["sense_id"]), {}),
            })
        out_clusters.append({
            "cluster_id": int(cl["cluster_id"]),
            "cluster_no": int(cl["cluster_no"]),
            "name": str(cl["name"]),
            "size": len(members),
            "members": members,
        })
    return {
        "study_code": study_code,
        "run": run,
        "clusters": out_clusters,
        "value_types": value_types,
        "ranges": ranges,
    }


def _effective_types(matrix: Dict[str, Any],
                     value_types: Optional[Dict[str, str]],
                     ranges: Optional[Dict[str, Tuple[float, float]]],
                     ) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
    """合并显式指定的 value_types/ranges（测试/换包场景）与包元数据。"""
    vt = dict(matrix["value_types"] or {})
    rg = dict(matrix["ranges"] or {})
    if value_types:
        vt.update(value_types)
    if ranges:
        rg.update(ranges)
    return vt, rg


def _nominal_fallback(vectors: Sequence[Dict[str, int]],
                      value_types: Dict[str, str],
                      ranges: Dict[str, Tuple[float, float]],
                      ) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
    """特征元数据为空时的 nominal 兜底（S2 review 修复，与 semantic_search 同口径）。

    load_feature_types 对包缺失/自检未过返回空 dict，契约是「调用方把未知
    特征按 nominal 处理并告警」。若把空 value_types 直接传进 gower_distance，
    所有特征都不在 value_types 里 → 每一对都被判「无共同特征」记 0，medoid
    排序与谱系树会静默产出全零距离的退化结果（tier 按行序乱贴）。故在
    元数据为空而向量确有编码时，把出现过的特征码按 nominal 兜底并告警，
    与 semantic_search.search_similar_senses 对同一条件的降级语义保持一致。
    """
    if value_types or not vectors:
        return value_types, ranges
    codes = sorted({code for vec in vectors for code in vec})
    if not codes:
        return value_types, ranges
    logger.warning("特征元数据为空（范畴包缺失/自检未过），%d 个特征码按 nominal 兜底: %s",
                   len(codes), ", ".join(codes))
    return {code: "nominal" for code in codes}, {}


def _sense_label(verb: str, sense_no: Any) -> str:
    """谱系树/条形图成员标签：verb-Sn（en: run-S2；zh: 跑-S②）。"""
    sn = "?" if sense_no is None or str(sense_no) == "" else str(sense_no)
    return f"{verb}-S{sn}"


# ============================================
# F6 medoid 典型性排序
# ============================================

def compute_medoid_ranking(category: str = "motion",
                           language: str = "en",
                           run_id: Optional[int] = None,
                           value_types: Optional[Dict[str, str]] = None,
                           ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                           prototype_share: float = 1 / 3,
                           periphery_share: float = 1 / 3,
                           ) -> List[Dict[str, Any]]:
    """每簇的 medoid 典型性排序（论文 §5.2 的程序化原型/次典型/边缘判定）。

    对选定运行的每个簇：取成员 in_clustering 特征向量 → Gower 相异度矩阵 →
    medoid = 簇内到其他成员平均距离最小的成员 → 各成员按到 medoid 的距离
    排名划 tier（默认最近 1/3 原型 / 中 1/3 次典型 / 最远 1/3 边缘）。

    Args:
        category: 范畴包名（motion）或研究代号（RUN），见模块 docstring。
        language: "en" / "zh"。
        run_id: 指定聚类运行；None 取该语言最新运行。
        value_types/ranges: 显式特征元数据（缺省从范畴包 features.yaml 读）。
        prototype_share/periphery_share: 三分位份额（默认 1/3、1/3）。

    Returns:
        按 cluster_no 排序的簇列表，每项::

            {"cluster_id", "cluster_no", "cluster_name", "size",
             "medoid": {sense_id, verb, sense_no, sense_label, gower_to_medoid, tier},
             "members": [{sense_id, verb, sense_no, sense_label,
                          gower_to_medoid, tier, is_medoid}, ...]}

        members 按 gower_to_medoid 升序（平局按 sense_id）；空簇跳过；
        范畴/运行不存在 → []。
    """
    matrix = _load_cluster_matrix(category, language, run_id)
    if matrix is None:
        return []
    vt, rg = _effective_types(matrix, value_types, ranges)
    # 包缺失 → 元数据为空时按 nominal 兜底（否则 gower 全 0，tier 退化，S2 review）
    vt, rg = _nominal_fallback(
        [m["features"] for cl in matrix["clusters"] for m in cl["members"]], vt, rg)

    ranking: List[Dict[str, Any]] = []
    for cl in matrix["clusters"]:
        members = cl["members"]
        if not members:
            continue  # 空簇（理论上有外键就不该出现，防御性跳过）
        vectors = [m["features"] for m in members]
        dist = gower_matrix(vectors, vt, rg)
        med_idx = medoid_index(dist)
        tiers = assign_tiers([dist[med_idx][i] for i in range(len(members))],
                             prototype_share, periphery_share)
        rows = []
        for i, m in enumerate(members):
            rows.append({
                "sense_id": m["sense_id"],
                "verb": m["verb"],
                "sense_no": m["sense_no"],
                "sense_label": m["sense_label"],
                "gower_to_medoid": dist[med_idx][i],
                "tier": tiers[i],
                "is_medoid": i == med_idx,
            })
        rows.sort(key=lambda r: (r["gower_to_medoid"], r["sense_id"]))
        medoid = next(r for r in rows if r["is_medoid"])
        ranking.append({
            "cluster_id": cl["cluster_id"],
            "cluster_no": cl["cluster_no"],
            "cluster_name": cl["name"],
            "size": len(rows),
            "medoid": {k: medoid[k] for k in
                       ("sense_id", "verb", "sense_no", "sense_label",
                        "gower_to_medoid", "tier")},
            "members": rows,
        })
    ranking.sort(key=lambda c: c["cluster_no"])
    return ranking


# ============================================
# F3 谱系树（dendrogram）
# ============================================

def linkage_from_distance_matrix(dist_matrix: Sequence[Sequence[float]],
                                 method: str = "average") -> List[List[float]]:
    """由预计算相异度矩阵做层次聚类（scipy linkage，需先 squareform 压缩）。

    scipy 不原生支持 Gower 度量，故先算好方阵再 squareform 传入；
    method 默认 average（UPGMA，与 d1 聚类运行的 algorithm 口径一致）。
    返回 linkage 矩阵（n-1 行 × 4 列：idx1, idx2, dist, count）。
    """
    if not HAS_SCIPY:
        raise ImportError("scipy 未安装，无法计算谱系树（pip install scipy）")
    if len(dist_matrix) < 2:
        raise ValueError("谱系树至少需要 2 个观测")
    condensed = _scipy_squareform(np.asarray(dist_matrix, dtype=float))
    z = _scipy_linkage(condensed, method=method)
    return [[float(v) for v in row] for row in z]


def cut_height_for(linkage_matrix: Sequence[Sequence[float]], k: int) -> Optional[float]:
    """切成 k 簇的参考高度：首个会跌破 k 簇的合并（第 n-k+1 次）的高度。

    参考线画在「再合并一次就会跌破 k 簇」的那次合并上：平均联接单调，
    高度 < 该值的合并恰有 n-k 次 → k 簇（与 plotly color_threshold 及
    test_cut_height_yields_k_clusters 的严格小于口径一致；S1 review 订正
    原稿「第 (n-k) 次合并的高度」的措辞 —— 代码取行 n-k 即第 n-k+1 次
    合并，行为不变）；k=1 取最后一次合并的高度（其上方即单簇）；
    k 出界返回 None。
    """
    n = len(linkage_matrix) + 1
    if not (1 <= k < n):
        return None
    row = n - k if k >= 2 else n - 2
    return float(linkage_matrix[row][2])


def build_dendrogram_data(category: str = "motion",
                          language: str = "en",
                          run_id: Optional[int] = None,
                          value_types: Optional[Dict[str, str]] = None,
                          ranges: Optional[Dict[str, Tuple[float, float]]] = None,
                          ) -> Dict[str, Any]:
    """谱系树可绘数据（F3）：Gower 相异度 → average 联接 → linkage 矩阵。

    成员集与 compute_medoid_ranking 同源（同一运行的全体簇成员，
    按 verb/sense_no/sense_label 排序保证叶序确定），labels = verb-Sn。

    Returns:
        {"labels", "linkage"（n-1×4 列表）, "distance_matrix"（Gower 方阵）,
         "n_senses", "method", "metric",
         "run_id", "language", "study_code", "k"（运行参数的探索性切分）,
         "cut_height"（切成 k 簇的参考高度）, "members",
         "cophenetic"（源运行共表相关系数，批次 3 新增）,
         "version"（源运行版本号，批次 3 新增）}；
        scipy 缺失抛 ImportError；范畴/运行不存在 → {}。
        新增键向后兼容：只加键不动旧键，既有消费方不受影响。
    """
    matrix = _load_cluster_matrix(category, language, run_id)
    if matrix is None:
        return {}
    vt, rg = _effective_types(matrix, value_types, ranges)

    members: List[Dict[str, Any]] = []
    for cl in matrix["clusters"]:
        for m in cl["members"]:
            members.append({**m, "cluster_id": cl["cluster_id"],
                            "cluster_no": cl["cluster_no"]})
    members.sort(key=lambda m: (m["verb"], str(m["sense_no"]), m["sense_label"]))
    if len(members) < 2:
        return {}

    # 包缺失 → 元数据为空时按 nominal 兜底（否则 gower 全 0，树退化，S2 review）
    vt, rg = _nominal_fallback([m["features"] for m in members], vt, rg)
    dist = gower_matrix([m["features"] for m in members], vt, rg)
    z = linkage_from_distance_matrix(dist, method="average")
    run = matrix["run"]
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    k = params.get("k") if isinstance(params, dict) else None
    try:
        k = int(k) if k is not None else None
    except (TypeError, ValueError):
        k = None
    return {
        "labels": [_sense_label(m["verb"], m["sense_no"]) for m in members],
        "linkage": z,
        "distance_matrix": dist,
        "n_senses": len(members),
        "method": "average",
        "metric": "gower",
        "run_id": int(run["run_id"]),
        "language": language,
        "study_code": matrix["study_code"],
        "k": k,
        "cut_height": cut_height_for(z, k) if k else None,
        "members": members,
        "cophenetic": run.get("cophenetic"),
        "version": str(run.get("version") or ""),
    }


def recut_clusters(dendro: Dict[str, Any], k: int) -> Dict[str, Any]:
    """交互式谱系切割（论文 §5.1 承诺；对照清单 F2）：fcluster maxclust 重切。

    对 build_dendrogram_data 返回的**已算好** linkage 矩阵按目标簇数 k 重切
    （scipy.cluster.hierarchy.fcluster(Z, k, criterion='maxclust')），不重算
    Gower 距离与联接 —— 谱系树标签页的滑块每次拖动只做一次轻量切分。

    medoid 口径：与 compute_medoid_ranking 同一判定（medoid_index —— 簇内到
    其他成员平均 Gower 距离最小者，平局取下标最小者），距离直接取预计算
    Gower 方阵的子阵（同一矩阵、无重编码，结果等价于对新分簇重算）；单成员
    簇自身即 medoid。tier 三分位不在交互切割中重贴 —— 那是典型性排序 tab
    （正式运行）的口径，交互切割只标注成员归属与 medoid。

    Args:
        dendro: build_dendrogram_data 的返回结构（须含 linkage/members；
            distance_matrix 缺失时多成员簇的 medoid 记 None，不猜）。
        k: 目标簇数（页面滑块范围 2–RECUT_K_MAX；k 须 ≤ n_senses）。

    Returns:
        {"k", "n_clusters", "assignments"（与 dendro["members"] 同序的簇号，
        1 起）, "clusters": [{"cluster_no", "size", "members", "medoid"}]}；
        members 为 dendro["members"] 条目的浅拷贝 + is_medoid 键 —— **不改
        输入对象**（dendro 来自 st.cache_data，原地污染会串缓存）。簇号按
        成员叶序首现顺序连续编号。k 越界（<2、>min(10, n)）/ scipy 缺失 /
        输入缺 linkage → {}。注意 scipy 语义：同高合并平局处 maxclust 可能
        给出少于 k 的簇数（返回实际簇数，不做人为拆分）。
    """
    if not HAS_SCIPY or not dendro or not dendro.get("linkage"):
        return {}
    n = len(dendro["linkage"]) + 1
    try:
        k = int(k)
    except (TypeError, ValueError):
        return {}
    if not (2 <= k <= min(RECUT_K_MAX, n)):
        return {}
    z = np.asarray(dendro["linkage"], dtype=float)
    raw = [int(a) for a in _scipy_fcluster(z, k, criterion="maxclust")]
    # fcluster 原始标签序不确定 → 按成员叶序首现顺序重编为 1..实际簇数
    renumber: Dict[int, int] = {}
    for a in raw:
        if a not in renumber:
            renumber[a] = len(renumber) + 1
    assignments = [renumber[a] for a in raw]
    dist = dendro.get("distance_matrix")
    members_in = dendro.get("members") or []
    clusters: List[Dict[str, Any]] = []
    for no in range(1, len(renumber) + 1):
        idxs = [i for i, a in enumerate(assignments) if a == no]
        members_out = [{**members_in[i], "is_medoid": False} for i in idxs]
        medoid = None
        if members_out:
            if len(idxs) == 1:
                med_idx = 0  # 单成员簇：自身即 medoid（medoid_index 同口径）
            elif dist is not None:
                sub = [[dist[i][j] for j in idxs] for i in idxs]
                med_idx = medoid_index(sub)
            else:
                med_idx = None  # 无距离矩阵不猜 medoid
            if med_idx is not None:
                members_out[med_idx]["is_medoid"] = True
                medoid = members_out[med_idx]
        clusters.append({"cluster_no": no, "size": len(members_out),
                         "members": members_out, "medoid": medoid})
    return {"k": k, "n_clusters": len(clusters), "assignments": assignments,
            "clusters": clusters}


def next_interactive_version(existing: Sequence[str],
                             now_str: Optional[str] = None,
                             prefix: str = INTERACTIVE_VERSION_PREFIX) -> str:
    """生成下一个「交互-时间戳」运行版本号（cs_cluster_runs.version）。

    口径：缺省 ``交互-YYYYmmdd-HHMMSS``（秒级时间戳后缀）；与该范畴+语言
    已用版本（UNIQUE(category_id, language, version) 的应用层预查去重，
    existing = 既有版本列表）冲突时自动递增序号后缀 —— ``交互-…-2``、
    ``…-3``，重试上限 999；全部占用时抛 ValueError 提示改用自定义版本号。

    Args:
        existing: 该范畴+语言下已存在的 version 列表（调用方先查库）。
        now_str: 时间戳（测试可注入固定值）；缺省取当前时间。
        prefix: 版本前缀（缺省「交互」；交互切割的结果均为探索性运行）。
    """
    ts = now_str or datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{prefix}-{ts}"
    used = {str(v) for v in existing}
    if base not in used:
        return base
    for i in range(2, 1000):
        candidate = f"{base}-{i}"
        if candidate not in used:
            return candidate
    raise ValueError(
        f"版本号 {base} 及序号后缀（-2…-999）均已占用，请改用自定义版本号")


def save_interactive_cluster_run(dendro: Dict[str, Any], recut: Dict[str, Any],
                                 version: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """交互切割结果 → cs_cluster_runs 新运行版本（探索性运行版本化，F2）。

    写入三表（**参数化 SQL**，单事务 get_db_cursor(autocommit=False)，风格与
    category_study.replace_category_study 一致；后者是全范畴先删后插，不适合
    页面层追加单条运行，故在本模块自行实现 INSERT，列约束以 category_study.py
    建表 SQL 为准 —— UNIQUE uq_cs_cluster_runs (category_id, language,
    version)）：

      * cs_cluster_runs：algorithm="Gower+average"、params={"k", "criterion":
        "maxclust", "interactive": True, "source_run_id"}、cophenetic 沿用源
        运行值（交互切割不重算树，同一棵树 → 同一 cophenetic）、version；
      * cs_clusters：cluster_no/name（「交互切割k=k簇n」）/size；
      * cs_cluster_members：重切后的 sense_id 归属。

    版本化口径：version 缺省由 next_interactive_version 自动生成（「交互-
    时间戳」，应用层对既有版本先查去重）；显式 version 或并发竞态命中
    UNIQUE 冲突（MySQL errno 1062）时**不覆盖既有行**（交互版与预计算版
    共存互不覆盖），返回 conflict 结果，由页面提示改版本号。

    Args:
        dendro: build_dendrogram_data 返回结构（须含 study_code/run_id/
            cophenetic；language 也从 dendro 取）。
        recut: recut_clusters 返回结构（clusters 为空 → 拒绝保存）。
        version: 显式版本号；None 自动生成。

    Returns:
        {"ok": True, "run_id", "version", "n_clusters", "n_members"} |
        {"ok": False, "conflict": True, "version", "error"}（UNIQUE 冲突）|
        {"ok": False, "error"}（输入不完整/范畴不存在/写库失败）。
    """
    clusters = (recut or {}).get("clusters") or []
    if not clusters:
        return {"ok": False, "error": "交互切割结果为空，无法保存"}
    study_code = str((dendro or {}).get("study_code") or "")
    source_run_id = (dendro or {}).get("run_id")
    if not study_code or source_run_id is None:
        return {"ok": False, "error": "谱系树数据缺少 run/study_code，无法保存"}
    language = str((dendro or {}).get("language") or "")
    if language not in LANGUAGES:
        return {"ok": False, "error": f"语言 {language or '（空）'} 不合法"}
    categories = [c for c in get_categories() if str(c["code"]) == study_code]
    if not categories:
        return {"ok": False, "error": f"范畴 {study_code} 不存在，无法保存"}
    category_id = int(categories[0]["id"])

    # 版本号：显式 > 自动生成（应用层对既有版本去重，UNIQUE 冲突的常规路径）
    final_version = version
    if not final_version:
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    """SELECT version FROM cs_cluster_runs
                       WHERE category_id = %s AND language = %s""",
                    (category_id, language),
                )
                existing = [r["version"] for r in cursor.fetchall()]
            final_version = next_interactive_version(existing)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"版本号预查失败: {e}"}

    k = recut.get("k")
    params = {
        "k": int(k) if k is not None else None,
        "criterion": "maxclust",
        "interactive": True,
        "source_run_id": int(source_run_id),
    }
    n_members = 0
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                """INSERT INTO cs_cluster_runs
                   (category_id, language, algorithm, params, cophenetic, version)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (category_id, language, "Gower+average",
                 json.dumps(params, ensure_ascii=False),
                 dendro.get("cophenetic"), final_version),
            )
            cursor.execute("SELECT LAST_INSERT_ID() AS id")
            run_id = int(cursor.fetchone()["id"])
            for cl in clusters:
                cursor.execute(
                    """INSERT INTO cs_clusters
                       (run_id, cluster_no, name, size, profile, note)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (run_id, int(cl["cluster_no"]),
                     f"交互切割k={k}簇{cl['cluster_no']}", int(cl["size"]),
                     None,
                     f"交互切割（fcluster maxclust，源运行 run_id="
                     f"{int(source_run_id)}，探索性结果）"),
                )
                cursor.execute("SELECT LAST_INSERT_ID() AS id")
                cluster_id = int(cursor.fetchone()["id"])
                for m in cl["members"]:
                    cursor.execute(
                        """INSERT INTO cs_cluster_members (cluster_id, sense_id)
                           VALUES (%s, %s)""",
                        (cluster_id, int(m["sense_id"])),
                    )
                    n_members += 1
    except pymysql.err.IntegrityError as e:
        # 1062 duplicate：UNIQUE(category_id, language, version) 冲突（并发
        # 竞态路径，应用层预查之后的兜底）。交互版不覆盖既有行（与预计算版
        # 共存互不覆盖），事务由 get_db_cursor 回滚。
        if getattr(e, "args", (None,))[0] == 1062:
            return {"ok": False, "conflict": True, "version": final_version,
                    "error": f"版本号「{final_version}」已存在，请改版本号后重试"}
        return {"ok": False, "error": f"写库失败: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"写库失败: {e}"}
    return {"ok": True, "run_id": run_id, "version": final_version,
            "n_clusters": len(clusters), "n_members": n_members}


# ============================================
# 批次 5 · 义项分立复核（工序 8 / 闸门 G3）：迁移与纯逻辑
# ============================================

def _parse_enum_values(column_type: str) -> Optional[List[str]]:
    """information_schema COLUMN_TYPE（如 ``enum('目标','保留')``）→ 值列表。

    仅处理 MySQL 8 标准 enum 文本（单引号包裹、'' 转义内部引号）；非 enum
    或格式异常返回 None（调用方按非枚举列处理，不强行改动）。
    """
    text = str(column_type or "").strip()
    if not text.lower().startswith("enum(") or not text.endswith(")"):
        return None
    body = text[5:-1]
    values: List[str] = []
    i = 0
    while i < len(body):
        if body[i] != "'":
            return None
        i += 1
        buf: List[str] = []
        closed = False
        while i < len(body):
            ch = body[i]
            if ch == "'":
                if i + 1 < len(body) and body[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                closed = True
                break
            buf.append(ch)
            i += 1
        if not closed:
            return None
        values.append("".join(buf))
        if i < len(body):
            if body[i] != ",":
                return None
            i += 1
    return values


def _quote_sql_literal(value: str) -> str:
    """SQL 字符串字面量（MySQL：反斜杠与单引号转义）。

    仅用于 DDL 拼接中的枚举值/注释/默认值 —— 这些值全部来自 information_schema
    的列定义回读与代码常量，不是用户输入；业务查询（分立落地 UPDATE）一律
    参数化，见 execute_sense_division。
    """
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _strip_quoted_default(raw: Any) -> str:
    """COLUMN_DEFAULT 规整：MariaDB 风格的引号包裹剥一层（MySQL 8 为裸值）。"""
    text = str(raw)
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1]
    return text


def _as_int_id(value: Any) -> Optional[int]:
    """宽松转正整数 id（bool/None/非整数/≤0 → None；防脏参数进 SQL 参数表）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return None
    return iv if iv > 0 else None


def _column_meta(table: str, column: str) -> Optional[Dict[str, Any]]:
    """information_schema 列定义（当前 DATABASE()；列/表不存在 → None）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
                   FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = %s""",
                (table, column),
            )
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"_column_meta({table}.{column}) 查询失败: {e}")
        return None


def _ensure_sense_split_columns_for(table: str) -> Dict[str, Any]:
    """对指定表执行分立复核迁移（幂等；ensure_sense_split_columns 的可测内核）。

    先实测现定义（information_schema）再动手，绝不覆盖既有值：

      1. status 列分支：
         * **ENUM 且不含 merged/split** → MODIFY 追加两值（原值顺序保留在前，
           NULL/DEFAULT/COMMENT 原样保留，COMMENT 追加分立语义说明）；
         * varchar/char 且长度 < 6（装不下 'merged'）→ 同型加宽到 8
           （主库实测 varchar(8)：长度充足，本分支不触发，列型保持不动 ——
           category_study.py 建表 SQL 即 varchar(8)，转 ENUM 反而制造
           「新建库 vs 迁移库」的 schema 漂移；'merged'/'split' 对 varchar
           本就是合法取值）；
         * 其余类型不动。
      2. merged_into 列缺失 → ADD COLUMN merged_into INT NULL AFTER status
         （自引用软键指向合并目标的 cs_senses.id。**不加外键**：
         replace_category_study 是「全范畴先删后插」，自引用外键会让删除顺序
         互相卡死；D 域不删行纪律下软键足够，页面展示时按 id join 校验）。

    Args:
        table: 表名（代码侧常量/测试合成表，非用户输入；反引号包裹）。

    Returns:
        {"ok": True, "table", "status_altered", "merged_into_added",
         "status_column_type"（迁移后实测）, "actions": [描述]} |
        {"ok": False, "error", "actions"}（表不存在/查定义失败/ALTER 失败）。
    """
    actions: List[str] = []
    meta = _column_meta(table, "status")
    if meta is None:
        return {"ok": False, "error": f"表 {table} 不存在或 status 列定义不可读",
                "actions": actions}
    column_type = str(meta.get("COLUMN_TYPE") or "")
    nullable = str(meta.get("IS_NULLABLE") or "NO").upper() == "YES"
    default = meta.get("COLUMN_DEFAULT")
    comment = str(meta.get("COLUMN_COMMENT") or "")

    status_altered = False
    enum_values = _parse_enum_values(column_type)
    if enum_values is not None:
        missing = [v for v in SPLIT_STATUS_VALUES if v not in enum_values]
        if missing:
            new_comment = (comment + "；" if comment else "") + (
                "分立复核（批次5）：merged=并入他义位 / split=拆分出的新义位")
            new_type = ("ENUM("
                        + ", ".join(_quote_sql_literal(v) for v in enum_values + missing)
                        + ")")
            parts = [f"MODIFY COLUMN `status` {new_type}"]
            if not nullable:
                parts.append("NOT NULL")
            if default is not None:
                parts.append(f"DEFAULT {_quote_sql_literal(_strip_quoted_default(default))}")
            parts.append(f"COMMENT {_quote_sql_literal(new_comment)}")
            try:
                with get_db_cursor() as cursor:
                    cursor.execute(f"ALTER TABLE `{table}` " + " ".join(parts))
                status_altered = True
                actions.append(
                    f"status 枚举扩值：追加 {', '.join(missing)}"
                    f"（原 {len(enum_values)} 个值顺序保留，默认值/注释保留）")
            except Exception as e:
                return {"ok": False, "error": f"status 枚举扩值失败: {e}",
                        "actions": actions}
    else:
        match = re.match(r"^(var)?char\((\d+)\)", column_type, re.IGNORECASE)
        if match and int(match.group(2)) < len("merged"):
            word = "VARCHAR" if match.group(1) else "CHAR"
            parts = [f"MODIFY COLUMN `status` {word}(8)"]
            if not nullable:
                parts.append("NOT NULL")
            if default is not None:
                parts.append(f"DEFAULT {_quote_sql_literal(_strip_quoted_default(default))}")
            if comment:
                parts.append(f"COMMENT {_quote_sql_literal(comment)}")
            try:
                with get_db_cursor() as cursor:
                    cursor.execute(f"ALTER TABLE `{table}` " + " ".join(parts))
                status_altered = True
                actions.append(f"status {column_type} → {word}(8)（装不下 "
                               f"'merged'，同型加宽；默认值/注释保留）")
            except Exception as e:
                return {"ok": False, "error": f"status 加宽失败: {e}",
                        "actions": actions}

    merged_into_added = False
    if _column_meta(table, "merged_into") is None:
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    f"""ALTER TABLE `{table}` ADD COLUMN `merged_into` INT NULL
                        COMMENT {_quote_sql_literal(MERGED_INTO_COMMENT)}
                        AFTER `status`""")
            merged_into_added = True
            actions.append("新增列 merged_into INT NULL（自引用软键，无外键）")
        except Exception as e:
            return {"ok": False, "error": f"新增 merged_into 失败: {e}",
                    "actions": actions}

    post = _column_meta(table, "status")
    return {
        "ok": True,
        "table": table,
        "status_altered": status_altered,
        "merged_into_added": merged_into_added,
        "status_column_type": str(post.get("COLUMN_TYPE") or "") if post else column_type,
        "actions": actions,
    }


# 已迁移表标记（进程级）：页面每次渲染都会走 tab 入口，幂等迁移在进程内直通；
# 迁移失败的表不进集合，下次渲染自动重试。测试直接调 _ensure_sense_split_columns_for
# 可绕过本标记（合成表每例新建）。
_ENSURED_SPLIT_TABLES: set = set()


def ensure_sense_split_columns() -> None:
    """幂等执行 cs_senses 分立复核迁移（分立复核 tab 渲染入口调用）。

    迁移内容与分支口径见 _ensure_sense_split_columns_for docstring；本函数
    只针对业务库 cs_senses，失败只记日志不抛异常（页面可继续渲染，
    merged_into 列缺失时分立证据列灰注降级）。进程内成功一次后直通。
    """
    if "cs_senses" in _ENSURED_SPLIT_TABLES:
        return
    result = _ensure_sense_split_columns_for("cs_senses")
    if result.get("ok"):
        _ENSURED_SPLIT_TABLES.add("cs_senses")
        if result.get("actions"):
            logger.info("cs_senses 分立复核迁移完成: %s", "; ".join(result["actions"]))
    else:
        logger.error("cs_senses 分立复核迁移失败: %s", result.get("error"))


# 已迁移表标记（进程级）：语义同 _ENSURED_SPLIT_TABLES（锁定迁移进程内直通）。
_ENSURED_LOCKED_TABLES: set = set()


def _ensure_cluster_locked_column_for(table: str) -> Dict[str, Any]:
    """对指定表执行簇锁定迁移（幂等；ensure_cluster_locked_column 的可测内核）。

    G3 闸门（分立→释义）的落库位：locked=1 = 该簇义项清单**复核定稿**，
    才允许流入释义撰写（阶段 2 消费约定）。先经 information_schema 实测
    （_column_meta，等价 SHOW COLUMNS 探测），locked 列缺失才动手：

      ADD COLUMN locked TINYINT(1) NOT NULL DEFAULT 0

    不改既有列/既有行（DEFAULT 0 = 全部簇初始未定稿，与 G3「未定稿不放行」
    初始态一致）；表存在性以 id 列为准探测（cs_clusters 主键），表不存在
    如实报错（不猜）。

    Args:
        table: 表名（代码侧常量/测试合成表，非用户输入；反引号包裹）。

    Returns:
        {"ok": True, "table", "locked_added", "locked_column_type"（迁移后实测）,
         "actions": [描述]} |
        {"ok": False, "error", "actions"}（表不存在/ALTER 失败）。
    """
    actions: List[str] = []
    if _column_meta(table, "id") is None:
        return {"ok": False, "error": f"表 {table} 不存在或 id 列定义不可读",
                "actions": actions}
    locked_added = False
    if _column_meta(table, "locked") is None:
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    f"""ALTER TABLE `{table}` ADD COLUMN `locked` TINYINT(1)
                        NOT NULL DEFAULT 0
                        COMMENT {_quote_sql_literal(CLUSTER_LOCKED_COMMENT)}""")
            locked_added = True
            actions.append("新增列 locked TINYINT(1) NOT NULL DEFAULT 0"
                           "（G3 分立复核定稿位）")
        except Exception as e:
            return {"ok": False, "error": f"新增 locked 失败: {e}",
                    "actions": actions}
    post = _column_meta(table, "locked")
    return {
        "ok": True,
        "table": table,
        "locked_added": locked_added,
        "locked_column_type": str(post.get("COLUMN_TYPE") or "") if post else "",
        "actions": actions,
    }


def ensure_cluster_locked_column() -> None:
    """幂等执行 cs_clusters 簇锁定迁移（分立复核 tab 渲染入口调用；批次 6）。

    迁移内容与 G3 语义见 _ensure_cluster_locked_column_for docstring；本函数
    只针对业务库 cs_clusters，失败只记日志不抛异常（页面锁定控件降级提示，
    证据视图徽章按「未锁定」口径渲染，不猜）。进程内成功一次后直通。
    """
    if "cs_clusters" in _ENSURED_LOCKED_TABLES:
        return
    result = _ensure_cluster_locked_column_for("cs_clusters")
    if result.get("ok"):
        _ENSURED_LOCKED_TABLES.add("cs_clusters")
        if result.get("actions"):
            logger.info("cs_clusters 簇锁定迁移完成: %s", "; ".join(result["actions"]))
    else:
        logger.error("cs_clusters 簇锁定迁移失败: %s", result.get("error"))


@st.cache_data(ttl=300, show_spinner=False)
def _load_sense_rows(cache_scope: str, sense_ids: Tuple[int, ...]) -> Dict[int, Dict[str, Any]]:
    """cs_senses 现状（id → {status, merged_into}）—— 分立复核证据列（5 分钟缓存）。

    merged_into 列未迁移（ensure 失败）/库不可用 → {}（页面灰注降级，不编数）。
    cache_scope 首参不得下划线前缀（跨库隔离，见 _load_page_data docstring）。
    """
    if not sense_ids:
        return {}
    placeholders = ",".join(["%s"] * len(sense_ids))
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""SELECT id, status, merged_into FROM cs_senses
                    WHERE id IN ({placeholders})""",
                list(sense_ids),
            )
            return {
                int(r["id"]): {
                    "status": str(r["status"]) if r["status"] is not None else None,
                    "merged_into": int(r["merged_into"])
                    if r["merged_into"] is not None else None,
                }
                for r in cursor.fetchall()
            }
    except Exception as e:
        logger.warning(f"_load_sense_rows cs_senses 现状查询降级（列缺失或库不可用）: {e}")
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _load_word_freqs(cache_scope: str, verbs: Tuple[str, ...]) -> Dict[str, int]:
    """corpus_word_stats 词频（verb → MAX(freq)，10 分钟缓存）。

    表缺/库不可用 → {}（页面灰注降级）。cache_scope 首参同上（跨库隔离）。
    """
    if not verbs:
        return {}
    placeholders = ",".join(["%s"] * len(verbs))
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""SELECT verb, MAX(freq) AS freq FROM corpus_word_stats
                    WHERE verb IN ({placeholders}) GROUP BY verb""",
                list(verbs),
            )
            return {str(r["verb"]): int(r["freq"] or 0) for r in cursor.fetchall()}
    except Exception as e:
        logger.warning(f"_load_word_freqs 词频查询降级（corpus_word_stats 缺失或不可用）: {e}")
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _load_cluster_locks(cache_scope: str,
                        cluster_ids: Tuple[int, ...]) -> Dict[int, bool]:
    """cs_clusters.locked 现状（cluster_id → bool）—— 分立复核锁定徽章（5 分钟缓存）。

    locked 列未迁移（ensure_cluster_locked_column 失败）/库不可用 → {}
    （证据视图按未锁定口径渲染，不猜）。cache_scope 首参不得下划线前缀
    （跨库隔离，见 _load_page_data docstring）。
    """
    if not cluster_ids:
        return {}
    placeholders = ",".join(["%s"] * len(cluster_ids))
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT id, locked FROM cs_clusters WHERE id IN ({placeholders})",
                list(cluster_ids),
            )
            return {int(r["id"]): bool(r["locked"]) for r in cursor.fetchall()}
    except Exception as e:
        logger.warning(f"_load_cluster_locks 锁定状态查询降级（locked 列缺失或库不可用）: {e}")
        return {}


def set_cluster_locked(cluster_id: Any, locked: bool) -> Dict[str, Any]:
    """簇锁定/解锁写库（G3 闸门写路径；SQL 参数化，批次 6）。

    语义：locked=1 = 该簇义项清单复核定稿（G3「分立→释义」放行，阶段 2
    才允许流入释义撰写）；locked=0 = 未定稿。权限（仅词典管理员/审校）
    由页面层 _is_division_adjudicator 把门，本函数只负责合法写。

    Returns:
        {"ok": True, "cluster_id", "locked", "updated"} |
        {"ok": False, "error"}（cluster_id 非法/簇不存在/数据库失败）。
        成功后清 _load_cluster_locks 缓存（证据视图徽章即时刷新）。
    """
    cid = _as_int_id(cluster_id)
    if cid is None:
        return {"ok": False, "error": f"非法 cluster_id: {cluster_id!r}（须为正整数）"}
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE cs_clusters SET locked = %s WHERE id = %s",
                (1 if locked else 0, cid),
            )
            updated = int(cursor.rowcount)
    except Exception as e:
        return {"ok": False, "error": f"锁定写库失败: {e}"}
    if not updated:
        return {"ok": False, "error": f"簇 #{cid} 不存在（未更新任何行）"}
    _load_cluster_locks.clear()
    return {"ok": True, "cluster_id": cid, "locked": bool(locked),
            "updated": updated}


def _plain_member_name(m: Optional[Dict[str, Any]]) -> str:
    """成员显示名（纯文本：dataframe/expander 由 Streamlit 自带转义）。"""
    if not isinstance(m, dict):
        return ""
    no = f"·{m['sense_no']}" if m.get("sense_no") else ""
    return f"{m.get('verb')}{no} {m.get('sense_label')}".strip()


def build_sense_division_evidence(dendro: Dict[str, Any],
                                  ranking: Sequence[Dict[str, Any]],
                                  freqs: Optional[Dict[str, int]] = None,
                                  sense_rows: Optional[Dict[int, Dict[str, Any]]] = None,
                                  locks: Optional[Dict[int, Any]] = None,
                                  ) -> List[Dict[str, Any]]:
    """最近运行簇清单 → 分立复核证据行（纯函数，可测）。

    ranking/dendro 必须同源（_load_page_data 同一次装载：同一最新运行）。
    每簇聚合：成员行（sense_id/verb/sense_no/标签/到 medoid 距离/tier/词频/
    cs_senses 现状 status·merged_into/name 显示名）、medoid 显示名、簇内平均
    Gower 距离（**全部无序对**距离均值 —— dendro 预计算方阵子阵，不重算；
    与「到 medoid 平均距离」的 medoid 判据区分开）。方阵缺失或成员不在矩阵
    → 该簇 avg_pairwise=None（不猜）；freqs/sense_rows 缺项对应字段留 None
    （页面灰注降级）。locks（cluster_id → locked）缺项按未锁定（批次 6：
    每簇带 locked 布尔，页面渲染「已锁定」徽章）。

    Returns:
        [{cluster_id, cluster_no, name, size, medoid_name, avg_pairwise,
          locked, members: [...]}]（按 ranking 顺序）。
    """
    if not dendro or not (dendro.get("members") or []):
        return []
    members_all = dendro["members"]
    index_of = {int(m["sense_id"]): i for i, m in enumerate(members_all)}
    dist = dendro.get("distance_matrix")
    freq_map = freqs or {}
    row_map = sense_rows or {}
    lock_map = locks or {}
    clusters_out: List[Dict[str, Any]] = []
    for cluster in ranking or []:
        member_rows: List[Dict[str, Any]] = []
        idxs: List[int] = []
        for m in cluster.get("members") or []:
            sid = _as_int_id(m.get("sense_id"))
            row = {
                "sense_id": sid,
                "verb": str(m.get("verb") or ""),
                "sense_no": m.get("sense_no"),
                "sense_label": str(m.get("sense_label") or ""),
                "gower_to_medoid": m.get("gower_to_medoid"),
                "tier": m.get("tier"),
                "name": _plain_member_name(m),
                "freq": freq_map.get(str(m.get("verb") or "")),
                "status": None,
                "merged_into": None,
            }
            if sid is not None and sid in row_map:
                row["status"] = row_map[sid].get("status")
                row["merged_into"] = row_map[sid].get("merged_into")
            member_rows.append(row)
            if sid is not None and sid in index_of:
                idxs.append(index_of[sid])
        avg_pairwise: Optional[float] = None
        if dist is not None and len(idxs) >= 2:
            total = 0.0
            pairs = 0
            for a in range(len(idxs)):
                for b in range(a + 1, len(idxs)):
                    total += float(dist[idxs[a]][idxs[b]])
                    pairs += 1
            avg_pairwise = total / pairs if pairs else None
        medoid = cluster.get("medoid")
        cid = _as_int_id(cluster.get("cluster_id"))
        clusters_out.append({
            "cluster_id": cid,
            "cluster_no": cluster.get("cluster_no"),
            "name": str(cluster.get("cluster_name") or ""),
            "size": len(member_rows),
            "medoid_name": _plain_member_name(medoid) if medoid else "",
            "avg_pairwise": avg_pairwise,
            "locked": bool(lock_map.get(int(cid))) if cid is not None else False,
            "members": member_rows,
        })
    return clusters_out


def merged_sense_display(status: Any, merged_into: Any) -> Optional[str]:
    """cs_senses 现状 → merged 消费标注文案（纯函数，可测；批次 6 G3 收口）。

    status='merged'（大小写/空白容错）→「已并入 → #N」（N = merged_into，
    证据视图「cs_senses 现状」列对 merged 义位的收口标注）；merged_into
    缺失时「已并入（去向待补录）」—— 不猜去向 id。非 merged → None
    （调用方维持原 status 展示）。
    """
    if str(status or "").strip().lower() != MERGED_STATUS:
        return None
    target = _as_int_id(merged_into)
    if target is not None:
        return f"已并入 → #{target}"
    return "已并入（去向待补录）"


def sense_division_landing_counts(sense_rows: Dict[int, Dict[str, Any]]) -> Dict[str, int]:
    """cs_senses 现状 → 分立复核落地计数（纯函数，可测；批次 6）。

    裁决区如实注明落地规模：{"merged": status='merged' 行数,
    "split": status='split' 行数, "total": 传入行数}——merged 行在模板/图谱
    消费中被跳过（「N 条已并入不计入」）。脏行/缺键按 0 计，不抛。
    """
    merged = split = 0
    for row in (sense_rows or {}).values():
        status = str((row or {}).get("status") or "").strip().lower()
        if status == MERGED_STATUS:
            merged += 1
        elif status == "split":
            split += 1
    return {"merged": merged, "split": split,
            "total": len(sense_rows or {})}


def build_sense_division_proposal(action: str,
                                  cluster_no: Any,
                                  members: Sequence[Dict[str, Any]],
                                  reason: str,
                                  target_sense_id: Any = None,
                                  run_id: Any = None,
                                  version: Any = None,
                                  ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """分立建议 → ai_proposals.proposal 载荷（纯函数校验，非法返回错误文案）。

    载荷结构（JSON 可序列化；decide 留痕与 execute_sense_division 落地共用）::

        {"action": "merge"|"split"|"keep", "cluster_no": int,
         "sense_ids": [int...], "senses": ["verb·no 标签"...]（审计可读）,
         "target_sense_id": int（仅 merge：保留目标，其余 status='merged' 且
         merged_into 指向它）, "reason": str, "run_id": int|None,
         "version": str|None}

    校验（应用层先拒，非法值不进台账 —— 与 ai_ledger 同纪律）：动作白名单；
    理由必填（G3 闸门：分立建议必须写明依据）；sense 清单非空且 id 均为正整数
    （自动去重）；merge 须 ≥2 个 sense 且保留目标在所选清单内。

    Returns:
        (proposal_dict, None) | (None, 错误文案)。
    """
    if action not in SENSE_DIVISION_ACTIONS:
        return None, f"非法动作 {action!r}（须为 merge/split/keep）"
    no = _as_int_id(cluster_no)
    if no is None:
        return None, "目标簇无效（须为正整数簇号）"
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        return None, "理由必填（G3 闸门：分立建议必须写明依据）。"
    sense_ids: List[int] = []
    sense_names: List[str] = []
    seen: set = set()
    for m in members or []:
        if not isinstance(m, dict):
            continue
        sid = _as_int_id(m.get("sense_id"))
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        sense_ids.append(sid)
        sense_names.append(_plain_member_name(m))
    if not sense_ids:
        return None, "sense 清单为空（至少选择一个义位）。"
    target = _as_int_id(target_sense_id)
    if action == "merge":
        if len(sense_ids) < 2:
            return None, "合并建议至少选择 2 个义位（并入同一目标）。"
        if target is None:
            return None, "合并建议必须指定保留目标（merged_into 指向它）。"
        if target not in sense_ids:
            return None, "合并目标必须在所选 sense 清单内。"
    proposal: Dict[str, Any] = {
        "action": action,
        "cluster_no": no,
        "sense_ids": sense_ids,
        "senses": sense_names,
        "reason": cleaned_reason,
        "run_id": _as_int_id(run_id),
        "version": str(version) if version else None,
    }
    if action == "merge":
        proposal["target_sense_id"] = target
    return proposal, None


def _session_user() -> Optional[Dict[str, Any]]:
    """当前会话用户（施工规范 §5：st.session_state.get("user")，纵深防御自检）。"""
    user = st.session_state.get("user")
    return user if isinstance(user, dict) else None


def _is_division_adjudicator(user: Optional[Dict[str, Any]]) -> bool:
    """分立复核裁决门（G3 闸门权限判定；纯函数可测）。

    语义参照 collab_pages._is_admin_like（过渡期判定 role == 'admin' 视为兼有）
    并扩到六角色：effective roles 含 dict_admin 或 reviewer（词典管理员定位
    裁决，审校可复核 —— 施工规范 §8 批次 5 契约）。不 import collab_pages/app
    （页面模块间不横向依赖），本模块自带一份判定。
    未登录/非 dict/其余角色一律 False（fail-closed）。
    """
    if not isinstance(user, dict):
        return False
    if user.get("role") == "admin":
        return True
    roles = user.get("roles")
    if not isinstance(roles, (list, tuple, set)):
        return False
    return bool({"dict_admin", "reviewer"} & {str(r) for r in roles})


def execute_sense_division(proposal: Any) -> Dict[str, Any]:
    """裁决采纳后的分立落地（G3：adopted 才写 cs_senses；SQL 全参数化）。

    动作语义（与建议载荷一一对应）：
      * merge → 除保留目标外的所选义位 status='merged' 且 merged_into=目标 id
        （目标自身状态不动 —— 合并是「其他义位并入它」）；
      * split → 所选义位 status='split'（拆分出的新义位由后续工序建档，本 MVP
        只贴状态标记，不自动插新行 —— 如实不越权造数据）；
      * keep  → 不写库，仅裁决留痕。

    Returns:
        {"ok": True, "action", "updated"（UPDATE 行数，keep=0）, "sense_ids",
         "target_sense_id"（仅 merge）} | {"ok": False, "error"}（载荷非法/
        动作未知/数据库失败）。
    """
    if not isinstance(proposal, dict):
        return {"ok": False, "error": "提议载荷缺失（非 dict）"}
    action = proposal.get("action")
    if action not in SENSE_DIVISION_ACTIONS:
        return {"ok": False, "error": f"非法动作 {action!r}（须为 merge/split/keep）"}
    ids: List[int] = []
    for v in proposal.get("sense_ids") or []:
        iv = _as_int_id(v)
        if iv is not None and iv not in ids:
            ids.append(iv)
    if not ids:
        return {"ok": False, "error": "sense_ids 为空或全部非法"}
    target = _as_int_id(proposal.get("target_sense_id"))
    if action == "merge":
        if target is None or target not in ids or len(ids) < 2:
            return {"ok": False,
                    "error": "merge 载荷非法：须 ≥2 个 sense 且 target_sense_id 在其中"}
        others = [i for i in ids if i != target]
        placeholders = ",".join(["%s"] * len(others))
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    f"""UPDATE cs_senses
                        SET status = 'merged', merged_into = %s
                        WHERE id IN ({placeholders})""",
                    [target] + others,
                )
                updated = int(cursor.rowcount)
        except Exception as e:
            return {"ok": False, "error": f"merge 落地失败: {e}"}
        return {"ok": True, "action": "merge", "updated": updated,
                "sense_ids": others, "target_sense_id": target}
    if action == "split":
        placeholders = ",".join(["%s"] * len(ids))
        try:
            with get_db_cursor() as cursor:
                cursor.execute(
                    f"UPDATE cs_senses SET status = 'split' "
                    f"WHERE id IN ({placeholders})",
                    ids,
                )
                updated = int(cursor.rowcount)
        except Exception as e:
            return {"ok": False, "error": f"split 落地失败: {e}"}
        return {"ok": True, "action": "split", "updated": updated, "sense_ids": ids}
    return {"ok": True, "action": "keep", "updated": 0, "sense_ids": ids}


def adjudicate_sense_division(proposal_id: int,
                              decision: str,
                              reason: Optional[str],
                              decider: int,
                              proposal: Any) -> Dict[str, Any]:
    """分立复核裁决编排（页面层）：先 decide() 留痕，adopted 才执行落地。

    与 ai_ledger.decide 的分工：decide 只写 ai_proposals（不可变留痕，
    重复裁决拒绝）；cs_senses 的状态落地是词典域写路径，由本函数在 adopted
    分支调用 execute_sense_division 完成（AI/提议者永不直写 D，人裁决才落地）。

    * rejected/modified → 仅留痕不落地（modified 表示人改过候选，本页 MVP
      不提供改参编辑 —— 落地语义只认 adopted，页面按钮注明「仅留痕」）；
    * decide 失败（提案不存在/已被他人抢先裁决/裁决人非法）→ 不执行；
    * adopted 但执行失败 → ok=False 且留痕已记录（裁决不可覆盖），页面提示
      按提案 id 人工补救。

    Returns:
        {"ok": True, "decision", "executed", "updated"} |
        {"ok": False, "error", ...}（含 executed=False 的「已裁决未落地」态）。
    """
    if decision not in DECISIONS:
        return {"ok": False, "error": f"非法裁决值 {decision!r}（须 ∈ {DECISIONS}）"}
    pid = _as_int_id(proposal_id)
    if pid is None:
        return {"ok": False, "error": f"非法 proposal_id: {proposal_id!r}"}
    if not decide(pid, decision, reason, decider):
        return {"ok": False, "decision": decision, "executed": False,
                "error": f"提案 #{pid} 裁决未记录（不存在或已被他人裁决）"}
    if decision != DECISION_ADOPTED:
        return {"ok": True, "decision": decision, "executed": False, "updated": 0}
    execution = execute_sense_division(proposal)
    if not execution.get("ok"):
        return {"ok": False, "decision": decision, "executed": False,
                "error": (f"提案 #{pid} 已裁决采纳但落地失败"
                          f"（留痕已记录，按提案 id 人工补救）: {execution.get('error')}")}
    return {"ok": True, "decision": decision, "executed": True,
            "updated": int(execution.get("updated") or 0), "execution": execution}


# ============================================
# 批次 5 · 义位级图谱（论文 §7.2）：经典 MDS 坐标与图谱组装
# ============================================

def classical_mds_coordinates(dist_matrix: Sequence[Sequence[float]],
                              ) -> Tuple[List[List[float]], float]:
    """经典 MDS（Torgerson/Gower 1968）前两主轴坐标 —— 义位图谱的坐标实现。

    **零新依赖**：双中心化 B = -0.5·J·D²·J（J = I − 11′/n）后取最大两个特征值
    的 sqrt 缩放特征向量（numpy 特征分解；不用 sklearn —— 它不在
    requirements.txt，引入即违「零新依赖」纪律）。这是定义良好的最优 2D 投影
    （strain 最小），不是示意造假坐标；但 Gower 相异度对混合变量不保证欧氏
    嵌入 —— 负特征值舍去（标准做法），坐标仍是真实距离的最优线性近似，
    解释率 = (λ1+λ2)/Σλ⁺ 如实随图展示（页面 caption 注明与本实现的差异）。

    Returns:
        (coords n×2, explained∈[0,1])；n=1 / 全零矩阵 / 空输入 → 全 0 坐标、
        0.0；非方阵 → ([], 0.0)。
    """
    matrix = np.asarray(dist_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] == 0:
        return [], 0.0
    n = matrix.shape[0]
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ (matrix ** 2) @ j
    b = (b + b.T) / 2.0  # 特征分解前的数值噪声对称化
    vals, vecs = np.linalg.eigh(b)
    order = np.argsort(vals)[::-1]
    vals = np.clip(vals[order], 0.0, None)  # 非欧氏 Gower 的负特征值舍去
    positive_sum = float(vals.sum())
    top = vals[:2]
    coords = vecs[:, order][:, :2] * np.sqrt(top)
    if coords.shape[1] < 2:
        # n=1 / 正特征值不足 2 个：补零列保证恒为 n×2（第二轴 = 0）
        coords = np.hstack([coords, np.zeros((n, 2 - coords.shape[1]))])
    explained = float(top.sum() / positive_sum) if positive_sum > 0 else 0.0
    return [[float(row[0]), float(row[1])] for row in coords], explained


def build_sense_graph_data(dendro: Dict[str, Any],
                           recut: Dict[str, Any],
                           edge_limit: int = GRAPH_EDGES_MAX,
                           merged_ids: Optional[Sequence[int]] = None,
                           ) -> Dict[str, Any]:
    """义位图谱组装（纯函数）：recut 分组键 + dendro 预计算 Gower 方阵 → 节点/边/坐标。

    数据链（论文 §7.2「节点=义位、距离=Gower、原型居中」的本实现口径）：
      * 节点 = 交互切割（recut_clusters，**复用已算好 linkage，勿重算 Gower**）
        后的义位成员，坐标 = classical_mds_coordinates（前两主轴）；
      * 原型 = 各簇 medoid（recut 已标注，与典型性排序同口径），图谱以
        is_medoid 标记供页面画星标大标记；
      * 边 = 簇内两两 Gower 距离，按距离降序取前 edge_limit 条（边表可选）。

    批次 6 merged 消费收口：merged_ids（cs_senses.status='merged' 的
    sense_id 集合，页面从 _load_sense_rows 现状取）中的义位**跳过不进图谱**
    （G3 分立复核定稿 —— 消费流向其并入目标，如实计数 n_merged_skipped
    供页面注明「N 条已并入不计入」）。坐标对保留成员的子方阵重投影
    （子阵条目与原方阵逐位一致，边距离仍是预计算 Gower 真值）；merged_ids
    为空时与原全量投影逐位一致（向后兼容）。

    Returns:
        {"k", "n_clusters", "n_senses", "n_merged_skipped",
         "nodes"（x/y/label/cluster_no/is_medoid/sense_id/verb）,
         "edges"（簇/成员对/Gower 距离）, "explained"（MDS 两轴解释率）,
         "labels"}；
        dendro/recut 不完整、assignments 与成员数不齐、或过滤后无保留成员
        → {}（不猜）。
    """
    members_all = (dendro or {}).get("members") or []
    dist = (dendro or {}).get("distance_matrix")
    assignments = (recut or {}).get("assignments") or []
    if not members_all or dist is None or not assignments:
        return {}
    if len(assignments) != len(members_all):
        return {}
    merged_set = {sid for sid in (_as_int_id(v) for v in (merged_ids or ()))
                  if sid is not None}
    kept: List[int] = []
    for i, m in enumerate(members_all):
        sid = _as_int_id(m.get("sense_id"))
        if sid is not None and sid in merged_set:
            continue  # G3 收口：merged 义位跳过（不计入图谱，消费流向并入目标）
        kept.append(i)
    if not kept:
        return {}
    labels_kept = [_sense_label(members_all[i].get("verb"),
                                members_all[i].get("sense_no")) for i in kept]
    medoid_ids: Dict[int, Optional[int]] = {}
    for cl in (recut.get("clusters") or []):
        medoid = cl.get("medoid")
        medoid_ids[int(cl.get("cluster_no") or 0)] = (
            _as_int_id(medoid.get("sense_id")) if isinstance(medoid, dict) else None)
    # MDS 投影：有跳过时对保留成员子方阵重投影；无跳过时 kept==全体下标，
    # 与原全量投影逐位一致（既有消费方不受影响）。
    if len(kept) == len(members_all):
        coords, explained = classical_mds_coordinates(dist)
    else:
        sub = [[dist[i][j] for j in kept] for i in kept]
        coords, explained = classical_mds_coordinates(sub)
    nodes: List[Dict[str, Any]] = []
    for pos, i in enumerate(kept):
        m = members_all[i]
        cluster_no = int(assignments[i])
        sid = _as_int_id(m.get("sense_id"))
        nodes.append({
            "sense_id": sid,
            "label": labels_kept[pos],
            "verb": str(m.get("verb") or ""),
            "cluster_no": cluster_no,
            "is_medoid": sid is not None and medoid_ids.get(cluster_no) == sid,
            "x": coords[pos][0] if pos < len(coords) else 0.0,
            "y": coords[pos][1] if pos < len(coords) else 0.0,
        })
    edges: List[Dict[str, Any]] = []
    for no in sorted(medoid_ids):
        kept_pos = [pos for pos, i in enumerate(kept) if int(assignments[i]) == no]
        for a in range(len(kept_pos)):
            for b in range(a + 1, len(kept_pos)):
                p, q = kept_pos[a], kept_pos[b]
                edges.append({
                    "簇": no,
                    "成员对": f"{labels_kept[p]} — {labels_kept[q]}",
                    "Gower 距离": float(dist[kept[p]][kept[q]]),
                })
    edges.sort(key=lambda e: e["Gower 距离"], reverse=True)
    edges = edges[:max(0, int(edge_limit))]
    return {
        "k": recut.get("k"),
        "n_clusters": recut.get("n_clusters"),
        "n_senses": len(nodes),
        "n_merged_skipped": len(members_all) - len(kept),
        "nodes": nodes,
        "edges": edges,
        "explained": explained,
        "labels": labels_kept,
    }


# ============================================
# Streamlit 页面（F3 谱系树 + F6 典型性排序 + 批次 5 双 tab）
# ============================================

def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span，文本须先经 _html_escape）。

    RV1-2（_badge 收敛）：实现单份进 design_system.get_badge_html ——
    文字颜色按底色自动选深/浅（旧版写死白字，浅底不达 WCAG AA）；
    转义契约不变。
    """
    return get_badge_html(text, color)


def _member_name(m: Dict[str, Any]) -> str:
    """成员显示名：verb·sense_no（义位标签），全部经 _html_escape。"""
    no = f"·{_html_escape(str(m['sense_no']))}" if m.get("sense_no") else ""
    return f"{_html_escape(str(m['verb']))}{no} {_html_escape(str(m['sense_label']))}"


@st.cache_data(ttl=600, show_spinner=False)
def _load_page_data(cache_scope: str, category: str, language: str) -> Dict[str, Any]:
    """页面级缓存（10 分钟）：典型性排序 + 谱系树数据一次装载。

    首参 cache_scope（**不得**加下划线前缀）由调用方传
    mysql_db.cache_scope_key()：st.cache_data 的键只含入参，且**下划线开头的
    参数不参与哈希**（Streamlit 明确行为）—— 曾把作用域传进 `_cache_scope`
    下划线参数，等于没进键，测试切换 MYSQL_DATABASE 指向测试库时键不变，
    会把业务库的聚类矩阵串进「空测试库」用例（S1 review 修复本身失效，
    S3 合跑复现：换库必须换缓存槽位，跨库隔离）。

    R4-1 fail-closed 归因：返回值新增 ``load_error`` 键（None=数据层可达，
    str=取数探针查询失败的原因）。取数失败时 ranking 归 []、
    dendro 归 {"load_error": 原因}，页面据此分流「数据不可用（勿重跑灌库）」
    与「未灌入」（键只加不改，既有消费方不受影响）。

    归因两层（R4-1 尾部「缺表 vs 真数据不足」二分）：主探针只验
    cs_cluster_runs；主探针可达但 ranking 仍空时，底层 get_clusters_with_members
    等可能把深层缺表（cs_clusters/cs_cluster_members/cs_senses/cs_lexemes/
    cs_sense_features）静默折叠成 [] —— 此时以 _cluster_family_reachable_error
    深探针（覆盖 _load_cluster_matrix 全部读面）二次归因，失败同样归
    load_error（页面与谱系/分立/图谱三 tab 均走「数据不可用」，不再误报
    「数据不足/未灌入」）。深探针仅空态分支调用，正常路径零开销。"""
    load_error: Optional[str] = None
    try:
        # 数据层可达性探针：底层 category_study.get_cluster_runs 对异常静默
        # 返 []，无法区分「查询失败」与「真没数据」—— 这里直接探一次主表，
        # 失败即归因为服务端异常（勿重跑灌库），成功则维持既有空态语义。
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM cs_cluster_runs")
            cursor.fetchone()
    except Exception as e:
        load_error = f"语义分析数据读取失败：{e}"
    ranking: List[Dict[str, Any]] = []
    dendro: Dict[str, Any] = {}
    if load_error:
        dendro = {"load_error": load_error}
    else:
        # 批次 19 工具页面接线（规范 §4，semantic_search.py 先例同款）：
        # 页面取数改经 get_tool("typicality").run(...) —— 同模块自委托，
        # registry 未加载回落原直调逐字节等价；行为与缓存语义不变。
        from src.tools.registry import get_tool as _get_tool
        _typ = _get_tool("typicality")
        ranking = (_typ.run({"category": category, "language": language})
                   if _typ is not None else
                   compute_medoid_ranking(category, language))
        if not ranking:
            # R4-1/R4-5 尾部二分：主探针可达但 ranking 空 —— 深探针区分
            # 「真未灌入」与「表族缺表/读取失败被底层静默折叠成 []」；
            # 后者归 load_error，防止误导重跑灌库与「数据不足」误报。
            deep_error = _cluster_family_reachable_error()
            if deep_error:
                load_error = deep_error
                dendro = {"load_error": load_error}
    scipy_missing = False
    if ranking:
        try:
            _clu = _get_tool("clustering")
            dendro = (_clu.run({"category": category, "language": language})
                      if _clu is not None else
                      build_dendrogram_data(category, language))
        except ImportError:
            scipy_missing = True
    return {"ranking": ranking, "dendro": dendro, "scipy_missing": scipy_missing,
            "load_error": load_error}


def _recut_comparison_rows(recut: Dict[str, Any]) -> pd.DataFrame:
    """重切结果 → k 簇成员清单对比表（簇号/成员数/medoid 标注/成员清单）。"""
    rows = []
    for cl in recut["clusters"]:
        medoid = cl.get("medoid")
        rows.append({
            "簇": cl["cluster_no"],
            "成员数": cl["size"],
            "medoid": _member_name(medoid) if medoid else "—",
            "成员清单": "、".join(
                _sense_label(m["verb"], m["sense_no"]) for m in cl["members"]),
        })
    return pd.DataFrame(rows)


def _render_recut_save(dendro: Dict[str, Any], recut: Dict[str, Any]) -> None:
    """「保存为新运行版本」控件：checkbox 确认（st.confirm 式）→ 写库反馈。

    保存走 save_interactive_cluster_run（cs_cluster_runs 追加新 version），
    UNIQUE(category_id, language, version) 冲突时不覆盖既有行，页面提示改
    版本号。
    """
    confirm = st.checkbox(
        "我确认保存：交互切割结果为探索性运行，与预计算版共存互不覆盖",
        key="ca_save_confirm")
    custom = st.text_input("版本号（留空自动生成「交互-时间戳」）",
                           key="ca_save_version")
    if st.button("💾 保存为新运行版本", key="ca_save_btn"):
        if not confirm:
            st.warning("请先勾选上方确认框（保存为探索性运行版本）。")
            return
        result = save_interactive_cluster_run(
            dendro, recut, version=custom.strip() or None)
        if result.get("ok"):
            st.success(
                f"已保存为新运行版本「{result['version']}」"
                f"（{result['n_clusters']} 簇 / {result['n_members']} 个成员）。"
                f"交互切割结果为探索性运行，与预计算版共存互不覆盖。")
        elif result.get("conflict"):
            st.error(
                f"版本号「{result.get('version')}」已存在"
                f"（同范畴+语言+版本唯一），请改版本号后重试。")
        else:
            st.error(f"保存失败：{result.get('error', '未知错误')}")


def _render_dendrogram(dendro: Dict[str, Any]) -> None:
    """谱系树 tab：plotly create_dendrogram（预计算 Gower 矩阵直传）+ k 切分参考线
    + 交互式谱系切割（F2：fcluster maxclust 重切 + 保存为新运行版本）。

    降级三层（R4-7/R4-5）：plotly 缺失 → 入口 warning＋return（与 scipy 同款
    双层降级）；取数失败（dendro.load_error）→ 「数据不可用：<原因>」；
    树真为空（成员少于 2 个 / 运行缺 linkage）→ 数据不足提示。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>谱系树（Gower + average 层次聚类）</h3>",
                unsafe_allow_html=True)
    if not HAS_PLOTLY:
        st.warning("plotly 未安装，谱系树 tab 不可用（pip install plotly）；"
                   "典型性排序不受影响。")
        return
    if dendro.get("load_error"):
        st.warning(
            f"数据不可用：{dendro['load_error']}。属服务端异常，"
            "**勿重跑灌库脚本**；恢复后刷新本页即可。"
        )
        return
    if not dendro or not dendro.get("linkage"):
        st.warning("谱系树数据不足（簇成员少于 2 个）。")
        return
    from plotly.figure_factory import create_dendrogram

    k = dendro.get("k")
    cut = dendro.get("cut_height")
    # scipy 不原生支持 gower 度量：预计算好的 Gower 方阵经 distfun 压缩成
    # 紧凑距离向量，linkagefun 固定 average（UPGMA），与 d1 运行口径一致。
    # plotly 要求 X 为二维 ndarray（列表无 .shape 属性）。
    fig = create_dendrogram(
        np.asarray(dendro["distance_matrix"], dtype=float),
        distfun=_scipy_squareform,
        linkagefun=lambda d: _scipy_linkage(d, method="average"),
        labels=dendro["labels"],
        color_threshold=cut,
    )
    if cut is not None:
        fig.add_hline(
            # RV1-6：参考线深档红（白底 5.47:1；旧 #e53e3e 4.13:1）
            y=cut, line_dash="dash", line_color="#c53030",
            annotation_text=f"k={k} 探索性切分参考线",
            annotation_position="top right",
        )
    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(tickfont=dict(size=10)),
        plot_bgcolor="#ffffff",
    )
    st.plotly_chart(fig, use_container_width=True)
    if cut is not None:
        cut_note = (f"红色虚线为 k={k} 的探索性切分参考线"
                    f"（该高度再合并一次即跌破 {k} 簇）—— ")
    else:
        cut_note = "运行参数未提供有效 k，未画切分参考线 —— "
    coph = dendro.get("cophenetic")
    try:
        coph_note = (f"源运行版本「{dendro.get('version') or '—'}」"
                     f"cophenetic 共表相关系数 {float(coph):.3f}，"
                     f"越高树越保真两两距离。") if coph else ""
    except (TypeError, ValueError):
        coph_note = ""
    st.caption(
        f"方法：Gower 相异度（binary/nominal 不一致记 1，ordinal 归一差值）"
        f"+ average 联接（UPGMA），共 {dendro['n_senses']} 个义位、"
        f"{len(dendro['linkage'])} 次合并。{cut_note}{coph_note}"
        f"层次树本身支持任意高度切割，"
        f"k=5 只是 d1 试点采用的探索性解，不是唯一正确答案。"
    )

    # —— 交互式谱系切割（论文 §5.1「可交互切割」；对照清单 F2）——
    st.markdown(f"<h3 style='{HEADER_H3}'>交互式谱系切割</h3>",
                unsafe_allow_html=True)
    n = int(dendro.get("n_senses") or len(dendro["linkage"]) + 1)
    k_max = max(2, min(RECUT_K_MAX, n))
    run_k = dendro.get("k")
    default_k = (run_k if run_k and 2 <= run_k <= k_max
                 else min(RECUT_K_DEFAULT, k_max))
    k_choice = st.slider(
        "切割簇数 k", min_value=2, max_value=k_max, value=default_k,
        key="ca_recut_k",
        help=f"scipy fcluster(maxclust) 对当前谱系树重切（2–{RECUT_K_MAX}，"
             f"此处上限为 min(10, 义位数)={k_max}）；默认当前运行参数的 k。")
    recut = recut_clusters(dendro, k_choice)
    if not recut:
        st.warning(f"k={k_choice} 无法重切（谱系树数据不足）。")
        return
    st.dataframe(_recut_comparison_rows(recut), hide_index=True)
    st.caption(
        "medoid 口径：与典型性排序一致（簇内到其他成员平均 Gower 距离最小者，"
        "平局取叶序靠前者），距离取预计算方阵子阵重算；tier 三分位不在此重贴"
        "（正式运行看典型性排序 tab）。同高合并平局处 fcluster(maxclust) 可能"
        "给出少于 k 的簇数（scipy 语义）。"
        "交互切割结果为探索性运行，与预计算版共存互不覆盖（对照清单 F2）。"
    )
    _render_recut_save(dendro, recut)


def _render_tier_bars(cluster: Dict[str, Any]) -> None:
    """单簇成员距离条形图（plotly 横条，tier 分色，最近成员在顶部）。"""
    if not HAS_PLOTLY:
        st.caption("（plotly 未安装，条形图不可用 —— 成员排序表不受影响。）")
        return
    import plotly.express as px

    members = cluster["members"]
    df = pd.DataFrame({
        "成员": [_member_name(m) for m in members],
        "到 medoid 的 Gower 距离": [m["gower_to_medoid"] for m in members],
        "典型性层级": [TIER_LABELS[m["tier"]] for m in members],
    })
    fig = px.bar(
        df, x="到 medoid 的 Gower 距离", y="成员", orientation="h",
        color="典型性层级", color_discrete_map={
            TIER_LABELS[TIER_PROTOTYPE]: TIER_COLORS[TIER_PROTOTYPE],
            TIER_LABELS[TIER_TYPICAL]: TIER_COLORS[TIER_TYPICAL],
            TIER_LABELS[TIER_PERIPHERY]: TIER_COLORS[TIER_PERIPHERY],
        },
        category_orders={"成员": df["成员"].tolist()},
        text="到 medoid 的 Gower 距离",
    )
    fig.update_yaxes(autorange="reversed")  # 升序成员列表 → 距离最小者画在顶部
    fig.update_traces(texttemplate="%{x:.3f}", textposition="outside")
    fig.update_layout(
        height=max(240, 46 * len(members) + 90),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(range=[0, max(0.05, max(
            m["gower_to_medoid"] for m in members) * 1.15)]),
        plot_bgcolor="#ffffff",
    )
    st.plotly_chart(fig, use_container_width=True)


# ============================================
# Streamlit 页面 · 批次 5 双 tab（🧬 义项分立复核 / 🕸️ 义位图谱）
# ============================================

_DIV_FLASH_KEY = "ca_division_flash"


def _flash_division(level: str, text: str) -> None:
    """tab 内操作反馈（st.rerun 前入 session_state，重跑后弹出 —— collab_pages 同款）。"""
    st.session_state[_DIV_FLASH_KEY] = {"level": level, "text": text}


def _pop_flash_division() -> None:
    """弹出并清空一条待展示反馈（level 白名单外的脏值丢弃，不打崩页面）。"""
    msg = st.session_state.pop(_DIV_FLASH_KEY, None)
    if isinstance(msg, dict) and msg.get("level") in ("success", "error", "warning", "info"):
        getattr(st, msg["level"])(str(msg.get("text") or ""))


def _status_display(m: Dict[str, Any]) -> str:
    """成员的 cs_senses 现状展示（批次 6 收口）：merged → 「已并入 → #N」标注。

    status='merged' 的义位是分立复核落地结果，下游（模板/图谱）不再消费，
    证据视图以「已并入 → #N」标注（merged_into 缺失给「去向待补录」）；
    其余 status 维持原样（含 merged_into 指向）。
    """
    merged_text = merged_sense_display(m.get("status"), m.get("merged_into"))
    if merged_text:
        return merged_text
    status = m.get("status") or "—"
    target = m.get("merged_into")
    if target is not None:
        return f"{status} → #{target}"
    return str(status)


def _render_division_form(category: str, language: str, dendro: Dict[str, Any],
                          evidence: List[Dict[str, Any]],
                          user: Dict[str, Any]) -> None:
    """建议表单（登录即可提议）：动作/目标簇/sense 清单/（merge 时）保留目标/理由。

    提议只入台账（ai_ledger.record_proposal kind='draft', stage='sense_division'，
    unit_ref=f"{category}:{language}"，evidence_ref=簇运行版本，uncertainty=None
    —— 人工建议无综合信号，不编数），adopted 才由裁决流程落地 cs_senses。
    """
    if not evidence:
        st.warning("无簇证据可引用（运行簇清单为空），暂不能发起建议。")
        return
    action = st.selectbox(
        "动作", options=list(SENSE_DIVISION_ACTIONS),
        format_func=lambda a: SENSE_DIVISION_ACTION_LABELS.get(a, a),
        key="ca_div_action",
        help="merge=并入同一目标（被并义位 status='merged'、merged_into 指向保留目标）；"
             "split=应拆分（status='split'）；keep=维持现状（仅留痕）。")
    cluster = st.selectbox(
        "目标簇", options=evidence,
        format_func=lambda c: f"簇{c['cluster_no']} · {c['name']}（{c['size']} 成员）",
        key="ca_div_cluster")
    if cluster.get("locked"):
        st.caption("⚠️ 该簇已锁定（分立复核定稿，G3）：如需调整义项清单请先解锁；"
                   "对已定稿簇的合并/拆分建议按修订请求对待。")
    members = cluster["members"]
    option_of = {f"{m['name']} (#{m['sense_id']})": m for m in members}
    picked_labels = st.multiselect(
        "sense 清单（所选簇成员）", options=list(option_of.keys()),
        key="ca_div_senses",
        help="同一簇内的义位；显示名后缀 #sense_id 消歧。")
    target = None
    if action == "merge":
        if picked_labels:
            target_label = st.selectbox(
                "合并保留目标（merged_into 指向它）", options=picked_labels,
                key="ca_div_target")
            target = option_of[target_label]["sense_id"]
        else:
            st.caption("先在上方选择 ≥2 个 sense，再指定保留目标。")
    reason = st.text_area(
        "理由（必填）", key="ca_div_reason", height=72,
        placeholder="写明证据：簇内距离/词频/释义分歧/词典学依据…")
    if st.button("📤 提交分立建议", key="ca_div_submit", type="primary"):
        picked_rows = [option_of[label] for label in picked_labels]
        proposal, err = build_sense_division_proposal(
            action, cluster["cluster_no"], picked_rows, reason,
            target_sense_id=target, run_id=dendro.get("run_id"),
            version=dendro.get("version"))
        if err:
            st.error(err)
            return
        pid = record_proposal(
            KIND_DRAFT, SENSE_DIVISION_STAGE, f"{category}:{language}",
            proposal, evidence_ref=dendro.get("version") or None,
            uncertainty=None, created_by=_as_int_id(user.get("id")))
        if pid:
            _flash_division(
                "success", f"分立建议已登记为提案 #{pid}，"
                           "待词典管理员/审校裁决（G3 闸门：分立→释义）。")
            st.rerun()
        else:
            st.error("登记失败（AI 台账不可用或载荷被拒），请稍后重试。")


def _render_division_adjudication(p: Dict[str, Any], user: Dict[str, Any]) -> None:
    """单条待裁决提议：详情 ＋ 理由框 ＋ 采纳执行/否决/修改后采纳（仅留痕）。

    流程（collab_pages._decide_buttons 同款）：点按钮 → 校验 →
    adjudicate_sense_division（decide 留痕 → adopted 才落地）→ flash ＋
    st.rerun；裁决失败原位提示（通常已被他人抢先裁决）。
    """
    pid = int(p.get("id") or 0)
    proposal = p.get("proposal") if isinstance(p.get("proposal"), dict) else {}
    st.json(proposal)
    cols = st.columns(2)
    cols[0].caption(
        f"证据引用：{p.get('evidence_ref') or '（无）'} · "
        f"登记时间：{p.get('created_at') or '—'}")
    cols[1].caption(
        f"工作单元：{p.get('unit_ref') or '—'} · 不确定度："
        f"{p.get('uncertainty') if p.get('uncertainty') is not None else '—'}")
    reason = st.text_area(
        "裁决理由（否决必填；采纳建议填写 —— 留痕可复现）",
        key=f"ca_div_reason_{pid}", height=68)
    adopt_col, reject_col, modify_col = st.columns(3)
    clicked: Optional[str] = None
    if adopt_col.button("✅ 采纳执行", key=f"ca_div_adopt_{pid}", type="primary"):
        clicked = DECISION_ADOPTED
    if reject_col.button("⛔ 否决", key=f"ca_div_reject_{pid}"):
        clicked = DECISION_REJECTED
    if modify_col.button("✏️ 修改后采纳（仅留痕）", key=f"ca_div_modify_{pid}"):
        clicked = DECISION_MODIFIED
    if clicked is None:
        return
    if clicked == DECISION_REJECTED and not (
            isinstance(reason, str) and reason.strip()):
        _flash_division("error", f"提案 #{pid}：否决必须填写理由（架构纪律）。")
        st.rerun()
    clean_reason = reason.strip() if isinstance(reason, str) else None
    result = adjudicate_sense_division(
        pid, clicked, clean_reason or None, _as_int_id(user.get("id")) or 0, proposal)
    if result.get("ok"):
        if result.get("executed"):
            _flash_division(
                "success", f"提案 #{pid} 已采纳并落地 cs_senses"
                           f"（更新 {result.get('updated')} 行；G3 留痕完整）。")
        else:
            _flash_division(
                "success", f"提案 #{pid} 已裁决为"
                           f"「{SENSE_DIVISION_ACTION_LABELS.get(clicked, clicked)}」"
                           "（仅留痕，不落地）。")
    else:
        _flash_division("error", f"提案 #{pid} 裁决失败：{result.get('error')}")
    st.rerun()


def _render_cluster_lock_section(evidence: List[Dict[str, Any]],
                                 user: Optional[Dict[str, Any]]) -> None:
    """簇锁定/解锁（G3 闸门写路径，批次 6）：adjudicator 出控件，其余角色出提示。

    锁定语义（G3「分立→释义」）：locked=1 = 该簇义项清单**复核定稿**，
    才允许流入释义撰写（阶段 2 消费约定）；解锁即退回未定稿。权限判定复用
    _is_division_adjudicator（effective 六角色 dict_admin/reviewer；过渡期
    role=='admin' 兼容），不 import app（页面模块间不横向依赖）。写库走
    set_cluster_locked（参数化 UPDATE cs_clusters），成功后该函数已清
    _load_cluster_locks 缓存，flash ＋ st.rerun 即时刷新徽章。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>簇锁定（G3 闸门：复核定稿）</h3>",
                unsafe_allow_html=True)
    if not (isinstance(user, dict) and _is_division_adjudicator(user)):
        st.caption("锁定/解锁由词典管理员/审校执行（effective 六角色需 "
                   "dict_admin/reviewer；过渡期 role=='admin' 兼容）—— "
                   "locked 簇的义项清单视为复核定稿，阶段 2 才允许流入释义撰写。")
        return
    if not evidence:
        st.caption("无簇可锁定（当前运行簇清单为空）。")
        return
    st.caption(
        "锁定＝该簇义项清单复核定稿（G3 闸门「分立→释义」：locked 簇才允许"
        "流入释义撰写，阶段 2 消费约定）；解锁即退回未定稿。写库为参数化 "
        "UPDATE cs_clusters.locked，操作即时生效并刷新证据视图徽章。"
    )
    cluster = st.selectbox(
        "选择簇", options=evidence,
        format_func=lambda c: (
            f"簇{c['cluster_no']} · {str(c['name']).split('（')[0]}"
            f"（{c['size']} 成员）{' 🔒 已锁定' if c.get('locked') else ''}"),
        key="ca_lock_cluster")
    current = bool(cluster.get("locked"))
    lock_col, unlock_col = st.columns(2)
    if lock_col.button("🔒 锁定（复核定稿）", key="ca_lock_btn", type="primary"):
        if current:
            st.info(f"簇{cluster['cluster_no']} 已处于锁定状态（复核定稿），无需重复锁定。")
        else:
            result = set_cluster_locked(cluster.get("cluster_id"), True)
            if result.get("ok"):
                _flash_division(
                    "success",
                    f"簇{cluster['cluster_no']}（#{result.get('cluster_id')}）已锁定："
                    "义项清单复核定稿（G3 放行，阶段 2 可流入释义撰写）。")
                st.rerun()
            else:
                st.error(f"锁定失败：{result.get('error', '未知错误')}")
    if unlock_col.button("🔓 解锁", key="ca_unlock_btn"):
        if not current:
            st.info(f"簇{cluster['cluster_no']} 未锁定（无需解锁）。")
        else:
            result = set_cluster_locked(cluster.get("cluster_id"), False)
            if result.get("ok"):
                _flash_division(
                    "success",
                    f"簇{cluster['cluster_no']}（#{result.get('cluster_id')}）已解锁："
                    "退回未定稿（G3 收紧，阶段 2 暂停消费该簇）。")
                st.rerun()
            else:
                st.error(f"解锁失败：{result.get('error', '未知错误')}")


def _render_sense_division_tab(category: str, language: str,
                               data: Dict[str, Any]) -> None:
    """🧬 义项分立复核 tab（工序 8 · 闸门 G3「分立→释义」的人工工作台）。

    四段：
      1. 簇证据视图（全角色可看）：最近运行簇清单（成员/medoid/簇内平均 Gower
         距离/cs_senses 现状 —— merged 行标注「已并入 → #N」）＋词频列
         （corpus_word_stats，缺数据灰注降级）；locked 簇加「已锁定」徽章；
      2. 簇锁定（G3 闸门写路径，词典管理员/审校）：锁定=义项清单复核定稿；
      3. 发起建议（登录即可）：merge/split/keep → ai_proposals 台账留痕；
      4. 裁决区（词典管理员/审校，effective 六角色；过渡期 role=='admin' 兼容）：
         list_pending(stage='sense_division') 逐条裁决，adopted 才落地
         cs_senses；区首显示 cs_senses 落地结果计数（merged/split 条数，
         merged 如实注明不计入模板/图谱）。

    渲染入口先跑 ensure_sense_split_columns() 与 ensure_cluster_locked_column()
    （幂等迁移；迁移口径与主库迁移记录见各自函数与模块 docstring）。
    """
    ensure_sense_split_columns()
    ensure_cluster_locked_column()
    dendro = (data or {}).get("dendro") or {}
    # R4-5 三口径：取数失败（load_error，带原因）vs 真不足（成员少于 2 个）
    if dendro.get("load_error"):
        st.warning(
            f"数据不可用：{dendro['load_error']}。属服务端异常，"
            "**勿重跑灌库脚本**，分立复核暂不可用；恢复后刷新本页即可。"
        )
        return
    if not dendro or not dendro.get("linkage"):
        st.warning("谱系树数据不足（簇成员少于 2 个），分立复核不可用。")
        return
    ranking = (data or {}).get("ranking") or []
    cache_scope = cache_scope_key()
    members_all = dendro.get("members") or []
    sense_ids = tuple(sid for sid in (_as_int_id(m.get("sense_id")) for m in members_all)
                      if sid is not None)
    verbs = tuple(sorted({str(m.get("verb") or "") for m in members_all}))
    cluster_ids = tuple(cid for cid in (_as_int_id(c.get("cluster_id")) for c in ranking)
                        if cid is not None)
    sense_rows = _load_sense_rows(cache_scope, sense_ids)
    freqs = _load_word_freqs(cache_scope, verbs)
    locks = _load_cluster_locks(cache_scope, cluster_ids)
    evidence = build_sense_division_evidence(dendro, ranking, freqs=freqs,
                                             sense_rows=sense_rows, locks=locks)
    _pop_flash_division()

    st.markdown(f"<h3 style='{HEADER_H3}'>簇证据视图（最近运行簇清单）</h3>",
                unsafe_allow_html=True)
    st.caption(
        "闸门 G3（分立→释义）：该簇分立复核定稿（义项清单锁定）后才进入释义撰写。"
        "每簇：🏆 medoid（簇内到其他成员平均距离最小者）、簇内平均两两 Gower 距离、"
        "成员清单（含词频与 cs_senses 现状 —— merged 行标注「已并入 → #N」"
        "（分立复核定稿，模板/图谱不再消费））。"
    )
    if not freqs:
        st.caption("（corpus_word_stats 词频暂无数据或不可用 —— 词频列留空，不编数。）")
    for cluster in evidence:
        title = str(cluster["name"]).split("（")[0]
        avg = cluster["avg_pairwise"]
        avg_text = "—" if avg is None else f"{avg:.3f}"
        lock_mark = " 🔒 已锁定" if cluster.get("locked") else ""
        header = (f"簇{cluster['cluster_no']} · {title}（{cluster['size']} 成员）"
                  f" 🏆 medoid: {cluster['medoid_name']} · 簇内平均距离 {avg_text}"
                  f"{lock_mark}")
        with st.expander(header, expanded=False):
            if cluster.get("locked"):
                st.markdown(
                    _badge("已锁定 · 复核定稿（G3 放行释义撰写）", LOCKED_COLOR),
                    unsafe_allow_html=True)
            rows = pd.DataFrame([{
                "成员": m["name"],
                "sense_id": m["sense_id"],
                "到 medoid 距离": m["gower_to_medoid"],
                "典型性层级": TIER_LABELS.get(m["tier"], m["tier"]),
                "词频": m["freq"],
                "cs_senses 现状": _status_display(m),
            } for m in cluster["members"]])
            st.dataframe(rows, hide_index=True)

    user = _session_user()
    _render_cluster_lock_section(evidence, user)

    st.markdown(f"<h3 style='{HEADER_H3}'>发起分立建议</h3>", unsafe_allow_html=True)
    if not isinstance(user, dict):
        st.info("登录后即可发起分立建议（全部角色可提议）；"
                "裁决由词典管理员/审校执行（G3 闸门）。")
    else:
        _render_division_form(category, language, dendro, evidence, user)

    st.markdown(f"<h3 style='{HEADER_H3}'>裁决区（词典管理员/审校）</h3>",
                unsafe_allow_html=True)
    counts = sense_division_landing_counts(sense_rows)
    merged_note = (f"（其中 {counts['merged']} 条已并入不计入模板/图谱，"
                   "消费流向其并入目标）" if counts["merged"] else "")
    st.caption(
        f"cs_senses 落地结果计数（当前运行成员 {counts['total']} 条）："
        f"merged {counts['merged']} 条 · split {counts['split']} 条{merged_note}。"
    )
    if not _is_division_adjudicator(user):
        st.caption("当前会话无裁决权（effective 六角色需 dict_admin/reviewer；"
                   "过渡期 role=='admin' 兼容）—— 可查看证据并发起建议。")
        return
    pending = list_pending(kind=KIND_DRAFT, stage=SENSE_DIVISION_STAGE,
                           limit=DIV_PENDING_LIMIT)
    if not pending:
        st.info("sense_division 工序暂无待裁决提议（台账为空或 AI 台账不可用）。")
        return
    st.caption(
        f"共 {len(pending)} 条待裁决（按不确定度降序；含全部范畴/语言的 "
        f"sense_division 提议，unit_ref 注明归属）。"
    )
    for p in pending:
        payload = p.get("proposal") if isinstance(p.get("proposal"), dict) else {}
        action_label = SENSE_DIVISION_ACTION_LABELS.get(payload.get("action"), "?")
        with st.expander(f"提案 #{p.get('id')} · {action_label} · "
                         f"{p.get('unit_ref') or '（无单元）'}"):
            _render_division_adjudication(p, user)


def _render_sense_graph_tab(dendro: Dict[str, Any]) -> None:
    """🕸️ 义位图谱 tab：经典 MDS 前两轴散点（簇着色、medoid 星标）＋边表可选。

    坐标方案（如实可行、不造假坐标）：scipy 无 MDS，sklearn 不在 requirements
    （零新依赖纪律）→ 用 classical_mds_coordinates（Torgerson 经典 MDS，
    numpy 特征分解）取前两主轴 —— 定义良好的最优 2D 投影，两轴解释率如实
    展示；「原型居中」以 medoid 星标大标记呈现，投影下几何居中不保证。
    全部差异在页面 caption 注明（论文 §7.2 口径）。

    降级三层（R4-7/R4-5）：plotly 缺失 → 入口 warning＋return（不再让函数顶部
    的 plotly import 直接炸 tab）；取数失败（dendro.load_error）→ 「数据不可用：
    <原因>」；树真为空 → 数据不足提示。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>义位图谱（原型居中 · 边=Gower 距离）</h3>",
                unsafe_allow_html=True)
    if not HAS_PLOTLY:
        st.warning("plotly 未安装，义位图谱 tab 不可用（pip install plotly）；"
                   "典型性排序不受影响。")
        return
    import plotly.express as px
    import plotly.graph_objects as go

    if dendro.get("load_error"):
        st.warning(
            f"数据不可用：{dendro['load_error']}。属服务端异常，"
            "**勿重跑灌库脚本**，义位图谱暂不可用；恢复后刷新本页即可。"
        )
        return
    if not dendro or not dendro.get("linkage"):
        st.warning("谱系树数据不足（簇成员少于 2 个），义位图谱不可用。")
        return
    n_senses = int(dendro.get("n_senses") or len(dendro["linkage"]) + 1)
    k_max = max(2, min(RECUT_K_MAX, n_senses))
    run_k = dendro.get("k")
    default_k = run_k if run_k and 2 <= run_k <= k_max else min(RECUT_K_DEFAULT, k_max)
    k_choice = st.slider(
        "分组簇数 k（义位图谱）", min_value=2, max_value=k_max, value=default_k,
        key="ca_graph_k",
        help="与谱系树 tab 同源的 fcluster(maxclust) 重切（复用已算好 linkage，"
             "不重算 Gower）；图谱以重切结果为分组键。")
    recut = recut_clusters(dendro, k_choice)
    if not recut:
        st.warning(f"k={k_choice} 无法重切（谱系树数据不足）。")
        return
    # 批次 6 merged 消费收口：cs_senses.status='merged' 的义位不进图谱
    # （G3 分立复核定稿，消费流向其并入目标），如实注明跳过计数。
    cache_scope = cache_scope_key()
    members_all = dendro.get("members") or []
    sense_ids = tuple(sid for sid in (_as_int_id(m.get("sense_id")) for m in members_all)
                      if sid is not None)
    sense_rows = _load_sense_rows(cache_scope, sense_ids)
    merged_ids = sorted(
        sid for sid, row in sense_rows.items()
        if str((row or {}).get("status") or "").strip().lower() == MERGED_STATUS)
    graph = build_sense_graph_data(dendro, recut, merged_ids=merged_ids or None)
    if not graph or not graph.get("nodes"):
        st.warning("图谱数据组装失败（预计算距离矩阵缺失，或成员已全部并入）。")
        return
    df = pd.DataFrame([{
        "MDS-1": node["x"],
        "MDS-2": node["y"],
        "簇": f"簇{node['cluster_no']}",
        "标签": node["label"],
        "sense_id": node["sense_id"],
    } for node in graph["nodes"]])
    cluster_order = [f"簇{no}" for no in sorted(
        {node["cluster_no"] for node in graph["nodes"]})]
    fig = px.scatter(
        df, x="MDS-1", y="MDS-2", color="簇",
        category_orders={"簇": cluster_order},
        hover_data={"标签": True, "sense_id": True},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    medoid_nodes = [node for node in graph["nodes"] if node["is_medoid"]]
    if medoid_nodes:
        fig.add_trace(go.Scatter(
            x=[m["x"] for m in medoid_nodes],
            y=[m["y"] for m in medoid_nodes],
            mode="markers", name="medoid（原型）",
            marker=dict(size=22, symbol="star", color=MEDOID_COLOR,
                        line=dict(width=1, color="#7b341e")),
            text=[m["label"] for m in medoid_nodes],
            textposition="top center",
        ))
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor="#ffffff", legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True)
    explained_pct = f"{graph.get('explained') or 0.0:.1%}"
    st.caption(
        f"口径注记（论文 §7.2「节点=义位、距离=Gower、原型居中」）："
        f"节点=k={graph.get('k')} 交互切割的义位成员；距离=谱系树预计算 Gower "
        f"方阵（不重算）；原型=medoid 星标大标记。本实现的如实差异：坐标为经典 "
        f"MDS（Torgerson，numpy 特征分解，零新依赖）前两主轴的最优 2D 投影，"
        f"两轴解释率 {explained_pct}（Gower 对混合变量不保证欧氏嵌入，负特征值"
        f"已舍去）—— 图上距离近似反映真实相异度，不是精确还原，更非示意造点；"
        f"「原型居中」以星标呈现，几何居中在投影下不保证。"
        f"边=簇内两两 Gower 距离（下方边表可选）。"
    )
    skipped = int(graph.get("n_merged_skipped") or 0)
    if skipped:
        st.caption(
            f"G3 收口：{skipped} 条已并入不计入（cs_senses status='merged'，"
            "分立复核定稿 —— 图谱与模板不再为其生成内容，消费流向其并入目标；"
            "坐标对保留成员重投影）。"
        )
    if st.checkbox("显示簇内边表（两两 Gower 距离，按距离降序）", key="ca_graph_edges"):
        edges = graph.get("edges") or []
        st.dataframe(pd.DataFrame(edges), hide_index=True)
        st.caption(f"边表上限 {GRAPH_EDGES_MAX} 条（按距离降序截断）。")


# ============================================
# Streamlit 页面 · 批次 8 合并页（📊 语义分析：谱系四 tab + 英汉对比五 tab）
# ============================================

def _render_typicality_tab(data: Dict[str, Any]) -> None:
    """🏆 典型性 tab（F6，论文 §5.2）：medoid 徽章 + 距离条形图 + 三级典型性。

    批次 8 从原 render_cluster_analysis_page 的典型性块原样抽出（渲染逻辑
    逐字不变），供旧四 tab 页与合并页共用。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>各簇典型性排序"
                f"（medoid = 簇内到其他成员平均距离最小者）</h3>",
                unsafe_allow_html=True)
    st.caption(
        "层级三分位：距 medoid 最近 1/3 = 原型（prototype），中 1/3 = 次典型"
        "（typical），最远 1/3 = 边缘（periphery）；medoid 距离恒为 0，"
        "必属原型。"
    )
    for cluster in data["ranking"]:
        medoid = cluster["medoid"]
        # expander 标签不渲染 HTML（streamlit 前端 allowHTML=False，S1 review）：
        # 徽章 span 会原样显示成字面文本，medoid 改用纯文本标注；
        # 标签由 Streamlit 自带转义，DB 文本无需（也不能）先过 _html_escape。
        title = str(cluster["cluster_name"]).split("（")[0]
        medoid_no = f"·{medoid['sense_no']}" if medoid.get("sense_no") else ""
        header = (
            f"簇{cluster['cluster_no']} · {title}"
            f"（{cluster['size']} 成员） 🏆 medoid: "
            f"{medoid['verb']}{medoid_no} {medoid['sense_label']}"
        )
        with st.expander(header, expanded=len(data["ranking"]) <= 6):
            _render_tier_bars(cluster)
            legend = " ".join(
                _badge(f"{TIER_LABELS[t]} "
                       f"({sum(1 for m in cluster['members'] if m['tier'] == t)})",
                       TIER_COLORS[t])
                for t in (TIER_PROTOTYPE, TIER_TYPICAL, TIER_PERIPHERY)
            )
            st.markdown(legend, unsafe_allow_html=True)


def render_semantic_analysis_page() -> None:
    """📊 语义分析页（批次 8 合并：「🏃‍♀️ 范畴深挖」+「📈 谱系与典型性」）。

    「一个动作一个门」收口页，st.tabs 九个，全部委托既有渲染、取数逻辑
    原样复用（_load_page_data / _load_category 装载段逐字保留，不改取数）：

      1-4 tab（谱系侧，本模块）：🌳 谱系树（F3/F2，标签 R8-2 缩短；交互
         切割在 tab 内）→ 🏆 典型性（F6）→ 🧬 分立复核（工序 8 · 闸门 G3）
         → 🕸️ 义位图谱（论文 §7.2）；
      5-9 tab（英汉对比侧，category_study_page 视图函数）：🫱🫲 双语对比 →
         🔥 编码热图 → 🔀 跨语言对齐 → ⚖️ 图式对齐 → 📋 总览。

    两侧读同一 cs_* 表族，谱系侧运行缺失不早退 —— 九 tab 各自降级
    （谱系 tab warning、对比 tab 引导 caption）。使用说明由
    app.render_cluster_entry 以 guide 键 "cluster" 渲染（本函数不重复渲染）；
    旧键 "category" 在 app.main() 顶部重定向一次（防书签断裂），
    旧入口 render_cluster_analysis_page / render_category_study_page 保留为
    兼容薄包装。
    """
    st.markdown(f"<h1 style='{HEADER_H1}'>📊 语义分析</h1>",
                unsafe_allow_html=True)
    st.caption(
        "谱系侧：F3 谱系树（Gower + average 层次聚类，k=5 探索性切分参考线）｜ "
        "F6 典型性排序（medoid 到簇内成员平均距离最小 → 原型/次典型/边缘三级）｜ "
        "工序 8 分立复核（G3 闸门：merge/split/keep 建议 → 裁决落地 cs_senses → "
        "簇锁定复核定稿，merged 义位下游不消费）｜ 义位级图谱（论文 §7.2）｜ "
        "英汉对比侧：五视图对应研究流水线（义位甄别 → P/M/C+A 特征编码 → "
        "双语独立聚类 → 双层对齐 → 总览甄别）"
    )

    # —— 谱系侧选择器与数据（原 render_cluster_analysis_page 装载逻辑原样）——
    packs = list(CATEGORIES()) or ["motion"]
    default_idx = packs.index("motion") if "motion" in packs else 0
    # FX-41（批次 20 挂账项）：ui.default_category 偏好接线 —— 偏好命中
    # 选项集才改首建 index；未登录/断库/无键/值空由 get_pref fail-closed
    # 返 None，偏好不在选项集保持原 motion 默认（ImportError 兜底并行读面
    # 未落），不崩页面。widget key 不变，index 只作用于首次实例化，
    # 不劫持用户手选。
    try:
        from src.user_context_db import get_pref

        pref = get_pref("ui.default_category")
        if pref in packs:
            default_idx = packs.index(pref)
    except ImportError:  # 并行读面未落 → 按无偏好降级
        pass
    category = st.selectbox("范畴", options=packs, index=default_idx,
                            key="ca_category")
    language = st.selectbox("语言", options=list(LANGUAGES),
                            format_func=lambda lang: LANGUAGE_LABELS.get(lang, lang),
                            key="ca_language")

    data = _load_page_data(cache_scope_key(), category, language)
    # R4-1/R4-5 三口径：load_error=取数失败（数据不可用，勿重跑灌库）；
    # ranking=[]（数据层可达）=未灌入（给灌库指引）；有数=正常渲染。
    if data.get("load_error"):
        st.warning(
            f"数据不可用：{data['load_error']}。属服务端异常，"
            "**勿重跑灌库脚本**；恢复后刷新本页即可。"
        )
    elif not data["ranking"]:
        st.info(
            f"范畴 {category}（{LANGUAGE_LABELS.get(language, language)}侧）"
            "暂无聚类运行数据。请先运行 scripts/load_category_study.py "
            "灌入语义分析数据。"
        )
    if data.get("scipy_missing"):
        st.warning("scipy 未安装，谱系树标签页不可用（pip install scipy）；"
                   "典型性排序不受影响。")

    # —— 英汉对比侧数据（原 render_category_study_page 装载逻辑原样搬移：
    #      ready → categories → _load_category 三级判定保留；R4-5 在 False/空
    #      分支各加一层可达性探针，区分「JOIN 失败」与「真没数据」）——
    cs_code: Optional[str] = None
    cs_cat: Optional[Dict[str, Any]] = None
    cs_data: Optional[Dict[str, Any]] = None
    if category_study_ready():
        categories = get_categories()
        if not categories:
            # ready() 已确认 categories 有行，到这里为空只剩 JOIN/读失败或竞态
            if _categories_table_reachable():
                st.warning(
                    "categories 为空：多见于灌数后页面缓存未刷新——请刷新本页重试；"
                    "仍为空请重跑 `MYSQL_HOST=127.0.0.1 python3 "
                    "scripts/load_category_study.py` 灌入研究数据。"
                )
            else:
                st.warning(
                    "数据不可用：categories 读取失败（JOIN 查询出错或连接中断），"
                    "**勿重跑灌库脚本**；恢复后刷新本页即可。"
                )
        else:
            if len(categories) == 1:
                cs_code = categories[0]["code"]
                cs_cat = categories[0]
            else:
                codes = [c["code"] for c in categories]
                name_of = {c["code"]: c["name_cn"] for c in categories}
                cs_code = st.selectbox(
                    "范畴", options=codes,
                    format_func=lambda c: f"{name_of[c]}（{c}）",
                    key="cs_category")
                cs_cat = next(c for c in categories if c["code"] == cs_code)
            cs_data = _load_category(cache_scope_key(), cs_code)
            if cs_data is None:
                st.warning(f"范畴 {cs_code} 数据加载失败。")
            else:
                st.caption(
                    f"范畴：{cs_cat['name_cn']}（{cs_cat['name_en']}）· 状态：{cs_cat['status']} · "
                    f"英语 {cs_cat['en_lexemes']} 词 {cs_cat['en_senses']} 义位 / "
                    f"汉语 {cs_cat['zh_lexemes']} 词条 {cs_cat['zh_senses']} 义位条目"
                )
    elif _categories_table_reachable():
        st.info(
            "语义分析数据尚未灌入。运行 "
            "`MYSQL_HOST=127.0.0.1 python3 scripts/load_category_study.py` "
            "从 data/d1/ 跑范畴两个 xlsx 加载。"
        )
    else:
        st.warning(
            "数据不可用：categories 表读取失败（数据库查询出错或连接中断）。"
            "属服务端异常，**勿重跑灌库脚本**；恢复后刷新本页即可。"
        )

    tab_tree, tab_typical, tab_division, tab_graph, tab_compare, tab_matrix, \
        tab_align, tab_schema, tab_family, tab_overview = st.tabs([
            "🌳 谱系树", "🏆 典型性", "🧬 分立复核", "🕸️ 义位图谱",
            "🫱🫲 双语对比", "🔥 编码热图", "🔀 跨语言对齐", "⚖️ 图式对齐",
            "🌐 图式谱系", "📋 总览"])

    with tab_tree:
        _render_dendrogram(data["dendro"])

    with tab_typical:
        _render_typicality_tab(data)

    with tab_division:
        _render_sense_division_tab(category, language, data)

    with tab_graph:
        _render_sense_graph_tab(data["dendro"])

    # —— 英汉对比五视图（委托 category_study_page 既有视图函数，取数不改）——
    for tab, render_view in (
            (tab_compare, render_cluster_compare_view),
            (tab_matrix, render_matrix_view),
            (tab_align, render_alignment_view),
            (tab_schema, render_schema_view),
            (tab_overview, render_overview_view),
    ):
        with tab:
            if cs_data is not None:
                render_view(cs_data)
            else:
                st.caption("（语义分析数据未就绪 —— 见页面顶部提示。）")

    # 🌐 图式谱系（批次 32：图式范畴化——工作流缺失环节平台化，P 构件插件）
    with tab_family:
        _render_schema_family_tab(category, language)


def render_cluster_analysis_page() -> None:
    """兼容薄包装（批次 8）：旧「📈 谱系与典型性」页入口 → 语义分析合并页。

    四 tab（谱系树/典型性排序/义项分立复核/义位图谱）已并入
    render_semantic_analysis_page（key=cluster，label 📊 语义分析）；
    本函数保留旧调用点（tests/test_cluster_analysis.py PAGE_SCRIPT 等）
    可用，行为 = 渲染合并页。
    """
    render_semantic_analysis_page()


def _render_schema_family_tab(category: str, language: str) -> None:
    """🌐 图式谱系（批次 32，工作流「图式范畴化」环节平台化）。

    对各簇提取的事件图式本身做二级归纳：三级归属向量（核心=2/槽位=1/缺省=0）
    → Gower nominal → UPGMA → 图式家族＋medoid 代表图式——更高层级的事件
    类型谱系。工具面：schema_family_tool（第 12 个内置工具，两步激活照全仓
    口径）。数据面：不落库（实时计算，簇数据变更即随指纹重算）。
    """
    from src import schema_family as _sf
    from src.template_engine import derive_cluster_schemas

    st.markdown("### 🌐 图式谱系（图式范畴化·事件类型层级）")
    st.caption(
        "理论：对各子簇提炼的事件图式本身进行归纳——梳理图式之间的亲缘关系与"
        "家族相似性，建立更高层级的事件类型谱系（图式范畴化）。方法：把义位"
        "聚类的同一套机器（Gower nominal＋UPGMA＋medoid）用在图式对象上——"
        "图式特征向量＝各语义槽三级归属（核心=2／槽位=1／缺省=0）。工具面："
        "schema_family_tool（第 12 个内置工具，P 构件，两步激活）。"
    )
    schemas = derive_cluster_schemas(category, language)
    if len(schemas) < 2:
        st.info(
            f"范畴 {category}（{language} 侧）当前 {len(schemas)} 个图式——"
            "≥2 个子簇图式后显示家族谱系。请先完成聚类与图式提取。"
        )
        return
    _sf_key = f"schema_family_result_{category}_{language}"
    if st.button("⚙️ 计算图式家族谱系", key=f"schema_family_calc_{category}_{language}"):
        st.session_state[_sf_key] = _sf.build_schema_families(schemas)
    result = st.session_state.get(_sf_key)
    if not result:
        st.caption("点上方「⚙️ 计算图式家族谱系」生成。")
        return
    st.dataframe(_sf.families_summary(result), use_container_width=True,
                 hide_index=True)
    for f in result.get("families", []):
        proto = f["prototype"]
        members_txt = "、".join(
            f"{m.get('cluster_no')}·{m.get('cluster_name')}"
            + ("（代表）" if m.get("is_prototype") else "")
            for m in f["members"])
        core_txt = "、".join(
            f"{cf.get('code')}·{cf.get('label', '')}"
            for cf in proto.get("core_features") or [])
        st.markdown(
            f"**家族 {f['family_no']}**（{len(f['members'])} 图式，"
            f"族内平均距离 {f['avg_distance']}）：{members_txt}  \n"
            f"代表图式：簇 {proto.get('cluster_no')}·{proto.get('cluster_name')} "
            f"—— 核心要素：{core_txt}"
        )

