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
    get_or_create_cluster,
    init_database,
    insert_definition,
    refresh_cluster_sizes,
    replace_word_relations,
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


def build_synonym_pairs(entries):
    """
    从次语义范畴（sub_cat）推导词间关系的**簇内完全图**。

    规则：同一次范畴内的动词语义相近，构成一个词义簇；簇内**任意两词**都建立一条
    近义边（完全图）。例如「处所脱离」= abandon/desert/leave 三词两两相连；
    「常态行走」56 词则产生 C(56,2)=1540 条边。

    为什么坚持完全图（早期版本为了「避免枢纽」改成了环邻，每个词只连左右 3 个
    邻居）：环邻会让用户查到 amble 时看不到 walk，只看到 clump/dodder —— 那是人为
    截断，不是语义事实。用户要的是「查一个词就能看到它整个词簇」，完全图才是对的
    表达。边数增长的问题交给**展示层**解决：页面只画当前簇且设上限，DB 里存完整
    真值。二者职责分开后，数据正确、界面也不糊。

    完全图总边数（155 词 / 25 簇）实测为 2143 条。

    Returns:
        (pairs, clusters)
        pairs:    [(verb_a, verb_b, sub_cat), ...]，a<b 的无向去重对
        clusters: {(main_cat, sub_cat): [verb, ...]}
    """
    clusters = defaultdict(list)
    for e in entries:
        clusters[(e.get("main_cat") or "", e.get("sub_cat") or "")].append(e["verb"])

    pairs = []
    for (_main_cat, sub_cat), verbs in clusters.items():
        members = sorted(set(verbs))
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                pairs.append((a, b, sub_cat))

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


def seed_database(entries, oxford_cache, pairs, clusters) -> dict:
    """
    把词库、词义簇与词间关系写入 MySQL。

    顺序很重要：先建簇（definitions 的 cluster_id 有外键指向它），再灌定义
    （带上 cluster_id），最后写完全图边（word_relations 的两个外键指向 definitions）。

    与 main() 拆开是为了让容器入口（scripts/entrypoint.sh）也能调用，
    从而做到「docker compose up 之后自动就有词库」，无需人工执行灌库脚本。

    Returns:
        {"definitions": n, "clusters": n, "relations": n}
    """
    # 1) 词义簇
    cluster_id_by_key = {}
    for (main_cat, sub_cat), verbs in clusters.items():
        cid = get_or_create_cluster(main_cat, sub_cat)
        if cid is not None:
            cluster_id_by_key[(main_cat, sub_cat)] = cid

    # 2) 定义（带簇归属）
    sub_cat_to_cluster = {
        sc: cluster_id_by_key.get((mc, sc))
        for (mc, sc) in clusters
    }
    ok_defs = 0
    for entry in entries:
        verb, chinese, semantic_table, example, model_version = build_definition_row(
            entry, oxford_cache
        )
        cid = sub_cat_to_cluster.get(entry.get("sub_cat"))
        if insert_definition(verb, chinese, semantic_table, example, model_version, cid):
            ok_defs += 1

    # 3) 词间关系（簇内完全图，整批替换）
    relations = [
        (a, b, "近义", f"{_mc} / {sub_cat}")
        for a, b, sub_cat in pairs
        for _mc in [next(mc for (mc, sc) in clusters if sc == sub_cat)]
    ]
    ok_rel = replace_word_relations(relations)

    # 4) 回填簇规模
    refresh_cluster_sizes()

    return {"definitions": ok_defs, "clusters": len(cluster_id_by_key), "relations": ok_rel}


def definitions_count() -> int:
    """当前 definitions 表行数；库不可用时返回 -1。"""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM definitions")
            return int(cur.fetchone()["n"] or 0)
    except Exception:
        return -1


def main():
    parser = argparse.ArgumentParser(description="把词库与词间关系灌入 MySQL")
    parser.add_argument("--dry-run", action="store_true", help="只解析与构建图谱，不写数据库")
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="仅当 definitions 表为空时才写入（容器首启自动灌库用，可重复执行）",
    )
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

    if args.if_empty:
        existing = definitions_count()
        if existing > 0:
            print(f"definitions 已有 {existing} 行，--if-empty 跳过写入")
            return 0
        print("definitions 为空，开始首次灌库")

    stats = seed_database(entries, oxford_cache, pairs, clusters)
    print(f"word_clusters:  {stats['clusters']} 个")
    print(f"definitions:    写入/更新 {stats['definitions']}/{len(entries)}")
    print(f"word_relations: {stats['relations']} 条（{len(pairs)} 对簇内完全图边）")

    # 校验：DB 里的边数应与完全图理论值一致
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM definitions")
        n_defs = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM word_clusters")
        n_clusters = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM word_relations")
        n_rel = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM v_cluster_complete_graph")
        n_view = cur.fetchone()["n"]
    print(f"库内合计: definitions={n_defs}, word_clusters={n_clusters}, "
          f"word_relations={n_rel}")
    print(f"一致性核对: 视图推导的完全图边数={n_view} "
          f"({'一致 ✅' if n_view == n_rel else '不一致 ❌'})")

    # 抽样确认词间关系可查（度数应等于 簇大小-1）
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT d.verb, c.label AS cluster_label, c.size AS cluster_size,
                   COUNT(r.id) AS relatives
            FROM definitions d
            LEFT JOIN word_clusters c ON c.id = d.cluster_id
            LEFT JOIN word_relations r
                   ON r.verb_a_id = d.id OR r.verb_b_id = d.id
            GROUP BY d.id
            ORDER BY relatives DESC
            LIMIT 5
        """)
        print("关系最多的词 (度数应 = 簇大小-1):")
        for r in cur.fetchall():
            print(f"    {r['verb']:<12} 簇={r['cluster_label']:<28} "
                  f"size={r['cluster_size']:>3} 度数={r['relatives']:>3}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
