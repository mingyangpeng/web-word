"""
OALD10 义项提取器。

数据源：`docs/output-oald10en-for-senselist-1020.xlsx` —— OALD 第 10 版的逐义项导出。
一行的形态是「一个词条 + 一个词性 + 一个把全部义项打包成 Python 字面量的字符串」：

    headword='crawl'  pos='verb'  content="{'headword': 'crawl', 'pos': 'verb',
        'definitions': [{'definition': '...', 'examples': '\\n...\\n...'}, ...]}"

## 提取什么、扔掉什么

原始字段里混着两类东西：**义项内容**（要）和 **OALD 的标注机器**（不要，但不能丢）。
清洗规则只有一条原则 —— **粘在文本上的语法码剥下来单独存，绝不留在释义正文里**：

| 原始形态 | 处理 | 去向 |
|----------|------|------|
| `[intransitive]to move using your legs` | 剥掉方括号前缀 | `grammar` 字段 |
| 例句串 `"\\na\\nb\\n"` | 按行切分、去空行 | `examples` 列表 |
| 行首 `<+ adv./prep.> He ran home` | 剥掉尖括号前缀 | `example_patterns` |
| 例句里的 `(= pay by credit card)` | **保留** | 那是词典原文的解释性夹注，不是编码 |
| `group_tag: 'IDIOMS'` | 提升为 `sense_group` | `sense_group` 字段 |

「剥下来单独存」而不是「删掉」是有意的：`[transitive]` 决定这个义项能不能带宾语，
是研究者判断英汉对齐时必须看的证据。清洗的目标是让 `definition` 只剩可读英文，
不是让信息消失。

## 同形词与拼写变体

表里有三种「词不在表里」的情况，都必须处理，否则会静默少词：

1. **直接命中** —— `amble` 就是 `amble`（129 词）。
2. **同形异义** —— 词条名带编号：`row` → `row1`（划船）/ `row2`（争吵），
   `tear` → `tear1`（撕）/ `tear2`（流泪）。原表用 `link_to` 列指过来
   （`row` 行的 `link_to` 是 `row1_1`），所以能可靠地找到全部同形词。
3. **拼写变体** —— `whiz` 在表里拼作 `whizz`。

三者的义项**合并到同一个词目下**，但每条义项都保留它来自哪个编号词条（`headword`），
因为「row 的哪个义项是划船」这件事需要能回溯。

## 覆盖率的诚实说明

136 词里有 4 个在整张表里都查不到动词义项：`dodder`、`scutter`、`kayak`、`oar`。
这不是解析 bug —— 逐个复核过（`kayak`/`oar` 只有名词词条，另两个词条名都不存在）。
它们会以「0 义项」出现在导出清单里，而不是被悄悄跳过。
"""

import ast
import logging
import os
import re
from typing import Any, Dict, List, Tuple

from src.word_source import (  # noqa: E402
    ALIGNMENT_PARTIAL,
    PROTOTYPE_METAPHOR,
    PROTOTYPE_Y,
)

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OALD_XLSX = os.path.join(ROOT, "docs/output-oald10en-for-senselist-1020.xlsx")

SOURCE_NAME = "OALD10"

# 词条名末尾的编号（row1 / tear2）—— OALD 用它区分同形异义
_HOMOGRAPH_SUFFIX = re.compile(r"^(.+?)(\d+)$")
# 释义开头的语法码：[intransitive] / [transitive, often passive] …
_GRAMMAR_PREFIX = re.compile(r"^\s*\[([^\]]*)\]\s*")
# 例句行开头的句法模式：<+ adv./prep.> / <run something> …
_PATTERN_PREFIX = re.compile(r"^\s*<([^>]*)>\s*")


def _clean(value: Any) -> str:
    """去掉 Excel 里常见的全角空格与首尾空白。"""
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


def split_definition(raw: str) -> Tuple[str, str]:
    """
    把 `[intransitive]to move using your legs` 拆成 (grammar, definition)。

    只剥**开头**的一个方括号组：释义正文里出现的方括号是词典原文
    （如 `[singular]`、`[countable]` 之外还有编者按），不能一起吃掉。
    实测 665 条义项中，方括号出现在非开头的有 0 条，所以这条规则是安全的；
    但规则仍然只认行首，免得将来数据变了会静默吃掉正文。
    """
    text = _clean(raw)
    m = _GRAMMAR_PREFIX.match(text)
    if not m:
        return "", text
    return _clean(m.group(1)), text[m.end():].strip()


def split_examples(raw: str) -> Tuple[List[str], List[str]]:
    """
    把例句串拆成 (例句列表, 句法模式列表)，两者**按下标一一对应**。

    OALD 把同一语法组下的例句连续排列，只有第一句带 `<...>` 前缀：

        <+ adv./prep.> The dogs ran off as soon as we appeared.
        He ran home in tears to his mother.

    第二句沿用第一句的模式，但**它的模式字段是空的** —— 这不是缺失，
    而是继承。所以模式按「最近一次出现的 `<...>`」向下传播，
    这样每个例句都拿到自己实际适用的句法模式。

    实测 1331 行例句里，只有 pattern 没有正文的行 0 条、一行含多个 `<>` 的 0 条，
    所以「前缀 + 正文」的简单切分足够；仍然对空正文做了防御。
    """
    text = _clean(raw)
    if not text:
        return [], []

    examples: List[str] = []
    patterns: List[str] = []
    current = ""
    for line in text.split("\n"):
        line = _clean(line)
        if not line:
            continue
        m = _PATTERN_PREFIX.match(line)
        if m:
            current = _clean(m.group(1))
            body = line[m.end():].strip()
        else:
            body = line
        if not body:
            continue
        examples.append(body)
        patterns.append(current)
    return examples, patterns


def parse_row_content(content: Any) -> List[Dict[str, Any]]:
    """
    解析一行 `definition_content`，返回清洗后的义项列表。

    原始串是 Python 字面量（单引号 + `\\n` 转义），所以用 `ast.literal_eval`
    而不是 `json.loads` —— 实测 216601 行全部可解析，0 失败。
    """
    if not content:
        return []
    try:
        obj = ast.literal_eval(str(content))
    except (ValueError, SyntaxError) as e:
        logger.warning(f"OALD 行无法解析，已跳过: {e}")
        return []
    if not isinstance(obj, dict):
        return []

    out: List[Dict[str, Any]] = []
    for raw in obj.get("definitions") or []:
        if not isinstance(raw, dict):
            continue
        grammar, definition = split_definition(raw.get("definition") or "")
        if not definition:
            continue
        examples, patterns = split_examples(raw.get("examples") or "")
        group = _clean(raw.get("group_tag"))
        out.append({
            "sense_group": group or None,
            "grammar": grammar or None,
            # 键名就是 `word_senses.en_ndef` —— 清洗产物说话要跟落地表一个词汇表。
            # 曾经这里叫 `definition`，而 replace_word_senses 读的是 `en_ndef`，
            # 结果 665 条义项的释义**全部静默丢失**（行数对得上，日志看不出异常，
            # 只有打开卡片才发现每条都是空的）。测试里钉住了这个键名。
            "en_ndef": definition,
            "examples": examples,
            "example_patterns": patterns,
            # 习语义项（group_tag == IDIOMS）的「释义」常是整句习语的解释，
            # 不是词本身的位移义。**保留但标记**：是否排除该由研究者定，
            # 程序替他们决定就等于隐藏了数据。
            "is_idiom": 1 if group.upper() == "IDIOMS" else 0,
            "source": SOURCE_NAME,
        })
    return out


def load_oald_verb_index(path: str = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    扫描整张 OALD 表，建立 `小写词条名 -> [清洗后的义项]` 索引（只收 `pos='verb'`）。

    同时记录 `link_to` 别名表：形如 `row` → `{row1, row2}`，
    用于把同形异义词条归并到同一个词目下。

    Returns:
        {"senses": {词条名: [义项]}, "aliases": {裸词: [编号词条]}}
    """
    path = path or OALD_XLSX
    if not os.path.exists(path):
        logger.warning(f"OALD 表不存在，义项提取跳过: {path}")
        return {"senses": {}, "aliases": {}}

    import openpyxl  # 延迟导入：只有这个脚本需要，应用运行时不装也能跑

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]

    senses: Dict[str, List[Dict[str, Any]]] = {}
    aliases: Dict[str, set] = {}
    rows = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 5:
            continue
        link_to, headword, pos, content = row[1], row[2], row[3], row[4]
        if not headword:
            continue
        rows += 1
        name = _clean(headword).lower()

        if link_to:
            # link_to 形如 `row1_1`（词条名 + 义项序号），去掉末尾 `_N` 就是词条名
            target = re.sub(r"_\d+$", "", _clean(link_to).lower())
            if target:
                aliases.setdefault(name, set()).add(target)

        if _clean(pos).lower() != "verb":
            continue
        parsed = parse_row_content(content)
        if parsed:
            senses.setdefault(name, []).extend(parsed)

    wb.close()
    logger.info(f"OALD 表扫描完成：{rows} 行，动词词条 {len(senses)} 个")
    return {"senses": senses, "aliases": aliases}


def resolve_headwords(verb: str, index: Dict[str, Any]) -> Tuple[List[str], str]:
    """
    找出该词在 OALD 表里对应的全部词条名，以及通过哪种方式找到的。

    返回 (词条名列表, 解析方式)，解析方式是 `direct` / `alias` / `homograph` / `missing`。
    把过程暴露出来是为了让覆盖率报表能区分「表里根本没有这个词」和「靠编号猜出来的」
    —— 后者是更弱的证据。
    """
    senses = index.get("senses") or {}
    aliases = index.get("aliases") or {}
    verb = verb.lower()

    if verb in senses:
        return [verb], "direct"

    # 同形异义：link_to 指向的编号词条
    via_alias = sorted(n for n in aliases.get(verb, set()) if n in senses)
    if via_alias:
        return via_alias, "alias"

    # 兜底：编号词条名去掉编号后与裸词相同（link_to 列缺失时仍能取到）
    guess = sorted(k for k in senses if _HOMOGRAPH_SUFFIX.sub(r"\1", k) == verb)
    if guess:
        return guess, "homograph"

    return [], "missing"


def senses_for(verb: str, index: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """
    取某个词的 OALD 义项（已归并同形异义 / 拼写变体）。

    Returns:
        (义项列表, 解析方式, 用到的词条名)。
        每条义项额外带 `headword` 字段，指出它来自哪个编号词条 —— 同形异义词
        （row1 划船 / row2 争吵）合并后仍要能回溯。
    """
    names, how = resolve_headwords(verb, index)
    senses = index.get("senses") or {}
    out: List[Dict[str, Any]] = []
    for name in names:
        for s in senses.get(name, []):
            item = dict(s)
            item["headword"] = name
            out.append(item)
    return out, how, names


def audit_coverage(verbs: List[str], index: Dict[str, Any]) -> Dict[str, Any]:
    """生成覆盖率报表，供灌库日志与导出清单使用。"""
    from collections import Counter

    per: Dict[str, int] = {}
    how_ct = Counter()
    missing: List[str] = []
    total = 0
    for v in verbs:
        ss, how, _ = senses_for(v, index)
        per[v] = len(ss)
        how_ct[how] += 1
        total += len(ss)
        if not ss:
            missing.append(v)

    all_senses = [s for v in verbs for s in senses_for(v, index)[0]]
    idioms = sum(1 for s in all_senses if s.get("is_idiom"))
    with_ex = sum(1 for s in all_senses if s.get("examples"))
    with_grammar = sum(1 for s in all_senses if s.get("grammar"))

    return {
        "total_verbs": len(verbs),
        "total_senses": total,
        "avg_senses": round(total / len(verbs), 2) if verbs else 0.0,
        "by_resolution": dict(how_ct),
        "missing_verbs": missing,
        "idiom_senses": idioms,
        "senses_with_examples": with_ex,
        "senses_with_grammar": with_grammar,
        "per_verb": per,
    }


def annotate_oald_senses(senses: List[Dict[str, Any]],
                         levin_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    给 OALD 义项打上与 dictionary.db 义位**同一套**的标注标签。

    两套义项共用标注字段，是为了让它们在同一张表里可比较 —— 否则「OALD 的这条
    算不算原型义」只能靠读英文自己判断，而字段空着会让人以为「没标注」而不是
    「另一个来源不用标注」。

    标注规则与 ``annotate_senses`` 保持一致，只有一处不同：**首个非习语义项**
    记为原型义。OALD 把习语（IDIOMS 组）排在最后，但 `run` 这类词的义项顺序未必
    把最典型义放第一，所以判据是「第一条且不是习语」，比「第 0 条」更贴近意图。

    ``needs_review`` 一律置 1：文档第 45 段要求全部标签由研究者人工复核。
    """
    # 原型义只能有一个。dictionary.db 的义位优先级更高（SOURCE_RANK 里它排第一），
    # 它已经标过 Y 的词，OALD 这一侧就全部记 拓展 —— 否则同一个词会出现两个 Y，
    # 「哪个是原型义」这个字段就自相矛盾了。
    has_other_source = bool(levin_row.get("_has_dict_senses"))
    proto_at = None if has_other_source else next(
        (i for i, s in enumerate(senses) if not s.get("is_idiom")), 0
    )

    out = []
    for i, sense in enumerate(senses):
        item = dict(sense)
        item["prototype_level"] = PROTOTYPE_Y if i == proto_at else PROTOTYPE_METAPHOR
        item["image_schema"] = levin_row.get("image_schema") or None
        item["alignment"] = levin_row.get("alignment_hint") or ALIGNMENT_PARTIAL
        item["cn_syntax"] = levin_row.get("cn_syntax_hint") or None
        item["translation_strategy"] = levin_row.get("translation_hint") or None
        item["prototype_is_first"] = 1 if i == proto_at else 0
        item["needs_review"] = 1
        out.append(item)
    return out
