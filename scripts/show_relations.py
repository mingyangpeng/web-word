#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
查看数据库中的单词关系
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

def show_relations():
    """显示单词关系"""
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # 查询所有关系
        cursor.execute("""
            SELECT r.id, r.word_id, w.word AS source_word,
                   r.related_word_id, w2.word AS related_word,
                   r.relation_type, r.relation_strength, r.created_at
            FROM word_relations r
            JOIN words w ON r.word_id = w.id
            JOIN words w2 ON r.related_word_id = w2.id
            ORDER BY r.word_id, r.related_word_id
            LIMIT 200
        """)
        results = cursor.fetchall()

        print(f"\n数据库中共有 {len(results)} 条单词关系:\n")
        print("=" * 130)

        for rel in results:
            print(f"[{rel['id']:3d}] {rel['source_word']:15s} --({rel['relation_type']:10s})--> {rel['related_word']:15s} (强度: {rel['relation_strength']})")

        print("=" * 130)

        # 按关系类型统计
        print("\n按关系类型统计:")
        cursor.execute("""
            SELECT relation_type, COUNT(*) as count
            FROM word_relations
            GROUP BY relation_type
            ORDER BY count DESC
        """)
        stats = cursor.fetchall()
        for stat in stats:
            print(f"  {stat['relation_type']:10s}: {stat['count']:3d} 条关系")

        # 显示特定单词的关系
        print("\n" + "=" * 130)
        print("特定单词的关系示例:")
        print("=" * 130)

        test_words = ['arrive', 'run', 'chase', 'enter', 'walk']

        for word in test_words:
            cursor.execute("""
                SELECT w2.word AS related_word, r.relation_type
                FROM word_relations r
                JOIN words w ON r.word_id = w.id
                JOIN words w2 ON r.related_word_id = w2.id
                WHERE w.word = %s
            """, (word,))
            rels = cursor.fetchall()

            if rels:
                print(f"\n'{word}' 的关系:")
                for rel in rels:
                    print(f"  - {rel['relation_type']:10s}: {rel['related_word']}")

        # 按类别分组显示
        print("\n" + "=" * 130)
        print("按范畴分组的关系:")
        print("=" * 130)

        categories = {
            '路径聚焦类': ['arrive', 'reach', 'come', 'go', 'enter', 'exit', 'leave', 'depart', 'advance', 'recede'],
            '方式聚焦类': ['walk', 'run', 'jump', 'fly', 'swim', 'climb', 'crawl', 'drive', 'sail', 'ski'],
            '关联聚焦类': ['chase', 'pursue', 'follow', 'accompany', 'guide', 'lead']
        }

        for category, words in categories.items():
            relations = []
            for word in words:
                cursor.execute("""
                    SELECT w2.word, r.relation_type
                    FROM word_relations r
                    JOIN words w ON r.word_id = w.id
                    JOIN words w2 ON r.related_word_id = w2.id
                    WHERE w.word = %s
                """, (word,))
                for rel in cursor.fetchall():
                    if rel['related_word'] not in words:
                        relations.append(f"  {word:15s} --{rel['relation_type']:10s}--> {rel['related_word']:15s}")

            if relations:
                print(f"\n{category}:")
                for rel in relations[:10]:  # 每类最多显示10条
                    print(rel)
                if len(relations) > 10:
                    print(f"  ... (共{len(relations)}条)")

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
    print("单词关系查看工具")
    print("=" * 80)
    show_relations()
    print("=" * 80)
