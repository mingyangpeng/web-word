"""多供应商 LLM 配置数据层 —— llm_providers 表的建表、CRUD 与连通性测试。

职责边界：
  * 本文件只管 llm_providers 一张表的数据存取（管理面：管理员在页面上维护
    供应商档案），不发起任何正式的模型调用 —— 客户端构造与
    「DB 供应商优先 → .env 环境变量」的路由在 src/llm_api.py（四级降级链
    第一级的数据源就是本表的 get_default_provider）；
  * test_provider_connectivity 是唯一的主动外联（管理页「测试连接」按钮），
    发一次 max_tokens=1 的最小请求，不产生业务调用。

表设计（Agent MP-D 交付契约 DDL 原样）：
  * api_format ENUM('openai','anthropic')：openai 格式走 OpenAI SDK
    （chat.completions，兼容智谱/OpenAI/DeepSeek 等一切 OpenAI 风格网关）；
    anthropic 格式走 {base_url}/v1/messages（llm_api 内置零新依赖 HTTP
    客户端，anthropic SDK 不在 requirements.txt）；
  * models JSON：该供应商可用的模型名列表（如 ["glm-4", "glm-4-plus"]），
    llm_api 取第一个作为默认模型（调用方可显式指定）；
  * is_default 全表至多一行 =1（set_default 事务内「先清全部再设本条」
    保证）；且还需 enabled=1 才真正生效（get_default_provider 联合判定，
    管理员停用默认供应商即自动回落 .env 链）；
  * API Key 明文存储（管理决策）：数据层原样返回，页面层必须把可见性
    gate 到管理员角色，且绝不写入日志。

安全与容错口径（与 users_db 同款）：
  1. SQL 一律参数化；UPDATE 的 SET 列名来自代码内白名单常量，用户输入
     只进占位符参数，无注入面；
  2. 读函数失败返回空值（[]/None），写函数失败返回 0/False，绝不抛异常
     打崩页面；ensure_llm_provider_tables 失败只记日志 —— llm_api 可能在
     无 DB 的离线环境读取本模块，必须能静默降级。
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 建表 SQL（交付契约 DDL 原样）
# ============================================
PROVIDERS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS llm_providers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  base_url VARCHAR(500) NOT NULL,
  api_format ENUM('openai','anthropic') NOT NULL DEFAULT 'openai',
  api_key TEXT NOT NULL,
  models JSON NULL,                             -- ["model-a","model-b"]
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  is_default TINYINT(1) NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  created_by INT NULL,                          -- 建档人 users.id（软引用，无外键）
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_llm_providers_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

# api_format 应用层先拒（不依赖 MySQL ENUM 报错），非法值不进数据库
API_FORMATS = ("openai", "anthropic")

# update_provider 白名单：is_default 刻意不在列 —— 默认供应商的唯一性由
# set_default() 的事务（先清全部再设本条）保证，绕过它会破坏不变量。
_UPDATABLE_FIELDS = frozenset(
    {"name", "base_url", "api_format", "api_key", "models", "enabled", "sort_order"}
)

# 连通性测试超时（秒）——「测试连接」按钮不能让页面干等正式调用级别的 30s
CONNECTIVITY_TIMEOUT = int(os.getenv("LLM_CONNECT_TIMEOUT", "15"))


# ============================================
# 建表（幂等）
# ============================================

def ensure_llm_provider_tables() -> None:
    """建 llm_providers 表（幂等，可重复调用）。

    数据库不可用时只记日志不抛异常（与 ensure_user_tables 容错口径一致）：
    llm_api._get_db_provider 在无 DB 环境也会走到本模块，必须静默降级。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(PROVIDERS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"llm_providers 表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"llm_providers 表初始化意外错误: {e}")


# ============================================
# 行归一化
# ============================================

_PROVIDER_COLUMNS = (
    "id, name, base_url, api_format, api_key, models, "
    "enabled, is_default, sort_order, created_by, created_at"
)


def _models_from_raw(raw: Any) -> List[str]:
    """models 列的容错解析：JSON 串 / 原生 list → 去空白去空的 str 列表。

    脏数据（非法 JSON、非数组、混入非字符串项）按能取多少取多少处理，
    绝不抛异常 —— 一条脏行不能打崩供应商列表页。
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [item for item in raw if isinstance(item, str)]
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if isinstance(data, (list, tuple)):
            items = [item for item in data if isinstance(item, str)]
        elif isinstance(data, str):
            items = [data]  # 单字符串也接受（["glm-4"] 的误写形态）
        else:
            return []
    return [item.strip() for item in items if item.strip()]


def _row_to_provider(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """DB 行 → 供应商 dict（models 解析、开关列转 bool、id 列转 int）。"""
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "base_url": row["base_url"],
        "api_format": row["api_format"],
        # API Key 明文原样返回（管理决策：页面层 gate 到管理员、不落日志）
        "api_key": row["api_key"],
        "models": _models_from_raw(row.get("models")),
        "enabled": bool(int(row.get("enabled") or 0)),
        "is_default": bool(int(row.get("is_default") or 0)),
        "sort_order": int(row.get("sort_order") or 0),
        "created_by": int(row["created_by"]) if row.get("created_by") is not None else None,
        "created_at": row.get("created_at"),
    }


# ============================================
# 查询
# ============================================

def list_providers(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """全部供应商（按 sort_order, id 升序 —— 管理页展示顺序）。

    Args:
        enabled_only: True 只返回 enabled=1 的供应商。

    Returns:
        list[dict]：供应商列表；数据库不可用返回 []。
    """
    sql = f"SELECT {_PROVIDER_COLUMNS} FROM llm_providers"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY sort_order, id"
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [dict(p) for p in (_row_to_provider(row) for row in rows) if p]
    except pymysql.Error as e:
        logger.error(f"查询供应商列表失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询供应商列表意外错误: {e}")
        return []


def get_provider(provider_id: int) -> Optional[Dict[str, Any]]:
    """按 id 取单个供应商；不存在 / id 非法 / 数据库不可用返回 None。"""
    if not isinstance(provider_id, int) or isinstance(provider_id, bool) \
            or provider_id <= 0:
        logger.error(f"get_provider 拒绝非法 provider_id: {provider_id!r}")
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {_PROVIDER_COLUMNS} FROM llm_providers WHERE id = %s",
                (provider_id,),
            )
            return _row_to_provider(cursor.fetchone())
    except pymysql.Error as e:
        logger.error(f"查询供应商 {provider_id} 失败（MySQL）: {e}")
        return None
    except Exception as e:
        logger.error(f"查询供应商 {provider_id} 意外错误: {e}")
        return None


def get_default_provider() -> Optional[Dict[str, Any]]:
    """当前生效的默认供应商（is_default=1 AND enabled=1）。

    llm_api 四级降级链第一级的数据源：无默认、默认被停用、表未建、
    库不可用 —— 一律 None，调用方回落 .env 环境变量链。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {_PROVIDER_COLUMNS} FROM llm_providers "
                "WHERE is_default = 1 AND enabled = 1 "
                "ORDER BY sort_order, id LIMIT 1"
            )
            return _row_to_provider(cursor.fetchone())
    except pymysql.Error as e:
        logger.error(f"查询默认供应商失败（MySQL）: {e}")
        return None
    except Exception as e:
        logger.error(f"查询默认供应商意外错误: {e}")
        return None


# ============================================
# 写入
# ============================================

def create_provider(name: str, base_url: str, api_format: str, api_key: str,
                    models: Optional[List[str]] = None,
                    created_by: Optional[int] = None) -> int:
    """新建供应商（enabled=1，is_default=0，sort_order=0），返回新 id。

    Args:
        name: 供应商名（UNIQUE，重复返回 0）。
        base_url: 网关根地址。openai 格式即 OpenAI SDK 的 base_url
            （如 https://open.bigmodel.cn/api/paas/v4）；anthropic 格式为
            /v1/messages 的宿主根（如 https://api.anthropic.com）。
        api_format: 'openai' | 'anthropic'（大小写不敏感，非法返回 0）。
        api_key: 明文 API Key（管理决策：明文存储，页面层 gate 可见性）。
        models: 模型名列表（None/空 → NULL；llm_api 取第一个为默认模型）。
        created_by: 建档人 users.id（审计留痕，可 None）。

    Returns:
        int: 新供应商 id；参数非法 / 重名 / 数据库错误返回 0。
    """
    name = str(name or "").strip()
    base_url = str(base_url or "").strip()
    api_key = str(api_key or "").strip()
    fmt = str(api_format or "").lower()
    if not name or not base_url or not api_key:
        logger.error("create_provider 需要非空 name / base_url / api_key")
        return 0
    if fmt not in API_FORMATS:
        logger.error(f"create_provider 拒绝非法 api_format: {api_format!r}"
                     f"（须为 {'/'.join(API_FORMATS)}）")
        return 0
    if created_by is not None:
        if isinstance(created_by, bool) or not isinstance(created_by, int) \
                or created_by <= 0:
            logger.error(f"create_provider 拒绝非法 created_by: {created_by!r}")
            return 0
    if models is None or (isinstance(models, (list, tuple)) and not list(models)):
        models_json: Optional[str] = None
    elif isinstance(models, (list, tuple)):
        cleaned = [str(m).strip() for m in models if str(m).strip()]
        if not cleaned:
            models_json = None
        else:
            models_json = json.dumps(cleaned, ensure_ascii=False)
    else:
        logger.error(f"create_provider 拒绝非法 models（须为列表或 None）: {models!r}")
        return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO llm_providers (name, base_url, api_format, api_key, "
                "models, enabled, is_default, sort_order, created_by) "
                "VALUES (%s, %s, %s, %s, %s, 1, 0, 0, %s)",
                (name, base_url, fmt, api_key, models_json, created_by),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        # e 只有 SQL 错误信息（如 Duplicate entry 'xxx'），不含 api_key
        logger.error(f"创建供应商 '{name}' 失败: {e}")
        return 0
    except Exception as e:
        logger.error(f"创建供应商 '{name}' 意外错误: {e}")
        return 0


def _coerce_update_values(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """白名单字段值归一化为可入库形态；任一非法返回 None（整体拒绝）。"""
    coerced: Dict[str, Any] = {}
    for key, value in updates.items():
        if key == "models":
            if value is None:
                coerced[key] = None
                continue
            if not isinstance(value, (list, tuple)):
                return None
            cleaned = [str(m).strip() for m in value if str(m).strip()]
            coerced[key] = json.dumps(cleaned, ensure_ascii=False) if cleaned else None
        elif key == "api_format":
            fmt = str(value or "").lower()
            if fmt not in API_FORMATS:
                return None
            coerced[key] = fmt
        elif key == "enabled":
            coerced[key] = 1 if value else 0
        elif key == "sort_order":
            try:
                coerced[key] = int(value)
            except (TypeError, ValueError):
                return None
        else:  # name / base_url / api_key
            text = str(value or "").strip()
            if not text:
                return None
            coerced[key] = text
    return coerced


def update_provider(provider_id: int, **kwargs) -> bool:
    """更新供应商的白名单字段：name / base_url / api_format / api_key /
    models / enabled / sort_order。

    is_default 刻意不在白名单 —— 默认供应商的唯一性由 set_default() 的
    事务保证，页面「设为默认」请调 set_default(provider_id)。

    Args:
        provider_id: 供应商 id。
        **kwargs: 白名单字段（见上）。models 传 None 或空列表清空；
            api_format 大小写不敏感；任一字段非法则整体拒绝（False）。

    Returns:
        bool: 实际变更为 True；无合法字段 / 字段值非法 / 供应商不存在 /
        目标值与现值相同（MySQL 不计变更行，与 set_role「未变更= False」
        口径一致）/ 数据库错误为 False。
    """
    if not isinstance(provider_id, int) or isinstance(provider_id, bool) \
            or provider_id <= 0:
        logger.error(f"update_provider 拒绝非法 provider_id: {provider_id!r}")
        return False
    updates: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if key not in _UPDATABLE_FIELDS:
            logger.error(f"update_provider 拒绝非白名单字段: {key!r}"
                         "（is_default 请走 set_default）")
            return False
        updates[key] = value
    if not updates:
        logger.error("update_provider 没有可更新字段")
        return False
    coerced = _coerce_update_values(updates)
    if coerced is None:
        logger.error(f"update_provider 字段值非法，整体拒绝: {list(kwargs)}")
        return False
    # SET 列名来自代码内白名单常量，值全部走占位符 —— 无注入面
    set_clause = ", ".join(f"{col} = %s" for col in coerced)
    params = tuple(coerced.values()) + (provider_id,)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"UPDATE llm_providers SET {set_clause} WHERE id = %s", params
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        # e 只有 SQL 错误信息，不含 api_key
        logger.error(f"更新供应商 {provider_id} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"更新供应商 {provider_id} 意外错误: {e}")
        return False


def delete_provider(provider_id: int) -> bool:
    """物理删除供应商；删除成功 / 供应商不存在 / 非法 id 为 False。"""
    if not isinstance(provider_id, int) or isinstance(provider_id, bool) \
            or provider_id <= 0:
        logger.error(f"delete_provider 拒绝非法 provider_id: {provider_id!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute("DELETE FROM llm_providers WHERE id = %s", (provider_id,))
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"删除供应商 {provider_id} 失败: {e}")
        return False
    except Exception as e:
        logger.error(f"删除供应商 {provider_id} 意外错误: {e}")
        return False


def set_enabled(provider_id: int, enabled: bool) -> bool:
    """启用（True）/ 停用（False）供应商。

    停用默认供应商即令其退出生效链（get_default_provider 要求 enabled=1），
    llm_api 自动回落 .env —— 页面停用后无需额外操作。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE llm_providers SET enabled = %s WHERE id = %s",
                (1 if enabled else 0, provider_id),
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"修改供应商 {provider_id} 启停状态失败: {e}")
        return False
    except Exception as e:
        logger.error(f"修改供应商 {provider_id} 启停状态意外错误: {e}")
        return False


def set_default(provider_id: int) -> bool:
    """把供应商设为全表唯一默认（事务内先清全部 is_default 再设本条）。

    只动 is_default，不改 enabled —— 目标供应商若处于停用态，
    get_default_provider 会按「is_default=1 AND enabled=1」判为无默认
    （回落 .env）。页面应引导先 set_enabled(id, True) 再设默认。

    Returns:
        bool: 设默认成功为 True；供应商不存在 / 数据库错误为 False
        （失败时旧默认保持不变 —— 事务回滚）。
    """
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute("SELECT id FROM llm_providers WHERE id = %s", (provider_id,))
            if cursor.fetchone() is None:
                logger.error(f"set_default 供应商不存在: {provider_id}")
                return False
            cursor.execute("UPDATE llm_providers SET is_default = 0 WHERE is_default = 1")
            cursor.execute(
                "UPDATE llm_providers SET is_default = 1 WHERE id = %s",
                (provider_id,),
            )
            if cursor.rowcount <= 0:  # 防御：前一行存在却更新不到（并发删除等）
                raise pymysql.Error("默认标记更新未生效")
    except pymysql.Error as e:
        logger.error(f"设置默认供应商 {provider_id} 失败（事务已回滚）: {e}")
        return False
    except Exception as e:
        logger.error(f"设置默认供应商 {provider_id} 意外错误: {e}")
        return False
    return True


# ============================================
# 连通性测试（管理页「测试连接」按钮；唯一的主动外联）
# ============================================

def http_post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any],
                   timeout: int = CONNECTIVITY_TIMEOUT) -> Tuple[int, str]:
    """POST 一个 JSON 请求，返回 (status_code, body_text)。

    HTTP 层优先 httpx（openai / zhipuai SDK 自带依赖），缺环境回退
    requests（requirements.txt 既有依赖）—— 本模块零新增依赖。
    网络层异常（DNS 失败 / 超时 / 连接拒绝）向上抛，由调用方决定降级口径。
    """
    try:
        import httpx
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        return resp.status_code, resp.text
    except ImportError:
        pass
    import requests
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    return resp.status_code, resp.text


def test_provider_connectivity(provider_id: int) -> Dict[str, Any]:
    """对供应商发一次 max_tokens=1 的最小请求，测试连通性与鉴权。

    openai 格式 POST {base_url}/chat/completions（与 OpenAI SDK 追加路径的
    行为一致）；anthropic 格式 POST {base_url}/v1/messages（带
    anthropic-version 头）。模型取 models 第一个 —— 未配置模型无法构造
    最小请求，如实报错而非误报连通。

    Returns:
        dict: {"ok": bool, "status_code": int|None, "latency_ms": int,
        "model": str|None, "error": str|None}。
        ok=True 当且仅当收到 HTTP 响应且状态码 < 400；401/403 给出鉴权
        失败说明，404 提示检查 base_url，网络异常 status_code=None。
    """
    result: Dict[str, Any] = {
        "ok": False,
        "status_code": None,
        "latency_ms": 0,
        "model": None,
        "error": None,
    }
    provider = get_provider(provider_id)
    if provider is None:
        result["error"] = f"供应商不存在: {provider_id}"
        return result
    models = provider.get("models") or []
    model = models[0] if models else None
    result["model"] = model
    if not model:
        result["error"] = "未配置模型（models 为空），无法发起连通性测试"
        return result

    base = str(provider["base_url"] or "").rstrip("/")
    api_key = provider["api_key"] or ""
    if (provider.get("api_format") or "openai") == "anthropic":
        url = f"{base}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    else:
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
    payload = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }

    started = time.monotonic()
    try:
        status_code, body = http_post_json(url, headers, payload, CONNECTIVITY_TIMEOUT)
    except Exception as e:  # noqa: BLE001 —— 网络层任何异常都折算成测试失败
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        result["error"] = f"网络错误: {e}"
        return result
    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    result["status_code"] = status_code
    if status_code in (401, 403):
        result["error"] = f"认证失败（HTTP {status_code}）：API Key 无效或无权限"
    elif status_code == 404:
        result["error"] = (f"HTTP 404：接口路径不存在，请检查 base_url="
                           f"{provider['base_url']}")
    elif status_code >= 400:
        snippet = (body or "")[:200]
        result["error"] = f"HTTP {status_code}：{snippet}"
    else:
        result["ok"] = True
    return result
