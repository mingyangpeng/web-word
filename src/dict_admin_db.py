"""词典管理数据层 —— 定制属性（EAV）与导入批次登记/回滚（Agent C）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D⑧ 词典项目域
（custom_fields / custom_values / import_batches 三表）与 §15（数据出入口纪律，
**导入同权**：批量灌库的业务数据操作仅词典管理员）；
契约：docs/spec/阶段1施工规范.md §3-C（本文件签名与之一致，不得擅改）。

是什么（三张表，平台架构设计规范 附录 A）：
  * custom_fields：项目定制**字段定义**（语域/教材分级/频级…）。applies_to
    声明字段挂在哪类锚上（word 词目 / sense 义位 / example 例证），value_type
    声明值的类型（text/number/enum/date/bool），enum 字段必须在定义时给出
    enum_values 白名单（JSON）。字段只有两态：active / deprecated（弃用，
    只停写不删行 —— 历史值要能一直展示，绝不物理删除）。
  * custom_values：定制属性**值**（EAV 中的 V）。锚 = (anchor_type, anchor_id)，
    UNIQUE(field_id, anchor_type, anchor_id) —— 一字段一锚一值，重复 set 即改值
    （upsert）。text/enum/date/bool 存 value_text，number 存 value_num。
  * import_batches：导入向导的**批次台账**（batch 审计线）。running → finished
    （记 rows_total/ok/rejected）→ rolled_back（按 revert_log 回滚）；
    成品词条内容模型的「定制属性区」与导入留痕都从这三表取数。
  * import_revert_log（批次 6-T 伴生表）：revert_log 的**持久化**存储 ——
    事件逐条落库（UNIQUE(batch_id, seq)），rollback_batch 无显式 revert_log
    时从本表读取，跨会话回滚成立（此前 revert_log 只暂存页面会话，会话
    丢失即不可回滚）。

数据链：
  导入向导（批次 2 页面）：start_batch 登记 → 逐行灌业务表（行级 revert_log 由
  调用方收集）→ finish_batch 记数 → persist_revert_log 把事件落伴生表 →
  出问题 rollback_batch 优先读伴生表回滚（显式传 revert_log 的旧口径不变）；
  定制属性页：define_field 建字段 → set_value 按锚写值 → get_values_for_anchor
  （词条装配「定制属性区」按锚取全值）→ query_anchors_by_field（按字段查值反查
  锚，浏览器筛选用）→ deprecate_field 弃用（存量值保留只读）。

**权限要求（平台架构设计规范 §15，导入同权 / 内容性操作同权）**：
  本模块全部业务数据写操作（define_field / deprecate_field / set_value /
  start_batch / finish_batch / rollback_batch）**仅词典管理员（dict_admin，
  项目内即 chief）可执行**；平台管理员不碰业务数据（只管系统与账号）。
  本期数据层不做角色判定 —— 中央闸门函数（require_dict_admin）由批次 2
  在页面/服务层接线拦截，数据层 docstring 标注口径以便核对。

required 语义（重要，见 custom_fields.required 列注释）：
  required 只是**声明**（批次 2 表单侧强制必填、缺值提示），数据层 set_value
  **不**因 required 拒绝空值、也不删除既有值 —— 表单强制是入口职责，
  数据层保持「存什么算什么」，避免表单逻辑泄漏进存储层。

回滚口径（rollback_batch 的 MVP 约定，docstring 详见函数注释）：
  * revert_log 两类动作：{action:'insert', table, row_id} → **软作废**
    （表有 status 列且枚举含 'deprecated' 才执行；表有 import_voided 列则
    置 import_voided=1 作废 —— R3-9c，definitions 词目层走此通道；两样都
    没有的表仅留痕不动行，MVP 不物理 DELETE，被作废行仍可审计追溯）；
    {action:'update', table, row_id, old_values} → 按 old_values **恢复旧值**
    （old_values 含 updated_at 时随逐列恢复一并 SET —— R3-9a，导入引擎
    落旧值，显式赋值优先于 ON UPDATE CURRENT_TIMESTAMP，回滚后行的时间戳
    回到导入前时点）；
  * revert_log 先整体校验、任一条非法整体拒绝（防半套回滚）；
  * revert_log 来源两态（批次 6-T）：显式传参 = 旧口径原样（向后兼容）；
    传 None = 从伴生表 import_revert_log 按批次读回（无记录如实拒绝）；
  * **混用仲裁（R3-1）**：伴生表已有该批次持久化事件时，显式传参不再原样
    放行 —— 显式空清单拒（与持久化日志矛盾）；显式非空但与持久化集不同
    拒（防架空持久化日志）；仅逐事件一致时放行。无持久化记录 → 显式传参
    现状不变；
  * persist_revert_log 批次状态守卫（R3-2）：running/finished 才可补写
    日志，rolled_back 拒（已回滚批次不可补写日志）；
  * 回滚动作写批次状态：成功后 status='rolled_back'（状态机见 rollback_batch）。

接口（契约 §3-C）：
  ensure_dict_admin_tables / define_field / deprecate_field / set_value /
  get_values_for_anchor / query_anchors_by_field / start_batch / finish_batch /
  rollback_batch
  批次 6-T 追加：persist_revert_log(batch_id, events)（revert_log 持久化，
  非契约签名 —— 仿 list_fields 的「非契约辅助」先例）
  另有只读辅助 list_fields / get_field（非契约签名，供批次 2 定制属性管理页
  列字段/看单字段 —— 仿 ai_ledger.get_proposal 的「非契约只读辅助」先例）。

降级：
  数据库不可用时读函数返回 []/None、写函数返回 0/False，均只记日志不抛异常
  （与 users_db/org_db/ai_ledger 容错口径一致）—— 页面可继续渲染降级提示，
  不整页崩掉。

安全规则（全体遵守）：
  1. SQL 一律参数化；**仅有的两处动态表名/列名**（rollback_batch 对 revert_log
     的 UPDATE）来自本模块常量正则 ^[A-Za-z0-9_]{1,64}$ 白名单 + information_schema
     存在性双重校验，值仍走占位符 —— 表名/列名绝不接受调用方原文拼 SQL；
  2. 入参在应用层先校验再入库（applies_to/value_type/枚举值/日期/布尔/编号
     非法根本不进数据库，不依赖 ENUM/JSON 报错）；
  3. 无 users 外键（created_by/updated_by/operator 为软引用），ensure 可独立
     先行建表，不依赖 users/dictionary_projects 是否已迁移。
"""

import json
import logging
import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pymysql

from src.db_utils import as_int as _as_int  # R6-4：公共小件单一实现点
from src.db_utils import table_exists as _table_exists
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（契约 §3-C 表设计原样枚举）
# ============================================
# applies_to：字段挂哪类锚（词目/义位/例证）。也是 custom_values.anchor_type
# 的合法集 —— 一个字段的值只能写在与 applies_to 同类的锚上（见 set_value）。
# R6-7：删 ANCHOR_TYPES 别名 —— 枚举只留 APPLIES_TO 一个名字（锚即
# applies_to；media_db 侧四锚枚举已改 MEDIA_ANCHOR_TYPES，调用点已同步）。
APPLIES_TO = ("word", "sense", "example")

# value_type：值类型五枚举。number → value_num，其余 → value_text（bool 规整 '1'/'0'）。
VALUE_TYPES = ("text", "number", "enum", "date", "bool")

# 字段状态：active 在用（可写值）；deprecated 弃用（存量值保留只读、拒新写）。
FIELD_STATUSES = ("active", "deprecated")

# 批次状态机：running（登记后灌库中）→ finished（记账完成，可回滚起点）
# → rolled_back（已按 revert_log 回滚）。终态，不可逆。
BATCH_STATUSES = ("running", "finished", "rolled_back")

# revert_log 合法动作（契约 §3-C rollback_batch 注释）。
REVERT_INSERT = "insert"   # 导入新增的行 → 软作废（MVP 口径见 rollback_batch docstring）
REVERT_UPDATE = "update"   # 导入覆盖过的行 → 按 old_values 恢复旧值
REVERT_ACTIONS = (REVERT_INSERT, REVERT_UPDATE)

# 动态标识符白名单（rollback_batch 的表名/列名校验；防 SQL 注入的第一道闸）。
# 第二道闸是 information_schema 存在性校验 —— 两道都过才允许拼接。
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

# 软作废写入的 status 值（与 FIELD_STATUSES、custom_fields 枚举同词）。
_SOFT_INVALIDATE_STATUS = "deprecated"

# 定制属性值的长度上限（字符）。value_text 是 TEXT 列（65535 **字节**），utf8mb4
# 下一个汉字 4 字节 —— 10000 字符的上限保证任何合法值都装得下，超长在入口拒
# 而不是等 MySQL 报 DataError。
MAX_VALUE_TEXT_LEN = 10000

# enum 字段的枚举值规模上限（MVP：白名单条目与单条长度，防滥用不必设死）。
MAX_ENUM_ITEMS = 200
MAX_ENUM_VALUE_LEN = 100

# 字段 code/name 长度（与列宽一致：VARCHAR(64) / VARCHAR(120)）。
MAX_FIELD_CODE_LEN = 64
MAX_FIELD_NAME_LEN = 120

# 批次文件名 / 目标域长度（与列宽一致）。
MAX_FILE_NAME_LEN = 255
MAX_TARGET_DOMAIN_LEN = 40

# ============================================
# 建表 SQL（契约 §3-C 表设计原样；DDL 风格与多人标注系统设计规范 §2 一致）
# ============================================

CUSTOM_FIELDS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS custom_fields (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,                     -- 词典项目（dictionary_projects，软引用）
  code VARCHAR(64) NOT NULL,                   -- 字段代码（项目内唯一，如 register）
  name VARCHAR(120) NOT NULL,                  -- 展示名（如 语域）
  applies_to ENUM('word','sense','example') NOT NULL DEFAULT 'word',  -- 挂哪类锚
  value_type ENUM('text','number','enum','date','bool') NOT NULL DEFAULT 'text',
  enum_values JSON NULL,                       -- value_type='enum' 时的合法值白名单（JSON 数组）
  required TINYINT(1) NOT NULL DEFAULT 0,      -- 仅作声明：批次 2 表单强制必填；数据层不拒空值
  status ENUM('active','deprecated') NOT NULL DEFAULT 'active',  -- 弃用只停写不删行
  created_by INT NULL,                         -- 定义人 users.id（软引用，可 NULL）
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_custom_field_code (project_id, code),
  KEY idx_custom_fields_project (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# custom_values 无 users 外键（updated_by 软引用）；field_id 对 custom_fields
# 是本模块内部 FK —— 字段被运维物理删除时值行级联消失，不留悬挂 EAV 行。
# 本模块对外只 deprecate（不删字段），CASCADE 仅为运维清理兜底。
CUSTOM_VALUES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS custom_values (
  id INT AUTO_INCREMENT PRIMARY KEY,
  field_id INT NOT NULL,
  anchor_type ENUM('word','sense','example') NOT NULL DEFAULT 'word',  -- 锚类型（= 字段 applies_to）
  anchor_id INT NOT NULL,   -- 锚行 id（definitions/oald_senses/sense_examples 的 INT 主键）
  value_text TEXT NULL,                        -- text/enum/date/bool 值（bool 存 '1'/'0'）
  value_num DOUBLE NULL,                       -- number 值
  updated_by INT NULL,                         -- 最后写值人 users.id（软引用，可 NULL）
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_custom_value (field_id, anchor_type, anchor_id),
  KEY idx_custom_values_anchor (anchor_type, anchor_id),
  CONSTRAINT fk_custom_values_field FOREIGN KEY (field_id)
    REFERENCES custom_fields(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

IMPORT_BATCHES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS import_batches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,                     -- 词典项目（软引用）
  file_name VARCHAR(255) NOT NULL,             -- 导入文件名（审计追溯）
  file_sha256 CHAR(64) NOT NULL,               -- 文件指纹（幂等/对账）
  target_domain VARCHAR(40) NOT NULL DEFAULT '',  -- 灌入的目标域（如 definitions / custom_values）
  mapping_json JSON NULL,                      -- 列→字段映射（导入向导的映射留痕）
  rows_total INT NOT NULL DEFAULT 0,           -- finish_batch 时回填
  rows_ok INT NOT NULL DEFAULT 0,
  rows_rejected INT NOT NULL DEFAULT 0,
  status ENUM('running','finished','rolled_back') NOT NULL DEFAULT 'running',
  operator INT NULL,                           -- 操作人 users.id —— 仅词典管理员（§15 导入同权），软引用
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_import_batches_project (project_id, status),
  KEY idx_import_batches_sha (file_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# 伴生表（批次 6-T）：revert_log 的**持久化**存储。此前 revert_log 只暂存在
# 导入页会话（st.session_state），会话丢失即不可回滚；本表把逐行事件落库，
# rollback_batch 无显式 revert_log 时从本表读取 —— 跨会话回滚成立。
# batch_id 对 import_batches 是本模块内部 FK（CASCADE：批次行被运维清理时
# 事件随之消失，不留悬挂行）；(batch_id, seq) 唯一 —— seq 批内从 1 递增，
# 回滚按 seq 升序重放（与导入执行时的收集顺序一致）。
IMPORT_REVERT_LOG_TABLE_SQL = """CREATE TABLE IF NOT EXISTS import_revert_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  batch_id INT NOT NULL,                       -- 导入批次（import_batches，本模块内部 FK）
  seq INT NOT NULL,                            -- 事件序号（批内从 1 递增，回放顺序）
  event JSON NOT NULL,                         -- revert_log 事件（口径逐字对齐 rollback_batch）
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_import_revert_log (batch_id, seq),
  CONSTRAINT fk_import_revert_log_batch FOREIGN KEY (batch_id)
    REFERENCES import_batches(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 建表
# ============================================
def ensure_dict_admin_tables() -> None:
    """幂等创建 custom_fields / custom_values / import_batches 三表（可重复调用）。

    三表均不依赖 users / dictionary_projects 外键（软引用），ensure 可独立于
    其他模块先行建表。被数据库拒绝（无权限等）只记 error 日志不抛异常，
    页面可继续渲染。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(CUSTOM_FIELDS_TABLE_SQL)
            cursor.execute(CUSTOM_VALUES_TABLE_SQL)
            cursor.execute(IMPORT_BATCHES_TABLE_SQL)
            cursor.execute(IMPORT_REVERT_LOG_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"dict_admin 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"dict_admin 表初始化意外错误: {e}")


# ============================================
# 入参规整（应用层先拒，非法值不进数据库）
# ============================================
_INVALID = object()  # 字符串校验失败的哨兵（None 是合法值，不能复用；仿 ai_ledger）


def _clean_str(value: Any, max_len: int) -> Any:
    """必填字符串规整：非 str/纯空白/超长 → _INVALID；否则去首尾空白。"""
    if not isinstance(value, str):
        return _INVALID
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len:
        return _INVALID
    return cleaned


def _dump_json_strict(value: Any) -> Optional[str]:
    """dict/list → JSON 串；标量/不可序列化/NaN/Inf 返回 None（MySQL JSON 列必炸的先在入口拒）。"""
    if not isinstance(value, (dict, list)):
        return None
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return None


def _parse_json(raw: Any) -> Any:
    """JSON 列 → dict/list（PyMySQL 对 JSON 列可能给 str；坏数据按缺失返回 None）。"""
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None
    return None


def _clean_enum_values(enum_values: Any) -> Any:
    """enum 字段白名单规整：list/tuple 的非空短字符串 → 去重保序列表；否则 _INVALID。

    空白成员剔除；成员统一 str().strip()；空名单（剔完为空）也是 _INVALID ——
    enum 字段必须给出至少一个合法值，否则永远写不进值。
    """
    if not isinstance(enum_values, (list, tuple)):
        return _INVALID
    cleaned: List[str] = []
    for item in enum_values:
        if not isinstance(item, str):
            return _INVALID
        text = item.strip()
        if not text:
            return _INVALID  # 空白枚举成员：定义歧义，入口拒绝
        if len(text) > MAX_ENUM_VALUE_LEN:
            return _INVALID
        if text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return _INVALID
    if len(cleaned) > MAX_ENUM_ITEMS:
        return _INVALID
    return cleaned


def _clean_sha256(value: Any) -> Any:
    """sha256 指纹规整：64 位十六进制（大小写均可）→ 小写串；否则 _INVALID。

    用正则而非 int(text, 16) 判定 —— int 解析容忍下划线分隔（'a_b' 也过），
    不是合法指纹。
    """
    if not isinstance(value, str):
        return _INVALID
    text = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        return _INVALID
    return text


def _normalize_value(
    value_type: str,
    value: Any,
    enum_values: Optional[List[str]] = None,
) -> Any:
    """按 value_type 把入参值规整为存储形态 (value_text, value_num)。

    Returns:
        tuple[str|None, float|None]：合法值的存储形态；
        _INVALID：类型不符/越界/非有限数/日期非法/枚举不在白名单。

    口径（与 set_value / query_anchors_by_field 共用，保证写读一致）：
      * text：必须 str（原样存储，不 strip —— 数据保真）；空串合法
        （required 是批次 2 表单侧强制，数据层不拒空值，见模块 docstring）；
      * number：int/float（bool 拒），须有限（NaN/Inf 拒）→ value_num；
      * enum：str，去首尾空白后必须 ∈ enum_values 白名单 → value_text；
      * date：YYYY-MM-DD 字符串（严格补零）或 date/datetime 实例 → ISO 串；
      * bool：True/False 或 0/1 → value_text '1'/'0'（其余一律拒，不猜）。
    """
    if value_type == "text":
        if not isinstance(value, str):
            return _INVALID
        if len(value) > MAX_VALUE_TEXT_LEN:
            return _INVALID
        return (value, None)
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _INVALID
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return _INVALID
        return (None, f)
    if value_type == "enum":
        if not isinstance(value, str):
            return _INVALID
        text = value.strip()
        if not text or not enum_values or text not in enum_values:
            return _INVALID
        return (text, None)
    if value_type == "date":
        if isinstance(value, datetime):
            return (value.date().isoformat(), None)
        if isinstance(value, date):
            return (value.isoformat(), None)
        if isinstance(value, str):
            text = value.strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
                return _INVALID
            try:
                date.fromisoformat(text)
            except ValueError:
                return _INVALID
            return (text, None)
        return _INVALID
    if value_type == "bool":
        if isinstance(value, bool):
            return ("1" if value else "0", None)
        if isinstance(value, int) and value in (0, 1):
            return (str(value), None)
        return _INVALID
    return _INVALID


def _value_matches_column(value_type: str) -> str:
    """该 value_type 的值落在 custom_values 的哪一列（query_anchors_by_field 用）。"""
    return "value_num" if value_type == "number" else "value_text"


# ============================================
# 库内元数据探测（rollback_batch 动态表名的第二道闸）
# ============================================

def _columns_of(cursor, table: str) -> Dict[str, str]:
    """表的 {列名: COLUMN_TYPE} 映射（rollback_batch 校验 old_values 列名用）。"""
    cursor.execute(
        """SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
        (table,),
    )
    return {str(r["COLUMN_NAME"]): str(r["COLUMN_TYPE"] or "") for r in cursor.fetchall()}


def _soft_invalidate_supported(cursor, table: str) -> bool:
    """该表是否支持软作废（MVP 口径，rollback_batch 用）。

    条件：表有 status 列，且 —— 列是 ENUM 时枚举必须含 'deprecated'
    （否则 UPDATE 会触发 DataError，先探测直接跳过）；非 ENUM（VARCHAR 等）
    视为可写。探测不到 status 列的表一律 False（仅留痕不作废）。
    """
    columns = _columns_of(cursor, table)
    col_type = columns.get("status")
    if col_type is None:
        return False
    lowered = col_type.lower()
    if lowered.startswith("enum("):
        inner = lowered[lowered.find("(") + 1 : lowered.rfind(")")]
        members = [m.strip().strip("'") for m in inner.split(",")]
        return _SOFT_INVALIDATE_STATUS in members
    return True


# ============================================
# 字段定义 CRUD
# ============================================

def define_field(
    project_id: int,
    code: str,
    name: str,
    applies_to: str,
    value_type: str,
    enum_values: Any = None,
    required: bool = False,
    created_by: Optional[int] = None,
) -> int:
    """定义一个项目定制字段（custom_fields 行），返回新字段 id。

    **权限要求（§15 导入/内容操作同权）**：仅词典管理员（dict_admin / 项目
    chief）；批次 2 由中央闸门 require_dict_admin() 拦截后调用。

    校验口径（应用层先拒，非法值不进数据库）：
      * code 项目内唯一（UNIQUE(project_id, code)）；重复定义返回 0 ——
        改枚举/改名属新语义需求，本期无更新接口（弃用后重建新 code 即可）；
      * applies_to / value_type 必须在枚举白名单内；
      * value_type='enum' 时 enum_values 必须是 ≥1 条非空字符串的白名单
        （去重保序后以 JSON 存库）；**非 enum 类型传非空 enum_values 也拒**
        （调用方参数错位，宁可拒绝不留歧义行）；
      * required 仅作声明存 1/0：批次 2 表单强制必填用，数据层不因 required
        拒绝任何值（见模块 docstring「required 语义」）；
      * created_by 是定义人 users.id（软引用），None 允许（系统预置字段）。

    Args:
        project_id: 词典项目 id
        code: 字段代码（非空，≤64 字符，项目内唯一）
        name: 展示名（非空，≤120 字符）
        applies_to: 挂锚类型 ∈ APPLIES_TO（'word'/'sense'/'example'）
        value_type: 值类型 ∈ VALUE_TYPES
        enum_values: enum 字段的合法值白名单（list/tuple[str]）；其余类型传 None
        required: 是否必填（仅声明，表单侧强制）
        created_by: 定义人 users.id（可 None）

    Returns:
        int: 新字段 id；参数非法 / code 重复 / 数据库错误返回 0
        （falsy，调用方按失败处理，与 ai_ledger.record_proposal 口径一致）。
    """
    pid = _as_int(project_id)
    if pid is None or pid <= 0:
        logger.error(f"define_field 拒绝非法 project_id: {project_id!r}")
        return 0
    clean_code = _clean_str(code, MAX_FIELD_CODE_LEN)
    if clean_code is _INVALID:
        logger.error(f"define_field 拒绝非法 code: {code!r}（非空字符串，≤{MAX_FIELD_CODE_LEN} 字符）")
        return 0
    clean_name = _clean_str(name, MAX_FIELD_NAME_LEN)
    if clean_name is _INVALID:
        logger.error(f"define_field 拒绝非法 name: {name!r}（非空字符串，≤{MAX_FIELD_NAME_LEN} 字符）")
        return 0
    if applies_to not in APPLIES_TO:
        logger.error(f"define_field 拒绝非法 applies_to: {applies_to!r}（须 ∈ {APPLIES_TO}）")
        return 0
    if value_type not in VALUE_TYPES:
        logger.error(f"define_field 拒绝非法 value_type: {value_type!r}（须 ∈ {VALUE_TYPES}）")
        return 0
    if value_type == "enum":
        cleaned_enum = _clean_enum_values(enum_values)
        if cleaned_enum is _INVALID:
            logger.error(
                f"define_field 拒绝非法 enum_values: {enum_values!r}"
                f"（enum 字段须为 ≥1 条非空字符串的白名单，≤{MAX_ENUM_ITEMS} 条）"
            )
            return 0
        enum_json = json.dumps(cleaned_enum, ensure_ascii=False)
    else:
        # 非 enum 类型：enum_values 必须为空（None 或空序列）——
        # 传了内容就是调用方参数错位，宁可拒绝不留歧义行
        if enum_values is not None and not (
            isinstance(enum_values, (list, tuple)) and len(enum_values) == 0
        ):
            logger.error(
                f"define_field 拒绝非 enum 字段携带 enum_values（value_type={value_type}）"
            )
            return 0
        enum_json = None
    creator = _as_int(created_by)
    if created_by is not None and (creator is None or creator <= 0):
        logger.error(f"define_field 拒绝非法 created_by: {created_by!r}")
        return 0

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO custom_fields "
                "(project_id, code, name, applies_to, value_type, enum_values, "
                "required, status, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)",
                (
                    pid,
                    clean_code,
                    clean_name,
                    applies_to,
                    value_type,
                    enum_json,
                    1 if required else 0,
                    creator,
                ),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        # Duplicate entry（code 重复）等都在这里落地
        logger.error(f"定义定制字段失败（project={pid}, code={code!r}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"定义定制字段意外错误（code={code!r}）: {e}")
        return 0


def deprecate_field(field_id: int) -> bool:
    """弃用定制字段（status: active → deprecated），返回是否实际弃用。

    **权限要求（§15）**：仅词典管理员（dict_admin / 项目 chief）；批次 2 由
    中央闸门 require_dict_admin() 拦截后调用。

    弃用语义：**只停写不删** —— 存量 custom_values 保留（词条装配的定制属性区
    继续展示），新写值被 set_value 拒绝。字段绝不物理删除（历史值的外键引用
    要一直成立；运维清理走 FK CASCADE 兜底）。

    Returns:
        bool: 实际弃用 True；字段不存在 / **已弃用过**（未变更 = False 口径，
        与 users_db.set_role 一致）/ 数据库错误为 False。
    """
    fid = _as_int(field_id)
    if fid is None or fid <= 0:
        logger.error(f"deprecate_field 拒绝非法 field_id: {field_id!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE custom_fields SET status = 'deprecated' "
                "WHERE id = %s AND status = 'active'",
                (fid,),
            )
            if cursor.rowcount <= 0:
                logger.error(f"deprecate_field 无可弃用行: field_id={fid}（不存在或已弃用）")
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"弃用字段 {fid} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"弃用字段 {fid} 意外错误: {e}")
        return False


def set_value(field_id: int, anchor_type: str, anchor_id: int, value: Any,
              updated_by: int) -> bool:
    """为锚写一个定制属性值（一字段一锚一值，重复写即改值 upsert）。

    **权限要求（§15）**：仅词典管理员（定制属性是词典资产的内容性数据）。

    校验口径（应用层先拒）：
      * 字段必须存在且 **status='active'** —— 弃用字段拒绝一切新写值
        （deprecate_field 的语义）；字段不存在 / 已弃用返回 False；
      * anchor_type ∈ APPLIES_TO 且 **必须等于字段的 applies_to**
        （word 字段不能挂到 sense 锚上 —— 定义错位在入口拦下）；
      * value 按字段 value_type 规整（见 _normalize_value）：number 必须是
        有限数值；enum 必须在字段 enum_values 白名单内；date 必须是
        YYYY-MM-DD（或 date/datetime 实例）；bool 只认 True/False/0/1；
      * **required 不在本函数校验**：required 是批次 2 表单侧的强制必填
        声明，数据层存什么算什么（见模块 docstring「required 语义」）；
      * updated_by 必填（值变更留痕：谁最后写的）。

    Returns:
        bool: 新写入或实际改值 True；**值与现值完全相同**（MySQL 不计变更行，
        返回 False —— 「未变更 = False」口径与 users_db.set_role 一致）；
        字段不存在/已弃用、锚不匹配、值类型非法、updated_by 非法、
        数据库错误为 False。
    """
    fid = _as_int(field_id)
    if fid is None or fid <= 0:
        logger.error(f"set_value 拒绝非法 field_id: {field_id!r}")
        return False
    if anchor_type not in APPLIES_TO:
        logger.error(f"set_value 拒绝非法 anchor_type: {anchor_type!r}（须 ∈ {APPLIES_TO}）")
        return False
    aid = _as_int(anchor_id)
    if aid is None or aid <= 0:
        logger.error(f"set_value 拒绝非法 anchor_id: {anchor_id!r}")
        return False
    writer = _as_int(updated_by)
    if writer is None or writer <= 0:
        logger.error(f"set_value 拒绝非法 updated_by: {updated_by!r}（值变更必须留痕）")
        return False

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT applies_to, value_type, enum_values, status "
                "FROM custom_fields WHERE id = %s",
                (fid,),
            )
            field = cursor.fetchone()
            if field is None:
                logger.error(f"set_value 字段不存在: field_id={fid}")
                return False
            if str(field.get("status")) != "active":
                logger.error(f"set_value 拒绝写已弃用字段: field_id={fid}")
                return False
            if anchor_type != str(field.get("applies_to")):
                logger.error(
                    f"set_value 锚类型与字段 applies_to 不符: anchor_type={anchor_type!r}, "
                    f"applies_to={field.get('applies_to')!r}"
                )
                return False
            enum_values = _parse_json(field.get("enum_values"))
            stored = _normalize_value(
                str(field.get("value_type")), value,
                enum_values if isinstance(enum_values, list) else None,
            )
            if stored is _INVALID:
                logger.error(
                    f"set_value 拒绝非法值: field_id={fid}, value_type="
                    f"{field.get('value_type')!r}, value={value!r}"
                )
                return False
            value_text, value_num = stored
            cursor.execute(
                """INSERT INTO custom_values
                   (field_id, anchor_type, anchor_id, value_text, value_num, updated_by)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     value_text = VALUES(value_text),
                     value_num = VALUES(value_num),
                     updated_by = VALUES(updated_by),
                     updated_at = NOW()""",
                (fid, anchor_type, aid, value_text, value_num, writer),
            )
            # 新插入 rowcount=1；ON DUPLICATE 且值有变化 rowcount=2；
            # 值无变化 rowcount=0（MySQL upsert 语义）→ 未变更 = False
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"写定制属性值失败（field={fid}, anchor={anchor_type}:{aid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"写定制属性值意外错误（field={fid}）: {e}")
        return False


def get_values_for_anchor(anchor_type: str, anchor_id: int) -> List[Dict[str, Any]]:
    """按锚取全部定制属性值（词条装配「定制属性区」数据源），附字段元信息。

    只读，不做 status 过滤：弃用字段的存量值一并返回（field_status 让页面
    自行决定展示/灰显口径 —— 数据层保持「存什么给什么」）。

    Args:
        anchor_type: 锚类型 ∈ APPLIES_TO
        anchor_id: 锚行 id

    Returns:
        list[dict]: 每项含值行字段（id/field_id/value_text/value_num/
        updated_by/updated_at）+ 字段元信息（code/name/applies_to/value_type/
        enum_values(已解析 list)/required/field_status），按 field_id 升序；
        参数非法 / 无值 / 数据库不可用返回 []。
    """
    if anchor_type not in APPLIES_TO:
        logger.error(f"get_values_for_anchor 拒绝非法 anchor_type: {anchor_type!r}")
        return []
    aid = _as_int(anchor_id)
    if aid is None or aid <= 0:
        logger.error(f"get_values_for_anchor 拒绝非法 anchor_id: {anchor_id!r}")
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT cv.id, cv.field_id, cv.anchor_type, cv.anchor_id,
                          cv.value_text, cv.value_num, cv.updated_by, cv.updated_at,
                          cf.code, cf.name, cf.applies_to, cf.value_type,
                          cf.enum_values, cf.required, cf.status AS field_status
                   FROM custom_values cv
                   JOIN custom_fields cf ON cf.id = cv.field_id
                   WHERE cv.anchor_type = %s AND cv.anchor_id = %s
                   ORDER BY cf.id""",
                (anchor_type, aid),
            )
            rows = cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"按锚查定制属性值失败（anchor={anchor_type}:{aid}）: {e}")
        return []
    except Exception as e:
        logger.error(f"按锚查定制属性值意外错误: {e}")
        return []
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["enum_values"] = _parse_json(item.get("enum_values"))
        num = item.get("value_num")
        try:
            item["value_num"] = float(num) if num is not None else None
        except (TypeError, ValueError):
            item["value_num"] = None
        result.append(item)
    return result


def query_anchors_by_field(field_id: int, value: Any) -> List[str]:
    """按字段反查持有某值的锚 id 清单（浏览器按定制属性筛选的数据源）。

    value 按字段 value_type 用与 set_value **同一套**规整规则归一后再匹配
    （number 匹配 value_num 列，其余匹配 value_text 列）—— 保证「写过就能
    查到」。value 不符合该字段类型口径（如给 number 字段传 'abc'）按查无
    处理并记日志（查询页不该被脏入参打崩）。

    Args:
        field_id: 字段 id
        value: 目标值（按字段 value_type 规整后精确匹配）

    Returns:
        list[str]: 锚 id 字符串列表（升序；契约签名即 list[str] —— 锚 id
        以字符串出参，页面拼接/比较免转型）；字段不存在 / 值非法 /
        查无 / 数据库不可用返回 []。
    """
    fid = _as_int(field_id)
    if fid is None or fid <= 0:
        logger.error(f"query_anchors_by_field 拒绝非法 field_id: {field_id!r}")
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT value_type, enum_values FROM custom_fields WHERE id = %s",
                (fid,),
            )
            field = cursor.fetchone()
            if field is None:
                logger.error(f"query_anchors_by_field 字段不存在: field_id={fid}")
                return []
            value_type = str(field.get("value_type"))
            enum_values = _parse_json(field.get("enum_values"))
            stored = _normalize_value(
                value_type, value,
                enum_values if isinstance(enum_values, list) else None,
            )
            if stored is _INVALID:
                logger.error(
                    f"query_anchors_by_field 值与字段类型不符（field={fid}, "
                    f"value_type={value_type!r}, value={value!r}）"
                )
                return []
            value_text, value_num = stored
            column = _value_matches_column(value_type)
            cursor.execute(
                f"""SELECT anchor_id FROM custom_values
                    WHERE field_id = %s AND {column} = %s
                    ORDER BY anchor_id""",  # noqa: S608 — column 是本模块常量（非用户输入）
                (fid, value_num if value_type == "number" else value_text),
            )
            rows = cursor.fetchall()
            return [str(int(r["anchor_id"])) for r in rows]
    except pymysql.Error as e:
        logger.error(f"按字段查锚失败（field={fid}）: {e}")
        return []
    except Exception as e:
        logger.error(f"按字段查锚意外错误（field={fid}）: {e}")
        return []


# ============================================
# 只读辅助（非契约 §3-C 签名；供批次 2 定制属性管理页取数）
# ============================================

_FIELD_COLUMNS = (
    "id, project_id, code, name, applies_to, value_type, enum_values, "
    "required, status, created_by, created_at"
)


def list_fields(project_id: int, include_deprecated: bool = False) -> List[Dict[str, Any]]:
    """项目的字段定义清单（非契约签名；定制属性管理页列字段用）。

    Args:
        project_id: 词典项目 id
        include_deprecated: 是否含已弃用字段（默认只出 active）

    Returns:
        list[dict]: 字段字典列表（enum_values 已解析为 list），按 id 升序；
        项目非法 / 无字段 / 数据库不可用返回 []。
    """
    pid = _as_int(project_id)
    if pid is None or pid <= 0:
        logger.error(f"list_fields 拒绝非法 project_id: {project_id!r}")
        return []
    where = " WHERE project_id = %s"
    if not include_deprecated:
        where += " AND status = 'active'"  # 常量拼接（非用户输入）
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {_FIELD_COLUMNS} FROM custom_fields{where} ORDER BY id",
                (pid,),
            )
            rows = cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"查询项目 {pid} 字段清单失败: {e}")
        return []
    except Exception as e:
        logger.error(f"查询项目 {pid} 字段清单意外错误: {e}")
        return []
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["enum_values"] = _parse_json(item.get("enum_values"))
        item["required"] = bool(int(item.get("required") or 0))
        result.append(item)
    return result


def get_field(field_id: int) -> Optional[Dict[str, Any]]:
    """按 id 取单个字段定义（非契约签名；含已弃用 —— 管理页详情用）。

    Returns:
        dict | None: 字段字典（enum_values 已解析）；不存在 / id 非法 /
        数据库不可用返回 None。
    """
    fid = _as_int(field_id)
    if fid is None or fid <= 0:
        logger.error(f"get_field 拒绝非法 field_id: {field_id!r}")
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {_FIELD_COLUMNS} FROM custom_fields WHERE id = %s",
                (fid,),
            )
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"读取字段 {fid} 失败: {e}")
        return None
    except Exception as e:
        logger.error(f"读取字段 {fid} 意外错误: {e}")
        return None
    if row is None:
        return None
    item = dict(row)
    item["enum_values"] = _parse_json(item.get("enum_values"))
    item["required"] = bool(int(item.get("required") or 0))
    return item


# ============================================
# 导入批次台账（§15 导入同权：业务数据批量灌库仅词典管理员）
# ============================================

def start_batch(project_id: int, file_name: str, file_sha256: str,
                target_domain: str, mapping_json: Any, operator: int) -> int:
    """登记一次导入批次（status='running'），返回批次 id。

    **权限要求（§15 导入同权）**：导入向导/批量灌库的业务数据操作**仅词典
    管理员**可执行；平台管理员不碰业务数据。本期数据层不做角色判定 ——
    批次 2 由中央闸门 require_dict_admin() 拦截后调用；operator 即操作人
    users.id（审计留痕，必填）。

    Args:
        project_id: 词典项目 id
        file_name: 导入文件名（非空，≤255 字符）
        file_sha256: 文件 sha256 十六进制串（64 位，大小写均可，统一小写入库）
        target_domain: 灌入的目标域（非空，≤40 字符，如 'definitions'）
        mapping_json: 列→字段映射（dict/list，或可解析为二者的 JSON 串；
            以 JSON 留痕）
        operator: 操作人 users.id（词典管理员）

    Returns:
        int: 新批次 id（status='running'，行数三列 0）；参数非法 /
        数据库错误返回 0。
    """
    pid = _as_int(project_id)
    if pid is None or pid <= 0:
        logger.error(f"start_batch 拒绝非法 project_id: {project_id!r}")
        return 0
    clean_name = _clean_str(file_name, MAX_FILE_NAME_LEN)
    if clean_name is _INVALID:
        logger.error(f"start_batch 拒绝非法 file_name: {file_name!r}（非空，≤{MAX_FILE_NAME_LEN} 字符）")
        return 0
    clean_sha = _clean_sha256(file_sha256)
    if clean_sha is _INVALID:
        logger.error(f"start_batch 拒绝非法 file_sha256: {file_sha256!r}（须为 64 位十六进制）")
        return 0
    clean_domain = _clean_str(target_domain, MAX_TARGET_DOMAIN_LEN)
    if clean_domain is _INVALID:
        logger.error(
            f"start_batch 拒绝非法 target_domain: {target_domain!r}"
            f"（非空，≤{MAX_TARGET_DOMAIN_LEN} 字符）"
        )
        return 0
    mapping = _parse_json(mapping_json) if isinstance(mapping_json, str) else mapping_json
    mapping_json_str = _dump_json_strict(mapping)
    if mapping_json_str is None:
        logger.error(
            f"start_batch 拒绝非法 mapping_json: {mapping_json!r}（dict/list 或可解析 JSON 串）"
        )
        return 0
    op = _as_int(operator)
    if op is None or op <= 0:
        logger.error(f"start_batch 拒绝非法 operator: {operator!r}（操作人必填，§15 导入同权）")
        return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO import_batches "
                "(project_id, file_name, file_sha256, target_domain, mapping_json, "
                "rows_total, rows_ok, rows_rejected, status, operator) "
                "VALUES (%s, %s, %s, %s, %s, 0, 0, 0, 'running', %s)",
                (pid, clean_name, clean_sha, clean_domain, mapping_json_str, op),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"登记导入批次失败（project={pid}, file={file_name!r}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"登记导入批次意外错误（file={file_name!r}）: {e}")
        return 0


def finish_batch(batch_id: int, rows_total: int, rows_ok: int,
                 rows_rejected: int) -> bool:
    """导入完成记账：回填行数并把 status 从 running → finished。

    **权限要求（§15 导入同权）**：仅词典管理员；批次 2 由中央闸门拦截后调用。

    状态机守卫：**只有 running 批次可 finish** —— 已 finished / 已 rolled_back
    的批次拒绝重复记账（batch 台账是一次性事实，不许覆盖）。rows_* 必须
    ≥0 整数；口径建议 rows_ok + rows_rejected == rows_total（数据层不强制
    求和，留给页面自检）。

    Returns:
        bool: 记账成功 True；批次不存在 / **不在 running 态** / 行数非法 /
        数据库错误为 False。
    """
    bid = _as_int(batch_id)
    if bid is None or bid <= 0:
        logger.error(f"finish_batch 拒绝非法 batch_id: {batch_id!r}")
        return False
    total = _as_int(rows_total)
    ok = _as_int(rows_ok)
    rejected = _as_int(rows_rejected)
    if None in (total, ok, rejected) or min(total, ok, rejected) < 0:
        logger.error(
            f"finish_batch 拒绝非法行数: rows_total={rows_total!r}, "
            f"rows_ok={rows_ok!r}, rows_rejected={rows_rejected!r}（均须 ≥0 整数）"
        )
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE import_batches SET rows_total = %s, rows_ok = %s, "
                "rows_rejected = %s, status = 'finished' "
                "WHERE id = %s AND status = 'running'",
                (total, ok, rejected, bid),
            )
            if cursor.rowcount <= 0:
                logger.error(
                    f"finish_batch 无可记账批次: batch_id={bid}（不存在或已非 running）"
                )
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"导入批次 {bid} 记账失败: {e}")
        return False
    except Exception as e:
        logger.error(f"导入批次 {bid} 记账意外错误: {e}")
        return False


def persist_revert_log(batch_id: int, events: Any) -> bool:
    """把一次导入的 revert_log 事件逐条持久化进伴生表 import_revert_log。

    **权限要求（§15 导入同权）**：仅词典管理员可执行导入与回滚，持久化是
    「执行写入」的收尾动作 —— 页面由中央闸门拦截后调用（数据层不做角色判定，
    与本模块其余写 API 同口径，docstring 标注以便核对）。

    口径（批次 6-T）：
      * events 须为 list/tuple[dict]：每条事件是 JSON 可序列化的 dict，且
        action ∈ REVERT_ACTIONS 白名单（与 rollback_batch 的预校验同源 ——
        白名单外/不可序列化的事件在持久化入口就拒，不让坏日志进伴生表）；
      * seq 批内从 1 递增（UNIQUE(batch_id, seq)）；**同一批次只允许持久化
        一次**（已有记录时整体拒绝，防两次执行的事件混序拼接 —— 重新导入
        应登记新批次）；
      * **批次状态守卫（R3-2）**：仅 running / finished 批次可补写日志 ——
        rolled_back 批次拒绝（已回滚批次不可补写日志：回滚已完成却再落一份
        事件集，会让台账与库内实态互相矛盾）；批次不存在同样拒绝（FK 报错
        前先给可读日志）；
      * **空清单合法**（零行变更的批次无事可记，返回 True、零插入）；
      * 逐事件参数化插入，单事务（autocommit=False）：任一条失败整体回滚，
        不留半套日志；
      * batch_id 必须真实存在（FK → import_batches，CASCADE：批次行被运维
        清理时事件随之消失）。

    Args:
        batch_id: 批次 id（import_batches 现存行）
        events: revert_log 事件清单（list[dict]，口径同 rollback_batch；
            空清单合法）

    Returns:
        bool: 持久化完成 True（含空清单）；参数非法 / 批次不存在 /
        批次已回滚（rolled_back，R3-2 守卫）/ 已持久化过 / 数据库错误为 False。
    """
    bid = _as_int(batch_id)
    if bid is None or bid <= 0:
        logger.error(f"persist_revert_log 拒绝非法 batch_id: {batch_id!r}")
        return False
    if not isinstance(events, (list, tuple)):
        logger.error(
            f"persist_revert_log 拒绝非法 events: 须为 list[dict]（得 {type(events).__name__}）"
        )
        return False
    # --- 入口校验（先验后写，任何一条非法整体拒绝）---
    serialized: List[str] = []
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            logger.error(f"persist_revert_log 拒绝非法事件 #{i}: {event!r}（须为 dict）")
            return False
        if event.get("action") not in REVERT_ACTIONS:
            logger.error(
                f"persist_revert_log 拒绝非法 action（#{i}）: {event.get('action')!r}"
                f"（须 ∈ {REVERT_ACTIONS}）"
            )
            return False
        event_json = _dump_json_strict(event)
        if event_json is None:
            logger.error(f"persist_revert_log 拒绝不可 JSON 序列化的事件（#{i}）: {event!r}")
            return False
        serialized.append(event_json)
    try:
        # autocommit=False：状态守卫＋已有日志检查＋逐条插入同处一个事务，
        # 任何一步失败整体回滚（不留半套持久化日志）
        with get_db_cursor(autocommit=False) as cursor:
            # --- 批次状态守卫（R3-2）：running/finished 才可补写日志 ---
            cursor.execute(
                "SELECT status FROM import_batches WHERE id = %s",
                (bid,),
            )
            batch = cursor.fetchone()
            if batch is None:
                logger.error(f"persist_revert_log 批次不存在: batch_id={bid}")
                return False
            batch_status = str(batch.get("status"))
            if batch_status not in ("running", "finished"):
                logger.error(
                    f"persist_revert_log 拒绝补写: batch_id={bid}（status="
                    f"{batch_status!r}）—— 已回滚批次不可补写日志"
                )
                return False
            cursor.execute(
                "SELECT COUNT(*) AS n FROM import_revert_log WHERE batch_id = %s",
                (bid,),
            )
            if int(cursor.fetchone()["n"] or 0) > 0:
                logger.error(
                    f"persist_revert_log 拒绝重复持久化: batch_id={bid}"
                    "（该批次已有持久化回滚日志；重新导入请登记新批次）"
                )
                return False
            for seq, event_json in enumerate(serialized, start=1):
                cursor.execute(
                    "INSERT INTO import_revert_log (batch_id, seq, event) "
                    "VALUES (%s, %s, %s)",
                    (bid, seq, event_json),
                )
        return True
    except pymysql.Error as e:
        # FK 1452（批次不存在）等都在这里落地
        logger.error(f"持久化 revert_log 失败（batch_id={bid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"持久化 revert_log 意外错误（batch_id={bid}）: {e}")
        return False


def _load_persisted_revert_log(cursor, batch_id: int) -> Optional[List[Dict[str, Any]]]:
    """从伴生表读回一个批次的持久化 revert_log（**只读**；rollback_batch 用）。

    Returns:
        list[dict] | None：按 seq 升序的事件清单（JSON 已解析）；无记录返回
        None（调用方按「无持久化回滚日志」拒绝）；记录存在但任一条 JSON
        损坏/不是 dict 也返回 None（fail-closed：半套可读日志不放行回滚）。
    """
    cursor.execute(
        "SELECT seq, event FROM import_revert_log "
        "WHERE batch_id = %s ORDER BY seq",
        (batch_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    events: List[Dict[str, Any]] = []
    for row in rows:
        parsed = _parse_json(row.get("event"))
        if not isinstance(parsed, dict):
            logger.error(
                f"持久化回滚日志损坏（batch_id={batch_id}, seq={row.get('seq')!r}）—— "
                "事件不是可解析的 JSON 对象，拒绝回滚（fail-closed）"
            )
            return None
        events.append(parsed)
    return events


def _same_revert_events(
    persisted: List[Dict[str, Any]], explicit: Any,
) -> bool:
    """显式 revert_log 与持久化事件集是否**逐事件一致**（rollback_batch 混用仲裁用）。

    一致 = 条数相同且按序逐条相等（dict 相等不敏感键序 —— 与 JSON 落库读回的
    结构对齐）。注意持久化事件是 JSON 往返产物：显式清单里若混入 JSON 不可
    表示的类型（datetime/tuple），比较会判不一致 —— 这正是想要的结果（不一致
    的传参不放行，调用方以持久化清单为准或显式传 None）。
    """
    if not isinstance(explicit, (list, tuple)):
        return False
    if len(persisted) != len(explicit):
        return False
    return all(p == e for p, e in zip(persisted, explicit))


def rollback_batch(batch_id: int, revert_log: Optional[List[Dict[str, Any]]] = None) -> bool:
    """按 revert_log 回滚一个已完成的导入批次（status: finished → rolled_back）。

    **权限要求（§15 导入同权）**：仅词典管理员；批次 2 由中央闸门拦截后调用。

    revert_log 来源两态（批次 6-T，向后兼容）：
      * **显式传参**（旧口径原样）：调用方直接给事件清单（既有测试/调用点
        不受影响）；空清单合法 —— 只翻转批次状态，对应「导入零行变更」；
      * **revert_log=None**（新口径，跨会话回滚）：从伴生表 import_revert_log
        读取该批次的持久化事件（persist_revert_log 写入，按 seq 升序重放）；
        批次无持久化记录时**如实拒绝**（批次状态不动），日志注明
        「无持久化回滚日志」—— 零行变更批次本就无事可回滚，历史批次的
        回滚须以持久化日志或显式传参为凭。

    显式传参 × 持久化日志的**混用仲裁（R3-1）**：伴生表已有该批次的持久化
    事件时，显式传参不再原样放行 ——
      * 显式传**空清单** → 拒（日志注明「持久化回滚日志存在，显式空清单与
        之矛盾」—— 持久化事件集在手却按零变更翻状态，审计线断链）；
      * 显式传**非空但与持久化集不同** → 拒（防架空：绕开持久化日志传入
        另一套事件，回滚结果与台账脱钩）；
      * 仅显式传参与持久化事件集**逐事件一致**时放行（幂等重放同一份清单
        的既有调用点不受影响）。
    伴生表无持久化记录（或记录损坏读不回）→ 显式传参维持旧口径原样。

    revert_log 两类动作（由导入执行方在灌库时逐行收集后传入）：
      * ``{'action': 'insert', 'table': <表名>, 'row_id': <id>}`` —— 导入新增
        的行：**软作废**（MVP 口径）。软作废 = ``UPDATE <table> SET
        status='deprecated' WHERE id=<row_id>``；**仅当目标表有 status 列且
        （ENUM 时）枚举含 'deprecated'** 才执行；目标表有 **import_voided**
        列（R3-9c，definitions 词目层的导入作废标记）则置
        ``import_voided=1``（装配/导出读侧按 0 过滤，行仍留库可审计）；
        两样都没有的表只留痕不动行：MVP 不物理 DELETE，作废行仍可审计追溯。
      * ``{'action': 'update', 'table': <表名>, 'row_id': <id>,
        'old_values': {列: 旧值, ...}}`` —— 导入覆盖过的行：按 old_values
        **恢复旧值**（逐列 UPDATE 回写）；old_values 含 **updated_at** 键时
        随逐列恢复一并 SET（R3-9a：import_engine 落导入前旧值 —— MySQL 显式
        赋值优先于 ON UPDATE CURRENT_TIMESTAMP，回滚后行的时间戳回到导入前
        时点，不被回滚动作本身再次顶掉）。

    安全规则（本文件唯一两处动态表/列名的地方，双闸校验）：
      * 表名/列名必须过本模块常量正则 ^[A-Za-z0-9_]{1,64}$，且表/列必须
        真实存在于当前库（information_schema 探测）—— 两道都过才允许拼接，
        值仍全走占位符；
      * revert_log **先整体校验、再执行**：任一条非法（动作/表/行/old_values
        不合规）整体拒绝、批次状态不动 —— 防止半套回滚（回滚是原子意图，
        要么全做要么不做）；
      * 行级 rowcount=0（行已被删等）只记日志不中断 —— 回滚容忍幂等重放。

    状态机：**只有 finished 批次可回滚**；running（导入未完成，无回滚基线）
    与 rolled_back（已回滚，不许重复回滚）一律拒绝。

    Args:
        batch_id: 批次 id（须处于 finished 态）
        revert_log: 回滚动作清单（结构见上）。**None = 从伴生表
            import_revert_log 读取该批次持久化事件**（跨会话回滚，无记录
            如实拒绝）；显式传 list/tuple = 旧口径原样（空清单合法 —— 只
            翻转批次状态，对应「导入本身零行变更」的批次）

    Returns:
        bool: 回滚执行完成且批次已置 rolled_back 为 True；批次不存在 /
        不在 finished 态 / 无持久化回滚日志（revert_log=None 时）/
        revert_log 任一条非法 / 执行中数据库错误为 False
        （执行失败时事务整体回滚，批次状态保持 finished）。
    """
    bid = _as_int(batch_id)
    if bid is None or bid <= 0:
        logger.error(f"rollback_batch 拒绝非法 batch_id: {batch_id!r}")
        return False
    if revert_log is not None and not isinstance(revert_log, (list, tuple)):
        logger.error(
            f"rollback_batch 拒绝非法 revert_log: "
            f"须为 list 或 None（得 {type(revert_log).__name__}）"
        )
        return False

    try:
        # autocommit=False：预校验＋执行＋状态翻转同处一个事务，任何一步失败
        # 由 get_db_cursor 异常路径整体回滚（docstring 承诺「事务整体回滚」）
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "SELECT status FROM import_batches WHERE id = %s",
                (bid,),
            )
            row = cursor.fetchone()
            if row is None:
                logger.error(f"rollback_batch 批次不存在: batch_id={bid}")
                return False
            if str(row.get("status")) != "finished":
                logger.error(
                    f"rollback_batch 拒绝非 finished 批次: batch_id={bid}, "
                    f"status={row.get('status')!r}（running 无回滚基线；rolled_back 已回滚）"
                )
                return False

            # --- revert_log 来源判定（None = 读伴生表；显式传参遇持久化
            #     记录走混用仲裁，R3-1：防架空持久化日志）---
            persisted = _load_persisted_revert_log(cursor, bid)
            if revert_log is None:
                if persisted is None:
                    logger.error(
                        f"rollback_batch 拒绝回滚: batch_id={bid}"
                        "（无持久化回滚日志 —— persist_revert_log 未写入或日志损坏；"
                        "零行变更批次本就无事可回滚，显式传参可回滚空清单）"
                    )
                    return False
                revert_log = persisted
            elif persisted is not None:
                if len(revert_log) == 0:
                    logger.error(
                        f"rollback_batch 拒绝回滚: batch_id={bid}"
                        "（持久化回滚日志存在，显式空清单与之矛盾 —— "
                        "零变更须以持久化日志为准或显式传一致清单）"
                    )
                    return False
                if not _same_revert_events(persisted, revert_log):
                    logger.error(
                        f"rollback_batch 拒绝回滚: batch_id={bid}"
                        "（显式 revert_log 与持久化回滚日志不一致 —— "
                        "防架空：按持久化日志回滚请显式传 None）"
                    )
                    return False

            # --- 第一道闸：整体预校验 revert_log（先验后动，防半套回滚） ---
            validated: List[Tuple[str, str, int, Optional[Dict[str, Any]]]] = []
            for i, entry in enumerate(revert_log):
                if not isinstance(entry, dict):
                    logger.error(f"rollback_batch 拒绝非法条目 #{i}: {entry!r}（须为 dict）")
                    return False
                action = entry.get("action")
                if action not in REVERT_ACTIONS:
                    logger.error(
                        f"rollback_batch 拒绝非法 action（#{i}）: {action!r}"
                        f"（须 ∈ {REVERT_ACTIONS}）"
                    )
                    return False
                table = entry.get("table")
                if not isinstance(table, str) or not _IDENTIFIER_RE.match(table):
                    logger.error(f"rollback_batch 拒绝非法表名（#{i}）: {table!r}")
                    return False
                if not _table_exists(cursor, table):
                    logger.error(f"rollback_batch 拒绝未知表（#{i}）: {table!r}（当前库无此表）")
                    return False
                row_id = _as_int(entry.get("row_id"))
                if row_id is None or row_id <= 0:
                    logger.error(f"rollback_batch 拒绝非法 row_id（#{i}）: {entry.get('row_id')!r}")
                    return False
                old_values: Optional[Dict[str, Any]] = None
                if action == REVERT_UPDATE:
                    raw_old = entry.get("old_values")
                    if not isinstance(raw_old, dict) or not raw_old:
                        logger.error(
                            f"rollback_batch 拒绝非法 old_values（#{i}）: {raw_old!r}"
                            "（update 动作须为非空 dict）"
                        )
                        return False
                    columns = _columns_of(cursor, table)
                    for col, val in raw_old.items():
                        if not isinstance(col, str) or not _IDENTIFIER_RE.match(col):
                            logger.error(f"rollback_batch 拒绝非法列名（#{i}）: {col!r}")
                            return False
                        if col not in columns:
                            logger.error(f"rollback_batch 拒绝未知列（#{i}）: {table}.{col}")
                            return False
                        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                            logger.error(f"rollback_batch 拒绝非法旧值（#{i}）: {col}={val!r}")
                            return False
                    old_values = dict(raw_old)
                validated.append((action, table, row_id, old_values))

            # --- 执行（单事务：任何失败整体回滚，批次状态保持 finished） ---
            for i, (action, table, row_id, old_values) in enumerate(validated):
                if action == REVERT_INSERT:
                    columns = _columns_of(cursor, table)
                    if _soft_invalidate_supported(cursor, table):
                        cursor.execute(
                            f"UPDATE `{table}` SET status = %s WHERE id = %s",
                            (_SOFT_INVALIDATE_STATUS, row_id),
                        )
                        if cursor.rowcount <= 0:
                            logger.info(
                                f"rollback_batch 软作废未命中行: {table}.id={row_id}"
                                "（不存在或已作废，容忍幂等重放）"
                            )
                    if "import_voided" in columns:
                        # R3-9c：导入作废标记（definitions 无 status 列 —— 走本列
                        # 作废；读侧 entry_assembly / export_center 按 0 过滤）
                        cursor.execute(
                            f"UPDATE `{table}` SET import_voided = 1 WHERE id = %s",
                            (row_id,),
                        )
                        if cursor.rowcount <= 0:
                            logger.info(
                                f"rollback_batch 作废标记未命中行: {table}.id={row_id}"
                                "（不存在或已作废，容忍幂等重放）"
                            )
                    if (not _soft_invalidate_supported(cursor, table)
                            and "import_voided" not in columns):
                        # MVP 口径：无 status 列也无 import_voided 列的表
                        # 只留痕不动行，不物理 DELETE
                        logger.info(
                            f"rollback_batch 软作废跳过（MVP 口径）: 表 {table} 无可写 "
                            f"status 列，行 {table}.id={row_id} 仅留痕未作废"
                        )
                else:
                    # old_values 含 updated_at 时随逐列一并恢复（R3-9a：显式
                    # 赋值优先于 ON UPDATE CURRENT_TIMESTAMP，见 docstring）
                    assignments = ", ".join(f"`{col}` = %s" for col in old_values)
                    cursor.execute(
                        f"UPDATE `{table}` SET {assignments} WHERE id = %s",
                        (*old_values.values(), row_id),
                    )
                    if cursor.rowcount <= 0:
                        logger.info(
                            f"rollback_batch 旧值恢复未命中行: {table}.id={row_id}"
                            "（不存在或值已同，容忍幂等重放）"
                        )
            cursor.execute(
                "UPDATE import_batches SET status = 'rolled_back' "
                "WHERE id = %s AND status = 'finished'",
                (bid,),
            )
            if cursor.rowcount <= 0:
                # 预检与执行间被并发改走状态：整体回滚（防覆盖终态）
                logger.error(f"rollback_batch 状态翻转失败: batch_id={bid}（并发变更，整体回滚）")
                raise RuntimeError("batch status changed during rollback")
        return True
    except pymysql.Error as e:
        logger.error(f"回滚导入批次 {bid} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"回滚导入批次 {bid} 意外错误: {e}")
        return False
