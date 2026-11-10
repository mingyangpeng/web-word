"""批次 20 用户偏好键消费测试（FX-38）。

批次 19（FX-37）只做了偏好读写 UI（users_admin_page「⚙️ 我的偏好」段，
预置 _PREF_PRESET_KEYS 两键：ui.default_category / ui.rows_per_page）；
本批让键真正生效 —— 测试三块：

  * user_context_db.get_pref（新增值级直读面）：三态（有值 / 无值默认 /
    未登录 default）＋ 键清洗照 _check_key（非法不触库）＋ 库不可用 /
    脏值 fail-closed 回 default；SQL 恒带 user_id（own-rows-only）；
  * app.py 消费点 _rows_per_page_pref（语料页搭配明细行数）：两态
    （偏好命中生效 / 偏好越界或脏值回退默认）＋ clamp [10,200] ＋
    脏偏好值不崩；
  * 源级接线锁：render_corpus_dataset_page 明细取数走 _rows_per_page_pref
    （硬编码 limit=100 退役，未登录面数值不变 —— fx29 接线等价锁口径）；
    槽位枚举 limit=2000 全量扫描不消费偏好；ui.default_category 的范畴包
    combobox 不在 app.py 托管面（真身 src/semantic_search.py ss_category）
    —— 挂账依据锁，防后续批误判消费点已接线。

任务预设的「偏好命中 index / 偏好不在选项集回退」两态对应到本批唯一
app.py 托管消费点（行数 clamp）即「有效值生效 / 越界·脏值回退默认」；
index 形态消费点随范畴包 combobox 一并挂账（见输出勘察表）。

全部不依赖真库（数据层 monkeypatch ＋ FakeCursor，fx37 同款假体）。
"""

import inspect
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.app as app_module  # noqa: E402  （模块级导入执行 init_database，仓库既有测试口径）
from src import user_context_db  # noqa: E402
from src.user_context_db import get_pref  # noqa: E402

UID = 138


# ============================================
# 假体：DB 游标（fx37 同款最小件）
# ============================================

class _FakeCursor:
    """get_db_cursor 上下文假体：记录 SQL/params，fetch 按预设行返回。"""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.sqls = []
        self.params_list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.sqls.append(sql)
        self.params_list.append(params)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _BoomCursor:
    """一触即炸的游标（降级路径用；记录调用次数供零访问断言）。"""

    def __init__(self):
        self.calls = 0

    def __enter__(self):
        self.calls += 1
        raise pymysql.Error("db down")

    def __exit__(self, *exc):
        return False


def _login_ucdb(monkeypatch, uid=UID):
    """数据层会话 → 指定用户（fx31/fx37 同款：ucdb.current_user 模块级引用）。"""
    monkeypatch.setattr(user_context_db, "current_user",
                        lambda: {"id": uid, "username": "fx38"})


def _sentinel_on(monkeypatch):
    """建表哨兵置位（ensure 直通，单测不触 DDL 路径）。"""
    monkeypatch.setattr(user_context_db, "_TABLES_ENSURED", True)


def _stub_cursor(monkeypatch, rows):
    """登录态 + 哨兵 + 预设行游标（成功路径标配）。"""
    fake = _FakeCursor(rows)
    _login_ucdb(monkeypatch)
    _sentinel_on(monkeypatch)
    monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: fake)
    return fake


# ============================================
# 1. get_pref 值级直读（三态 + 校验先拒 + 降级）
# ============================================

class TestGetPref:
    """get_pref(key, default)：消费面只关心值 —— 有值返回值，无值/未登录/
    断库/键非法一律 default；键清洗照 _check_key，SQL 恒带 user_id。"""

    # ---- 三态之一：有值 → 原样返回（SQL own-rows-only 锁）----

    def test_pref_value_returned_as_is(self, monkeypatch):
        fake = _stub_cursor(
            monkeypatch, [{"pref_value": "motion"}])
        assert get_pref("ui.default_category") == "motion"
        sql = " ".join(fake.sqls[0].split())
        assert "SELECT pref_value FROM user_profiles" in sql
        assert "WHERE user_id = %s AND pref_key = %s LIMIT 1" in sql
        assert fake.params_list[0] == (UID, "ui.default_category")

    def test_pref_key_stripped_before_sql(self, monkeypatch):
        """键名清洗照 _check_key：两端空白 strip 后入 SQL（标识符非用户原文）。"""
        fake = _stub_cursor(monkeypatch, [{"pref_value": "20"}])
        assert get_pref("  ui.rows_per_page  ") == "20"
        assert fake.params_list[0] == (UID, "ui.rows_per_page")

    def test_pref_empty_string_value_returned_as_is(self, monkeypatch):
        """'' 是已设值（RV2-3 第 3 类反例不适用 KV：upsert 收 ''），原样返回
        —— 消费侧自判（如不在选项集回退），数据层不替消费方猜语义。"""
        _stub_cursor(monkeypatch, [{"pref_value": ""}])
        assert get_pref("ui.default_category") == ""

    # ---- 三态之二：无值（无键 / 键在值 NULL）→ default ----

    @pytest.mark.parametrize("rows", [
        [],                                # 无此键
        [{"pref_value": None}],            # 键已建未设值（RV2-3 第 2 类）
        ["not-a-dict"],                    # 脏行形态：非 dict 按「无值」降级
    ])
    def test_missing_or_null_value_returns_default(self, monkeypatch, rows):
        _stub_cursor(monkeypatch, rows)
        assert get_pref("ui.default_category") is None
        assert get_pref("ui.default_category", "motion") == "motion"

    def test_non_str_value_treated_as_unset(self, monkeypatch):
        """pref_value 非 str（数值注入类脏数据）按无值处理回 default
        （fx29「state_value 非字符串 → None」同口径），绝不猜态。"""
        _stub_cursor(monkeypatch, [{"pref_value": 20}])
        assert get_pref("ui.rows_per_page", 100) == 100

    # ---- 三态之三：未登录 → default（fail-closed 零 DB 访问）----

    def test_no_login_returns_default_zero_db(self, monkeypatch):
        boom = _BoomCursor()
        monkeypatch.setattr(user_context_db, "current_user", lambda: None)
        _sentinel_on(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        assert get_pref("ui.default_category", "motion") == "motion"
        assert boom.calls == 0

    # ---- 入参校验先拒（零 DB 访问，照 _check_key 口径）----

    @pytest.mark.parametrize("bad_key", [None, 123, "", "   ", "k" * 121])
    def test_bad_key_returns_default_no_db(self, monkeypatch, bad_key):
        boom = _BoomCursor()
        _login_ucdb(monkeypatch)
        _sentinel_on(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        assert get_pref(bad_key, "fallback") == "fallback"
        assert boom.calls == 0

    # ---- 库不可用降级：default（不抛）----

    def test_db_down_returns_default(self, monkeypatch):
        boom = _BoomCursor()
        _login_ucdb(monkeypatch)
        _sentinel_on(monkeypatch)
        monkeypatch.setattr(user_context_db, "get_db_cursor", lambda: boom)
        assert get_pref("ui.rows_per_page", "100") == "100"
        assert boom.calls == 1  # ensure 后触库才炸（登录态必须有 DB 访问尝试）


# ============================================
# 2. app.py 消费点：_rows_per_page_pref（两态 + clamp + 脏值不崩）
# ============================================

@pytest.fixture()
def pref_source(monkeypatch):
    """app._rows_per_page_pref 的读取源打桩缝：get_pref 经函数内导入逐次
    取 user_context_db.get_pref 模块属性 → monkeypatch 模块属性即生效。
    返回 set_pref(raw) 记录器（raw=None 模拟未登录/断库 fail-closed）。"""
    state = {"raw": None}

    def set_pref(raw):
        state["raw"] = raw

    monkeypatch.setattr(
        user_context_db, "get_pref",
        lambda key, default=None: (state["raw"]
                                   if isinstance(state["raw"], str) else None),
    )
    return set_pref


class TestRowsPerPagePref:
    """语料页搭配明细行数消费 ui.rows_per_page：命中生效 / 越界·脏值回退
    （任务「两态」在本消费点的形态），clamp [10,200]，默认 100 = 既有
    硬编码行为（无偏好不改变页面行为）。"""

    # ---- 两态之一：偏好命中 → 生效 ----

    @pytest.mark.parametrize("raw, want", [
        ("20", 20),          # 值域内直用
        ("100", 100),        # 与默认同值（幂等）
        ("  30  ", 30),      # 设置项两端空白：int() 前本函数 strip
        ("5", 10),           # clamp 下限
        ("500", 200),        # clamp 上限
    ])
    def test_valid_pref_applied_with_clamp(self, pref_source, raw, want):
        pref_source(raw)
        assert app_module._rows_per_page_pref() == want

    # ---- 两态之二：偏好不在值域 / 脏值 → 回退默认 100，不崩 ----

    @pytest.mark.parametrize("raw", [
        "motion",            # 脏值（范畴串误存行数键）
        "",                  # 空串
        "   ",               # 纯空白
        "20.5",              # 非整数字符串
        "1e2",               # 数值形态但不被 int() 收
    ])
    def test_dirty_pref_falls_back_to_default(self, pref_source, raw):
        pref_source(raw)
        assert app_module._rows_per_page_pref() == 100

    @pytest.mark.parametrize("unset", [None, object()])
    def test_unset_pref_falls_back_to_default(self, pref_source, unset):
        """未登录 / 断库 / 键在值空（get_pref 返回 None）与任意非 str 回
        默认 —— 无偏好不改变页面行为。"""
        pref_source(unset)
        assert app_module._rows_per_page_pref() == 100

    def test_default_arg_passthrough(self, pref_source):
        """default 参数透传（消费面可带各自默认；本页唯一调用点用默认 100）。"""
        pref_source(None)
        assert app_module._rows_per_page_pref(default=50) == 50

    def test_reader_failure_falls_back_not_crash(self, monkeypatch):
        """读取链自身异常（导入/调用意外）按无偏好降级 —— 语料页不被
        偏好功能拖垮（_logout/_resume_page_loader fail-open 先例）。"""
        def boom(key, default=None):
            raise RuntimeError("session broken")

        monkeypatch.setattr(user_context_db, "get_pref", boom)
        assert app_module._rows_per_page_pref() == 100


# ============================================
# 3. 源级接线锁（消费点在场 ＋ 挂账依据）
# ============================================

class TestWiringLocks:
    """源级锁：接线不漂移、挂账不误判。"""

    _corpus_src = inspect.getsource(app_module.render_corpus_dataset_page)
    _app_src = inspect.getsource(app_module)

    def test_corpus_detail_consumes_pref(self):
        """搭配明细取数走 _rows_per_page_pref（硬编码 limit=100 退役）。"""
        assert '"limit": _rows_per_page_pref()' in self._corpus_src
        assert '"limit": 100' not in self._corpus_src

    def test_slot_scan_limit_untouched(self):
        """槽位枚举 limit=2000 是全量扫描（构建槽位选项集）非展示行数
        —— 不消费行数偏好（clamp 会截断槽位发现），保持硬编码。"""
        assert '"limit": 2000' in self._corpus_src

    def test_not_logged_in_pref_keeps_fx29_equivalence(self):
        """未登录面 get_pref → None → 100：fx29 接线等价锁
        （calls[1] limit=100）在无偏好会话口径不变。"""
        # _rows_per_page_pref 的默认值即旧硬编码值
        sig_src = inspect.getsource(app_module._rows_per_page_pref)
        assert "default: int = 100" in sig_src

    def test_no_category_pack_combobox_in_app(self):
        """ui.default_category 挂账依据：范畴包 combobox（ss_category）不在
        app.py 托管面 —— 真身在 src/semantic_search.py（批次 19 后仍硬编码
        motion 默认），本批不改非托管模块。"""
        assert "ss_category" not in self._app_src
        import src.semantic_search as ss_module

        ss_src = inspect.getsource(ss_module)
        assert '"ss_category"' in ss_src          # 真实控件在场（挂账目标）
        assert "index=default_idx" in ss_src      # 仍为硬编码默认（未接线）
