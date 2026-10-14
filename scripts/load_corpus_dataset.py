#!/usr/bin/env python3
"""把 output/ 语料数据包灌入 web_word_db，供 Streamlit 页面展示。

数据源（与 data/corpus/ 同源，优先 output/）：
  - wsketch_full/<verb>.json          → corpus_word_stats + corpus_collocations
  - 06_图式提取结果/schema_evidence/  → word_schema_scores + corpus_schema_evidence

用法：
  python scripts/load_corpus_dataset.py             # 全量替换（先删后插，事务）
  python scripts/load_corpus_dataset.py --if-empty  # 已灌过则跳过
"""
import argparse
import json
import os
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src import mysql_db  # noqa: E402


def find_dir(*candidates):
    for c in candidates:
        p = os.path.join(BASE, c)
        if os.path.isdir(p):
            return p
    return None


def iter_collocations(gramrels):
    """展平槽位：嵌套槽（prepositional phrases 的介词子槽）直接作为搭配条目，
    与 export_verb_corpus_sheets.py 的口径一致。"""
    for rel in gramrels:
        words = rel.get("Words", [])
        if words and "word" not in words[0] and "Words" in words[0]:
            for sub in words:
                yield rel["name"], sub.get("name"), sub.get("count"), sub.get("score")
        else:
            for w in words:
                yield rel["name"], w.get("word"), w.get("count"), w.get("score")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-empty", action="store_true",
                    help="corpus_word_stats 已有数据时跳过")
    args = ap.parse_args()

    if args.if_empty and mysql_db.corpus_dataset_ready():
        print("语料数据集已灌入，跳过（去掉 --if-empty 可强制重灌）")
        return 0

    sketch_dir = find_dir(
        os.path.join("output", "05_原始数据", "wsketch_full"),
        os.path.join("data", "corpus", "wsketch_full"),
    )
    evidence_dir = find_dir(
        os.path.join("output", "06_图式提取结果", "schema_evidence"),
        os.path.join("data", "corpus", "wsketch_full"),
    )
    if not sketch_dir or not evidence_dir:
        print("✗ 找不到数据目录（output/05_原始数据/wsketch_full 与 "
              "output/06_图式提取结果/schema_evidence）")
        return 1

    if not mysql_db.init_database():
        print("✗ MySQL 不可用")
        return 1

    stats_rows, coll_rows = [], []
    verbs = sorted(f[:-5] for f in os.listdir(sketch_dir) if f.endswith(".json"))
    for verb in verbs:
        j = json.load(open(os.path.join(sketch_dir, verb + ".json"), encoding="utf-8"))
        gramrels = j.get("Gramrels", [])
        n_types = 0
        rank_map = {}
        for slot, word, count, score in iter_collocations(gramrels):
            if word is None:
                continue
            key = f"{slot} > {word}" if (slot and word == slot) else slot
            rank_map.setdefault(slot, 0)
            rank_map[slot] += 1
            n_types += 1
            coll_rows.append({
                "verb": verb, "slot": slot, "rank_in_slot": rank_map[slot],
                "collocate": word, "logdice": score, "cooccur_count": count,
                "typical_combo": None, "combo_freq": None,
            })
        stats_rows.append({
            "verb": verb, "lpos": j.get("lpos") or "",
            "freq": j.get("freq") or 0, "relfreq": j.get("relfreq"),
            "slot_count": len(gramrels), "collocate_count": n_types,
            "candidate_schema": None, "retrieved_at": date(2026, 9, 30),
        })

    score_rows, evidence_rows = [], []
    cand = {}
    for verb in verbs:
        p = os.path.join(evidence_dir, verb + ".json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        cand[verb] = d.get("candidate_schema")
        ranks = {s: i + 1 for i, s in enumerate(d.get("ranking", []))}
        for schema, info in (d.get("schemas") or {}).items():
            score_rows.append({
                "verb": verb, "schema_name": schema,
                "slots_present": info.get("slots_present", 0),
                "slots_defined": info.get("slots_defined", 0),
                "coverage": info.get("coverage"),
                "n_types": info.get("n_types", 0),
                "mean_logdice": info.get("mean_logdice"),
                "prominence_score": info.get("prominence_score"),
                "cand_rank": ranks.get(schema, 99),
            })
            for e in (info.get("top_evidence") or [])[:10]:
                evidence_rows.append({
                    "verb": verb, "schema_name": schema,
                    "rank_no": e.get("rank_no") or (evidence_rows and 0) or 0,
                    "word": e.get("word"), "logdice": e.get("logdice"),
                    "slot": e.get("slot") or "",
                })
    # rank_no 按 schema 内顺序重建（JSON 里没有显式排名）
    from collections import defaultdict
    seen = defaultdict(int)
    for r in evidence_rows:
        seen[(r["verb"], r["schema_name"])] += 1
        r["rank_no"] = seen[(r["verb"], r["schema_name"])]
    for r in stats_rows:
        r["candidate_schema"] = cand.get(r["verb"])

    n1 = mysql_db.replace_corpus_word_stats(stats_rows)
    n2 = mysql_db.replace_corpus_collocations(coll_rows)
    n3 = mysql_db.replace_corpus_schema_scores(score_rows)
    n4 = mysql_db.replace_corpus_schema_evidence(evidence_rows)
    print(f"corpus_word_stats={n1}, corpus_collocations={n2}, "
          f"word_schema_scores={n3}, corpus_schema_evidence={n4}")
    ok = n1 == len(verbs) and n2 == len(coll_rows)
    print("✅ 语料数据集灌入完成" if ok else "✗ 灌入行数不符，检查日志")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
