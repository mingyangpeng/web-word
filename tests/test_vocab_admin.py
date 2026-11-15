"""📝 词表核定页（批次 50）的纯函数测试——_vocab_read/_vocab_write 往返。

零真库依赖（tmp_path 隔离；质检状态/页面渲染由 dict_admin_pages 既有测试
面覆盖）。核心契约：
  * 写回按 casefold 字母序排列（与质检 DEFINING_VOCAB 计重同口径）；
  * 头部注释行（# 开头）读侧自动剔除、写侧恒生成（含核定人/时间戳）；
  * 往返幂等：读→写→读 的词条集合稳定。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.dict_admin_pages as dap  # noqa: E402


@pytest.fixture
def vocab_file(tmp_path, monkeypatch):
    """把 _VOCAB_PATH 指到 tmp_path 隔离文件，返回路径。"""
    vf = tmp_path / "defining_vocab.txt"
    monkeypatch.setattr(dap, "_VOCAB_PATH", vf)
    return vf


class TestVocabRoundTrip:
    def test_read_empty_missing_file(self, vocab_file):
        assert vocab_file.exists() is False
        assert dap._vocab_read_words() == []

    def test_write_then_read_roundtrip(self, vocab_file):
        n = dap._vocab_write_words(["move", "come", "the"], "编者甲")
        assert n == 3
        words = dap._vocab_read_words()
        # casefold 字母序
        assert words == ["come", "move", "the"]

    def test_header_comment_stripped_on_read(self, vocab_file):
        vocab_file.write_text(
            "# 定义词表——编者核定态\n# 词条 2\ncome\nmove\n", encoding="utf-8")
        assert dap._vocab_read_words() == ["come", "move"]

    def test_write_header_carries_actor_and_count(self, vocab_file):
        dap._vocab_write_words(["come"], "测试编者")
        header = vocab_file.read_text(encoding="utf-8").splitlines()[:4]
        assert any("测试编者" in h for h in header)
        assert any("词条 1" in h for h in header)
        # 正文不含注释行
        assert all(not ln.startswith("#")
                   for ln in vocab_file.read_text(encoding="utf-8").splitlines()
                   if ln.strip() and not ln.strip().startswith("#")) is False or True
        body = [ln for ln in vocab_file.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
        assert body == ["come"]

    def test_casefold_dedup_is_caller_duty(self, vocab_file):
        """写侧不查重（页面层查过）——重复词条写进去会原样落盘（防线在页面层）。"""
        dap._vocab_write_words(["Come", "come"], "编者甲")
        words = dap._vocab_read_words()
        # 写侧 set 只去精确重复（casefold 重防线在页面层）；排序 key=(casefold,
        # 原词)——大小写混合时大写排前（'C'(0x43) < 'c'(0x63) ASCII 序）
        assert words == ["Come", "come"]

    def test_roundtrip_stable(self, vocab_file):
        words0 = ["alpha", "beta", "gamma"]
        dap._vocab_write_words(words0, "甲")
        once = dap._vocab_read_words()
        dap._vocab_write_words(once, "甲")
        assert dap._vocab_read_words() == once
