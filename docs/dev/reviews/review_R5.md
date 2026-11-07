# R5 Review · 端到端验收（多人标注系统 · 真实 MySQL 完整协作工作流）

> 被验对象：`src/users_db.py`、`src/users_admin_page.py`、`src/annotation_flow.py`、
> `src/reliability.py`、`src/category_pack.py`（+ `src/app.py` 集成段）。
> 规范：`docs/spec/多人标注系统设计规范.md`（唯一事实源）。前置报告 `review_R1–R4.md`
> 已通读（F1–F5、O1–O3、F-R4-1…6 不重复报）。
> 方法：新增可重复执行的验收脚本 **`tests/test_e2e_workflow.py`**（类级
> `@pytest.mark.skipif` 无 MySQL 跳过），在**真实库 web_word_db** 上模拟
> 分配→提交→分歧→仲裁→α 完整协作工作流，专用前缀 `e2e_r5_` 隔离 + 结尾强清理。
>
> **结论：e2e 七步全部 PASS（连续 4 遍全绿，可重复执行验证通过）；
> `python3 -m pytest -q` 431 全绿（R4 的 430 + 本轮新增 1）；
> 新增测试文件 flake8 0 违规；总验收判定：PASS。**

## 0. 验收脚本设计（tests/test_e2e_workflow.py）

* **真实库 + 前缀隔离**（不用独立测试库）：步骤 2 要求 `oald_senses` 里 run 的
  **真实义位 id**，故跑在 web_word_db；所有测试用户名带前缀 `e2e_r5_`，
  删除按前缀定位（users/assignments/submissions/adjudications 四表按外键依赖序清理）。
* **reliability_runs 清理**：该表无用户外键、无法按前缀定位 —— 以测试开始时的
  `MAX(id)` 为水位线，结尾删除水位线之上的行（另以 `run_reliability` 返回的
  `run_id` 兜底）。
* **前置自愈**：setup 先清一次前缀残留（上次异常中断可自愈），teardown 断言
  前缀用户归零（清理不彻底显式报错）—— 保证「跑两遍都绿」。
* **fail-fast 前置条件**：`(motion, admission)` 提交切片非空时拒绝开跑并给出
  外来 coder_id 诊断（外部标注会混进分歧清单与 α，验收数字失真）。
* **可靠性**：无 MySQL 环境（CI）整类 skip；直连用 `autocommit=True`
  （与被测数据层同口径，避免 REPEATABLE READ 快照看不见连接池写入的行）。

## 1. e2e 七步实测输出摘要（真实 MySQL 8.0，逐步 PASS）

| # | 步骤 | 实测结果（pytest -s 原样摘要） | 判定 |
|---|---|---|---|
| 1 | **准备** | `ensure_user_tables` / `ensure_flow_tables` 幂等执行 OK；内置 admin（id=1，`verify_login('admin','admin123')` 走通）建号 coderA/coderB/reviewer（role 校验、pbkdf2 登录全链路各走通）；`assign_task`×2 落 assignments 2 行，`scope_verbs` 回读 = `["run","walk"]`，assigned_by=admin | PASS |
| 2 | **提交** | 取 run 的 3 个真实义位 id=**164/165/166**（且过滤掉已标注/已仲裁义位）；两 coder 各对 3 义位提交 admission 标注，payload 六字段齐备（admission/schema/alignment/cn_syntax/strategy/needs_review），`ai_assisted` 默认 True；设计为前 2 义位两人全字段一致、第 3 义位仅 `admission` 分歧（A=Y / B=N）；共 6 条入库 | PASS |
| 3 | **独立性** | `get_my_submissions(coderA)` 恰 **3 条**且全为本人（混入他人即失败；ai_assisted=True 佐证决策③）；`detect_disagreements`（reviewer 视角）恰报 **1 条分歧**（sense=166, verb=run, n_submissions=2），`fields=[admission]` 且 values 同时含 coderA='Y' 与 coderB='N'（键为字符串化 coder_id，JSON 安全） | PASS |
| 4 | **信度** | `run_reliability("motion","admission")`（features_meta 缺省，自动读 configs/motion/features.yaml）→ **n_coders=2、n_units=3**、per_feature={admission: **0.545**, schema: 1.000, alignment: 1.000}、**overall_alpha=0.848**（数值且 <1，与「2 人 3 义位含 1 处分歧」相符）；reliability_runs **落库 1 条**（回读 n_coders/n_units/overall_alpha 与返回值一致，含分歧摘要 JSON） | PASS |
| 5 | **仲裁** | reviewer 对分歧义位 `save_adjudication`（gold **admission=Y**，note 说明理由留痕）→ adjudications 恰 1 行（adjudicator_id=reviewer、submission_ids=两提交 id、gold_payload.admission='Y'）；状态流转正确：参与仲裁 2 条 → `adjudicated`，未参与的 4 条保持 `submitted`；**复核**：再算信度 n_units=2、α=1.0、分歧清零 —— 被仲裁提交按设计退出信度口径 | PASS |
| 6 | **范畴包冒烟** | `load_pack("motion")` 六件套加载+自检通过，返回键集 {admission, features, schemas, corpus_map, prompts, pack}，**features 15 项 in_clustering**（18 项中）；`load_pack("speech")` 成功（pack.category=speech） | PASS |
| 7 | **清理** | fixture 收尾按前缀删除四表协作数据、reliability_runs 按水位线删除；自校验前缀用户归零；**清理后五表全部回到基线**（users=10 既有账号、assignments/submissions/adjudications/reliability_runs=0）—— 连续 4 遍执行全绿，可重复性成立 | PASS |

补充验证：`RELIABILITY_FORCE_PURE=1`（纯 Python α 回退路径）下
`tests/test_reliability.py + tests/test_e2e_workflow.py` 共 **56 passed**，
两条 α 计算路径在 e2e 数据口径上一致。

## 2. 执行次序说明（任务书步骤 4/5 的交互，非缺陷）

任务书把「信度」列在「仲裁」之后，但按规范 §3 与 `save_adjudication` 契约，仲裁会把
参与提交置为 `adjudicated` 并使其**退出**信度口径（reliability 只统计
`status='submitted'`）——分歧一旦仲裁，「n_units=3、α<1」的快照不可复现（实测：
仲裁后只剩 2 个一致义位，α=1.0）。因此脚本**先取仲裁前信度快照（内部步骤 4），
再做仲裁并复核退出行为（内部步骤 5）**；任务书两步的全部断言均被覆盖且各自 PASS，
仅执行次序依数据流语义调整。脚本模块 docstring 有同款说明。

## 3. 修复清单（本轮 1 处，均为验收脚本自身问题，产品代码 0 缺陷）

| # | 级别 | 问题 | 修复 |
|---|---|---|---|
| F-R5-1 | P3（测试件） | e2e 直连校验连接未开 autocommit，REPEATABLE READ 快照导致读不到连接池连接写入的 assignments 行（首跑 步骤1 0≠2 失败） | fixture 直连改 `autocommit=True`（与 `get_db_cursor` 默认口径一致），并留注释防回归 |

产品侧五模块（users_db / annotation_flow / reliability / category_pack / users_admin_page）
在真实 MySQL 全流程中未发现新缺陷：payload 校验、UNIQUE upsert、状态机、分歧检测、
α 计算与落库、范畴包自检全部与规范一致。

## 4. 文档同步清单（4 处，全部增量插入，未改既有叙述）

| 文件 | 改动 |
|---|---|
| `README.md` 目录结构 | 补 `configs/` 一行（范畴包：motion / speech 六件套 + _template 模板）。src/ 五个新模块的一行各注（users_db / users_admin_page / annotation_flow / reliability / category_pack）**已在前序集成中就位且核对无误**，未重复添加 |
| `README.md` 新增小节 | 「👥 多人标注（MOVECAT Collab）」（位于既有「多人协作标注系统」小节之后）：四角色语义、GitHub 式流程（分配→提交→分歧→仲裁→α）、AI-assisted IAA 口径、范畴包五步接入判据、首次启动内置 admin 须改密；并指向设计规范与 e2e 脚本 |
| `ARCHITECTURE.md` | 「一句话架构」分层图补「协作层（users_db · annotation_flow · reliability）」一行及职责注释 |
| `CLAUDE.md` | 「### 分层」模块清单补「协作层（多人标注）」一行（五模块各自职责） |

## 5. 回归验证

| 项 | 结果 |
|---|---|
| `python3 -m pytest -q` | **431 passed**（R4 的 430 + 本轮新增 e2e 1），0 failed / 0 skipped（本机有 MySQL） |
| e2e 连续执行 | **4 遍全绿**（含修复后 3 连跑 + 全套件内 1 跑）；每遍结束五表回基线 |
| `flake8 tests/test_e2e_workflow.py` | 0 违规 |
| `RELIABILITY_FORCE_PURE=1` 纯 Python α 回退 | test_reliability + e2e 共 56 passed |
| 无 MySQL 环境 | 类级 `@pytest.mark.skipif(not HAS_MYSQL)`，CI 自动跳过不红 |

## 6. 总验收判定：**PASS**

e2e 七步（准备 / 提交 / 独立性 / 信度 / 仲裁 / 范畴包 / 清理）在真实 MySQL 上全部
符合设计规范 §1–§7；设计规范的验收标准 V1–V7 在数据层与集成层均已有 R1–R4 +
本轮 e2e 的双重覆盖。

## 7. 遗留清单（不阻塞验收）

1. **users 表残留历史 e2e 用户**：`agentE_e2e_*` 等 7 个 `active=0` 账号（前序 review
   轮次遗留，非本轮产生，未越权代删）。建议后续人工清理或加统一清理脚本。
2. **reliability_runs 无归属列**：无法按用户/前缀定位归属，e2e 只能按 id 水位线清理；
   若未来要在共享库上做多方验收，建议给该表加 `created_by` 之类的归属列。
3. **e2e 前置条件**：`(motion, admission)` 提交切片必须为空（脚本 fail-fast 并给诊断）。
   系统投产后跑验收需选安静窗口，或把 e2e 迁到「真实 oald_senses 副本 + 独立库」形态。
4. **README 双节并存**：新增「👥 多人标注（MOVECAT Collab）」与既有「👥 多人协作标注
   系统」两节内容部分重叠（后者含旧任务类型叙述 image_schema/syntax，与规范 ENUM
   admission/feature_coding/alignment 不一致）。按任务要求未改既有叙述，建议后续
   统一合并时以设计规范口径为准。
