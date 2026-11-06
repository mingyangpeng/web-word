"""R3 集成与回归测试 —— 真实登录流 / 角色×页面权限矩阵 / 断库降级（AppTest）。

与 tests/test_pages.py 的分工：
  * test_pages.py 直接向 session_state 注入 user（页面级渲染契约）；
  * 本文件走**真实登录表单**（填用户名/密码 → 点登录 → 会话就位），覆盖
    「登录表单 → verify_login → session user → 角色分派」的完整接缝（R3 清单 5），
    并把 角色×页面 权限矩阵固化为可执行断言（R3 清单 1）。

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


def _radio_keys(at) -> list:
    """侧边栏页面 radio 的当前选项，还原为页面键（AppTest 的 options 是
    format_func 应用后的标签，这里用 page_label 反查回 PAGE_KEYS 的键）。"""
    radios = [r for r in at.sidebar.radio if r.label == "页面"]
    if not radios:
        return []
    label2key = {page_label(k): k for k in PAGE_KEYS}
    return [label2key.get(str(o), str(o)) for o in radios[0].options]


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
        # verify_login 返回规范四字段（无 password_hash，哈希不出数据层）
        assert user["username"] == "r3_ann"
        assert user["role"] == "annotator"
        assert user["display_name"] == "标注员'丙"
        assert set(user.keys()) == {"id", "username", "display_name", "role"}
        # 登录框消失，退出按钮在场
        assert not any(t.key == "login_username" for t in at.sidebar.text_input)
        assert any("退出登录" in str(b.label) for b in at.sidebar.button)

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
                                   "annotate", "category"]

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
        """admin：全部页面可用，标注页为快速通道（原单人流直写权威层）。"""
        at = _new_at()
        at.run()
        at = _form_login(at, "r3_admin", "r3-admin-pw")
        assert not at.exception

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
    "cluster": "聚类可视化与典型性排序",
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
                        "annotate", "category"]

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
        """admin：三新页可见可渲染；radio 为全部 12 键且保持 PAGE_KEYS 顺序。"""
        at = self._login_and_assert_new_pages("r3_admin", "r3-admin-pw")
        assert _radio_keys(at) == list(PAGE_KEYS), "admin 侧边栏应为全部页面键（原序）"

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
        "category": "范畴深挖数据尚未灌入",
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
        """断库：cluster 页 get_categories 降级为空 → info 引导灌库，不抛异常。"""
        import src.cluster_analysis as ca

        ca._load_page_data.clear()  # 清掉 DB-up 用例的页面缓存，真跑断库路径
        at = _new_at()
        at.session_state["user"] = {"id": 1, "username": "r3_admin",
                                    "display_name": "管理员", "role": "admin"}
        at.session_state["page"] = "cluster"
        at.run()
        assert not at.exception
        assert any("暂无聚类运行数据" in str(i.value) for i in at.info)
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
