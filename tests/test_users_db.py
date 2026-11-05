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
from src.users_db import (  # noqa: E402
    PBKDF2_ITERATIONS,
    ROLES,
    create_user,
    ensure_user_tables,
    hash_password,
    list_users,
    set_active,
    set_role,
    verify_login,
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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 users 数据层集成测试")
class TestUsersDbIntegration:
    """数据层 CRUD + 内置默认 admin（跑在独立测试库 web_word_users_test）。"""

    @pytest.fixture
    def users_db(self, monkeypatch):
        """
        建空测试库并让 users 模块指向它，测试结束 DROP。

        与 test_migration_integration.v1_database 相同的手法：
        get_db_cursor / _new_connection 在调用时读 mysql_db 模块全局，
        monkeypatch MYSQL_DATABASE 即可，连接池按键含 db 名，互不污染。
        账号无建库权限（生产账号常见）则 skip —— 环境能力问题，不是代码缺陷。
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
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 users 集成测试: {e}")
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
