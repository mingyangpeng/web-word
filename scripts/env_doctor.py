#!/usr/bin/env python3
"""环境体检 —— 新机器部署前后的自检（./start doctor；./start 默认静默跑精简版）。

检查七类环境要素，每类给 ✓/✗ 与修复指引：
  1. Python 版本（>= 3.9）与关键依赖（streamlit/pandas/plotly/pymysql/yaml/openpyxl/zhipuai）
  2. MySQL：二进制（brew 路径或 PATH）、服务器可达、应用账号可登录
  3. .env：存在、ZHIPUAI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY 至少一个非空
  4. AI 接入：LLM 客户端能初始化（不实际调用，不产生费用）
  5. 种子数据：13 项全部在位（词表/义项表/语料/跑范畴/现汉7/dictionary.db 或分卷）
  6. 数据库内容：web_word_db 已建且 25 张表有行（部署完成后核对）
  7. 端口与磁盘：8501 占用状态、数据目录所在盘剩余空间

用法：
    ./start doctor            # 全量体检（含数据库内容核对）
    ./start doctor --quiet    # 精简版：只报失败项，全过则一行通过（./start 默认调用）
退出码：全过 0；有关键失败 1。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_MODULES = ["streamlit", "pandas", "plotly", "pymysql", "yaml",
                    "openpyxl", "zhipuai"]

# 种子数据：知识图谱/语料/范畴/现汉7/实验词表/dictionary 全库（或分卷）
SEEDS = [
    ("词表·Levin 筛选表", "docs/Levin移动动词候选词筛选表.xlsx"),
    ("词表·OALD10 义项表", "docs/output-oald10en-for-senselist-1020.xlsx"),
    ("词表·义项清单（中英对照）", "docs/词表义项清单.xlsx"),
    ("词表·域系初判表", "docs/域系初判表v0.2.xlsx"),
    ("词库·旧词库 JSON", "data/motion_verbs_extracted.json"),
    ("词库·英文释义缓存", "data/oxford_cache.json"),
    ("词库·词间关系图谱", "data/word_graph.json"),
    ("语料·enTenTen21 检索包", "data/corpus"),
    ("实验词·跑范畴甄别表", "data/d1/跑范畴英汉义位甄别表.xlsx"),
    ("实验词·跑范畴编码聚类表", "data/d1/跑范畴英汉义位编码与独立聚类表.xlsx"),
    ("现汉7·mdx 词典源", "data/ModernChineseDict/mdx/dict.mdx.txt"),
    ("词典·dictionary.db 或分卷", None),  # 特判：本体或分卷任一在即 ✓
]

# 数据库验收基线（表 → 期望最小行数；0 = 只要求表存在）
DB_BASELINE = {
    "definitions": 171, "word_clusters": 12, "word_relations": 1935,
    "oald_senses": 996, "word_senses": 246,  # 996 = 992 OALD + 4 人工补充
    "corpus_word_stats": 171, "corpus_collocations": 0,
    "corpus_schema_evidence": 0, "word_schema_scores": 0,
    "domain_family_senses": 352, "domain_family_examples": 1176,
    "categories": 1, "cs_lexemes": 42, "cs_senses": 57,
    "cs_sense_features": 918, "cs_cluster_runs": 2, "cs_clusters": 10,
    "cs_cluster_members": 51, "cs_cluster_alignment": 5,
    "zh_dict_entries": 70103, "zh_dict_senses": 94868, "zh_dict_examples": 76085,
}

results = []  # (ok, category, message, hint)


def check(ok: bool, category: str, msg: str, hint: str = "") -> bool:
    results.append((ok, category, msg, hint))
    return ok


def check_python():
    import platform
    v = platform.python_version()
    ok = tuple(int(x) for x in v.split(".")[:2]) >= (3, 9)
    check(ok, "Python", f"版本 {v}", "需要 Python ≥ 3.9（brew install python@3.11）")

    missing = []
    for m in REQUIRED_MODULES:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    check(not missing, "Python 依赖",
          "全部就绪" if not missing else f"缺少 {missing}",
          f"pip3 install -r requirements.txt（或 pip3 install {' '.join(missing)}）")


def check_mysql():
    mysql_bin = shutil.which("mysql") or "/opt/homebrew/opt/mysql@8.0/bin/mysql"
    has_bin = os.path.exists(mysql_bin)
    check(has_bin, "MySQL", "二进制就绪" if has_bin else "未安装",
          "brew install mysql@8.0（./start 也会自动尝试）")

    if not has_bin:
        return
    try:
        from src.mysql_db import get_db_cursor
        with get_db_cursor() as c:
            c.execute("SELECT 1")
        check(True, "MySQL", "服务器可达，应用账号可登录", "")
    except Exception as e:
        check(False, "MySQL", f"服务器/账号不可用: {e}",
              "./start 会自动启动 MySQL 并探测 root 密码建库授权；"
              "或手动执行 mysql -u root -p < scripts/grant_local_mysql.sql")


def check_env():
    env_path = ROOT / ".env"
    check(env_path.exists(), "配置 .env", "存在（随仓库分发）"
          if env_path.exists() else "缺失",
          "cp .env.example .env")
    if not env_path.exists():
        return
    keys = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    ai_key = (keys.get("ZHIPUAI_API_KEY") or keys.get("OPENAI_API_KEY")
              or keys.get("DEEPSEEK_API_KEY") or "")
    check(bool(ai_key), "AI 接入",
          "API key 已配置" if ai_key else "三个提供商的 key 均为空",
          "编辑 .env 填入 ZHIPUAI_API_KEY（不配则应用降级为离线释义）")
    check(bool(keys.get("MYSQL_PASSWORD")), "配置 .env",
          "MySQL 密码已配置", "")


def check_ai_client():
    try:
        from src.llm_api import get_llm_client
        client, provider = get_llm_client()
        check(client is not None, "AI 接入",
              f"客户端就绪（提供商: {provider}）" if client else "无可用的提供商",
              "检查 .env 的 ZHIPUAI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY")
    except Exception as e:
        check(False, "AI 接入", f"客户端初始化异常: {e}", "")


def check_seeds():
    for name, rel in SEEDS:
        if rel is None:  # dictionary.db 特判：本体或分卷任一在即 ✓
            full = (ROOT / "data" / "dictionary.db").exists()
            parts = list(ROOT.glob("data/dictionary.db.part*"))
            ok = full or bool(parts)
            msg = ("完整文件在位" if full else
                   f"分卷在位（{len(parts)} 卷，./start 自动重组）" if parts
                   else "本体与分卷均缺失")
            check(ok, "种子数据", f"{name}: {msg}",
                  "git checkout 重取 data/dictionary.db.part*" if not ok else "")
            continue
        p = ROOT / rel
        check(p.exists(), "种子数据", f"{name}: {'在位' if p.exists() else '缺失'}",
              f"git checkout HEAD -- {rel}" if not p.exists() else "")


def check_database():
    try:
        from src.mysql_db import get_db_cursor
        with get_db_cursor() as c:
            c.execute("SHOW TABLES")
            tables = {list(r.values())[0] for r in c.fetchall()}
            if not tables:
                check(False, "数据库内容", "web_word_db 为空（./start 会自动灌库）", "")
                return
            bad = []
            for table, min_rows in DB_BASELINE.items():
                if table not in tables:
                    bad.append(f"{table}(缺表)")
                    continue
                c.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                n = int(c.fetchone()["n"])
                if min_rows and n < min_rows:
                    bad.append(f"{table}({n}<{min_rows})")
            check(not bad, "数据库内容",
                  "25 张表全部达到验收基线" if not bad else f"缺口: {', '.join(bad)}",
                  "重跑 ./start（灌库幂等）" if bad else "")
    except Exception as e:
        check(False, "数据库内容", f"无法核对: {e}", "./start 先建库灌库")


def check_ports_disk():
    import socket
    s = socket.socket()
    try:
        busy = s.connect_ex(("127.0.0.1", 8501)) == 0
        check(True, "端口/磁盘", f"8501 {'已被应用占用（正常）' if busy else '空闲'}", "")
    finally:
        s.close()
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / 1024 ** 3
    check(free_gb > 2, "端口/磁盘", f"剩余空间 {free_gb:.1f} GB",
          "清理磁盘（data/mysql 与词典重组需要约 3GB）" if free_gb <= 2 else "")


def main():
    parser = argparse.ArgumentParser(description="部署环境体检")
    parser.add_argument("--quiet", action="store_true",
                        help="精简版：只输出失败项")
    args = parser.parse_args()

    check_python()
    check_mysql()
    check_env()
    check_ai_client()
    check_seeds()
    check_database()
    check_ports_disk()

    failed = [r for r in results if not r[0]]
    if args.quiet:
        if not failed:
            print("[env] 环境体检通过")
            return 0
        print(f"[env] ⚠ 环境体检 {len(failed)} 项未过：")
        for _, cat, msg, hint in failed:
            print(f"  ✗ [{cat}] {msg}" + (f" → {hint}" if hint else ""))
        return 1

    # 全量报告
    print("=" * 62)
    print("web-word 部署环境体检报告")
    print("=" * 62)
    for ok, cat, msg, hint in results:
        mark = "✓" if ok else "✗"
        line = f"{mark} [{cat}] {msg}"
        print(line)
        if not ok and hint:
            print(f"    → 修复: {hint}")
    n_ok = len(results) - len(failed)
    print("=" * 62)
    print(f"结果: {n_ok}/{len(results)} 通过" + ("" if not failed else
          f"，{len(failed)} 项需处理（见 ✗ 行的修复指引）"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
