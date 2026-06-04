#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
简单测试：直接运行 Streamlit 页面
"""

import sys
import os
import subprocess
import time
import requests
import signal

print("=" * 60)
print("📋 单词知识图谱应用 - 简单测试")
print("=" * 60)

# 测试数据库连接
print("\n【1/3】测试数据库连接...")
try:
    from data.word_database import DatabaseManager
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM words")
    count = cursor.fetchone()[0]
    print(f"✅ 数据库连接成功！单词总数: {count}")
    cursor.close()
    db.close_connection()
except Exception as e:
    print(f"❌ 数据库连接失败: {e}")

# 测试 LLM 服务
print("\n【2/3】测试 LLM 服务...")
try:
    from services.llm_service import LLMService
    llm = LLMService()
    result = llm.analyze_word("hello")
    if "error" in result:
        print(f"❌ LLM 服务失败: {result.get('error')}")
    else:
        print(f"✅ LLM 服务正常工作！")
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"   示例回复: {content[:80]}...")
except Exception as e:
    print(f"❌ LLM 服务测试失败: {e}")

# 测试应用访问
print("\n【3/3】测试应用访问...")
try:
    response = requests.get('http://localhost:8501/', timeout=5)
    if response.status_code == 200:
        print(f"✅ 应用访问正常！")
        print(f"   访问地址: http://localhost:8501")
    else:
        print(f"❌ 应用访问异常: HTTP {response.status_code}")
except Exception as e:
    print(f"❌ 应用访问失败: {e}")

print("\n" + "=" * 60)
print("✅ 测试完成！应用已启动并运行正常。")
print("请在浏览器中打开: http://localhost:8501")
print("=" * 60)

# 保持运行
try:
    while True:
        time.sleep(10)
except KeyboardInterrupt:
    print("\n停止应用...")
    subprocess.run(['pkill', '-f', 'streamlit run app.py'], capture_output=True)
    print("✅ 应用已停止")
