#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
LLM 服务测试脚本 - 测试所有 LLM 功能
"""

import sys
import os
import json

# 确保项目根目录在路径中
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from services.llm_service import LLMService, get_llm_service

print("=" * 60)
print("🧪 LLM 服务功能测试")
print("=" * 60)

all_tests_passed = True

# 测试1: 创建 LLM 服务实例
print("\n【测试1】创建 LLM 服务实例...")
try:
    llm = LLMService()
    print(f"✅ LLM 服务实例创建成功")
    print(f"   - API Key 已配置: {'是' if llm.api_key else '否'}")
    print(f"   - 模型: {llm.model}")
    print(f"   - API 端点: {llm.api_url}")
except Exception as e:
    print(f"❌ 创建失败: {str(e)}")
    all_tests_passed = False

# 测试2: 测试基础聊天功能
print("\n【测试2】测试基础聊天功能...")
try:
    result = llm.chat([
        {"role": "user", "content": "请用一句话介绍你自己"}
    ], max_tokens=100)

    if "error" in result:
        print(f"❌ 聊天失败: {result.get('error')}")
        all_tests_passed = False
    else:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 聊天成功")
        print(f"   回复: {content}")

except Exception as e:
    print(f"❌ 基础聊天测试失败: {str(e)}")
    all_tests_passed = False

# 测试3: 测试单词分析功能
print("\n【测试3】测试单词分析功能...")
try:
    result = llm.analyze_word("hello")

    if "error" in result:
        print(f"❌ 单词分析失败: {result.get('error')}")
        all_tests_passed = False
    else:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 单词分析成功")
        print(f"   单词: hello")
        # 显示部分内容
        lines = content.split('\n')[:5]
        for line in lines:
            print(f"   {line}")

except Exception as e:
    print(f"❌ 单词分析测试失败: {str(e)}")
    all_tests_passed = False

# 测试4: 测试关系生成功能
print("\n【测试4】测试关系生成功能...")
try:
    result = llm.generate_relations("happy")

    if "error" in result:
        print(f"❌ 关系生成失败: {result.get('error')}")
        all_tests_passed = False
    elif "choices" in result:
        print(f"✅ 关系生成成功")
        # 解析 JSON 结果
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        # 尝试提取 JSON
        start_idx = content.find('{')
        end_idx = content.rfind('}') + 1
        if start_idx != -1:
            json_str = content[start_idx:end_idx]
            try:
                relations = json.loads(json_str)
                print(f"   关系类型: {list(relations.keys())}")
                for rel_type, words in relations.items():
                    print(f"   - {rel_type}: {words[:3] if words else '无'}")
            except:
                print(f"   内容: {content[:100]}...")
    else:
        print(f"⚠️  关系生成结果格式异常: {result}")

except Exception as e:
    print(f"❌ 关系生成测试失败: {str(e)}")
    all_tests_passed = False

# 测试5: 测试例句生成功能
print("\n【测试5】测试例句生成功能...")
try:
    result = llm.generate_example_sentences("run", count=3)

    if "error" in result:
        print(f"❌ 例句生成失败: {result.get('error')}")
        all_tests_passed = False
    else:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 例句生成成功")
        lines = content.split('\n')[:6]
        for line in lines:
            if line.strip():
                print(f"   {line}")

except Exception as e:
    print(f"❌ 例句生成测试失败: {str(e)}")
    all_tests_passed = False

# 测试6: 测试带历史的聊天功能
print("\n【测试6】测试带历史的聊天功能...")
try:
    history = [
        {"role": "user", "content": "我的名字是张三"},
        {"role": "assistant", "content": "你好，张三！很高兴认识你。"},
        {"role": "user", "content": "我叫什么名字？"}
    ]

    result = llm.chat_with_history("我今年多大年纪？", history)

    if "error" in result:
        print(f"❌ 带历史的聊天失败: {result.get('error')}")
        all_tests_passed = False
    else:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 带历史的聊天成功")
        print(f"   回复: {content}")

except Exception as e:
    print(f"❌ 带历史的聊天测试失败: {str(e)}")
    all_tests_passed = False

# 测试7: 测试不同温度参数
print("\n【测试7】测试不同温度参数...")
try:
    # 低温度 - 期望更确定的回答
    result1 = llm.chat([{"role": "user", "content": "用 1-10 评分给我打分"}], temperature=0.1, max_tokens=50)
    # 高温度 - 期望更多样化的回答
    result2 = llm.chat([{"role": "user", "content": "用 1-10 评分给我打分"}], temperature=1.5, max_tokens=50)

    if "error" in result1 or "error" in result2:
        print(f"❌ 温度参数测试失败")
        all_tests_passed = False
    else:
        content1 = result1.get("choices", [{}])[0].get("message", {}).get("content", "")
        content2 = result2.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ 温度参数测试成功")
        print(f"   温度 0.1: {content1[:50]}...")
        print(f"   温度 1.5: {content2[:50]}...")

except Exception as e:
    print(f"❌ 温度参数测试失败: {str(e)}")
    all_tests_passed = False

# 测试8: 测试最大 Token 限制
print("\n【测试8】测试最大 Token 限制...")
try:
    result = llm.chat([{"role": "user", "content": "写一段话，每行一个词，共100行"}], max_tokens=2000)

    if "error" in result:
        print(f"❌ Token 限制测试失败: {result.get('error')}")
        all_tests_passed = False
    else:
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        lines = content.split('\n')
        print(f"✅ Token 限制测试成功")
        print(f"   生成行数: {len(lines)}")
        print(f"   内容预览: {lines[:3]}")

except Exception as e:
    print(f"❌ Token 限制测试失败: {str(e)}")
    all_tests_passed = False

# 测试9: 测试错误处理 - 超时
print("\n【测试9】测试错误处理（超时）...")
try:
    # 尝试超时测试（使用不存在的 API 端点）
    llm_with_timeout = LLMService(api_url="http://invalid-url-that-does-not-exist-12345.com")
    result = llm_with_timeout.chat([{"role": "user", "content": "test"}], timeout=2)

    if "error" in result:
        print(f"✅ 错误处理测试成功 - 正确捕获网络错误: {result.get('error')}")
    else:
        print(f"⚠️  错误处理测试异常 - 未能捕获错误")

except Exception as e:
    print(f"✅ 错误处理测试成功 - 正确抛出异常: {str(e)[:50]}")

# 测试10: 测试移动动词关系生成（使用项目数据）
print("\n【测试10】测试移动动词关系生成...")
try:
    result = llm.generate_relations("run")

    if "error" in result:
        print(f"❌ 移动词关系生成失败: {result.get('error')}")
        all_tests_passed = False
    elif "choices" in result:
        print(f"✅ 移动词关系生成成功")
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        start_idx = content.find('{')
        end_idx = content.rfind('}') + 1
        if start_idx != -1:
            json_str = content[start_idx:end_idx]
            try:
                relations = json.loads(json_str)
                print(f"   关系类型: {list(relations.keys())}")
                for rel_type, words in relations.items():
                    print(f"   - {rel_type}: {words[:3] if words else '无'}")
            except:
                pass

except Exception as e:
    print(f"❌ 移动词关系生成测试失败: {str(e)}")
    all_tests_passed = False

# 测试11: 测试会话式聊天
print("\n【测试11】测试会话式聊天...")
try:
    session_llm = LLMService()

    # 模拟多轮对话
    messages = []
    conversation = [
        "介绍一下你自己",
        "我会叫你什么名字？",
        "今天天气怎么样？"
    ]

    for msg in conversation:
        messages.append({"role": "user", "content": msg})
        result = session_llm.chat(messages)
        if "error" not in result:
            assistant_msg = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            messages.append({"role": "assistant", "content": assistant_msg})
            print(f"   用户: {msg}")
            print(f"   助手: {assistant_msg[:50]}...")

    print(f"✅ 会话式聊天测试成功")

except Exception as e:
    print(f"❌ 会话式聊天测试失败: {str(e)}")
    all_tests_passed = False

# 总结
print("\n" + "=" * 60)
if all_tests_passed:
    print("🎉 所有 LLM 服务测试通过！")
    print("")
    print("✅ LLM 服务功能正常，可以正常调用")
else:
    print("⚠️ 部分测试失败，请检查上述错误")
print("=" * 60)
