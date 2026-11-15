# R4 Review · 代码质量与测试盲区审查（多人标注系统）

> 被审代码：`src/users_db.py`、`src/annotation_flow.py`、`src/reliability.py`、
> `src/category_pack.py`、`src/users_admin_page.py`、`src/app.py`（登录/提交流/仲裁/信度集成段）、
> `configs/motion+speech`、五个对应测试文件。前置报告 `review_R1/R2/R3.md` 已通读
> （F1–F5、O1–O3 不重复报）。
> 方法：逐条过审查清单 + 假游标/真实 MySQL（web_word_flow_test 等独立测试库）实测 +
> `python3 -I -c "import ..."` 导入健康探针 + flake8 全新增文件复验。
>
> **结论：补测试 13 项（另扩展既有 2 项），修复 6 处，消重 2 处（另 4 组"形似异义"判定不消重，见 §4）。
> `python3 -m pytest -q` 430 全绿（原 417 + 新增 13）；新增 10 个文件 flake8 0 违规。**

## 1. 审查清单逐条结论

### 1.1 清单 1 · 测试盲区补齐

**a) submit_annotation 非法 payload —— 服务端校验此前已在位，一处静默入库漏洞本轮修掉（F-R4-1）**

| 输入 | 此前行为 | 结论 |
|---|---|---|
| 缺 `admission` 键 | `validate_payload` 拒绝（annotation_flow.py 入口校验） | 已有校验 + 已有测试（`test_admission_missing_key_rejected`），非盲区 |
| `admission` ∉ {Y,EXT,N} | `validate_payload` 枚举拒绝（`ADMIT_VALUES`） | 已有校验 + 已有测试（`test_admission_illegal_value_rejected`），非盲区 |
| features 值非数字 | **标量字符串按设计放行** —— C1 等 nominal 特征的合法取值就是字符串标签，拒绝会破坏规范 §2 的 payload 结构；dict/list/None/NaN float 此前已拒 | 非风险，维持 |
| features/额外键值 = `"nan"` 串 | **静默入库**（`_is_scalar_label` 放行一切字符串），而两个下游消费方（`_normalize_for_compare`、`_is_usable_label`）都把它按缺失剔除 —— 库里只存垃圾值 | **F-R4-1 已修** + 3 项测试（validate / submit 假游标 / 真实 MySQL 集成） |

白名单字段的取舍：`validate_payload` 对未登记额外键放行是文档化的前向兼容决定（额外值必须标量、且不进分歧比对/信度口径），不构成数据质量风险，本轮维持不放死白名单（收紧会破坏前向兼容且无对应风险面）。"inf" 串两侧口径一致按合法标签放行（R2 #20 已验证）。

**b) detect_disagreements 对 feature_coding 此前是否真有覆盖 —— 有，非盲区**

`TestDetectDisagreementsFeatureCoding` 此前 5 项（逐特征比对 / 多分歧排序 / 单人特征 / bool 归一 / R2 nan 串回归）+ 真实 MySQL 集成 1 项（`test_feature_coding_disagreement_end_to_end`）。本轮补 1 项边界：特征值**显式 None** 按缺失（锁定 `features.get(name) is not None` 过滤口径）。

**c) save_adjudication 对不存在 sense_id / 无 submission_ids —— 补 2 项真实 MySQL 测试**

- 无 submission_ids（`[]`）：此前已有假游标测试（`test_empty_submission_ids_skips_update`：只写 gold 不翻状态）。
- `submission_ids=None`/非 list/坏元素：此前已有拒绝测试。
- **sense_id 不存在（新增）**：真实 MySQL FK 拒绝 → 返回 False，`adjudications` 无残留行（此前无测试覆盖 FK 路径）。
- **submission_ids 指向不存在的提交（新增）**：数据层宽容口径固化 —— gold 照写（留痕）、不炸、无提交被翻转（页面传参恒来自 `get_submissions_for_sense`，此为防御路径）。

**d) compute_alpha units 空 dict / value_type 非法串 —— 已有覆盖，补非 dict 边界并顺带修出一个崩溃路径（F-R4-3）**

- 空 dict：`test_empty_units` 已有；value_type 非法串：`test_bad_task_value_type_does_not_crash`（"interval-ish" → nominal）已有 —— 非盲区。
- **units 非 dict（None/list/串）与内层非 dict（`{1: "Y"}`）此前会抛 AttributeError**（`inner.get`/`.values()` 触达非 dict）——本轮加守卫按缺失处理（F-R4-3）+ 2 项测试。

**e) run_selfcheck 占位符颗粒度 —— 实现本就逐占位符报告，测试颗粒度不足，本轮钉死**

`_check_screening` 对 9 个占位符逐个检查、逐条报 `缺少占位符 {name}`；既有测试只断言 `any(...)`（不够精确）。新增 `test_missing_placeholder_granularity_exact`：同挖 2 个占位符 → **恰好 2 条问题、每条只点名缺失的那个、无其他自检条款噪音**（全清单精确断言）。

### 1.2 清单 2 · 资源与健壮性 —— 通过（含 2 处修复）

- **数据库连接自取自还**：五个新模块每个函数体都是 `with get_db_cursor() as cursor:`（mysql_db 的上下文管理器在 finally 里把连接归还池、游标关闭）；`save_adjudication` 用 `get_db_cursor(autocommit=False)` 保证 gold 落库与状态翻转同事务（成功 commit / 异常 rollback）。**无模块级连接、无长连接泄漏点**（逐函数走查 + 现有 `_patch_boom` 断库测试佐证异常路径同样归还）。
- **JSON 解析失败路径**：`parse_payload` / `_parse_json_list` 坏 JSON/非 dict/bytes 乱码 → `{}`/`None` 按缺失剔除，不炸。本轮补 `scope_verbs` 坏 JSON（"not-json"/`'{"a":1}'`/截断串）→ None 的测试。
- **大 payload（1000 特征）**：三条路径实测不炸（新增 3 项测试）——`submit_annotation` 校验+JSON 序列化+参数捕获、`detect_disagreements` 1000 特征只报真实分歧、`run_reliability` 逐特征 1000 项 α（999 一致 + 1 分歧，overall=999/1000 精确断言）。
- **flake8**：新增 10 个文件（5 源码 + 5 测试）**0 违规**；R2 §5.3 遗留的 `tests/test_category_pack.py` 3 处 E501 顺手修掉（F-R4-6）。`src/app.py` 为既有文件（历史 E402/E501 与本轮改动无关，R1–R3 同口径不扩权）。

### 1.3 清单 3 · 一致性 —— 通过（类型提示补齐见 F-R4-4）

- **logger 名**：五个新模块 + app.py 全部 `logging.getLogger(__name__)`，无 root logger 使用。
- **不打印密码/payload 全文**：grep 走查 —— users_db 日志只含用户名与异常对象 `e`（口令字面值仅存在于 `_DEFAULT_ADMIN_PASSWORD` 常量，不落日志）；annotation_flow 拒绝路径只记 sense/coder id 与 task_type，不 dump payload；users_admin_page 只记操作者与目标 id。
- **docstring 与签名一致**：核对无漂移；本轮把 7 个公共函数签名补上类型提示后与 docstring 契约完全对齐（F-R4-4）。
- 观察项：reliability 的日志用 `%s` 惰性格式、其余模块用 f-string —— 两种均为合法风格且不在密码/payload 风险面上，未做无意义翻改。

### 1.4 清单 4 · 死代码与重复 —— 见 §4（修复 2 处，4 组判定不消重）

### 1.5 清单 5 · requirements 与导入健康 —— 通过

- `krippendorff>=0.9.0` 已在 requirements.txt（本轮复核，注释与 reliability.py 的双路径说明一致），无重复/遗漏依赖。
- **导入无副作用**：五个新模块 `python3 -I -c "import ..."` 全部 0 退出 —— import 时不连库、不建表（`ensure_user_tables`/`ensure_flow_tables`/`_ensure_reliability_table` 全在函数体内，仅由 app.py 运行时按需调用）；users_admin_page 顶层 import streamlit 属页面模块常态，无 DB 副作用。

## 2. 补测试清单（13 项新增 + 2 项扩展，全部遵循现有两层风格：假游标本地跑、MySQL 依赖 skipif）

| # | 测试 | 位置 | 对应清单 |
|---|---|---|---|
| 1 | `test_nan_string_values_rejected` | tests/test_annotation_flow.py::TestValidatePayload | 1a |
| 2 | `test_nan_string_payload_rejected` | 同 ::TestSubmitAnnotation（假游标：SQL 根本不执行） | 1a |
| 3 | `test_large_payload_1000_features` | 同 ::TestSubmitAnnotation | 2 |
| 4 | `test_status_constants_match_ddl_enum` | 同 ::TestEnsureFlowTables | 4 |
| 5 | `test_none_feature_value_treated_missing` | 同 ::TestDetectDisagreementsFeatureCoding | 1b |
| 6 | `test_large_feature_set_1000` | 同 ::TestDetectDisagreementsFeatureCoding | 2 |
| 7 | `test_scope_verbs_bad_json_null` | 同 ::TestGetAssignmentStats | 2 |
| 8 | `test_adjudication_nonexistent_sense_fk_rejected` | 同 ::TestFlowIntegration（真实 MySQL FK） | 1c |
| 9 | `test_adjudication_unknown_submission_ids_tolerated` | 同 ::TestFlowIntegration | 1c |
| 10 | `test_non_dict_units_return_none` | tests/test_reliability.py::TestNotComputable | 1d |
| 11 | `test_non_dict_inner_values_treated_missing` | 同 ::TestNotComputable | 1d/2 |
| 12 | `test_large_feature_set_1000` | tests/test_reliability.py::TestRunReliabilityFeatureCoding | 2 |
| 13 | `test_missing_placeholder_granularity_exact` | tests/test_category_pack.py | 1e |

扩展既有 2 项：`TestFlowIntegration::test_illegal_payload_never_enters_db` 增补 'nan'/'NaN' 串经真实 MySQL JSON 列路径的拒收断言；`TestPageHelpers::test_parse_payload_variants` 随消重改指 `rel.parse_payload` 并增补 bytes 与非 dict 变体。

## 3. 修复清单（6 处，均已 Edit 落地）

### F-R4-1 · P2 数据质量 · payload 值为 NaN 字符串时静默入库 —— 已修复
* **位置**：`src/annotation_flow.py` `_is_scalar_label`。
* **问题**：字符串 `"nan"/"NaN"/" nan "` 通过校验入库，而两个下游消费方（本模块 `_normalize_for_compare`、reliability `_is_usable_label`）都把它按缺失剔除 —— 违反本模块自述的「非法值根本不进数据库」口径（R4 清单 1a 的实锤）。
* **修复**：`_is_scalar_label` 对字符串增加与 reliability 同口径的守卫（`float()` 可解析出 NaN 的串拒收）；"inf" 等非 NaN 数值串维持合法标签。测试：清单 1a 的 3 项（validate / 假游标 / 真实 MySQL）。

### F-R4-2 · P3 消重 · `_parse_payload` 两份逐字复制实现 —— 已修复（见 §4 消重 1）

### F-R4-3 · P3 健壮性 · units 内层非 dict 使 compute_alpha 抛 AttributeError —— 已修复
* **位置**：`src/reliability.py` `_units_to_matrix`（coder 收集 / raw 收集 / matrix 填充三处）。
* **问题**：`compute_alpha({1: "Y"}, ...)`（内层非 dict）在 `.get()/.values()` 处抛 AttributeError —— 与模块「不让单条脏数据炸掉整个引擎」的承诺不符（进程内公开 API 直达）。
* **修复**：内层非 dict 一律按缺失/无数据单元处理；返回 None 不抛。测试 2 项。

### F-R4-4 · P3 一致性 · 公共函数类型提示缺失 —— 已修复
* **位置**：`src/annotation_flow.py`（submit_annotation / get_my_submissions / get_submissions_for_sense / detect_disagreements / save_adjudication / assign_task）、`src/reliability.py`（run_reliability）。
* **修复**：按各自 docstring 的契约补齐注解（`note: Optional[str]`、`scope_verbs: Optional[list]` 等），运行时宽容语义不变（注解不参与运行时校验）。

### F-R4-5 · P3 死代码 · `STATUS_ADJUDICATED` 等常量零引用 + 页面魔法串分叉 —— 已修复
* **位置**：`src/annotation_flow.py` 常量定义、`src/app.py` render_submission_flow。
* **问题**：`STATUS_SUBMITTED/STATUS_ADJUDICATED/SUBMISSION_STATUSES` 定义后全仓零引用（死代码），而 app.py:2597 用魔法串 `"adjudicated"` 判状态 —— 数据层 ENUM 与页面口径靠裸串对齐。
* **修复**：app.py 导入 `STATUS_ADJUDICATED` 并接线状态判断；`SUBMISSION_STATUSES` 以契约测试钉死（`test_status_constants_match_ddl_enum`）。行为不变。

### F-R4-6 · P3 卫生 · R2 遗留 3 处 E501 —— 已修复
* **位置**：`tests/test_category_pack.py` 三处超长行（原 71/87/167 行），重排为多行，断言语义不变。

## 4. 消重清单

**已消重（2 处）**

1. **`_parse_payload` 逐字双份**（annotation_flow.py 与 reliability.py 各一份，完全相同）：公共化为 `annotation_flow.parse_payload`（附「唯一实现」docstring），reliability 删除本地副本改导入 —— payload JSON 列解析从此单一实现，行为逐字节不变（`test_parse_payload_variants` 与全部假游标/集成测试复跑通过）。
2. **状态口径魔法串**：app.py 页面判断的 `"adjudicated"` 裸串改用 `annotation_flow.STATUS_ADJUDICATED` 常量（见 F-R4-5）。

**判定「形似异义」不消重（4 组，避免为消重而改行为）**

- `_is_scalar_label`（flow，入口校验）vs `_is_usable_label`（reliability，计算过滤）：谓词形似但语义不同 —— 前者拒 inf（入库面）、后者 inf 可用（计算面）；一个「拒绝」一个「按缺失跳过」。合并必然改动某一侧行为，保留两份、docstring 互相引用口径。
- `_current_user`（app.py / users_admin_page.py 各一份 + reliability 内联同款 isinstance-dict 守卫）：app 导入两者，反向导入成环 —— 分层强制的重复；三处口径已由 R3-F1 统一，保留。
- HTML 转义：三处均为 stdlib `html.escape` 的别名导入（app/users_admin_page 的 `_html_escape`、reliability 的 `html.escape`），非逻辑重复。
- `_list_categories`（reliability）vs `CATEGORIES`（category_pack）：前者是带 ImportError 回退的容错包装（回退分支有既有测试覆盖），属纵深防御非重复。

## 5. 回归验证

| 项 | 结果 |
|---|---|
| `python3 -m pytest -q` | **430 passed**（原 417 + 新增 13），0 failed |
| `RELIABILITY_FORCE_PURE=1 python3 -m pytest tests/test_reliability.py -q` | 55 passed（纯 Python 回退路径全绿） |
| 真实 MySQL 集成（users / flow / apptest 三套件） | 全部实际执行、无 skip（含新增 2 项 FK/宽容口径用例） |
| `flake8` 新增 10 文件 | **0 违规** |
| `python3 -I -c "import src.xxx"` 五模块 | 全部 0 退出，无连库/建表副作用 |
| sanity 脚本（nan 拒收 / parse_payload 共享 / 非 dict units / 状态常量） | 全部通过 |
