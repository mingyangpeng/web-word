# Phase 3: 后端集成 CONTEXT

**Created:** 2026-05-29
**Phase:** 3 - 后端集成

---

## Domain

This phase implements backend services to support the English synonym verb definition tool:
- MySQL 8.0 database for persistent storage (replacing SQLite)
- Zhipu AI (智谱 AI) LLM API integration for generating verb definitions
- User feedback storage and statistics retrieval
- Database migration from SQLite to MySQL 8.0

---

## Locked Requirements

From REQUIREMENTS.md (Phase 3 scope):
- **BACKEND-01**: MySQL 8.0 数据库设计
- **BACKEND-02**: 大模型 API 集成（提示词工程）
- **BACKEND-03**: 用户反馈存储到数据库
- **BACKEND-04**: 统计数据查询接口

---

## Decisions

### 1. LLM API Provider
**Decision:** Use 智谱 AI (Zhipu AI)

**Rationale:**
- 国内可用，无需配置代理
- API 价格合理，适合学习场景
- 提供与 OpenAI 兼容的 SDK 接口
- 支持中文理解和生成

**Implementation Notes:**
- Use Zhipu AI SDK or HTTP API directly
- API key stored in environment variable: `ZHIPUAI_API_KEY`
- Model selection: `glm-4` (latest available)

---

### 2. Database Migration
**Decision:** Create new MySQL 8.0 database (not migrate existing SQLite)

**Rationale:**
- Clean slate for database design
- Avoid conflicts with existing SQLite development
- Separate development and production databases
- Easier to implement proper MySQL 8.0 features

**Implementation Notes:**
- Database name: `web_word_db`
- Create at local MySQL instance (port 3306) for development
- Schema to be designed in Phase 3
- Replace SQLite operations with MySQL equivalents

---

### 3. Prompt Template Style
**Decision:** Simple and clear format initially (will be refined later)

**Rationale:**
- Faster to implement MVP
- Can be iteratively improved based on usage
- Matches current frontend mock data format

**Format to use:**
```
动词: {verb}
中文释义: {definition}
语义分解:
- 方式: {manner}
- 方向: {direction}
- 体相: {aspect}
- 范围: {scope}
```

**Future refinement:** Will update prompt based on user feedback and actual usage data.

---

### 4. Implementation Priority
**Decision:** Complete MySQL 8.0 implementation first, LLM API integration second

**Rationale:**
- Database is foundational for persistent storage
- User feedback system depends on database
- Statistics display depends on database queries
- LLM API can work with SQLite temporarily during database setup

**Implementation Order:**
1. Set up MySQL 8.0 database and connection
2. Create database schema
3. Migrate/replace SQLite operations with MySQL
4. Implement LLM API integration
5. Test end-to-end flow

---

## Canonical Refs

- `.planning/PROJECT.md` - Project context and architecture
- `.planning/REQUIREMENTS.md` - Phase 3 requirements (BACKEND-01 through BACKEND-04)
- `.planning/ROADMAP.md` - Phase 3 goals and success criteria
- `.planning/STATE.md` - Project state tracking
- `src/database.py` - Existing SQLite database module (to be replaced)
- `requirements.txt` - Python dependencies

---

## Codebase Context

### Existing Assets
- `src/database.py` - SQLite implementation with CRUD operations
- `data/web_word.db` - Current SQLite database file
- `src/app.py` - Streamlit frontend (currently uses mock data)

### To Create
- `src/mysql_db.py` - New MySQL 8.0 database module
- `src/llm_api.py` - Zhipu AI API integration module
- `.env` - Environment variables for API keys and database config
- `init_db_mysql.sql` - MySQL database initialization script

### Dependencies to Add
- `pymysql` - MySQL driver
- `cryptography` - Required by Zhipu AI SDK
- `zhipuai` - Zhipu AI Python SDK

---

## Open Questions (Deferred)

1. **Database host:** Local MySQL on localhost:3306 or remote?
2. **Database credentials:** Will use environment variables for flexibility
3. **LLM model parameters:** Temperature, max_tokens - start with defaults
4. **Error handling:** What to do when API fails or database is unavailable?
5. **Rate limiting:** Any constraints on API usage?

---

## Success Criteria

Phase 3 is complete when:
1. MySQL 8.0 database is set up and accessible
2. Database schema matches requirements
3. All CRUD operations work correctly
4. LLM API can generate verb definitions
5. User feedback is stored and retrieved
6. Statistics are computed from database
7. End-to-end flow: User input → LLM API → Database → Frontend display
