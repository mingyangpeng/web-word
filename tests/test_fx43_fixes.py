"""FX-43 批次修复测试：AI-人一致率升级为逐特征真值（AI 草稿快照落库）。

对应修复（论文核心指标 AI-人一致率的口径强化，RV2-3 NULL 口径）：

  * DDL —— annotation_submissions 补 ai_draft_snapshot JSON NULL（ALTER-only
    幂等迁移，照 FX-20 _migrate_assignments_round_columns 模式含 MySQL 1060
    白名单；建表 SQL 保持规范 §2 原样，存量库与新库走「建旧形 → 探测补列」
    同一条路径）。NULL = 提交时无 AI 草稿（纯人工/系统），不用空对象冒充；
  * 提交链捕获 —— submit_annotation 加可选 ai_draft 参数（None=SQL 与既有
    语句逐字节一致，旧调用零破坏；非 dict/空 dict/序列化失败降级同 None，
    快照脏值不拦标注提交本体；ensure_ascii=False 序列化后落 ai_draft_snapshot，
    覆盖更新时快照随新提交同步覆盖）。捕获点在 app.py 标注平台提交处
    （LLM 初筛草稿原始值，页面 AppTest 接线锁见 fx35 口径注记）；
  * 逐特征一致率 —— collab_metrics.feature_level_agreement_rate：取
    ai_draft_snapshot 非空的提交，快照 vs 提交 payload 逐键比对，一致特征数
    ÷ 可比特征总数（分母=两侧都有的键；聚合所有提交）；快照面无数据/库不可用
    → {"rate": None, 其余 0}（「还没数据」≠ 0%，消费方维持回退）；
  * 指标页接线 —— collab_pages 五指标卡 AI-人一致率双口径回退链：快照面有
    数据 → 逐特征真值（caption 标「逐特征口径（n 提交）」）；无快照 → 回退
    FX-19 台账口径（caption 标「提案对照口径」）；台账自身不可用 → 整卡灰注。

外部依赖隔离（test_fx19/test_fx20 同款三段）：
  * 假游标用例不连库：monkeypatch annotation_flow / collab_metrics 的
    get_db_cursor，按 SQL 子串分派种子行（迁移探测走 information_schema 路由）；
  * 真库用例（TestFx43RealDb）复用已授权测试库机制（web_word_fx43_test，已入
    scripts/grant_local_mysql.sql；独立库名不与其他模块测试冲突，fixture 前后
    DROP 重建），MySQL 不可用/无建库权限整类 skip；
  * 页面 AppTest 用例打桩 collab_metrics 数据函数，不依赖开发库内容。
"""

import json
import logging
import os
import sys

import pymysql
import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.annotation_flow as flow  # noqa: E402
import src.collab_metrics as cm  # noqa: E402
import src.mysql_db as db  # noqa: E402
from src.annotation_flow import (  # noqa: E402
    SUBMISSION_AI_DRAFT_COLUMNS,
    ensure_flow_tables,
    submit_annotation,
)

TEST_DB = "web_word_fx43_test"


# ============================================
# 假游标基建（不连库：按 SQL 子串分派；fx20 FakeFx20Cursor 变体）
# ============================================
class _Ctx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class _FakeCursor:
    """按 SQL 子串分派的假游标：select_routes 命中即供行，否则结果空。"""

    def __init__(self):
        self.executed = []
        self.select_routes = []  # [(子串, 行列表或 callable(sql, params)->行)]
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._result = []
        for substring, rows in self.select_routes:
            if substring in sql:
                self._result = rows(sql, params) if callable(rows) else list(rows)
                return

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _patch_flow_probe(monkeypatch, existing_columns=()):
    """flow.get_db_cursor → 假游标；information_schema 探测按 existing 供行
    ((table, column) 集合) —— 迁移幂等/缺列补列测试用（fx20 _patch 同款）。"""
    cursor = _FakeCursor()
    existing = set(existing_columns)

    def _probe(sql, params):
        table, column = params
        return [{"n": 1 if (table, column) in existing else 0}]

    cursor.select_routes.append(("information_schema.COLUMNS", _probe))
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


def _patch_flow_plain(monkeypatch):
    """flow.get_db_cursor → 假游标（无探测路由，提交语句形态测试用）。"""
    cursor = _FakeCursor()
    monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
    return cursor


def _flow_records(caplog):
    return [r for r in caplog.records if r.name == "src.annotation_flow"]


_VALID_PAYLOAD = {"admission": "Y", "needs_review": False}
_VALID_DRAFT = {
    "admission": "Y",
    "schema": "方式伴随图式",
    "alignment": "完全对齐",
    "reason": "趋向补语证据充分",
}


# ============================================
# 1) DDL：ai_draft_snapshot 列（ALTER-only 幂等迁移 + 1060 白名单）
# ============================================
class TestMigrateAiDraftColumn:
    def test_column_shape(self):
        """迁移对单列、ALTER-only、JSON NULL（RV2-3：NULL=无 AI 草稿）。"""
        assert [c for c, _ in SUBMISSION_AI_DRAFT_COLUMNS] == ["ai_draft_snapshot"]
        for _, sql in SUBMISSION_AI_DRAFT_COLUMNS:
            assert sql.startswith("ALTER TABLE annotation_submissions ADD COLUMN")
            assert "JSON NULL" in sql

    def test_missing_column_emits_alter_after_tables(self, monkeypatch):
        """缺列 → 建三表后补列（存量库/新库同一条「建旧形 → 探测补列」路径）。"""
        cursor = _patch_flow_probe(monkeypatch, existing_columns=())
        ensure_flow_tables()
        sqls = [sql for sql, _ in cursor.executed]
        creates = [s for s in sqls if s.startswith("CREATE TABLE")]
        alters = [s for s in sqls if s.startswith("ALTER TABLE")]
        assert len(creates) == 3                       # 三表 DDL 照旧
        assert SUBMISSION_AI_DRAFT_COLUMNS[0][1] in alters
        # FX-43 的 ALTER 在全部建表之后（且随 FX-20 两列迁移之后）
        assert sqls.index(SUBMISSION_AI_DRAFT_COLUMNS[0][1]) > sqls.index(creates[-1])
        assert len([a for a in alters if "annotation_submissions" in a]) == 1

    def test_idempotent_when_column_exists(self, monkeypatch):
        """列已在 → 探测命中跳过，零 annotation_submissions ALTER（幂等核心）。"""
        cols = {("assignments", c) for c, _ in flow.ASSIGNMENTS_ROUND_COLUMNS}
        cols.add(("annotation_submissions", "ai_draft_snapshot"))
        cursor = _patch_flow_probe(monkeypatch, existing_columns=cols)
        ensure_flow_tables()
        ensure_flow_tables()
        assert not [s for s, _ in cursor.executed
                    if s.startswith("ALTER TABLE annotation_submissions")]

    def test_direct_callable_missing_column(self, monkeypatch):
        """直调入口：缺列态恰好 1 探测 + 1 ALTER（fx20 direct_callable 同款）。"""
        cursor = _patch_flow_probe(monkeypatch, existing_columns=())
        flow._migrate_submissions_ai_draft_column(cursor)
        assert len(cursor.executed) == 2
        assert "information_schema.COLUMNS" in cursor.executed[0][0]
        assert cursor.executed[1][0] == SUBMISSION_AI_DRAFT_COLUMNS[0][1]


class _DupColAlterCursor:
    """桩游标：information_schema 探测按 existing 供行；ALTER 注入指定异常
    （fx32 _DupColAlterCursor 同款）。"""

    def __init__(self, existing=(), alter_exc=None):
        self.executed = []
        self.existing = set(existing)
        self.alter_exc = alter_exc
        self._result = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.lstrip().startswith("ALTER TABLE"):
            if self.alter_exc is not None:
                raise self.alter_exc
            return
        if "information_schema.COLUMNS" in sql:
            table, column = params
            self._result = [{"n": 1 if (table, column) in self.existing else 0}]
            return
        self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _dup_col_error():
    return pymysql.err.InternalError(
        1060, "Duplicate column name 'ai_draft_snapshot'")


class TestAiDraftMigration1060Whitelist:
    """MySQL 1060 白名单（RV14-4 幂等自愈）：FX-43 迁移同款处理。"""

    def test_1060_self_heals_not_raises(self, caplog):
        """ALTER 撞 1060（并发首启第二进程在探测窗口后撞列）→ 幂等成功不抛。"""
        cursor = _DupColAlterCursor(existing=(), alter_exc=_dup_col_error())
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            flow._migrate_submissions_ai_draft_column(cursor)  # 不应 raise
        alters = [s for s, _ in cursor.executed if s.startswith("ALTER TABLE")]
        assert len(alters) == 1
        assert any("1060" in r.getMessage() and "幂等自愈" in r.getMessage()
                   for r in _flow_records(caplog))

    def test_non_1060_propagates(self):
        """非 1060 的迁移错误照旧向上抛（白名单不扩大）。"""
        cursor = _DupColAlterCursor(
            existing=(),
            alter_exc=pymysql.err.OperationalError(
                1054, "Unknown column 'ai_draft_snapshot'"),
        )
        with pytest.raises(pymysql.err.OperationalError):
            flow._migrate_submissions_ai_draft_column(cursor)

    def test_ensure_flow_tables_1060_not_misattributed(self, monkeypatch, caplog):
        """外层 1060 单列分流：来自 FX-43 迁移的撞列不进「检查 users/
        oald_senses 是否已建」误导文案（fx32 同款断言换入口）。"""

        def _boom(cursor):
            raise _dup_col_error()

        monkeypatch.setattr(flow, "_migrate_submissions_ai_draft_column", _boom)
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(_DupColAlterCursor()))
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            ensure_flow_tables()  # 不应 raise
        messages = [r.getMessage() for r in _flow_records(caplog)]
        assert any("1060" in m and "幂等自愈" in m for m in messages)
        assert not any("检查 users/oald_senses" in m for m in messages)


# ============================================
# 2) 提交链：submit_annotation 带/不带 ai_draft 的落库形态
# ============================================
class TestSubmitAnnotationAiDraft:
    def _last_write(self, cursor):
        sql, params = cursor.executed[-1]
        assert "INSERT INTO annotation_submissions" in sql
        return sql, params

    def test_without_ai_draft_sql_byte_identical_to_legacy(self, monkeypatch):
        """ai_draft 缺省（None）→ 语句与 FX-43 前逐字节一致（旧调用零破坏）：
        不含快照列，新行落列默认 NULL。"""
        cursor = _patch_flow_plain(monkeypatch)
        assert submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD)
        sql, params = self._last_write(cursor)
        assert "ai_draft_snapshot" not in sql
        assert ("(category, sense_id, task_type, coder_id, payload, "
                "ai_assisted, status)") in sql
        assert params == ("motion", 501, "admission", 12,
                          json.dumps(_VALID_PAYLOAD, ensure_ascii=False), 1)

    def test_ai_draft_none_kwarg_matches_legacy_call(self, monkeypatch):
        """显式 ai_draft=None 与不传该参数 → 执行的 SQL/params 完全一致。"""
        cursor_a = _patch_flow_plain(monkeypatch)
        submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD)
        legacy = list(cursor_a.executed)
        cursor_b = _patch_flow_plain(monkeypatch)
        submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD,
                          ai_draft=None)
        assert cursor_b.executed == legacy

    def test_ai_draft_lands_in_sql_and_params(self, monkeypatch):
        """带草稿：INSERT 列 + ON DUPLICATE 更新两处快照列；ensure_ascii=False
        序列化（中文直存，不转 \\u 转义）。"""
        cursor = _patch_flow_plain(monkeypatch)
        assert submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD,
                                 ai_draft=_VALID_DRAFT)
        sql, params = self._last_write(cursor)
        # 3 处 = INSERT 列清单 + 覆盖更新赋值目标 + VALUES(...) 引用
        assert sql.count("ai_draft_snapshot") == 3
        assert "ai_draft_snapshot = VALUES(ai_draft_snapshot)" in sql
        assert len(params) == 7
        assert params[-1] == json.dumps(_VALID_DRAFT, ensure_ascii=False)
        assert "方式伴随图式" in params[-1]              # ensure_ascii=False 实证
        assert "\\u" not in params[-1]

    def test_ai_draft_overwrite_updates_snapshot(self, monkeypatch):
        """同一 (sense, task_type, coder) 覆盖提交带新草稿 → 快照随新提交同步
        覆盖（快照语义=「本次提交时 AI 给了什么」，不沿用旧行残留）。"""
        cursor = _patch_flow_plain(monkeypatch)
        submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD,
                          ai_draft={"admission": "Y"})
        submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD,
                          ai_draft={"admission": "N", "reason": "改判"})
        assert cursor.executed[-1][1][-1] == json.dumps(
            {"admission": "N", "reason": "改判"}, ensure_ascii=False)

    @pytest.mark.parametrize("bad_draft", [{}, "草稿", [], 3])
    def test_empty_or_nondict_draft_falls_back_to_legacy(self, monkeypatch,
                                                         bad_draft, caplog):
        """空对象/非 dict 草稿 → 降级同 None（RV2-3：不用空对象冒充有草稿），
        语句回落既有形态，提交本体不受影响。"""
        cursor = _patch_flow_plain(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="src.annotation_flow"):
            assert submit_annotation("motion", 501, "admission", 12,
                                     _VALID_PAYLOAD, ai_draft=bad_draft)
        sql, params = self._last_write(cursor)
        assert "ai_draft_snapshot" not in sql
        assert len(params) == 6
        assert any("ai_draft" in r.getMessage() and "NULL" in r.getMessage()
                   for r in caplog.records)

    def test_unserializable_draft_degrades_submission_survives(self, monkeypatch):
        """草稿不可序列化（set 值）→ 快照降级 NULL、提交照常成功
        （快照脏值不拦标注提交本体）。"""
        cursor = _patch_flow_plain(monkeypatch)
        assert submit_annotation("motion", 501, "admission", 12, _VALID_PAYLOAD,
                                 ai_draft={"admission": "Y", "bad": {1, 2}})
        sql, params = self._last_write(cursor)
        assert "ai_draft_snapshot" not in sql and len(params) == 6

    def test_invalid_payload_still_rejected_with_draft(self, monkeypatch):
        """payload 非法照旧拒绝（快照参数不改变既有校验闸）。"""
        _patch_flow_plain(monkeypatch)
        assert not submit_annotation("motion", 501, "admission", 12,
                                     {"admission": "X"},
                                     ai_draft=_VALID_DRAFT)


# ============================================
# 3) 逐特征一致率：纯聚合（一致/不一致/键缺失三态）
# ============================================
class TestFeatureAgreementFromRows:
    def test_three_state_aggregation(self):
        """一致（同键同值）/ 不一致（同键异值）/ 键缺失（单侧独有）三态聚合：
        分母只算两侧都有的键。"""
        rows = [
            # 完全一致：3 键全同（payload 多出 needs_review 单侧独有，不计）
            {"ai_draft_snapshot": json.dumps(
                {"admission": "Y", "schema": "方式伴随图式", "alignment": "完全对齐"},
                ensure_ascii=False),
             "payload": json.dumps(
                 {"admission": "Y", "schema": "方式伴随图式",
                  "alignment": "完全对齐", "needs_review": False},
                 ensure_ascii=False)},
            # 部分不一致：admission 异值不计入分子，schema 同值计入
            {"ai_draft_snapshot": {"admission": "N", "schema": "终点抵达图式"},
             "payload": {"admission": "EXT", "schema": "终点抵达图式",
                         "needs_review": True}},
            # 键缺失：快照仅 reason（单侧独有），可比 0
            {"ai_draft_snapshot": {"reason": "只有理由"},
             "payload": {"admission": "Y"}},
        ]
        r = cm.feature_level_agreement_from_rows(rows)
        assert r == {"rate": 0.8, "n_submissions": 3, "n_features": 5,
                     "matched": 4}

    def test_json_string_rows_and_dict_rows_equal(self):
        """PyMySQL JSON 列 str/dict 两形态解析一致（parse_payload 单一实现）。"""
        row_dict = {"ai_draft_snapshot": {"admission": "Y"},
                    "payload": {"admission": "Y"}}
        row_str = {"ai_draft_snapshot": json.dumps({"admission": "Y"}),
                   "payload": json.dumps({"admission": "Y"})}
        assert (cm.feature_level_agreement_from_rows([row_dict])
                == cm.feature_level_agreement_from_rows([row_str])
                == {"rate": 1.0, "n_submissions": 1, "n_features": 1,
                    "matched": 1})

    def test_dirty_or_empty_snapshot_skipped(self):
        """脏快照（解析失败/空对象/非 dict JSON）不进比对面（RV2-3：空对象
        不冒充有草稿），n_submissions 不虚增。"""
        rows = [
            {"ai_draft_snapshot": "{}", "payload": {"admission": "Y"}},
            {"ai_draft_snapshot": "[]", "payload": {"admission": "Y"}},
            {"ai_draft_snapshot": None, "payload": {"admission": "Y"}},
            {"ai_draft_snapshot": "{坏 JSON", "payload": {"admission": "Y"}},
            {"ai_draft_snapshot": {"admission": "Y"},
             "payload": {"admission": "Y"}},
        ]
        r = cm.feature_level_agreement_from_rows(rows)
        assert r["n_submissions"] == 1 and r["matched"] == 1
        assert r["n_features"] == 1 and r["rate"] == 1.0

    def test_no_comparable_features_rate_none(self):
        """有带快照提交但零可比键 → rate None（「还没有可比特征」≠ 0%）。"""
        r = cm.feature_level_agreement_from_rows(
            [{"ai_draft_snapshot": {"reason": "x"}, "payload": {"admission": "Y"}}])
        assert r == {"rate": None, "n_submissions": 1, "n_features": 0,
                     "matched": 0}

    def test_empty_rows_zero_face(self):
        """无行 → 全零零值面，rate None（消费方维持回退）。"""
        assert cm.feature_level_agreement_from_rows([]) == {
            "rate": None, "n_submissions": 0, "n_features": 0, "matched": 0}
        assert cm.feature_level_agreement_from_rows(None) == {
            "rate": None, "n_submissions": 0, "n_features": 0, "matched": 0}

    def test_rate_four_decimals(self):
        """比率 4 位小数（模块 _rate4 纪律）：2/3 → 0.6667。"""
        rows = [{"ai_draft_snapshot": {"admission": "Y", "schema": "S"},
                 "payload": {"admission": "Y", "schema": "T"}}]
        assert cm.feature_level_agreement_from_rows(rows)["rate"] == 0.5
        rows = [{"ai_draft_snapshot": {"a": 1, "b": 2, "c": 3},
                 "payload": {"a": 1, "b": 2, "c": 4}}]
        assert cm.feature_level_agreement_from_rows(rows)["rate"] == 0.6667

    def test_note_constants_document_both_modes(self):
        """两口径文案常量齐全且各含关键口径词（页面 caption/tooltip 单一事实源）。"""
        for note in (cm.AGREEMENT_NOTE, cm.FEATURE_AGREEMENT_NOTE):
            assert isinstance(note, str) and note.strip()
        assert "提案对照口径" in cm.AGREEMENT_NOTE
        assert "逐特征口径" in cm.FEATURE_AGREEMENT_NOTE
        assert "ai_draft_snapshot" in cm.FEATURE_AGREEMENT_NOTE


# ============================================
# 4) 逐特征一致率：取数层 + 降级（假游标，不连库）
# ============================================
class TestFeatureLevelAgreementRateFetch:
    def _patch_cm_cursor(self, monkeypatch, rows):
        cursor = _FakeCursor()
        cursor.select_routes.append(("annotation_submissions", list(rows)))
        monkeypatch.setattr(cm, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        return cursor

    def test_fetch_filters_and_limit(self, monkeypatch):
        """SQL 面：快照非 NULL 过滤 + 常量 WHERE 片段参数化 + 最近优先 LIMIT。"""
        cursor = self._patch_cm_cursor(monkeypatch, [])
        r = cm.feature_level_agreement_rate("motion", "admission")
        assert r == {"rate": None, "n_submissions": 0, "n_features": 0,
                     "matched": 0}
        sql, params = cursor.executed[0]
        assert "ai_draft_snapshot IS NOT NULL" in sql
        assert "category = %s" in sql and "task_type = %s" in sql
        assert "ORDER BY id DESC LIMIT %s" in sql
        assert params == ("motion", "admission", 500)

    def test_fetch_no_filter_cross_category(self, monkeypatch):
        """category/task_type 缺省 None → 跨范畴聚合（页面总卡口径），仅 LIMIT 参数。"""
        cursor = self._patch_cm_cursor(monkeypatch, [])
        cm.feature_level_agreement_rate()
        sql, params = cursor.executed[0]
        assert "category = %s" not in sql and "task_type = %s" not in sql
        assert params == (500,)

    def test_fetch_rows_fed_to_pure_aggregation(self, monkeypatch):
        """取数行喂纯聚合：种子两行 → matched/n_features 逐键对表。"""
        rows = [
            {"ai_draft_snapshot": {"admission": "Y", "schema": "方式伴随图式"},
             "payload": {"admission": "Y", "schema": "方式伴随图式"}},
            {"ai_draft_snapshot": {"admission": "N"},
             "payload": {"admission": "EXT"}},
        ]
        self._patch_cm_cursor(monkeypatch, rows)
        r = cm.feature_level_agreement_rate()
        assert r == {"rate": 0.6667, "n_submissions": 2, "n_features": 3,
                     "matched": 2}

    def test_invalid_limit_falls_back_to_default(self, monkeypatch):
        """非法 limit（0/负数/bool）→ 回落默认 500（LIMIT 恒有界）。"""
        for bad in (0, -5, True):
            cursor = self._patch_cm_cursor(monkeypatch, [])
            cm.feature_level_agreement_rate(limit=bad)
            assert cursor.executed[0][1] == (500,)

    def test_db_offline_zero_face(self, monkeypatch):
        """数据库不可用 → 零值面（rate None + 其余 0），不抛异常（消费方维持
        回退，是「不可用」不是 0%）。"""

        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(cm, "get_db_cursor", _boom)
        assert cm.feature_level_agreement_rate() == {
            "rate": None, "n_submissions": 0, "n_features": 0, "matched": 0}


# ============================================
# 5) 指标页回退链（AppTest；打桩数据函数，不依赖开发库内容）
# ============================================
_METRICS_TAB_SCRIPT = (
    "from src.collab_pages import _render_metrics_tab\n"
    "_render_metrics_tab()\n"
)

_STUB_FEATURE_TRUTH = {
    "rate": 0.75, "n_submissions": 8, "n_features": 20, "matched": 15}
_STUB_FEATURE_EMPTY = {
    "rate": None, "n_submissions": 0, "n_features": 0, "matched": 0}
_STUB_LEDGER = {
    "available": True, "adopted": 3, "rejected": 1, "modified": 1,
    "decided": 5, "agreement_rate": 0.6, "partial_agreement": 1,
    "note": cm.AGREEMENT_NOTE,
}


def _patch_ledger_stubs(monkeypatch):
    """打桩 collab_pages 侧台账触点（get_stats/工序枚举；fx19 _patch_ledger_stubs
    同款）—— 页面总览段不触库，本组用例只聚焦 AI-人一致率卡。"""
    import src.collab_pages as cp

    monkeypatch.setattr(cp, "get_stats", lambda stage=None: {
        "stage": stage, "total": 9, "pending": 1, "adopted": 3, "rejected": 1,
        "modified": 1, "decided": 5, "adoption_rate": 0.6,
        "avg_uncertainty": 0.4})
    monkeypatch.setattr(cp, "_list_proposal_stages", lambda: ["sense_division"])


def _patch_other_metric_stubs(monkeypatch):
    """打桩其余四指标卡（本组用例聚焦 AI-人一致率双口径，避免触库）。"""
    monkeypatch.setattr(cm, "annotation_savings", lambda: {
        "available": True, "base_count": 6, "minutes_saved": 18.0,
        "hours_saved": 0.3, "minutes_per_item": 3.0, "estimated": True,
        "note": cm.SAVINGS_NOTE})
    monkeypatch.setattr(cm, "writing_rejection_rate", lambda: {
        "available": True, "approved": 5, "revision_requested": 2,
        "rejected": 1, "decided": 8, "rejection_rate": 0.375,
        "note": cm.REJECTION_NOTE})
    monkeypatch.setattr(cm, "substitution_test_status", lambda: {
        "available": False, "configured": True, "pass_rate": None,
        "reason": cm.SUBSTITUTION_NOTE, "note": cm.SUBSTITUTION_NOTE})
    monkeypatch.setattr(cm, "style_check_status", lambda: {
        "available": False, "configured": True, "pass_rate": None,
        "reason": cm.STYLE_CHECK_NOTE, "note": cm.STYLE_CHECK_NOTE})


class TestAgreementCardFallbackChain:
    def test_feature_truth_takes_priority(self, monkeypatch):
        """快照面有数据 → 逐特征真值优先：rate 上卡、caption 标「逐特征口径
        （n 提交）」；台账口径取数不发生（桩观测）。"""
        ledger_calls = []
        monkeypatch.setattr(cm, "feature_level_agreement_rate",
                            lambda *a, **k: dict(_STUB_FEATURE_TRUTH))

        def _ledger_spy():
            ledger_calls.append(1)
            return dict(_STUB_LEDGER)

        monkeypatch.setattr(cm, "ai_human_agreement_rate", _ledger_spy)
        _patch_ledger_stubs(monkeypatch)
        _patch_other_metric_stubs(monkeypatch)
        at = AppTest.from_string(_METRICS_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        metrics = {m.label: m.value for m in at.metric}
        assert metrics.get("AI-人一致率") == "75.0%"      # 逐特征真值，非台账 0.6
        assert ledger_calls == []                         # 回退链未触发台账取数
        caption_text = "".join(str(c.value) for c in at.caption)
        assert "逐特征口径（8 提交）" in caption_text
        assert "ai_draft_snapshot" in caption_text
        assert "提案对照口径" not in caption_text

    def test_no_snapshot_falls_back_to_ledger(self, monkeypatch):
        """快照面无数据 → 回退台账口径：caption 标「提案对照口径」。"""
        monkeypatch.setattr(cm, "feature_level_agreement_rate",
                            lambda *a, **k: dict(_STUB_FEATURE_EMPTY))
        monkeypatch.setattr(cm, "ai_human_agreement_rate",
                            lambda: dict(_STUB_LEDGER))
        _patch_ledger_stubs(monkeypatch)
        _patch_other_metric_stubs(monkeypatch)
        at = AppTest.from_string(_METRICS_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        metrics = {m.label: m.value for m in at.metric}
        assert metrics.get("AI-人一致率") == "60.0%"      # 台账口径真值
        caption_text = "".join(str(c.value) for c in at.caption)
        assert "提案对照口径" in caption_text
        assert "ai_proposals" in caption_text
        assert "逐特征口径" not in caption_text

    def test_db_offline_grey_note_not_zero(self, monkeypatch):
        """快照面无数据＋台账侧库不可用 → 整卡灰注（值「—」＋降级文案，
        不是 0%）。"""
        monkeypatch.setattr(cm, "feature_level_agreement_rate",
                            lambda *a, **k: dict(_STUB_FEATURE_EMPTY))

        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(cm, "get_db_cursor", _boom)
        _patch_ledger_stubs(monkeypatch)
        _patch_other_metric_stubs(monkeypatch)
        at = AppTest.from_string(_METRICS_TAB_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        metrics = {m.label: m.value for m in at.metric}
        assert metrics.get("AI-人一致率") == "—"
        caption_text = "".join(str(c.value) for c in at.caption)
        assert "数据库不可用" in caption_text
        assert "灰注" in caption_text

    def test_tool_path_preserved_without_draft(self):
        """捕获点分流哨兵（源码级）：无草稿（ai_draft=None）时 FX-35 工具优先
        接线原样保留；带草稿才走直调传快照（AppTest 表单链路见 fx35 等价锁，
        其 _SENSE 无 llm_* 字段恰好覆盖工具路径）。"""
        import inspect

        import src.app as app_module

        src = inspect.getsource(app_module.render_submission_flow)
        seg_start = src.find("_admission_tool = get_tool")
        seg_end = src.find("if _submitted:")
        assert seg_start != -1 and seg_end != -1 and seg_start < seg_end
        segment = src[seg_start:seg_end]
        assert "if _admission_tool is not None and _ai_draft is None:" in segment
        assert "ai_draft=_ai_draft" in segment


# ============================================
# 6) 真库集成（web_word_fx43_test；无 MySQL 整类 skip）
# ============================================
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


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过 FX43 集成测试")
class TestFx43RealDb:
    """快照列迁移/落库形态/逐特征一致率端到端跑在真实 MySQL 8.0（独立测试库）。"""

    @pytest.fixture
    def fx43_db(self, monkeypatch):
        original_database = db.MYSQL_DATABASE
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
                "COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(f"USE {TEST_DB}")
        except pymysql.err.OperationalError as e:
            conn.close()
            pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX43 集成测试: {e}")
        conn.commit()

        monkeypatch.setattr(db, "MYSQL_DATABASE", TEST_DB)
        db._register_category_study_tables()
        db._register_zh_dict_tables()
        for table_sql in db.CREATE_TABLES_SQL:
            cur.execute(table_sql)
        conn.commit()
        conn.close()

        from src.users_db import create_user, ensure_user_tables

        ensure_user_tables()
        ensure_flow_tables()  # 建三表 + FX-20 两列 + FX-43 快照列迁移

        # 种子：1 词条 1 义项 + 2 标注员
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO definitions (verb, chinese_ndef, semantic_table) "
                "VALUES (%s, %s, %s)",
                ("run", "跑", json.dumps({"manner": "x"})),
            )
            definition_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO oald_senses (definition_id, sense_index, definition, "
                "headword) VALUES (%s, %s, %s, %s)",
                (definition_id, 1, "to move fast on foot", "run"),
            )
            sense_id = cursor.lastrowid

        coder_a = create_user("fx43_alice", "pw123456", "快照员甲", "annotator")
        coder_b = create_user("fx43_bob", "pw123456", "快照员乙", "annotator")
        assert all(isinstance(u, int) for u in (coder_a, coder_b))

        yield {"sense_id": sense_id, "coder_a": coder_a, "coder_b": coder_b}

        monkeypatch.setattr(db, "MYSQL_DATABASE", original_database)
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.commit()
        conn.close()

    @staticmethod
    def _snapshot_of(sense_id: int, coder_id: int):
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT payload, ai_draft_snapshot FROM annotation_submissions "
                "WHERE sense_id = %s AND coder_id = %s AND task_type = 'admission'",
                (sense_id, coder_id),
            )
            return cursor.fetchone()

    def test_migration_adds_json_null_column(self, fx43_db):
        """建旧形 → 探测补列：ensure_flow_tables 后快照列在库且可空。"""
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COLUMN_NAME, IS_NULLABLE, DATA_TYPE FROM "
                "information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND "
                "TABLE_NAME = 'annotation_submissions' AND "
                "COLUMN_NAME = 'ai_draft_snapshot'",
                (TEST_DB,),
            )
            row = cursor.fetchone()
        assert row is not None
        assert row["IS_NULLABLE"] == "YES" and row["DATA_TYPE"] == "json"

    def test_migration_idempotent_second_run(self, fx43_db):
        """二次 ensure_flow_tables 不炸不重复加列（真库 information_schema
        是活的：探测命中直接跳过）。"""
        ensure_flow_tables()
        ensure_flow_tables()  # 不应 raise
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.COLUMNS WHERE "
                "TABLE_SCHEMA = %s AND TABLE_NAME = 'annotation_submissions' "
                "AND COLUMN_NAME = 'ai_draft_snapshot'",
                (TEST_DB,),
            )
            assert cursor.fetchone()["n"] == 1

    def test_submit_with_draft_roundtrip_cjk(self, fx43_db):
        """带草稿提交 → 快照列原样往返（ensure_ascii=False 中文不转义；
        PyMySQL 对 JSON 列给 str 且键序经 MySQL 归一 —— parse_payload 解析
        后与原 dict 深比）。"""
        sense_id, coder = fx43_db["sense_id"], fx43_db["coder_a"]
        assert submit_annotation("motion", sense_id, "admission", coder,
                                 _VALID_PAYLOAD, ai_draft=_VALID_DRAFT)
        row = self._snapshot_of(sense_id, coder)
        assert row is not None
        assert "方式伴随图式" in str(row["ai_draft_snapshot"])  # 中文直存实证
        assert flow.parse_payload(row["ai_draft_snapshot"]) == _VALID_DRAFT
        assert flow.parse_payload(row["payload"]) == _VALID_PAYLOAD

    def test_submit_without_draft_stores_null(self, fx43_db):
        """不带草稿提交 → 快照列 NULL（RV2-3：无草稿不用空对象冒充）。"""
        sense_id, coder = fx43_db["sense_id"], fx43_db["coder_b"]
        assert submit_annotation("motion", sense_id, "admission", coder,
                                 _VALID_PAYLOAD)
        row = self._snapshot_of(sense_id, coder)
        assert row is not None and row["ai_draft_snapshot"] is None

    def test_resubmit_overwrite_then_legacy_keep(self, fx43_db):
        """覆盖更新两态：带新草稿 → 快照同步覆盖；不带草稿（旧调用形态）→
        快照保持不动（SQL 不含快照列 = 与列缺省行为完全一致）。"""
        sense_id, coder = fx43_db["sense_id"], fx43_db["coder_a"]
        assert submit_annotation("motion", sense_id, "admission", coder,
                                 _VALID_PAYLOAD, ai_draft={"admission": "Y"})
        assert submit_annotation("motion", sense_id, "admission", coder,
                                 _VALID_PAYLOAD,
                                 ai_draft={"admission": "N", "reason": "改判"})
        row = self._snapshot_of(sense_id, coder)
        assert flow.parse_payload(row["ai_draft_snapshot"]) == {
            "admission": "N", "reason": "改判"}
        # 旧调用形态覆盖：快照列不出现在语句里 → 旧行快照保持
        assert submit_annotation("motion", sense_id, "admission", coder,
                                 _VALID_PAYLOAD)
        row = self._snapshot_of(sense_id, coder)
        assert flow.parse_payload(row["ai_draft_snapshot"]) == {
            "admission": "N", "reason": "改判"}

    def test_feature_level_rate_end_to_end(self, fx43_db):
        """逐特征一致率端到端：种子三态提交 → rate/matched/n_features/
        n_submissions 对表（3 人：全一致/部分一致/键缺失）。"""
        sense_id = fx43_db["sense_id"]
        coder_a, coder_b = fx43_db["coder_a"], fx43_db["coder_b"]

        # coder_a 全一致（3 键同值；payload 多 needs_review 单侧独有不计）
        assert submit_annotation(
            "motion", sense_id, "admission", coder_a,
            {"admission": "Y", "schema": "方式伴随图式", "alignment": "完全对齐",
             "needs_review": False},
            ai_draft={"admission": "Y", "schema": "方式伴随图式",
                      "alignment": "完全对齐"})
        # coder_b 部分一致（admission 异值可比不入分子；alignment 同值入分子）
        assert submit_annotation(
            "motion", sense_id, "alignment", coder_b,
            {"admission": "EXT", "alignment": "完全对齐", "needs_review": True},
            ai_draft={"admission": "N", "alignment": "完全对齐"})
        # 第 3 条：快照仅 reason（键缺失，可比 0）
        assert submit_annotation(
            "motion", sense_id, "feature_coding", coder_a,
            {"features": {"P1": 1}},
            ai_draft={"reason": "只给理由"})

        r = cm.feature_level_agreement_rate()
        assert r["n_submissions"] == 3
        assert r["n_features"] == 5
        assert r["matched"] == 4
        assert r["rate"] == 0.8

        # 过滤面：task_type=admission 只见 coder_a 一条（3/3）
        r_adm = cm.feature_level_agreement_rate(task_type="admission")
        assert r_adm["n_submissions"] == 1 and r_adm["rate"] == 1.0
        # 过滤面：category 不匹配 → 零值面（不是 0%）
        r_other = cm.feature_level_agreement_rate(category="speech")
        assert r_other == {"rate": None, "n_submissions": 0,
                           "n_features": 0, "matched": 0}

    def test_db_offline_degrades_zero_face(self, fx43_db, monkeypatch):
        """真库环境下断库 → 零值面（不抛异常，消费方维持回退）。"""

        def _boom():
            raise pymysql.Error("fake connection failure")

        monkeypatch.setattr(cm, "get_db_cursor", _boom)
        assert cm.feature_level_agreement_rate() == {
            "rate": None, "n_submissions": 0, "n_features": 0, "matched": 0}
