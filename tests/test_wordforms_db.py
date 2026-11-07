"""词形表模块测试（src/wordforms_db.py）。

两层结构，与 tests/test_users_db.py 既有约定一致：

  * 入参守卫（空/超长/非法 form）在应用层先拒、不碰数据库 —— 本地与
    CI 全跑；
  * 数据层（ensure_wordforms_tables / resolve_form / load_pinyin_from_zh_dict /
    plan_pinyin_load）依赖真实 MySQL —— 连不上或账号无建库权限就 skip
    （类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_wordforms_test（monkeypatch
db.MYSQL_DATABASE 指向它），每个测试重建，跑完 DROP。库名按模块预授权
（scripts/grant_local_mysql.sql 模式）；无该库名授权的环境自动 skip。

现汉词条表依赖：load_pinyin_from_zh_dict 读 zh_dict_entries（lemma/pinyin
列，见 src/zh_dict.py）—— fixture 直接在测试库执行
zh_dict.ZH_DICT_TABLES_SQL 建 3 表并种少量词条（不跑全量灌库脚本），
种数据即可验证「每词条写一条 kind='pinyin' 词形 + 幂等」。

覆盖面（阶段1施工规范对 Agent E 的要求）：
  resolve_form 精确匹配（含声调/大小写敏感）/ 拼音灌库幂等（第二次 0 新增）/
  空拼音与超长词条跳过 / 多 kind 词形还原 / plan 预估口径。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.wordforms_db import (  # noqa: E402
    KINDS,
    KIND_PINYIN,
    MAX_FORM_LEN,
    MAX_LEMMA_LEN,
    ensure_wordforms_tables,
    load_pinyin_from_zh_dict,
    plan_pinyin_load,
    resolve_form,
)

TEST_DB = "web_word_wordforms_test"


# ============================================
# 入参守卫（应用层先拒，不碰数据库 —— CI 必跑）
# ============================================

class TestGuards:
    """resolve_form 的应用层守卫与模块常量。"""

    def test_empty_form_rejected(self):
        """空/纯空白 form 返回 []。"""
        assert resolve_form("") == []
        assert resolve_form("   ") == []
        assert resolve_form(None) == []  # type: ignore[arg-type]
        assert resolve_form(123) == []  # type: ignore[arg-type]

    def test_too_long_form_rejected(self):
        """超 80 字符 form 返回 []（VARCHAR(80) 上限，应用层先拒）。"""
        assert resolve_form("a" * 81) == []

    def test_kinds_match_contract(self):
        """词形三类型与平台架构设计规范 §6 D① 一致。"""
        assert KINDS == ("inflection", "variant", "pinyin")

    def test_max_lengths_match_ddl(self):
        """长度上限与 DDL 对齐（lemma_word/form 均 VARCHAR(80)）。"""
        assert MAX_LEMMA_LEN == 80
        assert MAX_FORM_LEN == 80


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
def wordforms_env(monkeypatch):
    """建测试库 + zh_dict 三表（种数据）+ wordforms 空表，结束 DROP。

    zh_dict_entries 是 load_pinyin 的输入源：fixture 执行
    src/zh_dict.ZH_DICT_TABLES_SQL 在测试库建表（不跑全量灌库脚本），
    种 5 条代表性词条（多音字两条 + 单条 + 空拼音 + NULL 拼音）。
    """
    import pymysql
    from src.zh_dict import ZH_DICT_TABLES_SQL

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
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过 wordforms 集成测试: {e}")
    cur.close()
    conn.close()

    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)

    # 建现汉三表（种数据的输入源）+ wordforms 空表
    from src.mysql_db import get_db_cursor

    with get_db_cursor() as cursor:
        for sql in ZH_DICT_TABLES_SQL:
            cursor.execute(sql)
    seed_zh_entries()
    ensure_wordforms_tables()
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


def seed_zh_entries():
    """种词条：跑 pǎo/páo（多音字）、苹果 píngguǒ、板 bǎn（空拼音）、
    ABC（NULL 拼音）。"""
    from src.mysql_db import get_db_cursor

    rows = [
        ("跑", "pǎo", "动"),
        ("跑", "páo", "名"),
        ("苹果", "píngguǒ", "名"),
        ("板", "", "名"),        # 空串拼音 → 跳过
        ("ABC", None, None),     # NULL 拼音 → 跳过
    ]
    with get_db_cursor() as cursor:
        for lemma, pinyin, pos in rows:
            cursor.execute(
                "INSERT INTO zh_dict_entries (lemma, pinyin, pos, erhua) "
                "VALUES (%s, %s, %s, 0)",
                (lemma, pinyin, pos),
            )


def _wf_rows(cursor, kind=KIND_PINYIN):
    cursor.execute("SELECT lemma_word, form, kind FROM wordforms WHERE kind = %s", (kind,))
    return {(r["lemma_word"], r["form"]) for r in cursor.fetchall()}


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 wordforms 数据层集成测试")
class TestWordformsIntegration:
    """wordforms 建表 / 拼音灌库 / 词形还原（跑在 web_word_wordforms_test）。"""

    # --- 建表 ---

    def test_ensure_idempotent(self, wordforms_env):
        """ensure 重复调用幂等（CREATE TABLE IF NOT EXISTS）。"""
        ensure_wordforms_tables()
        ensure_wordforms_tables()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wordforms'"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 1

    # --- 拼音灌库（契约核心：幂等）---

    def test_load_pinyin_writes_rows(self, wordforms_env):
        """每词条一条 kind='pinyin' 词形；空/NULL 拼音与空词目跳过。"""
        inserted = load_pinyin_from_zh_dict()
        # 种了 5 条：跑 pǎo / 跑 páo / 苹果 píngguǒ 可灌（板空拼音、ABC NULL 跳过）
        assert inserted == 3
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            pairs = _wf_rows(cursor)
        assert ("跑", "pǎo") in pairs
        assert ("跑", "páo") in pairs      # 多音字每读音一条（同 lemma_word）
        assert ("苹果", "píngguǒ") in pairs
        assert len(pairs) == 3
        with get_db_cursor() as cursor:
            cursor.execute("SELECT DISTINCT kind FROM wordforms")
            assert {r["kind"] for r in cursor.fetchall()} == {"pinyin"}

    def test_load_pinyin_idempotent(self, wordforms_env):
        """幂等：重复灌库第二次 0 新增，行数不变（UNIQUE+IGNORE 策略）。"""
        first = load_pinyin_from_zh_dict()
        assert first == 3
        second = load_pinyin_from_zh_dict()
        third = load_pinyin_from_zh_dict()
        assert second == 0
        assert third == 0
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM wordforms")
            assert int(cursor.fetchone()["n"] or 0) == 3  # 不产生重复行

    def test_load_pinyin_incremental(self, wordforms_env):
        """增量补灌：只灌新词目，不冲掉已有行。"""
        load_pinyin_from_zh_dict()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO zh_dict_entries (lemma, pinyin, pos, erhua) "
                "VALUES (%s, %s, '动', 0)",
                ("奔驰", "bēnchí"),
            )
        added = load_pinyin_from_zh_dict()
        assert added == 1
        with get_db_cursor() as cursor:
            pairs = _wf_rows(cursor)
        assert ("奔驰", "bēnchí") in pairs
        assert ("跑", "pǎo") in pairs  # 旧行保留
        assert len(pairs) == 4

    def test_load_skips_overlong_pinyin(self, wordforms_env):
        """超长拼音（>80 字符，zh_dict VARCHAR(128) 容得下）跳过，不截断不入库。

        注：zh_dict_entries.lemma 是 VARCHAR(64)，词目天然 < 80 —— 超长
        词目守卫是防御性的，经真实数据链（zh_dict 来源）不可触达，故本
        用例只覆盖拼音侧超长。
        """
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO zh_dict_entries (lemma, pinyin, pos, erhua) "
                "VALUES (%s, %s, '拟声', 0)",
                ("短", "h" * 81),
            )
        inserted = load_pinyin_from_zh_dict()
        assert inserted == 3  # 超长拼音词条跳过，只灌原 3 条
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            pairs = _wf_rows(cursor)
        assert all(len(form) <= MAX_FORM_LEN for _, form in pairs)
        assert ("短", "h" * 81) not in pairs

    def test_load_pinyin_missing_zh_dict_returns_zero(self, monkeypatch):
        """现汉词条表不存在时不抛异常，返回已灌行数（error 日志落地）。"""
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
            pytest.skip(f"当前 MySQL 账号无建库权限: {e}")
        cur.close()
        conn.close()
        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_wordforms_tables()  # 只有 wordforms，不建 zh_dict_entries
        assert load_pinyin_from_zh_dict() == 0  # 输入源缺失 → 0（不抛）
        try:
            conn = pymysql.connect(
                host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
                password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
                cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
                autocommit=True,
            )
            conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # --- 词形还原 ---

    def test_resolve_form_exact(self, wordforms_env):
        """resolve_form 精确命中：form → lemma 行（含 kind/created_at）。"""
        load_pinyin_from_zh_dict()
        hits = resolve_form("píngguǒ")
        assert len(hits) == 1
        row = hits[0]
        assert row["lemma_word"] == "苹果"
        assert row["form"] == "píngguǒ"
        assert row["kind"] == "pinyin"
        assert row["id"] > 0
        assert row["created_at"] is not None

    def test_resolve_form_tone_sensitive(self, wordforms_env):
        """utf8mb4_bin：声调符号敏感 —— 'pao' 查不到 'pǎo'（查调口径）。"""
        load_pinyin_from_zh_dict()
        assert resolve_form("pao") == []
        assert resolve_form("pǎo") != []
        assert resolve_form(" pingguo") == []  # 带空格的原始串（strip 后仍不匹配）
        assert resolve_form("píngguǒ ") != []  # 入参去空白后精确命中

    def test_resolve_form_multi_hits(self, wordforms_env):
        """同 form 多词目 → 全部返回；不同 kind 同 form 也全部返回。"""
        load_pinyin_from_zh_dict()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO zh_dict_entries (lemma, pinyin, pos, erhua) "
                "VALUES (%s, %s, '名', 0)",
                ("平果", "píngguǒ"),
            )
        load_pinyin_from_zh_dict()  # 增量：只灌新的 平果 行
        hits = resolve_form("píngguǒ")
        assert {h["lemma_word"] for h in hits} == {"苹果", "平果"}
        # 不同 kind：variant 词形同 form 也应一并还原
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO wordforms (lemma_word, form, kind) "
                "VALUES (%s, %s, %s)",
                ("苹果", "píngguǒ", "variant"),
            )
        hits = resolve_form("píngguǒ")
        kinds = {h["kind"] for h in hits}
        assert kinds == {"pinyin", "variant"}
        assert len(hits) == 3

    def test_resolve_form_case_sensitive(self, wordforms_env):
        """utf8mb4_bin：拉丁字母大小写敏感（'Pao' ≠ 'pao'）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO wordforms (lemma_word, form, kind) VALUES (%s, %s, %s)",
                ("B超", "B chāo", "pinyin"),
            )
        assert len(resolve_form("B chāo")) == 1
        assert resolve_form("b chāo") == []

    # --- plan_pinyin_load（脚本 --dry-run 口径，只读）---

    def test_plan_matches_load(self, wordforms_env):
        """plan 的 would_add 与真实灌入一致；灌后 would_add=0。"""
        plan = plan_pinyin_load()
        assert plan["candidates"] == 3
        assert plan["existing"] == 0
        assert plan["would_add"] == 3
        assert load_pinyin_from_zh_dict() == 3
        plan_after = plan_pinyin_load()
        assert plan_after["candidates"] == 3
        assert plan_after["existing"] == 3
        assert plan_after["would_add"] == 0
