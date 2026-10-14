"""
安全模块测试
"""

import os
from src.security import InputValidator, KeyManager


class TestInputValidator:
    """输入验证器测试"""

    def test_validate_string_valid(self):
        """测试有效的字符串输入"""
        is_valid, error = InputValidator.validate_string("跑进来", max_length=100)
        assert is_valid is True
        assert error is None

    def test_validate_string_empty(self):
        """测试空字符串"""
        is_valid, error = InputValidator.validate_string("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_validate_string_too_long(self):
        """测试超长字符串"""
        long_string = "a" * 1001
        is_valid, error = InputValidator.validate_string(long_string, max_length=1000)
        assert is_valid is False
        assert "length" in error.lower()

    def test_validate_xss(self):
        """测试XSS攻击"""
        xss_string = "<script>alert('xss')</script>"
        is_valid, error = InputValidator.validate_string(xss_string)
        assert is_valid is False

    def test_sanitize_html(self):
        """测试HTML清理"""
        input_html = "<script>alert('test')</script>Normal text"
        sanitized = InputValidator.sanitize_html(input_html)
        # escape 函数会转义 HTML 标签
        assert "&lt;script&gt;" in sanitized
        assert "&lt;script&gt;alert(&#x27;test&#x27;)&lt;/script&gt;" in sanitized
        assert "Normal text" in sanitized


class TestKeyManager:
    """密钥管理器测试"""

    def test_get_api_key(self):
        """测试获取API密钥"""
        os.environ['ZHIPU_API_KEY'] = 'test_key_12345'
        key = KeyManager.get_api_key('zhipu')
        assert key == 'test_key_12345'
        del os.environ['ZHIPU_API_KEY']

    def test_mask_key(self):
        """测试密钥掩码（长密钥保留首尾 4 位，长度不变）"""
        # 真实 API 密钥 32 位量级 —— 4+4 保留才不至于泄露大半密钥
        key = KeyManager.mask_key('test_key_1234567890abcdefghij')
        assert key.startswith('test')
        assert key.endswith('ghij')
        assert len(key) == len('test_key_1234567890abcdefghij')  # 保持长度不变

    def test_mask_key_short_key_fully_masked(self):
        """短密钥（<16 位）整体掩码 —— 保留首尾会泄露大半内容"""
        assert KeyManager.mask_key('short') == '****'
        assert KeyManager.mask_key('test_key_12345') == '****'  # 15 位：旧实现会泄露 11/15
        assert KeyManager.mask_key('abcdefgh') == '****'  # 8 位：旧实现等于原样输出
