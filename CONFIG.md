# 配置说明

## 📁 配置文件结构

```
web-word/
├── config/
│   ├── config.yaml          # 主配置文件（YAML 格式）
│   └── README.md            # 配置说明
│
├── data/
│   └── *.db                 # SQLite 数据库文件（备用）
│
└── src/
    └── mysql_db.py          # 使用 YAML 配置
```

## 📝 config.yaml 配置文件

### 数据库配置

```yaml
database:
  mysql:
    host: localhost              # MySQL 主机地址
    port: 3306                   # MySQL 端口
    database: web_word_db        # 数据库名称
    user: web_word_user          # 数据库用户名
    password: your_password      # 数据库密码
    charset: utf8mb4             # 字符集
    collation: utf8mb4_unicode_ci # 排序规则

  pool:
    size: 5                      # 连接池大小
    max_overflow: 10             # 最大溢出连接数

  sqlite:
    path: data/web_word.db       # SQLite 文件路径
    enabled: false               # 是否启用 SQLite
```

### 应用配置

```yaml
app:
  model:
    provider: zhipu              # 模型提供商：zhipu, openai, deepseek
    model_name: glm-4            # 模型名称
    api_key_env: ZHIPU_API_KEY   # API 密钥环境变量名
```

### 日志配置

```yaml
logging:
  level: INFO                    # 日志级别：DEBUG, INFO, WARNING, ERROR
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## 🚀 初始化数据库

### 1. 创建 MySQL 数据库和用户

```bash
# 连接 MySQL
mysql -u root -p

# 在 MySQL 命令行中执行：
CREATE DATABASE IF NOT EXISTS web_word_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'web_word_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON web_word_db.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 重新启动 MySQL 服务（如果在后台运行的）
brew services restart mysql@8.0
```

### 2. 测试连接

```bash
# 测试 MySQL 连接
mysqladmin ping -h localhost -u web_word_user -pyour_password
```

### 3. 运行应用

```bash
streamlit run src/app.py
```

应用启动时会自动：
- 从 `config.yaml` 加载配置
- 初始化 MySQL 数据库
- 创建所有必需的表（definitions, synonyms, feedbacks, usage_logs, statistics）

## 🔧 Python 配置加载示例

### 从 yaml 文件加载配置

```python
import yaml
from src.mysql_db import get_config, get_mysql_config

# 方法 1: 使用提供的辅助函数
config = get_config()
mysql_config = get_mysql_config()

# 方法 2: 直接使用 yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# 访问配置
database_name = config['database']['mysql']['database']
host = config['database']['mysql']['host']
```

### 模块配置变量

配置文件加载后，`src/mysql_db.py` 中的变量会自动从配置读取：

```python
from src.mysql_db import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_DATABASE,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_POOL_SIZE,
    MYSQL_POOL_MAX_OVERFLOW
)

print(f"连接到: {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
```

## 📦 依赖项

安装必要的 Python 包：

```bash
pip install pymysql pyyaml
```

## 🔐 安全建议

1. **不要在代码中硬编码密码**
   - ✅ 使用 `config.yaml` 配置文件
   - ✅ 在生产环境中使用环境变量或密钥管理服务
   - ❌ 不要将 `config.yaml` 提交到 Git

2. **文件权限**
   ```bash
   # 确保配置文件只有所有者可读
   chmod 600 config/config.yaml
   ```

3. **备份配置**
   - 定期备份 `config.yaml` 文件
   - 使用版本控制跟踪配置更改

## 🐛 故障排除

### 配置文件加载失败

```python
# 检查 PyYAML 是否安装
python -c "import yaml; print(yaml.__version__)"
```

### MySQL 连接失败

```bash
# 检查 MySQL 服务状态
pgrep -x mysqld

# 检查连接
mysql -u web_word_user -p -h localhost
```

### 数据库表不存在

应用启动时会自动创建表。如果表创建失败：
1. 检查 MySQL 用户权限
2. 检查数据库是否已创建
3. 查看应用日志获取详细错误信息
