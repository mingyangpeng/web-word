#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
数据库测试脚本 - 测试所有数据库功能
"""

import sys
import os
import json

# 确保项目根目录在路径中
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from data.word_database import DatabaseManager, get_db_manager

print("=" * 60)
print("🧪 数据库功能测试")
print("=" * 60)

all_tests_passed = True

# 测试1: 创建数据库管理器实例
print("\n【测试1】创建数据库管理器实例...")
try:
    db = DatabaseManager()
    print("✅ 数据库管理器实例创建成功")
except Exception as e:
    print(f"❌ 创建失败: {str(e)}")
    all_tests_passed = False

# 测试2: 测试数据库连接
print("\n【测试2】测试数据库连接...")
try:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT VERSION()")
    version = cursor.fetchone()[0]
    print(f"✅ 数据库连接成功 (MySQL {version})")
    cursor.close()
except Exception as e:
    print(f"❌ 连接失败: {str(e)}")
    all_tests_passed = False
finally:
    db.close_connection()

# 测试3: 检查表是否存在
print("\n【测试3】检查数据库表...")
try:
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()

    tables = ["words", "word_relations", "chat_history", "user_learning", "learning_stats", "system_config"]
    table_exists = {}

    for table in tables:
        cursor.execute(f"SHOW TABLES LIKE '{table}'")
        result = cursor.fetchone()
        table_exists[table] = result is not None
        if table_exists[table]:
            print(f"✅ 表 {table} 存在")
        else:
            print(f"⚠️  表 {table} 不存在")

    cursor.close()
    db.close_connection()

    # 检查是否有至少一个表存在
    if not any(table_exists.values()):
        print("❌ 数据库中没有表，需要初始化")
        all_tests_passed = False
except Exception as e:
    print(f"❌ 检查表失败: {str(e)}")
    all_tests_passed = False

# 测试4: 如果表不存在，创建表
print("\n【测试4】表初始化...")
try:
    db = DatabaseManager()
    with open("config/init_database.sql", "r", encoding="utf-8") as f:
        sql_script = f.read()

    conn = db.get_connection()
    cursor = conn.cursor()

    # 分割并执行 SQL 语句
    statements = [s.strip() for s in sql_script.split(';') if s.strip() and not s.strip().startswith('--')]
    created_tables = []

    for stmt in statements:
        try:
            cursor.execute(stmt)
            created_tables.append(stmt[:50].replace('\n', ''))
        except Exception as e:
            # 忽略已经存在的错误
            if "already exists" not in str(e):
                pass

    conn.commit()
    cursor.close()
    db.close_connection()

    if created_tables:
        print(f"✅ 成功创建表: {len(created_tables)} 个")
    else:
        print("✅ 数据库表已存在，无需初始化")

except Exception as e:
    print(f"❌ 初始化失败: {str(e)}")
    all_tests_passed = False

# 测试5: 测试添加单词
print("\n【测试5】测试添加单词...")
try:
    db = DatabaseManager()
    test_word_id = db.add_word(
        word="testword",
        pronunciation="/ˈtɛstwɜːd/",
        part_of_speech="名词",
        definition="测试单词",
        example_sentence="This is a test word.",
        example_translation="这是一个测试单词。",
        frequency=5,
        difficulty_level="easy"
    )

    if test_word_id > 0:
        print(f"✅ 添加单词成功 (ID: {test_word_id})")

        # 验证添加
        test_word = db.get_word(word="testword")
        if test_word and test_word['word'] == "testword":
            print(f"✅ 验证成功: {test_word['word']} - {test_word['definition']}")
        else:
            print(f"❌ 验证失败: 无法获取添加的单词")
    else:
        print(f"❌ 添加单词失败 (返回 ID: {test_word_id})")

    db.close_connection()

except Exception as e:
    print(f"❌ 添加单词失败: {str(e)}")
    all_tests_passed = False

# 测试6: 测试搜索单词
print("\n【测试6】测试搜索单词...")
try:
    db = DatabaseManager()
    results = db.search_words("test")
    print(f"✅ 搜索单词成功，找到 {len(results)} 个结果")
    for r in results[:3]:
        print(f"   - {r['word']}: {r['definition']}")
    db.close_connection()

except Exception as e:
    print(f"❌ 搜索单词失败: {str(e)}")
    all_tests_passed = False

# 测试7: 测试更新单词
print("\n【测试7】测试更新单词...")
try:
    db = DatabaseManager()
    updated = db.update_word(1, definition="更新的测试单词")
    print(f"✅ 更新单词成功")

    # 验证更新
    word = db.get_word(word_id=1)
    if word and word['definition'] == "更新的测试单词":
        print(f"✅ 验证成功: 定义已更新")
    else:
        print(f"❌ 验证失败: 定义未正确更新")

    db.close_connection()

except Exception as e:
    print(f"❌ 更新单词失败: {str(e)}")
    all_tests_passed = False

# 测试8: 测试获取所有单词
print("\n【测试8】测试获取所有单词...")
try:
    db = DatabaseManager()
    words = db.get_all_words(limit=10)
    print(f"✅ 获取单词列表成功，共 {len(words)} 个单词")
    if words:
        print(f"   前3个: {[w['word'] for w in words[:3]]}")
    db.close_connection()

except Exception as e:
    print(f"❌ 获取单词列表失败: {str(e)}")
    all_tests_passed = False

# 测试9: 测试添加关系
print("\n【测试9】测试添加单词关系...")
try:
    db = DatabaseManager()

    # 获取测试单词 ID
    test_word = db.get_word(word="testword")
    if not test_word:
        print("⚠️  测试单词不存在，跳过关系测试")
    else:
        test_id = test_word['id']

        # 添加关系
        rel_id = db.add_relation(test_id, 1, "synonym", 1.0)
        if rel_id > 0:
            print(f"✅ 添加关系成功 (ID: {rel_id})")

            # 验证关系
            relations = db.get_word_relations(test_id)
            print(f"✅ 获取关系成功，找到 {len(relations)} 个关系")

            # 获取完整图谱
            graph = db.get_full_graph()
            print(f"✅ 获取完整图谱成功，节点 {len(graph['nodes'])} 个，边 {len(graph['edges'])} 条")

        db.close_connection()

except Exception as e:
    print(f"❌ 添加关系失败: {str(e)}")
    all_tests_passed = False

# 测试10: 测试用户学习记录
print("\n【测试10】测试用户学习记录...")
try:
    db = DatabaseManager()

    # 添加学习记录
    db.add_user_learning_record("user123", 1, study_count=5, proficiency_level=2)
    print(f"✅ 添加学习记录成功")

    # 获取学习进度
    progress = db.get_user_study_progress("user123")
    print(f"✅ 获取学习进度成功，共 {len(progress)} 条记录")

    # 获取已掌握单词
    mastered = db.get_user_mastered_words("user123")
    print(f"✅ 获取已掌握单词成功，共 {len(mastered)} 个")

    db.close_connection()

except Exception as e:
    print(f"❌ 学习记录测试失败: {str(e)}")
    all_tests_passed = False

# 测试11: 测试对话历史
print("\n【测试11】测试对话历史...")
try:
    db = DatabaseManager()

    # 添加消息
    msg_id = db.add_chat_message("user123", "user", "你好")
    print(f"✅ 添加消息成功 (ID: {msg_id})")

    # 获取历史
    history = db.get_chat_history("user123", limit=10)
    print(f"✅ 获取历史成功，共 {len(history)} 条记录")

    db.close_connection()

except Exception as e:
    print(f"❌ 对话历史测试失败: {str(e)}")
    all_tests_passed = False

# 测试12: 测试学习统计
print("\n【测试12】测试学习统计...")
try:
    db = DatabaseManager()

    # 更新统计
    stats = db.get_user_stats("user123")
    print(f"✅ 获取统计信息: {stats}")

    db.update_user_stats("user123")
    print(f"✅ 更新统计成功")

    db.close_connection()

except Exception as e:
    print(f"❌ 学习统计测试失败: {str(e)}")
    all_tests_passed = False

# 测试13: 测试配置管理
print("\n【测试13】测试配置管理...")
try:
    db = DatabaseManager()

    # 设置配置
    db.set_config("test_config", "test_value", "测试配置")
    print(f"✅ 设置配置成功")

    # 获取配置
    value = db.get_config("test_config")
    if value == "test_value":
        print(f"✅ 获取配置成功: {value}")
    else:
        print(f"❌ 配置验证失败: 期望 test_value，得到 {value}")

    # 清理
    db.set_config("test_config", "", None)
    db.close_connection()

except Exception as e:
    print(f"❌ 配置管理测试失败: {str(e)}")
    all_tests_passed = False

# 测试14: 测试批量操作
print("\n【测试14】测试批量操作...")
try:
    db = DatabaseManager()

    # 准备批量数据
    words_data = [
        {
            "word": "batch1",
            "pronunciation": "/ˈbætʃ1/",
            "part_of_speech": "形容词",
            "definition": "批量1",
            "example_sentence": "Batch 1",
            "example_translation": "批量1",
            "frequency": 1,
            "difficulty_level": "easy"
        },
        {
            "word": "batch2",
            "pronunciation": "/ˈbætʃ2/",
            "part_of_speech": "形容词",
            "definition": "批量2",
            "example_sentence": "Batch 2",
            "example_translation": "批量2",
            "frequency": 1,
            "difficulty_level": "easy"
        }
    ]

    count = db.batch_add_words(words_data)
    print(f"✅ 批量添加单词成功，添加 {count} 个")

    db.close_connection()

except Exception as e:
    print(f"❌ 批量操作测试失败: {str(e)}")
    all_tests_passed = False

# 总结
print("\n" + "=" * 60)
if all_tests_passed:
    print("🎉 所有数据库测试通过！")
else:
    print("⚠️ 部分测试失败，请检查上述错误")
print("=" * 60)
