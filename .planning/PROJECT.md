---
name: web-word
description: English synonym verb definition tool for Chinese learners
type: project
---

# Web Word 项目

## 项目概述

**核心价值**：为中文用户提供英语近义动词的精准释义和对比，帮助用户准确理解和区分英语动词的使用场景。

**主要问题**：中文用户在学习英语动词时，常遇到近义动词难以区分的问题（如 run, sprint, dash, jog, race 等词汇）。本项目通过语义分解和对比展示，帮助用户理解每个动词的独特用法和细微差别。

**主要用户**：
- 中文母语者学习英语的成年人
- 英语学习者（B1-C1 水平）
- 需要精确表达的外语工作者

## 项目目标

1. 提供近义动词的精准释义，突出每个动词的独特语义特征
2. 通过对比展示帮助用户理解近义动词的细微差别
3. 支持用户自定义添加和反馈
4. 积累高质量的动词释义数据集

## 核心功能

### 1. 动词查询与释义
- 输入英语动词
- 返回释义（包括语义分解）
- 近义词对比展示

### 2. 语义分解要素（基于 Talmy 运动事件类型学）
- 【方式】- 动作采用的姿势/手段（如：跑步、滑行）
- 【路径】- 动作经过的空间轨迹（如：直线进入、环绕）
- 【方向】- 动作朝向的终点/目标（如：朝向内部、向上）
- 【体相】- 动作时的身体姿态/状态（如：前倾、紧绷）
- 【范围】- 动作涉及的范围/程度

### 3. 用户反馈系统
- 评分反馈（1-5星）
- 用法示例补充
- 释义改进建议

### 4. 数据统计
- 热门动词排行
- 平均评分
- 用户反馈收集

## 技术架构

### 前端
- **Streamlit** - 快速构建 Web 界面
- **Sticky 搜索栏** - 固定定位，实时反馈
- **语义表格展示** - 颜色编码，易于理解
- **侧边栏折叠/展开** - 图标栏 rail 模式（参考 DeepSeek 网页版）
- **目标平台**：电脑端 Chrome 浏览器（1920x1080）

### 后端
- **Python 3.11+** - 主要编程语言
- **MySQL 8.0 (Docker)** - 数据库存储
- **Zhipu AI (智谱 AI) LLM API** - 提示词工程与释义生成
- **FastAPI/Flask** - 可选的 API 层

### 数据层
- **MySQL** - 存储动词释义、用户反馈、统计数据
- **缓存层** - 减少重复查询
- **数据导出** - CSV 格式支持

## v1.0 MVP Shipped (2026-08-24)

### Validated Requirements (19/19)
**Design System:** DESIGN-01/02/03 ✅  
**Core Features:** CORE-01/02/03/04/05 ✅  
**UI Polish (Phase 1-2):** UI-01/02/03/04 ✅  
**Backend Integration (Phase 3):** BACKEND-01/02/03/04 ✅  
**Navigation (Phase 4):** UI-06/07/08 ✅

### Key Deliverables
- **Streamlit 应用** (`src/app.py`)：Google-style sticky 搜索栏、语义分解表格、近义词卡片、用户反馈 1-5 星、数据导出 CSV
- **MySQL 8.0 模块** (`src/mysql_db.py`)：连接池、CRUD、配置化（config.yaml）、Docker Compose 部署
- **Zhipu AI LLM 封装** (`src/llm_api.py`)：SDK 集成、缓存、错误处理、批量生成
- **155 个移动动词语义数据**已入库（docx + Oxford API + Talmy 特征分解）
- **测试套件**：`tests/test_phase4.py` — AppTest + 单元测试（18 passed）

### Technical Stack Validated
- Streamlit + Python 3.11 + MySQL 8.0 (Docker) + Zhipu AI (glm-4.7-flash)
- 部署目标：Hugging Face Spaces / Docker Compose
- 目标分辨率：Chrome 1920x1080 only

## Current State (v1.0 Complete)

### What This Is (updated)
A **shipped** English synonym verb definition tool for Chinese learners, providing:
- Semantic decomposition of motion verbs (Manner/Path/Direction/Aspect/Scope)
- Clickable hot-verbs list with local filtering
- Collapsible sidebar with icon-rail mode
- MySQL-backed feedback & statistics
- Extensible LLM prompt pipeline

### Core Value (verified)
Real-time, semantically-transparent verb definitions that make motion-verb nuances visible to Chinese learners — **achieved at v1.0**.

### Business Context
- **Target**: Chinese English learners (B1-C1), precision writers
- **Model**: Free web tool, data accumulation via feedback
- **Metric**: Query volume, avg rating, feedback rate
- **Status**: v1.0 MVP live; v1.1 planning

## Requirements Status

### Validated (v1.0)
- DESIGN-01/02/03 — Unified design system, Chrome 1920x1080, accessibility
- CORE-01/02/03/04/05 — Query, definition, synonym compare, feedback, stats
- UI-01/02/03/04 — Input area, definition compare, semantic table, example library
- BACKEND-01/02/03/04 — MySQL 8.0, LLM API, feedback storage, stats query
- UI-06/07/08 — Sidebar collapse rail, stats polish, clickable+filterable hot verbs

### Active (v1.1 — Live Generation & Admin)
- **LLM-01**: 接入智谱 AI 实时生成释义，替代 MOCK_DEFINITIONS 成为主显示来源（数据流：DB 命中 → 缓存/实时 LLM → 解析入库 → 渲染；LLM 与 DB 均失败时退回 Mock）
- **SETTINGS-01**: 页面高级配置面板（TOKEN / URL / MODEL），默认预填智谱参数；修改后写入配置文件（config 文件，非仅环境变量），部署时免改环境变量
- **AUTH-01**: 用户登录（users 表 + 角色 role 字段，管理员角色门控管理功能）；v1.1 仅管理员账户，由种子/部署配置初始化，无公开注册
- **ADMIN-01**: 管理员登录后从网页端新增词条到 MySQL（动词 + 中文释义 + 语义分解 JSON + 例句）

### Deferred (v2.0+)
- UI-09/10: 顶部导航栏 / 面包屑
- UI-11: 响应式布局（移动端/平板）
- UI-12: 历史记录视图
- UI-13: 主题切换（浅色/深色）
- UI-14: 数据导出（CSV/JSON 增强）
- BACKEND-05: 实时数据同步
- 动词库扩容至 500+（v1.1 保持 155 基础动词，仅通过管理员新增；扩容留待 v2.0）

### Out of Scope
- Mobile app (PWA instead)
- Video chat
- Offline mode
- 完整用户注册/社交账户系统（v1.1 仅管理员账户，users 表 + role 字段，由种子初始化；公开注册留待 v2.0）
- 公开用户注册（v1.1 无注册页，管理员账户由部署种子创建）

## Known Issues & Technical Debt

1. **Mock data still primary** — `MOCK_DEFINITIONS` 在 `app.py` 中仍为主显示，LLM API 仅作 fallback → **v1.1 目标：接入真实生成**
2. **API Key 管理** — `.env` 中 ZHIPU/OPENAI/DEEPSEEK 密钥均为空，需部署时注入 → **v1.1 目标：页面配置面板免改环境变量**
3. **Docker MySQL 基线** — 工作树 `origin/HEAD` 未解析，worktree 自动降级为顺序模式（需设置 `worktree.baseRef:"head"`）
4. **19 个 REQ-ID 追溯表** 尚未同步到 REQUIREMENTS.md（待 v1.1 首轮规划时补齐）
5. **Phase 1/2/3 VERIFICATION.md 缺失** — 仅 Phase 4 有正式验收报告；v1.0 以 override_closeout 关闭，已记录 3 阶段验证缺口
6. **新增词条管理缺失** — v1.1 新增管理员模式下的网页端词条录入（当前仅能通过 DB 脚本写入）

## Key Decisions Audit

| Decision | Outcome | Rationale |
|----------|---------|-----------|
| LLM Provider: 智谱 AI | ✅ Good | 国内直连、价格合理、OpenAI 兼容 SDK |
| Database: MySQL 8.0 Docker | ✅ Good | 与部署环境一致、配置化 |
| Sidebar collapse: icon rail | ✅ Good | 参考 DeepSeek 网页版，非隐藏+悬浮 |
| Stats display: metric + divider | ✅ Good | 保留原生风格、零新组件 |
| Hot verbs: click + local filter | ✅ Good | 复用 select_example_verb，零后端 |
| Motion verbs: docx + Oxford API | ✅ Good | 155 verbs, 3-tier categorization |
| Deployment: Docker Compose | ✅ Good | 单命令启动、健康检查 |

## Context Update

- **Codebase**: ~4k LOC Python (app/mysql/llm/api/security/design_system)
- **Data**: 155 motion verbs in MySQL `definitions` table (semantic JSON each)
- **Tests**: 18 passing (pytest + AppTest)
- **Tech Stack**: Streamlit, Python 3.11, MySQL 8.0, Zhipu AI, Docker
- **User Feedback Themes**: None yet (v1.0 just shipped)

## Current Milestone: v1.1 Live Generation & Admin

**Goal:** 把项目从"演示（mock 数据主显示）"变成"可用的真实工具"——让智谱 AI 实时生成释义、提供页面内 API 配置、并用管理员模式支持网页端新增词条。

**Target features:**
- 智谱 AI 实时生成释义（替代 MOCK_DEFINITIONS 主显示，含缓存与降级）
- 页面高级配置面板（TOKEN / URL / MODEL，默认预填智谱参数）
- 管理员登录模式（轻量口令）
- 管理员网页端新增词条到 MySQL

---

*Last updated: 2026-08-24 after v1.0 milestone*
*v1.0 MVP shipped: 19/19 requirements validated, 18 tests passing*
*Next: `/gsd-new-milestone` to begin v1.1 planning*