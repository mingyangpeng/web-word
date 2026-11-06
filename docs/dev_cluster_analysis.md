# 开发报告：聚类可视化与典型性排序（F3 谱系树 + F6 medoid 排序）

> 交付人：开发1（Agent）· 日期：2026-11-06
> 对应缺口：docs/p1/白话版对照清单.md 第三档 F3（谱系树）与 F6（medoid 典型性排序），
> 支撑论文 §5.1（谱系树可交互切割）与 §5.2（原型/次典型/边缘程序化判定）。

## 1. 交付物清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `src/cluster_analysis.py` | 新增 | Gower 相异度、medoid 典型性排序、谱系树数据、Streamlit 页面（约 700 行，含 docstring） |
| `tests/test_cluster_analysis.py` | 新增 | 39 个测试：纯函数（合成向量、已知 medoid）+ 范畴包元数据 + DB 端到端（skipif）+ AppTest 页面冒烟 |
| `requirements.txt` | 修改 | 仅追加 `scipy>=1.10.0`（谱系树 squareform+linkage 需要；本环境已装 1.17.1，补进依赖清单保证可复现） |

未触碰约束清单里的任何文件（src/app.py、page_guides.py、category_study.py、
category_study_page.py、reliability.py、annotation_flow.py、users_db.py、
template_engine.py、semantic_search.py）。页面接入由集成步骤统一做。

## 2. 公开 API（函数签名与口径）

### F6 典型性排序

```python
compute_medoid_ranking(category="motion", language="en", run_id=None,
                       value_types=None, ranges=None,
                       prototype_share=1/3, periphery_share=1/3) -> list[dict]
```

- `run_id=None` 取该范畴+语言**最新**聚类运行（id 最大）；显式 run_id 不属于该
  语言时告警并回退最新运行。
- 每簇输出：

```python
{"cluster_id", "cluster_no", "cluster_name", "size",
 "medoid": {sense_id, verb, sense_no, sense_label, gower_to_medoid, tier},
 "members": [{sense_id, verb, sense_no, sense_label, gower_to_medoid,
              tier, is_medoid}, ...]}   # 按 gower_to_medoid 升序（平局按 sense_id）
```

- **medoid** = 簇内到其他成员平均 Gower 距离最小的成员（平均分母 n-1；
  平局取成员装载序（cs_cluster_members 按 lemma/sense_no 排序）最前者，
  确定可复现 —— S1 review 更正：非「sense_id 最小者」）。
- **tier 三分位**：成员按到 medoid 距离升序排名，最近 ceil(n/3) = prototype、
  最远 ceil(n/3) = periphery、中间 = typical；份额可配置
  （`prototype_share`/`periphery_share`，typical 自动取中间余量）。
  边界行为：n=1 → 全 prototype；n=2 → 1 原型 + 1 边缘（无次典型）；
  medoid 距离恒为 0，必属原型。平局按输入下标序稳定切分。
- 范畴/运行不存在 → 返回 `[]`（不抛异常）。

### F3 谱系树

```python
build_dendrogram_data(category="motion", language="en", run_id=None,
                      value_types=None, ranges=None) -> dict
```

- 与 medoid 排序**同一特征矩阵**（`_load_cluster_matrix` 共用装载），
  成员按 verb/sense_no/sense_label 排序保证叶序确定；labels = `verb-Sn`
  （en: `run-S2`；zh: `跑-S①`，缺义项号记 `S—`）。
- 返回 `{"labels", "linkage"（n-1×4 列表）, "distance_matrix"（Gower 方阵）,
  "n_senses", "method": "average", "metric": "gower", "run_id", "language",
  "study_code", "k"（运行参数 params.k）, "cut_height", "members"}`。
- scipy 不原生支持 gower 度量 → 预计算 Gower 方阵，经 `squareform` 压缩后
  `linkage(method="average")`（UPGMA，与 d1 运行的 `Gower+average` 口径一致）。
- `cut_height` = 切成 k 簇的参考高度 = 第 (n-k) 次合并的高度（该高度再合并
  一次即跌破 k 簇）；k=1 取最后一次合并高度；k 出界 → None。
- 簇成员 < 2 → `{}`；scipy 缺失 → 抛 `ImportError`（页面侧降级告警）。

### 纯函数（可独立复用/测试）

- `gower_distance(vec_a, vec_b, value_types, ranges)`：binary/nominal 不一致记 1、
  ordinal 记 |a−b|/值域跨度（值域来自 features.yaml `values` 键 min-max，
  如 P5/M2 → (0,2)），取各特征均值；无共同特征记 0。
- `gower_matrix(vectors, value_types, ranges)`：对称方阵，对角 0。
- `medoid_index(dist_matrix)`：平均距离最小者下标（平局取下标最小）。
- `assign_tiers(distances, prototype_share, periphery_share)`：与输入同序的
  tier 列表。
- `linkage_from_distance_matrix(dist_matrix, method="average")`、
  `cut_height_for(linkage_matrix, k)`。
- `load_feature_types(category)`：读范畴包 features.yaml 的 value_type 与
  ordinal 值域（仅 in_clustering=true 的 15 列，A1-A3 核验区排除）。

## 3. 数据链与范畴解析

- 数据复用 `src/category_study.py` 的 cs_* 表：`get_categories()`（范畴定位）、
  `get_cluster_runs(category_id, language)`（运行解析）、
  `get_clusters_with_members(run_id)`（簇与成员）；
  另有一条自建查询取 `cs_sense_features` 中 **in_clustering=1** 的特征列
  （get_clusters_with_members 返回的 features 含 A 区核验列，不能直接进矩阵）。
- value_type 来自范畴包：`src/category_pack.load_pack("motion")` 读
  `configs/motion/features.yaml`（binary/nominal/ordinal 决定 Gower 分支）。
  包加载失败时降级：未知特征按 nominal 处理并记录 warning（页面不崩）。
- **category 参数解析**：接受范畴包目录名（`motion`，与页面选择器一致）或
  范畴深挖 categories.code（`RUN`）。包名→研究代号的对应关系由模块级常量
  `PACK_TO_STUDY_CODE = {"motion": "RUN"}` 声明（d1 试点：motion 包的研究
  登记名是 RUN 跑范畴）；code 直接匹配大小写不敏感。
- 测试/换包场景可显式传 `value_types`/`ranges` 覆盖包元数据（CLUSRUN 种子
  范畴即用此通道，不依赖 configs）。

## 4. Streamlit 页面

```python
render_cluster_analysis_page()   # 集成步骤在 app.py 页面分派中挂载即可
```

- 顶部：标题 + 说明 caption；范畴选择器（`category_pack.CATEGORIES()`，
  默认 motion）+ 语言选择器（英语/汉语）。
- **Tab1 🌳 谱系树**：`plotly.figure_factory.create_dendrogram`（Gower 方阵
  经 distfun=squareform、linkagefun=average 注入；plotly 要求二维 ndarray，
  已转换）+ 红色虚线 **k=5 探索性切分参考线**（add_hline 于 cut_height，
  附注释文案），caption 明确「k=5 只是探索性解，不是唯一正确答案」。
- **Tab2 🏆 典型性排序**：每簇一个 expander（簇号+短名+成员数+金色
  **medoid 徽章**，默认前 6 簇展开）→ 成员**距离条形图**（plotly 横条，
  tier 三色、距离最小者在顶部、数值标注 .3f）→ tier 徽章图例（原型/次典型/
  边缘 + 计数）。
- 样式沿用 `src/design_system`（HEADER_H1/H3、SUCCESS/INFO 色 = tier 三色、
  WARNING 金色 = medoid 徽章）；所有 DB 文本（词目、义项号、义位标签、簇名）
  进 `unsafe_allow_html` 前过 `_html_escape`。
- 数据经 `st.cache_data(ttl=600)` 页面级缓存；无数据渲染 st.info 引导灌库；
  scipy 缺失渲染 st.warning 且典型性排序不受影响。

## 5. 测试（tests/test_cluster_analysis.py，39 个）

| 组 | 数量 | 要点 |
|---|---|---|
| TestGowerDistance / TestGowerMatrix | 8 | binary/nominal 记 1、ordinal 归一差值、混合均值 0.5、缺失列跳过、矩阵对称 |
| TestMedoidIndex | 3 | **合成向量已知 medoid**：三条相同向量 + 1/3 与 2.5/3 干扰项，medoid=aa，平均距离 7/24、0.375、0.75 精确断言 |
| TestAssignTiers | 9 | n=9 精确三等分、n=7（3/1/3）、n=2（无次典型）、n=1、自定义份额、平局按序稳定 |
| TestDendrogramHelpers | 7 | 2 点 1 次合并、n-1 行、末次合并 count=n、单调、k 切分高度下方恰 n-k 次合并、k=1/k 出界边界、verb-Sn 标签 |
| TestFeatureTypesFromPack | 2 | motion 包 15 列 value_type/值域、A 区排除、缺包降级 |
| TestMedoidRankingDB（skipif） | 5 | 种子范畴 CLUSRUN 端到端：medoid 精确值与 tier 序、份额传播、语言过滤/单成员簇、显式 run_id 与跨语言回退、输出契约 |
| TestDendrogramDB（skipif） | 3 | n-1 合并 + labels/k/cut_height 一致性 + 方阵重算 linkage 相等、单成员空树、未知范畴空结果 |
| TestPage | 2 | 无数据降级提示（monkeypatch，不需 DB）；真实 RUN 数据 AppTest 冒烟（5 簇 expander 在场） |

结果：**39 passed**；全仓 `python3 -m pytest -q` **511 passed, 0 failed**
（本次开发前基线 443，期间并行交付的 template_engine 增加 29 个，均未回归）。
新文件 `flake8` 干净（max-line-length=100）。

## 6. 边界与说明（集成/论文引用注意）

1. **k=5 是探索性切分**：谱系树支持任意高度切割，参考线仅标注 d1 试点的
   k=5（来自 cs_cluster_runs.params.k，非硬编码）；页面文案已注明。
2. **平局语义**：medoid 平局取成员装载序（lemma/sense_no）最前者；tier 平局按距离排名的稳定序
   ——与「人看特征画像判读」相比是可复现的程序化判定，论文 §5.2 可直接引用。
3. **无特征编码的成员**：Gower 距离对无共同特征的向量对记 0（实际编码矩阵
   51 义位 15 列齐全，不会触发；CSL 剔除义位本来就不在簇成员里）。
4. **zh 义项号**：现汉条目 sense_no 常为 `—`，标签形如 `奔窜-S—`，属数据
   原貌；簇 4 的 17 个英义位等大簇在树图上横向铺开，plotly 交互可缩放。
5. **依赖**：scipy 已加入 requirements.txt（>=1.10）；plotly/pandas 复用
   既有依赖。scipy 缺失时模块可导入，仅谱系树功能降级（HAS_SCIPY 标志）。
6. **中文与代码纪律**：引擎层不含具体词类名词（特征码/value_type 全部来自
   范畴包），唯一词类相关物是 `PACK_TO_STUDY_CODE` 映射常量（包名→研究登记名，
   属配置性质，已注释）。
