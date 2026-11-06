"""页面使用说明的一一对应测试。

两道锁：
  1. 结构锁：侧边栏 radio 的选项与 PAGE_GUIDES 键完全一致（按角色过滤子集
     仍以 PAGE_KEYS 为基准）—— 页面有说明、说明有页面，新增页面漏配/
     删页漏删说明都会失败；
  2. 渲染锁：AppTest 逐页运行，断言「使用说明」真实出现在页面上，
     且每页说明含各自的关键内容锚点（不是千篇一律的模板文案）。

多人标注系统（规范 §5）新增三页 users_admin / reliability / submission
有角色门：渲染锁经 _SESSION_USERS 注入相应角色的会话用户。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.page_guides import PAGE_GUIDES, PAGE_KEYS, page_label, render_page_usage_guide  # noqa: E402

# app.py 的九页分派（与 main() 的 elif 链一致；含多人标注系统新增三页）
APP_PAGES = {"search", "graph", "corpus", "domain", "annotate", "category",
             "submission", "users_admin", "reliability",
             "cluster", "template", "semantic"}

# 每页说明的专属内容锚点（从 PAGE_GUIDES 内容派生，防止说明被清空成模板）
_ANCHORS = {
    "search": "五要素",
    "graph": "力导向",
    "corpus": "enTenTen21",
    "domain": "三域十二系",
    "annotate": "五维标注",
    "category": "图式对齐",
    "submission": "覆盖更新",
    "users_admin": "角色",
    "reliability": "Krippendorff",
    "cluster": "medoid",
    "template": "母图式",
    "semantic": "Gower",
}
# 详细版新增段：每页必须有原理与数据来源
_ANCHORS_PRINCIPLE = {
    "search": "Talmy",
    "graph": "完全图",
    "corpus": "logDice",
    "domain": "R2/R3",
    "annotate": "义位",
    "category": "Gower",
    "submission": "独立性",
    "users_admin": "自保护",
    "reliability": "AI-assisted",
    "cluster": "medoid",
    "template": "确定性槽位拼装",
    "semantic": "最近邻",
}

# 有角色门的页面：AppTest 渲染锁注入的会话用户（规范 §6-5 会话结构；
# 仅 session_state 注入，不要求库中存在该账号——页面不反查用户表）
_SESSION_USERS = {
    "annotate": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "users_admin": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "reliability": {"id": 3, "username": "reviewer_e2e", "display_name": "测试审核员",
                    "role": "reviewer"},
    "submission": {"id": 2, "username": "coder_e2e", "display_name": "测试标注员",
                   "role": "annotator"},
    "cluster": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "template": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "semantic": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
}


def test_page_keys_match_app_pages():
    """结构锁：PAGE_GUIDES 键 == app.py 的页面集合。"""
    assert set(PAGE_KEYS) == APP_PAGES
    assert list(PAGE_KEYS) == ["search", "graph", "corpus", "domain", "annotate",
                               "submission", "category", "users_admin", "reliability",
                               "cluster", "template", "semantic"]


def test_every_guide_has_required_fields():
    for key, guide in PAGE_GUIDES.items():
        assert set(guide) >= {"label", "purpose", "steps", "notes"}, key
        assert guide["label"].startswith(("🔍", "🕸️", "📊", "🧭", "🏷️", "🏃‍♀️",
                                          "📥", "👥", "📐", "📈", "🧩", "🧠")), key
        assert len(guide["steps"]) >= 3, f"{key} 步骤过少"
        assert any(kw in guide["purpose"] or kw in " ".join(guide["steps"])
                   for kw in (_ANCHORS[key],)), f"{key} 缺专属锚点 {_ANCHORS[key]}"


def test_guide_render_rejects_unknown_key():
    """未知键给出警告而不是静默空白（AppTest 外的兜底路径）。"""
    import streamlit as st
    # 不在 ScriptRunContext 下调用会打警告但不崩 —— 只验证键查找逻辑
    assert PAGE_GUIDES.get("nonexistent") is None
    assert page_label("nonexistent") == "nonexistent"
    # 键存在时不抛异常（st 调用在裸模式下打 ScriptRunContext 警告，可忽略）
    try:
        render_page_usage_guide("search")
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"合法键渲染不应抛异常: {e}")


@pytest.mark.parametrize("page_key", sorted(APP_PAGES))
def test_every_page_renders_its_guide(page_key):
    """渲染锁：AppTest 逐页运行，「使用说明」expander 真实出现且内容专属。

    有角色门的页面先注入 _SESSION_USERS 的会话用户（未登录会被
    「请先登录」门拦下，说明不会渲染）。
    """
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "src", "app.py"),
        default_timeout=180,
    )
    if page_key in _SESSION_USERS:
        at.session_state["user"] = _SESSION_USERS[page_key]
    at.session_state["page"] = page_key
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    # 收集页面全部文本：expander 标签 + 其内部元素 + 页面级 markdown/caption
    parts = [str(e.label) for e in at.expander]
    for e in at.expander:
        parts += [str(x.value) for x in
                  list(e.markdown) + list(e.caption) + list(e.subheader)]
    parts += [str(x.value) for x in list(at.markdown) + list(at.caption)]
    texts = "\n".join(parts)
    assert "使用说明" in texts, f"{page_key}: 说明 expander 未渲染"
    anchor = _ANCHORS[page_key]
    assert anchor in texts, f"{page_key}: 说明缺专属锚点 {anchor}"
    assert "原理" in texts and "数据来源" in texts, \
        f"{page_key}: 详细版说明缺原理/数据来源段"
    assert _ANCHORS_PRINCIPLE[page_key] in texts, \
        f"{page_key}: 原理段缺专属锚点 {_ANCHORS_PRINCIPLE[page_key]}"

    # 侧边栏标签与 PAGE_GUIDES 一致（radio 渲染的是 page_label）
    assert page_label(page_key) in texts, f"{page_key}: 侧边栏标签与说明不一致"


def test_sidebar_radio_uses_page_guides():
    """app.py 源码级检查：radio 选项来自 PAGE_KEYS 的角色可见性过滤。

    多人标注系统按角色过滤侧边栏入口（规范 §5/§6-4），过滤后的子集
    仍必须以 PAGE_KEYS 为单一事实来源（_visible_page_keys 遍历 PAGE_KEYS），
    不允许手写页面清单。
    """
    app_src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "app.py"), encoding="utf-8").read()
    assert "options=visible_keys" in app_src, "侧边栏未接角色可见性过滤（断链）"
    assert "def _visible_page_keys" in app_src, "缺角色可见性过滤函数"
    # 过滤必须以 PAGE_KEYS 为基准（防硬编码页面清单）
    assert "PAGE_KEYS" in app_src
    assert "format_func=page_label" in app_src
    # 每个页面渲染函数都调用了 render_page_usage_guide
    for key in APP_PAGES:
        assert f'render_page_usage_guide("{key}")' in app_src or \
               key == "category", key
    # category 的调用在 category_study_page.py
    cat_src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "category_study_page.py"), encoding="utf-8").read()
    assert 'render_page_usage_guide("category")' in cat_src
