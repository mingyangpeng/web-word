"""主编驾驶舱 · 十五道工序漏斗聚合（批次 3 Agent I，阶段1施工规范 §6）。

是什么（平台架构设计规范 §3 四阶段十五道工序链的「进度漏斗」数据段）：
  ``get_cluster_pipeline_status(category)`` 把语义分析段（工序 4–8）的进度数据
  聚合成六段漏斗，每段**如实**给数或如实声明缺数 —— 绝不编数：

    admission     工序4 义位准入   cs_senses.status 分组计数（保留/边缘/剔除/目标，
                                  经 cs_lexemes → categories 定位范畴）
    coding        工序5 特征标注   annotation_submissions 按 (task_type, status) 计数
    reliability   工序6 信度检验   reliability_runs 最近一次运行 overall_alpha（G2 达标线 0.7）
    clustering    工序7 聚类归类   cs_cluster_runs 最新运行版本 + 簇数（cs_clusters 计数）
    split_review  工序8 分立复核   cs_senses status ∈ {merged, split} 计数（G3 清单锁定）
    authoring     工序10–13 编纂成文  definition_versions（表当前未建 → 如实 None 段）

数据链（全部只读；本模块不建表、不写库）：
  mysql_db.get_db_cursor 参数化查询 cs_senses / cs_lexemes / categories /
  cs_cluster_runs / cs_clusters（category_study.py 建的范畴深挖 8 表）；
  annotation_submissions（annotation_flow.py 建）；reliability_runs
  （reliability.py 建）；definition_versions 只做 information_schema 存在性探测。
  范畴名到 categories.code 的解析复用 cluster_analysis.PACK_TO_STUDY_CODE 的口径
  （motion 包名 → RUN 研究代号），惰性导入避免聚合模块连带加载 pandas/streamlit。

缺数口径（「如实缺数」是本模块的第一纪律）：
  * 每段返回 ``{"data": <dict>|None, "reason": <str>|None}``：data 非 None 时
    reason 恒为 None；data 为 None 时 reason 必给一句话说明（表未建 / categories
    无此范畴 / 暂无运行记录 / 数据库不可用），由漏斗渲染成灰色「未建/无数据」行；
  * 表存在但该范畴 0 行 → None 段（「暂无」不是 0——0 条提交与「从未运行」
    在漏斗上含义不同）；唯一例外是 split_review：范畴已有义位而 merged/split
    均为 0 时给真 0（复核尚未发生是可展示的事实）；
  * 单段查询失败不让整页崩：逐段 try/except，失败段给 reason，其余段照常。

接口：
  get_cluster_pipeline_status(category: str) -> dict     # 聚合（含 segments 六段）
  format_funnel_segments(status: dict) -> list[(str, str)]  # 纯函数，漏斗渲染用
  MISSING_PREFIX                                          # None 段文本前缀（渲染判灰）

降级：数据库不可用/范畴未登记/表未建一律 None 段 + reason，函数不抛异常；
  format_funnel_segments 对缺键/脏值容错（None/非 dict 入参返回 []）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.db_utils import table_exists as _db_table_exists  # R6-4：公共小件单一实现点
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（段序与展示名；与规范 §3 工序编号对应）
# ============================================

# 漏斗段键与渲染顺序（语义分析段工序 4–8 ＋ 编纂成文段占位）
SEGMENT_ORDER: Tuple[str, ...] = (
    "admission",
    "coding",
    "reliability",
    "clustering",
    "split_review",
    "authoring",
)

SEGMENT_LABELS: Dict[str, str] = {
    "admission": "工序4 义位准入",
    "coding": "工序5 特征标注",
    "reliability": "工序6 信度检验",
    "clustering": "工序7 聚类归类",
    "split_review": "工序8 分立复核",
    "authoring": "工序10–13 编纂成文",
}

# None 段渲染文本前缀（dict_admin_pages 据此判灰色「未建/无数据」）
MISSING_PREFIX = "未建/无数据"

# 分立复核的两个状态值（cs_senses.status 为 VARCHAR(8)，默认值是 保留/边缘/剔除/目标；
# merged/split 由分立复核流程写入 —— 当前尚无写入方，如实给 0）
SPLIT_REVIEW_STATUSES: Tuple[str, str] = ("merged", "split")

# 编纂成文段的数据源表（阶段 1 尚未建 —— 探测到存在才尝试计数）
DEFINITION_VERSIONS_TABLE = "definition_versions"

# 各段依赖的业务表（缺表是合法状态：模块未初始化，如实声明而不是抛错）
_SEGMENT_TABLES = {
    "coding": "annotation_submissions",
    "reliability": "reliability_runs",
    "clustering": "cs_cluster_runs",
    "admission": "cs_senses",
    "split_review": "cs_senses",
}


# ============================================
# 逐段降级容器与表探测
# ============================================

def _segment(data: Optional[dict], reason: Optional[str] = None) -> dict:
    """段值构造：data 非 None 时 reason 必为 None（互斥不变量，渲染据此判灰）。"""
    if data is not None:
        return {"data": data, "reason": None}
    return {"data": None, "reason": reason or "暂无数据"}


def _table_exists(table: str) -> bool:
    """当前库中表是否存在（information_schema 只读探测；表名是模块常量）。

    本模块口径是「只传表名、自开游标」（各段逐表探测用），与
    db_utils.table_exists(cursor, table) 的游标入参版签名不同 —— 实现已
    收敛为对后者的薄包装（R6-4：探测逻辑单一实现点），同名入参版保留
    供段内调用点与测试 monkeypatch 零改动。
    """
    with get_db_cursor() as cursor:
        return _db_table_exists(cursor, table)


# ============================================
# 范畴解析（包名 motion ↔ categories.code RUN，口径对齐 cluster_analysis）
# ============================================

def _pack_to_study_map() -> Dict[str, str]:
    """包名 → categories.code 映射（单一事实源 cluster_analysis.PACK_TO_STUDY_CODE）。

    惰性导入：cluster_analysis 顶层引 pandas/streamlit，聚合模块不连带加载；
    导入失败（依赖缺失等）回退到 d1 试点的既定映射（注释口径，非编数）。
    """
    try:
        from src.cluster_analysis import PACK_TO_STUDY_CODE

        return {str(k).lower(): str(v) for k, v in dict(PACK_TO_STUDY_CODE).items()}
    except Exception as e:  # noqa: BLE001 —— 映射缺失按 d1 试点口径兜底
        logger.debug(f"PACK_TO_STUDY_CODE 惰性导入失败，回退既有映射: {e}")
        return {"motion": "RUN"}


def _resolve_category(category: str) -> Tuple[Optional[str], str, Optional[str]]:
    """范畴参数 → (categories.code 研究代号, 标注侧 category 名, 失败原因)。

    先按 categories.code 大小写不敏感直配（兼容 RUN 与 run），再按
    PACK_TO_STUDY_CODE 把包名（motion）映射到研究代号（RUN）；反向
    （传 RUN）同样折算出标注侧包名（motion）。

    Returns:
        (study_code, pack_name, resolve_reason)：解析成功时 reason 为 None；
        cs 侧各段在 study_code=None 时把 reason 填进自己的「未建/无数据」文本，
        标注侧仍按 pack_name（解析不出时为原词小写）继续查自己的表。
    """
    cat = str(category or "").strip()
    if not cat:
        return None, "", "未提供范畴"
    mapping = _pack_to_study_map()
    sql = "SELECT code FROM categories ORDER BY id"
    codes: Dict[str, str] = {}
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql)
            codes = {str(r["code"]).upper(): str(r["code"]) for r in cursor.fetchall()}
    except Exception as e:  # noqa: BLE001 —— categories 缺失/库不可用按未登记降级，不抛
        logger.warning(f"漏斗范畴解析查询 categories 失败（category={cat!r}）: {e}")
        return None, cat.lower(), "categories 表查询失败（库不可用或表未建，详见服务端日志）"
    # 直配：入参本身就是登记过的研究代号（RUN ↔ run）
    if cat.upper() in codes:
        code = codes[cat.upper()]
        pack = next((p for p, c in mapping.items() if c.upper() == code.upper()), None)
        return code, (pack or cat.lower()), None
    # 包名映射：motion → RUN（须确实登记过才认）
    mapped = mapping.get(cat.lower())
    if mapped and mapped.upper() in codes:
        return codes[mapped.upper()], cat.lower(), None
    return (
        None,
        cat.lower(),
        f"categories 无范畴 {cat}（cs 侧数据未灌或范畴未登记，标注侧按 {cat.lower()} 查）",
    )


# ============================================
# 逐段聚合（每段独立降级：data+reason 二元组）
# ============================================

def _segment_admission(study_code: Optional[str], resolve_reason: Optional[str],
                       pack_name: str) -> dict:
    """工序4 义位准入：cs_senses 按 status 分组计数（G1 甄别落地的筛出结果）。

    准入判定 Y/EXT/N 的逐义位明细在 annotation_submissions.payload（工序 5
    编码口径），本段取研究层甄别表的 status 分组 —— 两处口径不同，不混算。
    """
    if study_code is None:
        return _segment(None, resolve_reason)
    sql = (
        "SELECT s.status AS status, COUNT(*) AS n "
        "FROM cs_senses s "
        "JOIN cs_lexemes l ON s.lexeme_id = l.id "
        "JOIN categories c ON l.category_id = c.id "
        "WHERE c.code = %s "
        "GROUP BY s.status"
    )
    try:
        if not _table_exists("cs_senses"):
            return _segment(None, "cs_senses 表未建（范畴深挖 8 表由 mysql_db.init_database 建）")
        with get_db_cursor() as cursor:
            cursor.execute(sql, (study_code,))
            rows = cursor.fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"漏斗准入段查询失败（code={study_code}）: {e}")
        return _segment(None, "准入段查询失败（cs_senses/cs_lexemes/categories，详见服务端日志）")
    if not rows:
        return _segment(None, f"范畴 {study_code} 暂无义位数据（cs_senses 未灌）")
    by_status = {str(r["status"]): int(r["n"] or 0) for r in rows}
    return _segment({"total": sum(by_status.values()), "by_status": by_status})


def _segment_coding(pack_name: str, resolve_reason: Optional[str]) -> dict:
    """工序5 特征标注：annotation_submissions 按 (task_type, status) 计数。"""
    if not pack_name:
        return _segment(None, resolve_reason or "未提供范畴")
    try:
        if not _table_exists("annotation_submissions"):
            return _segment(
                None, "annotation_submissions 表未建（标注流程模块 ensure_flow_tables）"
            )
        sql = (
            "SELECT task_type, status, COUNT(*) AS n "
            "FROM annotation_submissions "
            "WHERE category = %s "
            "GROUP BY task_type, status"
        )
        with get_db_cursor() as cursor:
            cursor.execute(sql, (pack_name,))
            rows = cursor.fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"漏斗特征标注段查询失败（category={pack_name}）: {e}")
        return _segment(None, "特征标注段查询失败（详见服务端日志）")
    if not rows:
        return _segment(None, f"范畴 {pack_name} 暂无标注提交（annotation_submissions）")
    by_task: Dict[str, dict] = {}
    for r in rows:
        task = str(r["task_type"])
        entry = by_task.setdefault(task, {"total": 0, "submitted": 0, "adjudicated": 0})
        n = int(r["n"] or 0)
        entry["total"] += n
        if str(r["status"]) == "submitted":
            entry["submitted"] += n
        elif str(r["status"]) == "adjudicated":
            entry["adjudicated"] += n
    total = sum(e["total"] for e in by_task.values())
    return _segment({"total": total, "by_task": by_task})


def _segment_reliability(pack_name: str, resolve_reason: Optional[str]) -> dict:
    """工序6 信度检验：reliability_runs 最近一次运行的 overall_alpha（G2 线 0.7）。"""
    if not pack_name:
        return _segment(None, resolve_reason or "未提供范畴")
    try:
        if not _table_exists("reliability_runs"):
            return _segment(None, "reliability_runs 表未建（信度模块首次运行时自建）")
        sql = (
            "SELECT id, task_type, n_coders, n_units, overall_alpha, computed_at "
            "FROM reliability_runs "
            "WHERE category = %s "
            "ORDER BY id DESC LIMIT 1"
        )
        with get_db_cursor() as cursor:
            cursor.execute(sql, (pack_name,))
            row = cursor.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"漏斗信度段查询失败（category={pack_name}）: {e}")
        return _segment(None, "信度段查询失败（详见服务端日志）")
    if not row:
        return _segment(None, f"范畴 {pack_name} 暂无信度运行记录（reliability_runs）")
    alpha = row.get("overall_alpha")
    data = {
        "run_id": int(row["id"]),
        "task_type": str(row.get("task_type") or ""),
        "n_coders": int(row.get("n_coders") or 0),
        "n_units": int(row.get("n_units") or 0),
        "overall_alpha": None if alpha is None else float(alpha),
        "computed_at": str(row.get("computed_at") or ""),
    }
    return _segment(data)


def _segment_clustering(study_code: Optional[str], resolve_reason: Optional[str],
                        pack_name: str) -> dict:
    """工序7 聚类归类：cs_cluster_runs 最新版本 + 簇数（最新运行 id 最大为准）。"""
    if study_code is None:
        return _segment(None, resolve_reason)
    try:
        if not _table_exists("cs_cluster_runs"):
            return _segment(None, "cs_cluster_runs 表未建（范畴深挖 8 表由 mysql_db.init_database 建）")
        base = (
            "FROM cs_cluster_runs r "
            "JOIN categories c ON r.category_id = c.id "
            "WHERE c.code = %s"
        )
        latest_sql = (
            "SELECT r.id AS run_id, r.language, r.algorithm, r.version, r.created_at, "
            "(SELECT COUNT(*) FROM cs_clusters cl WHERE cl.run_id = r.id) AS n_clusters "
            + base
            + " ORDER BY r.id DESC LIMIT 1"
        )
        count_sql = f"SELECT COUNT(*) AS n {base}"
        with get_db_cursor() as cursor:
            cursor.execute(latest_sql, (study_code,))
            row = cursor.fetchone()
            cursor.execute(count_sql, (study_code,))
            n_runs = int(cursor.fetchone()["n"] or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"漏斗聚类段查询失败（code={study_code}）: {e}")
        return _segment(None, "聚类段查询失败（cs_cluster_runs/categories，详见服务端日志）")
    if not row:
        return _segment(None, f"范畴 {study_code} 暂无聚类运行记录（cs_cluster_runs）")
    data = {
        "run_id": int(row["run_id"]),
        "study_code": study_code,
        "language": str(row.get("language") or ""),
        "algorithm": str(row.get("algorithm") or ""),
        "version": str(row.get("version") or ""),
        "n_clusters": int(row.get("n_clusters") or 0),
        "n_runs": n_runs,
        "created_at": str(row.get("created_at") or ""),
    }
    return _segment(data)


def _segment_split_review(study_code: Optional[str], resolve_reason: Optional[str],
                          pack_name: str) -> dict:
    """工序8 分立复核：cs_senses status ∈ {merged, split} 计数（G3 前置）。

    范畴已有义位而 merged/split 均为 0 时给真 0（复核尚未发生是事实，不是缺数）；
    范畴连义位都没有才按「暂无」降级。
    """
    if study_code is None:
        return _segment(None, resolve_reason)
    # 占位符顺序：两个 SUM 的 status 参数在前，WHERE 的 code 在后
    # （列别名来自模块常量 SPLIT_REVIEW_STATUSES，非用户输入，无拼接面）
    sum_clauses = ", ".join(
        f"SUM(CASE WHEN s.status = %s THEN 1 ELSE 0 END) AS {status}"
        for status in SPLIT_REVIEW_STATUSES
    )
    sql = (
        "SELECT COUNT(*) AS total, "
        + sum_clauses
        + " FROM cs_senses s "
        "JOIN cs_lexemes l ON s.lexeme_id = l.id "
        "JOIN categories c ON l.category_id = c.id "
        "WHERE c.code = %s"
    )
    params = [*SPLIT_REVIEW_STATUSES, study_code]
    try:
        if not _table_exists("cs_senses"):
            return _segment(None, "cs_senses 表未建（范畴深挖 8 表由 mysql_db.init_database 建）")
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"漏斗分立复核段查询失败（code={study_code}）: {e}")
        return _segment(None, "分立复核段查询失败（cs_senses/cs_lexemes/categories，详见服务端日志）")
    total = int(row["total"] or 0) if row else 0
    if total <= 0:
        return _segment(None, f"范畴 {study_code} 暂无义位数据（cs_senses 未灌）")
    data = {
        "total_senses": total,
        **{status: int(row[status] or 0) for status in SPLIT_REVIEW_STATUSES},
    }
    return _segment(data)


def _segment_authoring() -> dict:
    """工序10–13 编纂成文：definition_versions（阶段 1 未建 → 如实 None 段）。

    表未建是本期的**预期状态**（词条装配/释义版本属后续批次），reason 写明，
    不给假数据；未来表就位后本段自动改为行计数。
    """
    try:
        if not _table_exists(DEFINITION_VERSIONS_TABLE):
            return _segment(
                None,
                f"{DEFINITION_VERSIONS_TABLE} 表未建（释义版本/审校数据源，属后续批次）",
            )
        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS n FROM {DEFINITION_VERSIONS_TABLE}")
            n = int(cursor.fetchone()["n"] or 0)
        return _segment({"n_versions": n})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"漏斗编纂侧段探测失败: {e}")
        return _segment(None, f"编纂侧探测失败（{DEFINITION_VERSIONS_TABLE}，详见服务端日志）")


# ============================================
# 对外接口 1：聚合
# ============================================

def get_cluster_pipeline_status(category: str) -> dict:
    """聚合十五道工序漏斗的语义分析段（工序 4–8）＋编纂成文段占位。

    Args:
        category: 范畴名。包名（motion）或研究代号（RUN）均可 —— 经
            categories.code 直配 / PACK_TO_STUDY_CODE 映射折算；标注侧
            （annotation_submissions/reliability_runs）按折算出的包名查，
            cs 侧（cs_senses/cs_cluster_runs）按研究代号查。

    Returns:
        dict::

            {
              "category": <规整后的入参>,
              "study_code": "RUN"|None,   # cs 侧解析结果（None=categories 无此范畴）
              "pack_name": "motion",      # 标注侧查询名（入参为 RUN 时折算）
              "segments": {
                "<segment>": {"data": dict|None, "reason": str|None},  # 六段
              },
            }

        每段 data 与 reason 互斥：data 非 None 时 reason 为 None；缺数段
        data 为 None 且 reason 一句话说明（表未建/无范畴/暂无数据/库不可用）。
        本函数不抛异常：任何单段失败都折成该段的 reason。
    """
    cat = str(category or "").strip()
    study_code, pack_name, resolve_reason = _resolve_category(cat)

    segments = {
        "admission": _segment_admission(study_code, resolve_reason, pack_name),
        "coding": _segment_coding(pack_name, resolve_reason),
        "reliability": _segment_reliability(pack_name, resolve_reason),
        "clustering": _segment_clustering(study_code, resolve_reason, pack_name),
        "split_review": _segment_split_review(study_code, resolve_reason, pack_name),
        "authoring": _segment_authoring(),
    }
    return {
        "category": cat,
        "study_code": study_code,
        "pack_name": pack_name,
        "segments": segments,
    }


# ============================================
# 对外接口 2：漏斗文本（纯函数，dict_admin_pages 渲染用）
# ============================================

def _fmt_alpha(alpha: Any) -> str:
    """overall_alpha 展示：None →「—」（没跑出 α ≠ 0），数值 → 三位小数。"""
    try:
        return f"{float(alpha):.3f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_counts(by_what: Dict[str, Any], fmt_item) -> str:
    """分组计数 → 「k v · k v」串（按计数降序、同数按键名升序，确定性渲染）。"""
    def _sort_key(item):
        """排序键：计数降序、同数按键名升序（脏计数按 -1 兜底，不抛）。"""
        key, value = item
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = -1
        return (-n, str(key))

    return " · ".join(fmt_item(k, v) for k, v in sorted(by_what.items(), key=_sort_key))


def _format_admission(data: dict) -> str:
    """工序4 段文本：义位总数＋按甄别状态分组的明细（降序渲染）。"""
    total = data.get("total")
    by_status = data.get("by_status") or {}
    detail = _fmt_counts(by_status, lambda k, v: f"{k} {v}")
    return f"义位 {total}：{detail}" if detail else f"义位 {total}"


def _format_coding(data: dict) -> str:
    """工序5 段文本：提交总数＋按任务类型分组（含 submitted/adjudicated 细分）。"""
    total = data.get("total")
    by_task = data.get("by_task") or {}
    detail = _fmt_counts(
        by_task,
        lambda k, v: (
            f"{k} {v.get('total', 0)}"
            f"（submitted {v.get('submitted', 0)} · adjudicated {v.get('adjudicated', 0)}）"
        ),
    )
    return f"提交 {total}：{detail}" if detail else f"提交 {total}"


def _format_reliability(data: dict) -> str:
    """工序6 段文本：最近一次信度运行（α／编码人数／单元数／计算时间）。"""
    alpha = _fmt_alpha(data.get("overall_alpha"))
    parts = [
        f"最近运行（{data.get('task_type') or '—'}）α={alpha}",
        f"编码人 {data.get('n_coders', 0)}",
        f"单元 {data.get('n_units', 0)}",
    ]
    computed = data.get("computed_at")
    if computed:
        parts.append(str(computed))
    return " · ".join(parts)


def _format_clustering(data: dict) -> str:
    """工序7 段文本：最新聚类运行的版本与簇数（附算法与累计运行次数）。"""
    return (
        f"{data.get('study_code') or '—'}·{data.get('language') or '—'}"
        f" 最新「{data.get('version') or '—'}」：{data.get('n_clusters', 0)} 簇"
        f"（{data.get('algorithm') or '—'}；共 {data.get('n_runs', 0)} 次运行）"
    )


def _format_split_review(data: dict) -> str:
    """工序8 段文本：merged/split 计数＋义位总数（G3 清单锁定口径）。"""
    merged = data.get("merged", 0)
    split = data.get("split", 0)
    return f"merged {merged} · split {split}（义位 {data.get('total_senses', 0)}）"


def _format_authoring(data: dict) -> str:
    """工序10–13 段文本：definition_versions 版本行计数。"""
    return f"definition_versions {data.get('n_versions', 0)} 条"


# 各段文本格式化器（与 SEGMENT_ORDER 键一一对应；新增段必须同时给格式化器）
_SEGMENT_FORMATTERS = {
    "admission": _format_admission,
    "coding": _format_coding,
    "reliability": _format_reliability,
    "clustering": _format_clustering,
    "split_review": _format_split_review,
    "authoring": _format_authoring,
}


def format_funnel_segments(status: Any) -> List[Tuple[str, str]]:
    """聚合结果 → 漏斗渲染行 ``[(段名, 文本), ...]``（纯函数，不碰 st./DB）。

    * 按 SEGMENT_ORDER 输出六段；status 缺段/多段/键漂移时跳过未知键，不抛；
    * 有数段文本为该段真实计数串；缺数段（data=None）文本以 MISSING_PREFIX
      开头并附 reason —— 渲染层据此把该行画灰；
    * 入参 None/非 dict/segments 非 dict → []（空漏斗，页面给占位提示）。
    """
    if not isinstance(status, dict):
        return []
    segments = status.get("segments")
    if not isinstance(segments, dict):
        return []
    rows: List[Tuple[str, str]] = []
    for key in SEGMENT_ORDER:
        segment = segments.get(key)
        if not isinstance(segment, dict):
            continue  # 键漂移/缺段：跳过而不是编一个「0」
        label = SEGMENT_LABELS.get(key, key)
        data = segment.get("data")
        if data is None:
            reason = segment.get("reason") or "暂无数据"
            rows.append((label, f"{MISSING_PREFIX}：{reason}"))
        else:
            formatter = _SEGMENT_FORMATTERS.get(key)
            if formatter is None:  # pragma: no cover —— 新段漏配格式化器的防御
                rows.append((label, str(data)))
                continue
            try:
                rows.append((label, formatter(data)))
            except Exception as e:  # noqa: BLE001 —— 脏数据不让渲染崩
                logger.warning(f"漏斗段 {key} 文本格式化失败: {e}")
                rows.append((label, f"{MISSING_PREFIX}：段数据格式异常（{e}）"))
    return rows
