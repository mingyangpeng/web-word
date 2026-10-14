#!/usr/bin/env python3
"""导出【表1 原始义项总表】——三表义位筛选工作流的原始层（只读存档）。

三表工作流（Lexikos 论文方法部分可直接引用）：
  表1 原始提取总表（本文件，只读存档，严禁删改）
  表2 义项筛选判定表 = output/02_义位标注/<动词>_义项.xlsx 的人工列（L 意象图式 /
      M 准入标签 Y·拓展·N / N 判定理由 / O 备注）
  表3 最终研究义位表 = docs/表3_最终研究义位表.xlsx（scripts/export_final_sense_list.py
      从平台标注结果生成，标注完成后重跑）

数据血缘：docs/词表义项清单.xlsx「义项明细」(+4 补充词)
        → scripts/export_sense_annotation_sheets.py → output/02_义位标注/
        → 本脚本原样汇出 → docs/表1_原始义项总表.xlsx
"""

import sys
import os
from datetime import date
from pathlib import Path

XLSX_SKILL_DIR = "/Users/jhon/.zcode/cli/plugins/cache/zcode-plugins-official/spreadsheets/0.1.7/skills/xlsx"
for sub in [XLSX_SKILL_DIR, os.path.join(XLSX_SKILL_DIR, "templates")]:
    if sub not in sys.path:
        sys.path.insert(0, sub)
from base import (  # noqa: E402
    FORMATS, setup_sheet, style_header_row, style_data_row, style_total_row,
    font_caption, font_subheader, auto_fit_columns, auto_fit_row_heights,
)
from openpyxl import Workbook, load_workbook  # noqa: E402
from openpyxl.styles import PatternFill  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "output" / "02_义位标注"
OUT = ROOT / "docs" / "表1_原始义项总表.xlsx"

COLS = ["SenseID", "词形", "义项序号", "来源", "及物性", "英文释义", "例句",
        "句法模式", "是否习语", "原型义", "原型主导义简述（词目层初判，仅参考）"]

rows = []
for f in sorted(SRC_DIR.glob("*_义项.xlsx")):
    wb = load_workbook(f, read_only=True)
    ws = wb["义位标注"]
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[0]:
            continue
        rows.append(list(r[:11]))  # A–K 列原样，人工列 L–O 不属于原始层
    wb.close()

src_counter = {}
for r in rows:
    src_counter[r[3]] = src_counter.get(r[3], 0) + 1

wb = Workbook()

# ---- 数据页
ws = wb.active
ws.title = "原始义项总表"
LAST = len(COLS) + 1
setup_sheet(ws, title=f"表1 · 原始义项总表（{len(rows)} 动词 OALD 义项原样汇出 · 只读存档）", last_col=LAST)
for col, h in enumerate(COLS, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=LAST)
for i, r in enumerate(rows):
    rn = 5 + i
    for col, v in enumerate(r, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=LAST, row_index=i)
total = 5 + len(rows)
ws.cell(row=total, column=2, value="合计")
ws.cell(row=total, column=3, value=f"{len(rows)} 义位")
style_total_row(ws, row_num=total, col_start=2, col_end=LAST)
ws.cell(row=total + 2, column=2,
        value="本页为筛选起点的完整基线：物理移动义、隐喻义、静态义、习语、名词回退词的动词义全部保留，"
              "一律不在本表删改；筛选决策记入表2（02_义位标注 人工列），剔除义位写明理由后原样留存。").font = font_caption()
ws.freeze_panes = "D5"
ws.auto_filter.ref = f"B4:M{total - 1}"
auto_fit_columns(ws, min_width=8, max_width=44, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ---- 说明页
ws2 = wb.create_sheet("说明与三表工作流")
setup_sheet(ws2, title="表1 说明 · 三表工作流与数据血缘", last_col=3)
ws2.column_dimensions["B"].width = 20
ws2.column_dimensions["C"].width = 108
rn = 4

def sec(title):
    global rn
    ws2.cell(row=rn, column=2, value=title).font = font_subheader()
    ws2.cell(row=rn, column=2).fill = PatternFill("solid", fgColor="D6E4F0")
    ws2.cell(row=rn, column=3).fill = PatternFill("solid", fgColor="D6E4F0")
    ws2.row_dimensions[rn].height = 24
    rn += 1

def kv(k, v):
    global rn
    ws2.cell(row=rn, column=2, value=k)
    ws2.cell(row=rn, column=3, value=v)
    style_data_row(ws2, row_num=rn, col_start=2, col_end=3, row_index=rn % 2)
    rn += 1

sec("一、本表定位（只读存档）")
kv("作用", "171 个目标动词（方式 136 + 路径 22 + 互动 13）在 OALD10 的全部义项原样汇出，一字不动，作为研究基线；"
          "物理移动、抽象隐喻、静态方位、习语等全部义项都在，是筛选的起点而非结果。")
kv("固化日期", str(date.today()))
kv("规模", f"{len(rows)} 义位；来源构成：" + "、".join(f"{k} {v} 条" for k, v in sorted(src_counter.items(), key=lambda x: -x[1])))
rn += 1

sec("二、三表工作流（论文方法部分可直接写）")
kv("表1（本文件）", "全部义项原样罗列，原始存档，不可删改——保证没有\"人为抹除义项\"的嫌疑。")
kv("表2 筛选判定表", "output/02_义位标注/<动词>_义项.xlsx：A–K 列为本表的派生（只读），L–O 人工列即操作层——"
                 "意象图式、准入标签（Y / 拓展 / N）、判定理由、备注。每条义位的取舍必须写理由；"
                 "标 N（剔除）的义位不删行，留存理由备审稿核查。")
kv("表3 最终研究义位表", "docs/表3_最终研究义位表.xlsx，由 scripts/export_final_sense_list.py 从平台"
                    "人工标注结果（human_reviewed=1）提取：Y 类为核心研究义位，拓展类单独成页；"
                    "标注进行中可随时重跑，当前为 0 行属预期。")
rn += 1

sec("三、写作口径提示")
kv("术语对应", "建议方案中的\"保留/剔除\"在本项目细化为三分：Y＝保留（核心原型物理位移义）；"
            "拓展＝保留但分工不同（隐喻引申义，仅用于原型辐射网络与英汉隐喻对比，不进核心统计）；N＝剔除（静态方位/纯状态变化/习语等）。"
            "论文方法部分用三分口径，与编码手册标准 1 一致。")
kv("频次口径", "本研究语料为 Sketch Engine · enTenTen21（检索参数与日期见 output/00_数据集说明与数据字典.md），"
            "词目频次取自该语料；如改用 COCA 需全文（含搭配与 PS 计算）统一更换，属重大方法决策，需先在阶段 0 定盘。"
            "义位级频次无现成可复现来源，低频义位以\"语料证据支撑缺失\"在表2 判定理由中如实说明，不设机械阈值。")
auto_fit_row_heights(ws2, header_row=4, data_start_row=4)

wb.properties.creator = "Z.ai"
wb.save(OUT)
print(f"saved: {OUT}")
print(f"rows={len(rows)}, by source={src_counter}")
