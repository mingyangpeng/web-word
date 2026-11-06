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
        r"(union\s+(all\s+)?select)", r"(select\s+.*\s+from)",
        r"(insert\s+into.*values)", r"(delete\s+from)",
        r"(drop\s+table)", r"(update.*set)",
        r"(;|--|/\*)", r"(xp_cmdshell)", r"(exec\s+\()"
    ]

    XSS_PATTERNS = [
        r"<script\b[^>]*>.*?</script>",
        r"<script\b",  # 未闭合的 script 开标签同样拒绝（.*? 不匹配换行、且可能没有闭合）
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
            if re.search(pattern, value, re.IGNORECASE | re.DOTALL):
                logger.warning(f"Potential SQL injection attempt: {value[:50]}")
                return False, "Invalid input detected"

        for pattern in cls.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE | re.DOTALL):
                logger.warning(f"Potential XSS attack: {value[:50]}")
                return False, "Invalid input detected"

        return True, None

    @classmethod
    def sanitize_html(cls, value):
        """清理HTML内容防止XSS"""
        return escape(value)


# CSV 公式注入防护：Excel/WPS 打开 CSV 时，以这些字符开头的单元格会被
# 当作公式执行（CSV Injection / Formula Injection）。业界通行做法是给
# 这类文本前置一个单引号 `'`，使其被解析为普通文本。
# = 公式；+/- 数值强制正负；@ 宏调用；\t 回车（\r）为 OWASP 建议的同批
# 危险前缀（制表符/回车开头的单元格会被部分表格软件解析为公式或被利用）。
CSV_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value):
    """对可能被 Excel 当作公式的 CSV 单元格文本前置单引号（唯一实现）。

    仅处理字符串；若首字符为 = + - @ \\t \\r 之一，则在最前面加 `'`。
    其余类型（数字、None 等）原样返回，正常文本不受影响。
    """
    if isinstance(value, str) and value[:1] in CSV_FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


# 历史别名：早期实现名，app.py / template_engine 等既有调用点沿用。
# 与 sanitize_csv_cell 指向同一实现，杜绝两份逻辑漂移。
sanitize_csv_value = sanitize_csv_cell


def sanitize_csv_dataframe(df):
    """对 DataFrame 的所有字符串单元格应用 CSV 公式注入防护。

    返回新的 DataFrame（不修改原对象），供 to_csv 导出前调用。
    """
    return df.map(sanitize_csv_cell) if hasattr(df, "map") else df.applymap(sanitize_csv_cell)


class KeyManager:
    """密钥管理器"""

    @staticmethod
    def get_api_key(provider):
        """从环境变量获取API密钥"""
        keys = {
            'zhipu': os.getenv('ZHIPUAI_API_KEY') or os.getenv('ZHIPU_API_KEY'),  # 新名优先
            'openai': os.getenv('OPENAI_API_KEY'),
            'deepseek': os.getenv('DEEPSEEK_API_KEY')
        }
        return keys.get(provider)

    @staticmethod
    def mask_key(key):
        """掩码API密钥（用于日志）。

        只有足够长的密钥才值得保留首尾 4 位：短于 16 位时首尾 4+4 会
        覆盖大半甚至全部密钥，掩码失去意义（len=8 时等于原样输出）。
        """
        if not isinstance(key, str) or len(key) < 16:
            return '****'

        # 掩码中间部分，保留前后 4 个字符
        prefix = key[:4]
        suffix = key[-4:]
        masked_length = len(key) - 8
        masked = '*' * max(4, masked_length)
        return prefix + masked + suffix
