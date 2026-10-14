"""页面级渲染测试（AppTest 无头执行）。

覆盖应用四个页面的最小渲染契约：不抛异常、关键元素在场。
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

APP = os.path.join(PROJECT_ROOT, "src", "app.py")
TIMEOUT = 60


def _run_page(page: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
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


def test_corpus_page_renders_with_editor():
    """语料数据集页：总表 + 可编辑搭配明细（PS 口径回写入口）。"""
    at = _run_page("corpus")
    assert not at.exception
    texts = _page_text(at)
    assert "语料数据集" in texts
    assert "搭配明细（按槽位，可编辑）" in texts
    assert "PS 口径" in texts


def test_annotate_page_renders_with_form():
    """标注平台页：进度指标 + 五维表单。"""
    at = _run_page("annotate")
    assert not at.exception
    texts = _page_text(at)
    assert "标注平台" in texts
    assert "图式五维标注" in texts
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
