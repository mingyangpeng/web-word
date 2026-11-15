#!/usr/bin/env python3
"""build_defining_vocab.py —— 定义词表候选构建（语料高频词自动提取）。

背景（批次 50）：configs/style.yaml 的 defining_vocab.vocab_file 一直占位
「待编者核定」→ 体例质检 DEFINING_VOCAB 项 fail（词表为空）——质检唯一 fail。

本脚本做什么（**确定性统计，非学术判断**）：
    1. 从释义语料（definitions.en_ndef ＋ oald_senses.definition，两表英文
       释义正文）提取全部英文词（[a-z'] 分词，casefold 计频）；
    2. 词频降序排序，取频次 ≥ min_freq（默认 2——只出现一次的词多为专名/
       拼写噪声，不进受控定义词表）构成候选词表；
    3. 写 configs/defining_vocab.txt（一行一词，频次注释在文件头）；
    4. style.yaml 的 defining_vocab.vocab_file 指向该文件（**编者核定语义
       保留**：初版=语料高频自动提取，编者在「📝 词表核定」页增删后即为
       定稿——增删记录随 git 留痕）。

编者核定流（后续人工动作，非本脚本）：
    词典管理区「📝 词表核定」页：浏览词表（含频次）→ 增删词 → 写回 txt
    → 质检即时反映。受控定义词表的语言学充分性（该不该用 X 解释 Y）始终
    由编者判断，本脚本只把「从零整理词表」的体力活机械化。

用法：
    python scripts/build_defining_vocab.py [--min-freq 2] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VOCAB_FILE = ROOT / "configs" / "defining_vocab.txt"
STYLE_FILE = ROOT / "configs" / "style.yaml"

WORD_RE = re.compile(r"[a-z']+")


def fetch_corpus_definitions() -> List[str]:
    """取释义语料英文正文（definitions.en_ndef ＋ oald_senses.definition）。

    连接参数照 mysql_db._setting 口径（env → yaml → 默认）；宿主直跑默认
    127.0.0.1:3306（容器映射）或 3307（测试双轨）——按 .env/config 解析，
    与应用同一套 mysql_db.get_db_cursor（fail-open：库不可用返回空＋提示）。
    """
    from src.mysql_db import get_db_cursor

    texts: List[str] = []
    queries = (
        "SELECT en_ndef FROM definitions WHERE en_ndef IS NOT NULL AND en_ndef <> ''",
        "SELECT definition FROM oald_senses WHERE definition IS NOT NULL AND definition <> ''",
    )
    with get_db_cursor() as cursor:
        for q in queries:
            try:
                cursor.execute(q)
                # DictCursor 返回 dict 行——取首个（唯一列）值；tuple 形态兼容取 [0]
                for row in cursor.fetchall():
                    val = next(iter(row.values())) if isinstance(row, dict) else row[0]
                    texts.append(str(val))
            except Exception as e:  # noqa: BLE001 —— 单表缺失按空处理（迁移前旧库）
                print(f"  ⚠ 取数失败（{q.split('FROM')[1].strip()[:30]}…）: {e}")
    return texts


def count_words(texts: List[str]) -> Counter:
    """分词计频：[a-z']+ 提取、casefold 归一（与质检 casefold 计重同口径）。"""
    counter: Counter = Counter()
    for text in texts:
        for tok in WORD_RE.findall(text.lower()):
            counter[tok] += 1
    return counter


def build_vocab(counter: Counter, min_freq: int) -> List[Tuple[str, int]]:
    """候选词表：频次 ≥ min_freq 的词按（频次降序，字典序升序）排列。"""
    pairs = [(w, c) for w, c in counter.items() if c >= min_freq]
    pairs.sort(key=lambda x: (-x[1], x[0]))
    return pairs


def write_vocab_file(pairs: List[Tuple[str, int]], dry_run: bool) -> None:
    """写词表 txt（一行一词；头部注释记来源与频次分布摘要）。"""
    total = sum(c for _, c in pairs)
    header = (
        "# 定义词表（defining vocabulary）—— 初版由语料高频词自动提取\n"
        f"# 生成：scripts/build_defining_vocab.py（语料 = definitions.en_ndef +\n"
        f"# oald_senses.definition；词条 {len(pairs)}，总出现 {total} 次）\n"
        "# 编者核定：在词典管理区「📝 词表核定」页增删词（写回本文件，git 留痕）；\n"
        "# 受控定义词表的语言学充分性始终由编者判断——本文件只是体力活机械化。\n"
    )
    body = "\n".join(w for w, _ in pairs) + "\n"
    if dry_run:
        print(f"  [dry-run] 将写 {VOCAB_FILE}：{len(pairs)} 词（前 10："
              f"{', '.join(w for w, _ in pairs[:10])}）")
        return
    VOCAB_FILE.write_text(header + body, encoding="utf-8")
    print(f"  ✓ 词表写入 {VOCAB_FILE}：{len(pairs)} 词")


def point_style_yaml(dry_run: bool) -> None:
    """style.yaml 的 vocab_file 指向词表文件（占位「待编者核定」→ 真路径）。"""
    s = STYLE_FILE.read_text(encoding="utf-8")
    old = "vocab_file: 待编者核定"
    new = ("vocab_file: defining_vocab.txt   # 词表本体（初版=语料高频自动提取，\n"
           "                                  # 编者在「📝 词表核定」页增删定稿）")
    if old in s:
        if dry_run:
            print("  [dry-run] 将更新 style.yaml vocab_file → defining_vocab.txt")
        else:
            STYLE_FILE.write_text(s.replace(old, new, 1), encoding="utf-8")
            print("  ✓ style.yaml vocab_file 已指向 defining_vocab.txt")
    elif "defining_vocab.txt" in s:
        print("  ✓ style.yaml 已指向 defining_vocab.txt（幂等跳过）")
    else:
        print("  ⚠ style.yaml 无 vocab_file 占位——请人工核对（未改动）")


def main() -> int:
    ap = argparse.ArgumentParser(description="定义词表候选构建（语料高频自动提取）")
    ap.add_argument("--min-freq", type=int, default=2,
                    help="入表最低频次（默认 2；单次出现的词多为专名/噪声）")
    ap.add_argument("--dry-run", action="store_true", help="只预览不落盘")
    args = ap.parse_args()

    print("① 取释义语料（definitions.en_ndef ＋ oald_senses.definition）")
    texts = fetch_corpus_definitions()
    if not texts:
        print("  ✗ 释义语料为空——检查数据库连接/灌库状态（./start status）")
        return 1
    print(f"  ✓ 释义正文 {len(texts)} 条")

    print("② 分词计频（casefold，与质检计重同口径）")
    counter = count_words(texts)
    print(f"  ✓ 不同词 {len(counter)} 个（总出现 {sum(counter.values())} 次）")

    print(f"③ 构建候选词表（min_freq={args.min_freq}）")
    pairs = build_vocab(counter, args.min_freq)
    if len(pairs) < 10:
        print(f"  ✗ 候选仅 {len(pairs)} 词（<10）——词表规模不足，质检仍会 warn；"
              "检查语料量或调低 --min-freq")
        return 1

    write_vocab_file(pairs, args.dry_run)
    point_style_yaml(args.dry_run)

    print("④ 质检验证（DEFINING_VOCAB 项）")
    if args.dry_run:
        print("  [dry-run] 跳过")
        return 0
    from src.style_check import check_defining_vocab
    import yaml as _yaml
    style = _yaml.safe_load(STYLE_FILE.read_text(encoding="utf-8"))
    item = check_defining_vocab(style)
    print(f"  DEFINING_VOCAB → {item.get('status')}: {item.get('note', '')[:90]}")
    return 0 if item.get("status") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
