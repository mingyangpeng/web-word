"""编纂成文域数据层测试（src/writing_db.py，批次 7 Agent U）。

两层结构，与 tests/test_ai_ledger.py 约定一致：

  * 纯函数（sense_ref 校验 / ai_draft 序列化守卫）与模块常量不碰数据库 ——
    本地与 CI 全跑；
  * 数据层 CRUD（ensure / create_draft / update_draft / submit_for_review /
    add_comment / request_revision / approve / publish / list_versions /
    list_pending_reviews 及只读辅助）依赖真实 MySQL —— 连不上或账号无建库
    权限就 skip（模块级 skipif + fixture 内 skip），CI（无数据库）依然全绿。

集成测试使用独立测试库 web_word_writing_test（monkeypatch db.MYSQL_DATABASE
指向它，连接池按键区分 host/port/db/user，互不污染），每个测试重建，跑完 DROP。
三表全部软引用无外键（仿 ai_ledger 先例），不建 users 表即可全量验证 ——
回避制/裁决在数据层只比 id，不读用户表。

覆盖面（阶段1施工规范 §10 对 Agent U 的要求）：
  建版/版本链（version 自动递增 + based_on_version）/ 乐观锁 / 状态机
  draft→in_review→(rejected|final)→published / 回避制（审校人≠撰写人硬校验，
  裁决仅受派审校人）/ publish 角色口径（dict_admin；legacy admin 兼判）/
  待审清单联结 / 意见线与收口。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src.writing_db import (  # noqa: E402
    ADJUDICATE_DECISIONS,
    MAX_CONTENT_LEN,
    MAX_SENSE_REF_LEN,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_FINAL,
    STATUS_IN_REVIEW,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
    STATUS_REVIEWED,
    STATUS_REVISED,
    VERDICTS,
    VERSION_STATUSES,
    _dump_ai_draft,
    _parse_ai_draft,
    add_comment,
    adjudicate_final,
    approve,
    create_draft,
    ensure_writing_tables,
    get_latest_version,
    get_version,
    list_comments,
    list_pending_reviews,
    list_versions,
    publish,
    request_revision,
    resolve_comment,
    submit_for_review,
    update_draft,
    valid_sense_ref,
)

TEST_DB = "web_word_writing_test"

REF = "motion:12:345"          # 标准三段式锚（0 占位口径在 sense_ref 用例覆盖）
REF2 = "motion:13:346"
REF_ZH = "RUN:7:0"             # OALD 锚未解析的 0 占位


# ============================================
# 纯函数与常量（契约 §10 枚举口径，无数据库）
# ============================================

class TestConstantsAndGuards:
    """模块常量与入参守卫（不碰数据库，CI 必跑）。"""

    def test_status_enum_full_set(self):
        """status 全集 8 态（帮助文档 §4.2 状态机 + 两级终审占位）。"""
        assert VERSION_STATUSES == (
            "draft", "in_review", "reviewed", "revised",
            "approved", "final", "published", "rejected",
        )

    def test_verdict_enum_full_set(self):
        """verdict 四值（pending + 通过/否决/要求修订）。"""
        assert VERDICTS == ("pending", "approved", "rejected", "revision_requested")

    def test_adjudicate_decisions_subset_of_verdicts(self):
        """终裁决策集 = verdict 的 {approved, rejected} 子集（批次 8 G6 契约）。"""
        assert ADJUDICATE_DECISIONS == ("approved", "rejected")
        assert set(ADJUDICATE_DECISIONS) <= set(VERDICTS)

    def test_valid_sense_ref_accepts_three_part(self):
        """三段式锚合法：常规 / 0 占位 / 带下划线连字符的范畴段。"""
        assert valid_sense_ref("motion:12:345") is True
        assert valid_sense_ref("motion:0:345") is True   # 未进范畴深挖库占位
        assert valid_sense_ref("RUN:7:0") is True        # OALD 锚未解析占位
        assert valid_sense_ref("motion_verb-1:0:0") is True
        assert valid_sense_ref("  motion:12:345  ") is True  # 容忍首尾空白

    def test_valid_sense_ref_rejects_bad_formats(self):
        """缺段/负数/非数字/空段/超长/数字开头范畴段/非字符串一律非法。"""
        bad = [
            None, 42, "",
            "motion", "motion:12", "motion:12:345:9",   # 段数不对
            "motion:-1:345", "motion:12:-1",            # 负数
            "motion:x:345", "motion:12:x",              # 非数字
            ":12:345", "motion::345",                   # 空段
            "12motion:1:1",                             # 范畴段必须字母开头
            "a" * 61 + ":1:1",                          # 超总长（> 60）
            "a" * 32 + ":1:1",                          # 范畴段 > 31 字符
        ]
        for ref in bad:
            assert valid_sense_ref(ref) is False, f"应拒绝: {ref!r}"
        # 总长口径（MAX_SENSE_REF_LEN=60）边界内合法
        ok = "m" * 20 + ":1:1"
        assert len(ok) <= MAX_SENSE_REF_LEN and valid_sense_ref(ok) is True

    def test_dump_ai_draft_accepts_containers(self):
        """dict/list 快照可序列化，中文原样（ensure_ascii=False）。"""
        dumped = _dump_ai_draft({"template_text": "【图式：方式伴随】…", "n": 1})
        assert dumped is not None
        assert "图式" in dumped
        assert _dump_ai_draft([]) == "[]"

    def test_dump_ai_draft_rejects_scalars_and_nan(self):
        """标量/不可序列化/NaN/Inf 一律 _INVALID（create_draft 据此拒绝）。"""
        from src.writing_db import _INVALID

        bad = [42, "纯字符串", 3.14, True, {"x": float("nan")}, {1, 2}]
        for item in bad:
            assert _dump_ai_draft(item) is _INVALID, f"应拒绝: {item!r}"
        assert _dump_ai_draft(None) is None  # None = 不挂快照，合法

    def test_parse_ai_draft_roundtrip(self):
        """JSON 列读回：dict 原样 / str 解析 / NULL → None / 坏数据 → None。"""
        assert _parse_ai_draft({"a": 1}) == {"a": 1}
        assert _parse_ai_draft('{"a": 1}') == {"a": 1}
        assert _parse_ai_draft(None) is None
        assert _parse_ai_draft("not-json") is None
        assert _parse_ai_draft('"scalar"') is None  # 非容器
        assert _parse_ai_draft(b'{"a": 2}') == {"a": 2}

    def test_content_length_cap_matches_contract(self):
        """content 上限远小于 MEDIUMTEXT 容量、sense_ref 口径为 60。"""
        assert MAX_CONTENT_LEN == 1_000_000
        assert MAX_SENSE_REF_LEN == 60


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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过编纂成文域集成测试")
class TestWritingDbIntegration:
    """数据层 CRUD + 状态机 + 回避制（跑在独立测试库 web_word_writing_test）。"""

    @pytest.fixture
    def writing(self, monkeypatch):
        """建空测试库并让 writing_db 指向它，测试结束 DROP。

        与 test_ai_ledger.ledger 相同的手法：get_db_cursor / _new_connection
        在调用时读 mysql_db 模块全局，monkeypatch MYSQL_DATABASE 即可；
        连接池按键含 db 名，互不污染。三表无外键，ensure 可独立建表
        （不建 users 表 —— 回避制/裁决在数据层只比 id）。
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
                "COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过编纂成文域集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        ensure_writing_tables()
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

    def _fetch(self, version_id):
        """直接读库取版本行（绕过数据层，验证落库真相）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM definition_versions WHERE id = %s", (version_id,)
            )
            return cursor.fetchone()

    def _fetch_task(self, version_id):
        """直接读库取版本的审校任务行（最新一条）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM review_tasks WHERE version_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (version_id,),
            )
            return cursor.fetchone()

    def _fetch_tasks(self, version_id):
        """直接读库取版本的全部审校任务行（id 升序，验「不覆盖不删行」）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM review_tasks WHERE version_id = %s ORDER BY id",
                (version_id,),
            )
            return list(cursor.fetchall() or [])

    def _count(self, table, where="1=1", params=()):
        """直接数行数（验证统计真相）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)
            return int(cursor.fetchone()["n"])

    def _submit(self, version_id, reviewer_id=2, note=None):
        """提交初审（用例内高频步骤）。"""
        assert submit_for_review(version_id, reviewer_id, note) is True

    def _set_status(self, version_id, status):
        """直改版本状态（仅造两级终审中段态 approved 等测试前置，绕过状态机）。"""
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE definition_versions SET status = %s WHERE id = %s",
                (status, version_id),
            )

    # --- 建表 ---

    def test_ensure_idempotent(self, writing):
        """ensure 重复调用幂等（CREATE TABLE IF NOT EXISTS）。"""
        ensure_writing_tables()
        ensure_writing_tables()
        assert list_versions() == []
        assert list_pending_reviews() == []

    # --- create_draft：建版与版本链 ---

    def test_create_draft_version_auto_increments(self, writing):
        """同 sense_ref 连续建版 version 自动递增；跨 sense_ref 互不干扰。"""
        v1 = create_draft(REF, 9, "第一版释义")
        v2 = create_draft(REF, 9, "第二版释义")
        other = create_draft(REF2, 9, "别的义位")
        assert 0 < v1 < v2 and other > 0
        assert self._fetch(v1)["version"] == 1
        assert self._fetch(v2)["version"] == 2
        assert self._fetch(other)["version"] == 1

    def test_create_draft_defaults_and_optional_fields(self, writing):
        """默认 status='draft'；based_on/style_version/ai_draft 可选字段往返。"""
        snapshot = {"kind": "template_preview", "template_text": "模板底稿"}
        vid = create_draft(
            REF, 9, "释义成文", based_on_version=None,
            style_version="style.yaml@v1", ai_draft=snapshot,
        )
        row = self._fetch(vid)
        assert row["status"] == STATUS_DRAFT
        assert row["sense_ref"] == REF
        assert row["author_id"] == 9
        assert row["based_on_version"] is None
        assert row["style_version"] == "style.yaml@v1"
        assert _parse_ai_draft(row["ai_draft"]) == snapshot
        assert row["created_at"] is not None and row["updated_at"] is not None
        got = get_version(vid)
        assert got["ai_draft"] == snapshot  # 读侧解析回 dict

    def test_create_draft_based_on_version_roundtrip(self, writing):
        """based_on_version 记版本号（打回重提链路）；可指向既有版。"""
        v1 = create_draft(REF, 9, "v1")
        v2 = create_draft(REF, 9, "v2", based_on_version=1)
        assert self._fetch(v2)["based_on_version"] == 1
        assert self._fetch(v2)["version"] == 2
        assert v1 > 0

    def test_create_draft_rejects_bad_sense_ref(self, writing):
        """sense_ref 三段式口径：非法格式/超长根本不进数据库。"""
        bad = ["", "   ", "motion", "motion:12", "motion:x:1", ":1:1",
               "m" * 61 + ":1:1", None, 123]
        for ref in bad:
            assert create_draft(ref, 9, "内容") == 0, f"应拒绝: {ref!r}"
        assert self._count("definition_versions") == 0

    def test_create_draft_rejects_bad_content(self, writing):
        """content 必须是非空字符串（strip 判空；原文存库不 strip）。"""
        bad = ["", "   ", None, 42, "x" * (MAX_CONTENT_LEN + 1)]
        for content in bad:
            assert create_draft(REF, 9, content) == 0, f"应拒绝: {content!r}"
        assert self._count("definition_versions") == 0

    def test_create_draft_rejects_bad_optional_params(self, writing):
        """author_id/based_on_version/style_version/ai_draft 非法一律拒绝。"""
        assert create_draft(REF, 0, "内容") == 0
        assert create_draft(REF, -1, "内容") == 0
        assert create_draft(REF, "me", "内容") == 0
        assert create_draft(REF, 9, "内容", based_on_version=0) == 0
        assert create_draft(REF, 9, "内容", based_on_version=-3) == 0
        assert create_draft(REF, 9, "内容", style_version="s" * 41) == 0
        assert create_draft(REF, 9, "内容", style_version=123) == 0
        assert create_draft(REF, 9, "内容", ai_draft="字符串不是快照") == 0
        assert create_draft(REF, 9, "内容", ai_draft={"x": float("nan")}) == 0
        assert self._count("definition_versions") == 0

    def test_create_draft_rejects_unknown_based_on(self, writing):
        """based_on_version 必须指向同 sense_ref 的既有版号（版本链完整性）。"""
        create_draft(REF, 9, "v1")
        assert create_draft(REF, 9, "v2", based_on_version=99) == 0
        assert create_draft(REF, 9, "v2", based_on_version=2) == 0  # 尚无 v2
        assert self._count("definition_versions") == 1

    def test_create_draft_zero_placeholder_refs(self, writing):
        """0 占位锚（motion:0:345 / RUN:7:0）合法且链独立。"""
        assert create_draft("motion:0:345", 9, "OALD 直撰") > 0
        assert create_draft("RUN:7:0", 9, "仅研究层编码") > 0
        assert self._count("definition_versions") == 2

    # --- update_draft：乐观锁 + 作者守卫（R1-3） ---

    def test_update_draft_roundtrip(self, writing):
        """更新成文/体例/快照全量覆盖；version 号保持不变（R1-3 起须作者匹配）。"""
        vid = create_draft(REF, 9, "初稿", style_version=None)
        assert update_draft(vid, 1, "改定稿", style_version="style.yaml@v2",
                            ai_draft={"k": "v"}, author_id=9) is True
        row = self._fetch(vid)
        assert row["content"] == "改定稿"
        assert row["style_version"] == "style.yaml@v2"
        assert row["version"] == 1
        assert _parse_ai_draft(row["ai_draft"]) == {"k": "v"}

    def test_update_draft_optimistic_lock(self, writing):
        """expect_version 不符拒绝（乐观锁口径）；正确版本可再更新。"""
        vid = create_draft(REF, 9, "初稿")
        # 表单装载时以为是 v2（实际 v1）→ 拒
        assert update_draft(vid, 2, "过期表单的修改", author_id=9) is False
        assert self._fetch(vid)["content"] == "初稿"
        # 正确版本号 → 成功
        assert update_draft(vid, 1, "新鲜表单的修改", author_id=9) is True

    def test_update_draft_rejects_non_draft(self, writing):
        """提交审校后（in_review）不可再改稿 —— 状态机口径。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid)
        assert update_draft(vid, 1, "审校期间偷改", author_id=9) is False
        assert self._fetch(vid)["content"] == "初稿"

    def test_update_draft_rejects_bad_args(self, writing):
        """行不存在 / 非法 id / 空 content / 非法 ai_draft 拒绝。"""
        vid = create_draft(REF, 9, "初稿")
        assert update_draft(999999, 1, "x", author_id=9) is False
        assert update_draft("abc", 1, "x") is False
        assert update_draft(None, 1, "x") is False
        assert update_draft(vid, 0, "x") is False
        assert update_draft(vid, 1, "") is False
        assert update_draft(vid, 1, "   ") is False
        assert update_draft(vid, 1, "x", ai_draft=42) is False
        assert update_draft(vid, 1, "x", style_version="s" * 41) is False
        assert self._fetch(vid)["content"] == "初稿"

    def test_update_draft_nochange_still_succeeds(self, writing):
        """同内容重存（MySQL 计 0 受影响行）不算失败 —— 行存在即成功。"""
        vid = create_draft(REF, 9, "同样的话")
        assert update_draft(vid, 1, "同样的话", author_id=9) is True

    def test_update_draft_author_hijack_rejected(self, writing):
        """R1-3 作者守卫：非作者（含不传 author_id 直调）改写他人草稿一律拒绝。"""
        vid = create_draft(REF, 9, "本人草稿")
        # 他人声称自己是作者 → 拒，内容不动
        assert update_draft(vid, 1, "劫持内容", author_id=8) is False
        # 直调不传 author_id（旧行为可 hijack）→ fail-closed 拒
        assert update_draft(vid, 1, "劫持内容") is False
        assert self._fetch(vid)["content"] == "本人草稿"
        # 作者本人 → 放行
        assert update_draft(vid, 1, "本人改定", author_id=9) is True
        assert self._fetch(vid)["content"] == "本人改定"

    def test_update_draft_author_null_row_only_null_claim(self, writing):
        """author_id=NULL 的系统登记行：仅 author_id=None 的调用可改写。"""
        vid = create_draft(REF, None, "系统登记行", allow_system=True)
        assert update_draft(vid, 1, "冒名改写", author_id=9) is False
        assert update_draft(vid, 1, "补登记改写", author_id=None) is True
        assert self._fetch(vid)["content"] == "补登记改写"

    def test_update_draft_rejects_bad_author_id(self, writing):
        """author_id 非法值（0/负数/非整数）拒绝（fail-closed）。"""
        vid = create_draft(REF, 9, "初稿")
        for bad in (0, -1, "me", True):
            assert update_draft(vid, 1, "x", author_id=bad) is False, bad
        assert self._fetch(vid)["content"] == "初稿"

    # --- submit_for_review：状态机 + 回避制 ---

    def test_submit_creates_pending_task(self, writing):
        """draft → in_review，任务 pending 落库（round=1，note 留痕）。"""
        vid = create_draft(REF, 9, "初稿")
        assert self._fetch(vid)["status"] == STATUS_DRAFT
        assert submit_for_review(vid, 2, "请审校：替换性测试已自检") is True
        row = self._fetch(vid)
        assert row["status"] == STATUS_IN_REVIEW
        task = self._fetch_task(vid)
        assert task["verdict"] == "pending"
        assert task["reviewer_id"] == 2
        assert task["round"] == 1
        assert task["note"] == "请审校：替换性测试已自检"

    def test_submit_recusal_hard_block(self, writing):
        """回避制硬校验：审校人=撰写人直接拒绝，状态不动、任务不建。"""
        vid = create_draft(REF, 9, "自写词条")
        assert submit_for_review(vid, 9) is False
        assert self._fetch(vid)["status"] == STATUS_DRAFT
        assert self._count("review_tasks") == 0

    def test_submit_only_from_draft(self, writing):
        """重复提交拒绝（非 draft 态）；不存在/非法 id 拒绝。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        assert submit_for_review(vid, 3) is False
        assert self._fetch_task(vid)["reviewer_id"] == 2  # 首个任务未被覆盖
        assert submit_for_review(999999, 2) is False
        assert submit_for_review("abc", 2) is False
        assert submit_for_review(vid, 0) is False
        assert submit_for_review(vid, -1) is False
        assert submit_for_review(vid, "admin") is False

    def test_submit_rejects_bad_note(self, writing):
        """note 非字符串/超长拒绝（应用层先拒）。"""
        vid = create_draft(REF, 9, "初稿")
        assert submit_for_review(vid, 2, note=123) is False
        assert submit_for_review(vid, 2, note="n" * 16001) is False
        assert self._count("review_tasks") == 0
        assert self._fetch(vid)["status"] == STATUS_DRAFT

    def test_submit_author_null_system_row_rejected(self, writing):
        """R1-4：author_id 为 NULL（系统登记行）不可提交审校 —— 先补登记作者。"""
        vid = create_draft(REF, None, "系统登记的草稿", allow_system=True)
        assert submit_for_review(vid, 9) is False
        assert self._fetch(vid)["status"] == STATUS_DRAFT
        assert self._count("review_tasks") == 0

    def test_create_draft_null_author_requires_allow_system(self, writing):
        """R1-4：create_draft 无主行默认拒绝；allow_system=True 显式豁免。"""
        assert create_draft(REF, None, "无主行默认拒") == 0
        assert list_versions(REF) == []
        vid = create_draft(REF, None, "系统登记行", allow_system=True)
        assert vid > 0
        assert self._fetch(vid)["author_id"] is None

    def test_approve_author_null_system_row_rejected(self, writing):
        """R1-4：author_id 为 NULL 的行不可审校通过（即使已伪造入审校态）。"""
        vid = create_draft(REF, None, "系统登记行", allow_system=True)
        self._set_status(vid, STATUS_IN_REVIEW)  # 造历史存量态（绕过提交守卫）
        # 需要一条 pending 任务才走到回避制；先手工补任务行
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO review_tasks (version_id, reviewer_id, round, verdict) "
                "VALUES (%s, 2, 1, 'pending')",
                (vid,),
            )
        assert approve(vid, 2) is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._fetch_task(vid)["verdict"] == "pending"

    # --- add_comment：意见线 + 回避制 ---

    def test_add_comment_roundtrip(self, writing):
        """意见挂版本（resolved 默认 0），list_comments 按 id 升序。"""
        vid = create_draft(REF, 9, "初稿")
        c1 = add_comment(vid, 2, "定义词「移动」不在词表，建议换。")
        c2 = add_comment(vid, 3, "补充替换性测试证据。")
        assert 0 < c1 < c2
        comments = list_comments(vid)
        assert [c["id"] for c in comments] == [c1, c2]
        assert all(c["resolved"] == 0 for c in comments)
        assert comments[0]["body"].startswith("定义词")

    def test_add_comment_recusal(self, writing):
        """作者不得在自己的版本上挂意见（回避制无豁免）。"""
        vid = create_draft(REF, 9, "初稿")
        assert add_comment(vid, 9, "自评一条") == 0
        assert list_comments(vid) == []

    def test_add_comment_rejects_bad_args(self, writing):
        """版本不存在 / body 空 / 非法 id 拒绝。"""
        vid = create_draft(REF, 9, "初稿")
        assert add_comment(999999, 2, "x") == 0
        assert add_comment(vid, 2, "") == 0
        assert add_comment(vid, 2, "   ") == 0
        assert add_comment(vid, 2, None) == 0
        assert add_comment(vid, 0, "x") == 0
        assert add_comment(vid, "me", "x") == 0
        assert add_comment("abc", 2, "x") == 0
        assert list_comments(vid) == []

    def test_resolve_comment_marks_without_delete(self, writing):
        """收口只标记不删行；重复同向标记返回 False（无变更）。"""
        vid = create_draft(REF, 9, "初稿")
        cid = add_comment(vid, 2, "意见")
        assert resolve_comment(cid, True) is True
        comments = list_comments(vid)
        assert len(comments) == 1 and comments[0]["resolved"] == 1
        assert resolve_comment(cid, True) is False  # 已是同值
        assert resolve_comment(cid, False) is True  # 可回退
        assert resolve_comment(999999, True) is False
        assert resolve_comment("abc") is False

    # --- request_revision：打回 ---

    def test_request_revision_flow(self, writing):
        """in_review → rejected；任务 verdict=revision_requested；note 覆盖。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2, note="提交说明")
        assert request_revision(vid, 2, "定义词越表，请改写。") is True
        assert self._fetch(vid)["status"] == STATUS_REJECTED
        task = self._fetch_task(vid)
        assert task["verdict"] == "revision_requested"
        assert task["note"] == "定义词越表，请改写。"

    def test_request_revision_keeps_note_when_none(self, writing):
        """note 缺省保留提交时说明（COALESCE 口径）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2, note="原始提交说明")
        assert request_revision(vid, 2) is True
        assert self._fetch_task(vid)["note"] == "原始提交说明"

    def test_request_revision_only_assigned_reviewer(self, writing):
        """非受派审校人不能裁决（分权口径）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        assert request_revision(vid, 3, "我不是受派人") is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._fetch_task(vid)["verdict"] == "pending"

    def test_request_revision_recusal(self, writing):
        """作者不能打回自己的版本（即便被指派——指派本身已被回避制拦住）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        assert request_revision(vid, 9, "自打回") is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW

    def test_request_revision_state_guards(self, writing):
        """非 in_review / 无待审任务 / 二次打回 / 非法 id 一律拒绝。"""
        vid = create_draft(REF, 9, "初稿")
        assert request_revision(vid, 2, "还没提交") is False  # draft 态
        self._submit(vid, reviewer_id=2)
        assert request_revision(vid, 2, "第一次") is True
        assert request_revision(vid, 2, "第二次") is False  # 已 rejected
        assert self._fetch(vid)["status"] == STATUS_REJECTED
        assert request_revision(999999, 2) is False
        assert request_revision("abc", 2) is False

    # --- approve：终审即 final（MVP） ---

    def test_approve_flow(self, writing):
        """in_review → final；任务 verdict=approved；通过留言可留。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        assert approve(vid, 2, "体例与替换性测试均过，定稿。") is True
        assert self._fetch(vid)["status"] == STATUS_FINAL
        task = self._fetch_task(vid)
        assert task["verdict"] == "approved"
        assert task["note"] == "体例与替换性测试均过，定稿。"

    def test_approve_guards_mirror_request_revision(self, writing):
        """通过与打回同守卫：非受派人/作者本人/非 in_review/二次裁决拒绝。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        assert approve(vid, 3) is False          # 非受派
        assert approve(vid, 9) is False          # 回避制
        assert approve(vid, 2) is True
        assert approve(vid, 2) is False          # 已 final
        assert self._fetch(vid)["status"] == STATUS_FINAL
        other = create_draft(REF2, 9, "另一版")
        assert approve(other, 2) is False        # draft 态不可通过
        assert self._fetch(other)["status"] == STATUS_DRAFT

    # --- publish：dict_admin 口径 + final→published ---

    def test_publish_by_dict_admin(self, writing):
        """dict_admin 有效角色（roles 快照）可发布 final 版。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        approve(vid, 2)
        actor = {"id": 5, "username": "chief", "role": "viewer",
                 "roles": ["dict_admin"]}
        assert publish(vid, actor) is True
        assert self._fetch(vid)["status"] == STATUS_PUBLISHED

    def test_publish_legacy_admin_transitional(self, writing):
        """过渡期 legacy role=='admin' 经 effective_six_roles 兼判 dict_admin。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        approve(vid, 2)
        assert publish(vid, {"id": 1, "username": "admin", "role": "admin"}) is True

    def test_publish_denies_non_dict_admin(self, writing):
        """reviewer/editor/sys_admin/viewer/未登录 一律拒绝（fail-closed）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        approve(vid, 2)
        for actor in [
            {"id": 3, "role": "viewer", "roles": ["reviewer"]},
            {"id": 4, "role": "viewer", "roles": ["editor"]},
            {"id": 6, "role": "viewer", "roles": ["sys_admin"]},
            {"id": 7, "role": "viewer", "roles": ["viewer"]},
            {"id": 3, "role": "reviewer"},          # legacy 无六角色映射
            None, "admin", 42,
        ]:
            assert publish(vid, actor) is False, f"应拒绝: {actor!r}"
        assert self._fetch(vid)["status"] == STATUS_FINAL

    def test_publish_state_guards(self, writing):
        """非 final 态（draft/in_review/rejected/published）不可发布。"""
        draft = create_draft(REF, 9, "草稿")
        assert publish(draft, {"id": 1, "role": "admin"}) is False
        in_review = create_draft(REF2, 9, "审校中")
        self._submit(in_review, reviewer_id=2)
        assert publish(in_review, {"id": 1, "role": "admin"}) is False
        assert publish(999999, {"id": 1, "role": "admin"}) is False
        assert self._fetch(draft)["status"] == STATUS_DRAFT

    # --- adjudicate_final：词典管理员终裁（批次 8 G6，两级终审收口） ---

    DICT_ADMIN_ACTOR = {"id": 1, "username": "chief", "role": "viewer",
                        "roles": ["dict_admin"]}
    LEGACY_ADMIN_ACTOR = {"id": 1, "username": "admin", "role": "admin"}

    def test_adjudicate_approve_in_review_direct_to_final(self, writing):
        """in_review --approved--> final 直达（两级终审收口）；终裁落新任务行。"""
        vid = create_draft(REF, 9, "争议词条初稿")
        self._submit(vid, reviewer_id=2)
        assert adjudicate_final(
            vid, 1, "approved", "升级终裁：语义分立证据充分，收口。",
            actor=self.DICT_ADMIN_ACTOR,
        ) is True
        assert self._fetch(vid)["status"] == STATUS_FINAL
        tasks = self._fetch_tasks(vid)
        assert len(tasks) == 2  # 受派审校任务行 + 终裁任务行（不覆盖不删行）
        first, final = tasks[0], tasks[1]
        assert (first["verdict"], first["round"], first["reviewer_id"]) == (
            "pending", 1, 2)  # 受派人的 pending 任务保持原样（不代为裁决）
        assert (final["verdict"], final["round"], final["reviewer_id"]) == (
            "approved", 2, 1)  # round+1 标记终裁轮，verdict 按 decision
        assert final["note"] == "升级终裁：语义分立证据充分，收口。"

    def test_adjudicate_reject_in_review_to_rejected(self, writing):
        """in_review --rejected--> rejected（终裁否决）；理由随任务行留痕。"""
        vid = create_draft(REF, 9, "将被否决的初稿")
        self._submit(vid, reviewer_id=2)
        assert adjudicate_final(
            vid, 1, "rejected", "释义不可代回语料原文，否决。",
            actor=self.DICT_ADMIN_ACTOR,
        ) is True
        assert self._fetch(vid)["status"] == STATUS_REJECTED
        final = self._fetch_task(vid)
        assert final["verdict"] == "rejected"
        assert final["round"] == 2
        assert final["note"] == "释义不可代回语料原文，否决。"

    def test_adjudicate_approve_note_optional(self, writing):
        """note 缺省（""）终裁通过：任务行 note 为 NULL，状态照常收口。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        assert adjudicate_final(
            vid, 1, "approved", "", actor=self.DICT_ADMIN_ACTOR) is True
        assert self._fetch(vid)["status"] == STATUS_FINAL
        assert self._fetch_task(vid)["note"] is None

    def test_adjudicate_supplement_from_approved_state(self, writing):
        """补终裁：approved（两级链中段占位）--approved--> final；rejected 拒绝。"""
        vid = create_draft(REF, 9, "两级链中段行")
        self._submit(vid, reviewer_id=2)
        self._set_status(vid, STATUS_APPROVED)  # 造 approved 态（中段占位）
        assert adjudicate_final(
            vid, 1, "approved", actor=self.LEGACY_ADMIN_ACTOR) is True
        assert self._fetch(vid)["status"] == STATUS_FINAL
        # approved 态行不允许终裁否决（否决只认 in_review）
        other = create_draft(REF2, 9, "另一中段行")
        self._submit(other, reviewer_id=2)
        self._set_status(other, STATUS_APPROVED)
        assert adjudicate_final(
            other, 1, "rejected", "想否决", actor=self.DICT_ADMIN_ACTOR) is False
        assert self._fetch(other)["status"] == STATUS_APPROVED

    def test_adjudicate_rejects_other_states(self, writing):
        """draft / final / published / rejected / reviewed / revised 一律拒绝。"""
        draft = create_draft(REF, 9, "草稿")
        assert adjudicate_final(
            draft, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        self._submit(draft, reviewer_id=2)
        approve(draft, 2)  # → final
        assert adjudicate_final(
            draft, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        assert adjudicate_final(
            draft, 1, "rejected", "定稿后否决", actor=self.DICT_ADMIN_ACTOR) is False
        assert self._fetch(draft)["status"] == STATUS_FINAL
        published = create_draft(REF2, 9, "发布版")
        self._submit(published, reviewer_id=2)
        approve(published, 2)
        publish(published, {"id": 1, "role": "admin"})
        assert adjudicate_final(
            published, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        rejected = create_draft("motion:14:0", 9, "已打回版")
        self._submit(rejected, reviewer_id=2)
        request_revision(rejected, 2, "打回")
        assert adjudicate_final(
            rejected, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        for idx, mid in enumerate((STATUS_REVIEWED, STATUS_REVISED)):
            row = create_draft(f"motion:{15 + idx}:0", 9, "中段占位态")
            self._submit(row, reviewer_id=2)
            self._set_status(row, mid)
            assert adjudicate_final(
                row, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False, mid
        assert self._count("review_tasks") == 5  # 只有各版本提交时的任务行，无终裁行

    def test_adjudicate_requires_dict_admin_actor(self, writing):
        """actor 显式传入且有效六角色须含 dict_admin（legacy admin 兼判）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        for actor in [
            None, "admin", 42,
            {"id": 3, "role": "viewer", "roles": ["reviewer"]},
            {"id": 4, "role": "viewer", "roles": ["editor"]},
            {"id": 6, "role": "viewer", "roles": ["sys_admin"]},
            {"id": 7, "role": "viewer", "roles": ["viewer", "annotator"]},
            {"id": 3, "role": "reviewer"},  # legacy 无六角色映射
        ]:
            assert adjudicate_final(
                vid, 1, "approved", actor=actor) is False, f"应拒绝: {actor!r}"
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._count("review_tasks") == 1
        assert adjudicate_final(
            vid, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is True

    def test_adjudicate_recusal_hard_block(self, writing):
        """回避制无豁免（含词典管理员）：终裁人=撰写人直接拒绝，状态不动。"""
        vid = create_draft(REF, 9, "管理员自写词条")
        self._submit(vid, reviewer_id=2)
        actor = {"id": 9, "username": "chief", "role": "viewer",
                 "roles": ["dict_admin"]}
        assert adjudicate_final(vid, 9, "approved", actor=actor) is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._count("review_tasks", "version_id = %s", (vid,)) == 1

    def test_adjudicate_rejects_bad_args(self, writing):
        """decision 非法 / id 非法 / note 超长一律拒绝（不进数据库）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        for decision in ("pending", "revision_requested", "bogus", "", None, 1):
            assert adjudicate_final(
                vid, 1, decision, actor=self.DICT_ADMIN_ACTOR) is False, decision
        for vid_bad in (999999, 0, -1, "abc", None):
            assert adjudicate_final(
                vid_bad, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        for aid_bad in (0, -1, "me", None):
            assert adjudicate_final(
                vid, aid_bad, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        assert adjudicate_final(
            vid, 1, "approved", note="n" * 16001,
            actor=self.DICT_ADMIN_ACTOR) is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._count("review_tasks") == 1

    def test_adjudicate_round_follows_existing_max(self, writing):
        """终裁轮 = 既有任务 round 最大值 +1（多轮历史下不重号）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:  # 造历史：手工补一条 round=3 的已决任务
            cursor.execute(
                "INSERT INTO review_tasks (version_id, reviewer_id, round, verdict) "
                "VALUES (%s, 3, 3, 'approved')",
                (vid,),
            )
        assert adjudicate_final(
            vid, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is True
        assert self._fetch_task(vid)["round"] == 4
        assert self._fetch(vid)["status"] == STATUS_FINAL

    def test_adjudicate_impersonation_rejected(self, writing):
        """R1-4 冒名收口：adjudicator_id ≠ actor['id'] 一律拒绝（留痕不伪造）。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        # A 会话（id=1）冒 B（id=2）之名终裁 → 拒，状态与任务行不动
        assert adjudicate_final(
            vid, 2, "approved", "冒名终裁", actor=self.DICT_ADMIN_ACTOR) is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._count("review_tasks", "version_id = %s", (vid,)) == 1
        # actor 无有效 id（脏会话）同样拒绝
        no_id_actor = {"username": "chief", "role": "viewer",
                       "roles": ["dict_admin"]}
        assert adjudicate_final(
            vid, 1, "approved", actor=no_id_actor) is False
        # adjudicator_id == actor['id'] → 放行
        assert adjudicate_final(
            vid, 1, "approved", "本人终裁", actor=self.DICT_ADMIN_ACTOR) is True
        assert self._fetch(vid)["status"] == STATUS_FINAL
        assert self._fetch_task(vid)["reviewer_id"] == 1

    def test_adjudicate_author_null_system_row_rejected(self, writing):
        """R1-4：author_id 为 NULL 的行不可终裁（先补登记作者）。"""
        vid = create_draft(REF, None, "系统登记行", allow_system=True)
        self._set_status(vid, STATUS_IN_REVIEW)
        assert adjudicate_final(
            vid, 1, "approved", actor=self.DICT_ADMIN_ACTOR) is False
        assert self._fetch(vid)["status"] == STATUS_IN_REVIEW
        assert self._count("review_tasks", "version_id = %s", (vid,)) == 0

    # --- 全链路：版本链（打回重提） ---

    def test_full_revision_chain(self, writing):
        """v1 被打回 → v2（based_on_version=1）→ 通过 → 发布；链表完整。"""
        v1 = create_draft(REF, 9, "第一版（有定义词越表）")
        self._submit(v1, reviewer_id=2)
        request_revision(v1, 2, "请换定义词。")
        v2 = create_draft(REF, 9, "第二版（改写完成）", based_on_version=1)
        assert self._fetch(v2)["version"] == 2
        self._submit(v2, reviewer_id=2)
        assert approve(v2, 2) is True
        assert publish(v2, {"id": 1, "role": "admin"}) is True

        versions = list_versions(REF)
        assert [row["version"] for row in versions] == [1, 2]  # 链按版号升序
        assert versions[0]["status"] == STATUS_REJECTED
        assert versions[1]["status"] == STATUS_PUBLISHED
        assert versions[1]["based_on_version"] == 1
        # 任务留痕：v1 一条（打回）、v2 一条（通过），均不删
        assert self._count("review_tasks", "version_id = %s", (v1,)) == 1
        assert self._count("review_tasks", "version_id = %s", (v2,)) == 1

    # --- list_versions ---

    def test_list_versions_filters_and_order(self, writing):
        """sense_ref/status 过滤与升序；非法 status/sense_ref 返回 []。"""
        a = create_draft(REF, 9, "a")
        b = create_draft(REF, 9, "b")
        create_draft(REF2, 8, "c")
        assert [r["version"] for r in list_versions(REF)] == [1, 2]
        assert [r["sense_ref"] for r in list_versions()] == [REF, REF, REF2]
        assert [r["id"] for r in list_versions(REF, status=STATUS_DRAFT)] == [a, b]
        assert submit_for_review(a, 2) is True
        assert [r["id"] for r in list_versions(REF, status=STATUS_IN_REVIEW)] == [a]
        assert [r["id"] for r in list_versions(REF, status=STATUS_DRAFT)] == [b]
        assert [r["id"] for r in list_versions(REF, status=STATUS_FINAL)] == []
        assert list_versions(REF, status="not-a-status") == []
        assert list_versions("bad-ref") == []
        assert list_versions(limit=0) == []
        assert list_versions(limit=-1) == []

    def test_list_versions_limit_cap(self, writing):
        """limit 截断生效（不超过 MAX_LIST_LIMIT）。"""
        from src.writing_db import MAX_LIST_LIMIT

        for i in range(5):
            create_draft(f"motion:{100 + i}:0", 9, f"v{i}")
        assert len(list_versions(limit=3)) == 3
        assert len(list_versions(limit=10 ** 6)) == 5  # 截到 MAX 也不炸
        assert MAX_LIST_LIMIT >= 5

    def test_list_versions_ai_draft_parsed(self, writing):
        """list_versions 的 ai_draft 是解析后的容器（PyMySQL JSON 列给 str）。"""
        create_draft(REF, 9, "a", ai_draft={"k": [1, 2]})
        rows = list_versions(REF)
        assert rows[0]["ai_draft"] == {"k": [1, 2]}

    # --- list_pending_reviews ---

    def test_list_pending_reviews_join_and_filter(self, writing):
        """待审清单联结版本行；reviewer_id 过滤；裁决后退出清单。"""
        v1 = create_draft(REF, 9, "初稿一")
        v2 = create_draft(REF2, 8, "初稿二")
        self._submit(v1, reviewer_id=2)
        self._submit(v2, reviewer_id=3)
        mine = list_pending_reviews(reviewer_id=2)
        assert len(mine) == 1
        row = mine[0]
        assert row["task_id"] > 0
        assert row["version_id"] == v1
        assert row["sense_ref"] == REF
        assert row["version"] == 1
        assert row["author_id"] == 9
        assert row["content"] == "初稿一"
        assert row["status"] == STATUS_IN_REVIEW
        assert row["round"] == 1
        assert row["verdict"] == "pending"
        assert len(list_pending_reviews()) == 2  # 全局口径
        approve(v1, 2)
        assert list_pending_reviews(reviewer_id=2) == []   # 已裁决退出
        assert len(list_pending_reviews()) == 1
        assert list_pending_reviews(reviewer_id=2, limit=0) == []

    def test_list_pending_reviews_ai_draft_parsed(self, writing):
        """待审清单的 ai_draft 解析回容器（审校台对照直读）。"""
        vid = create_draft(REF, 9, "初稿", ai_draft={"template_text": "T"})
        self._submit(vid, reviewer_id=2)
        row = list_pending_reviews(reviewer_id=2)[0]
        assert row["ai_draft"] == {"template_text": "T"}

    def test_list_pending_reviews_invalid_reviewer(self, writing):
        """reviewer_id 非法（非正整数）返回 []，不报错。"""
        create_draft(REF, 9, "初稿")
        vid = create_draft(REF2, 9, "初稿二")
        self._submit(vid, reviewer_id=2)
        assert list_pending_reviews(reviewer_id=0) == []
        assert list_pending_reviews(reviewer_id=-1) == []
        assert list_pending_reviews(reviewer_id="me") == []
        assert len(list_pending_reviews()) == 1

    # --- get_version / get_latest_version ---

    def test_get_version_and_latest(self, writing):
        """单版读取 + 最新版定位（撰写台续写/重提的底稿入口）。"""
        v1 = create_draft(REF, 9, "v1")
        v2 = create_draft(REF, 9, "v2", based_on_version=1)
        assert get_version(v1)["content"] == "v1"
        assert get_version(999999) is None
        assert get_version("abc") is None
        assert get_version(None) is None
        latest = get_latest_version(REF)
        assert latest["id"] == v2 and latest["version"] == 2
        assert get_latest_version("bad") is None
        assert get_latest_version("motion:999:888") is None

    def test_get_latest_version_draft_masked_for_non_author(self, writing):
        """R1-3 脱敏：draft 态最新版对非作者/未声明身份返回 draft_hidden 标记。"""
        create_draft(REF, 9, "在途草稿内容")
        # 未声明身份（直调缺省）→ 脱敏
        masked = get_latest_version(REF)
        assert masked["content"] is None
        assert masked["draft_hidden"] is True
        # 他者身份 → 脱敏
        other = get_latest_version(REF, viewer_id=8)
        assert other["content"] is None and other["draft_hidden"] is True
        # 作者本人 → 不受限
        mine = get_latest_version(REF, viewer_id=9)
        assert mine["content"] == "在途草稿内容"
        assert "draft_hidden" not in mine
        # 审校侧声明 → 不受限
        reviewer = get_latest_version(REF, viewer_id=2, allow_reviewer=True)
        assert reviewer["content"] == "在途草稿内容"

    def test_get_latest_version_masking_only_draft_state(self, writing):
        """脱敏只作用于 draft 态：rejected 重提预填与定稿回看不受限。"""
        v1 = create_draft(REF, 9, "被拒内容")
        self._submit(v1, reviewer_id=2)
        request_revision(v1, 2, "打回")
        row = get_latest_version(REF, viewer_id=8)
        assert row["status"] == STATUS_REJECTED
        assert row["content"] == "被拒内容"
        assert "draft_hidden" not in row
        self._set_status(v1, STATUS_FINAL)
        assert get_latest_version(REF)["content"] == "被拒内容"

    # --- 状态机总览：MVP 不经由的扩展占位态 ---

    def test_reserved_states_not_reached_by_mvp(self, writing):
        """reviewed/revised/approved 是批次 8 两级终审占位：MVP 流转不经由。"""
        vid = create_draft(REF, 9, "初稿")
        self._submit(vid, reviewer_id=2)
        approve(vid, 2)
        assert self._fetch(vid)["status"] == STATUS_FINAL
        row = self._fetch(vid)
        assert row["status"] not in (STATUS_REVIEWED, STATUS_REVISED,
                                     STATUS_APPROVED)
