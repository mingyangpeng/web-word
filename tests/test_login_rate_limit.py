"""批次 62 商业化测试：登录失败限速＋匿名日配额。

限速：进程级内存限速器（users_db._login_failures）——窗口/上限/清零/GC。
配额：anonymous_query_count_today 的 fail-open 口径（真库交互走 AppTest
已由浏览器验证覆盖，此处聚焦数据层口径）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.users_db import (  # noqa: E402
    _LOGIN_FAIL_MAX,
    _LOGIN_FAIL_WINDOW,
    _clear_login_failures,
    _login_failures,
    _login_locked,
    _record_login_failure,
    verify_login,
)


@pytest.fixture(autouse=True)
def _isolate_failures():
    """限速字典逐用例隔离（进程级全局态——不隔离会跨用例串味）。"""
    _login_failures.clear()
    yield
    _login_failures.clear()


class TestLoginRateLimit:
    def test_below_threshold_not_locked(self):
        """窗口内失败次数 < 上限：未锁定。"""
        for _ in range(_LOGIN_FAIL_MAX - 1):
            _record_login_failure("probe_u1")
        assert _login_locked("probe_u1") is False

    def test_at_threshold_locked(self):
        """窗口内失败次数达上限：锁定。"""
        for _ in range(_LOGIN_FAIL_MAX):
            _record_login_failure("probe_u2")
        assert _login_locked("probe_u2") is True

    def test_clear_unlocks(self):
        """成功登录清零 → 解锁。"""
        for _ in range(_LOGIN_FAIL_MAX):
            _record_login_failure("probe_u3")
        assert _login_locked("probe_u3") is True
        _clear_login_failures("probe_u3")
        assert _login_locked("probe_u3") is False

    def test_expired_window_unlocks(self, monkeypatch):
        """滑动窗口：全部失败记录过期后自动解锁（_login_locked 顺带清理）。"""
        import time

        for _ in range(_LOGIN_FAIL_MAX):
            _record_login_failure("probe_u4")
        assert _login_locked("probe_u4") is True
        # 把记录全部改成窗口外的时间戳
        monkeypatch.setitem(
            _login_failures, "probe_u4",
            [time.time() - _LOGIN_FAIL_WINDOW - 1] * _LOGIN_FAIL_MAX)
        assert _login_locked("probe_u4") is False
        # 清理后过期键已移除
        assert "probe_u4" not in _login_failures

    def test_gc_caps_dict_growth(self, monkeypatch):
        """GC：键数超 10000 时清过期键（防随机用户名攻击撑爆内存）。"""
        import time

        stale = [time.time() - _LOGIN_FAIL_WINDOW - 1]
        # 10001 个全部过期的键
        for i in range(10001):
            _login_failures[f"stale_{i}"] = stale
        _record_login_failure("fresh_probe")
        assert len(_login_failures) < 10001  # 过期键被清
        assert _login_failures.get("fresh_probe")  # 新键保留

    def test_verify_login_returns_none_when_locked(self):
        """锁定态 verify_login 返回 None（与密码错同口径——防枚举）。"""
        for _ in range(_LOGIN_FAIL_MAX):
            _record_login_failure("probe_locked")
        assert verify_login("probe_locked", "whatever-password") is None


class TestAnonQuotaCount:
    def test_count_fail_open(self, monkeypatch):
        """计数读失败返回 0（fail-open——统计故障不拦查询）。"""
        import src.mysql_db as db

        monkeypatch.setattr(db, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("probe down")))
        assert db.anonymous_query_count_today() == 0
