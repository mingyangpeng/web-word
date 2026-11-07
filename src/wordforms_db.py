"""词形表数据层 —— wordforms：检索词形还原的形态索引（Agent E）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D① 词条资源域
「wordforms(词形表：inflection/variant/pinyin，检索词形还原用)」；
契约：docs/spec/阶段1施工规范.md §3-E（本文件签名与之一致）。

是什么（一张表）：
  wordforms  词形 → 词目的还原索引。lemma_word 是词条头词（现汉词目
  字符串），form 是一种 surface 词形（屈折/异体/拼音），kind 标词形
  类型 ∈ {inflection 屈折, variant 异体, pinyin 拼音}。检索端拿到用户
  输入或文档中的 surface 形式，按 form 精确匹配还原出词目行。

  注：契约 §3-E 注释写「lemma_id/form/kind/pinyin」，批次任务书给的
  DDL 为 lemma_word VARCHAR(80)（词目字符串）—— 现汉侧词形还原天然
  以词目字符串为键（zh_dict_entries 无跨库词目 id 可引），本实现按
  任务书 DDL 落 lemma_word 列；inflection/variant 词形（批次 2+）
  亦以词目字符串为键，无需改表。

数据链：
  zh_dict_entries（现汉读音条目，lemma/pinyin 两列，多音字每读音一行）
  → load_pinyin_from_zh_dict()（每词条写一条 kind='pinyin' 词形）
  → 检索词形还原（批次 2：检索框输入拼音 → resolve_form → 词目）；
  inflection/variant 词形后续由相应数据链灌入（表结构已预留 kind）。

幂等策略（load_pinyin_from_zh_dict，二选一中的「库端唯一键 + IGNORE」）：
  UNIQUE(lemma_word, form, kind) 是幂等根基 —— 每次全量重灌用
  INSERT IGNORE 批量写入，重复键被忽略、只计真正新增行；返回值是
  **本次新增行数**（首灌 ≈ 词条数，重复运行返回 0，天然幂等）。
  与「先清空再重灌」策略相比：不清旧数据（inflection/variant 词形
  不受牵连）、可增量补灌、中途失败可安全重跑。应用层先规整
  （跳过空拼音/超长值），IGNORE 只会命中重复键。

接口（契约 §3-E）：
  ensure_wordforms_tables / resolve_form / load_pinyin_from_zh_dict
  另有只读辅助 plan_pinyin_load（非契约签名，供灌库脚本 --dry-run
  预估新增行数，不写库）。

降级：
  数据库不可用时 resolve_form 返回 []、load_pinyin_from_zh_dict 与
  plan_pinyin_load 返回 0 / 空口径，只记日志不抛异常；ensure 被拒
  只记 error 日志。

安全规则：
  1. SQL 一律参数化（唯一拼接是 LIMIT 的纯整数占位符）；
  2. 入参应用层先校验：空/超长 form 直接返回 []，不进数据库；
  3. form / lemma_word 用 utf8mb4_bin（同 zh_dict_entries 决策）：
     unicode_ci 会折叠声调符号（pǎo = pao）与 CJK 扩展区字符，
     词形还原要求精确区分（拼音检索是「查调」不是「查音节」）。
"""

import logging
from typing import Any, Dict, List

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（契约 §3-E 表设计原样）
# ============================================
# kind：词形三类型（平台架构设计规范 §6 D①）。
KIND_INFLECTION = "inflection"  # 屈折（后续批次灌入）
KIND_VARIANT = "variant"        # 异体（后续批次灌入）
KIND_PINYIN = "pinyin"          # 拼音（现汉词条灌入）
KINDS = (KIND_INFLECTION, KIND_VARIANT, KIND_PINYIN)

# 字段长度上限（与 DDL 一致；zh_dict_entries.pinyin 是 VARCHAR(128)，
# 超过 80 的拼音词条跳过并在 plan/日志中计数——不截断，拼音截断无意义）
MAX_LEMMA_LEN = 80   # lemma_word VARCHAR(80)
MAX_FORM_LEN = 80    # form VARCHAR(80)

# 批量插入批大小（同 zh_dict.replace_zh_dict 口径，控制事务大小）
BATCH_SIZE = 5000

WORDFORMS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS wordforms (
  id INT AUTO_INCREMENT PRIMARY KEY,
  lemma_word VARCHAR(80) CHARACTER SET utf8mb4
    COLLATE utf8mb4_bin NOT NULL
    COMMENT '词条头词（现汉词目字符串；二进制排序保留声调/CJK 扩展区区分）',
  form VARCHAR(80) CHARACTER SET utf8mb4
    COLLATE utf8mb4_bin NOT NULL
    COMMENT 'surface 词形（屈折/异体/拼音），resolve_form 精确匹配键',
  kind ENUM('inflection','variant','pinyin') NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wordforms (lemma_word, form, kind),
  INDEX idx_wordforms_form (form)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 建表
# ============================================
def ensure_wordforms_tables() -> None:
    """幂等创建 wordforms 表（契约 §3-E 表设计原样，可重复调用）。

    无外键依赖（lemma_word 是词目字符串软引用），可独立先行建表；
    被数据库拒绝（无权限等）只记 error 日志不抛异常。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(WORDFORMS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"wordforms 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"wordforms 表初始化意外错误: {e}")


# ============================================
# 词形还原（检索端取数入口）
# ============================================
def resolve_form(form: str) -> List[Dict[str, Any]]:
    """词形还原：form 精确匹配 → 词目行清单（契约 §3-E）。

    按 form 精确匹配（utf8mb4_bin：大小写与声调符号敏感 —— 'pao' 查
    不到 'pǎo'）。同一 form 可能还原出多行（不同 kind 同形、或多词目
    同拼音），全部返回，交由检索端按 kind / 词频决定排序。

    Args:
        form: surface 词形（非空 str，≤80 字符；去首尾空白后匹配）

    Returns:
        list[dict]: [{id, lemma_word, form, kind, created_at}]；
        form 非法或数据库不可用返回 []。
    """
    if not isinstance(form, str):
        logger.error(f"resolve_form 拒绝非法 form: {form!r}（str）")
        return []
    cleaned = form.strip()
    if not cleaned:
        logger.error("resolve_form 拒绝空 form")
        return []
    if len(cleaned) > MAX_FORM_LEN:
        logger.error(f"resolve_form 拒绝超长 form（>{MAX_FORM_LEN} 字符）")
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT id, lemma_word, form, kind, created_at
                   FROM wordforms WHERE form = %s""",
                (cleaned,),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(f"词形还原查询失败（form={cleaned!r}）: {e}")
        return []
    except Exception as e:
        logger.error(f"词形还原查询意外错误: {e}")
        return []


# ============================================
# 拼音词形灌入（scripts/load_wordforms.py 调用）
# ============================================
def _iter_pinyin_rows() -> Any:
    """生成器：zh_dict_entries → (lemma, pinyin) 候选对。

    只取 lemma/pinyin 均非空且长度合法的对；超长/空值跳过并在调用方
    计数（应用层先规整，保证后续 INSERT IGNORE 只命中重复键）。
    zh_dict_entries 表不存在（现汉未灌库）时抛 pymysql.Error，由调用方捕获。
    """
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT lemma, pinyin FROM zh_dict_entries "
            "WHERE lemma IS NOT NULL AND lemma <> '' "
            "AND pinyin IS NOT NULL AND pinyin <> ''"
        )
        for row in cursor.fetchall():
            lemma = str(row["lemma"]).strip()
            pinyin = str(row["pinyin"]).strip()
            if not lemma or not pinyin:
                continue
            yield lemma, pinyin


def plan_pinyin_load() -> Dict[str, Any]:
    """预估 load_pinyin_from_zh_dict 的灌入规模（**只读，不写库**）。

    灌库脚本 --dry-run 用：候选行（现汉拼音词形）与 wordforms 已有
    kind='pinyin' 行做差集，得到 would_add（真跑将新增的行数）。
    wordforms 表尚未建时按空表口径（existing=0）—— 预演不触发任何
    DDL/DML；zh_dict_entries 缺失/不可查时返回全 0 口径（调用方据此
    提示先灌现汉词条）。

    Returns:
        dict: {candidates, existing, would_add, skipped_long, skipped_empty}
        （skipped_long=现汉侧超长被跳过数；skipped_empty=空拼音词条数，
        现库口径下 SQL 已过滤空值，故恒为 0，保留键以对齐脚本输出）。
    """
    plan = {
        "candidates": 0,
        "existing": 0,
        "would_add": 0,
        "skipped_long": 0,
        "skipped_empty": 0,
    }
    try:
        seen: set = set()
        for lemma, pinyin in _iter_pinyin_rows():
            if len(lemma) > MAX_LEMMA_LEN or len(pinyin) > MAX_FORM_LEN:
                plan["skipped_long"] += 1
                continue
            plan["candidates"] += 1
            seen.add((lemma, pinyin))
    except pymysql.Error as e:
        logger.error(f"预估拼音灌入失败（现汉词条表就绪了吗？）: {e}")
        return {k: 0 for k in plan}
    except Exception as e:
        logger.error(f"预估拼音灌入意外错误: {e}")
        return {k: 0 for k in plan}
    try:
        with get_db_cursor() as cursor:
            # 表存在性先查 information_schema（只读）：wordforms 未建时按空表
            # 口径返回，不让 1146 在连接层抛 ERROR 日志噪音（预演不建表）
            cursor.execute(
                """SELECT COUNT(*) AS n FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'wordforms'"""
            )
            if int(cursor.fetchone()["n"] or 0) == 0:
                existing_pairs: set = set()
            else:
                cursor.execute(
                    "SELECT lemma_word, form FROM wordforms WHERE kind = 'pinyin'"
                )
                existing_pairs = {
                    (str(r["lemma_word"]), str(r["form"]))
                    for r in cursor.fetchall()
                }
    except pymysql.Error as e:
        logger.error(f"预估拼音灌入失败（读 wordforms）: {e}")
        return {k: 0 for k in plan}
    plan["existing"] = len(existing_pairs)
    plan["would_add"] = len(seen - existing_pairs)
    return plan


def load_pinyin_from_zh_dict() -> int:
    """从现汉词条表（zh_dict_entries）灌拼音词形，幂等（契约 §3-E）。

    每个有拼音的读音条目写一条词形行：
        lemma_word = zh_dict_entries.lemma
        form       = zh_dict_entries.pinyin
        kind       = 'pinyin'
    多音字每读音一条（跑 páo / pǎo → 两行，同一 lemma_word）。

    幂等策略见模块 docstring：UNIQUE(lemma_word, form, kind) +
    INSERT IGNORE，重复运行不产生重复行。调用前自动 ensure（表缺失
    时自建）；zh_dict_entries 不存在或为空时返回 0 并记 error 日志
    （先跑 scripts/load_zh_dict.py）。

    Returns:
        int: **本次新增行数**（首灌 ≈ 有效词条数；重复运行返回 0，
        即「0 新增」是幂等的成功态而非失败）。数据库不可用返回 0。
    """
    ensure_wordforms_tables()
    inserted = 0
    try:
        # 分批收集候选（70k+ 行不宜一次 executemany）
        batch: List[tuple] = []
        skipped_long = 0
        for lemma, pinyin in _iter_pinyin_rows():
            if len(lemma) > MAX_LEMMA_LEN or len(pinyin) > MAX_FORM_LEN:
                skipped_long += 1
                continue
            batch.append((lemma, pinyin, KIND_PINYIN))
            if len(batch) >= BATCH_SIZE:
                inserted += _insert_ignore_rows(batch)
                batch = []
        if batch:
            inserted += _insert_ignore_rows(batch)
        if skipped_long:
            logger.warning(
                f"load_pinyin_from_zh_dict 跳过超长词条 {skipped_long} 条"
                f"（lemma/pinyin > {MAX_LEMMA_LEN}/{MAX_FORM_LEN} 字符）"
            )
        logger.info(f"load_pinyin_from_zh_dict 完成：本次新增 {inserted} 行")
        return inserted
    except pymysql.Error as e:
        logger.error(f"拼音词形灌入失败（MySQL；现汉词条表就绪了吗？）: {e}")
        return inserted
    except Exception as e:
        logger.error(f"拼音词形灌入意外错误: {e}")
        return inserted


def _insert_ignore_rows(rows: List[tuple]) -> int:
    """一批 INSERT IGNORE 写入，返回真实新增行数（rowcount 不计被忽略行）。"""
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.executemany(
                """INSERT IGNORE INTO wordforms (lemma_word, form, kind)
                   VALUES (%s, %s, %s)""",
                rows,
            )
            added = int(cursor.rowcount or 0)
        return added
    except pymysql.Error as e:
        logger.error(f"拼音词形批量写入失败（一批 {len(rows)} 行）: {e}")
        return 0
