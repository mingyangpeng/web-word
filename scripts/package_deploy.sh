#!/bin/bash
# 部署包打包脚本——产出跨平台 tar.gz
# 用法: bash scripts/package_deploy.sh [输出目录]
set -euo pipefail

OUT_DIR="${1:-.}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="lexischema-deploy-${TIMESTAMP}"
STAGING=$(mktemp -d)
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "📦 打包 LexiSchema 部署包..."
echo "   源: $PROJECT_ROOT"
echo "   暂存: $STAGING/$ARCHIVE_NAME"

# ---- 复制项目文件（rsync 排除模式）----
mkdir -p "$STAGING/$ARCHIVE_NAME"
rsync -a \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='data/mysql/' \
  --exclude='data/backups/' \
  --exclude='data/exports/' \
  --exclude='data/logs/' \
  --exclude='data/media/' \
  --exclude='data/cache/' \
  --exclude='data/dictionary.db' \
  --exclude='data/zh_dict_senses.json' \
  --exclude='__pycache__/' \
  --exclude='.DS_Store' \
  --exclude='.pytest_cache/' \
  --exclude='.mypy_cache/' \
  --exclude='.claude/' \
  --exclude='.planning/' \
  --exclude='.gsd/' \
  --exclude='.github/' \
  --exclude='.flake8' \
  --exclude='.graphifyignore' \
  --exclude='.dockerignore' \
  --exclude='.coveragerc' \
  --exclude='mypy.ini' \
  --exclude='pytest.ini' \
  --exclude='.zcode*' \
  --exclude='node_modules/' \
  --exclude='htmlcov/' \
  --exclude='.venv/' \
  --exclude='docs/research/papers/' \
  --exclude='docs/dev/reports/' \
  --exclude='docs/dev/reviews/' \
  --exclude='docs/archive/' \
  --exclude='scripts/archive/' \
  --exclude='screenshots/' \
  --exclude='tests/' \
  --exclude='services/' \
  "$PROJECT_ROOT/" "$STAGING/$ARCHIVE_NAME/"

# ---- 补充部署专用文件 ----
cp "$PROJECT_ROOT/docs/DEPLOYMENT.md" "$STAGING/$ARCHIVE_NAME/" 2>/dev/null || true
cp "$PROJECT_ROOT/.env.example" "$STAGING/$ARCHIVE_NAME/" 2>/dev/null || true

# ---- 生成 .env 占位模板（不含真实凭据）----
cat > "$STAGING/$ARCHIVE_NAME/.env" <<'ENVFILE'
# ============================================
# LexiSchema 环境配置
# 生产部署：真实凭据写 .env.local（gitignored）或环境变量
# ============================================

# MySQL 8.0
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=web_word_db
MYSQL_USER=web_word_user
MYSQL_PASSWORD=CHANGE_ME_PRODUCTION
MYSQL_ROOT_PASSWORD=CHANGE_ME_ROOT

# LLM API（三选一或走「🤖 模型供应商」页面配置）
ZHIPUAI_API_KEY=
ZHIPUAI_MODEL=glm-4
# OPENAI_API_KEY=
# OPENAI_BASE_URL=https://api.openai.com/v1
# DEEPSEEK_API_KEY=
# DEEPSEEK_BASE_URL=https://api.deepseek.com
# LLM_PROVIDER=          # 空=自动优先级; zhipu/openai/deepseek=钉死
ENVFILE

# ---- 快速启动指南 ----
cat > "$STAGING/$ARCHIVE_NAME/QUICK_START.md" <<'QSGUIDE'
# LexiSchema 快速部署指南

## 方式 A：Docker Compose（推荐，Win/Mac/Linux 通用）

前置：[Docker Desktop](https://www.docker.com/products/docker-desktop/) 或 Docker Engine + Compose v2

```bash
# 1. 解压后进入目录
cd lexischema-deploy-*

# 2. 编辑 .env 设置 MySQL 密码（必改！）
#    MYSQL_PASSWORD=你的安全密码
#    MYSQL_ROOT_PASSWORD=你的安全root密码

# 3. 一条命令启动
docker compose up -d

# 4. 打开浏览器
open http://localhost:8501
# 默认账号 admin / admin123（首次登录后立即改密！）
```

## 方式 B：本地 Python + MySQL（无 Docker）

前置：Python 3.11+、MySQL 8.0

### macOS
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装并启动 MySQL
brew install mysql@8.0 && brew services start mysql@8.0

# 3. 建库授权
mysql -u root -e "CREATE DATABASE web_word_db CHARACTER SET utf8mb4;
CREATE USER 'web_word_user'@'localhost' IDENTIFIED BY 'webword123';
GRANT ALL ON web_word_db.* TO 'web_word_user'@'localhost';"

# 4. 配置环境
cp .env.example .env
# 编辑 .env 设置密码

# 5. 灌库＋启动
chmod +x start develop.sh start.sh repair.sh
./start
```

### Linux (Ubuntu/Debian)
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 MySQL
sudo apt install mysql-server
sudo systemctl start mysql

# 3. 建库授权
sudo mysql -e "CREATE DATABASE web_word_db CHARACTER SET utf8mb4;
CREATE USER 'web_word_user'@'localhost' IDENTIFIED BY 'webword123';
GRANT ALL ON web_word_db.* TO 'web_word_user'@'localhost';"

# 4-5. 同 macOS（配置 .env → ./start）
```

### Windows
```powershell
# 1. 安装 Python 3.11+ 与 MySQL 8.0（MySQL Installer）
# 2. pip install -r requirements.txt
# 3. MySQL Workbench 或命令行建库授权
# 4. 配置 .env → python -m streamlit run src/app.py
```

## 首次登录

| 项 | 值 |
|----|-----|
| URL | http://localhost:8501 |
| 账号 | admin |
| 密码 | admin123 |
| ⚠️ | 首次登录后立即修改密码！ |

## 常见问题

| 问题 | 解决 |
|------|------|
| MySQL 连不上 | 检查 .env 的 MYSQL_HOST/PORT/USER/PASSWORD |
| 页面空白/报错 | 查看 `docker compose logs web` 或终端输出 |
| 数据为空 | 等待首启灌库完成（约 2-3 分钟），或手动 `./develop.sh` |
| 端口冲突 | 改 docker-compose.yml 的端口映射或 .env 的 MYSQL_PORT |
QSGUIDE

# ---- 打 tar.gz ----
echo "📦 生成 tar.gz..."
cd "$STAGING"
tar czf "$OUT_DIR/$ARCHIVE_NAME.tar.gz" "$ARCHIVE_NAME"
cd "$PROJECT_ROOT"

# ---- 计算校验和 ----
SHA=$(shasum -a 256 "$OUT_DIR/$ARCHIVE_NAME.tar.gz" | awk '{print $1}')
SIZE=$(du -h "$OUT_DIR/$ARCHIVE_NAME.tar.gz" | awk '{print $1}')

echo ""
echo "✅ 部署包已生成"
echo "   文件: $OUT_DIR/$ARCHIVE_NAME.tar.gz"
echo "   大小: $SIZE"
echo "   SHA256: ${SHA:0:16}..."
echo ""
echo "   部署: 解压 → 编辑 .env → docker compose up -d → http://localhost:8501"

# 清理暂存
rm -rf "$STAGING"
