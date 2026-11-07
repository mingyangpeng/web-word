# R2 Review · 数据正确性审查（多人标注系统）

> 审查范围：`src/reliability.py`、`src/annotation_flow.py`、`src/users_db.py`（仅数据层）、`src/category_pack.py`；
> 表 DDL 对照 `docs/spec/多人标注系统设计规范.md` §2。前置报告 `review_R0_agentB/C.md`、`review_R1.md` 已通读（不重复报）。
> 方法：**不看实现**，用独立编写的 Krippendorff's α 参照实现（`Fraction` 精确有理数算术，直接从
> units 出发、不经被审代码的矩阵数值化）逐公式重算对照；另用真实 MySQL 8.0.46 独立测试库
> （`web_word_flow_test`，跑完 DROP）做 22 项 live 探针覆盖 upsert / 分歧边界 / JSON 往返 / 落库读回。
>
> **结论：发现 4 处问题，修复 4 处（F1/F2/F3/F4，见 §3）。α 计算公式本体经 200 组随机差分 +
> 9 组精确锚点验证无误（最大偏差 4.2e-16）。`python3 -m pytest -q` 402 全绿（原 394 + 新增 8）。**

## 1. α 计算独立复核（清单 1，最重要）

### 1.1 参照实现（review 侧，非仓库代码）

按 Krippendorff (2011) 一般公式直接实现，与被审实现刻意不同构以避免同源错误：

* 可配对值 = 位于 `n_u ≥ 2` 单元内的取值，缺失（None / NaN / 脏值）跳过；
* 巧合矩阵 `o_ck = Σ_u [c≠k: m_c·m_k/(n_u−1)；c==k: m_c(m_c−1)/(n_u−1)]`；
* `α = 1 − (n−1)·Σ_{c≠k} o_ck δ_ck / Σ_{c≠k} n_c n_k δ_ck`（n = 可配对值总数）；
* nominal：`δ` 0/1（按原始标签相等性，不做数值化）；ordinal：先排秩，
  `δ²_ik = (Σ_{g=i..k} n_g − (n_i+n_k)/2)²`（秩次 + 巧合边际，与库 0.9.0 `_ordinal_metric` 同一定义）；
* 全程 `Fraction` 精确算术 → 转 float 即为真值参照，杜绝浮点求和顺序差异。

### 1.2 对照表（期望 = 独立参照/解析解；实测 = compute_alpha 库路径 / 纯 Python 回退路径）

| # | case | 期望 | 实测（lib / pure） | 结论 |
|---|---|---|---|---|
| 1 | ①完全一致：nominal 4人×6单元 | 1.0 | 1.0 / 1.0 | 一致 |
| 2 | ①完全一致：ordinal 2人×5单元 | 1.0 | 1.0 / 1.0 | 一致 |
| 3 | ②完全不一致：2人×4单元全 (a,b)（解析解 α=1/N−1） | −3/4 = −0.75 | −0.75 / −0.75 | 一致 |
| 4 | ②三类轮转 (1,2)(2,3)(3,1) | −1/4 = −0.25 | −0.25 / −0.25 | 一致 |
| 5 | ②单对不一致（N=1） | 0.0 | 0.0 / 0.0 | 一致 |
| 6 | ③经典数据 nominal（Krippendorff 2011 p.8 / 库 doctest） | **56/81** ≈ 0.691358 | 0.691358024691358（两者同） | 一致，与发布值吻合 |
| 7 | ③经典数据 ordinal（同上） | **108577/133160** ≈ 0.815388 | 0.8153875037548814（两者同） | 一致（发布值 0.815） |
| 8 | ③手推 A：2人×4单元 (a,a)(a,b)(b,a)(b,b) | 1/8 = 0.125 | 0.125 / 0.125 | 一致 |
| 9 | ③手推 B nominal：2人×9单元 | 10/27 ≈ 0.370370 | 0.3703703703703704 / 0.37037037037037035 | 一致 |
| 10 | ③手推 B ordinal | 37/54 ≈ 0.685185 | 0.6851851851851851（两者同） | 一致 |
| 11 | ⑥四人：4人×3单元 | 1/12 ≈ 0.0833333 | 0.08333333333333337 / 0.08333333333333337 | 一致（见 §1.3 注） |
| 12 | ⑥两人：2人×3单元（上者子集） | 4/9 ≈ 0.444444 | 0.4444444444444444（两者同） | 一致 |
| 13 | ⑥多人 ordinal：4人×4单元三类 | 独立参照 0.24978956228956228 | 0.24978956228956228 / 0.24978956228956217 | 一致 |
| 14 | ④带缺失：随机挖 30% 格子，固定种子 **200 组**差分（2-5人×3-12单元、nominal/ordinal/binary 混合） | 独立参照逐组 | max\|lib−ref\| = **4.16e-16**，max\|pure−ref\| = **3.33e-16** | 全部 < 1e-9 ✓ |
| 15 | ④经典数据再挖 30% 缺失 | 0.6231884057971014 | 同值（两者同） | 一致 |
| 16 | ⑤ordinal 等距 {0,1,2} vs 不等距 {0,10,1000}（同秩结构） | α 必须相同（秩次语义，非间距） | 0.3125 / 0.3125，逐位同 | 一致 → **ordinal 真用秩次距离**，非 nominal、也非 interval |
| 17 | ⑤相邻秩分歧：ordinal 应显著高于 nominal | ordinal > nominal + 0.05 | 0.61875 vs 0.28571 | 一致 |
| 18 | 脏值：字符串 `"nan"` 混入 | 两路径一致且按缺失 | **修复前 lib=1.0 / pure=0.625 分叉**；修复后 1.0 / 1.0 | **F1（bug，已修）** |
| 19 | 脏值：超大 int（float 溢出） | 不崩溃、路径一致 | **修复前 OverflowError 崩溃**；修复后 1/6（两路径同） | **F3（bug，已修）** |
| 20 | 脏值：字符串 `"inf"`、dict 脏值、float NaN | 两路径一致 | 均一致（"inf" 作类别两路径同；dict/NaN 按缺失） | 通过 |

**误差说明**：任务要求 <1e-6；实测全部 ≤ 4.2e-16（浮点求和顺序差异的量级），1e-9 容差可达并已作为回归断言写入套件（`tests/test_reliability.py::TestR2IndependentVerification`，把 #3–#12、#15–#19 的精确分数值固化为锚点，容差 1e-9，此前套件为 0.01）。

### 1.3 复核中的两点说明

* **#11 的期望值更正**：首轮手算得 3/14，与实现不符；逐项重推发现手算把对角巧合项写成
  `m_c²/(n_u−1)`，正确为 `m_c(m_c−1)/(n_u−1)`，正确值 1/12 —— Fraction 参照与两路实现一致。
  这正体现独立精确参照的价值：分歧时先怀疑手算，实现以标准定义为准。
* **ordinal 的输入解释约定**（非 bug，文档已注明）：非数值标签按字典序排秩（features.yaml 的
  ordinal 特征均为数值编码，实际不走到）；数值标签按数值排秩，间距无关（#16 证实）。
  bool/int/数值字符串在数值化分支按 Python 值相等统一（`True`≡`1`≡`1.0`），属文档化的
  「可 float → 原值」约定，两路径行为一致。

## 2. 清单 2–6 逐条结论

### 2.1 run_reliability 聚合逻辑 —— 通过（含一处口径确认）

* **feature_coding 的特征口径**：指标清单 = 实际提交 payload `features` 键的**并集**，**不按**
  `in_clustering` 过滤。核对 `configs/motion/features.yaml`（15 项 in_clustering=true + 3 项核验区
  A1-A3=false）与两份设计文档后确认这是规范行为：`in_clustering`/`clustering.feature_scope` 是
  Gower 聚类的列范围（跨词类通用框架.md features.yaml 的 clustering 节），设计规范 §3 对信度的
  要求原文是「feature_coding 对**每特征**按其 value_type 算」，且核验区特征的 IAA 对 reviewer
  同样有意义。已在 `run_reliability` 处补口径注释（本轮唯一文档性改动）。live 探针 5e 实测：
  只有 A1 时正常按 binary→nominal 计算 α=0.0 并落库。
* **value_type 读取来源正确**：页面层 `render_reliability_page` → `run_reliability(category, task)`
  （features_meta=None）→ `_load_features_meta` 读 `configs/{category}/features.yaml`（缺文件 → []，
  全部默认 nominal）→ `_resolve_value_type` 按 code/feature/name/id 四键匹配（binary→nominal、
  ordinal→ordinal、未登记→nominal）。live 探针 5a 实测读到 18 特征、P5=ordinal；5b/5c 实测
  P5 用 ordinal 分支（0.833333）且 ≠ nominal（0.400000），与独立参照一致（per_feature 按
  `round(α, 6)` 圆整存储展示，文档化行为）。
* **admission overall=三字段均值**：合理且标注充分 —— 页面/CSV 均给出 per_field 明细
  （{"admission","schema","alignment"}）与各自达标判定，overall 只是汇总口径，docstring 已注明
  「不可算的跳过；全不可算为 None」。
* **空提交集 / 单编码人**：空集 → `n_coders=0`、per_feature 三键全 None、overall=None、**不落库**
  （既有测试 test_no_submissions）；单人 → α=None 仍落库留痕（test_single_coder_still_writes_run，
  DECIMAL 列 NULL）；数据库不可用 → 带 `db_error` 的结果不抛异常。**无假 0 返回路径**。

### 2.2 upsert 语义（submit_annotation）—— 通过

* **payload 全量替换**：`INSERT ... ON DUPLICATE KEY UPDATE payload = VALUES(payload) ...`，
  live 探针 1a：先提交 `{admission, schema, cn_syntax, strategy}` 再提交 `{admission:"N"}`，
  读回 payload 恰为 `{"admission": "N"}` —— 旧键**无合并残留**。
* **submitted_at 刷新**：探针 1c 实测 `01:57:43 → 01:57:44`（UPSERT 内 `submitted_at = CURRENT_TIMESTAMP`）。
* **status 重置**：探针 1d/2b + 既有集成测试（test_adjudication_flips_status_and_overwrites）实测：
  已 adjudicated 的条目被再次提交 → **该行重置回 'submitted'**（重新进审核流，符合任务建议），
  同 sense 其他 coder 的 adjudicated 状态不受影响，且既有仲裁 gold 行不被清除（留痕完整，探针 2c）。
  upsert 行 id 不变（UNIQUE 键命中，探针 1b）。

### 2.3 detect_disagreements 边界 —— 通过

* **payload 字段缺失（老版本提交）**：全部经 `payload.get(field)` / `isinstance(features, dict)` 守卫，
  live 探针 4b 实测老 payload 只含 `admission` 一键 → 无 KeyError、无假分歧。
* **bool 与字符串 'true' 混存**：`_normalize_for_compare` bool → `'true'/'false'`，探针 4a 实测
  coder A 提交 `needs_review: true`、coder B 提交 `needs_review: "true"` → 判一致（不报分歧）；
  TINYINT 0/1 混写亦兼容（既有测试）。
* **features 子字典键集不一致（A 18 项 vs B 15 项）**：实现取**并集**逐特征比对、某特征仅单方
  有值按缺失容忍跳过 —— 等价于「只有双方共有的键才可能产生分歧」，不报结构分歧（设计取舍：
  键集差异本身不是标注分歧，缺键 = 未标注）。docstring 已有明确说明（「某字段只在部分 payload
  里出现时：有值的 coder 参与比对（缺失容忍）」）。探针 4c 实测 18 vs 15 → 无异常无假分歧；
  4d 实测共有键 P5 有分歧时正确报出。
* **坏 payload**：`_parse_payload` 失败/非 dict → `{}` 按缺失剔除（探针 4e 用 `[1,2]` 实测不抛）；
  另证实**非法 JSON 文本根本进不了库**（MySQL JSON 列写入时即拒绝，errno 3140）。

### 2.4 JSON 往返（真实 MySQL 8.0.46）—— 通过

* 类型稳定：`needs_review: true` 往返后仍为 `bool`（不变 `1`/`'true'`）；`extra_int: 3` 仍为 `int`；
  float 2.5 保持数值（探针 3a–3c）。
* utf8mb4 中文无损：`中文句法：施事+路径`、`策略②`、引号/反斜杠/emoji（`🏃`）逐字符一致
  （探针 3d；连接 charset=utf8mb4 + `json.dumps(ensure_ascii=False)`）。
* `reliability_runs` 落库读回：per_feature JSON 往返、overall DECIMAL(5,3) NULL 语义正确（探针 6a）。

### 2.5 category_pack —— 通过

* **重复加载**：`load_pack` **无缓存**，每次重新读盘并重新 selfcheck；返回对象相互独立 ——
  探针实测：改动返回 dict 后再次 load 仍得完整 18 特征，selfcheck 依旧通过。无缓存意味着无
  陈旧缓存/共享可变状态副作用（代价是重复磁盘 I/O，对配置体量可忽略，且换来配置热更新友好）。
* **CATEGORIES() 容错**：configs 目录不存在 → 返回 `()`（isdir 守卫，不抛）；目录存在但为空 →
  `()`；`_`/`.` 开头目录排除。`reliability._list_categories` 在 CATEGORIES() 为空/ImportError 时
  逐级回退（自扫 configs/ → 兜底 `("motion",)`），已有测试覆盖回退分支。

### 2.6 users_db（数据层）—— 通过（无新发现）

`verify_login`/`hash_password`/`create_user`/`set_role`/`set_active` 与 R1 结论一致（F1 时序侧信道
已修）。本轮经探针实测 `create_user` 建号、登录数据流无新问题；密码哈希不出数据层、日志无明文。

## 3. 发现清单（已修复）

### F1 · P1 数据正确性 · 字符串 `"nan"` 使 α 两条计算路径结果分叉 —— 已修复

* **位置**：`src/reliability.py` `_is_usable_label`（主修）；`src/annotation_flow.py`
  `_normalize_for_compare`（同口径对齐，F2 合并说明）。
* **问题**：`_is_usable_label` 放行一切字符串，而字符串 `"nan"`/`"NaN"`/`" nan "` 等可被
  `float()` 解析为 NaN。数值化后：库路径中 NaN 恰是缺失哨兵（np.nan）→ 按**缺失**；
  纯 Python 回退里 NaN 不是 None → 被**当作一个真实类别**参与巧合矩阵（且 NaN 参与排序
  顺序未定义）。实测同一份数据 lib=1.0 / pure=0.625 —— 违反「两条计算路径逐位同源」的
  模块契约，也违反本模块「脏值按缺失跳过、不做假第三类别」的自述口径。
* **修复**：`_is_usable_label` 对字符串增加守卫 —— `float()` 可解析出 NaN 的串按缺失
  （与 float NaN 同口径）。修复后探针/回归：两路径同值（1.0），且 `"nan"` 不再成为假类别。
* **F2（跨模块一致性，同源修复）**：`annotation_flow._normalize_for_compare` 此前把 float NaN
  视为缺失、却把字符串 `"nan"` 当真实标签参与分歧比对 —— 会对照 1 的修复产生两个模块对
  同一脏值的口径分叉（信度页视为缺失、仲裁分歧清单却报假分歧）。同口径补守卫：
  字符串 "nan" 一律按缺失剔除。探针 4 组 + 新增回归测试（flow 侧 1 项）验证。

### F3 · P2 数据正确性 · 超大 int 标签使 compute_alpha 崩溃（OverflowError 未接住）—— 已修复

* **位置**：`src/reliability.py` `_units_to_matrix` 数值化决策与矩阵转换两处
  `except (TypeError, ValueError)`。
* **问题**：`float(10**400)` 抛 **OverflowError**，不在捕获范围内 → 单条脏值直接炸掉整个引擎，
  违反 docstring「不让单条脏数据炸掉整个引擎」的承诺。MySQL JSON 虽会截断超大整数为
  double，但 `compute_alpha` 是公开 API，进程内直接调用可触达。
* **修复**：两处 except 增加 `OverflowError`；超大 int 自动落入「非数值 → 标签码」分支
  （`sorted({str(v)})` 双射编码，nominal 不变式保持）。回归：1/6 精确锚点（两路径同值）。

### F4 · P3 卫生 · 既有 flake8 E501 —— 已修复（本模块内）

`src/reliability.py` DDL 常量里的 per_feature 注释行 112 字符超长（既有问题，R0 交付时遗留）。
重排为两行注释，DDL 语义子串原样保留（`test_key_lines` 断言全过，真实 MySQL 建表实测正常）。
注：`tests/test_category_pack.py` 另有 3 处既有 E501（Agent D 遗留，非本轮四个被审模块的
运行代码），未动 —— 遗留观察项，不影响功能与测试。

## 4. 回归验证

| 项 | 结果 |
|---|---|
| `python3 -m pytest -q` | **402 passed**（原 394 + 新增 8：TestR2IndependentVerification 7 项 + flow nan 回归 1 项），0 failed |
| `RELIABILITY_FORCE_PURE=1 python3 -m pytest -q` | **402 passed**（强制纯 Python 回退路径全量回归） |
| `flake8`（reliability / annotation_flow / 两个测试文件） | **0 违规** |
| 独立 α 对照脚本（6 大类 20 项 + 200 组随机差分，Fraction 精确参照） | **全部通过**（修复后两路径逐组一致） |
| 真实 MySQL live 探针 22 项（upsert/仲裁/JSON 往返/分歧边界/run_reliability/落库读回） | **22/22 通过**（测试库跑完即 DROP，无残留） |

新增回归测试位置：`tests/test_reliability.py::TestR2IndependentVerification`（精确分数锚点 +
nan/超大 int 回归）、`tests/test_annotation_flow.py::TestDetectDisagreementsFeatureCoding::
test_nan_string_feature_value_treated_missing`。

## 5. 遗留与建议（不阻塞）

1. `run_reliability` 的 `per_feature`/`overall` 以 6 位小数圆整返回/落库（overall 落库再截到
   DECIMAL(5,3)）—— 文档化行为，展示无碍；若未来要做二次统计，建议消费方读原始 α 计算
   路径而非 reliablity_runs 的圆整值。
2. reliability 侧分歧条目（`disagreements`）与 flow 侧 `detect_disagreements` 的取值归一口径
   现已对齐（bool → 'true'/'false'、"nan" → 缺失）；但 reliability 侧仍用 `str(v)` 粗归一，
   True vs 1 会报分歧而 flow 判一致（bool 0/1 特征若混用 int/bool 才可触达，当前 UI 提交
   全 int，不可达）。后续如统一两侧分歧实现，可复用 `_normalize_for_compare`。
3. `tests/test_category_pack.py` 3 处既有 E501（见 F4 注），建议下轮顺手清理。
