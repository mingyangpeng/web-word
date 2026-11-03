"""
统一日志配置

提供全局 logger 实例，替代散布各处的 print 语句。
支持通过环境变量 LOG_LEVEL 调整日志级别。
"""

import logging
import os
import sys
from typing import Optional


_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

_logger_cache: dict = {}


def get_logger(name: str = "web-word", level: Optional[int] = None) -> logging.Logger:
    """
    获取指定名称的 logger（带缓存，避免重复配置 handler）

    Args:
        name: logger 名称，建议传入模块名（如 __name__）
        level: 显式日志级别；未指定时从环境变量 LOG_LEVEL 读取，默认 INFO

    Returns:
        配置好的 logging.Logger 实例
    """
    if name in _logger_cache:
        logger = _logger_cache[name]
        if level is not None:
            logger.setLevel(level)
        return logger

    if level is None:
        env_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, env_level, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免向 root logger 传播导致重复输出
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT))
        logger.addHandler(handler)

    _logger_cache[name] = logger
    return logger


def set_global_level(level: int) -> None:
    """运行时调整所有已缓存 logger 的级别（用于设置页动态调整）"""
    for logger in _logger_cache.values():
        logger.setLevel(level)
