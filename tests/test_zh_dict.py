"""《现汉7》中文词典（zh_dict_*）的集成测试：解析器 → 数据层 → 查询。

三层覆盖：
  1. parse_modern_chinese_dict.parse_entry —— 用 mdx 真实片段做单元锚点
     （跑 6 义项 / 坎儿¹² 同形词 / B超 裸义项号 / 语域 / 比喻标记）；
  2. zh_dict 数据层 —— 业务库上灌入小样本，验证 (lemma, pinyin) 唯一键
     的两个坑（拼音声调折叠 㾦 pēi/pèi、CJK 扩展区 虺𪨇/虺𬯎）与例句回挂；
  3. 查询 —— lookup_lemma / search_verbs / get_zh_dict_stats。

没有可用的 MySQL 时数据层测试 skip（与 test_migration_integration 同口径）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from src import zh_dict as zd  # noqa: E402


# ============================================
# 1. 解析器单元锚点（纯函数，不碰数据库）
# ============================================

def _parse_one(html_line: str, lemma: str):
    """单条 mdx 正文行 → parse_entry 结果。"""
    import re
    from parse_modern_chinese_dict import parse_entry, ENTRY_RE
    m = ENTRY_RE.search(html_line)
    assert m, "ENTRY_RE 未匹配"
    return parse_entry(lemma, m.group(1))


PAO_PAO = ('<link rel="stylesheet" type="text/css" href="现代汉语词典.css">'
           '<main><span class="title">跑</span><div class="metadata">'
           '<div class="py">pǎo</div></div><span class="lya">动</span><br>'
           '<span class="num">①</span>两只脚或四条腿迅速前进（脚可以同时腾空）：'
           '～动丨赛～｜～了一圈<span class="er">儿</span>｜鹿～得很快丨'
           '<span class="lyc">比喻用法</span>火车在飞～。<br>'
           '<span class="num">②</span>逃走：别让兔子～了｜～了和尚～不了庙。<br>'
           '<span class="num">③</span><span class="lyb">方</span>走：～路。<br>'
           '<span class="num">④</span>为某种事务而奔走：～码头｜～材料。<br>'
           '<span class="num">⑤</span>物体离开了应该在的位置：～调'
           '<span class="er">儿</span>｜～题。<br>'
           '<span class="num">⑥</span>气体、液体等泄漏或挥发：～水｜～气。'
           '<br><span class="sma">另见</span>981页páo。</main>')


def test_parse_pao_six_senses():
    e = _parse_one(PAO_PAO, "跑")
    assert e["pinyin"] == "pǎo"
    assert e["pos"] == "动"
    assert len(e["senses"]) == 6
    nos = [s["no"] for s in e["senses"]]
    assert nos == ["①", "②", "③", "④", "⑤", "⑥"]
    # ①释义与例句
    s1 = e["senses"][0]
    assert s1["definition"].startswith("两只脚或四条腿迅速前进")
    assert "跑动" in s1["examples"] and "赛跑" in s1["examples"]
    assert s1["is_metaphor"] is True  # 火车在飞跑（lyc 标记）
    # ③方言语域
    assert e["senses"][2]["register"] == "方言"
    assert e["senses"][2]["definition"] == "走"
    # ②无比喻
    assert e["senses"][1]["is_metaphor"] is False
    # 例句里的 ～ 已还原为词目
    assert "别让兔子跑了" in e["senses"][1]["examples"]
    # 另见
    assert e["cross_refs"] and e["cross_refs"][0].startswith("另见")


def test_parse_bare_circled_numbers():
    """B超 形态：①② 裸文本连排（无 .num 无 <br>）也能切分。"""
    line = ('<link rel="stylesheet" type="text/css" href="现代汉语词典.css">'
            '<main><span class="title">B超</span><div class="metadata">'
            '<div class="py">B chāo</div></div>①B型超声诊断的简称：做～。'
            '②B型超声诊断仪的简称，利用超声脉冲回波幅度调制荧光屏辉度分布'
            '而显示人体断面像并从中获得临床诊断信息的装置。</main>')
    e = _parse_one(line, "B超")
    assert len(e["senses"]) == 2
    assert e["senses"][0]["no"] == "①"
    assert e["senses"][0]["definition"].startswith("B型超声诊断的简称")
    assert e["senses"][0]["examples"] == ["做B超。"]
    assert e["senses"][1]["no"] == "②"


def test_parse_single_sense_no_number():
    """单义项词条（奔跑）：无义项号，no=None，释义例句正常拆。"""
    line = ('<link rel="stylesheet" type="text/css" href="现代汉语词典.css">'
            '<main><span class="title">奔跑</span><div class="metadata">'
            '<div class="py">bēnpǎo</div></div><span class="lya">动</span>'
            '很快地跑；奔走：往来～｜～如飞。</main>')
    e = _parse_one(line, "奔跑")
    assert len(e["senses"]) == 1
    s = e["senses"][0]
    assert s["no"] is None
    assert s["definition"] == "很快地跑；奔走"
    assert s["examples"] == ["往来奔跑", "奔跑如飞。"]


def test_parse_erhua_and_register():
    """小跑：儿化标注 + 口语语域。"""
    line = ('<link rel="stylesheet" type="text/css" href="现代汉语词典.css">'
            '<main><span class="title">小跑</span><div class="metadata">'
            '<div class="py">xiǎopǎo</div></div>（～<span class="er">儿</span>）'
            '<span class="lyb">口</span><span class="lya">动</span>'
            '快步走，接近于跑；小步慢跑：一路～。</main>')
    e = _parse_one(line, "小跑")
    assert e["erhua"] is True
    assert e["senses"][0]["register"] == "口语"
    assert e["senses"][0]["definition"].startswith("快步走")


# ============================================
# 2. 数据层（需要 MySQL；不可用则 skip）
# ============================================

def _db_available():
    try:
        with zd.get_db_cursor() if hasattr(zd, "get_db_cursor") else _cursor():
            pass
        return True
    except Exception:
        return False


def _cursor(autocommit: bool = True):
    from src.mysql_db import get_db_cursor
    return get_db_cursor(autocommit=autocommit)


def _db_up() -> bool:
    try:
        with _cursor() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def loaded_sample():
    """灌入覆盖两个唯一键坑的小样本，返回灌入计数。

    隔离方式：**先备份业务数据，测完恢复**。zh_dict_* 是《现汉7》全量词典
    （7 万词条），绝不能被测试清空 —— 之前直接 DELETE 曾把共享库的词典
    数据抹掉（页面上词典对照区变空）。备份走三表全量 SELECT，7 万行在
    秒级完成；没有可用的 MySQL 时整个模块 skip。
    """
    if not _db_up():
        pytest.skip("MySQL 不可用，跳过 zh_dict 数据层测试")
    # ---- 备份业务数据 ----
    backup = {}
    with _cursor() as c:
        for table, cols in (
            ("zh_dict_entries",
             "id, lemma, pinyin, pos, erhua, cross_ref, raw_html"),
            ("zh_dict_senses",
             "id, entry_id, sense_no, definition, register, is_metaphor, sense_order"),
            ("zh_dict_examples",
             "id, sense_id, ex_order, example, is_metaphor"),
        ):
            c.execute(f"SELECT {cols} FROM {table}")
            backup[table] = list(c.fetchall())

    sample = [
        {   # 多音字：pēi / pèi 声调不同（unicode_ci 会折叠 → bin 排序解决）
            "lemma": "㾦", "pinyin": "pēi", "pos": None, "erhua": False,
            "cross_refs": [], "raw_html": None,
            "senses": [{"no": None, "register": None, "is_metaphor": False,
                        "definition": "中医指疮", "examples": []}],
        },
        {
            "lemma": "㾦", "pinyin": "pèi", "pos": None, "erhua": False,
            "cross_refs": [], "raw_html": None,
            "senses": [{"no": None, "register": None, "is_metaphor": False,
                        "definition": "又音", "examples": []}],
        },
        {   # 跑 pǎo：6 义项 + 例句（验证例句回挂）
            "lemma": "跑", "pinyin": "pǎo", "pos": "动", "erhua": False,
            "cross_refs": ["另见 981页páo"], "raw_html": None,
            "senses": [
                {"no": "①", "register": None, "is_metaphor": True,
                 "definition": "两只脚或四条腿迅速前进",
                 "examples": ["跑动", "赛跑", "火车在飞跑"]},
                {"no": "②", "register": None, "is_metaphor": False,
                 "definition": "逃走", "examples": ["别让兔子跑了"]},
                {"no": "③", "register": "方言", "is_metaphor": False,
                 "definition": "走", "examples": ["跑路"]},
                {"no": "④", "register": None, "is_metaphor": False,
                 "definition": "为某种事务而奔走", "examples": ["跑码头"]},
                {"no": "⑤", "register": None, "is_metaphor": False,
                 "definition": "物体离开了应该在的位置", "examples": ["跑题"]},
                {"no": "⑥", "register": None, "is_metaphor": False,
                 "definition": "气体、液体等泄漏或挥发", "examples": ["跑气"]},
            ],
        },
        {   # 跑 páo：另一读音（同词目不同读音 → 两条 entry）
            "lemma": "跑", "pinyin": "páo", "pos": "动", "erhua": False,
            "cross_refs": [], "raw_html": None,
            "senses": [{"no": None, "register": None, "is_metaphor": False,
                        "definition": "走兽用脚刨地", "examples": ["虎跑泉"]}],
        },
        {   # CJK 扩展区字符（unicode_ci 判等 → bin 排序解决）
            "lemma": "虺𪨇", "pinyin": "huītuí", "pos": "动", "erhua": False,
            "cross_refs": [], "raw_html": None,
            "senses": [{"no": None, "register": None, "is_metaphor": False,
                        "definition": "A", "examples": []}],
        },
        {
            "lemma": "虺𬯎", "pinyin": "huītuí", "pos": None, "erhua": False,
            "cross_refs": [], "raw_html": None,
            "senses": [{"no": None, "register": None, "is_metaphor": False,
                        "definition": "B", "examples": []}],
        },
    ]
    counts = zd.replace_zh_dict(sample)
    yield counts
    # ---- 恢复业务数据（含自增 id 原值，外键关系不变）----
    with _cursor(autocommit=False) as c:
        for table in ("zh_dict_examples", "zh_dict_senses", "zh_dict_entries"):
            c.execute(f"DELETE FROM {table}")
        for table in ("zh_dict_entries", "zh_dict_senses", "zh_dict_examples"):
            rows = backup[table]
            if not rows:
                continue
            cols = ", ".join(rows[0].keys())
            placeholders = ", ".join(f"%({k})s" for k in rows[0])
            c.executemany(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                rows,
            )


def test_load_counts(loaded_sample):
    counts = loaded_sample
    assert counts["entries"] == 6
    assert counts["senses"] == 11  # 1+1+6+1+1+1
    assert counts["examples"] == 9  # 3+1+1+1+1+1 + 1(páo)


def test_lookup_pao_multi_reading(loaded_sample):
    """多音字：跑 pǎo/páo 两条 entry，义项与例句正确回挂。"""
    entries = zd.lookup_lemma("跑")
    assert len(entries) == 2
    by_py = {e["pinyin"]: e for e in entries}
    pao3 = by_py["pǎo"]
    assert len(pao3["senses"]) == 6
    s1 = pao3["senses"][0]
    assert s1["definition"].startswith("两只脚")
    assert len(s1["examples"]) == 3
    assert bool(s1["is_metaphor"]) is True
    assert pao3["senses"][2]["register"] == "方言"
    pao2 = by_py["páo"]
    assert pao2["senses"][0]["examples"] == [
        {"example": "虎跑泉", "is_metaphor": False}]


def test_lookup_tone_distinct(loaded_sample):
    """声调折叠坑：㾦 pēi / pèi 两条都能查到（bin 排序不折叠）。"""
    entries = zd.lookup_lemma("㾦")
    assert {e["pinyin"] for e in entries} == {"pēi", "pèi"}


def test_lookup_cjk_ext(loaded_sample):
    """CJK 扩展区坑：虺𪨇 / 虺𬯎 是两个不同词目。"""
    a = zd.lookup_lemma("虺𪨇")
    b = zd.lookup_lemma("虺𬯎")
    assert len(a) == 1 and len(b) == 1
    assert a[0]["senses"][0]["definition"] == "A"
    assert b[0]["senses"][0]["definition"] == "B"


def test_search_verbs(loaded_sample):
    hits = zd.search_verbs("跑")
    lemmas = {h["lemma"] for h in hits}
    assert "跑" in lemmas
    # 非动词不出现
    assert "㾦" not in lemmas


def test_stats(loaded_sample):
    stats = zd.get_zh_dict_stats()
    assert stats["entries"] == 6
    assert stats["senses"] == 11
    assert stats["examples"] == 9
    assert stats["verb_entries"] == 3  # 跑×2 + 虺𪨇
