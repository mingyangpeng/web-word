"""导入业务写入映射引擎 —— definitions 词目层 UPSERT（批次 5，Agent Q，敏感写路径）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§15（数据出入口纪律——**导入同权**：
导入向导/批量灌库的业务数据操作**仅词典管理员**，平台管理员不碰业务数据）与
§6 D① 域（definitions 词目层＝展示投影）；契约：docs/spec/阶段1施工规范.md §8
（批次 5 Agent Q 行）；回滚口径：src/dict_admin_db.py rollback_batch（**只读对齐**，
本模块不改其文件）。

是什么（两个入口，页面层 src/data_pages.py 数据导入向导第三步调用）：
  * plan_import(rows, mapping) —— **纯函数**（零 DB 访问，可单测）：按「列名 →
    目标字段」映射产出导入计划：合法行（含规整后的写入值）／非法行（含中文原因）；
  * run_import(rows, mapping, operator, dry_run=True) —— 执行引擎。**默认干跑**：
    dry_run=True 只做 SELECT 读库、返回将写入的变更预览（谁会 INSERT、谁会
    UPDATE、每字段旧值→新值），**零写库**；dry_run=False 才逐行 UPSERT
    definitions（键 = verb），并逐行收集 revert_log 供 dict_admin_db
    rollback_batch 回滚。

目标字段白名单（definitions 实测 SHOW COLUMNS，2026-11）：
  * verb          VARCHAR(100) NOT NULL UNIQUE —— UPSERT 键，本身永不被 UPDATE
                  （键标识行；映射到 verb 的列是「键列」，不是可覆盖字段）；
  * chinese_ndef  TEXT NOT NULL —— 中文释义（导入主载荷；行级必填，空值拒绝——
                  NOT NULL 且空释义是垃圾数据，入口拒、不留歧义行）；
  * phonetic      VARCHAR(64) NULL —— 音标（可选；**空值跳过写入**，避免误映射
                  的空列把库内已有音标批量抹掉）。
  映射必须含 verb（键列）与 chinese_ndef（主载荷）——缺 chinese_ndef 时新词目
  行无法成型（NOT NULL），phonetic-only 的映射口径不支持（如实拒绝）；phonetic
  可选。白名单之外的目标字段一律拒（数据层入口校验，不依赖 MySQL 报错）。
  SET/INSERT 列名只可能出自本模块常量元组 —— 动态拼列名的注入面被白名单封死，
  值全走占位符。

cluster_id 保留纪律（沿用既有灌库 UPSERT 约定，src/mysql_db.py
insert_definition 的 ``cluster_id = COALESCE(VALUES(cluster_id), cluster_id)``）：
  簇归属（definitions.cluster_id → word_clusters）不是导入映射的目标字段，本
  引擎对既有行采用「SELECT 旧值 → 只 UPDATE 变更的映射字段」的行级写法，
  **cluster_id 绝不出现在 UPDATE SET 列表** —— 与 COALESCE(VALUES(cluster_id),
  cluster_id) 的「不覆盖现值」语义等价；新 INSERT 行 cluster_id 显式置 NULL
  （新词目尚无簇归属，留给聚类工序）。行级 revert_log 必须先读旧值，因此不复用
  单条 INSERT ... ON DUPLICATE KEY UPDATE，保留语义等价并在此声明。

revert_log 事件格式（**逐字对齐** dict_admin_db.REVERT_ACTIONS / rollback_batch
的预校验，勿改字段名）：
  * 覆盖既有行：{"action": "update", "table": "definitions", "row_id": <id>,
    "old_values": {仅被本次导入改写的列: 覆盖前旧值, ...}} —— 回滚按 old_values
    恢复旧值；行内容与现值完全相同时**不发事件**（无变更无可回滚，且
    rollback_batch 拒绝 old_values 为空的 update 事件）；
  * 新增词目行：{"action": "insert", "table": "definitions", "row_id": <新id>}。

insert 回滚的**如实限制**（先读 dict_admin_db.rollback_batch 实现后定的口径）：
  definitions 表**没有 status 列**（实测 SHOW COLUMNS），rollback_batch 的
  软作废（UPDATE ... SET status='deprecated'）对它不生效 —— 该实现遇到无
  status 列的表**只留痕不动行、绝不物理 DELETE**。因此新词目行回滚后的状态是
  「批次标记 rolled_back、行仍在库中可审计追溯」，而非行消失；物理清理留给
  后续版本的专门运维流程。本模块因此**沿用标准 action='insert' 事件**（不发明
  'insert_hard' 之类私有动作 —— REVERT_ACTIONS 白名单外的 action 会被
  rollback_batch 整体拒绝，破坏整套回滚）。

打标不删行纪律（§6 D 域「版本化、不删行」）：
  * 本引擎**不物理 DELETE 任何行**（只有 update/insert 两种写、零删）；
  * UPDATE 前必读旧值（revert_log.old_values 的唯一来源，先读后写）；
  * SQL 全参数化；唯一动态片段是 SET 列名，取值限定 TARGET_FIELDS 白名单。

**不支持 oald_senses 追加写入**（如实声明，留批次 6 评审）：本引擎只写
definitions 词目层（词目的中文释义/音标投影）；把导入行灌成 oald_senses 义项
行（义位锚、sense_index 体系）涉及义位准入语义，本批次不做 —— 映射目标出现
oald_senses 相关字段一律按白名单拒绝，不假装支持。

**权限要求（§15 导入同权）**：本引擎仅词典管理员可驱动 —— 页面层闸门
（src/data_pages.py render_import_page 入口 _is_dict_admin 判定 ＋ 集成接线
的中央闸门 require_dict_admin）拦截后调用；operator 必填（操作人 users.id，
审计留痕）。引擎自身不做角色判定（与 dict_admin_db 同口径：页面/服务层闸门
负责，docstring 标注以便核对）。

revert_log 的存放位置（页面接线口径）：run_import 只返回 revert_log 清单；
import_batches 表无 revert_log 列，页面把它暂存会话（st.session_state），
「执行写入 → finish_batch 记账 → 回滚按钮启用 → rollback_batch(batch_id,
revert_log)」须在同一会话内完成；会话丢失则 revert_log 不可恢复（页面如实
提示，持久化留后续版本）。

接口（契约 §8-Agent Q）：
  plan_import(rows, mapping) -> dict
  run_import(rows, mapping, operator, dry_run=True) -> dict
  TARGET_FIELDS（目标字段白名单，页面映射下拉据此渲染）

降级：数据库不可用时 run_import 返回 ok=False 的结果 dict（连接错误在
get_db_cursor 记日志后重抛，本引擎兜住转结果，不让异常穿透到页面）；干跑与
纯函数路径不写库，本地与 CI 全可跑。

安全规则（全体遵守）：
  1. SQL 一律参数化；动态片段仅 SET/INSERT 列名（TARGET_FIELDS 白名单常量
     成员，绝不接受调用方原文拼 SQL）；
  2. 映射在应用层先校验再执行（白名单外目标字段/缺 verb 键/缺 chinese_ndef
     主载荷/一字段多列映射一律整批拒绝，不留歧义写入）；
  3. 单元格值规整为字符串（None/NaN → 空串；str 去首尾空白）后才校验入库，
     Excel/CSV 的脏类型不直接进 SQL。
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（目标字段白名单 —— definitions 实测列；页面映射下拉同源渲染）
# ============================================

# UPSERT 键：映射到 verb 的列提供每行的词目键；verb 本身永不被 UPDATE。
KEY_FIELD = "verb"

# 主载荷字段：映射必含（新词目行 chinese_ndef NOT NULL，缺它则 INSERT 无法成型）。
PAYLOAD_FIELD = "chinese_ndef"

# 可写字段白名单（键 + 两个可覆盖字段）。SET/INSERT 列名只可能出自这里；
# cluster_id 等其余列一律不在写域内（簇归属保留语义见模块 docstring）。
TARGET_FIELDS = ("verb", "chinese_ndef", "phonetic")

# 列宽/长度上限（与 definitions 实测列一致；chinese_ndef 为 TEXT，取
# dict_admin_db.MAX_VALUE_TEXT_LEN 同款 10000 字符保守上限）。
MAX_VERB_LEN = 100            # verb VARCHAR(100)
MAX_PHONETIC_LEN = 64         # phonetic VARCHAR(64)
MAX_CHINESE_NDEF_LEN = 10000  # chinese_ndef TEXT（utf8mb4 字节上限内的保守值）

# 目标表（revert_log.table 逐字对齐 rollback_batch 的表名校验）。
TARGET_TABLE = "definitions"

# 新词目行 semantic_table 的结构占位（JSON NOT NULL 列；非映射白名单字段，
# 语义由后续工序补齐 —— 如实占位为空对象，不编造内容）。
INSERT_SEMANTIC_PLACEHOLDER = "{}"

# 行内规整后实际参与读写的数据字段（排除键；由映射决定，顺序随白名单）。
_DATA_FIELDS = tuple(f for f in TARGET_FIELDS if f != KEY_FIELD)


# ============================================
# 入参规整（纯函数）
# ============================================

def _cell_str(value: Any) -> str:
    """单元格值规整为字符串（纯函数）：None/NaN → ''；str 去首尾空白；
    其余（数字/日期等 Excel 类型）str() 后去空白。"""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def validate_mapping(mapping: Any) -> Tuple[Optional[Dict[str, str]], List[str]]:
    """校验「列名 → 目标字段」映射（纯函数；plan_import / run_import 共用）。

    口径（应用层先拒，非法映射不留歧义写入）：
      * mapping 须为非空 dict，键（列名）与非空 str 值（目标字段）；
      * 目标字段必须 ∈ TARGET_FIELDS 白名单（oald_senses 等一律拒）；
      * **一字段至多一列**（两列映射到同一字段属映射歧义，整批拒绝）；
      * 必须含 verb 键列与 chinese_ndef 主载荷列（缺任一则行无法定位或
        INSERT 无法成型 —— 见模块 docstring「目标字段白名单」）。

    Returns:
        (mapping_norm, errors)：合法时 ({列名: 字段}, [])；非法时
        (None, [中文原因, ...])。
    """
    if not isinstance(mapping, dict) or not mapping:
        return None, ["映射须为非空的「列名 → 目标字段」dict"]
    errors: List[str] = []
    norm: Dict[str, str] = {}
    seen_targets: Dict[str, str] = {}
    for col, field in mapping.items():
        if not isinstance(col, str) or not col.strip():
            errors.append("映射的列名须为非空字符串")
            continue
        if not isinstance(field, str) or field.strip() not in TARGET_FIELDS:
            errors.append(
                f"列「{col.strip()}」的目标字段 {field!r} 不在白名单 "
                f"{list(TARGET_FIELDS)} 内（oald_senses 追加写入不支持，批次 6 评审）"
            )
            continue
        clean_col = col.strip()
        clean_field = field.strip()
        if clean_field in seen_targets:
            errors.append(
                f"目标字段「{clean_field}」被两列映射（「{seen_targets[clean_field]}」"
                f"与「{clean_col}」）—— 一字段至多一列，映射歧义整批拒绝"
            )
            continue
        seen_targets[clean_field] = clean_col
        norm[clean_col] = clean_field
    if KEY_FIELD not in seen_targets:
        errors.append(f"映射缺少目标字段「{KEY_FIELD}」（UPSERT 键列必选）")
    if PAYLOAD_FIELD not in seen_targets:
        errors.append(
            f"映射缺少目标字段「{PAYLOAD_FIELD}」（中文释义为导入主载荷，"
            "新词目行 chinese_ndef NOT NULL，phonetic-only 映射口径不支持）"
        )
    if errors or not norm:
        return None, errors
    return norm, []


# ============================================
# plan_import（纯函数，零 DB 访问）
# ============================================

def plan_import(rows: Any, mapping: Any) -> Dict[str, Any]:
    """按映射产出导入计划（**纯函数**，零 DB 访问，可单测）。

    校验口径（行级，非法行带中文原因进 rejected，不影响其余行）：
      * 行须为 dict（否则「行格式非法」）；
      * verb：规整后非空且 ≤{MAX_VERB_LEN} 字符 —— 它是 UPSERT 键；
      * chinese_ndef：规整后非空且 ≤{MAX_CHINESE_NDEF_LEN} 字符（NOT NULL 且
        空释义是垃圾数据，入口拒）；
      * phonetic：≤{MAX_PHONETIC_LEN} 字符；**空值合法** —— 执行时跳过写入
        保留现值（见模块 docstring「phonetic 空值跳过」）；
      * 同一文件内 verb 重复：仅首行有效，后续重复行拒绝（确定性口径，不玩
        「后者覆盖前者」的隐式语义）。

    Args:
        rows: 行清单（list[dict]，键 = 列名；Excel/CSV 解析产物，值可为
              None/NaN/数字/字符串）
        mapping: 「列名 → 目标字段」dict（validate_mapping 口径）

    Returns:
        dict: {rows_total, rows_ok, rows_rejected, valid_rows, rejected,
        mapping_errors}。
          * valid_rows: [{"row_index": i, "verb": v, "values": {字段: 规整值}}]
            （values 只含映射字段的写入值，含 verb 键值）；
          * rejected: [{"row_index": i, "reason": 中文原因}]；
          * mapping_errors 非空 = 映射级非法：整批拒绝（rows_ok=0，
            rows_rejected=len(rows)，每行 reason 取第一条映射原因）。
    """
    if not isinstance(rows, (list, tuple)):
        _, errors = validate_mapping(mapping)
        errors = errors + ["rows 须为 list[dict]（每行「列名 → 单元格值」）"]
        return {
            "rows_total": 0,
            "rows_ok": 0,
            "rows_rejected": 0,
            "valid_rows": [],
            "rejected": [],
            "mapping_errors": errors,
        }

    norm, errors = validate_mapping(mapping)
    if norm is None:
        first = errors[0] if errors else "映射非法"
        return {
            "rows_total": len(rows),
            "rows_ok": 0,
            "rows_rejected": len(rows),
            "valid_rows": [],
            "rejected": [{"row_index": i, "reason": first} for i in range(len(rows))],
            "mapping_errors": errors,
        }

    verb_col = next(c for c, f in norm.items() if f == KEY_FIELD)
    data_fields = [f for f in _DATA_FIELDS if f in norm.values()]
    field_col = {f: c for c, f in norm.items()}  # 字段 → 源列（norm 的反向查表）

    valid_rows: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    seen_verbs: Dict[str, int] = {}

    for i, row in enumerate(rows):
        reason = ""
        values: Dict[str, str] = {}
        if not isinstance(row, dict):
            reason = "行格式非法（须为「列名 → 值」的键值对）"
        else:
            verb = _cell_str(row.get(verb_col))
            if not verb:
                reason = f"{KEY_FIELD}（词目键）为空"
            elif len(verb) > MAX_VERB_LEN:
                reason = (
                    f"{KEY_FIELD} 超长（>{MAX_VERB_LEN} 字符，"
                    f"列宽 VARCHAR({MAX_VERB_LEN})）"
                )
            elif verb in seen_verbs:
                reason = f"{KEY_FIELD} 与文件中第 {seen_verbs[verb] + 1} 行重复"
            else:
                for field in data_fields:
                    text = _cell_str(row.get(field_col[field]))
                    if field == PAYLOAD_FIELD:
                        if not text:
                            reason = "chinese_ndef（中文释义）为空（导入主载荷必填）"
                            break
                        if len(text) > MAX_CHINESE_NDEF_LEN:
                            reason = f"chinese_ndef 超长（>{MAX_CHINESE_NDEF_LEN} 字符）"
                            break
                    elif field == "phonetic" and len(text) > MAX_PHONETIC_LEN:
                        reason = (
                            f"phonetic 超长（>{MAX_PHONETIC_LEN} 字符，"
                            f"列宽 VARCHAR({MAX_PHONETIC_LEN})）"
                        )
                        break
                    values[field] = text
                if not reason:
                    values[KEY_FIELD] = verb
                    seen_verbs[verb] = i

        if reason:
            rejected.append({"row_index": i, "reason": reason})
        else:
            valid_rows.append({"row_index": i, "verb": verb, "values": values})

    return {
        "rows_total": len(rows),
        "rows_ok": len(valid_rows),
        "rows_rejected": len(rejected),
        "valid_rows": valid_rows,
        "rejected": rejected,
        "mapping_errors": [],
    }


# ============================================
# run_import（执行引擎；dry_run=True 默认零写库）
# ============================================

def _fatal_result(rows_total: int, error: str) -> Dict[str, Any]:
    """致命失败（操作人非法 / 映射非法 / 数据库异常）的统一结果骨架。"""
    return {
        "ok": False,
        "dry_run": None,
        "rows_total": rows_total,
        "rows_ok": 0,
        "rows_rejected": 0,
        "revert_log": [],
        "preview": [],
        "rejected": [],
        "mapping_errors": [],
        "error": error,
    }


def _mapped_data_fields(plan: Dict[str, Any]) -> List[str]:
    """本次计划实际映射到的数据字段（排除键；顺序随白名单，SELECT/diff 共用）。"""
    mapped = {f for item in plan["valid_rows"] for f in item["values"]}
    return [f for f in _DATA_FIELDS if f in mapped]


def _fetch_existing(cursor, verb: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    """按 verb 精确读既有行（id + 指定字段现值；**只读**，update 前必读旧值）。

    Returns:
        dict | None：{"id": int, <字段>: 现值, ...}；不存在返回 None。
        列名出自 TARGET_FIELDS 白名单成员（常量拼接，非用户输入），值走占位符。
    """
    cols = ", ".join(fields)  # fields ⊆ _DATA_FIELDS ⊆ TARGET_FIELDS 白名单
    cursor.execute(f"SELECT id, {cols} FROM definitions WHERE verb = %s", (verb,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _diff_changes(
    existing: Dict[str, Any], values: Dict[str, str], fields: List[str],
) -> Dict[str, Dict[str, Any]]:
    """计算既有行会被改写的字段（{字段: {"old": 旧值, "new": 新值}}）。

    口径：
      * 通用：新旧相等不写（值相同的字段不进 SET、revert_log 不收 —— 无变更
        无可回滚，且 rollback_batch 拒绝 old_values 为空的 update 事件）；
      * phonetic：**新值为空跳过**（空单元格不清库内现值）；旧值 None 与规整
        空串视为一致；
      * verb 不在 fields（键字段只定位、不覆盖）。
    """
    changes: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        new = values.get(field, "")
        old = existing.get(field)
        old_str = "" if old is None else str(old)
        if field == "phonetic" and not new:
            continue  # 空音标跳过写入，保留现值
        if new != old_str:
            changes[field] = {"old": old, "new": new}
    return changes


def _insert_row(cursor, values: Dict[str, str]) -> int:
    """INSERT 新词目行，返回新 id（**打标不删行纪律：只有写，无删**）。

    列与值口径：verb/chinese_ndef 必写；phonetic 仅非空时写（否则走列默认
    NULL）；semantic_table 写空对象占位（NOT NULL 结构占位，见模块 docstring）；
    cluster_id 显式 NULL（新词目尚无簇归属）。全部值走占位符，列名为常量。
    """
    cols = ["verb", PAYLOAD_FIELD, "semantic_table", "cluster_id"]
    params: List[Any] = [values[KEY_FIELD], values[PAYLOAD_FIELD],
                         INSERT_SEMANTIC_PLACEHOLDER, None]
    if values.get("phonetic"):
        cols.append("phonetic")
        params.append(values["phonetic"])
    placeholders = ", ".join(["%s"] * len(cols))
    cursor.execute(
        f"INSERT INTO definitions ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(params),
    )
    return int(cursor.lastrowid)


def _update_row(cursor, row_id: int, changes: Dict[str, Dict[str, Any]]) -> None:
    """按变更集 UPDATE 既有行（SET 列 ⊆ TARGET_FIELDS 白名单，值全占位符）。

    cluster_id 不在变更集内（白名单外）——「COALESCE 保留现值」语义见模块
    docstring；**打标不删行**：只 UPDATE，绝不 DELETE。
    """
    assignments = ", ".join(f"{field} = %s" for field in changes)
    params = [changes[f]["new"] for f in changes] + [row_id]
    cursor.execute(
        f"UPDATE definitions SET {assignments} WHERE id = %s",  # noqa: S608 — 列名为白名单常量
        tuple(params),
    )


def _apply_update(cursor, existing: Dict[str, Any], values: Dict[str, str],
                  fields: List[str], revert_log: List[Dict[str, Any]]) -> None:
    """既有行的更新路径：diff → UPDATE 仅变更字段 → 收 update 型 revert_log。

    无变更时不写库、不发事件（幂等重放口径，回滚无可恢复之物）。
    """
    changes = _diff_changes(existing, values, fields)
    if not changes:
        return
    row_id = int(existing["id"])
    _update_row(cursor, row_id, changes)
    revert_log.append({
        "action": "update",
        "table": TARGET_TABLE,
        "row_id": row_id,
        "old_values": {f: changes[f]["old"] for f in changes},
    })


def run_import(rows: Any, mapping: Any, operator: Any, dry_run: bool = True) -> Dict[str, Any]:
    """按映射执行导入（**默认干跑，零写库**；显式 dry_run=False 才写库）。

    **权限要求（§15 导入同权）**：仅词典管理员可驱动（页面层闸门拦截后调用）；
    operator 必填（操作人 users.id，审计留痕，非法整批拒绝）。

    执行流程（dry_run=False）：
      1. plan_import 产计划（映射非法 → 整批拒绝；行级口径见 plan_import）；
      2. 逐合法行：SELECT 既有行（**update 前必读旧值**）→ 存在则 UPDATE 仅
         变更的映射字段（cluster_id 等白名单外字段永不触碰）；不存在则 INSERT
         新词目行；
      3. 逐行收集 revert_log（update→old_values；insert→新 id）；
      4. 行级写失败记 rejected 继续、不中断整批；数据库级异常转 ok=False 结果
         （已收集的 revert_log 原样返回 —— 部分写入也必须可回滚）。

    INSERT 撞 UNIQUE（SELECT 后、INSERT 前被并发写入 verb 的窄窗口）：重读该
    行并按「既有行」路径走 UPDATE + old_values 留痕（revert_log 完整性优先于
    乐观路径；重读仍不存在或再失败按行拒绝）。

    干跑（dry_run=True，默认）：只对合法行做 SELECT 读库，产出变更预览
    （insert / update+diff / none 三态），**零写库**、revert_log 恒为空；
    未显式 dry_run=False 的任何调用路径都不会写库。

    Args:
        rows: 行清单（list[dict]，列名 → 单元格值）
        mapping: 「列名 → 目标字段」dict（目标字段 ∈ TARGET_FIELDS）
        operator: 操作人 users.id（正整数；审计留痕）
        dry_run: True=干跑（默认，零写库）；False=实际写入

    Returns:
        dict: {ok, dry_run, rows_total, rows_ok, rows_rejected, revert_log,
        preview, rejected, mapping_errors[, error]}。
          * rows_ok/rows_rejected：干跑 = 计划口径；实跑 = 实际写成/拒绝行数
            （rows_ok + rows_rejected == rows_total）；
          * revert_log：dict_admin_db.rollback_batch 事件清单（干跑恒空）；
          * preview（仅干跑）：[{"row_index", "verb", "action":
            "insert"|"update"|"none", "changes": {字段: {"old","new"}},
            "row_id"}]；
          * ok=False：致命失败（映射非法/操作人非法/数据库异常）；映射非法时
            rows_rejected=len(rows)、rejected 带逐行原因；数据库异常时
            revert_log 保留已收集部分（部分写入可回滚），error 带中文原因。
    """
    total = len(rows) if isinstance(rows, (list, tuple)) else 0

    op = operator if isinstance(operator, int) and not isinstance(operator, bool) else None
    if op is None or op <= 0:
        return _fatal_result(
            total,
            f"operator 非法: {operator!r}（须为操作人 users.id 正整数，§15 导入同权审计留痕）",
        )

    plan = plan_import(rows, mapping)
    if plan["mapping_errors"]:
        result = _fatal_result(total, "映射非法：整批拒绝（见 mapping_errors / rejected 明细）")
        result["mapping_errors"] = plan["mapping_errors"]
        result["rejected"] = plan["rejected"]
        result["rows_rejected"] = plan["rows_rejected"]
        return result

    fields = _mapped_data_fields(plan)
    result: Dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "rows_total": plan["rows_total"],
        "rows_ok": 0,
        "rows_rejected": plan["rows_rejected"],
        "revert_log": [],
        "preview": [],
        "rejected": list(plan["rejected"]),
        "mapping_errors": [],
    }

    if not plan["valid_rows"]:
        return result  # 无可执行行（全拒绝/空文件）：零读写，直接返回计划口径

    try:
        if dry_run:
            with get_db_cursor() as cursor:
                for item in plan["valid_rows"]:
                    existing = _fetch_existing(cursor, item["verb"], fields)
                    if existing is None:
                        entry: Dict[str, Any] = {
                            "row_index": item["row_index"],
                            "verb": item["verb"],
                            "action": "insert",
                            "changes": {
                                f: {"old": None, "new": item["values"][f]}
                                for f in fields if item["values"].get(f)
                            },
                            "row_id": None,
                        }
                    else:
                        changes = _diff_changes(existing, item["values"], fields)
                        entry = {
                            "row_index": item["row_index"],
                            "verb": item["verb"],
                            "action": "update" if changes else "none",
                            "changes": changes,
                            "row_id": int(existing["id"]),
                        }
                    result["preview"].append(entry)
            result["rows_ok"] = len(plan["valid_rows"])
            return result

        # --- 实写路径（dry_run=False）---
        written = 0
        with get_db_cursor() as cursor:
            for item in plan["valid_rows"]:
                verb = item["verb"]
                values = item["values"]
                try:
                    existing = _fetch_existing(cursor, verb, fields)
                    if existing is not None:
                        _apply_update(cursor, existing, values, fields, result["revert_log"])
                        written += 1  # 含「无变更」的幂等行（同样计 ok）
                        continue
                    # 新词目行：INSERT（撞 UNIQUE 的窄窗口 → 重读走 UPDATE 路径）
                    try:
                        new_id = _insert_row(cursor, values)
                    except pymysql.err.IntegrityError as e:
                        if not e.args or int(e.args[0]) != 1062:
                            raise
                        logger.warning(f"INSERT 撞 UNIQUE（verb={verb!r}），改走 UPDATE 路径")
                        existing = _fetch_existing(cursor, verb, fields)
                        if existing is None:
                            raise
                        _apply_update(cursor, existing, values, fields, result["revert_log"])
                        written += 1
                        continue
                    result["revert_log"].append({
                        "action": "insert",
                        "table": TARGET_TABLE,
                        "row_id": new_id,
                    })
                    written += 1
                except pymysql.Error as e:
                    logger.error(
                        f"导入行写入失败（row_index={item['row_index']}, verb={verb!r}）: {e}"
                    )
                    result["rejected"].append({
                        "row_index": item["row_index"],
                        "reason": f"写入失败（数据库）：{e}",
                    })
                    result["rows_rejected"] += 1
        result["rows_ok"] = written
        logger.info(
            f"导入执行完成（operator={op}, dry_run=False）：ok={written}, "
            f"rejected={result['rows_rejected']}, revert_log={len(result['revert_log'])} 条"
        )
        return result
    except pymysql.Error as e:
        # 数据库级异常：已发生的写入必须仍可回滚 → revert_log 原样返回
        logger.error(f"导入执行数据库异常（已收集 revert_log {len(result['revert_log'])} 条）: {e}")
        fatal = _fatal_result(total, f"数据库异常，导入中止（已写入部分见 revert_log，可据此回滚）: {e}")
        fatal["revert_log"] = result["revert_log"]
        fatal["rows_ok"] = result["rows_ok"]
        fatal["rows_rejected"] = result["rows_rejected"]
        fatal["rejected"] = result["rejected"]
        return fatal
    except Exception as e:
        logger.error(f"导入执行意外异常: {e}")
        fatal = _fatal_result(total, f"意外异常，导入中止: {e}")
        fatal["revert_log"] = result["revert_log"]
        fatal["rows_ok"] = result["rows_ok"]
        fatal["rows_rejected"] = result["rows_rejected"]
        fatal["rejected"] = result["rejected"]
        return fatal
