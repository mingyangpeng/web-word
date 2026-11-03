#!/usr/bin/env python3
"""导出「图式候选核查表」xlsx（服务 Lexikos Project 论文写作）。

数据来源（可复跑，与数据集血缘一致）：
  - 应用库 word_schema_scores / corpus_word_stats / corpus_collocations（词目层图式初筛与频次）
  - docs/词表义项清单.xlsx「词表概览」（Levin 主范畴/次类/词目层图式初判）
  - data/corpus/pilot_verbs.json（试点 12 词及选取理由）

产出：docs/图式候选核查表.xlsx，5 个工作表：
  00 说明与论文对接 / 01 核查总表(136词) / 02 四图式构成与判读 /
  03 图式×次类交叉 / 04 试点覆盖检查
"""

import json
import subprocess
import sys
import os
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

XLSX_SKILL_DIR = "/Users/jhon/.zcode/cli/plugins/cache/zcode-plugins-official/spreadsheets/0.1.7/skills/xlsx"
for sub in [XLSX_SKILL_DIR, os.path.join(XLSX_SKILL_DIR, "templates")]:
    if sub not in sys.path:
        sys.path.insert(0, sub)
from base import (  # noqa: E402
    FONT_NAME, HEADER_BOLD, PRIMARY, PRIMARY_LIGHT, SECONDARY,
    ACCENT_POSITIVE, ACCENT_WARNING, NEUTRAL_600, NEUTRAL_900,
    FORMATS, font_subheader, font_caption,
    setup_sheet, style_header_row, style_data_row, style_total_row,
    auto_fit_columns, auto_fit_row_heights,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "图式候选核查表.xlsx"

# ---------------------------------------------------------------- 数据获取

def mysql_rows(sql):
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text())["database"]["mysql"]
    host = cfg["host"] if cfg["host"] != "mysql" else "127.0.0.1"  # 容器外回退
    cmd = ["mysql", f"-h{host}", f"-P{cfg['port']}", f"-u{cfg['user']}",
           f"-p{cfg['password']}", cfg["database"], "-N", "-B", "-e", sql]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [line.split("\t") for line in out.splitlines() if line.strip()]

# 词表：verb -> (次类, 词目层初判图式)
lex = {}
wb_lex = load_workbook(ROOT / "docs" / "词表义项清单.xlsx", read_only=True)
for row in wb_lex["词表概览"].iter_rows(min_row=2, values_only=True):
    if row[0]:
        lex[str(row[0]).strip()] = (str(row[3]).strip(), str(row[4]).strip())
wb_lex.close()

# 语料 AI 候选：verb -> (freq, cand_schema)
cand = {r[0]: (int(r[1]), r[2]) for r in
        mysql_rows("SELECT verb, freq, candidate_schema FROM corpus_word_stats;")}

# 四图式得分：verb -> {rank: (schema, score)}
scores = defaultdict(dict)
for verb, name, score, rank in mysql_rows(
        "SELECT verb, schema_name, prominence_score, cand_rank FROM word_schema_scores;"):
    scores[verb][int(rank)] = (name, float(score))

# 试点 12 词
pilot_json = json.loads((ROOT / "data" / "corpus" / "pilot_verbs.json").read_text())
pilot = {p["verb"]: p for p in pilot_json["verbs"]}
pilot_coll = {r[0]: int(r[1]) for r in mysql_rows(
    "SELECT verb, COUNT(*) FROM corpus_collocations WHERE verb IN "
    "('run','walk','fly','drop','jump','roll','charge','sweep','drift','sneak','limp','dart') "
    "GROUP BY verb;")}

# ---------------------------------------------------------------- 分析

NOISE = {  # 18 个与词表初判不一致的词：初步判读（待人工复核）
    "tear": "同形词形混杂：tear（撕裂）动词语料大量混入，词目层频次含大量非位移用法",
    "speed": "方式词被 goal-PP 槽位覆盖推高；另含超速/提速等非自移动词义",
    "hurtle": "方式词，into/through 类 PP 槽位覆盖推高",
    "clamber": "方式词（攀爬），PP 槽位覆盖推高",
    "slog": "方式词，PP 槽位覆盖推高",
    "tiptoe": "方式词，goal-PP 槽位覆盖推高",
    "swagger": "方式词，goal-PP 槽位覆盖推高",
    "traipse": "方式词，goal-PP 槽位覆盖推高",
    "lope": "方式词，goal-PP 槽位覆盖推高",
    "scud": "低频方式词，与第二名分差仅 0.07，候选归属不稳",
    "ferry": "伪互动：passengers/cargo 类宾语槽位造成双实体共现，非互动位移语义",
    "jet": "伪互动：宾语槽位（jet sth）造成双实体共现",
    "oar": "伪互动：工具/宾语槽位噪声；极低频",
    "rove": "低频词，槽位噪声",
    "troop": "伪互动：复数群体主语类槽位噪声",
    "promenade": "低频词，槽位噪声",
    "lollop": "极低频，噪声",
    "sweep": "词目主导义为「打扫」（及物使役），位移感来自隐喻用法 sweep through/into，源点脱离候选不可靠",
}

GROUP_ORDER = ["方式伴随图式", "终点抵达图式", "互动位移图式", "源点脱离图式"]
rows = []
for verb, (freq, cs) in cand.items():
    sub, lex_schema = lex.get(verb, ("—", "—"))
    s1, s2 = scores[verb].get(1, ("—", None)), scores[verb].get(2, ("—", None))
    margin = round(s1[1] - s2[1], 2) if s1[1] is not None and s2[1] is not None else None
    fuzzy = margin is not None and margin < 2.0
    agree = "一致" if lex_schema == cs else "不一致"
    note = NOISE.get(verb) or ("第一、二名图式分差 <2，归属不稳" if fuzzy else "—")
    action = ("义位层重建归属（词目层候选视为噪声）" if verb in NOISE
              else "人工复核优先" if fuzzy else "常规复核确认")
    rows.append({
        "verb": verb, "freq": freq, "sub": sub, "lex": lex_schema, "cand": cs,
        "s1": s1, "s2": s2, "margin": margin, "fuzzy": fuzzy, "agree": agree,
        "note": note, "action": action,
        "pilot": "★" if verb in pilot else "",
    })
rows.sort(key=lambda r: (GROUP_ORDER.index(r["cand"]), -r["freq"]))

# ---------------------------------------------------------------- 样式辅助

FILL_WARN = PatternFill("solid", fgColor="FEF9E7")
FILL_POS = PatternFill("solid", fgColor="E8F5E9")
FILL_INPUT = PatternFill("solid", fgColor=PRIMARY_LIGHT)   # 人工填写列
FONT_WARN = Font(name=FONT_NAME, size=11, color=ACCENT_WARNING)
FONT_POS = Font(name=FONT_NAME, size=11, color=ACCENT_POSITIVE)

def set_num(ws, row, col, fmt):
    c = ws.cell(row=row, column=col)
    c.number_format = fmt
    c.alignment = Alignment(horizontal="right", vertical="center")

def section_title(ws, row, text, last_col):
    ws.cell(row=row, column=2, value=text).font = font_subheader()
    ws.cell(row=row, column=2).fill = PatternFill("solid", fgColor=SECONDARY)
    for col in range(3, last_col + 1):
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=SECONDARY)
    ws.row_dimensions[row].height = 24

def kv_row(ws, row, key, value, idx):
    ws.cell(row=row, column=2, value=key)
    ws.cell(row=row, column=3, value=value)
    style_data_row(ws, row_num=row, col_start=2, col_end=3, row_index=idx)

wb = Workbook()

# ================================================= 00 说明与论文对接
ws = wb.active
ws.title = "00 说明与论文对接"
setup_sheet(ws, title="图式候选核查表 · 说明与论文对接", last_col=3)
ws.column_dimensions["B"].width = 22
ws.column_dimensions["C"].width = 110

r = 4
section_title(ws, r, "一、本表定位", 3); r += 1
info = [
    ("用途", "固化词目层图式候选初筛的核查结果，服务 MOVECAT/Lexikos Project 论文写作："
            "§4.1 试点选取依据、§2/§3 图式体系与工作流表述、RQ1 三域七系的词目层基础、33 个模糊词的人工复核清单。"),
    ("数据来源", "应用库 word_schema_scores / corpus_word_stats（初筛检索 2026-09-30，enTenTen21）＋ "
               "docs/词表义项清单.xlsx「词表概览」（Levin 次类与词目层初判）＋ data/corpus/pilot_verbs.json（试点 12 词）。"),
    ("重要口径", "01–03 表均为【词目层】初筛（每词一个候选凸显图式，重心得分 S = Mean_logDice × log2(N+1)，"
              "未做语义归类），【不是义位层】结论；义位层图式归属以试点标注（232 义位）为准。"),
    ("复跑方式", "python3 scripts/export_schema_review_workbook.py（自动从库与词表重新生成本文件）。"),
]
for i, (k, v) in enumerate(info):
    kv_row(ws, r, k, v, i); r += 1
r += 1

section_title(ws, r, "二、三大结构发现（写作前必读）", 3); r += 1
findings = [
    ("发现①", "方式伴随 118/136（86.8%）——词目层候选分布高度偏斜，方式伴随内部必须按 8 个 Levin 次类细分，"
            "否则无法支撑分范畴释义模板。"),
    ("发现②", "终点抵达 10 词、互动位移 7 词、源点脱离 1 词经核查【基本为噪声候选】（同形词形/伪互动宾语槽位/"
            "隐喻用法/低频槽位噪声），18 词与词表初判全部不一致，另有 33 词分差 Δ<2 归属不稳。"),
    ("发现③", "词表 136 词 100% 为方式聚焦型；编码手册中源点脱离（leave/depart）、终点抵达（arrive/reach）、"
            "互动位移（chase/follow/accompany）的经典例词均不在词表内 → 需在路线 A/B 间做出决策（见「待决事项」）。"),
]
for i, (k, v) in enumerate(findings):
    kv_row(ws, r, k, v, i); r += 1
r += 1

section_title(ws, r, "三、工作表清单与论文对接", 3); r += 1
ws.cell(row=r, column=2, value="工作表")
ws.cell(row=r, column=3, value="内容 → 论文用途")
style_header_row(ws, row_num=r, col_start=2, col_end=3); r += 1
sheets_doc = [
    ("01 核查总表", "136 词逐词核查（初判 vs 语料候选、分差、模糊/不一致标记、试点标记）→ §3.1 工作流"
                 "「语料初筛候选 → 人工校验」环节的证据；§4.3 人工校正候选义位的实例素材来源。"),
    ("02 四图式构成与判读", "四类候选的成员清单与噪声判读 → §2.2/讨论中说明词目层初筛局限（呼应「统计簇≠义位」）。"),
    ("03 图式×次类交叉", "候选图式 × Levin 次类矩阵 → RQ1（三域七系）词目层基础矩阵；义位层标注完成后在本表基础上更新。"),
    ("04 试点覆盖检查", "试点 12 词的次类覆盖与工作量（义位数/搭配行数）→ §4.1 试点选取论证；含次类覆盖缺口与补词建议。"),
    ("00 本页", "数据口径、结构发现、决策点 → 写作前通读；投稿核查时对照。"),
]
for i, (k, v) in enumerate(sheets_doc):
    kv_row(ws, r, k, v, i); r += 1
r += 1

section_title(ws, r, "四、待决事项", 3); r += 1
todo_rows = [
    ("决策点：路线 A/B", "路线 A＝扩词表，补入路径聚焦与互动位移词元（开题报告五类构成 159 词），四图式获真实词元；"
                    "路线 B＝保持方式聚焦词表，由义位层标注让方式动词义位跨图式自然分布，模板按「图式×次类×句法型」设计。"
                    "建议：试点阶段走路线 B（不动词表，232 义位标注直接产出 RQ1 数据）；博士论文如需覆盖全部图式模板再扩词表。"
                    "该决策影响论文 §2 理论框架与 §3 工作流的表述，动笔前与导师确认。"),
    ("人工复核任务", "01 表中 33 个 Δ<2 模糊词 + 18 个不一致词优先复核，在「人工复核图式」列给出词目层裁定并写明依据。"),
    ("口径统一", "论文 §4.4 与编码手册的信度指标需统一（大纲用 Krippendorff's α，手册用 Kappa），投稿前定稿。"),
]
for i, (k, v) in enumerate(todo_rows):
    kv_row(ws, r, k, v, i); r += 1

auto_fit_row_heights(ws, header_row=4, data_start_row=4)

# ================================================= 01 核查总表
ws = wb.create_sheet("01 核查总表")
HEADERS = ["序号", "动词", "语料频次", "Levin次类", "词表初判图式", "语料AI候选图式",
           "S1图式", "S1得分", "S2图式", "S2得分", "分差Δ", "初判vs候选",
           "模糊(Δ<2)", "初步判读（待人工复核）", "试点词", "建议处理",
           "人工复核图式", "复核备注"]
LAST = len(HEADERS) + 1
setup_sheet(ws, title="136 词图式候选核查总表（词目层初筛 · 2026-09-30 检索）", last_col=LAST)
for col, h in enumerate(HEADERS, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=LAST)

for i, rd in enumerate(rows):
    rn = 5 + i
    vals = [i + 1, rd["verb"], rd["freq"], rd["sub"], rd["lex"], rd["cand"],
            rd["s1"][0], rd["s1"][1], rd["s2"][0], rd["s2"][1], rd["margin"],
            rd["agree"], "是" if rd["fuzzy"] else "", rd["note"], rd["pilot"],
            rd["action"], None, None]
    for col, v in enumerate(vals, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=LAST, row_index=i)
    set_num(ws, rn, 4, FORMATS["integer"])
    for col, fmt in ((9, FORMATS["decimal_2"]), (11, FORMATS["decimal_2"]),
                     (12, FORMATS["decimal_2"])):
        set_num(ws, rn, col, fmt)
    # 行级标记：不一致行整行琥珀底；模糊词 Δ 单元格琥珀字；试点词绿底
    if rd["agree"] == "不一致":
        for col in range(2, LAST + 1):
            ws.cell(row=rn, column=col).fill = FILL_WARN
    if rd["fuzzy"]:
        ws.cell(row=rn, column=13).font = FONT_WARN
    if rd["pilot"]:
        ws.cell(row=rn, column=16).fill = FILL_POS
        ws.cell(row=rn, column=16).font = FONT_POS
    # 人工填写列底色
    for col in (18, 19):
        ws.cell(row=rn, column=col).fill = FILL_INPUT

total_row = 5 + len(rows)
ws.cell(row=total_row, column=2, value="合计")
ws.cell(row=total_row, column=3, value=f"{len(rows)} 词")
ws.cell(row=total_row, column=4, value=sum(r["freq"] for r in rows))
style_total_row(ws, row_num=total_row, col_start=2, col_end=LAST)
set_num(ws, total_row, 4, FORMATS["integer"])
ws.cell(row=total_row + 2, column=2,
        value="注：琥珀底行＝与词表初判不一致（基本为噪声候选）；「模糊(Δ<2)」琥珀字＝分差不足 2 分，复核优先；"
              "★＝试点词；浅蓝两列为人工填写区。").font = font_caption()
ws.freeze_panes = "D5"
ws.auto_filter.ref = f"B4:{get_column_letter(LAST)}{total_row - 1}"
auto_fit_columns(ws, min_width=8, max_width=42, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ================================================= 02 四图式构成与判读
ws = wb.create_sheet("02 四图式构成与判读")
H2 = ["候选图式", "词数", "占比", "成员（按语料频次降序）", "初步判读", "论文表述建议"]
setup_sheet(ws, title="四类图式候选的词目构成与判读", last_col=len(H2) + 1)
for col, h in enumerate(H2, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=len(H2) + 1)

GROUP_NOTE = {
    "方式伴随图式": ("词表主体的真实成员类；词目层候选可信，但 87% 的占比说明它只是顶层，"
                "内部必须按 8 个 Levin 次类细分（见 03 表），义位层还需叠加入准/图式标注。"),
    "终点抵达图式": ("基本为噪声候选：tear 为同形词形混杂（撕裂义），其余为方式词被 goal-PP 槽位覆盖推高；"
                "义位层真实归属以试点标注为准。"),
    "互动位移图式": ("伪互动：宾语/工具槽位造成的双实体共现（ferry passengers 类）；编码手册例词 "
                "chase/follow/accompany 不在词表中，互动位移的真实成员要在义位层（使役/伴随用法）重建。"),
    "源点脱离图式": ("噪声候选：sweep 词目主导义为「打扫」，位移感来自隐喻用法；源点脱离图式在词目层没有真实成员。"),
}
GROUP_PAPER = {
    "方式伴随图式": "正文可报告为初筛主分布，并以其偏斜论证「词目层初筛必须细分＋人工归类」的方法主张。",
    "终点抵达图式": "正文报告初筛分布时注明噪声来源（数据字典 §3.3 已注明「未语义归类」），作为局限与人工校验必要性的证据。",
    "互动位移图式": "支撑「统计簇≠语言学义位」论证；与词表初判的 18 处冲突可写入 §4.3 校正案例。",
    "源点脱离图式": "同上；并在局限中说明方式聚焦词表对图式覆盖的影响（关联路线 A/B 决策）。",
}
group_members = defaultdict(list)
for rd in rows:
    group_members[rd["cand"]].append(rd["verb"])

rn = 5
for i, g in enumerate(GROUP_ORDER):
    members = group_members.get(g, [])
    vals = [g, len(members), len(members) / len(rows),
            ", ".join(members), GROUP_NOTE[g], GROUP_PAPER[g]]
    for col, v in enumerate(vals, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=len(H2) + 1, row_index=i)
    set_num(ws, rn, 3, FORMATS["integer"])
    set_num(ws, rn, 4, FORMATS["percentage"])
    rn += 1
ws.cell(row=rn, column=2, value="合计")
ws.cell(row=rn, column=3, value=len(rows))
ws.cell(row=rn, column=4, value=1.0)
style_total_row(ws, row_num=rn, col_start=2, col_end=len(H2) + 1)
set_num(ws, rn, 3, FORMATS["integer"])
set_num(ws, rn, 4, FORMATS["percentage"])
ws.column_dimensions["E"].width = 72
ws.column_dimensions["F"].width = 46
ws.column_dimensions["G"].width = 46
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ================================================= 03 图式×次类交叉
ws = wb.create_sheet("03 图式×次类交叉")
subs = []
for rd in rows:
    if rd["sub"] not in subs:
        subs.append(rd["sub"])
H3 = ["候选图式"] + subs + ["合计"]
setup_sheet(ws, title="候选图式 × Levin 次类 交叉矩阵（词目数）", last_col=len(H3) + 1)
for col, h in enumerate(H3, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=len(H3) + 1)

xtab = defaultdict(Counter)
for rd in rows:
    xtab[rd["cand"]][rd["sub"]] += 1
rn = 5
for i, g in enumerate(GROUP_ORDER):
    vals = [g] + [xtab[g][s] for s in subs] + [sum(xtab[g].values())]
    for col, v in enumerate(vals, 2):
        ws.cell(row=rn, column=col, value=v)
    style_data_row(ws, row_num=rn, col_start=2, col_end=len(H3) + 1, row_index=i)
    for col in range(3, len(H3) + 2):
        set_num(ws, rn, col, FORMATS["integer"])
    rn += 1
vals = ["合计"] + [sum(xtab[g][s] for g in GROUP_ORDER) for s in subs] + [len(rows)]
for col, v in enumerate(vals, 2):
    ws.cell(row=rn, column=col, value=v)
style_total_row(ws, row_num=rn, col_start=2, col_end=len(H3) + 1)
for col in range(3, len(H3) + 2):
    set_num(ws, rn, col, FORMATS["integer"])
ws.cell(row=rn + 2, column=2,
        value="读法：方式伴随 118 词横跨全部 8 个次类（陆地 40 / 奔跑 21 / 运载工具 19 / 滚动滑行 12 / 腾空跳跃 12 / "
              "长途 7 / 匍匐 4 / 飞行游动 3）——这就是「方式伴随必须细分」的直接依据；另三类共 18 词的次类分布"
              "见 02 表判读（噪声候选）。义位层标注完成后，建议按本表结构输出「义位层图式 × 次类」矩阵作为 RQ1 的正式结果。").font = font_caption()
auto_fit_columns(ws, min_width=9, max_width=20, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ================================================= 04 试点覆盖检查
ws = wb.create_sheet("04 试点覆盖检查")
H4 = ["动词", "语料频次", "义位数", "Levin次类", "词表初判", "语料候选", "搭配明细行数", "选取理由"]
setup_sheet(ws, title="试点 12 词覆盖检查（对应论文 §4.1）", last_col=len(H4) + 1)
for col, h in enumerate(H4, 2):
    ws.cell(row=4, column=col, value=h)
style_header_row(ws, row_num=4, col_start=2, col_end=len(H4) + 1)

rn = 5
pilot_sorted = sorted(pilot.values(), key=lambda p: -p["freq"])
for i, p in enumerate(pilot_sorted):
    v = p["verb"]
    sub, lex_schema = lex.get(v, ("—", "—"))
    _, cs = cand.get(v, (None, "—"))
    vals = [v, p["freq"], p["senses"], sub, lex_schema, cs,
            pilot_coll.get(v, 0), p["rationale"]]
    for col, val in enumerate(vals, 2):
        ws.cell(row=rn, column=col, value=val)
    style_data_row(ws, row_num=rn, col_start=2, col_end=len(H4) + 1, row_index=i)
    set_num(ws, rn, 3, FORMATS["integer"])
    set_num(ws, rn, 4, FORMATS["integer"])
    set_num(ws, rn, 8, FORMATS["integer"])
    rn += 1
ws.cell(row=rn, column=2, value="合计")
ws.cell(row=rn, column=4, value=sum(p["senses"] for p in pilot_sorted))
ws.cell(row=rn, column=8, value=sum(pilot_coll.get(p["verb"], 0) for p in pilot_sorted))
style_total_row(ws, row_num=rn, col_start=2, col_end=len(H4) + 1)
set_num(ws, rn, 4, FORMATS["integer"])
set_num(ws, rn, 8, FORMATS["integer"])
rn += 2

section_title(ws, rn, "次类覆盖小结（试点 12 词 vs 词表 8 个次类）", len(H4) + 1); rn += 1
ws.cell(row=rn, column=2, value="Levin次类")
ws.cell(row=rn, column=3, value="试点覆盖词")
ws.cell(row=rn, column=4, value="状态与建议")
style_header_row(ws, row_num=rn, col_start=2, col_end=4); rn += 1
SUGGEST = {"匍匐爬行类": "缺口：建议补 crawl（中频、方式纯型）或 scramble",
           "长途行进类": "缺口：建议补 hike 或 trek（隐喻引申丰富）",
           "运载工具类": "视 fly 次类归属而定；如无覆盖建议补 drive（使役用法丰富）",
           "滚动滑行类": "缺口：建议补 slide（物理/隐喻并存）"}
pilot_subs = defaultdict(list)
for p in pilot_sorted:
    pilot_subs[lex.get(p["verb"], ("—",))[0]].append(p["verb"])
for i, s in enumerate(subs):
    covered = pilot_subs.get(s, [])
    if covered:
        status = "已覆盖：" + "、".join(covered)
    else:
        status = SUGGEST.get(s, "缺口：建议补 1 个代表词")
    ws.cell(row=rn, column=2, value=s)
    ws.cell(row=rn, column=3, value="、".join(covered) if covered else "—")
    ws.cell(row=rn, column=4, value=status)
    style_data_row(ws, row_num=rn, col_start=2, col_end=4, row_index=i)
    if not covered:
        ws.cell(row=rn, column=4).fill = FILL_WARN
        ws.cell(row=rn, column=4).font = FONT_WARN
    rn += 1
ws.cell(row=rn + 1, column=2,
        value="注：试点 12 词由 1003 大纲 §4.1 标准选定（高频-中频-低频梯度、物理/隐喻并存、39→2 义位跨度、习语与使役覆盖）；"
              "若按琥珀色缺口建议补词，试点扩大为 13–14 词，§4.1 的选取理由需同步补充。").font = font_caption()
ws.column_dimensions["I"].width = 60
auto_fit_columns(ws, min_width=8, max_width=30, header_row=4, data_start_row=5)
auto_fit_row_heights(ws, header_row=4, data_start_row=5)

# ---------------------------------------------------------------- 保存
wb.properties.creator = "Z.ai"
OUT.parent.mkdir(parents=True, exist_ok=True)
wb.save(OUT)
print(f"saved: {OUT}")
print(f"rows={len(rows)}, fuzzy={sum(1 for r in rows if r['fuzzy'])}, "
      f"mismatch={sum(1 for r in rows if r['agree'] == '不一致')}, pilot={len(pilot)}")
