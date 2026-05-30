"""
LLM API 集成模块

提供与智谱 AI、DeepSeek、OpenAI 等大模型的接口。
"""

import os
import json
import logging
from typing import Optional

try:
    import zhipuai
    ZHIPUAI_AVAILABLE = True
except ImportError:
    ZHIPUAI_AVAILABLE = False
    logging.warning("zhipuai not installed. Install with: pip install zhipuai")

logger = logging.getLogger(__name__)


class LLMConfig:
    """LLM 配置类"""
    def __init__(self, provider='zhipu', api_key='', model_name='glm-4',
                 temperature=0.7, max_tokens=1000):
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    @classmethod
    def from_env(cls, provider=None):
        """从环境变量创建配置"""
        if provider is None:
            provider = os.getenv('DEFAULT_MODEL', 'zhipu')

        api_key = {
            'zhipu': os.getenv('ZHIPU_API_KEY', ''),
            'openai': os.getenv('OPENAI_API_KEY', ''),
            'deepseek': os.getenv('DEEPSEEK_API_KEY', '')
        }.get(provider, '')

        if not api_key:
            logger.warning(f"No API key found for provider: {provider}")

        return cls(
            provider=provider,
            api_key=api_key,
            model_name=os.getenv(f'{provider.upper()}_MODEL', f'{provider}-4'),
            temperature=float(os.getenv('TEMPERATURE', '0.7')),
            max_tokens=int(os.getenv('MAX_TOKENS', '1000'))
        )


class LLMService:
    """LLM 服务类"""

    def __init__(self, config=None):
        """初始化 LLM 服务"""
        self.config = config or LLMConfig.from_env()

        # 初始化 API 客户端
        if self.config.provider == 'zhipu' and ZHIPUAI_AVAILABLE:
            zhipuai.api_key = self.config.api_key
        elif self.config.provider == 'openai':
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.config.api_key)
            except ImportError:
                logger.warning("OpenAI SDK not available")
                self.client = None
        elif self.config.provider == 'deepseek':
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=self.config.api_key,
                    base_url="https://api.deepseek.com"
                )
            except ImportError:
                logger.warning("OpenAI SDK not available")

    def _build_prompt(self, verb):
        """构建提示词"""
        prompt = f"""你是一个中文动词语义分解专家。请为动词"{verb}"生成优化的释义，包含语义分解。

要求：
1. 提供一个简洁的中文释义
2. 将释义分解为语义要素（方式/路径/方向/体相）
3. 使用 JSON 格式返回

输出格式示例：
{{
    "chinese_ndef": "跑进来 - 主体以跑步的姿态进入某处",
    "semantic_table": [
        ["方式", "🏃", "主体采用跑步的姿态"],
        ["路径", "→", "运动经过的轨迹"],
        ["方向", "←", "朝向某处"],
        ["体相", "💫", "运动时的状态"]
    ],
    "example_sentence": "他跑进来气喘吁吁地报告情况。"
}}

请只返回 JSON，不要其他内容。"""
        return prompt

    def generate_definition(self, verb, force_refresh=False):
        """
        生成动词语义分解

        Args:
            verb: 动词
            force_refresh: 是否强制刷新缓存

        Returns:
            包含释义和语义分解的字典，失败返回 None
        """
        if not self.config.api_key:
            logger.error("No API key configured")
            return None

        prompt = self._build_prompt(verb)

        try:
            if self.config.provider == 'zhipu':
                response = zhipuai.model_api.invoke(
                    model=self.config.model_name,
                    prompt=prompt
                )
                result = response['data']['choices'][0]['content']
            elif self.config.provider == 'openai':
                response = self.client.chat.completions.create(
                    model=self.config.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens
                )
                result = response.choices[0].message.content
            elif self.config.provider == 'deepseek':
                response = self.client.chat.completions.create(
                    model=self.config.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens
                )
                result = response.choices[0].message.content

            # 解析 JSON
            definition = json.loads(result)

            logger.info(f"Generated definition for verb: {verb}")
            return definition

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for '{verb}': {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate definition for '{verb}': {e}")
            return None

    def get_available_models(self):
        """获取可用的模型列表"""
        return [self.config.model_name]


# 全局 LLM 服务实例
_llm_service = None


def get_llm_service():
    """获取或创建 LLM 服务实例"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def generate_verb_definition(verb):
    """
    生成动词语义分解的便捷函数

    Args:
        verb: 动词

    Returns:
        包含释义和语义分解的字典，失败返回 None
    """
    llm = get_llm_service()
    return llm.generate_definition(verb)
