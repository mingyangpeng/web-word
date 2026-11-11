"""标注提交与仲裁流数据层 —— 多人标注系统（Agent B）。

设计规范：docs/spec/多人标注系统设计规范.md（唯一事实源）§2 三表 DDL、
§3 模块契约（本文件签名与之一致，不得擅改）、§6 安全规则、§7 验收 V2/V3/V7。

职责边界：
  * 只管 annotation_submissions / adjudications / assignments 三张表 ——
    users 表在 users_db.py（Agent A），信度计算在 reliability.py（Agent C），
    页面分派在 app.py 集成时做（规范 §5）。
  * 独立性（用户决策④）：annotator 之间互相不可见 —— 数据层由
    get_my_submissions（只看自己）与 get_submissions_for_sense（reviewer/admin
    看全部）两个入口体现，页面不得给 annotator 角色调后者。

核心语义（验收 V2/V3）：
  * 同一 (sense_id, task_type, coder_id) 重复提交 = 覆盖更新（UNIQUE 约束
    uq_submission + INSERT ... ON DUPLICATE KEY UPDATE）；覆盖后 status 重置为
    'submitted' —— 新提交必须重新进审核/仲裁，旧 adjudicated 结论不自动沿用。
  * 仲裁对 (sense_id, task_type) 唯一（uq_adjudication）：重复仲裁 = 覆盖定稿
    （最新 gold 为准），并把**本次明示的** submission_ids 置为 'adjudicated'
    （reliability.py 只统计 status='submitted'，仲裁后的提交自然退出信度计算）。
  * status 仅 'submitted' / 'adjudicated' 两态（规范 §2 ENUM）。

安全规则（规范 §6，全体遵守）：
  1. SQL 一律参数化（沿用 mysql_db.get_db_cursor 模式），本文件无一处把值
     拼进 SQL 文本 —— IN 子句也只用动态占位符；
  2. 权限检查（谁能仲裁、谁看全部）由页面层 role gate 负责（§6-4），
     数据层按「入口函数即最小权限面」拆分（get_my_* vs get_submissions_for_sense）；
  3. payload 在应用层先校验再入库：非法值根本不进数据库（不依赖 ENUM/JSON 报错）。
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional

import pymysql

from src.db_utils import as_int as _as_int  # R6-4：公共小件单一实现点
from src.db_utils import column_exists as _column_exists  # R6-4：同上（FX-20 迁移用）
from src.mysql_db import get_db_cursor
from src.users_db import effective_six_roles

logger = logging.getLogger(__name__)

# ============================================
# 常量（规范 §1/§2/§3）
# ============================================
TASK_TYPES = ("admission", "feature_coding", "alignment")

# task_type 展示名（R6-8 单一导出：sense_spine / collab_pages 的两份同名
# 映射收敛于此；存库一律用英文枚举值，中文只做展示。admission 取工序名
# 「义位准入」——sense_spine 原值，collab_pages 的「准入标注」自此统一）。
TASK_TYPE_LABELS = {
    "admission": "义位准入",
    "feature_coding": "特征编码",
    "alignment": "英汉对齐",
}

# submission status 仅两态（规范 §2 ENUM('submitted','adjudicated')）
STATUS_SUBMITTED = "submitted"
STATUS_ADJUDICATED = "adjudicated"
SUBMISSION_STATUSES = (STATUS_SUBMITTED, STATUS_ADJUDICATED)

# admission 任务比对字段（验收 V3 + 任务要求：含 needs_review，bool 值按
# 'true'/'false' 比较）。alignment 作为独立 task_type 时只比 alignment 本身
# （与 reliability.py 的 _TASK_FIELDS 口径一致，另加 needs_review 属 flow 特有）。
ADMISSION_FIELDS = ("admission", "schema", "alignment", "needs_review")
ALIGNMENT_FIELDS = ("alignment",)

# admission 任务 payload["admission"] 的合法值（规范 §2 注释："Y|EXT|N"）
ADMIT_VALUES = ("Y", "EXT", "N")

# ============================================
# 建表 SQL（规范 §2 三表 DDL 原样；幂等，CREATE TABLE IF NOT EXISTS）
# ============================================
ASSIGNMENTS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  assignee_id INT NOT NULL,
  category VARCHAR(40) NOT NULL DEFAULT 'motion',
  task_type ENUM('admission','feature_coding','alignment') NOT NULL DEFAULT 'admission',
  scope_verbs JSON NULL,                        -- NULL=全部动词；否则 ["run","walk",...]
  status ENUM('open','in_progress','submitted','closed') NOT NULL DEFAULT 'open',
  assigned_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_assignee (assignee_id),
  CONSTRAINT fk_assign_user FOREIGN KEY (assignee_id) REFERENCES users(id),
  CONSTRAINT fk_assign_admin FOREIGN KEY (assigned_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

ANNOTATION_SUBMISSIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS annotation_submissions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category VARCHAR(40) NOT NULL DEFAULT 'motion',
  sense_id INT NOT NULL,                        -- → oald_senses.id（996 义位含 4 补充）
  task_type ENUM('admission','feature_coding','alignment') NOT NULL DEFAULT 'admission',
  coder_id INT NOT NULL,
  payload JSON NOT NULL,   -- admission 任务: {"admission":"Y|EXT|N","schema":"...","alignment":"...",
                           --   "cn_syntax":"...","strategy":"...","needs_review":bool}
                           -- feature_coding 任务: {"features":{"P1":1,...}}
  ai_assisted TINYINT(1) NOT NULL DEFAULT 1,    -- 全员看同样 AI 草稿（用户决策③）
  status ENUM('submitted','adjudicated') NOT NULL DEFAULT 'submitted',
  submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_submission (sense_id, task_type, coder_id),
  KEY idx_sense (sense_id), KEY idx_coder (coder_id),
  CONSTRAINT fk_sub_sense FOREIGN KEY (sense_id) REFERENCES oald_senses(id),
  CONSTRAINT fk_sub_coder FOREIGN KEY (coder_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

ADJUDICATIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS adjudications (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sense_id INT NOT NULL,
  task_type ENUM('admission','feature_coding','alignment') NOT NULL DEFAULT 'admission',
  submission_ids JSON NOT NULL,                 -- 参与仲裁的提交 id 列表（留痕）
  adjudicator_id INT NOT NULL,
  gold_payload JSON NOT NULL,                   -- 定稿判定（同 payload 结构）
  note TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_adjudication (sense_id, task_type),
  CONSTRAINT fk_adj_sense FOREIGN KEY (sense_id) REFERENCES oald_senses(id),
  CONSTRAINT fk_adj_user FOREIGN KEY (adjudicator_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_FLOW_TABLE_DDLS = (
    # 顺序：先建只依赖 users 的 assignments，再建依赖 users + oald_senses 的两表。
    # users 表由 users_db.ensure_user_tables() 负责（集成时先调它）；
    # oald_senses 由 mysql_db.init_database() 负责。被引用表缺失时 MySQL 直接报错，
    # 由下面的 try/except 记日志（含修复提示），不让页面整页崩掉。
    ASSIGNMENTS_TABLE_SQL,
    ANNOTATION_SUBMISSIONS_TABLE_SQL,
    ADJUDICATIONS_TABLE_SQL,
)

# FX-20 试标轮两列（ALTER-only 幂等迁移；建表 SQL 保持规范 §2 原样不动，
# 存量库与新库统一走「建旧形 → 探测补列」同一条迁移路径，仿
# media_db.MEDIA_BINDINGS_AUDIT_COLUMNS 先例）。NULL 口径遵循仓库 RV2-3
# 「留痕列 NULL 口径」：round INT NULL=未设轮次（正式轮不用 0 冒充）；
# training TINYINT(1) NULL=非试标轮（未设即 NULL，不用 0 冒充「非试标」）。
# `round` 加反引号：与 MySQL 内建函数名 ROUND 同名，防御性引用。
ASSIGNMENTS_ROUND_COLUMNS = (
    ("round", "ALTER TABLE assignments ADD COLUMN `round` INT NULL"),
    ("training",
     "ALTER TABLE assignments ADD COLUMN training TINYINT(1) NULL DEFAULT NULL"),
)

# FX-43 AI 初筛草稿快照列（ALTER-only 幂等迁移，照 ASSIGNMENTS_ROUND_COLUMNS
# 先例）：annotation_submissions 补 ai_draft_snapshot JSON NULL，落提交时的
# AI 初筛草稿原始值（「AI 当初给的」，不含人工修改后的值 —— 修改后的最终值
# 在 payload）。NULL 口径遵循仓库 RV2-3「留痕列 NULL 口径」：NULL = 提交时
# 无 AI 草稿（纯人工/系统提交），不用空对象 {} 冒充「有草稿」。建表 SQL 保持
# 规范 §2 DDL 原样不动，存量库与新库统一走「建旧形 → 探测补列」同一条迁移
# 路径（仿 media_db.MEDIA_BINDINGS_AUDIT_COLUMNS 先例）。
SUBMISSION_AI_DRAFT_COLUMNS = (
    ("ai_draft_snapshot",
     "ALTER TABLE annotation_submissions ADD COLUMN ai_draft_snapshot JSON NULL"),
)

# assignments.status 实际枚举（规范 §2 DDL ENUM，test_status_constants_match_ddl_enum
# 锁定）。规范 §8 写「改派仅限 draft/rejected」，码内无此二字面值 —— 以码为准的
# 映射口径见 REASSIGNABLE_ASSIGNMENT_STATUSES 注释。
ASSIGNMENT_STATUSES = ("open", "in_progress", "submitted", "closed")

# 改派状态闸（FX-20，规范 §8「改派仅限 draft/rejected」→ 码内枚举映射）：
#   * draft（已分派未动工）→ 'open'；
#   * rejected 无字面对应 —— 全仓无 assignments 状态流转写点（分派创建即 open，
#     无人 UPDATE status），无法产生「被打回」行；
#   * in_progress（active 对应，动工中）/ submitted（工作已交付待审，改派会孤儿化
#     已交成果）/ closed（已闭环）一律拒绝改派。
# 刻意比「停用用户强制先改派在途任务」（规范 §8）更严：在途 in_progress 的移出
# 保护沿用 org_db.remove_member 既有纪律口径（占位实现），本函数不放宽、
# 也不接管该纪律 —— 闸门收窄到「未动工的分派可换人」这一最小诚实面。
REASSIGNABLE_ASSIGNMENT_STATUSES = ("open",)

# 分立复核裁决落地后的 cs_senses.status 取值（与 cluster_analysis.SPLIT_STATUS_VALUES
# 同一口径的镜像常量 —— annotation_flow 不反向依赖页面/分析模块，防环）。
DIVIDED_SENSE_STATUSES = ("merged", "split")


# ============================================
# payload 校验（应用层先拒，非法值不进数据库）
# ============================================
def _is_scalar_label(value: Any) -> bool:
    """标注值只允许标量（str/int/float/bool）。

    dict/list 等结构化值不是标注（payload 结构由各 task_type 的键负责）；
    float NaN/Inf 也拒 —— json.dumps 会产出非法 JSON（NaN 字面量），MySQL
    JSON 列必炸，与其等报错不如入口先拒。
    字符串 "nan"/"NaN" 等（float() 可解析出 NaN 的串）同样拒：两个下游消费方
    （本模块 _normalize_for_compare 与 reliability._is_usable_label）都把这类
    串按缺失剔除，入库只是存垃圾值（R4 review：与「非法值根本不进数据库」
    口径对齐）。"inf" 等非 NaN 数值串是合法 nominal 标签，照常放行。
    """
    if isinstance(value, bool):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        try:
            return not math.isnan(float(value))
        except ValueError:
            return True
    return isinstance(value, int)


def validate_payload(task_type: str, payload: Any) -> bool:
    """校验 payload 是否符合规范 §2 注释的各任务结构。非法返回 False。

    * admission：必须有 ``admission`` ∈ {"Y","EXT","N"}；``needs_review`` 若给
      必须是 bool；其余值均为标量；
    * feature_coding：必须有非空 ``features`` dict，键为特征码（非空 str），
      值为标量（P1 的 0/1、ordinal 数值、nominal 标签均可）；
    * alignment：规范未定义固定结构，只要求非空 dict 且值均为标量；
    * 通用：payload 必须是非空 dict（payload 列 NOT NULL，空标注无意义）；
      未登记的额外键放行（前向兼容），但其值也必须是标量。
    """
    if not isinstance(payload, dict) or not payload:
        return False

    if task_type == "feature_coding":
        features = payload.get("features")
        if not isinstance(features, dict) or not features:
            return False
        for name, value in features.items():
            if not isinstance(name, str) or not name.strip():
                return False
            if not _is_scalar_label(value):
                return False
        extra = {k: v for k, v in payload.items() if k != "features"}
    else:
        extra = payload

    # 额外键的值一律标量（feature_coding 的 features 嵌套 dict 已单独校验）
    for value in extra.values():
        if not _is_scalar_label(value):
            return False

    if task_type == "admission":
        if "admission" not in payload:
            return False
        if payload["admission"] not in ADMIT_VALUES:
            return False
        if "needs_review" in payload and not isinstance(payload["needs_review"], bool):
            return False
        return True

    # alignment：结构从宽（值标量 + 非空已在上面统一校验）
    return True


# _as_int 收敛至 src/db_utils.as_int（R6-4 单一实现点；原「宽容转 int，
# bool/None/转不动 → None」语义与公共件逐字节一致，别名导入调用点不变）。
def parse_payload(raw: Any) -> dict:
    """annotation_submissions.payload → dict（PyMySQL 对 JSON 列可能给 str 或 dict）。

    本函数是 JSON 列 payload 解析的**唯一实现**（R4 消重：reliability.py 原有一份
    逐字复制，现改为从此处导入）；解析失败/非 dict 一律返回 {}，按缺失剔除。
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_json_list(raw: Any) -> Optional[list]:
    """JSON 列（scope_verbs / submission_ids）→ list；NULL → None；坏数据 → None。

    返回契约不变（None=全部动词 / 无仲裁留痕，RV14-8 不动形态）；坏数据路径
    加 logger.warning 留痕 —— scope_verbs 坏数据按 None 降级会把「范围语义」
    静默放大为「全部动词」（标注人实际能看到的动词集合被放大），必须落日志
    供运维核查库内脏数据，不得无声降级。
    """
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            _warn_bad_json_list(f"UTF-8 解码失败: {bytes(raw)[:80]!r}")
            return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            _warn_bad_json_list(f"非法 JSON: {raw[:80]!r}")
            return None
        if not isinstance(parsed, list):
            _warn_bad_json_list(f"JSON 非 list（{type(parsed).__name__}）: {raw[:80]!r}")
            return None
        return parsed
    _warn_bad_json_list(f"非字符串/列表类型（{type(raw).__name__}）: {raw!r}"[:120])
    return None


def _warn_bad_json_list(detail: str) -> None:
    """_parse_json_list 坏数据统一告警文案（RV14-8：单点，两消费方同口径）。"""
    logger.warning(
        "JSON 列坏数据按 None 降级（%s）—— scope_verbs 场景即「范围语义"
        "静默放大为全部动词」，请核查库内脏数据", detail,
    )


def _row_round(row: dict) -> Optional[int]:
    """assignments 行的 round 列 → int|None（FX-20；None=未设轮次，RV2-3 口径）。

    PyMySQL 对 INT NULL 给 None；脏值（非数字串等）按 None 降级不编数。
    """
    raw = row.get("round")
    if raw is None:
        return None
    value = _as_int(raw)
    return value if (value is not None and value >= 1) else None


def _row_training(row: dict) -> Optional[bool]:
    """assignments 行的 training 列 → bool|None（FX-20；None=非试标不留痕）。

    TINYINT(1) 可能有 0/1/None 三态：None=未设（正式轮不留痕）；0/1 → bool。
    列未迁移补齐（查询报 Unknown column）由调用方的降级路径兜住。
    """
    raw = row.get("training")
    if raw is None:
        return None
    return bool(raw)


# ============================================
# 建表
# ============================================
def ensure_flow_tables() -> None:
    """幂等创建 flow 三表：assignments / annotation_submissions / adjudications
    （规范 §2 DDL 原样，CREATE TABLE IF NOT EXISTS，可重复调用）。

    建表后随做两段幂等迁移（information_schema 探测、已有则跳过 —— 存量库与
    新库同一条路径）：FX-20 试标轮两列（``_migrate_assignments_round_columns``）
    ＋ FX-43 AI 初筛草稿快照列（``_migrate_submissions_ai_draft_column``）。

    外键引用 users 与 oald_senses：集成时先调 ``users_db.ensure_user_tables()``
    （users 表为空还会得到内置 admin），并确保 ``mysql_db.init_database()`` 已建
    oald_senses。被引用表缺失时本函数只记 error 日志不抛异常（与
    users_db.ensure_user_tables 的容错口径一致），页面可继续渲染。
    """
    try:
        with get_db_cursor() as cursor:
            for ddl in _FLOW_TABLE_DDLS:
                cursor.execute(ddl)
            _migrate_assignments_round_columns(cursor)
            _migrate_submissions_ai_draft_column(cursor)
    except pymysql.Error as e:
        if _is_dup_column_error(e):
            # RV14-4：1060（Duplicate column）= 并发首启的第二进程在探测窗口后
            # 撞列 —— 幂等成功而非故障，单列分流，不进下方「检查 users/oald_senses
            # 是否已建」误导文案（那是被引用表缺失的归因）。
            logger.info(f"flow 表结构已被并发进程补齐（MySQL 1060 幂等自愈）: {e}")
        else:
            logger.error(f"flow 表初始化失败（MySQL，检查 users/oald_senses 是否已建）: {e}")
    except Exception as e:
        logger.error(f"flow 表初始化意外错误: {e}")


def _is_dup_column_error(e: BaseException) -> bool:
    """MySQL 1060（ER_DUP_FIELD，Duplicate column）判定（RV14-4 迁移幂等自愈）。"""
    return isinstance(e, pymysql.Error) and bool(e.args) and e.args[0] == 1060


def _add_columns_if_missing(cursor, table: str, columns, label: str) -> None:
    """缺列补列的公共迁移核（FX-20/FX-43 两段迁移共用，行为口径不变）。

    ALTER-only：column_exists 探测（information_schema，走 db_utils 单一实现）→
    缺列才 ADD COLUMN；二次执行探测命中直接跳过，不炸不重复加列。ALTER 逐条
    捕 MySQL 1060（并发首启第二进程在探测窗口后撞列，RV14-4）—— 视为幂等
    成功继续探测下一列；其余 pymysql.Error 向上抛，由 ensure_flow_tables
    的外层 try/except 记日志（不抛），页面可继续渲染。
    """
    for column, sql in columns:
        if not _column_exists(cursor, table, column):
            try:
                cursor.execute(sql)
            except pymysql.Error as e:
                if not _is_dup_column_error(e):
                    raise
                logger.info(
                    f"{table}.{column} 已由并发进程补齐"
                    "（MySQL 1060，幂等自愈继续，RV14-4）"
                )
                continue
            logger.info(f"{table}.{column} 列已补齐（{label}）")


def _migrate_assignments_round_columns(cursor) -> None:
    """assignments 存量结构迁移：补 round / training 两列（幂等，FX-20）。

    ALTER-only 幂等迁移核见 _add_columns_if_missing（本函数是 assignments
    试标轮两列的入口签名，tests/test_fx20_fixes.py 直调锁定）。
    """
    _add_columns_if_missing(cursor, "assignments", ASSIGNMENTS_ROUND_COLUMNS,
                            "FX-20 试标轮迁移")


def _migrate_submissions_ai_draft_column(cursor) -> None:
    """annotation_submissions 存量结构迁移：补 ai_draft_snapshot 列（FX-43）。

    同款 ALTER-only 幂等迁移核（_add_columns_if_missing，含 MySQL 1060
    白名单）；列语义与 NULL 口径见 SUBMISSION_AI_DRAFT_COLUMNS 注释（RV2-3：
    NULL=无 AI 草稿，不用空对象冒充）。
    """
    _add_columns_if_missing(cursor, "annotation_submissions",
                            SUBMISSION_AI_DRAFT_COLUMNS,
                            "FX-43 AI 草稿快照迁移")


# ============================================
# 提交（验收 V2：重复提交 = 覆盖更新）
# ============================================
def submit_annotation(
    category: str,
    sense_id: int,
    task_type: str,
    coder_id: int,
    payload: dict,
    ai_assisted: bool = True,
    ai_draft: Optional[Dict] = None,
) -> bool:
    """提交/覆盖一条标注（INSERT ... ON DUPLICATE KEY UPDATE）。

    同一 (sense_id, task_type, coder_id) 已有提交时整行覆盖（payload、
    ai_assisted、submitted_at 均更新），且 **status 重置为 'submitted'** ——
    覆盖即重新进入审核流，旧的 adjudicated 结论不自动沿用（验收 V2）。

    Args:
        category: 范畴名（如 'motion'），非空字符串
        sense_id: 义位 id（oald_senses.id）
        task_type: 'admission' | 'feature_coding' | 'alignment'
        coder_id: 标注员 id（users.id）
        payload: 标注内容（结构见 validate_payload；非法值直接拒绝，不进库）
        ai_assisted: 是否基于 AI 草稿标注（用户决策③：全员看同样草稿，默认 True）
        ai_draft: AI 初筛草稿**原始值**快照（FX-43，「AI 当初给的」，不含人工
            修改后的值 —— 修改后的最终值在 payload）；ensure_ascii=False 序列化
            后落 ai_draft_snapshot 列，供逐特征 AI-人一致率比对
            （collab_metrics.feature_level_agreement_rate）。None = 行为与列
            缺省完全一致（SQL 不写快照列，新行落列默认 NULL，旧调用零破坏）；
            非 dict / 空 dict / 序列化失败 → 降级同 None（RV2-3 口径：不用
            空对象冒充「有草稿」，也不让快照脏值拖垮标注提交本体）。

    Returns:
        bool: 提交成功 True；payload/参数非法或数据库错误 False
    """
    if not isinstance(category, str) or not category.strip():
        logger.error("submit_annotation 拒绝空 category")
        return False
    if task_type not in TASK_TYPES:
        logger.error(f"submit_annotation 拒绝非法 task_type: {task_type!r}")
        return False
    sense = _as_int(sense_id)
    coder = _as_int(coder_id)
    if sense is None or sense <= 0 or coder is None or coder <= 0:
        logger.error(f"submit_annotation 拒绝非法 id: sense_id={sense_id!r}, coder_id={coder_id!r}")
        return False
    if not validate_payload(task_type, payload):
        logger.error(f"submit_annotation 拒绝非法 payload（task_type={task_type}）")
        return False

    # FX-43 草稿快照预序列化：None/非 dict/空 dict/序列化失败 → draft_json=None
    # （SQL 不含快照列，与既有语句逐字节一致 —— 旧调用零破坏，RV2-3 不用空对象
    # 冒充有草稿）。快照脏值只降级快照本身，不拦标注提交本体。
    draft_json: Optional[str] = None
    if ai_draft is not None:
        if not isinstance(ai_draft, dict) or not ai_draft:
            logger.warning(
                "submit_annotation: ai_draft 非 dict/为空 → 快照落 NULL"
                "（RV2-3 口径：不用空对象冒充有草稿）"
            )
        else:
            try:
                draft_json = json.dumps(ai_draft, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                logger.error(f"submit_annotation: ai_draft 序列化失败 → 快照落 NULL: {e}")

    if draft_json is None:
        # 既有语句（FX-43 前逐字节原样）：不带 ai_draft，新行落列默认 NULL
        sql = (
            "INSERT INTO annotation_submissions "
            "(category, sense_id, task_type, coder_id, payload, ai_assisted, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'submitted') "
            "ON DUPLICATE KEY UPDATE "
            "category = VALUES(category), "
            "payload = VALUES(payload), "
            "ai_assisted = VALUES(ai_assisted), "
            "status = 'submitted', "
            "submitted_at = CURRENT_TIMESTAMP"
        )
        params: tuple = (
            category,
            sense,
            task_type,
            coder,
            json.dumps(payload, ensure_ascii=False),
            1 if ai_assisted else 0,
        )
    else:
        # 带草稿快照：INSERT 落原始值；覆盖更新时快照随新提交同步覆盖
        # （快照语义=「本次提交时 AI 给了什么」，不沿用旧行残留快照）
        sql = (
            "INSERT INTO annotation_submissions "
            "(category, sense_id, task_type, coder_id, payload, ai_assisted, "
            "ai_draft_snapshot, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted') "
            "ON DUPLICATE KEY UPDATE "
            "category = VALUES(category), "
            "payload = VALUES(payload), "
            "ai_assisted = VALUES(ai_assisted), "
            "ai_draft_snapshot = VALUES(ai_draft_snapshot), "
            "status = 'submitted', "
            "submitted_at = CURRENT_TIMESTAMP"
        )
        params = (
            category,
            sense,
            task_type,
            coder,
            json.dumps(payload, ensure_ascii=False),
            1 if ai_assisted else 0,
            draft_json,
        )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            return True
    except pymysql.Error as e:
        logger.error(f"提交标注失败（sense={sense}, coder={coder}）: {e}")
        return False
    except Exception as e:
        logger.error(f"提交标注意外错误（sense={sense}, coder={coder}）: {e}")
        return False


def _submission_row_to_dict(row: dict) -> dict:
    """annotation_submissions 行 → 对外 dict（payload 解析，ai_assisted 转 bool）。"""
    return {
        "id": int(row["id"]),
        "category": row.get("category"),
        "sense_id": int(row["sense_id"]),
        "task_type": row.get("task_type"),
        "coder_id": int(row["coder_id"]),
        "payload": parse_payload(row.get("payload")),
        "ai_assisted": bool(row.get("ai_assisted")),
        "status": row.get("status"),
        "submitted_at": row.get("submitted_at"),
    }


def get_my_submissions(
    coder_id: int, category: str, task_type: str
) -> List[Dict[str, Any]]:
    """某标注员在 (category, task_type) 下的全部自己的提交（独立性入口）。

    annotator 只允许经此函数看自己的提交（含 submitted 与 adjudicated 两态，
    自己的历史结论对自己可见）；按 sense_id 升序。数据库不可用返回 []。
    """
    coder = _as_int(coder_id)
    if coder is None:
        logger.error(f"get_my_submissions 拒绝非法 coder_id: {coder_id!r}")
        return []
    sql = (
        "SELECT id, category, sense_id, task_type, coder_id, payload, ai_assisted, "
        "status, submitted_at "
        "FROM annotation_submissions "
        "WHERE coder_id = %s AND category = %s AND task_type = %s "
        "ORDER BY sense_id, id"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (coder, category, task_type))
            return [_submission_row_to_dict(row) for row in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"查询提交列表失败（coder={coder}）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询提交列表意外错误（coder={coder}）: {e}")
        return []


def get_submissions_for_sense(
    sense_id: int, task_type: str
) -> List[Dict[str, Any]]:
    """某义位在指定任务类型下的**全部编码人**提交（reviewer/admin 专用入口）。

    与 get_my_submissions 相对：这是「看全部」入口（用户决策④），页面层必须
    做 role gate，不得暴露给 annotator。附 LEFT JOIN users 的 username /
    display_name 供仲裁面板展示；adjudicated 的历史提交也返回（留痕可见）。
    数据库不可用返回 []。
    """
    sense = _as_int(sense_id)
    if sense is None:
        logger.error(f"get_submissions_for_sense 拒绝非法 sense_id: {sense_id!r}")
        return []
    sql = (
        "SELECT s.id, s.category, s.sense_id, s.task_type, s.coder_id, s.payload, "
        "s.ai_assisted, s.status, s.submitted_at, u.username, u.display_name "
        "FROM annotation_submissions s "
        "LEFT JOIN users u ON u.id = s.coder_id "
        "WHERE s.sense_id = %s AND s.task_type = %s "
        "ORDER BY s.coder_id, s.id"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (sense, task_type))
            rows = []
            for row in cursor.fetchall():
                item = _submission_row_to_dict(row)
                item["username"] = row.get("username")
                item["display_name"] = row.get("display_name")
                rows.append(item)
            return rows
    except pymysql.Error as e:
        logger.error(f"查询义位提交失败（sense={sense}）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询义位提交意外错误（sense={sense}）: {e}")
        return []


# ============================================
# 分歧检测（验收 V3）
# ============================================
def _normalize_for_compare(field: str, value: Any) -> Any:
    """比对口径归一：bool → 'true'/'false'（任务要求）。

    needs_review 防御性兼容 int 0/1（TINYINT 混写）；NaN 视为缺失
    （返回 None，调用方按缺失跳过），与 reliability.py 的缺失容忍口径一致。
    字符串 "nan"/"NaN" 等（float() 可解析出 NaN 的串）同样按缺失 —— 与
    reliability._is_usable_label 的口径一致（R2 review：脏值不做假标签）。
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if field == "needs_review" and value in (0, 1):
        return "true" if int(value) == 1 else "false"
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        try:
            if math.isnan(float(value)):
                return None
        except ValueError:
            pass
    return value


def _coder_sort_key(coder_id: Any):
    """values dict 的键排序：数字 id 按数值序，其余按字典序兜底。"""
    try:
        return (0, int(coder_id), "")
    except (TypeError, ValueError):
        return (1, 0, str(coder_id))


def _disagree_fields_for_payloads(
    task_type: str, payloads: Dict[int, dict]
) -> List[Dict[str, Any]]:
    """同一 sense 下 {coder_id: payload} 的分歧字段列表（只列取值不一的字段）。

    admission/alignment 任务比对其固定字段；feature_coding 对 payload["features"]
    逐特征比对。某字段只在部分 payload 里出现时：有值的 coder 参与比对
    （缺失容忍），值不足两个或全部一致则不算分歧。
    """
    if task_type == "feature_coding":
        names = sorted(
            {
                str(name)
                for payload in payloads.values()
                for name in (payload.get("features") or {})
            }
        )
        candidates = []
        for name in names:
            values = {}
            for coder_id, payload in payloads.items():
                features = payload.get("features")
                if isinstance(features, dict) and features.get(name) is not None:
                    values[str(coder_id)] = _normalize_for_compare(
                        name, features.get(name)
                    )
            candidates.append((name, values))
    else:
        fields = ADMISSION_FIELDS if task_type == "admission" else ALIGNMENT_FIELDS
        candidates = []
        for field in fields:
            values = {}
            for coder_id, payload in payloads.items():
                raw = payload.get(field)
                if raw is not None:
                    values[str(coder_id)] = _normalize_for_compare(field, raw)
            candidates.append((field, values))

    fields_out = []
    for field, values in candidates:
        # 归一后可能产生 None（NaN）；None 按缺失剔除
        values = {coder: v for coder, v in values.items() if v is not None}
        if len(values) < 2:
            continue
        if len({str(v) for v in values.values()}) <= 1:
            continue
        fields_out.append(
            {
                "field": field,
                "values": {
                    coder: values[coder]
                    for coder in sorted(values.keys(), key=_coder_sort_key)
                },
            }
        )
    return fields_out


def detect_disagreements(
    category: str, task_type: str, min_coders: int = 2
) -> List[Dict[str, Any]]:
    """分歧清单：同一 sense 被 ≥min_coders 人提交且存在取值不一的字段。

    只统计 status='submitted' 的提交（已 adjudicated 的视为已解决，退出清单，
    与 reliability.py 口径一致）。admission 任务比对字段
    admission/schema/alignment/needs_review（bool 转 'true'/'false' 比较）；
    feature_coding 逐特征比对 payload["features"]；alignment 任务比 alignment。

    Returns:
        list[dict]::

            [{"sense_id": int, "verb": str|None, "sense_index": int|None,
              "n_submissions": int,
              "fields": [{"field": str, "values": {"<coder_id>": value}}, ...]}]

        verb / sense_index 经 LEFT JOIN oald_senses 取（headword / sense_index），
        义位不存在时为 None；values 的键是字符串化的 coder_id（JSON 安全）。
        数据库不可用返回 []。
    """
    if task_type not in TASK_TYPES:
        logger.error(f"detect_disagreements 拒绝非法 task_type: {task_type!r}")
        return []
    try:
        min_coders = int(min_coders)
    except (TypeError, ValueError):
        min_coders = 2

    sql = (
        "SELECT s.sense_id, s.coder_id, s.payload, o.headword AS verb, o.sense_index "
        "FROM annotation_submissions s "
        "LEFT JOIN oald_senses o ON o.id = s.sense_id "
        "WHERE s.category = %s AND s.task_type = %s AND s.status = 'submitted' "
        "ORDER BY s.sense_id, s.coder_id"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (category, task_type))
            rows = list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"分歧检测读取提交失败: {e}")
        return []
    except Exception as e:
        logger.error(f"分歧检测读取提交意外错误: {e}")
        return []

    # sense_id → {coder_id: payload}（UNIQUE 约束保证一人一行）+ verb/sense_index
    by_sense: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        entry = by_sense.setdefault(
            int(row["sense_id"]),
            {
                "verb": row.get("verb"),
                "sense_index": row.get("sense_index"),
                "payloads": {},
            },
        )
        entry["payloads"][int(row["coder_id"])] = parse_payload(row.get("payload"))

    result: List[Dict[str, Any]] = []
    for sense_id in sorted(by_sense):
        entry = by_sense[sense_id]
        n_coders = len(entry["payloads"])
        if n_coders < max(2, min_coders):
            # 少于 2 人不可能有「编码人间分歧」；min_coders 更大时按调用方门槛
            continue
        fields = _disagree_fields_for_payloads(task_type, entry["payloads"])
        if not fields:
            continue
        result.append(
            {
                "sense_id": sense_id,
                "verb": entry["verb"],
                "sense_index": entry["sense_index"],
                "n_submissions": n_coders,
                "fields": fields,
            }
        )
    return result


# ============================================
# 仲裁定稿
# ============================================
def save_adjudication(
    sense_id: int,
    task_type: str,
    adjudicator_id: int,
    gold_payload: dict,
    submission_ids: list,
    note: Optional[str],
    *,
    actor: Any = None,
) -> bool:
    """写入（或覆盖）一条仲裁定稿 gold，并把参与的提交置为 'adjudicated'。

    * (sense_id, task_type) 在 adjudications 表唯一（uq_adjudication）：重复仲裁
      = 覆盖最新定稿（gold_payload / submission_ids / adjudicator_id / note 均更新）；
    * submission_ids 是**本次明示参与仲裁**的提交 id（留痕写入 gold 行），事务里
      同时 UPDATE annotation_submissions SET status='adjudicated'（reliability.py
      只统计 submitted，仲裁后的提交自然退出信度与分歧口径）；未列入的提交
      保持 'submitted'；
    * 两条语句在同一事务（get_db_cursor(autocommit=False)）：定稿落库与状态
      翻转要么都成功要么都不发生。

    **数据层直调面口径（R1-1 第一批，施工规范 §14）**：keyword ``actor=None``
    ——None = 系统作业（仲裁数据迁移等）；页面调用点**必须**传
    ``actor=当前会话用户``。actor 为 dict 时其有效六角色须含 reviewer 及以上
    仲裁面（dict_admin / sys_admin / reviewer —— 与 app 仲裁面板入口同一
    允许集，判定单一实现 users_db.effective_six_roles），不足抛 PermissionError
    （低权直调伪造 gold 定稿＝污染金标，与 R1-1 提权家族同源收口）；其余
    类型 fail-closed 同抛。抛出发生在函数入口（try 之前），不落入 False 口径。

    Args:
        sense_id: 义位 id；task_type: 任务类型
        adjudicator_id: 仲裁人 id（页面层须已做 reviewer/admin role gate）
        gold_payload: 定稿判定（结构同 submit_annotation 的 payload，先校验）
        submission_ids: 参与仲裁的提交 id 列表（允许空列表 = 无历史提交直接定稿）
        note: 仲裁说明（可为 None）
        actor: 会话用户 dict（页面传当前用户）| None（系统作业）

    Returns:
        bool: 成功 True；参数非法或数据库错误 False

    Raises:
        PermissionError: actor 为低权 dict / 非 dict 垃圾值（R1-1 直调面）。
    """
    if actor is None:
        pass  # 系统作业（docstring 口径：页面调用点必须传 actor）
    elif isinstance(actor, dict):
        effective = effective_six_roles(actor)
        if not (effective & {"dict_admin", "sys_admin", "reviewer"}):
            raise PermissionError(
                f"保存仲裁定稿被拒绝：当前用户（{actor.get('username', '?')}）"
                "有效角色集不含 reviewer/dict_admin —— 仲裁仅审校侧可执行"
                "（数据层直调面口径：页面调用点必须传 actor=当前会话用户；"
                "None=系统作业）。"
            )
    else:
        raise PermissionError(
            "保存仲裁定稿被拒绝：actor 须为会话用户 dict 或 None（系统作业）"
            "——数据层直调面口径：页面调用点必须传 actor=当前会话用户。"
        )
    if task_type not in TASK_TYPES:
        logger.error(f"save_adjudication 拒绝非法 task_type: {task_type!r}")
        return False
    sense = _as_int(sense_id)
    adjudicator = _as_int(adjudicator_id)
    if sense is None or sense <= 0 or adjudicator is None or adjudicator <= 0:
        logger.error(
            f"save_adjudication 拒绝非法 id: sense_id={sense_id!r}, "
            f"adjudicator_id={adjudicator_id!r}"
        )
        return False
    if not validate_payload(task_type, gold_payload):
        logger.error(f"save_adjudication 拒绝非法 gold_payload（task_type={task_type}）")
        return False
    if submission_ids is None or isinstance(submission_ids, (str, bytes, dict)):
        logger.error(f"save_adjudication 拒绝非法 submission_ids: {submission_ids!r}")
        return False
    ids = []
    for raw_id in submission_ids:
        item = _as_int(raw_id)
        if item is None or item <= 0:
            logger.error(f"save_adjudication 拒绝非法提交 id: {raw_id!r}")
            return False
        ids.append(item)
    if note is not None and not isinstance(note, str):
        logger.error(f"save_adjudication 拒绝非法 note: {note!r}")
        return False

    insert_sql = (
        "INSERT INTO adjudications "
        "(sense_id, task_type, submission_ids, adjudicator_id, gold_payload, note) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE "
        "submission_ids = VALUES(submission_ids), "
        "adjudicator_id = VALUES(adjudicator_id), "
        "gold_payload = VALUES(gold_payload), "
        "note = VALUES(note), "
        "created_at = CURRENT_TIMESTAMP"
    )
    insert_params = (
        sense,
        task_type,
        json.dumps(ids, ensure_ascii=False),
        adjudicator,
        json.dumps(gold_payload, ensure_ascii=False),
        note,
    )
    update_sql = (
        "UPDATE annotation_submissions SET status = 'adjudicated' "
        "WHERE sense_id = %s AND task_type = %s AND id IN ("
        + ", ".join(["%s"] * len(ids))
        + ")"
    )
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(insert_sql, insert_params)
            if ids:
                cursor.execute(update_sql, (sense, task_type, *ids))
        return True
    except pymysql.Error as e:
        logger.error(f"保存仲裁失败（sense={sense}, task={task_type}）: {e}")
        return False
    except Exception as e:
        logger.error(f"保存仲裁意外错误（sense={sense}, task={task_type}）: {e}")
        return False


# ============================================
# 任务分配（补充函数，供 admin 用户管理/分配页调用）
# ============================================
def assign_task(
    assignee_id: int,
    category: str,
    task_type: str,
    scope_verbs: Optional[list],
    assigned_by: int,
    *,
    round: Optional[int] = None,
    training: Optional[bool] = None,
) -> bool:
    """新建一条任务分配（assignments 表；规范 §3 之外的补充函数，签名经任务方确认）。

    Args:
        assignee_id: 被分配人 id（users.id，须已存在 —— FK 兜底）
        category: 范畴名（如 'motion'），非空字符串
        task_type: 'admission' | 'feature_coding' | 'alignment'
        scope_verbs: 动词范围。None = 全部动词；否则为动词名列表
            （如 ["run", "walk"]），存为 JSON
        assigned_by: 分配人 id（admin）
        round: 轮次（第几轮标注；FX-20 试标轮）。None=正式轮不留痕（RV2-3：
            未设轮次=NULL，不用 0 冒充）；给值须 int 且 ≥1（bool 不算 int）。
            要求 assignments 已含 round 列（ensure_flow_tables 幂等迁移补齐）。
        training: 试标轮位（FX-20）。None=非试标轮不留痕；True/False 存 1/0
            （试标轮位=1 起）。round 是「第几轮」的计数，training 是「该轮是否
            试标」的位标记，两者独立留痕、互不替代。

    Returns:
        bool: 成功 True；参数非法 / assignee 不存在（FK 拒绝）/ 数据库错误 False
    """
    assignee = _as_int(assignee_id)
    admin = _as_int(assigned_by)
    if assignee is None or assignee <= 0 or admin is None or admin <= 0:
        logger.error(
            f"assign_task 拒绝非法 id: assignee_id={assignee_id!r}, assigned_by={assigned_by!r}"
        )
        return False
    if not isinstance(category, str) or not category.strip():
        logger.error("assign_task 拒绝空 category")
        return False
    if task_type not in TASK_TYPES:
        logger.error(f"assign_task 拒绝非法 task_type: {task_type!r}")
        return False
    # round/training 校验（FX-20）：非法值入口先拒，不进数据库。
    # bool 是 int 子类，须先排除 —— True 冒充轮次 1 是脏数据不是留痕。
    round_val: Optional[int]
    if round is None:
        round_val = None
    elif isinstance(round, bool) or not isinstance(round, int) or round < 1:
        logger.error(f"assign_task 拒绝非法 round（须 int 且 ≥1 或 None）: {round!r}")
        return False
    else:
        round_val = round
    training_val: Optional[int]
    if training is None:
        training_val = None
    elif isinstance(training, bool):
        training_val = 1 if training else 0
    else:
        logger.error(f"assign_task 拒绝非法 training（须 bool 或 None）: {training!r}")
        return False
    if scope_verbs is not None:
        if not isinstance(scope_verbs, (list, tuple)):
            logger.error(f"assign_task 拒绝非法 scope_verbs: {scope_verbs!r}")
            return False
        scope_verbs = [str(v) for v in scope_verbs]
        if not scope_verbs or any(not v.strip() for v in scope_verbs):
            logger.error("assign_task 拒绝空动词范围（空请传 None 表示全部动词）")
            return False
        scope_verbs_json: Optional[str] = json.dumps(scope_verbs, ensure_ascii=False)
    else:
        scope_verbs_json = None

    sql = (
        "INSERT INTO assignments "
        "(assignee_id, category, task_type, scope_verbs, assigned_by, `round`, training) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                sql,
                (assignee, category, task_type, scope_verbs_json, admin,
                 round_val, training_val),
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        # 含 FK 违反（assignee/assigned_by 用户不存在，errno 1452）
        logger.error(f"创建任务分配失败（assignee={assignee}）: {e}")
        return False
    except Exception as e:
        logger.error(f"创建任务分派意外错误（assignee={assignee}）: {e}")
        return False


# ============================================
# 分配进度统计
# ============================================
def get_assignment_stats() -> List[Dict[str, Any]]:
    """每标注员 / 每任务类型的标注进度（admin 分配页 + reviewer 概览用）。

    以 assignments 的每一行为基准（谁被分配了什么任务），LEFT JOIN 该人在
    (category, task_type) 上的提交计数；另把「有提交但没被分配过」的组合补在
    后面（assignment_id/assignment_status/assigned_by 为 None，自发表情况）。

    Returns:
        list[dict]::

            [{"assignment_id": int|None, "assignee_id": int,
              "username": str|None, "display_name": str|None,
              "category": str, "task_type": str,
              "assignment_status": 'open'|'in_progress'|'submitted'|'closed'|None,
              "scope_verbs": list|None, "assigned_by": int|None,
              "round": int|None, "training": bool|None,
              "n_submitted": int, "n_adjudicated": int}]

        round/training 为 FX-20 试标轮两列（NULL=未设轮次/非试标，RV2-3 留痕列
        NULL 口径；assignments 表未迁移补列时键仍存在、值为 None）。孤儿行
        （有提交无分派）两键为 None。数据库不可用返回 []。
    """
    assignments_sql = (
        "SELECT a.id AS assignment_id, a.assignee_id, a.category, a.task_type, "
        "a.status AS assignment_status, a.scope_verbs, a.assigned_by, "
        "a.`round` AS round, a.training, "
        "u.username, u.display_name, "
        "COALESCE(t.n_submitted, 0) AS n_submitted, "
        "COALESCE(t.n_adjudicated, 0) AS n_adjudicated "
        "FROM assignments a "
        "LEFT JOIN users u ON u.id = a.assignee_id "
        "LEFT JOIN ("
        "  SELECT coder_id, category, task_type, "
        "         SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END) AS n_submitted, "
        "         SUM(CASE WHEN status = 'adjudicated' THEN 1 ELSE 0 END) AS n_adjudicated "
        "  FROM annotation_submissions "
        "  GROUP BY coder_id, category, task_type"
        ") t ON t.coder_id = a.assignee_id AND t.category = a.category "
        "AND t.task_type = a.task_type "
        "ORDER BY a.assignee_id, a.category, a.task_type, a.id"
    )
    # 有提交但没有任何对应分配的（自发表）：也纳入进度视图，分配字段留空
    orphan_sql = (
        "SELECT s.coder_id AS assignee_id, s.category, s.task_type, "
        "SUM(CASE WHEN s.status = 'submitted' THEN 1 ELSE 0 END) AS n_submitted, "
        "SUM(CASE WHEN s.status = 'adjudicated' THEN 1 ELSE 0 END) AS n_adjudicated, "
        "u.username, u.display_name "
        "FROM annotation_submissions s "
        "LEFT JOIN users u ON u.id = s.coder_id "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM assignments a "
        "  WHERE a.assignee_id = s.coder_id AND a.category = s.category "
        "  AND a.task_type = s.task_type"
        ") "
        "GROUP BY s.coder_id, s.category, s.task_type, u.username, u.display_name "
        "ORDER BY s.coder_id, s.category, s.task_type"
    )
    stats: List[Dict[str, Any]] = []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(assignments_sql)
            for row in cursor.fetchall():
                stats.append(
                    {
                        "assignment_id": int(row["assignment_id"]),
                        "assignee_id": int(row["assignee_id"]),
                        "username": row.get("username"),
                        "display_name": row.get("display_name"),
                        "category": row.get("category"),
                        "task_type": row.get("task_type"),
                        "assignment_status": row.get("assignment_status"),
                        "scope_verbs": _parse_json_list(row.get("scope_verbs")),
                        "assigned_by": (
                            int(row["assigned_by"]) if row.get("assigned_by") else None
                        ),
                        "round": _row_round(row),
                        "training": _row_training(row),
                        "n_submitted": int(row.get("n_submitted") or 0),
                        "n_adjudicated": int(row.get("n_adjudicated") or 0),
                    }
                )
            cursor.execute(orphan_sql)
            for row in cursor.fetchall():
                stats.append(
                    {
                        "assignment_id": None,
                        "assignee_id": int(row["assignee_id"]),
                        "username": row.get("username"),
                        "display_name": row.get("display_name"),
                        "category": row.get("category"),
                        "task_type": row.get("task_type"),
                        "assignment_status": None,
                        "scope_verbs": None,
                        "assigned_by": None,
                        "round": None,
                        "training": None,
                        "n_submitted": int(row.get("n_submitted") or 0),
                        "n_adjudicated": int(row.get("n_adjudicated") or 0),
                    }
                )
        return stats
    except pymysql.Error as e:
        logger.error(f"查询分配进度失败: {e}")
        return []
    except Exception as e:
        logger.error(f"查询分配进度意外错误: {e}")
        return []


# ============================================
# FX-20：分派台账读面 / 改派 / 试标轮 / 重标闭环（G2 修订→重标）
# ============================================
def list_assignments_admin(
    statuses: Optional[list] = None, limit: int = 200
) -> List[Dict[str, Any]]:
    """assignments 台账（词典管理员任务分配面板：改派/轮次徽章的数据源）。

    Args:
        statuses: 状态过滤清单（ASSIGNMENT_STATUSES 子集）；None=不过滤全量。
        limit: 返回条数上限（≤0 返回 []；防一次性拖全表），按 id 降序（最新在前）。

    Returns:
        list[dict]::

            [{"id", "assignee_id", "username", "display_name", "category",
              "task_type", "status", "scope_verbs"(list|None), "assigned_by",
              "round"(int|None), "training"(bool|None), "created_at"}]

        表未建 / 列未迁移（Unknown column）/ 库不可用返回 []（页面按空台账
        降级渲染，不崩）。审计口径：本函数只读，写路径在 reassign_assignment。
    """
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        return []
    if lim <= 0:
        return []
    sql = (
        "SELECT a.id, a.assignee_id, a.category, a.task_type, a.status, "
        "a.scope_verbs, a.assigned_by, a.`round` AS round, a.training, "
        "a.created_at, u.username, u.display_name "
        "FROM assignments a LEFT JOIN users u ON u.id = a.assignee_id"
    )
    params: list = []
    if statuses:
        clean = [s for s in statuses if s in ASSIGNMENT_STATUSES]
        if not clean:
            return []
        sql += " WHERE a.status IN (" + ", ".join(["%s"] * len(clean)) + ")"
        params.extend(clean)
    sql += " ORDER BY a.id DESC LIMIT %s"
    params.append(lim)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = []
            for row in cursor.fetchall():
                item = dict(row)
                item["scope_verbs"] = _parse_json_list(item.get("scope_verbs"))
                item["round"] = _row_round(item)
                item["training"] = _row_training(item)
                rows.append(item)
            return rows
    except pymysql.Error as e:
        # 含表未建 / round 列未迁移（errno 1054 Unknown column）：按空台账降级
        logger.error(f"查询分派台账失败: {e}")
        return []
    except Exception as e:
        logger.error(f"查询分派台账意外错误: {e}")
        return []


def _require_assignment_actor(actor: Any, action: str) -> None:
    """改派/重标的数据层直调面权限闸（FX-20；与 save_adjudication 同族口径）。

    keyword ``actor=None`` = 系统作业（迁移等）；页面调用点**必须**传
    ``actor=当前会话用户``。actor 为 dict 时其有效六角色须含词典管理员面
    （dict_admin / sys_admin —— 规范 §8：任务分配/改派/轮次是词典管理员职责，
    与页面 guards.require_dict_admin 入口同一判定实现
    users_db.effective_six_roles），不足抛 PermissionError；其余类型 fail-closed
    同抛。抛出发生在调用方的 try 之前，不落入返回值口径。
    """
    if actor is None:
        return  # 系统作业（docstring 口径：页面调用点必须传 actor）
    if isinstance(actor, dict):
        effective = effective_six_roles(actor)
        if effective & {"dict_admin", "sys_admin"}:
            return
        raise PermissionError(
            f"{action}被拒绝：当前用户（{actor.get('username', '?')}）有效角色集"
            "不含 dict_admin —— 任务分配/改派/轮次仅词典管理员可执行"
            "（数据层直调面口径：页面调用点必须传 actor=当前会话用户；"
            "None=系统作业）。"
        )
    raise PermissionError(
        f"{action}被拒绝：actor 须为会话用户 dict 或 None（系统作业）。"
    )


def reassign_assignment(
    assignment_id: int,
    project_id: int,
    new_assignee_id: int,
    reassigned_by: int,
    *,
    actor: Any = None,
) -> bool:
    """改派一条分派（assignments.assignee_id 换人；FX-20 改派入口的数据层）。

    闸门（全部通过才写库，任一拒绝返回 False 并记日志）：
      1. actor 权限闸（_require_assignment_actor：dict_admin/sys_admin；
         None=系统作业，页面调用点必须传会话用户）；
      2. 状态闸：status ∈ REASSIGNABLE_ASSIGNMENT_STATUSES（'open'）——
         规范 §8「改派仅限 draft/rejected」以码为准的映射，见常量注释；
      3. 非当前承包人闸：new_assignee ≠ 现承包人（换人不是重复指派）；
      4. 调用方所选项目在册闸（RV13-4 措辞降格）：new_assignee 须在**调用方
         所选** project_id 的 project_members 在册且账号在用（users.active=1）
         —— assignments 无项目列，「任务所属项目」语义待阶段 2 补列后建立；
         dict_admin 全局可信角色下风险有界（管理员本可经 collab_pages 对任意
         项目分派，本闸不新增也收不走其合法面）；
      5. 留痕一致性（RV13-5）：reassigned_by 须与 actor["id"] 一致（as_int
         清洗后比对）—— 数据层直调面收口：留痕只能是自己，不接受「A 会话
         落 B 的名」；actor=None 系统作业面不受此限（此时入参即留痕来源）；
      6. 原子并发守卫（RV13-2/RV14-6）：单条 UPDATE ... WHERE id=%s AND
         status=%s AND assignee_id=%s AND EXISTS(项目在册在用复验) —— 在册
         校验从「读后写」收敛为与写库原子复验，消除读↔写窗口的 TOCTOU；
         assignee_id 前值复验消除并发改派的静默覆盖与审计前值失真。
         rowcount=0 时重读行归因（状态已推进 / 承包人已被并发改派（含同值
         重放）/ 目标已失格 / 行已删除），日志如实。

    原承包人在途保护沿用 org_db.remove_member 的既有纪律口径：本函数只换
    assignments.assignee_id（assigned_by 同步为执行改派的管理员，台账「当前
    分派人」如实），**不动** project_members（原承包人在该项目的其他在途
    任务与成员资格不受影响）。

    审计：成功改派写结构化日志（谁改的/原→新承包人/分派 id/项目 id），
    logger.info 级别供运维回溯（本表无专用审计列，遵循「改研究方案的进文件，
    改运营状态的进界面」——留痕走日志，与 collab_pages 创建分派同口径）。

    Args:
        assignment_id: 分派 id
        project_id: 改派目标校验用项目 id（assignments 无项目列，项目上下文
            由调用方提供 —— 页面传当前所选项目）
        new_assignee_id: 新承包人 users.id
        reassigned_by: 执行改派的词典管理员 users.id（须等于 actor["id"]，
            见闸 5）
        actor: 会话用户 dict（页面传当前用户）| None（系统作业）

    Returns:
        bool: 改派成功 True；分派不存在 / 状态闸不过 / 目标非法（非在册、
        同人）/ 留痕不一致（RV13-5）/ 并发守卫未命中 / 数据库错误 False

    Raises:
        PermissionError: actor 为低权 dict / 非 dict 垃圾值（入口先抛）。
    """
    _require_assignment_actor(actor, "改派任务分派")
    aid = _as_int(assignment_id)
    pid = _as_int(project_id)
    new_uid = _as_int(new_assignee_id)
    by_id = _as_int(reassigned_by)
    if aid is None or aid <= 0 or pid is None or pid <= 0:
        logger.error(
            f"reassign_assignment 拒绝非法 id: assignment_id={assignment_id!r}, "
            f"project_id={project_id!r}"
        )
        return False
    if new_uid is None or new_uid <= 0 or by_id is None or by_id <= 0:
        logger.error(
            f"reassign_assignment 拒绝非法 id: new_assignee_id={new_assignee_id!r}, "
            f"reassigned_by={reassigned_by!r}"
        )
        return False
    # 闸 5（RV13-5）：留痕执行人与会话 actor 一致性 —— 留痕只能是自己。
    # actor 已过 _require_assignment_actor（dict 或 None）；dict 缺合法 id
    # 视为不一致（fail-closed，不猜）。
    if actor is not None:
        actor_id = _as_int(actor.get("id"))
        if actor_id is None or actor_id != by_id:
            logger.error(
                f"改派拒绝：reassigned_by（user {by_id}）与会话用户 "
                f"actor['id']（{actor_id!r}）不一致 —— "
                "留痕只能是自己（RV13-5）；系统作业请传 actor=None"
            )
            return False

    select_sql = (
        "SELECT id, assignee_id, status, category, task_type "
        "FROM assignments WHERE id = %s"
    )
    member_sql = (
        "SELECT COUNT(*) AS n FROM project_members pm "
        "JOIN users u ON u.id = pm.user_id "
        "WHERE pm.project_id = %s AND pm.user_id = %s AND u.active = 1"
    )
    # 原子并发守卫（RV13-2/RV14-6）：status + assignee_id 前值 + 项目在册在用
    # EXISTS 三重复验与写库同语句原子执行（读后写窗口的 TOCTOU 收口）；
    # SET assigned_by 同步为执行改派的管理员（台账「当前分派人」如实）。
    # 注：reviewer 建议文本含 updated_at=NOW()，assignments 无该列（DDL 仅
    # created_at），按实际表结构核对后不落此列。
    update_sql = (
        "UPDATE assignments SET assignee_id = %s, assigned_by = %s "
        "WHERE id = %s AND status = %s AND assignee_id = %s "
        "AND EXISTS ("
        "SELECT 1 FROM project_members pm "
        "JOIN users u ON u.id = pm.user_id "
        "WHERE pm.project_id = %s AND pm.user_id = %s AND u.active = 1)"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(select_sql, (aid,))
            row = cursor.fetchone()
            if not row:
                logger.error(f"改派拒绝：分派 #{aid} 不存在")
                return False
            current_assignee = _as_int(row.get("assignee_id"))
            status = row.get("status")
            if status not in REASSIGNABLE_ASSIGNMENT_STATUSES:
                logger.error(
                    f"改派拒绝：分派 #{aid} 状态为 {status!r}"
                    f"（仅 {REASSIGNABLE_ASSIGNMENT_STATUSES} 可改派 —— 规范"
                    "「改派仅限 draft/rejected」以码为准的映射，见常量注释）"
                )
                return False
            if current_assignee is not None and new_uid == current_assignee:
                logger.error(
                    f"改派拒绝：新承包人（user {new_uid}）与分派 #{aid} 现承包人相同"
                )
                return False
            cursor.execute(member_sql, (pid, new_uid))
            member_row = cursor.fetchone()
            if int((member_row or {}).get("n") or 0) <= 0:
                logger.error(
                    f"改派拒绝：user {new_uid} 不是项目 {pid} 在册在用成员"
                    "（project_members 校验不过）"
                )
                return False
            cursor.execute(update_sql, (new_uid, by_id, aid, status,
                                        current_assignee, pid, new_uid))
            if cursor.rowcount <= 0:
                reason = _reassign_miss_reason(
                    cursor, aid, status, current_assignee, pid, new_uid
                )
                logger.error(f"改派失败：分派 #{aid} {reason}")
                return False
            logger.info(
                f"改派审计：分派 #{aid}（{row.get('category')}/"
                f"{row.get('task_type')}，状态 {status}）承包人 "
                f"{current_assignee} → {new_uid}，执行人 user {by_id}，"
                f"项目 {pid}，actor={getattr(actor, 'get', lambda k: None)('username')}"
            )
            return True
    except pymysql.Error as e:
        logger.error(f"改派失败（assignment={aid}, project={pid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"改派意外错误（assignment={aid}, project={pid}）: {e}")
        return False


def _reassign_miss_reason(
    cursor, aid: int, expected_status: Any, prev_assignee: Optional[int],
    pid: int, new_uid: int,
) -> str:
    """改派 UPDATE rowcount=0 的归因（RV13-2/RV14-6：0 行不只一种，日志如实）。

    重读行尽力区分四种 0 行：状态已并发推进 / 承包人已被并发改派（含同值
    重放 —— 他人已完成本次改派）/ 目标已失格（并发移出项目或账号停用，
    EXISTS 复验未命中）/ 行面未变但并发更新窗口仍存在（兜底文案）。重读
    本身失败时归因降级为兜底文案，不掩盖原始失败。
    """
    fallback = "分派已被并发更新（含同值重放）"
    try:
        cursor.execute(
            "SELECT status, assignee_id FROM assignments WHERE id = %s", (aid,)
        )
        row = cursor.fetchone()
    except Exception:  # noqa: BLE001 —— 归因尽力而为，失败走兜底文案
        return fallback
    if not row:
        return "分派不存在（已被并发删除）"
    now_status = row.get("status")
    now_assignee = _as_int(row.get("assignee_id"))
    if now_status != expected_status:
        return (
            f"状态已并发推进为 {now_status!r}（乐观守卫未命中，"
            "仅 open 可改派）"
        )
    if now_assignee is not None and now_assignee != prev_assignee:
        if now_assignee == new_uid:
            return "已被并发完成同值改派（同值重放，本次未重复写）"
        return (
            f"承包人已被并发改派为 user {now_assignee}"
            "（前值复验未命中，未覆盖他人变更）"
        )
    # 行面（状态/承包人）未变 → 目标成员资格复验（区分「目标已失格」0 行）
    try:
        cursor.execute(
            "SELECT COUNT(*) AS n FROM project_members pm "
            "JOIN users u ON u.id = pm.user_id "
            "WHERE pm.project_id = %s AND pm.user_id = %s AND u.active = 1",
            (pid, new_uid),
        )
        member_row = cursor.fetchone()
        if int((member_row or {}).get("n") or 0) <= 0:
            return "目标已失格（并发移出项目或账号停用，在册复验未命中）"
    except Exception:  # noqa: BLE001 —— 归因尽力而为
        pass
    return fallback


_DIVIDED_COLS_ENSURED = False


def _ensure_divided_cols() -> None:
    """list_divided_senses 读 cs_senses.merged_into —— 列由 cluster_analysis 的
    分立迁移负责（页面/分析路径触发）；本读面（驾驶舱台账）可能先于其被调，
    故自行做一次幂等补列（进程级哨兵直通；失败仅记日志，查询路径照旧容错）。
    ALTER 捕 MySQL 1060（并发首启另一进程已补列）视为幂等成功置哨兵（RV14-4，
    与 _migrate_assignments_round_columns 同款处理）。"""
    global _DIVIDED_COLS_ENSURED
    if _DIVIDED_COLS_ENSURED:
        return
    try:
        with get_db_cursor() as cursor:
            if not _column_exists(cursor, "cs_senses", "merged_into"):
                try:
                    cursor.execute(
                        "ALTER TABLE cs_senses ADD COLUMN merged_into INT NULL "
                        "AFTER status"
                    )
                    logger.info("cs_senses.merged_into 列已补齐（FX-20 台账读面迁移）")
                except pymysql.Error as e:
                    if not _is_dup_column_error(e):
                        raise
                    logger.info(
                        "cs_senses.merged_into 已由并发进程补齐"
                        "（MySQL 1060，幂等自愈，RV14-4）"
                    )
        _DIVIDED_COLS_ENSURED = True
    except Exception as e:  # noqa: BLE001 —— 表未建/库不可用由查询路径如实降级
        logger.warning(f"cs_senses.merged_into 迁移探测失败（list_divided_senses）: {e}")


def list_divided_senses(limit: int = 200) -> List[Dict[str, Any]]:
    """分立复核已裁决义位清单（cs_senses.status ∈ merged/split；G2 重标入口证据面）。

    只读；表未建 / merged_into 列未迁移 / 库不可用返回 []（页面按「尚无裁决」
    降级，不编数）。裁决落地写点在 cluster_analysis.execute_sense_division
    （本模块只读消费，不越权）。
    """
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        return []
    if lim <= 0:
        return []
    sql = (
        "SELECT id, sense_no, sense_label, status, merged_into "
        "FROM cs_senses WHERE status IN (%s, %s) ORDER BY id LIMIT %s"
    )
    _ensure_divided_cols()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (*DIVIDED_SENSE_STATUSES, lim))
            rows = []
            for row in cursor.fetchall():
                item = dict(row)
                merged_into = _as_int(item.get("merged_into"))
                item["merged_into"] = merged_into if merged_into and merged_into > 0 else None
                rows.append(item)
            return rows
    except pymysql.Error as e:
        logger.error(f"查询已裁决义位失败（cs_senses）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询已裁决义位意外错误（cs_senses）: {e}")
        return []


def _resolve_study_code(category: str) -> Optional[str]:
    """范畴参数 → 语义分析 categories.code（FX-20 重标闸用；与 sense_spine
    _study_code_for 同口径的独立实现 —— annotation_flow 不 import sense_spine
    （它 import 本模块，反向会成环），PACK_TO_STUDY_CODE 包名映射**懒导入**
    cluster_analysis（调用时才 import，模块加载序无环）。"""

    def _query(code: str) -> Optional[str]:
        """按 code 查 categories 表：存在返回原 code，不存在返回 None（fx5 契约：全函数 docstring）。"""
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT code FROM categories WHERE code = %s LIMIT 1", (code,)
            )
            row = cursor.fetchone()
            return str(row["code"]) if row else None

    cat = str(category or "").strip()
    if not cat:
        return None
    try:
        direct = _query(cat)
    except Exception as e:  # noqa: BLE001 —— categories 表未建/库不可用按未解析
        logger.warning(f"categories 直配查询失败（{cat}）: {e}")
        direct = None
    if direct:
        return direct
    try:
        # 懒导入：cluster_analysis 是页面/分析层模块，模块顶层 import 会拖重
        # 依赖（streamlit 等）且有环风险；仅此处按需取包名映射。
        from src.cluster_analysis import PACK_TO_STUDY_CODE

        mapped = PACK_TO_STUDY_CODE.get(cat.lower())
        if not mapped:
            return None
        return _query(mapped)
    except ImportError:
        logger.warning("cluster_analysis.PACK_TO_STUDY_CODE 不可用，包名映射跳过")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"categories 包名映射查询失败（{cat}）: {e}")
        return None


# 标注侧 sense_id（oald_senses.id）→ cs_senses 状态的裁决闸查询（FX-20）。
# 映射键与 sense_spine._find_cs_sense_id 同口径：(categories.code, language='en',
# cs_lexemes.lemma=o.headword, cs_senses.sense_no=str(o.sense_index))；
# sense_no 直接用 CAST(o.sense_index AS CHAR) 在 JOIN 条件内解析（免先读行再
# 二次查询），多命中取最小 id（确定性，与 _find_cs_sense_id 一致）。
#
# FX-45 RV19-1 消缺后，create_reannotation_tasks 的闸核对改走下方
# _CS_STATUS_BATCH_SQL 单条 IN 查询（N 次往返 → 1 条）；本语句保留作
# **逐义位等价性对照基准**（test_fx45_fixes 用同一数据集断言两种实现
# 同输出）——批量语句的 JOIN 键须与本语句逐字一致，改动任一侧都必须
# 重跑该等价性测试。
_CS_STATUS_SQL = (
    "SELECT s.status AS cs_status "
    "FROM oald_senses o "
    "JOIN cs_lexemes l ON l.language = 'en' AND l.lemma = o.headword "
    "JOIN categories c ON c.id = l.category_id AND c.code = %s "
    "JOIN cs_senses s ON s.lexeme_id = l.id "
    "AND s.sense_no = CAST(o.sense_index AS CHAR) COLLATE utf8mb4_unicode_ci "
    "WHERE o.id = %s "
    "ORDER BY s.id LIMIT 1"
)

# 批量裁决闸查询（FX-45 任务 2，RV19-1 留档项消缺）：JOIN 键与
# _CS_STATUS_SQL 逐字一致（同一映射口径），WHERE o.id IN (placeholders)
# 一次取整批；ORDER BY s.id 全序下每个 sense_id 的行子序列仍按
# cs_senses.id 升序，Python 侧按首次出现取状态 = 原逐条
# ``ORDER BY s.id LIMIT 1``（多命中取最小 cs_senses.id）的等价实现。
_CS_STATUS_BATCH_SQL = (
    "SELECT o.id AS sense_id, s.status AS cs_status "
    "FROM oald_senses o "
    "JOIN cs_lexemes l ON l.language = 'en' AND l.lemma = o.headword "
    "JOIN categories c ON c.id = l.category_id AND c.code = %s "
    "JOIN cs_senses s ON s.lexeme_id = l.id "
    "AND s.sense_no = CAST(o.sense_index AS CHAR) COLLATE utf8mb4_unicode_ci "
    "WHERE o.id IN ({placeholders}) "
    "ORDER BY s.id"
)


def _fetch_cs_status_map(study_code: str, sense_ids: List[int]) -> Dict[int, Any]:
    """单条 IN 查询取逐义位裁决状态（FX-45 任务 2；原逐义位单发的批量化）。

    映射口径与 _CS_STATUS_SQL 逐字一致（同一 JOIN 键）；多命中取最小
    cs_senses.id（与原 ORDER BY s.id LIMIT 1 语义一致，确定性同
    sense_spine._find_cs_sense_id）。

    Args:
        study_code: 语义分析研究代号（categories.code，_resolve_study_code 解析）
        sense_ids: 标注侧义位 id 清单（oald_senses.id，调用方已去重清洗）

    Returns:
        dict: sense_id → cs_status 原始值（状态判定交调用方）。
        **未映射的 sense_id 不入键**（与原「fetchone() is None → 未映射」
        分支对齐 —— 调用方须用 ``in`` 判存在，不能用 .get() 把「未映射」
        与「状态为 NULL」混淆）。查询失败向上抛（create_reannotation_tasks
        外层 fail-closed 口径不变）。
    """
    if not sense_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(sense_ids))
    status_map: Dict[int, Any] = {}
    with get_db_cursor() as cursor:
        cursor.execute(
            _CS_STATUS_BATCH_SQL.format(placeholders=placeholders),
            (study_code, *sense_ids),
        )
        for row in cursor.fetchall():
            key = _as_int(row.get("sense_id"))
            # ORDER BY s.id 下同 sense_id 的首行即最小 cs_senses.id —— 后续
            # 行（更大 id）不覆盖首行（多命中取最小 id，与逐条 LIMIT 1 一致）。
            if key is None or key in status_map:
                continue
            status_map[key] = row.get("cs_status")
    return status_map


def create_reannotation_tasks(
    category: str,
    sense_ids: list,
    round: int,
    assigned_by: int,
    *,
    actor: Any = None,
    task_type: str = "feature_coding",
) -> Dict[str, Any]:
    """G2「修订→重标」闭环：对已裁决 merged/split 的义位发起重标（FX-20）。

    语义（最小诚实闭环）：
      * ``round`` = 被裁决失效的**当前轮次**（int ≥1）；函数创建 round+1 的
        重标任务（旧轮提交**原样保留作历史**，annotation_submissions 零写入
        —— status 仅 submitted/adjudicated 两态，不造「失效」第三态）；
      * 受影响义位闸：逐义位把**标注侧 sense_id**（annotation_submissions.
        sense_id = oald_senses.id 空间）经 (categories.code, cs_lexemes.lemma=
        o.headword, cs_senses.sense_no=str(o.sense_index)) 映射到 cs_senses，
        状态须 ∈ DIVIDED_SENSE_STATUSES（merged/split）—— 未裁决/映射不上的
        义位跳过并列明，绝不带病建任务；
      * 重标任务派给**该批义位的历史标注人且账号在用**（RV13-3：
        annotation_submissions DISTINCT coder_id JOIN users u ON u.active=1，
        停用账号排除）；复核口径如实声明——复核=账号在用；**项目在册不可
        建立**（assignments 无项目列），口径与改派面一致降级（闸 4 口径见
        reassign_assignment docstring）；无历史提交的义位不产生任务（如实返回）；
      * 同轮幂等闸（RV14-1）：落库前按 (category, task_type, assignee_id,
        round) 探测 assignments 已存在行（探测条件 ``round IS NOT NULL AND
        round=%s``，round 为 NULL 的正式轮行不受影响），存在即跳过该标注人
        并计入返回体 ``dedup`` —— 页面重复发起不再翻倍；
      * 留痕一致性（RV13-5）：assigned_by 须与 actor["id"] 一致（as_int 清洗
        后比对）—— 留痕只能是自己；actor=None 系统作业面不受此限（此时
        入参即留痕来源）；
      * scope_verbs = 受影响义位的 headword 集合（正确使用动词范围语义，
        不把 sense_id 塞进 scope —— FX-15 口径：scope 语义不动）；义位查不到
        headword 时 None=全部动词（页面灰注如实说明）；
      * training 恒为 None（重标是正式轮，试标位留给试标分派）。

    **落库点挂钩待接线**：分立复核裁决落地写点在 cluster_analysis.
    execute_sense_division（merge/split 写 cs_senses，非本模块所有权文件），
    本函数是裁决后的重标消费口 —— 建议接线位置：adjudicate_sense_division
    的 adopted 分支（decide 留痕与 execute_sense_division 落地成功后）按
    proposal["sense_ids"] 调本函数（actor=裁决人会话用户，None 兜底系统作业）。
    当前由词典管理员在「任务分配」tab 的「发起重标」入口手工触发，闸门保证
    只有已裁决义位可发。

    Args:
        category: 范畴名（包名 motion 或研究代号 RUN，经 _resolve_study_code 解析）
        sense_ids: 受影响义位 id 清单（标注侧 oald_senses.id；去重保序）
        round: 被裁决失效的当前轮次（int ≥1；任务建在 round+1）
        assigned_by: 发起重标的词典管理员 users.id
        actor: 会话用户 dict（页面传当前用户）| None（系统作业）
        task_type: 重标任务类型（默认 feature_coding=工序5 特征标注重标；
            须 ∈ TASK_TYPES）

    Returns:
        dict::

            {"ok": bool, "reannotation_round": int, "created": int,
             "dedup": int, "failed_coder_ids": [...],
             "eligible_sense_ids": [...], "skipped": [{"sense_id", "reason"}, ...],
             "coder_ids": [...], "note": str|None, "error": str|None}

        ok=True 时 created=成功建出的任务数、dedup=按同轮幂等闸跳过的标注人
        数（RV14-1）；error 只在 ok=False 时非空。
        actor 低权直接抛 PermissionError（入口先抛，同 save_adjudication）。
    """
    _require_assignment_actor(actor, "发起重标（G2 修订→重标闭环）")
    if not isinstance(category, str) or not category.strip():
        return {"ok": False, "error": "范畴名为空", "created": 0}
    if task_type not in TASK_TYPES:
        return {
            "ok": False,
            "error": f"非法 task_type: {task_type!r}（须为 {TASK_TYPES} 之一）",
            "created": 0,
        }
    # RV19-1：批量义位上限（防 10000 id 触发逐义位闸核对往返＋巨型 IN＋日志洪流）
    REANNOTATION_MAX_SENSE_IDS = 500
    dedup_ids = list(dict.fromkeys(
        sid for sid in (sense_ids or [])
        if isinstance(sid, int) and not isinstance(sid, bool) and sid > 0
    )) if isinstance(sense_ids, list) else []
    if len(dedup_ids) > REANNOTATION_MAX_SENSE_IDS:
        return {
            "ok": False,
            "error": (f"sense_ids 批量超限（{len(dedup_ids)} > "
                      f"{REANNOTATION_MAX_SENSE_IDS}）——分批发起"),
            "created": 0,
        }
    if isinstance(round, bool) or not isinstance(round, int) or round < 1:
        return {
            "ok": False,
            "error": f"非法 round（须 int 且 ≥1，= 被失效的当前轮次）: {round!r}",
            "created": 0,
        }
    admin = _as_int(assigned_by)
    if admin is None or admin <= 0:
        return {"ok": False, "error": f"非法 assigned_by: {assigned_by!r}", "created": 0}
    # 留痕一致性（RV13-5）：assigned_by 与会话 actor["id"] 一致 —— 留痕只能
    # 是自己；actor=None 系统作业面不受此限（此时入参即留痕来源）。
    if actor is not None:
        actor_id = _as_int(actor.get("id"))
        if actor_id is None or actor_id != admin:
            return {
                "ok": False,
                "error": (
                    f"assigned_by（user {admin}）与会话用户 actor['id']"
                    f"（{actor_id!r}）不一致 —— 留痕只能是自己（RV13-5）；"
                    "系统作业请传 actor=None"
                ),
                "created": 0,
            }
    ids: List[int] = []
    for raw in (sense_ids if isinstance(sense_ids, (list, tuple)) else []):
        value = _as_int(raw)
        if value is None or value <= 0:
            return {"ok": False, "error": f"非法 sense_id: {raw!r}", "created": 0}
        if value not in ids:
            ids.append(value)
    if not ids:
        return {"ok": False, "error": "sense_ids 为空", "created": 0}

    new_round = round + 1
    skipped: List[Dict[str, Any]] = []
    try:
        study_code = _resolve_study_code(category)
        if not study_code:
            return {
                "ok": False,
                "error": (
                    f"范畴 {category!r} 无法解析到语义分析研究代号（categories "
                    "未灌数据或包名未登记）—— 重标闸无法核对分立裁决，未创建任务"
                ),
                "created": 0,
            }
        # 逐义位裁决闸（映射 oald_senses.id → cs_senses.status）：FX-45 任务 2
        # （RV19-1 留档项消缺）改单条 IN 查询（N 次往返 → 1 条，500 上限内
        # 占位符可控）；映射口径与 _CS_STATUS_SQL 逐字一致，多命中取最小
        # cs_senses.id —— 每 sense_id 的裁决判定与原逐条查询等价
        # （test_fx45_fixes 同数据集对照锁定）。
        eligible: List[int] = []
        status_map = _fetch_cs_status_map(study_code, ids)
        for sid in ids:
            if sid not in status_map:
                skipped.append({
                    "sense_id": sid,
                    "reason": "未映射到语义分析义位（cs_senses），无法核对分立裁决",
                })
                continue
            cs_status_raw = status_map[sid]
            status = str(cs_status_raw or "").strip().lower()
            if status not in DIVIDED_SENSE_STATUSES:
                skipped.append({
                    "sense_id": sid,
                    "reason": f"cs_senses 状态为 {cs_status_raw!r}"
                    "（非 merged/split），未裁决或维持原分立",
                })
                continue
            eligible.append(sid)
        if not eligible:
            return {
                "ok": False,
                "error": "所选义位均未通过分立裁决闸（仅 merged/split 可重标）",
                "created": 0,
                "skipped": skipped,
                "reannotation_round": new_round,
            }
        with get_db_cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(eligible))
            # 历史标注人复核（RV13-3）：JOIN users 过滤停用账号（u.active=1）。
            # 项目在册复核不可建立 —— assignments 无项目列，口径与改派面一致
            # 降级为「账号在用」（docstring 已如实声明）。
            cursor.execute(
                "SELECT DISTINCT coder_id FROM annotation_submissions "
                "JOIN users u ON u.id = coder_id AND u.active = 1 "
                f"WHERE category = %s AND task_type = %s AND sense_id IN ({placeholders}) "
                "ORDER BY coder_id",
                (category, task_type, *eligible),
            )
            coder_ids = [_as_int(r["coder_id"]) for r in cursor.fetchall()]
            coder_ids = [c for c in coder_ids if c is not None and c > 0]
            if not coder_ids:
                return {
                    "ok": True,
                    "reannotation_round": new_round,
                    "created": 0,
                    "dedup": 0,
                    "eligible_sense_ids": eligible,
                    "skipped": skipped,
                    "coder_ids": [],
                    "note": (
                        "受影响义位无历史标注提交，未创建重标任务"
                        "（如需指派请用试标轮分派表单）"
                    ),
                    "error": None,
                }
            cursor.execute(
                "SELECT DISTINCT headword FROM oald_senses "
                f"WHERE id IN ({placeholders}) AND headword IS NOT NULL",
                tuple(eligible),
            )
            verbs = [str(r["headword"]).strip() for r in cursor.fetchall()]
            verbs = [v for v in verbs if v]
            # 同轮幂等闸（RV14-1）：已存在同 (category, task_type, assignee_id,
            # round) 行的标注人跳过 —— 页面重复发起不再翻倍。探测条件
            # ``round IS NOT NULL AND round=%s``：round 为 NULL 的正式轮行
            # （RV2-3 未设轮次）不受影响。探测失败随外层闸核对一起 fail-closed
            # （幂等性无法核实时不落库）。
            coder_placeholders = ", ".join(["%s"] * len(coder_ids))
            cursor.execute(
                "SELECT DISTINCT assignee_id FROM assignments "
                f"WHERE category = %s AND task_type = %s "
                f"AND assignee_id IN ({coder_placeholders}) "
                "AND `round` IS NOT NULL AND `round` = %s",
                (category, task_type, *coder_ids, new_round),
            )
            dup_ids = {_as_int(r["assignee_id"]) for r in cursor.fetchall()}
            dup_ids.discard(None)
    except pymysql.Error as e:
        logger.error(f"重标闸核对失败（category={category}）: {e}")
        return {"ok": False, "error": f"数据库错误: {e}", "created": 0}
    except Exception as e:
        logger.error(f"重标闸核对意外错误（category={category}）: {e}")
        return {"ok": False, "error": f"意外错误: {e}", "created": 0}

    scope_verbs = verbs if verbs else None
    failed: List[int] = []
    created = 0
    dedup = 0
    for coder in coder_ids:
        if coder in dup_ids:
            dedup += 1  # 同轮幂等闸（RV14-1）：已有同轮行，跳过不重复建
            continue
        if assign_task(
            coder, category, task_type, scope_verbs, admin,
            round=new_round, training=None,
        ):
            created += 1
        else:
            failed.append(coder)
    notes: List[str] = []
    if failed:
        notes.append("部分标注人建任务失败，详见服务端日志")
    if dedup:
        notes.append(f"{dedup} 名标注人本轮重标任务已存在（幂等跳过）")
    _brief = lambda seq, n=20: (seq[:n] + [f"…共{len(seq)}"] if len(seq) > n else seq)  # noqa: E731
    logger.info(
        f"重标审计：范畴 {category}/{task_type} 轮次 {round}→{new_round}，"
        f"义位 {_brief(eligible)}，历史标注人 {_brief(coder_ids)}，"
        f"建任务 {created} 条"
        f"（幂等跳过 {dedup}，失败 {failed}，跳过 {skipped}），"
        f"发起人 user {admin}，"
        f"actor={getattr(actor, 'get', lambda k: None)('username')}"
    )
    return {
        "ok": True,
        "reannotation_round": new_round,
        "created": created,
        "dedup": dedup,
        "failed_coder_ids": failed,
        "eligible_sense_ids": eligible,
        "skipped": skipped,
        "coder_ids": coder_ids,
        "note": "；".join(notes) or None,
        "error": None,
    }
