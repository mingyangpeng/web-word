#!/usr/bin/env bash
# =============================================================================
# deploy/validate.sh — 公网部署三件套静态自检
#
# 只做文本级检查（括号配平 / 必需指令存在性 / 占位符提醒），不要求本机有
# nginx/caddy 二进制 —— 语法终验在目标机（nginx -t / systemctl reload）。
# 修改 deploy/ 下样例配置后先跑一遍：
#   bash deploy/validate.sh
#
# 退出码：0 = 全部通过（WARN 不计失败）；1 = 存在 FAIL。
# =============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_CONF="$SCRIPT_DIR/nginx.conf.example"
CADDYFILE="$SCRIPT_DIR/Caddyfile.example"

PASS=0
FAIL=0
WARN=0

pass() { printf '  [PASS] %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL + 1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN + 1)); }

# 去注释后统计某字符出现次数（配置里无含 # 或花括号的字符串字面量，sed 足够）
count_char() { # $1=file $2=char
    sed 's/#.*$//' "$1" | tr -cd "$2" | wc -c | tr -d ' '
}

check_braces() { # $1=file $2=label
    local open close
    open=$(count_char "$1" '{')
    close=$(count_char "$1" '}')
    if [ "$open" -gt 0 ] && [ "$open" -eq "$close" ]; then
        pass "$2 括号配平：{ $open / } $close"
    else
        fail "$2 括号不配平：{ $open / } $close"
    fi
}

check_contains() { # $1=file $2=pattern $3=desc
    if grep -qE -- "$2" "$1"; then
        pass "$3"
    else
        fail "$3（未匹配到：$2）"
    fi
}

echo "=============================================="
echo " LexiSchema deploy 静态自检"
echo " 脚本：$SCRIPT_DIR"
echo "=============================================="

# ---------------------------------------------------------------- bash 自检
echo ""
echo "--- validate.sh 自身（bash 语法） ---"
if bash -n "$0" 2>/dev/null; then
    pass "bash -n \$0 语法检查通过"
else
    fail "validate.sh 自身 bash 语法错误（bash -n 失败）"
fi

# ---------------------------------------------------------------- nginx
echo ""
echo "--- nginx.conf.example ---"
if [ ! -f "$NGINX_CONF" ]; then
    fail "文件不存在：$NGINX_CONF"
else
    check_braces "$NGINX_CONF" "nginx"

    # 必需指令
    check_contains "$NGINX_CONF" 'listen[^;]*443'        "listen 443（TLS 终止）"
    check_contains "$NGINX_CONF" 'ssl_certificate[[:space:]]' "ssl_certificate 指令存在"
    check_contains "$NGINX_CONF" 'proxy_pass[[:space:]]+http://127\.0\.0\.1:8501' "proxy_pass → 127.0.0.1:8501"
    # WebSocket 升级头（Streamlit 必需）
    check_contains "$NGINX_CONF" 'proxy_set_header[[:space:]]+Upgrade' "proxy_set_header Upgrade（WebSocket 必需）"
    check_contains "$NGINX_CONF" 'proxy_set_header[[:space:]]+Connection' "proxy_set_header Connection（WebSocket 必需）"
    check_contains "$NGINX_CONF" 'map[[:space:]]+\$http_upgrade[[:space:]]+\$connection_upgrade' "map \$http_upgrade → \$connection_upgrade"
    # 限速：login（/_stcore/stream）10r/m + static 路由
    check_contains "$NGINX_CONF" 'limit_req_zone.*rate=10r/m' "limit_req_zone login 10r/m"
    check_contains "$NGINX_CONF" 'location[[:space:]]*=[[:space:]]*/_stcore/stream' "location = /_stcore/stream（Streamlit 无独立登录端点，login 限速落此）"
    check_contains "$NGINX_CONF" 'location[[:space:]]+/app/static/' "location /app/static/（RV4-7 折中块）"
    check_contains "$NGINX_CONF" 'limit_req_zone.*rate=30r/m' "limit_req_zone static 30r/m"
    # 安全头
    check_contains "$NGINX_CONF" 'Strict-Transport-Security' "HSTS 头"
    check_contains "$NGINX_CONF" 'X-Frame-Options[[:space:]]+SAMEORIGIN' "X-Frame-Options SAMEORIGIN"
    check_contains "$NGINX_CONF" 'X-Content-Type-Options[[:space:]]+nosniff' "X-Content-Type-Options nosniff"
    # 其他
    check_contains "$NGINX_CONF" 'client_max_body_size[[:space:]]+50m' "client_max_body_size 50m（媒体上传）"
    check_contains "$NGINX_CONF" 'gzip[[:space:]]+on;' "gzip on"

    # server_name 存在性（指令必须存在）
    if grep -qE '^[[:space:]]*server_name[[:space:]]+' "$NGINX_CONF"; then
        pass "server_name 指令存在"
    else
        fail "缺少 server_name 指令"
    fi

    # 占位符提醒（WARN，不计失败）
    if grep -q 'lexischema.example.com' "$NGINX_CONF"; then
        warn "server_name 仍是占位符 lexischema.example.com —— 部署时改成实际域名（80/443 两处）"
    fi
    if grep -q 'REPLACE-ME' "$NGINX_CONF"; then
        warn "证书路径仍是占位符 REPLACE-ME —— 部署时改成实际证书路径（certbot/caddy 签发后回填）"
    fi
    if grep -qE 'location[[:space:]]+/app/static/[[:space:]]*\{[^}]*deny[[:space:]]+all' "$NGINX_CONF"; then
        fail "/app/static/ 配置了 deny all —— 会打断浏览器侧图谱请求（见 deploy/README.md §三）"
    fi
fi

# ---------------------------------------------------------------- Caddy
echo ""
echo "--- Caddyfile.example ---"
if [ ! -f "$CADDYFILE" ]; then
    fail "文件不存在：$CADDYFILE"
else
    check_braces "$CADDYFILE" "Caddy"

    # 站点块：存在一行非注释、非缩进的域名 + 开花括号（基本形态）
    if grep -qE '^[^[:space:]#][^=]*\{[[:space:]]*$' "$CADDYFILE"; then
        pass "站点块基本形态（域名 + {）"
    else
        fail "未找到站点块（应形如 '域名 {'）"
    fi

    check_contains "$CADDYFILE" 'reverse_proxy[[:space:]]+127\.0\.0\.1:8501' "reverse_proxy → 127.0.0.1:8501"
    check_contains "$CADDYFILE" 'Strict-Transport-Security' "HSTS 头"
    check_contains "$CADDYFILE" 'X-Frame-Options'          "X-Frame-Options"
    check_contains "$CADDYFILE" 'X-Content-Type-Options'   "X-Content-Type-Options nosniff"
    check_contains "$CADDYFILE" 'X-Robots-Tag.*noindex'    "/app/static/ 不索引（X-Robots-Tag）"

    if grep -qE '^[[:space:]]*lexischema\.example\.com[[:space:]]*\{' "$CADDYFILE"; then
        warn "Caddy 站点名仍是占位符 lexischema.example.com —— 部署时改成实际域名（证书随之自动签发）"
    fi
fi

# ---------------------------------------------------------------- 汇总
echo ""
echo "=============================================="
echo " 结果：PASS=$PASS FAIL=$FAIL WARN=$WARN"
if [ "$FAIL" -gt 0 ]; then
    echo " 结论：未通过（存在 FAIL）—— 修正后再跑"
    echo "=============================================="
    exit 1
else
    echo " 结论：全部通过（WARN 为部署期占位符提醒，属预期）"
    echo " 注：文本级检查不替代目标机 nginx -t / caddy validate"
    echo "=============================================="
    exit 0
fi
