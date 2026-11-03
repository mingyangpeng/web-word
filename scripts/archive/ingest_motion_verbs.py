#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ingest English motion-verb definitions into the project MySQL (Docker) instance.

Pipeline:
  1. Parse data/docs/英语移动动词五大范畴分类总表.docx -> per-verb category metadata
     (次范畴 / 二级次范畴 / Levin来源 / 典型构式 / 核心语义特征 / 备注)
  2. For each verb, look it up in data/dictionary.db (SQLite) and extract <Ch-Def>
     (Oxford-style Chinese gloss) + example sentences.
  3. Verbs missing from dictionary.db (or without <Ch-Def>) are supplemented with the
     free Oxford/WordNet gloss from dictionaryapi.dev, combined with the docx's
     semantic-feature decomposition (Talmy manner/path/direction/aspect/scope).
  4. Build an app-compatible semantic_table dict (manner/path/direction/aspect/scope)
     and a clean chinese_ndef, then INSERT/UPSERT into the MySQL `definitions` table.

Requires: docx, pymysql, requests
"""
import os
import re
import sys
import json
import sqlite3
import logging

import docx
from pymysql.cursors import DictCursor
import pymysql
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ingest_motion_verbs")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 让 `from src.xxx` 可用（与 src/app.py 的处理一致），无论从哪个目录调用本脚本。
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DOCX_PATH = os.path.join(ROOT, "data/docs/英语移动动词五大范畴分类总表.docx")
DICT_DB = os.path.join(ROOT, "data/dictionary.db")

# ---- MySQL 连接（复用主程序的配置解析：环境变量 > config/config.yaml > 默认）----
# 修正前这里把 host/user/password 硬编码在本文件里，导致换机器必须改脚本本身。
# 现在与 src/mysql_db.py 共用同一套优先级，跑法与主程序完全一致：
#     MYSQL_HOST=127.0.0.1 python scripts/ingest_motion_verbs.py
from src.mysql_db import (  # noqa: E402
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DATABASE,
    MYSQL_CHARSET,
)

OXFORD_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
OXFORD_CACHE = os.path.join(ROOT, "data/oxford_cache.json")

# ----------------------------------------------------------------------------
# 1. Parse docx category metadata
# ----------------------------------------------------------------------------
def parse_docx(path):
    d = docx.Document(path)
    verb_meta = {}
    for t in d.tables[:5]:  # first 5 tables are the detailed per-verb tables
        cur_main = cur_sub = None
        for row in t.rows[1:]:
            c = [cell.text.strip() for cell in row.cells]
            if len(c) < 7:
                continue
            main, sub, verb, levin, constr, feat, note = c[0], c[1], c[2], c[3], c[4], c[5], c[6]
            if main:
                cur_main = main
            if sub:
                cur_sub = sub
            for part in re.split(r"[,，/ ]+", verb):
                part = part.strip().lower()
                if part and part.isalpha():
                    verb_meta[part] = {
                        "main_cat": cur_main,
                        "sub_cat": sub or cur_sub,
                        "levin": levin,
                        "constr": constr,
                        "feat": feat,
                        "note": note,
                    }
    return verb_meta


# ----------------------------------------------------------------------------
# 2. Extract Chinese definition + examples from dictionary.db
# ----------------------------------------------------------------------------
def get_db_definition(lemma, con):
    cur = con.cursor()
    cur.execute("SELECT xml FROM dictionary WHERE lemma=? LIMIT 1", (lemma,))
    r = cur.fetchone()
    if not r:
        return None
    xml = r[0]
    ch_defs = re.findall(r"<Ch-Def[^>]*>(.*?)</Ch-Def>", xml, re.S)
    ch_defs = [re.sub(r"\s+", "", c) for c in ch_defs if c.strip()]
    # Chinese examples
    ch_ex = re.findall(r"<sense-Ex-s[^>]*>(.*?)</sense-Ex-s>", xml, re.S)
    ch_ex = [re.sub(r"<[^>]+>", "", c).strip() for c in ch_ex if c.strip()]
    # English examples
    en_ex = re.findall(r"<sense-Ex-e[^>]*>(.*?)</sense-Ex-e>", xml, re.S)
    en_ex = [re.sub(r"<[^>]+>", "", c).strip() for c in en_ex if c.strip()]
    return {
        "ch_def": ch_defs[0] if ch_defs else None,
        "ch_def_all": ch_defs,
        "ch_example": ch_ex[0] if ch_ex else None,
        "en_example": en_ex[0] if en_ex else None,
    }


# ----------------------------------------------------------------------------
# 3. Oxford (dictionaryapi.dev) gloss + example
# ----------------------------------------------------------------------------
_oxford_cache = {}
if os.path.exists(OXFORD_CACHE):
    try:
        with open(OXFORD_CACHE, "r", encoding="utf-8") as _f:
            _oxford_cache = json.load(_f)
    except Exception:
        _oxford_cache = {}


def _save_oxford_cache():
    try:
        with open(OXFORD_CACHE, "w", encoding="utf-8") as _f:
            json.dump(_oxford_cache, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass


MOTION_KEYWORDS = ("move", "movement", "travel", "go ", "go fast", "speed", "run", "walk",
                    "fly", "rush", "hurry", "dart", "dash", "sweep", "glide", "slide",
                    "roll", "turn", "advance", "proceed", "pass", "cross", "climb", "descend",
                    "rise", "fall", "leap", "jump", "flow", "drift", "sail", "ride", "swim",
                    "crawl", "creep", "hasten", "flee", "escape", "depart", "leave", "enter",
                    "approach", "retreat", "progress", "journey", "trot", "gallop", "bound")


def _motion_score(text):
    t = (text or "").lower()
    return sum(1 for k in MOTION_KEYWORDS if k in t)


def fetch_oxford_one(word):
    """Fetch a single verb's Oxford gloss, preferring motion/ movement senses.

    Returns dict {'en_def', 'en_example'} or None.
    """
    try:
        r = requests.get(OXFORD_API.format(word=word), timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict):  # error object
            return None

        candidates = []
        # Collect verb definitions first, then any
        for entry in data:
            for m in entry.get("meanings", []):
                is_verb = m.get("partOfSpeech") in ("verb", "verb-transitive", "verb-intransitive")
                for defn in m.get("definitions", []):
                    txt = re.sub(r"\s+", " ", defn.get("definition", "")).strip()
                    ex = (defn.get("example") or "").strip() or None
                    candidates.append((is_verb, _motion_score(txt), txt, ex))

        if not candidates:
            return None

        # Sort: verb PoS first, then higher motion score, then shorter (core) definition
        candidates.sort(key=lambda x: (not x[0], -x[1], len(x[2])))
        best = candidates[0]
        # If top candidate has no motion signal but a lower-ranked one does, prefer it
        if best[1] == 0:
            for cand in candidates:
                if cand[0] and cand[1] > 0:
                    best = cand
                    break
        return {"en_def": best[2], "en_example": best[3]}
    except Exception as e:
        logger.warning("Oxford fetch failed for %s: %s", word, e)
    return None


def get_oxford(word):
    """Return cached Oxford result for a verb (must be prefetched)."""
    return _oxford_cache.get(word)


def prefetch_oxford(words):
    """Concurrent prefetch of Oxford glosses for all needed verbs."""
    needed = [w for w in words if w not in _oxford_cache]
    logger.info("Prefetching Oxford glosses for %d verbs (of %d total)...", len(needed), len(words))
    from concurrent.futures import ThreadPoolExecutor, as_completed

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_map = {ex.submit(fetch_oxford_one, w): w for w in needed}
        for fut in as_completed(fut_map):
            w = fut_map[fut]
            try:
                _oxford_cache[w] = fut.result()
            except Exception:
                _oxford_cache[w] = None
            done += 1
            if done % 25 == 0:
                logger.info("  Oxford fetched %d/%d", done, len(needed))
    logger.info("Oxford prefetch complete: %d with gloss, %d empty",
                sum(1 for v in _oxford_cache.values() if v), len(_oxford_cache))


# ----------------------------------------------------------------------------
# 4. Semantic-feature -> Chinese decomposition
# ----------------------------------------------------------------------------
FEATURE_CN = {
    "位移": "位移；移动",
    "终点": "到达终点",
    "起点": "从起点",
    "离开": "离开",
    "来源": "离开来源",
    "返回": "返回原处",
    "趋近": "趋近参照点",
    "远离": "远离参照点",
    "方式": "以特定方式",
    "滚动": "滚动",
    "滑行": "滑行",
    "弹跳": "弹跳",
    "飘移": "飘移",
    "飘浮": "飘浮",
    "奔跑": "奔跑",
    "爬行": "爬行",
    "跳跃": "跳跃",
    "游动": "游动",
    "飞行": "飞行",
    "上升": "向上移动",
    "下降": "向下移动",
    "前进": "向前移动",
    "后退": "向后移动",
    "目的": "以某目的为方向",
    "追赶": "追赶",
    "跟随": "跟随",
    "参与者": "涉及另一参与者",
    "陪同": "陪同",
    "引领": "引领",
    "引导": "引导",
    "隐秘": "隐秘地",
    "正式": "正式地",
    "逃离": "逃离",
    "出发": "出发",
    "方向": "朝向某方向",
}

# 次范畴 -> 主范畴（路径聚焦 / 方式聚焦 / 互动聚焦）
PATH_FOCUS_CATS = {"到达类", "返回类", "来类", "去类", "进入类", "外出离场类",
                   "上升类", "下降类", "前进类", "后退类", "脱离类", "逃离类"}
MANNER_FOCUS_CATS = {"滚动滑行类", "陆地行进类", "腾空跳跃类", "飞行游动类",
                     "匍匐爬行类", "长途行进类", "运载工具类"}
INTERACT_PURPOSE = {"追赶类", "尾随类"}
INTERACT_PARTICIPANT = {"陪同类", "引导类"}


def main_category(main_cat):
    if main_cat in PATH_FOCUS_CATS:
        return "路径聚焦类"
    if main_cat in MANNER_FOCUS_CATS:
        return "方式聚焦类"
    if main_cat in INTERACT_PURPOSE:
        return "互动聚焦类（目的）"
    if main_cat in INTERACT_PARTICIPANT:
        return "互动聚焦类（参与者）"
    return "未分类"


def features_to_cn(feat):
    out = []
    for tok, cn in FEATURE_CN.items():
        if tok in feat:
            out.append(cn)
    # dedupe preserve order
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


def build_semantic_table(meta, oxford):
    main = meta.get("main_cat") or ""
    sub = meta.get("sub_cat") or ""
    feat = meta.get("feat") or ""
    constr = meta.get("constr") or ""
    note = meta.get("note") or ""
    main_cat = main_category(main)

    feat_cn = features_to_cn(feat)

    # 方式 (manner): locomotion style from 二级次范畴 + [+方式] tags
    manner_bits = []
    if sub:
        manner_bits.append(sub)
    for tok in ["滚动", "滑行", "弹跳", "飘移", "飘浮", "奔跑", "爬行", "跳跃", "游动", "飞行"]:
        if tok in feat:
            manner_bits.append(tok + "前进")
    manner = "；".join(manner_bits) if manner_bits else (sub or "（见释义）")

    # 路径 (path): from 典型构式
    path = constr
    if not path:
        if "路径" in main_cat or main_cat == "路径聚焦类":
            path = "由动词词根融合路径信息"
        else:
            path = "路径由卫星成分/介词短语（如 to/at/from/across）补充"

    # 方向 (direction): from 主范畴 + 特征 tags
    direction_bits = []
    for tok in ["终点", "来源", "返回", "趋近", "远离", "上升", "下降", "前进", "后退", "方向"]:
        if tok in feat:
            direction_bits.append(tok)
    if main_cat == "路径聚焦类":
        direction_bits.insert(0, "路径/方向为词汇核心")
    direction = "；".join(direction_bits) if direction_bits else "依构式补语确定"

    # 体相 (aspect): bodily posture / 备注
    aspect_bits = []
    if note:
        aspect_bits.append(note)
    if "隐秘" in feat:
        aspect_bits.append("动作隐秘")
    if "正式" in feat:
        aspect_bits.append("姿态正式")
    if not aspect_bits:
        aspect_bits.append("通常体现该运动类型的典型身体姿态")
    aspect = "；".join(aspect_bits)

    # 范围 (scope): category chain
    scope = f"{main_cat} / {main}" + (f" / {sub}" if sub else "")

    return {
        "manner": manner,
        "path": path,
        "direction": direction,
        "aspect": aspect,
        "scope": scope,
        "_main_cat": main_cat,
        "_feat_cn": "；".join(feat_cn),
    }


# ----------------------------------------------------------------------------
# 5. Build chinese_ndef
# ----------------------------------------------------------------------------
def build_chinese_ndef(verb, meta, db_def, oxford):
    sub = meta.get("sub_cat") or ""
    feat = meta.get("feat") or ""
    feat_cn = features_to_cn(feat)
    feat_str = "、".join(feat_cn) if feat_cn else "移动"

    # Source 1: dictionary.db Ch-Def (best)
    if db_def and db_def.get("ch_def"):
        return db_def["ch_def"], "dictionary.db"

    # Source 2: build from features + Oxford gloss
    parts = []
    if sub:
        parts.append(sub)
    parts.append(feat_str + "。")
    if oxford and oxford.get("en_def"):
        parts.append(f"（Oxford: {oxford['en_def']}）")
    text = "".join(parts).strip()
    src = "oxford-combined" if (oxford and oxford.get("en_def")) else "docx-features"
    return text, src


# ----------------------------------------------------------------------------
# MySQL insert (reuse exact schema from mysql_db.py)
# ----------------------------------------------------------------------------
CREATE_DEF = """
CREATE TABLE IF NOT EXISTS definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    verb VARCHAR(100) NOT NULL UNIQUE,
    chinese_ndef TEXT NOT NULL,
    semantic_table JSON NOT NULL,
    example_sentence TEXT,
    model_version VARCHAR(50) DEFAULT 'zhipu-glm-4',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_definitions_verb (verb(50)),
    INDEX idx_definitions_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def get_conn():
    return pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE, charset=MYSQL_CHARSET, cursorclass=DictCursor, autocommit=True,
    )


def insert_definition(verb, chinese_ndef, semantic_table, example_sentence, model_version):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_DEF)
            semantic_json = json.dumps(semantic_table, ensure_ascii=False)
            cur.execute("""
                INSERT INTO definitions (verb, chinese_ndef, semantic_table, example_sentence, model_version)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    chinese_ndef = VALUES(chinese_ndef),
                    semantic_table = VALUES(semantic_table),
                    example_sentence = VALUES(example_sentence),
                    model_version = VALUES(model_version),
                    updated_at = CURRENT_TIMESTAMP
            """, (verb, chinese_ndef, semantic_json, example_sentence, model_version))
            return True
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    dry_run = "--dry-run" in sys.argv
    verb_meta = parse_docx(DOCX_PATH)
    logger.info("Parsed %d unique verbs from docx", len(verb_meta))

    con = sqlite3.connect(DICT_DB)
    con.row_factory = None

    # Determine DB coverage
    cur = con.cursor()
    cur.execute("SELECT lemma FROM dictionary")
    dbset = set(r[0].lower() for r in cur.fetchall())

    # Prefetch Oxford glosses for verbs not already covered by dictionary.db
    need_oxford = [v for v in verb_meta if v.lower() not in dbset]
    prefetch_oxford(need_oxford)

    rows = []
    missing_db = []
    for verb in sorted(verb_meta):
        meta = verb_meta[verb]
        in_db = verb.lower() in dbset
        db_def = get_db_definition(verb, con) if in_db else None
        has_ch = bool(db_def and db_def.get("ch_def"))
        if not in_db:
            missing_db.append(verb)

        # Oxford supplement for missing / no-Ch-Def is fetched in bulk before loop
        oxford = _oxford_cache.get(verb) if not has_ch else None

        chinese_ndef, src = build_chinese_ndef(verb, meta, db_def, oxford)
        sem = build_semantic_table(meta, oxford)

        # example sentence
        example = None
        if db_def:
            example = db_def.get("ch_example") or db_def.get("en_example")
        if not example and oxford:
            example = oxford.get("en_example")

        rows.append({
            "verb": verb,
            "main_cat": sem["_main_cat"],
            "sub_cat": meta.get("sub_cat") or meta.get("main_cat"),
            "chinese_ndef": chinese_ndef,
            "semantic_table": {k: v for k, v in sem.items() if not k.startswith("_")},
            "example_sentence": example,
            "model_version": src,
            "in_db": in_db,
            "has_ch": has_ch,
            "oxford": bool(oxford and oxford.get("en_def")),
        })

    con.close()

    _save_oxford_cache()

    # Summary
    n = len(rows)
    n_in_db = sum(1 for r in rows if r["in_db"])
    n_has_ch = sum(1 for r in rows if r["has_ch"])
    n_oxford = sum(1 for r in rows if r["oxford"])
    logger.info("Total verbs: %d | in dictionary.db: %d | with Ch-Def: %d | Oxford-supplemented: %d",
                n, n_in_db, n_has_ch, n_oxford)

    # Dump intermediate JSON for transparency
    dump_path = os.path.join(ROOT, "data/motion_verbs_extracted.json")
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    logger.info("Wrote extraction dump -> %s", dump_path)

    if dry_run:
        # print a few samples
        for r in rows[:3] + rows[-3:]:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print("\n[DRY RUN] No MySQL writes performed.")
        return

    # Insert into MySQL
    ok = 0
    for r in rows:
        try:
            insert_definition(r["verb"], r["chinese_ndef"], r["semantic_table"],
                              r["example_sentence"], r["model_version"])
            ok += 1
        except Exception as e:
            logger.error("Insert failed for %s: %s", r["verb"], e)
    logger.info("Inserted/updated %d/%d definitions into MySQL", ok, n)

    # Final count in DB
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM definitions")
        print("definitions table row count:", cur.fetchone()["c"])
    conn.close()


if __name__ == "__main__":
    main()
