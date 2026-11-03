"""
MySQL 数据库操作封装

支持单词管理、关系网络、用户学习记录等操作。
所有 SQL 操作通过 :class:`DatabaseManager` 统一执行；
建议使用 :func:`get_db_manager` 获取单例。
"""

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import mysql.connector
from mysql.connector import Error, pooling

from config.constants import (
    DB_POOL_SIZE,
    MASTERY_THRESHOLD,
    RELATION_COLOR_MAP,
    DEFAULT_NODE_COLOR,
    NODE_SIZE_DEFAULT,
    NODE_SIZE_LARGE,
    NODE_SIZE_FREQUENCY_THRESHOLD,
)
from config.env import load_dotenv
from config.logging_config import get_logger

logger = get_logger(__name__)


# ========== 数据库配置 ==========

def get_db_config() -> Dict[str, Any]:
    """
    从环境变量构建数据库连接配置。

    首次调用时自动加载项目根目录的 .env 文件（不覆盖已存在的环境变量），
    确保 nohup / systemd 等无 shell 环境的启动方式也能读取配置。

    环境变量：
        DB_HOST (默认 localhost)
        DB_PORT (默认 3306)
        DB_USER (默认 root)
        DB_PASSWORD (默认空)
        DB_NAME (默认 word_knowledge_db)
        DB_CHARSET (默认 utf8mb4)
    """
    load_dotenv()
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "word_knowledge_db"),
        "charset": os.environ.get("DB_CHARSET", "utf8mb4"),
    }


# ========== 连接池 ==========

class _ConnectionPool:
    """MySQL 连接池封装（懒加载，单例）"""

    def __init__(self) -> None:
        self._pool: Optional[pooling.MySQLConnectionPool] = None

    def get_pool(self) -> pooling.MySQLConnectionPool:
        if self._pool is None:
            config = get_db_config()
            # pooling.MySQLConnectionPool 的 pool_size 上限为配置项
            self._pool = pooling.MySQLConnectionPool(
                pool_name="word_pool",
                pool_size=DB_POOL_SIZE,
                **config,
            )
            logger.info("数据库连接池已创建（size=%d，host=%s）",
                        DB_POOL_SIZE, config["host"])
        return self._pool

    def get_connection(self) -> mysql.connector.MySQLConnection:
        return self.get_pool().get_connection()


_pool_singleton = _ConnectionPool()


# ========== 数据库管理器 ==========

class DatabaseManager:
    """数据库管理类"""

    def __init__(self, db_config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化数据库管理器。

        Args:
            db_config: 显式连接配置；为 None 时使用连接池。
                       显式配置用于测试场景，绕过连接池。
        """
        # 显式配置：保留为兼容旧代码与单元测试
        self._explicit_config: Optional[Dict[str, Any]] = db_config
        self._explicit_connection: Optional[mysql.connector.MySQLConnection] = None

    # ---------- 连接管理 ----------

    def get_connection(self) -> mysql.connector.MySQLConnection:
        """获取数据库连接：优先复用显式连接，否则从连接池获取。"""
        if self._explicit_config is not None:
            if self._explicit_connection is None or not self._explicit_connection.is_connected():
                self._explicit_connection = mysql.connector.connect(**self._explicit_config)
            return self._explicit_connection
        return _pool_singleton.get_connection()

    def close_connection(self) -> None:
        """关闭显式持有的连接（连接池管理的连接由 with 上下文自动归还）。"""
        if self._explicit_connection and self._explicit_connection.is_connected():
            self._explicit_connection.close()
            self._explicit_connection = None

    # ---------- 通用执行 ----------

    def execute_query(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        fetch: bool = False,
    ) -> Any:
        """
        执行一条 SQL 语句。

        Args:
            query: SQL 语句，使用 %s 占位符
            params: 参数元组
            fetch: True 则返回 SELECT 结果（list[dict]），False 返回受影响行数

        Returns:
            查询结果列表或受影响行数
        """
        conn = self.get_connection()
        cursor = None
        try:
            # 使用连接池时，连接以 with 形式借出，需在 finally 显式归还
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params or ())

            if fetch:
                result = cursor.fetchall()
            else:
                result = cursor.rowcount
            conn.commit()
            return result
        except Error:
            conn.rollback()
            logger.exception("SQL 执行失败: %s | params=%s", query, params)
            raise
        finally:
            if cursor is not None:
                cursor.close()
            # 仅归还连接池的连接；显式连接复用
            if self._explicit_config is None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    logger.debug("归还连接到池失败", exc_info=True)

    def execute_many(
        self,
        query: str,
        seq_of_params: Iterable[Sequence[Any]],
    ) -> int:
        """
        批量执行 SQL（适用于 INSERT/UPDATE 批量操作）。

        Returns:
            受影响行数
        """
        conn = self.get_connection()
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.executemany(query, list(seq_of_params))
            conn.commit()
            return cursor.rowcount
        except Error:
            conn.rollback()
            logger.exception("批量 SQL 执行失败: %s", query)
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if self._explicit_config is None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    logger.debug("归还连接到池失败", exc_info=True)

    # ========== 单词相关操作 ==========

    def add_word(
        self,
        word: str,
        pronunciation: Optional[str] = None,
        part_of_speech: Optional[str] = None,
        definition: Optional[str] = None,
        example_sentence: Optional[str] = None,
        example_translation: Optional[str] = None,
        frequency: int = 0,
        difficulty_level: str = "medium",
    ) -> int:
        """添加单词，返回受影响行数（用于批量场景判断是否成功）"""
        query = """
        INSERT INTO words (word, pronunciation, part_of_speech, definition,
                          example_sentence, example_translation, frequency, difficulty_level)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            word, pronunciation, part_of_speech, definition,
            example_sentence, example_translation, frequency, difficulty_level,
        )
        return self.execute_query(query, params)

    def get_word(
        self,
        word_id: Optional[int] = None,
        word: Optional[str] = None,
    ) -> Optional[Dict]:
        """按 ID 或单词名称获取单词信息。"""
        if word_id:
            query = "SELECT * FROM words WHERE id = %s"
            result = self.execute_query(query, (word_id,), fetch=True)
        elif word:
            query = "SELECT * FROM words WHERE word = %s"
            result = self.execute_query(query, (word,), fetch=True)
        else:
            return None
        return result[0] if result else None

    def get_all_words(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取所有单词（按 ID 倒序）"""
        query = """
        SELECT id, word, pronunciation, part_of_speech, definition,
               example_sentence, example_translation, frequency, difficulty_level
        FROM words
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """
        return self.execute_query(query, (limit, offset), fetch=True)

    def search_words(self, keyword: str, limit: int = 50) -> List[Dict]:
        """搜索单词（匹配 word / definition / part_of_speech）

        注：使用 COLLATE utf8mb4_bin 进行子串匹配，避免 MySQL 8.0 默认
        排序规则（utf8mb4_0900_ai_ci）下 'happiness' LIKE '%happy%' = 0
        的 UCA 权重 bug。
        """
        query = """
        SELECT id, word, pronunciation, part_of_speech, definition,
               example_sentence, example_translation, frequency, difficulty_level
        FROM words
        WHERE word LIKE %s COLLATE utf8mb4_bin
           OR definition LIKE %s COLLATE utf8mb4_bin
           OR part_of_speech LIKE %s COLLATE utf8mb4_bin
        ORDER BY frequency DESC
        LIMIT %s
        """
        kw = f"%{keyword}%"
        params = (kw, kw, kw, limit)
        return self.execute_query(query, params, fetch=True)

    def update_word(self, word_id: int, **kwargs) -> bool:
        """更新单词字段"""
        if not kwargs:
            return False
        set_clause = ", ".join([f"{k} = %s" for k in kwargs.keys()])
        params = list(kwargs.values()) + [word_id]
        query = f"UPDATE words SET {set_clause} WHERE id = %s"
        self.execute_query(query, params)
        return True

    def delete_word(self, word_id: int) -> bool:
        """删除单词"""
        self.execute_query("DELETE FROM words WHERE id = %s", (word_id,))
        return True

    # ========== 关系网络相关操作 ==========

    def add_relation(
        self,
        word_id: int,
        related_word_id: int,
        relation_type: str,
        relation_strength: float = 1.0,
    ) -> int:
        """添加单词关系"""
        query = """
        INSERT INTO word_relations (word_id, related_word_id, relation_type, relation_strength)
        VALUES (%s, %s, %s, %s)
        """
        return self.execute_query(
            query, (word_id, related_word_id, relation_type, relation_strength)
        )

    def get_word_relations(
        self,
        word_id: int,
        relation_type: Optional[str] = None,
    ) -> List[Dict]:
        """获取单词的关系列表"""
        if relation_type:
            query = """
            SELECT r.*, w.word AS related_word
            FROM word_relations r
            JOIN words w ON r.related_word_id = w.id
            WHERE r.word_id = %s AND r.relation_type = %s
            """
            return self.execute_query(query, (word_id, relation_type), fetch=True)

        query = """
        SELECT r.*, w.word AS related_word
        FROM word_relations r
        JOIN words w ON r.related_word_id = w.id
        WHERE r.word_id = %s
        """
        return self.execute_query(query, (word_id,), fetch=True)

    def get_relations_for_word_ids(
        self,
        word_ids: Sequence[int],
        relation_type: Optional[str] = None,
    ) -> Dict[int, List[Dict]]:
        """
        批量获取多个单词的关系（解决 N+1 查询问题）。

        Args:
            word_ids: 单词 ID 列表
            relation_type: 可选关系类型过滤

        Returns:
            {word_id: [relation_dict, ...]}
        """
        if not word_ids:
            return {}

        placeholders = ",".join(["%s"] * len(word_ids))
        params: Tuple[Any, ...] = tuple(word_ids)

        if relation_type:
            query = f"""
            SELECT r.*, w.word AS related_word
            FROM word_relations r
            JOIN words w ON r.related_word_id = w.id
            WHERE r.word_id IN ({placeholders}) AND r.relation_type = %s
            """
            params = tuple(word_ids) + (relation_type,)
        else:
            query = f"""
            SELECT r.*, w.word AS related_word
            FROM word_relations r
            JOIN words w ON r.related_word_id = w.id
            WHERE r.word_id IN ({placeholders})
            """

        rows = self.execute_query(query, params, fetch=True)
        grouped: Dict[int, List[Dict]] = {wid: [] for wid in word_ids}
        for row in rows:
            wid = row.get("word_id")
            if wid is not None:
                grouped.setdefault(wid, []).append(row)
        return grouped

    def get_relation_type_stats(self) -> Dict[str, int]:
        """
        一次性聚合查询所有关系类型计数（解决 settings.py 的 N+1 问题）。

        Returns:
            {relation_type: count}
        """
        query = """
        SELECT relation_type, COUNT(*) AS cnt
        FROM word_relations
        GROUP BY relation_type
        """
        rows = self.execute_query(query, fetch=True)
        return {row["relation_type"]: int(row["cnt"]) for row in rows if row.get("relation_type")}

    def get_full_graph(self) -> Dict:
        """
        获取完整知识图谱数据（nodes + edges）。

        使用 :meth:`execute_query` 一次性获取所有关系，
        避免 N+1 查询。

        Returns:
            {'nodes': [...], 'edges': [...]}
        """
        words = self.get_all_words()
        if not words:
            return {"nodes": [], "edges": []}

        word_ids = [w["id"] for w in words]
        relations_grouped = self.get_relations_for_word_ids(word_ids)

        # 构建节点：默认颜色，根据 frequency 调整大小
        nodes = []
        for w in words:
            freq = w.get("frequency", 0) or 0
            nodes.append({
                "id": w["id"],
                "word": w["word"],
                "label": w["word"],
                "size": NODE_SIZE_LARGE if freq > NODE_SIZE_FREQUENCY_THRESHOLD else NODE_SIZE_DEFAULT,
                "color": DEFAULT_NODE_COLOR,
            })

        # 索引：节点 id -> 节点 dict（用于 O(1) 颜色更新）
        node_index = {n["id"]: n for n in nodes}

        # 构建边，同时更新相关节点颜色
        # 关系类型优先级：当节点涉及多种关系时，使用最高优先级的颜色
        relation_priority = {
            "antonym": 5,    # 反义（最具区分性）
            "synonym": 4,
            "homophone": 3,
            "family": 2,
            "related": 1,    # 相关（最弱，最后被覆盖）
        }

        def _assign_color(node: Dict, rel_type: str) -> None:
            """仅在更高优先级时覆盖节点颜色"""
            current = node.get("color")
            current_pri = relation_priority.get(
                _relation_type_from_color(current), 0
            )
            new_pri = relation_priority.get(rel_type, 0)
            if new_pri >= current_pri:
                node["color"] = RELATION_COLOR_MAP.get(rel_type, DEFAULT_NODE_COLOR)

        def _relation_type_from_color(color: str) -> str:
            for rt, c in RELATION_COLOR_MAP.items():
                if c == color:
                    return rt
            return ""

        edges = []
        seen_edge_keys = set()  # 去重 (source, target, relation)

        for source_id, rels in relations_grouped.items():
            for rel in rels:
                target_id = rel["related_word_id"]
                rel_type = rel["relation_type"]

                if source_id in node_index:
                    _assign_color(node_index[source_id], rel_type)
                if target_id in node_index:
                    _assign_color(node_index[target_id], rel_type)

                key = (source_id, target_id, rel_type)
                if key in seen_edge_keys:
                    continue
                seen_edge_keys.add(key)

                edges.append({
                    "source": source_id,
                    "target": target_id,
                    "relation": rel_type,
                    "strength": rel.get("relation_strength", 1.0),
                })

        return {"nodes": nodes, "edges": edges}

    # ========== 用户学习记录操作 ==========

    def add_user_learning_record(
        self,
        user_id: str,
        word_id: int,
        study_count: int = 1,
        proficiency_level: int = 0,
    ) -> None:
        """添加或更新用户学习记录（UPSERT）"""
        existing = self.execute_query(
            "SELECT 1 FROM user_learning WHERE user_id = %s AND word_id = %s",
            (user_id, word_id),
            fetch=True,
        )
        if existing:
            query = """
            UPDATE user_learning
            SET study_count = study_count + %s,
                proficiency_level = %s,
                last_studied_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND word_id = %s
            """
            self.execute_query(
                query, (study_count, proficiency_level, user_id, word_id)
            )
        else:
            query = """
            INSERT INTO user_learning (user_id, word_id, study_count, proficiency_level)
            VALUES (%s, %s, %s, %s)
            """
            self.execute_query(
                query, (user_id, word_id, study_count, proficiency_level)
            )

    def get_user_study_progress(self, user_id: str) -> List[Dict]:
        """获取用户学习进度"""
        query = """
        SELECT ul.*, w.word, w.definition, w.part_of_speech
        FROM user_learning ul
        JOIN words w ON ul.word_id = w.id
        WHERE ul.user_id = %s
        ORDER BY ul.last_studied_at DESC
        """
        return self.execute_query(query, (user_id,), fetch=True)

    def get_user_mastered_words(self, user_id: str) -> List[Dict]:
        """获取用户已掌握的单词（proficiency_level >= MASTERY_THRESHOLD）"""
        query = f"""
        SELECT ul.*, w.word, w.definition, w.part_of_speech
        FROM user_learning ul
        JOIN words w ON ul.word_id = w.id
        WHERE ul.user_id = %s AND ul.proficiency_level >= %s
        ORDER BY ul.last_studied_at DESC
        """
        return self.execute_query(
            query, (user_id, MASTERY_THRESHOLD), fetch=True
        )

    # ========== 对话历史操作 ==========

    def add_chat_message(self, user_id: str, role: str, content: str) -> int:
        """添加对话消息"""
        query = """
        INSERT INTO chat_history (user_id, role, content)
        VALUES (%s, %s, %s)
        """
        return self.execute_query(query, (user_id, role, content))

    def get_chat_history(self, user_id: str, limit: int = 100) -> List[Dict]:
        """获取用户对话历史（按时间倒序）"""
        query = """
        SELECT * FROM chat_history
        WHERE user_id = %s
        ORDER BY timestamp DESC
        LIMIT %s
        """
        return self.execute_query(query, (user_id, limit), fetch=True)

    def clear_chat_history(self, user_id: str) -> None:
        """清除用户对话历史"""
        self.execute_query("DELETE FROM chat_history WHERE user_id = %s", (user_id,))

    # ========== 系统配置操作 ==========

    def get_config(self, key: str) -> Optional[str]:
        """获取配置值"""
        result = self.execute_query(
            "SELECT config_value FROM system_config WHERE config_key = %s",
            (key,),
            fetch=True,
        )
        return result[0]["config_value"] if result else None

    def set_config(self, key: str, value: str, description: Optional[str] = None) -> None:
        """设置配置值（UPSERT）"""
        query = """
        INSERT INTO system_config (config_key, config_value, description)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            config_value = VALUES(config_value),
            description = VALUES(description),
            updated_at = CURRENT_TIMESTAMP
        """
        self.execute_query(query, (key, value, description))

    # ========== 学习统计操作 ==========

    def get_user_stats(self, user_id: str) -> Dict:
        """获取用户学习统计（不存在则自动创建空记录）"""
        existing = self.execute_query(
            "SELECT * FROM learning_stats WHERE user_id = %s",
            (user_id,),
            fetch=True,
        )
        if not existing:
            self.execute_query(
                """
                INSERT INTO learning_stats (user_id, total_words, mastered_words, learning_words)
                VALUES (%s, 0, 0, 0)
                """,
                (user_id,),
            )
            return {"total_words": 0, "mastered_words": 0, "learning_words": 0}
        return existing[0]

    def update_user_stats(self, user_id: str) -> None:
        """根据 user_learning 表实时刷新 learning_stats"""
        records = self.get_user_study_progress(user_id)
        total = len(records)
        mastered = sum(1 for r in records if (r.get("proficiency_level") or 0) >= MASTERY_THRESHOLD)
        learning = total - mastered

        self.execute_query(
            """
            UPDATE learning_stats
            SET total_words = %s,
                mastered_words = %s,
                learning_words = %s,
                last_active_date = CURRENT_TIMESTAMP
            WHERE user_id = %s
            """,
            (total, mastered, learning, user_id),
        )

    # ========== 批量操作 ==========

    def batch_add_words(self, words_data: Iterable[Dict]) -> int:
        """批量添加单词（遇到唯一键冲突跳过），返回成功条数"""
        count = 0
        for word_data in words_data:
            try:
                self.add_word(**word_data)
                count += 1
            except Error as e:
                # 1062: Duplicate entry
                if e.errno == 1062:
                    logger.debug("单词已存在，跳过: %s", word_data.get("word"))
                else:
                    logger.warning("添加单词失败 %s: %s", word_data.get("word"), e)
        return count

    def batch_add_relations(self, relations_data: Iterable[Dict]) -> int:
        """批量添加关系（遇到唯一键冲突跳过），返回成功条数"""
        count = 0
        for rel_data in relations_data:
            try:
                self.add_relation(**rel_data)
                count += 1
            except Error as e:
                if e.errno != 1062:
                    logger.warning("添加关系失败 %s: %s", rel_data, e)
        return count


# ========== 全局单例 ==========

_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """获取全局数据库管理实例（懒加载）"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
