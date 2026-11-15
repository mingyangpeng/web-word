#!/usr/bin/env bash
#
# status.sh —— 项目状态一览（只读，不改任何东西）。
#
# 输出：容器状态（compose ps）＋ web 健康端点 ＋ MySQL 容器健康 ＋
# 数据卷占用。861 端口/8502 直跑实例不在职责内（README 口径）。
#
# 用法：bash scripts/ops/status.sh

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

say_info "容器状态"
docker compose ps

say_info "web 健康端点（8501）"
body="$(curl -s -m 3 http://localhost:8501/_stcore/health 2>/dev/null || true)"
if [ "$body" = "ok" ]; then
    say_ok "http://localhost:8501 —— ok"
else
    say_warn "8501 无响应（body=${body:-空}）—— 未启动或正在预热（启动后预热约需数十秒）"
fi

say_info "MySQL 容器健康"
if docker compose ps mysql 2>/dev/null | grep -q healthy; then
    say_ok "mysql 容器 healthy"
else
    say_warn "mysql 容器非 healthy（或未启动）"
fi

say_info "数据卷占用"
docker system df 2>/dev/null | head -5 || say_warn "docker system df 不可用"
