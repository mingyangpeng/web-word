#!/usr/bin/env python3
"""把《现汉7》词条拼音灌成词形表（wordforms，kind='pinyin'）。

数据链：zh_dict_entries（现汉读音条目，scripts/load_zh_dict.py 灌入）
   → src/wordforms_db.load_pinyin_from_zh_dict()（每词条写一条
     kind='pinyin' 词形：lemma_word=词目, form=拼音）
   → 检索词形还原（批次 2：检索框输入拼音 → wordforms_db.resolve_form
     → 词目）。

幂等：wordforms 的 UNIQUE(lemma_word, form, kind) + INSERT IGNORE——
重复运行不产生重复行、返回值（本次新增行数）为 0 即幂等成功态。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/load_wordforms.py            # 灌入
    MYSQL_HOST=127.0.0.1 python3 scripts/load_wordforms.py --dry-run  # 预演，不写库
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import wordforms_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入《现汉7》拼音词形（幂等）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只预估不写库（候选/已有/将新增行数）")
    args = parser.parse_args()

    plan = wordforms_db.plan_pinyin_load()
    if plan["candidates"] == 0 and plan["existing"] == 0:
        print("zh_dict_entries 无拼音候选且 wordforms 为空（全 0 口径亦可能是"
              "数据库不可用——查上方 ERROR 日志确认）。")
        print("若词条未灌：先运行 python3 scripts/load_zh_dict.py")
        return 1

    print(f"拼音词形候选 {plan['candidates']} 条"
          f"（跳过超长 {plan['skipped_long']} 条），"
          f"wordforms 已有 kind='pinyin' {plan['existing']} 行，"
          f"将新增 {plan['would_add']} 行")

    if args.dry_run:
        print("已按 --dry-run 预演结束，未写库。")
        return 0

    inserted = wordforms_db.load_pinyin_from_zh_dict()
    print(f"本次新增词形 {inserted} 行（重复运行返回 0 = 幂等成功）")

    # 抽查：resolve_form 对已灌词形应能还原
    ok = _spot_check()
    print("抽查词形还原:", "通过 ✓" if ok else "未通过 ✗")
    return 0 if ok else 1


def _spot_check() -> bool:
    """取几个现汉词条，resolve_form(拼音) 应还原出对应词目。"""
    try:
        from src.mysql_db import get_db_cursor

        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT lemma, pinyin FROM zh_dict_entries "
                "WHERE pinyin IS NOT NULL AND pinyin <> '' "
                "ORDER BY id LIMIT 5"
            )
            samples = list(cursor.fetchall())
        if not samples:
            return True  # 没有可抽查的词条（空库不判失败）
        for row in samples:
            hits = wordforms_db.resolve_form(str(row["pinyin"]))
            lemmas = {h["lemma_word"] for h in hits}
            if str(row["lemma"]) not in lemmas:
                print(f"  未还原: {row['lemma']!r} ← {row['pinyin']!r}")
                return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  抽查执行失败: {e}")
        return False


if __name__ == "__main__":
    sys.exit(main())
