# S2 Review · 数据正确性审查（独立复算验证）

> 审查对象：`src/cluster_analysis.py`（Gower/medoid/tier）、`src/template_engine.py`（母图式提炼）、
> `src/category_study.py`（图式层对齐）、`src/semantic_search.py`（Gower 最近邻）。
> 审查方法：**不依赖被审模块数学代码的独立复算**——自写参考实现（Gower / medoid / tier /
> 图式划分 / 图式对齐 / 检索归一）+ 自写 SQL 直查 web_word_db，特征 value_type/ranges 与
> 图式名映射人工读 `configs/motion/features.yaml`、`schemas.yaml` 后硬编码；复算脚本以
> `python3 -I`（隔离模式）运行。
>
> **结论：五项全部核验通过，零数值偏差，无需修改任何源码；真值锚点全部与库吻合。
> 任务前提纠偏 1 处：`src/reliability.py` 从未含 Gower 实现（实为 Krippendorff α），
> 全仓 Gower 特征向量实现唯一（cluster_analysis.gower_distance），不存在需合并的双实现。**
> 修复后双绿：`pytest tests/ -q` = **608 passed**；`verify_paper_claims.py` = **53 通过 / 0 不符**。

## 0. 测试基线核对

- 审查起点实测：`python3 -m pytest tests/ -q` = **608 passed**（与 S1 收官一致，未漂移）；
  `MYSQL_HOST=127.0.0.1 python3 scripts/verify_paper_claims.py` = **53 通过 / 0 不符**。
- MySQL 以 `MYSQL_HOST=127.0.0.1` 连接（默认主机名 `mysql` 不可解析，S1 同款惯例）。

## 1. 清单逐项独立复算

### 1.1 Gower 实现一致性 —— 通过（前提纠偏，无双实现可合并）

| 检查点 | 结论 | 证据 |
|---|---|---|
| 前提核验：「reliability.py 有一套 Gower」 | ❌ 前提不成立 | `git log --all -S gower -- src/reliability.py` 为空（历史上从未有过）；`dir(reliability)` 无任何 gower/dissim/distance 符号；该模块是 Krippendorff α（巧合矩阵公式），正文仅 1 处注释提及「Gower 聚类的列范围」（reliability.py:569），无实现 |
| 全仓 Gower 实现唯一性 | ✅ | `gower_distance` 仅定义于 cluster_analysis.py:172；`semantic_search.gower_distance is ca.gower_distance`（同一函数对象，复用非复制，dev_semantic_search.md §5 口径）；`category_study.compute_schema_alignment` 的「Gower 式平均绝对差（/2 归一）」是图式中心的另一**文档化度量**（dev 文档明示），非同一函数的重复实现 |
| 混合类型+缺失值小样本（13 例） | ✅ | binary/ordinal/nominal 混合、单侧缺失剔出分母、双侧各缺、跨度 0 防除零、无共同特征记 0、ranges 缺省 (0,2)、value_types 外特征不进分母——`ca.gower_distance` 与独立参考实现逐例一致（含我方初版 1 个错误期望值 0.5/1.0 的排除，见 §3 复算记录） |
| 库内全矩阵 | ✅ | 51 编码义位（en 32 + zh 19）× 15 列，1275 对逐一比对 `ca.gower_matrix` vs 参考实现：零偏差；矩阵对称、对角 0 |

**判定：无偏差 → 无需提取公共函数**（cluster_analysis 内已是单处实现，semantic_search 已复用）。

### 1.2 medoid / tier 独立重算 —— 通过（en 5 簇 + zh 5 簇全量）

- 独立 SQL（cs_clusters/cs_cluster_members 按 `l.lemma, s.sense_no` 序）+ 参考实现重算每簇
  Gower 方阵、medoid（平均距离分母 n-1）、三分位 tier，与 `compute_medoid_ranking('RUN', lang)`
  逐位比对：**medoid、到 medoid 距离、tier、is_medoid、members 升序、tier 计数全部一致**
  （en 簇4 n=17 实测 6/5/6、medoid=gallop-2，与 S1 记录一致）。
- 平局留档：二值特征致距离强量化，8/10 簇的 medoid 存在等距平局
  （如 en 簇4 [10,11,16,28] 四方平局、zh 簇4 五方平局）；实现按成员装载序（lemma,sense_no）
  取首者，参考实现同口径同结果，**确定性与一致性均成立**（非缺陷，换序规则已隐含钉死）。

### 1.3 母图式共享/恒定特征集独立重算 —— 通过（en/zh 10 簇全量）

- 独立重算规则：binary 均值 ≥0.5 → schema_core、(0,0.5) → 槽位；序数/名义方差=0（且均值>0）
  → schema_core、方差>0 → 槽位；全簇全 0 → 不进模板；A1-A3 不进提炼；
  图式名映射：追逐过半 > P1 ≥0.5 > P2/P3 ≥0.5 > 方式伴随。
- 与 `derive_cluster_schemas('RUN', en/zh)` 逐簇比对：**schema_core（含均值 3 位小数）、
  variable_slots、图式名、schema_source=feature_map 全部一致；core∪slots 无任何 A 码**。
  抽样核对了 en 簇4（M1a 0.765/M1b 0.824/M3a 1.0，可变槽位 P5/M2/C1）与 S1、dev 文档一致。
- 口径留档（非缺陷）：「全簇全 0 不进模板」是 `docs/dev/reports/dev_template_engine.md` §3.1 规则表
  明文（「方差=0 **且均值>0**」+「任意 全簇全 0 不进模板」），实现与文档一致；
  真实库仅 zh 簇5（小跑，n=1）的 P5/M2 触发该条（速度=低/情态=轻缓不进模板）。
  代码 inline 注释「0 也是有意义的取值」指非全零列的同值共享分支，与文档规则不冲突。

### 1.4 最近邻归一化分母口径 —— 通过

- `search_similar_senses` 的分母 = `gower_distance` 内部的 `len(common)`（双方共同编码特征数），
  与返回的 `matched_features` 为**同一集合**——报告口径与计算口径必然一致，无「分母错位」路径。
- 实测（查询向量 {P1:1,P5:2,M3a:1,C1:2}，en 32 义位）：每条 distance 与参考实现一致、
  `distance×|common|` 还原逐特征分支和（无隐藏归一）；库侧 51 义位 in_clustering 特征均
  15 列齐全 → 同一次检索内所有候选分母恒等（=查询特征数 4），**分数可比性成立**；
  无共同特征的义位被跳过（Gower 记 0 的陷阱已防）。跨范畴/跨语言本就不混检
  （检索作用域 = 范畴 × 语言，各自 packs 的 value_types 同源），不存在跨词类分数混比面。
- 旁证一致性：15 维均值「/2 归一」口径在 `compute_schema_alignment`、
  `category_study_page._render_feature_mean_chart`、`verify_paper_claims`（SQL AVG/2）三处同约定、
  同 15 列（CLUSTERING_FEATURES/in_clustering）范围、同「剔除无编码义位」处理。

### 1.5 真值锚点校验 —— 通过（全部以库为准，零改动）

| 锚点 | 独立复算/直查结果 |
|---|---|
| cophenetic 英 0.825 / 汉 0.795 | ✅ cs_cluster_runs 直查一致 |
| k=5（en/zh 两条 run params） | ✅ 均 `{"k": 5}`，英 5 簇 / 汉 5 簇 |
| 对齐 完全 1 / 部分 3 / 零 1 | ✅ cs_cluster_alignment 直查一致 |
| 方式奔跑 d=0.045 | ✅ 直查一致 |
| 图式层 0.018 / 0.066 | ✅ 独立重算精确值 0.017778 / 0.065833，按论文口径 3 位舍入吻合；成员数 18/10、5/8、9/0（终点抵达汉 0）、0/1（互动位移英 0）全吻合 |
| 域系 352 条（264/62/26） | ✅ domain_family_senses 直查一致 |
| 其余（171 词/12 次类/1935 关系/996 义位/918 格等） | ✅ verify_paper_claims 53 项全过 |

独立复算与真值**零冲突**，未发现需「以库为准」修正的实现 bug。

## 2. 修复清单

**无源码修复**（五项复算零偏差；唯一「修复」是任务前提纠偏：Gower 双实现的前提不成立，
reliability.py 为 Krippendorff α 实现，全仓 Gower 单实现且已被 semantic_search 复用，
无可提取、无漂移风险）。未新增测试（行为零变更，既有 608 用例已覆盖各分支；
复算脚本存于 `/tmp/s2_review/s2_recompute.py` 供复核，不入库）。

## 3. 复算记录（过程透明）

初版复算脚本曾报 10 项不符，逐一排查后**全部为脚本自身问题**，被审实现无一有错：
① case「双侧各缺不同特征」我方期望算错（common 含 O 同值对，正确期望 0.5 非 1.0，ca 正确）；
② §1b 列数断言误把 6 条 zh 剔除义位（无编码）计入「51 义位」集合；
③ medoid 距离逐位比对误用排序后下标索引装载序矩阵（平局簇错位，对回 sense_id 后一致）；
④ zh 簇5（n=1）tier 计数期望未复现「边缘份额上限 n−n_proto」的截断（实现正确）；
⑤ §0 结构断言误把 reliability.py 注释中的「Gower」字样当实现。
修正后 164 项检查全部 PASS。

## 4. 复现

```bash
MYSQL_HOST=127.0.0.1 python3 -m pytest tests/ -q          # 608 passed
MYSQL_HOST=127.0.0.1 python3 scripts/verify_paper_claims.py 2>&1 | tail -1   # 53 通过 / 0 不符
MYSQL_HOST=127.0.0.1 python3 -I /tmp/s2_review/s2_recompute.py               # S2 复算 164 项全 PASS
```
