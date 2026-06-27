#!/bin/bash
# entrypoint.sh — Docker 容器入口脚本
# 等待 MySQL 就绪后启动 Streamlit

set -e

echo "⏳ Waiting for MySQL..."
python scripts/wait_for_mysql.py

echo "🚀 Starting Streamlit..."
exec streamlit run src/app.py --server.port=8501 --server.address=0.0.0.0
