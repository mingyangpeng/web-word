# Phase 3: 后端集成 Research

**Created:** 2026-05-29

## MySQL 8.0 Design

### Database Schema

#### Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `definitions` | 存储动词释义和语义分解 | id, verb (PK), chinese_ndef, semantic_table, example_sentence |
| `synonyms` | 存储近义词关系 | id, original_verb_id (FK), synonym_verb (FK) |
| `feedbacks` | 存储用户反馈 | id, verb, rating, feedback_text, created_at |
| `statistics` | 存储统计数据 | id, total_queries, avg_rating, total_feedbacks, last_updated |
| `usage_logs` | 记录查询日志 | id, verb, query_time, device_info |

**Schema Design Rationale:**
- `definitions` table stores the core verb information with semantic decomposition
- `synonyms` table stores relationships between related verbs
- `feedbacks` table stores user ratings and comments
- `statistics` table for real-time statistics (can be computed on-the-fly)
- `usage_logs` for analytics and debugging

### Indexing Strategy

```sql
-- Index on frequently queried columns
CREATE INDEX idx_definitions_verb ON definitions(verb);
CREATE INDEX idx_feedbacks_verb ON feedbacks(verb);
CREATE INDEX idx_feedbacks_created_at ON feedbacks(created_at);
CREATE INDEX idx_synonyms_original ON synonyms(original_verb_id);
CREATE INDEX idx_synonyms_synonym ON synonyms(synonym_verb_id);
```

### Connection Configuration

- **Host:** `localhost` (development) or configurable
- **Port:** `3306`
- **Database Name:** `web_word_db`
- **User:** `web_word_user` (separate user for security)
- **Password:** Environment variable `MYSQL_PASSWORD`
- **Charset:** `utf8mb4` (for emoji support)
- **Collation:** `utf8mb4_unicode_ci`

### Migration Strategy

1. **Backup existing SQLite data:**
   ```bash
   cp data/web_word.db data/web_word_db_backup_$(date +%Y%m%d).db
   ```

2. **Migrate data if needed:**
   ```python
   # SQLite → MySQL migration script
   INSERT INTO definitions SELECT * FROM queries WHERE verb = ...
   ```

3. **Drop SQLite after migration:** Only if all data successfully migrated

## Zhipu AI (智谱 AI) Integration

### API Authentication

**How to get API key:**
1. Visit https://open.bigmodel.cn/
2. Register account and create API key
3. Store key in environment variable: `ZHIPUAI_API_KEY`

**Authentication Method:**
- Use `zhipuai` Python SDK: `from zhipuai import ZhipuAI`
- Or direct HTTP API with Bearer token

```python
from zhipuai import ZhipuAI

client = ZhipuAI(api_key="your-api-key-here")
response = client.chat.completions.create(
    model="glm-4",
    messages=[
        {"role": "system", "content": "你是一个中文释义助手..."},
        {"role": "user", "content": "请解释动词 'look'"}
    ]
)
```

**Error Codes and Handling:**
- `401`: Invalid API key
- `429`: Rate limit exceeded
- `500`: Internal server error
- `503`: Service unavailable

### API Endpoints

**Chat Completion API:**
- **Endpoint:** `https://open.bigmodel.cn/api/paas/v4/chat/completions`
- **Model:** `glm-4` (latest)
- **Request Format:**
  ```json
  {
    "model": "glm-4",
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "..."}
    ],
    "temperature": 0.7,
    "max_tokens": 500
  }
  ```

**Response Format:**
```json
{
  "id": "chatcmpl-...",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "动词 'look' 的中文释义：\n..."
    }
  }]
}
```

**Rate Limits:**
- Default: Check Zhipu AI official documentation
- Typically: 1000 calls/day for free tier
- Consider caching responses for same verbs

### Prompt Engineering

**Suggested Prompt Template:**
```
你是一个中文释义助手。请解释以下英语动词，并提供语义分解：

动词：{verb}

要求：
1. 用简体中文回答
2. 包含：中文释义、语义分解（方式、方向、体相、范围）
3. 提供一个例句
4. 如果有近义词，简要说明差异

请以 JSON 格式返回：
{
  "chinese_ndef": "中文释义",
  "semantic_table": {
    "manner": "方式",
    "direction": "方向",
    "aspect": "体相",
    "scope": "范围"
  },
  "example": "例句",
  "synonyms": ["近义词1", "近义词2"]
}
```

**Configuration Options:**
- `temperature`: 0.7 (for balanced creativity and accuracy)
- `max_tokens`: 500 (enough for definition and decomposition)
- `top_p`: 0.9 (nucleus sampling)

## Code Architecture

### Module Structure

```
src/
├── database.py          # MySQL 数据库操作
├── llm_api.py           # Zhipu AI API 封装
├── api.py               # FastAPI 后端接口
└── app.py               # Streamlit 前端
```

**File Responsibilities:**
- `database.py`: Database connection, CRUD operations, migrations
- `llm_api.py`: LLM API calls, response parsing, caching
- `api.py`: RESTful API endpoints (for potential frontend-backend separation)
- `app.py`: Streamlit UI with integrated backend calls

### Environment Variables

**Required:**
- `MYSQL_HOST`: MySQL server host
- `MYSQL_PORT`: MySQL port (default: 3306)
- `MYSQL_DATABASE`: Database name
- `MYSQL_USER`: Database user
- `MYSQL_PASSWORD`: Database password
- `ZHIPUAI_API_KEY`: Zhipu AI API key

**Optional:**
- `MYSQL_POOL_SIZE`: Connection pool size (default: 5)
- `LLM_TIMEOUT`: API call timeout (default: 30s)
- `LLM_CACHE_DIR`: Cache directory for responses

### Security Considerations

1. **API Key Management:**
   - Never hardcode API keys
   - Use environment variables
   - Never commit `.env` file

2. **Database Security:**
   - Use separate user with minimal privileges
   - Use parameterized queries (prevent SQL injection)
   - Enable SSL for production connections

3. **Error Handling:**
   - Catch API errors gracefully
   - Log errors for debugging
   - Provide user-friendly error messages

### Frontend-Backend Communication

**Streamlit 方式 (直接集成):**
```python
# 在 app.py 中直接调用
from llm_api import get_definition
from database import save_feedback, get_stats

# 调用 LLM API
result = get_definition("look")

# 存储到数据库
save_feedback("look", 5, "很好")

# 获取统计数据
stats = get_stats()
```

**FastAPI 方式 (分离后端):**
```python
# api.py 中定义接口
@app.post("/api/definition")
def get_definition(verb: str):
    result = llm_api.get_definition(verb)
    return {"verb": verb, "result": result}

# app.py 中调用
response = requests.post("http://localhost:8000/api/definition", json={"verb": "look"})
```

**Recommendation:** Start with direct integration (Streamlit + functions) for simplicity. Consider FastAPI later if frontend needs more control.
