"""编纂成文域数据层 —— 释义撰写与审校三表（批次 7 Agent U）。

设计规范：docs/spec/平台架构设计规范.md（v5.1）§3 工序 10/13（释义撰写 · 审校
定稿，G4/G5 闸门）与 §6 D④ 编纂成文域（definition_versions / sense_examples /
sense_translations / review_tasks / review_comments —— sense_examples /
sense_translations 两表归批次 7 Agent V 的 lexical_db.py，本文件只管三表）；
§8 编纂协作范式（簇承包 → 多轮审校（回避制）→ 定稿；两级终审）；
契约：docs/spec/阶段1施工规范.md §10 批次 7 Agent U 行（DDL 原样落地）。

是什么（三张表，全部软引用、无外键，仿 src/ai_ledger.py 独立建表先例）：
  definition_versions  释义版本表（三版本脊柱第三条：annotation_submissions →
                       cs_cluster_runs → definition_versions）。**sense_ref
                       三段式锚**：``范畴包名:cs_senses.id:oald_senses.id``，
                       如 ``motion:12:345``；未落在对应空间的槽位以 0 占位
                       （``motion:0:345`` = 未进范畴深挖库的 OALD 义位，
                       ``RUN:7:0`` = 只有研究层编码、OALD 锚未解析）——
                       校验只查格式（正则 + ≤60 字符），不做存在性校验
                       （软引用，锚校验归页面/集成层）；version 在 sense_ref
                       内自动递增，UNIQUE(sense_ref, version) 兜底并发建版。
  review_tasks         审校任务（submit_for_review 时创建，一版一轮一条；
                       verdict 四值，pending 为初始态）。
  review_comments      审校意见线（逐条挂版本；resolved 由作者/审校收口，
                       收口只是标记不删行 —— D 域不删行纪律）。

状态机（帮助文档 §4.2 口径：draft→in_review→reviewed→revised→approved→final
→published；rejected 为打回侧支）::

    draft ──submit_for_review──▶ in_review ──approve──▶ final ──publish──▶ published
                                    │
                                    └─request_revision─▶ rejected
        （作者重提 = create_draft 自动 version+1，带 based_on_version=被拒版号）

  reviewed / revised / approved 三个枚举值是**两级终审扩展占位**（§8：普通词条
  reviewer 终审即 final；争议词条升级词典管理员终裁——例外通道而非必经站）：
  MVP 单级审校不经由 reviewed / revised；批次 8（G6 批）落终裁接口
  adjudicate_final：in_review --approved--> final 直达收口（两级终审的例外通道，
  跳过 reviewed/approved 中段枚举），并支持 approved --approved--> final（补终裁，
  供未来两级链中段行收口）——reviewed / revised 仍为占位不经由，契约 DDL 不动。

CRUD 契约（施工规范 §10）：
  create_draft / update_draft（乐观锁 expect_version）/ submit_for_review
  （draft→in_review，回避制硬校验）/ add_comment / request_revision
  （→rejected）/ approve（→final 的 MVP）/ publish（仅 dict_admin 口径，
  G6 硬闸门批次 8 接管）/ list_versions / list_pending_reviews。
  另有非契约只读/收口辅助 get_version / get_latest_version / list_comments /
  resolve_comment（供页面与测试，仿 ai_ledger.get_proposal 先例）。

角色与回避制口径（§8「回避制无豁免，含词典管理员」）：
  * 数据层硬校验：审校动作（submit_for_review 指派、add_comment、
    request_revision、approve、adjudicate_final 终裁）的 reviewer_id /
    adjudicator_id 一律不得等于该版本 author_id（author_id 为 NULL 的系统
    登记行无可比对对象，如实放行并记日志）；
  * 裁决动作（request_revision / approve）须由**受派审校人**执行（与
    review_tasks.reviewer_id 一致）；终裁（adjudicate_final）走词典管理员
    口径（actor 有效六角色含 dict_admin，同 publish 的判定源）而非受派
    审校人口径 —— 例外通道收口，见函数 docstring；意见线（add_comment）
    任何非作者登录者可挂 —— 裁决与意见分权；
  * publish 的 actor 角色判定（任务契约明确要求）：actor 会话 dict 的有效
    六角色须含 dict_admin —— 判定复用 users_db.effective_six_roles（与
    guards.require_dict_admin 同一实现；legacy role=='admin' 经映射兼判），
    本层不 import streamlit；
  * 除 publish 外本层不读 users 表 —— 三表自洽、可独立建库测试；页面层
    角色门（_can_write/_can_review）与 guards 闸门纵深防御各管一层。

降级（同 ai_ledger 口径）：数据库不可用时写操作返回 0/False、读操作返回
[]/None，只记日志不抛异常 —— 页面可继续渲染「暂不可用」而不是整页崩掉。

安全规则（同 users_db / ai_ledger 口径）：
  1. SQL 一律参数化（get_db_cursor 模式），本文件无一处把值拼进 SQL 文本
     （WHERE/ORDER 只用本模块白名单常量）；
  2. 入参应用层先校验再入库：非法 sense_ref / 内容 / 版本号 / 回避制冲突 /
     非法状态流转根本不进数据库（不依赖 ENUM/UNIQUE 报错；UNIQUE
     (sense_ref, version) 只作并发建版的最后防线）；
  3. 多语句流转（提交审校 / 打回 / 通过）走 autocommit=False 事务 +
     SELECT ... FOR UPDATE 行锁 —— 状态判定与写入原子，不留半流转行。

已知口径（R3-8 · P3 · 批次 12 复审，本轮不修码）：版本脊柱跨作者续基无守卫无
标记 —— create_draft/_validate_refs 的断链四路（不存在版本/跨 sense_ref/0/
非整数）实测全拒，但同 sense_ref 下 based_on 指向他人版本被接受（仅查存在性，
无作者连续性校验）。架构规范 §8 未要求拒绝，不算违约；但换手续基在审计线上
只有逐行 author_id 可对比，无「重提换手」显式留痕 —— A→B(author1)→C(author2)
与正常链在库内不可区分（批次 12：续基换手时可加 remark 或审计标记）。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import pymysql

from src.mysql_db import get_db_cursor
from src.users_db import effective_six_roles

logger = logging.getLogger(__name__)

# ============================================
# 常量（契约 §10 DDL 枚举原样；入口校验用，非法值不进数据库）
# ============================================
# definition_versions.status 全集。MVP 状态机只经
# draft / in_review / final / published / rejected 五态；
# reviewed / revised / approved 为两级终审扩展占位（见模块 docstring）。
STATUS_DRAFT = "draft"
STATUS_IN_REVIEW = "in_review"
STATUS_REVIEWED = "reviewed"
STATUS_REVISED = "revised"
STATUS_APPROVED = "approved"
STATUS_FINAL = "final"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"
VERSION_STATUSES = (
    STATUS_DRAFT, STATUS_IN_REVIEW, STATUS_REVIEWED, STATUS_REVISED,
    STATUS_APPROVED, STATUS_FINAL, STATUS_PUBLISHED, STATUS_REJECTED,
)

# review_tasks.verdict 四值。MVP 只落 pending / approved / revision_requested；
# rejected（直接否决，不经打回修订）为终裁扩展占位。
VERDICT_PENDING = "pending"
VERDICT_APPROVED = "approved"
VERDICT_REJECTED = "rejected"
VERDICT_REVISION_REQUESTED = "revision_requested"
VERDICTS = (
    VERDICT_PENDING, VERDICT_APPROVED, VERDICT_REJECTED,
    VERDICT_REVISION_REQUESTED,
)

# 终裁决策集（adjudicate_final 的 decision 入参全集）：终裁只有通过/否决两向，
# 「要求修订」是受派审校人的打回动作（request_revision），不进终裁口径。
ADJUDICATE_DECISIONS = (VERDICT_APPROVED, VERDICT_REJECTED)

# list 类接口单次返回上限（仿 ai_ledger.MAX_LIST_LIMIT；防一次性拖全表）
MAX_LIST_LIMIT = 500

# 字段长度口径（与 DDL 列型对齐；应用层先拒，不靠 MySQL 截断/报错）
MAX_SENSE_REF_LEN = 60      # sense_ref VARCHAR(60)
MAX_STYLE_VERSION_LEN = 40  # style_version VARCHAR(40)
MAX_CONTENT_LEN = 1_000_000  # content MEDIUMTEXT（16MB），取宽松上限防误传巨串
MAX_TEXT_LEN = 16_000       # note/body TEXT（65535 字节），CJK 3 字节留余量

# sense_ref 三段式：范畴段（字母开头的字母/数字/下划线/连字符，≤31 字符）
# :cs_id:oald_id（两段 id 均为非负整数，0 = 该空间未落位）。总长 ≤ 60 另行校验。
SENSE_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,30}:\d{1,10}:\d{1,10}$")

# ============================================
# 建表 DDL（契约 §10 表设计原样；幂等，CREATE TABLE IF NOT EXISTS）
# 不加 users 外键（author_id/reviewer_id 为软引用），三表可独立先行建表
# （测试库 web_word_writing_test 无 users 表也能全量跑）。
# ============================================

DEFINITION_VERSIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS definition_versions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sense_ref VARCHAR(60) NOT NULL COMMENT '三段式锚 范畴包名:cs_senses.id:oald_senses.id',
  version INT NOT NULL COMMENT 'sense_ref 内版本号，自动递增',
  author_id INT NULL COMMENT '撰写人 users.id（软引用；系统登记为 NULL）',
  based_on_version INT NULL COMMENT '所基版本号（同 sense_ref 的 version 号，非行 id；打回重提时挂）',
  style_version VARCHAR(40) NULL COMMENT '体例版本占位（style.yaml@v1；批次 8 体例工单接入）',
  content MEDIUMTEXT NOT NULL COMMENT '释义成文',
  status ENUM('draft','in_review','reviewed','revised','approved',
              'final','published','rejected') NOT NULL DEFAULT 'draft',
  ai_draft JSON NULL COMMENT 'AI/模板草稿快照（审校对照用；模板预览或 AI 生成留痕）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_definition_versions (sense_ref, version),
  KEY idx_definition_versions_ref (sense_ref, status),
  KEY idx_definition_versions_author (author_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

REVIEW_TASKS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS review_tasks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  version_id INT NOT NULL COMMENT 'definition_versions.id（软引用）',
  reviewer_id INT NULL COMMENT '受派审校人 users.id（软引用；回避制硬校验对象）',
  round TINYINT NOT NULL DEFAULT 1 COMMENT '审校轮次（同版本重复提交自动 +1）',
  verdict ENUM('pending','approved','rejected','revision_requested') NOT NULL DEFAULT 'pending',
  note TEXT NULL COMMENT '裁决意见（提交说明/打回理由/通过留言）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_review_tasks_pending (verdict, reviewer_id),
  KEY idx_review_tasks_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

REVIEW_COMMENTS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS review_comments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  version_id INT NOT NULL COMMENT 'definition_versions.id（软引用）',
  reviewer_id INT NULL COMMENT '留言人 users.id（软引用；回避制硬校验对象）',
  body TEXT NOT NULL COMMENT '意见正文',
  resolved TINYINT(1) NOT NULL DEFAULT 0 COMMENT '0=未处理 1=已处理（标记不删行）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_review_comments_version (version_id),
  KEY idx_review_comments_open (version_id, resolved)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


def ensure_writing_tables() -> None:
    """幂等创建编纂成文域三表（契约 §10 表设计原样，可重复调用）。

    无外键依赖（author_id/reviewer_id/version_id 均软引用），可独立于
    users 等其他模块先行建表；被数据库拒绝（无权限等）只记 error 日志
    不抛异常，页面可继续渲染（降级口径同 ai_ledger.ensure_ai_ledger_tables）。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(DEFINITION_VERSIONS_TABLE_SQL)
            cursor.execute(REVIEW_TASKS_TABLE_SQL)
            cursor.execute(REVIEW_COMMENTS_TABLE_SQL)
    except pymysql.Error as e:
        logger.error(f"编纂成文域三表初始化失败（MySQL）: {e}")
    except Exception as e:
        logger.error(f"编纂成文域三表初始化意外错误: {e}")


# ============================================
# 入参规整（应用层先拒，非法值不进数据库；仿 ai_ledger 同名助手）
# ============================================
_INVALID = object()  # 字符串校验失败的哨兵（None 是合法值，不能复用）


def _as_int(value: Any) -> Optional[int]:
    """宽松转 int（int/float/int-str 可转；bool/None/其余 None）—— 防脏参数。

    float NaN/Inf 也拒：int(nan) 抛 ValueError，正好落进 except。
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_positive_int(value: Any) -> Optional[int]:
    """宽松转正 int（>0）；其余 None。id 类参数（author/reviewer/version 行）用。"""
    got = _as_int(value)
    return got if got is not None and got > 0 else None


def _clean_optional_str(value: Any, max_len: int) -> Any:
    """可选字符串规整：None/纯空白 → None；去首尾空白；超长 → _INVALID。

    Returns:
        None（空）| str（去空白后）| _INVALID（类型不对或超长，调用方拒绝）
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        return _INVALID
    return cleaned


def valid_sense_ref(sense_ref: Any) -> bool:
    """sense_ref 三段式格式校验（``范畴:cs_id:oald_id``，总长 ≤ 60）。

    只查格式不做存在性校验（软引用口径，见模块 docstring）；0 占位合法。
    """
    if not isinstance(sense_ref, str):
        return False
    ref = sense_ref.strip()
    if not ref or len(ref) > MAX_SENSE_REF_LEN:
        return False
    return bool(SENSE_REF_RE.match(ref))


def _clean_content(content: Any) -> Any:
    """content 规整：非空字符串（strip 后非空）原样返回；其余 _INVALID。

    存库保留原文（不 strip）—— 成文是有格式的散文，首尾空白可能是作者
    有意的排版；只以 strip 结果做「非空」判定。
    """
    if not isinstance(content, str):
        return _INVALID
    if not content.strip():
        return _INVALID
    if len(content) > MAX_CONTENT_LEN:
        return _INVALID
    return content


def _dump_ai_draft(ai_draft: Any) -> Any:
    """ai_draft → JSON 串；None 原样（不挂快照）；非法返回 _INVALID。

    只有 dict/list 是合法快照（JSON 容器，与 ai_ledger._dump_proposal 同口径）；
    NaN/Inf 拒 —— json.dumps 默认会产出非法 JSON 字面量，MySQL JSON 列必炸。
    """
    if ai_draft is None:
        return None
    if not isinstance(ai_draft, (dict, list)):
        return _INVALID
    try:
        return _dump_json(ai_draft)
    except (TypeError, ValueError):
        return _INVALID


def _dump_json(payload: Any) -> str:
    """dict/list → JSON 串（ensure_ascii=False，禁 NaN/Inf）。"""
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def _parse_ai_draft(raw: Any) -> Optional[Any]:
    """JSON 列 ai_draft → dict/list；NULL/解析失败返回 None（无快照）。

    PyMySQL 对 JSON 列可能给 str 或 dict，两种都接（仿 ai_ledger 口径）。
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, (dict, list)) else None
    return None


def _validate_refs(cursor, ref: str, based_on: Optional[int]) -> bool:
    """based_on_version 存在性校验（同 sense_ref 的既有版号）。

    版本链完整性：based_on_version 必须指向同 sense_ref 下已存在的版本号
    （且必然小于新 version —— 新版号取 MAX+1）。返回 False 即拒绝建版。
    """
    if based_on is None:
        return True
    cursor.execute(
        "SELECT COUNT(*) AS n FROM definition_versions "
        "WHERE sense_ref = %s AND version = %s",
        (ref, based_on),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def _row_to_version(row: Dict[str, Any]) -> Dict[str, Any]:
    """definition_versions 行 → 对外 dict（ai_draft 解析回容器）。"""
    out = dict(row)
    out["ai_draft"] = _parse_ai_draft(out.get("ai_draft"))
    return out


# ============================================
# 撰写：建版与改稿（draft 态）
# ============================================

def create_draft(
    sense_ref: str,
    author_id: Optional[int],
    content: str,
    based_on_version: Optional[int] = None,
    style_version: Optional[str] = None,
    ai_draft: Any = None,
    *,
    allow_system: bool = False,
) -> int:
    """新建释义草稿（status='draft'，version 在 sense_ref 内自动递增）。

    版本号 = 同 sense_ref 下 MAX(version)+1（UNIQUE(sense_ref, version)
    兜底并发建版：撞 UNIQUE 即建版失败返回 0，调用方重试即可）。

    **author_id=None 收紧（R1-4，施工规范 §14 批次 12）**：无主（系统登记）
    行不允许默认创建 —— keyword ``allow_system=False`` 缺省拒绝并返回 0；
    仅内部系统作业（历史数据补登记/灌库脚本）显式传 ``allow_system=True``
    豁免（调用点须 docstring 注明理由）。理由：author_id 为 NULL 的行在
    R1-4 后不可进入人工审校链（submit_for_review / approve / adjudicate_final
    一律拒绝「系统登记行不可人工审校，先补登记作者」），默认放行建无主行
    只会生产永远无法定稿的死行，且给「匿名写入权威域」留了旁路 —— 页面与
    测试调用一律传撰写人 users.id。

    Args:
        sense_ref: 三段式锚 ``范畴包名:cs_senses.id:oald_senses.id``
            （如 ``motion:12:345``；未落位槽位 0 占位，见模块 docstring）。
        author_id: 撰写人 users.id（软引用）。None 须同时传
            ``allow_system=True``（系统登记口径，见上），否则拒绝。
        content: 释义成文（非空，≤ MAX_CONTENT_LEN）。
        based_on_version: 所基版本号（同 sense_ref 的既有 version 号，非行
            id；打回重提时传被拒版的 version 号）。给定时校验存在性，
            不存在拒绝建版（版本链完整性）。
        style_version: 体例版本占位（如 ``style.yaml@v1``；≤ 40 字符）。
        ai_draft: AI/模板草稿快照（dict/list；JSON 落库，审校对照用）。
        allow_system: 系统作业显式越过（author_id=None 时必须 True；
            调用点 docstring 注明理由）。

    Returns:
        int: 新行 id（>0）；参数非法 / based_on 不存在 /
        author_id=None 且未显式 allow_system / 数据库错误返回 0。
    """
    ref = sense_ref.strip() if isinstance(sense_ref, str) else ""
    if not valid_sense_ref(ref):
        logger.error(f"create_draft 拒绝非法 sense_ref: {sense_ref!r}")
        return 0
    author = _as_positive_int(author_id) if author_id is not None else None
    if author_id is not None and author is None:
        logger.error(f"create_draft 拒绝非法 author_id: {author_id!r}")
        return 0
    if author is None and not allow_system:
        logger.error(
            "create_draft 拒绝 author_id=None（R1-4 收紧：无主行不可默认创建"
            "——系统登记行不可人工审校；内部系统作业须显式传 allow_system=True，"
            "页面/测试调用一律传撰写人 users.id）"
        )
        return 0
    clean_content = _clean_content(content)
    if clean_content is _INVALID:
        logger.error("create_draft 拒绝空/超长/非字符串 content")
        return 0
    based_on = _as_positive_int(based_on_version) if based_on_version is not None else None
    if based_on_version is not None and based_on is None:
        logger.error(f"create_draft 拒绝非法 based_on_version: {based_on_version!r}")
        return 0
    style = _clean_optional_str(style_version, MAX_STYLE_VERSION_LEN)
    if style is _INVALID:
        logger.error(f"create_draft 拒绝非法 style_version: {style_version!r}")
        return 0
    ai_json = _dump_ai_draft(ai_draft)
    if ai_json is _INVALID:
        logger.error("create_draft 拒绝非法 ai_draft（须为可 JSON 序列化的 dict/list）")
        return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM definition_versions "
                "WHERE sense_ref = %s",
                (ref,),
            )
            next_version = int(cursor.fetchone()["v"] or 0) + 1
            if not _validate_refs(cursor, ref, based_on):
                logger.error(
                    f"create_draft 拒绝：based_on_version={based_on} 在 {ref} 下不存在"
                )
                return 0
            cursor.execute(
                "INSERT INTO definition_versions (sense_ref, version, author_id, "
                "based_on_version, style_version, content, status, ai_draft) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (ref, next_version, author, based_on, style, clean_content,
                 STATUS_DRAFT, ai_json),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"create_draft 失败（{ref}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"create_draft 意外错误（{ref}）: {e}")
        return 0


def update_draft(
    version_id: int,
    expect_version: int,
    content: str,
    style_version: Optional[str] = None,
    ai_draft: Any = None,
    *,
    author_id: Optional[int] = None,
) -> bool:
    """改写草稿（仅 draft 态；乐观锁 expect_version + 作者守卫）。

    乐观锁口径：expect_version 是编辑表单装载时看到的版本号 —— WHERE
    id + version + status='draft' 三重守卫，装载后该行状态已流转（或目标
    行已易主为新版）时更新不生效返回 False，调用方刷新后重试（先存后提、
    双开标签页互踩等场景由它挡住）。version 列本身不可变，行内更新不改号；
    行存在性先查后写（MySQL 对「值无变化」的 UPDATE 计 0 受影响行，
    不能拿 rowcount 当失败 —— 以前置 SELECT 为准）。

    **作者守卫（R1-3，施工规范 §14 批次 12）**：UPDATE WHERE 追加
    ``AND author_id <=> %s``（NULL 安全相等），入口前置 SELECT 同步校验 ——
    ``author_id`` 须与目标行 author_id 一致才可改写：author_id=None 只匹配
    author_id 为 NULL 的系统登记行；传他人 id（含不传而目标是他人草稿）
    一律拒绝并记日志「作者不符」。R1 报告复现③（update_draft 直接改写
    他人草稿＝内容劫持）的数据层收口；页面撰写台传当前会话用户 id
    （mode='update' 已保证目标是本人草稿）。

    Args:
        version_id: 目标行 id（definition_versions.id）。
        expect_version: 期望版本号（须与该行 version 一致）。
        content: 新成文（非空，≤ MAX_CONTENT_LEN）。
        style_version: 体例版本（None = 置空；全量覆盖口径）。
        ai_draft: 快照（None = 置空；全量覆盖口径）。
        author_id: 撰写人 users.id（须与目标行 author_id 一致；None 仅匹配
            系统登记行 —— fail-closed，不给「不校验作者」留旁路）。

    Returns:
        bool: 更新成功为 True；行不存在 / expect_version 不符 / 已非 draft /
        作者不符（R1-3）/ 参数非法 / 数据库错误为 False。
    """
    vid = _as_positive_int(version_id)
    ev = _as_positive_int(expect_version)
    if vid is None or ev is None:
        logger.error(f"update_draft 拒绝非法 id/expect_version: {version_id!r}/{expect_version!r}")
        return False
    author = _as_positive_int(author_id) if author_id is not None else None
    if author_id is not None and author is None:
        logger.error(f"update_draft 拒绝非法 author_id: {author_id!r}")
        return False
    clean_content = _clean_content(content)
    if clean_content is _INVALID:
        logger.error("update_draft 拒绝空/超长/非字符串 content")
        return False
    style = _clean_optional_str(style_version, MAX_STYLE_VERSION_LEN)
    if style is _INVALID:
        logger.error(f"update_draft 拒绝非法 style_version: {style_version!r}")
        return False
    ai_json = _dump_ai_draft(ai_draft)
    if ai_json is _INVALID:
        logger.error("update_draft 拒绝非法 ai_draft（须为可 JSON 序列化的 dict/list）")
        return False
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "SELECT status, author_id FROM definition_versions "
                "WHERE id = %s AND version = %s FOR UPDATE",
                (vid, ev),
            )
            row = cursor.fetchone()
            if row is None:
                logger.error(
                    f"update_draft 目标行不存在或版本不符（id={vid}, expect={ev}）"
                )
                return False
            if row.get("status") != STATUS_DRAFT:
                logger.error(
                    f"update_draft 拒绝非 draft 态行（id={vid}, status={row.get('status')}）"
                )
                return False
            row_author = (
                _as_positive_int(row.get("author_id"))
                if row.get("author_id") is not None
                else None
            )
            if row_author != author:
                logger.error(
                    f"update_draft 作者不符拒绝（R1-3 内容劫持防护）：id={vid} "
                    f"行 author_id={row.get('author_id')}，调用方声称 "
                    f"author_id={author_id!r} —— 只能改写本人草稿"
                )
                return False
            cursor.execute(
                "UPDATE definition_versions SET content = %s, style_version = %s, "
                "ai_draft = %s WHERE id = %s AND version = %s AND status = %s "
                "AND author_id <=> %s",
                (clean_content, style, ai_json, vid, ev, STATUS_DRAFT, author),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"update_draft 失败（id={vid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"update_draft 意外错误（id={vid}）: {e}")
        return False


# ============================================
# 提交与审校（状态机流转 + 回避制）
# ============================================

def _load_version_for_guard(
    cursor, version_id: int, expect_status: Optional[str]
) -> Optional[Dict[str, Any]]:
    """行锁读版本行（供事务内流转前置守卫）；不存在 / 状态不符返回 None。"""
    cursor.execute(
        "SELECT id, sense_ref, version, author_id, status FROM definition_versions "
        "WHERE id = %s FOR UPDATE",
        (version_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    if expect_status is not None and row.get("status") != expect_status:
        return None
    return row


def _recusal_violated(author_id: Any, reviewer_id: int, action: str,
                      sense_ref: Any, version: Any) -> bool:
    """回避制判定（§8 无豁免）：审校动作的 reviewer 不得是版本作者。

    author_id 为 NULL（系统登记行）无可比对对象 —— 如实放行并记日志。
    注意 R1-4 收口后本函数的 NULL 放行分支只服务 add_comment /
    request_revision；审校链三入口（submit_for_review / approve /
    adjudicate_final）在回避制判定**之前**先过 _system_row_blocked
    （NULL 行直接拒绝），不再到达此处。
    """
    if author_id is None:
        logger.warning(
            f"{action}: 版本 {sense_ref} v{version} author_id 为 NULL，"
            "回避制无可比对对象，放行（系统登记口径）"
        )
        return False
    if int(author_id) == int(reviewer_id):
        logger.error(
            f"{action} 回避制拦截：用户 {reviewer_id} 不得审校自写词条"
            f"（{sense_ref} v{version}）——回避制无豁免（架构规范 §8）"
        )
        return True
    return False


def _system_row_blocked(author_id: Any, action: str,
                        sense_ref: Any, version: Any) -> bool:
    """系统登记行守卫（R1-4，施工规范 §14 批次 12）：author_id 为 NULL 的
    版本行不可进入人工审校链。

    submit_for_review / approve / adjudicate_final 三处审校链入口在回避制
    判定之前调用：命中 NULL 行返回 True（调用方拒绝）并记日志「系统登记行
    不可人工审校，先补登记作者」。理由：NULL 行无回避制比对对象、无作者
    可追责（R1 报告复现⑤全链放行），且 create_draft 的 author_id=None 已
    收紧为 allow_system 显式豁免 —— 存量无主行须先补登记作者再入审校链。
    add_comment / request_revision 不在本守卫范围（意见线与受派裁决维持
    旧口径，见 _recusal_violated）。
    """
    if author_id is None:
        logger.error(
            f"{action} 拒绝：{sense_ref} v{version} author_id 为 NULL —— "
            "系统登记行不可人工审校，先补登记作者（R1-4）"
        )
        return True
    return False


def submit_for_review(version_id: int, reviewer_id: int,
                      note: Optional[str] = None) -> bool:
    """提交初审：draft → in_review，并创建待审任务（verdict='pending'）。

    G4 闸门（撰写→审校）的人工侧落点；AI 体例质检挂钩批次 8 接入。
    回避制硬校验：reviewer_id 不得等于版本 author_id（无豁免，含词典
    管理员 —— 自写词条自审在此直接拒绝）。author_id 为 NULL 的系统登记行
    不可提交审校（R1-4：先补登记作者）。轮次自动递增：同 version_id
    若存在历史任务（理论流程不会发生，防御性支持），round = MAX+1。

    Args:
        version_id: 草稿行 id（须处于 draft 态）。
        reviewer_id: 受派审校人 users.id（正整数；≠ author_id）。
        note: 提交说明（可选；≤ MAX_TEXT_LEN）。

    Returns:
        bool: 提交成功为 True；行不存在 / 非 draft 态 / 回避制冲突 /
        参数非法 / 数据库错误为 False（状态保持 draft，不留半流转）。
    """
    vid = _as_positive_int(version_id)
    rid = _as_positive_int(reviewer_id)
    if vid is None or rid is None:
        logger.error(
            f"submit_for_review 拒绝非法 version_id/reviewer_id: {version_id!r}/{reviewer_id!r}"
        )
        return False
    clean_note = _clean_optional_str(note, MAX_TEXT_LEN)
    if clean_note is _INVALID:
        logger.error(f"submit_for_review 拒绝非法 note: {note!r}")
        return False
    try:
        with get_db_cursor(autocommit=False) as cursor:
            row = _load_version_for_guard(cursor, vid, STATUS_DRAFT)
            if row is None:
                logger.error(
                    f"submit_for_review 拒绝：id={vid} 不存在或非 draft 态"
                )
                return False
            if _system_row_blocked(row.get("author_id"), "submit_for_review",
                                   row.get("sense_ref"), row.get("version")):
                return False
            if _recusal_violated(row.get("author_id"), rid, "submit_for_review",
                                 row.get("sense_ref"), row.get("version")):
                return False
            cursor.execute(
                "SELECT COALESCE(MAX(round), 0) AS r FROM review_tasks "
                "WHERE version_id = %s",
                (vid,),
            )
            round_no = int(cursor.fetchone()["r"] or 0) + 1
            cursor.execute(
                "INSERT INTO review_tasks (version_id, reviewer_id, round, verdict, note) "
                "VALUES (%s, %s, %s, %s, %s)",
                (vid, rid, round_no, VERDICT_PENDING, clean_note),
            )
            cursor.execute(
                "UPDATE definition_versions SET status = %s "
                "WHERE id = %s AND status = %s",
                (STATUS_IN_REVIEW, vid, STATUS_DRAFT),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"submit_for_review 失败（id={vid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"submit_for_review 意外错误（id={vid}）: {e}")
        return False


def _load_pending_task(cursor, version_id: int,
                       reviewer_id: int) -> Optional[Dict[str, Any]]:
    """取该版本最新一条待审任务并校验受派审校人；不匹配返回 None。"""
    cursor.execute(
        "SELECT id, reviewer_id FROM review_tasks "
        "WHERE version_id = %s AND verdict = %s ORDER BY id DESC LIMIT 1",
        (version_id, VERDICT_PENDING),
    )
    task = cursor.fetchone()
    if task is None:
        return None
    if int(task.get("reviewer_id") or 0) != int(reviewer_id):
        return None
    return task


def add_comment(version_id: int, reviewer_id: int, body: str) -> int:
    """挂审校意见（意见线逐条挂版本），返回意见 id（失败 0）。

    回避制硬校验：留言人不得是版本作者（意见线是审校侧动作，无豁免）。
    与裁决动作分权：意见线任何非作者登录者可挂（不限受派审校人），
    request_revision / approve 仅受派审校人可执行。
    对版本状态无要求（draft 即可预挂意见 —— 审校人提前介入口径）。

    Returns:
        int: 意见 id（>0）；版本不存在 / 回避制冲突 / body 空 / 参数非法 /
        数据库错误返回 0。
    """
    vid = _as_positive_int(version_id)
    rid = _as_positive_int(reviewer_id)
    if vid is None or rid is None:
        logger.error(
            f"add_comment 拒绝非法 version_id/reviewer_id: {version_id!r}/{reviewer_id!r}"
        )
        return 0
    clean_body = _clean_optional_str(body, MAX_TEXT_LEN)
    if clean_body is None or clean_body is _INVALID:
        logger.error("add_comment 拒绝空/超长/非字符串 body")
        return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT author_id, sense_ref, version FROM definition_versions "
                "WHERE id = %s",
                (vid,),
            )
            row = cursor.fetchone()
            if row is None:
                logger.error(f"add_comment 目标版本不存在（id={vid}）")
                return 0
            if _recusal_violated(row.get("author_id"), rid, "add_comment",
                                 row.get("sense_ref"), row.get("version")):
                return 0
            cursor.execute(
                "INSERT INTO review_comments (version_id, reviewer_id, body) "
                "VALUES (%s, %s, %s)",
                (vid, rid, clean_body),
            )
            return int(cursor.lastrowid)
    except pymysql.Error as e:
        logger.error(f"add_comment 失败（id={vid}）: {e}")
        return 0
    except Exception as e:
        logger.error(f"add_comment 意外错误（id={vid}）: {e}")
        return 0


def request_revision(version_id: int, reviewer_id: int,
                     note: Optional[str] = None) -> bool:
    """要求修订（打回）：in_review → rejected，任务 verdict → revision_requested。

    仅受派审校人可执行（review_tasks.reviewer_id 一致）；回避制硬校验
    （reviewer ≠ author）。note 给定时覆盖任务 note（打回理由留痕），
    缺省保留提交时说明。作者以 create_draft（version 自动 +1、
    based_on_version=被拒版号）重提 —— 版本链不断。

    Returns:
        bool: 打回成功为 True；行不存在 / 非 in_review 态 / 无待审任务 /
        非受派审校人 / 回避制冲突 / 数据库错误为 False。
    """
    vid = _as_positive_int(version_id)
    rid = _as_positive_int(reviewer_id)
    if vid is None or rid is None:
        logger.error(
            f"request_revision 拒绝非法 version_id/reviewer_id: {version_id!r}/{reviewer_id!r}"
        )
        return False
    clean_note = _clean_optional_str(note, MAX_TEXT_LEN)
    if clean_note is _INVALID:
        logger.error(f"request_revision 拒绝非法 note: {note!r}")
        return False
    try:
        with get_db_cursor(autocommit=False) as cursor:
            row = _load_version_for_guard(cursor, vid, STATUS_IN_REVIEW)
            if row is None:
                logger.error(
                    f"request_revision 拒绝：id={vid} 不存在或非 in_review 态"
                )
                return False
            if _recusal_violated(row.get("author_id"), rid, "request_revision",
                                 row.get("sense_ref"), row.get("version")):
                return False
            task = _load_pending_task(cursor, vid, rid)
            if task is None:
                logger.error(
                    f"request_revision 拒绝：id={vid} 无受派给 {rid} 的待审任务"
                )
                return False
            cursor.execute(
                "UPDATE review_tasks SET verdict = %s, note = COALESCE(%s, note) "
                "WHERE id = %s AND verdict = %s",
                (VERDICT_REVISION_REQUESTED, clean_note, int(task["id"]),
                 VERDICT_PENDING),
            )
            cursor.execute(
                "UPDATE definition_versions SET status = %s "
                "WHERE id = %s AND status = %s",
                (STATUS_REJECTED, vid, STATUS_IN_REVIEW),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"request_revision 失败（id={vid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"request_revision 意外错误（id={vid}）: {e}")
        return False


def approve(version_id: int, reviewer_id: int,
            note: Optional[str] = None) -> bool:
    """审校通过（MVP 终审）：in_review → final，任务 verdict → approved。

    **两级终审口径（架构规范 §8）**：普通词条 reviewer 终审即 final ——
    本函数即该口径的 MVP 单级实现；「争议词条（仲裁后存疑/申诉/抽查）升级
    词典管理员终裁」是**例外通道而非必经站**，其接口位（reviewed→approved
    →final 链展开＋升级/改派动作＋终裁留痕）留给批次 8 集成在此补齐
    （契约 DDL 的 reviewed/revised/approved 枚举占位即为此预留），本版不实现。
    仅受派审校人可执行；回避制硬校验（无豁免，含词典管理员 —— 自写词条
    由其他 reviewer 终审）；author_id 为 NULL 的系统登记行不可审校通过
    （R1-4：先补登记作者）。

    Args:
        version_id: in_review 态版本行 id。
        reviewer_id: 受派审校人 users.id。
        note: 通过留言（可选；给定时覆盖任务 note）。

    Returns:
        bool: 通过为 True；行不存在 / 非 in_review 态 / 无待审任务 /
        非受派审校人 / 回避制冲突 / 数据库错误为 False。
    """
    vid = _as_positive_int(version_id)
    rid = _as_positive_int(reviewer_id)
    if vid is None or rid is None:
        logger.error(
            f"approve 拒绝非法 version_id/reviewer_id: {version_id!r}/{reviewer_id!r}"
        )
        return False
    clean_note = _clean_optional_str(note, MAX_TEXT_LEN)
    if clean_note is _INVALID:
        logger.error(f"approve 拒绝非法 note: {note!r}")
        return False
    try:
        with get_db_cursor(autocommit=False) as cursor:
            row = _load_version_for_guard(cursor, vid, STATUS_IN_REVIEW)
            if row is None:
                logger.error(f"approve 拒绝：id={vid} 不存在或非 in_review 态")
                return False
            if _system_row_blocked(row.get("author_id"), "approve",
                                   row.get("sense_ref"), row.get("version")):
                return False
            if _recusal_violated(row.get("author_id"), rid, "approve",
                                 row.get("sense_ref"), row.get("version")):
                return False
            task = _load_pending_task(cursor, vid, rid)
            if task is None:
                logger.error(f"approve 拒绝：id={vid} 无受派给 {rid} 的待审任务")
                return False
            cursor.execute(
                "UPDATE review_tasks SET verdict = %s, note = COALESCE(%s, note) "
                "WHERE id = %s AND verdict = %s",
                (VERDICT_APPROVED, clean_note, int(task["id"]), VERDICT_PENDING),
            )
            cursor.execute(
                "UPDATE definition_versions SET status = %s "
                "WHERE id = %s AND status = %s",
                (STATUS_FINAL, vid, STATUS_IN_REVIEW),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"approve 失败（id={vid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"approve 意外错误（id={vid}）: {e}")
        return False


def adjudicate_final(
    version_id: int,
    adjudicator_id: int,
    decision: str,
    note: str = "",
    *,
    actor: Any = None,
) -> bool:
    """词典管理员终裁（批次 8 G6 契约；两级终审的例外通道收口，架构规范 §8）。

    **角色口径**：actor（会话用户 dict）的有效六角色须含 dict_admin —— 判定
    复用 users_db.effective_six_roles（与 guards.require_dict_admin 同一实现；
    legacy role=='admin' 经映射兼判）。actor 须显式传入（本层不 import
    streamlit、不读 users 表，测试可注入）；actor 缺失/非 dict/无 dict_admin
    一律拒绝（fail-closed）。adjudicator_id 是终裁人 users.id（留痕用，页面层
    传会话用户 id）；**R1-4 冒名收口：本层强制 adjudicator_id == actor["id"]**
    —— 不一致即返回 False 并记日志「终裁冒名拒绝」（R1 报告复现④：以 A 会话
    冒 B 之名留痕终裁，伪造审校记录）。

    **状态机（终态图）**::

        in_review ──decision=approved──▶ final     （终裁通过 = final 直达：
                                                    两级终审收口，跳过
                                                    reviewed/approved 中段占位）
        approved  ──decision=approved──▶ final     （补终裁：两级链中段的
                                                    approved 行收口到 final）
        in_review ──decision=rejected──▶ rejected  （终裁否决，直接打回侧支；
                                                    作者重提走 create_draft
                                                    version+1 + based_on_version）
        其余状态（draft / reviewed / revised / final / published / rejected）
        与非法 decision 一律拒绝（不进数据库）。

    **留痕**：每次终裁向 review_tasks 插入**新任务行**（不覆盖受派审校人的
    既有任务行 —— 伪造 verdict 即篡改审校记录，纪律禁止）：round =
    MAX(round)+1（round+1 标记终裁轮），verdict = decision，reviewer_id =
    adjudicator_id，note = 终裁意见。受派审校人未决的 pending 任务保持原样
    （终裁已收口后其裁决动作会被 approve/request_revision 的状态守卫拒绝，
    页面层如实转述）；list_pending_reviews 的联结读侧可见版本状态。

    **回避制无豁免（§8，含词典管理员）**：adjudicator_id 不得等于版本
    author_id —— 自写词条由其他词典管理员终裁；author_id 为 NULL（系统登记）
    的行直接拒绝（R1-4：系统登记行不可人工审校，先补登记作者 —— 不再
    「无可比对对象即放行」）。

    Args:
        version_id: 版本行 id（须处于 in_review / approved 态，见状态机）。
        adjudicator_id: 终裁人 users.id（正整数；≠ author_id，回避制）。
        decision: 终裁决策，须 ∈ ADJUDICATE_DECISIONS（approved / rejected）。
        note: 终裁意见（可选；否决理由由页面层强制必填，数据层不重复强制）。
        actor: 会话用户 dict（显式传入；有效六角色须含 dict_admin）。

    Returns:
        bool: 终裁成功为 True；行不存在 / 状态不符 / decision 非法 / actor
        无 dict_admin / 回避制冲突 / 参数非法 / 数据库错误为 False（状态
        保持原态、不留半流转）。
    """
    vid = _as_positive_int(version_id)
    aid = _as_positive_int(adjudicator_id)
    if vid is None or aid is None:
        logger.error(
            f"adjudicate_final 拒绝非法 version_id/adjudicator_id: "
            f"{version_id!r}/{adjudicator_id!r}"
        )
        return False
    if decision not in ADJUDICATE_DECISIONS:
        logger.error(
            f"adjudicate_final 拒绝非法 decision: {decision!r}"
            f"（须 ∈ {ADJUDICATE_DECISIONS}）"
        )
        return False
    clean_note = _clean_optional_str(note, MAX_TEXT_LEN)
    if clean_note is _INVALID:
        logger.error(f"adjudicate_final 拒绝非法 note: {note!r}")
        return False
    if not isinstance(actor, dict):
        logger.error(
            "adjudicate_final 拒绝：actor 须显式传入会话用户 dict（未登录"
            "写路径 fail-closed）"
        )
        return False
    if "dict_admin" not in effective_six_roles(actor):
        logger.error(
            f"adjudicate_final 回绝：actor（{actor.get('username', '?')}）"
            "有效角色集不含 dict_admin —— 终裁仅词典管理员（架构规范 §8）"
        )
        return False
    actor_id = _as_positive_int(actor.get("id"))
    if actor_id is None or actor_id != aid:
        logger.error(
            f"adjudicate_final 终裁冒名拒绝（R1-4）：adjudicator_id="
            f"{adjudicator_id!r} ≠ actor['id']={actor.get('id')!r} "
            f"（actor={actor.get('username', '?')}）—— 留痕人必须等于操作人，"
            "伪造他人终裁记录一律拒绝"
        )
        return False
    if decision == VERDICT_APPROVED:
        allowed_from = (STATUS_IN_REVIEW, STATUS_APPROVED)
        target_status = STATUS_FINAL
    else:
        allowed_from = (STATUS_IN_REVIEW,)
        target_status = STATUS_REJECTED
    try:
        with get_db_cursor(autocommit=False) as cursor:
            cursor.execute(
                "SELECT id, sense_ref, version, author_id, status "
                "FROM definition_versions WHERE id = %s FOR UPDATE",
                (vid,),
            )
            row = cursor.fetchone()
            if row is None:
                logger.error(f"adjudicate_final 拒绝：id={vid} 不存在")
                return False
            if row.get("status") not in allowed_from:
                logger.error(
                    f"adjudicate_final 拒绝：id={vid} 状态 "
                    f"{row.get('status')} 不在可终裁态 {allowed_from}"
                )
                return False
            if _system_row_blocked(row.get("author_id"), "adjudicate_final",
                                   row.get("sense_ref"), row.get("version")):
                return False
            if _recusal_violated(row.get("author_id"), aid, "adjudicate_final",
                                 row.get("sense_ref"), row.get("version")):
                return False
            cursor.execute(
                "SELECT COALESCE(MAX(round), 0) AS r FROM review_tasks "
                "WHERE version_id = %s",
                (vid,),
            )
            round_no = int(cursor.fetchone()["r"] or 0) + 1
            cursor.execute(
                "INSERT INTO review_tasks (version_id, reviewer_id, round, "
                "verdict, note) VALUES (%s, %s, %s, %s, %s)",
                (vid, aid, round_no, decision, clean_note),
            )
            cursor.execute(
                "UPDATE definition_versions SET status = %s "
                "WHERE id = %s AND status = %s",
                (target_status, vid, row.get("status")),
            )
        return True
    except pymysql.Error as e:
        logger.error(f"adjudicate_final 失败（id={vid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"adjudicate_final 意外错误（id={vid}）: {e}")
        return False


def publish(version_id: int, actor: Any) -> bool:
    """定稿发布：final → published（G6 闸门位，仅 dict_admin 口径）。

    角色口径（任务契约）：actor（会话用户 dict）的有效六角色须含
    dict_admin —— 判定复用 users_db.effective_six_roles（与
    guards.require_dict_admin 同一实现；legacy role=='admin' 经映射兼判，
    本层不 import streamlit / 不读 users 表，测试可注入 actor dict）。

    **G6 硬闸门（许可强制：发布释义须自产/改写；体例终检；备份新鲜）由
    批次 8 在页面/集成层接管** —— 本期函数内只做角色口径 + 状态机，
    通过 publish ≠ 已过 G6（docstring 如实注明，防误读）。

    Args:
        version_id: final 态版本行 id。
        actor: 会话用户 dict（含 role/roles；非 dict 一律拒绝）。

    Returns:
        bool: 发布成功为 True；非 final 态 / actor 无 dict_admin /
        参数非法 / 数据库错误为 False。
    """
    vid = _as_positive_int(version_id)
    if vid is None:
        logger.error(f"publish 拒绝非法 version_id: {version_id!r}")
        return False
    if not isinstance(actor, dict):
        logger.error("publish 拒绝：actor 须为会话用户 dict（未登录写路径 fail-closed）")
        return False
    if "dict_admin" not in effective_six_roles(actor):
        logger.error(
            f"publish 回绝：actor（{actor.get('username', '?')}）有效角色集"
            "不含 dict_admin —— 出版批准仅词典管理员（架构规范 §8）"
        )
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE definition_versions SET status = %s "
                "WHERE id = %s AND status = %s",
                (STATUS_PUBLISHED, vid, STATUS_FINAL),
            )
            if cursor.rowcount <= 0:
                logger.error(f"publish 拒绝：id={vid} 不存在或非 final 态")
                return False
            return True
    except pymysql.Error as e:
        logger.error(f"publish 失败（id={vid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"publish 意外错误（id={vid}）: {e}")
        return False


# ============================================
# 查询（版本链 / 待审清单 / 意见线）
# ============================================

_VERSION_COLUMNS = (
    "id, sense_ref, version, author_id, based_on_version, style_version, "
    "content, status, ai_draft, created_at, updated_at"
)

# list_pending_reviews 联表查询的版本侧列（显式列出，带 v. 前缀防歧义）
_PENDING_VERSION_COLUMNS = (
    "v.id AS version_id, v.sense_ref, v.version, v.author_id, "
    "v.based_on_version, v.style_version, v.content, v.status, v.ai_draft"
)


def list_versions(
    sense_ref: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """版本链表（sense_ref, version 升序；ai_draft 解析回容器）。

    Args:
        sense_ref: 限定锚（None = 全库，管理员总览口径；格式非法返回 []）。
        status: 状态过滤（须 ∈ VERSION_STATUSES，非法返回 []）。
        limit: 返回上限（≤0 返回 []；超过 MAX_LIST_LIMIT 截断）。

    Returns:
        list[dict]: 版本行列表；数据库不可用返回 []。
    """
    got_limit = _as_int(limit)
    if got_limit is None or got_limit <= 0:
        return []
    got_limit = min(got_limit, MAX_LIST_LIMIT)
    ref: Optional[str] = None
    if sense_ref is not None:
        ref = sense_ref.strip() if isinstance(sense_ref, str) else ""
        if not valid_sense_ref(ref):
            return []
    if status is not None and status not in VERSION_STATUSES:
        return []
    sql = f"SELECT {_VERSION_COLUMNS} FROM definition_versions"
    where: List[str] = []
    params: List[Any] = []
    if ref is not None:
        where.append("sense_ref = %s")
        params.append(ref)
    if status is not None:
        where.append("status = %s")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY sense_ref ASC, version ASC LIMIT %s"
    params.append(got_limit)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            return [_row_to_version(row) for row in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"list_versions 查询失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"list_versions 意外错误: {e}")
        return []


def list_pending_reviews(
    reviewer_id: Optional[int] = None, limit: int = 200
) -> List[Dict[str, Any]]:
    """待审任务清单（verdict='pending'），联结版本行供审校台直读。

    Args:
        reviewer_id: 受派审校人过滤（None = 全部待审 —— 词典管理员总览 /
            协作收件箱全局视图口径；正整数 = 「待我审校」）。
        limit: 返回上限（≤0 返回 []；超过 MAX_LIST_LIMIT 截断）。

    Returns:
        list[dict]: 每行含任务字段（task_id/reviewer_id/round/verdict/note/
        task_created_at）＋版本字段（version_id/sense_ref/version/author_id/
        status/content/ai_draft/based_on_version/style_version）；按 task_id
        升序（先到先审）；数据库不可用返回 []。
    """
    got_limit = _as_int(limit)
    if got_limit is None or got_limit <= 0:
        return []
    got_limit = min(got_limit, MAX_LIST_LIMIT)
    rid = _as_positive_int(reviewer_id) if reviewer_id is not None else None
    if reviewer_id is not None and rid is None:
        return []
    sql = (
        "SELECT t.id AS task_id, t.reviewer_id, t.round, "
        "       t.verdict, t.note, t.created_at AS task_created_at, "
        f"{_PENDING_VERSION_COLUMNS} "
        "FROM review_tasks t JOIN definition_versions v ON v.id = t.version_id "
        "WHERE t.verdict = %s"
    )
    params: List[Any] = [VERDICT_PENDING]
    if rid is not None:
        sql += " AND t.reviewer_id = %s"
        params.append(rid)
    sql += " ORDER BY t.id ASC LIMIT %s"
    params.append(got_limit)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            rows = []
            for row in cursor.fetchall():
                out = dict(row)
                out["ai_draft"] = _parse_ai_draft(out.get("ai_draft"))
                rows.append(out)
            return rows
    except pymysql.Error as e:
        logger.error(f"list_pending_reviews 查询失败（MySQL）: {e}")
        return []
    except Exception as e:
        logger.error(f"list_pending_reviews 意外错误: {e}")
        return []


def get_version(version_id: int) -> Optional[Dict[str, Any]]:
    """单版本行读取（含已定稿/已发布行；ai_draft 解析回容器）。

    Returns:
        dict | None: 版本行；不存在 / 非法 id / 数据库不可用返回 None。
    """
    vid = _as_positive_int(version_id)
    if vid is None:
        return None
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {_VERSION_COLUMNS} FROM definition_versions WHERE id = %s",
                (vid,),
            )
            row = cursor.fetchone()
            return _row_to_version(row) if row else None
    except pymysql.Error as e:
        logger.error(f"get_version 查询失败（id={vid}）: {e}")
        return None
    except Exception as e:
        logger.error(f"get_version 意外错误（id={vid}）: {e}")
        return None


def get_latest_version(
    sense_ref: str,
    *,
    viewer_id: Optional[int] = None,
    allow_reviewer: bool = False,
) -> Optional[Dict[str, Any]]:
    """sense_ref 的最新版本行（version 最大者）；无任何版本返回 None。

    撰写台续写/打回重提的底稿定位入口；锚格式非法返回 None。

    **draft 态脱敏（R1-3，施工规范 §14 批次 12）**：最新行为 draft 态且查看者
    不是其作者（也未声明审校侧 ``allow_reviewer=True``）时，content 返回
    脱敏标记 ``{"content": None, "draft_hidden": True}``（其余字段照常）——
    他人在途草稿内容对非作者/非审校侧不可读；作者本人（viewer_id 与行
    author_id 一致）与审校侧不受限。viewer_id=None（未声明身份的直调）按
    「非作者」fail-closed 脱敏；非 draft 态行不受影响（rejected 版重提
    预填、定稿/发布版回看照常）。

    Args:
        sense_ref: 三段式锚。
        viewer_id: 查看者 users.id（撰写台传当前会话用户；None = 未声明身份，
            draft 内容一律脱敏）。
        allow_reviewer: 审校侧声明（审校台/总览读底稿时 True；调用点须已做
            reviewer/dict_admin 角色门 —— 本层不查角色，只承接声明）。
    """
    if not valid_sense_ref(sense_ref):
        return None
    ref = sense_ref.strip()
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                f"SELECT {_VERSION_COLUMNS} FROM definition_versions "
                "WHERE sense_ref = %s ORDER BY version DESC LIMIT 1",
                (ref,),
            )
            row = cursor.fetchone()
            out = _row_to_version(row) if row else None
            if out is not None and out.get("status") == STATUS_DRAFT:
                author = out.get("author_id")
                is_author = (
                    viewer_id is not None
                    and author is not None
                    and _as_positive_int(viewer_id) == _as_positive_int(author)
                )
                if not is_author and not allow_reviewer:
                    out["content"] = None
                    out["draft_hidden"] = True
            return out
    except pymysql.Error as e:
        logger.error(f"get_latest_version 查询失败（{ref}）: {e}")
        return None
    except Exception as e:
        logger.error(f"get_latest_version 意外错误（{ref}）: {e}")
        return None


def list_comments(version_id: int, only_open: bool = False) -> List[Dict[str, Any]]:
    """版本的审校意见线（id 升序；only_open=True 只取未处理）。

    Returns:
        list[dict]: 意见行（id/version_id/reviewer_id/body/resolved/
        created_at）；数据库不可用返回 []。
    """
    vid = _as_positive_int(version_id)
    if vid is None:
        return []
    sql = (
        "SELECT id, version_id, reviewer_id, body, resolved, created_at "
        "FROM review_comments WHERE version_id = %s"
    )
    if only_open:
        sql += " AND resolved = 0"
    sql += " ORDER BY id ASC"
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (vid,))
            return [dict(row) for row in cursor.fetchall()]
    except pymysql.Error as e:
        logger.error(f"list_comments 查询失败（id={vid}）: {e}")
        return []
    except Exception as e:
        logger.error(f"list_comments 意外错误（id={vid}）: {e}")
        return []


def resolve_comment(comment_id: int, resolved: bool = True) -> bool:
    """标记意见处理状态（收口只是标记，不删行 —— D 域不删行纪律）。

    谁可收口（作者确认修完 / 审校确认已答）由页面层判定，数据层不重复实现。

    Returns:
        bool: 标记成功为 True；意见不存在 / 参数非法 / 数据库错误为 False。
        目标状态与现值相同时 MySQL 不计为变更行，返回 False。
    """
    cid = _as_positive_int(comment_id)
    if cid is None:
        logger.error(f"resolve_comment 拒绝非法 comment_id: {comment_id!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE review_comments SET resolved = %s WHERE id = %s",
                (1 if resolved else 0, cid),
            )
            return cursor.rowcount > 0
    except pymysql.Error as e:
        logger.error(f"resolve_comment 失败（id={cid}）: {e}")
        return False
    except Exception as e:
        logger.error(f"resolve_comment 意外错误（id={cid}）: {e}")
        return False


__all__ = [
    "VERSION_STATUSES",
    "VERDICTS",
    "ADJUDICATE_DECISIONS",
    "STATUS_DRAFT",
    "STATUS_IN_REVIEW",
    "STATUS_REVIEWED",
    "STATUS_REVISED",
    "STATUS_APPROVED",
    "STATUS_FINAL",
    "STATUS_PUBLISHED",
    "STATUS_REJECTED",
    "VERDICT_PENDING",
    "VERDICT_APPROVED",
    "VERDICT_REJECTED",
    "VERDICT_REVISION_REQUESTED",
    "MAX_LIST_LIMIT",
    "MAX_SENSE_REF_LEN",
    "MAX_STYLE_VERSION_LEN",
    "MAX_CONTENT_LEN",
    "MAX_TEXT_LEN",
    "DEFINITION_VERSIONS_TABLE_SQL",
    "REVIEW_TASKS_TABLE_SQL",
    "REVIEW_COMMENTS_TABLE_SQL",
    "ensure_writing_tables",
    "valid_sense_ref",
    "create_draft",
    "update_draft",
    "submit_for_review",
    "add_comment",
    "request_revision",
    "approve",
    "adjudicate_final",
    "publish",
    "list_versions",
    "list_pending_reviews",
    "get_version",
    "get_latest_version",
    "list_comments",
    "resolve_comment",
]
