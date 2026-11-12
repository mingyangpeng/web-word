"""功能模块插件注册表（批次 30）——五构件 D·C·P·A·U 插件化。

是什么（用户需求「做成五个插件的模式……供词典管理员进行选取的勾选」）：
    平台五大构件（架构 v5.1 §3）做成**可勾选的模块插件**：词典管理员在
    「🧩 插件管理」（categories_tools_page）勾选启停；停用的模块——侧边栏
    入口隐藏＋页面直访拦截（fail-closed），数据层不受影响（禁用是入口级
    开关，不撤数据——重新勾选即恢复，与工具两步激活同 philosophy）。

五模块 → 页面映射（与 _SIDEBAR_ZONES 对齐）：
    D 义位权威库  → annotate/submission/reliability（语义建模区）
    C 配置定义层  → 范畴包配置面（configs 六件套；无独立页——挂 categories_tools_page）
    P 编纂工序链  → cluster/template/writing/lexical/dict_admin（编纂产出＋词典管理）
    A 协作智能层  → ai_hub＋AI 功能（协作智能层）
    U 编者界面层  → search/graph/corpus/domain/semantic（查阅展示区）

纪律：
    * 默认全启用（新增模块/存量库无行 → enabled——升级不自伤）；
    * 勾选持久化 module_plugins 表（enabled_by 留痕 RV2-3 第 1 类）；
    * U 编者界面层为查阅底线：**禁止停用**（勾选禁用——查阅是平台存在的
      底线，勾选 UI 上该行置灰）；
    * C 配置定义层同理**禁止停用**（配置层是引擎输入，停 C 等于停全站）；
      两者的勾选框置灰＋caption 说明。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.guards import require_role
from src.mysql_db import get_db_cursor
from src.users_db import effective_six_roles

logger = logging.getLogger(__name__)

MODULE_D = "d"
MODULE_C = "c"
MODULE_P = "p"
MODULE_A = "a"
MODULE_U = "u"

MODULE_SPECS: Dict[str, Dict[str, Any]] = {
    MODULE_D: {
        "name": "义位权威库",
        "symbol": "D",
        "pages": ("annotate", "submission", "reliability"),
        "description": "义位数据与标注工作流（标注平台/标注提交/信度报告）",
        "lock": False,
    },
    MODULE_C: {
        "name": "配置定义层",
        "symbol": "C",
        "pages": (),
        "description": "范畴包六件套配置（引擎输入；停用＝停全站，锁定项）",
        "lock": True,
    },
    MODULE_P: {
        "name": "编纂工序链",
        "symbol": "P",
        "pages": ("cluster", "template", "writing", "lexical", "dict_admin"),
        "description": "聚类→模板→撰写→例证→出版（编纂产出＋词典管理）",
        "lock": False,
    },
    MODULE_A: {
        "name": "协作智能层",
        "symbol": "A",
        "pages": ("ai_hub",),
        "description": "AI 三通道协作（协作收件箱＋AI 功能）",
        "lock": False,
    },
    MODULE_U: {
        "name": "编者界面层",
        "symbol": "U",
        "pages": ("search", "graph", "corpus", "domain", "semantic"),
        "description": "查阅展示（公众入口；平台底线，锁定项）",
        "lock": True,
    },
}

_PAGE_TO_MODULE: Dict[str, str] = {
    page: mod
    for mod, spec in MODULE_SPECS.items()
    for page in spec["pages"]
}

MODULE_PLUGINS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS module_plugins (
        module_key VARCHAR(16) NOT NULL COMMENT '模块键（MODULE_SPECS 键）',
        enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '启用位（默认 1——存量库/新键不自伤）',
        enabled_by INT NULL COMMENT '操作人 users.id（软引用无 FK —— RV2-3 第 1 类）',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (module_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_TABLES_ENSURED = False


def ensure_module_plugins_table() -> bool:
    """幂等建表（进程哨兵直通；失败不置位自动重试——照 user_context_db 先例）。"""
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return True
    try:
        with get_db_cursor() as cursor:
            cursor.execute(MODULE_PLUGINS_TABLE_SQL)
        _TABLES_ENSURED = True
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"module_plugins 建表失败（下次调用重试）: {e}")
        return False


def _require_module_actor(actor: Any, action: str) -> Dict[str, Any]:
    """模块勾选权限闸：仅词典管理员（sys_admin 兼判，与工具点亮同口径）。"""
    if not isinstance(actor, dict):
        raise PermissionError(f"{action}需要登录会话用户（dict 形态）")
    effective = effective_six_roles(actor)
    if not ({"dict_admin", "sys_admin"} & effective):
        raise PermissionError(
            f"{action}被拒绝：当前用户（{actor.get('username', '?')}）有效角色集"
            "不含词典管理员 —— 功能模块勾选仅词典管理员可执行"
        )
    return actor


def is_module_enabled(module_key: str) -> bool:
    """模块启用判定（页面门/侧边栏过滤的单一实现）。

    语义：无行/表未建/库不可用/未知模块键 → **True**（默认启用——升级
    不自伤；fail-open 与工具两步激活同 philosophy：禁用是显式动作）。
    仅显式 enabled=0 行 → False。
    """
    if module_key not in MODULE_SPECS:
        return True
    ensure_module_plugins_table()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT enabled FROM module_plugins WHERE module_key = %s",
                (module_key,),
            )
            row = cursor.fetchone()
        if row is None:
            return True
        return bool(row.get("enabled"))
    except Exception as e:  # noqa: BLE001 —— fail-open：禁用是显式动作
        logger.warning(f"module_plugins 读失败（{module_key}，按启用降级）: {e}")
        return True


def disabled_modules() -> set:
    """当前停用的模块键集合（侧边栏过滤一次取全，避免逐页查询）。"""
    ensure_module_plugins_table()
    disabled: set = set()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT module_key, enabled FROM module_plugins "
                "WHERE enabled = 0"
            )
            for row in cursor.fetchall():
                key = row.get("module_key")
                if key in MODULE_SPECS:
                    disabled.add(key)
    except Exception as e:  # noqa: BLE001 —— fail-open 全启用
        logger.warning(f"module_plugins 批量读失败（按全启用降级）: {e}")
    return disabled


def set_module_enabled(module_key: str, enabled: bool, actor: Any) -> bool:
    """勾选启停（词典管理员；写入前校验模块键＋锁定项拒绝）。

    锁定项：MODULE_C（配置定义层——引擎输入）与 MODULE_U（编者界面层——
    查阅底线）不允许停用（勾选框置灰），返回 False 并记日志。
    """
    _require_module_actor(actor, "功能模块勾选")
    if module_key not in MODULE_SPECS:
        logger.error(f"module_plugins 拒绝未知模块键: {module_key!r}")
        return False
    spec = MODULE_SPECS[module_key]
    if not enabled and spec["lock"]:
        logger.error(
            f"module_plugins 拒绝停用锁定模块: {module_key}（{spec['name']}——"
            "配置层/查阅层是平台底线）"
        )
        return False
    if not isinstance(enabled, bool):
        enabled = bool(enabled)
    uid = None
    if isinstance(actor, dict):
        try:
            uid = int(actor.get("id") or 0) or None
        except (TypeError, ValueError):
            uid = None
    ensure_module_plugins_table()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """INSERT INTO module_plugins (module_key, enabled, enabled_by)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE enabled = VALUES(enabled),
                                           enabled_by = VALUES(enabled_by)""",
                (module_key, 1 if enabled else 0, uid),
            )
        logger.info(
            f"功能模块 {module_key}（{spec['name']}）已"
            f"{'启用' if enabled else '停用'}（操作人 {uid}）"
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"module_plugins 写失败（{module_key}）: {e}")
        return False


def list_module_settings() -> List[Dict[str, Any]]:
    """五模块全量设置行（插件管理页渲染用；按 MODULE_SPECS 序）。"""
    ensure_module_plugins_table()
    settings: Dict[str, Dict[str, Any]] = {}
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT module_key, enabled, enabled_by, updated_at "
                           "FROM module_plugins")
            for row in cursor.fetchall():
                settings[row.get("module_key")] = dict(row)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"module_plugins 批量读失败（按默认启用渲染）: {e}")
    out: List[Dict[str, Any]] = []
    for key, spec in MODULE_SPECS.items():
        row = settings.get(key) or {}
        out.append({
            "module_key": key,
            "name": spec["name"],
            "symbol": spec["symbol"],
            "description": spec["description"],
            "lock": spec["lock"],
            "pages": list(spec["pages"]),
            "enabled": bool(row.get("enabled", True)),
            "updated_at": row.get("updated_at"),
            "enabled_by": row.get("enabled_by"),
        })
    return out


def filter_pages_by_modules(pages: Any) -> List[str]:
    """按模块启用态过滤页面键序列（侧边栏/落地三分支共用）。"""
    disabled = disabled_modules()
    if not disabled:
        return list(pages)
    return [p for p in pages if _PAGE_TO_MODULE.get(p, "") not in disabled]
