# MySQL 数据库配置

## 数据库配置信息
- **数据库名**: word_knowledge_db
- **用户名**: jhon
- **密码**: p
- **数据目录**: /home/pmy/megatron_2025/pmy/web-word/db_data
- **服务地址**: localhost
- **端口**: 3306

## 连接信息
```python
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'jhon',
    'password': 'p',
    'database': 'word_knowledge_db'
}
```

## 数据库状态
- ✅ MySQL 8.0 服务器已安装并运行
- ✅ 数据库 word_knowledge_db 已创建
- ✅ 用户 jhon 已创建并授权
- ✅ 字符集: utf8mb4
- ✅ 排序规则: utf8mb4_unicode_ci

## 服务状态
```bash
# 检查服务状态
sudo systemctl status mysql

# 启动服务
sudo systemctl start mysql

# 停止服务
sudo systemctl stop mysql

# 重启服务
sudo systemctl restart mysql
```

## 验证连接
```bash
# 使用用户连接
mysql -u jhon -p word_knowledge_db -e "SELECT DATABASE();"
# 输入密码: p

# 查看所有数据库
mysql -u root -p -e "SHOW DATABASES;"

# 查看 jhon 用户权限
mysql -u root -p -e "SHOW GRANTS FOR 'jhon'@'localhost';"
```

## 数据库表结构
参见: `data/word_data.sql`
