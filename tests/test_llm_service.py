"""
LLM 服务单元测试

不依赖真实 API；使用 mock 验证：
- 配置缺失时抛 LLMConfigError
- chat 方法的请求/响应分支
- generate_relations 的 JSON 解析逻辑
- _extract_json 工具方法的鲁棒性
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from services.llm_service import (
    LLMConfigError,
    LLMService,
    get_llm_service,
    reset_llm_service,
)


# ========== 配置测试 ==========

class TestLLMConfig:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GLM_API_KEY", raising=False)
        with pytest.raises(LLMConfigError, match="缺少 GLM API Key"):
            LLMService()

    def test_api_key_from_param(self, monkeypatch):
        monkeypatch.delenv("GLM_API_KEY", raising=False)
        svc = LLMService(api_key="test-key-123")
        assert svc.api_key == "test-key-123"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "env-key-456")
        svc = LLMService()
        assert svc.api_key == "env-key-456"

    def test_param_overrides_env(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "env-key")
        svc = LLMService(api_key="param-key")
        assert svc.api_key == "param-key"

    def test_default_model(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "k")
        svc = LLMService()
        assert svc.model == "glm-4-flash"

    def test_custom_model_via_env(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "k")
        monkeypatch.setenv("GLM_MODEL", "glm-4-plus")
        svc = LLMService()
        assert svc.model == "glm-4-plus"


# ========== chat 方法测试 ==========

class TestChat:
    @pytest.fixture
    def svc(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "test-key")
        return LLMService()

    def test_success_response(self, svc):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "hello"}}]
        }
        with patch("services.llm_service.requests.post", return_value=mock_response) as mock_post:
            result = svc.chat([{"role": "user", "content": "hi"}])

        assert "choices" in result
        assert result["choices"][0]["message"]["content"] == "hello"
        mock_post.assert_called_once()
        # 验证 API Key 传入 header
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"

    def test_non_200_status(self, svc):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        with patch("services.llm_service.requests.post", return_value=mock_response):
            result = svc.chat([{"role": "user", "content": "hi"}])

        assert "error" in result
        assert result["status_code"] == 401

    def test_timeout(self, svc):
        with patch(
            "services.llm_service.requests.post",
            side_effect=requests.exceptions.Timeout(),
        ):
            result = svc.chat([{"role": "user", "content": "hi"}])
        assert "超时" in result["error"]

    def test_network_error(self, svc):
        with patch(
            "services.llm_service.requests.post",
            side_effect=requests.exceptions.ConnectionError("conn refused"),
        ):
            result = svc.chat([{"role": "user", "content": "hi"}])
        assert "网络请求异常" in result["error"]

    def test_invalid_json_response(self, svc):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        with patch("services.llm_service.requests.post", return_value=mock_response):
            result = svc.chat([{"role": "user", "content": "hi"}])
        assert "error" in result
        assert "JSON 解析失败" in result["error"]


# ========== JSON 提取测试 ==========

class TestExtractJson:
    def test_pure_json(self):
        data = {"synonym": ["a", "b"]}
        assert LLMService._extract_json(json.dumps(data)) == data

    def test_json_with_prefix_text(self):
        content = '以下是结果：\n{"synonym": ["a"]}'
        assert LLMService._extract_json(content) == {"synonym": ["a"]}

    def test_json_with_suffix_text(self):
        content = '{"antonym": ["x"]}\n以上是答案。'
        assert LLMService._extract_json(content) == {"antonym": ["x"]}

    def test_json_in_code_block(self):
        content = '```json\n{"related": ["y"]}\n```'
        assert LLMService._extract_json(content) == {"related": ["y"]}

    def test_invalid_content_returns_none(self):
        assert LLMService._extract_json("not json at all") is None

    def test_empty_string(self):
        assert LLMService._extract_json("") is None


# ========== generate_relations 测试 ==========

class TestGenerateRelations:
    @pytest.fixture
    def svc(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "k")
        return LLMService()

    def test_returns_parsed_dict(self, svc):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "synonym": ["glad", "joyful"],
                        "antonym": ["sad"],
                        "related": ["smile"],
                        "homophone": [],
                        "family": ["happiness"],
                    })
                }
            }]
        }
        with patch("services.llm_service.requests.post", return_value=mock_response):
            result = svc.generate_relations("happy")

        assert result["synonym"] == ["glad", "joyful"]
        assert result["antonym"] == ["sad"]
        assert result["family"] == ["happiness"]

    def test_filters_to_requested_types(self, svc):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "synonym": ["a"],
                        "antonym": ["b"],
                        "related": ["c"],
                    })
                }
            }]
        }
        with patch("services.llm_service.requests.post", return_value=mock_response):
            result = svc.generate_relations("word", relation_types=["synonym"])

        # 仅包含 synonym，其他被过滤
        assert "synonym" in result
        assert "antonym" not in result

    def test_propagates_error(self, svc):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        with patch("services.llm_service.requests.post", return_value=mock_response):
            result = svc.generate_relations("happy")
        assert "error" in result


# ========== 单例测试 ==========

class TestSingleton:
    def setup_method(self):
        reset_llm_service()

    def teardown_method(self):
        reset_llm_service()

    def test_get_llm_service_singleton(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "k")
        svc1 = get_llm_service()
        svc2 = get_llm_service()
        assert svc1 is svc2

    def test_reset_clears_singleton(self, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "k")
        svc1 = get_llm_service()
        reset_llm_service()
        svc2 = get_llm_service()
        assert svc1 is not svc2
