# MOVECAT 问答文档 · 定稿口径 v2（2026-11-10）

> 承接《MOVECAT问答文档.docx》（2026-10-11 四问定稿）。本版按 2026-11-10 平台实态逐条核对修订：
> 修正过时数字、补齐技术栈实测值、对齐数据库真实数据，并为每问新增「⚠️ 风险与修正」段
> （写作/答辩前必须先处理的口径偏差）。每问四段：**定稿答案 → 论文落点 → 数据支撑 → 风险与修正**。
>
> 核对方式：全部数字来自本机数据库（`web_word_db`，54 表）与代码实测，出处逐条标注文件路径；
> 可复现命令见各节「数据支撑」。v1 → v2 差异清单见附录 B。

---

## 目录

- [问题一：MOVECAT 是什么词的缩写？](#问题一movecat-是什么词的缩写)
- [问题二：平台用了什么技术实现？功能是什么？](#问题二平台用了什么技术实现功能是什么)
- [问题三：OALD 义位提取的版权口径怎么说？](#问题三oald-义位提取的版权口径怎么说)
- [问题四：结果部分如何与 OALD 词条对比、凸显平台优越性？](#问题四结果部分如何与-oald-词条对比凸显平台优越性)
- [附录 A：答辩口头速查（四问各三句）](#附录-a答辩口头速查四问各三句)
- [附录 B：v1 → v2 修订记录](#附录-bv1--v2-修订记录)

---

## 问题一：MOVECAT 是什么词的缩写？

### 定稿答案

**MOVECAT = MOtion VErb CATegorization**（移动动词范畴化）。

- 字母切分：`MO`tion + `VE`rb + `CAT`egorization，与项目英文名
  *Schema-Based **Categorization** of **Motion Verb**s*（三篇系列论文副题统一口径）完全对应。
- 平台全称（论文题名）：*MOVECAT: A Prototype Annotation Platform for Schema-based
  Multi-dimensional Definition of English Motion Verbs*
  （中文：面向英语移动动词图式多维释义的标注原型平台）。
  注意：**这个全称是平台的题名，不是缩写的逐词展开**——缩写展开只有
  MOtion VErb CATegorization 一个，答辩被追问时不要把题名当展开念。
- 层级关系：MOVECAT 先是**项目名**（移动动词图式范畴化研究项目），平台沿用同名；
  系列论文中「（MOVECAT 系列）」指项目，「MOVECAT 标注平台」指工具。

> v1 修订说明：v1 原文「MOVECAT 是 MOtion VErb CAT“”（题名）对应」中 `CAT` 后的展开词
> 缺失（docx 原稿即残缺，经查 `w:del`/脚注/批注均无残留，非删除所致）。本版补齐为
> CATegorization，与三篇论文英文副题逐词核对一致。

### 首次出现写法（中/英，直接粘贴）

**中文稿**：

> 本研究隶属移动动词图式范畴化研究项目（**MOVECAT**，MOtion VErb CATegorization）。
> 项目配套的标注平台同名，全称 *MOVECAT: A Prototype Annotation Platform for
> Schema-based Multi-dimensional Definition of English Motion Verbs*
> （面向英语移动动词图式多维释义的标注原型平台），下文简称「MOVECAT 平台」。

**英文稿**：

> This study is part of the research project on schema-based categorization of
> motion verbs (**MOVECAT**, MOtion VErb CATegorization). The accompanying
> annotation platform bears the same name: *MOVECAT: A Prototype Annotation
> Platform for Schema-based Multi-dimensional Definition of English Motion Verbs*
> (hereafter the MOVECAT platform).

### 论文落点

- 英文题名页与摘要首次出现处：全称 + (hereafter MOVECAT)，此后一律用缩写；
- 中文稿首次出现处：括注（MOVECAT，MOtion VErb CATegorization，移动动词范畴化）；
- 参考文献内部资料条目沿用现有口径：「移动动词图式范畴化研究项目组（MOVECAT）. 2026.」

### ⚠️ 风险与修正：MOVECAT / LexiSchema 双名并存

平台自批次 9 起在界面与导出物中改称 **LexiSchema**（[docs/使用说明书.md](../../使用说明书.md)
第 11 行；[src/template_engine.py](../../../src/template_engine.py) 第 6 行；模板导出 CSV
列名「LexiSchema模板化释义」写死于代码），Lexikos 投稿文章亦用 LexiSchema；
而三篇系列论文、本 README 仍用 MOVECAT。**同一篇文章内两名单用会被审稿人当成两个系统**。

处理口径（二选一，全文统一）：

1. Lexikos 项目文章 → 统一 **LexiSchema**；学位论文与系列论文 → 统一 **MOVECAT**，
   并在首次出现处脚注一句：「MOVECAT 平台即 LexiSchema 的原型实现（同一系统，更名前口径）」；
2. 或全部统一为 MOVECAT，将 LexiSchema 仅作为平台界面品牌名在系统描述一节提及。

推荐方案 1（与两篇投稿的现状改动最小）。依据：[docs/spec/白话版对照清单.md](../../spec/白话版对照清单.md)
第 5–7 行已写明三者关系（总计划书 / 论文草稿（LexiSchema）/ 本仓库真实平台（MOVECAT））。

---

## 问题二：平台用了什么技术实现？功能是什么？

### 2.1 技术栈（实测口径，2026-11-10）

| 层 | 技术 | 版本 / 规模（实测） | 代码落点 |
|---|---|---|---|
| 应用层 | Python + **Streamlit** | Python 3.11；Streamlit ≥1.41（实测 1.57.0）；单入口 17 页路由 | `src/app.py` |
| 数据层 | **MySQL 8.0 / InnoDB**（PyMySQL） | 库 `web_word_db` **54 张表**；建表与 v1→v7 幂等迁移 | `src/mysql_db.py`；各 `*_db.py` |
| 语料层 | **Sketch Engine word sketch API**（enTenTen21） | 171 词逐词 JSON 存档；**69,943 行**搭配明细入库 | `data/corpus/wsketch_full/`；`scripts/load_corpus_dataset.py` |
| 分析层 | **SciPy** 层次聚类 + 自实现 **Gower** 相异度 | `linkage`/`squareform`/`fcluster`；跑范畴英汉各 5 簇 | `src/cluster_analysis.py:155-157` |
| 信度层 | **krippendorff** 库 + 纯 Python 同公式回退 | α（nominal/ordinal），缺失值容忍，库缺失不崩 | `src/reliability.py:14-37` |
| 可视化 | **Plotly** + **vis-network**（本地 static 资源，静态 HTML＋内容指纹缓存） | 171 词 / 1,935 边 / 12 簇力导向图 | `src/graph_export.py` |
| AI 层 | 多供应商：智谱 SDK / OpenAI / DeepSeek（均 OpenAI 兼容）+ Anthropic 兼容客户端 | 优先级 = `llm_providers` 表默认项 → 环境变量链；DB 供应商缓存 5s | `src/llm_api.py`；`src/llm_providers_db.py` |
| 表格 IO | **openpyxl**（xlsx 种子 → 库；模板 → CSV/JSON 导出） | 导出过 `sanitize_csv_value` 防 CSV 公式注入 | `src/template_engine.py`；`src/export_center.py` |
| 配置层 | **范畴包六件套**（pack / admission / features / schemas / corpus_map / prompts，YAML） | `configs/motion`（正式）＋ `configs/speech`（第二范畴验证帧）＋ `configs/_template` | `src/category_pack.py`（`load_pack`/`run_selfcheck`） |
| 扩展层 | **工具插件注册表**（ToolSpec 中央注册表） | 10 类内置工具薄包装（准入/特征标注/信度/聚类/典型性/图式/对齐/模板/语料证据/语义检索）＋多媒体 | `src/tools/registry.py`；`src/tools/builtin/` |
| 认证 | **pbkdf2_sha256**（每用户随机盐，150,000 迭代） | 六角色 ＋ `user_roles` 一人多角色 | `src/users_db.py:114` 起 |
| 部署 | Docker 多阶段构建；**非 root**（uid 1000）；healthcheck 打 `/_stcore/health`；MySQL `--skip-log-bin` | 基础镜像 digest 固定 | `Dockerfile`；`docker-compose.yml` |

代码规模（实测）：`src/` 66 个模块 **46,550 行**；测试 **2,566 项**（`pytest --collect-only`，
2026-11-10；README 的「59 模块 1,997 项」为旧口径，建议同步更新）。

### 2.2 功能：七区十七页

v1 的「平台共五个页面」已过时——现平台为**七区十七页**（侧边栏分组见
`src/app.py:413-419` `_SIDEBAR_ZONES`；页名与说明同源于 `src/page_guides.py`）：

| 区 | 页面 | 功能 | 产出物 |
|---|---|---|---|
| 🔍 查阅展示 | 搜索释义 | Talmy 五要素（方式/路径/方向/体相/范围）分解释义；六张折叠卡片＋词簇图＋语料证据 | 词目/义位全景视图 |
| | 知识图谱 | 171 词 / 1,935 条近义关系 / 12 词簇交互式力导向图；可搜、可点、可按簇过滤 | 宏观语义地图 |
| | 语料数据集 | 词频、四图式重心得分、逐槽位 logDice 搭配；搭配词语义类别页内回写 | 语料证据库（可下钻至原始 JSON） |
| | 域系初判 | 352 条保留义位的三域十二系归属＋双语例句＋R0/R2/R3 规则标签 | 域—系分类底稿 |
| | 以句搜义 | 自然语言 → 特征向量 → Gower 最近邻反查义位（规则层离线可用） | 第二检索模式 |
| 🏷️ 语义建模 | 标注平台 | **五维标注**：准入(Y/拓展/N) → 意象图式(4 选 1) → 英汉对齐 → 汉语句法 → 译义策略；义位隔离呈现、待复核队列、逐词进度 | 逐 SenseID 标注记录 |
| | 标注提交 | 盲标工作台：所有编码人看**同一份** AI 初筛草稿，互不可见对方提交 | `annotation_submissions` |
| | 信度报告 | 同 (范畴, 任务) 全量提交算 Krippendorff's α；逐特征明细＋分歧清单 CSV | α 报告（论文 §4） |
| 📊 语义分析 | 语义分析 | 谱系树（交互切割 k=5）/ medoid 三级典型性 / 义项分立复核 / 义位图谱，四视图一页 | 簇结构＋典型性排序 |
| ✍️ 编纂产出 | 释义模板 | 逐簇提炼**母图式**（均值 ≥0.5 判共享要素）→ 单义位**四维模板**实例化（图式/语义参数/句法/对齐预留），与 OALD10 原文并排，批量导出 | 结构化释义模板（确定性拼装，不调 LLM） |
| | 释义撰写与审校 | locked 簇承包 → 模板打底 → 成文 → 版本留痕 → 回避制审校 → 终审 → 发布（状态机） | 成品义项草稿 |
| | 例证与对译 | 例证三来源（语料草选/人工改写/自拟）＋媒体例证；对译三态（完全/部分/无对应） | 例证区＋对译区 |
| 🤖 AI 协作 | AI 协作 | 协作收件箱（AI 提议 → 人裁决，按不确定度排序）＋协同度量（采纳率等可引指标） | 人机协同台账 |
| 📖 词典管理 | 词典管理 | 主编驾驶舱、项目成员三级权限、EAV 定制属性、媒体库 | 项目/资产治理 |
| | 模型供应商 | LLM 供应商（名称/Base URL/API 格式/Key/模型清单）＋连通性测试 | 运行时模型配置 |
| 🔧 系统管理 | 账号管理 / 帮助中心 | 六角色账号、启停；帮助文档按七区四段式渲染 | 权限与文档 |

**四个支撑模块贯穿各页**：① 语料与义项管理（打标不删行）② 候选义位管理
③ 图式五维标注 ④ 质控与导出（G6 许可终检闸门）。

### 2.3 平台承载的数据规模（实测，2026-11-10）

| 数据 | 规模 | 出处 |
|---|---|---|
| 词目池 | 171 词目（Levin 1993 第 51 章 216 候选 → 双重核查 171） | `definitions` 表 171 行 |
| 义位总表 | **996** 条 = 992 OALD10 ＋ 4 人工补充（kayak/oar/dodder/scutter，172 词目） | `oald_senses`（`source` 字段区分） |
| 保留义位（域系） | 352 条 / 162 词目；三域：方式 264 / 路径 62 / 互动 26 | `domain_family_senses` |
| 双语例句 | 1,176 条（126 条带已审校中文翻译） | `domain_family_examples` |
| 语料搭配 | **69,943 行** / 171 词；原始槽位串 **48 种**（跑范畴子集 28 种）；归并呈现口径 27 类 | `corpus_collocations`；`corpus_word_stats` |
| 图式证据 | 6,744 行逐词证据文件 | `corpus_schema_evidence` |
| 词间关系 | 1,935 条近义边 / 12 词簇 | `word_relations` / `word_clusters` |
| 跑范畴试点 | 英 23 词目 32 义位；汉 19 词条 25 义位条目（含 6 条剔除留痕），19 条完成 15 维编码 | `cs_lexemes`/`cs_senses`/`cs_sense_features` |
| LLM 初筛 | 162 个词目文件（逐义位草稿，仅作候选） | `data/corpus/llm_screening/` |

### 2.4 论文落点

§3.3 按词典学任务介绍模块（不写工程细节），骨架段落可直接用：

> 平台采用**配置驱动、四层解耦**架构：**配置定义层**（范畴包六件套，语义特征、准入标准、
> 图式定义、语料映射、提示词全部外置于 YAML）→ **语义处理引擎层**（Gower 相异度＋average
> 层次聚类、medoid 典型性、母图式提炼、模板实例化，全部确定性计算、不调 LLM）→
> **协作智能层**（LLM 仅输出候选草稿；盲标工作台＋IAA 信度质控，裁决权在人）→
> **结果输出层**（四维释义模板、词条装配预览、结构化导出，导出经许可终检闸门）。
> 配置层与引擎层的隔离使跨范畴迁移只需更换配置包：第二范畴（言说动词验证帧）已完成
> 六件套复用验证，引擎零修改。

技术栈表（2.1）作附录或投稿补充材料；正文 §3.2 仅需一句「数据存于关系数据库以保证可回溯」封顶。

### 2.5 ⚠️ 风险与修正：与旧口径的偏差（写作时必改）

| # | 旧口径 | 实测 | 处理 |
|---|---|---|---|
| 1 | 「平台共五个页面」（v1 问答、P3 论文） | **七区十七页** | 论文改「平台以七个功能区、十七个页面组织」；如需保留「五页面」须注明为核心作业页 |
| 2 | 「27 类语法槽位」 | 原始 **48 种**槽位串（跑范畴子集 28）；27 为归并呈现口径 | 正文写「归并为 27 类语法槽位」并脚注原始 48 种；或统一改 48 |
| 3 | v1 问答「enTenTen21 约 61 亿词」 | 系列论文统一口径「约 520 亿词（61.6 billion tokens）」 | v1 系量级笔误；三篇论文与问答统一为后者 |
| 4 | 汉语侧「24 个词条」（论文 §4.1 正文） | 表 4-1 实为 **19 词条** 25 义位条目；`cs_lexemes` zh=19 与表一致 | 以 19 词条/25 条目修订正文（表是对的，正文笔误） |
| 5 | README「59 模块 1,997 项测试」 | 76 文件 **2,566 项**（collect-only） | README 数字刷新 |

---

## 问题三：OALD 义位提取的版权口径怎么说？

### 3.1 四层论述（审稿人真正会看的结构）

1. **使用性质**：OALD10 的义项编号、语法码、释义、例句在本研究中是**被分析的研究对象**，
   而非**被出版的辞书内容**。平台产出的是义位层**标注标签**（准入、图式、对齐、句法、译义
   策略）与**统计量**，不是任何形式的词典条目；最终研究义位表是标注数据集，不含 OALD
   释义的再汇编。
2. **使用方式**：逐义项数据以本地结构化表用于标注判定；论文仅在**判定所必需**的范围内
   引用个别释义与例句作为示例，逐一注明
   *Oxford Advanced Learner's Dictionary, 10th edition*；不整表复制、不随文分发、
   不做替代性汇编。
3. **研究惯例**：以主流学习词典为义项切分基准开展词典学研究（对比研究、义项划分评估、
   释义质量评估）是语料库词典学与义项研究的通行做法；本研究遵循同一惯例，并在方法部分
   明确标注数据来源与版次。
4. **边界声明**：本阶段产出仅用于学术发表与研究复现；若成果未来转化为面向公众的词典
   产品，将另行取得出版方授权；公开数据集对词典原文做**最小化处理**（仅保留 SenseID、
   标签与统计层，释义例句不随公开数据集分发）。

### 3.2 方法节可直接粘贴段落

**中文**：

> 本研究的义项清单以《牛津高阶英语词典（第 10 版）》（OALD10）为义项切分参照
> （sense-inventory reference）。OALD10 的释义与例句在本研究中作为义位判定的分析材料使用，
> 其性质为学术研究中的引用与分析，而非词典内容的复制或再出版。平台产出为义位层面的
> 结构化标注标签与统计结果，不构成词典条目；论文仅在判定示例的必要范围内引用个别释义
> 与例句并注明出处与版次。公开共享的数据集仅保留 SenseID、标注标签与统计量，不含词典
> 释义与例句原文；如需完整数据可依数据可用性声明联系作者。

**English**：

> The sense inventory of this study takes OALD10 as its sense-inventory reference.
> OALD10 definitions and examples are used as analytical material for sense-level
> adjudication — scholarly citation and analysis, not reproduction or re-publication
> of dictionary content. The platform's outputs are structured sense-level annotation
> labels and statistics, not dictionary entries; individual definitions and examples
> are quoted only where indispensable to illustrate an adjudication, with source and
> edition acknowledged. The publicly shared dataset retains only SenseIDs, labels and
> statistics, and contains no dictionary text; access to the full data is available
> under the Data Availability statement.

### 3.3 平台已有的技术保障（写进论文很加分）

| 保障 | 实现位置 |
|---|---|
| 导出许可终检闸门（G6）：未过终检的快照在 MANIFEST 中强制标注「内部快照，未经 G6 许可终检不得对外交付」 | `src/export_center.py:140-177`（`license_checked` 参数） |
| 部署包排除词典原文：打包脚本 `--exclude='data/dictionary.db'`、`--exclude='data/zh_dict_senses.json'` | `scripts/package_deploy.sh:29-30` |
| 数据可用性声明「最小化共享」口径已成文 | `docs/research/papers/series/投稿包/通用声明块.md` |
| 跨范畴迁移验证暴露并修复引擎词类硬编码（B-1 段已应用） | `docs/research/papers/lexikos/论文修订工单-261107.md` |

### 3.4 ⚠️ 风险与修正：三个会推翻上述口径的现实问题（投稿前必处理）

| # | 风险 | 事实（实测） | 后果与处理 |
|---|---|---|---|
| 1 | **词典原文被 git 跟踪** | `data/dictionary.db` 以 3 个 90MB 分卷**入库**（`git ls-files` 可见 `dictionary.db.part00/01/02`），内含 OALD 派生释义与双语例句 | 只要仓库可被 clone，「不复制、不分发」即被反证。**投稿前**：仓库转 private；从工作树与历史移除分卷，改为「脚本＋用户自备词典文件」部署（打包脚本已是此口径） |
| 2 | **《现汉7》mdx 被跟踪** | `data/ModernChineseDict/dict.mdx`（4.9MB）在 git 中；其自带 README 明写「仅供学习交流，禁止商用，下载后 24 小时内删除」 | 中文侧声明一并失效；处理同上（移出跟踪） |
| 3 | **`.env` 被跟踪且历史含真 key** | `.env` 在 `git ls-files` 中；提交 `0923900`/`b421018` 含 `ZHIPUAI_API_KEY=sk-PeAias…`（现工作区已清空） | 与版权无直接关系，但同一公开仓库同时存在旧 key＋词典原文会连带质疑全文可信度。处理：作废旧 key；`.env` 移出跟踪（`.gitignore` 仅忽略 `.env.local`，需补 `.env`） |

> 一句话口径（答辩被问「数据在哪」时）：研究数据仓库为课题组内部非公开仓库；
> 公开版仅含标签与统计层，词典原文不随任何公开渠道分发。

---

## 问题四：结果部分如何与 OALD 词条对比、凸显平台优越性？

### 4.1 对比框架：OALD 4 项 vs 平台 4＋12 项

优越性的论证**不能靠宣称，要靠并排对比让人一眼看出差别**。OALD 词条给的是 4 项
（释义、语法码、例句、习语标记）；平台对同一义位额外给出 12 项结构化信息：
意象图式、原型层级、簇归属、簇内典型性、英汉对齐等级、汉语句法特征、译义策略、
判定理由、语料词频、四图式重心得分与排名、槽位搭配证据、四维结构化模板。

**不要写「平台释义比 OALD 更好」**——那是无法证伪的宣称；写「平台提供了 OALD 所没有的
结构化基础」。

### 4.2 真实数据对照表（可直接进 §4.2）

> 下表「模板化释义」列为 `src/template_engine.py` 引擎对跑范畴真实数据的**现场输出**
> （`instantiate_template('run','en',<sense_id>)`，2026-11-10 实跑，非手工样例）；
> 语料列来自 `corpus_word_stats` / `word_schema_scores`。

| 义位 | OALD10 原文释义 | 平台四维模板（引擎真实输出） | 平台多出的结构化信息 | 可核验证据 |
|---|---|---|---|---|
| **run¹** 足部奔跑义 | to move using your legs, going faster than when you walk | 【图式：**方式伴随图式**】人/动物主体，以低速、一般方式在陆地介质中移动，动因自主；[可变槽位：速度=低；情态急促度=一般；动因=自主] | 图式标签；主体槽（人/动物）；介质槽；速度/情态/动因三档；簇 4「方式奔跑大类」17 成员；对齐=部分对齐；汉语句法=需方式状语补充 | 词频 **24,647,035**（run 全形 2,465 万次，与论文一致）；四图式重心：方式伴随 **54.19（第 1）**；簇内共享要素 M1a=0.765 / M1b=0.824 / M3a=1.00 |
| **jog¹** 慢跑义 | to run slowly and steadily for a long time, especially for exercise | 【图式：方式伴随图式】**人**主体，以低速、一般方式在陆地介质中移动，动因自主；[速度=低；情态=一般；动因=自主] | 与 run¹ 只差**一个槽位**（M1b：人/动物 → 人）——同簇近义差异被压成可对比参数 | 词频 168,439；方式伴随 33.60（第 1）；同簇（簇 4） |
| **sprint¹** 短距冲刺义 | to run or swim a short distance very fast | 【图式：**终点抵达图式**】人主体，**抵达终点，有界达成**，以**高速、急促**方式在陆地介质中移动，动因自主；[主体-动物=非动物；情态=急促；动因=自主] | 与 run¹/jog¹ **不同簇**（簇 1「短距有界冲刺类」：run²/sprint¹/charge⁷/dash¹）；P2=1、P3=1、P5=2 三项界定特征显式化 | 簇 1 画像 P2=P3=1.0、P5=2.0。⚠ sprint 属跑范畴补录 4 词（sprint/pound/stampede/career，不在 Levin 171 池语料提取范围），**无词频可引**，证据列只写簇画像 |
| **flee¹** 逃离义 | to leave a person or place very quickly, especially because you are afraid of possible danger | 【图式：**源点脱离图式**】人/动物主体，**自源点出发**，有界达成，以高速、急促方式在陆地介质中移动，**动因受迫**；[速度=高；动因=受迫] | 源点凸显＋受迫动因显式化；簇 5「逃离脱离类」6 成员 | 词频 1,127,096；语料候选 top-1 为方式伴随 41.05，**人工判定为源点脱离**——统计簇≠义位的实证案例（放 §5 讨论） |
| **escape¹** 逃脱义 | to get away from a place where you have been kept as a prisoner or not allowed to leave | 与 flee¹ **模板文本完全相同** | 暴露真实局限：15 维特征中没有「受困前提」一类，两义位在现有维度下不可分 | 词频 2,130,493；同上 |

**表后解读段**（紧跟表格）：

> 前两行显示平台把「同一簇内靠语感区分的近义梯度」变成了**可对比参数**（run¹ 与 jog¹
> 仅差主体槽一个维度）；第三行显示平台能把「终点＋有界＋高速」这类**事件结构**显式标出，
> 而 OALD 只能将其隐含在 *a short distance very fast* 的措辞中；第四、五行主动交代边界——
> 当两个义位的差异落在 15 维特征之外（如 escape 的「被拘禁前提」），模板输出同一文本，
> 此时必须由编者补写。这说明模板的定位是**结构化底座**而非成品释义：OALD 的释义是终点
> 产品，平台的标注与模板是结构化中间层——二者不是替代关系，而是标注资源让分范畴释义
> 模板的提炼成为可能。

### 4.3 论证三步（同时防住两种审稿质疑）

1. **展示 OALD 有什么**：释义准确、例句地道，但语义重心、事件要素、跨语言差异都隐含在
   措辞里，读者与学习者无法显式获取；义项之间没有统一刻画框架，近义差异散落于例句与
   用法提示中。
2. **展示平台多了什么**：同一义位经五维标注＋模板实例化后，语义重心显式化、事件要素
   结构化、跨语言差异可预期、每条判定可回溯到语料证据。
3. **点明边界（防过度宣称，勿删）**：对比展示的是标注资源对释义模板构建的**支撑价值**；
   成品词条级的优越性验证属于下一阶段（模板套用＋用户评估），本文不下此结论。

第 3 步同时回应「你在贬低 OALD 吗」与「你凭什么说你更好」两类质疑。

### 4.4 ⚠️ 风险与修正：用表前必须处理的 5 处

| # | 问题 | 实测证据 | 处理 |
|---|---|---|---|
| 1 | **逐义位标签是规则外推（候选），非人工成果** | `oald_senses` 996 条：`needs_review=1` 992 条；`human_reviewed` 全 0。`scripts/load_word_library.py:91-113` 写明首义位=Y、其余=拓展、图式/句法/译义取自 Levin 次类 | 表头统一写「**程序预编码（候选标签，待人工复核）**」；或先对拟展示的 3–5 个义位完成真实人工标注再引用 |
| 2 | **词目层与义位层 Y 标注矛盾** | `definitions.run.prototype_level='Y'`，但 `oald_senses` 中 run 的 39 个义项全部为「拓展」；另有 18 个词目一条 Y 都没有（如 arrive 4 条全拓展） | 明确「Y 为人工复核后回写」的口径；现状不要把两处 Y 同时引作证据 |
| 3 | **对齐等级无区分度** | `oald_senses.alignment`：992/992 全为「部分对齐」 | 对比表只引用跑范畴试点（32＋25 条，人工甄别过）的对齐判定；不用全库 992 条说「平台给出对齐分级」 |
| 4 | **flee/escape/arrive/chase 不宜作「优越性」样例** | 语料候选 top-1 与人工判定：arrive 方式伴随 43.25 vs 终点抵达；chase 源点脱离 40.09 vs 互动位移；全库候选与人工一致率 **119/171＝69.6%** | 这四词改放 §5 作「统计簇≠义位」的方法学证据；§4.2 对比表用 run¹/jog¹/sprint¹，再配一个边界案例（escape）自曝其短更稳 |
| 5 | **α 数值尚无数据** | `annotation_submissions`/`assignments`/`adjudications`/`reliability_runs` 四表全为 0 行 | 结果部分不得出现任何 α 数值；保持现稿口径「信度检验设计见 §3，数值于全量标注完成后如实报告」 |

另有两处小口径同步：论文「171 词 / 27 类槽位」→ 原始 48 种（归并 27）；「平台五页面」→
七区十七页（见 2.5）。

---

## 附录 A：答辩口头速查（四问各三句）

**Q1 MOVECAT 是什么缩写？**
MOtion VErb CATegorization，移动动词范畴化。项目与标注平台同名，平台题名是
A Prototype Annotation Platform for Schema-based Multi-dimensional Definition of English
Motion Verbs。注意题名是平台名，不是缩写展开。

**Q2 用什么技术实现？**
Python＋Streamlit 应用层、MySQL 54 张表数据层、Sketch Engine enTenTen21 语料层、
SciPy（Gower＋层次聚类）与 krippendorff 信度层；LLM 多供应商只出候选草稿、人裁决。
功能上是七区十七页：查阅展示 / 语义建模（五维标注＋盲标＋α）/ 语义分析 / 编纂产出
（模板→撰写→例证对译）/ AI 协作 / 词典管理 / 系统管理。配置驱动，跨范畴换配置包即可，
第二范畴已验证引擎零修改。

**Q3 OALD 版权怎么讲？**
四点：使用性质是被分析对象不是被出版内容；方式是本地判定＋必要范围内注明出处的个别
引用，不整表不分发；以主流学习词典为义项基准是领域惯例；公开数据最小化（只留 SenseID＋
标签＋统计），未来产品化另取授权。平台有 G6 许可终检闸门，部署包排除词典原文。

**Q4 凭什么说比 OALD 好？**
不比「谁的释义好」，比「多了什么」：OALD 4 项信息，平台 4＋12 项——图式、典型性、
对齐、句法、译义、证据链全部结构化可检索。run 和 jog 同簇只差一个主体槽、sprint 的
「终点＋有界＋高速」显式成槽，这些 OALD 只能藏在措辞里。边界也说清楚：平台是结构化
中间层不是成品释义，escape 与 flee 模板同文正说明 15 维之外仍需编者补写。

---

## 附录 B：v1 → v2 修订记录

| # | v1（2026-10-11 docx） | v2（2026-11-10） | 依据 |
|---|---|---|---|
| 1 | Q1 缩写展开残缺（「MOtion VErb CAT“”」） | 补齐为 **MOtion VErb CATegorization**；区分「缩写展开」与「平台题名」 | 三篇系列论文英文副题；docx 原稿无残留内容 |
| 2 | Q1 未提双名问题 | 新增 MOVECAT / LexiSchema 双名风险与统一口径建议 | `docs/spec/白话版对照清单.md`；代码内 LexiSchema 字样 |
| 3 | Q2 技术栈「enTenTen21 约 61 亿词」 | 改「约 520 亿词（61.6 billion tokens）」 | P1/P2 论文统一口径；Sketch Engine 官方 |
| 4 | Q2 「平台共五个页面」 | 七区十七页，逐页功能表 | `src/app.py` `_SIDEBAR_ZONES`；`src/page_guides.py` |
| 5 | Q2 技术栈无版本/规模 | 补实测版本（Streamlit 1.57 等）、54 表、2,566 测试、46,550 行 | 本机实跑 |
| 6 | Q2 无数据规模表 | 新增 2.3 节九项实测规模（996=992+4 等） | 数据库实查 |
| 7 | Q3 四点论述 | 保留四点；新增可粘贴中英段落＋平台技术保障＋三项现实风险 | 本机 git/文件实查 |
| 8 | Q4 limp-S1 单例五维表 | 改为五义位真实引擎输出对照表；limp 改为「语料候选与人工一致」的正例补充（方式伴随 27.999 居首，与 v1 数字吻合） | `template_engine` 现场实跑；`word_schema_scores` |
| 9 | Q4 建议 arrive-S1/chase-S1 作对照样例 | 改为风险项：二者的语料候选与人工判定相悖，移作 §5 方法学证据 | `corpus_word_stats` vs `definitions` 一致率 69.6% |
| 10 | — | 新增 2.5/4.4 两张「口径偏差修正表」（五页面、27 槽位、24 词条、Y 矛盾、对齐无区分度、α 无数据） | 数据库实查 |

---

*维护口径：本文与《MOVECAT问答文档.docx》并行存在；docx 为答辩定稿快照，本 md 为
随平台演进的活文档。平台功能/数字变更时先改这里，再在投稿前固化进 docx。*
