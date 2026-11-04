#!/usr/bin/env python3
"""论文声明 ↔ 数据库核对 —— papers/P3 与 docs/paper/期刊论文的定量声明复现。

把两篇论文的全部定量声明固化为断言，投稿前/数据变更后随时重跑：
    MYSQL_HOST=127.0.0.1 python3 scripts/verify_paper_claims.py

核对清单（25+ 项，全部应输出 ✓）：
  [规模] 171 词 / 12 次类 / 1935 关系 / 996 义位 = 992 OALD + 4 人工补充
  [域系] 352 条（方式 264 / 路径 62 / 互动 26）/ 12 系
  [甄别] 汉语保留 14 / 边缘 5 / 剔除 6；标注 附逃离 9 / 附追逐 1 / 附冲撞 1
  [编码] 918 格 = 51 义位 × 18 特征 = 765(P/M/C) + 153(A)
  [聚类] 英 5 簇 / 汉 5 簇 / cophenetic 0.825·0.795 / k=5
  [对齐] 完全 1 / 部分 3 / 零 1 / 方式奔跑 d=0.045 / 英方式 17 条(53%) /
         汉方式 8 条(42%) / 英逃离 6 条
  [表4-2] 期刊论文 15 维均值对比逐格复现（含差值最大三特征 P1>P2/P3）
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mysql_db import get_db_cursor  # noqa: E402

CODES = ["P1", "P2", "P3", "P4", "P5", "M1a", "M1b", "M1c", "M1d",
         "M2", "M3a", "M3b", "M3c", "M3d", "C1"]

# 期刊论文表 4-2 的 15 维均值（/2 归一）与 |差|/2 —— 逐格断言
TABLE_4_2 = {
    "P1": (0.078, 0.211), "P2": (0.125, 0.000), "P3": (0.125, 0.000),
    "P4": (0.000, 0.000), "P5": (0.406, 0.395), "M1a": (0.422, 0.447),
    "M1b": (0.312, 0.368), "M1c": (0.031, 0.053), "M1d": (0.031, 0.000),
    "M2": (0.859, 0.842), "M3a": (0.500, 0.500), "M3b": (0.000, 0.000),
    "M3c": (0.000, 0.000), "M3d": (0.000, 0.000), "C1": (0.812, 0.763),
}

passed, failed = 0, 0


def ck(name, actual, expect, tol=None):
    global passed, failed
    if isinstance(actual, bool) and isinstance(expect, bool):
        ok = actual is expect
    else:
        ok = (abs(actual - expect) <= tol) if tol is not None else (actual == expect)
    passed, failed = passed + ok, failed + (not ok)
    print(f"{'✓' if ok else '✗'} {name}: 库={actual} / 声明={expect}")


def main() -> int:
    with get_db_cursor() as c:
        # ---------- 规模 ----------
        c.execute("SELECT COUNT(*) n FROM definitions")
        ck("词库 171 词", c.fetchone()["n"], 171)
        c.execute("SELECT COUNT(*) n FROM word_clusters")
        ck("12 次类", c.fetchone()["n"], 12)
        c.execute("SELECT COUNT(*) n FROM word_relations")
        ck("词间关系 1935", c.fetchone()["n"], 1935)
        c.execute("SELECT COUNT(*) n FROM oald_senses WHERE source='OALD10'")
        ck("OALD 来源义项 992", c.fetchone()["n"], 992)
        c.execute("SELECT COUNT(*) n FROM oald_senses WHERE source='人工补充'")
        ck("人工补充 4 条", c.fetchone()["n"], 4)
        c.execute("SELECT COUNT(*) n FROM oald_senses")
        ck("研究词表义位 996 = 992 + 4", c.fetchone()["n"], 996)

        # ---------- 域系 ----------
        c.execute("SELECT COUNT(*) n FROM domain_family_senses")
        ck("域系初判 352 条", c.fetchone()["n"], 352)
        c.execute("SELECT domain, COUNT(*) n FROM domain_family_senses "
                  "GROUP BY domain")
        dom = {r["domain"]: r["n"] for r in c.fetchall()}
        ck("方式位移域 264", dom.get("方式位移域", 0), 264)
        ck("路径位移域 62", dom.get("路径位移域", 0), 62)
        ck("互动位移域 26", dom.get("互动位移域", 0), 26)
        c.execute("SELECT COUNT(DISTINCT family) n FROM domain_family_senses")
        ck("12 系", c.fetchone()["n"], 12)

        # ---------- 甄别与标注 ----------
        c.execute("""SELECT s.status, COUNT(*) n FROM cs_senses s
                     JOIN cs_lexemes l ON s.lexeme_id = l.id
                     WHERE l.language='zh' GROUP BY s.status""")
        st = {r["status"]: r["n"] for r in c.fetchall()}
        ck("汉语判定 保留14/边缘5/剔除6",
           (st.get("保留", 0), st.get("边缘", 0), st.get("剔除", 0)), (14, 5, 6))
        c.execute("""SELECT s.tag, COUNT(*) n FROM cs_senses s
                     JOIN cs_lexemes l ON s.lexeme_id = l.id
                     WHERE l.language='zh' AND s.tag IS NOT NULL AND s.tag != '无'
                     GROUP BY s.tag""")
        tags = {r["tag"]: r["n"] for r in c.fetchall()}
        ck("标注 附逃离9/附追逐1/附冲撞1",
           (tags.get("附逃离", 0), tags.get("附追逐", 0), tags.get("附冲撞", 0)),
           (9, 1, 1))

        # ---------- 编码矩阵 ----------
        c.execute("SELECT COUNT(*) n FROM cs_sense_features")
        ck("编码 918 格 = 51×18", c.fetchone()["n"], 918)
        c.execute("SELECT COUNT(*) n FROM cs_sense_features WHERE in_clustering=1")
        ck("P/M/C 765 = 51×15", c.fetchone()["n"], 765)
        c.execute("SELECT COUNT(*) n FROM cs_sense_features WHERE in_clustering=0")
        ck("A 系 153 = 51×3", c.fetchone()["n"], 153)
        c.execute("""SELECT l.language, COUNT(*) n FROM cs_senses s
                     JOIN cs_lexemes l ON s.lexeme_id = l.id GROUP BY l.language""")
        sn = {r["language"]: r["n"] for r in c.fetchall()}
        ck("英 32 义位", sn.get("en", 0), 32)
        ck("汉 25 义位条目", sn.get("zh", 0), 25)
        c.execute("""SELECT l.language, COUNT(*) n FROM cs_lexemes l
                     GROUP BY l.language""")
        ln = {r["language"]: r["n"] for r in c.fetchall()}
        ck("英 23 词", ln.get("en", 0), 23)
        ck("汉 19 词条", ln.get("zh", 0), 19)

        # ---------- 聚类 ----------
        for lang, exp_cop in (("en", 0.825), ("zh", 0.795)):
            c.execute("""SELECT cophenetic FROM cs_cluster_runs
                         WHERE language=%s""", (lang,))
            ck(f"{lang} cophenetic {exp_cop}",
               float(c.fetchone()["cophenetic"]), exp_cop, tol=1e-6)
        for lang, exp_clusters in (("en", 5), ("zh", 5)):
            c.execute("""SELECT COUNT(*) n FROM cs_clusters c
                         JOIN cs_cluster_runs r ON c.run_id = r.id
                         WHERE r.language=%s""", (lang,))
            ck(f"{lang} {exp_clusters} 簇", c.fetchone()["n"], exp_clusters)
        c.execute("SELECT verdict, COUNT(*) n FROM cs_cluster_alignment "
                  "GROUP BY verdict")
        vd = {r["verdict"]: r["n"] for r in c.fetchall()}
        ck("对齐判定 完全1/部分3/零1",
           (vd.get("完全对齐", 0), vd.get("部分对齐", 0), vd.get("零对齐", 0)),
           (1, 3, 1))
        c.execute("""SELECT a.gower_distance FROM cs_cluster_alignment a
                     JOIN cs_clusters en ON a.en_cluster_id = en.id
                     WHERE a.verdict='完全对齐'""")
        ck("方式奔跑 d=0.045", float(c.fetchone()["gower_distance"]), 0.045,
           tol=1e-6)
        c.execute("""SELECT r.language, c.size FROM cs_clusters c
                     JOIN cs_cluster_runs r ON c.run_id = r.id
                     WHERE c.name LIKE '方式奔跑%'""")
        for r in c.fetchall():
            exp = (17, 53) if r["language"] == "en" else (8, 42)
            denom = 32 if r["language"] == "en" else 19
            ck(f"{r['language']} 方式奔跑 {exp[0]} 条（{exp[1]}%）",
               (r["size"], round(r["size"] / denom * 100)), exp)
        c.execute("""SELECT COUNT(*) n FROM cs_cluster_members m
                     JOIN cs_clusters c ON m.cluster_id = c.id
                     JOIN cs_cluster_runs r ON c.run_id = r.id
                     WHERE r.language='en' AND c.cluster_no=5""")
        ck("英逃离脱离类 6 条", c.fetchone()["n"], 6)

        # ---------- 期刊论文表 4-2：15 维均值逐格 ----------
        means = {}
        for lang in ("en", "zh"):
            fmt = ",".join(["%s"] * len(CODES))
            c.execute(f"""SELECT f.feature_code, AVG(f.value)/2 AS norm
                          FROM cs_sense_features f
                          JOIN cs_senses s ON f.sense_id = s.id
                          JOIN cs_lexemes l ON s.lexeme_id = l.id
                          WHERE l.language = %s AND f.feature_code IN ({fmt})
                          GROUP BY f.feature_code""", (lang, *CODES))
            means[lang] = {r["feature_code"]: float(r["norm"])
                           for r in c.fetchall()}
        for code, (exp_en, exp_zh) in TABLE_4_2.items():
            actual = (round(means["en"].get(code, 0), 3),
                      round(means["zh"].get(code, 0), 3))
            ok = (abs(actual[0] - exp_en) <= 5e-4
                  and abs(actual[1] - exp_zh) <= 5e-4)
            ck(f"表4-2 {code} 英 {exp_en} / 汉 {exp_zh}: 库={actual}",
               ok, True)
        diffs = sorted(
            ((abs(means["en"].get(k, 0) - means["zh"].get(k, 0)), k)
             for k in CODES), reverse=True)
        ck("差值最大三特征 P1 > P2/P3",
           [k for _, k in diffs[:3]], ["P1", "P3", "P2"])

    print(f"\n核对完成：{passed} 通过 / {failed} 不符")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
