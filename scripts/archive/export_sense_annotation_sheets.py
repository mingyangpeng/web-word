#!/usr/bin/env python3
"""为 136 个英语自移移动动词生成逐词「义位标注表」xlsx。

数据来源：
  - docs/词表义项清单.xlsx「义项明细」：OALD10 逐义项数据（132 词，665 义位）
  - data/oxford_cache.json：Oxford 释义缓存（dodder）
  - docs/词表义项清单.xlsx「词表概览」：主范畴/次类/原型主导义简述（4 个缺义词的补充来源）

每词一个 xlsx（data/corpus/sense_sheets/<verb>_义项.xlsx），两个工作表：
  1. 义位标注 —— 14 字段（见 FIELD_NOTES），义项以 S1,S2,S3... 编号（SenseID），
     人工标注列（意象图式/准入标签/判定理由/备注）留空待填
  2. 字段注释 —— 14 字段的定义与填写规范（附录表格下方直接粘贴版）

义位编号体系：SenseID = <verb>-S<序号>（如 walk-S1），后续图式提取、
准入判定（Y/拓展/N）、PS 计算均以该义位为分析单元。
"""
import json
import os

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENSE_SRC = os.path.join(BASE, "docs", "词表义项清单.xlsx")
OXFORD_CACHE = os.path.join(BASE, "data", "oxford_cache.json")
VERBS_FILE = os.path.join(BASE, "data", "corpus", "verbs_171.json")
OUT_DIR = os.path.join(BASE, "data", "corpus", "sense_sheets")

# 14 字段（义位标注表列头）
FIELDS = [
    "SenseID", "词目", "义项序号", "来源", "及物性", "英文释义", "例句",
    "句法模式", "是否习语", "原型义", "原型主导义简述", "意象图式",
    "准入标签", "判定理由", "备注",
]

# 字段注释（附录表格下方直接粘贴）
FIELD_NOTES = [
    ("词目", "目标动词词条"),
    ("义项序号", "该义位在词典中的编号，构建 SenseID（本表以 S1,S2,S3... 编号）"),
    ("来源", "词典来源（如 OALD），用于溯源"),
    ("及物性", "动词的及物属性（及物 / 不及物 / 两用），移动事件句法分析必备"),
    ("英文释义", "OALD 对应义项原文，判定依据"),
    ("例句", "该义位典型例句，语义判定证据"),
    ("句法模式", "记录该义位的典型句法实现，Talmy 移动事件分析核心"),
    ("是否习语", "标记习语义项，习语一般归入 N 或拓展"),
    ("原型义", "词典标记的词条原型义项（词典自带，不等于本研究 Y 类原型物理位移义）"),
    ("原型主导义简述", "研究者概括该义位核心语义，辅助意象图式判断"),
    ("意象图式", "人工标注，四选一：源点脱离图式 / 终点抵达图式 / 方式伴随图式 / 互动位移图式；多重图式取凸显重心，次要图式记入备注"),
    ("准入标签", "Y（原型实体位移义）/ 拓展（隐喻位移）/ N（非位移义）"),
    ("判定理由", "依据释义、例句简要说明准入标签与意象图式判定依据，用于编码信度复核"),
    ("备注", "边界案例、图式叠加、AI 初标与人工判定不一致、编码分歧等"),
]

# 人工填写列（生成时留空）
MANUAL_COLS = {"意象图式", "准入标签", "判定理由", "备注"}

HEADER_FILL = PatternFill("solid", fgColor="4472C4")
MANUAL_FILL = PatternFill("solid", fgColor="FFF2CC")
HEADER_FONT = Font(bold=True, color="FFFFFF")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
WRAP = Alignment(vertical="top", wrap_text=True)

# 4 个缺词典释义词的补充数据（来源见 docstring；kayak/oar 为 levin-brief 研究者标注）
FALLBACK_SENSES = {
    "dodder": [
        {
            "def": "To shake or tremble as one moves, especially as of old age or childhood; to totter.",
            "example": None,
            "grammar": "intransitive",
            "syntax": "dodder + adv./prep.",
            "group": None,
            "idiom": None,
            "prototype": "是",
        },
    ],
    "scutter": [
        {
            "def": "（OALD10 未收录；据语料与词表）to move quickly with short, hurried steps; scurry.",
            "example": None,
            "grammar": "intransitive",
            "syntax": "scutter + adv./prep.",
            "group": None,
            "idiom": None,
            "prototype": "是",
        },
    ],
    "kayak": [
        {
            "def": "（OALD10 动词义项未收录；据词表 levin-brief）to travel in a kayak.",
            "example": None,
            "grammar": "intransitive",
            "syntax": "kayak + adv./prep.",
            "group": None,
            "idiom": None,
            "prototype": "是",
        },
    ],
    "oar": [
        {
            "def": "（OALD10 动词义项未收录；据词表 levin-brief）to propel a boat with oars; row.",
            "example": None,
            "grammar": "intransitive",
            "syntax": "oar + adv./prep.",
            "group": None,
            "idiom": None,
            "prototype": "是",
        },
    ],
}


def load_senses():
    """读取义项明细，返回 {verb: [sense_row, ...]}。"""
    wb = openpyxl.load_workbook(SENSE_SRC, read_only=True)
    ws = wb["义项明细"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    idx = {h: i for i, h in enumerate(header)}
    senses = {}
    for r in rows[1:]:
        if not r[0]:
            continue
        senses.setdefault(r[0], []).append({
            "no": r[idx["义项序号"]],
            "source": r[idx["来源"]],
            "group": r[idx["语义分组"]],
            "grammar": r[idx["语法码"]],
            "def": r[idx["英文释义"]],
            "example": r[idx["例句"]],
            "syntax": r[idx["句法模式"]],
            "idiom": r[idx["是否习语"]],
            "prototype": r[idx["原型义"]],
        })
    return senses


def load_overview():
    """读取词表概览，返回 {verb: {主范畴, 次类, 原型主导义简述, 意象图式}}。"""
    wb = openpyxl.load_workbook(SENSE_SRC, read_only=True)
    ws = wb["词表概览"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    idx = {h: i for i, h in enumerate(header)}
    out = {}
    for r in rows[1:]:
        if not r[0]:
            continue
        out[r[0]] = {
            "main_cat": r[idx["主范畴"]],
            "sub_cat": r[idx["次类"]],
            "schema": r[idx["意象图式"]],
            "brief": r[idx["原型主导义简述"]],
            "ch_def": r[idx["词目中文释义（灌库值）"]] if "词目中文释义（灌库值）" in idx else None,
        }
    return out


def build_sense_sheet(verb, verb_senses, overview, oxford_cache, out_dir=None):
    wb = openpyxl.Workbook()

    # ---------- Sheet 1: 义位标注 ----------
    ws = wb.active
    ws.title = "义位标注"
    ws.append(FIELDS)
    for c in ws[1]:
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER

    if verb_senses is None:
        verb_senses = FALLBACK_SENSES.get(verb, [])
        for s in verb_senses:
            s["source"] = "oxford-cache" if verb == "dodder" else "levin-brief"

    info = overview.get(verb, {})
    for i, s in enumerate(verb_senses, 1):
        sid = f"{verb}-S{i}"
        row = [
            sid, verb, f"S{i}", s.get("source"), s.get("grammar"),
            s.get("def"), s.get("example"), s.get("syntax"),
            s.get("idiom"), s.get("prototype"),
            info.get("brief"), None, None, None, None,
        ]
        ws.append(row)

    # 人工填写列底色
    manual_idx = [FIELDS.index(c) + 1 for c in ["意象图式", "准入标签", "判定理由", "备注"]]
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for ci in manual_idx:
            row[ci - 1].fill = MANUAL_FILL

    widths = [12, 10, 8, 10, 14, 50, 50, 24, 8, 8, 22, 16, 10, 40, 30]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.alignment = WRAP
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions

    # ---------- Sheet 2: 字段注释 ----------
    ws2 = wb.create_sheet("字段注释")
    ws2.append(["字段", "注释"])
    for c in ws2[1]:
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTER
    for name, note in FIELD_NOTES:
        ws2.append([name, note])
    ws2.append([])
    ws2.append(["SenseID", f"义位编号 = <动词>-S<序号>（如 {verb}-S1）。"
                "本研究的义位准入判定（Y/拓展/N）、意象图式标注、"
                "英汉对齐、PS 计算均以 SenseID 为分析单元；"
                "语料搭配数据见同目录 verb_sheets/{verb}.xlsx，"
                "图式证据槽位与 SenseID 一一对应。"])
    ws2.append(["词表信息", f"主范畴：{info.get('main_cat', '—')}；次类：{info.get('sub_cat', '—')}；"
                f"词表意象图式（词目层初判）：{info.get('schema', '—')}。"
                "注意：词目层分类仅作参考，义位层标注须逐条独立判定，二者不可相互替代。"])
    ws2.column_dimensions["A"].width = 18
    ws2.column_dimensions["B"].width = 90
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        row[1].alignment = WRAP

    out = os.path.join(out_dir or OUT_DIR, f"{verb}_义项.xlsx")
    wb.save(out)
    return out, len(verb_senses)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="导出逐词义位标注表（data/corpus/sense_sheets）")
    parser.add_argument("--verbs", default=VERBS_FILE,
                        help="词目清单 json（默认 data/corpus/verbs_171.json，171 词全范围）")
    parser.add_argument("--out-dir", default=OUT_DIR, help="输出目录")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    verbs = json.load(open(args.verbs, encoding="utf-8"))
    senses = load_senses()
    overview = load_overview()
    oxford_cache = json.load(open(OXFORD_CACHE, encoding="utf-8")) \
        if os.path.exists(OXFORD_CACHE) else {}

    total = 0
    fallback = []
    for i, v in enumerate(verbs, 1):
        vs = senses.get(v)
        _, n = build_sense_sheet(v, vs, overview, oxford_cache, out_dir=args.out_dir)
        total += n
        if vs is None:
            fallback.append(v)
        if i % 20 == 0:
            print(f"  {i}/{len(verbs)} done")
    print(f"saved {len(verbs)} sense sheets ({total} senses) to {OUT_DIR}")
    print(f"fallback-sourced verbs: {fallback}")


if __name__ == "__main__":
    main()
