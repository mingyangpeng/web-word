"""《现汉7》中文词典数据层 —— ModernChineseDict 结构化数据的存储与查询。

数据链：data/ModernChineseDict/mdx/dict.mdx.txt（mdict 纯文本导出）
   → scripts/parse_modern_chinese_dict.py（结构化，70113 词条 / 94876 义项）
   → data/zh_dict_senses.json
   → scripts/load_zh_dict.py 灌入本模块的 3 张表
   → 范畴深挖汉语侧 / 后续中文词条提取共用。

表结构（3 张，v10 迁移建表）：

  zh_dict_entries   词条（读音条目）：多音字每个读音一行（跑 páo / 跑 pǎo）
  zh_dict_senses    义项：义项号（①②…或 NULL=单义项）、释义、语域、比喻标记
  zh_dict_examples  例句：与义项一对多，比喻例（◇）单独标记

与 cs_senses（范畴深挖义位表）的关系：zh_dict_* 是**词典原始层**，
cs_senses 是**研究加工层**（甄别/编码后的义位）。研究层通过
(lemma, sense_no) 引用词典层，甄别表的《现汉7》释义/例句/语体/判定
从此有库内可查的证据源，不再依赖 xlsx 单一来源。

例句拆分子表而非 JSON 列：与 domain_family_examples 同一决策 ——
JSON 列不可查询、不可索引，例句是要按义项/比喻标记检索的一等数据。
"""

import logging
from typing import Any, Dict, List

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 建表 SQL（由 mysql_db.init_database 统一执行，v10）
# ============================================
ZH_DICT_TABLES_SQL = [
    # --- 词条（读音条目）：多音字每读音一行 ---
    # lemma / pinyin 两列都用 utf8mb4_bin：
    #   * pinyin —— unicode_ci 会把声调符号折叠（pēi = pèi = pei），
    #     多音字词条唯一键直接冲突（实测 㾦 pēi/pèi 撞键）；
    #   * lemma —— CJK 扩展区字符（虺𪨇 / 虺𬯎）在 unicode_ci 下判等，
    #     同形词唯一键冲突。二进制排序严格按码位，两个问题一次解决。
    # 查询端按 lemma 精确匹配（lookup_lemma），不受排序规则影响。
    """CREATE TABLE IF NOT EXISTS zh_dict_entries (
        id INT AUTO_INCREMENT PRIMARY KEY,
        lemma VARCHAR(64) CHARACTER SET utf8mb4
            COLLATE utf8mb4_bin NOT NULL
            COMMENT '词目（跑 / 奔跑 / B超；同形词带上标 㧟¹）',
        pinyin VARCHAR(128) CHARACTER SET utf8mb4
            COLLATE utf8mb4_bin DEFAULT NULL
            COMMENT '拼音（多音字词条每读音一行；二进制排序保留声调区分）',
        pos VARCHAR(16) DEFAULT NULL COMMENT '词性：动/名/形/副/量/拟声/连/代/介/助/叹/数',
        erhua TINYINT(1) NOT NULL DEFAULT 0 COMMENT '儿化词条（～儿）',
        cross_ref VARCHAR(255) DEFAULT NULL COMMENT '另见 xx页xxx（多音字互指）',
        raw_html MEDIUMTEXT COMMENT 'mdx 原始 HTML（溯源用）',
        UNIQUE KEY uq_zh_dict_entries (lemma, pinyin),
        INDEX idx_zh_dict_entries_lemma (lemma),
        INDEX idx_zh_dict_entries_pos (pos)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 义项 ---
    """CREATE TABLE IF NOT EXISTS zh_dict_senses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        entry_id INT NOT NULL,
        sense_no VARCHAR(8) DEFAULT NULL COMMENT '义项号 ①②…；NULL=单义项',
        definition TEXT NOT NULL COMMENT '释义（：前的部分）',
        register VARCHAR(32) DEFAULT NULL
            COMMENT '语域：书面/方言/口语/文言（lyb 标注映射）',
        is_metaphor TINYINT(1) NOT NULL DEFAULT 0
            COMMENT '含比喻用法例（lyc 标记，◇例不计入判定的口径）',
        sense_order INT NOT NULL DEFAULT 0 COMMENT '义项在词条内的顺序（0 起）',
        UNIQUE KEY uq_zh_dict_senses (entry_id, sense_order),
        INDEX idx_zh_dict_senses_register (register),
        CONSTRAINT fk_zh_dict_senses_entry FOREIGN KEY (entry_id)
            REFERENCES zh_dict_entries(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    # --- 例句（与义项一对多；比喻例单独标记）---
    """CREATE TABLE IF NOT EXISTS zh_dict_examples (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        sense_id INT NOT NULL,
        ex_order INT NOT NULL COMMENT '例句序号（1 起）',
        example VARCHAR(512) NOT NULL COMMENT '例句原文（～ 已还原为词目）',
        is_metaphor TINYINT(1) NOT NULL DEFAULT 0
            COMMENT '比喻例（lyc 标记之后的例句）',
        UNIQUE KEY uq_zh_dict_examples (sense_id, ex_order),
        CONSTRAINT fk_zh_dict_examples_sense FOREIGN KEY (sense_id)
            REFERENCES zh_dict_senses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]


# ============================================
# 灌入（scripts/load_zh_dict.py 调用）
# ============================================

def replace_zh_dict(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """全量替换词典数据（先删后插，单事务）。

    entries 结构（parse_modern_chinese_dict.py 的输出）：
        {lemma, pinyin, pos, erhua, cross_refs: [...],
         senses: [{no, register, is_metaphor, definition, examples: [...]}],
         raw_html}

    9.5 万义项 + 30 万例句的批量插入分批提交（每 5000 义项一批），
    避免 undo log 过大。

    Returns:
        {"entries": n, "senses": n, "examples": n} 计数。
    """
    counts = {"entries": 0, "senses": 0, "examples": 0}
    batch_size = 5000
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("DELETE FROM zh_dict_examples")
            cursor.execute("DELETE FROM zh_dict_senses")
            cursor.execute("DELETE FROM zh_dict_entries")

            pending_senses: List[Dict[str, Any]] = []
            for e in entries:
                cursor.execute(
                    """INSERT INTO zh_dict_entries
                       (lemma, pinyin, pos, erhua, cross_ref, raw_html)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (e["lemma"], e.get("pinyin"), e.get("pos"),
                     int(bool(e.get("erhua"))),
                     "; ".join(e.get("cross_refs") or []) or None,
                     e.get("raw_html")),
                )
                cursor.execute("SELECT LAST_INSERT_ID() AS id")
                entry_id = int(cursor.fetchone()["id"])
                counts["entries"] += 1

                for order, s in enumerate(e.get("senses") or []):
                    pending_senses.append({
                        "entry_id": entry_id,
                        "sense_no": s.get("no"),
                        "definition": s.get("definition") or "",
                        "register": s.get("register"),
                        "is_metaphor": int(bool(s.get("is_metaphor"))),
                        "sense_order": order,
                        "examples": s.get("examples") or [],
                        "is_metaphor_sense": int(bool(s.get("is_metaphor"))),
                    })
                    counts["senses"] += 1

                # 分批插义项 + 例句，控制事务大小
                if len(pending_senses) >= batch_size:
                    _flush_senses(cursor, pending_senses, counts)
                    cursor.connection.commit()
                    pending_senses = []
            if pending_senses:
                _flush_senses(cursor, pending_senses, counts)
        return counts
    except Exception as e:
        logger.error(f"replace_zh_dict failed: {e}")
        raise


def _flush_senses(cursor, senses: List[Dict[str, Any]],
                  counts: Dict[str, int]) -> None:
    """一批义项（及其例句）插入。

    executemany 后 LAST_INSERT_ID 只返回**最后一条**的 id —— 不能用它回填
    每个义项的 sense_id。改为先插义项、再按 (entry_id, sense_order) 查回
    全部 id（组合键在插入前已知，天然一一对应）。
    """
    cursor.executemany(
        """INSERT INTO zh_dict_senses
           (entry_id, sense_no, definition, register, is_metaphor, sense_order)
           VALUES (%(entry_id)s, %(sense_no)s, %(definition)s,
                   %(register)s, %(is_metaphor)s, %(sense_order)s)""",
        senses,
    )
    # 查回这批义项的 id：本批的 (entry_id, sense_order) 组合唯一
    pairs = {(s["entry_id"], s["sense_order"]) for s in senses}
    cursor.execute(
        """SELECT id, entry_id, sense_order FROM zh_dict_senses
           WHERE (entry_id, sense_order) IN (%s)"""
        % ", ".join("(%s, %s)" % p for p in pairs),
    )
    id_by_pair = {(int(r["entry_id"]), int(r["sense_order"])): int(r["id"])
                  for r in cursor.fetchall()}

    example_rows = []
    for s in senses:
        sense_id = id_by_pair[(s["entry_id"], s["sense_order"])]
        for i, ex in enumerate(s["examples"], start=1):
            example_rows.append({
                "sense_id": sense_id, "ex_order": i,
                "example": str(ex)[:512],
                # 比喻例：义项带 lyc 标记时，其例句全部标比喻（保守口径，
                # 与甄别表「◇隐喻例不计入判定」一致）
                "is_metaphor": s["is_metaphor_sense"],
            })
            counts["examples"] += 1
    if example_rows:
        cursor.executemany(
            """INSERT INTO zh_dict_examples
               (sense_id, ex_order, example, is_metaphor)
               VALUES (%(sense_id)s, %(ex_order)s, %(example)s,
                       %(is_metaphor)s)""",
            example_rows,
        )


# ============================================
# 查询
# ============================================

def zh_dict_ready() -> bool:
    """词典数据是否已灌入。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM zh_dict_entries")
            return int(cursor.fetchone()["n"] or 0) > 0
    except Exception as e:
        logger.debug(f"zh_dict check failed: {e}")
        return False


def lookup_lemma(lemma: str) -> List[Dict[str, Any]]:
    """查一个词目的全部读音条目（含义项与例句）。

    返回 [{entry_id, lemma, pinyin, pos, erhua, cross_ref,
           senses: [{sense_id, sense_no, definition, register,
                     is_metaphor, sense_order,
                     examples: [{example, is_metaphor}]}]}]
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT id, lemma, pinyin, pos, erhua, cross_ref
                   FROM zh_dict_entries WHERE lemma = %s
                   ORDER BY pinyin""",
                (lemma,),
            )
            entries = list(cursor.fetchall())
            if not entries:
                return []
            ids = [int(e["id"]) for e in entries]
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(
                f"""SELECT id, entry_id, sense_no, definition, register,
                           is_metaphor, sense_order
                    FROM zh_dict_senses
                    WHERE entry_id IN ({placeholders})
                    ORDER BY entry_id, sense_order""",
                ids,
            )
            senses_by_entry: Dict[int, List[Dict[str, Any]]] = {}
            sense_by_id: Dict[int, Dict[str, Any]] = {}
            sense_ids = []
            for s in cursor.fetchall():
                s["examples"] = []
                senses_by_entry.setdefault(int(s["entry_id"]), []).append(s)
                sense_by_id[int(s["id"])] = s
                sense_ids.append(int(s["id"]))
            if sense_ids:
                ph2 = ",".join(["%s"] * len(sense_ids))
                cursor.execute(
                    f"""SELECT sense_id, example, is_metaphor, ex_order
                        FROM zh_dict_examples
                        WHERE sense_id IN ({ph2})
                        ORDER BY sense_id, ex_order""",
                    sense_ids,
                )
                for ex in cursor.fetchall():
                    s = sense_by_id.get(int(ex["sense_id"]))
                    if s is not None:
                        s["examples"].append({
                            "example": ex["example"],
                            "is_metaphor": bool(ex["is_metaphor"]),
                        })
            for e in entries:
                e["senses"] = senses_by_entry.get(int(e["id"]), [])
            return entries
    except Exception as e:
        logger.error(f"lookup_lemma failed: {e}")
        return []


def search_verbs(keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按词目子串搜动词词条（范畴深挖选词 / 页面检索用）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT e.id, e.lemma, e.pinyin, e.pos,
                          COUNT(s.id) AS n_senses
                   FROM zh_dict_entries e
                   LEFT JOIN zh_dict_senses s ON s.entry_id = e.id
                   WHERE e.lemma LIKE %s AND e.pos = '动'
                   GROUP BY e.id, e.lemma, e.pinyin, e.pos
                   ORDER BY e.lemma
                   LIMIT %s""",
                (f"%{keyword}%", limit),
            )
            return list(cursor.fetchall())
    except Exception as e:
        logger.error(f"search_verbs failed: {e}")
        return []


def get_zh_dict_stats() -> Dict[str, int]:
    """词典规模统计（灌库校验 / 页面展示）。"""
    stats = {"entries": 0, "senses": 0, "examples": 0, "verb_entries": 0}
    try:
        with get_db_cursor() as cursor:
            for key, sql in (
                ("entries", "SELECT COUNT(*) AS n FROM zh_dict_entries"),
                ("senses", "SELECT COUNT(*) AS n FROM zh_dict_senses"),
                ("examples", "SELECT COUNT(*) AS n FROM zh_dict_examples"),
                ("verb_entries",
                 "SELECT COUNT(*) AS n FROM zh_dict_entries WHERE pos = '动'"),
            ):
                cursor.execute(sql)
                stats[key] = int(cursor.fetchone()["n"] or 0)
        return stats
    except Exception as e:
        logger.error(f"get_zh_dict_stats failed: {e}")
        return stats


def register_tables() -> None:
    """把 3 张表注册进 mysql_db 的建表清单（机制同 category_study）。"""
    from src import mysql_db
    for sql in ZH_DICT_TABLES_SQL:
        table_name = sql.split("CREATE TABLE IF NOT EXISTS ")[1].split(" ")[0]
        existing = [s for s in mysql_db.CREATE_TABLES_SQL
                    if f"CREATE TABLE IF NOT EXISTS {table_name} " in s
                    or f"CREATE TABLE IF NOT EXISTS {table_name} (" in s]
        if not existing:
            mysql_db.CREATE_TABLES_SQL.append(sql)
