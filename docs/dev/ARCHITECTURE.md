# 架构说明

本文件描述**当前代码**的分层、模块职责与数据流，与 `README.md` 的快速开始互补。
阶段性的设计讨论与决策记录不在这里，而在 `.planning/`（尤其是 `.planning/codebase/`
与各 phase 的 CONTEXT / DISCUSSION-LOG）。

## 一句话架构

Streamlit 单进程应用：界面层（`src/app.py`）在渲染过程中同步调用「释义适配层」，适配层
依次尝试数据库（MySQL 8.0）、大模型（多供应商：智谱 / OpenAI 兼容 / DeepSeek）、内置
示例，任一环节不可用即降级，因此**数据库或 API key 缺失都不会让页面崩溃**。

```
用户（浏览器）
    │
    ▼
Streamlit 界面       src/app.py
    │                搜索栏（固定置顶）/ 六张结果卡片 / 示例库 / 反馈表单 / 侧边栏
    │
    ▼
释义适配层            src/app.py: get_display_definition()
    │                优先级：数据库 → 实时大模型 → 内置示例 → 兜底骨架
    │
    ├──────────────► 数据访问层   src/mysql_db.py     MySQL 8.0
    │                连接池、建表、CRUD、统计、查询日志
    │
    ├──────────────► 协作层   src/users_db.py · src/annotation_flow.py · src/reliability.py
    │                多人标注：账号角色 / 任务分配 / 提交·分歧·仲裁 / Krippendorff's α 信度
    │
    └──────────────► 大模型封装   src/llm_api.py      多供应商（zhipu/openai/deepseek）
                     提示词、调用、JSON 解析、MySQL 缓存、兜底释义
                     供应商注册/路由数据面 src/llm_providers_db.py（🤖 模型供应商页）

横切  src/security.py（输入校验 / HTML 转义 / 密钥掩码）
      src/design_system.py（颜色、间距、字体、组件样式）
```

## 分层与模块职责

### 界面层 — `src/app.py`

- 页面配置与 `session_state` 初始化（卡片折叠状态、侧边栏折叠状态）；页面体系为
  **十七页**（`page_guides.py: PAGE_KEYS=17` 单一事实源，16 个显式分支 + search 兜底），
  按 `_PAGE_ACCESS` 角色矩阵过滤（六角色：词典管理员/平台管理员/审校/编纂/标注/只读）。
- 启动时调用 `init_database()`；失败则置 `DB_AVAILABLE = False` 并在页面提示
  「MySQL 数据库不可用，使用离线模式」，随后统计 / 导出 / 反馈写入全部走空数据分支。
- 界面组成：
  - **固定置顶搜索栏**（`st.container(key="search_bar")` + CSS `position: sticky`）；
  - **结果六卡片**：原型与位移事件分析 / 范畴锚定 / 义位标注 / 核心释义与多维辨异 /
    图式示例 / 语料库证据（enTenTen21），各自可折叠；
  - **示例库**：三个分类标签页（方式聚焦类 / 路径聚焦类 / 体相聚焦类），点击动词回调
    `select_example_verb()`；
  - **反馈表单**：1–5 星 `select_slider` + 文字 `text_area`，提交写入 `feedbacks` 表；
  - **侧边栏**：实验统计、热门动词（本地子串筛选 + 点击查询）、反馈 CSV 导出，可折叠为窄图标栏。
- `MOCK_DEFINITIONS`、`EXAMPLE_VERBS`、`CATEGORY_*`、`SEMANTIC_COLORS`、`THEORY_DESCRIPTION`
  等常量集中在文件内，供离线路径与示例库使用。

### 释义适配层 — `get_display_definition()`（同在 `src/app.py`）

统一出口，返回规范化的 `{traditional, optimized, semantic_table, example}`。取数顺序：

1. **输入校验** — `InputValidator.validate_string(verb, max_length=50)` 不通过则直接兜底，
   非法输入不进入提示词。
2. **数据库命中** — `get_definition_by_verb()`；命中即返回（`chinese_ndef` 中若同时存了传统与
   优化两段，由 `_restore_trad_opt()` 拆回）。
3. **实时大模型** — `llm_api.get_definition()`；成功后立刻 `mysql_db_persist()` 回写数据库作为
   缓存，下次查询走第 2 步。
4. **内置示例** — `MOCK_DEFINITIONS`。
5. **兜底骨架** — `llm_api.get_fallback_definition()`，五元字段显示「待生成」。

第 3 步被包在 `st.spinner` 与 `try/except` 中，异常只提示「实时生成暂不可用，已显示离线释义」。

### 数据访问层 — `src/mysql_db.py`

- 配置：启动时读 `config/config.yaml`，**环境变量优先于 YAML**，再退回内置默认值
  （`_setting(env_key, yaml_key, default)`）。变量名见 `config/README.md`。
- 连接：`get_connection_pool()` / `get_db_cursor()`（上下文管理器）；`init_database(max_retries=3,
  retry_delay=2.0)` 启动时带重试建表，以适配 Docker 中 MySQL 尚未就绪的情况。
- 表（核心词库域 `CREATE_TABLES_SQL`；全库 49 张表分属各数据层模块，
  `scripts/init_db.sql` 只建库与授权、不复制 DDL）：

  | 表 | 用途 | 关键字段 |
  |----|------|----------|
  | `word_clusters` | 词簇（main_cat × sub_cat） | `uq_word_clusters_cats` |
  | `definitions` | 动词释义 | `verb`(唯一) / `chinese_ndef` / `semantic_table`(JSON) / `cluster_id` / `phonetic` |
  | `word_relations` | 词间关系（簇内完全图） | `uq_word_relations_pair`、`CHECK(verb_a_id < verb_b_id)` |
  | `word_senses` / `oald_senses` | 中英对照义位 / OALD10 义项 | `sense_index` 等 |
  | `feedbacks` | 用户反馈 | `verb` / `rating`(1–5) / `feedback_text` |
  | `usage_logs` | 查询日志 | `verb` / `query_time` / `device_info` |
  | `schema_migrations` | 结构版本记录 | 供 `init_database()` 判断迁移 |

  协作/编纂/媒体/供应商/导入导出等域的表见 `src/users_db.py`、`annotation_flow.py`、
  `reliability.py`、`category_study.py`、`zh_dict.py`、`media_db.py`、`writing_db.py`、
  `lexical_db.py`、`llm_providers_db.py`、`registry_db.py` 等模块各自的 DDL。
- 主要函数：`insert_definition` / `get_definition_by_verb` / `get_all_definitions`；
  `get_cluster_graph(…)` / `get_hot_verbs`（带 cache）；`insert_feedback` /
  `get_feedback_by_verb` / `get_feedback_data`；`log_usage` / `clear_old_usage_logs`。
- 统计口径：`total_queries` 来自 `usage_logs`（真实查询次数），`total_definitions` 是已收录
  词条数，两者分开统计，不互相冒充。
- 性能口径（批次 13）：`init_database()` 有会话级单例守卫（`_init_db_done`，每会话只跑
  一次 DDL）；`get_full_word_graph` / `get_hot_verbs` 走 `st.cache_data`；装配/义项脊柱/
  版本历史/模板逐义项已收敛为批量查询（N+1 修复，契约见 `tests/test_fx13_fixes.py`）。

### 大模型封装 — `src/llm_api.py`（多供应商）

- **多供应商路由**：默认按优先级自动选择 智谱（`ZHIPUAI_API_KEY`，可加
  `ZHIPUAI_BASE_URL` 指向 OpenAI 兼容网关）→ OpenAI（`OPENAI_API_KEY`）→
  DeepSeek（`DEEPSEEK_API_KEY`）；`LLM_PROVIDER=zhipu|openai|deepseek` 可强制指定。
  **DB 优先**：`src/llm_providers_db.py` 注册的供应商（「🤖 模型供应商」页管理，
  `enabled` + `is_default` 口径）优先生效；环境变量链为无 DB 配置时的兜底。
- 模型名 `ZHIPUAI_MODEL`（或 `LLM_MODEL`，默认 `glm-4`）、`LLM_TEMPERATURE`、
  `LLM_MAX_TOKENS`、`LLM_TIMEOUT`、`CACHE_TTL_HOURS` 均可由环境变量调整。
- 提示词 `PROMPT_TEMPLATE` 要求模型返回 JSON，字段含 `traditional` / `optimized` /
  `chinese_ndef` / `semantic_table`（五键：`manner` 方式、`path` 路径、`direction` 方向、
  `aspect` 体相、`scope` 范围）/ `example` / `synonyms`。
- `_parse_llm_response()` 从可能带 Markdown 代码块的回复中提取 JSON。
- 缓存：命中 `get_definition_from_cache()` 直接返回；成功后 `save_definition_to_cache()` 写回
  `definitions` 表，TTL 由 `CACHE_TTL_HOURS` 控制。
- 关键点：无任何可用供应商（DB 注册全关＋环境变量 key 全空）时 `get_definition()`
  返回 `None`，适配层自动降级，应用照常运行。
- 另提供 `generate_batch_definitions()`、`get_synonyms_for_verb()`、
  `get_fallback_definition()` 与异常体系（`LLMError` / `APIKeyError` / `RateLimitError`）。

### 横切模块

- `src/security.py` — `InputValidator`（SQL 注入与 XSS 模式正则校验、`sanitize_html`）与
  `KeyManager`（读取 / 掩码 `ZHIPU_API_KEY` 等旧名环境变量）。主应用只用 `InputValidator`。
- `src/design_system.py` — 颜色、间距、字体常量与样式生成函数（卡片、按钮、徽章等），由
  `src/app.py` 统一引用以保持视觉一致。

### 数据库表结构（MySQL 8.0）

结构权威是 `src/mysql_db.py: CREATE_TABLES_SQL`；`scripts/init_db.sql` 只负责建库与授权，
不再复制建表语句（否则两份 DDL 会漂移，且它以 root 身份先于应用执行，会静默锁死旧结构）。

```
word_clusters ──1:N──► definitions ──N:M(物化)──► word_relations
   (main_cat, sub_cat)      cluster_id                 无向：a<b 且 pair 唯一
        │                        │
        └────────────────────────┴──► v_cluster_complete_graph（视图：由簇推导完全图）

feedbacks    用户评分/反馈（CHECK rating 1..5）
usage_logs   查询日志 —— 「热门动词」「总查询次数」的唯一数据来源
schema_migrations  结构版本，供 init_database() 决定是否迁移
```

**词间关系 = 簇内完全图**：同一次语义范畴内的两两动词都有一条边，物化进
`word_relations`（171 词 / 12 次类簇 → 1935 条边），`definitions.cluster_id` 是它的推导依据。
词目分类来自 `docs/Levin移动动词候选词筛选表.xlsx`；义位明细另存 `word_senses`，
释义来源分级见 `docs/英语自移移动动词词表.docx`，
视图 `v_cluster_complete_graph` 提供「从簇推导」的对照实现，两者边数必须相等。

**迁移自动且幂等**：`init_database()` 每次启动调用 `_migrate_schema()`，用
`information_schema` 探测后按需 ALTER / DROP（补 `cluster_id`、删旧 `synonyms` 与死表
`statistics`、写版本号）。业务表行原地保留，只有 `synonyms` 的旧环邻边被丢弃
（它是新完全图的错误子集，跑一次灌库脚本即重建）。

### 词簇图谱的三层接口

词与词的关系在三个层次上可用，同一份数据（`word_clusters` + `word_relations`）：

| 层次 | 入口 | 用途 |
|------|------|------|
| 数据 | `get_cluster_graph(verb)` / `get_cluster_graph_by_id(id)` / `list_clusters()` | 返回 `{nodes, links}`（结构对齐 graphify 的 graph.json） |
| 文件 | `data/word_graph.json`（`scripts/load_word_library.py` 生成） | 审阅、导出、喂给 graphify CLI |
| 页面（单簇） | `app.py` + `src/graph_export.py`（vis-network HTML，vendored） | 跟随查询词的交互完全图，可切换簇 / 缩放 / 点击成员切词 |
| 页面（全库） | `app.py: render_interactive_graph_page()` + `src/graph_export.py` | graphify 风格力导向图：171 词 / 1935 边，可搜索、点选、按簇过滤；静态 HTML + iframe，数据指纹命名 |

页面渲染用 **vendored vis-network**（`src/static/vis-network.min.js` 本地加载，不引 CDN
——内网零网络依赖）导出为**静态 HTML 文件 + iframe**，文件名带数据指纹：数据不变
不重载，页内重跑保留选中节点与拖动状态（单簇完全图与全库力导向图同用这一套）。

### 知识图谱（两张，均可离线重建）

| 图谱 | 产物 | 内容 |
|------|------|------|
| 代码结构图谱 | `graphify-out/graph.json` + `GRAPH_REPORT.md` + `graph.html` | graphify 对源码做 AST 解析（不需 API key），给出社区划分、枢纽节点、执行流 |
| 词间关系图谱 | `data/word_graph.json` | 节点=动词，边=近义关系；来源是词库的次语义范畴 `sub_cat` |

两者由 `scripts/build_knowledge_graphs.sh` 统一重建；索引范围由 `.graphifyignore`
控制（排除数据目录与历史归档文档）。词间关系同时灌入 MySQL `word_relations` 表，
供应用「图式示例」卡片展示近义词。

> 历史包袱已清理（2026-09）：`src/database.py`（旧 SQLite 模块）、`src/api.py`
> （第二套 LLM 封装，依赖的 `zhipuai.model_api` 在 SDK v2 已移除、实际不可用）、
> `tests/conftest.py`（空 fixture）、`tests/test_api.py`、`scripts/migrate_db.py`
> （读已不存在的 `config['database']['sqlite']`，一跑就 KeyError）、
> `scripts/wait-for-mysql.sh`（无人引用 + 硬编码密码），
> 以及 `src/mysql_db.py: migrate_from_sqlite()`（无调用方、无测试）。

## 数据流

1. 用户在搜索栏输入动词（或点击示例库 / 热门动词）。
2. `get_display_definition(verb)` 按上述优先级取数。
3. `render_semantic_table()` 把 `semantic_table` 渲染为五元彩色表格，其余字段填入六张卡片。
4. 用户提交反馈 → `insert_feedback()` → `feedbacks` 表。
5. 侧边栏调用 `get_stats()` / `get_hot_verbs()` 读取实时统计；导出按钮把 `get_feedback_data()`
   转成 UTF-8-BOM 的 CSV 供下载。

## 部署形态

- **Docker Compose**：`mysql:8.0` 服务 + web 镜像（基础镜像 `python:3.11-slim`，
  三处 `FROM` 按 digest 固定；容器内非 root 运行，uid 1000）。
  `scripts/entrypoint.sh` 先用 `scripts/wait_for_mysql.py` 探活 `$MYSQL_HOST:$MYSQL_PORT`
  （30 次 × 2 秒），超时也以离线模式启动；数据落命名卷 `web-word-mysql-data` /
  `web-word-app-data`，种子由镜像内 `/app/seed/data` 幂等补种（缺才拷）。
  web 与 mysql 服务均带 **healthcheck**（web 用 python urllib 探 `_stcore/health`）；
  MySQL 以 `--skip-log-bin` 启动（binlog 关闭，datadir 不再日增约 1G）；
  compose 的 `env_file` 挂 `.env`＋`.env.local`（后者 `required: false`，
  需 Compose v2.24+）。
- **本地**：本机 MySQL 8.0 + `streamlit run src/app.py`，连接参数由
  `scripts/lib_deploy.sh` 从 `MYSQL_*` 环境变量归一为内部 `DB_*`（已导出的优先、
  `.env.local` 覆盖 `.env`，不再硬编码 127.0.0.1/webword123）；`./develop.sh` 部署、
  `./start.sh` 启动、`./repair.sh --fix` 修复，三脚本共享同一函数库。

两种形态共用同一份被跟踪的 `config/config.yaml`，靠环境变量优先级区分 —— 详见
[`config/README.md`](config/README.md)。
