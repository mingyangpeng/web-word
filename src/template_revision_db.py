"""模板人工修订持久化 —— template_revisions 单表数据层（FX-38）。

是什么：
    「🧩 释义模板」页的**在线人工修订**数据面：编者对确定性引擎输出的四维
    模板文本做人工修订（增删槽位、调整措辞、补充句法说明），修订**按版本
    留痕**保存；引擎输出始终并存为基线，修订是叠加其上的人工层（论文 §6.2
    人机协同口径）。对应批注（261110 葛反馈）要求的「编者修订定稿」闭环。

数据链（不新建依赖，flow-tables 先例：模块内 ensure，不进 mysql_db 全量建
表清单，页面首用幂等建表）：
    template_revisions（本模块建表）→ cs_senses（sense_id 锚，src/category_study.py）

权限口径（单一事实源）：
    编纂职能 **editor + reviewer + dict_admin**（与 lexical_pages.CAN_EDIT_ROLES
    同集）；数据层写路径一律 require_role 闸（tool_settings_db 先例，纵深防御
    ——页面层另有 require_role_interactive 交互面闸，双层）；viewer/annotator/
    未登录拒绝。历史读取不设闸（页面本就登录可见）。

并发语义：
    建版本号走**单语句原子自增** —— ``INSERT … SELECT COALESCE(MAX(version),0)+1
    …``，同语句内完成「读最大版 + 插新行」，InnoDB 行锁保证同义位并发保存
    版本连续且不撞 UNIQUE，无需显式事务/先读后写。

清洗口径（仿 lexical_db._clean_*）：
    revision_text 非空字符串 ≤6000；note 可选 ≤500（None→""）；sense_ref 可选
    ≤64；actor 须为通过闸门的用户 dict（edited_by 取正整数 id，edited_by_name
    取 username；审计双列口径，tool_settings_db._actor_ref 同款）。

降级：
    表未建/库不可用时读面返回 None/空字典（fail-open，页面据此隐藏修订列），
    写面返回 {"ok": False, "reason": ...}（页面转 st.error 按因提示）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pymysql

from src.guards import require_role
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# 编纂职能角色集（单一事实源口径，与 lexical_pages.CAN_EDIT_ROLES 同集）
CAN_REVISE_ROLES = {"editor", "reviewer", "dict_admin"}

MAX_REVISION_TEXT_LEN = 6000
MAX_NOTE_LEN = 500
MAX_SENSE_REF_LEN = 64

TEMPLATE_REVISIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS template_revisions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category VARCHAR(64) NOT NULL,
  language VARCHAR(4) NOT NULL,
  sense_id INT NOT NULL,
  sense_ref VARCHAR(64) NULL,
  version INT NOT NULL,
  revision_text MEDIUMTEXT NOT NULL,
  note VARCHAR(500) NULL,
  edited_by INT NULL,
  edited_by_name VARCHAR(64) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_cat_lang_sense_ver (category, language, sense_id, version),
  KEY idx_tpl_rev_locate (category, language, sense_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_template_revision_tables() -> None:
    """幂等建 template_revisions（flow-tables 先例：页面首用调用，无需迁移）。"""
    with get_db_cursor() as cursor:
        cursor.execute(TEMPLATE_REVISIONS_TABLE_SQL)


# ---------- 清洗（仿 lexical_db._clean_*；非法一律 None → 应用层先拒） ----------
def _clean_revision_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_REVISION_TEXT_LEN:
        return None
    return text


def _clean_note(value: Any) -> str:
    """可选优化要点：None→""；非 str/超长→拒收（返回 "" 由调用方按拒收口径）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) > MAX_NOTE_LEN:
        return ""
    return text


def _clean_sense_ref(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    ref = value.strip()
    if not ref or len(ref) > MAX_SENSE_REF_LEN:
        return None
    return ref


def _clean_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _actor_ref(actor: Any) -> tuple:
    """从通过闸门的 actor dict 取留痕引用：(actor_id, actor_username)。"""
    if not isinstance(actor, dict):
        return None, None
    return actor.get("id"), actor.get("username")


def _norm_locate(category: Any, language: Any,
                 sense_id: Any) -> Optional[tuple]:
    """定位三元组规整：category/language 非空 str，sense_id 正整数。"""
    if not isinstance(category, str) or not category.strip():
        return None
    if not isinstance(language, str) or not language.strip():
        return None
    sid = _clean_positive_int(sense_id)
    if sid is None:
        return None
    return category.strip(), language.strip(), sid


# ---------- 写路径 ----------
def save_revision(category: Any, language: Any, sense_id: Any,
                  revision_text: Any, actor: Any, *,
                  note: Any = None, sense_ref: Any = None) -> Dict[str, Any]:
    """保存一条人工修订（版本单语句原子自增；历史全量留痕，最新版为现行）。

    - 权限：require_role(actor, CAN_REVISE_ROLES)，不满足抛 PermissionError；
    - 入参非法 → {"ok": False, "reason": ...}（页面按因转述，不抛）；
    - 表未建/库不可用 → {"ok": False, "reason": "db"}（页面 fail-open 提示）。
    """
    require_role(actor, CAN_REVISE_ROLES, action="模板人工修订")
    loc = _norm_locate(category, language, sense_id)
    if loc is None:
        logger.error("save_revision 拒绝非法定位入参: category=%r language=%r "
                     "sense_id=%r", category, language, sense_id)
        return {"ok": False, "reason": "定位参数非法（范畴/语言/义位）"}
    cat, lang, sid = loc
    text = _clean_revision_text(revision_text)
    if text is None:
        return {"ok": False,
                "reason": f"修订文本非法（须为非空字符串且 ≤{MAX_REVISION_TEXT_LEN} 字）"}
    note_text = _clean_note(note)
    if note is not None and (not isinstance(note, str)
                             or (note.strip() and not note_text)):
        # 非字符串 / 超长非空 → 拒收（fail-closed；纯空白串视为无 note 放行）
        return {"ok": False,
                "reason": f"优化要点非法（须为字符串且 ≤{MAX_NOTE_LEN} 字）"}
    ref = _clean_sense_ref(sense_ref)
    if sense_ref is not None and ref is None:
        return {"ok": False,
                "reason": f"sense_ref 非法（须为非空字符串且 ≤{MAX_SENSE_REF_LEN} 字）"}
    actor_id, actor_name = _actor_ref(actor)
    try:
        with get_db_cursor() as cursor:
            # 单语句原子建版：同语句内 MAX(version)+1，无先读后写竞态窗口
            cursor.execute(
                "INSERT INTO template_revisions "
                "(category, language, sense_id, sense_ref, version, "
                " revision_text, note, edited_by, edited_by_name) "
                "SELECT %s, %s, %s, %s, COALESCE(MAX(version), 0) + 1, "
                "       %s, %s, %s, %s "
                "FROM template_revisions "
                "WHERE category = %s AND language = %s AND sense_id = %s",
                (cat, lang, sid, ref, text, note_text or None,
                 actor_id if _clean_positive_int(actor_id) else None,
                 actor_name if isinstance(actor_name, str) else None,
                 cat, lang, sid),
            )
            cursor.execute(
                "SELECT version FROM template_revisions "
                "WHERE category = %s AND language = %s AND sense_id = %s "
                "ORDER BY version DESC LIMIT 1",
                (cat, lang, sid),
            )
            row = cursor.fetchone()
            version = int(row["version"]) if row else None
        logger.info("模板人工修订落库: %s/%s sense=%s → v%s (by %s)",
                    cat, lang, sid, version, actor_name)
        return {"ok": True, "version": version}
    except pymysql.Error as exc:
        logger.error("template_revisions 写入失败（%s/%s sense=%s）: %s",
                     cat, lang, sid, exc)
        return {"ok": False, "reason": "数据库写入失败"}


# ---------- 读路径（fail-open：库不可用返回 None/空，页面据此退化） ----------
def get_latest_revision(category: Any, language: Any,
                        sense_id: Any) -> Optional[Dict[str, Any]]:
    """单义位最新修订（无修订/库不可用 → None）。"""
    revs = get_latest_revisions(category, language, [sense_id])
    return revs.get(sense_id)


def get_latest_revisions(category: Any, language: Any,
                         sense_ids: List[Any]) -> Dict[int, Dict[str, Any]]:
    """批義位最新修订表（并排总览/CSV 回填用）。

    Returns:
        {sense_id: 修订行 dict}；仅含有修订的义位；定位非法的条目跳过；
        库不可用/表未建 → 空字典（fail-open）。
    """
    if not isinstance(sense_ids, (list, tuple)) or not sense_ids:
        return {}
    locs: List[tuple] = []
    seen = set()
    for sid in sense_ids:
        loc = _norm_locate(category, language, sid)
        if loc is not None and loc not in seen:
            seen.add(loc)
            locs.append(loc)
    if not locs:
        return {}
    where = " OR ".join(
        ["(r.category = %s AND r.language = %s AND r.sense_id = %s)"]
        * len(locs))
    params: List[Any] = []
    for cat, lang, sid in locs:
        params.extend([cat, lang, sid])
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT r.category, r.language, r.sense_id, r.sense_ref, "
                "       r.version, r.revision_text, r.note, "
                "       r.edited_by, r.edited_by_name, r.created_at "
                "FROM template_revisions r "
                "JOIN (SELECT category, language, sense_id, "
                "             MAX(version) AS max_version "
                "      FROM template_revisions GROUP BY category, language, "
                "           sense_id) m "
                "  ON r.category = m.category AND r.language = m.language "
                " AND r.sense_id = m.sense_id AND r.version = m.max_version "
                f"WHERE {where}",
                params,
            )
            rows = cursor.fetchall() or []
    except pymysql.Error as exc:
        logger.error("template_revisions 批量读取失败: %s", exc)
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            out[int(row["sense_id"])] = dict(row)
        except (TypeError, ValueError):
            continue
    return out


def list_revisions(category: Any, language: Any,
                   sense_id: Any) -> List[Dict[str, Any]]:
    """单义位全部修订历史（version DESC；库不可用 → 空列表）。"""
    loc = _norm_locate(category, language, sense_id)
    if loc is None:
        return []
    cat, lang, sid = loc
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT version, revision_text, note, edited_by, "
                "       edited_by_name, created_at "
                "FROM template_revisions "
                "WHERE category = %s AND language = %s AND sense_id = %s "
                "ORDER BY version DESC",
                (cat, lang, sid),
            )
            return [dict(r) for r in (cursor.fetchall() or [])]
    except pymysql.Error as exc:
        logger.error("template_revisions 历史读取失败（%s/%s sense=%s）: %s",
                     cat, lang, sid, exc)
        return []


def get_latest_notes(category: Any, language: Any,
                     sense_ids: List[Any]) -> Dict[int, str]:
    """批義位最新修订的优化要点（CSV「优化要点」列回填；fail-open 空字典）。"""
    revs = get_latest_revisions(category, language, sense_ids)
    return {sid: (r.get("note") or "") for sid, r in revs.items()}
