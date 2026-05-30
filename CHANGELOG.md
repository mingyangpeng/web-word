# 数据库配置更新日志

## 更新时间
2026/05/30

## 更改摘要

从 `.env` 文件迁移到 `config.yaml` 配置文件，使用 Python 的 PyYAML 库读取配置。

## 主要更改

### 1. 删除 SQLite 数据库
- ✅ 删除 `data/web_word.db` 文件
- SQLite 不再是主要数据库，MySQL 取代其位置

### 2. 创建 YAML 配置文件
- ✅ 创建 `config/config.yaml` 配置文件
- 使用 YAML 格式，结构化、易读、易维护
- 支持数据库配置、应用配置、日志配置

### 3. 更新 Python 代码
- ✅ 更新 `src/mysql_db.py` 以使用 YAML 配置
- 添加 `yaml` 库导入
- 实现 `load_config()`, `get_config()`, `get_mysql_config()`, `get_pool_config()` 函数
- 配置变量从 YAML 文件读取，不再使用环境变量

### 4. 添加依赖
- ✅ 安装 `PyYAML` Python 包

### 5. 创建测试和文档
- ✅ 创建 `test_config.py` 测试脚本
- ✅ 创建 `CONFIG.md` 配置说明文档
- ✅ 更新 `ARCHITECTURE.md` 架构文档

## 配置文件结构

```yaml
# config/config.yaml

database:
  mysql:
    host: localhost
    port: 3306
    database: web_word_db
    user: web_word_user
    password: web_project_pass123
    charset: utf8mb4
    collation: utf8mb4_unicode_ci

  pool:
    size: 5
    max_overflow: 10

  sqlite:
    path: data/web_word.db
    enabled: false

app:
  model:
    provider: zhipu
    model_name: glm-4
    api_key_env: ZHIPU_API_KEY

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## Python API

### 加载配置

```python
from src.mysql_db import get_config, get_mysql_config

# 获取完整配置
config = get_config()
print(config['database']['mysql']['host'])

# 获取 MySQL 配置
mysql_config = get_mysql_config()
print(f"连接到 {mysql_config['database']}")

# 获取连接池配置
pool_config = get_pool_config()
print(f"连接池大小: {pool_config['size']}")
```

### 模块配置变量

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
```

## 优势

1. **结构化配置**：YAML 格式更清晰，支持注释
2. **类型提示**：YAML 可以包含类型信息
3. **嵌套结构**：便于组织复杂配置
4. **版本控制**：YAML 文件更适合 Git 比较
5. **Python 优先**：直接使用 Python 读取，无需环境变量解析

## 迁移指南

如果你之前使用 `.env` 文件：

1. ✅ 已完成迁移，无需手动操作
2. 配置文件位置：`config/config.yaml`
3. 配置变量从模块导入：`from src.mysql_db import MYSQL_HOST`

## 测试

运行测试脚本验证配置加载：

```bash
python test_config.py
```

预期输出：

```
配置加载测试
============================================================
1. YAML 可用性: ✅ 是
2. 配置文件加载: ✅ 配置文件已加载
3. MySQL 配置: ✅ MySQL 配置已获取
4. 连接池配置: ✅ 连接池配置已获取
============================================================
```

## 下一步

1. 初始化 MySQL 数据库（如果尚未完成）
2. 运行应用：`streamlit run src/app.py`
3. 查看日志输出验证配置加载

## 参考资料

- [CONFIG.md](CONFIG.md) - 详细配置说明
- [ARCHITECTURE.md](ARCHITECTURE.md) - 系统架构文档
- [PyYAML 文档](https://pyyaml.org/)
