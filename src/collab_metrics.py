"""协同度量五指标数据层（FX-19）—— 规范 §5「度量」清单的缺失指标集中实现。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§5 度量条目（L126-127）：
「采纳率、AI-人一致率 vs 人-人 α、标注节省量、替换测试通过率、打回率、
体例质检通过率」。批次 2 协同度量页此前只有采纳率（ai_ledger.get_stats，
保持不动）；本模块补齐其余五指标的**数据源勘察结论、计算口径与降级纪律**
（宁缺毋假：有数据源的算真值，没有的如实灰注，绝不编数字）。

五指标数据源勘察表（FX-19，2024-11 勘察；页面卡片与本文档口径一致）：

  ================  ===========================  ==========  ==============================
  指标              数据源                        可算/灰注   口径一句话
  ================  ===========================  ==========  ==============================
  AI-人一致率       ai_proposals(kind='draft')   可算*       完全一致(adopted)÷已裁决草稿提案
                    已裁决提案 vs 人工裁决                    （modified=部分一致不入分子）
  标注节省量        ai_proposals(kind='draft')   可算（估算）(采纳+修改后采纳)×3.0 分钟/条
                    adopted+modified 计数                     （工程估算，非实测，页面带徽章）
  打回率            writing_db.review_tasks      可算        (打回修订+直接否决)÷已出结论审校轮
                    .verdict（按审校轮次）                    （verdict≠pending 的轮次）
  替换测试通过率    configs/style.yaml           灰注        配置就绪、无执行结果数据源 →
                    substitution_test（配置）                 占位不编数字
  体例质检通过率    style_check_runs（FX-25）    可算**/灰注  最近 1 次 run：passed÷(passed+
                    无 run 记录 → 灰注                        failed)，warn 单列不入分母
  ================  ===========================  ==========  ==============================

  * AI-人一致率的「可算」是**台账三值裁决口径**的退路实现：annotation_submissions
    只存 ai_assisted 布尔标志（DDL 注释「全员看同样 AI 草稿（用户决策③）」），
    **不落 AI 草稿内容快照**，逐特征比对不可行；adjudications.gold_payload 是
    人工定稿而非 AI 草稿，同样比对不了。故按勘测指令退而用 ai_proposals 的
    draft 提案与其后人工裁决对照（完全一致=adopted / 部分一致=modified /
    不一致=rejected）。局限：台账只存三值裁决，该口径数值上等同 draft 通道
    「严格采纳率」（采纳率分子计入 modified，本指标不计，二者有别）；待
    annotation_submissions 留存 AI 草稿快照后应升级为逐特征一致率。

  ** 体例质检通过率的「可算」自 FX-25 起：数据源 style_check_runs（引擎
    src/style_check.run_style_check 落库，通过率公式与 warn 口径单一事实源
    见其模块 docstring）。取**最近 1 次 run** 而非最近 5 次聚合 —— 体例以
    style.yaml 现行版本为准，历史 run 属旧版本配置下的结果，跨版本聚合
    分子分母不可比；list_recent_runs(limit=5) 供历史清单展示。无 run 记录
    /数据库不可用仍灰注（宁缺毋假）。

模块纪律（同 ai_ledger / collab_pages 口径）：
  1. SQL 一律参数化（本模块查询文本全是常量，无一处值拼接）；对 writing_db
     只读（自建 SELECT，不改其表结构与数据）；
  2. 分子/分母在纯函数里算（*_from_counts 三件），tests/test_fx19_fixes.py
     用夹具数据断言分子分母；DB 查询函数只负责取数喂给纯函数；
  3. 降级：数据库不可用/表未建时查询函数返回 available=False ＋ reason 文案
     （不抛异常），页面整卡灰注 —— 是「不可用」，不是「0%」；
  4. 每个指标 docstring 注明计算口径与分母/分子定义（本文件即口径单一事实源，
     页面 tooltip/caption 引用同文案）。
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.mysql_db import get_db_cursor
from src.style_check import list_recent_runs, pass_rate_from_counts

logger = logging.getLogger(__name__)

# ============================================
# 常量（口径单一事实源；页面 tooltip 直接引用）
# ============================================

# AI-人一致率 · 数据源与局限说明（页面 caption/tooltip 引用）
AGREEMENT_NOTE = (
    "口径：完全一致（adopted）÷ 已裁决草稿提案（adopted+rejected+modified，pending 不计）；"
    "修改后采纳（modified）= 部分一致，保守口径不入分子。数据源：ai_proposals kind='draft'"
    "（annotation_submissions 不落 AI 草稿快照，逐特征比对暂不可行）；局限：台账仅三值裁决，"
    "数值上接近 draft 通道严格采纳率 —— 待提交表留存 AI 草稿快照后升级为逐特征一致率。"
)

# 标注节省量 · 单条平均耗时假设（**工程估算**，非实测：出处类型＝工程估算）。
# 假设 AI 草稿底稿平均为标注员节省约 3 分钟/条（含阅读草稿＋校对改写相对从零
# 编码的净节省；修改后采纳的场景按全额计，常数已偏向保守）。无实测工时数据
# 支撑，页面必须带「估算」徽章，不得看起来像实测值。
SAVED_MINUTES_PER_ITEM = 3.0
SAVINGS_NOTE = (
    "口径：（原样采纳＋修改后采纳的草稿提案数）× 3.0 分钟/条 —— 假设值为工程估算"
    "（非实测，无工时数据支撑）；数据源：ai_proposals kind='draft' 的 adopted/modified 计数。"
)

# 打回率 · 口径说明（页面 caption/tooltip 引用）
REJECTION_NOTE = (
    "口径：（revision_requested 打回修订＋rejected 直接否决）÷ 已出审校结论的审校任务轮"
    "（verdict≠pending，按轮次计：打回重提产生新轮）。数据源：writing_db.review_tasks"
    "（只读）；标注侧质检打回暂无数据源（ai_proposals audit 通道尚无业务写入，批次 8 接入）。"
)

# 替换测试通过率 · 灰注文案（配置就绪、无执行结果数据源 —— 宁缺毋假，不编数字）
SUBSTITUTION_NOTE = (
    "尚未接入替换测试数据（配置已就绪：configs/style.yaml substitution_test ——"
    " method/sample_size/pass_threshold 待编者核定；全库无替换测试执行结果表），"
    "指标位占位，不编数字。"
)

# 体例质检通过率 · 灰注文案（style_check_runs 无 run 记录 —— 宁缺毋假，不编数字；
# FX-25 起数据源已接入，引擎 src/style_check.run_style_check 落库，本卡有 run 即转真值）
STYLE_CHECK_NOTE = (
    "尚未接入体例质检执行数据（style_check_runs 尚无该范畴 run 记录；质检引擎"
    " src/style_check.run_style_check 已就绪）—— 运行一次后本卡转真值，"
    "当前占位不编数字。"
)

# 体例质检通过率 · 真值口径（页面 caption/tooltip 引用；口径单一事实源
# style_check 模块 docstring，此处同文案）
STYLE_CHECK_RATE_NOTE = (
    "口径：最近 1 次体例质检 run 的通过项 ÷（通过项＋失败项）—— warn 单列"
    "（自动化比对未覆盖/暂无数据可检类观察项），不计入分子也不计入分母；"
    "数据源 style_check_runs（引擎 src/style_check.run_style_check 落库，"
    "FX-25）。取最近 1 次而非多次聚合：体例以 style.yaml 现行版本为准，"
    "历史 run 属旧版本配置，跨版本聚合分子分母不可比。"
)

# 降级通用文案（数据库不可用/表未建 —— 是「不可用」不是「0」）
DB_UNAVAILABLE_NOTE = "数据库不可用或表未初始化，本指标暂无法统计（灰注降级，非 0）。"

# configs/style.yaml 位置（仓库根；substitution_test / ai_audit 配置探测）
_STYLE_YAML_PATH = Path(__file__).resolve().parent.parent / "configs" / "style.yaml"


# ============================================
# 计数规整（纯函数内部兜底：脏数据按 0，不抛异常）
# ============================================
def _count(value: Any) -> int:
    """宽松计数规整：bool/None/非数值/负数一律按 0（计数不会为负）。"""
    if value is None or isinstance(value, bool):
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _rate4(numerator: int, denominator: int) -> Optional[float]:
    """比率（4 位小数）；分母 0 → None（「还没数据」≠「0%」，ai_ledger 同口径）。"""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


# ============================================
# 指标 1 · AI-人一致率（台账三值裁决口径）
# ============================================
def agreement_rate_from_counts(
    adopted: Any, rejected: Any, modified: Any
) -> Dict[str, Any]:
    """AI-人一致率纯函数（分子/分母在这里算，测试直接断言）。

    口径（模块 docstring 勘察表同源）：
      * 分母 decided = adopted + rejected + modified（**已裁决**草稿提案；
        pending 不计 —— 与 ai_ledger.get_stats 采纳率分母同口径）；
      * 分子 = adopted（人工原样采纳 = AI 草稿与人工最终结果完全一致）；
      * modified = 部分一致（人改过 AI 候选后采纳），保守口径**不入分子**
        （宁缺毋滥）；rejected = 不一致；
      * decided = 0 → agreement_rate = None（还没数据 ≠ 0%）。

    Args:
        adopted: 完全一致计数（ai_proposals kind='draft' AND status='adopted'）
        rejected: 不一致计数（同上 status='rejected'）
        modified: 部分一致计数（同上 status='modified'）

    Returns:
        dict: {adopted, rejected, modified, decided, agreement_rate,
        partial_agreement}；计数 int，比率 float（4 位小数）或 None。
    """
    a, r, m = _count(adopted), _count(rejected), _count(modified)
    decided = a + r + m
    return {
        "adopted": a,
        "rejected": r,
        "modified": m,
        "decided": decided,
        "agreement_rate": _rate4(a, decided),
        "partial_agreement": m,
    }


def _fetch_draft_decision_counts() -> Optional[Dict[str, int]]:
    """取 ai_proposals kind='draft' 的已裁决三值计数（本模块参数化只读查询）。

    Returns:
        dict | None: {adopted, rejected, modified}；数据库不可用/表未建返回
        None（查询函数据此降级 available=False）。
    """
    sql = (
        "SELECT COALESCE(SUM(status = 'adopted'), 0) AS adopted, "
        "COALESCE(SUM(status = 'rejected'), 0) AS rejected, "
        "COALESCE(SUM(status = 'modified'), 0) AS modified "
        "FROM ai_proposals WHERE kind = 'draft' AND status <> 'pending'"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()
    except Exception as e:  # noqa: BLE001 —— 表未建/库断连统一降级（pymysql.Error 含在内）
        logger.error(f"统计 draft 提案裁决计数失败（AI-人一致率降级）: {e}")
        return None
    if not row:
        return {"adopted": 0, "rejected": 0, "modified": 0}
    return {
        "adopted": _count(row.get("adopted")),
        "rejected": _count(row.get("rejected")),
        "modified": _count(row.get("modified")),
    }


def ai_human_agreement_rate() -> Dict[str, Any]:
    """AI-人一致率（指标 1；台账三值裁决口径，见 AGREEMENT_NOTE）。

    Returns:
        dict: {available, adopted, rejected, modified, decided,
        agreement_rate, partial_agreement, note}。available=False 表示数据库
        不可用（计数 0、rate None、note 换降级文案）；available=True 且
        agreement_rate=None 表示尚无已裁决草稿提案（「还没数据」≠ 0%）。
    """
    counts = _fetch_draft_decision_counts()
    if counts is None:
        result = agreement_rate_from_counts(0, 0, 0)
        result.update({"available": False, "note": DB_UNAVAILABLE_NOTE})
        return result
    result = agreement_rate_from_counts(
        counts["adopted"], counts["rejected"], counts["modified"]
    )
    result.update({"available": True, "note": AGREEMENT_NOTE})
    return result


# ============================================
# 指标 2 · 标注节省量（估算，页面必须带「估算」徽章）
# ============================================
def savings_estimate_from_counts(
    adopted: Any,
    modified: Any,
    minutes_per_item: float = SAVED_MINUTES_PER_ITEM,
    include_modified: bool = True,
) -> Dict[str, Any]:
    """标注节省量纯函数（估算口径在分子这里算，测试直接断言）。

    口径：节省分钟 = (adopted [+ modified]) × minutes_per_item。
      * adopted（原样采纳）全额计入；modified（修改后采纳）默认也计入
        —— AI 草稿仍是底稿，节省已部分发生（include_modified=False 可切换
        为只算原样采纳的保守口径）；
      * minutes_per_item 默认 SAVED_MINUTES_PER_ITEM = 3.0 分钟/条，
        **工程估算**（出处类型：工程估算，非实测，无工时数据支撑）；
      * 本指标永远是估算值 —— 调用方（页面）必须带「估算」徽章展示。

    Args:
        adopted: 原样采纳条数
        modified: 修改后采纳条数
        minutes_per_item: 单条节省分钟假设（工程估算常数）
        include_modified: 修改后采纳是否计入（默认 True）

    Returns:
        dict: {base_count, minutes_saved, hours_saved, minutes_per_item,
        estimated}；estimated 恒为 True（估算口径标记，页面徽章依据）。
    """
    base = _count(adopted) + (_count(modified) if include_modified else 0)
    minutes = round(base * float(minutes_per_item), 1)
    return {
        "base_count": base,
        "minutes_saved": minutes,
        "hours_saved": round(minutes / 60.0, 2),
        "minutes_per_item": float(minutes_per_item),
        "estimated": True,
    }


def annotation_savings() -> Dict[str, Any]:
    """标注节省量（指标 2；估算口径，见 SAVINGS_NOTE；页面带「估算」徽章）。

    Returns:
        dict: {available, base_count, minutes_saved, hours_saved,
        minutes_per_item, estimated, note}。available=False 表示数据库不可用
        （计数 0、节省 0、note 换降级文案）；estimated 恒为 True。
    """
    counts = _fetch_draft_decision_counts()
    if counts is None:
        result = savings_estimate_from_counts(0, 0)
        result.update({"available": False, "note": DB_UNAVAILABLE_NOTE})
        return result
    result = savings_estimate_from_counts(counts["adopted"], counts["modified"])
    result.update({"available": True, "note": SAVINGS_NOTE})
    return result


# ============================================
# 指标 3 · 打回率（writing 侧审校轮次口径）
# ============================================
def rejection_rate_from_counts(
    approved: Any, revision_requested: Any, rejected: Any
) -> Dict[str, Any]:
    """打回率纯函数（分子/分母在这里算，测试直接断言）。

    口径（REJECTION_NOTE 同源）：
      * 分母 decided = approved + revision_requested + rejected
        （**已出审校结论**的审校任务轮；verdict='pending' 不计 —— 调用方
        fetch 层已按 verdict≠pending 取数，本函数收到的就是三值计数）；
      * 分子 = revision_requested（打回修订）+ rejected（直接否决）；
      * decided = 0 → rejection_rate = None（还没有审校轮 ≠ 0%）。

    Args:
        approved: 审校通过轮数（verdict='approved'）
        revision_requested: 打回修订轮数（verdict='revision_requested'）
        rejected: 直接否决轮数（verdict='rejected'）

    Returns:
        dict: {approved, revision_requested, rejected, decided,
        rejection_rate}；计数 int，比率 float（4 位小数）或 None。
    """
    a, rv, rj = _count(approved), _count(revision_requested), _count(rejected)
    decided = a + rv + rj
    return {
        "approved": a,
        "revision_requested": rv,
        "rejected": rj,
        "decided": decided,
        "rejection_rate": _rate4(rv + rj, decided),
    }


def _fetch_review_task_verdicts() -> Optional[Dict[str, int]]:
    """取 review_tasks 的 verdict 三值计数（只读自建 SQL，不改 writing_db）。

    review_tasks 由 writing_db.ensure_writing_tables 建（无外键，表可独立
    存在）；表未建/库不可用返回 None（降级灰注）。
    """
    sql = (
        "SELECT COALESCE(SUM(verdict = 'approved'), 0) AS approved, "
        "COALESCE(SUM(verdict = 'revision_requested'), 0) AS revision_requested, "
        "COALESCE(SUM(verdict = 'rejected'), 0) AS rejected "
        "FROM review_tasks WHERE verdict <> 'pending'"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()
    except Exception as e:  # noqa: BLE001 —— 表未建/库断连统一降级（pymysql.Error 含在内）
        logger.error(f"统计审校轮次 verdict 计数失败（打回率降级）: {e}")
        return None
    if not row:
        return {"approved": 0, "revision_requested": 0, "rejected": 0}
    return {
        "approved": _count(row.get("approved")),
        "revision_requested": _count(row.get("revision_requested")),
        "rejected": _count(row.get("rejected")),
    }


def writing_rejection_rate() -> Dict[str, Any]:
    """打回率（指标 3；writing 侧审校轮次口径，见 REJECTION_NOTE）。

    Returns:
        dict: {available, approved, revision_requested, rejected, decided,
        rejection_rate, note}。available=False 表示数据库不可用/表未建
        （计数 0、rate None、note 换降级文案）；available=True 且
        rejection_rate=None 表示尚无已出结论的审校轮。
    """
    counts = _fetch_review_task_verdicts()
    if counts is None:
        result = rejection_rate_from_counts(0, 0, 0)
        result.update({"available": False, "note": DB_UNAVAILABLE_NOTE})
        return result
    result = rejection_rate_from_counts(
        counts["approved"], counts["revision_requested"], counts["rejected"]
    )
    result.update({"available": True, "note": REJECTION_NOTE})
    return result


# ============================================
# 指标 4/5 · 替换测试通过率 / 体例质检通过率（灰注占位，宁缺毋假）
# ============================================
def _style_yaml_config(key: str) -> bool:
    """configs/style.yaml 是否配置了指定键（只读探测；探测失败按未配置）。

    yaml 解析失败时退化为文本扫描（键行前缀匹配），保证灰注文案里的
    「配置已就绪」判断在脏 YAML 下也不会误报。
    """
    try:
        text = _STYLE_YAML_PATH.read_text(encoding="utf-8")
    except OSError as e:
        logger.error(f"读取 configs/style.yaml 失败（按未配置处理）: {e}")
        return False
    try:
        import yaml  # category_pack 同款运行时 import

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return key in data
    except Exception as e:  # noqa: BLE001 —— 解析失败走文本扫描兜底
        logger.warning(f"configs/style.yaml 解析失败（退化文本扫描）: {e}")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            return True
    return False


def substitution_test_status() -> Dict[str, Any]:
    """替换测试通过率（指标 4）—— **无执行结果数据源，灰注占位不编数字**。

    勘察结论（FX-19）：configs/style.yaml 的 substitution_test 配置就绪
    （method/sample_size/pass_threshold 待编者核定），但全库 grep 无替换测试
    执行结果表/写入（ai_proposals audit 通道无业务写入；writing_pages 的
    替换性测试仅为撰写口径提示）。按「宁缺毋假」纪律返回 available=False
    ＋ reason 文案，pass_rate 恒 None。

    Returns:
        dict: {available(恒 False), configured, pass_rate(恒 None), reason,
        note}。configured=True 时 reason 为「配置已就绪」灰注文案。
    """
    configured = _style_yaml_config("substitution_test")
    reason = SUBSTITUTION_NOTE if configured else (
        "尚未接入替换测试数据（configs/style.yaml 未检出 substitution_test 配置）；"
        "指标位占位，不编数字。"
    )
    return {
        "available": False,
        "configured": configured,
        "pass_rate": None,
        "reason": reason,
        "note": reason,
    }


def style_check_pass_rate_from_counts(passed: Any, failed: Any) -> Optional[float]:
    """体例质检通过率纯函数（指标 5 分子/分母在这里算，测试直接断言）。

    口径（style_check 模块 docstring 同源，委托其单一实现）：
    passed/(passed+failed)；warn 单列，不入分子也不入分母；分母 0 → None
    （「还没有可比项」≠ 0%）。
    """
    return pass_rate_from_counts(passed, failed)


def style_check_status(category: Optional[str] = None) -> Dict[str, Any]:
    """体例质检通过率（指标 5；FX-25 接真数据源，口径见 STYLE_CHECK_RATE_NOTE）。

    口径选择（模块 docstring 勘察表 ** 注同源）：取**最近 1 次 run** ——
    体例以 style.yaml 现行版本为准，历史 run 属旧版本配置，跨版本聚合
    分子分母不可比。三态：
      * 数据库不可用/表未建 → available=False ＋ DB_UNAVAILABLE_NOTE（灰注）；
      * 无 run 记录 → available=False ＋ STYLE_CHECK_NOTE（灰注，不编数字）；
      * 有 run → available=True，pass_rate=passed/(passed+failed)
        （warn 单列不入分母），附 run_id/范畴/三态计数。

    Args:
        category: 范畴名；None → 跨范畴取最近 1 次（协同度量页无范畴
            上下文），给定 → 该范畴最近 1 次。

    Returns:
        dict: {available, configured, pass_rate, run_id, run_category,
        passed, failed, warned, total, reason, note}。
    """
    configured = _style_yaml_config("style_version")
    rows = list_recent_runs(category, limit=1)
    if rows is None:
        return {
            "available": False,
            "configured": configured,
            "pass_rate": None, "run_id": None, "run_category": None,
            "passed": 0, "failed": 0, "warned": 0, "total": 0,
            "reason": DB_UNAVAILABLE_NOTE,
            "note": DB_UNAVAILABLE_NOTE,
        }
    if not rows:
        return {
            "available": False,
            "configured": configured,
            "pass_rate": None, "run_id": None, "run_category": None,
            "passed": 0, "failed": 0, "warned": 0, "total": 0,
            "reason": STYLE_CHECK_NOTE,
            "note": STYLE_CHECK_NOTE,
        }
    run = rows[0]
    passed = _count(run.get("passed"))
    failed = _count(run.get("failed"))
    warned = _count(run.get("warned"))
    return {
        "available": True,
        "configured": configured,
        "pass_rate": style_check_pass_rate_from_counts(passed, failed),
        "run_id": run.get("id"),
        "run_category": run.get("category"),
        "passed": passed, "failed": failed, "warned": warned,
        "total": _count(run.get("total")),
        "reason": STYLE_CHECK_RATE_NOTE,
        "note": STYLE_CHECK_RATE_NOTE,
    }
