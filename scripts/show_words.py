#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
查看数据库中的单词 - 显示详细信息和分类
"""
import sys
import os
import mysql.connector

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'jhon',
    'password': 'p',
    'database': 'word_knowledge_db'
}

def show_words():
    """显示所有单词详细信息"""
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # 查询所有单词
        cursor.execute("""
            SELECT id, word, pronunciation, part_of_speech, definition,
                   frequency, difficulty_level, created_at
            FROM words
            ORDER BY id
        """)
        results = cursor.fetchall()

        print(f"\n数据库中共有 {len(results)} 个单词:\n")
        print("=" * 140)

        for word in results:
            print(f"ID: {word['id']:3d} | "
                  f"单词: {word['word']:15s} | "
                  f"词性: {word['part_of_speech']:6s} | "
                  f"难度: {word['difficulty_level']:8s} | "
                  f"释义: {word['definition'][:50]}")

        print("=" * 140)

        # 按分类统计
        print("\n按分类统计:")
        cursor.execute("""
            SELECT difficulty_level, COUNT(*) as count
            FROM words
            GROUP BY difficulty_level
            ORDER BY count DESC
        """)
        stats = cursor.fetchall()
        for stat in stats:
            print(f"  {stat['difficulty_level']:8s}: {stat['count']:3d} 个单词")

        # 按词性统计
        print("\n按词性统计:")
        cursor.execute("""
            SELECT part_of_speech, COUNT(*) as count
            FROM words
            GROUP BY part_of_speech
            ORDER BY count DESC
        """)
        stats = cursor.fetchall()
        for stat in stats:
            print(f"  {stat['part_of_speech']:8s}: {stat['count']:3d} 个单词")

        # 显示移动动词
        print("\n" + "=" * 140)
        print("移动动词列表 (按分类):")
        print("=" * 140)

        # 按主分类分组
        categories = {
            '路径聚焦类': [],
            '方式聚焦类': [],
            '关联聚焦类': []
        }

        for word in results:
            definition = word['definition']
            word_lower = word['word'].lower()

            # 检查分类
            if word_lower in ['arrive', 'reach', 'return', 'come', 'go',
                             'enter', 'exit', 'ascend', 'rise', 'climb',
                             'fall', 'descend', 'plunge', 'tumble',
                             'advance', 'recede', 'leave', 'abandon',
                             'desert', 'depart', 'escape', 'flee']:
                categories['路径聚焦类'].append(word)
            elif word_lower in ['roll', 'slide', 'bounce', 'drift', 'float', 'glide', 'swing',
                               'walk', 'stride', 'run', 'trot', 'gallop', 'jog', 'sprint',
                               'march', 'tramp', 'stomp', 'step', 'hop', 'skip', 'jump',
                               'leap', 'vault', 'spring', 'hurdle', 'scramble', 'scurry',
                               'dodge', 'zigzag', 'fly', 'soar', 'hover', 'swim', 'dive',
                               'crawl', 'creep', 'clamber', 'slither', 'snake',
                               'travel', 'journey', 'trek', 'hike', 'backpack', 'trudge',
                               'migrate', 'commute', 'drive', 'ride', 'ski', 'skate',
                               'board', 'surf', 'skateboard', 'cycle', 'motor']:
                categories['方式聚焦类'].append(word)
            elif word_lower in ['chase', 'pursue', 'follow', 'shadow', 'tail', 'track', 'trail',
                               'accompany', 'conduct', 'escort', 'guide', 'lead', 'shepherd', 'wait']:
                categories['关联聚焦类'].append(word)

        for category, words in categories.items():
            if words:
                print(f"\n{category} ({len(words)} 个单词):")
                for word in words:
                    print(f"  - {word['word']:15s}: {word['definition'][:40]}")

        cursor.close()

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == '__main__':
    print("=" * 80)
    print("数据库单词查看工具")
    print("=" * 80)
    show_words()
    print("=" * 80)
