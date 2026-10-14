#!/usr/bin/env python3
"""从 OALD10（词表义项清单）+ wordsketch（output/05_原始数据）更新域—系初判数据。

更新两块：
  ① OALD10 例句全量补入：domain_family_examples 当前只有首条例句（400 行），
     词表义项明细的例句列是 OALD 全部例句（352 义位共 1050 条）——全量补入，
     dictionary.db 已有翻译的义位保留双语对齐，其余为 OALD10 来源（翻译待补）；
     主表 example 冗余列同步刷新。
  ② wordsketch 语料证据关联：主表新增 freq（enTenTen21 词目频次）、
     schema_scores（四图式重心得分 JSON）——127 词有数据，35 个路径/互动词
     待 Sketch Engine 检索后补（freq NULL = 未检索）。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/update_domain_family_data.py
"""

import glob
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymysql  # noqa: E402
import yaml  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

WL_XLSX = ROOT / "docs" / "词表义项清单.xlsx"
WSKETCH_DIR = ROOT / "output" / "05_原始数据" / "wsketch_full"
SCHEMA_EVIDENCE = ROOT / "output" / "06_图式提取结果" / "schema_evidence"


def _conn():
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text())["database"]["mysql"]
    host = cfg["host"] if cfg["host"] != "mysql" else "127.0.0.1"
    return pymysql.connect(host=host, port=cfg["port"], user=cfg["user"],
                           password=cfg["password"], database=cfg["database"],
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def load_oald_examples():
    """词表义项明细 → {(word, sense_num): [例句, ...]}（OALD10 全部例句）。"""
    wb = load_workbook(WL_XLSX, read_only=True)
    ws = wb["义项明细"]
    idx = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[0] or r[1] is None:
            continue
        key = (str(r[0]).strip(), int(r[1]))
        exs = [e for e in str(r[7] or "").split("\n") if e.strip()]
        if exs:
            idx[key] = exs
    wb.close()
    return idx


def load_cn_examples():
    """中英对照义位 → {(word, sense_num): (中文释义, [英例], [中例])}。"""
    wb = load_workbook(WL_XLSX, read_only=True)
    ws = wb["中英对照义位"]
    idx = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[0] or r[1] is None:
            continue
        key = (str(r[0]).strip(), int(r[1]))
        exs = [e for e in str(r[6] or "").split("\n") if e.strip()]
        cn_exs = [e for e in str(r[7] or "").split("\n") if e.strip()]
        idx[key] = (str(r[2] or "").strip() or None, exs, cn_exs)
    wb.close()
    return idx


def load_wsketch():
    """wsketch_full JSON → {verb: freq}；schema_evidence → {verb: 四图式得分}。"""
    freq = {}
    for f in glob.glob(str(WSKETCH_DIR / "*.json")):
        verb = os.path.basename(f).replace(".json", "")
        try:
            d = json.load(open(f, encoding="utf-8"))
            freq[verb] = int(d.get("freq") or 0)
        except (json.JSONDecodeError, OSError):
            continue
    scores = {}
    for f in glob.glob(str(SCHEMA_EVIDENCE / "*.json")):
        verb = os.path.basename(f).replace(".json", "")
        try:
            d = json.load(open(f, encoding="utf-8"))
            # d: {图式名: {prominence_score, ...}} 或带包装——兼容两种
            items = d.get("schemas") or {}
            scores[verb] = {
                name: round(float(v.get("prominence_score") or 0), 2)
                for name, v in items.items()
                if isinstance(v, dict)
            }
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return freq, scores


def main() -> int:
    oald_ex = load_oald_examples()
    cn_idx = load_cn_examples()
    ws_freq, ws_scores = load_wsketch()
    print(f"OALD 例句义位: {len(oald_ex)} | dictionary.db 双语: {len(cn_idx)} | "
          f"wordsketch 频次: {len(ws_freq)} 词 | 图式得分: {len(ws_scores)} 词")

    conn = _conn()
    today = date.today()
    n_ex_new, n_ex_kept, n_freq, n_scores, n_first = 0, 0, 0, 0, 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT word, sense_num FROM domain_family_senses ORDER BY word, sense_num")
            senses = cur.fetchall()

            for w, n in [(r["word"], r["sense_num"]) for r in senses]:
                # ---- ① 例句全量补入 ----
                # 例句合并：dictionary.db 双语例句在前（带翻译），OALD 补充在后（无翻译），
                # 英文文本去重（两来源首条常相同）
                cn = cn_idx.get((w, n))
                oald = oald_ex.get((w, n), [])
                examples, seen = [], set()
                if cn and cn[1]:
                    for en, zh in zip(cn[1], cn[2]):
                        if en not in seen:
                            examples.append((en, zh, "dictionary.db"))
                            seen.add(en)
                for e in oald:
                    if e not in seen:
                        examples.append((e, None, "OALD10"))
                        seen.add(e)

                if examples:
                    # 先清该义位旧例句，再全量写入（幂等）
                    cur.execute(
                        "DELETE FROM domain_family_examples WHERE word=%s AND sense_num=%s",
                        (w, n))
                    for i, (en, zh, src) in enumerate(examples, start=1):
                        cur.execute(
                            """INSERT INTO domain_family_examples
                               (word, sense_num, ex_num, example_en, example_cn, source)
                               VALUES (%s, %s, %s, %s, %s, %s)""",
                            (w, n, i, en, zh, src))
                        n_ex_new += 1
                    # 主表冗余首例句刷新
                    first = examples[0][0] if examples else None
                    cur.execute(
                        "UPDATE domain_family_senses SET example=%s WHERE word=%s AND sense_num=%s",
                        (first, w, n))
                    n_first += 1
                else:
                    n_ex_kept += 1

                # ---- ② wordsketch 证据关联 ----
                if w in ws_freq:
                    cur.execute(
                        "UPDATE domain_family_senses SET freq=%s WHERE word=%s AND sense_num=%s",
                        (ws_freq[w], w, n))
                    n_freq += 1
                if w in ws_scores:
                    cur.execute(
                        "UPDATE domain_family_senses SET schema_scores=%s "
                        "WHERE word=%s AND sense_num=%s",
                        (json.dumps(ws_scores[w], ensure_ascii=False), w, n))
                    n_scores += 1

        conn.commit()
    finally:
        conn.close()

    print(f"例句写入 {n_ex_new} 行（覆盖 {n_first} 义位，{n_ex_kept} 义位无例句保留空）")
    print(f"频次关联 {n_freq} 行 | 图式得分关联 {n_scores} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
