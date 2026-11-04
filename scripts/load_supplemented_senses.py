#!/usr/bin/env python3
"""把 4 条人工补充义位（scutter/kayak/oar/dodder）灌入 oald_senses。

背景：研究词表共 996 义位 = 992 条 OALD10 + 4 条人工补充（见
docs/词表版本说明.md —— 这 4 词的义项 OALD10 未收录，据 Levin brief 与
BCC 语料人工撰写）。补充义位的定稿在
data/corpus/sense_sheets/<词>_义项.xlsx（与 171 词的义位标注表同构）。

此前 load_word_library.py 只灌 OALD 来源，这 4 条在标注平台缺行 ——
word_source 子集快照/全库词典都覆盖不了它们。本脚本按 oald_senses 的
表结构写入（source='人工补充'，is_idiom=0），幂等（先删该 4 词的
同源行再插）。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/load_supplemented_senses.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook  # noqa: E402

from src import mysql_db  # noqa: E402

SUPPLEMENT_WORDS = ["scutter", "kayak", "oar", "dodder"]
SHEET_DIR = ROOT / "data" / "corpus" / "sense_sheets"
SOURCE_TAG = "人工补充"


def read_senses() -> list:
    """4 个 xlsx → [{verb, sense_index, definition, examples, source}, ...]"""
    out = []
    for verb in SUPPLEMENT_WORDS:
        path = SHEET_DIR / f"{verb}_义项.xlsx"
        wb = load_workbook(path, read_only=True)
        ws = wb[wb.sheetnames[0]]
        for r in ws.iter_rows(min_row=2, values_only=True):
            if not r[0] or not str(r[0]).startswith(f"{verb}-S"):
                continue
            # 列序（表头）：SenseID/词目/义项序号/来源/及物性/英文释义/例句/
            # 句法模式/是否习语/原型义/原型主导义简述/意象图式/准入标签/判定理由/备注
            definition = str(r[5] or "").strip()
            # 释义前缀「（OALD10 动词义项未收录；据词表 levin-brief 与 BCC 撰写）」
            # 保留原文 —— 来源与撰写依据是判定可回溯性的一部分
            examples = [e for e in str(r[6] or "").split("\n") if e.strip()]
            grammar = str(r[4] or "").strip() or None
            out.append({
                "verb": str(r[1]).strip(),
                "sense_index": int(str(r[2]).strip().lstrip("S")),
                "definition": definition,
                "grammar": grammar,
                "examples": examples,
            })
        wb.close()
    return out


def main() -> int:
    senses = read_senses()
    print(f"解析人工补充义位 {len(senses)} 条："
          f"{[(s['verb'], s['sense_index']) for s in senses]}")
    if len(senses) != 4:
        print("⚠ 预期 4 条（每词 1 条），数量异常，中止。")
        return 1

    if not mysql_db.init_database():
        print("数据库初始化失败。")
        return 1

    try:
        with mysql_db.get_db_cursor(autocommit=False) as cursor:
            for s in senses:
                cursor.execute("SELECT id FROM definitions WHERE verb = %s",
                               (s["verb"],))
                row = cursor.fetchone()
                if not row:
                    print(f"⚠ {s['verb']} 不在 definitions，跳过")
                    continue
                did = int(row["id"])
                # 幂等：先删同词同序号的「人工补充」行再插（不动 OALD 行）
                cursor.execute(
                    """DELETE FROM oald_senses
                       WHERE definition_id = %s AND sense_index = %s
                         AND source = %s""",
                    (did, s["sense_index"], SOURCE_TAG))
                cursor.execute(
                    """INSERT INTO oald_senses
                       (definition_id, sense_index, definition, grammar,
                        examples, example_patterns, is_idiom, headword, source)
                       VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s)""",
                    (did, s["sense_index"], s["definition"], s["grammar"],
                     json.dumps(s["examples"], ensure_ascii=False),
                     json.dumps([], ensure_ascii=False),
                     s["verb"], SOURCE_TAG))
        print(f"已灌入 {len(senses)} 条人工补充义位（source={SOURCE_TAG}）。")
        return 0
    except Exception as e:
        print(f"灌入失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
