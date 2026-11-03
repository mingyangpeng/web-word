#!/usr/bin/env python3
"""把 ModernChineseDict 的 mdx 文本结构化为《现汉7》词条 JSON。

数据源：data/ModernChineseDict/mdx/dict.mdx.txt —— mdict 导出的纯文本，
格式为「词条名行 + HTML 正文行 + </> 分隔行」循环（约 7.5 万词条）。

正文 HTML 的 class 语义（现代汉语词典.css）：
  .py    拼音（可能多个，多音字词条每个读音一条 mdx 记录）
  .lya   词性标签（名/动/形/副/量/拟声/连/代/介/助/叹/数）
  .lyb   语域标注（书=书面语 / 方=方言 / 口=口语 / 古=古语 / 非推荐词形）
  .lyc   比喻用法标记（◇火车在飞跑 的 ◇）
  .num   义项号（①②③…，无 .num 的词条是单义项）
  .er    儿化后缀（～儿）
  .sma   附注（另见 / ［英 …缩写］ / ［书］ 等）
  .usage 用法说明块（少数词条尾部）

结构化输出（data/zh_dict_senses.json）：
  [{lemma, pinyin, pos, senses: [{no, label, register, is_metaphor,
     definition, examples, note}], cross_ref, raw_html}, ...]

义项切分：按 <span class="num">①</span>…<br> 切；无义项号的词条整体为一个
义项（no=None）。例句切分：释义与例句用「：」分隔，例句之间用「｜」「丨」分隔；
「～」还原为词目本身。比喻例（lyc 标记后的例句）单独标 is_metaphor=True，
与甄别表「◇隐喻例不计入判定」的口径一致。

用法：
    python3 scripts/parse_modern_chinese_dict.py            # 全量解析
    python3 scripts/parse_modern_chinese_dict.py --limit 100  # 只解析前 100 条（调试）
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MDX_TXT = ROOT / "data" / "ModernChineseDict" / "mdx" / "dict.mdx.txt"
OUT_JSON = ROOT / "data" / "zh_dict_senses.json"

# mdx 文本里词条正文是单行 HTML，</> 是记录分隔符。
# ENTRY_RE 捕获 <main>…</main> 之间（含 <main> 标签本身，便于后续清洗时
# 统一剥掉外层标签，避免 <main> 残留干扰义项切分）。
# 注意：link 标签有两种形态（href 在前 / 在后），都不能进捕获组。
ENTRY_RE = re.compile(r"<main>(.*?)</main>")
# 同词目同读音的多条记录（㧟¹/㧟² 上标区分的同形词）：上标数字并入词目，
# 保持 (lemma, pinyin) 唯一 —— 㧟¹ 与 㧟² 是两个词目而非重复记录。
SUPERSCRIPTS = "¹²³⁴⁵⁶⁷⁸⁹"
TAG_RE = re.compile(r"<[^>]+>")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
# 语域标注 → 甄别表口径（驰突=书面/文言、小跑=口语、跑③=方言）
REGISTER_MAP = {"书": "书面", "方": "方言", "口": "口语", "古": "文言"}


def _text(fragment: str) -> str:
    """HTML 片段 → 纯文本（去标签、解实体、压空白）。"""
    txt = TAG_RE.sub("", fragment)
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def _split_examples(body: str, lemma: str) -> tuple:
    """释义正文 → (释义, [例句…])。

    「：」前是释义、后是例句；例句间用全角竖线分隔；「～」还原为词目。
    无「：」时整段都是释义（如「逃走」）。
    """
    definition, _, ex_part = body.partition("：")
    examples = []
    if ex_part:
        for ex in re.split(r"[｜丨]", ex_part):
            ex = ex.strip()
            if ex:
                examples.append(ex.replace("～", lemma))
    return definition.strip(), examples


def parse_entry(lemma: str, html_body: str) -> dict:
    """一条 mdx 记录（一个读音的词条）→ 结构化 dict。"""
    # 拼音（.py 块）
    m = re.search(r'<div class="py">([^<]*)</div>', html_body)
    pinyin = m.group(1).strip() if m else None

    # 词性（.lya 块；个别词条缺失）
    m = re.search(r'<span class="lya">([^<]*)</span>', html_body)
    pos = m.group(1).strip() if m else None

    # 儿化标注：（～儿）出现在词性之前
    erhua = '<span class="er">' in html_body

    # 另见/附注（.sma 块，可能多条）
    cross_refs = [t for t in (
        _text(x) for x in re.findall(r'<span class="sma">(.*?)</span>', html_body))
        if t.startswith("另见")]

    # 去掉头部（title/metadata/词性/儿化）与尾部（sma/usage），留义项正文。
    # metadata 是嵌套 div（<div class="metadata"><div class="py">…</div></div>），
    # 非贪婪 .*?</div> 会停在**内层** </div>，把外层 </div> 残留给正文 ——
    # B超 词条的 ① 因此不在段首、义项切分失效。这里显式吃掉两层闭合。
    body = re.sub(r"<span class=\"title\">.*?</span>", "", html_body, flags=re.S)
    body = re.sub(r'<div class="metadata">.*?</div></div>', "", body, flags=re.S)
    body = re.sub(r"<div[^>]*>.*?</div>", "", body, flags=re.S)  # 兜底：残余 div
    body = re.sub(r"</?main>", "", body)
    body = re.sub(r"<span class=\"lya\">.*?</span>", "", body)
    body = re.sub(r"<span class=\"sma\">.*?</span>", "", body)
    body = re.sub(r"<div class=\"usage\">.*?</div>", "", body, flags=re.S)
    body = re.sub(r"^（～<span class=\"er\">儿</span>）", "", body.strip())

    # 按 <br> 分段，再按义项号聚合。义项号有两种形态：
    #   a) <span class="num">①</span>（主流，14786 处）
    #   b) 裸文本 ①②③（OCR 残留，如 B超）—— 同样切分，但保留原文
    segments = [s for s in re.split(r"<br\s*/?>", body) if _text(s)]
    senses = []
    current = None  # {no, register, parts: [(text, is_metaphor)]}
    for seg in segments:
        m = re.search(r'<span class="num">([①-⑮])</span>\s*(.*)', seg, flags=re.S)
        if not m:
            # 段中裸义项号（B超形态：整段是「①…。②…。」连排，无 <br> 无 .num）
            m2 = re.match(r"(.*?)([①-⑮])(.*)", seg, flags=re.S)
            if m2 and _text(m2.group(1)):
                # 前半是上一义项的延续，② 起开新义项 —— 逐个拆
                if current is None:
                    current = {"no": None, "register": None, "parts": [], "raw": []}
                current["raw"].append(m2.group(1))
                senses.append(current)
                current = {"no": m2.group(2), "register": None,
                           "parts": [], "raw": [m2.group(3)]}
                rest = m2.group(3)
                while True:
                    m3 = re.match(r"(.*?)([②-⑮])(.*)", rest, flags=re.S)
                    if not m3 or not _text(m3.group(1)):
                        break
                    current["raw"][-1] = m3.group(1)
                    senses.append(current)
                    current = {"no": m3.group(2), "register": None,
                               "parts": [], "raw": [m3.group(3)]}
                    rest = m3.group(3)
                continue
            if m2 and not _text(m2.group(1)):
                # 段首就是裸义项号（①在段首）
                m = re.match(r"\s*([①-⑮])\s*(.*)", seg, flags=re.S)
        if m:
            if current:
                senses.append(current)
            current = {"no": m.group(1), "register": None,
                       "parts": [], "raw": [m.group(2)]}
            # 段内后续的裸 ②③④（B超形态：①…。②…。连排在同一段）
            rest = m.group(2)
            while True:
                m3 = re.match(r"(.*?)([②-⑮])(.*)", rest, flags=re.S)
                if not m3 or not _text(m3.group(1)):
                    break
                current["raw"][-1] = m3.group(1)
                senses.append(current)
                current = {"no": m3.group(2), "register": None,
                           "parts": [], "raw": [m3.group(3)]}
                rest = m3.group(3)
        else:
            if current is None:
                current = {"no": None, "register": None, "parts": [], "raw": [seg]}
            else:
                current["raw"].append(seg)

    if current:
        senses.append(current)

    out_senses = []
    for s in senses:
        # 语域标注（.lyb）在义项开头
        register = None
        m = re.search(r'<span class="lyb">([^<]*)</span>', "".join(s["raw"]))
        if m:
            tag = m.group(1).strip()
            register = REGISTER_MAP.get(tag, tag)
        # 比喻标记（.lyc）：其后的例句是隐喻例
        is_metaphor = 'class="lyc"' in "".join(s["raw"])
        # 义项正文：去掉 num/lyb 标签后取纯文本
        seg_text = "".join(s["raw"])
        seg_text = re.sub(r'<span class="num">[^<]*</span>', "", seg_text)
        seg_text = re.sub(r'<span class="lyb">[^<]*</span>', "", seg_text)
        seg_text = re.sub(r'<span class="lyc">[^<]*</span>', "", seg_text)
        definition, examples = _split_examples(_text(seg_text), lemma)
        out_senses.append({
            "no": s["no"],
            "register": register,
            "is_metaphor": is_metaphor,
            "definition": definition,
            "examples": examples,
        })

    return {
        "lemma": lemma,
        "pinyin": pinyin,
        "pos": pos,
        "erhua": erhua,
        "senses": out_senses,
        "cross_refs": cross_refs,
        "raw_html": html_body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="结构化《现汉7》mdx 文本")
    parser.add_argument("--limit", type=int, default=0, help="只解析前 N 条（调试）")
    parser.add_argument("-o", "--output", default=str(OUT_JSON))
    args = parser.parse_args()

    if not MDX_TXT.exists():
        print(f"源文件不存在: {MDX_TXT}")
        return 1

    entries = []
    lemma = None
    skipped = 0
    with open(MDX_TXT, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line == "</>":
                lemma = None
                continue
            if lemma is None:
                lemma = line.strip()  # 词条名行
                continue
            if line.startswith("@@@LINK="):
                # 交叉引用记录（@@@LINK=㧟）：指向目标词条，无正文，跳过
                skipped += 1
                lemma = None
                continue
            m = ENTRY_RE.search(line)
            if not m:
                skipped += 1
                continue  # 少数词条的正文可能跨行或格式特殊，跳过并计数
            # 同形词上标：正文 title 里的 㧟¹/㧟² 与词条名行的 㧟 不同 —— 以
            # title 为准并入词目，保证 (lemma, pinyin) 唯一。
            # title 可能含内嵌标签（坎<span class="er">儿</span>¹），且内嵌
            # span 自己也带 </span> —— 用「到 metadata div 前」的窗口取 title
            body = m.group(1)
            tm = re.match(r'\s*(.*?)<div class="metadata">', body, flags=re.S)
            title_html = tm.group(1) if tm else None
            entry_lemma = lemma
            if title_html is not None:
                title_txt = _text(title_html)
                if title_txt and title_txt != lemma:
                    if any(c in SUPERSCRIPTS for c in title_txt) and \
                            title_txt.rstrip(SUPERSCRIPTS) == lemma:
                        entry_lemma = title_txt  # 保留上标：㧟¹ / 㧟² / 坎儿¹
                    else:
                        skipped += 1
                        continue  # title 与词目行不一致且非上标形态：不可信，跳过
            entries.append(parse_entry(entry_lemma, body))
            if args.limit and len(entries) >= args.limit:
                break

    # (lemma, pinyin) 唯一性兜底：仍重复时后者并入前者（保留首个）
    seen = {}
    deduped = []
    for e in entries:
        key = (e["lemma"], e.get("pinyin"))
        if key in seen:
            seen[key]["senses"].extend(e["senses"])
            skipped += 1
        else:
            seen[key] = e
            deduped.append(e)
    entries = deduped

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)

    n_senses = sum(len(e["senses"]) for e in entries)
    n_verbs = sum(1 for e in entries if e["pos"] == "动")
    print(f"解析 {len(entries)} 个词条（读音条目），共 {n_senses} 个义项，"
          f"其中动词词条 {n_verbs} 个；跳过/合并 {skipped} 条 → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
