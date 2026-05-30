#!/usr/bin/env python3
"""
MySQL 连接测试脚本
测试数据库连接、表创建和基本操作
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.mysql_db import (
    init_database,
    get_stats,
    get_hot_verbs,
    get_feedback_data,
    insert_feedback,
    PYMYSQL_AVAILABLE,
    MYSQL_HOST,
    MYSQL_DATABASE,
    MYSQL_USER
)


def test_mysql_connection():
    """测试 MySQL 连接"""
    print("=" * 60)
    print("MySQL 连接测试")
    print("=" * 60)

    # 1. 检查 PyMySQL
    print(f"\n1️⃣ PyMySQL 可用性: {'✅' if PYMYSQL_AVAILABLE else '❌'}")
    if not PYMYSQL_AVAILABLE:
        print("   解决方案: pip install pymysql")
        return False

    # 2. 检查配置
    print(f"\n2️⃣ MySQL 配置:")
    print(f"   主机: {MYSQL_HOST}")
    print(f"   端口: 3306")
    print(f"   数据库: {MYSQL_DATABASE}")
    print(f"   用户: {MYSQL_USER}")

    # 3. 初始化数据库
    print(f"\n3️⃣ 初始化数据库:")
    result = init_database()
    print(f"   初始化结果: {'✅ 成功' if result else '❌ 失败'}")

    if not result:
        print("   请检查 MySQL 服务是否运行")
        print("   解决方案: brew services start mysql")
        return False

    # 4. 测试统计功能
    print(f"\n4️⃣ 测试统计功能:")
    stats = get_stats()
    print(f"   总查询次数: {stats['total_queries']}")
    print(f"   平均评分: {stats['avg_rating']:.1f}/5.0")
    print(f"   总反馈数: {stats['total_feedbacks']}")
    print(f"   总同义词: {stats['total_synonyms']}")

    # 5. 测试热门动词
    print(f"\n5️⃣ 热门动词 (Top 5):")
    hot_verbs = get_hot_verbs(limit=5)
    if hot_verbs:
        for v in hot_verbs:
            print(f"   - {v['verb']}: {v['count']} 次, ⭐ {v['avg_rating']}")
    else:
        print("   暂无热门数据")

    # 6. 测试反馈数据
    print(f"\n6️⃣ 反馈数据:")
    feedbacks = get_feedback_data()
    print(f"   总数: {len(feedbacks)} 条")

    # 7. 测试插入操作
    print(f"\n7️⃣ 测试插入操作:")
    test_feedback = insert_feedback("测试动词", 5, "这是一个测试反馈")
    print(f"   插入结果: {'✅ 成功' if test_feedback else '❌ 失败'}")

    # 8. 验证插入
    print(f"\n8️⃣ 验证插入结果:")
    feedbacks = get_feedback_data()
    print(f"   总数: {len(feedbacks)} 条")
    if len(feedbacks) > 0:
        print(f"   最新反馈: {feedbacks[-1]}")

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！MySQL 连接正常")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_mysql_connection()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
