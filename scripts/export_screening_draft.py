#!/usr/bin/env python3
"""表2 粗筛草稿（第一轮机械筛选）——AI 初筛第一层：规则引擎，打标不删行。

定位：三表工作流中表2（02_义位标注 人工列）的草稿供料层。
  规则命中 → 写「粗筛草稿标签 + 命中规则 + 机器依据」，全部义位保留，进入待复核队列；
  人工在平台/表2 复核确认后，最终标签回写表2（xlsx L–O 列与 oald_senses）。

编码规则（与《义项判定标准修改稿》对齐；三个口径决策采用默认值，可整体翻转重跑）：
  D1 使役义：按手册——客体发生物理位移的使役自移记 Y 候选，进存疑清单；不自动剔除（及物仅标"待判"）。
  D2 隐喻义：按手册——保留为拓展层；figurative 标记未随 OALD 提取留存，机械层不判，
     隐喻性筛查交 LLM 初筛（下一层）与人工。
  D3 语料：enTenTen21 单语料；义位级频次无来源，不设机械阈值，词目频次仅作参考列。

机械可用信号（数据现状）：
  is_idiom（可靠，全量）· grammar 语法码（437/665 有值，228 空）· 释义文本。
产出：docs/表2_粗筛草稿_试点12词.xlsx
"""

import json
import sys
import os
from datetime import date
from pathlib import Path

import yaml
import pymysql

XLSX_SKILL_DIR = "/Users/jhon/.zcode/cli/plugins/cache/zcode-plugins-official/spreadsheets/0.1.7/skills/xlsx"
for sub in [XLSX_SKILL_DIR, os.path.join(XLSX_SKILL_DIR, "templates")]:
    if sub not in sys.path:
        sys.path.insert(0, sub)
from base import (  # noqa: E402
    FONT_NAME, FORMATS, PRIMARY_LIGHT, setup_sheet, style_header_row,
    style_data_row, style_total_row, font_caption, font_subheader,
    auto_fit_columns, auto_fit_row_heights,
)
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "表2_粗筛草稿_试点12词.xlsx"
PILOT = [p["verb"] for p in json.loads(
    (ROOT / "data" / "corpus" / "pilot_verbs.json").read_text())["verbs"]]

cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text())["database"]["mysql"]
host = cfg["host"] if cfg["host"] != "mysql" else "127.0.0.1"
conn = pymysql.connect(host=host, port=cfg["port"], user=cfg["user"],
                       password=cfg["password"], database=cfg["database"],
                       charset="utf8mb4", cursorclass=pymysql.cursors.Cursor)
with conn.cursor() as cur:
    cur.execute(
        f"""SELECT headword, sense_index, definition, grammar, is_idiom
            FROM oald_senses WHERE headword IN ({','.join(['%s'] * len(PILOT))})
            ORDER BY FIELD(headword, {','.join(['%s'] * len(PILOT))}), sense_index""",
        PILOT + PILOT)
    senses = cur.fetchall()
    cur.execute("SELECT verb, freq FROM corpus_word_stats")
    freq = dict(cur.fetchall())
conn.close()

# ---- 规则引擎

def voice_class(grammar):
    """语法码 → 不及物 / 及物 / 两用 / 缺失。"""
    if not grammar or not str(grammar).strip():
        return "缺失"
    g = str(grammar).lower()
    has_i, has_t = "intransitive" in g, "transitive" in g
    if has_i and has_t:
        return "两用"
    return "不及物" if has_i else "及物"

rows = []
for hw, idx, definition, grammar, is_idiom in senses:
    vc = voice_class(grammar)
    if is_idiom:
        tag = "N候选（习语）"
        rule, basis = "R4 习语", "OALD IDIOMS 组；按手册一般归 N 或拓展，与「问题清单」页确认"
    elif vc == "不及物":
        tag = "Y候选"
        rule = "R1 自移候选"
        basis = "不及物；主体自主位移候选（隐喻性未经筛查，LLM 初筛/人工确认）"
    elif vc == "两用":
        tag = "Y候选*"
        rule = "R1 自移候选（两用）"
        basis = "两用：不及物侧为自移候选；及物侧按手册边界条款人工确认（客体位移→Y）"
    elif vc == "及物":
        tag = "待判（及物）"
        rule = "R2 使役/及物"
        basis = "及物：客体位移的使役自移→Y候选（手册 D1）；静态/状态变化→N候选；隐喻→拓展候选"
    else:
        tag = "待判（语法缺失）"
        rule = "R0 信息不足"
        basis = "语法码缺失（228/665 现状）；结合释义与例句人工判定"
    rows.append([f"{hw}-S{int(idx)}", hw, f"S{int(idx)}", grammar or "",
                 vc, definition or "", "是" if is_idiom else "", freq.get(hw, 0),
                 tag, rule, basis, "是" if tag.startswith("待判") else "",
                 None, None])  # 人工最终标签 / 人工理由

tag_counts = {}
for r in rows:
    tag_counts[r[8]] = tag_counts.get(r[8], 0) + 1

wb = Workbook()

# ---- 草稿表
HEADERS = ["SenseID", "词形", "义项号", "OALD语法码", "及物性归类", "英文释义", "是否习语",
           "词目频次(enTenTen21)", "粗筛草稿标签", "命中规则", "机器依据",
           "待复核", "人工最终标签", "人工理由"]
LAST = len(HEADERS) + 1
ws = wb.active
ws.title = "粗筛草稿"
setup_sheet(ws, title="表2 粗筛草稿 · 试点 12 词义位第一轮机械筛选（打标不删行）", last_col=LAST)
for col, h in enumerate(HEADERS, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=LAST)
TAG_FILL = {
    "Y候选": PatternFill("solid", fgColor="E8F5E9"),
    "Y候选*": PatternFill("solid", fgColor="E8F5E9"),
    "N候选（习语）": PatternFill("solid", fgColor="FDEDEC"),
    "待判（及物）": PatternFill("solid", fgColor="FEF9E7"),
    "待判（语法缺失）": PatternFill("solid", fgColor="FEF9E7"),
}
for i, r in enumerate(rows):
    rn = 5 + i
    for col, v in enumerate(r, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=LAST, row_index=i)
    ws.cell(row=rn, column=10).fill = TAG_FILL.get(r[8], ws.cell(row=rn, column=10).fill)
    ws.cell(row=rn, column=9).number_format = FORMATS["integer"]
    ws.cell(row=rn, column=9).alignment = __import__("openpyxl").styles.Alignment(
        horizontal="right", vertical="center")
    for col in (14, 15):
        ws.cell(row=rn, column=col).fill = PatternFill("solid", fgColor=PRIMARY_LIGHT)
total = 5 + len(rows)
ws.cell(row=total, column=2, value="合计")
ws.cell(row=total, column=3, value=f"{len(rows)} 义位")
style_total_row(ws, row_num=total, col_start=2, col_end=LAST)
ws.cell(row=total + 2, column=2,
        value="绿＝Y候选；红＝N候选（习语）；琥珀＝待人工判定。所有行均不删除，最终标签以人工复核为准，"
              "确认后回写表2（02_义位标注 L–O 列）与标注平台。").font = font_caption()
ws.freeze_panes = "D5"
ws.auto_filter.ref = f"B4:O{total - 1}"
auto_fit_columns(ws, min_width=8, max_width=44, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ---- 规则命中统计
ws2 = wb.create_sheet("规则命中统计")
setup_sheet(ws2, title="粗筛规则命中统计（试点 12 词 · 232 义位）", last_col=4)
ws2.column_dimensions["B"].width = 22
ws2.column_dimensions["C"].width = 12
ws2.column_dimensions["D"].width = 60
for col, h in enumerate(["草稿标签", "条数", "含义与去向"], 2):
    ws2.cell(row=4, column=col, value=h)
style_header_row(ws2, row_num=4, col_start=2, col_end=4)
MEANING = {
    "Y候选": "不及物自移候选 → 复核确认后记 Y，进五维标注",
    "Y候选*": "两用词性 → 及物侧用法需人工确认后定 Y/拓展/N",
    "N候选（习语）": "OALD 习语 → 默认 N，与问题清单确认，留剔除理由",
    "待判（及物）": "使役/隐喻/状态变化混杂 → 人工逐条判（对应 D1 决策）",
    "待判（语法缺失）": "语法码缺失 → 结合释义例句人工判",
}
rn = 5
for i, (tag, n) in enumerate(sorted(tag_counts.items(), key=lambda x: -x[1])):
    ws2.cell(row=rn, column=2, value=tag)
    ws2.cell(row=rn, column=3, value=n)
    ws2.cell(row=rn, column=4, value=MEANING.get(tag, ""))
    style_data_row(ws2, row_num=rn, col_start=2, col_end=4, row_index=i)
    ws2.cell(row=rn, column=3).number_format = FORMATS["integer"]
    rn += 1
ws2.cell(row=rn, column=2, value="合计")
ws2.cell(row=rn, column=3, value=len(rows))
style_total_row(ws2, row_num=rn, col_start=2, col_end=4)
rn += 2
sec_note = [
    ("数据现状", "语法码 437/665 有值（228 缺失）；figurative 标记未随 OALD 提取留存，"
              "机械层无法判隐喻性——由下一层 LLM 初筛按手册规则 1（抽象隐喻投射→拓展）补齐，人工确认。"),
    ("三个口径决策（默认值）", "D1 使役按手册（客体位移→Y候选，不自动剔除）；D2 隐喻保留为拓展层；"
                      "D3 语料维持 enTenTen21、不设机械低频阈值（词目频次仅参考列）。"
                      "翻转任一决策=改脚本重跑，草稿可整体再生。"),
    ("下一步", "LLM 初筛（隐喻性 + 四图式候选 + 存疑标记）→ 灌入平台待复核队列 → 人工日课标注。"),
]
for k, v in sec_note:
    ws2.cell(row=rn, column=2, value=k).font = font_subheader()
    ws2.cell(row=rn, column=3, value="")
    ws2.cell(row=rn, column=4, value=v)
    style_data_row(ws2, row_num=rn, col_start=2, col_end=4, row_index=rn % 2)
    rn += 1
auto_fit_row_heights(ws2, header_row=4, data_start_row=4)

# ---- 口径与规则说明
ws3 = wb.create_sheet("口径与规则")
setup_sheet(ws3, title="粗筛规则口径（论文方法部分可直接引用的机械层描述）", last_col=3)
ws3.column_dimensions["B"].width = 20
ws3.column_dimensions["C"].width = 108
rn = 4
for k, v in [
    ("工作流位置", "表1（原始总表，只读）→ 本粗筛草稿（机械规则层，打标不删行）→ 表2 人工判定层"
              "（02_义位标注 L–O 列 / 标注平台）→ 表3（结果层，human_reviewed=1 提取）。"),
    ("R1 自移候选", "语法码为不及物或两用、非习语 → Y候选。注意机械层不判隐喻性（figurative 标记缺失），"
                "候选中混有隐喻义，由 LLM 初筛与人工复核剔除。"),
    ("R2 及物待判", "及物义位不自动剔除（D1 默认口径）：客体位移的使役自移按手册记 Y 并入存疑清单；"
                "静态/状态变化记 N；隐喻记拓展。三条路径均人工判定。"),
    ("R4 习语", "OALD IDIOMS 组（试点内 N 条见统计页）→ N候选，逐条与词表「问题清单」页核对后定 N 或拓展。"),
    ("低频过滤", "试点阶段不设机械阈值（D3）：义位级频次无可复现来源，低频义位以\"语料证据支撑缺失\""
              "在判定理由中如实说明；词目频次列仅供人工参考。"),
    ("拆分义位约定", "不推翻 OALD 义项划分；同一 OALD 子义项内若语料稳定出现两套完全不同的移动事件结构，"
                "可在备注中申请拆分为两个子义位（SenseID 加后缀 a/b），论文注明\"基于共时语料证据的拆分\"，"
                "统一进存疑清单仲裁。"),
    ("图式归纳", "图式绑定义位不绑定词形；在粗筛保留的义位上，由该义位下的真实语料例句抽象共享事件结构"
              "（Talmy 要素），归入三域七系图式体系（注意：外部建议中的\"三域五类\"为笔误，全文统一七系）。"),
    ("生成信息", f"生成日期 {date.today()}；数据源 oald_senses（试点 12 词 232 义位）+ corpus_word_stats；"
             "脚本 scripts/export_screening_draft.py 可重跑。"),
]:
    ws3.cell(row=rn, column=2, value=k).font = font_subheader()
    ws3.cell(row=rn, column=3, value=v)
    style_data_row(ws3, row_num=rn, col_start=2, col_end=3, row_index=rn % 2)
    rn += 1
auto_fit_row_heights(ws3, header_row=4, data_start_row=4)

wb.properties.creator = "Z.ai"
wb.save(OUT)
print(f"saved: {OUT}")
print(f"rows={len(rows)}, tags={tag_counts}")
