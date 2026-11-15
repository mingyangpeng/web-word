"""跨模块公共小件收敛点（R6-4）—— _as_int/_current_user/_column_exists/_table_exists
＋ LIKE 转义小件（_escape_like/LIKE_ESCAPE，第二轮 review 自 data_pages 下沉）。

背景（R6 代码质量巡检）：同一语义的四个小件曾在 8+ 个模块各复制一份
（同名同义，行为逐字节一致），漂移风险随份数增长。本模块把它们收敛为
**单一实现点**，各模块改 ``from src.db_utils import as_int as _as_int``
式别名导入 —— 调用点零改动（模块内名字不变，测试 monkeypatch 模块属性
依旧生效），实现只剩这一份。

下沉件（第二轮 review P2 分层修复）：``_escape_like``（含 ``LIKE_ESCAPE``
常量）原是页面层 data_pages 的私有件，数据层 collab_db 反向 import 页面
模块才拿到转义 —— 分层违例，且 collab_db 被连带拖进 streamlit/pandas
UI 依赖链。现按本模块「零内部依赖公共小件收敛点」定位下沉：data_pages
保留同名 re-export（测试锚点 ``from src.data_pages import _escape_like``
的 ``is`` 同源断言与转义行为断言不动），collab_db 直接 import 本模块。

五个小件的语义（与既有各副本逐字节一致，收敛不改行为）：

  as_int(value)         宽松转 int：int/int-str/float 整数可转；
                        bool/None/其余 → None（bool 是 int 子类，须先拦）。
  current_user()        当前会话用户：st.session_state["user"] 且为 dict
                        才返回，否则 None（fail-closed；页面层纵深防御
                        的第一层判定）。
  column_exists(cursor, table, column)
                        当前库某表是否已有该列（information_schema 探测，
                        让 ALTER 幂等；schema 取 DATABASE() —— 连接所
                        在库，与 users_db/media_db 副本同口径）。
  table_exists(cursor, table)
                        当前库是否存在该表（information_schema 探测，
                        rollback_batch 动态表名闸门等用）。
  _escape_like(value)   LIKE 通配符转义（纯函数；'!' 先转义再转 % _，
                        与 SQL 侧 ``ESCAPE '!'`` 配套，防通配符注入）。
                        下划线名保留为历史口径 —— R2-5 起 data_pages 与
                        collab_db 的测试锚点都按这个名字寻址。

边界（刻意不收进来的同名不同义件，R6-4 已就地改名消歧）：
  * dict_admin_db._dump_json_strict（原 _dump_json）—— JSON 序列化非
    DB 小件，且与 writing_db._dump_json 同名不同义，改名后各归各家；
  * collab_pages._can_adjudicate_inbox（原 _can_adjudicate）—— 收件箱
    裁决权语义，与 writing_pages._can_adjudicate（词典管理员终裁）同名
    不同义；
  * writing_pages._list_categories_dicts（原 _list_categories）—— 返回
    dict 清单，与 reliability._list_categories（返回 code 元组）同名
    不同义；
  * sense_spine._fetch_submissions_for_spine（原 _fetch_submissions）——
    义位脊柱专用取数，与 reliability._fetch_submissions（范畴×任务级）
    同名不同义。

降级与依赖：
  本模块零 src 内部依赖、不查库不建表（column_exists/table_exists 只用
  调用方传入的 cursor）；streamlit 延迟到 current_user 函数体内导入 ——
  纯数据层模块（annotation_flow 等）import 本模块不引入 UI 依赖。

安全规则：
  column_exists / table_exists 的表名/列名只进占位符值（information_schema
  的标识符不能用 %s 占位的是本查询的 WHERE 值位置 —— TABLE_NAME/COLUMN_NAME
  都是列值比较，参数化安全）；调用方传入的表名列名应是代码常量，不收
  用户输入原文。
"""

from typing import Any, Dict, Optional

__all__ = ["as_int", "current_user", "column_exists", "table_exists"]


def as_int(value: Any) -> Optional[int]:
    """宽松转 int（bool/None/非整值返回 None；入参清洗统一口径）。

    bool 是 int 子类（True == 1），必须先拦 —— 否则 ``as_int(True)``
    会把布尔当 id 用。int / 整数值 float / 整数串可转；其余返回 None。
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def current_user() -> Optional[Dict[str, Any]]:
    """当前会话用户（规范 §6-5：会话只存 st.session_state['user']）。

    user 缺键 / 非 dict（脏值）→ None（fail-closed）。streamlit 在函数
    体内导入：本模块被纯数据层 import 时不拖 UI 依赖。
    """
    import streamlit as st

    user = st.session_state.get("user")
    return user if isinstance(user, dict) else None


def column_exists(cursor, table: str, column: str) -> bool:
    """当前库某表是否已有该列（让 ALTER 幂等；仿 users_db 副本口径）。

    Args:
        cursor: 已连接的 DB-API cursor（DictCursor，取行键 "n"）
        table: 表名（调用方常量）
        column: 列名（调用方常量）

    Returns:
        bool: information_schema.COLUMNS 命中 True，否则 False。
    """
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
             AND COLUMN_NAME = %s""",
        (table, column),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


def table_exists(cursor, table: str) -> bool:
    """当前库是否存在该表（information_schema 探测；仿 dict_admin_db 副本口径）。

    Args:
        cursor: 已连接的 DB-API cursor（DictCursor，取行键 "n"）
        table: 表名（调用方常量；rollback_batch 动态表名的白名单校验
        之外仍以代码常量为前提，不收用户输入原文）

    Returns:
        bool: information_schema.TABLES 命中 True，否则 False。
    """
    cursor.execute(
        """SELECT COUNT(*) AS n FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
        (table,),
    )
    return int(cursor.fetchone()["n"] or 0) > 0


# ============================================
# LIKE 转义小件（R2-5 单一实现点；第二轮 review 自 data_pages 下沉）
# ============================================

# LIKE 转义字符（SQL 侧 ESCAPE '!'，避开 MySQL 反斜杠双重转义的坑）。
LIKE_ESCAPE = "!"


def _escape_like(value: Any) -> str:
    """转义 LIKE 通配符与本模块的转义字符（纯函数，防通配符注入）。

    与 SQL 侧 ``LIKE %s ESCAPE '!'`` 配套：'!' 是转义字符必须先转义，然后
    % 与 _ 转为字面字符；反斜杠在显式 ESCAPE 下无特殊含义，不处理。
    非 str 入参（None/数字等）返回空串 —— 调用方按「空搜索词」处理。

    分层（第二轮 review）：实现自页面层 data_pages 原样下沉 —— 行为逐字节
    一致（tests/test_data_pages.py 的转义行为断言与 tests/test_review_
    regression.py R2-5 的 ``is`` 同源断言继续成立）；data_pages 保留同名
    re-export、collab_db 直接 import 本模块，数据层不再反向依赖页面层。
    """
    if not isinstance(value, str):
        return ""
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE + LIKE_ESCAPE)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


# ─── LLM 供应商表 DDL（批次 46：单一事实源自 llm_providers_db 下沉至此——
# mysql_db 的 CREATE_TABLES_SQL 建表链与本模块同挂零依赖公共件，避免数据层
# 互 import；llm_providers_db 经本处引用保持契约不变）
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
