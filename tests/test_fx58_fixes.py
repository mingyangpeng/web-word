"""FX-58 批次修复测试（RV24-2 / RV24-5 / RV25-2 / RV24-8 / RV19-6）。

对应修复清单（RV-24/RV-25 审出，FX-58 逐条落地）：

  * RV24-2 P2 —— annotation_flow.submit_annotation 无草稿重提清残留快照：
    覆盖更新走带快照列分支 ai_draft_snapshot = NULL（曾带草稿提交的同义位
    重提不再残留旧快照，下游 _fetch_snapshot_submissions 不再把它当带快照
    提交聚合，AI-人一致率公开指标不出假分歧）；纯旧库列缺失（未跑 FX-43
    迁移）时 MySQL 1054 回落旧语句（列缺失时旧 SQL 不变）；
  * RV24-5 P3 —— mysql_db 头部 ALTER-only 清单去失真：补
    annotation_submissions.ai_draft_snapshot（归属 src/annotation_flow.py
    的 FX-43 迁移），cs_clusters.merged_into 笔误改 cs_senses.merged_into
    （cluster_analysis 分立迁移 ＋ annotation_flow 台账读面两处补列）；
  * RV25-2 P2 —— 撰写台暂存陈旧重放双保险：「💾 保存草稿」成功路径
    delete_draft 使暂存失效（保存成功即暂存失效——暂存只覆盖未保存内容）；
    恢复侧 _apply_stash_defaults：暂存 based_on_version 落后当前最新版号
    → 旧暂存文不回填编辑框（基线已前进，暂存仅存档可查），页面 st.expander
    只读收纳旧文本；
  * RV24-8 P3 —— template_revision_db.save_revision 1062 逐因：UNIQUE
    兜底命中返回专项文案「并发保存冲突（他人刚保存一版），请重试」，
    不再泛化「数据库写入失败」；
  * RV19-6 同型补 —— collab_metrics._fetch_snapshot_submissions 取数上限
    200（行含 payload ＋ ai_draft_snapshot 双 MEDIUMTEXT/JSON 大文本列）。

外部依赖隔离（fx43 三段同款）：假游标用例不连库；页面用例打桩 wp.st 与
数据面函数，不依赖库内容（本文件无真库类 —— RV24-2 端到端由 fx43 真库
adapted 用例 test_resubmit_overwrite_then_clear_snapshot 覆盖）。
"""

import inspect
import json
import logging
import os
import sys

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.annotation_flow as flow  # noqa: E402
import src.collab_metrics as cm  # noqa: E402
from src import template_revision_db as trd  # noqa: E402
from src import ui_kit  # noqa: E402
from src import user_context_db as ucdb  # noqa: E402
from src import writing_pages as wp  # noqa: E402
from src.annotation_flow import submit_annotation  # noqa: E402


# ============================================
# 假游标基建（fx43 _FakeCursor 同款最小件）
# ============================================
class _Ctx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class _FakeCursor:
    """记录型假游标：execute 只记录不供行（SELECT 面 fetchone → None）。"""

    def __init__(self):
        self.executed = []  # [(sql, params)]

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


# ============================================
# 1) RV24-2：无草稿重提清残留快照
# ============================================
class TestRv24_2NoDraftClearsSnapshotSql:
    """submit_annotation 无草稿分支：清残留快照语句 ＋ 旧库 1054 回落。"""

    def test_no_draft_upsert_uses_clear_snapshot_sql(self, monkeypatch):
        """无草稿（ai_draft=None）→ 覆盖更新 ai_draft_snapshot = NULL：
        曾带草稿提交的同义位重提不再残留旧快照；快照不占参数位（params 仍
        6 元，旧调用点零适配）。"""
        cursor = _FakeCursor()
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
        assert submit_annotation("motion", 501, "admission", 12,
                                 {"admission": "Y", "needs_review": False})
        sql, params = cursor.executed[-1]
        assert "ai_draft_snapshot = NULL" in sql
        assert "VALUES(ai_draft_snapshot)" not in sql
        assert len(params) == 6
        assert params[:4] == ("motion", 501, "admission", 12)

    def test_degraded_draft_clears_snapshot_too(self, monkeypatch, caplog):
        """非 dict/空 dict 草稿降级同 None → 同走清残留分支（RV2-3 不用空
        对象冒充有草稿；快照脏值不拦提交本体）。"""
        cursor = _FakeCursor()
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
        with caplog.at_level(logging.WARNING, logger="src.annotation_flow"):
            assert submit_annotation("motion", 501, "admission", 12,
                                     {"admission": "Y"}, ai_draft={})
        sql, _ = cursor.executed[-1]
        assert "ai_draft_snapshot = NULL" in sql

    def test_legacy_db_1054_falls_back_to_old_sql(self, monkeypatch, caplog):
        """纯旧库列缺失（未跑 FX-43 迁移）→ 清残留语句撞 MySQL 1054 →
        回落旧语句重试成功（列缺失时旧 SQL 不变，不让清残留能力挡老库提交）。"""

        class _NoSnapshotColCursor(_FakeCursor):
            """快照列缺失桩：SQL 涉 ai_draft_snapshot 即 1054，其余照录。"""

            def execute(self, sql, params=None):
                if "ai_draft_snapshot" in sql:
                    raise pymysql.err.OperationalError(
                        1054, "Unknown column 'ai_draft_snapshot' in "
                        "'field list'")
                self.executed.append((sql, params))

        cursor = _NoSnapshotColCursor()
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
        with caplog.at_level(logging.INFO, logger="src.annotation_flow"):
            assert submit_annotation("motion", 501, "admission", 12,
                                     {"admission": "Y"})
        assert len(cursor.executed) == 1
        sql, params = cursor.executed[0]
        assert "ai_draft_snapshot" not in sql          # 旧语句形态
        assert "ON DUPLICATE KEY UPDATE" in sql
        assert len(params) == 6
        assert any("1054" in r.getMessage() or "回落旧语句" in r.getMessage()
                   for r in caplog.records)

    def test_1054_fallback_failure_still_returns_false(self, monkeypatch):
        """旧库回落语句也失败（断连等）→ False 不抛（提交本体降级口径不变）。"""

        class _AlwaysBoomCursor(_FakeCursor):
            def execute(self, sql, params=None):
                if "ai_draft_snapshot" in sql:
                    raise pymysql.err.OperationalError(1054, "Unknown column")
                raise pymysql.err.OperationalError(2003, "db down")

        monkeypatch.setattr(
            flow, "get_db_cursor",
            lambda autocommit=True: _Ctx(_AlwaysBoomCursor()))
        assert submit_annotation("motion", 501, "admission", 12,
                                 {"admission": "Y"}) is False

    def test_with_draft_upsert_unchanged(self, monkeypatch):
        """带草稿提交语句形态不回归：快照随新提交同步覆盖（VALUES 赋值）。"""
        cursor = _FakeCursor()
        monkeypatch.setattr(flow, "get_db_cursor", lambda autocommit=True: _Ctx(cursor))
        assert submit_annotation("motion", 501, "admission", 12,
                                 {"admission": "Y"},
                                 ai_draft={"admission": "N"})
        sql, params = cursor.executed[-1]
        assert "ai_draft_snapshot = VALUES(ai_draft_snapshot)" in sql
        assert len(params) == 7

    def test_docstring_states_new_contract(self):
        """docstring 口径变更钉板：清残留语义在位，「逐字节一致」约束如实
        注明放弃（RV24-2）。"""
        doc = inspect.getdoc(flow.submit_annotation) or ""
        assert "无草稿重提清残留快照" in doc
        assert "假比对污染公开指标" in doc
        assert "约束放弃" in doc
        assert "1054 回落旧语句" in doc

    def test_upsert_constants_shape(self):
        """三形态语句常量：清残留 vs 旧语句仅差快照行；带草稿形态照旧。"""
        clear = flow._UPSERT_NO_DRAFT_CLEAR_SNAPSHOT
        legacy = flow._UPSERT_NO_DRAFT_LEGACY
        with_draft = flow._UPSERT_WITH_DRAFT_SNAPSHOT
        assert "ai_draft_snapshot = NULL" in clear
        assert "ai_draft_snapshot" not in legacy
        assert "ai_draft_snapshot = VALUES(ai_draft_snapshot)" in with_draft
        # 除快照行外三语句共享同一 upsert 骨架（覆盖语义一致）
        for stem in ("INSERT INTO annotation_submissions",
                     "ON DUPLICATE KEY UPDATE",
                     "status = 'submitted'",
                     "submitted_at = CURRENT_TIMESTAMP"):
            assert stem in clear and stem in legacy and stem in with_draft

    def test_unknown_column_error_predicate(self):
        """1054 判定：命中 1054；不误吞 1060/1062/文案型错误。"""
        assert flow._is_unknown_column_error(
            pymysql.err.OperationalError(1054, "Unknown column")) is True
        for exc in (pymysql.err.InternalError(1060, "Duplicate column"),
                    pymysql.err.InternalError(1062, "Duplicate entry"),
                    pymysql.Error("db down")):
            assert flow._is_unknown_column_error(exc) is False


class _StashStoreCursor(_FakeCursor):
    """annotation_submissions upsert 语义的最小状态机桩：
    key=(category, sense_id, task_type, coder_id)；带草稿语句落草稿 JSON，
    清残留语句置 None，旧语句（无快照列）不动既有行、新行落列默认 None ——
    恰好是三形态语句在真实库上的行效果。"""

    def __init__(self):
        super().__init__()
        self.store = {}  # key -> draft_json|None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "INSERT INTO annotation_submissions" in sql:
            category, sense_id, task_type, coder_id = params[:4]
            key = (category, sense_id, task_type, coder_id)
            if "VALUES(ai_draft_snapshot)" in sql:
                self.store[key] = params[-1]        # 带草稿：快照随新提交覆盖
            elif "ai_draft_snapshot = NULL" in sql:
                self.store[key] = None              # RV24-2：清残留快照
            else:
                self.store.setdefault(key, None)    # 旧语句：列缺省不动旧行


class TestRv24_2FetchStopsAggregatingStaleRow:
    """端到端（桩库）：曾带草稿提交 → 无草稿重提 → 快照 NULL →
    _fetch_snapshot_submissions 不再聚合该行（AI-人一致率不出假分歧）。"""

    def _patch_flow_store(self, monkeypatch):
        cursor = _StashStoreCursor()
        monkeypatch.setattr(flow, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        return cursor

    def _patch_cm_rows(self, monkeypatch, cursor):
        """cm 取数面打桩：每次 SELECT 现取 store 快照（payload 固定 N，
        快照列随 store 实况），「读库是活的」语义。"""
        payload_json = json.dumps({"admission": "N"}, ensure_ascii=False)
        read = _FakeCursor()
        read._current = []

        def _execute(sql, params=None):
            read.executed.append((sql, params))
            if "ai_draft_snapshot IS NOT NULL" in sql:
                read._current = [
                    {"payload": payload_json, "ai_draft_snapshot": snap}
                    for snap in list(cursor.store.values())]
                return
            read._current = []

        read.execute = _execute

        def _fetchall():
            return list(read._current)

        read.fetchall = _fetchall
        monkeypatch.setattr(cm, "get_db_cursor",
                            lambda autocommit=True: _Ctx(read))
        return read

    def test_resubmit_without_draft_drops_stale_aggregation(self, monkeypatch):
        cursor = self._patch_flow_store(monkeypatch)
        key = ("motion", 501, "admission", 12)
        # 1) 曾带草稿提交（AI 给 Y，人工交 N —— 会产生假分歧比对）
        assert submit_annotation("motion", 501, "admission", 12,
                                 {"admission": "N"},
                                 ai_draft={"admission": "Y"})
        assert cursor.store[key] == json.dumps({"admission": "Y"},
                                               ensure_ascii=False)
        self._patch_cm_rows(monkeypatch, cursor)
        before = cm.feature_level_agreement_rate()
        assert before["n_submissions"] == 1
        assert before["matched"] == 0 and before["n_features"] == 1
        # 2) 无草稿重提（本次纯人工）→ 清残留
        assert submit_annotation("motion", 501, "admission", 12,
                                 {"admission": "N"})
        assert cursor.store[key] is None
        # 3) 不再聚合该行（「还没数据」零值面，不拿新 payload 对旧草稿假比对）
        after = cm.feature_level_agreement_rate()
        assert after == {"rate": None, "n_submissions": 0, "n_features": 0,
                         "matched": 0}


# ============================================
# 2) RV24-5：ALTER-only 清单去失真
# ============================================
class TestRv24_5AlterOnlyListTruth:
    """mysql_db 头部 ALTER-only 清单与实况互钉（清单失真即测试报警）。"""

    def _mysql_db_text(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "mysql_db.py")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_lists_ai_draft_snapshot_with_owner_module(self):
        """补 annotation_submissions.ai_draft_snapshot 条目，且文件归属写对：
        迁移实现在 src/annotation_flow.py（FX-43），不在本模块。"""
        text = self._mysql_db_text()
        assert "annotation_submissions.ai_draft_snapshot" in text
        entry_idx = text.index("annotation_submissions.ai_draft_snapshot")
        nearby = text[entry_idx:entry_idx + 200]
        assert "src/annotation_flow.py" in nearby
        assert "FX-43" in nearby

    def test_cs_senses_merged_into_not_cs_clusters(self):
        """merged_into 表名笔误修正：清单条目为 cs_senses.merged_into
        （cluster_analysis 分立迁移 ＋ annotation_flow 台账读面两处补列）；
        cs_clusters.merged_into 字样在本模块绝迹。"""
        text = self._mysql_db_text()
        assert "cs_senses.merged_into" in text
        assert "cs_clusters.merged_into" not in text

    def test_migration_really_lives_in_annotation_flow(self):
        """清单条目与实况互证：ai_draft_snapshot 的 ALTER 迁移确实在
        annotation_flow（SUBMISSION_AI_DRAFT_COLUMNS /
        _migrate_submissions_ai_draft_column），merged_into 的台账读面补列
        也在 annotation_flow（_ensure_divided_cols）。"""
        assert [c for c, _ in flow.SUBMISSION_AI_DRAFT_COLUMNS] == [
            "ai_draft_snapshot"]
        sql = flow.SUBMISSION_AI_DRAFT_COLUMNS[0][1]
        assert sql.startswith("ALTER TABLE annotation_submissions ADD COLUMN")
        assert callable(flow._migrate_submissions_ai_draft_column)
        flow_src = inspect.getsource(flow)
        assert "ALTER TABLE cs_senses ADD COLUMN merged_into" in flow_src

    def test_cluster_analysis_owns_merged_into_migration(self):
        """merged_into 的另一补列点在 cluster_analysis 分立迁移。"""
        import src.cluster_analysis as ca

        src_text = inspect.getsource(ca)
        assert "ADD COLUMN `merged_into` INT NULL" in src_text
        assert '_ensure_sense_split_columns_for("cs_senses")' in src_text


# ============================================
# 3) RV25-2：撰写台暂存陈旧重放双保险
# ============================================
_WP_SENSE = {
    "cs_sense_id": 77, "sense_no": "1",
    "sense_label": "cause to go from one place to another",
    "status": "locked", "lemma": "move", "language": "en",
    "category_code": "motion", "category_name": "移动",
    "cluster_id": 5, "cluster_no": 3, "locked": True,
}
_WP_ME = {"id": 901, "username": "fx58", "display_name": "FX58 用户",
          "role": "admin"}
_WP_FORM_KEY = "writing_draft_77"
# update 态基线：本人自有在途草稿 v2
_WP_LATEST_OWN_DRAFT = {
    "id": 11, "version": 2, "status": "draft", "author_id": 901,
    "content": "自有草稿内容", "style_version": "style.yaml@v1",
    "based_on_version": None,
}
# rejected 态基线：被拒 v3（打回重提 prefill）
_WP_LATEST_REJECTED = {
    "id": 12, "version": 3, "status": "rejected", "author_id": 901,
    "content": "被拒内容v3", "style_version": "style.yaml@v1",
    "based_on_version": None,
}


class _StubSt:
    """st 假体（fx39 _StubSt 同款最小件）：记录调用，button 按 key 点击。"""

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def __init__(self, *, click_keys=(), text_values=None):
        self.markdowns, self.captions = [], []
        self.errors, self.infos, self.warnings, self.successes = [], [], [], []
        self.buttons, self.text_widgets, self.selects, self.radios = [], [], [], []
        self.expanders = []
        self.rerun_count = 0
        self._click_keys = set(click_keys)
        self._text_values = dict(text_values or {})

    def markdown(self, text, **kw):
        self.markdowns.append(text)

    def caption(self, text):
        self.captions.append(text)

    def error(self, text):
        self.errors.append(text)

    def info(self, text):
        self.infos.append(text)

    def warning(self, text):
        self.warnings.append(text)

    def success(self, text):
        self.successes.append(text)

    def button(self, label, **kw):
        self.buttons.append((label, kw))
        return kw.get("key") in self._click_keys

    def text_area(self, label, value="", **kw):
        self.text_widgets.append(("text_area", label, value, kw))
        return self._text_values.get(kw.get("key"), value)

    def text_input(self, label, value="", **kw):
        self.text_widgets.append(("text_input", label, value, kw))
        return self._text_values.get(kw.get("key"), value)

    def selectbox(self, label, options, **kw):
        self.selects.append((label, list(options)))
        return options[0] if options else None

    def radio(self, label, options, **kw):
        self.radios.append((label, list(options)))
        return options[0] if options else None

    def columns(self, n):
        count = len(n) if isinstance(n, (list, tuple)) else n
        return [self._Ctx() for _ in range(count)]

    def expander(self, label=None, **kw):
        self.expanders.append(label)
        return self._Ctx()

    def rerun(self):
        self.rerun_count += 1


def _widget_value(stub, key):
    for _kind, _label, value, kw in stub.text_widgets:
        if kw.get("key") == key:
            return value
    return None


class TestRv25_2StashFreshness:
    """撰写台暂存陈旧重放双保险（RV25-2）。"""

    def _render_write(self, monkeypatch, *, latest=None, stash_state=None,
                      click_keys=()):
        """渲染撰写台（数据面全打桩；返回 (stub, dels, updates)）。"""
        flashes: list = []
        monkeypatch.setattr(ui_kit, "flash",
                            lambda msg, level="success": flashes.append(msg))
        dels: list = []
        monkeypatch.setattr(ucdb, "delete_draft",
                            lambda key: dels.append(key) or True)
        monkeypatch.setattr(ucdb, "upsert_draft", lambda key, state: True)
        rows = []
        if stash_state is not None:
            rows.append({
                "id": 1, "form_key": _WP_FORM_KEY,
                "state_json": json.dumps(stash_state, ensure_ascii=False),
                "created_at": "2026-11-10 08:00:00",
                "updated_at": "2026-11-10 09:30:00",
            })
        monkeypatch.setattr(ucdb, "list_drafts", lambda limit=500: rows)
        updates: list = []
        monkeypatch.setattr(
            wp.writing_db, "update_draft",
            lambda vid, expect, content, style_version=None, ai_draft=None,
            **kw: updates.append((vid, expect, content, style_version)) or True)
        creates: list = []
        monkeypatch.setattr(
            wp.writing_db, "create_draft",
            lambda ref_arg, uid, content_arg, **kw:
            creates.append((ref_arg, uid, content_arg,
                            kw.get("based_on_version"))) or 13)
        monkeypatch.setattr(wp.writing_db, "get_cluster_lock_state",
                            lambda *a, **k: None)
        monkeypatch.setattr(wp.writing_db, "get_latest_version",
                            lambda ref, viewer_id=None: latest)
        monkeypatch.setattr(wp, "_list_categories_dicts",
                            lambda: [{"code": "motion", "name_cn": "移动"}])
        monkeypatch.setattr(wp, "_list_candidate_senses",
                            lambda cat, lang: [dict(_WP_SENSE)])
        monkeypatch.setattr(wp, "_resolve_oald_sense_id", lambda lemma, no: 345)
        monkeypatch.setattr(wp, "_template_preview", lambda *a: None)
        monkeypatch.setattr(
            wp, "_reviewer_options",
            lambda me: [{"id": 202, "label": "审校员（uid 202）"}])
        stub = _StubSt(click_keys=click_keys)
        monkeypatch.setattr(wp, "st", stub)
        wp._render_write_tab(_WP_ME)
        return stub, dels, updates

    # -- 恢复侧双保险：基线落后不回填 --

    def test_stale_stash_not_refilled_into_editor(self, monkeypatch):
        """暂存 based_on_version=2 落后最新 v3（被拒打回重提态）→ 编辑框
        默认值保持 target prefill（旧暂存文不回填）；警示 caption＋expander
        只读存档。"""
        stub, _, _ = self._render_write(
            monkeypatch, latest=_WP_LATEST_REJECTED,
            stash_state={"content": "暂存的旧底稿",
                         "style_version": "style.yaml@v2",
                         "based_on_version": 2})
        assert _widget_value(stub, "writing_content_0_3") == "被拒内容v3"
        assert any("基线已前进，暂存仅存档可查" in c for c in stub.captions)
        assert any("旧暂存存档" in e for e in stub.expanders)
        # 旧暂存文本只读可见（expander 内 markdown 收纳）
        assert any("暂存的旧底稿" in m for m in stub.markdowns)
        # 不得假报「已恢复暂存草稿」（未回填就不叫恢复）
        assert not any("已恢复暂存草稿" in c for c in stub.captions)

    def test_fresh_stash_still_restored(self, monkeypatch):
        """回归锁：暂存基线 = 当前最新（v2）→ 照常回填编辑框（RV25-2 只拦
        「落后」态，不伤正常恢复）。"""
        stub, _, _ = self._render_write(
            monkeypatch, latest=_WP_LATEST_OWN_DRAFT,
            stash_state={"content": "暂存的新文",
                         "style_version": "style.yaml@v9",
                         "based_on_version": 2})
        assert _widget_value(stub, "writing_content_11_2") == "暂存的新文"
        assert any("已恢复暂存草稿" in c for c in stub.captions)
        assert not any("旧暂存存档" in e for e in stub.expanders)

    def test_apply_stash_defaults_stale_contract(self):
        """纯函数契约：落后态 (content_default=prefill, restore=None,
        base=存档警示)；相等态照旧回填。"""
        target = {"mode": "create", "target_id": None, "expect_version": None,
                  "prefill": "被拒内容v3", "based_on_version": 3,
                  "notice": None}
        stashed = {"state": {"content": "旧文", "style_version": "v2",
                             "based_on_version": 2},
                   "updated_at": "2026-11-10 09:30:00"}
        content, style, restore, base = wp._apply_stash_defaults(
            stashed, target, {"id": 12, "version": 3})
        assert content == "被拒内容v3"
        assert restore is None
        assert base and "基线已前进，暂存仅存档可查" in base
        latest_equal = {"id": 11, "version": 2, "status": "draft",
                        "author_id": 901, "content": "自有草稿内容",
                        "style_version": "style.yaml@v1"}
        target_u = {"mode": "update", "target_id": 11, "expect_version": 2,
                    "prefill": "自有草稿内容", "based_on_version": None,
                    "notice": None}
        content2, style2, restore2, base2 = wp._apply_stash_defaults(
            stashed, target_u, latest_equal)
        assert content2 == "旧文" and style2 == "v2"
        assert restore2 and "提交后自动清除" in restore2
        assert base2 is None

    # -- 保存侧：保存成功即暂存失效 --

    def test_save_draft_success_deletes_stash_update_mode(self, monkeypatch):
        """update 态保存成功 → delete_draft(form_key)（暂存失效，防止版本
        前进换 content_key 后陈旧暂存重放）。"""
        stub, dels, updates = self._render_write(
            monkeypatch, latest=_WP_LATEST_OWN_DRAFT,
            stash_state={"content": "暂存文", "based_on_version": 2},
            click_keys={"writing_save_draft"})
        assert updates and updates[0][:2] == (11, 2)   # 乐观锁目标照旧
        assert dels == [_WP_FORM_KEY]
        assert stub.successes

    def test_save_draft_success_deletes_stash_create_mode(self, monkeypatch):
        """create 态（打回重提）保存成功 → 同样 delete_draft(form_key)。"""
        stub, dels, _ = self._render_write(
            monkeypatch, latest=_WP_LATEST_REJECTED,
            stash_state={"content": "暂存文", "based_on_version": 3},
            click_keys={"writing_save_draft"})
        assert dels == [_WP_FORM_KEY]
        assert stub.successes

    def test_save_draft_failure_keeps_stash(self, monkeypatch):
        """保存失败（乐观锁拦截）→ 不清暂存（暂存仍覆盖未保存内容）。"""
        flashes: list = []
        monkeypatch.setattr(ui_kit, "flash",
                            lambda msg, level="success": flashes.append(msg))
        dels: list = []
        monkeypatch.setattr(ucdb, "delete_draft",
                            lambda key: dels.append(key) or True)
        monkeypatch.setattr(ucdb, "upsert_draft", lambda key, state: True)
        monkeypatch.setattr(ucdb, "list_drafts", lambda limit=500: [])
        monkeypatch.setattr(
            wp.writing_db, "update_draft",
            lambda vid, expect, content, style_version=None, ai_draft=None,
            **kw: False)
        monkeypatch.setattr(wp.writing_db, "get_cluster_lock_state",
                            lambda *a, **k: None)
        monkeypatch.setattr(wp.writing_db, "get_latest_version",
                            lambda ref, viewer_id=None: _WP_LATEST_OWN_DRAFT)
        monkeypatch.setattr(wp, "_list_categories_dicts",
                            lambda: [{"code": "motion", "name_cn": "移动"}])
        monkeypatch.setattr(wp, "_list_candidate_senses",
                            lambda cat, lang: [dict(_WP_SENSE)])
        monkeypatch.setattr(wp, "_resolve_oald_sense_id", lambda lemma, no: 345)
        monkeypatch.setattr(wp, "_template_preview", lambda *a: None)
        monkeypatch.setattr(
            wp, "_reviewer_options",
            lambda me: [{"id": 202, "label": "审校员（uid 202）"}])
        stub = _StubSt(click_keys={"writing_save_draft"})
        monkeypatch.setattr(wp, "st", stub)
        wp._render_write_tab(_WP_ME)
        assert dels == []
        assert stub.errors

    def test_save_then_rerender_editor_has_no_stale_text(self, monkeypatch):
        """场景复现：暂存 → 保存草稿成功（清暂存）→ 重开撰写台（下一 render）
        → 编辑框不含陈旧暂存文（v2→v3 换 content_key 也不再重放）。"""
        stash_state = {"content": "陈旧暂存文", "style_version": "style.yaml@v1",
                       "based_on_version": 2}
        stub1, dels, _ = self._render_write(
            monkeypatch, latest=_WP_LATEST_OWN_DRAFT,
            stash_state=stash_state, click_keys={"writing_save_draft"})
        assert dels == [_WP_FORM_KEY]                  # 保存成功即暂存失效
        # 下一 render：暂存已清（rows=[]），编辑框默认值 = target prefill
        stub2, _, _ = self._render_write(
            monkeypatch, latest=_WP_LATEST_OWN_DRAFT, stash_state=None)
        assert _widget_value(stub2, "writing_content_11_2") == "自有草稿内容"
        assert not any("陈旧暂存文" in v for v in
                       [_widget_value(stub2, "writing_content_11_2")])
        assert not any("陈旧暂存文" in c for c in stub2.captions)

    def test_source_locks_delete_on_save_success(self):
        """源码级锁：_render_write_tab 的「💾 保存草稿」成功两分支（update/
        create）均 delete_draft；「保存成功即暂存失效」口径入注释。"""
        src = inspect.getsource(wp._render_write_tab)
        assert src.count("user_context_db.delete_draft(stash_form_key)") == 3
        seg_start = src.find("保存草稿（版本自动递增）")
        seg_end = src.find("**📨 提交初审**")
        assert seg_start != -1 and seg_end != -1 and seg_start < seg_end
        seg = src[seg_start:seg_end]
        assert seg.count("user_context_db.delete_draft(stash_form_key)") == 2
        assert "保存成功即暂存失效" in seg
        # 恢复侧 expander 存档在位
        assert "🗄️ 旧暂存存档" in src


# ============================================
# 4) RV24-8：save_revision 1062 逐因
# ============================================
class TestRv24_8SaveRevisionDuplicateEntry:
    """UNIQUE 兜底命中（MySQL 1062）→ 专项文案；其余错误维持通用降级。"""

    EDITOR = {"id": 2, "username": "editor_x", "roles": ["editor"]}

    def _patch_exec_error(self, monkeypatch, errno, msg):
        class _ErrCursor(_FakeCursor):
            def execute(self, sql, params=None):
                raise pymysql.err.InternalError(errno, msg)

        monkeypatch.setattr(trd, "get_db_cursor",
                            lambda autocommit=True: _Ctx(_ErrCursor()))

    def test_1062_yields_concurrent_conflict_reason(self, monkeypatch):
        self._patch_exec_error(
            monkeypatch, 1062,
            "Duplicate entry 'run-en-1-3' for key "
            "'uq_cat_lang_sense_ver'")
        result = trd.save_revision("run", "en", 1, "修订文本", self.EDITOR)
        assert result == {"ok": False,
                          "reason": "并发保存冲突（他人刚保存一版），请重试"}

    def test_non_1062_keeps_generic_reason(self, monkeypatch):
        for errno, exc_cls in ((2003, pymysql.err.OperationalError),
                               (1146, pymysql.err.OperationalError),
                               (1451, pymysql.err.InternalError)):
            self._patch_exec_error(monkeypatch, errno, f"err {errno}")
            result = trd.save_revision("run", "en", 1, "修订文本", self.EDITOR)
            assert result == {"ok": False, "reason": "数据库写入失败"}

    def test_docstring_and_module_note_updated(self):
        """「不撞 UNIQUE」过述改「UNIQUE 兜底＋1062 逐因」（docstring 钉板）。"""
        module_doc = inspect.getdoc(trd) or ""
        assert "不撞 UNIQUE" not in module_doc
        assert "UNIQUE" in module_doc and "1062" in module_doc
        fn_doc = inspect.getdoc(trd.save_revision) or ""
        assert "并发保存冲突（他人刚保存一版），请重试" in fn_doc
        assert "1062" in fn_doc


# ============================================
# 5) RV19-6：逐特征一致率取数上限 200
# ============================================
class TestRv19_6SnapshotFetchCap:
    """_fetch_snapshot_submissions LIMIT 恒有界（行含双 MEDIUMTEXT 大文本）。"""

    def _patch_cm_cursor(self, monkeypatch):
        cursor = _FakeCursor()
        monkeypatch.setattr(cm, "get_db_cursor",
                            lambda autocommit=True: _Ctx(cursor))
        return cursor

    def test_cap_constant_is_200(self):
        assert cm._SNAPSHOT_FETCH_CAP == 200

    def test_default_limit_is_cap(self, monkeypatch):
        cursor = self._patch_cm_cursor(monkeypatch)
        cm.feature_level_agreement_rate()
        assert cursor.executed[0][1] == (200,)

    def test_oversized_limit_capped(self, monkeypatch):
        """limit>200 → 压到 200（调大也不放行全表大字段拖回）。"""
        for big in (201, 500, 10_000):
            cursor = self._patch_cm_cursor(monkeypatch)
            cm.feature_level_agreement_rate(limit=big)
            assert cursor.executed[0][1] == (200,)

    def test_small_limit_passes_through(self, monkeypatch):
        """合法小值照旧透传（最近优先取数语义不变）。"""
        cursor = self._patch_cm_cursor(monkeypatch)
        cm.feature_level_agreement_rate("motion", "admission", limit=50)
        assert cursor.executed[0][1] == ("motion", "admission", 50)

    def test_invalid_limit_falls_to_cap(self, monkeypatch):
        """非法值（0/负数/bool/非 int）→ 回落上界 200。"""
        for bad in (0, -5, True, "500", None, 3.5):
            cursor = self._patch_cm_cursor(monkeypatch)
            cm._fetch_snapshot_submissions(None, None, bad)
            assert cursor.executed[0][1] == (200,)

    def test_direct_fetch_capped_too(self, monkeypatch):
        cursor = self._patch_cm_cursor(monkeypatch)
        cm._fetch_snapshot_submissions(None, None, 999)
        assert cursor.executed[0][1] == (200,)
