"""词典项目与项目成员数据层 —— 协作底座的项目壳、成员册与自检。

是什么：
  一部词典 = 一个项目（dictionary_projects），成员册（project_members）挂项目，
  项目内职能五角色 chief/reviewer/editor/annotator/viewer（chief=主编即词典
  管理员在本项目的化身）。账号体系在 users_db.py（六角色），本项目模块只管
  「人 × 项目」的入册关系 —— 三级最小权限链的第二级
  （平台管理员建号 viewer → 词典管理员入册项目职能 → 再分派具体任务）。

数据链：
  ensure_org_tables() 建表（幂等，users 表由 users_db.ensure_user_tables 先行）
  → create_project 建壳并册封首位 chief → add_member/remove_member 维护成员册
  → get_projects_for_user/get_members 供页面渲染 → project_selfcheck 体检
  （每项目 ≥1 名 chief 等约束，系统体检/主编驾驶舱数据源）。

接口（docs/spec/阶段1施工规范.md §3-A，签名不得擅改；批次 2 页面按此接线）：
  ensure_org_tables() -> None
  create_project(name, chief_id, categories, description="") -> int | None
  list_projects() -> list[dict]
  add_member(project_id, user_id, project_role, granted_by) -> bool
  remove_member(project_id, user_id) -> bool
  get_projects_for_user(user_id) -> list[dict]
  get_members(project_id) -> list[dict]
  project_selfcheck(project_id) -> (bool, list[str])

降级口径：
  * 数据库不可用时读函数返回 []/安全值、写函数返回 False，只记日志不抛异常
    （与 users_db.ensure_user_tables 容错口径一致）；
  * remove_member 的「在途任务检查」本期为接口占位：查 assignments 表
    （annotation_flow.py 所建）存在 open/in_progress 行则拒绝；该表尚不存在
    时视为无在途任务放行（MVP：任务分派未启用前不阻塞成员管理）。

关键业务规则（施工规范 §3-A + 平台架构设计规范 §8）：
  * chief 不可被 remove_member 移除（每项目 ≥1 名 chief 是项目自检硬约束）；
  * project_selfcheck：项目存在、≥1 名 chief、chief 账号在用（active=1）；
  * 成员项目内角色一枚举 {chief, reviewer, editor, annotator, viewer}，
    一人一项目一职（UNIQUE），add_member 重入= 改授职能（upsert）；
  * SQL 一律参数化；FK 对 users ON DELETE CASCADE / SET NULL，账号物理删除
    （测试清理）不残留悬挂行、不阻断删除路径 —— 隶属「users FK 删除纪律」
    第 1 条（用户自有表 CASCADE + 纯留痕列 SET NULL），规范全文见
    src/users_db.py USER_ROLES_TABLE_SQL 前注释；业务引用侧（NO ACTION ＋
    入口前置探测）的示例是 annotation_flow 三表，本模块不含该口径。

已知口径（R3-7 · P3 · 批次 12 复审，本轮不修码）：remove_member 后 assignments
残留＋在途检查全局口径 —— closed 任务成员可移除成功但 assignments 行残留（无
归档标记；表本身无 project_id，任务与项目关系不可考，成员再入册后旧任务跨任期
累积）；在途检查按 assignee_id 全局 COUNT，open 任务连带挡住该用户在另一个项目
的移除（over-block）。占位实现已声明（MVP）故降 P3；assignments 无 project_id
是结构根因（批次 12：加 project_id 列或归档标记）。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import pymysql

from src.db_utils import as_int as _as_int  # RV3-5/R6-4：公共小件单一实现点
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 建表 SQL（DDL 风格与 docs/spec/多人标注系统设计规范.md §2 一致）
# ============================================

DICTIONARY_PROJECTS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS dictionary_projects (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  description TEXT NULL,
  categories JSON NULL,                         -- 项目覆盖的语义范畴清单，如 ["motion"]
  status ENUM('active','archived') NOT NULL DEFAULT 'active',
  created_by INT NULL,                          -- 建壳人（首位 chief）；账号删除置 NULL，项目不随人亡
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_projects_creator FOREIGN KEY (created_by)
    REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

PROJECT_MEMBERS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS project_members (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  user_id INT NOT NULL,
  project_role ENUM('chief','reviewer','editor','annotator','viewer')
    NOT NULL DEFAULT 'viewer',
  granted_by INT NULL,                          -- 授权人（词典管理员）；账号删除置 NULL
  granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_project_member (project_id, user_id),
  KEY idx_project_members_user (user_id),
  CONSTRAINT fk_pm_project FOREIGN KEY (project_id)
    REFERENCES dictionary_projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_pm_user FOREIGN KEY (user_id)
    REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_pm_granter FOREIGN KEY (granted_by)
    REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# 项目内角色枚举（施工规范 §3-A；与六角色体系不同层：这是「项目内职能」，
# 账号全局角色在 users_db.user_roles，两级各自独立校验）。
PROJECT_ROLES = ("chief", "reviewer", "editor", "annotator", "viewer")

# chief 在项目内职能中的定位：词典管理员的项目化身（平台架构设计规范 §8）。
CHIEF_ROLE = "chief"

# 在途任务状态（assignments.status ENUM 的前两态；submitted/closed 不算在途）。
_IN_FLIGHT_STATUSES = ("open", "in_progress")


# ============================================
# 建表
# ============================================

def ensure_org_tables() -> None:
    """
    建 dictionary_projects / project_members 两表（幂等）。

    两表外键都指向 users —— 先调 users_db.ensure_user_tables 把依赖表就位
    （幂等、开销可忽略），再建自己的表。数据库不可用时只记日志不抛异常，
    让调用方（页面）可以继续渲染而不是整页崩掉。
    """
    from src.users_db import ensure_user_tables  # 局部导入避免环依赖表面化

    try:
        ensure_user_tables()
        with get_db_cursor() as cursor:
            cursor.execute(DICTIONARY_PROJECTS_TABLE_SQL)
            cursor.execute(PROJECT_MEMBERS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"org 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"org 表初始化意外错误: {e}")


# ============================================
# 内部助手
# ============================================

def _normalize_categories(categories: Any) -> Optional[str]:
    """
    categories 参数 → JSON 字符串（存 dictionary_projects.categories）。

    接受 list/tuple（范畴名清单）或 str（单个范畴名，或已是 JSON 串则原样
    校验后入库）；空值返回 None。范畴名统一 str() 后去空，空清单存 NULL
    （未划范畴 ≠ 空集）。
    """
    if categories is None:
        return None
    if isinstance(categories, str):
        text = categories.strip()
        if not text:
            return None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return json.dumps(
                        [str(c).strip() for c in parsed if str(c).strip()],
                        ensure_ascii=False,
                    )
            except ValueError:
                pass
        return json.dumps([text], ensure_ascii=False)
    if isinstance(categories, (list, tuple)):
        names = [str(c).strip() for c in categories if str(c).strip()]
        return json.dumps(names, ensure_ascii=False) if names else None
    return None


def _parse_categories(raw: Any) -> List[str]:
    """库中 categories JSON 串 → 范畴名清单（脏数据容错，坏 JSON 返回 []）。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(c) for c in raw]
    try:
        parsed = json.loads(raw)
        return [str(c) for c in parsed] if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _assignments_table_exists(cursor) -> bool:
    """assignments 表是否已建（annotation_flow.ensure_flow_tables 的产物）。"""
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assignments'"""
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _has_in_flight_tasks(cursor, user_id: int) -> bool:
    """
    该用户是否有在途任务（open/in_progress 的 assignments 行）。

    占位实现（施工规范 §3-A「查 assignments 占位，MVP 返回提示」）：
    assignments 表尚不存在时按无在途任务处理，不阻塞成员管理。
    两个状态字面量是本模块固定枚举（非用户输入），其余值一律参数化。
    """
    if not _assignments_table_exists(cursor):
        return False
    cursor.execute(
        "SELECT COUNT(*) AS n FROM assignments "
        "WHERE assignee_id = %s AND status IN ('open', 'in_progress')",
        (user_id,),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _is_chief(cursor, project_id: int, user_id: int) -> bool:
    """该用户在该项目是否持有 chief 职能。"""
    cursor.execute(
        "SELECT COUNT(*) AS n FROM project_members "
        "WHERE project_id = %s AND user_id = %s AND project_role = %s",
        (project_id, user_id, CHIEF_ROLE),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


# ============================================
# 项目壳 CRUD
# ============================================

def create_project(name: str, chief_id: int, categories: Any,
                   description: str = "") -> Optional[int]:
    """
    创建词典项目并册封首位主编（chief），返回项目 id。

    建壳与「chief 入册」同事务：project_members 里立即出现一条
    project_role='chief' 的记录（首位词典管理员的项目化身）——
    保证任何存活的 projects 行都满足「≥1 名 chief」自检约束。
    chief_id 必须是已存在用户（FK 校验）；项目名重复（UNIQUE）返回 None。

    chief_id 入参清洗走 db_utils.as_int（RV3-5）：bool 是 int 子类，
    ``isinstance(chief_id, int)`` 会把 True 放行成 chief_id=1（越权册封
    风险），as_int 先拦 bool；int-str/整数值 float 同口径宽松可转，与其余
    id 类入参清洗一致（口径表见 src/lexical_db.py 模块 docstring）。

    Args:
        name: 项目名（非空，≤120 字符）
        chief_id: 首位主编的用户 id（>0；bool/None/非整值一律拒绝）
        categories: 覆盖的语义范畴清单（list/tuple/str，可空 —— None=未划
            范畴；str 可为单个范畴名或 JSON 串；规整规则见
            _normalize_categories，故注解为 Any）
        description: 项目描述（可空）

    Returns:
        int | None: 新项目 id；参数非法 / chief 不存在 / 项目名重复 /
        数据库错误返回 None。
    """
    if not isinstance(name, str) or not name.strip():
        logger.error("create_project 需要非空项目名")
        return None
    cid = _as_int(chief_id)
    if cid is None or cid <= 0:
        logger.error(f"create_project 需要合法 chief_id: {chief_id!r}")
        return None
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "INSERT INTO dictionary_projects "
                "(name, description, categories, status, created_by) "
                "VALUES (%s, %s, %s, 'active', %s)",
                (name.strip(), description or "", _normalize_categories(categories),
                 cid),
            )
            project_id = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO project_members (project_id, user_id, project_role, "
                "granted_by) VALUES (%s, %s, %s, %s)",
                (project_id, cid, CHIEF_ROLE, cid),
            )
        return project_id
    except pymysql.Error as e:
        # Duplicate entry（项目名重复）/ FK 无此 chief 等都在这里落地
        logger.error(f"创建项目 '{name}' 失败: {e}")
        return None
    except Exception as e:
        logger.error(f"创建项目 '{name}' 意外错误: {e}")
        return None


def list_projects() -> List[Dict[str, Any]]:
    """
    全部项目列表（按 id 升序），附成员数与 chief 用户 id。

    Returns:
        list[dict]: {id, name, description, categories(范围 list), status,
        created_by, created_at, member_count}；数据库不可用返回 []。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT p.id, p.name, p.description, p.categories, p.status,
                          p.created_by, p.created_at,
                          (SELECT COUNT(*) FROM project_members m
                           WHERE m.project_id = p.id) AS member_count
                   FROM dictionary_projects p ORDER BY p.id"""
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["categories"] = _parse_categories(item.get("categories"))
                item["member_count"] = int(item.get("member_count") or 0)
                result.append(item)
            return result
    except pymysql.Error as e:
        logger.error(f"查询项目列表失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询项目列表意外错误: {e}")
        return []


def get_projects_for_user(user_id: int) -> List[Dict[str, Any]]:
    """
    用户入册的全部项目（附自己在该项目内的职能），按项目 id 升序。

    登录落地页/侧边栏据此渲染「我的项目」；project_role 是该用户在此
    项目的职能（chief/reviewer/editor/annotator/viewer），与账号全局六角色
    （users_db.list_roles）分属两级权限链。

    Returns:
        list[dict]: 项目字段 + project_role；未入册/数据库不可用返回 []。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT p.id, p.name, p.description, p.categories, p.status,
                          p.created_by, p.created_at, m.project_role, m.granted_at
                   FROM project_members m
                   JOIN dictionary_projects p ON p.id = m.project_id
                   WHERE m.user_id = %s ORDER BY p.id""",
                (user_id,),
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["categories"] = _parse_categories(item.get("categories"))
                result.append(item)
            return result
    except pymysql.Error as e:
        logger.error(f"查询用户 {user_id} 项目列表失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询用户 {user_id} 项目列表意外错误: {e}")
        return []


# ============================================
# 成员册 CRUD
# ============================================

def add_member(project_id: int, user_id: int, project_role: str,
               granted_by: int) -> bool:
    """
    用户入册项目（授项目内职能）；已入册则改授新职能（upsert）。

    一人一项目一职（UNIQUE(project_id, user_id)）：重复 add 同职能返回 False
    （无实际变更，与 set_role「未变更= False」口径一致）；改授不同职能是
    合法操作（词典管理员调整职能），执行 UPDATE 并返回 True。
    chief 职能不受本函数限制（可以再册一位 chief —— 多主项目，
    平台架构设计规范 §8 单点缓解建议 ≥2 名词典管理员）。

    Args:
        project_id: 项目 id
        user_id: 用户 id
        project_role: 项目内职能（PROJECT_ROLES 之一）
        granted_by: 授权人用户 id（词典管理员）

    Returns:
        bool: 新增入册或实际改授职能为 True；职能非法 / 项目或用户不存在 /
        重复授予同一职能 / 数据库错误为 False。
    """
    if project_role not in PROJECT_ROLES:
        logger.error(f"add_member 拒绝非法项目职能: {project_role!r}")
        return False
    if not isinstance(granted_by, int) or granted_by <= 0:
        logger.error(f"add_member 需要合法 granted_by: {granted_by!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """INSERT INTO project_members (project_id, user_id, project_role, granted_by)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     project_role = VALUES(project_role),
                     granted_by = VALUES(granted_by)""",
                (project_id, user_id, project_role, granted_by),
            )
            # 新插入 rowcount=1；ON DUPLICATE 且值有变化 rowcount=2；
            # 值无变化 rowcount=0（MySQL upsert 语义）
            return cursor.rowcount > 0
    except pymysql.Error as e:
        # FK 失败（无此项目/用户）也在这里落地
        logger.error(f"项目 {project_id} 入册用户 {user_id} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"项目 {project_id} 入册用户 {user_id} 意外错误: {e}")
        return False


def remove_member(project_id: int, user_id: int) -> bool:
    """
    把用户移出项目成员册。

    两条硬性拒绝（施工规范 §3-A）：
      1. **chief 不可移除** —— 每项目 ≥1 名 chief 是项目自检硬约束，
         先改授他人或解散项目，而不是直接摘掉主编；
      2. **成员有在途任务时拒绝** —— 占位实现：assignments 表存在该用户
         open/in_progress 行即拒绝（停用用户强制先改派在途任务，平台架构
         设计规范 §8）；assignments 表尚未建时视为无在途任务放行（MVP）。

    Returns:
        bool: 实际移除为 True；chief / 在途任务 / 非成员 / 数据库错误为 False。
    """
    try:
        with get_db_cursor() as cursor:
            if _is_chief(cursor, project_id, user_id):
                logger.error(
                    f"拒绝移除项目 {project_id} 的主编（user {user_id}）："
                    "chief 不可移除，请先改授他人"
                )
                return False
            if _has_in_flight_tasks(cursor, user_id):
                logger.error(
                    f"拒绝移除项目 {project_id} 成员（user {user_id}）："
                    "存在在途任务，请先改派"
                )
                return False
            cursor.execute(
                "DELETE FROM project_members WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            if cursor.rowcount <= 0:
                logger.error(f"项目 {project_id} 无成员 user {user_id} 可移除")
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"项目 {project_id} 移除成员 {user_id} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"项目 {project_id} 移除成员 {user_id} 意外错误: {e}")
        return False


def get_members(project_id: int) -> List[Dict[str, Any]]:
    """
    项目成员册（按 chief 优先、再按入册时间升序），附账号显示信息。

    Returns:
        list[dict]: {id(成员行 id), project_id, user_id, project_role,
        granted_by, granted_at, username, display_name, active}；
        数据库不可用返回 []。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT m.id, m.project_id, m.user_id, m.project_role,
                          m.granted_by, m.granted_at,
                          u.username, u.display_name, u.active
                   FROM project_members m
                   JOIN users u ON u.id = m.user_id
                   WHERE m.project_id = %s
                   ORDER BY (m.project_role = 'chief') DESC, m.id""",
                (project_id,),
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["active"] = int(item.get("active") or 0)
                result.append(item)
            return result
    except pymysql.Error as e:
        logger.error(f"查询项目 {project_id} 成员失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询项目 {project_id} 成员意外错误: {e}")
        return []


# ============================================
# 项目自检
# ============================================

def project_selfcheck(project_id: int) -> Tuple[bool, List[str]]:
    """
    项目健康自检（系统体检/主编驾驶舱数据源）。

    检查项（施工规范 §3-A：≥1 名 chief 等约束）：
      1. 项目存在；
      2. ≥1 名 chief 成员（chief 不可移除约束的兜底核对）；
      3. chief 账号在用（active=1）—— 停用主编意味着项目无人可执行
         词典管理员职能，须显式改授。

    Returns:
        (bool, list[str]): 全部通过 (True, [])；否则 (False, 问题文案清单，
        每条可直接进体检报告)。项目不存在返回 (False, ['项目不存在'])；
        数据库不可用返回 (False, ['数据库不可用'])。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM dictionary_projects WHERE id = %s",
                (project_id,),
            )
            if int(cursor.fetchone()["n"] or 0) <= 0:
                return False, ["项目不存在"]
            cursor.execute(
                """SELECT COUNT(*) AS n FROM project_members
                   WHERE project_id = %s AND project_role = 'chief'""",
                (project_id,),
            )
            n_chiefs = int(cursor.fetchone()["n"] or 0)
            problems: List[str] = []
            if n_chiefs <= 0:
                problems.append("无主编（chief）成员：每项目至少 1 名 chief")
            else:
                cursor.execute(
                    """SELECT COUNT(*) AS n FROM project_members m
                       JOIN users u ON u.id = m.user_id
                       WHERE m.project_id = %s AND m.project_role = 'chief'
                         AND u.active = 1""",
                    (project_id,),
                )
                if int(cursor.fetchone()["n"] or 0) <= 0:
                    problems.append("主编（chief）账号已全部停用，请改授在用账号")
            return (True, []) if not problems else (False, problems)
    except pymysql.Error as e:
        logger.error(f"项目 {project_id} 自检失败（MySQL）: {e}")
        return False, ["数据库不可用"]
    except Exception as e:
        logger.error(f"项目 {project_id} 自检意外错误: {e}")
        return False, ["数据库不可用"]
