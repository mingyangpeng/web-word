"""R9 端到端回归扩展：十轮 review 修复关键行为固化（防退化专用测试面）。

把十轮 review 已修复的关键行为钉成回归（修复面与既有专项测试互补 —— 本文件
只固化「用户可感知的端到端行为」，不重复专项测试的签名/源级细目）：

  一、权限回归（R1 固化）
    * 八会话 × 关键页可见性矩阵（AppTest）：侧边栏 radio 选项逐会话对表
      （未登录/legacy admin/legacy reviewer/授予式 annotator/reviewer/
      dict_admin/editor/纯 viewer）—— 表来自 _PAGE_ACCESS_SIX 权威语义，
      越权放大或误伤收窄即刻红；
    * 关键页直入闸门（纵深防御）：低权/未登录注入 page 直入受保护页，
      页级 role gate 文案在场（radio 可见性不是闸门）；
    * 低权直调六写函数 PermissionError（users_db 直调面 R1-1）；
    * update_draft 劫持拒绝（R1-3：非作者/不传 author_id 打他人草稿 →
      False，内容不被篡改）；
    * adjudicate_final 冒名拒绝（R1-4：adjudicator_id ≠ actor['id'] →
      False 且零留痕；非 dict_admin/缺 actor 同拒；合法终裁留痕在）；
    * 登出全清（R1-6：user/业务键全清、白名单基建键保留、页面回搜索）。

  二、输入回归（R2 固化）
    * SVG/脚本伪装 png 上传拒绝（R2-2 魔数一致性：声明 image 须 PNG/JPEG
      魔数；audio/video 顶着异形魔数同拒；嗅探不出不误伤；data=None 维持
      既有调用旧形态）；
    * date 2024-02-30 专用拒绝（R2-3：正则过但 fromisoformat 拒 =
      「格式对但日期不存在」，表单侧二分专用报错）；
    * 例证正文 20000 上限（R2-6：20001 拒、20000 收，页面注明在场）；
    * collab LIKE 字面匹配（R2-5：walk_100 不误中 walkz100 —— 下划线按
      字面，前缀搜索仍正常）。

  三、一致性回归（R3 固化）
    * rollback 混用仲裁（R3-1：持久化事件在场 + 显式空清单 → 拒；显式
      非空但不同 → 拒；逐事件一致 → 放行）；
    * rolled_back 批次 persist 拒（R3-2：已回滚批次不可补写日志）；
    * remove_example 自动摘绑（R3-3：删例证前摘光其媒体绑定，绑定数 0）；
    * created_by 建号留痕（R3-5：users.created_by 与 user_roles.granted_by
      同取建号人；缺省 NULL；非法值拒建）。

  四、归因回归（R4 固化）
    * definitions 表缺失（pymysql 1146）时图谱页文案 = 「数据不可用（勿重跑
      灌库）」而非「未灌数据」—— 同一页面两种空态二分（R4-1 三口径）；
    * 离线侧边栏统计 metric = "—" 而非 0（R4-2：无法统计 ≠ 统计到零）；
    * MOCK 兜底卡片带「内置示例（非词典数据）」徽章（R4-6 来源披露）。

  五、复用回归（批次 10 R-1 收口固化）
    * speech 包 render_template_text 零 motion 词面残留（跨词类复用判据）；
    * motion 整句逐字护栏（收口 = 拼装表逐字迁移入包，渲染逐字不变）；
    * 引擎零词类拼装词面（grep 判据：M1a/自源点出发等不出现于引擎源）。

环境约定（对齐 tests/test_stage1_e2e.py 的专库模式）：

  * 专用测试库 ``web_word_review_regression_test``（独立隔离，不与其它模块
    的测试库互删）。当前 scripts/grant_local_mysql.sql **尚未授权**，未授权
    时库类用例自动 skip（提示见 fixture）；补齐授权所需 SQL：

        GRANT ALL PRIVILEGES ON `web\\_word\\_review\\_regression\\_test`.*
            TO 'web_word_user'@'127.0.0.1';
        GRANT ALL PRIVILEGES ON `web\\_word\\_review\\_regression\\_test`.*
            TO 'web_word_user'@'localhost';
        FLUSH PRIVILEGES;

  * 临时借库验证（如 CI 借已授权库跑本回归）可用环境变量
    ``REVIEW_REGRESSION_TEST_DB`` 覆写库名；缺省仍是
    web_word_review_regression_test；
  * MySQL 不可用 / 无建库权限 → 库类整类 skip（CI 无库依然全绿）；
    纯层（上传/date 校验、离线侧边栏、MOCK 徽章、批次 10 模板）无库全跑；
  * 数据层签名以各模块实际实现为准（先 grep 核对过）。
"""

import inspect
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import src.mysql_db as db  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
TEST_DB = (os.environ.get("REVIEW_REGRESSION_TEST_DB")
           or "web_word_review_regression_test").strip()
TIMEOUT = 180
PREFIX = "r9_"
PASSWORD = "R9#regression-pass"

# 专库按整库重建隔离；sense_ref/词目等业务键用 99xx 段避免撞既有种子。
LIKE_VERBS = ("walk_100", "walkz100", "walking")


def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不动库）。"""
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

requires_db = pytest.mark.skipif(
    not HAS_MYSQL, reason=f"MySQL 不可用，跳过 R9 回归库用例（{TEST_DB}）")


def _q(sql, params=()):
    """测试内直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


# ============================================
# 八会话（与 test_r1_fixes 同形态：id 由 fixture 回填库内真实账号；
# 授予式用户 = legacy role 列与 user_roles 授予不一致，R1-2 修复的对象形态）
# ============================================

_SESSIONS = {
    "legacy_admin": {"id": 0, "username": PREFIX + "admin",
                     "display_name": "内置管理员", "role": "admin", "roles": []},
    "legacy_reviewer": {"id": 0, "username": PREFIX + "rev",
                        "display_name": "存量审校", "role": "reviewer", "roles": []},
    "granted_annotator": {"id": 0, "username": PREFIX + "grant_ann",
                          "display_name": "授予标注", "role": "viewer",
                          "roles": ["annotator", "viewer"]},
    "granted_reviewer": {"id": 0, "username": PREFIX + "grant_rev",
                         "display_name": "授予审校", "role": "viewer",
                         "roles": ["reviewer", "viewer"]},
    "granted_dict_admin": {"id": 0, "username": PREFIX + "grant_chief",
                           "display_name": "授予词典管理", "role": "annotator",
                           "roles": ["dict_admin", "annotator"]},
    "granted_editor": {"id": 0, "username": PREFIX + "grant_editor",
                       "display_name": "授予撰写", "role": "viewer",
                       "roles": ["editor", "viewer"]},
    "pure_viewer": {"id": 0, "username": PREFIX + "view",
                    "display_name": "只读", "role": "viewer", "roles": ["viewer"]},
}

# 八会话 × 关键页可见性矩阵（期望集合 = _PAGE_ACCESS_SIX 权威表语义的投影；
# 基础页 annotate 虽全员可见，页级另有 role gate —— 直入闸门单独断言）。
_ALL_PAGES = {
    "ai_hub", "annotate", "cluster", "corpus", "dict_admin", "domain", "graph",
    "help", "lexical", "model_settings", "reliability", "search", "semantic",
    "submission", "template", "users_admin", "writing",
}
_EXPECTED_VISIBLE = {
    "anon": {"annotate", "corpus", "domain", "graph", "help", "search"},
    "legacy_admin": _ALL_PAGES,
    "legacy_reviewer": _ALL_PAGES - {"users_admin", "dict_admin", "model_settings"},
    "granted_annotator": _ALL_PAGES - {"users_admin", "dict_admin",
                                       "model_settings", "reliability", "lexical"},
    "granted_reviewer": _ALL_PAGES - {"users_admin", "dict_admin", "model_settings"},
    "granted_dict_admin": _ALL_PAGES - {"users_admin"},
    "granted_editor": _ALL_PAGES - {"users_admin", "dict_admin",
                                    "model_settings", "reliability"},
    "pure_viewer": _ALL_PAGES - {"submission", "users_admin", "reliability",
                                 "dict_admin", "lexical", "model_settings"},
}


@pytest.fixture(scope="module")
def r9_env():
    """整库重建（DROP+CREATE 专库）→ 真实 schema + 各域建表 + 八会话账号，
    yield 共享状态 → 还原全局并 DROP。账号 id 回填 _SESSIONS（AppTest 注入
    与直调闸门共用同一批真实账号）。"""
    conn_params = dict(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
        autocommit=True,
    )
    conn = pymysql.connect(**conn_params)
    try:
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
                cur.execute(
                    f"CREATE DATABASE `{TEST_DB}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        except pymysql.err.OperationalError as e:
            pytest.skip(
                f"账号对 {TEST_DB} 无建库权限，跳过 R9 回归库用例（补授权 SQL "
                f"见模块 docstring）: {e}"
            )
    finally:
        conn.close()

    old_database = db.MYSQL_DATABASE
    state: dict = {}
    try:
        db.MYSQL_DATABASE = TEST_DB
        assert db.init_database(), "测试库初始化失败（无 DDL 权限或连接失败）"

        from src.dict_admin_db import ensure_dict_admin_tables
        from src.lexical_db import ensure_lexical_tables
        from src.media_db import ensure_media_tables
        from src.users_db import (
            create_user,
            ensure_user_tables,
            grant_role,
        )
        from src.writing_db import ensure_writing_tables

        ensure_user_tables()
        ensure_dict_admin_tables()
        ensure_media_tables()
        ensure_lexical_tables()
        ensure_writing_tables()

        # 内置 admin 在场（ensure_user_tables 幂等建出），留 id 备用
        admins = _q("SELECT id FROM users WHERE username='admin' AND active=1")
        state["builtin_admin_id"] = int(admins[0]["id"]) if admins else 0

        uid_admin = create_user(PREFIX + "admin", PASSWORD, "内置管理员", "admin")
        uid_rev = create_user(PREFIX + "rev", PASSWORD, "存量审校", "reviewer")
        uid_ann = create_user(PREFIX + "grant_ann", PASSWORD, "授予标注", "viewer")
        assert grant_role(uid_ann, "annotator") is True
        uid_grev = create_user(PREFIX + "grant_rev", PASSWORD, "授予审校", "viewer")
        assert grant_role(uid_grev, "reviewer") is True
        uid_chief = create_user(PREFIX + "grant_chief", PASSWORD,
                                "授予词典管理", "annotator")
        assert grant_role(uid_chief, "dict_admin") is True
        uid_editor = create_user(PREFIX + "grant_editor", PASSWORD,
                                 "授予撰写", "viewer")
        assert grant_role(uid_editor, "editor") is True
        uid_view = create_user(PREFIX + "view", PASSWORD, "只读", "viewer")

        for key, uid in (
            ("legacy_admin", uid_admin), ("legacy_reviewer", uid_rev),
            ("granted_annotator", uid_ann), ("granted_reviewer", uid_grev),
            ("granted_dict_admin", uid_chief), ("granted_editor", uid_editor),
            ("pure_viewer", uid_view),
        ):
            _SESSIONS[key]["id"] = int(uid)
        state["uid_admin"] = int(uid_admin)
        state["uid_reviewer"] = int(uid_grev)
        state["uid_annotator"] = int(uid_ann)
        state["uid_chief"] = int(uid_chief)
        state["uid_editor"] = int(uid_editor)
        state["uid_viewer"] = int(uid_view)
        yield state
    finally:
        db.MYSQL_DATABASE = old_database
        # 丢弃指向已删库的连接池条目与页面级缓存槽位（键含库名）
        pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
        getattr(db, "_connection_pools", {}).pop(pool_key, None)
        try:
            db.get_full_word_graph.clear()
        except Exception:  # noqa: BLE001 —— 老版本无此缓存函数时忽略
            pass
        conn = pymysql.connect(**conn_params)
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        finally:
            conn.close()


# ============================================
# AppTest 辅助（test_r1_fixes 同手法）
# ============================================

def _pget(at, key, default=None):
    """AppTest 会话读取（SafeSessionState 不支持 .get()）。"""
    try:
        return at.session_state[key]
    except Exception:  # noqa: BLE001
        return default


def _page_text(at) -> str:
    """主区域全部文本（markdown/caption/标题/各消息通道）。"""
    parts = []
    for accessor in ("markdown", "caption", "header", "subheader", "title",
                     "info", "warning", "error", "success"):
        elements = getattr(at, accessor, None) or []
        parts.extend(str(e.value) for e in elements)
    return "\n".join(parts)


def _any_warning_containing(at, needle: str) -> bool:
    return any(needle in str(w.value) for w in at.warning)


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _run_page_as(page: str, user):
    """注入会话用户/页面后直接打开（模拟「会话残留/越权直入」路径）。"""
    at = _new_at()
    if user is not None:
        at.session_state["user"] = user
    at.session_state["page"] = page
    at.run()
    return at


def _sessions() -> dict:
    assert _SESSIONS["legacy_admin"]["id"] > 0, "r9_env fixture 未就位"
    return _SESSIONS


# ============================================
# 一、权限回归（R1 固化）
# ============================================

@requires_db
class TestR1VisibilityMatrix:
    """八会话 × 关键页可见性矩阵 + 直入闸门（AppTest，专库）。"""

    @pytest.mark.parametrize("session_key", sorted(_EXPECTED_VISIBLE))
    def test_sidebar_visibility_per_session(self, r9_env, session_key):
        """侧边栏 radio 选项逐会话对表（越权放大/误伤收窄都算退化）。

        注：本版 Streamlit 的 AppTest radio.options 已是 format_func 加工后的
        展示标签 —— 用页面体系同源的 page_label 反查回页面键再对表。
        """
        from src.page_guides import PAGE_KEYS, page_label

        label_to_key = {page_label(k): k for k in PAGE_KEYS}
        user = None if session_key == "anon" else _sessions()[session_key]
        at = _new_at()
        if user is not None:
            at.session_state["user"] = user
        at.run()
        assert not at.exception, session_key
        radios = list(at.sidebar.radio)
        assert radios, f"{session_key}: 页面切换 radio 未渲染"
        got = set()
        for option in radios[0].options:
            assert option in label_to_key, f"{session_key}: 未知选项标签 {option!r}"
            got.add(label_to_key[option])
        expected = _EXPECTED_VISIBLE[session_key]
        assert got == expected, (
            f"{session_key} 可见页与权威表不符：多出 {sorted(got - expected)}，"
            f"缺失 {sorted(expected - got)}"
        )

    @pytest.mark.parametrize(
        "page, session_key, needle",
        [
            ("submission", "anon", "请先登录"),
            ("annotate", "anon", "请先登录"),
            ("writing", "anon", "请先登录后再访问释义撰写与审校工作台"),
            ("submission", "pure_viewer", "无权限"),
            ("annotate", "pure_viewer", "无权限"),
            ("reliability", "pure_viewer", "仅对 reviewer / admin 开放"),
            ("reliability", "granted_annotator", "仅对 reviewer / admin 开放"),
            ("users_admin", "granted_annotator", "用户管理仅管理员可用"),
            ("dict_admin", "granted_editor", "仅词典管理员可访问词典管理区"),
        ],
    )
    def test_page_gate_direct_entry(self, r9_env, page, session_key, needle):
        """关键页直入闸门（纵深防御）：radio 不可见 ≠ 不可直入，页级门必须拦。"""
        at = _run_page_as(page, _sessions().get(session_key))
        assert not at.exception, (page, session_key)
        assert needle in _page_text(at), (
            f"{session_key} 直入 {page} 应见闸门文案 {needle!r}，"
            f"实际页面：{_page_text(at)[:200]!r}"
        )

    def test_authorized_sessions_pass_gates(self, r9_env):
        """放行态抽查：授予式用户过 annotate/reliability 门、dict_admin 过区门。"""
        at = _run_page_as("annotate", _sessions()["granted_annotator"])
        assert not at.exception
        assert not _any_warning_containing(at, "无权限")
        assert "提交流" in _page_text(at)

        at = _run_page_as("reliability", _sessions()["granted_reviewer"])
        assert not at.exception
        assert not _any_warning_containing(at, "仅对 reviewer / admin 开放")
        assert "还没有已提交的标注" in _page_text(at)  # 空库降级哨兵

        at = _run_page_as("users_admin", _sessions()["legacy_admin"])
        assert not at.exception
        assert "用户管理" in _page_text(at)

        chief = _sessions()["granted_dict_admin"]
        at = _run_page_as("dict_admin", chief)
        assert not at.exception
        assert not _any_warning_containing(at, "仅词典管理员可访问词典管理区")
        assert "主编驾驶舱" in _page_text(at)


@requires_db
class TestR1LogoutFullClear:
    """R1-6 登出全清（AppTest）：业务键不跨登出存活、白名单保留。"""

    def test_logout_clears_business_keys_and_user(self, r9_env):
        at = _new_at()
        at.run()
        at.session_state["user"] = _sessions()["granted_annotator"]
        at.run()  # radio options 按新角色重渲染
        at.session_state["verb_result"] = {"verb": "walk"}
        at.session_state["show_result"] = True
        at.session_state["_display_def_cache"] = {"walk": "x"}
        at.session_state["hot_filter"] = "跑"
        at.session_state["_user_db_backed"] = True
        at.session_state["page"] = "submission"
        at.run()
        assert _pget(at, "user") is not None
        assert "提交流" in _page_text(at), "受保护页未按注入用户渲染"

        logout = [b for b in at.sidebar.button if "退出登录" in str(b.label)]
        assert logout, "退出按钮未找到"
        logout[0].click()
        at.run()
        assert not at.exception
        assert _pget(at, "user") is None, "退出后 session user 未清除"
        for key in ("verb_result", "show_result", "_display_def_cache",
                    "hot_filter", "_user_db_backed"):
            assert _pget(at, key) is None, f"业务键 {key} 登出后残留（R1-6）"
        assert _pget(at, "sidebar_collapsed") is not None, "白名单基建键被误清"
        assert _pget(at, "_user_tables_ready") is not None, "白名单基建键被误清"
        assert _pget(at, "page") == "search", "残留页未回搜索页"
        assert _any_warning_containing(at, "请先登录"), "登出提示未出现"


@requires_db
class TestR1DataLayerGates:
    """R1 直调面/写路径收口（数据层真库）。"""

    def test_low_privilege_direct_calls_raise_permission_error(self, r9_env):
        """R1-1：viewer 直调六写函数一律 PermissionError（闸门在函数入口）。"""
        from src.users_db import (
            change_password,
            create_user,
            grant_role,
            revoke_role,
            set_active,
            set_role,
        )

        viewer_actor = dict(_sessions()["pure_viewer"])
        chief_actor = dict(_sessions()["granted_dict_admin"])
        chief_id, viewer_id = r9_env["uid_chief"], r9_env["uid_viewer"]

        with pytest.raises(PermissionError):
            create_user("r9_nope", PASSWORD, "不该存在", actor=viewer_actor)
        with pytest.raises(PermissionError):
            set_role(chief_id, "viewer", actor=viewer_actor)
        with pytest.raises(PermissionError):
            grant_role(chief_id, "sys_admin", actor=viewer_actor)
        with pytest.raises(PermissionError):
            revoke_role(chief_id, "viewer", actor=viewer_actor)
        with pytest.raises(PermissionError):
            set_active(chief_id, False, actor=viewer_actor)
        with pytest.raises(PermissionError):
            change_password(chief_id, "NewPass#123", actor=viewer_actor)
        # 非 dict 垃圾 actor fail-closed 同抛（不给「不校验」留旁路）
        with pytest.raises(PermissionError):
            set_role(chief_id, "viewer", actor="admin")

        # 对照：同一目标、足色 actor → 闸门放行（业务层无操作返回 False）
        assert grant_role(viewer_id, "viewer", actor=chief_actor) is False

    def test_update_draft_rejects_author_hijack(self, r9_env):
        """R1-3：update_draft 劫持拒绝 —— 非作者/缺 author_id 打他人草稿 →
        False 且内容不被篡改；作者本人带乐观锁照常改写。"""
        from src.writing_db import create_draft, update_draft

        author_id = r9_env["uid_editor"]
        hijacker_id = r9_env["uid_annotator"]
        vid = create_draft("motion:9901:9901", author_id, "作者初稿内容")
        assert vid > 0, "create_draft 应落行"

        assert update_draft(vid, 1, "劫持者的改写", author_id=hijacker_id) is False
        assert update_draft(vid, 1, "匿名劫持（不传 author_id）") is False
        rows = _q("SELECT content, status FROM definition_versions WHERE id=%s",
                  (vid,))
        assert rows and rows[0]["content"] == "作者初稿内容", "草稿内容被篡改"
        assert rows[0]["status"] == "draft"

        assert update_draft(vid, 1, "作者本人改稿", author_id=author_id) is True
        rows = _q("SELECT content FROM definition_versions WHERE id=%s", (vid,))
        assert rows[0]["content"] == "作者本人改稿"

    def test_adjudicate_final_rejects_impersonation_and_non_chief(self, r9_env):
        """R1-4：adjudicate_final 冒名拒绝 —— adjudicator_id ≠ actor['id'] →
        False 且零伪造留痕；非 dict_admin / 缺 actor 同拒；合法终裁留痕在。"""
        from src.writing_db import (
            adjudicate_final,
            create_draft,
            submit_for_review,
        )

        author_id = r9_env["uid_editor"]
        reviewer_id = r9_env["uid_reviewer"]
        chief_id = r9_env["uid_chief"]
        chief_actor = dict(_sessions()["granted_dict_admin"])
        reviewer_actor = dict(_sessions()["granted_reviewer"])

        vid = create_draft("motion:9902:9902", author_id, "待终裁稿")
        assert vid > 0
        assert submit_for_review(vid, reviewer_id) is True

        # 冒名：actor=词典管理员本人，却把留痕人写成 reviewer → False
        tasks_before = _q("SELECT id FROM review_tasks WHERE version_id=%s",
                          (vid,))
        assert adjudicate_final(vid, reviewer_id, "approved",
                                actor=chief_actor) is False
        tasks_after = _q("SELECT id FROM review_tasks WHERE version_id=%s", (vid,))
        assert len(tasks_after) == len(tasks_before), "冒名终裁留下伪造留痕行"
        row = _q("SELECT status FROM definition_versions WHERE id=%s", (vid,))[0]
        assert row["status"] == "in_review", "被拒终裁不得改状态"

        # 非 dict_admin（reviewer 会话、id 自匹配）→ False；缺 actor → False
        assert adjudicate_final(vid, reviewer_id, "approved",
                                actor=reviewer_actor) is False
        assert adjudicate_final(vid, chief_id, "approved", actor=None) is False

        # 合法终裁：adjudicator_id == actor['id'] 且 dict_admin → True + 留痕
        assert adjudicate_final(vid, chief_id, "approved",
                                actor=chief_actor) is True
        row = _q("SELECT status FROM definition_versions WHERE id=%s", (vid,))[0]
        assert row["status"] == "final"
        tasks = _q("SELECT reviewer_id, verdict FROM review_tasks "
                   "WHERE version_id=%s", (vid,))
        assert any(int(t["reviewer_id"]) == chief_id and t["verdict"] == "approved"
                   for t in tasks), "终裁留痕行缺失"


# ============================================
# 二、输入回归（R2 固化）
# ============================================

class TestR2UploadAndDateGuards:
    """R2-2 上传魔数一致性 + R2-3 date 真实性（纯函数，无库也跑）。"""

    def test_svg_disguised_as_png_rejected(self):
        """SVG/脚本伪装 png → 拒（「文件内容与扩展名不符」）；真 PNG/JPEG 放行。"""
        from src.dict_admin_pages import _validate_upload

        svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        err = _validate_upload("evil.png", len(svg), "image/png", svg)
        assert err is not None and "文件内容与扩展名不符" in err, err
        script = b"<script>alert(document.cookie)</script>"
        err = _validate_upload("evil.png", len(script), "image/png", script)
        assert err is not None and "文件内容与扩展名不符" in err, err

        # 真 PNG / JPEG 魔数 → 放行
        assert _validate_upload("ok.png", 8, "image/png",
                                b"\x89PNG\r\n\x1a\nrest") is None
        assert _validate_upload("ok.jpg", 8, "image/jpeg",
                                b"\xff\xd8\xff\xe0rest") is None

        # 声明 audio/video 而内容是 PNG → 同款拒绝（改名伪装）
        png_payload = b"\x89PNG\r\n\x1a\nrest"
        err = _validate_upload("x.mp3", len(png_payload), "audio/mpeg",
                               png_payload)
        assert err is not None and "文件内容与扩展名不符" in err, err
        # 嗅探不出（未知二进制）→ 不误伤（落盘后缀由资产形态兜底）
        assert _validate_upload("y.mp3", 8, "audio/mpeg",
                                b"\x00\x01\x02\x03\x04\x05\x06\x07") is None
        # data=None：既有调用方旧形态维持（跳过内容校验）
        assert _validate_upload("old.png", 8, "image/png") is None
        # data 不可读类型 → 拒而不抛
        err = _validate_upload("bad.png", 8, "image/png", object())
        assert err is not None and "文件内容不可读" in err, err

    def test_date_20240230_rejected_with_dedicated_error(self):
        """R2-3：2024-02-30（格式对但日期不存在）→ _coerce_value 拒；
        真实日历日期（含闰日 2024-02-29）放行；表单侧二分专用报错在场。"""
        from src.dict_admin_pages import _coerce_value

        assert _coerce_value("date", "2024-02-30") is None
        assert _coerce_value("date", "2023-02-29") is None      # 非闰年
        assert _coerce_value("date", "2024-13-01") is None
        assert _coerce_value("date", "2024/02/30") is None      # 格式不过正则
        assert _coerce_value("date", "2024-2-3") is None
        assert _coerce_value("date", "2024-02-29") == "2024-02-29"  # 闰日真实
        assert _coerce_value("date", "2024-02-28") == "2024-02-28"

        # 表单侧专用报错二分：正则过但 fromisoformat 拒 = 「日期不存在」
        src = inspect.getsource(
            __import__("src.dict_admin_pages", fromlist=["_render_write_value_form"])
            ._render_write_value_form)
        assert "日期不存在：年月日组合不是真实日历日期" in src
        assert "2024-02-30" in src
        assert "日期格式须为 YYYY-MM-DD。" in src

    def test_example_page_declares_20000_cap(self):
        """R2-6：页面表单注明 20000 上限与「超长拒收不落库」（与数据层同源）。"""
        from src.lexical_db import MAX_CONTENT_LEN
        from src.lexical_pages import _render_examples_tab

        assert MAX_CONTENT_LEN == 20000
        src = inspect.getsource(_render_examples_tab)
        assert "MAX_CONTENT_LEN" in src, "表单上限应与数据层常量同源"
        assert "超长拒收不落库" in src
        assert "新增失败：例证文本为空/超长" in src


@requires_db
class TestR2ContentLimitsAndCollabLike:
    """R2-6 例证 20000 上限（真库收/拒边界）+ R2-5 collab LIKE 字面匹配。"""

    def test_example_content_cap_boundary(self, r9_env):
        """20000 恰好收（落库可查回），20001 拒（add 返回 0 / update False）。"""
        from src.lexical_db import (
            MAX_CONTENT_LEN,
            add_example,
            update_example,
        )

        ok = add_example("motion:9903:9903", "例" * MAX_CONTENT_LEN,
                         source="composed", created_by=r9_env["uid_editor"])
        assert ok > 0, "恰好 20000 字符应放行落库"
        rows = _q("SELECT content FROM sense_examples WHERE id=%s", (ok,))
        assert len(rows[0]["content"]) == MAX_CONTENT_LEN

        assert update_example(ok, content="改" * MAX_CONTENT_LEN) is True
        assert add_example("motion:9903:9903", "例" * (MAX_CONTENT_LEN + 1)) == 0
        assert update_example(ok, content="改" * (MAX_CONTENT_LEN + 1)) is False
        rows = _q("SELECT content FROM sense_examples WHERE id=%s", (ok,))
        assert rows[0]["content"] == "改" * MAX_CONTENT_LEN, "超长更新不得落库"

    def test_collab_search_like_is_literal(self, r9_env):
        """R2-5：walk_100 按字面命中，不误中 walkz100（下划线不再是通配符）；
        普通前缀搜索照常工作。"""
        from src.collab_pages import _escape_like, _search_verbs
        from src.data_pages import _escape_like as _escape_like_ref

        # 转义与 data_pages 同源同口径（R2-5 修复点）
        assert _escape_like is _escape_like_ref
        assert _escape_like("walk_100") == "walk!_100"

        with db.get_db_cursor() as cursor:
            verb_ids = {}
            for verb in LIKE_VERBS:
                cursor.execute(
                    "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
                    "VALUES (%s, 'R2-5 回归种子', '{}')", (verb,))
                did = int(cursor.lastrowid)
                cursor.execute(
                    "INSERT INTO oald_senses (definition_id, sense_index, headword, "
                    "definition) VALUES (%s, 1, %s, 'seed sense')", (did, verb))
                verb_ids[verb] = did

        hits = [r["verb"] for r in _search_verbs("walk_100")]
        assert hits == ["walk_100"], f"walk_100 应只命中字面行，实际 {hits}"
        hits = [r["verb"] for r in _search_verbs("walkz100")]
        assert hits == ["walkz100"], f"walkz100 应只命中字面行，实际 {hits}"
        # 前缀正向对照：LIKE 本体未坏
        hits = sorted(r["verb"] for r in _search_verbs("walk"))
        assert hits == sorted(LIKE_VERBS)
        assert _search_verbs("") == []


# ============================================
# 三、一致性回归（R3 固化）
# ============================================

@requires_db
class TestR3ConsistencyRegression:
    """R3-1/R3-2/R3-3/R3-5 关键行为（真库，独立专库不与其它模块互删）。"""

    def _finished_batch(self):
        from src.dict_admin_db import finish_batch, start_batch

        bid = start_batch(1, "r9.xlsx", "ab" * 32, "custom_values", {},
                          started_by=1)
        assert bid > 0
        assert finish_batch(bid, 1, 1, 0) is True
        return bid

    def _text_field(self, code):
        from src.dict_admin_db import define_field

        fid = define_field(1, code, "语域", "word", "text", created_by=1)
        assert isinstance(fid, int) and fid > 0
        return fid

    def test_rollback_persisted_log_blocks_empty_explicit_list(self, r9_env):
        """R3-1：持久化事件在场 + 显式空清单 → 拒（矛盾），状态与数据均不动。"""
        from src.dict_admin_db import persist_revert_log, rollback_batch

        fid = self._text_field("r9_arb1")
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        assert rollback_batch(bid, []) is False
        assert str(_q("SELECT status FROM import_batches WHERE id=%s",
                      (bid,))[0]["status"]) == "finished"
        assert str(_q("SELECT status FROM custom_fields WHERE id=%s",
                      (fid,))[0]["status"]) == "active"

    def test_rollback_persisted_log_blocks_differing_explicit_list(self, r9_env):
        """R3-1：显式非空但与持久化集不同 → 拒（防架空持久化日志）。"""
        from src.dict_admin_db import persist_revert_log, rollback_batch

        fid = self._text_field("r9_arb2")
        other = self._text_field("r9_arb3")
        bid = self._finished_batch()
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is True
        assert rollback_batch(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": other},
        ]) is False
        for f in (fid, other):
            assert str(_q("SELECT status FROM custom_fields WHERE id=%s",
                          (f,))[0]["status"]) == "active"

    def test_rollback_identical_explicit_list_passes(self, r9_env):
        """R3-1 放行分支：逐事件一致 → 回滚生效（批次 rolled_back、行弃用）。"""
        from src.dict_admin_db import persist_revert_log, rollback_batch

        fid = self._text_field("r9_arb4")
        bid = self._finished_batch()
        events = [{"action": "insert", "table": "custom_fields", "row_id": fid}]
        assert persist_revert_log(bid, events) is True
        assert rollback_batch(bid, events) is True
        assert str(_q("SELECT status FROM import_batches WHERE id=%s",
                      (bid,))[0]["status"]) == "rolled_back"
        assert str(_q("SELECT status FROM custom_fields WHERE id=%s",
                      (fid,))[0]["status"]) == "deprecated"

    def test_rolled_back_batch_rejects_persist(self, r9_env):
        """R3-2：rolled_back 批次补写日志 → False，零落库（不可事后补账）。"""
        from src.dict_admin_db import persist_revert_log, rollback_batch

        fid = self._text_field("r9_guard")
        bid = self._finished_batch()
        assert rollback_batch(bid, []) is True  # 无持久化记录 → 显式空清单照旧放行
        assert persist_revert_log(bid, [
            {"action": "insert", "table": "custom_fields", "row_id": fid},
        ]) is False
        assert not _q("SELECT id FROM import_revert_log WHERE batch_id=%s", (bid,))

    def test_remove_example_auto_unbinds_media(self, r9_env, tmp_path):
        """R3-3：remove_example 删例证前自动摘其全部绑定（绑定数归 0，无孤儿）。"""
        from src.lexical_db import add_example, remove_example
        from src.media_db import bind_asset, register_asset

        path = tmp_path / "r9_unbind.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nr9-unbind-bytes")
        aid = register_asset(path, "image", "R9 摘绑素材",
                             "CC-BY-4.0（R9 回归）")
        assert aid > 0
        eid = add_example("motion:9904:9904", "摘绑例证文本",
                          created_by=r9_env["uid_editor"])
        assert eid > 0
        assert bind_asset(aid, "example", eid, "example_media") is True
        assert len(_q("SELECT id FROM media_bindings WHERE "
                      "anchor_type='example' AND anchor_id=%s", (eid,))) == 1

        assert remove_example(eid) is True
        assert not _q("SELECT id FROM sense_examples WHERE id=%s", (eid,))
        # R3-3 自动摘除：例证锚上绑定数 = 0
        assert _q("SELECT id FROM media_bindings WHERE "
                  "anchor_type='example' AND anchor_id=%s", (eid,)) == []

    def test_create_user_records_created_by(self, r9_env):
        """R3-5：created_by 落 users 列且 user_roles.granted_by 同取建号人；
        缺省 NULL（既有调用零破坏）；非法值拒建不落行。"""
        from src.users_db import create_user

        creator = create_user(PREFIX + "creator", PASSWORD, "建号管理员", "admin")
        assert isinstance(creator, int) and creator > 0

        u = create_user(PREFIX + "newbie", PASSWORD, "被建号新人", "viewer",
                        created_by=creator)
        assert isinstance(u, int) and u > 0
        row = _q("SELECT created_by FROM users WHERE id=%s", (u,))[0]
        assert int(row["created_by"]) == creator
        granted = _q("SELECT granted_by FROM user_roles WHERE user_id=%s "
                     "AND role='viewer'", (u,))
        assert [int(g["granted_by"]) for g in granted] == [creator]

        legacy = create_user(PREFIX + "legacy_new", PASSWORD, "缺省口径", "viewer")
        assert isinstance(legacy, int) and legacy > 0
        assert _q("SELECT created_by FROM users WHERE id=%s",
                  (legacy,))[0]["created_by"] is None

        before = len(_q("SELECT id FROM users"))
        for bad in (0, -1, "1", 999999):
            assert create_user(PREFIX + "bad", PASSWORD, "不该存在", "viewer",
                               created_by=bad) is None, bad
        assert len(_q("SELECT id FROM users")) == before, "非法 created_by 建了号"


# ============================================
# 四、归因回归（R4 固化）
# ============================================

class TestR4OfflineAttribution:
    """R4-2 离线侧边栏 "—" + R4-6 MOCK 来源徽章（断库/打桩，不连库）。"""

    def test_offline_sidebar_metrics_show_dash(self, monkeypatch):
        """DB_AVAILABLE=False 时六个统计 metric 显示 "—" 而非 0（R4-2）；
        反馈导出降级文案在场。"""
        from streamlit.testing.v1 import AppTest

        monkeypatch.setattr(db, "init_database", lambda *a, **k: False)
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        assert not at.exception
        metrics = {m.label: m.value for m in at.sidebar.metric}
        for label in ("总查询次数", "已收录词目", "词簇", "词间关系",
                      "平均评分", "总反馈数"):
            assert label in metrics, f"离线侧边栏缺 metric {label}"
            assert metrics[label] == "—", f"离线时 {label} 应为 —，实际 {metrics[label]!r}"
        assert any("数据库离线，反馈导出暂不可用" in str(c.value)
                   for c in at.sidebar.caption)

    def test_mock_card_carries_builtin_example_badge(self, monkeypatch):
        """R4-6：MOCK 兜底带 source="内置示例"，卡片渲染「内置示例（非词典
        数据）」徽章；DB/LLM 来源不渲染。"""
        import streamlit as real_st

        import src.app as app_module

        real_st.session_state.pop("_display_def_cache", None)
        monkeypatch.setattr(app_module, "get_definition_by_verb",
                            lambda verb: None)
        monkeypatch.setattr(app_module, "get_definition",
                            lambda verb, *a, **k: None)
        verb = next(iter(app_module.MOCK_DEFINITIONS))

        display = app_module.get_display_definition(verb)
        assert display.get("source") == "内置示例"
        html = app_module.render_card_core(verb)
        assert "内置示例（非词典数据）" in html

        # DB/LLM 来源 → 无徽章（来源分级不误标）
        monkeypatch.setattr(app_module, "get_display_definition",
                            lambda v: {"source": "oald"}, raising=False)
        assert app_module._mock_source_badge_html(verb) == ""
        real_st.session_state.pop("_display_def_cache", None)


@requires_db
class TestR4GraphPageAttribution:
    """R4-1 图谱页三口径二分（真库 + 真 1146）：表缺失 ≠ 未灌数据。"""

    def test_missing_definitions_table_says_unavailable_not_unloaded(self, r9_env):
        """DROP definitions 后图谱页 = 「数据不可用（勿重跑灌库）」；
        表在但空 = 「暂无词间关系数据」（未灌口径）。两种空态不得混报。

        借库验证时测试库可能带存量数据 —— 先 DROP definitions，让首跑的
        init_database 幂等建出**空表**，「未灌」口径才有确定前提。"""
        conn_params = dict(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            database=TEST_DB,  # 裸连接直选测试库（DROP TABLE 须先选中库）
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )

        def _drop_definitions():
            conn = pymysql.connect(**conn_params)
            try:
                with conn.cursor() as cur:
                    # word_senses 有 FK 指向 definitions —— 模拟缺表仅本次会话
                    # 关闭外键检查（不动库内约束定义）
                    cur.execute("SET FOREIGN_KEY_CHECKS=0")
                    cur.execute("DROP TABLE IF EXISTS definitions")
                    cur.execute("SET FOREIGN_KEY_CHECKS=1")
            finally:
                conn.close()

        try:
            _drop_definitions()
            db.get_full_word_graph.clear()
            at = _new_at()
            at.session_state["page"] = "graph"
            at.run()  # 首跑：init_database 幂等重建空 definitions → 「未灌」口径
            assert not at.exception
            assert "暂无词间关系数据" in _page_text(at), "表在但空应报「未灌」口径"

            _drop_definitions()  # 模拟表缺失（1146 面）；会话旗标在 → 不再建表
            db.get_full_word_graph.clear()
            at.run()
            assert not at.exception
            text = _page_text(at)
            assert "数据不可用：全库图谱读取失败" in text, (
                f"1146 应归因「数据不可用」，实际：{text[:300]!r}")
            assert "勿重跑灌库" in text, "降级披露应劝阻重跑灌库"
            assert "暂无词间关系数据" not in text, (
                "查询失败不得谎报「未灌数据」（R4-1 退化）")
        finally:
            db.get_full_word_graph.clear()
            # 恢复 definitions 表（init_database 幂等建表），还原模块共享环境
            assert db.init_database()


# ============================================
# 五、复用回归（批次 10 R-1 收口固化）
# ============================================

class TestBatch10SpeechReuseRegression:
    """speech 跨词类复用 + motion 逐字护栏（纯函数，无库也跑）。"""

    @pytest.fixture(scope="class")
    def te(self):
        from src import template_engine as te_module

        return te_module

    @pytest.fixture(scope="class")
    def motion_meta(self, te):
        from src.category_pack import load_pack

        return te._feature_meta(load_pack("motion"))

    @pytest.fixture(scope="class")
    def speech_meta(self, te):
        from src.category_pack import load_pack

        return te._feature_meta(load_pack("speech"))

    @staticmethod
    def _mkvector_motion(**overrides):
        base = {code: 0 for code in
                ["P1", "P2", "P3", "P4", "P5",
                 "M1a", "M1b", "M1c", "M1d", "M2",
                 "M3a", "M3b", "M3c", "M3d", "C1", "A1", "A2", "A3"]}
        base.update(overrides)
        return base

    @staticmethod
    def _speech_vector(**overrides):
        base = {"I1": 0, "I2": 0, "I3": 0, "S1": "oral", "R1": 0, "R2": 0,
                "A1": 0}
        base.update(overrides)
        return base

    def _motion_cluster_schema(self, te, motion_meta, vectors):
        from src.category_pack import load_pack

        meta = {"cluster_id": 901, "cluster_no": 1, "cluster_name": "合成簇",
                "size": len(vectors),
                "members": [{"sense_id": i, "lemma": f"w{i}", "sense_no": str(i),
                             "sense_label": f"义{i}"} for i, _ in enumerate(vectors)]}
        return te.derive_cluster_schema_from_members(
            meta, vectors, motion_meta,
            schema_defs=load_pack("motion")["schemas"]["schemas"])

    # motion 词面残留判据（R-1 收口 grep 口径：拼装词面不得回流入引擎/他包）
    _MOTION_RESIDUES = ("移动", "介质", "自源点出发", "主体不限", "动因")

    def test_speech_render_zero_motion_residue(self, te, speech_meta):
        """speech 包 render_template_text：词面全按 speech 拼装节出，
        零 motion 词面残留（跨词类复用判据 5/5 的防退化面）。"""
        text = te.render_template_text(
            speech_meta, self._speech_vector(I1=1, I2=1, I3=1, R2=1),
            {"name": "断言图式", "code": "ASSERT"}, [])
        assert text.startswith("【图式：断言图式】")
        assert "有受话" in text and "有引语" in text
        assert "以口头声道就话题作出陈述" in text
        assert "正式度中性" in text
        assert "[可变槽位: 无（全要素簇内共享）]" in text
        for residue in self._MOTION_RESIDUES:
            assert residue not in text, f"speech 渲染含 motion 词面残留 {residue!r}"

        # 换向量（书面声道/指令取向/正式度高/话题凸显）→ 仍零残留
        text2 = te.render_template_text(
            speech_meta,
            self._speech_vector(I1=1, I3=0, R1=1, R2=2, S1="written"),
            {"name": "指令图式", "code": "DIRECTIVE"}, [])
        assert text2.startswith("【图式：指令图式】")
        for residue in self._MOTION_RESIDUES:
            assert residue not in text2, f"speech 渲染含 motion 词面残留 {residue!r}"

    def test_motion_guard_sentences_verbatim(self, te, motion_meta):
        """motion 整句逐字护栏：收口 = 拼装表逐字迁移入包，两句基准渲染
        与收口前引擎输出逐字相同（错一字即退化）。"""
        run_vec = self._mkvector_motion(M1a=1, M1b=1, M2=1, M3a=1, C1=2, A1=1)
        m13 = self._mkvector_motion(M1a=1, M3a=1)
        vecs = [run_vec, m13, m13, m13]
        cluster_schema = self._motion_cluster_schema(te, motion_meta, vecs)
        tpl = te.build_template(
            {"sense_id": 1, "lemma": "run", "sense_no": "1",
             "sense_label": "足部奔跑义", "language": "en", "status": "目标",
             "tag": None, "register": None, "subject_type": None,
             "source_dict": "OALD10",
             "definition": "[intransitive]to move using your legs, "
                           "going faster than when you walk"},
            run_vec, cluster_schema, motion_meta)
        assert tpl["template_text"] == (
            "【图式：方式伴随图式】人/动物主体，以低速、一般方式在陆地介质中移动，"
            "动因自主；[可变槽位: 主体-动物=动物主体；情态急促度=一般；动因=自主]")

        flee_vec = self._mkvector_motion(P1=1, C1=1, M2=2, M3a=1)
        cluster_schema2 = self._motion_cluster_schema(te, motion_meta, [flee_vec] * 4)
        tpl2 = te.build_template(
            {"sense_id": 9, "lemma": "flee", "sense_no": "1",
             "sense_label": "逃离义", "language": "en", "status": "目标",
             "tag": None, "register": None, "subject_type": None,
             "source_dict": "OALD10", "definition": "[intransitive]to leave"},
            flee_vec, cluster_schema2, motion_meta)
        assert tpl2["template_text"] == (
            "【图式：源点脱离图式】主体不限，自源点出发，以低速、急促方式在陆地介质"
            "中移动，动因受迫；[可变槽位: 无（全要素簇内共享）]")

    def test_engine_source_free_of_motion_assembly_faces(self, te):
        """R-1 收口 grep 判据：motion 拼装词面/特征码不再出现于引擎源
        （拼装表只能活在范畴包 template_assembly 节）。"""
        engine_src = inspect.getsource(te)
        for token in ("M1a", "M3a", "自源点出发", "陆地介质", "动因自主"):
            assert token not in engine_src, f"引擎源残留 motion 词面 {token!r}"

    def test_speech_assembly_resolves_from_pack_not_engine(self, te):
        """speech 拼装节确从范畴包解析（缺节 fail-closed，不回退 motion）。"""
        from src.category_pack import load_pack

        pack = load_pack("speech")
        assembly = (pack["schemas"] or {}).get("template_assembly")
        assert isinstance(assembly, dict) and assembly, (
            "speech 包缺 template_assembly 节")
        # 言说动词词面在拼装节内（含 concat 子段递归查找），而非引擎硬编码
        blobs = []

        def _walk(node):
            if isinstance(node, dict):
                blobs.append(str(node.get("text") or ""))
                for frag in (node.get("fragments") or {}).values():
                    blobs.append(str(frag))
                for child in node.get("concat") or []:
                    _walk(child)
            elif isinstance(node, list):
                for child in node:
                    _walk(child)

        _walk(assembly.get("segments") or [])
        assert any("就话题" in blob for blob in blobs), (
            "speech 拼装节应含言说动词词面（就话题）")
