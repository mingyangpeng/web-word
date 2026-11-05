# R0 Review · Agent B：标注提交与仲裁流模块改动清单

> 依据唯一事实源 `docs/p1/多人标注系统设计规范.md` 实现（§2 三表 DDL、§3 模块契约、§6 安全规则、验收 V2/V3/V7 数据层侧、V6）。
> 状态：完成。`tests/test_annotation_flow.py` 71 通过（含 8 项真实 MySQL 8.0 集成，非 skip）；全量 `pytest -q` **351 通过、0 失败、无回归**（users/reliability 等既有测试全绿）。

## 1. 新增文件

### `src/annotation_flow.py` —— 标注提交与仲裁流数据层

- 建表 SQL：规范 §2 的 **annotation_submissions / adjudications / assignments 三表 DDL 原样**（InnoDB / utf8mb4 / ENUM / UNIQUE 约束 / 外键一概照抄；唯一差异：payload 列的中文注释为满足 repo flake8 max-line=100 换行续写 `--`，列定义本身未动；users_db 同样去掉了行尾分号）。
- 规范 §3 契约函数，签名逐一与规范一致（`inspect.signature` 核对过）：
  - `ensure_flow_tables() -> None`：幂等建三表（先 assignments——只依赖 users，再依赖 users+oald_senses 的两表）；被引用表缺失/DB 不可用只记 error 日志不抛（与 `users_db.ensure_user_tables` 容错口径一致）。集成时需先调 `users_db.ensure_user_tables()`。
  - `submit_annotation(category, sense_id, task_type, coder_id, payload, ai_assisted=True) -> bool`：**INSERT ... ON DUPLICATE KEY UPDATE**（uq_submission），同 (sense, task, coder) 重复提交=整行覆盖且 **status 重置 'submitted'**（覆盖即重新进审核流，旧 adjudicated 结论不自动沿用）——验收 V2。payload 以 `json.dumps(ensure_ascii=False)` 落 JSON 列；ai_assisted 默认 1（用户决策③）。
  - `validate_payload(task_type, payload) -> bool`（模块内校验入口）：payload 必须非空 dict、值全标量（拒 dict/list/None/NaN/Inf）；admission 任务必须有 `admission` ∈ {Y,EXT,N}（§2 注释），`needs_review` 若给必须 bool；feature_coding 必须有非空 `features` dict（键非空特征码、值标量）；alignment 结构从宽。非法值应用层先拒，根本不进数据库。
  - `get_my_submissions(coder_id, category, task_type) -> list[dict]`：标注员**只看自己**（用户决策④独立性入口），含 submitted/adjudicated 两态；payload 字符串自动解析为 dict，ai_assisted 转 bool。
  - `get_submissions_for_sense(sense_id, task_type) -> list[dict]`：reviewer/admin「看全部」入口，LEFT JOIN users 带 username/display_name 供仲裁面板；页面层必须 role gate。
  - `detect_disagreements(category, task_type, min_coders=2) -> list[dict]`：只统计 status='submitted'；admission 比对 `admission/schema/alignment/needs_review` 四字段（**bool 转 'true'/'false' 比较**，int 0/1 防御兼容，NaN 按缺失跳过），feature_coding 逐特征比 `payload["features"]`，alignment 比 alignment；返回 `[{sense_id, verb, sense_index, n_submissions, fields:[{field, values:{coder_id_str: value}}]}]`，verb/sense_index 经 LEFT JOIN oald_senses(headword, sense_index)；缺失容忍（某 coder 缺该字段不参与比对）；已仲裁的退出清单——验收 V3。
  - `save_adjudication(sense_id, task_type, adjudicator_id, gold_payload, submission_ids, note) -> bool`：uq_adjudication 唯一，重复仲裁=覆盖定稿（gold/submission_ids/adjudicator_id/note/created_at 更新）；gold_payload 过同一 payload 校验；**同一事务**（`get_db_cursor(autocommit=False)`）里 INSERT gold + `UPDATE annotation_submissions SET status='adjudicated' WHERE id IN (动态占位符)`，与 reliability.py「只统计 submitted」口径衔接；submission_ids 为空则只写 gold 不翻状态。
  - `get_assignment_stats() -> list[dict]`：每标注员/每任务进度——assignments 每行 LEFT JOIN 提交计数（n_submitted/n_adjudicated 按 status 分列），并补「有提交但无分配」的孤儿行（assignment_id/assignment_status=None，自发表情况）；scope_verbs JSON 解析（NULL=全部动词）。
- 补充函数 `assign_task(assignee_id, category, task_type, scope_verbs, assigned_by) -> bool`（经任务方确认的规范外补充，供后续 admin 分配页调用）：INSERT assignments；scope_verbs None=全部动词，否则非空字符串列表存 JSON；非法 task_type/空 category/空动词列表拒绝；assignee 不存在由 FK 拒绝（errno 1452 捕获返回 False）。
- 全部 SQL 参数化，无字符串拼接（IN 子句只用动态 `%s` 占位符）；风格沿用 `mysql_db.get_db_cursor` + try/except pymysql.Error + logger，与 users_db.py / reliability.py 一致。

### `tests/test_annotation_flow.py` —— 71 项测试

- 纯逻辑层（63 项，假游标按 SQL 文本分派，test_reliability.py 同款手法，CI 必跑）：
  - ensure：三表 DDL 落地（uq_submission / uq_adjudication / status 两态枚举文本断言）、建表顺序、DB 异常吞掉不抛；
  - payload 校验：三任务合法结构、admission 非法值/缺键/needs_review 非 bool 拒绝、非标量/NaN/Inf 拒绝、空 payload 拒绝、额外标量键放行；
  - **V2 upsert**：重复提交走 ON DUPLICATE KEY UPDATE 且 status 重置 'submitted'；payload JSON 中文不转义；非法 payload/参数零 SQL 执行；
  - **V3 分歧**：分歧检出含 verb/sense_index（JOIN 种子）、全一致不列、schema/alignment 也比、needs_review true/false 比较（含 bool 相等不列、int 0/1 兼容）、payload 为 JSON 字符串可解析、缺失容忍、NaN 视缺失、adjudicated 剔除、min_coders 门槛（2 人 vs 3 人）、单人/孤儿义位（verb=None）、feature_coding 逐特征（多分歧特征按名排序、单方特征不列、bool 特征归一）、alignment 任务、非法 task_type/DB 异常返回 []；
  - 仲裁：INSERT+UPDATE 参数断言（ids/gold JSON、IN 占位符）、空 submission_ids 跳过 UPDATE、autocommit=False 事务断言、非法 gold/ids/task/note 拒绝且零执行、DB 异常 False；
  - assign_task / stats：参数与 scope_verbs JSON、None=全部动词、孤儿行合并、scope_verbs NULL 解析、DB 异常返回 []。
- 集成层（8 项，`@pytest.mark.skipif(not HAS_MYSQL, ...)`，与 test_users_db.py 同约定；跑在独立测试库 `web_word_flow_test`，monkeypatch `db.MYSQL_DATABASE` + 池按键隔离，每测重建、结束 DROP）：用 `mysql_db.CREATE_TABLES_SQL` 建权威层全套表（oald_senses/users 是 flow 表外键目标）→ ensure_user_tables + ensure_flow_tables；验证 ensure 幂等、**V2 覆盖更新**（仍一行、id 不变、payload 更新、非法值不入库）、**V3 端到端分歧**（两码人 admission 分歧+needs_review true/false、一致义位不列、feature_coding）、独立性（get_my_submissions 只见自己 vs get_submissions_for_sense 双方+username）、仲裁翻状态+重复仲裁覆盖 gold+分歧清空+覆盖提交后 status 复位、assign_task+孤儿统计。

## 2. 未改动

- `src/app.py`、`src/users_db.py`、`src/reliability.py`、`src/category_pack 相关`、`requirements.txt` —— 按约束保持原样（本模块无新增依赖）。

## 3. 验证记录

| 项 | 结果 |
|---|---|
| `python3 -m pytest tests/test_annotation_flow.py -q` | **71 passed**（MySQL 8.0.46 本地实跑，8 项集成非 skip） |
| `python3 -m pytest -q`（全量回归，验收 V6） | **351 passed，0 failed** |
| `flake8 src/annotation_flow.py tests/test_annotation_flow.py` | 0 违规（repo `.flake8`，max-line 100） |
| 规范 §3 签名核对 | 7 个契约函数 + assign_task 补充，`inspect.signature` 逐一比对一致 |
| 测试库清理 | `web_word_flow_test` 跑完即 DROP，无残留 |

- 环境备注：与 Agent A 相同的本机 MySQL 实跑环境；为其测试库模式一致，用本地 root 给 `web_word_user` 补授了 `web_word_flow_test` 库权限（仅测试库，GRANT 保留属测试约定内操作）。无 MySQL 时集成类自动 skip，CI 仍全绿。

## 4. 遗留与交接

- **V7（AI 草稿可见）与角色分派属页面层**（规范 §5，app.py 集成步骤）：数据层已就绪——annotator 表单保存走 `submit_annotation`（ai_assisted 默认 True），独立性由 `get_my_submissions`（annotator）与 `get_submissions_for_sense`（reviewer/admin，需 role gate）保证。
- 仲裁面板可组合：`detect_disagreements` 出清单 → `get_submissions_for_sense` 看双方 → `save_adjudication` 定稿（其 submission_ids 参数传面板勾选的提交 id，未勾选的保持 submitted）。
- admin 分配页直接调 `assign_task` + `get_assignment_stats`（规范 §3 外的唯一补充函数，签名经任务方确认）。
- 语义口径提醒：重复提交会把该行 status 重置为 'submitted'（旧 adjudicated 不沿用）；`save_adjudication` 只翻转**本次明示的** submission_ids——两个口径都与 reliability.py「只统计 submitted」衔接，集成时无需额外处理。
