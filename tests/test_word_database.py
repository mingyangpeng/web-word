"""
数据库管理器单元测试

需要可用的 MySQL 实例（使用 isolated_db fixture 自动创建临时 schema）。
若本机无 MySQL，整个模块会被跳过。

覆盖：
- 单词 CRUD
- 关系批量查询（N+1 修复）
- 知识图谱构建
- 用户学习记录 UPSERT
- 对话历史
- 系统配置 UPSERT
"""

from __future__ import annotations

import os

import pytest

# 检测是否可连 MySQL，否则跳过整个模块
mysql_available = True
try:
    import mysql.connector
    from data.word_database import get_db_config
    _cfg = get_db_config()
    _probe = mysql.connector.connect(
        host=_cfg["host"], port=_cfg["port"],
        user=_cfg["user"], password=_cfg["password"],
        connect_timeout=2,
    )
    _probe.close()
except Exception:
    mysql_available = False

pytestmark = pytest.mark.skipif(not mysql_available, reason="MySQL 不可用，跳过数据库测试")


# ========== 单词 CRUD ==========

class TestWordCRUD:

    def test_add_and_get_word(self, isolated_db):
        db = isolated_db
        db.add_word(
            word="happy",
            pronunciation="/ˈhæpi/",
            part_of_speech="adj",
            definition="feeling or showing pleasure",
            difficulty_level="easy",
        )

        result = db.get_word(word="happy")
        assert result is not None
        assert result["word"] == "happy"
        assert result["part_of_speech"] == "adj"
        assert result["difficulty_level"] == "easy"

    def test_get_word_by_id(self, isolated_db):
        db = isolated_db
        db.add_word(word="run", part_of_speech="verb")
        word = db.get_word(word="run")
        assert word is not None

        by_id = db.get_word(word_id=word["id"])
        assert by_id is not None
        assert by_id["word"] == "run"

    def test_get_nonexistent_word(self, isolated_db):
        assert isolated_db.get_word(word="nonexistent_xyz") is None
        assert isolated_db.get_word(word_id=999999) is None

    def test_get_word_with_no_args(self, isolated_db):
        assert isolated_db.get_word() is None

    def test_search_words(self, isolated_db):
        db = isolated_db
        db.add_word(word="happy", part_of_speech="adj", definition="pleased")
        db.add_word(word="happily", part_of_speech="adv", definition="in a happy way")
        db.add_word(word="sad", part_of_speech="adj", definition="not happy")

        results = db.search_words("happy")
        words = {r["word"] for r in results}
        # happy（word 匹配）、happily（word 前缀匹配，含 'happy' 子串）、
        # sad（definition 含 'happy'）都应命中
        assert "happy" in words
        assert "happily" in words
        assert "sad" in words

    def test_update_word(self, isolated_db):
        db = isolated_db
        db.add_word(word="run", part_of_speech="verb", frequency=5)
        word = db.get_word(word="run")
        db.update_word(word["id"], frequency=100, difficulty_level="medium")

        updated = db.get_word(word="run")
        assert updated["frequency"] == 100
        assert updated["difficulty_level"] == "medium"

    def test_update_word_no_fields(self, isolated_db):
        db = isolated_db
        db.add_word(word="jump")
        word = db.get_word(word="jump")
        assert db.update_word(word["id"]) is False

    def test_delete_word(self, isolated_db):
        db = isolated_db
        db.add_word(word="swim")
        word = db.get_word(word="swim")
        db.delete_word(word["id"])
        assert db.get_word(word="swim") is None

    def test_duplicate_word_raises(self, isolated_db):
        db = isolated_db
        db.add_word(word="unique_word")
        with pytest.raises(Exception):  # mysql.connector.errors.IntegrityError
            db.add_word(word="unique_word")

    def test_get_all_words_pagination(self, isolated_db):
        db = isolated_db
        for i in range(5):
            db.add_word(word=f"word_{i}")
        page1 = db.get_all_words(limit=2, offset=0)
        page2 = db.get_all_words(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        page1_ids = {w["id"] for w in page1}
        page2_ids = {w["id"] for w in page2}
        assert not (page1_ids & page2_ids)


# ========== 关系网络 ==========

class TestRelations:

    def _setup_pair(self, db):
        db.add_word(word="happy", part_of_speech="adj")
        db.add_word(word="glad", part_of_speech="adj")
        db.add_word(word="joyful", part_of_speech="adj")
        return db.get_word(word="happy")["id"], db.get_word(word="glad")["id"], db.get_word(word="joyful")["id"]

    def test_add_and_get_relation(self, isolated_db):
        db = isolated_db
        happy_id, glad_id, _ = self._setup_pair(db)
        db.add_relation(happy_id, glad_id, "synonym")

        rels = db.get_word_relations(happy_id)
        assert len(rels) == 1
        assert rels[0]["related_word"] == "glad"
        assert rels[0]["relation_type"] == "synonym"

    def test_get_relations_filtered_by_type(self, isolated_db):
        db = isolated_db
        happy_id, glad_id, joyful_id = self._setup_pair(db)
        db.add_relation(happy_id, glad_id, "synonym")
        db.add_relation(happy_id, joyful_id, "related")

        syns = db.get_word_relations(happy_id, relation_type="synonym")
        assert len(syns) == 1
        assert syns[0]["related_word"] == "glad"

    def test_get_relations_for_word_ids_batch(self, isolated_db):
        """关键测试：批量查询替代 N+1"""
        db = isolated_db
        happy_id, glad_id, joyful_id = self._setup_pair(db)
        db.add_relation(happy_id, glad_id, "synonym")
        db.add_relation(happy_id, joyful_id, "related")
        db.add_relation(glad_id, joyful_id, "synonym")

        grouped = db.get_relations_for_word_ids([happy_id, glad_id, joyful_id])
        assert len(grouped[happy_id]) == 2
        assert len(grouped[glad_id]) == 1
        assert grouped[joyful_id] == []

    def test_get_relations_for_empty_ids(self, isolated_db):
        assert isolated_db.get_relations_for_word_ids([]) == {}

    def test_get_relation_type_stats(self, isolated_db):
        """关键测试：聚合统计替代 settings.py 的 N+1"""
        db = isolated_db
        happy_id, glad_id, joyful_id = self._setup_pair(db)
        db.add_relation(happy_id, glad_id, "synonym")
        db.add_relation(happy_id, joyful_id, "related")
        db.add_relation(glad_id, joyful_id, "synonym")

        stats = db.get_relation_type_stats()
        assert stats.get("synonym") == 2
        assert stats.get("related") == 1

    def test_get_full_graph(self, isolated_db):
        db = isolated_db
        happy_id, glad_id, joyful_id = self._setup_pair(db)
        db.add_relation(happy_id, glad_id, "synonym")
        db.add_relation(happy_id, joyful_id, "related")

        graph = db.get_full_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2

        # 节点颜色应被关系类型覆盖
        happy_node = next(n for n in graph["nodes"] if n["id"] == happy_id)
        assert happy_node["color"] == "#2ecc71"  # synonym green

    def test_get_full_graph_empty(self, isolated_db):
        graph = isolated_db.get_full_graph()
        assert graph == {"nodes": [], "edges": []}

    def test_duplicate_relation_silently_skipped_in_batch(self, isolated_db):
        db = isolated_db
        happy_id, glad_id, _ = self._setup_pair(db)
        db.add_relation(happy_id, glad_id, "synonym")
        # batch_add_relations 遇到 1062 应跳过
        count = db.batch_add_relations([
            {"word_id": happy_id, "related_word_id": glad_id, "relation_type": "synonym"},
        ])
        assert count == 0


# ========== 学习记录 ==========

class TestUserLearning:

    def test_create_and_update_record(self, isolated_db):
        db = isolated_db
        db.add_word(word="learn")
        word_id = db.get_word(word="learn")["id"]

        # 首次创建
        db.add_user_learning_record("user1", word_id, study_count=1, proficiency_level=1)
        # 再次更新（累加 study_count）
        db.add_user_learning_record("user1", word_id, study_count=1, proficiency_level=2)

        progress = db.get_user_study_progress("user1")
        assert len(progress) == 1
        assert progress[0]["study_count"] == 2
        assert progress[0]["proficiency_level"] == 2

    def test_mastered_filter(self, isolated_db):
        db = isolated_db
        db.add_word(word="easy")
        db.add_word(word="hard")
        easy_id = db.get_word(word="easy")["id"]
        hard_id = db.get_word(word="hard")["id"]

        db.add_user_learning_record("u1", easy_id, proficiency_level=4)
        db.add_user_learning_record("u1", hard_id, proficiency_level=1)

        mastered = db.get_user_mastered_words("u1")
        assert len(mastered) == 1
        assert mastered[0]["word"] == "easy"


# ========== 对话历史 ==========

class TestChatHistory:

    @staticmethod
    def _ensure_user(db, user_id: str) -> None:
        """user_learning.user_id 是 chat_history 的外键源，需先创建占位记录"""
        db.add_word(word=f"_placeholder_{user_id}")
        placeholder_id = db.get_word(word=f"_placeholder_{user_id}")["id"]
        db.add_user_learning_record(user_id, placeholder_id)

    def test_add_and_get_messages(self, isolated_db):
        db = isolated_db
        self._ensure_user(db, "user1")
        db.add_chat_message("user1", "user", "Hello")
        db.add_chat_message("user1", "assistant", "Hi there")

        history = db.get_chat_history("user1")
        assert len(history) == 2

    def test_clear_history(self, isolated_db):
        db = isolated_db
        self._ensure_user(db, "user1")
        db.add_chat_message("user1", "user", "msg")
        db.clear_chat_history("user1")
        assert len(db.get_chat_history("user1")) == 0


# ========== 系统配置 ==========

class TestSystemConfig:

    def test_set_and_get(self, isolated_db):
        db = isolated_db
        db.set_config("test_key", "test_value", "description")
        assert db.get_config("test_key") == "test_value"

    def test_get_nonexistent(self, isolated_db):
        assert isolated_db.get_config("nonexistent") is None

    def test_upsert(self, isolated_db):
        db = isolated_db
        db.set_config("key1", "v1")
        db.set_config("key1", "v2")
        assert db.get_config("key1") == "v2"


# ========== 学习统计 ==========

class TestLearningStats:

    def _ensure_user(self, db, user_id: str) -> None:
        """learning_stats.user_id 引用 user_learning.user_id，需先创建占位记录"""
        db.add_word(word=f"_placeholder_{user_id}")
        placeholder_id = db.get_word(word=f"_placeholder_{user_id}")["id"]
        db.add_user_learning_record(user_id, placeholder_id)

    def test_get_creates_default(self, isolated_db):
        db = isolated_db
        self._ensure_user(db, "new_user")
        stats = db.get_user_stats("new_user")
        assert stats["total_words"] == 0
        assert stats["mastered_words"] == 0

    def test_update_stats(self, isolated_db):
        db = isolated_db
        self._ensure_user(db, "u1")
        db.add_word(word="w1")
        db.add_word(word="w2")
        w1 = db.get_word(word="w1")["id"]
        w2 = db.get_word(word="w2")["id"]

        db.add_user_learning_record("u1", w1, proficiency_level=4)
        db.add_user_learning_record("u1", w2, proficiency_level=2)

        db.get_user_stats("u1")  # 触发初始化
        db.update_user_stats("u1")

        stats = db.get_user_stats("u1")
        # 占位词 + w1 + w2 共 3 个学习记录，其中 w1 掌握
        assert stats["total_words"] == 3
        assert stats["mastered_words"] == 1
        assert stats["learning_words"] == 2
