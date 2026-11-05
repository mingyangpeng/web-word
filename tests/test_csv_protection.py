"""
CSV 公式注入防护测试（评审 R1 的 P2 安全遗留）

导出反馈数据 (CSV) 时，用户输入文本直接进 CSV——Excel 打开时以
= + - @ \\t 开头的单元格会被当作公式执行（CSV Injection）。
防护做法：对这类文本前置单引号 `'`（业界通行做法）。
"""

import pandas as pd

from src.security import (
    CSV_FORMULA_TRIGGER_CHARS,
    sanitize_csv_dataframe,
    sanitize_csv_value,
)


class TestSanitizeCsvValue:
    """单元格级防护：4 类触发字符 + 制表符"""

    def test_equals_sign_triggered(self):
        """以 = 开头的公式文本被前置单引号"""
        assert sanitize_csv_value("=SUM(A1:A2)") == "'=SUM(A1:A2)"

    def test_plus_sign_triggered(self):
        """以 + 开头的文本被前置单引号"""
        assert sanitize_csv_value("+8613800000000") == "'+8613800000000"

    def test_minus_sign_triggered(self):
        """以 - 开头的文本被前置单引号"""
        assert sanitize_csv_value("-1+1|cmd") == "'-1+1|cmd"

    def test_at_sign_triggered(self):
        """以 @ 开头的文本被前置单引号"""
        assert sanitize_csv_value("@import(url)") == "'@import(url)"

    def test_tab_triggered(self):
        """以 \\t 开头的文本被前置单引号"""
        assert sanitize_csv_value("\tpayload") == "'\tpayload"

    def test_trigger_chars_complete(self):
        """触发字符集合覆盖 = + - @ \\t"""
        assert set(CSV_FORMULA_TRIGGER_CHARS) == {"=", "+", "-", "@", "\t"}

    def test_normal_text_untouched(self):
        """正常文本不受影响（中文反馈、普通句子、空串）"""
        for text in ("动词标注很准", "hello world", "3.14", "评价：好用", ""):
            assert sanitize_csv_value(text) == text

    def test_mid_string_trigger_not_touched(self):
        """仅首字符触发：中间出现 = + - @ 不处理"""
        assert sanitize_csv_value("a=b") == "a=b"

    def test_non_string_untouched(self):
        """非字符串（数字、None）原样返回"""
        assert sanitize_csv_value(5) == 5
        assert sanitize_csv_value(-3) == -3
        assert sanitize_csv_value(None) is None


class TestSanitizeCsvDataFrame:
    """DataFrame 级防护：导出前整表处理"""

    def test_feedback_like_frame(self):
        """模拟反馈表导出：恶意文本被加引号，正常数据不动"""
        df = pd.DataFrame({
            "verb": ["run", "=HYPERLINK(\"http://evil\")"],
            "rating": [5, 1],
            "feedback_text": ["很好", "+cmd|' /C calc"],
        })
        out = sanitize_csv_dataframe(df)
        assert out.loc[0, "verb"] == "run"
        assert out.loc[0, "feedback_text"] == "很好"
        assert out.loc[1, "verb"].startswith("'=")
        assert out.loc[1, "feedback_text"].startswith("'+" )
        # 数字列不受影响
        assert out.loc[1, "rating"] == 1

    def test_original_df_not_mutated(self):
        """返回新对象，不修改原 DataFrame"""
        df = pd.DataFrame({"feedback_text": ["=cmd"]})
        out = sanitize_csv_dataframe(df)
        assert df.loc[0, "feedback_text"] == "=cmd"
        assert out.loc[0, "feedback_text"] == "'=cmd"

    def test_exported_csv_starts_with_quote(self):
        """端到端：to_csv 输出中恶意单元格带单引号前缀"""
        df = pd.DataFrame({"feedback_text": ["=1+1"]})
        csv = sanitize_csv_dataframe(df).to_csv(index=False)
        assert "'=1+1" in csv
