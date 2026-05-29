# Codebase Concerns

**Analysis Date:** 2026-05-29

## Tech Debt

### LLM Integration (Phase 3+ Scope)
- **Issue:** Large model API integration is planned but not implemented — marked in `app.py` lines 980-1006 as "future integration"
- **Files:** `src/app.py` lines 981-1006 (comment block describing unimplemented LLM integration)
- **Impact:** Core value proposition (semantic decomposition via LLM) cannot be fully delivered
- **Fix approach:** Implement LLM API call with proper error handling, caching, and fallback to mock data

### Mock Data in Production Code
- **Issue:** Mock data (`MOCK_DEFINITIONS`) still present in production code despite documented as placeholder
- **Files:** `src/app.py` lines 381-612 (18 mock verb definitions with semantic tables)
- **Impact:** Users see fake data instead of real LLM-generated results
- **Fix approach:** Replace with actual LLM API integration, keep mock data only for demo/testing mode

### Missing Database Adapter
- **Issue:** Code comments reference MySQL 8.0 (`src/database.py` line 1020 comment: "MySQL 8.0 数据库存储") but current implementation uses SQLite
- **Files:** `src/app.py` lines 1020-1025 (comment block mentioning PyMySQL/MySQL)
- **Impact:** Inconsistency between documented architecture and actual implementation
- **Fix approach:** Either update database.py to support MySQL connection or remove MySQL references

## Known Bugs

### JavaScript Injection Without Validation
- **Symptoms:** `components.html()` in `app.py` lines 881-964 injects unvalidated JavaScript code that runs in user browsers
- **Files:** `src/app.py` lines 881-964 (Sticky search bar implementation)
- **Trigger:** Any user can trigger the JS injection by navigating to the app
- **Workaround:** None currently — JS code only runs in Streamlit iframe context

### Database Connection Fallback Silent Failure
- **Symptoms:** Database connection errors are caught but only show warning; code continues with `DB_AVAILABLE = False`
- **Files:** `src/app.py` lines 52-57
- **Impact:** Users don't get clear feedback about what went wrong
- **Workaround:** Check browser console and app logs

### Session State State Drift
- **Symptoms:** Session state not explicitly initialized for all new sessions (card_expanded, show_result)
- **Files:** `src/app.py` lines 41-47 (conditional session state init)
- **Impact:** Potential KeyError on first load before session state is populated

## Security Considerations

### Missing API Key Management
- **Risk:** LLM API integration (planned) will require storing API keys
- **Files:** `src/app.py` lines 980-1006 (mentions DeepSeek/智谱/OpenAI without key handling)
- **Current mitigation:** No API key handling implemented yet
- **Recommendations:**
  - Use environment variables for API keys (not hardcoded)
  - Never commit `.env` files or API keys to git
  - Consider using a proxy service if deploying to public HF Spaces

### No Authentication/Authorization
- **Risk:** No access control for user submissions; all data could be tampered with
- **Impact:** Game-able system (users could submit fake feedback)
- **Recommendations:** Add user tracking and rate limiting if deploying publicly

### No Input Sanitization
- **Risk:** User input (verb names, feedback text) not validated or sanitized before display
- **Files:** `src/app.py` render functions (lines 127-324)
- **Impact:** Potential XSS vulnerabilities in displayed content
- **Recommendations:** Sanitize all user inputs before HTML rendering

### SQL Injection Risk (Low)
- **Risk:** Parameterized queries used in database.py, so SQL injection is not a direct issue
- **Files:** `src/database.py` lines 93-102, 108-113 (all queries use `?` parameters)
- **Mitigation:** Already protected by parameterized queries
- **Status:** No action needed

## Performance Bottlenecks

### Large Mock Data Dictionary
- **Problem:** `MOCK_DEFINITIONS` contains 18 complete verb entries (180+ lines)
- **Files:** `src/app.py` lines 381-612
- **Cause:** Hardcoded in-memory data structure
- **Improvement path:** Move to external JSON/YAML file for easier updates and smaller initial load

### No Caching Mechanism
- **Problem:** Every verb query triggers full UI re-render in Streamlit
- **Impact:** Frequent queries show slight delay
- **Improvement path:** Add LRU cache for LLM responses (after integration)

### Streamlit State Management Overhead
- **Problem:** Session state used for all UI state (card_expanded, show_result, verb_result)
- **Impact:** More complex than necessary for simple display state
- **Improvement path:** Simplify state management, use Streamlit's built-in caching

## Fragile Areas

### app.py Monolithic Structure
- **Files:** `src/app.py` (1025 lines)
- **Why fragile:** Single file handles rendering, session state, mock data, JS injection
- **Safe modification:** Refactor into modules before changing core rendering logic
- **Test coverage:** Not explicitly tested (no test files found)

### Design System Tightly Coupled to Streamlit API
- **Files:** `src/design_system.py`
- **Why fragile:** Style functions return strings meant for Streamlit's `**style` parameter
- **Safe modification:** Can add new color/spacing variants; breaking changes require updating all style calls

### Database Schema Mismatch
- **Issue:** Schema comments mention MySQL but code uses SQLite
- **Files:** `src/database.py` lines 1-6, 1020 comment
- **Safe modification:** Add new tables/cOLUMNS; breaking changes require migration script

## Scaling Limits

### SQLite Storage Limit
- **Problem:** SQLite has a 140GB limit; for a public app with many users this will be hit
- **Current capacity:** Unknown (data/web_word.db exists but empty)
- **Limit:** ~140GB max
- **Scaling path:** Migrate to PostgreSQL or MySQL for production use

### No Rate Limiting
- **Problem:** No API call or user request limiting
- **Impact:** Can be abused for spam or resource exhaustion
- **Scaling path:** Add rate limiting middleware for LLM API calls

### Single Worker Deployment
- **Problem:** Streamlit runs in single-threaded mode by default
- **Impact:** Poor performance under concurrent user load
- **Scaling path:** Use Streamlit's `server.enableCORS=false` with proper reverse proxy for scaling

## Dependencies at Risk

### Streamlit PyPI Package
- **Risk:** No version pinning in requirements.txt
- **Impact:** Dependency updates could introduce breaking changes
- **Migration plan:** Pin streamlit and pandas to specific versions in requirements.txt

## Missing Critical Features

### LLM API Integration
- **Problem:** Core feature not implemented — users cannot get semantic decomposition from LLM
- **Blocks:** Cannot deliver on project's core value proposition
- **Priority:** High

### Environment Configuration Management
- **Problem:** No `.env` file or configuration management for environment-specific settings
- **Blocks:** Cannot properly manage API keys, database credentials, debug mode
- **Priority:** High

### Error Boundary / Recovery
- **Problem:** No graceful degradation when API calls fail
- **Blocks:** App becomes unusable if LLM service goes down (currently shows mock data)
- **Priority:** Medium

### Comprehensive Testing
- **Problem:** No test files found in repository
- **Blocks:** Cannot reliably verify refactoring doesn't break existing functionality
- **Priority:** High

## Test Coverage Gaps

### No Unit Tests
- **Untested area:** All Python functions in app.py and database.py
- **Files:** Entire source codebase lacks test coverage
- **Risk:** Breaking changes could go unnoticed
- **Priority:** High

### No Integration Tests
- **Untested area:** Database connections, session state management, mock data loading
- **Risk:** Integration issues only discovered in production
- **Priority:** Medium

### No End-to-End Tests
- **Untested area:** User flows (search verb → view results → submit feedback)
- **Risk:** UX issues go undetected until user reports
- **Priority:** Low

---

*Concerns audit: 2026-05-29*
