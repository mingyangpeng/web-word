# 数据库配置说明

## 当前配置

- **数据库名称**: web_word_db
- **用户名**: web_word_user
- **密码**: web_project_pass123
- **字符集**: utf8mb4

## 初始化数据库

如果数据库尚未初始化，请运行以下命令：

```bash
# 连接 MySQL
mysql -u root -p

# 在 MySQL 命令行中执行：
CREATE DATABASE IF NOT EXISTS web_word_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'web_word_user'@'localhost' IDENTIFIED BY 'web_project_pass123';
GRANT ALL PRIVILEGES ON web_word_db.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 重新启动 MySQL 服务（如果在后台运行的）
brew services restart mysql@8.0
```

## 测试连接

```bash
mysqladmin ping -h localhost -u web_word_user -pweb_project_pass123
```

## 数据库初始化

应用启动时会自动初始化数据库表，包括：
- definitions (动词定义)
- synonyms (同义词)
- feedbacks (用户反馈)
- usage_logs (使用日志)
- statistics (统计数据)
