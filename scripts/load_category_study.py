#!/usr/bin/env python3
"""把 d1/ 跑范畴两个 xlsx 灌入 MySQL 的范畴深挖 8 表（categories / cs_*）。

数据链：
  d1/跑范畴英汉义位甄别表.xlsx          阶段1 甄别（词条/义位/判定/标注）
  d1/跑范畴英汉义位编码与独立聚类表.xlsx  阶段2 编码矩阵 + 独立聚类 + 跨语言对齐

口径：本表为程序预编码（单标注演示），正式流程需双标注 IAA 后重跑 ——
cluster_runs.version 记为「预编码」，将来 IAA 版本另起 run 共存。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/load_category_study.py            # 全量替换
    MYSQL_HOST=127.0.0.1 python3 scripts/load_category_study.py --if-empty  # 仅空表时灌入
    ... --category RUN   # 指定范畴代号（默认 RUN，与 d1 数据对应）
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook  # noqa: E402

from src import category_study, mysql_db  # noqa: E402

D1_DIR = ROOT / "data" / "d1"
SCREENING_XLSX = D1_DIR / "跑范畴英汉义位甄别表.xlsx"
CODING_XLSX = D1_DIR / "跑范畴英汉义位编码与独立聚类表.xlsx"

# 甄别表说明区（尾部合并行）里的研究定位，存进 categories.notes
CATEGORY_NOTES = (
    "【跑】范畴英汉纵向深挖：上位范畴 → 下位成员（英 23 词 32 义位 / "
    "汉 24 词条 25 义位条目）→ 范畴化释义。与全词库横向聚类（290 义位/16 类）"
    "互补。证据链：OALD10 + enTenTen21 Word Sketch /《现汉7》+ BCC（待补）。"
    "编码为程序预编码，正式流程需双标注 IAA 后重跑。"
)

# 编码矩阵特征列（与 category_study.FEATURE_COLUMNS 一致；从表头动态读取亦可，
# 但固定顺序更稳 —— 表头顺序即矩阵列序）
FEATURE_CODES = category_study.FEATURE_CODES

_LEVIN_EXTRA = {"sprint", "pound", "stampede", "career"}  # 补录 4 词，不在 Levin 51 类

# 编码矩阵的词目与甄别清单的词目存在个别形态差（tear1 vs tear），统一映射
_LEMMA_ALIASES = {"tear1": "tear"}


def _cell(v) -> str:
    """单元格转干净字符串：None → ''，去首尾空白。"""
    return str(v).strip() if v is not None else ""


def _split_members(text: str):
    """「run·跑完里程义 / sprint·短距冲刺义」→ [(lemma, sense_label), ...]。

    成员格式为「词目·义位标签」，斜杠分隔。汉语侧词目带义项号（跑①），
    与甄别清单的 (lemma, sense_no) 对应关系由 _zh_sense_key 处理。
    """
    members = []
    for part in text.split("/"):
        part = part.strip()
        if not part:
            continue
        lemma, _, label = part.partition("·")
        if not label:
            continue
        members.append((lemma.strip(), label.strip()))
    return members


def _parse_profile(text: str):
    """「P2=1.00；P3=1.00；…」→ {'P2': 1.0, ...}（簇特征画像）。"""
    profile = {}
    for m in re.finditer(r"([PMCA]\d[abcd]?)=([0-9.]+)", text or ""):
        profile[m.group(1)] = float(m.group(2))
    return profile


def _zh_sense_key(lemma_with_no: str):
    """汉语编码矩阵的词条「跑①」「驰驱①」→ (lemma, sense_no)。

    甄别清单里单义项双字词的义项号是「—」，矩阵里不带号（如「奔跑」）——
    返回 sense_no=None 表示「该词条唯一义位」，匹配时回退。
    """
    m = re.match(r"^(.+?)([①②③④⑤⑥])$", lemma_with_no.strip())
    if m:
        return m.group(1), m.group(2)
    return lemma_with_no.strip(), None


def read_screening() -> dict:
    """甄别表 → {en: [sense...], zh: [sense...]}，义位行含全部甄别字段。"""
    wb = load_workbook(SCREENING_XLSX, read_only=True)

    en_senses = []
    ws = wb["英语目标义位清单"]
    for r in ws.iter_rows(min_row=5, values_only=True):
        if _cell(r[1]) in ("", "合计") or not _cell(r[2]):
            continue
        en_senses.append({
            "language": "en",
            "lemma": _cell(r[2]),
            "sense_no": _cell(r[3]),
            "sense_label": _cell(r[4]),
            "definition": _cell(r[5]),
            "example": _cell(r[6]),
            "subject_type": _cell(r[7]),
            "register": _cell(r[8]),
            "tag": _cell(r[9]),
            "status": "目标",  # 英语侧无三态判定，进清单即目标义位
            "remark": _cell(r[10]),
        })

    zh_senses = []
    ws = wb["汉语目标义位清单"]
    for r in ws.iter_rows(min_row=5, values_only=True):
        if _cell(r[1]) in ("", "合计") or not _cell(r[2]):
            continue
        zh_senses.append({
            "language": "zh",
            "lemma": _cell(r[2]),
            "sense_no": _cell(r[3]),
            "sense_label": _cell(r[4]),
            "definition": _cell(r[5]),
            "example": _cell(r[6]),
            "status": _cell(r[7]) or "保留",
            "subject_type": _cell(r[8]),
            "register": _cell(r[9]),
            "tag": _cell(r[10]),
            "remark": _cell(r[11]),
        })
    wb.close()
    return {"en": en_senses, "zh": zh_senses}


def read_coding(screening: dict) -> dict:
    """编码矩阵 → 每个义位的 features + feature_remarks（按 词目+义位标签 匹配）。

    匹配键：英语 (lemma, sense_label)；汉语 (lemma去义项号, sense_label)，
    汉语矩阵词条带 ①② 而甄别清单拆成 lemma+sense_no 两列。
    """
    # 索引：language → (lemma, label) → sense dict（往里填 features）
    index = {"en": {}, "zh": {}}
    for lang, senses in screening.items():
        for se in senses:
            key = (se["lemma"], se["sense_label"])
            index[lang][key] = se
            if lang == "zh":
                # 矩阵里「跑①」→ 甄别清单 (跑, ①)；也登记无号形态（奔跑 → 奔跑）
                lemma_no, _no = _zh_sense_key(se["lemma"])
                index["zh"].setdefault((lemma_no, se["sense_label"]), se)

    wb = load_workbook(CODING_XLSX, read_only=True)

    def _fill(sheet_name: str, language: str, lemma_col: int, remark_col: int):
        ws = wb[sheet_name]
        for r in ws.iter_rows(min_row=5, values_only=True):
            lemma_raw = _cell(r[lemma_col])
            label = _cell(r[3])
            if not lemma_raw or not label or lemma_raw in ("序号",):
                continue
            lemma = lemma_raw
            if language == "zh":
                lemma, _ = _zh_sense_key(lemma_raw)
            else:
                lemma = _LEMMA_ALIASES.get(lemma, lemma)
            se = index[language].get((lemma, label))
            if se is None:
                print(f"⚠ 编码矩阵行在甄别清单找不到: {language} {lemma_raw}·{label}，跳过")
                continue
            features, remarks = {}, {}
            for i, code in enumerate(FEATURE_CODES):
                col = 4 + i  # 特征列从 E 列（idx 4）起，与表头 P1..A3 对齐
                raw = _cell(r[col])
                if raw in ("", "—"):
                    continue
                try:
                    features[code] = int(float(raw))
                except ValueError:
                    print(f"⚠ 非法编码值 {code}={raw!r} ({lemma_raw}·{label})，跳过")
            note = _cell(r[remark_col])
            if note:
                # 矩阵备注是整行一条，挂在行级 remark（甄别表 remark 优先保留原值）
                se.setdefault("coding_remark", note)
            se["features"] = features

    # 英语矩阵：词目 col2，备注 col22；汉语矩阵：词条 col2，备注 col24
    _fill("英语编码矩阵", "en", 2, 22)
    _fill("汉语编码矩阵", "zh", 2, 24)

    # ---- 独立聚类 ----
    runs = []
    for sheet_name, language in (("英语独立聚类", "en"), ("汉语独立聚类", "zh")):
        ws = wb[sheet_name]
        all_rows = list(ws.iter_rows(values_only=True))
        # 标题在第 2 行（idx 1）：「英语侧独立聚类（Gower+average，k=5，cophenetic 0.825）」
        title = ""
        for r in all_rows[:3]:
            for v in r:
                if v is not None and "聚类" in str(v):
                    title = str(v)
                    break
            if title:
                break
        m = re.search(r"cophenetic\s*([0-9.]+)", title)
        cophenetic = float(m.group(1)) if m else None
        clusters, notes = [], []
        for r in all_rows[3:]:
            no_cell = _cell(r[1])
            if no_cell == "簇号":
                continue
            if no_cell and re.fullmatch(r"\d+", no_cell):
                members = []
                for lemma_label in _split_members(_cell(r[5])):
                    members.append(lemma_label)  # (lemma, label)；汉语 lemma 可能带①
                clusters.append({
                    "cluster_no": int(no_cell),
                    "name": _cell(r[2]),
                    "size": int(float(_cell(r[3]) or 0)),
                    "profile": _parse_profile(_cell(r[4])),
                    "note": None,
                    "members": members,
                })
            else:
                # 解读区（簇表下方的类型学观察文本），收进 notes 后按「簇N」前缀归属
                note = no_cell or _cell(r[2])
                if note and clusters:
                    notes.append(note)
        # 解读区行（簇表下方无簇号的文本行）挂到对应簇：按「簇N 」前缀归属
        for note in notes:
            m = re.match(r"^簇(\d+)", note)
            if m:
                no = int(m.group(1))
                for cl in clusters:
                    if cl["cluster_no"] == no and cl["note"] is None:
                        cl["note"] = note
                        break
        runs.append({
            "language": language,
            "algorithm": "Gower+average",
            "params": {"k": len(clusters)},
            "cophenetic": cophenetic,
            "version": "预编码",
            "clusters": clusters,
        })

    # ---- 跨语言对齐 ----
    alignments = []
    ws = wb["跨语言簇对齐"]
    for r in ws.iter_rows(min_row=4, values_only=True):
        en_no = _cell(r[1])  # 「英簇1」
        if not en_no.startswith("英簇"):
            continue
        m = re.match(r"^英簇(\d+)", en_no)
        m2 = re.match(r"^汉簇(\d+)", _cell(r[4]))
        if not m or not m2:
            continue
        dist_raw = _cell(r[7])
        try:
            distance = float(dist_raw)
        except ValueError:
            distance = None
        alignments.append({
            "en_cluster_no": int(m.group(1)),
            "zh_cluster_no": int(m2.group(1)),
            "gower_distance": distance,
            "verdict": _cell(r[8]),
            "explanation": _cell(r[9]),
        })
    wb.close()
    return {"runs": runs, "alignments": alignments}


def build_payload(category_code: str) -> dict:
    """组装 replace_category_study 的 payload（甄别 + 编码 + 聚类 + 对齐）。"""
    screening = read_screening()
    coding = read_coding(screening)

    # ---- 词条（从两侧义位反推，保持与清单一致的词目集合）----
    lexemes = []
    seen = set()
    for lang, senses in screening.items():
        for se in senses:
            key = (lang, se["lemma"])
            if key in seen:
                continue
            seen.add(key)
            lexemes.append({
                "language": lang,
                "lemma": se["lemma"],
                "source_dict": "OALD10" if lang == "en" else "现汉7",
                "in_levin": 0 if (lang == "en" and se["lemma"] in _LEVIN_EXTRA) else 1,
            })

    # ---- 义位（features 已由 read_coding 填入；feature_remarks 用矩阵行备注）----
    senses = []
    for lang in ("en", "zh"):
        for se in screening[lang]:
            remark = se.get("remark") or se.get("coding_remark")
            senses.append({
                "language": lang,
                "lemma": se["lemma"],
                "sense_no": se["sense_no"],
                "sense_label": se["sense_label"],
                "definition": se.get("definition") or None,
                "example": se.get("example") or None,
                "subject_type": se.get("subject_type") or None,
                "register": se.get("register") or None,
                "tag": se.get("tag") or None,
                "status": se.get("status", "保留"),
                "remark": remark or None,
                "features": se.get("features", {}),
                "feature_remarks": {},
            })

    # ---- 簇成员键修正：汉语矩阵成员「跑①·逃走义」的 lemma 带 ①，
    #      甄别清单是 (跑, ②, 逃走义)。把 (lemma, label) 解析成
    #      (lemma, sense_no, label) 三元组供 replace_category_study 匹配。----
    zh_by_label = {}
    for se in screening["zh"]:
        zh_by_label[(se["lemma"], se["sense_label"])] = se
        lemma_no, _ = _zh_sense_key(se["lemma"])
        zh_by_label.setdefault((lemma_no, se["sense_label"]), se)

    for run in coding["runs"]:
        for cl in run["clusters"]:
            fixed = []
            for lemma, label in cl["members"]:
                if run["language"] == "zh":
                    base_lemma, sense_no = _zh_sense_key(lemma)
                    se = zh_by_label.get((base_lemma, label))
                    if se is None:
                        print(f"⚠ 汉簇成员找不到义位: {lemma}·{label}，跳过")
                        continue
                    fixed.append((se["lemma"], se["sense_no"], label))
                else:
                    fixed.append((lemma, "", label))  # 英语 sense_no 由标签匹配回填
            cl["members"] = fixed

    # 英语成员的 sense_no：编码矩阵不带义项号，用 (lemma, label) 从甄别清单回填
    # （tear1 之类的矩阵词目形态先归一到甄别清单词目）
    en_by_label = {(se["lemma"], se["sense_label"]): se for se in screening["en"]}
    for run in coding["runs"]:
        if run["language"] != "en":
            continue
        for cl in run["clusters"]:
            fixed = []
            for lemma, _, label in cl["members"]:
                lemma = _LEMMA_ALIASES.get(lemma, lemma)
                se = en_by_label.get((lemma, label))
                if se is None:
                    print(f"⚠ 英簇成员找不到义位: {lemma}·{label}，跳过")
                    continue
                fixed.append((lemma, se["sense_no"], label))
            cl["members"] = fixed

    return {
        "category": {
            "code": category_code,
            "name_cn": "跑",
            "name_en": "Run",
            "status": "试点",
            "notes": CATEGORY_NOTES,
        },
        "lexemes": lexemes,
        "senses": senses,
        "cluster_runs": coding["runs"],
        "alignments": coding["alignments"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入范畴深挖数据（跑范畴 d1）")
    parser.add_argument("--if-empty", action="store_true", help="仅当无范畴数据时写入")
    parser.add_argument("--category", default="RUN", help="范畴代号（默认 RUN）")
    args = parser.parse_args()

    for xlsx in (SCREENING_XLSX, CODING_XLSX):
        if not xlsx.exists():
            print(f"源文件不存在: {xlsx}")
            return 1

    if args.if_empty and category_study.category_study_ready(args.category):
        print(f"范畴 {args.category} 已有数据，跳过（--if-empty）。")
        return 0

    payload = build_payload(args.category)
    n_senses = len(payload["senses"])
    n_runs = len(payload["cluster_runs"])
    print(f"解析完成：词条 {len(payload['lexemes'])}，义位 {n_senses}，"
          f"聚类运行 {n_runs}，对齐行 {len(payload['alignments'])}")

    if not mysql_db.init_database():
        print("数据库初始化失败。")
        return 1

    counts = category_study.replace_category_study(payload)
    print(f"已灌入范畴 {args.category}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
