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

# Try to import PyMySQL, provide fallback to SQLite
try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logging.warning("PyMySQL not available. Install with: pip install pymysql")

# Try to import PyYAML for config loading
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logging.warning("PyYAML not available. Install with: pip install pyyaml")

# Load configuration from config.yaml
def load_config():
    """从 config.yaml 加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config
        except Exception as e:
            logger.error(f"Failed to load config.yaml: {e}")
    else:
        logger.warning(f"Config file not found: {config_path}")
    return None

def get_config():
    """获取全局配置对象"""
    global _config
    if _config is None:
        _config = load_config()
    return _config

def get_mysql_config():
    """获取 MySQL 配置"""
    config = get_config()
    if config and 'database' in config and 'mysql' in config['database']:
        return config['database']['mysql']
    return None

def get_pool_config():
    """获取连接池配置"""
    config = get_config()
    if config and 'database' in config and 'pool' in config['database']:
        return config['database']['pool']
    return {'size': 5, 'max_overflow': 10}

_config = None  # 全局配置对象

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# 数据库配置
# ============================================
# 优先级：环境变量 > config/config.yaml > 内置默认值。
#
# 为什么环境变量优先：同一份 config.yaml 要能在两种环境下工作 ——
#   * Docker Compose：MySQL 主机名是 compose 服务名 "mysql"
#   * 本地开发：MySQL 主机名是 "127.0.0.1"
# 若 YAML 固定优先级最高，本地开发者必须改被 git 跟踪的配置才能启动。
# 环境变量优先让部署方无需改动仓库内的任何文件。
_mysql_config = get_mysql_config() or {}


def _setting(env_key: str, yaml_key: str, default: Any) -> Any:
    """读取一项数据库设置：环境变量优先，其次 YAML，最后默认值。"""
    env_value = os.getenv(env_key)
    if env_value is not None and env_value != "":
        return env_value
    if _mysql_config.get(yaml_key) not in (None, ""):
        return _mysql_config[yaml_key]
    return default


MYSQL_HOST = _setting("MYSQL_HOST", "host", "127.0.0.1")
MYSQL_PORT = int(_setting("MYSQL_PORT", "port", 3306))
MYSQL_DATABASE = _setting("MYSQL_DATABASE", "database", "web_word_db")
MYSQL_USER = _setting("MYSQL_USER", "user", "web_word_user")
MYSQL_PASSWORD = _setting("MYSQL_PASSWORD", "password", "")
MYSQL_CHARSET = _setting("MYSQL_CHARSET", "charset", "utf8mb4")
MYSQL_COLLATION = _setting("MYSQL_COLLATION", "collation", "utf8mb4_unicode_ci")


# Connection pool configuration
_pool_config = get_pool_config()
MYSQL_POOL_SIZE = _pool_config.get('size', 5)
MYSQL_POOL_MAX_OVERFLOW = _pool_config.get('max_overflow', 10)

# ============================================
# 建表 SQL
# ============================================
CREATE_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS definitions (
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    """CREATE TABLE IF NOT EXISTS synonyms (
        id INT AUTO_INCREMENT PRIMARY KEY,
        original_verb_id INT NOT NULL,
        synonym_verb VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (original_verb_id) REFERENCES definitions(id) ON DELETE CASCADE,
        INDEX idx_synonyms_original (original_verb_id),
        INDEX idx_synonyms_synonym (synonym_verb(50))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    """CREATE TABLE IF NOT EXISTS feedbacks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        rating INT NOT NULL CHECK(rating BETWEEN 1 AND 5),
        feedback_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_feedbacks_verb (verb(50)),
        INDEX idx_feedbacks_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    """CREATE TABLE IF NOT EXISTS usage_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        device_info VARCHAR(255),
        INDEX idx_usage_logs_verb (verb(50)),
        INDEX idx_usage_logs_query_time (query_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    """CREATE TABLE IF NOT EXISTS statistics (
        id INT AUTO_INCREMENT PRIMARY KEY,
        stat_name VARCHAR(50) NOT NULL UNIQUE,
        stat_value TEXT NOT NULL,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_statistics_name (stat_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
]

# ============================================
# 初始化数据库
# ============================================
def init_database(max_retries: int = 3, retry_delay: float = 2.0) -> bool:
    """
    Initialize MySQL database and create tables.

    Includes retry logic for Docker environments where MySQL may not be ready yet.

    Args:
        max_retries: Maximum number of connection attempts (default 3)
        retry_delay: Seconds to wait between retries (default 2.0)

    Returns:
        bool: True if successful, False if database is unavailable
    """
    import time

    if not PYMYSQL_AVAILABLE:
        logger.warning("PyMySQL not available, skipping MySQL initialization")
        return False

    for attempt in range(1, max_retries + 1):
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
            for table_sql in CREATE_TABLES_SQL:
                cursor.execute(table_sql)
            logger.info("Database tables created successfully")

            cursor.close()
            conn.close()

            return True

        except pymysql.Error as e:
            logger.warning(f"MySQL init attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error(f"MySQL initialization failed after {max_retries} attempts")
                return False
        except Exception as e:
            logger.warning(f"Unexpected error on attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                logger.error(f"MySQL initialization failed after {max_retries} attempts")
                return False

    return False


# ============================================
# 数据库连接池
# ============================================
_connection_pool = None

def get_connection_pool():
    """
    Get or create a connection pool.

    Note: PyMySQL 1.1.0 does not support ConnectionPool,
    so we'll manage connections manually.
    """
    global _connection_pool

    if _connection_pool is not None:
        return _connection_pool

    if not PYMYSQL_AVAILABLE:
        return None

    try:
        _connection_pool = []
        logger.info("Connection pool created (manual management)")
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
            # Manual connection management
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                charset=MYSQL_CHARSET,
                cursorclass=DictCursor,
                autocommit=True
            )
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
                cursorclass=DictCursor,
                autocommit=True
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

    统计口径（2026-09 修正）：
      * total_queries  —— 真实查询次数，来自 usage_logs 表（每次用户搜索都会
        log_usage 记一笔）。修正前这里统计的是 definitions 表的行数，也就是
        「已收录词条数」，被当成「总查询次数」显示，属于口径错误。
      * total_definitions —— 已收录词条数，单独返回，不再冒充查询数。
      * queries_today —— 今天的查询次数，用于侧边栏的当日增量。

    Returns:
        Dictionary containing statistics
    """
    empty = {
        "total_queries": 0,
        "queries_today": 0,
        "total_definitions": 0,
        "avg_rating": 0.0,
        "total_feedbacks": 0,
        "total_synonyms": 0,
    }
    try:
        with get_db_cursor() as cursor:
            # 真实查询次数（来自查询日志）
            cursor.execute("SELECT COUNT(*) AS n FROM usage_logs")
            total_queries = int(cursor.fetchone()['n'] or 0)

            # 今日查询次数
            cursor.execute(
                "SELECT COUNT(*) AS n FROM usage_logs WHERE DATE(query_time) = CURDATE()"
            )
            queries_today = int(cursor.fetchone()['n'] or 0)

            # 已收录词条数（与查询次数分开，避免口径混淆）
            cursor.execute("SELECT COUNT(*) AS n FROM definitions")
            total_definitions = int(cursor.fetchone()['n'] or 0)

            # Average rating
            cursor.execute("SELECT COALESCE(AVG(rating), 0) AS avg_rating FROM feedbacks")
            avg_rating = round(float(cursor.fetchone()['avg_rating']), 1)

            # Total feedbacks
            cursor.execute("SELECT COUNT(*) AS n FROM feedbacks")
            total_feedbacks = int(cursor.fetchone()['n'] or 0)

            # Total synonyms
            cursor.execute("SELECT COUNT(*) AS n FROM synonyms")
            total_synonyms = int(cursor.fetchone()['n'] or 0)

            return {
                "total_queries": total_queries,
                "queries_today": queries_today,
                "total_definitions": total_definitions,
                "avg_rating": avg_rating,
                "total_feedbacks": total_feedbacks,
                "total_synonyms": total_synonyms,
            }

    except pymysql.Error as e:
        logger.error(f"Failed to get statistics: {e}")
        return empty
    except Exception as e:
        logger.error(f"Unexpected error getting statistics: {e}")
        return empty


def get_hot_verbs(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get hot verbs based on **real query frequency**.

    修正前这里按 definitions 表的行数排序（d.verb, COUNT(d.id)），definitions
    每个动词只有一行，所以「热度」恒等于 1，排序实际由 LIMIT 前的物理顺序决定，
    根本不是热门查询。现在以 usage_logs 的查询次数为准，并用待查词的原词形
    关联 definitions/feedbacks 取评分。

    Args:
        limit: Maximum number of verbs to return

    Returns:
        List of hot verb dictionaries with count and average rating
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT u.verb,
                       COUNT(*) AS count,
                       COALESCE((
                           SELECT AVG(f.rating) FROM feedbacks f WHERE f.verb = u.verb
                       ), 0) AS avg_rating
                FROM usage_logs u
                GROUP BY u.verb
                ORDER BY count DESC, u.verb ASC
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
