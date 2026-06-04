#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
测试 LLM 服务模块（不使用代理）
"""

import os
import sys

# 禁用代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

# 导入服务
from services.llm_service import LLMService
import json


def test_llm_service():
    """测试 LLM 服务"""
    llm = LLMService()

    print("=" * 60)
    print("🚀 LLM 服务模块测试")
    print("=" * 60)

    # 测试 1: 单词分析
    print("\n【测试 1】单词分析")
    print("-" * 60)
    result = llm.analyze_word("happy")
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        print(f"✅ 分析成功")
        print(content)

    # 测试 2: 生成关系
    print("\n【测试 2】生成关系")
    print("-" * 60)
    result = llm.generate_relations("happy")
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        print(f"✅ 关系生成成功:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # 测试 3: 生成例句
    print("\n【测试 3】生成例句")
    print("-" * 60)
    result = llm.generate_example_sentences("run", count=3)
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        print(f"✅ 例句生成成功:")
        print(content)

    # 测试 4: 简单对话
    print("\n【测试 4】简单对话")
    print("-" * 60)
    result = llm.chat([{"role": "user", "content": "用一句话解释什么是知识图谱"}])
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        print(f"✅ 回复成功:")
        print(content)

    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_llm_service()
