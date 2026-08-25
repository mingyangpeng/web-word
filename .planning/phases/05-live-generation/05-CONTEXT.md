# Phase 5: 实时生成接入 (Live Generation) - Context

**Gathered:** 2026-08-25
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase makes Zhipu AI live generation the primary definition source for the verb tool. It rewires the query path so that for any verb, the app resolves a definition via `DB hit → live LLM → parse → store in MySQL → render`, falling back to MOCK_DEFINITIONS only when both DB and LLM fail. It covers the render integration, the data-source priority wiring, the LLM prompt/response contract (traditional + optimized text blocks + semantic dict), and the generation loading UX. No auth, no config panel, no admin entry — those are Phase 6/7/8.

</domain>

<decisions>
## Implementation Decisions

### Render Integration
- **D-01:** Introduce a single adapter `get_display_definition(verb)` (in app.py, alongside the existing `get_verb_definition()` at app.py:409) that returns a normalized dict `{traditional, optimized, semantic_table, example}`. All four render functions — `render_card_prototype`, `render_card_anchor` (reads MOCK at app.py:272), `render_card_core` (reads MOCK at app.py:305), `render_card_example`, and the main result area (app.py:853) — must consume this adapter instead of `MOCK_DEFINITIONS`. — **Reversibility:** costly — every render site currently reads MOCK_DIRECTLY; changing the shared call shape means touching all four + main area, so get it right once via the adapter.
- **D-02:** MOCK_DEFINITIONS is demoted to the lowest-priority fallback inside the adapter: priority is DB → live LLM → MOCK_DEFINITIONS → (get_fallback_definition from llm_api.py as the absolute last resort). The 155 verbs already in MySQL `definitions` and new LLM-generated rows take precedence over hand-curated mock. — **Reversibility:** reversible — it's a priority ordering in one function.

### LLM Response Contract
- **D-03:** Extend `PROMPT_TEMPLATE` (llm_api.py:60) so the LLM returns BOTH a `traditional` (词典式释义) text block AND an `optimized` (语义分解释义) text block, plus the `semantic_table` dict, `example`, and `synonyms`. `render_card_core` (card #3) shows both blocks exactly as it does today. The existing `_parse_llm_response` (llm_api.py:284) must map `traditional`/`optimized` into the parsed dict (currently it only maps `chinese_ndef`, `semantic_table`, `example`, `synonyms`). — **Reversibility:** reversible — prompt + parser change, no schema migration (columns store JSON anyway).
- **D-04:** Semantic element model stays the 4+1 set already in code: manner/方向/体相/范围/路径 mapping via `get_semantic_table_for_verb` (app.py:432). The LLM semantic_table dict keys expected: manner, direction, aspect, scope, path. No change to the 5-row render table format. — **Reversibility:** reversible.

### Data Source Wiring (LLM-02 / LLM-03)
- **D-05:** `get_display_definition(verb)` flow (LLM-02): (1) `get_definition_by_verb(verb)` from mysql_db → if found, return normalized; (2) else call `llm_api.get_definition(verb)` which calls `_call_llm_api` + caches to MySQL; on success, persist the normalized row via `mysql_db.insert_definition(verb, chinese_ndef, semantic_table, example, model_version)` so subsequent queries hit DB (LLM-03); (3) on LLM failure, return MOCK if present; (4) final fallback `get_fallback_definition`. — **Reversibility:** reversible — logic localized in the adapter; `insert_definition` already implements ON DUPLICATE KEY UPDATE.
- **D-06:** LLM-04 error handling: wrap the LLM call so a missing/empty `ZHIPUAI_API_KEY` or timeout/exception degrades gracefully — log, show a user-facing st.warning/info ("实时生成暂不可用，已显示离线释义"), and return the next-priority source without crashing the app. Reuse the try/except already in `_call_llm_api`. — **Reversibility:** reversible.

### Loading UX
- **D-07:** Use `st.spinner("正在调用大模型生成释义...")` around the live-generation path in `get_display_definition` (or at the call site in the main area). DB hits (cached) return instantly so the spinner only appears on a genuine first-time LLM call. No skeleton placeholders. — **Reversibility:** reversible.

### Claude's Discretion
- Exact wording of the degradation warning message (D-06) and where precisely the spinner wraps (adapter vs call site) are left to Claude — keep it consistent with existing st.info/st.warning patterns in app.py.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase / Requirements
- `.planning/ROADMAP.md` § "Phase 5: 实时生成接入" — goal, success criteria (LLM-01..04)
- `.planning/REQUIREMENTS.md` § "Live Generation (LLM)" — LLM-01/02/03/04 definitions

### Existing Code (read before implementing)
- `src/app.py` — `get_verb_definition()` (app.py:409), `get_semantic_table_for_verb()` (app.py:432), `MOCK_DEFINITIONS` (app.py:468), `render_card_core()` (app.py:295, reads MOCK at 305), `render_card_anchor()` (app.py:262, reads MOCK at 272), main result area (app.py:848-918, MOCK read at 853), `render_semantic_table()` (app.py:155)
- `src/llm_api.py` — `get_definition()` (app.py:~207), `_call_llm_api()` (~239), `_parse_llm_response()` (~284, needs traditional/optimized mapping), `PROMPT_TEMPLATE` (~60, extend for both blocks), `get_fallback_definition()` (~389), `save_definition_to_cache()` / `get_definition_from_cache()` (~134)
- `src/mysql_db.py` — `insert_definition()` (mysql_db.py:~322, ON DUPLICATE KEY UPDATE), `get_definition_by_verb()` (~365), `definitions` table schema (mysql_db.py:~105)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `get_verb_definition(verb)` (app.py:409) — already calls `llm_api.get_definition()` with cache + force_refresh; extend or wrap it into the adapter.
- `insert_definition()` (mysql_db.py:~322) — already does INSERT ... ON DUPLICATE KEY UPDATE; perfect for LLM-03 persistence without new SQL.
- `get_fallback_definition()` (llm_api.py:~389) — ready-made absolute-last-resort dict.

### Established Patterns
- Render functions take `verb` and read `MOCK_DEFINITIONS.get(verb, {})` — the adapter must preserve the same `{traditional, optimized, semantic_table, example}` access shape so minimal render-body changes are needed.
- `get_semantic_table_for_verb()` already converts a semantic_table dict into the `[[type, emoji, desc], ...]` list `render_semantic_table` expects — reuse it in the adapter.

### Integration Points
- Main result area (app.py:850-918) is where the spinner + adapter call should be injected; currently it branches on `verb in MOCK_DEFINITIONS`.
- `_parse_llm_response` is the single place to add `traditional`/`optimized` keys so `render_card_core` gets both blocks.

</code_context>

<specifics>
## Specific Ideas

- Keep the existing 4-card layout identical (原型与位移事件分析 / 范畴锚定 / 核心释义与多维辨异 / 图式示例) — only the data source behind each card changes, not the presentation.
- The 155 motion verbs already in MySQL should render from DB instantly (no LLM call), proving the "DB first" branch works.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 5-实时生成接入 (Live Generation)*
*Context gathered: 2026-08-25*
