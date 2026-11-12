r"""FX-18 修复批次回归测试。

覆盖台账（FX-15 规范×实现对账 组①：工具注册表/两步激活/两表落库/pack 自检）：

  * 两表落库   mysql_db.CREATE_TABLES_SQL 含 category_tool_settings /
               settings_audit 全量 DDL（幂等 CREATE；留痕列 INT NULL 软引用，
               不触 ALTER-only 清单）；沙箱实建两表幂等；
  * 权限闸门   available_set 非 sys_admin 拒 / enabled_set 非 dict_admin 拒
               （guards.require_role，PermissionError 先于任何 DB 触达）；
  * 两步激活   enabled 必须 available 先行（未 available 拒且不留审计）；
               enabled ⊆ available 不变式（enabled=1 时 available_unset 拒，
               RV14-3 后由 UPDATE WHERE 原子复验兜底）；
               enabled_unset 幂等（无行返回 True）；available_unset 幂等
               （无行返回 True 不建行不留痕，RV14-9）；
  * 持久化往返 available → enabled → 查询（get_setting/is_enabled/
               enabled_map/list_settings）全链真库沙箱（web_word_fx18_test）；
  * 审计留痕   available_set/available_unset/enabled_set/enabled_unset 各写
               一行 settings_audit：who(actor_id/username)/action/old→new；
  * registry   DB 持久化位优先（loader 返回值覆盖进程位）、读不到回落
               _ENABLED（None/异常两路）、registry_enabled_override 三态、
               bind_registry_loader 绑定/解绑、reset_registry_state 复位钩子；
  * 内置工具   十类＋multimedia＋schema_family 共 12 工具注册（批次 32）、run 薄包装委托（monkeypatch
               目标函数验证 task_type 固定与参数合并）、render 留阶段 2；
  * pack 自检  三态（无引用通过 / 未注册引用失败 / 已注册未启用警示）＋
               引用解析（字符串/映射/非法形态）＋ 真实 motion 包无引用通过；
  * 页面       范畴与工具页 AppTest：未登录拦截 / viewer 拒 / sys_admin 渲染
               available 区 / dict_admin 渲染 enabled 区（未 available 不可开）
               / 开关即写留审计。

数据库口径：与 test_registry_db.py 同手法 —— 集成用例跑独立测试库
web_word_fx18_test（scripts/grant_local_mysql.sql 已按 `\_` 转义授权三
host），fixture 自建自清；MySQL 不可用则集成类 skip，守卫/纯进程类全跑。
"""

import json
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import src.mysql_db as db  # noqa: E402
from src import tool_settings_db as tsd  # noqa: E402
from src.mysql_db import get_db_cursor  # noqa: E402
from src.tools import builtin  # noqa: E402,F401  导入即注册内置 12 工具（批次 32 起）
from src.tools import pack_check, registry as reg  # noqa: E402
from src.tools.registry import (  # noqa: E402
    RegistryError,
    get_tool,
    list_tools,
    register,
    reset_registry_state,
    set_db_enabled_loader,
    set_enabled,
)

TEST_DB = "web_word_fx18_test"
PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

# 会话用户样例（guards.require_role 显式入参口径；role=legacy 列，
# roles=会话快照，与 app 登录态同构）
SYS_ADMIN = {"id": 2, "username": "sys_a", "role": "viewer",
             "roles": ["sys_admin"]}
DICT_ADMIN = {"id": 3, "username": "dict_a", "role": "viewer",
              "roles": ["dict_admin"]}
LEGACY_ADMIN = {"id": 1, "username": "admin", "role": "admin"}  # 两位一体
EDITOR = {"id": 4, "username": "ed", "role": "viewer", "roles": ["editor"]}
VIEWER = {"id": 5, "username": "vw", "role": "viewer", "roles": ["viewer"]}


@pytest.fixture(autouse=True)
def _isolate_registry():
    """注册表运行态快照/还原（含 FX-18 的 DB loader 缝），测试互不污染。"""
    snap_tools = dict(reg._REGISTRY)
    snap_enabled = set(reg._ENABLED)
    snap_probes = dict(reg._DEP_PROBES)
    snap_loader = reg._DB_ENABLED_LOADER
    yield
    reg._REGISTRY.clear()
    reg._REGISTRY.update(snap_tools)
    reg._ENABLED.clear()
    reg._ENABLED.update(snap_enabled)
    reg._DEP_PROBES.clear()
    reg._DEP_PROBES.update(snap_probes)
    reg.set_db_enabled_loader(snap_loader)


def _mysql_reachable() -> bool:
    """连通探针（只建连接不建库，对齐 test_registry_db/test_pages 口径）。"""
    try:
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


@pytest.fixture
def fx18_env(monkeypatch):
    """建空测试库并让 tool_settings_db 指向它，测试结束 DROP。

    与 test_registry_db.registry_env 同手法：get_db_cursor 在调用时读
    mysql_db 模块全局，monkeypatch MYSQL_DATABASE 即可（连接池按键区分
    host/port/db/user，互不污染）；账号无该库名授权则 skip。
    """
    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
    )
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
            f"COLLATE utf8mb4_unicode_ci"
        )
    except pymysql.err.OperationalError as e:
        conn.close()
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX-18 集成测试: {e}")
    conn.close()

    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
    yield
    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
        autocommit=True,
    )
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.close()


# ============================================
# 1. 两表落库（CREATE_TABLES_SQL 全量 DDL）
# ============================================

def _mysql_db_text() -> str:
    with open(os.path.join(PROJECT_ROOT, "src", "mysql_db.py"),
              "r", encoding="utf-8") as fh:
        return fh.read()


class TestDdl:
    def test_category_tool_settings_ddl_in_create_tables_sql(self):
        text = _mysql_db_text()
        assert "CREATE TABLE IF NOT EXISTS category_tool_settings" in text
        for col in ("category", "tool_id", "tool_version", "available",
                    "enabled", "params JSON", "updated_by INT NULL"):
            assert col in text, f"category_tool_settings 缺列: {col}"
        assert "UNIQUE KEY uq_category_tool (category, tool_id)" in text

    def test_settings_audit_ddl_in_create_tables_sql(self):
        text = _mysql_db_text()
        assert "CREATE TABLE IF NOT EXISTS settings_audit" in text
        for col in ("scope", "action", "old_value", "new_value",
                    "actor_id INT NULL", "actor_username", "created_at"):
            assert col in text, f"settings_audit 缺列: {col}"

    def test_actor_columns_soft_reference_no_fk(self):
        """留痕列口径（RV2-3 第 1 类 INT NULL 软引用）：两表无 REFERENCES
        users —— CREATE_TABLES_SQL 先于 users 表存在，同 ai_proposals
        created_by 口径（审计行永久保留，删号不阻）。"""
        text = _mysql_db_text()
        cts = text.split("CREATE TABLE IF NOT EXISTS category_tool_settings")[1]
        cts = cts.split("ENGINE=InnoDB")[0]
        audit = text.split("CREATE TABLE IF NOT EXISTS settings_audit")[1]
        audit = audit.split("ENGINE=InnoDB")[0]
        assert "REFERENCES" not in cts
        assert "REFERENCES" not in audit

    @pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过建表集成")
    def test_ensure_tables_idempotent(self, fx18_env):
        assert tsd.ensure_tool_settings_tables() is True
        assert tsd.ensure_tool_settings_tables() is True
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME IN ('category_tool_settings',
                                        'settings_audit')"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 2


# ============================================
# 2. 两步激活权限闸（不触库：PermissionError 先于任何 DB 访问）
# ============================================

class TestPermissionGates:
    def test_available_set_requires_sys_admin(self):
        """非平台管理员设 available 一律拒（纯词典管理员也不行——§8 分工）。"""
        for actor in (DICT_ADMIN, EDITOR, VIEWER, None):
            with pytest.raises(PermissionError):
                tsd.available_set("motion", "typicality", actor=actor)

    def test_available_unset_requires_sys_admin(self):
        with pytest.raises(PermissionError):
            tsd.available_unset("motion", "typicality", actor=DICT_ADMIN)

    def test_enabled_set_requires_dict_admin(self):
        """非词典管理员设 enabled 一律拒（纯平台管理员也不行——§8 分工）。"""
        for actor in (SYS_ADMIN, EDITOR, VIEWER, None):
            with pytest.raises(PermissionError):
                tsd.enabled_set("motion", "typicality", actor=actor)

    def test_enabled_unset_requires_dict_admin(self):
        with pytest.raises(PermissionError):
            tsd.enabled_unset("motion", "typicality", actor=SYS_ADMIN)

    def test_legacy_admin_passes_both_gates(self):
        """legacy admin 两位一体（dict_admin+sys_admin）：两个闸门都放行。
        用非法入参短路（闸门在入参校验之前）——只验证放行，不触库。"""
        assert tsd.available_set("", "", actor=LEGACY_ADMIN) is False
        assert tsd.enabled_set("", "", actor=LEGACY_ADMIN) is False

    @pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过集成")
    def test_gate_rejection_writes_nothing(self, fx18_env):
        """权限拒绝路径不产生状态变更也不留审计行。"""
        tsd.ensure_tool_settings_tables()
        with pytest.raises(PermissionError):
            tsd.enabled_set("motion", "typicality", actor=SYS_ADMIN)
        with pytest.raises(PermissionError):
            tsd.available_set("motion", "typicality", actor=DICT_ADMIN)
        assert tsd.list_settings("motion") == []
        assert tsd.list_audit(category="motion") == []


# ============================================
# 3. 两步激活语义 + 持久化往返（真库沙箱）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-18 集成测试")
class TestTwoStepActivationRoundTrip:
    def test_available_then_enabled_full_chain(self, fx18_env):
        """available → enabled 全链：置位/查询/启用态/版本快照。"""
        tsd.ensure_tool_settings_tables()
        assert tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        row = tsd.get_setting("motion", "typicality")
        assert row["available"] == 1 and row["enabled"] == 0
        assert tsd.is_enabled("motion", "typicality") is False

        assert tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        row = tsd.get_setting("motion", "typicality")
        assert row["available"] == 1 and row["enabled"] == 1
        assert row["tool_version"] == "1.0.0"   # 注册表版本快照（D⑥ 口径）
        assert tsd.is_enabled("motion", "typicality") is True
        assert tsd.enabled_map("motion") == {"typicality": True}
        assert [r["tool_id"] for r in tsd.list_settings("motion")] == \
            ["typicality"]

    def test_enabled_requires_available_first(self, fx18_env):
        """available 先行约束：无行 / available=0 时 enabled_set 拒且不留审计。

        RV14-9 口径变更：available_set(available=False) 无行 → 幂等熄灭
        （True，不 INSERT available=0 空行、不留审计——同 enabled_set 无行
        熄灭先例）；「available=0 显式行」改由 先置位→撤下 造出（撤下走
        UPDATE 原子复验并落审计 available_unset），enabled_set 照旧被前置闸拒绝。
        """
        tsd.ensure_tool_settings_tables()
        # 无行（available 未做）：enabled_set 拒且不留审计
        assert tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN) is False
        assert tsd.list_audit(category="motion") == []
        # 无行撤位（RV14-9）：幂等熄灭 True，不建行、不留审计；
        # enabled_set 照旧被「无行=未 available 先行」拒绝
        assert tsd.available_set("motion", "typicality", actor=SYS_ADMIN,
                                 available=False)
        assert tsd.get_setting("motion", "typicality") is None
        assert tsd.list_audit(category="motion") == []
        assert tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN) is False
        # available=0 的显式行（先置位再撤下；撤下也是平台管理员操作，应留痕）
        assert tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        assert tsd.available_unset("motion", "typicality", actor=SYS_ADMIN)
        assert tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN) is False
        actions = [r["action"] for r in tsd.list_audit(category="motion")]
        assert actions == ["available_unset", "available_set"]  # 倒序：仅平台管理员动作留痕；enabled_set 拒绝不留任何审计
        assert tsd.is_enabled("motion", "typicality") is False

    def test_available_unset_blocked_while_enabled(self, fx18_env):
        """enabled ⊆ available 不变式：enabled=1 时撤 available 拒（不级联熄灭）。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        assert tsd.available_unset("motion", "typicality",
                                   actor=SYS_ADMIN) is False
        row = tsd.get_setting("motion", "typicality")
        assert row["available"] == 1 and row["enabled"] == 1

    def test_enabled_unset_then_available_unset(self, fx18_env):
        """先解除 enabled 才能撤 available（两步激活逆序）。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        assert tsd.enabled_unset("motion", "typicality", actor=DICT_ADMIN)
        assert tsd.is_enabled("motion", "typicality") is False
        assert tsd.available_unset("motion", "typicality", actor=SYS_ADMIN)
        row = tsd.get_setting("motion", "typicality")
        assert row["available"] == 0 and row["enabled"] == 0

    def test_enabled_unset_idempotent_on_missing_row(self, fx18_env):
        """幂等熄灭：无持久化行的 enabled_unset 返回 True（无状态可变更）。"""
        tsd.ensure_tool_settings_tables()
        assert tsd.enabled_unset("motion", "template", actor=DICT_ADMIN) is True
        assert tsd.get_setting("motion", "template") is None

    def test_invalid_inputs_rejected_at_app_layer(self, fx18_env):
        """入参在应用层先拒：空值 / 超长（64 列宽）根本不进库。"""
        tsd.ensure_tool_settings_tables()
        assert tsd.available_set("", "typicality", actor=SYS_ADMIN) is False
        assert tsd.available_set("motion", "  ", actor=SYS_ADMIN) is False
        assert tsd.available_set("m" * 65, "typicality",
                                 actor=SYS_ADMIN) is False
        assert tsd.available_set("motion", "t" * 65,
                                 actor=SYS_ADMIN) is False
        assert tsd.available_set(None, "typicality", actor=SYS_ADMIN) is False
        assert tsd.available_set("motion", None, actor=SYS_ADMIN) is False
        assert tsd.list_settings() == []

    def test_registry_unknown_tool_rejected_for_enable(self, fx18_env):
        """引用必须先在注册表：enabled_set 对未注册 id 拒（不发明新工具）。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "ghost_tool", actor=SYS_ADMIN)
        assert tsd.enabled_set("motion", "ghost_tool",
                               actor=DICT_ADMIN) is False
        assert tsd.is_enabled("motion", "ghost_tool") is False


# ============================================
# 4. 审计留痕（who/when/action/old→new）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-18 集成测试")
class TestAuditTrail:
    def test_available_and_enabled_actions_audited(self, fx18_env):
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        tsd.enabled_unset("motion", "typicality", actor=DICT_ADMIN)
        tsd.available_unset("motion", "typicality", actor=SYS_ADMIN)

        rows = tsd.list_audit(category="motion")
        assert [r["action"] for r in rows] == [
            "available_unset", "enabled_unset", "enabled_set", "available_set"]
        assert all(r["scope"] == tsd.SCOPE for r in rows)
        assert all(r["tool_id"] == "typicality" for r in rows)
        # who：操作人 id + username 冗余留痕
        assert rows[0]["actor_id"] == SYS_ADMIN["id"]
        assert rows[0]["actor_username"] == SYS_ADMIN["username"]
        assert rows[1]["actor_id"] == DICT_ADMIN["id"]
        assert rows[1]["actor_username"] == DICT_ADMIN["username"]
        assert all(r["created_at"] is not None for r in rows)   # when
        # old→new（JSON 文本口径；首次置位无旧值为 NULL）
        assert rows[3]["old_value"] is None
        assert json.loads(rows[3]["new_value"]) == {"available": True,
                                                    "enabled": False}
        # rows[2]=enabled_set（首次点亮）：old=INSERT 时的中间态 available=1/enabled=0
        assert json.loads(rows[2]["old_value"]) == {"available": True,
                                                    "enabled": False}
        assert json.loads(rows[2]["new_value"]) == {"available": True,
                                                    "enabled": True}

    def test_main_row_upsert_idempotent_audit_still_written(self, fx18_env):
        """主行 UPDATE 幂等（UNIQUE 约束不重复插）；每次动作仍各留一行审计。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN,
                          available=True)   # 重复置位走 UPDATE
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM category_tool_settings")
            assert int(cursor.fetchone()["n"] or 0) == 1
        assert len(tsd.list_audit(category="motion")) == 2

    def test_list_audit_limit_and_category_filter(self, fx18_env):
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.available_set("speech", "template", actor=SYS_ADMIN)
        assert [r["category"] for r in tsd.list_audit(category="motion")] == \
            ["motion"]
        all_rows = tsd.list_audit(limit=10)
        assert {r["category"] for r in all_rows} == {"motion", "speech"}
        assert tsd.list_audit(limit=0) == []
        assert tsd.list_audit(limit="abc") == []
        # RV19-6：上界 200（越界请求 clamp 到上限，不失控拉取）
        assert tsd.list_audit(limit=500) is not None


# ============================================
# 5. registry 接线：DB 持久化位优先，读不到回落进程内
# ============================================

class TestRegistryDbPriority:
    """loader 缝纯进程内行为（自定义桩，无需 DB）。"""

    def _dummy(self, tool_id="loader_probe"):
        spec = reg.ToolSpec(id=tool_id, name="loader 探针", version="0.1.0",
                            stage="probe_stage")
        register(spec)
        return spec

    def test_no_loader_falls_back_to_process_bits(self):
        spec = self._dummy()
        assert list_tools(enabled_only=True) == []      # 默认全灭
        set_enabled(spec.id, True)
        assert [t.id for t in list_tools(enabled_only=True)] == [spec.id]

    def test_loader_true_overrides_process_off(self):
        spec = self._dummy()
        set_db_enabled_loader(lambda tool_id: True)     # DB 位=启用（优先）
        ids = [t.id for t in list_tools(enabled_only=True)]
        assert spec.id in ids          # 探针被 DB 位点亮
        assert ids == sorted(ids)      # 顺序稳定契约

    def test_loader_false_overrides_process_on(self):
        spec = self._dummy()
        set_enabled(spec.id, True)                      # 进程位=启用
        set_db_enabled_loader(lambda tool_id: False)    # DB 位=未启用（优先）
        assert spec.id not in [t.id for t in list_tools(enabled_only=True)]

    def test_loader_none_falls_back(self):
        spec = self._dummy()
        set_enabled(spec.id, True)
        set_db_enabled_loader(lambda tool_id: None)     # 无持久化行 → 回落
        assert spec.id in [t.id for t in list_tools(enabled_only=True)]

    def test_loader_exception_falls_back(self):
        def _boom(tool_id):
            raise RuntimeError("loader 炸了")
        spec = self._dummy()
        set_enabled(spec.id, True)
        set_db_enabled_loader(_boom)
        assert spec.id in [t.id for t in list_tools(enabled_only=True)]

    def test_unbind_restores_process_semantics(self):
        spec = self._dummy()
        set_db_enabled_loader(lambda tool_id: False)
        set_db_enabled_loader(None)                     # 解绑
        set_enabled(spec.id, True)
        assert spec.id in [t.id for t in list_tools(enabled_only=True)]

    def test_reset_registry_state_hook(self):
        spec = self._dummy()
        set_enabled(spec.id, True)
        reg.register_dep_probe("dep_reset", lambda: False)
        set_db_enabled_loader(lambda tool_id: True)
        reset_registry_state()
        # enabled 位 / 探针 / loader 清空；注册表本体保留（内置工具不重注）
        assert spec.id not in [t.id for t in list_tools(enabled_only=True)]
        assert reg._DEP_PROBES == {}
        assert get_tool("admission") is not None    # 内置注册表本体保留
        assert reg._DB_ENABLED_LOADER is None
        assert reg.get_tool(spec.id) is spec


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-18 集成测试")
class TestRegistryEnabledOverride:
    """registry_enabled_override（DB 取数口）三态 + bind_registry_loader。"""

    def test_override_states(self, fx18_env):
        tsd.ensure_tool_settings_tables()
        assert tsd.registry_enabled_override("typicality") is None  # 无行
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        # 有行（enabled=0）→ 以 DB 为准返回 False；仅完全无行才回落 None
        assert tsd.registry_enabled_override("typicality") is False
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        assert tsd.registry_enabled_override("typicality") is True
        tsd.enabled_unset("motion", "typicality", actor=DICT_ADMIN)
        assert tsd.registry_enabled_override("typicality") is False
        assert tsd.registry_enabled_override("") is None            # 非法入参
        assert tsd.registry_enabled_override(None) is None

    def test_override_any_category_enabled(self, fx18_env):
        """注册表是全局能力面：任一范畴 enabled=1 即启用（范畴决策留行上）。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        tsd.available_set("speech", "typicality", actor=SYS_ADMIN)
        tsd.enabled_unset("speech", "typicality", actor=DICT_ADMIN)  # 幂等熄灭
        assert tsd.registry_enabled_override("typicality") is True

    def test_bind_registry_loader_roundtrip(self, fx18_env):
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        # enabled_set 成功会同步刷新进程位（页面立即生效口径）——先灭进程位，
        # 单独验证「DB 位优先」：绑定时 DB 亮胜过进程灭，解绑后回落进程灭
        set_enabled("typicality", False)
        tsd.bind_registry_loader(True)
        assert "typicality" in {t.id for t in list_tools(enabled_only=True)}
        # 解绑回落进程位（进程位已灭 → 熄）
        tsd.bind_registry_loader(False)
        assert "typicality" not in {t.id for t in list_tools(enabled_only=True)}
        # 反向：DB 灭胜过进程亮（先把 DB 位真正熄灭——enabled_unset 落库）
        set_enabled("typicality", True)
        tsd.enabled_unset("motion", "typicality", actor=DICT_ADMIN)
        tsd.bind_registry_loader(True)
        assert "typicality" not in {t.id for t in list_tools(enabled_only=True)}

    def test_bind_with_unreachable_db_degrades(self, monkeypatch):
        """库不可用 → override 返回 None → 注册表回落进程位（页面不炸）。"""
        from src.tools.registry import ToolSpec
        spec = ToolSpec(id="offline_probe", name="离线探针", version="0.1.0",
                        stage="probe_stage")
        register(spec)
        set_enabled("offline_probe", True)
        # 指向不可达端口（池按键区分，不影响其他用例）
        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        monkeypatch.setattr(db, "MYSQL_PORT", 49999)
        tsd.bind_registry_loader(True)
        try:
            assert tsd.registry_enabled_override("offline_probe") is None
            assert [t.id for t in list_tools(enabled_only=True)] == \
                ["offline_probe"]
        finally:
            set_db_enabled_loader(None)


# ============================================
# 6. 内置十类工具注册补全（十类对照）
# ============================================

# 十类对照（架构 §4 顺序）＋（＋multimedia）：
# tool_id → (stage, 委托模块, 委托函数, run ctx 样例)
TEN_CATEGORY_MAP = [
    ("admission", "admission", "src.annotation_flow", "submit_annotation",
     {"category": "motion", "sense_id": 7, "coder_id": 1,
      "payload": {"admission": "Y"}}),
    ("feature_coding", "feature_coding", "src.annotation_flow",
     "submit_annotation",
     {"category": "motion", "sense_id": 7, "coder_id": 1,
      "payload": {"features": {"P5": 1}}}),
    ("reliability", "reliability", "src.reliability", "run_reliability",
     {"category": "motion", "task_type": "feature_coding"}),
    ("clustering", "clustering", "src.cluster_analysis",
     "build_dendrogram_data", {"category": "motion", "language": "en"}),
    ("typicality", "clustering", "src.cluster_analysis",
     "compute_medoid_ranking",
     {"category": "motion", "language": "zh", "run_id": 3}),
    ("schema", "schema", "src.template_engine", "derive_cluster_schemas",
     {"category": "motion", "language": "en"}),
    ("alignment", "alignment", "src.annotation_flow", "submit_annotation",
     {"category": "motion", "sense_id": 7, "coder_id": 1,
      "payload": {"alignment": "literal"}}),
    ("template", "template", "src.template_engine", "collect_cluster_templates",
     {"category": "motion", "language": "en", "cluster_no": 2}),
    ("semantic_search", "semantic_search", "src.semantic_search",
     "search_similar_senses",
     {"feature_vector": {"P5": 2}, "category": "motion"}),
    ("corpus_evidence", "corpus_evidence", "src.mysql_db",
     "get_corpus_collocations", {"verb": "march", "limit": 50}),
    ("multimedia", "multimedia", "src.media_db", "list_assets_for_anchor",
     {"anchor_type": "word", "anchor_id": 5}),
]

EXPECTED_TOOL_IDS = {t[0] for t in TEN_CATEGORY_MAP} | {"schema_family"}
ANNOTATION_TOOLS = ("admission", "feature_coding", "alignment")


class TestBuiltinTenCategories:
    def test_all_registered(self):
        assert {t.id for t in list_tools()} == EXPECTED_TOOL_IDS

    @pytest.mark.parametrize(
        "tool_id,stage,mod_name,func_name,ctx", TEN_CATEGORY_MAP)
    def test_contract_and_run_delegate(self, tool_id, stage, mod_name,
                                       func_name, ctx, monkeypatch):
        tool = get_tool(tool_id)
        assert tool is not None
        assert tool.stage == stage
        assert tool.version
        assert tool.permission in {"viewer", "annotator", "reviewer", "editor"}
        assert tool.deps and all(isinstance(d, str) and d for d in tool.deps)
        assert isinstance(tool.params_schema, dict)

        captured = {}
        sentinel = object()
        target_mod = importlib.import_module(mod_name)

        def _delegate(**kwargs):
            captured["args"] = kwargs
            return sentinel

        monkeypatch.setattr(target_mod, func_name, _delegate)
        result = tool.run(dict(ctx))
        assert result is sentinel
        args = dict(captured["args"])
        if tool_id in ANNOTATION_TOOLS:
            # 三标注工具 run 以 task_type 固定委托（不得发明新语义）
            assert args.pop("task_type") == tool_id
            assert args["ai_assisted"] is True      # 未给参数补 schema 默认值
        # 通用契约：ctx 参数透传。参数面无 category 的查询工具（corpus_evidence
        # 按 verb、multimedia 按 anchor）按各自参数面断言——不发明 category 语义
        if tool_id == "corpus_evidence":
            assert args["verb"] == ctx["verb"] and args["limit"] == ctx["limit"]
        elif tool_id == "multimedia":
            assert args["anchor_type"] == ctx["anchor_type"]
            assert args["anchor_id"] == ctx["anchor_id"]
        else:
            assert args["category"] == ctx.get("category", args.get("category"))
        # 给出的参数透传
        for key, value in ctx.items():
            assert args[key] == value

    def test_required_param_missing_raises(self, monkeypatch):
        import src.annotation_flow as af
        monkeypatch.setattr(af, "submit_annotation", lambda **kw: True)
        with pytest.raises(RegistryError, match="payload"):
            get_tool("admission").run({"sense_id": 7, "coder_id": 1})

    def test_annotation_tools_fixed_task_types(self, monkeypatch):
        """三标注工具同一委托函数、task_type 各自固定（对照表口径）。"""
        import src.annotation_flow as af
        seen = []
        monkeypatch.setattr(
            af, "submit_annotation",
            lambda **kw: seen.append(kw["task_type"]) or True)
        for tool_id in ANNOTATION_TOOLS:
            get_tool(tool_id).run({"sense_id": 1, "coder_id": 1,
                                   "payload": {"admission": "Y"}})
        assert seen == ["admission", "feature_coding", "alignment"]

    def test_render_left_for_stage2(self):
        for tool_id in EXPECTED_TOOL_IDS:
            with pytest.raises(NotImplementedError):
                get_tool(tool_id).render({})

    def test_check_deps_green_without_probes(self):
        """无探针登记时依赖自检全绿（批次 2 登记探针后强校验）。"""
        for tool_id in EXPECTED_TOOL_IDS:
            assert get_tool(tool_id).check_deps() == []


# ============================================
# 7. pack 自检三态（引用 ⊆ 注册表 ＋ 启用态）
# ============================================

class TestPackSelfcheck:
    def _write_pack(self, root, category, content):
        pack_dir = root / "configs" / category
        pack_dir.mkdir(parents=True, exist_ok=True)
        (pack_dir / "pack.yaml").write_text(content, encoding="utf-8")
        return str(root)

    def test_no_tools_key_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
        self._write_pack(tmp_path, "motion", "category: motion\nversion: 1\n")
        report = pack_check.pack_selfcheck("motion")
        assert report["ok"] is True
        assert report["refs"] == []
        assert report["note"] == "无工具引用，通过"
        assert report["problems"] == [] and report["warnings"] == []

    def test_registered_but_disabled_warns(self, tmp_path, monkeypatch):
        """已注册未启用 → ok 不降（§4 五步顺序 selfcheck 绿先于点亮）但警示。"""
        monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
        self._write_pack(tmp_path, "motion",
                         "category: motion\nversion: 1\ntools:\n"
                         "  - typicality\n")
        report = pack_check.pack_selfcheck("motion")
        assert report["ok"] is True
        assert report["refs"] == ["typicality"]
        assert len(report["warnings"]) == 1
        assert "未启用" in report["warnings"][0]
        assert report["problems"] == []

    def test_unregistered_reference_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
        self._write_pack(
            tmp_path, "motion",
            "category: motion\nversion: 1\ntools:\n"
            "  - typicality\n  - ghost\n")
        report = pack_check.pack_selfcheck("motion")
        assert report["ok"] is False
        assert any("未注册" in p and "ghost" in p for p in report["problems"])

    def test_mapping_form_and_illegal_form(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
        self._write_pack(
            tmp_path, "motion",
            "category: motion\nversion: 1\ntools:\n"
            "  - id: typicality\n    params: {k: 1}\n"
            "  - 42\n")
        report = pack_check.pack_selfcheck("motion")
        assert report["refs"] == ["typicality"]          # 映射形态取 id 键
        assert any("无法解析" in p for p in report["problems"])
        assert report["ok"] is False

    def test_tools_not_a_list_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
        self._write_pack(tmp_path, "motion",
                         "category: motion\nversion: 1\ntools: typicality\n")
        report = pack_check.pack_selfcheck("motion")
        assert report["ok"] is False
        assert any("必须是列表" in p for p in report["problems"])

    def test_missing_pack_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
        report = pack_check.pack_selfcheck("no_such_cat")
        assert report["ok"] is False
        assert any("缺失 pack.yaml" in p for p in report["problems"])

    def test_real_motion_pack_has_no_tool_refs(self):
        """真实范畴包现状：motion 未声明 tools → 无引用通过（三态之一）。"""
        report = pack_check.pack_selfcheck("motion")
        assert report["ok"] is True
        assert report["note"] == "无工具引用，通过"

    def test_template_pack_yaml_still_parses_with_tools_comment(self):
        """configs/_template/pack.yaml 追加注释样例后仍可解析（无引用通过）。"""
        report = pack_check.pack_selfcheck("_template")
        assert report["refs"] == []
        assert report["note"] == "无工具引用，通过"

    @pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过集成")
    def test_enabled_ref_no_warning_when_loader_sees_enabled(
            self, tmp_path, monkeypatch, fx18_env):
        """启用态校验接 DB 位：loader 绑定后 enabled=1 的引用不警示。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        tsd.enabled_set("motion", "typicality", actor=DICT_ADMIN)
        tsd.bind_registry_loader(True)
        try:
            monkeypatch.setattr(pack_check, "_REPO_ROOT", str(tmp_path))
            self._write_pack(
                tmp_path, "motion",
                "category: motion\nversion: 1\ntools:\n  - typicality\n")
            report = pack_check.pack_selfcheck("motion")
            assert report["ok"] is True
            assert report["warnings"] == []
        finally:
            set_db_enabled_loader(None)


# ============================================
# 8. 范畴与工具页（AppTest 无头渲染）
# ============================================

PAGE_SCRIPT = (
    "import sys\n"
    f"sys.path.insert(0, {PROJECT_ROOT!r})\n"
    "from src.categories_tools_page import render_categories_tools_page\n"
    "render_categories_tools_page()\n"
)

_PAGE_USER_SYS = {"id": 2, "username": "sys_a", "display_name": "平台管理员",
                  "role": "viewer", "roles": ["sys_admin"]}
_PAGE_USER_DICT = {"id": 3, "username": "dict_a", "display_name": "词典管理员",
                   "role": "viewer", "roles": ["dict_admin"]}


def _run_page(user: dict = None) -> AppTest:
    at = AppTest.from_string(PAGE_SCRIPT, default_timeout=60)
    if user is not None:
        at.session_state["user"] = user
    at.run()
    return at


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过页面渲染测试")
class TestCategoriesToolsPage:
    def test_unauthenticated_blocked(self, fx18_env):
        at = _run_page(None)
        assert not at.exception
        assert any("请先登录" in w.value for w in at.warning)

    def test_viewer_rejected(self, fx18_env):
        at = _run_page({"id": 9, "username": "vw", "display_name": "只读",
                        "role": "viewer", "roles": ["viewer"]})
        assert not at.exception
        assert any("仅管理员可用" in e.value for e in at.error)

    def test_sys_admin_sees_available_zone(self, fx18_env):
        """平台管理员：available 区可操作（无占位说明）、enabled 区只读说明。"""
        at = _run_page(_PAGE_USER_SYS)
        assert not at.exception
        texts = " ".join(m.value for m in at.markdown)
        assert "available 区" in texts
        assert "enabled 区" in texts
        assert not any("available 位仅平台管理员可操作" in i.value
                       for i in at.info)
        assert any("enabled 位仅词典管理员可操作" in i.value for i in at.info)
        # available 区 11 个开关 + 功能模块 3 个可勾选（d/p/a——c/u 锁定
        # 禁用态 checkbox 亦渲染，共 5 个；批次 30 五构件插件化）
        assert len(at.checkbox) == len(list_tools()) + 5
        avail_boxes = [c for c in at.checkbox if c.label == "available"]
        assert len(avail_boxes) == len(list_tools())
        assert all(not c.disabled for c in avail_boxes)

    def test_dict_admin_sees_enabled_zone_locked_until_available(self, fx18_env):
        """词典管理员：enabled 区渲染，未 available 的工具开关禁用（两步激活）。"""
        tsd.ensure_tool_settings_tables()
        tsd.available_set("motion", "typicality", actor=SYS_ADMIN)
        at = _run_page(_PAGE_USER_DICT)
        assert not at.exception
        assert any("available 位仅平台管理员可操作" in i.value for i in at.info)
        assert not any("enabled 位仅词典管理员可操作" in i.value
                       for i in at.info)
        enab_boxes = [c for c in at.checkbox if c.label == "enabled"]
        assert len(enab_boxes) == len(list_tools())
        by_disabled = {c.disabled for c in enab_boxes}
        assert True in by_disabled and False in by_disabled  # available 的可开

    def test_sys_admin_available_toggle_persists_and_audits(self, fx18_env):
        """开关即写：available 开勾 → 写库 + 审计行（who=页面会话用户）。

        RV25-3 形态适配：写回已改 on_change 回调触发（真用户动作才写库）
        —— AppTest 的 check() 改变 widget 值后 run() 即触发回调。
        """
        tsd.ensure_tool_settings_tables()
        at = _run_page(_PAGE_USER_SYS)
        assert not at.exception
        target = next(c for c in at.checkbox
                      if c.label == "available" and not c.value)
        first_tool_id = sorted(t.id for t in list_tools())[0]
        target.check().run()   # 勾选置位 → on_change 回调写库（RV25-3）
        assert not at.exception
        rows = tsd.list_settings()
        assert len(rows) == 1
        assert rows[0]["tool_id"] == first_tool_id
        assert rows[0]["available"] == 1 and rows[0]["enabled"] == 0
        audit = tsd.list_audit()
        assert any(r["action"] == "available_set"
                   and r["actor_username"] == "sys_a"
                   and r["tool_id"] == first_tool_id for r in audit)
