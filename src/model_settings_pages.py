"""模型供应商管理页 —— 多供应商 LLM 配置（Agent MP-P）。

区级单页（无 tabs）：左侧供应商列表 + 右侧编辑面板（st.columns([1, 3])，
参考区级页面视觉语言 src/dict_admin_pages.py：_esc 转义 + 角色门 + 卡片）。
数据全部来自数据层 src/llm_providers_db.py（Agent MP-D 并行交付的
llm_providers 三表：providers / models / 连通性探测），本模块只做页面编排，
不重复实现业务规则、不 import app.py / llm_api.py。

是什么：
  * 左列：供应商单选列表（st.radio，启用/默认状态进标签）＋「＋ 添加供应商」
    按钮 —— 点击后右栏切到空白新建模式；
  * 右列（编辑面板）：名称 / Base URL / API 格式（openai / anthropic）/
    API Key（password 遮蔽，管理员可经 st.toggle 切明文）＋ 模型列表
    （text_area 每行一个，另给「＋ 添加模型」单条追加）＋ enabled /
    is_default 两个 toggle ＋「保存」「删除」「测试连通」三按钮；
  * 测试连通调 llm_providers_db.test_provider_connectivity，结果经
    _normalize_test_result 容错归一后以 st.success / st.error 转述。

管理决策（本批次口径，改口径须同步 docstring 与帮助文档）：
  * API Key **明文存储**于数据库（不做加密/掩码列）——平台是单机研究工具，
    Key 只经本页 password 输入框回显给词典管理员（type=password 默认遮蔽，
    st.toggle 主动切换才显示明文）；不入日志、不出现在导出/快照通道；
    名称 / Base URL / API Key 三项必填是数据层硬约束，表单侧先拦。
  * 删除是**物理 DELETE**：供应商配置（名称/URL/Key/模型清单）皆可由管理员
    随时重建，无需软删留痕；删除前须勾选确认框（两步防误删）。
  * is_default（默认供应商）只能**转移**不能直接取消（set_default 事务内先清
    全表再设本条）；新建供应商入库即 enabled=1 / is_default=0，新建表单里的
    enabled / is_default 开关由页面在建档后用 set_enabled / set_default 补齐。

权限（纵深防御，规范 §6-4：入口判定，不信任前端隐藏）——仅词典管理员：
  1. 会话纯函数 _is_model_admin：users_db.effective_six_roles（与 app.py /
     users_admin_page 同源的单一实现）含 'dict_admin'，或过渡期 role ==
     'admin'（内置 admin 的 users_db 幂等迁移口径）；
  2. 会话不放行时实时查库 users_db.has_role(id, 'dict_admin') 兜底
     （会话快照滞后于授权的场景，_db_confirms_model_admin）。
两层都不过 → st.error 并 return，页面内容不渲染。写路径（保存/删除）另过
guards.require_dict_admin() 中央闸门（与 dict_admin_pages 写路径同款第二层）。

widget key 一律 'llm_' 前缀（见各 st.* 调用 key= 与 _EDIT_MARKER/_FLASH_KEY）；
供应商名/模型名/Base URL 进 unsafe_allow_html 前一律过 _esc；radio/selectbox
的选项文本由 Streamlit 自带转义，不需（也不能）先转义。

编辑面板状态机（跨 rerun 的 widget 状态管理）：
  * 选中供应商 pid 记在 st.session_state["llm_selected_id"]；新建模式记在
    st.session_state["llm_creating"]；
  * 字段编辑缓冲（llm_name / llm_base_url / llm_api_format / llm_api_key /
    llm_models 等固定 key）由 _sync_edit_buffer 在「编辑目标变更」时整体
    重写（marker _EDIT_MARKER 记录当前目标，widget 实例化前写 session
    即为其初值，无需额外 rerun）——避免切换供应商后残留上一个的值。

对 llm_providers_db 的调用集中在本模块 _save_provider / _delete_provider /
_test_provider / _list_providers 四个调用点（数据层契约由 Agent MP-D 冻结）：
  * list_providers() -> list[dict]（_row_to_provider 形态：id/name/base_url/
    api_format/api_key/models(list)/enabled/is_default/sort_order/...）；
  * create_provider(name, base_url, api_format, api_key, models=None,
    created_by=None) -> int（0=失败；新行 enabled=1 / is_default=0）；
  * update_provider(provider_id, **kwargs) -> bool（白名单 name/base_url/
    api_format/api_key/models/enabled/sort_order；is_default 刻意不在白名单；
    「无变更」返回 False —— 页面先对库内现值做差量再提交，免误报）；
  * set_enabled(provider_id, enabled) -> bool / set_default(provider_id)
    -> bool（全表唯一默认，只能转移不能取消）；
  * delete_provider(provider_id) -> bool（物理 DELETE）；
  * test_provider_connectivity(provider_id) -> {"ok": bool, "status_code",
    "latency_ms", "model", "error"}（_normalize_test_result 容错归一，
    兼容 bool / 二元组 / 其他 dict 形态）。
数据层未就绪（ImportError）时页面降级为提示，不崩 import。

由集成步骤挂载（render_model_settings_page() 注册进 app.py 分派 ＋ GUIDE
原样并入 PAGE_GUIDES["model_settings"]）；本模块不修改 app.py / page_guides.py。
"""

import json
import logging
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src import users_db
from src.db_utils import current_user as _current_user
from src.design_system import HEADER_H3, get_card_style
from src.guards import require_dict_admin

try:
    from src import llm_providers_db
except ImportError:  # pragma: no cover —— MP-D 数据层交付前的过渡窗口
    llm_providers_db = None

logger = logging.getLogger(__name__)

# ============================================
# 页面使用说明（四段式；集成时原样并入 PAGE_GUIDES["model_settings"]）
# ============================================

GUIDE: Dict[str, Any] = {
    "label": "🤖 模型供应商",
    "purpose": (
        "管理 LLM 模型供应商（名称 / Base URL / API 格式 / API Key / 模型清单）"
        "的配置页：配置通过连通性测试后，即可在释义生成等 AI 功能中使用；"
        "仅词典管理员可用，API Key 明文存储、页面默认遮蔽仅管理员可切明文。"
    ),
    "principle": [
        "多供应商同构配置：每家供应商就是一条（name, base_url, api_format, "
        "api_key, models, enabled, is_default）记录，api_format 只分 openai / "
        "anthropic 两族 —— 两大 API 形态之外的差异（模型名、温度等）不进本页，"
        "页面不做供应商特判，业务侧（释义生成等）只认「启用中的供应商」。",
        "API Key 明文存储是本批次的管理决策：平台为单机研究工具，Key 只经本页 "
        "password 输入框（默认遮蔽）回显，管理员经 st.toggle 主动切换才显示"
        "明文；Key 不入日志、不进导出与快照通道。若部署形态变化（多人共库等）"
        "应先改存储口径再放开可见性。",
        "is_default（默认供应商）与 enabled（启用）是两个独立开关：enabled 关闭"
        "只是本供应商下线不删除，配置保留可随时重新启用；is_default 标记 AI "
        "功能的默认选择，唯一性由数据层 set_default 事务保证（先清全表再设本条）"
        "——默认只能转移、不能直接取消，停用的默认供应商会被 AI 功能自动跳过"
        "（回落平台兜底配置）。",
        "模型清单（models）每行一个模型名：它是该供应商下可供业务侧挑选的模型"
        "白名单，可在文本域批量编辑，也可用「＋ 添加模型」单条追加；空清单等于"
        "「未配置可用模型」——连通测试取清单第一个模型发起最小请求，清单为空时"
        "会如实报「无法发起连通性测试」。",
        "删除是物理 DELETE 且两步确认：供应商配置可随时重建（名称/URL/Key/模型"
        "清单都是管理员手填的重建成本极低的数据），无需软删留痕；误删的最大代价"
        "是重新录入一遍，因此不做回收站。",
        "权限最小化：模型供应商是平台级 AI 基础设施配置（配置错了影响所有 AI "
        "功能），故只对词典管理员开放（会话判定 ＋ 实时查库兜底两层角色门），"
        "普通用户/标注员/只读者不可见不可写。",
    ],
    "data_source": [
        "src/llm_providers_db.py：llm_providers（供应商配置表）—— list_providers "
        "（sort_order,id 升序）读清单、create_provider 建档（新行 enabled=1 / "
        "is_default=0，名称 UNIQUE）、update_provider 白名单字段更新（name/"
        "base_url/api_format/api_key/models/enabled，无变更返回 False）、"
        "set_enabled / set_default（全表唯一默认，事务保证）、delete_provider "
        "（物理 DELETE）、test_provider_connectivity（取 models 第一个发 "
        "max_tokens=1 的最小请求，返回 ok/status_code/latency_ms/model/error）"
        "—— models 以 JSON 串落库，页面用 _as_model_list 容读。",
        "src/users_db.py：users / user_roles（effective_six_roles 作会话角色门"
        "单一实现；has_role(id, 'dict_admin') 作实时兜底）。",
        "src/guards.py：require_dict_admin 中央闸门 —— 保存/删除等写路径在页面"
        "角色门之后再过一道 API 级闸门（与词典管理区写路径同款纵深防御）。",
        "src/db_utils.py：current_user() 读当前会话用户（st.session_state['user']，"
        "fail-closed）；建档人 users.id 随 create_provider 的 created_by 留痕。",
    ],
    "steps": [
        "进入「🤖 模型供应商」先看左列供应商列表：每项标注「#id」与状态后缀"
        "（·默认 / ·停用）；点选即载入右栏编辑面板（名称 / Base URL / API 格式 / "
        "API Key / 模型清单 / 启用 / 默认）。",
        "「＋ 添加供应商」：右栏切到空白新建模式，填名称与 Base URL（须以 "
        "http(s):// 开头）、选 API 格式（openai / anthropic）、粘贴 API Key"
        "（必填）、在模型清单文本域每行填一个模型名（或用「＋ 添加模型」单条"
        "追加）后点「保存」——保存成功即入列表，可继续测试连通。",
        "编辑既有供应商：改字段后点「保存」（与库内现值相同的保存会被数据层计为"
        "「未变更」，页面先做差量提交避免误报）；API Key 默认以密码形态遮蔽，"
        "需要核对时打开「👁 显示明文」开关（仅管理员本人页面可见），核对完建议"
        "关回遮蔽态。",
        "「测试连通」：对已保存的供应商发起一次真实最小请求（新建未保存的供应商"
        "须先保存；取模型清单第一个模型，max_tokens=1），结果以绿/红转述（含 "
        "HTTP 状态码、耗时与模型名）；401/403 提示 Key 无效、404 提示核对 "
        "base_url、网络异常如实转述。",
        "「删除」：先勾选「我确认物理删除」再点「删除」——物理 DELETE 不可恢复，"
        "供应商配置可随时按原参数重建；删除后列表自动落到剩余首项。",
        "enabled / is_default 两个开关随「保存」一并提交：临时下线某家供应商用 "
        "enabled=关（配置保留），把 AI 功能默认走某家供应商用 is_default=开"
        "（设默认须目标供应商处于启用态才会在 AI 功能中生效；取消默认不可直接"
        "操作，把另一家设为默认即自动转移）。",
    ],
    "notes": [
        "权限口径：本页仅词典管理员可用；过渡期内置 admin 账号视为兼有 "
        "dict_admin（会话 role=='admin' 直接放行，另有 users_db.has_role 实时"
        "兜底）。平台管理员如需接管须先被授予 dict_admin。",
        "API Key 明文存储（管理决策）：数据库不做加密列，页面默认 password 遮蔽，"
        "「显示明文」开关只改变当前页面的回显形态；Key 永不打进服务端日志。"
        "名称 / Base URL / API Key 必填是数据层硬约束（create_provider 拒空），"
        "表单侧先拦并给可读文案。如需轮换 Key：直接在编辑面板粘贴新 Key 保存"
        "即可，无需删除重建。",
        "新建模式与编辑模式共用一套字段控件（llm_ 前缀固定 key）：切换供应商/"
        "进出新建时页面会整体重写编辑缓冲（_sync_edit_buffer），不会把上一家的"
        "配置残留到下一家的表单里。",
        "测试连通只对已保存的供应商可用：新建未保存时按钮会提示先保存 —— 连通"
        "探测需要数据层落库后的完整配置（含 Key 与首个模型）才能发起。",
        "删除是物理 DELETE（管理决策）：不软删、无回收站；删除前必须勾选确认框，"
        "两步防误删。删除默认供应商后 AI 功能回落平台兜底配置（数据层口径），"
        "本页不做二次确认弹窗。",
        "所有供应商名/模型名/Base URL 渲染进 HTML（标题、状态卡）前一律转义；"
        "下拉与单选的选项文本由 Streamlit 自带转义。",
    ],
}

# ============================================
# 展示常量
# ============================================

# API 格式白名单与数据层同源（llm_providers_db.API_FORMATS；数据层未就绪时
# 用本地兜底常量，保证纯函数测试不依赖数据层在场）
API_FORMATS: Tuple[str, ...] = (
    tuple(getattr(llm_providers_db, "API_FORMATS", ()) or ())
    or ("openai", "anthropic")
)
API_FORMAT_LABELS = {
    "openai": "OpenAI 兼容（openai）",
    "anthropic": "Anthropic 原生（anthropic）",
}

# 新建/编辑模式的编辑目标哨兵（session marker；pid 为 int，新建用字符串）
_EDIT_TARGET_NEW = "new"
_EDIT_MARKER = "llm_edit_loaded_for"
_FLASH_KEY = "llm_flash"          # 跨 rerun 的一次性提示（(kind, text) 元组）
_SELECTED_KEY = "llm_selected_id"  # 左列当前选中供应商 id（int）
_CREATING_KEY = "llm_creating"     # 是否处于新建模式（bool）

_BASE_URL_SCHEMES = ("http://", "https://")


# ============================================
# 纯函数（无 st./DB 依赖，tests/test_model_settings_pages.py 直接测）
# ============================================

def _esc(value: Any) -> str:
    """任意值 → HTML 安全文本（str() 后 html.escape 含引号）。

    所有进 unsafe_allow_html 的供应商名/模型名/Base URL 必须先过这里；
    radio/selectbox 等纯文本控件由 Streamlit 自带转义，调用方不要再转。
    """
    return _html_escape(str(value), quote=True)


def _is_model_admin(user: Any) -> bool:
    """会话用户 dict 是否放行模型供应商页（纯函数，fail-closed）。

    口径（与 dict_admin_pages._is_dict_admin 同款过渡期判定）：
      * users_db.effective_six_roles（六角色单一实现）含 'dict_admin' 放行
        —— legacy role=='admin' 经映射必然兼有 dict_admin；
      * 过渡兜底：role == 'admin' 直接放行（不依赖映射表在场的保守判定）；
      * 非 dict 会话、缺键、roles 为非序列类型一律不放行（fail-closed，
        不做大小写/类型宽容 —— 角色枚举在库里恒为小写字面量）。
    实时兜底（会话滞后场景）由 _db_confirms_model_admin 另行查库，不在本函数。
    """
    if not isinstance(user, dict):
        return False
    try:
        if "dict_admin" in users_db.effective_six_roles(user):
            return True
    except Exception as e:  # pragma: no cover —— 会话结构异常时继续走兜底判定
        logger.warning(f"effective_six_roles 计算失败（username={user.get('username')!r}）: {e}")
    return user.get("role") == "admin"


def _db_confirms_model_admin(user: Dict[str, Any]) -> bool:
    """实时查库兜底：users_db.has_role(id, 'dict_admin')（fail-closed）。

    会话快照可能滞后（先登录后被授予 dict_admin，或旧版会话 dict 无 roles 键），
    会话判定不过时以库为准再核一次。has_role 自身对停用/不存在/库故障返回
    False，这里只兜异常不让角色门崩页面。
    """
    try:
        uid = int(user.get("id") or 0)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    try:
        return users_db.has_role(uid, "dict_admin")
    except Exception as e:  # pragma: no cover —— 数据层已自兜底，防御性兜一层
        logger.warning(f"dict_admin 角色兜底查询失败（uid={uid}）: {e}")
        return False


def _parse_models_text(raw: Any) -> List[str]:
    """「glm-4\\ndeepseek-v3」→ ['glm-4', 'deepseek-v3']（每行一个模型名）。

    去首尾空白、丢空行、保序去重；非字符串输入返回 []（空清单视为
    「未配置可用模型」，由业务侧如实处理，页面不强拦）。
    """
    if not isinstance(raw, str):
        return []
    items: List[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if text and text not in items:
            items.append(text)
    return items


def _as_model_list(models: Any) -> List[str]:
    """数据层 models 字段 → 模型名清单（容读：list / JSON 串 / 多行串 / None）。

    list/tuple 逐项 str 化去空；字符串先试 JSON 解析（MP-D 若存 JSON 串），
    失败再按多行文本解析；其余类型返回 []。顺序保留、去重。
    """
    if isinstance(models, (list, tuple)):
        items: List[str] = []
        for m in models:
            text = str(m or "").strip()
            if text and text not in items:
                items.append(text)
        return items
    if isinstance(models, str):
        text = models.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return _parse_models_text(text)
        if isinstance(parsed, (list, tuple)):
            return _as_model_list(parsed)
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
        return []
    return []


def _format_models_text(models: Any) -> str:
    """模型清单 → text_area 展示文本（每行一个）。"""
    return "\n".join(_as_model_list(models))


def _provider_options(providers: List[Dict[str, Any]]) -> Dict[str, int]:
    """「名称（#id·状态）→ id」左列单选映射（radio 纯文本，不需转义）。

    状态后缀如实标注：is_default → 「·默认」，未启用 → 「·停用」；同名供应商
    由 #id 保证标签唯一。数据层返回顺序即展示顺序（默认项是否置顶归数据层）。
    """
    options: Dict[str, int] = {}
    for p in providers:
        pid = int(p.get("id") or 0)
        name = str(p.get("name") or f"供应商#{pid}")
        suffix = ""
        if p.get("is_default"):
            suffix += "·默认"
        if not p.get("enabled", True):
            suffix += "·停用"
        options[f"{name}（#{pid}{suffix}）"] = pid
    return options


def _normalize_test_result(result: Any) -> Tuple[bool, str]:
    """连通性测试返回值容错归一 → (ok, detail)（纯函数，不抛异常）。

    容形态（llm_providers_db.test_provider_connectivity 契约为
    {"ok": bool, "status_code": int|None, "latency_ms": int, "model": str|None,
    "error": str|None}；其余三种主流形态也容）：
      * bool → ok 取原值，detail 给缺省文案；
      * (ok, detail) 二元组/list → 逐位取值；
      * dict → ok 认 ok / success / connected 键，detail 认 detail / message /
        error / msg 键；无 ok 系字段视为「不可判定」按失败转述；成功且无
        detail 键时用 model / latency_ms / status_code 拼可读摘要；
      * 其余（None/字符串/数字等）→ 失败＋形态说明。
    """
    if isinstance(result, bool):
        return result, ("供应商连通成功。" if result else "供应商连通失败。")
    if isinstance(result, (tuple, list)) and len(result) == 2:
        ok, detail = result
        return bool(ok), str(detail or "").strip() or "无细节。"
    if isinstance(result, dict):
        ok = result.get("ok")
        if ok is None:
            ok = result.get("success")
        if ok is None:
            ok = result.get("connected")
        detail = str(
            result.get("detail") or result.get("message")
            or result.get("error") or result.get("msg") or ""
        ).strip()
        if ok is None:
            return False, detail or "连通测试返回不含 ok/success 字段，无法判定。"
        if ok and not detail:
            parts = []
            if result.get("model"):
                parts.append(f"模型 {result['model']}")
            if result.get("latency_ms") is not None:
                parts.append(f"{result['latency_ms']}ms")
            if result.get("status_code") is not None:
                parts.append(f"HTTP {result['status_code']}")
            if parts:
                return True, " · ".join(str(p) for p in parts)
        return bool(ok), detail or ("供应商连通成功。" if ok else "供应商连通失败。")
    return False, f"连通测试返回了无法识别的形态（{type(result).__name__}）。"


def _edit_form_error(name: Any, base_url: Any, api_key: Any) -> Optional[str]:
    """保存前表单校验（纯函数）：名称/Base URL/API Key 必填、URL 须 http(s)。

    名称 / Base URL / API Key 必填是数据层硬约束（create_provider 拒空、
    update_provider 对空 api_key 整体拒绝），表单侧先拦给可读文案；
    模型清单允许为空（连通测试会如实报「无法发起连通性测试」）。合法返回 None。
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        return "供应商名称必填。"
    clean_url = str(base_url or "").strip()
    if not clean_url:
        return "Base URL 必填（如 https://open.bigmodel.cn/api/paas/v4）。"
    low = clean_url.lower()
    if not low.startswith(_BASE_URL_SCHEMES):
        return "Base URL 须以 http:// 或 https:// 开头。"
    if not str(api_key or "").strip():
        return "API Key 必填（数据层硬约束；明文存储，仅词典管理员可见）。"
    return None


# ============================================
# 编辑面板状态机（跨 rerun 的 widget 缓冲同步）
# ============================================

def _sync_edit_buffer(target: Any, provider: Optional[Dict[str, Any]]) -> None:
    """编辑目标变更时整体重写字段缓冲（widget 实例化前写 session 即为初值）。

    target 是「编辑目标哨兵」：既有供应商为 int pid，新建模式为 _EDIT_TARGET_NEW。
    provider 为 None（新建）时全部置空。同名 key（llm_name 等）被 st.* 控件
    复用，写入须发生在控件实例化之前（本函数只在 render 早期调用）。
    切换目标同时复位明文开关与删除确认，避免跨供应商泄漏状态。
    """
    if st.session_state.get(_EDIT_MARKER) == target:
        return
    st.session_state[_EDIT_MARKER] = target
    st.session_state["llm_name"] = str((provider or {}).get("name") or "")
    st.session_state["llm_base_url"] = str((provider or {}).get("base_url") or "")
    api_format = str((provider or {}).get("api_format") or "openai")
    if api_format not in API_FORMATS:
        api_format = "openai"
    st.session_state["llm_api_format"] = api_format
    st.session_state["llm_api_key"] = str((provider or {}).get("api_key") or "")
    st.session_state["llm_models"] = _format_models_text(
        (provider or {}).get("models")
    )
    st.session_state["llm_enabled"] = bool((provider or {}).get("enabled", True))
    st.session_state["llm_is_default"] = bool((provider or {}).get("is_default"))
    st.session_state["llm_show_key"] = False
    st.session_state["llm_confirm_delete"] = False
    st.session_state["llm_new_model"] = ""


# ============================================
# 数据层调用点（MP-D 契约假设集中在这四个小函数，签名出入只改这里）
# ============================================

def _list_providers() -> List[Dict[str, Any]]:
    """供应商清单（fail-closed：数据层未就绪/异常/异常形态一律 []）。"""
    if llm_providers_db is None:
        return []
    try:
        providers = llm_providers_db.list_providers()
    except Exception as e:  # noqa: BLE001 —— 数据层理论不抛，防御性兜一层
        logger.warning(f"list_providers 意外失败: {e}")
        return []
    if not isinstance(providers, list):
        logger.warning(f"list_providers 返回异常形态: {type(providers).__name__}")
        return []
    return [p for p in providers if isinstance(p, dict)]


def _save_provider(pid: int, name: str, base_url: str, api_format: str,
                   api_key: str, models: List[str], enabled: bool,
                   is_default: bool, current: Optional[Dict[str, Any]] = None,
                   created_by: Optional[int] = None) -> Tuple[bool, int, str]:
    """保存（新建 pid<=0 / 更新 pid>0）→ (ok, new_id, note)。

    口径对齐 llm_providers_db 实契约（见模块 docstring）：
      * 新建走 create_provider（新行恒 enabled=1 / is_default=0），随后按表单
        开关补 set_enabled(False) / set_default；主操作（建档）失败才返回
        ok=False，后续补齐失败以 note 如实转述（行已建成，不能谎报全败）；
      * 更新先对库内现值（current）做差量 —— update_provider 白名单不含
        is_default，且「无变更」返回 False，先比可免「没改也报错」；
      * 「取消默认」无数据层操作（默认只能转移），以 note 引导。
    异常折叠为失败不抛（页面转 st.error，详见服务端日志）。
    """
    if llm_providers_db is None:
        return False, 0, "数据层 llm_providers_db 未就绪。"
    try:
        if pid <= 0:
            new_id = int(llm_providers_db.create_provider(
                name=name, base_url=base_url, api_format=api_format,
                api_key=api_key, models=models, created_by=created_by,
            ) or 0)
            if new_id <= 0:
                return False, 0, ""
            note = ""
            if not enabled:
                llm_providers_db.set_enabled(new_id, False)
            if is_default:
                if llm_providers_db.set_default(new_id):
                    if not enabled:
                        note = ("已设为默认但处于停用态：默认供应商须启用才会在 "
                                "AI 功能中生效。")
                else:
                    note = "已建档，但「设为默认」未生效：请稍后在本页重设。"
            return True, new_id, note
        current = current or {}
        updates: Dict[str, Any] = {}
        if name != str(current.get("name") or ""):
            updates["name"] = name
        if base_url != str(current.get("base_url") or ""):
            updates["base_url"] = base_url
        if api_format != str(current.get("api_format") or ""):
            updates["api_format"] = api_format
        if api_key != str(current.get("api_key") or ""):
            updates["api_key"] = api_key
        if models != _as_model_list(current.get("models")):
            updates["models"] = models
        if enabled != bool(current.get("enabled", True)):
            updates["enabled"] = enabled
        if updates and not llm_providers_db.update_provider(pid, **updates):
            return False, 0, ""
        note = ""
        if current.get("is_default") and not is_default:
            note = ("默认标记不能直接取消：把另一家供应商「设为默认」后，"
                    "默认会自动转移过去。")
        elif is_default and not current.get("is_default"):
            if llm_providers_db.set_default(pid):
                if not enabled:
                    note = ("已设为默认但处于停用态：默认供应商须启用才会在 "
                            "AI 功能中生效。")
            else:
                note = "字段已保存，但「设为默认」未生效（默认未变）：请重试。"
        return True, 0, note
    except Exception as e:  # noqa: BLE001 —— 防御性转译，不崩页面
        logger.warning(f"保存供应商失败（pid={pid}, name={name!r}）: {e}")
        return False, 0, ""


def _delete_provider(pid: int) -> bool:
    """物理删除供应商（软硬删口径见模块 docstring）；异常折叠为 False。"""
    if llm_providers_db is None:
        return False
    try:
        return bool(llm_providers_db.delete_provider(pid))
    except Exception as e:  # noqa: BLE001 —— 防御性转译
        logger.warning(f"delete_provider 意外失败（pid={pid}）: {e}")
        return False


def _test_provider(pid: int) -> Tuple[bool, str]:
    """连通性测试 → (ok, detail)；数据层未就绪/异常折叠为失败文案。"""
    if llm_providers_db is None:
        return False, "数据层 llm_providers_db 未就绪，无法发起连通测试。"
    try:
        return _normalize_test_result(
            llm_providers_db.test_provider_connectivity(pid)
        )
    except Exception as e:  # noqa: BLE001 —— 网络层异常如实转述
        logger.warning(f"test_provider_connectivity 意外失败（pid={pid}）: {e}")
        return False, f"连通测试过程出现异常：{e}"


# ============================================
# 渲染：左列（供应商列表）
# ============================================

def _render_provider_list(providers: List[Dict[str, Any]]) -> int:
    """左列：标题 + 供应商单选 + 「＋ 添加供应商」按钮；返回当前选中 pid。

    选中态记在 st.session_state[_SELECTED_KEY]；清单变化导致旧选中项消失时
    回落到首项（新建模式下选中项仅作「取消新建」后的落点）。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>📋 供应商列表</h3>", unsafe_allow_html=True)
    options = _provider_options(providers)
    selected_pid = 0
    if options:
        labels = list(options.keys())
        prev_pid = st.session_state.get(_SELECTED_KEY)
        if prev_pid not in options.values():
            prev_pid = None
        index = list(options.values()).index(prev_pid) if prev_pid else 0
        # 旧 label 不在新清单（重命名/删除后的残留态）时复位单选，防 KeyError
        stale_label = st.session_state.get("llm_provider_pick")
        if stale_label is not None and stale_label not in labels:
            del st.session_state["llm_provider_pick"]
        picked = st.radio(
            "选择供应商", labels, index=index, key="llm_provider_pick",
            help="括号内为供应商 id 与状态（·默认 / ·停用）。",
        )
        selected_pid = int(options.get(picked, 0))
        st.session_state[_SELECTED_KEY] = selected_pid
        st.caption(f"共 {len(options)} 家供应商；·默认 / ·停用为状态后缀。")
    else:
        st.session_state[_SELECTED_KEY] = 0
        st.info("尚无供应商：点下方「＋ 添加供应商」录入第一家。")

    if st.button("＋ 添加供应商", key="llm_add_provider",
                 use_container_width=True, type="primary"):
        st.session_state[_CREATING_KEY] = True
        st.session_state[_EDIT_MARKER] = None  # 强制编辑缓冲对「新建」重新同步
    return selected_pid


# ============================================
# 渲染：右列（编辑面板）
# ============================================

def _render_status_card(provider: Optional[Dict[str, Any]], creating: bool) -> None:
    """编辑面板头卡：名称（转义）＋ 启用/默认徽章（新建模式给占位说明）。"""
    if creating:
        st.markdown(
            f"<div style='{get_card_style()}'><strong>新建供应商</strong>"
            f"<p style='margin:6px 0 0 0;color:#4a5568;'>填写完成后点「保存」"
            f"入库；保存后即可「测试连通」。</p></div>",
            unsafe_allow_html=True,
        )
        return
    pid = int((provider or {}).get("id") or 0)
    name = str((provider or {}).get("name") or f"供应商#{pid}")
    badges = []
    if (provider or {}).get("is_default"):
        badges.append(_badge("默认", "#2b6cb0"))
    if (provider or {}).get("enabled", True):
        badges.append(_badge("启用", "#2f855a"))
    else:
        badges.append(_badge("停用", "#718096"))
    st.markdown(
        f"<div style='{get_card_style()}'><strong>编辑供应商 #{pid}："
        f"{_esc(name)}</strong> {' '.join(badges)}"
        f"<p style='margin:6px 0 0 0;color:#4a5568;'>Base URL："
        f"{_esc((provider or {}).get('base_url') or '—')}</p></div>",
        unsafe_allow_html=True,
    )


def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span）。text 为调用方给的固定枚举文案（不含 UGC）。"""
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'padding:1px 10px;border-radius:10px;font-size:0.78em;'
        f'margin-left:4px;">{text}</span>'
    )


def _render_models_block() -> None:
    """模型清单块：text_area 批量编辑（每行一个）＋「＋ 添加模型」单条追加。

    「＋ 添加模型」走 on_click 回调：回调在下一轮脚本执行前运行，此时
    llm_models / llm_new_model 两个 widget 尚未实例化，可安全改写其
    session 状态（脚本内对已实例化 widget 赋值会抛 StreamlitAPIException）；
    回调不能调 st.warning 等渲染件，校验结果经 llm_add_model_msg 落地。
    """
    st.text_area(
        "模型列表（每行一个模型名）",
        key="llm_models",
        height=120,
        help="该供应商下可供 AI 功能挑选的模型白名单；直接在文本域批量编辑，"
             "或用下方「＋ 添加模型」单条追加。",
        placeholder="glm-4\ndeepseek-chat",
    )
    add_col, btn_col = st.columns([3, 1])
    with add_col:
        st.text_input("添加单个模型", key="llm_new_model",
                      placeholder="如 glm-4-plus")
    with btn_col:
        st.markdown("")  # 与输入框底部对齐的占位
        st.button("＋ 添加模型", key="llm_add_model",
                  use_container_width=True, on_click=_on_add_model)
    msg = st.session_state.pop("llm_add_model_msg", None)
    if isinstance(msg, (tuple, list)) and len(msg) == 2:
        kind, text = msg
        (st.success if kind == "ok" else st.warning)(str(text))
    current = _as_model_list(st.session_state.get("llm_models", ""))
    if current:
        st.caption("当前模型清单：" + _esc("、".join(current)))
    else:
        st.caption("清单为空：连通测试与业务调用将无模型可选。")


def _on_add_model() -> None:
    """「＋ 添加模型」on_click 回调：把 llm_new_model 追加进 llm_models 缓冲。

    回调阶段（下一轮脚本实例化 widget 之前）改写 widget 键状态是 Streamlit
    官方允许的唯一时机；校验失败也经 llm_add_model_msg 带回脚本渲染。
    """
    new_name = str(st.session_state.get("llm_new_model") or "").strip()
    if not new_name:
        st.session_state["llm_add_model_msg"] = (
            "warn", "请先在左侧输入框填写模型名。")
        return
    current = _as_model_list(st.session_state.get("llm_models", ""))
    if new_name in current:
        st.session_state["llm_add_model_msg"] = (
            "warn", f"模型「{new_name}」已在清单中。")
        return
    current.append(new_name)
    st.session_state["llm_models"] = _format_models_text(current)
    st.session_state["llm_new_model"] = ""
    st.session_state["llm_add_model_msg"] = ("ok", f"已添加模型「{new_name}」。")


def _handle_save(selected_pid: int, creating: bool,
                 provider: Optional[Dict[str, Any]],
                 me: Dict[str, Any]) -> None:
    """「保存」：表单校验 → guards 中央闸门 → create/update → flash + rerun。"""
    name = str(st.session_state.get("llm_name") or "").strip()
    base_url = str(st.session_state.get("llm_base_url") or "").strip()
    api_format = str(st.session_state.get("llm_api_format") or "openai")
    api_key = str(st.session_state.get("llm_api_key") or "")
    models = _parse_models_text(str(st.session_state.get("llm_models") or ""))
    enabled = bool(st.session_state.get("llm_enabled", True))
    is_default = bool(st.session_state.get("llm_is_default", False))

    error = _edit_form_error(name, base_url, api_key)
    if error:
        st.error(error)
        return
    if api_format not in API_FORMATS:
        st.error(f"API 格式须为 {' / '.join(API_FORMATS)} 之一。")
        return
    try:
        require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    try:
        created_by = int(me.get("id") or 0) or None
    except (TypeError, ValueError):
        created_by = None
    ok, new_id, note = _save_provider(
        0 if creating else selected_pid, name, base_url, api_format,
        api_key, models, enabled, is_default,
        current=None if creating else provider, created_by=created_by,
    )
    if not ok:
        st.error("保存未生效：可能名称重复、参数被数据层拒绝或数据库不可用"
                 "（详见服务端日志）。")
        return
    st.session_state[_CREATING_KEY] = False
    st.session_state[_EDIT_MARKER] = None  # 保存后强制按新记录重同步缓冲
    if creating and new_id:
        st.session_state[_SELECTED_KEY] = new_id
        flash = f"已创建供应商「{name}」（id={new_id}）。"
    else:
        flash = f"已保存供应商「{name}」的配置。"
    st.session_state[_FLASH_KEY] = ("warn" if note else "ok", flash + note)
    logger.info(f"模型供应商已保存（pid={new_id or selected_pid}, name={name!r}, "
                f"default={is_default}, enabled={enabled}）")
    st.rerun()


def _handle_delete(selected_pid: int, providers: List[Dict[str, Any]]) -> None:
    """「删除」：两步确认（勾选框）→ guards → 物理 DELETE → 落到剩余首项。"""
    if not st.session_state.get("llm_confirm_delete"):
        st.warning("删除是物理 DELETE 且不可恢复：请先勾选「我确认物理删除」。")
        return
    try:
        require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    if not _delete_provider(selected_pid):
        st.error("删除未生效：供应商可能已不存在或数据库不可用（详见服务端日志）。")
        return
    remaining = [int(p.get("id") or 0) for p in providers
                 if int(p.get("id") or 0) != selected_pid]
    st.session_state[_CREATING_KEY] = False
    st.session_state[_SELECTED_KEY] = remaining[0] if remaining else 0
    st.session_state[_EDIT_MARKER] = None
    st.session_state[_FLASH_KEY] = ("ok", f"已删除供应商 #{selected_pid}"
                                          "（物理删除，配置可随时重建）。")
    logger.info(f"模型供应商已物理删除（pid={selected_pid}）")
    st.rerun()


def _handle_test(selected_pid: int, creating: bool) -> None:
    """「测试连通」：新建未保存先提示；已保存则调数据层并转述结果。"""
    if creating:
        st.info("新供应商尚未保存：请先「保存」，再测试连通。")
        return
    if selected_pid <= 0:
        st.info("尚无供应商可测试：请先「＋ 添加供应商」并保存。")
        return
    with st.spinner("正在探测供应商连通性……"):
        ok, detail = _test_provider(selected_pid)
    if ok:
        st.success(f"✓ 连通成功：{detail}")
    else:
        st.error(f"✗ 连通失败：{detail}")


def _render_edit_panel(selected_pid: int, providers: List[Dict[str, Any]],
                       creating: bool, me: Dict[str, Any]) -> None:
    """右列编辑面板：头卡 + 字段区 + 模型清单 + 开关 + 三按钮 + 取消新建。"""
    provider: Optional[Dict[str, Any]] = None
    if not creating:
        provider = next(
            (p for p in providers if int(p.get("id") or 0) == selected_pid), None
        )
        if provider is None:
            # 无供应商 / 选中项已被删除 / 尚未点选：不渲染空壳表单
            if providers:
                st.info("左侧选择一家供应商，或点「＋ 添加供应商」新建。")
            return

    _sync_edit_buffer(_EDIT_TARGET_NEW if creating else selected_pid, provider)
    _render_status_card(provider, creating)

    st.text_input("名称", key="llm_name", max_chars=120,
                  help="供应商显示名（如 智谱 / DeepSeek / 内网网关）。")
    st.text_input("Base URL", key="llm_base_url",
                  help="API 根地址，须以 http(s):// 开头（如 "
                       "https://open.bigmodel.cn/api/paas/v4）。")
    st.selectbox(
        "API 格式", list(API_FORMATS), key="llm_api_format",
        format_func=lambda f: API_FORMAT_LABELS.get(f, f),
        help="openai=OpenAI 兼容 chat.completions；anthropic=Anthropic 原生。",
    )
    # type 参数按上一轮的明文开关取值：开关在下方，state 已随 rerun 可读
    show_key = bool(st.session_state.get("llm_show_key", False))
    st.text_input(
        "API Key", key="llm_api_key",
        type="default" if show_key else "password",
        help="必填（数据层硬约束）。管理决策：明文存储于数据库，仅词典管理员"
             "可见；页面默认遮蔽，用下方「👁 显示明文」开关临时核对。"
             "保存后不会打进服务端日志。",
    )
    st.toggle("👁 显示明文", key="llm_show_key",
              help="仅在当前页面回显明文，便于核对；不改变存储形态。")

    st.markdown(f"<h4 style='{HEADER_H3}'>🧾 模型清单</h4>", unsafe_allow_html=True)
    _render_models_block()

    toggle_col1, toggle_col2 = st.columns(2)
    with toggle_col1:
        st.toggle("启用（enabled）", key="llm_enabled",
                  help="关闭只是下线不删除，配置保留可随时重新启用。")
    with toggle_col2:
        st.toggle("设为默认供应商（is_default）", key="llm_is_default",
                  help="AI 功能（释义生成等）默认使用标为默认的供应商。")

    st.markdown("")
    save_col, del_col, test_col = st.columns(3)
    with save_col:
        if st.button("💾 保存", key="llm_save", type="primary",
                     use_container_width=True):
            _handle_save(selected_pid, creating, provider, me)
    with del_col:
        st.checkbox("我确认物理删除（不可恢复）", key="llm_confirm_delete")
        if st.button("🗑 删除", key="llm_delete", use_container_width=True):
            _handle_delete(selected_pid, providers)
    with test_col:
        st.markdown("")  # 与保存按钮底部对齐的占位
        if st.button("🔌 测试连通", key="llm_test", use_container_width=True):
            _handle_test(selected_pid, creating)

    if creating:
        st.markdown("")
        if st.button("取消新建", key="llm_cancel"):
            st.session_state[_CREATING_KEY] = False
            st.session_state[_EDIT_MARKER] = None  # 回落编辑选中供应商前重同步
            st.rerun()


# ============================================
# 页面入口
# ============================================

def render_model_settings_page() -> None:
    """「🤖 模型供应商」页面入口（规范 §6-4：role gate 在函数入口）。

    权限纵深防御（仅词典管理员）：会话纯函数 _is_model_admin（六角色 +
    过渡 admin 兼判）不过时再查库 has_role 兜底；两层都不过只渲染拦截
    提示。数据层未就绪（MP-D 并行交付窗口）降级为提示，不崩页面。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录。")
        return
    if not _is_model_admin(me) and not _db_confirms_model_admin(me):
        st.error("⛔ 模型供应商管理仅词典管理员可用。")
        return

    st.title("🤖 模型供应商")
    st.caption("管理 LLM 模型供应商，配置后在释义生成等 AI 功能中使用。")

    if llm_providers_db is None:
        st.warning(
            "数据层 src/llm_providers_db.py 未就绪（模块缺失）：本页暂无法"
            "读写供应商配置。请联系集成方确认数据层已交付。"
        )
        return

    flash = st.session_state.pop(_FLASH_KEY, None)
    if isinstance(flash, (tuple, list)) and len(flash) == 2:
        kind, text = flash
        renderer = st.success if kind == "ok" else (
            st.warning if kind == "warn" else st.error
        )
        renderer(str(text))

    providers = _list_providers()

    left_col, right_col = st.columns([1, 3])
    with left_col:
        selected_pid = _render_provider_list(providers)
    with right_col:
        # creating 在左列之后读取：「＋ 添加供应商」按钮就在左列内 —— 若在
        # 分列前取值，点击当轮右栏还拿不到刚置位的标志，表单会晚一轮才出现
        creating = bool(st.session_state.get(_CREATING_KEY))
        _render_edit_panel(selected_pid, providers, creating, me)
