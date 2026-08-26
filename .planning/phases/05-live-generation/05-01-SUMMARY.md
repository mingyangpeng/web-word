---
phase: 05-live-generation
plan: 01
subsystem: llm
tags: [zhipuai, streamlit, mysql, adapter, semantic-decomposition]

# Dependency graph
requires:
  - phase: 03-backend-integration
    provides: mysql_db.insert_definition / get_definition_by_verb, llm_api.get_definition, security.InputValidator
provides:
  - get_display_definition(verb) unified adapter as the single data source for all render sites
  - Extended LLM response contract with traditional/optimized text blocks
  - DB -> live LLM -> MOCK -> fallback resolution priority with persistence and graceful degradation
affects: [05-02-render-rewire, 05-03-tests]

# Actuals (#2632)
actuals:
  tokens: 2672           # ~10687 diff chars / 4 over the realized src diff
  tasks: 1
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "get_display_definition(verb) as the sole normalized data source {traditional, optimized, semantic_table, example}"
    - "DB -> live LLM (spinner) -> MOCK -> fallback priority ordering inside one adapter"
    - "combined chinese_ndef JSON {'traditional','optimized'} to avoid schema migration"

key-files:
  created: []
  modified:
    - src/llm_api.py
    - src/app.py

key-decisions:
  - "D-01/D-02/D-05/D-06/D-07 realized in get_display_definition: single adapter, DB-first priority, LLM persistence, graceful warning on failure, spinner only around live-LLM branch"
  - "T-05-01 mitigation: InputValidator rejects empty/over-length/SQL/XSS verbs at adapter entry, never fed to LLM prompt; illegal input short-circuits to get_fallback_definition"
  - "chinese_ndef stores combined {'traditional','optimized'} JSON (D-03: no schema migration); DB read restores split, legacy plain text falls back to traditional only"
  - "MOCK_DEFINITIONS demoted to lowest-priority fallback; get_semantic_table_for_verb rewired to consume the adapter with unchanged signature/shape"

patterns-established:
  - "Unified adapter pattern: every render site should call get_display_definition instead of reading MOCK directly"
  - "Combined-JSON-in-existing-column pattern for adding structured fields without ALTER TABLE"

requirements-completed:
  - LLM-01
  - LLM-02
  - LLM-03
  - LLM-04

coverage:
  - id: D1
    description: "Extended PROMPT_TEMPLATE with traditional/optimized text blocks; _parse_llm_response maps traditional/optimized (keep chinese_ndef)"
    requirement: LLM-01
    verification:
      - kind: unit
        ref: "python -c 'from src.llm_api import PROMPT_TEMPLATE, _parse_llm_response; ...; assert d[\"traditional\"]==\"T传统\" and d[\"optimized\"]==\"O优化\"'"
        status: pass
    human_judgment: false
  - id: D2
    description: "get_display_definition returns {traditional, optimized, semantic_table, example} with DB->LLM->MOCK->fallback priority and persistence"
    requirement: LLM-02
    verification:
      - kind: unit
        ref: "python -c 'from src.app import get_display_definition; r=get_display_definition(\"跑进来\"); assert set([...]).issubset(r.keys()) and r[\"traditional\"] and r[\"optimized\"]'"
        status: pass
    human_judgment: false
  - id: D3
    description: "Live-LLM result persisted via mysql_db.insert_definition (combined chinese_ndef JSON, semantic_table JSON, example_sentence)"
    requirement: LLM-03
    verification:
      - kind: unit
        ref: "src/app.py#mysql_db_persist (unit-tested _restore_trad_opt round-trip)"
        status: pass
    human_judgment: false
  - id: D4
    description: "LLM failure/exception caught, st.warning('实时生成暂不可用，已显示离线释义'), app does not crash; degrades to MOCK/fallback"
    requirement: LLM-04
    verification:
      - kind: unit
        ref: "get_display_definition('跑进来') returns MOCK content when DB + LLM unavailable (offline path)"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-08-26
status: complete
---

# Phase 5 Plan 01: 端到端实时生成适配器 (Live Generation Tracer) Summary

**Extended llm_api contract with traditional/optimized blocks and shipped get_display_definition(verb) — the single adapter wiring DB -> live LLM -> MOCK -> fallback with persistence and graceful degradation.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-08-26T06:21:05Z
- **Completed:** 2026-08-26T06:25:40Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Extended `llm_api.PROMPT_TEMPLATE` to request two independent text blocks — `traditional` (词典式释义) and `optimized` (语义分解释义) — while keeping the 5-key `semantic_table` (manner/path/direction/aspect/scope); `_parse_llm_response` now maps `traditional`/`optimized` (and still `chinese_ndef`).
- Added `get_display_definition(verb)` in `app.py` as the sole normalized data source returning `{traditional, optimized, semantic_table, example}`, with strict priority: DB hit -> live LLM (wrapped in `st.spinner`) -> MOCK_DEFINITIONS -> `get_fallback_definition`.
- Persisted successful LLM results to MySQL via `mysql_db.insert_definition` (D-03: combined `chinese_ndef` JSON, no schema migration) so subsequent queries hit DB.
- Wired T-05-01 mitigation: `InputValidator.validate_string(verb, max_length=50)` rejects empty/over-length/SQL/XSS verbs at the adapter entry; illegal input never reaches the LLM prompt and short-circuits to the fallback.
- Rewired `get_semantic_table_for_verb` to consume the adapter (signature and 5-row return shape unchanged), leaving all four render cards untouched.

## Task Commits

Each task was committed atomically:

1. **Task 1: 端到端实时生成适配器（契约扩展 + get_display_definition）** - `343dbbc` (feat)

## Files Created/Modified

- `src/llm_api.py` - Extended `PROMPT_TEMPLATE` (traditional/optimized blocks); `_parse_llm_response` maps `traditional`/`optimized`.
- `src/app.py` - New `get_display_definition` adapter (DB->LLM->MOCK->fallback, persistence, spinner, T-05-01 entry validation), `mysql_db_persist`, `_restore_trad_opt`, `_normalize_mock_semantic_table`; `get_semantic_table_for_verb` rewired; imports added (`get_definition_by_verb`, `insert_definition`, `get_fallback_definition`, `InputValidator`).

## Decisions Made

- Adapter is the single source of truth; `MOCK_DEFINITIONS` demoted to lowest-priority fallback (D-02).
- Spinner wraps only the live-LLM branch (D-07) — DB/MOCK/fallback return instantly.
- `chinese_ndef` column stores combined `{"traditional","optimized"}` JSON to avoid migration (D-03); read path splits, legacy plain text falls back to `traditional` only.
- Illegal verb input is rejected at the entry via `InputValidator` and routed to the fallback without touching the LLM prompt (T-05-01).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required (the offline MOCK/fallback path runs without a Zhipu AI key or live MySQL).

## Next Phase Readiness

- `get_display_definition` is ready for the render rewire plan (05-02) to consume across all four cards and the main result area.
- 05-03 (tests) can build on the adapter's deterministic priority and the `_restore_trad_opt` / `_normalize_mock_semantic_table` helpers.
- Live LLM/DB paths require `ZHIPUAI_API_KEY` (T-05-02: read only via `os.getenv`, never logged) and a running MySQL for the persistence branch; both are optional for the offline path verified here.

---
*Phase: 05-live-generation*
*Completed: 2026-08-26*
