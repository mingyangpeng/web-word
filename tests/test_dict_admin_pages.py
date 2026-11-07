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

批次 8 Agent G6 增补（出版导出 tab / G6 闸门执行页）：
  * G6 三卡摘要纯函数（DB/文件系统探测以可注入函数或 tmp_path 驱动）：
    _g6_license_summary（resource_registry 在场/逐行 license 审计，缺表/探测
    失败灰注占位）、_g6_style_summary（style.yaml 在场，全缺灰注占位）、
    _g6_backup_summary（exports 最近快照 + mysqldump 最近文件，缺则灰注）；
  * 闸门判定纯函数 _g6_gate_open / _g6_gate_blockers / _g6_license_passed
    （占位与未过同拦 published、不拦内部快照的口径）；
  * _advance_export_status 单步流转（假 cursor 驱动：单向流转表 + 乐观并发
    守卫）；快照按钮闸门 mock（guards 拒绝时不触 build_content_snapshot）。

不要求 AppTest（未接线）；本文件不连数据库（import 各数据层模块不触发连接，
G6 摘要与渲染层用例以注入函数 / monkeypatch 假对象驱动）。
"""
import hashlib
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import dict_admin_db, org_db  # noqa: E402
import src.dict_admin_pages as dp  # noqa: E402
from src.dict_admin_pages import (  # noqa: E402
    ANCHOR_LABELS,
    EXPORT_STATUS_LABELS,
    G6_FAILED,
    G6_PASSED,
    G6_PLACEHOLDER,
    GUIDE,
    PROJECT_ROLE_LABELS,
    VALUE_TYPE_LABELS,
    _advance_export_status,
    _esc,
    _format_rate,
    _format_uncertainty,
    _g6_backup_summary,
    _g6_checklist,
    _g6_gate_blockers,
    _g6_gate_open,
    _g6_license_passed,
    _g6_license_summary,
    _g6_style_summary,
    _is_dict_admin,
    _parse_enum_csv,
    _render_exports_flow,
    _render_snapshot_builder,
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


# ============================================
# 出版导出 G6 闸门执行页（批次 8 Agent G6）
# ============================================

def test_guide_notes_cover_publication_tab():
    """批次 8 承诺：GUIDE 注明出版导出 tab（G6/占位口径/单向流转/内部快照）。"""
    joined = " ".join(GUIDE["steps"] + GUIDE["notes"] + [GUIDE["purpose"]])
    assert "出版导出" in joined
    assert "G6" in joined
    assert "published" in joined
    assert "revoked" in joined
    assert "内部快照" in joined


def test_export_status_labels_cover_enum():
    """export_batches 三态中文映射齐（ready/published/revoked）。"""
    assert set(EXPORT_STATUS_LABELS) == {"ready", "published", "revoked"}


# --- G6 ① 许可终检（resource_registry 逐行 license 审计） ---

def test_g6_license_placeholder_when_table_missing():
    """表未建 → 灰注占位「资源登记未启用」（不编绿灯）。"""
    check = _g6_license_summary(exists_fn=lambda: False)
    assert check["status"] == G6_PLACEHOLDER
    assert "资源登记未启用" in check["detail"]


def test_g6_license_placeholder_when_probe_fails():
    """库不可用（探测 None/抛异常）→ 占位，不误报已过。"""
    assert _g6_license_summary(exists_fn=lambda: None)["status"] == G6_PLACEHOLDER

    def _boom():
        raise RuntimeError("db down")

    assert _g6_license_summary(exists_fn=_boom)["status"] == G6_PLACEHOLDER


def test_g6_license_passed_when_all_licensed():
    """逐行 license 非空 → 已过，行数如实展示。"""
    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=lambda: (7, 0))
    assert check["status"] == G6_PASSED
    assert "7" in check["detail"]


def test_g6_license_passed_vacuous_on_empty_table():
    """表在场 0 行 → 审计空过（已过，0 行如实注明）。"""
    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=lambda: (0, 0))
    assert check["status"] == G6_PASSED
    assert "0 行" in check["detail"]


def test_g6_license_failed_when_missing_license_rows():
    """license 空值行 >0 → 未过（无许可资源不得出版），计数进 detail。"""
    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=lambda: (4, 1))
    assert check["status"] == G6_FAILED
    assert "1/4" in check["detail"]


def test_g6_license_placeholder_when_stats_raise():
    """表在场但审计失败 → 按占位处理（不编绿灯）。"""
    def _boom():
        raise RuntimeError("bad sql")

    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=_boom)
    assert check["status"] == G6_PLACEHOLDER


# --- G6 ② 体例终检（style.yaml 在场检查） ---

def test_g6_style_passed_when_style_yaml_present(tmp_path):
    """候选路径任一在场 style.yaml → 已过（路径如实展示）。"""
    style = tmp_path / "style.yaml"
    style.write_text("version: v1\n", encoding="utf-8")
    check = _g6_style_summary(candidates=[str(style)])
    assert check["status"] == G6_PASSED
    assert "style.yaml" in check["detail"]


def test_g6_style_placeholder_when_absent(tmp_path):
    """全部候选缺位 → 灰注占位「体例工单未建」。"""
    check = _g6_style_summary(candidates=[str(tmp_path / "nope.yaml")])
    assert check["status"] == G6_PLACEHOLDER
    assert "体例工单未建" in check["detail"]


def test_g6_style_default_candidates_derive_from_repo_root(tmp_path, monkeypatch):
    """缺省候选 = 模块常量相对路径拼仓库根（_MEDIA_UPLOAD_BASE 可注入验证）。"""
    monkeypatch.setattr(dp, "_MEDIA_UPLOAD_BASE", str(tmp_path))
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "style.yaml").write_text("version: v1\n", encoding="utf-8")
    check = _g6_style_summary()
    assert check["status"] == G6_PASSED
    assert "configs/style.yaml" in check["detail"] or "configs\\style.yaml" in (
        check["detail"])


# --- G6 ③ 备份新鲜（exports 最近快照 + mysqldump 最近文件） ---

def test_g6_backup_passed_with_both_evidences(tmp_path):
    """快照目录 + mysqldump 文件都在 → 已过，两个最近时间如实展示。"""
    exports = tmp_path / "exports"
    data = tmp_path / "data"
    exports.mkdir()
    data.mkdir()
    snap = exports / "snapshot-20261107-000000"
    snap.mkdir()
    dump = data / "dump.sql"
    dump.write_text("-- dump", encoding="utf-8")
    os.utime(snap, (1700000000, 1700000000))
    os.utime(dump, (1700000100, 1700000100))
    check = _g6_backup_summary(export_root=exports, data_root=data)
    assert check["status"] == G6_PASSED
    assert "最近内容域快照" in check["detail"]
    assert "最近 mysqldump" in check["detail"]


def test_g6_backup_gray_note_when_mysqldump_missing(tmp_path):
    """只有快照、无 mysqldump → 已过但卡内灰注（运维备份线未接入）。"""
    exports = tmp_path / "exports"
    data = tmp_path / "data"
    (exports / "snapshot-20261107-120000").mkdir(parents=True)
    data.mkdir()
    check = _g6_backup_summary(export_root=exports, data_root=data)
    assert check["status"] == G6_PASSED
    assert "mysqldump 备份未探测到" in check["detail"]


def test_g6_backup_passed_on_dump_alone(tmp_path):
    """只有 mysqldump 文件（无快照）→ 备份证据在场即已过，快照位如实为 —。"""
    data = tmp_path / "data"
    data.mkdir()
    (data / "backup.sql").write_text("-- dump", encoding="utf-8")
    check = _g6_backup_summary(
        export_root=tmp_path / "exports", data_root=data)
    assert check["status"] == G6_PASSED
    assert "—" in check["detail"]


def test_g6_backup_placeholder_when_no_evidence(tmp_path):
    """两类备份证据全缺（含目录不存在）→ 占位。"""
    check = _g6_backup_summary(
        export_root=tmp_path / "exports", data_root=tmp_path / "data")
    assert check["status"] == G6_PLACEHOLDER
    assert "尚无备份证据" in check["detail"]


def test_g6_backup_ignores_non_snapshot_entries(tmp_path):
    """exports 下非 snapshot-* 条目不算快照证据（口径：只认快照落盘目录）。"""
    exports = tmp_path / "exports"
    data = tmp_path / "data"
    (exports / "not-a-snapshot").mkdir(parents=True)
    data.mkdir()
    assert _g6_backup_summary(
        export_root=exports, data_root=data)["status"] == G6_PLACEHOLDER


# --- G6 闸门判定（三项全过才放行 published） ---

def _check(key, status):
    titles = {"license": "许可终检", "style": "体例终检", "backup": "备份新鲜"}
    return {"key": key, "status": status, "title": titles[key], "detail": "d"}


def test_g6_checklist_order_and_shape():
    """三卡顺序固定：许可 → 体例 → 备份；各卡键齐、状态合法。"""
    checks = _g6_checklist(
        exists_fn=lambda: False,
        stats_fn=lambda: (0, 0),
        style_candidates=["/nonexistent/style.yaml"],
        export_root="/nonexistent/exports",
        data_root="/nonexistent/data",
    )
    assert [c["key"] for c in checks] == ["license", "style", "backup"]
    for c in checks:
        assert set(c) == {"key", "status", "title", "detail"}
        assert c["status"] in (G6_PASSED, G6_PLACEHOLDER, G6_FAILED)


def test_g6_gate_open_only_when_all_passed():
    """三项全过 → 放行；任一占位/未过 → 拦下并列出「标题：徽章名」。"""
    all_passed = [_check("license", G6_PASSED),
                  _check("style", G6_PASSED),
                  _check("backup", G6_PASSED)]
    assert _g6_gate_open(all_passed) is True
    assert _g6_gate_blockers(all_passed) == []

    for key, status, text in [
        ("license", G6_PLACEHOLDER, "许可终检：占位"),
        ("style", G6_PLACEHOLDER, "体例终检：占位"),
        ("backup", G6_FAILED, "备份新鲜：未过"),
    ]:
        checks = [dict(c) for c in all_passed]
        for c in checks:
            if c["key"] == key:
                c["status"] = status
        assert _g6_gate_open(checks) is False
        assert _g6_gate_blockers(checks) == [text]


def test_g6_license_passed_flag_is_single_check():
    """license_passed 只看许可单项（快照 license_checked 旗标口径，非全闸门）。"""
    assert _g6_license_passed([_check("license", G6_PASSED),
                               _check("style", G6_PLACEHOLDER)]) is True
    assert _g6_license_passed([_check("license", G6_PLACEHOLDER),
                               _check("style", G6_PASSED)]) is False
    assert _g6_license_passed([]) is False  # 缺卡 fail-closed


# --- 快照状态单步流转（单向流转表 + 乐观并发守卫，假 cursor 驱动） ---

class _FakeCursor:
    """get_db_cursor 假体：记录 SQL/参数，rowcount 可设，可注入异常。"""

    def __init__(self, rowcount=1, error=None):
        self.rowcount = rowcount
        self.error = error
        self.executed = []

    def execute(self, sql, params=None):
        if self.error is not None:
            raise self.error
        self.executed.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_advance_export_status_single_step_flows(monkeypatch):
    """流转表内的单步生效（UPDATE 带 WHERE status=当前态 的乐观守卫）。"""
    fake = _FakeCursor(rowcount=1)
    monkeypatch.setattr(dp, "get_db_cursor", lambda: fake)
    assert _advance_export_status(3, "ready", "published") is True
    sql, params = fake.executed[0]
    assert "UPDATE export_batches" in sql
    assert params == ("published", 3, "ready")
    assert _advance_export_status(3, "ready", "revoked") is True


def test_advance_export_status_optimistic_guard(monkeypatch):
    """rowcount=0（状态已被他人变更/行不在）→ False。"""
    monkeypatch.setattr(dp, "get_db_cursor", lambda: _FakeCursor(rowcount=0))
    assert _advance_export_status(3, "ready", "published") is False


def test_advance_export_status_rejects_outside_flow_table(monkeypatch):
    """单向流转表外（回退/跳级/同态）一律拒绝，不触库。"""
    fake = _FakeCursor(rowcount=1)
    monkeypatch.setattr(dp, "get_db_cursor", lambda: fake)
    for frm, to in [("published", "ready"), ("revoked", "ready"),
                    ("ready", "draft"), ("published", "published"),
                    ("bogus", "ready")]:
        assert _advance_export_status(3, frm, to) is False, (frm, to)
    assert fake.executed == []


def test_advance_export_status_rejects_bad_id_and_db_error(monkeypatch):
    """id 非法 / cursor 异常 → False（降级不抛）。"""
    monkeypatch.setattr(
        dp, "get_db_cursor",
        lambda: _FakeCursor(rowcount=1, error=RuntimeError("db down")))
    assert _advance_export_status("abc", "ready", "published") is False
    assert _advance_export_status(0, "ready", "published") is False
    assert _advance_export_status(-1, "ready", "published") is False
    assert _advance_export_status(None, "ready", "published") is False
    assert _advance_export_status(3, "ready", "published") is False  # db down


# --- 快照按钮闸门 mock（guards 拒绝 → 不触 build_content_snapshot） ---

class _StubCol:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubSt:
    """st 假体：button 行为可配，记录调用与消息（页面转述可断言）。

    clicked=True 时全部按钮可点；click_label 给定时只有点 label 含该子串的
    按钮返回 True（模拟真实页面上「未点的按钮不触发」）。
    """

    def __init__(self, clicked=True, click_label=None):
        self.clicked = clicked
        self.click_label = click_label
        self.buttons = []
        self.messages = []

    def columns(self, spec, **kwargs):
        return [_StubCol() for _ in range(len(spec)) if True] if isinstance(
            spec, (list, tuple)) else [_StubCol() for _ in range(spec)]

    def button(self, *args, **kwargs):
        label = args[0] if args else ""
        self.buttons.append((label, kwargs))
        if self.click_label is not None:
            return self.click_label in label
        return self.clicked

    def selectbox(self, *args, **kwargs):
        opts = kwargs.get("options") or (args[1] if len(args) > 1 else [])
        return opts[0] if opts else None

    def markdown(self, *args, **kwargs):
        self.messages.append(("markdown", args[0] if args else ""))

    def caption(self, *args, **kwargs):
        self.messages.append(("caption", args[0] if args else ""))

    def info(self, *args, **kwargs):
        self.messages.append(("info", args[0] if args else ""))

    def warning(self, *args, **kwargs):
        self.messages.append(("warning", args[0] if args else ""))

    def success(self, *args, **kwargs):
        self.messages.append(("success", args[0] if args else ""))

    def error(self, *args, **kwargs):
        self.messages.append(("error", args[0] if args else ""))

    def rerun(self):
        self.messages.append(("rerun", ""))


_ME = {"id": 1, "username": "chief", "role": "viewer", "roles": ["dict_admin"]}


def test_snapshot_builder_gate_blocks_on_permission_error(monkeypatch):
    """guards.require_dict_admin 抛 PermissionError → st.error 转述，构建不被调用。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)

    def _deny():
        raise PermissionError("仅词典管理员可执行词典数据写操作。")

    spy_args = []

    def _spy(actor=None, license_checked=False):
        spy_args.append((actor, license_checked))
        return {"ok": True, "batch_id": 1}

    monkeypatch.setattr(dp.guards, "require_dict_admin", _deny)
    monkeypatch.setattr(dp.export_center, "build_content_snapshot", _spy)
    _render_snapshot_builder(True, _ME)
    assert spy_args == []  # 闸门拦下，快照机械未被触达
    assert any(kind == "error" and "仅词典管理员" in text
               for kind, text in stub.messages)


def test_snapshot_builder_passes_actor_and_license_flag(monkeypatch):
    """闸门通过 → build_content_snapshot(actor, license_checked=许可单项结论)。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    seen = {}

    def _spy(actor=None, license_checked=False):
        seen["actor"] = actor
        seen["license_checked"] = license_checked
        return {"ok": True, "batch_id": 9, "rows_total": 42,
                "zip_path": "data/exports/snapshot-x/content-snapshot-x.zip",
                "tables_included": ["definitions"], "tables_skipped": ["wordforms"]}

    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME)
    monkeypatch.setattr(dp.export_center, "build_content_snapshot", _spy)
    _render_snapshot_builder(False, _ME)  # 许可占位 → 内部快照旗标 False
    assert seen["actor"] == _ME
    assert seen["license_checked"] is False
    assert any(kind == "success" and "42" in text
               for kind, text in stub.messages)
    assert any("包含表" in text and "definitions" in text
               for kind, text in stub.messages if kind == "markdown")
    assert any("跳过" in text and "wordforms" in text
               for kind, text in stub.messages if kind == "markdown")


def test_snapshot_builder_reports_failure_without_raise(monkeypatch):
    """构建失败（ok=False）→ st.error 转述，不抛异常。"""
    stub = _StubSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME)
    monkeypatch.setattr(
        dp.export_center, "build_content_snapshot",
        lambda actor=None, license_checked=False: {"ok": False,
                                                   "error": "快照构建失败：boom"})
    _render_snapshot_builder(True, _ME)
    assert any(kind == "error" and "boom" in text
               for kind, text in stub.messages)


def test_exports_flow_publish_disabled_when_gate_not_open(monkeypatch):
    """G6 未全过 → published 按钮 disabled=True；撤销按钮不受闸门限制。"""
    stub = _StubSt(clicked=False)  # 不点击，只看按钮装配
    monkeypatch.setattr(dp, "st", stub)
    exports = [{"id": 3, "file_path": "data/exports/s3/x.zip", "rows_total": 9,
                "status": "ready", "created_at": "2026-11-07"}]
    _render_exports_flow(exports, gate_open=False,
                         blockers=["许可终检：占位", "体例终检：占位"])
    pub = next(kw for label, kw in stub.buttons if "published" in label)
    rev = next(kw for label, kw in stub.buttons if "撤销" in label)
    assert pub["disabled"] is True
    assert rev.get("disabled", False) is False  # 撤销不受 G6 闸门限制
    assert any(kind == "warning" and "许可终检：占位" in text
               for kind, text in stub.messages)
    assert stub.buttons  # 按钮已装配


def test_exports_flow_publish_enabled_and_calls_advance(monkeypatch):
    """G6 全过 → published 按钮可用；点击走 require_dict_admin + 单步流转 + rerun。"""
    stub = _StubSt(click_label="published")  # 只点 published，撤销按钮不触发
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME)
    calls = []

    def _advance(batch_id, frm, to):
        calls.append((batch_id, frm, to))
        return True

    monkeypatch.setattr(dp, "_advance_export_status", _advance)
    exports = [{"id": 3, "file_path": "data/exports/s3/x.zip", "rows_total": 9,
                "status": "ready", "created_at": "2026-11-07"}]
    _render_exports_flow(exports, gate_open=True, blockers=[])
    pub = next(kw for label, kw in stub.buttons if "published" in label)
    assert pub["disabled"] is False
    assert calls == [(3, "ready", "published")]
    assert any(kind == "rerun" for kind, _ in stub.messages)
