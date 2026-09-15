---
phase: 05-live-generation
plan: 03
subsystem: testing
tags: [pytest, streamlit-apptest, monkeypatch, adapter-contract, coverage]

# Dependency graph
requires:
  - phase: 05-live-generation
    provides: get_display_definition adapter (05-01) and adapter-only render layer (05-02)
provides:
  - tests/test_phase5.py — 10 tests locking the adapter contract (priority/persistence/degradation/validation) and the AppTest load+render smoke path
  - An autouse fixture that turns un-mocked external calls into hard failures, so no test can silently hit Zhipu AI or MySQL
affects: [phase-06-config-panel, phase-07-auth, phase-08-admin-entry]

# Actuals (#2632)
actuals:
  tokens: 2384           # ~9536 diff chars / 4 over the realized test-file + fix diff
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-closed test isolation: autouse fixture patches every external seam to raise AssertionError, each test re-patches only what it needs"
    - "AppTest smoke assertions on element-list content (at.markdown) rather than screenshots, for adapter-driven render regressions"

key-files:
  created:
    - tests/test_phase5.py
  modified:
    - src/app.py

key-decisions:
  - "autouse _no_external_io fixture 使「忘记 patch」变成显式失败，而不是静默触网/连库（测试可在离线 CI 跑）"
  - "补一条 legacy 行用例（chinese_ndef 为纯文本）覆盖 _restore_trad_opt 的向后兼容分支"
  - "补一条非法输入用例，验证 InputValidator 在适配器入口拦截 SQL/XSS 且不进入 LLM 调用（T-05-01）"
  - "AppTest 暴露的 st.button(**CSS字符串) TypeError 按最小修复处理：只去掉错误的 ** 展开，不改布局/不接回 MOCK"

patterns-established:
  - "Plan-level verification gate: 每个 plan 的 <verify> 断言在提交前实跑，发现的运行期缺陷即刻修复并单独提交"

requirements-completed:
  - LLM-01
  - LLM-02
  - LLM-03
  - LLM-04

coverage:
  - id: D1
    description: "测试覆盖适配器优先级 DB→LLM→MOCK→fallback，且 DB 命中时不触发 LLM 调用"
    requirement: LLM-02
    verification:
      - kind: unit
        ref: "tests/test_phase5.py::test_adapter_db_branch, ::test_adapter_mock_fallback, ::test_adapter_final_fallback"
        status: pass
    human_judgment: false
  - id: D2
    description: "LLM 成功结果按契约持久化：chinese_ndef 为 combined JSON、semantic_table 为 dict"
    requirement: LLM-03
    verification:
      - kind: unit
        ref: "tests/test_phase5.py::test_adapter_llm_persist"
        status: pass
    human_judgment: false
  - id: D3
    description: "LLM 异常/密钥缺失时不崩溃并降级；非法输入被拦截且不进 LLM"
    requirement: LLM-04
    verification:
      - kind: unit
        ref: "tests/test_phase5.py::test_adapter_no_crash_on_llm_exception, ::test_adapter_rejects_illegal_input"
        status: pass
    human_judgment: false
  - id: D4
    description: "LLM 响应解析映射 traditional/optimized 且保留 chinese_ndef（契约扩展回归保护）"
    requirement: LLM-01
    verification:
      - kind: unit
        ref: "tests/test_phase5.py::test_parse_maps_traditional_optimized"
        status: pass
    human_judgment: false
  - id: D5
    description: "应用加载无异常，且展示态下四卡结果区成功渲染（不再依赖 MOCK 硬编码）"
    requirement: LLM-01
    verification:
      - kind: integration
        ref: "tests/test_phase5.py::test_app_loads, ::test_result_render_no_mock_hardcode (AppTest)"
        status: pass
      - kind: automated_ui
        ref: "python -m pytest -q -> 28 passed（含既有 18 个回归用例）"
        status: pass
    human_judgment: false
  - id: D6
    description: "真实智谱 AI 调用与 MySQL 持久化端到端成功（非 mock）"
    requirement: LLM-03
    verification: []
    human_judgment: true
    rationale: "本机无 ZHIPUAI_API_KEY、MySQL 容器未启动，所有用例均为契约级隔离测试；真实链路需带密钥且有库的环境人工跑一次查询。"

# Metrics
duration: 7min
completed: 2026-09-15
status: complete
---

# Phase 5 Plan 03: 全链路自动化测试 (Phase 5 Tests) Summary

**用 10 个隔离测试把「DB→实时 LLM→MOCK→fallback」优先级、持久化契约与降级不崩溃钉死，并顺手抓出并修掉一个此前会让结果区渲染直接崩溃的 st.button 参数错误。**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-09-15T20:35Z
- **Completed:** 2026-09-15T20:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 新增 `tests/test_phase5.py`（10 个用例）：适配器 DB 优先且不触发 LLM、历史纯文本行兼容、LLM 结果持久化契约（combined `chinese_ndef` JSON + dict 型 `semantic_table`）、MOCK 降级、最终兜底、LLM 异常不崩溃、非法输入拦截、解析契约回归、AppTest 加载与四卡渲染冒烟。
- autouse `_no_external_io` fixture 把所有外部接缝（`mysql_db.get_definition_by_verb` / `insert_definition`、`llm_api.get_definition`）替换为抛 `AssertionError`，任何遗漏的 patch 都会立刻显式失败，测试在离线环境可确定性通过。
- AppTest 首次真正渲染结果区，暴露 `st.button("📤 提交反馈", type="primary", **get_button_primary_style())` —— 该 helper 返回 CSS 字符串而非 kwargs，展开后抛 `TypeError`，导致「有搜索结果」的展示态整体渲染失败。按最小修复去掉错误展开并单独提交，未触碰四卡布局、未接回 MOCK。
- 全量套件 28 passed（既有 18 个 v1.0 回归用例 + 新增 10 个），`flake8` 对 `tests/test_phase5.py` 零告警。

## Task Commits

Each task was committed atomically:

1. **Task 1: 单元测试 — 适配器契约与优先级** - `8186a3a` (test)
2. **Task 2: 集成测试 — AppTest 加载与四卡渲染** - `2f87e17` (test)

**Auto-fixed during Task 2:** `e45b134` (fix: stop spreading CSS string into st.button kwargs)

## Files Created/Modified

- `tests/test_phase5.py` - 新增；适配器契约单元测试 8 个 + AppTest 集成测试 2 个（256 行）。
- `src/app.py` - 仅修正反馈提交按钮的 `**get_button_primary_style()` 误用（1 行 + 注释）。

## Decisions Made

- 测试隔离采取「fail-closed」：默认全部外部依赖不可达，用例按需覆盖，比逐用例显式 patch 更能防止未来新增分支静默触网。
- 覆盖范围按 plan 指定扩展了两条 plan 未列出但契约关键的用例：legacy `chinese_ndef` 纯文本行（保护 DB 回读向后兼容）与非法输入拦截（T-05-01 安全缓解的回归保护）。
- `st.button` 修复只改参数传递方式：`type="primary"` 已能表达主按钮语义，主色由 Streamlit 主题提供；不为此引入新的样式注入机制（避免超出本 plan 范围）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] st.button 展开 CSS 字符串导致结果区渲染 TypeError**
- **Found during:** Task 2（AppTest 展示态渲染）
- **Issue:** `src/app.py:1104` 以 `**get_button_primary_style()` 传参，而该 helper 返回的是 CSS 声明字符串（`design_system.py:85`），`**` 展开直接抛 `TypeError: argument after ** must be a mapping, not str`；由于 AppTest 此前从未进入 `show_result=True` 分支，该缺陷在 v1.0 验收与既有 18 个测试中一直未被发现。
- **Fix:** 改为 `st.button("📤 提交反馈", type="primary")`，并加注释说明为何不能展开。
- **Files modified:** `src/app.py`
- **Verification:** `tests/test_phase5.py::test_result_render_no_mock_hardcode` 通过（`at.exception == []`）；全量 28 passed。
- **Committed in:** `e45b134`

---

**Total deviations:** 1 auto-fixed（1 bug）
**Impact on plan:** 该缺陷属于本 plan 明确要求修复的类别（「若 AppTest 暴露应用运行期问题，按需最小修复」），且未引入 MOCK 回退、未改布局。无范围蔓延。

## Issues Encountered

- 集成用例断言最初失败于 `at.exception != []`。定位为上述 `st.button` 缺陷（此前从未有任何测试进入展示态），修复后转绿。
- AppTest 运行于无 MySQL / 无 `ZHIPUAI_API_KEY` 环境，日志中会出现连接失败与客户端不可用的 ERROR —— 属预期降级噪声，断言不受影响。

## User Setup Required

None - 测试完全隔离，不需要智谱密钥或运行中的 MySQL。

## Next Phase Readiness

- Phase 5 全部 3 个 plan 已执行完毕，LLM-01..04 的行为已由 10 个隔离测试锁定。
- Phase 6（页面配置面板）可安全改动 LLM 调用参数：`test_adapter_llm_persist` 会保护持久化契约，`test_result_render_no_mock_hardcode` 会保护渲染链路。
- 遗留人工验收项：带真实 `ZHIPUAI_API_KEY` 与 MySQL 的环境各跑一次新动词查询，确认实时生成→入库→二次命中；以及 1920×1080 下的四卡视觉确认。

---
*Phase: 05-live-generation*
*Completed: 2026-09-15*
