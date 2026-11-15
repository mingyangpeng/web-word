#!/usr/bin/env bash
#
# down.sh —— 移除容器（保留数据卷）。
#
# 口径：docker compose down —— 删容器与网络，**不带 -v**（数据卷永不删：
# MySQL 数据/web-word-app-data 媒体卷/bind 的 data/backups 全保留）。
# 日常启停用 start.sh/stop.sh 即可；down 用于要重建容器（改了 compose
# 配置/端口映射）或清理重建的场景。
#
# 用法：bash scripts/ops/down.sh

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

ensure_docker_daemon
require_compose

say_info "docker compose down（删容器与网络；数据卷保留——永不删卷）"
docker compose down
say_ok "容器已移除，数据卷保留。再启动：bash scripts/ops/start.sh"
