# R0 集成报告（Agent E）：四人模块集成接线到 Streamlit 主应用

> 日期：2026-11-06 · 依据唯一事实源：`docs/p1/多人标注系统设计规范.md`（§3 模块契约、§5 UI 集成契约、§6 安全规则、验收 V1/V2/V3/V7）
> 改动文件：`src/app.py`、`src/page_guides.py`、`tests/test_page_guides.py`、`tests/test_pages.py`（受影响的既有测试修复到绿 + 新页用例）
> 未改动：`src/users_db.py`、`src/annotation_flow.py`、`src/reliability.py`、`src/category_pack.py`（四模块签名与实现零改动）

## 1. 改动点

### 1.1 src/app.py（集成主体）

| # | 改动 | 说明 |
|---|---|---|
| 1 | **登录态启动初始化** | `DB_AVAILABLE=True` 时调用 `ensure_user_tables()`（幂等建 users 表 + 内置 admin），以 `session_state["_user_tables_ready"]` 旗标每会话只跑一次；失败只记日志不崩 |
| 2 | **侧边栏登录区** `_render_login_section()` | 位于侧边栏顶部、页面切换 radio 之前。未登录：登录表单（`st.form` + `clear_on_submit`，密码不常驻会话），成功写 `st.session_state["user"]={id,username,display_name,role}` 后 `st.rerun()`，失败 `st.error`；已登录：display_name + 角色徽章（HTML 已转义）+ 退出按钮（`_logout` 清除会话用户）。`DB_AVAILABLE=False` 显示 info「登录不可用（数据库离线）」不崩溃 |
| 3 | **权限 helper** | `require_login() -> dict|None`（未登录渲染 st.warning「请先登录」并返回 None）、`_current_user()`、`_logout()`、`_visible_page_keys(role)`（角色可见性过滤）、`_ensure_flow_tables_once()`（首次访问提交流/仲裁面板时幂等建 annotation_submissions 等三表，无需手跑迁移） |
| 4 | **页面 radio 角色可见性** | 选项仍来自 `PAGE_KEYS`（单一事实来源，未硬编码），经 `_PAGE_ACCESS` 过滤子集；残留页（登出/换角色后当前页不在可见集合）重置回 search，避免 radio 抛 StreamlitAPIException |
| 5 | **main() 分派链** | `_page` 在 `render_sidebar()` 之前取值（侧边栏的重置只影响下一轮），新增 submission / users_admin / reliability 三个分支；标注页 + 新三页统一过 `require_login()` 登录门（渲染入口再判角色门，纵深防御） |
| 6 | **标注页角色分派** `render_annotation_page()` | admin → 顶部「快速通道：直写权威层；多人提交流见『📥 标注提交』页」提示 + 原有全部功能原样保留（原函数体整体更名为 `_render_annotation_admin_view()`，内部逻辑零改动）；annotator/reviewer → 新提交流 `render_submission_flow()`，reviewer 额外渲染 `render_reviewer_panel()`；viewer → 无权限警告 |
| 7 | **新视图 `render_submission_flow()`** | 选动词（`get_annotation_progress`）→ 选义位（`get_oald_senses`，状态徽章简化复用）→ **V7：LLM 初筛草稿可见**（llm_tag/llm_schema/llm_align/llm_reason/llm_doubt）→ configs/motion 准入标准只读面板（`load_pack("motion")`，失败降级 caption）→ 表单（准入 Y/EXT/N、图式、对齐、汉语句法、译义策略、存疑勾选；预填优先级=本人上次提交>LLM 草稿>空）→ `submit_annotation(category="motion", task_type="admission", coder_id=user.id, payload)` → 成功提示；附「我的提交记录」（`get_my_submissions`，st.dataframe）。**annotator 全程无任何他人数据入口**（§0 独立性）；留空可选字段不入 payload（缺失≠空串，不污染分歧比对） |
| 8 | **新视图 `render_reviewer_panel()`** | 入口 role gate（仅 reviewer/admin）；`detect_disagreements("motion","admission")` 逐条展示（各编码人取值对照，coder_id→显示名经 `list_users`）；每条分歧 gold 表单（准入/图式/对齐/仍存疑/note）→ `save_adjudication`（submission_ids 取自 `get_submissions_for_sense`），成功置会话旗标后 rerun（提示跨 rerun 展示）；附 `get_assignment_stats` 进度概览 |
| 9 | **新页面** `render_submission_page()` / `render_users_admin_entry()` / `render_reliability_entry()` | submission：h1+说明+viewer 拦截+提交流（reviewer/admin 加仲裁面板）；users_admin / reliability：使用说明 + 调 Agent A/C 的页面函数（其函数入口自带 role gate） |

### 1.2 src/page_guides.py（小改）

- `PAGE_GUIDES` 新增三键：**`submission`（📥 标注提交）**、**`users_admin`（👥 用户管理）**、**`reliability`（📐 信度报告）**，各含 label/purpose/principle/data_source/steps/notes（覆盖覆盖更新语义、独立性、AI-assisted IAA 口径、角色语义、自保护、pbkdf2 口径等）。
- `PAGE_KEYS` 顺序变为：search, graph, corpus, domain, annotate, **submission**, category, **users_admin**, **reliability**。

### 1.3 受影响测试的修复（非功能性）

- `tests/test_page_guides.py`：APP_PAGES/锚点/标签 emoji/键序断言纳入三新页；渲染锁对有角色门的页面注入 `_SESSION_USERS` 会话用户（§6-5 会话结构，不要求库中存在该账号）；radio 源码断言更新为「经 `_visible_page_keys` 过滤、仍以 PAGE_KEYS 为基准」。
- `tests/test_pages.py`：`test_annotate_page_renders_with_form` 注入 admin 会话（页面有登录门）；新增 11 个用例（见 §4）。

## 2. 新增页面

| 页面键 | 标签 | 可见角色 | 入口 | 说明 |
|---|---|---|---|---|
| `submission` | 📥 标注提交 | admin / reviewer / annotator | `render_submission_page()` | 多人提交流；annotator 仅见自己的提交；reviewer/admin 额外见分歧清单与仲裁面板 |
| `users_admin` | 👥 用户管理 | admin | `render_users_admin_entry()` → `users_admin_page.render_users_admin_page()` | 页面函数入口自带 admin gate（未登录「请先登录」、非 admin「仅管理员可用」） |
| `reliability` | 📐 信度报告 | admin / reviewer | `render_reliability_entry()` → `reliability.render_reliability_page()` | 页面函数入口自带 reviewer/admin gate；AI-assisted IAA 口径 |

## 3. 权限矩阵

| 页面 | 未登录 | viewer | annotator | reviewer | admin |
|---|---|---|---|---|---|
| search/graph/corpus/domain/category | ✅ | ✅ | ✅ | ✅ | ✅ |
| annotate（标注平台） | ⚠️ 请先登录（main 分派门） | ⚠️ 无权限 | ✅ 提交流 | ✅ 提交流+仲裁面板 | ✅ 快速通道（直写权威层）+ 顶部提示 |
| submission（标注提交） | ⚠️ 请先登录 | ⚠️ 无权限 | ✅ 仅自己的提交 | ✅ +分歧/仲裁 | ✅ +分歧/仲裁 |
| users_admin | ⚠️ 请先登录 | 隐藏→进入报⛔ | 隐藏→进入报⛔ | 隐藏→进入报⛔ | ✅ |
| reliability | ⚠️ 请先登录 | 隐藏→入口⚠️ | 隐藏→入口⚠️ | ✅ | ✅ |
| 侧边栏 | 登录表单 | 六页 | 七页（+提交） | 八页（+提交+信度） | 九页 |

- 权限判定全部在渲染入口（§6-4）：main() 分派处登录门 → 页面函数入口角色门；不依赖侧边栏隐藏。
- 安全：所有用户生成内容进 HTML 前过 `_html_escape`；SQL 全部来自四模块参数化查询（app.py 无原生 SQL）；密码不回显、表单 clear_on_submit；会话仅 `st.session_state["user"]`，登出清除。

## 4. 测试结果

- **全量 pytest：394 passed**（基线 380 passed，无回归；+14 为新页/权限门用例）：
  - `test_pages.py` 新增：标注页未登录警告 / viewer 无权限 / annotator 提交流 / reviewer 仲裁面板；提交页未登录 / annotator 渲染（且无仲裁面板）/ reviewer 渲染；用户管理双门 / admin 渲染；信度页 annotator 拦截 / reviewer 渲染。
  - `test_page_guides.py`：三新页说明结构锁 + AppTest 渲染锁（注入相应角色）。
- **import 冒烟**：`python3 -c "import src.app"` 无报错。
- **端到端验证**（临时脚本、真实 MySQL，验证后已清理合成数据行并停用验证账号）：
  1. 内置 admin `verify_login` 成功/失败路径 ✓；
  2. annotator A/B 经 UI 表单提交同一义位（Y vs N）→ `annotation_submissions` 两行 ✓；
  3. `detect_disagreements` 命中该义位（验收 V3）✓；
  4. reviewer 仲裁定稿 gold=Y → 两提交置 `adjudicated`、退出分歧清单 ✓；
  5. A 同义位再次提交 EXT → 单行覆盖、status 重置 `submitted`（验收 V2）✓；
  6. V7：annotator 提交流可见 LLM 初筛草稿 ✓；
  7. 登录 UI 全流程（失败报错 / 成功后 radio 九页 / 登出回六页）与各角色 radio 可见性 ✓；
  8. 离线模式（MySQL 不可达）：登录区显示「登录不可用（数据库离线）」，search/submission/users_admin/reliability 四页均无异常 ✓。

## 5. 发现的问题（按约束未改动，仅记录）

1. **`src/users_admin_page.py` `_render_create_user_form` 清密码的键名不一致（轻微）**：表单控件 key 为 `users_admin_create_password`，但提交后清除的是 `st.session_state.pop("users_admin_create_form_password", None)`——键名错位导致该兜底清除实际未生效。实际风险≈0（表单 `clear_on_submit=True` 已清控件状态），但兜底代码失效属实。建议后续改为 pop 正确的 key。
2. **`users_db.set_role/set_active` 对「目标值与现值相同」返回 False**（MySQL rowcount=0），页面会显示「修改失败：…角色未变化…」——语义已在 docstring 声明、页面文案也已覆盖「未变化」情形，属设计取舍非缺陷。
3. **e2e 过程中发现的集成自身问题（已修复）**：仲裁成功后直接 `st.success` + `st.rerun()` 会丢弃成功提示（rerun 作废当前 run 输出）——改为会话旗标 `_adjudication_done` 跨 rerun 展示。

## 6. 遗留说明

- 验证用账号 `agentE_e2e_*`（users id 2–13）已全部 `active=0` 停用（不物理删除，保留 FK 引用完整性）；其合成 submission/adjudication 行已删除，不影响生产数据口径。
- 内置默认 admin（admin/admin123）为公开 bootstrap 凭据，首次登录后应立即修改密码（用户管理页安全提示已有说明；改密功能属后续个人设置页范围，本次任务不含）。
