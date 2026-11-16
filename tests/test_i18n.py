"""src/i18n.py 单测 —— 原文即 key 渐进式双语基建的行为与哨兵锁。

覆盖面（对照任务验收口径）：
  * t() 双态：zh 态原样返回（显式 en 不生效）/ en 态查 ZH_EN /
    显式 en 优先于字典 / 未收录回落 zh 原文（未翻译不崩）；
  * get_lang 三级回退：会话 → user_context_db.get_profile("ui.lang")
    → 默认 zh；脏值（会话与偏好两层）不采信；user_context_db 读异常
    与 import 错误兜底；
  * set_lang：写会话 + 登录态持久化（monkeypatch user_context_db.
    upsert_profile 断言键值）；未登录只写会话不触库；断库/写异常
    不崩；非法 lang 拒绝（不写会话不触库）；
  * is_en 判定；
  * 字典哨兵：17 页 label 逐字覆盖（import src.page_guides 读真
    label 对照，emoji 保留）、七区头覆盖（_SIDEBAR_ZONES 区名逐字）、
    「🤖 模型供应商」与「🤖 AI 协作」译文区分、字典规模 60-80。

时序契约（tests/conftest.py 头注 / tests/helpers.py docstring）：本文件
的 src.* import 必须发生在 conftest 的 env 设定之后 —— conftest 在 env
块之后已显式 import tests.helpers 固定时序；本文件顶部再 import 一次
tests.helpers 命中 sys.modules 缓存（照 helpers 先例），保证后续
src.i18n / src.page_guides 以正确时序加载。

数据库纪律：本文件全部用 monkeypatch（session_state 换成 dict、
user_context_db 读写换桩），零真库依赖 —— conftest 的 MYSQL_PORT
fail-fast 与本文件无关（不触库）。
"""

import sys

# 时序哨兵：显式 import 一次（conftest 已保证 env 先行；见文件 docstring）
from tests import helpers  # noqa: F401  (导入即固定 helper 的 src 加载时序)

import src
from src import i18n
from src.page_guides import PAGE_GUIDES

# src/app.py _SIDEBAR_ZONES 的七区头（逐字照抄，含 emoji）——
# 哨兵口径：app.py 是脚本级模块（顶层有页面渲染面），单测不 import 它，
# 改区名时此清单与 app.py 的漂移由 test_dict_covers_seven_zone_heads 之外
# 的 test_page_guides 族/AppTest 集成测试兜底；本清单只在区名重命名时需
# 同步（与 tests/helpers._nav_buttons 依赖 page_label 标签集的既有口径一致）。
SEVEN_ZONE_NAMES = (
    "🔍 查阅展示",
    "🏷️ 语义建模",
    "📊 语义分析",
    "✍️ 编纂产出",
    "🤖 AI 协作",
    "📖 词典管理",
    "🔧 系统管理",
)

# app.py 语料页消费先例的登录会话形态（db_utils.current_user 口径：
# 会话 'user' 为 dict 即登录态）
_LOGGED_IN_USER = {"id": 7, "username": "i18n_user", "role": "viewer"}


# ============================================
# 注入工具（fx32 先例：monkeypatch.setattr(模块.st, "session_state", dict)）
# ============================================

def _patch_session(monkeypatch, initial=None) -> dict:
    """把 i18n 可见的 st.session_state 换成普通 dict（返回它供断言）。"""
    session = dict(initial or {})
    monkeypatch.setattr(i18n.st, "session_state", session)
    return session


def _patch_get_profile(monkeypatch, pref_value):
    """桩掉 user_context_db.get_profile，返回调用记录（断言是否触库/键名）。

    pref_value=None 模拟「无键/未登录/断库」（fail-closed 返回 None）；
    其他值模拟「键在值空/已设偏好」的行形态（pref_value 列）。
    """
    from src import user_context_db

    calls = []

    def fake_get_profile(key, *args, **kwargs):
        calls.append(key)
        if pref_value is None:
            return None
        return {"pref_key": key, "pref_value": pref_value}

    monkeypatch.setattr(user_context_db, "get_profile", fake_get_profile)
    return calls


def _patch_upsert_profile(monkeypatch, raise_exc=None):
    """桩掉 user_context_db.upsert_profile，返回调用记录（键值断言用）。

    raise_exc 非 None 时桩体抛异常（模拟断库/意外错误）。
    """
    from src import user_context_db

    calls = []

    def fake_upsert(key, value):
        calls.append((key, value))
        if raise_exc is not None:
            raise raise_exc
        return True

    monkeypatch.setattr(user_context_db, "upsert_profile", fake_upsert)
    return calls


def _block_user_context_db_import(monkeypatch):
    """强制 `from src import user_context_db` 抛 ImportError（import 兜底用）。

    双保险：删掉 src 包上的模块属性 + sys.modules 槽位置 None ——
    from-import 的 getattr 快捷路径与 sys.modules 命中路径都被堵死。
    """
    monkeypatch.delattr(src, "user_context_db", raising=False)
    monkeypatch.setitem(sys.modules, "src.user_context_db", None)


# ============================================
# t() —— 渐进式核心（原文即 key）
# ============================================

class TestT:
    def test_t_zh_state_returns_zh_verbatim(self, monkeypatch):
        """zh 态原样返回 zh：收录与未收录的 key 都逐字原样。"""
        _patch_session(monkeypatch, {"ui_lang": "zh"})
        assert i18n.t("登录") == "登录"
        assert i18n.t("🔍 搜索释义") == "🔍 搜索释义"
        assert i18n.t("这句未收录的页面文案 XYZ") == "这句未收录的页面文案 XYZ"

    def test_t_zh_state_ignores_explicit_en(self, monkeypatch):
        """zh 态连显式 en 参数也不生效 —— 输出由语言态唯一决定。"""
        _patch_session(monkeypatch, {"ui_lang": "zh"})
        assert i18n.t("登录", "Log in") == "登录"

    def test_t_en_dict_hit(self, monkeypatch):
        """en 态查 ZH_EN：通用词与带 emoji 的页 label 都能命中。"""
        _patch_session(monkeypatch, {"ui_lang": "en"})
        assert i18n.t("登录") == "Sign in"
        assert i18n.t("🔍 搜索释义") == "🔍 Search Definitions"
        assert i18n.t("请先登录。") == "Please sign in first."

    def test_t_en_explicit_en_wins_over_dict(self, monkeypatch):
        """en 态显式 en 参数优先于 ZH_EN 字典（就地译文的优先级最高）。"""
        _patch_session(monkeypatch, {"ui_lang": "en"})
        assert i18n.t("登录", "Log in") == "Log in"
        # 未收录 key + 显式 en → 就地译文也生效（渐进式的第二生长点）
        assert i18n.t("字典里没有的词", "Custom wording") == "Custom wording"

    def test_t_en_unlisted_falls_back_to_zh(self, monkeypatch):
        """en 态未收录 → 回落 zh 原文（未翻译不崩，渐进式核心契约）。"""
        _patch_session(monkeypatch, {"ui_lang": "en"})
        assert i18n.t("这句话还没翻译") == "这句话还没翻译"

    def test_t_default_lang_is_zh_without_any_state(self, monkeypatch):
        """无会话键 + 偏好无值 → 默认 zh 态（get_lang 全链回退穿 t()）。"""
        session = _patch_session(monkeypatch)
        calls = _patch_get_profile(monkeypatch, None)
        assert i18n.t("登录") == "登录"
        assert session.get("ui_lang") is None
        assert calls == [i18n.LANG_PREF_KEY]  # 偏好层被问过（键名逐字）


# ============================================
# get_lang —— 三级回退与脏值防御
# ============================================

class TestGetLang:
    def test_default_zh_when_no_session_no_profile(self, monkeypatch):
        """三级全空 → 默认 "zh"。"""
        _patch_session(monkeypatch)
        _patch_get_profile(monkeypatch, None)
        assert i18n.get_lang() == "zh"

    def test_session_state_wins_without_touching_profile(self, monkeypatch):
        """一级会话优先：命中即返回，不再触偏好层（读路径零 DB）。"""
        _patch_session(monkeypatch, {"ui_lang": "en"})
        calls = _patch_get_profile(monkeypatch, "zh")
        assert i18n.get_lang() == "en"
        assert calls == []  # 会话命中 → 偏好层未被问

    def test_profile_fallback_when_session_missing(self, monkeypatch):
        """二级回落：会话无键 → 读持久化偏好。"""
        _patch_session(monkeypatch)
        _patch_get_profile(monkeypatch, "en")
        assert i18n.get_lang() == "en"

    def test_dirty_profile_value_not_trusted(self, monkeypatch):
        """偏好脏值（非法语言/值空/行形态不对）一律不采信 → 默认 zh。"""
        _patch_session(monkeypatch)
        _patch_get_profile(monkeypatch, "fr")
        assert i18n.get_lang() == "zh"

        _patch_session(monkeypatch)
        _patch_get_profile(monkeypatch, None)  # 键在值空（pref_value NULL）
        assert i18n.get_lang() == "zh"

        from src import user_context_db

        monkeypatch.setattr(user_context_db, "get_profile", lambda key: "不是dict")
        assert i18n.get_lang() == "zh"

    def test_dirty_session_value_falls_through(self, monkeypatch):
        """会话脏值不采信 → 落到偏好层/默认（不猜态）。"""
        _patch_session(monkeypatch, {"ui_lang": "fr"})
        _patch_get_profile(monkeypatch, None)
        assert i18n.get_lang() == "zh"

    def test_profile_read_exception_fallback(self, monkeypatch):
        """偏好读取抛异常（断库等）→ 兜底默认 zh，不崩。"""
        _patch_session(monkeypatch)
        from src import user_context_db

        def boom(key):
            raise RuntimeError("db down")

        monkeypatch.setattr(user_context_db, "get_profile", boom)
        assert i18n.get_lang() == "zh"

    def test_user_context_db_import_error_fallback(self, monkeypatch):
        """user_context_db import 失败 → 兜底默认 zh（app.py 先例形态）。"""
        _patch_session(monkeypatch)
        _block_user_context_db_import(monkeypatch)
        assert i18n.get_lang() == "zh"


# ============================================
# set_lang —— 合法性校验 / 会话写入 / 登录态持久化
# ============================================

class TestSetLang:
    def test_set_lang_writes_session_and_persists_when_logged_in(self, monkeypatch):
        """登录态：写会话 + upsert_profile("ui.lang", lang) 落偏好。"""
        session = _patch_session(monkeypatch, {"user": dict(_LOGGED_IN_USER)})
        calls = _patch_upsert_profile(monkeypatch)
        assert i18n.set_lang("en") is True
        assert session["ui_lang"] == "en"
        assert calls == [("ui.lang", "en")]  # 键名与值逐字

    def test_set_lang_logged_out_writes_session_only(self, monkeypatch):
        """未登录：只写会话，不触持久化层（fail-closed 双保险）。"""
        session = _patch_session(monkeypatch)  # 无 "user" 键
        calls = _patch_upsert_profile(monkeypatch)
        assert i18n.set_lang("en") is True
        assert session["ui_lang"] == "en"
        assert calls == []

    def test_set_lang_dirty_user_session_treated_as_logged_out(self, monkeypatch):
        """会话 user 非 dict（脏值）→ 按未登录处理，不触库。"""
        session = _patch_session(monkeypatch, {"user": "不是dict"})
        calls = _patch_upsert_profile(monkeypatch)
        assert i18n.set_lang("en") is True
        assert session["ui_lang"] == "en"
        assert calls == []

    def test_set_lang_db_failure_still_writes_session(self, monkeypatch):
        """登录态断库（upsert 抛异常）：会话切换照常生效，不崩。"""
        session = _patch_session(monkeypatch, {"user": dict(_LOGGED_IN_USER)})
        _patch_upsert_profile(monkeypatch, raise_exc=RuntimeError("MySQL down"))
        assert i18n.set_lang("en") is True
        assert session["ui_lang"] == "en"

    def test_set_lang_persist_import_error_still_writes_session(self, monkeypatch):
        """登录态持久化 import 失败：只写会话不崩（尽力而为口径）。"""
        session = _patch_session(monkeypatch, {"user": dict(_LOGGED_IN_USER)})
        _block_user_context_db_import(monkeypatch)
        assert i18n.set_lang("en") is True
        assert session["ui_lang"] == "en"

    def test_set_lang_rejects_invalid_lang(self, monkeypatch):
        """非法 lang 拒绝：返回 False，会话与偏好都不动。"""
        session = _patch_session(monkeypatch, {"user": dict(_LOGGED_IN_USER)})
        calls = _patch_upsert_profile(monkeypatch)
        for bad in ("fr", "", "EN", "zh-CN", None, 123, True):
            assert i18n.set_lang(bad) is False, f"非法值应被拒绝: {bad!r}"
        assert "ui_lang" not in session
        assert calls == []

    def test_set_lang_roundtrip_switch_back_to_zh(self, monkeypatch):
        """en ↔ zh 往返：来回切换都会话生效 + 持久化，is_en 随动。"""
        session = _patch_session(monkeypatch, {"user": dict(_LOGGED_IN_USER)})
        _patch_upsert_profile(monkeypatch)
        assert i18n.set_lang("en") is True
        assert i18n.is_en() is True
        assert i18n.set_lang("zh") is True
        assert session["ui_lang"] == "zh"
        assert i18n.is_en() is False


# ============================================
# is_en —— 判定面
# ============================================

class TestIsEn:
    def test_zh_state_false(self, monkeypatch):
        _patch_session(monkeypatch, {"ui_lang": "zh"})
        assert i18n.is_en() is False

    def test_en_state_true(self, monkeypatch):
        _patch_session(monkeypatch, {"ui_lang": "en"})
        assert i18n.is_en() is True


# ============================================
# ZH_EN 字典哨兵 —— 与真模块对照，锁逐字一致
# ============================================

class TestDictionary:
    def test_dict_covers_all_17_page_labels(self):
        """17 页 label（import src.page_guides 读真值）逐条收录且 emoji 保留。"""
        assert len(PAGE_GUIDES) == 17, "页数哨兵：PAGE_GUIDES 应为 17 页"
        for page_key, guide in PAGE_GUIDES.items():
            label = guide["label"]
            assert label in i18n.ZH_EN, f"页 {page_key} 的 label 未收录: {label}"
            translated = i18n.ZH_EN[label]
            assert translated != label, f"页 {page_key} 的 label 未翻译: {label}"
            # emoji 保留：译文首字符与原文首字符一致（label 全部以 emoji 开头）
            assert translated[0] == label[0], \
                f"页 {page_key} 的 label 译文丢了 emoji: {label} → {translated}"

    def test_model_providers_translation_distinct_from_ai_hub(self):
        """「🤖 模型供应商」译 "🤖 Model Providers"，与 AI 协作的 "🤖 AI Hub" 区分。"""
        assert i18n.ZH_EN["🤖 模型供应商"] == "🤖 Model Providers"
        assert i18n.ZH_EN["🤖 AI 协作"] == "🤖 AI Hub"
        assert i18n.ZH_EN["🤖 模型供应商"] != i18n.ZH_EN["🤖 AI 协作"]

    def test_dict_covers_seven_zone_heads(self):
        """七区头（_SIDEBAR_ZONES 区名逐字）全部收录且 emoji 保留。"""
        for zone in SEVEN_ZONE_NAMES:
            assert zone in i18n.ZH_EN, f"区名未收录: {zone}"
            translated = i18n.ZH_EN[zone]
            assert translated != zone, f"区名未翻译: {zone}"
            assert translated[0] == zone[0], \
                f"区名译文丢了 emoji: {zone} → {translated}"

    def test_dict_size_within_framework_budget(self):
        """字典规模哨兵：批次 61 起转正为全量文案字典（框架层 + 批量包裹沉淀）。

        旧口径 60-80 是「框架层专用、页面文案就地传 en 参数」时代的预算；
        批次 61 全仓可见面批量 _t 包裹后，en 态查表成为主要译径，字典转为
        全量文案单一事实源——预算改为下限守门（≥200，防误删）＋上不封顶。"""
        assert len(i18n.ZH_EN) >= 200, \
            f"ZH_EN 条目数异常缩水（批次 61 后应 ≥200）: {len(i18n.ZH_EN)}"

    def test_dict_values_are_translated_strings(self):
        """全字典键值卫生：键值均非空 str、值与键不同（无「假翻译」条目）。"""
        for key, value in i18n.ZH_EN.items():
            assert isinstance(key, str) and key, f"非法键: {key!r}"
            assert isinstance(value, str) and value, f"键 {key!r} 的译文为空"
            assert value != key, f"键 {key!r} 的译文与原文相同（未真翻译）"
