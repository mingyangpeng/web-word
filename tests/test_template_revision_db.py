"""FX-38 模板人工修订数据层测试（src/template_revision_db.py）。

两层结构（与 test_lexical_db.py 同口径）：
  * 入参守卫 / 权限闸门类：不碰库，CI 全跑 —— PermissionError（未登录 /
    viewer / annotator）、定位三元组与文本/note/sense_ref 清洗拒收；
  * MySQL 集成类：TEST_DB 独立库（fixture DROP/CREATE + monkeypatch
    MYSQL_DATABASE），无库权限即 skip —— 建表幂等、版本原子自增、
    latest/批量/历史读面、多范畴隔离、CSV note 回填。

口径：编纂职能 editor/reviewer/dict_admin 可修订（CAN_REVISE_ROLES）；
legacy admin → dict_admin 两位一体同样放行；引擎输出为基线，修订是人工层。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql  # noqa: E402

from src import mysql_db as db  # noqa: E402
from src import template_revision_db as trd  # noqa: E402
from src.guards import require_role  # noqa: E402

TEST_DB = "web_word_template_revision_test"

EDITOR = {"id": 2, "username": "editor_x", "roles": ["editor"]}
REVIEWER = {"id": 3, "username": "reviewer_x", "roles": ["reviewer"]}
ADMIN = {"id": 1, "username": "admin", "role": "admin"}
VIEWER = {"id": 5, "username": "viewer_x", "role": "viewer"}
ANNOTATOR = {"id": 6, "username": "annotator_x", "role": "annotator"}

LOC = ("run", "en", 1)


def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不建库；仿 test_lexical_db）。"""
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


# ============================================
# a) 权限闸门（不碰库）
# ============================================
@pytest.fixture
def _forbid_db(monkeypatch):
    """守卫/清洗类**强制禁库**：save_revision 一旦越过清洗层触到 get_db_cursor
    直接抛错 → 返回 {"ok": False, "reason": "数据库写入失败"}。

    为什么必须有：全量跑时 test_page_guides 的 AppTest 会先以业务库渲染模板页、
    幂等建出 template_revisions——若不禁库，本类的探针写路径会误写业务库
    （solo 跑时表不存在恰好不写，属侥幸）。清洗拒收断言发生在碰库之前，
    禁库后逐条仍成立；落库行为断言归集成类。仅挂在本节两个类
    （usefixtures），集成类不受影响。
    """

    from contextlib import contextmanager

    @contextmanager
    def _boom(*_a, **_k):
        # 模拟连库失败：save_revision 的 except pymysql.Error 口径接住，
        # 返回 {"ok": False, "reason": "数据库写入失败"}，绝不写任何库
        raise pymysql.OperationalError(2003, "guard tests forbid DB access")
        yield  # pragma: no cover

    monkeypatch.setattr(trd, "get_db_cursor", _boom)
    yield


@pytest.mark.usefixtures("_forbid_db")
class TestSaveRevisionGuards:
    def test_none_actor_rejected(self):
        """未登录（actor=None）一律拒绝：require_role fail-closed。"""
        with pytest.raises(PermissionError):
            trd.save_revision(*LOC, "修订文本", None)

    def test_viewer_and_annotator_rejected(self):
        """viewer / annotator 无编纂职能 → PermissionError。"""
        for actor in (VIEWER, ANNOTATOR):
            with pytest.raises(PermissionError):
                trd.save_revision(*LOC, "修订文本", actor)

    def test_editor_reviewer_admin_allowed(self):
        """editor / reviewer / legacy admin（dict_admin 两位一体）过闸。

        闸门之后再因表未建（本类不建库）落库失败 → ok=False，不抛；
        此处只断言「不是 PermissionError」，落库行为归集成类。
        """
        for actor in (EDITOR, REVIEWER, ADMIN):
            result = trd.save_revision(*LOC, "守卫探针修订", actor)
            assert isinstance(result, dict)
            assert "Permission" not in str(result.get("reason", ""))


# ============================================
# b) 入参守卫（过闸后、碰库前的清洗拒收；不碰库）
# ============================================
@pytest.mark.usefixtures("_forbid_db")
class TestSaveRevisionValidation:
    def test_invalid_locate_rejected(self):
        """category/language 非法 或 sense_id 非正整数 → ok=False。"""
        for loc in ((None, "en", 1), ("run", "", 1), ("run", "en", 0),
                    ("run", "en", "x"), ("run", "en", 1.5)):
            result = trd.save_revision(*loc, "修订文本", EDITOR)
            assert result == {"ok": False, "reason": "定位参数非法（范畴/语言/义位）"}

    def test_revision_text_rejected(self):
        """修订文本：非 str / 空 / 超长 → ok=False。"""
        for text in (None, 123, "", "   ", "修" * (trd.MAX_REVISION_TEXT_LEN + 1)):
            result = trd.save_revision(*LOC, text, EDITOR)
            assert result["ok"] is False
            assert "修订文本非法" in result["reason"]

    def test_note_too_long_rejected(self):
        """优化要点超 500 字 → ok=False（空/None 合法）。"""
        result = trd.save_revision(*LOC, "修订文本", EDITOR,
                                   note="注" * (trd.MAX_NOTE_LEN + 1))
        assert result["ok"] is False and "优化要点非法" in result["reason"]
        ok = trd.save_revision(*LOC, "修订文本", EDITOR, note=None)
        # 库未建 → 落库失败，但不是入参拒收
        assert ok.get("reason") != "优化要点非法（须 ≤500 字）"

    def test_sense_ref_too_long_rejected(self):
        """sense_ref 超长 → ok=False（None 合法）。"""
        result = trd.save_revision(*LOC, "修订文本", EDITOR,
                                   sense_ref="r" * (trd.MAX_SENSE_REF_LEN + 1))
        assert result["ok"] is False and "sense_ref 非法" in result["reason"]

    def test_get_latest_revisions_invalid_ids_skipped(self):
        """批量读面：非法定位条目跳过，不抛（纯内存清洗）。"""
        assert trd.get_latest_revisions("run", "en", [0, "x", None]) == {}
        assert trd.get_latest_revisions("run", "en", []) == {}


# ============================================
# c) MySQL 集成（独立测试库；无库权限 skip）
# ============================================
@pytest.fixture
def revision_env(monkeypatch):
    """建空测试库并指向它，测试结束 DROP（仿 test_lexical_db.lexical_env）。"""
    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        connect_timeout=3,
    )
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci")
    except pymysql.err.OperationalError as e:
        conn.close()
        pytest.skip(f"当前 MySQL 账号无建库权限，跳过模板修订集成测试: {e}")
    conn.close()
    monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
    yield
    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        connect_timeout=3, autocommit=True,
    )
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.close()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用")
class TestSaveRevisionIntegration:
    def test_ensure_idempotent_and_save_version_increments(self, revision_env):
        """建表幂等；连续保存版本号单语句原子自增（1→2→3）。"""
        trd.ensure_template_revision_tables()
        trd.ensure_template_revision_tables()  # 幂等
        for expect in (1, 2, 3):
            result = trd.save_revision(
                "run", "en", 1, f"第 {expect} 版修订文本", EDITOR,
                note=f"要点{expect}", sense_ref="run1")
            assert result == {"ok": True, "version": expect}

    def test_get_latest_returns_newest(self, revision_env):
        """latest 读面取最大版本；note/sense_ref/留痕字段齐备。"""
        trd.ensure_template_revision_tables()
        trd.save_revision("run", "en", 1, "第一版", EDITOR, note="n1",
                          sense_ref="run1")
        trd.save_revision("run", "en", 1, "第二版", ADMIN, note="n2",
                          sense_ref="run1")
        latest = trd.get_latest_revision("run", "en", 1)
        assert latest["version"] == 2
        assert latest["revision_text"] == "第二版"
        assert latest["note"] == "n2"
        assert latest["edited_by_name"] == "admin"
        assert latest["sense_ref"] == "run1"

    def test_batch_and_notes_and_history(self, revision_env):
        """批量 latest / note 回填 / 历史排序（version DESC）。"""
        trd.ensure_template_revision_tables()
        trd.save_revision("run", "en", 1, "甲义位修订", EDITOR, note="甲要点")
        trd.save_revision("run", "en", 1, "甲义位修订二", EDITOR)
        trd.save_revision("run", "en", 2, "乙义位修订", REVIEWER, note="乙要点")
        revs = trd.get_latest_revisions("run", "en", [1, 2, 3])
        assert set(revs) == {1, 2}
        assert revs[1]["revision_text"] == "甲义位修订二"
        assert revs[1]["note"] is None  # 第二版未带 note
        # note 回填口径：有修订即有条目（note 空 → ""），CSV 回填留空列
        assert trd.get_latest_notes("run", "en", [1, 2, 3]) == {1: "", 2: "乙要点"}
        hist = trd.list_revisions("run", "en", 1)
        assert [h["version"] for h in hist] == [2, 1]

    def test_locate_isolation(self, revision_env):
        """(category, language, sense_id) 三元组隔离：跨范畴/语言互不可见。"""
        trd.ensure_template_revision_tables()
        trd.save_revision("run", "en", 1, "英文修订", EDITOR)
        assert trd.get_latest_revision("run", "zh", 1) is None
        assert trd.get_latest_revision("motion", "en", 1) is None
        result = trd.save_revision("run", "zh", 1, "汉语修订", EDITOR)
        assert result["ok"] is True and result["version"] == 1

    def test_unsaved_sense_reads_empty(self, revision_env):
        """无修订义位：latest=None、批量不含、历史空（fail-open 口径）。"""
        trd.ensure_template_revision_tables()
        assert trd.get_latest_revision("run", "en", 99) is None
        assert trd.list_revisions("run", "en", 99) == []
        assert trd.get_latest_revisions("run", "en", [99]) == {}

    def test_role_gate_enforced_against_real_table(self, revision_env):
        """集成面复核：viewer 写路径抛 PermissionError（数据层闸门不空转）。"""
        trd.ensure_template_revision_tables()
        with pytest.raises(PermissionError):
            trd.save_revision("run", "en", 1, "viewer 修订", VIEWER)
        assert trd.list_revisions("run", "en", 1) == []


# ============================================
# d) require_role 与 CAN_REVISE_ROLES 口径钉死
# ============================================
class TestRoleSetContract:
    def test_can_revise_roles_matches_lexical_can_edit(self):
        """与编纂职能 CAN_EDIT_ROLES 同集（lexical_pages.py 单一事实源口径）。"""
        from src.lexical_pages import CAN_EDIT_ROLES

        assert trd.CAN_REVISE_ROLES == set(CAN_EDIT_ROLES)

    def test_require_role_allowed_empty_fails_closed(self):
        """allowed 空 → 一律拒绝（guards fail-closed，回归护栏）。"""
        with pytest.raises(PermissionError):
            require_role(EDITOR, set(), action="模板人工修订")


# ============================================
# e) FX-38 review 补强：note 非字符串拒收（fail-closed 口径钉死）
# ============================================
@pytest.mark.usefixtures("_forbid_db")
class TestSaveRevisionNoteContract:
    def test_non_string_note_rejected(self):
        """note=123 等非字符串 → 拒收（不静默丢弃）。"""
        for bad in (123, 1.5, ["要点"], {"note": 1}):
            result = trd.save_revision(*LOC, "修订文本", EDITOR, note=bad)
            assert result["ok"] is False
            assert "优化要点非法" in result["reason"]

    def test_empty_and_whitespace_note_accepted(self):
        """note=None / 纯空白 → 视为无 note（放行；落库归集成类）。"""
        for note in (None, "", "   "):
            result = trd.save_revision(*LOC, "修订文本", EDITOR, note=note)
            assert result.get("reason") != "优化要点非法（须为字符串且 ≤500 字）"
