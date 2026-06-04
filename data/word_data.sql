-- 单词知识图谱数据库表结构
-- 数据库: word_knowledge_db
-- 字符集: utf8mb4
-- 排序规则: utf8mb4_unicode_ci

-- 1. 单词表
CREATE TABLE IF NOT EXISTS words (
    id INT AUTO_INCREMENT PRIMARY KEY,
    word VARCHAR(100) NOT NULL UNIQUE,
    pronunciation VARCHAR(200) DEFAULT NULL,
    part_of_speech VARCHAR(50) DEFAULT NULL,
    definition TEXT DEFAULT NULL,
    example_sentence TEXT DEFAULT NULL,
    example_translation TEXT DEFAULT NULL,
    frequency INT DEFAULT 0,
    difficulty_level VARCHAR(20) DEFAULT 'medium',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_word (word),
    INDEX idx_frequency (frequency),
    INDEX idx_difficulty (difficulty_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. 单词关系表（表示节点边）
CREATE TABLE IF NOT EXISTS word_relations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    word_id INT NOT NULL,
    related_word_id INT NOT NULL,
    relation_type VARCHAR(50) NOT NULL,
    relation_strength FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
    FOREIGN KEY (related_word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE KEY unique_relation (word_id, related_word_id, relation_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 用户学习记录表
CREATE TABLE IF NOT EXISTS user_learning (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(100) DEFAULT NULL,
    word_id INT NOT NULL,
    study_count INT DEFAULT 1,
    last_studied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    proficiency_level INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
    INDEX idx_user_word (user_id, word_id),
    INDEX idx_last_studied (last_studied_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 对话记录表
CREATE TABLE IF NOT EXISTS chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(100) DEFAULT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_learning(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. 学习统计表
CREATE TABLE IF NOT EXISTS learning_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(100) DEFAULT NULL,
    total_words INT DEFAULT 0,
    mastered_words INT DEFAULT 0,
    learning_words INT DEFAULT 0,
    total_study_time INT DEFAULT 0,
    streak_days INT DEFAULT 0,
    last_active_date DATE DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_learning(user_id) ON DELETE SET NULL,
    UNIQUE KEY unique_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    config_key VARCHAR(100) NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    description VARCHAR(500) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认配置
INSERT INTO system_config (config_key, config_value, description) VALUES
('llm_api_key', '', 'GLM-4.7-Flash API 密钥'),
('llm_model', 'glm-4-flash', '使用的模型名称'),
('max_words_per_session', '20', '每次学习最大单词数'),
('default_difficulty', 'medium', '默认难度级别'),
('auto_backup_enabled', 'true', '是否启用自动备份');

-- 查看表列表
SHOW TABLES;
