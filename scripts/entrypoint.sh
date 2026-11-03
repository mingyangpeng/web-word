#!/bin/bash
# entrypoint.sh — Docker 容器入口脚本
# 等待 MySQL 就绪 → 幂等灌入全部数据（与 ./start 的七步一致）→ 启动 Streamlit
#
# 数据与 ./start 同源：词库/语料/范畴深挖/域系初判/域系增强/LLM 初筛草稿/
# 现汉7 词典。种子文件由 Dockerfile COPY 进镜像；environment 列在
# docker-compose.yml（.env 已入库，compose 的 environment 覆盖 env_file，
# MYSQL_HOST=mysql 由 compose 强制指定）。

set -e

echo "⏳ Waiting for MySQL..."
python scripts/wait_for_mysql.py

run_loader() {  # run_loader <说明> <命令...>
    local desc="$1"; shift
    echo "📚 $desc..."
    "$@" --if-empty || echo "⚠️  $desc 失败，继续以现有数据启动（应用支持离线降级）"
}

# --if-empty 保证幂等：表已有数据时直接跳过，**不会**执行整体重建，
# 也就不会覆盖用户/管理员后续新增或修改的词条。
# 单步失败不阻断启动（应用支持离线降级），与 ./start 的容错口径一致。

run_loader "灌入词库 + OALD10 义项 + 词间关系" \
    python scripts/load_word_library.py
run_loader "灌入 enTenTen21 语料数据集" \
    python scripts/load_corpus_dataset.py
run_loader "灌入跑范畴深挖数据" \
    python scripts/load_category_study.py
run_loader "灌入域系初判" \
    python scripts/load_domain_family.py
python scripts/update_domain_family_data.py \
    || echo "⚠️  域系初判增强失败（非阻断）"
python scripts/load_llm_screening.py --if-empty \
    || echo "⚠️  LLM 初筛草稿灌入失败（非阻断）"
if [ ! -f data/zh_dict_senses.json ] && [ -f data/ModernChineseDict/mdx/dict.mdx.txt ]; then
    echo "📚 结构化《现汉7》mdx（首次运行）..."
    python scripts/parse_modern_chinese_dict.py \
        || echo "⚠️  mdx 解析失败（非阻断）"
fi
run_loader "灌入《现汉7》词典" \
    python scripts/load_zh_dict.py

echo "🚀 Starting Streamlit..."
exec streamlit run src/app.py --server.port=8501 --server.address=0.0.0.0
