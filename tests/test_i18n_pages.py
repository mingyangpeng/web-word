"""R1 双语逐页实证 —— en 态逐页 AppTest 渲染 ＋ 语言切换往返 ＋ 持久化往返。

前两轮双语 review 只做过框架层（tests/test_i18n.py：字典哨兵/三级回退/
set_lang 单测）与页 H1 接线，本轮**逐页＋页面级**深测：

  1. **en 态逐页渲染**（17 页）：admin 登录 mock（fx23 先例）单实例依次
     _goto 全部 17 页，逐页断言 `not at.exception`（只抓 exception/
     StreamlitAPIException 类崩溃——框架层已知页面正文渐进式保持中文，
     **不做正文中文残留断言**，只采集 en 率供报告）；未登录侧另跑
     未登录可见六页（search/graph/corpus/domain/annotate/help）；
  2. **框架层无中文残留**（i18n 所有权面，硬断言）：en 态侧边栏 17 页
     导航按钮 label 逐字等于 ZH_EN 译文且零 CJK、七区区头零 CJK、
     登录区（Username/Password/Sign in）英文；
  3. **语言切换往返**：语言 radio zh→en→zh —— session ui_lang 跟随、
     导航 label 英文↔中文逐字往返（page_label 稳定）、radio 值稳定；
  4. **user_profiles 持久化往返**：登录态（真库 3307，requires_db 门）
     radio 切 en → user_profiles(ui.lang) 落 'en'（SQL 直证 ＋
     get_profile 读回路径）→ 切回 zh → 落 'zh' → 清理现场。

时序/手法契约（两轮实证踩坑记录）：
  * **en 态导航必须按 widget key（nav_{page_key}）点选**：批次 49 起
    导航按钮 label 过 _t —— en 态 label 是英文译文，helpers._goto 的
    page_label（中文）标签匹配在 en 态必落空。本文件 _goto_key 按
    app.py 渲染的固定 key 抓按钮，两语言通吃；
  * ZH_EN 查译文只能在 AppTest 会话外用字典直查（裸模式 get_lang 恒
    zh，i18n.t() 在裸模式返回原文——tests/test_i18n 先例同因）；
  * 单实例逐页走查沿用 fx23 先例（admin 全 17 页连续导航）——AppTest
    每实例首启成本远高于单轮 rerun，且页间会话连续更贴近真实用户。

报告口径（本文件输出的逐页表）：exception 计数（必须 0）＋ en 率
（主区文本去 <style> 后 1 − CJK 字符占比；正文中文为已知渐进式现状，
该率只入报告不设阈值断言）。
"""

import re
import sys

import pytest

# 时序契约（tests/conftest.py 头注）：conftest 已先于本文件设定 env 并
# import tests.helpers 固定 src.* 加载时序；这里再 import 命中 sys.modules 缓存。
from tests import helpers  # noqa: F401
from tests.helpers import _new_at, requires_db

from src.app import _SIDEBAR_ZONES  # fx23 先例：import 真模块对照区名
from src.i18n import ZH_EN
from src.mysql_db import get_db_cursor
from src.page_guides import PAGE_KEYS, page_label

# fx23 口径的 admin 登录 mock（六角色会话；_USER_DB_BACKED_KEY 未置 →
# _refresh_session_user 跳过实时回查，纯会话计算）
_ADMIN_SESSION = {
    "id": 1,
    "username": "admin",
    "display_name": "管理员",
    "role": "admin",
    "roles": ["dict_admin", "sys_admin"],
}

# 未登录可见页（fx23 ANON_VISIBLE 同口径：查阅区四页＋标注平台＋帮助中心）
ANON_VISIBLE = ["search", "graph", "corpus", "domain", "annotate", "help"]

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_STYLE_RE = re.compile(r"<style>.*?</style>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


# ============================================
# en 态适配的导航/文本 helper
# ============================================

def _goto_key(at, key: str):
    """en 态导航：按 widget key（app.py 渲染的 nav_{key}）点选导航按钮。

    helpers._goto 以 page_label（中文）标签匹配——en 态按钮 label 已过 _t
    是英文译文，标签匹配必落空；widget key 与语言无关，两态通用。
    """
    hits = [b for b in at.sidebar.button if str(b.key) == f"nav_{key}"]
    assert hits, f"导航按钮不存在（en 态按 key 抓取）: {key}"
    hits[0].click()
    at.run()


def _nav_labels(at) -> dict:
    """导航按钮 {page_key: label}（按 widget key 还原页键，两语言通用）。"""
    return {str(b.key)[4:]: str(b.label) for b in at.sidebar.button
            if str(b.key).startswith("nav_")}


def _lang_radio(at):
    """侧边栏语言 radio（'🌐 Language / 语言'；label 双语形态刻意保留）。"""
    hits = [r for r in at.sidebar.radio if "Language" in str(r.label)]
    assert hits, "语言 radio 不在场"
    return hits[0]


def _zone_headers(at) -> list:
    """侧边栏区头文本（ls-nav-header div 内文案，已剥壳）。

    先剥 <style> 块再抓 div——design_system 的 CSS 大 markdown 也含
    'ls-nav-header' 字样（选择器文本），不剥会混进伪区头。
    """
    headers = []
    for m in at.markdown:
        v = _STYLE_RE.sub("", str(m.value))
        hit = re.search(r"ls-nav-header'>(.*?)</div>", v, re.S)
        if hit:
            headers.append(hit.group(1))
    return headers


def _page_text(at) -> str:
    """主区文本聚合（去 <style> CSS 块、去标签）——en 率度量原料。"""
    parts: list = []
    for el in at.markdown:
        parts.append(_TAG_RE.sub("", _STYLE_RE.sub("", str(el.value))))
    for getter in (at.caption, at.header, at.subheader, at.title, at.text):
        parts.extend(str(el.value) for el in getter)
    for el in at.button:
        parts.append(str(el.label))
    for getter in (at.radio, at.selectbox, at.checkbox, at.text_input,
                   at.text_area, at.multiselect):
        parts.extend(str(el.label) for el in getter)
    for el in at.metric:
        parts.append(f"{el.label}{el.value}")
    return " ".join(parts)


def _en_stats(at) -> dict:
    """en 率统计：en_rate = 1 − CJK 字符占比（去 <style> 后；信息度量）。"""
    blob = re.sub(r"\s", "", _page_text(at))
    total = len(blob)
    cjk = len(_CJK_RE.findall(blob))
    return {"en_rate": round(1 - cjk / total, 2) if total else 1.0,
            "cjk": cjk, "total": total}


# ============================================
# fixture：en 态 admin 逐页走查（单实例，fx23 先例）
# ============================================

@pytest.fixture(scope="module")
def en_admin_reports():
    """en 态 admin 单实例走查 17 页：逐页采集 exception/en 率/ui_lang。

    报告行随走查即打印（pytest -s 可见），供 R1 逐页结果表引用。
    """
    reports: dict = {}
    at = _new_at()
    at.session_state["ui_lang"] = "en"
    at.session_state["user"] = _ADMIN_SESSION
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    # 框架层硬断言（i18n 所有权面）：17 页导航 label = ZH_EN 译文、零 CJK
    labels = _nav_labels(at)
    assert sorted(labels) == sorted(PAGE_KEYS), \
        f"en 态导航页键集漂移: {sorted(labels)}"
    for key, label in labels.items():
        expected = ZH_EN.get(page_label(key), page_label(key))
        assert label == expected, \
            f"en 态导航 label 应为 ZH_EN 译文: {key} {label!r} != {expected!r}"
        assert not _CJK_RE.search(label), f"en 态导航 label 残留中文: {label!r}"
    # 七区区头：逐字 = ZH_EN 译文、零 CJK
    heads = _zone_headers(at)
    expected_heads = [ZH_EN[zone] for zone, _keys in _SIDEBAR_ZONES
                      if any(k in PAGE_KEYS for k in _keys)]
    assert len(heads) == len(expected_heads), \
        f"区头数漂移: {heads} != {expected_heads}"
    for head, expected in zip(heads, expected_heads):
        assert head == expected, f"en 态区头应=译文: {head!r} != {expected!r}"
        assert not _CJK_RE.search(head), f"en 态区头残留中文: {head!r}"
    # 登录区英文（未登录分支的 Username/Password 在 admin 态不可见——
    # 登录区改显「退出」；语言 radio 双语 label 刻意保留不查 CJK）
    assert str(at.session_state["ui_lang"]) == "en"

    print("\n== R1 en 态逐页走查（admin mock）==")
    for key in PAGE_KEYS:
        _goto_key(at, key)
        exc = [str(e.value) for e in at.exception]
        stats = _en_stats(at)
        reports[key] = {"exception": exc, "ui_lang": str(
            at.session_state["ui_lang"]), **stats}
        print(f"{key:16s} exc={len(exc)} en_rate={stats['en_rate']:.2f} "
              f"cjk={stats['cjk']}/{stats['total']}")
    return reports


@pytest.fixture(scope="module")
def en_anon_reports():
    """en 态未登录走查六可见页（口径同 fx23 ANON_VISIBLE）。"""
    reports: dict = {}
    at = _new_at()
    at.session_state["ui_lang"] = "en"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    for key in ANON_VISIBLE:
        _goto_key(at, key)
        exc = [str(e.value) for e in at.exception]
        reports[key] = {"exception": exc,
                        "ui_lang": str(at.session_state["ui_lang"]),
                        **_en_stats(at)}
    return reports


# ============================================
# 1. en 态逐页渲染（17 页 admin ＋ 6 页未登录；只抓崩溃类）
# ============================================

@pytest.mark.parametrize("page_key", sorted(PAGE_KEYS))
def test_en_admin_page_renders_without_crash(en_admin_reports, page_key):
    """en 态 admin 逐页渲染：零 exception（含 StreamlitAPIException 类崩溃）、
    语言态保持 en。页面正文中文残留为已知渐进式现状，不在此断言（en 率入
    报告）；框架层（导航/区头/登录区）零残留由 fixture 硬断言锁定。"""
    rep = en_admin_reports[page_key]
    assert rep["exception"] == [], \
        f"en 态 {page_key} 渲染异常: {rep['exception']}"
    assert rep["ui_lang"] == "en", f"en 态走查中 {page_key} 语言态漂移"


@pytest.mark.parametrize("page_key", sorted(ANON_VISIBLE))
def test_en_anon_page_renders_without_crash(en_anon_reports, page_key):
    """en 态未登录逐页渲染（可见六页）：零 exception、语言态保持 en。"""
    rep = en_anon_reports[page_key]
    assert rep["exception"] == [], \
        f"en 态未登录 {page_key} 渲染异常: {rep['exception']}"
    assert str(rep.get("ui_lang", "en")) == "en"


def test_en_anon_sidebar_framework_english():
    """en 态未登录：导航 label=译文零 CJK ＋ 登录区 Username/Password/Sign in。"""
    at = _new_at()
    at.session_state["ui_lang"] = "en"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    labels = _nav_labels(at)
    assert sorted(labels) == sorted(ANON_VISIBLE)
    for key, label in labels.items():
        expected = ZH_EN.get(page_label(key), page_label(key))
        assert label == expected and not _CJK_RE.search(label), \
            f"en 态未登录导航 label 漂移: {key} {label!r}"
    inputs = [str(t.label) for t in at.sidebar.text_input]
    assert "Username" in inputs and "Password" in inputs, inputs
    assert any(str(b.label) == ZH_EN["登录"] for b in at.sidebar.button), \
        "en 态登录提交按钮（Sign in）不在场"


# ============================================
# 2. 语言切换往返（zh→en→zh，radio 交互）
# ============================================

def test_lang_radio_roundtrip_labels_and_session():
    """zh→en→zh：session ui_lang 跟随；导航 label 英文↔中文逐字往返
    （page_label 稳定）；radio 值稳定；全程零 exception。"""
    at = _new_at()
    at.session_state["ui_lang"] = "zh"
    at.session_state["user"] = _ADMIN_SESSION
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    zh_labels = _nav_labels(at)
    for key, label in zh_labels.items():
        assert label == page_label(key), \
            f"zh 态导航 label 应=page_label 原文: {key} {label!r}"

    # zh → en（radio 交互；set_lang 写会话后 st.rerun）
    _lang_radio(at).set_value("en")
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert str(at.session_state["ui_lang"]) == "en"
    en_labels = _nav_labels(at)
    for key, label in en_labels.items():
        expected = ZH_EN.get(page_label(key), page_label(key))
        assert label == expected and not _CJK_RE.search(label), \
            f"en 态导航 label 漂移: {key} {label!r}"

    # en → zh（往返回中文，label 逐字还原）
    _lang_radio(at).set_value("zh")
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert str(at.session_state["ui_lang"]) == "zh"
    assert _nav_labels(at) == zh_labels, "往返后导航 label 未逐字还原（page_label 稳定性）"
    assert str(_lang_radio(at).value) == "zh", "radio 值未随切回 zh"


def test_lang_radio_set_lang_invalid_choice_impossible():
    """语言 radio 选项恰为白名单两值的 format_func 映像（中文/English）——
    options 为 AppTest 的显示标签层，非白名单值无从出现（get_lang 脏值
    防御的入口面锁死）。"""
    at = _new_at()
    at.session_state["ui_lang"] = "zh"
    at.session_state["user"] = _ADMIN_SESSION
    at.run()
    r = _lang_radio(at)
    assert list(r.options) == ["中文", "English"], \
        f"语言 radio 显示选项应恰为白名单映像: {r.options}"


# ============================================
# 3. user_profiles 持久化往返（真库 3307；requires_db 门）
# ============================================

def _db_ui_lang(user_id: int):
    """SQL 直读 user_profiles.ui.lang（直证持久化落库；None=无行）。"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT pref_value FROM user_profiles "
            "WHERE user_id = %s AND pref_key = 'ui.lang' LIMIT 1",
            (user_id,))
        rows = cursor.fetchall()
        return rows[0]["pref_value"] if rows else None


def _db_clear_ui_lang(user_id: int) -> None:
    """清理 ui.lang 偏好行（测试前后各一次：现场自愈不漏库）。"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "DELETE FROM user_profiles WHERE user_id = %s AND pref_key = 'ui.lang'",
            (user_id,))


@requires_db
def test_ui_lang_persisted_roundtrip_via_radio(monkeypatch):
    """登录态语言 radio 往返 → user_profiles 落库往返（真库 3307）。

    set_lang 的持久化路径（i18n.py）：登录态（db_utils.current_user 会话
    dict）写 user_context_db.upsert_profile("ui.lang", lang)。radio 交互
    后 SQL 直证行值；get_profile 读回路径（会话身份桩为 mock 用户）断言
    pref_value == 'en' —— 即任务口径「set_lang 后 get_profile('ui.lang')
    == 'en'」（get_profile 裸模式无会话，桩 _resolve_user_id 的会话来源
    current_user；读写均走真库真 SQL，仅身份注入）。
    """
    from src import user_context_db

    _db_clear_ui_lang(_ADMIN_SESSION["id"])
    try:
        at = _new_at()
        at.session_state["ui_lang"] = "zh"
        at.session_state["user"] = _ADMIN_SESSION
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        assert _db_ui_lang(_ADMIN_SESSION["id"]) is None, "预清理未生效"

        # zh → en：radio 交互触发 set_lang（会话＋持久化双写）
        _lang_radio(at).set_value("en")
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        assert str(at.session_state["ui_lang"]) == "en"
        assert _db_ui_lang(_ADMIN_SESSION["id"]) == "en", \
            "set_lang('en') 未落 user_profiles（ui.lang）"

        # get_profile 读回路径（真库；会话身份桩为 mock 用户 id）
        monkeypatch.setattr(user_context_db, "current_user",
                            lambda: dict(_ADMIN_SESSION))
        row = user_context_db.get_profile("ui.lang")
        assert isinstance(row, dict) and row.get("pref_value") == "en", \
            f"get_profile('ui.lang') 应读回 'en': {row}"

        # en → zh：落库随切回（同键覆盖幂等）
        _lang_radio(at).set_value("zh")
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        assert str(at.session_state["ui_lang"]) == "zh"
        assert _db_ui_lang(_ADMIN_SESSION["id"]) == "zh", \
            "set_lang('zh') 未覆盖 user_profiles（ui.lang）"
    finally:
        _db_clear_ui_lang(_ADMIN_SESSION["id"])
