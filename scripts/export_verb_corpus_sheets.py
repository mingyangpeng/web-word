#!/usr/bin/env python3
"""为 136 个英语自移移动动词生成逐词 xlsx 语料档案。

数据来源：Sketch Engine（广外 libVPN）English Web 2021 (enTenTen21)，
接口 bonito/run.cgi/wsketch，maxitems=50，原始 JSON 存于
data/corpus/wsketch_full/<verb>.json。

每词一个 xlsx（data/corpus/verb_sheets/<verb>.xlsx），工作表：
  1. 词频概览   —— 频次、每百万词频次、各语法关系汇总
  2. 搭配明细   —— 每个语法关系（槽位）前 50 个搭配词：
                   logDice(score)、搭配频次(count)、典型组合(cm)、
                   语料库主题分布(High)、语义类别（留空供人工归类）、
                   处理（保留/剔除，供概念归类清洗）
  3. 图式证据   —— 四类意象图式 × 证据槽位映射（源点脱离/终点抵达/
                   方式伴随/互动位移），自动汇总对应槽位的搭配证据
  4. PS计算     —— 原型性得分工作表：槽位确定→概念归类→PS 公式
                   （PS = Mean_logDice × log2(N+1)），N 与 Mean_logDice
                   由「语义类别=保留」的行自动汇总

参照：docs/开题报告.docx「原型性量化分析——以到达类·终点抵达为例」
      docs/义项判定标准修改稿.docx（四类意象图式）
"""
import json
import math
import os

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE, "data", "corpus", "wsketch_full")
OUT_DIR = os.path.join(BASE, "data", "corpus", "verb_sheets")
VERBS_FILE = os.path.join(BASE, "data", "corpus", "verbs_136.json")

CORPUS = "English Web 2021 (enTenTen21)"
RETRIEVED = "2026-09-30"

HEADER_FILL = PatternFill("solid", fgColor="4472C4")
KEEP_FILL = PatternFill("solid", fgColor="E2EFDA")
SCHEMA_FILL = PatternFill("solid", fgColor="FFF2CC")
HEADER_FONT = Font(bold=True, color="FFFFFF")
CENTER = Alignment(horizontal="center", vertical="center")

# 四类意象图式（义项判定标准修改稿）× 证据槽位映射。
# 槽位名即 Sketch Engine 语法关系（%w 为动词占位符）。
SCHEMA_SLOTS = {
    "源点脱离图式": {
        "定义": "重心为运动体离开起始位置（leave, depart 类）",
        "证据槽位": [
            'particles after "%w"',           # away / off / out 等脱离小品词
            'objects of "%w away"',
            'objects of "%w off"',
            'objects of "%w out"',
            'prepositional phrases',           # from / out of 脱离介词短语
        ],
    },
    "终点抵达图式": {
        "定义": "重心为运动体到达目标位置（arrive, reach 类）",
        "证据槽位": [
            'objects of "%w"',                 # 及物动词的终点宾语
            'objects of "%w up"',
            'objects of "%w down"',
            'objects of "%w in"',
            'objects of "%w into"',
            'prepositional phrases',           # to / at / in 终点介词短语
            'particles after "%w" with object',
        ],
    },
    "方式伴随图式": {
        "定义": "重心为位移过程伴随的运动方式（run, swim, limp 类）",
        "证据槽位": [
            'modifiers of "%w"',               # slowly / barefoot 等方式状语
            'adjectives after "%w"',
            'usage patterns',
            'subjects of "%w"',                # 典型运动体（人/动物/交通工具）
            '"%w" and/or ...',                 # and/or 并列的同类方式动词
            'complements of "%w"',
        ],
    },
    "互动位移图式": {
        "定义": "重心为两个实体同时发生物理位移、具备空间互动关系（chase, follow 类）",
        "证据槽位": [
            'objects of "%w"',                 # 互动对象宾语
            'pronominal objects of "%w"',
            'pronominal subjects of "%w"',
            'subjects of "%w"',
            'prepositional phrases',           # after / behind 互动介词
            'particles after "%w" with object',
        ],
    },
}

# 搭配明细列（语义类别/处理留空，供人工概念归类，参照开题报告表7-9）
DETAIL_HEADERS = [
    "排名", "槽位(语法关系)", "搭配词", "logDice", "搭配频次",
    "典型组合(cm)", "cm频次", "语料库主题分布", "语义类别(人工)", "处理(人工)",
]

SHEET1_FIELDS = [
    ("语料库", CORPUS),
    ("检索平台", "Sketch Engine（广外图书馆 libVPN 代理访问）"),
    ("动词", None),  # filled per verb
    ("词性(lpos)", None),
    ("语料库总频次", None),
    ("每百万词频次(relfreq)", None),
    ("语法关系(槽位)数", None),
    ("搭配词总数(每槽位前50)", None),
    ("检索日期", RETRIEVED),
]


def fmt_num(x):
    if x is None:
        return ""
    if isinstance(x, float):
        return round(x, 2)
    return x


def style_header(ws, row=1):
    for c in ws[row]:
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER


def iter_collocations(gramrels):
    """展平嵌套槽位：prepositional phrases 等槽位的 Words 是二级槽位
    （如 "%w" through ...，其 Words 为空、count/score 即该介词的频次与
    logDice），直接把二级槽位本身作为搭配条目输出。"""
    for rel in gramrels:
        words = rel.get("Words", [])
        if words and "word" not in words[0] and "Words" in words[0]:
            for sub in words:
                yield rel["name"], sub["name"], {
                    "word": sub.get("name"),
                    "count": sub.get("count"),
                    "score": sub.get("score"),
                    "cm": None,
                    "cmf": None,
                    "High": [],
                }
        else:
            for w in words:
                yield rel["name"], None, w


def build_verb_sheet(verb):
    src = os.path.join(SRC_DIR, f"{verb}.json")
    j = json.load(open(src, encoding="utf-8"))
    gramrels = j.get("Gramrels", [])

    wb = openpyxl.Workbook()

    # ---------- Sheet 1: 词频概览 ----------
    ws = wb.active
    ws.title = "词频概览"
    ws.append(["字段", "值"])
    style_header(ws)
    total_words = 0
    for k, v in SHEET1_FIELDS:
        if k == "动词":
            v = verb
        elif k == "词性(lpos)":
            v = j.get("lpos", "")
        elif k == "语料库总频次":
            v = j.get("freq")
        elif k == "每百万词频次(relfreq)":
            v = fmt_num(j.get("relfreq"))
        elif k == "语法关系(槽位)数":
            v = len(gramrels)
        elif k == "搭配词总数(每槽位前50)":
            v = sum(len(r.get("Words", [])) for r in gramrels)
        ws.append([k, v])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 30

    # 槽位汇总表
    ws.append([])
    ws.append(["槽位(语法关系)", "槽位频次", "槽位logDice", "搭配词数", "前5搭配词(logDice)"])
    style_header(ws, row=ws.max_row)
    for rel in gramrels:
        words = rel.get("Words", [])
        if words and "word" not in words[0] and "Words" in words[0]:
            top5 = "; ".join(
                f"{sub['name']}({sub['score']})" for sub in words[:5]
            )
            n = len(words)
        else:
            top5 = "; ".join(f"{w['word']}({w['score']})" for w in words[:5])
            n = len(words)
        ws.append([
            rel.get("name"), rel.get("count"), rel.get("score"),
            n, top5,
        ])
    for i, w_ in enumerate([34, 12, 12, 12, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = w_

    # ---------- Sheet 2: 搭配明细 ----------
    ws2 = wb.create_sheet("搭配明细")
    ws2.append(DETAIL_HEADERS)
    style_header(ws2)
    rank_map = {}
    for slot, subslot, w in iter_collocations(gramrels):
        slot_label = slot if not subslot else f"{slot} > {subslot}"
        rank_map[slot_label] = rank_map.get(slot_label, 0) + 1
        rank = rank_map[slot_label]
        highs = "; ".join(
            f"{h.get('mod')} {h.get('tt')}({h.get('ratio')})"
            for h in w.get("High", [])[:3]
        )
        ws2.append([
            rank, slot_label, w.get("word"), w.get("score"),
            w.get("count"), w.get("cm"), w.get("cmf"),
            highs, "", "",
        ])
    for i, w_ in enumerate([6, 30, 16, 10, 12, 24, 8, 40, 22, 12], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w_
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions

    # ---------- Sheet 3: 图式证据 ----------
    ws3 = wb.create_sheet("图式证据")
    ws3.append(["意象图式", "图式定义", "证据槽位", "槽位频次", "搭配词数", "前5搭配证据(logDice)"])
    style_header(ws3)
    rel_map = {r.get("name"): r for r in gramrels}
    for schema, info in SCHEMA_SLOTS.items():
        for slot in info["证据槽位"]:
            rel = rel_map.get(slot)
            if not rel:
                continue
            words = rel.get("Words", [])
            if words and "word" not in words[0] and "Words" in words[0]:
                top5 = "; ".join(
                    f"{sub['name']}({sub['score']})" for sub in words[:5]
                )
                n = len(words)
            else:
                top5 = "; ".join(f"{w['word']}({w['score']})" for w in words[:5])
                n = len(words)
            ws3.append([
                schema, info["定义"], slot, rel.get("count"),
                n, top5,
            ])
        # 该图式在本动词上是否有证据
    ws3.append([])
    ws3.append(["判定提示", "本表自动汇总四类意象图式对应的证据槽位搭配。"
                "空缺槽位说明该动词在该图式维度上语料证据不足。"
                "最终图式标签需结合 OALD 释义与真实例句人工判定（见义项判定标准修改稿）。"])
    for i, w_ in enumerate([16, 44, 28, 12, 12, 60], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w_
    for row in ws3.iter_rows(min_row=2, max_row=ws3.max_row):
        if row[0].value in SCHEMA_SLOTS:
            for c in row:
                c.fill = SCHEMA_FILL

    # ---------- Sheet 4: PS计算 ----------
    ws4 = wb.create_sheet("PS计算")
    ws4.append(["原型性得分（PS）计算工作表"])
    ws4["A1"].font = Font(bold=True, size=13)
    ws4.append([])
    ws4.append(["公式", "PS = Mean_logDice × log2(N + 1)"])
    ws4.append(["Mean_logDice", "所有「语义类别=保留」搭配词 logDice 的算术平均（质量维度）"])
    ws4.append(["N", "「语义类别=保留」搭配词总数（广度维度，对数压缩）"])
    ws4.append(["操作", "在「搭配明细」表填写「语义类别(人工)」与「处理(人工)」，"
                "将核心槽位的行标记处理=保留；本表自动汇总 N 与 Mean_logDice 并计算 PS"])
    ws4.append(["参照", "开题报告「原型性量化分析——以到达类·终点抵达次范畴为例」"])
    ws4.append([])
    ws4.append(["核心槽位(人工确定)", "有效搭配词数 N", "logDice 总值", "平均 logDice", "PS = Mean×log2(N+1)"])
    style_header(ws4, row=ws4.max_row)
    # 公式引用搭配明细表：统计「处理」列(J)=保留的行
    # 用 openpyxl 公式实现动态汇总
    detail_rows = ws2.max_row - 1
    ws4.append([
        "（在搭配明细表 J 列填「保留」后自动计算）",
        f'=COUNTIF(搭配明细!J2:J{ws2.max_row},"保留")',
        f'=SUMIF(搭配明细!J2:J{ws2.max_row},"保留",搭配明细!D2:D{ws2.max_row})',
        f'=IFERROR(D{ws4.max_row+1}/B{ws4.max_row+1},0)',
        f'=IFERROR(D{ws4.max_row+1}*LOG(B{ws4.max_row+1}+1,2),0)',
    ])
    for i, w_ in enumerate([30, 16, 14, 14, 22], 1):
        ws4.column_dimensions[get_column_letter(i)].width = w_

    out = os.path.join(OUT_DIR, f"{verb}.xlsx")
    wb.save(out)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    verbs = json.load(open(VERBS_FILE, encoding="utf-8"))
    for i, v in enumerate(verbs, 1):
        build_verb_sheet(v)
        if i % 20 == 0:
            print(f"  {i}/{len(verbs)} done")
    print(f"saved {len(verbs)} verb sheets to {OUT_DIR}")


if __name__ == "__main__":
    main()
