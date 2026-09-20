#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把词表、义位与词间关系灌入 MySQL。

## 数据来源（三者职责不同，不要混用）

| 来源 | 提供什么 | 地位 |
|------|----------|------|
| `docs/Levin移动动词候选词筛选表.xlsx` | 171 个通过筛选的自移移动动词、三主范畴 / 十二次类、判断理由 | **词目分类权威** |
| `data/dictionary.db` | 逐义位的 Ch-Def / En-Def / 例句 / 近义反义词 | **释义正确性首选** |
| `data/motion_verbs_extracted.json` | 旧词库的中文释义与五元语义分解 | 释义兜底 |
| `data/oxford_cache.json` | 英文释义 | 末级兜底 |

解析逻辑全部在 `src/word_source.py`，本脚本只负责编排与写库。

## 与旧版本的关键差异

旧版读 `data/motion_verbs_extracted.json` 的 155 词。现在以 Levin 筛选表的 171 词为准，
分类体系也从自定义的 25 个 sub_cat 换成文档规定的 **三主范畴 / 十二次类**。

这意味着**簇与关系必须整体重建**：新旧两套次类混在一张图上会得到自相矛盾的结果。
所以本脚本会先 `clear_all_word_data()` 清空 four 张词表（保留 feedbacks 与 usage_logs
这两个用户产生的表），再重新写入。想保留旧数据请先备份。

## 用法

    python scripts/load_word_library.py                 # 全量重建
    python scripts/load_word_library.py --dry-run       # 只解析不写库
    python scripts/load_word_library.py --if-empty      # 仅当库为空时写入（容器首启用）
    MYSQL_HOST=127.0.0.1 python scripts/load_word_library.py
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
    clear_all_word_data,
    get_db_cursor,
    get_or_create_cluster,
    init_database,
    insert_definition,
    prune_empty_clusters,
    refresh_cluster_sizes,
    replace_word_relations,
    replace_word_senses,
)
from src.word_source import (  # noqa: E402
    ALIGNMENT_PARTIAL,
    DictionaryDB,
    PROTOTYPE_METAPHOR,
    PROTOTYPE_Y,
    audit_coverage,
    build_entries,
    load_legacy_library,
    load_levin_table,
    load_oxford_cache,
    load_rejected_lemmas,
)

WORD_GRAPH_PATH = os.path.join(ROOT, "data", "word_graph.json")


# ============================================
# 义位标注
# ============================================
def annotate_senses(senses, levin_row):
    """
    给每个义位打上标注标签。

    **这里只产出候选标签，不是最终结论。** `docs/义项判定标准.docx` 第 45 段明确：
    「程序 / 大模型仅输出候选标签作为参考，最终全部标签由研究者人工复核确认」。
    所以每个义位都置 `needs_review=1`，页面上也会显示「待复核」。

    判定规则的落点：

      * ``prototype_level`` —— 只有第一个义位按 ``Y``（原型物理位移义）处理，因为
        词目是**依据主导原型义**收录进 Levin 表的；其余义位一律标 ``拓展``（待人工
        确认哪些其实是 ``N`` 静态/状态变化义 —— 这需要读懂释义，规则判不了）。
      * ``image_schema`` / ``cn_syntax`` / ``translation_strategy`` —— 取自该词所属
        次类，因为同一子类的动词共享同一套图式凸显重心。
      * ``alignment`` —— 次类默认倾向（多数为「部分对齐」），待人工复核。

    Args:
        senses: DictionaryDB.senses() 的结果
        levin_row: load_levin_table() 的单行

    Returns:
        带标注字段的义位列表
    """
    out = []
    for i, sense in enumerate(senses):
        item = dict(sense)
        item["prototype_level"] = PROTOTYPE_Y if i == 0 else PROTOTYPE_METAPHOR
        item["image_schema"] = levin_row.get("image_schema") or None
        item["alignment"] = levin_row.get("alignment_hint") or ALIGNMENT_PARTIAL
        item["cn_syntax"] = levin_row.get("cn_syntax_hint") or None
        item["translation_strategy"] = levin_row.get("translation_hint") or None
        item["source"] = "dictionary.db"
        item["needs_review"] = 1
        out.append(item)
    return out


def build_semantic_table(entry):
    """
    组五元语义分解表。

    五项内容来自**文档定义的字段**，而不是旧版那种把次范畴名硬塞进 manner、
    把「NP V NP」塞进 path 的占位写法（旧词库里 manner 一栏写的常是次范畴名，
    path 一栏写的是句法框架 —— 那不是语义分解，是字段错位）。
    """
    schema = entry.get("image_schema") or ""
    return {
        "manner": entry.get("sense_brief") or entry.get("sub_cat") or "",
        "path": f"{entry.get('main_cat', '')} / {entry.get('sub_cat', '')}".strip(" /"),
        "direction": schema,
        "aspect": entry.get("cn_syntax") or "",
        "scope": entry.get("translation_strategy") or "",
    }


def build_synonym_pairs(entries):
    """
    从次类推导词间关系的**簇内完全图**。

    规则：同一次类内的动词语义相近，构成一个词义簇；簇内**任意两词**都建一条近义边。
    例如「来源类」8 词两两相连 = C(8,2)=28 条；「陆地行进类」45 词 = 990 条。

    为什么坚持完全图（早期版本为「避免枢纽」改成了环邻，每个词只连左右 3 个邻居）：
    环邻会让用户查到 amble 时看不到 walk，只看到 clump/dodder —— 那是人为截断，
    不是语义事实。边数增长的问题交给**展示层**解决（页面只画当前簇并设上限），
    DB 里存完整真值。

    Returns:
        (pairs, clusters)
        pairs:    [(verb_a, verb_b, main_cat, sub_cat), ...]，a<b 的无向去重对
        clusters: {(main_cat, sub_cat): [verb, ...]}
    """
    clusters = defaultdict(list)
    for e in entries:
        clusters[(e.get("main_cat") or "", e.get("sub_cat") or "")].append(e["verb"])

    pairs = []
    for (main_cat, sub_cat), verbs in clusters.items():
        members = sorted(set(verbs))
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                pairs.append((a, b, main_cat, sub_cat))

    pairs.sort()
    return pairs, clusters


def build_word_graph(entries, clusters, pairs):
    """生成词间关系图谱文件 data/word_graph.json（含义位标注，供人工审阅与图谱工具消费）。"""
    nodes = [
        {
            "id": e["verb"],
            "label": e["verb"],
            "main_cat": e.get("main_cat"),
            "sub_cat": e.get("sub_cat"),
            "image_schema": e.get("image_schema"),
            "prototype_level": PROTOTYPE_Y,
            "alignment": e.get("alignment_hint"),
            "chinese_ndef": e.get("chinese_ndef"),
            "definition_source": e.get("definition_source"),
            "sense_count": e.get("sense_count", 0),
        }
        for e in entries
    ]

    links = [
        {
            "source": a, "target": b, "relation": "近义",
            "main_cat": main_cat, "sub_cat": sub_cat,
        }
        for a, b, main_cat, sub_cat in pairs
    ]

    cluster_nodes = []
    for (main_cat, sub_cat), verbs in sorted(clusters.items()):
        sample = next(
            (e for e in entries
             if e.get("main_cat") == main_cat and e.get("sub_cat") == sub_cat),
            {},
        )
        cluster_nodes.append({
            "main_cat": main_cat,
            "sub_cat": sub_cat,
            "size": len(verbs),
            "edge_count": len(verbs) * (len(verbs) - 1) // 2,
            "image_schema": sample.get("image_schema"),
            "cn_syntax": sample.get("cn_syntax_hint"),
            "translation_strategy": sample.get("translation_hint"),
            "verbs": sorted(set(verbs)),
        })

    return {
        "directed": False,
        "multigraph": False,
        "description": "英语自移移动动词词间关系图：节点=动词，边=同一次类近义关系（簇内完全图）",
        "source": "docs/Levin移动动词候选词筛选表.xlsx + data/dictionary.db",
        "nodes": nodes,
        "links": links,
        "clusters": cluster_nodes,
    }


# ============================================
# 写库
# ============================================
def seed_database(entries, pairs, clusters) -> dict:
    """
    把词表、义位与词间关系写入 MySQL。

    顺序很重要：先建簇（definitions.cluster_id 外键指向它），再灌定义（带 cluster_id），
    再写义位明细（外键指向 definitions.id），最后写完全图边（两个外键指向 definitions）。

    与 main() 拆开是为了让容器入口（scripts/entrypoint.sh）也能调用。

    Returns:
        {"definitions": n, "clusters": n, "relations": n, "senses": n}
    """
    # 1) 词义簇（带簇层面的图式与句法特征）
    cluster_id_by_key = {}
    for (main_cat, sub_cat) in clusters:
        sample = next(
            (e for e in entries
             if e.get("main_cat") == main_cat and e.get("sub_cat") == sub_cat),
            {},
        )
        cid = get_or_create_cluster(
            main_cat, sub_cat,
            image_schema=sample.get("image_schema"),
            cn_syntax=sample.get("cn_syntax_hint"),
            translation_strategy=sample.get("translation_hint"),
        )
        if cid is not None:
            cluster_id_by_key[(main_cat, sub_cat)] = cid

    # 2) 定义 + 义位明细
    cluster_of = {(e.get("main_cat"), e.get("sub_cat")): cluster_id_by_key.get(
        (e.get("main_cat"), e.get("sub_cat"))) for e in entries}

    ok_defs = 0
    ok_senses = 0
    for entry in entries:
        verb = entry["verb"]
        cid = cluster_of.get((entry.get("main_cat"), entry.get("sub_cat")))
        chinese = entry.get("chinese_ndef") or f"{verb}：待补释义"

        annotations = {
            "en_ndef": entry.get("en_ndef") or None,
            "phonetic": entry.get("phonetic") or None,
            "levin_source": entry.get("levin_source") or None,
            "cross_subclass": entry.get("cross_subclass") or None,
            "sense_brief": entry.get("sense_brief") or None,
            "judge_reason": entry.get("judge_reason") or None,
            "image_schema": entry.get("image_schema") or None,
            "prototype_level": PROTOTYPE_Y,
            "alignment": entry.get("alignment_hint") or None,
            "cn_syntax": entry.get("cn_syntax_hint") or None,
            "translation_strategy": entry.get("translation_hint") or None,
            "definition_source": entry.get("definition_source") or None,
            "source_rank": entry.get("definition_rank"),
            "sense_count": entry.get("sense_count") or 0,
            # 文档第 45 段：「程序 / 大模型仅输出候选标签作为参考，
            # 最终全部标签由研究者人工复核确认」。所以**所有**行的标注都置 1，
            # 而不是只标二手释义那些 —— 图式、对齐等级、原型层级全是规则推导的候选值。
            # 释义本身的可信度由 definition_source / source_rank 单独表达，两件事不混。
            "needs_review": 1,
            # 原型义位是否就是词典首条；0 表示被选择器用硬证据修正过
            "prototype_is_first": 1 if entry.get("prototype_is_first", True) else 0,
        }

        if not insert_definition(
            verb, chinese, build_semantic_table(entry),
            entry.get("example_sentence") or None,
            entry.get("definition_source") or "word-library",
            cid, annotations,
        ):
            continue
        ok_defs += 1

        senses = annotate_senses(entry.get("senses") or [], entry)
        if senses:
            with get_db_cursor() as cur:
                cur.execute("SELECT id FROM definitions WHERE verb = %s", (verb,))
                row = cur.fetchone()
            if row:
                ok_senses += replace_word_senses(int(row["id"]), senses)

    # 3) 词间关系（簇内完全图，整批替换）
    relations = [
        (a, b, "近义", f"{main_cat} / {sub_cat}")
        for a, b, main_cat, sub_cat in pairs
    ]
    ok_rel = replace_word_relations(relations)

    # 4) 清理空簇并回填簇规模
    prune_empty_clusters()
    refresh_cluster_sizes()

    return {"definitions": ok_defs, "clusters": len(cluster_id_by_key),
            "relations": ok_rel, "senses": ok_senses}


def definitions_count() -> int:
    """当前 definitions 表行数；库不可用时返回 -1。"""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM definitions")
            return int(cur.fetchone()["n"] or 0)
    except Exception:
        return -1


# ============================================
# 主流程
# ============================================
def main():
    parser = argparse.ArgumentParser(description="把词表、义位与词间关系灌入 MySQL")
    parser.add_argument("--dry-run", action="store_true", help="只解析与构建图谱，不写数据库")
    parser.add_argument("--if-empty", action="store_true",
                        help="仅当 definitions 表为空时才写入（容器首启自动灌库用）")
    args = parser.parse_args()

    # --- 解析三个来源 ---
    levin = load_levin_table()
    print(f"Levin 筛选表: {len(levin)} 个动词")

    db = DictionaryDB()
    if not db.available:
        print("⚠️  data/dictionary.db 不存在，释义将全部退回旧词库 / 英文缓存")
    oxford = load_oxford_cache()
    legacy = load_legacy_library()

    entries = build_entries(levin, oxford, db, legacy)
    audit = audit_coverage(entries)

    print(f"dictionary.db 命中: {audit['in_dictionary_db']}/{audit['total']} "
          f"({audit['dictionary_原文率']}%)，其中 {audit['with_senses']} 条带义位明细")
    print("释义来源分布:")
    for src, n in sorted(audit["by_source"].items(), key=lambda x: -x[1]):
        print(f"    {src:<18} {n:>4}  ({n / audit['total'] * 100:.1f}%)")

    rejects = load_rejected_lemmas()
    print(f"候选表剔除词: {len(rejects)} 个（不进词表，文档附录会列出原因）")

    pairs, clusters = build_synonym_pairs(entries)
    total_edges = sum(len(v) * (len(v) - 1) // 2 for v in clusters.values())
    print(f"次类簇: {len(clusters)} 个  ->  词间近义关系: {len(pairs)} 条")
    if len(pairs) != total_edges:
        print(f"⚠️  边数与完全图理论值不符: {len(pairs)} != {total_edges}")

    # --- 词间关系图谱（本地产物）---
    graph = build_word_graph(entries, clusters, pairs)
    with open(WORD_GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    print(f"已写出词间关系图谱: {os.path.relpath(WORD_GRAPH_PATH, ROOT)}")

    if args.dry_run:
        print("--dry-run：跳过数据库写入")
        return 0

    if not init_database(max_retries=3, retry_delay=2.0):
        print("❌ MySQL 不可用，无法导入。请检查 MYSQL_HOST / config/config.yaml",
              file=sys.stderr)
        return 1

    if args.if_empty:
        existing = definitions_count()
        if existing > 0:
            print(f"definitions 已有 {existing} 行，--if-empty 跳过写入")
            return 0
        print("definitions 为空，开始首次灌库")

    # 分类体系换了一套（旧 25 个 sub_cat → Levin 12 个次类），旧的簇与边必须整体重建。
    removed = clear_all_word_data()
    print("已清空词表数据（保留 feedbacks / usage_logs）: "
          + ", ".join(f"{k}={v}" for k, v in removed.items()))

    stats = seed_database(entries, pairs, clusters)
    print(f"word_clusters:  {stats['clusters']} 个")
    print(f"definitions:    写入/更新 {stats['definitions']}/{len(entries)}")
    print(f"word_senses:    {stats['senses']} 条义位")
    print(f"word_relations: {stats['relations']} 条（{len(pairs)} 对簇内完全图边）")

    # --- 校验 ---
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM definitions")
        n_defs = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM word_clusters")
        n_clusters = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM word_relations")
        n_rel = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM word_senses")
        n_senses = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM v_cluster_complete_graph")
        n_view = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM word_clusters WHERE size < 1")
        n_orphan = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM feedbacks")
        n_fb = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM usage_logs")
        n_log = cur.fetchone()["n"]

    print(f"库内合计: definitions={n_defs}, word_clusters={n_clusters}, "
          f"word_senses={n_senses}, word_relations={n_rel}")
    print(f"一致性核对: 视图推导的完全图边数={n_view} "
          f"({'一致 ✅' if n_view == n_rel else '不一致 ❌'})")
    print(f"空簇: {n_orphan}（应为 0）")
    print(f"用户数据保留: feedbacks={n_fb}, usage_logs={n_log}")

    # --- 抽样：词间关系可查（度数应等于 簇大小 - 1）---
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT d.verb, c.label AS cluster_label, c.size AS cluster_size,
                   COUNT(r.id) AS relatives
            FROM definitions d
            LEFT JOIN word_clusters c ON c.id = d.cluster_id
            LEFT JOIN word_relations r
                   ON r.verb_a_id = d.id OR r.verb_b_id = d.id
            GROUP BY d.id, d.verb, c.label, c.size
            ORDER BY relatives DESC
            LIMIT 5
        """)
        print("关系最多的词 (度数应 = 簇大小-1):")
        for r in cur.fetchall():
            print(f"    {r['verb']:<12} 簇={r['cluster_label']:<24} "
                  f"size={r['cluster_size']:>3} 度数={r['relatives']:>3}")

    # --- 抽样：义位与标注 ---
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT d.verb, d.definition_source, d.sense_count,
                   d.image_schema, d.alignment, d.needs_review,
                   COUNT(s.id) AS senses
            FROM definitions d
            LEFT JOIN word_senses s ON s.definition_id = d.id
            GROUP BY d.id, d.verb, d.definition_source, d.sense_count,
                     d.image_schema, d.alignment, d.needs_review
            ORDER BY senses DESC, d.verb
            LIMIT 5
        """)
        print("义位最多的词:")
        for r in cur.fetchall():
            print(f"    {r['verb']:<12} 义位={r['senses']:>3} "
                  f"来源={r['definition_source']:<16} 图式={r['image_schema'] or '-':<8} "
                  f"对齐={r['alignment'] or '-':<6} 待复核={r['needs_review']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
