---
phase: 05-live-generation
plan: 02
subsystem: ui
tags: [streamlit, adapter, render-rewire, mock-demotion, semantic-decomposition]

# Dependency graph
requires:
  - phase: 05-live-generation
    provides: get_display_definition(verb) unified adapter + get_semantic_table_for_verb rewired to it (05-01)
provides:
  - All four render cards and the main result area consume the adapter; no render site reads MOCK_DEFINITIONS
  - "MOCK_DEFINITIONS references collapsed to its definition site + the adapter's lowest-priority fallback"
affects: [05-03-tests, phase-06-config-panel]

# Actuals (#2632)
actuals:
  tokens: 610            # ~2439 diff chars / 4 over the realized src/app.py diff
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Adapter-only rendering: every render_card_* reads get_display_definition / its helper, never a module-level data literal"
    - "Shape adapter at the boundary: get_semantic_table_for_verb converts the semantic dict into the 5-row list the HTML renderer unpacks"

key-files:
  created: []
  modified:
    - src/app.py

key-decisions:
  - "render_card_anchor keeps its existing list-of-lists unpacking (semantic_type, emoji, description); the conversion stays in get_semantic_table_for_verb so the HTML template is untouched (T-05-04 mitigation)"
  - "render_card_prototype already went through the adapter via get_semantic_table_for_verb in 05-01 — only a documentation comment was added, no behaviour change"
  - "Main-area MOCK branch deleted as dead code: it recomputed traditional/optimized that were never read, since rendering flows through the four card functions"

patterns-established:
  - "Demote a hardcoded data source by routing every consumer through one adapter instead of deleting the literal — keeps the offline fallback intact"

requirements-completed:
  - LLM-01
  - LLM-02
  - LLM-03
  - LLM-04

coverage:
  - id: D1
    description: "render_card_prototype / render_card_anchor render from the adapter; no MOCK_DEFINITIONS reference remains in either function"
    requirement: LLM-01
    verification:
      - kind: unit
        ref: "python -c \"...assert 'MOCK_DEFINITIONS' not in s[s.find('def render_card_prototype'):s.find('def render_card_core')]; st=get_semantic_table_for_verb('跑进来'); assert isinstance(st,list) and len(st)==5 and len(st[0])==3\" -> RENDER_12_OK"
        status: pass
    human_judgment: false
  - id: D2
    description: "render_card_core shows traditional + optimized sourced from get_display_definition; main-area MOCK/通用示例 branch removed"
    requirement: LLM-01
    verification:
      - kind: unit
        ref: "python -c \"...core=...; assert 'MOCK_DEFINITIONS' not in core; main=...; assert 'MOCK_DEFINITIONS' not in main and '通用示例' not in main; html=render_card_core('跑进来'); assert '传统释义' in html and '优化释义' in html\" -> RENDER_34_OK"
        status: pass
    human_judgment: false
  - id: D3
    description: "MOCK_DEFINITIONS全文件引用收敛：仅剩定义处（L659）与适配器降级分支（L572-573）"
    requirement: LLM-02
    verification:
      - kind: unit
        ref: "grep -n MOCK_DEFINITIONS src/app.py -> lines 447,451,503 (docstrings), 572,573 (adapter fallback), 659 (definition), 1253 (legacy note)"
        status: pass
    human_judgment: false
  - id: D4
    description: "四卡布局与视觉不变，结果区可在无 DB/无 LLM 的离线环境下正常渲染（降级路径）"
    requirement: LLM-04
    verification:
      - kind: integration
        ref: "tests/test_phase5.py::test_result_render_no_mock_hardcode (AppTest, show_result=True)"
        status: pass
    human_judgment: true
    rationale: "像素级视觉一致性（卡片间距、配色、emoji 呈现）需人在浏览器 1920x1080 下目视确认；自动化只能断言卡片标题与无异常。"

# Metrics
duration: 6min
completed: 2026-09-15
status: complete
---

# Phase 5 Plan 02: 渲染层改接统一适配器 (Render Rewire) Summary

**四个渲染卡片的主结果区不再读硬编码 MOCK —— 全部经由 get_display_definition 适配器取数，Mock 收敛为适配器内的最低优先级降级源。**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-09-15T20:31Z
- **Completed:** 2026-09-15T20:34Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- `render_card_anchor` 不再直接读 `MOCK_DEFINITIONS` 的 list-of-lists，改由 `get_semantic_table_for_verb` 提供语义表（该 helper 内部已走统一适配器，并负责 dict → 5 行 `[[类型, emoji, 描述], ...]` 的形状转换），下游解包与 HTML 模板完全未改。
- `render_card_core` 的 traditional/optimized 改由 `get_display_definition(verb)` 提供，两个文本块（📋 传统释义 / ✅ 优化释义）与样式保持不变。
- 删除主结果区从未被使用的 MOCK / 通用示例分支（dead code）：该分支重算的 `traditional`/`optimized` 在其作用域内无人读取，实际渲染一直走四卡函数。
- MOCK_DEFINITIONS 引用收敛至定义处与适配器降级分支，`grep` 结果仅剩 docstring 说明、降级分支与定义本身。

## Task Commits

Each task was committed atomically:

1. **Task 1: render_card_prototype 与 render_card_anchor 改接适配器** - `3b38621` (refactor)
2. **Task 2: render_card_core 改接 + 主结果区移除 MOCK 分支** - `00ddb14` (refactor)

## Files Created/Modified

- `src/app.py` - `render_card_anchor` 走 `get_semantic_table_for_verb`；`render_card_core` 走 `get_display_definition`；主结果区 dead-code 分支删除；两处数据来源注释。

## Decisions Made

- 形状转换留在 `get_semantic_table_for_verb`：`render_card_anchor` 的 `semantic_type, emoji, description = row` 解包依赖 5 行 list 形状，把 dict→list 的转换集中在 helper 里可让渲染函数零改动（T-05-04 缓解）。
- `render_card_prototype` 在 05-01 已通过该 helper 走适配器，本计划仅补注释，不做行为改动。
- 主结果区的 MOCK 分支按 dead code 直接删除，而不是改接或注释保留 —— 它不影响输出，保留只会留下第二个数据来源。

## Deviations from Plan

None - plan executed exactly as written。

## Issues Encountered

None。验证命令 `python -c "..."` 在无 MySQL / 无 `ZHIPUAI_API_KEY` 的环境下会打印连接失败的 ERROR 日志（预期降级噪声），断言仍全部通过。

## User Setup Required

None - 离线降级路径无需智谱密钥或 MySQL。

## Next Phase Readiness

- 渲染层已是「适配器唯一取数」，05-03 的集成测试可直接对 `show_result=True` 的展示态做冒烟断言。
- Phase 6 的配置面板只需改适配器内 LLM 分支的调用参数，无需再触碰渲染层。

---
*Phase: 05-live-generation*
*Completed: 2026-09-15*
