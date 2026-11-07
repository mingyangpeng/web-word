"""AI 协作台账数据层 —— 三通道 AI 提议的留痕与裁决（Agent D）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§5（A 协作智能层）与
§6 D⑤ 协作留痕域（ai_proposals 是三版本脊柱之外的第 4 条留痕线）；
契约：docs/spec/阶段1施工规范.md §3-D（本文件签名与之一致，不得擅改）。

是什么（ai_proposals 一张表）：
  登记 AI 在每道工序（stage）对每个工作单元（unit_ref）产出的三类提议：

    * draft（草稿，AI→人）：准入/特征/图式草稿、主动学习排序、义项合拆提议、
      模板批量生成、配图/视频推荐、枚举属性预填、导入异常检测、分派建议等；
    * audit（质检，AI→人）：第三标注员预演预警、簇画像冲突报警、替换性测试、
      体例/句式/定义词表检查、文图一致性、许可终检等；
    * probe（探针，人↔AI）：库内受控问答附证据链，无据明说「无据」。

数据链（平台架构设计规范 §5，资源注入协议）：
  提示词＝①配置规则（C）＋②库内证据（D）＋③任务指令（prompts/）→ AI 输出
  分层标注来源（依据配置规则 X／库内证据 Y／模型推断 Z）→ record_proposal
  登记（提示词版本 prompt_version ＋ 资源快照版本 resource_version ＋ 不确定度
  uncertainty ＋ 证据引用 evidence_ref）→ 人裁决 decide（采纳/否决/修改＋理由）
  → get_stats 供协同度量页（采纳率、平均不确定度 → 论文表格）。

  * AI 永不直写 D（义位权威库）：本表只存候选与证据；采纳后的实际落地由
    页面层调用对应数据模块完成，ai_proposals 仅作留痕；
  * 不确定度＝综合信号（规则层未命中特征数＋历史人-机分歧率＋预演分歧标记），
    **禁用 LLM 自报置信度** —— 本层只存 [0,1] 数值，不关心来源公式；
  * probe 通常不入裁决流：照常以 status='pending' 入账（不设特殊状态），
    也可裁决；批次 2 协作收件箱按通道取数（见 list_pending docstring）。

接口（契约 §3-D）：
  ensure_ai_ledger_tables / record_proposal / decide / list_pending / get_stats
  另有只读辅助 get_proposal（非契约签名，供批次 2 单条详情/防重复裁决提示）。

降级：
  数据库不可用时 record_proposal 返回 0、decide 返回 False、list_pending 返回
  []、get_stats 返回全 0 口径 dict（adoption_rate/avg_uncertainty 为 None），
  均只记日志不抛异常 —— 页面可继续渲染「AI 暂不可用」而不是整页崩掉。

安全规则（同 annotation_flow.py 口径）：
  1. SQL 一律参数化，本文件无一处把值拼进 SQL 文本（WHERE/ORDER 拼接只来自
     本模块白名单常量，值全走占位符）；
  2. 入参在应用层先校验再入库：非法 kind/decision/proposal/不确定度根本不进
     数据库（不依赖 ENUM/JSON 报错）；
  3. 权限检查（谁能裁决）由页面层 role gate 负责，数据层不重复实现。
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（平台架构设计规范 §5 三通道 / 阶段1施工规范 §3-D）
# ============================================
# kind：三通道（草稿/质检/探针）。入口校验用，非法值不进数据库。
KIND_DRAFT = "draft"    # 草稿（AI→人）
KIND_AUDIT = "audit"    # 质检（AI→人）
KIND_PROBE = "probe"    # 探针（人↔AI，库内受控问答）
KINDS = (KIND_DRAFT, KIND_AUDIT, KIND_PROBE)

# decision：裁决三值（decide 入参）。pending 是裁决前的初始状态。
DECISION_ADOPTED = "adopted"    # 采纳（原样落地）
DECISION_REJECTED = "rejected"  # 否决
DECISION_MODIFIED = "modified"  # 修改后采纳（人改过 AI 的候选）
DECISIONS = (DECISION_ADOPTED, DECISION_REJECTED, DECISION_MODIFIED)

# status：提案全生命周期。probe 不设特殊状态（见模块 docstring）。
STATUS_PENDING = "pending"
PROPOSAL_STATUSES = (STATUS_PENDING,) + DECISIONS

# uncertainty 取值域（综合信号归一化到 [0,1]；禁 LLM 自报置信度，见模块 docstring）
MIN_UNCERTAINTY = 0.0
MAX_UNCERTAINTY = 1.0

# list_pending 单次返回上限（收件箱分页足够；防一次性拖全表）
MAX_LIST_LIMIT = 500

# 建表 DDL（契约 §3-D 表设计原样；幂等，CREATE TABLE IF NOT EXISTS）。
# 不加 users 外键（decider_id/created_by 允许系统登记为 NULL，且本表建表
# 不依赖 users 表存在 —— ensure 可独立先行）。
AI_PROPOSALS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS ai_proposals (
  id INT AUTO_INCREMENT PRIMARY KEY,
  kind ENUM('draft','audit','probe') NOT NULL DEFAULT 'draft',  -- 三通道：草稿/质检/探针
  stage VARCHAR(40) NOT NULL DEFAULT '',       -- 工序名（编纂工序链，如 admission）
  unit_ref VARCHAR(120) NOT NULL DEFAULT '',   -- 工作单元引用（如 oald_senses:123 / cluster:45）
  proposal JSON NOT NULL,                      -- 提议内容（结构随 kind/stage 而定）
  evidence_ref VARCHAR(255) NULL,              -- 证据链引用（库内证据出处；无据为 NULL）
  prompt_version VARCHAR(40) NULL,             -- 提示词版本（资源注入协议留痕）
  resource_version VARCHAR(40) NULL,           -- 资源快照版本（资源注入协议留痕）
  uncertainty DECIMAL(5,4) NULL,               -- 不确定度 [0,1]（综合信号，非 LLM 自报）
  status ENUM('pending','adopted','rejected','modified') NOT NULL DEFAULT 'pending',
  decision_reason TEXT NULL,                   -- 裁决理由（人写，采纳/否决留痕）
  decider_id INT NULL,                         -- 裁决人 users.id
  decided_at DATETIME NULL,
  created_by INT NULL,                         -- 登记人 users.id（系统自动登记为 NULL）
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_pending (status, kind, stage, uncertainty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 建表
# ============================================
def ensure_ai_ledger_tables() -> None:
    """幂等创建 ai_proposals 表（契约 §3-D 表设计原样，可重复调用）。

    无外键依赖（decider_id/created_by 为软引用），可独立于其他模块先行建表；
    被数据库拒绝（无权限等）只记 error 日志不抛异常，页面可继续渲染。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(AI_PROPOSALS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"ai_proposals 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"ai_proposals 表初始化意外错误: {e}")


# ============================================
# 入参规整（应用层先拒，非法值不进数据库）
# ============================================
_INVALID = object()  # 字符串校验失败的哨兵（None 是合法值，不能复用）


def _as_int(value: Any) -> Optional[int]:
    """宽松转 int（int/float/int-str 可转；bool/None/其余 None）—— 防脏参数。

    float NaN/Inf 也拒：int(nan) 抛 ValueError，正好落进 except。
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_optional_str(value: Any, max_len: int) -> Any:
    """可选字符串规整：None/纯空白 → None；去首尾空白；超长 → _INVALID。

    Returns:
        None（空）| str（去空白后）| _INVALID（类型不对或超长，调用方拒绝）
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        return _INVALID
    return cleaned


def _dump_proposal(proposal: Any) -> Optional[str]:
    """proposal → JSON 串；非法返回 None。

    只有 dict/list 是「提议内容」（JSON 容器）；标量不是提议。NaN/Inf 拒 ——
    json.dumps 默认会产出非法 JSON 字面量（NaN），MySQL JSON 列必炸，与其
    等报错不如入口先拒（与 annotation_flow 同口径）。
    """
    if not isinstance(proposal, (dict, list)):
        return None
    try:
        return json.dumps(proposal, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return None


def _parse_proposal_payload(raw: Any) -> Any:
    """JSON 列 proposal → dict/list（PyMySQL 对 JSON 列可能给 str 或 dict）。

    解析失败/非容器返回 {}（坏数据按缺失处理，不打崩收件箱渲染）。
    """
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, (dict, list)) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_uncertainty(value: Any) -> Optional[float]:
    """数值 → [0,1] 内 float（4 位小数）；None/非法（含越界/NaN/字符串）返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f) or f < MIN_UNCERTAINTY or f > MAX_UNCERTAINTY:
        return None
    return round(f, 4)


def _dec_to_float(value: Any) -> Optional[float]:
    """DECIMAL 列 → float（4 位小数口径）；None/坏值 → None（无数据）。"""
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


# ============================================
# 登记（三通道共用入口）
# ============================================
def record_proposal(
    kind: str,
    stage: str,
    unit_ref: str,
    proposal: Any,
    evidence_ref: Optional[str] = None,
    prompt_version: Optional[str] = None,
    resource_version: Optional[str] = None,
    uncertainty: Optional[float] = None,
    created_by: Optional[int] = None,
) -> int:
    """登记一条 AI 提议（三通道 draft/audit/probe 共用），返回新提案 id。

    资源注入协议留痕：调用方应传 prompt_version（提示词版本）与
    resource_version（资源快照版本），让每条提议可复现「当时 AI 看到了什么」；
    uncertainty 传综合信号（规则层未命中特征数＋历史人-机分歧率＋预演分歧
    标记），不要传 LLM 自报置信度。

    Args:
        kind: 通道，∈ KINDS（'draft'/'audit'/'probe'）
        stage: 工序名（非空，≤40 字符，如 'admission'）
        unit_ref: 工作单元引用（非空，≤120 字符，如 'oald_senses:123'）
        proposal: 提议内容（可 JSON 序列化的 dict/list；NaN/Inf 拒）
        evidence_ref: 证据链引用（≤255 字符；None/空白存 NULL = 无据）
        prompt_version: 提示词版本（≤40 字符）
        resource_version: 资源快照版本（≤40 字符）
        uncertainty: 不确定度 [0,1]（None = 信号不可得）
        created_by: 登记人 users.id（系统自动登记传 None）

    Returns:
        int: 新提案 id；kind/stage/unit_ref/proposal/可选字符串/不确定度
        非法或数据库错误返回 0（falsy，调用方按失败处理）。
    """
    if kind not in KINDS:
        logger.error(f"record_proposal 拒绝非法 kind: {kind!r}（须 ∈ {KINDS}）")
        return 0
    if not isinstance(stage, str) or not stage.strip() or len(stage.strip()) > 40:
        logger.error(f"record_proposal 拒绝非法 stage: {stage!r}（非空字符串，≤40 字符）")
        return 0
    if not isinstance(unit_ref, str) or not unit_ref.strip() or len(unit_ref.strip()) > 120:
        logger.error(f"record_proposal 拒绝非法 unit_ref: {unit_ref!r}（非空字符串，≤120 字符）")
        return 0
    proposal_json = _dump_proposal(proposal)
    if proposal_json is None:
        logger.error(
            f"record_proposal 拒绝非法 proposal（kind={kind}）：须为可 JSON 序列化的 "
            f"dict/list，禁 NaN/Inf（type={type(proposal).__name__}）"
        )
        return 0
    evidence = _clean_optional_str(evidence_ref, 255)
    if evidence is _INVALID:
        logger.error(f"record_proposal 拒绝非法 evidence_ref: {evidence_ref!r}（≤255 字符）")
        return 0
    prompt_ver = _clean_optional_str(prompt_version, 40)
    if prompt_ver is _INVALID:
        logger.error(f"record_proposal 拒绝非法 prompt_version: {prompt_version!r}（≤40 字符）")
        return 0
    resource_ver = _clean_optional_str(resource_version, 40)
    if resource_ver is _INVALID:
        logger.error(f"record_proposal 拒绝非法 resource_version: {resource_version!r}（≤40 字符）")
        return 0
    raw_uncertainty = uncertainty
    uncertainty = _as_uncertainty(uncertainty)
    if raw_uncertainty is not None and uncertainty is None:
        logger.error(f"record_proposal 拒绝非法 uncertainty: {raw_uncertainty!r}（须为 [0,1] 数值）")
        return 0
    creator = _as_int(created_by)
    if created_by is not None and (creator is None or creator <= 0):
        logger.error(f"record_proposal 拒绝非法 created_by: {created_by!r}")
        return 0

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO ai_proposals (kind, stage, unit_ref, proposal, evidence_ref, "
                "prompt_version, resource_version, uncertainty, status, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)",
                (
                    kind,
                    stage.strip(),
                    unit_ref.strip(),
                    proposal_json,
                    evidence,
                    prompt_ver,
                    resource_ver,
                    uncertainty,
                    creator,
                ),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"登记 AI 提议失败（kind={kind}, stage={stage!r}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"登记 AI 提议意外错误: {e}")
        return 0


# ============================================
# 裁决（采纳/否决/修改）
# ============================================
def decide(proposal_id: int, decision: str, reason: Optional[str], decider: int) -> bool:
    """裁决一条待决提案（decision ∈ {adopted, rejected, modified}）。

    **仅 status='pending' 可裁决**（UPDATE 带 status='pending' 守卫）：
    重复裁决返回 False 且不改写首次结论 —— 采纳/否决记录是一次性的留痕，
    不可被覆盖（协同度量口径依赖不可变历史）。

    Args:
        proposal_id: 提案 id（ai_proposals.id）
        decision: 裁决值 ∈ DECISIONS；'modified' 表示人改过候选后采纳
        reason: 裁决理由（str；None 存 NULL —— 页面应尽量要求填写）
        decider: 裁决人 users.id

    Returns:
        bool: 裁决成功 True；decision/reason/decider 非法、提案不存在、
        **已裁决过（重复裁决）** 或数据库错误为 False。
    """
    pid = _as_int(proposal_id)
    if pid is None or pid <= 0:
        logger.error(f"decide 拒绝非法 proposal_id: {proposal_id!r}")
        return False
    if decision not in DECISIONS:
        logger.error(f"decide 拒绝非法 decision: {decision!r}（须 ∈ {DECISIONS}）")
        return False
    if reason is not None and not isinstance(reason, str):
        logger.error(f"decide 拒绝非法 reason: {reason!r}（str 或 None）")
        return False
    adjudicator = _as_int(decider)
    if adjudicator is None or adjudicator <= 0:
        logger.error(f"decide 拒绝非法 decider: {decider!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE ai_proposals SET status = %s, decision_reason = %s, "
                "decider_id = %s, decided_at = NOW() "
                "WHERE id = %s AND status = 'pending'",
                (decision, reason, adjudicator, pid),
            )
            if cursor.rowcount <= 0:
                # 两种等价情形：提案不存在 / 已裁决过 —— 统一拒绝且不动历史
                logger.error(f"decide 无可裁决行: proposal_id={pid}（不存在或已裁决）")
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"裁决提案 {pid} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"裁决提案 {pid} 意外错误: {e}")
        return False


# ============================================
# 待决列表（协作收件箱数据源）
# ============================================
def list_pending(
    kind: Optional[str] = None,
    stage: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """待裁决提案列表，按 uncertainty DESC, id ASC（契约 §3-D 排序口径）。

    不确定度高的排前面 —— 收件箱「最需要人看」的提议优先；不确定度缺失
    （NULL）排最后；同分按登记先后（id ASC）稳定排序。

    探针（probe）的取数约定：probe 提议照常以 pending 入账、也可裁决，
    但探针问答通常**不入裁决流**。批次 2 协作收件箱应按通道取数 ——
    ``list_pending(kind='draft')`` 与 ``list_pending(kind='audit')`` 进收件箱；
    probe 仅在探针问答页按需查询（kind='probe'），或对 ``list_pending()``
    结果自行过滤 ``kind != 'probe'``。

    Args:
        kind: 通道过滤（∈ KINDS）；None = 全部通道
        stage: 工序过滤；None = 全部工序
        limit: 返回条数上限（≤0 返回 []；超过 MAX_LIST_LIMIT 截断）

    Returns:
        list[dict]: 提案字典列表（全字段，proposal 已解析为 dict/list，
        uncertainty 为 float）；kind 非法或数据库不可用返回 []。
    """
    if kind is not None and kind not in KINDS:
        logger.error(f"list_pending 拒绝非法 kind: {kind!r}（须 ∈ {KINDS} 或 None）")
        return []
    if stage is not None and not isinstance(stage, str):
        logger.error(f"list_pending 拒绝非法 stage: {stage!r}")
        return []
    lim = _as_int(limit)
    if lim is None:
        logger.error(f"list_pending 拒绝非法 limit: {limit!r}")
        return []
    if lim <= 0:
        return []
    lim = min(lim, MAX_LIST_LIMIT)

    sql = (
        "SELECT id, kind, stage, unit_ref, proposal, evidence_ref, prompt_version, "
        "resource_version, uncertainty, status, decision_reason, decider_id, "
        "decided_at, created_by, created_at "
        "FROM ai_proposals WHERE status = 'pending'"
    )
    params: List[Any] = []
    if kind is not None:
        sql += " AND kind = %s"
        params.append(kind)
    if stage is not None:
        sql += " AND stage = %s"
        params.append(stage.strip())
    sql += " ORDER BY uncertainty DESC, id ASC LIMIT %s"
    params.append(lim)

    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"查询待决提案失败（kind={kind!r}, stage={stage!r}）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询待决提案意外错误: {e}")
        return []

    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["proposal"] = _parse_proposal_payload(item.get("proposal"))
        item["uncertainty"] = _dec_to_float(item.get("uncertainty"))
        result.append(item)
    return result


# ============================================
# 统计（协同度量页数据源，规范 §5 度量）
# ============================================
_EMPTY_STATS_KEYS = (
    "stage", "total", "pending", "adopted", "rejected", "modified",
    "decided", "adoption_rate", "avg_uncertainty",
)


def _empty_stats(stage: Any) -> Dict[str, Any]:
    """全 0 口径统计（空库/数据库不可用/非法参数时返回）。"""
    return {
        "stage": stage,
        "total": 0,
        "pending": 0,
        "adopted": 0,
        "rejected": 0,
        "modified": 0,
        "decided": 0,
        "adoption_rate": None,
        "avg_uncertainty": None,
    }


def get_stats(stage: Optional[str] = None) -> Dict[str, Any]:
    """提案统计：总数/pending 数/采纳率/平均不确定度（协同度量页数据源）。

    采纳率口径（规范 §5）：adopted / (adopted + rejected + modified) ——
    分母是**已裁决**提案数（pending 不计）；尚无已裁决提案时为 None
    （「还没数据」≠「采纳率 0」，页面自行决定展示口径）。平均不确定度
    按范围内 uncertainty 非空的**全部**提案平均（含已裁决 —— 度量的是
    信号本身的质量，不是当前积压）。

    Args:
        stage: 工序过滤；None = 全库口径

    Returns:
        dict: {stage, total, pending, adopted, rejected, modified, decided,
        adoption_rate, avg_uncertainty}；计数为 int，两个比率为 float（4 位
        小数）或 None（无数据）。stage 非法/数据库不可用返回全 0 口径
        （计数 0、比率为 None），不抛异常。
    """
    if stage is not None and not isinstance(stage, str):
        logger.error(f"get_stats 拒绝非法 stage: {stage!r}")
        return _empty_stats(stage)

    where = ""
    params: tuple = ()
    if stage is not None:
        # where 文本只含常量与占位符，stage 值走参数（不拼 SQL 文本）
        where = " WHERE stage = %s"
        params = (stage.strip(),)

    sql = (
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(status = 'pending'), 0) AS pending, "
        "COALESCE(SUM(status = 'adopted'), 0) AS adopted, "
        "COALESCE(SUM(status = 'rejected'), 0) AS rejected, "
        "COALESCE(SUM(status = 'modified'), 0) AS modified, "
        "AVG(uncertainty) AS avg_uncertainty "
        "FROM ai_proposals" + where
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"统计提案失败（stage={stage!r}）: {e}")
        return _empty_stats(stage)
    except Exception as e:
        logger.error(f"统计提案意外错误: {e}")
        return _empty_stats(stage)
    if row is None:
        return _empty_stats(stage)

    adopted = int(row.get("adopted") or 0)
    rejected = int(row.get("rejected") or 0)
    modified = int(row.get("modified") or 0)
    decided = adopted + rejected + modified
    adoption_rate = round(adopted / decided, 4) if decided > 0 else None
    return {
        "stage": stage,
        "total": int(row.get("total") or 0),
        "pending": int(row.get("pending") or 0),
        "adopted": adopted,
        "rejected": rejected,
        "modified": modified,
        "decided": decided,
        "adoption_rate": adoption_rate,
        "avg_uncertainty": _dec_to_float(row.get("avg_uncertainty")),
    }


# ============================================
# 单条读取（辅助入口，非契约 §3-D 签名）
# ============================================
def get_proposal(proposal_id: int) -> Optional[Dict[str, Any]]:
    """按 id 取单条提案（含已裁决），供批次 2 收件箱详情/防重复裁决提示。

    非契约签名（报告已注明）：list_pending 只出 pending 行，裁决前页面需要
    读单条确认当前状态（is-pending 检查）与展示完整留痕字段。

    Args:
        proposal_id: 提案 id

    Returns:
        dict | None: 全字段字典（proposal 已解析、uncertainty 为 float）；
        id 非法/不存在/数据库不可用返回 None。
    """
    pid = _as_int(proposal_id)
    if pid is None or pid <= 0:
        logger.error(f"get_proposal 拒绝非法 proposal_id: {proposal_id!r}")
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, kind, stage, unit_ref, proposal, evidence_ref, "
                "prompt_version, resource_version, uncertainty, status, "
                "decision_reason, decider_id, decided_at, created_by, created_at "
                "FROM ai_proposals WHERE id = %s",
                (pid,),
            )
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"读取提案 {pid} 失败: {e}")
        return None
    except Exception as e:
        logger.error(f"读取提案 {pid} 意外错误: {e}")
        return None
    if row is None:
        return None
    item = dict(row)
    item["proposal"] = _parse_proposal_payload(item.get("proposal"))
    item["uncertainty"] = _dec_to_float(item.get("uncertainty"))
    return item
