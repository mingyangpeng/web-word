"""
pytest 共享 fixture

提供：
- 临时数据库环境（:func:`isolated_db`）
- LLM 服务 mock（:func:`mock_llm_service`）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

# 将项目根目录加入 sys.path，使 `from config import ...` 等可被测试代码导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ========== 加载 .env 到 os.environ（仅当未设置时） ==========

def _load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # 不覆盖已存在的环境变量
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


@pytest.fixture
def isolated_db() -> Iterator["DatabaseManager"]:  # noqa: F821
    """
    构造一个隔离的 DatabaseManager。

    策略：复用现有 word_knowledge_db（jhon 用户仅有该库权限），
    在每个测试开始前 TRUNCATE 所有业务表，确保测试间数据隔离。
    """
    import mysql.connector

    from data.word_database import DatabaseManager, get_db_config

    cfg = get_db_config()
    db = DatabaseManager(db_config=cfg)

    # 清空所有业务表（保留表结构）
    _truncate_all_tables(db)

    try:
        yield db
    finally:
        db.close_connection()
        # 测试结束同样清空，避免残留
        try:
            _truncate_all_tables(db)
        except Exception:  # noqa: BLE001
            pass


# 业务表列表（按外键依赖顺序：被引用的表先清空引用方）
_BUSINESS_TABLES = [
    "chat_history",
    "learning_stats",
    "user_learning",
    "word_relations",
    "system_config",
    "words",
]


def _truncate_all_tables(db) -> None:
    """清空所有业务表数据（保留表结构）"""
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        # 临时关闭外键检查，避免依赖顺序问题
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in _BUSINESS_TABLES:
            cursor.execute(f"TRUNCATE TABLE `{table}`")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
    finally:
        cursor.close()


@pytest.fixture
def mock_llm_service(monkeypatch) -> MagicMock:
    """
    Mock 全局 LLM 服务，避免在测试中真实调用智谱 API。

    使用方式：
        def test_xxx(mock_llm_service):
            mock_llm_service.chat.return_value = {"choices": [...]}
    """
    mock = MagicMock(name="MockLLMService")
    monkeypatch.setattr("services.llm_service._llm_service", mock)

    # 同时替换 get_llm_service 返回值
    import services.llm_service as svc

    monkeypatch.setattr(svc, "get_llm_service", lambda: mock)
    return mock
