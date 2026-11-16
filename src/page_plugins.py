"""页面与功能开关数据层（批次 62）——页面级/功能级启停的单一事实源。

是什么（用户需求「所有页面需要在账号管理中心支持开启或关闭；页面内的功能
启用也要在管理中做开关设置」）：
    两张自持表（self-ensure，与 module_plugins 同 philosophy）：
      page_plugins     一行一页：page_key（PAGE_KEYS）＋ enabled ＋ 留痕；
                       侧边栏隐藏＋直访拦截（与模块闸 fail-closed 叠加）；
      feature_plugins  一行一功能：feature_key ＋ page_key ＋ 双语 label ＋
                       enabled ＋ 留痕；页面渲染点按 is_feature_enabled 取闸。

底线豁免（禁停三键，与 module_plugins 的豁免纪律同构）：
    * search      兜底首页（导航回退/残留页重置的落点）——停它等于锁死导航；
    * help        全员可达的兜底出口（帮助不该有门槛）；
    * users_admin 账号管理页宿主——开关管理段所在页，停它=管理员自锁。
    三键 UI 勾选框置灰＋读侧恒按启用判定（直库写 0 也不拦导航）。

fail-open 口径（继承 module_plugins/tool_settings 的容错纪律）：
    表缺失/读失败/键未知 → 恒启用——开关基础设施故障不允许把功能锁死；
    仅 set_* 写路径与管理界面真实感知表状态。

功能注册表 FEATURE_SPECS：
    功能开关是**代码声明的常量清单**（key/page/双语 label/默认值）——
    建表时 seed 进 feature_plugins（INSERT IGNORE，升级零自伤）；渲染点
    is_feature_enabled(fkey) 查表，未知键按 default 放行（渐进式：新增
    功能未建行也能渲染）。

权限：set_* 走 require_role_interactive({"sys_admin", "dict_admin"})——
    与 module_plugins.set_module_enabled 同款（词典管理员兼判，legacy admin
    经映射必然两位一体）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.db_utils import as_int
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# 底线豁免三键（禁停；读侧恒启用）
LOCKED_PAGES = ("search", "help", "users_admin")

PAGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS page_plugins (
    page_key     VARCHAR(40)  NOT NULL PRIMARY KEY,
    enabled      TINYINT(1)   NOT NULL DEFAULT 1,
    enabled_by   BIGINT       NULL,
    enabled_at   DATETIME     NULL,
    updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                 ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

FEATURES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS feature_plugins (
    feature_key  VARCHAR(60)  NOT NULL PRIMARY KEY,
    page_key     VARCHAR(40)  NOT NULL,
    label_zh     VARCHAR(120) NOT NULL,
    label_en     VARCHAR(120) NOT NULL,
    enabled      TINYINT(1)   NOT NULL DEFAULT 1,
    enabled_by   BIGINT       NULL,
    enabled_at   DATETIME     NULL,
    updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                 ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_feature_page (page_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# 功能注册表（代码声明的常量清单——seed 与管理界面共用同一事实源）
# key 命名：页面键.功能语义；label 双语供管理界面直接渲染（不走 i18n 字典——
# 开关行是配置数据不是界面文案，随表行落库）。
FEATURE_SPECS: List[Dict[str, str]] = [
    {"key": "search.examples", "page": "search",
     "zh": "📚 示例库（方式/路径/体相三标签）", "en": "📚 Example Library (manner/path/aspect tabs)"},
    {"key": "search.feedback", "page": "search",
     "zh": "💬 反馈与评分区", "en": "💬 Feedback & Rating"},
    {"key": "search.relations", "page": "search",
     "zh": "🕸️ 词与词关系区块", "en": "🕸️ Word Relations block"},
    {"key": "search.stats", "page": "search",
     "zh": "📊 侧边栏 Experiment Stats", "en": "📊 Sidebar Experiment Stats"},
    {"key": "search.hot_verbs", "page": "search",
     "zh": "🔥 热门查询动词（侧边栏）", "en": "🔥 Hot Verbs (sidebar)"},
    {"key": "graph.cluster_browse", "page": "graph",
     "zh": "🗂️ 按词簇浏览区", "en": "🗂️ Browse by Cluster"},
    {"key": "corpus.collocation_edit", "page": "corpus",
     "zh": "✏️ 搭配明细人工归类（可编辑区）", "en": "✏️ Collocation manual categorisation (editable)"},
    {"key": "domain.corpus_evidence", "page": "domain",
     "zh": "📈 义位语料证据区", "en": "📈 Sense corpus evidence"},
]



# ============================================
# 读缓存（批次 62 review-2：每 rerun 5-10 个开关小查询收敛为 30s 一次）
# ============================================
# 进程级 TTL 缓存：{cache_key: (取数时刻, 值)}。set_* 写路径主动失效本表
# 缓存键——管理界面切换即时可见（rerun 后读新值）；其他进程（8501 容器
# 独立进程）有 ≤30s 延迟——开关是非关键配置，容忍。
_CACHE_TTL = 30
_read_cache: dict = {}


def _cache_get(key: str):
    import time

    hit = _read_cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key: str, value) -> None:
    import time

    _read_cache[key] = (time.time(), value)


def _cache_invalidate() -> None:
    """写路径主动失效（同进程内切换即时生效）。"""
    _read_cache.clear()


def _actor_id(actor: Any) -> Any:
    """actor（登录用户 dict）→ users.id（脏值清洗为 None）。"""
    return as_int((actor or {}).get("id")) if isinstance(actor, dict) else None


def ensure_page_plugins_tables() -> bool:
    """两表自持创建＋功能默认行 seed（INSERT IGNORE 升级零自伤）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(PAGES_TABLE_SQL)
            cursor.execute(FEATURES_TABLE_SQL)
            for spec in FEATURE_SPECS:
                cursor.execute(
                    "INSERT IGNORE INTO feature_plugins "
                    "(feature_key, page_key, label_zh, label_en, enabled) "
                    "VALUES (%s, %s, %s, %s, 1)",
                    (spec["key"], spec["page"], spec["zh"], spec["en"]),
                )
        return True
    except Exception as e:  # pymysql.Error 兜 Exception——fail-open 口径不抛
        logger.error(f"page_plugins 表初始化失败: {e}")
        return False


def is_page_enabled(page_key: str) -> bool:
    """页面闸（fail-open）：表缺/读失败/豁免键/未知键 → True。"""
    if page_key in LOCKED_PAGES:
        return True
    cache_key = f"page:{page_key}"
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT enabled FROM page_plugins WHERE page_key = %s", (page_key,))
            row = cursor.fetchone()
    except Exception as e:
        logger.warning(f"页面开关读取失败（按启用降级）: {e}")
        return True
    if row is None:
        result = True  # 未登记页默认启用
    else:
        result = bool(as_int(row.get("enabled")))
    _cache_put(cache_key, result)
    return result


def disabled_pages() -> set:
    """停用页集合（侧边栏批量过滤用；fail-open 空集；30s 缓存）。"""
    hit = _cache_get("disabled_pages")
    if hit is not None:
        return hit
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT page_key FROM page_plugins WHERE enabled = 0")
            rows = cursor.fetchall() or []
    except Exception as e:
        logger.warning(f"停用页集合读取失败（按全启用降级）: {e}")
        return set()
    result = {str(r.get("page_key")) for r in rows if r.get("page_key")}
    _cache_put("disabled_pages", result)
    return result


def set_page_enabled(page_key: str, enabled: bool, actor: Any) -> bool:
    """置页面开关（底线三键拒绝；未知页键拒绝——开关面只对 PAGE_KEYS 开放）。"""
    if page_key in LOCKED_PAGES:
        logger.warning(f"拒绝停用底线页 {page_key}（LOCKED_PAGES）")
        return False
    from src.page_guides import PAGE_KEYS  # 惰性导入（page_guides 零重依赖纪律）
    if page_key not in PAGE_KEYS:
        logger.warning(f"拒绝设置未知页面开关 {page_key}（不在 PAGE_KEYS）")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO page_plugins (page_key, enabled, enabled_by, enabled_at) "
                "VALUES (%s, %s, %s, NOW()) "
                "ON DUPLICATE KEY UPDATE enabled = VALUES(enabled), "
                "enabled_by = VALUES(enabled_by), enabled_at = VALUES(enabled_at)",
                (page_key, 1 if enabled else 0, _actor_id(actor)),
            )
        _cache_invalidate()
        return True
    except Exception as e:
        logger.error(f"页面开关写入失败 {page_key}: {e}")
        return False


def list_page_settings() -> List[Dict[str, Any]]:
    """页面开关清单（管理界面渲染；fail-open 空表）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT page_key, enabled, enabled_by, enabled_at "
                "FROM page_plugins ORDER BY page_key")
            return cursor.fetchall() or []
    except Exception as e:
        logger.warning(f"页面开关清单读取失败: {e}")
        return []


def is_feature_enabled(feature_key: str) -> bool:
    """功能闸（fail-open）：表缺/读失败/键未知 → True（渐进式，新增功能零配置可渲染）。"""
    cache_key = f"feat:{feature_key}"
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT enabled FROM feature_plugins WHERE feature_key = %s",
                (feature_key,))
            row = cursor.fetchone()
    except Exception as e:
        logger.warning(f"功能开关读取失败（按启用降级）: {e}")
        return True
    if row is None:
        result = True
    else:
        result = bool(as_int(row.get("enabled")))
    _cache_put(cache_key, result)
    return result


def set_feature_enabled(feature_key: str, enabled: bool, actor: Any) -> bool:
    """置功能开关（未知键拒绝——开关面只对 FEATURE_SPECS 开放）。"""
    if not any(s["key"] == feature_key for s in FEATURE_SPECS):
        logger.warning(f"拒绝设置未知功能开关 {feature_key}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE feature_plugins SET enabled = %s, enabled_by = %s, "
                "enabled_at = NOW() WHERE feature_key = %s",
                (1 if enabled else 0, _actor_id(actor), feature_key),
            )
        _cache_invalidate()
        return True
    except Exception as e:
        logger.error(f"功能开关写入失败 {feature_key}: {e}")
        return False


def list_feature_settings() -> List[Dict[str, Any]]:
    """功能开关清单（含全部 spec——未 seed 的 spec 也以默认启用态列出，
    管理界面以 FEATURE_SPECS 为骨架、DB enabled 值为叠加态）。"""
    db_states: Dict[str, Dict[str, Any]] = {}
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT feature_key, enabled, enabled_by, enabled_at "
                "FROM feature_plugins")
            for r in (cursor.fetchall() or []):
                db_states[str(r.get("feature_key"))] = r
    except Exception as e:
        logger.warning(f"功能开关清单读取失败（按默认启用降级）: {e}")
    out = []
    for spec in FEATURE_SPECS:
        st = db_states.get(spec["key"], {})
        raw_enabled = as_int(st.get("enabled"))
        out.append({
            "key": spec["key"],
            "page": spec["page"],
            "label_zh": spec["zh"],
            "label_en": spec["en"],
            # 未 seed 的 spec 默认启用（1）——DB 无行≠停用
            "enabled": 1 if raw_enabled is None else raw_enabled,
            "enabled_by": st.get("enabled_by"),
            "enabled_at": st.get("enabled_at"),
        })
    return out
