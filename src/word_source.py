"""
词表数据源解析器。

本模块把三个来源读成统一结构，供 `scripts/load_word_library.py` 灌库：

| 来源 | 内容 | 地位 |
|------|------|------|
| `docs/Levin移动动词候选词筛选表.xlsx` | 171 个通过筛选的自移移动动词 + 三主范畴/十二次类 + 判断理由 | **词目层面的分类权威** |
| `data/dictionary.db` | 每个动词逐义位的 Ch-Def / En-Def / 例句 / 近义反义词 | **释义正确性的首选来源** |
| `data/oxford_cache.json` | 英文释义缓存（联网抓取结果的落盘） | 补充来源，dictionary.db 未收录时使用 |

## 为什么「释义以 dictionary.db 为首选」

`docs/义项判定标准.docx` 要求「所有判定结果，必须可回溯到 OALD 释义、例句原文，备注栏留存依据」。
`dictionary.db` 是 OALD 的本地结构化数据（`Ch-Def` 是已审校的中文释义，带例句、近义词、
反义词），它天然带**原文可回溯**的属性；而大模型生成的释义无法回溯到词典原文。

所以优先级是：dictionary.db 的 Ch-Def → 既有词库 → Oxford 英文释义拼装 → 空。

**覆盖率的诚实说明**：dictionary.db 里 `pos='v'` 的 lemma 只有 333 个，与词表的 136 词
交集仅 9 个、其中 4 个有实际 Ch-Def。也就是说**约 97% 的词拿不到词典原文**。
这不是可以掩盖的事 —— 每个义位都会记录 `source` 字段，页面与文档里也如实标注来源，
使用者一眼能看出哪条是词典原文、哪条是二手拼装。
"""

import json
import logging
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEVIN_XLSX = os.path.join(ROOT, "docs/Levin移动动词候选词筛选表.xlsx")
DICTIONARY_DB = os.path.join(ROOT, "data/dictionary.db")
OXFORD_CACHE = os.path.join(ROOT, "data/oxford_cache.json")

# ---------------------------------------------------------------
# 意象图式类型 —— 取值**只能**来自这个清单
# ---------------------------------------------------------------
# 标准 2 明确「标注时不能自行新增图式类型」。把它做成常量并用测试钉住，
# 避免代码里随手扩出一个第五种。
IMAGE_SCHEMAS = (
    "源点脱离图式",
    "终点抵达图式",
    "方式伴随图式",
    "互动位移图式",
)

# 标准 1 的准入标签
PROTOTYPE_Y = "Y"           # 核心原型义，进入全套标注
PROTOTYPE_METAPHOR = "拓展"  # 隐喻引申义
PROTOTYPE_N = "N"           # 剔除

# 标准 4 的英汉对齐等级
ALIGNMENT_FULL = "完全对齐"
ALIGNMENT_PARTIAL = "部分对齐"
ALIGNMENT_ZERO = "零对齐"

# 每个 Levin 次类对应的意象图式（来自标准 2 的四类定义）
#   * 来源类 → 源点脱离图式（语义重心是离开起始位置）
#   * 终点类 → 终点抵达图式（语义重心是到达目标位置）
#   * 大部分方式类 → 方式伴随图式（语义重心是位移伴随的运动方式）
#   * 互动类 → 互动位移图式（两个实体同时位移并互动）
# 滚动滑行与运载工具两类比较特殊：它们的语义重心不在「用什么姿势」，
# 而在「靠什么介质/工具位移」，但也属于方式域（Talmy 方式动词），归入方式伴随图式。
SCHEMA_BY_SUB_CAT = {
    "来源类": "源点脱离图式",
    "终点类": "终点抵达图式",
    "陆地行进类": "方式伴随图式",
    "奔跑行进类": "方式伴随图式",
    "腾空跳跃类": "方式伴随图式",
    "匍匐爬行类": "方式伴随图式",
    "滚动滑行类": "方式伴随图式",
    "长途行进类": "方式伴随图式",
    "飞行游动类": "方式伴随图式",
    "运载工具类": "方式伴随图式",
    "目的类": "互动位移图式",
    "参与者类": "互动位移图式",
}

# ---------------------------------------------------------------
# 标准 4：英汉对齐等级 —— 可由词类特征推断的那部分
# ---------------------------------------------------------------
# 标准说得很清楚：对齐判断的对象是「英语义位激活的意象图式 vs 汉语表达该场景
# 常规使用的意象图式」。这是需要人工/模型逐义位判断的，**不能纯靠规则推导**。
#
# 这里只做一件有把握的事：按次类给出**默认倾向**，并在注释里说明依据；
# 最终值留给人工复核（文档第 45 段：「程序仅输出候选标签作为参考，
# 最终全部标签由研究者人工复核确认」）。所以字段名叫 candidate（候选），
# 灌库时会写入 `alignment` 并同时置 `needs_review=1`。
ALIGNMENT_HINT_BY_SUB_CAT = {
    # 路径义在汉语里通常由趋向补语承担，而英语动词本身内置路径 —— 典型的部分对齐
    "来源类": ALIGNMENT_PARTIAL,
    "终点类": ALIGNMENT_PARTIAL,
    # 方式义是「部分对齐」最经典的场景：英语动词自带方式（limp = 一瘸一拐地走），
    # 汉语动词「走」不带方式，必须加副词补充
    "陆地行进类": ALIGNMENT_PARTIAL,
    "奔跑行进类": ALIGNMENT_PARTIAL,
    "腾空跳跃类": ALIGNMENT_PARTIAL,
    "匍匐爬行类": ALIGNMENT_PARTIAL,
    "滚动滑行类": ALIGNMENT_PARTIAL,
    "长途行进类": ALIGNMENT_PARTIAL,
    "飞行游动类": ALIGNMENT_PARTIAL,
    "运载工具类": ALIGNMENT_PARTIAL,
    # 互动位移图式在汉语里多由「V1着V2」或「跟着/追着」类结构表达，
    # 图式本身能对上，但句法实现差异大 —— 仍按部分对齐待复核
    "目的类": ALIGNMENT_PARTIAL,
    "参与者类": ALIGNMENT_PARTIAL,
}

# ---------------------------------------------------------------
# 标准 4 配套字段【汉语句法特征】的候选值
# ---------------------------------------------------------------
CN_SYNTAX_BY_SCHEMA = {
    "源点脱离图式": "需趋向补语（离开／出去）；动词可带处所宾语",
    "终点抵达图式": "需趋向补语（到／进／上来）；常与处所介词短语共现",
    "方式伴随图式": "汉语动词不编码方式，需状语补充（如「一瘸一拐地走」）",
    "互动位移图式": "常用连动式（跟着／追着＋V）；需两个参与者共现",
}

TRANSLATION_STRATEGY_BY_SCHEMA = {
    "源点脱离图式": "保留源点脱离图式；汉语以趋向补语显化路径",
    "终点抵达图式": "保留终点抵达图式；汉语补出终点趋向成分",
    "方式伴随图式": "汉语增补方式状语以承载英语动词自带的方式语义",
    "互动位移图式": "重构为汉语连动结构；保留双参与者互动关系",
}


def _clean(value: Any) -> str:
    """去掉 Excel 里常见的全角空格与首尾空白。"""
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


# ===============================================================
# 1. Levin 筛选表
# ===============================================================
#: 三主范畴里代表「自移移动动词」的那一个。词表只收这一类 ——
#: 见 `load_levin_table` 的 scope 参数说明。
MAIN_CAT_MANNER = "方式聚焦型"


def load_levin_table(path: str = None, scope: str = "all") -> List[Dict[str, Any]]:
    """
    读 `docs/Levin移动动词候选词筛选表.xlsx` 的「去除不符合的」页。

    用这一页而不是「候选词筛选表」：前者是**筛选后**的词（Talmy 与 Levin 构式
    交替核查均为 Y），后者含 45 个被剔除的词及其剔除原因。两者的词目集合应满足
    「候选 = 保留 ∪ 剔除」，测试里会核对这一点，防止有人只改一页。

    Args:
        path: xlsx 路径，默认取仓库内的那份
        scope: 取词范围。
            ``"all"``（默认）取全部三类 171 词（方式 136 + 路径 22 + 互动 13）。
            这是本研究的词表范围：2026-10-07 决定把 9-28 被收窄掉的 35 个
            路径聚焦型 / 互动聚焦型词目捞回（它们已通过 Talmy 与构式核查），
            使源点脱离、终点抵达、互动位移三类图式拥有真实词元。
            ``"manner"`` 只取主范畴为「方式聚焦型」的 136 词 —— 9-28 至 10-07
            间的历史词表范围，与 `docs/output-oald10en-for-senselist-1020.xlsx`
            当时的提取范围一致；保留该选项供对照与语料连续性检查使用。

    Returns:
        [{verb, levin_source, cross_subclass, main_cat, sub_cat,
          sense_brief, judge_reason, image_schema, alignment_hint}, ...]
    """
    import openpyxl

    path = path or LEVIN_XLSX
    wb = openpyxl.load_workbook(path, data_only=True)
    if "去除不符合的" not in wb.sheetnames:
        raise ValueError(f"xlsx 缺少「去除不符合的」工作表: {wb.sheetnames}")

    ws = wb["去除不符合的"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header = [_clean(h) for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    required = ["词目(lemma)", "主范畴", "次类"]
    missing = [c for c in required if c not in idx]
    if missing:
        raise ValueError(f"xlsx 缺少必需列 {missing}；实际列 = {header}")

    def cell(row, name, default=""):
        i = idx.get(name)
        return _clean(row[i]) if i is not None and i < len(row) else default

    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows[1:]:
        verb = cell(row, "词目(lemma)")
        if not verb:
            continue
        key = verb.lower()
        if key in seen:
            logger.warning(f"Levin 表出现重复词目，已跳过后者: {verb}")
            continue
        seen.add(key)

        sub_cat = cell(row, "次类")
        main_cat = cell(row, "主范畴")
        schema = SCHEMA_BY_SUB_CAT.get(sub_cat)
        if schema is None:
            # 不静默兜底：新增了次类却忘了映射图式，必须让人看见
            logger.warning(f"次类「{sub_cat}」未映射意象图式，将留空待人工确认")

        out.append({
            "verb": verb,
            "levin_source": cell(row, "Levin来源子类"),
            "cross_subclass": cell(row, "是否跨子类收录"),
            "main_cat": main_cat,
            "sub_cat": sub_cat,
            "sense_brief": cell(row, "原型主导义简述"),
            "judge_reason": cell(row, "判断理由(备注)"),
            "image_schema": schema or "",
            # 规则推导的**候选**标签，需人工复核（见模块顶部说明）
            "alignment_hint": ALIGNMENT_HINT_BY_SUB_CAT.get(sub_cat, ""),
            "cn_syntax_hint": CN_SYNTAX_BY_SCHEMA.get(schema, "") if schema else "",
            "translation_hint": TRANSLATION_STRATEGY_BY_SCHEMA.get(schema, "") if schema else "",
        })

    if scope == "manner":
        kept = [e for e in out if e["main_cat"] == MAIN_CAT_MANNER]
        dropped = len(out) - len(kept)
        if dropped:
            logger.info(
                f"按 scope='manner' 只取「{MAIN_CAT_MANNER}」，另有 {dropped} 个"
                f"路径/互动聚焦型词未进词表（它们不是自移移动动词）"
            )
        out = kept
    elif scope != "all":
        raise ValueError(f"未知的 scope: {scope!r}（只接受 'manner' / 'all'）")

    out.sort(key=lambda e: (e["main_cat"], e["sub_cat"], e["verb"]))
    return out


def load_rejected_lemmas(path: str = None) -> Dict[str, str]:
    """读「候选词筛选表」里被剔除的词 → 剔除原因。用于核对与生成文档附录。"""
    import openpyxl

    path = path or LEVIN_XLSX
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["候选词筛选表"]
    rows = list(ws.iter_rows(values_only=True))
    header = [_clean(h) for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    rejected: Dict[str, str] = {}
    for row in rows[1:]:
        verb = _clean(row[idx["词目(lemma)"]]) if idx.get("词目(lemma)") is not None else ""
        if not verb:
            continue
        reason = _clean(row[idx["剔除原因"]]) if idx.get("剔除原因") is not None else ""
        if reason:
            rejected[verb] = reason
    return rejected


# ===============================================================
# 2. dictionary.db
# ===============================================================
_NS_RE = re.compile(r"<[^>]+>")


class DictionaryDB:
    """
    `data/dictionary.db` 的只读访问器。

    库里的 `dictionary` 表把每个词条存成一行，`xml` 字段是完整词条 XML。
    义位（sense）是 XML 里的 `<sense>` 节点，逐义位带 Ch-Def / En-Def /
    例句 / 近义反义词 —— 正好对应文档里「分析单元是义位，而非词目」的要求。
    """

    def __init__(self, path: str = None):
        self.path = path or DICTIONARY_DB
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def available(self) -> bool:
        return os.path.exists(self.path)

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            # 只读打开：这个库是第三方数据，本项目绝不该写它
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def has_verb(self, verb: str) -> bool:
        if not self.available:
            return False
        cur = self.connect().cursor()
        cur.execute(
            "SELECT 1 FROM dictionary WHERE lower(trim(lemma)) = ? AND trim(pos, char(32) || char(12288)) = 'v' LIMIT 1",
            (verb.lower(),),
        )
        return cur.fetchone() is not None

    def phonetic(self, verb: str) -> str:
        """
        取美/英音标，形如 ``əˈbændən``；两者相同只留一个，不同则用 `` | `` 分隔（美 | 英）。

        dictionary.db 只有一部分词条带 ``<pronunciation>``（实测 136 词里 9 个）。
        没有就返回空串 —— 前端据此显示「未收录」。**不猜、不转写**：音标是发音事实，
        用规则拼一个出来比留空更糟，因为读者无从分辨哪条是抄的、哪条是编的。
        """
        if not self.available:
            return ""
        cur = self.connect().cursor()
        cur.execute(
            "SELECT xml FROM dictionary WHERE lower(trim(lemma)) = ? AND trim(pos, char(32) || char(12288)) = 'v' LIMIT 1",
            (verb.lower(),),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return ""
        try:
            root = ET.fromstring(row[0])
        except ET.ParseError:
            return ""
        parts: List[str] = []
        for tag in ("AmE", "BrE"):
            node = root.find(f"pronunciation/{tag}/IPA")
            text = _clean(node.text if node is not None else None)
            if text and text not in parts:
                parts.append(text)
        return " | ".join(parts)

    def senses(self, verb: str) -> List[Dict[str, Any]]:
        """
        取某个动词的**全部义位**。

        只认 `pos = 'v'` 的行：文档的标注对象是动词，误取名词/形容词义位会污染结果。
        `pos` 字段在库里存在脏值（`'v '`、`' v'`、`'v\\u3000'`），所以用 `trim()`。

        Returns:
            [{sense_index, ch_ndef, en_ndef, construction, examples,
              ch_examples, synonyms, antonyms}, ...]
        """
        if not self.available:
            return []
        cur = self.connect().cursor()
        cur.execute(
            """SELECT xml FROM dictionary
               WHERE lower(trim(lemma)) = ? AND trim(pos, char(32) || char(12288)) = 'v'
               ORDER BY id""",
            (verb.lower(),),
        )
        rows = cur.fetchall()

        out: List[Dict[str, Any]] = []
        for (xml,) in rows:
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)
            except ET.ParseError as e:
                logger.warning(f"{verb}: 词条 XML 解析失败 ({e})")
                continue
            for sense in root.iter("sense"):
                parsed = _parse_sense(sense)
                if parsed is None:
                    continue
                parsed["sense_index"] = len(out) + 1
                out.append(parsed)
        return out


# ----------------------------------------------------------------------
# 原型义位选择
# ----------------------------------------------------------------------
# 为什么必须做选择：dictionary.db 里的义位按词典原书顺序排列，**首位往往不是位移原型义**。
# 实测 `charge` 的首条是「要价，收费」，而它在 Levin 表里的原型主导义是「猛冲向前」——
# 直接取首条会把一个移动动词的释义写成"收费"，这是实质性错误，不是排序偏好问题。
#
# 判定信号（全部来自仓库内的数据，不引外部词典）：
#   1. 与 xlsx「原型主导义简述」的**加权字符重合** —— 这是研究者人工判断的结论，权重最高
#   2. 定义里的中文位移语素
#   3. 英文 definiens 里的位移动词
#
# 第 1 项刻意用**加权字符重叠**而不是关键词子串匹配：简述是中文学术短语，
# 常常整串无标点（如「追逐另一对象移动」），切成词后 '词 in 释义' 永远是假；
# 而按字符算重合能拿到 0.25 vs 0.00 的清晰区分度。
# 权重用 idf 式的「该字在本词各义位中出现的频次」——「移动」「对象」这类
# 在每个义位里都有的字权重自动降到接近 0，不会把噪声算成信号。
_CN_MOTION_CHARS = "走跑跳爬滑行移进出去到离飞游滚落升奔冲越穿跨登攀航渡骑驾涉趟踩划钻溜蹿"

_EN_MOTION_TERMS = (
    "move", "moves", "moving", "movement", "go ", "goes", "going", "went",
    "travel", "walk", "run", "runs", "jump", "leap", "climb", "crawl", "creep",
    "swim", "fly", "flies", "flying", "roll", "slide", "slip", "glide",
    "ride", "drive", "sail", "row", "paddle", "march", "stride",
    "dash", "rush", "hurry", "wander", "stroll", "amble", "sprint", "gallop",
    "trot", "hop", "skip", "bounce", "dive", "plunge", "ascend", "descend",
    "from one place to another", "position", "direction", "journey",
    "chase", "pursue", "follow", "accompany", "escort", "lead", "guide",
    "on foot", "by land", "by sea", "by air", "away", "towards", "toward",
)

# 中文里的功能字与结构符号，直接排除，避免它们制造虚假重合
_CN_STOP = set("的 了 在 是 与 和 或 等 某 人 物 事 对 向 从 到 里 中 上 下 一个 〔〕〔〕；，。、（）()　 ")


def _cn_chars(text: str) -> List[str]:
    """取中文与字母数字字符，去掉标点与功能字。"""
    out = []
    for c in text or "":
        if c in _CN_STOP:
            continue
        if "\u4e00" <= c <= "\u9fff" or c.isalnum():
            out.append(c)
    return out


def _char_weights(senses: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    按 idf 计算每个字的信息量：在本词各义位里出现得越多，权重越低。

    这样「移动」「对象」这类在每个义位都出现的字几乎不贡献分数，
    而「追逐」「坠」「划」这类只在个别义位出现的字成为真正的信号。
    """
    from math import log

    texts = [_cn_chars(s.get("ch_ndef") or "") for s in senses]
    n = max(len(texts), 1)
    df: Dict[str, int] = {}
    for chars in texts:
        for c in set(chars):
            df[c] = df.get(c, 0) + 1
    return {c: log((n + 1) / (d + 1)) + 1e-6 for c, d in df.items()}


def has_motion_content(sense: Dict[str, Any]) -> bool:
    """这个义位本身是否含位移语义（中文位移语素 或 英文位移动词）。"""
    ch = sense.get("ch_ndef") or ""
    en = (sense.get("en_ndef") or "").lower()
    return any(c in ch for c in _CN_MOTION_CHARS) or any(t in en for t in _EN_MOTION_TERMS)


def brief_overlap(sense: Dict[str, Any], brief: str,
                  weights: Optional[Dict[str, float]] = None) -> float:
    """义位与「原型主导义简述」的加权字符重合率，范围 0~1。"""
    brief_chars = set(_cn_chars(brief))
    if not brief_chars:
        return 0.0
    sense_chars = set(_cn_chars(sense.get("ch_ndef") or ""))
    weights = weights or {}
    hit = sum(weights.get(c, 1.0) for c in brief_chars & sense_chars)
    total = sum(weights.get(c, 1.0) for c in brief_chars)
    return (hit / total) if total > 0 else 0.0


def score_sense(sense: Dict[str, Any], brief: str,
                weights: Optional[Dict[str, float]] = None) -> float:
    """综合分，只用于同一词内部的义位排序。"""
    score = 10.0 * brief_overlap(sense, brief, weights)
    if has_motion_content(sense):
        score += 2.0
    # 极短释义（如「sth runs」这种只给搭配框架、没给释义的残留条目）降权
    if len(sense.get("ch_ndef") or "") <= 6:
        score -= 1.0
    return score


def select_prototype_index(senses: List[Dict[str, Any]], brief: str) -> int:
    """
    选出最可能是「位移原型义」的义位下标。

    ## 为什么默认是「首条」，而不是「得分最高的那条」

    词典（OALD）的义位顺序本身携带信息：最常用、最核心的义位列在最前。
    实测 17 个能从 dictionary.db 取到释义的词里，**14 个的首条恰好就是原型义**
    （come「来到；到达」、go「去，走」、fall「从高处落下」、move「改变位置」、
    chase「追逐；追赶」、run「跑；奔跑」……）。

    但纯按「与原型主导义简述的字符重合」排序会**弄坏其中若干个**：`come` 的简述是
    「朝说话人位置趋近」，它描述的是方向语义，字面在「来到；到达」里一个都不出现，
    而某个冷僻义位「〔某物〕垂到〔某位置〕」反而因为带「位置」二字拿到最高分。
    用一个会挑冷僻义位的启发式去覆盖一个基本正确的默认值，是净损失。

    所以策略是**只在有硬证据时才覆盖**，两个条件必须同时成立：

      1. 首条义位**完全不含**位移语义（既无中文位移语素，也无英文位移动词）；
      2. 存在另一个义位，既含位移语义，又与简述有实际重合。

    这条规则能抓住真正需要修正的错例（`charge` 首条是「要价，收费」，
    而它的原型主导义是「猛冲向前」），又不会把本来正确的首条换掉。
    """
    with_ch = [i for i, s in enumerate(senses) if s.get("ch_ndef")]
    if not with_ch:
        return 0

    first = with_ch[0]
    if has_motion_content(senses[first]):
        return first

    weights = _char_weights(senses)
    best_i, best_score = first, 0.0
    for i in with_ch[1:]:
        if not has_motion_content(senses[i]):
            continue
        overlap = brief_overlap(senses[i], brief, weights)
        if overlap > best_score:
            best_score, best_i = overlap, i

    # 没有任何义位同时满足「含位移语义」与「与简述重合」，退回首条
    if best_score <= 0:
        return first
    return best_i


def prototype_is_confident(senses: List[Dict[str, Any]], brief: str) -> bool:
    """首条义位是否就是得分最高的那一条（即「直接取首条」没有选错）。"""
    if not senses:
        return False
    return select_prototype_index(senses, brief) == 0


def _parse_sense(sense: ET.Element) -> Optional[Dict[str, Any]]:
    """把一个 <sense> 节点解析成扁平结构；无任何实质内容时返回 None。"""
    definition = sense.find("definition")
    if definition is None:
        return None

    ch = _clean(definition.findtext("Ch-Def"))
    construction = _clean(definition.findtext("En-Def/construction"))
    definiens = _clean(definition.findtext("En-Def/definiens"))
    en = " ".join(x for x in (construction, definiens) if x)

    examples, ch_examples = [], []
    for ex in sense.iter("sense-example"):
        e = _clean(ex.findtext("En-Ex"))
        c = _clean(ex.findtext("Ch-Ex"))
        if e:
            examples.append(e)
            ch_examples.append(c)

    synonyms = [_clean(s.findtext("sense-synonymWord")) for s in sense.iter("sense-synonym")]
    antonyms = [_clean(a.findtext("antonymWord")) for a in sense.iter("antonym")]

    synonyms = [s for s in synonyms if s]
    antonyms = [a for a in antonyms if a]

    # 全是空的义位没有价值，丢掉 —— 库里存在这种占位节点（只有空标签）
    if not (ch or en or examples):
        return None

    return {
        "ch_ndef": ch,
        "en_ndef": en,
        "construction": construction,
        "examples": examples,
        "ch_examples": ch_examples,
        "synonyms": synonyms,
        "antonyms": antonyms,
    }


# ===============================================================
# 3. Oxford 缓存
# ===============================================================
def load_oxford_cache(path: str = None) -> Dict[str, Dict[str, Any]]:
    """
    读英文释义缓存。

    值可能是 `null`（抓取失败留下的占位），统一归一成 `{}`，避免下游 `None.get()`。
    """
    path = path or OXFORD_CACHE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Oxford 缓存读取失败: {e}")
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: (v if isinstance(v, dict) else {}) for k, v in raw.items()}


# ===============================================================
# 4. 合成词表
# ===============================================================
# 释义来源的**可信度分级**。数字越小越可信，供页面/文档排序与标注。
#
#   1  dictionary.db  —— OALD 已审校中文释义，可回溯原文（文档明确要求的「依据留存」）
#   2  legacy-library —— 既有词库的释义，多为「次范畴 + 特征」拼装（docx-features），
#                        可读但**不是词典原文**，属于二手转写
#   3  oxford-en      —— 只有英文释义，中文待补
#   4  pending        —— 两个来源都没有
SOURCE_RANK = {
    "dictionary.db": 1,
    "legacy-library": 2,
    # 来自 xlsx「原型主导义简述」列：是研究者自己写的原型义短语（如 slither「蜿蜒滑行爬行」），
    # 比机器拼装可信，但只是短语、不是完整词典释义
    "levin-brief": 3,
    "oxford-en": 4,
    "pending": 5,
}


def build_entries(levin_rows: List[Dict[str, Any]],
                  oxford: Dict[str, Dict[str, Any]],
                  db: Optional[DictionaryDB] = None,
                  legacy: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    把 Levin 分类 + dictionary.db 义位 + 既有词库 + Oxford 缓存合成一个词表。

    释义优先级（`definition_source` 字段如实记录实际取到哪一级）：

        1. `dictionary.db` 的 Ch-Def —— OALD 已审校中文释义，可回溯原文
        2. 既有 `data/motion_verbs_extracted.json` 的 chinese_ndef
        3. xlsx 的「原型主导义简述」—— 研究者自己写的原型义短语
        4. Oxford 英文释义（中文待补，字段里会显式写明）
        5. 空（页面与文档标注「待补」）

    **不伪造**：拿不到词典原文时不会假装拿到，`definition_source` 与
    `definition_rank` 会如实落库，文档与页面上都看得见。

    Args:
        levin_rows: load_levin_table() 的结果
        oxford: load_oxford_cache() 的结果
        db: DictionaryDB 实例；None 时不查词典
        legacy: {verb: 旧词库条目}；None 时跳过第 2 级

    Returns:
        每个元素含词目层字段 + `senses` 列表 + 来源标注
    """
    db = db if db is not None else DictionaryDB()
    legacy = legacy or {}
    out: List[Dict[str, Any]] = []

    for row in levin_rows:
        verb = row["verb"]
        senses = db.senses(verb) if db.available else []

        ch_ndef = ""
        source = "pending"
        example = ""
        # 第 1 级：词典原文
        #
        # 不能直接取 senses[0]：词典按原书顺序排列义位，首位常是引申义。
        # 实测 charge 的首条是「要价，收费」，而它的 Levin 原型主导义是「冲锋奔跑」。
        # 选错义位会把一个移动动词的释义写成完全无关的意思 —— 这是实质性错误，
        # 而不是排序问题。
        brief = row.get("sense_brief") or ""
        proto_idx = select_prototype_index(senses, brief)
        proto_sense = senses[proto_idx] if senses else None

        if proto_sense and proto_sense["ch_ndef"]:
            ch_ndef = proto_sense["ch_ndef"]
            source = "dictionary.db"
            example = (proto_sense["examples"] or [""])[0]

        # 第 2 级：既有词库
        if not ch_ndef:
            old = legacy.get(verb) or legacy.get(verb.lower())
            if old and (old.get("chinese_ndef") or "").strip():
                ch_ndef = old["chinese_ndef"].strip()
                source = "legacy-library"
                example = (old.get("example_sentence") or "").strip()
                legacy_senses = old.get("senses") or []
                if legacy_senses:
                    senses = legacy_senses

        # 第 3 级：Levin 表的「原型主导义简述」。
        # xlsx 里 171 个词**全都有**这一列，所以这一级能兜住所有缺中文释义的词，
        # 页面与文档里不会再出现「待补释义」这种空壳。
        if not ch_ndef:
            brief = (row.get("sense_brief") or "").strip()
            if brief:
                ch_ndef = f"{brief}（研究者标注的原型义简述，完整释义待补）"
                source = "levin-brief"

        # 第 4 级：Oxford 英文
        if not ch_ndef:
            ox = oxford.get(verb) or {}
            if ox.get("en_def"):
                ch_ndef = f"（英文释义，中文待补）{ox['en_def']}"
                source = "oxford-en"
                example = ox.get("en_example") or ""

        # sense_count 的语义：**实际会写进 word_senses 表的义位行数**。
        #
        # 必须与 replace_word_senses 写入的行数一致，否则文档里的「合计 N 条义位」
        # 与库里的行数对不上 —— 本轮先写成「有中文释义的义位数」(238)，而库里
        # 实际 246 行，同一件事两个数字互相矛盾。所以统一在最后按最终 senses 算。
        sense_count = len(senses)

        # 是否保留了词典首条义位（要在重排**之前**判断，重排后 proto_idx 恒为 0）
        # 仅 dictionary.db 来源有意义：legacy/levin-brief 来源 senses 被整表替换，
        # proto_idx 指的是词典义位列表，对它们没有"保留首条"可言
        kept_first = (proto_idx == 0) if source == "dictionary.db" else True

        # 把选中的原型义位挪到首位：页面的「义位明细」表按 sense_index 升序展示，
        # 原型义排第一才符合文档「原型义为核心样本」的表述。
        if senses and proto_idx > 0:
            senses = [senses[proto_idx]] + [
                s for i, s in enumerate(senses) if i != proto_idx
            ]
        for i, sense in enumerate(senses):
            sense["sense_index"] = i + 1

        entry = dict(row)
        entry.update({
            "chinese_ndef": ch_ndef,
            "example_sentence": example,
            # 选择器是否保留了词典的首条义位。False 表示首条完全不含位移语义、
            # 被硬证据覆盖掉了 —— 这些词复核时应优先看。
            "prototype_is_first": kept_first,
            "definition_source": source,
            "definition_rank": SOURCE_RANK[source],
            "sense_count": sense_count,
            "has_dictionary_verb": db.has_verb(verb) if db.available else False,
            "phonetic": db.phonetic(verb) if db.available else "",
            "senses": senses,
        })
        out.append(entry)

    return out


def load_legacy_library(path: str = None) -> Dict[str, Dict[str, Any]]:
    """读既有词库 `data/motion_verbs_extracted.json`，用于释义优先级的第 2 级。"""
    path = path or os.path.join(ROOT, "data/motion_verbs_extracted.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"旧词库读取失败: {e}")
        return {}
    if not isinstance(rows, list):
        return {}
    return {str(r.get("verb", "")).strip(): r for r in rows if r.get("verb")}


def audit_coverage(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    统计释义来源覆盖率。

    这是**必须公开**的数字：dictionary.db 与 Levin 词表交集很小，若不在文档与页面上
    说明，使用者会以为每条释义都是词典原文。
    """
    from collections import Counter

    by_source = Counter(e["definition_source"] for e in entries)
    in_db = sum(1 for e in entries if e["has_dictionary_verb"])
    with_senses = sum(1 for e in entries if e["senses"])
    return {
        "total": len(entries),
        "by_source": dict(by_source),
        "in_dictionary_db": in_db,
        "with_senses": with_senses,
        "missing_from_db": len(entries) - in_db,
        # dictionary.db 里 pos='v' 的 lemma 只有 333 个，与 Levin 交集很小，
        # 所以「多少条能拿到词典原文」是必须公开的数字
        "dictionary_原文率": round(in_db / len(entries) * 100, 1) if entries else 0.0,
    }
