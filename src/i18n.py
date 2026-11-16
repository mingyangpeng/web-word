"""平台中英双语基建 —— 原文即 key 的渐进式 i18n 层（轻量实现）。

设计口径（渐进式方案，三句话版）：
  1. **原文即 key**：字典 ZH_EN 以「中文原文 → 英文译文」为键值对，页面
     文案不需要抽 key 改造 —— 未收录的文案在英文态显示中文原文，
     **未翻译不崩**（渐进式核心：翻译覆盖可以一页一页长出来）；
  2. **语言状态三级回退**：会话（st.session_state["ui_lang"]）→
     持久化偏好（user_context_db.get_profile("ui.lang")）→ 默认 "zh"。
     照 app.py 语料页 _rows_per_page_pref（ui.rows_per_page）的消费先例
     形态：user_context_db 函数内导入、try/except 全包裹 —— 未登录 /
     断库 / import 错误一律静默降级回上一级，绝不打崩页面；
  3. **消费面极窄**：页面只需两个函数 —— ``t("中文原文")`` 取当前语言
     文案、``set_lang("en")`` 切语言（写会话 + 登录态时持久化），
     ``is_en()`` 供个别分支逻辑（如只对英文态追加提示）使用。

字典范围（框架层，约 79 条）：17 页侧边栏 label（与 src/page_guides.py
PAGE_GUIDES 的 label 逐字一致，emoji 保留）、3 条页 H1 主标题（与
label 不同串的页面主标题，页头 i18n 接线补收）、七区头（与 src/app.py
_SIDEBAR_ZONES 区名逐字一致；与页 label 同串的三条共用同一条目）、
登录/通用动词、通用名词与界面动词、使用说明段头与侧栏常驻文案、
R4 高频降级/状态提示（grep src/ 收录的高频原文）。页面级长文案不进本
字典 —— 各页按需在调用点用 ``t(zh, en)`` 的显式 en 参数就地给译文，
或经并行会话逐步沉淀进 ZH_EN。

与任务口径的两处落地差异（如实注明）：
  * 持久化写接口用的是 ``user_context_db.upsert_profile``（键值 upsert、
    幂等）——user_context_db 没有名为 set_profile 的函数，upsert_profile
    即其「set 语义」的正式 API（同键覆盖，重复写也是成功）；
  * 登录态判定走 ``db_utils.current_user`` 的同一口径（会话 user 为
    dict 即登录），未登录时根本不触库 —— 与 user_context_db 内部
    fail-closed（读 None / 写 False）双保险。

本模块不 import src.page_guides / src.app（框架层保持零重依赖）：
label / 区名的逐字一致性由 tests/test_i18n.py 用「import 真模块对照」
的哨兵测试锁死，漂移会被测试拦下。
"""

from typing import Dict, Optional, Tuple

import streamlit as st

# ============================================
# 语言常量（会话键 / 偏好键 / 支持集）
# ============================================

# 支持的语言集合（set_lang 白名单；get_lang 校验脏值用它）
SUPPORTED_LANGS: Tuple[str, ...] = ("zh", "en")

# 默认语言：平台以中文为母语工作面，任何一级都取不到语言时回 zh
DEFAULT_LANG = "zh"

# 一级：会话键（set_lang 即写它；rerun 间存活，关浏览器即失）
LANG_SESSION_KEY = "ui_lang"

# 二级：持久化偏好键（user_profiles 表，键名约定 'ui.*' 即界面设置，
# 与 app.py 消费先例 ui.rows_per_page 同命名空间）
LANG_PREF_KEY = "ui.lang"


# ============================================
# 语言状态：get / set / 判定（三级回退，fail-closed）
# ============================================

def get_lang() -> str:
    """当前界面语言（'zh' | 'en'；恒返回合法值，绝不抛错）。

    三级回退（上一级取不到或取到脏值才落下一级）：
      1. 会话 st.session_state[LANG_SESSION_KEY] —— 本轮已显式切换的语言；
      2. 持久化偏好 user_context_db.get_profile(LANG_PREF_KEY) —— 登录用户
         跨设备/跨会话续接的偏好（键在值空 / 未登录 / 断库 / 键非法 →
         None，user_context_db fail-closed 口径）；
      3. 默认 DEFAULT_LANG="zh"。

    脏值防御：两级读到的值都必须 ∈ SUPPORTED_LANGS 才采信（手改会话/
    手改库写入 "fr" 等非法值 → 一律视同无值，不猜态）。user_context_db
    函数内导入照 app.py _rows_per_page_pref 先例（功能件非启动依赖，
    import 失败按无偏好降级），try/except 全包裹 —— 本函数在任何环境
    （无 DB、无 Streamlit 运行时、离线单测）都可安全调用。
    """
    # 一级：会话（bare 模式/异常路径下 session 不可用 → 视同无值）
    # AppTest 兼容（review P1）：SafeSessionState 不支持 .get()（AttributeError
    # 会被 except 吞掉导致 en 态永远读不到——tests/helpers._pget 注释早有记录）
    # ——改用 in + [key] 形态（真实浏览器与 AppTest 双兼容）
    try:
        lang = st.session_state[LANG_SESSION_KEY]
    except KeyError:  # 键未设（正常路径——未切换过语言）
        lang = None
    except Exception:  # noqa: BLE001 —— SafeSessionState/bare 模式异常按无值降级
        lang = None
    if lang in SUPPORTED_LANGS:
        return lang

    # 二级：持久化偏好（函数内导入照 _rows_per_page_pref 先例）
    try:
        from src import user_context_db

        row = user_context_db.get_profile(LANG_PREF_KEY)
    except Exception as e:  # noqa: BLE001 —— 未登录/断库/import 错误 → 降级
        # 与 app.py 消费先例同款静默口径：debug 级留痕即可
        import logging

        logging.getLogger(__name__).debug(f"读取 ui.lang 偏好失败（按默认语言降级）: {e}")
        row = None
    val = row.get("pref_value") if isinstance(row, dict) else None
    if val in SUPPORTED_LANGS:
        # 写回会话缓存（review 优化：偏好极少变——命中后本会话零触库；
        # 用户切语言走 set_lang 显式更新，粘滞无影响）
        try:
            st.session_state[LANG_SESSION_KEY] = val
        except Exception:  # noqa: BLE001 —— bare 模式缓存失败不影响返回
            pass
        return val

    # 三级：默认中文
    return DEFAULT_LANG


def set_lang(lang: str) -> bool:
    """切换界面语言：先写会话（必成），登录态再持久化（尽力而为）。

    返回 True=语言已接受并写入会话；False=lang 非法（不在
    SUPPORTED_LANGS 白名单），会话与偏好都不动（调用方可据此提示）。

    持久化路径：仅登录态（db_utils.current_user 同口径：会话 user 为
    dict）才写 user_context_db.upsert_profile("ui.lang", lang)——
    未登录只写会话（无主人可归，user_context_db 本身也 fail-closed
    拒写），断库/import 失败 try/except 静默吞掉（本会话切换照常生效，
    下次登录后重新切一次即可，绝不打崩页面）。写偏好用 upsert_profile
    （同键覆盖幂等；user_context_db 无 set_profile，见模块 docstring）。
    """
    # 合法性校验（先拒非法值：不写会话不触库）
    if not isinstance(lang, str) or lang not in SUPPORTED_LANGS:
        return False

    # 一级：写会话（本轮 rerun 立即生效）
    try:
        st.session_state[LANG_SESSION_KEY] = lang
    except Exception:  # noqa: BLE001 —— 无运行时上下文等极端路径不崩
        pass

    # 二级：登录态持久化（尽力而为，失败只影响跨会话续接）
    try:
        from src.db_utils import current_user

        if current_user() is None:
            return True  # 未登录：只写会话即达成本次切换
        from src import user_context_db

        user_context_db.upsert_profile(LANG_PREF_KEY, lang)
    except Exception as e:  # noqa: BLE001 —— 断库/import 错误 → 只写会话不崩
        import logging

        logging.getLogger(__name__).debug(f"持久化 ui.lang 偏好失败（仅本会话生效）: {e}")
    return True


def is_en() -> bool:
    """当前是否英文界面（个别分支逻辑用，如英文态追加语言覆盖提示）。"""
    return get_lang() == "en"


def t(zh: str, en: Optional[str] = None) -> str:
    """取当前语言的文案（渐进式核心入口；未翻译不崩）。

    Args:
        zh: 中文原文（即字典 key；zh 态原样返回）。
        en: 显式英文译文（可选）。**优先级最高** —— 页面对某条文案有
            更贴切的译法时就地传入，无需先沉淀进 ZH_EN。

    行为：
      * zh 态：无条件原样返回 zh（显式 en 参数也不生效 —— 语言态唯一
        决定输出，保证同一页面两态所见即所得）；
      * en 态：先看显式 en 参数（给了就用），再查 ZH_EN 字典，
        未收录返回 zh 原文（未翻译的页面文案显示中文 —— 渐进式：
        翻译覆盖按页生长，缺一条只是「这条显示中文」，不缺胳膊少腿）。
    """
    if not is_en():
        return zh
    if en is not None:
        return en
    return ZH_EN.get(zh, zh)


# ============================================
# ZH_EN 字典：中文原文 → 英文译文（框架层，79 条）
# ============================================

# 收录纪律：
#   * key 必须与页面真实渲染的中文文案逐字一致（含 emoji 与标点）——
#     17 页 label 与七区头的逐字性由 tests/test_i18n.py 对照
#     src/page_guides.PAGE_GUIDES / src/app.py _SIDEBAR_ZONES 锁死；
#   * 同串同译：与页 label 完全同串的三条区名（📊 语义分析 / 🤖 AI 协作 /
#     📖 词典管理）不重复收，共用同一条目；
#   * 「🤖 模型供应商」刻意译作 "🤖 Model Providers"，与 ai_hub 的
#     "🤖 AI Hub" 区分（两个入口都带 🤖，撞名会让用户分不清）；
#   * 页面级长文案不进本字典（框架层只收通用词与高频提示）—— 各页
#     文案在调用点用 t(zh, en) 显式参数就地给译文，或后续批次沉淀；
#     例外：各页 H1 主标题（与 label 不同串的）随页头 i18n 接线收编，
#     保证 en 态页标题不再是中文（双语 review finding）。
ZH_EN: Dict[str, str] = {
    # —— 17 页侧边栏 label（与 src/page_guides.py PAGE_GUIDES 逐字一致）——
    "🔍 搜索释义": "🔍 Search Definitions",
    "🕸️ 知识图谱": "🕸️ Knowledge Graph",
    "📊 语料数据集": "📊 Corpus Dataset",
    "🧭 域系初判": "🧭 Domain-Family Screening",
    "🏷️ 标注平台": "🏷️ Annotation Platform",
    "📥 标注提交": "📥 Annotation Submission",
    "👥 账号管理": "👥 Account Management",
    "📐 信度报告": "📐 Reliability Report",
    "📊 语义分析": "📊 Semantic Analysis",
    "🧩 释义模板": "🧩 Definition Templates",
    "💬 以句搜义": "💬 Search by Sentence",
    "❓ 帮助中心": "❓ Help Center",
    "📖 词典管理": "📖 Dictionary Admin",
    "🤖 AI 协作": "🤖 AI Hub",
    "✍️ 释义撰写与审校": "✍️ Drafting & Review",
    "📖 例证与对译": "📖 Examples & Translation",
    # 与「🤖 AI 协作」的译文刻意区分（同为 🤖 前缀的两个入口不能撞名）
    "🤖 模型供应商": "🤖 Model Providers",

    # —— 页 H1 主标题（与侧边栏 label 不同串的页面主标题；双语 review
    #    finding「en 态页 H1 仍中文」接线补收 —— 各 *_pages.py 页面入口的
    #    `<h1 style='{HEADER_H1}'>` 内文案用 _t 取此处译文）——
    "🧰 数据导入向导": "🧰 Data Import Wizard",
    "📖 词条浏览器": "📖 Entry Browser",
    "👥 用户管理": "👥 User Management",

    # —— 七区头（与 src/app.py _SIDEBAR_ZONES 区名逐字一致；与页 label
    #    同串的「📊 语义分析」「🤖 AI 协作」「📖 词典管理」共用上段条目）——
    "🔍 查阅展示": "🔍 Browse",
    "🏷️ 语义建模": "🏷️ Semantic Modeling",
    "✍️ 编纂产出": "✍️ Authoring",
    "🔧 系统管理": "🔧 System Admin",

    # —— 登录与通用动词（任务指定的 11 条基础动词）——
    "登录": "Sign in",
    "退出登录": "Sign out",
    "🚪 退出登录": "🚪 Sign out",
    "🔐 登录": "🔐 Sign in",
    "用户名": "Username",
    "密码": "Password",
    "保存": "Save",
    "提交": "Submit",
    "取消": "Cancel",
    "删除": "Delete",
    "确认": "Confirm",
    "导出": "Export",
    "恢复": "Restore",

    # —— 通用名词/界面动词（grep src/ 高频原文）——
    "搜索": "Search",
    "下载": "Download",
    "上传": "Upload",
    "关闭": "Close",
    "刷新": "Refresh",
    "编辑": "Edit",
    "全选": "Select all",
    "全部": "All",
    "筛选": "Filter",
    "排序": "Sort",
    "状态": "Status",
    "操作": "Actions",
    "详情": "Details",
    "备注": "Note",
    "反馈": "Feedback",
    "评分": "Rating",
    "帮助": "Help",
    "设置": "Settings",
    "语言": "Language",
    "中文": "Chinese",
    "英文": "English",
    "重试": "Retry",
    "展开": "Expand",
    "收起": "Collapse",

    # —— 使用说明段头与侧栏常驻文案（src/page_guides.py / src/app.py 原文）——
    "📖 使用说明": "📖 Usage Guide",
    "📤 提交反馈": "📤 Submit Feedback",
    "📥 数据导出": "📥 Data Export",
    "🔥 热门查询动词": "🔥 Hot Verbs",
    "📚 示例库": "📚 Example Library",
    "原理": "Principles",
    "数据来源": "Data Sources",
    "怎么用": "How to Use",
    "注意事项": "Notes",

    # —— R4 高频降级/状态提示（grep src/ 收录的高频原文，含句读形态）——
    "请先登录。": "Please sign in first.",
    "请先登录": "Please sign in first.",
    "数据库不可用": "Database unavailable.",
    "保存失败": "Save failed.",
    "保存成功": "Saved successfully.",
    "提交成功": "Submitted successfully.",
    "删除成功": "Deleted successfully.",
    "加载失败": "Failed to load.",
    "暂无数据": "No data.",
    # —— 批次 61：全仓可见面批量 _t 包裹的文案（266 条系统消息/按钮/段头）——
    "### 🌐 图式谱系（图式范畴化·事件类型层级）": "### 🌐 Schema Genealogy (schema categorisation · event-type hierarchy)",
    "##### 与词典原文并排对照（§6.4）": "##### Side by side with dictionary originals (§6.4)",
    "##### 人工修订（编者定稿层）": "##### Manual revision (editor finalisation layer)",
    "##### 可变槽位（簇内分歧 / 低频要素）": "##### Variable slots (in-cluster divergence / low-frequency features)",
    "##### 同簇并排总览（范畴化释义对照）": "##### Same-cluster side-by-side overview (categorised definition comparison)",
    "##### 实例化模板（四维结构）": "##### Instantiated template (four dimensions)",
    "##### 批量导出（当前簇全部义位）": "##### Batch export (all senses in the current cluster)",
    "##### 核心要素（簇共享，均值 ≥ 0.5）": "##### Core elements (cluster-shared, mean ≥ 0.5)",
    "**LexiSchema 模板化释义**": "**LexiSchema templated definition**",
    "**① 图式维度**": "**① Schema dimension**",
    "**② 语义参数维度**": "**② Semantic-parameter dimension**",
    "**③ 句法维度**": "**③ Syntax dimension**",
    "**④ 对齐预留维度**": "**④ Alignment (reserved) dimension**",
    "**人工修订版（现行）**": "**Manually revised (current)**",
    "**修订文本**（预填现行文本：引擎基线或最新修订）": "**Revised text** (pre-filled with the current text: engine baseline or latest revision)",
    "<h3 style='color: #2d3748; font-weight: 600; margin: 0 0 16px 0;'>📚 示例库</h3>": "<h3 style='color: #2d3748; font-weight: 600; margin: 0 0 16px 0;'>📚 Example Library</h3>",
    "available 位仅平台管理员可操作（当前账号无 sys_admin 角色）。": "The enabled flag is platform-admin only (this account has no sys_admin role).",
    "configs/ 下暂无范畴包（含 pack.yaml 的目录）。": "No category packs under configs/ (directories containing pack.yaml).",
    "enabled 位仅词典管理员可操作（当前账号无 dict_admin 角色）。": "The enabled flag is dictionary-admin only (this account has no dict_admin role).",
    "enum 字段需要至少 1 个枚举值（逗号分隔白名单）。": "An enum field needs at least 1 value (comma-separated whitelist).",
    "schema_core 原始均值": "schema_core raw mean",
    "sense_division 工序暂无待决提议（台账为空或 AI 台账不可用）。": "No pending proposals for the sense-division step (ledger empty or AI ledger unavailable).",
    "↑ 文件 sha256 指纹（写入 import_batches.file_sha256，幂等/对账凭据）": "↑ File sha256 fingerprint (written to import_batches.file_sha256 — the idempotency/reconciliation credential)",
    "≥2 次质检后显示趋势": "Trend shows after ≥2 checks",
    "♻️ 发起重标（G2 修订→重标闭环，仅已裁决 merged/split 可发）": "♻️ Re-annotate (G2 revise→re-annotate loop; only adjudicated merged/split may file)",
    "⚙️ 计算图式家族谱系": "⚙️ Compute schema-family genealogy",
    "⚠️ MySQL 数据库不可用，使用离线模式": "⚠️ MySQL unavailable — offline mode",
    "⚠️ 以下结果距离相同，供参照（并列距离按义位 id 稳定排序）。": "⚠️ The results below share the same distance, for reference (ties sorted stably by sense id).",
    "⚠️ 数据库初始化失败，已转入离线模式（详情见服务端日志）": "⚠️ Database init failed — switched to offline mode (see server logs)",
    "⚠️ 请先评分并填写反馈内容": "⚠️ Please rate and write your feedback first",
    "⛔ 仲裁面板仅 reviewer / admin 可用（annotator 之间互相不可见，规范 §0）。": "⛔ The arbitration panel is reviewer/admin only (annotators cannot see each other, spec §0).",
    "⛔ 数据导入仅词典管理员可用（导入同权，规范 §15）。": "⛔ Data import is dictionary-admin only (import parity, spec §15).",
    "⛔ 模型供应商管理仅词典管理员可用。": "⛔ Model-provider management is dictionary-admin only.",
    "⛔ 用户管理仅管理员可用。": "⛔ User management is admin only.",
    "⛔ 范畴与工具页仅管理员可用。": "⛔ The categories & tools page is admin only.",
    "⛔ 账号已被停用或删除，会话已失效，请重新登录。": "⛔ The account has been deactivated or deleted; the session expired — please sign in again.",
    "✅ 反馈已成功提交！感谢您的参与！": "✅ Feedback submitted successfully — thank you!",
    "✅ 反馈已记录（离线模式，未持久化）！": "✅ Feedback recorded (offline mode, not persisted)!",
    "✅ 密码已修改，下次登录请使用新密码。": "✅ Password changed — use the new password next sign-in.",
    "✓ 项目自检通过：chief 齐备且账号在用。": "✓ Project self-check passed: chiefs in place and accounts active.",
    "义位锚拼装失败（数据异常）。": "Failed to assemble the sense anchor (data anomaly).",
    "义位锚拼装失败（数据异常）：请换一个义位，或联系管理员核查 cs_senses 行。": "Failed to assemble the sense anchor (data anomaly): pick another sense, or ask an admin to inspect the cs_senses row.",
    "义项脊柱暂时不可用（编排异常，详见服务端日志）。": "The sense spine is temporarily unavailable (orchestration anomaly — see server logs).",
    "习语义项（IDIOMS 组）—— 按标注手册一般归入 N 或 EXT": "Idiom sense (IDIOMS group) — normally N or EXT per the annotation manual",
    "习语义项（IDIOMS 组）—— 按范畴包准入标准一般归入 N 或 EXT": "Idiom sense (IDIOMS group) — normally N or EXT per the category pack's gating standard",
    "仲裁保存失败（数据库写入未成功），请重试。": "Failed to save the arbitration (DB write did not succeed) — please retry.",
    "仲裁说明（note）": "Arbitration note",
    "会话用户信息不完整，请重新登录后再试。": "Session user info incomplete — sign in again and retry.",
    "你不是该任务的受派审校人，无法裁决。": "You are not this task's assigned reviewer and cannot adjudicate.",
    "保存修订（生成新版本）": "Save revision (creates a new version)",
    "保存失败（数据库写入未成功），请重试": "Save failed (DB write did not succeed) — please retry",
    "保存失败：会话失效、正文超长或数据库不可用。": "Save failed: session expired, text too long, or database unavailable.",
    "保存失败：参数或数据库异常，详见服务端日志。": "Save failed: parameter or database anomaly — see server logs.",
    "保存失败：键非法、值超长或数据库不可用。": "Save failed: invalid key, value too long, or database unavailable.",
    "信度报告仅对 reviewer / admin 开放。": "The reliability report is open to reviewer/admin only.",
    "修改失败（数据库未写入），请重试。": "Update failed (nothing written to the DB) — please retry.",
    "修改失败：用户不存在、角色未变化或数据库错误。": "Update failed: user missing, role unchanged, or database error.",
    "修改密码": "Change password",
    "修订历史": "Revision history",
    "值不能为空。": "Value cannot be empty.",
    "先在上方选择 ≥2 个 sense，再指定保留目标。": "Select ≥2 senses above first, then pick the keep target.",
    "入册未生效：数据层返回异常（详见服务端日志），请稍后重试。": "Enrolment did not take effect: data-layer anomaly (see server logs) — retry later.",
    "全部指标 α ≥ 0.7，信度达标。": "All indicators α ≥ 0.7 — reliability threshold met.",
    "写入失败：数据层返回异常（详见服务端日志），请稍后重试。": "Write failed: data-layer anomaly (see server logs) — retry later.",
    "创建失败：角色非法、用户名已存在或数据库错误。": "Creation failed: invalid role, username taken, or database error.",
    "删除失败（数据库不可用），请稍后重试。": "Delete failed (database unavailable) — retry later.",
    "删除失败：行不存在/数据库不可用。": "Delete failed: row missing or database unavailable.",
    "删除是物理 DELETE 且不可恢复：请先勾选「我确认物理删除」。": "Deletion is a physical, unrecoverable DELETE: tick \"I confirm physical deletion\" first.",
    "删除未生效：供应商可能已不存在或数据库不可用（详见服务端日志）。": "Delete did not take effect: the provider may be gone or the DB is unavailable (see server logs).",
    "反馈提交失败（数据库写入未成功），请稍后重试": "Feedback submission failed (DB write did not succeed) — retry later",
    "取消收藏失败（数据库不可用或收藏已不存在），请稍后重试。": "Un-favourite failed (DB unavailable or the favourite is gone) — retry later.",
    "取消收藏失败（数据库不可用），请稍后重试。": "Un-favourite failed (database unavailable) — retry later.",
    "只看待标注/存疑义位": "Only pending/doubtful senses",
    "台账暂无提案记录 —— 提案由各业务工序登记后按工序汇总。": "The ledger has no proposals yet — proposals are registered by each business step and aggregated per step.",
    "图谱数据组装失败（预计算距离矩阵缺失，或成员已全部并入）。": "Graph data assembly failed (precomputed distance matrix missing, or all members merged).",
    "字段代码与展示名不能为空。": "Field code and display name cannot be empty.",
    "字段清单已变化，请重试。": "The field list has changed — please retry.",
    "定义字段失败：数据层返回异常（详见服务端日志），请稍后重试。": "Field definition failed: data-layer anomaly (see server logs) — retry later.",
    "定稿后仍存疑（保留在复核清单）": "Still doubtful after finalisation (keep on the re-check list)",
    "定稿失败：参数非法/数据库不可用（lexical_db 已记日志）。": "Finalisation failed: invalid params or DB unavailable (logged by lexical_db).",
    "定稿理由 / 依据条款": "Finalisation rationale / cited clause",
    "实时生成暂不可用，已显示离线释义": "Real-time generation unavailable — showing the offline definition",
    "尚无书签——在义项脊柱点『📌 收藏本义位』即可收藏。": "No bookmarks yet — click \"📌 Favourite this sense\" in the sense spine to bookmark.",
    "尚无供应商可测试：请先「＋ 添加供应商」并保存。": "No provider to test yet: \"＋ Add provider\" and save first.",
    "尚无供应商：点下方「＋ 添加供应商」录入第一家。": "No providers yet: click \"＋ Add provider\" below to enter the first one.",
    "尚无词典项目：先在「🧭 主编驾驶舱」建壳（改派目标须挂项目在册）。": "No dictionary projects yet: create a shell in \"🧭 Cockpit\" first (reassignment targets must belong to a project).",
    "尚无词典项目：在下方「🏗️ 创建项目（建壳）」建壳并指定首位词典管理员。": "No dictionary projects yet: create a shell via \"🏗️ Create project\" below and designate the first dictionary admin.",
    "左侧选择一家供应商，或点「＋ 添加供应商」新建。": "Pick a provider on the left, or click \"＋ Add provider\" to create one.",
    "已退出登录：会话数据已清空，请先登录后再访问受保护页面。": "Signed out: session data cleared — sign in before accessing protected pages.",
    "广播未发布：数据层返回异常（详见服务端日志），请稍后重试。": "Broadcast not published: data-layer anomaly (see server logs) — retry later.",
    "建壳失败（名称重复或数据库异常），详见服务端日志。": "Shell creation failed (duplicate name or DB anomaly) — see server logs.",
    "弃用失败：字段不存在或已弃用（未变更不重复计）。": "Deprecation failed: field missing or already deprecated (no change is not counted).",
    "弃用失败：数据层返回异常（详见服务端日志），请稍后重试。": "Deprecation failed: data-layer anomaly (see server logs) — retry later.",
    "当前密码不正确。": "Current password is incorrect.",
    "当前没有 finished 批次（回滚的合法起点）。": "No finished batches (the legal starting point for rollback).",
    "当前没有分歧条目（各编码人取值一致、不足两人，或已全部定稿）。": "No disagreement items (coders agree, fewer than two coders, or all finalised).",
    "当前没有可提交的在途草稿：请先「保存草稿」，再提交初审。": "No in-flight draft to submit: \"Save draft\" first, then submit for review.",
    "当前笔记为空（''=显式清空但保留行）。": "The note is currently empty ('' = explicitly cleared but the row is kept).",
    "当前筛选下无义位。": "No senses match the current filter.",
    "当前簇没有可导出的模板。": "The current cluster has no templates to export.",
    "当前角色：（无六角色记录，按旧角色列兜底显示）": "Current roles: (no six-role records — falling back to the legacy role column)",
    "意见内容为空。": "Comment text is empty.",
    "成文有未保存的修改：请先「保存草稿」，再提交初审。": "The text has unsaved changes: \"Save draft\" first, then submit for review.",
    "所选例证已被删除或列表已刷新，请重选。": "The selected example was deleted or the list refreshed — pick again.",
    "打回失败：任务已被处理或状态已变化，请刷新。": "Rejection failed: the task was already handled or its state changed — refresh.",
    "打回须给理由：请在裁决意见里写明修订要求。": "Rejection requires a reason: state the revision requirements in the adjudication comment.",
    "授予未生效：该用户已持有该角色、用户不存在或数据库错误。": "Grant did not take effect: the user already holds the role, the user is missing, or a database error.",
    "探针通道暂无待决记录。": "No pending records on the probe channel.",
    "提交失败（数据库写入未成功或校验未通过），请重试": "Submission failed (DB write did not succeed or validation failed) — please retry",
    "撤销未生效：该用户未持有该角色、用户不存在或数据库错误。": "Revoke did not take effect: the user does not hold the role, the user is missing, or a database error.",
    "操作失败：用户不存在、状态未变化或数据库错误。": "Operation failed: user missing, state unchanged, or database error.",
    "收藏失败（数据库不可用），请稍后重试。": "Favouriting failed (database unavailable) — retry later.",
    "数值字段的值必须是有限数字。": "A numeric field's value must be a finite number.",
    "数据库不可用，仲裁面板不可用（离线模式）。": "Database unavailable — the arbitration panel is unavailable (offline mode).",
    "数据库不可用，提交流不可用（离线模式）。": "Database unavailable — the submission flow is unavailable (offline mode).",
    "数据库不可用，无法展示词簇图谱（离线模式下仅提供释义）。": "Database unavailable — the cluster graph cannot be shown (offline mode provides definitions only).",
    "数据库不可用，标注平台不可用。": "Database unavailable — the annotation platform is unavailable.",
    "数据源：ai_proposals kind='draft' 的 adopted+modified 计数。": "Data source: adopted+modified counts of ai_proposals kind='draft'.",
    "文件中没有数据行，无法登记批次。": "The file has no data rows — cannot register a batch.",
    "文件类型不在上传白名单内（png/jpeg/jpg/mp3/mp4）。": "File type not on the upload whitelist (png/jpeg/jpg/mp3/mp4).",
    "文件解析失败：请确认上传的是 xlsx 或 csv（docx 阶段 2 接入）。": "File parsing failed: please upload xlsx or csv (docx lands in phase 2).",
    "新供应商尚未保存：请先「保存」，再测试连通。": "The new provider is not saved yet: \"Save\" first, then test connectivity.",
    "无 ready 态快照可流转（published/revoked 为终态，清单见上）。": "No ready snapshots to transition (published/revoked are terminal — see the list above).",
    "无对齐数据。": "No alignment data.",
    "无成员可移除。": "No members to remove.",
    "无汉语义位。": "No Chinese senses.",
    "无法确定操作人（会话用户缺少有效 id），不能登记批次。": "Cannot identify the operator (session user lacks a valid id) — batch not registered.",
    "无簇可锁定（当前运行簇清单为空）。": "No clusters to lock (the current run's cluster list is empty).",
    "无簇证据可引用（运行簇清单为空），暂不能发起建议。": "No cluster evidence to cite (the run's cluster list is empty) — cannot file a suggestion yet.",
    "无编码数据，无法推导图式。": "No coding data — the schema cannot be derived.",
    "无英语义位。": "No English senses.",
    "日期格式须为 YYYY-MM-DD。": "Date format must be YYYY-MM-DD.",
    "显示簇内边表（两两 Gower 距离，按距离降序）": "Show the in-cluster edge table (pairwise Gower distances, descending)",
    "暂无任务分配/提交数据。": "No assignment/submission data yet.",
    "暂无可选义位（cs_senses 未建表/无数据/数据库不可用）。": "No selectable senses (cs_senses missing / no data / database unavailable).",
    "暂无已存偏好键（保存上方预设键或新增自定义键后可删）。": "No saved preference keys (save a preset key above or add a custom one, then delete).",
    "暂无意见。": "No comments.",
    "暂无提交记录。": "No submissions.",
    "暂无数据：书签控件渲染异常（详见服务端日志）。": "No data: bookmark widget render anomaly (see server logs).",
    "暂无数据：我的笔记段渲染异常（详见服务端日志）。": "No data: my-notes section render anomaly (see server logs).",
    "暂无更多广播记录（或数据库暂不可用）。": "No more broadcasts (or the database is temporarily unavailable).",
    "暂无用户。请确认数据库已初始化（users 表由 ensure_user_tables 创建）。": "No users yet. Confirm the database is initialised (the users table is created by ensure_user_tables).",
    "暂无用户可入册（账号由平台管理员在系统管理区创建）。": "No users to enrol (accounts are created by the platform admin in System Administration).",
    "暂无绑定记录（media_bindings 为空或数据库不可用）。": "No binding records (media_bindings empty or database unavailable).",
    "暂无资产可绑定：先在上方「登记资产」。": "No assets to bind: \"Register asset\" above first.",
    "暂无资产记录（media_assets 为空、按状态筛选无命中，或数据库不可用）。": "No asset records (media_assets empty, no match for the status filter, or database unavailable).",
    "暂无进行中的任务：任务由词典管理员在「任务分配」页分派后出现在这里。": "No in-flight tasks: tasks appear here after the dictionary admin assigns them on the Task Assignment page.",
    "未搜索或无命中：不选动词则任务不限动词（scope_verbs=NULL，全库）。": "Not searched or no hits: with no verbs selected the task covers all verbs (scope_verbs=NULL, whole library).",
    "未配置": "Not configured",
    "本版无 AI/模板草稿快照（纯人工撰写）。": "This version has no AI/template draft snapshot (purely human-written).",
    "本簇全部要素共享，无可变槽位。": "All elements in this cluster are shared — no variable slots.",
    "本簇没有成员义位，无法实例化。": "This cluster has no member senses — cannot instantiate.",
    "本簇没有达到阈值的共享二元要素。": "This cluster has no shared binary features above the threshold.",
    "本范畴暂无运行层操作审计。": "No run-level operation audit for this category yet.",
    "本项目还没有定制字段：先在上方「定义字段」。": "No custom fields in this project yet: \"Define field\" above first.",
    "查看义位 → 簇归属对照": "View sense → cluster-membership mapping",
    "模板实例化失败，请查看日志。": "Template instantiation failed — check the logs.",
    "没有可与该向量比对的义位（该范畴 / 语言侧没有特征编码数据）。": "No senses comparable to this vector (no feature coding for this category/language side).",
    "没有可修改角色的其他用户。": "No other users whose roles can be changed.",
    "没有可弃用的在用字段。": "No active fields to deprecate.",
    "没有可授予角色的其他用户。": "No other users to grant roles to.",
    "没有可操作的其他用户。": "No other users to operate on.",
    "没有可改派的分派（status='open' 的分派为空）。": "No assignments to reassign (no status='open' assignments).",
    "没有可流转的绑定（全部已发布或状态未知）。": "No bindings to transition (all published or state unknown).",
    "没有在用字段可写值：先「定义字段」。": "No active fields to write values for: \"Define field\" first.",
    "没有检测到分歧（各编码人对所有共同标注单元的取值一致，或重叠样本不足）。": "No disagreement detected (coders agree on all jointly annotated units, or the overlap is insufficient).",
    "流转未生效：绑定状态已被他人变更（乐观并发守卫）或数据库不可用。": "Transition did not take effect: the binding state was changed by someone else (optimistic-concurrency guard) or the DB is unavailable.",
    "清单为空：连通测试与业务调用将无模型可选。": "The list is empty: connectivity tests and business calls will have no model to pick.",
    "点上方「⚙️ 计算图式家族谱系」生成。": "Click \"⚙️ Compute schema-family genealogy\" above to generate.",
    "生成当前簇全部模板": "Generate all templates for the current cluster",
    "用户名与初始密码不能为空。": "Username and initial password cannot be empty.",
    "用户名或密码错误，或账号已停用。": "Wrong username or password, or the account is deactivated.",
    "登录不可用（数据库离线）": "Sign-in unavailable (database offline)",
    "登记失败（AI 台账不可用或载荷被拒），请稍后重试。": "Registration failed (AI ledger unavailable or payload rejected) — retry later.",
    "登记失败：参数非法或数据库不可用（详见服务端日志）。": "Registration failed: invalid params or DB unavailable (see server logs).",
    "登记失败：文件不存在/参数非法/数据库不可用（media_db 已记日志）。": "Registration failed: file missing / invalid params / DB unavailable (logged by media_db).",
    "移除未生效：数据层返回异常（详见服务端日志），请稍后重试。": "Removal did not take effect: data-layer anomaly (see server logs) — retry later.",
    "管理 LLM 模型供应商，配置后在释义生成等 AI 功能中使用。": "Manage LLM providers; once configured they become usable by AI features such as definition generation.",
    "绑定失败：数据层返回异常（详见服务端日志），请稍后重试。": "Binding failed: data-layer anomaly (see server logs) — retry later.",
    "绑定选择已变化，请重试。": "The binding selection has changed — please retry.",
    "自定义键不能为空。": "The custom key cannot be empty.",
    "范畴": "Category",
    "落盘失败：无法写入 data/media（磁盘/权限问题，详见服务端日志）。": "Failed to write to disk: cannot write data/media (disk/permission issue — see server logs).",
    "落盘路径计算失败（资产形态非法或内容不可读），上传已取消。": "Failed to compute the disk path (invalid asset kind or unreadable content) — upload cancelled.",
    "记账失败：批次不存在、已非 running 态或数据库不可用。": "Accounting failed: batch missing, no longer running, or database unavailable.",
    "词库为空：先运行 `python scripts/load_word_library.py` 灌入义位。": "The word library is empty: run `python scripts/load_word_library.py` first.",
    "词条装配预览暂时不可用（编排异常，详见服务端日志）。": "The entry-assembly preview is temporarily unavailable (orchestration anomaly — see server logs).",
    "词簇图生成失败，请检查 `src/static/` 是否可写。": "Cluster graph generation failed — check that `src/static/` is writable.",
    "该 (范畴, 任务类型) 下还没有已提交的标注。": "No submitted annotations for this (category, task type) yet.",
    "该义位尚未定稿对译——三态单选后填表定稿。": "This sense's translation is not finalised — pick one of the three states and finalise.",
    "该义位暂无 LLM 初筛草稿（可直接人工判定）。": "No LLM pre-screen draft for this sense (judge manually straight away).",
    "该义位暂无例证，先在上方新增。": "No examples for this sense — add one above first.",
    "该义位暂无例证，先在下方新增（新例证以「候选」态起步）。": "No examples for this sense — add below first (new examples start in \"candidate\" state).",
    "该义位暂无例证，先新增文字例证再绑媒体。": "No examples for this sense — add a textual example before binding media.",
    "该义位还没有任何释义版本：去「✍️ 撰写台」开第一版。": "No definition versions for this sense yet: open the first one in \"✍️ Writing Bench\".",
    "该义位还没有私人笔记（仅自己可见；保存后跨设备续接）。": "No private note for this sense yet (visible only to you; synced across devices once saved).",
    "该义位还没有笔记可删。": "This sense has no note to delete yet.",
    "该例证尚无媒体绑定。": "This example has no media bindings yet.",
    "该例证已「发布」（终态，不可再流转）。": "This example is \"published\" (terminal — no further transitions).",
    "该用户暂无可撤销的六角色（授予后可撤销）。": "This user has no six-role grants to revoke (grant first, then revoke).",
    "该筛选条件下没有待处理义位 🎉": "No pending senses under this filter 🎉",
    "该范畴/语言暂无义位（与撰写台同源，merged 禁选）。": "No senses for this category/language (same source as the writing bench; merged senses excluded).",
    "该词目暂无 oald_senses 义项记录（如实标注，不编造）。": "No oald_senses records for this lemma (labelled truthfully — never invented).",
    "该项目还没有成员（除建壳时的首位 chief 外）。": "No members in this project yet (besides the first chief designated at shell creation).",
    "请先勾选上方确认框（保存为探索性运行版本）。": "Tick the confirmation box above first (saves as an exploratory run version).",
    "请先登录后再访问编纂成文区（例证与对译）。": "Sign in before entering the writing zone (Examples & Translation).",
    "请先登录后再访问词典管理区。": "Sign in before entering the Dictionary Admin zone.",
    "请先登录后再访问释义撰写与审校工作台。": "Sign in before entering the writing & review workbench.",
    "请先选择准入标签（Y / EXT / N）。": "Pick a gating label first (Y / EXT / N).",
    "请先选择审校人（回避制：不能选自己）。": "Pick a reviewer first (recusal: you cannot pick yourself).",
    "请先选择金标准入标签（Y / EXT / N）。": "Pick the gold-standard gating label first (Y / EXT / N).",
    "请填写当前密码与新密码，且两次新密码一致。": "Fill the current password and the new password, with both new entries matching.",
    "请填写至少一个受影响义位 id（逗号分隔的正整数）。": "Provide at least one affected sense id (comma-separated positive integers).",
    "谱系树数据不足（簇成员少于 2 个）。": "Insufficient dendrogram data (fewer than 2 cluster members).",
    "谱系树数据不足（簇成员少于 2 个），义位图谱不可用。": "Insufficient dendrogram data (fewer than 2 members) — the sense map is unavailable.",
    "谱系树数据不足（簇成员少于 2 个），分立复核不可用。": "Insufficient dendrogram data (fewer than 2 members) — split re-check is unavailable.",
    "轮次须为 ≥1 的整数（第几轮标注），不能是 0 或负数。": "The round must be an integer ≥1 (which annotation round), not 0 or negative.",
    "轮次须为 ≥1 的整数，或留空表示正式轮（不留痕）。": "The round must be an integer ≥1, or empty for the formal round (untracked).",
    "输入词目关键字开始检索（如 run —— 当前匹配 definitions.verb 词目列）。": "Type a lemma keyword to start searching (e.g. run — currently matches the definitions.verb lemma column).",
    "运行范畴包工具引用自检": "Run the category-pack tool-reference self-check",
    "选择义位（SenseID）": "Pick a sense (SenseID)",
    "通过失败：任务已被处理或状态已变化，请刷新。": "Approval failed: the task was already handled or its state changed — refresh.",
    "释义成文为空，无法提交。": "The composed text is empty — cannot submit.",
    "释义成文为空：暂存前请先撰写内容。": "The composed text is empty: write something before stashing.",
    "释义成文为空：请先撰写内容再保存。": "The composed text is empty: write something before saving.",
    "释义模板引擎 · 母图式提炼与槽位实例化": "Definition template engine · master-schema distillation and slot instantiation",
    "释义语料为空——重建跳过（./start status 查库）": "Definition corpus empty — rebuild skipped (check the DB via ./start status)",
    "金标英汉对齐": "Gold-standard EN-ZH alignment",
    "项目名称必填。": "Project name is required.",
    "（corpus_word_stats 词频暂无数据或不可用 —— 词频列留空，不编数。）": "(corpus_word_stats frequency unavailable — frequency column left empty, no invented numbers.)",
    "（plotly 未安装，条形图不可用 —— 成员排序表不受影响。）": "(plotly not installed — bar chart unavailable; the sorted member table is unaffected.)",
    "（暂无历史）": "(no history)",
    "（该英簇无对齐汉簇）": "(this EN cluster has no aligned ZH cluster)",
    "（语义分析数据未就绪 —— 见页面顶部提示。）": "(semantic-analysis data not ready — see the notice at the top of the page.)",
    "🎯 试标轮分派（轮次/试标位留痕，默认留空=正式轮）": "🎯 Trial-round assignment (round/trial slot tracked; empty = formal round)",
    "🏗️ 创建项目（建壳并指定首位词典管理员）": "🏗️ Create project (shell + first dictionary admin)",
    "💾 保存为新运行版本": "💾 Save as new run version",
    "💾 保存仲裁定稿（金标）": "💾 Save arbitration finalisation (gold standard)",
    "💾 保存本义位标注": "💾 Save this sense's annotation",
    "📄 词条锚暂不支持跳转（依赖词条浏览器上下文），挂账中。": "📄 Entry anchors do not support jumps yet (needs the entry-browser context) — pending.",
    "📊 任务分配进度（get_assignment_stats）": "📊 Assignment progress (get_assignment_stats)",
    "📌 收藏本义位": "📌 Favourite this sense",
    "📍 已收藏·取消": "📍 Favourited · Remove",
    "📖 OALD10 词典原文对照（英语侧证据源）": "📖 OALD10 originals (EN-side evidence source)",
    "📖 《现汉7》词典原文对照（甄别证据源）": "📖 现汉7 originals (screening evidence source)",
    "📢 该项目暂无广播记录（或数据库暂不可用，稍后重试）。": "📢 No broadcasts for this project yet (or the database is temporarily unavailable — retry later).",
    "📢 项目广播取数暂不可用（数据库未就绪），稍后重试。": "📢 Broadcast data temporarily unavailable (database not ready) — retry later.",
    "📤 提交分立建议": "📤 Submit split suggestion",
    "📤 提交本义位标注": "📤 Submit this sense's annotation",
    "🔁 改派分派（仅未动工 open 的分派可改派）": "🔁 Reassign (only untouched open assignments)",
    "🔄 从语料重建初版（高级）": "🔄 Rebuild initial version from corpus (advanced)",
    "🔑 修改密码": "🔑 Change password",
    "🗄️ 书签读取失败（数据库异常），暂不可用。": "🗄️ Bookmark read failed (database anomaly) — temporarily unavailable.",
    "🗄️ 数据库离线，书签暂不可读。": "🗄️ Database offline — bookmarks temporarily unreadable.",
    "sense_division 工序暂无待裁决提议（台账为空或 AI 台账不可用）。": "No pending proposals for the sense-division step (ledger empty or AI ledger unavailable).",
    # —— 批次 61 补：Levin 十二次类簇名＋四图式名（词表灌库固定常量，DB 数据值展示层译径）——
    "陆地行进类": "Land-travel",
    "奔跑行进类": "Running",
    "腾空跳跃类": "Leaping",
    "匍匐爬行类": "Crawling",
    "滚动滑行类": "Rolling",
    "长途行进类": "Long-distance",
    "飞行游动类": "Flying & Swimming",
    "运载工具类": "Vehicle",
    "来源类": "Source",
    "终点类": "Endpoint",
    "目的类": "Purposive",
    "参与者类": "Participant",
    "方式位移域": "Manner-Motion Domain",
    "路径位移域": "Path-Motion Domain",
    "互动位移域": "Interactive-Motion Domain",
    "方式伴随图式": "Manner-accompanying Schema",
    "源点脱离图式": "Source-off Schema",
    "终点抵达图式": "Endpoint-arrival Schema",
    "互动位移图式": "Interactive-motion Schema",
    # —— 批次 61 补：角色标签（ROLE_LABELS 消费点过 _t）＋改密提示＋续接上次 ——
    "管理员": "Admin",
    "审核员": "Reviewer",
    "标注员": "Annotator",
    "只读": "Read-only",
    "词典管理员": "Dictionary Admin",
    "平台管理员": "Platform Admin",
    "撰写员": "Editor",
    "内置管理员": "Built-in Admin",
    "⚠️ 默认密码未修改——请在下方「🔑 修改密码」中更换（改后此提示自动消失）。": "⚠️ Default password unchanged — change it under “🔑 Change password” below (this notice disappears once changed).",
    "🔐 初始口令未修改——请在「🔑 修改密码」中更换。": "🔐 Initial password unchanged — change it under “🔑 Change password”.",
    "续接上次": "Resume last",
}
