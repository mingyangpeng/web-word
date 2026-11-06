# S1 Review · 功能对照 + 安全审查（三新模块接管代审）

> 审查对象：`src/cluster_analysis.py`、`src/template_engine.py`、`src/semantic_search.py`
> 及其在 `src/app.py` 的集成点（cluster / template / semantic 三入口）与 `src/page_guides.py` 扩写。
> 审查依据：sess_55181c38 主会话 S1 审查清单（七项，见 §1）；方法 = 逐条代码核验 +
> 真实库实测（MySQL 127.0.0.1，RUN 范畴 en 32 义位 / 汉 19 条目）+ scipy 手算对照 + pytest 全量。
>
> **结论：七项全部核验通过；发现并修复 2 处（1 处文档性、1 处安全加固，均无行为回退），
> 新增 1 个安全回归测试。修复后 `python3 -m pytest tests/ -q` = 608 passed 全绿。**

## 0. 测试基线核对（清单第 7 项）

- 审查起点实测：**607 passed**（非任务口径的 595；443 基线 + 本批新增的账面应为 595，
  工作区实际比该口径多 12 个用例，应为 S1 审查前主会话/监工后续又补的用例 —— 以实测为准，
  不虚报）。修复后复跑：**608 passed**（+1 为本次新增的安全回归用例）。
- MySQL 连接：审查中曾断连（默认主机名 `mysql` 解析失败），按惯例以
  `MYSQL_HOST=127.0.0.1` 恢复，无需 repair.sh（数据完好，未重灌）。

## 1. 清单逐项核验

### 1.1 medoid 逻辑 —— 通过

| 检查点 | 结论 | 证据 |
|---|---|---|
| medoid = 簇内 Gower 距离均值最小者 | ✅ | `medoid_index`（cluster_analysis.py:215）：`sum(dist_matrix[i])/(n-1)` 取最小，平局取下标最小者；单成员簇记 0。手算 3×3 矩阵对照通过 |
| tier 三分位 | ✅ | `assign_tiers`（:230）：`ceil(n/3)` 原型 / 中段次典型 / `ceil(n/3)` 边缘，medoid 距离 0 恒居首恒为原型。真实库簇 4（17 成员）实测 6/5/6，medoid=gallop（距离 0） |
| 分母口径 | ✅ | 平均距离分母 n-1（其余成员数），非 n —— 与「到其他成员的平均距离」定义一致 |

### 1.2 scipy linkage 输入 —— 通过

- 全仓（三模块范围）仅两处 `linkage` 调用：`linkage_from_distance_matrix`（:491-492）
  先 `_scipy_squareform` 压缩方阵再喂 linkage；页面 `create_dendrogram`（:622-626）
  以 2D 方阵 + `distfun=_scipy_squareform` 直传 —— **无任何直接喂非方阵/未压缩矩阵的路径**。
- NaN 面：距离矩阵全部由 `gower_matrix` 自产（int 编码 → 有限值，对角恒 0、恒对称）；
  ordinal 值域跨度为 0 时 `span else 0.0` 已防除零，无 NaN 来源。`len < 2` 抛 ValueError，
  不静默。

### 1.3 k=5 参考线 —— 通过（订正 1 处 docstring）

- k 的来源：`build_dendrogram_data` 取 `cs_cluster_runs.params` 的 `k`。真实库核对：
  RUN 范畴 en/zh 两条 run 的 params 均为 `{"k": 5}`，algorithm=`Gower+average` ——
  **与论文口径（RUN 范畴 k=5 探索性切分）一致**；页面文案明确「k=5 只是 d1 试点
  采用的探索性解，不是唯一正确答案」，不夸大。
- 切分高度约定：`cut_height_for` 取行 `n-k`（即首个会跌破 k 簇的合并高度），
  「严格低于该线的合并恰有 n-k 次 → k 簇」。真实库实测：n=32、k=5 时
  cut=0.2、线下合并 27 = n-k ✅。该口径与 plotly `color_threshold`（高亮恰 k 簇）及
  既有测试 `test_cut_height_yields_k_clusters` 的严格小于断言一致，**代码行为正确**；
  但原 docstring 首句写「第 (n-k) 次合并的高度」与取行 `n-k`（第 n-k+1 次）自相矛盾，
  已订正措辞（见 §2 修复①，行为不变）。

### 1.4 母图式提炼 —— 通过

| 检查点 | 结论 | 证据 |
|---|---|---|
| 二元均值 ≥0.5 判共享 | ✅ | `derive_cluster_schema_from_members`：`mean >= CORE_THRESHOLD(0.5)` → schema_core，`(0, 0.5)` → 可变槽位；全簇全 0 不进模板 |
| 序数/名义方差=0 判恒定 | ✅ | 非二元分支 `var == 0 → core`（记共享取值）、`var > 0 → 槽位`；`pvariance` 单成员簇记 0 |
| A 组（A1-A3）不进图式提炼 | ✅ | `semantic_meta` 只收 `in_clustering=true` 的特征（motion 包 = P/M/C 15 列），A 列（in_clustering=false）不进 means/core；`build_template` 里 A 组只进句法维度核验；`load_feature_types` / 检索向量同口径排除 |
| 真实库对照 | ✅ | 簇 4「方式奔跑大类」实测 schema_core = {M1a: 0.765, M1b: 0.824, M3a: 1.0}，可变槽位 P5/M2/C1，图式=方式伴随图式（feature_map）—— 与 `docs/dev_template_engine.md` §4 的真实输出逐字一致；core 中无任何 A 码 |

### 1.5 模板引擎四维 —— 通过（附口径说明）

- 实现的四维 = **图式维度 / 语义参数维度 / 句法维度 / 对齐预留维度**（论文 §6.2），
  `build_template` 无条件产出全部四键，缺一即 KeyError（报错而非静默）；测试
  `test_template_engine.py:217-221` 逐键断言「缺四维结构之一」即 fail ——
  **结构性齐全，无缺维静默输出路径**。数据不可用时 `instantiate_template` 返回
  None 并记 error 日志（降级不崩、不假输出）。
- 口径说明：清单括注的「方式/路径/方向/体相」是论文的**五元语义分解**
  （方式/路径/方向/体相/范围，P2/P3 论文原文），属词条内容要素，不是模板的
  四维结构名 —— 两者在 `page_guides.py` 与 dev 文档中分属不同概念层。
  d1 试点 15 特征不含体相/范围列，模板正文按既有拼装表（主体/路径/方式/介质/
  动因）生成。实现与 dev_template_engine.md §3.4、论文 §6.2 一致，不按清单括注
  改代码（避免虚构需求）。

### 1.6 安全项 —— 通过（加固 1 处）

| 检查点 | 结论 | 证据 |
|---|---|---|
| 新三页输入点过 src/security 校验 | ✅（修复后） | cluster/template 两页仅 selectbox/radio（选项来自包目录/DB 枚举），无自由文本；semantic 页查询框为唯一自由文本输入，**修复前未过安全校验 —— 已修（见 §2 修复②）**：`InputValidator.validate_string(query, max_length=200)` 不过即 st.error 拒绝，控件层另加 `max_chars=200`。查询句本不进 SQL、不原样渲染 HTML（chips/展开卡均过 `_html_escape`），此为纵深防御 + 超长截停，与首页动词搜索（app.py:908）同口径 |
| CSV 导出过 sanitize | ✅ | 三模块中仅 template_engine 有导出：`build_export_csv` 对每个单元格过 `src/security.sanitize_csv_value`（与 `sanitize_csv_dataframe` 同一底层实现，security.py 明示二者同源；列表行导出用单元格函数是正确选择）。新 patch 文档同步声明 |
| 无 SQL 拼接注入面 | ✅ | 三模块 9 处 `cursor.execute` 全部参数化（`%s` 占位）；f-string 仅用于拼占位符个数（`",".join(["%s"]*n)`），**无任何值拼接进 SQL**；`lookup_sense_id` 动态追加的是固定片段，值仍在参数列表 |

### 1.7 测试基线 —— 通过（口径见 §0）

`python3 -m pytest tests/ -q` 修复前 607 passed（1:25），修复后 **608 passed** 全绿；
新增用例 `test_malicious_query_rejected_by_validator` 覆盖本次安全加固。

## 2. 修复清单（外科手术式，无重构无重排）

| # | 文件:行 | 问题 | 改法 |
|---|---|---|---|
| ① | `src/cluster_analysis.py:496-506`（`cut_height_for` docstring） | 文档缺陷：首句「第 (n-k) 次合并的高度」与代码取行 `n-k`（第 n-k+1 次合并）矛盾，易误导后续维护者误改行为 | 仅订正 docstring 措辞为「首个会跌破 k 簇的合并（第 n-k+1 次）的高度」，并注明与 plotly color_threshold / 测试严格小于口径一致；**代码与测试零改动，行为不变** |
| ② | `src/semantic_search.py`（import 区 + `render_semantic_search_page`） | 安全加固：唯一自由文本输入点（查询框）未过 `src/security.py` 校验（清单 1.6），与全库自由文本输入惯例不一致 | 导入 `InputValidator`；查询框加 `max_chars=200`；空查询早退后 `validate_string(query, max_length=200)` 不过 → `st.error` 明示拒绝并 return（不进解析/检索/LLM） |
| ③ | `tests/test_semantic_search.py`（TestPage） | 为修复②补回归测试 | 新增 `test_malicious_query_rejected_by_validator`：`<script>` 注入串 → 页面报「未通过安全校验」、不渲染结果表、无异常 |

未修复事项（核验判定为非缺陷，留档）：`cut_height_for` 在 scipy `fcluster`（≤ 语义）
下切出 k-1 簇 —— 系该函数文档化的「严格小于」可视参考线约定（测试钉死、plotly 同口径），
非 bug；如后续要接 fcluster 请另行显式换算。

## 3. 数据真值核对（红线项）

- 171 词（方式 136 / 路径 22 / 互动 13）：`page_guides.py`「search/graph」段口径一致 ✅
- RUN 试点：英 32 义位 / 汉 19 条目 —— 与 cs_cluster_members 实测一致（en 32 / zh 19）✅
- cophenetic 英 0.825 / 汉 0.795：`page_guides.py`（category 段）原样保留 ✅
- k=5：两条 run params 均为 `{"k": 5}`；页面/说明均标「探索性」✅
- d=0.045 / 0.018 / 0.066：page_guides 既有 d<0.05 阈值文案与 d=0.045 实例未被改动 ✅
- α：新增代码零提及 α 具体值；信度页文案维持「达标线 α ≥ 0.7 / 未实测显示 —」口径 ✅
- 996 义位（992 OALD + 4 补充）：三新模块与 page_guides 扩写未触碰该真值 ✅

## 4. 复现

```bash
MYSQL_HOST=127.0.0.1 python3 -m pytest tests/ -q   # 608 passed
MYSQL_HOST=127.0.0.1 python3 -c "from src import cluster_analysis as ca; \
  d=ca.build_dendrogram_data('RUN','en'); print(d['k'], d['cut_height'])"   # 5 0.2
```
