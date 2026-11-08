"""出版导出中心（export_center）测试：权限闸门 + 内容域快照。

两层结构（与既有套件同口径）：
  * 纯函数/闸门层：非 dict 与无 dict_admin 角色的 actor 直接拒绝（不触库）；
    CONTENT_TABLES 纪律——账号安全数据表不得出现在快照范围；
  * 集成层（真 MySQL，skip 模式）：快照构建往返——zip 落盘、MANIFEST 如实、
    export_batches 登记行、缺表跳过记录；库不可用整类 skip。
"""

import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.export_center import (  # noqa: E402
    CONTENT_TABLES,
    build_content_snapshot,
    list_exports,
)

# ============================================
# 闸门与纪律（纯层，无 DB 依赖）
# ============================================


class TestExportGate:
    def test_none_actor_rejected_without_db(self):
        result = build_content_snapshot(actor=None)
        assert result["ok"] is False
        assert "仅词典管理员" in result["error"]

    def test_non_dict_actor_rejected(self):
        result = build_content_snapshot(actor="admin")
        assert result["ok"] is False

    def test_viewer_role_rejected(self):
        result = build_content_snapshot(
            actor={"id": 9, "username": "v", "role": "viewer",
                   "roles": ["viewer"]})
        assert result["ok"] is False

    def test_legacy_admin_allowed_shape(self):
        """legacy admin（dict_admin 折叠）通过角色闸——失败只可能来自 DB 层。"""
        result = build_content_snapshot(
            actor={"id": 1, "username": "admin", "role": "admin",
                   "roles": ["dict_admin", "sys_admin"]})
        # 无库环境 error 来自 DB 异常而非权限；有库环境 ok——两种都不该是权限拒绝
        if not result["ok"]:
            assert "仅词典管理员" not in result["error"]

    def test_no_account_security_tables_in_scope(self):
        """§15：账号安全数据绝不进内容域快照。"""
        banned = {"users", "user_roles", "settings_audit", "ai_proposals",
                  "annotation_submissions"}
        assert not banned & set(CONTENT_TABLES)


# ============================================
# 集成层：真 MySQL 快照往返
# ============================================

def _mysql_reachable() -> bool:
    """连通探针（RV-10 P1-3）：只 `import pymysql` 恒为 True 探不出连通性，
    改为真建连接，口径对齐 test_fx3_perf._db_available / test_users_db._mysql_reachable。"""
    try:
        import pymysql

        import src.mysql_db as db

        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过导出中心集成测试")
class TestContentSnapshot:
    def test_snapshot_roundtrip(self, tmp_path):
        actor = {"id": 1, "username": "admin", "role": "admin",
                 "roles": ["dict_admin", "sys_admin"]}
        result = build_content_snapshot(actor=actor, license_checked=False)
        assert result["ok"] is True, result.get("error")
        assert result["batch_id"] > 0
        assert Path(result["zip_path"]).exists()
        with zipfile.ZipFile(result["zip_path"]) as zf:
            names = zf.namelist()
            assert "MANIFEST.txt" in names
            manifest = zf.read("MANIFEST.txt").decode("utf-8")
            assert "未过" in manifest  # license_checked=False 如实标注
        included = set(result["tables_included"])
        assert "definitions" in included
        # 缺表如实跳过（不编空文件）
        for t in result["tables_skipped"]:
            assert t not in included
        exports = list_exports(limit=5)
        assert any(e["id"] == result["batch_id"] for e in exports)

    def test_skipped_tables_reason_recorded(self):
        actor = {"id": 1, "username": "admin", "role": "admin",
                 "roles": ["dict_admin", "sys_admin"]}
        result = build_content_snapshot(actor=actor)
        assert result["ok"] is True
        # 尚未建的编纂域表应出现在跳过清单（如 sense_examples/sense_translations）
        assert isinstance(result["tables_skipped"], list)
