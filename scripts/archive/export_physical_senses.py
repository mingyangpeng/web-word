#!/usr/bin/env python3
"""导出「物理位移义位表」——词表义项清单的物理位移子集（表头不变，仅 OALD10 来源）。

筛选口径（与编码手册标准 1 对齐的机械近似，供 LLM 初筛与人工复核的候选层）：
  1. 来源 = OALD10（补充来源 4 词的义位不在本表，另行处理）；
  2. 排除习语义项（IDIOMS 组，按手册一般归 N 或拓展）；
  3. 释义文本的物理位移关键词/短语匹配（walk/run/move/go/travel/fly 等动词核心、
     direction/ground/surface/place 等位移要素）；
  4. 排除明显的非位移释义（纯状态/属性/声音/光义等负向词表）。

⚠️ 定位声明：这是【机械候选层】，不是准入判定结果。真正的 Y/拓展/N 标签
   必须由 LLM 初筛 + 人工复核（编码手册流程）确定；本表只把"明显非物理位移"
   的义位先排除出候选池，缩小初筛范围。每行保留判定所需的全部字段（表头与
   词表义项清单「义项明细」完全一致），复核时直接在此表或平台操作。

产出：docs/物理位移义位表.xlsx
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

XLSX_SKILL_DIR = "/Users/jhon/.zcode/cli/plugins/cache/zcode-plugins-official/spreadsheets/0.1.7/skills/xlsx"
for sub in [XLSX_SKILL_DIR, os.path.join(XLSX_SKILL_DIR, "templates")]:
    if sub not in sys.path:
        sys.path.insert(0, sub)
from base import (  # noqa: E402
    FONT_NAME, FORMATS, PRIMARY_LIGHT, setup_sheet, style_header_row,
    style_data_row, style_total_row, font_caption, font_subheader,
    auto_fit_columns, auto_fit_row_heights,
)
from openpyxl import Workbook, load_workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "词表义项清单.xlsx"
OUT = ROOT / "docs" / "物理位移义位表.xlsx"

# ---- 机械筛选规则（候选层近似，非准入判定） ----

# 物理位移释义的正向信号：释义里出现这些核心动词或位移要素
POS_PATTERNS = [
    r"\b(walk|run|move|go|travel|fly|swim|jump|leap|climb|crawl|creep|ride|drive|sail|row|paddle|ski|skate|cycle|drift|float|glide|slide|roll|bounce|hop|skip|dash|rush|hurry|march|stroll|wander|roam|stray|stumble|stagger|limp|hobble|tiptoe|sneak|slip|dash|dart|bolt|race|chase|follow|pursue|flee|escape|leave|depart|arrive|enter|exit|return|cross|ascend|descend|rise|fall|drop|plunge|tumble|advance|proceed|head)\b",
    r"\b(in a particular )?direction\b",
    r"\b(somewhere|another place|a place|some place)\b.*\b(go|move|travel|walk)\b",
    r"\b(go|move|travel|walk|fly|swim)\b.*\b(somewhere|place|direction|forward|backward|up|down|along|across|through|toward|away)\b",
    r"\b(with difficulty|quickly|slowly|fast|rapidly|steadily|smoothly|gracefully|suddenly)\b.*\b(move|walk|go|travel)\b",
    r"\b(manner|way|style|gait|speed|pace)\b.*\b(moving|movement|walking|running)\b",
    r"\b(movement|motion)\b",
    r"\b(body|legs|feet|wings|arms)\b.*\b(move|moving)\b",
    r"\b(of a vehicle|of a boat|of a plane|of an aircraft|of a bird|of an animal|of a fish)\b",
    r"\b(support|carry|transport|convey|take|bring|send|guide|lead|escort)\b.*\b(somebody|something|someone)\b.*\b(to|from|through|across)\b",
    r"\b(get|gets|getting)\b.*\b(to|into|inside|out of)\b.*\b(place|building|room|position|destination|place)\b",
    r"\b(reach|reaches|reaching)\b",
    r"\b(to (go and )?(get|fetch|collect|pick up))\b",
    r"\b(of a person|of people|of an animal|of animals)\b",
]

# 明确的非位移负向信号：命中即排除（在正向命中之后二次过滤）
NEG_PATTERNS = [
    r"\b(become|grow|turn)\b.*\b(bigger|smaller|larger|less|more|worse|better)\b",
    r"\b(increase|decrease|rise|fall)\b.*\b(price|value|temperature|number|amount|level|rate|sound|volume)\b",
    r"\b(sound|noise|voice|music|song|tune)\b",
    r"\b(light|colour|color|glow|shine|sparkle|flash)\b",
    r"\b(feel|feeling|emotion|mood|sense|sensation)\b",
    r"\b(think|believe|understand|know|realize|remember|imagine)\b",
    r"\b(say|tell|speak|talk|mention|discuss|argue)\b",
    r"\b(of a clock|of a watch|of time|of the time)\b",
    r"\b(die|death|dead|alive|live|life)\b",
    r"\b(make|cause)\b.*\b(somebody|something)\b.*\b(to be|feel|become)\b",
    r"\b(happen|occur|take place)\b",
    r"\b(exist|be present|remain|stay)\b.*\b(state|condition|situation)\b",
    r"\b(flow|pour|stream)\b.*\b(liquid|water|blood|tears)\b",
    r"\b(of a plant|of a tree|of leaves|of hair)\b",
    r"\b(dry|wet|moist|damp)\b",
    r"\b(shape|form|appearance|look|seem)\b",
    r"\b(quantity|quality|degree|extent|amount)\b",
]

def classify(defn: str):
    """返回 (是否保留候选, 命中正向信号数, 命中负向信号数)。"""
    if not defn:
        return False, 0, 0
    d = defn.lower()
    pos = sum(1 for p in POS_PATTERNS if re.search(p, d))
    neg = sum(1 for p in NEG_PATTERNS if re.search(p, d))
    # 强位移信号（pos>=2）可压过单个弱负向信号；仅弱正向时负向一票否决
    keep = (pos >= 2 and neg <= 1) or (pos >= 1 and neg == 0)
    return keep, pos, neg

# ---- 读取与筛选 ----
wb_src = load_workbook(SRC, read_only=True)
ws_src = wb_src["义项明细"]
headers = [c.value for c in next(ws_src.iter_rows(min_row=1, max_row=1))]

kept, dropped_idiom, dropped_source, dropped_semantic = [], 0, 0, 0
for r in ws_src.iter_rows(min_row=2, values_only=True):
    if not r[0]:
        continue
    row = list(r)
    # 列：词目0 义项序号1 来源2 语义分组3 语法码4 英文释义5 例句数6 例句7 句法模式8 是否习语9 原型义10 来源词条11
    if row[2] != "OALD10":
        dropped_source += 1
        continue
    if row[9] == "是":
        dropped_idiom += 1
        continue
    keep, pos, neg = classify(str(row[5] or ""))
    if keep:
        kept.append(row)
    else:
        dropped_semantic += 1
wb_src.close()

# ---- 写出（表头不变） ----
wb = Workbook()
ws = wb.active
ws.title = "物理位移义位"
LAST = len(headers) + 1
setup_sheet(ws, title=f"物理位移义位表（机械候选层 · {len(kept)} 条 / OALD10）", last_col=LAST)
for col, h in enumerate(headers, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=LAST)
for i, row in enumerate(kept):
    rn = 5 + i
    for col, v in enumerate(row, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=LAST, row_index=i)
total = 5 + len(kept)
ws.cell(row=total, column=2, value="合计")
ws.cell(row=total, column=3, value=f"{len(kept)} 义位")
ws.cell(row=total, column=4, value=f"{len(set(r[0] for r in kept))} 词")
style_total_row(ws, row_num=total, col_start=2, col_end=LAST)
ws.freeze_panes = "D5"
ws.auto_filter.ref = f"B4:M{total - 1}"
auto_fit_columns(ws, min_width=6, max_width=60, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ---- 说明页 ----
ws2 = wb.create_sheet("筛选口径说明")
setup_sheet(ws2, title="物理位移义位表 · 筛选口径与定位", last_col=3)
ws2.column_dimensions["B"].width = 22
ws2.column_dimensions["C"].width = 100
rn = 4

def kv(k, v, warn=False):
    global rn
    ws2.cell(row=rn, column=2, value=k)
    ws2.cell(row=rn, column=3, value=v)
    style_data_row(ws2, row_num=rn, col_start=2, col_end=3, row_index=rn % 2)
    if warn:
        ws2.cell(row=rn, column=3).font = Font(name=FONT_NAME, size=11, color="C0392B")
    rn += 1

kv("本表定位", "机械候选层：把明显非物理位移的义位先排除出候选池，缩小 LLM 初筛与人工复核范围。"
            "不是准入判定结果——Y/拓展/N 最终标签仍须按编码手册由 LLM 初筛＋人工复核确定。", warn=True)
kv("数据来源", "docs/词表义项清单.xlsx「义项明细」，仅取来源=OALD10 的 992 条；表头与原表完全一致。")
kv("筛选规则", "三步机械规则：①排除习语义项（是否习语=是，258 条）；②释义文本正向匹配物理位移信号"
            "（移动动词核心词、位移方向/处所要素、方式状语、载具/动物主体等 10 类正则）；"
            "③负向信号一票否决（状态变化、声音、光、情感、认知、言语、植物、液体流等 17 类正则）。")
kv("筛选结果", f"992 条 OALD10 义位 → 保留候选 {len(kept)} 条；排除：习语 {dropped_idiom} 条、"
            f"非 OALD10 来源 {dropped_source} 条、语义信号未命中 {dropped_semantic} 条。")
kv("已知局限", "机械正则必然有误伤与漏判：如 go 的抽象义（go mad）可能因正向词命中而保留，"
            "而某些真实位移义位因释义措辞特殊被误排。因此本表只作候选池，边界义位以人工判定为准；"
            "被误排的义位可在原表（词表义项清单）复核后手动加回。")
kv("与三表工作流关系", "本表 = 表 2（筛选判定层）的候选输入之一；准入标签与判定理由仍写入表 2 / 标注平台。")
kv("生成信息", f"生成日期 {date.today()}；脚本 scripts/export_physical_senses.py 可重跑；"
            f"规则调整（正则增删）后重跑即整体再生。")
auto_fit_row_heights(ws2, header_row=4, data_start_row=4)

wb.properties.creator = "Z.ai"
wb.save(OUT)
print(f"saved: {OUT}")
print(f"kept={len(kept)} ({len(set(r[0] for r in kept))} verbs), "
      f"dropped: idiom={dropped_idiom}, source={dropped_source}, semantic={dropped_semantic}")
