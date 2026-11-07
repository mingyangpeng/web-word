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

批次 11 Agent AV2 增补（G6 小尾巴收口：三卡灰注转硬检 + 资源登记块）：
  * 体例终检硬检：style.yaml 在场**且**含 style_version 字段 → 已过（展示
    体例版本；纯函数 _g6_style_version）；缺字段/缺文件 → 占位「体例文件
    未研制」；
  * 备份新鲜硬检：data/backups/ 树内最新 *.sql.gz/*.tar.gz（纯函数
    _g6_scan_backups，scripts/backup_db.sh 落地产物）为主证据，无产物 →
    占位「备份任务未运行」（快照≠灾备备份，仅快照也占位）；
  * 许可终检 0 行口径：「空过（未登记资源）」注明；
  * 资源登记块：纯函数 _registry_form_error（四项必填/超长）＋
    _render_registry_form / _render_resource_registry_section 渲染
    （_StubSt 扩展 text_input；guards 拒绝 → register_resource 不触达）。

FX4（R2 批次）增补：上传魔数一致性（_validate_upload 增 data= 形参，复用
_sniff_upload_ext 魔数逻辑）/ _coerce_value 日期真实日历校验与 text 长度上限
＋写值表单专用报错 / 建壳 chief 下拉去双重转义（R2-1）/ 驾驶舱取数失败内联
降级披露（_safe_cockpit_* ＋ _cockpit_db_ready 连通探测试题，R4-3）。

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
    _coerce_value,
    _esc,
    _format_rate,
    _format_uncertainty,
    _g6_backup_summary,
    _g6_checklist,
    _g6_gate_blockers,
    _g6_gate_open,
    _g6_license_passed,
    _g6_license_summary,
    _g6_scan_backups,
    _g6_style_summary,
    _g6_style_version,
    _is_dict_admin,
    _parse_enum_csv,
    _registry_form_error,
    _render_exports_flow,
    _render_registry_form,
    _render_registry_table,
    _render_resource_registry_section,
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


# --- G6 ① 许可终检（resource_registry 逐行 license 审计，批次 11 硬检口径） ---

def test_g6_license_placeholder_when_table_missing():
    """表未建（自举建表未生效）→ 灰注占位，不编绿灯。"""
    check = _g6_license_summary(exists_fn=lambda: False)
    assert check["status"] == G6_PLACEHOLDER
    assert "表未建" in check["detail"]


def test_g6_license_placeholder_when_probe_fails():
    """库不可用（探测 None/抛异常）→ 占位，不误报已过。"""
    assert _g6_license_summary(exists_fn=lambda: None)["status"] == G6_PLACEHOLDER

    def _boom():
        raise RuntimeError("db down")

    assert _g6_license_summary(exists_fn=_boom)["status"] == G6_PLACEHOLDER


def test_g6_license_passed_when_all_licensed():
    """逐行 license 非空 → 已过（✅ n 行），行数如实展示。"""
    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=lambda: (7, 0))
    assert check["status"] == G6_PASSED
    assert "7" in check["detail"]


def test_g6_license_passed_vacuous_on_empty_table():
    """表在场 0 行 → 审计空过（已过，「空过（未登记资源）」注明）。"""
    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=lambda: (0, 0))
    assert check["status"] == G6_PASSED
    assert "0 行" in check["detail"]
    assert "空过" in check["detail"]
    assert "未登记资源" in check["detail"]


def test_g6_license_failed_when_missing_license_rows():
    """license 空值行 >0 → 未过 ❌ n/m（无许可资源不得出版）。"""
    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=lambda: (4, 1))
    assert check["status"] == G6_FAILED
    assert "1/4" in check["detail"]


def test_g6_license_placeholder_when_stats_raise():
    """表在场但审计失败 → 按占位处理（不编绿灯）。"""
    def _boom():
        raise RuntimeError("bad sql")

    check = _g6_license_summary(exists_fn=lambda: True, stats_fn=_boom)
    assert check["status"] == G6_PLACEHOLDER


# --- G6 ② 体例终检（style.yaml 在场 + style_version 字段硬检，批次 11） ---

def test_g6_style_version_parser(tmp_path):
    """_g6_style_version：读不动（不存在/目录）→ None，不抛异常。"""
    assert _g6_style_version(str(tmp_path / "no-such-file.yaml")) is None
    assert _g6_style_version(str(tmp_path)) is None  # 目录 → OSError 折叠


def test_g6_style_passed_when_style_yaml_present(tmp_path):
    """style.yaml 在场且含 style_version → 已过，体例版本如实展示。"""
    style = tmp_path / "style.yaml"
    style.write_text("# 体例文件\nstyle_version: 1.0\ndefining_vocab: {}\n",
                     encoding="utf-8")
    check = _g6_style_summary(candidates=[str(style)])
    assert check["status"] == G6_PASSED
    assert "style.yaml" in check["detail"]
    assert "1.0" in check["detail"]


def test_g6_style_version_tolerates_quotes_and_comments(tmp_path):
    """style_version: "1.0"  /  值后行尾注释 → 版本值干净解析。"""
    style = tmp_path / "style.yaml"
    style.write_text('style_version: "2.1"  # 版本履历\n', encoding="utf-8")
    assert _g6_style_version(str(style)) == "2.1"
    style.write_text("style_version: 3  # 待编者核定\n", encoding="utf-8")
    assert _g6_style_version(str(style)) == "3"


def test_g6_style_placeholder_when_style_version_missing(tmp_path):
    """style.yaml 在场但缺 style_version 字段 → 占位（研制不完整）。"""
    style = tmp_path / "style.yaml"
    style.write_text("defining_vocab:\n  vocab_size: 2500\n", encoding="utf-8")
    check = _g6_style_summary(candidates=[str(style)])
    assert check["status"] == G6_PLACEHOLDER
    assert "style_version" in check["detail"]


def test_g6_style_placeholder_when_absent(tmp_path):
    """全部候选缺位 → 灰注占位「体例文件未研制」。"""
    check = _g6_style_summary(candidates=[str(tmp_path / "nope.yaml")])
    assert check["status"] == G6_PLACEHOLDER
    assert "体例文件未研制" in check["detail"]


def test_g6_style_default_candidates_derive_from_repo_root(tmp_path, monkeypatch):
    """缺省候选 = 模块常量相对路径拼仓库根（_MEDIA_UPLOAD_BASE 可注入验证）。"""
    monkeypatch.setattr(dp, "_MEDIA_UPLOAD_BASE", str(tmp_path))
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "style.yaml").write_text("style_version: 1.0\n", encoding="utf-8")
    check = _g6_style_summary()
    assert check["status"] == G6_PASSED
    assert "configs/style.yaml" in check["detail"] or "configs\\style.yaml" in (
        check["detail"])


# --- G6 ③ 备份新鲜（data/backups 灾备产物为主证据，批次 11 硬检口径） ---

def test_g6_backup_passed_with_backup_artifacts(tmp_path):
    """data/backups 有灾备产物（+ 快照也在）→ 已过，灾备路径与两时间展示。"""
    exports = tmp_path / "exports"
    backups = tmp_path / "data" / "backups" / "db"
    exports.mkdir(parents=True)
    backups.mkdir(parents=True)
    snap = exports / "snapshot-20261107-000000"
    snap.mkdir()
    dump = backups / "20261107-0215.sql.gz"
    dump.write_bytes(b"\x1f\x8b fake-gzip")
    os.utime(snap, (1700000000, 1700000000))
    os.utime(dump, (1700000100, 1700000100))
    check = _g6_backup_summary(
        export_root=exports, backups_root=tmp_path / "data" / "backups")
    assert check["status"] == G6_PASSED
    assert "最近灾备备份" in check["detail"]
    assert "20261107-0215.sql.gz" in check["detail"]
    assert "最近内容域快照" in check["detail"]


def test_g6_backup_passed_on_media_tar_alone(tmp_path):
    """只有 media/*.tar.gz（media 归档是同批产物之一）→ 已过，快照位如实为 —。"""
    backups = tmp_path / "data" / "backups" / "media"
    backups.mkdir(parents=True)
    tarball = backups / "20261107-0215-media.tar.gz"
    tarball.write_bytes(b"\x1f\x8b fake-gzip")
    check = _g6_backup_summary(
        export_root=tmp_path / "exports", backups_root=tmp_path / "data" / "backups")
    assert check["status"] == G6_PASSED
    assert "—" in check["detail"]


def test_g6_backup_placeholder_when_snapshot_only(tmp_path):
    """只有内容域快照、无灾备产物 → 占位「备份任务未运行」（快照≠灾备备份）。"""
    exports = tmp_path / "exports"
    (exports / "snapshot-20261107-120000").mkdir(parents=True)
    check = _g6_backup_summary(
        export_root=exports, backups_root=tmp_path / "data" / "backups")
    assert check["status"] == G6_PLACEHOLDER
    assert "备份任务未运行" in check["detail"]


def test_g6_backup_placeholder_when_no_evidence(tmp_path):
    """两类证据全缺（含目录不存在）→ 占位「备份任务未运行」。"""
    check = _g6_backup_summary(
        export_root=tmp_path / "exports", backups_root=tmp_path / "data" / "backups")
    assert check["status"] == G6_PLACEHOLDER
    assert "备份任务未运行" in check["detail"]


def test_g6_backup_ignores_non_snapshot_entries(tmp_path):
    """exports 下非 snapshot-* 条目不算快照证据（口径：只认快照落盘目录）。"""
    exports = tmp_path / "exports"
    (exports / "not-a-snapshot").mkdir(parents=True)
    assert _g6_backup_summary(
        export_root=exports,
        backups_root=tmp_path / "data" / "backups",
    )["status"] == G6_PLACEHOLDER


def test_g6_scan_backups_pure_scan(tmp_path):
    """_g6_scan_backups：跨 db/media 子目录取最新；无匹配/无目录 → (None, '')。"""
    backups = tmp_path / "data" / "backups"
    (backups / "db").mkdir(parents=True)
    (backups / "media").mkdir(parents=True)
    assert _g6_scan_backups(backups) == (None, "")  # 空树
    assert _g6_scan_backups(tmp_path / "nope") == (None, "")  # 目录不存在
    db_dump = backups / "db" / "20261107-0215.sql.gz"
    db_dump.write_bytes(b"x")
    media_tar = backups / "media" / "20261106-0215-media.tar.gz"
    media_tar.write_bytes(b"x")
    stray = backups / "db" / "notes.txt"
    stray.write_bytes(b"x")
    os.utime(db_dump, (1700000100, 1700000100))
    os.utime(media_tar, (1700000200, 1700000200))
    ts, rel = _g6_scan_backups(backups)
    assert ts == 1700000200.0  # 最新者胜（db 与 media 同权）
    assert rel == os.path.join("media", "20261106-0215-media.tar.gz")
    os.utime(db_dump, (1700000300, 1700000300))
    assert _g6_scan_backups(backups)[0] == 1700000300.0
    # 非灾备产物（.sql/.txt）不算数
    os.utime(stray, (1700009900, 1700009900))
    assert _g6_scan_backups(backups)[0] == 1700000300.0


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
        backups_root="/nonexistent/backups",
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
    text_values 按 widget key 提供文本输入值（批次 11 资源登记表单用），
    未配置的 key 返回 ''（模拟空表单）。
    """

    def __init__(self, clicked=True, click_label=None, text_values=None):
        self.clicked = clicked
        self.click_label = click_label
        self.text_values = dict(text_values or {})
        self.buttons = []
        self.messages = []

    def columns(self, spec, **kwargs):
        return [_StubCol() for _ in range(len(spec)) if True] if isinstance(
            spec, (list, tuple)) else [_StubCol() for _ in range(spec)]

    def text_input(self, *args, **kwargs):
        key = kwargs.get("key") or (args[0] if args else "")
        return self.text_values.get(key, "")

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

    def _advance(batch_id, frm, to, published_by=None):
        calls.append((batch_id, frm, to, published_by))
        return True

    monkeypatch.setattr(dp, "_advance_export_status", _advance)
    exports = [{"id": 3, "file_path": "data/exports/s3/x.zip", "rows_total": 9,
                "status": "ready", "created_at": "2026-11-07"}]
    _render_exports_flow(exports, gate_open=True, blockers=[])
    pub = next(kw for label, kw in stub.buttons if "published" in label)
    assert pub["disabled"] is False
    # R3-4b：published 流转随带当前会话用户 username（出版留痕）
    assert calls == [(3, "ready", "published", _ME["username"])]
    assert any(kind == "rerun" for kind, _ in stub.messages)


# --- 资源登记块（批次 11 AV2：D⑥ 数据面；表单校验 + 闸门 + 渲染降级） ---

def test_registry_form_error_requires_four_fields():
    """四项必填：任一缺失（空/纯空白/非 str）给出可读文案；license 文案点明纪律。"""
    assert "资源名称" in _registry_form_error("", "v", "c", "l")
    assert "资源版本" in _registry_form_error("n", "  ", "c", "l")
    assert "覆盖说明" in _registry_form_error("n", "v", None, "l")
    assert "许可（license）必填" in _registry_form_error("n", "v", "c", "")
    assert "D⑥ 许可纪律" in _registry_form_error("n", "v", "c", "   \t")
    assert _registry_form_error("n", "v", "c", "l") is None


def test_registry_form_error_rejects_overlong():
    """超长拒绝（上限与 registry_db 列宽一致：120/64/255/120）。"""
    assert "超长" in _registry_form_error("n" * 121, "v", "c", "l")
    assert "超长" in _registry_form_error("n", "v" * 65, "c", "l")
    assert "超长" in _registry_form_error("n", "v", "c" * 256, "l")
    assert "超长" in _registry_form_error("n", "v", "c", "l" * 121)
    assert _registry_form_error("n" * 120, "v" * 64, "c" * 255, "l" * 120) is None


def test_registry_form_gate_blocks_before_register(monkeypatch):
    """guards.require_dict_admin 拒绝 → st.error 转述，register_resource 不触达。"""
    stub = _StubSt(text_values={
        "pub_reg_name": "enTenTen21", "pub_reg_version": "2021",
        "pub_reg_coverage": "69,943 搭配", "pub_reg_license": "CC BY 4.0",
    })
    monkeypatch.setattr(dp, "st", stub)

    def _deny():
        raise PermissionError("仅词典管理员可执行词典数据写操作。")

    def _boom(*_a, **_k):
        raise AssertionError("闸门拦下后不得触达数据层")

    monkeypatch.setattr(dp.guards, "require_dict_admin", _deny)
    monkeypatch.setattr(dp.registry_db, "register_resource", _boom)
    _render_registry_form(_ME)
    assert any(kind == "error" and "仅词典管理员" in text
               for kind, text in stub.messages)


def test_registry_form_passes_form_values_and_actor(monkeypatch):
    """表单合法 → register_resource(四值, registered_by=username) + st.success。"""
    stub = _StubSt(text_values={
        "pub_reg_name": "enTenTen21", "pub_reg_version": "2021",
        "pub_reg_coverage": "69,943 搭配", "pub_reg_license": "CC BY 4.0",
    })
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME)
    seen = {}

    def _spy(name, version, coverage, license_text, registered_by=""):
        seen.update(name=name, version=version, coverage=coverage,
                    license_text=license_text, registered_by=registered_by)
        return 5

    monkeypatch.setattr(dp.registry_db, "register_resource", _spy)
    _render_registry_form(_ME)
    assert seen == {"name": "enTenTen21", "version": "2021",
                    "coverage": "69,943 搭配", "license_text": "CC BY 4.0",
                    "registered_by": "chief"}
    assert any(kind == "success" and "#5" in text
               for kind, text in stub.messages)


def test_registry_form_missing_fields_error_before_gate(monkeypatch):
    """表单缺必填 → st.error 拦在闸门之前（guards/register 都不触达）。"""
    stub = _StubSt(text_values={"pub_reg_name": "enTenTen21"})
    monkeypatch.setattr(dp, "st", stub)

    def _boom(*_a, **_k):
        raise AssertionError("表单未过校验不得触达闸门/数据层")

    monkeypatch.setattr(dp.guards, "require_dict_admin", _boom)
    monkeypatch.setattr(dp.registry_db, "register_resource", _boom)
    _render_registry_form(_ME)
    assert any(kind == "error" and "必填" in text
               for kind, text in stub.messages)


def test_registry_form_data_layer_failure_reports_error(monkeypatch):
    """数据层返回 0（校验拒绝/库不可用）→ st.error 转述，不抛异常。"""
    stub = _StubSt(text_values={
        "pub_reg_name": "enTenTen21", "pub_reg_version": "2021",
        "pub_reg_coverage": "69,943 搭配", "pub_reg_license": "CC BY 4.0",
    })
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.guards, "require_dict_admin", lambda: _ME)
    monkeypatch.setattr(dp.registry_db, "register_resource",
                        lambda *a, **k: 0)
    _render_registry_form(_ME)
    assert any(kind == "error" and "登记未生效" in text
               for kind, text in stub.messages)


def test_registry_section_lists_resources(monkeypatch):
    """有登记 → 只读表渲染（许可列如实展示）；资源来自 registry_db.list_resources。"""
    stub = _StubSt(clicked=False)  # 不点登记按钮，只看清单装配
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(
        dp.registry_db, "list_resources",
        lambda limit=50: [
            {"id": 2, "name": "enTenTen21<v2>", "version": "2021",
             "coverage": "69,943 搭配", "license": "CC BY 4.0",
             "registered_by": "chief", "created_at": "2026-11-07"},
            {"id": 1, "name": "OALD", "version": "第7版",
             "coverage": "996 全义项", "license": "授权协议",
             "registered_by": "", "created_at": "2026-11-06"},
        ],
    )
    _render_resource_registry_section(_ME)
    table_html = [text for kind, text in stub.messages if kind == "markdown"]
    assert any("enTenTen21&lt;v2&gt;" in t for t in table_html)  # 过 _esc
    assert any("CC BY 4.0" in t for t in table_html)


def test_registry_section_empty_state(monkeypatch):
    """无登记（list_resources 空表/库不可用返回 []）→ st.info 引导登记。"""
    stub = _StubSt(clicked=False)
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(dp.registry_db, "list_resources", lambda limit=50: [])
    _render_resource_registry_section(_ME)
    assert any(kind == "info" and "暂无登记资源" in text
               for kind, text in stub.messages)


def test_registry_section_list_failure_degrades(monkeypatch):
    """list_resources 抛异常 → 块内兜底为空清单（st.info），不拖垮出版 tab。"""
    stub = _StubSt(clicked=False)
    monkeypatch.setattr(dp, "st", stub)

    def _boom(limit=50):
        raise RuntimeError("boom")

    monkeypatch.setattr(dp.registry_db, "list_resources", _boom)
    _render_resource_registry_section(_ME)
    assert any(kind == "info" and "暂无登记资源" in text
               for kind, text in stub.messages)


def test_registry_table_renders_rows(monkeypatch):
    """_render_registry_table 纯装配：行值经 _esc 进表格 HTML。"""
    stub = _StubSt(clicked=False)
    monkeypatch.setattr(dp, "st", stub)
    _render_registry_table([
        {"id": 1, "name": "<OALD>", "version": "第7版",
         "coverage": "996 全义项", "license": "授权协议",
         "registered_by": "chief", "created_at": "2026-11-06"},
    ])
    html = [text for kind, text in stub.messages if kind == "markdown"]
    assert any("&lt;OALD&gt;" in t for t in html)
    assert any("996 全义项" in t for t in html)


# ============================================
# R2 批次（FX4）：上传魔数一致性 / 写值专用报错 / 驾驶舱降级披露
# ============================================

class _FormSt(_StubSt):
    """_StubSt 扩展：form/expander 上下文、number_input、metric 与 selectbox
    录制（写值表单与驾驶舱渲染用例）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = []
        self.selectboxes = []
        self.number_values = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def form(self, *args, **kwargs):
        self.messages.append(("form", args[0] if args else ""))
        return self

    def expander(self, *args, **kwargs):
        self.messages.append(("expander", args[0] if args else ""))
        return self

    def form_submit_button(self, *args, **kwargs):
        return self.clicked

    def number_input(self, *args, **kwargs):
        key = kwargs.get("key") or ""
        return self.number_values.get(key, kwargs.get("value", 0))

    def metric(self, label, value=None, **kwargs):
        self.metrics.append((label, value))
        return value

    def selectbox(self, *args, **kwargs):
        opts = kwargs.get("options") or (args[1] if len(args) > 1 else [])
        self.selectboxes.append((args[0] if args else "", list(opts)))
        return opts[0] if opts else None


def test_validate_upload_magic_number_consistency():
    """R2-2：内容魔数与扩展名一致性 —— image 声明须 PNG/JPEG 魔数（svg/
    script 伪装 png 落盘前被拦）；跨形态改名（PNG 数据顶 .mp3）同拦；
    audio/video 嗅探不出按资产形态兜底放行（不误伤合法文件）。"""
    assert _validate_upload("a.png", 100, "image/png", data=_PNG_BYTES) is None
    assert _validate_upload("a.jpeg", 100, "image/jpeg", data=_JPG_BYTES) is None
    # JPEG 数据顶 .png 名：同属 image 且魔数真实 → 放行（落盘后缀按嗅探 .jpg）
    assert _validate_upload("a.png", 100, "image/png", data=_JPG_BYTES) is None
    svg = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>"
    assert "文件内容与扩展名不符" in _validate_upload(
        "a.png", 100, "image/png", data=svg)
    assert "文件内容与扩展名不符" in _validate_upload(
        "a.jpg", 100, "image/jpeg", data=b"<script>alert(1)</script>")
    assert "文件内容与扩展名不符" in _validate_upload(
        "a.png", 100, "image/png", data=b"not-a-known-magic")
    # 跨形态改名：图像数据顶音/视频后缀 → 内容明确嗅探为其他形态 → 拒
    assert "文件内容与扩展名不符" in _validate_upload(
        "a.mp3", 100, "audio/mpeg", data=_PNG_BYTES)
    assert "文件内容与扩展名不符" in _validate_upload(
        "a.mp4", 100, "video/mp4", data=_MP3_BYTES)
    # audio/video 嗅探不出 → 放行（_upload_target_path 按形态兜底后缀）
    assert _validate_upload(
        "a.mp3", 100, "audio/mpeg", data=b"not-a-known-magic") is None
    assert _validate_upload(
        "a.mp4", 100, "video/mp4", data=b"\x00\x00\x00" + b"x" * 20) is None
    # data=None（既有调用方旧形态）跳过内容校验；非 bytes 内容拒
    assert _validate_upload("a.png", 100, "image/png") is None
    assert "内容不可读" in _validate_upload(
        "a.png", 100, "image/png", data="text-not-bytes")


def test_coerce_value_date_real_calendar():
    """R2-3：date 分支正则后再验真实日历日期 —— 2024-02-30 这类「格式对但
    日期不存在」返回 None；闰年 02-29 过；旧格式口径不变。"""
    assert _coerce_value("date", "2024-02-30") is None
    assert _coerce_value("date", "2023-02-29") is None   # 非闰年
    assert _coerce_value("date", "2024-13-01") is None
    assert _coerce_value("date", "2024-04-31") is None
    assert _coerce_value("date", "2024-02-29") == "2024-02-29"  # 闰年真实
    assert _coerce_value("date", "2024-12-31") == "2024-12-31"
    assert _coerce_value("date", "2024-2-3") is None     # 严格补零口径不变
    assert _coerce_value("date", "abc") is None
    assert _coerce_value("date", "") is None


def test_coerce_value_text_length_cap():
    """R2-3：text 分支对照 dict_admin_db.MAX_VALUE_TEXT_LEN 上限，超长返回
    None（数据层 set_value 同款上限的表单侧前移）；enum/bool 行为不变。"""
    cap = dict_admin_db.MAX_VALUE_TEXT_LEN
    assert cap == 10000
    assert _coerce_value("text", "x" * cap) == "x" * cap       # 边界 ≤ 放行
    assert _coerce_value("text", "x" * (cap + 1)) is None      # 超长拒
    assert _coerce_value("enum", "x" * (cap + 1)) == "x" * (cap + 1)
    assert _coerce_value("bool", "True") is True


def test_write_value_form_dedicated_date_errors(monkeypatch):
    """R2-3 专用报错二分：格式对但日期不存在 → 「日期不存在」；格式错 →
    「日期格式须为 YYYY-MM-DD」；文本超长 → 「文本超长」。"""
    field_date = {"id": 5, "code": "field_date", "name": "首发日期",
                  "applies_to": "word", "value_type": "date",
                  "required": False, "status": "active", "enum_values": []}

    def _render_date(monkeypatch, raw):
        stub = _FormSt(text_values={"dict_admin_val_date": raw})
        monkeypatch.setattr(dp, "st", stub)
        dp._render_write_value_form([field_date], _ME)
        return [text for kind, text in stub.messages if kind == "error"]

    errs = _render_date(monkeypatch, "2024-02-30")
    assert any("日期不存在" in t for t in errs)
    assert not any("日期格式须为" in t for t in errs)
    errs = _render_date(monkeypatch, "2024/02/30")
    assert any("日期格式须为 YYYY-MM-DD" in t for t in errs)
    assert not any("日期不存在" in t for t in errs)

    field_text = {"id": 6, "code": "field_text", "name": "备注",
                  "applies_to": "word", "value_type": "text",
                  "required": False, "status": "active", "enum_values": []}
    stub = _FormSt(text_values={
        "dict_admin_val_text": "x" * (dict_admin_db.MAX_VALUE_TEXT_LEN + 1)})
    monkeypatch.setattr(dp, "st", stub)
    dp._render_write_value_form([field_text], _ME)
    errs = [text for kind, text in stub.messages if kind == "error"]
    assert any("文本超长" in t and "10000" in t for t in errs)


def test_safe_cockpit_projects_degrades_on_exception_and_bad_shape(monkeypatch):
    """R4-3：list_projects 抛异常 / 返回 None / 非 list 形态 → 取数失败
    （degraded=True，projects=[]），且异常路径不触发连通探测。"""
    probe_calls = []

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(dp.org_db, "list_projects", _boom)
    monkeypatch.setattr(
        dp, "_cockpit_db_ready",
        lambda table: probe_calls.append(table) or True)
    assert dp._safe_cockpit_projects() == ([], True)
    assert probe_calls == []  # 异常路径无需探测
    monkeypatch.setattr(dp.org_db, "list_projects", lambda: None)
    assert dp._safe_cockpit_projects() == ([], True)
    monkeypatch.setattr(dp.org_db, "list_projects", lambda: {"id": 1})
    assert dp._safe_cockpit_projects() == ([], True)


def test_safe_cockpit_projects_distinguishes_real_zero_from_failure(monkeypatch):
    """R4-3：空结果 × 连通探测二分 —— 探测过 = 真 0（不降级）；探测不过 =
    取数失败（降级）；非空结果不探测（有数据即库连通）。"""
    monkeypatch.setattr(dp.org_db, "list_projects", lambda: [])
    monkeypatch.setattr(dp, "_cockpit_db_ready", lambda table: True)
    assert dp._safe_cockpit_projects() == ([], False)   # 真 0
    monkeypatch.setattr(dp, "_cockpit_db_ready", lambda table: False)
    assert dp._safe_cockpit_projects() == ([], True)    # 取数失败
    rows = [{"id": 1, "name": "P", "member_count": 2}]
    probe_calls = []
    monkeypatch.setattr(dp.org_db, "list_projects", lambda: rows)
    monkeypatch.setattr(
        dp, "_cockpit_db_ready",
        lambda table: probe_calls.append(table) or False)
    assert dp._safe_cockpit_projects() == (rows, False)
    assert probe_calls == []


def test_safe_cockpit_stats_degrades_and_distinguishes(monkeypatch):
    """R4-3：get_stats 抛异常/None/非 dict → 取数失败；total=0 × 探测二分
    真 0 与取数失败；有计数不探测。"""
    probe_calls = []

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(dp.ai_ledger, "get_stats", _boom)
    monkeypatch.setattr(
        dp, "_cockpit_db_ready",
        lambda table: probe_calls.append(table) or True)
    assert dp._safe_cockpit_stats() == ({}, True)
    assert probe_calls == []
    monkeypatch.setattr(dp.ai_ledger, "get_stats", lambda: None)
    assert dp._safe_cockpit_stats() == ({}, True)
    monkeypatch.setattr(dp.ai_ledger, "get_stats", lambda: [1, 2])
    assert dp._safe_cockpit_stats() == ({}, True)
    empty = {"total": 0, "pending": 0, "adoption_rate": None,
             "avg_uncertainty": None}
    monkeypatch.setattr(dp.ai_ledger, "get_stats", lambda: dict(empty))
    monkeypatch.setattr(dp, "_cockpit_db_ready", lambda table: True)
    stats, degraded = dp._safe_cockpit_stats()
    assert stats.get("total") == 0 and degraded is False   # 真 0
    monkeypatch.setattr(dp, "_cockpit_db_ready", lambda table: False)
    assert dp._safe_cockpit_stats() == ({}, True)          # 取数失败
    counted = dict(empty, total=7)
    monkeypatch.setattr(dp.ai_ledger, "get_stats", lambda: counted)
    assert dp._safe_cockpit_stats() == (counted, False)


def test_cockpit_metrics_disclose_degradation(monkeypatch):
    """R4-3：取数失败组画「—」并给内联提示「数据库暂不可用，指标为降级
    渲染」（与 ai_hub 降级口径一致）；探测通过的真 0 画 0，两组独立判定。"""
    stub = _FormSt()
    monkeypatch.setattr(dp, "st", stub)
    dp._render_cockpit_metrics([], {"total": 0}, True, False)
    assert any(kind == "warning" and "数据库暂不可用，指标为降级渲染" in text
               for kind, text in stub.messages)
    metrics = dict(stub.metrics)
    assert metrics["词典项目"] == "—"
    assert metrics["成员人次（合计）"] == "—"
    assert metrics["AI 提案总数"] == 0  # 统计组未降级 → 真 0
    assert metrics["待裁决"] == 0

    stub = _FormSt()
    monkeypatch.setattr(dp, "st", stub)
    dp._render_cockpit_metrics(
        [{"member_count": 2}],
        {"total": 7, "pending": 2, "adoption_rate": None, "avg_uncertainty": None},
        False, True)
    assert any(kind == "warning" and "降级渲染" in text
               for kind, text in stub.messages)
    metrics = dict(stub.metrics)
    assert metrics["AI 提案总数"] == "—"
    assert metrics["待裁决"] == "—"
    assert metrics["词典项目"] == 1      # 项目组未降级 → 真值

    stub = _FormSt()
    monkeypatch.setattr(dp, "st", stub)
    dp._render_cockpit_metrics(
        [{"member_count": 3}], {"total": 5}, False, False)
    assert not any(kind == "warning" for kind, _ in stub.messages)
    metrics = dict(stub.metrics)
    assert metrics["词典项目"] == 1
    assert metrics["成员人次（合计）"] == 3
    assert metrics["AI 提案总数"] == 5


def test_cockpit_chief_options_not_double_escaped(monkeypatch):
    """R2-1：建壳 chief 下拉不再预转义 —— display_name 含 HTML 字符时选项为
    原文（selectbox 由 Streamlit 自带转义；预转义会双重转义成字面实体）。"""
    stub = _FormSt()
    monkeypatch.setattr(dp, "st", stub)
    monkeypatch.setattr(
        dp, "_safe_cockpit_projects",
        lambda: ([{"id": 1, "name": "P1", "member_count": 1}], False))
    monkeypatch.setattr(dp, "_safe_cockpit_stats", lambda: ({"total": 0}, False))
    monkeypatch.setattr(dp.users_db, "list_users", lambda: [
        {"id": 7, "username": "chief_b", "display_name": "主编<b>甲</b>",
         "active": True},
    ])
    monkeypatch.setattr(dp.users_db, "effective_six_roles",
                        lambda user: {"dict_admin"})
    monkeypatch.setattr(dp.org_db, "project_selfcheck", lambda pid: (True, []))
    monkeypatch.setattr(dp.pipeline_status, "get_cluster_pipeline_status",
                        lambda cat: {})
    monkeypatch.setattr(dp.pipeline_status, "format_funnel_segments",
                        lambda status: [])
    dp._render_cockpit_tab()
    chief_calls = [opts for _label, opts in stub.selectboxes
                   if any("chief_b" in str(o) for o in opts)]
    assert chief_calls, "chief 下拉未渲染（建壳候选为空？）"
    assert any("主编<b>甲</b>（chief_b）" in str(o) for o in chief_calls[0])
    assert all("&lt;" not in str(o) for o in chief_calls[0])
