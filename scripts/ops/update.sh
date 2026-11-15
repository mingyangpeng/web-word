#!/usr/bin/env bash
#
# update.sh —— 代码更新滚动部署（git pull → 重建镜像 → 平滑替换容器）。
#
# 做什么：git pull（快进，永不 force）→ docker compose build web →
# docker compose up -d（只重建镜像变化的 web；mysql 不动）→ 健康等待。
# 数据卷不受影响（代码烧镜像、数据在卷——升级不自伤）。
#
# 用法：bash scripts/ops/update.sh

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

ensure_docker_daemon
require_compose
require_env_file

say_info "① git pull（快进合并）"
git -C "$OPS_ROOT" pull --ff-only || {
    say_warn "git pull 失败（本地有分叉？）—— 跳过拉取，用当前工作树代码继续重建"
}

say_info "② 重建 web 镜像"
docker compose build web

say_info "③ 平滑替换容器"
docker compose up -d web

wait_web_healthy || true
say_ok "更新完成。变更记录：git -C $OPS_ROOT log --oneline -3"
