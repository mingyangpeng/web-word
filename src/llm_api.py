"""
Zhipu AI (智谱 AI) LLM API Wrapper

提供大模型 API 调用、响应解析和缓存功能。
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

# Try to import ZhipuAI SDK
try:
    from zhipuai import ZhipuAI
    ZHIPUAI_AVAILABLE = True
except ImportError:
    ZHIPUAI_AVAILABLE = False
    logging.warning("ZhipuAI SDK not available. Install with: pip install zhipuai")

# Try to import MySQL for caching
try:
    from src.mysql_db import get_definition_by_verb, insert_definition, get_db_cursor
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    logging.warning("MySQL module not available, caching disabled")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# Configuration
# ============================================
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "500"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

# Cache configuration
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))

# ============================================
# Prompt Template
# ============================================
PROMPT_TEMPLATE = """你是一个中文释义助手。请解释以下中文动词，并提供语义分解。

动词：{verb}

要求：
1. 用简体中文回答
2. 包含：传统释义、优化释义（带语义分解表）
3. 提供一个例句
4. 如果有近义词，简要说明差异

请以 JSON 格式返回：
{{
  "chinese_ndef": "中文释义",
  "semantic_table": {{
    "manner": "方式（运动采用的姿势/手段）",
    "direction": "方向（运动朝向的终点/目标）",
    "aspect": "体相（运动时身体的姿态/状态）",
    "scope": "范围（运动的范围/程度）"
  }},
  "example": "例句",
  "synonyms": ["近义词1", "近义词2"]
}}
"""

# ============================================
# LLM Client
# ============================================
_client = None

def get_zhipuai_client():
    """
    Get or create ZhipuAI client.

    Returns:
        ZhipuAI client instance or None if unavailable
    """
    global _client

    if _client is not None:
        return _client

    if not ZHIPUAI_AVAILABLE:
        logger.warning("ZhipuAI SDK not available")
        return None

    if not ZHIPUAI_API_KEY:
        logger.warning("ZHIPUAI_API_KEY not set")
        return None

    try:
        _client = ZhipuAI(api_key=ZHIPUAI_API_KEY)
        logger.info("ZhipuAI client initialized successfully")
        return _client

    except Exception as e:
        logger.error(f"Failed to initialize ZhipuAI client: {e}")
        return None


# ============================================
# Cache Management
# ============================================
def _get_cache_key(verb: str) -> str:
    """
    Generate a cache key for a verb.

    Args:
        verb: The verb to cache

    Returns:
        MD5 hash string
    """
    return hashlib.md5(verb.lower().encode()).hexdigest()


def is_cache_available() -> bool:
    """
    Check if caching is available.

    Returns:
        bool: True if MySQL caching is available
    """
    return MYSQL_AVAILABLE


def get_definition_from_cache(verb: str) -> Optional[Dict[str, Any]]:
    """
    Get definition from cache.

    Args:
        verb: The verb to look up

    Returns:
        Cached definition or None if not found/expired
    """
    if not MYSQL_AVAILABLE:
        return None

    try:
        # Check database for cached definition
        # For now, we'll store the full response in the semantic_table column as a JSON object
        result = get_definition_by_verb(verb)

        if result and 'semantic_table' in result:
            # semantic_table is a dict with semantic components
            # We need to also store the full response structure
            # Let's enhance the database structure or store in comments

            # Check if response is fresh (within TTL)
            created_at = result.get('created_at')
            if created_at:
                cache_time = datetime.fromisoformat(str(created_at))
                age = datetime.now() - cache_time

                if age < timedelta(hours=CACHE_TTL_HOURS):
                    logger.debug(f"Cache hit for verb: {verb}")
                    return result

        return None

    except Exception as e:
        logger.error(f"Error checking cache for '{verb}': {e}")
        return None


def save_definition_to_cache(verb: str, result: Dict[str, Any]) -> bool:
    """
    Save definition to cache.

    Args:
        verb: The verb to cache
        result: The result dictionary to cache

    Returns:
        bool: True if successful
    """
    if not MYSQL_AVAILABLE:
        logger.warning("MySQL not available, cannot cache")
        return False

    try:
        # Save to MySQL
        return insert_definition(
            verb=verb,
            chinese_ndef=result.get('chinese_ndef', ''),
            semantic_table=result.get('semantic_table', {}),
            example_sentence=result.get('example', ''),
            model_version=LLM_MODEL
        )

    except Exception as e:
        logger.error(f"Error saving to cache: {e}")
        return False


# ============================================
# Main API Functions
# ============================================
def get_definition(verb: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get definition for a verb from LLM API with caching.

    Args:
        verb: The verb to define
        force_refresh: If True, skip cache and call API directly

    Returns:
        Dictionary containing definition data or None if failed
    """
    if not verb or not verb.strip():
        logger.warning("Empty verb provided")
        return None

    # Check cache first (unless force_refresh)
    if not force_refresh:
        cached = get_definition_from_cache(verb)
        if cached:
            return cached

    # Call LLM API
    result = _call_llm_api(verb)

    # Save to cache if successful
    if result:
        save_definition_to_cache(verb, result)
        logger.info(f"Got definition for '{verb}' from LLM API")

    return result


def _call_llm_api(verb: str) -> Optional[Dict[str, Any]]:
    """
    Call Zhipu AI API to get definition.

    Args:
        verb: The verb to define

    Returns:
        Dictionary containing definition data or None if failed
    """
    client = get_zhipuai_client()
    if not client:
        logger.error("ZhipuAI client not available")
        return None

    try:
        # Prepare prompt
        prompt = PROMPT_TEMPLATE.format(verb=verb)

        logger.info(f"Calling Zhipu AI API for verb: {verb}")

        # Call API
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个中文释义助手，基于运动事件类型学为中文动词提供优化释义。"},
                {"role": "user", "content": prompt}
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            timeout=LLM_TIMEOUT
        )

        # Parse response
        content = response.choices[0].message.content.strip()

        logger.info(f"Received response from Zhipu AI for '{verb}'")

        return _parse_llm_response(content, verb)

    except Exception as e:
        logger.error(f"LLM API call failed for '{verb}': {e}")
        return None


def _parse_llm_response(content: str, verb: str) -> Optional[Dict[str, Any]]:
    """
    Parse LLM response into structured format.

    Args:
        content: Raw response text from LLM
        verb: The original verb

    Returns:
        Parsed dictionary or None if parsing fails
    """
    try:
        # Try to extract JSON from response
        # Sometimes LLM includes markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        # Ensure required fields exist
        result = {
            "verb": verb,
            "chinese_ndef": data.get("chinese_ndef", ""),
            "semantic_table": data.get("semantic_table", {}),
            "example": data.get("example", ""),
            "synonyms": data.get("synonyms", []),
            "raw_response": content
        }

        logger.debug(f"Parsed response for '{verb}': {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Raw content: {content}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing response: {e}")
        return None


# ============================================
# Batch Definition Generation
# ============================================
def generate_batch_definitions(verbs: List[str]) -> Dict[str, Any]:
    """
    Generate definitions for multiple verbs.

    Args:
        verbs: List of verbs to define

    Returns:
        Dictionary with results and errors
    """
    results = {
        "successful": [],
        "failed": [],
        "errors": {}
    }

    for verb in verbs:
        result = get_definition(verb, force_refresh=False)
        if result:
            results["successful"].append(result)
        else:
            results["failed"].append(verb)
            results["errors"][verb] = "Failed to generate definition"

    logger.info(f"Batch generation complete: {len(results['successful'])} successful, {len(results['failed'])} failed")

    return results


# ============================================
# Synonym Query
# ============================================
def get_synonyms_for_verb(verb: str) -> List[str]:
    """
    Get synonyms for a verb from LLM or cache.

    Args:
        verb: The verb to get synonyms for

    Returns:
        List of synonym verbs
    """
    try:
        result = get_definition(verb)

        if result and result.get("synonyms"):
            return result["synonyms"]
        else:
            logger.info(f"No synonyms found for '{verb}'")
            return []

    except Exception as e:
        logger.error(f"Error getting synonyms for '{verb}': {e}")
        return []


# ============================================
# Fallback Definitions
# ============================================
def get_fallback_definition(verb: str) -> Optional[Dict[str, Any]]:
    """
    Get a simple fallback definition when LLM is unavailable.

    Args:
        verb: The verb to define

    Returns:
        Simple dictionary with fallback content
    """
    return {
        "verb": verb,
        "chinese_ndef": f"动词「{verb}」的释义",
        "semantic_table": {
            "manner": "待生成",
            "direction": "待生成",
            "aspect": "待生成",
            "scope": "待生成"
        },
        "example": f"例如：{verb}表示...（需要接入大模型API获取详细释义）",
        "synonyms": [],
        "raw_response": f"Fallback definition for '{verb}'"
    }


# ============================================
# Error Handling
# ============================================
class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass


class APIKeyError(LLMError):
    """Exception when API key is missing or invalid."""
    pass


class RateLimitError(LLMError):
    """Exception when rate limit is exceeded."""
    pass


def handle_llm_error(error: Exception, verb: str) -> None:
    """
    Handle LLM API errors gracefully.

    Args:
        error: The exception that occurred
        verb: The verb that caused the error
    """
    if isinstance(error, APIKeyError):
        logger.error(f"API key error for '{verb}': {error}")
    elif isinstance(error, RateLimitError):
        logger.warning(f"Rate limit exceeded for '{verb}': {error}")
    elif hasattr(error, 'status_code'):
        if error.status_code == 401:
            raise APIKeyError(f"Invalid API key for '{verb}'")
        elif error.status_code == 429:
            raise RateLimitError(f"Rate limit exceeded for '{verb}'")
        elif error.status_code == 500:
            logger.error(f"Server error for '{verb}': {error}")
        elif error.status_code == 503:
            logger.error(f"Service unavailable for '{verb}': {error}")
    else:
        logger.error(f"Unexpected error for '{verb}': {error}")
