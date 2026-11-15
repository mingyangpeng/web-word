"""AI 协作区数据层 —— 任务分派 assignments 与协作区台账读面（P3 分层抽取）。

出处（review finding P3）：src/collab_pages.py 原页面层直写/直读 SQL 段整体
迁入本模块 —— 页面层持写路径（INSERT assignments 等）与 dict_admin_db /
writing_db「页面层调数据层」的分层惯例不一致；本文件把该惯例补齐到协作区。
函数体自 collab_pages 逐字搬运、逻辑零改写（只改宿主模块与封装）；页面层
collab_pages.py 留同名薄封装，对外签名与返回契约逐项不变。

是什么（一写面＋七读面；表全部归既有模块建，本层不建表不携带 DDL）：
  assignments         任务分派表（annotation_flow.ensure_flow_tables 建，DDL：
                      多人标注系统设计规范 §2）。create_assignment 是本层唯一
                      写路径（INSERT，status 固定初始态 'open'）；任务状态
                      流转（open→in_progress→submitted→closed）在「语义建模 →
                      标注任务」页经 annotation_flow 完成 —— 「我的任务」刻意
                      只读（避免双入口状态口径分裂，见 collab_pages GUIDE），
                      本层亦不提供状态流转函数。
  ai_proposals        提案台账（ai_ledger 建）——本层只有三个只读聚合
                      （收件箱 pending 计数 / 按工序分组计数 / 工序枚举），
                      裁决写路径全走 ai_ledger.decide（一次性不可改留痕）。
  definitions × oald_senses   mysql_db 建的词典主库（动词/义位只读搜索）。
  information_schema  assignments 表就绪探测（只读）。

函数清单（原宿主 src/collab_pages.py；P3 前的页面层私有名 → 本层公开名）：
  create_assignment          （同名）创建分派 INSERT —— 参数校验先行（非法
                             id / task_type / category / scope_verbs 返回 0
                             不进库），本层唯一写路径
  list_my_assignments        （同名）我的任务（status ≠ 'closed'，id 降序）
  count_open_assignments     （原 _count_open_assignments）被派人在途任务数
                             （负荷上限 _check_load_limit 的计数口径）
  assignments_table_ready    （原 _assignments_table_ready）表就绪探测
  search_verbs               （原 _search_verbs）动词/义位搜索（R2-5 LIKE
                             转义＋ESCAPE '!' 字面匹配）
  list_proposal_stages       （原 _list_proposal_stages）工序枚举
  pending_inbox_count        （同名）收件箱待办徽章计数（draft/audit pending）
  pending_stage_counts       （原 _pending_stage_counts）按工序 pending 计数
  _parse_scope_verbs         （同名纯函数随迁）scope_verbs JSON 列解析
                             （list_my_assignments 的行后处理归数据层）

页面层衔接（collab_pages.py 同名薄封装）：
  * 页面函数签名 / 返回值 / 降级行为逐项一致 —— 测试（tests/test_collab_pages
    等）与 app.py 的导入锚点不动；
  * search_verbs 额外带 keyword-only cursor_factory 注入参数（默认
    mysql_db.get_db_cursor）：collab_pages 薄封装传入其模块级 get_db_cursor，
    保住 R2-5 契约测试对页面模块游标工厂的 monkeypatch 锚点（生产路径注入的
    与本层默认是同一工厂对象，行为零差异）；
  * pending_inbox_count 的 30s 缓存（@st.cache_data）留在页面层薄封装 ——
    Streamlit 缓存是页面关注点，本层只给未缓存的真值。

降级（同 writing_db / ai_ledger 口径）：数据库不可用时写操作返回 0、读操作
返回 []/None/False，只记日志不抛异常 —— 页面可继续渲染降级提示而不是整页
崩掉（页面据此给「暂不可用 / 空态」而不是抛错）。

安全规则（同 users_db / ai_ledger 口径）：
  1. SQL 一律参数化（get_db_cursor 模式），本文件无一处把值拼进 SQL 文本
     （表名 / 枚举 / 状态值全是本模块常量或 import 的单一事实源；search_verbs
     的 ``%`` 包裹拼在**值**里，通配符经 db_utils._escape_like 转义 ——
     R2-5 单一实现复用，不复制第二份转义逻辑；第二轮 review 已把该小件
     从页面层 data_pages 下沉公共件（db_utils），本模块不再反向依赖页面层）；
  2. 入参应用层先校验再入库：非法 id / task_type / category / scope_verbs
     根本不进数据库（不依赖 ENUM / FK 报错兜底，FK 只作最后防线）；
  3. task_type 枚举 import 自 annotation_flow.TASK_TYPES（assignments DDL
     ENUM 的单一事实源，避免两处常量漂移）。
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from src.annotation_flow import TASK_TYPES as ASSIGNMENT_TASK_TYPES
# R2-5：LIKE 转义单一实现点 —— 第二轮 review 已自页面层 data_pages 下沉
# src/db_utils，数据层不再反向 import 页面模块（分层修复；data_pages 是
# 同一实现的 re-export，`is` 同源断言两边都成立）。
from src.db_utils import _escape_like
from src.mysql_db import get_db_cursor

logger = logging.getLogger(__name__)


def _parse_scope_verbs(raw: Any) -> Optional[List[str]]:
    """assignments.scope_verbs JSON 列 → 动词清单（纯函数，脏数据容错）。

    None → None（DDL 语义：NULL = 全部动词）；JSON 串/list → str 清单；
    解析失败/结构不对 → None（按未限范围渲染，不打崩「我的任务」）。

    （自 collab_pages._parse_scope_verbs 原样随迁 —— P3 分层抽取，行后处理
    归数据层；页面层同名保留为别名，测试导入锚点不变。）
    """
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    return None


def assignments_table_ready() -> bool:
    """assignments 表是否已建（annotation_flow.ensure_flow_tables 的产物）。

    只读探测（information_schema，表名是本模块常量非用户输入）。表缺失是合法
    状态（任务分派未启用），页面据此给修复指引而不是抛错 —— 与 org_db
    「查 assignments 占位，MVP 放行」同口径。

    （自 collab_pages._assignments_table_ready 原样迁入 —— P3 分层抽取，
    页面层同名薄封装委托本函数。）
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assignments'"
            )
            row = cursor.fetchone()
            return bool(row) and int(row["n"] or 0) > 0
    except Exception as e:  # noqa: BLE001 —— 库不可用按表未就绪渲染
        logger.error(f"探测 assignments 表就绪失败: {e}")
        return False


def list_my_assignments(assignee_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """当前用户的在途任务（assignments，status ≠ 'closed'；参数化只读）。

    「我的任务」段数据源：**只读展示** —— 任务的标注与提交动作在
    「语义建模 → 标注任务」页完成，本查询刻意不提供提交入口（避免双入口造成
    状态口径分裂，见 GUIDE notes）。

    Args:
        assignee_id: 当前登录用户 users.id
        limit: 返回条数上限（≤0 返回 []；防一次性拖全表）

    Returns:
        list[dict]: {id, category, task_type, scope_verbs(None=全部动词 或
        list[str]), status, assigned_by, created_at}，按 id 降序（最新分派在前）；
        参数非法 / 表未建 / 数据库不可用返回 []。

    （自 collab_pages.list_my_assignments 原样迁入 —— P3 分层抽取，页面层
    同名薄封装委托本函数。）
    """
    try:
        uid = int(assignee_id)
        lim = int(limit)
    except (TypeError, ValueError):
        return []
    if uid <= 0 or lim <= 0:
        return []
    sql = (
        "SELECT id, category, task_type, scope_verbs, status, assigned_by, created_at "
        "FROM assignments WHERE assignee_id = %s AND status <> 'closed' "
        "ORDER BY id DESC LIMIT %s"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (uid, lim))
            rows = cursor.fetchall()
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按空列表降级渲染
        logger.error(f"查询用户 {uid} 的在途任务失败: {e}")
        return []
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["scope_verbs"] = _parse_scope_verbs(item.get("scope_verbs"))
        result.append(item)
    return result


def count_open_assignments(assignee_id: int) -> Optional[int]:
    """被派人的在途任务数（assignments status ∈ open/in_progress；只读）。

    负荷上限校验（collab_pages._check_load_limit）的计数口径。表未建 / 参数
    非法 / 库不可用返回 None（按「未知」处理）—— 体检性校验不阻断页面，真正
    建分派时 create_assignment 的失败路径会给出明确报错。

    （自 collab_pages._count_open_assignments 原样迁入 —— P3 分层抽取，
    页面层同名薄封装委托本函数。）
    """
    try:
        uid = int(assignee_id)
    except (TypeError, ValueError):
        return None
    if uid <= 0:
        return None
    sql = (
        "SELECT COUNT(*) AS n FROM assignments "
        "WHERE assignee_id = %s AND status IN ('open', 'in_progress')"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (uid,))
            row = cursor.fetchone()
            return int(row["n"] or 0) if row else 0
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按未知处理
        logger.error(f"统计在途任务数失败（assignee={uid}）: {e}")
        return None


def create_assignment(
    assignee_id: int,
    task_type: str,
    scope_verbs: Optional[List[str]] = None,
    assigned_by: int = 0,
    category: str = "motion",
) -> int:
    """创建任务分派（INSERT assignments；本层唯一写路径，docstring 注明）。

    assignments 表由 annotation_flow.ensure_flow_tables() 建（DDL：多人标注
    系统设计规范 §2）。本函数不建表；任务×角色矩阵 / 负荷上限 / 回避制三重
    校验在页面调用前完成（collab_pages._render_assign_tab 用
    _check_role_matrix / _check_load_limit / _check_recusal 接线）—— 本函数
    保持薄 INSERT 不重复校验，数据层直调（脚本/测试）仍走参数与 FK 兜底。

    Args:
        assignee_id: 标注员 users.id
        task_type: 任务类型 ∈ ASSIGNMENT_TASK_TYPES（import 自 annotation_flow，
        与 assignments DDL ENUM 一致）
        scope_verbs: 范围动词清单（list/tuple，元素去空白后须非空）；
        None = 全部动词（DDL 语义：scope_verbs NULL）
        assigned_by: 分派人 users.id（词典管理员，= 页面当前登录用户）
        category: 范畴（DDL 默认 'motion'；批次 3 簇为粒度分派时按所选动词
        所在簇推导，页面不暴露该参数）

    Returns:
        int: 新任务 id；参数非法（含 scope_verbs 传了空清单 —— 意图不明，
        页面层「一个不选」已归一为 None）/ 表未建 / 数据库错误返回 0。

    （自 collab_pages.create_assignment 原样迁入 —— P3 分层抽取，页面层
    同名薄封装委托本函数，签名与返回契约不变。）
    """
    try:
        assignee = int(assignee_id)
        granter = int(assigned_by)
    except (TypeError, ValueError):
        logger.error(f"create_assignment 拒绝非法 id: assignee_id={assignee_id!r}, "
                     f"assigned_by={assigned_by!r}")
        return 0
    if assignee <= 0 or granter <= 0:
        logger.error(f"create_assignment 拒绝非正 id: assignee={assignee}, "
                     f"assigned_by={granter}")
        return 0
    if task_type not in ASSIGNMENT_TASK_TYPES:
        logger.error(f"create_assignment 拒绝非法 task_type: {task_type!r}")
        return 0
    if not isinstance(category, str) or not category.strip() or len(category) > 40:
        logger.error(f"create_assignment 拒绝非法 category: {category!r}")
        return 0
    scope_json: Optional[str] = None
    if scope_verbs is not None:
        if not isinstance(scope_verbs, (list, tuple)):
            logger.error(f"create_assignment 拒绝非法 scope_verbs: {scope_verbs!r}")
            return 0
        cleaned = [str(v).strip() for v in scope_verbs if str(v).strip()]
        if not cleaned:
            logger.error("create_assignment 拒绝空 scope_verbs 清单"
                         "（不限动词请传 None，DDL 语义 NULL=全部动词）")
            return 0
        try:
            scope_json = json.dumps(cleaned, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error(f"create_assignment 序列化 scope_verbs 失败: {e}")
            return 0
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO assignments (assignee_id, category, task_type, "
                "scope_verbs, status, assigned_by) "
                "VALUES (%s, %s, %s, %s, 'open', %s)",
                (assignee, category.strip(), task_type, scope_json, granter),
            )
            return int(cursor.lastrowid)
    except Exception as e:  # noqa: BLE001 —— FK 无此人/表缺失/库不可用按失败
        logger.error(f"创建任务分派失败（assignee={assignee}, task_type={task_type}）: {e}")
        return 0


def search_verbs(
    keyword: str,
    limit: int = 20,
    *,
    cursor_factory: Optional[Callable[[], Any]] = None,
) -> List[Dict[str, Any]]:
    """动词/义位搜索（definitions × oald_senses 参数化只读查询）。

    词目（definitions.verb）或 OALD 义项词目（oald_senses.headword）LIKE 匹配：
    关键词走占位符，包裹用的 ``%`` 由本函数拼在**值**里（``%kw%``）；R2-5 起
    关键词先经 db_utils._escape_like 转义（``!``/``%``/``_``，SQL 侧
    ``ESCAPE '!'`` 与 db_utils.LIKE_ESCAPE 同源同口径）—— 通配符按字面
    处理：搜 ``100%`` 匹配字面「100%」而不是「100」开头的任意串（与
    data_pages 词条搜索口径一致，无 SQL 文本拼接）。

    Args:
        keyword: 搜索关键词（去空白后为空返回 []；通配符按字面处理）
        limit: 返回条数上限（去重到动词，按词目排序）
        cursor_factory: 游标工厂注入（keyword-only，默认 mysql_db.get_db_cursor）。
        兼容锚点：collab_pages 薄封装传入其模块级 get_db_cursor，保住 R2-5
        契约测试对页面模块游标工厂的 monkeypatch（tests/test_collab_pages.py
        test_search_verbs_escapes_wildcards_and_sets_escape_clause）；生产路径
        注入的与本层默认是同一工厂对象，行为零差异。

    Returns:
        list[dict]: {verb, sense_count, cluster_id, oald_senses（OALD 义项数）}；
        两表由 mysql_db.init_database 建，库不可用/无命中返回 []。

    （自 collab_pages._search_verbs 原样迁入 —— P3 分层抽取，除游标工厂改为
    可注入外逻辑逐字保留。）
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    try:
        lim = max(1, int(limit))
    except (TypeError, ValueError):
        return []
    like = f"%{_escape_like(kw)}%"  # 值，不进 SQL 文本；通配符按字面处理
    sql = (
        "SELECT d.verb AS verb, d.sense_count AS sense_count, "
        "d.cluster_id AS cluster_id, COUNT(os.id) AS oald_senses "
        "FROM definitions d "
        "JOIN oald_senses os ON os.definition_id = d.id "
        "WHERE d.verb LIKE %s ESCAPE '!' OR os.headword LIKE %s ESCAPE '!' "
        "GROUP BY d.id, d.verb, d.sense_count, d.cluster_id "
        "ORDER BY d.verb LIMIT %s"
    )
    open_cursor = cursor_factory or get_db_cursor
    try:
        with open_cursor() as cursor:
            cursor.execute(sql, (like, like, lim))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 —— 表缺失/库不可用按无命中降级
        logger.error(f"动词搜索失败（keyword 长度 {len(kw)}）: {e}")
        return []


def list_proposal_stages() -> Optional[List[str]]:
    """台账出现过的全部工序（stage）清单（参数化只读）。

    协同度量按工序下钻需要工序枚举；ai_proposals 的 stage 无独立维表，
    直接 SELECT DISTINCT（SQL 文本为常量，无用户输入参与）。

    两态（RV 第二轮 R4 口径）：空台账返回 []（页面 info「暂无记录」）；
    查询失败（库不可用等）返回 None（页面 warning「勿重跑灌库」）——
    原失败也折 [] 的口径让页面无法区分「等恢复」与「真没数据」，拆开
    归因（真库空表行为不变，tests/test_collab_pages 的 [] 断言不受影响）。

    （自 collab_pages._list_proposal_stages 原样迁入 —— P3 分层抽取，
    页面层同名薄封装委托本函数。）
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT DISTINCT stage FROM ai_proposals ORDER BY stage")
            rows = cursor.fetchall()
            return [str(r["stage"]) for r in rows if r.get("stage")]
    except Exception as e:  # noqa: BLE001
        logger.error(f"枚举提案工序失败: {e}")
        return None


def pending_inbox_count() -> int:
    """收件箱待办计数：pending 的 draft/audit 提议数（probe 不计）。

    供 collab_pages 侧边栏待办徽章薄封装（30s 缓存在页面层）：库不可用/
    表未建返回 0（徽章自然隐藏），异常不外抛——侧边栏计数失败不该影响
    页面主流程。

    （自 collab_pages.pending_inbox_count 原样迁入 —— P3 分层抽取，仅剥离
    页面层 @st.cache_data（缓存归页面薄封装，本层给未缓存真值）。）
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM ai_proposals "
                "WHERE status = 'pending' AND kind IN ('draft', 'audit')"
            )
            row = cursor.fetchone()
            return int(row["n"] or 0) if row else 0
    except Exception as e:  # noqa: BLE001 —— 计数失败降级为 0（R6-10 补留痕）
        logger.warning(f"pending_inbox_count 侧边栏待办计数失败（按 0 降级）: {e}")
        return 0


def pending_stage_counts() -> List[Any]:
    """按 stage 分组的 pending 计数（待我裁决类目；参数化只读）。

    Returns:
        list[(stage, n)]: 按待决数降序；库不可用/无 pending 返回 []。

    （自 collab_pages._pending_stage_counts 原样迁入 —— P3 分层抽取，
    页面层同名薄封装委托本函数。）
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT stage, COUNT(*) AS n FROM ai_proposals "
                "WHERE status = 'pending' GROUP BY stage ORDER BY n DESC"
            )
            return [(str(r["stage"]), int(r["n"] or 0)) for r in cursor.fetchall()]
    except Exception as e:  # noqa: BLE001 —— R6-10：吞错补留痕
        logger.warning(f"pending_stage_counts 按工序分组计数失败（按空降级）: {e}")
        return []
