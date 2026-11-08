"""出版导出中心 —— 内容域快照的唯一正式出口（架构规范 §15 / 工序 15）。

定位：**内容性导出的唯一正式通道**。把词典内容域（词条资源/定制属性/例证/对译/
媒体元数据——表存在才导，缺表如实跳过并记录）打包为 CSV 快照 + zip，登记
`export_batches`（审计线）；G6 出版闸门（许可终检/体例终检）由词典管理区
「出版导出」页接线后在此前置，本版先落数据面与快照机械。

纪律（§15）：
- 内容性导出仅词典管理员——调用方传 actor（页面层 `guards.require_dict_admin()`
  通过后的用户 dict），本模块校验 effective 角色集含 dict_admin，否则拒绝；
- 运维性备份（平台管理员）不是交付通道，与本中心分离；
- 不含 users/密码等账号安全数据（内容域快照显式排除）；
- definitions 导出排除 import_voided=1（R3-9c：导入回滚作废行不进出版交付
  快照，行仍留库审计；见 _dump_table_csv）；
- export_batches.operator_id 只落有效 users.id 或 NULL（R3-6，不落 0 假人）。

降级：某内容表不存在→该表跳过并记入 `skipped`（如实，不编空文件）；
库不可用→整单失败返回 error。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.db_utils import column_exists as _column_exists  # R6-4：公共小件单一实现点
from src.db_utils import table_exists as _db_table_exists
from src.import_engine import has_import_voided_column
from src.mysql_db import get_db_cursor
from src.users_db import effective_six_roles

logger = logging.getLogger(__name__)

EXPORT_BATCHES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS export_batches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  operator_id INT NULL,
  scope VARCHAR(40) NOT NULL DEFAULT 'content_snapshot',
  file_path VARCHAR(255) NOT NULL,
  rows_total INT NOT NULL DEFAULT 0,
  tables_included JSON NULL,
  tables_skipped JSON NULL,
  license_checked TINYINT(1) NOT NULL DEFAULT 0,
  status ENUM('ready','published','revoked') NOT NULL DEFAULT 'ready',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# 内容域快照范围（§15：排除账号安全数据；表不存在则跳过）
CONTENT_TABLES: List[str] = [
    "definitions", "oald_senses", "wordforms",
    "custom_fields", "custom_values", "sense_examples", "sense_translations",
    "media_assets", "media_bindings", "export_batches",
]

EXPORT_ROOT = Path(__file__).resolve().parent.parent / "data" / "exports"

# R3-4b 存量迁移：export_batches 补出版留痕两列（谁把快照流转到 published、
# 何时）。建表 SQL 保持原样（存量库走 ALTER 幂等迁移，information_schema
# 探测、已有则跳过；仿 users_db.must_change_password 先例）。revoked 流转
# 不写这两列（列名语义即出版人；撤销留痕走服务端日志）。
EXPORT_BATCHES_AUDIT_COLUMNS = (
    ("published_by",
     "ALTER TABLE export_batches ADD COLUMN published_by VARCHAR(64) NULL"),
    ("published_at",
     "ALTER TABLE export_batches ADD COLUMN published_at DATETIME NULL"),
)

# R6-6：快照状态域前缀 EXPORT_STATUS_*（与 DDL ENUM('ready','published',
# 'revoked') 一致，值不改）—— 裸 'ready' 等字面量此前散在 SQL 文本里，
# 与 lexical_db.STATUS_*（中文审定链）/ writing_db.STATUS_*（英文撰审链）
# 撞值易混；域前缀后跨模块 import 处一眼可辨归属。
EXPORT_STATUS_READY = "ready"
EXPORT_STATUS_PUBLISHED = "published"
EXPORT_STATUS_REVOKED = "revoked"
EXPORT_STATUSES = (
    EXPORT_STATUS_READY, EXPORT_STATUS_PUBLISHED, EXPORT_STATUS_REVOKED,
)


def ensure_export_tables() -> None:
    """幂等建 export_batches（快照审计线）＋补出版留痕两列（R3-4b，幂等）。"""
    with get_db_cursor() as cursor:
        cursor.execute(EXPORT_BATCHES_TABLE_SQL)
        for column, sql in EXPORT_BATCHES_AUDIT_COLUMNS:
            if not _column_exists(cursor, "export_batches", column):
                cursor.execute(sql)
                logger.info(f"export_batches.{column} 列已补齐（R3-4b 出版留痕迁移）")


def _table_exists(table: str) -> bool:
    """当前库中内容表是否存在（information_schema 只读探测；R6-4 收敛）。

    本模块口径是「只传表名、自开游标」（快照逐表探测用），与
    db_utils.table_exists(cursor, table) 的游标入参版签名不同 —— 实现已
    收敛为对后者的薄包装：information_schema 探测逻辑只剩
    src/db_utils.py 一份，本模块保留同名入参版供 build_content_snapshot
    与测试 monkeypatch 调用点零改动。
    """
    with get_db_cursor() as cursor:
        return _db_table_exists(cursor, table)


def _dump_table_csv(table: str) -> tuple[str, int]:
    """导出单表全行为 CSV 文本（表头+行）；返回 (csv 文本, 行数)。

    definitions 行外排除 import_voided=1（R3-9c）：导入回滚的作废行只留库
    审计，不进出版交付的内容域快照；列缺失（存量库未跑过导入迁移）时如实
    导出全表（探测见 import_engine.has_import_voided_column）。"""
    sql = f"SELECT * FROM {table}"  # 表名来自模块常量白名单
    if table == "definitions" and has_import_voided_column():
        sql += " WHERE import_voided = 0"
    with get_db_cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall() or []
    if not rows:
        return "", 0
    headers = list(rows[0].keys())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h) for h in headers])
    return buffer.getvalue(), len(rows)


def build_content_snapshot(actor: Optional[Dict[str, Any]] = None,
                           license_checked: bool = False) -> Dict[str, Any]:
    """构建内容域快照：逐表 CSV → zip → 登记 export_batches。

    Args:
        actor: 调用方用户 dict（页面层经 guards.require_dict_admin 传入；
               此处再校验一次——单一事实源 effective_six_roles）。
        license_checked: 许可终检是否已过（G6 接线前置；False=内部快照，
                         不得对外交付——页面据此渲染提示）。

    Returns:
        {ok, batch_id?, zip_path?, rows_total, tables_included, tables_skipped,
         license_checked, error?}
    """
    roles = effective_six_roles(actor)
    if "dict_admin" not in roles:
        return {"ok": False,
                "error": "仅词典管理员可执行内容域快照导出（架构规范 §15）。"}
    try:
        ensure_export_tables()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = EXPORT_ROOT / f"snapshot-{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        included: List[str] = []
        skipped: List[str] = []
        rows_total = 0
        zip_path = out_dir / f"content-snapshot-{stamp}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for table in CONTENT_TABLES:
                if not _table_exists(table):
                    skipped.append(table)
                    continue
                text, n = _dump_table_csv(table)
                rows_total += n
                if n:
                    zf.writestr(f"{table}.csv", text)
                    included.append(table)
                else:
                    included.append(table)  # 空表也入清单（0 行如实）
            zf.writestr("MANIFEST.txt",
                        "LexiSchema 内容域快照（内部快照，未经 G6 许可终检不得对外交付）\n"
                        f"生成时间: {stamp}\n包含表: {', '.join(included)}\n"
                        f"跳过(表未建): {', '.join(skipped) or '无'}\n"
                        f"总行数: {rows_total}\n"
                        f"许可终检: {'已过' if license_checked else '未过（仅内部使用）'}\n")
        with get_db_cursor() as cursor:
            # operator_id 落库口径（R3-6）：actor 携带有效 id 才落正整数，
            # 否则 NULL（审计「未知操作人」）—— 绝不落 0（users.id 从 1 起，
            # 0 是不存在的假操作人，污染审计线）。列本就 NULL 可空，无需迁移。
            operator_id = (
                int(actor["id"])
                if isinstance(actor, dict) and actor.get("id")
                else None
            )
            cursor.execute(
                "INSERT INTO export_batches (operator_id, scope, file_path, "
                "rows_total, tables_included, tables_skipped, license_checked, status) "
                "VALUES (%s, 'content_snapshot', %s, %s, %s, %s, %s, %s)",
                (operator_id, str(zip_path.relative_to(
                    Path(__file__).resolve().parent.parent)), rows_total,
                 json.dumps(included), json.dumps(skipped),
                 1 if license_checked else 0, EXPORT_STATUS_READY),
            )
            batch_id = cursor.lastrowid
        return {"ok": True, "batch_id": batch_id, "zip_path": str(zip_path),
                "rows_total": rows_total, "tables_included": included,
                "tables_skipped": skipped, "license_checked": license_checked}
    except Exception as e:  # noqa: BLE001 —— 快照失败整单返回，不半途抛
        logger.warning(f"内容域快照构建失败: {e}")
        return {"ok": False, "error": f"快照构建失败：{e}"}


def list_exports(limit: int = 20) -> List[Dict[str, Any]]:
    """最近快照清单（出版导出页列表用；库不可用返回空）。"""
    try:
        ensure_export_tables()
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, operator_id, scope, file_path, rows_total, "
                "license_checked, status, created_at FROM export_batches "
                "ORDER BY id DESC LIMIT %s", (int(limit),))
            return list(cursor.fetchall() or [])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"快照清单读取失败: {e}")
        return []
