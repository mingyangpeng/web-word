#!/usr/bin/env bash
# repair.sh —— 检测并修复现有部署的问题。
#
# 用法：
#     ./repair.sh           只检测：全量体检报告 + 逐表核对，不改任何东西
#     ./repair.sh --fix     检测 + 自动修复（以下动作全部幂等）：
#                           - MySQL 未运行 → 启动（空目录自动初始化）
#                           - 账号不可用 → 重新建库授权
#                           - dictionary.db 缺失 → 分卷重组
#                           - 22 张表行数低于验收基线 → 重跑对应灌库步骤
#     ./repair.sh --fix --force-reload
#                           在 --fix 基础上强制全量重灌（各 loader 不带
#                           --if-empty，先清后灌；部分灌入的表由此补齐）
#
# 体检项与 ./start.sh doctor 相同（scripts/env_doctor.py），本脚本额外做
# 「检测 → 修复 → 复检」闭环。
set -euo pipefail
cd "$(dirname "$0")"

FIX=0
FORCE_RELOAD=0
for arg in "$@"; do
  case "$arg" in
    --fix)          FIX=1 ;;
    --force-reload) FORCE_RELOAD=1 ;;
    *) echo "未知参数: ${arg}（用法: ./repair.sh [--fix] [--force-reload]）" >&2; exit 2 ;;
  esac
done
[ $FORCE_RELOAD -eq 1 ] && [ $FIX -eq 0 ] && \
  { echo "--force-reload 需与 --fix 搭配（单独使用无修复动作）" >&2; exit 2; }

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

  if ! "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" \
       -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1" "$DB_NAME" >/dev/null 2>&1; then
    echo "[fix] 应用账号不可用 → 重新建库授权..."
    grant_if_needed || true
  fi

  if [ ! -f data/dictionary.db ] && ls data/dictionary.db.part* >/dev/null 2>&1; then
    echo "[fix] dictionary.db 缺失 → 分卷重组..."
    # RV9-6：重组失败如实报告 + 重下指引（复检会兜底上报，但这里就讲清楚）
    reassemble_dictionary_db \
      || echo "  ⚠ 分卷重组失败 —— 修复: git checkout HEAD -- 'data/dictionary.db.part*' 后重跑"
  fi

  echo "[fix] 重灌低于基线的表（--if-empty 幂等，已有数据的表自动跳过）..."
  if [ $FORCE_RELOAD -eq 1 ]; then
    # RV9-9：部分灌入的表 --if-empty 修不了（非空即跳过），强制全量重灌
    echo "[fix] --force-reload：各 loader 不带 --if-empty 全量重灌（先清后灌）..."
    run_all_loaders --force-reload || true
  else
    run_all_loaders || true
  fi

  echo "------------------------------------------------------"
  echo " 复检"
fi

# ---------- 3. 复检 ----------
env_ok=0
if python3 scripts/env_doctor.py --quiet; then
  env_ok=1
  echo " ✅ 环境与数据体检通过"
else
  echo " ⚠ 环境体检有未过项 —— 跑 ./start doctor 看全量报告"
fi

# ---------- 4. 论文声明核对（53 项断言，投稿前必过）----------
# 两篇论文的全部定量声明都应能从库复现 —— 数据变更后最易漂移的就是它们。
# （断言数 53 与 scripts/verify_paper_claims.py 末尾自报的
#   「核对完成：53 通过 / 0 不符」口径一致 —— 含表 4-2 逐格循环展开。）
echo "------------------------------------------------------"
echo " 论文声明核对（papers/P3 + docs/paper 期刊论文，53 项断言）"
# 连接参数随 .env（load_env 已导出）—— 不再硬编码 127.0.0.1 静默覆盖（RV8-4 同型）
if python3 scripts/verify_paper_claims.py; then
  echo " ✅ 论文数字与库一致"
else
  echo " ⚠ 论文声明与库不一致 —— 若数据变更属预期，同步修改论文；"
  echo "   否则运行 ./repair.sh --fix 重灌数据后复查"
  env_ok=0
fi

echo "======================================================"
if [ $env_ok -eq 1 ]; then
  echo " ✅ 环境与数据全部正常"
  echo "    网页未启动则运行 ./start.sh"
  exit 0
fi
echo " ⚠ 仍有未过项 —— 跑 ./start doctor 看全量报告与修复指引"
echo "======================================================"
exit 1
