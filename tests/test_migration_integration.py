"""
结构迁移的**真实数据库**集成测试。

`test_schema.py` 用假游标验证「迁移发了哪些 SQL」；这里进一步在**真的 MySQL** 上
建一个 v1 结构的库、灌入业务数据，然后跑迁移，断言：

  * 业务数据（definitions / feedbacks / usage_logs）**一行不丢**、原文不变；
  * 旧表 synonyms / statistics 被删除，新表 word_clusters / word_relations 建出来；
  * definitions 补上 cluster_id；
  * 迁移是**幂等**的 —— 连跑三次，结果与跑一次完全一致。

没有可用的 MySQL 时整个模块 skip，所以 CI（无数据库）依然全绿。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402


TEST_DB = "web_word_migration_test"


# v1 结构：definitions 无 cluster_id，带 synonyms 与 statistics
V1_DDL = [
    """CREATE TABLE definitions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL UNIQUE,
        chinese_ndef TEXT NOT NULL,
        semantic_table JSON NOT NULL,
        example_sentence TEXT,
        model_version VARCHAR(50) DEFAULT 'zhipu-glm-4',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_definitions_verb (verb(50)),
        INDEX idx_definitions_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE synonyms (
        id INT AUTO_INCREMENT PRIMARY KEY,
        original_verb_id INT NOT NULL,
        synonym_verb VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (original_verb_id) REFERENCES definitions(id) ON DELETE CASCADE,
        INDEX idx_synonyms_original (original_verb_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE feedbacks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        rating INT NOT NULL,
        feedback_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_feedbacks_verb (verb(50))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE usage_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        device_info VARCHAR(255),
        INDEX idx_usage_logs_verb (verb(50))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE statistics (
        id INT AUTO_INCREMENT PRIMARY KEY,
        stat_name VARCHAR(50) NOT NULL UNIQUE,
        stat_value TEXT NOT NULL,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]

# 迁移后必须原样保留的业务数据
SEED_DEFS = [
    (1, "abandon", "〔某人〕舍弃〔汽车；房子等〕", '{"manner":"x"}', "He abandoned the car."),
    (2, "desert", "抛弃", '{"manner":"y"}', ""),
    (3, "leave", "离开", '{"manner":"z"}', ""),
]


def _server_conn():
    """连到 MySQL 服务器（不指定库），拿不到连接就跳过整个模块。"""
    import pymysql
    from pymysql.cursors import DictCursor

    try:
        return pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=DictCursor,
            connect_timeout=3,
        )
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"MySQL 不可用，跳过迁移集成测试: {e}")


@pytest.fixture
def v1_database(monkeypatch):
    """
    建一个 v1 结构的库并灌入业务数据，测试结束后删掉。

    同时把 db.MYSQL_DATABASE 指过去 —— init_database / get_db_cursor 都读模块全局，
    所以 monkeypatch 就够了，不需要动环境变量（它在 import 时已经被读走了）。

    如果当前账号没有建库权限（很常见：生产账号只被授权到具体某个库），就 skip ——
    这是环境能力问题，不是代码缺陷，不该让测试红。本地要跑这个测试，先授权：

        mysql -u root -e "CREATE DATABASE IF NOT EXISTS web_word_migration_test; \\
                          GRANT ALL ON web_word_migration_test.* TO 'web_word_user'@'%';"
    """
    conn = _server_conn()
    cur = conn.cursor()
    import pymysql

    try:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    except pymysql.err.OperationalError as e:
        conn.close()
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过迁移集成测试: {e}")
    cur.execute(f"USE {TEST_DB}")
    for ddl in V1_DDL:
        cur.execute(ddl)
    cur.executemany(
        """INSERT INTO definitions
           (id, verb, chinese_ndef, semantic_table, example_sentence)
           VALUES (%s, %s, %s, %s, %s)""",
        SEED_DEFS,
    )
    cur.executemany(
        "INSERT INTO synonyms (original_verb_id, synonym_verb) VALUES (%s, %s)",
        [(1, "desert"), (2, "abandon"), (1, "leave"), (3, "abandon")],
    )
    cur.execute("INSERT INTO feedbacks (verb, rating, feedback_text) VALUES ('abandon', 5, '很好')")
    cur.executemany("INSERT INTO usage_logs (verb) VALUES (%s)", [("abandon",), ("desert",)])
    cur.execute("INSERT INTO statistics (stat_name, stat_value) VALUES ('total', '3')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)

    yield TEST_DB

    conn = _server_conn()
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.commit()
    conn.close()


def _tables():
    with db.get_db_cursor() as c:
        c.execute(
            """SELECT TABLE_NAME AS t FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = %s""",
            (db.MYSQL_DATABASE,),
        )
        return {r["t"] for r in c.fetchall()}


def _scalar(sql, args=None):
    with db.get_db_cursor() as c:
        c.execute(sql, args or ())
        return c.fetchone()


class TestMigrationOnRealV1Database:
    def test_migration_succeeds(self, v1_database):
        assert db.init_database(max_retries=1) is True

    def test_business_rows_survive_verbatim(self, v1_database):
        """迁移最要紧的一条：业务数据一行不丢、内容不变。"""
        db.init_database(max_retries=1)

        rows = _scalar("SELECT COUNT(*) AS n FROM definitions")["n"]
        assert rows == len(SEED_DEFS)

        # 逐行核对原文，而不只是数目
        with db.get_db_cursor() as c:
            c.execute("SELECT id, verb, chinese_ndef FROM definitions ORDER BY id")
            got = [(r["id"], r["verb"], r["chinese_ndef"]) for r in c.fetchall()]
        assert got == [(i, v, cn) for i, v, cn, _, _ in SEED_DEFS]

        assert _scalar("SELECT COUNT(*) AS n FROM feedbacks")["n"] == 1
        assert _scalar("SELECT COUNT(*) AS n FROM usage_logs")["n"] == 2

    def test_legacy_tables_are_gone(self, v1_database):
        db.init_database(max_retries=1)
        tables = _tables()
        assert "synonyms" not in tables
        assert "statistics" not in tables

    def test_new_tables_and_view_exist(self, v1_database):
        db.init_database(max_retries=1)
        tables = _tables()
        assert {"word_clusters", "word_relations", "schema_migrations"} <= tables
        assert "v_cluster_complete_graph" in tables

    def test_cluster_id_column_added(self, v1_database):
        db.init_database(max_retries=1)
        with db.get_db_cursor() as c:
            c.execute(
                """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'definitions'
                     AND COLUMN_NAME = 'cluster_id'""",
                (db.MYSQL_DATABASE,),
            )
            assert c.fetchone()["n"] == 1
            # 老数据没有簇，应为 NULL 而不是被填成 0/空串
            assert _scalar("SELECT COUNT(*) AS n FROM definitions WHERE cluster_id IS NULL")["n"] == 3

    def test_schema_version_recorded(self, v1_database):
        db.init_database(max_retries=1)
        assert _scalar("SELECT MAX(version) AS v FROM schema_migrations")["v"] == db.SCHEMA_VERSION

    def test_idempotent_across_repeated_runs(self, v1_database):
        """连跑三次必须与跑一次完全等价 —— 迁移会在每次启动时执行。"""
        db.init_database(max_retries=1)
        with db.get_db_cursor() as c:
            c.execute("SELECT COUNT(*) AS n FROM schema_migrations")
            migrations_after_first = c.fetchone()["n"]

        for _ in range(3):
            assert db.init_database(max_retries=1) is True

        assert _scalar("SELECT COUNT(*) AS n FROM schema_migrations")["n"] == migrations_after_first
        assert _scalar("SELECT COUNT(*) AS n FROM definitions")["n"] == len(SEED_DEFS)
        assert _scalar("SELECT COUNT(*) AS n FROM feedbacks")["n"] == 1

    def test_word_relations_rejects_duplicate_and_reversed_pairs(self, v1_database):
        """两大结构约束：无向边只能存一份、同一条边不能重复。"""
        db.init_database(max_retries=1)
        cid = db.get_or_create_cluster("测试类", "测试簇")
        assert cid is not None
        for verb, ndef in (("aa", "甲"), ("bb", "乙")):
            assert db.insert_definition(verb, ndef, {"manner": "m"}, cluster_id=cid) is True

        with db.get_db_cursor() as c:
            c.execute("SELECT id FROM definitions WHERE verb IN ('aa','bb') ORDER BY verb")
            ids = [r["id"] for r in c.fetchall()]
        lo, hi = sorted(ids)

        import pymysql

        # MySQL 对不同约束报不同的错误类：唯一键是 IntegrityError(1062)，
        # CHECK 是 3819（pymysql 归到 OperationalError）。这里按「被拒绝」断言，
        # 并核对确实是预期的那条约束，而不是别的错误撞上来。
        def _violation(sql, args):
            with db.get_db_cursor() as c:
                try:
                    c.execute(sql, args)
                except (pymysql.err.IntegrityError, pymysql.err.OperationalError) as e:
                    return e
            return None

        with db.get_db_cursor() as c:
            c.execute(
                "INSERT INTO word_relations (verb_a_id, verb_b_id) VALUES (%s, %s)",
                (lo, hi),
            )

        dup = _violation(
            "INSERT INTO word_relations (verb_a_id, verb_b_id) VALUES (%s, %s)", (lo, hi)
        )
        assert dup is not None, "同一对无向边被重复插入了 —— uq_word_relations_pair 没生效"
        assert "uq_word_relations_pair" in str(dup) or dup.args[0] == 1062

        reversed_pair = _violation(
            "INSERT INTO word_relations (verb_a_id, verb_b_id) VALUES (%s, %s)", (hi, lo)
        )
        assert reversed_pair is not None, "反序边被插入了 —— CHECK(a < b) 没生效"
        assert "chk_word_relations_order" in str(reversed_pair)


class TestViewMatchesMaterializedTable:
    """视图（由簇推导）与物化表必须给出同一张图。"""

    def test_edge_counts_agree_after_seeding(self, v1_database):
        db.init_database(max_retries=1)
        cid = db.get_or_create_cluster("测试类", "三点簇")
        for verb in ("a1", "a2", "a3"):
            db.insert_definition(verb, "释义", {"manner": "m"}, cluster_id=cid)
        db.replace_word_relations(
            [("a1", "a2", "近义", "测试类 / 三点簇"),
             ("a1", "a3", "近义", "测试类 / 三点簇"),
             ("a2", "a3", "近义", "测试类 / 三点簇")]
        )

        materialized = _scalar("SELECT COUNT(*) AS n FROM word_relations")["n"]
        derived = _scalar("SELECT COUNT(*) AS n FROM v_cluster_complete_graph")["n"]
        assert materialized == derived == 3

    def test_replace_is_not_accumulative(self, v1_database):
        """整批替换语义：重复灌库不应让边数翻倍。"""
        db.init_database(max_retries=1)
        cid = db.get_or_create_cluster("测试类", "两点簇")
        for verb in ("b1", "b2"):
            db.insert_definition(verb, "释义", {"manner": "m"}, cluster_id=cid)
        rels = [("b1", "b2", "近义", "测试类 / 两点簇")]

        assert db.replace_word_relations(rels) == 1
        assert db.replace_word_relations(rels) == 1
        assert _scalar("SELECT COUNT(*) AS n FROM word_relations")["n"] == 1


class TestDefinitionClusterPreservation:
    """LLM 实时生成释义时不带簇信息，不能把已建立的簇归属抹掉。"""

    def test_insert_without_cluster_keeps_existing(self, v1_database):
        db.init_database(max_retries=1)
        cid = db.get_or_create_cluster("测试类", "保留簇")
        db.insert_definition("cc", "初次", {"manner": "m"}, cluster_id=cid)
        assert _scalar("SELECT cluster_id AS c FROM definitions WHERE verb='cc'")["c"] == cid

        # 模拟 LLM 路径：同一动词再写一次，不传 cluster_id
        db.insert_definition("cc", "模型重写", {"manner": "m2"})
        row = _scalar("SELECT chinese_ndef AS n, cluster_id AS c FROM definitions WHERE verb='cc'")
        assert row["n"] == "模型重写"      # 内容被更新
        assert row["c"] == cid             # 但簇归属保留

    def test_insert_with_cluster_overrides(self, v1_database):
        db.init_database(max_retries=1)
        c1 = db.get_or_create_cluster("测试类", "簇一")
        c2 = db.get_or_create_cluster("测试类", "簇二")
        db.insert_definition("dd", "x", {"manner": "m"}, cluster_id=c1)
        db.insert_definition("dd", "x", {"manner": "m"}, cluster_id=c2)
        assert _scalar("SELECT cluster_id AS c FROM definitions WHERE verb='dd'")["c"] == c2
