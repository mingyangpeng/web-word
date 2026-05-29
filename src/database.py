"""
SQLite 数据库模块

提供数据库连接、表初始化和 CRUD 操作。
数据库文件存储在 data/ 目录下。
"""

import os
import json
import sqlite3
from contextlib import contextmanager

# ============================================
# 数据库路径
# ============================================
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "web_word.db")

# ============================================
# 建表 SQL
# ============================================
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verb TEXT NOT NULL,
    traditional_text TEXT,
    optimized_text TEXT,
    semantic_table TEXT,
    model_version TEXT DEFAULT 'mock',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER,
    verb TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_queries_verb ON queries(verb);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON queries(created_at);
CREATE INDEX IF NOT EXISTS idx_feedbacks_verb ON feedbacks(verb);
CREATE INDEX IF NOT EXISTS idx_feedbacks_query_id ON feedbacks(query_id);
"""


def _get_connection() -> sqlite3.Connection:
    """创建并返回一个新的数据库连接。"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_cursor(commit=False):
    """获取数据库游标的上下文管理器。

    Args:
        commit: 为 True 时，退出时自动 commit
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def init_db():
    """初始化数据库：建表。"""
    with get_cursor(commit=True) as cursor:
        cursor.executescript(CREATE_TABLES_SQL)


# ============================================
# 查询日志
# ============================================
def insert_query(verb: str, traditional_text: str = None,
                 optimized_text: str = None, semantic_table: list = None,
                 model_version: str = "mock") -> int:
    """插入一条查询记录，返回自增 ID。"""
    with get_cursor(commit=True) as cursor:
        cursor.execute(
            """INSERT INTO queries (verb, traditional_text, optimized_text, semantic_table, model_version)
               VALUES (?, ?, ?, ?, ?)""",
            (verb, traditional_text, optimized_text,
             json.dumps(semantic_table, ensure_ascii=False) if semantic_table else None,
             model_version)
        )
        return cursor.lastrowid


def get_query_by_verb(verb: str) -> dict | None:
    """根据动词查询最近一条查询记录。"""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM queries WHERE verb = ? ORDER BY created_at DESC LIMIT 1",
            (verb,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


# ============================================
# 用户反馈
# ============================================
def insert_feedback(verb: str, rating: int, feedback_text: str = None,
                    query_id: int = None) -> int:
    """插入一条用户反馈，返回自增 ID。"""
    with get_cursor(commit=True) as cursor:
        cursor.execute(
            """INSERT INTO feedbacks (query_id, verb, rating, feedback_text)
               VALUES (?, ?, ?, ?)""",
            (query_id, verb, rating, feedback_text)
        )
        return cursor.lastrowid


# ============================================
# 统计查询
# ============================================
def get_stats() -> dict:
    """获取统计数据：总查询次数、平均评分、总反馈数。"""
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total_queries FROM queries")
        total_queries = cursor.fetchone()["total_queries"]

        cursor.execute("SELECT COALESCE(AVG(rating), 0) AS avg_rating FROM feedbacks")
        avg_rating = round(float(cursor.fetchone()["avg_rating"]), 1)

        cursor.execute("SELECT COUNT(*) AS total_feedbacks FROM feedbacks")
        total_feedbacks = cursor.fetchone()["total_feedbacks"]

    return {
        "total_queries": total_queries,
        "avg_rating": avg_rating,
        "total_feedbacks": total_feedbacks,
    }


def get_hot_verbs(limit: int = 5) -> list[dict]:
    """获取热门动词及其平均评分。"""
    with get_cursor() as cursor:
        cursor.execute(
            """SELECT q.verb, COUNT(*) AS count,
                      COALESCE(AVG(f.rating), 0) AS avg_rating
               FROM queries q
               LEFT JOIN feedbacks f ON q.verb = f.verb
               GROUP BY q.verb
               ORDER BY count DESC
               LIMIT ?""",
            (limit,)
        )
        rows = cursor.fetchall()
        return [{"verb": r["verb"], "count": r["count"],
                 "avg_rating": round(float(r["avg_rating"]), 1)} for r in rows]


def get_feedback_data() -> list[dict]:
    """获取所有反馈数据，用于 CSV 导出。"""
    with get_cursor() as cursor:
        cursor.execute(
            """SELECT verb, rating, feedback_text, created_at
               FROM feedbacks ORDER BY created_at DESC"""
        )
        return [dict(r) for r in cursor.fetchall()]
