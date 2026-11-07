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

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（规范 §1/§2/§3）
# ============================================
TASK_TYPES = ("admission", "feature_coding", "alignment")

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


def _as_int(value: Any) -> Optional[int]:
    """宽容转 int（UI 层可能传来 str）；转不动返回 None。"""
    if isinstance(value, bool):  # bool 是 int 子类，但 id 不会是 bool
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    """JSON 列（scope_verbs / submission_ids）→ list；NULL → None；坏数据 → None。"""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            return None
    return None


# ============================================
# 建表
# ============================================
def ensure_flow_tables() -> None:
    """幂等创建 flow 三表：assignments / annotation_submissions / adjudications
    （规范 §2 DDL 原样，CREATE TABLE IF NOT EXISTS，可重复调用）。

    外键引用 users 与 oald_senses：集成时先调 ``users_db.ensure_user_tables()``
    （users 表为空还会得到内置 admin），并确保 ``mysql_db.init_database()`` 已建
    oald_senses。被引用表缺失时本函数只记 error 日志不抛异常（与
    users_db.ensure_user_tables 的容错口径一致），页面可继续渲染。
    """
    try:
        with get_db_cursor() as cursor:
            for ddl in _FLOW_TABLE_DDLS:
                cursor.execute(ddl)
    except pymysql.Error as e:
        logger.error(f"flow 表初始化失败（MySQL，检查 users/oald_senses 是否已建）: {e}")
    except Exception as e:
        logger.error(f"flow 表初始化意外错误: {e}")


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
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                sql,
                (
                    category,
                    sense,
                    task_type,
                    coder,
                    json.dumps(payload, ensure_ascii=False),
                    1 if ai_assisted else 0,
                ),
            )
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

    Args:
        sense_id: 义位 id；task_type: 任务类型
        adjudicator_id: 仲裁人 id（页面层须已做 reviewer/admin role gate）
        gold_payload: 定稿判定（结构同 submit_annotation 的 payload，先校验）
        submission_ids: 参与仲裁的提交 id 列表（允许空列表 = 无历史提交直接定稿）
        note: 仲裁说明（可为 None）

    Returns:
        bool: 成功 True；参数非法或数据库错误 False
    """
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
) -> bool:
    """新建一条任务分配（assignments 表；规范 §3 之外的补充函数，签名经任务方确认）。

    Args:
        assignee_id: 被分配人 id（users.id，须已存在 —— FK 兜底）
        category: 范畴名（如 'motion'），非空字符串
        task_type: 'admission' | 'feature_coding' | 'alignment'
        scope_verbs: 动词范围。None = 全部动词；否则为动词名列表
            （如 ["run", "walk"]），存为 JSON
        assigned_by: 分配人 id（admin）

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
        "INSERT INTO assignments (assignee_id, category, task_type, scope_verbs, assigned_by) "
        "VALUES (%s, %s, %s, %s, %s)"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (assignee, category, task_type, scope_verbs_json, admin))
            return cursor.rowcount > 0
    except pymysql.Error as e:
        # 含 FK 违反（assignee/assigned_by 用户不存在，errno 1452）
        logger.error(f"创建任务分配失败（assignee={assignee}）: {e}")
        return False
    except Exception as e:
        logger.error(f"创建任务分配意外错误（assignee={assignee}）: {e}")
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
              "n_submitted": int, "n_adjudicated": int}]

        数据库不可用返回 []。
    """
    assignments_sql = (
        "SELECT a.id AS assignment_id, a.assignee_id, a.category, a.task_type, "
        "a.status AS assignment_status, a.scope_verbs, a.assigned_by, "
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
