#!/usr/bin/env bash
#
# start.sh —— 启动项目（全 Docker：mysql＋web 两容器）。
#
# 做什么：daemon 自愈 → .env 检查 → docker compose up -d → 轮询 web 健康端点
# （最多 120s）→ 打印访问地址。幂等：重复运行无害（compose 起在跑的容器
# = 无操作）。
#
# 用法：bash scripts/ops/start.sh

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

ensure_docker_daemon
require_compose
require_env_file

say_info "docker compose up -d（mysql＋web）"
docker compose up -d

wait_web_healthy || true
say_info "状态一览：bash scripts/ops/status.sh"
