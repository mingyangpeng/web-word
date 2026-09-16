# 配置说明

## 文件一览

| 文件 | 作用 | 是否跟踪 |
|------|------|----------|
| `config/config.yaml` | 应用实际读取的配置（`src/mysql_db.py`） | ✅ 已提交，不要删除 |
| `config/config.example.yaml` | 同结构模板，含注释与占位值 | ✅ 已提交 |
| `.env.example` | 环境变量模板（Docker 与本地都可参考） | ✅ 已提交 |
| `.env` | 你本机的实际环境变量 | ❌ 已被 `.gitignore` 忽略 |

换一台机器部署时，把示例复制成正式配置再改值即可：

```bash
cp config/config.example.yaml config/config.yaml
```

## 配置优先级（重要）

```
环境变量  >  config/config.yaml  >  代码内置默认值
```

`src/mysql_db.py` 按上面的顺序逐项取值：只要同名环境变量存在且非空，就覆盖 YAML。
这样同一份 `config/config.yaml` 能同时服务两种部署方式，部署方**不需要修改任何被
git 跟踪的文件**：

- **Docker Compose**：MySQL 主机名是 compose 服务名 `mysql`（由 `docker-compose.yml` 注入环境变量覆盖）
- **本地开发**：MySQL 主机名通常是 `127.0.0.1`

代码识别的环境变量名：

| 变量 | 含义 | 内置默认值 |
|------|------|-----------|
| `MYSQL_HOST` | 数据库主机 | `127.0.0.1` |
| `MYSQL_PORT` | 端口 | `3306` |
| `MYSQL_DATABASE` | 库名 | `web_word_db` |
| `MYSQL_USER` | 用户名 | `web_word_user` |
| `MYSQL_PASSWORD` | 密码 | 空 |
| `MYSQL_CHARSET` | 字符集 | `utf8mb4` |
| `MYSQL_COLLATION` | 排序规则 | `utf8mb4_unicode_ci` |

只改主机一个变量、不动 YAML：

```bash
MYSQL_HOST=127.0.0.1 streamlit run src/app.py
```

## config.yaml 结构

```yaml
database:
  mysql:
    host: mysql            # Docker 下的服务名；本地开发可改为 127.0.0.1
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

> `app.model.*` 目前是预留字段：`src/llm_api.py` 不读取 YAML，它直接读环境变量
> `ZHIPUAI_API_KEY` 与 `LLM_MODEL`。要换模型请改环境变量，不要改这里。

> `config/config.yaml` **不要加入 `.gitignore`**：它已被跟踪，且应用启动时就要读它。
> 想避免把本机密码提交上去，请用环境变量覆盖（见上表）。

## 本地 MySQL 从零搭建

### 1. 创建库与账号

```bash
mysql -u root -p
```

```sql
CREATE DATABASE IF NOT EXISTS web_word_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'web_word_user'@'localhost'
  IDENTIFIED BY 'webword123';
-- 库名里的下划线要写成 \_ ：GRANT 中 `_` 是单字符通配符，
-- 不转义会连带授权给 webXwordYdb 之类的无关库。
GRANT ALL PRIVILEGES ON `web\_word\_db`.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

> 更省事的做法：直接跑仓库内的一体化授权脚本（幂等，含迁移测试所需库）：
> ```bash
> mysql -u root -p < scripts/grant_local_mysql.sql
> ```

macOS（Homebrew）如刚装完 MySQL：

```bash
brew services start mysql
```

### 2. 验证连接

```bash
mysqladmin ping -h 127.0.0.1 -u web_word_user -pwebword123
mysql -h 127.0.0.1 -u web_word_user -pwebword123 web_word_db -e "SHOW TABLES;"
```

### 3. 建表

应用启动时会自动建表，无需手工执行；也可以直接用仓库内的 SQL：

```bash
mysql -h 127.0.0.1 -u web_word_user -pwebword123 < scripts/init_db.sql
```

五张表（见 `src/mysql_db.py` 的 `CREATE_TABLES_SQL` 与 `scripts/init_db.sql`）：

- `definitions` — 动词释义与 `semantic_table`（JSON：manner/path/direction/aspect/scope）
- `synonyms` — 近义关系（外键指向 `definitions`）
- `feedbacks` — 用户评分（1–5）与文字反馈
- `usage_logs` — 查询日志
- `statistics` — 统计数据

### 4. 启动应用

```bash
MYSQL_HOST=127.0.0.1 streamlit run src/app.py
```

数据库连不上时应用不会崩溃，会提示「MySQL 数据库不可用，使用离线模式」并继续提供
离线释义。

## Docker Compose 如何配置

`docker-compose.yml` 的行为：

1. 用 `mysql:8.0` 起数据库服务，服务名 `mysql`，端口 `3306:3306`；库名 `web_word_db`、
   用户 `web_word_user` 写死在 compose 里，密码取 `${MYSQL_PASSWORD:-webword123}`。
2. 首次启动执行 `scripts/init_db.sql`（挂到 `/docker-entrypoint-initdb.d/`）完成授权与建表。
3. 给 web 容器注入 `MYSQL_HOST=mysql`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、
   `MYSQL_PASSWORD`、`ZHIPUAI_API_KEY`。这些环境变量按上面的优先级覆盖 `config.yaml`，
   所以容器内 `config.yaml` 即使写 `localhost` 也能正常连上。
4. 数据落在命名卷 `web-word-mysql-data`，**不是**仓库里的 `data/mysql/`。

```bash
docker compose up -d
```

## 安全提醒

- `config/config.yaml` 里的密码是**开发用默认值**，生产环境请改掉，并优先用环境变量注入。
- 不要把真实密钥写进被跟踪的文件；`ZHIPUAI_API_KEY` 用环境变量或 `.env` 提供。
- `.env` 已在 `.gitignore` 中；但代码**没有**自动加载 `.env`（仓库内无 `load_dotenv`），
  启动前需自己 `export`，或 `set -a; source .env; set +a`。

## 故障排除

```bash
# PyYAML 是否可用
python -c "import yaml; print(yaml.__version__)"

# MySQL 进程
pgrep -x mysqld

# 查看当前实际生效的连接参数（已应用环境变量优先）
python -c "from src.mysql_db import MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER; print(MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER)"
```

若 `config/config.yaml` 完全缺失，`src/mysql_db.py` 会记录一条 warning 并整体退回到
「环境变量 + 内置默认值」，此时必须靠环境变量提供连接信息。
