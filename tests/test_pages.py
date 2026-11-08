"""页面级渲染测试（AppTest 无头执行）。

覆盖应用页面的最小渲染契约：不抛异常、关键元素在场。
多人标注系统（规范 §5/§7-V1）：标注页与新增三页有登录/角色门 ——
需要授权内容的用例经 _run_page 的 user 参数注入会话用户
（规范 §6-5 会话结构 st.session_state["user"]，页面不反查用户表）。
DB 依赖：本测试连接真实 MySQL（与 test_schema 同口径，本地 ./start 后可跑）。
"""
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 页面测试连接真实 MySQL（与 test_schema 同口径）。必须在 import src.app 之前
# 设置：config.yaml 的 host 是 Docker 服务名 "mysql"，本地裸跑 pytest 时
# 环境变量优先级覆盖它，否则页面渲染会退化成"数据库不可用"分支。
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import pymysql  # noqa: E402

import src.mysql_db as _db  # noqa: E402


def _mysql_reachable() -> bool:
    """连通探针（RV-10 P1-2）：只建连接不建库，对齐 test_fx3_perf._db_available。

    页面渲染大多有「数据库离线」降级分支可无库跑；只有断言具体业务数据
    （用户表单、分歧仲裁面板等需真实表结构/数据）的用例才需要真库。
    """
    try:
        conn = pymysql.connect(
            host=_db.MYSQL_HOST, port=_db.MYSQL_PORT, user=_db.MYSQL_USER,
            password=_db.MYSQL_PASSWORD, charset=_db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()

# 数据依赖型用例：断言的元素只在库可用时渲染（离线分支渲染的是降级提示）
requires_mysql = pytest.mark.skipif(
    not HAS_MYSQL, reason="MySQL 不可用，跳过依赖真实库数据的页面渲染用例")

APP = os.path.join(PROJECT_ROOT, "src", "app.py")
TIMEOUT = 60

# 会话用户样例（规范 §1 角色语义；仅 session_state 注入，不要求库中存在）
_ADMIN_USER = {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"}
_CODER_USER = {"id": 2, "username": "coder_e2e", "display_name": "测试标注员",
               "role": "annotator"}
_REVIEWER_USER = {"id": 3, "username": "reviewer_e2e", "display_name": "测试审核员",
                  "role": "reviewer"}
_VIEWER_USER = {"id": 4, "username": "viewer_e2e", "display_name": "测试只读",
                "role": "viewer"}


def _run_page(page: str, user: dict = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    if user is not None:
        at.session_state["user"] = user
    at.session_state["page"] = page
    at.run()
    return at


def _page_text(at: AppTest) -> str:
    """AppTest 里 markdown/caption/标题等文本元素的总和。"""
    parts = []
    for accessor in ("markdown", "caption", "header", "subheader", "title"):
        elements = getattr(at, accessor, None) or []
        parts.extend(e.value for e in elements)
    return " ".join(parts)


def test_search_page_renders():
    at = _run_page("search")
    assert not at.exception
    texts = _page_text(at)
    assert "动词释义优化器" in texts


@requires_mysql
def test_corpus_page_renders_with_editor():
    """语料数据集页：总表 + 可编辑搭配明细（PS 口径回写入口）。"""
    at = _run_page("corpus")
    assert not at.exception
    texts = _page_text(at)
    assert "语料数据集" in texts
    assert "搭配明细（按槽位，可编辑）" in texts
    assert "PS 口径" in texts


@requires_mysql
def test_annotate_page_renders_with_form():
    """标注平台页（admin 快速通道）：进度指标 + 五维表单（直写权威层）。"""
    at = _run_page("annotate", user=_ADMIN_USER)
    assert not at.exception
    texts = _page_text(at)
    assert "标注平台" in texts
    assert "图式五维标注" in texts
    # admin 快速通道提示在场（规范 §5：保留原直写权威层入口）
    assert any("快速通道" in str(i.value) for i in at.info)
    # 五维表单控件在场（form 内的控件经 at.radio/selectbox 等访问器读取）
    radio_labels = [r.label for r in at.radio]
    assert any("准入标签" in lb for lb in radio_labels), f"准入标签缺失: {radio_labels}"
    assert any("意象图式" in lb for lb in
               [r.label for r in at.radio] + [s.label for s in at.selectbox]), "意象图式选择缺失"
    assert any("英汉对齐" in lb for lb in [s.label for s in at.selectbox]), "对齐选择缺失"
    # 进度指标（metric）在场
    assert len(at.metric) >= 3


def test_graph_page_renders():
    at = _run_page("graph")
    assert not at.exception
    all_md = " ".join(x.value for x in at.markdown)
    assert "词间关系知识图谱" in all_md


# ============================================
# 多人标注系统：登录门 / 角色门 / 新页面（规范 §5/§7-V1）
# ============================================
def test_annotate_page_requires_login():
    """V1：未登录不能进标注页（渲染「请先登录」，页面内容不渲染）。"""
    at = _run_page("annotate")
    assert not at.exception
    assert any("请先登录" in str(w.value) for w in at.warning)
    assert not any("图式五维标注" in str(m.value) for m in at.markdown)


def test_annotate_page_viewer_denied():
    """V1：viewer 进标注页提示无权限。"""
    at = _run_page("annotate", user=_VIEWER_USER)
    assert not at.exception
    assert any("无权限" in str(w.value) for w in at.warning)


def test_annotate_page_annotator_gets_submission_flow():
    """标注页按角色分派：annotator 看到多人提交流（含 V7 AI 草稿区与我的提交记录）。"""
    at = _run_page("annotate", user=_CODER_USER)
    assert not at.exception
    texts = _page_text(at)
    assert "标注平台" in texts
    assert "我的提交记录" in texts
    # annotator 不应看到 admin 直写权威层的表单
    assert not any("图式五维标注" in str(m.value) for m in at.markdown)


@requires_mysql
def test_annotate_page_reviewer_gets_panel():
    """标注页按角色分派：reviewer 看到提交流 + 分歧清单与仲裁面板。"""
    at = _run_page("annotate", user=_REVIEWER_USER)
    assert not at.exception
    assert "分歧清单与仲裁" in _page_text(at)


def test_submission_page_requires_login():
    """新增「标注提交」页：未登录渲染「请先登录」。"""
    at = _run_page("submission")
    assert not at.exception
    assert any("请先登录" in str(w.value) for w in at.warning)


def test_submission_page_renders_for_annotator():
    """「标注提交」页（annotator）：提交流 + 我的提交记录；无他人数据入口。"""
    at = _run_page("submission", user=_CODER_USER)
    assert not at.exception
    texts = _page_text(at)
    assert "标注提交" in texts
    assert "我的提交记录" in texts
    # 独立性（规范 §0）：annotator 页面不渲染分歧/仲裁面板
    assert "分歧清单与仲裁" not in texts


@requires_mysql
def test_submission_page_reviewer_gets_panel():
    """「标注提交」页（reviewer）：额外渲染分歧清单与仲裁面板。"""
    at = _run_page("submission", user=_REVIEWER_USER)
    assert not at.exception
    assert "分歧清单与仲裁" in _page_text(at)


def test_users_admin_page_gate():
    """用户管理页：未登录提示登录；非 admin 角色提示无权限。"""
    at = _run_page("users_admin")
    assert not at.exception
    assert any("请先登录" in str(w.value) for w in at.warning)

    at2 = _run_page("users_admin", user=_CODER_USER)
    assert not at2.exception
    assert any("仅管理员可用" in str(e.value) for e in at2.error)


def test_users_admin_page_renders_for_admin():
    """用户管理页（admin）：指标卡 + 用户表 + 表单入口。"""
    at = _run_page("users_admin", user=_ADMIN_USER)
    assert not at.exception
    texts = _page_text(at)
    assert "用户管理" in texts
    assert "修改角色" in texts
    assert len(at.metric) >= 3


def test_reliability_page_gate():
    """信度报告页：annotator 提示无权限（页面入口 role gate）。"""
    at = _run_page("reliability", user=_CODER_USER)
    assert not at.exception
    assert any("reviewer / admin" in str(w.value) for w in at.warning)


def test_reliability_page_renders_for_reviewer():
    """信度报告页（reviewer）：标题 + 口径标注 + 选择器在场。"""
    at = _run_page("reliability", user=_REVIEWER_USER)
    assert not at.exception
    texts = _page_text(at)
    assert "信度报告" in texts
    assert "AI-assisted IAA" in texts
