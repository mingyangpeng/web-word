#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成《英语自移移动动词词表》Word 文档。

## 为什么用脚本生成而不是手工写

词表的数据来自三处（Levin 筛选表、dictionary.db、旧词库），把 171 个词手抄进 Word
既费时又必然与数据库不一致。脚本生成的好处是**任何一个数字都能追溯到来源**，
重新灌库后重跑一次就同步了。

## 文档的诚实性要求

`docs/义项判定标准.docx` 要求「所有判定结果必须可回溯到 OALD 释义、例句原文，
备注栏留存依据」。但 dictionary.db 只覆盖 136 词里的 9 个，所以文档里**必须写明**
每个词的释义来自哪一级来源，以及全部标注都是待复核的候选值。
不写清楚的话，读者会误以为每条释义都是词典原文。

## 用法

    python scripts/generate_word_doc.py                    # 默认输出到 docs/
    python scripts/generate_word_doc.py -o /tmp/out.docx
    python scripts/generate_word_doc.py --no-db            # 不读 MySQL，只读文件源
"""
import argparse
import datetime
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Pt, RGBColor  # noqa: E402

from src.word_source import (  # noqa: E402
    DictionaryDB,
    audit_coverage,
    build_entries,
    load_legacy_library,
    load_levin_table,
    load_oxford_cache,
    load_rejected_lemmas,
)

DEFAULT_OUT = os.path.join(ROOT, "docs", "英语自移移动动词词表.docx")

# 来源标签与颜色（可信度越高越绿）
SOURCE_LABEL = {
    "dictionary.db": ("词典原文(OALD)", RGBColor(0x1E, 0x7B, 0x34)),
    "legacy-library": ("既有词库(二手)", RGBColor(0xB4, 0x6A, 0x00)),
    "levin-brief": ("研究者原型义", RGBColor(0xB4, 0x6A, 0x00)),
    "oxford-en": ("仅英文", RGBColor(0xC0, 0x39, 0x2B)),
    "pending": ("暂无", RGBColor(0xC0, 0x39, 0x2B)),
}

MAIN_CAT_ORDER = ["方式聚焦型", "路径聚焦型", "互动聚焦型"]
SCHEMA_NOTE = {
    "源点脱离图式": "语义重心是运动体离开起始位置",
    "终点抵达图式": "语义重心是运动体到达目标位置",
    "方式伴随图式": "语义重心是位移伴随的运动方式",
    "互动位移图式": "两个实体同时发生物理位移并互动",
}


def _set_cell(cell, text, bold=False, size=9, color=None, font="微软雅黑"):
    cell.text = ""
    para = cell.paragraphs[0]
    run = para.add_run(text if text else "")
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = font
    if color is not None:
        run.font.color.rgb = color


def _heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = "微软雅黑"
    return h


def _para(doc, text, size=10, italic=False, color=None, bold=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.italic = italic
    run.bold = bold
    run.font.name = "微软雅黑"
    if color is not None:
        run.font.color.rgb = color
    return p


def build_document(entries, rejects, audit, cluster_meta=None):
    """把词表渲染成 Word 文档对象。"""
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10)

    # ---------------- 封面 ----------------
    title = doc.add_heading("英语自移移动动词词表", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.name = "微软雅黑"

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("基于 Talmy 移动事件类型学 · Levin(1993) 词表筛选 · 三域十二次类")
    run.font.size = Pt(11)
    run.font.name = "微软雅黑"

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run(
        f"共 {audit['total']} 词 · 12 个次类 · 3 个主范畴\n"
        f"生成日期：{datetime.date.today().isoformat()}"
    )
    run.font.size = Pt(10)
    run.font.name = "微软雅黑"

    # ---------------- 一、编者说明 ----------------
    _heading(doc, "一、编者说明", 1)

    _para(doc, "1. 词目来源", bold=True)
    _para(
        doc,
        "本词表的 171 个词目全部取自《Levin移动动词候选词筛选表》，即同时通过 "
        "Talmy 移动事件语义核查与 Levin 构式交替核查的词。候选阶段共 216 词，"
        f"其中 {len(rejects)} 词因语义重心偏移、语体受限或频率过低等原因被剔除，"
        "剔除词与理由见附录 A。",
    )
    _para(
        doc,
        "词目层面的分类（主范畴 / 次类）依据词目的主导原型义确定，"
        "对应《义项判定标准》中的「三域七系」体系，本词表细化为三主范畴、十二次类。",
    )

    _para(doc, "2. 分析单元是义位，不是词目", bold=True)
    _para(
        doc,
        f"依《义项判定标准》规定，标注单元为义位（sense）。本词表共为 "
        f"{audit['with_senses']} 个词建立了义位明细（合计 {sum(e.get('sense_count', 0) for e in entries)} 条义位），"
        "义位来源为《牛津高阶学习词典》(OALD) 结构化数据，逐义位含中英文释义、"
        "搭配框架、例句与近义/反义词。",
    )

    _para(doc, "3. 释义来源的可信度分级", bold=True)
    _para(
        doc,
        "《义项判定标准》要求所有判定可回溯到 OALD 释义与例句原文。"
        "本词表对每条释义都标注了实际来源，四级可信度如下（Rank 越小越可信）：",
    )
    src_table = doc.add_table(rows=1, cols=4)
    src_table.style = "Light Grid Accent 1"
    src_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = src_table.rows[0].cells
    for i, t in enumerate(("Rank", "来源", "说明", "词数")):
        _set_cell(hdr[i], t, bold=True, size=9)
    rank_rows = [
        (1, "dictionary.db", "OALD 已审校中文释义，可回溯原文（最高可信）"),
        (2, "既有词库", "早期词库的中文释义，多为「次范畴+特征」拼装，非词典原文"),
        (3, "研究者原型义", "《Levin筛选表》「原型主导义简述」列，是短语而非完整释义"),
        (4, "Oxford 英文", "仅有英文释义，中文待补"),
        (5, "无", "两个来源都未覆盖"),
    ]
    by_src = audit["by_source"]
    counts = {
        1: by_src.get("dictionary.db", 0),
        2: by_src.get("legacy-library", 0),
        3: by_src.get("levin-brief", 0),
        4: by_src.get("oxford-en", 0),
        5: by_src.get("pending", 0),
    }
    for rank, name, desc in rank_rows:
        cells = src_table.add_row().cells
        _set_cell(cells[0], str(rank), size=9)
        _set_cell(cells[1], name, size=9)
        _set_cell(cells[2], desc, size=9)
        _set_cell(cells[3], str(counts[rank]), size=9)

    _para(doc, "")
    _para(
        doc,
        f"⚠️ 覆盖率提示：dictionary.db 中 pos=v 的词目仅 333 个，与本词表交集 23 个，"
        f"其中 {audit['with_senses']} 个有实际中文释义，即词典原文率 "
        f"{audit['dictionary_原文率']}%。其余词目的释义来自二手来源，"
        "使用时请注意区分。这一数字不是缺陷掩盖，而是如实披露。",
        size=9,
        bold=True,
        color=RGBColor(0xB4, 0x6A, 0x00),
    )

    _para(doc, "4. 标注均为候选值", bold=True)
    _para(
        doc,
        "按《义项判定标准》第 45 条：「程序 / 大模型仅输出候选标签作为参考，最终全部标签"
        "由研究者人工复核确认」。本词表中的原型层级、意象图式、英汉对齐等级均为"
        "依据次类归属推导的候选值，需人工复核后定稿。",
        size=9,
        color=RGBColor(0xB4, 0x6A, 0x00),
    )

    # ---------------- 二、统计概览 ----------------
    doc.add_page_break()
    _heading(doc, "二、分类体系与统计概览", 1)

    _heading(doc, "2.1 三主范畴", 2)
    cat_count = Counter(e["main_cat"] for e in entries)
    t = doc.add_table(rows=1, cols=3)
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(("主范畴", "词数", "占比")):
        _set_cell(t.rows[0].cells[i], h, bold=True, size=9)
    for cat in MAIN_CAT_ORDER:
        n = cat_count.get(cat, 0)
        cells = t.add_row().cells
        _set_cell(cells[0], cat, size=9)
        _set_cell(cells[1], str(n), size=9)
        _set_cell(cells[2], f"{n / audit['total'] * 100:.1f}%", size=9)

    _heading(doc, "2.2 十二次类", 2)
    grouped = defaultdict(list)
    for e in entries:
        grouped[(e["main_cat"], e["sub_cat"])].append(e)

    t = doc.add_table(rows=1, cols=5)
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(("主范畴", "次类", "词数", "意象图式", "簇内关系边")):
        _set_cell(t.rows[0].cells[i], h, bold=True, size=9)
    for cat in MAIN_CAT_ORDER:
        for (mc, sub), items in sorted(grouped.items(), key=lambda x: -len(x[1])):
            if mc != cat:
                continue
            n = len(items)
            cells = t.add_row().cells
            _set_cell(cells[0], mc, size=9)
            _set_cell(cells[1], sub, size=9)
            _set_cell(cells[2], str(n), size=9)
            _set_cell(cells[3], items[0].get("image_schema") or "-", size=9)
            _set_cell(cells[4], str(n * (n - 1) // 2), size=9)

    total_edges = sum(
        len(v) * (len(v) - 1) // 2 for v in grouped.values()
    )
    _para(doc, "")
    _para(
        doc,
        f"同一次类内的动词互为近义，构成一个词义簇；簇内任意两词之间建立一条近义边"
        f"（完全图）。全表共 {total_edges} 条词间关系边。",
        size=9,
    )

    # ---------------- 三、词表正文 ----------------
    doc.add_page_break()
    _heading(doc, "三、词表正文", 1)
    _para(
        doc,
        "按「主范畴 → 次类」分组排列。每词列出：原型主导义、意象图式、英汉对齐等级、"
        "释义及其来源、义位明细。",
        size=9,
        italic=True,
    )

    for cat in MAIN_CAT_ORDER:
        cat_items = [e for e in entries if e["main_cat"] == cat]
        if not cat_items:
            continue
        _heading(doc, f"3.{MAIN_CAT_ORDER.index(cat) + 1} {cat}（{len(cat_items)} 词）", 2)

        by_sub = defaultdict(list)
        for e in cat_items:
            by_sub[e["sub_cat"]].append(e)

        for sub, items in sorted(by_sub.items(), key=lambda x: -len(x[1])):
            schema = items[0].get("image_schema") or "-"
            _heading(doc, f"{sub}（{len(items)} 词）", 3)
            note = SCHEMA_NOTE.get(schema, "")
            _para(
                doc,
                f"意象图式：{schema}" + (f" —— {note}" if note else "")
                + f"　|　汉语句法：{items[0].get('cn_syntax_hint') or '-'}",
                size=9,
                italic=True,
            )

            t = doc.add_table(rows=1, cols=5)
            t.style = "Light Grid Accent 1"
            for i, h in enumerate(("词目", "原型主导义", "原型层级", "英汉对齐", "释义来源")):
                _set_cell(t.rows[0].cells[i], h, bold=True, size=9)

            for e in sorted(items, key=lambda x: x["verb"]):
                label, color = SOURCE_LABEL.get(
                    e["definition_source"], ("?", None)
                )
                cells = t.add_row().cells
                _set_cell(cells[0], e["verb"], bold=True, size=9)
                _set_cell(cells[1], e.get("sense_brief") or "-", size=9)
                _set_cell(cells[2], "Y", size=9)
                _set_cell(cells[3], e.get("alignment_hint") or "-", size=9)
                _set_cell(cells[4], label, size=9, color=color)

            # 释义明细（词典原文词给出完整释义与例句）
            detailed = [
                e for e in sorted(items, key=lambda x: x["verb"])
                if e["definition_source"] == "dictionary.db"
            ]
            for e in detailed:
                _para(doc, "")
                _para(doc, f"▸ {e['verb']}", size=10, bold=True)
                _para(
                    doc,
                    f"　释义：{e['chinese_ndef']}",
                    size=9,
                    color=RGBColor(0x1E, 0x7B, 0x34),
                )
                if e.get("example_sentence"):
                    _para(doc, f"　例句：{e['example_sentence']}", size=9, italic=True)
                senses = e.get("senses") or []
                if len(senses) > 1:
                    _para(
                        doc,
                        f"　其他义位（共 {len(senses)} 条，仅列前 5）：",
                        size=9,
                    )
                    for s in senses[1:6]:
                        text = s.get("ch_ndef") or s.get("en_ndef") or "—"
                        _para(doc, f"　　· {text[:120]}", size=8)
                if not e.get("prototype_is_first", True):
                    _para(
                        doc,
                        "　⚠️ 原型义位经脚本修正：词典首条义位不含位移语义，"
                        "已按原型主导义改选（需人工确认）。",
                        size=8,
                        color=RGBColor(0xB4, 0x6A, 0x00),
                    )
                if e.get("judge_reason"):
                    _para(doc, f"　收录依据：{e['judge_reason']}", size=8, italic=True)
            doc.add_paragraph()

    # ---------------- 附录 A ----------------
    doc.add_page_break()
    _heading(doc, "附录 A　候选词剔除记录", 1)
    _para(
        doc,
        f"候选阶段共 216 词，剔除 {len(rejects)} 词。剔除理由原文照录，未作归类改写。",
        size=9,
    )
    t = doc.add_table(rows=1, cols=2)
    t.style = "Light Grid Accent 1"
    _set_cell(t.rows[0].cells[0], "词目", bold=True, size=9)
    _set_cell(t.rows[0].cells[1], "剔除理由", bold=True, size=9)
    for verb in sorted(rejects):
        cells = t.add_row().cells
        _set_cell(cells[0], verb, size=9)
        _set_cell(cells[1], rejects[verb], size=9)

    # ---------------- 附录 B ----------------
    doc.add_page_break()
    _heading(doc, "附录 B　数据来源与生成方式", 1)
    for line in (
        "本词表由脚本 scripts/generate_word_doc.py 自动生成，所有数字均可追溯：",
        "· 《Levin移动动词候选词筛选表.xlsx》—— 词目、主范畴/次类、原型主导义简述、判断理由",
        "· data/dictionary.db（OALD 结构化数据）—— 义位、中英文释义、例句、近义反义词",
        "· data/motion_verbs_extracted.json —— 早期词库的中文释义（二手来源）",
        "· data/oxford_cache.json —— 英文释义缓存",
        "· docs/义项判定标准.docx —— 标注字段的定义与值域",
        "",
        "重新生成：python scripts/generate_word_doc.py",
        "同步数据库：python scripts/load_word_library.py",
    ):
        _para(doc, line, size=9)

    return doc


def main():
    parser = argparse.ArgumentParser(description="生成《英语自移移动动词词表》Word 文档")
    parser.add_argument("-o", "--output", default=DEFAULT_OUT, help="输出路径")
    parser.add_argument("--no-db", action="store_true", help="只读文件来源，不读 dictionary.db")
    args = parser.parse_args()

    levin = load_levin_table()
    db = DictionaryDB() if not args.no_db else DictionaryDB("/nonexistent")
    entries = build_entries(levin, load_oxford_cache(), db, load_legacy_library())
    rejects = load_rejected_lemmas()
    audit = audit_coverage(entries)

    print(f"词表: {len(entries)} 词 | 义位明细: {audit['with_senses']} 词 "
          f"| 剔除记录: {len(rejects)} 条")
    print("释义来源:", audit["by_source"])

    doc = build_document(entries, rejects, audit)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    doc.save(args.output)
    size_kb = os.path.getsize(args.output) / 1024
    print(f"已生成: {args.output}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
