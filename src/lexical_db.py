"""编纂成文域数据层 —— sense_examples / sense_translations 两表（批次 7 Agent V）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D④ 编纂成文域
（sense_examples · sense_translations 三态）与 §3 工序 11/12
（11 例证配置含多模态 · 12 标签与对译三态）；
契约：docs/spec/阶段1施工规范.md §10 批次 7-V（本文件签名与之一致）。

是什么（两张表，编纂成文域的例证与对译半区）：

  sense_examples      义位例证：文字例证一行一条（语料例 corpus / 改写例
                      adapted / 自拟例 composed 三来源），caption 记例证
                      说明/出处；媒体例证走 media_bindings 四锚中的
                      example 锚（本模块 bind_example_media 封装调用
                      media_db.bind_asset，同时把资产 id 记入
                      media_asset_id 列便于例证列表直读——绑定关系
                      本身只在 media_bindings，不在本表复制）；
  sense_translations  义位对译三态定稿：一义位一行（UNIQUE(sense_ref)），
                      state ∈ {full 完全对应 / partial 部分对应（对应词
                      ＋括注）/ none 无对应（释义翻译）}；equivalent 存
                      对应词，paraphrase 存无对应时的释义翻译，note 为
                      辨析栏草稿（近义簇英汉辨析栏的起草字段，批次 8
                      装配侧消费）；finalized_by/finalized_at 记定稿人
                      与定稿时间，updated_at 随改随刷。

数据链：
  工序 11/12（编纂成文）→ 编纂产出区「例证与对译」页（lexical_pages，
  批次 7 集成接线）→ 本模块 → 词条装配（阶段 2）按 state/审定态取数：
  例证区取审定/发布例证，对译区按三态渲染（none 态渲染 paraphrase）。

接口（契约 §10-V）：
  ensure_lexical_tables / add_example / list_examples / update_example /
  remove_example / advance_example_status / bind_example_media /
  set_translation / get_translation

降级：
  数据库不可用时 ensure 只记日志不抛异常（页面可继续渲染）；
  add_example 返回 0、update_example / remove_example /
  advance_example_status / bind_example_media / set_translation 返回
  False、list_examples 返回 []、get_translation 返回 None，均只记日志。

软删口径（本模块唯一非「不删行」的表）：
  sense_examples 的 remove_example 是**物理 DELETE** —— 例证可重建、
  不是词典正文：义项权威数据（cs_senses / definition_versions 等）遵循
  D 域「版本化、不删行」纪律，例证是可反复增删的配置项，删错重录即可，
  留僵尸行反而污染装配取数（docstring 明示，页面按钮文案同步注明）。
  删除前自动摘除该例证锚上的全部媒体绑定（R3-3，media_db
  .unbind_for_anchor('example', ...) —— media_bindings 无外键指向本表，
  孤儿绑定由此清理，不再依赖页面手工摘除）。
  sense_translations 无删除接口：三态定稿一义位一行，改口径即重新
  set_translation 覆盖定稿（定稿人/时间刷新），历史留痕走批次 8 审校
  台账（不在本表）。

安全规则：
  1. SQL 一律参数化，本文件无一处把值拼进 SQL 文本；
  2. 入参在应用层先校验再入库：非法 source/state/状态、空 sense_ref、
     空 content、超长 content（MAX_CONTENT_LEN=20000，R2-6 显式设防）/
     超长 equivalent/caption/note 根本不进数据库
     （不依赖 ENUM/长度报错）；
  3. 单步流转（候选→审定→发布）带乐观并发守卫 WHERE status=当前态，
     两人同时流转同一条只有一人生效，任何人不跳级、不回退。
"""

import logging
from typing import Any, Dict, List, Optional

import pymysql

from src import media_db
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（契约 §10-V 表设计原样）
# ============================================
# source：文字例证三来源（工序 11：语料草选 corpus → 人工改写 adapted →
# 自拟 composed；改写/自拟即「改写标记」，装配侧按 style.yaml 展示来源）。
SOURCE_CORPUS = "corpus"
SOURCE_ADAPTED = "adapted"
SOURCE_COMPOSED = "composed"
EXAMPLE_SOURCES = (SOURCE_CORPUS, SOURCE_ADAPTED, SOURCE_COMPOSED)

# status：例证审定三态（与 media_db.STATUSES 同链同语义：候选→审定→发布）。
STATUS_CANDIDATE = "候选"
STATUS_REVIEWED = "审定"
STATUS_PUBLISHED = "发布"
EXAMPLE_STATUSES = (STATUS_CANDIDATE, STATUS_REVIEWED, STATUS_PUBLISHED)

# state：对译三态（工序 12：完全对应 / 部分对应＋括注 / 无对应→释义翻译）。
STATE_FULL = "full"
STATE_PARTIAL = "partial"
STATE_NONE = "none"
TRANSLATION_STATES = (STATE_FULL, STATE_PARTIAL, STATE_NONE)

# 字段长度上限（与 DDL 一致，应用层先拒超长值）。
MAX_SENSE_REF_LEN = 60     # sense_ref VARCHAR(60)
MAX_CAPTION_LEN = 255      # caption VARCHAR(255)
MAX_EQUIVALENT_LEN = 255   # equivalent VARCHAR(255)
MAX_NOTE_LEN = 500         # note VARCHAR(500)
# content TEXT 本无列宽上限，但「无上限」不等于不设防（R2-6）：应用层显式
# 给 20000 字符保守上限（utf8mb4 TEXT 65535 字节内的安全值，远超正常例证
# 句长），防误贴整段语料/整篇文档把例证表撑成垃圾场；页面 help 同口径注明。
MAX_CONTENT_LEN = 20000    # content TEXT（应用层显式上限，超长拒收）

# 建表 DDL（契约 §10-V 表设计原样；幂等，CREATE TABLE IF NOT EXISTS）。
SENSE_EXAMPLES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS sense_examples (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sense_ref VARCHAR(60) NOT NULL COMMENT '义位锚：cs_senses.id 字符串引用（编纂成文域软引用，不做外键）',
  content TEXT NOT NULL COMMENT '例证文本（语料例/改写例/自拟例）',
  source ENUM('corpus','adapted','composed') NOT NULL DEFAULT 'corpus' COMMENT '来源三选一（改写/自拟即改写标记）',
  caption VARCHAR(255) NOT NULL DEFAULT '' COMMENT '例证说明/出处（媒体例证另经 media_bindings）',
  media_asset_id INT NULL COMMENT '媒体例证资产（软引用 media_assets.id；绑定关系在 media_bindings example 锚）',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '同义位多例证展示顺序（小在前）',
  status ENUM('候选','审定','发布') NOT NULL DEFAULT '候选' COMMENT '审定三态：候选→审定→发布，单步流转',
  created_by INT NULL COMMENT '录入人 users.id（软引用，系统登记为 NULL）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_sense_examples_ref (sense_ref),
  KEY idx_sense_examples_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

SENSE_TRANSLATIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS sense_translations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sense_ref VARCHAR(60) NOT NULL COMMENT '义位锚：cs_senses.id 的字符串引用',
  state ENUM('full','partial','none') NOT NULL COMMENT '对译三态（括注/释义翻译口径见 note/paraphrase）',
  equivalent VARCHAR(255) NOT NULL DEFAULT '' COMMENT '对应词（full/partial 态）',
  note VARCHAR(500) NOT NULL DEFAULT '' COMMENT '括注（partial 必填）兼辨析栏草稿（近义簇英汉辨析栏起草字段，批次 8 装配侧消费）',
  paraphrase TEXT NULL COMMENT '释义翻译（none 态必填）',
  finalized_by INT NULL COMMENT '定稿人 users.id（软引用）',
  finalized_at DATETIME NULL COMMENT '定稿时间（set_translation 每次落库刷新）',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_sense_translations_ref (sense_ref),
  KEY idx_sense_translations_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 建表
# ============================================
def ensure_lexical_tables() -> None:
    """幂等创建 sense_examples / sense_translations 两表（契约 §10-V 原样）。

    两表自含（sense_ref 是跨域软引用，不外键到 cs_senses；media_asset_id
    软引用 media_assets.id，绑定关系本体在 media_bindings），可独立先行
    建表；被数据库拒绝（无权限等）只记 error 日志不抛异常。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(SENSE_EXAMPLES_TABLE_SQL)
            cursor.execute(SENSE_TRANSLATIONS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"lexical 两表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"lexical 两表初始化意外错误: {e}")


# ============================================
# 入参规整（应用层先拒，非法值不进数据库）
# ============================================
def _as_int(value: Any) -> Optional[int]:
    """宽松转 int（int/int-str 可转；bool/None/其余返回 None）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_ref(sense_ref: Any) -> Optional[str]:
    """sense_ref 规整：去空白、限长 60；非法返回 None（应用层先拒）。"""
    if not isinstance(sense_ref, str):
        return None
    ref = sense_ref.strip()
    if not ref or len(ref) > MAX_SENSE_REF_LEN:
        return None
    return ref


def _clean_limited_str(value: Any, max_len: int, default: str = "") -> Optional[str]:
    """可选字符串规整：None→default；非 str/超长→None（拒收）。"""
    if value is None:
        return default
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) > max_len:
        return None
    return text


def _clean_actor(value: Any) -> Optional[int]:
    """操作人 id 规整：None 允许（系统登记）；给出则须为正整数。"""
    if value is None:
        return None
    uid = _as_int(value)
    if uid is None or uid <= 0:
        return None
    return uid


# ============================================
# 例证 CRUD
# ============================================
def add_example(
    sense_ref: str,
    content: str,
    source: str = SOURCE_CORPUS,
    caption: str = "",
    sort_order: int = 0,
    created_by: Optional[int] = None,
) -> int:
    """新增一条义位例证，返回例证 id（sense_examples.id）。

    例证以「候选」态起步（审定三态与 media_db 资产同链：候选→审定→发布）。

    Args:
        sense_ref: 义位锚（cs_senses.id 的字符串形式；非空、≤60 字符）。
            cs_senses.status='merged' 的义位由页面层禁选（分立复核已并入
            他义位，不再配置例证）；本数据层不做跨域存在性校验（软引用，
            与 media_db 锚口径一致）。
        content: 例证文本（非空；R2-6 起 ≤MAX_CONTENT_LEN=20000 字符 —— TEXT
            本无列宽上限，应用层显式设防，页面 help 同口径注明）。
        source: 来源 ∈ EXAMPLE_SOURCES（'corpus'/'adapted'/'composed'，
            默认语料例）。
        caption: 例证说明/出处（≤255 字符，默认 ''）。
        sort_order: 展示顺序（默认 0，小在前）。
        created_by: 录入人 users.id（可 None=系统登记）。

    Returns:
        int: 新例证 id；任一参数非法 / 数据库错误返回 0（falsy）。
    """
    ref = _clean_ref(sense_ref)
    if ref is None:
        logger.error(f"add_example 拒绝非法 sense_ref: {sense_ref!r}")
        return 0
    if not isinstance(content, str) or not content.strip():
        logger.error("add_example 拒绝空 content（例证文本必填）")
        return 0
    if len(content.strip()) > MAX_CONTENT_LEN:
        logger.error(
            f"add_example 拒绝超长 content（>{MAX_CONTENT_LEN} 字符）"
        )
        return 0
    if source not in EXAMPLE_SOURCES:
        logger.error(
            f"add_example 拒绝非法 source: {source!r}（须 ∈ {EXAMPLE_SOURCES}）"
        )
        return 0
    cap = _clean_limited_str(caption, MAX_CAPTION_LEN)
    if cap is None:
        logger.error(f"add_example 拒绝超长 caption（>{MAX_CAPTION_LEN} 字符）")
        return 0
    order = _as_int(sort_order)
    if order is None:
        logger.error(f"add_example 拒绝非法 sort_order: {sort_order!r}")
        return 0
    creator = _clean_actor(created_by)
    if created_by is not None and creator is None:
        logger.error(f"add_example 拒绝非法 created_by: {created_by!r}")
        return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO sense_examples "
                "(sense_ref, content, source, caption, sort_order, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (ref, content.strip(), source, cap, order, creator),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"新增例证失败（sense_ref={ref!r}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"新增例证意外错误: {e}")
        return 0


def list_examples(
    sense_ref: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """列义位例证（装配与页面取数入口）。

    Args:
        sense_ref: 义位锚（None=全部义位；传入则精确匹配）。
        status: 审定态筛选（None=全部；装配侧通常取审定/发布态）。
        limit: 返回上限（默认 500，最小 1）。

    Returns:
        list[dict]: 按 sort_order, id 稳定排序（装配确定性）；
        参数非法 / 数据库不可用返回 []。
    """
    ref = None
    if sense_ref is not None:
        ref = _clean_ref(sense_ref)
        if ref is None:
            logger.error(f"list_examples 拒绝非法 sense_ref: {sense_ref!r}")
            return []
    if status is not None and status not in EXAMPLE_STATUSES:
        logger.error(
            f"list_examples 拒绝非法 status: {status!r}（须 ∈ {EXAMPLE_STATUSES}）"
        )
        return []
    limit_val = _as_int(limit)
    if limit_val is None or limit_val <= 0:
        logger.error(f"list_examples 拒绝非法 limit: {limit!r}")
        return []
    sql = (
        "SELECT id, sense_ref, content, source, caption, media_asset_id, "
        "sort_order, status, created_by, created_at FROM sense_examples"
    )
    clauses: List[str] = []
    params: List[Any] = []
    if ref is not None:
        clauses.append("sense_ref = %s")
        params.append(ref)
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sort_order, id LIMIT %s"
    params.append(limit_val)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [dict(r) for r in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"查询例证失败（sense_ref={sense_ref!r}）: {e}")
        return []
    except Exception as e:
        logger.error(f"查询例证意外错误: {e}")
        return []


def update_example(
    example_id: int,
    content: Optional[str] = None,
    source: Optional[str] = None,
    caption: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> bool:
    """更新例证可编辑字段（Patch 语义：仅非 None 字段入库），返回是否成功。

    可改：content / source / caption / sort_order（改写标记来源随改）。
    status 不在本接口——审定流转走 advance_example_status 单步链。

    Args:
        example_id: 例证 id（>0，行须存在）。
        content: 新例证文本（None=不改；给出须非空，R2-6 起 ≤MAX_CONTENT_LEN
            字符，与 add_example 同上限）。
        source: 新来源 ∈ EXAMPLE_SOURCES（None=不改）。
        caption: 新说明/出处（None=不改；'' 允许=清空）。
        sort_order: 新顺序（None=不改）。

    Returns:
        bool: 更新成功（rowcount=1）True；参数非法 / 行不存在 / 数据库
        错误 False。
    """
    eid = _as_int(example_id)
    if eid is None or eid <= 0:
        logger.error(f"update_example 拒绝非法 example_id: {example_id!r}")
        return False
    sets: List[str] = []
    params: List[Any] = []
    if content is not None:
        if not isinstance(content, str) or not content.strip():
            logger.error("update_example 拒绝空 content")
            return False
        if len(content.strip()) > MAX_CONTENT_LEN:
            logger.error(
                f"update_example 拒绝超长 content（>{MAX_CONTENT_LEN} 字符）"
            )
            return False
        sets.append("content = %s")
        params.append(content.strip())
    if source is not None:
        if source not in EXAMPLE_SOURCES:
            logger.error(
                f"update_example 拒绝非法 source: {source!r}（须 ∈ {EXAMPLE_SOURCES}）"
            )
            return False
        sets.append("source = %s")
        params.append(source)
    if caption is not None:
        cap = _clean_limited_str(caption, MAX_CAPTION_LEN, default="")
        if cap is None or not isinstance(caption, str):
            logger.error(
                f"update_example 拒绝非法/超长 caption（>{MAX_CAPTION_LEN}）"
            )
            return False
        sets.append("caption = %s")
        params.append(cap)
    if sort_order is not None:
        order = _as_int(sort_order)
        if order is None:
            logger.error(f"update_example 拒绝非法 sort_order: {sort_order!r}")
            return False
        sets.append("sort_order = %s")
        params.append(order)
    if not sets:
        logger.warning("update_example 无可更新字段（全部为 None）")
        return False
    params.append(eid)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"UPDATE sense_examples SET {', '.join(sets)} WHERE id = %s",
                tuple(params),
            )
            return cursor.rowcount == 1
    except pymysql.Error as e:
        logger.error(f"更新例证失败（example_id={eid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"更新例证意外错误（example_id={eid}）: {e}")
        return False


def remove_example(example_id: int) -> bool:
    """物理删除一条例证（**本模块唯一的删除接口**），返回是否成功。

    软删口径：例证可重建、不是词典正文（模块 docstring「软删口径」）——
    D 域不删行纪律管的是义项权威数据与版本脊柱，例证是可反复增删的
    配置项；物理删除避免僵尸行污染装配取数。

    媒体绑定自动摘除（R3-3）：media_bindings 无外键指向本表（多态引用），
    删除例证前先调 ``media_db.unbind_for_anchor('example', example_id)``
    摘除该例证锚上的**全部**绑定（顺序执行，与删除同一请求链完成）——
    孤儿绑定不再依赖页面手工摘除（页面此前并没有这个按钮，旧文案指向
    一个不存在的能力）。摘除数只记日志：绑定摘除失败（库不可用等）返回
    0 且**不阻断例证删除**（锚行即将消失，摘不掉的绑定已无装配入口可达，
    仅留审计日志）。

    Args:
        example_id: 例证 id（>0）。

    Returns:
        bool: 删除成功（rowcount=1）True；参数非法 / 行不存在 / 数据库
        错误 False。
    """
    eid = _as_int(example_id)
    if eid is None or eid <= 0:
        logger.error(f"remove_example 拒绝非法 example_id: {example_id!r}")
        return False
    # R3-3：先摘例证锚上的全部媒体绑定（防孤儿绑定；顺序执行，unbind 自带
    # 容错返回 0 不阻断删除），再删例证行
    media_db.unbind_for_anchor(media_db.ANCHOR_EXAMPLE, eid)
    try:
        with get_db_cursor() as cursor:
            cursor.execute("DELETE FROM sense_examples WHERE id = %s", (eid,))
            return cursor.rowcount == 1
    except pymysql.Error as e:
        logger.error(f"删除例证失败（example_id={eid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"删除例证意外错误（example_id={eid}）: {e}")
        return False


# ============================================
# 例证审定流转（单步 + 乐观并发守卫）
# ============================================
def _next_example_status(from_status: str) -> Optional[str]:
    """审定链的下一步（候选→审定→发布；发布为终态返回 None）。"""
    chain = {STATUS_CANDIDATE: STATUS_REVIEWED, STATUS_REVIEWED: STATUS_PUBLISHED}
    return chain.get(from_status)


def advance_example_status(example_id: int, from_status: str, to_status: str) -> bool:
    """例证审定流转一步（候选→审定→发布），返回是否生效。

    参数化 UPDATE + 乐观并发守卫（WHERE status = from_status）：两人同时
    流转同一条时只有一人生效（rowcount=1）；非法状态对（不在单步链上）
    直接拒绝——逐级单步、不可跳级、不可回退，与媒体绑定流转
    （dict_admin_pages._advance_binding_status）同一口径。

    Args:
        example_id: 例证 id（>0）。
        from_status: 当前审定态（须 ∈ EXAMPLE_STATUSES 且为该例证实际状态）。
        to_status: 目标态（须为 from_status 的链上下一步）。

    Returns:
        bool: 流转生效 True；参数非法 / 非单步对 / 状态已被他人先行流转 /
        行不存在 / 数据库错误 False。
    """
    eid = _as_int(example_id)
    if eid is None or eid <= 0:
        logger.error(f"advance_example_status 拒绝非法 example_id: {example_id!r}")
        return False
    if from_status not in EXAMPLE_STATUSES or to_status not in EXAMPLE_STATUSES:
        logger.error(
            f"advance_example_status 拒绝非法状态对: {from_status!r} → {to_status!r}"
        )
        return False
    if _next_example_status(from_status) != to_status:
        logger.error(
            f"advance_example_status 拒绝非单步对：{from_status!r} → {to_status!r}"
        )
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE sense_examples SET status = %s "
                "WHERE id = %s AND status = %s",
                (to_status, eid, from_status),
            )
            return cursor.rowcount == 1
    except pymysql.Error as e:
        logger.error(f"例证流转失败（example_id={eid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"例证流转意外错误（example_id={eid}）: {e}")
        return False


# ============================================
# 媒体例证绑定（封装 media_db.bind_asset，不复制其逻辑）
# ============================================
def bind_example_media(example_id: int, asset_id: int, caption: str = "") -> bool:
    """把媒体资产绑为某例证的媒体例证（媒体例证入口，封装调用不复制逻辑）。

    委托 media_db.bind_asset(asset_id, anchor_type='example',
    anchor_id=example_id, purpose='example_media', caption=caption)——
    资产存在性 / UNIQUE 幂等 / caption 限长校验全在 media_db；绑定成功后
    把 asset_id 记入 sense_examples.media_asset_id（软引用，例证列表
    直读展示用；绑定关系本体只在 media_bindings）。

    Args:
        example_id: 例证 id（>0，行须存在——anchor 存在性校验在本层做，
            media_db 对多态锚不做存在性校验）。
        asset_id: 资产 id（media_assets.id，>0，须已登记——存在性校验
            在 media_db）。
        caption: 图注/来源说明（≤255 字符，默认 ''；媒体例证 caption
            通常记来源）。

    Returns:
        bool: 绑定成功（含 media_db 幂等命中）True；参数非法 / 例证不存在 /
        media_db 拒绝（资产不存在等）/ 数据库错误 False。
        幂等重绑：回写前先读 media_asset_id 现值，已等于目标 asset_id 时
        直接 True（跳过回写——同值 UPDATE 在 MySQL rowcount=0，不得据此
        判失败）；不同值则回写后 True（行存在性已在入校与回写前两查确认）。
    """
    eid = _as_int(example_id)
    if eid is None or eid <= 0:
        logger.error(f"bind_example_media 拒绝非法 example_id: {example_id!r}")
        return False
    aid = _as_int(asset_id)
    if aid is None or aid <= 0:
        logger.error(f"bind_example_media 拒绝非法 asset_id: {asset_id!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT id FROM sense_examples WHERE id = %s", (eid,))
            if cursor.fetchone() is None:
                logger.error(f"bind_example_media 拒绝：例证不存在 example_id={eid}")
                return False
    except pymysql.Error as e:
        logger.error(f"bind_example_media 例证存在性校验失败: {e}")
        return False
    except Exception as e:
        logger.error(f"bind_example_media 例证存在性校验意外错误: {e}")
        return False
    if not media_db.bind_asset(
        aid, media_db.ANCHOR_EXAMPLE, eid, media_db.PURPOSE_EXAMPLE_MEDIA, caption,
    ):
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT media_asset_id FROM sense_examples WHERE id = %s",
                (eid,),
            )
            row = cursor.fetchone()
            if row is None:
                logger.error(
                    f"bind_example_media 回写前例证已不存在 example_id={eid}"
                )
                return False
            if row["media_asset_id"] == aid:
                # 幂等重绑：media_asset_id 已是目标值，同值 UPDATE 的
                # rowcount=0 不代表失败——直接判成功、跳过回写。
                return True
            cursor.execute(
                "UPDATE sense_examples SET media_asset_id = %s WHERE id = %s",
                (aid, eid),
            )
            # 行存在性已由上方 SELECT 现值确认，UPDATE 后不再依赖 rowcount。
            return True
    except pymysql.Error as e:
        logger.error(f"媒体例证回写 media_asset_id 失败（example_id={eid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"媒体例证回写 media_asset_id 意外错误（example_id={eid}）: {e}")
        return False


# ============================================
# 对译三态定稿（upsert，一义位一行）
# ============================================
def set_translation(
    sense_ref: str,
    state: str,
    equivalent: str = "",
    note: str = "",
    paraphrase: Optional[str] = None,
    finalized_by: Optional[int] = None,
) -> bool:
    """写义位对译定稿（upsert：无则插行、有则覆盖），返回是否成功。

    **定稿语义**：每次成功调用都把 finalized_by / finalized_at 刷新为
    本次定稿人与当前时间——三态口径可以改（改即重新定稿，表上只留
    最新一版，历史留痕归批次 8 审校台账）；updated_at 由
    ON UPDATE CURRENT_TIMESTAMP 自动刷新。

    Args:
        sense_ref: 义位锚（非空、≤60 字符；merged 义位由页面层禁选）。
        state: 三态 ∈ TRANSLATION_STATES（'full'/'partial'/'none'）。
        equivalent: 对应词（full/partial 态应给出；≤255 字符）。
        note: 括注（partial 态为括注位）兼辨析栏草稿（≤500 字符）。
        paraphrase: 释义翻译（none 态应给出；TEXT）。
        finalized_by: 定稿人 users.id（可 None=系统登记）。

    Returns:
        bool: 定稿成功 True；参数非法 / 数据库错误 False。
        （state 与各字段的**搭配校验**——partial 须有括注、none 须有
        paraphrase 等——归页面层表单分支，数据层只做类型/枚举/限长。）
    """
    ref = _clean_ref(sense_ref)
    if ref is None:
        logger.error(f"set_translation 拒绝非法 sense_ref: {sense_ref!r}")
        return False
    if state not in TRANSLATION_STATES:
        logger.error(
            f"set_translation 拒绝非法 state: {state!r}（须 ∈ {TRANSLATION_STATES}）"
        )
        return False
    eq = _clean_limited_str(equivalent, MAX_EQUIVALENT_LEN)
    if eq is None:
        logger.error(
            f"set_translation 拒绝非法/超长 equivalent（>{MAX_EQUIVALENT_LEN}）"
        )
        return False
    nt = _clean_limited_str(note, MAX_NOTE_LEN)
    if nt is None:
        logger.error(f"set_translation 拒绝超长 note（>{MAX_NOTE_LEN}）")
        return False
    if paraphrase is not None and not isinstance(paraphrase, str):
        logger.error(f"set_translation 拒绝非法 paraphrase: {paraphrase!r}（str 或 None）")
        return False
    para = paraphrase.strip() if isinstance(paraphrase, str) else None
    if para == "":
        para = None  # 空释义翻译按未给出处理
    finalizer = _clean_actor(finalized_by)
    if finalized_by is not None and finalizer is None:
        logger.error(f"set_translation 拒绝非法 finalized_by: {finalized_by!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """INSERT INTO sense_translations
                   (sense_ref, state, equivalent, note, paraphrase,
                    finalized_by, finalized_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW())
                   ON DUPLICATE KEY UPDATE
                     state = VALUES(state),
                     equivalent = VALUES(equivalent),
                     note = VALUES(note),
                     paraphrase = VALUES(paraphrase),
                     finalized_by = VALUES(finalized_by),
                     finalized_at = NOW()""",
                (ref, state, eq, nt, para, finalizer),
            )
            return True
    except pymysql.Error as e:
        logger.error(f"对译定稿失败（sense_ref={ref!r}）: {e}")
        return False
    except Exception as e:
        logger.error(f"对译定稿意外错误（sense_ref={ref!r}）: {e}")
        return False


def get_translation(sense_ref: str) -> Optional[Dict[str, Any]]:
    """读义位对译定稿（一义位至多一行，UNIQUE(sense_ref)）。

    Args:
        sense_ref: 义位锚（非空、≤60 字符）。

    Returns:
        dict | None: 定稿行（id/sense_ref/state/equivalent/note/paraphrase/
        finalized_by/finalized_at/updated_at）；无定稿 / 参数非法 /
        数据库不可用返回 None。
    """
    ref = _clean_ref(sense_ref)
    if ref is None:
        logger.error(f"get_translation 拒绝非法 sense_ref: {sense_ref!r}")
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT id, sense_ref, state, equivalent, note, paraphrase, "
                "finalized_by, finalized_at, updated_at "
                "FROM sense_translations WHERE sense_ref = %s",
                (ref,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except pymysql.Error as e:
        logger.error(f"查询对译定稿失败（sense_ref={ref!r}）: {e}")
        return None
    except Exception as e:
        logger.error(f"查询对译定稿意外错误（sense_ref={ref!r}）: {e}")
        return None
