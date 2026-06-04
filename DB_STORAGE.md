# 数据存储位置

## 方案一：使用 Docker 部署 MySQL（推荐）

数据文件将存储在项目根目录的 `db_data` 文件夹内。

### 快速启动

```bash
# 1. 启动 MySQL 容器
docker-compose up -d

# 2. 等待 MySQL 启动完成
docker-compose logs -f mysql

# 3. 查看数据库状态
docker-compose exec mysql mysql -u jhon -pp -D word_knowledge_db -e "SHOW TABLES;"
```

### 数据文件位置

```
web-word/
├── db_data/              # MySQL 数据目录（所有表数据物理存储在此）
│   ├── word_knowledge_db/  # 数据库目录
│   │   ├── ibdata1       # 共享表空间
│   │   ├── ib_logfile0    # 事务日志
│   │   ├── *.ibd         # 各个表的表空间文件（words.ibd, word_relations.ibd 等）
│   │   └── ...
│   └── .env              # 数据库配置文件
├── docker-compose.yml    # Docker 配置
└── app.py               # Streamlit 应用
```

### 停止服务

```bash
docker-compose down
```

### 数据备份

```bash
# 备份整个 db_data 目录
tar -czf db_backup_$(date +%Y%m%d).tar.gz db_data/
```

## 方案二：使用系统 MySQL（当前配置）

当前配置使用系统 MySQL，数据仍在 `/var/lib/mysql/word_knowledge_db/`

### 查看数据文件

```bash
sudo du -sh /var/lib/mysql/word_knowledge_db/
sudo ls -lh /var/lib/mysql/word_knowledge_db/
```

### 修改数据目录（需要 sudo 权限）

1. 修改 `/etc/mysql/mysql.conf.d/custom-datadir.cnf`：
   ```ini
   [mysqld]
   datadir=/home/pmy/megatron_2025/pmy/web-word/db_data
   socket=/tmp/mysql.sock
   ```

2. 停止 MySQL：
   ```bash
   sudo systemctl stop mysql
   ```

3. 移动现有数据：
   ```bash
   sudo mkdir -p db_data
   sudo cp -r /var/lib/mysql/word_knowledge_db db_data/
   sudo rm -rf /var/lib/mysql/*
   ```

4. 启动 MySQL：
   ```bash
   sudo systemctl start mysql
   ```

## 方案三：使用 MySQL 套接字路径配置（最简单）

已修改 `data/word_database.py`，自动从环境变量读取配置。

### 设置环境变量

```bash
# 在 ~/.bashrc 或 ~/.zshrc 中添加
export DB_PASSWORD='p'
```

### 连接数据库

```bash
mysql -u jhon -p -D word_knowledge_db
```

## 数据库连接信息

- **主机**: localhost
- **端口**: 3306
- **用户**: jhon
- **密码**: p（或在 `.env` 文件中配置）
- **数据库名**: word_knowledge_db

## 验证表数据

```bash
# 使用 Docker 方式
docker-compose exec mysql mysql -u jhon -pp -D word_knowledge_db -e "SHOW TABLES;"

# 查看各表数据量
docker-compose exec mysql mysql -u jhon -pp -D word_knowledge_db -e "
SELECT 'words' AS 表名, COUNT(*) AS 记录数 FROM words
UNION ALL
SELECT 'word_relations', COUNT(*) FROM word_relations
UNION ALL
SELECT 'user_learning', COUNT(*) FROM user_learning
UNION ALL
SELECT 'chat_history', COUNT(*) FROM chat_history
UNION ALL
SELECT 'learning_stats', COUNT(*) FROM learning_stats
UNION ALL
SELECT 'system_config', COUNT(*) FROM system_config;
"
```

## 推荐方案

✅ **推荐使用方案一（Docker 部署）**

- 数据存储在项目 `db_data` 目录，便于版本控制和备份
- 无需 sudo 权限，开箱即用
- 环境隔离，不影响系统 MySQL
- 易于迁移和部署
