#!/usr/bin/env bash
# develop.sh —— 部署脚本：环境 + MySQL + 全量数据，一次准备到位。
#
# 新机器部署（git clone 之后）：
#     ./develop.sh           # 部署环境与数据库（不动网页）
#     ./start.sh             # 再启动网页
#
# 做什么（全部幂等，重复执行安全）：
#   1. 加载 .env（已随仓库分发）
#   2. Python 依赖自检 + 自动安装
#   3. MySQL 二进制自动安装（无则 brew install mysql@8.0）
#   4. 启动 MySQL（空数据目录自动初始化）+ 建库授权（root 密码自动探测）
#   5. 重组 dictionary.db（197MB 分卷 + sha256 校验）
#   6. 八步灌库（词库/语料/范畴深挖/域系初判/域系增强/LLM 初筛/现汉7）
#   7. 环境体检（22 张表验收基线，与 scripts/env_doctor.py DB_BASELINE 对齐）
#
# 注意：本脚本不启动网页 —— 数据就绪后运行 ./start.sh。
set -euo pipefail
cd "$(dirname "$0")"

# shellcheck disable=SC1091
source scripts/lib_deploy.sh

echo "======================================================"
echo " web-word 部署（环境 + 数据库 + 全量数据）"
echo "======================================================"

load_env
check_deps || true                    # 失败不中断：先装 MySQL，应用端自检再拦
ensure_mysql_binary || exit 1
start_mysqld || exit 1
grant_if_needed || exit 1
# RV9-6：重组失败（sha256 不符/合并中断）不许吞 —— 带着坏词典打 ✅ 完成横幅
# 就是「损坏部署无人知」；失败即退出并给重下指引。
reassemble_dictionary_db || {
  echo "  修复: git checkout HEAD -- 'data/dictionary.db.part*' 重取分卷后重跑"
  exit 1
}

echo "------------------------------------------------------"
echo " 灌入全量数据（幂等，已有数据的表自动跳过）"
# RV9-5：run_all_loaders 在 set -e 下非零返回会直接中断脚本 —— 体检步骤
# 被跳过且无任何指引。失败时给出指引，让体检决定成败（缺口如实上报）。
if ! run_all_loaders; then
  echo "⚠ 有灌库步骤失败 —— 继续体检定位缺口；./repair.sh --fix 可针对性重灌"
fi

echo "------------------------------------------------------"
echo " 环境体检"
if python3 scripts/env_doctor.py --quiet; then
  echo "======================================================"
  echo " ✅ 部署完成 —— 运行 ./start.sh 启动网页"
  echo "======================================================"
  exit 0
fi
echo " 体检有未过项，跑 ./repair.sh --fix 自动修复，或 ./start doctor 看全量报告"
exit 1
