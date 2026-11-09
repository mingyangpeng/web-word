"""
多供应商 LLM API Wrapper（智谱 / OpenAI / DeepSeek / DB 自定义供应商）

提供大模型 API 调用、响应解析和缓存功能。提供商路由按四级降级链：

  1. DB 供应商 —— llm_providers 表 is_default=1 AND enabled=1 的供应商
     （src/llm_providers_db.py，管理页可维护），按 api_format 构造客户端；
  2/3. .env 环境变量链 —— ZHIPUAI_API_KEY → OPENAI_API_KEY / DEEPSEEK_API_KEY
     （语义与 DB 层引入前逐字节一致，保留为降级路径，删除风险为零）；
  4. 调用方兜底 —— 无任何提供商时 get_definition 返回 None，
     app 层落 get_fallback_definition（五要素「待生成」形态）。
"""

import os
import json
import time
import logging
import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional, Dict, Any, List

# Try to import ZhipuAI SDK
try:
    from zhipuai import ZhipuAI
    ZHIPUAI_AVAILABLE = True
except ImportError:
    ZHIPUAI_AVAILABLE = False
    logging.warning("ZhipuAI SDK not available. Install with: pip install zhipuai")

# Try to import MySQL for caching
try:
    from src.mysql_db import get_definition_by_verb, insert_definition
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
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")  # 兼容旧引用；实际读取见 get_zhipuai_client()
LLM_MODEL = os.getenv("ZHIPUAI_MODEL") or os.getenv("LLM_MODEL", "glm-4")
# .env 默认模型名快照：DB 供应商生效期间 LLM_MODEL 会被同步改写为该供应商
# 的首个模型（semantic_search 等旧调用方直接读 llm_api.LLM_MODEL），
# reset_llm_client() 时恢复到这里保存的 .env 值。
_DEFAULT_LLM_MODEL = LLM_MODEL
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
2. 分别给出两个独立的文本块：
   - traditional（传统词典式释义，一段自然语言描述）
   - optimized（优化释义，基于运动事件类型学对语义要素进行分解的解释，一段自然语言描述）
3. 提供 semantic_table 语义分解字典，键为五元模型：manner（方式）、path（路径）、direction（方向）、aspect（体相）、scope（范围）
4. 提供一个例句
5. 如果有近义词，简要说明差异

请以 JSON 格式返回：
{{
  "traditional": "传统词典式释义（自然语言段落）",
  "optimized": "优化释义（语义分解释义，自然语言段落）",
  "chinese_ndef": "中文释义（与 traditional 一致或为其精简版）",
  "semantic_table": {{
    "manner": "方式（运动采用的姿势/手段）",
    "path": "路径（运动经过的空间轨迹）",
    "direction": "方向（运动朝向的终点/目标）",
    "aspect": "体相（运动时身体的姿态/状态）",
    "scope": "范围（运动的范围/程度）"
  }},
  "example": "例句",
  "synonyms": ["近义词1", "近义词2"]
}}
"""

# ============================================
# LLM Client —— 多提供商接入（DB 供应商 → 智谱 → OpenAI/DeepSeek）
# ============================================
# 四级降级链（本模块负责前三级；第四级是调用方兜底释义 get_fallback_definition）：
#   1. DB 供应商：llm_providers 表 is_default=1 AND enabled=1
#      （src/llm_providers_db.py，管理页可维护）。api_format 分流：
#        * openai    → OpenAI SDK + base_url（兼容一切 OpenAI 风格网关）
#        * anthropic → _AnthropicCompatClient 直调 {base_url}/v1/messages
#                      （anthropic SDK 不在 requirements.txt，零新依赖）
#      模型名取 provider.models JSON 的第一个。读取失败（表未建/库不可用/
#      无默认）静默回落 —— llm_api 可能被无 DB 的离线环境 import，DB 层
#      绝不能抛异常打崩调用路径。
#   2/3. .env 环境变量链（语义不变，保留为降级路径，删除风险为零）：
#      * ZHIPUAI_API_KEY（+ 可选 ZHIPUAI_BASE_URL 自定义网关）—— 智谱 SDK
#      * OPENAI_API_KEY（+ 可选 OPENAI_BASE_URL）—— openai SDK
#      * DEEPSEEK_API_KEY —— openai SDK + api.deepseek.com
#   4. 全部不可用 → (None, "")，调用方走兜底。
# LLM_PROVIDER 可强制指定：zhipu/openai/deepseek 钉死 .env 对应家（跳过 DB
# 层，操作员显式覆盖语义不变）；"db" 钉死 DB 供应商（不可用不降级）；
# 缺省 = DB 优先。
# 模型名：DB 供应商取 models[0]（并同步 LLM_MODEL 全局，旧调用方
# semantic_search 直读 llm_api.LLM_MODEL 也能拿到正确值）；.env 链沿用
# ZHIPUAI_MODEL / OPENAI_MODEL / DEEPSEEK_MODEL 或统一的 LLM_MODEL（默认 glm-4）。
_client = None
_client_provider = ""
_client_model = ""          # 当前生效客户端应使用的模型名（"" → 回落 LLM_MODEL）

# DB 供应商读取结果的短 TTL 缓存：无缓存客户端可用时（如未配任何 key 的
# 兜底路径）避免每次调用都打一次 SELECT。管理页改配置后调 reset_llm_client()
# 立即生效，否则至多延迟 _DB_PROVIDER_TTL_SECONDS 秒。
_DB_PROVIDER_TTL_SECONDS = float(os.getenv("LLM_DB_PROVIDER_TTL_SECONDS", "5"))
_db_provider_cache: Dict[str, Any] = {"valid": False, "read_at": 0.0, "provider": None}


def _openai_sdk_available():
    """openai SDK 是否可导入（离线环境 False，调用方降级到 HTTP 兜底路径）。"""
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


# --------------------------------------------
# 第 1 级：DB 供应商（llm_providers 表）
# --------------------------------------------
def _get_db_provider() -> Optional[Dict[str, Any]]:
    """读 llm_providers 表 is_default=1 AND enabled=1 的供应商配置。

    表未建 / 库不可用 / llm_providers_db 不可导入（离线模式）/ 无默认供应商
    → None（调用方走 .env 环境变量降级），绝不抛异常。结果带短 TTL 缓存
    （_DB_PROVIDER_TTL_SECONDS，默认 5s）；reset_llm_client() 立即失效。

    Returns:
        dict | None: 供应商配置（id/name/base_url/api_format/api_key/models/
        enabled/is_default/sort_order/created_by/created_at）；无默认供应商
        或读取失败为 None。
    """
    now = time.monotonic()
    if _db_provider_cache["valid"] and \
            (now - _db_provider_cache["read_at"]) < _DB_PROVIDER_TTL_SECONDS:
        return _db_provider_cache["provider"]
    provider = None
    try:
        from src import llm_providers_db  # 延迟导入：离线环境不阻塞本模块 import
        provider = llm_providers_db.get_default_provider()
    except Exception as e:  # noqa: BLE001 —— 任何失败都静默降级到 .env
        logger.info(f"llm_providers 读取失败，走 .env 降级: {e}")
        provider = None
    _db_provider_cache["valid"] = True
    _db_provider_cache["read_at"] = now
    _db_provider_cache["provider"] = provider
    return provider


def _first_model_of(provider: Dict[str, Any]) -> str:
    """DB 供应商 models 列表的第一个模型名（空 / 脏数据返回 ""）。"""
    for item in (provider.get("models") or []):
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


class _AnthropicCompatClient:
    """把 Anthropic Messages API（POST {base_url}/v1/messages）包装成
    OpenAI chat.completions 风格客户端。

    供 DB 供应商 api_format='anthropic' 使用。anthropic SDK 不在
    requirements.txt，HTTP 层复用 llm_providers_db.http_post_json
    （httpx 优先、requests 兜底）—— 零新依赖。

    只覆盖本仓库调用面用到的子集：
      client.chat.completions.create(model=, messages=[{role, content}, ...],
                                     temperature=, max_tokens=, timeout=)
      → response.choices[0].message.content
    system 消息映射为顶层 system 参数，其余消息原样透传。
    """

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, base_url: str, api_key: str,
                 timeout: Optional[int] = None):
        """按 DB 供应商配置装配兼容客户端（chat.completions.create 挂到 _create）。"""
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = int(timeout or LLM_TIMEOUT)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model: str, messages: Optional[List[Dict[str, Any]]] = None,
                temperature: Optional[float] = None,
                max_tokens: Optional[int] = None,
                timeout: Optional[int] = None, **kwargs) -> SimpleNamespace:
        """发 Anthropic Messages 请求并包成 OpenAI 风格响应（SimpleNamespace）。"""
        from src.llm_providers_db import http_post_json  # 延迟导入（同降级口径）

        if not self.base_url:
            raise LLMError("anthropic 格式 DB 供应商 base_url 为空")
        system_parts: List[str] = []
        rest: List[Dict[str, Any]] = []
        for msg in (messages or []):
            if msg.get("role") == "system":
                system_parts.append(str(msg.get("content") or ""))
            else:
                rest.append({"role": msg.get("role"), "content": msg.get("content")})
        payload: Dict[str, Any] = {
            "model": model,
            "messages": rest,
            "max_tokens": int(max_tokens or LLM_MAX_TOKENS),  # Anthropic 必填
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        status_code, body = http_post_json(
            f"{self.base_url}/v1/messages", headers, payload,
            int(timeout or self.timeout),
        )
        if status_code >= 400:
            raise LLMError(f"Anthropic API HTTP {status_code}: {(body or '')[:200]}")
        try:
            data = json.loads(body or "{}")
        except ValueError as e:
            raise LLMError(f"Anthropic API 响应非 JSON: {e}") from e
        text = "".join(
            block.get("text", "") for block in (data.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=text, role="assistant")
            )],
            model=data.get("model") or model,
            raw=data,
        )


def _build_db_provider_client(provider: Dict[str, Any]):
    """按 DB 供应商 api_format 构造客户端；失败返回 None（继续 .env 降级）。"""
    name = provider.get("name", "?")
    api_format = str(provider.get("api_format") or "openai").lower()
    api_key = provider.get("api_key") or ""
    base_url = str(provider.get("base_url") or "").strip()
    if not api_key or not base_url:
        logger.error(f"DB 供应商 {name} 缺 api_key/base_url，跳过并走 .env 降级")
        return None
    if api_format == "anthropic":
        try:
            return _AnthropicCompatClient(base_url, api_key, timeout=LLM_TIMEOUT)
        except Exception as e:
            logger.error(f"DB 供应商 {name} anthropic 客户端构造失败: {e}")
            return None
    # openai 兼容格式（缺省）：OpenAI SDK + base_url
    if not _openai_sdk_available():
        logger.error(f"DB 供应商 {name} 为 openai 格式但 openai SDK 未安装")
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=base_url, timeout=LLM_TIMEOUT)
    except Exception as e:
        logger.error(f"DB 供应商 {name} OpenAI 客户端构造失败: {e}")
        return None


def get_llm_model() -> str:
    """当前生效客户端应使用的模型名。

    DB 供应商生效时为其 models 第一个；.env 链 / 无客户端时回落 LLM_MODEL
    （.env 默认）。调用方一律用本函数取模型名，不要再直读 LLM_MODEL。
    """
    return _client_model or LLM_MODEL


def _sync_llm_model_global() -> None:
    """DB 供应商生效时把模块级 LLM_MODEL 同步为其首个模型。

    semantic_search 等旧调用方在 get_llm_client() 之后直读
    ``llm_api.LLM_MODEL``（拿不到 _client_model 内部态），同步全局才能让
    它们把正确模型名传给 DB 客户端；reset_llm_client() 恢复 .env 默认值。
    """
    global LLM_MODEL
    if _client_model and _client_model != LLM_MODEL:
        logger.info(f"LLM_MODEL 全局同步为 DB 供应商模型: {_client_model}")
        LLM_MODEL = _client_model


def reset_llm_client() -> None:
    """清空客户端与 DB 供应商缓存（llm_providers 管理页改配置后调用）。

    * _client/_client_provider/_client_model 归零，下次 get_llm_client() 重建；
    * _get_db_provider 的 TTL 缓存失效，下次立即重读 llm_providers 表；
    * LLM_MODEL 恢复为 .env 默认值（DB 供应商生效期间可能被同步改写）。
    """
    global _client, _client_provider, _client_model, LLM_MODEL
    _client = None
    _client_provider = ""
    _client_model = ""
    LLM_MODEL = _DEFAULT_LLM_MODEL
    _db_provider_cache["valid"] = False
    _db_provider_cache["read_at"] = 0.0
    _db_provider_cache["provider"] = None
    logger.info("LLM client 缓存已重置（下次调用重新按 DB → .env 链选择提供商）")


def get_zhipuai_client():
    """兼容旧名：返回当前配置的 LLM 客户端
    （可能是 DB/智谱/OpenAI/DeepSeek 之一）。"""
    return get_llm_client()


def get_llm_client():
    """Get or create the LLM client，四级降级链自动选择。

    优先级：DB 供应商（llm_providers 表默认启用项）→ 智谱 → OpenAI/DeepSeek
    → (None, "")。LLM_PROVIDER 可强制指定（见模块头注释）。

    Returns:
        (client, provider) 元组；均不可用时 (None, "")。provider 为
        "db:{name}" / "zhipu" / "openai" / "deepseek"。
        旧调用方只取 client 的兼容用法见 get_zhipuai_client()。
    """
    global _client, _client_provider, _client_model

    if _client is not None:
        return _client, _client_provider

    forced = os.getenv("LLM_PROVIDER", "").lower()

    # --- 1. DB 供应商（llm_providers 表，管理页维护；读取失败静默回落）---
    if forced in ("", "db"):
        db_provider = _get_db_provider()
        if db_provider is not None:
            client = _build_db_provider_client(db_provider)
            if client is not None:
                _client = client
                _client_provider = f"db:{db_provider.get('name', '?')}"
                _client_model = _first_model_of(db_provider) or LLM_MODEL
                _sync_llm_model_global()
                logger.info(
                    f"LLM client: {_client_provider} "
                    f"(api_format={db_provider.get('api_format')}, "
                    f"base_url={db_provider.get('base_url')}, model={_client_model})"
                )
                return _client, _client_provider
            # 构造失败（SDK 缺失 / 配置缺字段）→ 继续走 .env 降级链

    # --- 2. 智谱（ZhipuAI SDK，支持自定义网关；语义与引入 DB 层前一致）---
    if forced in ("", "zhipu", "zhipuai"):
        api_key = os.getenv("ZHIPUAI_API_KEY") or os.getenv("ZHIPU_API_KEY") or ""
        if api_key and ZHIPUAI_AVAILABLE:
            try:
                base_url = os.getenv("ZHIPUAI_BASE_URL") or ""
                kwargs = {"api_key": api_key}
                if base_url:
                    kwargs["base_url"] = base_url
                _client = ZhipuAI(**kwargs)
                _client_provider = "zhipu"
                _client_model = LLM_MODEL
                logger.info(f"LLM client: zhipu (base_url={base_url or 'default'})")
                return _client, _client_provider
            except Exception as e:
                logger.error(f"Failed to initialize ZhipuAI client: {e}")

    # --- 3. OpenAI / DeepSeek（openai SDK，OpenAI 兼容）---
    if forced in ("", "openai", "deepseek") and _openai_sdk_available():
        candidates = [
            ("openai", os.getenv("OPENAI_API_KEY") or "",
             os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"),
            ("deepseek", os.getenv("DEEPSEEK_API_KEY") or "",
             os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"),
        ]
        if forced == "openai":
            candidates = [candidates[0]]
        elif forced == "deepseek":
            candidates = [candidates[1]]
        for provider, api_key, base_url in candidates:
            if not api_key:
                continue
            try:
                from openai import OpenAI
                _client = OpenAI(api_key=api_key, base_url=base_url,
                                 timeout=LLM_TIMEOUT)
                _client_provider = provider
                _client_model = LLM_MODEL
                logger.info(f"LLM client: {provider} (base_url={base_url})")
                return _client, _client_provider
            except Exception as e:
                logger.error(f"Failed to initialize {provider} client: {e}")

    logger.warning("没有可用的 LLM 提供商（llm_providers 表无启用中的默认供应商，"
                   "且需配置 ZHIPUAI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY "
                   "之一）")
    return None, ""


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
                    # 归一化成与 LLM 结果一致的形状，调用方才能按同一组键取值
                    return {
                        "verb": verb,
                        "chinese_ndef": result.get("chinese_ndef", ""),
                        "traditional": result.get("chinese_ndef", ""),
                        "optimized": result.get("chinese_ndef", ""),
                        "semantic_table": result.get("semantic_table") or {},
                        "example": result.get("example_sentence") or "",
                        "synonyms": [],
                        "raw_response": result.get("raw_response"),
                        "_cache_hit": True,
                    }

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
        # Save to MySQL（model_version 记录实际生效的模型，DB 供应商时是其首个模型）
        return insert_definition(
            verb=verb,
            chinese_ndef=result.get('chinese_ndef', ''),
            semantic_table=result.get('semantic_table', {}),
            example_sentence=result.get('example', ''),
            model_version=get_llm_model()
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
    Call the configured LLM provider (DB 供应商 / 智谱 / OpenAI / DeepSeek)
    for a definition.

    Args:
        verb: The verb to define

    Returns:
        Dictionary containing definition data or None if failed
    """
    client, provider = get_llm_client()
    if not client:
        logger.error("LLM client not available")
        return None

    try:
        # Prepare prompt
        prompt = PROMPT_TEMPLATE.format(verb=verb)

        logger.info(f"Calling {provider} API for verb: {verb}")

        # Call API（OpenAI 兼容 chat.completions 签名；DB 的 anthropic 供应商
        # 由 _AnthropicCompatClient 在客户端内部做协议转换，调用方无感）
        response = client.chat.completions.create(
            model=get_llm_model(),  # DB 供应商 → models[0]；.env 链 → LLM_MODEL
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

        logger.info(f"Received response from {provider} for '{verb}'")

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
            "traditional": data.get("traditional", ""),
            "optimized": data.get("optimized", ""),
            "chinese_ndef": data.get("chinese_ndef", ""),
            "semantic_table": data.get("semantic_table", {}),
            "example": data.get("example", ""),
            "synonyms": data.get("synonyms", []),
            "raw_response": content
        }

        logger.debug("Parsed response for '%s': %s", verb,
                     json.dumps(result, ensure_ascii=False, indent=2))
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

    logger.info(
        "Batch generation complete: %d successful, %d failed",
        len(results['successful']), len(results['failed'])
    )

    return results


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
        # 五元模型必须齐全。修正前这里缺 "path"，而 app.py 的
        # get_semantic_table_for_verb 会读 semantic_table["path"]，
        # 缺失时该行永远显示「待生成」，误导用户以为路径要素无法解析。
        "semantic_table": {
            "manner": "待生成",
            "path": "待生成",
            "direction": "待生成",
            "aspect": "待生成",
            "scope": "待生成",
        },
        "example": "",
        "synonyms": [],
        "raw_response": f"Fallback definition for '{verb}'",
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
