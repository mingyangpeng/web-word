# Dockerfile for Streamlit Application (macOS M1 / arm64 compatible)
# python:3.11-slim has multi-arch manifests — Docker Desktop auto-pulls arm64 variant
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
COPY scripts/load_corpus_dataset.py ./scripts/load_corpus_dataset.py
COPY scripts/load_category_study.py ./scripts/load_category_study.py
COPY scripts/load_domain_family.py ./scripts/load_domain_family.py
COPY scripts/update_domain_family_data.py ./scripts/update_domain_family_data.py
COPY scripts/load_llm_screening.py ./scripts/load_llm_screening.py
COPY scripts/parse_modern_chinese_dict.py ./scripts/parse_modern_chinese_dict.py
COPY scripts/load_zh_dict.py ./scripts/load_zh_dict.py
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

# 词库种子：容器首启由 entrypoint.sh 按 ./start 同款七步幂等灌入。
# data/mysql（本机数据库目录）与 dictionary.db 本体不进镜像；
# 容器内 word_source 走 data/dictionary_senses_subset.json 降级
# （17 词 246 义位，已覆盖义位标注与域系中文对照所需）。
COPY docs/Levin移动动词候选词筛选表.xlsx ./docs/Levin移动动词候选词筛选表.xlsx
COPY docs/output-oald10en-for-senselist-1020.xlsx ./docs/output-oald10en-for-senselist-1020.xlsx
COPY docs/词表义项清单.xlsx ./docs/词表义项清单.xlsx
COPY docs/域系初判表v0.2.xlsx ./docs/域系初判表v0.2.xlsx
COPY data/motion_verbs_extracted.json ./data/motion_verbs_extracted.json
COPY data/oxford_cache.json ./data/oxford_cache.json
COPY data/dictionary_senses_subset.json ./data/dictionary_senses_subset.json
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
