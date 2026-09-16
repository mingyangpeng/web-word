# 更新日志

本项目使用 [GSD 工作流](.planning/) 按里程碑推进，每个里程碑的详细计划、验证记录与
上下文归档在 `.planning/milestones/` 与 `.planning/phases/`。本文件只记录**面向使用者的
变更**。

> 早期版本（2026-05-30 之前）没有独立版本号，条目按实际完成时间归入 v1.0。

## 2026-09 — 表结构重构与词簇图谱接口

### 破坏性变更（自动迁移，无需手工干预）

- **`synonyms` 表已删除**，取而代之的是 `word_clusters` + `word_relations` + `definitions.cluster_id`。
  旧表的边是「环邻」（每词只连同簇左右各 3 个邻居），新语义是「簇内**完全图**」
  （同簇任意两词都有边）。两者不能共存 —— 混在一起会得到自相矛盾的图。旧边被丢弃，
  跑一次 `python scripts/load_word_library.py` 即重建为 2143 条正确边。
- **`statistics` 表已删除**：v1 设计里的键值统计表，全仓库无任何代码读写，实际是死表。
- `init_database()` 现在会自动执行结构迁移（`_migrate_schema()`），用 `information_schema`
  探测后按需 ALTER / DROP，幂等可重复。`definitions` / `feedbacks` / `usage_logs` 的行**原地保留**。

### 新增

- **`word_clusters` 表**：词义簇，唯一键 `(main_cat, sub_cat)`，共 25 个簇。
- **`word_relations` 表**：词间关系，物化簇内完全图，共 2143 条边。
  `CHECK(verb_a_id < verb_b_id)` 保证无向边只存一份（旧表双向各存一行），
  `uq_word_relations_pair` 保证重复灌库幂等，两个端点均有外键（旧表的 `synonym_verb`
  是裸字符串，无法保证词真的存在）。
- **`schema_migrations` 表**：结构版本记录。
- **视图 `v_cluster_complete_graph`**：由簇成员推导完全图，作为物化表的对照实现，
  灌库脚本每次都会核对两者边数是否相等。
- **页面上的词与词关系图谱**（`src/cluster_graph.py` + `app.py: render_cluster_graph_section`）：
  搜索结果页新增 🕸️ 区块，把「查询词 + 其所属词簇」的完全图画成内联 SVG。
  支持切换「完整簇 / 只显示中心词连线」、显示簇大小与 C(n,2) 边数、
  展开簇内成员列表并点击直接切词。
- **切换词簇**：新增 `get_cluster_graph_by_id()` 与 `list_clusters()`，页面上有
  「切换词簇」下拉框，可直接打开 25 个簇中的任意一个 —— 在此之前只能靠「先搜一个别的词」
  间接进入它所在的簇，无法主动浏览。换词时（搜索框 / 热门词 / 簇内成员按钮）选择器自动
  重置回「跟随当前词」。
- 侧边栏新增 **词义簇** 与 **词间关系** 两个结构指标。
- `tests/test_schema.py`（21 个用例）：DDL 约束契约、迁移幂等性、完全图查询与 SVG 渲染。

### 修正

- **`scripts/init_db.sql` 不再复制建表语句**。它以前有一份完整的 CREATE TABLE 副本，
  且以 root 身份**先于**应用执行 —— 一旦建出旧结构的表，应用启动时的
  `CREATE TABLE IF NOT EXISTS` 会**静默跳过**，库就永久停在旧结构上。现在它只建库与授权，
  建表统一由 `src/mysql_db.py` 负责。同时补了 `CREATE USER IF NOT EXISTS`：
  MySQL 8 的 GRANT 不再隐式建用户，用户不存在时整行 GRANT 会以 ERROR 1410 中断脚本。
- **`insert_definition()` 的 `cluster_id` 用 `COALESCE(VALUES(cluster_id), cluster_id)`**：
  传 None 时保留库中现值。否则 LLM 实时生成释义（它不知道簇划分）会把灌库脚本建立的
  簇归属抹成 NULL。
- **建视图的时机移到迁移之后**：视图引用 `definitions.cluster_id`，而旧库要等迁移才补上该列。
- **词簇图谱的小簇布局**：3 个词时改用左右布局，原先的上下布局会让「两个环上节点之间的边」
  与中心词标签叠在同一竖直线上。
- `get_synonyms()` 改为按 `cluster_id` 取同簇其他成员（不再依赖已删除的 `synonyms` 表）。


## Unreleased（仓库清理与部署可用性）

### 部署可用性

- **修复 Docker 下大模型静默失效**：`docker-compose.yml` 注入的是 `ZHIPU_API_KEY`，而应用
  实际读取的是 `ZHIPUAI_API_KEY`（`src/llm_api.py`），导致容器内 key 恒为空、释义永远走离线
  降级且无任何报错。现已同时透传两个变量，并允许通过环境变量覆盖 `LLM_MODEL`。
- **新增 `config/config.example.yaml`**：提供 `host: localhost` 与占位凭据的模板，配合
  `cp config/config.example.yaml config/config.yaml` 即可在新机器部署。
- **重写 `config/README.md`**：修正了此前文档中错误的口令与表结构，写明配置优先级
  （环境变量 > `config/config.yaml` > 内置默认值）、代码识别的全部 `MYSQL_*` 变量名、
  本地 MySQL 从零搭建步骤，以及 Docker Compose 的注入行为。
- **修正 `.env.example`**：`ENVIRONMENT` / `DEBUG` 实际无任何代码读取，已移入「已废弃/预留」；
  `MYSQL_HOST` 默认值同时说明 Docker（`mysql`）与本地（`127.0.0.1`）两种情形。
- **重写 `README.md`**：两条快速开始路径（Docker Compose / 本地 Python + 本地 MySQL），
  目录结构与当前仓库一致，并说明 `.env` 不会被自动加载（仓库无 python-dotenv）。
- **补全 `requirements.txt`**：新增 `python-docx`、`requests`（仅
  `scripts/ingest_motion_verbs.py` 使用），并把运行时依赖、脚本依赖、测试与开发工具分区。
- **CI**：`.github/workflows/ci-cd.yml` 的 Hugging Face 部署任务因转义错误与占位实现而无法
  工作，暂时注释并标注 TODO；测试任务不变。

### 仓库瘦身

- **不再跟踪 `data/mysql/`**（193 个文件、约 184 MB 的 InnoDB 数据文件、binlog 与证书）。
  `.gitignore` 早已包含 `data/`，但文件在规则加入前就已被提交，导致运行中的 MySQL 每次写入都会
  弄脏工作区。仅从索引移除，磁盘上的 datadir 保持原样。
- **不再跟踪根目录重复的学位论文 docx**（与 `data/docs/` 下的副本逐字节相同）。
- **不再跟踪 `.DS_Store` 与遗留的 `tests/__pycache__/*.pyc`**。
- **忽略本机运行产物**：`graphify-out/`、`.gsd/`、`.planning/milestone.lock`。
- **删除 7 份过期的一次性交付/清理报告**：`CLEANUP_REPORT.md`、`FINAL_DELIVERY_REPORT.md`、
  `FINAL_TEST_REPORT.md`、`PROJECT_DELIVERY_SUMMARY.md`、`INDEX.md`、`DOCS_INDEX.md`、
  `DATABASE_MIGRATION.md`。它们宣称「完成度 95% / 可交付」，而当时的 LLM 仍是模拟数据，且
  其中的口令与表结构均与实际代码不符，容易误导新协作者。

## v1.1（进行中）

### Phase 05 — 实时生成接入（Live Generation）

- 新增端到端释义适配层 `get_display_definition()`，明确取数优先级：
  **数据库命中 → 实时 LLM 生成 → 内置示例 `MOCK_DEFINITIONS` → 兜底骨架**。
- LLM 生成成功的结果会持久化到 MySQL，作为后续查询的缓存（`CACHE_TTL_HOURS`，默认 24 小时）。
- 缺少 `ZHIPUAI_API_KEY` 或调用异常时降级不崩溃：仅在结果区提示「实时生成暂不可用，
  已显示离线释义」。
- 把 `InputValidator` 接入查询入口，非法输入不再进入大模型提示词。
- 新增 `tests/test_phase5.py` 覆盖优先级、持久化契约与降级路径。

### 界面修复

- 修复固定搜索栏：此前用 `st.markdown` 包裹 `st.text_input` 的写法从未生效（Streamlit 会把
  两者渲染成兄弟节点），并修正了 `rgba(#ffffff, 0.98)` 这类非法 CSS 与永不成功的 JS 注入等待。
  回归测试见 `tests/test_search_bar.py`。

## v1.0（2026-08-24，tag `v1.0`）

**4 个阶段、5 个计划、8 个任务**（详见 `.planning/milestones/v1.0-*`）。

### 界面与交互

- 三分类示例库（方式聚焦类 / 路径聚焦类 / 体相聚焦类），点击动词即查询。
- 结果四卡片布局：原型与位移事件分析 / 范畴锚定 / 核心释义与多维辨异 / 图式示例，均可折叠。
- 侧边栏：实验统计、热门查询动词（本地筛选、点击即查）、反馈数据 CSV 导出；支持折叠为窄图标栏。

### 后端接入

- **MySQL 8.0 数据访问层**：连接池、启动自动建表，五张表 —— `definitions`、`synonyms`、
  `feedbacks`、`usage_logs`、`statistics`。
- **智谱 AI（GLM）接入**：`src/llm_api.py` 负责调用、JSON 解析与 MySQL 缓存。
- 统计口径修正：「总查询次数」改为来自 `usage_logs`，「已收录词条」单独展示，不再把词条数
  冒充查询次数。
- 用户反馈（1–5 星 + 文字）写入 `feedbacks` 表。

### 安全

- `src/security.py`：SQL 注入与 XSS 模式校验、输出 HTML 转义、密钥掩码。

### 工程化

- Docker 化部署：`Dockerfile` + `docker-compose.yml`（`mysql:8.0` + Streamlit），入口脚本
  先探活 MySQL 再启动应用，探活超时也以离线模式启动；数据落命名卷。
- 迁移到 macOS M1（arm64）：改用 Compose 内的 MySQL，`python:3.11-slim` 多架构镜像。
- pytest 测试框架与 GitHub Actions CI。
