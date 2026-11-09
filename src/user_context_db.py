"""用户上下文域数据层 —— 5 表的建表与自人 CRUD（批次 7 Agent FX-31）。

规范出处：docs/spec/平台架构设计规范.md §6 D 域清单第 ⑨ 组（原文摘录）::

    ⑨ 用户上下文域 user_profiles · user_state(工作位置/续接点) · user_bookmarks
       · user_notes · draft_states(未提交表单自动保存)

及同文 §7「登录落地三分支」——「有续接点→上次位置（侧边栏『继续：…』）」、
「用户上下文（profiles/state/bookmarks/notes/draft_states）跨设备续接，
localStorage 备注阶段 2 一键上传合并」。

**规范只给了 5 张表名与一行用途注**（附录 A 同名单，未给列结构）——列结构
按用途最小设计，逐表在 DDL 注释与本 docstring 注明（任务口径：以规范表清单
为准建 5 表，规范未细列列结构则按用途最小设计）：

  user_profiles  用户偏好/界面设置（键值对）。规范把「界面设置」并入偏好
                 键值面（§7 登录落地三分支同一句提及 profiles 跨设备续接），
                 不单列第六张表 —— 键名约定 'ui.*' 即界面设置。
  user_state     工作位置/续接点（键值对，值通常为 JSON 串）。规范 §7 的
                 「上次位置（侧边栏『继续：…』）」取 state_key（如
                 'last_sense'）；「最近浏览（义位/词条足迹）」是续接点的
                 列表形态，约定存 state_key='recent_senses' 的 JSON 足迹，
                 不单列第六张表。
  user_bookmarks 书签/收藏（跳转快捷位）。多态软锚 anchor_type + anchor_id：
                 'sense'=义位（oald_senses.id 数字串）/ 'entry'=词条（词目
                 文本）/ 'page'=页面路由键 —— 页面锚不是数字，故 anchor_id
                 用 VARCHAR 存字符串形态（media_db 四锚全为数字行 id 用
                 INT，本表与它不同源，勿照抄）。
  user_notes     义位笔记（用户 × sense_id 一条私人笔记，编辑=覆盖）。
                 sense_id INT 软引用 oald_senses.id（义位唯一锚）。
  draft_states   未提交表单自动保存。form_key=表单标识（页面+表单名），
                 state_json=表单字段快照（JSON 列）。

域纪律（任务口径）：
  * 上下文域 = 必须归人：每表 user_id INT NOT NULL，且**数据层不收 user_id
    入参** —— 一律取会话 current_user()['id']（db_utils 单一实现点）；
    session 无登录 / 用户 dict 脏值（无有效 id）→ fail-closed 返回安全值
    （读 [] / 写 False），绝不触碰数据库 —— 上下文域是登录态功能；
  * 只读写自己的行：所有 SQL 的 WHERE 一律带会话派生的 user_id，无法越权
    （连参数入口都没有）；
  * 无外键（软引用，仓库惯例）；users 缺行不炸（登录态由 app 层保证）；
  * created_at / updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP，
    **更新语句手动刷 updated_at = NOW()**（dict_admin_db 回滚恢复 updated_at
    的既有先例；DDL 不加 ON UPDATE CURRENT_TIMESTAMP —— 刷新点显式在 SQL
    里，可测可审）；updated_at 永不回写 NULL（RV2-3 留痕列不发明 NULL 语义）；
  * RV2-3 留痕列 NULL 口径照仓库三分类落位：VARCHAR/TEXT/JSON NULL=动作
    尚未发生（bookmark 未填备注 / draft 无快照 / 键已建未设值）；
    user_notes.note NOT NULL=显式无内容（'' 即清空但保留行）；本域无
    「系统作业」行（每行必有主人，user_id NOT NULL）。

建表与容错（annotation_flow._FLOW_TABLE_DDLS 先例：表 DDL 定义在本模块，
ensure 惰性建表＋进程级哨兵直通，不改 src/mysql_db.py）：
  * ensure_user_context_tables() 幂等（CREATE TABLE IF NOT EXISTS）；成功后
    进程级哨兵 _TABLES_ENSURED 置位直通（cluster_analysis._ENSURED_SPLIT_TABLES
    同款语义：失败的表不置位，下次调用自动重试）；
  * 本模块 15 个 CRUD 每个入口都先走 ensure（哨兵置位后零开销直通）——UI
    接线方无需记得先建表；页面渲染入口也可以显式调用 ensure（无害）；
  * 库不可用：ensure 只记日志不抛异常；读函数返回 []、写函数返回 False，
    绝不打崩页面（与 users_db / llm_providers_db 容错口径一致）。

CRUD 面（每表 upsert / list / delete 一组，函数名同构）：
  upsert_profile / list_profiles / delete_profile          （user_profiles）
  upsert_state   / list_states   / delete_state            （user_state）
  upsert_bookmark / list_bookmarks / delete_bookmark        （user_bookmarks）
  upsert_note    / list_notes    / delete_note             （user_notes）
  upsert_draft   / list_drafts   / delete_draft             （draft_states）

  * upsert 一律 INSERT ... ON DUPLICATE KEY UPDATE（唯一键兜底并发），返回
    True=落库成功——**刻意不沿用 dict_admin_db.set_value 的 rowcount 语义**
    （值未变化的重复写 rowcount=0 会报 False）：用户偏好「再存一次没变化」
    是幂等成功不是失败；
  * 入参校验在任何 DB 访问之前生效（应用层先拒，非法值不进数据库，
    llm_providers_db 同款纪律）；键类参数 strip 后存（标识符，非用户原文），
    值/笔记/备注类参数原样存（用户数据，不替用户做清洗）。
"""

import json
import logging
from typing import Any, Dict, List, Optional

import pymysql

from src.db_utils import as_int, current_user
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)


# ============================================
# 建表 SQL（规范 §6 D⑨ 表名清单；列结构按用途最小设计，见模块 docstring）
# ============================================

USER_PROFILES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS user_profiles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL COMMENT '主人 users.id（软引用，无外键；会话派生）',
  pref_key VARCHAR(120) NOT NULL COMMENT '偏好键（含界面设置 ui.*）',
  pref_value TEXT NULL COMMENT '偏好值（原样字符串；NULL=键已建未设值，RV2-3 第 2 类）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_profiles (user_id, pref_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

USER_STATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS user_state (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL COMMENT '主人 users.id（软引用，无外键；会话派生）',
  state_key VARCHAR(120) NOT NULL COMMENT '状态键（last_sense=续接点；recent_senses=最近浏览足迹）',
  state_value TEXT NULL COMMENT '状态值（通常 JSON 串；NULL=键已建未设值，RV2-3 第 2 类）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_state (user_id, state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

USER_BOOKMARKS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS user_bookmarks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL COMMENT '主人 users.id（软引用，无外键；会话派生）',
  anchor_type ENUM('sense','entry','page') NOT NULL
    COMMENT '跳转锚类型：义位/词条/页面（多态软引用，锚形态各异，无外键）',
  anchor_id VARCHAR(120) NOT NULL
    COMMENT '锚值（sense=oald_senses.id 数字串；entry=词目文本；page=页面路由键）',
  title VARCHAR(200) NULL COMMENT '收藏显示名（NULL=未命名，展示时回退锚值，RV2-3 第 2 类）',
  note VARCHAR(500) NULL COMMENT '收藏备注（NULL=未填，RV2-3 第 2 类）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_bookmarks (user_id, anchor_type, anchor_id),
  KEY idx_user_bookmarks_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

USER_NOTES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS user_notes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL COMMENT '主人 users.id（软引用，无外键；会话派生）',
  sense_id INT NOT NULL COMMENT '义位锚 oald_senses.id（软引用，无外键；义位唯一锚规范）',
  note TEXT NOT NULL COMMENT '笔记正文（NOT NULL：''=显式清空但保留行，RV2-3 第 3 类）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_notes (user_id, sense_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

DRAFT_STATES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS draft_states (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL COMMENT '主人 users.id（软引用，无外键；会话派生）',
  form_key VARCHAR(150) NOT NULL COMMENT '表单标识（页面+表单名，如 definition_draft:sense:345）',
  state_json JSON NULL COMMENT '表单字段快照（JSON；NULL=键已建无内容快照，RV2-3 第 2 类）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_draft_states (user_id, form_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# 顺序无关（无外键、互不引用），照 _FLOW_TABLE_DDLS 元组先例统一遍历建表。
_USER_CONTEXT_TABLE_DDLS = (
    USER_PROFILES_TABLE_SQL,
    USER_STATE_TABLE_SQL,
    USER_BOOKMARKS_TABLE_SQL,
    USER_NOTES_TABLE_SQL,
    DRAFT_STATES_TABLE_SQL,
)

# user_bookmarks.anchor_type 的应用层白名单（与 DDL ENUM 同值同序；先拒非法
# 值不进数据库，MySQL ENUM 报错只是最后防线）。扩展新锚 = 改此常量＋存量库
# ALTER（ENUM 尾部追加对 MySQL 是安全变更），DDL 是契约。
BOOKMARK_ANCHOR_TYPES = ("sense", "entry", "page")


# ============================================
# 建表（幂等＋进程级哨兵）
# ============================================

# 进程级哨兵：成功置位后 ensure 直通（页面每次渲染都会走 CRUD 入口，惰性
# 建表只在进程首个 DB 可用的调用点发生一次）。失败不置位 —— 下次调用自动
# 重试（cluster_analysis._ENSURED_SPLIT_TABLES 同款语义）。测试直接置
# _TABLES_ENSURED = False 可强制重走 DDL 路径。
_TABLES_ENSURED = False


def ensure_user_context_tables() -> None:
    """惰性幂等创建用户上下文域 5 表（CREATE TABLE IF NOT EXISTS，可重复调用）。

    进程内成功一次后经 _TABLES_ENSURED 哨兵直通；数据库不可用时只记日志
    不抛异常（哨兵不置位，下次自动重试）——本模块被无 DB 环境读取时必须
    能静默降级（与 ensure_user_tables / ensure_llm_provider_tables 口径一致）。

    五表互不引用且无外键（软引用），单库可独立先建，不依赖 init_database
    的其他表。
    """
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    try:
        with get_db_cursor() as cursor:
            for ddl in _USER_CONTEXT_TABLE_DDLS:
                cursor.execute(ddl)
        _TABLES_ENSURED = True
        logger.info("用户上下文域 5 表就绪（user_profiles/user_state/user_bookmarks/"
                    "user_notes/draft_states）")
    except pymysql.Error as e:
        logger.error(f"用户上下文域 5 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"用户上下文域 5 表初始化意外错误: {e}")


# ============================================
# 会话归人与入参校验（应用层先拒，全部在任何 DB 访问之前生效）
# ============================================

def _resolve_user_id() -> Optional[int]:
    """会话 → user_id（fail-closed）。

    current_user() 非 dict / 缺 id / id 非正整数（bool 是 int 子类，as_int
    已先拦）→ None —— 上下文域是登录态功能，无有效主人一律拒绝，调用方
    拿 None 返回安全值（读 [] / 写 False），不触碰数据库。
    """
    user = current_user()
    if not isinstance(user, dict):
        return None
    uid = as_int(user.get("id"))
    if uid is None or uid <= 0:
        return None
    return uid


def _check_key(key: Any, limit: int) -> Optional[str]:
    """键类参数校验：str、strip 后非空、不超列宽；返回 strip 后的键。

    键是标识符不是用户原文，strip 后入库；非法 → None（调用方转安全值）。
    """
    if not isinstance(key, str):
        return None
    key = key.strip()
    if not key or len(key) > limit:
        return None
    return key


def _check_opt_text(value: Any, limit: int, sentinel: Any) -> Any:
    """可选文本：None→合法 None；str 合规→文本；其余→sentinel（拒绝哨兵）。"""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        return sentinel
    return value


# ============================================
# 通用 upsert / list / delete 内核（每表一组的同构实现点）
# ============================================

def _upsert_kv(table: str, key_col: str, value_col: str, key: Any, value: Any,
               key_limit: int) -> bool:
    """KV 两表（user_profiles / user_state）共用的 upsert 内核。

    value 严格收 str | None（None=NULL=键已建未设值；dict/list 等由调用方
    json.dumps 后传入 —— 数据层不偷偷序列化，避免「存进去的是啥」出现两种
    口径）。重复写同一值也是成功（幂等），见模块 docstring 返回值口径。
    fail-closed 顺序：入参校验 → 会话归人 → 才 ensure/触库（未登录零 DB 访问）。
    """
    if value is not None and not isinstance(value, str):
        return False
    clean_key = _check_key(key, key_limit)
    if clean_key is None:
        return False
    uid = _resolve_user_id()
    if uid is None:
        return False
    ensure_user_context_tables()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""INSERT INTO {table} (user_id, {key_col}, {value_col})
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      {value_col} = VALUES({value_col}),
                      updated_at = NOW()""",
                (uid, clean_key, value),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"写 {table} 失败（key={clean_key!r}）: {e}")
        return False
    except Exception as e:
        logger.error(f"写 {table} 意外错误（key={clean_key!r}）: {e}")
        return False


def _list_rows(table: str, columns: str, order_by: str) -> List[Dict[str, Any]]:
    """list 内核：只读会话主人的行；库不可用/未登录返回 []（fail-closed）。"""
    uid = _resolve_user_id()
    if uid is None:
        return []
    ensure_user_context_tables()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {columns} FROM {table} WHERE user_id = %s ORDER BY {order_by}",
                (uid,),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"读 {table} 失败（降级返回空列表）: {e}")
        return []
    except Exception as e:
        logger.error(f"读 {table} 意外错误（降级返回空列表）: {e}")
        return []


def _delete_own_row(table: str, where_col: str, where_val: Any) -> bool:
    """delete 内核：只删会话主人的行（WHERE 恒带 user_id）；0 行命中=False。

    删别人的行不是异常而是「无此行」——本函数根本没有越过 user_id 的入口。
    """
    uid = _resolve_user_id()
    if uid is None:
        return False
    ensure_user_context_tables()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {table} WHERE user_id = %s AND {where_col} = %s",
                (uid, where_val),
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"删 {table} 失败（key={where_val!r}）: {e}")
        return False
    except Exception as e:
        logger.error(f"删 {table} 意外错误（key={where_val!r}）: {e}")
        return False


# ============================================
# user_profiles —— 用户偏好/界面设置（键值对）
# ============================================

def upsert_profile(key: str, value: Optional[str]) -> bool:
    """写一条用户偏好（键值对；同键覆盖，updated_at 手动刷新）。"""
    return _upsert_kv("user_profiles", "pref_key", "pref_value",
                      key, value, 120)


def list_profiles() -> List[Dict[str, Any]]:
    """当前用户的全部偏好（按 pref_key 稳定序，UI 渲染免再排）。"""
    return _list_rows(
        "user_profiles",
        "id, pref_key, pref_value, created_at, updated_at",
        "pref_key ASC",
    )


def delete_profile(key: str) -> bool:
    """删除当前用户的一条偏好（无此键=False）。"""
    clean = _check_key(key, 120)
    if clean is None:
        return False
    return _delete_own_row("user_profiles", "pref_key", clean)


# ============================================
# user_state —— 工作位置/续接点/最近浏览足迹（键值对）
# ============================================

def upsert_state(key: str, value: Optional[str]) -> bool:
    """写一条工作状态（如 'last_sense'='42'、'recent_senses'='[41,42,43]'）。"""
    return _upsert_kv("user_state", "state_key", "state_value",
                      key, value, 120)


def list_states() -> List[Dict[str, Any]]:
    """当前用户的全部状态键值（按 updated_at 降序，最新续接点在前）。"""
    return _list_rows(
        "user_state",
        "id, state_key, state_value, created_at, updated_at",
        "updated_at DESC, id DESC",
    )


def delete_state(key: str) -> bool:
    """删除当前用户的一条状态（无此键=False）。"""
    clean = _check_key(key, 120)
    if clean is None:
        return False
    return _delete_own_row("user_state", "state_key", clean)


# ============================================
# user_bookmarks —— 书签/收藏（跳转快捷位）
# ============================================

def upsert_bookmark(anchor_type: str, anchor_id: str,
                    title: Optional[str] = None,
                    note: Optional[str] = None) -> bool:
    """收藏一个跳转位（同锚重复收藏=覆盖标题/备注，幂等）。

    Args:
        anchor_type: 锚类型，仅 BOOKMARK_ANCHOR_TYPES 三值（'sense'/'entry'/
            'page'），与 DDL ENUM 同值。
        anchor_id: 锚值（'sense' 传 oald_senses.id 的数字串；'entry' 传词目
            文本；'page' 传页面路由键）。软引用：本层不做存在性校验（锚
            校验归页面/集成层，同 media_db 口径）。
        title: 显示名（None=未命名）。
        note: 备注（None=未填）。
    """
    reject = object()
    if anchor_type not in BOOKMARK_ANCHOR_TYPES or not isinstance(anchor_id, str):
        return False
    anchor_id = anchor_id.strip()
    if not anchor_id or len(anchor_id) > 120:
        return False
    clean_title = _check_opt_text(title, 200, reject)
    if clean_title is reject:
        return False
    clean_note = _check_opt_text(note, 500, reject)
    if clean_note is reject:
        return False
    uid = _resolve_user_id()
    if uid is None:
        return False
    ensure_user_context_tables()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """INSERT INTO user_bookmarks
                     (user_id, anchor_type, anchor_id, title, note)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     title = VALUES(title),
                     note = VALUES(note),
                     updated_at = NOW()""",
                (uid, anchor_type, anchor_id, clean_title, clean_note),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"写 user_bookmarks 失败（anchor={anchor_type}:{anchor_id!r}）: {e}")
        return False
    except Exception as e:
        logger.error(f"写 user_bookmarks 意外错误（anchor={anchor_type}:{anchor_id!r}）: {e}")
        return False


def list_bookmarks() -> List[Dict[str, Any]]:
    """当前用户的全部收藏（按 updated_at 降序，最近收藏在前）。"""
    return _list_rows(
        "user_bookmarks",
        "id, anchor_type, anchor_id, title, note, created_at, updated_at",
        "updated_at DESC, id DESC",
    )


def delete_bookmark(anchor_type: str, anchor_id: str) -> bool:
    """取消收藏（无此锚=False；别人的收藏对本会话即「无此行」）。"""
    if anchor_type not in BOOKMARK_ANCHOR_TYPES or not isinstance(anchor_id, str):
        return False
    anchor_id = anchor_id.strip()
    if not anchor_id or len(anchor_id) > 120:
        return False
    return _delete_composite("user_bookmarks", anchor_type, anchor_id)


def _delete_composite(table: str, anchor_type: str, anchor_id: str) -> bool:
    """user_bookmarks 专用复合键 delete（anchor_type + anchor_id 双 WHERE）。"""
    uid = _resolve_user_id()
    if uid is None:
        return False
    ensure_user_context_tables()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """DELETE FROM user_bookmarks
                   WHERE user_id = %s AND anchor_type = %s AND anchor_id = %s""",
                (uid, anchor_type, anchor_id),
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"删 user_bookmarks 失败（anchor={anchor_type}:{anchor_id!r}）: {e}")
        return False
    except Exception as e:
        logger.error(f"删 user_bookmarks 意外错误（anchor={anchor_type}:{anchor_id!r}）: {e}")
        return False


# ============================================
# user_notes —— 义位笔记（用户 × sense_id 私人笔记）
# ============================================

def upsert_note(sense_id: Any, note: str) -> bool:
    """写当前用户在某义位上的私人笔记（同义位重写=覆盖，''=显式清空）。"""
    sid = as_int(sense_id)
    if sid is None or sid <= 0 or not isinstance(note, str):
        return False
    uid = _resolve_user_id()
    if uid is None:
        return False
    ensure_user_context_tables()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """INSERT INTO user_notes (user_id, sense_id, note)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     note = VALUES(note),
                     updated_at = NOW()""",
                (uid, sid, note),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"写 user_notes 失败（sense_id={sid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"写 user_notes 意外错误（sense_id={sid}）: {e}")
        return False


def list_notes() -> List[Dict[str, Any]]:
    """当前用户的全部义位笔记（按 updated_at 降序，最近编辑在前）。"""
    return _list_rows(
        "user_notes",
        "id, sense_id, note, created_at, updated_at",
        "updated_at DESC, id DESC",
    )


def delete_note(sense_id: Any) -> bool:
    """删除当前用户在某义位的笔记（无此行=False）。"""
    sid = as_int(sense_id)
    if sid is None or sid <= 0:
        return False
    return _delete_own_row("user_notes", "sense_id", sid)


# ============================================
# draft_states —— 未提交表单自动保存
# ============================================

def upsert_draft(form_key: str, state: Any) -> bool:
    """保存表单快照（同 form_key 覆盖；state 收 dict/list/None）。

    dict/list 由本层统一 json.dumps（ensure_ascii=False —— 中文原样可读）；
    None=NULL（建键但清空快照）；str 拒收（是否已序列化存在二义性，入口
    先拒 —— 要存 JSON 串请走 upsert_state）。
    """
    clean_key = _check_key(form_key, 150)
    if clean_key is None:
        return False
    if state is not None and not isinstance(state, (dict, list)):
        return False
    uid = _resolve_user_id()
    if uid is None:
        return False
    ensure_user_context_tables()
    try:
        # json.dumps 放 try 内：循环引用等罕见脏结构也走统一降级（False）
        payload = (json.dumps(state, ensure_ascii=False)
                   if state is not None else None)
        with get_db_cursor() as cursor:
            cursor.execute(
                """INSERT INTO draft_states (user_id, form_key, state_json)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     state_json = VALUES(state_json),
                     updated_at = NOW()""",
                (uid, clean_key, payload),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"写 draft_states 失败（form={clean_key!r}）: {e}")
        return False
    except Exception as e:
        logger.error(f"写 draft_states 意外错误（form={clean_key!r}）: {e}")
        return False


def list_drafts() -> List[Dict[str, Any]]:
    """当前用户的全部表单快照（按 updated_at 降序，最近自动保存在前）。"""
    return _list_rows(
        "draft_states",
        "id, form_key, state_json, created_at, updated_at",
        "updated_at DESC, id DESC",
    )


def delete_draft(form_key: str) -> bool:
    """清除当前用户的表单快照（表单已正式提交后由页面调用；无此键=False）。"""
    clean = _check_key(form_key, 150)
    if clean is None:
        return False
    return _delete_own_row("draft_states", "form_key", clean)
