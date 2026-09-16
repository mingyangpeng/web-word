#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把词库与词间关系灌入 MySQL。

与旧脚本 scripts/ingest_motion_verbs.py 的区别：
  * 旧脚本依赖 docx + 联网抓 Oxford API（dictionaryapi.dev）才能补全释义，
    在离线或没有 docx 的机器上直接跑不起来 —— 这是「换个机器就跑不动」的
    主要原因之一。
  * 本脚本**零外部网络依赖**：只读仓库内已固化好的
    data/motion_verbs_extracted.json（155 词，含中文释义与五元语义分解）
    与 data/oxford_cache.json（英文释义缓存），因此可以在任何机器上重跑。

产出：
  1. definitions 表 —— 155 个动词的释义与 semantic_table
  2. synonyms 表    —— 词与词的关系（同一 sub_cat 的近义簇内两两相连）
  3. data/word_graph.json —— 同一份词间关系的图谱文件（节点=词，边=近义/同类），
     供人工审阅与后续图谱工具消费

用法：
    python scripts/load_word_library.py                # 使用默认连接配置
    MYSQL_HOST=127.0.0.1 python scripts/load_word_library.py
    python scripts/load_word_library.py --dry-run      # 只解析不写库
"""
import argparse
import json
import os
import sys
from collections import defaultdict

# 让 `from src.xxx` 可用（与 app.py 的 sys.path 处理保持一致）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.mysql_db import (  # noqa: E402
    get_db_cursor,
    init_database,
    insert_definition,
    insert_synonym,
)

LIBRARY_PATH = os.path.join(ROOT, "data", "motion_verbs_extracted.json")
OXFORD_CACHE = os.path.join(ROOT, "data", "oxford_cache.json")
WORD_GRAPH_PATH = os.path.join(ROOT, "data", "word_graph.json")


def load_library():
    """读取 155 词词库。"""
    with open(LIBRARY_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_oxford_cache():
    """读取英文释义缓存（可能不存在，返回空 dict）。"""
    if not os.path.exists(OXFORD_CACHE):
        return {}
    with open(OXFORD_CACHE, encoding="utf-8") as f:
        data = json.load(f) or {}
    # 缓存里可能存在 value 为 null 的键（未取到释义的词），统一归一成空 dict，
    # 否则下游 .get() 会在 None 上炸掉。
    return {k: (v if isinstance(v, dict) else {}) for k, v in data.items()}


def build_definition_row(entry, oxford_cache):
    """
    把词库条目整理成 definitions 表需要的字段。

    返回 (verb, chinese_ndef, semantic_table, example_sentence, model_version)
    """
    verb = entry["verb"]
    cached = oxford_cache.get(verb) or {}
    chinese = (entry.get("chinese_ndef") or "").strip()

    # 释义缺失时用英文缓存兜底，保证每行都有可展示内容
    if not chinese:
        en_def = (cached.get("en_def") or "").strip()
        chinese = f"（暂无中文释义）{en_def}" if en_def else f"{verb}：暂无释义数据"

    semantic_table = entry.get("semantic_table") or {}

    example = entry.get("example_sentence") or cached.get("en_example")

    return (
        verb,
        chinese,
        semantic_table,
        example,
        entry.get("model_version") or "word-library",
    )


def build_synonym_pairs(entries, neighbors_per_side=3, complete_graph_max=6):
    """
    从 sub_cat 近义簇推导词与词的关系。

    规则：同一次范畴（sub_cat）内的动词语义相近，构成近义簇。例如
    「奔跑行进」= bolt / canter / charge / dart / dash / gallop / hasten ...
    「处所脱离」= abandon / desert / leave。

    连边策略（避免噪声边）：
      * 小簇（<= complete_graph_max 个词，如 3 词的「处所脱离」）：完全图，
        任意两词都互为近义 —— 这也正是用户最需要对比的场景。
      * 大簇（如 56 词的「常态行走」）：不做完全图。C(56,2)=1540 条边会把
        每个词连成 55 度枢纽，对「显示近义动词」毫无用处。改为把簇内词按
        字母序排成环，每个词只连左右各 neighbors_per_side 个邻居，使每个词
        的度上限为 2*neighbors_per_side（默认 6）。

    之所以按字母序而不是语义相似度排序：词库里没有词对之间的相似度分数，
    唯一可用的分组信息就是 sub_cat。按字母序取邻居是确定性做法，至少保证
    结果可复现；真正精细的近义程度排序应由大模型生成后再替换此处。

    Returns:
        (pairs, clusters)
        pairs: [(verb_a, verb_b, sub_cat), ...]，a<b 去重后的无序对
        clusters: {(main_cat, sub_cat): [verb, ...]}
    """
    clusters = defaultdict(list)
    for e in entries:
        clusters[(e.get("main_cat") or "", e.get("sub_cat") or "")].append(e["verb"])

    seen = set()
    pairs = []

    def add(a, b, sub_cat):
        if a == b:
            return
        key = (a, b) if a < b else (b, a)
        if key in seen:
            return
        seen.add(key)
        pairs.append((key[0], key[1], sub_cat))

    for (_main_cat, sub_cat), verbs in clusters.items():
        members = sorted(set(verbs))
        n = len(members)
        if n < 2:
            continue

        if n <= complete_graph_max:
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    add(a, b, sub_cat)
        else:
            for i, a in enumerate(members):
                for offset in range(1, neighbors_per_side + 1):
                    add(a, members[(i + offset) % n], sub_cat)

    pairs.sort()
    return pairs, clusters


def build_word_graph(entries, clusters, pairs):
    """
    生成词间关系图谱文件 data/word_graph.json。

    这是「描述词与词之间关系」的产物：节点是动词，边是近义关系
    （同一次范畴簇），并带 category 标注便于按范畴检索。
    """
    nodes = []
    for e in entries:
        nodes.append({
            "id": e["verb"],
            "label": e["verb"],
            "main_cat": e.get("main_cat"),
            "sub_cat": e.get("sub_cat"),
            "chinese_ndef": e.get("chinese_ndef"),
            "semantic_table": e.get("semantic_table"),
        })

    links = []
    for a, b, sub_cat in pairs:
        mc = next(
            (mc for (mc, sc) in clusters if sc == sub_cat), ""
        )
        links.append({
            "source": a,
            "target": b,
            "relation": "近义",
            "sub_cat": sub_cat,
            "main_cat": mc,
        })

    return {
        "directed": False,
        "multigraph": False,
        "description": "英语移动动词词间关系图：节点=动词，边=同一次范畴近义关系",
        "nodes": nodes,
        "links": links,
        "clusters": [
            {
                "main_cat": mc,
                "sub_cat": sc,
                "size": len(verbs),
                "verbs": sorted(set(verbs)),
            }
            for (mc, sc), verbs in sorted(clusters.items())
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="把词库与词间关系灌入 MySQL")
    parser.add_argument("--dry-run", action="store_true", help="只解析与构建图谱，不写数据库")
    args = parser.parse_args()

    entries = load_library()
    oxford_cache = load_oxford_cache()
    print(f"词库: {len(entries)} 个动词  (Oxford 缓存: {len(oxford_cache)} 条)")

    clusters = defaultdict(list)
    for e in entries:
        clusters[(e.get("main_cat") or "", e.get("sub_cat") or "")].append(e["verb"])
    pairs, clusters = build_synonym_pairs(entries)
    print(f"近义簇: {len(clusters)} 个  ->  词间近义关系: {len(pairs)} 条")

    # 词间关系图谱（本地产物，便于审阅/被图谱工具消费）
    graph = build_word_graph(entries, clusters, pairs)
    with open(WORD_GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    print(f"已写出词间关系图谱: {os.path.relpath(WORD_GRAPH_PATH, ROOT)}")

    if args.dry_run:
        print("--dry-run：跳过数据库写入")
        return 0

    if not init_database(max_retries=3, retry_delay=2.0):
        print("❌ MySQL 不可用，无法导入。请检查 MYSQL_HOST / config/config.yaml", file=sys.stderr)
        return 1

    ok_defs = 0
    for entry in entries:
        verb, chinese, semantic_table, example, model_version = build_definition_row(
            entry, oxford_cache
        )
        if insert_definition(verb, chinese, semantic_table, example, model_version):
            ok_defs += 1
    print(f"definitions: 写入/更新 {ok_defs}/{len(entries)}")

    ok_syn = 0
    for a, b, _sub_cat in pairs:
        # synonyms 表是有向的（original_verb_id -> synonym_verb），
        # 双向各写一条，才能从任一词查到同簇其他词。
        if insert_synonym(a, b):
            ok_syn += 1
        if insert_synonym(b, a):
            ok_syn += 1
    print(f"synonyms:    写入 {ok_syn} 条（{len(pairs)} 对 × 双向）")

    # 校验
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM definitions")
        n_defs = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM synonyms")
        n_syn = cur.fetchone()["n"]
    print(f"库内合计: definitions={n_defs}, synonyms={n_syn}")

    # 抽样确认词间关系可查
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT d.verb, COUNT(s.id) AS relatives
            FROM definitions d
            LEFT JOIN synonyms s ON s.original_verb_id = d.id
            GROUP BY d.id ORDER BY relatives DESC LIMIT 5
        """)
        print("近义关系最多的词:", [(r["verb"], r["relatives"]) for r in cur.fetchall()])

    return 0


if __name__ == "__main__":
    sys.exit(main())
