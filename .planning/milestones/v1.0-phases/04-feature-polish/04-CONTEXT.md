# Phase 4: 功能完善 - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase completes the remaining UI polish for the English synonym verb definition tool:
- **UI-06**: 侧边栏折叠/展开功能（参考 DeepSeek 网页版的窄图标栏 rail 模式）
- **UI-07**: 优化统计数据显示（维持 metric 风格，仅做间距/标题/分隔微调）
- **UI-08**: 改进热门动词列表（点击填入搜索框 + 本地前端筛选）

Phase 4 is strictly UI/UX polish on top of the already-integrated MySQL backend. It does NOT add new data capabilities, new APIs, or change the semantic-decomposition model. Scope is bounded by ROADMAP.md Phase 4 and REQUIREMENTS.md UI-06/07/08.

</domain>

<decisions>
## Implementation Decisions

### Sidebar Collapse / Expand (UI-06)
- **D-01:** Collapsed state uses a narrow **icon rail** (参照 DeepSeek 网页版 / VS Code 活动栏), NOT a fully hidden floating button.
  - The rail shows one icon per sidebar section (📊 统计, 🔥 热门, 📥 导出), with a hover tooltip / label.
  - Clicking an icon expands the full sidebar back to its expanded width.
  - Expansion toggle (☰ / ◀) lives in the rail.
  - **Reversibility:** costly — touches `render_sidebar()` structure, page layout, and `st.set_page_config(initial_sidebar_state)` plus a new `st.session_state` flag for collapsed state.
- **D-02:** Collapse state is held in `st.session_state` (e.g. `sidebar_collapsed` bool), initialized from current `initial_sidebar_state="expanded"`. No persistence across reloads required for v1.0.

### Statistics Display (UI-07)
- **D-03:** Keep Streamlit's native `st.sidebar.metric()` style. Only refine vertical spacing (`get_section_spacing()`), heading hierarchy (`HEADER_H2` / `HEADER_H3`), and section dividers. Do NOT introduce new card components for metrics.
  - **Reversibility:** reversible — pure styling/typography tuning in `render_sidebar()`.

### Hot Verbs List (UI-08)
- **D-04:** Each hot-verb row is clickable → clicking fills the top search box (`st.session_state["搜索动词"]`) and triggers the existing `search_verb()` callback (reuse `select_example_verb` pattern at `src/app.py:127`).
- **D-05:** Add a local filter input ABOVE the hot-verbs list that does client-side substring filtering of the already-loaded `hot_verbs` list (no backend round-trip). Reuse the existing `st.text_input` styling.
  - **Reversibility:** reversible — add a local `st.text_input` + Python filter over `hot_verbs` in `render_sidebar()`.

### Claude's Discretion
- Exact rail width, icon set, hover animation timing, and divider styling — pick defaults consistent with the existing design system (`design_system.py`) without further questions.
- Whether the filter input appears above or inline with the 🔥 热门查询动词 header — implement whichever reads cleaner.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & Requirements
- `.planning/ROADMAP.md` § Phase 4 — Goal, Success Criteria, Planned Work for UI-06/07/08
- `.planning/REQUIREMENTS.md` — UI-06 / UI-07 / UI-08 requirement definitions (Pending)

### Existing Code (read before editing)
- `src/app.py` `render_sidebar()` (lines ~706–760) — current sidebar implementation (metrics, hot verbs markdown table, CSV export)
- `src/app.py` `st.set_page_config(initial_sidebar_state="expanded")` (line ~35) — sidebar default state
- `src/app.py` `select_example_verb(verb)` (line ~127) — click-to-search callback to reuse for hot-verb click
- `src/app.py` `search_verb()` (line ~118) — on_change callback to reuse
- `src/design_system.py` — `get_section_spacing()`, `HEADER_H2`, `HEADER_H3`, card/button style helpers
- `src/mysql_db.py` `get_stats()` / `get_hot_verbs(limit=5)` (lines ~621/671) — backend data sources (already wired)
- `.planning/phases/03-backend-integration/03-CONTEXT.md` — confirms backend (MySQL + Zhipu) is the integration baseline this phase builds UI on

### Reference (user-cited visual style)
- DeepSeek 网页版 (chat.deepseek.com) — narrow icon-rail sidebar collapse pattern (cited as the desired look for UI-06); not a repo artifact, captured as a design intent in `<specifics>`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `select_example_verb(verb)` (`src/app.py:127`) — already implements "fill search box + trigger search" via `st.session_state` mutation; reuse for hot-verb click.
- `design_system.py` helpers (`get_section_spacing`, `HEADER_H2/H3`, `get_card_style`, `get_badge_style`) — use for consistent spacing/headings in the rail and expanded sidebar.
- `render_card_header(..., expandable=True, collapsed=...)` (`src/app.py:849+`) — existing expand/collapse card pattern; the `card_expanded` session_state map is a precedent for the new `sidebar_collapsed` flag.

### Established Patterns
- Session-state flags drive UI toggles (see `card_expanded` dict at `src/app.py:44`). Mirror with `sidebar_collapsed`.
- Sidebar renders metrics via `st.sidebar.metric` and hot verbs via a markdown table (`src/app.py:721–735`) — UI-07 keeps metric style, UI-08 replaces the static markdown table with clickable + filterable list.
- `DB_AVAILABLE` guard wraps all DB calls in `render_sidebar()` — new filter input must respect it (no filter when `hot_verbs` is empty).

### Integration Points
- New collapse toggle + rail render inside `render_sidebar()` (called once at `src/app.py:1037`).
- Hot-verb click → `select_example_verb(v['verb'])` keeps the existing search pipeline (no new backend needed).

</code_context>

<specifics>
## Specific Ideas

- **UI-06 visual target:** DeepSeek 网页版 (chat.deepseek.com) 的窄图标栏 rail 模式 — 折叠后侧栏收成一条细图标列，hover 出文字，点击图标展开。用户明确点名此参考而非"完全隐藏+悬浮按钮"或"保留搜索框"方案。
- **UI-07:** 用户选择"维持 metric 微调"，即不引入卡片组件，只调整间距/标题层级/分隔。
- **UI-08:** 用户选择"点击填入 + 本地筛选"——点击动词填入搜索框（复用现有逻辑），上方加一个本地过滤输入框对已有热门词做前端筛选。

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within Phase 4 scope. (Note: REQUIREMENTS.md lists UI-09, UI-10, AUTH-01 as Deferred — out of this phase's boundary, captured for future milestones.)

</deferred>

---

*Phase: 4-功能完善*
*Context gathered: 2026-08-24*
