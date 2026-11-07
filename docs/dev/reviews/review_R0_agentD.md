# R0 Review · Agent D：范畴包（Category Pack）机制改动清单

> 依据唯一事实源 `docs/spec/多人标注系统设计规范.md`（§3 src/category_pack.py 契约、§4、验收 V5/V6）
> 与 `docs/spec/跨词类通用框架.md`（§1 目录结构、§2 六文件规范、§3 言说动词验证帧）实现。
> 状态：完成。`tests/test_category_pack.py` **29 通过**；全量 `pytest -q` **380 通过、无回归**。
> motion 与 speech 两个范畴包均过 selfcheck；`configs/_template/` 供新词类四步接入（框架文档 §5）。

## 1. 新增文件

### `src/category_pack.py` —— 范畴包加载与自检引擎（规范 §3 契约，签名一致）

- `CATEGORIES() -> tuple`：扫描 `configs/` 下含 `pack.yaml` 的目录，跳过 `_`/`.` 开头内部目录
  （`_template` 不外露）。返回排序 tuple；`src/reliability.py` 的 `_list_categories()` 主路径
  直接消费该函数（调用点契约已对齐）。
- `load_pack(category) -> dict`：返回 `{admission, features, schemas, corpus_map, prompts, pack}`
  六键；`prompts = {"screening": <screening.txt 全文>}`。加载即自检，失败抛
  `CategoryPackError`，`str(exc)` 为「- 」起头、换行拼接的问题清单（含问题总数）。
- `run_selfcheck(category) -> (bool, list[str])`：**纯 Python 校验，不引 jsonschema**（规范 §4）。
  实现自检六条：
  1. 六文件齐全且 `yaml.safe_load` 可解析（顶层必须是映射；screening.txt 可读且非空）；
  2. `admission_classes` 非空、每项有非空 code 且 code 互斥（重复即报，列出重复码）；
  3. `features` 非空；`in_clustering=true` ≥5 项；每个特征 `value_type ∈ {binary, nominal,
     ordinal}`；每个 in_clustering 特征有非空 code 且唯一（重复即报）；
  4. `schemas` 非空、`annotation.mode` 已定义、每个 `evidence_slot` ∈ `corpus_map.slots`
     的 code 集合（坏槽位名原样进问题清单，验收 V5 反向用例依赖此点）；
  5. `prompts/screening.txt` 存在且含全部 9 个占位符：`{category_name}`、
     `{operational_definition}`、`{admission_classes}`、`{verbal_heuristic}`、`{boundary_rules}`、
     `{schema_names}`、`{sense_id}`、`{definition}`、`{examples}`；
  6. 每个特征的 `group` 必须在 `features.yaml` 的 `groups` 定义里（与 admission 无关，⑥ 检查）。
- 辅助：`PACK_FILES`（五个 YAML 文件名）、`SCREENING_RELPATH`、`REQUIRED_PLACEHOLDERS`、
  `VALUE_TYPES`、`MIN_CLUSTERING_FEATURES=5` 均为模块常量；`_REPO_ROOT` 为模块级变量，
  测试用 monkeypatch 指向 tmp_path 构造坏包。yaml 只用 `safe_load`（§6-6）。
- 引擎-配置边界（框架文档 §4 纪律）：模块内零具体词类名词（无四图式名、无 P5/速度、
  无提示词口诀），有测试守护（见下）。

### `configs/motion/` —— 范畴包①：移动动词（已验证真值，框架文档 §2 逐文件实例化）

- `pack.yaml`：display_name 英语移动动词；`lemma_pool {candidates: 216, admitted_lemmas: 171}`；
  `sense_counts {total: 996, oald: 992, supplemented: 4}`；`pilot {en: {senses: 32},
  zh: {items: 25}}`；selfcheck 六条清单原文。
- `admission.yaml`：操作性定义 + Y/EXT/N 三分（核心物理位移义/隐喻拓展义/剔除义）+
  边界条款 BR1-3 + 候选链 `mechanical_screening {10 正 17 负, kept: 358, of: 992}`、
  `explicit_rules {R0: 344, R1_removed: 6, R2_kept: 5, R3_review: 3, net: 352}`。
- `features.yaml`：分组 P(路径)/M(方式)/C(动因)/A(核验)；**P1-P5 / M1a-M1d / M2 / M3a-M3d /
  C1 共 15 项 in_clustering=true + A1-A3 三项 false**；P5/M2 为 ordinal（速度/情态急促度，
  值域 0/1/2）、C1 为 nominal（动因三分）、其余 13 项 binary；每项带 `values` 值域；
  `clustering {algorithm: gower_upgma, feature_scope: in_clustering}`。
- `schemas.yaml`：四图式封闭清单 MANNER_ACCOMP（方式伴随，6 槽位）/ SOURCE_DETACH（源点
  脱离，5 槽位）/ GOAL_ARRIVE（终点抵达，4 槽位）/ INTERACT_MOVE（互动位移，4 槽位），
  各带 definition + classic_examples + evidence_slots；`annotation {mode: forced_choice,
  secondary_schema: record}`；域归并三域：方式位移域 / 路径位移域（SOURCE_DETACH+
  GOAL_ARRIVE）/ 互动位移域。
- `corpus_map.yaml`：enTenTen21 + sketch_engine_wordsketch；**18 个槽位**的
  `sketch_gramrel` 映射（subjects/objects/modifiers/…/particles_with_obj）；
  `scoring {function: mean_logdice_log2n, top_k: 50}`；`noise_filter {remove: [抽象概念名词,
  隐喻投射名词, 量化时间状态名词], keep: [能指代或编码事件要素的词项]}`。
- `prompts/screening.txt`：九占位符齐全 + 判定口诀原文「有没有真实物体，在物理空间里从
  一个地方移动到另一个地方？有→Y；抽象隐喻→拓展；不动／只是改变自身属性→N」。

### `configs/speech/` —— 范畴包②：言说动词最小验证帧（框架文档 §3，虚构数据）

证明同一结构装得下不同词类：六件套同构、引擎零修改即通过 selfcheck。

- `admission.yaml`：简版三分（核心言说义/隐喻拓展义/剔除义）+ 一条 BR1；
- `features.yaml`：I(互动结构)/S(符号行为)/R(传信方式)/A(核验) 四组；**7 项特征——6 项
  in_clustering=true**（I1/I2/I3 binary、S1 声道 nominal `{oral, written, sign}`、R1 信息取向
  ordinal、R2 正式度 ordinal）、**A 组 1 项 in_clustering=false**（构式论元-直接引语）；
- `schemas.yaml`：三图式 ASSERT/DIRECTIVE/EXPRESSIVE（各带 evidence_slots）+ forced_choice
  + 三域归并（命题传信域/指令调节域/情感表达域）；
- `corpus_map.yaml`：**8 个槽位**（ subjects/objects/pronominal_objects/modifiers/
  and_or_conj/usage_patterns/complements/pp_about_of）+ 同款 scoring/noise_filter；
- `pack.yaml`（演示值并注明非已验证真值）与 `prompts/screening.txt`（九占位符 + 言说口诀）。
- 「四图式换三图式、六槽位换八槽位，引擎读到的都是同一套键名」有测试断言守护。

### `configs/_template/` —— 空模板（新词类接入第一步 `cp -r` 的底版）

- 六件套字段齐全、值留占位（`请填写…` / `TEMPLATE_CATEGORY` / `SLOT_N` / `SCHEMA_N`）；
- 模板本身即可解析、占位符齐全，但 `pack.yaml.category` 与目录名不一致 → 被 `CATEGORIES()`
  排除且 selfcheck 不通过（复制后改 category 即恢复）；有测试守护两行为。

### `tests/test_category_pack.py` —— 29 项（验收 V5 正反向全覆盖）

- **motion 正向**：selfcheck/load_pack 通过；已验证真值逐一抽查（216/171、996=992+4、
  试点英 32 义位汉 25 条目、10正17负 992→358、344-6+5+3→352、BR1-3）；特征 15+3 与
  value_type 分布（P5/M2 ordinal、C1 nominal、其余 binary）；四图式与三域归并；18 槽位 +
  scoring + noise_filter；口诀原文；图式槽位 ⊆ 槽位枚举。
- **speech 正向**：selfcheck/load_pack 通过；features ≥6、ordinal+nominal+binary 齐备、
  A 组一项 false、每项带 values；三图式八槽位；与 motion 的键名结构同构断言。
- **反向（tmp_path 复制 motion + monkeypatch `_REPO_ROOT`）**：evidence_slot 改成
  `objects_bogus` → `CategoryPackError` 且信息含槽位名（验收 V5 原文用例）；删文件、
  坏 YAML、准入 code 重复、in_clustering 不足 5、value_type 非法、group 未定义、
  占位符缺失、screening.txt 缺失、未知 category → 各自触发对应问题清单。
- **契约守护**：`CATEGORIES()` 含 motion/speech 且 `_template` 被排除；`run_selfcheck`
  返回 `(bool, list[str])`；`REQUIRED_PLACEHOLDERS` 与规范九占位符一致；引擎源码无具体
  词类名词；yaml 仅 `safe_load`（无 `yaml.load(`/`unsafe_load`/`import jsonschema`）。

## 2. 修改文件（1 处，测试前提修正）

- `tests/test_reliability.py::test_list_categories_fallback`：该测试原假设「category_pack
  不存在」，import 失败走 `_list_categories()` 的回退分支。Agent D 交付 `src/category_pack.py`
  后主路径恒可用，导致全量回归中该测试失败（`('motion', 'speech') != ('motion',)`）。
  修正方式：向 `sys.modules` 注入 `"src.category_pack": None` 强制 ImportError，
  **显式模拟原测试前提**，保留 Agent C 的回退分支覆盖意图。`src/reliability.py` 本体
  一字未动（约束遵守）。这是测试与模块交付顺序造成的必然后果，非功能缺陷。

## 3. 未改动（按约束）

- `src/app.py`、`src/category_study.py`、`src/llm_api.py`：三处硬编码（FEATURE_COLUMNS、
  四图式名、提示词口诀）的迁移属后续集成步骤（框架文档 §6），本次只交付配置侧与引擎侧
  读取能力，未触碰页面/API。
- `src/users_db.py`、`src/reliability.py`、`src/annotation_flow.py`（其他 agent 产物）。
- `requirements.txt` 未改（PyYAML 已随 streamlit 可用，本模块零新增依赖）。

## 4. 验证记录

| 项 | 结果 |
|---|---|
| `python3 -m pytest tests/test_category_pack.py -q` | **29 passed** |
| 全量 `python3 -m pytest -q`（回归） | **380 passed**，无失败无回归 |
| 15 个 pack YAML 全部 `yaml.safe_load` 解析通过 | 是（含 `_template`） |
| motion / speech `run_selfcheck` | 均 `(True, [])` |
| 坏 evidence_slot → `CategoryPackError` 含槽位名 | 是（验收 V5） |
| `CATEGORIES()` | `('motion', 'speech')`，`_template` 排除 |
| 约束文件（app/category_study/llm_api/users_db/reliability/annotation_flow）改动 | 无 |

## 5. 新词类接入四步（框架文档 §5，供后续使用）

```
cp -r configs/_template configs/<new_category>
填六件套（准入标准最重，特征含 value_type，槽位与图式对齐）
灌义位（cs_* 表 category 字段隔离）
引擎加载时 run_selfcheck 全过才开放该范畴页面
```
