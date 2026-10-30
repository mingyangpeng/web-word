"""
MySQL 8.0 数据库模块

提供数据库连接、表初始化和 CRUD 操作。
数据库存储在 MySQL 8.0 服务器上。
"""

import os
import json
import logging
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

# Try to import PyMySQL, provide fallback to SQLite
try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    logging.warning("PyMySQL not available. Install with: pip install pymysql")

# Try to import PyYAML for config loading
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logging.warning("PyYAML not available. Install with: pip install pyyaml")

# Load configuration from config.yaml
def load_config():
    """从 config.yaml 加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config
        except Exception as e:
            logger.error(f"Failed to load config.yaml: {e}")
    else:
        logger.warning(f"Config file not found: {config_path}")
    return None

def get_config():
    """获取全局配置对象"""
    global _config
    if _config is None:
        _config = load_config()
    return _config

def get_mysql_config():
    """获取 MySQL 配置"""
    config = get_config()
    if config and 'database' in config and 'mysql' in config['database']:
        return config['database']['mysql']
    return None

def get_pool_config():
    """获取连接池配置"""
    config = get_config()
    if config and 'database' in config and 'pool' in config['database']:
        return config['database']['pool']
    return {'size': 5, 'max_overflow': 10}

_config = None  # 全局配置对象

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# 数据库配置
# ============================================
# 优先级：环境变量 > config/config.yaml > 内置默认值。
#
# 为什么环境变量优先：同一份 config.yaml 要能在两种环境下工作 ——
#   * Docker Compose：MySQL 主机名是 compose 服务名 "mysql"
#   * 本地开发：MySQL 主机名是 "127.0.0.1"
# 若 YAML 固定优先级最高，本地开发者必须改被 git 跟踪的配置才能启动。
# 环境变量优先让部署方无需改动仓库内的任何文件。
_mysql_config = get_mysql_config() or {}


def _setting(env_key: str, yaml_key: str, default: Any) -> Any:
    """读取一项数据库设置：环境变量优先，其次 YAML，最后默认值。"""
    env_value = os.getenv(env_key)
    if env_value is not None and env_value != "":
        return env_value
    if _mysql_config.get(yaml_key) not in (None, ""):
        return _mysql_config[yaml_key]
    return default


MYSQL_HOST = _setting("MYSQL_HOST", "host", "127.0.0.1")
MYSQL_PORT = int(_setting("MYSQL_PORT", "port", 3306))
MYSQL_DATABASE = _setting("MYSQL_DATABASE", "database", "web_word_db")
MYSQL_USER = _setting("MYSQL_USER", "user", "web_word_user")
MYSQL_PASSWORD = _setting("MYSQL_PASSWORD", "password", "")
MYSQL_CHARSET = _setting("MYSQL_CHARSET", "charset", "utf8mb4")
MYSQL_COLLATION = _setting("MYSQL_COLLATION", "collation", "utf8mb4_unicode_ci")


# Connection pool configuration
_pool_config = get_pool_config()
MYSQL_POOL_SIZE = _pool_config.get('size', 5)
MYSQL_POOL_MAX_OVERFLOW = _pool_config.get('max_overflow', 10)

# ============================================
# 建表 SQL
# ============================================
# 表结构版本（见 SCHEMA_VERSION 与 init_database 内的迁移调用）。
#
# 设计要点（2026-09 重构）：
#   * word_clusters —— 词义簇，来源是词库的 (main_cat, sub_cat)。这是「词与词关系」
#     的第一性数据：同簇 => 互为近义。
#   * definitions.cluster_id —— 每个动词归属哪个簇，簇成员关系由此表达。
#   * word_relations —— 词间关系边表，**物化的是簇内完全图**：同一簇内任意两词都有一
#     条边。CHECK(verb_a_id < verb_b_id) 保证无向边只存一份（不再像旧 synonyms 那样
#     双向各存一行），(verb_a_id, verb_b_id) 唯一约束保证重复灌库幂等。
#   * 旧 synonyms 表已废弃：它用 original_verb_id(FK) + synonym_verb(裸字符串，无 FK)
#     表达有向关系，既无唯一约束（重复插入直接翻倍），也无法保证词真的存在。
#
# 为什么冗余物化：word_relations 的边在数学上可由 cluster_id 推导，显式物化是为了让
# 「词间关系」成为可直接查询 / 导出 / 喂给图谱工具的一等数据，而不是每次现场 JOIN 生成。
# 视图 v_cluster_complete_graph 则提供「从簇推导」的对照实现，两者应一致。

SCHEMA_VERSION = 9

CREATE_TABLES_SQL = [
    # --- 迁移记录 ---
    """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INT NOT NULL PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 词义簇 ---
    """CREATE TABLE IF NOT EXISTS word_clusters (
        id INT AUTO_INCREMENT PRIMARY KEY,
        main_cat VARCHAR(64) NOT NULL,
        sub_cat VARCHAR(64) NOT NULL,
        label VARCHAR(160) NOT NULL,
        size INT NOT NULL DEFAULT 0,
        image_schema VARCHAR(32) DEFAULT NULL,
        cn_syntax VARCHAR(255) DEFAULT NULL,
        translation_strategy VARCHAR(255) DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_word_clusters_cats (main_cat, sub_cat),
        INDEX idx_word_clusters_size (size),
        INDEX idx_word_clusters_schema (image_schema)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 动词释义（含所属簇）---
    """CREATE TABLE IF NOT EXISTS definitions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        chinese_ndef TEXT NOT NULL,
        semantic_table JSON NOT NULL,
        example_sentence TEXT,
        model_version VARCHAR(50) DEFAULT 'zhipu-glm-4',
        cluster_id INT DEFAULT NULL,
        en_ndef TEXT,
        phonetic VARCHAR(64) DEFAULT NULL,
        levin_source VARCHAR(64) DEFAULT NULL,
        cross_subclass VARCHAR(8) DEFAULT NULL,
        sense_brief VARCHAR(255) DEFAULT NULL,
        judge_reason VARCHAR(600) DEFAULT NULL,
        image_schema VARCHAR(32) DEFAULT NULL,
        prototype_level VARCHAR(16) DEFAULT NULL,
        alignment VARCHAR(16) DEFAULT NULL,
        cn_syntax VARCHAR(255) DEFAULT NULL,
        translation_strategy VARCHAR(255) DEFAULT NULL,
        definition_source VARCHAR(32) DEFAULT NULL,
        source_rank TINYINT DEFAULT NULL,
        sense_count INT NOT NULL DEFAULT 0,
        needs_review TINYINT(1) NOT NULL DEFAULT 0,
        prototype_is_first TINYINT(1) DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_definitions_verb (verb),
        INDEX idx_definitions_cluster (cluster_id),
        INDEX idx_definitions_created_at (created_at),
        INDEX idx_definitions_source (definition_source),
        INDEX idx_definitions_schema (image_schema),
        INDEX idx_definitions_review (needs_review),
        CONSTRAINT fk_definitions_cluster FOREIGN KEY (cluster_id)
            REFERENCES word_clusters(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 义位（sense）明细 ---
    # 判定标准文档明确「分析单元是义位（sense），而非词目 lemma」，所以义位必须独立成表。
    # 一个动词可以有多个义位（go 在 dictionary.db 里有 38 个），每个义位单独标注
    # 意象图式 / 原型层级 / 对齐等级；词目层的 definitions 行则是「主导原型义」的摘要。
    """CREATE TABLE IF NOT EXISTS word_senses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        definition_id INT NOT NULL,
        sense_index INT NOT NULL,
        en_ndef TEXT,
        ch_ndef TEXT,
        construction VARCHAR(255) DEFAULT NULL,
        examples JSON,
        ch_examples JSON,
        synonyms JSON,
        antonyms JSON,
        prototype_level VARCHAR(16) DEFAULT NULL,
        image_schema VARCHAR(32) DEFAULT NULL,
        alignment VARCHAR(16) DEFAULT NULL,
        cn_syntax VARCHAR(255) DEFAULT NULL,
        translation_strategy VARCHAR(255) DEFAULT NULL,
        source VARCHAR(32) DEFAULT NULL,
        needs_review TINYINT(1) NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_word_senses_index (definition_id, sense_index),
        INDEX idx_word_senses_definition (definition_id),
        INDEX idx_word_senses_prototype (prototype_level),
        INDEX idx_word_senses_source (source),
        CONSTRAINT fk_word_senses_definition FOREIGN KEY (definition_id)
            REFERENCES definitions(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- OALD10 义项（与 word_senses 分开成表）---
    #
    # 为什么不与 word_senses 合并成一张表加 `source` 列：两个来源的**切分体系不同**，
    # 无法一一对应，合表会带来三个具体麻烦 ——
    #
    #   1. `sense_index` 是「同一个词目下第几条」的序号，两套体系混排后
    #      `charge` 的 10 条中英义位后面接着 12 条 OALD 义项，序号不再表达任何东西；
    #   2. OALD 义项有 `grammar` / `sense_group` / `is_idiom` 这些**只有它才有**的字段，
    #      合表就必须容忍一半的行这些列恒为 NULL；
    #   3. 两个来源都有各自的「首条义项」，合表后「谁是原型义」要靠外部约定来消歧。
    #
    # 代价是「取某词的全部义项」要 UNION 或查两次 —— 这个代价集中在一个地方
    # （`get_all_senses`），换来的是两张表各自干净、字段都有意义。
    """CREATE TABLE IF NOT EXISTS oald_senses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        definition_id INT NOT NULL,
        sense_index INT NOT NULL,
        -- OALD 原始释义（英文）。已被清洗：开头的语法码剥到 grammar 列，
        -- 例句拆进 examples，正文里不再残留 `[...]` / `<...>`
        definition TEXT,
        -- 剥下来的语法码，如 `transitive, often passive`。**不删**：它决定这个义项
        -- 能不能带宾语，是判断英汉对齐时必须看的证据
        grammar VARCHAR(64) DEFAULT NULL,
        -- 语义分组标签（OALD 的 group_tag），如 `money` / `IDIOMS` / `move fast on foot`
        sense_group VARCHAR(64) DEFAULT NULL,
        examples JSON,
        -- 例句的句法模式，与 examples **按下标一一对应**；不适用处为空串
        example_patterns JSON,
        -- 习语义项（group_tag == IDIOMS）标记。保留该义项但标记出来：
        -- 是否排除应由研究者决定，程序替他们决定等于隐藏了数据
        is_idiom TINYINT(1) NOT NULL DEFAULT 0,
        -- 义项来自哪个词条名。同形异义（row1 划船 / row2 争吵、tear1 / tear2）
        -- 会归并到同一个词目下，靠这一列回溯
        headword VARCHAR(64) DEFAULT NULL,
        prototype_level VARCHAR(16) DEFAULT NULL,
        image_schema VARCHAR(32) DEFAULT NULL,
        alignment VARCHAR(16) DEFAULT NULL,
        cn_syntax VARCHAR(255) DEFAULT NULL,
        translation_strategy VARCHAR(255) DEFAULT NULL,
        source VARCHAR(32) NOT NULL DEFAULT 'OALD10',
        needs_review TINYINT(1) NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_oald_senses_index (definition_id, sense_index),
        INDEX idx_oald_senses_definition (definition_id),
        INDEX idx_oald_senses_idiom (is_idiom),
        INDEX idx_oald_senses_group (sense_group),
        CONSTRAINT fk_oald_senses_definition FOREIGN KEY (definition_id)
            REFERENCES definitions(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 词间关系（无向，簇内完全图）---
    """CREATE TABLE IF NOT EXISTS word_relations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb_a_id INT NOT NULL,
        verb_b_id INT NOT NULL,
        relation VARCHAR(32) NOT NULL DEFAULT '近义',
        cluster_id INT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_word_relations_pair (verb_a_id, verb_b_id),
        INDEX idx_word_relations_a (verb_a_id),
        INDEX idx_word_relations_b (verb_b_id),
        INDEX idx_word_relations_cluster (cluster_id),
        CONSTRAINT chk_word_relations_order CHECK (verb_a_id < verb_b_id),
        CONSTRAINT fk_word_relations_a FOREIGN KEY (verb_a_id)
            REFERENCES definitions(id) ON DELETE CASCADE,
        CONSTRAINT fk_word_relations_b FOREIGN KEY (verb_b_id)
            REFERENCES definitions(id) ON DELETE CASCADE,
        CONSTRAINT fk_word_relations_cluster FOREIGN KEY (cluster_id)
            REFERENCES word_clusters(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 用户反馈 ---
    """CREATE TABLE IF NOT EXISTS feedbacks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        rating INT NOT NULL,
        feedback_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_feedbacks_verb (verb(50)),
        INDEX idx_feedbacks_created_at (created_at),
        CONSTRAINT chk_feedbacks_rating CHECK (rating BETWEEN 1 AND 5)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 查询日志 ---
    """CREATE TABLE IF NOT EXISTS usage_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(100) NOT NULL,
        query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        device_info VARCHAR(255),
        INDEX idx_usage_logs_verb (verb(50)),
        INDEX idx_usage_logs_query_time (query_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 语料库词频概览（数据源：output/05_原始数据/wsketch_full，
    #     Sketch Engine enTenTen21 Word Sketch，由 scripts/load_corpus_dataset.py 灌入）---
    """CREATE TABLE IF NOT EXISTS corpus_word_stats (
        verb VARCHAR(50) PRIMARY KEY,
        lpos VARCHAR(10) NOT NULL DEFAULT '-v',
        freq BIGINT NOT NULL DEFAULT 0,
        relfreq FLOAT NULL COMMENT '每百万词频次',
        slot_count INT NOT NULL DEFAULT 0 COMMENT '语法关系(槽位)数',
        collocate_count INT NOT NULL DEFAULT 0 COMMENT '搭配词型总数',
        candidate_schema VARCHAR(32) NULL COMMENT 'AI初筛候选凸显图式',
        retrieved_at DATE NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 语料搭配明细（每槽位前 50 个搭配词，语义归类列人工填写后回写）---
    """CREATE TABLE IF NOT EXISTS corpus_collocations (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        verb VARCHAR(50) NOT NULL,
        slot VARCHAR(190) NOT NULL,
        rank_in_slot INT NOT NULL,
        collocate VARCHAR(190) NOT NULL,
        logdice FLOAT NULL,
        cooccur_count BIGINT NULL,
        typical_combo VARCHAR(255) NULL,
        combo_freq INT NULL,
        semantic_category VARCHAR(64) NULL COMMENT '语义类别(人工)',
        keep_flag VARCHAR(8) NULL COMMENT '保留/剔除(人工)',
        INDEX idx_cc_verb_slot (verb, slot),
        INDEX idx_cc_collocate (collocate(64))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 意象图式重心得分（AI 初筛，S = Mean_logDice × log2(N+1)）---
    """CREATE TABLE IF NOT EXISTS word_schema_scores (
        verb VARCHAR(50) NOT NULL,
        schema_name VARCHAR(32) NOT NULL,
        slots_present INT NOT NULL,
        slots_defined INT NOT NULL,
        coverage FLOAT NULL,
        n_types INT NOT NULL DEFAULT 0,
        mean_logdice FLOAT NULL,
        prominence_score FLOAT NULL,
        cand_rank INT NOT NULL,
        PRIMARY KEY (verb, schema_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 图式证据搭配（每图式 Top10 证据词及其槽位）---
    """CREATE TABLE IF NOT EXISTS corpus_schema_evidence (
        verb VARCHAR(50) NOT NULL,
        schema_name VARCHAR(32) NOT NULL,
        rank_no INT NOT NULL,
        word VARCHAR(190) NOT NULL,
        logdice FLOAT NULL,
        slot VARCHAR(190) NOT NULL,
        PRIMARY KEY (verb, schema_name, rank_no)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 域—系初判（v0.2：352 保留义位按词目层初判归域归系，页面展示与标注对照）---
    # 主键 = (word, sense_num)：SenseID「动词-Sn」拆成词目 + 义位序号两列，
    # 组合键定位单词义项；sense_id 保留为 STORED 生成列（word-Sn），兼容旧引用。
    # 中文释义 + 多条例句（含中文翻译）拆子表 domain_family_examples，
    # 例句与翻译逐条对齐（同序号同行），避免 JSON 列不可查询、不可索引。
    """CREATE TABLE IF NOT EXISTS domain_family_senses (
        word VARCHAR(50) NOT NULL COMMENT '词目（SenseID 的动词部分）',
        sense_num INT NOT NULL COMMENT '义位序号（SenseID 的 Sn 部分）',
        sense_id VARCHAR(64) AS (CONCAT(word, '-S', sense_num)) STORED
            COMMENT '生成列：动词-Sn，全数据集主键',
        definition TEXT NULL COMMENT 'OALD10 英文释义',
        definition_cn TEXT NULL COMMENT '中文释义（dictionary.db 已审校释义，覆盖 17 词 246 义位）',
        example TEXT NULL COMMENT '首条例句（英文，冗余自子表第 1 条，便于列表速览）',
        lemma_schema VARCHAR(32) NULL COMMENT '词目层初判图式',
        domain VARCHAR(32) NOT NULL COMMENT '认知域（初判）',
        family VARCHAR(32) NOT NULL COMMENT '语义系（初判）',
        sense_annotation VARCHAR(32) NULL COMMENT '义位层标注（待人工，初判表预留列）',
        rule_tag VARCHAR(8) NOT NULL DEFAULT 'R0' COMMENT '筛选规则标签：R0 常规/R2 明确保留/R3 边界复核',
        rule_note VARCHAR(500) NULL COMMENT 'R2/R3 的判定理由（完整文本）',
        source VARCHAR(32) NOT NULL DEFAULT '域系初判表v0.2'
            COMMENT '本行数据来源（xlsx 版本 / 人工修订 / LLM 初筛）',
        loaded_at DATE NULL COMMENT '首次灌入日期',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '最后修改时间（自动更新）',
        PRIMARY KEY (word, sense_num)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 域—系初判·例句子表（多条例句 + 对应中文翻译，逐条对齐）---
    """CREATE TABLE IF NOT EXISTS domain_family_examples (
        word VARCHAR(50) NOT NULL COMMENT '词目（与主表组合键对应）',
        sense_num INT NOT NULL COMMENT '义位序号',
        ex_num INT NOT NULL COMMENT '例句序号（1 起，与中文翻译同序号对齐）',
        example_en TEXT NULL COMMENT '英文例句',
        example_cn TEXT NULL COMMENT '中文翻译（与 example_en 同行对齐；缺失为 NULL）',
        source VARCHAR(32) NULL COMMENT '例句来源：OALD10 / dictionary.db / corpus',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '最后修改时间（自动更新）',
        PRIMARY KEY (word, sense_num, ex_num),
        FOREIGN KEY (word, sense_num) REFERENCES domain_family_senses(word, sense_num)
            ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]

# 只读视图：用「簇成员两两配对」推导完全图，作为 word_relations 物化表的对照实现。
CREATE_VIEWS_SQL = [
    """CREATE OR REPLACE VIEW v_cluster_complete_graph AS
        SELECT c.id      AS cluster_id,
               c.label   AS cluster_label,
               c.sub_cat AS sub_cat,
               a.id      AS verb_a_id,
               a.verb    AS verb_a,
               b.id      AS verb_b_id,
               b.verb    AS verb_b
        FROM word_clusters c
        JOIN definitions a ON a.cluster_id = c.id
        JOIN definitions b ON b.cluster_id = c.id AND b.id > a.id
    """
]

# 范畴深挖（category study）8 表：categories / cs_lexemes / cs_senses /
# cs_sense_features / cs_cluster_runs / cs_clusters / cs_cluster_members /
# cs_cluster_alignment。表结构单一来源在 src/category_study.py —— 这里在
# init_database 时 import 并追加，避免循环依赖（category_study 只用本模块的
# get_db_cursor）。v9 迁移即「建表」，新表无历史数据，无需 ALTER。
def _register_category_study_tables() -> None:
    try:
        from src import category_study
        category_study.register_tables()
    except ImportError as e:
        logger.warning(f"category_study module unavailable, skip its tables: {e}")

# ============================================
# 结构迁移
# ============================================
def _column_exists(cursor, table: str, column: str) -> bool:
    """表上是否已有该列（用于让 ALTER 幂等）。"""
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (MYSQL_DATABASE, table, column),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _table_exists(cursor, table: str) -> bool:
    """表是否存在。"""
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s""",
        (MYSQL_DATABASE, table),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _constraint_exists(cursor, table: str, name: str) -> bool:
    """外键/约束是否存在。"""
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.TABLE_CONSTRAINTS
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s""",
        (MYSQL_DATABASE, table, name),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _index_exists(cursor, table: str, name: str) -> bool:
    """索引是否存在。"""
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s""",
        (MYSQL_DATABASE, table, name),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _migrate_schema(cursor) -> Dict[str, Any]:
    """
    把旧结构的库原地升级到 SCHEMA_VERSION，幂等、不丢业务数据。

    从 v1 → v2 做的事：

      1. ``definitions`` 增加 ``cluster_id``（+ 索引 + 外键），让每个动词能归属到一个词义簇。
         旧库的 CREATE TABLE IF NOT EXISTS 对已存在的表是空操作，所以必须 ALTER。
      2. 建 ``word_relations``（由 CREATE_TABLES_SQL 完成）并**丢弃旧的 ``synonyms``**。
         synonyms 是派生数据：它的边由词库的 sub_cat 现场推导而来，可以随时重建，
         因此不迁移行、只重建。判据是 ``word_relations`` 是否为空 —— 空则说明尚未重建。
         保留它不是更好：旧表存的是「环邻」边，新语义是「簇内完全图」，混在一起会得到
         自相矛盾的图。
      3. 丢弃 ``statistics`` 表：v1 设计里的键值统计表，全仓库无任何代码读写，实际是死表。
      4. 记录版本到 ``schema_migrations``。

    从 v2 → v3 做的事：

      5. 依据 `docs/义项判定标准.docx`，给 ``definitions`` 加义位层面的标注字段
         （意象图式 / 原型层级 / 英汉对齐等级 / 汉语句法特征 / 译义转化策略 / 释义来源…），
         给 ``word_clusters`` 加簇层面的图式与句法特征，并新建 ``word_senses`` 明细表。

         文档明确「分析单元是义位（sense），而非词目 lemma」，所以义位必须独立成表；
         词目层的 ``definitions`` 行退化为「主导原型义」的摘要。

         迁移**只做结构**：词簇与词间关系是派生数据，由灌库脚本按新的 Levin 分类重建。
         不在迁移里 DELETE 是有意的 —— 迁移每次启动都会跑，让它删业务数据太危险。

    从 v3 → v4 做的事：

      6. ``definitions`` 增加 ``phonetic``（音标）。数据源是 ``data/dictionary.db``
         的 ``<pronunciation>``，覆盖不全（136 词里 23 个），所以允许为 NULL，
         前端据此显示「未收录」而不是编一个音标。

    从 v5 → v6 做的事：

      7. 把 OALD10 义项从 ``word_senses`` 拆出来，独立成 ``oald_senses`` 表
         （表本身由 ``CREATE_TABLES_SQL`` 建，迁移只负责删过渡列）。

         中间那版曾把两个来源合在 ``word_senses`` 里、按 ``source`` 区分，实测下来
         合表的代价更高：两套切分体系无法一一对应，``sense_index`` 混排后不再表达
         「同词目下第几条」，并且一半的行 ``grammar`` / ``sense_group`` /
         ``is_idiom`` 恒为 NULL。分表后两张表各自干净、每列都有意义。

         迁移删掉 v5 新增的那 6 列并清掉已写入的 OALD 过渡行 —— 两者都是派生数据，
         灌库脚本会重建。代价是「取某词全部义项」要查两次，这个代价集中在
         ``get_all_senses()`` 一个地方。

    Args:
        cursor: 已 USE 到目标库的 DictCursor。

    Returns:
        迁移摘要 dict，便于日志与测试断言。
    """
    summary: Dict[str, Any] = {"from": None, "to": SCHEMA_VERSION, "actions": []}

    # 已记录的版本（旧库没有这张表时视为 v1）
    if _table_exists(cursor, "schema_migrations"):
        cursor.execute("SELECT MAX(version) AS v FROM schema_migrations")
        row = cursor.fetchone()
        summary["from"] = int(row["v"]) if row and row["v"] is not None else 1
    else:
        summary["from"] = 1

    # --- 1. definitions.cluster_id ---
    if not _column_exists(cursor, "definitions", "cluster_id"):
        cursor.execute(
            "ALTER TABLE definitions ADD COLUMN cluster_id INT DEFAULT NULL"
        )
        summary["actions"].append("definitions.cluster_id added")

    if not _index_exists(cursor, "definitions", "idx_definitions_cluster"):
        cursor.execute(
            "ALTER TABLE definitions ADD INDEX idx_definitions_cluster (cluster_id)"
        )
        summary["actions"].append("idx_definitions_cluster added")

    if not _constraint_exists(cursor, "definitions", "fk_definitions_cluster"):
        cursor.execute(
            """ALTER TABLE definitions
               ADD CONSTRAINT fk_definitions_cluster FOREIGN KEY (cluster_id)
               REFERENCES word_clusters(id) ON DELETE SET NULL"""
        )
        summary["actions"].append("fk_definitions_cluster added")

    # --- 2. 丢弃派生表 synonyms ---
    if _table_exists(cursor, "synonyms"):
        cursor.execute("SELECT COUNT(*) AS n FROM synonyms")
        n_old = int(cursor.fetchone()["n"] or 0)
        cursor.execute("DROP TABLE synonyms")
        summary["actions"].append(f"synonyms dropped (had {n_old} rows, derived data)")
        summary["synonyms_rows_discarded"] = n_old

    # --- 3. 丢弃死表 statistics ---
    if _table_exists(cursor, "statistics"):
        cursor.execute("SELECT COUNT(*) AS n FROM statistics")
        n_stat = int(cursor.fetchone()["n"] or 0)
        cursor.execute("DROP TABLE statistics")
        summary["actions"].append(f"statistics dropped (had {n_stat} rows, unused)")

    # --- 4. v3：义位层面的标注字段（依据 docs/义项判定标准.docx）---
    #
    # 这些列全部可空：已有的 155 行不该因为加列而失败，灌库脚本随后会填上真实值。
    # 用 ADD COLUMN 而不是重建表，是为了不丢 feedback 与 usage_logs 引用的 verb 数据。
    new_definition_columns = [
        ("en_ndef", "TEXT"),
        ("levin_source", "VARCHAR(64)"),
        ("cross_subclass", "VARCHAR(8)"),
        ("sense_brief", "VARCHAR(255)"),
        ("judge_reason", "VARCHAR(600)"),
        ("image_schema", "VARCHAR(32)"),
        ("prototype_level", "VARCHAR(16)"),
        ("alignment", "VARCHAR(16)"),
        ("cn_syntax", "VARCHAR(255)"),
        ("translation_strategy", "VARCHAR(255)"),
        ("definition_source", "VARCHAR(32)"),
        ("source_rank", "TINYINT"),
        ("sense_count", "INT NOT NULL DEFAULT 0"),
        ("needs_review", "TINYINT(1) NOT NULL DEFAULT 0"),
        # 原型义位是否就是词典首条。0 = 被选择器修正过，复核时优先看
        ("prototype_is_first", "TINYINT(1) DEFAULT NULL"),
    ]
    for col, ddl in new_definition_columns:
        if not _column_exists(cursor, "definitions", col):
            cursor.execute(f"ALTER TABLE definitions ADD COLUMN {col} {ddl}")
            summary["actions"].append(f"definitions.{col} added")

    for idx_col, idx_name in [
        ("definition_source", "idx_definitions_source"),
        ("image_schema", "idx_definitions_schema"),
        ("needs_review", "idx_definitions_review"),
    ]:
        if not _index_exists(cursor, "definitions", idx_name):
            cursor.execute(
                f"ALTER TABLE definitions ADD INDEX {idx_name} ({idx_col})"
            )
            summary["actions"].append(f"{idx_name} added")

    new_cluster_columns = [
        ("image_schema", "VARCHAR(32)"),
        ("cn_syntax", "VARCHAR(255)"),
        ("translation_strategy", "VARCHAR(255)"),
    ]
    for col, ddl in new_cluster_columns:
        if not _column_exists(cursor, "word_clusters", col):
            cursor.execute(f"ALTER TABLE word_clusters ADD COLUMN {col} {ddl}")
            summary["actions"].append(f"word_clusters.{col} added")

    if not _index_exists(cursor, "word_clusters", "idx_word_clusters_schema"):
        cursor.execute(
            "ALTER TABLE word_clusters ADD INDEX idx_word_clusters_schema (image_schema)"
        )
        summary["actions"].append("idx_word_clusters_schema added")

    # 迁移只做**结构**改造；词簇与关系是派生数据，由灌库脚本按新的 Levin 分类重建。
    # 不在迁移里 DELETE 是刻意的：迁移在每次应用启动时都会跑，让它删业务数据太危险。
    if not _table_exists(cursor, "word_senses"):
        summary["actions"].append("word_senses will be created by CREATE_TABLES_SQL")
    if not _table_exists(cursor, "oald_senses"):
        summary["actions"].append("oald_senses will be created by CREATE_TABLES_SQL")

    # --- v3 → v4：definitions.phonetic（音标）---
    # 音标来自 data/dictionary.db 的 <pronunciation>，只有一部分词条带
    # （实测 136 词里 9 个）。它是**词目层的固有属性**，所以和别的标注字段一起
    # 放在 definitions 里，由灌库脚本写入；LLM 实时生成时不传该键，
    # 因而不会把灌库写入的音标抹成 NULL（与 cluster_id 用 COALESCE 同一个道理）。
    if not _column_exists(cursor, "definitions", "phonetic"):
        cursor.execute(
            "ALTER TABLE definitions ADD COLUMN phonetic VARCHAR(64) DEFAULT NULL"
        )
        summary["actions"].append("definitions.phonetic added")

    # --- v5 → v6：OALD 义项从 word_senses 拆出，独立成 oald_senses 表 ---
    #
    # 中间那版（v5）曾把 OALD 义项塞进 word_senses、按 source 列区分。实测下来
    # 合表的代价高过收益：两套切分体系无法一一对应，sense_index 混排后不再表达
    # 「同词目下第几条」，且一半的行 grammar / sense_group / is_idiom 恒为 NULL。
    # 现在按来源分表，这里把当时的过渡列**删掉**。
    #
    # DROP COLUMN 是会丢数据的方向，所以只在「确实存在这些过渡列」时才执行，
    # 且范围严格限定为 v5 新增的那 6 列 —— 不碰 word_senses 的原有列。
    # 新表由 CREATE_TABLES_SQL 建（它在迁移之前已跑过），迁移不重复建。
    for col in ("sense_group", "grammar", "example_patterns", "is_idiom",
                "headword", "prototype_is_first"):
        if _column_exists(cursor, "word_senses", col):
            cursor.execute(f"ALTER TABLE word_senses DROP COLUMN {col}")
            summary["actions"].append(f"word_senses.{col} dropped (moved to oald_senses)")

    if _index_exists(cursor, "word_senses", "idx_word_senses_idiom"):
        cursor.execute("ALTER TABLE word_senses DROP INDEX idx_word_senses_idiom")
        summary["actions"].append("idx_word_senses_idiom dropped")

    # 过渡期若曾把 OALD 行写进 word_senses，这里**不删它们**：迁移只做结构改造，
    # 不删业务数据 —— 迁移每次启动都跑，让它删数据等于给部署留了一个清库的开关。
    # 那些行是派生数据，下一次 `scripts/load_word_library.py` 的
    # `clear_all_word_data()` 会连同两个义项表一起重建，无需迁移代劳。
    # 只把情况记进 summary，让人从日志里知道「该重跑灌库了」。
    cursor.execute("SELECT COUNT(*) AS n FROM word_senses WHERE source = %s", ("OALD10",))
    stale = int(cursor.fetchone()["n"] or 0)
    if stale:
        summary["actions"].append(
            f"word_senses 有 {stale} 条 OALD 过渡行待灌库脚本重建（迁移不动它们）"
        )
        summary["stale_oald_rows"] = stale

    # --- v6 → v7：oald_senses.human_reviewed（人工复核标记）---
    #
    # needs_review 的预灌语义是「待人工复核」（灌库默认全 1），与标注平台上
    # 研究者主动打的「存疑边界案例」是两件事 —— 之前共用一列导致"存疑"指标
    # 恒等于总义位数。现在用 human_reviewed 记录"该义位已经人工标注保存过"，
    # needs_review 回归其本义：复核后仍存疑、需进仲裁清单。
    if not _column_exists(cursor, "oald_senses", "human_reviewed"):
        cursor.execute(
            "ALTER TABLE oald_senses ADD COLUMN "
            "human_reviewed TINYINT(1) NOT NULL DEFAULT 0"
        )
        summary["actions"].append("oald_senses.human_reviewed added")

    # --- 6. 记录版本 ---
    cursor.execute(
        """INSERT INTO schema_migrations (version, name) VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE name = VALUES(name)""",
        (SCHEMA_VERSION, "category study tables (categories/cs_*)"),
    )
    return summary


# ============================================
# 初始化数据库
# ============================================
def init_database(max_retries: int = 3, retry_delay: float = 2.0) -> bool:
    """
    Initialize MySQL database and create tables.

    Includes retry logic for Docker environments where MySQL may not be ready yet.

    Args:
        max_retries: Maximum number of connection attempts (default 3)
        retry_delay: Seconds to wait between retries (default 2.0)

    Returns:
        bool: True if successful, False if database is unavailable
    """
    import time

    if not PYMYSQL_AVAILABLE:
        logger.warning("PyMySQL not available, skipping MySQL initialization")
        return False

    for attempt in range(1, max_retries + 1):
        conn = None
        cursor = None
        try:
            # Create connection without database (to create it)
            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                charset=MYSQL_CHARSET,
                cursorclass=DictCursor
            )

            cursor = conn.cursor()

            # Create database if not exists（库名来自配置，反引号包裹：
            # 含连字符/保留字也不炸，且与全文件"标识符一律显式处理"的约定一致）
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                          f"CHARACTER SET {MYSQL_CHARSET} "
                          f"COLLATE {MYSQL_COLLATION}")
            logger.info(f"Database '{MYSQL_DATABASE}' ready")

            # Use the database
            cursor.execute(f"USE `{MYSQL_DATABASE}`")

            # 范畴深挖 8 表（v9）：注册进 CREATE_TABLES_SQL 再统一建表
            _register_category_study_tables()

            # Create tables
            for table_sql in CREATE_TABLES_SQL:
                cursor.execute(table_sql)
            logger.info("Database tables created successfully")

            # 结构迁移：把旧库（有 synonyms / statistics、definitions 无 cluster_id）
            # 升级到当前结构。幂等，可重复运行。
            # 必须跑在建视图之前：视图引用 definitions.cluster_id，而旧库要等迁移
            # 才补上这一列，否则 CREATE VIEW 会报 Unknown column。
            _migrate_schema(cursor)

            # 视图依赖迁移后的列，放在迁移之后
            for view_sql in CREATE_VIEWS_SQL:
                cursor.execute(view_sql)

            # 查询日志保留期：usage_logs 被 get_stats/get_hot_verbs 每次 rerun
            # 全表扫描，不清理会无限增长。启动时清一次 365 天前的记录。
            try:
                removed = clear_old_usage_logs(365)
                if removed:
                    logger.info(f"Cleaned {removed} usage_logs entries older than 365 days")
            except Exception as e:
                logger.warning(f"usage_logs retention skipped: {e}")

            return True

        except pymysql.Error as e:
            logger.warning(f"MySQL init attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error(f"MySQL initialization failed after {max_retries} attempts")
                return False
        except Exception as e:
            logger.warning(f"Unexpected error on attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                logger.error(f"MySQL initialization failed after {max_retries} attempts")
                return False
        finally:
            # 失败重试路径也要释放连接 —— 之前只有成功路径才 close，
            # 最多连漏 3 条 socket 等服务端超时。
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    return False


# ============================================
# 数据库连接池
# ============================================
# ============================================
# 连接池（真实实现）
# ============================================
# 之前这里的"池"只是一个空列表，get_db_cursor 每次都新建 TCP 连接 +
# 完成一次 auth 握手 —— Streamlit 每次交互重跑脚本，侧栏统计就要开 2-3 条
# 新连接。现在用 LifoQueue 维护复用连接：取出时 ping(reconnect=True) 保活，
# 用完归还；线程安全（多 session 并发各自独占取出的连接）。
import queue as _queue
import threading as _threading

_connection_pools: dict = {}
_pool_lock = _threading.Lock()

# 会话时区：TIMESTAMP 列的读写都按它换算。容器默认 UTC，而应用用户在
# UTC+8 —— 不固定时区会让"今日查询次数"在每天 0:00-8:00 之间算错。
MYSQL_TIME_ZONE = os.getenv("MYSQL_TIME_ZONE", "+08:00")


def _pool_key():
    """池按键区分（host, port, db, user）—— 测试会 monkeypatch MYSQL_DATABASE
    指向迁移测试库，键隔离保证不会把测试库的连接还给业务库的池里复用。"""
    return (MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER)


def get_connection_pool():
    """获取（或惰性创建）当前配置对应的连接池。返回 None 表示 PyMySQL 不可用。"""
    key = _pool_key()

    if not PYMYSQL_AVAILABLE:
        return None

    with _pool_lock:
        pool = _connection_pools.get(key)
        if pool is None:
            pool = _queue.LifoQueue(maxsize=10)
            _connection_pools[key] = pool
    return pool


def _new_connection(autocommit: bool = True):
    """新建一条连接（统一出口，便于集中设置会话参数）。"""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset=MYSQL_CHARSET,
        cursorclass=DictCursor,
        autocommit=autocommit,
        init_command=f"SET time_zone = '{MYSQL_TIME_ZONE}'" if MYSQL_TIME_ZONE else None,
    )


@contextmanager
def get_db_cursor(autocommit: bool = True):
    """
    Context manager for database cursor.

    Yields:
        DictCursor or None if database unavailable

    autocommit=False 时，退出 with 块自动 commit；异常路径自动 rollback。
    供"先删后插"的多语句写操作使用，保证原子性。
    """
    conn = None
    cursor = None

    try:
        pool = get_connection_pool()
        if pool is not None:
            try:
                conn = pool.get_nowait()
                conn.ping(reconnect=True)  # 复用前保活：服务端超时断开则重连
            except _queue.Empty:
                conn = None
            except pymysql.Error:
                # 取出的连接已死且重连失败：丢弃，走新建
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = None
        if conn is None:
            conn = _new_connection(autocommit=autocommit)
        else:
            conn.autocommit(autocommit)
        cursor = conn.cursor()

        yield cursor

        if not autocommit:
            conn.commit()

    except pymysql.Error as e:
        if conn and not autocommit:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        if conn and not autocommit:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"Unexpected error: {e}")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            pool = get_connection_pool()
            if pool is not None and not pool.full():
                try:
                    pool.put_nowait(conn)
                    conn = None
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


# ============================================
# Definitions CRUD Operations
# ============================================
# insert_definition 里允许由调用方写入的**标注字段**。
#
# 为什么用白名单 + 动态拼列名：这些字段（意象图式、对齐等级、释义来源…）只有灌库脚本
# 会传，而 LLM 实时生成路径一个都不传。若把它们写成固定的 `VALUES(col)`，实时生成时
# 会拿 NULL 去覆盖灌库建立的标注 —— 与 cluster_id 当初踩的是同一个坑。
# 白名单同时挡住了列名注入（列名无法参数化，只能拼接）。
_ANNOTATION_COLUMNS = (
    "en_ndef",
    "phonetic",
    "levin_source",
    "cross_subclass",
    "sense_brief",
    "judge_reason",
    "image_schema",
    "prototype_level",
    "alignment",
    "cn_syntax",
    "translation_strategy",
    "definition_source",
    "source_rank",
    "sense_count",
    "needs_review",
    "prototype_is_first",
)


def insert_definition(verb: str, chinese_ndef: str, semantic_table: Dict[str, str],
                       example_sentence: Optional[str] = None,
                       model_version: str = "zhipu-glm-4",
                       cluster_id: Optional[int] = None,
                       annotations: Optional[Dict[str, Any]] = None) -> bool:
    """
    Insert or update a verb definition.

    Args:
        verb: The verb to define
        chinese_ndef: Chinese definition text
        semantic_table: Dictionary of semantic components (manner, direction, aspect, etc.)
        example_sentence: Example sentence
        model_version: Model version used for generation
        cluster_id: 所属词义簇 id（见 word_clusters）。为 None 时不覆盖已有值 ——
            LLM 实时生成释义时并不知道词库的簇划分，若把它写成 NULL 会把灌库
            脚本已经建立的簇归属抹掉。
        annotations: 义位层面的标注字段（见 ``_ANNOTATION_COLUMNS``）。
            同样的语义：**只更新显式传入的键，未传的键保持库中现值**。
            LLM 实时生成时不传，于是不会抹掉灌库脚本写入的标注。

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            semantic_json = json.dumps(semantic_table, ensure_ascii=False)

            cols = ["verb", "chinese_ndef", "semantic_table",
                    "example_sentence", "model_version", "cluster_id"]
            params: List[Any] = [verb, chinese_ndef, semantic_json,
                                 example_sentence, model_version, cluster_id]

            updates = [
                "chinese_ndef = VALUES(chinese_ndef)",
                "semantic_table = VALUES(semantic_table)",
                # 例句为空时不覆盖 —— LLM 路径常带空 example，别把库里已有的
                # 真实例句冲掉
                ("example_sentence = COALESCE(NULLIF(VALUES(example_sentence), ''),"
                 " example_sentence)"),
                "model_version = VALUES(model_version)",
                "cluster_id = COALESCE(VALUES(cluster_id), cluster_id)",
            ]

            for key, value in (annotations or {}).items():
                if key not in _ANNOTATION_COLUMNS:
                    logger.warning(f"忽略未知标注字段: {key}")
                    continue
                cols.append(key)
                params.append(value)
                # 只更新显式传入的键
                updates.append(f"{key} = VALUES({key})")

            updates.append("updated_at = CURRENT_TIMESTAMP")

            placeholders = ", ".join(["%s"] * len(cols))
            cursor.execute(
                f"""INSERT INTO definitions ({", ".join(cols)})
                    VALUES ({placeholders})
                    ON DUPLICATE KEY UPDATE {", ".join(updates)}""",
                tuple(params),
            )

            logger.info(f"Definition inserted/updated for verb: {verb}")
            return True

    except pymysql.Error as e:
        logger.error(f"Failed to insert definition for '{verb}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error inserting definition: {e}")
        return False


def replace_word_senses(definition_id: int, senses: List[Dict[str, Any]]) -> int:
    """
    整体替换某个动词的义位明细（先删后插，幂等）。

    与 ``replace_word_relations`` 同样的取舍：义位是**派生数据**（由 dictionary.db 或
    OALD xlsx 现场解析而来），整表替换比逐行 diff 简单且绝不会留下孤儿行。
    用 DELETE-all 而不是 TRUNCATE，因为事务里 TRUNCATE 会隐式提交。

    本表只装 ``data/dictionary.db`` 的中英对照义位。OALD10 的英文义项粒度不同
    （带语法码与语义分组），单独放在 ``oald_senses`` 表 —— 理由见该表的建表注释。

    Args:
        definition_id: ``definitions.id``
        senses: 义位列表，每项含 sense_index / ch_ndef / prototype_level 等

    Returns:
        实际写入的行数；失败返回 0
    """
    try:
        # 先删后插必须原子：中途失败不能留下"义位被删光"的中间态
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "DELETE FROM word_senses WHERE definition_id = %s", (definition_id,)
            )
            if not senses:
                return 0

            rows = [
                (
                    definition_id,
                    s.get("sense_index", i + 1),
                    s.get("en_ndef"),
                    s.get("ch_ndef"),
                    s.get("construction"),
                    json.dumps(s.get("examples") or [], ensure_ascii=False),
                    json.dumps(s.get("ch_examples") or [], ensure_ascii=False),
                    json.dumps(s.get("synonyms") or [], ensure_ascii=False),
                    json.dumps(s.get("antonyms") or [], ensure_ascii=False),
                    s.get("prototype_level"),
                    s.get("image_schema"),
                    s.get("alignment"),
                    s.get("cn_syntax"),
                    s.get("translation_strategy"),
                    s.get("source"),
                    int(s.get("needs_review") or 0),
                )
                for i, s in enumerate(senses)
            ]

            cursor.executemany(
                """INSERT INTO word_senses
                       (definition_id, sense_index, en_ndef, ch_ndef, construction,
                        examples, ch_examples, synonyms, antonyms,
                        prototype_level, image_schema, alignment,
                        cn_syntax, translation_strategy, source, needs_review)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s)""",
                rows,
            )
            return len(rows)

    except pymysql.Error as e:
        logger.error(f"Failed to replace senses for definition {definition_id}: {e}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error replacing senses: {e}")
        return 0


def replace_oald_senses(definition_id: int, senses: List[Dict[str, Any]]) -> int:
    """
    整体替换某个动词的 OALD10 义项（先删后插，幂等）。

    与 ``replace_word_senses`` 同样的取舍：义项是派生数据（由 OALD xlsx 现场解析），
    整表替换比逐行 diff 简单且不会留下孤儿行。用 DELETE-all 而不是 TRUNCATE，
    因为事务里 TRUNCATE 会隐式提交。

    Returns:
        实际写入的行数；失败返回 0
    """
    try:
        # 先删后插必须原子
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "DELETE FROM oald_senses WHERE definition_id = %s", (definition_id,)
            )
            if not senses:
                return 0

            rows = [
                (
                    definition_id,
                    s.get("sense_index", i + 1),
                    s.get("en_ndef"),
                    s.get("grammar"),
                    s.get("sense_group"),
                    json.dumps(s.get("examples") or [], ensure_ascii=False),
                    json.dumps(s.get("example_patterns") or [], ensure_ascii=False),
                    int(s.get("is_idiom") or 0),
                    s.get("headword"),
                    s.get("prototype_level"),
                    s.get("image_schema"),
                    s.get("alignment"),
                    s.get("cn_syntax"),
                    s.get("translation_strategy"),
                    s.get("source") or "OALD10",
                    int(s.get("needs_review") or 0),
                )
                for i, s in enumerate(senses)
            ]

            cursor.executemany(
                """INSERT INTO oald_senses
                       (definition_id, sense_index, definition, grammar, sense_group,
                        examples, example_patterns, is_idiom, headword,
                        prototype_level, image_schema, alignment,
                        cn_syntax, translation_strategy, source, needs_review)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s)""",
                rows,
            )
            return len(rows)

    except pymysql.Error as e:
        logger.error(f"Failed to replace OALD senses for definition {definition_id}: {e}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error replacing OALD senses: {e}")
        return 0


def _parse_json_columns(rows: List[Dict[str, Any]], fields: tuple) -> List[Dict[str, Any]]:
    """把 JSON 列从字符串解析成 Python 对象；坏值归一成空列表而不是 None。"""
    for row in rows:
        for field in fields:
            value = row.get(field)
            if isinstance(value, str):
                try:
                    row[field] = json.loads(value)
                except json.JSONDecodeError:
                    row[field] = []
    return rows


def get_oald_senses(verb: str, limit: int = 200) -> List[Dict[str, Any]]:
    """
    取某个动词的 OALD10 义项（英文，带语法码与语义分组）。

    Args:
        verb: 动词原形
        limit: 上限。默认 200 —— 最多的 run 有 39 条，等于无上限，同时兜住异常数据。

    Returns:
        义项列表，``examples`` / ``example_patterns`` 已解析成列表。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.*,
                          df.llm_tag, df.llm_schema, df.llm_align,
                          df.llm_reason, df.llm_doubt
                   FROM oald_senses s
                   JOIN definitions d ON d.id = s.definition_id
                   LEFT JOIN domain_family_senses df
                          ON df.word = d.verb AND df.sense_num = s.sense_index
                   WHERE d.verb = %s
                   ORDER BY s.sense_index
                   LIMIT %s""",
                (verb, limit),
            )
            rows = cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"Failed to fetch OALD senses for '{verb}': {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching OALD senses: {e}")
        return []

    return _parse_json_columns(rows, ("examples", "example_patterns"))


def get_all_senses(verb: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    一次取回某个动词的**两个来源**的义项。

    分两张表存的代价集中在这里：调用方（页面、文档生成）只要用这一个函数，
    就不必知道有两个来源、更不必自己 UNION。键名固定为两个来源名。
    """
    return {
        "word_senses": get_senses(verb),
        "oald_senses": get_oald_senses(verb),
    }


def get_senses(verb: str, limit: int = 200) -> List[Dict[str, Any]]:
    """
    取某个动词的 dictionary.db 义位明细（中英对照），供页面展示与文档生成。

    OALD 义项在 ``get_oald_senses``；要两个来源一起取用 ``get_all_senses``。

    Args:
        verb: 动词原形
        limit: 上限。默认 200 —— go 的义位有 38 条，历史上默认 50 会**静默截断**
            而看不出被截了；给到 200 对当前数据（最多 62）等于无上限，同时仍兜住异常数据。

    Returns:
        义项列表，JSON 列已解析成 Python 对象（坏值归一成空列表）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.* FROM word_senses s
                   JOIN definitions d ON d.id = s.definition_id
                   WHERE d.verb = %s
                   ORDER BY s.sense_index
                   LIMIT %s""",
                (verb, limit),
            )
            rows = cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"Failed to fetch senses for '{verb}': {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching senses: {e}")
        return []

    return _parse_json_columns(rows, ("examples", "ch_examples", "synonyms", "antonyms"))


def get_definition_by_verb(verb: str) -> Optional[Dict[str, Any]]:
    """
    Get definition by verb name.

    Args:
        verb: The verb to look up

    Returns:
        Dictionary containing definition data or None if not found
    """
    try:
        with get_db_cursor() as cursor:
            # 连 word_clusters 取簇信息，供界面显示「该词属于哪个语义簇」
            cursor.execute("""
                SELECT d.*,
                       c.label AS cluster_label,
                       c.main_cat AS cluster_main_cat,
                       c.sub_cat AS cluster_sub_cat,
                       c.size AS cluster_size,
                       c.image_schema AS cluster_image_schema
                FROM definitions d
                LEFT JOIN word_clusters c ON c.id = d.cluster_id
                WHERE d.verb = %s
                ORDER BY d.created_at DESC
                LIMIT 1
            """, (verb,))

            row = cursor.fetchone()
            if row:
                # Parse JSON semantic table
                semantic_table = json.loads(row['semantic_table']) if isinstance(row['semantic_table'], str) else row['semantic_table']
                return {
                    'verb': row['verb'],
                    'chinese_ndef': row['chinese_ndef'],
                    'semantic_table': semantic_table,
                    'example_sentence': row['example_sentence'],
                    'model_version': row['model_version'],
                    'cluster_id': row['cluster_id'],
                    'cluster_label': row['cluster_label'],
                    'cluster_sub_cat': row['cluster_sub_cat'],
                    'cluster_size': row['cluster_size'],
                    'cluster_image_schema': row.get('cluster_image_schema'),
                    # --- v3 义位标注字段（来源见 docs/义项判定标准.docx）---
                    'en_ndef': row.get('en_ndef'),
                    'levin_source': row.get('levin_source'),
                    'cross_subclass': row.get('cross_subclass'),
                    'sense_brief': row.get('sense_brief'),
                    'judge_reason': row.get('judge_reason'),
                    'image_schema': row.get('image_schema'),
                    'prototype_level': row.get('prototype_level'),
                    'alignment': row.get('alignment'),
                    'cn_syntax': row.get('cn_syntax'),
                    'translation_strategy': row.get('translation_strategy'),
                    'definition_source': row.get('definition_source'),
                    'source_rank': row.get('source_rank'),
                    'sense_count': row.get('sense_count'),
                    'needs_review': row.get('needs_review'),
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            return None

    except pymysql.Error as e:
        logger.error(f"Failed to get definition for '{verb}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting definition: {e}")
        return None


def get_all_definitions(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get all definitions from the database.

    Args:
        limit: Maximum number of definitions to return

    Returns:
        List of definition dictionaries
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM definitions
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                semantic_table = json.loads(row['semantic_table']) if isinstance(row['semantic_table'], str) else row['semantic_table']
                results.append({
                    'verb': row['verb'],
                    'chinese_ndef': row['chinese_ndef'],
                    'semantic_table': semantic_table,
                    'example_sentence': row['example_sentence'],
                    'model_version': row['model_version'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                })
            return results

    except pymysql.Error as e:
        logger.error(f"Failed to get all definitions: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting all definitions: {e}")
        return []


# ============================================
# 词义簇与词间关系
# ============================================
def get_or_create_cluster(main_cat: str, sub_cat: str, label: str = None,
                           image_schema: str = None, cn_syntax: str = None,
                           translation_strategy: str = None) -> Optional[int]:
    """
    取回词义簇 id，不存在则创建。

    簇的唯一键是 (main_cat, sub_cat)，对应 `docs/Levin移动动词候选词筛选表.xlsx`
    的「主范畴 / 次类」两列。

    簇层面的 `image_schema` / `cn_syntax` / `translation_strategy` **只在非空时覆盖**：
    这里跟 definitions 的标注字段同一个取舍 —— 同一簇的所有成员共享一套图式与句法
    特征，但调用方不传时不该把已有值抹成 NULL。

    Args:
        main_cat: 主范畴，如「方式聚焦型」
        sub_cat: 次类，如「陆地行进类」
        label: 展示名，默认 "main_cat / sub_cat"
        image_schema: 该簇的意象图式（取值见标准 2 的四类）
        cn_syntax: 该簇的汉语句法特征
        translation_strategy: 该簇的译义转化策略

    Returns:
        簇 id；数据库不可用时返回 None
    """
    if not main_cat or not sub_cat:
        return None
    label = label or f"{main_cat} / {sub_cat}"

    updates = ["label = VALUES(label)", "id = LAST_INSERT_ID(id)"]
    params: List[Any] = [main_cat, sub_cat, label,
                         image_schema, cn_syntax, translation_strategy]
    for col, value in (("image_schema", image_schema),
                       ("cn_syntax", cn_syntax),
                       ("translation_strategy", translation_strategy)):
        if value:
            updates.append(f"{col} = VALUES({col})")

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""INSERT INTO word_clusters
                        (main_cat, sub_cat, label, image_schema, cn_syntax, translation_strategy)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE {", ".join(updates)}""",
                tuple(params),
            )
            cursor.execute(
                "SELECT id FROM word_clusters WHERE main_cat = %s AND sub_cat = %s",
                (main_cat, sub_cat),
            )
            row = cursor.fetchone()
            return int(row["id"]) if row else None
    except pymysql.Error as e:
        logger.error(f"Failed to get/create cluster {main_cat}/{sub_cat}: {e}")
        return None


def prune_empty_clusters() -> int:
    """
    删除没有任何成员的词簇，返回删除数量。

    为什么需要：切换分类体系（旧的 25 个 sub_cat → Levin 的 12 个次类）之后，
    旧簇会全部变成空壳。留着它们会让页面上的「切换词簇」下拉框出现一堆 0 词选项，
    也会让 get_full_word_graph 报出错误的簇数。

    只删空簇，绝不删有成员的 —— 这个函数的失败模式必须是「少删」而不是「多删」。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT id FROM word_clusters")
            all_ids = [int(r["id"]) for r in cursor.fetchall()]
            cursor.execute(
                "SELECT DISTINCT cluster_id FROM definitions WHERE cluster_id IS NOT NULL"
            )
            used = {int(r["cluster_id"]) for r in cursor.fetchall()}
            stale = [i for i in all_ids if i not in used]
            if stale:
                placeholders = ", ".join(["%s"] * len(stale))
                cursor.execute(
                    f"DELETE FROM word_clusters WHERE id IN ({placeholders})",
                    tuple(stale),
                )
            return len(stale)
    except pymysql.Error as e:
        logger.error(f"Failed to prune empty clusters: {e}")
        return 0


def clear_all_word_data() -> Dict[str, int]:
    """
    清空词表相关数据（定义 / 义位 / 关系 / 簇），**保留 feedbacks 与 usage_logs**。

    为什么需要：分类体系变更时，旧的簇归属与由此推导的关系边都是**派生数据**，
    必须整体重建而不能就地增量 —— 否则新旧两套次类会混在一张图上，得到自相矛盾的
    结果（旧簇 25 个里有的只剩 1 个成员，新簇 12 个）。

    为什么保留 feedbacks / usage_logs：它们是**用户产生的**，不是派生数据，
    而且以 verb 字符串而非外键关联，删词表不该连带删掉它们。

    Returns:
        各表删除行数
    """
    removed: Dict[str, int] = {}
    try:
        # 整体清库必须原子：多张表要么一起清掉，要么都不动
        with get_db_cursor(autocommit=False) as cursor:
            for table in ("word_relations", "oald_senses", "word_senses"):
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
                removed[table] = int(cursor.fetchone()["n"] or 0)
                cursor.execute(f"DELETE FROM {table}")

            cursor.execute("SELECT COUNT(*) AS n FROM definitions")
            removed["definitions"] = int(cursor.fetchone()["n"] or 0)
            cursor.execute("DELETE FROM definitions")

            cursor.execute("SELECT COUNT(*) AS n FROM word_clusters")
            removed["word_clusters"] = int(cursor.fetchone()["n"] or 0)
            cursor.execute("DELETE FROM word_clusters")
    except pymysql.Error as e:
        logger.error(f"Failed to clear word data: {e}")
    except Exception as e:
        logger.error(f"Unexpected error clearing word data: {e}")
    return removed


def refresh_cluster_sizes() -> int:
    """重算每个簇的 size 字段（簇成员数）。返回更新的簇数。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """UPDATE word_clusters c
                   SET c.size = (
                       SELECT COUNT(*) FROM definitions d WHERE d.cluster_id = c.id
                   )"""
            )
            return cursor.rowcount
    except pymysql.Error as e:
        logger.error(f"Failed to refresh cluster sizes: {e}")
        return 0


def replace_word_relations(relations: List[tuple]) -> int:
    """
    整批替换词间关系（簇内完全图）。

    为什么是「替换」而不是「累加」：完全图是**推导出来的完整集合** —— 词库改了、
    簇划分变了，旧边就成了错误数据。继续累加会留下自相矛盾的图。所以每次灌库先清空
    word_relations 再重建，保证 DB 里的图恒等于词库推出来的那张图。

    Args:
        relations: [(verb_a, verb_b, relation, cluster_label), ...]，
                   verb_a < verb_b（无向边只存一份）

    Returns:
        实际写入的边数
    """
    if not relations:
        return 0
    try:
        # 清空重建必须原子：中途失败不能留下一张空图
        with get_db_cursor(autocommit=False) as cursor:
            # 动词名 -> id 映射（一次查完，避免 N 次单查）
            cursor.execute("SELECT id, verb FROM definitions")
            verb_ids = {row["verb"]: row["id"] for row in cursor.fetchall()}

            cursor.execute("SELECT id, label FROM word_clusters")
            cluster_ids = {row["label"]: row["id"] for row in cursor.fetchall()}

            cursor.execute("DELETE FROM word_relations")

            rows = []
            skipped = 0
            for a, b, relation, cluster_label in relations:
                id_a, id_b = verb_ids.get(a), verb_ids.get(b)
                if id_a is None or id_b is None:
                    skipped += 1
                    continue
                # CHECK 约束要求 a < b；调用方理应已排序，这里再兜一层
                if id_a > id_b:
                    id_a, id_b = id_b, id_a
                rows.append((id_a, id_b, relation, cluster_ids.get(cluster_label)))

            if rows:
                cursor.executemany(
                    """INSERT INTO word_relations
                       (verb_a_id, verb_b_id, relation, cluster_id)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE relation = VALUES(relation)""",
                    rows,
                )
            if skipped:
                logger.warning(f"{skipped} 条关系引用了库里不存在的动词，已跳过")
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to replace word relations: {e}")
        return 0


def get_synonyms(verb: str) -> List[str]:
    """
    取某动词的近义动词（同簇的全部其他成员）。

    Args:
        verb: 动词

    Returns:
        近义动词列表；词不存在或库不可用时为空列表
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT other.verb AS verb
                   FROM definitions me
                   JOIN definitions other
                        ON other.cluster_id = me.cluster_id AND other.id <> me.id
                   WHERE me.verb = %s AND me.cluster_id IS NOT NULL
                   ORDER BY other.verb""",
                (verb,),
            )
            return [row["verb"] for row in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"Failed to get synonyms for '{verb}': {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting synonyms: {e}")
        return []


def _build_cluster_graph(cursor, cluster_id: int, center, max_members: int) -> Dict[str, Any]:
    """
    给定簇 id，组装完全图结构。get_cluster_graph / get_cluster_graph_by_id 共用。

    Args:
        cursor: 已打开的游标
        cluster_id: 词簇 id
        center: 中心词（可不在该簇内，此时不标记 is_center）
        max_members: 参与绘制的最大成员数

    Returns:
        见 get_cluster_graph 的 Returns 说明
    """
    cursor.execute(
        """SELECT id, label, sub_cat, main_cat, size
           FROM word_clusters WHERE id = %s""",
        (cluster_id,),
    )
    cluster_row = cursor.fetchone()
    if not cluster_row:
        return {
            "center": center or "",
            "cluster": None,
            "nodes": [],
            "links": [],
            "truncated": False,
            "complete_edge_count": 0,
        }

    cursor.execute(
        """SELECT d.id, d.verb, d.chinese_ndef, d.en_ndef,
                  d.sense_brief, d.image_schema, d.example_sentence
           FROM definitions d
           WHERE d.cluster_id = %s ORDER BY d.verb""",
        (cluster_id,),
    )
    members = cursor.fetchall()

    full_size = len(members)
    truncated = full_size > max_members
    if truncated:
        # 稳定截断：中心词必留，其余按字母序取前 max_members-1 个
        others = [m for m in members if m["verb"] != center]
        keep = set()
        if center:
            keep.add(center)
        keep |= {m["verb"] for m in others[: max(0, max_members - len(keep))]}
        members = [m for m in members if m["verb"] in keep]

    nodes = [
        {
            "id": m["verb"],
            "label": m["verb"],
            "is_center": bool(center) and m["verb"] == center,
            "cluster_id": cluster_id,
            # 浮层卡片明细（与知识图谱页 nodeDetailHTML 同源字段）
            "chinese_ndef": m.get("chinese_ndef") or "",
            "en_ndef": m.get("en_ndef") or "",
            "sense_brief": m.get("sense_brief") or "",
            "image_schema": m.get("image_schema") or "",
            "example_sentence": m.get("example_sentence") or "",
            "sub_cat": cluster_row["sub_cat"],
        }
        for m in members
    ]

    # 簇内完全图：任意两成员一条边
    links = []
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            links.append(
                {"source": a["verb"], "target": b["verb"], "relation": "近义"}
            )

    return {
        "center": center or "",
        "cluster": {
            "id": cluster_id,
            "label": cluster_row["label"],
            "sub_cat": cluster_row["sub_cat"],
            "main_cat": cluster_row["main_cat"],
            # size 用簇的真实成员数（不是截断后的），否则页面会低报规模
            "size": int(cluster_row["size"] or full_size),
        },
        "nodes": nodes,
        "links": links,
        "truncated": truncated,
        # 完全图边数取**完整簇**的 C(n,2)，与 DB 中 word_relations 的边数一致
        "complete_edge_count": full_size * (full_size - 1) // 2,
    }


def get_cluster_graph(center: str, max_members: int = 200) -> Dict[str, Any]:
    """
    取「中心词 + 其所属词簇」的完全图，供页面用 graphify 风格可视化。

    返回结构刻意对齐 graphify 的 graph.json（nodes / links），这样页面渲染器与
    文件产物 `data/word_graph.json` 可以共用同一套前端代码。

    完全图的边数按 C(n,2) 增长：56 词的「常态行走」簇就是 1540 条边。max_members
    是安全阀（默认 200，远大于当前最大的 56 词簇，正常不会触发），触发时按字母序
    稳定截断并在返回值里用 truncated 标明，避免意外的超大簇把浏览器拖死。

    Args:
        center: 用户查询的动词
        max_members: 单簇参与绘制的最大成员数

    Returns:
        {
          "center": str,
          "cluster": {"id","label","sub_cat","main_cat","size"} | None,
          "nodes": [{"id","label","is_center","cluster_id"}],
          "links": [{"source","target","relation"}],
          "truncated": bool,
          "complete_edge_count": int,   # 完整簇的 C(n,2)
        }
    """
    empty = {
        "center": center or "",
        "cluster": None,
        "nodes": [],
        "links": [],
        "truncated": False,
        "complete_edge_count": 0,
    }
    if not center:
        return empty

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT cluster_id FROM definitions WHERE verb = %s LIMIT 1",
                (center,),
            )
            row = cursor.fetchone()
            if not row or row["cluster_id"] is None:
                return empty
            return _build_cluster_graph(cursor, row["cluster_id"], center, max_members)

    except pymysql.Error as e:
        logger.error(f"Failed to get cluster graph for '{center}': {e}")
        return empty
    except Exception as e:
        logger.error(f"Unexpected error building cluster graph: {e}")
        return empty


def get_cluster_graph_by_id(cluster_id: int, center: str = None,
                           max_members: int = 200) -> Dict[str, Any]:
    """
    按簇 id 直接取完全图 —— 这是页面上「切换簇」的入口。

    get_cluster_graph 只能从某个词反查它所在的簇，用户因此无法主动浏览别的簇，
    只能靠「先搜一个别的词」间接跳过去。这个函数让任意簇都能被直接打开。

    Args:
        cluster_id: 词簇 id（来自 list_clusters）
        center: 想要高亮的词；缺省或不在簇内时，取簇内字母序第一个词
        max_members: 单簇参与绘制的最大成员数

    Returns:
        与 get_cluster_graph 相同结构
    """
    empty = {
        "center": center or "",
        "cluster": None,
        "nodes": [],
        "links": [],
        "truncated": False,
        "complete_edge_count": 0,
    }
    try:
        with get_db_cursor() as cursor:
            graph = _build_cluster_graph(cursor, cluster_id, center, max_members)
        # 没传 center、或 center 不在簇内时，退化为簇内第一个词，
        # 保证图上总有一个被高亮的节点（否则用户看不出「从哪儿看起」）。
        if graph["nodes"] and not any(n["is_center"] for n in graph["nodes"]):
            first = graph["nodes"][0]["id"]
            graph["center"] = first
            for node in graph["nodes"]:
                node["is_center"] = node["id"] == first
        return graph
    except pymysql.Error as e:
        logger.error(f"Failed to get cluster graph for cluster {cluster_id}: {e}")
        return empty
    except Exception as e:
        logger.error(f"Unexpected error building cluster graph {cluster_id}: {e}")
        return empty


def list_clusters(limit: int = 500) -> List[Dict[str, Any]]:
    """
    列出所有词义簇（按成员数降序），供页面「切换簇」下拉框使用。

    Returns:
        [{"id","label","main_cat","sub_cat","size","edge_count"}, ...]
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT id, main_cat, sub_cat, label, size
                   FROM word_clusters
                   ORDER BY size DESC, label ASC
                   LIMIT %s""",
                (limit,),
            )
            rows = cursor.fetchall()
            out = []
            for row in rows:
                size = int(row["size"] or 0)
                out.append({
                    "id": row["id"],
                    "main_cat": row["main_cat"],
                    "sub_cat": row["sub_cat"],
                    "label": row["label"],
                    "size": size,
                    "edge_count": size * (size - 1) // 2,
                })
            return out
    except pymysql.Error as e:
        logger.error(f"Failed to list clusters: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error listing clusters: {e}")
        return []


# ============================================
# Feedbacks CRUD Operations
# ============================================
def _json_dict(value: Any) -> Dict[str, Any]:
    """把 JSON 列归一成 dict。pymysql 视配置返回 str 或已解析对象，两种都要能接。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "ignore")
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _json_list(value: Any) -> List[Any]:
    """把 JSON 列归一成 list；None / 坏值一律给空列表，避免前端拿到 null。"""
    if isinstance(value, list):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "ignore")
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


def get_full_word_graph() -> Dict[str, Any]:
    """
    取全库词间关系图：所有词 + 所有关系边（各簇完全图的并集）。

    这是给页面上的**交互式图谱**用的数据源 —— 形状刻意对齐 graphify 的
    graph.json（nodes / links + 每个节点的社区归属），这样前端的力导向渲染器
    可以直接套用同一套配置。

    与 get_cluster_graph 的区别：
      * get_cluster_graph —— 单个词的簇，节点几十个，用于「看清这个词跟谁近义」；
      * get_full_word_graph —— 整库 155 词 / 2143 边，用于「浏览全局语义地图」。

    nodes 里带 degree（度数），前端据此决定节点大小；带 cluster_label/sub_cat
    供图例分组与信息面板展示。

    Returns:
        {
          "nodes": [{"id","label","cluster_id","cluster_label","sub_cat",
                     "main_cat","degree"}],
          "links": [{"source","target","relation"}],
          "clusters": [{"id","label","sub_cat","size","edge_count"}],
          "stats": {"node_count","edge_count","cluster_count"},
        }
    """
    empty = {"nodes": [], "links": [], "clusters": [],
             "stats": {"node_count": 0, "edge_count": 0, "cluster_count": 0}}
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT d.verb, d.cluster_id,
                          d.chinese_ndef, d.en_ndef, d.phonetic,
                          d.semantic_table, d.example_sentence,
                          d.image_schema, d.prototype_level, d.alignment,
                          d.cn_syntax, d.translation_strategy,
                          d.definition_source, d.source_rank, d.sense_count,
                          d.sense_brief, d.judge_reason,
                          d.levin_source, d.cross_subclass,
                          d.needs_review, d.prototype_is_first,
                          c.label AS cluster_label, c.sub_cat AS sub_cat,
                          c.main_cat AS main_cat,
                          c.image_schema AS cluster_image_schema,
                          c.cn_syntax AS cluster_cn_syntax,
                          c.translation_strategy AS cluster_translation_strategy
                   FROM definitions d
                   LEFT JOIN word_clusters c ON c.id = d.cluster_id
                   ORDER BY d.verb"""
            )
            node_rows = cursor.fetchall()

            # 义位明细：只有一部分词有（实测 64 条覆盖 4 词），所以按 verb 归组后
            # 缺的词就是空列表 —— 卡片据此显示「该词没有中英对照义位」。
            cursor.execute(
                """SELECT d.verb, s.sense_index, s.ch_ndef, s.en_ndef,
                          s.construction, s.examples, s.ch_examples,
                          s.synonyms, s.antonyms,
                          s.image_schema, s.prototype_level, s.alignment,
                          s.cn_syntax, s.translation_strategy
                   FROM word_senses s
                   JOIN definitions d ON d.id = s.definition_id
                   ORDER BY d.verb, s.sense_index"""
            )
            sense_rows = cursor.fetchall()

            # OALD 义项覆盖 132/136 词，是卡片上义项信息的主力来源。
            # 与 word_senses 分开查、分开装 —— 两套切分体系不能混成一个列表。
            cursor.execute(
                """SELECT d.verb, s.sense_index, s.definition, s.grammar,
                          s.sense_group, s.examples, s.example_patterns,
                          s.is_idiom, s.prototype_level
                   FROM oald_senses s
                   JOIN definitions d ON d.id = s.definition_id
                   ORDER BY d.verb, s.sense_index"""
            )
            oald_rows = cursor.fetchall()

            cursor.execute(
                """SELECT a.verb AS source, b.verb AS target, r.relation
                   FROM word_relations r
                   JOIN definitions a ON a.id = r.verb_a_id
                   JOIN definitions b ON b.id = r.verb_b_id"""
            )
            link_rows = cursor.fetchall()

            cursor.execute(
                "SELECT id, label, sub_cat, size FROM word_clusters ORDER BY size DESC, label"
            )
            cluster_rows = cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"Failed to build full word graph: {e}")
        return empty
    except Exception as e:
        logger.error(f"Unexpected error building full word graph: {e}")
        return empty

    links = [
        {"source": r["source"], "target": r["target"], "relation": r["relation"]}
        for r in link_rows
    ]

    # 度数 = 该词在图上的连边数。簇内完全图下它恒等于 (簇大小-1)，
    # 所以节点大小实际表达的是「这个词的语义簇有多大」。
    degree = {r["verb"]: 0 for r in node_rows}
    for link in links:
        if link["source"] in degree:
            degree[link["source"]] += 1
        if link["target"] in degree:
            degree[link["target"]] += 1

    senses_by_verb: Dict[str, List[Dict[str, Any]]] = {}
    for r in sense_rows:
        senses_by_verb.setdefault(r["verb"], []).append({
            "sense_index": r["sense_index"],
            "ch_ndef": r["ch_ndef"] or "",
            "en_ndef": r["en_ndef"] or "",
            "construction": r["construction"] or "",
            "examples": _json_list(r["examples"]),
            "ch_examples": _json_list(r["ch_examples"]),
            "synonyms": _json_list(r["synonyms"]),
            "antonyms": _json_list(r["antonyms"]),
            "image_schema": r["image_schema"] or "",
            "prototype_level": r["prototype_level"] or "",
            "alignment": r["alignment"] or "",
            "cn_syntax": r["cn_syntax"] or "",
        })

    oald_by_verb: Dict[str, List[Dict[str, Any]]] = {}
    for r in oald_rows:
        oald_by_verb.setdefault(r["verb"], []).append({
            "sense_index": r["sense_index"],
            "definition": r["definition"] or "",
            "grammar": r["grammar"] or "",
            "sense_group": r["sense_group"] or "",
            "examples": _json_list(r["examples"]),
            "example_patterns": _json_list(r["example_patterns"]),
            "is_idiom": int(r["is_idiom"] or 0),
            "prototype_level": r["prototype_level"] or "",
        })

    nodes = [
        {
            "id": r["verb"],
            "label": r["verb"],
            "cluster_id": r["cluster_id"],
            "cluster_label": r["cluster_label"] or "未分组",
            "sub_cat": r["sub_cat"] or "未分组",
            "main_cat": r["main_cat"] or "",
            "degree": degree.get(r["verb"], 0),
            # --- 卡片用的明细字段（图谱渲染不读，但信息面板与浮层卡片要）---
            "chinese_ndef": r["chinese_ndef"] or "",
            "en_ndef": r["en_ndef"] or "",
            "phonetic": r["phonetic"] or "",
            "semantic_table": _json_dict(r["semantic_table"]),
            "example_sentence": r["example_sentence"] or "",
            "image_schema": r["image_schema"] or "",
            "prototype_level": r["prototype_level"] or "",
            "alignment": r["alignment"] or "",
            "cn_syntax": r["cn_syntax"] or "",
            "translation_strategy": r["translation_strategy"] or "",
            "definition_source": r["definition_source"] or "",
            "source_rank": r["source_rank"],
            "sense_count": r["sense_count"] or 0,
            "sense_brief": r["sense_brief"] or "",
            "judge_reason": r["judge_reason"] or "",
            "levin_source": r["levin_source"] or "",
            "cross_subclass": r["cross_subclass"] or "",
            "needs_review": int(r["needs_review"] or 0),
            "prototype_is_first": r["prototype_is_first"],
            "cluster_image_schema": r["cluster_image_schema"] or "",
            "cluster_cn_syntax": r["cluster_cn_syntax"] or "",
            "cluster_translation_strategy": r["cluster_translation_strategy"] or "",
            "senses": senses_by_verb.get(r["verb"], []),
            "oald_senses": oald_by_verb.get(r["verb"], []),
        }
        for r in node_rows
    ]

    clusters = []
    for r in cluster_rows:
        size = int(r["size"] or 0)
        clusters.append({
            "id": r["id"],
            "label": r["label"],
            "sub_cat": r["sub_cat"],
            "size": size,
            "edge_count": size * (size - 1) // 2,
        })

    return {
        "nodes": nodes,
        "links": links,
        "clusters": clusters,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(links),
            "cluster_count": len(clusters),
        },
    }


def insert_feedback(verb: str, rating: int, feedback_text: Optional[str] = None) -> bool:
    """
    Insert user feedback.

    Args:
        verb: The verb that was queried
        rating: User rating (1-5)
        feedback_text: Optional feedback text

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO feedbacks (verb, rating, feedback_text) VALUES (%s, %s, %s)",
                (verb, rating, feedback_text)
            )

            logger.info(f"Feedback inserted for '{verb}': rating={rating}")
            return True

    except pymysql.Error as e:
        logger.error(f"Failed to insert feedback for '{verb}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error inserting feedback: {e}")
        return False


def get_feedback_by_verb(verb: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get feedback for a specific verb.

    Args:
        verb: The verb to get feedback for
        limit: Maximum number of feedback entries to return

    Returns:
        List of feedback dictionaries
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM feedbacks WHERE verb = %s ORDER BY created_at DESC LIMIT %s",
                (verb, limit)
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    except pymysql.Error as e:
        logger.error(f"Failed to get feedback for '{verb}': {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting feedback: {e}")
        return []


def get_feedback_data() -> List[Dict[str, Any]]:
    """
    Get all feedback data.

    Returns:
        List of all feedback dictionaries
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM feedbacks ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    except pymysql.Error as e:
        logger.error(f"Failed to get feedback data: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting feedback data: {e}")
        return []


# ============================================
# Statistics Operations
# ============================================
def get_stats() -> Dict[str, Any]:
    """
    Get database statistics.

    统计口径（2026-09 修正）：
      * total_queries  —— 真实查询次数，来自 usage_logs 表（每次用户搜索都会
        log_usage 记一笔）。修正前这里统计的是 definitions 表的行数，也就是
        「已收录词条数」，被当成「总查询次数」显示，属于口径错误。
      * total_definitions —— 已收录词条数，单独返回，不再冒充查询数。
      * queries_today —— 今天的查询次数，用于侧边栏的当日增量。
      * total_clusters / total_relations —— 词义簇数与词间关系边数（结构指标）。

    Returns:
        Dictionary containing statistics
    """
    empty = {
        "total_queries": 0,
        "queries_today": 0,
        "total_definitions": 0,
        "avg_rating": 0.0,
        "total_feedbacks": 0,
        "total_clusters": 0,
        "total_relations": 0,
    }
    try:
        with get_db_cursor() as cursor:
            # 真实查询次数（来自查询日志）
            cursor.execute("SELECT COUNT(*) AS n FROM usage_logs")
            total_queries = int(cursor.fetchone()['n'] or 0)

            # 今日查询次数 —— 用 sargable 范围谓词（不用 DATE() 包列），
            # 会话时区已在连接 init_command 固定为应用时区
            cursor.execute(
                "SELECT COUNT(*) AS n FROM usage_logs "
                "WHERE query_time >= CURDATE() "
                "  AND query_time < CURDATE() + INTERVAL 1 DAY"
            )
            queries_today = int(cursor.fetchone()['n'] or 0)

            # 已收录词条数（与查询次数分开，避免口径混淆）
            cursor.execute("SELECT COUNT(*) AS n FROM definitions")
            total_definitions = int(cursor.fetchone()['n'] or 0)

            # Average rating
            cursor.execute("SELECT COALESCE(AVG(rating), 0) AS avg_rating FROM feedbacks")
            avg_rating = round(float(cursor.fetchone()['avg_rating']), 1)

            # Total feedbacks
            cursor.execute("SELECT COUNT(*) AS n FROM feedbacks")
            total_feedbacks = int(cursor.fetchone()['n'] or 0)

            # 词义簇数量（结构指标，反映词库覆盖的语义分组数）
            cursor.execute("SELECT COUNT(*) AS n FROM word_clusters")
            total_clusters = int(cursor.fetchone()['n'] or 0)

            # 词间关系边数（= 各簇完全图边数之和）
            cursor.execute("SELECT COUNT(*) AS n FROM word_relations")
            total_relations = int(cursor.fetchone()['n'] or 0)

            return {
                "total_queries": total_queries,
                "queries_today": queries_today,
                "total_definitions": total_definitions,
                "avg_rating": avg_rating,
                "total_feedbacks": total_feedbacks,
                "total_clusters": total_clusters,
                "total_relations": total_relations,
            }

    except pymysql.Error as e:
        logger.error(f"Failed to get statistics: {e}")
        return empty
    except Exception as e:
        logger.error(f"Unexpected error getting statistics: {e}")
        return empty


def get_hot_verbs(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get hot verbs based on **real query frequency**.

    修正前这里按 definitions 表的行数排序（d.verb, COUNT(d.id)），definitions
    每个动词只有一行，所以「热度」恒等于 1，排序实际由 LIMIT 前的物理顺序决定，
    根本不是热门查询。现在以 usage_logs 的查询次数为准，并用待查词的原词形
    关联 definitions/feedbacks 取评分。

    Args:
        limit: Maximum number of verbs to return

    Returns:
        List of hot verb dictionaries with count and average rating
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT u.verb,
                       COUNT(*) AS count,
                       COALESCE((
                           SELECT AVG(f.rating) FROM feedbacks f WHERE f.verb = u.verb
                       ), 0) AS avg_rating
                FROM usage_logs u
                GROUP BY u.verb
                ORDER BY count DESC, u.verb ASC
                LIMIT %s
            """, (limit,))

            rows = cursor.fetchall()
            return [
                {
                    'verb': row['verb'],
                    'count': int(row['count']),
                    'avg_rating': round(float(row['avg_rating']), 1)
                }
                for row in rows
            ]

    except pymysql.Error as e:
        logger.error(f"Failed to get hot verbs: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting hot verbs: {e}")
        return []


def log_usage(verb: str, device_info: Optional[str] = None) -> bool:
    """
    Log a usage event.

    Args:
        verb: The verb that was queried
        device_info: Optional device information

    Returns:
        bool: True if successful
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO usage_logs (verb, device_info) VALUES (%s, %s)",
                (verb, device_info)
            )
            return True
    except pymysql.Error as e:
        logger.error(f"Failed to log usage for '{verb}': {e}")
        return False


def clear_old_usage_logs(days: int = 30) -> int:
    """
    Clear usage logs older than specified days.

    Args:
        days: Number of days to keep logs

    Returns:
        Number of deleted rows
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "DELETE FROM usage_logs WHERE query_time < DATE_SUB(NOW(), INTERVAL %s DAY)",
                (days,)
            )
            deleted = cursor.rowcount
            logger.info(f"Cleared {deleted} old usage logs")
            return deleted
    except pymysql.Error as e:
        logger.error(f"Failed to clear old usage logs: {e}")
        return 0


# ============================================
# 语料数据集（Sketch Engine enTenTen21 → 页面展示）
# 数据源：output/05_原始数据/wsketch_full/*.json 与
#        output/06_图式提取结果/schema_evidence/*.json，
# 由 scripts/load_corpus_dataset.py 灌入。语义类别/保留标记列留给人工回写。
# ============================================

def replace_corpus_word_stats(rows: List[Dict[str, Any]]) -> int:
    """全量替换语料词频概览（136 词）。rows: dict(verb,lpos,freq,relfreq,
    slot_count,collocate_count,candidate_schema,retrieved_at)。"""
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("DELETE FROM corpus_word_stats")
            if rows:
                cursor.executemany(
                    """INSERT INTO corpus_word_stats
                       (verb, lpos, freq, relfreq, slot_count, collocate_count,
                        candidate_schema, retrieved_at)
                       VALUES (%(verb)s, %(lpos)s, %(freq)s, %(relfreq)s,
                               %(slot_count)s, %(collocate_count)s,
                               %(candidate_schema)s, %(retrieved_at)s)""",
                    rows,
                )
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to replace corpus_word_stats: {e}")
        return 0


def replace_corpus_collocations(rows: List[Dict[str, Any]]) -> int:
    """全量替换语料搭配明细（约 5 万行，事务保证不留半截数据）。"""
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("DELETE FROM corpus_collocations")
            if rows:
                cursor.executemany(
                    """INSERT INTO corpus_collocations
                       (verb, slot, rank_in_slot, collocate, logdice,
                        cooccur_count, typical_combo, combo_freq)
                       VALUES (%(verb)s, %(slot)s, %(rank_in_slot)s, %(collocate)s,
                               %(logdice)s, %(cooccur_count)s, %(typical_combo)s,
                               %(combo_freq)s)""",
                    rows,
                )
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to replace corpus_collocations: {e}")
        return 0


def replace_corpus_schema_scores(rows: List[Dict[str, Any]]) -> int:
    """全量替换图式重心得分（136 词 × 4 图式）。"""
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("DELETE FROM word_schema_scores")
            if rows:
                cursor.executemany(
                    """INSERT INTO word_schema_scores
                       (verb, schema_name, slots_present, slots_defined, coverage,
                        n_types, mean_logdice, prominence_score, cand_rank)
                       VALUES (%(verb)s, %(schema_name)s, %(slots_present)s,
                               %(slots_defined)s, %(coverage)s, %(n_types)s,
                               %(mean_logdice)s, %(prominence_score)s, %(cand_rank)s)""",
                    rows,
                )
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to replace word_schema_scores: {e}")
        return 0


def replace_corpus_schema_evidence(rows: List[Dict[str, Any]]) -> int:
    """全量替换图式证据搭配（每图式 Top10）。"""
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("DELETE FROM corpus_schema_evidence")
            if rows:
                cursor.executemany(
                    """INSERT INTO corpus_schema_evidence
                       (verb, schema_name, rank_no, word, logdice, slot)
                       VALUES (%(verb)s, %(schema_name)s, %(rank_no)s,
                               %(word)s, %(logdice)s, %(slot)s)""",
                    rows,
                )
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to replace corpus_schema_evidence: {e}")
        return 0


def get_corpus_overview() -> List[Dict[str, Any]]:
    """语料数据集总表（136 词 × 频次/候选图式/四图式最高得分）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT s.verb, s.lpos, s.freq, s.relfreq, s.slot_count,
                          s.collocate_count, s.candidate_schema,
                          MAX(w.prominence_score) AS max_score
                   FROM corpus_word_stats s
                   LEFT JOIN word_schema_scores w ON w.verb = s.verb
                   GROUP BY s.verb, s.lpos, s.freq, s.relfreq, s.slot_count,
                            s.collocate_count, s.candidate_schema
                   ORDER BY s.freq DESC"""
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get corpus overview: {e}")
        return []


def get_corpus_word_stats(verb: str) -> Optional[Dict[str, Any]]:
    """单词语料概览行。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT verb, lpos, freq, relfreq, slot_count, collocate_count, "
                "candidate_schema, retrieved_at FROM corpus_word_stats WHERE verb = %s",
                (verb,),
            )
            return cursor.fetchone()
    except pymysql.Error as e:
        logger.error(f"Failed to get corpus stats for '{verb}': {e}")
        return None


def get_corpus_schema_scores(verb: str) -> List[Dict[str, Any]]:
    """单词的四图式得分（按得分降序）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT schema_name, slots_present, slots_defined, coverage,
                          n_types, mean_logdice, prominence_score, cand_rank
                   FROM word_schema_scores WHERE verb = %s
                   ORDER BY prominence_score DESC""",
                (verb,),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get schema scores for '{verb}': {e}")
        return []


def get_corpus_schema_evidence(verb: str, top_n: int = 5) -> List[Dict[str, Any]]:
    """单词的图式证据搭配（每图式前 top_n 条，按图式+排名排序）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT schema_name, rank_no, word, logdice, slot
                   FROM corpus_schema_evidence
                   WHERE verb = %s AND rank_no <= %s
                   ORDER BY schema_name, rank_no""",
                (verb, top_n),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get schema evidence for '{verb}': {e}")
        return []


def get_corpus_collocations(verb: str, slot: Optional[str] = None,
                            limit: int = 200) -> List[Dict[str, Any]]:
    """单词的搭配明细（可按槽位过滤，logDice 降序即原始排名）。"""
    try:
        with get_db_cursor() as cursor:
            if slot:
                cursor.execute(
                    """SELECT id, slot, rank_in_slot, collocate, logdice, cooccur_count,
                              typical_combo, combo_freq, semantic_category, keep_flag
                       FROM corpus_collocations
                       WHERE verb = %s AND slot = %s
                       ORDER BY slot, rank_in_slot LIMIT %s""",
                    (verb, slot, limit),
                )
            else:
                cursor.execute(
                    """SELECT id, slot, rank_in_slot, collocate, logdice, cooccur_count,
                              typical_combo, combo_freq, semantic_category, keep_flag
                       FROM corpus_collocations
                       WHERE verb = %s
                       ORDER BY slot, rank_in_slot LIMIT %s""",
                    (verb, limit),
                )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get collocations for '{verb}': {e}")
        return []


def corpus_dataset_ready() -> bool:
    """语料数据集是否已灌入（corpus_word_stats 有数据）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM corpus_word_stats")
            return int(cursor.fetchone()["n"] or 0) > 0
    except (pymysql.Error, Exception) as e:
        logger.debug(f"corpus dataset check failed: {e}")
        return False


# ============================================
# 域—系初判（domain_family_senses，v0.2 词目层初判预览）
# ============================================

def replace_domain_family_senses(rows: List[Dict[str, Any]],
                                 example_rows: Optional[List[Dict[str, Any]]] = None) -> int:
    """全量替换域—系初判义位表与例句子表（docs/域系初判表v0.2.xlsx 灌入）。

    主表行结构：word / sense_num / definition / definition_cn / example /
    lemma_schema / domain / family / sense_annotation / rule_tag / rule_note /
    source / loaded_at（sense_id 为生成列，不写入；updated_at 自动维护）。
    例句行结构：word / sense_num / ex_num / example_en / example_cn / source，
    与主表同事务写入，外键级联删除。
    """
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("DELETE FROM domain_family_examples")
            cursor.execute("DELETE FROM domain_family_senses")
            if rows:
                cursor.executemany(
                    """INSERT INTO domain_family_senses
                       (word, sense_num, definition, definition_cn, example,
                        lemma_schema, domain, family, sense_annotation,
                        rule_tag, rule_note, source, loaded_at)
                       VALUES (%(word)s, %(sense_num)s, %(definition)s,
                               %(definition_cn)s, %(example)s,
                               %(lemma_schema)s, %(domain)s,
                               %(family)s, %(sense_annotation)s,
                               %(rule_tag)s, %(rule_note)s, %(source)s,
                               %(loaded_at)s)""",
                    rows,
                )
            if example_rows:
                cursor.executemany(
                    """INSERT INTO domain_family_examples
                       (word, sense_num, ex_num, example_en, example_cn, source)
                       VALUES (%(word)s, %(sense_num)s, %(ex_num)s,
                               %(example_en)s, %(example_cn)s, %(source)s)""",
                    example_rows,
                )
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to replace domain_family_senses: {e}")
        return 0


def domain_family_ready() -> bool:
    """域—系初判数据是否已灌入。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM domain_family_senses")
            return int(cursor.fetchone()["n"] or 0) > 0
    except (pymysql.Error, Exception) as e:
        logger.debug(f"domain_family check failed: {e}")
        return False


def get_domain_family_overview() -> List[Dict[str, Any]]:
    """域—系总览：域 → 系 → 义位数（按义位数降序）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT domain, family, COUNT(*) AS n_senses,
                          COUNT(DISTINCT word) AS n_verbs
                   FROM domain_family_senses
                   GROUP BY domain, family
                   ORDER BY FIELD(domain, '方式位移域', '路径位移域', '互动位移域'),
                            n_senses DESC"""
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get domain family overview: {e}")
        return []


def get_domain_family_senses(domain: Optional[str] = None,
                             family: Optional[str] = None,
                             word: Optional[str] = None) -> List[Dict[str, Any]]:
    """域—系逐义位明细，支持按域/系/词过滤（word + sense_num 排序）。

    组合键 (word, sense_num) 定位单词义项；sense_id 为生成列一并返回。
    """
    conditions, params = [], []
    if domain:
        conditions.append("domain = %s")
        params.append(domain)
    if family:
        conditions.append("family = %s")
        params.append(family)
    if word:
        conditions.append("word = %s")
        params.append(word)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"""SELECT word, sense_num, sense_id, definition, definition_cn,
                           example, lemma_schema, domain, family, sense_annotation,
                           rule_tag, rule_note, source, loaded_at, updated_at,
                           freq, schema_scores
                    FROM domain_family_senses {where}
                    ORDER BY word, sense_num""",
                tuple(params),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get domain family senses: {e}")
        return []


def get_domain_family_examples(word: str, sense_num: int) -> List[Dict[str, Any]]:
    """某义位的全部例句（英文 + 中文翻译，按 ex_num 升序，逐条对齐）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT ex_num, example_en, example_cn, source
                   FROM domain_family_examples
                   WHERE word = %s AND sense_num = %s
                   ORDER BY ex_num""",
                (word, sense_num),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get domain family examples: {e}")
        return []


# ============================================
# MOVECAT 标注平台（义位准入 / 图式五维标注 / 进度与导出）
# ============================================

def get_annotation_progress() -> List[Dict[str, Any]]:
    """逐动词标注进度（oald_senses，132 词 665 义位 = SenseID 体系的数据基础）：
    义位总数 / 已标注（prototype_level 非空）/ 存疑数。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT d.verb,
                          COUNT(*) AS total,
                          SUM(s.prototype_level IS NOT NULL
                              AND s.prototype_level <> '') AS annotated,
                          SUM(s.human_reviewed = 1) AS reviewed,
                          SUM(s.needs_review = 1) AS flagged,
                          SUM(s.is_idiom = 1) AS idioms
                   FROM oald_senses s
                   JOIN definitions d ON d.id = s.definition_id
                   GROUP BY d.verb ORDER BY d.verb"""
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get annotation progress: {e}")
        return []


def update_sense_annotation(sense_id: int, prototype_level: Optional[str],
                            image_schema: Optional[str], alignment: Optional[str],
                            cn_syntax: Optional[str],
                            translation_strategy: Optional[str],
                            needs_review: bool) -> bool:
    """写入一条 OALD 义位的图式五维标注（空串归一为 NULL = 未标注）。

    注意：MySQL UPDATE 默认只计"值有变化"的行为 affected —— 原样复核保存会
    返回 0，因此以"未抛异常"为成功，不能用 rowcount>0 判断。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """UPDATE oald_senses SET
                       prototype_level = NULLIF(%s, ''),
                       image_schema = NULLIF(%s, ''),
                       alignment = NULLIF(%s, ''),
                       cn_syntax = NULLIF(%s, ''),
                       translation_strategy = NULLIF(%s, ''),
                       needs_review = %s,
                       human_reviewed = 1
                   WHERE id = %s""",
                (prototype_level, image_schema, alignment,
                 cn_syntax, translation_strategy,
                 1 if needs_review else 0, sense_id),
            )
            return True
    except pymysql.Error as e:
        logger.error(f"Failed to update sense annotation (id={sense_id}): {e}")
        return False


def get_annotation_export_rows() -> List[Dict[str, Any]]:
    """导出用：全部义位的标注资源（词典学研究的结构化产出）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT d.verb, s.sense_index, s.definition AS en_ndef,
                          s.grammar AS construction, s.is_idiom,
                          s.prototype_level, s.image_schema,
                          s.alignment, s.cn_syntax, s.translation_strategy,
                          s.needs_review, s.source
                   FROM oald_senses s
                   JOIN definitions d ON d.id = s.definition_id
                   ORDER BY d.verb, s.sense_index"""
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"Failed to get annotation export rows: {e}")
        return []


def update_collocation_annotations(rows: List[Dict[str, Any]]) -> int:
    """批量回写搭配词的人工概念归类（语义类别 + 保留/剔除）。

    rows: [{"id": int, "semantic_category": str|None, "keep_flag": str|None}, ...]
    语义类别进入 PS 计算口径（保留集合的 N 与 Mean_logDice）。
    """
    if not rows:
        return 0
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.executemany(
                """UPDATE corpus_collocations
                   SET semantic_category = NULLIF(%s, ''),
                       keep_flag = NULLIF(%s, '')
                   WHERE id = %s""",
                [(r["semantic_category"] or "", r["keep_flag"] or "", r["id"])
                 for r in rows],
            )
            return len(rows)
    except pymysql.Error as e:
        logger.error(f"Failed to update collocation annotations: {e}")
        return 0
