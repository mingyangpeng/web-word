-- 创建数据库
CREATE DATABASE IF NOT EXISTS word_knowledge_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- 创建用户并授权
CREATE USER IF NOT EXISTS 'jhon'@'localhost' IDENTIFIED BY 'p';
GRANT ALL PRIVILEGES ON word_knowledge_db.* TO 'jhon'@'localhost';
FLUSH PRIVILEGES;

-- 显示结果
SHOW DATABASES;
