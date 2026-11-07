"""dict_admin_pages 纯逻辑层测试（批次 2 Agent F，施工规范 §5）。

页面尚未接线 app.py（集成步骤负责），故按批次 2 契约只测纯逻辑：
  * GUIDE 结构契约：四段式齐（purpose/principle/data_source/steps/notes）、
    label 以 📖 前缀、steps ≥ 3 —— 集成时原样并入 PAGE_GUIDES["dict_admin"]；
  * 角色门纯函数 _is_dict_admin：过渡期 admin / roles 含 dict_admin / 无 user
    三态 + fail-closed 边界（非 dict、非序列 roles、大小写不宽容）；
  * HTML 转义 _esc、枚举 CSV 解析 _parse_enum_csv、比率/不确定度展示口径；
  * 展示映射与数据层枚举保持同步（PROJECT_ROLES / APPLIES_TO / VALUE_TYPES）。

批次 8 Agent W 增补（上传通道）：_validate_upload（扩展名/MIME 白名单 + 大小）
与 _upload_target_path（内容寻址落盘路径，tmp_path 实写验证）；GUIDE 注明
上传通道开通。

不要求 AppTest（未接线）；本文件不连数据库（import 各数据层模块不触发连接）。
"""
import hashlib
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import dict_admin_db, org_db  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    ANCHOR_LABELS,
    GUIDE,
    PROJECT_ROLE_LABELS,
    VALUE_TYPE_LABELS,
    _esc,
    _format_rate,
    _format_uncertainty,
    _is_dict_admin,
    _parse_enum_csv,
    _upload_target_path,
    _validate_upload,
    render_dict_admin_page,
)


# ============================================
# GUIDE 结构契约（集成并入 PAGE_GUIDES 的前提）
# ============================================

def test_guide_contract_fields():
    """四段式五键齐备且 label 以 📖 前缀（施工规范 §5 通用约定）。"""
    assert isinstance(GUIDE, dict)
    for key in ("label", "purpose", "principle", "data_source", "steps", "notes"):
        assert key in GUIDE, f"GUIDE 缺少 {key}"
    assert GUIDE["label"].startswith("📖")
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


def test_guide_covers_three_tabs():
    """步骤/说明要覆盖本模块三个 tab（驾驶舱/成员/定制属性）。"""
    joined = " ".join(GUIDE["steps"] + GUIDE["notes"])
    assert "驾驶舱" in joined
    assert "项目成员" in joined
    assert "定制属性" in joined


# ============================================
# 角色门纯函数 _is_dict_admin（三态 + fail-closed 边界）
# ============================================

def test_is_dict_admin_no_user():
    """无 user / 非 dict 一律不放行。"""
    assert _is_dict_admin(None) is False
    assert _is_dict_admin({}) is False
    assert _is_dict_admin("admin") is False
    assert _is_dict_admin(42) is False
    assert _is_dict_admin(["admin"]) is False


def test_is_dict_admin_transitional_admin_role():
    """过渡期：会话 role == 'admin' 视为兼有 dict_admin。"""
    assert _is_dict_admin({"id": 1, "role": "admin"}) is True
    assert _is_dict_admin({"id": 1, "role": "admin", "roles": []}) is True


def test_is_dict_admin_roles_contains_dict_admin():
    """六角色会话快照：roles 含 dict_admin 放行（list/tuple/set 皆可）。"""
    assert _is_dict_admin({"id": 2, "role": "viewer",
                           "roles": ["dict_admin"]}) is True
    assert _is_dict_admin({"id": 2, "role": "reviewer",
                           "roles": ("reviewer", "dict_admin")}) is True
    assert _is_dict_admin({"id": 2, "roles": {"dict_admin"}}) is True


def test_is_dict_admin_denied_states():
    """其他角色 / roles 不含 dict_admin / 缺键不放行。"""
    assert _is_dict_admin({"id": 3, "role": "reviewer"}) is False
    assert _is_dict_admin({"id": 3, "role": "viewer",
                           "roles": ["viewer", "annotator"]}) is False
    assert _is_dict_admin({"id": 3, "roles": ["sys_admin"]}) is False
    assert _is_dict_admin({"id": 3}) is False


def test_is_dict_admin_fail_closed_types_and_case():
    """roles 非序列 / 大小写不符一律不放行（枚举在库中恒为小写字面量）。"""
    assert _is_dict_admin({"id": 4, "roles": "dict_admin"}) is False  # 字符串非序列白名单
    assert _is_dict_admin({"id": 4, "roles": ["DICT_ADMIN"]}) is False
    assert _is_dict_admin({"id": 4, "role": "Admin"}) is False
    assert _is_dict_admin({"id": 4, "roles": None}) is False


# ============================================
# HTML 转义与解析/展示口径纯函数
# ============================================

def test_esc_escapes_markup_quotes_and_ampersand():
    assert _esc("<b>&") == "&lt;b&gt;&amp;"
    assert _esc('a"b') == "a&quot;b"
    assert _esc("a'b") == "a&#x27;b"
    assert _esc("普通中文") == "普通中文"


def test_esc_stringifies_non_str_values():
    assert _esc(123) == "123"
    assert _esc(None) == "None"
    assert _esc("<img src=x>") == "&lt;img src=x&gt;"


def test_parse_enum_csv_basic_and_chinese_comma():
    assert _parse_enum_csv("语域, 教材分级，频级") == ["语域", "教材分级", "频级"]
    assert _parse_enum_csv("a,b,c") == ["a", "b", "c"]


def test_parse_enum_csv_strips_dedupes_and_drops_empty():
    assert _parse_enum_csv(" a , a , b ") == ["a", "b"]
    assert _parse_enum_csv(" , , ") == []
    assert _parse_enum_csv("") == []


def test_parse_enum_csv_non_str_input():
    assert _parse_enum_csv(None) == []
    assert _parse_enum_csv(["a", "b"]) == []  # 表单只接受逗号分隔文本
    assert _parse_enum_csv(123) == []


def test_format_rate_and_uncertainty_display():
    assert _format_rate(None) == "—"
    assert _format_rate(0) == "0.0%"
    assert _format_rate(0.5) == "50.0%"
    assert _format_rate(1) == "100.0%"
    assert _format_rate("bad") == "—"
    assert _format_uncertainty(None) == "—"
    assert _format_uncertainty(0.1234) == "0.12"
    assert _format_uncertainty("x") == "—"


# ============================================
# 展示映射与数据层枚举同步（防枚举扩展后中文映射漏项）
# ============================================

def test_label_maps_cover_data_layer_enums():
    assert set(PROJECT_ROLE_LABELS) == set(org_db.PROJECT_ROLES)
    assert set(ANCHOR_LABELS) == set(dict_admin_db.APPLIES_TO)
    assert set(VALUE_TYPE_LABELS) == set(dict_admin_db.VALUE_TYPES)


# ============================================
# 入口签名契约
# ============================================

def test_render_entry_is_callable():
    assert callable(render_dict_admin_page)


# ============================================
# 上传通道（批次 8 Agent W）：准入校验与落盘路径纯函数
# ============================================

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
_JPG_BYTES = b"\xff\xd8\xff\xe0\x00" + b"fake-jpeg-body"
_MP3_BYTES = b"ID3\x04\x00\x00\x00" + b"fake-mp3-body"
_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4-body"


def test_validate_upload_accepts_whitelisted():
    """白名单扩展名 + 对应 MIME + 合法大小 → None（放行）。"""
    assert _validate_upload("a.png", 1024, "image/png") is None
    assert _validate_upload("b.jpg", 1, "image/jpeg") is None
    assert _validate_upload("c.jpeg", 10, "image/jpeg") is None
    assert _validate_upload("d.mp3", 2048, "audio/mpeg") is None
    assert _validate_upload("e.mp4", 5 * 1024 * 1024, "video/mp4") is None
    assert _validate_upload("F.PNG", 7, "image/png") is None  # 扩展名大小写不敏感
    assert _validate_upload("g.MP3", 7, "audio/mp3") is None  # mp3 非标准 MIME 别名


def test_validate_upload_rejects_bad_extension():
    """白名单外扩展名 / 无扩展名 / 未选文件 → 可读错误文案，不抛异常。"""
    assert "不支持" in _validate_upload("a.gif", 10, "image/gif")
    assert "不支持" in _validate_upload("a.exe", 10, "application/octet-stream")
    assert "不支持" in _validate_upload("noext", 10, "image/png")
    assert "未选择" in _validate_upload("", 10, "image/png")
    assert "未选择" in _validate_upload(None, 10, None)
    assert "未选择" in _validate_upload("   ", 10, "image/png")


def test_validate_upload_rejects_mime_mismatch():
    """MIME 缺失或与扩展名不对应 → 拒绝（防改名伪装）。"""
    assert "MIME" in _validate_upload("a.png", 10, "video/mp4")
    assert "MIME" in _validate_upload("a.jpg", 10, "image/png")
    assert "MIME" in _validate_upload("a.mp3", 10, "")
    assert "MIME" in _validate_upload("a.mp4", 10, None)
    assert "MIME" in _validate_upload("a.png", 10, "image/gif")


def test_validate_upload_rejects_bad_size():
    """空文件 / 脏大小 / 超 50MB → 拒绝；恰好 50MB 放行（边界 ≤）。"""
    assert "空文件" in _validate_upload("a.png", 0, "image/png")
    assert "空文件" in _validate_upload("a.png", -5, "image/png")
    assert "大小不可读" in _validate_upload("a.png", "bad", "image/png")
    assert "50MB" in _validate_upload("a.png", 50 * 1024 * 1024 + 1, "image/png")
    assert _validate_upload("a.png", 50 * 1024 * 1024, "image/png") is None


def test_upload_target_path_content_addressed(tmp_path):
    """落盘路径 = {base}/data/media/{kind}/YYYYMM/{sha256 前 16 位}{嗅探后缀}。"""
    month = datetime.now().strftime("%Y%m")
    sha16 = hashlib.sha256(_PNG_BYTES).hexdigest()[:16]
    target = _upload_target_path("image", _PNG_BYTES, str(tmp_path))
    assert target == os.path.join(
        str(tmp_path), "data", "media", "image", month, f"{sha16}.png",
    )
    # 内容寻址确定性：同内容同路径（重复上传覆盖同一文件，与 sha256 去重一致）
    assert target == _upload_target_path("image", _PNG_BYTES, str(tmp_path))


def test_upload_target_path_sniffs_kind_dirs_and_ext(tmp_path):
    """目录段按 kind，后缀按内容魔数（jpeg→.jpg / mp3→.mp3 / mp4→.mp4）。"""
    month = datetime.now().strftime("%Y%m")
    cases = [
        ("image", _JPG_BYTES, ".jpg"),
        ("audio", _MP3_BYTES, ".mp3"),
        ("video", _MP4_BYTES, ".mp4"),
    ]
    for kind, payload, ext in cases:
        sha16 = hashlib.sha256(payload).hexdigest()[:16]
        assert _upload_target_path(kind, payload, str(tmp_path)) == os.path.join(
            str(tmp_path), "data", "media", kind, month, f"{sha16}{ext}",
        )


def test_upload_target_path_falls_back_to_kind_ext(tmp_path):
    """魔数嗅探不出 → 按资产形态用规范后缀兜底（png/mp3/mp4）。"""
    blob = b"not-a-known-magic"
    assert _upload_target_path("image", blob, str(tmp_path)).endswith(".png")
    assert _upload_target_path("audio", blob, str(tmp_path)).endswith(".mp3")
    assert _upload_target_path("video", blob, str(tmp_path)).endswith(".mp4")


def test_upload_target_path_fail_closed_on_bad_input(tmp_path):
    """kind 非法 / data 非 bytes 类 → 返回 ''（falsy），不抛异常。"""
    assert _upload_target_path("bogus", _PNG_BYTES, str(tmp_path)) == ""
    assert _upload_target_path(None, _PNG_BYTES, str(tmp_path)) == ""
    assert _upload_target_path("image", "text-not-bytes", str(tmp_path)) == ""
    assert _upload_target_path("image", 123, str(tmp_path)) == ""
    assert _upload_target_path("image", None, str(tmp_path)) == ""


def test_upload_target_path_writable_and_register_relative(tmp_path):
    """返回路径可直接落盘（mkdir parents exist_ok）；相对 base 即登记用仓库相对路径。"""
    target = _upload_target_path("image", _PNG_BYTES, str(tmp_path))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(_PNG_BYTES)
    assert os.path.isfile(target)
    rel = os.path.relpath(target, str(tmp_path))
    assert rel == os.path.join(
        "data", "media", "image", datetime.now().strftime("%Y%m"),
        f"{hashlib.sha256(_PNG_BYTES).hexdigest()[:16]}.png",
    )


def test_guide_notes_cover_upload_channel():
    """批次 8 承诺：GUIDE 注明上传通道开通（白名单/50MB/落盘口径/双轨保留）。"""
    joined = " ".join(GUIDE["steps"] + GUIDE["notes"])
    assert "上传" in joined
    assert "50MB" in joined
    assert "data/media" in joined
    assert "服务器路径" in joined  # 双轨保留
