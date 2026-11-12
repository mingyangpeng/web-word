"""R3 集成与回归测试 —— 真实登录流 / 角色×页面权限矩阵 / 断库降级（AppTest）。

与 tests/test_pages.py 的分工：
  * test_pages.py 直接向 session_state 注入 user（页面级渲染契约）；
  * 本文件走**真实登录表单**（填用户名/密码 → 点登录 → 会话就位），覆盖
    「登录表单 → verify_login_full → session user（四键+roles）→ 角色分派」
    的完整接缝（R3 清单 5；批次 3-K 六角色会话升级），并把 角色×页面 权限
    矩阵固化为可执行断言（R3 清单 1 + 批次 3 六角色可见性）。

数据库：独立测试库 web_word_users_test（与 test_users_db.py 同一手法 ——
CREATE DATABASE + patch db.MYSQL_DATABASE，连接池按键含库名互不污染）；
MySQL 不可用或账号无建库权限时整模块 skip，CI（无数据库）依然全绿。
断库降级用例（TestDbUnavailableDegrade）把 MySQL 指向必然拒绝连接的端口，
不依赖任何数据库，始终可跑。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import src.mysql_db as db  # noqa: E402
from src.page_guides import PAGE_KEYS, page_label  # noqa: E402
from src.users_db import create_user, ensure_user_tables  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
TEST_DB = "web_word_users_test"
TIMEOUT = 180

# 测试账号（username → (password, display_name, role)）；display_name 特意含
# HTML 特殊字符，兼做转义回归（R3 清单 7）
_R3_ADMIN = ("r3_admin", "r3-admin-pw", "管理员<b>甲</b>", "admin")
_R3_REVIEWER = ("r3_rev", "r3-rev-pw", "审核员&乙", "reviewer")
_R3_CODER = ("r3_ann", "r3-ann-pw", "标注员'丙", "annotator")
_R3_VIEWER = ("r3_view", "r3-view-pw", "只读\"丁", "viewer")
_R3_ESCAPE = ("r3_esc", "r3-esc-pw", "<b>x</b>&跑", "annotator")
_R3_USERS = (_R3_ADMIN, _R3_REVIEWER, _R3_CODER, _R3_VIEWER, _R3_ESCAPE)


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


def _new_at() -> "object":
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _form_login(at, username: str, password: str):
    """侧边栏登录表单真实提交（填账号密码 → 点「登录」提交按钮 → rerun）。"""
    inputs = {t.key: t for t in at.sidebar.text_input}
    inputs["login_username"].set_value(username)
    inputs["login_password"].set_value(password)
    submit = [b for b in at.sidebar.button
              if b.form_id and "登录" in str(b.label)]
    assert submit, "登录提交按钮未找到"
    submit[0].click()
    at.run()
    return at


def _nav_buttons(at) -> list:
    """侧边栏导航按钮（批次 22 升级：radio → 按钮式真侧边栏）。

    导航按钮在 st.sidebar.container(key="ls_nav") 内按七区序渲染，label
    即 page_label（与登录/退出/热门动词等按钮以 PAGE_KEYS 键集区分）。
    返回按渲染序排列的按钮元素（顺序即七区序）。
    """
    label2key = {page_label(k): k for k in PAGE_KEYS}
    out = []
    for b in at.sidebar.button:
        if str(b.label) in label2key:  # label=page_label 值（非键）
            out.append(b)
    return out


def _radio_keys(at) -> list:
    """侧边栏可见页键（批次 22 起经导航按钮还原；函数名保留兼容调用面）。"""
    label2key = {page_label(k): k for k in PAGE_KEYS}
    return [label2key[str(b.label)] for b in _nav_buttons(at)
            if str(b.label) in label2key]


def _nav_click(at, key: str):
    """点导航按钮切页（on_click 回调写 session_state["page"] 后 rerun）。"""
    for b in _nav_buttons(at):
        if str(b.label) == page_label(key):
            b.click()
            at.run()
            return
    raise AssertionError(f"导航按钮不存在: {key}")


def _run_page_as(page: str, user: dict):
    """直接注入会话用户并打开页面（模拟「会话残留强行进入」隐藏页的真实路径：
    隐藏页不在该角色 radio 选项里，无法经 radio 点击到达，只能以残留会话态
    直入 —— 与 test_pages.py 同一手法；入口 role gate 必须拦下）。"""
    at = _new_at()
    at.session_state["user"] = user
    at.session_state["page"] = page
    at.run()
    return at


# ============================================
# 模块级测试库（建库失败 → 整模块 skip）
# ============================================

@pytest.fixture(scope="module")
def r3_env():
    import pymysql

    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.close()
    except pymysql.err.OperationalError as e:
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 R3 集成测试: {e}")

    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    try:
        assert db.init_database(), "测试库初始化失败"
        ensure_user_tables()
        for username, password, display_name, role in _R3_USERS:
            uid = create_user(username, password, display_name, role)
            assert isinstance(uid, int) and uid > 0, f"建测试账号失败: {username}"
        yield
    finally:
        db.MYSQL_DATABASE = old_db  # 先还原全局再删库（与 test_users_db 同约定）
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()


# ============================================
# 清单 5：真实登录表单 → session user
# ============================================

class TestLoginFlow:
    """登录成功/失败路径（经侧边栏登录表单，非 session 注入）。"""

    def test_login_success_sets_session_user(self, r3_env):
        """正确密码：session user 就位（规范 §6-5 结构），登录框换成退出按钮。"""
        at = _new_at()
        at.run()
        assert not at.exception
        assert _pget(at, "user") is None  # 未登录

        at = _form_login(at, "r3_ann", "r3-ann-pw")
        assert not at.exception
        user = _pget(at, "user")
        assert isinstance(user, dict)
        # 批次 3-K 六角色会话：verify_login_full 返回规范五字段 —— 旧四键
        # 逐字段不变（role 仍为旧 users.role 列值，向后兼容）+ roles 六角色
        # 列表（优先级降序）；无 password_hash，哈希不出数据层
        assert user["username"] == "r3_ann"
        assert user["role"] == "annotator"
        assert user["roles"] == ["annotator"]
        assert user["display_name"] == "标注员'丙"
        assert set(user.keys()) == {"id", "username", "display_name", "role", "roles"}
        # 登录框消失，退出按钮在场
        assert not any(t.key == "login_username" for t in at.sidebar.text_input)
        assert any("退出登录" in str(b.label) for b in at.sidebar.button)

    def test_login_must_change_password_banner(self, r3_env):
        """批次 3-K ①：管理员签发初始口令（must_change_password=1）→ 登录后横幅。

        create_user 建号即置 must_change_password=1（r3_env 的测试账号全部
        如此），登录成功后侧边栏应出现强制改密横幅（指向用户管理页改密）。
        """
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_view", "r3-view-pw")
        assert not at.exception
        assert any("初始口令未修改" in str(c.value) for c in at.sidebar.caption)

    def test_must_change_password_banner_clears_after_change(self, r3_env):
        """批次 3-K ①：改密成功（change_password 清零标志）后横幅消失。

        专用账号 r3_chg，不动模块级共享账号（否则影响后续矩阵用例登录）。
        """
        from src.users_db import change_password, create_user

        uid = create_user("r3_chg", "r3-chg-pw", "改密用户", "viewer")
        assert isinstance(uid, int) and uid > 0
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_chg", "r3-chg-pw")
        assert not at.exception
        assert any("初始口令未修改" in str(c.value) for c in at.sidebar.caption)
        assert change_password(int(uid), "r3-chg-new-pw")
        at.run()
        assert not at.exception
        assert not any("初始口令未修改" in str(c.value) for c in at.sidebar.caption)

    def test_login_wrong_password_no_user(self, r3_env):
        """错误密码：无 session user + 统一失败文案（防枚举，规范 §6）。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_ann", "definitely-wrong")
        assert not at.exception
        assert _pget(at, "user") is None
        assert any("用户名或密码错误" in str(e.value) for e in at.sidebar.error)

    def test_login_escapes_html_display_name(self, r3_env):
        """display_name 含 HTML 特殊字符：会话存原文，侧边栏渲染必须转义（清单 7）。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_esc", "r3-esc-pw")
        assert not at.exception
        user = _pget(at, "user")
        assert user is not None and user["display_name"] == "<b>x</b>&跑"

        sidebar_md = "\n".join(str(m.value) for m in at.sidebar.markdown)
        assert "&lt;b&gt;x&lt;/b&gt;&amp;跑" in sidebar_md, "侧边栏未转义 display_name"
        assert "<b>x</b>" not in sidebar_md, "display_name 原文泄漏进 HTML"

    def test_sidebar_self_change_password_flow(self, r3_env):
        """批次 4-N：侧边栏「🔑 修改密码」自助改密 expander（旧密码＋新密码＋确认）。

        三段：两次新密码不一致 → error 不落库；旧密码错 → error 不落库
        （防越权改密）；旧密码对 + 长度合规 → 落库成功（旧口令立即失效、
        新口令可登录、must_change_password 横幅随之消失）。
        """
        from src.users_db import change_password, create_user, verify_login

        uid = create_user("r3_selfpw", "r3-selfpw-pw", "自助改密用户", "viewer")
        assert isinstance(uid, int) and uid > 0

        at = _new_at()
        at.run()
        at = _form_login(at, "r3_selfpw", "r3-selfpw-pw")
        assert not at.exception
        # 初始口令横幅在场（create_user 置 must_change_password=1）
        assert any("初始口令未修改" in str(c.value) for c in at.sidebar.caption)

        expanders = [e for e in at.sidebar.expander if "修改密码" in str(e.label)]
        assert expanders, "侧边栏缺「🔑 修改密码」expander"
        inputs = {t.key: t for t in at.sidebar.text_input}
        assert {"self_pw_old", "self_pw_new", "self_pw_again"} <= set(inputs), \
            "自助改密表单缺三输入框"
        submit = [b for b in at.sidebar.button
                  if b.form_id and "修改密码" in str(b.label)]
        assert submit, "「修改密码」提交按钮未找到"

        # ① 两次新密码不一致：error，不落库
        inputs["self_pw_old"].set_value("r3-selfpw-pw")
        inputs["self_pw_new"].set_value("r3-selfpw-new1")
        inputs["self_pw_again"].set_value("r3-selfpw-different")
        submit[0].click()
        at.run()
        assert not at.exception
        assert any("两次新密码" in str(e.value) for e in at.sidebar.error)
        assert verify_login("r3_selfpw", "r3-selfpw-pw") is not None, "口令不应被改"

        # ② 旧密码错误：error，不落库（改密须验证当前口令）
        inputs = {t.key: t for t in at.sidebar.text_input}
        inputs["self_pw_old"].set_value("totally-wrong")
        inputs["self_pw_new"].set_value("r3-selfpw-new1")
        inputs["self_pw_again"].set_value("r3-selfpw-new1")
        submit = [b for b in at.sidebar.button
                  if b.form_id and "修改密码" in str(b.label)]
        submit[0].click()
        at.run()
        assert not at.exception
        assert any("当前密码不正确" in str(e.value) for e in at.sidebar.error)
        assert verify_login("r3_selfpw", "r3-selfpw-pw") is not None, "口令不应被改"

        # ③ 正确旧密码 + 合规新密码：成功落库（旧口令失效、横幅消失）
        inputs = {t.key: t for t in at.sidebar.text_input}
        inputs["self_pw_old"].set_value("r3-selfpw-pw")
        inputs["self_pw_new"].set_value("r3-selfpw-new2")
        inputs["self_pw_again"].set_value("r3-selfpw-new2")
        submit = [b for b in at.sidebar.button
                  if b.form_id and "修改密码" in str(b.label)]
        submit[0].click()
        at.run()
        assert not at.exception
        assert any("密码已修改" in str(s.value) for s in at.sidebar.success), \
            "自助改密成功后应 st.success"
        assert verify_login("r3_selfpw", "r3-selfpw-pw") is None, "旧口令应立即失效"
        assert verify_login("r3_selfpw", "r3-selfpw-new2") is not None, "新口令应可登录"
        at.run()
        assert not any("初始口令未修改" in str(c.value) for c in at.sidebar.caption), \
            "改密成功后 must_change_password 横幅应消失"
        # change_password 直接调用不破坏（对照：数据层接口不受影响）
        assert change_password(uid, "r3-selfpw-new3")


# ============================================
# 清单 1：角色 × 页面 权限矩阵（真实登录后逐页实测）
# ============================================

class TestRoleMatrix:
    """四角色 × 受保护页面的分派矩阵（规范 §1/§5；V1）。

    两条到达路径，与真实使用一一对应：
      * radio 可达页（在该角色侧边栏选项里）→ 真实登录后切换 session page；
      * radio 不可达页（角色不符的隐藏页）→ 持该角色登录态直入
        （_run_page_as 注入 session user，模拟残留会话强行进入）。
    测试库无业务数据（oald_senses 为空），提交流断言用「提交流：准入」caption
    为哨兵；仲裁面板/用户管理/信度页的标题不依赖业务数据。admin 快速通道完整
    表单（需真实词库数据）由 test_pages.py::test_annotate_page_renders_with_form
    在业务库覆盖。
    """

    def test_unlogged_all_protected_pages_blocked(self, r3_env):
        """未登录：标注/提交/用户管理/信度四页全部拦截（清单 1 第 1 行）。"""
        for page in ("annotate", "submission", "users_admin", "reliability"):
            at = _new_at()
            at.session_state["page"] = page
            at.run()
            assert not at.exception, page
            assert any("请先登录" in str(w.value) for w in at.warning), \
                f"未登录进 {page} 未被拦截"
            texts = _page_text(at)
            assert "图式五维标注" not in texts, page
            assert "分歧清单与仲裁" not in texts, page
            assert "账号与角色" not in texts, page
            assert "AI-assisted IAA" not in texts, page
        # 未登录侧边栏：三个受保护页入口全部不可见（仅基础六页）
        at = _new_at()
        at.run()
        assert _radio_keys(at) == ["search", "graph", "corpus", "domain",
                                   "annotate", "help"]

    def test_annotator_matrix(self, r3_env):
        """annotator：可见提交流；不可见他人提交/仲裁面板；用户管理与信度页拦截。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_ann", "r3-ann-pw")
        assert not at.exception
        user = _pget(at, "user")
        assert user and user["role"] == "annotator"

        # 侧边栏：提交页可见，用户管理/信度不可见
        keys = _radio_keys(at)
        assert "submission" in keys
        assert "users_admin" not in keys
        assert "reliability" not in keys

        # 标注页 → 多人提交流（radio 可达），无 admin 快速通道表单、无仲裁面板
        at.session_state["page"] = "annotate"
        at.run()
        texts = _page_text(at)
        assert "提交流：准入" in texts
        assert "图式五维标注" not in texts, "annotator 不得见 admin 直写权威层表单"
        assert "分歧清单与仲裁" not in texts, "annotator 不得见仲裁面板"

        # 提交页 → 同一提交流，仍无仲裁面板
        at.session_state["page"] = "submission"
        at.run()
        texts = _page_text(at)
        assert "提交流：准入" in texts
        assert "分歧清单与仲裁" not in texts

        # 用户管理/信度（radio 不可达）→ 残留会话直入被入口 role gate 拦下
        at2 = _run_page_as("users_admin", user)
        assert not at2.exception
        assert any("仅管理员可用" in str(e.value) for e in at2.error)

        at3 = _run_page_as("reliability", user)
        assert not at3.exception
        assert any("reviewer / admin" in str(w.value) for w in at3.warning)

    def test_reviewer_matrix(self, r3_env):
        """reviewer：分歧+仲裁面板可见；用户管理拦截；信度页可用。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_rev", "r3-rev-pw")
        assert not at.exception
        user = _pget(at, "user")
        assert user and user["role"] == "reviewer"

        keys = _radio_keys(at)
        assert "submission" in keys and "reliability" in keys
        assert "users_admin" not in keys, "reviewer 不得见用户管理入口"

        at.session_state["page"] = "annotate"
        at.run()
        assert "分歧清单与仲裁" in _page_text(at), "reviewer 标注页应有仲裁面板"

        at.session_state["page"] = "submission"
        at.run()
        assert "分歧清单与仲裁" in _page_text(at)

        at.session_state["page"] = "reliability"
        at.run()
        texts = _page_text(at)
        assert "信度报告" in texts
        assert "AI-assisted IAA" in texts

        at2 = _run_page_as("users_admin", user)
        assert not at2.exception
        assert any("仅管理员可用" in str(e.value) for e in at2.error)

    def test_admin_matrix(self, r3_env):
        """admin：全部页面可用，标注页为快速通道（原单人流直写权威层）。

        批次 3-K：legacy admin 六角色两位一体（roles=[dict_admin, sys_admin]），
        _PAGE_ACCESS_SIX 口径下仍可见全部页面（radio == PAGE_KEYS 全集）。
        """
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_admin", "r3-admin-pw")
        assert not at.exception
        user = _pget(at, "user")
        assert user and user["role"] == "admin"
        assert user["roles"] == ["dict_admin", "sys_admin"], \
            "内置/legacy admin 六角色两位一体（词典管理员+平台管理员）"

        keys = _radio_keys(at)
        assert {"submission", "users_admin", "reliability"} <= set(keys)

        at.session_state["page"] = "annotate"
        at.run()
        assert any("快速通道" in str(i.value) for i in at.info), "缺快速通道提示"

        at.session_state["page"] = "submission"
        at.run()
        assert "分歧清单与仲裁" in _page_text(at), "admin 提交页应有仲裁面板"

        at.session_state["page"] = "users_admin"
        at.run()
        texts = _page_text(at)
        assert "修改角色" in texts
        assert "账号与角色" in texts
        # 用户表内他人 display_name 同样转义（清单 7：徽章/表格渲染面）
        table_md = "\n".join(str(m.value) for m in at.markdown)
        assert "&lt;b&gt;x&lt;/b&gt;&amp;跑" in table_md, "用户表未转义 display_name"
        assert "<b>x</b>" not in table_md

        at.session_state["page"] = "reliability"
        at.run()
        assert "信度报告" in _page_text(at)

    def test_viewer_matrix(self, r3_env):
        """viewer：三个受保护页全部无权限提示。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_view", "r3-view-pw")
        assert not at.exception
        user = _pget(at, "user")
        assert user and user["role"] == "viewer"

        keys = _radio_keys(at)
        assert not {"submission", "users_admin", "reliability"} & set(keys)

        # 标注页（radio 可达）：入口显式拦截 viewer
        at.session_state["page"] = "annotate"
        at.run()
        assert any("无权限" in str(w.value) for w in at.warning)

        # 提交/用户管理/信度（radio 不可达）：残留会话直入均被拦下
        at2 = _run_page_as("submission", user)
        assert not at2.exception
        assert any("无权限" in str(w.value) for w in at2.warning)

        at3 = _run_page_as("users_admin", user)
        assert not at3.exception
        assert any("仅管理员可用" in str(e.value) for e in at3.error)

        at4 = _run_page_as("reliability", user)
        assert not at4.exception
        assert any("reviewer / admin" in str(w.value) for w in at4.warning)


# ============================================
# 批次 3-K ②：六角色会话的 radio 可见性（legacy role ∪ session roles）
# ============================================

class TestSixRoleSessionVisibility:
    """session roles（六角色）与 legacy role 并集决定侧边栏可见性。

    批次 3-K 核心口径：_PAGE_ACCESS_SIX（值=六角色名）+ _visible_page_keys
    的 legacy→六角色换算。注入会话不触库（无 _user_db_backed 标记），故
    不需要 r3_env —— 断库环境同样可跑（radio 过滤纯会话计算）。
    """

    _BASE_USER = {"id": 900, "username": "six_role_x", "display_name": "矩阵注入",
                  "role": "viewer"}

    def _radio_keys_for(self, user_extra: dict):
        at = _new_at()
        at.session_state["user"] = {**self._BASE_USER, **user_extra}
        at.session_state["page"] = "search"
        at.run()
        assert not at.exception
        return _radio_keys(at)

    def test_legacy_only_baseline_unchanged(self):
        """无 roles 键的旧结构会话：仅按 legacy role 折算，viewer 行为不变。"""
        keys = self._radio_keys_for({})
        assert "cluster" in keys and "ai_hub" in keys  # 全角色可见的四页
        assert not {"submission", "users_admin", "reliability", "dict_admin"} & set(keys)

    def test_session_roles_sys_admin_opens_users_admin_only(self):
        """viewer + roles=[sys_admin]：用户管理可见；词典管理区不可见（六角色分闸）。"""
        keys = self._radio_keys_for({"roles": ["sys_admin"]})
        assert "users_admin" in keys, "sys_admin 会话角色应放开用户管理入口"
        assert "dict_admin" not in keys, "未授词典管理员不得见词典管理区"

    def test_session_roles_dict_admin_opens_dict_admin_only(self):
        """viewer + roles=[dict_admin]：词典管理区可见；RV23-P3 起用户管理
        宿主页（「📦 功能模块」段所在）入口同步放开（与页面体闸同口径）。"""
        keys = self._radio_keys_for({"roles": ["dict_admin"]})
        assert "dict_admin" in keys
        assert "users_admin" in keys

    def test_session_roles_annotator_adds_submission(self):
        """viewer + roles=[annotator]：提交流入口可见（annotator 及以上）。"""
        keys = self._radio_keys_for({"roles": ["annotator"]})
        assert "submission" in keys
        assert "users_admin" not in keys and "dict_admin" not in keys

    def test_admin_legacy_role_maps_to_both_admin_pages(self):
        """legacy role=admin（无 roles 键）：视为兼 dict_admin+sys_admin。"""
        keys = self._radio_keys_for({"role": "admin"})
        assert {"users_admin", "dict_admin", "submission", "reliability"} <= set(keys)

    def test_page_access_tables_key_aligned(self):
        """_PAGE_ACCESS_SIX 与 legacy 投影 _PAGE_ACCESS 键集一致（防两表漂移）。"""
        from src.app import _PAGE_ACCESS, _PAGE_ACCESS_SIX

        assert set(_PAGE_ACCESS) == set(_PAGE_ACCESS_SIX)
        for key, roles in _PAGE_ACCESS_SIX.items():
            assert roles, f"{key}: 六角色允许集为空（该页将对全员隐藏）"


# ============================================
# 批次 4-N ④：提权硬闸门（管理角色授予/撤销仅词典管理员）＋页面体角色门收口
# ============================================

def _user_roles_rows(username: str) -> list:
    """直查测试库 user_roles（JOIN users 按用户名还原六角色行，按角色名排序）。

    硬闸门用例用它断言「数据层未被调用」：被拒后库中角色行必须原封不动 ——
    闸门只拦 UI 提交不够，必须证明 grant_role/revoke_role 根本没执行。
    """
    import pymysql

    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, database=TEST_DB, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ur.role AS role FROM user_roles ur "
                "JOIN users u ON u.id = ur.user_id "
                "WHERE u.username = %s ORDER BY ur.role",
                (username,),
            )
            return [str(r["role"]) for r in cur.fetchall()]
    finally:
        conn.close()


class TestPrivilegeEscalationGate:
    """提权硬闸门（批次 4-N，施工规范 §7-N / 平台架构设计规范 §8 三级链）。

    口径：授予/撤销 dict_admin/sys_admin（管理角色）仅词典管理员（effective 集
    含 dict_admin）可执行 —— 平台管理员不得自行提权；纯 sys_admin 不提权口径下
    仅可授/撤 viewer；legacy admin（两位一体）全通过。被拒时 st.error 且
    **不调数据层**（库中角色行不变）。页面体角色门收口为 effective_six_roles
    含 sys_admin 或 dict_admin（词典管理员过渡期兼判）。

    会话构造两种：注入 roles 会话（任务指定手法；无 _user_db_backed 标记，
    不触发实时回查——快照即注入值）与真实登录（legacy admin 路径）。正用例
    的注入 id 用真实账号 id（granted_by 外键必须可落库）。
    """

    def _open_users_admin(self, user: dict):
        """注入会话直入用户管理页（模拟残留会话/直链进入）。"""
        at = _new_at()
        at.session_state["user"] = user
        at.session_state["page"] = "users_admin"
        at.run()
        assert not at.exception
        return at

    @staticmethod
    def _select_grant_target(at, target_label: str) -> None:
        sels = [s for s in at.selectbox
                if s.key == "users_admin_role_grant_user"]  # R6-9 前缀收敛
        assert sels, "角色授予面板的「选择用户」未找到"
        sels[0].set_value(target_label)
        at.run()
        assert not at.exception

    @staticmethod
    def _submit_grant(at, role: str) -> None:
        sels = [s for s in at.selectbox if s.label == "授予角色"]
        assert sels, "「授予角色」selectbox 未找到"
        sels[0].set_value(role)
        submits = [b for b in at.button
                   if b.form_id and "授予角色" in str(b.label)]
        assert submits, "「授予角色」提交按钮未找到"
        submits[0].click()
        at.run()
        assert not at.exception

    @staticmethod
    def _submit_revoke(at, role: str) -> None:
        sels = [s for s in at.selectbox if s.label == "撤销角色"]
        assert sels, "「撤销角色」selectbox 未找到"
        sels[0].set_value(role)
        submits = [b for b in at.button
                   if b.form_id and "撤销角色" in str(b.label)]
        assert submits, "「撤销角色」提交按钮未找到"
        submits[0].click()
        at.run()
        assert not at.exception

    def test_pure_sys_admin_enters_and_grant_dict_admin_rejected(self, r3_env):
        """三态②：纯 sys_admin（roles 注入）可进用户管理，授 dict_admin 被拒。

        被拒断言两层：st.error 出硬闸门口径文案；user_roles 表无 dict_admin 行
        （数据层未被调用——页面层闸门真的拦住了写路径）。
        """
        from src.users_db import create_user, grant_role

        actor_uid = create_user("r3_gate_sysadm", "r3-gate-sysadm-pw",
                                "纯平台管理员", "viewer")
        assert isinstance(actor_uid, int)
        assert grant_role(actor_uid, "sys_admin")  # 纯平台管理员（无 dict_admin）
        assert create_user("r3_gate_tgt1", "r3-gate-tgt1-pw", "闸门目标一", "viewer")

        user = {"id": 9001, "username": "r3_gate_sysadm",
                "display_name": "纯平台管理员", "role": "viewer",
                "roles": ["sys_admin"]}
        at = self._open_users_admin(user)
        # 页面体角色门收口：纯 sys_admin 放行（六角色口径，不再读 legacy role）
        assert "账号与角色" in _page_text(at), "纯 sys_admin 应可进入用户管理"

        self._select_grant_target(at, "r3_gate_tgt1（闸门目标一）")
        self._submit_grant(at, "dict_admin")
        assert any("授予/撤销管理角色仅词典管理员可执行" in str(e.value)
                   for e in at.error), "硬闸门未拒绝纯 sys_admin 授予 dict_admin"
        assert "dict_admin" not in _user_roles_rows("r3_gate_tgt1"), \
            "被拒后数据层不应写入 dict_admin 行"

    def test_pure_sys_admin_revoke_dict_admin_rejected(self, r3_env):
        """撤销同闸：纯 sys_admin 撤销 dict_admin 被拒，既有行原封不动。"""
        from src.users_db import create_user, grant_role

        assert create_user("r3_gate_sysadm2", "r3-gate-sysadm2-pw",
                           "纯平台管理员二", "viewer")
        target_uid = create_user("r3_gate_tgt2", "r3-gate-tgt2-pw",
                                 "闸门目标二", "viewer")
        assert isinstance(target_uid, int)
        # 用例前置：经数据层直接授予 dict_admin（API 级闸门批次 5，测试可直调）
        assert grant_role(target_uid, "dict_admin")
        assert "dict_admin" in _user_roles_rows("r3_gate_tgt2")

        user = {"id": 9002, "username": "r3_gate_sysadm2",
                "display_name": "纯平台管理员二", "role": "viewer",
                "roles": ["sys_admin"]}
        at = self._open_users_admin(user)
        self._select_grant_target(at, "r3_gate_tgt2（闸门目标二）")
        self._submit_revoke(at, "dict_admin")
        assert any("授予/撤销管理角色仅词典管理员可执行" in str(e.value)
                   for e in at.error), "硬闸门未拒绝纯 sys_admin 撤销 dict_admin"
        assert "dict_admin" in _user_roles_rows("r3_gate_tgt2"), \
            "被拒后数据层不应删除既有 dict_admin 行"

    def test_pure_sys_admin_can_grant_and_revoke_viewer(self, r3_env):
        """不提权口径：纯 sys_admin 仅可授/撤 viewer（建号基线，三级链第一级）。"""
        from src.users_db import create_user, grant_role

        actor_uid = create_user("r3_gate_sysadm3", "r3-gate-sysadm3-pw",
                                "纯平台管理员三", "viewer")
        assert isinstance(actor_uid, int)
        assert grant_role(actor_uid, "sys_admin")
        target_uid = create_user("r3_gate_tgt3", "r3-gate-tgt3-pw",
                                 "闸门目标三", "annotator")  # 基线无 viewer 行
        assert isinstance(target_uid, int)

        # 注入真实 id（granted_by 外键可落库）
        user = {"id": int(actor_uid), "username": "r3_gate_sysadm3",
                "display_name": "纯平台管理员三", "role": "viewer",
                "roles": ["sys_admin"]}
        at = self._open_users_admin(user)
        self._select_grant_target(at, "r3_gate_tgt3（闸门目标三）")
        self._submit_grant(at, "viewer")
        assert "viewer" in _user_roles_rows("r3_gate_tgt3"), "授 viewer 应成功落库"

        self._select_grant_target(at, "r3_gate_tgt3（闸门目标三）")
        self._submit_revoke(at, "viewer")
        assert "viewer" not in _user_roles_rows("r3_gate_tgt3"), "撤 viewer 应成功删行"

    def test_legacy_admin_grant_dict_admin_allowed(self, r3_env):
        """三态①（闸门正路径）：legacy admin 真实登录两位一体，授 dict_admin 通过。"""
        from src.users_db import create_user

        assert create_user("r3_gate_tgt4", "r3-gate-tgt4-pw", "闸门目标四", "viewer")

        at = _new_at()
        at.run()
        at = _form_login(at, "r3_admin", "r3-admin-pw")
        assert not at.exception
        at.session_state["page"] = "users_admin"
        at.run()
        assert "账号与角色" in _page_text(at)

        self._select_grant_target(at, "r3_gate_tgt4（闸门目标四）")
        self._submit_grant(at, "dict_admin")
        assert "dict_admin" in _user_roles_rows("r3_gate_tgt4"), \
            "legacy admin（dict_admin+sys_admin 两位一体）授 dict_admin 应通过闸门落库"
        assert not at.error, "正路径不应出现 error 通道"

    def test_pure_sys_admin_cannot_demote_dict_admin_via_legacy_form(self, r3_env):
        """legacy 修改角色表单旁路封堵（撤方向）：对兼有 dict_admin 的用户改基线
        ≙ 撤销管理角色（set_role 重置 user_roles），纯 sys_admin 被拒且行不变。"""
        from src.users_db import create_user

        assert create_user("r3_gate_adminish", "r3-gate-adminish-pw",
                           "闸门兼管理目标", "admin")  # 基线含 dict_admin+sys_admin
        assert "dict_admin" in _user_roles_rows("r3_gate_adminish")

        user = {"id": 9004, "username": "gate_actor4",
                "display_name": "闸门注入会话", "role": "viewer",
                "roles": ["sys_admin"]}
        at = self._open_users_admin(user)
        # 「修改角色」表单：第一个「选择用户」+「新角色」均在 form 内（AppTest
        # 平铺访问）；目标下拉取首个匹配（先于停用表单的同名下拉渲染）
        target_sel = [s for s in at.selectbox if s.label == "选择用户"]
        assert target_sel, "修改角色表单的目标下拉未找到"
        target_sel[0].set_value("r3_gate_adminish（闸门兼管理目标）")
        role_sel = [s for s in at.selectbox if s.label == "新角色"]
        assert role_sel, "修改角色表单的角色下拉未找到"
        role_sel[0].set_value("reviewer")
        submits = [b for b in at.button
                   if b.form_id and "保存角色" in str(b.label)]
        assert submits, "「保存角色」提交按钮未找到"
        submits[0].click()
        at.run()
        assert not at.exception
        assert any("授予/撤销管理角色仅词典管理员可执行" in str(e.value)
                   for e in at.error), "改基线撤销管理角色未被硬闸门拒绝"
        assert "dict_admin" in _user_roles_rows("r3_gate_adminish"), \
            "被拒后目标的管理角色行不应被重置"

    def test_editor_blocked_by_page_gate(self, r3_env):
        """三态③：普通 editor（roles 注入）进用户管理被页面体角色门拦下。"""
        user = {"id": 9003, "username": "gate_editor", "display_name": "纯编辑",
                "role": "viewer", "roles": ["editor"]}
        at = self._open_users_admin(user)
        assert any("仅管理员可用" in str(e.value) for e in at.error), \
            "editor 进用户管理未被拦下"
        assert "账号与角色" not in _page_text(at), "editor 不应见用户管理内容"


# ============================================
# 批次 3-K ③：搜索页词形还原提示（resolve_form 前置查询 + 一键切换）
# ============================================

def _insert_wordform(lemma: str, form: str, kind: str = "pinyin") -> None:
    """向测试库 wordforms 直插一行词形（INSERT IGNORE，幂等）。"""
    import pymysql

    conn = pymysql.connect(
        host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
        password=db.MYSQL_PASSWORD, database=TEST_DB, charset=db.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO wordforms (lemma_word, form, kind) "
                "VALUES (%s, %s, %s)",
                (lemma, form, kind),
            )
    finally:
        conn.close()


class TestSearchWordformHint:
    """搜索链路入口的词形还原提示：词形「X」→ 词目「Y」+ 一键切换查询。"""

    def test_wordform_hint_and_switch(self, r3_env):
        """拼音词形命中：提示行渲染；点切换按钮后以词目重查、提示消失。"""
        from src.wordforms_db import ensure_wordforms_tables

        ensure_wordforms_tables()
        _insert_wordform("跑", "pǎo")
        at = _new_at()
        at.run()  # 应用启动块幂等建 wordforms 表
        inputs = {t.key: t for t in at.text_input}
        inputs["搜索动词"].set_value("pǎo")
        at.run()
        assert not at.exception
        assert any("词形「pǎo」→ 词目「跑」" in str(i.value) for i in at.info), \
            "词形还原提示未渲染"
        assert _pget(at, "verb_result") == "pǎo"

        btn = [b for b in at.button if "查询「跑」" in str(b.label)]
        assert btn, "一键切换查询按钮未渲染"
        btn[0].click()
        at.run()
        assert not at.exception
        assert _pget(at, "verb_result") == "跑", "切换后未以词目重新发起查询"
        assert not any("词形「pǎo」" in str(i.value) for i in at.info), \
            "切换后旧提示残留"

    def test_wordform_no_hint_for_plain_lemma(self, r3_env):
        """查询词即词目（无词形命中）：不渲染提示，搜词主链路照常。"""
        from src.wordforms_db import ensure_wordforms_tables

        ensure_wordforms_tables()
        _insert_wordform("跑", "pǎo")
        at = _new_at()
        at.run()
        inputs = {t.key: t for t in at.text_input}
        inputs["搜索动词"].set_value("跑进来")
        at.run()
        assert not at.exception
        assert _pget(at, "verb_result") == "跑进来"
        assert not any("词形「" in str(i.value) for i in at.info)


# ============================================
# S3 清单 1/2/4：三新页（cluster/template/semantic）× 五会话矩阵
# ============================================

_S3_NEW_PAGES = ("cluster", "template", "semantic")


def _page_text_with_expanders(at) -> str:
    """_page_text + 使用说明 expander 的标签（expander 折叠时标签不在 _page_text 里）。"""
    parts = [_page_text(at)]
    parts.extend(str(e.label) for e in at.expander)
    return "\n".join(parts)


# 空库（cs_* 范畴数据未灌）下三新页的预期降级哨兵（S3 清单 4：
# info/warning 优雅降级而非异常；模板页 categories 为空走 info，
# categories 有行但无运行走 warning，两者都含「范畴深挖数据尚未灌入」分支外的
# 独立哨兵 —— 这里断言 categories 为空分支的 info）。
_S3_EMPTY_DB_SENTINEL = {
    "cluster": "暂无聚类运行数据",
    "template": "范畴深挖数据尚未灌入",
    "semantic": "输入一句话",
}
# 三新页页面正文的特征标题（证明页面本体渲染，而非仅入口/使用说明）
_S3_PAGE_TITLE = {
    "cluster": "📊 语义分析",
    "template": "释义模板引擎",
    "semantic": "以句搜义",
}


class TestS3NewPagesMatrix:
    """三新页 × 五会话矩阵（S3 清单 1/2）+ 空库降级（清单 4）。

    与 TestRoleMatrix 的分工：那里固化 submission/users_admin/reliability 的
    角色门；这里固化三新页的「require_login 门 + _PAGE_ACCESS 全角色可见」。
    测试库只有 users 数据，cs_* 表为空 —— 登录后逐页渲染的断言同时固化
    空库降级契约（info 引导，不抛异常、不出 error 通道）。
    """

    def test_unlogged_new_pages_blocked_and_hidden(self, r3_env):
        """未登录：三新页「请先登录」拦截、内容与使用说明不渲染、侧边栏无入口。"""
        for page in _S3_NEW_PAGES:
            at = _new_at()
            at.session_state["page"] = page
            at.run()
            assert not at.exception, page
            assert any("请先登录" in str(w.value) for w in at.warning), \
                f"未登录进 {page} 未被拦截"
            texts = _page_text_with_expanders(at)
            assert _S3_PAGE_TITLE[page] not in texts, f"{page} 未登录泄漏页面本体"
            assert "使用说明" not in texts, f"{page} 未登录渲染了使用说明"
        # 侧边栏：三新页对未登录隐藏（_PAGE_ACCESS 非 None 的键不出现在 radio）
        at = _new_at()
        at.run()
        keys = _radio_keys(at)
        assert not set(_S3_NEW_PAGES) & set(keys), "未登录侧边栏不应出现三新页"
        assert keys == ["search", "graph", "corpus", "domain",
                        "annotate", "help"]

    def _login_and_assert_new_pages(self, username: str, password: str):
        """真实登录 → 三新页 radio 可见 → 逐页渲染：guide + 页面标题 + 空库降级。"""
        at = _new_at()
        at.run()
        at = _form_login(at, username, password)
        assert not at.exception
        keys = _radio_keys(at)
        assert set(_S3_NEW_PAGES) <= set(keys), f"侧边栏缺新页入口: {keys}"
        for page in _S3_NEW_PAGES:
            at.session_state["page"] = page
            at.run()
            assert not at.exception, page
            texts = _page_text_with_expanders(at)
            assert "使用说明" in texts, f"{page} 缺使用说明 expander"
            assert _S3_PAGE_TITLE[page] in texts, f"{page} 页面本体未渲染"
            assert _S3_EMPTY_DB_SENTINEL[page] in texts, \
                f"{page} 空库降级提示缺失（cs_* 表为空）"
            assert not at.error, f"{page} 出现 error 通道（应 info/warning 降级）"
        return at

    def test_annotator_new_pages_visible_and_render(self, r3_env):
        """annotator：三新页可见可渲染（_PAGE_ACCESS 含 annotator）。"""
        self._login_and_assert_new_pages("r3_ann", "r3-ann-pw")

    def test_reviewer_new_pages_visible_and_render(self, r3_env):
        """reviewer：三新页可见可渲染。"""
        self._login_and_assert_new_pages("r3_rev", "r3-rev-pw")

    def test_admin_new_pages_and_full_radio_order(self, r3_env):
        """admin：三新页可见可渲染；radio 为全部 17 键且保持七区分组顺序。

        FX-23 七区菜单分组：admin 全可见，选项序 = 七区序（组间按
        _SIDEBAR_ZONES，组内保持 PAGE_KEYS 相对序）—— 键集仍恰为 PAGE_KEYS
        全集（路由契约不变），只是展示重排。
        """
        from src.app import _SIDEBAR_ZONES

        at = self._login_and_assert_new_pages("r3_admin", "r3-admin-pw")
        zone_ordered = [k for _zone, zone_keys in _SIDEBAR_ZONES for k in zone_keys]
        assert sorted(zone_ordered) == sorted(PAGE_KEYS), "七区表须不重不漏覆盖 17 页"
        assert _radio_keys(at) == zone_ordered, "admin 侧边栏应为全部页面键（七区序）"

    def test_viewer_new_pages_visible_and_render(self, r3_env):
        """viewer：三新页可见可渲染（_PAGE_ACCESS 显式含 viewer；区别于受保护三页）。"""
        at = self._login_and_assert_new_pages("r3_view", "r3-view-pw")
        # 对照：viewer 仍不可见受保护三页（回归锚点，防新页改表时误放开旧页）
        keys = _radio_keys(at)
        assert not {"submission", "users_admin", "reliability"} & set(keys)

    def test_semantic_page_query_flow_empty_db(self, r3_env):
        """semantic 带查询：规则层解析出特征 chips（离线、不依赖库）+ 最近邻降级 info。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_admin", "r3-admin-pw")
        at.session_state["page"] = "semantic"
        at.run()
        query_box = [t for t in at.text_input if t.key == "ss_query"]
        assert query_box, "semantic 查询输入框未渲染"
        query_box[0].set_value("一个士兵整齐地走")
        at.run()
        assert not at.exception
        texts = _page_text(at)
        assert "解析出的特征向量" in texts, "规则层解析未渲染特征 chips 区"
        assert "暂无义位数据" in texts, "空库最近邻应降级 info"
        assert not at.error


class TestS3EmptyDbExistingPages:
    """S3 清单 4（既有页侧）：业务表为空时既有页优雅降级，不抛异常。

    TestS3NewPagesMatrix 已钉三新页在空测试库的降级；这里补三个读业务表
    的既有基础页 —— category 读 categories/cs_*（测试库无该表，查无范畴
    数据走同一 info 分支）、graph 读 word_relations、domain 读
    domain_family_senses（表在但空）。search/corpus/annotate 的空库渲染
    已由 TestCrossPageState / TestRoleMatrix 覆盖，不重复。
    """

    _EMPTY_DB_SENTINEL = {
        # category 键已并入 cluster（语义分析页，空库降级由 S3 矩阵覆盖）
        "graph": "暂无词间关系数据",
        "domain": "域系初判数据尚未灌入",
    }

    def test_existing_pages_empty_db_graceful(self, r3_env):
        """空测试库直入三页：info 引导而非异常，无 error 通道。"""
        for page, sentinel in self._EMPTY_DB_SENTINEL.items():
            at = _new_at()
            at.session_state["page"] = page
            at.run()
            assert not at.exception, page
            texts = _page_text_with_expanders(at)
            assert sentinel in texts, \
                f"{page} 空库未给优雅降级提示（预期 info: {sentinel}）"
            assert not at.error, f"{page} 出现 error 通道（应 info/warning 降级）"


# ============================================
# 清单 6：跨页状态与登出失效
# ============================================

class TestCrossPageState:
    """登录态跨页保持；退出后受保护页立即失效。"""

    def test_user_persists_across_page_switches(self, r3_env):
        """登录 → 连续切换页面 → session user 不丢、退出按钮仍在。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_ann", "r3-ann-pw")
        for page in ("corpus", "search", "annotate"):
            at.session_state["page"] = page
            at.run()
            assert not at.exception, page
            user = _pget(at, "user")
            assert isinstance(user, dict) and user["username"] == "r3_ann", page
            assert any("退出登录" in str(b.label) for b in at.sidebar.button), page

    def test_logout_invalidates_protected_pages_immediately(self, r3_env):
        """退出：user 清除；当轮 users_admin 内容不再渲染并提示登录；页面回搜索。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_admin", "r3-admin-pw")
        at.session_state["page"] = "users_admin"
        at.run()
        assert "账号与角色" in _page_text(at)

        logout = [b for b in at.sidebar.button if "退出登录" in str(b.label)]
        logout[0].click()
        at.run()
        assert not at.exception
        assert _pget(at, "user") is None, "退出后 session user 未清除"
        texts = _page_text(at)
        assert "账号与角色" not in texts, "退出后用户管理内容仍渲染"
        assert any("请先登录" in str(w.value) for w in at.warning), "未提示登录"
        assert _pget(at, "page") == "search", "残留页未回搜索页"


# ============================================
# 清单 3：DB_AVAILABLE=False 全路径优雅降级
# ============================================

class TestDbUnavailableDegrade:
    """断库（连接必然被拒绝的端口）：登录框/标注/用户管理/信度页全部优雅降级。"""

    @pytest.fixture
    def db_down(self, monkeypatch):
        """把 MySQL 指向无服务的端口（立即 ECONNREFUSED，无长超时）。"""
        import socket

        s = socket.socket()
        refused = s.connect_ex((db.MYSQL_HOST, 1)) != 0
        s.close()
        if not refused:  # 极端环境 1 号端口真有服务：换一个大概率关闭的端口
            monkeypatch.setattr(db, "MYSQL_PORT", 65501)
        else:
            monkeypatch.setattr(db, "MYSQL_PORT", 1)
        yield

    def test_sidebar_login_unavailable(self, db_down):
        """断库：侧边栏登录框降级为 info，不渲染输入框、不抛异常。"""
        at = _new_at()
        at.run()
        assert not at.exception
        assert any("登录不可用" in str(i.value) for i in at.sidebar.info)
        assert not any(t.key == "login_username" for t in at.sidebar.text_input)

    def test_annotate_unlogged_still_blocked(self, db_down):
        """断库：未登录进标注页仍被「请先登录」拦截（登录门不依赖数据库状态）。"""
        at = _new_at()
        at.session_state["page"] = "annotate"
        at.run()
        assert not at.exception
        assert any("请先登录" in str(w.value) for w in at.warning)

    def test_submission_flow_offline_info(self, db_down):
        """断库：提交流降级为 info 提示，ensure_flow_tables 不被调用炸掉。"""
        at = _new_at()
        at.session_state["user"] = {"id": 2, "username": "r3_ann",
                                    "display_name": "标注员", "role": "annotator"}
        at.session_state["page"] = "submission"
        at.run()
        assert not at.exception
        assert any("数据库不可用" in str(i.value) for i in at.info)

    def test_users_admin_offline_graceful(self, db_down):
        """断库：用户管理页走 list_users 空列表降级（info），不抛异常。"""
        at = _new_at()
        at.session_state["user"] = {"id": 1, "username": "r3_admin",
                                    "display_name": "管理员", "role": "admin"}
        at.session_state["page"] = "users_admin"
        at.run()
        assert not at.exception
        assert any("暂无用户" in str(i.value) for i in at.info)

    def test_reliability_offline_graceful(self, db_down):
        """断库：信度页走 run_reliability 的 db_error 降级（st.error），不抛异常。"""
        at = _new_at()
        at.session_state["user"] = {"id": 3, "username": "r3_rev",
                                    "display_name": "审核员", "role": "reviewer"}
        at.session_state["page"] = "reliability"
        at.run()
        assert not at.exception
        assert any("数据库不可用" in str(e.value) for e in at.error)

    # ---- S3 清单 3：三新页断库降级（require_login 依赖数据库，登录本身不可用，
    #      注入会话用户模拟「断库前已登录」的残留会话）----

    def test_cluster_page_offline_graceful(self, db_down):
        """断库：cluster 页数据层探针失败 → warning「数据不可用」，不抛异常。

        R4-1/R4-5 三口径归因后，断库（探针 SELECT COUNT(*) FROM cs_cluster_runs
        连不上）走「数据不可用：<原因>（勿重跑灌库）」分支，不再误报「未灌入」
        （原文案「暂无聚类运行数据」仍归空库用例 TestS3NewPagesMatrix 固化）。"""
        import src.cluster_analysis as ca

        ca._load_page_data.clear()  # 清掉 DB-up 用例的页面缓存，真跑断库路径
        at = _new_at()
        at.session_state["user"] = {"id": 1, "username": "r3_admin",
                                    "display_name": "管理员", "role": "admin"}
        at.session_state["page"] = "cluster"
        at.run()
        assert not at.exception
        warnings_and_infos = [str(w.value) for w in at.warning] + \
                             [str(i.value) for i in at.info]
        assert any("数据不可用" in t for t in warnings_and_infos), \
            "断库下 cluster 页应给「数据不可用」提示"
        assert any("勿重跑灌库" in t for t in warnings_and_infos), \
            "「数据不可用」提示应明确勿重跑灌库"
        assert not at.error

    def test_template_page_offline_graceful(self, db_down):
        """断库：template 页 category_study_ready 降级 False → info 引导灌库，不抛异常。"""
        at = _new_at()
        at.session_state["user"] = {"id": 1, "username": "r3_admin",
                                    "display_name": "管理员", "role": "admin"}
        at.session_state["page"] = "template"
        at.run()
        assert not at.exception
        assert any("范畴深挖数据尚未灌入" in str(i.value) for i in at.info)
        assert not at.error

    def test_semantic_page_offline_graceful(self, db_down):
        """断库：semantic 页空查询走引导 info；带查询规则层解析（离线可用）+
        最近邻装载降级 info，不抛异常。"""
        import src.semantic_search as ss

        ss._load_page_index.clear()
        at = _new_at()
        at.session_state["user"] = {"id": 1, "username": "r3_admin",
                                    "display_name": "管理员", "role": "admin"}
        at.session_state["page"] = "semantic"
        at.run()
        assert not at.exception
        assert any("输入一句话" in str(i.value) for i in at.info)

        query_box = [t for t in at.text_input if t.key == "ss_query"]
        assert query_box, "断库下 semantic 查询输入框应照常渲染"
        query_box[0].set_value("一个士兵整齐地走")
        at.run()
        assert not at.exception
        texts = _page_text(at)
        assert "解析出的特征向量" in texts, "断库下规则层解析应照常工作"
        assert any("暂无义位数据" in str(i.value) for i in at.info)
        assert not at.error
