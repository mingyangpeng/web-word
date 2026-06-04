#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
从 JSON 文件导入单词到数据库
"""
import sys
import os
import json

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import mysql.connector
from typing import Dict

DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'jhon',
    'password': 'p',
    'database': 'word_knowledge_db'
}

def load_existing_words() -> set:
    """加载已存在的单词"""
    conn = None
    existing_words = set()

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT word FROM words")
        results = cursor.fetchall()
        for row in results:
            existing_words.add(row['word'].lower())
    except Exception as e:
        print(f"读取数据库错误: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

    return existing_words

def determine_pos_and_difficulty(note: str, chinese: str) -> tuple:
    """根据注音和中文确定词性和难度"""
    pos = 'verb'  # 默认为动词

    # 从 note 提取信息
    note_lower = note.lower()

    # 判断难度
    difficulty = 'medium'
    if 'hard' in note_lower or '难' in chinese:
        difficulty = 'hard'
    elif 'easy' in note_lower or '易' in chinese:
        difficulty = 'easy'

    # 检查是否可能不是动词
    if '名' in note or '名词' in note_lower:
        pos = 'noun'
    elif '形' in note or '形容词' in note_lower:
        pos = 'adjective'

    return pos, difficulty

def import_from_json(json_path: str):
    """从 JSON 文件导入单词"""
    if not os.path.exists(json_path):
        print(f"错误: JSON 文件不存在: {json_path}")
        return

    # 读取 JSON 文件
    with open(json_path, 'r', encoding='utf-8') as f:
        words_data = json.load(f)

    print(f"从 {json_path} 读取了 {len(words_data)} 个单词条目")

    # 加载已存在的单词
    existing_words = load_existing_words()
    print(f"数据库中已存在 {len(existing_words)} 个单词")

    # 准备要添加的单词
    words_to_add = []
    skipped = 0

    for item in words_data:
        word = item.get('word', '').strip()
        if not word:
            continue

        if word.lower() in existing_words:
            skipped += 1
            continue

        # 提取详细信息
        chinese = item.get('chinese', '')
        category = item.get('category', '')
        subclass = item.get('subclass', '')
        formula = item.get('formula', '')
        meaning = item.get('meaning', '')
        note = item.get('note', '')

        # 确定词性和难度
        pos, difficulty = determine_pos_and_difficulty(note, chinese)

        # 构建定义
        definition_parts = []
        if chinese:
            definition_parts.append(chinese)
        if meaning:
            definition_parts.append(meaning)
        if category:
            definition_parts.append(f"[{category}]")
        if note:
            definition_parts.append(f"({note})")

        prepared_data = {
            'word': word,
            'pronunciation': None,
            'part_of_speech': pos,
            'definition': ' '.join(definition_parts),
            'example_sentence': None,
            'example_translation': None,
            'frequency': 0,
            'difficulty_level': difficulty
        }

        words_to_add.append(prepared_data)

    print(f"需要添加 {len(words_to_add)} 个新单词")
    print(f"跳过 {skipped} 个已存在的单词")

    # 批量添加
    if words_to_add:
        print("\n开始批量添加...")
        success_count = 0
        failed_count = 0

        conn = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor(dictionary=True)

            for i, word_data in enumerate(words_to_add):
                try:
                    query = """
                    INSERT INTO words (word, pronunciation, part_of_speech, definition,
                                      example_sentence, example_translation, frequency, difficulty_level)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    params = (
                        word_data['word'],
                        word_data['pronunciation'],
                        word_data['part_of_speech'],
                        word_data['definition'],
                        word_data['example_sentence'],
                        word_data['example_translation'],
                        word_data['frequency'],
                        word_data['difficulty_level']
                    )
                    cursor.execute(query, params)
                    conn.commit()
                    success_count += 1

                    if (i + 1) % 10 == 0:
                        print(f"已添加 {i + 1}/{len(words_to_add)} 个单词")

                except Exception as e:
                    print(f"添加单词失败: {word_data['word']}, 错误: {e}")
                    failed_count += 1
                    if conn:
                        conn.rollback()

        finally:
            if conn and conn.is_connected():
                conn.close()

        print(f"\n添加完成!")
        print(f"成功: {success_count}")
        print(f"失败: {failed_count}")
    else:
        print("没有需要添加的新单词")

    # 显示最终统计
    final_words = load_existing_words()
    print(f"\n最终统计: 数据库中共有 {len(final_words)} 个单词")

    # 按分类统计
    print("\n按分类统计单词:")
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT difficulty_level, COUNT(*) as count
            FROM words
            GROUP BY difficulty_level
            ORDER BY count DESC
        """)
        stats = cursor.fetchall()
        for stat in stats:
            print(f"  {stat['difficulty_level']:8s}: {stat['count']:3d} 个单词")

        # 显示所有单词
        cursor.execute("""
            SELECT id, word, part_of_speech, difficulty_level
            FROM words
            ORDER BY id
            LIMIT 50
        """)
        results = cursor.fetchall()

        print("\n所有单词列表:")
        for word in results:
            print(f"  [{word['id']:3d}] {word['word']:15s} ({word['part_of_speech']:8s}) - {word.get('difficulty_level', 'N/A')}")

        cursor.close()
    except Exception as e:
        print(f"读取数据失败: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == '__main__':
    print("=" * 80)
    print("JSON 文件导入工具")
    print("=" * 80)

    # 导入 movement_verbs.json
    json_path = os.path.join(project_root, 'data', 'movement_verbs.json')
    import_from_json(json_path)

    print("=" * 80)
