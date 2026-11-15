#!/usr/bin/env bash
#
# stop.sh —— 停止项目（保留容器与数据卷）。
#
# 口径：docker compose stop（容器保留，restart 快；**永不删数据卷**——
# MySQL 数据/media/backups 只增不删）。要连容器一起删用 scripts/ops/
# down.sh；要停本机 8502 直跑实例见 README。
#
# 用法：bash scripts/ops/stop.sh

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

ensure_docker_daemon
require_compose

say_info "docker compose stop（容器保留、数据卷不动）"
docker compose stop
say_ok "已停止。再启动：bash scripts/ops/start.sh"
