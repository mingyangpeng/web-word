"""项目广播数据层 —— 规范 §8②组「项目广播」的最小诚实版（FX-30）。

是什么：
  词典管理员面向**在册项目全体成员**的公告域：project_broadcasts 表
  （发布留痕，只增不改不删 —— 广播是「公示」不是「待办」，见下「规范口径」）。
  发布入口在词典管理区·项目成员 tab（dict_admin_pages._render_broadcast_section），
  展示面在协作收件箱顶部（collab_pages._render_broadcast_banner）。

规范口径（docs/spec/平台架构设计规范.md §8 原文，grep「广播」共 3 处）：
  * 角色职责表：词典管理员「…出版批准…、**项目广播**、主编驾驶舱 | reviewer」
    —— 发布权归词典管理员（本模块 require_role 闸）；
  * 关键规则：「**项目广播**：project_announcements（登录横幅＋收件箱类目）」
    —— 规范给域定的表名是 project_announcements；本实现按任务书 FX-30 的
    DDL 口径落表为 project_broadcasts（最小诚实版：规范未细定义列结构，
    列/索引按任务书；表名差异在此如实注明，规范修订时可一次 RENAME 对齐）；
    「收件箱类目」由 latest_for_user + collab_pages 收件箱顶部段覆盖；
    「登录横幅」（登录后全站横幅）非本批范围（app.py 本批禁碰）；
  * 单点缓解：「单人项目关键动作走 bypass 留痕＋**项目广播公示**兜底」——
    广播的定位是留痕公示面，不是可裁决待办，故本模块只提供发布与只读查询，
    无编辑/撤回/已读回执（规范未定义，不擅自加）。

数据链：
  ensure_broadcast_table() 建表（幂等；DDL 单一事实源 mysql_db.
  PROJECT_BROADCASTS_TABLE_SQL，同时注册在 CREATE_TABLES_SQL 随全量建表）
  → publish_broadcast 发布（词典管理员闸 require_role ＋ 项目在册校验）
  → list_broadcasts 按项目倒序（发布页历史小表）
  → latest_for_user 聚合在册项目的最新广播（收件箱顶部，每人每项目一条）。

降级口径（与 org_db/users_db 容错口径一致）：
  * 数据库不可用时：读函数返回 []（list_broadcasts）/ None（latest_for_user，
    None=取数失败，与「真 0 条=空清单」区分，供页面分级灰注）、写函数返回
    None，只记日志不抛异常；
  * published_by 为 NULL 的行渲染为「系统作业」（RV2-3 留痕列第 1 类口径，
    与 style_check 历史表同款）；本模块原样返回 NULL，文案在页面层。

关键业务规则：
  * 发布权：guards.require_role(actor, allowed={"dict_admin"}) —— 判定走
    users_db.effective_six_roles 单一实现（legacy admin 自然通过）；
  * project_id 须为在册项目（dictionary_projects 有该行）—— 经 org_db.
    list_projects 只读校验，不直接写 org 域（广播域只读引用项目壳）；
  * project_id/title/body 是软引用/文本列，无 FK、无 UNIQUE，同一项目可
    多条广播，倒序展示；
  * SQL 一律参数化（表名/列名来自本模块常量，不拼用户输入）。
"""

import logging
from typing import Any, Dict, List, Optional

import pymysql

from src.db_utils import as_int as _as_int  # RV3-5/R6-4：公共小件单一实现点
from src.mysql_db import PROJECT_BROADCASTS_TABLE_SQL, get_db_cursor

logger = logging.getLogger(__name__)

# 历史小表/收件箱单次渲染上限（防一次性拖全表；发布页与收件箱共用）
LIST_LIMIT_DEFAULT = 20

# 发布允许角色（规范 §8：项目广播归词典管理员职责）
PUBLISH_ALLOWED_ROLES = ("dict_admin",)


# ============================================
# 建表
# ============================================

def ensure_broadcast_table() -> None:
    """
    建 project_broadcasts 表（幂等，CREATE TABLE IF NOT EXISTS）。

    DDL 与 mysql_db.CREATE_TABLES_SQL 末位条目同源（单一事实源
    PROJECT_BROADCASTS_TABLE_SQL）。数据库不可用时只记日志不抛异常，
    让调用方（页面自举）可以继续渲染而不是整页崩掉 —— 与 org_db.
    ensure_org_tables 容错口径一致。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(PROJECT_BROADCASTS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"project_broadcasts 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"project_broadcasts 表初始化意外错误: {e}")


# ============================================
# 发布
# ============================================

def publish_broadcast(project_id: int, title: str, body: str,
                      actor: Any) -> Optional[int]:
    """
    发布一条项目广播，返回新广播 id；参数非法/拒绝/库不可用返回 None。

    两道闸（调用点页面门之外的数据层闸，纵深防御）：
      1. **角色闸**：guards.require_role(actor, allowed=PUBLISH_ALLOWED_ROLES,
         action="项目广播发布") —— 未登录/非词典管理员抛 PermissionError
         （本函数不吞权限异常：权限拒绝与降级失败是两类事实，页面层分别
         转译为 st.error 与灰注）；
      2. **项目在册闸**：project_id 必须是 dictionary_projects 在册项目，
         经 org_db.list_projects() 只读校验（广播域不写 org 域）；不在册
         返回 None（静默拒绝，记 error 日志）。

    published_by 取 actor 的用户 id（RV2-3 留痕列第 1 类：NULL=系统作业；
    本函数总有人 actor，正常路径恒为发布人 id；actor 缺 id 时落 NULL，
    如实留痕不编造）。id 清洗走 db_utils.as_int（bool 是 int 子类，先拦）。

    Args:
        project_id: 目标项目 id（须在册）
        title: 标题（非空，≤200 字符 —— DDL VARCHAR(200)，超长截断前先拒）
        body: 正文（非空）
        actor: 发布人用户 dict（含 id/role/roles；词典管理员）

    Returns:
        int | None: 新广播 id；角色闸拒绝抛 PermissionError（不吞）；
        title/body 空、project 不在册、数据库错误返回 None。
    """
    from src.guards import require_role  # 局部导入：数据层不拖 UI 依赖的顶层

    user = require_role(actor, allowed=PUBLISH_ALLOWED_ROLES,
                        action="项目广播发布")
    if not isinstance(title, str) or not title.strip():
        logger.error("publish_broadcast 需要非空标题")
        return None
    if not isinstance(body, str) or not body.strip():
        logger.error("publish_broadcast 需要非空正文")
        return None
    if len(title) > 200:
        logger.error("publish_broadcast 标题超长（>200 字符，DDL 上限）")
        return None
    pid = _as_int(project_id)
    if pid is None or pid <= 0:
        logger.error(f"publish_broadcast 需要合法 project_id: {project_id!r}")
        return None
    publisher_id = _as_int(user.get("id")) if isinstance(user, dict) else None
    try:
        from src.org_db import list_projects  # 局部导入避免模块加载环

        registered = {int(p.get("id") or 0) for p in list_projects()}
        if pid not in registered:
            logger.error(
                f"publish_broadcast 拒绝：项目 {pid} 不在册（dictionary_projects 无此行）"
            )
            return None
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO project_broadcasts (project_id, title, body, published_by) "
                "VALUES (%s, %s, %s, %s)",
                (pid, title.strip(), body, publisher_id),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"项目 {pid} 发布广播失败（MySQL）: {e}")
        return None
    except Exception as e:
        logger.error(f"项目 {pid} 发布广播意外错误: {e}")
        return None


# ============================================
# 查询
# ============================================

def list_broadcasts(project_id: int,
                    limit: int = LIST_LIMIT_DEFAULT) -> List[Dict[str, Any]]:
    """
    项目的广播历史（按 id 倒序，最新在前），附发布人账号名。

    发布页历史小表数据源。发布人经 LEFT JOIN users 取 username/display_name
    （published_by 软引用，账号物理删除后行保留、发布人字段为 NULL ——
    页面层渲染「系统作业/已注销」口径）；项目不在册/无广播返回 []。

    Args:
        project_id: 项目 id
        limit: 返回条数上限（>0；防全表拖取）

    Returns:
        list[dict]: {id, project_id, title, body, published_by, created_at,
        publisher_username, publisher_display_name}；数据库不可用返回 []。
    """
    cap = _as_int(limit)
    if cap is None or cap <= 0:
        cap = LIST_LIMIT_DEFAULT
    pid = _as_int(project_id)
    if pid is None or pid <= 0:
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT b.id, b.project_id, b.title, b.body, b.published_by,
                          b.created_at, u.username AS publisher_username,
                          u.display_name AS publisher_display_name
                   FROM project_broadcasts b
                   LEFT JOIN users u ON u.id = b.published_by
                   WHERE b.project_id = %s
                   ORDER BY b.id DESC LIMIT %s""",
                (pid, cap),
            )
            return [dict(row) for row in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"查询项目 {project_id} 广播列表失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询项目 {project_id} 广播列表意外错误: {e}")
        return []


def latest_for_user(user_id: int) -> Optional[List[Dict[str, Any]]]:
    """
    用户在册项目的最新广播聚合（每项目一条，按广播 id 倒序）—— 收件箱顶部
    「项目广播」段数据源（规范 §8「收件箱类目」口径的最小落法）。

    「在册项目」= project_members 有该用户的行（org 域成员册，只读引用）；
    项目从未有过广播则该项目不出现在结果里（无广播不渲染段）。三态返回
    供页面分级渲染：None=取数失败（库不可用/表未建）→ 灰注；[]=用户无在册
    项目或在册项目都无广播 → 不渲染段；非空 → 渲染广播条。

    SQL 口径：相关子查询取每项目 MAX(id)（不依赖 MySQL 8 窗口函数，与库
    版本兼容面一致），再 JOIN users 带发布人名、JOIN dictionary_projects
    带项目名（收件箱条目要能区分广播来自哪个项目）。

    Args:
        user_id: 用户 id

    Returns:
        list[dict] | None: [{id, project_id, project_name, title, body,
        published_by, created_at, publisher_username, publisher_display_name}]；
        数据库不可用返回 None。
    """
    uid = _as_int(user_id)
    if uid is None or uid <= 0:
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT b.id, b.project_id, p.name AS project_name,
                          b.title, b.body, b.published_by, b.created_at,
                          u.username AS publisher_username,
                          u.display_name AS publisher_display_name
                   FROM project_broadcasts b
                   JOIN project_members m ON m.project_id = b.project_id
                   JOIN dictionary_projects p ON p.id = b.project_id
                   LEFT JOIN users u ON u.id = b.published_by
                   WHERE m.user_id = %s
                     AND b.id = (SELECT MAX(b2.id) FROM project_broadcasts b2
                                 WHERE b2.project_id = b.project_id)
                   ORDER BY b.id DESC""",
                (uid,),
            )
            return [dict(row) for row in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"查询用户 {user_id} 最新广播失败（MySQL）: {e}")
        return None
    except Exception as e:
        logger.error(f"查询用户 {user_id} 最新广播意外错误: {e}")
        return None
