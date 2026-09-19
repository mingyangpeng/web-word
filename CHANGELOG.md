# 更新日志

本项目使用 [GSD 工作流](.planning/) 按里程碑推进，每个里程碑的详细计划、验证记录与
上下文归档在 `.planning/milestones/` 与 `.planning/phases/`。本文件只记录**面向使用者的
变更**。

> 早期版本（2026-05-30 之前）没有独立版本号，条目按实际完成时间归入 v1.0。

## 2026-09 — 按《义项判定标准》重建词表，释义以 dictionary.db 为准，产出一份词表文档

依据 `docs/` 下两份新文档（`义项判定标准.docx`、`Levin移动动词候选词筛选表.xlsx`）重构词表。

**词表换成 Levin 筛选结果，分类换成文档规定的体系**

词目从旧词库的 155 词改为筛选表的 **171 词**；分类从自定义的 25 个 sub_cat 改为文档的
**三主范畴 / 十二次类**。这套变更必须**整体重建**簇与关系（新旧两套次类混在一张图上
只会得到自相矛盾的结果），所以灌库脚本现在会先 `clear_all_word_data()`，
但**保留 feedbacks 与 usage_logs** —— 那是用户产生的数据，不是派生数据。

实测：`definitions=171, word_clusters=12, word_relations=1935, word_senses=246`，
视图推导的边数与物化表一致。

**表结构升到 v3（义位独立成表）**

文档明确「分析单元是义位（sense），而非词目 lemma」，所以新增 `word_senses` 表，
一词目下逐义位记录中英文释义、搭配框架、例句、近义反义词与逐义位的标注字段。
`definitions` 增加义位层面的标注列（意象图式 / 原型层级 / 英汉对齐等级 /
汉语句法特征 / 译义转化策略 / 释义来源 / 来源可信度 / 待复核标志）。

迁移**只做结构**：加列加表，不删任何业务数据。迁移每次应用启动都会跑，让它删数据太危险；
词簇与关系的重建是灌库脚本的职责。新增测试专门断言迁移里不含任何 DELETE。

**释义以 dictionary.db 为首选来源，并如实标注来源**

`src/word_source.py` 是新的词表数据源解析层，把四个来源合成统一结构，释义按可信度降级：

| Rank | 来源 | 词数 |
|------|------|------|
| 1 | dictionary.db（OALD，可回溯原文） | 17 |
| 2 | 既有词库（二手转写） | 130 |
| 3 | 研究者标注的原型义（短语） | 24 |
| 4/5 | 仅英文 / 无 | 0 |

**词典原文率只有 13.5%**，这个数字在页面上、文档里、审计输出中都显式标出 ——
`dictionary.db` 里 `pos='v'` 的词目仅 333 个，与 Levin 词表交集 23 个。不写清楚的话，
读者会以为每条释义都是词典原文。

**原型义位选择：默认保留首条，只在有硬证据时覆盖**

词典的义位顺序携带信息，首位通常就是原型义（17 个词里 16 个如此）。但 `charge`
的首条是「要价，收费」，而它的 Levin 原型主导义是「猛冲向前」—— 直接取首条会把一个
移动动词的释义写成完全无关的意思。

选择器的第一版按「与原型主导义简述的字符重合」排序，结果**弄坏了本来正确的词**：
`come` 的简述是「朝说话人位置趋近」，字面在「来到；到达」里一个都不出现，
而冷僻义位「〔某物〕垂到〔某位置〕」因为带「位置」二字拿到最高分。
用一个会挑冷僻义位的启发式覆盖基本正确的默认值，是净损失。

最终策略：默认保留首条，只有当首条**完全不含位移语义**（既无中文位移语素也无英文
位移动词）、且存在另一个既含位移语义又与简述有实际重合的义位时才覆盖。
实测恰好修正 `charge` 一词，并由测试钉住「只覆盖 charge」这个结果。

**新增词表文档**

`scripts/generate_word_doc.py` → `docs/英语自移移动动词词表.docx`（171 词 / 12 次类 /
1935 边 / 45 条剔除记录）。含编者说明、分类统计、分组词表、义位明细、剔除理由附录。
由脚本生成是为了让每个数字都能追溯到来源，重新灌库后重跑即同步。

**顺带修掉一个真实缺陷：卡片 CSS 当文本泄漏到页面上**

结果区原本用 `st.markdown(get_card_style(), unsafe_allow_html=True)` 给卡片上样式，
实际效果是把 CSS **当文本渲染**出来 —— 页面上可见 5 段
「background-color: #f7fafc; padding: 24px; border-radius: 12px; ...」，
而配对的 `</div>` 也没包住任何东西（Streamlit 把每次 st.markdown 渲染成独立兄弟节点，
HTML 无法跨调用闭合）。这个缺陷从 2026-05 的 phase-02 就存在。

改为带 key 的 `st.container(key=f"card_body_{card_key}")` + CSS 选择器，
与搜索栏 `.st-key-search_bar` 是同一个模式。加了回归测试，并验证过它
在旧写法下确实会失败。

测试 97 → **152**（有 MySQL）/ 140（无 MySQL，12 skipped）。


## 2026-09 — 图谱粒子动效与全屏

- **粒子动效**：每个节点向外冒彩色粒子（带拖尾轨道），**上限 200 个**同时活跃。
  画在独立 canvas 覆盖层上（不拦截鼠标事件），只读 vis-network 的坐标，因此不影响
  拖拽/缩放/点击，且每帧只重绘覆盖层而不必重画 2143 条边。左上角可一键开关。
- **粒子按簇轮转分配**：有选中节点时其所在簇优先（用户要求）；其余按簇大小轮转。
  不能按度数排序取前 N —— 实测那样 200 个粒子会被 56 词的「常态行走」簇独占，
  25 个簇里只有 1 个发光。
- **全屏**：左上角 ⛶ 按钮，对整个 body 请求全屏（侧边栏一起放大），再点退出。
  组件 iframe 的 `allow` 已含 `fullscreen`，实测可进入 1920×1080 并正确重算画布。
- 产物指纹现在**并入模板版本号**（`TEMPLATE_VERSION`）。原先只由数据决定，
  于是「改了模板但数据没变」时 URL 不变，页面继续跑旧渲染逻辑，改了看不见 ——
  本轮踩过这个坑，现在改模板即产生新 URL 并自动清理旧文件。


## 2026-09 — 节点即粒子：引力斥力与阻尼、解除数量上限、搜索自动解锁词簇

- **单词节点本身就是粒子**（原先是「节点旁边另挂一圈小点」）。节点之间同时受锚定力
  （弱弹簧回布局原位）、斥力（与距离平方成反比）与近义边上的引力，一阶阻尼
  `v ← (v + a) × DAMPING`。整体速度按用户要求降到原布局的 0.1×。
- **取消 200 个粒子的数量上限**。每个可见节点都有一颗粒子，粒子数恒等于可见节点数
  （默认 171）。不设上限时「选中簇优先吃配额」的预算分配失去意义，那套两阶段分配
  代码（`PARTICLE_MAX` / `FOCUS_SHARE` / `focusClusterIds` / `particlesPerNode`）
  整体删除，不留开关 —— 没有调用方的死代码只会误导后来的人。
- **修复「一团光晕，啥也看不清」**：粒子半径没有乘 `network.getScale()`。vis 把节点
  画成 `size × scale` 屏幕像素，粒子层却按 canvas 单位画，于是在缩小的默认视野里
  粒子半径是节点的 **3.4 倍**；171 个半透明光晕在 `lighter` 叠加下互相加亮，
  17.1% 的已绘制像素饱和成近纯白。修复后：半径乘缩放并夹在 `[2.5px, 26px]`、
  光晕从节点半径的 3.2 倍降到 1.9 倍、缩放小到 `r < 4px` 时只画实心点（LOD）。
  实测覆盖画布 51%→8%，近纯白 17.1%→0.86%。
- **搜索自动解锁词簇**（用户要求）：搜到的词即使其所在词簇当前没勾选，也会被自动
  勾选上，避免「搜到了这个词，图上却看不到它」。解锁在 `network.focus` 之前执行。
- **物理参数实测标定**：关键指标是「被限速的节点数」—— 初版 167/171 个节点顶在
  `MAX_SPEED` 上，运动由限速而非受力决定，观感是「整张图匀速平移」。经在浏览器中
  逐组测量，采用 `DAMPING=0.94` / `ACCEL_MAX=0.014` / `REPULSE_K=3`，被限速节点
  降到 **0/171**，`MAX_SPEED` 退回纯安全兜底。

## 2026-09 — 交互式知识图谱页（graphify 风格）

把「词与词关系」从静态 SVG 升级为可交互的力导向图，观感与操作对齐
[graphify](https://github.com/Graphify-Labs/graphify) 产出的 `graph.html`。

- **新增图谱页**（侧边栏顶部切换）：全库 155 词 / 2143 边一张图。支持滚轮缩放、
  拖拽平移、节点搜索、点击查看节点信息与全部近义词、按语义簇勾选过滤、高亮邻居、
  实时统计当前可见节点/关系/簇数。
- **新增 `src/graph_export.py`** + `get_full_word_graph()`：图谱数据同时具备
  「单簇」与「全库」两种粒度，前者给结果页的 SVG，后者给图谱页。
- **vis-network 本地化**（`src/static/vis-network.min.js`，688KB，随仓库提交），
  不引 CDN —— 与「灌库脚本离线可用 / 无 key 降级 / 无库降级」一致，内网环境下
  CDN 会渲染成一片空白。为此开启 `server.enableStaticServing`。
- **图谱以静态文件 + iframe 呈现**，文件名带数据指纹。若用
  `components.html(html_string)`，Streamlit 每次重跑都会重写 iframe，力导向布局
  从零收敛、用户拖动的位置与选中节点全丢；静态文件则只在数据变化时重载。
- 图谱页底部提供 25 个「按词簇浏览」按钮，点击直接跳到该簇的第一个词并展示其完全图。


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
- **授权语句里的库名现在转义下划线**（`scripts/grant_local_mysql.sql` 新增，
  `scripts/init_db.sql` / README / config/README 同步修正）。GRANT 中的 `_` 是
  **单字符通配符**（与 LIKE 同规则），`GRANT ... ON web_word_db.*` 授予的实际是
  「web_任意字符_word_任意字符_db」这个**模式** —— 同机上名字相像的无关库会被一并授权。
  实测确认：未转义时 `web_word_user` 能 `SELECT` 另一个库的表，改成 `web\_word\_db`
  后被拒（1142）。这类问题不报错、不失败，只会安静多给权限，因此另加静态测试
  （`tests/test_schema.py: TestGrantStatements`）扫描所有 SQL 与文档里的 GRANT 语句。
- **新增 `scripts/grant_local_mysql.sql`**：一体化、幂等的本地授权脚本，覆盖应用库
  与迁移集成测试所需库，并说明为何要同时授权 `@'localhost'` / `@'127.0.0.1'` / `@'%'`。

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
