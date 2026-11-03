#!/usr/bin/env python3
"""按用户 2026-10-08 筛选规则更新「物理位移义位表」→ 产出「义位筛选规则表」。

规则（可直接写进 4.1.2）：
  R1 剔除：完全脱离空间位移的抽象义（抽象行为/关系/状态，无空间参与者，
     也无隐喻化位移框架）——含物品破损义、竞技规则义、机械空转义；
  R2 保留：隐喻性空间位移（空间位移图式为基底，主体/目标域被抽象化），
     判定标准：能用「[某物] 从 X 移动到 Y」位移框架理解；
  R3 边界案例：保留 + 标注「需复核」，进双重核验统一判定，不直接删。

产出：docs/义位筛选规则表.xlsx
  01 筛选结果：358 候选 → 剔除 5 + 待复核 3 + 保留 350
  02 剔除与待复核明细（含理由）
  03 规则口径（论文 4.1.2 可直接引用）
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
    FONT_NAME, PRIMARY_LIGHT, setup_sheet, style_header_row, style_data_row,
    style_total_row, font_caption, auto_fit_columns, auto_fit_row_heights,
)
from openpyxl import Workbook, load_workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "义位筛选规则表.xlsx"

wb_src = load_workbook(ROOT / "docs" / "物理位移义位表.xlsx", read_only=True)
cand = []
for r in wb_src["物理位移义位"].iter_rows(min_row=5, values_only=True):
    if r[1] is None or r[1] == "合计":
        break
    cand.append({"verb": str(r[1]), "sid": f"{r[1]}-S{r[2]}", "defn": str(r[6] or ""),
                 "ex": str(r[8] or ""), "grammar": str(r[5] or "")})
wb_src.close()

# ---- R1 黑名单（明确剔除，用户判定） ----
BLACKLIST = {
    "run-S35": "R1 物品破损义：袜子/丝袜脱丝，描述织物破损过程，无空间位移参与者，亦无隐喻化位移框架",
    "rush-S6": "R1 竞技规则义：橄榄球术语（冲向持球者），编码的是竞技规则行为，非通用空间位移",
    "rush-S7": "R1 竞技规则义：橄榄球持球推进战术，同上",
    "race-S2": "R1 使役参赛义：使动物/车辆参加比赛，编码竞技事件参与，非空间位移本身",
    "race-S5": "R1 机械空转义：发动机高速空转，机械运转无整体空间位移",
    "race-S1": "R1 竞技义：与对手比速度的竞赛行为，编码竞技事件而非空间位移本身（与 race-S2 同类）",
}
# ---- R2 白名单（明确保留，用户判定） ----
WHITELIST = {
    "run-S17": "R2 隐喻性空间位移：手指在空间中划过头发——身体部位的空间移动，位移框架完整",
    "sweep-S3": "R2 受外力空间位移：船被（浪/风）卷走，客体被动整体位移",
    "sweep-S4": "R2 隐喻性空间位移：雨席卷而入——自然力过境的位移图式（源-路径-终点完整）",
    "scoot-S2": "R2 空间位移（短距）：坐姿短距离挪动，位移框架完整",
    "run-S9": "R2 空间位移（路线运行）：公交车沿路线位移，主体为车辆",
}

# ---- R3 边界标记（保留+待复核，模式识别） ----
ABSTRACT_PATTERNS = [
    r"\b(compete|competition|contest|tournament)\b",
    r"\b(engine|motor)\b.*\b(fast|quickly|run|running)\b",
    r"\b(business|company|organization|manage|operate)\b",
    r"\b(campaign|election|candidate)\b",
    r"\b(computer|machine|software|program|system|process)\b",
    r"\b(nose|liquid|water|tears|blood)\b.*\b(run|running|flow)\b",
    r"\b(newspaper|magazine|article|story|print)\b",
    r"\b(achieve|manage to)\b.*\b(difficulty|hurry)\b",
    r"\b(organization|activity)\b.*\b(leave|stop|quit)\b",
    r"\b(list|exam|race|competition)\b.*\b(name|enter|put)\b",
]
MOTION_GUARD = [
    r"\b(move|moves|moving|moved)\b",
    r"\b(travel|travels|travelling)\b",
    r"\b(walk|walks|walking)\b",
    r"\b(fly|flies|flying)\b",
    r"\b(swim|swims|swimming)\b",
    r"\b(push|carry|drive|ride)\b.*\b(somebody|something|forward)\b",
    r"\b(go|goes|going)\b.*\b(somewhere|place|direction|along|across|through)\b",
    r"\b(run|runs|running)\b.*\b(route|along|across|through|over|direction)\b",
]

review, kept = [], []
for c in cand:
    if c["sid"] in BLACKLIST:
        continue
    if c["sid"] in WHITELIST:
        kept.append({**c, "rule": "R2", "note": WHITELIST[c["sid"]]})
        continue
    d = c["defn"].lower()
    if (any(re.search(p, d) for p in ABSTRACT_PATTERNS)
            and not any(re.search(p, d) for p in MOTION_GUARD)):
        review.append({**c, "note": "R3 边界：抽象信号命中但无位移保护词，保留待双重核验统一判定"})
        kept.append({**c, "rule": "R3", "note": "边界案例：保留+需复核"})
    else:
        kept.append({**c, "rule": "R0", "note": ""})

n_r0 = sum(1 for k in kept if k["rule"] == "R0")
n_r2 = sum(1 for k in kept if k["rule"] == "R2")
n_r3 = sum(1 for k in kept if k["rule"] == "R3")

# ---- 工作簿 ----
wb = Workbook()

# 01 筛选结果总览
ws = wb.active
ws.title = "01 筛选结果"
H1 = ["规则", "判定", "义位数", "说明"]
setup_sheet(ws, title="义位筛选规则表（R1 剔除 / R2 保留 / R3 边界复核 · 2026-10-08）", last_col=len(H1) + 1)
for col, h in enumerate(H1, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=len(H1) + 1)
rows01 = [
    ("R1", "剔除", len(BLACKLIST), "完全脱离空间位移的抽象义：物品破损（run-S35）、竞技规则（rush-S6/S7、race-S2）、机械空转（race-S5）"),
    ("R2", "保留（明确）", n_r2, "隐喻性/边缘性空间位移，位移框架完整：run-S17、sweep-S3/S4、scoot-S2、run-S9"),
    ("R3", "保留＋需复核", n_r3, "边界案例：抽象信号命中但无位移保护词，进双重核验统一判定，不直接删"),
    ("R0", "保留（常规）", n_r0, "物理位移义位，无抽象信号"),
]
for i, r in enumerate(rows01):
    rn = 5 + i
    for col, v in enumerate(r, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=len(H1) + 1, row_index=i)
total = 5 + len(rows01)
ws.cell(row=total, column=2, value="合计")
ws.cell(row=total, column=4, value=len(BLACKLIST) + len(kept))
style_total_row(ws, row_num=total, col_start=2, col_end=len(H1) + 1)
auto_fit_columns(ws, min_width=8, max_width=80, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# 02 剔除与待复核明细
ws2 = wb.create_sheet("02 剔除与待复核明细")
H2 = ["SenseID", "词目", "英文释义", "例句（首条）", "判定", "理由"]
setup_sheet(ws2, title="R1 剔除明细 + R3 待复核明细（全部留痕，不删行）", last_col=len(H2) + 1)
for col, h in enumerate(H2, 2):
    ws2.cell(row=4, column=col, value=h)
style_header_row(ws2, row_num=4, col_start=2, col_end=len(H2) + 1)
rn = 5
i = 0
FILL_R1 = PatternFill("solid", fgColor="FDEDEC")
FILL_R3 = PatternFill("solid", fgColor="FEF9E7")
for sid, reason in BLACKLIST.items():
    c = next(x for x in cand if x["sid"] == sid)
    first_ex = c["ex"].split("\n")[0] if c["ex"] and c["ex"] != "None" else ""
    vals = [sid, c["verb"], c["defn"], first_ex, "R1 剔除", reason]
    for col, v in enumerate(vals, 2):
        ws2.cell(row=rn, column=col, value=v)
    style_data_row(ws2, row_num=rn, col_start=2, col_end=len(H2) + 1, row_index=i)
    for col in range(2, len(H2) + 2):
        ws2.cell(row=rn, column=col).fill = FILL_R1
    rn += 1; i += 1
for c in review:
    first_ex = c["ex"].split("\n")[0] if c["ex"] and c["ex"] != "None" else ""
    vals = [c["sid"], c["verb"], c["defn"], first_ex, "R3 待复核", c["note"]]
    for col, v in enumerate(vals, 2):
        ws2.cell(row=rn, column=col, value=v)
    style_data_row(ws2, row_num=rn, col_start=2, col_end=len(H2) + 1, row_index=i)
    for col in range(2, len(H2) + 2):
        ws2.cell(row=rn, column=col).fill = FILL_R3
    rn += 1; i += 1
ws2.cell(row=rn + 1, column=2,
         value="R1 剔除的义位完整留痕（含理由），与表 2 的 N 类处理一致：不删行、可回溯。"
               "R3 待复核条目在双重核验（LLM 初筛 + 人工复核）中统一判定后升级为 R0/R1/R2。").font = font_caption()
auto_fit_columns(ws2, min_width=8, max_width=70, header_row=4, data_start_row=5)
auto_fit_row_heights(ws2, header_row=4, data_start_row=5)

# 03 保留义位全量（350 条）
ws3 = wb.create_sheet("03 保留义位全量")
H3 = ["SenseID", "词目", "语法码", "英文释义", "例句（首条）", "规则", "备注"]
setup_sheet(ws3, title="保留义位全量（R0 常规 + R2 明确保留 + R3 边界复核）", last_col=len(H3) + 1)
for col, h in enumerate(H3, 2):
    ws3.cell(row=4, column=col, value=h)
style_header_row(ws3, row_num=4, col_start=2, col_end=len(H3) + 1)
for i, k in enumerate(kept):
    rn = 5 + i
    first_ex = k["ex"].split("\n")[0] if k["ex"] and k["ex"] != "None" else ""
    vals = [k["sid"], k["verb"], k["grammar"], k["defn"], first_ex, k["rule"], k["note"]]
    for col, v in enumerate(vals, 2):
        ws3.cell(row=rn, column=col, value=v)
    style_data_row(ws3, row_num=rn, col_start=2, col_end=len(H3) + 1, row_index=i)
    if k["rule"] == "R2":
        ws3.cell(row=rn, column=7).fill = PatternFill("solid", fgColor="E8F5E9")
    elif k["rule"] == "R3":
        ws3.cell(row=rn, column=7).fill = FILL_R3
total3 = 5 + len(kept)
ws3.cell(row=total3, column=2, value="合计")
ws3.cell(row=total3, column=3, value=f"{len(kept)} 义位")
style_total_row(ws3, row_num=total3, col_start=2, col_end=len(H3) + 1)
ws3.freeze_panes = "D5"
ws3.auto_filter.ref = f"B4:H{total3 - 1}"
auto_fit_columns(ws3, min_width=8, max_width=60, header_row=4, data_start_row=5)
auto_fit_row_heights(ws3, header_row=4, data_start_row=5)

# 04 规则口径（论文 4.1.2 可直接引用）
ws4 = wb.create_sheet("04 规则口径")
setup_sheet(ws4, title="义位筛选规则口径（论文 4.1.2 可直接引用）", last_col=3)
ws4.column_dimensions["B"].width = 22
ws4.column_dimensions["C"].width = 100
rn = 4
for k, v in [
    ("规则 R1（剔除）", "完全脱离空间位移的抽象义：释义核心描述抽象行为、关系或状态，无空间移动参与者，"
                   "亦无隐喻化的位移框架。典型：物品破损义（run-S35 袜子脱丝）、竞技规则义（rush-S6/S7 橄榄球术语、"
                   "race-S2 使役参赛）、机械空转义（race-S5 发动机空转）。"),
    ("规则 R2（保留）", "隐喻性空间位移：以空间位移图式为基底，主体或目标域被抽象化。判定标准——"
                   "能否用「[某物] 从 X 移动到 Y」的位移框架理解。典型：run-S17（手指划过头发，身体部位空间移动）、"
                   "sweep-S3（船被浪卷走，受外力位移）、sweep-S4（雨席卷，源-路径-终点完整）、scoot-S2（坐姿短距挪动）、"
                   "run-S9（公交沿路线运行）。"),
    ("规则 R3（边界）", "介于抽象与位移之间的义位不擅自杀：保留并标记「需复核」，进入双重核验统一判定。"
                   "好处：筛选过程可复现、可辩护，体现方法严谨性。本批标记 3 条（scramble-S3、desert-S4、enter-S2）。"),
    ("一句话口径", "剔除的是「没有空间位移的语义」（抽象义、静态义、专业术语义）；"
               "保留的是「空间位移的隐喻/边缘用法」（主体变了、方向变了，但图式仍是位移框架）。"),
    ("与既有流程关系", "本规则作用于物理位移义位表（358 候选）之上，属表 2 判定层的规则细化；"
                  "R1 剔除对应编码手册 N 类（留痕不删行），R2/R3 保留义位仍须走 LLM 初筛＋人工复核的完整流程。"),
    ("生成信息", f"生成日期 {date.today()}；脚本 scripts/export_sense_rule_table.py 可重跑；"
             f"黑/白名单与模式规则调整后整体再生。"),
]:
    ws4.cell(row=rn, column=2, value=k)
    ws4.cell(row=rn, column=3, value=v)
    style_data_row(ws4, row_num=rn, col_start=2, col_end=3, row_index=rn % 2)
    rn += 1
auto_fit_row_heights(ws4, header_row=4, data_start_row=4)

wb.properties.creator = "Z.ai"
wb.save(OUT)
print(f"saved: {OUT}")
print(f"R1剔除={len(BLACKLIST)}, R2明确保留={n_r2}, R3待复核={n_r3}, R0常规保留={n_r0}, 总保留={len(kept)}")
