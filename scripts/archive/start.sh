#!/usr/bin/env bash
# start.sh —— 启动网页（Streamlit）。数据库未部署时给出明确指引。
#
# 用法：
#     ./start.sh           启动网页（幂等，已在运行则提示地址）
#     ./start.sh stop      停止网页与 MySQL
#     ./start.sh status    查看服务状态
#     ./start.sh doctor    环境全量体检
#
# 首次部署请先运行 ./develop.sh（环境 + 数据库 + 全量数据）；本脚本只负责
# 启动网页 —— 但若 MySQL 未运行会用已部署的数据目录拉起（不重复灌库）。
set -euo pipefail
cd "$(dirname "$0")"

# shellcheck disable=SC1091
source scripts/lib_deploy.sh

load_env

case "${1:-start}" in
  stop)   stop_all; exit 0 ;;
  status) status_all; exit 0 ;;
  doctor) python3 scripts/env_doctor.py "${@:2}"; exit $? ;;
esac

check_deps || true
ensure_mysql_binary || exit 1

# 数据目录空 = 从未部署过：指向 develop.sh，而不是在这里静默灌库
mkdir -p "$DATADIR"
if [ -z "$(ls -A "$DATADIR" 2>/dev/null)" ]; then
  echo "✗ 数据库尚未部署（data/mysql 为空）。请先运行："
  echo "    ./develop.sh     # 部署环境 + 数据库 + 全量数据（幂等）"
  echo "  然后再运行 ./start.sh"
  exit 1
fi

# RV9-6：分卷重组失败（sha256 不符/合并中断）= 词典数据不可信，不允许带病上线
reassemble_dictionary_db || {
  echo "  修复: git checkout HEAD -- 'data/dictionary.db.part*' 重取分卷后重跑"
  exit 1
}
start_mysqld || { echo "  仍失败可运行 ./repair.sh --fix 诊断修复"; exit 1; }
grant_if_needed || exit 1
# RV9-1：数据已灌探测 —— 初始化后中断（系统表在、基线表全空）会让网页以
# 零数据上线；这里拦下并给 env_doctor / repair 指引。
check_data_loaded || exit 1
start_streamlit
