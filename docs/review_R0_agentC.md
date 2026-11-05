# R0 Review · Agent C：Krippendorff's α 信度引擎改动清单

> 依据唯一事实源 `docs/p1/多人标注系统设计规范.md` 实现（§2 reliability_runs DDL、§3 模块契约、§6 安全规则、验收 V4/V6）。
> 状态：完成。`tests/test_reliability.py` **45 通过**（合成数据已知 α 验证，库路径与纯 Python 回退路径双验）；全量 `pytest -q` **280 通过、无回归**；真实 MySQL 8.0.46 上 DDL/写入/读回集成冒烟通过。

## 1. 新增文件

### `src/reliability.py` —— 信度引擎（计算 + 落库 + 页面）

**双计算路径（任务要求 1，两条都在）：**

1. **主路径**：`krippendorff` 库 0.9.0（已 `pip install` 并写入 requirements.txt 末尾）——`krippendorff.alpha(reliability_data=矩阵, level_of_measurement='nominal'|'ordinal')`，矩阵形状 (M 编码人, N 义位单元)，缺失值 `np.nan`，取值全部转 float（字符串标签按排序去重映射成码，nominal 对双射编码不变式，ordinal 非数值标签按字典序——features.yaml 的 ordinal 特征均为数值编码，实际不走到）。
2. **纯 Python 回退** `_alpha_pure`：实现 Krippendorff (2011) 巧合矩阵公式（与库逐项同源：`o_ck` 按 1/(n_u−1) 计入、`D_o=(1/n)Σ o·δ`、`D_e=(1/(n(n−1)))Σ n_c n_k δ`；δ nominal=0/1，ordinal=`(Σ_{g=i..k} n_g − (n_i+n_k)/2)²`）。nominal/ordinal 两分支、缺失值跳过（n_u<2 的单元整单元跳过）。库缺失（ImportError）或库计算异常时自动启用；环境变量 `RELIABILITY_FORCE_PURE=1` 可强制（测试双路径用）。

**规范 §3 契约函数（签名一致）：**

- `compute_alpha(units, value_type) -> float | None`：units = `{unit_id: {coder_id: value}}`，缺失 = 某 coder 无该 unit（键缺/None/NaN/结构化脏值均按缺失跳过，脏值不变成假类别）。返回 None 的情形：总观测 < 2、无任何单元被 ≥2 人标过（含单人数据，验收⑤）、units 为空。完全一致（可配对单元上只有一个去重值）返回 1.0（验收①）——注意按**可配对单元**判重，只出现在单人单元的取值不参与，否则库会在 (e·d)=0 时给出 nan。value_type：`ordinal` 走 ordinal 分支；`nominal`/`binary`/未知默认 nominal（验收③：同数据 ordinal ≠ nominal）。
- `run_reliability(category, task_type, features_meta=None) -> dict`：`features_meta` 传 None 时自动读 `configs/{category}/features.yaml`（不存在 → []，全部特征默认 nominal）。流程：直连 MySQL 读 `annotation_submissions` 全部 `status='submitted'`（SQL 全参数化，参照 `mysql_db.get_db_cursor` 模式）→ 按 payload 聚合成 units → 逐指标算 α：
  - **admission**：对 payload 的 `admission`/`schema`/`alignment` 三字段各算 nominal α，overall = 三字段均值；
  - **feature_coding**：对 payload["features"] 每特征按 features_meta 的 value_type 算（`binary`→nominal、`ordinal`→ordinal），overall = 各特征 α 均值（不可算的跳过）；
  - **alignment**（DDL 枚举里的独立 task_type）：比对 payload 的 `alignment` 字段。
  - 结果写入 `reliability_runs`（DDL 规范 §2 原样，幂等 `CREATE TABLE IF NOT EXISTS`；overall 圆整到 DECIMAL(5,3)，per_feature/disagreements JSON dumps），返回 `{overall_alpha, per_feature, n_coders, n_units, disagreements, ...}`。无提交时空跑不落库；DB 不可用返回带 `db_error` 的结果不抛异常。
- `render_reliability_page() -> None`：📐 信度报告页。**role gate 在函数入口**（§6-4，读 `st.session_state["user"]`，仅 reviewer/admin）。功能：category/task_type 选择器 → overall α 大数字卡（≥0.7 达标/未达标判定 + 编码人数/单元数）→ 每特征 α 条形图（plotly，<0.7 红色高亮 + 0.7 达标虚线；无 plotly 退 `st.bar_chart`）→ 低信度特征 warning 高亮 → 分歧条目表（长表）→ CSV 导出（`st.download_button`，utf-8-sig，含汇总 + 逐特征 + 分歧三节）。**口径标注常量 `IAA_CAPTION = "AI-assisted IAA（全员可见 AI 草稿口径）"`** 徽章常显（用户决策③）。样式沿用 app.py 模式：`from src.design_system import HEADER_H1/H2/H3, get_card_style`（import 失败时内联等价值）；payload 派生字符串进 HTML 前过 `html.escape`（§6-3）。

**辅助**：`RELIABILITY_RUNS_DDL`（规范 §2 原样）、`_load_features_meta`（PyYAML 读 features.yaml）、`_resolve_value_type`（按 code/feature/name/id 匹配，未登记默认 nominal）、`_parse_payload`（PyMySQL JSON 列 str/dict 双兼容）、`_fetch_submissions`/`_ensure_reliability_table`/`_persist_run`（全部参数化 SQL）。

### `tests/test_reliability.py` —— 合成数据验证（45 项）

- **验收 V4 核心（已知 α 手算核对，误差 < 0.01）**，每项都在库路径与回退路径（monkeypatch `KRIPPENDORFF_AVAILABLE=False`）各跑一遍：
  - ① 完全一致 → 1.0（nominal/ordinal）；
  - ② 手推算例 A：2 人 × 4 单元 (a,a),(a,b),(b,a),(b,b) → **0.125**；手推算例 B：2 人 × 9 单元（分歧全在相邻秩）→ nominal **0.3704** / ordinal **0.6852**（巧合矩阵逐步计算，注释里给出 o/n_v/δ 全过程）；经典可查表数据（Krippendorff 原文 p.8，即 krippendorff 库 doctest 引用例）→ nominal **0.691358**、ordinal **0.815**；
  - ③ 同一批数据 ordinal(0.6852) ≠ nominal(0.3704)；相邻秩分歧时 ordinal 显著更高；`binary` 与 `nominal` 结果一致（映射正确）；
  - ④ 缺失值容忍：coder 缺一半单元不报错且两路径同值；含大量缺失的可查表数据仍回已知 α；None/NaN/结构化脏值按缺失跳过（手算 0.4444）；
  - ⑤ 单人数据、两人无重叠单元、空 units、全 None → None；仅一个重叠单元完全一致 → 1.0；未知 value_type 不抛异常按 nominal。
  - 两路径一致性断言：同一含缺失数据上 `lib == pure`（abs 1e-9）。
- **run_reliability 数据库路径**（`test_schema.py` 同款「按 SQL 文本分派」假游标，无 MySQL 也全绿）：admission 三字段 α（0.5333/1.0/1.0，overall 0.844）+ INSERT 参数捕获 + DDL 执行断言 + `status='submitted'` 过滤断言 + 分歧条目（sense 104）；feature_coding 按 features_meta 分支（P1 binary→0.4444、P5 ordinal→0.7778，≠ nominal 会得到的 0.5455）、meta 缺失默认 nominal、meta=None 自动读 configs/{cat}/features.yaml（tmp_path 生成 yaml）；payload JSON 字符串兼容；单人提交 α=None 仍落库留痕；空提交不落库；DB 不可用返回 db_error 不抛；未知 task_type 抛 ValueError。
- **辅助纯函数**：DDL 关键行抽查（DECIMAL(5,3)/JSON/computed_at/InnoDB）、`_export_csv` 三节内容、`_list_categories` 回退、`_parse_payload` 各形态、`IAA_CAPTION` 常量。

## 2. 修改文件

- `requirements.txt`：**末尾**新增 `krippendorff>=0.9.0`（附注释说明回退实现）。`PyYAML` 及其余条目未动。

## 3. 未改动（按约束）

- `src/app.py`（页面集成留待规范 §5 最终集成步骤：侧边栏入口「📐 信度报告（reviewer/admin）」）、`src/users_db.py`、`src/annotation_flow.py`（未创建/未触碰；读 annotation_submissions 直接 SQL，DDL 已冻结）、`src/mysql_db.py`。

## 4. 验证记录

| 项 | 结果 |
|---|---|
| `pip install krippendorff` | krippendorff 0.9.0 安装成功（numpy 1.26.4 共存） |
| `python3 -m pytest tests/test_reliability.py -q` | **45 passed**（主路径） |
| `RELIABILITY_FORCE_PURE=1 python3 -m pytest tests/test_reliability.py -q` | **45 passed**（强制纯 Python 回退路径） |
| `python3 -m pytest -q`（全量回归，验收 V6） | **280 passed，0 failed** |
| `flake8 src/reliability.py tests/test_reliability.py`（max-line 120） | 0 违规 |
| 真实 MySQL 8.0.46 集成冒烟 | `reliability_runs` DDL 幂等创建 OK；INSERT→SELECT 往返 OK（DECIMAL(5,3) 读回 Decimal、JSON 列 round-trip）；测试行已清理 |
| Streamlit AppTest 页面冒烟 | admin 进页渲染标题/IAA 口径徽章/选择器；annotation_submissions 未建表时 `st.error` 兜底不崩；未登录/无角色被入口 role gate 拦截 |
| 规范 §3 签名核对 | `compute_alpha(units, value_type)`、`run_reliability(category, task_type, features_meta)`（补 None 默认=自动读 features.yaml，位置传参兼容规范签名）、`render_reliability_page()` 与规范一致 |

## 5. 备注（给 review/集成）

1. `annotation_submissions` 表尚未在库中创建（Agent B 的 `ensure_flow_tables` 负责）；在其创建前，`run_reliability` 返回带 `db_error` 的结果、页面 `st.error` 兜底——不影响其它页面。
2. `reliability_runs` 已在真实库中按规范 §2 DDL 幂等创建并验证（无外键，可独立存在），测试行已清理，库中现无残留行。
3. ordinal 分支对**非数值标签**按排序字典序映射（无显式次序信息时的唯一可行默认）；configs/motion/features.yaml 的 ordinal 特征（P5 速度、M2 情态急促度等）均为数值编码，不受影响。
4. α 命名口径：所有指标均为 **AI-assisted IAA（全员可见 AI 草稿）**，页面徽章与 CSV 首行都带该标注（用户决策③、验收 V7 同源）。
