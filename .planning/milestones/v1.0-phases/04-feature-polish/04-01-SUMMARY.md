---
phase: 04-feature-polish
plan: 01
title: 侧边栏折叠图标栏 + 统计微调 + 热门动词交互
one_liner: 在已集成 MySQL 后端之上收尾三项导航 UI 打磨（UI-06/07/08），纯前端改动单集成点 render_sidebar()。
duration: 2026-08-24
tasks:
  - Task 1 (UI-06): 侧边栏折叠/展开图标栏端到端打通
  - Task 2 (UI-07): 统计显示间距/标题层级/分隔微调
  - Task 3 (UI-08): 热门动词可点击 + 本地筛选
key_files_modified:
  - src/app.py
  - tests/test_phase4.py
requirements_completed:
  - UI-06
  - UI-07
  - UI-08
coverage:
  automated:
    - "tests/test_phase4.py::test_sidebar_flag — sidebar_collapsed 默认 False 且存在"
    - "tests/test_phase4.py::test_collapse_toggle — 折叠态 ☰ 图标栏 / 展开态 ◀ 折叠按钮"
    - "tests/test_phase4.py::test_stats_section — 实验统计标题 + 分隔线已渲染"
    - "tests/test_phase4.py::test_filter_hot_verbs — 前端子串过滤单元断言"
  result: "4 passed (pytest exit 0)"
deviations:
  - "AppTest 因 components.html 固定 JS 注入导致默认 3s 超时，测试中 run(timeout=30) 显式放宽；不影响运行时行为。"
  - "折叠/展开按钮的 on_click 使用 lambda 写入 session_state.__setitem__，等价于设置 sidebar_collapsed 标志，无新增持久化逻辑（符合 D-02 不跨刷新持久化）。"
  - "无偏离计划功能点：未引入卡片组件（D-03）、未引入浮动/隐藏元素（D-01）、未新增后端调用或语义模型改动。"
---

## 完成说明

Phase 4 剩余三项 UI 打磨全部完成并通过回归测试。所有改动集中在 `render_sidebar` 单一集成点（`main()` 仅一处调用），未触碰后端、API 或语义分解模型。

- **UI-06**：侧边栏支持折叠为窄图标栏（☰/📊/🔥/📥，含 `help=` hover 提示），点击任一图标展开回完整宽度；默认展开态由 `sidebar_collapsed` 标志控制（源于 `initial_sidebar_state="expanded"`，无跨刷新持久化）。
- **UI-07**：统计区保留原生 `st.sidebar.metric` 风格，主标题用 `HEADER_H2`、区块标题用 `HEADER_H3`，区块间插入 `st.sidebar.divider()`，未引入任何卡片组件。
- **UI-08**：热门动词列表改为可点击按钮（复用 `select_example_verb` 填充搜索框并触发 `search_verb`），列表上方新增本地筛选输入框 `hot_filter`，经 `filter_hot_verbs()` 纯前端子串过滤，无后端往返；空数据时仍走 `info` 分支不渲染筛选与按钮。
