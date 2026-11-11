# 开发报告：释义模板引擎（母图式自动提炼 + 槽位实例化 + 批量导出）

> 对应 `docs/spec/白话版对照清单.md` 第二档 F5（自动生成释义模板的引擎）与
> 第三档「模板批量导出」；目标形态 = 论文 §6（Lexikos Project的写作-261104）
> 的四维模板与 §6.4 对照表（run¹/jog/march 三个手工样例）。
>
> 交付：`src/template_engine.py`（新）、`tests/test_template_engine.py`（新）。
> 未改动任何受约束文件（app.py / page_guides.py / category_study*.py /
> cluster_analysis.py / semantic_search*.py / users_db.py / annotation_flow.py /
> reliability.py）；`src/security.py` 无需改动——CSV 防公式注入函数
> `sanitize_csv_value` 已存在，直接复用。

## 1. 交付面一览

| 需求（清单口径） | 实现 | 入口 |
|---|---|---|
| 母图式自动提炼 | 逐簇取 cs_sense_features 长表成员均值，阈值划分共享要素/可变槽位 | `derive_cluster_schemas(category, language)` |
| 槽位实例化 | 单义位特征向量 → 四维模板（图式/语义参数/句法/对齐预留）+ OALD 原文对照 | `instantiate_template(category, language, sense_id, engine_schema=None)` |
| 模板文字生成 | 确定性槽位拼装，**不调 LLM**，词面全部来自 features.yaml | `render_template_text(...)` / `build_template(...)` |
| 批量导出 | 当前簇全部义位 → CSV（§6.4 列结构）+ 结构化 JSON | `collect_cluster_templates` / `build_export_csv` / `build_export_json` |
| 页面（集成步骤接线） | 簇选择 → 母图式两栏卡片 → 同簇并排总览 → 义位实例化卡片 → OALD 并排对照 → 人工修订（版本留痕）→ 两个导出按钮 | `render_template_page()` |
| 同簇并排总览（FX-38） | 整簇义位「词典原文 vs 模板化释义」一屏对照表；修订行带「已修订（vN）」标记 | `overview_rows(templates, revisions)`（纯函数）+ 页内 `st.dataframe` |
| 在线人工修订（FX-38） | 编纂职能 editor/reviewer/dict_admin 在线改模板文本＋优化要点，按版本留痕；引擎输出并存为基线；库离线整块降级 | `src/template_revision_db.py`（save/get_latest/get_latest_revisions/list_revisions/get_latest_notes） |

## 2. 架构与数据流

```
configs/motion/features.yaml ──(load_pack)──► 特征元数据 {code: label/value_type/values}
configs/motion/schemas.yaml  ──(load_pack)──► 四图式定义（名称/重心定义）
cs_cluster_runs → cs_clusters → cs_cluster_members → cs_sense_features
        │                                   （get_clusters_with_members 复用）
        ▼
derive_cluster_schemas(RUN, en)          【母图式提炼】纯函数核心
        = derive_cluster_schema_from_members(cluster_meta, 成员特征矩阵, …)
        ▼
instantiate_template(RUN, en, sense_id)  【槽位实例化】纯函数核心
        = build_template(义位行, 特征向量, 母图式, …)   ← cs_senses.definition（OALD 原文）
        ▼
collect_cluster_templates → build_export_csv / build_export_json
```

分层原则与 test_category_study 相同：**纯函数核心（可合成数据全测）+ DB 编排**
（失败降级返回 `[]` / `None` 并记日志，不崩）。

### 2.1 命名空间桥接：RUN → motion

cs 表的范畴代号（`categories.code = 'RUN'`）与 configs 包名（`motion`）是两套
命名空间。`resolve_pack(category, observed_codes)` 按确定性顺序解析：
同名直取 → 否则扫描全部范畴包，选特征编码与义位实际编码列重合度最高的包。
无候选时抛 `CategoryPackError`（编排层降级）。

## 3. 规则口径（全部确定性）

### 3.1 母图式提炼（schema_core / variable_slots）

只提炼语义要素：`in_clustering=true` 的特征（motion 包 = P/M/C 15 列）。
**A 组核验特征不进图式**（真实数据教训：簇1 的 A1「构式论元-不及物」全簇为 1，
若不过滤会冒充语义共享要素；A 组属于句法维度）。

| 特征类型 | 条件 | 归属 |
|---|---|---|
| binary | 均值 ≥ 0.5 | schema_core（共享要素，记均值） |
| binary | 均值 ∈ (0, 0.5) | 可变槽位 |
| ordinal / nominal | 簇内方差 = 0 且均值 > 0 | schema_core（记共享取值） |
| ordinal / nominal | 簇内方差 > 0 | 可变槽位（附取值分布：计数+占比） |
| 任意 | 全簇全 0 | 不进模板（与本簇无关） |

可变槽位的取值分布按计数降序，附 `ratio`（占比，3 位小数）。

### 3.2 簇 → 四图式映射（图式维度）

优先级与 `category_study.derive_image_schema` 的凸显顺序一致：
追逐标注过半 → 互动位移；P1 均值 ≥ 0.5 → 源点脱离；P2 或 P3 均值 ≥ 0.5 →
终点抵达；其余 → 方式伴随。名称/定义取自 schemas.yaml；
映射不上时退回簇名字面匹配，再不行返回 None。

### 3.3 模板文字拼装（参照论文样例格式）

格式：`【图式：X】主体，路径，以方式移动，动因Y；[可变槽位: …]`

| 片段 | 来源（词面均出自 features.yaml） |
|---|---|
| 主体 | M1a-M1d 取 1 的 label 去「主体-」前缀，"/" 连接 +「主体」；无 → 主体不限 |
| 路径 | P1/P2/P3/P4 取 1 → 自源点出发 / 抵达终点 / 有界达成 / 沿垂直轴向 |
| 方式 | P5（值标签+「速」）、M2（值标签）按「、」连接 →「以…方式」 |
| 介质 | M3a-M3d 取 1 的 label 去「介质-」前缀 →「在 X 介质中」 |
| 动因 | C1 值标签 →「动因 X」 |
| 槽位清单 | 本簇可变槽位 × 本义位取值的中文标签 |

同一输入两次渲染逐字符相同（测试断言）；无随机、无 LLM 调用。

### 3.4 四维结构（论文 §6.2）

- **图式维度**：图式 code/name/definition（schemas.yaml）+ 所属簇 + schema_core；
- **语义参数维度**：15 项语义槽位逐条 `{code, label, value, value_label, role}`，
  role = core（簇共享）/ variable（可变槽位）/ off（全簇无关）；
- **句法维度**：A 组核验特征（A1 构式论元-不及物 / A2 及物使役 / A3 主体受限，
  来自 cs 表 A 列）+ 及物性摘要（不及物 / 及物使役 / 未标注）；
- **对齐预留维度**：`{filled: False, note: …}` 空槽，待跨语言簇对齐 /
  双语同位义位回填后实例化（论文 §6 的编辑流程预留）。

词典原文一并返回：`oald = {source, grammar, definition}`，
复用 `oald_senses.split_definition` 把 `[intransitive]` 语法码剥到 grammar，
释义正文干净可直接对照（§6.4 两列）。

## 4. run-S1 复现对照（真实 cs 数据，MySQL RUN 范畴）

引擎对簇4「方式奔跑大类（17 条）」提炼出的母图式（真实输出）：

```
schema_core: 主体-人 0.765 / 主体-动物 0.824 / 介质-陆地 1.0
可变槽位:  速度 低:15/17·中:2/17   情态急促度 急促:10/17·一般:7/17
          动因 自主:13/17·受迫:4/17
图式映射:  方式伴随图式（MANNER_ACCOMP，feature_map）
```

按论文 §6.4 的列结构对照（run 与 jog 为同簇真实义位；march 不在跑范畴
甄别表 23 个英语词目内，故以同簇 sprint 替补第三例）：

| 词条（义位） | OALD10 原文释义 | LexiSchema 模板化释义（引擎真实输出） |
|---|---|---|
| run1（足部奔跑义） | [intransitive] to move using your legs, going faster than when you walk | 【图式：方式伴随图式】人/动物主体，以低速、一般方式在陆地介质中移动，动因自主；[可变槽位: 速度=低；情态急促度=一般；动因=自主] |
| jog1（慢跑义） | [intransitive] to run slowly and steadily for a long time, especially for exercise | 【图式：方式伴随图式】人主体，以低速、一般方式在陆地介质中移动，动因自主；[可变槽位: 速度=低；情态急促度=一般；动因=自主] |
| sprint1（短距冲刺义）·簇1 | to run or swim a short distance very fast | 【图式：终点抵达图式】人主体，抵达终点，有界达成，以高速、急促方式在陆地介质中移动，动因自主；[可变槽位: 主体-动物=非动物主体；情态急促度=急促；动因=自主] |

与论文手工样例（【图式：实体自主位移】[人/动物]，以快速、双腿交替的步态移动；
[可选参数：目标/方向，±有目的]）的差异，如实说明：

1. **图式命名**：论文手工样例用「实体自主位移」，引擎输出 schemas.yaml 的
   「方式伴随图式」——以配置文件为唯一事实源，编者可在四维卡片上改定。
2. **主体**：run1 编码 M1a=1+M1b=1 → 「人/动物主体」，与手工样例 [人/动物] 一致；
   jog1 编码仅 M1a=1 → 「人主体」，与手工样例 [人] 一致。
3. **速度措辞**：编码矩阵中 run1 的 P5=0（低）——引擎如实输出「低速」，
   手工样例的「快速」掺入了编者语言。这是**编码口径 vs 编辑措辞**的差别，
   模板把差异固化为可对比参数（速度槽 15/17 为低）正是 §6.4 优化要点
   「速度层级梯度」的机器版。若编者按判 run 应为「中速」，改编码重跑即可。
4. **槽位措辞**：手工样例的「可选参数：目标/方向，±有目的」是人工概括；
   引擎输出特征级槽位（终点凸显=不凸显 等），保证可批量、可复现。
5. **步态细节**（「双腿交替」「固定步幅」）：18 列特征中没有步态维度，
   引擎不做超出配置的推断——这正是「模板给编者当结构化底座、编者润色定稿」
   （论文 §6.2 人机协同原则）的分工边界。

## 5. 导出与安全

- CSV 列序 = §6.4 对照表：词条义位 / OALD10原文释义 / LexiSchema模板化释义 /
  图式维度 / 语义参数维度 / 句法维度 / 对齐预留维度 / 簇号 / 簇名 /
  优化要点（编者填写，留空列）。
- 每个单元格过 `src/security.sanitize_csv_value`：以 `= + - @ \t` 开头的文本
  前置单引号，防 Excel/WPS 公式注入（CSV Injection）。该函数已存在
  （test_csv_protection.py 全套覆盖），**未新增、未改动 security.py**。
- 页面下载用 `utf-8-sig`（带 BOM，Excel 直开中文不乱码）；JSON 用
  `ensure_ascii=False, indent=2`，保留中文四维键。

## 6. 页面

`render_template_page()`（app.py 接线由集成步骤统一做）：
范畴 → 语言 → 簇 → 母图式两栏卡片（核心要素 vs 可变槽位，槽位带取值分布）
→ **同簇并排总览（FX-38）**：`instantiate_templates` 批量实例化整簇 +
`template_revision_db.get_latest_revisions` 批量取修订 → `overview_rows`
纯函数行构造 → `st.dataframe`（TextColumn width=large，域系页先例同款；
词典原文列来源随语言标注 OALD10/现汉7）
→ 簇内义位 → 实例化模板卡片（四维分栏）→ 与词典原文并排对照 →
**人工修订面板（FX-38）**：现行修订 info（版本/修订人/优化要点）+ 修订
表单（textarea 预填现行文本 + 优化要点 input；`require_role_interactive`
页面闸 + 数据层 `require_role` 二次闸；成功 `ui_kit.flash` + `st.rerun`，
RV12-2 纪律）+ 修订历史 expander（version DESC）；无编纂职能角色降级只读
→ 「生成当前簇全部模板」按钮 → CSV（FX-38：有修订义位自动回填「优化要点」
列，列结构 10 列不变）/ JSON 两个下载。
AppTest 无头冒烟验证：无异常、簇切换正常、17 条模板生成、两个下载控件渲染
（streamlit 1.57 的下载数据走 deferred blob，AppTest 树中不可直接读字节，
载荷正确性由单元测试覆盖）。库不可用时按全库惯例降级提示，不崩——FX-38
三处（并排总览修订列 / 修订面板 / CSV 回填）各自 fail-open，页面其余功能
不受影响。

## 7. 测试

`tests/test_template_engine.py`（FX-38 后 37 项）＋
`tests/test_template_revision_db.py`（FX-38 新增 16 项：守卫/清洗不碰库
＋集成类走独立库 `web\_word\_template\_revision\_test`，grant 脚本已补
三 host 授权），全绿；页面说明锚点测试（test_page_guides.py）锚「母图式」
「确定性槽位拼装」保持命中：

| 层 | 覆盖 |
|---|---|
| 母图式提炼（合成矩阵，不碰库） | binary 均值 1.0/0.5 边界/0.25 归属正确；序数同值→核心、分歧→槽位；全 0 剔除；A 组不进图式；空簇；四图式映射（P1→源点脱离、P2/P3→终点抵达、追逐→互动位移、无路径→方式伴随、无 defs→None） |
| 槽位实例化（合成数据） | 四维字段齐全；中文 label/值标签逐项对齐 features.yaml（源点凸显/人主体/自主/陆地介质）；OALD 语法码剥离；及物性摘要；模板文字确定性（两次调用逐字符相同）+ 随向量变化（flee 式）+ 无簇回退 |
| 导出（合成数据） | CSV 首个 `=` 开头单元格被前置单引号（防公式注入全表断言）；列结构 = §6.4 表；JSON 四维键 round-trip；FX-38 notes 回填（按 sense_id 填「优化要点」，缺省 None 与历史输出逐字节一致） |
| 并排总览行构造（FX-38，纯函数） | 基础字段/引擎基线标记；修订覆盖与「已修订（vN）」标记；无修订占位"—"；非法输入跳过/退化；混合修订逐行标记 |
| 配置桥接 | motion 直取；RUN + 观测编码列 → motion；无候选包抛 CategoryPackError |
| 修订数据层（FX-38，不碰库） | 未登录/viewer/annotator PermissionError；定位三元组与文本/note/sense_ref 清洗拒收；CAN_REVISE_ROLES 与 lexical_pages.CAN_EDIT_ROLES 同集钉死；allowed 空 fail-closed 回归护栏 |
| 修订数据层（FX-38，独立库集成） | 建表幂等；版本原子自增 1→2→3；latest 取最大版；批量/历史排序/多范畴隔离；无修订义位 fail-open 空读；viewer 写路径真表复核 |
| MySQL 路径（不可用 skipif，与 test_category_study 同口径） | 真 RUN 数据：英 5 簇提炼、核心/槽位 ⊆ in_clustering 特征集；run-S1 实例化对照论文样例（簇4→方式伴随图式、C1=自主、M1a=人主体）；簇4 全量 17 条导出 CSV/JSON 校验 |

flake8（max-line-length=100）对两个新文件零告警。

## 8. 边界与后续

- 槽位拼装表（M1a-M1d / P5 / M3a-M3d / P1-P4 / C1）引用 motion 包特征编码，
  口径同 category_study.py；换词类 = 换 configs/<category>/ 并扩展拼装表，
  主流程（提炼/实例化/导出）零修改。
- 对齐预留维度当前恒为空槽：回填动作依赖跨语言簇对齐（cs_cluster_alignment）
  与双语同位义位判定，属于后续开发（论文 §6 把定稿权留给编者）。
- march 不在跑范畴甄别表内，论文 §6.4 第三例如需 march 需先扩甄别数据。
