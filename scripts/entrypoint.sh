#!/bin/bash
# entrypoint.sh — Docker 容器入口脚本
# 等待 MySQL 就绪 → 幂等灌入全部数据（与 ./start 的八步一致）→ 启动 Streamlit
#
# 数据与 ./start 同源：词库/语料/范畴深挖/域系初判/域系增强/LLM 初筛草稿/
# 现汉7 词典。种子文件由 Dockerfile COPY 进镜像的 /app/seed/data（/app/data
# 是 named volume 挂载点，COPY 进去的内容会被盖住，故镜像侧只放种子暂存区）；
# environment 列在 docker-compose.yml（.env 已入库，compose 的 environment
# 覆盖 env_file，MYSQL_HOST=mysql 由 compose 强制指定）。

set -e

# ---- 种子补入（先于一切灌库步骤，幂等）----
# /app/data 由 named volume 承载：首次启动卷为空，把镜像内 /app/seed/data 的
# 种子拷进去完成「首次灌入」；已有文件一律不覆盖 —— 保留「升级不强制覆盖」
# 语义（升级镜像不会重置用户数据；确需刷新某个种子，删卷内对应文件重启即可）。
SEED_ROOT="/app/seed/data"
if [ -d "$SEED_ROOT" ]; then
    while IFS= read -r -d '' rel; do
        if [ ! -f "/app/data/$rel" ]; then
            mkdir -p "/app/data/$(dirname "$rel")" \
                && cp "$SEED_ROOT/$rel" "/app/data/$rel" \
                && echo "🌱 seeded /app/data/$rel" \
                || echo "⚠️  种子补入失败：${rel}（非阻断，继续启动）"
        fi
    done < <(find "$SEED_ROOT" -type f -printf '%P\0')
fi

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
# 人工补充义位 4 条（scutter/kayak/oar/dodder）：研究词表 996 = 992 OALD + 4 补充。
# 脚本自身幂等（先删同源行再插），不接 --if-empty 也不受它影响；依赖
# data/corpus/sense_sheets/ 的 4 个 xlsx（已 COPY 进镜像）。
run_loader "灌入人工补充义位（4 条）" \
    python scripts/load_supplemented_senses.py
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
