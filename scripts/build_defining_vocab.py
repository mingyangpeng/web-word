#!/usr/bin/env python3
"""build_defining_vocab.py —— 定义词表候选构建（语料高频词自动提取）。

薄壳（批次 51）：构建函数单一事实源在 src/style_check.py（fetch_corpus_
definitions / count_corpus_words / build_corpus_vocab）——本脚本只做 CLI
编排（取数→计频→构建→写 configs/defining_vocab.txt→style.yaml 指向→
质检验证）。编者核定流在词典管理区「📝 词表核定」页。

用法：
    python scripts/build_defining_vocab.py [--min-freq 2] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.style_check import (  # noqa: E402 —— 薄壳复用质检模块的词表构建函数
    build_corpus_vocab,
    check_defining_vocab,
    count_corpus_words,
    fetch_corpus_definitions,
)

VOCAB_FILE = ROOT / "configs" / "defining_vocab.txt"
STYLE_FILE = ROOT / "configs" / "style.yaml"


def write_vocab_file(pairs, dry_run: bool) -> None:
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
    """style.yaml 的 vocab_file 指向词表文件（幂等）。"""
    s = STYLE_FILE.read_text(encoding="utf-8")
    if "configs/defining_vocab.txt" in s:
        print("  ✓ style.yaml 已指向 defining_vocab.txt（幂等跳过）")
        return
    old = "vocab_file: 待编者核定"
    new = ("vocab_file: configs/defining_vocab.txt   # 词表本体（仓库根相对；初版=语料高频自动提取，\n"
           "                                         # 编者在「📝 词表核定」页增删定稿）")
    if old in s:
        if dry_run:
            print("  [dry-run] 将更新 style.yaml vocab_file")
        else:
            STYLE_FILE.write_text(s.replace(old, new, 1), encoding="utf-8")
            print("  ✓ style.yaml vocab_file 已指向 defining_vocab.txt")
    else:
        print("  ⚠ style.yaml 无占位也无现路径——请人工核对（未改动）")


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
    counter = count_corpus_words(texts)
    print(f"  ✓ 不同词 {len(counter)} 个（总出现 {sum(counter.values())} 次）")

    print(f"③ 构建候选词表（min_freq={args.min_freq}）")
    pairs = build_corpus_vocab(counter, args.min_freq)
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
    import yaml as _yaml
    style = _yaml.safe_load(STYLE_FILE.read_text(encoding="utf-8"))
    item = check_defining_vocab(style)
    print(f"  DEFINING_VOCAB → {item.get('status')}: {item.get('note', '')[:90]}")
    return 0 if item.get("status") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
