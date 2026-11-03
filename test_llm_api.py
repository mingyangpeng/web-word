#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
测试智谱 AI GLM-4.7-Flash API 调用（标准格式）
"""

import requests
import json

API_KEY = "bbc997fb45264cac9333323b2f94ac79.brADNBLmFHaqMXbQ"

# 智谱 AI 标准聊天接口
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

def test_llm():
    """测试 GLM API 调用"""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    # 标准智谱 Chat Completions 格式
    payload = {
        "model": "glm-4-flash",
        "messages": [
            {
                "role": "user",
                "content": "你好！请用简体中文介绍你自己，并计算 15 + 27 等于多少？"
            }
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }

    print(f"📡 请求 URL: {API_URL}")
    print(f"🔑 模型: glm-4-flash")
    print(f"📝 请求内容: {payload['messages'][0]['content']}")
    print("-" * 60)

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        print(f"📊 状态码: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print("\n✅ 请求成功！")
            print("-" * 60)

            print("📥 完整响应:")
            print(json.dumps(result, indent=2, ensure_ascii=False))

            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0].get('message', {}).get('content', '')
                print("\n🤖 助手回复:")
                print("-" * 60)
                print(content)

            return True
        else:
            print(f"\n❌ 请求失败!")
            print(f"错误响应: {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("\n❌ 请求超时！网络连接可能有问题。")
        print("可能原因:")
        print("  1. 代理设置阻止了 HTTPS 连接")
        print("  2. 网络连接不稳定")
        print("  3. API 服务暂时不可用")
        return False
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 智谱 AI GLM-4.Flash API 测试")
    print("=" * 60)

    success = test_llm()

    print("\n" + "=" * 60)
    if success:
        print("✅ API 调用正常！")
    else:
        print("❌ 测试失败。")
    print("=" * 60)
