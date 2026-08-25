# Phase 5: 实时生成接入 (Live Generation) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-25
**Phase:** 5-实时生成接入 (Live Generation)
**Areas discussed:** Render integration, Mock role, Card schema, Loading UX

---

## Render Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Single adapter | Add get_display_definition(verb) returning {traditional, optimized, semantic_table, example}; all render functions call it | ✓ |
| Per-function inline | Rewrite each render function to call get_verb_definition() directly | |
| session_state injection | Inject live dict into session_state, render funcs read from it | |

**User's choice:** Single adapter
**Notes:** Minimal new surface; MOCK becomes just another source inside the adapter.

---

## Mock Role

| Option | Description | Selected |
|--------|-------------|----------|
| Mock = final fallback only | Priority DB → LLM → Mock; MOCK lowest priority | ✓ |
| Mock = curated override (top) | Keep MOCK as first source (hand-curated), else DB→LLM | |
| Remove MOCK entirely | Delete MOCK_DEFINITIONS, rely fully on DB/LLM | |

**User's choice:** Mock = final fallback only
**Notes:** 155 verbs already in MySQL + new LLM rows take precedence over hand-curated mock.

---

## Card Schema (LLM Response Contract)

| Option | Description | Selected |
|--------|-------------|----------|
| Prompt returns both | LLM returns traditional + optimized text blocks + semantic_table dict | ✓ |
| LLM returns optimized only | Derive traditional line from verb | |
| Build both from dict | Build both HTML client-side from the dict | |

**User's choice:** Prompt returns both
**Notes:** Keeps current 4-card layout intact; render_card_core shows both blocks.

---

## Loading UX

| Option | Description | Selected |
|--------|-------------|----------|
| Spinner | st.spinner during get_display_definition; instant on DB hit | ✓ |
| Skeleton placeholder | Show placeholder card, replace on arrival | |
| No indicator | Let call block silently | |

**User's choice:** Spinner
**Notes:** AppTest-safe; only appears on genuine first-time LLM call.

---

## Claude's Discretion

- Exact wording of the degradation warning (D-06) and precise spinner wrapping location (adapter vs call site) left to Claude, consistent with existing st.info/st.warning patterns.

## Deferred Ideas

None — discussion stayed within phase scope.
