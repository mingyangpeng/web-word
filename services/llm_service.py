"""
智谱 AI GLM-4.7-Flash 大模型服务封装

通过 HTTPS 调用智谱 AI 的 chat/completions 接口，
提供单词分析、关系生成、对话等能力。
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

from config.constants import (
    GLM_API_TIMEOUT_SECONDS,
    GLM_DEFAULT_MODEL,
    GLM_DEFAULT_TEMPERATURE,
    GLM_MAX_TOKENS_ANALYZE,
    GLM_MAX_TOKENS_CHAT,
    GLM_MAX_TOKENS_EXAMPLES,
    GLM_MAX_TOKENS_RELATIONS,
    RELATION_TYPES,
)
from config.env import load_dotenv
from config.logging_config import get_logger

logger = get_logger(__name__)


# ========== 异常定义 ==========

class LLMConfigError(RuntimeError):
    """LLM 配置错误（如缺少 API Key）"""


class LLMRequestError(RuntimeError):
    """LLM 请求过程中的错误（网络、解析等）"""


# ========== 主服务类 ==========

class LLMService:
    """大模型服务类"""

    DEFAULT_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        初始化 LLM 服务。

        Args:
            api_key: API 密钥，优先级：参数 > 环境变量 GLM_API_KEY。
                     若都未提供，抛出 LLMConfigError。
            api_url: API 端点，默认使用智谱官方端点。
            model: 模型名称，默认使用 :data:`GLM_DEFAULT_MODEL`。
        """
        # 主动加载 .env，确保 nohup / systemd 启动也能读到 GLM_API_KEY
        load_dotenv()
        api_key = api_key or os.getenv("GLM_API_KEY")
        if not api_key:
            raise LLMConfigError(
                "缺少 GLM API Key。请在 .env 文件中设置 GLM_API_KEY 或通过环境变量传入。"
            )

        self.api_key = api_key
        self.api_url = api_url or self.DEFAULT_API_URL
        self.model = model or os.getenv("GLM_MODEL", GLM_DEFAULT_MODEL)
        logger.info("LLMService 已初始化，model=%s", self.model)

    # ---------- 核心请求 ----------

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = GLM_DEFAULT_TEMPERATURE,
        max_tokens: int = GLM_MAX_TOKENS_CHAT,
    ) -> Dict[str, Any]:
        """
        发送聊天请求。

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}, ...]
            temperature: 温度参数（0-2），控制随机性
            max_tokens: 最大输出 token 数

        Returns:
            成功：原始 API 响应 dict（含 choices 字段）
            失败：{"error": str, "status_code": int (可选)}
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=GLM_API_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout:
            logger.warning("LLM 请求超时（%ds）", GLM_API_TIMEOUT_SECONDS)
            return {"error": f"请求超时（{GLM_API_TIMEOUT_SECONDS}s）"}
        except requests.exceptions.RequestException as e:
            logger.warning("LLM 网络异常: %s", e)
            return {"error": f"网络请求异常: {e}"}

        if response.status_code != 200:
            logger.warning(
                "LLM API 返回非 200: status=%s, body=%s",
                response.status_code,
                response.text[:200],
            )
            return {
                "error": f"API 请求失败: {response.status_code}",
                "status_code": response.status_code,
                "response": response.text,
            }

        try:
            return response.json()
        except ValueError as e:
            logger.exception("LLM 响应 JSON 解析失败")
            return {"error": f"响应 JSON 解析失败: {e}"}

    # ---------- 高层封装 ----------

    def analyze_word(self, word: str) -> Dict[str, Any]:
        """分析单词的语义和用法"""
        prompt = f"""请分析单词 '{word}' 的语义和用法：

1. 提供中文释义
2. 提供英文释义
3. 说明词性（如：名词、动词、形容词等）
4. 提供发音（国际音标）
5. 给出 3-5 个例句（中英文对照）
6. 说明单词的常用程度或频率

请用简洁清晰的语言回答。"""
        result = self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=GLM_MAX_TOKENS_ANALYZE,
        )
        if "error" not in result:
            result["word"] = word
        return result

    def generate_relations(
        self,
        word: str,
        relation_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        为单词生成关系网络。

        Args:
            word: 单词
            relation_types: 关系类型子集，默认覆盖 :data:`RELATION_TYPES` 全部

        Returns:
            成功：{relation_type: [word_list]}
            失败：{"error": str, ...}
        """
        types = relation_types or list(RELATION_TYPES)
        prompt = f"""为单词 '{word}' 生成以下关系（每个类型 3-5 个）：

        1. 近义词 (synonym)
        2. 反义词 (antonym)
        3. 相关词 (related) - 在主题或场景上相关
        4. 同音词 (homophone) - 发音相同或相似
        5. 词族词 (family) - 词形变化（如动词变名词）

        请以 JSON 格式返回，格式如下：
        {{
            "synonym": ["word1", "word2", ...],
            "antonym": ["word1", "word2", ...],
            "related": ["word1", "word2", ...],
            "homophone": ["word1"],
            "family": ["word1", "word2", ...]
        }}

        只返回 JSON，不要包含其他文字。"""
        result = self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=GLM_MAX_TOKENS_RELATIONS,
        )

        if "error" in result or "choices" not in result:
            return result

        content = result["choices"][0]["message"]["content"].strip()
        parsed = self._extract_json(content)
        if isinstance(parsed, dict):
            # 仅保留请求的关系类型
            return {k: v for k, v in parsed.items() if k in types}

        logger.warning("关系 JSON 解析失败，原始内容: %s", content[:200])
        return {
            "error": "无法解析返回的 JSON 数据",
            "raw_content": content,
        }

    @staticmethod
    def _extract_json(content: str) -> Any:
        """
        从可能含前后文字的内容中提取首个 JSON 对象。

        Args:
            content: LLM 原始输出

        Returns:
            解析后的 dict / list，解析失败返回 None
        """
        # 优先尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 退化为子串截取（首个 { 到末尾 }）
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            candidate = content[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 尝试去除 markdown 代码块
                cleaned = re.sub(r"```(?:json)?\s*", "", candidate)
                cleaned = cleaned.replace("```", "")
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    return None
        return None

    def generate_example_sentences(self, word: str, count: int = 5) -> Dict[str, Any]:
        """生成单词的例句"""
        prompt = f"""为单词 '{word}' 生成 {count} 个英文例句，每个例句后附中文翻译。

        要求：
        1. 例句要多样化，涵盖不同的语境
        2. 翻译要准确自然
        3. 每个例句格式：英文句号 | 中文翻译

        只返回例句列表，不要包含其他文字。"""
        result = self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=GLM_MAX_TOKENS_EXAMPLES,
        )
        if "error" not in result:
            result["word"] = word
        return result

    def chat_with_history(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = GLM_DEFAULT_TEMPERATURE,
        max_tokens: int = GLM_MAX_TOKENS_CHAT,
    ) -> Dict[str, Any]:
        """带历史对话的聊天"""
        messages = list(history or [])
        messages.append({"role": "user", "content": message})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    def get_available_models(self) -> Dict[str, Any]:
        """询问 LLM 列出可用模型（结果可能不完整，仅作参考）"""
        prompt = "请列出智谱 AI 当前可用的所有模型，包括模型名称和简短描述。"
        return self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=GLM_MAX_TOKENS_ANALYZE,
        )


# ========== 全局单例 ==========

_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """获取全局 LLM 服务实例（懒加载）"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def reset_llm_service() -> None:
    """重置全局实例（仅用于测试）"""
    global _llm_service
    _llm_service = None


# ========== 命令行调试入口 ==========

if __name__ == "__main__":
    import sys

    _DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=_DEFAULT_FORMAT)

    try:
        llm = LLMService()
    except LLMConfigError as e:
        print(f"❌ {e}")
        sys.exit(1)

    print("\n=== 测试 1: 单词分析 ===")
    result = llm.analyze_word("happy")
    if "error" not in result:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 单词分析成功\n{content[:200]}")
    else:
        print(f"❌ {result.get('error')}")

    print("\n=== 测试 2: 生成关系 ===")
    result = llm.generate_relations("happy")
    if "error" not in result:
        print(f"✅ 关系生成成功\n{json.dumps(result, indent=2, ensure_ascii=False)}")
    else:
        print(f"❌ {result.get('error')}")

    print("\n=== 测试 3: 生成例句 ===")
    result = llm.generate_example_sentences("run", count=3)
    if "error" not in result:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 例句生成成功\n{content[:300]}")
    else:
        print(f"❌ {result.get('error')}")
