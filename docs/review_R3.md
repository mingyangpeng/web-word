# R3 Review · 集成与回归审查（多人标注系统）

> 审查范围：`src/app.py`（登录/角色分派/新页面集成）、`src/page_guides.py`（页面键）、
> `src/users_admin_page.py`，及其与 `src/users_db.py`、`src/annotation_flow.py`、
> `src/reliability.py` 的接缝。规范：`docs/p1/多人标注系统设计规范.md` §1/§5/§6/§7。
> 前置报告 `docs/review_R1.md`、`docs/review_R2.md` 已通读（F1–F5 不重复报）。
>
> 方法：Streamlit AppTest（streamlit.testing.v1，v1.57.0）无头实测 + 源码走查 +
> git diff AST 级对照（admin 分支 vs 改造前）+ 断库实测（MySQL 指向必然拒绝连接的端口）
> + 转义实测（display_name 注入 `<b>x</b>&跑`）。
>
> **结论：发现 4 处，修复 1 处（另 3 处 P3 观察项），并交付新增集成测试 15 项。
> `python3 -m pytest -q` 417 全绿（原 402 + 新增 15）。**

## 1. 角色 × 页面权限矩阵（AppTest 实测）

实测手段：真实登录表单（填用户名/密码 → 点「登录」提交按钮 → 校验会话）建立会话后逐页断言；
radio 不可达的隐藏页以「残留会话直入」（注入 session user + 直接设 page）模拟强行进入，
验证渲染入口 role gate（规范 §6-4）。可执行断言落在 `tests/test_integration_apptest.py::TestRoleMatrix`。

### 1.1 主区域分派矩阵（九页 × 五身份）

| 页面（键） | 未登录 | annotator | reviewer | admin | viewer |
|---|---|---|---|---|---|
| 🔍 搜索释义（search） | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 |
| 🕸️ 知识图谱（graph） | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 |
| 📊 语料数据集（corpus） | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 |
| 🧭 域系初判（domain） | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 |
| 🏷️ 标注平台（annotate） | ⛔ 请先登录 | ✅ 提交流（**无**仲裁面板、**无** admin 直写表单） | ✅ 提交流＋分歧清单与仲裁面板 | ✅ 快速通道（原单人流直写权威层） | ⛔ 无权限提示 |
| 📥 标注提交（submission） | ⛔ 请先登录 | ✅ 提交流＋我的提交记录（仅本人） | ✅ 提交流＋仲裁面板 | ✅ 提交流＋仲裁面板 | ⛔ 无权限提示 |
| 🏃‍♀️ 范畴深挖（category） | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 | ✅ 可用 |
| 👥 用户管理（users_admin） | ⛔ 请先登录 | ⛔ 仅管理员可用 | ⛔ 仅管理员可用 | ✅ 全部功能 | ⛔ 仅管理员可用 |
| 📐 信度报告（reliability） | ⛔ 请先登录 | ⛔ reviewer/admin 专用 | ✅ 可用 | ✅ 可用 | ⛔ reviewer/admin 专用 |

### 1.2 侧边栏 radio 可见性（_PAGE_ACCESS 过滤实测）

| 身份 | 侧边栏页面选项 |
|---|---|
| 未登录 | 基础六页（search/graph/corpus/domain/annotate/category） |
| annotator | 基础六页 ＋ 📥 标注提交 |
| reviewer | 基础六页 ＋ 📥 标注提交 ＋ 📐 信度报告 |
| admin | 全部九页 |
| viewer | 基础六页（同未登录） |

纵深防御核对：隐藏页即使以残留会话直入，渲染入口 role gate 全部拦下（实测见上表 ⛔ 行）；
annotator 的页面不存在任何他人提交数据入口（`get_submissions_for_sense`/`detect_disagreements`
唯一生产调用点在 `render_reviewer_panel`，其入口 `role not in ("admin","reviewer")` 即 return，
app.py:2618 附近，R1 结论复核成立）。

## 2. 审查清单逐条结论

### 2.1 清单 1 · 角色分派矩阵实测 —— 通过（见 §1）

分派链：`main()` 分派处 `require_login()`（登录门）→ 各页渲染入口 role gate（角色门），
双层判定，实测全部按矩阵生效。admin 在「标注平台」页的快速通道提示（st.info 🛠️）在场，
多人提交流在其「标注提交」页；原快速通道表单保留（见 §2.4）。

### 2.2 清单 2 · 页面键一致性 —— 通过（无死键、无缺键）

程序化核对 + 既有结构锁（tests/test_page_guides.py::test_page_keys_match_app_pages）：

- `PAGE_GUIDES` 九键 = `PAGE_KEYS` = app.py `main()` 分派链的九个分支（含 else→search），
  一一对应；**无定义未分派的死键，无分派未定义的缺键**。
- `_PAGE_ACCESS` 三键（submission/users_admin/reliability）均为真实页面键；
  侧边栏 radio `options=visible_keys` 仍以 `PAGE_KEYS` 遍历过滤为单一事实来源（未硬编码页面清单）。
- 每页 `label/purpose/steps/notes`（及详细版 principle/data_source）齐全；
  `page_label` 对未知键防御性回退原样键。

### 2.3 清单 3 · DB_AVAILABLE=False 全路径 —— 通过（六路径实测优雅降级，零异常）

实测方法：把 `db.MYSQL_PORT` 指向必然 ECONNREFUSED 的端口，AppTest 逐页运行（init_database
3 次重试失败 → DB_AVAILABLE=False）。结果固化在
`tests/test_integration_apptest.py::TestDbUnavailableDegrade`：

| 路径 | 断库行为 | 结论 |
|---|---|---|
| 侧边栏登录框 | st.sidebar.info「登录不可用（数据库离线）」，无输入框 | ✅ |
| 未登录 → 标注/提交/用户管理/信度 | 仍渲染「请先登录」（登录门不依赖数据库状态） | ✅ |
| annotator → 提交流 | st.info「数据库不可用，提交流不可用（离线模式）」 | ✅ |
| annotator/reviewer → 仲裁面板 | st.info「数据库不可用，仲裁面板不可用（离线模式）」 | ✅ |
| admin → 用户管理页 | `list_users()` 捕获连接异常返回 [] → st.info「暂无用户…」 | ✅（文案见 O3） |
| reviewer/admin → 信度页 | `run_reliability` 捕获异常 → db_error → st.error「数据库不可用…」 | ✅ |

`ensure_*` 调用点守卫核对：`ensure_user_tables` 仅在 `DB_AVAILABLE and not _user_tables_ready`
时调用（app.py 启动块）；`_ensure_flow_tables_once` 内部首行 `if not DB_AVAILABLE: return`，
且提交流/仲裁面板均在 DB_AVAILABLE 检查**之后**才调用它 —— 断库时两个 ensure 均不会触达
数据库，实测无异常。

### 2.4 清单 4 · 既有六页回归 —— 通过

- **admin 标注页分支与改造前行为一致**：git diff 提取 HEAD 版 `render_annotation_page`
  与现 `_render_annotation_admin_view` 做 AST 归一化对比（剥离 docstring 后 unparse 全等），
  **除函数名外逐语句一致** —— 原 update_sense_annotation 直写权威层表单/进度/导出全部保留；
  集成仅在外层加了 admin 角色判定与快速通道 st.info。test_pages.py 的
  `test_annotate_page_renders_with_form`（业务库真实数据）复核表单在场。
- **session_state 键冲突**：全仓核对新增键（user/_user_tables_ready/_flow_tables_ready/
  login_username/login_password/logout_button/submission_verb/submission_sense/
  users_admin_create_*/_adjudication_done）与既有键（搜索动词/verb_result/card_expanded/
  corpus_filter/df_*/cs_view 等）无交集；提交流与 admin 快速通道的表单/控件 key 前缀
  （`submission_*`/`ann_form_*`）互不相撞。
- **提交流换词 stale key 实测**：annotator 在提交页切换「选择动词」后 rerun 无
  StreamlitAPIException（selectbox 显式 key 的旧值随选项变更被 Streamlit 1.57 自动重置）。
- **侧边栏折叠模式**：折叠分支（窄图标栏）实测未登录/搜索页、admin/标注页均无异常；
  点 ☰ 展开后登录框/页面 radio 正常出现，page 状态保留。折叠栏本身不承载登录 UI 属
  既有 D-01 设计（见 O1）。
- 既有六页 AppTest 套件（test_pages / test_page_guides / test_phase4 / test_phase5 /
  test_search_bar）全量复跑通过。

### 2.5 清单 5 · AppTest 冒烟 —— 已交付（新增 15 项）

新建 `tests/test_integration_apptest.py`（与现有 AppTest 风格一致；跑独立测试库
`web_word_users_test`，与 test_users_db.py 同一建库手法，无权限/无库则整模块 skip）：

- **真实登录表单冒烟（任务要求的 3 条）**：登录成功 → session user 就位且恰为规范四字段
  `{id, username, display_name, role}`（不含 password_hash）；错误密码 → 无 user ＋ 统一失败
  文案；未登录直入标注页 → 「请先登录」且受保护内容不渲染。
- **角色矩阵**（§1 固化为断言，4 角色 × 9 页）。
- **跨页状态与登出**（§2.6）。
- **断库降级**（§2.3，不依赖数据库，始终可跑）。
- **HTML 转义回归**（§2.7）。

### 2.6 清单 6 · 跨页状态 —— 通过（修复 1 处，见 F1）

- 登录 → 连续切换 corpus/search/annotate：session user 不丢、退出按钮常在（实测）。
- 退出（users_admin 页点「🚪 退出登录」）：**当轮** user 即清除、用户管理内容不再渲染、
  主区域出现「请先登录」，残留页回搜索页（`_visible_page_keys` 重置生效）——受保护页
  立即失效，实测通过。
- 全仓 grep 核对读取 `st.session_state["user"]` 的三个位置（app._current_user、
  users_admin_page._current_user、reliability.render_reliability_page）：前两处有
  isinstance-dict 守卫，reliability 原先没有 —— 已补齐（F1）。
- 角色快照语义（改角色/停用后已建立会话持旧角色）为规范 §6-5 明示的 MVP 取舍，
  R1-F4 已记录，不重复报。

### 2.7 清单 7 · 中文与 HTML 转义 —— 通过（实测）

- 实测账号 display_name=`<b>x</b>&跑`（另测 `管理员<b>甲</b>`、`审核员&乙`、`只读"丁`）：
  登录后侧边栏渲染为 `&lt;b&gt;x&lt;/b&gt;&amp;跑`，**无原文 `<b>` 泄漏**；admin 用户管理
  表格中他人 display_name 同样转义（AppTest 断言固化，R3 清单 7 回归）。
- 走查确认进入 `unsafe_allow_html=True` 的库内/会话文本（角色徽章文字、用户表全列、
  仲裁面板编码人名与取值、LLM 草稿 reason/doubt、范畴包文本、释义/例句、义位英文释义）
  全部过 `_html_escape`；selectbox 选项（_user_options）为纯文本通道无需转义。
- st.success/st.warning 等 Markdown 通道内插值不受 HTML 注入（Streamlit 默认不渲染裸 HTML）。

## 3. 发现清单（已修复）

### F1 · P3 健壮性 · reliability 页读取会话用户缺 isinstance 守卫（三模块接缝口径不一） —— 已修复

- **位置**：`src/reliability.py` `render_reliability_page` 入口。
- **问题**：app.py 与 users_admin_page.py 的 `_current_user()` 均以
  `isinstance(user, dict)` 守卫会话用户（规范 §6-5 会话结构），reliability 原为
  `st.session_state.get("user") or {}` —— 会话 `user` 被写成非 dict 真值时
  `user.get("role")` 抛 AttributeError 整页崩（生产不可达，属接缝口径不一致）。
- **修复**：与另两模块同口径：非 dict 一律按未登录拦截（`user if isinstance(user, dict) else {}`）。
  行为对正常登录/reviewer/admin/annotator 路径零影响，82 项相关测试复跑通过。

## 4. 发现清单（观察项，未修）

### O1 · P3 设计观察 · 折叠侧边栏不承载登录/身份 UI

- **位置**：`src/app.py` `render_sidebar` 折叠分支（D-01 窄图标栏）。
- **现状**：折叠时只有 ☰/📊/🔥/📥 四个图标按钮，登录框、用户徽章与退出按钮都在展开分支。
  折叠态下无法登录/登出/查看身份，需先点 ☰ 展开（实测展开后一切正常，无异常无功能损坏）。
- **建议**：属既有折叠栏交互设计，未改动；如需折叠态快速登出，可在折叠分支加一个
  退出图标按钮（仅已登录时渲染）。

### O2 · P3 信息次序 · 受保护页入口先渲染使用说明再进 role gate

- **位置**：`app.py` 的 `render_users_admin_entry` / `render_reliability_entry` /
  `render_submission_page`（标题+使用说明 expander 在角色判定之前）。
- **现状**：已登录非授权角色强行进入时会看到该页的「📖 使用说明」文档文本，随后才是
  ⛔ 无权限提示。未登录用户在分派处已被 `require_login` 拦下，看不到任何内容；
  泄漏面仅限文档文字，无任何数据。安全边界（函数入口 role gate）本身有效（R1 §1.1）。
- **建议**：如追求零信息暴露，可把 guide 渲染移进各页 role gate 之后的分支；
  需要在入口函数里重复一次角色判定，收益很小，故未改。

### O3 · P3 文案 · 断库时用户管理页提示「暂无用户。请确认数据库已初始化」

- **位置**：`src/users_admin_page.py` `render_users_admin_page`。
- **现状**：`list_users()` 对「库不可用」与「表为空」统一返回 []，页面只能给同一条 info；
  断库时该文案略误导（实测不崩、其余降级正常）。数据层无法区分两态（返回值签名即 []），
  如需区分应由数据层返回哨兵/异常标志，超出本轮最小修复面。

## 5. 交付与回归验证

| 项 | 结果 |
|---|---|
| 新增 `tests/test_integration_apptest.py` | **15 项全过**（真实登录流 3 + 角色矩阵 5 + 跨页/登出 2 + 断库降级 5，另含转义断言） |
| `python3 -m pytest -q` | **417 passed**（原 402 + 新增 15），0 failed |
| flake8（新增测试文件 + 修改的 reliability.py） | **0 违规**（.flake8 max-line-length=100） |
| admin 分支 AST 对照（HEAD vs 现行） | 除函数名外**逐语句一致**（原单人流零污染） |
| 断库实测（端口必拒连接） | 6 路径全部优雅降级，0 异常 |
| 转义实测（display_name=`<b>x</b>&跑` 等含 HTML 特殊字符账号） | 侧边栏/用户表均转义，无原文泄漏 |

## 6. 遗留承接（自 R1/R2，本轮未重复处理）

- R1-F3（CSV 公式注入防护）、R1-F4（会话角色快照）、R1-F5（bootstrap 口令 admin/admin123
  靠流程约束）—— 状态不变，仍为遗留观察项。
- R2 §5 遗留（per_feature 6 位圆整、两侧分歧实现的 bool/int 归一差异、3 处既有 E501）—— 状态不变。
