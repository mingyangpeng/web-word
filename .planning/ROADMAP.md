# Roadmap: Web Word 项目

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-08-24)
- 🚧 **v1.1 Live Generation & Admin** — Phases 5-8 (planning)

---

## v1.0 MVP — SHIPPED 2026-08-24 (archive summary)

**Phases completed:** 4 phases, 5 plans, 8 tasks
**Requirements validated:** 19/19 (DESIGN-01/02/03, CORE-01..05, UI-01/02/03/04, BACKEND-01..04, UI-06/07/08)

**Key deliverables:**
- Streamlit 应用 (`src/app.py`)：sticky 搜索栏、语义分解表、近义词卡片、1-5 星反馈、CSV 导出
- MySQL 8.0 模块 (`src/mysql_db.py`)：连接池、CRUD、config.yaml 配置
- Zhipu AI 封装 (`src/llm_api.py`)：SDK 集成、缓存、错误处理
- 155 个动词语义数据入库；18 个测试通过

---

## v1.1 Live Generation & Admin — ACTIVE

**Goal:** 把项目从「mock 数据演示」变成「可用的真实工具」——智谱 AI 实时生成释义、页面内 API 配置、管理员模式网页端新增词条。

### Phases

- [x] **Phase 5: 实时生成接入 (Live Generation)** - 智谱 AI 成为主显示来源，DB→实时 LLM→解析入库→渲染，Mock 仅作最终降级
- [ ] **Phase 6: 页面配置面板 (Page Configuration)** - 页面内 API TOKEN/URL/MODEL 配置，预填智谱默认，持久化到配置文件
- [ ] **Phase 7: 管理员认证 (Authentication)** - users 表 + role，管理员种子账户，session 登录门控管理功能
- [ ] **Phase 8: 管理员词条录入 (Admin Entry Management)** - 网页端表单新增/更新动词词条到 MySQL，带校验与反馈

---

## Phase Details

### Phase 5: 实时生成接入 (Live Generation)
**Goal**: 用户查询动词时由智谱 AI 实时生成释义替代 MOCK_DEFINITIONS 成为主显示来源，并在 DB 与 LLM 双失败时退回 Mock。
**Depends on**: v1.0 (Phase 3 LLM + MySQL 模块已就绪)
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04
**Success Criteria** (what must be TRUE):
  1. 用户输入动词并搜索时，主显示区展示的内容来自实时生成或 DB 命中，而非 MOCK_DEFINITIONS（Mock 仅在 DB 与 LLM 均失败时作为最终降级出现）
  2. 数据流按「DB 命中 → 实时 LLM 生成 → 解析入库 → 渲染」执行，DB 已有记录时不再调用 LLM，新动词首次查询后写入 MySQL `definitions` 表供后续直接命中
  3. 生成的释义（动词、中文释义、语义分解 JSON、例句、模型版本）成功写入 MySQL `definitions` 表
  4. 当 API 密钥缺失或调用超时/失败时，应用不崩溃，明确提示用户并退回可用数据源（DB 优先，Mock 最终兜底）
**Plans**: 3 plans (05-01 tracer, 05-02 render rewire, 05-03 tests) — all complete 2026-09-15 (28 tests passing)
**UI hint**: yes

### Phase 6: 页面配置面板 (Page Configuration)
**Goal**: 在页面内提供高级配置面板，可修改 API TOKEN/URL/MODEL，预填智谱默认值，并将修改持久化到配置文件。
**Depends on**: Phase 5 (配置供 LLM 调用使用)
**Requirements**: SETTINGS-01, SETTINGS-02, SETTINGS-03
**Success Criteria** (what must be TRUE):
  1. 页面提供高级配置面板，用户可修改 API TOKEN、URL、MODEL 三项参数
  2. 配置面板默认预填智谱参数（默认 TOKEN 占位、URL、glm-4.7-flash 等），部署时无需修改环境变量即可运行
  3. 修改配置后写入配置文件（如 `config/llm_config.yaml` 的 `llm` 段），重启应用后保持生效，而非仅会话内环境变量
**Plans**: TBD
**UI hint**: yes

### Phase 7: 管理员认证 (Authentication)
**Goal**: 支持用户登录（users 表 + role 字段），管理员账户由种子/初始化创建，未登录访问管理功能时跳转登录。
**Depends on**: Phase 5/6 (管理功能需认证后使用)
**Requirements**: AUTH-01, AUTH-02, AUTH-03
**Success Criteria** (what must be TRUE):
  1. 系统支持用户登录（基于 `users` 表 + `role` 字段），管理员角色可门控管理功能访问
  2. v1.1 仅存在管理员账户，由部署种子/初始化脚本创建，无公开注册入口
  3. 登录状态通过 session 管理，未登录用户访问管理功能时跳转到登录界面
**Plans**: TBD
**UI hint**: yes

### Phase 8: 管理员词条录入 (Admin Entry Management)
**Goal**: 管理员登录后可在网页端新增或更新动词词条到 MySQL，含字段校验与成功反馈。
**Depends on**: Phase 7 (需管理员登录)
**Requirements**: ADMIN-01, ADMIN-02, ADMIN-03
**Success Criteria** (what must be TRUE):
  1. 管理员登录后可在网页端表单新增词条（动词 + 中文释义 + 语义分解 JSON + 例句）到 MySQL
  2. 提交时校验必要字段（动词非空、语义分解为合法 JSON），重复动词执行更新而非报错
  3. 新增/更新成功后前端给出明确反馈，且可立即查询到该词条
**Plans**: TBD
**UI hint**: yes

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 5. 实时生成接入 | 3/3 | Complete | 2026-09-15 |
| 6. 页面配置面板 | 0/0 | Not started | - |
| 7. 管理员认证 | 0/0 | Not started | - |
| 8. 管理员词条录入 | 0/0 | Not started | - |

---

*Roadmap updated: 2026-08-24 — v1.1 milestone active, 13 requirements mapped across Phases 5-8*
