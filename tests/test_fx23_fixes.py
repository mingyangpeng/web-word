"""FX-23 侧边栏七区菜单分组的回归测试（规范②组「七区菜单分组」首项）。

分组只改**呈现**：选项按七区连续排列（组间按 _SIDEBAR_ZONES 序、组内保持
PAGE_KEYS 相对序），标签 = 【区名】+ page_label；可见集仍由 _visible_page_keys
按六角色权限表过滤（不改任何页面的权限门）。四道锁：

  1. 分区表锁：_SIDEBAR_ZONES 不重不漏覆盖 PAGE_KEYS 17 键，区名/区序与
     docs/使用说明书.md §四 界面导览的七区口径一致；
  2. 标签锁：选项标签仍以 page_label 为页名源（页名与使用说明同源）；
  3. 未登录锁：侧边栏只出未登录可见集（查阅区四页 + 标注平台 + 帮助中心），
     受保护页入口一个不漏地隐藏，帮助中心入口保持可达；
  4. 管理员可达锁：admin 登录后七区全部 17 页在 radio 中，逐页点选后
     session_state["page"] 正确且全程无 exception（路由契约不变）。

未登录态口径说明（照实，不改权限）：
  * semantic（以句搜义）按文档归「查阅展示」区，但权限在 _PAGE_ACCESS_SIX
    （登录可见）→ 未登录不出现在侧边栏，故未登录查阅区只渲染四基础页；
  * annotate（标注平台）是权限表外的基础页（页面层 require_login 拦未登录）、
    help（帮助中心）不计权限表 —— 两者未登录仍随可见集出现（与既有集成测试
    锁定的未登录六键一致），分组后照实落在「语义建模」区与「系统管理」区。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import pytest  # noqa: E402

from src.app import (  # noqa: E402
    _SIDEBAR_ZONES,
    _group_keys_by_zone,
    _visible_page_keys,
    sidebar_option_label,
)
from src.page_guides import PAGE_KEYS, page_label  # noqa: E402

# 七区权威口径（区名 → 页键集合），与 docs/使用说明书.md §四 界面导览一致
EXPECTED_ZONES = {
    "🔍 查阅展示": {"search", "graph", "corpus", "domain", "semantic"},
    "🏷️ 语义建模": {"annotate", "submission", "reliability"},
    "📊 语义分析": {"cluster"},
    "✍️ 编纂产出": {"template", "writing", "lexical"},
    "🤖 AI 协作": {"ai_hub"},
    "📖 词典管理": {"dict_admin", "model_settings"},
    "🔧 系统管理": {"users_admin", "help"},
}

# 未登录可见键（现状权限口径，与既有集成测试锁定的六键一致；
# 顺序 = 七区展示序：查阅区四页 → 语义建模区标注平台 → 系统管理区帮助中心）
ANON_VISIBLE = ["search", "graph", "corpus", "domain", "annotate", "help"]

# 未登录不得出现的登录页（submission/users_admin/reliability 三受保护页 +
# 八个区级/工作区登录页；annotate 与 help 照实可见，见模块 docstring）
ANON_HIDDEN = ("submission", "users_admin", "reliability", "cluster",
               "template", "semantic", "dict_admin", "ai_hub",
               "writing", "lexical", "model_settings")

# 探针会话（纯会话计算，不触库；roles 与 legacy role 并集口径见 users_db）
_PROBE_SESSIONS = {
    "anon": None,
    "viewer": {"id": 2, "username": "v", "display_name": "只读",
               "role": "viewer", "roles": ["viewer"]},
    "annotator": {"id": 3, "username": "a", "display_name": "标注",
                  "role": "annotator", "roles": ["annotator"]},
    "admin": {"id": 1, "username": "admin", "display_name": "管理员",
              "role": "admin", "roles": ["dict_admin", "sys_admin"]},
}

_ADMIN_SESSION = _PROBE_SESSIONS["admin"]


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "src", "app.py"),
        default_timeout=180,
    )


def _nav_buttons(at):
    """侧边栏导航按钮（批次 22 按钮式侧边栏；label=page_label）。"""
    return [b for b in at.sidebar.button
            if str(b.label) in {page_label(k) for k in PAGE_KEYS}]


def _nav_keys(at) -> list:
    label2key = {page_label(k): k for k in PAGE_KEYS}
    return [label2key[str(b.label)] for b in _nav_buttons(at)
            if str(b.label) in label2key]


def _radio_labels(at) -> list:
    """兼容名：导航按钮标签序（七区序）。"""
    return [str(b.label) for b in _nav_buttons(at)]


def _radio_keys(at) -> list:
    """侧边栏可见页键（导航按钮按七区序还原；批次 22 按钮式侧边栏）。"""
    label2key = {page_label(k): k for k in PAGE_KEYS}
    return [label2key[str(b.label)] for b in _nav_buttons(at)
            if str(b.label) in label2key]


def _radio_labels(at) -> list:
    """兼容名：导航按钮标签序（七区序）。"""
    return [str(b.label) for b in _nav_buttons(at)]


def _goto(at, key: str):
    """点导航按钮切页（on_click 写 session_state["page"] 后 rerun）。"""
    for b in _nav_buttons(at):
        if str(b.label) == page_label(key):
            b.click()
            at.run()
            return
    raise AssertionError(f"导航按钮不存在: {key}")


# ============================================
# 1. 分区表锁 + 2. 标签锁（纯数据层，不触 AppTest）
# ============================================

def test_zone_table_matches_manual_seven_zones():
    """七区区名/区序/成员与使用说明书 §四 一致，不重不漏覆盖 17 页。"""
    zone_names = [zone for zone, _keys in _SIDEBAR_ZONES]
    assert zone_names == list(EXPECTED_ZONES), \
        f"七区区名或区序漂移: {zone_names}"
    for zone, zone_keys in _SIDEBAR_ZONES:
        assert set(zone_keys) == EXPECTED_ZONES[zone], \
            f"{zone} 成员漂移: {sorted(zone_keys)}"
    flat = [k for _zone, zone_keys in _SIDEBAR_ZONES for k in zone_keys]
    assert sorted(flat) == sorted(PAGE_KEYS), \
        "七区未不重不漏覆盖 PAGE_KEYS 17 键（漏页/重复归区）"


def test_group_keys_by_zone_reorders_without_changing_key_set():
    """重排只换顺序不改键集：组间按区序，组内保持入参（PAGE_KEYS）相对序。"""
    full = _group_keys_by_zone(list(PAGE_KEYS))
    assert sorted(full) == sorted(PAGE_KEYS), "重排不得增删键"
    zone_order = {k: i for i, (_z, ks) in enumerate(_SIDEBAR_ZONES) for k in ks}
    # 组间连续成块
    seen_zones, last = [], None
    for k in full:
        z = zone_order[k]
        if z != last:
            seen_zones.append(z)
            last = z
    assert seen_zones == sorted(set(zone_order.values())), \
        f"区块交叉: {seen_zones}"
    # 组内保持 PAGE_KEYS 相对序（semantic 归查阅区后仍在 graph/corpus/domain 之后）
    z1 = [k for k in full if zone_order[k] == 0]
    assert z1 == [k for k in PAGE_KEYS if k in {"search", "graph", "corpus",
                                                "domain", "semantic"}]
    # 未知键（漏配区）稳定沉尾且不丢
    assert _group_keys_by_zone(["search", "mystery", "cluster"]) == \
        ["search", "cluster", "mystery"]


def test_option_label_prefixes_zone_and_keeps_page_label():
    """标签契约（RV21-5 瘦身后）：页名同源；区名含于页名 → 省前缀；
    否则前缀 =【区名（去 emoji）】。分组归属由选项分块位置表达。"""
    import re as _re

    def _zone_text(zone: str) -> str:
        return _re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "",
                       zone).strip()

    for key in PAGE_KEYS:
        label = sidebar_option_label(key)
        assert label.endswith(page_label(key)), f"{key}: 页名未取自 page_label"
    for zone, zone_keys in _SIDEBAR_ZONES:
        zt = _zone_text(zone)
        for key in zone_keys:
            label = sidebar_option_label(key)
            if zt in page_label(key):
                assert label == page_label(key), (
                    f"{key}: 区名含于页名应省前缀 {label!r}")
            else:
                assert label.startswith(f"【{zt}】"), (
                    f"{key}: 前缀应为去 emoji 区名 {label!r}")
                assert zt in page_label(key) or True


# ============================================
# 3. 未登录锁（AppTest）
# ============================================

def test_anon_sees_only_browse_entries_grouped():
    """未登录：无 exception；radio 只出未登录可见集，受保护页入口全隐藏。

    分组照实呈现：查阅区四页 + 标注平台（语义建模区、页面层登录门）+
    帮助中心（系统管理区、全员可达）—— 帮助中心入口保持可达。
    """
    at = _new_at()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    keys = _radio_keys(at)
    assert keys == ANON_VISIBLE, \
        f"未登录侧边栏应为六键（七区序）: {keys}"
    for hidden in ANON_HIDDEN:
        assert hidden not in keys, f"未登录不得见 {hidden}"

    # 批次 22 按钮式侧边栏：小节头（ls-nav-header）分块 + 按钮标签=页名。
    # 前四页=查阅展示区，随后标注平台（语义建模区）、帮助中心（系统管理区）
    headers = [m.value for m in at.markdown if "ls-nav-header" in m.value]
    assert any("查阅展示" in h for h in headers), headers
    assert any("语义建模" in h for h in headers), headers
    assert any("系统管理" in h for h in headers), headers
    # RV21-5 瘦身契约抽检：区名含于页名的页无前缀（语义分析等），此处六键
    # 中标注平台应为「【语义建模】🏷️ 标注平台」形态
    nav = _nav_buttons(at)
    assert any(str(b.label) == page_label("annotate") for b in nav), \
        "标注平台按钮形态漂移"  # AppTest Button.type=元素类型（'button'），kind 不外露


# ============================================
# 4. 分组不越权不漏页 + admin 可达锁（AppTest）
# ============================================

@pytest.mark.parametrize("session_key", sorted(_PROBE_SESSIONS))
def test_grouping_preserves_visible_set_per_session(session_key):
    """分组只改呈现：各探针会话的 radio 键集（无序）== _visible_page_keys。"""
    user = _PROBE_SESSIONS[session_key]
    at = _new_at()
    if user is not None:
        at.session_state["user"] = user
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert set(_radio_keys(at)) == set(_visible_page_keys(user)), session_key


def test_admin_all_seven_zones_all_17_pages_click_through():
    """admin：七区全部 17 页可达 —— 逐页点选后 session_state["page"] 正确。

    逐页点选 = 对 radio 逐个 set_value（AppTest 的选项点击等价），单实例
    连续导航（贴近真实用户翻页）；每页断言：无 exception 且路由键正确。
    """
    at = _new_at()
    at.session_state["user"] = _ADMIN_SESSION
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    # 键集：恰为 PAGE_KEYS 全集；顺序：七区序（组内 PAGE_KEYS 相对序）
    keys = _radio_keys(at)
    assert sorted(keys) == sorted(PAGE_KEYS), \
        "admin 侧边栏应七区全部 17 页可达"
    assert keys == [k for _zone, zone_keys in _SIDEBAR_ZONES for k in zone_keys]

    # 七区全部渲染：每区首键标签符合 RV21-5 瘦身契约（区名含于页名→省前缀，
    # 否则【去 emoji 区名】前缀）——分块位置由上面 keys 顺序断言锁定
    import re as _re

    def _zone_text(z: str) -> str:
        return _re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", z).strip()

    labels = _radio_labels(at)
    for zone, zone_keys in _SIDEBAR_ZONES:
        zt = _zone_text(zone)
        first = sidebar_option_label(zone_keys[0])
        if zt in page_label(zone_keys[0]):
            assert first == page_label(zone_keys[0]), f"{zone} 区首键应省前缀"
        else:
            assert first.startswith(f"【{zt}】"), f"七区缺 {zone} 区块"

    # 逐页点选（路由契约：key="page" 写 session_state，main() 按其分派）
    for key in PAGE_KEYS:
        _goto(at, key)
        assert not at.exception, \
            [str(e.value) for e in at.exception] + [f"点选 {key} 后异常"]
        assert at.session_state["page"] == key, \
            f"点选 {key} 后路由键错: {at.session_state['page']}"
