"""
安全模块

提供输入验证、输出编码、密钥管理等安全功能。
"""

import re
import logging
import os
from html import escape

logger = logging.getLogger(__name__)


class InputValidator:
    """输入验证器"""

    SQL_PATTERNS = [
        r"(union\s+select)", r"(select\s+.*\s+from)",
        r"(insert\s+into.*values)", r"(delete\s+from)",
        r"(drop\s+table)", r"(update.*set)",
        r"(;|--|/\*)", r"(xp_cmdshell)", r"(exec\s+\()"
    ]

    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"onload\s*=",
        r"<iframe[^>]*>",
        r"(alert\()",
        r"(document\.cookie)",
    ]

    @classmethod
    def validate_string(cls, value, max_length=1000):
        """
        验证字符串输入

        Returns:
            (是否有效, 错误消息)
        """
        if not isinstance(value, str):
            return False, "Input must be a string"

        if len(value) == 0:
            return False, "Input cannot be empty"

        if len(value) > max_length:
            return False, f"Input exceeds maximum length of {max_length}"

        for pattern in cls.SQL_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Potential SQL injection attempt: {value[:50]}")
                return False, "Invalid input detected"

        for pattern in cls.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Potential XSS attack: {value[:50]}")
                return False, "Invalid input detected"

        return True, None

    @classmethod
    def sanitize_html(cls, value):
        """清理HTML内容防止XSS"""
        return escape(value)


class KeyManager:
    """密钥管理器"""

    @staticmethod
    def get_api_key(provider):
        """从环境变量获取API密钥"""
        keys = {
            'zhipu': os.getenv('ZHIPU_API_KEY'),
            'openai': os.getenv('OPENAI_API_KEY'),
            'deepseek': os.getenv('DEEPSEEK_API_KEY')
        }
        return keys.get(provider)

    @staticmethod
    def mask_key(key):
        """掩码API密钥（用于日志）"""
        if not key or len(key) < 8:
            return '****'

        # 掩码中间部分，保留前后 4 个字符
        prefix = key[:4]
        suffix = key[-4:]
        masked_length = len(key) - 8
        masked = '*' * max(4, masked_length)  # 至少 4 个掩码字符
        return prefix + masked + suffix
