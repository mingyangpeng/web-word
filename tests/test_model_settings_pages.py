"""model_settings_pages 纯逻辑层测试（Agent MP-P）。

页面尚未接线 app.py（集成步骤负责），按纯层契约只测不依赖 DB 的部分：
  * GUIDE 结构契约：四段式齐（purpose/principle/data_source/steps/notes）、
    label 以 🤖 前缀、steps ≥ 3 —— 集成时原样并入 PAGE_GUIDES["model_settings"]；
  * 角色门纯函数 _is_model_admin 三态：过渡 role=='admin' / roles 含
    dict_admin / 都不满足，加 fail-closed 边界（非 dict、大小写不宽容、
    roles 字符串形态不放行）＋ _db_confirms_model_admin 实时兜底
    （monkeypatch users_db.has_role）；
  * HTML 转义 _esc、模型清单解析/回写（_parse_models_text /
    _as_model_list / _format_models_text）、左列选项映射 _provider_options；
  * 连通测试结果容错归一 _normalize_test_result（bool / 二元组 / dict /
    未知形态）与保存表单校验 _edit_form_error；
  * widget key 前缀扫描：模块源码内全部 st.* 的 key= 字面量与
    st.session_state 字面量一律 'llm_' 前缀、无 f-string 动态 key；
  * import 纪律：不 import app.py / llm_api.py；
  * 数据层缺位/桩件形态：llm_providers_db 为 None 时四个调用点
    fail-closed（[] / False / 提示文案），注入桩件时调用签名与返回
    归一路径正确（MP-D 交付前锁住本模块一侧的契约假设）。

本文件不连数据库（users_db.effective_six_roles 是纯会话计算；渲染层
不触发 —— Streamlit 控件仅 import 不实例化）。
"""
import inspect
import os
import re
import sys

import pytest

from src import users_db

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.model_settings_pages as mp  # noqa: E402
from src.model_settings_pages import (  # noqa: E402
    API_FORMATS,
    GUIDE,
    _as_model_list,
    _db_confirms_model_admin,
    _edit_form_error,
    _esc,
    _format_models_text,
    _is_model_admin,
    _normalize_test_result,
    _parse_models_text,
    _provider_options,
    render_model_settings_page,
)


# ============================================
# GUIDE 结构契约（集成并入 PAGE_GUIDES 的前提）
# ============================================

def test_guide_contract_fields():
    """四段式五键齐备且 label 以 🤖 前缀（施工规范 §5 通用约定）。"""
    assert isinstance(GUIDE, dict)
    for key in ("label", "purpose", "principle", "data_source", "steps", "notes"):
        assert key in GUIDE, f"GUIDE 缺少 {key}"
    assert GUIDE["label"].startswith("🤖")
    assert isinstance(GUIDE["purpose"], str) and GUIDE["purpose"].strip()


def test_guide_list_sections_nonempty_strings():
    """principle/data_source/steps/notes 都是非空字符串清单。"""
    for key in ("principle", "data_source", "steps", "notes"):
        section = GUIDE[key]
        assert isinstance(section, list) and section, f"GUIDE.{key} 应为非空 list"
        assert all(isinstance(item, str) and item.strip() for item in section), (
            f"GUIDE.{key} 应全为非空字符串"
        )


def test_guide_steps_at_least_three():
    """steps ≥ 3（契约硬指标）。"""
    assert len(GUIDE["steps"]) >= 3


def test_guide_mentions_key_decisions():
    """说明文档覆盖本批次管理决策：明文存储、物理删除、API 格式白名单。"""
    joined = " ".join(GUIDE["principle"] + GUIDE["notes"] + GUIDE["steps"])
    assert "明文" in joined  # API Key 明文存储口径
    assert "物理 DELETE" in joined  # 物理删除口径
    for fmt in API_FORMATS:
        assert fmt in joined, f"GUIDE 应提及 API 格式 {fmt}"


# ============================================
# 角色门（三态 + fail-closed + 实时兜底）
# ============================================

def test_role_gate_three_states():
    """admin 过渡放行 / roles 含 dict_admin 放行 / 其余不放行。"""
    # 态 1：过渡期内置 admin（legacy role 映射与显式兜底双保险）
    assert _is_model_admin({"role": "admin"}) is True
    # 态 2：六角色快照含 dict_admin（legacy role 列只是普通用户）
    assert _is_model_admin({"role": "viewer", "roles": ["dict_admin"]}) is True
    # 态 3：两者都不满足
    assert _is_model_admin({"role": "viewer", "roles": ["annotator"]}) is False


def test_role_gate_fail_closed_edges():
    """非 dict / 缺键 / 大小写不宽容 / roles 非序列形态一律不放行。"""
    assert _is_model_admin(None) is False
    assert _is_model_admin("admin") is False
    assert _is_model_admin({}) is False
    assert _is_model_admin({"id": 1}) is False  # 无 role 无 roles
    assert _is_model_admin({"role": "ADMIN"}) is False  # 大小写不宽容
    assert _is_model_admin({"role": "dict_admin"}) is False  # 非 legacy 枚举不折算
    assert _is_model_admin({"roles": "dict_admin"}) is False  # 字符串不是角色快照
    assert _is_model_admin({"roles": 42}) is False
    # 容器形态宽容度：list/tuple/set 都接受
    assert _is_model_admin({"roles": ("dict_admin",)}) is True
    assert _is_model_admin({"roles": {"dict_admin"}}) is True


def test_db_fallback_confirms(monkeypatch):
    """_db_confirms_model_admin：has_role 实时兜底，异常/无 id fail-closed。"""
    monkeypatch.setattr(
        users_db, "has_role",
        lambda uid, role: role == "dict_admin" and uid == 7,
    )
    assert _db_confirms_model_admin({"id": 7}) is True
    assert _db_confirms_model_admin({"id": 8}) is False
    assert _db_confirms_model_admin({}) is False  # 无 id 不查库
    assert _db_confirms_model_admin({"id": "x"}) is False  # id 脏值不查库

    def _boom(uid, role):
        raise RuntimeError("db down")

    monkeypatch.setattr(users_db, "has_role", _boom)
    assert _db_confirms_model_admin({"id": 7}) is False  # 库故障不崩角色门


# ============================================
# HTML 转义
# ============================================

def test_esc_escapes_html_and_quotes():
    """供应商名/模型名进 unsafe_allow_html 前必须过 _esc。"""
    assert _esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert _esc('<b class="x">智谱</b>') == "&lt;b class=&quot;x&quot;&gt;智谱&lt;/b&gt;"
    assert _esc("a&b") == "a&amp;b"
    assert _esc(None) == "None"  # 任意值 str() 后转义，不抛
    assert _esc(123) == "123"


# ============================================
# 模型清单解析 / 回写 / 左列选项映射
# ============================================

def test_parse_models_text():
    """text_area 文本 → 每行一个模型名：去空白、丢空行、保序去重。"""
    assert _parse_models_text("glm-4\ndeepseek-chat\n") == ["glm-4", "deepseek-chat"]
    assert _parse_models_text("  glm-4 \n\nglm-4\ndeepseek-chat") == [
        "glm-4", "deepseek-chat",
    ]
    assert _parse_models_text("") == []
    assert _parse_models_text(None) == []
    assert _parse_models_text(42) == []  # 非字符串不抛


def test_as_model_list_tolerant_forms():
    """数据层 models 字段容读：list / JSON 串 / 多行串 / 标量 / 脏值。"""
    assert _as_model_list(["a", " b ", "", "a"]) == ["a", "b"]
    assert _as_model_list(('x', 'y')) == ["x", "y"]
    assert _as_model_list('["glm-4", "glm-4", "deepseek-chat"]') == [
        "glm-4", "deepseek-chat",
    ]
    assert _as_model_list('"glm-4"') == ["glm-4"]  # JSON 标量串
    assert _as_model_list("glm-4\ndeepseek-chat") == [
        "glm-4", "deepseek-chat",
    ]  # 非 JSON 串按多行解析
    assert _as_model_list("") == []
    assert _as_model_list(None) == []
    assert _as_model_list(3.14) == []
    assert _as_model_list({"models": ["x"]}) == []  # dict 形态不猜


def test_format_models_text_roundtrip():
    """清单 → text_area 文本 → 解析回清单，往返一致。"""
    models = ["glm-4", "deepseek-chat", "qwen-max"]
    assert _format_models_text(models) == "glm-4\ndeepseek-chat\nqwen-max"
    assert _parse_models_text(_format_models_text(models)) == models
    assert _format_models_text(None) == ""


def test_provider_options_labels():
    """左列映射：#id 保证同名唯一，·默认/·停用 状态后缀如实标注。"""
    providers = [
        {"id": 2, "name": "智谱", "is_default": True, "enabled": True},
        {"id": 1, "name": "智谱", "is_default": False, "enabled": False},
        {"id": 3, "name": "DeepSeek", "is_default": False, "enabled": True},
    ]
    options = _provider_options(providers)
    assert list(options.values()) == [2, 1, 3]  # 数据层返回顺序即展示顺序
    assert "智谱（#2·默认）" in options
    assert "智谱（#1·停用）" in options
    assert "DeepSeek（#3）" in options
    # 缺名/缺布尔字段的兜底口径
    fallback = _provider_options([{"id": 9}])
    assert fallback == {"供应商#9（#9）": 9}


# ============================================
# 连通测试结果归一 / 保存表单校验
# ============================================

def test_normalize_test_result_shapes():
    """bool / 二元组 / dict（ok 系与 detail 系键）/ 未知形态四路归一。"""
    assert _normalize_test_result(True) == (True, "供应商连通成功。")
    assert _normalize_test_result(False) == (False, "供应商连通失败。")
    assert _normalize_test_result((True, "pong glm-4")) == (True, "pong glm-4")
    assert _normalize_test_result([False, "超时"]) == (False, "超时")
    assert _normalize_test_result({"ok": True, "detail": "模型 glm-4 可用"}) == (
        True, "模型 glm-4 可用",
    )
    assert _normalize_test_result({"success": False, "error": "401"}) == (False, "401")
    assert _normalize_test_result({"connected": True}) == (True, "供应商连通成功。")
    # llm_providers_db 实契约形态：成功且无 error 时用 model/latency/HTTP 拼摘要
    assert _normalize_test_result({
        "ok": True, "status_code": 200, "latency_ms": 35,
        "model": "glm-4", "error": None,
    }) == (True, "模型 glm-4 · 35ms · HTTP 200")
    # 失败时 error 文案原样转述（401/404/网络错误等）
    assert _normalize_test_result({
        "ok": False, "status_code": 401, "latency_ms": 12,
        "model": "glm-4", "error": "认证失败（HTTP 401）：API Key 无效或无权限",
    })[1] == "认证失败（HTTP 401）：API Key 无效或无权限"
    # 无 ok 系字段 → 不可判定按失败转述
    ok, detail = _normalize_test_result({"latency_ms": 12})
    assert ok is False and "无法判定" in detail
    # 完全未知的形态
    ok, detail = _normalize_test_result("sure")
    assert ok is False and "str" in detail
    ok, detail = _normalize_test_result(None)
    assert ok is False


def test_edit_form_error():
    """保存校验：名称/Base URL/API Key 必填、URL 须 http(s) 开头；清单可空。"""
    assert _edit_form_error("", "https://x", "k") is not None  # 名称必填
    assert _edit_form_error("  ", "https://x", "k") is not None
    assert _edit_form_error("智谱", "", "k") is not None  # Base URL 必填
    assert _edit_form_error("智谱", "ftp://x", "k") is not None  # scheme 白名单
    assert _edit_form_error("智谱", "open.bigmodel.cn", "k") is not None
    assert _edit_form_error("智谱", "https://x", "") is not None  # Key 必填（硬约束）
    assert _edit_form_error("智谱", "https://x", "  ") is not None
    assert _edit_form_error(
        "智谱", "https://open.bigmodel.cn/api/paas/v4", "sk-xxx") is None
    assert _edit_form_error("本地网关", "http://127.0.0.1:8000/v1", "k") is None


# ============================================
# widget key 前缀扫描 + import 纪律
# ============================================

_SOURCE = inspect.getsource(mp)
_WIDGET_KEY_RE = re.compile(r'key\s*=\s*"([^"]+)"')
_SESSION_KEY_RE = re.compile(
    r'st\.session_state(?:\.get\(|\.pop\(|\[)\s*"([^"]+)"'
)


def test_widget_keys_all_llm_prefixed():
    """模块内全部 st.* key= 字面量一律 'llm_' 前缀（widget 命名空间隔离）。"""
    keys = set(_WIDGET_KEY_RE.findall(_SOURCE))
    assert keys, "应扫描到 st.* 控件的 key=（页面为控件化表单）"
    offenders = [k for k in keys if not k.startswith("llm_")]
    assert not offenders, f"widget key 未用 llm_ 前缀: {offenders}"


def test_widget_keys_no_fstring_dynamic_keys():
    """无 f-string 动态 key（编辑缓冲走固定 key + session 同步，不造动态命名空间）。"""
    assert not re.search(r'key\s*=\s*f["\']', _SOURCE), "禁止 f-string 动态 key"


def test_widget_keys_core_inventory():
    """核心控件 key 在场（布局契约：列表/编辑面板/三按钮/两开关）。"""
    keys = set(_WIDGET_KEY_RE.findall(_SOURCE))
    for required in (
        "llm_provider_pick",   # 左列供应商单选
        "llm_add_provider",    # ＋ 添加供应商
        "llm_name",            # 名称
        "llm_base_url",        # Base URL
        "llm_api_format",      # API 格式
        "llm_api_key",         # API Key（password）
        "llm_show_key",        # 明文开关
        "llm_models",          # 模型清单 text_area
        "llm_add_model",       # ＋ 添加模型
        "llm_enabled",         # 启用 toggle
        "llm_is_default",      # 默认 toggle
        "llm_save",            # 保存
        "llm_delete",          # 删除
        "llm_confirm_delete",  # 删除两步确认
        "llm_test",            # 测试连通
    ):
        assert required in keys, f"缺核心 widget key: {required}"


def test_session_state_keys_all_llm_prefixed():
    """跨 rerun 状态键（含常量）也一律 llm_ 前缀，便于统一清理命名空间。"""
    literals = set(_SESSION_KEY_RE.findall(_SOURCE))
    offenders = [k for k in literals if not k.startswith("llm_")]
    assert not offenders, f"session key 未用 llm_ 前缀: {offenders}"
    for const in (mp._EDIT_MARKER, mp._FLASH_KEY, mp._SELECTED_KEY,
                  mp._CREATING_KEY):
        assert const.startswith("llm_"), f"session 常量 {const} 未用 llm_ 前缀"
    # 编辑目标哨兵是「值」不是键，不受前缀约束，但须与键常量区分开
    assert mp._EDIT_TARGET_NEW == "new"


def test_import_discipline_no_app_no_llm_api():
    """不 import app.py / llm_api.py（模块 docstring 声明的纪律）。"""
    import_lines = [ln.strip() for ln in _SOURCE.splitlines()
                    if re.match(r"^\s*(?:from|import)\s+", ln)]
    assert import_lines, "应存在 import 语句"
    for ln in import_lines:
        assert not re.search(r"\bapp\b", ln), f"禁止 import app: {ln}"
        assert "llm_api" not in ln, f"禁止 import llm_api: {ln}"
    assert render_model_settings_page is not None  # 入口函数在场


# ============================================
# 数据层调用点：缺位 fail-closed + 桩件契约
# ============================================

class _StubProvidersDB:
    """llm_providers_db 桩件：锁本模块一侧的调用签名与返回归一假设。

    形态对齐 MP-D 实契约：create_provider 不收 enabled/is_default（新行恒
    启用非默认）、update_provider 白名单不含 is_default、默认走 set_default。
    """

    def __init__(self):
        self.created = None
        self.updated = None
        self.deleted = None
        self.tested = None
        self.enabled_calls = []
        self.default_calls = []

    def list_providers(self):
        return [{"id": 1, "name": "智谱", "base_url": "https://x",
                 "api_format": "openai", "api_key": "k",
                 "models": ["glm-4"], "enabled": True, "is_default": False}]

    def create_provider(self, **kw):
        self.created = kw
        return 42

    def update_provider(self, pid, **kw):
        self.updated = (pid, kw)
        return True

    def set_enabled(self, pid, enabled):
        self.enabled_calls.append((pid, enabled))
        return True

    def set_default(self, pid):
        self.default_calls.append(pid)
        return True

    def delete_provider(self, pid):
        self.deleted = pid
        return True

    def test_provider_connectivity(self, pid):
        self.tested = pid
        return {"ok": True, "detail": "模型 glm-4 可用"}


def test_api_formats_sync_with_data_layer():
    """API 格式白名单与数据层同源（数据层在场时取其常量，缺位时本地兜底）。"""
    if mp.llm_providers_db is not None:
        assert mp.API_FORMATS == mp.llm_providers_db.API_FORMATS
    else:
        assert mp.API_FORMATS == ("openai", "anthropic")


def test_data_layer_missing_fail_closed():
    """数据层未交付（None）时四个调用点一律 fail-closed，不抛不崩。"""
    if mp.llm_providers_db is not None:
        pytest.skip("MP-D 数据层已交付，缺层形态不适用")
    assert mp._list_providers() == []
    assert mp._save_provider(0, "x", "https://a", "openai", "k",
                             ["m"], True, False) == (
        False, 0, "数据层 llm_providers_db 未就绪。")
    assert mp._save_provider(3, "x", "https://a", "openai", "k",
                             ["m"], True, False)[0] is False
    assert mp._delete_provider(3) is False
    ok, detail = mp._test_provider(3)
    assert ok is False and "未就绪" in detail


def test_data_layer_stub_contract(monkeypatch):
    """注入桩件：新建走 create_provider（kwargs + models 清单 + created_by）、
    开关补齐走 set_enabled / set_default；更新做差量后走 update_provider；
    删除/连通按 id；list 异常形态折叠 []。"""
    stub = _StubProvidersDB()
    monkeypatch.setattr(mp, "llm_providers_db", stub)

    # 新建：默认+启用 → create 一次，set_default 补一次，无 set_enabled
    ok, new_id, note = mp._save_provider(
        0, "智谱", "https://x", "openai", "k", ["glm-4"], True, True,
        created_by=5,
    )
    assert ok is True and new_id == 42 and note == ""
    assert stub.created == {"name": "智谱", "base_url": "https://x",
                            "api_format": "openai", "api_key": "k",
                            "models": ["glm-4"], "created_by": 5}
    assert stub.default_calls == [42] and stub.enabled_calls == []

    # 新建：停用+非默认 → create 后补 set_enabled(False)，不碰 set_default
    monkeypatch.setattr(stub, "create_provider", lambda **kw: 43)
    ok, new_id, note = mp._save_provider(
        0, "内网", "http://10.0.0.5/v1", "openai", "k", [], False, False)
    assert ok is True and new_id == 43 and note == ""
    assert stub.enabled_calls == [(43, False)] and stub.default_calls == [42]

    # 新建：默认但停用 → 设默认成功但给「须启用才生效」警示 note
    monkeypatch.setattr(stub, "create_provider", lambda **kw: 44)
    ok, new_id, note = mp._save_provider(
        0, "备件", "https://b", "anthropic", "k", ["claude"], False, True)
    assert ok is True and new_id == 44 and "停用" in note and "启用" in note

    # 更新：与库内现值全等 → 差量为空，不触 update_provider（免「未变更」误报）
    current = {"name": "智谱", "base_url": "https://x", "api_format": "openai",
               "api_key": "k", "models": ["glm-4"], "enabled": True,
               "is_default": False}
    ok, _, note = mp._save_provider(
        1, "智谱", "https://x", "openai", "k", ["glm-4"], True, False,
        current=current)
    assert ok is True and note == "" and stub.updated is None

    # 更新：改两字段（name/models）→ update_provider 只收差量白名单字段
    ok, _, note = mp._save_provider(
        1, "智谱新版", "https://x", "openai", "k", ["glm-4", "glm-4-plus"],
        True, False, current=current)
    assert ok is True and note == ""
    pid, kw = stub.updated
    assert pid == 1
    assert set(kw) == {"name", "models"}  # 未变字段不进白名单提交
    assert kw["name"] == "智谱新版" and kw["models"] == ["glm-4", "glm-4-plus"]

    # 更新：现值是默认而开关关掉 → 无取消接口，note 引导「转移」
    ok, _, note = mp._save_provider(
        1, "智谱", "https://x", "openai", "k", ["glm-4"], True, False,
        current=dict(current, is_default=True))
    assert ok is True and "转移" in note

    # 更新：非默认 → 默认 → set_default 补一刀
    ok, _, note = mp._save_provider(
        1, "智谱", "https://x", "openai", "k", ["glm-4"], True, True,
        current=current)
    assert ok is True and note == "" and stub.default_calls[-1] == 1

    assert mp._delete_provider(7) is True and stub.deleted == 7

    ok, detail = mp._test_provider(1)
    assert ok is True and detail == "模型 glm-4 可用" and stub.tested == 1

    providers = mp._list_providers()
    assert len(providers) == 1 and providers[0]["id"] == 1

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(stub, "list_providers", _boom)
    assert mp._list_providers() == []  # 数据层异常折叠为空清单


def test_data_layer_abnormal_shapes_folded(monkeypatch):
    """数据层返回异常形态（None/非 list/0/失败）时页面侧如实折叠。"""
    class _Weird:
        def list_providers(self):
            return None

        def create_provider(self, **kw):
            return 0  # 数据层失败口径（重名/非法参数）

        def update_provider(self, pid, **kw):
            return False

        def delete_provider(self, pid):
            return False

        def test_provider_connectivity(self, pid):
            return None

    monkeypatch.setattr(mp, "llm_providers_db", _Weird())
    assert mp._list_providers() == []  # None 折叠 []
    assert mp._save_provider(0, "x", "https://a", "openai", "k", [], True,
                             False) == (False, 0, "")
    assert mp._save_provider(3, "x", "https://a", "openai", "k", [], True,
                             False,
                             current={"name": "x", "base_url": "https://b",
                                      "api_key": "old"}) == (False, 0, "")
    assert mp._delete_provider(3) is False
    ok, detail = mp._test_provider(3)
    assert ok is False and detail  # None 返回归一为失败＋可读文案
