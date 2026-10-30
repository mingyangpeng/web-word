"""范畴深挖（category study）数据层 —— 跑范畴英汉对比研究的存储与查询。

数据链：d1/跑范畴英汉义位甄别表.xlsx（阶段1 甄别）+
        d1/跑范畴英汉义位编码与独立聚类表.xlsx（阶段2 编码/聚类/对齐）
   → scripts/load_category_study.py 灌入本模块的 8 张表
   → src/app.py 的「范畴深挖」页面组读取展示。

与既有 15 表体系的关系：旧表围绕英语单语 136 词（word_senses 只有中文附属列、
word_clusters 是 Levin 次类硬编码）。本模块建立的是「范畴 → 语言侧 → 词条 →
义位 → 特征编码 → 聚类 → 跨语言对齐」的独立层级，英汉同构（lexemes.language
区分），不与旧表共键 —— 旧表是全词库横向视角，本模块是范畴内纵向视角，
两者通过词目字符串松关联即可，强行共键会把两套切分体系搅在一起
（oald_senses 与 word_senses 分表的教训，见 mysql_db.py v6 迁移注释）。

表结构（8 张，均由 CREATE_TABLES_SQL 建表 + SCHEMA_VERSION 迁移记录）：

  categories          范畴：RUN/WALK/…，研究定位的「上位范畴」
  cs_lexemes          词条：英汉同构，language=en/zh，source_dict=OALD10/现汉7
  cs_senses           义位：甄别表落地（释义/例句/主体/语体/标注/判定）
  cs_sense_features   编码矩阵长表：sense × feature(P1..A3) × value(0/1/2)
  cs_cluster_runs     聚类运行：算法/参数/cophenetic/版本（预编码 vs 双标注IAA）
  cs_clusters         簇：名称/规模/特征画像
  cs_cluster_members  簇成员：簇 ↔ 义位
  cs_cluster_alignment 跨语言簇对齐：英簇 ↔ 汉簇 + Gower 距离 + 四类判定

命名统一加 cs_ 前缀（category study），避免与旧 word_clusters /
word_senses 混淆；categories 无前缀冲突故不加。

特征编码用长表而非宽列：后续加新特征（群体性/语体限制正式编码）零改表；
进聚类与否由 in_clustering 区分（P/M/C 进矩阵 15 列，A 仅核验），
与编码矩阵表「A1-A3 仅核验不进矩阵」的口径一致。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from src.mysql_db import get_db_cursor, _table_exists

logger = logging.getLogger(__name__)

# ============================================
# 建表 SQL（由 mysql_db.init_database 统一执行）
# ============================================
# 迁移机制：这些 CREATE TABLE IF NOT EXISTS 追加进 mysql_db.CREATE_TABLES_SQL，
# 版本号 bump 到 9（v9 = category study 8 表）。旧库升级时建表即迁移 ——
# 新表无历史数据要改，不需要 ALTER 式迁移逻辑。

CATEGORY_STUDY_TABLES_SQL = [
    # --- 范畴 ---
    """CREATE TABLE IF NOT EXISTS categories (
        id INT AUTO_INCREMENT PRIMARY KEY,
        code VARCHAR(32) NOT NULL COMMENT '范畴代号，如 RUN',
        name_cn VARCHAR(64) NOT NULL COMMENT '中文名，如 跑',
        name_en VARCHAR(64) NOT NULL COMMENT '英文名，如 Run',
        status VARCHAR(16) NOT NULL DEFAULT '试点'
            COMMENT '试点 / 进行中 / 完成',
        notes TEXT NULL COMMENT '研究定位说明',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_categories_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 词条（英汉同构）---
    """CREATE TABLE IF NOT EXISTS cs_lexemes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        category_id INT NOT NULL,
        language VARCHAR(4) NOT NULL COMMENT 'en / zh',
        lemma VARCHAR(100) NOT NULL COMMENT '词目（en: run/tear1；zh: 跑/奔跑）',
        source_dict VARCHAR(32) NOT NULL COMMENT 'OALD10 / 现汉7',
        in_levin TINYINT(1) NOT NULL DEFAULT 0
            COMMENT '是否在 Levin(1993) 51 类初始词表内',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_cs_lexemes (category_id, language, lemma),
        INDEX idx_cs_lexemes_lang (language),
        CONSTRAINT fk_cs_lexemes_category FOREIGN KEY (category_id)
            REFERENCES categories(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 义位（甄别表落地）---
    """CREATE TABLE IF NOT EXISTS cs_senses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        lexeme_id INT NOT NULL,
        sense_no VARCHAR(16) NOT NULL
            COMMENT '义项号：en 为 OALD 义项号(1/2/3)，zh 为现汉①②或 —',
        sense_label VARCHAR(64) NOT NULL COMMENT '义位标签，如 足部奔跑义',
        definition TEXT NULL COMMENT '词典释义（原文）',
        example TEXT NULL COMMENT '典型例句',
        subject_type VARCHAR(64) NULL COMMENT '主体类型：人/动物/马/交通工具…',
        register VARCHAR(32) NULL COMMENT '语体：通用/口语/书面/文言/法律',
        tag VARCHAR(32) NULL COMMENT '逃离/冲撞/惊逃/失控/追逐 标注',
        status VARCHAR(8) NOT NULL DEFAULT '保留'
            COMMENT '保留 / 边缘 / 剔除 / 目标（英语侧无三态判定）',
        remark VARCHAR(500) NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_cs_senses (lexeme_id, sense_no, sense_label),
        INDEX idx_cs_senses_status (status),
        CONSTRAINT fk_cs_senses_lexeme FOREIGN KEY (lexeme_id)
            REFERENCES cs_lexemes(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 特征编码矩阵（长表）---
    """CREATE TABLE IF NOT EXISTS cs_sense_features (
        id INT AUTO_INCREMENT PRIMARY KEY,
        sense_id INT NOT NULL,
        feature_code VARCHAR(8) NOT NULL COMMENT 'P1..P5/M1a..M3d/C1/A1..A3',
        value TINYINT NOT NULL DEFAULT 0 COMMENT '编码值 0/1/2',
        in_clustering TINYINT(1) NOT NULL DEFAULT 1
            COMMENT '是否进聚类矩阵（P/M/C=1，A 仅核验=0）',
        remark VARCHAR(500) NULL,
        UNIQUE KEY uq_cs_sense_features (sense_id, feature_code),
        INDEX idx_cs_sense_features_code (feature_code),
        CONSTRAINT fk_cs_sense_features_sense FOREIGN KEY (sense_id)
            REFERENCES cs_senses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 聚类运行（版本化：预编码版与双标注 IAA 版共存）---
    """CREATE TABLE IF NOT EXISTS cs_cluster_runs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        category_id INT NOT NULL,
        language VARCHAR(4) NOT NULL COMMENT 'en / zh',
        algorithm VARCHAR(64) NOT NULL COMMENT '如 Gower+average',
        params JSON NULL COMMENT 'k 及其他参数',
        cophenetic FLOAT NULL COMMENT '共表相关系数',
        version VARCHAR(32) NOT NULL DEFAULT '预编码'
            COMMENT '预编码 / 双标注IAA / …',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_cs_cluster_runs (category_id, language, version),
        CONSTRAINT fk_cs_cluster_runs_category FOREIGN KEY (category_id)
            REFERENCES categories(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 簇 ---
    """CREATE TABLE IF NOT EXISTS cs_clusters (
        id INT AUTO_INCREMENT PRIMARY KEY,
        run_id INT NOT NULL,
        cluster_no INT NOT NULL,
        name VARCHAR(255) NOT NULL COMMENT '簇名（含特征画像摘要）',
        size INT NOT NULL DEFAULT 0,
        profile JSON NULL COMMENT '特征画像（均值≥0.3 的特征: 均值）',
        note TEXT NULL COMMENT '簇解读（类型学观察）',
        UNIQUE KEY uq_cs_clusters (run_id, cluster_no),
        CONSTRAINT fk_cs_clusters_run FOREIGN KEY (run_id)
            REFERENCES cs_cluster_runs(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 簇成员 ---
    """CREATE TABLE IF NOT EXISTS cs_cluster_members (
        id INT AUTO_INCREMENT PRIMARY KEY,
        cluster_id INT NOT NULL,
        sense_id INT NOT NULL,
        UNIQUE KEY uq_cs_cluster_members (cluster_id, sense_id),
        INDEX idx_cs_cluster_members_sense (sense_id),
        CONSTRAINT fk_cs_cluster_members_cluster FOREIGN KEY (cluster_id)
            REFERENCES cs_clusters(id) ON DELETE CASCADE,
        CONSTRAINT fk_cs_cluster_members_sense FOREIGN KEY (sense_id)
            REFERENCES cs_senses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 跨语言簇对齐（英簇 ↔ 汉簇，多对多）---
    """CREATE TABLE IF NOT EXISTS cs_cluster_alignment (
        id INT AUTO_INCREMENT PRIMARY KEY,
        en_cluster_id INT NOT NULL,
        zh_cluster_id INT NOT NULL,
        gower_distance FLOAT NULL COMMENT '簇中心 Gower 距离',
        verdict VARCHAR(16) NOT NULL
            COMMENT '完全对齐 / 部分对齐 / 零对齐 / 错位对齐',
        explanation TEXT NULL,
        UNIQUE KEY uq_cs_cluster_alignment (en_cluster_id, zh_cluster_id),
        CONSTRAINT fk_cs_alignment_en FOREIGN KEY (en_cluster_id)
            REFERENCES cs_clusters(id) ON DELETE CASCADE,
        CONSTRAINT fk_cs_alignment_zh FOREIGN KEY (zh_cluster_id)
            REFERENCES cs_clusters(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]

# 特征编码的展示元数据：列序 = 编码矩阵列序（P/M/C 进聚类，A 仅核验）。
# label 用于热图列轴与卡片画像；group 用于分色/分组标题。
FEATURE_COLUMNS: List[Dict[str, str]] = [
    {"code": "P1", "label": "P1 源点凸显", "group": "路径 P"},
    {"code": "P2", "label": "P2 终点凸显", "group": "路径 P"},
    {"code": "P3", "label": "P3 有界达成", "group": "路径 P"},
    {"code": "P4", "label": "P4 轴向(垂直)", "group": "路径 P"},
    {"code": "P5", "label": "P5 速度", "group": "路径 P"},
    {"code": "M1a", "label": "M1a 主体:人", "group": "主体 M1"},
    {"code": "M1b", "label": "M1b 主体:动物/马", "group": "主体 M1"},
    {"code": "M1c", "label": "M1c 主体:车辆/工具", "group": "主体 M1"},
    {"code": "M1d", "label": "M1d 主体:无生/液体", "group": "主体 M1"},
    {"code": "M2", "label": "M2 情态(急促度)", "group": "方式 M2"},
    {"code": "M3a", "label": "M3a 介质:陆地", "group": "介质 M3"},
    {"code": "M3b", "label": "M3b 介质:水", "group": "介质 M3"},
    {"code": "M3c", "label": "M3c 介质:空气", "group": "介质 M3"},
    {"code": "M3d", "label": "M3d 介质:其他", "group": "介质 M3"},
    {"code": "C1", "label": "C1 动因", "group": "动因 C"},
    {"code": "A1", "label": "A1 核验", "group": "核验 A"},
    {"code": "A2", "label": "A2 核验", "group": "核验 A"},
    {"code": "A3", "label": "A3 主体受限", "group": "核验 A"},
]
FEATURE_CODES = [f["code"] for f in FEATURE_COLUMNS]
CLUSTERING_FEATURES = [f["code"] for f in FEATURE_COLUMNS if not f["code"].startswith("A")]

VERDICT_ORDER = ["完全对齐", "部分对齐", "错位对齐", "零对齐"]
STATUS_ORDER = ["保留", "边缘", "剔除", "目标"]

# 四类意象图式（与全词库体系一致：word_source.py / 标注平台 SCHEMA_OPTIONS）。
# 范畴深挖数据没有显式图式列，由 P/M/C 编码推导：
#   互动位移 —— 逃离/冲撞/追逐标注中的追逐类（互动聚焦，双参与者）
#   源点脱离 —— P1=1（源点凸显：flee/escape/逃X 族）
#   终点抵达 —— P2=1 或 P3=1（终点凸显/有界达成：sprint/dash/跑完里程）
#   方式伴随 —— 其余（步态/速度/主体差异，路径不凸显）
# 判定顺序即列表序：追逐 > 源点 > 终点 > 方式（与编码手册的凸显优先级一致）。
SCHEMA_ORDER = ["方式伴随", "源点脱离", "终点抵达", "互动位移"]


def derive_image_schema(features: Dict[str, int],
                        tag: Optional[str] = None) -> str:
    """由 P/M/C 特征编码推导义位的四类意象图式。

    Args:
        features: 编码矩阵 {P1: 0, ..., C1: 2}（剔除义位为空 dict → 方式伴随，
            但调用方应先过滤无编码义位）。
        tag: 甄别表的逃离/冲撞/惊逃/失控/追逐标注（追逐 → 互动位移）。
    """
    if tag and "追逐" in str(tag):
        return "互动位移"
    if features.get("P1") == 1:
        return "源点脱离"
    if features.get("P2") == 1 or features.get("P3") == 1:
        return "终点抵达"
    return "方式伴随"


def compute_schema_alignment(senses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """图式层中英对齐：四类图式 × (英/汉义位集合) + 图式级簇心距离与判定。

    与簇对齐（cs_cluster_alignment，簇↔簇）不同，这里对齐的是**图式类型**：
    每类图式取两侧全部成员的 15 列聚类特征均值（/2 归一）为图式中心，
    Gower 式平均绝对差为距离；一侧为空 → 零对齐（图式在对方语言未词汇化）。

    判定口径沿用开题报告四类：d<0.05 完全；d<0.15 部分；其余零/错位
    （图式层无"错位"——错位指对应词附带冗余语义，是词对概念）。

    Returns:
        按 SCHEMA_ORDER 排序的行：{schema, en_members, zh_members,
        en_size, zh_size, distance, verdict}。
    """
    import statistics

    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        s: {"en": [], "zh": []} for s in SCHEMA_ORDER}
    for s in senses:
        feats = s.get("features") or {}
        if not feats:
            continue  # 剔除义位不进编码矩阵，也不进图式对齐
        sch = derive_image_schema(feats, s.get("tag"))
        groups[sch][s["language"]].append(s)

    rows = []
    for sch in SCHEMA_ORDER:
        en, zh = groups[sch]["en"], groups[sch]["zh"]
        if not en or not zh:
            distance, verdict = None, "零对齐"
        else:
            diffs = []
            for f in CLUSTERING_FEATURES:
                em = statistics.mean(m["features"].get(f, 0) for m in en)
                zm = statistics.mean(m["features"].get(f, 0) for m in zh)
                diffs.append(abs(em - zm) / 2)
            distance = statistics.mean(diffs)
            verdict = ("完全对齐" if distance < 0.05 else
                       "部分对齐" if distance < 0.15 else "零对齐")
        rows.append({
            "schema": sch,
            "en_members": en, "zh_members": zh,
            "en_size": len(en), "zh_size": len(zh),
            "distance": distance, "verdict": verdict,
        })
    return rows


# ============================================
# 灌入（load_category_study.py 调用）
# ============================================

def replace_category_study(payload: Dict[str, Any]) -> Dict[str, int]:
    """全量替换一个范畴的深挖数据（先删后插，单事务）。

    payload 结构（load_category_study.py 组装）::

        {
          "category": {code, name_cn, name_en, status, notes},
          "lexemes": [{language, lemma, source_dict, in_levin}],
          "senses": [{language, lemma, sense_no, sense_label, definition,
                      example, subject_type, register, tag, status, remark,
                      features: {P1: 0, ..., A3: 0}, feature_remarks: {...}}],
          "cluster_runs": [{language, algorithm, params, cophenetic, version,
                            clusters: [{cluster_no, name, size, profile,
                                        note, members: [(lemma, sense_no, sense_label)]}}],
          "alignments": [{en_cluster_no, zh_cluster_no, gower_distance,
                          verdict, explanation}],
        }

    幂等口径：同范畴重灌 = 删掉该范畴全部行再插入（categories ON DELETE
    CASCADE 级联到 7 张子表）。跨范畴不互删。

    Returns:
        {"lexemes": n, "senses": n, "features": n, "clusters": n,
         "members": n, "alignments": n} 计数。
    """
    counts = {"lexemes": 0, "senses": 0, "features": 0,
              "clusters": 0, "members": 0, "alignments": 0}
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cat = payload["category"]
            cursor.execute("DELETE FROM categories WHERE code = %s", (cat["code"],))

            cursor.execute(
                """INSERT INTO categories (code, name_cn, name_en, status, notes)
                   VALUES (%s, %s, %s, %s, %s)""",
                (cat["code"], cat["name_cn"], cat["name_en"],
                 cat.get("status", "试点"), cat.get("notes")),
            )
            cursor.execute("SELECT LAST_INSERT_ID() AS id")
            category_id = int(cursor.fetchone()["id"])

            # 词条 → (language, lemma) → id
            lexeme_ids: Dict[tuple, int] = {}
            for lx in payload["lexemes"]:
                cursor.execute(
                    """INSERT INTO cs_lexemes
                       (category_id, language, lemma, source_dict, in_levin)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (category_id, lx["language"], lx["lemma"],
                     lx["source_dict"], int(lx.get("in_levin", 0))),
                )
                cursor.execute("SELECT LAST_INSERT_ID() AS id")
                lexeme_ids[(lx["language"], lx["lemma"])] = int(cursor.fetchone()["id"])
            counts["lexemes"] = len(lexeme_ids)

            # 义位 + 特征编码
            sense_ids: Dict[tuple, int] = {}  # (language, lemma, sense_no, sense_label) → id
            for se in payload["senses"]:
                key = (se["language"], se["lemma"], se["sense_no"], se["sense_label"])
                cursor.execute(
                    """INSERT INTO cs_senses
                       (lexeme_id, sense_no, sense_label, definition, example,
                        subject_type, register, tag, status, remark)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (lexeme_ids[(se["language"], se["lemma"])], se["sense_no"],
                     se["sense_label"], se.get("definition"), se.get("example"),
                     se.get("subject_type"), se.get("register"), se.get("tag"),
                     se.get("status", "保留"), se.get("remark")),
                )
                cursor.execute("SELECT LAST_INSERT_ID() AS id")
                sense_id = int(cursor.fetchone()["id"])
                sense_ids[key] = sense_id

                remarks = se.get("feature_remarks") or {}
                for code, value in (se.get("features") or {}).items():
                    cursor.execute(
                        """INSERT INTO cs_sense_features
                           (sense_id, feature_code, value, in_clustering, remark)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (sense_id, code, int(value),
                         0 if code.startswith("A") else 1, remarks.get(code)),
                    )
                    counts["features"] += 1
            counts["senses"] = len(sense_ids)

            # 聚类运行 + 簇 + 成员；cluster_ids[(language, cluster_no)] 供对齐表引用
            cluster_ids: Dict[tuple, int] = {}
            for run in payload["cluster_runs"]:
                cursor.execute(
                    """INSERT INTO cs_cluster_runs
                       (category_id, language, algorithm, params, cophenetic, version)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (category_id, run["language"], run["algorithm"],
                     json.dumps(run.get("params"), ensure_ascii=False),
                     run.get("cophenetic"), run.get("version", "预编码")),
                )
                cursor.execute("SELECT LAST_INSERT_ID() AS id")
                run_id = int(cursor.fetchone()["id"])

                for cl in run["clusters"]:
                    cursor.execute(
                        """INSERT INTO cs_clusters
                           (run_id, cluster_no, name, size, profile, note)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (run_id, cl["cluster_no"], cl["name"], cl.get("size", 0),
                         json.dumps(cl.get("profile"), ensure_ascii=False),
                         cl.get("note")),
                    )
                    cursor.execute("SELECT LAST_INSERT_ID() AS id")
                    cluster_id = int(cursor.fetchone()["id"])
                    cluster_ids[(run["language"], cl["cluster_no"])] = cluster_id
                    counts["clusters"] += 1

                    for (lemma, sense_no, sense_label) in cl["members"]:
                        lang = run["language"]
                        sense_key = (lang, lemma, str(sense_no), sense_label)
                        sense_id = sense_ids.get(sense_key)
                        if sense_id is None:
                            raise ValueError(
                                f"簇成员找不到义位: {sense_key}（先核对甄别清单）")
                        cursor.execute(
                            """INSERT INTO cs_cluster_members (cluster_id, sense_id)
                               VALUES (%s, %s)""",
                            (cluster_id, sense_id),
                        )
                        counts["members"] += 1

            # 跨语言对齐
            for al in payload["alignments"]:
                en_id = cluster_ids.get(("en", al["en_cluster_no"]))
                zh_id = cluster_ids.get(("zh", al["zh_cluster_no"]))
                if en_id is None or zh_id is None:
                    raise ValueError(
                        f"对齐行引用不存在的簇: en#{al['en_cluster_no']} "
                        f"zh#{al['zh_cluster_no']}")
                cursor.execute(
                    """INSERT INTO cs_cluster_alignment
                       (en_cluster_id, zh_cluster_id, gower_distance, verdict, explanation)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (en_id, zh_id, al.get("gower_distance"),
                     al["verdict"], al.get("explanation")),
                )
                counts["alignments"] += 1
        return counts
    except Exception as e:
        logger.error(f"replace_category_study failed: {e}")
        raise


# ============================================
# 查询（app.py 范畴深挖页面调用）
# ============================================

def category_study_ready(code: Optional[str] = None) -> bool:
    """范畴深挖数据是否已灌入（可指定范畴代号）。"""
    try:
        with get_db_cursor() as cursor:
            if code:
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM categories WHERE code = %s", (code,))
            else:
                cursor.execute("SELECT COUNT(*) AS n FROM categories")
            return int(cursor.fetchone()["n"] or 0) > 0
    except Exception as e:
        logger.debug(f"category study check failed: {e}")
        return False


def get_categories() -> List[Dict[str, Any]]:
    """范畴列表（含各语言词条/义位计数），页面顶部选择器用。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT c.id, c.code, c.name_cn, c.name_en, c.status, c.notes,
                          (SELECT COUNT(*) FROM cs_lexemes l
                            WHERE l.category_id = c.id AND l.language = 'en') AS en_lexemes,
                          (SELECT COUNT(*) FROM cs_lexemes l
                            WHERE l.category_id = c.id AND l.language = 'zh') AS zh_lexemes,
                          (SELECT COUNT(*) FROM cs_senses s
                            JOIN cs_lexemes l ON s.lexeme_id = l.id
                            WHERE l.category_id = c.id AND l.language = 'en') AS en_senses,
                          (SELECT COUNT(*) FROM cs_senses s
                            JOIN cs_lexemes l ON s.lexeme_id = l.id
                            WHERE l.category_id = c.id AND l.language = 'zh') AS zh_senses
                   FROM categories c ORDER BY c.id"""
            )
            return list(cursor.fetchall())
    except Exception as e:
        logger.error(f"get_categories failed: {e}")
        return []


def get_senses_with_features(category_id: int,
                             language: Optional[str] = None,
                             status: Optional[str] = None) -> List[Dict[str, Any]]:
    """义位明细 + 特征编码（宽表化），热图/聚类面板/甄别清单共用。

    每行：sense_id / language / lemma / sense_no / sense_label / definition /
    example / subject_type / register / tag / status / remark /
    features（{P1: 0, ...}，缺省特征不出现）/ cluster_no（若有）。
    """
    sql = (
        """SELECT s.id AS sense_id, l.language, l.lemma, s.sense_no,
                  s.sense_label, s.definition, s.example, s.subject_type,
                  s.register, s.tag, s.status, s.remark
           FROM cs_senses s
           JOIN cs_lexemes l ON s.lexeme_id = l.id
           WHERE l.category_id = %s"""
    )
    params: List[Any] = [category_id]
    if language:
        sql += " AND l.language = %s"
        params.append(language)
    if status:
        sql += " AND s.status = %s"
        params.append(status)
    sql += " ORDER BY l.language DESC, l.lemma, s.sense_no, s.sense_label"
    # DESC 让英语(en)排前、汉语(zh)排后，与编码矩阵表「英语矩阵在上」一致
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            senses = list(cursor.fetchall())
            if not senses:
                return []
            ids = [s["sense_id"] for s in senses]
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(
                f"""SELECT sense_id, feature_code, value, remark
                    FROM cs_sense_features
                    WHERE sense_id IN ({placeholders})""",
                ids,
            )
            features: Dict[int, Dict[str, int]] = {}
            remarks: Dict[int, Dict[str, str]] = {}
            for row in cursor.fetchall():
                sid = int(row["sense_id"])
                features.setdefault(sid, {})[row["feature_code"]] = int(row["value"])
                if row["remark"]:
                    remarks.setdefault(sid, {})[row["feature_code"]] = row["remark"]
            cursor.execute(
                f"""SELECT m.sense_id, c.cluster_no, c.name AS cluster_name
                    FROM cs_cluster_members m
                    JOIN cs_clusters c ON m.cluster_id = c.id
                    WHERE m.sense_id IN ({placeholders})""",
                ids,
            )
            cluster_of: Dict[int, Dict[str, Any]] = {}
            for row in cursor.fetchall():
                cluster_of[int(row["sense_id"])] = {
                    "cluster_no": int(row["cluster_no"]),
                    "cluster_name": row["cluster_name"],
                }
            for s in senses:
                sid = s["sense_id"]
                s["features"] = features.get(sid, {})
                s["feature_remarks"] = remarks.get(sid, {})
                s["cluster"] = cluster_of.get(sid)
            return senses
    except Exception as e:
        logger.error(f"get_senses_with_features failed: {e}")
        return []


def get_cluster_runs(category_id: int,
                     language: Optional[str] = None) -> List[Dict[str, Any]]:
    """聚类运行列表（含簇与成员计数）。"""
    sql = (
        """SELECT r.id AS run_id, r.language, r.algorithm, r.params,
                  r.cophenetic, r.version,
                  (SELECT COUNT(*) FROM cs_clusters c WHERE c.run_id = r.id) AS n_clusters
           FROM cs_cluster_runs r
           WHERE r.category_id = %s"""
    )
    params: List[Any] = [category_id]
    if language:
        sql += " AND r.language = %s"
        params.append(language)
    sql += " ORDER BY r.language DESC, r.id"
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            runs = list(cursor.fetchall())
            for run in runs:
                if isinstance(run.get("params"), str):
                    try:
                        run["params"] = json.loads(run["params"])
                    except (TypeError, ValueError):
                        pass
            return runs
    except Exception as e:
        logger.error(f"get_cluster_runs failed: {e}")
        return []


def get_clusters_with_members(run_id: int) -> List[Dict[str, Any]]:
    """一个聚类运行的全部簇：名称/规模/画像/解读 + 成员义位（含特征编码）。

    成员行带义位明细与 features，聚类对比面板点开簇即可看成员画像，
    不用再回查 get_senses_with_features。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT c.id AS cluster_id, c.cluster_no, c.name, c.size,
                          c.profile, c.note
                   FROM cs_clusters c
                   WHERE c.run_id = %s
                   ORDER BY c.cluster_no""",
                (run_id,),
            )
            clusters = list(cursor.fetchall())
            if not clusters:
                return []
            for cl in clusters:
                if isinstance(cl.get("profile"), str):
                    try:
                        cl["profile"] = json.loads(cl["profile"])
                    except (TypeError, ValueError):
                        cl["profile"] = {}
            cursor.execute(
                """SELECT m.cluster_id, s.id AS sense_id, l.lemma, l.language,
                          s.sense_no, s.sense_label, s.definition, s.example,
                          s.subject_type, s.register, s.tag, s.status
                   FROM cs_cluster_members m
                   JOIN cs_senses s ON m.sense_id = s.id
                   JOIN cs_lexemes l ON s.lexeme_id = l.id
                   WHERE m.cluster_id IN
                         (SELECT id FROM cs_clusters WHERE run_id = %s)
                   ORDER BY l.lemma, s.sense_no""",
                (run_id,),
            )
            members = list(cursor.fetchall())
            member_ids = [m["sense_id"] for m in members]
            features: Dict[int, Dict[str, int]] = {}
            if member_ids:
                placeholders = ",".join(["%s"] * len(member_ids))
                cursor.execute(
                    f"""SELECT sense_id, feature_code, value FROM cs_sense_features
                        WHERE sense_id IN ({placeholders})""",
                    member_ids,
                )
                for row in cursor.fetchall():
                    features.setdefault(int(row["sense_id"]), {})[
                        row["feature_code"]] = int(row["value"])
            by_cluster: Dict[int, List[Dict[str, Any]]] = {}
            for m in members:
                m["features"] = features.get(m["sense_id"], {})
                by_cluster.setdefault(int(m["cluster_id"]), []).append(m)
            for cl in clusters:
                cl["members"] = by_cluster.get(int(cl["cluster_id"]), [])
            return clusters
    except Exception as e:
        logger.error(f"get_clusters_with_members failed: {e}")
        return []


def get_alignments(category_id: int,
                   version: str = "预编码") -> List[Dict[str, Any]]:
    """跨语言簇对齐行（英簇/汉簇名称、距离、判定、说明）。

    version 过滤两侧 cluster_runs 的版本 —— 预编码版与双标注 IAA 版
    各自对齐，互不混排。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT a.id, a.gower_distance, a.verdict, a.explanation,
                          en.id AS en_cluster_id, en.cluster_no AS en_cluster_no,
                          en.name AS en_cluster_name, en.size AS en_size,
                          zh.cluster_no AS zh_cluster_no,
                          zh.name AS zh_cluster_name, zh.size AS zh_size,
                          en_run.id AS en_run_id, zh_run.id AS zh_run_id
                   FROM cs_cluster_alignment a
                   JOIN cs_clusters en ON a.en_cluster_id = en.id
                   JOIN cs_clusters zh ON a.zh_cluster_id = zh.id
                   JOIN cs_cluster_runs en_run ON en.run_id = en_run.id
                   JOIN cs_cluster_runs zh_run ON zh.run_id = zh_run.id
                   WHERE en_run.category_id = %s
                     AND en_run.version = %s AND zh_run.version = %s
                   ORDER BY FIELD(a.verdict, '完全对齐', '部分对齐',
                                  '错位对齐', '零对齐'),
                            a.gower_distance""",
                (category_id, version, version),
            )
            rows = list(cursor.fetchall())
            return rows
    except Exception as e:
        logger.error(f"get_alignments failed: {e}")
        return []


def get_cluster_profiles(run_id: int) -> Dict[int, Dict[str, Any]]:
    """一个运行内各簇的特征画像 {cluster_id: profile_dict}（雷达图叠加用）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT id, profile FROM cs_clusters WHERE run_id = %s""",
                (run_id,),
            )
            out: Dict[int, Dict[str, Any]] = {}
            for row in cursor.fetchall():
                profile = row["profile"]
                if isinstance(profile, str):
                    try:
                        profile = json.loads(profile)
                    except (TypeError, ValueError):
                        profile = {}
                out[int(row["id"])] = profile or {}
            return out
    except Exception as e:
        logger.error(f"get_cluster_profiles failed: {e}")
        return {}


def get_screening_stats(category_id: int) -> Dict[str, Any]:
    """甄别统计（范畴总览页）：各语言词条/义位/判定分布 + 聚类运行概要。"""
    stats: Dict[str, Any] = {"en": {}, "zh": {}}
    try:
        with get_db_cursor() as cursor:
            for lang in ("en", "zh"):
                cursor.execute(
                    """SELECT COUNT(DISTINCT l.id) AS n_lexemes,
                              COUNT(s.id) AS n_senses
                       FROM cs_lexemes l
                       LEFT JOIN cs_senses s ON s.lexeme_id = l.id
                       WHERE l.category_id = %s AND l.language = %s""",
                    (category_id, lang),
                )
                row = cursor.fetchone()
                stats[lang]["n_lexemes"] = int(row["n_lexemes"])
                stats[lang]["n_senses"] = int(row["n_senses"])
                cursor.execute(
                    """SELECT s.status, COUNT(*) AS n
                       FROM cs_senses s
                       JOIN cs_lexemes l ON s.lexeme_id = l.id
                       WHERE l.category_id = %s AND l.language = %s
                       GROUP BY s.status""",
                    (category_id, lang),
                )
                stats[lang]["status"] = {r["status"]: int(r["n"])
                                         for r in cursor.fetchall()}
            cursor.execute(
                """SELECT language, version, algorithm, cophenetic,
                          (SELECT COUNT(*) FROM cs_clusters c
                            WHERE c.run_id = r.id) AS n_clusters
                   FROM cs_cluster_runs r
                   WHERE r.category_id = %s ORDER BY r.language DESC, r.id""",
                (category_id,),
            )
            stats["runs"] = list(cursor.fetchall())
            cursor.execute(
                """SELECT verdict, COUNT(*) AS n FROM cs_cluster_alignment a
                   JOIN cs_clusters en ON a.en_cluster_id = en.id
                   JOIN cs_cluster_runs r ON en.run_id = r.id
                   WHERE r.category_id = %s GROUP BY verdict""",
                (category_id,),
            )
            stats["verdicts"] = {r["verdict"]: int(r["n"])
                                 for r in cursor.fetchall()}
        return stats
    except Exception as e:
        logger.error(f"get_screening_stats failed: {e}")
        return stats


def register_tables() -> None:
    """把 8 张表注册进 mysql_db 的建表清单（init_database 前调用）。

    mysql_db.CREATE_TABLES_SQL 是模块级列表；本模块在 import 时由
    app.py / load 脚本显式调用一次，保持「建表 SQL 单一来源在各自模块」
    而不是让 mysql_db 反向 import 本模块（那会形成循环依赖）。
    """
    from src import mysql_db
    for sql in CATEGORY_STUDY_TABLES_SQL:
        table_name = sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" ")[0]
        existing = [s for s in mysql_db.CREATE_TABLES_SQL
                    if f"CREATE TABLE IF NOT EXISTS {table_name} " in s
                    or f"CREATE TABLE IF NOT EXISTS {table_name} (" in s]
        if not existing:
            mysql_db.CREATE_TABLES_SQL.append(sql)
