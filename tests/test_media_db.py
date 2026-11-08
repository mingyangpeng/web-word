"""媒体资产域模块测试（src/media_db.py）。

两层结构，与 tests/test_users_db.py 既有约定一致：

  * 入参守卫（license 必填 / kind 与四锚枚举 / 超长与非法值）在应用层
    先拒、不碰数据库 —— 本地与 CI 全跑；
  * 数据层 CRUD（ensure_media_tables / register_asset / bind_asset /
    list_assets_for_anchor）依赖真实 MySQL —— 连不上或账号无建库权限
    就 skip（类级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_media_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，
跑完 DROP。库名按模块预授权（scripts/grant_local_mysql.sql 模式）；
无该库名授权的环境（CI 常见）自动 skip。

覆盖面（阶段1施工规范对 Agent E 的要求）：
  许可必填拒绝 / sha256 去重（同内容返回已有 id）/ 绑定四锚与 UNIQUE /
  list_assets_for_anchor 排序与字段 / 资产级联删除 / status 审定三态。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.media_db import (  # noqa: E402
    KINDS,
    MEDIA_ANCHOR_TYPES,
    MEDIA_STATUSES,
    PURPOSES,
    bind_asset,
    ensure_media_tables,
    list_assets_for_anchor,
    register_asset,
)

TEST_DB = "web_word_media_test"

# 一个 1x1 PNG 的最小合法字节（内容哈希测试用；register 只读字节算 sha256）
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_png(tmp_path, name="pic.png", payload=PNG_BYTES):
    """临时图片文件（内容可定制以测 sha256 去重/不同内容）。"""
    p = tmp_path / name
    p.write_bytes(payload)
    return str(p)


# ============================================
# 入参守卫（应用层先拒，不碰数据库 —— CI 必跑）
# ============================================

class TestGuards:
    """register_asset / bind_asset / list_assets_for_anchor 的应用层守卫。"""

    def test_license_required_rejected(self, tmp_path):
        """许可必填：空/纯空白 license 拒绝（不碰库，返回 0）。"""
        path = _write_png(tmp_path)
        assert register_asset(path, "image", "src", "") == 0
        assert register_asset(path, "image", "src", "   \n\t ") == 0
        assert register_asset(path, "image", "src", None) == 0  # type: ignore[arg-type]

    def test_license_too_long_rejected(self, tmp_path):
        """license 超 120 字符拒绝（VARCHAR(120) 上限，应用层先拒）。"""
        path = _write_png(tmp_path)
        assert register_asset(path, "image", "src", "许" * 121) == 0

    def test_invalid_kind_rejected(self, tmp_path):
        """kind 须 ∈ {image,audio,video}，非法值不进库。"""
        path = _write_png(tmp_path)
        assert register_asset(path, "gif", "src", "许可") == 0
        assert register_asset(path, "", "src", "许可") == 0
        assert register_asset(path, None, "src", "许可") == 0  # type: ignore[arg-type]

    def test_missing_file_rejected(self, tmp_path):
        """文件不存在/不可读拒绝（sha256 无从算起）。"""
        assert register_asset(str(tmp_path / "nope.png"), "image", "src", "许可") == 0
        assert register_asset("", "image", "src", "许可") == 0

    def test_invalid_source_rejected(self, tmp_path):
        """source 非 str 拒绝；空串允许（存 ''）。"""
        path = _write_png(tmp_path)
        assert register_asset(
            path, "image", 123, "许可",  # type: ignore[arg-type]
        ) == 0

    def test_bind_invalid_enum_rejected(self):
        """bind_asset 非法 anchor_type/purpose/status 在应用层拒绝。"""
        assert bind_asset(1, "lemma", 1, "illustration") is False
        assert bind_asset(1, "word", 1, "decoration") is False
        assert bind_asset(1, "word", 1, "illustration", status="待定") is False
        assert bind_asset(
            1, "word", 1, "illustration", caption=None,  # type: ignore[arg-type]
        ) is False

    def test_bind_invalid_ids_rejected(self):
        """bind_asset 非法 id（0/负数/非整数）拒绝。"""
        assert bind_asset(0, "word", 1, "illustration") is False
        assert bind_asset(-1, "word", 1, "illustration") is False
        assert bind_asset("x", "word", 1, "illustration") is False  # type: ignore[arg-type]
        assert bind_asset(1, "word", 0, "illustration") is False
        assert bind_asset(1, "word", -5, "illustration") is False

    def test_list_invalid_args_rejected(self):
        """list_assets_for_anchor 非法锚/锚 id 返回 []。"""
        assert list_assets_for_anchor("lemma", 1) == []
        assert list_assets_for_anchor("word", 0) == []
        assert list_assets_for_anchor("word", "abc") == []  # type: ignore[arg-type]

    def test_constants_match_contract(self):
        """四锚/三用途/三状态/三类资产与契约 §3-E 枚举一致。"""
        assert KINDS == ("image", "audio", "video")
        assert MEDIA_ANCHOR_TYPES == ("word", "sense", "example", "schema")
        assert PURPOSES == (
            "pronunciation", "illustration", "example_media", "schema_diagram",
        )
        assert MEDIA_STATUSES == ("候选", "审定", "发布")  # R6-6 域前缀


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
def media_env(monkeypatch):
    """建空测试库并让 media 模块指向它，测试结束 DROP。

    与 test_users_db.py 同一手法：get_db_cursor 在调用时读 mysql_db
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
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过 media 集成测试: {e}")
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


def _count(cursor, table):
    cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
    return int(cursor.fetchone()["n"] or 0)


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 media 数据层集成测试")
class TestMediaIntegration:
    """media 两表 CRUD（跑在独立测试库 web_word_media_test）。"""

    # --- 建表 ---

    def test_ensure_idempotent(self, media_env):
        """ensure 重复调用幂等（CREATE TABLE IF NOT EXISTS）。"""
        ensure_media_tables()
        ensure_media_tables()
        ensure_media_tables()
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME IN ('media_assets', 'media_bindings')"""
            )
            assert int(cursor.fetchone()["n"] or 0) == 2

    # --- register_asset ---

    def test_register_returns_id_and_fields(self, media_env, tmp_path):
        """登记返回 id；size_bytes/mime 推断/license/status 入库正确。"""
        ensure_media_tables()
        path = _write_png(tmp_path)
        asset_id = register_asset(path, "image", "测试来源", "CC BY 4.0")
        assert isinstance(asset_id, int) and asset_id > 0
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM media_assets WHERE id = %s", (asset_id,))
            row = cursor.fetchone()
        assert row["kind"] == "image"
        assert row["file_path"] == path
        assert row["mime"] == "image/png"            # 扩展名推断
        assert len(row["sha256"]) == 64
        assert row["source"] == "测试来源"
        assert row["license"] == "CC BY 4.0"
        assert int(row["size_bytes"]) == len(PNG_BYTES)
        assert row["status"] == "候选"               # 默认候选

    def test_register_license_stripped(self, media_env, tmp_path):
        """license 首尾空白去除后入库（非空校验在去空白后做）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "  CC0  ")
        assert asset_id > 0
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT license FROM media_assets WHERE id = %s", (asset_id,))
            assert cursor.fetchone()["license"] == "CC0"

    def test_register_sha256_dedup(self, media_env, tmp_path):
        """sha256 去重：同内容不同文件名返回已有 id，库中仍一行。"""
        ensure_media_tables()
        id1 = register_asset(_write_png(tmp_path, "a.png"), "image", "s", "CC0")
        id2 = register_asset(_write_png(tmp_path, "b.png"), "image", "s", "CC0")
        assert id1 > 0
        assert id2 == id1  # 重复返回已有 id
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            assert _count(cursor, "media_assets") == 1

    def test_register_different_content_new_id(self, media_env, tmp_path):
        """不同内容 → 不同资产（sha256 唯一不去重合法新增）。"""
        ensure_media_tables()
        id1 = register_asset(_write_png(tmp_path, "a.png"), "image", "s", "CC0")
        id2 = register_asset(
            _write_png(tmp_path, "b.png", payload=PNG_BYTES + b"tail"),
            "image", "s", "CC0",
        )
        assert id1 != id2

    def test_register_rejects_empty_license_no_row(self, media_env, tmp_path):
        """许可必填是硬约束：拒绝后库中无行（不只是返回 0）。"""
        ensure_media_tables()
        path = _write_png(tmp_path)
        assert register_asset(path, "image", "s", "") == 0
        assert register_asset(path, "image", "s", "  ") == 0
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            assert _count(cursor, "media_assets") == 0

    def test_register_mime_override(self, media_env, tmp_path):
        """显式 mime 覆盖扩展名推断；空串 mime 存 NULL（内容须互异防 sha 去重）。"""
        ensure_media_tables()
        id1 = register_asset(_write_png(tmp_path, "a.png"), "image", "s", "CC0",
                             mime="image/x-custom")
        id2 = register_asset(
            _write_png(tmp_path, "b.png", payload=PNG_BYTES + b"x"), "image", "s",
            "CC0", mime="   ",
        )
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT id, mime FROM media_assets ORDER BY id")
            rows = {r["id"]: r["mime"] for r in cursor.fetchall()}
        assert rows[id1] == "image/x-custom"
        assert rows[id2] is None

    # --- bind_asset：四锚 ---

    def test_bind_four_anchor_types(self, media_env, tmp_path):
        """同一资产可绑四类锚（word/sense/example/schema 各一行）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0")
        anchors = [
            ("word", 11), ("sense", 22), ("example", 33), ("schema", 44),
        ]
        for anchor_type, anchor_id in anchors:
            assert bind_asset(asset_id, anchor_type, anchor_id, "illustration") is True
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT anchor_type, anchor_id FROM media_bindings ORDER BY id"
            )
            assert [(r["anchor_type"], int(r["anchor_id"]))
                    for r in cursor.fetchall()] == anchors

    def test_bind_unique_idempotent(self, media_env, tmp_path):
        """UNIQUE(asset_id, anchor_type, anchor_id, purpose)：重复绑定返回
        True 且不新插行（幂等命中保留首次值）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0")
        assert bind_asset(asset_id, "word", 1, "illustration",
                          caption="第一次", sort_order=3, status="审定") is True
        assert bind_asset(asset_id, "word", 1, "illustration",
                          caption="第二次", sort_order=9, status="候选") is True
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM media_bindings")
            rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["caption"] == "第一次"   # 保留首次绑定值
        assert int(rows[0]["sort_order"]) == 3
        assert rows[0]["status"] == "审定"

    def test_bind_same_anchor_different_purpose(self, media_env, tmp_path):
        """同资产同锚不同用途是两条合法绑定（UNIQUE 含 purpose）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0")
        assert bind_asset(asset_id, "word", 1, "illustration") is True
        assert bind_asset(asset_id, "word", 1, "schema_diagram") is True
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            assert _count(cursor, "media_bindings") == 2

    def test_bind_nonexistent_asset_rejected(self, media_env):
        """绑到不存在的资产返回 False（应用层先查，FK 兜底）。"""
        ensure_media_tables()
        assert bind_asset(999999, "word", 1, "illustration") is False

    def test_bind_status_enum(self, media_env, tmp_path):
        """status 审定三态（候选/审定/发布）合法，其余拒绝。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0")
        assert bind_asset(asset_id, "word", 1, "illustration", status="发布") is True
        assert bind_asset(asset_id, "word", 2, "illustration", status="审定") is True
        assert bind_asset(asset_id, "word", 3, "illustration", status="草稿") is False
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("SELECT DISTINCT status FROM media_bindings")
            assert {r["status"] for r in cursor.fetchall()} == {"发布", "审定"}

    # --- list_assets_for_anchor ---

    def test_list_orders_by_sort_order(self, media_env, tmp_path):
        """list 按 sort_order, id 稳定排序（装配确定性）。"""
        ensure_media_tables()
        id_a = register_asset(_write_png(tmp_path, "a.png"), "image", "s", "CC0")
        id_b = register_asset(_write_png(tmp_path, "b.png",
                                         payload=PNG_BYTES + b"b"), "image", "s", "CC0")
        id_c = register_asset(_write_png(tmp_path, "c.png",
                                         payload=PNG_BYTES + b"c"), "image", "s", "CC0")
        assert bind_asset(id_a, "word", 7, "illustration", sort_order=2) is True
        assert bind_asset(id_b, "word", 7, "illustration", sort_order=1) is True
        assert bind_asset(id_c, "word", 7, "illustration", sort_order=2) is True
        rows = list_assets_for_anchor("word", 7)
        assert [(r["asset_id"], int(r["sort_order"])) for r in rows] == [
            (id_b, 1), (id_a, 2), (id_c, 2),  # 同 sort_order 按 id 升序
        ]

    def test_list_row_fields(self, media_env, tmp_path):
        """list 行含绑定+资产字段（两组状态键名区分）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0",
                                  mime="image/png")
        bind_asset(asset_id, "sense", 5, "illustration", caption="图注")
        rows = list_assets_for_anchor("sense", 5)
        assert len(rows) == 1
        row = rows[0]
        assert row["binding_id"] > 0
        assert row["asset_id"] == asset_id
        assert row["anchor_type"] == "sense"
        assert int(row["anchor_id"]) == 5
        assert row["purpose"] == "illustration"
        assert row["caption"] == "图注"
        assert row["binding_status"] == "候选"
        assert row["asset_status"] == "候选"
        assert row["kind"] == "image"
        assert row["mime"] == "image/png"
        assert row["license"] == "CC0"

    def test_list_filters_by_anchor(self, media_env, tmp_path):
        """list 只返回该锚的绑定（word 锚 ≠ sense 锚）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0")
        bind_asset(asset_id, "word", 1, "illustration")
        bind_asset(asset_id, "sense", 2, "illustration")
        assert len(list_assets_for_anchor("word", 1)) == 1
        assert len(list_assets_for_anchor("sense", 2)) == 1
        assert list_assets_for_anchor("word", 2) == []
        assert list_assets_for_anchor("example", 1) == []

    # --- 级联与清理 ---

    def test_delete_asset_cascades_bindings(self, media_env, tmp_path):
        """删资产级联删绑定（FK ON DELETE CASCADE，不留悬挂行）。"""
        ensure_media_tables()
        asset_id = register_asset(_write_png(tmp_path), "image", "s", "CC0")
        bind_asset(asset_id, "word", 1, "illustration")
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute("DELETE FROM media_assets WHERE id = %s", (asset_id,))
            cursor.execute("SELECT COUNT(*) AS n FROM media_bindings")
            assert int(cursor.fetchone()["n"] or 0) == 0
