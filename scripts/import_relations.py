#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
导入单词关系到数据库
"""
import sys
import os
import json
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

# 加载关系数据
RELATIONS_FILE = os.path.join(project_root, 'data', 'word_graph_relations.json')

def load_relations():
    """加载关系数据"""
    with open(RELATIONS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def word_to_id(word, conn):
    """根据单词获取ID"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM words WHERE word = %s", (word,))
    result = cursor.fetchone()
    cursor.close()
    return result['id'] if result else None

def import_relations():
    """导入关系到数据库"""
    print("=" * 80)
    print("单词关系导入工具")
    print("=" * 80)

    # 加载关系数据
    data = load_relations()
    print(f"\n从 {RELATIONS_FILE} 读取了关系数据")
    print(f"关系类型: {list(data['relations'].keys())}")

    # 连接数据库
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # 检查现有关系
        cursor.execute("SELECT COUNT(*) FROM word_relations")
        existing_count = cursor.fetchone()[0]
        print(f"\n数据库中已有 {existing_count} 条关系")

        total_imported = 0
        total_skipped = 0

        # 为每种关系类型导入
        for rel_type, rel_list in data['relations'].items():
            print(f"\n处理 {rel_type} 关系...")
            for source_word, targets in rel_list.items():
                source_id = word_to_id(source_word, conn)
                if not source_id:
                    continue

                for target_word in targets:
                    target_id = word_to_id(target_word, conn)
                    if not target_id:
                        continue

                    # 检查是否已存在
                    cursor.execute("""
                        SELECT id FROM word_relations
                        WHERE word_id = %s AND related_word_id = %s AND relation_type = %s
                    """, (source_id, target_id, rel_type))
                    if cursor.fetchone():
                        total_skipped += 1
                        continue

                    # 插入关系
                    try:
                        cursor.execute("""
                            INSERT INTO word_relations (word_id, related_word_id, relation_type, relation_strength)
                            VALUES (%s, %s, %s, 1.0)
                        """, (source_id, target_id, rel_type))
                        total_imported += 1

                        if total_imported % 50 == 0:
                            print(f"  已导入 {total_imported} 条关系...")

                    except Exception as e:
                        print(f"  插入失败 ({source_word} -> {target_word}): {e}")

            conn.commit()

        print(f"\n导入完成!")
        print(f"成功导入: {total_imported} 条关系")
        print(f"跳过已存在: {total_skipped} 条关系")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
    finally:
        if conn and conn.is_connected():
            conn.close()

    # 显示统计
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # 按关系类型统计
        print("\n" + "=" * 80)
        print("按关系类型统计:")
        print("=" * 80)
        cursor.execute("""
            SELECT relation_type, COUNT(*) as count
            FROM word_relations
            GROUP BY relation_type
            ORDER BY count DESC
        """)
        stats = cursor.fetchall()
        for stat in stats:
            print(f"  {stat['relation_type']:10s}: {stat['count']:3d} 条关系")

        # 显示示例
        print("\n" + "=" * 80)
        print("关系示例:")
        print("=" * 80)
        cursor.execute("""
            SELECT w.word, w2.word, r.relation_type
            FROM word_relations r
            JOIN words w ON r.word_id = w.id
            JOIN words w2 ON r.related_word_id = w2.id
            ORDER BY r.id
            LIMIT 30
        """)
        results = cursor.fetchall()
        for row in results:
            print(f"  {row['word']:15s} --{row['relation_type']:10s}--> {row['word']!r:15s}")

        # 显示特定单词的关系
        print("\n" + "=" * 80)
        print("特定单词的关系:")
        print("=" * 80)
        test_words = ['arrive', 'run', 'chase', 'enter', 'walk', 'fly']

        for word in test_words:
            cursor.execute("""
                SELECT w2.word, r.relation_type
                FROM word_relations r
                JOIN words w ON r.word_id = w.id
                JOIN words w2 ON r.related_word_id = w2.id
                WHERE w.word = %s
                ORDER BY r.relation_type
            """, (word,))
            rels = cursor.fetchall()

            if rels:
                print(f"\n'{word}' 的关系:")
                for rel in rels:
                    print(f"  - {rel['relation_type']:10s}: {rel['related_word']}")

        cursor.close()
    except Exception as e:
        print(f"显示统计错误: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

    print("\n" + "=" * 80)

if __name__ == '__main__':
    import_relations()
