"""用户与权限数据层 —— 多人标注系统的账号存储、登录校验与角色管理。

设计规范：docs/p1/多人标注系统设计规范.md（唯一事实源）§2 users 表 DDL、
§3 模块契约（本文件签名与之一致，不得擅改）、§6 安全规则。

职责边界：
  * 只管 users 一张表与密码哈希 —— 任务分配/提交/仲裁在 annotation_flow.py，
    页面在 users_admin_page.py（集成时由 app.py 按角色分派）。
  * 内置默认 admin：users 表为空时由 ensure_user_tables() 自动创建
    admin/admin123（display_name=内置管理员，role=admin）。
    **该账号仅供首次 bootstrap，首次登录后必须立即修改密码**；修改密码功能
    在登录/个人设置页实现（见规范 §5 UI 集成契约）。

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
    建 users 表（幂等，CREATE TABLE IF NOT EXISTS）+ 内置默认 admin。

    users 表为空时自动创建内置管理员 admin/admin123
    （display_name=内置管理员，role=admin）。
    **首次登录后必须立即修改密码** —— 默认口令是公开的 bootstrap 凭据，
    不能长期留在生产库里。重复调用不会重复创建（表非空即跳过）。

    数据库不可用时只记日志不抛异常（与 mysql_db.init_database 的容错口径一致），
    让调用方（页面）可以继续渲染登录框而不是整页崩掉。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(USERS_TABLE_SQL)
            _ensure_default_admin(cursor)
    except pymysql.Error as e:
        logger.error(f"users 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"users 表初始化意外错误: {e}")


def _ensure_default_admin(cursor) -> None:
    """users 表为空时插入内置默认 admin（供 ensure_user_tables 调用）。"""
    cursor.execute("SELECT COUNT(*) AS n FROM users")
    if int(cursor.fetchone()["n"] or 0) > 0:
        return
    cursor.execute(
        "INSERT INTO users (username, password_hash, display_name, role, active) "
        "VALUES (%s, %s, %s, %s, 1)",
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


# ============================================
# 登录与用户 CRUD
# ============================================

def verify_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    校验用户名+密码，成功返回会话用户信息。

    Args:
        username: 用户名
        password: 明文密码（只在内存中比对，不落库不落日志）

    Returns:
        dict | None: 成功返回 {id, username, display_name, role}（不含
        password_hash，哈希不出数据层）；用户不存在 / 密码错误 /
        active=0（已停用）统一返回 None —— 三种失败不可区分，防账号枚举。
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
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


def create_user(username: str, password: str, display_name: str, role: str) -> Optional[int]:
    """
    新建用户（active=1），返回新用户 id。

    角色必须是 ROLES 之一（应用层先拒，非法值不进数据库）；
    用户名重复（UNIQUE 约束）返回 None。

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
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (username, password_hash, display_name, role, active) "
                "VALUES (%s, %s, %s, %s, 1)",
                (username, hash_password(password), display_name, role),
            )
            return int(cursor.lastrowid)
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
    修改用户角色。

    Args:
        user_id: 用户 id
        role: 目标角色（必须 ∈ ROLES）

    Returns:
        bool: 角色实际变更（或用户存在且值有变化）为 True；角色非法 /
        用户不存在 / 数据库错误为 False。目标值与现值相同时 MySQL 不计为
        变更行，返回 False（对页面而言等价于「未变更」）。
    """
    if role not in ROLES:
        logger.error(f"set_role 拒绝非法角色: {role!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE users SET role = %s WHERE id = %s",
                (role, user_id),
            )
            return cursor.rowcount > 0
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
