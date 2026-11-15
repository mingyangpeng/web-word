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
}
