"""FX-25 批次修复测试：AI 体例质检引擎＋记录面＋协同度量接线。

对应规范 ②组「AI 体例质检挂钩」与 FX-19 协同度量五指标中「体例质检通过率」
的灰注缺口 —— 本批次把质检引擎（src/style_check.run_style_check）、记录面
（style_check_runs，DDL 注册进 mysql_db.CREATE_TABLES_SQL）与指标接线
（collab_metrics.style_check_status 三态）建起来，让指标有真数据：

  * 纯函数检查项  —— 夹具 style.yaml 三态（齐全/缺键/重复词）＋词表偏小
    warn＋排序规则枚举外 fail＋vocab_file 解析＋microstructure×spine 映射
    （含 spine 不可比对 → warn「自动化比对未覆盖」）；全机械断言，不碰 DB。
  * 真库沙箱往返  —— 独立测试库 web_word_fx25_test：run → list_recent →
    style_check_status 口径一致（total=passed+failed+warned、pass_rate=
    passed/(passed+failed)、warn 单列）；run_by 留痕（actor 落 id、系统作业
    落 NULL —— RV2-3 第 1 类口径）。
  * 权限闸        —— 非 dict_admin 抛 PermissionError 且不落行（guards
    既有模式）；actor=None 系统作业放行、run_by=NULL。
  * DB 离线降级   —— run_style_check ok=False＋reason（R4 归因）、
    list_recent_runs 返回 None、不崩不写半行。
  * collab_metrics 接线三态 —— 无 run 灰注（STYLE_CHECK_NOTE）/有 run 真值
    （最近 1 次口径）/取数不可用灰注（DB_UNAVAILABLE_NOTE）。

外部依赖隔离：纯函数用例不碰数据库（CI 全跑）；沙箱用例跑独立测试库
web_word_fx25_test（连不上/无建库权限则 skip，test_fx19_fixes 同口径）。
"""

import hashlib
import os
import sys
from pathlib import Path

import pymysql
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.mysql_db as db  # noqa: E402
from src import collab_metrics as cm  # noqa: E402
from src import sense_spine  # noqa: E402
from src import style_check as sc  # noqa: E402
from src.sense_spine import SpineSection  # noqa: E402

# 独立测试库（本地 MySQL 账号按名授权，web_word_fx25_test 已入
# scripts/grant_local_mysql.sql 授权清单；pytest 串行执行、fixture 前后
# DROP 重建，互不污染）
TEST_DB = "web_word_fx25_test"

DICT_ADMIN = {"id": 7, "username": "fx25da", "role": "viewer",
              "roles": ["dict_admin"]}
EDITOR = {"id": 8, "username": "fx25ed", "role": "viewer", "roles": ["editor"]}

# 夹具体例（六件套键齐全；词表 12 词无重复 → 全部机械通过）
FULL_YAML = """\
style_version: 1.0
defining_vocab:
  vocab_size: 12
  allow_gloss_terms: true
  words: [give, take, move, put, break, cut, fill, cover, change, follow, hold, turn]
substitution_test:
  method: 双向替换（释义↔证据例句互换）
  sample_size: 10
  pass_threshold: 0.8
sense_ordering:
  primary: 原型梯度（范畴内典型性得分，原型居前）
  secondary_check: 频次校验
  non_modeled_last: true
microstructure:
  bracket_note:
    format: 全角圆括号
    optional: true
  custom_attributes: true
multimedia:
  slots:
    illustration:
      anchor: [word, sense]
  example_media:
    caption_required: true
    source_required: true
  license_gate: 无许可不入库
"""

# 缺键态：缺 sense_ordering 与 multimedia（CFG_COMPLETE fail 逐键列名；
# SENSE_ORDERING 未声明 fail）
MISSING_KEYS_YAML = """\
style_version: 1.0
defining_vocab:
  words: [give, take, move, put, break, cut, fill, cover, change, follow, hold, turn]
substitution_test:
  method: 双向替换
microstructure:
  custom_attributes: true
"""

# 重复词条态：give 出现两次（DEFINING_VOCAB fail）
DUP_WORDS_YAML = """\
style_version: 1.0
defining_vocab:
  words: [give, give, take, move, put, break, cut, fill, cover, change, hold, turn]
substitution_test:
  method: 双向替换
sense_ordering:
  primary: 原型梯度
microstructure:
  custom_attributes: true
multimedia:
  license_gate: 无许可不入库
"""

# 词表偏小态：仅 5 词无重复（DEFINING_VOCAB warn 词表偏小）
SMALL_VOCAB_YAML = """\
style_version: 1.0
defining_vocab:
  words: [give, take, move, put, break]
substitution_test:
  method: 双向替换
sense_ordering:
  primary: 原型梯度
microstructure:
  custom_attributes: true
multimedia:
  license_gate: 无许可不入库
"""


# ============================================
# 夹具与工具
# ============================================
@pytest.fixture
def configs_root(tmp_path, monkeypatch):
    """可写 configs 根（monkeypatch sc._CONFIGS_ROOT）；返回写入函数。"""
    root = tmp_path / "configs"

    def _write(yaml_text: str, category: str = "motion") -> str:
        d = root / category
        d.mkdir(parents=True, exist_ok=True)
        (d / "style.yaml").write_text(yaml_text, encoding="utf-8")
        return str(root)

    monkeypatch.setattr(sc, "_CONFIGS_ROOT", root)
    return _write


def _items_by_code(items):
    """逐项结果按 code 索引（断言辅助）。"""
    return {it["code"]: it for it in items}


def _mysql_reachable() -> bool:
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001 —— 本地/CI 无 MySQL 时跳过集成段
        return False


HAS_MYSQL = _mysql_reachable()


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-25 集成测试")
class _SandboxCase:
    """沙箱共用件（建空测试库＋style_check_runs，测试结束 DROP）。"""

    @pytest.fixture
    def fx25_db(self, monkeypatch):
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
        )
        cur = conn.cursor()
        try:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            cur.execute(
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 "
                f"COLLATE utf8mb4_unicode_ci"
            )
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX-25 集成测试: {e}")
        conn.close()
        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        sc.ensure_style_check_table()   # 空表=「无 run 记录」态（区别于表未建）
        yield
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()

    @staticmethod
    def _seed_media_binding(license_text="CC BY 4.0", caption="",
                            purpose="example_media", seed=0):
        """种一条媒体绑定（直连 SQL；sha256 唯一由 seed 保证）。返回 binding id。"""
        from src.media_db import (MEDIA_ASSETS_TABLE_SQL,
                                  MEDIA_BINDINGS_TABLE_SQL)
        with db.get_db_cursor() as cursor:
            cursor.execute(MEDIA_ASSETS_TABLE_SQL)
            cursor.execute(MEDIA_BINDINGS_TABLE_SQL)
            sha = hashlib.sha256(f"fx25-{seed}".encode()).hexdigest()
            cursor.execute(
                "INSERT INTO media_assets (kind, file_path, sha256, source, "
                "license, status) VALUES ('image', %s, %s, 'fx25test', %s, '发布')",
                (f"media/fx25-{seed}.png", sha, license_text),
            )
            asset_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO media_bindings (asset_id, anchor_type, anchor_id, "
                "purpose, caption, status) VALUES (%s, 'sense', 1, %s, %s, '发布')",
                (asset_id, purpose, caption),
            )
            return cursor.lastrowid


# ============================================
# 1. DDL 注册与单一事实源
# ============================================
class TestDDLRegistration:
    """style_check_runs DDL：注册进 CREATE_TABLES_SQL、关键列齐全。"""

    def test_ddl_is_single_source_and_registered(self):
        assert db.STYLE_CHECK_RUNS_TABLE_SQL in db.CREATE_TABLES_SQL
        assert "CREATE TABLE IF NOT EXISTS style_check_runs" \
            in db.STYLE_CHECK_RUNS_TABLE_SQL

    def test_ddl_columns_and_audit_semantics(self):
        """留痕列口径（RV2-3 第 1 类）：run_by INT NULL=系统作业/无人。"""
        ddl = db.STYLE_CHECK_RUNS_TABLE_SQL
        for col in ("id INT AUTO_INCREMENT PRIMARY KEY", "category VARCHAR(64)",
                    "run_by INT NULL", "passed INT NOT NULL DEFAULT 0",
                    "failed INT NOT NULL DEFAULT 0", "warned INT NOT NULL DEFAULT 0",
                    "total INT NOT NULL DEFAULT 0", "detail_json MEDIUMTEXT NULL",
                    "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"):
            assert col in ddl, f"style_check_runs DDL 缺: {col}"


# ============================================
# 2. 配置装载（候选路径）
# ============================================
class TestLoadStyleConfig:
    """load_style_config：范畴级优先/词典层回退/缺失与解析失败归因。"""

    def test_real_repo_config_falls_back_to_dict_level(self):
        """真仓库：configs/motion/style.yaml 未研制 → 回退 configs/style.yaml。"""
        style, path, err = sc.load_style_config("motion")
        assert err is None and isinstance(style, dict)
        assert path.endswith("configs/style.yaml")
        assert "style_version" in style

    def test_category_level_takes_priority(self, configs_root):
        """范畴级文件在场 → 优先于词典层（范畴级研制后自然接管）。"""
        root = configs_root(FULL_YAML)
        style, path, err = sc.load_style_config("motion")
        assert err is None and path == os.path.join(root, "motion", "style.yaml")
        assert style["style_version"] == 1.0

    def test_missing_config_reports_reason(self, tmp_path, monkeypatch):
        """全部候选路径缺席 → (None, '', reason)（R4 归因文案）。"""
        monkeypatch.setattr(sc, "_CONFIGS_ROOT", tmp_path / "configs")
        style, path, err = sc.load_style_config("motion")
        assert style is None and path == ""
        assert "style.yaml 不在场" in err and "体例文件未研制" in err

    def test_parse_failure_reports_reason(self, configs_root):
        """YAML 解析失败 → 归因相对路径＋异常类型（RV19-3：绝对路径与异常
        原文不再上 UI 面——磁盘布局披露收口；细节归服务端日志）。"""
        root = configs_root("substitution_test: [坏缩进\n  -: {")
        style, path, err = sc.load_style_config("motion")
        assert style is None and path == "configs/style.yaml"
        assert "解析失败" in err and "原因类型" in err
        assert "解析失败" in err

    def test_non_mapping_top_level_reports_reason(self, configs_root):
        """顶层非映射（列表）→ 归因。"""
        configs_root("- a\n- b\n")
        style, _path, err = sc.load_style_config("motion")
        assert style is None and "顶层必须是映射" in err


# ============================================
# 3. 纯函数检查项（夹具三态，不碰 DB）
# ============================================
class TestPureCheckItems:
    """run_config_check_items：齐全/缺键/重复词三态＋warn 与枚举外面。"""

    def test_full_config_first_four_items_pass(self, configs_root):
        """齐全态：CFG/VOCAB/SENSE/MICRO 四项全 pass（词表 12 词无重复）。"""
        configs_root(FULL_YAML)
        style, _path, err = sc.load_style_config("motion")
        assert err is None
        items = _items_by_code(sc.run_config_check_items(style))
        assert set(items) == {"CFG_COMPLETE", "DEFINING_VOCAB",
                              "SENSE_ORDERING", "MICROSTRUCTURE_SPINE"}
        assert all(it["status"] == "pass" for it in items.values()), items
        assert "12 词" in items["DEFINING_VOCAB"]["detail"]
        assert "词表偏小" not in items["DEFINING_VOCAB"]["detail"]

    def test_missing_keys_fail_with_key_names(self, configs_root):
        """缺键态：CFG fail 逐键列名（sense_ordering/multimedia）；SENSE 未声明 fail。"""
        configs_root(MISSING_KEYS_YAML)
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["CFG_COMPLETE"]["status"] == "fail"
        detail = items["CFG_COMPLETE"]["detail"]
        assert "sense_ordering" in detail and "multimedia" in detail
        assert "缺必备键" in detail
        assert items["SENSE_ORDERING"]["status"] == "fail"
        assert "未声明" in items["SENSE_ORDERING"]["detail"]
        assert items["DEFINING_VOCAB"]["status"] == "pass"

    def test_duplicate_vocab_words_fail(self, configs_root):
        """重复词态：DEFINING_VOCAB fail，列重复词条与计数。"""
        configs_root(DUP_WORDS_YAML)
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["DEFINING_VOCAB"]["status"] == "fail"
        detail = items["DEFINING_VOCAB"]["detail"]
        assert "重复词条" in detail and "give" in detail

    def test_small_vocab_warns_not_fails(self, configs_root):
        """词表 <10 无重复 → warn「词表偏小」（warn 不判违例）。"""
        configs_root(SMALL_VOCAB_YAML)
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["DEFINING_VOCAB"]["status"] == "warn"
        assert "词表偏小" in items["DEFINING_VOCAB"]["detail"]

    def test_empty_vocab_fails_without_inventing_words(self, configs_root):
        """词表本体未配置（无 words/vocab_file）→ fail，不编词表。"""
        configs_root(FULL_YAML.replace(
            "  words: [give, take, move, put, break, cut, fill, cover, "
            "change, follow, hold, turn]\n", ""))
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["DEFINING_VOCAB"]["status"] == "fail"
        assert "定义词表为空" in items["DEFINING_VOCAB"]["detail"]

    def test_vocab_file_resolution_and_comments(self, configs_root):
        """vocab_file 相对 configs 根解析；# 注释行与空行跳过。"""
        root = configs_root(FULL_YAML.replace(
            "  words: [give, take, move, put, break, cut, fill, cover, "
            "change, follow, hold, turn]\n", "  vocab_file: defining_vocab.txt\n"))
        (sc._CONFIGS_ROOT / "defining_vocab.txt").write_text(
            "# 定义词表（每行一词）\ngive\ntake\nmove\nput\nbreak\ncut\n"
            "fill\ncover\nchange\n\nfollow\nhold\nturn\n", encoding="utf-8")
        style, path, _ = sc.load_style_config("motion")
        # 与 run_style_check 相同的解析目录链：style.yaml 所在目录 → 上级 → 仓库根
        search_dirs = [Path(path).parent, Path(path).parent.parent,
                       sc._REPO_ROOT]
        items = _items_by_code(sc.run_config_check_items(style, search_dirs))
        assert items["DEFINING_VOCAB"]["status"] == "pass"
        assert "vocab_file" in items["DEFINING_VOCAB"]["detail"]
        assert str(root)  # root 在场（目录链含 configs 根）

    def test_placeholder_vocab_file_fails_honestly(self, configs_root):
        """「待编者核定」类占位 vocab_file → 按未配置 fail（不猜、不编）。"""
        configs_root(FULL_YAML.replace(
            "  words: [give, take, move, put, break, cut, fill, cover, "
            "change, follow, hold, turn]\n", "  vocab_file: 待编者核定\n"))
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["DEFINING_VOCAB"]["status"] == "fail"
        assert "未落盘" in items["DEFINING_VOCAB"]["detail"]

    def test_sense_ordering_enum_outside_fails(self, configs_root):
        """排序规则键在枚举外（按字母序）→ fail 列枚举。"""
        configs_root(FULL_YAML.replace(
            "  primary: 原型梯度（范畴内典型性得分，原型居前）",
            "  primary: 按字母序排列"))
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["SENSE_ORDERING"]["status"] == "fail"
        detail = items["SENSE_ORDERING"]["detail"]
        assert "枚举外" in detail and "原型梯度" in detail and "频次" in detail

    def test_sense_ordering_freq_enum_passes(self, configs_root):
        """枚举内第二值（频次）同样合法。"""
        configs_root(FULL_YAML.replace(
            "  primary: 原型梯度（范畴内典型性得分，原型居前）",
            "  primary: 频次排序"))
        style, _path, _ = sc.load_style_config("motion")
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["SENSE_ORDERING"]["status"] == "pass"

    def test_real_repo_config_cfg_complete(self):
        """真仓库 configs/style.yaml：六件套键齐备（在场检回归钉）。"""
        style, _path, err = sc.load_style_config("motion")
        assert err is None
        items = _items_by_code(sc.run_config_check_items(style))
        assert items["CFG_COMPLETE"]["status"] == "pass"
        assert items["SENSE_ORDERING"]["status"] == "pass"
        # 词表本体未编制（vocab_size/vocab_file 待编者核定）→ 如实 fail
        assert items["DEFINING_VOCAB"]["status"] == "fail"

    def test_microstructure_spine_uncovered_key_fails(self, monkeypatch):
        """spine 七段面缺映射段 → fail（配置声明与 spine 实现面脱钩即报警）。"""
        fake = [SpineSection(title=f"{i} 号段", body=None, missing_reason="x")
                for i in range(1, 8)]        # 七段齐全但无「定制属性」段
        monkeypatch.setattr(sense_spine, "_spine_sections",
                            lambda *a, **k: fake, raising=True)
        item = sc.check_microstructure_spine(
            {"microstructure": {"custom_attributes": True}})
        assert item["status"] == "fail"
        assert "未被 spine 实现面覆盖" in item["detail"]
        assert "定制属性" in item["detail"]

    def test_microstructure_spine_section_count_anomaly_warns(self, monkeypatch):
        """spine 实现面段数异常（≠7）→ warn「自动化比对未覆盖」。"""
        monkeypatch.setattr(sense_spine, "_spine_sections",
                            lambda *a, **k: [], raising=True)
        item = sc.check_microstructure_spine(
            {"microstructure": {"custom_attributes": True}})
        assert item["status"] == "warn"
        assert "自动化比对未覆盖" in item["detail"]

    def test_microstructure_spine_unreadable_warns(self, monkeypatch):
        """spine 读取抛异常 → warn「自动化比对未覆盖」（不崩）。"""
        def _boom(*a, **k):
            raise RuntimeError("spine unavailable")

        monkeypatch.setattr(sense_spine, "_spine_sections", _boom,
                            raising=True)
        item = sc.check_microstructure_spine(
            {"microstructure": {"custom_attributes": True}})
        assert item["status"] == "warn"
        assert "自动化比对未覆盖" in item["detail"]

    def test_microstructure_unmapped_keys_listed_not_failed(self):
        """编纂成文层构件（bracket_note 等）不在映射内 → 如实列名，不计违例。"""
        style, _path, _ = sc.load_style_config("motion")
        item = sc.check_microstructure_spine(style)
        assert item["status"] == "pass"
        assert "未纳入 spine 自动比对" in item["detail"]
        assert "bracket_note" in item["detail"]


# ============================================
# 4. 真库沙箱：run → 落库 → 读回 → 指标口径一致
# ============================================
@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX-25 集成测试")
class TestRunStyleCheckSandbox(_SandboxCase):
    """run_style_check 落库往返（独立测试库）。"""

    def test_run_round_trip_counts_and_rate_consistent(self, fx25_db,
                                                       configs_root):
        """齐全态真跑：ok/run_id/五项/口径一致（total=三态和，warn 单列）。"""
        configs_root(FULL_YAML)
        r = sc.run_style_check("motion", actor=DICT_ADMIN)
        assert r["ok"] is True and isinstance(r["run_id"], int) and r["run_id"] > 0
        assert r["category"] == "motion"
        assert r["total"] == len(r["items"]) == 5
        assert r["total"] == r["passed"] + r["failed"] + r["warned"]
        # 沙箱无 media 两表 → 媒体抽查 warn「暂无媒体绑定可检」（不入 failed）
        by_code = _items_by_code(r["items"])
        assert by_code["MULTIMEDIA_BINDINGS"]["status"] == "warn"
        assert "暂无媒体绑定可检" in by_code["MULTIMEDIA_BINDINGS"]["detail"]
        assert r["warned"] == 1 and r["failed"] == 0 and r["passed"] == 4
        assert r["pass_rate"] == 1.0      # 4/(4+0)，warn 不入分母
        assert r["pass_rate"] == cm.style_check_pass_rate_from_counts(
            r["passed"], r["failed"])

    def test_run_row_recorded_and_read_back(self, fx25_db, configs_root):
        """落库行读回：list_recent_runs 行字段＋items 解析＋run_by 留痕。"""
        configs_root(FULL_YAML)
        r = sc.run_style_check("motion", actor=DICT_ADMIN)
        rows = sc.list_recent_runs("motion", limit=5)
        assert rows is not None and len(rows) == 1
        row = rows[0]
        assert row["id"] == r["run_id"] and row["category"] == "motion"
        assert row["run_by"] == DICT_ADMIN["id"]      # 显式 actor 落 users.id
        assert row["passed"] == r["passed"] and row["failed"] == r["failed"]
        assert row["warned"] == r["warned"] and row["total"] == r["total"]
        assert isinstance(row["items"], list) and len(row["items"]) == 5
        assert {it["code"] for it in row["items"]} == {
            "CFG_COMPLETE", "DEFINING_VOCAB", "SENSE_ORDERING",
            "MICROSTRUCTURE_SPINE", "MULTIMEDIA_BINDINGS"}

    def test_system_job_run_by_null(self, fx25_db, configs_root):
        """actor=None 系统作业：放行（RV 口径）且 run_by 落 NULL。"""
        configs_root(FULL_YAML)
        r = sc.run_style_check("motion", actor=None)
        assert r["ok"] is True
        row = sc.list_recent_runs("motion", limit=1)[0]
        assert row["run_by"] is None

    def test_list_recent_runs_filters_category_and_orders_desc(
            self, fx25_db, configs_root):
        """category 过滤＋id 降序（新在前）；跨范畴清单不带过滤。"""
        configs_root(FULL_YAML)
        first = sc.run_style_check("motion", actor=DICT_ADMIN)
        configs_root(MISSING_KEYS_YAML, category="speech")
        second = sc.run_style_check("speech", actor=None)
        rows = sc.list_recent_runs("motion", limit=5)
        assert [row["id"] for row in rows] == [first["run_id"]]
        rows_all = sc.list_recent_runs(limit=5)
        assert [row["id"] for row in rows_all] == [second["run_id"],
                                                   first["run_id"]]

    def test_latest_run_wins_in_status(self, fx25_db, configs_root):
        """两次 run（齐全→缺键）：status 取最近 1 次（缺键态 rate=2/5=0.4）。"""
        configs_root(FULL_YAML)
        sc.run_style_check("motion", actor=DICT_ADMIN)
        configs_root(MISSING_KEYS_YAML)
        second = sc.run_style_check("motion", actor=DICT_ADMIN)
        # 缺键态：CFG/SENSE/MULTIMEDIA fail（键未声明即违例）；VOCAB/MICRO pass
        assert second["failed"] == 3 and second["passed"] == 2
        assert second["warned"] == 0 and second["total"] == 5
        status = cm.style_check_status("motion")
        assert status["available"] is True
        assert status["run_id"] == second["run_id"]
        assert status["passed"] == 2 and status["failed"] == 3
        assert status["warned"] == 0 and status["total"] == 5
        assert status["pass_rate"] == 0.4     # 2/(2+3)，warn 不入分母
        assert "最近 1 次" in status["note"]

    def test_permission_gate_rejects_non_dict_admin(self, fx25_db,
                                                    configs_root):
        """非 dict_admin 抛 PermissionError，且不落任何行（闸先于一切写）。"""
        configs_root(FULL_YAML)
        with pytest.raises(PermissionError) as ei:
            sc.run_style_check("motion", actor=EDITOR)
        assert "体例质检执行" in str(ei.value)
        assert sc.list_recent_runs("motion", limit=5) == []

    def test_permission_gate_precedes_config_and_db(self, fx25_db,
                                                    monkeypatch):
        """闸先于配置/DB：非法 actor＋配置缺失＋DB 炸 → 仍是 PermissionError。"""
        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(sc, "get_db_cursor", _boom)
        with pytest.raises(PermissionError):
            sc.run_style_check("motion", actor=EDITOR)

    def test_db_offline_degrades_with_reason(self, fx25_db, monkeypatch):
        """DB 离线：ok=False＋reason 归因、run_id=None、不崩；读函数返回 None。"""
        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(sc, "get_db_cursor", _boom)
        r = sc.run_style_check("motion", actor=DICT_ADMIN)
        assert r["ok"] is False and r["run_id"] is None
        assert "数据库不可用" in r["reason"]
        assert r["passed"] == 0 and r["items"] == []
        assert sc.list_recent_runs("motion", limit=5) is None

    def test_invalid_category_rejected(self, fx25_db):
        """含路径分隔符/点前缀的范畴名 → ok=False（category 进路径与 SQL 值）。"""
        for bad in ("../etc", "a/b", ".hidden", "", "..\\win"):
            r = sc.run_style_check(bad, actor=DICT_ADMIN)
            assert r["ok"] is False and "范畴名非法" in r["reason"], bad

    def test_missing_config_degrades_with_reason(self, fx25_db, tmp_path,
                                                 monkeypatch):
        """配置缺失（候选路径全缺席）：ok=False＋reason，不落库。"""
        monkeypatch.setattr(sc, "_CONFIGS_ROOT", tmp_path / "no_configs")
        r = sc.run_style_check("motion", actor=DICT_ADMIN)
        assert r["ok"] is False and r["run_id"] is None
        assert "style.yaml" in r["reason"]
        assert sc.list_recent_runs("motion", limit=5) == []

    def test_media_binding_violations_fail_spot_check(self, fx25_db,
                                                      configs_root):
        """媒体抽查：图注必配而空图注 → fail；空许可 → fail；修复后转 pass。"""
        configs_root(FULL_YAML)
        self._seed_media_binding(caption="", seed=1)  # 违例 1：example_media 无图注
        r = sc.run_style_check("motion", actor=DICT_ADMIN)
        item = _items_by_code(r["items"])["MULTIMEDIA_BINDINGS"]
        assert item["status"] == "fail" and "图注" in item["detail"]
        self._seed_media_binding(license_text="", caption="有图注",
                                 purpose="illustration", seed=2)  # 违例 2：空许可
        r2 = sc.run_style_check("motion", actor=DICT_ADMIN)
        item2 = _items_by_code(r2["items"])["MULTIMEDIA_BINDINGS"]
        assert item2["status"] == "fail" and "许可" in item2["detail"]
        # 修复：补齐全部空图注与空许可 → 抽查转 pass
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE media_bindings SET caption = '图注已补' "
                "WHERE TRIM(caption) = ''")
            cursor.execute(
                "UPDATE media_assets SET license = 'CC0' "
                "WHERE TRIM(license) = ''")
        r3 = sc.run_style_check("motion", actor=DICT_ADMIN)
        item3 = _items_by_code(r3["items"])["MULTIMEDIA_BINDINGS"]
        assert item3["status"] == "pass" and "无违例" in item3["detail"]
        # 三次 run 全部落库，通过率随抽查结果演进（最近 1 次口径）
        rows = sc.list_recent_runs("motion", limit=3)
        assert len(rows) == 3 and rows[0]["id"] == r3["run_id"]


# ============================================
# 5. collab_metrics 接线三态
# ============================================
class TestCollabMetricsWiring(_SandboxCase):
    """style_check_status 三态＋纯函数口径（无 run 灰注/有 run 真值/不可用）。

    纯函数用例不碰 DB（CI 全跑）；落库态用例依赖沙箱（无 MySQL 逐个 skip）。
    """

    def test_pass_rate_pure_function(self):
        """纯函数：passed/(passed+failed)；warn 不入分母；分母 0 → None。"""
        assert cm.style_check_pass_rate_from_counts(4, 0) == 1.0
        assert cm.style_check_pass_rate_from_counts(2, 2) == 0.5
        assert cm.style_check_pass_rate_from_counts(0, 0) is None
        assert cm.style_check_pass_rate_from_counts(None, "x") is None
        # 与引擎单一实现同源
        assert cm.style_check_pass_rate_from_counts(3, 1) \
            == sc.pass_rate_from_counts(3, 1)

    def test_fetch_unavailable_grey_note(self, monkeypatch):
        """取数不可用（list_recent_runs → None）→ DB_UNAVAILABLE_NOTE 灰注。"""
        monkeypatch.setattr(cm, "list_recent_runs",
                            lambda category=None, limit=5: None)
        status = cm.style_check_status()
        assert status["available"] is False and status["pass_rate"] is None
        assert status["reason"] == cm.DB_UNAVAILABLE_NOTE

    @pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过集成段")
    def test_no_runs_grey_note(self, fx25_db):
        """无 run 记录 → available=False＋STYLE_CHECK_NOTE（灰注，不编数字）。"""
        status = cm.style_check_status("motion")
        assert status["available"] is False
        assert status["pass_rate"] is None and status["run_id"] is None
        assert "尚未接入" in status["reason"] and "不编数字" in status["reason"]
        assert status["note"] == cm.STYLE_CHECK_NOTE

    @pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过集成段")
    def test_with_run_real_value_matches_run_row(self, fx25_db, configs_root):
        """有 run → 真值：pass_rate/计数与 run 行一致（最近 1 次口径）。"""
        configs_root(MISSING_KEYS_YAML)
        r = sc.run_style_check("motion", actor=DICT_ADMIN)
        status = cm.style_check_status("motion")
        assert status["available"] is True
        assert status["run_id"] == r["run_id"]
        assert status["run_category"] == "motion"
        assert status["passed"] == r["passed"]
        assert status["failed"] == r["failed"] and status["warned"] == r["warned"]
        assert status["pass_rate"] == r["pass_rate"]
        assert status["pass_rate"] == cm.style_check_pass_rate_from_counts(
            r["passed"], r["failed"])
        assert status["note"] == cm.STYLE_CHECK_RATE_NOTE

    @pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过集成段")
    def test_status_without_category_uses_latest_overall(self, fx25_db,
                                                         configs_root):
        """category=None → 跨范畴最近 1 次（协同度量页无范畴上下文）。"""
        configs_root(FULL_YAML)
        sc.run_style_check("motion", actor=DICT_ADMIN)
        configs_root(MISSING_KEYS_YAML, category="speech")
        latest = sc.run_style_check("speech", actor=DICT_ADMIN)
        status = cm.style_check_status()
        assert status["available"] is True
        assert status["run_id"] == latest["run_id"]
        assert status["run_category"] == "speech"
