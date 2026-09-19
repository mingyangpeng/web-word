#!/bin/bash
# entrypoint.sh — Docker 容器入口脚本
# 等待 MySQL 就绪 → 首次启动灌入词库 → 启动 Streamlit

set -e

echo "⏳ Waiting for MySQL..."
python scripts/wait_for_mysql.py

# 首次启动自动灌入词库（词目以 docs/Levin移动动词候选词筛选表.xlsx 的 171 词为准，
# 释义优先取 data/dictionary.db，缺失时降级到旧词库 / 研究者标注）与词间近义关系。
#
# --if-empty 保证幂等：definitions 表已有数据时直接跳过，**不会**执行整体重建，
# 也就不会覆盖用户/管理员后续新增或修改的词条。
# 数据库不可用时不阻断启动（应用会降级为离线模式）。
#
# 注意脚本会读 docs/ 下的 xlsx，Dockerfile 已把它拷进镜像（.dockerignore 里有例外）。
echo "📚 Seeding word library (skipped if already populated)..."
python scripts/load_word_library.py --if-empty || \
    echo "⚠️  灌库失败，继续以现有数据启动（应用支持离线降级）"

echo "🚀 Starting Streamlit..."
exec streamlit run src/app.py --server.port=8501 --server.address=0.0.0.0
