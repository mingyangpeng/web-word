# v1.1 Requirements

**Milestone:** v1.1 - Live Generation & Admin
**Created:** 2026-08-24
**Core Value:** 为中文用户提供英语近义动词的精准释义和对比

---

## v1.1 Requirements

These turn the app from a mock-data demo into a working tool: live generation, page-level
API configuration, and an admin mode for web-based entry addition.

### Live Generation (LLM)

- [x] **LLM-01**: 用户查询动词时，应用调用智谱 AI 实时生成释义（含语义分解表），替代 MOCK_DEFINITIONS 成为主显示来源
- [x] **LLM-02**: 数据流为「DB 命中 → 实时 LLM 生成 → 解析入库 → 渲染」；LLM 与 DB 均失败时退回 Mock 数据作为最终降级
- [x] **LLM-03**: 生成的释义（动词、中文释义、语义分解 JSON、例句、模型版本）写入 MySQL `definitions` 表，供后续查询直接命中
- [x] **LLM-04**: LLM 调用具备错误处理与超时降级，API 密钥缺失/失效时不崩溃，明确提示并退回可用数据源

### Page Configuration (SETTINGS)

- [ ] **SETTINGS-01**: 页面提供高级配置面板，可修改 API TOKEN / URL / MODEL 三项
- [ ] **SETTINGS-02**: 配置面板默认预填智谱参数（默认 TOKEN/URL/glm-4.7-flash），部署时无需修改环境变量即可运行
- [ ] **SETTINGS-03**: 配置修改后持久化写入配置文件（config 文件），非仅会话内环境变量，重启后保持

### Authentication (AUTH)

- [ ] **AUTH-01**: 系统支持用户登录（users 表 + 角色 role 字段），管理员角色门控管理功能
- [ ] **AUTH-02**: v1.1 仅管理员账户，由部署种子/初始化配置创建，无公开注册页
- [ ] **AUTH-03**: 登录状态通过 session 管理，未登录访问管理功能时跳转登录

### Admin Entry Management (ADMIN)

- [ ] **ADMIN-01**: 管理员登录后可在网页端新增词条到 MySQL（动词 + 中文释义 + 语义分解 JSON + 例句）
- [ ] **ADMIN-02**: 新增词条时校验必要字段（动词非空、语义分解为合法 JSON），重复动词执行更新而非报错
- [ ] **ADMIN-03**: 新增词条成功后在前端给出明确反馈，并可立即查询到该词条

---

## v1.0 Validated (locked — reference only)

Design: DESIGN-01/02/03 · Core: CORE-01..05 · UI: UI-01..04, UI-06/07/08 · Backend: BACKEND-01..04
(19/19 已验证，详见 PROJECT.md)

## Deferred to v2.0+

| Feature | Reason |
|---------|--------|
| 顶部导航栏 / 面包屑 (UI-09/10) | 非核心，留待体验增强里程碑 |
| 响应式布局 / 移动端适配 (UI-11) | 目标平台仍为桌面 Chrome，移动端延后 |
| 历史记录视图 (UI-12) | 依赖用户系统，v2.0 用户体系完善后做 |
| 主题切换 (UI-13) | 非核心 |
| 数据导出增强 CSV/JSON (UI-14) | 当前已有 CSV 导出，增强延后 |
| 实时数据同步 (BACKEND-05) | 非核心 |
| 动词库扩容至 500+ | v1.1 保持 155 基础动词，仅通过管理员新增；扩容留 v2.0 |
| 公开用户注册 | v1.1 仅管理员账户 |

## Out of Scope

- Mobile app (PWA instead)
- Video chat
- Offline mode

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LLM-01 | Phase 5 | Complete |
| LLM-02 | Phase 5 | Complete |
| LLM-03 | Phase 5 | Complete |
| LLM-04 | Phase 5 | Complete |
| SETTINGS-01 | Phase 6 | Pending |
| SETTINGS-02 | Phase 6 | Pending |
| SETTINGS-03 | Phase 6 | Pending |
| AUTH-01 | Phase 7 | Pending |
| AUTH-02 | Phase 7 | Pending |
| AUTH-03 | Phase 7 | Pending |
| ADMIN-01 | Phase 8 | Pending |
| ADMIN-02 | Phase 8 | Pending |
| ADMIN-03 | Phase 8 | Pending |

**Coverage:**
- v1.1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---

*Created: 2026-08-24 — v1.1 starts after v1.0 MVP shipped (19/19 requirements validated)*
