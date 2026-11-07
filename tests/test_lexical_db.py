"""编纂成文域数据层测试（src/lexical_db.py，批次 7 Agent V）。

两层结构，与 tests/test_media_db.py 既有约定一致：

  * 入参守卫（空 sense_ref/content / 非法 source/state / 超长字段 /
    非单步流转对）在应用层先拒、不碰数据库 —— 本地与 CI 全跑；
  * 数据层 CRUD（ensure_lexical_tables / add_example / list_examples /
    update_example / remove_example / advance_example_status /
    bind_example_media / set_translation / get_translation）依赖真实
    MySQL —— 连不上就 skip（类级 skipif），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_lexical_test（monkeypatch db.MYSQL_DATABASE
指向它，库名按模块预授权 scripts/grant_local_mysql.sql 模式），每个测试
重建，跑完 DROP。媒体绑定委托用 monkeypatch 换掉 media_db.bind_asset
断言调用参数（不复制其逻辑）；另有一条真实链路用例（register_asset 真图
→ 绑定 → media_bindings 落行）。

覆盖面（阶段1施工规范 §10-V）：
  例证 CRUD 与物理删除 / 审定三态单步流转乐观守卫 / 对译三态 upsert
  （finalized_by/at 落库、一义位一稿）/ 媒体例证绑定委托与回写。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.lexical_db import (  # noqa: E402
    EXAMPLE_SOURCES,
    EXAMPLE_STATUSES,
    TRANSLATION_STATES,
    add_example,
    advance_example_status,
    bind_example_media,
    ensure_lexical_tables,
    get_translation,
    list_examples,
    remove_example,
    set_translation,
    update_example,
)

TEST_DB = "web_word_lexical_test"


# ============================================
# 入参守卫（应用层先拒，不碰数据库 —— CI 必跑）
# ============================================

class TestGuards:
    """add/update/remove/advance/set_translation/get_translation 的应用层守卫。"""

    def test_add_invalid_ref_rejected(self):
        """sense_ref 必须是非空、≤60 字符的 str。"""
        assert add_example("", "例句") == 0
        assert add_example("   \n\t ", "例句") == 0
        assert add_example("#" * 61, "例句") == 0
        assert add_example(None, "例句") == 0  # type: ignore[arg-type]
        assert add_example(12, "例句") == 0  # type: ignore[arg-type]

    def test_add_invalid_content_rejected(self):
        """content 必填（非空 str，去空白后非空）。"""
        assert add_example("s1", "") == 0
        assert add_example("s1", "   \n ") == 0
        assert add_example("s1", None) == 0  # type: ignore[arg-type]
        assert add_example("s1", 42) == 0  # type: ignore[arg-type]

    def test_add_invalid_source_caption_order_rejected(self):
        """source ∈ 三枚举；caption ≤255；sort_order 须可转 int。"""
        assert add_example("s1", "例句", source="quote") == 0
        assert add_example("s1", "例句", source="") == 0
        assert add_example("s1", "例句", source=None) == 0  # type: ignore[arg-type]
        assert add_example("s1", "例句", caption="#" * 256) == 0
        assert add_example("s1", "例句", caption=123) == 0  # type: ignore[arg-type]
        assert add_example("s1", "例句", sort_order="x") == 0
        assert add_example("s1", "例句", sort_order=None) == 0

    def test_add_invalid_creator_rejected(self):
        """created_by 给出须为正整数（None=系统登记允许；bool 拒绝）。"""
        assert add_example("s1", "例句", created_by=0) == 0
        assert add_example("s1", "例句", created_by=-3) == 0
        assert add_example("s1", "例句", created_by="x") == 0
        assert add_example("s1", "例句", created_by=True) == 0

    def test_update_invalid_args_rejected(self):
        """update_example：非法 id / 无字段 / 空 content / 非法 source / 超长。"""
        assert update_example(0, content="x") is False
        assert update_example(-1, content="x") is False
        assert update_example("x", content="x") is False  # type: ignore[arg-type]
        assert update_example(1) is False  # 无可更新字段
        assert update_example(1, content="  ") is False
        assert update_example(1, content="x", source="wrong") is False
        assert update_example(1, caption="#" * 256) is False
        assert update_example(1, sort_order="x") is False

    def test_remove_and_advance_invalid_ids_rejected(self):
        """remove/advance 的 id 守卫。"""
        assert remove_example(0) is False
        assert remove_example(-2) is False
        assert remove_example("x") is False  # type: ignore[arg-type]
        assert advance_example_status(0, "候选", "审定") is False
        assert advance_example_status("x", "候选", "审定") is False  # type: ignore[arg-type]

    def test_advance_rejects_non_single_step_pairs(self):
        """审定链逐级单步：跳级/回退/终态再流一律拒绝（不碰库）。"""
        assert advance_example_status(1, "候选", "发布") is False      # 跳级
        assert advance_example_status(1, "审定", "候选") is False      # 回退
        assert advance_example_status(1, "发布", "审定") is False      # 终态
        assert advance_example_status(1, "候选", "候选") is False      # 原地
        assert advance_example_status(1, "草稿", "审定") is False      # 非法态
        assert advance_example_status(1, "候选", "待定") is False      # 非法态

    def test_set_translation_invalid_args_rejected(self):
        """set_translation：非法 ref/state/超长 equivalent/note/paraphrase 型。"""
        assert set_translation("", "full") is False
        assert set_translation("   ", "full") is False
        assert set_translation("#" * 61, "full") is False
        assert set_translation("s1", "exact") is False        # 非法三态
        assert set_translation("s1", "") is False
        assert set_translation("s1", None) is False  # type: ignore[arg-type]
        assert set_translation("s1", "full", equivalent="#" * 256) is False
        assert set_translation("s1", "full", note="#" * 501) is False
        assert set_translation("s1", "none", paraphrase=42) is False  # type: ignore[arg-type]
        assert set_translation("s1", "full", finalized_by=0) is False
        assert set_translation("s1", "full", finalized_by=True) is False

    def test_get_translation_invalid_ref_returns_none(self):
        """非法 sense_ref 一律 None（不抛异常）。"""
        assert get_translation("") is None
        assert get_translation("#" * 61) is None
        assert get_translation(None) is None  # type: ignore[arg-type]
        assert get_translation(7) is None  # type: ignore[arg-type]

    def test_bind_invalid_ids_rejected(self):
        """bind_example_media 的 id 守卫（不碰库）。"""
        assert bind_example_media(0, 1, "") is False
        assert bind_example_media(1, 0, "") is False
        assert bind_example_media(-1, 1, "") is False
        assert bind_example_media("x", 1, "") is False  # type: ignore[arg-type]
        assert bind_example_media(1, True, "") is False  # bool 拒绝

    def test_constants_match_contract(self):
        """三来源/三审定态/对译三态与契约 §10-V 枚举一致。"""
        assert EXAMPLE_SOURCES == ("corpus", "adapted", "composed")
        assert EXAMPLE_STATUSES == ("候选", "审定", "发布")
        assert TRANSLATION_STATES == ("full", "partial", "none")


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
def lexical_env(monkeypatch):
    """建空测试库并让 lexical 模块指向它，测试结束 DROP。

    与 test_media_db.py 同一手法：get_db_cursor 在调用时读 mysql_db
    模块全局，monkeypatch MYSQL_DATABASE 即可；账号无该库名授权则 skip。
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
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过 lexical 集成测试: {e}")
    conn.close()

    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
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


def _count(cursor, table, where="1=1", params=()):
    cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)
    return int(cursor.fetchone()["n"] or 0)


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 lexical 数据层集成测试")
class TestLexicalIntegration:
    """sense_examples / sense_translations 两表 CRUD（独立测试库）。"""

    # --- 建表 ---

    def test_ensure_idempotent(self, lexical_env):
        """ensure 重复调用幂等（CREATE TABLE IF NOT EXISTS）。"""
        ensure_lexical_tables()
        ensure_lexical_tables()
        ensure_lexical_tables()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME IN ('sense_examples', 'sense_translations')"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 2

    # --- add / list ---

    def test_add_defaults_and_list_roundtrip(self, lexical_env):
        """新增默认值（corpus/候选/''/0）与列表回读字段齐全。"""
        ensure_lexical_tables()
        eid = add_example("12", "The dog ran across the field.",
                          caption="enTenTen21", created_by=3)
        assert isinstance(eid, int) and eid > 0
        rows = list_examples("12")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == eid
        assert row["sense_ref"] == "12"
        assert row["content"] == "The dog ran across the field."
        assert row["source"] == "corpus"
        assert row["caption"] == "enTenTen21"
        assert row["media_asset_id"] is None
        assert row["sort_order"] == 0
        assert row["status"] == "候选"
        assert row["created_by"] == 3
        assert row["created_at"] is not None

    def test_add_content_stripped(self, lexical_env):
        """content 首尾空白去除后入库。"""
        ensure_lexical_tables()
        assert add_example("s", "  例句  ") > 0
        rows = list_examples("s")
        assert rows[0]["content"] == "例句"

    def test_list_order_by_sort_order_then_id(self, lexical_env):
        """多例证按 sort_order, id 稳定排序（装配确定性）。"""
        ensure_lexical_tables()
        a = add_example("s", "乙", sort_order=2)
        b = add_example("s", "甲一", sort_order=1)
        c = add_example("s", "甲二", sort_order=1)
        rows = list_examples("s")
        assert [r["id"] for r in rows] == [b, c, a]
        assert [r["content"] for r in rows] == ["甲一", "甲二", "乙"]

    def test_list_filters_and_isolation(self, lexical_env):
        """sense_ref/status 过滤互不串扰；无命中返回 []。"""
        ensure_lexical_tables()
        add_example("1", "甲")
        add_example("1", "乙")
        pub = add_example("2", "丙")
        assert advance_example_status(pub, "候选", "审定") is True
        assert advance_example_status(pub, "审定", "发布") is True
        assert len(list_examples("1")) == 2
        assert len(list_examples("2")) == 1
        assert list_examples("999") == []
        assert [r["id"] for r in list_examples("2", status="发布")] == [pub]
        assert list_examples("2", status="候选") == []
        assert list_examples("2", status="鬼") == []      # 非法状态拒绝
        assert list_examples("2", limit=0) == []          # 非法 limit 拒绝

    # --- update ---

    def test_update_patch_semantics(self, lexical_env):
        """Patch 语义：只改给出的字段，其余保持；caption='' 显式清空。"""
        ensure_lexical_tables()
        eid = add_example("s", "原句", caption="出处 A", sort_order=5,
                          created_by=7)
        assert update_example(eid, source="adapted") is True
        row = list_examples("s")[0]
        assert row["source"] == "adapted"
        assert row["content"] == "原句"
        assert row["caption"] == "出处 A"
        assert row["sort_order"] == 5
        assert row["created_by"] == 7
        assert update_example(eid, content="新句", caption="", sort_order=0) is True
        row = list_examples("s")[0]
        assert row["content"] == "新句"
        assert row["caption"] == ""
        assert row["sort_order"] == 0
        assert row["source"] == "adapted"
        assert update_example(eid + 1000, content="x") is False  # 行不存在

    # --- advance（单步 + 乐观守卫）---

    def test_advance_full_chain_then_terminal(self, lexical_env):
        """候选→审定→发布逐级单步；发布后终态不可再流。"""
        ensure_lexical_tables()
        eid = add_example("s", "例句")
        assert advance_example_status(eid, "候选", "发布") is False  # 跳级拒绝
        assert advance_example_status(eid, "候选", "审定") is True
        assert list_examples("s")[0]["status"] == "审定"
        assert advance_example_status(eid, "审定", "发布") is True
        assert list_examples("s")[0]["status"] == "发布"
        assert advance_example_status(eid, "审定", "发布") is False  # 已终态
        assert advance_example_status(eid, "发布", "发布") is False

    def test_advance_optimistic_guard_second_flow_loses(self, lexical_env):
        """乐观守卫：同一 from_status 的第二次流转 rowcount=0 拒绝。"""
        ensure_lexical_tables()
        eid = add_example("s", "例句")
        assert advance_example_status(eid, "候选", "审定") is True
        # 模拟另一人仍按「候选」起步流转：状态已被先行推进，必然失败
        assert advance_example_status(eid, "候选", "审定") is False
        assert list_examples("s")[0]["status"] == "审定"

    # --- remove（物理 DELETE）---

    def test_remove_is_physical_delete(self, lexical_env):
        """remove 物理删除：行消失；重复删除返回 False（软删口径见 docstring）。"""
        ensure_lexical_tables()
        eid = add_example("s", "要删的例证")
        add_example("s", "留下的例证")
        from src.mysql_db import get_db_cursor

        assert remove_example(eid) is True
        with get_db_cursor() as cursor:
            assert _count(cursor, "sense_examples",
                          "id = %s", (eid,)) == 0
            assert _count(cursor, "sense_examples") == 1
        assert remove_example(eid) is False
        remaining = list_examples("s")
        assert len(remaining) == 1
        assert remaining[0]["content"] == "留下的例证"

    # --- set_translation / get_translation（三态 upsert）---

    def test_set_translation_insert_and_upsert(self, lexical_env):
        """三态定稿：首写插行、再写覆盖（一义位一稿），finalized_by/at 刷新。"""
        ensure_lexical_tables()
        assert set_translation("12", "full", equivalent="跑",
                               note="辨析草稿", finalized_by=5) is True
        tr = get_translation("12")
        assert tr["sense_ref"] == "12"
        assert tr["state"] == "full"
        assert tr["equivalent"] == "跑"
        assert tr["note"] == "辨析草稿"
        assert tr["paraphrase"] is None
        assert tr["finalized_by"] == 5
        assert tr["finalized_at"] is not None
        assert tr["updated_at"] is not None
        # 覆盖写：改口径为 partial，equivalent/note/finalized 全刷新
        assert set_translation("12", "partial", equivalent="奔跑",
                               note="括注：强调奔", finalized_by=8) is True
        tr = get_translation("12")
        assert tr["state"] == "partial"
        assert tr["equivalent"] == "奔跑"
        assert tr["note"] == "括注：强调奔"
        assert tr["finalized_by"] == 8
        assert tr["finalized_at"] is not None
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            assert _count(cursor, "sense_translations") == 1  # UNIQUE 一义位一稿

    def test_set_translation_none_state_paraphrase(self, lexical_env):
        """none 态释义翻译：paraphrase 落库；空串按未给出（NULL）处理。"""
        ensure_lexical_tables()
        assert set_translation("s", "none",
                               paraphrase="用「奔跑」的释义直译",
                               finalized_by=2) is True
        tr = get_translation("s")
        assert tr["state"] == "none"
        assert tr["equivalent"] == ""
        assert tr["paraphrase"] == "用「奔跑」的释义直译"
        assert set_translation("s", "none", paraphrase="   ") is True
        assert get_translation("s")["paraphrase"] is None

    def test_set_translation_system_finalize(self, lexical_env):
        """finalized_by=None 允许（系统登记口径），行仍成立。"""
        ensure_lexical_tables()
        assert set_translation("s", "full", equivalent="跑") is True
        tr = get_translation("s")
        assert tr["finalized_by"] is None
        assert tr["finalized_at"] is not None

    def test_get_translation_missing_and_bad_args(self, lexical_env):
        """无定稿 / 库外 sense_ref 返回 None，不抛异常。"""
        ensure_lexical_tables()
        assert get_translation("nope") is None

    # --- bind_example_media（委托 media_db，monkeypatch 断言）---

    def test_bind_media_delegates_to_media_db(self, lexical_env, monkeypatch):
        """绑定委托 media_db.bind_asset（anchor='example'，purpose=
        example_media），成功后回写 media_asset_id——只封装不复制逻辑。"""
        ensure_lexical_tables()
        eid = add_example("s", "例句")
        calls = []

        def fake_bind(asset_id, anchor_type, anchor_id, purpose,
                      caption="", sort_order=0, status="候选"):
            calls.append({
                "asset_id": asset_id, "anchor_type": anchor_type,
                "anchor_id": anchor_id, "purpose": purpose, "caption": caption,
            })
            return True

        from src import media_db

        monkeypatch.setattr(media_db, "bind_asset", fake_bind)
        assert bind_example_media(eid, 33, "图注来源") is True
        assert len(calls) == 1
        assert calls[0] == {
            "asset_id": 33, "anchor_type": "example", "anchor_id": eid,
            "purpose": "example_media", "caption": "图注来源",
        }
        row = list_examples("s")[0]
        assert row["media_asset_id"] == 33

    def test_bind_media_media_db_false_propagates(self, lexical_env, monkeypatch):
        """media_db 拒绝（资产不存在等）→ 返回 False，media_asset_id 不回写。"""
        ensure_lexical_tables()
        eid = add_example("s", "例句")
        from src import media_db

        monkeypatch.setattr(media_db, "bind_asset",
                            lambda *a, **k: False)
        assert bind_example_media(eid, 44, "") is False
        assert list_examples("s")[0]["media_asset_id"] is None

    def test_bind_media_missing_example_never_calls_media_db(
        self, lexical_env, monkeypatch,
    ):
        """例证不存在先拒：不触达 media_db（锚存在性校验在本层）。"""
        ensure_lexical_tables()

        def explode(*a, **k):  # media_db 被触达即失败
            raise AssertionError("media_db.bind_asset 不应被调用")

        from src import media_db

        monkeypatch.setattr(media_db, "bind_asset", explode)
        assert bind_example_media(9999, 1, "") is False

    def test_bind_media_real_path_media_bindings(self, lexical_env, tmp_path):
        """真实链路：register_asset 真图 → 绑定 → media_bindings 落行
        （anchor_type='example' / purpose='example_media'）。"""
        ensure_lexical_tables()
        from src.media_db import ensure_media_tables, list_assets_for_anchor, register_asset

        ensure_media_tables()
        png = tmp_path / "pic.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        asset_id = register_asset(str(png), "image", "测试来源", "CC BY 4.0")
        assert asset_id > 0
        eid = add_example("s", "例句")
        assert bind_example_media(eid, asset_id, "配图：奔跑") is True
        bindings = list_assets_for_anchor("example", eid)
        assert len(bindings) == 1
        assert bindings[0]["asset_id"] == asset_id
        assert bindings[0]["anchor_type"] == "example"
        assert bindings[0]["purpose"] == "example_media"
        assert bindings[0]["caption"] == "配图：奔跑"
