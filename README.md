# 中文动词释义优化器

基于 **Talmy 运动事件类型学**的中文动词语义分解与释义优化系统。输入一个中文动词
（如「跑进来」），系统返回由**方式 / 路径 / 方向 / 体相 / 范围**五元语义分解构成的
优化释义，并可与传统词典式释义对照；同时提供示例库、用户评分反馈、热门动词统计与
反馈数据导出。界面为 Streamlit 单页应用（中文）。

## ✨ 功能特性

- **五元语义分解**：`semantic_table` 为五个键的字典 —— `manner`（方式）、`path`（路径）、
  `direction`（方向）、`aspect`（体相）、`scope`（范围），在界面中以彩色表格渲染。
- **释义分级策略**：查询时按 **数据库命中 → 实时大模型生成 → 内置示例 → 兜底占位** 的顺序
  取数，任一级不可用都不会中断页面（见 `src/app.py: get_display_definition`）。
- **结果卡片**：原型与位移事件分析 / 范畴锚定 / 核心释义与多维辨异 / 图式示例，四张可折叠卡片。
- **示例库**：三个分类标签页（方式聚焦类 / 路径聚焦类 / 体相聚焦类），点击动词即填充搜索框并查询。
- **固定置顶搜索栏**：搜索框随页面滚动固定在顶部。
- **侧边栏**：实验统计（总查询次数、已收录词条、平均评分、总反馈数）、热门查询动词
  （可本地子串筛选、点击即查）、反馈数据 CSV 导出；侧边栏可折叠为窄图标栏。
- **用户反馈**：1–5 星评分 + 文字建议，写入 `feedbacks` 表。
- **安全校验**：`src/security.py` 对输入做 SQL 注入与 XSS 模式校验，输出做 HTML 转义。
- **离线可用**：没有智谱 API key 也能启动并返回释义（详见下文「常见问题」）。

## 🚀 快速开始

前置：**Python 3.11+**。数据库为 **MySQL 8.0**（应用不使用 SQLite）。

两条路径任选其一；两条路径都用同一份 `requirements.txt`。

### 路径 A：Docker Compose 一键启动

```bash
git clone <repo-url> && cd web-word

# 可选：配置智谱 API key，用于实时生成释义
cp .env.example .env
# 编辑 .env，填入 ZHIPUAI_API_KEY=你的key

docker compose up -d
docker compose logs -f web      # 查看启动日志
```

打开 <http://localhost:8501>。

MySQL 由 Compose 自动起（`mysql:8.0`，服务名 `mysql`），数据写入命名卷
`web-word-mysql-data`，首次启动执行 `scripts/init_db.sql` 建表。`docker-compose.yml`
会给 web 容器注入 `MYSQL_HOST=mysql` 等环境变量，**不需要改 `config/config.yaml`**。

停止与清理：

```bash
docker compose down            # 停止容器，保留数据卷
docker compose down -v         # 连数据卷一起删除（会清空数据库）
```

### 路径 B：本地 Python + 本地 MySQL

**1）准备 MySQL 8.0 的库与账号**

```bash
mysql -u root -p
```

```sql
CREATE DATABASE IF NOT EXISTS web_word_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'web_word_user'@'localhost'
  IDENTIFIED BY 'webword123';
GRANT ALL PRIVILEGES ON web_word_db.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

macOS（Homebrew）如刚装完 MySQL：`brew services start mysql`。

**2）安装依赖并配置环境变量**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env：本地开发把 MYSQL_HOST 设为 127.0.0.1
set -a; source .env; set +a      # 本项目没有 python-dotenv，必须手动导出
```

> Windows PowerShell：
> ```powershell
> Get-Content .env | Where-Object {$_ -match '^\s*[^#]'} | ForEach-Object {
>   $k,$v = $_ -split '=',2; Set-Item "env:$k" $v
> }
> ```

**3）启动应用**

```bash
streamlit run src/app.py
```

打开 <http://localhost:8501>。建表由应用启动时自动完成。

> 不想动 `.env` 也可以只临时覆盖主机名：
> `MYSQL_HOST=127.0.0.1 streamlit run src/app.py`
> 环境变量优先级高于 `config/config.yaml`（详见 `config/README.md`）。

**4）（可选）灌入词库**

```bash
python scripts/load_word_library.py            # 离线，无网络依赖
```

## 📁 目录结构

```
web-word/
├── src/                        # 应用源码
│   ├── app.py                  # Streamlit 主应用（界面、卡片、反馈、侧边栏）
│   ├── mysql_db.py             # MySQL 8.0 数据访问层（连接、建表、CRUD、统计）
│   ├── llm_api.py              # 智谱 AI 封装（调用、解析、MySQL 缓存、兜底释义）
│   ├── design_system.py        # 设计系统常量与样式生成
│   ├── security.py             # 输入校验（SQL 注入 / XSS）与密钥掩码
│   ├── api.py                  # 旧版多提供商 LLM 封装，主流程未使用（见「已知遗留」）
│   ├── database.py             # 旧版 SQLite 模块，已废弃（见「已知遗留」）
│   └── .streamlit/config.toml  # Streamlit 运行配置
├── config/
│   ├── config.yaml             # 应用实际读取的数据库配置（已提交）
│   ├── config.example.yaml     # 同结构模板（含注释，推荐复制后修改）
│   └── README.md               # 配置优先级与环境变量说明
├── scripts/
│   ├── entrypoint.sh           # 容器入口：等 MySQL → 启动 Streamlit
│   ├── wait_for_mysql.py       # TCP 探活等待 MySQL（Docker 使用）
│   ├── wait-for-mysql.sh       # 同上，bash 版本备用
│   ├── init_db.sql             # 建表与授权 SQL（Compose 首启动执行）
│   ├── load_word_library.py    # 离线灌词库（读仓库内 JSON，零网络依赖）
│   ├── ingest_motion_verbs.py  # 解析 docx + 联网抓释义（需 python-docx、requests）
│   ├── migrate_db.py           # 旧 SQLite → MySQL 迁移脚本
│   └── get-stats.sh/.js        # 项目统计（GSD 工作流辅助）
├── tests/                      # pytest 测试（见「测试」）
├── data/                       # 运行期数据（已被 .gitignore 忽略）
│   ├── docs/                   # 原始 docx 资料
│   ├── motion_verbs_extracted.json / oxford_cache.json  # 词库与释义缓存
│   └── mysql/                  # 本机 MySQL datadir（不提交）
├── docs/                       # 设计系统文档
├── screenshots_final/          # 界面截图
├── graphify-out/               # 代码图谱生成物（已忽略）
├── .planning/                  # GSD 阶段性规划与归档
├── Dockerfile / docker-compose.yml
├── requirements.txt
└── README.md / CLAUDE.md / ARCHITECTURE.md / CHANGELOG.md / CONFIG.md / TESTING.md
```

## ⚙️ 配置说明

应用配置分两层：

1. **数据库连接** — `config/config.yaml`，YAML 结构，键为
   `database.mysql.{host,port,database,user,password,charset,collation}` 与
   `database.pool.{size,max_overflow}`。
2. **环境变量** — 见 `.env.example`。LLM 相关（`ZHIPUAI_API_KEY`、`LLM_MODEL` 等）
   只走环境变量，`src/llm_api.py` **不读 YAML**。

**优先级：环境变量 > `config/config.yaml` > 代码内置默认值。** 只要同名环境变量存在且
非空，就覆盖 YAML。这样同一份 `config/config.yaml` 能同时服务 Docker（主机名 `mysql`）
与本地开发（主机名 `127.0.0.1`），无需修改被 git 跟踪的文件。

代码识别的数据库环境变量：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、
`MYSQL_PASSWORD`、`MYSQL_CHARSET`、`MYSQL_COLLATION`。

> 换机器部署时复制模板即可：`cp config/config.example.yaml config/config.yaml`。
> `config/config.yaml` **故意不加入 `.gitignore`** —— 应用启动就要读它；想避免提交本机
> 密码，请用环境变量覆盖。

完整的字段说明、从零搭建本地 MySQL 的步骤、Compose 的注入行为与故障排除，见
[`config/README.md`](config/README.md)。

## 🕸️ 知识图谱（词间关系 + 代码结构）

项目维护**两张**图谱，都是本地生成、可离线重建。

### 1. 词间关系图谱：`data/word_graph.json`

节点是动词，边是「近义」关系。关系来源是词库里的**次语义范畴**（`sub_cat`）：
同一次范畴的动词语义相近，构成近义簇，例如

| 次范畴 | 成员示例 |
|--------|----------|
| 处所脱离 | abandon · desert · leave |
| 奔跑行进 | bolt · canter · charge · dart · dash · gallop … |
| 攀爬匍匐 | clamber · crawl · creep · scramble |
| 同行随行 | accompany · conduct · escort |

小簇（≤6 词）连成完全图——任意两词互为近义；大簇（如 56 词的「常态行走」）
每个词只连左右各 3 个邻居，避免每个词都变成 55 度的枢纽。当前共 155 节点、
369 条边、25 个簇，最大度 6。

这张图同时灌进 MySQL 的 `synonyms` 表（双向写入 738 行），应用里「图式示例」
卡片展示的近义动词就来自它。重建：

```bash
python scripts/load_word_library.py --dry-run   # 只重建图谱文件，不写库
python scripts/load_word_library.py             # 重建图谱 + 灌入 MySQL
```

查询（需要 `graphify` CLI，见下）：

```bash
graphify explain "abandon" --graph data/word_graph.json   # 看它的近义邻居
graphify path "abandon" "leave" --graph data/word_graph.json
```

### 2. 代码结构图谱：`graphify-out/`

用 [graphify](https://pypi.org/project/graphifyy/) 对源码做 AST 解析（纯本地，
**不需要任何 API key**），产出社区划分、枢纽节点与意外连接报告，以及可在浏览器
点击浏览的 `graph.html`。

```bash
# 一次性安装
uv tool install graphifyy
export PATH="$HOME/.local/bin:$PATH"     # uv tool 的默认安装目录常不在 PATH

# 重建两张图
scripts/build_knowledge_graphs.sh

# 也可以只重建代码图谱 / 只重建词间图谱
scripts/build_knowledge_graphs.sh --code
scripts/build_knowledge_graphs.sh --words
```

日常查询：

```bash
graphify query "释义生成的数据流"           # 按概念找相关节点与执行流
graphify explain get_display_definition    # 某个符号的 360° 视图（调用者/被调用者）
graphify impact get_display_definition     # 改这个函数会影响谁
graphify god-nodes --top 10                # 架构枢纽节点
```

`graphify-out/` 与 `data/word_graph.json` 都已提交或按需重建；前者已被 `.gitignore`
忽略（属生成物），后者随 `data/word_graph.json` 一并入库。图谱构建范围由仓库根目录的
`.graphifyignore` 控制（排除数据目录、历史归档文档等，只索引源码与当前文档）。

## 🧪 测试

```bash
pip install -r requirements.txt

# 常规运行（pytest.ini 默认带覆盖率：--cov=src --cov-report=html）
pytest

# 不看覆盖率、跑得快一些
python -m pytest -q -p no:cacheprovider --no-cov

# 只跑某个文件
pytest tests/test_security.py
```

覆盖率 HTML 报告输出到 `htmlcov/index.html`。测试用 `monkeypatch` 隔离外部依赖，
不会真实调用智谱 API 或 MySQL。

测试文件与覆盖内容：

| 文件 | 内容 |
|------|------|
| `tests/test_phase5.py` | 释义分级策略（DB → LLM → 兜底）、LLM 结果持久化、缺 key 不崩溃 |
| `tests/test_phase4.py` | 侧边栏折叠 / 统计 / 热门动词筛选 |
| `tests/test_search_bar.py` | 固定置顶搜索栏回归测试 |
| `tests/test_security.py` | 输入校验与密钥掩码 |
| `tests/test_api.py` | 旧版 `src/api.py` 的 LLM 封装 |

## ❓ 常见问题

**MySQL 连不上怎么办？**

应用不会因此崩溃，会提示「⚠️ MySQL 数据库不可用，使用离线模式」，功能降级为离线释义。
排查顺序：

```bash
# 1. 进程是否在跑
pgrep -x mysqld
# 2. 端口是否可达
mysqladmin ping -h 127.0.0.1 -u web_word_user -pwebword123
# 3. 看当前生效的连接参数
python -c "from src.mysql_db import MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER; print(MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER)"
```

常见原因：

- **主机名不对**：`config/config.yaml` 里默认是 Docker 服务名 `mysql`。本地跑必须用
  `MYSQL_HOST=127.0.0.1` 覆盖（环境变量优先，不用改文件）。
- **Docker 反了**：容器内**不要**设 `MYSQL_HOST=127.0.0.1`，那会指向容器自己；Compose 已
  自动注入 `mysql`。
- **账号/密码**：默认开发凭据是 `web_word_user` / `webword123`，需与
  `docker-compose.yml` 的 `MYSQL_PASSWORD`（默认 `webword123`）一致。
- **库没建**：见「快速开始 → 路径 B」第 1 步的 `CREATE DATABASE` / `CREATE USER` / `GRANT`。

**智谱 API key 怎么配？**

在 [智谱开放平台](https://open.bigmodel.cn/) 申请 key，然后导出环境变量 —— 变量名是
**`ZHIPUAI_API_KEY`**（注意中间的 `AI`，`src/llm_api.py` 读的就是这个名字）：

```bash
export ZHIPUAI_API_KEY=你的key
streamlit run src/app.py
```

或写进 `.env`（`.env` 已被 gitignore）后 `set -a; source .env; set +a`。可选调优变量见
`.env.example`：`LLM_MODEL`（默认 `glm-4`）、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、
`LLM_TIMEOUT`、`CACHE_TTL_HOURS`。

> `.env.example` 里另有旧名 `ZHIPU_API_KEY`，那是旧版 `src/api.py` / `src/security.py`
> 读的，主应用不读它 —— 填错名字只会静默走到离线释义。

**为什么没有 API key 也能跑？**

因为释义获取是分级的（`src/app.py: get_display_definition`，优先级从高到低）：

1. **数据库命中** —— `definitions` 表里已有该动词就直出；
2. **实时大模型生成** —— 调用智谱 AI（需要 `ZHIPUAI_API_KEY`），成功后写回数据库做缓存；
3. **内置示例** —— `src/app.py` 的 `MOCK_DEFINITIONS`；
4. **兜底占位** —— `src/llm_api.py: get_fallback_definition()` 返回「待生成」骨架。

没有 key 时第 2 步会被跳过（`src/llm_api.py` 检测到空 key 就不会创建客户端），页面照常渲染，
只是释义来自第 1/3/4 级，并提示「实时生成暂不可用，已显示离线释义」。同理，MySQL 不可用时
也能启动。所以本项目的默认体验是「**离线可跑，配 key 才更聪明**」。

**为什么搜索不到某个动词？**

只有已在数据库、内置示例或大模型可生成范围内的动词才有释义；其余会落到兜底占位
（五元字段显示「待生成」）。灌库可用 `python scripts/load_word_library.py`。

**端口 8501 被占用？**

`streamlit run src/app.py --server.port=8502`，或改动 `src/.streamlit/config.toml`。

## 🐳 Docker 说明

```bash
docker compose up -d           # 启动（构建 web 镜像 + mysql:8.0）
docker compose logs -f web     # 跟随应用日志
docker compose down            # 停止
```

- web 容器启动流程：`scripts/entrypoint.sh` → `scripts/wait_for_mysql.py` 探活
  `$MYSQL_HOST:$MYSQL_PORT`（最多 30 次 × 2 秒）→ `streamlit run src/app.py`。
- 探活超时也不会失败退出，而是以 **离线模式** 启动应用。
- 端口：web `8501:8501`，MySQL `3306:3306`；数据分别在命名卷
  `web-word-app-data` 与 `web-word-mysql-data`。

## 📌 已知遗留

- `src/database.py` 是**旧版 SQLite 模块**，当前应用完全走 MySQL（`src/mysql_db.py`），
  `src/` 内无任何文件导入它；仅 `tests/conftest.py` 导入了 `init_db`，其 `test_db` fixture
  是空实现。保留待清理。
- `src/api.py` 是**第二套 LLM 封装**，`src/app.py` 不导入它（应用只用 `src/llm_api.py`）；
  `tests/test_api.py` 覆盖它，故保留。
- `src/mysql_db.py: migrate_from_sqlite()` 是历史迁移入口，与上述遗留模块同理。
- `graphify-out/`、`.gsd/`、`.planning/milestone.lock`、`data/` 均为本机运行产物，已被忽略。
