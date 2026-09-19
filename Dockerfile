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
# 只拷这几个必要文件，不拷 data/ 其余内容（dictionary.db 有 197MB、
# data/mysql 是本机数据库目录，都不该进镜像）。
#
# 注意 **必须拷 Levin 筛选表**：现在词目与分类（三主范畴 / 十二次类）都以它为准，
# 缺了它 load_word_library.py 会直接抛错，容器首启就灌不出词库。
# data/dictionary.db（197MB）**刻意不进镜像** —— 它只覆盖 171 词里的 23 个，
# 为它让镜像膨胀 200MB 不划算。缺失时释义自动降级到旧词库 / 研究者标注，
# 来源会如实标注（见 docs/英语自移移动动词词表.docx 的编者说明）。
COPY docs/Levin移动动词候选词筛选表.xlsx ./docs/Levin移动动词候选词筛选表.xlsx
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
