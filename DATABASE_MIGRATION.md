# 数据库迁移说明

## 📁 数据库位置变更

**原位置**: `/opt/homebrew/var/mysql/web_word_db/`
**新位置**: `/Users/jhon/pmy/web-word/data/mysql/`

## ✅ 迁移完成状态

- **数据库**: web_word_db
- **存储引擎**: InnoDB
- **字符集**: utf8mb4
- **排序规则**: utf8mb4_unicode_ci
- **总大小**: ~196 MB

## 📊 数据库表结构

| 表名 | 说明 | 记录数 |
|------|------|--------|
| definitions | 动词释义定义表 | 0 |
| feedbacks | 用户反馈表 | 1 (测试数据) |
| statistics | 统计数据表 | 0 |
| synonyms | 同义词关系表 | 0 |
| usage_logs | 使用日志表 | 0 |

## 🔧 MySQL 配置

**配置文件**: `/opt/homebrew/etc/my.cnf`

```ini
[mysqld]
datadir = /Users/jhon/pmy/web-word/data/mysql
bind-address = 127.0.0.1
mysqlx-bind-address = 127.0.0.1
```

## 🔑 数据库账号

- **用户名**: web_word_user
- **密码**: 空（无密码）
- **主机**: localhost
- **数据库**: web_word_db
- **权限**: ALL PRIVILEGES

## 📝 使用说明

### 1. 连接数据库

```bash
# 连接到数据库
mysql -u web_word_user

# 使用数据库
mysql -u web_word_user web_word_db
```

### 2. 备份数据

```bash
# 备份数据库
mysqldump -u web_word_user web_word_db > backup_$(date +%Y%m%d).sql

# 备份特定表
mysqldump -u web_word_user web_word_db definitions > definitions_backup.sql
```

### 3. 恢复数据

```bash
# 恢复数据库
mysql -u web_word_user web_word_db < backup_20260530.sql
```

### 4. 启动 MySQL

```bash
# 启动 MySQL 服务
mysqld_safe --user=jhon --datadir=/Users/jhon/pmy/web-word/data/mysql

# 或者使用 brew services
brew services start mysql@8.0
```

### 5. 停止 MySQL

```bash
# 停止 MySQL 服务
killall mysqld

# 或者使用 brew services
brew services stop mysql@8.0
```

## 📂 目录结构

```
/Users/jhon/pmy/web-word/
├── data/
│   └── mysql/              # MySQL 数据目录
│       ├── mysql/          # MySQL 系统数据库
│       ├── performance_schema/  # 性能模式
│       ├── sys/            # 系统视图
│       ├── web_word_db/    # 应用数据库
│       ├── auto.cnf        # 自动配置
│       ├── binlog.index    # 二进制日志索引
│       └── *.ibd           # InnoDB 数据文件
├── config/
│   └── config.yaml         # 应用配置
└── src/
    ├── mysql_db.py         # MySQL 数据库模块
    └── app.py              # Streamlit 应用
```

## ⚠️ 注意事项

1. **数据目录权限**: 确保 `jhon` 用户对 `/Users/jhon/pmy/web-word/data/mysql/` 有读写权限
2. **MySQL 服务**: 需要手动启动（或使用 brew services）
3. **备份建议**: 定期备份数据库到安全位置
4. **磁盘空间**: 确保 `data/mysql/` 所在的磁盘有足够空间

## 🧪 测试验证

```bash
# 测试数据库连接
mysql -u web_word_user -e "SELECT 1;"

# 检查数据库大小
du -sh /Users/jhon/pmy/web-word/data/mysql

# 查看表结构
mysql -u web_word_user web_word_db -e "SHOW TABLES;"
mysql -u web_word_user web_word_db -e "DESCRIBE definitions;"

# 检查 MySQL 状态
mysql -u web_word_user -e "SHOW PROCESSLIST;"
```

## 🔄 迁移历史

- **2026-05-30**: 从 `/opt/homebrew/var/mysql/` 迁移到项目 `data/mysql/` 目录

## 📞 支持

如有问题，请检查：
1. MySQL 服务状态: `ps aux | grep mysql`
2. 错误日志: `/Users/jhon/pmy/web-word/data/mysql/MacBook-Pro-2.local.err`
3. 数据库连接: `mysql -u web_word_user -e "SELECT 1;"`
