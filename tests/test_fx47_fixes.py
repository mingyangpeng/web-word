"""批次 27 监工轮消缺测试（RV4-2/RV4-4）。

RV4-2：_sha256_file 对 NUL byte 路径（ValueError）兜底返 None——登记前
去重预检不崩页（P2：漏接会带 traceback 崩上传通道）。
RV4-4：config.toml showErrorDetails=false 契约钉死（生产不外泄 traceback）。
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.dict_admin_pages as dp  # noqa: E402


class TestSha256FileValueError:
    """RV4-2：NUL byte 路径 OSError/ValueError 双兜底。"""

    def test_nul_byte_path_returns_none_not_raise(self):
        """NUL byte 路径（部分平台 ValueError）→ None，不崩。"""
        bad = "/tmp/with\x00nul.bin"
        assert "\x00" in bad
        assert dp._sha256_file(bad) is None

    def test_missing_file_returns_none(self):
        """常规 OSError 面：不存在路径 → None。"""
        assert dp._sha256_file("/nonexistent/no/such/file.bin") is None

    def test_valid_file_still_hashes(self, tmp_path):
        """正常文件回归：内容哈希正确。"""
        f = tmp_path / "a.bin"
        f.write_bytes(b"hello")
        import hashlib
        assert dp._sha256_file(str(f)) == hashlib.sha256(b"hello").hexdigest()

    def test_source_catches_value_error(self):
        """源级钉板：except 子句含 ValueError（防回潮）。"""
        import inspect
        src = inspect.getsource(dp._sha256_file)
        assert "(OSError, ValueError)" in src


class TestShowErrorDetailsContract:
    """RV4-4：生产不外泄 traceback——config 契约钉死。"""

    def test_show_error_details_false(self):
        import tomllib
        cfg = tomllib.load(open(
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "src", ".streamlit", "config.toml"), "rb"))
        # showErrorDetails 在 [client] 段（Streamlit 的 traceback 外泄开关）
        client = cfg.get("client", {})
        assert client.get("showErrorDetails") is False, \
            "生产 showErrorDetails 必须 false（traceback 外泄面）"
