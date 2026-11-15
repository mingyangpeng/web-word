#!/usr/bin/env bash
#
# logs.sh —— 查看容器日志。
#
# 用法：bash scripts/ops/logs.sh [web|mysql|all] [--tail N]
#   默认 web --tail 100 跟随；all 跟随两服务流。
# 示例：
#   bash scripts/ops/logs.sh                 # web 最近 100 行＋跟随
#   bash scripts/ops/logs.sh mysql --tail 50 # MySQL 最近 50 行＋跟随
#   bash scripts/ops/logs.sh all             # 两服务全部流

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"
ensure_docker_daemon
require_compose

SERVICE="${1:-web}"
case "$SERVICE" in
    web|mysql|all) ;;
    *) say_err "用法：logs.sh [web|mysql|all] [--tail N]"; exit 1 ;;
esac
shift || true
TAIL=100
if [ "${1:-}" = "--tail" ] && [ -n "${2:-}" ]; then
    TAIL="$2"
fi

if [ "$SERVICE" = "all" ]; then
    docker compose logs -f --tail "$TAIL" web mysql
else
    docker compose logs -f --tail "$TAIL" "$SERVICE"
fi
