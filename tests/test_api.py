"""
LLM API 集成测试
"""

import pytest
import os
import zhipuai
from src.api import LLMService, LLMConfig, get_llm_service


@pytest.fixture
def llm_config():
    """创建 LLM 配置"""
    return LLMConfig(
        provider='zhipu',
        api_key='test_api_key',
        model_name='glm-4'
    )


@pytest.fixture
def llm_service(llm_config):
    """创建 LLM 服务实例"""
    return LLMService(llm_config)


class TestLLMConfig:
    """LLM 配置测试"""

    def test_from_env(self):
        """测试从环境变量创建配置"""
        os.environ['ZHIPU_API_KEY'] = 'test_key'
        os.environ['DEFAULT_MODEL'] = 'zhipu'

        config = LLMConfig.from_env()
        assert config.api_key == 'test_key'
        assert config.provider == 'zhipu'

        del os.environ['ZHIPU_API_KEY']
        del os.environ['DEFAULT_MODEL']

    def test_default_values(self):
        """测试默认值"""
        config = LLMConfig()
        assert config.temperature == 0.7
        assert config.max_tokens == 1000


class TestLLMService:
    """LLM 服务测试"""

    def test_init(self, llm_service):
        """测试初始化"""
        assert llm_service.config is not None
        assert llm_service.config.api_key == 'test_api_key'

    def test_build_prompt(self, llm_service):
        """测试提示词构建"""
        prompt = llm_service._build_prompt("跑进来")
        assert "跑进来" in prompt
        assert "语义分解" in prompt

    def test_generate_definition_failure(self, llm_service, monkeypatch):
        """测试生成失败情况"""
        # Mock zhipuai.api_key 设置为空
        original_api_key = zhipuai.api_key
        monkeypatch.setattr('zhipuai.api_key', '')
        result = llm_service.generate_definition("测试动词")
        monkeypatch.setattr('zhipuai.api_key', original_api_key)
        assert result is None

    def test_get_available_models(self, llm_service):
        """测试获取模型列表"""
        models = llm_service.get_available_models()
        assert len(models) == 1
        assert models[0] == 'glm-4'


class TestGetLLMService:
    """全局服务获取测试"""

    def test_get_singleton(self):
        """测试单例模式"""
        service1 = get_llm_service()
        service2 = get_llm_service()
        assert service1 is service2
