#!/usr/bin/env python3
"""把结构化的《现汉7》词典 JSON 灌入 MySQL 的 zh_dict_* 3 表。

数据链：data/ModernChineseDict/mdx/dict.mdx.txt
   → scripts/parse_modern_chinese_dict.py → data/zh_dict_senses.json → 本脚本。

用法：
    MYSQL_HOST=127.0.0.1 python3 scripts/load_zh_dict.py            # 全量替换
    MYSQL_HOST=127.0.0.1 python3 scripts/load_zh_dict.py --if-empty  # 未达就绪判据才灌入
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mysql_db, zh_dict  # noqa: E402

JSON_PATH = ROOT / "data" / "zh_dict_senses.json"


# ============================================
# --if-empty 就绪判据
# （P2 修复：旧判据「zh_dict_entries > 0」过松——实测 3307 测试库仅残留
#   6 行词条残骸即被判「已就绪」跳过，词典数据从此缺着没人补。
#   判据放 scripts 本地而非改 src/zh_dict.py：页面侧 zh_dict_ready 的
#   「有数据即用」口径与本脚本的「灌库前对账」口径用途不同，不互相绑死。）
# ============================================

def count_json_entries(path: Path = JSON_PATH) -> Optional[int]:
    """低成本统计结构化 JSON 的词条数（--if-empty 的对账锚点）。

    文件约 45MB 且 --if-empty 每次启动都探测，不值得整体 json.load（慢＋占
    内存）。生成器 parse_modern_chinese_dict.py 以 indent=1 落盘：每个词条
    对象的 "lemma" 键物理行形如「\\n  "lemma": …」（恰好两空格缩进）——
    senses 子对象的键缩进 4+ 空格不会误中，字符串值内的换行已被 JSON 转义成
    字面 \\n、不产生物理行首。故按物理行计数即精确词条数（已与 json.load
    全量解析对账：70103 == 70103）。
    缩进口径若变（生成器改格式）则计数为 0 → 返回 None，readiness 放弃
    对账、退回三表比例判据——宁可多灌一次（replace 幂等），不可误跳过。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    n = data.count(b'\n  "lemma":')
    return n if n > 0 else None


def zh_dict_readiness(counts: Dict[str, int],
                      expected_entries: Optional[int] = None) -> bool:
    """判定 zh_dict_* 三表是否「就绪」（--if-empty 的跳过判据）。纯函数。

    Args:
        counts: {"entries": n, "senses": n, "examples": n} 三表实际行数。
        expected_entries: data/zh_dict_senses.json 的词条数；拿不到传 None。

    判据三层，全部通过才算就绪——设计取向：宁可重灌（replace 先删后插、
    幂等），不可把残骸/半截灌入误判就绪：
      ① entries > 0 —— 三表全空 = 从未灌过；
      ② 子表对账：senses ≥ entries/2（向下取整，至少 1）且 examples > 0
        —— 残骸态的典型特征是「词条有行、子表空/畸少」；完整态
        senses/entries ≈ 1.35（现汉7：94868/70103），entries/2 是极宽松
        下界（全部单义项也应 senses == entries）；
      ③ 预期对账（JSON 可数时）：entries ≥ expected_entries —— 拦住
        「自洽残骸/半截灌入」：中断的灌入可能已写入几万词条＋成批义项例句
        （②的比例判据拦不住），只有和数据源词条数对账才识破。用严格 ≥ 而
        非容差：数据源再生成后词条数变化，本就该触发重灌刷新；DB 侧多于
        预期（人工补录等）则照常跳过、不碰存量。
    """
    entries = int(counts.get("entries") or 0)
    senses = int(counts.get("senses") or 0)
    examples = int(counts.get("examples") or 0)
    if entries <= 0:
        return False
    if senses < max(1, entries // 2) or examples <= 0:
        return False
    if expected_entries is not None and entries < expected_entries:
        return False
    return True


def probe_zh_dict_readiness() -> Dict[str, Any]:
    """采集就绪判据的输入：三表行数（DB）＋预期词条数（JSON 对账锚点）。

    DB 不可达时三表计数按全 0 口径返回（readiness 判 False → 继续走灌入
    流程，由 init_database/replace 报出真正的连接错误——与旧 zh_dict_ready
    的失败口径一致，不让 --if-empty 在连接异常时静默跳过）。
    """
    counts = {"entries": 0, "senses": 0, "examples": 0}
    try:
        stats = zh_dict.get_zh_dict_stats()
        counts = {k: int(stats.get(k) or 0) for k in counts}
    except Exception as e:  # noqa: BLE001
        print(f"zh_dict_* 三表计数查询失败（{e}）——按未就绪处理。")
    return {"counts": counts, "expected": count_json_entries()}


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入《现汉7》结构化词典")
    parser.add_argument("--if-empty", action="store_true",
                        help="仅当 zh_dict_* 未达就绪判据（三表对账＋预期词条数）"
                             "时写入；残骸/半截灌入也会重灌")
    args = parser.parse_args()

    if not JSON_PATH.exists():
        print(f"结构化 JSON 不存在: {JSON_PATH}")
        print("先运行: python3 scripts/parse_modern_chinese_dict.py")
        return 1

    if args.if_empty:
        probe = probe_zh_dict_readiness()
        c = probe["counts"]
        if zh_dict_readiness(c, probe["expected"]):
            print(f"zh_dict_* 已就绪（entries/senses/examples = "
                  f"{c['entries']}/{c['senses']}/{c['examples']}，"
                  f"预期词条 {probe['expected']}），跳过（--if-empty）。")
            return 0
        print(f"zh_dict_* 未达就绪判据（entries/senses/examples = "
              f"{c['entries']}/{c['senses']}/{c['examples']}，"
              f"预期词条 {probe['expected']}）——继续灌入。")

    with open(JSON_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    print(f"读入 {len(entries)} 个词条（读音条目）")

    if not mysql_db.init_database():
        print("数据库初始化失败。")
        return 1

    counts = zh_dict.replace_zh_dict(entries)
    print(f"已灌入: {counts}")

    # 校验：跑范畴 19 词条应全部可查
    ok = all(zh_dict.lookup_lemma(w) for w in
             ["跑", "奔跑", "奔驰", "驰骋", "逃逸"])
    print("抽查 跑/奔跑/奔驰/驰骋/逃逸:", "全部可查 ✓" if ok else "存在缺失 ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
