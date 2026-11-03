#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
详细查看单词关系
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

def show_detailed_relations():
    """显示详细的关系数据"""
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # 获取所有单词
        cursor.execute("SELECT id, word FROM words WHERE word NOT LIKE '%类' AND word != '总计' ORDER BY id")
        words = cursor.fetchall()

        print("\n" + "=" * 150)
        print("单词关系详细分析")
        print("=" * 150)

        # 按关系类型分组
        relation_types = ['synonym', 'antonym', 'related']

        for rel_type in relation_types:
            print(f"\n{'=' * 150}")
            print(f"{rel_type.upper()} 关系 ({rel_type})")
            print('=' * 150)

            # 获取该类型的关系
            cursor.execute("""
                SELECT w.word AS source, w2.word AS target
                FROM word_relations r
                JOIN words w ON r.word_id = w.id
                JOIN words w2 ON r.related_word_id = w2.id
                WHERE r.relation_type = %s
                ORDER BY source, target
            """, (rel_type,))

            results = cursor.fetchall()
            print(f"共 {len(results)} 条关系:\n")

            # 按来源单词分组
            source_words = {}
            for row in results:
                source = row['source']
                if source not in source_words:
                    source_words[source] = []
                source_words[source].append(row['target'])

            # 显示每组关系
            for source in sorted(source_words.keys()):
                targets = sorted(source_words[source])
                # 只显示与移动动词相关的关系
                if any(word in ['arrive', 'reach', 'come', 'go', 'enter', 'exit',
                               'run', 'walk', 'jump', 'fly', 'swim', 'climb',
                               'chase', 'pursue', 'follow', 'accompany'] for word in [source] + targets):
                    print(f"  {source:15s} --{rel_type:10s}--> {', '.join(targets)}")

        # 三大范畴关系网络
        print("\n" + "=" * 150)
        print("三大范畴知识网络")
        print("=" * 150)

        categories = {
            '路径聚焦类': ['arrive', 'reach', 'come', 'go', 'enter', 'exit',
                          'ascend', 'rise', 'climb', 'fall', 'descend',
                          'advance', 'recede', 'leave', 'depart', 'escape', 'flee'],
            '方式聚焦类': ['walk', 'run', 'jump', 'leap', 'fly', 'swim', 'dive',
                           'climb', 'crawl', 'drive', 'ride', 'ski', 'skate',
                           'run', 'trot', 'gallop', 'jog', 'sprint', 'march'],
            '关联聚焦类': ['chase', 'pursue', 'follow', 'shadow', 'tail',
                           'accompany', 'conduct', 'escort', 'guide', 'lead']
        }

        for category_name, words in categories.items():
            # 获取该范畴所有单词的关系
            word_ids = []
            for word in words:
                cursor.execute("SELECT id FROM words WHERE word = %s", (word,))
                result = cursor.fetchone()
                if result:
                    word_ids.append(result['id'])

            if word_ids:
                print(f"\n{category_name} ({len(words)} 个单词):")

                # 获取所有关系
                placeholders = ', '.join(['%s'] * len(word_ids))
                cursor.execute(f"""
                    SELECT w.word, w2.word, r.relation_type
                    FROM word_relations r
                    JOIN words w ON r.word_id = w.id
                    JOIN words w2 ON r.related_word_id = w2.id
                    WHERE r.word_id IN ({placeholders})
                    AND w2.word NOT LIKE '%类'
                    ORDER BY r.relation_type, w.word, w2.word
                """, word_ids)

                rels = cursor.fetchall()
                for rel in rels:
                    # 只显示与该范畴相关的关系
                    target_field = 'target' if 'target' in rel else 'related_word'
                    if rel['word'] in words or rel.get(target_field) in words:
                        rel_type_icon = {
                            'synonym': '★',
                            'antonym': '✖',
                            'related': '~'
                        }.get(rel['relation_type'], '')

                        print(f"  {rel_type_icon} {rel['word']:15s} --{rel['relation_type']:10s}--> {rel.get(target_field, '?'):15s}")

        # 显示关系统计
        print("\n" + "=" * 150)
        print("关系类型分布")
        print("=" * 150)

        for rel_type in ['synonym', 'antonym', 'related', 'homophone', 'family']:
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM word_relations r
                JOIN words w ON r.word_id = w.id
                JOIN words w2 ON r.related_word_id = w2.id
                WHERE w.word NOT LIKE '%类' AND w2.word NOT LIKE '%类'
            """)
            result = cursor.fetchone()
            count = result['count'] if result else 0
            print(f"  {rel_type:10s}: {count:3d} 条")

        cursor.close()

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == '__main__':
    show_detailed_relations()
