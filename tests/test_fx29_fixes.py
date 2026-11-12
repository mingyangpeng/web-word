"""FX-29 回归：登录落地三分支（规范②组）＋ corpus_evidence 工具页面接线。

规范《平台架构设计规范.md》§9 L242-243 原文（实现以此为准）：
  「登录落地三分支：有待办→协作收件箱；有续接点→上次位置（侧边栏「继续：…」）；
    首次→搜索释义。……」

五道锁：
  1. 落地解析锁（单元，纯会话计算不触库）：三分支解析按规范语序 ——
     有待办→ai_hub；有续接点→上次位置（loader 缝）；首次→search；
     分支目标一律过 _visible_page_keys 角色可见集过滤（隐藏页视同未命中）；
  2. 优先级锁：分支序即规范语序 —— 有待办压过续接点；
  3. 落地写页锁（AppTest 真登录表单）：登录成功那一刻 session_state["page"]
     按三分支写入（无待办→search；有待办→ai_hub，viewer 亦然 ——
     ai_hub 六角色全可见）；
  4. 不劫持锁（AppTest）：落地后手动切页（radio 点选）即生效并跨轮保持
     —— 落地解析只在登录成功路径跑一次，不进每轮渲染；
  5. 接线等价锁（AppTest＋打桩）：语料页搭配明细两处调用经 corpus_evidence
     工具 run —— monkeypatch 数据层函数 mysql_db.get_corpus_collocations，
     断言 tool.run 收到的正是原直调参数（verb/slot/limit 逐字段一致，含
     params_schema 合并出的 slot=None 默认），返回行列表契约不变。

口径注记（照实，不遮掩）：
  * 分支 2「续接点」：用户上下文域（src/user_context_db，FX-31）的 user_state
    为键值面，「键 → 落地页」的页级换算与 set_resume_page_loader 绑定归其
    接线方 —— 本批只锁缝的行为（单元面测）。loader 缝只能在单元面测
    （AppTest 以脚本形态执行 app.py，script 命名空间的模块级缝无法从测试
    侧绑定）；AppTest 侧分支 2 恒不命中（由分支 1/3 用例覆盖）。
  * semantic_search_tool 未在本批接线：其 search_similar_senses 调用点在
    src/semantic_search.py（不在 app.py 托管面内），且 params_schema 不含
    页面级缓存 index（merge_params 丢弃非 schema 键）—— 接线欠账归后续批
    （需工具 owner 扩 params_schema 收 index 后补接）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

import pytest  # noqa: E402

import src.app as app_module  # noqa: E402
import src.collab_pages as collab_pages  # noqa: E402
import src.mysql_db as db  # noqa: E402
from src.page_guides import PAGE_KEYS, page_label  # noqa: E402
from src.users_db import create_user, ensure_user_tables  # noqa: E402

# ============================================
# 探针会话（纯会话计算，不触库；结构与 verify_login_full 输出一致）
# ============================================
_ADMIN = {"id": 901, "username": "fx29_admin", "display_name": "管理员",
          "role": "admin", "roles": ["dict_admin", "sys_admin"]}
_ANNOTATOR = {"id": 902, "username": "fx29_ann", "display_name": "标注员",
              "role": "annotator", "roles": ["annotator"]}
_VIEWER = {"id": 903, "username": "fx29_view", "display_name": "只读",
           "role": "viewer", "roles": ["viewer"]}


@pytest.fixture(autouse=True)
def _reset_resume_loader():
    """loader 缝复位＋flash 队列清空（autouse）：模块级缝/裸模式会话队列
    不跨用例泄漏（RV15-3 起分支 2 命中会写 ui_kit flash 队列）。"""
    yield
    app_module.set_resume_page_loader(None)
    from src import ui_kit
    ui_kit.st.session_state.pop(ui_kit._FLASH_QUEUE_KEY, None)


# ============================================
# 1+2. 落地解析锁 / 优先级锁（单元，不触库）
# ============================================
# RV15-1 口径更新：分支 1 加可裁决角色条件（_can_adjudicate_inbox 同源口径
# —— 有效六角色含 dict_admin/reviewer 才落 ai_hub），无裁决权角色
# （viewer/annotator/editor/sys_admin）有全局 pending 也顺序到分支 2/3；
# pending_inbox_count 全局计数不动（侧边栏徽章语义保留）。

@pytest.mark.parametrize("user", [_ADMIN, _ANNOTATOR, _VIEWER],
                         ids=["admin", "annotator", "viewer"])
def test_first_login_lands_search(user, monkeypatch):
    """分支 3「首次」：无待办且无续接点 → 搜索释义（全角色）。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    assert app_module._landing_page_for(user) == "search"


def test_adjudicator_pending_lands_collab_inbox(monkeypatch):
    """分支 1「有待办」：可裁决（legacy admin 两位一体）且 pending>0 → ai_hub。

    待办信号源与侧边栏「🤖 AI 待办」徽章同一函数（pending_inbox_count）。
    """
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
    assert app_module._landing_page_for(_ADMIN) == "ai_hub"


@pytest.mark.parametrize("user", [_ANNOTATOR, _VIEWER],
                         ids=["annotator", "viewer"])
def test_non_adjudicator_pending_skips_ai_hub(user, monkeypatch):
    """RV15-1：无裁决权角色有全局 pending → 不落 ai_hub，顺序到分支 3。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
    assert app_module._landing_page_for(user) == "search"


def test_non_adjudicator_pending_falls_to_resume(monkeypatch):
    """RV15-1 验收面：viewer 登录且有全局 pending → 落续接点而非 ai_hub。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
    app_module.set_resume_page_loader(lambda uid: "cluster")
    assert app_module._landing_page_for(_VIEWER) == "cluster"


def test_pending_zero_counts_as_first_time(monkeypatch):
    """pending_inbox_count()=0（库不可用/表未建/无待办的同口径）→ 非分支 1。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    assert app_module._landing_page_for(_ANNOTATOR) == "search"


def test_resume_point_lands_last_page(monkeypatch):
    """分支 2「有续接点」：loader 读到上次工作页 → 落地该页（角色可见）。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    app_module.set_resume_page_loader(lambda uid: "cluster")
    assert app_module._landing_page_for(_ADMIN) == "cluster"


def test_resume_none_means_first_time(monkeypatch):
    """loader 未读到续接点（None）→ 视同首次 → 搜索释义。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    app_module.set_resume_page_loader(lambda uid: None)
    assert app_module._landing_page_for(_ADMIN) == "search"


def test_pending_takes_priority_over_resume(monkeypatch):
    """优先级锁（规范语序即分支序）：有待办压过续接点（可裁决角色）。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 1)
    app_module.set_resume_page_loader(lambda uid: "cluster")
    assert app_module._landing_page_for(_ADMIN) == "ai_hub"


def test_resume_filtered_by_role_visibility(monkeypatch):
    """续接点指向该角色不可见页（dict_admin 对 viewer 隐藏）→ 视同未命中，
    顺序取分支 3；同一续接点对 dict_admin 可见则照常落地。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    app_module.set_resume_page_loader(lambda uid: "dict_admin")
    assert app_module._landing_page_for(_VIEWER) == "search"
    assert app_module._landing_page_for(_ADMIN) == "dict_admin"


def test_resume_junk_key_falls_through(monkeypatch):
    """续接点为未知页键（不在 PAGE_KEYS，必不在可见集）→ 视同未命中。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)
    app_module.set_resume_page_loader(lambda uid: "mystery")
    assert app_module._landing_page_for(_ADMIN) == "search"


def test_loader_failure_falls_through_to_search(monkeypatch):
    """loader 抛异常 → 按无续接点降级（fail-open 到下一分支），不外抛。"""
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 0)

    def _boom(uid):
        raise RuntimeError("user_state 不可读")

    app_module.set_resume_page_loader(_boom)
    assert app_module._landing_page_for(_ADMIN) == "search"


def test_landing_targets_always_valid_page_keys(monkeypatch):
    """路由契约哨兵：三分支落地键必属 PAGE_KEYS（键集 17 键不变）。

    RV15-1：admin（可裁决）落 ai_hub；annotator/viewer（无裁决权）顺序到
    分支 2 落续接点 cluster（cluster 六角色全可见）—— 落地键仍在可见集内。
    """
    assert len(PAGE_KEYS) == 17
    monkeypatch.setattr(app_module, "pending_inbox_count", lambda: 2)
    app_module.set_resume_page_loader(lambda uid: "cluster")
    hits = {app_module._landing_page_for(u) for u in (_ADMIN, _ANNOTATOR, _VIEWER)}
    assert hits <= set(PAGE_KEYS), f"落地键越出 PAGE_KEYS: {hits}"
    assert hits == {"ai_hub", "cluster"}


# ============================================
# AppTest 测试库（建库失败 → 仅 AppTest 用例 skip；单元用例不受影响）
# ============================================

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")
# 预授权测试库（scripts/grant_local_mysql.sql 授权覆盖，自建库名无 GRANT）。
# 专用沙箱库（批次 27 监工轮 RV18-3 归位：此前复用 writing_test 与
# test_writing_db 共享面存在并行互踩风险；本库授权见 grant_local_mysql.sql）
# （pytest 串行约定下各模块 fixture 建库/删库互不重叠 —— 并行会话另论。）
TEST_DB = "web_word_fx29_test"
TIMEOUT = 180

_USERS = (("fx29_ann", "fx29-ann-pw", "标注员", "annotator"),
          ("fx29_view", "fx29-view-pw", "只读用户", "viewer"),
          ("fx29_rev", "fx29-rev-pw", "审校用户", "reviewer"))


@pytest.fixture(scope="module")
def fx29_db():
    """模块级测试库（test_integration_apptest.r3_env 同约定）：建库→建表→
    建号，结束后还原全局库名再删库。MySQL 不可用只 skip 依赖它的用例。"""
    import pymysql

    try:
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(
            f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.close()
    except pymysql.err.OperationalError as e:
        pytest.skip(f"MySQL 不可用或账号无建库权限，跳过 FX-29 AppTest 用例: {e}")

    old_db = db.MYSQL_DATABASE
    db.MYSQL_DATABASE = TEST_DB
    try:
        assert db.init_database(), "测试库初始化失败"
        ensure_user_tables()
        for username, password, display_name, role in _USERS:
            uid = create_user(username, password, display_name, role)
            assert isinstance(uid, int) and uid > 0, f"建测试账号失败: {username}"
        yield
    finally:
        db.MYSQL_DATABASE = old_db  # 先还原全局再删库（与 r3_env 同约定）
        conn = pymysql.connect(
            host=db.MYSQL_HOST, port=db.MYSQL_PORT, user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD, charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=3,
            autocommit=True,
        )
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()


def _new_at():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _pget(at, key, default=None):
    """AppTest 会话读取（SafeSessionState 不支持 .get()）。"""
    try:
        return at.session_state[key]
    except Exception:  # noqa: BLE001
        return default


def _form_login(at, username: str, password: str):
    """侧边栏登录表单真实提交（与 test_integration_apptest 同一手法）。"""
    inputs = {t.key: t for t in at.sidebar.text_input}
    inputs["login_username"].set_value(username)
    inputs["login_password"].set_value(password)
    submit = [b for b in at.sidebar.button
              if b.form_id and "登录" in str(b.label)]
    assert submit, "登录提交按钮未找到"
    submit[0].click()
    at.run()
    return at


def _goto(at, key: str):
    """点侧边栏导航按钮切页（批次 22 按钮式侧边栏；on_click 后 rerun）。"""
    for b in at.sidebar.button:
        if str(b.label) == page_label(key):
            b.click()
            at.run()
            return
    raise AssertionError(f"导航按钮不存在: {key}")


# ============================================
# 3. 落地写页锁（AppTest 真登录表单）
# ============================================

def test_login_first_time_lands_search(fx29_db, monkeypatch):
    """真登录表单：无待办 → 落地搜索释义（分支 3「首次」）。"""
    monkeypatch.setattr(collab_pages, "pending_inbox_count", lambda: 0)
    at = _new_at()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert _pget(at, "user") is None
    assert _pget(at, "page") == "search"  # 未登录残留页回退（既有口径）

    at = _form_login(at, "fx29_ann", "fx29-ann-pw")
    assert not at.exception, [str(e.value) for e in at.exception]
    user = _pget(at, "user")
    assert isinstance(user, dict) and user["username"] == "fx29_ann"
    assert _pget(at, "page") == "search", "登录落地（首次）应为搜索释义"


def test_login_with_pending_lands_ai_hub(fx29_db, monkeypatch):
    """真登录表单：可裁决角色（reviewer）有待办 → 落地协作收件箱（RV15-1）。

    登录前残留页为 search（未登录回退），登录后被落地改写为 ai_hub ——
    证明「落地写页」确实发生在登录成功那一刻。
    """
    monkeypatch.setattr(collab_pages, "pending_inbox_count", lambda: 2)
    at = _new_at()
    at.run()
    assert _pget(at, "page") == "search"

    at = _form_login(at, "fx29_rev", "fx29-rev-pw")
    assert not at.exception, [str(e.value) for e in at.exception]
    user = _pget(at, "user")
    assert isinstance(user, dict) and user["username"] == "fx29_rev"
    assert _pget(at, "page") == "ai_hub", "登录落地（有待办）应为协作收件箱"


def test_login_viewer_with_pending_skips_ai_hub(fx29_db, monkeypatch):
    """RV15-1 AppTest 面：viewer 有全局 pending → 不落 ai_hub（首次到 search）。"""
    monkeypatch.setattr(collab_pages, "pending_inbox_count", lambda: 2)
    at = _new_at()
    at.run()
    at = _form_login(at, "fx29_view", "fx29-view-pw")
    assert not at.exception, [str(e.value) for e in at.exception]
    user = _pget(at, "user")
    assert isinstance(user, dict) and user["username"] == "fx29_view"
    assert _pget(at, "page") == "search", "无裁决权角色不因全局 pending 落 ai_hub"


# ============================================
# 4. 不劫持锁（AppTest：落地后手动切页）
# ============================================

def test_manual_page_switch_after_landing_not_hijacked(fx29_db, monkeypatch):
    """落地后手动切页不被劫持：radio 点选即生效并跨轮保持。

    落地解析只在登录成功路径跑一次 —— 切页、再跑一轮（无任何输入）后
    页面停留在用户选择，不弹回 ai_hub。（RV15-1：落地 ai_hub 用可裁决的
    reviewer 账号。）
    """
    monkeypatch.setattr(collab_pages, "pending_inbox_count", lambda: 2)
    at = _new_at()
    at.run()
    at = _form_login(at, "fx29_rev", "fx29-rev-pw")
    assert _pget(at, "page") == "ai_hub", "前置：登录落地协作收件箱"

    _goto(at, "search")
    at.run()
    assert _pget(at, "page") == "search", "手动切页即生效"

    _goto(at, "graph")
    at.run()
    assert _pget(at, "page") == "graph"

    at.run()  # 再跑一轮（无输入）—— 不被劫持回 ai_hub
    assert not at.exception, [str(e.value) for e in at.exception]
    assert _pget(at, "page") == "graph", "落地不得劫持用户手动切页"


# ============================================
# 5. 接线等价锁（AppTest＋打桩：corpus_evidence tool.run 参数透传）
# ============================================

# 语料页只读面打桩的 canned 行（列结构与 mysql_db.get_corpus_collocations 一致）
_COLLS = [
    {"id": 1, "slot": 'objects of "%w"', "rank_in_slot": 1, "collocate": "table",
     "logdice": 10.5, "cooccur_count": 120, "typical_combo": "",
     "combo_freq": 0, "semantic_category": "", "keep_flag": ""},
    {"id": 2, "slot": 'objects of "%w"', "rank_in_slot": 2, "collocate": "chair",
     "logdice": 9.4, "cooccur_count": 80, "typical_combo": "",
     "combo_freq": 0, "semantic_category": "", "keep_flag": ""},
]

_OVERVIEW_ROW = {"verb": "walk", "lpos": "V", "freq": 1000, "relfreq": 10.0,
                 "slot_count": 2, "collocate_count": 50,
                 "candidate_schema": "", "max_score": 0.5}


def test_corpus_page_routes_through_registry_tool(fx29_db, monkeypatch):
    """语料页搭配明细两处调用经 corpus_evidence 工具 run —— 页面原直调参数
    原样透传（逐字段断言 tool.run → 数据层收到的 kwargs）：
      * 全槽位枚举：get_corpus_collocations(picked, limit=2000)
        → run({"verb": picked, "limit": 2000}) → 数据层 (verb, slot=None, 2000)
        （slot=None 为 params_schema 默认值合并补齐，与原直调的形参默认等价）；
      * 单槽位明细：get_corpus_collocations(picked, slot=slot, limit=100)
        → run({"verb": picked, "slot": slot, "limit": 100})。
    返回行列表契约不变：canned 行进入可编辑明细，页面渲染无异常。
    """
    calls = []

    def fake_collocations(**kwargs):
        calls.append(dict(kwargs))
        return [dict(r) for r in _COLLS]

    # 数据层打桩：工具 run 经 mysql_db 模块属性查找委托 → 桩必经 tool.run
    monkeypatch.setattr(db, "get_corpus_collocations", fake_collocations)
    # 页面其余只读面一并打桩（本用例聚焦接线等价性，不依赖语料库灌数）
    monkeypatch.setattr(db, "corpus_dataset_ready", lambda: True)
    monkeypatch.setattr(db, "get_corpus_overview", lambda: [dict(_OVERVIEW_ROW)])
    monkeypatch.setattr(db, "get_corpus_word_stats",
                        lambda verb: {"freq": 1000, "relfreq": 10.0,
                                      "slot_count": 2, "collocate_count": 50})
    monkeypatch.setattr(db, "get_corpus_schema_scores", lambda verb: [])
    monkeypatch.setattr(db, "get_corpus_schema_evidence", lambda verb, top_n=5: [])

    at = _new_at()
    at.session_state["page"] = "corpus"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    # 页面恰好两处取数，全部经注册表工具（原调用点参数原样透传）
    assert len(calls) == 2, f"搭配明细取数次数漂移: {calls}"
    assert calls[0] == {"verb": "walk", "slot": None, "limit": 2000}
    assert calls[1] == {"verb": "walk", "slot": 'objects of "%w"', "limit": 100}

    # 返回值契约不变：明细 section 照常渲染（编辑入口在场）
    captions = " ".join(str(c.value) for c in at.caption)
    assert "PS 计算口径" in captions
    assert "当前槽位：2 行" in captions


class TestResumeGlue:
    """RV18-3：续接点胶水层真适配器＋登出写路径行为覆盖（此前仅 lambda 桩喂缝）。"""

    # FX-35 适配（非接线失联，照实注明）：本类跑在模块专属库
    # web_word_fx29_test 上，而 user_context_db 的惰性建表哨兵
    # _TABLES_ENSURED 是**进程级**的 —— 任何先行模块在自己的测试库上触发过
    # 惰性建表（如 test_integration_apptest 登录落地 → _resume_page_loader →
    # list_states），本类再调 ensure_user_context_tables() 就被哨兵直通跳过
    # DDL，user_state 在本模块库中不存在 → 误报失败（与被测代码无关的用例
    # 顺序脆弱性；全量字母序 fx29 先于 integration 故基线未暴露）。照
    # fx31/fx33 既有哨兵手法（存值→置 False 强制重走 DDL→还原）补隔离。
    @pytest.fixture(autouse=True)
    def _force_context_ddl(self):
        import src.user_context_db as ucdb

        sentinel_before = ucdb._TABLES_ENSURED
        ucdb._TABLES_ENSURED = False  # 强制重走 DDL 路径（本模块专属库）
        yield
        ucdb._TABLES_ENSURED = sentinel_before

    def test_adapter_reads_own_state_row(self, fx29_db, monkeypatch):
        """真适配器：会话派生 list_states 读 resume_page；未写/删除后返 None。"""
        import src.user_context_db as ucdb

        monkeypatch.setattr(
            ucdb, "current_user",
            lambda: {"id": 2, "username": "fx29_ann", "role": "annotator",
                     "roles": ["annotator"]})
        ucdb.ensure_user_context_tables()
        assert app_module._resume_page_loader(2) is None  # 未写 → None
        assert ucdb.upsert_state("resume_page", "cluster") is True
        assert app_module._resume_page_loader(2) == "cluster"
        assert ucdb.delete_state("resume_page") is True
        assert app_module._resume_page_loader(2) is None

    def test_adapter_non_string_value_returns_none(self, fx29_db, monkeypatch):
        """脏值 fail-open：state_value 非字符串（数值注入）→ None 不落地。"""
        import src.user_context_db as ucdb

        monkeypatch.setattr(
            ucdb, "current_user",
            lambda: {"id": 2, "username": "fx29_ann", "role": "annotator",
                     "roles": ["annotator"]})
        ucdb.ensure_user_context_tables()
        ucdb.upsert_state("resume_page", "cluster")
        # 直写脏值（绕过 upsert 的 str 校验——模拟库内脏数据）
        with db.get_db_cursor() as cursor:
            cursor.execute(
                "UPDATE user_state SET state_value = %s "
                "WHERE state_key = 'resume_page'", ("12345",))
        assert app_module._resume_page_loader(2) is None
        ucdb.delete_state("resume_page")

    def test_logout_write_path_wires_upsert_state(self):
        """登出写路径源级钉板：_logout 经会话派生 upsert_state 落 resume_page
        （RV18-3 胶水另一半；写库行为本体由 fx31 upsert 测试覆盖）。"""
        import inspect

        src = inspect.getsource(app_module._logout)
        assert "upsert_state" in src
        assert '"resume_page"' in src
        assert "PAGE_KEYS" in src  # 页键白名单守卫在场
