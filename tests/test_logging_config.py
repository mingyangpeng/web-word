"""
配置与日志模块测试
"""

import io
import logging

from config.logging_config import get_logger, set_global_level


class TestLoggingConfig:
    def test_get_logger_returns_logger(self):
        logger = get_logger("test_module_1")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_caches(self):
        l1 = get_logger("test_module_2")
        l2 = get_logger("test_module_2")
        assert l1 is l2

    def test_different_names_distinct(self):
        l1 = get_logger("test_module_3")
        l2 = get_logger("test_module_4")
        assert l1 is not l2

    def test_logger_writes_to_stdout(self, capsys):
        logger = get_logger("test_capture_xyz")
        logger.info("hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.out
        assert "INFO" in captured.out

    def test_set_global_level_changes_level(self):
        logger = get_logger("test_level")
        set_global_level(logging.WARNING)
        assert logger.level == logging.WARNING
        # 恢复
        set_global_level(logging.INFO)
