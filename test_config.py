"""
测试配置加载
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.mysql_db import (
    get_config,
    get_mysql_config,
    get_pool_config,
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_DATABASE,
    MYSQL_USER,
    MYSQL_PASSWORD,
    YAML_AVAILABLE
)

print("=" * 60)
print("配置加载测试")
print("=" * 60)

print(f"\n1. YAML 可用性: {'✅ 是' if YAML_AVAILABLE else '❌ 否'}")

print("\n2. 配置文件加载:")
config = get_config()
if config:
    print(f"   ✅ 配置文件已加载")
    print(f"   - 数据库名称: {config.get('database', {}).get('mysql', {}).get('database')}")
    print(f"   - 主机: {config.get('database', {}).get('mysql', {}).get('host')}")
    print(f"   - 端口: {config.get('database', {}).get('mysql', {}).get('port')}")
    print(f"   - 用户: {config.get('database', {}).get('mysql', {}).get('user')}")
    print(f"   - 字符集: {config.get('database', {}).get('mysql', {}).get('charset')}")
else:
    print(f"   ❌ 配置文件未加载")

print("\n3. MySQL 配置:")
mysql_config = get_mysql_config()
if mysql_config:
    print(f"   ✅ MySQL 配置已获取")
    print(f"   - 主机: {mysql_config.get('host')}")
    print(f"   - 端口: {mysql_config.get('port')}")
    print(f"   - 数据库: {mysql_config.get('database')}")
    print(f"   - 用户: {mysql_config.get('user')}")
else:
    print(f"   ❌ MySQL 配置未获取")

print("\n4. 连接池配置:")
pool_config = get_pool_config()
if pool_config:
    print(f"   ✅ 连接池配置已获取")
    print(f"   - 连接数: {pool_config.get('size')}")
    print(f"   - 最大溢出: {pool_config.get('max_overflow')}")
else:
    print(f"   ❌ 连接池配置未获取")

print("\n5. 模块配置变量:")
print(f"   - MYSQL_HOST: {MYSQL_HOST}")
print(f"   - MYSQL_PORT: {MYSQL_PORT}")
print(f"   - MYSQL_DATABASE: {MYSQL_DATABASE}")
print(f"   - MYSQL_USER: {MYSQL_USER}")
print(f"   - MYSQL_PASSWORD: {'*' * len(MYSQL_PASSWORD) if MYSQL_PASSWORD else '(空)'}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
