#!/usr/bin/env python3
"""把 data/corpus/llm_screening/*.json 的 LLM 初筛草稿灌入 domain_family_senses。

标注平台（app.py）在义位卡片上显示「LLM 初筛草稿（候选参考，须人工确认）」：
准入标签 / 图式候选 / 对齐候选 / 理由 / 存疑点。数据源是
data/corpus/llm_screening/<verb>.json（scripts/archive/llm_sense_screening.py
的历史产出，136 词的义位级初筛）。

列（v11 迁移新增）：llm_tag / llm_schema / llm_align / llm_reason / llm_doubt。
按 (word, sense_num) 关联 —— SenseID「动词-Sn」拆成两列，与 domain_family_senses
主键对齐；表里没有的义位跳过并计数（初筛词表与域系表版本差异属正常）。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/load_llm_screening.py            # 全量刷新
    MYSQL_HOST=127.0.0.1 python3 scripts/load_llm_screening.py --if-empty  # 仅空列时灌入
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mysql_db  # noqa: E402

SCREENING_DIR = ROOT / "data" / "corpus" / "llm_screening"


def llm_screening_ready() -> bool:
    """llm_* 草稿列是否已有数据。"""
    try:
        with mysql_db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM domain_family_senses "
                "WHERE llm_tag IS NOT NULL")
            return int(cursor.fetchone()["n"] or 0) > 0
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入 LLM 初筛草稿列")
    parser.add_argument("--if-empty", action="store_true",
                        help="仅当 llm_tag 列全空时写入")
    args = parser.parse_args()

    if not SCREENING_DIR.is_dir():
        print(f"初筛目录不存在: {SCREENING_DIR}")
        return 1
    if args.if_empty and llm_screening_ready():
        print("llm_* 草稿列已有数据，跳过（--if-empty）。")
        return 0

    if not mysql_db.init_database():
        print("数据库初始化失败。")
        return 1

    n_updated, n_missing, n_files = 0, 0, 0
    try:
        with mysql_db.get_db_cursor(autocommit=False) as cursor:
            # 现有义位索引：(word, sense_num) → 存在性
            cursor.execute("SELECT word, sense_num FROM domain_family_senses")
            known = {(r["word"], int(r["sense_num"])) for r in cursor.fetchall()}

            for path in sorted(SCREENING_DIR.glob("*.json")):
                n_files += 1
                data = json.loads(path.read_text(encoding="utf-8"))
                for sid, result in (data.get("results") or {}).items():
                    try:
                        word, _, num = sid.rpartition("-S")
                        sense_num = int(num)
                    except ValueError:
                        continue
                    if (word, sense_num) not in known:
                        n_missing += 1
                        continue
                    cursor.execute(
                        """UPDATE domain_family_senses
                           SET llm_tag = %s, llm_schema = %s, llm_align = %s,
                               llm_reason = %s, llm_doubt = %s
                           WHERE word = %s AND sense_num = %s""",
                        (str(result.get("准入标签") or "") or None,
                         str(result.get("意象图式候选标签") or "") or None,
                         str(result.get("英汉对齐候选等级") or "") or None,
                         str(result.get("理由") or "") or None,
                         str(result.get("备注存疑点") or "") or None,
                         word, sense_num))
                    n_updated += 1
    except Exception as e:
        print(f"灌入失败: {e}")
        return 1

    print(f"已灌入 LLM 初筛草稿: {n_updated} 义位（{n_files} 个文件；"
          f"{n_missing} 条 SenseID 不在域系表，跳过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
