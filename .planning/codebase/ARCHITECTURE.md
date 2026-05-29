# Architecture

**Analysis Date:** 2026-05-29

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Frontend Layer: Streamlit                             │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        Sticky Search Bar (CSS/JS)                       │  │
│  │  - Google-style fixed positioning with backdrop-filter blur            │  │
│  │  - Real-time search with 300ms debounce                                │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        Main Content Area                                │  │
│  │  - Theory description (Wave-like vs Vector-like motion events)          │  │
│  │  - Semantic table rendering (emoji-coded)                               │  │
│  │  - Four expandable cards: prototype, anchor, core, example             │  │
│  │  - Example library with 3 category tabs (20 verbs)                      │  │
│  │  - User feedback section (rating + text)                                 │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        Sidebar Components                               │  │
│  │  - Statistics (total queries, avg rating, total feedbacks)             │  │
│  │  - Hot verbs leaderboard (5 most searched)                              │  │
│  │  - CSV export for feedback data                                         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Backend Layer: Business Logic                            │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        Design System Module                              │  │
│  │  - Centralized color palette (WCAG AA compliant)                        │  │
│  │  - Spacing system (8px base unit)                                       │  │
│  │  - Reusable style functions (buttons, cards, tables, spacing)          │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        Database Module                                   │  │
│  │  - Connection management (WAL mode, foreign keys)                      │  │
│  │  - CRUD operations (queries, feedbacks)                                 │  │
│  │  - Statistics queries (total, avg, hot verbs)                           │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Data Layer: SQLite                                   │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         queries Table                                   │  │
│  │  - id, verb, traditional_text, optimized_text, semantic_table,         │  │
│  │    model_version, created_at                                            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        feedbacks Table                                  │  │
│  │  - id, query_id, verb, rating, feedback_text, created_at               │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Main Application | Page configuration, session state initialization, sticky search bar CSS, entry point | `src/app.py` (lines 30-978) |
| Sticky Search Bar | Real-time verb search with 300ms debounce, Google-style fixed positioning via inline CSS/JS | `src/app.py` (lines 62-123) |
| Theory Section | Explain Talmy's motion event typology (wave-like vs vector-like) | `src/app.py` (lines 84-105) |
| Semantic Table Renderer | Render semantic decomposition table with emoji color coding | `src/app.py` (lines 127-166) |
| Card Renderers | Four specialized card functions for different content types (prototype, anchor, core, example) | `src/app.py` (lines 171-325) |
| Example Library | Three-tab interface with 18 categorized verbs, triggers search on click | `src/app.py` (lines 329-377) |
| Sidebar | Statistics display, hot verbs leaderboard, CSV export button | `src/app.py` (lines 640-694) |
| Feedback Form | Rating slider (1-5), text input, submit with database persistence | `src/app.py` (lines 816-858) |
| Design System | Centralized styling, colors, spacing, component functions | `src/design_system.py` |
| Database Layer | Connection management, CRUD, statistics, initialization | `src/database.py` |
| Mock Data | 18 verbs with full semantic decomposition (placeholder for LLM API) | `src/app.py` (lines 382-612) |

## Pattern Overview

**Overall:** Frontend-driven SPA with SQLite backend

**Key Characteristics:**
- Single-threaded event-driven architecture (Streamlit)
- State managed via `st.session_state`
- CSS/JS injection for interactive features (sticky search bar)
- Design system pattern for UI consistency
- Mock data pattern (placeholder for LLM integration)

## Layers

**Frontend Layer (Streamlit):**
- Purpose: User interface and interaction logic
- Location: `src/app.py`
- Contains: Page config, rendering functions, session state, mock data
- Depends on: Design system module, database module
- Used by: Browser users via Streamlit server

**Design System Layer:**
- Purpose: Centralized styling and UI component library
- Location: `src/design_system.py`
- Contains: Color palette, spacing constants, style functions
- Depends on: None (self-contained)
- Used by: Frontend layer for consistent styling

**Backend Logic Layer:**
- Purpose: Business logic and data operations
- Location: `src/database.py`
- Contains: Database connection, CRUD operations, statistics queries
- Depends on: Standard library only
- Used by: Frontend layer for data persistence

**Data Layer (SQLite):**
- Purpose: Persistent storage for queries and feedbacks
- Location: `data/web_word.db`
- Contains: Two tables (queries, feedbacks) with indexes
- Depends on: Standard library (sqlite3)
- Used by: Backend layer for data storage

## Data Flow

### Primary Request Path

1. **User searches verb** (`src/app.py:714`)
   - User enters verb in sticky search bar
   - `on_change=search_verb` triggers
   - Session state updated: `st.session_state.verb_result = value`

2. **Search result display** (`src/app.py:742-772`)
   - Check if verb exists in `MOCK_DEFINITIONS`
   - If yes, use predefined data
   - If no, use generic template with verb in place

3. **Card rendering** (`src/app.py:783-807`)
   - Four cards rendered with expandable/collapsible states
   - Each card uses its respective render function
   - States managed in `st.session_state.card_expanded`

4. **User feedback** (`src/app.py:836-858`)
   - User submits rating + text
   - `insert_feedback()` called from database module
   - Success/error handling with user notification
   - Session state records last submission

### Secondary Flow: Statistics

1. **Render sidebar** (`src/app.py:640-694`)
   - `get_stats()` queries total queries and average rating
   - `get_hot_verbs()` aggregates feedback counts by verb
   - CSV data exported via `get_feedback_data()`

2. **Database queries** (`src/database.py:134-179`)
   - `get_stats()`: Two queries (COUNT and AVG)
   - `get_hot_verbs()`: LEFT JOIN with GROUP BY
   - `get_feedback_data()`: Simple SELECT ordered by created_at

**State Management:**
- Session state (`st.session_state`): Card expand/collapse, current verb, show_result, last_feedback, feedback_submitted
- Database: Persistent storage via SQLite WAL mode

## Key Abstractions

**Semantic Decomposition Table:**
- Purpose: Display semantic elements (方式/路径/方向/体相) with emojis
- Examples: `render_semantic_table()` in `src/app.py`
- Pattern: List of tuples [[type, emoji, description]]

**Expandable Card Component:**
- Purpose: Group related content with header/footer structure
- Examples: `render_card_header()`, `render_card_prototype()`, etc. in `src/app.py`
- Pattern: Header + content div with collapsible state

**Sticky Search Bar:**
- Purpose: Fixed-position search bar with blur effect
- Implementation: Inline CSS (st.markdown) + HTML/JS (st.components.html)
- Pattern: Scroll listener with position toggling

**Design System Style Functions:**
- Purpose: Reusable CSS styling for consistent UI
- Examples: `get_button_primary_style()`, `get_card_style()`, `get_section_spacing()` in `src/design_system.py`
- Pattern: Function returning formatted CSS strings

## Entry Points

**Streamlit Application:**
- Location: `src/app.py`
- Triggers: `streamlit run src/app.py`
- Responsibilities:
  - Page configuration (`st.set_page_config`)
  - Session state initialization
  - Database initialization with fallback
  - Rendering of sidebar and main area
  - Mock data definitions (18 verbs)

**Database Module:**
- Location: `src/database.py`
- Triggers: Imported by `app.py`, called for data operations
- Responsibilities:
  - Connection management with context manager
  - Table creation (queries, feedbacks)
  - CRUD operations
  - Statistical queries

**Design System Module:**
- Location: `src/design_system.py`
- Triggers: Imported by `app.py`, used for styling
- Responsibilities:
  - Color definitions
  - Spacing constants
  - Style function generation
  - Accessibility verification

## Architectural Constraints

- **Threading:** Single-threaded (Streamlit event loop); no parallel processing
- **Global state:** `st.session_state` (streamlit-managed), database connections via context manager
- **Circular imports:** None detected
- **Session state:** Extensive use for interactivity (cards, search results)
- **Frontend-only:** No API layer yet (LLM integration planned)
- **Fallback mode:** Database errors fall back to offline mode with mock data

## Anti-Patterns

### Mock Data in Production Logic

**What happens:** Dictionary `MOCK_DEFINITIONS` contains hardcoded semantic decompositions for 18 verbs in `src/app.py` (lines 382-612). These will be replaced by LLM API calls but currently represent all semantics.

**Why it's wrong:** Hardcoded data prevents personalization, scale, and maintains false sense of database integration.

**Do this instead:** Create a service layer `src/api.py` with LLM integration that reads from external model, storing only successful queries in SQLite. Separate mock data to a `src/mock_data.py` module with clear "PLACEHOLDER" warnings.

### Inline CSS/JS in Streamlit

**What happens:** Styling and interactive logic are embedded as inline strings in `src/app.py` (lines 62-79 for CSS, 881-964 for JS).

**Why it's wrong:** Difficult to maintain, test, and debug; violates separation of concerns.

**Do this instead:** Extract to separate CSS file (`src/static/style.css`) and JS file (`src/static/sticky-search.js`). Use Streamlit's native styling with CSS import.

### Mixed Data Sources

**What happens:** Current app uses both `MOCK_DEFINITIONS` (in-memory dictionary) and database (SQLite). Success queries are only recorded when feedback is submitted.

**Why it's wrong:** Search history is incomplete; cannot track queries that were viewed but not rated.

**Do this instead:** Record all queries on search, not just feedback. Use a background flag to determine if LLM was used vs mock data.

## Error Handling

**Strategy:** Defensive programming with fallbacks

**Patterns:**
- Database initialization wrapped in try/except with fallback to offline mode (`src/app.py:52-57`)
- API calls (planned) would follow similar pattern
- User feedback submission handles missing required fields with warnings
- Database operations use transaction context managers with rollback on failure

## Cross-Cutting Concerns

**Logging:** Not implemented yet (commented placeholders in `app.py` lines 984-1025)

**Validation:** Basic input validation (1-50 char verb length in `search_verb()`, rating 1-5 in `insert_feedback()`)

**Authentication:** None implemented (all functions public)

**Caching:** Not implemented (can be added via LRU cache or Streamlit caching)
