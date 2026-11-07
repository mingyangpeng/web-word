"""用户与权限数据层 —— 多人标注系统的账号存储、登录校验与角色管理。

设计规范：docs/spec/多人标注系统设计规范.md（唯一事实源）§2 users 表 DDL、
§3 模块契约（本文件签名与之一致，不得擅改）、§6 安全规则；
v5.1 多角色扩展见 docs/spec/平台架构设计规范.md §8（六角色 · 三级最小权限链）
与 docs/spec/阶段1施工规范.md §3-A（本文件扩展部分的契约）。

职责边界：
  * users 表 + user_roles 多角色表 + 密码哈希 —— 任务分配/提交/仲裁在
    annotation_flow.py，项目与项目成员在 org_db.py，页面在 users_admin_page.py
    （集成时由 app.py 按角色分派）。
  * 内置默认 admin：users 表为空时由 ensure_user_tables() 自动创建
    admin/admin123（display_name=内置管理员，role=admin）。
    **该账号仅供首次 bootstrap，首次登录后必须立即修改密码**（must_change_password=1，
    修改密码功能在登录/个人设置页实现，见规范 §5 UI 集成契约）；
    ensure_user_tables() 同时把它幂等迁移为 dict_admin+sys_admin 双角色
    （平台架构设计规范 §8：六角色模型下的两位一体）。

六角色模型（平台架构设计规范 §8，v5.1）：
  * user_roles 一人多角色（一人可叠加），优先级 dict_admin > sys_admin >
    reviewer > editor > annotator > viewer；新号默认 viewer（create_user 缺省）；
  * 旧 users.role 列保留为**兼容快照**：存量数据/旧调用方（app 会话刷新、
    页面权限门）仍读它，语义与升级前逐字节一致；user_roles 是增量事实源，
    list_roles 对无 user_roles 行的账号按旧列映射兜底（admin→dict_admin+sys_admin）。
  * grant_role/revoke_role/has_role/list_roles 是批次 2 页面层的角色判定接口；
    verify_login 保持原四键返回（原因见 verify_login docstring「批次 2 接线」）。

安全规则（规范 §6，全体遵守）：
  1. SQL 一律参数化（沿用 mysql_db.get_db_cursor 模式），本文件无一处字符串拼接；
  2. 密码 pbkdf2_sha256 + 每用户随机盐（secrets.token_hex(16)），
     150000 迭代（≥120000），存储格式 `pbkdf2_sha256$iterations$salt_hex$hash_hex`，
     禁止明文/可逆 —— 密码哈希不出数据层（list_users 不返回 password_hash），
     默认口令也绝不写入日志；
  3. verify_login 对「无此用户 / 密码错 / 已停用」返回同样的 None，防账号枚举。
"""

import hashlib
import hmac
import logging
import secrets
from typing import Any, Dict, List, Optional

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 建表 SQL（规范 §2 users 表 DDL 原样）
# ============================================
USERS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,          -- 格式 pbkdf2_sha256$iterations$salt_hex$hash_hex
  display_name VARCHAR(80) NOT NULL DEFAULT '',
  role ENUM('admin','reviewer','annotator','viewer') NOT NULL DEFAULT 'annotator',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# v5.1 存量表变更（平台架构设计规范 附录 A）：users(＋must_change_password)。
# 建表 SQL 保持规范 §2 原样（存量库走 ALTER 幂等迁移，见 ensure_user_tables），
# 新库也是「先建旧形 → ALTER 补列」，迁移路径与新库路径合二为一。
MUST_CHANGE_PASSWORD_COLUMN_SQL = (
    "ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0"
)

# user_roles 多角色表（平台架构设计规范 §8 六角色）。一人可叠加，UNIQUE 去重；
# FK 对 users ON DELETE CASCADE：账号物理删除（测试清理/运维清理）时角色行
# 跟随消失，绝不阻断删除路径（e2e 清理只删 users，靠本 CASCADE 自愈）。
USER_ROLES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS user_roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  role ENUM('dict_admin','sys_admin','reviewer','editor','annotator','viewer') NOT NULL,
  granted_by INT NULL,                          -- 授权人（平台管理员），系统迁移行为 NULL
  granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_role (user_id, role),
  KEY idx_user_roles_role (role),
  CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id)
    REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_roles_granter FOREIGN KEY (granted_by)
    REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# ============================================
# 密码哈希（规范 §6-2）
# ============================================
# 迭代次数：规范要求 ≥120000，取 150000（规范 §2 注释给出的格式示例值）。
# 存量哈希自带 iterations 字段，未来上调只需改这里，旧哈希仍可校验。
PBKDF2_ITERATIONS = 150000
_PBKDF2_ALGO = "pbkdf2_sha256"

# 角色枚举（规范 §1 角色语义）。create_user / set_role 在入口校验，
# 不依赖 MySQL ENUM 报错 —— 应用层先拒绝，非法值根本不进数据库。
ROLES = ("admin", "reviewer", "annotator", "viewer")

# ============================================
# v5.1 六角色（平台架构设计规范 §8）
# ============================================
# 六角色按权限从高到低排列 —— 元组顺序即优先级顺序（index 越小越高）。
# dict_admin=词典管理员、sys_admin=平台管理员；后四者与规范 §1 同名同义。
NEW_ROLES = ("dict_admin", "sys_admin", "reviewer", "editor", "annotator", "viewer")

# 旧 users.role 列值 → 六角色集的映射（list_roles 对无 user_roles 行的存量账号
# 兜底；内置 admin 的双角色是它的规范语义，见 ensure_user_tables 迁移）。
LEGACY_ROLE_TO_NEW_ROLES = {
    "admin": ("dict_admin", "sys_admin"),
    "reviewer": ("reviewer",),
    "annotator": ("annotator",),
    "viewer": ("viewer",),
}

# 内置默认管理员（bootstrap 用）。口令按规范固定为 admin123：
# 只在此处出现一次，绝不写进日志；首次登录后必须修改。
_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD = "admin123"
_DEFAULT_ADMIN_DISPLAY_NAME = "内置管理员"

# 防时序侧信道的哑元哈希（标准存储格式，不对应任何真实账号）：
# verify_login 在「无此用户」分支也对它做一次等价成本的 pbkdf2 校验，
# 使响应耗时与「有此用户但密码错」不可区分 —— 防止通过时间差枚举用户名。
_TIMING_DUMMY_HASH = (
    f"{_PBKDF2_ALGO}${PBKDF2_ITERATIONS}$"
    f"{'0' * 32}${hashlib.sha256(b'no-such-user-timing-pad').hexdigest()}"
)


def hash_password(plain: str) -> str:
    """
    生成密码哈希：pbkdf2_sha256$150000$salt$hash。

    每次调用生成新的随机盐（secrets.token_hex(16)，密码学安全随机源），
    同一明文两次哈希结果不同 —— 这是特性不是缺陷，校验靠 verify_password。

    Args:
        plain: 明文密码（只在内存中出现，不落库、不落日志）

    Returns:
        str: `pbkdf2_sha256$iterations$salt_hex$hash_hex` 格式的存储串
    """
    salt_hex = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    )
    return f"{_PBKDF2_ALGO}${PBKDF2_ITERATIONS}${salt_hex}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """
    校验明文密码与存储哈希是否匹配。

    存储串格式非法（缺字段 / 迭代数非数字 / 盐非十六进制 / 算法不对）
    一律返回 False 而不是抛异常 —— 脏数据不能把登录页打崩。

    Args:
        plain: 待校验的明文密码
        stored: hash_password 生成的存储串（或库中读出的 password_hash）

    Returns:
        bool: 匹配为 True；不匹配或格式非法为 False
    """
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        # compare_digest：常数时间比较，防时序侧信道
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (AttributeError, TypeError, ValueError):
        # stored 为 None/格式坏/盐非法/明文不可编码 —— 全按校验失败处理
        return False


# ============================================
# 建表与内置默认管理员
# ============================================

def ensure_user_tables() -> None:
    """
    users/user_roles 建表与结构迁移（幂等）+ 内置默认 admin。

    步骤（全部幂等，可重复调用）：
      1. 建 users 表（CREATE TABLE IF NOT EXISTS，规范 §2 DDL 原样）；
      2. 存量迁移：users 补 must_change_password 列（information_schema 探测，
         已有则跳过 —— 仿 mysql_db._migrate_schema 风格）；
      3. 建 user_roles 多角色表（六角色，FK → users ON DELETE CASCADE）；
      4. users 表为空时创建内置管理员 admin/admin123
         （display_name=内置管理员，role=admin，must_change_password=1）。
         **首次登录后必须立即修改密码** —— 默认口令是公开的 bootstrap 凭据，
         不能长期留在生产库里；
      5. 内置 admin 幂等迁移为 dict_admin+sys_admin 双角色
         （平台架构设计规范 §8：六角色模型下两位一体）。

    数据库不可用时只记日志不抛异常（与 mysql_db.init_database 的容错口径一致），
    让调用方（页面）可以继续渲染登录框而不是整页崩掉。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(USERS_TABLE_SQL)
            _migrate_users_columns(cursor)
            cursor.execute(USER_ROLES_TABLE_SQL)
            _ensure_default_admin(cursor)
            _migrate_builtin_admin_roles(cursor)
    except pymysql.Error as e:
        logger.error(f"users 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"users 表初始化意外错误: {e}")


def _column_exists(cursor, table: str, column: str) -> bool:
    """表上是否已有该列（让 ALTER 幂等；仿 mysql_db._migrate_schema 同名助手）。"""
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND COLUMN_NAME = %s""",
        (table, column),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _migrate_users_columns(cursor) -> None:
    """users 存量结构迁移：补 must_change_password 列（幂等，可重复运行）。"""
    if not _column_exists(cursor, "users", "must_change_password"):
        cursor.execute(MUST_CHANGE_PASSWORD_COLUMN_SQL)
        logger.info("users.must_change_password 列已补齐（v5.1 存量表迁移）")


def _ensure_default_admin(cursor) -> None:
    """users 表为空时插入内置默认 admin（供 ensure_user_tables 调用）。"""
    cursor.execute("SELECT COUNT(*) AS n FROM users")
    if int(cursor.fetchone()["n"] or 0) > 0:
        return
    cursor.execute(
        "INSERT INTO users (username, password_hash, display_name, role, active, "
        "must_change_password) VALUES (%s, %s, %s, %s, 1, 1)",
        (
            _DEFAULT_ADMIN_USERNAME,
            hash_password(_DEFAULT_ADMIN_PASSWORD),
            _DEFAULT_ADMIN_DISPLAY_NAME,
            "admin",
        ),
    )
    # 日志只提账号名与「必须改密」，绝不写默认口令明文
    logger.warning(
        "users 表为空，已创建内置默认管理员 'admin'（首次登录后必须修改密码）"
    )


def _migrate_builtin_admin_roles(cursor) -> None:
    """
    内置 admin 幂等迁移为 dict_admin + sys_admin 双角色（平台架构设计规范 §8）。

    只针对 username='admin' 这一个 bootstrap 账号；普通账号不做自动迁移
    （六角色授予是词典管理员的显式管理动作）。UNIQUE(user_id, role) +
    INSERT IGNORE 保证重复调用零副作用。
    """
    for role in LEGACY_ROLE_TO_NEW_ROLES["admin"]:
        cursor.execute(
            "INSERT IGNORE INTO user_roles (user_id, role, granted_by) "
            "SELECT id, %s, NULL FROM users WHERE username = %s",
            (role, _DEFAULT_ADMIN_USERNAME),
        )


# ============================================
# 登录与用户 CRUD
# ============================================

def _verify_login_record(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    登录校验核心（供 verify_login / verify_login_full 共用）。

    通过校验返回 {"row": users 行（不含 password_hash）, "roles": [六角色按
    优先级降序]}；任一失败路径统一返回 None（防账号枚举）。roles 读自
    user_roles 表；表缺失/查询失败时按旧 role 列映射兜底（登录不能因为
    角色表故障而不可用），并保持三种失败不可区分的时间口径。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, username, display_name, role, active, password_hash "
                "FROM users WHERE username = %s",
                (username,),
            )
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"登录查询失败（MySQL）: {e}")
        return None
    except Exception as e:
        logger.error(f"登录查询意外错误: {e}")
        return None

    if row is None:
        # 无此用户：也执行一次等价成本的 pbkdf2 校验再返回 None（哑元哈希），
        # 响应耗时与「有此用户但密码错」一致，防时序枚举用户名。
        verify_password(password, _TIMING_DUMMY_HASH)
        return None
    if not verify_password(password, row.get("password_hash") or ""):
        return None
    if not int(row.get("active") or 0):
        # 密码先校验、停用后判定：停用用户的响应耗时与正常失败一致
        return None

    user_id = int(row["id"])
    try:
        roles = _load_roles_or_raise(user_id)
    except Exception as e:  # 角色表故障不拦登录：按旧列映射兜底
        # 注意须调 _load_roles_or_raise（异常上抛）而非 list_roles——后者
        # 自吞异常恒返回 []，会让本兜底分支永远不可达（瞬时故障时管理员
        # 将以 roles=[] 登录、六角色全空直到重登）。
        logger.error(f"登录读取 user_roles 失败，按旧角色列兜底: {e}")
        roles = list(LEGACY_ROLE_TO_NEW_ROLES.get(row.get("role"), ()))
    return {"row": row, "roles": roles}


def verify_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    校验用户名+密码，成功返回会话用户信息。

    批次 2 接线说明（v5.1 六角色）：本函数返回**保持升级前逐字段一致**的
    {id, username, display_name, role}（role 仍为旧 users.role 列值）——
    app.py 把返回 dict 原样塞进 session（st.session_state["user"] = info），
    只读集成测试 tests/test_integration_apptest.py 锁定 session user 恰为
    四键。批次 2 改造六角色会话时改调 verify_login_full（多一个 roles 列表，
    优先级 dict_admin > sys_admin > reviewer > editor > annotator > viewer）
    或在登录处补 ``info["roles"] = list_roles(info["id"])``，并同步该集成断言。

    Args:
        username: 用户名
        password: 明文密码（只在内存中比对，不落库不落日志）

    Returns:
        dict | None: 成功返回 {id, username, display_name, role}（不含
        password_hash，哈希不出数据层）；用户不存在 / 密码错误 /
        active=0（已停用）统一返回 None —— 三种失败不可区分，防账号枚举。
    """
    record = _verify_login_record(username, password)
    if record is None:
        return None
    row = record["row"]
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


def verify_login_full(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    verify_login 的六角色完整版：返回在四键基础上增加 roles 列表。

    roles 按优先级降序（dict_admin > sys_admin > reviewer > editor >
    annotator > viewer），来自 user_roles 表；无 user_roles 行的存量账号按
    旧 role 列映射兜底（admin→[dict_admin, sys_admin]）。role 键仍为旧列值，
    向后兼容不变。

    批次 2 页面层按本函数接线六角色会话；批次 1 期间 app.py 继续用
    verify_login（四键），两者共享同一套校验与防枚举口径。

    Returns:
        dict | None: {id, username, display_name, role, roles}；失败同
        verify_login（统一 None，防账号枚举）。
    """
    record = _verify_login_record(username, password)
    if record is None:
        return None
    row = record["row"]
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "roles": list(record["roles"]),
    }


def create_user(username: str, password: str, display_name: str,
                role: str = "viewer") -> Optional[int]:
    """
    新建用户（active=1，must_change_password=1），返回新用户 id。

    v5.1：role 缺省 **viewer**（平台架构设计规范 §8「新号默认 viewer」；
    平台管理员建号后由词典管理员在项目内入册提权 —— 三级最小权限链第一级）。
    role 仍接受旧枚举 ROLES（存量调用方不变）；同时把旧角色映射写入
    user_roles 六角色表（admin→dict_admin+sys_admin，其余同名），两处存储
    保持一致。新号 must_change_password=1：管理员签发的初始口令，首次登录
    必须修改（needs_password_change 供登录页横幅读取，change_password 清零）。

    角色必须是 ROLES 之一（应用层先拒，非法值不进数据库）；
    用户名重复（UNIQUE 约束）返回 None。users 行与 user_roles 行同事务写入，
    角色行失败则整体回滚（不留半初始化账号）。

    Returns:
        int | None: 新用户 id；角色非法 / 参数为空 / 用户名重复 / 数据库错误 返回 None
    """
    if role not in ROLES:
        logger.error(f"create_user 拒绝非法角色: {role!r}")
        return None
    if not username or not password:
        logger.error("create_user 需要非空 username 与 password")
        return None
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "INSERT INTO users (username, password_hash, display_name, role, "
                "active, must_change_password) VALUES (%s, %s, %s, %s, 1, 1)",
                (username, hash_password(password), display_name, role),
            )
            new_id = int(cursor.lastrowid)
            for new_role in LEGACY_ROLE_TO_NEW_ROLES.get(role, ()):
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role, granted_by) "
                    "VALUES (%s, %s, NULL)",
                    (new_id, new_role),
                )
        return new_id
    except pymysql.Error as e:
        # e 里只有 SQL 错误信息（如 Duplicate entry 'xxx'），不含密码
        logger.error(f"创建用户 '{username}' 失败: {e}")
        return None
    except Exception as e:
        logger.error(f"创建用户 '{username}' 意外错误: {e}")
        return None


def list_users() -> List[Dict[str, Any]]:
    """
    全部用户列表（按 id 升序）。

    只返回 id / username / display_name / role / active / created_at，
    **不含 password_hash** —— 哈希只用于登录校验，不出数据层。

    Returns:
        list[dict]: 用户字典列表；数据库不可用返回 []
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, username, display_name, role, active, created_at "
                "FROM users ORDER BY id"
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except pymysql.Error as e:
        logger.error(f"查询用户列表失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询用户列表意外错误: {e}")
        return []


def set_role(user_id: int, role: str) -> bool:
    """
    修改用户角色（旧枚举兼容接口）。

    v5.1：本接口把旧 users.role 列视为「账号基线角色快照」。实际变更时
    同事务把 user_roles 重置为该基线的映射集（admin→dict_admin+sys_admin，
    其余同名）—— 否则旧页面降级账号后 user_roles 仍保留高角色
    （如 dict_admin），构成提权漏洞。六角色的叠加授权走 grant_role /
    revoke_role（不受本接口影响，除非基线实际变更）。

    Args:
        user_id: 用户 id
        role: 目标角色（必须 ∈ ROLES）

    Returns:
        bool: 角色实际变更（或用户存在且值有变化）为 True；角色非法 /
        用户不存在 / 数据库错误为 False。目标值与现值相同时 MySQL 不计为
        变更行，返回 False（对页面而言等价于「未变更」，也不动 user_roles
        —— 显式叠加的角色不被误清）。
    """
    if role not in ROLES:
        logger.error(f"set_role 拒绝非法角色: {role!r}")
        return False
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "UPDATE users SET role = %s WHERE id = %s",
                (role, user_id),
            )
            if cursor.rowcount <= 0:
                return False  # 未变更：保持 user_roles 现状（叠加授权不误清）
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s", (user_id,))
            for new_role in LEGACY_ROLE_TO_NEW_ROLES.get(role, ()):
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role, granted_by) "
                    "VALUES (%s, %s, NULL)",
                    (user_id, new_role),
                )
        return True
    except pymysql.Error as e:
        logger.error(f"修改用户 {user_id} 角色失败: {e}")
        return False
    except Exception as e:
        logger.error(f"修改用户 {user_id} 角色意外错误: {e}")
        return False


def set_active(user_id: int, active: bool) -> bool:
    """
    停用（False）/ 启用（True）用户。

    停用的用户 verify_login 返回 None（不能登录），但记录保留 ——
    历史 submissions 的 coder_id 外键仍指向他，物理删除会断引用。

    Returns:
        bool: 状态实际变更为 True；用户不存在 / 数据库错误为 False。
        目标状态与现值相同时 MySQL 不计为变更行，返回 False。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE users SET active = %s WHERE id = %s",
                (1 if active else 0, user_id),
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"修改用户 {user_id} 状态失败: {e}")
        return False
    except Exception as e:
        logger.error(f"修改用户 {user_id} 状态意外错误: {e}")
        return False


def get_user_role(user_id: int) -> Optional[str]:
    """
    实时读取用户当前角色（会话角色防陈旧，R1-P2b）。

    与登录时的角色快照相对：权限判定应以本函数的**当次**返回值为准，
    快照只用于侧边栏显示。管理员 set_role / set_active 后本函数立即
    反映新值 —— 已建立的会话无需等重新登录。

    Args:
        user_id: 用户 id

    Returns:
        str | None: 角色（'admin'/'reviewer'/'annotator'/'viewer'）；
        用户不存在、**已停用（active=0）** 或数据库不可用返回 None ——
        调用方（app 会话刷新）把 None 统一按「会话失效，登出」处理：
        停用/删除用户的旧会话在下次任意操作时即被登出（fail-closed）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT role FROM users WHERE id = %s AND active = 1",
                (user_id,),
            )
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"读取用户 {user_id} 角色失败（MySQL）: {e}")
        return None
    except Exception as e:
        logger.error(f"读取用户 {user_id} 角色意外错误: {e}")
        return None
    if row is None:
        return None
    role = row.get("role")
    return str(role) if role else None


# ============================================
# v5.1 六角色多角色 API（平台架构设计规范 §8；批次 2 页面层按此接线）
# ============================================

def effective_six_roles(user: Optional[Dict[str, Any]]) -> set:
    """会话用户的**有效六角色集** —— 页面层六角色门的单一实现（批次 4-N 收口）。

    有效集 = legacy users.role 列映射（LEGACY_ROLE_TO_NEW_ROLES）
           ∪ session roles 快照（verify_login_full 写入、app._refresh_session_user
           刷新的六角色列表）。

    契约签名（施工规范 §7-N）：``effective_six_roles(user: dict | None) -> set[str]``；
    本文件沿用 typing 风格书写（Optional[Dict[str, Any]] -> set），语义相同。

    规则：
      * user 非 dict（None / 残缺注入）→ 空集 —— 未登录＝无权限（fail-closed）；
      * legacy role 映射向后兼容：admin→{dict_admin, sys_admin}（两位一体），
        reviewer/annotator/viewer 同名（users.role 列语义与升级前逐字节一致）；
      * session roles 逐名校验：不在 NEW_ROLES 的非法角色名一律忽略
        （fail-closed —— 拼写漂移/注入垃圾不放大权限）；list/tuple/set 均接受；
      * 无 roles 键的旧结构会话只按 legacy role 折算（行为与升级前一致）。

    本函数是纯会话计算（不查库）——实时权限判定仍走 list_roles/has_role
    （fail-closed 读库）；app 会话每次 rerun 经 _refresh_session_user 刷新快照后
    由本函数折算。app.py 的本地 _effective_six_roles 已收口为本实现的别名
    （批次 3 的复制实现删除，单一事实源在此）；users_admin_page 的页面体角色门
    与提权硬闸门同源调用，不再各自折算。

    Returns:
        set: 有效六角色集合（NEW_ROLES 的子集，可能为空）。
    """
    roles: set = set()
    if not isinstance(user, dict):
        return roles
    roles.update(LEGACY_ROLE_TO_NEW_ROLES.get(user.get("role"), ()))
    session_roles = user.get("roles")
    if isinstance(session_roles, (list, tuple, set)):
        roles.update(r for r in session_roles if r in NEW_ROLES)
    return roles


def _sort_roles_by_priority(roles) -> List[str]:
    """把角色集合按 NEW_ROLES 优先级降序排列（未知角色排最后，稳序）。"""
    order = {role: i for i, role in enumerate(NEW_ROLES)}
    return sorted(set(roles), key=lambda r: (order.get(r, len(NEW_ROLES)), r))


def _load_roles_or_raise(user_id: int) -> List[str]:
    """
    六角色列表读取核心（list_roles 与登录兜底共用）；数据库故障向上抛，
    由调用方按各自口径兜底（list_roles 吞掉返回 []，登录按旧 role 列映射）。

    返回语义：无 user_roles 行 → 旧 users.role 列映射兜底；用户不存在 /
    已停用（active=0）→ []（fail-closed）。

    Args:
        user_id: 用户 id

    Returns:
        list[str]: 六角色列表（可能为空）；priority 高者在前。
    """
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT u.role AS legacy_role, ur.role AS new_role "
            "FROM users u LEFT JOIN user_roles ur ON ur.user_id = u.id "
            "WHERE u.id = %s AND u.active = 1",
            (user_id,),
        )
        rows = list(cursor.fetchall())
    if not rows:
        return []
    new_roles = [str(r["new_role"]) for r in rows if r.get("new_role")]
    if new_roles:
        return _sort_roles_by_priority(new_roles)
    # 存量兜底：无 user_roles 行 → 旧 role 列映射
    return list(LEGACY_ROLE_TO_NEW_ROLES.get(rows[0].get("legacy_role"), ()))


def list_roles(user_id: int) -> List[str]:
    """
    用户的全部六角色，按优先级降序（dict_admin > sys_admin > reviewer >
    editor > annotator > viewer）。

    事实源是 user_roles 表；账号没有任何 user_roles 行（存量账号尚未迁移）
    时按旧 users.role 列映射兜底（admin→[dict_admin, sys_admin]，其余同名），
    保证升级前创建的账号在六角色判定下不丢权限。

    fail-closed：用户不存在 / **已停用（active=0）** / 数据库不可用返回 []
    （与 get_user_role 把停用按「会话失效」处理的口径一致 —— 停用账号
    不持有任何有效权限）。

    Args:
        user_id: 用户 id

    Returns:
        list[str]: 六角色列表（可能为空）；priority 高者在前。
    """
    if not isinstance(user_id, int) or user_id <= 0:
        return []
    try:
        return _load_roles_or_raise(user_id)
    except pymysql.Error as e:
        logger.error(f"读取用户 {user_id} 角色列表失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"读取用户 {user_id} 角色列表意外错误: {e}")
        return []


def has_role(user_id: int, role: str) -> bool:
    """
    用户当前是否持有某六角色（实时读库，不用会话快照）。

    fail-closed：停用/不存在的用户、非法角色、数据库故障一律 False。

    Args:
        user_id: 用户 id
        role: 六角色之一（NEW_ROLES）

    Returns:
        bool: 持有为 True。
    """
    if role not in NEW_ROLES:
        logger.error(f"has_role 拒绝非法角色: {role!r}")
        return False
    return role in list_roles(user_id)


def grant_role(user_id: int, role: str, granted_by: Optional[int] = None) -> bool:
    """
    授予用户一个六角色（user_roles 多角色，一人可叠加）。

    重复授予（已持有）返回 False（无实际变更，与 set_role「未变更= False」
    口径一致）；角色非法 / 用户不存在 / 数据库错误返回 False。
    停用用户允许预授权（启用后生效；读取侧 fail-closed 已兜底）。

    Args:
        user_id: 用户 id
        role: 六角色之一（NEW_ROLES）
        granted_by: 授权人 id（平台管理员；系统迁移可为 None）

    Returns:
        bool: 实际新增授权为 True。
    """
    if role not in NEW_ROLES:
        logger.error(f"grant_role 拒绝非法角色: {role!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO user_roles (user_id, role, granted_by) "
                "VALUES (%s, %s, %s)",
                (user_id, role, granted_by),
            )
            if cursor.rowcount <= 0:
                logger.error(
                    f"grant_role 未生效（用户 {user_id} 已持有 {role}，或用户不存在）"
                )
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"授予用户 {user_id} 角色 {role} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"授予用户 {user_id} 角色 {role} 意外错误: {e}")
        return False


def revoke_role(user_id: int, role: str) -> bool:
    """
    撤销用户的一个六角色。

    Returns:
        bool: 实际撤销为 True；未持有 / 角色非法 / 数据库错误为 False
        （与 set_role/set_active「未变更= False」口径一致）。
    """
    if role not in NEW_ROLES:
        logger.error(f"revoke_role 拒绝非法角色: {role!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_roles WHERE user_id = %s AND role = %s",
                (user_id, role),
            )
            if cursor.rowcount <= 0:
                logger.error(
                    f"revoke_role 未生效（用户 {user_id} 未持有 {role}，或用户不存在）"
                )
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"撤销用户 {user_id} 角色 {role} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"撤销用户 {user_id} 角色 {role} 意外错误: {e}")
        return False


def needs_password_change(user_id: int) -> bool:
    """
    用户是否必须修改口令（users.must_change_password=1）。

    建号（create_user）与内置 admin bootstrap 时置 1（管理员签发的初始
    口令必须更换），change_password 成功后清零。供批次 2 登录页「强制
    改密」横幅读取 —— 与 is_using_default_password（弱口令判据）并行使用：
    前者是生命周期标志，后者是默认口令比对判据。

    Returns:
        bool: 需要改密为 True；不需要 / 用户不存在 / 数据库不可用为 False
        （不误报横幅）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT must_change_password FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"读取用户 {user_id} 改密标志失败（MySQL）: {e}")
        return False
    except Exception as e:
        logger.error(f"读取用户 {user_id} 改密标志意外错误: {e}")
        return False
    if row is None:
        return False
    return bool(int(row.get("must_change_password") or 0))


def is_using_default_password(user_id: int) -> bool:
    """
    该用户当前口令是否仍是内置默认口令（R1-P2c 弱口令判据）。

    判据：取库中 password_hash，``verify_password(_DEFAULT_ADMIN_PASSWORD,
    stored)``。哈希不出数据层 —— 明文/哈希比较都在本模块内完成，
    调用方（app 登录横幅）只拿 bool。

    Args:
        user_id: 用户 id

    Returns:
        bool: 当前哈希仍匹配默认口令为 True（登录页须常驻强制改密横幅）；
        已改密 / 用户不存在 / 数据库不可用为 False（不误报横幅）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT password_hash FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"读取用户 {user_id} 口令判据失败（MySQL）: {e}")
        return False
    except Exception as e:
        logger.error(f"读取用户 {user_id} 口令判据意外错误: {e}")
        return False
    if row is None:
        return False
    return verify_password(_DEFAULT_ADMIN_PASSWORD, row.get("password_hash") or "")


# 新口令最小长度（R1-P2c：内置 admin123 恰 8 位，新口令不得更弱）。
# 规范 §6 未给下限，此处按任务要求取 ≥8。
MIN_PASSWORD_LENGTH = 8


def change_password(user_id: int, new_plain: str) -> bool:
    """
    修改用户口令：长度 ≥ 8 校验 + pbkdf2 重哈希（新随机盐）后写库。

    供登录页「默认口令强制改密」横幅与后续个人设置使用。哈希规则与
    create_user 相同（hash_password 每次生成新盐），旧口令立即失效；
    成功后同时清 must_change_password 标志（改密义务已履行）。

    Args:
        user_id: 用户 id
        new_plain: 新明文口令（只在内存中出现，不落库、不落日志）

    Returns:
        bool: 修改成功为 True；新口令长度不足 8 / 非字符串 /
        用户不存在 / 数据库错误为 False。
    """
    if not isinstance(new_plain, str) or len(new_plain) < MIN_PASSWORD_LENGTH:
        logger.error(
            f"change_password 拒绝弱口令（用户 {user_id}，长度 "
            f"{len(new_plain) if isinstance(new_plain, str) else '非字符串'} "
            f"< {MIN_PASSWORD_LENGTH}）"
        )
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s, must_change_password = 0 "
                "WHERE id = %s",
                (hash_password(new_plain), user_id),
            )
            if cursor.rowcount <= 0:
                logger.error(f"change_password 用户不存在: {user_id}")
                return False
            return True
    except pymysql.Error as e:
        # e 里只有 SQL 错误信息，不含口令
        logger.error(f"修改用户 {user_id} 口令失败: {e}")
        return False
    except Exception as e:
        logger.error(f"修改用户 {user_id} 口令意外错误: {e}")
        return False
