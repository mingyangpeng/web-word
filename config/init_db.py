#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
MySQL 数据库初始化脚本
通过 sudo 执行创建数据库和用户
"""

import subprocess
import sys

def execute_sql(sql_file):
    """执行 SQL 文件"""
    try:
        result = subprocess.run(
            ['sudo', 'mysql'],
            input=open(sql_file).read(),
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"SQL 执行失败: {result.stderr}")
            return False
        print("SQL 执行成功:")
        print(result.stdout)
        return True
    except Exception as e:
        print(f"执行异常: {e}")
        return False

if __name__ == "__main__":
    sql_file = "/home/pmy/megatron_2025/pmy/web-word/config/init_database.sql"
    if execute_sql(sql_file):
        print("\n数据库初始化完成!")
        sys.exit(0)
    else:
        print("\n数据库初始化失败!")
        sys.exit(1)
