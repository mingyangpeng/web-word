#!/usr/bin/env python3
"""导出论文公开版数据包 —— 与投稿声明口径一致（SenseID + 标签 + 统计层）。

投稿声明（docs/research/papers/series/投稿包/通用声明块.md）承诺：公开版本只含 SenseID、标签与
统计层，不含 OALD10 与《现汉7》词典原文（版权限制）。本脚本从数据库导出
恰好这一范围的数据，写入 docs/research/papers/series/投稿包/数据包/：

  01_义位清单_英.xlsx   SenseID / 词目 / 义项号 / 标签 / 主体 / 语体 / 判定（不含释义例句）
  02_义位清单_汉.xlsx   同上（汉语侧，含三态判定）
  03_特征编码矩阵.xlsx  SenseID × P1..C1（15 维聚类特征）+ A1..A3 核验列
  04_聚类结果.xlsx      英汉各簇：簇号 / 簇名 / 规模 / 特征画像 / 成员 SenseID
  05_跨语言对齐.xlsx    英簇 ↔ 汉簇 / 簇中心距离 / 四类判定
  06_统计汇总.xlsx      各表行数与关键统计（域系分布、判定漏斗、簇规模）

不含：词典释义与例句原文（dictionary.db / OALD10 / 现汉7 mdx 的文本）。

用法：
    python3 scripts/export_paper_dataset.py            # 导出并写入投稿包
    python3 scripts/export_paper_dataset.py --stdout   # 只打印清单不写文件
"""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402

from src.mysql_db import get_db_cursor  # noqa: E402

OUT_DIR = ROOT / "docs" / "research" / "papers" / "series" / "投稿包" / "数据包"


def _fetch(cursor, sql, params=()):
    cursor.execute(sql, params)
    return list(cursor.fetchall())


def build_sheets(cursor):
    """返回 [(sheet 名, 表头 list, 行 list)]。"""
    sheets = []

    # 01/02 义位清单（无词典原文）
    for lang, name in (("en", "01_义位清单_英"), ("zh", "02_义位清单_汉")):
        rows = _fetch(cursor, """
            SELECT l.lemma, s.sense_no, s.sense_label, s.subject_type,
                   s.register, s.tag, s.status
            FROM cs_senses s JOIN cs_lexemes l ON s.lexeme_id = l.id
            WHERE l.language = %s
            ORDER BY l.lemma, s.sense_no""", (lang,))
        sid = lambda r: f"{r['lemma']}-S{r['sense_no'] or '1'}"
        sheets.append((name,
                       ["SenseID", "词目", "义项号", "标签", "主体类型",
                        "语体", "标注", "判定"],
                       [[sid(r), r["lemma"], r["sense_no"], r["sense_label"],
                         r["subject_type"], r["register"], r["tag"],
                         r["status"]] for r in rows]))

    # 03 特征编码矩阵（数值本身不含词典文本）
    rows = _fetch(cursor, """
        SELECT l.lemma, s.sense_no, f.feature_code, f.value, f.in_clustering
        FROM cs_sense_features f
        JOIN cs_senses s ON f.sense_id = s.id
        JOIN cs_lexemes l ON s.lexeme_id = l.id
        ORDER BY l.language DESC, l.lemma, s.sense_no, f.feature_code""")
    matrix = {}
    order = []
    for r in rows:
        sid = f"{r['lemma']}-S{r['sense_no'] or '1'}"
        if sid not in matrix:
            matrix[sid] = {"lang": "英" if r["lemma"] and
                           all('\u4e00' <= ch <= '\u9fff' for ch in r["lemma"])
                           else "英", "cells": {}}
            order.append(sid)
        matrix[sid]["cells"][r["feature_code"]] = r["value"]
    codes = ["P1", "P2", "P3", "P4", "P5", "M1a", "M1b", "M1c", "M1d",
             "M2", "M3a", "M3b", "M3c", "M3d", "C1", "A1", "A2", "A3"]
    head = ["SenseID"] + codes
    body = []
    for sid in order:
        cells = matrix[sid]["cells"]
        body.append([sid] + [cells.get(c, "") for c in codes])
    sheets.append(("03_特征编码矩阵", head, body))

    # 04 聚类结果
    rows = _fetch(cursor, """
        SELECT r.language, r.id AS run_id, c.cluster_no, c.name, c.size,
               c.profile
        FROM cs_clusters c JOIN cs_cluster_runs r ON c.run_id = r.id
        ORDER BY r.language DESC, c.cluster_no""")
    cl_head = ["语言", "簇号", "簇名", "规模", "特征画像", "成员 SenseID"]
    cl_body = []
    for r in rows:
        members = _fetch(cursor, """
            SELECT l.lemma, s.sense_no FROM cs_cluster_members m
            JOIN cs_senses s ON m.sense_id = s.id
            JOIN cs_lexemes l ON s.lexeme_id = l.id
            WHERE m.cluster_id = (SELECT id FROM cs_clusters
                                  WHERE run_id = %s AND cluster_no = %s)
            ORDER BY l.lemma""", (r["run_id"], r["cluster_no"]))
        sids = ", ".join(f"{m['lemma']}-S{m['sense_no'] or '1'}"
                         for m in members)
        cl_body.append(["英" if r["language"] == "en" else "汉",
                        r["cluster_no"], r["name"], r["size"],
                        r["profile"], sids])
    sheets.append(("04_聚类结果", cl_head, cl_body))

    # 05 跨语言对齐
    rows = _fetch(cursor, """
        SELECT en.cluster_no en_no, en.name en_name, zh.cluster_no zh_no,
               zh.name zh_name, a.gower_distance, a.verdict
        FROM cs_cluster_alignment a
        JOIN cs_clusters en ON a.en_cluster_id = en.id
        JOIN cs_clusters zh ON a.zh_cluster_id = zh.id
        ORDER BY a.gower_distance""")
    sheets.append(("05_跨语言对齐",
                   ["英簇号", "英簇名", "汉簇号", "汉簇名",
                    "簇中心 Gower 距离", "判定"],
                   [[r["en_no"], r["en_name"], r["zh_no"], r["zh_name"],
                     r["gower_distance"], r["verdict"]] for r in rows]))

    # 06 统计汇总
    dom = _fetch(cursor, "SELECT domain, COUNT(*) n FROM domain_family_senses "
                         "GROUP BY domain ORDER BY n DESC")
    stat_rows = []
    for r in dom:
        stat_rows.append(["域系初判·" + r["domain"], r["n"]])
    for lang, total in (("en", 32), ("zh", 25)):
        stat_rows.append([f"跑范畴{'英' if lang == 'en' else '汉'}义位", total])
    for verdict in ("完全对齐", "部分对齐", "零对齐"):
        n = next((r for r in _fetch(cursor, "SELECT verdict, COUNT(*) n "
                                             "FROM cs_cluster_alignment "
                                             "GROUP BY verdict")
                  if r["verdict"] == verdict), {}).get("n", 0)
        stat_rows.append(["跨语言对齐·" + verdict, n])
    sheets.append(("06_统计汇总", ["统计项", "数值"], stat_rows))
    return sheets


def main() -> int:
    parser = argparse.ArgumentParser(description="导出论文公开版数据包")
    parser.add_argument("--stdout", action="store_true", help="只打印清单不写文件")
    args = parser.parse_args()

    if not mysql_ready():
        print("数据库不可用，先运行 ./develop.sh")
        return 1

    with get_db_cursor() as cursor:
        sheets = build_sheets(cursor)

    print(f"数据包 {len(sheets)} 张表：")
    for name, head, body in sheets:
        print(f"  {name}: {len(body)} 行 × {len(head)} 列")
    if args.stdout:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    import openpyxl
    for name, head, body in sheets:
        wb = Workbook()
        ws = wb.active
        ws.title = name[:31]
        ws.append(head)
        for row in body:
            ws.append(row)
        out = OUT_DIR / f"{name}.xlsx"
        wb.save(out)
    readme = OUT_DIR / "README.txt"
    readme.write_text(
        f"web-word 论文公开版数据包（生成日期 {date.today()}）\n"
        f"\n口径与投稿声明一致：仅含 SenseID、标签与统计层，"
        f"不含 OALD10 与《现汉7》词典原文。\n"
        f"完整数据（含词典文本）因版权限制不随包分发，联系通讯作者获取。\n"
        f"复现：仓库 scripts/export_paper_dataset.py 可从数据库重新生成本目录。\n",
        encoding="utf-8")
    print(f"\n已写入 {OUT_DIR}（含 README.txt 口径说明）")
    return 0


def mysql_ready() -> bool:
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return False


if __name__ == "__main__":
    sys.exit(main())
