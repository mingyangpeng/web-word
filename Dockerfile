# Dockerfile for Streamlit Application (macOS M1 / arm64 compatible)
# python:3.11-slim has multi-arch manifests — Docker Desktop auto-pulls arm64 variant
# FROM 按 RepoDigests 固定（2026-11-08 docker pull 后 image inspect 实取，多架构
# manifest list digest，arm64/amd64 通用）；升级基础镜像时重新 pull 并换新 digest。
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

# ---- 词典全库组装 stage：分卷 → dictionary.db（sha256 校验）----
# data/dictionary.db（197MB，超 GitHub 100MB 上限）以 90MB 分卷随仓库分发，
# 本地裸跑由 ./develop.sh 重组；镜像侧在此组装，word_source 的音标（phonetic）
# 等「只认全库」的字段才能与本地裸跑完全一致。分卷中间层不进最终镜像。
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS dict_builder
WORKDIR /app
COPY data/dictionary.db.part* ./data/
COPY data/dictionary.db.sha256 ./data/
RUN cat data/dictionary.db.part* > data/dictionary.db \
    && sha256sum -c data/dictionary.db.sha256 \
    && rm data/dictionary.db.part*

FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

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
#
# 种子一律 COPY 到 /app/seed/data（镜像内非挂载点，目录结构与 data/ 完全同源）
# —— 不能直接 COPY 进 /app/data：它是 named volume（app_data）挂载点，volume
# 一挂就把镜像内内容盖住，存量部署升级镜像后种子会静默不更新（RV11 P2-5）。
# entrypoint.sh 启动时把 /app/data 里缺失的文件从 /app/seed/data 幂等补入
# （已有文件不覆盖：首次灌入、升级不强制覆盖）。
COPY docs/research/tables/Levin移动动词候选词筛选表.xlsx ./docs/research/tables/Levin移动动词候选词筛选表.xlsx
COPY docs/research/tables/output-oald10en-for-senselist-1020.xlsx ./docs/research/tables/output-oald10en-for-senselist-1020.xlsx
COPY docs/research/tables/词表义项清单.xlsx ./docs/research/tables/词表义项清单.xlsx
COPY docs/research/tables/域系初判表v0.2.xlsx ./docs/research/tables/域系初判表v0.2.xlsx
COPY data/motion_verbs_extracted.json ./seed/data/motion_verbs_extracted.json
COPY data/oxford_cache.json ./seed/data/oxford_cache.json
COPY data/dictionary_senses_subset.json ./seed/data/dictionary_senses_subset.json
COPY --from=dict_builder /app/data/dictionary.db ./seed/data/dictionary.db
COPY data/d1/ ./seed/data/d1/
COPY data/corpus/ ./seed/data/corpus/
COPY data/ModernChineseDict/mdx/ ./seed/data/ModernChineseDict/mdx/

RUN chmod +x ./scripts/entrypoint.sh

# data/ 是应用运行时写入区（备份/导出/日志/媒体/缓存），预建子目录并归属
# 应用用户；种子已在 /app/seed，此处 /app/data 为空目录，chown 零层膨胀
RUN mkdir -p /app/data/backups /app/data/exports /app/data/logs /app/data/media /app/data/cache

# 非 root 运行（RV11 P2-4）：固定 uid 1000 的应用用户，仅 /app/data 需可写
# （named volume 首挂时 Docker 按镜像内属主 copy-up，卷内即 app 可写；种子
# 在 /app/seed 只读即可）。entrypoint.sh 无需 root 的步骤（无 apt、无改权限），
# 八步灌库与 streamlit 均以 app 身份执行。宿主机 ./data/backups bind 挂载的
# 属主一致性见 docker-compose.yml 注释与 docs/DEPLOYMENT.md 升级注意事项。
RUN useradd -m -u 1000 app \
    && chown -R app:app /app/data \
    && chown app:app /app
USER app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Expose port
EXPOSE 8501

# Entrypoint: wait for MySQL then start Streamlit
CMD ["./scripts/entrypoint.sh"]
