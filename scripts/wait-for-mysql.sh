#!/bin/bash
# wait-for-mysql.sh — 等待 MySQL 就绪后再启动 Streamlit
# 用法: ./wait-for-mysql.sh <host> <port> -- <command...>

set -e

host="$1"
port="$2"
shift 2

# 解析 "--" 分隔符
if [ "$1" = "--" ]; then
    shift
fi

echo "⏳ Waiting for MySQL at ${host}:${port}..."

max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt + 1))

    # 尝试 TCP 连接
    if timeout 2 bash -c "echo > /dev/tcp/${host}/${port}" 2>/dev/null; then
        # TCP 可达，再验证 MySQL 协议响应
        if command -v mysqladmin &> /dev/null; then
            if mysqladmin ping -h "${host}" -P "${port}" -u "web_word_user" -p"webword123" --silent 2>/dev/null; then
                echo "✅ MySQL is ready! (attempt ${attempt}/${max_attempts})"
                exec "$@"
            fi
        else
            # 没有 mysqladmin，TCP 可达即视为就绪
            echo "✅ MySQL port reachable! (attempt ${attempt}/${max_attempts})"
            exec "$@"
        fi
    fi

    echo "  Attempt ${attempt}/${max_attempts} — MySQL not ready, retrying in 2s..."
    sleep 2
done

echo "❌ MySQL did not become ready after ${max_attempts} attempts. Starting app in offline mode..."
exec "$@"
