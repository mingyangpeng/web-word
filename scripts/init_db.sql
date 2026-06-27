-- MySQL 初始化脚本
-- Docker 容器首次启动时自动执行（/docker-entrypoint-initdb.d/）
-- 注意：MYSQL_USER 和 MYSQL_PASSWORD 环境变量已经会自动创建 web_word_user
-- 此脚本用于额外的权限设置和表初始化

-- 确保应用用户有完整权限
GRANT ALL PRIVILEGES ON web_word_db.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- 创建表（与应用 init_database() 保持一致，作为备用初始化）
USE web_word_db;

CREATE TABLE IF NOT EXISTS definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL UNIQUE,
    chinese_ndef TEXT NOT NULL,
    semantic_table JSON NOT NULL,
    example_sentence TEXT,
    model_version VARCHAR(50) DEFAULT 'zhipu-glm-4',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_definitions_verb (verb(50)),
    INDEX idx_definitions_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS synonyms (
    id INT AUTO_INCREMENT PRIMARY KEY,
    original_verb_id INT NOT NULL,
    synonym_verb VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (original_verb_id) REFERENCES definitions(id) ON DELETE CASCADE,
    INDEX idx_synonyms_original (original_verb_id),
    INDEX idx_synonyms_synonym (synonym_verb(50))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS feedbacks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL,
    rating INT NOT NULL CHECK(rating BETWEEN 1 AND 5),
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_feedbacks_verb (verb(50)),
    INDEX idx_feedbacks_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS usage_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL,
    query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_info VARCHAR(255),
    INDEX idx_usage_logs_verb (verb(50)),
    INDEX idx_usage_logs_query_time (query_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS statistics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stat_name VARCHAR(50) NOT NULL UNIQUE,
    stat_value TEXT NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_statistics_name (stat_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
