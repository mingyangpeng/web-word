"""资源登记数据层 —— resource_registry 表（D⑥ 资源发布域，批次 11）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D⑥「resource_registry
（许可必填,双人双签）」、§3 闸门表 G6「许可检查」、§15（数据出入口纪律：
对外交付必须走词典管理员的出版导出）。

是什么（一张表，平台架构设计规范 附录 A 新增表清单）：

  resource_registry  外部资源登记档案：一行一个（资源 × 版本）。语料库
                     （enTenTen21）、参考词典（OALD/现汉7）、媒体包等
                     进入平台的一切外部资源都要在此登记——name/version/
                     coverage/license 四项必填，UNIQUE(name, version)
                     保证同资源同版本只有一行（重复登记幂等返回已有 id）。
                     **license 必填**是 D⑥ 许可纪律：无许可的资源根本
                     进不了库，G6 出版闸门的「许可终检」逐行审计本表。

双人双签（许可审定=技术录入＋词典管理员审定两条签署线）为批次 12 工单，
本版落数据面：登记（registered_by 留痕）＋清单＋单条读取，供词典管理区
「出版导出」tab 的「🗂️ 资源登记」块与 G6 许可终检取数。

权限口径（§15）：登记/修改属业务数据操作，归词典管理员——页面层
guards.require_dict_admin() 拦截后才能触达 register_resource；本模块
（数据层）不做角色判定，与 dict_admin_db 同口径（docstring 标注以便核对）。

接口：
  ensure_resource_registry_tables / register_resource / list_resources /
  get_resource

降级：
  数据库不可用时 ensure 只记日志不抛异常（页面可继续渲染）；register_resource
  返回 0、list_resources 返回 []、get_resource 返回 None，均只记日志不抛异常
  （与 media_db/dict_admin_db 容错口径一致）。

安全规则：
  1. SQL 一律参数化，本文件无一处把值拼进 SQL 文本（表名来自模块常量）；
  2. 入参在应用层先校验再入库：空 name/version/coverage/license、超长值
     根本不进数据库（不依赖 DDL 报错）；
  3. 许可纪律是本模块硬约束：register_resource 拒绝空 license —— 比起
     DDL NOT NULL 报错，应用层先拒给出可读的错误日志；
  4. 无外键（registered_by 为 users.username 软引用），ensure 可独立先行
     建表，不依赖 users 是否已迁移。
"""

import logging
from typing import Any, Dict, List, Optional

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（字段长度与 DDL 一致，应用层先拒超长值）
# ============================================
MAX_NAME_LEN = 120          # name VARCHAR(120) NOT NULL
MAX_VERSION_LEN = 64        # version VARCHAR(64) NOT NULL
MAX_COVERAGE_LEN = 255      # coverage VARCHAR(255) NOT NULL
MAX_LICENSE_LEN = 120       # license VARCHAR(120) NOT NULL（D⑥ 许可必填）
MAX_REGISTERED_BY_LEN = 64  # registered_by VARCHAR(64)（users.username 软引用）

# 建表 DDL（幂等，CREATE TABLE IF NOT EXISTS；UNIQUE(name, version) 去重键）。
RESOURCE_REGISTRY_TABLE_SQL = """CREATE TABLE IF NOT EXISTS resource_registry (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL COMMENT '资源名称（如 enTenTen21 / OALD / 现汉7）',
  version VARCHAR(64) NOT NULL COMMENT '资源版本（如 2021 / 第7版 / v1.0）',
  coverage VARCHAR(255) NOT NULL COMMENT '覆盖说明（如 996 全义项 / 352 建模义位）',
  license VARCHAR(120) NOT NULL COMMENT '许可：必填，无许可不入库（D⑥ 许可纪律）',
  registered_by VARCHAR(64) NOT NULL DEFAULT '' COMMENT '登记人（users.username，软引用留痕）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_resource_registry (name, version),
  KEY idx_resource_registry_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 建表
# ============================================
def ensure_resource_registry_tables() -> None:
    """幂等创建 resource_registry（D⑥ 资源发布域数据面；批次 11）。

    被数据库拒绝（无权限等）只记 error 日志不抛异常，页面可继续渲染。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(RESOURCE_REGISTRY_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"resource_registry 初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"resource_registry 初始化意外错误: {e}")


# ============================================
# 入参规整（应用层先拒，非法值不进数据库）
# ============================================
def _norm_field(value: Any, label: str, max_len: int) -> Optional[str]:
    """规整一个必填字符串字段：非 str/去空白后为空/超长 → None（记日志）。"""
    if not isinstance(value, str):
        logger.error(f"register_resource 拒绝非法 {label}: {value!r}（str）")
        return None
    text = value.strip()
    if not text:
        logger.error(f"register_resource 拒绝空 {label}（必填）")
        return None
    if len(text) > max_len:
        logger.error(
            f"register_resource 拒绝超长 {label}（>{max_len} 字符，{len(text)}）"
        )
        return None
    return text


# ============================================
# 登记（UNIQUE(name, version) 去重 + license 必填）
# ============================================
def register_resource(
    name: Any,
    version: Any,
    coverage: Any,
    license: Any,
    registered_by: Any = "",
) -> int:
    """登记一个外部资源，返回 resource_registry.id。

    许可纪律（硬约束）：license 去空白后必须非空 —— 无许可的资源根本
    不进数据库（D⑥「resource_registry 许可必填」；G6 许可终检逐行
    审计本表，空 license 行会把出版闸门打成未过）。

    UNIQUE(name, version) 去重：同资源同版本重复登记**不新插行**，返回
    已有资源的 id（幂等复用，与 media_assets sha256 去重同款；重复事实
    记 warning 日志留痕）。不同版本各自一行（版本演进如实分立）。

    Args:
        name: 资源名称（非空，≤120 字符，如 'enTenTen21'）
        version: 资源版本（非空，≤64 字符，如 '2021'）
        coverage: 覆盖说明（非空，≤255 字符，如 '996 全义项'）
        license: 许可说明（非空，≤120 字符，如 'CC BY 4.0'）
        registered_by: 登记人（≤64 字符；页面传 users.username 留痕，
            空串允许——数据层不强加角色判定）。RV3-3 跨类型注：操作人参数
            在 int 家族（*_by 存 users.id FK）之外，本参数取 **username
            字符串** —— resource_registry.registered_by 列是 VARCHAR(64)
            （无 FK），页面层把会话用户名直接入列留痕免二次查库；口径表
            见 src/lexical_db.py 模块 docstring「操作人参数口径」。

    Returns:
        int: 资源 id（新登记或去重命中的已有 id）；任一必填项非法 /
        数据库错误返回 0（falsy，调用方按失败处理）。
    """
    name_n = _norm_field(name, "name", MAX_NAME_LEN)
    if name_n is None:
        return 0
    version_n = _norm_field(version, "version", MAX_VERSION_LEN)
    if version_n is None:
        return 0
    coverage_n = _norm_field(coverage, "coverage", MAX_COVERAGE_LEN)
    if coverage_n is None:
        return 0
    # 许可纪律：应用层先拒空 license（DDL NOT NULL 之外的语义校验）
    license_n = _norm_field(license, "license", MAX_LICENSE_LEN)
    if license_n is None:
        return 0
    if not isinstance(registered_by, str):
        logger.error(
            f"register_resource 拒绝非法 registered_by: {registered_by!r}（str）"
        )
        return 0
    registered_by_n = registered_by.strip()
    if len(registered_by_n) > MAX_REGISTERED_BY_LEN:
        logger.error(
            f"register_resource 拒绝超长 registered_by"
            f"（>{MAX_REGISTERED_BY_LEN} 字符）"
        )
        return 0

    try:
        with get_db_cursor() as cursor:
            # UNIQUE(name, version) 去重：已登记 → 返回已有 id，不重复入库
            cursor.execute(
                "SELECT id FROM resource_registry WHERE name = %s AND version = %s",
                (name_n, version_n),
            )
            row = cursor.fetchone()
            if row is not None:
                existing_id = int(row["id"])
                logger.warning(
                    f"register_resource (name, version) 去重命中：返回已有资源 "
                    f"id={existing_id}（本次请求 name={name_n!r}, "
                    f"version={version_n!r}）"
                )
                return existing_id
            cursor.execute(
                "INSERT INTO resource_registry "
                "(name, version, coverage, license, registered_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (name_n, version_n, coverage_n, license_n, registered_by_n),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(
            f"登记资源失败（name={name_n!r}, version={version_n!r}）: {e}"
        )
        return 0
    except Exception as e:
        logger.error(f"登记资源意外错误: {e}")
        return 0


# ============================================
# 查询（清单 + 单条）
# ============================================
def list_resources(limit: int = 50) -> List[Dict[str, Any]]:
    """已登记资源清单（id 倒序=最新在前；出版导出 tab 资源列表用）。

    Args:
        limit: 返回条数上限（1–500，越界取边界；默认 50）。

    Returns:
        list[dict]: id/name/version/coverage/license/registered_by/created_at；
        数据库不可用返回 []（页面渲染降级提示，不抛异常）。
    """
    try:
        limit_n = int(limit)
    except (TypeError, ValueError):
        logger.error(f"list_resources 拒绝非法 limit: {limit!r}")
        return []
    limit_n = max(1, min(limit_n, 500))
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, name, version, coverage, license, registered_by, "
                "created_at FROM resource_registry ORDER BY id DESC LIMIT %s",
                (limit_n,),
            )
            return list(cursor.fetchall() or [])
    except pymysql.Error as e:
        logger.error(f"资源清单读取失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"资源清单读取意外错误: {e}")
        return []


def get_resource(resource_id: Any) -> Optional[Dict[str, Any]]:
    """按 id 读取单条资源登记（不存在/库不可用返回 None）。

    Args:
        resource_id: 资源 id（正整数；非法值返回 None）。
    """
    if isinstance(resource_id, bool):
        return None
    try:
        rid = int(resource_id)
    except (TypeError, ValueError):
        logger.error(f"get_resource 拒绝非法 resource_id: {resource_id!r}")
        return None
    if rid <= 0:
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, name, version, coverage, license, registered_by, "
                "created_at FROM resource_registry WHERE id = %s",
                (rid,),
            )
            return cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"资源读取失败（id={rid}）: {e}")
        return None
    except Exception as e:
        logger.error(f"资源读取意外错误（id={rid}）: {e}")
        return None
