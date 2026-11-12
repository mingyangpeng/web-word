"""安全加固与遗留清理测试（R1-P2a/P2b/P2c + R5 遗留 1/2）。

覆盖四组加固点：

  1. CSV 公式注入防护（R1-P2a）：sanitize_csv_cell 对 = + - @ \\t \\r 六类
     注入串前置单引号，正常文本/数字不动；统一实现的别名一致性；DataFrame
     路径与 reliability._export_csv 的真实导出路径。
  2. 弱口令判据（R1-P2c）：change_password 长度 ≥8 校验（校验先于任何
     数据库访问，纯函数部分无库也跑）；真实库部分验证 pbkdf2 重哈希、
     旧口令失效、is_using_default_password 判据翻转。
  3. 会话角色防陈旧（R1-P2b）：get_user_role 实时反映 set_role / set_active
     ——管理员改角色/停用立即生效（旧权限立即失效）；另以 AppTest 验证
     UI 层：改角色后旧页面权限立即失效、停用用户下次操作被登出并提示。
  4. reliability_runs.created_by 归属列（R5 遗留 2）：迁移幂等（连跑两次
     不炸、列恰一条）、_persist_run 落库归属、run_reliability 传参透传。

分层与既有约定一致：纯函数/假游标不碰数据库（CI 全跑）；数据层与 AppTest
依赖真实 MySQL（独立测试库 web_word_users_test —— 与 test_users_db /
test_integration_apptest 共用同一授权库名，串行执行互不污染；连不上或
账号无建库权限整类 skip）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import src.mysql_db as db  # noqa: E402
import src.reliability as rel  # noqa: E402
from src.security import (  # noqa: E402
    CSV_FORMULA_TRIGGER_CHARS,
    sanitize_csv_cell,
    sanitize_csv_dataframe,
    sanitize_csv_value,
)
from src.users_db import (  # noqa: E402
    MIN_PASSWORD_LENGTH,
    change_password,
    create_user,
    ensure_user_tables,
    get_user_role,
    is_using_default_password,
    list_users,
    set_active,
    set_role,
    verify_login,
    verify_password,
)

TEST_DB = "web_word_users_test"


# ============================================
# 1) sanitize_csv_cell：注入串全覆盖（无数据库）
# ============================================
class TestSanitizeCsvCell:
    """单元格级防护：= + - @ \\t \\r 全触发 + 正常内容不误伤。"""

    def test_equals_sign_triggered(self):
        assert sanitize_csv_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
        assert sanitize_csv_cell("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"

    def test_plus_sign_triggered(self):
        assert sanitize_csv_cell("+8613800000000") == "'+8613800000000"

    def test_minus_sign_triggered(self):
        assert sanitize_csv_cell("-1+1|cmd") == "'-1+1|cmd"

    def test_at_sign_triggered(self):
        assert sanitize_csv_cell("@import(url)") == "'@import(url)"

    def test_tab_triggered(self):
        assert sanitize_csv_cell("\tpayload") == "'\tpayload"

    def test_carriage_return_triggered(self):
        """回车（\\r）开头同批防护（OWASP CSV 注入建议覆盖）"""
        assert sanitize_csv_cell("\rcr_payload") == "'\rcr_payload"

    def test_normal_text_untouched(self):
        """中文标注文本 / 空串 / 数字样文本不受影响"""
        for text in ("动词 run 标注为 Y", "hello world", "3.14", "拓展", ""):
            assert sanitize_csv_cell(text) == text

    def test_mid_string_trigger_not_touched(self):
        """仅首字符触发：中间出现 = + - @ 不处理"""
        assert sanitize_csv_cell("a=b") == "a=b"
        assert sanitize_csv_cell("方案A-备注") == "方案A-备注"

    def test_non_string_untouched(self):
        """数字/None/布尔原样返回（信度 α 列不受影响）"""
        assert sanitize_csv_cell(5) == 5
        assert sanitize_csv_cell(-3) == -3
        assert sanitize_csv_cell(0.848) == 0.848
        assert sanitize_csv_cell(None) is None
        assert sanitize_csv_cell(True) is True

    def test_trigger_chars_complete(self):
        """触发集合 = 任务要求的六类前缀"""
        assert set(CSV_FORMULA_TRIGGER_CHARS) == {"=", "+", "-", "@", "\t", "\r"}

    def test_alias_is_same_implementation(self):
        """历史名 sanitize_csv_value 与 sanitize_csv_cell 是同一实现（消重保证）"""
        assert sanitize_csv_value is sanitize_csv_cell

    def test_dataframe_path(self):
        """DataFrame 整表路径：恶意单元格加引号、数字列与原对象不动"""
        import pandas as pd

        df = pd.DataFrame({
            "verb": ["run", "@evil"],
            "alpha": [0.848, None],
            "note": ["-ok", "=HYPERLINK(\"http://x\")"],
        })
        out = sanitize_csv_dataframe(df)
        assert out.loc[0, "verb"] == "run"
        assert out.loc[0, "alpha"] == 0.848
        assert out.loc[1, "verb"].startswith("'@")
        assert out.loc[1, "note"].startswith("'=")
        assert df.loc[1, "verb"] == "@evil"  # 原对象不被修改


class TestReliabilityExportCsvProtection:
    """reliability._export_csv 逐单元格防护（R1-P2a 在信度/分歧导出点落地）。"""

    RESULT = {
        "category": "motion",
        "task_type": "admission",
        "n_coders": 2,
        "n_units": 2,
        "overall_alpha": 1.0,
        "per_feature": {"admission": 1.0, "-weird_feature": 0.5},
        "disagreements": [
            {"sense_id": 7, "field": "admission",
             "values": {"1": "Y", "2": "=cmd|' /C calc"}}
        ],
    }

    def test_malicious_disagreement_value_quoted(self):
        text = rel._export_csv(self.RESULT).decode("utf-8-sig")
        assert "'=cmd|' /C calc" in text, "分歧取值以 = 开头未加单引号前缀"

    def test_malicious_feature_name_quoted(self):
        text = rel._export_csv(self.RESULT).decode("utf-8-sig")
        assert "'-weird_feature" in text, "特征名以 - 开头未加单引号前缀"

    def test_normal_cells_untouched(self):
        text = rel._export_csv(self.RESULT).decode("utf-8-sig")
        assert "admission,1.000,是" in text
        assert "overall_alpha" in text


# ============================================
# 2) 弱口令判据：纯校验部分（无数据库）
# ============================================
class TestWeakPasswordPolicyPure:
    """change_password 的入口校验先于数据库访问 —— 无库环境即可验证。"""

    def test_min_length_is_eight(self):
        """弱口令下限 = 8（admin123 恰 8 位，新口令不得更弱）"""
        assert MIN_PASSWORD_LENGTH == 8

    def test_short_password_rejected_without_db(self, monkeypatch):
        """7 位口令：入口即拒（连库都不该碰）"""
        import src.users_db as udb

        def _no_db(*a, **kw):
            raise AssertionError("7 位口令应在长度校验即拒绝，不应触库")

        monkeypatch.setattr(udb, "get_db_cursor", _no_db)
        assert udb.change_password(1, "7chars!") is False

    def test_eight_chars_reaches_database(self, monkeypatch):
        """8 位恰好达标：过长度门、走到写库路径（假游标返回 rowcount=1 → True）"""
        import src.users_db as udb

        class _Cur:
            rowcount = 1

            def execute(self, *a, **kw):
                pass

        class _Ctx:
            def __enter__(self):
                return _Cur()

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(udb, "get_db_cursor", lambda *a, **kw: _Ctx())
        assert udb.change_password(1, "8char-ok") is True  # 恰 8 位

    def test_non_string_password_rejected(self):
        """非字符串口令一律拒绝"""
        assert change_password(1, None) is False
        assert change_password(1, 12345678) is False


# ============================================
# 4) run_reliability 的 created_by 透传（假游标，无数据库）
# ============================================
class _FakeCtx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class _FakeRunCursor:
    """按 SQL 文本分派的假游标（与 test_reliability.py 同手法，最小版）。"""

    def __init__(self, rows):
        self.rows = rows
        self.insert_params = None
        self.lastrowid = 4242
        self._result = []

    def execute(self, sql, params=None):
        if "FROM annotation_submissions" in sql:
            category, task_type = params
            self._result = [
                r for r in self.rows
                if r["category"] == category and r["task_type"] == task_type
            ]
        elif "INSERT INTO reliability_runs" in sql:
            self.insert_params = params
            self._result = []
        else:
            # DDL / INFORMATION_SCHEMA 迁移查询：按"无需迁移"处理（fetchone→None）
            self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _sub(sense_id, coder_id, payload):
    return {"id": 0, "sense_id": sense_id, "coder_id": coder_id,
            "payload": payload, "status": "submitted",
            "category": "motion", "task_type": "admission"}


class TestRunReliabilityCreatedBy:
    """run_reliability(created_by=...) → INSERT 参数透传（R5 遗留 2）。"""

    ROWS = [
        _sub(101, 1, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
        _sub(101, 2, {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}),
    ]

    def _run(self, monkeypatch, **kwargs):
        cursor = _FakeRunCursor(self.ROWS)
        monkeypatch.setattr(rel, "get_db_cursor", lambda autocommit=True: _FakeCtx(cursor))
        return cursor, rel.run_reliability("motion", "admission", **kwargs)

    def test_created_by_forwarded(self, monkeypatch):
        cursor, result = self._run(monkeypatch, created_by=7)
        assert "db_error" not in result
        assert cursor.insert_params is not None
        assert cursor.insert_params[7] == 7, "created_by 应落在 INSERT 第 8 个参数"

    def test_created_by_defaults_to_none(self, monkeypatch):
        cursor, _ = self._run(monkeypatch)
        assert cursor.insert_params[7] is None

    def test_created_by_dirty_value_becomes_none(self, monkeypatch):
        """脏值（非整型化）按 NULL 落库，不炸页面"""
        cursor, result = self._run(monkeypatch, created_by="not-an-int")
        assert "db_error" not in result
        assert cursor.insert_params[7] is None


# ============================================
# 集成部分：真实 MySQL（独立测试库，无库整类 skip）
# ============================================

def _mysql_reachable() -> bool:
    try:
        import pymysql
        from pymysql.cursors import DictCursor

        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=DictCursor, connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()


@pytest.fixture
def hardening_db():
    """独立测试库 web_word_users_test：建库 → patch 全局 → yield → 删库。

    与 test_users_db.py 同一手法（连接池按键含库名，互不污染）。
    """
    import pymysql

    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
    )
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    except pymysql.err.OperationalError as e:
        conn.close()
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过安全加固集成测试: {e}")
    conn.close()

    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    ensure_user_tables()
    yield
    db.MYSQL_DATABASE = old_db  # 先还原全局再删库（与 test_users_db 同约定）
    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3, autocommit=True,
    )
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.close()


def _admin_id() -> int:
    for u in list_users():
        if u["username"] == "admin":
            return int(u["id"])
    raise AssertionError("内置 admin 不存在（ensure_user_tables 未生效）")


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过安全加固集成测试")
class TestChangePasswordIntegration:
    """change_password / is_using_default_password（R1-P2c，真实库）。"""

    def test_default_admin_flagged_until_changed(self, hardening_db):
        """内置默认口令判据：初始 True，改密后 False（横幅消失的判据链路）"""
        uid = _admin_id()
        assert is_using_default_password(uid) is True
        assert change_password(uid, "new-pass-9") is True
        assert is_using_default_password(uid) is False
        # 旧默认口令登录失效，新口令登录成功
        assert verify_login("admin", "admin123") is None
        assert verify_login("admin", "new-pass-9") is not None

    def test_weak_password_rejected_hash_unchanged(self, hardening_db):
        """7 位口令拒绝且旧哈希原样：登录仍用旧口令（弱口令进不了库）"""
        uid = create_user("hp_weak", "old-pass-8", "弱口令测试", "annotator")
        assert change_password(uid, "7chars!") is False
        assert verify_login("hp_weak", "old-pass-8") is not None, "弱口令拒绝不应动旧哈希"
        assert verify_login("hp_weak", "7chars!") is None

    def test_change_password_rehashes_and_invalidates_old(self, hardening_db):
        """改密 = pbkdf2 重哈希：旧口令立即失效、新口令可登录、新盐新哈希"""
        uid = create_user("hp_rehash", "old-pass-8", "重哈希测试", "annotator")
        listed = next(u for u in list_users() if u["id"] == uid)
        assert "password_hash" not in listed  # 哈希不出数据层（回归护栏）
        assert change_password(uid, "brand-new-pass") is True
        assert verify_login("hp_rehash", "old-pass-8") is None
        login = verify_login("hp_rehash", "brand-new-pass")
        assert login is not None and login["role"] == "annotator"
        # 新哈希可独立校验且格式合法（pbkdf2_sha256$iter$salt$hash）
        with db.get_db_cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", (uid,))
            stored = cur.fetchone()["password_hash"]
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        assert algo == "pbkdf2_sha256"
        assert int(iterations) >= 120000
        assert verify_password("brand-new-pass", stored) is True

    def test_change_password_nonexistent_user(self, hardening_db):
        assert change_password(999999, "long-enough-8") is False

    def test_change_password_allows_resetting_to_default(self, hardening_db):
        """改回默认口令 → 判据重新为 True（横幅重现；防呆由流程约束兜底）"""
        uid = create_user("hp_reset", "first-pass-1", "回设测试", "annotator")
        assert is_using_default_password(uid) is False
        assert change_password(uid, "admin123") is True  # 恰 8 位，允许
        assert is_using_default_password(uid) is True


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过安全加固集成测试")
class TestRoleLiveCheck:
    """get_user_role 实时性（R1-P2b）：改角色/停用立即生效，旧权限立即失效。"""

    def _mk_user(self, username, role="annotator"):
        uid = create_user(username, "pw123456", username, role)
        assert isinstance(uid, int)
        return uid

    def test_role_reflects_set_role_immediately(self, hardening_db):
        """改角色后 get_user_role 当次返回新角色 —— 旧角色权限立即失效"""
        uid = self._mk_user("rl_live")
        assert get_user_role(uid) == "annotator"
        assert set_role(uid, "reviewer") is True
        assert get_user_role(uid) == "reviewer", "改角色未即时生效"
        assert set_role(uid, "admin") is True
        assert get_user_role(uid) == "admin"

    def test_deactivated_user_role_none_then_restored(self, hardening_db):
        """停用 → None（会话刷新即登出判据）；启用 → 恢复"""
        uid = self._mk_user("rl_deact")
        assert get_user_role(uid) == "annotator"
        assert set_active(uid, False) is True
        assert get_user_role(uid) is None, "停用用户仍返回角色（登出判据失效）"
        assert set_active(uid, True) is True
        assert get_user_role(uid) == "annotator"

    def test_missing_user_role_none(self, hardening_db):
        assert get_user_role(999999) is None

    def test_verify_login_refuses_deactivated(self, hardening_db):
        """停用后旧会话即使重新登录也被拒（统一 None，防枚举语义不变）"""
        uid = self._mk_user("rl_login")
        assert verify_login("rl_login", "pw123456") is not None
        set_active(uid, False)
        assert verify_login("rl_login", "pw123456") is None


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过安全加固集成测试")
class TestCreatedByMigration:
    """reliability_runs.created_by 迁移幂等（R5 遗留 2，真实库）。"""

    def test_migration_idempotent_twice(self, hardening_db):
        """连跑两次建表+迁移不炸、列恰一条（幂等）"""
        assert rel._ensure_reliability_table() is True
        assert rel._ensure_reliability_table() is True
        with db.get_db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
                "AND COLUMN_NAME = 'created_by'"
            )
            assert int(cur.fetchone()["n"]) == 1, "created_by 列应恰一条（不重复加列）"

    def test_migration_on_legacy_table(self, hardening_db):
        """模拟旧表（无 created_by）：先 DROP 旧 DDL 再迁移补列"""
        legacy_ddl = "\n".join(
            line for line in rel.RELIABILITY_RUNS_DDL.splitlines()
            if not line.strip().startswith("created_by")
        )
        assert "created_by" not in legacy_ddl  # 前置：旧 DDL 应已无 created_by
        with db.get_db_cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS reliability_runs")
            cur.execute(legacy_ddl)
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
                "AND COLUMN_NAME = 'created_by'"
            )
            assert int(cur.fetchone()["n"]) == 0, "前置失败：旧表应无 created_by"
        assert rel._ensure_reliability_table() is True
        with db.get_db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
                "AND COLUMN_NAME = 'created_by'"
            )
            assert int(cur.fetchone()["n"]) == 1
        # 再跑一遍仍幂等
        assert rel._ensure_reliability_table() is True

    def test_persist_run_writes_created_by(self, hardening_db):
        """_persist_run 落库 created_by；None 落 NULL"""
        assert rel._ensure_reliability_table() is True
        result = {
            "category": "motion", "task_type": "admission",
            "n_coders": 2, "n_units": 2, "overall_alpha": 1.0,
            "per_feature": {"admission": 1.0}, "disagreements": [],
        }
        rel._persist_run(dict(result), created_by=42)
        rel._persist_run(dict(result))
        with db.get_db_cursor() as cur:
            cur.execute(
                "SELECT created_by FROM reliability_runs ORDER BY id"
            )
            values = [r["created_by"] for r in cur.fetchall()]
        assert values[0] == 42
        assert values[1] is None

    def test_run_reliability_end_to_end_created_by(self, hardening_db):
        """真实库端到端：造两条一致提交 → run_reliability(created_by=uid) 落库归属"""
        from src.annotation_flow import ensure_flow_tables, submit_annotation

        # 本用例需要完整 schema（definitions/oald_senses 外键），幂等初始化
        assert db.init_database(), "测试库 schema 初始化失败"
        ensure_flow_tables()
        coder = create_user("cb_coder", "pw123456", "cb", "annotator")
        # oald_senses 由 init 建表但无数据：测试库自造一个 definition+sense
        with db.get_db_cursor() as cur:
            cur.execute(
                "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
                "VALUES ('cb_verb', '端到端', '{}')"
            )
            did = int(cur.lastrowid)
            cur.execute(
                "INSERT INTO oald_senses (definition_id, sense_index, definition) "
                "VALUES (%s, 1, 'to run hard')", (did,)
            )
            osid = int(cur.lastrowid)
        payload = {"admission": "Y", "schema": "SOURCE_PATH", "alignment": "A"}
        assert submit_annotation("motion", osid, "admission", coder, payload) is True
        result = rel.run_reliability("motion", "admission", created_by=coder)
        assert "db_error" not in result
        assert result.get("run_id") is not None
        with db.get_db_cursor() as cur:
            cur.execute(
                "SELECT created_by, n_coders FROM reliability_runs WHERE id = %s",
                (result["run_id"],),
            )
            row = cur.fetchone()
        assert row["created_by"] == coder
        assert row["n_coders"] == 1


# ============================================
# 3) UI 层：默认口令横幅 / 角色实时生效 / 停用登出（AppTest，真实库）
# ============================================
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过安全加固 AppTest")
class TestHardeningUi:
    """会话加固的端到端行为（侧边栏登录表单 → 实时回查 → 页面权限）。"""

    @pytest.fixture(scope="class")
    def ui_env(self):
        """类级测试库 + 预置账号：admin（默认口令）/ ann（自定义口令 annotator）。"""
        import pymysql

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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过安全加固 AppTest: {e}")
        conn.close()

        old_db = db.MYSQL_DATABASE
        db.MYSQL_DATABASE = TEST_DB
        ensure_user_tables()
        admin_id = _admin_id()
        ann_id = create_user("hd_ann", "hd-ann-pw-8", "加固标注员", "annotator")
        assert isinstance(admin_id, int) and isinstance(ann_id, int)
        yield {"admin_id": admin_id, "ann_id": ann_id}
        db.MYSQL_DATABASE = old_db
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3, autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()

    def _new_at(self):
        from streamlit.testing.v1 import AppTest

        return AppTest.from_file(APP, default_timeout=180)

    def _form_login(self, at, username, password):
        inputs = {t.key: t for t in at.sidebar.text_input}
        inputs["login_username"].set_value(username)
        inputs["login_password"].set_value(password)
        submit = [b for b in at.sidebar.button if b.form_id and "登录" in str(b.label)]
        assert submit, "登录提交按钮未找到"
        submit[0].click()
        at.run()
        return at

    def _pget(self, at, key, default=None):
        try:
            return at.session_state[key]
        except Exception:  # noqa: BLE001
            return default

    def test_default_password_banner_and_dismiss(self, ui_env):
        """默认口令用户登录 → 侧边栏横幅（唯一入口指向自助面板）；经自助面板改密 → 横幅消失。

        R8-1（批次 12）：横幅内嵌表单已删除——改密 UI 三处合一，唯一入口=
        「🔑 修改密码」自助面板（_render_self_change_password_form）。本用例改经
        自助面板走完整改密流，横幅「改密后消失」语义不变。
        """
        at = self._new_at()
        at.run()
        at = self._form_login(at, "admin", "admin123")
        assert not at.exception
        # 批次 31：横幅压一行 caption（侧边栏净化——保留语义，文案精简）
        assert any("默认密码未修改" in str(c.value) for c in at.sidebar.caption), \
            "默认口令用户登录后未出现改密提示"
        # 三处合一：横幅不再内嵌表单，唯一入口=自助面板
        assert not any(t.key == "force_new_password" for t in at.sidebar.text_input), \
            "内嵌表单已删除，不应再有 force_new_password 输入"
        assert any("修改密码" in str(b.label) for b in at.sidebar.button), \
            "唯一入口「🔑 修改密码」expander 未渲染"

        # 经唯一入口（自助面板）改密：两次不一致 → 报错；7 位 → 报错；合规 → 成功且横幅消失
        def _set_form(at, v1, v2):
            # AppTest：expander 折叠态不影响元素树（面板内 widget 始终可寻址、
            # 表单可直接提交），无需（也不能）对 Expander 块做 set_value
            cur = {t.key: t for t in at.sidebar.text_input}
            cur["self_pw_old"].set_value("admin123")
            cur["self_pw_new"].set_value(v1)
            cur["self_pw_again"].set_value(v2)
            submit = [b for b in at.sidebar.button
                      if b.form_id and "修改密码" in str(b.label)]
            assert submit, "自助改密提交按钮未找到"
            submit[0].click()
            at.run()
            return at

        # 两次新密码不一致 → 自助面板校验报错（报错文案落在 sidebar.error）
        at = _set_form(at, "hd-admin-new", "different")
        assert any("两次新密码一致" in str(e.value) for e in
                   list(at.sidebar.error) + list(at.error))
        at = _set_form(at, "7chars!", "7chars!")
        assert any("至少 8 位" in str(e.value) for e in
                   list(at.sidebar.error) + list(at.error))
        at = _set_form(at, "hd-admin-new", "hd-admin-new")
        assert not at.exception
        assert is_using_default_password(ui_env["admin_id"]) is False
        assert verify_login("admin", "hd-admin-new") is not None
        assert verify_login("admin", "admin123") is None
        # 下一次 rerun：横幅不再出现
        at.run()
        assert not at.exception
        assert not any("默认密码未修改" in str(c.value) for c in at.sidebar.caption)

    def test_role_change_takes_effect_immediately(self, ui_env):
        """管理员改角色后，旧会话下次操作即按新角色判定（标注页立即失去 annotator 权限）"""
        at = self._new_at()
        at.run()
        at = self._form_login(at, "hd_ann", "hd-ann-pw-8")
        assert self._pget(at, "user") is not None
        at.session_state["page"] = "annotate"
        at.run()
        assert not at.exception

        # 管理员在库侧把角色改成 viewer（不经本会话）
        assert set_role(ui_env["ann_id"], "viewer") is True
        at.run()
        assert not at.exception
        user = self._pget(at, "user")
        assert user is not None and user["role"] == "viewer", "会话快照未刷新"
        # 标注页（残留页）入口按新角色拦下：viewer 无权限
        assert any("无权限" in str(w.value) for w in at.warning), \
            "改角色后旧权限未立即失效"

    def test_deactivated_user_logged_out_on_next_action(self, ui_env):
        """停用用户会话在下次任意操作被登出并提示"""
        at = self._new_at()
        at.run()
        at = self._form_login(at, "hd_ann", "hd-ann-pw-8")
        assert self._pget(at, "user") is not None

        assert set_active(ui_env["ann_id"], False) is True
        at.session_state["page"] = "search"
        at.run()  # 任意操作（基础页也触发实时回查）
        assert not at.exception
        assert self._pget(at, "user") is None, "停用用户会话未被登出"
        assert any("停用" in str(w.value) for w in at.warning), "登出未给出提示"
