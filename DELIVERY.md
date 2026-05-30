# 项目交付文档

## 项目信息

- **项目名称**: 中文动词释义 Web 应用
- **版本**: 1.0.0
- **交付日期**: 2026/05/30
- **技术栈**: Python 3.11 + Streamlit + MySQL + PyYAML

## 功能特性

### ✅ 已完成功能

1. **动词语义分解展示**
   - 基于 Talmy 运动事件类型学
   - 语义要素分解（方式/路径/方向/体相）
   - Emoji 颜色编码

2. **交互式界面**
   - Sticky 搜索栏
   - 四个可展开卡片
   - 示例库（20个动词）
   - 用户反馈表单

3. **数据库管理**
   - MySQL 数据库支持
   - YAML 配置管理
   - 连接池配置

4. **API 集成**
   - LLM API 集成准备
   - 智谱 AI 接口
   - 模型配置管理

5. **安全性**
   - 输入验证
   - XSS 防护
   - API 密钥管理

6. **测试框架**
   - Pytest 测试框架
   - 单元测试
   - 覆盖率报告

7. **部署准备**
   - Docker 支持
   - Docker Compose 配置
   - CI/CD 工作流

## 文件结构

\`\`\`
web-word/
├── src/
│   ├── app.py              # 主应用
│   ├── mysql_db.py         # MySQL 数据库模块
│   ├── database.py         # SQLite 数据库模块（备用）
│   ├── design_system.py    # 设计系统
│   ├── api.py              # LLM API 集成
│   └── security.py         # 安全模块
├── config/
│   ├── config.yaml         # 主配置文件
│   └── README.md           # 配置说明
├── tests/
│   ├── conftest.py         # 测试配置
│   ├── test_api.py         # API 测试
│   ├── test_security.py    # 安全测试
│   └── __init__.py
├── scripts/
│   └── migrate_db.py       # 数据库迁移脚本
├── Dockerfile              # Docker 配置
├── docker-compose.yml      # Docker Compose 配置
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量示例
├── pytest.ini              # Pytest 配置
└── .github/workflows/
    └── ci-cd.yml           # CI/CD 配置
\`\`\`

## 快速开始

### 1. 安装依赖

\`\`\`bash
pip install -r requirements.txt
\`\`\`

### 2. 配置环境变量

\`\`\`bash
cp .env.example .env
# 编辑 .env 文件，设置 API 密钥和数据库密码
\`\`\`

### 3. 初始化数据库

\`\`\`bash
mysql -u root -p
CREATE DATABASE web_word_db CHARACTER SET utf8mb4;
CREATE USER 'web_word_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON web_word_db.* TO 'web_word_user'@'localhost';
\`\`\`

### 4. 运行应用

\`\`\`bash
streamlit run src/app.py
\`\`\`

### 5. 运行测试

\`\`\`bash
pytest --cov=src --cov-report=html
\`\`\`

### 6. 使用 Docker

\`\`\`bash
docker-compose up -d
\`\`\`

## 配置说明

### config/config.yaml

\`\`\`yaml
database:
  mysql:
    host: localhost
    port: 3306
    database: web_word_db
    user: web_word_user
    password: your_password
  pool:
    size: 5
    max_overflow: 10

app:
  model:
    provider: zhipu
    model_name: glm-4
    api_key_env: ZHIPU_API_KEY
\`\`\`

## API 集成

### 智谱 AI

\`\`\`bash
# 设置 API 密钥
export ZHIPU_API_KEY=your_api_key_here
\`\`\`

### 模型选择

支持以下模型提供商：
- zhipu: 智谱 AI (GLM-4)
- openai: OpenAI (GPT-4, GPT-3.5)
- deepseek: DeepSeek

## 测试

### 运行所有测试

\`\`\`bash
pytest
\`\`\`

### 运行并生成覆盖率报告

\`\`\`bash
pytest --cov=src --cov-report=html --cov-report=term
# 打开 htmlcov/index.html 查看详细报告
\`\`\`

## 安全检查

项目包含以下安全措施：

1. **输入验证**: SQL 注入和 XSS 防护
2. **API 密钥管理**: 环境变量存储
3. **错误处理**: 详细的错误日志

## 性能优化

1. **连接池**: MySQL 连接池配置
2. **缓存**: LLM 响应缓存（待实现）
3. **数据库索引**: 已优化索引

## 部署

### Hugging Face Spaces

1. 创建新 Space
2. 选择 Streamlit as runtime
3. 连接 GitHub 仓库
4. 推送代码到 main 分支自动部署

### Docker 部署

\`\`\`bash
docker-compose up -d
\`\`\`

### 手动部署

\`\`\`bash
streamlit run src/app.py --server.port=8501
\`\`\`

## 维护

### 更新依赖

\`\`\`bash
pip freeze > requirements.txt
\`\`\`

### 数据库迁移

\`\`\`bash
python scripts/migrate_db.py
\`\`\`

### 备份数据库

\`\`\`bash
mysqldump -u web_word_user -p web_word_db > backup.sql
\`\`\`

## 故障排除

### 数据库连接失败

检查：
1. MySQL 服务是否运行
2. config.yaml 中的配置是否正确
3. 用户权限是否正确

### API 密钥错误

检查：
1. .env 文件中的 API 密钥是否正确
2. 模型提供商是否配置正确

## 联系方式

如有问题或建议，请通过 GitHub Issues 联系。

---

**文档版本**: 1.0.0
**最后更新**: 2026/05/30
