"""
测试配置和共享 fixtures
"""

import pytest
import tempfile
import shutil

from src.database import init_db


@pytest.fixture(scope="function")
def test_db():
    """创建临时测试数据库"""
    yield
    # 清理工作
