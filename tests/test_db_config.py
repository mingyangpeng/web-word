"""
Word database 辅助函数测试（不依赖真实 MySQL）
"""

from unittest.mock import MagicMock, patch

import pytest


class TestGetDbConfig:
    def test_default_values(self, monkeypatch):
        # 清空所有相关环境变量
        for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_CHARSET"):
            monkeypatch.delenv(key, raising=False)

        from data.word_database import get_db_config
        cfg = get_db_config()
        assert cfg["host"] == "localhost"
        assert cfg["port"] == 3306
        assert cfg["user"] == "root"
        assert cfg["password"] == ""
        assert cfg["database"] == "word_knowledge_db"
        assert cfg["charset"] == "utf8mb4"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "db.example.com")
        monkeypatch.setenv("DB_PORT", "3307")
        monkeypatch.setenv("DB_USER", "appuser")
        monkeypatch.setenv("DB_PASSWORD", "secret")
        monkeypatch.setenv("DB_NAME", "mydb")
        monkeypatch.setenv("DB_CHARSET", "latin1")

        from data.word_database import get_db_config
        cfg = get_db_config()
        assert cfg["host"] == "db.example.com"
        assert cfg["port"] == 3307
        assert cfg["user"] == "appuser"
        assert cfg["password"] == "secret"
        assert cfg["database"] == "mydb"
        assert cfg["charset"] == "latin1"


class TestExecuteQueryErrorHandling:
    def test_rollback_on_error(self):
        """模拟 cursor.execute 抛出 Error，验证 conn.rollback 被调用"""
        from mysql.connector import Error as MySQLError

        from data.word_database import DatabaseManager

        # 构造 mock 连接与 cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("syntax error")
        mock_conn.cursor.return_value = mock_cursor

        db = DatabaseManager(db_config={"host": "x"})
        with patch.object(db, "get_connection", return_value=mock_conn):
            with pytest.raises(MySQLError):
                db.execute_query("SELECT 1")

        mock_conn.rollback.assert_called_once()
        mock_cursor.close.assert_called_once()


class TestUpdateWord:
    def test_no_kwargs_returns_false(self):
        from data.word_database import DatabaseManager
        db = DatabaseManager(db_config={"host": "x"})
        assert db.update_word(1) is False
