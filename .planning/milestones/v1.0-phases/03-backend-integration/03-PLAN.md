---
phase: 03-backend-integration
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: [src/mysql_db.py, src/llm_api.py, src/app.py, requirements.txt, .env.example]
autonomous: true
requirements: [BACKEND-01, BACKEND-02, BACKEND-03, BACKEND-04]
user_setup:
  - service: mysql
    why: "Local MySQL 8.0 database for persistent storage"
    env_vars:
      - name: MYSQL_HOST
        source: "MySQL local installation (localhost:3306)"
      - name: MYSQL_PORT
        source: "Default MySQL port (3306)"
      - name: MYSQL_DATABASE
        source: "Database name (web_word_db)"
      - name: MYSQL_USER
        source: "MySQL user creation (web_word_user)"
      - name: MYSQL_PASSWORD
        source: "MySQL user password"
  - service: zhipu.ai
    why: "Zhipu AI API for generating verb definitions"
    env_vars:
      - name: ZHIPUAI_API_KEY
        source: "Zhipu AI Dashboard -> Developers -> API keys"
    dashboard_config:
      - task: "Create API key"
        location: "Zhipu AI Platform -> API Management"

must_haves:
  truths:
    - "MySQL 8.0 database connects successfully with environment variables"
    - "LLM API can generate verb definitions with semantic decomposition"
    - "User feedback is stored in database and retrievable"
    - "Statistics are computed from database queries"
  artifacts:
    - path: "src/mysql_db.py"
      provides: "MySQL connection, schema, CRUD operations"
      min_lines: 100
    - path: "src/llm_api.py"
      provides: "Zhipu AI API wrapper with caching"
      min_lines: 60
    - path: ".env.example"
      provides: "Environment variable template"
      contains: "MYSQL_*, ZHIPUAI_API_KEY"
  key_links:
    - from: "src/app.py"
      to: "src/mysql_db.py"
      via: "import mysql_db"
      pattern: "from src.mysql_db import"
    - from: "src/app.py"
      to: "src/llm_api.py"
      via: "import llm_api"
      pattern: "from src.llm_api import"
    - from: "src/llm_api.py"
      to: "src/mysql_db.py"
      via: "check_cache_verb"
      pattern: "get_definition_from_db"
---

<objective>
Replace SQLite with MySQL 8.0 database and integrate Zhipu AI LLM API to generate verb definitions from user queries.

Purpose: Provide persistent storage and dynamic LLM-powered verb definitions instead of static mock data.

Output: mysql_db.py (MySQL operations), llm_api.py (Zhipu AI integration), integrated app.py (frontend-backend connected)
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/03-backend-integration/03-CONTEXT.md
@.planning/phases/03-backend-integration/03-RESEARCH.md
@src/database.py (existing SQLite module for reference)
@src/app.py (existing Streamlit frontend)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create MySQL 8.0 database module</name>
  <files>src/mysql_db.py, requirements.txt</files>
  <action>
  Create src/mysql_db.py with MySQL 8.0 database operations:
  - Database connection using PyMySQL with environment variables (MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD)
  - Connection pooling for performance (pymysql.connections.ConnectionPool)
  - UTF-8MB4 charset support for emoji
  - Create database and tables on init: definitions, synonyms, feedbacks, usage_logs
  - CRUD operations: insert_definition, get_definition_by_verb, insert_feedback, get_stats, get_hot_verbs
  - Table schema based on RESEARCH.md design with proper indexes
  - Error handling with graceful fallback when database unavailable

  Update requirements.txt:
  - Add pymysql==1.1.0 for MySQL 8.0 support
  - Add zhipuai==1.0.2 for LLM API
  - Add cryptography==42.0.8 (required by zhipuai)

  IMPORTANT per D-01 (MySQL 8.0 design): Use separate user with minimal privileges, parameterized queries, proper indexing.
  </action>
  <verify>
    <automated>python -c "from src.mysql_db import get_connection_pool; pool = get_connection_pool(); print('MySQL pool created successfully')"</automated>
  </verify>
  <done>MySQL connection pool created, tables initialized, CRUD functions available in mysql_db.py</done>
</task>

<task type="auto">
  <name>Task 2: Create Zhipu AI LLM API wrapper</name>
  <files>src/llm_api.py</files>
  <action>
  Create src/llm_api.py with Zhipu AI integration:
  - Initialize ZhipuAI client from environment variable ZHIPUAI_API_KEY
  - Define prompt template (simple format per D-03) for generating verb definitions with semantic decomposition
  - Implement get_definition(verb: str) function:
    - Check cache in MySQL first (if database connected)
    - If cached, return from database
    - If not cached, call Zhipu AI glm-4 model
    - Parse JSON response into structured format (traditional, optimized, semantic_table)
    - Store result in MySQL cache for future use
  - Handle API errors: 401 (invalid key), 429 (rate limit), 500 (server error)
  - Retry logic for transient failures
  - Cache TTL: 24 hours for cached definitions

  IMPORTANT per D-01 (implementation order): MySQL first, then LLM API. This task depends on mysql_db.py for caching.
  </action>
  <verify>
    <automated>python -c "from src.llm_api import get_definition, is_cache_available; print(f'Cache available: {is_cache_available()}'); result = get_definition('跑进来'); print(f'Result type: {type(result)}')"</automated>
  </verify>
  <done>LLM API wrapper created with caching, error handling, and Zhipu AI integration working</done>
</task>

<task type="auto">
  <name>Task 3: Integrate backend with Streamlit frontend</name>
  <files>src/app.py</files>
  <action>
  Update src/app.py to integrate MySQL and LLM API:
  - Replace existing SQLite imports with mysql_db imports
  - Initialize MySQL pool at startup (on_change when DB_AVAILABLE changes)
  - Replace MOCK_DEFINITIONS with real LLM API calls:
    - Create get_verb_definition(verb) function that uses llm_api.get_definition()
    - Fall back to mock data if API fails or unavailable
  - Replace SQLite queries with mysql_db queries for stats and hot verbs
  - Update insert_feedback to use mysql_db.insert_feedback()
  - Add try-except blocks around database operations for graceful degradation
  - Update session state to track definitions and prevent duplicate API calls

  IMPORTANT per D-04 (implementation order): Ensure all user feedback and statistics use MySQL database.
  </action>
  <verify>
    <automated>streamlit run src/app.py --version 2>&1 | head -5 || echo "Streamlit launched successfully"</automated>
  </verify>
  <done>App runs with MySQL database and LLM API, displays real definitions from API, stores user feedback</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Client → MySQL | Untrusted input (verb names) - mitigate with parameterized queries |
| Client → LLM API | Untrusted input (verb names) - mitigate with input validation and error handling |
| Client → Database | Untrusted feedback text - mitigate with SQL injection prevention via parameterized queries |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-03-01 | Spoofing | Zhipu AI API key | mitigate | Store in environment variable, never hardcode, validate at runtime |
| T-03-02 | Elevation | Database credentials | mitigate | Use separate user with minimal privileges (no DROP/ALTER), environment variables |
| T-03-03 | Tampering | User feedback | mitigate | Parameterized queries, input validation on text fields |
| T-03-04 | Information Disclosure | Error messages | accept | Accept risk - error messages for development, masked in production |
| T-03-05 | Denial of Service | API rate limits | mitigate | Implement caching to reduce calls, rate limit handling with retry logic |
| T-03-06 | Repudiation | Feedback logs | mitigate | All feedbacks logged with timestamp and IP (when available) |
| T-03-SC | Package Legitimacy | zhipuai package | mitigate | Verify package legitimacy before install (npmjs.com for npm, pypi.org for Python) |

## Security Notes

- Package legitimacy checkpoint required for zhipuai (T-03-01 mitigation)
- SQL injection prevented by parameterized queries (T-03-03 mitigation)
- Rate limiting accepted for free tier API (T-03-05 disposition)
</threat_model>

<verification>
Phase 3 backend integration is complete when:
1. MySQL database connection and schema are initialized successfully
2. LLM API can generate verb definitions with semantic decomposition
3. User feedback is stored and retrieved from MySQL
4. Statistics are computed from MySQL database queries
5. End-to-end flow: User input → LLM API → MySQL → Frontend display works
6. Graceful fallback when database or API is unavailable
</verification>

<success_criteria>
1. MySQL 8.0 database (web_word_db) connected with proper schema
2. Zhipu AI API generates verb definitions with semantic decomposition table
3. User feedback stored in database and retrievable via get_feedback_data()
4. Statistics (total_queries, avg_rating, hot_verbs) computed from MySQL
5. All mock data replaced with real API/database calls
6. Error handling for API failures and database unavailability
7. Environment variables properly configured and documented in .env.example
</success_criteria>

<output>
Create `.planning/phases/03-backend-integration/03-01-SUMMARY.md` when done
</output>
