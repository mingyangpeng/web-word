"""
MySQL 8.0 数据库模块

提供数据库连接、表初始化和 CRUD 操作。
数据库存储在 MySQL 8.0 服务器上。
"""

import os
import json
import logging
from contextlib import contextmanager
from typing import Optional, Dict, List, Any
from datetime import datetime

# Try to import PyMySQL, provide fallback to SQLite
try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logging.warning("PyMySQL not available. Install with: pip install pymysql")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# 数据库配置
# ============================================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "web_word_db")
MYSQL_USER = os.getenv("MYSQL_USER", "web_word_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_CHARSET = "utf8mb4"
MYSQL_COLLATION = "utf8mb4_unicode_ci"

# Connection pool configuration
MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "5"))
MYSQL_POOL_MAX_OVERFLOW = int(os.getenv("MYSQL_POOL_MAX_OVERFLOW", "10"))

# ============================================
# 建表 SQL
# ============================================
CREATE_TABLES_SQL = """
-- Definitions table: store verb definitions and semantic decomposition
CREATE TABLE IF NOT EXISTS definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL UNIQUE,
    chinese_ndef TEXT NOT NULL,
    semantic_table JSON NOT NULL,
    example_sentence TEXT,
    model_version VARCHAR(50) DEFAULT 'zhipu-glm-4',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_definitions_verb (verb(50)),
    INDEX idx_definitions_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Synonyms table: store synonym relationships
CREATE TABLE IF NOT EXISTS synonyms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    original_verb_id INT NOT NULL,
    synonym_verb VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (original_verb_id) REFERENCES definitions(id) ON DELETE CASCADE,
    INDEX idx_synonyms_original (original_verb_id),
    INDEX idx_synonyms_synonym (synonym_verb(50))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Feedbacks table: store user feedback
CREATE TABLE IF NOT EXISTS feedbacks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL,
    rating INT NOT NULL CHECK(rating BETWEEN 1 AND 5),
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_feedbacks_verb (verb(50)),
    INDEX idx_feedbacks_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Usage logs table: record query logs
CREATE TABLE IF NOT EXISTS usage_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL,
    query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_info VARCHAR(255),
    INDEX idx_usage_logs_verb (verb(50)),
    INDEX idx_usage_logs_query_time (query_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Statistics table: cached statistics
CREATE TABLE IF NOT EXISTS statistics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stat_name VARCHAR(50) NOT NULL UNIQUE,
    stat_value TEXT NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_statistics_name (stat_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

# ============================================
# 初始化数据库
# ============================================
def init_database() -> bool:
    """
    Initialize MySQL database and create tables.

    Returns:
        bool: True if successful, False if database is unavailable
    """
    if not PYMYSQL_AVAILABLE:
        logger.warning("PyMySQL not available, skipping MySQL initialization")
        return False

    try:
        # Create connection without database (to create it)
        conn = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset=MYSQL_CHARSET,
            cursorclass=DictCursor
        )

        cursor = conn.cursor()

        # Create database if not exists
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DATABASE} "
                      f"CHARACTER SET {MYSQL_CHARSET} "
                      f"COLLATE {MYSQL_COLLATION}")
        logger.info(f"Database '{MYSQL_DATABASE}' ready")

        # Use the database
        cursor.execute(f"USE {MYSQL_DATABASE}")

        # Create tables
        cursor.executescript(CREATE_TABLES_SQL)
        logger.info("Database tables created successfully")

        cursor.close()
        conn.close()

        return True

    except pymysql.Error as e:
        logger.error(f"MySQL initialization error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during MySQL initialization: {e}")
        return False


# ============================================
# 数据库连接池
# ============================================
_connection_pool = None

def get_connection_pool():
    """
    Get or create a connection pool.

    Returns:
        pymysql.connections.ConnectionPool or None if PyMySQL unavailable
    """
    global _connection_pool

    if _connection_pool is not None:
        return _connection_pool

    if not PYMYSQL_AVAILABLE:
        return None

    try:
        _connection_pool = pymysql.ConnectionPool(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset=MYSQL_CHARSET,
            cursorclass=DictCursor,
            pool_size=MYSQL_POOL_SIZE,
            max_overflow=MYSQL_POOL_MAX_OVERFLOW,
            autocommit=True
        )
        logger.info("Connection pool created successfully")
        return _connection_pool

    except pymysql.Error as e:
        logger.error(f"Failed to create connection pool: {e}")
        return None


@contextmanager
def get_db_cursor():
    """
    Context manager for database cursor.

    Yields:
        DictCursor or None if database unavailable
    """
    conn = None
    cursor = None

    try:
        # Try connection pool first
        pool = get_connection_pool()
        if pool is not None:
            conn = pool.get_connection()
            cursor = conn.cursor()
        else:
            # Fallback: direct connection for testing
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                charset=MYSQL_CHARSET,
                cursorclass=DictCursor
            )
            cursor = conn.cursor()

        yield cursor

    except pymysql.Error as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Unexpected error: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ============================================
# Definitions CRUD Operations
# ============================================
def insert_definition(verb: str, chinese_ndef: str, semantic_table: Dict[str, str],
                       example_sentence: Optional[str] = None,
                       model_version: str = "zhipu-glm-4") -> bool:
    """
    Insert or update a verb definition.

    Args:
        verb: The verb to define
        chinese_ndef: Chinese definition text
        semantic_table: Dictionary of semantic components (manner, direction, aspect, etc.)
        example_sentence: Example sentence
        model_version: Model version used for generation

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            semantic_json = json.dumps(semantic_table, ensure_ascii=False)

            # Insert or update (ON DUPLICATE KEY UPDATE)
            cursor.execute("""
                INSERT INTO definitions (verb, chinese_ndef, semantic_table, example_sentence, model_version)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    chinese_ndef = VALUES(chinese_ndef),
                    semantic_table = VALUES(semantic_table),
                    example_sentence = VALUES(example_sentence),
                    model_version = VALUES(model_version),
                    updated_at = CURRENT_TIMESTAMP
            """, (verb, chinese_ndef, semantic_json, example_sentence, model_version))

            logger.info(f"Definition inserted/updated for verb: {verb}")
            return True

    except pymysql.Error as e:
        logger.error(f"Failed to insert definition for '{verb}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error inserting definition: {e}")
        return False


def get_definition_by_verb(verb: str) -> Optional[Dict[str, Any]]:
    """
    Get definition by verb name.

    Args:
        verb: The verb to look up

    Returns:
        Dictionary containing definition data or None if not found
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM definitions
                WHERE verb = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (verb,))

            row = cursor.fetchone()
            if row:
                # Parse JSON semantic table
                semantic_table = json.loads(row['semantic_table']) if isinstance(row['semantic_table'], str) else row['semantic_table']
                return {
                    'verb': row['verb'],
                    'chinese_ndef': row['chinese_ndef'],
                    'semantic_table': semantic_table,
                    'example_sentence': row['example_sentence'],
                    'model_version': row['model_version'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            return None

    except pymysql.Error as e:
        logger.error(f"Failed to get definition for '{verb}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting definition: {e}")
        return None


def get_all_definitions(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get all definitions from the database.

    Args:
        limit: Maximum number of definitions to return

    Returns:
        List of definition dictionaries
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM definitions
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                semantic_table = json.loads(row['semantic_table']) if isinstance(row['semantic_table'], str) else row['semantic_table']
                results.append({
                    'verb': row['verb'],
                    'chinese_ndef': row['chinese_ndef'],
                    'semantic_table': semantic_table,
                    'example_sentence': row['example_sentence'],
                    'model_version': row['model_version'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                })
            return results

    except pymysql.Error as e:
        logger.error(f"Failed to get all definitions: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting all definitions: {e}")
        return []


# ============================================
# Synonyms CRUD Operations
# ============================================
def insert_synonym(original_verb: str, synonym_verb: str) -> bool:
    """
    Insert a synonym relationship.

    Args:
        original_verb: The original verb
        synonym_verb: The synonym verb

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            # Get original verb ID
            cursor.execute("SELECT id FROM definitions WHERE verb = %s", (original_verb,))
            original_row = cursor.fetchone()

            if not original_row:
                logger.warning(f"Original verb not found: {original_verb}")
                return False

            # Check if synonym exists
            cursor.execute(
                "SELECT id FROM synonyms WHERE original_verb_id = %s AND synonym_verb = %s",
                (original_row['id'], synonym_verb)
            )

            if cursor.fetchone():
                logger.info(f"Synonym relationship already exists: {original_verb} -> {synonym_verb}")
                return True

            # Insert synonym
            cursor.execute(
                "INSERT INTO synonyms (original_verb_id, synonym_verb) VALUES (%s, %s)",
                (original_row['id'], synonym_verb)
            )

            logger.info(f"Synonym inserted: {original_verb} -> {synonym_verb}")
            return True

    except pymysql.Error as e:
        logger.error(f"Failed to insert synonym: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error inserting synonym: {e}")
        return False


def get_synonyms(verb: str) -> List[str]:
    """
    Get synonyms for a verb.

    Args:
        verb: The original verb

    Returns:
        List of synonym verbs
    """
    try:
        with get_db_cursor() as cursor:
            # Get original verb ID
            cursor.execute("SELECT id FROM definitions WHERE verb = %s", (verb,))
            original_row = cursor.fetchone()

            if not original_row:
                return []

            # Get synonyms
            cursor.execute(
                "SELECT synonym_verb FROM synonyms WHERE original_verb_id = %s",
                (original_row['id'],)
            )

            rows = cursor.fetchall()
            return [row['synonym_verb'] for row in rows]

    except pymysql.Error as e:
        logger.error(f"Failed to get synonyms for '{verb}': {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting synonyms: {e}")
        return []


# ============================================
# Feedbacks CRUD Operations
# ============================================
def insert_feedback(verb: str, rating: int, feedback_text: Optional[str] = None) -> bool:
    """
    Insert user feedback.

    Args:
        verb: The verb that was queried
        rating: User rating (1-5)
        feedback_text: Optional feedback text

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO feedbacks (verb, rating, feedback_text) VALUES (%s, %s, %s)",
                (verb, rating, feedback_text)
            )

            logger.info(f"Feedback inserted for '{verb}': rating={rating}")
            return True

    except pymysql.Error as e:
        logger.error(f"Failed to insert feedback for '{verb}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error inserting feedback: {e}")
        return False


def get_feedback_by_verb(verb: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get feedback for a specific verb.

    Args:
        verb: The verb to get feedback for
        limit: Maximum number of feedback entries to return

    Returns:
        List of feedback dictionaries
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM feedbacks WHERE verb = %s ORDER BY created_at DESC LIMIT %s",
                (verb, limit)
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    except pymysql.Error as e:
        logger.error(f"Failed to get feedback for '{verb}': {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting feedback: {e}")
        return []


def get_feedback_data() -> List[Dict[str, Any]]:
    """
    Get all feedback data.

    Returns:
        List of all feedback dictionaries
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM feedbacks ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    except pymysql.Error as e:
        logger.error(f"Failed to get feedback data: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting feedback data: {e}")
        return []


# ============================================
# Statistics Operations
# ============================================
def get_stats() -> Dict[str, Any]:
    """
    Get database statistics.

    Returns:
        Dictionary containing statistics
    """
    try:
        with get_db_cursor() as cursor:
            # Total queries (from definitions table)
            cursor.execute("SELECT COUNT(*) AS total_queries FROM definitions")
            total_queries = cursor.fetchone()['total_queries'] or 0

            # Average rating
            cursor.execute("SELECT COALESCE(AVG(rating), 0) AS avg_rating FROM feedbacks")
            avg_rating = round(float(cursor.fetchone()['avg_rating']), 1)

            # Total feedbacks
            cursor.execute("SELECT COUNT(*) AS total_feedbacks FROM feedbacks")
            total_feedbacks = cursor.fetchone()['total_feedbacks'] or 0

            # Total synonyms
            cursor.execute("SELECT COUNT(*) AS total_synonyms FROM synonyms")
            total_synonyms = cursor.fetchone()['total_synonyms'] or 0

            return {
                "total_queries": total_queries,
                "avg_rating": avg_rating,
                "total_feedbacks": total_feedbacks,
                "total_synonyms": total_synonyms,
            }

    except pymysql.Error as e:
        logger.error(f"Failed to get statistics: {e}")
        return {
            "total_queries": 0,
            "avg_rating": 0.0,
            "total_feedbacks": 0,
            "total_synonyms": 0,
        }
    except Exception as e:
        logger.error(f"Unexpected error getting statistics: {e}")
        return {
            "total_queries": 0,
            "avg_rating": 0.0,
            "total_feedbacks": 0,
            "total_synonyms": 0,
        }


def get_hot_verbs(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get hot verbs based on query frequency.

    Args:
        limit: Maximum number of verbs to return

    Returns:
        List of hot verb dictionaries with count and average rating
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT d.verb, COUNT(d.id) AS count,
                       COALESCE(AVG(f.rating), 0) AS avg_rating
                FROM definitions d
                LEFT JOIN feedbacks f ON d.verb = f.verb
                GROUP BY d.verb
                ORDER BY count DESC
                LIMIT %s
            """, (limit,))

            rows = cursor.fetchall()
            return [
                {
                    'verb': row['verb'],
                    'count': int(row['count']),
                    'avg_rating': round(float(row['avg_rating']), 1)
                }
                for row in rows
            ]

    except pymysql.Error as e:
        logger.error(f"Failed to get hot verbs: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting hot verbs: {e}")
        return []


def log_usage(verb: str, device_info: Optional[str] = None) -> bool:
    """
    Log a usage event.

    Args:
        verb: The verb that was queried
        device_info: Optional device information

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO usage_logs (verb, device_info) VALUES (%s, %s)",
                (verb, device_info)
            )
            return True
    except pymysql.Error as e:
        logger.error(f"Failed to log usage for '{verb}': {e}")
        return False


def clear_old_usage_logs(days: int = 30) -> int:
    """
    Clear usage logs older than specified days.

    Args:
        days: Number of days to keep logs

    Returns:
        Number of deleted rows
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "DELETE FROM usage_logs WHERE query_time < DATE_SUB(NOW(), INTERVAL %s DAY)",
                (days,)
            )
            deleted = cursor.rowcount
            logger.info(f"Cleared {deleted} old usage logs")
            return deleted
    except pymysql.Error as e:
        logger.error(f"Failed to clear old usage logs: {e}")
        return 0


# ============================================
# Data Migration from SQLite (Optional)
# ============================================
def migrate_from_sqlite(sqlite_db_path: str) -> Dict[str, int]:
    """
    Migrate data from SQLite database to MySQL.

    Args:
        sqlite_db_path: Path to SQLite database

    Returns:
        Dictionary with migration statistics
    """
    if not PYMYSQL_AVAILABLE:
        return {"error": "PyMySQL not available"}

    try:
        import sqlite3

        sqlite_conn = sqlite3.connect(sqlite_db_path)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()

        stats = {
            "queries_migrated": 0,
            "feedbacks_migrated": 0,
            "errors": 0
        }

        # Migrate queries
        sqlite_cursor.execute("SELECT * FROM queries")
        for row in sqlite_cursor.fetchall():
            try:
                semantic_table = json.loads(row['semantic_table']) if row['semantic_table'] else []

                insert_definition(
                    verb=row['verb'],
                    chinese_ndef=row['traditional_text'] or row['optimized_text'] or "",
                    semantic_table=semantic_table,
                    model_version=row.get('model_version', 'sqlite-migrated')
                )
                stats["queries_migrated"] += 1
            except Exception as e:
                logger.error(f"Failed to migrate query {row['id']}: {e}")
                stats["errors"] += 1

        # Migrate feedbacks
        sqlite_cursor.execute("SELECT * FROM feedbacks")
        for row in sqlite_cursor.fetchall():
            try:
                insert_feedback(
                    verb=row['verb'],
                    rating=row['rating'],
                    feedback_text=row.get('feedback_text')
                )
                stats["feedbacks_migrated"] += 1
            except Exception as e:
                logger.error(f"Failed to migrate feedback {row['id']}: {e}")
                stats["errors"] += 1

        sqlite_conn.close()

        logger.info(f"Migration complete: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return {"error": str(e)}
