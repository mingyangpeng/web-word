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
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

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
