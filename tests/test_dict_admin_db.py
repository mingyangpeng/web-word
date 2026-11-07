"""词典管理数据层模块测试（src/dict_admin_db.py，Agent C）。

两层结构，与 tests/test_users_db.py / test_ai_ledger.py 既有约定一致：

  * 纯函数（值规整 _normalize_value / 枚举白名单规整 / sha256 指纹规整 /
    标识符白名单正则）与模块常量、权限标注不碰数据库 —— 本地与 CI 全跑；
  * 数据层 CRUD（ensure / define_field / deprecate_field / set_value /
    get_values_for_anchor / query_anchors_by_field / start_batch /
    finish_batch / rollback_batch）依赖真实 MySQL —— 连不上或账号无建库
    权限就 skip（类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_users_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，
跑完 DROP。库名与 test_users_db / test_org_db / test_security_hardening
共用 —— 本地账号通常只对既有测试库名有授权（SHOW GRANTS 可查），复用
既成约定；若环境后续为本模块专库（如 web_word_dict_admin_test）补授权，
改 TEST_DB 一行即可。三表均无 users 外键（软引用），fixture 无需先拉
users 表，ensure_dict_admin_tables 可独立建表。

覆盖面（阶段1施工规范对 Agent C 的要求）：
  字段定义（枚举/类型校验与拒绝）/ 枚举值白名单拒绝 / EAV 读写（upsert
  一字段一锚一值）/ 按锚查询（词条装配定制属性区）/ 按字段查值反查锚 /
  批次登记与记账 / 批次回滚（软作废 + 旧值恢复 + 状态机 + revert_log
  整体预校验）。
"""

import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.dict_admin_db import (  # noqa: E402
    ANCHOR_TYPES,
    APPLIES_TO,
    BATCH_STATUSES,
    FIELD_STATUSES,
    MAX_VALUE_TEXT_LEN,
    REVERT_ACTIONS,
    VALUE_TYPES,
    _INVALID,
    _clean_enum_values,
    _clean_sha256,
    _normalize_value,
    define_field,
    deprecate_field,
    ensure_dict_admin_tables,
    finish_batch,
    get_field,
    get_values_for_anchor,
    list_fields,
    persist_revert_log,
    query_anchors_by_field,
    rollback_batch,
    set_value,
    start_batch,
)

TEST_DB = "web_word_dict_admin_test"  # 与 users 系测试共用（授权覆盖；见模块 docstring）


# ============================================
# 纯函数与常量（契约 §3-C 表设计口径，无数据库）
# ============================================

class TestConstants:
    """模块常量（契约 §3-C 枚举原样）。"""

    def test_enum_constants(self):
        """applies_to/锚类型/值类型/状态枚举与契约表设计一致。"""
        assert APPLIES_TO == ("word", "sense", "example")
        assert ANCHOR_TYPES == APPLIES_TO
        assert VALUE_TYPES == ("text", "number", "enum", "date", "bool")
        assert FIELD_STATUSES == ("active", "deprecated")
        assert BATCH_STATUSES == ("running", "finished", "rolled_back")
        assert REVERT_ACTIONS == ("insert", "update")

    def test_permission_annotations_present(self):
        """业务写操作的 docstring 标注「仅词典管理员」权限要求（§15 导入同权）。"""
        import src.dict_admin_db as m

        for fn in (m.define_field, m.deprecate_field, m.set_value,
                   m.start_batch, m.finish_batch, m.rollback_batch):
            doc = fn.__doc__ or ""
            assert "词典管理员" in doc, f"{fn.__name__} docstring 缺权限标注"
            assert "§15" in doc or "导入同权" in doc, f"{fn.__name__} docstring 缺规范出处"


class TestValueNormalization:
    """_normalize_value：五种 value_type 的规整与拒绝（写读共用同一套口径）。"""

    def test_text(self):
        """text：str 原样存储；空串合法（required 是表单侧强制，数据层不拒）。"""
        assert _normalize_value("text", "书面语") == ("书面语", None)
        assert _normalize_value("text", "") == ("", None)
        assert _normalize_value("text", " 带空格 ") == (" 带空格 ", None)
        assert _normalize_value("text", 42) is _INVALID
        assert _normalize_value("text", None) is _INVALID
        assert _normalize_value("text", "x" * (MAX_VALUE_TEXT_LEN + 1)) is _INVALID

    def test_number(self):
        """number：int/float（含负数）→ value_num；bool/字符串/NaN/Inf 拒。"""
        assert _normalize_value("number", 3) == (None, 3.0)
        assert _normalize_value("number", -2.5) == (None, -2.5)
        assert _normalize_value("number", 0) == (None, 0.0)
        assert _normalize_value("number", True) is _INVALID   # bool 不是数
        assert _normalize_value("number", "3") is _INVALID
        assert _normalize_value("number", float("nan")) is _INVALID
        assert _normalize_value("number", float("inf")) is _INVALID
        assert _normalize_value("number", None) is _INVALID

    def test_enum(self):
        """enum：去空白后必须 ∈ 白名单；白名单缺失/不含该值一律拒。"""
        allowed = ["正式", "草稿"]
        assert _normalize_value("enum", "正式", allowed) == ("正式", None)
        assert _normalize_value("enum", " 草稿 ", allowed) == ("草稿", None)  # 去空白后匹配
        assert _normalize_value("enum", "口语", allowed) is _INVALID
        assert _normalize_value("enum", "正式", None) is _INVALID
        assert _normalize_value("enum", "正式", []) is _INVALID
        assert _normalize_value("enum", 3, allowed) is _INVALID

    def test_date(self):
        """date：严格 YYYY-MM-DD（补零）或 date/datetime 实例 → ISO 串。"""
        assert _normalize_value("date", "2026-11-07") == ("2026-11-07", None)
        assert _normalize_value("date", date(2026, 11, 7)) == ("2026-11-07", None)
        assert _normalize_value("date", datetime(2026, 11, 7, 10, 30)) == ("2026-11-07", None)
        assert _normalize_value("date", "2026-2-3") is _INVALID      # 未补零
        assert _normalize_value("date", "2026-13-01") is _INVALID    # 月份越界
        assert _normalize_value("date", "2026-02-30") is _INVALID    # 日不存在
        assert _normalize_value("date", "07/11/2026") is _INVALID    # 非 ISO
        assert _normalize_value("date", 20261107) is _INVALID
        assert _normalize_value("date", None) is _INVALID

    def test_bool(self):
        """bool：True/False/0/1 → '1'/'0'；其余一律拒（不猜）。"""
        assert _normalize_value("bool", True) == ("1", None)
        assert _normalize_value("bool", False) == ("0", None)
        assert _normalize_value("bool", 1) == ("1", None)
        assert _normalize_value("bool", 0) == ("0", None)
        assert _normalize_value("bool", "true") is _INVALID
        assert _normalize_value("bool", 2) is _INVALID
        assert _normalize_value("bool", 1.0) is _INVALID
        assert _normalize_value("bool", None) is _INVALID

    def test_unknown_type_rejected(self):
        """未知 value_type（防御）一律 _INVALID。"""
        assert _normalize_value("json", {"a": 1}) is _INVALID
        assert _normalize_value("", "x") is _INVALID


class TestGuards:
    """入参守卫（枚举白名单 / sha256 指纹），无数据库。"""

    def test_clean_enum_values_dedupe_preserve_order(self):
        """白名单去重保序；tuple 也接受。"""
        assert _clean_enum_values(["正式", "草稿", "正式"]) == ["正式", "草稿"]
        assert _clean_enum_values(("A", "B")) == ["A", "B"]

    def test_clean_enum_values_rejects(self):
        """空名单/非字符串成员/空白成员/超长成员/超量一律 _INVALID。"""
        from src.dict_admin_db import MAX_ENUM_ITEMS, MAX_ENUM_VALUE_LEN

        assert _clean_enum_values(None) is _INVALID
        assert _clean_enum_values([]) is _INVALID
        assert _clean_enum_values("正式,草稿") is _INVALID      # 字符串不是清单
        assert _clean_enum_values(["正式", ""]) is _INVALID     # 空白成员
        assert _clean_enum_values(["正式", 3]) is _INVALID      # 非字符串
        assert _clean_enum_values(["x" * (MAX_ENUM_VALUE_LEN + 1)]) is _INVALID
        assert _clean_enum_values([str(i) for i in range(MAX_ENUM_ITEMS + 1)]) is _INVALID

    def test_clean_sha256(self):
        """64 位十六进制（大小写均可）→ 小写；其余拒。"""
        sha = "a" * 64
        assert _clean_sha256(sha) == sha
        assert _clean_sha256("A" * 64) == sha          # 大写归一
        assert _clean_sha256(" " + sha + " ") == sha   # 去空白
        assert _clean_sha256("a" * 63) is _INVALID
        assert _clean_sha256("a" * 65) is _INVALID
        assert _clean_sha256("z" * 64) is _INVALID     # 非十六进制
        assert _clean_sha256("a" * 32 + "_" + "b" * 31) is _INVALID  # 下划线不是指纹
        assert _clean_sha256(None) is _INVALID

    def test_identifier_whitelist(self):
        """动态表/列名白名单正则：只放行 [A-Za-z0-9_]{1,64}（防 SQL 注入第一道闸）。"""
        import src.dict_admin_db as m

        assert m._IDENTIFIER_RE.match("custom_fields")
        assert m._IDENTIFIER_RE.match("custom_values_2")
        assert m._IDENTIFIER_RE.match("a" * 64)
        for bad in ("", "a" * 65, "a-b", "a b", "表名", "a;drop", "a`b", "a'b", "a.b"):
            assert not m._IDENTIFIER_RE.match(bad), f"应拒绝: {bad!r}"


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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过词典管理数据层集成测试")
class TestDictAdminIntegration:
    """定制属性 EAV + 导入批次台账（跑在共用测试库 web_word_users_test）。"""

    @pytest.fixture
    def dict_admin(self, monkeypatch):
        """建空测试库并让本模块指向它，测试结束 DROP。

        与 test_users_db.users_db / test_ai_ledger.ledger 相同的手法：
        get_db_cursor / _new_connection 在调用时读 mysql_db 模块全局，
        monkeypatch MYSQL_DATABASE 即可，连接池按键含 db 名，互不污染。
        本模块三表无 users 外键，ensure 可独立建表（无需先拉 users）。
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过词典管理集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_dict_admin_tables()
        yield
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

    # --- 辅助 ---

    # 测试自控直写 SQL 的表名白名单（测试内防拼错，非被测代码）
    _TABLES = ("custom_fields", "custom_values", "import_batches", "import_revert_log")

    def _fetch(self, table, row_id):
        """直接读库取单行（绕过数据层，验证落库真相）。"""
        from src.mysql_db import get_db_cursor

        assert table in self._TABLES
        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (row_id,))
            return cursor.fetchone()

    def _count(self, table, where="1=1", params=()):
        """直接数行数（验证唯一约束/未变更语义的落库真相）。"""
        from src.mysql_db import get_db_cursor

        assert table in self._TABLES
        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)
            return int(cursor.fetchone()["n"])

    def _exec(self, sql, params=()):
        """直写一句 SQL（模拟导入方对业务表的覆盖写，供回滚恢复用例）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(sql, params)

    def _text_field(self, code="register", anchor="word"):
        """建一个 text/word 定制字段（默认口径）。"""
        fid = define_field(1, code, "语域", anchor, "text", created_by=1)
        assert isinstance(fid, int) and fid > 0
        return fid

    # --- 建表 ---

    def test_ensure_idempotent(self, dict_admin):
        """ensure 重复调用幂等：四表齐且不炸（CREATE TABLE IF NOT EXISTS）。"""
        ensure_dict_admin_tables()
        ensure_dict_admin_tables()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME IN ('custom_fields','custom_values',
                                        'import_batches','import_revert_log')"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 4

    # --- 字段定义 ---

    def test_define_field_basic(self, dict_admin):
        """定义 text 字段：落库字段齐、status=active、required=0。"""
        fid = self._text_field()
        row = self._fetch("custom_fields", fid)
        assert row["project_id"] == 1
        assert row["code"] == "register"
        assert row["name"] == "语域"
        assert row["applies_to"] == "word"
        assert row["value_type"] == "text"
        assert row["enum_values"] is None
        assert int(row["required"]) == 0
        assert row["status"] == "active"
        assert row["created_by"] == 1

    def test_define_field_required_and_enum(self, dict_admin):
        """required=True 与 enum 白名单（JSON）落库；get_field/list_fields 读回。"""
        fid = define_field(1, "grade", "教材分级", "word", "enum",
                           enum_values=["小学", "初中", "高中"], required=True,
                           created_by=1)
        assert fid > 0
        field = get_field(fid)
        assert field["required"] is True
        assert field["enum_values"] == ["小学", "初中", "高中"]
        assert field["value_type"] == "enum"
        # list_fields 默认只出 active
        fields = list_fields(1)
        assert [f["code"] for f in fields] == ["grade"]
        assert list_fields(1, include_deprecated=True)[0]["code"] == "grade"

    def test_define_field_rejects_invalid(self, dict_admin):
        """非法 applies_to/value_type/枚举/长度/编号一律 0，不进数据库。"""
        before = self._count("custom_fields")
        assert define_field(0, "x", "名", "word", "text") == 0          # project 非法
        assert define_field("一", "x", "名", "word", "text") == 0       # project 非整数
        # （数字串 "1" 可宽松转 int —— 与 ai_ledger._as_int 同口径，允许）
        assert define_field(1, "", "名", "word", "text") == 0           # 空 code
        assert define_field(1, "x", "", "word", "text") == 0            # 空 name
        assert define_field(1, "x" * 65, "名", "word", "text") == 0     # code 超长
        assert define_field(1, "x", "名" * 121, "word", "text") == 0    # name 超长
        assert define_field(1, "x", "名", "lemma", "text") == 0         # applies_to 非法
        assert define_field(1, "x", "名", "word", "json") == 0          # value_type 非法
        assert define_field(1, "x", "名", "word", "enum") == 0          # enum 缺白名单
        assert define_field(1, "x", "名", "word", "enum", enum_values=[]) == 0
        assert define_field(1, "x", "名", "word", "enum", enum_values=["a", ""]) == 0
        assert define_field(1, "x", "名", "word", "enum", enum_values=["a", 3]) == 0
        assert define_field(1, "x", "名", "word", "enum", enum_values="a,b") == 0
        assert define_field(1, "x", "名", "word", "text", enum_values=["a"]) == 0  # 非 enum 带 白名单
        assert define_field(1, "x", "名", "word", "text", created_by=0) == 0
        assert self._count("custom_fields") == before

    def test_define_field_duplicate_code_rejected(self, dict_admin):
        """UNIQUE(project_id, code)：同项目重复 code 拒；跨项目同 code 允许。"""
        assert define_field(1, "register", "语域", "word", "text") > 0
        assert define_field(1, "register", "重名", "sense", "enum",
                            enum_values=["a"]) == 0  # 同项目同 code
        assert define_field(2, "register", "另一项目的语域", "word", "text") > 0
        assert self._count("custom_fields", "code = %s", ("register",)) == 2

    # --- 弃用 ---

    def test_deprecate_field_lifecycle(self, dict_admin):
        """弃用：只停写不删 —— active→deprecated True，重复弃用 False，存量值保留。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "书面语", updated_by=1) is True
        assert deprecate_field(fid) is True
        assert deprecate_field(fid) is False  # 已弃用（未变更 = False 口径）
        assert get_field(fid)["status"] == "deprecated"
        # 弃用后拒新写值
        assert set_value(fid, "word", 8, "口语", updated_by=1) is False
        # 存量值保留只读（field_status 让页面灰显）
        values = get_values_for_anchor("word", 7)
        assert len(values) == 1
        assert values[0]["value_text"] == "书面语"
        assert values[0]["field_status"] == "deprecated"
        # list_fields 默认不再出弃用字段
        assert list_fields(1) == []
        assert list_fields(1, include_deprecated=True)[0]["status"] == "deprecated"

    def test_deprecate_field_nonexistent(self, dict_admin):
        """弃用不存在的字段返回 False。"""
        assert deprecate_field(999999) is False

    # --- EAV 写值（set_value）---

    def test_set_value_and_get_roundtrip(self, dict_admin):
        """写值 → 按锚取回：值 + 字段元信息齐（词条装配定制属性区口径）。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "书面语", updated_by=2) is True
        values = get_values_for_anchor("word", 7)
        assert len(values) == 1
        item = values[0]
        assert item["field_id"] == fid
        assert item["anchor_type"] == "word"
        assert item["anchor_id"] == 7
        assert item["value_text"] == "书面语"
        assert item["value_num"] is None
        assert item["updated_by"] == 2
        assert item["code"] == "register"
        assert item["name"] == "语域"
        assert item["value_type"] == "text"
        assert item["field_status"] == "active"

    def test_set_value_upsert_single_row(self, dict_admin):
        """一字段一锚一值：重复写是改值（UNIQUE upsert），不堆行。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "书面语", updated_by=2) is True
        assert set_value(fid, "word", 7, "口语", updated_by=3) is True
        assert self._count("custom_values", "field_id = %s", (fid,)) == 1
        values = get_values_for_anchor("word", 7)
        assert values[0]["value_text"] == "口语"
        assert values[0]["updated_by"] == 3

    def test_set_value_same_value_false(self, dict_admin):
        """同值重写：无实际变更 → False（未变更口径），行数不变。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "书面语", updated_by=2) is True
        assert set_value(fid, "word", 7, "书面语", updated_by=2) is False
        assert self._count("custom_values", "field_id = %s", (fid,)) == 1

    def test_set_value_enum_whitelist(self, dict_admin):
        """enum 字段：白名单内接受（去空白），白名单外拒绝不落库。"""
        fid = define_field(1, "grade", "教材分级", "word", "enum",
                           enum_values=["小学", "初中"], created_by=1)
        assert set_value(fid, "word", 7, "小学", updated_by=1) is True
        assert set_value(fid, "word", 8, " 初中 ", updated_by=1) is True  # 去空白匹配
        assert set_value(fid, "word", 9, "高中", updated_by=1) is False  # 不在白名单
        assert get_values_for_anchor("word", 9) == []
        assert {v["value_text"] for v in get_values_for_anchor("word", 7)} == {"小学"}
        assert {v["value_text"] for v in get_values_for_anchor("word", 8)} == {"初中"}

    def test_set_value_number(self, dict_admin):
        """number 字段：存 value_num 列；bool/字符串/NaN/Inf 拒。"""
        fid = define_field(1, "freq", "频级", "sense", "number", created_by=1)
        assert set_value(fid, "sense", 5, 3, updated_by=1) is True
        assert set_value(fid, "sense", 6, -2.5, updated_by=1) is True
        row = self._fetch("custom_values", get_values_for_anchor("sense", 5)[0]["id"])
        assert float(row["value_num"]) == 3.0
        assert row["value_text"] is None
        assert get_values_for_anchor("sense", 6)[0]["value_num"] == -2.5
        assert set_value(fid, "sense", 7, "3", updated_by=1) is False
        assert set_value(fid, "sense", 7, True, updated_by=1) is False
        assert set_value(fid, "sense", 7, float("nan"), updated_by=1) is False
        assert set_value(fid, "sense", 7, float("inf"), updated_by=1) is False
        assert get_values_for_anchor("sense", 7) == []

    def test_set_value_bool(self, dict_admin):
        """bool 字段：True/False/0/1 → '1'/'0'；'true'/2 拒。"""
        fid = define_field(1, "core", "核心词", "word", "bool", created_by=1)
        assert set_value(fid, "word", 1, True, updated_by=1) is True
        assert set_value(fid, "word", 2, 0, updated_by=1) is True
        assert {v["value_text"] for v in get_values_for_anchor("word", 1)} == {"1"}
        assert {v["value_text"] for v in get_values_for_anchor("word", 2)} == {"0"}
        assert set_value(fid, "word", 3, "yes", updated_by=1) is False
        assert set_value(fid, "word", 3, 2, updated_by=1) is False

    def test_set_value_date(self, dict_admin):
        """date 字段：严格 YYYY-MM-DD / date 实例；未补零/越界日期拒。"""
        fid = define_field(1, "reviewed_on", "复核日", "sense", "date", created_by=1)
        assert set_value(fid, "sense", 5, "2026-11-07", updated_by=1) is True
        assert set_value(fid, "sense", 6, date(2026, 1, 2), updated_by=1) is True
        assert get_values_for_anchor("sense", 5)[0]["value_text"] == "2026-11-07"
        assert get_values_for_anchor("sense", 6)[0]["value_text"] == "2026-01-02"
        assert set_value(fid, "sense", 7, "2026-1-2", updated_by=1) is False
        assert set_value(fid, "sense", 7, "2026-02-30", updated_by=1) is False
        assert set_value(fid, "sense", 7, "07/11/2026", updated_by=1) is False
        assert set_value(fid, "sense", 7, 20261107, updated_by=1) is False

    def test_set_value_required_not_enforced_here(self, dict_admin):
        """required 只是批次 2 表单声明：数据层不拒空值（存什么算什么）。"""
        fid = define_field(1, "note", "编者按", "word", "text", required=True,
                           created_by=1)
        assert set_value(fid, "word", 7, "", updated_by=1) is True  # 空串合法
        assert get_values_for_anchor("word", 7)[0]["value_text"] == ""

    def test_set_value_rejects_anchor_mismatch(self, dict_admin):
        """锚类型必须等于字段 applies_to：word 字段挂 sense 锚拒；未知锚类型拒。"""
        fid = self._text_field(anchor="word")
        assert set_value(fid, "sense", 5, "书面语", updated_by=1) is False
        assert set_value(fid, "example", 5, "书面语", updated_by=1) is False
        assert set_value(fid, "lemma", 5, "书面语", updated_by=1) is False
        assert set_value(fid, "", 5, "书面语", updated_by=1) is False
        assert self._count("custom_values") == 0

    def test_set_value_rejects_bad_params(self, dict_admin):
        """字段不存在 / 非法 anchor_id / updated_by 缺失 / 值超长一律 False。"""
        assert set_value(999999, "word", 7, "x", updated_by=1) is False  # 字段不存在
        fid = self._text_field()
        assert set_value(fid, "word", 0, "x", updated_by=1) is False     # anchor_id 非法
        assert set_value(fid, "word", "7", "x", updated_by=1) is True    # str int 可转
        assert set_value(fid, "word", 7, "x", updated_by=None) is False  # 留痕必填
        assert set_value(fid, "word", 7, "x", updated_by="x") is False
        assert set_value(fid, "word", 7, "长" * (MAX_VALUE_TEXT_LEN + 1),
                         updated_by=1) is False                          # 值超长
        assert self._count("custom_values") == 1

    def test_get_values_for_anchor_multi_fields_and_empty(self, dict_admin):
        """同一锚挂多个字段按 field_id 升序；无值锚返回 []。"""
        fid1 = self._text_field("register")
        fid2 = define_field(1, "grade", "教材分级", "word", "enum",
                            enum_values=["小学"], created_by=1)
        assert set_value(fid2, "word", 7, "小学", updated_by=1) is True
        assert set_value(fid1, "word", 7, "书面语", updated_by=1) is True
        values = get_values_for_anchor("word", 7)
        assert [v["field_id"] for v in values] == [fid1, fid2]
        assert get_values_for_anchor("word", 999) == []
        assert get_values_for_anchor("sense", 7) == []  # 该锚类型的另一类锚无值

    # --- 按字段查值反查锚（query_anchors_by_field）---

    def test_query_anchors_by_field_text(self, dict_admin):
        """text：精确匹配（原样，不 strip）；无命中返回 []。"""
        fid = self._text_field()
        assert set_value(fid, "word", 1, "书面语", updated_by=1) is True
        assert set_value(fid, "word", 2, "书面语", updated_by=1) is True
        assert set_value(fid, "word", 3, "口语", updated_by=1) is True
        assert query_anchors_by_field(fid, "书面语") == ["1", "2"]
        assert query_anchors_by_field(fid, "口语") == ["3"]
        assert query_anchors_by_field(fid, "方言") == []
        assert query_anchors_by_field(999999, "书面语") == []  # 字段不存在

    def test_query_anchors_by_field_number(self, dict_admin):
        """number：int/float 同值互通（都走 value_num 列）；类型不符按查无。"""
        fid = define_field(1, "freq", "频级", "sense", "number", created_by=1)
        assert set_value(fid, "sense", 5, 3, updated_by=1) is True
        assert set_value(fid, "sense", 6, 3.0, updated_by=1) is True
        assert set_value(fid, "sense", 7, -2.5, updated_by=1) is True
        assert query_anchors_by_field(fid, 3) == ["5", "6"]
        assert query_anchors_by_field(fid, 3.0) == ["5", "6"]
        assert query_anchors_by_field(fid, -2.5) == ["7"]
        assert query_anchors_by_field(fid, "abc") == []  # 非 number 值：查无（记日志）
        assert query_anchors_by_field(fid, True) == []

    def test_query_anchors_by_field_enum_bool_date(self, dict_admin):
        """enum/bool/date：与写值同一套规整后匹配（bool True ↔ '1'）。"""
        fenum = define_field(1, "grade", "教材分级", "word", "enum",
                             enum_values=["小学", "初中"], created_by=1)
        assert set_value(fenum, "word", 1, "小学", updated_by=1) is True
        assert set_value(fenum, "word", 2, "初中", updated_by=1) is True
        assert query_anchors_by_field(fenum, " 小学 ") == ["1"]   # 去空白匹配
        assert query_anchors_by_field(fenum, "高中") == []        # 白名单外：查无
        fbool = define_field(1, "core", "核心词", "word", "bool", created_by=1)
        assert set_value(fbool, "word", 3, True, updated_by=1) is True
        assert set_value(fbool, "word", 4, False, updated_by=1) is True
        assert query_anchors_by_field(fbool, True) == ["3"]
        assert query_anchors_by_field(fbool, 0) == ["4"]
        fdate = define_field(1, "reviewed_on", "复核日", "sense", "date", created_by=1)
        assert set_value(fdate, "sense", 8, "2026-11-07", updated_by=1) is True
        assert query_anchors_by_field(fdate, "2026-11-07") == ["8"]
        assert query_anchors_by_field(fdate, "2026-1-7") == []

    # --- 导入批次：登记与记账 ---

    def test_start_and_finish_batch(self, dict_admin):
        """start_batch 登记 running → finish_batch 记账转 finished；重复 finish 拒。"""
        sha = "ab" * 32
        bid = start_batch(1, "语域表.csv", sha, "custom_values",
                          {"file_col": "word", "register": "field:register"}, operator=1)
        assert isinstance(bid, int) and bid > 0
        row = self._fetch("import_batches", bid)
        assert row["project_id"] == 1
        assert row["file_name"] == "语域表.csv"
        assert row["file_sha256"] == sha
        assert row["target_domain"] == "custom_values"
        assert row["status"] == "running"
        assert int(row["rows_total"]) == 0
        assert row["operator"] == 1
        # mapping JSON 落库可读回
        import json

        assert json.loads(row["mapping_json"]) == {
            "file_col": "word", "register": "field:register"
        }
        assert finish_batch(bid, rows_total=10, rows_ok=8, rows_rejected=2) is True
        row = self._fetch("import_batches", bid)
        assert row["status"] == "finished"
        assert int(row["rows_total"]) == 10
        assert int(row["rows_ok"]) == 8
        assert int(row["rows_rejected"]) == 2
        assert finish_batch(bid, 10, 8, 2) is False  # 只有 running 可 finish
        assert finish_batch(999999, 1, 1, 0) is False

    def test_start_batch_accepts_json_str_mapping(self, dict_admin):
        """mapping_json 已是 JSON 串也接受（归一化转存）。"""
        bid = start_batch(1, "f.csv", "cd" * 32, "definitions", '{"col": "field:1"}',
                          operator=1)
        assert bid > 0
        row = self._fetch("import_batches", bid)
        assert self._fetch("import_batches", bid)["mapping_json"] is not None
        assert row["file_sha256"] == "cd" * 32

    def test_start_batch_rejects_invalid(self, dict_admin):
        """非法 sha/文件名/目标域/映射/操作人/项目 一律 0，不进数据库。"""
        good_sha = "ab" * 32
        before = self._count("import_batches")
        assert start_batch(0, "f.csv", good_sha, "definitions", {}, operator=1) == 0
        assert start_batch(1, "", good_sha, "definitions", {}, operator=1) == 0
        assert start_batch(1, "f" * 256, good_sha, "definitions", {}, operator=1) == 0
        assert start_batch(1, "f.csv", "短", "definitions", {}, operator=1) == 0       # sha 非法
        assert start_batch(1, "f.csv", "z" * 64, "definitions", {}, operator=1) == 0   # 非十六进制
        assert start_batch(1, "f.csv", good_sha, "", {}, operator=1) == 0             # 空目标域
        assert start_batch(1, "f.csv", good_sha, "d" * 41, {}, operator=1) == 0        # 目标域超长
        assert start_batch(1, "f.csv", good_sha, "definitions", None, operator=1) == 0  # 映射缺失
        assert start_batch(1, "f.csv", good_sha, "definitions", "col=x", operator=1) == 0  # 非 JSON
        assert start_batch(1, "f.csv", good_sha, "definitions", 42, operator=1) == 0   # 标量映射
        assert start_batch(1, "f.csv", good_sha, "definitions", {}, operator=0) == 0
        assert start_batch(1, "f.csv", good_sha, "definitions", {}, operator=None) == 0
        assert self._count("import_batches") == before

    # --- 导入批次：回滚（软作废 / 旧值恢复 / 状态机 / 预校验）---

    def _finished_batch(self) -> int:
        """建一个已 finished 的批次（回滚用例的公共前置）。"""
        bid = start_batch(1, "f.csv", "ab" * 32, "custom_values", {}, operator=1)
        assert bid > 0
        assert finish_batch(bid, 5, 5, 0) is True
        return bid

    def test_rollback_state_machine(self, dict_admin):
        """running 不可回滚（无基线）；finished 可；rolled_back 不可重复回滚。"""
        bid = start_batch(1, "f.csv", "ab" * 32, "custom_values", {}, operator=1)
        assert rollback_batch(bid, []) is False              # running：拒绝
        assert self._fetch("import_batches", bid)["status"] == "running"
        assert finish_batch(bid, 5, 5, 0) is True
        assert rollback_batch(bid, []) is True               # 空 revert_log 合法（零变更批次）
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"
        assert rollback_batch(bid, []) is False              # 已回滚：拒绝重复
        assert rollback_batch(999999, []) is False

    def test_rollback_insert_soft_invalidate(self, dict_admin):
        """insert 动作软作废：custom_fields 有含 deprecated 的 status 枚举 → 置 deprecated。"""
        fid = self._text_field()
        bid = self._finished_batch()
        assert rollback_batch(
            bid, [{"action": "insert", "table": "custom_fields", "row_id": fid}]
        ) is True
        assert self._fetch("custom_fields", fid)["status"] == "deprecated"
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"

    def test_rollback_insert_no_status_column_skipped(self, dict_admin):
        """无 status 列的表（custom_values）：MVP 口径只留痕不动行，批次仍转 rolled_back。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "书面语", updated_by=1) is True
        vid = get_values_for_anchor("word", 7)[0]["id"]
        bid = self._finished_batch()
        assert rollback_batch(
            bid, [{"action": "insert", "table": "custom_values", "row_id": vid}]
        ) is True
        assert self._fetch("custom_values", vid)["value_text"] == "书面语"  # 行未被动
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"

    def test_rollback_insert_missing_row_tolerated(self, dict_admin):
        """软作废未命中行（已删/已作废）：容忍幂等重放，批次仍 rolled_back。"""
        bid = self._finished_batch()
        assert rollback_batch(
            bid, [{"action": "insert", "table": "custom_fields", "row_id": 999999}]
        ) is True
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"

    def test_rollback_update_restores_old_values(self, dict_admin):
        """update 动作按 old_values 恢复旧值（模拟导入覆盖了既有值再回滚）。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "旧值", updated_by=1) is True
        vid = get_values_for_anchor("word", 7)[0]["id"]
        # 模拟导入方覆盖写（绕过数据层直写业务表）
        self._exec("UPDATE custom_values SET value_text = %s WHERE id = %s", ("新值", vid))
        assert self._fetch("custom_values", vid)["value_text"] == "新值"
        bid = self._finished_batch()
        assert rollback_batch(
            bid,
            [{"action": "update", "table": "custom_values", "row_id": vid,
              "old_values": {"value_text": "旧值"}}],
        ) is True
        assert self._fetch("custom_values", vid)["value_text"] == "旧值"
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"

    def test_rollback_update_multiple_columns(self, dict_admin):
        """update 动作一次恢复多列（value_text + value_num）。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "旧值", updated_by=1) is True
        vid = get_values_for_anchor("word", 7)[0]["id"]
        self._exec(
            "UPDATE custom_values SET value_text = %s, value_num = %s WHERE id = %s",
            ("新值", 9.5, vid),
        )
        bid = self._finished_batch()
        assert rollback_batch(
            bid,
            [{"action": "update", "table": "custom_values", "row_id": vid,
              "old_values": {"value_text": "旧值", "value_num": None}}],
        ) is True
        row = self._fetch("custom_values", vid)
        assert row["value_text"] == "旧值"
        assert row["value_num"] is None

    def test_rollback_rejects_invalid_log_atomically(self, dict_admin):
        """revert_log 任一条非法：整体拒绝（防半套回滚），批次状态保持 finished。"""
        fid = self._text_field()
        assert set_value(fid, "word", 7, "书面语", updated_by=1) is True
        vid = get_values_for_anchor("word", 7)[0]["id"]
        bid = self._finished_batch()
        bad_logs = [
            "不是清单",                                                   # 非 list
            [{"action": "drop", "table": "custom_fields", "row_id": 1}],  # 非法动作
            [{"action": "insert", "table": "custom_fields; DROP TABLE x", "row_id": 1}],
            [{"action": "insert", "table": "no_such_table", "row_id": 1}],  # 库中无此表
            [{"action": "insert", "table": "custom_fields", "row_id": 0}],
            [{"action": "insert", "table": "custom_fields", "row_id": "x"}],
            [{"action": "insert", "table": "custom_fields"}],              # 缺 row_id
            ["不是 dict"],
            [{"action": "update", "table": "custom_values", "row_id": vid}],          # 缺 old_values
            [{"action": "update", "table": "custom_values", "row_id": vid,
              "old_values": {}}],                                                    # 空 old_values
            [{"action": "update", "table": "custom_values", "row_id": vid,
              "old_values": {"no_such_col": 1}}],                                    # 未知列
            [{"action": "update", "table": "custom_values", "row_id": vid,
              "old_values": {"value_text; --": 1}}],                                 # 注入列名
            # 第一条合法、第二条非法：整体拒绝，合法那条也不许执行
            [{"action": "insert", "table": "custom_fields", "row_id": fid},
             {"action": "insert", "table": "ghost_tbl", "row_id": 1}],
        ]
        for bad in bad_logs:
            assert rollback_batch(bid, bad) is False, f"应拒绝: {bad!r}"
            assert self._fetch("import_batches", bid)["status"] == "finished"
        # 合法条目未被执行（整体拒绝语义）：字段仍是 active，值未被软作废
        assert self._fetch("custom_fields", fid)["status"] == "active"
        assert self._fetch("custom_values", vid)["value_text"] == "书面语"


# ============================================
# 批次 6-T：revert_log 持久化（伴生表 import_revert_log）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过词典管理数据层集成测试")
class TestRevertLogPersistence:
    """persist_revert_log 往返 + rollback_batch 无显式日志读伴生表（跨会话语义）。"""

    @pytest.fixture
    def dict_admin(self, monkeypatch):
        """与 TestDictAdminIntegration 同款建库 fixture（独立重建，互不污染）。"""
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过回滚持久化集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_dict_admin_tables()
        yield
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

    def _finished_batch(self) -> int:
        bid = start_batch(1, "f.xlsx", "ab" * 32, "definitions", {}, operator=1)
        assert bid > 0
        assert finish_batch(bid, 2, 2, 0) is True
        return bid

    _FETCH_TABLES = ("custom_fields", "custom_values", "import_batches",
                     "import_revert_log")

    def _fetch(self, table, row_id):
        """按主键取单行（表名限测试白名单，防拼接；参数化查询）。"""
        assert table in self._FETCH_TABLES, table
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (row_id,))
            return cursor.fetchone()

    def _persisted_rows(self, batch_id):
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT seq, event FROM import_revert_log "
                "WHERE batch_id = %s ORDER BY seq",
                (batch_id,),
            )
            return cursor.fetchall()

    # --- 持久化往返 ---

    def test_persist_roundtrip_seq_order(self, dict_admin):
        """事件逐条落库：seq 从 1 递增、JSON 读回与原事件相等（含中文/None 值）。"""
        events = [
            {"action": "update", "table": "custom_values", "row_id": 3,
             "old_values": {"value_text": "旧值", "value_num": None}},
            {"action": "insert", "table": "definitions", "row_id": 42},
        ]
        bid = self._finished_batch()
        assert persist_revert_log(bid, events) is True
        rows = self._persisted_rows(bid)
        assert [int(r["seq"]) for r in rows] == [1, 2]
        import json

        assert json.loads(rows[0]["event"]) == events[0]
        assert json.loads(rows[1]["event"]) == events[1]

    def test_persist_empty_list_legal(self, dict_admin):
        """空清单合法：True、零插入（零行变更批次无事可记）。"""
        bid = self._finished_batch()
        assert persist_revert_log(bid, []) is True
        assert list(self._persisted_rows(bid)) == []

    def test_persist_rejects_invalid_atomically(self, dict_admin):
        """非法入参整体拒绝不落库：非 list / 非 dict 条目 / 白名单外 action /
        不可 JSON 序列化事件 / 非法批次号 / 批次不存在（FK）。"""
        bid = self._finished_batch()
        bad_inputs = [
            "不是清单",
            [{"action": "insert", "table": "definitions", "row_id": 1}, "不是 dict"],
            [{"action": "drop", "table": "definitions", "row_id": 1}],   # REVERT_ACTIONS 外
            [{"action": "insert", "table": "definitions", "row_id": 1, "x": float("nan")}],
            [{"action": "insert", "table": "definitions", "row_id": 1, "x": {1, 2}}],
            42,
        ]
        for bad in bad_inputs:
            assert persist_revert_log(bid, bad) is False, f"应拒绝: {bad!r}"
        assert list(self._persisted_rows(bid)) == []
        assert persist_revert_log(0, []) is False
        assert persist_revert_log(-1, []) is False
        assert persist_revert_log("x", []) is False
        assert persist_revert_log(999999, [{"action": "insert", "table": "definitions",
                                            "row_id": 1}]) is False  # FK：批次不存在

    def test_persist_duplicate_rejected(self, dict_admin):
        """同一批次只允许持久化一次（防两次执行的事件混序拼接）。"""
        bid = self._finished_batch()
        events = [{"action": "insert", "table": "definitions", "row_id": 1}]
        assert persist_revert_log(bid, events) is True
        assert persist_revert_log(bid, events) is False
        assert persist_revert_log(bid, []) is False
        assert len(self._persisted_rows(bid)) == 1

    # --- 跨会话语义：无显式日志的回滚读伴生表 ---

    def test_rollback_without_explicit_log_reads_companion_table(self, dict_admin):
        """rollback_batch(batch_id)（不传日志）：从伴生表读事件执行 —— 跨会话回滚成立。

        会话语义：调用侧不携带任何内存态（revert_log 只存在于伴生表），
        模拟「A 会话执行写入＋持久化 → B 会话（新进程/新会话）回滚」。
        """
        fid = define_field(1, "register", "语域", "word", "text", created_by=1)
        bid = self._finished_batch()
        events = [{"action": "insert", "table": "custom_fields", "row_id": fid}]
        assert persist_revert_log(bid, events) is True
        # B 会话：只凭 batch_id 回滚（无内存 revert_log）
        assert rollback_batch(bid) is True
        assert self._fetch("custom_fields", fid)["status"] == "deprecated"
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"

    def test_rollback_update_event_from_companion_table(self, dict_admin):
        """伴生表 update 事件：无显式日志回滚按 old_values 恢复旧值。"""
        fid = define_field(1, "register", "语域", "word", "text", created_by=1)
        assert set_value(fid, "word", 7, "旧值", updated_by=1) is True
        vid = get_values_for_anchor("word", 7)[0]["id"]
        with db.get_db_cursor() as cursor:
            cursor.execute("UPDATE custom_values SET value_text = %s WHERE id = %s",
                           ("新值", vid))
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "update", "table": "custom_values", "row_id": vid,
             "old_values": {"value_text": "旧值"}},
        ]) is True
        assert rollback_batch(bid) is True
        assert self._fetch("custom_values", vid)["value_text"] == "旧值"

    def test_rollback_without_persisted_log_rejected_honestly(self, dict_admin):
        """无持久化记录 → 如实拒绝（status 保持 finished），注明无持久化回滚日志。"""
        fid = define_field(1, "register", "语域", "word", "text", created_by=1)
        bid = self._finished_batch()
        assert rollback_batch(bid) is False   # 从未 persist
        assert self._fetch("import_batches", bid)["status"] == "finished"
        assert rollback_batch(999999) is False
        # 零行变更批次：persist 空清单后同样无记录 → 无显式日志拒绝（空清单
        # 本就无事可回滚；显式传 [] 仍是合法的只翻状态路径）
        assert persist_revert_log(bid, []) is True
        assert rollback_batch(bid) is False
        assert rollback_batch(bid, []) is True
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"
        assert fid > 0  # 字段未受影响（空清单回滚零事件）

    def test_rollback_rejects_corrupt_persisted_event(self, dict_admin):
        """持久化事件损坏（JSON 合法但非 dict）→ fail-closed 拒绝，状态不动。"""
        bid = self._finished_batch()
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO import_revert_log (batch_id, seq, event) VALUES (%s, 1, %s)",
                (bid, "[1, 2]"),
            )
        assert rollback_batch(bid) is False
        assert self._fetch("import_batches", bid)["status"] == "finished"

    def test_rollback_rejects_invalid_persisted_event(self, dict_admin):
        """持久化了白名单外事件（防御纵深）→ 预校验整体拒绝，状态不动。"""
        bid = self._finished_batch()
        # 绕过 persist 入口校验直插（模拟历史脏数据/手工运维）
        import json

        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO import_revert_log (batch_id, seq, event) VALUES (%s, 1, %s)",
                (bid, json.dumps({"action": "drop", "table": "definitions", "row_id": 1})),
            )
        assert rollback_batch(bid) is False
        assert self._fetch("import_batches", bid)["status"] == "finished"

    def test_explicit_log_still_works_with_persistence_present(self, dict_admin):
        """向后兼容：已有持久化记录的批次，显式传参路径原样可用（覆盖伴生表读取）。"""
        fid = define_field(1, "register", "语域", "word", "text", created_by=1)
        fid2 = define_field(1, "grade", "分级", "word", "text", created_by=1)
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        # 显式传另一组事件：按显式清单执行（不读伴生表）
        assert rollback_batch(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid2},
        ]) is True
        assert self._fetch("custom_fields", fid)["status"] == "active"
        assert self._fetch("custom_fields", fid2)["status"] == "deprecated"
        assert self._fetch("import_batches", bid)["status"] == "rolled_back"

    def test_batch_cascade_deletes_persisted_log(self, dict_admin):
        """FK ON DELETE CASCADE：批次行清理时伴生事件随之消失（无悬挂行）。"""
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "definitions", "row_id": 1},
        ]) is True
        assert len(self._persisted_rows(bid)) == 1
        with db.get_db_cursor() as cursor:
            cursor.execute("DELETE FROM import_batches WHERE id = %s", (bid,))
        assert list(self._persisted_rows(bid)) == []


# ============================================
# 批次 6-T 验收④：跨会话回滚端到端实证
# （A 会话 run_import 写入＋persist → B 会话 rollback_batch 只凭 batch_id 回滚）
# ============================================

_DEFINITIONS_DDL = """CREATE TABLE IF NOT EXISTS definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL UNIQUE,
    chinese_ndef TEXT NOT NULL,
    semantic_table JSON NOT NULL,
    phonetic VARCHAR(64) DEFAULT NULL,
    cluster_id INT DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过跨会话回滚集成测试")
class TestCrossSessionRollback:
    """验收④：A 会话写入＋持久化 → B 会话（全新调用、零内存态）回滚成功。"""

    @pytest.fixture
    def cross_session_db(self, monkeypatch):
        """建空测试库（dict_admin 四表＋最小 definitions）并指向它，结束 DROP。"""
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过跨会话回滚集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)

        ensure_dict_admin_tables()
        with db.get_db_cursor() as cursor:
            cursor.execute(_DEFINITIONS_DDL)
        yield
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

    def _row_of(self, verb):
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, verb, chinese_ndef, phonetic FROM definitions WHERE verb = %s",
                (verb,),
            )
            return cursor.fetchone()

    def test_session_a_writes_persists_session_b_rolls_back(self, cross_session_db):
        """全链：start_batch → run_import 实写 → finish → persist；
        B 会话只拿 batch_id 调 rollback_batch（无显式日志）→ 旧值还原。"""
        from src.import_engine import run_import

        # --- A 会话：既有行被覆盖 + 新词目行 ---
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, chinese_ndef, semantic_table, phonetic) "
                "VALUES (%s, %s, '{}', %s)",
                ("run", "旧释义", "/old/"),
            )
            run_row_id = int(cursor.lastrowid)

        mapping = {"词目": "verb", "中文释义": "chinese_ndef", "音标": "phonetic"}
        rows = [
            {"词目": "run", "中文释义": "新释义", "音标": "/rʌn/"},
            {"词目": "dash", "中文释义": "猛冲", "音标": "/dæʃ/"},
        ]
        batch_id = start_batch(1, "verbs.xlsx", "ab" * 32, "definitions",
                               {"column_field_mapping": mapping}, 1)
        assert batch_id > 0
        result = run_import(rows, mapping, 1, dry_run=False)
        assert result["ok"] is True and result["rows_ok"] == 2
        assert len(result["revert_log"]) == 2
        assert finish_batch(batch_id, result["rows_total"], result["rows_ok"],
                            result["rows_rejected"]) is True
        assert persist_revert_log(batch_id, result["revert_log"]) is True

        # A 会话写入生效
        assert self._row_of("run")["chinese_ndef"] == "新释义"
        assert self._row_of("dash") is not None

        # --- B 会话（新 run）：除 batch_id 外零内存态（无 session、无 revert_log）---
        assert rollback_batch(batch_id) is True
        # 更新行恢复旧值；新增行按既有口径仅留痕（definitions 无 status 列）
        restored = self._row_of("run")
        assert restored["chinese_ndef"] == "旧释义"
        assert restored["phonetic"] == "/old/"
        assert restored["id"] == run_row_id
        assert self._row_of("dash") is not None
        with db.get_db_cursor() as cursor:
            cursor.execute("SELECT status FROM import_batches WHERE id = %s", (batch_id,))
            assert cursor.fetchone()["status"] == "rolled_back"

    def test_session_b_rollback_fails_without_persistence(self, cross_session_db):
        """反例：A 会话写入但未持久化（旧版页面行为）→ B 会话只凭 batch_id 拒绝。

        跨会话回滚以持久化日志为凭 —— 无凭据时如实拒绝（批次状态保持
        finished），不在无日志的情况下盲翻状态；本会话显式传参路径仍可用
        （向后兼容口径）。
        """
        from src.import_engine import run_import

        mapping = {"词目": "verb", "中文释义": "chinese_ndef"}
        batch_id = start_batch(1, "verbs.xlsx", "cd" * 32, "definitions", mapping, 1)
        result = run_import([{"词目": "walk", "中文释义": "走"}], mapping, 1, dry_run=False)
        assert result["ok"] is True
        assert len(result["revert_log"]) == 1
        assert finish_batch(batch_id, result["rows_total"], result["rows_ok"],
                            result["rows_rejected"]) is True
        # A 会话未调 persist_revert_log（事件只存在于调用侧内存）
        # B 会话只凭 batch_id：无持久化回滚日志 → 如实拒绝
        assert rollback_batch(batch_id) is False
        with db.get_db_cursor() as cursor:
            cursor.execute("SELECT status FROM import_batches WHERE id = %s", (batch_id,))
            assert cursor.fetchone()["status"] == "finished"
        # 显式传参路径不依赖持久化：同一批次仍可回滚（向后兼容）
        assert rollback_batch(batch_id, result["revert_log"]) is True
        with db.get_db_cursor() as cursor:
            cursor.execute("SELECT status FROM import_batches WHERE id = %s", (batch_id,))
            assert cursor.fetchone()["status"] == "rolled_back"
