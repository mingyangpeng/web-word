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
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

# 词库种子：容器首启由 entrypoint.sh 调 load_word_library.py --if-empty 灌入。
# 只拷这两个 JSON（约 110KB），不拷 data/ 其余内容（dictionary.db 有 197MB、
# data/mysql 是本机数据库目录，都不该进镜像）。
COPY data/motion_verbs_extracted.json ./data/motion_verbs_extracted.json
COPY data/oxford_cache.json ./data/oxford_cache.json

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
