"""媒体资产域数据层 —— media_assets / media_bindings 两表（Agent E）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§6 D⑦ 媒体资产域与词条
内容模型「多模态区」（释义配图 · 动作视频示范 · 图式示意图）；
契约：docs/spec/阶段1施工规范.md §3-E（本文件签名与之一致，不得擅改）。

是什么（两张表）：

  media_assets    资产档案：一个文件一行。kind ∈ {image,audio,video}，
                  sha256 唯一（同内容只入一行，重复登记返回已有 id），
                  **license 必填**（D⑥ 资源发布域同款许可纪律：无许可的
                  资产根本进不了库）；
  media_bindings  绑定关系：资产 × 四锚（word 词目 / sense 义位 /
                  example 例证 / schema 图式）× 用途（pronunciation /
                  illustration / example_media / schema_diagram）。
                  四锚是多态引用（锚表各不相同），anchor_id 不做外键，
                  存在性校验归加载脚本 / 批次 2 页面层；词目锚合法
                  ——媒体是展示层资产，允许挂词目（现汉配图 = 现汉
                  词条 zh_dict_entries.id，英文词条 = definitions.id）。

数据链：
  data/ModernChineseDict/images/ → scripts/load_media_xianhan.py
  （文件名→词条映射 + sha256 登记 + 词目锚绑定，status='候选'）
  → 词典管理员在批次 2 媒体管理页审定（候选→审定→发布）
  → 词条装配按 list_assets_for_anchor 取「发布」态资产渲染多模态区。

接口（契约 §3-E）：
  ensure_media_tables / register_asset / bind_asset / list_assets_for_anchor

降级：
  数据库不可用时 ensure 只记日志不抛异常（页面可继续渲染），
  register_asset 返回 0、bind_asset 返回 False、list_assets_for_anchor
  返回 []，均只记日志不抛异常。

安全规则：
  1. SQL 一律参数化，本文件无一处把值拼进 SQL 文本；
  2. 入参在应用层先校验再入库：非法 kind / 空 license / 非法锚与用途 /
     超长字段根本不进数据库（不依赖 ENUM 报错）；
  3. 许可纪律是本模块硬约束：register_asset 拒绝空 license —— 比起
     DDL NOT NULL 报错，应用层先拒给出可读的错误日志。
"""

import hashlib
import logging
import mimetypes
import os
from typing import Any, Dict, List, Union

import pymysql

from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（契约 §3-E 表设计原样）
# ============================================
# kind：资产形态三类（词条内容模型「多模态区」的承载面）。
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"
KINDS = (KIND_IMAGE, KIND_AUDIO, KIND_VIDEO)

# anchor_type：四锚（平台架构设计规范 §6 D⑦「四锚：词目/义位/例证/图式」）。
ANCHOR_WORD = "word"
ANCHOR_SENSE = "sense"
ANCHOR_EXAMPLE = "example"
ANCHOR_SCHEMA = "schema"
ANCHOR_TYPES = (ANCHOR_WORD, ANCHOR_SENSE, ANCHOR_EXAMPLE, ANCHOR_SCHEMA)

# purpose：绑定用途（词条内容模型多模态区四类位）。
PURPOSE_PRONUNCIATION = "pronunciation"
PURPOSE_ILLUSTRATION = "illustration"
PURPOSE_EXAMPLE_MEDIA = "example_media"
PURPOSE_SCHEMA_DIAGRAM = "schema_diagram"
PURPOSES = (
    PURPOSE_PRONUNCIATION,
    PURPOSE_ILLUSTRATION,
    PURPOSE_EXAMPLE_MEDIA,
    PURPOSE_SCHEMA_DIAGRAM,
)

# status：资产与绑定的审定三态（候选 → 审定 → 发布）。
STATUS_CANDIDATE = "候选"
STATUS_REVIEWED = "审定"
STATUS_PUBLISHED = "发布"
STATUSES = (STATUS_CANDIDATE, STATUS_REVIEWED, STATUS_PUBLISHED)

# 字段长度上限（与 DDL 一致，应用层先拒超长值）。
MAX_LICENSE_LEN = 120     # license VARCHAR(120) NOT NULL
MAX_SOURCE_LEN = 80       # source VARCHAR(80)
MAX_FILE_PATH_LEN = 255   # file_path VARCHAR(255)
MAX_MIME_LEN = 100        # mime VARCHAR(100)
MAX_CAPTION_LEN = 255     # caption VARCHAR(255)

# 建表 DDL（契约 §3-E 表设计原样；幂等，CREATE TABLE IF NOT EXISTS）。
MEDIA_ASSETS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS media_assets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  kind ENUM('image','audio','video') NOT NULL,
  file_path VARCHAR(255) NOT NULL COMMENT '资产文件路径（仓库相对路径优先，便于换机）',
  mime VARCHAR(100) NULL COMMENT 'MIME 类型（未提供时按扩展名推断）',
  sha256 CHAR(64) NOT NULL UNIQUE COMMENT '文件内容哈希：去重键，同内容只一行',
  source VARCHAR(80) NOT NULL DEFAULT '' COMMENT '来源（如 ModernChineseDict/images）',
  license VARCHAR(120) NOT NULL COMMENT '许可：必填，无许可不入库（D⑥ 许可纪律同款）',
  size_bytes BIGINT NULL COMMENT '文件字节数',
  status ENUM('候选','审定','发布') NOT NULL DEFAULT '候选',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_media_assets_kind (kind),
  KEY idx_media_assets_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

MEDIA_BINDINGS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS media_bindings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  asset_id INT NOT NULL,
  anchor_type ENUM('word','sense','example','schema') NOT NULL
    COMMENT '四锚：词目/义位/例证/图式（多态引用，锚表各异，不做外键）',
  anchor_id INT NOT NULL COMMENT '锚行 id（word=现汉词条 zh_dict_entries.id / definitions.id）',
  purpose ENUM('pronunciation','illustration','example_media','schema_diagram') NOT NULL,
  caption VARCHAR(255) NOT NULL DEFAULT '' COMMENT '图注（例证媒体：来源说明）',
  sort_order INT NOT NULL DEFAULT 0 COMMENT '同锚多资产展示顺序（小在前）',
  status ENUM('候选','审定','发布') NOT NULL DEFAULT '候选',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_media_bindings (asset_id, anchor_type, anchor_id, purpose),
  KEY idx_media_bindings_anchor (anchor_type, anchor_id),
  CONSTRAINT fk_media_bindings_asset FOREIGN KEY (asset_id)
    REFERENCES media_assets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 建表
# ============================================
def ensure_media_tables() -> None:
    """幂等创建 media_assets / media_bindings 两表（契约 §3-E 表设计原样）。

    两表自含（锚是多态引用，不外键到任何词条表），可独立先行建表；
    被数据库拒绝（无权限等）只记 error 日志不抛异常。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(MEDIA_ASSETS_TABLE_SQL)
            cursor.execute(MEDIA_BINDINGS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"media 两表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"media 两表初始化意外错误: {e}")


# ============================================
# 入参规整（应用层先拒，非法值不进数据库）
# ============================================
def _as_int(value: Any) -> Any:
    """宽松转 int（int/int-str/float 整数可转；bool/其余返回 None）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sha256_of_file(path: str) -> Any:
    """流式计算文件 sha256（64KB 分块，媒体文件可能很大）；读不动返回 None。"""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as e:
        logger.error(f"读取资产文件失败: {path} ({e})")
        return None


# ============================================
# 登记（sha256 去重 + license 必填）
# ============================================
def register_asset(
    path: Union[str, "os.PathLike[str]"],
    kind: str,
    source: str,
    license: str,
    mime: str = None,
) -> int:
    """登记一个媒体资产，返回资产 id（media_assets.id）。

    许可纪律（硬约束）：license 去空白后必须非空 —— 无许可的资产根本
    不进数据库。sha256 是去重键：同内容文件重复登记**不新插行**，返回
    已有资产的 id（重复事实记 warning 日志留痕）。

    Args:
        path: 资产文件路径（必须真实存在、可读 —— sha256 与 size_bytes
            从文件内容算出；file_path 按传入字符串原样入库，加载脚本
            传仓库相对路径）。str 或 os.PathLike。
        kind: 资产形态 ∈ KINDS（'image'/'audio'/'video'）
        source: 来源说明（≤80 字符；空串允许，存 ''）
        license: 许可说明（非空，≤120 字符）
        mime: MIME 类型（None 时按扩展名推断，推断不出存 NULL）

    Returns:
        int: 资产 id（新登记或去重命中的已有 id）；任一参数非法 /
        文件不可读 / 数据库错误返回 0（falsy，调用方按失败处理）。
    """
    if kind not in KINDS:
        logger.error(f"register_asset 拒绝非法 kind: {kind!r}（须 ∈ {KINDS}）")
        return 0
    if not isinstance(source, str):
        logger.error(f"register_asset 拒绝非法 source: {source!r}（str）")
        return 0
    source = source.strip()
    if len(source) > MAX_SOURCE_LEN:
        logger.error(f"register_asset 拒绝超长 source（>{MAX_SOURCE_LEN} 字符）")
        return 0
    # 许可纪律：应用层先拒空 license（DDL NOT NULL 之外的语义校验）
    if not isinstance(license, str) or not license.strip():
        logger.error("register_asset 拒绝空 license（许可必填，无许可不入库）")
        return 0
    license = license.strip()
    if len(license) > MAX_LICENSE_LEN:
        logger.error(
            f"register_asset 拒绝超长 license（>{MAX_LICENSE_LEN} 字符，"
            f"{len(license)}）"
        )
        return 0
    if mime is None:
        mime = mimetypes.guess_type(str(path))[0]  # 按扩展名推断
    if not isinstance(mime, str):
        logger.error(f"register_asset 拒绝非法 mime: {mime!r}（str 或 None）")
        return 0
    mime = mime.strip() or None
    if mime is not None and len(mime) > MAX_MIME_LEN:
        logger.error(f"register_asset 拒绝超长 mime（>{MAX_MIME_LEN} 字符）")
        return 0

    try:
        file_path = str(os.fspath(path))
    except TypeError:
        logger.error(f"register_asset 拒绝非法 path: {path!r}")
        return 0
    if not file_path or len(file_path) > MAX_FILE_PATH_LEN:
        logger.error(f"register_asset 拒绝非法/超长 file_path（>{MAX_FILE_PATH_LEN}）")
        return 0
    if not os.path.isfile(file_path):
        logger.error(f"register_asset 拒绝：文件不存在 {file_path!r}")
        return 0
    sha256 = _sha256_of_file(file_path)
    if sha256 is None:
        return 0
    try:
        size_bytes = os.path.getsize(file_path)
    except OSError as e:
        logger.error(f"读取资产文件大小失败: {file_path} ({e})")
        return 0

    try:
        with get_db_cursor() as cursor:
            # sha256 去重：同内容已登记 → 返回已有 id，不重复入库
            cursor.execute("SELECT id FROM media_assets WHERE sha256 = %s", (sha256,))
            row = cursor.fetchone()
            if row is not None:
                existing_id = int(row["id"])
                logger.warning(
                    f"register_asset sha256 去重命中：返回已有资产 id={existing_id}"
                    f"（本次请求 path={file_path!r}, kind={kind}）"
                )
                return existing_id
            cursor.execute(
                "INSERT INTO media_assets "
                "(kind, file_path, mime, sha256, source, license, size_bytes, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, '候选')",
                (kind, file_path, mime, sha256, source, license, size_bytes),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"登记媒体资产失败（path={file_path!r}, kind={kind}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"登记媒体资产意外错误: {e}")
        return 0


# ============================================
# 绑定（四锚 × 用途）
# ============================================
def bind_asset(
    asset_id: int,
    anchor_type: str,
    anchor_id: int,
    purpose: str,
    caption: str = "",
    sort_order: int = 0,
    status: str = STATUS_CANDIDATE,
) -> bool:
    """把资产绑到一个锚上，返回是否成功。

    UNIQUE(asset_id, anchor_type, anchor_id, purpose) 幂等：同一绑定重复
    调用（含并发撞键）按「已绑定」处理返回 True、保留首次的
    caption/sort_order/status（重跑加载脚本不会重复入行，也不会把已
    审定的状态冲回候选）。

    Args:
        asset_id: 资产 id（media_assets.id，须已存在）
        anchor_type: 锚类型 ∈ ANCHOR_TYPES（'word'/'sense'/'example'/'schema'）
        anchor_id: 锚行 id（>0；word 锚 = 现汉词条 zh_dict_entries.id
            或 definitions.id，数据层不做存在性校验 —— 锚表是多态的，
            校验归加载脚本与批次 2 页面层）
        purpose: 用途 ∈ PURPOSES（'pronunciation'/'illustration'/
            'example_media'/'schema_diagram'）
        caption: 图注（≤255 字符，默认 ''）
        sort_order: 展示顺序（默认 0，小在前）
        status: 绑定状态 ∈ STATUSES（默认 '候选'）

    Returns:
        bool: 绑定成功（含幂等命中）True；参数非法 / 资产不存在 /
        数据库错误 False。
    """
    aid = _as_int(asset_id)
    if aid is None or aid <= 0:
        logger.error(f"bind_asset 拒绝非法 asset_id: {asset_id!r}")
        return False
    if anchor_type not in ANCHOR_TYPES:
        logger.error(
            f"bind_asset 拒绝非法 anchor_type: {anchor_type!r}（须 ∈ {ANCHOR_TYPES}）"
        )
        return False
    tid = _as_int(anchor_id)
    if tid is None or tid <= 0:
        logger.error(f"bind_asset 拒绝非法 anchor_id: {anchor_id!r}")
        return False
    if purpose not in PURPOSES:
        logger.error(f"bind_asset 拒绝非法 purpose: {purpose!r}（须 ∈ {PURPOSES}）")
        return False
    if not isinstance(caption, str):
        logger.error(f"bind_asset 拒绝非法 caption: {caption!r}（str，默认 ''）")
        return False
    caption = caption.strip()
    if len(caption) > MAX_CAPTION_LEN:
        logger.error(f"bind_asset 拒绝超长 caption（>{MAX_CAPTION_LEN} 字符）")
        return False
    order = _as_int(sort_order)
    if order is None:
        logger.error(f"bind_asset 拒绝非法 sort_order: {sort_order!r}")
        return False
    if status not in STATUSES:
        logger.error(f"bind_asset 拒绝非法 status: {status!r}（须 ∈ {STATUSES}）")
        return False

    try:
        with get_db_cursor() as cursor:
            # 资产存在性先查（FK 报错日志不可读；missing 在应用层给清晰拒绝）
            cursor.execute("SELECT id FROM media_assets WHERE id = %s", (aid,))
            if cursor.fetchone() is None:
                logger.error(f"bind_asset 拒绝：资产不存在 asset_id={aid}")
                return False
            # 同键已绑定 → 幂等命中（保留首次绑定值），不算错误
            cursor.execute(
                "SELECT id FROM media_bindings "
                "WHERE asset_id = %s AND anchor_type = %s AND anchor_id = %s "
                "AND purpose = %s",
                (aid, anchor_type, tid, purpose),
            )
            if cursor.fetchone() is not None:
                logger.info(
                    f"bind_asset 幂等命中：asset_id={aid} 已绑 "
                    f"({anchor_type}, {tid}, {purpose})，保留首次绑定值"
                )
                return True
            cursor.execute(
                "INSERT INTO media_bindings "
                "(asset_id, anchor_type, anchor_id, purpose, caption, "
                " sort_order, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (aid, anchor_type, tid, purpose, caption, order, status),
            )
            return True
    except pymysql.IntegrityError as e:
        # 并发撞 UNIQUE（1062）→ 等价幂等命中；其余完整性错误按失败
        if e.args and e.args[0] == 1062:
            logger.info(f"bind_asset 并发撞键（UNIQUE），按幂等命中处理: {e}")
            return True
        logger.error(f"绑定媒体资产失败（asset_id={aid}）: {e}")
        return False
    except pymysql.Error as e:
        logger.error(f"绑定媒体资产失败（asset_id={aid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"绑定媒体资产意外错误: {e}")
        return False


# ============================================
# 查询（词条装配多模态区的取数入口）
# ============================================
def list_assets_for_anchor(anchor_type: str, anchor_id: int) -> List[Dict[str, Any]]:
    """列出一个锚上的全部资产绑定（装配确定性：按 sort_order, id 稳定排序）。

    Args:
        anchor_type: 锚类型 ∈ ANCHOR_TYPES
        anchor_id: 锚行 id

    Returns:
        list[dict]: 绑定+资产联查行，按展示顺序排序；键含两组状态——
        ``binding_status``（绑定的审定态）与 ``asset_status``（资产本身的
        审定态）。批次 2 渲染多模态区时应只取 binding_status='发布'（或
        按产品口径过滤候选）；anchor_type 非法 / anchor_id 非法 /
        数据库不可用返回 []。
    """
    if anchor_type not in ANCHOR_TYPES:
        logger.error(
            f"list_assets_for_anchor 拒绝非法 anchor_type: {anchor_type!r}"
            f"（须 ∈ {ANCHOR_TYPES}）"
        )
        return []
    tid = _as_int(anchor_id)
    if tid is None or tid <= 0:
        logger.error(f"list_assets_for_anchor 拒绝非法 anchor_id: {anchor_id!r}")
        return []
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT b.id AS binding_id, b.asset_id, b.anchor_type,
                          b.anchor_id, b.purpose, b.caption, b.sort_order,
                          b.status AS binding_status,
                          a.kind, a.file_path, a.mime, a.sha256, a.source,
                          a.license, a.size_bytes, a.status AS asset_status,
                          a.created_at
                   FROM media_bindings b
                   JOIN media_assets a ON a.id = b.asset_id
                   WHERE b.anchor_type = %s AND b.anchor_id = %s
                   ORDER BY b.sort_order, b.id""",
                (anchor_type, tid),
            )
            return list(cursor.fetchall())
    except pymysql.Error as e:
        logger.error(
            f"查询锚绑定失败（anchor_type={anchor_type!r}, anchor_id={tid}）: {e}"
        )
        return []
    except Exception as e:
        logger.error(f"查询锚绑定意外错误: {e}")
        return []
