# 配置说明

> 数据库配置的完整说明、从零搭建本地 MySQL 的步骤与故障排除，见
> [`config/README.md`](config/README.md)。本文件只做索引与速查。

## 配置分两类

| 类别 | 位置 | 谁在读 |
|------|------|--------|
| 数据库连接 | `config/config.yaml`（模板：`config/config.example.yaml`） | `src/mysql_db.py` |
| 其余全部设置 | 环境变量（模板：`.env.example`） | `src/llm_api.py`、`src/api.py`、`src/security.py` |

**优先级：环境变量 > `config/config.yaml` > 代码内置默认值。**

只要同名环境变量存在且非空就覆盖 YAML。这保证同一份被 git 跟踪的 `config.yaml` 能同时服务
Docker Compose（MySQL 主机名是服务名 `mysql`）与本地开发（主机名 `127.0.0.1`），部署方无需
修改任何被跟踪的文件。

## 环境变量清单

### 数据库（`src/mysql_db.py`）

| 变量 | 默认值 |
|------|--------|
| `MYSQL_HOST` | `127.0.0.1` |
| `MYSQL_PORT` | `3306` |
| `MYSQL_DATABASE` | `web_word_db` |
| `MYSQL_USER` | `web_word_user` |
| `MYSQL_PASSWORD` | 空 |
| `MYSQL_CHARSET` | `utf8mb4` |
| `MYSQL_COLLATION` | `utf8mb4_unicode_ci` |

### 大模型（`src/llm_api.py`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIPUAI_API_KEY` | 空 | **应用真正读取的 key**。为空则不创建客户端，释义降级为离线 |
| `LLM_MODEL` | `glm-4` | 模型名 |
| `LLM_TEMPERATURE` | `0.7` | |
| `LLM_MAX_TOKENS` | `500` | |
| `LLM_TIMEOUT` | `30` | 秒 |
| `CACHE_TTL_HOURS` | `24` | 释义在 MySQL 中的缓存时长 |

### Docker Compose 专用

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYSQL_ROOT_PASSWORD` | `rootpass123` | 仅 `docker-compose.yml` 的 mysql 服务读取，应用不读 |
| `MYSQL_PASSWORD` | `webword123` | Compose 注入给 web 容器 |

### 旧版 `src/api.py` / `src/security.py` 使用

`ZHIPU_API_KEY`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`DEFAULT_MODEL`、`TEMPERATURE`、
`MAX_TOKENS`。主应用 `src/app.py` 不导入这两个模块，因此运行应用**不需要**它们。

> 注意 `ZHIPU_API_KEY` 与 `ZHIPUAI_API_KEY` 是两个不同的名字：前者只被旧模块读取，后者才是
> 主应用读的。填错名字不会报错，只会静默走到离线释义。

### 无任何代码读取（预留）

`ENVIRONMENT`、`DEBUG`。

## `config.yaml` 结构

```yaml
database:
  mysql:
    host: mysql            # Docker 下为服务名；本地开发可改 127.0.0.1
    port: 3306
    database: web_word_db
    user: web_word_user
    password: "webword123"
    charset: utf8mb4
    collation: utf8mb4_unicode_ci
  pool:
    size: 5                # 连接池大小
    max_overflow: 10       # 最大溢出连接数

app:
  model:
    provider: zhipu        # 预留字段，当前代码未读取
    model_name: glm-4      # 预留字段，当前代码未读取
    api_key_env: ZHIPUAI_API_KEY

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

> `app.model.*` 是预留字段：`src/llm_api.py` 不读 YAML，只读环境变量。要换模型请改
> `LLM_MODEL`，别改这里。

## 换机器部署

```bash
cp config/config.example.yaml config/config.yaml   # 然后改值
```

`config/config.yaml` **故意不加入 `.gitignore`** —— 应用启动即需要它。想避免提交本机密码，
请用 `MYSQL_*` 环境变量覆盖，而不是删掉该文件。

## `.env` 不会被自动加载

仓库没有 `python-dotenv`，代码也不调用 `load_dotenv`。必须自己导出：

```bash
set -a; source .env; set +a
streamlit run src/app.py
```

PowerShell：

```powershell
Get-Content .env | Where-Object {$_ -match '^\s*[^#]'} | ForEach-Object {
  $k,$v = $_ -split '=',2; Set-Item "env:$k" $v
}
```

## 代码中如何读取

```python
# 数据库：已应用「环境变量优先」的最终值
from src.mysql_db import MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER
print(MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER)

# 原始 YAML（未经环境变量覆盖）
from src.mysql_db import get_config, get_mysql_config, get_pool_config
print(get_mysql_config())
print(get_pool_config())
```

## 故障排除

```bash
python -c "import yaml; print(yaml.__version__)"     # PyYAML 是否可用
pgrep -x mysqld                                      # MySQL 进程
mysqladmin ping -h 127.0.0.1 -u web_word_user -pwebword123
```

若 `config/config.yaml` 完全缺失，`src/mysql_db.py` 会记录一条 warning 并整体退回
「环境变量 + 内置默认值」，此时必须靠环境变量提供连接信息。应用不会因此崩溃 —— 数据库不可用
时页面会提示「MySQL 数据库不可用，使用离线模式」继续提供服务。
