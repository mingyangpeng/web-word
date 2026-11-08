"""用户与权限模块测试（src/users_db.py）。

两层结构，与 tests/ 既有约定一致：

  * 纯函数（hash_password / verify_password）不碰数据库 —— 本地与 CI 全跑；
  * 数据层 CRUD（ensure_user_tables / verify_login / create_user / list_users /
    set_role / set_active）依赖真实 MySQL —— 与 test_migration_integration.py
    同一约定：连不上或账号无建库权限就 skip（类级 skipif + fixture 内 skip），
    CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_users_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，
跑完 DROP。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
import src.users_db as users_db_module  # noqa: E402  （RV4-5 monkeypatch 用）
from src.users_db import (  # noqa: E402
    NEW_ROLES,
    PBKDF2_ITERATIONS,
    ROLES,
    _sort_roles_by_priority,
    change_password,
    create_user,
    ensure_user_tables,
    grant_role,
    has_role,
    hash_password,
    list_roles,
    list_users,
    needs_password_change,
    revoke_role,
    set_active,
    set_role,
    verify_login,
    verify_login_full,
    verify_password,
)

TEST_DB = "web_word_users_test"


# ============================================
# 纯函数：密码哈希（规范 §6-2）
# ============================================

class TestPasswordHashing:
    """hash_password / verify_password 往返与拒绝路径（无数据库）。"""

    def test_roundtrip(self):
        """正确密码通过校验。"""
        stored = hash_password("s3cret-跑 vividly")
        assert verify_password("s3cret-跑 vividly", stored) is True

    def test_wrong_password_rejected(self):
        """错误密码拒绝。"""
        stored = hash_password("correct-horse")
        assert verify_password("wrong-battery", stored) is False

    def test_hash_format(self):
        """存储格式 pbkdf2_sha256$iterations$salt_hex$hash_hex（规范 §2 注释）。"""
        stored = hash_password("whatever")
        parts = stored.split("$")
        assert len(parts) == 4
        algo, iterations, salt_hex, hash_hex = parts
        assert algo == "pbkdf2_sha256"
        assert int(iterations) >= 120000  # 规范 §6-2 下限
        assert len(salt_hex) == 32  # token_hex(16)
        assert len(hash_hex) == 64  # sha256 hex
        int(salt_hex, 16)  # 盐是合法十六进制
        int(hash_hex, 16)

    def test_iterations_meet_spec(self):
        """迭代次数 ≥120000（规范 §6-2）。"""
        assert PBKDF2_ITERATIONS >= 120000

    def test_unique_salt_per_hash(self):
        """同一明文两次哈希不同（每用户随机盐），但都能通过校验。"""
        h1 = hash_password("same-plain")
        h2 = hash_password("same-plain")
        assert h1 != h2
        assert verify_password("same-plain", h1)
        assert verify_password("same-plain", h2)

    def test_unicode_password(self):
        """中文/emoji 口令往返。"""
        stored = hash_password("管理员🙂123")
        assert verify_password("管理员🙂123", stored)
        assert not verify_password("管理员🙂12", stored)

    def test_malformed_stored_rejected(self):
        """存储串脏数据一律 False，不抛异常（脏数据不能打崩登录页）。"""
        good = hash_password("pw")
        bad_stored = [
            "",
            "not-a-hash",
            "md5$150000$ab$cd",            # 算法不对
            "pbkdf2_sha256$abc$ab$cd",     # 迭代数非数字
            "pbkdf2_sha256$150000$zz$cd",  # 盐非十六进制
            "pbkdf2_sha256$150000$ab$zz",  # 哈希非十六进制
            "pbkdf2_sha256$150000$ab",     # 缺字段
        ]
        for stored in bad_stored:
            assert verify_password("pw", stored) is False, f"应拒绝: {stored!r}"
        assert verify_password("pw", None) is False  # type: ignore[arg-type]
        # 篡改一位哈希 → 失败
        tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
        assert verify_password("pw", tampered) is False


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


@pytest.fixture
def users_db(monkeypatch):
    """
    建空测试库并让 users 模块指向它，测试结束 DROP。

    与 test_migration_integration.v1_database 相同的手法：
    get_db_cursor / _new_connection 在调用时读 mysql_db 模块全局，
    monkeypatch MYSQL_DATABASE 即可，连接池按键含 db 名，互不污染。
    账号无建库权限（生产账号常见）则 skip —— 环境能力问题，不是代码缺陷。
    （模块级 fixture：TestUsersDbIntegration 与 TestMultiRoles 共用。）
    """
    import pymysql

    conn = None
    try:
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
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    except pymysql.err.OperationalError as e:
        # connect 失败（无库环境）与建库被拒（无权限）同口径 skip —— 与
        # test_r1_fixes.r1_env / test_integration_apptest.r3_env 一致
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 users 集成测试: {e}")
    finally:
        if conn is not None:
            conn.close()

    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 users 数据层集成测试")
class TestUsersDbIntegration:
    """数据层 CRUD + 内置默认 admin（跑在独立测试库 web_word_users_test）。"""

    # --- 内置默认管理员 ---

    def test_default_admin_bootstrapped(self, users_db):
        """users 空表 ensure 后出现内置 admin/admin123（display_name=内置管理员）。"""
        ensure_user_tables()
        login = verify_login("admin", "admin123")
        assert login is not None
        assert login["username"] == "admin"
        assert login["display_name"] == "内置管理员"
        assert login["role"] == "admin"
        # 会话用户信息不含密码哈希
        assert "password_hash" not in login
        assert set(login.keys()) == {"id", "username", "display_name", "role"}

    def test_ensure_idempotent(self, users_db):
        """ensure 重复调用不重复建 admin（幂等）。"""
        ensure_user_tables()
        ensure_user_tables()
        ensure_user_tables()
        admins = [u for u in list_users() if u["username"] == "admin"]
        assert len(admins) == 1

    def test_ensure_keeps_existing_users(self, users_db):
        """表非空时 ensure 不再插 admin。"""
        ensure_user_tables()
        assert create_user("first", "pw123456", "第一个", "annotator") is not None
        ensure_user_tables()
        usernames = {u["username"] for u in list_users()}
        assert usernames == {"admin", "first"}

    # --- create + login 往返 ---

    def test_create_and_login(self, users_db):
        """create_user 后 verify_login 成功，返回规范字段。"""
        ensure_user_tables()
        uid = create_user("alice", "pw123456", "爱丽丝", "annotator")
        assert isinstance(uid, int) and uid > 0
        login = verify_login("alice", "pw123456")
        assert login is not None
        assert login == {"id": uid, "username": "alice", "display_name": "爱丽丝", "role": "annotator"}

    def test_login_wrong_password(self, users_db):
        """create 后错密码拒绝。"""
        ensure_user_tables()
        create_user("bob", "right-pass", "鲍勃", "viewer")
        assert verify_login("bob", "wrong-pass") is None

    def test_login_unknown_user(self, users_db):
        """不存在的用户返回 None。"""
        ensure_user_tables()
        assert verify_login("nobody", "whatever") is None

    def test_duplicate_username_rejected(self, users_db):
        """用户名 UNIQUE：重复创建返回 None，原用户不受影响。"""
        ensure_user_tables()
        uid = create_user("carol", "pw123456", "卡罗尔", "reviewer")
        assert uid is not None
        assert create_user("carol", "other-pass", "假卡罗尔", "viewer") is None
        login = verify_login("carol", "pw123456")
        assert login is not None and login["display_name"] == "卡罗尔"

    def test_invalid_role_rejected(self, users_db):
        """角色枚举非法值在应用层被拒：不进数据库、返回 None/False。"""
        ensure_user_tables()
        uid = create_user("dave", "pw123456", "戴夫", "annotator")
        assert uid is not None
        # create_user 非法角色
        assert create_user("eve", "pw123456", "伊芙", "superadmin") is None
        assert create_user("eve", "pw123456", "伊芙", "root") is None
        # set_role 非法角色
        assert set_role(uid, "hacker") is False
        # 库里没有非法角色行
        roles = {u["role"] for u in list_users()}
        assert roles <= set(ROLES)

    # --- 角色与状态管理 ---

    def test_set_role(self, users_db):
        """set_role 生效：改后登录信息与列表都反映新角色。"""
        ensure_user_tables()
        uid = create_user("erin", "pw123456", "艾琳", "viewer")
        assert set_role(uid, "reviewer") is True
        login = verify_login("erin", "pw123456")
        assert login is not None and login["role"] == "reviewer"
        users = {u["id"]: u for u in list_users()}
        assert users[uid]["role"] == "reviewer"

    def test_set_role_nonexistent_user(self, users_db):
        """set_role 到不存在的用户返回 False。"""
        ensure_user_tables()
        assert set_role(999999, "viewer") is False

    def test_set_active_disables_login(self, users_db):
        """停用后不能登录（active=1 才返回），启用后恢复。"""
        ensure_user_tables()
        uid = create_user("frank", "pw123456", "弗兰克", "annotator")
        assert verify_login("frank", "pw123456") is not None
        assert set_active(uid, False) is True
        assert verify_login("frank", "pw123456") is None  # 已停用不可登录
        users = {u["id"]: u for u in list_users()}
        assert int(users[uid]["active"]) == 0  # 记录仍在（外键引用不能断）
        assert set_active(uid, True) is True
        assert verify_login("frank", "pw123456") is not None

    def test_set_active_nonexistent_user(self, users_db):
        """set_active 到不存在的用户返回 False。"""
        ensure_user_tables()
        assert set_active(999999, False) is False

    # --- 安全不变量 ---

    def test_password_never_plaintext(self, users_db):
        """库中 password_hash 是 pbkdf2 格式，明文绝不出现在存储串里。"""
        from src.mysql_db import get_db_cursor

        ensure_user_tables()
        plain = "pw123456-机密"
        create_user("gina", plain, "吉娜", "viewer")
        with get_db_cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE username = %s", ("gina",))
            row = cursor.fetchone()
        stored = row["password_hash"]
        assert stored.startswith("pbkdf2_sha256$")
        assert plain not in stored

    def test_list_users_excludes_hash(self, users_db):
        """list_users 不返回 password_hash（哈希不出数据层）。"""
        ensure_user_tables()
        create_user("henry", "pw123456", "亨利", "annotator")
        for u in list_users():
            assert "password_hash" not in u

    def test_create_user_requires_credentials(self, users_db):
        """空用户名 / 空密码拒绝创建。"""
        ensure_user_tables()
        assert create_user("", "pw123456", "无名", "viewer") is None
        assert create_user("ghost", "", "空口令", "viewer") is None


# ============================================
# 纯函数：六角色优先级排序（无数据库）
# ============================================

class TestRolePriority:
    """_sort_roles_by_priority：优先级降序 + 去重（无数据库）。"""

    def test_priority_order(self):
        """按 dict_admin > sys_admin > reviewer > editor > annotator > viewer 排列。"""
        mixed = ["viewer", "dict_admin", "annotator", "reviewer", "editor", "sys_admin"]
        assert _sort_roles_by_priority(mixed) == list(NEW_ROLES)

    def test_dedup_and_partial(self):
        """去重；部分角色也按相对优先级排。"""
        assert _sort_roles_by_priority(["editor", "dict_admin", "editor"]) == [
            "dict_admin", "editor",
        ]
        assert _sort_roles_by_priority(["viewer", "sys_admin"]) == ["sys_admin", "viewer"]

    def test_unknown_role_last(self):
        """未知角色（防御）排最后，不挤掉合法角色的相对顺序。"""
        assert _sort_roles_by_priority(["mystery", "viewer", "dict_admin"]) == [
            "dict_admin", "viewer", "mystery",
        ]


# ============================================
# 集成测试：v5.1 六角色多角色 + must_change_password（真实 MySQL）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过多角色集成测试")
class TestMultiRoles:
    """user_roles 多角色 API + 内置 admin 双角色迁移 + 改密标志（共用 users_db fixture）。"""

    def _admin_id(self) -> int:
        login = verify_login("admin", "admin123")
        assert login is not None, "内置 admin 未就位"
        return int(login["id"])

    # --- 内置 admin 双角色迁移 ---

    def test_default_admin_dual_roles(self, users_db):
        """内置 admin 迁移为 dict_admin+sys_admin 双角色（按优先级排序）。"""
        ensure_user_tables()
        roles = list_roles(self._admin_id())
        assert roles == ["dict_admin", "sys_admin"]
        assert has_role(self._admin_id(), "dict_admin")
        assert has_role(self._admin_id(), "sys_admin")
        assert not has_role(self._admin_id(), "reviewer")

    def test_admin_roles_migration_idempotent(self, users_db):
        """ensure 重复调用不重复迁移（UNIQUE + INSERT IGNORE，角色不叠加）。"""
        ensure_user_tables()
        ensure_user_tables()
        ensure_user_tables()
        assert list_roles(self._admin_id()) == ["dict_admin", "sys_admin"]

    def test_verify_login_full_roles(self, users_db):
        """verify_login_full：四键 + roles；verify_login 保持四键向后兼容。"""
        ensure_user_tables()
        full = verify_login_full("admin", "admin123")
        assert full is not None
        assert set(full.keys()) == {"id", "username", "display_name", "role", "roles"}
        assert full["roles"] == ["dict_admin", "sys_admin"]
        assert full["role"] == "admin"  # 旧 role 列快照不变（向后兼容）
        legacy = verify_login("admin", "admin123")
        assert set(legacy.keys()) == {"id", "username", "display_name", "role"}
        assert "roles" not in legacy

    # --- create_user 默认 viewer + must_change_password ---

    def test_create_user_defaults_viewer(self, users_db):
        """create_user 缺省角色 = viewer（六角色模型「新号默认 viewer」）。"""
        ensure_user_tables()
        uid = create_user("newbie", "pw123456", "新人")
        assert isinstance(uid, int) and uid > 0
        login = verify_login("newbie", "pw123456")
        assert login is not None and login["role"] == "viewer"
        assert list_roles(uid) == ["viewer"]
        users = {u["id"]: u for u in list_users()}
        assert users[uid]["role"] == "viewer"

    def test_create_user_maps_legacy_role_to_user_roles(self, users_db):
        """create_user 旧角色同步映射进 user_roles（admin→双角色，其余同名）。"""
        ensure_user_tables()
        uid_admin = create_user("boss2", "pw123456", "另一个管理员", "admin")
        assert uid_admin is not None
        assert list_roles(uid_admin) == ["dict_admin", "sys_admin"]
        uid_ann = create_user("worker", "pw123456", "标注工", "annotator")
        assert uid_ann is not None
        assert list_roles(uid_ann) == ["annotator"]

    def test_must_change_password_lifecycle(self, users_db):
        """建号 must_change_password=1；change_password 成功后清零。"""
        ensure_user_tables()
        uid = create_user("changer", "pw123456", "改密员", "viewer")
        assert needs_password_change(uid) is True
        assert needs_password_change(999999) is False  # 不存在 → False（不误报横幅）
        assert change_password(uid, "brand-new-pw") is True
        assert needs_password_change(uid) is False
        assert verify_login("changer", "brand-new-pw") is not None

    def test_builtin_admin_must_change_password(self, users_db):
        """内置 admin 建号即必须改密（默认口令是公开 bootstrap 凭据）。"""
        ensure_user_tables()
        assert needs_password_change(self._admin_id()) is True

    def test_must_change_password_column_migration(self, users_db):
        """存量表迁移：DROP 掉 must_change_password 后 ensure 幂等补列。"""
        from src.mysql_db import get_db_cursor

        ensure_user_tables()
        with get_db_cursor() as cursor:
            cursor.execute("ALTER TABLE users DROP COLUMN must_change_password")
        ensure_user_tables()  # 迁移应把列补回来
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'
                     AND COLUMN_NAME = 'must_change_password'"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 1

    # --- grant / revoke / has / list ---

    def test_grant_revoke_flow(self, users_db):
        """授予→列表（优先级序）→重复授予 False→撤销→再撤销 False。"""
        ensure_user_tables()
        uid = create_user("poly", "pw123456", "多角色", "viewer")
        assert grant_role(uid, "editor", granted_by=self._admin_id()) is True
        assert grant_role(uid, "reviewer", granted_by=self._admin_id()) is True
        # 多角色叠加：基线 viewer 保留；优先级降序 reviewer(2) > editor(3) > viewer(5)
        assert list_roles(uid) == ["reviewer", "editor", "viewer"]
        # 重复授予：无实际变更 → False
        assert grant_role(uid, "editor") is False
        assert list_roles(uid) == ["reviewer", "editor", "viewer"]
        # 撤销
        assert revoke_role(uid, "editor") is True
        assert list_roles(uid) == ["reviewer", "viewer"]
        assert revoke_role(uid, "editor") is False  # 未持有 → False
        assert revoke_role(uid, "dict_admin") is False

    def test_full_priority_order(self, users_db):
        """六个角色全授予时按 NEW_ROLES 优先级完整排序。"""
        ensure_user_tables()
        uid = create_user("allroles", "pw123456", "全家桶", "viewer")
        for role in ("annotator", "editor", "reviewer", "sys_admin", "dict_admin"):
            assert grant_role(uid, role) is True
        assert list_roles(uid) == list(NEW_ROLES)

    def test_grant_invalid_inputs(self, users_db):
        """非法角色 / 不存在用户：一律 False，不进数据库。"""
        ensure_user_tables()
        uid = create_user("valid", "pw123456", "合法", "viewer")
        assert grant_role(uid, "hacker") is False
        assert grant_role(uid, "superadmin") is False
        assert revoke_role(uid, "hacker") is False
        assert has_role(uid, "hacker") is False
        assert grant_role(999999, "editor") is False
        assert revoke_role(999999, "viewer") is False
        assert list_roles(999999) == []
        # 库里没有非法角色行
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM user_roles WHERE role NOT IN "
                "('dict_admin','sys_admin','reviewer','editor','annotator','viewer')"
            )
            assert int(cursor.fetchone()["n"] or 0) == 0

    def test_list_roles_fail_closed_for_inactive(self, users_db):
        """停用账号 fail-closed：list_roles=[] / has_role=False，启用后恢复。"""
        ensure_user_tables()
        uid = create_user("dormant", "pw123456", "休眠", "viewer")
        assert grant_role(uid, "editor") is True
        assert set_active(uid, False) is True
        assert list_roles(uid) == []
        assert has_role(uid, "editor") is False
        assert set_active(uid, True) is True
        assert list_roles(uid) == ["editor", "viewer"]  # 叠加的 editor + 基线 viewer

    def test_list_roles_legacy_fallback(self, users_db):
        """无 user_roles 行的存量账号按旧 role 列映射兜底（直插模拟存量）。"""
        from src.mysql_db import get_db_cursor

        ensure_user_tables()
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (username, password_hash, display_name, role, active) "
                "VALUES (%s, %s, %s, %s, 1)",
                ("legacy_rev", hash_password("pw123456"), "存量审核", "reviewer"),
            )
            cursor.execute(
                "INSERT INTO users (username, password_hash, display_name, role, active) "
                "VALUES (%s, %s, %s, %s, 1)",
                ("legacy_admin", hash_password("pw123456"), "存量管理", "admin"),
            )
        assert list_roles(verify_login("legacy_rev", "pw123456")["id"]) == ["reviewer"]
        assert list_roles(verify_login("legacy_admin", "pw123456")["id"]) == [
            "dict_admin", "sys_admin",
        ]

    def test_set_role_syncs_user_roles(self, users_db):
        """set_role 实际变更时重置 user_roles 为基线映射（防降级后残留提权）。"""
        ensure_user_tables()
        uid = create_user("demote", "pw123456", "待降级", "annotator")
        assert grant_role(uid, "dict_admin") is True  # 叠加高角色
        assert "dict_admin" in list_roles(uid)
        # 基线降到 viewer：dict_admin 叠加必须被清掉（否则旧页面降级形同虚设）
        assert set_role(uid, "viewer") is True
        assert list_roles(uid) == ["viewer"]
        # 目标值与现值相同（rowcount=0）：不动 user_roles，叠加角色不误清
        assert grant_role(uid, "editor") is True
        assert set_role(uid, "viewer") is False  # 未变更
        assert list_roles(uid) == ["editor", "viewer"]

    def test_user_roles_cascade_on_user_delete(self, users_db):
        """账号物理删除时 user_roles 行级联消失（e2e 清理路径不被 FK 阻断）。"""
        from src.mysql_db import get_db_cursor

        ensure_user_tables()
        uid = create_user("ghosted", "pw123456", "将被删除", "viewer")
        assert grant_role(uid, "editor") is True
        assert list_roles(uid) == ["editor", "viewer"]
        with get_db_cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (uid,))
        assert list_roles(uid) == []
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM user_roles WHERE user_id = %s", (uid,)
            )
            assert int(cursor.fetchone()["n"] or 0) == 0


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 actor 权限闸门集成测试")
class TestR1ActorGate:
    """R1-1 直调面（批次 12）：六敏感写函数 actor=None 缺省不变；低权 actor
    dict 抛 PermissionError（足色 = dict_admin/sys_admin；change_password
    本人放行）；非 dict 垃圾 fail-closed 同抛。

    权限异常发生在函数入口（try 之前），不落入既有 False/None 业务口径 ——
    页面层据 PermissionError 与 False 区分「越权」与「业务失败」。actor dict
    的足色判定是纯会话计算（effective_six_roles，不查库），故低权 actor 无需
    真实账号；created_by 例外 —— 它走 user_roles FK，须指向真实用户。
    """

    _LOW_ACTOR = {"id": 900, "username": "r1_annotator", "role": "viewer",
                  "roles": ["annotator", "viewer"]}
    _JUNK_ACTORS = ("admin", 42, ["dict_admin"], True)

    def _make_admin_actor(self):
        """造真实管理员账号并返回其会话形态 actor dict（created_by FK 需要）。"""
        uid = create_user("r1_chief", "pw123456", "词典管理员", "viewer")
        assert grant_role(uid, "dict_admin") is True
        return {"id": uid, "username": "r1_chief", "role": "viewer",
                "roles": ["dict_admin", "sys_admin"]}

    def test_grant_revoke_actor_gate(self, users_db):
        """R1 复现①：低权 grant_role/revoke_role 授/撤 dict_admin 直接拒绝。"""
        ensure_user_tables()
        victim = create_user("r1_victim", "pw123456", "受害者", "viewer")
        with pytest.raises(PermissionError, match="授予"):
            grant_role(victim, "dict_admin", granted_by=900, actor=self._LOW_ACTOR)
        with pytest.raises(PermissionError, match="撤销"):
            revoke_role(victim, "viewer", actor=self._LOW_ACTOR)
        # 未生效：库内无新增/删除痕迹
        assert list_roles(victim) == ["viewer"]
        # 管理面 actor 与系统作业（None）照常
        admin = self._make_admin_actor()
        assert grant_role(victim, "editor", actor=admin) is True
        assert revoke_role(victim, "editor", actor=admin) is True
        assert grant_role(victim, "reviewer") is True  # actor=None 系统作业
        # 垃圾 actor fail-closed
        for junk in self._JUNK_ACTORS:
            with pytest.raises(PermissionError):
                grant_role(victim, "editor", actor=junk)

    def test_set_role_actor_gate(self, users_db):
        """低权改基线角色拒绝；管理面/系统作业照常。"""
        ensure_user_tables()
        uid = create_user("r1_setrole", "pw123456", "改基线", "viewer")
        with pytest.raises(PermissionError, match="基线角色"):
            set_role(uid, "annotator", actor=self._LOW_ACTOR)
        assert list_roles(uid) == ["viewer"]
        admin = self._make_admin_actor()
        assert set_role(uid, "annotator", actor=admin) is True
        assert set_role(uid, "viewer") is True  # actor=None
        for junk in self._JUNK_ACTORS:
            with pytest.raises(PermissionError):
                set_role(uid, "viewer", actor=junk)

    def test_change_password_actor_gate(self, users_db):
        """R1 复现②：低权改他人口令＝账号接管 → 拒绝；本人自助/管理员重置放行。"""
        ensure_user_tables()
        uid = create_user("r1_pwuser", "pw123456", "改密目标", "viewer")
        attacker = create_user("r1_attacker", "pw123456", "低权人", "viewer")
        with pytest.raises(PermissionError, match="口令"):
            change_password(uid, "hijacked-pw-1", actor=self._LOW_ACTOR)
        with pytest.raises(PermissionError, match="口令"):
            change_password(uid, "hijacked-pw-1",
                            actor={"id": attacker, "username": "r1_attacker",
                                   "role": "viewer"})
        # 本人自助改密放行（旧口令立即失效）
        assert change_password(uid, "self-new-pw-1", actor={
            "id": uid, "username": "r1_pwuser", "role": "viewer",
        }) is True
        assert verify_login("r1_pwuser", "self-new-pw-1") is not None
        # 管理员重置放行（重置后原口令失效）
        admin = self._make_admin_actor()
        assert change_password(uid, "admin-reset-pw-1", actor=admin) is True
        assert verify_login("r1_pwuser", "self-new-pw-1") is None
        assert verify_login("r1_pwuser", "admin-reset-pw-1") is not None
        # 系统作业（None）照常；垃圾 actor 拒绝
        assert change_password(uid, "system-pw-123") is True
        for junk in self._JUNK_ACTORS:
            with pytest.raises(PermissionError):
                change_password(uid, "junk-pw-1234", actor=junk)

    def test_create_user_actor_gate(self, users_db):
        """低权建号拒绝；管理面/系统作业照常（created_by 与 actor 协同）。"""
        ensure_user_tables()
        with pytest.raises(PermissionError, match="创建用户"):
            create_user("r1_by_low", "pw123456", "低权建号", "viewer",
                        created_by=900, actor=self._LOW_ACTOR)
        admin = self._make_admin_actor()
        ok = create_user("r1_by_admin", "pw123456", "管理建号", "viewer",
                         created_by=admin["id"], actor=admin)
        assert isinstance(ok, int) and ok > 0
        # R3-5 留痕与 R1-1 闸门协同：granted_by/created_by 同取建号人
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT created_by FROM users WHERE id = %s", (ok,))
            assert int(cursor.fetchone()["created_by"]) == admin["id"]
        ok2 = create_user("r1_by_system", "pw123456", "系统建号", "viewer")
        assert isinstance(ok2, int) and ok2 > 0
        for junk in self._JUNK_ACTORS:
            with pytest.raises(PermissionError):
                create_user("r1_by_junk", "pw123456", "垃圾", "viewer",
                            actor=junk)

    def test_set_active_actor_gate(self, users_db):
        """低权停用/启用拒绝；管理面/系统作业照常（R1-7 页面调用点配套）。"""
        ensure_user_tables()
        uid = create_user("r1_toggle", "pw123456", "启停目标", "viewer")
        with pytest.raises(PermissionError, match="停用/启用"):
            set_active(uid, False, actor=self._LOW_ACTOR)
        # 未触库：目标账号仍启用（verify_login 仍可登录）
        assert verify_login("r1_toggle", "pw123456") is not None
        admin = self._make_admin_actor()
        assert set_active(uid, False, actor=admin) is True
        assert verify_login("r1_toggle", "pw123456") is None
        assert set_active(uid, True) is True  # actor=None 系统作业
        for junk in self._JUNK_ACTORS:
            with pytest.raises(PermissionError):
                set_active(uid, False, actor=junk)

    def test_actor_gate_fires_before_validation(self, users_db):
        """权限闸门先于业务校验：低权 actor 传非法入参也抛 PermissionError
        （不落入 False 口径，越权与业务失败可区分）。"""
        ensure_user_tables()
        victim = create_user("r1_order", "pw123456", "顺序", "viewer")
        with pytest.raises(PermissionError):
            grant_role(victim, "not-a-role", actor=self._LOW_ACTOR)
        with pytest.raises(PermissionError):
            set_role(victim, "not-a-role", actor=self._LOW_ACTOR)
        with pytest.raises(PermissionError):
            change_password(victim, "short", actor=self._LOW_ACTOR)
        with pytest.raises(PermissionError):
            create_user("x", "pw123456", "x", "superadmin",
                        actor=self._LOW_ACTOR)


# ============================================
# RV4-5：管理动作实时回库复核（消除亚 rerun TOCTOU 窗口）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 users 数据层集成测试")
class TestRV45LiveRoleRecheck:
    """_require_actor_roles 二级判定（RV4-5）：会话快照足色后仍实时回库
    复核 —— 快照生成后角色被撤销/账号被停用时，旧快照不再放行敏感写。

    复用模块级 users_db fixture（独立测试库，跑完 DROP）。
    """

    def _stale_admin_actor(self, uid):
        """快照形态 actor dict：会话里还带着 dict_admin（库内已撤销）。"""
        return {"id": uid, "username": "rv45_chief", "role": "viewer",
                "roles": ["dict_admin", "sys_admin"]}

    def test_stale_snapshot_rejected_after_revoke(self, users_db):
        """核心场景：revoke 后拿旧快照 grant/revoke —— 实时复核拒绝。"""
        ensure_user_tables()
        chief = create_user("rv45_chief", "pw123456", "被撤权管理员", "viewer")
        assert grant_role(chief, "dict_admin") is True
        victim = create_user("rv45_victim", "pw123456", "目标", "viewer")
        stale = self._stale_admin_actor(chief)

        # 快照与库一致时放行（一级+二级都过）
        assert grant_role(victim, "editor", actor=stale) is True
        assert revoke_role(victim, "editor", actor=stale) is True

        # 库内撤销 dict_admin：快照没变（rerun 间共享的 session_state 形态）
        assert revoke_role(chief, "dict_admin") is True
        assert "dict_admin" not in list_roles(chief)  # 基线 viewer 仍在
        with pytest.raises(PermissionError, match="实时"):
            grant_role(victim, "reviewer", actor=stale)
        with pytest.raises(PermissionError, match="实时"):
            revoke_role(victim, "viewer", actor=stale)
        with pytest.raises(PermissionError, match="实时"):
            set_active(victim, False, actor=stale)
        # 未生效：库内无任何角色变动
        assert list_roles(victim) == ["viewer"]

    def test_demoted_snapshot_rejected_after_set_role(self, users_db):
        """set_role 降级路径：基线重置后旧快照同样被实时复核拦下。"""
        ensure_user_tables()
        chief = create_user("rv45_demoted", "pw123456", "降级管理员", "viewer")
        assert grant_role(chief, "dict_admin") is True
        target = create_user("rv45_target", "pw123456", "改基线", "viewer")
        stale = self._stale_admin_actor(chief)
        assert set_role(chief, "annotator") is True  # 基线重置清掉叠加角色
        assert "dict_admin" not in list_roles(chief)
        with pytest.raises(PermissionError, match="实时"):
            set_role(target, "annotator", actor=stale)

    def test_current_admin_still_passes(self, users_db):
        """快照与库一致的管理员不受影响（一级+二级都过）。"""
        ensure_user_tables()
        chief = create_user("rv45_live", "pw123456", "在权管理员", "viewer")
        assert grant_role(chief, "dict_admin") is True
        victim = create_user("rv45_live_v", "pw123456", "目标", "viewer")
        live = self._stale_admin_actor(chief)
        live["username"] = "rv45_live"
        assert grant_role(victim, "editor", actor=live) is True
        assert set_active(victim, False, actor=live) is True
        assert set_active(victim, True, actor=live) is True

    def test_fail_closed_when_role_lookup_empty(self, users_db, monkeypatch):
        """库内查无角色（停用/已删/库故障同形）→ fail-closed 拒绝。"""
        ensure_user_tables()
        chief = create_user("rv45_down", "pw123456", "查无角色", "viewer")
        assert grant_role(chief, "dict_admin") is True
        victim = create_user("rv45_down_v", "pw123456", "目标", "viewer")
        actor = self._stale_admin_actor(chief)
        actor["username"] = "rv45_down"
        # 模拟 list_roles 失败（数据库故障 → []，has_role fail-closed False）
        monkeypatch.setattr(users_db_module, "list_roles", lambda uid: [])
        with pytest.raises(PermissionError, match="实时"):
            grant_role(victim, "viewer", actor=actor)

    def test_actor_id_dirty_fail_closed(self, users_db):
        """快照足色但 id 脏值（无身份可复核）→ fail-closed 拒绝。"""
        ensure_user_tables()
        victim = create_user("rv45_dirty", "pw123456", "目标", "viewer")
        for bad_id in (None, 0, "abc"):
            actor = {"id": bad_id, "username": "ghost", "role": "viewer",
                     "roles": ["dict_admin"]}
            with pytest.raises(PermissionError, match="实时"):
                grant_role(victim, "editor", actor=actor)

    def test_self_password_change_unaffected(self, users_db):
        """自助改密走 self_uid 分支（无需管理角色，不做实时复核）。"""
        ensure_user_tables()
        uid = create_user("rv45_selfpw", "pw123456", "自助改密", "viewer")
        actor = {"id": uid, "username": "rv45_selfpw", "role": "viewer",
                 "roles": ["viewer"]}
        assert change_password(uid, "self-new-pw-9", actor=actor) is True
        assert verify_login("rv45_selfpw", "self-new-pw-9") is not None
