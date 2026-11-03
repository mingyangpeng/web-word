#!/bin/bash
# web-word 服务管理脚本
# 用法: ./web-word.sh [start|stop|restart|status|url|logs]

set -e

CMD=${1:-status}
LOG_DIR="/home/pmy/megatron_2025/pmy/web-word/logs"
URL_FILE="$LOG_DIR/current_url.txt"
PERMANENT_URL="https://word.jhon.de5.net"

case "$CMD" in
  start)
    systemctl --user start streamlit.service cloudflared.service
    echo "✅ 服务已启动"
    ;;
  stop)
    systemctl --user stop cloudflared.service streamlit.service
    echo "⏹  服务已停止"
    ;;
  restart)
    systemctl --user restart streamlit.service
    sleep 3
    systemctl --user restart cloudflared.service
    echo "🔄 服务已重启"
    ;;
  status)
    echo "===== 永久公网地址 ====="
    echo "🌐 $PERMANENT_URL"
    echo ""
    echo "===== 服务状态 ====="
    systemctl --user is-active streamlit.service cloudflared.service | paste <(echo -e "streamlit:\ncloudflared:") -
    echo ""
    echo "===== 进程 ====="
    ps -o pid,etime,cmd -C python,cloudflared 2>/dev/null | grep -E "streamlit|cloudflared" || echo "（无进程）"
    echo ""
    echo "===== 隧道连接 ====="
    cloudflared tunnel info streamlit-word-graph 2>&1 | grep -E "CONNECTOR|lax|sjc|conn" | tail -3
    ;;
  url)
    echo "$PERMANENT_URL"
    ;;
  logs)
    TAIL=${2:-30}
    echo "--- streamlit.log (last $TAIL) ---"
    tail -n "$TAIL" "$LOG_DIR/streamlit.log" 2>/dev/null
    echo ""
    echo "--- cloudflared.log (last $TAIL) ---"
    tail -n "$TAIL" "$LOG_DIR/cloudflared.log" 2>/dev/null
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status|url|logs}"
    echo ""
    echo "永久公网地址: $PERMANENT_URL"
    exit 1
    ;;
esac
