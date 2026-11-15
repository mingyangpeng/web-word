#!/usr/bin/env bash
#
# install.sh —— 环境安装/自检（全 Docker 部署口径）。
#
# 做什么（顺序执行，任一关键步失败即停）：
#   1. Docker CLI 在场＋daemon 运行（未运行按平台自动拉起并等待）；
#   2. docker compose v2 插件可用（compose 文件用 !reset 等 v2.24+ 语法）；
#   3. .env 在场（缺失从 .env.example 复制并提示必填项；AI key 至少一个
#      非空——只查存在性不查有效性，有效性由应用内模型供应商页自检）；
#   4. 端口 8501 预检（被非本应用占用则提示改 compose 端口映射）；
#   5. docker compose build（构建/重建 web 镜像——代码烧镜像，升级代码后
#      重跑本脚本或 scripts/ops/update.sh 即重建）；
#   6. 首次启动说明（MySQL 卷初始化＋种子灌库脚本指路）。
#
# 用法：bash scripts/ops/install.sh
# 退出码：全过 0；有关键失败 1。

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

say_info "① Docker daemon"
ensure_docker_daemon

say_info "② docker compose v2"
require_compose
say_ok "$(docker compose version --short 2>/dev/null || docker compose version)"

say_info "③ 环境配置 .env"
require_env_file || true
if [ -f "$OPS_ROOT/.env" ]; then
    if grep -qE '^(ZHIPUAI_API_KEY|OPENAI_API_KEY|DEEPSEEK_API_KEY)=..*' "$OPS_ROOT/.env"; then
        say_ok "AI key 至少一个非空（存在性检查；有效性由应用内「🤖 模型供应商」页自检）"
    else
        say_warn ".env 内未见任何 AI key（ZHIPUAI/OPENAI/DEEPSEEK）—— AI 功能不可用，其余功能不受影响"
    fi
fi

say_info "④ 端口 8501 预检"
if curl -s -m 3 http://localhost:8501/_stcore/health 2>/dev/null | grep -q ok; then
    say_warn "8501 已有本应用实例在跑（重复安装无害；要重建请先 scripts/ops/stop.sh）"
elif lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
    say_warn "8501 被其他进程占用 —— 如需更换端口改 docker-compose.yml 的 web.ports 映射"
else
    say_ok "8501 空闲"
fi

say_info "⑤ 构建 web 镜像（代码烧镜像 —— 构建 = 把当前源码打进容器）"
docker compose build web

say_info "⑥ 完成说明"
say_ok "环境就绪。下一步："
say_info "  启动：bash scripts/ops/start.sh"
say_info "  首次部署灌种子数据：入口见 docs/dev/DEPLOYMENT.md §1.5"
say_info "    （容器内跑 scripts/load_*.py 灌库族＋init_db.sql 建表基线）"
say_info "  灾备备份：scripts/backup_db.sh（mysqldump＋media 归档，保留 14 份）"
