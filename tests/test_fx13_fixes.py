"""FX13 批次修复测试：R5-4~7 N+1 族真修（装配 / 脊柱 / 版本历史 / 模板批量取数）。

对应修复（docs/dev/reports/findings_backlog.md R5-4~7，FX13 批次）：

  * R5-4  装配 N+1（src/entry_assembly.py）——建模义项的子表取数（发布例证 /
          对译定稿 / 媒体绑定）与模板释义改为「一次 IN 批量取回按锚分组，
          内存装配」：_assembly_sections 先经 _build_assembly_prefetch 批量
          预取（失败逐条回退旧行为），_fetch_* 薄适配层优先命中请求级缓存。
          断言：批量分组结果与逐义项数据层取数**逐字段相等**；
          _assembly_sections 预取路径 vs 强制回退（修复前等价路径）七段输出
          逐字段相等；查询数 examples 3→1 / translations 3→1 / media 4→1、
          模板 3 义位 9→3。
  * R5-5  脊柱 N+1（src/sense_spine.py）——② 标注留痕原逐任务类型循环 3 查询
          → task_type IN 一次取回（组间 TASK_TYPES 序、组内 coder_id,id 序，
          行转换复用 annotation_flow 单一实现）；批量失败回退逐类查询。
          断言：输出与逐类拼接逐字段相等；3→1。
  * R5-6  版本历史 N+1（src/writing_db.py + writing_pages.py）——新增
          list_comments_for_versions：一次 version_id IN 取回按版本分组，
          版本历史 / 审校台替代逐版本 list_comments 循环（失败回退）。
          断言：分组结果与逐版本 list_comments 逐字段相等（含 only_open）；
          3 版本 3→1。
  * R5-7  模板逐义项 N+1（src/template_engine.py）——新增 _fetch_senses /
          instantiate_templates：一次 3 条查询取回全簇义位行 / 簇归属 /
          特征向量，逐义位纯函数实例化（母图式与范畴包同解共享）；
          collect_cluster_templates 改走批量。断言：批量实例化与逐义位
          instantiate_template 结果逐字段相等；3 成员 9→3；collect 输出
          与「修复前逐成员循环」等价。

外部依赖隔离：
  * 假游标用例不连库：monkeypatch 各模块 get_db_cursor，按 SQL 供行＋计数；
  * 真库用例（TestFx13RealDb）复用已授权测试库 web_word_stage1_e2e_test
    （scripts/grant_local_mysql.sql 已 GRANT ALL；与 stage1/stage2 e2e 同库 ——
    不可与之并行同跑，pytest 顺序执行下各自 DROP+CREATE 互不污染），
    MySQL 不可用 / 账号无建库权限整类 skip；
  * 空库 / 无库环境不崩：批量取数失败一律折叠为回退路径（fail-closed 用例）。
"""

import contextlib
import json
import os
import sys

import pymysql
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.annotation_flow as annotation_flow  # noqa: E402
import src.category_study as category_study  # noqa: E402
import src.entry_assembly as entry_assembly  # noqa: E402
import src.lexical_db as lexical_db  # noqa: E402
import src.media_db as media_db  # noqa: E402
import src.mysql_db as db  # noqa: E402
import src.sense_spine as sense_spine  # noqa: E402
import src.template_engine as template_engine  # noqa: E402
import src.writing_db as writing_db  # noqa: E402
from src.users_db import create_user, ensure_user_tables  # noqa: E402

TEST_DB = "web_word_stage1_e2e_test"  # 复用已授权测试库（不可与 stage1/2 e2e 并行）

PUBLISHED = "发布"
REVIEWED = "审定"
CANDIDATE = "候选"


def _db_available() -> bool:
    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


def _q(sql: str, params: tuple = ()):
    """真库直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


# ============================================
# 假游标基建（不连库：按 SQL 供行 + execute 计数）
# ============================================

def install_fake_cursor(monkeypatch, module, handler=None, boom=False,
                        executed=None):
    """module.get_db_cursor → 假游标。

    handler(sql, params) -> list[dict]（DictCursor 口径返回 dict 行）；
    boom=True 时 execute 抛 RuntimeError（模拟库不可用）；
    executed 追加 (sql, params) 供查询计数断言。返回 executed 列表。
    """
    executed = executed if executed is not None else []

    class _FakeCursor:
        def __init__(self):
            self._rows = []

        def execute(self, sql, params=None):
            executed.append((sql, params))
            if boom:
                raise RuntimeError("fx13 fake db down")
            self._rows = list(handler(sql, params)) if handler else []

        def fetchone(self):
            return dict(self._rows[0]) if self._rows else None

        def fetchall(self):
            return [dict(r) for r in self._rows]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    @contextlib.contextmanager
    def fake(*args, **kwargs):
        yield _FakeCursor()

    monkeypatch.setattr(module, "get_db_cursor", fake)
    return executed


def count_sql(executed, needle):
    """执行清单中含 needle 的 SQL 条数（查询计数证据用）。"""
    return sum(1 for sql, _ in executed if needle in sql)


# ============================================
# 打桩数据（R5-4 / R5-6 / R5-7 / R5-5 共用）
# ============================================

_REFS = ("33", "34", "35")

_EXAMPLE_ROWS = [
    {"id": 2, "sense_ref": "33", "content": "She runs daily.", "source": "adapted",
     "caption": "", "media_asset_id": None, "sort_order": 0, "status": PUBLISHED,
     "created_by": 7, "created_at": "2026-01-02 09:00:00"},
    {"id": 1, "sense_ref": "33", "content": "He ran home.", "source": "corpus",
     "caption": "fx13 例一", "media_asset_id": None, "sort_order": 1,
     "status": PUBLISHED, "created_by": 7, "created_at": "2026-01-01 09:00:00"},
    {"id": 3, "sense_ref": "34", "content": "Run the program.", "source": "composed",
     "caption": None, "media_asset_id": None, "sort_order": 5, "status": PUBLISHED,
     "created_by": 8, "created_at": "2026-01-03 09:00:00"},
    {"id": 4, "sense_ref": "35", "content": "审定态例证不进装配", "source": "corpus",
     "caption": "", "media_asset_id": None, "sort_order": 0, "status": REVIEWED,
     "created_by": 8, "created_at": "2026-01-04 09:00:00"},
]

_TRANSLATION_ROWS = [
    {"id": 11, "sense_ref": "33", "state": "full", "equivalent": "跑",
     "note": "", "paraphrase": None, "finalized_by": 7,
     "finalized_at": "2026-01-05 10:00:00", "updated_at": "2026-01-05 10:00:00"},
    {"id": 12, "sense_ref": "34", "state": "partial", "equivalent": "奔跑",
     "note": "fx13 括注", "paraphrase": None, "finalized_by": 8,
     "finalized_at": "2026-01-06 10:00:00", "updated_at": "2026-01-06 10:00:00"},
    # "35" 无定稿行
]

_MEDIA_ROWS = [
    {"binding_id": 2, "asset_id": 2, "anchor_type": "sense", "anchor_id": 101,
     "purpose": "illustration", "caption": "fx13 义项图", "sort_order": 0,
     "binding_status": PUBLISHED, "reviewed_by": None, "reviewed_at": None,
     "kind": "image", "file_path": "fx13/sense101.png", "mime": "image/png",
     "sha256": "b" * 64, "source": "fx13", "license": "CC0", "size_bytes": 12,
     "asset_status": PUBLISHED, "created_at": "2026-01-08 08:00:00"},
    {"binding_id": 3, "asset_id": 3, "anchor_type": "sense", "anchor_id": 101,
     "purpose": "pronunciation", "caption": "", "sort_order": 1,
     "binding_status": PUBLISHED, "reviewed_by": None, "reviewed_at": None,
     "kind": "audio", "file_path": "fx13/sense101.mp3", "mime": "audio/mpeg",
     "sha256": "c" * 64, "source": "fx13", "license": "CC0", "size_bytes": 13,
     "asset_status": PUBLISHED, "created_at": "2026-01-08 08:05:00"},
    {"binding_id": 4, "asset_id": 4, "anchor_type": "sense", "anchor_id": 102,
     "purpose": "illustration", "caption": "候选绑定不进装配", "sort_order": 0,
     "binding_status": CANDIDATE, "reviewed_by": None, "reviewed_at": None,
     "kind": "image", "file_path": "fx13/sense102.png", "mime": "image/png",
     "sha256": "d" * 64, "source": "fx13", "license": "CC0", "size_bytes": 14,
     "asset_status": REVIEWED, "created_at": "2026-01-08 08:10:00"},
    {"binding_id": 5, "asset_id": 5, "anchor_type": "sense", "anchor_id": 103,
     "purpose": "illustration", "caption": "", "sort_order": 0,
     "binding_status": PUBLISHED, "reviewed_by": None, "reviewed_at": None,
     "kind": "video", "file_path": "fx13/sense103.mp4", "mime": "video/mp4",
     "sha256": "e" * 64, "source": "fx13", "license": "CC0", "size_bytes": 15,
     "asset_status": PUBLISHED, "created_at": "2026-01-08 08:15:00"},
    {"binding_id": 1, "asset_id": 1, "anchor_type": "word", "anchor_id": 12,
     "purpose": "illustration", "caption": "fx13 词目图", "sort_order": 0,
     "binding_status": PUBLISHED, "reviewed_by": None, "reviewed_at": None,
     "kind": "image", "file_path": "fx13/word12.png", "mime": "image/png",
     "sha256": "a" * 64, "source": "fx13", "license": "CC0", "size_bytes": 10,
     "asset_status": PUBLISHED, "created_at": "2026-01-07 08:00:00"},
]

_WORD_ID = 12
_SENSE_ANCHORS = (101, 102, 103)


def _filter_examples(sql, params):
    """sense_examples 两条 SQL（逐义位 = / 批量 IN）→ 发布态行（sort,id 序）。"""
    if "sense_ref IN" in sql:
        status, refs = params[0], [str(p) for p in params[1:]]
        matched = [r for r in _EXAMPLE_ROWS
                   if r["status"] == status and r["sense_ref"] in refs]
    else:
        ref, status = str(params[0]), params[1]
        matched = [r for r in _EXAMPLE_ROWS
                   if r["sense_ref"] == ref and r["status"] == status]
    return sorted(matched, key=lambda r: (r["sort_order"], r["id"]))


def _filter_translations(sql, params):
    if "sense_ref IN" in sql:
        refs = [str(p) for p in params]
        matched = [r for r in _TRANSLATION_ROWS if r["sense_ref"] in refs]
    else:
        ref = str(params[0])
        matched = [r for r in _TRANSLATION_ROWS if r["sense_ref"] == ref]
    return sorted(matched, key=lambda r: r["id"])


def _filter_media(sql, params):
    """media_bindings 两条 SQL（逐锚 WHERE= / 批量 OR+IN）→ 绑定行（sort,id 序）。"""
    rows = sorted(_MEDIA_ROWS, key=lambda r: (r["sort_order"], r["binding_id"]))
    if " OR " not in sql:
        # 逐锚 SQL：params = (anchor_type, anchor_id)
        anchor_type, anchor_id = str(params[0]), int(params[1])
        return [r for r in rows
                if r["anchor_type"] == anchor_type
                and int(r["anchor_id"]) == anchor_id]
    # 批量预取 SQL：params 平铺为 (word, word_id, sense, sid1, sid2, ...)，
    # 锚类型标记（word/sense）之后连排本类型锚 id
    allowed = set()
    i = 0
    while i < len(params):
        anchor_type = str(params[i])
        j = i + 1
        while j < len(params) and not (
                isinstance(params[j], str) and params[j] in ("word", "sense")):
            allowed.add((anchor_type, int(params[j])))
            j += 1
        i = j
    return [r for r in rows
            if (r["anchor_type"], int(r["anchor_id"])) in allowed]


# ============================================
# R5-4 装配批量预取：等价 + 查询计数（假游标，不连库）
# ============================================

def _patch_assembly_singletons(monkeypatch):
    """装配单查询桶打桩（义项行/范畴清单/映射/母图式/参见/定制属性/模板）。"""
    monkeypatch.setattr(
        entry_assembly, "_fetch_definition_row",
        lambda v: {"id": _WORD_ID, "verb": str(v), "phonetic": "/fx13/",
                   "chinese_ndef": "fx13 测试词目", "en_ndef": "to run fx13",
                   "definition_source": "dictionary.db", "source_rank": 1,
                   "cluster_id": None})
    monkeypatch.setattr(
        entry_assembly, "_fetch_oald_senses",
        lambda v: [{"id": sid, "sense_index": str(i + 1),
                    "definition": f"to move fx13 No.{i + 1}",
                    "grammar": "intransitive", "examples": [],
                    "sense_group": "move", "is_idiom": 0}
                   for i, sid in enumerate(_SENSE_ANCHORS)])
    monkeypatch.setattr(entry_assembly, "_fetch_category_codes",
                        lambda: ["RUN"])
    monkeypatch.setattr(
        entry_assembly, "_fetch_cs_sense_map",
        lambda code, lang, lemma:
        {str(i + 1): {"id": int(ref), "sense_label": f"fx13 义 {i + 1}",
                      "status": "保留", "merged_into": None}
         for i, ref in enumerate(_REFS)})
    monkeypatch.setattr(entry_assembly, "_derive_engine_schema",
                        lambda code, lang: [])
    monkeypatch.setattr(entry_assembly, "_fetch_synonyms", lambda v: [])
    monkeypatch.setattr(entry_assembly, "get_values_for_anchor",
                        lambda t, i: [])
    monkeypatch.setattr(entry_assembly, "instantiate_template",
                        lambda code, lang, cid, engine_schema=None: None)
    monkeypatch.setattr(
        entry_assembly, "instantiate_templates",
        lambda code, lang, ids, engine_schema=None:
        {int(i): None for i in ids})


class TestR54AssemblyBatch:
    """R5-4：批量预取分组 ≡ 逐义项数据层取数（逐字段）＋查询数下降。"""

    def test_batch_groups_equal_per_item_fetches(self, monkeypatch):
        def _lex_handler(sql, params):
            if "FROM sense_translations" in sql:
                return _filter_translations(sql, params)
            return _filter_examples(sql, params)

        # 逐义项基线（修复前取数路径：数据层逐 ref / 逐锚查询）
        lex_executed = install_fake_cursor(monkeypatch, lexical_db, _lex_handler)
        media_executed = install_fake_cursor(monkeypatch, media_db, _filter_media)

        old_examples = {ref: lexical_db.list_examples(ref, status=PUBLISHED)
                        for ref in _REFS}
        old_translations = {ref: lexical_db.get_translation(ref) for ref in _REFS}
        old_media = {}
        for anchor_type, aid in [("word", _WORD_ID)] + [
                ("sense", sid) for sid in _SENSE_ANCHORS]:
            old_media[(anchor_type, aid)] = media_db.list_assets_for_anchor(
                anchor_type, aid)

        # 修复后：一次 IN 批量分组（entry_assembly 私有批量 SQL）
        def _batch_handler(sql, params):
            if "FROM sense_examples" in sql:
                return _filter_examples(sql, params)
            if "FROM sense_translations" in sql:
                return _filter_translations(sql, params)
            if "FROM media_bindings" in sql:
                return _filter_media(sql, params)
            return []

        ea_executed = install_fake_cursor(monkeypatch, entry_assembly,
                                          _batch_handler)

        new_examples = entry_assembly._batch_fetch_published_examples(list(_REFS))
        new_translations = entry_assembly._batch_fetch_translations(list(_REFS))
        new_media = entry_assembly._batch_fetch_media(
            _WORD_ID, list(_SENSE_ANCHORS))

        for ref in _REFS:
            assert new_examples[ref] == old_examples[ref], f"例证分组不一致 ref={ref}"
            assert new_translations[ref] == old_translations[ref], \
                f"对译分组不一致 ref={ref}"
        for key, rows in old_media.items():
            assert new_media[key] == rows, f"媒体分组不一致 anchor={key}"
        # 同口径抽查：发布态过滤在 SQL 层（两条路径一致）；
        # 绑定态过滤在段构造层（行为不变，批量分组不丢候选绑定行）
        assert new_examples["35"] == []
        assert [r["binding_status"] for r in new_media[("sense", 102)]] == [CANDIDATE]

        # 查询计数：修复前 3+3+4 → 修复后 1+1+1
        assert count_sql(lex_executed, "FROM sense_examples") == 3
        assert count_sql(lex_executed, "FROM sense_translations") == 3
        assert count_sql(media_executed, "FROM media_bindings") == 4
        assert count_sql(ea_executed, "FROM sense_examples") == 1
        assert count_sql(ea_executed, "FROM sense_translations") == 1
        assert count_sql(ea_executed, "FROM media_bindings") == 1

    def test_assembly_sections_batch_equals_fallback(self, monkeypatch):
        """七段输出逐字段相等：预取路径 ≡ 强制回退（修复前等价路径）。"""
        _patch_assembly_singletons(monkeypatch)

        def _batch_handler(sql, params):
            if "FROM sense_examples" in sql:
                return _filter_examples(sql, params)
            if "FROM sense_translations" in sql:
                return _filter_translations(sql, params)
            if "FROM media_bindings" in sql:
                return _filter_media(sql, params)
            return []

        # 回退路径：数据层逐条查询（假游标供同一批打桩行）
        install_fake_cursor(monkeypatch, lexical_db,
                            lambda sql, params: (
                                _filter_translations(sql, params)
                                if "FROM sense_translations" in sql
                                else _filter_examples(sql, params)))
        install_fake_cursor(monkeypatch, media_db, _filter_media)

        # 运行 A（修复前等价路径）：四个批量桶强制失败 → 逐条回退
        mp_fallback = pytest.MonkeyPatch()
        for name in ("_batch_fetch_published_examples", "_batch_fetch_translations",
                     "_batch_fetch_media", "_batch_fetch_templates"):
            mp_fallback.setattr(entry_assembly, name, lambda *a, **k: None)
        try:
            sections_fallback = entry_assembly._assembly_sections("fxrunverb")
        finally:
            mp_fallback.undo()

        # 运行 B（修复后路径）：预取缓存命中
        ea_executed = install_fake_cursor(monkeypatch, entry_assembly,
                                          _batch_handler)
        sections_batch = entry_assembly._assembly_sections("fxrunverb")

        assert sections_batch == sections_fallback, (
            "预取路径与逐条回退路径的七段输出必须逐字段相等")
        # 段级口径抽查：例证/对译/媒体取到打桩数据（两条路径一致取到）
        assert "He ran home." in sections_batch[2].body
        assert "【完全对应】等价词：跑" in sections_batch[3].body
        assert sections_batch[4].images, "发布态图片应进 images 位"

        # 查询计数证据：修复前 3/3/4 → 修复后 1/1/1
        assert count_sql(ea_executed, "FROM sense_examples") == 1
        assert count_sql(ea_executed, "FROM sense_translations") == 1
        assert count_sql(ea_executed, "FROM media_bindings") == 1

        # 预取缓存请求级复位：装配结束不泄漏
        assert entry_assembly._ASSEMBLY_PREFETCH is None

    def test_templates_batch_prefetch_cuts_queries(self, monkeypatch):
        """模板释义桶：3 建模义项 9→3 查询（instantiate_templates 一次取数）。"""
        _patch_assembly_singletons(monkeypatch)
        # 反打桩：模板走 template_engine 真批量（假游标供行）
        mp = pytest.MonkeyPatch()
        mp.setattr(entry_assembly, "instantiate_templates",
                   template_engine.instantiate_templates)
        mp.setattr(entry_assembly, "instantiate_template",
                   template_engine.instantiate_template)

        def _tpl_handler(sql, params):
            if "FROM cs_sense_features" in sql:
                if "IN (" in sql:
                    ids = [int(p) for p in params]
                    return [r for r in _TPL_FEATURE_ROWS
                            if r["sense_id"] in ids]
                return [r for r in _TPL_FEATURE_ROWS
                        if r["sense_id"] == int(params[0])]
            if "FROM cs_cluster_members" in sql:
                if "IN (" in sql:
                    ids = [int(p) for p in params[:-1]]
                    return [r for r in _TPL_CLUSTER_ROWS
                            if r["sense_id"] in ids]
                return [r for r in _TPL_CLUSTER_ROWS
                        if r["sense_id"] == int(params[0])]
            if "FROM cs_senses" in sql:
                if "IN (" in sql:
                    ids = [int(p) for p in params[2:]]
                    return [r for r in _TPL_SENSE_ROWS
                            if r["sense_id"] in ids]
                return [r for r in _TPL_SENSE_ROWS
                        if r["sense_id"] == int(params[2])]
            return []

        ea_executed = install_fake_cursor(monkeypatch, entry_assembly,
                                          _tpl_handler)
        install_fake_cursor(monkeypatch, template_engine, _tpl_handler,
                            executed=ea_executed)
        install_fake_cursor(monkeypatch, lexical_db, lambda sql, params: [])
        install_fake_cursor(monkeypatch, media_db, lambda sql, params: [])
        mp.setattr(template_engine, "derive_cluster_schemas",
                   lambda category, language: [])  # 母图式提炼打桩（保持不连库）
        try:
            sections = entry_assembly._assembly_sections("fxrunverb")
        finally:
            mp.undo()
        # 批量取数：义位行 / 簇归属 / 特征向量各 1 条（旧逐义项 = 各 3 条）
        assert count_sql(ea_executed, "FROM cs_senses") == 1
        assert count_sql(ea_executed, "FROM cs_cluster_members") == 1
        assert count_sql(ea_executed, "FROM cs_sense_features") == 1
        # 打桩义位行缺 OALD 释义所需的列不进段体 —— 仅断言不崩且七段齐
        assert len(sections) == 6  # 参见打桩为空 → ⑦ 省略（契约不变）


_TPL_SENSE_ROWS = [
    {"sense_id": 33, "sense_no": "1", "sense_label": "fx13 长跑义",
     "definition": "to move fast on foot fx13", "example": None,
     "subject_type": "人", "register": "通用", "tag": "奔跑", "status": "保留",
     "remark": None, "lemma": "fxrun", "language": "en", "source_dict": "OALD10",
     "category_code": "RUN", "category_name": "跑"},
    {"sense_id": 34, "sense_no": "2", "sense_label": "fx13 使役义",
     "definition": "to cause to run fx13", "example": None,
     "subject_type": "人", "register": "通用", "tag": "驱动", "status": "保留",
     "remark": None, "lemma": "fxrun", "language": "en", "source_dict": "OALD10",
     "category_code": "RUN", "category_name": "跑"},
    {"sense_id": 35, "sense_no": "3", "sense_label": "fx13 运转义",
     "definition": "to operate fx13", "example": None,
     "subject_type": "机器", "register": "通用", "tag": "运转", "status": "保留",
     "remark": None, "lemma": "fxrun", "language": "en", "source_dict": "OALD10",
     "category_code": "RUN", "category_name": "跑"},
]

_TPL_CLUSTER_ROWS = [
    {"sense_id": 33, "cluster_id": 9, "cluster_no": 1, "cluster_name": "fx13 竞速簇"},
    {"sense_id": 34, "cluster_id": 9, "cluster_no": 1, "cluster_name": "fx13 竞速簇"},
    {"sense_id": 35, "cluster_id": 9, "cluster_no": 1, "cluster_name": "fx13 竞速簇"},
]

_TPL_FEATURE_ROWS = [
    {"sense_id": 33, "feature_code": "P1", "value": 1},
    {"sense_id": 33, "feature_code": "P2", "value": 1},
    {"sense_id": 33, "feature_code": "A1", "value": 1},
    {"sense_id": 34, "feature_code": "P1", "value": 0},
    {"sense_id": 34, "feature_code": "P2", "value": 1},
    {"sense_id": 34, "feature_code": "A1", "value": 1},
    {"sense_id": 35, "feature_code": "P1", "value": 1},
    {"sense_id": 35, "feature_code": "P2", "value": 0},
    {"sense_id": 35, "feature_code": "A2", "value": 1},
]


# ============================================
# R5-5 脊柱标注留痕批量：等价 + 查询计数（假游标）
# ============================================

_SUBMISSION_ROWS = [
    {"id": 1, "category": "motion", "sense_id": 164, "task_type": "admission",
     "coder_id": 7,
     "payload": json.dumps({"admission": "Y", "schema": "fx13", "alignment": "对齐",
                            "cn_syntax": "SVO", "strategy": "直译",
                            "needs_review": False}),
     "ai_assisted": 1, "status": "submitted",
     "submitted_at": "2026-01-09 09:00:00", "username": "fx13_a",
     "display_name": "标注员A"},
    {"id": 2, "category": "motion", "sense_id": 164, "task_type": "feature_coding",
     "coder_id": 8, "payload": json.dumps({"features": {"P1": 1, "P2": 0}}),
     "ai_assisted": 1, "status": "adjudicated",
     "submitted_at": "2026-01-09 09:05:00", "username": "fx13_b",
     "display_name": "标注员B"},
    {"id": 3, "category": "motion", "sense_id": 164, "task_type": "admission",
     "coder_id": 8,
     "payload": json.dumps({"admission": "N", "schema": "fx13", "alignment": "错位",
                            "cn_syntax": "SOV", "strategy": "意译",
                            "needs_review": True}),
     "ai_assisted": 0, "status": "submitted",
     "submitted_at": "2026-01-09 09:10:00", "username": "fx13_b",
     "display_name": "标注员B"},
    {"id": 4, "category": "motion", "sense_id": 164, "task_type": "alignment",
     "coder_id": 7, "payload": json.dumps({"alignment": "完全对齐"}),
     "ai_assisted": 1, "status": "submitted",
     "submitted_at": "2026-01-09 09:15:00", "username": "fx13_a",
     "display_name": "标注员A"},
]


def _submissions_handler(sql, params):
    if "task_type IN" in sql:
        sense_id = int(params[0])
        matched = [r for r in _SUBMISSION_ROWS if r["sense_id"] == sense_id]
        return sorted(matched, key=lambda r: (r["coder_id"], r["id"]))
    sense_id, task_type = int(params[0]), str(params[1])
    matched = [r for r in _SUBMISSION_ROWS
               if r["sense_id"] == sense_id and r["task_type"] == task_type]
    return sorted(matched, key=lambda r: (r["coder_id"], r["id"]))


class TestR55SubmissionsBatch:
    """R5-5：三类任务 3→1 查询；批量输出 ≡ 逐类拼接（逐字段、含顺序）。"""

    def test_batch_equals_per_task_type_loop(self, monkeypatch):
        # 旧路径基线：逐任务类型调 annotation_flow.get_submissions_for_sense
        af_executed = install_fake_cursor(monkeypatch, annotation_flow,
                                          _submissions_handler)
        old_rows = []
        for task_type in annotation_flow.TASK_TYPES:
            old_rows.extend(
                annotation_flow.get_submissions_for_sense(164, task_type))

        # 修复后：task_type IN 一次取回（sense_spine 私有批量 SQL）
        ss_executed = install_fake_cursor(monkeypatch, sense_spine,
                                          _submissions_handler)
        new_rows = sense_spine._fetch_submissions_for_spine(164)

        assert new_rows == old_rows, "批量取回应与逐任务类型拼接逐字段一致"
        assert [r["task_type"] for r in new_rows] == [
            "admission", "admission", "feature_coding", "alignment"], \
            "组间按 TASK_TYPES 序、组内 coder_id,id 序"
        assert count_sql(af_executed, "FROM annotation_submissions") == 3
        assert count_sql(ss_executed, "FROM annotation_submissions") == 1

    def test_batch_failure_falls_back_to_loop(self, monkeypatch):
        """批量失败 → 回退逐任务类型查询（旧行为兜底，输出一致）。"""
        install_fake_cursor(monkeypatch, sense_spine, _submissions_handler,
                            boom=True)
        install_fake_cursor(monkeypatch, annotation_flow, _submissions_handler)
        fallback_rows = sense_spine._fetch_submissions_for_spine(164)
        old_rows = []
        for task_type in annotation_flow.TASK_TYPES:
            old_rows.extend(
                annotation_flow.get_submissions_for_sense(164, task_type))
        assert fallback_rows == old_rows


# ============================================
# R5-6 版本意见线批量：等价 + 查询计数（假游标）
# ============================================

_COMMENT_ROWS = [
    {"id": 1, "version_id": 11, "reviewer_id": 8, "body": "fx13 意见一",
     "resolved": 0, "created_at": "2026-01-10 09:00:00"},
    {"id": 2, "version_id": 11, "reviewer_id": 8, "body": "fx13 意见二",
     "resolved": 1, "created_at": "2026-01-10 09:05:00"},
    {"id": 3, "version_id": 12, "reviewer_id": 8, "body": "第二版意见",
     "resolved": 0, "created_at": "2026-01-10 09:10:00"},
    # 版本 13 无意见
]


def _comments_handler(sql, params):
    only_open = "resolved = 0" in sql
    if "version_id IN" in sql:
        ids = [int(p) for p in params]
        matched = [r for r in _COMMENT_ROWS
                   if r["version_id"] in ids
                   and (not only_open or not r["resolved"])]
        return sorted(matched, key=lambda r: (r["version_id"], r["id"]))
    vid = int(params[0])
    matched = [r for r in _COMMENT_ROWS
               if r["version_id"] == vid
               and (not only_open or not r["resolved"])]
    return sorted(matched, key=lambda r: r["id"])


class TestR56CommentsBatch:
    """R5-6：一次 IN 按版本分组 ≡ 逐版本 list_comments（逐字段）＋ 3→1。"""

    def test_batch_equals_per_version(self, monkeypatch):
        wd_executed = install_fake_cursor(monkeypatch, writing_db,
                                          _comments_handler)
        old_groups = {vid: writing_db.list_comments(vid)
                      for vid in (11, 12, 13)}
        assert count_sql(wd_executed, "FROM review_comments") == 3

        new_groups = writing_db.list_comments_for_versions([11, 12, 13])
        assert count_sql(wd_executed, "FROM review_comments") == 4  # 3 旧 + 1 新
        assert new_groups == old_groups, "批量分组应与逐版本查询逐字段一致"
        assert new_groups[13] == [], "无意见版本应有空列表键（展示口径不变）"

        # only_open 口径一致
        old_open = writing_db.list_comments(11, only_open=True)
        new_open = writing_db.list_comments_for_versions([11, 12, 13],
                                                         only_open=True)
        assert new_open[11] == old_open
        assert all(not r["resolved"] for r in new_open[11])

    def test_fail_closed(self, monkeypatch):
        """空清单 / 全非法 / 库不可用 → None（调用方回退逐版本）。"""
        assert writing_db.list_comments_for_versions([]) is None
        assert writing_db.list_comments_for_versions([0, -1, "x", None]) is None
        install_fake_cursor(monkeypatch, writing_db, boom=True)
        assert writing_db.list_comments_for_versions([11, 12]) is None
        # 去重保序：重复 id 只查一次
        executed = install_fake_cursor(monkeypatch, writing_db,
                                       _comments_handler)
        groups = writing_db.list_comments_for_versions([11, 11, "11"])
        assert list(groups.keys()) == [11]
        assert count_sql(executed, "FROM review_comments") == 1


# ============================================
# R5-7 模板批量实例化：等价 + 查询计数（假游标）
# ============================================

_CLUSTER_SCHEMA = {
    "cluster_id": 9, "cluster_no": 1, "cluster_name": "fx13 竞速簇",
    "schema": {"code": "MOTION_PURSUIT", "name": "互动位移图式",
               "definition": "fx13 图式定义"},
    "schema_source": "feature_map",
    "schema_core": {"P1": 0.5},
    "core_features": [],
    "variable_slots": [{"code": "A1", "label": "构式论元",
                        "value_type": "binary", "distribution": []}],
    "members": [
        {"sense_id": 33, "lemma": "fxrun", "sense_no": "1",
         "sense_label": "fx13 长跑义"},
        {"sense_id": 34, "lemma": "fxrun", "sense_no": "2",
         "sense_label": "fx13 使役义"},
        {"sense_id": 35, "lemma": "fxrun", "sense_no": "3",
         "sense_label": "fx13 运转义"},
    ],
}


def _tpl_handler(sql, params):
    if "FROM cs_sense_features" in sql:
        if "IN (" in sql:
            ids = [int(p) for p in params]
            return [r for r in _TPL_FEATURE_ROWS if r["sense_id"] in ids]
        return [r for r in _TPL_FEATURE_ROWS if r["sense_id"] == int(params[0])]
    if "FROM cs_cluster_members" in sql:
        if "IN (" in sql:
            ids = [int(p) for p in params[:-1]]
            return [r for r in _TPL_CLUSTER_ROWS if r["sense_id"] in ids]
        return [r for r in _TPL_CLUSTER_ROWS if r["sense_id"] == int(params[0])]
    if "FROM cs_senses" in sql:
        if "IN (" in sql:
            ids = [int(p) for p in params[2:]]
            return [r for r in _TPL_SENSE_ROWS if r["sense_id"] in ids]
        return [r for r in _TPL_SENSE_ROWS if r["sense_id"] == int(params[2])]
    return []


class TestR57TemplatesBatch:
    """R5-7：批量实例化 ≡ 逐义位 instantiate_template（逐字段）＋ 9→3。"""

    def test_batch_equals_per_sense(self, monkeypatch):
        ids = [33, 34, 35]
        te_executed = install_fake_cursor(monkeypatch, template_engine,
                                          _tpl_handler)

        old_by_id = {}
        for sid in ids:
            tpl = template_engine.instantiate_template(
                "RUN", "en", sid, engine_schema=[_CLUSTER_SCHEMA])
            old_by_id[sid] = tpl
        n_after_old = len(te_executed)

        new_by_id = template_engine.instantiate_templates(
            "RUN", "en", ids, engine_schema=[_CLUSTER_SCHEMA])
        n_after_new = len(te_executed)

        assert new_by_id == old_by_id, "批量实例化应与逐义位口径逐字段一致"
        assert all(t is not None for t in new_by_id.values())
        # 四维结构抽查（两条路径同构）
        tpl = new_by_id[33]
        assert tpl["图式维度"]["name"] == "互动位移图式"
        assert tpl["句法维度"]["transitivity"] == "不及物"
        assert tpl["template_text"].startswith("【图式：互动位移图式】")

        # 查询计数证据：旧 3 义位 × 3 条查询（义位行/簇归属/特征向量）= 9
        # → 新批量一次取数 = 3
        assert n_after_old == 9, "修复前逐义位取数应为 3×3=9 条查询"
        assert n_after_new - n_after_old == 3, "修复后一次批量取数应为 3 条查询"

    def test_collect_cluster_templates_equals_old_loop(self, monkeypatch):
        """collect 输出 ≡ 修复前「逐成员 instantiate_template」循环（逐字段）。"""
        mp = pytest.MonkeyPatch()
        mp.setattr(template_engine, "derive_cluster_schemas",
                   lambda category, language: [dict(_CLUSTER_SCHEMA)])
        try:
            payload = template_engine.collect_cluster_templates("RUN", "en", 1)
        finally:
            mp.undo()
        assert payload["category"] == "RUN"
        assert payload["language"] == "en"
        assert payload["cluster"]["cluster_no"] == 1

        old_templates = []
        for m in _CLUSTER_SCHEMA["members"]:
            tpl = template_engine.instantiate_template(
                "RUN", "en", int(m["sense_id"]),
                engine_schema=[dict(_CLUSTER_SCHEMA)])
            if tpl:
                old_templates.append(tpl)
        assert payload["templates"] == old_templates

    def test_fail_closed_and_fallback(self, monkeypatch):
        """批量取数失败 → 回退逐义位；义位缺失 → None 占位；空清单 → {}。"""
        assert template_engine.instantiate_templates("RUN", "en", []) == {}
        assert template_engine._fetch_senses("RUN", "en", []) == {}

        # 义位不存在（无行）→ None 占位（与逐义位 instantiate_template 同口径）
        install_fake_cursor(monkeypatch, template_engine,
                            lambda sql, params: [])
        missing = template_engine.instantiate_templates("RUN", "en", [999])
        assert missing == {999: None}

        # 整批失败（boom）→ 回退逐义位 instantiate_template（也失败 → None）
        install_fake_cursor(monkeypatch, template_engine, boom=True)
        failed = template_engine.instantiate_templates("RUN", "en", [33, 34])
        assert failed == {33: None, 34: None}


# ============================================
# 空库 / 无库环境不崩（fail-closed 汇总）
# ============================================

class TestFx13NoDbRobustness:
    def test_assembly_batch_prefetch_never_raises(self, monkeypatch):
        """get_db_cursor 全 boom：预取编排折叠为回退桶，装配输出仍齐。"""
        install_fake_cursor(monkeypatch, entry_assembly, boom=True)
        buckets = entry_assembly._build_assembly_prefetch(
            {"id": 12}, [], {}, "RUN", "en", [])
        assert set(buckets) == {"examples", "translations", "media", "templates"}
        assert buckets["examples"] == {}  # 空 refs 直接空组（不触库）
        # 预取失败 → _fetch_* 回退原路径（数据层 boom 亦兜底为空）
        assert entry_assembly._batch_fetch_published_examples(["33"]) is None
        assert entry_assembly._batch_fetch_translations(["33"]) is None
        assert entry_assembly._batch_fetch_media(12, [101]) is None

    def test_assembly_adapters_fallback_without_prefetch(self, monkeypatch):
        """无预取（直调）时 _fetch_* 走原数据层路径，行为与修复前一致。"""
        assert entry_assembly._ASSEMBLY_PREFETCH is None
        install_fake_cursor(monkeypatch, lexical_db,
                            lambda sql, params: [])
        install_fake_cursor(monkeypatch, media_db, lambda sql, params: [])
        monkeypatch.setattr(entry_assembly, "instantiate_template",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("boom")))
        assert entry_assembly._fetch_published_examples("33") == []
        assert entry_assembly._fetch_translation("33") is None
        assert entry_assembly._fetch_media_for_anchor("sense", 101) == []
        assert entry_assembly._fetch_template("RUN", "en", 33, None) is None

    def test_cache_prefetch_hit_short_circuits_data_layer(self, monkeypatch):
        """预取命中时 _fetch_* 不再触数据层（打桩数据层 boom 也不影响输出）。"""
        entry_assembly._ASSEMBLY_PREFETCH = {
            "examples": {"33": [{"id": 1, "content": "fx13 缓存例"}]},
            "translations": {"33": None},
            "media": {("sense", 101): []},
            "templates": {33: None},
        }
        try:
            boom = install_fake_cursor(monkeypatch, lexical_db, boom=True)
            install_fake_cursor(monkeypatch, media_db, boom=True)
            install_fake_cursor(monkeypatch, entry_assembly, boom=True)
            monkeypatch.setattr(entry_assembly, "instantiate_template",
                                lambda *a, **k: (_ for _ in ()).throw(
                                    RuntimeError("boom")))
            rows = entry_assembly._fetch_published_examples("33")
            assert [r["content"] for r in rows] == ["fx13 缓存例"]
            assert entry_assembly._fetch_translation("33") is None
            assert entry_assembly._fetch_media_for_anchor("sense", 101) == []
            assert entry_assembly._fetch_template("RUN", "en", 33, None) is None
            assert not boom  # 缓存命中零查询
        finally:
            entry_assembly._ASSEMBLY_PREFETCH = None


# ============================================
# 真库端到端等价（复用已授权测试库；无库 / 无权限 skip）
# ============================================

def _counting_patch(monkeypatch, module, origins, counter):
    """module.get_db_cursor 包计数壳（真实连接不变；execute 计数＋留 SQL）。"""
    orig = origins[module]

    @contextlib.contextmanager
    def wrapped(*args, **kwargs):
        with orig(*args, **kwargs) as cursor:
            real_execute = cursor.execute

            def execute(sql, params=None):
                counter["n"] += 1
                counter["sqls"].append(sql)
                return real_execute(sql, params)

            cursor.execute = execute
            yield cursor

    monkeypatch.setattr(module, "get_db_cursor", wrapped)
    return counter


@pytest.mark.skipif(not _db_available(), reason="MySQL 不可用，跳过 FX13 真库等价用例")
class TestFx13RealDb:
    """R5-4~7 真库端到端：批量 ≡ 逐条（逐字段）＋ 查询数实测下降。"""

    @pytest.fixture(scope="class", autouse=True)
    def fx13_db(self):
        """整库重建（DROP+CREATE）→ 同构 schema → 多义项夹具数据 → yield → DROP。"""
        conn_params = dict(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, autocommit=True,
            connect_timeout=3,
        )
        conn = pymysql.connect(**conn_params)
        try:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
                    cur.execute(f"CREATE DATABASE `{TEST_DB}` "
                                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            except pymysql.err.OperationalError as e:
                pytest.skip(f"当前 MySQL 账号无建库权限，跳过 FX13 真库用例: {e}")
        finally:
            conn.close()

        old_database = db.MYSQL_DATABASE
        state: dict = {}
        try:
            db.MYSQL_DATABASE = TEST_DB
            category_study.register_tables()  # cs_* 8 表注册进建表清单
            assert db.init_database(), "init_database 失败（DDL 权限/连接）"
            from src.cluster_analysis import ensure_sense_split_columns
            ensure_sense_split_columns()  # cs_senses 补 status/merged_into（批次 6 迁移）
            ensure_user_tables()
            writing_db.ensure_writing_tables()
            lexical_db.ensure_lexical_tables()
            media_db.ensure_media_tables()
            from src.dict_admin_db import ensure_dict_admin_tables
            ensure_dict_admin_tables()
            annotation_flow.ensure_flow_tables()

            self._seed(state)
            yield state
        finally:
            pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
            getattr(db, "_connection_pools", {}).pop(pool_key, None)
            db.MYSQL_DATABASE = old_database
            conn = pymysql.connect(**conn_params)
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
            finally:
                conn.close()

    # ------------------------------------------------------------ 夹具数据
    def _seed(self, state):
        author_id = create_user("fx13_author", "fx13_Passw0rd!", "FX13 撰写人")
        chief_id = create_user("fx13_chief", "fx13_Passw0rd!", "FX13 审校人")
        assert author_id and chief_id
        state["author_id"], state["chief_id"] = author_id, chief_id

        _q("INSERT INTO categories (code, name_cn, name_en, status) "
           "VALUES ('RUN', '跑', 'Run', '试点')")
        _q("INSERT INTO cs_lexemes (category_id, language, lemma, source_dict) "
           "VALUES (1, 'en', 'fxrunverb', 'OALD10')")
        labels = ("fx13 长跑义", "fx13 使役义", "fx13 运转义")
        for i, label in enumerate(labels, start=1):
            _q("INSERT INTO cs_senses (lexeme_id, sense_no, sense_label, "
               "definition, subject_type, register, tag, status) "
               "VALUES (1, %s, %s, %s, %s, %s, %s, '保留')",
               (str(i), label, f"fx13 definition No.{i}", "人", "通用", "奔跑"))
        cs_ids = [int(r["id"]) for r in
                  _q("SELECT id FROM cs_senses ORDER BY id")]
        assert len(cs_ids) == 3
        state["cs_ids"] = cs_ids

        feature_rows = (
            (cs_ids[0], "P1", 1, 1), (cs_ids[0], "P2", 1, 1), (cs_ids[0], "A1", 1, 0),
            (cs_ids[1], "P1", 0, 1), (cs_ids[1], "P2", 1, 1), (cs_ids[1], "A1", 1, 0),
            (cs_ids[2], "P1", 1, 1), (cs_ids[2], "P2", 0, 1), (cs_ids[2], "A2", 1, 0),
        )
        for sid, code, value, in_cl in feature_rows:
            _q("INSERT INTO cs_sense_features (sense_id, feature_code, value, "
               "in_clustering) VALUES (%s, %s, %s, %s)", (sid, code, value, in_cl))

        _q("INSERT INTO cs_cluster_runs (category_id, language, algorithm, "
           "params, cophenetic, version) VALUES (1, 'en', 'fx13-fake', '{}', "
           "0.9, 'fx13run')")
        run_id = int(_q("SELECT MAX(id) AS id FROM cs_cluster_runs")[0]["id"])
        _q("INSERT INTO cs_clusters (run_id, cluster_no, name, size, profile) "
           "VALUES (%s, 1, 'fx13 竞速簇', 3, '{}')", (run_id,))
        cluster_id = int(_q("SELECT MAX(id) AS id FROM cs_clusters")[0]["id"])
        for sid in cs_ids:
            _q("INSERT INTO cs_cluster_members (cluster_id, sense_id) "
               "VALUES (%s, %s)", (cluster_id, sid))

        _q("INSERT INTO definitions (verb, chinese_ndef, semantic_table, "
           "en_ndef, phonetic, definition_source, source_rank, sense_count) "
           "VALUES ('fxrunverb', 'fx13 测试词目', '{}', 'to run fx13', "
           "'/fx13/', 'dictionary.db', 1, 3)")
        def_id = int(_q("SELECT id FROM definitions WHERE verb='fxrunverb'")[0]["id"])
        state["def_id"] = def_id
        oald_ids = []
        for i in (1, 2, 3):
            _q("INSERT INTO oald_senses (definition_id, sense_index, definition, "
               "grammar, sense_group, examples, is_idiom, headword) "
               "VALUES (%s, %s, %s, %s, %s, %s, 0, 'fxrunverb')",
               (def_id, i, f"to move fx13 No.{i}", "intransitive", "move",
                json.dumps([f"fx13 例句 {i}"])))
        oald_ids = [int(r["id"]) for r in
                    _q("SELECT id FROM oald_senses ORDER BY sense_index")]
        state["oald_ids"] = oald_ids

        # 例证：cs0 两条（发布），cs1 一条（发布），cs2 一条（停在审定）
        plan = ((cs_ids[0], "He ran home.", 1, True),
                (cs_ids[0], "She runs daily.", 0, True),
                (cs_ids[1], "Run the program.", 5, True),
                (cs_ids[2], "审定态例证不进装配", 0, False))
        for ref, content, order, to_publish in plan:
            eid = lexical_db.add_example(str(ref), content,
                                         source="corpus", caption="fx13",
                                         sort_order=order, created_by=author_id)
            assert eid
            if to_publish:
                assert lexical_db.advance_example_status(eid, CANDIDATE, REVIEWED)
                assert lexical_db.advance_example_status(eid, REVIEWED, PUBLISHED)

        assert lexical_db.set_translation(str(cs_ids[0]), "full",
                                          equivalent="跑", finalized_by=author_id)
        assert lexical_db.set_translation(str(cs_ids[1]), "partial",
                                          equivalent="奔跑", note="fx13 括注",
                                          finalized_by=author_id)
        # cs_ids[2] 无对译定稿行

        # 媒体：词目锚 1 张（发布）＋义项锚 3 张（发布/发布/候选）
        assets = (("image", "fx13/word12.png", "a" * 64, PUBLISHED),
                  ("image", "fx13/sense101.png", "b" * 64, PUBLISHED),
                  ("image", "fx13/sense102.png", "d" * 64, REVIEWED),
                  ("image", "fx13/sense103.png", "e" * 64, PUBLISHED))
        for kind, path, sha, status in assets:
            _q("INSERT INTO media_assets (kind, file_path, mime, sha256, source, "
               "license, size_bytes, status) VALUES (%s, %s, 'image/png', %s, "
               "'fx13', 'CC0', 10, %s)", (kind, path, sha, status))
        bindings = ((1, "word", def_id, PUBLISHED, 0),
                    (2, "sense", oald_ids[0], PUBLISHED, 0),
                    (3, "sense", oald_ids[1], CANDIDATE, 0),
                    (4, "sense", oald_ids[2], PUBLISHED, 1))
        for asset_no, anchor_type, anchor_id, status, sort_order in bindings:
            _q("INSERT INTO media_bindings (asset_id, anchor_type, anchor_id, "
               "purpose, caption, sort_order, status) VALUES "
               "(%s, %s, %s, 'illustration', 'fx13', %s, %s)",
               (asset_no, anchor_type, anchor_id, sort_order, status))

        # 定制属性：词目锚一个 text 字段值（project_id 软引用占 1）
        from src.dict_admin_db import set_value
        _q("INSERT INTO custom_fields (project_id, code, name, applies_to, "
           "value_type, enum_values, required, status) VALUES "
           "(1, 'fx13_reg', '语域fx13', 'word', 'text', NULL, 0, 'active')")
        field_id = int(_q("SELECT id FROM custom_fields "
                          "WHERE code='fx13_reg'")[0]["id"])
        assert set_value(field_id, "word", def_id, "口语", updated_by=author_id)

        # 版本链 + 意见线：3 版本（v3 无意见），v1 两条 / v2 一条
        ref = f"motion:{cs_ids[0]}:{oald_ids[0]}"
        state["ref"] = ref
        v1 = writing_db.create_draft(ref, author_id, "fx13 第一版释义。")
        v2 = writing_db.create_draft(ref, author_id, "fx13 第二版释义。",
                                     based_on_version=1)
        v3 = writing_db.create_draft(ref, author_id, "fx13 第三版释义。",
                                     based_on_version=2)
        assert v1 and v2 and v3
        state["version_ids"] = [v1, v2, v3]
        assert writing_db.add_comment(v1, chief_id, "fx13 请补充语料")
        assert writing_db.add_comment(v1, chief_id, "第二意见：术语统一")
        assert writing_db.add_comment(v2, chief_id, "第二版仍需润色")

        # 标注留痕：三类任务 × 2 编码人（oald_ids[0] 锚）
        payloads = {
            "admission": {"admission": "Y", "schema": "fx13", "alignment": "对齐",
                          "cn_syntax": "SVO", "strategy": "直译",
                          "needs_review": False},
            "feature_coding": {"features": {"P1": 1, "P2": 1}},
            "alignment": {"alignment": "完全对齐"},
        }
        rows = ((oald_ids[0], "admission", author_id, "submitted"),
                (oald_ids[0], "admission", chief_id, "adjudicated"),
                (oald_ids[0], "feature_coding", author_id, "submitted"),
                (oald_ids[0], "feature_coding", chief_id, "submitted"),
                (oald_ids[0], "alignment", chief_id, "submitted"))
        for sense_id, task_type, coder_id, status in rows:
            _q("INSERT INTO annotation_submissions (category, sense_id, "
               "task_type, coder_id, payload, ai_assisted, status) "
               "VALUES ('motion', %s, %s, %s, %s, 1, %s)",
               (sense_id, task_type, coder_id, json.dumps(payloads[task_type]),
                status))

    # ------------------------------------------------------------ R5-4
    def test_r5_4_batch_equals_per_item(self, fx13_db):
        refs = [str(cid) for cid in fx13_db["cs_ids"]]
        # 旧逻辑基线（逐义项数据层查询）
        old_examples = {r: lexical_db.list_examples(r, status=PUBLISHED)
                        for r in refs}
        old_translations = {r: lexical_db.get_translation(r) for r in refs}
        anchors = [("word", fx13_db["def_id"])] + [
            ("sense", oid) for oid in fx13_db["oald_ids"]]
        old_media = {k: media_db.list_assets_for_anchor(*k) for k in anchors}

        # 修复后（一次 IN 批量分组）
        new_examples = entry_assembly._batch_fetch_published_examples(refs)
        new_translations = entry_assembly._batch_fetch_translations(refs)
        new_media = entry_assembly._batch_fetch_media(
            fx13_db["def_id"], fx13_db["oald_ids"])

        for ref in refs:
            assert new_examples[ref] == old_examples[ref], f"例证 ref={ref}"
            assert new_translations[ref] == old_translations[ref], f"对译 ref={ref}"
        for key, rows in old_media.items():
            assert new_media[key] == rows, f"媒体 {key}"
        # 口径抽查：审定态例证 / 候选绑定被同口径过滤
        assert [r["content"] for r in new_examples[str(fx13_db["cs_ids"][2])]] == []
        assert [r for r in new_media[("sense", fx13_db["oald_ids"][1])]
                if r["binding_status"] == PUBLISHED] == []

        # 模板：批量 ≡ 逐义位（逐字段，含图式提炼口径）
        ids = fx13_db["cs_ids"]
        old_tpl = {i: template_engine.instantiate_template("RUN", "en", i)
                   for i in ids}
        new_tpl = template_engine.instantiate_templates("RUN", "en", ids)
        assert new_tpl == old_tpl
        assert all(t is not None for t in new_tpl.values())
        assert new_tpl[ids[0]]["图式维度"]["cluster_no"] == 1

    def test_r5_4_sections_batch_equals_fallback(self, fx13_db, monkeypatch):
        """装配七段输出逐字段相等（预取路径 ≡ 修复前逐条回退路径）＋查询数下降。"""
        origins = {m: m.get_db_cursor for m in
                   (entry_assembly, lexical_db, media_db, template_engine,
                    category_study, db)}

        def run_sections(force_fallback):
            counter = {"n": 0, "sqls": []}
            mp = pytest.MonkeyPatch()
            for m in origins:
                _counting_patch(mp, m, origins, counter)
            if force_fallback:
                for name in ("_batch_fetch_published_examples",
                             "_batch_fetch_translations",
                             "_batch_fetch_media",
                             "_batch_fetch_templates"):
                    mp.setattr(entry_assembly, name, lambda *a, **k: None)
            try:
                sections = entry_assembly._assembly_sections(
                    "fxrunverb", category="motion", language="en")
            finally:
                mp.undo()
            return sections, counter

        sections_fallback, old_counter = run_sections(force_fallback=True)
        sections_batch, new_counter = run_sections(force_fallback=False)

        assert sections_batch == sections_fallback, \
            "预取路径与修复前逐条路径的七段输出必须逐字段相等"
        # 有数段抽查（两条路径一致取到）
        assert "to move fx13 No.1" in sections_batch[1].body
        assert "He ran home." in sections_batch[2].body
        assert sections_batch[4].images, "发布态图片进 images 位"

        def family(counter, needle):
            return sum(1 for s in counter["sqls"] if needle in s)

        # 查询计数证据（实测）：例证 3→1 / 对译 3→1 / 媒体 4→1 / 模板逐义位 3→0
        assert family(old_counter, "FROM sense_examples") == 3
        assert family(new_counter, "FROM sense_examples") == 1
        assert family(old_counter, "FROM sense_translations") == 3
        assert family(new_counter, "FROM sense_translations") == 1
        assert family(old_counter, "FROM media_bindings") == 4
        assert family(new_counter, "FROM media_bindings") == 1
        # 逐义位特征向量查询（模板实例化）被批量 IN 取代（母图式提炼的
        # 全簇 features IN 查询两条路径各 1 次，不计入此口径）
        assert family(old_counter, "WHERE sense_id = %s") == 3
        assert family(new_counter, "WHERE sense_id = %s") == 0
        assert new_counter["n"] < old_counter["n"], "总查询数应下降"

    # ------------------------------------------------------------ R5-5
    def test_r5_5_submissions_batch_equals_loop(self, fx13_db, monkeypatch):
        oid = fx13_db["oald_ids"][0]
        # 旧逻辑基线（逐任务类型 3 查询）
        old_rows = []
        for task_type in annotation_flow.TASK_TYPES:
            old_rows.extend(
                annotation_flow.get_submissions_for_sense(oid, task_type))
        # 修复后（1 条批量查询）
        new_rows = sense_spine._fetch_submissions_for_spine(oid)
        assert new_rows == old_rows
        assert len(new_rows) == 5, "三类任务 × 编码人的提交应全量取回"

        origins = {m: m.get_db_cursor for m in (annotation_flow, sense_spine)}
        counter_old = {"n": 0, "sqls": []}
        mp = pytest.MonkeyPatch()
        for m in origins:
            _counting_patch(mp, m, origins, counter_old)
        try:
            for task_type in annotation_flow.TASK_TYPES:
                annotation_flow.get_submissions_for_sense(oid, task_type)
            n_old = counter_old["n"]
            counter_old["n"] = 0
            sense_spine._fetch_submissions_for_spine(oid)
            n_new = counter_old["n"]
        finally:
            mp.undo()
        assert (n_old, n_new) == (3, 1), "标注留痕查询数应 3→1"

    # ------------------------------------------------------------ R5-6
    def test_r5_6_comments_batch_equals_per_version(self, fx13_db, monkeypatch):
        vids = fx13_db["version_ids"]
        old_groups = {vid: writing_db.list_comments(vid) for vid in vids}
        assert len(old_groups[vids[0]]) == 2
        assert len(old_groups[vids[1]]) == 1
        assert old_groups[vids[2]] == []

        new_groups = writing_db.list_comments_for_versions(vids)
        assert new_groups == old_groups, "批量分组应与逐版本查询逐字段一致"

        # only_open 口径一致
        assert writing_db.list_comments_for_versions(
            vids, only_open=True) == {
            vid: writing_db.list_comments(vid, only_open=True) for vid in vids}

        origins = {writing_db: writing_db.get_db_cursor}
        counter = {"n": 0, "sqls": []}
        mp = pytest.MonkeyPatch()
        _counting_patch(mp, writing_db, origins, counter)
        try:
            for vid in vids:
                writing_db.list_comments(vid)
            n_old = counter["n"]
            counter["n"] = 0
            writing_db.list_comments_for_versions(vids)
            n_new = counter["n"]
        finally:
            mp.undo()
        assert (n_old, n_new) == (3, 1), "版本历史意见线查询数应 3→1"

    # ------------------------------------------------------------ R5-7
    def test_r5_7_collect_equals_old_loop(self, fx13_db, monkeypatch):
        ids = fx13_db["cs_ids"]
        schemas = template_engine.derive_cluster_schemas("RUN", "en")
        assert schemas, "fx13 聚类运行应可提炼母图式"
        cluster = next(s for s in schemas if s.get("cluster_no") == 1)

        # 修复前等价循环：逐成员 instantiate_template（engine_schema=[cluster]）
        old_templates = []
        for m in cluster["members"]:
            tpl = template_engine.instantiate_template(
                "RUN", "en", int(m["sense_id"]), engine_schema=[cluster])
            if tpl:
                old_templates.append(tpl)

        payload = template_engine.collect_cluster_templates("RUN", "en", 1)
        assert payload["category"] == "RUN" and payload["language"] == "en"
        assert payload["cluster"]["cluster_no"] == 1
        assert payload["templates"] == old_templates, \
            "批量导出应与修复前逐成员循环逐字段一致"

        # 批量实例化 ≡ 逐义位（None 占位口径一致）
        old_by_id = {i: template_engine.instantiate_template("RUN", "en", i)
                     for i in ids}
        new_by_id = template_engine.instantiate_templates("RUN", "en", ids)
        assert new_by_id == old_by_id

        # 查询计数证据（实测）：3 成员 9→3（义位行/簇归属/特征向量各一次）
        origins = {template_engine: template_engine.get_db_cursor}
        counter = {"n": 0, "sqls": []}
        mp = pytest.MonkeyPatch()
        _counting_patch(mp, template_engine, origins, counter)
        try:
            for i in ids:
                template_engine.instantiate_template(
                    "RUN", "en", i, engine_schema=[cluster])
            n_old = counter["n"]
            counter["n"] = 0
            template_engine.instantiate_templates("RUN", "en", ids,
                                                  engine_schema=[cluster])
            n_new = counter["n"]
        finally:
            mp.undo()
        assert (n_old, n_new) == (9, 3), "模板批量取数查询数应 9→3"
