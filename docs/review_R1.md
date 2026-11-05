# R1 Review · 功能对照与安全审查（多人标注系统）

> 审查依据：唯一事实源 `docs/p1/多人标注系统设计规范.md`（验收 V1–V7、安全规则 §6）。
> 被审代码：`src/users_db.py`、`src/users_admin_page.py`、`src/annotation_flow.py`、
> `src/reliability.py`、`src/category_pack.py`、`src/app.py`（标注集成部分）、`configs/motion/`、`configs/speech/`。
> 方法：逐条过审查清单 + 实际运行验证（合成数据手算 α、故意改坏范畴包跑 selfcheck、
> SQL 注入模式 grep、pytest 全量）。前置报告 `docs/review_R0_agentA–E.md` 已通读。
>
> **结论：发现 5 处，修复 2 处，剩余 3 处（均 P2，见 §3）。`python3 -m pytest -q` 394 全绿。**

## 1. 审查清单逐条结论

### 1.1 V1 角色门 —— 通过

| 检查点 | 结论 | 证据 |
|---|---|---|
| 未登录进标注页被拦 | ✅ | `app.py` `main()` 分派处对 `annotate` / `submission` / `users_admin` / `reliability` 四页统一 `require_login()`（未登录渲染「请先登录」并 return）；`render_submission_flow` / `render_reviewer_panel` / `render_reliability_page` / `render_users_admin_page` 函数入口各自再判一次（纵深防御） |
| annotator 任何路径不可见他人提交 | ✅ | 全仓 grep：`get_submissions_for_sense` 唯一生产调用点在 `render_reviewer_panel`（入口 `role not in ("admin","reviewer")` 即 return，app.py:2618）；`detect_disagreements` 同样只在该面板。提交流只经 `get_my_submissions(coder_id)`，coder_id 取自 `st.session_state["user"]["id"]`，无外部输入通道 |
| users_admin 页 admin-only（函数入口） | ✅ | `render_users_admin_page` 入口：未登录 → return；`role != "admin"` → st.error + return（users_admin_page.py:225–231），不信任侧边栏隐藏（`_PAGE_ACCESS` 只是 UI 过滤） |
| reliability 页角色门 | ✅ | `render_reliability_page` 入口 `role not in ("admin","reviewer")` → return（reliability.py:720–723）；未登录（`user={}`）同样被拦 |

附带：viewer 在 `render_annotation_page` / `render_submission_page` 入口被显式拦截；admin 快速通道 `_render_annotation_admin_view`（直写权威层 `update_sense_annotation`）仅 `role == "admin"` 分支可达。

### 1.2 V2 upsert —— 通过

`submit_annotation`（annotation_flow.py:291–301）`ON DUPLICATE KEY UPDATE` 覆盖 `category`、`payload`、`ai_assisted`，且 **`status = 'submitted'` 重置**、**`submitted_at = CURRENT_TIMESTAMP` 刷新**；`sense_id/task_type/coder_id` 即唯一键本身。集成测试 `test_submit_and_resubmit_overwrites`（tests/test_annotation_flow.py:907，真实 MySQL）验证覆盖为新值且状态重置。

### 1.3 V3 分歧检测 —— 通过（合成用例实测）

- needs_review 布尔比较：`_normalize_for_compare` bool → `'true'/'false'`，且兼容 TINYINT 0/1（True 与 1 判同，实测不出假分歧）；
- null / 坏 payload：`_parse_payload` 失败返回 `{}`，按缺失剔除，不炸、不报假分歧（实测）；
- 单提交（n_coders < 2）不报（`max(2, min_coders)` 门槛）；某字段仅一人有值时跳过（实测）；
- 三编码人两两一致不报（取值集合大小 ≤ 1 → skip，实测）；三人中 2+1 分裂正确报出并列出 3 个取值（实测）；
- feature_coding 逐特征比对、NaN 按缺失（实测）。

### 1.4 V4/V5 抽查 —— 通过（实测）

- **V5**：`run_selfcheck("motion")` 通过；把 `schemas.yaml` 的 `particles_after` 故意改成 `particles_aftr` 后 selfcheck 报「图式 SOURCE_DETACH 引用的证据槽位 'particles_aftr' 未在 corpus_map.slots 中定义」，`load_pack` 抛 `CategoryPackError`（问题清单形式）。**speech 包同样生效**（见 §1.7）。
- **V4**：`compute_alpha` 合成数据手算对比（nominal）：
  - 数据 A（2 人×4 单元，1 分歧单元）：手算 D_o=2/8、D_e=2·3·5/56 → α=0.533333，实测 0.533333；
  - 数据 B（2 人×3 单元）：手算 α=0.444444（nominal 与 ordinal 同值，因对称），实测一致；
  - 完全一致 → 1.0；单人无配对单元 → None；缺失容忍数据手算 α=0.444444 实测一致；
  - 纯 Python 回退 `_alpha_pure` 与 krippendorff 库在 5 组数据（含 ordinal 3 值、字符串标签 nominal）上逐位一致（≤1e-10）。

### 1.5 安全 §6 —— 见 §2 发现清单

- **a) SQL 参数化**：✅ 全部新模块（users_db / annotation_flow / reliability）每个 `execute()` 均为常量 SQL + 参数元组；唯一动态拼接是 `save_adjudication` 的 `IN (…)` 子句，只拼接 `%s` 占位符（`", ".join(["%s"] * len(ids))`），值走参数 —— 无 f-string/% 格式化/concat 把值拼进 SQL 的模式（grep 证实）。
- **b) 密码哈希**：✅ pbkdf2_sha256 + `secrets.token_hex(16)` 每用户随机盐 + 150000 迭代（≥120000）；`hmac.compare_digest` 常数时间比较；`list_users` 不返回 password_hash；全仓日志 grep 无密码明文/口令字面值（仅异常对象 e 与用户名）。时序侧信道问题见 F1。
- **c) 登录失败信息**：✅ 统一「用户名或密码错误，或账号已停用。」（app.py:1302），不泄露「用户存在」。
- **d) UGC 转义**：✅ 进入 `unsafe_allow_html` 的用户生成/库内文本（用户名、显示名、payload 的 admission/schema/alignment、分歧取值、LLM reason/doubt、范畴包文本、定义/例句）全部过 `_html_escape`；`cn_syntax/strategy` 回显走 `st.dataframe`（非 HTML 渲染）；未过转义的插值仅出现在 st.info/st.success 等 Markdown 通道（Streamlit 不渲染裸 HTML）或纯文本 label，无注入面。
- **e) role 判定在渲染入口**：✅ 见 §1.1，四个新页面全部函数入口判定。

### 1.6 V7 AI 草稿可见性 —— 通过

`render_submission_flow`（annotator/reviewer 提交流，app.py:2474–2494）渲染 LLM 初筛草稿（tag/schema/align + reason/doubt，转义），无草稿时 caption 说明；表单预填优先级「本人上次提交 > LLM 草稿 > 空」，草稿仅作参考不自动落库。

### 1.7 附带检查 —— 通过

- **speech 包自检生效**：`run_selfcheck("speech")` 通过、`load_pack("speech")` 正常返回六件套；把 speech 的 `admission.yaml` 的 `code:` 改坏后 selfcheck 正确报错（与 motion 同一代码路径，实测）。`CATEGORIES() == ('motion', 'speech')`。
- **ensure_* 幂等**：`ensure_user_tables` / `ensure_flow_tables` / `_ensure_reliability_table` 均为 `CREATE TABLE IF NOT EXISTS`（默认 admin 仅 users 空时插入）；已有测试覆盖重复调用（tests/test_users_db.py `test_ensure_idempotent` 等），本轮全量回归亦复证。

## 2. 发现清单（已修复）

### F1 · P1 安全隐患 · verify_login 时序侧信道可枚举用户名 —— 已修复

- **位置**：`src/users_db.py` `verify_login`
- **问题**：「无此用户」分支不做任何 pbkdf2 计算直接返回 None，响应耗时显著短于「有此用户但密码错」（实测约 0ms vs 31ms）；停用用户也在密码校验**之前**返回。攻击者可用响应时间差枚举有效用户名 —— 与「三种失败不可区分防枚举」的设计意图不符（清单 5c 的信息面已统一，此为时间通道的旁路）。
- **修复**：① 新增模块级哑元哈希 `_TIMING_DUMMY_HASH`（标准存储格式、不对应任何账号），「无此用户」分支同样执行一次等价成本校验（实测 30.9ms vs 30.9ms）；② 判定顺序改为先校验密码、后判 active，停用用户耗时与正常失败一致。返回值语义不变（三种失败仍统一 None），签名不变。

### F2 · P2 风格/卫生 · 新建用户表单清错了 session 键，密码「用完即焚」兜底失效 —— 已修复

- **位置**：`src/users_admin_page.py` `_render_create_user_form`
- **问题**：`st.session_state.pop("users_admin_create_form_password", None)` 弹的是不存在的键；widget 实际 key 为 `users_admin_create_password`，导致注释声明的「密码不常驻会话」兜底在本轮 run 内不生效（clear_on_submit 仍会在下次 rerun 清掉，暴露窗口极小）。
- **修复**：pop 键名改为与 text_input 的 key 一致（`users_admin_create_password`）。

## 3. 发现清单（未修复，遗留观察项）

### F3 · P2 安全隐患 · CSV 导出无公式注入防护 —— 未修（遗留）

- **位置**：`src/reliability.py` `_export_csv`；`src/app.py` `_render_annotation_admin_view` 的标注导出（后者为既有单人流代码）
- **问题**：以 `=`/`+`/`-`/`@` 开头的取值写入 CSV 后，Excel 打开会当公式执行。当前导出内容为枚举/数值（Y/EXT/N、α 值、coder_id），实际风险低；但 `cn_syntax/strategy` 等自由文本若未来进入导出（admin 标注导出已含），风险上升。
- **建议**：写单元格前对上述前缀加 `'` 前缀或空格转义。超出本轮最小修复范围，未改。

### F4 · P2 设计权衡 · 会话内角色为登录时快照 —— 未修（MVP 可接受）

- **位置**：`app.py`（`st.session_state["user"]`）、`users_db.set_role/set_active`
- **问题**：admin 改某用户角色/停用后，该用户**已建立的会话**仍持旧角色直到重新登录（规范 §6-5 明确 MVP 不做 cookie/服务端会话失效）。入口 role gate 本身有效，无提权写路径（提交流 coder_id 恒取自会话）。
- **建议**：后续可在敏感操作前按 user id 回查 `users.role/active`（一次参数化 SELECT）。

### F5 · P2 备忘 · 内置默认口令 admin/admin123 —— 符合规范设计，靠流程约束

- **位置**：`src/users_db.py` `_ensure_default_admin`
- **问题**：bootstrap 口令是公开的（规范 §3 明文规定），代码侧无法区分「首次登录」与「正常登录」来强制改密（需改表结构或加旗标，超出本轮权限）。现有缓解：日志与用户管理页均强提示必须改密；口令字面值只出现在源码常量、不落日志。
- **建议**：上线后由管理员人工确认已改密；或后续加 `must_change_password` 列强制流程。

## 4. 回归验证

- 修复后全量：`python3 -m pytest -q` → **394 passed**（含 users_db 22 项、annotation_flow、reliability、category_pack 等真实 MySQL 集成测试），无回归。
- 本轮新增验证（脚本级，未入套件）：V3 合成用例 9 组、V4 手算 α 5 组 + 库/回退一致性 5 组、V5 坏包 motion/speech 各 1 组、哑元哈希耗时均衡 1 组 —— 全部通过。
