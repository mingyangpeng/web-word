#!/usr/bin/env bash
#
# _common.sh —— ops 脚本公共函数库（被同目录脚本 source，不直接执行）。
#
# 口径（README 同述）：
#   * 全 Docker 部署 —— 本目录所有启动动作只走 docker compose，不做本机
#     裸跑兜底（本机裸跑仅限开发测试，入口见 docs/dev/TESTING.md）；
#   * 永不删数据卷 —— stop 只停容器，down 不带 -v；数据卷（MySQL 数据/
#     media/backups）只增不删；
#   * 项目根解析：脚本位置两级上溯（scripts/ops/ → 项目根），不依赖 CWD；
#   * macOS（Docker Desktop）与 Linux（systemd）双平台的 daemon 自愈。

# 项目根（scripts/ops/ 两级上溯）
OPS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$OPS_ROOT/docker-compose.yml"

# 颜色（非 TTY 时不着色）
if [ -t 1 ]; then
    C_OK="\033[32m"; C_WARN="\033[33m"; C_ERR="\033[31m"; C_INFO="\033[36m"; C_OFF="\033[0m"
else
    C_OK=""; C_WARN=""; C_ERR=""; C_INFO=""; C_OFF=""
fi

say_ok()   { printf "${C_OK}✓${C_OFF} %s\n" "$*"; }
say_warn() { printf "${C_WARN}⚠${C_OFF}  %s\n" "$*"; }
say_err()  { printf "${C_ERR}✗${C_OFF} %s\n" "$*" >&2; }
say_info() { printf "${C_INFO}▸${C_OFF} %s\n" "$*"; }

# daemon 自愈：docker CLI 在场但 daemon 不响应 → 按平台拉起后等待
ensure_docker_daemon() {
    if ! command -v docker >/dev/null 2>&1; then
        say_err "未找到 docker CLI —— 请先安装 Docker（一次性前置，装完重跑 ./start）"
        case "$(uname -s)" in
            Darwin)  say_info "macOS：brew install --cask docker（或从 https://docs.docker.com/get-docker/ 下载）" ;;
            Linux)   say_info "Linux：curl -fsSL https://get.docker.com | sh（官方一键脚本）" ;;
            *)       say_info "安装指引：https://docs.docker.com/get-docker/" ;;
        esac
        exit 1
    fi
    if docker info >/dev/null 2>&1; then
        say_ok "Docker daemon 运行中"
        return 0
    fi
    say_warn "Docker daemon 未运行 —— 尝试拉起…"
    case "$(uname -s)" in
        Darwin)
            open -a Docker || { say_err "Docker Desktop 拉起失败，请手动启动后重试"; exit 1; }
            ;;
        Linux)
            if command -v systemctl >/dev/null 2>&1; then
                sudo systemctl start docker || { say_err "systemctl start docker 失败，请手动处理后重试"; exit 1; }
            else
                say_err "请手动启动 Docker 服务后重试"; exit 1
            fi
            ;;
        *)
            say_err "未知平台 $(uname -s)，请手动启动 Docker"; exit 1
            ;;
    esac
    # 等 daemon 就绪（最多 40s，Docker Desktop 冷启动常见 10~25s）
    i=0
    while [ "$i" -lt 40 ]; do
        if docker info >/dev/null 2>&1; then
            say_ok "Docker daemon 已就绪（等待 $i 秒）"
            return 0
        fi
        sleep 2; i=$((i + 2))
    done
    say_err "等待 Docker daemon 超时（80s）—— 请手动启动后重试"
    exit 1
}

# compose 前置检查（v2 插件形态）
require_compose() {
    if ! docker compose version >/dev/null 2>&1; then
        say_err "docker compose（v2 插件）不可用 —— compose 文件用了 !reset 等 v2.24+ 语法"
        say_info "升级指引：Docker Desktop 自带；Linux 装 docker-compose-plugin"
        exit 1
    fi
}

# .env 前置检查（compose env_file required —— 缺文件 compose 直接拒起）
require_env_file() {
    if [ ! -f "$OPS_ROOT/.env" ]; then
        if [ -f "$OPS_ROOT/.env.example" ]; then
            cp "$OPS_ROOT/.env.example" "$OPS_ROOT/.env"
            say_warn ".env 缺失 —— 已从 .env.example 复制，请填好必填项（MySQL 口令/AI key）再启动"
        else
            say_err ".env 缺失且无 .env.example —— 请先补齐环境配置文件"
        fi
        return 1
    fi
    return 0
}

# web 健康端点轮询（Streamlit /_stcore/health；最多 120s）
wait_web_healthy() {
    url="http://localhost:8501/_stcore/health"
    say_info "等待 web 健康：$url"
    i=0
    while [ "$i" -lt 120 ]; do
        body="$(curl -s -m 3 "$url" 2>/dev/null || true)"
        if [ "$body" = "ok" ]; then
            say_ok "web 就绪（http://localhost:8501，等待 $i 秒）"
            return 0
        fi
        sleep 3; i=$((i + 3))
    done
    say_warn "等待超时（120s）—— 用 scripts/ops/logs.sh web 查日志"
    return 1
}
