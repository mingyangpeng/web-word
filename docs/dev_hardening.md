# 安全加固与遗留清理（多人标注系统 · review 轮收尾）

> 依据：`docs/review_R1.md` 遗留 3 处 P2（F3 CSV 公式注入 / F4 会话角色快照陈旧 /
> F5 内置默认口令靠流程约束）与 `docs/review_R5.md` 遗留 4 项（测试残留用户 /
> reliability_runs 无归属列等）。
> 改动范围：`src/security.py`、`src/users_db.py`、`src/reliability.py`、
> `src/app.py`（仅任务 2/3 相关区域）、`scripts/cleanup_test_users.py`（新增）、
> `tests/test_security_hardening.py`（新增）、`README.md`、`tests/test_csv_protection.py`（触发集断言同步）。
> 未触碰：`src/cluster_analysis.py`、`src/template_engine.py`、`src/semantic_search.py` 及其测试。
>
> **结论：五项加固全部落地；`python3 -m pytest -q` 592 全绿（基线 554 + 新增 38，
> 0 failed / 0 skipped）；新增文件 flake8 0 违规。**

## 1. CSV 公式注入防护（R1-P2a）

- **统一实现**：`src/security.sanitize_csv_cell(value)` —— 字符串首字符为
  `= + - @ \t \r` 之一时前置单引号 `'`（Excel/WPS 公式注入标准防护，OWASP
  CSV 注入建议同批前缀），数字/None/正常文本原样返回。历史名
  `sanitize_csv_value` 改为指向**同一实现**的别名（`is` 判等），杜绝两份逻辑漂移；
  `sanitize_csv_dataframe` 整表路径同步。触发集在原四类基础上补 `\r`（回车），
  `tests/test_csv_protection.py` 的集合完备性断言同步扩展（其余断言未动）。
- **导出点逐个核对**（全部在 `to_csv` / `csv.writer` 前过单元格）：
  | 导出点 | 状态 |
  |---|---|
  | `src/app.py` 反馈导出（约 ：1408） | 已有防护（前序轮接入），本轮核对无需改动 |
  | `src/app.py` 标注导出（`get_annotation_export_rows` 后 DataFrame，约 ：2373） | 已有防护（前序轮接入），本轮核对无需改动 |
  | `src/reliability.py` `_export_csv`（信度/分歧导出） | **本轮新增**：每个 `writer.writerow` 单元格过 `sanitize_csv_cell`（分歧取值/特征名可能带用户自由文本） |
  | `src/annotation_flow.py` | 无任何导出点（grep 核对），无需改动 |
  | `src/template_engine.py` 模板导出 | 前序轮已改为调用 `security.sanitize_csv_value`；本轮把该名变为同一实现的别名，**未改动该文件**，测试行为不变 |
- `src/users_admin_page.py` 同样无导出点（核对）。

## 2. 默认口令流程约束（R1-P2c）

- **数据层**（`src/users_db.py`）：
  - `change_password(user_id, new_plain) -> bool`：长度 ≥ `MIN_PASSWORD_LENGTH`
    （=8）应用层先拒（校验先于任何数据库访问）、`hash_password` pbkdf2 新随机盐
    重哈希后写库；用户不存在 / 数据库错误返回 False。不改 users 表结构。
  - `is_using_default_password(user_id) -> bool`：弱口令判据 —— 取库中
    `password_hash` 在数据层内完成 `verify_password(默认口令, stored)` 比较
    （哈希不出数据层，app 只拿 bool）。
- **登录逻辑**（`src/app.py` 侧边栏）：登录表单 `verify_login` 成功后写入
  会话标记 `_user_db_backed`；已登录分支每次 rerun 实时判据仍匹配默认口令时，
  侧边栏顶部渲染 `st.sidebar.warning`「**内置默认口令，请立即修改**」强制提示
  + 内联改密表单（两次输入一致性/长度校验 → `change_password`）——横幅持续
  显示直到口令已改（判据每次实时取库，改密成功下次 rerun 即消失）。
  登出时同时清除标记。

## 3. 会话角色防陈旧（R1-P2b）

- **数据层**（`src/users_db.py`）：`get_user_role(user_id) -> str | None` ——
  实时读库；用户不存在 / **已停用（active=0）** / 数据库不可用返回 None。
- **app 侧**（`src/app.py`，仅登录区最小改动）：新增 `_refresh_session_user()`，
  在 `render_sidebar()` 顶部调用（先于 `main()` 页面分派，且侧边栏每次 rerun
  必经）：
  - 只有**经登录表单真实鉴权建立**的会话（`_user_db_backed` 标记）才回查 ——
    测试/工具直接注入 `session_state["user"]` 的会话无标记，行为与旧版一致
    （既有 R3 权限矩阵测试全部原样通过）；
  - 停用 / 删除 → 清会话 + `st.warning`「账号已被停用或删除，会话已失效，
    请重新登录」—— 下次任意操作（含基础页）即被登出（fail-closed：库暂时
    不可读时同样登出，不留旧权限会话；DB_AVAILABLE=False 的断库降级路径跳过
    回查，保留既有断库语义）；
  - 角色变更 → 就地刷新会话快照 —— 登录快照自此**仅用于显示**，标注 /
    用户管理 / 信度三个受保护页入口（及侧边栏可见性过滤）读到的都是当次
    实时角色，管理员改角色/停用立即生效，无需重新登录。

## 4. reliability_runs 归属列（R5 遗留 2）

- `RELIABILITY_RUNS_DDL` 补 `created_by INT NULL`（触发本次计算的 users.id；
  NULL 允许脚本/数据层直调不带归属）。
- **幂等迁移**：`_ensure_reliability_table()` 在 `CREATE TABLE IF NOT EXISTS`
  之后执行 `_migrate_created_by_column()` —— `INFORMATION_SCHEMA.COLUMNS`
  查列（`TABLE_SCHEMA = DATABASE()`，标识符全字面量），不存在才
  `ALTER TABLE ADD COLUMN`；重复调用不炸、不重复加列。已有旧库（如本机
  web_word_db）在下次 `run_reliability` 落库时自动补列（本轮全量回归已在
  真库上实际触发并验证）。
- `run_reliability(category, task_type, features_meta=None, created_by=None)`
  新增可选参数 → `_persist_run` 落库（INSERT 参数追加在末位，既有假游标
  断言的下标 0–5 不受影响；脏值防御：不可整型化按 NULL 落库不炸页面）。
- `render_reliability_page` 调用处传当前会话用户 id：
  `run_reliability(category, task_type, created_by=user.get("id"))`。

## 5. 测试用户清理（R5 遗留 1）

- **新增 `scripts/cleanup_test_users.py`**：按用户名 LIKE 前缀白名单
  （`e2e\_r5\_%` —— e2e 验收脚本前缀；`agentE\_e2e\_%` —— 前序 review 轮遗留；
  下划线转义防单字符通配误伤，可 `--prefix` 临时追加）先查后删：
  - **--dry-run 默认开**：只打印匹配用户清单（id/username/role/active/created_at）
    与各关联表行数，不动数据；`--apply` 才真删；
  - 删除按外键依赖序：adjudications（adjudicator_id）→ annotation_submissions
    （coder_id）→ assignments（assignee_id/assigned_by）→ reliability_runs
    （created_by，列存在才删）→ users，全程单事务；删除后自校验前缀归零；
  - 误伤护栏：只删匹配前缀的行，生产账号一律不碰。
- **已实际执行**：真库 web_word_db 的 9 个 `agentE_e2e_*`（active=0 僵尸号，
  R5 遗留清单第 1 条）已按本脚本 `--apply` 清除（关联行 0 条），users 表回到
  仅 admin 基线；执行前后五表计数核对通过。
- `README.md` 「👥 多人标注（MOVECAT Collab）」小节末尾补一行用法
  （dry-run 预览 / --apply 真删 / 关联行随删语义）。

## 6. 测试（tests/test_security_hardening.py，新增 38 项）

| 组 | 覆盖 |
|---|---|
| TestSanitizeCsvCell（11） | = + - @ tab \r 六类注入串前置单引号；正常文本/中间触发/数字/None 不动；触发集合完备；别名与主实现 `is` 同一；DataFrame 整表路径与原对象不可变 |
| TestReliabilityExportCsvProtection（3） | 信度导出端到端：分歧取值 `=cmd…`、特征名 `-weird…` 被加引号，正常行原样 |
| TestWeakPasswordPolicyPure（4） | 弱口令下限=8；7 位入口即拒（monkeypatch 断言**不触库**）；恰 8 位过门走到写库路径（假游标）；非字符串拒绝 |
| TestRunReliabilityCreatedBy（3） | run_reliability 的 created_by 透传 INSERT 参数第 8 位；缺省 None；脏值落 NULL 不炸 |
| TestChangePasswordIntegration（5，真库） | 默认 admin 判据初始 True → 改密后 False、admin123 登录失效；弱口令拒绝且旧哈希不动；重哈希后旧口令失效/新口令可登录/存储格式合法；不存在用户 False；改回 admin123 判据重新为 True |
| TestRoleLiveCheck（4，真库） | 改角色 get_user_role 当次返回新角色（旧权限立即失效）；停用 → None → 启用恢复；不存在 None；停用后 verify_login 拒绝 |
| TestCreatedByMigration（4，真库） | 建表+迁移连跑两次不炸、列恰一条；旧表（剔除 created_by 的 DDL）迁移补列且再跑幂等；_persist_run 落库 42/NULL；run_reliability 端到端（真实提交 → 落库 created_by） |
| TestHardeningUi（3，AppTest+真库） | 默认口令用户登录出横幅 → 表单改密（不一致/7 位报错 → 合规成功）→ 横幅消失且 admin123 失效；管理员改角色后旧会话下次操作即按新角色拦截标注页；停用用户下次任意操作被登出并提示 |

## 7. 回归验证

| 项 | 结果 |
|---|---|
| `python3 -m pytest -q`（全量） | **592 passed**（基线 554 + 新增 38），0 failed / 0 skipped（本机有 MySQL） |
| 无 MySQL 环境（CI） | 数据层/AppTest 类沿用类级 skipif 约定，纯函数/假游标部分全跑 |
| flake8（新增/改动文件） | 0 违规（app.py 的 E402 为存量既有） |
| 真库状态 | users 仅剩 admin（9 个残留已清）；reliability_runs 已含 created_by 列、行数回 0 |
| 未触碰模块 | cluster_analysis / template_engine / semantic_search 及其测试零改动（git diff 核对） |
