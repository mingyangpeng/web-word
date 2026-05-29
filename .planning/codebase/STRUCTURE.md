# Codebase Structure

**Analysis Date:** 2026-05-29

## Directory Layout

```
web-word/
├── .claude/              # Claude AI configuration
├── .git/                 # Git repository
├── .planning/            # GSD project planning (committing)
│   ├── STATE.md          # Project state tracking
│   ├── ROADMAP.md        # Phase roadmap
│   ├── PROJECT.md        # Project reference
│   ├── REQUIREMENTS.md   # Feature requirements
│   ├── phases/           # Phase planning files
│   │   ├── 01-verb-tool/  # Phase 1: Verb tool implementation
│   │   └── 02-verb-content/ # Phase 2: Verb content structure
│   └── codebase/         # Codebase documentation (GSD output)
├── docs/                 # Documentation (not committed)
├── data/                 # Data files
│   ├── web_word.db       # SQLite database file
│   └── *.docx            # Research papers
├── screenshots_final/    # Final screenshots (gitignored)
├── screenshots_verify*/  # Verification screenshots
├── scripts/              # Helper scripts
│   ├── get-stats.js      # GSD stats collection (Node.js)
│   └── get-stats.sh      # Bash wrapper for get-stats.js
├── src/                  # Source code
│   ├── .streamlit/       # Streamlit configuration
│   │   └── config.toml   # Streamlit server settings
│   ├── app.py            # Main Streamlit application
│   ├── database.py       # SQLite database module
│   └── design_system.py  # Design system module
├── temp/                 # Temporary files
└── CLAUDE.md             # Project instructions for Claude Code
```

## Directory Purposes

**src/:**
- Purpose: All Python source code
- Contains: Application code, modules, configuration
- Key files: `app.py`, `database.py`, `design_system.py`

**src/.streamlit/:**
- Purpose: Streamlit server configuration
- Contains: `config.toml` with server settings
- Key files: `config.toml`

**data/:**
- Purpose: Persistent data storage
- Contains: SQLite database, research documents
- Key files: `web_word.db`

**scripts/:**
- Purpose: Utility scripts for project management
- Contains: GSD stats collection (Node.js and Bash)
- Key files: `get-stats.js`, `get-stats.sh`

**.planning/:**
- Purpose: GSD project planning and state tracking
- Contains: State file, roadmap, phase plans, research
- Key files: `STATE.md`, `ROADMAP.md`

**docs/:**
- Purpose: Documentation (not committed to git)
- Contains: Additional project documentation

**screenshots_*/:**
- Purpose: Screenshots for verification and final output
- Contains: Browser screenshots, app screenshots

## Key File Locations

**Entry Points:**
- `src/app.py`: Main Streamlit application entry point (`streamlit run src/app.py`)

**Core Logic:**
- `src/app.py`: Page configuration, rendering functions, session state, mock data (979 lines)
- `src/database.py`: Database connection, CRUD operations, statistics (179 lines)
- `src/design_system.py`: Style system, colors, component functions (568 lines)

**Configuration:**
- `src/.streamlit/config.toml`: Streamlit server settings (port 8501, headless mode)

**Data:**
- `data/web_word.db`: SQLite database with queries and feedbacks tables

**Project Management:**
- `CLAUDE.md`: Project instructions for Claude Code
- `.planning/STATE.md`: GSD project state tracking
- `.planning/ROADMAP.md`: Phase roadmap and progress

## Naming Conventions

**Files:**
- Python files: `*.py` with lowercase words, underscores (e.g., `database.py`, `design_system.py`)
- Config files: `*.toml`, `*.js`, `*.sh` with lowercase
- Markdown files: `*.md` with lowercase

**Directories:**
- Python modules: lowercase with underscores (e.g., `src/`, `src/.streamlit/`)
- Planning files: numbered prefixes for ordering (e.g., `01-verb-tool/`, `02-verb-content/`)

**Functions:**
- Snake_case: `render_card_prototype()`, `get_stats()`, `insert_feedback()`

**Variables:**
- snake_case: `DB_AVAILABLE`, `MOCK_DEFINITIONS`, `CATEGORY_MODE`

**Constants:**
- UPPER_SNAKE_CASE: `CREATE_TABLES_SQL`, `DB_PATH`, `PRIMARY_COLOR`

## Where to Add New Code

**New Feature - LLM API Integration:**
- Primary code: Create `src/api.py` for LLM calls (DeepSeek/智谱/OpenAI)
- Update: `src/app.py` to import and use LLM responses instead of `MOCK_DEFINITIONS`
- Tests: Create `src/api_test.py` (or `src/tests/` directory)

**New UI Component:**
- Implementation: Add function to `src/design_system.py` for reusable styles
- Integration: Call from `src/app.py` in appropriate section

**New Database Feature:**
- Implementation: Add functions to `src/database.py`
- Integration: Import in `src/app.py`, call from UI events

**Utilities/Helpers:**
- Shared helpers: Create new module in `src/` (e.g., `src/utils.py`)

**Testing:**
- Unit tests: Co-located or separate (recommend separate for larger projects)
- Integration tests: In `src/tests/` directory

## Special Directories

**.planning/:**
- Purpose: GSD project planning system
- Generated: Yes (automated by GSD commands)
- Committed: Yes (documentation)

**screenshots_*/:**
- Purpose: Visual verification artifacts
- Generated: Yes (via browser/screen capture)
- Committed: Yes (for documentation/verification)

**data/:**
- Purpose: Project data storage
- Generated: Yes (SQLite database)
- Committed: No (contains user data)

**temp/:**
- Purpose: Temporary working files
- Generated: Yes (auto-generated content)
- Committed: No (usually in .gitignore)

---

*Structure analysis: 2026-05-29*
