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

# app.py 的八页分派（与 main() 的 elif 链一致；批次 8：category 并入 cluster
# —— 语义分析页，旧键在 main() 顶部重定向）
APP_PAGES = {"search", "graph", "corpus", "domain", "annotate",
             "submission", "users_admin", "reliability",
             "cluster", "template", "semantic", "dict_admin", "ai_hub",
             "writing", "lexical",
             "model_settings", "help"}

# 每页说明的专属内容锚点（从 PAGE_GUIDES 内容派生，防止说明被清空成模板）
_ANCHORS = {
    "search": "五要素",
    "graph": "力导向",
    "corpus": "enTenTen21",
    "domain": "三域十二系",
    "annotate": "五维标注",
    "submission": "覆盖更新",
    "users_admin": "角色",
    "reliability": "Krippendorff",
    "cluster": "图式对齐",
    "template": "母图式",
    "semantic": "Gower",
    "dict_admin": "主编驾驶舱",
    "ai_hub": "收件箱",
    "writing": "审校",
    "lexical": "对译",
    "model_settings": "供应商",
    "help": "四段式",
}
# 详细版新增段：每页必须有原理与数据来源
_ANCHORS_PRINCIPLE = {
    "search": "Talmy",
    "graph": "完全图",
    "corpus": "logDice",
    "domain": "R2/R3",
    "annotate": "义位",
    "submission": "独立性",
    "users_admin": "自保护",
    "reliability": "AI-assisted",
    "cluster": "Gower",
    "template": "确定性槽位拼装",
    "semantic": "最近邻",
    "dict_admin": "三级最小权限链",
    "ai_hub": "混合主动交互",
    "writing": "两种范式",
    "lexical": "三态",
    "model_settings": "明文存储",
    "help": "母本",
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
    "dict_admin": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "ai_hub": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "writing": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
    "model_settings": {"id": 1, "username": "admin", "display_name": "管理员", "role": "admin"},
}


def test_page_keys_match_app_pages():
    """结构锁：PAGE_GUIDES 键 == app.py 的页面集合。"""
    assert set(PAGE_KEYS) == APP_PAGES
    assert list(PAGE_KEYS) == ["search", "graph", "corpus", "domain", "annotate",
                               "submission", "users_admin", "reliability",
                               "cluster", "template", "semantic",
                               "dict_admin", "ai_hub", "writing", "lexical",
                               "model_settings", "help"]


def test_every_guide_has_required_fields():
    for key, guide in PAGE_GUIDES.items():
        assert set(guide) >= {"label", "purpose", "steps", "notes"}, key
        assert guide["label"].startswith(("🔍", "🕸️", "📊", "🧭", "🏷️", "🏃‍♀️",
                                          "📥", "👥", "📐", "📈", "🧩", "🧠", "📖", "🤖", "✍️", "❓")), key
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
        assert f'render_page_usage_guide("{key}")' in app_src, key


def test_page_access_table_consistent_with_registration():
    """S3 清单 2 ＋ 批次 4-N 收编：六角色权威表与 legacy 投影表双检。

    防三类静默回归：
      * 页面改名/下线后两表留下陈旧键 —— 过滤对该键永远不生效，行为测试
        （角色矩阵）钉不住多出来的键；
      * _PAGE_ACCESS_SIX 角色元组出现六角色枚举之外的值（拼写漂移）——
        该角色将永远看不到该页，而矩阵用例只断言在场角色可见，断不出拼错的键
        （未知角色折叠进 legacy 投影后同样原样出现，被下方 legacy 值域断言拦下）；
      * 两表漂移 —— legacy `_PAGE_ACCESS` 必须恰为 `_PAGE_ACCESS_SIX` 经
        _SIX_TO_LEGACY_DOMAIN 的投影（dict_admin/sys_admin→admin、
        editor→annotator，其余同名），逐键相等；投影值仍 ⊆ 规范 §1 四角色
        （旧调用方哨兵保留）。
    导入 src.app 执行模块级代码（main() 有 __main__ 守卫，test_phase4/5 同款）。
    """
    from src.app import (  # noqa: E402
        _PAGE_ACCESS,
        _PAGE_ACCESS_SIX,
        _SIX_TO_LEGACY_DOMAIN,
    )
    from src.users_db import NEW_ROLES  # noqa: E402

    keys = {"submission", "users_admin", "reliability",
            "cluster", "template", "semantic", "dict_admin", "ai_hub",
            "writing", "lexical", "model_settings"}
    assert set(_PAGE_ACCESS_SIX) == keys, \
        "_PAGE_ACCESS_SIX 键应恰为十一个非基础页（基础六页与帮助中心对所有人可见，不进表）"
    assert set(_PAGE_ACCESS) == set(_PAGE_ACCESS_SIX), "两表键集漂移"

    legacy_canonical = {"admin", "reviewer", "annotator", "viewer"}
    for key, roles in _PAGE_ACCESS_SIX.items():
        # 权威表：值域 ⊆ 六角色名（拼写漂移哨兵）
        assert roles, f"{key}: 六角色允许集为空（该页将对全员隐藏）"
        assert set(roles) <= set(NEW_ROLES), f"{key}: 角色越出六角色枚举: {roles}"
        # legacy 表 = 权威表的投影（dict_admin/sys_admin→admin、editor→annotator 折叠）
        projected = tuple(sorted(
            {_SIX_TO_LEGACY_DOMAIN.get(role, role) for role in roles}
        ))
        assert _PAGE_ACCESS[key] == projected, \
            f"{key}: legacy _PAGE_ACCESS 与 _PAGE_ACCESS_SIX 投影不一致: " \
            f"{_PAGE_ACCESS[key]} != {projected}"
        # 旧哨兵保留：投影值 ⊆ 规范 §1 四角色
        assert projected, f"{key}: 投影角色元组为空（该页将对全员隐藏）"
        assert set(projected) <= legacy_canonical, \
            f"{key}: 投影越出规范 §1 四角色: {projected}"


class TestEffectiveSixRoles:
    """批次 4-N 六角色收口：users_db.effective_six_roles 单一实现＋app 薄别名。

    页面层六角色门（app._visible_page_keys、users_admin 页面体角色门、提权
    硬闸门）的折算逻辑自此只有一份 —— 这里钉住它的纯函数语义（不触库）。
    """

    def test_none_and_non_dict_fail_closed(self):
        """None / 非 dict 会话 → 空集（未登录＝无权限，fail-closed）。"""
        from src.users_db import effective_six_roles

        assert effective_six_roles(None) == set()
        assert effective_six_roles("admin") == set()
        assert effective_six_roles(42) == set()
        assert effective_six_roles(["admin"]) == set()

    def test_legacy_role_mapping(self):
        """legacy users.role 列映射：admin 两位一体，其余同名；未知旧值忽略。"""
        from src.users_db import effective_six_roles

        assert effective_six_roles({"role": "admin"}) == {"dict_admin", "sys_admin"}
        assert effective_six_roles({"role": "reviewer"}) == {"reviewer"}
        assert effective_six_roles({"role": "annotator"}) == {"annotator"}
        assert effective_six_roles({"role": "viewer"}) == {"viewer"}
        assert effective_six_roles({"role": "editor"}) == set()  # 旧列无此值
        assert effective_six_roles({}) == set()  # 无 role 键的残缺会话

    def test_session_roles_union_and_invalid_ignored(self):
        """session roles 与 legacy 映射取并集；非法角色名逐名忽略（fail-closed）。"""
        from src.users_db import effective_six_roles

        assert effective_six_roles(
            {"role": "viewer", "roles": ["sys_admin"]}
        ) == {"viewer", "sys_admin"}
        assert effective_six_roles(
            {"role": "admin", "roles": ["dict_admin"]}
        ) == {"dict_admin", "sys_admin"}  # 并集去重
        # 非法名（拼写漂移/注入垃圾）不放大权限；容器类型宽容（list/tuple/set）
        assert effective_six_roles(
            {"role": "viewer", "roles": ["dict_admin", "dickt_admin", "root", 7]}
        ) == {"viewer", "dict_admin"}
        assert effective_six_roles(
            {"role": None, "roles": ("editor",), }
        ) == {"editor"}
        assert effective_six_roles(
            {"role": None, "roles": {"annotator"}}
        ) == {"annotator"}
        # roles 键为非序列（脏数据）→ 忽略，只按 legacy 折算
        assert effective_six_roles(
            {"role": "viewer", "roles": "sys_admin"}
        ) == {"viewer"}

    def test_app_alias_delegates_to_users_db(self):
        """app._effective_six_roles 是 users_db.effective_six_roles 的别名
        （单一实现，非复制 def）；行为与数据层完全一致。"""
        import src.app as app_mod  # noqa: E402
        from src.users_db import effective_six_roles  # noqa: E402

        assert app_mod._effective_six_roles is effective_six_roles
        sample = {"id": 1, "username": "u", "role": "admin",
                  "roles": ["sys_admin", "reviewer"]}
        assert app_mod._effective_six_roles(sample) == \
            effective_six_roles(sample) == \
            {"dict_admin", "sys_admin", "reviewer"}
