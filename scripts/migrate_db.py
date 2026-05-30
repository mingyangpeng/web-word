#!/usr/bin/env python3
"""
数据库迁移脚本

从 SQLite 迁移到 MySQL
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    import pymysql
    import json
except ImportError:
    print("错误: 需要安装 pymysql")
    sys.exit(1)


def migrate_database():
    """执行数据库迁移"""
    print("开始数据库迁移...")

    import yaml
    with open('config/config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    mysql_config = config['database']['mysql']
    sqlite_path = config['database']['sqlite']['path']

    print(f"MySQL 配置: {mysql_config['database']}@{mysql_config['host']}")
    print(f"SQLite 文件: {sqlite_path}")

    conn = pymysql.connect(
        host=mysql_config['host'],
        port=mysql_config['port'],
        user=mysql_config['user'],
        password=mysql_config['password'],
        database=mysql_config['database'],
        charset=mysql_config['charset'],
        cursorclass=pymysql.cursors.DictCursor
    )

    cursor = conn.cursor()

    import sqlite3
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    print("\\n读取 SQLite 数据...")
    sqlite_cursor.execute("SELECT * FROM queries")
    queries = sqlite_cursor.fetchall()

    sqlite_cursor.execute("SELECT * FROM feedbacks")
    feedbacks = sqlite_cursor.fetchall()

    print(f"找到 {len(queries)} 条查询记录")
    print(f"找到 {len(feedbacks)} 条反馈记录")

    print("\\n迁移查询记录...")
    migrated = 0
    for row in queries:
        try:
            semantic_table = row['semantic_table']
            if isinstance(semantic_table, str):
                semantic_table = json.loads(semantic_table)

            cursor.execute("""
                INSERT INTO definitions (verb, chinese_ndef, semantic_table, example_sentence, model_version)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                row['verb'],
                row.get('traditional_text', ''),
                json.dumps(semantic_table, ensure_ascii=False),
                row.get('optimized_text', ''),
                row.get('model_version', 'sqlite-migrated')
            ))
            migrated += 1
        except Exception as e:
            print(f"  跳过: {row.get('verb', 'Unknown')} - {e}")

    conn.commit()
    print(f"✅ 已迁移 {migrated} 条查询记录")

    print("\\n迁移反馈记录...")
    migrated_feedbacks = 0
    for row in feedbacks:
        try:
            cursor.execute("""
                INSERT INTO feedbacks (verb, rating, feedback_text)
                VALUES (%s, %s, %s)
            """, (
                row['verb'],
                row.get('rating', 5),
                row.get('feedback_text', '')
            ))
            migrated_feedbacks += 1
        except Exception as e:
            print(f"  跳过: {row.get('verb', 'Unknown')} - {e}")

    conn.commit()
    print(f"✅ 已迁移 {migrated_feedbacks} 条反馈记录")

    sqlite_conn.close()
    cursor.close()
    conn.close()

    print("\\n✅ 数据库迁移完成！")


if __name__ == "__main__":
    migrate_database()
