"""多供应商 LLM 配置层测试（src/llm_providers_db.py + llm_api DB 路由）。

三层结构，与 tests/ 既有约定一致：

  * 纯单元（models 解析 / 入参校验 / HTTP 助手 / connectivity mock /
    llm_api 路由）—— 不碰数据库不触网，本地与 CI 全跑；
  * 数据层 CRUD（ensure 幂等 / UNIQUE / set_default 事务 / 停用联动）——
    真实 MySQL，专用测试库 web_word_llm_providers_test，连不上或账号无
    建库权限就 skip（类级 skipif + fixture 内 skip），CI 依然全绿；
  * llm_api × DB 全链路（真实建库 → 默认供应商 → _get_db_provider →
    客户端构造）—— 同一专库，验证四级降级链第一级真实生效。

llm_api 路由测试的核心契约：
  * DB 供应商（is_default=1 AND enabled=1）优先于 .env 三家 key；
  * DB 缺席/读取失败/构造失败 → .env 路径语义与引入前逐字节一致；
  * LLM_PROVIDER 显式指定时按操作员口径钉死（zhipu/openai/deepseek 跳过
    DB 层；"db" 钉死 DB 不降级）。
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.mysql_db as db  # noqa: E402
from src import llm_api  # noqa: E402
from src import llm_providers_db as lpdb  # noqa: E402
from src.llm_providers_db import (  # noqa: E402
    CONNECTIVITY_TIMEOUT,
    create_provider,
    delete_provider,
    ensure_llm_provider_tables,
    get_default_provider,
    get_provider,
    http_post_json,
    list_providers,
    set_default,
    set_enabled,
    update_provider,
    _models_from_raw,
)

TEST_DB = "web_word_llm_providers_test"

_NO_DB_TOUCH = "被测函数不应触碰数据库（校验须发生在任何 DB 访问之前）"


def _mysql_reachable() -> bool:
    """探测 MySQL 是否可用（只建连接，不建库）。"""
    try:
        import pymysql
        from pymysql.cursors import DictCursor

        conn = pymysql.connect(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=DictCursor,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_MYSQL = _mysql_reachable()


def _q(sql: str, params: tuple = ()):
    """测试内直查（走被 patch 到测试库的连接池；与被测数据层同口径）。"""
    with db.get_db_cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _db_provider(**overrides):
    """构造一个 DB 供应商 dict（llm_api 路由测试用，形状与数据层返回一致）。"""
    provider = {
        "id": 1,
        "name": "corp-gw",
        "base_url": "https://gw.corp.example/v1",
        "api_format": "openai",
        "api_key": "sk-db-1",
        "models": ["db-model-a", "db-model-b"],
        "enabled": True,
        "is_default": True,
        "sort_order": 0,
        "created_by": None,
        "created_at": None,
    }
    provider.update(overrides)
    return provider


# ============================================
# 纯单元：models 解析
# ============================================

class TestModelsParsing:
    """_models_from_raw 容错解析（JSON 列读出的各种形态）。"""

    def test_json_string(self):
        assert _models_from_raw('["model-a", "model-b"]') == ["model-a", "model-b"]

    def test_native_list_passthrough(self):
        assert _models_from_raw([" m1 ", "m2"]) == ["m1", "m2"]
        assert _models_from_raw(("m1",)) == ["m1"]

    def test_none_and_empty(self):
        assert _models_from_raw(None) == []
        assert _models_from_raw("") == []
        assert _models_from_raw("[]") == []
        assert _models_from_raw(["  ", ""]) == []

    def test_invalid_json_returns_empty(self):
        assert _models_from_raw("not-json{") == []

    def test_non_list_json(self):
        # 单字符串形态（["glm-4"] 的误写）接受；数字等垃圾拒绝
        assert _models_from_raw('"glm-4"') == ["glm-4"]
        assert _models_from_raw("42") == []

    def test_non_string_items_filtered(self):
        assert _models_from_raw('["m1", 42, null, "m2"]') == ["m1", "m2"]


# ============================================
# 纯单元：入参校验（不碰数据库）
# ============================================

class TestValidationNoDb:
    """create/update/get/delete 的入口校验须在任何 DB 访问之前生效。"""

    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError(_NO_DB_TOUCH)

        monkeypatch.setattr(lpdb, "get_db_cursor", _boom)

    @pytest.mark.parametrize("kwargs", [
        dict(name="", base_url="https://x.example", api_format="openai", api_key="k"),
        dict(name="n", base_url="  ", api_format="openai", api_key="k"),
        dict(name="n", base_url="https://x.example", api_format="openai", api_key="  "),
    ])
    def test_create_rejects_missing_fields(self, kwargs):
        assert create_provider(**kwargs) == 0

    @pytest.mark.parametrize("fmt", ["grpc", "", "OPEN AI", None])
    def test_create_rejects_bad_api_format(self, fmt):
        assert create_provider("n", "https://x.example", fmt, "k") == 0

    def test_create_rejects_bad_models(self):
        assert create_provider("n", "https://x.example", "openai", "k",
                               models="glm-4") == 0  # str 不是列表
        assert create_provider("n", "https://x.example", "openai", "k",
                               models=42) == 0

    @pytest.mark.parametrize("bad_by", [0, -1, "1", True, 1.5])
    def test_create_rejects_bad_created_by(self, bad_by):
        assert create_provider("n", "https://x.example", "openai", "k",
                               created_by=bad_by) == 0

    def test_update_rejects_non_whitelist_fields(self):
        # is_default 刻意不在白名单（唯一默认由 set_default 事务保证）
        assert update_provider(1, is_default=1) is False
        assert update_provider(1, hacker="x") is False

    def test_update_rejects_no_fields(self):
        assert update_provider(1) is False

    @pytest.mark.parametrize("kwargs", [
        dict(api_format="grpc"),
        dict(models="glm-4"),
        dict(base_url="   "),
        dict(api_key=""),
        dict(sort_order="abc"),
    ])
    def test_update_rejects_bad_values(self, kwargs):
        assert update_provider(1, **kwargs) is False

    @pytest.mark.parametrize("bad_id", [0, -1, "1", True, None])
    def test_get_delete_reject_bad_id(self, bad_id):
        assert get_provider(bad_id) is None
        assert delete_provider(bad_id) is False
        assert update_provider(bad_id, name="x") is False


# ============================================
# 纯单元：HTTP 助手（零新依赖的降级顺序）
# ============================================

class TestHttpHelper:
    """http_post_json：httpx 优先 → requests 兜底；网络异常上抛不静默。"""

    def test_prefers_httpx(self, monkeypatch):
        calls = []

        def _fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
            calls.append({"url": url, "json": json, "timeout": timeout})
            return SimpleNamespace(status_code=200, text="via-httpx")

        import httpx
        monkeypatch.setattr(httpx, "post", _fake_post)
        status, body = http_post_json("https://x.example/p", {"h": "1"},
                                      {"a": 1}, timeout=9)
        assert (status, body) == (200, "via-httpx")
        assert calls[0]["json"] == {"a": 1} and calls[0]["timeout"] == 9

    def test_falls_back_to_requests(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "httpx", None)  # 伪装 httpx 缺失

        def _fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
            return SimpleNamespace(status_code=503, text="via-requests")

        import requests
        monkeypatch.setattr(requests, "post", _fake_post)
        status, body = http_post_json("https://x.example/p", {}, {})
        assert (status, body) == (503, "via-requests")

    def test_no_http_lib_raises(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "httpx", None)
        monkeypatch.setitem(sys.modules, "requests", None)
        with pytest.raises(ImportError):
            http_post_json("https://x.example/p", {}, {})

    def test_network_error_propagates(self, monkeypatch):
        import httpx

        def _boom(*args, **kwargs):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(httpx, "post", _boom)
        with pytest.raises(RuntimeError):
            http_post_json("https://x.example/p", {}, {})


# ============================================
# 纯单元：连通性测试（HTTP 层全 mock，不触网）
# ============================================

class TestConnectivityUnit:
    """test_provider_connectivity 的请求形状与结果折算（get_provider mock）。"""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        self.captured = []
        self.provider = _db_provider(name="unit-gw", id=11,
                                     base_url="https://gw.example/v1/",
                                     models=["m1", "m2"])
        monkeypatch.setattr(lpdb, "get_provider", lambda pid: self.provider)

        def _capture(url, headers, payload, timeout=CONNECTIVITY_TIMEOUT):
            self.captured.append({"url": url, "headers": headers,
                                  "payload": payload, "timeout": timeout})
            return self.next_response

        self.next_response = (200, "{}")
        monkeypatch.setattr(lpdb, "http_post_json", _capture)

    def test_openai_request_shape(self):
        self.next_response = (200, '{"choices": []}')
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is True and result["error"] is None
        assert result["status_code"] == 200 and result["model"] == "m1"
        assert result["latency_ms"] >= 0
        call = self.captured[0]
        # base_url 尾斜杠被归一化；openai 格式追加 /chat/completions
        assert call["url"] == "https://gw.example/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer sk-db-1"
        assert call["payload"] == {"model": "m1", "max_tokens": 1,
                                   "messages": [{"role": "user", "content": "ping"}]}

    def test_anthropic_request_shape(self):
        self.provider.update(api_format="anthropic",
                             base_url="https://api.anthropic.example")
        self.next_response = (200, '{"content": []}')
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is True
        call = self.captured[0]
        assert call["url"] == "https://api.anthropic.example/v1/messages"
        assert call["headers"]["x-api-key"] == "sk-db-1"
        assert call["headers"]["anthropic-version"] == "2023-06-01"

    def test_auth_failure_401(self):
        self.next_response = (401, '{"error": "invalid key"}')
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is False and result["status_code"] == 401
        assert "认证失败" in result["error"]

    def test_auth_failure_403(self):
        self.next_response = (403, "")
        assert "认证失败" in lpdb.test_provider_connectivity(11)["error"]

    def test_not_found_hints_base_url(self):
        self.next_response = (404, "")
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is False and "404" in result["error"]
        assert "base_url" in result["error"]

    def test_server_error_contains_body_snippet(self):
        self.next_response = (500, "upstream-boom-body")
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is False and "upstream-boom-body" in result["error"]

    def test_network_error_soft(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("conn refused")

        monkeypatch.setattr(lpdb, "http_post_json", _boom)
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is False and result["status_code"] is None
        assert "网络错误" in result["error"] and result["latency_ms"] >= 0

    def test_missing_provider(self, monkeypatch):
        monkeypatch.setattr(lpdb, "get_provider", lambda pid: None)
        result = lpdb.test_provider_connectivity(999)
        assert result["ok"] is False and "供应商不存在" in result["error"]

    def test_no_models_configured(self):
        self.provider.update(models=[])
        result = lpdb.test_provider_connectivity(11)
        assert result["ok"] is False and "未配置模型" in result["error"]
        assert self.captured == [], "无模型时不应发起 HTTP 请求"


# ============================================
# 集成：真实 MySQL（专库 web_word_llm_providers_test，无环境则 skip）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL,
                    reason="MySQL 不可用，跳过 llm_providers 集成测试（真库）")
class TestProvidersDbIntegration:
    """CRUD / UNIQUE / set_default 事务 / 停用联动 / 真库连通性。"""

    @pytest.fixture
    def providers_db(self, monkeypatch):
        """建空测试库并让本模块指向它，ensure 建表（跑两遍验幂等），结束 DROP。"""
        import pymysql

        conn_params = dict(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
        )
        conn = pymysql.connect(**conn_params)
        try:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
                    cur.execute(
                        f"CREATE DATABASE {TEST_DB} "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
            except pymysql.err.OperationalError as e:
                pytest.skip(f"当前 MySQL 账号无建库权限，跳过集成测试: {e}")
        finally:
            conn.close()

        old_database = db.MYSQL_DATABASE
        try:
            db.MYSQL_DATABASE = TEST_DB
            ensure_llm_provider_tables()
            ensure_llm_provider_tables()  # 幂等：重复调用零副作用
            yield
        finally:
            # 还原全局并丢弃指向已删库的池条目（键含库名，防死连接滞留）
            db.MYSQL_DATABASE = old_database
            pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
            getattr(db, "_connection_pools", {}).pop(pool_key, None)
            conn = pymysql.connect(**conn_params)
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            finally:
                conn.close()

    # ------------------------------------------------------------
    # 建表与 DDL 契约
    # ------------------------------------------------------------
    def test_schema_contract(self, providers_db):
        cols = {r["COLUMN_NAME"]: r for r in _q(
            "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'llm_providers'",
            (TEST_DB,),
        )}
        assert set(cols) == {
            "id", "name", "base_url", "api_format", "api_key", "models",
            "enabled", "is_default", "sort_order", "created_by", "created_at",
        }
        assert cols["models"]["DATA_TYPE"] == "json"
        assert cols["models"]["IS_NULLABLE"] == "YES"
        # api_format ENUM 两个值齐全
        col_type = cols["api_format"]["COLUMN_TYPE"]
        assert "'openai'" in col_type and "'anthropic'" in col_type
        # name UNIQUE
        uniq = _q(
            "SELECT NON_UNIQUE FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'llm_providers' "
            "AND COLUMN_NAME = 'name'",
            (TEST_DB,),
        )
        assert any(int(r["NON_UNIQUE"]) == 0 for r in uniq)

    # ------------------------------------------------------------
    # CRUD 往返
    # ------------------------------------------------------------
    def test_create_get_roundtrip(self, providers_db):
        pid = create_provider("prov-a", "https://a.example/v1", "OpenAI",
                              "sk-a1", models=["model-a", "model-b"], created_by=7)
        assert isinstance(pid, int) and pid > 0
        provider = get_provider(pid)
        assert provider["name"] == "prov-a"
        assert provider["base_url"] == "https://a.example/v1"
        assert provider["api_format"] == "openai"  # 大小写归一
        assert provider["api_key"] == "sk-a1"      # 管理决策：明文存储原样返回
        assert provider["models"] == ["model-a", "model-b"]
        assert provider["enabled"] is True and provider["is_default"] is False
        assert provider["sort_order"] == 0 and provider["created_by"] == 7
        assert provider["created_at"] is not None
        assert get_default_provider() is None  # 新建不自动成为默认

    def test_create_models_normalization(self, providers_db):
        none_id = create_provider("m-none", "https://x.example", "openai", "k")
        assert get_provider(none_id)["models"] == []
        empty_id = create_provider("m-empty", "https://x.example", "openai", "k",
                                   models=[])
        assert get_provider(empty_id)["models"] == []
        strip_id = create_provider("m-strip", "https://x.example", "openai", "k",
                                   models=["  m1 ", "", "m2"])
        assert get_provider(strip_id)["models"] == ["m1", "m2"]
        # anthropic 格式小写归一
        ant_id = create_provider("m-ant", "https://x.example", "Anthropic", "k",
                                 models=["claude-x"])
        assert get_provider(ant_id)["api_format"] == "anthropic"

    def test_unique_name(self, providers_db):
        first = create_provider("dup-name", "https://a.example", "openai", "k1")
        assert first > 0
        assert create_provider("dup-name", "https://b.example", "openai", "k2") == 0
        rows = list_providers()
        assert [r["name"] for r in rows if r["name"] == "dup-name"] == ["dup-name"]
        assert len(rows) == 1, "重名插入被 UNIQUE 拒绝，不产生第二行"

    def test_list_order_and_enabled_only(self, providers_db):
        p5 = create_provider("order-5", "https://x.example", "openai", "k")
        p1 = create_provider("order-1", "https://x.example", "openai", "k")
        p3 = create_provider("order-3", "https://x.example", "openai", "k")
        assert update_provider(p5, sort_order=5)
        assert update_provider(p1, sort_order=1)
        assert update_provider(p3, sort_order=3)
        assert [r["id"] for r in list_providers()] == [p1, p3, p5]
        assert set_enabled(p3, False) is True
        listed = list_providers()
        assert [r["id"] for r in listed] == [p1, p3, p5]
        assert [r["enabled"] for r in listed] == [True, False, True]
        assert [r["id"] for r in list_providers(enabled_only=True)] == [p1, p5]

    def test_update_provider_fields(self, providers_db):
        pid = create_provider("upd-a", "https://old.example/v1", "openai", "sk-old",
                              models=["old-m"])
        assert update_provider(pid, name="upd-b", base_url="https://new.example/v1",
                               api_key="sk-new", api_format="anthropic",
                               models=["new-m1", "new-m2"], sort_order=9) is True
        provider = get_provider(pid)
        assert provider["name"] == "upd-b"
        assert provider["base_url"] == "https://new.example/v1"
        assert provider["api_key"] == "sk-new"
        assert provider["api_format"] == "anthropic"
        assert provider["models"] == ["new-m1", "new-m2"]
        assert provider["sort_order"] == 9
        # 目标值与现值相同 → MySQL 不计变更行 → False（未变更口径）
        assert update_provider(pid, sort_order=9) is False

    def test_update_models_none_clears(self, providers_db):
        pid = create_provider("upd-m", "https://x.example", "openai", "k",
                              models=["m1"])
        assert update_provider(pid, models=None) is True
        assert get_provider(pid)["models"] == []

    def test_update_nonexistent(self, providers_db):
        assert update_provider(4321, name="ghost") is False

    def test_update_rejects_is_default_even_in_db(self, providers_db):
        pid = create_provider("upd-d", "https://x.example", "openai", "k")
        assert update_provider(pid, is_default=1) is False
        assert _q("SELECT is_default FROM llm_providers WHERE id = %s",
                  (pid,))[0]["is_default"] == 0

    def test_delete_provider(self, providers_db):
        pid = create_provider("del-a", "https://x.example", "openai", "k")
        assert delete_provider(pid) is True
        assert get_provider(pid) is None
        assert delete_provider(pid) is False  # 二次删除：不存在

    # ------------------------------------------------------------
    # set_default 事务与停用联动
    # ------------------------------------------------------------
    def test_set_default_transaction(self, providers_db):
        pa = create_provider("def-a", "https://x.example", "openai", "k")
        pb = create_provider("def-b", "https://x.example", "openai", "k")
        pc = create_provider("def-c", "https://x.example", "openai", "k")

        assert get_default_provider() is None  # 无默认
        assert set_default(pb) is True
        assert get_default_provider()["id"] == pb
        assert get_provider(pa)["is_default"] is False
        assert get_provider(pc)["is_default"] is False

        assert set_default(pc) is True
        # 全表至多一行 is_default=1（事务先清后设的不变量）
        defaults = _q("SELECT id FROM llm_providers WHERE is_default = 1")
        assert [int(r["id"]) for r in defaults] == [pc]

        # 不存在的供应商：False 且旧默认原封不动
        assert set_default(4321) is False
        assert get_default_provider()["id"] == pc

    def test_get_default_requires_enabled(self, providers_db):
        pid = create_provider("def-e", "https://x.example", "openai", "k")
        assert set_default(pid) is True
        assert get_default_provider()["id"] == pid

        # 停用默认供应商 → 生效链视作无默认（但 is_default 标记保留）
        assert set_enabled(pid, False) is True
        assert get_default_provider() is None
        assert _q("SELECT is_default FROM llm_providers WHERE id = %s",
                  (pid,))[0]["is_default"] == 1
        assert set_enabled(pid, True) is True
        assert get_default_provider()["id"] == pid

        # set_enabled 目标不存在 → False
        assert set_enabled(4321, True) is False

    # ------------------------------------------------------------
    # 连通性（真库取供应商 + HTTP 层 mock，不触网）
    # ------------------------------------------------------------
    def test_connectivity_through_real_db(self, providers_db, monkeypatch):
        pid = create_provider("conn-a", "https://conn.example/v1", "openai",
                              "sk-conn", models=["conn-m"])
        captured = []

        def _capture(url, headers, payload, timeout=CONNECTIVITY_TIMEOUT):
            captured.append({"url": url, "headers": headers, "payload": payload})
            return 200, "{}"

        monkeypatch.setattr(lpdb, "http_post_json", _capture)
        result = lpdb.test_provider_connectivity(pid)
        assert result["ok"] is True and result["model"] == "conn-m"
        assert captured[0]["url"] == "https://conn.example/v1/chat/completions"
        assert captured[0]["payload"]["model"] == "conn-m"

    def test_connectivity_no_models_real_db(self, providers_db):
        pid = create_provider("conn-b", "https://conn.example", "openai", "sk")
        result = lpdb.test_provider_connectivity(pid)
        assert result["ok"] is False and "未配置模型" in result["error"]


# ============================================
# llm_api 路由：DB 供应商优先 vs .env 降级（纯单元，无 DB）
# ============================================

_DEFN_JSON = json.dumps({
    "traditional": "T传统", "optimized": "O优化", "chinese_ndef": "C中文",
    "semantic_table": {"manner": "m", "path": "p", "direction": "d",
                       "aspect": "a", "scope": "s"},
    "example": "例句", "synonyms": ["近义"],
}, ensure_ascii=False)


class _FakeCompletions:
    """记录 create() 入参并回放固定内容的假 chat.completions。"""

    def __init__(self, recorder, content):
        self._recorder = recorder
        self._content = content

    def create(self, **kwargs):
        self._recorder.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=self._content)
        )])


class TestLlmApiRouting:
    """四级降级链：DB 供应商 → .env 三家 → (None, "")；LLM_PROVIDER 钉死口径。"""

    @pytest.fixture(autouse=True)
    def _route_env(self, monkeypatch):
        llm_api.reset_llm_client()
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        for key in ("ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_BASE_URL",
                    "OPENAI_API_KEY", "OPENAI_BASE_URL",
                    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"):
            monkeypatch.delenv(key, raising=False)
        yield
        llm_api.reset_llm_client()

    # ------------------------------------------------------------
    # 第 1 级：DB 供应商优先
    # ------------------------------------------------------------
    def test_db_provider_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")  # 也在场但必须让位
        ctor_calls = []

        def _fake_openai_ctor(**kwargs):
            ctor_calls.append(kwargs)
            return object()  # 哨兵客户端

        monkeypatch.setattr("openai.OpenAI", _fake_openai_ctor)
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: _db_provider())

        client, tag = llm_api.get_llm_client()
        assert tag == "db:corp-gw"
        assert ctor_calls == [{"api_key": "sk-db-1",
                               "base_url": "https://gw.corp.example/v1",
                               "timeout": llm_api.LLM_TIMEOUT}]
        # 模型名取 models 第一个，并同步 LLM_MODEL 全局（旧调用方直读也正确）
        assert llm_api.get_llm_model() == "db-model-a"
        assert llm_api.LLM_MODEL == "db-model-a"
        assert client is not None

    def test_db_provider_anthropic_format(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: _db_provider(
            name="ant-corp", api_format="anthropic",
            base_url="https://api.anthropic.example", models=["claude-x"]))
        client, tag = llm_api.get_llm_client()
        assert tag == "db:ant-corp"
        assert isinstance(client, llm_api._AnthropicCompatClient)
        assert client.base_url == "https://api.anthropic.example"
        assert llm_api.get_llm_model() == "claude-x"

    def test_db_provider_construction_failure_falls_down_chain(self, monkeypatch):
        # openai 格式但 openai SDK 不可用 → DB 构造失败 → 沿降级链继续。
        # 注意：SDK 缺失同样关掉 .env 的 openai/deepseek 分支（同一 SDK），
        # 下一级是智谱 —— 这正是「继续降级」要验证的落点。
        monkeypatch.setenv("ZHIPUAI_API_KEY", "sk-env-zp")
        zhipu_calls = []
        monkeypatch.setattr(llm_api, "ZhipuAI",
                            lambda **kw: zhipu_calls.append(kw) or object())
        monkeypatch.setattr(llm_api, "_openai_sdk_available", lambda: False)
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: _db_provider())

        client, tag = llm_api.get_llm_client()
        assert tag == "zhipu"
        assert zhipu_calls == [{"api_key": "sk-env-zp"}]

    def test_db_provider_missing_key_falls_back(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")
        monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
        monkeypatch.setattr(llm_api, "_get_db_provider",
                            lambda: _db_provider(api_key=""))

        client, tag = llm_api.get_llm_client()
        assert tag == "openai", "DB 供应商缺 api_key 应跳过并走 .env"

    # ------------------------------------------------------------
    # 第 2/3 级：.env 链语义不变
    # ------------------------------------------------------------
    def test_env_fallback_when_db_absent(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: None)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")
        ctor_calls = []
        monkeypatch.setattr("openai.OpenAI",
                            lambda **kw: ctor_calls.append(kw) or object())

        client, tag = llm_api.get_llm_client()
        assert tag == "openai"
        assert ctor_calls[0]["api_key"] == "sk-env-openai"
        assert ctor_calls[0]["base_url"] == "https://api.openai.com/v1"
        assert llm_api.get_llm_model() == llm_api.LLM_MODEL

    def test_env_deepseek_semantics_unchanged(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: None)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-ds")
        ctor_calls = []
        monkeypatch.setattr("openai.OpenAI",
                            lambda **kw: ctor_calls.append(kw) or object())

        client, tag = llm_api.get_llm_client()
        assert tag == "deepseek"
        assert ctor_calls[0]["base_url"] == "https://api.deepseek.com"

    def test_env_zhipu_semantics_unchanged(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: None)
        monkeypatch.setenv("ZHIPUAI_API_KEY", "sk-env-zp")
        zhipu_calls = []
        monkeypatch.setattr(llm_api, "ZhipuAI",
                            lambda **kw: zhipu_calls.append(kw) or object())

        client, tag = llm_api.get_llm_client()
        assert tag == "zhipu"
        assert zhipu_calls == [{"api_key": "sk-env-zp"}]

    def test_no_provider_at_all(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: None)
        assert llm_api.get_llm_client() == (None, "")
        assert llm_api.get_zhipuai_client() == (None, "")  # 旧名兼容仍可用

    # ------------------------------------------------------------
    # LLM_PROVIDER 强制指定口径
    # ------------------------------------------------------------
    def test_forced_env_provider_skips_db_layer(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")
        monkeypatch.setattr("openai.OpenAI", lambda **kw: object())

        def _must_not_be_called():
            raise AssertionError("LLM_PROVIDER=openai 时不应读 DB 供应商层")

        monkeypatch.setattr(llm_api, "_get_db_provider", _must_not_be_called)
        client, tag = llm_api.get_llm_client()
        assert tag == "openai"

    def test_forced_db_only_uses_db(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "db")
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: _db_provider())
        monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
        client, tag = llm_api.get_llm_client()
        assert tag == "db:corp-gw"

    def test_forced_db_only_does_not_fall_back(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "db")
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: None)
        assert llm_api.get_llm_client() == (None, ""), \
            "LLM_PROVIDER=db 显式钉死：DB 不可用不降级到 .env"

    # ------------------------------------------------------------
    # _get_db_provider 自身：静默降级 + TTL 缓存 + reset
    # ------------------------------------------------------------
    def test_get_db_provider_swallows_all_errors(self, monkeypatch):
        def _boom():
            raise RuntimeError("table missing / db down")

        monkeypatch.setattr(lpdb, "get_default_provider", _boom)
        assert llm_api._get_db_provider() is None  # 不抛异常，走 .env

    def test_get_db_provider_import_failure_soft(self, monkeypatch):
        # llm_providers_db 模块不可导入（离线模式）→ None，不抛。
        # `from src import llm_providers_db` 的字节码是
        # __import__('src', ..., fromlist=('llm_providers_db',)) —— 拦截该形态。
        import builtins
        real_import = builtins.__import__

        def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "src" and "llm_providers_db" in tuple(fromlist or ()):
                raise ImportError("offline mode")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        assert llm_api._get_db_provider() is None

    def test_get_db_provider_ttl_cache_and_reset(self, monkeypatch):
        calls = []

        def _counting():
            calls.append(1)
            return _db_provider()

        monkeypatch.setattr(lpdb, "get_default_provider", _counting)
        first = llm_api._get_db_provider()
        second = llm_api._get_db_provider()
        assert first is second and len(calls) == 1, "TTL 内复用缓存，不打重复 SELECT"
        llm_api.reset_llm_client()
        llm_api._get_db_provider()
        assert len(calls) == 2, "reset 后应立即重读 llm_providers 表"

    def test_reset_restores_env_model(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: _db_provider())
        monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
        env_model = llm_api._DEFAULT_LLM_MODEL
        llm_api.get_llm_client()
        assert llm_api.LLM_MODEL == "db-model-a" != env_model
        llm_api.reset_llm_client()
        assert llm_api.LLM_MODEL == env_model
        assert llm_api.get_llm_model() == env_model

    # ------------------------------------------------------------
    # anthropic 兼容客户端（HTTP 层 mock）
    # ------------------------------------------------------------
    def test_anthropic_client_protocol_mapping(self, monkeypatch):
        monkeypatch.setattr(llm_api, "_get_db_provider", lambda: _db_provider(
            name="ant-corp", api_format="anthropic",
            base_url="https://api.anthropic.example", models=["claude-x"]))
        client, _tag = llm_api.get_llm_client()

        captured = []

        def _fake_post(url, headers, payload, timeout=15):
            captured.append({"url": url, "headers": headers, "payload": payload,
                             "timeout": timeout})
            return 200, json.dumps({
                "content": [{"type": "text", "text": "你好"},
                            {"type": "text", "text": "！"},
                            {"type": "other", "text": "丢我"}],
                "model": "claude-x",
            })

        monkeypatch.setattr(lpdb, "http_post_json", _fake_post)
        response = client.chat.completions.create(
            model="claude-x",
            messages=[{"role": "system", "content": "sys-prompt"},
                      {"role": "user", "content": "user-ask"}],
            temperature=0.2, max_tokens=64, timeout=7,
        )
        assert response.choices[0].message.content == "你好！", \
            "多 text 块拼接，非 text 块丢弃"
        call = captured[0]
        assert call["url"] == "https://api.anthropic.example/v1/messages"
        assert call["headers"]["x-api-key"] == "sk-db-1"
        assert call["headers"]["anthropic-version"] == "2023-06-01"
        assert call["payload"]["system"] == "sys-prompt"  # system 消息升顶
        assert call["payload"]["messages"] == [{"role": "user",
                                                "content": "user-ask"}]
        assert call["payload"]["max_tokens"] == 64
        assert call["timeout"] == 7

    def test_anthropic_client_default_max_tokens(self, monkeypatch):
        client = llm_api._AnthropicCompatClient("https://x.example", "sk")
        captured = []
        monkeypatch.setattr(
            lpdb, "http_post_json",
            lambda url, headers, payload, timeout=15:
            captured.append(payload) or (200, '{"content": []}'),
        )
        client.chat.completions.create(model="m",
                                       messages=[{"role": "user", "content": "hi"}])
        assert captured[0]["max_tokens"] == llm_api.LLM_MAX_TOKENS  # Anthropic 必填

    def test_anthropic_client_http_error_raises_llmerror(self, monkeypatch):
        client = llm_api._AnthropicCompatClient("https://x.example", "sk")
        monkeypatch.setattr(
            lpdb, "http_post_json",
            lambda url, headers, payload, timeout=15: (429, "rate limited"),
        )
        with pytest.raises(llm_api.LLMError, match="429"):
            client.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "hi"}])

    def test_anthropic_client_bad_json_raises_llmerror(self, monkeypatch):
        client = llm_api._AnthropicCompatClient("https://x.example", "sk")
        monkeypatch.setattr(
            lpdb, "http_post_json",
            lambda url, headers, payload, timeout=15: (200, "not-json{"),
        )
        with pytest.raises(llm_api.LLMError, match="JSON"):
            client.chat.completions.create(
                model="m", messages=[{"role": "user", "content": "hi"}])

    # ------------------------------------------------------------
    # _call_llm_api 模型名取 get_llm_model()（DB 供应商 → models[0]）
    # ------------------------------------------------------------
    def test_call_llm_api_uses_effective_model(self, monkeypatch):
        calls = []
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeCompletions(calls, _DEFN_JSON)))
        monkeypatch.setattr(llm_api, "get_llm_client",
                            lambda: (fake_client, "db:corp-gw"))
        monkeypatch.setattr(llm_api, "_client_model", "db-model-a")

        result = llm_api._call_llm_api("跑")
        assert calls and calls[0]["model"] == "db-model-a", \
            "调用模型名应取 get_llm_model()（DB 供应商首个模型）"
        assert result["traditional"] == "T传统"
        assert result["semantic_table"]["manner"] == "m"
        assert result["verb"] == "跑"

    def test_call_llm_api_model_falls_back_to_env(self, monkeypatch):
        calls = []
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=_FakeCompletions(calls, _DEFN_JSON)))
        monkeypatch.setattr(llm_api, "get_llm_client",
                            lambda: (fake_client, "openai"))

        result = llm_api._call_llm_api("走")
        assert calls[0]["model"] == llm_api.LLM_MODEL
        assert result["optimized"] == "O优化"


# ============================================
# llm_api × DB 全链路（真实 MySQL 专库）
# ============================================

@pytest.mark.skipif(not HAS_MYSQL,
                    reason="MySQL 不可用，跳过 llm_api×DB 全链路测试（真库）")
class TestLlmApiDbChainIntegration:
    """真实建库 → 默认供应商 → llm_api._get_db_provider → 客户端构造。

    复用 TestProvidersDbIntegration 的建库手法（独立类避免互为前置）。
    """

    @pytest.fixture
    def providers_db(self, monkeypatch):
        import pymysql

        conn_params = dict(
            host=db.MYSQL_HOST,
            port=db.MYSQL_PORT,
            user=db.MYSQL_USER,
            password=db.MYSQL_PASSWORD,
            charset=db.MYSQL_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=3,
        )
        conn = pymysql.connect(**conn_params)
        try:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
                    cur.execute(
                        f"CREATE DATABASE {TEST_DB} "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
            except pymysql.err.OperationalError as e:
                pytest.skip(f"当前 MySQL 账号无建库权限，跳过集成测试: {e}")
        finally:
            conn.close()

        old_database = db.MYSQL_DATABASE
        try:
            db.MYSQL_DATABASE = TEST_DB
            ensure_llm_provider_tables()
            yield
        finally:
            db.MYSQL_DATABASE = old_database
            pool_key = (db.MYSQL_HOST, db.MYSQL_PORT, TEST_DB, db.MYSQL_USER)
            getattr(db, "_connection_pools", {}).pop(pool_key, None)
            llm_api.reset_llm_client()  # 丢弃指向测试库的供应商缓存
            conn = pymysql.connect(**conn_params)
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            finally:
                conn.close()

    def test_full_db_chain_openai(self, providers_db, monkeypatch):
        pid = create_provider("it-openai", "https://it.example/v1", "openai",
                              "sk-it", models=["it-model-1", "it-model-2"])
        assert set_default(pid) is True
        llm_api.reset_llm_client()  # 立即重读（不等 TTL）

        provider = llm_api._get_db_provider()
        assert provider is not None
        assert provider["name"] == "it-openai"
        assert provider["models"] == ["it-model-1", "it-model-2"]  # JSON 解析
        assert provider["enabled"] is True and provider["is_default"] is True

        # openai SDK 已在依赖内 → 真实构造（不触网）
        client = llm_api._build_db_provider_client(provider)
        assert client is not None
        assert "openai" in type(client).__module__
        assert str(client.base_url).rstrip("/") == "https://it.example/v1"

    def test_full_db_chain_anthropic(self, providers_db):
        pid = create_provider("it-anthropic", "https://api.anthropic.example",
                              "anthropic", "sk-it-ant", models=["claude-it"])
        assert set_default(pid) is True
        llm_api.reset_llm_client()

        provider = llm_api._get_db_provider()
        assert provider["api_format"] == "anthropic"
        client = llm_api._build_db_provider_client(provider)
        assert isinstance(client, llm_api._AnthropicCompatClient)
        assert client.api_key == "sk-it-ant"
        assert llm_api._first_model_of(provider) == "claude-it"

    def test_disabled_default_is_invisible_to_llm_api(self, providers_db):
        pid = create_provider("it-disabled", "https://it.example", "openai",
                              "sk-it", models=["m"])
        assert set_default(pid) is True
        assert set_enabled(pid, False) is True
        llm_api.reset_llm_client()
        assert llm_api._get_db_provider() is None, \
            "停用的默认供应商应令 llm_api 视作无 DB 供应商（回落 .env）"

    def test_no_default_provider_is_invisible_to_llm_api(self, providers_db):
        assert create_provider("it-nodefault", "https://it.example", "openai",
                               "sk-it", models=["m"]) > 0
        llm_api.reset_llm_client()
        assert llm_api._get_db_provider() is None
