"""范畴×工具运行层持久化 —— category_tool_settings / settings_audit 两表数据层
（FX-18，架构规范 §4 工具插件体系「两步激活」＋ §7 运行层配置的落库实现）。

是什么（两张表，平台架构设计规范 附录 A 新增表清单；DDL 单一来源在
src/mysql_db.py 的 CREATE_TABLES_SQL —— init_database 统一建表，启动零额外成本）：

  category_tool_settings  一行一个（范畴 × 工具）的两步激活状态：
                          available（平台管理员位）＋ enabled（词典管理员位，
                          **必须 available 先行**）＋ tool_version 快照 ＋
                          params（运行参数，§7「enabled＋运行参数」）。
                          UNIQUE(category, tool_id) 保证置位走 UPDATE 幂等。
  settings_audit          运行层操作审计：who(actor_id/actor_username) /
                          when(created_at) / action / old→new(old_value/
                          new_value)。审计行永久保留（软引用无 FK，删号不阻、
                          行不消失，username 冗余列仍可读）。

两步激活语义（§4 原文口径，本模块是它的应用层执行点）：
  1. 平台管理员 available_set / available_unset —— 安装/依赖/selfcheck 就绪位；
  2. 词典管理员 enabled_set / enabled_unset —— 工作方法决策位；enabled=1
     的前置条件是该 (category, tool_id) 已 available=1（不满足直接拒绝，
     不靠 DDL 报错）；available_unset 在仍有 enabled=1 的范畴上拒绝
     （保持 enabled ⊆ available 不变式；规范未明文，本模块选「拒绝」而非
     「级联熄灭」—— 级联会以平台管理员身份写 enabled 审计，越权语义）。

权限口径（§8 六角色）：available 位归平台管理员（sys_admin）、enabled 位归
词典管理员（dict_admin），判定统一走 guards.require_role（本模块不做角色
判定实现，只声明「动作 → 允许角色集」映射，与 users_admin_page 同型）；
写路径全部带 actor（审计落 actor_id/actor_username）。

registry 接线（FX-18）：registry_enabled_override(tool_id) 提供注册表的
「DB 持久化位优先」取数口 —— 有行以 DB 为准（任一范畴 enabled=1 即启用），
无行 / 库不可用返回 None 让注册表回落进程内 _ENABLED（兼容测试打桩）；
bind_registry_loader() 把它接到 src/tools/registry.py 的 loader 缝上
（函数指针赋值，零启动成本，import 永不触库）。

接口：
  ensure_tool_settings_tables        幂等建两表（测试沙箱 / 独立部署用；
                                     生产路径由 init_database 的
                                     CREATE_TABLES_SQL 覆盖，二者同 DDL）
  available_set / available_unset    平台管理员（require_role sys_admin）
  enabled_set / enabled_unset        词典管理员（require_role dict_admin）
  get_setting / list_settings        按行读
  is_enabled / enabled_map           按 (category, tool_key) 查启用态
  registry_enabled_override          注册表 loader 取数口（tool_id 维度）
  bind_registry_loader               绑定/解绑注册表 loader 缝
  list_audit                         审计行读（倒序，限条数）

降级：
  数据库不可用时读路径返回 None / [] / False，写路径返回 False，只记日志
  不抛异常（与 registry_db / media_db 容错口径一致）；权限违例例外 ——
  PermissionError 照抛（guards 契约，页面捕获转 st.error）。

安全规则：
  1. SQL 一律参数化，本文件无一处把值拼进 SQL 文本（表名来自模块常量）；
  2. 入参在应用层先校验再入库：空 category / tool_key、超长值根本不进库；
  3. 角色判定复用 guards.require_role（六角色 effective 口径单一实现）；
  4. 留痕列 NULL 口径（RV2-3 第 1 类 INT NULL）：actor/updated_by 为
     users.id 软引用（无 FK —— CREATE_TABLES_SQL 先于 users 表存在），
     NULL = 系统作业/无人。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from src.guards import require_role
from src.mysql_db import get_db_cursor
from src.tools import registry as _registry

logger = logging.getLogger(__name__)

__all__ = [
    "SCOPE",
    "MAX_CATEGORY_LEN",
    "MAX_TOOL_KEY_LEN",
    "ACTION_AVAILABLE_SET",
    "ACTION_AVAILABLE_UNSET",
    "ACTION_ENABLED_SET",
    "ACTION_ENABLED_UNSET",
    "ensure_tool_settings_tables",
    "available_set",
    "available_unset",
    "enabled_set",
    "enabled_unset",
    "get_setting",
    "list_settings",
    "is_enabled",
    "enabled_map",
    "registry_enabled_override",
    "bind_registry_loader",
    "list_audit",
]

# ============================================
# 常量（字段长度与 DDL 一致，应用层先拒超长值）
# ============================================
SCOPE = "tool_settings"          # settings_audit.scope 固定值
MAX_CATEGORY_LEN = 64            # category VARCHAR(64) NOT NULL
MAX_TOOL_KEY_LEN = 64            # tool_id VARCHAR(64) NOT NULL

ACTION_AVAILABLE_SET = "available_set"
ACTION_AVAILABLE_UNSET = "available_unset"
ACTION_ENABLED_SET = "enabled_set"
ACTION_ENABLED_UNSET = "enabled_unset"


# ============================================
# 建表（幂等；与 mysql_db.CREATE_TABLES_SQL 同 DDL，测试沙箱用）
# ============================================
SETTINGS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS category_tool_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category VARCHAR(64) NOT NULL COMMENT '范畴名（configs/<category>/ 目录名）',
  tool_id VARCHAR(64) NOT NULL COMMENT '工具 id（注册表 ToolSpec.id；D⑥ 口径 tool_id VARCHAR）',
  tool_version VARCHAR(40) NULL COMMENT '最近启用时的工具版本快照（D⑥ 口径 version；未启用为 NULL）',
  available TINYINT(1) NOT NULL DEFAULT 0 COMMENT '平台管理员 available 位（两步激活第一步）',
  enabled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '词典管理员 enabled 位（两步激活第二步，须 available=1）',
  params JSON NULL COMMENT '运行参数（§7 运行层 enabled＋运行参数；未调参为 NULL）',
  updated_by INT NULL COMMENT '最近操作人 users.id（软引用无 FK，NULL=系统作业/无人）',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_category_tool (category, tool_id),
  INDEX idx_cts_tool (tool_id),
  INDEX idx_cts_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

AUDIT_TABLE_SQL = """CREATE TABLE IF NOT EXISTS settings_audit (
  id INT AUTO_INCREMENT PRIMARY KEY,
  scope VARCHAR(40) NOT NULL DEFAULT 'tool_settings'
      COMMENT '审计范围（当前固定 tool_settings：范畴×工具运行层配置）',
  category VARCHAR(64) NULL COMMENT '范畴名（全局动作无范畴为 NULL）',
  tool_id VARCHAR(64) NULL COMMENT '工具 id',
  action VARCHAR(40) NOT NULL COMMENT '动作：available_set/available_unset/enabled_set/enabled_unset',
  old_value VARCHAR(255) NULL COMMENT '变更前值（JSON 文本；首次设置无旧值为 NULL）',
  new_value VARCHAR(255) NULL COMMENT '变更后值（JSON 文本）',
  actor_id INT NULL COMMENT '操作人 users.id（软引用无 FK，审计行永久保留）',
  actor_username VARCHAR(64) NULL COMMENT '操作人 username 冗余留痕（删号后仍可读）',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_sa_scope (scope, category, tool_id),
  INDEX idx_sa_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


def ensure_tool_settings_tables() -> bool:
    """幂等创建 category_tool_settings / settings_audit（可重复调用）。

    生产路径：两表 DDL 已并入 mysql_db.CREATE_TABLES_SQL，init_database
    统一建 —— 本函数给测试沙箱（monkeypatch MYSQL_DATABASE 的独立库）与
    独立部署场景用，失败返回 False 只记日志不抛（容错口径）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(SETTINGS_TABLE_SQL)
            cursor.execute(AUDIT_TABLE_SQL)
        return True
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("建 tool_settings 两表失败: %s", exc)
        return False


# ============================================
# 内部工具函数
# ============================================
def _norm_pair(category: Any, tool_key: Any) -> Optional[tuple]:
    """(category, tool_key) 入参校验：非空字符串、不超长 → 规整后二元组；
    非法返回 None（应用层先拒，不碰库）。"""
    if not isinstance(category, str) or not category.strip():
        return None
    if not isinstance(tool_key, str) or not tool_key.strip():
        return None
    category = category.strip()
    tool_key = tool_key.strip()
    if len(category) > MAX_CATEGORY_LEN or len(tool_key) > MAX_TOOL_KEY_LEN:
        return None
    return category, tool_key


def _actor_ref(actor: Any) -> tuple:
    """从通过闸门的 actor dict 取留痕引用：(actor_id, actor_username)。"""
    if not isinstance(actor, dict):
        return None, None
    return actor.get("id"), actor.get("username")


def _value_json(available: bool, enabled: bool) -> str:
    """审计 old_value / new_value 的 JSON 文本口径。"""
    return json.dumps({"available": bool(available), "enabled": bool(enabled)},
                      ensure_ascii=False)


def _read_row(cursor, category: str, tool_key: str) -> Optional[Dict[str, Any]]:
    """读单行（内部；cursor 由调用方提供）。"""
    cursor.execute(
        "SELECT id, category, tool_id, tool_version, available, enabled, "
        "params, updated_by, created_at, updated_at "
        "FROM category_tool_settings WHERE category = %s AND tool_id = %s",
        (category, tool_key),
    )
    return cursor.fetchone()


def _write_audit(cursor, actor: Any, action: str, category: str,
                 tool_key: str, old_value: Optional[str],
                 new_value: Optional[str]) -> None:
    """审计写入（who/when/action/old→new；when 由 created_at DEFAULT 供）。

    审计失败不阻断主操作（日志告警）—— 留痕尽力而为，与主写同连接同
    事务口径（autocommit 路径各自提交，极端情况下主行成而审计不成，
    docstring 如实声明）。
    """
    try:
        actor_id, actor_username = _actor_ref(actor)
        cursor.execute(
            "INSERT INTO settings_audit "
            "(scope, category, tool_id, action, old_value, new_value, "
            " actor_id, actor_username) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (SCOPE, category, tool_key, action, old_value, new_value,
             actor_id if isinstance(actor_id, int) else None,
             actor_username if isinstance(actor_username, str) else None),
        )
    except Exception as exc:  # noqa: BLE001 审计失败不阻断主操作
        logger.error("settings_audit 写入失败（action=%s tool=%s/%s）: %s",
                     action, category, tool_key, exc)


# ============================================
# 两步激活写路径（权限闸门在函数入口）
# ============================================
def available_set(category: str, tool_key: str, actor: Any = None,
                  *, available: bool = True) -> bool:
    """平台管理员置 available 位（两步激活第一步，§4/§8：工具 available）。

    - 权限：require_role(actor, {"sys_admin"})，不满足抛 PermissionError；
    - 已有行 → UPDATE 幂等；无行 → INSERT（available 位独立于 enabled 存在，
      两步激活允许「先 available 未 enabled」的中间态）；
    - available 由 True 撤为 False 且该行 enabled=1 → 拒绝（返回 False，
      不变式 enabled ⊆ available；见模块 docstring 口径说明）。

    Returns:
        True 写库成功；False 入参非法 / 拒绝撤位 / 数据库错误。
    """
    require_role(actor, {"sys_admin"}, action="工具 available 设置")
    pair = _norm_pair(category, tool_key)
    if pair is None:
        logger.error("available_set 拒绝非法入参: category=%r tool_key=%r",
                     category, tool_key)
        return False
    cat, key = pair
    try:
        with get_db_cursor() as cursor:
            row = _read_row(cursor, cat, key)
            old_row = dict(row) if row else None
            if row is None:
                cursor.execute(
                    "INSERT INTO category_tool_settings "
                    "(category, tool_id, available, updated_by) "
                    "VALUES (%s, %s, %s, %s)",
                    (cat, key, 1 if available else 0, _actor_ref(actor)[0]),
                )
            else:
                if row.get("enabled") and not available:
                    logger.error(
                        "available_set 拒绝撤位：工具 %s/%s 仍 enabled=1"
                        "（enabled ⊆ available 不变式），先由词典管理员解除启用",
                        cat, key)
                    return False
                cursor.execute(
                    "UPDATE category_tool_settings SET available = %s, "
                    "updated_by = %s WHERE id = %s",
                    (1 if available else 0, _actor_ref(actor)[0], row["id"]),
                )
            old_value = _value_json(bool(old_row["available"]),
                                    bool(old_row["enabled"])) if old_row else None
            new_value = _value_json(available,
                                    bool(old_row["enabled"]) if old_row else False)
            action = ACTION_AVAILABLE_SET if available else ACTION_AVAILABLE_UNSET
            _write_audit(cursor, actor, action, cat, key, old_value, new_value)
        return True
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("available_set 写库失败（%s/%s）: %s", cat, key, exc)
        return False


def available_unset(category: str, tool_key: str, actor: Any = None) -> bool:
    """平台管理员撤 available 位（available_set 的反向入口）。"""
    return available_set(category, tool_key, actor, available=False)


def enabled_set(category: str, tool_key: str, actor: Any = None,
                *, enabled: bool = True) -> bool:
    """词典管理员置 enabled 位（两步激活第二步：界面点亮＋调运行参数）。

    - 权限：require_role(actor, {"dict_admin"})，不满足抛 PermissionError；
    - **available 先行**（两步激活语义）：enabled=True 时该 (category,
      tool_key) 必须 available=1（DB 读不到该行或 available=0 一律拒绝，
      返回 False）；
    - 置 enabled=True 时快照注册表当前 tool_version（D⑥ 口径 version）；
      工具未注册同样拒绝（引用必须先在注册表）；
    - 审计照写（含被拒的「未 available 先行」吗？——不：拒绝路径不产生
      状态变更，不留审计行，只记日志）。
    """
    require_role(actor, {"dict_admin"}, action="工具 enabled 设置")
    pair = _norm_pair(category, tool_key)
    if pair is None:
        logger.error("enabled_set 拒绝非法入参: category=%r tool_key=%r",
                     category, tool_key)
        return False
    cat, key = pair
    try:
        with get_db_cursor() as cursor:
            row = _read_row(cursor, cat, key)
            old_row = dict(row) if row else None
            if enabled:
                # 两步激活：available 必须先行
                if row is None or not row.get("available"):
                    logger.error(
                        "enabled_set 拒绝：工具 %s/%s 未 available 先行"
                        "（两步激活：平台管理员 available → 词典管理员 enabled）",
                        cat, key)
                    return False
                spec = _registry.get_tool(key)
                if spec is None:
                    logger.error("enabled_set 拒绝：工具 %s 未注册（引用必须先在注册表）",
                                 key)
                    return False
                version = spec.version
            else:
                version = (old_row or {}).get("tool_version")
            if row is None:
                if not enabled:
                    # 幂等熄灭：本来就没有持久化行，无状态可变更（不写审计）
                    return True
                # enabled=True 且无行：available 先行前置条件已保证非 None；
                # 此分支为防御（不应到达）
                logger.error("enabled_set 异常：行不存在（不应到达）")
                return False
            cursor.execute(
                "UPDATE category_tool_settings SET enabled = %s, "
                "tool_version = %s, updated_by = %s WHERE id = %s",
                (1 if enabled else 0, version, _actor_ref(actor)[0], row["id"]),
            )
            old_value = _value_json(bool(old_row["available"]),
                                    bool(old_row["enabled"])) if old_row else None
            new_value = _value_json(bool(old_row["available"]) if old_row else False,
                                    enabled)
            action = ACTION_ENABLED_SET if enabled else ACTION_ENABLED_UNSET
            _write_audit(cursor, actor, action, cat, key, old_value, new_value)
        # 进程内注册表位同步刷新（页面立即生效；重启后由 DB 位接管）
        _registry.set_enabled(key, enabled)
        return True
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("enabled_set 写库失败（%s/%s）: %s", cat, key, exc)
        return False


def enabled_unset(category: str, tool_key: str, actor: Any = None) -> bool:
    """词典管理员撤 enabled 位（enabled_set 的反向入口；available 位不动）。"""
    return enabled_set(category, tool_key, actor, enabled=False)


# ============================================
# 读路径（按 (category, tool_key) 查询启用态）
# ============================================
def get_setting(category: str, tool_key: str) -> Optional[Dict[str, Any]]:
    """读单行设置；无行 / 入参非法 / 库不可用返回 None。"""
    pair = _norm_pair(category, tool_key)
    if pair is None:
        return None
    cat, key = pair
    try:
        with get_db_cursor() as cursor:
            return _read_row(cursor, cat, key)
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("get_setting 读库失败（%s/%s）: %s", cat, key, exc)
        return None


def list_settings(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """列设置行（category 给定按范畴过滤；按 category, tool_id 排序稳定）。

    库不可用返回 []（容错口径）。
    """
    try:
        with get_db_cursor() as cursor:
            if isinstance(category, str) and category.strip():
                cursor.execute(
                    "SELECT id, category, tool_id, tool_version, available, "
                    "enabled, params, updated_by, created_at, updated_at "
                    "FROM category_tool_settings WHERE category = %s "
                    "ORDER BY category, tool_id",
                    (category.strip(),),
                )
            else:
                cursor.execute(
                    "SELECT id, category, tool_id, tool_version, available, "
                    "enabled, params, updated_by, created_at, updated_at "
                    "FROM category_tool_settings ORDER BY category, tool_id"
                )
            return list(cursor.fetchall())
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("list_settings 读库失败: %s", exc)
        return []


def is_enabled(category: str, tool_key: str) -> bool:
    """按 (category, tool_key) 查启用态：行存在以 DB 为准（enabled=1），
    无行 / 入参非法 / 库不可用返回 False（未配置 = 未启用，fail-closed）。"""
    pair = _norm_pair(category, tool_key)
    if pair is None:
        return False
    cat, key = pair
    try:
        with get_db_cursor() as cursor:
            row = _read_row(cursor, cat, key)
            return bool(row and row.get("enabled"))
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("is_enabled 读库失败（%s/%s）: %s", cat, key, exc)
        return False


def enabled_map(category: str) -> Dict[str, bool]:
    """一范畴内 {tool_key: enabled} 映射（页面 enabled 区一次取数；
    库不可用 / 非法入参返回 {}）。"""
    pair = _norm_pair(category, "__probe__")
    if pair is None:
        return {}
    cat = pair[0]
    return {row["tool_id"]: bool(row.get("enabled"))
            for row in list_settings(cat)}


# ============================================
# registry 接线：DB 持久化位优先，读不到回落进程内 _ENABLED
# ============================================
def registry_enabled_override(tool_id: str) -> Optional[bool]:
    """注册表 enabled 查询的 DB 取数口（tool_id 维度投影）。

    口径：
    - 该 tool_id 在库中有行 → 以 DB 为准：任一范畴 enabled=1 即启用
      （注册表是全局能力面；范畴维度决策留在 (category, tool_id) 行上）；
    - 无行 / 入参非法 / 库不可用 → None（调用方回落进程内 _ENABLED，
      兼容测试打桩 —— 注册表 loader 默认未绑定时行为与原实现逐字节一致）。
    """
    if not isinstance(tool_id, str) or not tool_id.strip():
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT MAX(enabled) AS any_enabled FROM category_tool_settings "
                "WHERE tool_id = %s",
                (tool_id.strip(),),
            )
            row = cursor.fetchone()
        if row is None or row.get("any_enabled") is None:
            return None            # 该工具无任何持久化行 → 回落
        return bool(row["any_enabled"])
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("registry_enabled_override 读库失败（tool=%s）: %s",
                     tool_id, exc)
        return None


def bind_registry_loader(bind: bool = True) -> None:
    """把 registry_enabled_override 绑到注册表的 DB loader 缝上（或解绑）。

    - bind=True：注册表 enabled 查询改为「DB 持久化位优先，读不到回落
      进程内 _ENABLED」（FX-18 接线口径）；库不可用时 override 返回
      None，自动回落，页面/测试不炸；
    - bind=False：解绑（注册表行为与原实现一致；测试隔离用）。
    本函数只做函数指针赋值，零启动成本、import 不触库。
    """
    _registry.set_db_enabled_loader(
        registry_enabled_override if bind else None)


def list_audit(limit: int = 50, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """审计行读（created_at 倒序；limit≤0 或非法 → []，库不可用 → []）。"""
    try:
        limit_n = int(limit)
    except (TypeError, ValueError):
        return []
    if limit_n <= 0:
        return []
    try:
        with get_db_cursor() as cursor:
            if isinstance(category, str) and category.strip():
                cursor.execute(
                    "SELECT id, scope, category, tool_id, action, old_value, "
                    "new_value, actor_id, actor_username, created_at "
                    "FROM settings_audit WHERE scope = %s AND category = %s "
                    "ORDER BY id DESC LIMIT %s",
                    (SCOPE, category.strip(), limit_n),
                )
            else:
                cursor.execute(
                    "SELECT id, scope, category, tool_id, action, old_value, "
                    "new_value, actor_id, actor_username, created_at "
                    "FROM settings_audit WHERE scope = %s "
                    "ORDER BY id DESC LIMIT %s",
                    (SCOPE, limit_n),
                )
            return list(cursor.fetchall())
    except Exception as exc:  # noqa: BLE001 库不可用降级
        logger.error("list_audit 读库失败: %s", exc)
        return []
