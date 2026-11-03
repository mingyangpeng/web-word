#!/usr/bin/env python3
"""把结构化的《现汉7》词典 JSON 灌入 MySQL 的 zh_dict_* 3 表。

数据链：data/ModernChineseDict/mdx/dict.mdx.txt
   → scripts/parse_modern_chinese_dict.py → data/zh_dict_senses.json → 本脚本。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/load_zh_dict.py            # 全量替换
    MYSQL_HOST=127.0.0.1 python3 scripts/load_zh_dict.py --if-empty  # 仅空表时灌入
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mysql_db, zh_dict  # noqa: E402

JSON_PATH = ROOT / "data" / "zh_dict_senses.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入《现汉7》结构化词典")
    parser.add_argument("--if-empty", action="store_true", help="仅当表为空时写入")
    args = parser.parse_args()

    if not JSON_PATH.exists():
        print(f"结构化 JSON 不存在: {JSON_PATH}")
        print("先运行: python3 scripts/parse_modern_chinese_dict.py")
        return 1

    if args.if_empty and zh_dict.zh_dict_ready():
        print("zh_dict_* 已有数据，跳过（--if-empty）。")
        return 0

    with open(JSON_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    print(f"读入 {len(entries)} 个词条（读音条目）")

    if not mysql_db.init_database():
        print("数据库初始化失败。")
        return 1

    counts = zh_dict.replace_zh_dict(entries)
    print(f"已灌入: {counts}")

    # 校验：跑范畴 19 词条应全部可查
    ok = all(zh_dict.lookup_lemma(w) for w in
             ["跑", "奔跑", "奔驰", "驰骋", "逃逸"])
    print("抽查 跑/奔跑/奔驰/驰骋/逃逸:", "全部可查 ✓" if ok else "存在缺失 ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
