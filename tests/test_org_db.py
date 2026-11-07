"""词典项目与项目成员模块测试（src/org_db.py）。

两层结构，与 tests/test_users_db.py 既有约定一致：

  * 纯函数（_normalize_categories / _parse_categories）不碰数据库 —— 本地与 CI 全跑；
  * 数据层 CRUD（ensure_org_tables / create_project / add_member / remove_member /
    list_projects / get_projects_for_user / get_members / project_selfcheck）
    依赖真实 MySQL —— 同一约定：连不上或账号无建库权限就 skip
    （类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_users_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，
跑完 DROP。库名与 test_users_db / test_integration_apptest /
test_security_hardening 共用 —— 本地账号通常只对既有测试库名有授权
（SHOW GRANTS 可查），复用同名的既成约定；若环境后续为 org 专库
（如 web_word_org_test）补授权，改 TEST_DB 一行即可。
org 两表外键指向 users，fixture 里 ensure_org_tables 会先
拉起 users_db.ensure_user_tables（幂等）。

remove_member 的「在途任务检查」依赖 assignments 表（annotation_flow.py
所建）—— 在途用例按其 DDL 原样建最小 assignments 表验证拒绝路径，
再用 DROP TABLE 验证占位降级路径（表不存在视为无在途任务）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.org_db import (  # noqa: E402
    _normalize_categories,
    _parse_categories,
    add_member,
    create_project,
    ensure_org_tables,
    get_members,
    get_projects_for_user,
    list_projects,
    project_selfcheck,
    remove_member,
)
from src.users_db import create_user, set_active  # noqa: E402

TEST_DB = "web_word_org_test"  # 与 users 系测试共用（授权覆盖；见模块 docstring）


# ============================================
# 纯函数：categories 规整（无数据库）
# ============================================

class TestCategoriesNormalizing:
    """_normalize_categories / _parse_categories 往返与脏数据容错。"""

    def test_list_roundtrip(self):
        """list → JSON 串 → list 往返保序。"""
        stored = _normalize_categories(["motion", "通信", " RUN "])
        assert _parse_categories(stored) == ["motion", "通信", "RUN"]

    def test_str_becomes_single_item_list(self):
        """单个范畴字符串 → 单元素清单。"""
        assert _parse_categories(_normalize_categories("motion")) == ["motion"]

    def test_json_string_passthrough(self):
        """已是 JSON 数组串 → 解析后入库（不二次包裹）。"""
        stored = _normalize_categories('["a","b"]')
        assert _parse_categories(stored) == ["a", "b"]

    def test_empty_and_none(self):
        """None / 空串 / 空清单 → None（未划范畴 ≠ 空集）。"""
        assert _normalize_categories(None) is None
        assert _normalize_categories("") is None
        assert _normalize_categories([]) is None
        assert _parse_categories(None) == []

    def test_dirty_json_fallback(self):
        """坏 JSON 串按普通字符串入库，读侧容错返回清单。"""
        stored = _normalize_categories("[不是JSON")
        assert _parse_categories(stored) == ["[不是JSON"]


# ============================================
# 集成测试：真实 MySQL（无环境则整类 skip）
# ============================================

def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不建库）。"""
    try:
        import pymysql
        from pymysql.cursors import DictCursor

        conn = pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=DictCursor,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()

# annotation_flow.py 的 assignments 建表 DDL（在途任务检查所依赖的表，
# 这里按原结构建最小版本验证 remove_member 的拒绝路径）。
ASSIGNMENTS_TABLE_SQL = """CREATE TABLE assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  assignee_id INT NOT NULL,
  category VARCHAR(40) NOT NULL DEFAULT 'motion',
  task_type ENUM('admission','feature_coding','alignment') NOT NULL DEFAULT 'admission',
  status ENUM('open','in_progress','submitted','closed') NOT NULL DEFAULT 'open',
  assigned_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_orgtest_assign_user FOREIGN KEY (assignee_id) REFERENCES users(id),
  CONSTRAINT fk_orgtest_assign_admin FOREIGN KEY (assigned_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 org 数据层集成测试")
class TestOrgDbIntegration:
    """项目壳 + 成员册 CRUD + 自检（跑在独立测试库 web_word_org_test）。"""

    @pytest.fixture
    def org_env(self, monkeypatch):
        """
        建空测试库（含 users / user_roles / org 两表），测试结束 DROP。

        与 test_users_db.users_db 同一手法：get_db_cursor 在调用时读
        mysql_db 模块全局，monkeypatch MYSQL_DATABASE 即可，连接池按键
        含 db 名，互不污染。账号无建库权限则 skip（环境能力问题）。
        """
        import pymysql

        conn = pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 org 集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_org_tables()  # 内部先 ensure_user_tables（FK 依赖 users）
        yield
        # 还原全局再删库：避免池中归还路径引用已删的库
        conn = pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()

    # --- ensure 幂等 ---

    def test_ensure_org_tables_idempotent(self, org_env):
        """ensure 重复调用不炸不重复（CREATE TABLE IF NOT EXISTS）。"""
        ensure_org_tables()
        ensure_org_tables()
        assert create_project("幂等项目", 1, ["motion"]) is not None

    # --- create_project ---

    def test_create_project_chief_enrolled(self, org_env):
        """建项目即册封首位 chief：成员册出现 chief 行，列表可见。"""
        chief = create_user("chief1", "pw123456", "主编甲", "viewer")
        pid = create_project("现代汉语动词语义词典", chief, ["motion"],
                             "阶段一试点范畴")
        assert isinstance(pid, int) and pid > 0
        members = get_members(pid)
        assert len(members) == 1
        assert members[0]["user_id"] == chief
        assert members[0]["project_role"] == "chief"
        assert members[0]["username"] == "chief1"
        projects = list_projects()
        assert len(projects) == 1
        assert projects[0]["name"] == "现代汉语动词语义词典"
        assert projects[0]["categories"] == ["motion"]
        assert projects[0]["member_count"] == 1
        assert projects[0]["created_by"] == chief

    def test_create_project_validation(self, org_env):
        """空名 / 重复名 / chief 不存在 → None。"""
        chief = create_user("chief2", "pw123456", "主编乙", "viewer")
        assert create_project("", chief, None) is None
        assert create_project("   ", chief, None) is None
        assert create_project("合法项目", 999999, None) is None  # FK 无此用户
        pid = create_project("唯一名项目", chief, None)
        assert pid is not None
        assert create_project("唯一名项目", chief, None) is None  # UNIQUE 重名
        # 名字两翼空白被规整
        pid2 = create_project("  空白项目  ", chief, None)
        assert pid2 is not None
        names = {p["name"] for p in list_projects()}
        assert "空白项目" in names and "  空白项目  " not in names

    def test_create_project_categories_variants(self, org_env):
        """categories 接受 list / str / None，读侧统一为 list。"""
        chief = create_user("chief3", "pw123456", "主编丙", "viewer")
        assert create_project("项目A", chief, "motion") is not None
        assert create_project("项目B", chief, ["motion", "posture"]) is not None
        assert create_project("项目C", chief, None) is not None
        by_name = {p["name"]: p for p in list_projects()}
        assert by_name["项目A"]["categories"] == ["motion"]
        assert by_name["项目B"]["categories"] == ["motion", "posture"]
        assert by_name["项目C"]["categories"] == []

    # --- add_member / get_members ---

    def test_add_member_roles_and_upsert(self, org_env):
        """入册各职能；重入同职能 False；改授职能 True 且生效。"""
        chief = create_user("chief4", "pw123456", "主编丁", "viewer")
        reviewer = create_user("rev4", "pw123456", "审校丁", "viewer")
        editor = create_user("ed4", "pw123456", "撰写丁", "viewer")
        pid = create_project("成员管理项目", chief, ["motion"])
        assert add_member(pid, reviewer, "reviewer", granted_by=chief) is True
        assert add_member(pid, editor, "annotator", granted_by=chief) is True
        # 改授职能（annotator → editor）：upsert 生效
        assert add_member(pid, editor, "editor", granted_by=chief) is True
        # 重复授予当前职能：无实际变更 → False
        assert add_member(pid, editor, "editor", granted_by=chief) is False
        roles = {m["user_id"]: m["project_role"] for m in get_members(pid)}
        assert roles == {chief: "chief", reviewer: "reviewer", editor: "editor"}

    def test_add_member_validation(self, org_env):
        """非法职能 / 项目或用户不存在 / granted_by 非法 → False。"""
        chief = create_user("chief5", "pw123456", "主编戊", "viewer")
        pid = create_project("校验项目", chief, None)
        outsider = create_user("out5", "pw123456", "编外", "viewer")
        assert add_member(pid, outsider, "boss", granted_by=chief) is False
        assert add_member(pid, outsider, "", granted_by=chief) is False
        assert add_member(999999, outsider, "viewer", granted_by=chief) is False
        assert add_member(pid, 999999, "viewer", granted_by=chief) is False
        assert add_member(pid, outsider, "viewer", granted_by=999999) is False
        assert get_members(pid) == get_members(pid)  # 读侧稳定
        assert len(get_members(pid)) == 1  # 非法入册未写库

    def test_multi_chief_allowed(self, org_env):
        """多主项目：可以册封第二位 chief（§8 单点缓解 ≥2 名词典管理员）。"""
        chief = create_user("chief6", "pw123456", "主编己", "viewer")
        co_chief = create_user("chief6b", "pw123456", "联合主编", "viewer")
        pid = create_project("双主项目", chief, None)
        assert add_member(pid, co_chief, "chief", granted_by=chief) is True
        chiefs = [m for m in get_members(pid) if m["project_role"] == "chief"]
        assert len(chiefs) == 2
        ok, problems = project_selfcheck(pid)
        assert ok and problems == []

    # --- remove_member ---

    def test_remove_chief_forbidden(self, org_env):
        """chief 不可被 remove_member 移除（含多主项目里的每一位 chief）。"""
        chief = create_user("chief7", "pw123456", "主编庚", "viewer")
        co_chief = create_user("chief7b", "pw123456", "联合主编庚", "viewer")
        pid = create_project("不可摘主项目", chief, None)
        add_member(pid, co_chief, "chief", granted_by=chief)
        assert remove_member(pid, chief) is False
        assert remove_member(pid, co_chief) is False
        assert len(get_members(pid)) == 2  # 无人被移除

    def test_remove_member_success_and_absent(self, org_env):
        """普通成员可移除；非成员移除 False；移除后可重新入册。"""
        chief = create_user("chief8", "pw123456", "主编辛", "viewer")
        worker = create_user("worker8", "pw123456", "成员辛", "viewer")
        pid = create_project("移除项目", chief, None)
        assert add_member(pid, worker, "annotator", granted_by=chief) is True
        assert remove_member(pid, worker) is True
        assert remove_member(pid, worker) is False  # 已不在册
        assert [m["user_id"] for m in get_members(pid)] == [chief]
        assert add_member(pid, worker, "viewer", granted_by=chief) is True  # 可重入

    def test_remove_member_with_in_flight_assignment(self, org_env):
        """在途任务占位检查：open/in_progress 拒绝，closed 放行，缺表降级放行。"""
        from src.mysql_db import get_db_cursor

        chief = create_user("chief9", "pw123456", "主编壬", "viewer")
        worker = create_user("worker9", "pw123456", "成员壬", "viewer")
        pid = create_project("在途项目", chief, None)
        add_member(pid, worker, "annotator", granted_by=chief)
        # 按 annotation_flow 的 DDL 建 assignments（org 模块自身不建它）
        with get_db_cursor() as cursor:
            cursor.execute(ASSIGNMENTS_TABLE_SQL)
            cursor.execute(
                "INSERT INTO assignments (assignee_id, category, task_type, assigned_by) "
                "VALUES (%s, 'motion', 'admission', %s)",
                (worker, chief),
            )
        # 在途（open）→ 拒绝移除
        assert remove_member(pid, worker) is False
        assert len(get_members(pid)) == 2
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE assignments SET status = 'closed' WHERE assignee_id = %s",
                (worker,),
            )
        # 任务已闭环 → 放行
        assert remove_member(pid, worker) is True
        # 占位降级：assignments 表不存在 → 视为无在途任务
        with get_db_cursor() as cursor:
            add_member(pid, worker, "viewer", granted_by=chief)
            cursor.execute("DROP TABLE assignments")
        assert remove_member(pid, worker) is True

    # --- get_projects_for_user ---

    def test_get_projects_for_user(self, org_env):
        """成员看到自己入册的项目与职能；非成员为空。"""
        chief = create_user("chief10", "pw123456", "主编癸", "viewer")
        member = create_user("member10", "pw123456", "成员癸", "viewer")
        outsider = create_user("out10", "pw123456", "路人癸", "viewer")
        p1 = create_project("甲项目", chief, ["motion"])
        p2 = create_project("乙项目", chief, None)
        add_member(p2, member, "editor", granted_by=chief)
        mine = get_projects_for_user(member)
        assert [p["id"] for p in mine] == [p2]
        assert mine[0]["project_role"] == "editor"
        assert mine[0]["name"] == "乙项目"
        chief_projects = get_projects_for_user(chief)
        assert [p["id"] for p in chief_projects] == [p1, p2]
        assert all(p["project_role"] == "chief" for p in chief_projects)
        assert get_projects_for_user(outsider) == []
        assert get_projects_for_user(999999) == []

    # --- project_selfcheck ---

    def test_selfcheck_healthy(self, org_env):
        """健康项目：chief 在册且在用 → (True, [])。"""
        chief = create_user("chief11", "pw123456", "主编子", "viewer")
        pid = create_project("健康项目", chief, None)
        assert project_selfcheck(pid) == (True, [])
        assert project_selfcheck(999999)[0] is False  # 项目不存在
        assert "项目不存在" in project_selfcheck(999999)[1]

    def test_selfcheck_missing_chief(self, org_env):
        """chief 行被绕过接口删除（模拟脏数据）→ 自检报警「无主编」。"""
        from src.mysql_db import get_db_cursor

        chief = create_user("chief12", "pw123456", "主编丑", "viewer")
        pid = create_project("失主项目", chief, None)
        with get_db_cursor() as cursor:
            cursor.execute(
                "DELETE FROM project_members WHERE project_id = %s "
                "AND project_role = 'chief'",
                (pid,),
            )
        ok, problems = project_selfcheck(pid)
        assert ok is False
        assert any("chief" in p for p in problems)

    def test_selfcheck_inactive_chief(self, org_env):
        """chief 账号被停用 → 自检报警；恢复后转绿。"""
        chief = create_user("chief13", "pw123456", "主编寅", "viewer")
        pid = create_project("停主编项目", chief, None)
        assert set_active(chief, False) is True
        ok, problems = project_selfcheck(pid)
        assert ok is False
        assert any("停用" in p for p in problems)
        assert set_active(chief, True) is True
        assert project_selfcheck(pid) == (True, [])
