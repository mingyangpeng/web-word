"""FX-30 批次实现验证：规范 §8②组「项目广播」最小诚实版。

口径（与 src/broadcast_db.py 模块 docstring、src/dict_admin_pages.py FX-30 段、
src/collab_pages.py _render_broadcast_banner 一致）：

  * 规范原文（grep「广播」3 处）：词典管理员职责含「项目广播」；关键规则
    「项目广播：project_announcements（登录横幅＋收件箱类目）」；单人项目
    「bypass 留痕＋项目广播公示兜底」。本批落「收件箱类目」＋发布入口；
    表名按任务书 DDL 口径 project_broadcasts（规范名差异已在数据层 docstring
    如实注明）；登录横幅非本批范围（app.py 禁碰）。
  * DDL：project_broadcasts 注册进 mysql_db.CREATE_TABLES_SQL（单一事实源
    PROJECT_BROADCASTS_TABLE_SQL 末位引用）；published_by NULL=系统作业
    （RV2-3 留痕列第 1 类）；project_id 软引用 org 域（无 FK）；索引
    (project_id, id)。
  * 数据层 src/broadcast_db.py：publish_broadcast 两道闸（require_role
    词典管理员 ＋ org_db.list_projects 只读校验项目在册）→ INSERT；
    list_broadcasts 按项目倒序附发布人名；latest_for_user 三态聚合
    （None=取数失败灰注 / []=无广播不渲染 / 非空=收件箱条目）。
  * 页面：词典管理区·项目成员 tab「📢 项目广播」段（form 发布 + 历史小表，
    ui_kit.flash ＋ st.rerun 纪律，widget key 前缀 dict_admin_bc_）；协作
    收件箱顶部广播条（无广播不渲染段、库降级灰注、published_by=NULL 显示
    「系统作业」）。
  * AppTest 冒烟：发布成功 flash 弹出 ＋ 收件箱广播条目在场（数据层打桩，
    不触真库）。

测试分层（与 tests/test_collab_pages.py / tests/test_fx26_fixes.py 约定一致）：
  * 契约与闸门（DDL 注册 / 角色闸 / 参数清洗 / 降级路径 / 页面 stub 渲染）
    不碰数据库 —— 本地与 CI 全跑；
  * 往返集成（发布 → 按项目列出 → latest_for_user 聚合）依赖真实 MySQL，
    跑在独立测试库 TEST_DB（monkeypatch db.MYSQL_DATABASE，fixture 前后
    DROP 重建；无建库权限自动 skip，CI 依然全绿）。
"""
import inspect
import os
import sys

import pymysql
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import src.dict_admin_pages as dp  # noqa: E402
import src.org_db as org_db  # noqa: E402
from src import ui_kit  # noqa: E402
from src import broadcast_db as bdb  # noqa: E402
from src.collab_pages import _render_broadcast_banner  # noqa: E402
from src.mysql_db import (  # noqa: E402
    CREATE_TABLES_SQL,
    PROJECT_BROADCASTS_TABLE_SQL,
)
from src.users_db import create_user  # noqa: E402

TEST_DB = "web_word_fx30_test"  # 运维按 fx 批次授权（同 fx18/fx20/fx25 口径）


def _mysql_reachable() -> bool:
    """MySQL 连通探测（与 test_collab_pages._mysql_reachable 同口径）。"""
    from pymysql.cursors import DictCursor

    try:
        from src import mysql_db as db

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


# ============================================
# 会话/夹具公共件
# ============================================

_ME_ADMIN = {"id": 7, "username": "fx30chief", "display_name": "主编甲",
             "role": "viewer", "roles": ["dict_admin"], "active": True}
_ME_VIEWER = {"id": 8, "username": "fx30viewer", "display_name": "路人",
              "role": "viewer", "roles": ["viewer"], "active": True}


def _reject_reason(result):
    """RV14-5 结果体契约：{"id": int|None, "reason": str|None} —— 取拒绝原因，
    顺带断言 id=None（拒绝体不携带 id）。"""
    assert result["id"] is None
    return result["reason"]


_FAKE_BROADCASTS = [
    {"id": 12, "project_id": 3, "project_name": "现汉七",
     "title": "出版导出暂停", "body": "周五 22:00 起库维护，导出暂停半日。",
     "published_by": 7, "created_at": "2026-11-10 09:00:00",
     "publisher_username": "chief", "publisher_display_name": "主编甲"},
    {"id": 5, "project_id": 4, "project_name": "动词典",
     "title": "试标轮开启", "body": "金标比对达标，正式轮下周开放。",
     "published_by": None, "created_at": "2026-11-09 10:00:00",
     "publisher_username": None, "publisher_display_name": None},
]


class _StubCol:
    """form/columns 的上下文假体（FX-26 同款最小件）。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubSt:
    """st 假体：广播段所需控件（form/text_input/text_area/submit＋输出族）。

    submit=True 模拟「📢 发布广播」提交；text 输入返回预设值（模拟用户键入）。
    记录调用供断言（kind, text）。
    """

    def __init__(self, submit=False, title="标题X", body="正文Y"):
        self.submit = submit
        self.title = title
        self.body = body
        self.messages = []       # (kind, text)

    def form(self, *args, **kwargs):
        return _StubCol()

    def text_input(self, *args, **kwargs):
        return self.title

    def text_area(self, *args, **kwargs):
        return self.body

    def form_submit_button(self, *args, **kwargs):
        return self.submit

    class _ExpCtx:
        """expander 上下文桩（RV21-2 广播历史可达面）。"""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def expander(self, *args, **kwargs):
        self.messages.append(("expander", args[0] if args else ""))
        return _StubSt._ExpCtx()

    def markdown(self, *args, **kwargs):
        self.messages.append(("markdown", args[0] if args else ""))

    def caption(self, *args, **kwargs):
        self.messages.append(("caption", args[0] if args else ""))

    def info(self, *args, **kwargs):
        self.messages.append(("info", args[0] if args else ""))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args[0] if args else ""))

    def success(self, *args, **kwargs):
        self.messages.append(("success", args[0] if args else ""))

    def error(self, *args, **kwargs):
        self.messages.append(("error", args[0] if args else ""))

    def rerun(self):
        self.messages.append(("rerun", ""))

    def texts(self, kind=None):
        return [t for k, t in self.messages if kind is None or k == kind]

    def joined(self):
        return "\n".join(self.texts())


def _clear_flash_queue():
    """清空 ui_kit 会话提示队列（裸模式 session_state 跨用例残留）。"""
    st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


class _ExplodeCursor:
    """假 get_db_cursor：任何进入即抛 pymysql.Error（降级路径守约用）。"""

    def __call__(self, *args, **kwargs):
        raise pymysql.Error("db down (stub)")


class _CaptureCursor:
    """假 cursor：捕获 SQL 与参数、按预设返回 lastrowid（发布落库守约用）。"""

    def __init__(self, store, lastrowid=42):
        self._store = store
        self._lastrowid = lastrowid

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._store.append((sql, params))

    def fetchone(self):
        # RV17-1 连通探测（SELECT 1）取行走此——桩恒返回存活行
        return {"1": 1}

    def fetchall(self):
        return []

    @property
    def lastrowid(self):
        return self._lastrowid


# ============================================
# 1. DDL 注册（mysql_db 单一事实源）
# ============================================

class TestDdlRegistration:
    """project_broadcasts 入 CREATE_TABLES_SQL；列/索引/软引用口径。"""

    def test_table_in_create_tables_sql(self):
        """CREATE_TABLES_SQL 含 project_broadcasts 建表语句（全量建表覆盖）。"""
        joined = "\n".join(CREATE_TABLES_SQL)
        assert "CREATE TABLE IF NOT EXISTS project_broadcasts" in joined

    def test_last_entry_references_constant(self):
        """CREATE_TABLES_SQL 引用 PROJECT_BROADCASTS_TABLE_SQL 常量本体
        （同源引用，与 FX-25 同款；zh_dict/category_study 动态注册在其后
        追加条目，故断言「在列」而非「末位」）。"""
        assert any(sql is PROJECT_BROADCASTS_TABLE_SQL for sql in CREATE_TABLES_SQL)

    def test_required_columns(self):
        """任务书 DDL 口径：id PK / title VARCHAR(200) NOT NULL / body TEXT NOT NULL
        / published_by INT NULL / created_at DATETIME DEFAULT CURRENT_TIMESTAMP。"""
        ddl = PROJECT_BROADCASTS_TABLE_SQL
        assert "id INT AUTO_INCREMENT PRIMARY KEY" in ddl
        assert "title VARCHAR(200) NOT NULL" in ddl
        assert "body TEXT NOT NULL" in ddl
        assert "published_by INT NULL" in ddl
        assert "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl

    def test_project_index_pair(self):
        """索引 (project_id, id)（按项目倒序列表的覆盖索引口径）。"""
        assert "INDEX idx_pb_project_id (project_id, id)" in PROJECT_BROADCASTS_TABLE_SQL

    def test_published_by_rv2_3_comment(self):
        """published_by 注释注明 RV2-3 留痕列第 1 类（NULL=系统作业）。"""
        assert "RV2-3" in PROJECT_BROADCASTS_TABLE_SQL
        assert "系统作业" in PROJECT_BROADCASTS_TABLE_SQL

    def test_no_foreign_key_soft_reference(self):
        """project_id 软引用 org 域：DDL 无 FOREIGN KEY（广播是留痕公示，
        项目壳变动不级联删史；发布/查询侧用在册校验兜真实性）。"""
        assert "FOREIGN KEY" not in PROJECT_BROADCASTS_TABLE_SQL.upper().replace(
            "软引用", "")

    def test_ensure_broadcast_table_idempotent_sql(self):
        """ensure_broadcast_table 执行的就是同一常量（两路同源，CI/无库也校验）。"""
        src = inspect.getsource(bdb.ensure_broadcast_table)
        assert "PROJECT_BROADCASTS_TABLE_SQL" in src


# ============================================
# 2. 数据层：常量 / 参数清洗 / 发布闸门 / 降级
# ============================================

class TestBroadcastConstants:
    """数据层常量口径（与页面/规范对齐，防漂移）。"""

    def test_list_limit_default_is_twenty(self):
        """历史小表/列表默认上限 20（任务书 limit=20 口径）。"""
        assert bdb.LIST_LIMIT_DEFAULT == 20

    def test_publish_allowed_roles_dict_admin(self):
        """发布允许角色 = 词典管理员（规范 §8 职责表）。"""
        assert bdb.PUBLISH_ALLOWED_ROLES == ("dict_admin",)

    def test_page_history_limit_aligned(self):
        """页面历史小表上限与数据层默认同源（FX30_BROADCAST_HISTORY=20）。"""
        assert dp.FX30_BROADCAST_HISTORY == bdb.LIST_LIMIT_DEFAULT == 20


class TestPublishGate:
    """发布闸门：非词典管理员拒（PermissionError，不吞）；非法参数静默拒。"""

    def test_non_dict_admin_rejected_before_db(self, monkeypatch):
        """viewer（legacy/快照两形态）→ PermissionError；DB 与 org 域零触达。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        monkeypatch.setattr(org_db, "list_projects",
                            lambda: (_ for _ in ()).throw(AssertionError("org 域被触达")))
        for actor in (_ME_VIEWER, {"id": 9, "role": "annotator"},
                      {"id": 10, "roles": ["editor"]}, None, "user", 42):
            with pytest.raises(PermissionError):
                bdb.publish_broadcast(1, "标题", "正文", actor=actor)

    def test_unregistered_project_rejected(self, monkeypatch):
        """项目不在册（org_db.list_projects 无此 id）→ 结果体 id=None＋reason
        归因「不在册」（RV14-5：拒绝走 reason 字段，静默拒绝＋error 日志）。"""
        monkeypatch.setattr(org_db, "list_projects",
                            lambda: [{"id": 3, "name": "现汉七"}])
        for actor in (_ME_ADMIN, {"id": 1, "roles": ["dict_admin"]}):
            result = bdb.publish_broadcast(999, "标题", "正文", actor=actor)
            assert result["id"] is None
            assert "不在册" in result["reason"]

    def test_registered_project_inserts(self, monkeypatch):
        """在册项目 → INSERT 参数化落库；标题去空白；published_by=actor id。"""
        store = []
        monkeypatch.setattr(org_db, "list_projects",
                            lambda: [{"id": 3, "name": "现汉七"}])
        monkeypatch.setattr(bdb, "get_db_cursor",
                            lambda *a, **k: _CaptureCursor(store, lastrowid=42))
        result = bdb.publish_broadcast(3, "  维护公告  ", "正文", actor=_ME_ADMIN)
        assert result == {"id": 42, "reason": None}
        sql, params = store[-1]
        assert "INSERT INTO project_broadcasts" in sql
        assert params == (3, "维护公告", "正文", 7)

    def test_actor_without_id_publishes_null_by(self, monkeypatch):
        """actor 合法角色但缺 id → published_by 落 NULL（RV2-3 系统作业留痕口径）。"""
        store = []
        monkeypatch.setattr(org_db, "list_projects", lambda: [{"id": 1}])
        monkeypatch.setattr(bdb, "get_db_cursor",
                            lambda *a, **k: _CaptureCursor(store, lastrowid=1))
        new_id = bdb.publish_broadcast(
            1, "系统公示", "自动作业", actor={"roles": ["dict_admin"]})
        assert new_id["id"] == 1 and new_id["reason"] is None
        assert store[-1][1][3] is None

    def test_invalid_params_rejected_before_db(self, monkeypatch):
        """空标题/空正文/超长标题/非法 project_id → id=None 且 reason 非空
        （RV14-5 归因）；DB 与 org 域零触达。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        monkeypatch.setattr(org_db, "list_projects",
                            lambda: (_ for _ in ()).throw(AssertionError("org 域被触达")))
        assert _reject_reason(bdb.publish_broadcast(3, "   ", "正文", actor=_ME_ADMIN))
        assert _reject_reason(bdb.publish_broadcast(3, None, "正文", actor=_ME_ADMIN))
        assert _reject_reason(bdb.publish_broadcast(3, "标题", "  ", actor=_ME_ADMIN))
        assert _reject_reason(bdb.publish_broadcast(3, "标题", None, actor=_ME_ADMIN))
        assert "超长" in _reject_reason(
            bdb.publish_broadcast(3, "x" * 201, "正文", actor=_ME_ADMIN))
        for bad_pid in (True, None, 0, -1, "3x", 3.5):
            assert _reject_reason(
                bdb.publish_broadcast(bad_pid, "标题", "正文", actor=_ME_ADMIN)
            ), bad_pid

    def test_body_over_limit_rejected_with_reason(self, monkeypatch):
        """正文超 10000 字符（RV14-5 应用层闸）→ 归因「正文超长」，零 DB 触达。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        result = bdb.publish_broadcast(3, "标题", "字" * (bdb.MAX_BODY_LEN + 1),
                                       actor=_ME_ADMIN)
        assert result["id"] is None
        assert "正文超长" in result["reason"]

    def test_db_down_returns_none(self, monkeypatch):
        """库不可用 → id=None、reason 归因「数据库」（记日志不抛，降级口径）。"""
        monkeypatch.setattr(org_db, "list_projects", lambda: [{"id": 3}])
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        result = bdb.publish_broadcast(3, "标题", "正文", actor=_ME_ADMIN)
        assert result["id"] is None
        assert "数据库" in result["reason"]


class TestQueryGuards:
    """查询辅助的入参清洗与降级（不碰库的形态先收口）。"""

    def test_list_broadcasts_invalid_project_no_db(self, monkeypatch):
        """非法 project_id / limit → 清洗后走默认或空清单；库不可用返回 []。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        for bad in (True, None, 0, -1, "abc"):
            assert bdb.list_broadcasts(bad) == [], bad
        # limit 非法收口到默认（仍会触库 → 降级 []），不在册判断不炸
        assert bdb.list_broadcasts(3, limit=0) == []
        assert bdb.list_broadcasts(3, limit=-5) == []

    def test_latest_for_user_invalid_uid_no_db(self, monkeypatch):
        """非法 user_id → []（无在册项目语义），库零触达。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        for bad in (True, None, 0, -1, "abc"):
            assert bdb.latest_for_user(bad) == [], bad

    def test_degradation_triple(self, monkeypatch):
        """降级三态：publish→拒绝体（reason 归因数据库）/ list→[] /
        latest→None（表未建同径）。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        monkeypatch.setattr(org_db, "list_projects", lambda: [{"id": 3}])
        result = bdb.publish_broadcast(3, "标题", "正文", actor=_ME_ADMIN)
        assert result["id"] is None and "数据库" in result["reason"]
        assert bdb.list_broadcasts(3) == []
        assert bdb.latest_for_user(7) is None

    def test_ensure_table_never_raises(self, monkeypatch):
        """ensure_broadcast_table 降级不抛（页面自举容错口径）。"""
        monkeypatch.setattr(bdb, "get_db_cursor", _ExplodeCursor())
        bdb.ensure_broadcast_table()  # 不抛即过


# ============================================
# 3. 往返集成（真实 MySQL；无权限/无库自动 skip）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过广播往返集成测试")
class TestBroadcastRoundtrip:
    """发布 → 按项目列出 → latest_for_user 聚合（独立测试库，前后 DROP）。"""

    @pytest.fixture
    def fx30_db(self, monkeypatch):
        """建空测试库＋最小表链（users→org→broadcast），测试结束 DROP。

        建库失败（无授权）skip；monkeypatch db.MYSQL_DATABASE 让连接池按键
        隔离指向测试库（与 test_collab_pages 同口径）。
        """
        from pymysql.cursors import DictCursor
        from src import mysql_db as db

        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT,
            user=db.MYSQL_USER, password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET, cursorclass=DictCursor, connect_timeout=3,
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
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过广播集成测试: {e}")
        conn.close()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        yield
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT,
            user=db.MYSQL_USER, password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET, cursorclass=DictCursor,
            connect_timeout=3, autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()

    def _create_base_tables(self) -> None:
        """users(+user_roles) + dictionary_projects/project_members + 广播表。"""
        from src.users_db import ensure_user_tables

        ensure_user_tables()
        org_db.ensure_org_tables()
        bdb.ensure_broadcast_table()

    def test_publish_list_roundtrip(self, fx30_db):
        """发布 2 条 → list_broadcasts 倒序逐字段一致；发布人名随行。"""
        self._create_base_tables()
        chief = create_user("fx30_chief", "pass_fx30_1", "主编甲", "admin")
        member = create_user("fx30_member", "pass_fx30_1", "成员乙", "viewer")
        project = org_db.create_project("现汉七广播项目", chief, ["motion"])
        assert project and project > 0
        org_db.add_member(project, member, "editor", granted_by=chief)

        actor = {"id": chief, "role": "admin"}      # legacy admin → dict_admin
        first = bdb.publish_broadcast(project, "第一条公告", "正文一",
                                      actor=actor)["id"]
        second = bdb.publish_broadcast(project, "第二条公告", "正文二",
                                       actor=actor)["id"]
        assert first and second and second > first

        items = bdb.list_broadcasts(project)
        assert [it["id"] for it in items] == [second, first]   # 倒序
        assert [it["title"] for it in items] == ["第二条公告", "第一条公告"]
        assert items[0]["body"] == "正文二"
        assert items[0]["project_id"] == project
        assert items[0]["published_by"] == chief
        assert items[0]["publisher_username"] == "fx30_chief"
        assert items[0]["publisher_display_name"] == "主编甲"
        assert items[0]["created_at"] is not None

    def test_latest_for_user_aggregates(self, fx30_db):
        """latest_for_user：在册项目各取最新一条；非成员为 []； chief 两项目两条。"""
        self._create_base_tables()
        chief = create_user("fx30_chief2", "pass_fx30_1", "主编丙", "admin")
        outsider = create_user("fx30_out", "pass_fx30_1", "局外人", "viewer")
        p1 = org_db.create_project("项目一", chief, ["motion"])
        p2 = org_db.create_project("项目二", chief, ["motion"])
        actor = {"id": chief, "role": "admin"}
        bdb.publish_broadcast(p1, "P1-旧", "x", actor=actor)
        p1_latest = bdb.publish_broadcast(p1, "P1-新", "y", actor=actor)["id"]
        p2_latest = bdb.publish_broadcast(p2, "P2-新", "z", actor=actor)["id"]

        mine = bdb.latest_for_user(chief)
        assert [it["id"] for it in mine] == [p2_latest, p1_latest]  # 广播 id 倒序
        by_project = {it["project_id"]: it for it in mine}
        assert by_project[p1]["title"] == "P1-新"     # 每项目只留最新一条
        assert by_project[p2]["title"] == "P2-新"
        assert by_project[p1]["project_name"] == "项目一"

        assert bdb.latest_for_user(outsider) == []    # 未入册 → 空清单（不渲染段）

    def test_gate_and_validation_in_db(self, fx30_db):
        """真实库下复验：非词典管理员抛 PermissionError；不在册项目拒绝体；
        空 title/body 拒绝体；published_by=NULL 行读回发布人为空。"""
        self._create_base_tables()
        chief = create_user("fx30_chief3", "pass_fx30_1", "主编丁", "admin")
        ann = create_user("fx30_ann3", "pass_fx30_1", "标注戊", "annotator")
        project = org_db.create_project("闸门项目", chief, ["motion"])
        actor = {"id": chief, "role": "admin"}

        with pytest.raises(PermissionError):
            bdb.publish_broadcast(project, "越权标题", "正文",
                                  actor={"id": ann, "role": "annotator"})
        with pytest.raises(PermissionError):
            bdb.publish_broadcast(project, "越权标题", "正文", actor=None)
        assert "不在册" in _reject_reason(
            bdb.publish_broadcast(999999, "不在册", "正文", actor=actor))
        assert _reject_reason(bdb.publish_broadcast(project, "", "正文", actor=actor))
        assert _reject_reason(bdb.publish_broadcast(project, "标题", "  ", actor=actor))

        sys_row = bdb.publish_broadcast(
            project, "系统公示", "自动作业", actor={"roles": ["dict_admin"]})["id"]
        rows = bdb.list_broadcasts(project)
        assert len(rows) == 1 and rows[0]["id"] == sys_row
        assert rows[0]["published_by"] is None
        assert rows[0]["publisher_username"] is None

    def test_table_missing_degrades(self, fx30_db):
        """广播表未建（只建 users/org）→ 读 [] / None、发布拒绝体，不抛。
        本用例 org 表空册 → 项目不在册先于触库被拒（RV14-5 归因「不在册」）。"""
        from src.users_db import ensure_user_tables

        ensure_user_tables()
        org_db.ensure_org_tables()   # 刻意不调 ensure_broadcast_table
        assert bdb.list_broadcasts(1) == []
        assert bdb.latest_for_user(1) is None
        result = bdb.publish_broadcast(
            1, "标题", "正文", actor={"roles": ["dict_admin"]})
        assert result["id"] is None and "不在册" in result["reason"]


# ============================================
# 4. 页面层：项目成员 tab 广播段（stub st）
# ============================================

def _patch_section(monkeypatch, stub, items="unset", publish="unset",
                   gate="pass"):
    """铺广播段假体：st / guards / broadcast_db 两函数。"""
    monkeypatch.setattr(dp, "st", stub)
    if gate == "pass":
        monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME_ADMIN)
    elif gate == "deny":
        def _deny():
            raise PermissionError("仅词典管理员可执行词典数据写操作。")
        monkeypatch.setattr(dp.guards, "require_dict_admin", _deny)
    if items != "unset":
        monkeypatch.setattr(dp.broadcast_db, "list_broadcasts",
                            lambda project_id, limit=20: items)
    if publish != "unset":
        monkeypatch.setattr(dp.broadcast_db, "publish_broadcast",
                            lambda *a, **k: publish)
    return stub


class TestBroadcastSection:
    """词典管理区·项目成员 tab「📢 项目广播」段（FX-30）。"""

    def test_section_renders_form_and_history(self, monkeypatch):
        """form＋两输入＋提交按钮在场；历史小表逐行渲染（系统作业口径）。"""
        stub = _patch_section(monkeypatch, _StubSt(), items=_FAKE_BROADCASTS)
        dp._render_broadcast_section(3, _ME_ADMIN)
        joined = stub.joined()
        assert "📢 项目广播" in joined
        assert 'key=f"dict_admin_bc_title_{project_id}"' in inspect.getsource(
            dp._render_broadcast_section)
        captions = stub.texts("caption")
        assert any("共 2 条" in c for c in captions)
        # 小表：标题/正文/发布者如实；published_by=None → 「系统作业」
        assert "出版导出暂停" in joined and "试标轮开启" in joined
        assert "导出暂停半日" in joined
        assert "主编甲" in joined and "系统作业" in joined

    def test_section_empty_history_caption(self, monkeypatch):
        """无广播/降级（list 返回 []）→ 引导灰注，不出表格。"""
        stub = _patch_section(monkeypatch, _StubSt(), items=[])
        dp._render_broadcast_section(3, _ME_ADMIN)
        joined = stub.joined()
        assert "暂无广播记录" in joined
        assert "🗂️ 该项目广播历史" not in joined

    def test_section_submit_success_flash_rerun(self, monkeypatch):
        """提交 → 中央闸门过 → publish → ui_kit.flash ＋ st.rerun；无 st.success。"""
        stub = _patch_section(monkeypatch, _StubSt(submit=True),
                              publish={"id": 9, "reason": None})
        _clear_flash_queue()
        dp._render_broadcast_section(3, _ME_ADMIN)
        assert any(k == "rerun" for k, _ in stub.messages)
        queue = st.session_state.get(ui_kit._FLASH_QUEUE_KEY) or []
        assert queue and "广播已发布" in queue[-1]["message"] and "#9" in queue[-1]["message"]
        assert not stub.texts("success")     # RV12-2：禁 st.success 回潮
        _clear_flash_queue()

    def test_section_submit_gate_denied(self, monkeypatch):
        """中央闸门拒绝 → st.error 转述；publish 一次不触；不 rerun。"""
        publish_calls = []
        stub = _StubSt(submit=True)
        _patch_section(monkeypatch, stub, gate="deny", publish=None)
        monkeypatch.setattr(dp.broadcast_db, "publish_broadcast",
                            lambda *a, **k: publish_calls.append(a))
        dp._render_broadcast_section(3, _ME_ADMIN)
        assert any(k == "error" and "仅词典管理员" in t for k, t in stub.messages)
        assert publish_calls == [] and not stub.texts("rerun")

    def test_section_submit_rejected_none(self, monkeypatch):
        """数据层返回 None（空标题/不在册/库失败）→ st.warning 灰注，不 rerun。"""
        stub = _patch_section(monkeypatch, _StubSt(submit=True), publish=None)
        dp._render_broadcast_section(3, _ME_ADMIN)
        assert any(k == "warning" and "广播未发布" in t for k, t in stub.messages)
        assert not stub.texts("rerun")

    def test_section_submit_unexpected_exception(self, monkeypatch):
        """数据层意外异常 → 防御性 st.warning，不崩段。"""
        stub = _StubSt(submit=True)
        _patch_section(monkeypatch, stub)

        def _boom(*a, **k):
            raise RuntimeError("exploded")
        monkeypatch.setattr(dp.broadcast_db, "publish_broadcast", _boom)
        dp._render_broadcast_section(3, _ME_ADMIN)
        assert any(k == "warning" and "未发布" in t for k, t in stub.messages)
        assert not stub.texts("rerun")

    def test_section_flash_discipline(self):
        """RV12-2 纪律：成功反馈 ui_kit.flash ＋ st.rerun，代码路径无 st.success 调用。"""
        src = inspect.getsource(dp._render_broadcast_section)
        assert "ui_kit.flash" in src and "st.rerun" in src
        # docstring 口径注释可提及 st.success，代码调用（st.success(）不得在场
        assert "st.success(" not in src

    def test_section_widget_keys_scoped_by_project(self):
        """widget key 一律 'dict_admin_' 前缀；广播段三键按项目作用域化
        （RV15-2：切项目键不同，会话 widget 状态不残留陈旧载荷）。"""
        src = inspect.getsource(dp._render_broadcast_section)
        assert 'key=f"dict_admin_bc_title_{project_id}"' in src
        assert 'key=f"dict_admin_bc_body_{project_id}"' in src
        assert 'f"dict_admin_broadcast_form_{project_id}"' in src
        assert 'key="dict_admin_bc_title"' not in src  # 旧全局键已退役

    def test_section_caption_echoes_publish_target(self, monkeypatch):
        """RV15-2：段头 caption 回显「发布目标：{项目名}」（调用方带出项目名）。"""
        stub = _patch_section(monkeypatch, _StubSt(), items=[])
        dp._render_broadcast_section(3, _ME_ADMIN, project_name="现汉七")
        captions = stub.texts("caption")
        assert any("发布目标：现汉七" in c and "id 3" in c for c in captions)

    def test_history_rows_truncate_long_body(self):
        """长正文截断 80 字＋省略号；时间原样；发布者回退 username→#id。"""
        rows = dp._broadcast_history_rows([
            {"created_at": "2026-11-10 09:00:00", "title": "T", "body": "字" * 100,
             "published_by": 7, "publisher_display_name": "主编甲"},
            {"created_at": None, "title": "T2", "body": "短",
             "published_by": 9, "publisher_display_name": None,
             "publisher_username": "u9"},
            {"created_at": None, "title": "T3", "body": "",
             "published_by": 11, "publisher_display_name": None,
             "publisher_username": None},
            {"created_at": None, "title": "T4", "body": None,
             "published_by": None},
        ])
        assert rows[0][2] == "字" * 80 + "…" and len(rows[0][2]) == 81
        assert rows[1][3] == "u9"
        assert rows[2][3] == "#11"
        assert rows[3][3] == "系统作业"       # RV2-3：NULL=系统作业


# ============================================
# 5. 页面层：协作收件箱顶部广播条（stub st）
# ============================================

class TestBroadcastBanner:
    """协作收件箱「📢 项目广播」条（FX-30，规范「收件箱类目」展示面）。"""

    def test_banner_none_degraded_gray_note(self, monkeypatch):
        """latest_for_user=None（库降级）→ 灰注 caption，无标题段无卡片。"""
        stub = _StubSt()
        cp = sys.modules["src.collab_pages"]
        monkeypatch.setattr(cp, "st", stub)
        monkeypatch.setattr(cp.broadcast_db, "latest_for_user", lambda uid: None)
        _render_broadcast_banner(_ME_ADMIN)
        joined = stub.joined()
        assert "取数暂不可用" in joined
        assert "📢 项目广播</h3>" not in joined

    def test_banner_empty_renders_nothing(self, monkeypatch):
        """空清单（无在册项目/无广播）→ 整段不渲染（不占收件箱版面）。"""
        stub = _StubSt()
        monkeypatch.setattr(sys.modules["src.collab_pages"], "st", stub)
        monkeypatch.setattr(sys.modules["src.collab_pages"].broadcast_db,
                            "latest_for_user", lambda uid: [])
        _render_broadcast_banner(_ME_ADMIN)
        assert stub.messages == []

    def test_banner_not_logged_in_no_call(self, monkeypatch):
        """未登录 → 不取数不渲染（入口登录门之外的兜底）。"""
        stub = _StubSt()
        cp = sys.modules["src.collab_pages"]
        monkeypatch.setattr(cp, "st", stub)
        calls = []
        monkeypatch.setattr(cp.broadcast_db, "latest_for_user",
                            lambda uid: calls.append(uid))
        _render_broadcast_banner(None)
        _render_broadcast_banner("user")
        assert calls == [] and stub.messages == []

    def test_banner_renders_items(self, monkeypatch):
        """条目在场：标题＋正文＋时间＋发布者＋项目名；NULL 发布者=系统作业。"""
        stub = _StubSt()
        cp = sys.modules["src.collab_pages"]
        monkeypatch.setattr(cp, "st", stub)
        monkeypatch.setattr(cp.broadcast_db, "latest_for_user",
                            lambda uid: _FAKE_BROADCASTS)
        _render_broadcast_banner(_ME_ADMIN)
        joined = stub.joined()
        assert "📢 项目广播</h3>" in joined
        assert "出版导出暂停" in joined and "周五 22:00 起库维护" in joined
        assert "试标轮开启" in joined
        assert "2026-11-10 09:00:00" in joined
        assert "主编甲" in joined and "现汉七" in joined
        assert "系统作业" in joined          # published_by=None 行
        assert "每项目一条" in "\n".join(stub.texts("caption"))

    def test_banner_escapes_html(self, monkeypatch):
        """标题/正文/项目名插值全过 _html_escape（恶意标注不成 HTML）。"""
        stub = _StubSt()
        cp = sys.modules["src.collab_pages"]
        monkeypatch.setattr(cp, "st", stub)
        monkeypatch.setattr(cp.broadcast_db, "latest_for_user", lambda uid: [
            {"id": 1, "project_id": 1, "project_name": "<b>evil</b>",
             "title": "<script>alert(1)</script>", "body": "<img src=x>",
             "published_by": 1, "created_at": "t",
             "publisher_username": "u", "publisher_display_name": None},
        ])
        _render_broadcast_banner(_ME_ADMIN)
        joined = stub.joined()
        assert "<script>" not in joined and "<img " not in joined
        assert "&lt;script&gt;" in joined and "&lt;b&gt;evil&lt;/b&gt;" in joined


# ============================================
# 6. AppTest 冒烟：发布成功 flash ＋ 收件箱条目在场
# ============================================

_DICT_ADMIN_SMOKE_SCRIPT = (
    "import streamlit as st\n"
    "from src import ui_kit\n"
    "from src.dict_admin_pages import _render_broadcast_section\n"
    "ui_kit.pop_and_render_flash()\n"     # 与 app.main() 每轮渲染开头同序
    "_render_broadcast_section(3, st.session_state['user'])\n"
)


def test_apptest_publish_smoke_flash(monkeypatch):
    """AppTest 冒烟（发布页）：表单可填、提交按钮在场；点击后数据层执行 →
    flash 经 pop_and_render_flash 弹出（数据层打桩，不触真库）。"""
    monkeypatch.setattr(dp.broadcast_db, "list_broadcasts",
                        lambda project_id, limit=20: _FAKE_BROADCASTS)
    seen = {}

    def _fake_publish(project_id, title, body, actor=None):
        seen["args"] = (project_id, title, body, actor)
        return {"id": 9, "reason": None}   # RV14-5 结果体契约

    monkeypatch.setattr(dp.broadcast_db, "publish_broadcast", _fake_publish)
    at = AppTest.from_string(_DICT_ADMIN_SMOKE_SCRIPT, default_timeout=60)
    at.session_state["user"] = dict(_ME_ADMIN)
    at.run()
    assert not at.exception
    # 表单控件与提交按钮在场
    assert at.text_input and at.text_area
    submit = [b for b in at.button if "发布广播" in b.label]
    assert submit, "发布广播提交按钮未渲染"
    # 填表 → 提交 → 数据层收到 actor 与内容 → flash 弹出
    at.text_input[0].set_value("冒烟标题")
    at.text_area[0].set_value("冒烟正文")
    submit[0].click().run()
    assert not at.exception
    assert seen["args"][:3] == (3, "冒烟标题", "冒烟正文")
    assert seen["args"][3].get("id") == _ME_ADMIN["id"]
    assert any("广播已发布" in str(s.value) and "#9" in str(s.value)
               for s in at.success)
    # 历史小表仍渲染（打桩恒返回假清单）
    markdown_text = "".join(str(md.value) for md in at.markdown)
    assert "出版导出暂停" in markdown_text


_INBOX_SMOKE_SCRIPT = (
    "import streamlit as st\n"
    "from src import ui_kit\n"
    "from src.collab_pages import _render_broadcast_banner\n"
    "ui_kit.pop_and_render_flash()\n"
    "_render_broadcast_banner(st.session_state['user'])\n"
)


def test_apptest_inbox_smoke_item_present(monkeypatch):
    """AppTest 冒烟（收件箱）：广播条目在场（标题/正文/发布者），不抛异常。"""
    cp = sys.modules["src.collab_pages"]
    monkeypatch.setattr(cp.broadcast_db, "latest_for_user",
                        lambda uid: _FAKE_BROADCASTS)
    at = AppTest.from_string(_INBOX_SMOKE_SCRIPT, default_timeout=60)
    at.session_state["user"] = dict(_ME_ADMIN)
    at.run()
    assert not at.exception
    markdown_text = "".join(str(md.value) for md in at.markdown)
    assert "📢 项目广播</h3>" in markdown_text
    assert "出版导出暂停" in markdown_text and "周五 22:00 起库维护" in markdown_text
    assert "主编甲" in markdown_text and "系统作业" in markdown_text


def test_apptest_inbox_smoke_empty_silent(monkeypatch):
    """AppTest 冒烟（收件箱空态）：无广播整段不渲染、无异常。"""
    cp = sys.modules["src.collab_pages"]
    monkeypatch.setattr(cp.broadcast_db, "latest_for_user", lambda uid: [])
    at = AppTest.from_string(_INBOX_SMOKE_SCRIPT, default_timeout=60)
    at.session_state["user"] = dict(_ME_ADMIN)
    at.run()
    assert not at.exception
    markdown_text = "".join(str(md.value) for md in at.markdown)
    assert "📢 项目广播</h3>" not in markdown_text


# ============================================
# 7. docstring 覆盖（R6-11 纪律，钉住本批新文件防回潮）
# ============================================

class TestR611:
    def test_broadcast_db_all_functions_have_docstrings(self):
        """src/broadcast_db.py 全函数（含降级分支）docstring 覆盖 100%。"""
        import ast

        path = os.path.join(PROJECT_ROOT, "src/broadcast_db.py")
        tree = ast.parse(open(path).read())
        missing = [
            f"{n.name}:{n.lineno}" for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and ast.get_docstring(n) is None
        ]
        assert not missing, f"src/broadcast_db.py 缺 docstring: {missing}"
