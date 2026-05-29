# Coding Conventions

**Analysis Date:** 2026-05-29

## Naming Patterns

### Files

**Python files:**
- Pattern: `lowercase_with_underscores.py`
- Example: `app.py`, `database.py`, `design_system.py`
- Test files: Not present (no test infrastructure)

**Configuration files:**
- Pattern: `lowercase_with_underscores.toml` (TOML)
- Example: `.streamlit/config.toml`

### Functions

**Function names:**
- Pattern: `snake_case` with descriptive verbs
- Example: `render_card_prototype()`, `get_stats()`, `insert_feedback()`

**Function prefixes:**
- `render_*` - Returns HTML for UI components
- `get_*` - Retrieves data from database or returns computed values
- `insert_*` - Adds records to database
- `init_*` - Initializes resources

### Variables

**Variable names:**
- Pattern: `snake_case`
- Example: `DB_AVAILABLE`, `semantic_data`, `header_style`

**Constants:**
- Pattern: `UPPER_SNAKE_CASE`
- Example: `PRIMARY_COLOR`, `SPACE_XS`, `MOCK_DEFINITIONS`

### Types

**Type hints:**
- Pattern: Modern Python type hints (PEP 585 union syntax)
- Example: `def insert_feedback(verb: str, rating: int, feedback_text: str = None) -> int:`
- Union types: `dict | None`, `list[dict]`

### Modules

**Imports:**
- Pattern: `from src.module import *` for related items
- Example: `from src.database import init_db, insert_query, get_stats`
- Path management: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))`

## Code Style

**Formatting:**
- Tool: Manual with no explicit formatter (no `black`, `flake8`, etc. in requirements)
- PEP 8 compliant (verified with `python3 -m py_compile`)
- 2-space indentation

**Docstrings:**
- Pattern: Triple-quoted strings (`"""`) for module and function documentation
- Format: Summary line, then detailed Args/Returns sections
- Example:
  ```python
  def render_semantic_table(semantic_data):
      """
      渲染语义分解表，带 emoji 和颜色编码。

      Args:
          semantic_data: 二维列表 [[类型, emoji, 描述], ...]

      Returns:
          HTML 格式的语义表
      """
  ```

**Comments:**
- Pattern: `# ====` section headers for logical grouping
- Language: English for code comments, Chinese for user-facing documentation
- Example:
  ```python
  # ============================================
  # 数据库初始化（连接失败时降级为无数据库模式）
  # ============================================
  ```

## Import Organization

**Order:**
1. Standard library imports (`sys`, `os`, `json`, `datetime`, `sqlite3`)
2. Third-party imports (`streamlit`, `pandas`)
3. Local module imports (relative imports)

**Example from `src/app.py`:**
```python
import sys
import os
import streamlit as st
import pandas as pd

from src.database import init_db, insert_query, insert_feedback
from src.design_system import HEADER_H1, HEADER_H2, ...
```

**Path Aliases:**
- No path aliases configured (uses relative imports)
- Root directory added to `sys.path` in `app.py`

## Error Handling

**Patterns:**
- Try/except with fallback for optional features (database connection)
- Example:
  ```python
  DB_AVAILABLE = False
  try:
      init_db()
      DB_AVAILABLE = True
  except Exception as e:
      st.warning(f"数据库未连接，使用离线模式：{e}")
  ```

**Logging:**
- Approach: Streamlit native feedback (`st.success()`, `st.warning()`, `st.error()`)
- No external logging library used

## Module Design

**Exports:**
- Pattern: Functions and classes exported at module level
- No explicit `__all__` defined
- Example from `src/database.py`:
  ```python
  def init_db():
      ...

  def insert_query(...) -> int:
      ...

  def get_stats() -> dict:
      ...
  ```

**Barrel Files:** Not used - each module is self-contained

**Private functions:**
- Pattern: Single underscore prefix for internal functions
- Example: `_get_connection()` in `database.py`

## Type Hints

**Usage:**
- Function parameters: Annotated with types (`verb: str`, `rating: int`)
- Return types: Annotated where appropriate (`-> None`, `-> int`, `-> dict`, `-> list[dict]`)
- Union types: Modern `A | B` syntax (Python 3.10+)

**Example:**
```python
def insert_feedback(verb: str, rating: int, feedback_text: str = None,
                    query_id: int = None) -> int:
    """插入一条用户反馈，返回自增 ID。"""
    ...
```

## Database Layer Conventions

**File:** `src/database.py`

**Patterns:**
- Connection management: Context manager with `get_cursor(commit=False)`
- Connection factory: `_get_connection()` for database connection creation
- Parameterized queries: All SQL uses `?` placeholders to prevent SQL injection
- Row factory: `sqlite3.Row` for dictionary-like row access

**Transaction handling:**
```python
@contextmanager
def get_cursor(commit=False):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
```

## Design System Conventions

**File:** `src/design_system.py`

**Patterns:**
- Centralized constants: Colors, spacing, fonts all defined at module level
- Helper functions: Each style function returns CSS strings
- Documentation: Each function has docstring with Args/Returns

**Color system:**
- Hex format with no alpha channel
- Semantic color naming: `PRIMARY_COLOR`, `SUCCESS_COLOR`, etc.
- Comments include contrast ratios (WCAG AA compliance)

**Spacing system:**
- 8px base unit: `SPACE_XS=8`, `SPACE_SM=16`, `SPACE_MD=24`, `SPACE_LG=32`, `SPACE_XL=48`

---

*Convention analysis: 2026-05-29*
