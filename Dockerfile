# Dockerfile for Streamlit Application (macOS M1 / arm64 compatible)
# python:3.11-slim has multi-arch manifests — Docker Desktop auto-pulls arm64 variant
FROM python:3.11-slim

# ---- 词典全库组装 stage：分卷 → dictionary.db（sha256 校验）----
# data/dictionary.db（197MB，超 GitHub 100MB 上限）以 90MB 分卷随仓库分发，
# 本地裸跑由 ./develop.sh 重组；镜像侧在此组装，word_source 的音标（phonetic）
# 等「只认全库」的字段才能与本地裸跑完全一致。分卷中间层不进最终镜像。
FROM python:3.11-slim AS dict_builder
WORKDIR /app
COPY data/dictionary.db.part* ./data/
COPY data/dictionary.db.sha256 ./data/
RUN cat data/dictionary.db.part* > data/dictionary.db \
    && sha256sum -c data/dictionary.db.sha256 \
    && rm data/dictionary.db.part*

FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Use Tsinghua PyPI mirror for reliable downloads in China
# Add retry logic for flaky connections
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir --retries 5 --timeout 60 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/wait_for_mysql.py ./scripts/wait_for_mysql.py
COPY scripts/load_word_library.py ./scripts/load_word_library.py
COPY scripts/load_supplemented_senses.py ./scripts/load_supplemented_senses.py
COPY scripts/load_corpus_dataset.py ./scripts/load_corpus_dataset.py
COPY scripts/load_category_study.py ./scripts/load_category_study.py
COPY scripts/load_domain_family.py ./scripts/load_domain_family.py
COPY scripts/update_domain_family_data.py ./scripts/update_domain_family_data.py
COPY scripts/load_llm_screening.py ./scripts/load_llm_screening.py
COPY scripts/parse_modern_chinese_dict.py ./scripts/parse_modern_chinese_dict.py
COPY scripts/load_zh_dict.py ./scripts/load_zh_dict.py
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

# 词库种子：容器首启由 entrypoint.sh 按 ./start 同款八步幂等灌入。
# data/mysql（本机数据库目录）与 zh_dict_senses.json 本体不进镜像（后者首启由 mdx 生成）；
# dictionary.db 全库由 dict_builder stage 组装后 COPY 进来（sha256 已校验），
# dictionary_senses_subset.json 仍随镜像分发，作为全库缺失场景的降级快照。
COPY docs/research/tables/Levin移动动词候选词筛选表.xlsx ./docs/research/tables/Levin移动动词候选词筛选表.xlsx
COPY docs/research/tables/output-oald10en-for-senselist-1020.xlsx ./docs/research/tables/output-oald10en-for-senselist-1020.xlsx
COPY docs/research/tables/词表义项清单.xlsx ./docs/research/tables/词表义项清单.xlsx
COPY docs/research/tables/域系初判表v0.2.xlsx ./docs/research/tables/域系初判表v0.2.xlsx
COPY data/motion_verbs_extracted.json ./data/motion_verbs_extracted.json
COPY data/oxford_cache.json ./data/oxford_cache.json
COPY data/dictionary_senses_subset.json ./data/dictionary_senses_subset.json
COPY --from=dict_builder /app/data/dictionary.db ./data/dictionary.db
COPY data/d1/ ./data/d1/
COPY data/corpus/ ./data/corpus/
COPY data/ModernChineseDict/mdx/ ./data/ModernChineseDict/mdx/

RUN chmod +x ./scripts/entrypoint.sh

# Create data directory
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Expose port
EXPOSE 8501

# Entrypoint: wait for MySQL then start Streamlit
CMD ["./scripts/entrypoint.sh"]
