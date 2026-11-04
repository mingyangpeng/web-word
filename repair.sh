#!/usr/bin/env bash
# repair.sh —— 检测并修复现有部署的问题。
#
# 用法：
#     ./repair.sh           只检测：全量体检报告 + 逐表核对，不改任何东西
#     ./repair.sh --fix     检测 + 自动修复（以下动作全部幂等）：
#                           - MySQL 未运行 → 启动（空目录自动初始化）
#                           - 账号不可用 → 重新建库授权
#                           - dictionary.db 缺失 → 分卷重组
#                           - 25 张表行数低于验收基线 → 重跑对应灌库步骤
#
# 体检项与 ./start.sh doctor 相同（scripts/env_doctor.py），本脚本额外做
# 「检测 → 修复 → 复检」闭环。
set -euo pipefail
cd "$(dirname "$0")"

FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

# shellcheck disable=SC1091
source scripts/lib_deploy.sh

load_env

echo "======================================================"
echo " web-word 问题检测（$([ $FIX -eq 1 ] && echo '检测 + 自动修复' || echo '仅检测，加 --fix 启用自动修复'))"
echo "======================================================"

# ---------- 1. 全量体检 ----------
python3 scripts/env_doctor.py || true

# ---------- 2. 逐项修复（--fix 时）----------
if [ $FIX -eq 1 ]; then
  echo "------------------------------------------------------"
  echo " 自动修复（全部幂等）"

  ensure_mysql_binary || true

  if ! db_up; then
    echo "[fix] MySQL 未运行 → 启动..."
    start_mysqld || echo "  ⚠ MySQL 仍不可用，请看 $LOGDIR/mysqld.err"
  fi

  if ! "$MYSQL_BIN/mysql" --protocol=tcp -h 127.0.0.1 -u web_word_user -pwebword123 \
       -e "SELECT 1" web_word_db >/dev/null 2>&1; then
    echo "[fix] 应用账号不可用 → 重新建库授权..."
    grant_if_needed || true
  fi

  if [ ! -f data/dictionary.db ] && ls data/dictionary.db.part* >/dev/null 2>&1; then
    echo "[fix] dictionary.db 缺失 → 分卷重组..."
    reassemble_dictionary_db || true
  fi

  echo "[fix] 重灌低于基线的表（--if-empty 幂等，已有数据的表自动跳过）..."
  run_all_loaders || true

  echo "------------------------------------------------------"
  echo " 复检"
fi

# ---------- 3. 复检 ----------
if python3 scripts/env_doctor.py --quiet; then
  echo "======================================================"
  echo " ✅ 环境与数据全部正常"
  echo "    网页未启动则运行 ./start.sh"
  echo "======================================================"
  exit 0
fi
echo "======================================================"
echo " ⚠ 仍有未过项 —— 跑 ./start doctor 看全量报告与修复指引"
echo "======================================================"
exit 1
