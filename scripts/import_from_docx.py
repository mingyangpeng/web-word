#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
从 Word 文档提取单词数据并导入数据库
"""
import json
import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from docx import Document
from typing import List, Dict

# 数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'jhon',
    'password': 'p',
    'database': 'word_knowledge_db'
}

def extract_words_from_docx(docx_path: str) -> List[Dict]:
    """
    从 Word 文档中提取单词数据

    Args:
        docx_path: Word 文档路径

    Returns:
        单词数据列表
    """
    if not os.path.exists(docx_path):
        print(f"错误: Word 文档不存在: {docx_path}")
        return []

    doc = Document(docx_path)
    words_data = []

    print(f"正在解析 Word 文档: {docx_path}")

    for row_idx, table in enumerate(doc.tables):
        for cell_idx, row in enumerate(table.rows):
            # 跳过表头
            if row_idx == 0:
                continue

            # 提取单元格数据
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) >= 2:
                word_data = {
                    'word': cells[0],
                    'chinese': cells[1] if len(cells) > 1 else '',
                    'category': cells[2] if len(cells) > 2 else '',
                    'subclass': cells[3] if len(cells) > 3 else '',
                    'formula': cells[4] if len(cells) > 4 else '',
                    'meaning': cells[5] if len(cells) > 5 else '',
                    'note': cells[6] if len(cells) > 6 else ''
                }
                if word_data['word']:
                    words_data.append(word_data)

    return words_data

def prepare_word_for_db(word_data: Dict) -> Dict:
    """
    将提取的单词数据转换为数据库所需的格式

    Args:
        word_data: 从文档提取的原始数据

    Returns:
        数据库格式数据
    """
    # 确定词性（从分类和公式推断）
    part_of_speech = 'verb'  # 默认为动词

    # 确定难度级别
    difficulty = 'medium'
    note = word_data.get('note', '')
    chinese = word_data.get('chinese', '')
    if '难' in note or 'hard' in note.lower():
        difficulty = 'hard'
    elif '易' in chinese or 'easy' in note.lower():
        difficulty = 'easy'

    return {
        'word': word_data['word'],
        'pronunciation': None,  # 可以从 GLM API 获取
        'part_of_speech': part_of_speech,
        'definition': chinese + ' ' + word_data.get('meaning', ''),
        'example_sentence': None,
        'example_translation': None,
        'frequency': 0,  # 需要从词频数据获取
        'difficulty_level': difficulty
    }

def load_existing_words() -> set:
    """加载已存在的单词"""
    import mysql.connector
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

def add_word_to_db(db_manager, word_data: Dict) -> bool:
    """添加单个单词到数据库"""
    try:
        word_id = db_manager.add_word(**word_data)
        return True
    except Exception as e:
        print(f"添加单词失败: {word_data['word']}, 错误: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("Word 文档单词导入工具")
    print("=" * 60)

    # 显示数据库配置
    print(f"数据库配置: {DB_CONFIG['database']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")

    # 检查数据库连接
    import mysql.connector
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        print("数据库连接成功!")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return

    # 关闭连接
    if conn and conn.is_connected():
        conn.close()

    # 提取 Word 文档
    docx_path = os.path.join(project_root, 'docs', '英语移动动词五大范畴分类总表.docx')
    words_data = extract_words_from_docx(docx_path)
    print(f"\n从文档中提取了 {len(words_data)} 个单词")

    # 加载已存在的单词
    existing_words = load_existing_words()
    print(f"数据库中已存在 {len(existing_words)} 个单词")

    # 准备数据
    words_to_add = []
    skipped = 0

    for word_data in words_data:
        word = word_data['word']
        if word.lower() in existing_words:
            skipped += 1
            continue

        prepared_data = prepare_word_for_db(word_data)
        words_to_add.append(prepared_data)

    print(f"需要添加 {len(words_to_add)} 个新单词")
    print(f"跳过 {skipped} 个已存在的单词")

    # 批量添加
    if words_to_add:
        print("\n开始批量添加...")
        success_count = 0
        failed_count = 0

        # 创建数据库管理器
        from data.word_database import DatabaseManager
        db_manager = DatabaseManager(DB_CONFIG)

        for i, word_data in enumerate(words_to_add):
            if add_word_to_db(db_manager, word_data):
                success_count += 1

                # 每 10 个单词打印一次进度
                if (i + 1) % 10 == 0:
                    print(f"已添加 {i + 1}/{len(words_to_add)} 个单词")
            else:
                failed_count += 1

        print(f"\n添加完成!")
        print(f"成功: {success_count}")
        print(f"失败: {failed_count}")
    else:
        print("没有需要添加的新单词")

    # 显示最终统计
    final_words = load_existing_words()
    print(f"\n最终统计: 数据库中共有 {len(final_words)} 个单词")

    # 显示一些示例
    print("\n最新添加的单词示例:")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, word, definition, difficulty_level FROM words ORDER BY id DESC LIMIT 10")
        results = cursor.fetchall()

        for word in results:
            print(f"  [{word['id']}] {word['word']}: {word.get('definition', '')[:30]}... ({word.get('difficulty_level', 'N/A')})")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"读取最新单词失败: {e}")

    print("=" * 60)

if __name__ == '__main__':
    main()
