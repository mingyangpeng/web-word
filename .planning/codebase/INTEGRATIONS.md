# External Integrations

**Analysis Date:** 2026/05/29

## APIs & External Services

**Not yet integrated (planned):**
- Large Model API (OpenAI SDK planned)
  - Purpose: Generate verb definitions with semantic decomposition
  - Alternative providers mentioned: DeepSeek, 智谱 AI (Zhipu)
  - Target: Replace MOCK_DEFINITIONS with real API calls
  - Location: app.py comments indicate this is pending work

**Data Export:**
- CSV export - Local file download (pandas to_csv)
  - Format: UTF-8 with BOM (utf-8-sig)
  - Data: verb, rating, feedback_text, created_at
  - Location: src/app.py lines 684-693

## Data Storage

**Databases:**
- SQLite 3 (Local file)
  - Connection: Direct file connection (data/web_word.db)
  - Client: sqlite3 (built-in)
  - Tables:
    - queries (id, verb, traditional_text, optimized_text, semantic_table, model_version, created_at)
    - feedbacks (id, query_id, verb, rating, feedback_text, created_at)
  - Indexes: verb, created_at, query_id
  - Location: src/database.py

**File Storage:**
- Local filesystem - Screenshot images
  - Locations: browser_screenshot.png, streamlit_screenshot.png, screenshots_* directories

## Authentication & Identity

**Not implemented:**
- No authentication system
- No user identification
- Anonymous query and feedback collection

## Monitoring & Observability

**Not implemented:**
- No error tracking service
- No application performance monitoring
- No logging service
- Manual fallback: st.warning() for database connection failures

## CI/CD & Deployment

**Hosting:**
- Hugging Face Spaces (recommended deployment target)
  - Free hosting for Streamlit applications
  - Auto-deployment from GitHub

**CI Pipeline:**
- Not configured (no GitHub Actions workflows found)
- Manual deployment process

## Environment Configuration

**Required env vars:**
- Not currently used (no environment variable loading in codebase)
- Could be added for API keys when LLM integration is implemented

**Secrets location:**
- Not present (no .env files detected)
- Future: API keys should be stored in environment variables

## Webhooks & Callbacks

**Incoming:**
- None configured

**Outgoing:**
- None configured

## Database Schema

**queries table:**
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- verb: TEXT NOT NULL
- traditional_text: TEXT (nullable)
- optimized_text: TEXT (nullable)
- semantic_table: TEXT (JSON stored as string)
- model_version: TEXT DEFAULT 'mock'
- created_at: TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- Indexes: idx_queries_verb, idx_queries_created_at

**feedbacks table:**
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- query_id: INTEGER (foreign key to queries.id)
- verb: TEXT NOT NULL
- rating: INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5)
- feedback_text: TEXT (nullable)
- created_at: TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- Indexes: idx_feedbacks_verb, idx_feedbacks_query_id

---

*Integration audit: 2026/05/29*
